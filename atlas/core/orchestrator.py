"""
ATLAS Orchestrator — routes LLM tool-calls to Skills in a sandboxed
subprocess, enforces permissions, intercepts Tier 2 high-risk commands,
and handles multi-step skill chaining.

SRS: SRS Section 4.2.2, FR-090, FR-113, FR-114, FR-115,
     NFR-018, NFR-023, NFR-033
"""
from __future__ import annotations
import asyncio
import importlib
import inspect
import multiprocessing
import pkgutil
from pathlib import Path
from typing import Any

import yaml

from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_CHAIN_DEPTH = 10  # FR-115: hard ceiling


# ── Skill discovery ───────────────────────────────────────────

def discover_skills() -> dict[str, type[BaseSkill]]:
    """
    Auto-discover all BaseSkill subclasses in atlas/skills/.
    SRS: NFR-025 (adding a skill requires zero core code changes)
    """
    skills_pkg = "atlas.skills"
    skills_dir = Path(__file__).parents[1] / "skills"
    manifest_path = skills_dir / "manifest.yaml"

    enabled_ids: set[str] = set()
    if manifest_path.exists():
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f) or {}
        for skill_id, cfg in manifest.get("skills", {}).items():
            if cfg.get("enabled", False):
                enabled_ids.add(skill_id)

    discovered: dict[str, type[BaseSkill]] = {}
    for module_info in pkgutil.iter_modules([str(skills_dir)]):
        if module_info.name in ("base", "__init__"):
            continue
        try:
            module = importlib.import_module(f"{skills_pkg}.{module_info.name}")
        except ImportError as exc:
            logger.warning("skill_import_failed", module=module_info.name, exc_info=exc)
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseSkill)
                and obj is not BaseSkill
                and getattr(obj, "name", None)
                and obj.name in enabled_ids
            ):
                discovered[obj.name] = obj

    logger.info("skills_discovered", count=len(discovered), skills=list(discovered.keys()))
    return discovered


# ── Subprocess sandbox ────────────────────────────────────────

def _sandbox_worker(
    skill_cls: type[BaseSkill],
    kwargs: dict[str, Any],
    result_queue: multiprocessing.Queue,
) -> None:
    """
    Entry point run inside the sandboxed subprocess.
    SRS: NFR-018 (subprocess isolation), NFR-033 (fault isolation)
    """
    try:
        instance = skill_cls()
        result = asyncio.run(instance.execute(**kwargs))
        result_queue.put(result)
    except Exception as exc:  # noqa: BLE001
        result_queue.put(SkillResult(success=False, error=f"Skill crashed: {exc}"))


async def _run_in_sandbox(
    skill_cls: type[BaseSkill],
    kwargs: dict[str, Any],
    timeout_sec: float = 30.0,
) -> SkillResult:
    """
    Run a skill in an isolated subprocess with a timeout.
    SRS: NFR-018, NFR-033
    """
    queue: multiprocessing.Queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_sandbox_worker,
        args=(skill_cls, kwargs, queue),
        daemon=True,
    )
    process.start()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(queue.get, True, timeout_sec),
            timeout=timeout_sec + 1.0,
        )
        process.join(timeout=1.0)
        return result  # type: ignore[return-value]
    except (asyncio.TimeoutError, Exception) as exc:
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
        logger.error("skill_sandbox_timeout", skill=skill_cls.name, exc_info=exc)
        return SkillResult(success=False, error=f"Skill '{skill_cls.name}' timed out.")


# ── Tier 2 auth interception ──────────────────────────────────

class Tier2AuthRequired(Exception):
    """Raised when a high-risk skill needs re-authentication."""
    def __init__(self, skill_name: str, risk_level: str) -> None:
        self.skill_name = skill_name
        self.risk_level = risk_level
        super().__init__(f"Skill '{skill_name}' (risk={risk_level}) requires re-auth.")


# ── Orchestrator ──────────────────────────────────────────────

class Orchestrator:
    """
    Routes LLM tool-calls to Skills, enforces Tier 2 auth,
    and handles multi-step skill chaining.

    SRS: SRS Section 4.2.2, FR-090, FR-113, FR-114, FR-115
    """

    def __init__(self) -> None:
        self._skills: dict[str, type[BaseSkill]] = {}
        self._tier2_verified: bool = False

    def load_skills(self) -> None:
        """Discover and register all enabled skills. SRS: NFR-025"""
        self._skills = discover_skills()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return all skills as LLM tool schemas. SRS: FR-113"""
        return [cls.to_tool_schema() for cls in self._skills.values()]

    def mark_tier2_verified(self) -> None:
        """Mark session as Tier-2-verified. SRS: FR-090"""
        self._tier2_verified = True

    def clear_tier2_verification(self) -> None:
        """Reset Tier 2 — called after each high-risk skill runs."""
        self._tier2_verified = False

    async def dispatch(
        self,
        tool_name: str,
        args: dict[str, Any],
        _depth: int = 0,
    ) -> SkillResult:
        """
        Execute a tool-call with validation, Tier 2 auth,
        sandbox, and chaining up to 10 iterations.

        SRS: FR-090, FR-113, FR-114, FR-115, NFR-018
        """
        bus = get_event_bus()

        # FR-115: iteration ceiling
        if _depth >= _MAX_CHAIN_DEPTH:
            return SkillResult(
                success=False,
                error=f"Maximum chain depth ({_MAX_CHAIN_DEPTH}) exceeded.",
            )

        skill_cls = self._skills.get(tool_name)
        if skill_cls is None:
            return SkillResult(success=False, error=f"Unknown skill: '{tool_name}'")

        # Validate args
        valid, err = skill_cls.validate_args(args)
        if not valid:
            return SkillResult(success=False, error=err)

        # FR-090: Tier 2 high-risk check
        cfg = get_config().auth
        if skill_cls.risk_level in cfg.tier2_risk_levels and not self._tier2_verified:
            bus.emit_nowait(AtlasEvent(
                EventType.TOOL_CALL_STARTED,
                data={"tool": tool_name, "blocked_pending_auth": True},
                source="orchestrator",
            ))
            return SkillResult(
                success=False,
                error="This action requires re-authentication.",
                requires_confirm=True,
            )

        # Execute in sandbox
        bus.emit_nowait(AtlasEvent(
            EventType.TOOL_CALL_STARTED,
            data={"tool": tool_name},
            source="orchestrator",
        ))
        result = await _run_in_sandbox(skill_cls, args)

        if skill_cls.risk_level in cfg.tier2_risk_levels:
            self.clear_tier2_verification()

        bus.emit_nowait(AtlasEvent(
            EventType.TOOL_CALL_FINISHED,
            data={"tool": tool_name, "success": result.success},
            source="orchestrator",
        ))

        # FR-113 / FR-114: skill chaining
        if result.success and result.chain_to:
            chained_args = result.data or {}
            chain_result = await self.dispatch(result.chain_to, chained_args, _depth + 1)
            if not chain_result.success:
                return SkillResult(
                    success=True,
                    data=result.data,
                    error=(
                        f"Completed '{tool_name}' but next step "
                        f"'{result.chain_to}' failed: {chain_result.error}"
                    ),
                    speak=(result.speak or "") + " However, I couldn't complete the next step.",
                )
            return chain_result

        return result
