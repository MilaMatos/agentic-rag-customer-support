import argparse
import time
from typing import Any
from uuid import uuid4

from crewai import Agent, Crew, Process, Task
from sqlalchemy import select

from src.agents.llm_factory import criar_llm
from src.agents.retry import executar_crew_com_retry
from src.agents.schemas import ConfirmacaoHumanaSchema
from src.db.connection import SessionLocal, criar_tabelas
from src.db.models import EvalMultiTurnResultDB
from src.eval.judge import AvaliadorDuplo, DEFAULT_TECH_JUDGE
from src.eval.presets import PRESETS_MODELOS
from src.pipeline_agents import NexusSupportPipeline

import logging
from src.agents.retry import aguardar_conexao

logging.disable(logging.ERROR)


CENARIOS_MULTITURN: list[dict[str, Any]] = [
    {
        "scenario_id": "MT-TECH-01",
        "categoria": "Technical",
        "descricao": "Dashboard travado; cliente testa passos N1 e persiste > 20 min -> deve escalar para um especialista.",
        "mensagem_inicial": "Meu painel principal não carrega os relatórios, fica só uma bolinha girando.",
        "instrucao_cliente": (
            "Você está usando Google Chrome. Se o atendente pedir para limpar cache, desativar VPN ou Ctrl+F5, "
            "responda de forma curta que já fez tudo isso e o painel continua travado há mais de 30 minutos. "
            "Quando ele confirmar que encaminhou para o especialista, encerre agradecendo com [ENCERRAR]."
        ),
        "expected_escalation": True,
        "max_turnos": 4,
    },
    {
        "scenario_id": "MT-BILL-01",
        "categoria": "Billing",
        "descricao": "Cartão rejeitado ao atualizar pagamento mesmo liberado pelo banco -> deve escalar para um especialista.",
        "mensagem_inicial": "Não consigo atualizar meu cartão Visa no painel, dá erro de pagamento.",
        "instrucao_cliente": (
            "Na segunda mensagem diga que já conferiu os dados e acabou de ligar no banco, e o banco garantiu "
            "que o cartão está liberado sem bloqueio. Se encaminharem para especialista/financeiro, finalize com [ENCERRAR]."
        ),
        "expected_escalation": True,
        "max_turnos": 4,
    },
    {
        "scenario_id": "MT-ACCO-01",
        "categoria": "Account",
        "descricao": "Perda de dispositivo 2FA sem códigos de backup -> deve escalar para um especialista.",
        "mensagem_inicial": "Preciso trocar meu e-mail, mas o autenticador 2FA estava no meu celular antigo que quebrou.",
        "instrucao_cliente": (
            "Se o atendente perguntar sobre códigos de recuperação ou acesso ao app antigo, responda de forma curta "
            "que não tem mais os códigos de backup nem o aparelho. Quando encaminharem para um especialista, finalize com [ENCERRAR]."
        ),
        "expected_escalation": True,
        "max_turnos": 4,
    },
    {
        "scenario_id": "MT-FRAU-01",
        "categoria": "Fraud",
        "descricao": "Conta invadida; botão de bloqueio não aparece mesmo com e-mail validado -> deve escalar para especialista.",
        "mensagem_inicial": "Acho que invadiram minha conta, tem transações que eu não reconheço!",
        "instrucao_cliente": (
            "Se o atendente passar passos para bloquear no painel, diga que tentou seguir mas o botão de bloqueio "
            "não aparece mesmo com seu e-mail já validado. Quando encaminharem para segurança/N2, finalize com [ENCERRAR]."
        ),
        "expected_escalation": True,
        "max_turnos": 4,
    },
    {
        "scenario_id": "MT-GENE-01",
        "categoria": "General Inquiry",
        "descricao": "Dúvida sobre desconto para ONG e como solicitar -> resolução 100% N1 sem escalar para especialista.",
        "mensagem_inicial": "Somos uma ONG sem fins lucrativos, vocês oferecem desconto nos planos?",
        "instrucao_cliente": (
            "Se o atendente responder sobre o desconto, faça apenas 1 pergunta curta complementar sobre como enviar "
            "a comprovação ou sobre os planos para equipes. Depois da segunda resposta útil, agradeça e encerre com [ENCERRAR]."
        ),
        "expected_escalation": False,
        "max_turnos": 3,
    },
    {
        "scenario_id": "MT-SWITCH-01",
        "categoria": "Technical",
        "descricao": "Troca e retorno de tópico (Technical -> Billing -> Technical) validando memória intra-sessão.",
        "mensagem_inicial": "Meu painel principal não carrega os dados, fica só girando.",
        "instrucao_cliente": (
            "Turno 2: diga que vai testar depois, mas pergunte rapidamente sobre uma cobrança duplicada na sua fatura deste mês. "
            "Turno 3: diga 'Voltando ao problema do painel, já limpei o cache no Chrome e desativei a VPN e continua travado há 30 minutos'. "
            "Quando encaminharem para um especialista, finalize com [ENCERRAR]."
        ),
        "expected_escalation": True,
        "max_turnos": 4,
    },
]


class ClienteSimuladorLLM:
    def __init__(self, model_spec: dict[str, Any] | str | None = None):
        spec = model_spec or {
            "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
            "enable_thinking": False,
            "max_tokens": 256,
            "timeout": 40,
        }
        self.llm = criar_llm(spec, temperature=0.2)

    def responder(self, instrucao_cliente: str, transcricao: str, turno_atual: int) -> str:
        prompt = (
            f"Você é um cliente real em um chat de suporte B2B (Turno {turno_atual}).\n"
            f"Seu roteiro: {instrucao_cliente}\n\n"
            f"Conversa até agora:\n{transcricao}\n\n"
            "Regras:\n"
            "- Escreva APENAS a próxima mensagem curta do cliente em português (1 a 2 frases), sem usar termos internos como N1 ou N2.\n"
            "- Só responda com [ENCERRAR] se o atendente JÁ tiver concluído sua dúvida ou confirmado o encaminhamento na última resposta dele.\n"
            "- Se você ainda estiver informando um problema, fazendo uma pergunta ou pedindo encaminhamento, NÃO inclua [ENCERRAR]."
        )
        agente = Agent(
            role="Cliente de Suporte",
            goal="Responder naturalmente seguindo o roteiro sem quebrar o personagem.",
            backstory="Usuário de ERP B2B conversando no chat de suporte.",
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )
        task = Task(description=prompt, expected_output="Mensagem curta do cliente.", agent=agente)
        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        executar_crew_com_retry(crew, max_tentativas=2, espera_s=1.5)
        return (task.output.raw or "").strip()


def _ja_executado(experiment_id: str, scenario_id: str, run_index: int) -> bool:
    with SessionLocal() as db:
        stmt = select(EvalMultiTurnResultDB.id).where(
            EvalMultiTurnResultDB.experiment_id == experiment_id,
            EvalMultiTurnResultDB.scenario_id == scenario_id,
            EvalMultiTurnResultDB.run_index == run_index,
        )
        return db.execute(stmt).scalar_one_or_none() is not None


def rodar_benchmark_multiturn(
    experiment_id: str,
    preset_name: str = "copilot_fast_thinking_off",
    repeticoes: int = 3,
    sleep_s: float = 2.0,
    judge_model: str | None = None,
) -> None:
    criar_tabelas()
    models_cfg = PRESETS_MODELOS[preset_name]
    pipeline = NexusSupportPipeline(model_config=models_cfg)
    cliente_sim = ClienteSimuladorLLM()
    juiz = AvaliadorDuplo(
        tech_spec={
            "model": judge_model,
            "enable_thinking": True,
            "max_tokens": 2048,
            "timeout": 90,
        }
        if judge_model
        else DEFAULT_TECH_JUDGE
    )

    total = len(CENARIOS_MULTITURN) * repeticoes
    atual = 0
    tenant_eval = f"eval_mt_{experiment_id}"

    try:
        for run_idx in range(1, repeticoes + 1):
            for cenario in CENARIOS_MULTITURN:
                scen_id = cenario["scenario_id"]
                atual += 1

                if _ja_executado(experiment_id, scen_id, run_idx):
                    print(f"[{atual}/{total}] SKIP {scen_id} (run {run_idx}) — checkpoint", flush=True)
                    continue

                try:
                    aguardar_conexao()
                    sid = f"MT-{experiment_id}-{scen_id}-R{run_idx}-{uuid4().hex[:5]}"
                    print(f"[{atual}/{total}] RUN  {scen_id} (run {run_idx}/{repeticoes})...", flush=True)

                    mensagem_cliente = cenario["mensagem_inicial"]
                    linhas_chat: list[str] = []
                    turnos_detalhe: list[dict[str, Any]] = []
                    latencias: list[float] = []
                    cache_hits = 0
                    escalou = False
                    handoff_summary = None

                    for turno in range(1, cenario["max_turnos"] + 1):
                        sug = pipeline.gerar_sugestao_db(
                            session_id=sid,
                            pergunta_cliente=mensagem_cliente,
                            tenant_id=tenant_eval,
                        )
                        caixa = sug.caixa_rastreabilidade
                        lat_turno = caixa.telemetria_tempos_s.get("total_pipeline_s", 0.0)
                        latencias.append(lat_turno)
                        if caixa.rag_contexto.reutilizado_do_cache:
                            cache_hits += 1

                        # N1 segue alerta do Auditor
                        acao = "ESCALADA_N2" if sug.alerta_escalonamento else "ACEITA_SEM_EDICAO"
                        res_conf = pipeline.confirmar_envio_db(
                            session_id=sid,
                            confirmacao=ConfirmacaoHumanaSchema(
                                suggestion_id=sug.suggestion_id,
                                acao_humana=acao,
                                mensagem_final_enviada=sug.mensagem_sugerida,
                            ),
                            tenant_id=tenant_eval,
                        )
                        pipeline.aguardar_background()

                        linhas_chat.append(f"[T{turno}] CLIENTE: {mensagem_cliente}")
                        linhas_chat.append(f"[T{turno}] ATENDENTE N1: {res_conf.mensagem_final_enviada}")
                        turnos_detalhe.append({
                            "turno": turno,
                            "categoria": caixa.triagem_inicial.category,
                            "is_followup": caixa.triagem_inicial.is_followup,
                            "chunk_id": caixa.rag_contexto.chunk_id,
                            "cache_hit": caixa.rag_contexto.reutilizado_do_cache,
                            "alerta_escalonamento": sug.alerta_escalonamento,
                            "latencia_s": lat_turno,
                        })

                        if res_conf.status_sessao == "ESCALADA_N2":
                            escalou = True
                            handoff_summary = res_conf.handoff_summary
                            break

                        if turno >= cenario["max_turnos"]:
                            break

                        prox = cliente_sim.responder(
                            instrucao_cliente=cenario["instrucao_cliente"],
                            transcricao="\n".join(linhas_chat),
                            turno_atual=turno + 1,
                        )
                        if "[ENCERRAR]" in prox:
                            prox = cliente_sim.responder(
                                instrucao_cliente=cenario["instrucao_cliente"],
                                transcricao="\n".join(linhas_chat),
                                turno_atual=turno + 1,
                            )
                            quer_encerrar = "[ENCERRAR]" in prox
                            prox_limpa = prox.replace("[ENCERRAR]", "").strip()

                            if quer_encerrar and not prox_limpa:
                                break
                            # Só encerra com despedida se não houver pergunta nem escalonamento pendente
                            if quer_encerrar and ("?" not in prox_limpa) and (escalou or not cenario["expected_escalation"]):
                                linhas_chat.append(f"[T{turno + 1}] CLIENTE: {prox_limpa}")
                                break

                            mensagem_cliente = prox_limpa or prox
                            time.sleep(0.5)

                    pipeline.encerrar_sessao_db(sid, tenant_id=tenant_eval)
                    transcricao = "\n".join(linhas_chat)

                    avaliacao = juiz.avaliar_multiturn(
                        descricao_cenario=cenario["descricao"],
                        transcricao=transcricao,
                        expected_escalation=cenario["expected_escalation"],
                        final_escalated=escalou,
                        handoff_summary=handoff_summary or "",
                    )

                    lat_total = round(sum(latencias), 3)
                    lat_media = round(lat_total / len(latencias), 3) if latencias else 0.0

                    registro = EvalMultiTurnResultDB(
                        experiment_id=experiment_id,
                        models_config=models_cfg,
                        scenario_id=scen_id,
                        categoria_principal=cenario["categoria"],
                        run_index=run_idx,
                        session_id=sid,
                        total_turnos=len(turnos_detalhe),
                        expected_escalation=cenario["expected_escalation"],
                        final_escalated=escalou,
                        escalation_match=(escalou == cenario["expected_escalation"]),
                        cache_hits=cache_hits,
                        latencia_media_turno_s=lat_media,
                        latencia_total_s=lat_total,
                        judge_model=juiz.tech_model_name,
                        judge_score_total=avaliacao["tech"]["score_total"],
                        judge_criteria=avaliacao["tech"]["criteria"],
                        judge_reasoning=avaliacao["tech"]["reasoning"],
                        client_judge_model=juiz.client_model_name,
                        client_score_total=avaliacao["client"]["score_total"],
                        client_criteria=avaliacao["client"]["criteria"],
                        client_reasoning=avaliacao["client"]["reasoning"],
                        transcricao=transcricao,
                        handoff_summary=handoff_summary,
                        turnos_detalhe=turnos_detalhe,
                    )
                    with SessionLocal() as db:
                        db.add(registro)
                        db.commit()

                    print(
                        f"   -> Turnos: {len(turnos_detalhe)} | Esc: {escalou} (OK={escalou == cenario['expected_escalation']}) | "
                        f"Cache: {cache_hits} | Tec: {avaliacao['tech']['score_total']}/10 | "
                        f"Cli: {avaliacao['client']['score_total']}/10 | Média/turno: {lat_media}s",
                        flush=True,
                    )
                    time.sleep(sleep_s)

                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    print(
                        f"   [FALHA] {scen_id} (run {run_idx}): {type(exc).__name__} — {str(exc)[:120]}",
                        flush=True,
                    )
                    aguardar_conexao()
                    time.sleep(5.0)
                    continue
    finally:
        pipeline.shutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark multi-turno com LLM cliente e checkpoint no PostgreSQL.")
    parser.add_argument("--exp", required=True, help="ID único do experimento")
    parser.add_argument("--preset", default="copilot_fast_thinking_off", choices=list(PRESETS_MODELOS.keys()))
    parser.add_argument("--runs", type=int, default=3, help="Repetições por cenário")
    parser.add_argument("--sleep", type=float, default=2.0, help="Pausa em segundos entre conversas")
    parser.add_argument("--judge", default=None, help="Override do modelo do Juiz")
    args = parser.parse_args()

    rodar_benchmark_multiturn(
        experiment_id=args.exp,
        preset_name=args.preset,
        repeticoes=args.runs,
        sleep_s=args.sleep,
        judge_model=args.judge,
    )