"""App Launcher skill. SRS: FR-021, SRS Appendix 14.1"""
from __future__ import annotations
import platform
import subprocess
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class AppLauncherSkill(BaseSkill):
    name: ClassVar[str] = "launch_app"
    description: ClassVar[str] = "Open, close, or focus an application by name."
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "app_name": {"type": "string", "required": True},
        "action":   {"type": "string", "required": True, "enum": ["open", "close", "focus"]},
    }
    permissions: ClassVar[list[str]] = ["process.execute"]
    risk_level: ClassVar[str] = "medium"

    async def execute(self, app_name: str, action: str) -> SkillResult:
        """SRS: FR-021"""
        try:
            sys = platform.system()
            if action == "open":
                if sys == "Windows":
                    subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)
                elif sys == "Darwin":
                    subprocess.Popen(["open", "-a", app_name])
                else:
                    subprocess.Popen([app_name.lower()])
                return SkillResult(success=True, data={"app": app_name, "action": "open"},
                                   speak=f"Opening {app_name}.")

            if action == "close":
                if sys == "Windows":
                    subprocess.run(["taskkill", "/IM", f"{app_name}.exe", "/F"], capture_output=True)
                elif sys == "Darwin":
                    subprocess.run(["osascript", "-e", f'quit app "{app_name}"'])
                else:
                    subprocess.run(["pkill", "-f", app_name])
                return SkillResult(success=True, data={"app": app_name, "action": "close"},
                                   speak=f"Closing {app_name}.")

            if action == "focus":
                if sys == "Darwin":
                    subprocess.run(["osascript", "-e",
                                    f'tell application "{app_name}" to activate'])
                    return SkillResult(success=True, speak=f"Switched to {app_name}.")
                return SkillResult(success=False,
                                   error=f"Focus not yet supported on {sys}.")

            return SkillResult(success=False, error=f"Unknown action: '{action}'")
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("app_launcher_error", app=app_name, exc_info=exc)
            return SkillResult(success=False, error=f"Could not {action} {app_name}: {exc}")
