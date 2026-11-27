from concurrent.futures import ThreadPoolExecutor
import json
import re
from typing import Any
from crewai import Agent, Crew, Process, Task

from src.agents.llm_factory import criar_llm, resolver_config
from src.agents.retry import executar_crew_com_retry

CRITERIOS_TEC_SINGLE = (
    "fidelidade_manual",
    "ausencia_alucinacao",
    "citacao_fonte",
    "coerencia_escalonamento",
    "aderencia_escopo",
)

CRITERIOS_CLI_SINGLE = (
    "empatia_tom",
    "clareza_passos",
    "utilidade_pratica",
    "sem_jargao_interno",
    "satisfacao_geral",
)

CRITERIOS_TEC_MULTI = (
    "memoria_isolamento",
    "nao_repeticao_n1",
    "ausencia_alucinacao",
    "timing_escalonamento",
    "qualidade_handoff",
)

CRITERIOS_CLI_MULTI = (
    "empatia_tom",
    "sensacao_de_ser_ouvido",
    "clareza_conducao",
    "sem_jargao_interno",
    "satisfacao_geral",
)

DEFAULT_TECH_JUDGE = {
    "model": "nvidia/nemotron-3-ultra-550b-a55b",
    "enable_thinking": True,
    "max_tokens": 4096,
    "timeout": 90,
}

DEFAULT_CLIENT_JUDGE = {
    "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "enable_thinking": False,
    "max_tokens": 2048,
    "timeout": 45,
}


def _rodar_agente_json(llm, role: str, backstory: str, prompt: str) -> str:
    agente = Agent(
        role=role,
        goal="Avaliar atendimento com rigor e retornar apenas JSON válido.",
        backstory=backstory,
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    task = Task(description=prompt, expected_output="JSON válido com justificativa e notas de 0 a 2.", agent=agente)
    crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
    executar_crew_com_retry(crew, max_tentativas=3, espera_s=2.0)
    return task.output.raw


def _parsear_nota(raw: str, criterios: tuple[str, ...]) -> dict[str, Any]:
    texto = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", texto, flags=re.DOTALL)

    dados: dict[str, Any] = {}
    if match:
        try:
            dados = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    notas: dict[str, int] = {}
    for c in criterios:
        val = dados.get(c, 0)
        notas[c] = max(0, min(2, int(val))) if isinstance(val, (int, float)) or str(val).isdigit() else 0

    return {
        "score_total": sum(notas.values()),
        "criteria": notas,
        "reasoning": str(dados.get("justificativa", "Sem justificativa.")),
    }


class AvaliadorDuplo:
    """Executa Juiz Técnico e Juiz Cliente em paralelo."""

    def __init__(
        self,
        tech_spec: str | dict[str, Any] = DEFAULT_TECH_JUDGE,
        client_spec: str | dict[str, Any] = DEFAULT_CLIENT_JUDGE,
    ):
        cfg_tec = resolver_config(tech_spec, temperature=0.0)
        cfg_cli = resolver_config(client_spec, temperature=0.0)
        self.tech_model_name = cfg_tec.model
        self.client_model_name = cfg_cli.model
        self.llm_tech = criar_llm(cfg_tec)
        self.llm_client = criar_llm(cfg_cli)

    def avaliar_single(
        self,
        pergunta: str,
        resposta_cliente: str,
        fonte_citada: str,
        conteudo_chunk: str,
        expected_escalation: bool,
        predicted_escalation: bool,
    ) -> dict[str, Any]:
        prompt_tec = f"""Avalie tecnicamente a resposta de suporte N1 (0, 1 ou 2 pontos por critério):
1. fidelidade_manual: Segue os passos exatos do manual base sem omitir instruções críticas?
2. ausencia_alucinacao: Inventou menus, prazos, valores ou regras fora do manual? (2=zero alucinação)
3. citacao_fonte: Avalie EXCLUSIVAMENTE FONTE_EXTRAIDA abaixo (a tag interna é removida antes de enviar ao cliente; NÃO penalize sua ausência no texto final). (2=corresponde ao manual ou FORA_DE_ESCOPO correto, 0=NÃO_CITADA ou errada)
4. coerencia_escalonamento: Decisão (previsto={predicted_escalation}, esperado={expected_escalation}) está correta?
5. aderencia_escopo: Respeitou os limites do N1 sem improvisar soluções fora da base?

PERGUNTA: {pergunta}
MANUAL BASE: {conteudo_chunk or "FORA DE ESCOPO"}
FONTE_EXTRAIDA: {fonte_citada}
RESPOSTA ENVIADA: {resposta_cliente}

Responda APENAS JSON válido:
{{"justificativa": "até 2 frases", "fidelidade_manual": 0, "ausencia_alucinacao": 0, "citacao_fonte": 0, "coerencia_escalonamento": 0, "aderencia_escopo": 0}}"""

        prompt_cli = f"""Você é o cliente real que enviou a dúvida abaixo e recebeu essa resposta do suporte. Avalie sua experiência (0, 1 ou 2 pontos por critério):
1. empatia_tom: O atendente foi educado, humano e acolhedor com o seu problema?
2. clareza_passos: As orientações são fáceis de entender e executar sem confusão?
3. utilidade_pratica: A resposta realmente ajuda a avançar na solução ou encaminha bem o caso?
4. sem_jargao_interno: A mensagem evitou códigos internos, tags técnicas ou termos de bastidor (ex: N1, N2, chunk, RAG)?
5. satisfacao_geral: Como cliente, você ficaria satisfeito com esse atendimento?

SUA PERGUNTA: {pergunta}
RESPOSTA RECEBIDA: {resposta_cliente}

Responda APENAS JSON válido:
{{"justificativa": "até 2 frases na visão do cliente", "empatia_tom": 0, "clareza_passos": 0, "utilidade_pratica": 0, "sem_jargao_interno": 0, "satisfacao_geral": 0}}"""

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_tec = pool.submit(
                _rodar_agente_json, self.llm_tech, "Auditor Técnico de QA",
                "Especialista sênior em auditoria de sistemas RAG B2B.", prompt_tec
            )
            fut_cli = pool.submit(
                _rodar_agente_json, self.llm_client, "Cliente Avaliador CSAT",
                "Usuário de software empresarial avaliando a qualidade do atendimento recebido.", prompt_cli
            )
            res_tec = _parsear_nota(fut_tec.result(), CRITERIOS_TEC_SINGLE)
            res_cli = _parsear_nota(fut_cli.result(), CRITERIOS_CLI_SINGLE)

        return {"tech": res_tec, "client": res_cli}

    def avaliar_multiturn(
        self,
        descricao_cenario: str,
        transcricao: str,
        expected_escalation: bool,
        final_escalated: bool,
        handoff_summary: str = "",
    ) -> dict[str, Any]:
        prompt_tec = f"""Avalie tecnicamente a conversa multi-turno (0, 1 ou 2 pontos por critério):
1. memoria_isolamento: Manteve o contexto do assunto e isolou corretamente trocas de tópico?
2. nao_repeticao_n1: Evitou repetir passos N1 que o cliente já afirmou ter feito?
3. ausencia_alucinacao: Manteve procedimentos plausíveis sem inventar políticas ou prazos?
4. timing_escalonamento: Escalou no momento certo? (esperado={expected_escalation}, ocorreu={final_escalated})
5. qualidade_handoff: Se houve escalonamento, o resumo N2 é útil e completo? (Se esperado=False e ocorreu=False, dê 2 pontos).

CENÁRIO: {descricao_cenario}
TRANSCRIÇÃO:
{transcricao}
RESUMO HANDOFF N2: {handoff_summary or "Não houve escalonamento"}

Responda APENAS JSON válido:
{{"justificativa": "até 2 frases", "memoria_isolamento": 0, "nao_repeticao_n1": 0, "ausencia_alucinacao": 0, "timing_escalonamento": 0, "qualidade_handoff": 0}}"""

        prompt_cli = f"""Você é o cliente desta conversa de chat com o suporte. Avalie sua experiência geral do início ao fim (0, 1 ou 2 pontos por critério):
1. empatia_tom: Atendimento educado, paciente e natural ao longo dos turnos?
2. sensacao_de_ser_ouvido: O atendente lembrou do que você já disse sem te obrigar a repetir informações?
3. clareza_conducao: As respostas e transições de assunto foram fáceis de acompanhar?
4. sem_jargao_interno: Evitou códigos internos ou termos técnicos de bastidor (N1/N2/RAG/chunk)?
5. satisfacao_geral: Você sairia satisfeito com o desenrolar deste atendimento?

TRANSCRIÇÃO DO CHAT:
{transcricao}

Responda APENAS JSON válido:
{{"justificativa": "até 2 frases na visão do cliente", "empatia_tom": 0, "sensacao_de_ser_ouvido": 0, "clareza_conducao": 0, "sem_jargao_interno": 0, "satisfacao_geral": 0}}"""

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_tec = pool.submit(
                _rodar_agente_json, self.llm_tech, "Auditor Técnico Multi-Turno",
                "Especialista sênior em QA de agentes conversacionais com memória.", prompt_tec
            )
            fut_cli = pool.submit(
                _rodar_agente_json, self.llm_client, "Cliente Avaliador CSAT",
                "Cliente B2B avaliando a fluidez e satisfação de um atendimento por chat.", prompt_cli
            )
            res_tec = _parsear_nota(fut_tec.result(), CRITERIOS_TEC_MULTI)
            res_cli = _parsear_nota(fut_cli.result(), CRITERIOS_CLI_MULTI)

        return {"tech": res_tec, "client": res_cli}