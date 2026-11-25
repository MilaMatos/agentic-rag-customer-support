from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import delete, select

from src.agents.schemas import (
    ConfirmacaoHumanaSchema,
    ResultadoConfirmacaoSchema,
    SugestaoCopilotoSchema,
)
from src.db.connection import SessionLocal
from src.db.models import ChatMessageDB, ChatSessionDB, CopilotTraceabilityDB

MAX_CHARS_TOPICO = 2400


class SessionRepository:
    def __init__(self, session_factory=SessionLocal, max_chars_topico: int = MAX_CHARS_TOPICO):
        self._session_factory = session_factory
        self.max_chars_topico = max_chars_topico

    def obter_ou_criar_sessao(self, session_id: str, tenant_id: str = "default") -> ChatSessionDB:
        with self._session_factory() as db:
            stmt = select(ChatSessionDB).where(
                ChatSessionDB.session_id == session_id,
                ChatSessionDB.tenant_id == tenant_id,
            )
            sessao = db.execute(stmt).scalar_one_or_none()
            if sessao is None:
                sessao = ChatSessionDB(session_id=session_id, tenant_id=tenant_id)
                db.add(sessao)
                db.commit()
                db.refresh(sessao)
            db.expunge(sessao)
            return sessao

    def obter_historico_recente(
        self,
        session_id: str,
        tenant_id: str = "default",
        limite_mensagens: int = 4,
    ) -> str:
        with self._session_factory() as db:
            stmt = (
                select(ChatMessageDB)
                .where(
                    ChatMessageDB.session_id == session_id,
                    ChatMessageDB.tenant_id == tenant_id,
                )
                .order_by(ChatMessageDB.created_at.desc(), ChatMessageDB.message_id.desc())
                .limit(limite_mensagens)
            )
            mensagens = list(reversed(db.execute(stmt).scalars().all()))
            return self._formatar_mensagens(mensagens)

    def obter_transcricao_completa(self, session_id: str, tenant_id: str = "default") -> str:
        with self._session_factory() as db:
            stmt = (
                select(ChatMessageDB)
                .where(
                    ChatMessageDB.session_id == session_id,
                    ChatMessageDB.tenant_id == tenant_id,
                )
                .order_by(ChatMessageDB.turn_number.asc(), ChatMessageDB.created_at.asc())
            )
            mensagens = db.execute(stmt).scalars().all()
            return self._formatar_mensagens(mensagens)

    def obter_contexto_topico(
        self,
        session_id: str,
        categoria: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == session_id,
                    ChatSessionDB.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()

            ctx_salvo = (sessao.topic_contexts or {}).get(categoria, {}) if sessao else {}
            resumo_anterior = ctx_salvo.get("summary", "")
            resumido_ate = int(ctx_salvo.get("summarized_until_turn", 0))
            cached_chunks = ctx_salvo.get("cached_chunks", [])

            stmt = (
                select(ChatMessageDB)
                .where(
                    ChatMessageDB.session_id == session_id,
                    ChatMessageDB.tenant_id == tenant_id,
                    ChatMessageDB.topic_category == categoria,
                    ChatMessageDB.turn_number > resumido_ate,
                )
                .order_by(ChatMessageDB.turn_number.asc(), ChatMessageDB.created_at.asc())
            )
            mensagens_novas = db.execute(stmt).scalars().all()
            texto_novo = self._formatar_mensagens(mensagens_novas)

            partes = []
            if resumo_anterior:
                partes.append(f"[RESUMO ANTERIOR DO TÓPICO ({categoria})]: {resumo_anterior}")
            if texto_novo:
                partes.append(texto_novo)

            historico_formatado = "\n".join(partes)
            ultimo_turno = mensagens_novas[-1].turn_number if mensagens_novas else resumido_ate
            precisa_compactar = len(texto_novo) > self.max_chars_topico

            return {
                "historico_formatado": historico_formatado,
                "cached_chunks": cached_chunks,
                "resumo_anterior": resumo_anterior,
                "texto_novo": texto_novo,
                "ultimo_turno_topico": ultimo_turno,
                "precisa_compactar": precisa_compactar,
            }

    def salvar_sugestao_pendente(self, sugestao: SugestaoCopilotoSchema) -> None:
        caixa = sugestao.caixa_rastreabilidade
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == sugestao.session_id,
                    ChatSessionDB.tenant_id == sugestao.tenant_id,
                )
            ).scalar_one_or_none()
            if sessao is None:
                sessao = ChatSessionDB(
                    session_id=sugestao.session_id,
                    tenant_id=sugestao.tenant_id,
                    turno_global=0,
                    turnos_no_topico_atual=0,
                )
                db.add(sessao)
                db.flush()

            sessao.pending_suggestion = sugestao.model_dump()
            sessao.status = "AGUARDANDO_N1"

            trace = CopilotTraceabilityDB(
                suggestion_id=sugestao.suggestion_id,
                session_id=sugestao.session_id,
                tenant_id=sugestao.tenant_id,
                turn_number=(sessao.turno_global or 0) + 1,
                ai_suggested_text=sugestao.mensagem_sugerida,
                category=caixa.triagem_inicial.category,
                chunk_id=caixa.rag_contexto.chunk_id,
                reutilizado_do_cache=caixa.rag_contexto.reutilizado_do_cache,
                aprovado_auditor=caixa.auditoria.aprovado_para_envio,
                redator_alucinou=caixa.auditoria.redator_alucinou,
                requer_escalonamento=caixa.auditoria.requer_escalonamento,
                total_pipeline_s=caixa.telemetria_tempos_s.get("total_pipeline_s", 0.0),
                caixa_completa=caixa.model_dump(),
            )
            db.add(trace)
            db.commit()

    def obter_sugestao_pendente(
        self, session_id: str, suggestion_id: str, tenant_id: str = "default"
    ) -> SugestaoCopilotoSchema:
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == session_id,
                    ChatSessionDB.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()
            if not sessao or not sessao.pending_suggestion:
                raise KeyError(f"Nenhuma sugestão pendente na sessão '{session_id}'.")
            if sessao.pending_suggestion.get("suggestion_id") != suggestion_id:
                raise KeyError(f"Sugestão '{suggestion_id}' não corresponde à pendente.")
            return SugestaoCopilotoSchema(**sessao.pending_suggestion)

    def confirmar_turno(
        self,
        sugestao: SugestaoCopilotoSchema,
        confirmacao: ConfirmacaoHumanaSchema,
        resultado: ResultadoConfirmacaoSchema,
    ) -> Optional[str]:
        """Efetiva mensagens, atualiza cache/trace e retorna categoria anterior se houve troca."""
        caixa = sugestao.caixa_rastreabilidade
        categoria = caixa.triagem_inicial.category
        chunk_id = caixa.rag_contexto.chunk_id
        is_followup = caixa.triagem_inicial.is_followup
        agora = datetime.now(timezone.utc)

        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == sugestao.session_id,
                    ChatSessionDB.tenant_id == sugestao.tenant_id,
                )
            ).scalar_one()

            categoria_anterior = sessao.categoria_atual
            trocou_topico = bool(categoria_anterior and categoria_anterior != categoria)

            sessao.turno_global += 1
            turno_atual = sessao.turno_global
            if is_followup and sessao.categoria_atual == categoria:
                sessao.turnos_no_topico_atual += 1
            else:
                sessao.turnos_no_topico_atual = 1

            sessao.categoria_atual = categoria
            sessao.chunks_em_cache = sugestao.chunks_usados
            sessao.pending_suggestion = None
            sessao.status = resultado.status_sessao

            # Reatribui dict para o SQLAlchemy detectar mutação no JSONB
            contexts = dict(sessao.topic_contexts or {})
            ctx_cat = dict(contexts.get(categoria, {}))
            if sugestao.chunks_usados:
                ctx_cat["cached_chunks"] = sugestao.chunks_usados
            contexts[categoria] = ctx_cat
            sessao.topic_contexts = contexts

            if resultado.status_sessao == "ESCALADA_N2":
                sessao.escalated_at = agora
                sessao.handoff_summary = resultado.handoff_summary

            db.add_all([
                ChatMessageDB(
                    message_id=f"MSG-{uuid4().hex[:12]}",
                    session_id=sugestao.session_id,
                    tenant_id=sugestao.tenant_id,
                    turn_number=turno_atual,
                    sender_role="CLIENT",
                    topic_category=categoria,
                    chunk_id=chunk_id,
                    content=sugestao.pergunta_cliente,
                ),
                ChatMessageDB(
                    message_id=f"MSG-{uuid4().hex[:12]}",
                    session_id=sugestao.session_id,
                    tenant_id=sugestao.tenant_id,
                    turn_number=turno_atual,
                    sender_role="HUMAN_N1",
                    topic_category=categoria,
                    chunk_id=chunk_id,
                    content=resultado.mensagem_final_enviada,
                ),
            ])

            trace = db.execute(
                select(CopilotTraceabilityDB).where(
                    CopilotTraceabilityDB.suggestion_id == confirmacao.suggestion_id,
                    CopilotTraceabilityDB.tenant_id == sugestao.tenant_id,
                )
            ).scalar_one_or_none()
            if trace:
                trace.human_final_text = resultado.mensagem_final_enviada
                trace.human_action = confirmacao.acao_humana
                trace.atendente_id = confirmacao.atendente_id
                trace.was_edited = resultado.was_edited
                trace.edit_ratio = resultado.edit_ratio
                trace.confirmed_at = agora

            db.commit()
            return categoria_anterior if trocou_topico else None

    def atualizar_resumo_topico(
        self,
        session_id: str,
        categoria: str,
        resumo: str,
        ate_turno: int,
        tenant_id: str = "default",
    ) -> None:
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == session_id,
                    ChatSessionDB.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()
            if not sessao or sessao.status == "ENCERRADA":
                return

            contexts = dict(sessao.topic_contexts or {})
            ctx_cat = dict(contexts.get(categoria, {}))
            ctx_cat["summary"] = resumo
            ctx_cat["summarized_until_turn"] = ate_turno
            contexts[categoria] = ctx_cat
            sessao.topic_contexts = contexts
            db.commit()

    def encerrar_sessao(self, session_id: str, tenant_id: str = "default") -> None:
        """Encerra sessão e limpa estado temporário preservando histórico e auditoria."""
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == session_id,
                    ChatSessionDB.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()
            if not sessao:
                return

            sessao.status = "ENCERRADA"
            sessao.closed_at = datetime.now(timezone.utc)
            sessao.chunks_em_cache = None
            sessao.topic_contexts = None
            sessao.pending_suggestion = None
            db.commit()

    def limpar_sessao_teste(self, session_id: str) -> None:
        with self._session_factory() as db:
            db.execute(delete(CopilotTraceabilityDB).where(CopilotTraceabilityDB.session_id == session_id))
            db.execute(delete(ChatMessageDB).where(ChatMessageDB.session_id == session_id))
            db.execute(delete(ChatSessionDB).where(ChatSessionDB.session_id == session_id))
            db.commit()

    @staticmethod
    def _formatar_mensagens(mensagens: list[ChatMessageDB]) -> str:
        linhas = []
        for m in mensagens:
            autor = "CLIENTE" if m.sender_role == "CLIENT" else "ATENDENTE N1"
            linhas.append(f"{autor}: {m.content}")
        return "\n".join(linhas)



    def listar_sessoes(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            stmt = select(ChatSessionDB).where(ChatSessionDB.tenant_id == tenant_id)
            if status:
                stmt = stmt.where(ChatSessionDB.status == status)
            stmt = stmt.order_by(ChatSessionDB.updated_at.desc()).limit(limite)

            sessoes = db.execute(stmt).scalars().all()
            return [self._serializar_sessao(s) for s in sessoes]

    def listar_fila_especialista(
        self,
        tenant_id: str = "default",
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            stmt = (
                select(ChatSessionDB)
                .where(
                    ChatSessionDB.tenant_id == tenant_id,
                    ChatSessionDB.status == "ESCALADA_N2",
                )
                .order_by(ChatSessionDB.escalated_at.desc(), ChatSessionDB.updated_at.desc())
                .limit(limite)
            )
            sessoes = db.execute(stmt).scalars().all()
            return [self._serializar_sessao(s) for s in sessoes]

    def listar_mensagens_sessao(
        self,
        session_id: str,
        tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            stmt = (
                select(ChatMessageDB)
                .where(
                    ChatMessageDB.session_id == session_id,
                    ChatMessageDB.tenant_id == tenant_id,
                )
                .order_by(ChatMessageDB.turn_number.asc(), ChatMessageDB.created_at.asc())
            )
            mensagens = db.execute(stmt).scalars().all()
            return [
                {
                    "message_id": m.message_id,
                    "turn_number": m.turn_number,
                    "sender_role": m.sender_role,
                    "topic_category": m.topic_category,
                    "chunk_id": m.chunk_id,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in mensagens
            ]

    def obter_detalhe_sessao(
        self,
        session_id: str,
        tenant_id: str = "default",
    ) -> Optional[dict[str, Any]]:
        with self._session_factory() as db:
            sessao = db.execute(
                select(ChatSessionDB).where(
                    ChatSessionDB.session_id == session_id,
                    ChatSessionDB.tenant_id == tenant_id,
                )
            ).scalar_one_or_none()
            if not sessao:
                return None

            dados = self._serializar_sessao(sessao)
            dados["pending_suggestion"] = sessao.pending_suggestion
            dados["mensagens"] = self.listar_mensagens_sessao(session_id, tenant_id=tenant_id)
            return dados

    @staticmethod
    def _serializar_sessao(s: ChatSessionDB) -> dict[str, Any]:
        return {
            "session_id": s.session_id,
            "tenant_id": s.tenant_id,
            "status": s.status,
            "turno_global": s.turno_global,
            "turnos_no_topico_atual": s.turnos_no_topico_atual,
            "categoria_atual": s.categoria_atual,
            "handoff_summary": s.handoff_summary,
            "tem_sugestao_pendente": bool(s.pending_suggestion),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "escalated_at": s.escalated_at.isoformat() if s.escalated_at else None,
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
        }