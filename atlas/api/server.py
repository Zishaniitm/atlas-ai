"""ATLAS internal FastAPI server. SRS: SRS 4.2.4 (localhost:7770), NFR-029"""
from __future__ import annotations
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="ATLAS Internal API", version="1.0.0",
                  description="Internal API — localhost only.")
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost", "http://127.0.0.1"],
                       allow_methods=["*"], allow_headers=["*"])

    from atlas.api.routes import auth, memory, personas, settings, skills
    from atlas.api.websocket import router as ws_router

    app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
    app.include_router(memory.router,   prefix="/api/v1/memory",   tags=["memory"])
    app.include_router(skills.router,   prefix="/api/v1/skills",   tags=["skills"])
    app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["auth"])
    app.include_router(personas.router, prefix="/api/v1/personas", tags=["personas"])
    app.include_router(ws_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "1.0.0"}

    return app


async def run_server() -> None:
    """SRS: SRS 4.2.4 (port 7770), NFR-015 (localhost only)"""
    cfg = get_config().api
    config = uvicorn.Config(app=create_app(), host=cfg.host, port=cfg.port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    logger.info("api_server_starting", host=cfg.host, port=cfg.port)
    await server.serve()
