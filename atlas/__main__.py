"""
ATLAS entry point.
Boot order: crash reporter → logging → config → auth check → memory
→ orchestrator → API server → voice pipeline → emit ATLAS_READY

SRS: NFR-010 (<=8s cold start), FR-079 (boots locked), SRS 4.3
"""
from __future__ import annotations
import asyncio
import sys


def main() -> None:
    """Synchronous entry point — wires up the event loop and boots ATLAS."""
    # 1. Crash reporter must be first (NFR-036)
    from atlas.telemetry.crash_reporter import register_handlers
    register_handlers()

    # 2. Logging (needed by everything after this)
    from atlas.utils.logging import setup_logging, get_logger
    setup_logging(dev_mode=True)
    logger = get_logger("atlas.main")
    logger.info("atlas_booting")

    # 3. Run async boot
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("atlas_shutdown_by_user")
    except Exception as exc:
        logger.error("atlas_fatal_error", exc_info=exc)
        sys.exit(1)


async def _async_main() -> None:
    """Full async boot sequence. SRS: NFR-010, FR-079, SRS 4.2"""
    from atlas.core.config import get_config
    from atlas.core.events import get_event_bus, AtlasEvent, EventType
    from atlas.utils.logging import get_logger
    logger = get_logger("atlas._main")
    cfg = get_config()

    # ── Memory ────────────────────────────────────────────────
    from atlas.memory.manager import init_memory, write_turn_fire_and_forget
    await init_memory()

    # ── Subscribe memory manager to pipeline events (BUG-09) ─
    bus = get_event_bus()

    async def _on_memory_request(event: AtlasEvent) -> None:
        """BUG-09: memory write fires AFTER TTS — never before."""
        turn = event.data.get("turn", {})
        write_turn_fire_and_forget(
            turn.get("user_text", ""),
            turn.get("atlas_text", ""),
        )

    bus.subscribe(EventType.MEMORY_WRITE_REQUEST, _on_memory_request)

    # ── Orchestrator ──────────────────────────────────────────
    from atlas.core.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    orchestrator.load_skills()
    logger.info("orchestrator_ready", skills=len(orchestrator.get_tool_schemas()))

    # ── FastAPI server ────────────────────────────────────────
    from atlas.api.server import run_server
    api_task = asyncio.create_task(run_server(), name="atlas-api")
    await asyncio.sleep(0.5)

    # ── LLM client ────────────────────────────────────────────
    try:
        import keyring  # type: ignore[import]
        api_key = keyring.get_password("atlas-ai", f"{cfg.llm.provider}_api_key")
    except Exception:
        api_key = None

    from atlas.core.llm import build_llm_client
    try:
        llm = build_llm_client(api_key=api_key)
    except RuntimeError:
        logger.warning("no_api_key_using_echo_stub")
        llm = _EchoLLM()  # type: ignore[assignment]

    # ── Wrap LLM with Orchestrator ────────────────────────────
    brain = _OrchestratingBrain(llm=llm, orchestrator=orchestrator)

    # ── Voice pipeline ────────────────────────────────────────
    from atlas.voice.pipeline import VoicePipeline
    pipeline = VoicePipeline()
    await pipeline.start(llm_handler=brain)

    # ── Auth check — boot locked if no PIN enrolled ───────────
    from atlas.security.auth.pin import is_enrolled
    if not is_enrolled():
        logger.warning("no_auth_enrolled_prompting_setup")
        await _first_run_pin_setup()
    else:
        logger.info("auth_enrolled_ready")

    bus.emit_nowait(AtlasEvent(EventType.ATLAS_READY, source="main"))
    logger.info("atlas_ready", port=cfg.api.port)
    print(f"\n🤖  ATLAS is ready. Say 'Hey Atlas' or visit http://localhost:{cfg.api.port}/docs\n")

    # ── Keep running ──────────────────────────────────────────
    try:
        await asyncio.gather(api_task, _keepalive())
    except asyncio.CancelledError:
        pass
    finally:
        await pipeline.stop()
        bus.emit_nowait(AtlasEvent(EventType.ATLAS_SHUTDOWN, source="main"))
        logger.info("atlas_stopped")


async def _first_run_pin_setup() -> None:
    """Prompt user to set a PIN on first run. SRS: FR-079, FR-080"""
    from atlas.security.auth.pin import enrol
    print("\n🔒  No authentication enrolled. Set up your PIN to continue.\n")
    while True:
        pin = input("Enter a new PIN (4–64 chars): ").strip()
        confirm = input("Confirm PIN: ").strip()
        if pin != confirm:
            print("PINs do not match. Try again.\n")
            continue
        success = await enrol(pin)
        if success:
            print("✅  PIN set successfully. ATLAS is now secured.\n")
            return
        print("PIN must be 4–64 characters. Try again.\n")


async def _keepalive() -> None:
    """Keep the event loop alive until Ctrl-C."""
    while True:
        await asyncio.sleep(3600)


class _EchoLLM:
    """Dev stub when no API key is configured."""
    async def process(self, text: str) -> str:
        return f"[ATLAS Echo] You said: {text}"


class _OrchestratingBrain:
    """
    Wraps an LLMClient + Orchestrator into the process(text) interface
    expected by the voice pipeline.

    SRS: SRS Section 4.2.2 (Orchestrator bridges L3→L2)
    """
    _SYSTEM_PROMPT = (
        "You are ATLAS, an advanced AI desktop assistant. "
        "You have access to tools for controlling the computer, searching the web, "
        "managing files, and much more. "
        "Always use the available tools to complete tasks. "
        "Be concise and natural — you speak your responses aloud."
    )

    def __init__(self, llm: object, orchestrator: "Orchestrator") -> None:  # type: ignore[name-defined]
        self._llm = llm
        self._orch = orchestrator

    async def process(self, user_text: str) -> str:
        """
        Full LLM → tool-call → skill → response cycle.
        SRS: SRS 4.3 steps 5–8
        """
        from atlas.memory.manager import get_working_memory
        from atlas.core.events import get_event_bus, AtlasEvent, EventType

        history = await get_working_memory()
        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": user_text},
        ]
        tools = self._orch.get_tool_schemas()

        # Call LLM
        response = await self._llm.complete(messages, tools=tools)
        tool_calls = response.get("tool_calls")

        if tool_calls:
            # Execute the first tool call via Orchestrator
            call = tool_calls[0]
            tool_name = call.function.name if hasattr(call, "function") else call.get("name", "")
            import json as _json
            raw_args = call.function.arguments if hasattr(call, "function") else call.get("arguments", "{}")
            args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args

            result = await self._orch.dispatch(tool_name, args)

            if result.speak:
                return result.speak
            if not result.success:
                return f"I couldn't complete that: {result.error}"

            # Give LLM the tool result to formulate a natural response
            messages.append({"role": "assistant", "content": f"Tool result: {result.data}"})
            followup = await self._llm.complete(messages)
            return followup.get("content", "Done.")

        return response.get("content", "I'm not sure how to help with that.")


if __name__ == "__main__":
    main()
