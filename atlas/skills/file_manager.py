"""File Manager skill. SRS: FR-020, SRS Appendix 14.1"""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class FileManagerSkill(BaseSkill):
    name: ClassVar[str] = "manage_file"
    description: ClassVar[str] = "Create, move, copy, delete, rename, or search files and folders."
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "action":  {"type": "string", "required": True,
                    "enum": ["create", "move", "copy", "delete", "rename", "search"]},
        "path":    {"type": "string", "required": True},
        "dest":    {"type": "string", "required": False},
        "pattern": {"type": "string", "required": False},
    }
    permissions: ClassVar[list[str]] = ["filesystem.read", "filesystem.write"]
    risk_level: ClassVar[str] = "high"

    async def execute(
        self,
        action: str,
        path: str,
        dest: str | None = None,
        pattern: str | None = None,
    ) -> SkillResult:
        """SRS: FR-020 — never raises; always returns SkillResult."""
        try:
            target = Path(path).expanduser().resolve()
            if action == "create":
                return self._create(target)
            if action == "delete":
                return self._delete(target)
            if action in ("move", "rename"):
                return self._move(target, dest)
            if action == "copy":
                return self._copy(target, dest)
            if action == "search":
                return self._search(target, pattern)
            return SkillResult(success=False, error=f"Unknown action: '{action}'")
        except (OSError, PermissionError) as exc:
            logger.error("file_manager_error", action=action, exc_info=exc)
            return SkillResult(success=False, error=f"File operation failed: {exc}")

    def _create(self, target: Path) -> SkillResult:
        if target.exists():
            return SkillResult(success=False, error=f"Already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch() if target.suffix else target.mkdir(parents=True, exist_ok=True)
        return SkillResult(success=True, data={"path": str(target)}, speak=f"Created {target.name}.")

    def _delete(self, target: Path) -> SkillResult:
        if not target.exists():
            return SkillResult(success=False, error=f"Not found: {target}")
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        return SkillResult(success=True, data={"path": str(target)},
                           speak=f"Deleted {target.name}.", requires_confirm=True)

    def _move(self, target: Path, dest: str | None) -> SkillResult:
        if not dest:
            return SkillResult(success=False, error="'dest' required for move/rename.")
        if not target.exists():
            return SkillResult(success=False, error=f"Not found: {target}")
        dp = Path(dest).expanduser().resolve()
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(dp))
        return SkillResult(success=True, data={"from": str(target), "to": str(dp)},
                           speak=f"Moved {target.name} to {dp.name}.")

    def _copy(self, target: Path, dest: str | None) -> SkillResult:
        if not dest:
            return SkillResult(success=False, error="'dest' required for copy.")
        if not target.exists():
            return SkillResult(success=False, error=f"Not found: {target}")
        dp = Path(dest).expanduser().resolve()
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, dp) if target.is_dir() else shutil.copy2(target, dp)
        return SkillResult(success=True, data={"from": str(target), "to": str(dp)},
                           speak=f"Copied {target.name}.")

    def _search(self, directory: Path, pattern: str | None) -> SkillResult:
        if not directory.is_dir():
            return SkillResult(success=False, error=f"Not a directory: {directory}")
        matches = [str(p) for p in directory.glob(pattern or "*") if p.is_file()]
        return SkillResult(success=True, data={"matches": matches, "count": len(matches)},
                           speak=f"Found {len(matches)} matching file(s).")
