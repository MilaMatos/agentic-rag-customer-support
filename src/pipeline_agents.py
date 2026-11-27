import logging
import os

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from difflib import SequenceMatcher
import threading
import time
from typing import Any, Optional
from uuid import uuid4

from src.agents.agent_auditor import AgenteAuditorQualidade
from src.agents.agent_classifier import AgenteClassificador
from src.agents.agent_redactor import AgenteRedatorN1
from src.agents.agent_summarizer import AgenteResumo
from src.agents.schemas import (
    AtendimentoRedatorSchema,
    CaixaRastreabilidadeSchema,
    ConfirmacaoHumanaSchema,
    ContextoRAGSchema,
    ResultadoConfirmacaoSchema,
    SugestaoCopilotoSchema,
    TicketClassification,
    VereditoAuditorSchema,
)
from src.db.session_repo import SessionRepository
from src.rag.retriever import NexusRetriever

logger = logging.getLogger(__name__)

MAX_TENTATIVAS_CORRECAO = 1
MIN_SIMILARITY = 0.30


class NexusSupportPipeline:
    """Orquestrador Multi-Agente RAG do NexusTech Support Copilot."""

    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        model_config: Optional[dict[str, Any]] = None,
    ):
        cfg = model_config or {}
        self.retriever = NexusRetriever()
        self.classificador = AgenteClassificador(model_name=cfg.get("classifier"))
        self.redator = AgenteRedatorN1(model_name=cfg.get("redactor"))
        self.auditor = AgenteAuditorQualidade(model_name=cfg.get("auditor"))
        self.resumidor = AgenteResumo(model_name=cfg.get("summarizer"))
        self.session_repo = session_repo or SessionRepository()
        self._bg_executor = ThreadPoolExecutor(max_workers=4)
        self._bg_lock = threading.Lock()
        self._bg_futures: set[Future] = set()
        self._compactacoes_ativas: set[tuple[str, str]] = set()

    def _obter_classificacao(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
    ) -> TicketClassification:
        if classificacao_externa:
            return TicketClassification(
                category=classificacao_externa.get("category")
                or classificacao_externa.get("categoria", "General Inquiry"),
                priority=classificacao_externa.get("priority")
                or classificacao_externa.get("prioridade", "Media"),
                initial_level=classificacao_externa.get("initial_level")
                or classificacao_externa.get("nivel_inicial", "N1"),
                triage_justification=classificacao_externa.get("triage_justification")
                or classificacao_externa.get("justificativa_triagem", ""),
            )
        return self.classificador.executar(pergunta_cliente=pergunta_cliente)

    def _executar_redacao_auditoria(
        self,
        pergunta_cliente: str,
        chunks: list[dict[str, Any]],
        categoria: str,
        historico_agentes: str,
    ) -> tuple[dict[str, str], VereditoAuditorSchema, int]:
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
                categoria=categoria,
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

        return res_redator, veredito, tentativas

    @staticmethod
    def _montar_sugestao(
        session_id: str,
        tenant_id: str,
        proximo_turno_global: int,
        proximo_turno_topico: int,
        pergunta_cliente: str,
        triagem: TicketClassification,
        chunks: list[dict[str, Any]],
        reutilizar_cache: bool,
        res_redator: dict[str, str],
        veredito: VereditoAuditorSchema,
        tentativas: int,
        tempos: dict[str, float],
    ) -> SugestaoCopilotoSchema:
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

        caixa = CaixaRastreabilidadeSchema(
            ticket_id=f"{session_id}-T{proximo_turno_global}",
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

        return SugestaoCopilotoSchema(
            suggestion_id=f"SUG-{uuid4().hex[:10]}",
            session_id=session_id,
            tenant_id=tenant_id,
            pergunta_cliente=pergunta_cliente,
            mensagem_sugerida=res_redator["mensagem_cliente"],
            alerta_escalonamento=veredito.requer_escalonamento,
            caixa_rastreabilidade=caixa,
            chunks_usados=chunks,
        )

    @staticmethod
    def _calcular_diff(texto_ia: str, texto_humano: str) -> tuple[bool, float]:
        was_edited = texto_ia != texto_humano
        if not was_edited:
            return False, 0.0
        similaridade = SequenceMatcher(None, texto_ia, texto_humano).ratio()
        return True, round(1.0 - similaridade, 4)

    def processar_ticket(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
        gerar_resumo: bool = True,
        ticket_id: Optional[str] = None,
    ) -> CaixaRastreabilidadeSchema:
        """Fluxo single-turn sem persistência de sessão."""
        t_inicio_total = time.time()
        id_exec = ticket_id or f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        t0 = time.time()
        triagem = self._obter_classificacao(pergunta_cliente, classificacao_externa)
        tempo_classificacao = round(time.time() - t0, 3)

        t1 = time.time()
        chunks = self.retriever.buscar_chunks(
            query=pergunta_cliente,
            k=1,
            category_filter=None,
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

        t2 = time.time()
        dados_redator, veredito, tentativas_realizadas = self._executar_redacao_auditoria(
            pergunta_cliente=pergunta_cliente,
            chunks=chunks,
            categoria=triagem.category,
            historico_agentes="",
        )
        tempo_agentes_rag = round(time.time() - t2, 3)

        t3 = time.time()
        resumo_texto = None
        if gerar_resumo:
            resumo_texto = self.resumidor.executar(
                resposta_final_cliente=dados_redator.get("mensagem_cliente", "")
            )
        tempo_resumo = round(time.time() - t3, 3)

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

    def _triagem_e_rag_turno1_paralelo(
        self, pergunta_cliente: str
    ) -> tuple[TicketClassification, list[dict[str, Any]], float, float]:
        """Executa Classificador e embedding em paralelo no Turno 1."""
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_triagem = pool.submit(
                self.classificador.executar,
                pergunta_cliente=pergunta_cliente,
                historico_recente="",
                categoria_anterior="",
            )
            fut_vetor = pool.submit(self.retriever.embeddings.embed_query, pergunta_cliente)
            triagem = fut_triagem.result()
            triagem.is_followup = False

            vetor = None
            try:
                vetor = fut_vetor.result()
            except Exception as exc:
                logger.warning("Fallback para busca padrão no Turno 1: %s", exc)
        tempo_triagem = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        if vetor is not None:
            chunks = self.retriever.buscar_chunks_por_vetor(
                embedding=vetor,
                k=1,
                category_filter=None,
                min_similarity=MIN_SIMILARITY,
            )
        else:
            query_busca = triagem.search_query.strip() if triagem.search_query else pergunta_cliente
            chunks = self.retriever.buscar_chunks(
                query=query_busca,
                k=1,
                category_filter=None,
                min_similarity=MIN_SIMILARITY,
            )
        tempo_retrieval = round(time.perf_counter() - t1, 3)
        return triagem, chunks, tempo_triagem, tempo_retrieval

    def gerar_sugestao_db(
        self,
        session_id: str,
        pergunta_cliente: str,
        tenant_id: str = "default",
    ) -> SugestaoCopilotoSchema:
        """Fase 1 HITL (PostgreSQL): paralelismo no T1 e memória por tópico."""
        t_inicio = time.perf_counter()
        tempos: dict[str, float] = {}

        sessao_db = self.session_repo.obter_ou_criar_sessao(session_id, tenant_id=tenant_id)
        reutilizar_cache = False

        if sessao_db.turno_global == 0:
            triagem, chunks, t_triagem, t_rag = self._triagem_e_rag_turno1_paralelo(pergunta_cliente)
            tempos["triagem_s"] = t_triagem
            tempos["retrieval_s"] = t_rag
            proximo_turno_topico = 1
            historico_agentes = ""
        else:
            historico_recente = self.session_repo.obter_historico_recente(
                session_id, tenant_id=tenant_id, limite_mensagens=4
            )
            t0 = time.perf_counter()
            triagem = self.classificador.executar(
                pergunta_cliente=pergunta_cliente,
                historico_recente=historico_recente,
                categoria_anterior=sessao_db.categoria_atual or "",
            )
            tempos["triagem_s"] = round(time.perf_counter() - t0, 3)

            ctx_topico = self.session_repo.obter_contexto_topico(
                session_id, categoria=triagem.category, tenant_id=tenant_id
            )
            historico_agentes = ctx_topico["historico_formatado"]

            t1 = time.perf_counter()
            mesmo_topico = (
                triagem.is_followup
                and sessao_db.categoria_atual == triagem.category
                and bool(sessao_db.chunks_em_cache)
            )
            if mesmo_topico:
                reutilizar_cache = True
                chunks = sessao_db.chunks_em_cache or []
                proximo_turno_topico = sessao_db.turnos_no_topico_atual + 1
            else:
                query_busca = triagem.search_query.strip() if triagem.search_query else pergunta_cliente
                chunks = self.retriever.buscar_chunks(
                    query=query_busca,
                    k=1,
                    category_filter=None,
                    min_similarity=MIN_SIMILARITY,
                )
                proximo_turno_topico = 1
            tempos["retrieval_s"] = round(time.perf_counter() - t1, 3)

        t2 = time.perf_counter()
        res_redator, veredito, tentativas = self._executar_redacao_auditoria(
            pergunta_cliente=pergunta_cliente,
            chunks=chunks,
            categoria=triagem.category,
            historico_agentes=historico_agentes,
        )
        tempos["redacao_e_auditoria_s"] = round(time.perf_counter() - t2, 3)
        tempos["resumo_s"] = 0.0
        tempos["total_pipeline_s"] = round(time.perf_counter() - t_inicio, 3)

        sugestao = self._montar_sugestao(
            session_id=session_id,
            tenant_id=tenant_id,
            proximo_turno_global=sessao_db.turno_global + 1,
            proximo_turno_topico=proximo_turno_topico,
            pergunta_cliente=pergunta_cliente,
            triagem=triagem,
            chunks=chunks,
            reutilizar_cache=reutilizar_cache,
            res_redator=res_redator,
            veredito=veredito,
            tentativas=tentativas,
            tempos=tempos,
        )
        self.session_repo.salvar_sugestao_pendente(sugestao)
        return sugestao

    def confirmar_envio_db(
        self,
        session_id: str,
        confirmacao: ConfirmacaoHumanaSchema,
        tenant_id: str = "default",
    ) -> ResultadoConfirmacaoSchema:
        """Fase 2 HITL (PostgreSQL): efetiva envio, resume no handoff e compacta tópicos em background."""
        sugestao = self.session_repo.obter_sugestao_pendente(
            session_id=session_id,
            suggestion_id=confirmacao.suggestion_id,
            tenant_id=tenant_id,
        )

        texto_ia = sugestao.mensagem_sugerida.strip()
        texto_humano = confirmacao.mensagem_final_enviada.strip()
        was_edited, edit_ratio = self._calcular_diff(texto_ia, texto_humano)

        handoff_summary = None
        if confirmacao.acao_humana == "ESCALADA_N2":
            previa = self.session_repo.obter_transcricao_completa(session_id, tenant_id=tenant_id)
            turno_final = f"CLIENTE: {sugestao.pergunta_cliente}\nATENDENTE N1: {texto_humano}"
            transcricao = f"{previa}\n{turno_final}".strip()
            handoff_summary = self.resumidor.executar(resposta_final_cliente=transcricao)
            status_sessao = "ESCALADA_N2"
        else:
            status_sessao = "ABERTA"

        resultado = ResultadoConfirmacaoSchema(
            suggestion_id=confirmacao.suggestion_id,
            session_id=session_id,
            tenant_id=tenant_id,
            acao_humana=confirmacao.acao_humana,
            atendente_id=confirmacao.atendente_id,
            mensagem_sugerida=texto_ia,
            mensagem_final_enviada=texto_humano,
            was_edited=was_edited,
            edit_ratio=edit_ratio,
            status_sessao=status_sessao,
            handoff_summary=handoff_summary,
        )

        categoria_anterior = self.session_repo.confirmar_turno(sugestao, confirmacao, resultado)

        if status_sessao == "ABERTA":
            cat_atual = sugestao.caixa_rastreabilidade.triagem_inicial.category
            self._agendar_compactacao_se_necessario(session_id, cat_atual, tenant_id)
            if categoria_anterior:
                self._agendar_compactacao_se_necessario(session_id, categoria_anterior, tenant_id)

        return resultado

    def encerrar_sessao_db(self, session_id: str, tenant_id: str = "default") -> None:
        self.session_repo.encerrar_sessao(session_id=session_id, tenant_id=tenant_id)

    def _agendar_compactacao_se_necessario(
        self, session_id: str, categoria: str, tenant_id: str
    ) -> None:
        ctx = self.session_repo.obter_contexto_topico(session_id, categoria, tenant_id=tenant_id)
        if not ctx["precisa_compactar"] or not ctx["texto_novo"]:
            return

        chave = (session_id, categoria)
        with self._bg_lock:
            if chave in self._compactacoes_ativas:
                return
            self._compactacoes_ativas.add(chave)

        def _executar():
            try:
                resumo = self.resumidor.resumir_topico(
                    categoria=categoria,
                    transcricao_topico=ctx["texto_novo"],
                    resumo_anterior=ctx["resumo_anterior"],
                )
                self.session_repo.atualizar_resumo_topico(
                    session_id=session_id,
                    categoria=categoria,
                    resumo=resumo,
                    ate_turno=ctx["ultimo_turno_topico"],
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                logger.warning("Falha na compactação em background (%s/%s): %s", session_id, categoria, exc)
            finally:
                with self._bg_lock:
                    self._compactacoes_ativas.discard(chave)

        fut = self._bg_executor.submit(_executar)
        with self._bg_lock:
            self._bg_futures.add(fut)
        fut.add_done_callback(lambda f: self._bg_futures.discard(f))

    def aguardar_background(self, timeout: float = 10.0) -> None:
        with self._bg_lock:
            pendentes = list(self._bg_futures)
        if pendentes:
            wait(pendentes, timeout=timeout)

    def shutdown(self, wait_pending: bool = True) -> None:
        if wait_pending:
            self.aguardar_background()
        self._bg_executor.shutdown(wait=wait_pending)