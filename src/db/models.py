from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
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