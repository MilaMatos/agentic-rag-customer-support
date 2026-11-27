from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.dependencies import get_pipeline
from src.api.routes import router
from src.db.connection import criar_tabelas
from src.pipeline_agents import NexusSupportPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pipeline = None
    if get_pipeline not in app.dependency_overrides:
        criar_tabelas()
        app.state.pipeline = NexusSupportPipeline()
    try:
        yield
    finally:
        pipeline = getattr(app.state, "pipeline", None)
        if pipeline is not None:
            if hasattr(pipeline, "shutdown"):
                pipeline.shutdown(wait_pending=True)
            elif hasattr(pipeline, "aguardar_background"):
                pipeline.aguardar_background()


app = FastAPI(
    title="NexusTech Support Copilot API",
    version="1.0.0",
    description="API REST e WebSockets HITL Multi-Tenant para o NexusTech Support Copilot.",
    lifespan=lifespan,
)

cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "*").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error_code" in exc.detail:
        payload = exc.detail
    else:
        payload = {
            "error_code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "detail": None,
        }
    return JSONResponse(status_code=exc.status_code, content=payload)


app.include_router(router)