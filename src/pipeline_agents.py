import os

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from difflib import SequenceMatcher
from uuid import uuid4

from src.rag.retriever import NexusRetriever
from src.agents.agent_classifier import AgenteClassificador
from src.agents.agent_redactor import AgenteRedatorN1
from src.agents.agent_auditor import AgenteAuditorQualidade
from src.agents.agent_summarizer import AgenteResumo
from src.agents.memory import SessionMemory
from src.agents.schemas import (
    TicketClassification,
    ContextoRAGSchema,
    AtendimentoRedatorSchema,
    VereditoAuditorSchema,
    CaixaRastreabilidadeSchema,
    SugestaoCopilotoSchema,
    ConfirmacaoHumanaSchema,
    ResultadoConfirmacaoSchema,
)

MAX_TENTATIVAS_CORRECAO = 2
MIN_SIMILARITY = 0.30

ARQUIVO_TESTES = Path("data/evaluation/testes_e3.json")
PASTA_RASTREABILIDADE = Path("logs/rastreabilidade")
PASTA_RASTREABILIDADE.mkdir(parents=True, exist_ok=True)


class NexusSupportPipeline:
    """Orquestrador Multi-Agente RAG do NexusTech Support Copilot"""

    def __init__(self):
        self.retriever = NexusRetriever()
        self.classificador = AgenteClassificador()
        self.redator = AgenteRedatorN1()
        self.auditor = AgenteAuditorQualidade()
        self.resumidor = AgenteResumo()

    def _obter_classificacao(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
    ) -> TicketClassification:
        """Usa o dict externo (se fornecido para teste isolado) ou aciona o AgenteClassificador"""
        if classificacao_externa:
            return TicketClassification(
                category=classificacao_externa.get("category") or classificacao_externa.get("categoria", "General Inquiry"),
                priority=classificacao_externa.get("priority") or classificacao_externa.get("prioridade", "Media"),
                initial_level=classificacao_externa.get("initial_level") or classificacao_externa.get("nivel_inicial", "N1"),
                triage_justification=classificacao_externa.get("triage_justification") or classificacao_externa.get("justificativa_triagem", ""),
            )
        return self.classificador.executar(pergunta_cliente=pergunta_cliente)

    def processar_ticket(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
        gerar_resumo: bool = True,
        ticket_id: Optional[str] = None,
    ) -> CaixaRastreabilidadeSchema:
        """Executa o fluxo completo do ticket e retorna a Caixa de Rastreabilidade"""
        t_inicio_total = time.time()
        id_exec = ticket_id or f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 1. Agente 1: Triagem e Classificação
        t0 = time.time()
        triagem = self._obter_classificacao(pergunta_cliente, classificacao_externa)
        tempo_classificacao = round(time.time() - t0, 3)

        # 2. Busca Semântica Fatiada no PGVector
        t1 = time.time()
        chunks = self.retriever.buscar_chunks(
            query=pergunta_cliente,
            k=1,
            category_filter=triagem.category,
            min_similarity=MIN_SIMILARITY,
        )
        tempo_rag = round(time.time() - t1, 3)

        chunk_top1 = chunks[0] if chunks else {}
        rag_trace = ContextoRAGSchema(
            chunk_id=chunk_top1.get("chunk_id", "FORA_DE_ESCOPO"),
            subcategoria=chunk_top1.get("subcategory", "N/A"),
            score_similaridade=chunk_top1.get("similarity_score", 0.0),
            regra_escalonamento_aplicada=chunk_top1.get("fatias", {}).get(
                "escalonamento", "Escalonar para N2 por ausência de cobertura."
            ),
        )

        # 3. Agentes 2 e 3: Redator <-> Auditor com Loop de Autocorreção
        t2 = time.time()
        feedback = None
        dados_redator: dict[str, str] = {}
        veredito: Optional[VereditoAuditorSchema] = None
        tentativas_realizadas = 0

        for tentativa in range(1, MAX_TENTATIVAS_CORRECAO + 2):
            tentativas_realizadas = tentativa
            dados_redator = self.redator.executar(
                pergunta_cliente=pergunta_cliente,
                chunks=chunks,
                feedback_anterior=feedback,
            )
            veredito = self.auditor.executar(
                pergunta_cliente=pergunta_cliente,
                resposta_redator=dados_redator["texto_completo_auditoria"],
                chunks=chunks,
            )
            if veredito.aprovado_para_envio:
                break
            feedback = veredito.feedback_correcao

        tempo_agentes_rag = round(time.time() - t2, 3)

        # 4. Agente 4: Resumo Executivo Interno
        t3 = time.time()
        resumo_texto = None
        if gerar_resumo:
            resumo_texto = self.resumidor.executar(
                resposta_final_cliente=dados_redator.get("mensagem_cliente", "")
            )
        tempo_resumo = round(time.time() - t3, 3)

        # 5. Montagem da Caixa de Rastreabilidade Oficial
        return CaixaRastreabilidadeSchema(
            ticket_id=id_exec,
            timestamp=datetime.now().astimezone().isoformat(),
            pergunta_cliente=pergunta_cliente,
            triagem_inicial=triagem,
            rag_contexto=rag_trace,
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente=dados_redator.get("mensagem_cliente", ""),
                fonte_tecnica_citada=dados_redator.get("fonte_citada", "NÃO_CITADA"),
                tentativas_redacao=tentativas_realizadas,
            ),
            auditoria=veredito,
            resumo_interno_ticket=resumo_texto,
            telemetria_tempos_s={
                "classificacao_s": tempo_classificacao,
                "retriever_pgvector_s": tempo_rag,
                "redator_e_auditor_s": tempo_agentes_rag,
                "resumo_s": tempo_resumo,
                "total_pipeline_s": round(time.time() - t_inicio_total, 3),
            },
        )

    def processar_turno_sessao(
        self,
        pergunta_cliente: str,
        sessao: SessionMemory,
        gerar_resumo: bool = True,
    ) -> CaixaRastreabilidadeSchema:
        """Processa um turno conversacional utilizando memória, cache de RAG e circuit breaker."""
        t_inicio = time.perf_counter()
        tempos: dict[str, float] = {}

        historico_str = sessao.obter_historico_formatado()
        cat_anterior = sessao.categoria_atual or ""

        # 1. Triagem Contextual (Detecta is_followup e reescreve search_query)
        t0 = time.perf_counter()
        triagem = self.classificador.executar(
            pergunta_cliente=pergunta_cliente,
            historico_recente=historico_str,
            categoria_anterior=cat_anterior,
        )
        # Se for primeiro turno, garante is_followup=False
        if sessao.turno_global == 0:
            triagem.is_followup = False
        tempos["triagem_s"] = round(time.perf_counter() - t0, 3)

        # 2. Decisão de Cache RAG vs. Nova Busca no PGVector
        t0 = time.perf_counter()
        reutilizar_cache = sessao.atualizar_contexto_topico(
            nova_categoria=triagem.category,
            is_followup=triagem.is_followup,
        )

        if reutilizar_cache:
            chunks = sessao.chunks_em_cache
        else:
            query_busca = triagem.search_query.strip() if triagem.search_query else pergunta_cliente
            chunks = self.retriever.buscar_chunks(
                query=query_busca,
                k=1,
                category_filter=triagem.category,
                min_similarity=MIN_SIMILARITY,
            )
        tempos["retrieval_s"] = round(time.perf_counter() - t0, 3)

        # 3. Verifica Circuit Breaker de Limite de Turnos no mesmo Tópico
        forcar_limite = sessao.atingiu_limite_topico()

        # 4. Loop Redator <-> Auditor com Memória
        t0 = time.perf_counter()
        feedback = None
        tentativas = 0
        res_redator = {"mensagem_cliente": "", "fonte_citada": "NÃO_CITADA", "texto_completo_auditoria": ""}
        veredito = None

        max_retries = getattr(self, "max_retries", 1)
        for tentativa in range(1, MAX_TENTATIVAS_CORRECAO + 2):
            tentativas = tentativa
            res_redator = self.redator.executar(
                pergunta_cliente=pergunta_cliente,
                chunks=chunks,
                feedback_anterior=feedback,
                categoria=triagem.category,
                historico_conversa=historico_str,
                forcar_escalonamento_limite=forcar_limite,
            )

            veredito = self.auditor.executar(
                pergunta_cliente=pergunta_cliente,
                resposta_redator=res_redator["texto_completo_auditoria"],
                chunks=chunks,
                historico_conversa=historico_str,
                forcar_escalonamento_limite=forcar_limite,
            )

            if forcar_limite:
                veredito.requer_escalonamento = True

            if veredito.aprovado_para_envio:
                break
            feedback = veredito.feedback_correcao

        tempos["redacao_e_auditoria_s"] = round(time.perf_counter() - t0, 3)

        # 5. Resumo Executivo
        t0 = time.perf_counter()
        resumo_str = ""
        if gerar_resumo:
            resumo_str = self.resumidor.executar(res_redator["mensagem_cliente"])
        tempos["resumo_s"] = round(time.perf_counter() - t0, 3)
        tempos["total_pipeline_s"] = round(time.perf_counter() - t_inicio, 3)

        # 6. Monta a Caixa de Rastreabilidade
        if chunks:
            c = chunks[0]
            rag_info = ContextoRAGSchema(
                chunk_id=c["chunk_id"],
                subcategoria=c["subcategory"],
                score_similaridade=c["similarity_score"],
                regra_escalonamento_aplicada=c["fatias"]["escalonamento"],
                reutilizado_do_cache=reutilizar_cache,
                turno_no_topico=sessao.turnos_no_topico_atual,
            )
        else:
            rag_info = ContextoRAGSchema(
                chunk_id="FORA_DE_ESCOPO",
                subcategoria="Nenhuma",
                score_similaridade=0.0,
                regra_escalonamento_aplicada="Escalonamento padrão por ausência de documentação.",
                reutilizado_do_cache=False,
                turno_no_topico=sessao.turnos_no_topico_atual,
            )

        ticket_id = f"{sessao.session_id}-T{sessao.turno_global}"
        caixa = CaixaRastreabilidadeSchema(
            ticket_id=ticket_id,
            timestamp=datetime.now().astimezone().isoformat(),
            pergunta_cliente=pergunta_cliente,
            triagem_inicial=triagem,
            rag_contexto=rag_info,
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente=res_redator["mensagem_cliente"],
                fonte_tecnica_citada=res_redator["fonte_citada"],
                tentativas_redacao=tentativas,
            ),
            auditoria=veredito,
            resumo_interno_ticket=resumo_str or None,
            telemetria_tempos_s=tempos,
        )

        # 7. Atualiza a Memória da Sessão
        sessao.registrar_turno(
            pergunta_cliente=pergunta_cliente,
            resposta_agente=res_redator["mensagem_cliente"],
            chunks_usados=chunks,
            caixa_dict=caixa.model_dump(),
        )

        return caixa

    def gerar_sugestao_turno(
        self,
        pergunta_cliente: str,
        sessao: SessionMemory,
    ) -> SugestaoCopilotoSchema:
        """Fase 1 HITL: gera sugestão e auditoria sem gravar na memória definitiva."""
        t_inicio = time.perf_counter()
        tempos: dict[str, float] = {}

        historico_str = sessao.obter_historico_formatado()
        cat_anterior = sessao.categoria_atual or ""

        t0 = time.perf_counter()
        triagem = self.classificador.executar(
            pergunta_cliente=pergunta_cliente,
            historico_recente=historico_str,
            categoria_anterior=cat_anterior,
        )
        if sessao.turno_global == 0:
            triagem.is_followup = False
        tempos["triagem_s"] = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        reutilizar_cache, proximo_turno_topico = sessao.avaliar_contexto_topico(
            nova_categoria=triagem.category,
            is_followup=triagem.is_followup,
        )

        if reutilizar_cache:
            chunks = sessao.chunks_em_cache
        else:
            query_busca = triagem.search_query.strip() if triagem.search_query else pergunta_cliente
            chunks = self.retriever.buscar_chunks(
                query=query_busca,
                k=1,
                category_filter=triagem.category,
                min_similarity=MIN_SIMILARITY,
            )
        tempos["retrieval_s"] = round(time.perf_counter() - t0, 3)

        # Limpa histórico injetado no Redator/Auditor quando houver troca de tópico
        historico_agentes = historico_str if reutilizar_cache else ""

        t0 = time.perf_counter()
        feedback = None
        tentativas = 0
        res_redator = {"mensagem_cliente": "", "fonte_citada": "NÃO_CITADA", "texto_completo_auditoria": ""}
        veredito: Optional[VereditoAuditorSchema] = None

        for tentativa in range(1, MAX_TENTATIVAS_CORRECAO + 2):
            tentativas = tentativa
            res_redator = self.redator.executar(
                pergunta_cliente=pergunta_cliente,
                chunks=chunks,
                feedback_anterior=feedback,
                categoria=triagem.category,
                historico_conversa=historico_agentes,
                forcar_escalonamento_limite=False,
            )
            veredito = self.auditor.executar(
                pergunta_cliente=pergunta_cliente,
                resposta_redator=res_redator["texto_completo_auditoria"],
                chunks=chunks,
                historico_conversa=historico_agentes,
                forcar_escalonamento_limite=False,
            )
            if veredito.aprovado_para_envio:
                break
            feedback = veredito.feedback_correcao

        tempos["redacao_e_auditoria_s"] = round(time.perf_counter() - t0, 3)
        tempos["resumo_s"] = 0.0
        tempos["total_pipeline_s"] = round(time.perf_counter() - t_inicio, 3)

        if chunks:
            c = chunks[0]
            rag_info = ContextoRAGSchema(
                chunk_id=c["chunk_id"],
                subcategoria=c["subcategory"],
                score_similaridade=c["similarity_score"],
                regra_escalonamento_aplicada=c["fatias"]["escalonamento"],
                reutilizado_do_cache=reutilizar_cache,
                turno_no_topico=proximo_turno_topico,
            )
        else:
            rag_info = ContextoRAGSchema(
                chunk_id="FORA_DE_ESCOPO",
                subcategoria="Nenhuma",
                score_similaridade=0.0,
                regra_escalonamento_aplicada="Escalonamento padrão por ausência de documentação.",
                reutilizado_do_cache=False,
                turno_no_topico=proximo_turno_topico,
            )

        proximo_turno_global = sessao.turno_global + 1
        caixa = CaixaRastreabilidadeSchema(
            ticket_id=f"{sessao.session_id}-T{proximo_turno_global}",
            timestamp=datetime.now().astimezone().isoformat(),
            pergunta_cliente=pergunta_cliente,
            triagem_inicial=triagem,
            rag_contexto=rag_info,
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente=res_redator["mensagem_cliente"],
                fonte_tecnica_citada=res_redator["fonte_citada"],
                tentativas_redacao=tentativas,
            ),
            auditoria=veredito,
            resumo_interno_ticket=None,
            telemetria_tempos_s=tempos,
        )

        suggestion_id = f"SUG-{uuid4().hex[:10]}"
        sugestao = SugestaoCopilotoSchema(
            suggestion_id=suggestion_id,
            session_id=sessao.session_id,
            tenant_id=sessao.tenant_id,
            pergunta_cliente=pergunta_cliente,
            mensagem_sugerida=res_redator["mensagem_cliente"],
            alerta_escalonamento=veredito.requer_escalonamento,
            caixa_rastreabilidade=caixa,
            chunks_usados=chunks,
        )

        sessao.salvar_sugestao_pendente(suggestion_id, sugestao.model_dump())
        return sugestao

    def confirmar_envio_turno(
        self,
        sessao: SessionMemory,
        confirmacao: ConfirmacaoHumanaSchema,
    ) -> ResultadoConfirmacaoSchema:
        """Fase 2 HITL: calcula diff de edição, efetiva memória e gera resumo só no escalonamento."""
        dados_pendentes = sessao.consumir_sugestao_pendente(confirmacao.suggestion_id)
        sugestao = SugestaoCopilotoSchema(**dados_pendentes)

        texto_ia = sugestao.mensagem_sugerida.strip()
        texto_humano = confirmacao.mensagem_final_enviada.strip()
        was_edited = texto_ia != texto_humano
        similaridade = SequenceMatcher(None, texto_ia, texto_humano).ratio()
        edit_ratio = round(1.0 - similaridade, 4) if was_edited else 0.0

        sessao.registrar_turno(
            pergunta_cliente=sugestao.pergunta_cliente,
            resposta_enviada=texto_humano,
            categoria=sugestao.caixa_rastreabilidade.triagem_inicial.category,
            is_followup=sugestao.caixa_rastreabilidade.triagem_inicial.is_followup,
            chunks_usados=sugestao.chunks_usados,
            caixa_dict=sugestao.caixa_rastreabilidade.model_dump(),
        )

        handoff_summary = None
        if confirmacao.acao_humana == "ESCALADA_N2":
            transcricao = sessao.obter_historico_formatado(completo=True)
            handoff_summary = self.resumidor.executar(resposta_final_cliente=transcricao)
            sessao.status = "ESCALADA_N2"
            sessao.handoff_summary = handoff_summary
        else:
            sessao.status = "ABERTA"

        return ResultadoConfirmacaoSchema(
            suggestion_id=confirmacao.suggestion_id,
            session_id=sessao.session_id,
            tenant_id=sessao.tenant_id,
            acao_humana=confirmacao.acao_humana,
            atendente_id=confirmacao.atendente_id,
            mensagem_sugerida=texto_ia,
            mensagem_final_enviada=texto_humano,
            was_edited=was_edited,
            edit_ratio=edit_ratio,
            status_sessao=sessao.status,
            handoff_summary=handoff_summary,
        )

    def processar_turno_sessao(
        self,
        pergunta_cliente: str,
        sessao: SessionMemory,
        gerar_resumo: bool = False,
    ) -> CaixaRastreabilidadeSchema:
        """Atalho síncrono (CLI/testes) que gera e auto-confirma a sugestão."""
        sugestao = self.gerar_sugestao_turno(pergunta_cliente=pergunta_cliente, sessao=sessao)
        acao = "ESCALADA_N2" if (gerar_resumo and sugestao.alerta_escalonamento) else "ACEITA_SEM_EDICAO"

        resultado = self.confirmar_envio_turno(
            sessao=sessao,
            confirmacao=ConfirmacaoHumanaSchema(
                suggestion_id=sugestao.suggestion_id,
                acao_humana=acao,
                mensagem_final_enviada=sugestao.mensagem_sugerida,
            ),
        )
        sugestao.caixa_rastreabilidade.resumo_interno_ticket = resultado.handoff_summary
        return sugestao.caixa_rastreabilidade


def rodar_pipeline_com_json_testes(
    filtro_id: Optional[str] = None,
    usar_agente_classificador: bool = True,
    gerar_resumo: bool = True,
) -> Path:
    pipeline = NexusSupportPipeline()

    with open(ARQUIVO_TESTES, "r", encoding="utf-8") as f:
        casos = json.load(f)

    if filtro_id:
        casos = [c for c in casos if c.get("id_teste") == filtro_id]

    caixas_geradas = []

    for caso in casos:
        entrada_mock = None
        if not usar_agente_classificador:
            entrada_mock = {
                "category": caso["categoria"],
                "priority": caso.get("prioridade", "Alta"),
                "initial_level": caso.get("nivel_inicial", "N1"),
                "triage_justification": caso.get("descricao", "Triagem via dataset de testes."),
            }

        print(f"\nProcessando [{caso['id_teste']}]...")
        caixa = pipeline.processar_ticket(
            pergunta_cliente=caso["pergunta"],
            classificacao_externa=entrada_mock,
            gerar_resumo=gerar_resumo,
            ticket_id=caso["id_teste"],
        )
        caixas_geradas.append(caixa.model_dump())

        print(f" -> Categoria Triagem: {caixa.triagem_inicial.category} (Esperada: {caso['categoria']})")
        print(f" -> Requer Escalonamento (Auditor): {caixa.auditoria.requer_escalonamento}")
        print(f" -> Tempo Total: {caixa.telemetria_tempos_s['total_pipeline_s']}s")

    caminho_saida = PASTA_RASTREABILIDADE / f"rastreabilidade_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(caixas_geradas, f, indent=4, ensure_ascii=False)

    print(f"\nCaixa de Rastreabilidade salva em: {caminho_saida.resolve()}")
    return caminho_saida


if __name__ == "__main__":
    # Para rodar os 4 agentes completos de ponta a ponta:
    rodar_pipeline_com_json_testes(usar_agente_classificador=True, gerar_resumo=True)