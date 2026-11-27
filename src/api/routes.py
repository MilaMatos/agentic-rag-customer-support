import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import text

from src.agents.schemas import ConfirmacaoHumanaSchema
from src.api.dependencies import get_pipeline, get_session_repo, get_tenant_id
from src.api.schemas import (
    ConfirmSuggestionRequest,
    ConfirmSuggestionResponse,
    CreateSessionRequest,
    PublicMessageResponse,
    SendMessageAcceptedResponse,
    SendMessageRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SpecialistQueueItem,
    SpecialistQueueResponse,
    SpecialistSessionDetailResponse,
)
from src.api.ws_manager import ws_manager
from src.db.connection import engine
from src.db.session_repo import SessionRepository
from src.pipeline_agents import NexusSupportPipeline

router = APIRouter()


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _erro_api(status_code: int, error_code: str, message: str, detail: Any = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message, "detail": detail},
    )


def check_db_ready() -> bool:
    """Executa SELECT 1 no PostgreSQL para o endpoint /ready."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _mapear_sessao(dados: dict[str, Any], customer_name: Optional[str] = None) -> SessionResponse:
    pending = dados.get("pending_suggestion") or {}
    alerta_esc = bool(pending.get("alerta_escalonamento", False))
    return SessionResponse(
        session_id=dados["session_id"],
        tenant_id=dados["tenant_id"],
        customer_name=customer_name or dados.get("customer_name"),
        status=dados["status"],
        categoria_atual=dados.get("categoria_atual"),
        turnos_no_topico_atual=dados.get("turnos_no_topico_atual", 0),
        turno_global=dados.get("turno_global", 0),
        has_pending_suggestion=bool(dados.get("tem_sugestao_pendente", bool(pending))),
        requer_escalonamento_sugerido=alerta_esc,
        created_at=dados.get("created_at"),
        updated_at=dados.get("updated_at"),
    )


async def _notificar_encerramento(tenant_id: str, session_id: str, closed_by: str) -> None:
    payload = {
        "session_id": session_id,
        "status": "ENCERRADA",
        "closed_by": closed_by,
        "closed_at": _agora_iso(),
    }
    await ws_manager.send_to_client(
        tenant_id=tenant_id,
        session_id=session_id,
        event_type="session.closed",
        data=payload,
    )
    await ws_manager.send_to_agents(
        tenant_id=tenant_id,
        event_type="session.closed",
        data=payload,
    )
    await ws_manager.send_to_specialists(
        tenant_id=tenant_id,
        event_type="session.closed",
        data=payload,
    )


async def _processar_copiloto_em_background(
    pipeline: NexusSupportPipeline,
    tenant_id: str,
    session_id: str,
    client_message_id: str,
    content: str,
) -> None:
    await ws_manager.send_to_agents(
        tenant_id=tenant_id,
        event_type="copilot.processing",
        data={
            "session_id": session_id,
            "client_message_id": client_message_id,
            "status": "IA_PROCESSANDO",
        },
    )

    try:
        sugestao = await asyncio.to_thread(
            pipeline.gerar_sugestao_db,
            session_id=session_id,
            pergunta_cliente=content,
            tenant_id=tenant_id,
        )
        caixa = sugestao.caixa_rastreabilidade
        triagem = caixa.triagem_inicial
        rag = caixa.rag_contexto
        aud = caixa.auditoria

        await ws_manager.send_to_agents(
            tenant_id=tenant_id,
            event_type="copilot.suggestion_ready",
            data={
                "session_id": session_id,
                "suggestion_id": sugestao.suggestion_id,
                "client_message_id": client_message_id,
                "ai_suggested_text": sugestao.mensagem_sugerida,
                "triagem": {
                    "category": triagem.category,
                    "priority": triagem.priority,
                    "rota_acao": "CONTINUAR_TOPICO" if triagem.is_followup else "NOVO_TOPICO",
                    "is_followup": triagem.is_followup,
                },
                "rag_contexto": {
                    "chunk_id": rag.chunk_id,
                    "subcategoria": rag.subcategoria,
                    "score_similaridade": rag.score_similaridade,
                    "reutilizado_do_cache": rag.reutilizado_do_cache,
                    "turno_no_topico": rag.turno_no_topico,
                },
                "auditoria": {
                    "aprovado_para_envio": aud.aprovado_para_envio,
                    "redator_alucinou": aud.redator_alucinou,
                    "citou_fonte": aud.citou_fonte,
                    "requer_escalonamento": aud.requer_escalonamento,
                    "analise_raciocinio": aud.analise_raciocinio,
                },
                "telemetria_tempos_s": caixa.telemetria_tempos_s,
            },
        )
    except Exception as exc:
        await ws_manager.send_to_agents(
            tenant_id=tenant_id,
            event_type="copilot.error",
            data={
                "session_id": session_id,
                "client_message_id": client_message_id,
                "error_message": f"Falha ao gerar sugestão do copiloto: {exc}",
            },
        )


# ---------------------------------------------------------------------------
# Health Checks
# ---------------------------------------------------------------------------

@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness_check(db_ok: bool = Depends(check_db_ready)) -> dict[str, str]:
    if not db_ok:
        raise _erro_api(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DATABASE_UNAVAILABLE",
            "PostgreSQL indisponível no momento.",
        )
    return {"status": "ready", "database": "connected"}


# ---------------------------------------------------------------------------
# Sessões e Mensagens (Cliente + Atendente N1)
# ---------------------------------------------------------------------------

@router.post("/api/v1/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def criar_sessao(
    body: CreateSessionRequest,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> SessionResponse:
    session_id = str(uuid4())
    sessao = repo.obter_ou_criar_sessao(
        session_id=session_id,
        tenant_id=tenant_id,
        customer_name=body.customer_name,
        customer_external_id=body.customer_external_id,
    )
    return SessionResponse(
        session_id=sessao.session_id,
        tenant_id=sessao.tenant_id,
        customer_name=getattr(sessao, "customer_name", None) or body.customer_name,
        status=sessao.status,
        categoria_atual=sessao.categoria_atual,
        turnos_no_topico_atual=sessao.turnos_no_topico_atual or 0,
        turno_global=sessao.turno_global or 0,
        has_pending_suggestion=bool(getattr(sessao, "pending_suggestion", None)),
        requer_escalonamento_sugerido=False,
        created_at=sessao.created_at.isoformat() if getattr(sessao, "created_at", None) else _agora_iso(),
        updated_at=sessao.updated_at.isoformat() if getattr(sessao, "updated_at", None) else _agora_iso(),
    )


@router.get("/api/v1/sessions", response_model=SessionListResponse)
def listar_sessoes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> SessionListResponse:
    status_permitidos = (
        {s.strip() for s in status_filter.split(",") if s.strip()} if status_filter else None
    )
    sessoes = repo.listar_sessoes(tenant_id=tenant_id)
    if status_permitidos:
        sessoes = [s for s in sessoes if s.get("status") in status_permitidos]
    return SessionListResponse(items=[_mapear_sessao(s) for s in sessoes])


@router.get("/api/v1/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def obter_mensagens_sessao(
    session_id: str,
    view: Literal["client", "agent"] = Query(default="client"),
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> SessionMessagesResponse:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )

    mensagens_publicas = [
        PublicMessageResponse(
            message_id=m["message_id"],
            turn_number=m.get("turn_number", 1),
            sender_role=m["sender_role"],
            content=m["content"],
            created_at=m.get("created_at"),
        )
        for m in detalhe.get("mensagens", [])
    ]

    # Regra de Ouro de Privacidade: visão cliente NUNCA recebe sugestão pendente nem metadados internos
    if view == "client":
        return SessionMessagesResponse(
            session_id=session_id,
            status=detalhe["status"],
            messages=mensagens_publicas,
            pending_suggestion=None,
            categoria_atual=None,
            turnos_no_topico_atual=None,
        )

    return SessionMessagesResponse(
        session_id=session_id,
        status=detalhe["status"],
        messages=mensagens_publicas,
        pending_suggestion=detalhe.get("pending_suggestion"),
        categoria_atual=detalhe.get("categoria_atual"),
        turnos_no_topico_atual=detalhe.get("turnos_no_topico_atual", 0),
    )


@router.post(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SendMessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enviar_mensagem_cliente(
    session_id: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
    pipeline: NexusSupportPipeline = Depends(get_pipeline),
) -> SendMessageAcceptedResponse:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )

    if detalhe["status"] == "ENCERRADA":
        raise _erro_api(
            status.HTTP_409_CONFLICT,
            "SESSION_CLOSED",
            "Esta sessão já foi encerrada.",
        )

    # Sessão sob posse do Especialista N2/N3: não aciona o Copiloto N1
    if detalhe["status"] == "ESCALADA_N2":
        msg = await asyncio.to_thread(
            repo.registrar_mensagem_direta,
            session_id=session_id,
            tenant_id=tenant_id,
            sender_role="CLIENT",
            content=body.content,
        )
        payload_ws = {"session_id": session_id, **msg}
        await ws_manager.send_to_specialists(
            tenant_id=tenant_id,
            event_type="client.message_received",
            data=payload_ws,
        )
        await ws_manager.send_to_agents(
            tenant_id=tenant_id,
            event_type="client.message_received",
            data=payload_ws,
        )
        return SendMessageAcceptedResponse(
            message_id=msg["message_id"],
            session_id=session_id,
            sender_role="CLIENT",
            content=body.content,
            session_status="ESCALADA_N2",
            created_at=msg["created_at"] or _agora_iso(),
        )

    client_message_id = f"MSG-{uuid4().hex[:12]}"
    agora = _agora_iso()

    await ws_manager.send_to_agents(
        tenant_id=tenant_id,
        event_type="client.message_received",
        data={
            "session_id": session_id,
            "message_id": client_message_id,
            "content": body.content,
            "created_at": agora,
        },
    )

    background_tasks.add_task(
        _processar_copiloto_em_background,
        pipeline=pipeline,
        tenant_id=tenant_id,
        session_id=session_id,
        client_message_id=client_message_id,
        content=body.content,
    )

    return SendMessageAcceptedResponse(
        message_id=client_message_id,
        session_id=session_id,
        sender_role="CLIENT",
        content=body.content,
        session_status="IA_PROCESSANDO",
        created_at=agora,
    )


@router.post(
    "/api/v1/sessions/{session_id}/suggestions/{suggestion_id}/confirm",
    response_model=ConfirmSuggestionResponse,
)
async def confirmar_sugestao(
    session_id: str,
    suggestion_id: str,
    body: ConfirmSuggestionRequest,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
    pipeline: NexusSupportPipeline = Depends(get_pipeline),
) -> ConfirmSuggestionResponse:
    detalhe_atual = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if detalhe_atual and detalhe_atual["status"] == "ESCALADA_N2":
        raise _erro_api(
            status.HTTP_403_FORBIDDEN,
            "SESSION_ESCALATED",
            "Sessão escalada para N2/N3. O atendente N1 não pode mais enviar mensagens.",
        )

    confirmacao = ConfirmacaoHumanaSchema(
        suggestion_id=suggestion_id,
        acao_humana=body.human_action,
        mensagem_final_enviada=body.human_final_text,
        atendente_id=body.attendant_id,
    )

    try:
        resultado = await asyncio.to_thread(
            pipeline.confirmar_envio_db,
            session_id=session_id,
            confirmacao=confirmacao,
            tenant_id=tenant_id,
        )
    except KeyError as exc:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SUGGESTION_NOT_FOUND",
            str(exc),
        )

    agora = _agora_iso()
    sent_message_id = f"MSG-{uuid4().hex[:12]}"

    if resultado.acao_humana == "ESCALADA_N2":
        detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id) or {}
        # Cliente recebe apenas aviso sanitizado (sem handoff_summary, chunk_id ou auditoria)
        await ws_manager.send_to_client(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type="session.escalated",
            data={
                "session_id": session_id,
                "status": "ESCALADA_N2",
                "system_notice": resultado.mensagem_final_enviada,
            },
        )
        # N1 e Especialista N2/N3 recebem o dossiê de handoff
        payload_interno = {
            "session_id": session_id,
            "status": "ESCALADA_N2",
            "handoff_summary": resultado.handoff_summary,
            "categoria_atual": detalhe.get("categoria_atual"),
            "escalated_at": agora,
        }
        await ws_manager.send_to_agents(tenant_id=tenant_id, event_type="session.escalated", data=payload_interno)
        await ws_manager.send_to_specialists(tenant_id=tenant_id, event_type="session.escalated", data=payload_interno)
    else:
        payload_msg = {
            "session_id": session_id,
            "message_id": sent_message_id,
            "sender_role": "HUMAN_N1",
            "content": resultado.mensagem_final_enviada,
            "created_at": agora,
        }
        await ws_manager.send_to_client(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type="agent.message_sent",
            data=payload_msg,
        )
        await ws_manager.send_to_agents(
            tenant_id=tenant_id,
            event_type="agent.message_sent",
            data=payload_msg,
        )

    return ConfirmSuggestionResponse(
        suggestion_id=resultado.suggestion_id,
        message_id=sent_message_id,
        session_status=resultado.status_sessao,
        human_action=resultado.acao_humana,
        was_edited=resultado.was_edited,
        edit_ratio=resultado.edit_ratio,
        handoff_summary=resultado.handoff_summary,
        confirmed_at=agora,
    )


# ---------------------------------------------------------------------------
# Fila, Chat Direto e Dossiê do Especialista N2/N3
# ---------------------------------------------------------------------------

@router.get("/api/v1/specialist/queue", response_model=SpecialistQueueResponse)
def listar_fila_especialista(
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> SpecialistQueueResponse:
    fila = repo.listar_fila_especialista(tenant_id=tenant_id)
    return SpecialistQueueResponse(
        items=[
            SpecialistQueueItem(
                session_id=s["session_id"],
                customer_name=s.get("customer_name"),
                categoria_atual=s.get("categoria_atual"),
                turno_global=s.get("turno_global", 0),
                handoff_summary=s.get("handoff_summary"),
                escalated_at=s.get("escalated_at"),
            )
            for s in fila
        ]
    )


@router.get("/api/v1/specialist/sessions/{session_id}", response_model=SpecialistSessionDetailResponse)
def detalhar_dossie_especialista(
    session_id: str,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> SpecialistSessionDetailResponse:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )

    mensagens_raw = detalhe.get("mensagens", [])
    last_chunk_id = next(
        (m.get("chunk_id") for m in reversed(mensagens_raw) if m.get("chunk_id")),
        None,
    )
    mensagens = [
        PublicMessageResponse(
            message_id=m["message_id"],
            turn_number=m.get("turn_number", 1),
            sender_role=m["sender_role"],
            content=m["content"],
            created_at=m.get("created_at"),
        )
        for m in mensagens_raw
    ]

    return SpecialistSessionDetailResponse(
        session_id=session_id,
        customer_name=detalhe.get("customer_name"),
        status=detalhe["status"],
        categoria_atual=detalhe.get("categoria_atual"),
        turno_global=detalhe.get("turno_global", 0),
        last_chunk_id=last_chunk_id,
        auditor_escalation_reason=detalhe.get("auditor_escalation_reason"),
        handoff_summary=detalhe.get("handoff_summary"),
        escalated_at=detalhe.get("escalated_at"),
        messages=mensagens,
    )


@router.post("/api/v1/specialist/sessions/{session_id}/messages", response_model=PublicMessageResponse)
async def enviar_mensagem_especialista(
    session_id: str,
    body: SendMessageRequest,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
) -> PublicMessageResponse:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )
    if detalhe["status"] != "ESCALADA_N2":
        raise _erro_api(
            status.HTTP_409_CONFLICT,
            "SESSION_NOT_ESCALATED",
            "Apenas sessões em ESCALADA_N2 podem receber respostas do especialista.",
        )

    msg = await asyncio.to_thread(
        repo.registrar_mensagem_direta,
        session_id=session_id,
        tenant_id=tenant_id,
        sender_role="SPECIALIST_N2",
        content=body.content,
    )
    payload_ws = {"session_id": session_id, **msg}
    await ws_manager.send_to_client(
        tenant_id=tenant_id,
        session_id=session_id,
        event_type="specialist.message_sent",
        data=payload_ws,
    )
    await ws_manager.send_to_specialists(
        tenant_id=tenant_id,
        event_type="specialist.message_sent",
        data=payload_ws,
    )
    await ws_manager.send_to_agents(
        tenant_id=tenant_id,
        event_type="specialist.message_sent",
        data=payload_ws,
    )
    return PublicMessageResponse(**msg)


# ---------------------------------------------------------------------------
# Encerramento (N1, Cliente e Especialista N2/N3)
# ---------------------------------------------------------------------------

@router.post("/api/v1/sessions/{session_id}/close")
async def encerrar_sessao_n1(
    session_id: str,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
    pipeline: NexusSupportPipeline = Depends(get_pipeline),
) -> dict[str, str]:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )
    if detalhe["status"] == "ESCALADA_N2":
        raise _erro_api(
            status.HTTP_403_FORBIDDEN,
            "SESSION_ESCALATED",
            "Sessão escalada para N2/N3. Apenas o especialista ou o cliente podem encerrar.",
        )
    await asyncio.to_thread(
        pipeline.encerrar_sessao_db,
        session_id=session_id,
        tenant_id=tenant_id,
    )
    await _notificar_encerramento(tenant_id=tenant_id, session_id=session_id, closed_by="HUMAN_N1")
    return {"session_id": session_id, "status": "ENCERRADA"}


@router.post("/api/v1/sessions/{session_id}/client-close")
async def encerrar_sessao_cliente(
    session_id: str,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
    pipeline: NexusSupportPipeline = Depends(get_pipeline),
) -> dict[str, str]:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )
    await asyncio.to_thread(
        pipeline.encerrar_sessao_db,
        session_id=session_id,
        tenant_id=tenant_id,
    )
    await _notificar_encerramento(tenant_id=tenant_id, session_id=session_id, closed_by="CLIENT")
    return {"session_id": session_id, "status": "ENCERRADA"}


@router.post("/api/v1/specialist/sessions/{session_id}/resolve")
async def resolver_chamado_especialista(
    session_id: str,
    tenant_id: str = Depends(get_tenant_id),
    repo: SessionRepository = Depends(get_session_repo),
    pipeline: NexusSupportPipeline = Depends(get_pipeline),
) -> dict[str, str]:
    detalhe = repo.obter_detalhe_sessao(session_id=session_id, tenant_id=tenant_id)
    if not detalhe:
        raise _erro_api(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Sessão não localizada para o tenant informado.",
        )
    await asyncio.to_thread(
        pipeline.encerrar_sessao_db,
        session_id=session_id,
        tenant_id=tenant_id,
    )
    await _notificar_encerramento(tenant_id=tenant_id, session_id=session_id, closed_by="SPECIALIST_N2")
    return {"session_id": session_id, "status": "ENCERRADA"}


# ---------------------------------------------------------------------------
# WebSockets (Isolados por Perfil e Tenant)
# ---------------------------------------------------------------------------

@router.websocket("/ws/client/{session_id}")
async def ws_client(websocket: WebSocket, session_id: str, tenant_id: str = Query(default="default-local")) -> None:
    await ws_manager.connect_client(websocket, tenant_id=tenant_id, session_id=session_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if payload.get("type") == "typing":
                typing_data = {
                    "session_id": session_id,
                    "is_typing": bool(payload.get("is_typing")),
                }
                await ws_manager.send_to_agents(
                    tenant_id=tenant_id,
                    event_type="client.typing",
                    data=typing_data,
                )
                await ws_manager.send_to_specialists(
                    tenant_id=tenant_id,
                    event_type="client.typing",
                    data=typing_data,
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_client(websocket, tenant_id=tenant_id, session_id=session_id)


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket, tenant_id: str = Query(default="default-local")) -> None:
    await ws_manager.connect_agent(websocket, tenant_id=tenant_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if payload.get("type") == "typing" and payload.get("session_id"):
                await ws_manager.send_to_client(
                    tenant_id=tenant_id,
                    session_id=payload["session_id"],
                    event_type="agent.typing",
                    data={
                        "session_id": payload["session_id"],
                        "is_typing": bool(payload.get("is_typing")),
                    },
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_agent(websocket, tenant_id=tenant_id)


@router.websocket("/ws/specialist")
async def ws_specialist(websocket: WebSocket, tenant_id: str = Query(default="default-local")) -> None:
    await ws_manager.connect_specialist(websocket, tenant_id=tenant_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if payload.get("type") == "typing" and payload.get("session_id"):
                await ws_manager.send_to_client(
                    tenant_id=tenant_id,
                    session_id=payload["session_id"],
                    event_type="specialist.typing",
                    data={
                        "session_id": payload["session_id"],
                        "is_typing": bool(payload.get("is_typing")),
                    },
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_specialist(websocket, tenant_id=tenant_id)