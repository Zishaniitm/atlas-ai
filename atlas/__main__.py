"""
ATLAS entry point.

Boot sequence (SRS Section 4.3 — data flow, SRS 12.2 Phase 0):
  1. Register crash reporter signal handler
  2. Set up structured logging
  3. Load and validate configuration
  4. Boot into LOCKED state — PIN auth required
  5. Start FastAPI internal API server (localhost:7770)
  6. Load voice pipeline (Whisper + Kokoro + wake word)
  7. Start async event loop — ATLAS is ready

Run with:
    python -m atlas
    atlas          (after pip install -e .)

SRS: NFR-010 (cold start <=8s cloud / <=20s local),
     FR-079 (boots locked), SRS 4.2.4 (localhost:7770)
"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """
    ATLAS main entry point.

    Bootstraps crash reporter and logging before anything else,
    so any startup error is captured.

    SRS: NFR-036 (crash report written before exit)
    """
    # ── Step 1: crash reporter FIRST — catches all subsequent errors ──
    from atlas.telemetry.crash_reporter import register_handlers
    register_handlers()

    # ── Step 2: logging setup ─────────────────────────────────────────
    from atlas.utils.logging import setup_logging, get_logger
    setup_logging(dev_mode="--dev" in sys.argv)
    logger = get_logger("atlas.__main__")
    logger.info("atlas_starting", version=_get_version())

    # ── Step 3: load and validate config ──────────────────────────────
    try:
        from atlas.core.config import get_config
        cfg = get_config()
        logger.info("config_loaded", provider=cfg.llm.provider, persona=cfg.voice.persona)
    except Exception as exc:
        logger.error("config_load_failed", exc_info=exc)
        sys.exit(1)

    # ── Step 4: check auth enrolment — must enrol before first use ────
    from atlas.security.auth.pin import is_enrolled
    if not is_enrolled():
        logger.warning("no_auth_enrolled")
        print(
            "\n⚠  No authentication method enrolled.\n"
            "   ATLAS boots in LOCKED state.\n"
            "   Open the HUD settings or run: atlas setup\n"
        )

    # ── Step 5–7: run async event loop ────────────────────────────────
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("atlas_shutdown_keyboard")
    except Exception as exc:
        logger.error("atlas_fatal_error", exc_info=exc)
        sys.exit(1)


async def _async_main() -> None:
    """
    Async boot sequence — all I/O-bound startup happens here.

    SRS: NFR-010, FR-079, SRS 4.2.4
    """
    from atlas.core.config import get_config
    from atlas.core.events import get_event_bus, AtlasEvent, EventType
    from atlas.utils.logging import get_logger

    logger = get_logger("atlas._async_main")
    cfg = get_config()

    # ── FastAPI server (localhost:7770) ────────────────────────────────
    from atlas.api.server import run_server
    import asyncio

    logger.info("api_server_launching", port=cfg.api.port)
    api_task = asyncio.create_task(run_server(), name="atlas-api")

    # Brief wait so the API is up before voice pipeline tries to connect
    await asyncio.sleep(0.5)

    # ── Voice pipeline ─────────────────────────────────────────────────
    # Build a minimal LLM stub for Phase 0 — full Orchestrator in Phase 1
    from atlas.core.llm import build_llm_client
    from atlas.voice.pipeline import VoicePipeline

    # Phase 0: try to build LLM client; fall back to echo stub if no key
    try:
        api_key = _get_api_key(cfg.llm.provider)
        llm = build_llm_client(api_key=api_key)
    except RuntimeError:
        logger.warning("llm_key_not_found_using_echo_stub")
        llm = _EchoLLM()

    pipeline = VoicePipeline()
    await pipeline.start(llm_handler=llm)

    # ── Emit ATLAS_READY ───────────────────────────────────────────────
    bus = get_event_bus()
    bus.emit_nowait(AtlasEvent(EventType.ATLAS_READY, source="__main__"))
    logger.info("atlas_ready")

    # Keep running until cancelled
    try:
        await api_task
    except asyncio.CancelledError:
        pass
    finally:
        await pipeline.stop()
        bus.emit_nowait(AtlasEvent(EventType.ATLAS_SHUTDOWN, source="__main__"))
        logger.info("atlas_shutdown_complete")


def _get_api_key(provider: str) -> str | None:
    """
    Retrieve API key from OS keychain.

    SRS: NFR-015 (keys from keychain only — never from config)

    Args:
        provider: LLM provider name ('openai', 'anthropic', 'ollama').

    Returns:
        API key string or None if not found / not needed (ollama).
    """
    if provider == "ollama":
        return None

    try:
        import keyring  # type: ignore[import]
        key = keyring.get_password("atlas-ai", f"{provider}_api_key")
        return key
    except Exception:
        return None


def _get_version() -> str:
    """Return ATLAS version string."""
    try:
        import importlib.metadata
        return importlib.metadata.version("atlas-ai")
    except Exception:
        return "0.1.0-alpha"


class _EchoLLM:
    """
    Phase 0 development stub — echoes user input back.

    Replaced by full LangChain Orchestrator in Phase 1.
    Allows voice pipeline to be tested without a real API key.
    """

    async def process(self, text: str) -> str:
        """Echo the input back with a prefix."""
        return f"[Phase 0 echo] You said: {text}"


if __name__ == "__main__":
    main()
