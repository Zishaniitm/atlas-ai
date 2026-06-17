"""
ATLAS internal FastAPI server — localhost:7770.

Communication backbone between the HUD (PyQt6), voice pipeline,
and LLM brain. All routes are versioned under /api/v1/.
WebSocket at /ws/conversation streams LLM tokens to the HUD.

SRS: SRS 4.2.4 (localhost:7770), SRS 4.2.6 (versioned API),
     FR-054–068 (HUD data), NFR-029 (/api/v1/ versioning)
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas.api.routes import auth, memory, personas, settings, skills
from atlas.api.websocket import router as ws_router
from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

# ── App factory ───────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    SRS: SRS 4.2.4, NFR-029 (versioned routes)

    Returns:
        Configured FastAPI instance with all routes registered.
    """
    app = FastAPI(
        title="ATLAS Internal API",
        description="Internal API for ATLAS AI Assistant — localhost only.",
        version="1.0.0",
        docs_url="/docs",       # dev only — disable in production builds
        redoc_url="/redoc",
    )

    # CORS — localhost only (NFR-015: no external access)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register versioned REST routers
    app.include_router(settings.router, prefix="/api/v1/settings",  tags=["settings"])
    app.include_router(memory.router,   prefix="/api/v1/memory",    tags=["memory"])
    app.include_router(skills.router,   prefix="/api/v1/skills",    tags=["skills"])
    app.include_router(auth.router,     prefix="/api/v1/auth",      tags=["auth"])
    app.include_router(personas.router, prefix="/api/v1/personas",  tags=["personas"])

    # WebSocket — token streaming to HUD
    app.include_router(ws_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Liveness probe — used by HUD to confirm server is up."""
        return {"status": "ok", "version": "1.0.0"}

    logger.info("fastapi_app_created")
    return app


# ── Server runner ─────────────────────────────────────────────

async def run_server() -> None:
    """
    Start the Uvicorn ASGI server.

    Called from atlas/__main__.py on startup.
    Runs on localhost:7770 — never exposed externally.

    SRS: SRS 4.2.4 (port 7770), NFR-015 (localhost only)
    """
    cfg = get_config().api
    config = uvicorn.Config(
        app=create_app(),
        host=cfg.host,
        port=cfg.port,
        log_level="warning",    # structlog handles ATLAS logging
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("api_server_starting", host=cfg.host, port=cfg.port)
    await server.serve()
