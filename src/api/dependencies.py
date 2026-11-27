import os
from typing import Optional
from fastapi import Header, HTTPException, Request, status

from src.db.session_repo import SessionRepository
from src.pipeline_agents import NexusSupportPipeline

APP_ENV = os.getenv("APP_ENV", "development").lower()
DEFAULT_DEV_TENANT = "default-local"


def get_tenant_id(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID")) -> str:
    if x_tenant_id and x_tenant_id.strip():
        return x_tenant_id.strip()
    if APP_ENV in {"dev", "development", "local", "test"}:
        return DEFAULT_DEV_TENANT
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error_code": "MISSING_TENANT_ID",
            "message": "Header X-Tenant-ID é obrigatório.",
            "detail": None,
        },
    )


def get_pipeline(request: Request) -> NexusSupportPipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "PIPELINE_NOT_READY",
                "message": "Pipeline de agentes não inicializada.",
                "detail": None,
            },
        )
    return pipeline


def get_session_repo(request: Request) -> SessionRepository:
    pipeline = get_pipeline(request)
    return pipeline.session_repo