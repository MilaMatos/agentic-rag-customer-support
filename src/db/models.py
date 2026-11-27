from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.connection import Base


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


class ChatSessionDB(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    status: Mapped[str] = mapped_column(String(24), default="ABERTA", index=True)
    turno_global: Mapped[int] = mapped_column(Integer, default=0)
    turnos_no_topico_atual: Mapped[int] = mapped_column(Integer, default=0)
    categoria_atual: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Estado quente (limpo ao encerrar a sessão)
    chunks_em_cache: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    topic_contexts: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    pending_suggestion: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    handoff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc, onupdate=_agora_utc)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatMessageDB(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    turn_number: Mapped[int] = mapped_column(Integer, default=1)
    sender_role: Mapped[str] = mapped_column(String(16))  # CLIENT | HUMAN_N1
    topic_category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    chunk_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc)

    __table_args__ = (
        Index("ix_msg_session_topic_turn", "session_id", "topic_category", "turn_number"),
    )


class CopilotTraceabilityDB(Base):
    __tablename__ = "copilot_traceability"

    suggestion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    turn_number: Mapped[int] = mapped_column(Integer, default=1)

    ai_suggested_text: Mapped[str] = mapped_column(Text)
    human_final_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_action: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    atendente_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    was_edited: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    edit_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    category: Mapped[str] = mapped_column(String(32), index=True)
    chunk_id: Mapped[str] = mapped_column(String(64), index=True)
    reutilizado_do_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    aprovado_auditor: Mapped[bool] = mapped_column(Boolean, default=True)
    redator_alucinou: Mapped[bool] = mapped_column(Boolean, default=False)
    requer_escalonamento: Mapped[bool] = mapped_column(Boolean, default=False)
    total_pipeline_s: Mapped[float] = mapped_column(Float, default=0.0)
    caixa_completa: Mapped[dict[str, Any]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalResultDB(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(80), index=True)
    models_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    run_index: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(24), default="single_turn")

    pergunta: Mapped[str] = mapped_column(Text)
    expected_category: Mapped[str] = mapped_column(String(32))
    predicted_category: Mapped[str] = mapped_column(String(32))
    category_match: Mapped[bool] = mapped_column(Boolean, default=False)

    expected_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    predicted_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_match: Mapped[bool] = mapped_column(Boolean, default=False)

    chunk_id: Mapped[str] = mapped_column(String(64))
    fonte_citada: Mapped[str] = mapped_column(String(64))
    aprovado_auditor: Mapped[bool] = mapped_column(Boolean, default=True)
    redator_alucinou: Mapped[bool] = mapped_column(Boolean, default=False)
    tentativas_redacao: Mapped[int] = mapped_column(Integer, default=1)
    total_pipeline_s: Mapped[float] = mapped_column(Float, default=0.0)
    telemetria_tempos: Mapped[dict[str, float]] = mapped_column(JSONB)

    judge_model: Mapped[str] = mapped_column(String(80))
    judge_score_total: Mapped[int] = mapped_column(Integer, default=0)
    judge_criteria: Mapped[dict[str, int]] = mapped_column(JSONB)
    judge_reasoning: Mapped[str] = mapped_column(Text, default="")

    client_judge_model: Mapped[str] = mapped_column(String(80), default="")
    client_score_total: Mapped[int] = mapped_column(Integer, default=0)
    client_criteria: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    client_reasoning: Mapped[str] = mapped_column(Text, default="")

    caixa_completa: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc)

    __table_args__ = (
        UniqueConstraint("experiment_id", "case_id", "run_index", name="uq_eval_exp_case_run"),
    )

class EvalMultiTurnResultDB(Base):
    __tablename__ = "eval_multiturn_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(80), index=True)
    models_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    categoria_principal: Mapped[str] = mapped_column(String(32))
    run_index: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[str] = mapped_column(String(80))

    total_turnos: Mapped[int] = mapped_column(Integer)
    expected_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    final_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_match: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    latencia_media_turno_s: Mapped[float] = mapped_column(Float, default=0.0)
    latencia_total_s: Mapped[float] = mapped_column(Float, default=0.0)

    judge_model: Mapped[str] = mapped_column(String(80))
    judge_score_total: Mapped[int] = mapped_column(Integer, default=0)
    judge_criteria: Mapped[dict[str, int]] = mapped_column(JSONB)
    judge_reasoning: Mapped[str] = mapped_column(Text, default="")

    client_judge_model: Mapped[str] = mapped_column(String(80), default="")
    client_score_total: Mapped[int] = mapped_column(Integer, default=0)
    client_criteria: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    client_reasoning: Mapped[str] = mapped_column(Text, default="")

    transcricao: Mapped[str] = mapped_column(Text)
    handoff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    turnos_detalhe: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora_utc)

    __table_args__ = (
        UniqueConstraint("experiment_id", "scenario_id", "run_index", name="uq_eval_mt_exp_scen_run"),
    )