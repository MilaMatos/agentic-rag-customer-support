from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from src.agents.schemas import AcaoHumana


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: Optional[Any] = None


class CreateSessionRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=160)
    customer_external_id: Optional[str] = Field(default=None, max_length=128)


class SessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    customer_name: Optional[str] = None
    status: str
    categoria_atual: Optional[str] = None
    turnos_no_topico_atual: int = 0
    turno_global: int = 0
    has_pending_suggestion: bool = False
    requer_escalonamento_sugerido: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]


class PublicMessageResponse(BaseModel):
    message_id: str
    turn_number: int = 1
    sender_role: str
    content: str
    created_at: Optional[str] = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    status: str
    messages: list[PublicMessageResponse]
    pending_suggestion: Optional[dict[str, Any]] = None
    categoria_atual: Optional[str] = None
    turnos_no_topico_atual: Optional[int] = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class SendMessageAcceptedResponse(BaseModel):
    message_id: str
    session_id: str
    sender_role: Literal["CLIENT"] = "CLIENT"
    content: str
    session_status: str
    created_at: Optional[str] = None


class ConfirmSuggestionRequest(BaseModel):
    attendant_id: str = Field(default="n1_default", min_length=1, max_length=64)
    human_action: AcaoHumana
    human_final_text: str = Field(..., min_length=1)


class ConfirmSuggestionResponse(BaseModel):
    suggestion_id: str
    message_id: Optional[str] = None
    session_status: str
    human_action: AcaoHumana
    was_edited: bool
    edit_ratio: float
    handoff_summary: Optional[str] = None
    confirmed_at: Optional[str] = None


class SpecialistQueueItem(BaseModel):
    session_id: str
    customer_name: Optional[str] = None
    categoria_atual: Optional[str] = None
    turno_global: int = 0
    handoff_summary: Optional[str] = None
    escalated_at: Optional[str] = None


class SpecialistQueueResponse(BaseModel):
    items: list[SpecialistQueueItem]


class SpecialistSessionDetailResponse(BaseModel):
    session_id: str
    customer_name: Optional[str] = None
    status: str
    categoria_atual: Optional[str] = None
    turno_global: int = 0
    last_chunk_id: Optional[str] = None
    auditor_escalation_reason: Optional[str] = None
    handoff_summary: Optional[str] = None
    escalated_at: Optional[str] = None
    messages: list[PublicMessageResponse] = Field(default_factory=list)