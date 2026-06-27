"""Volume Control skill. SRS: FR-032, SRS Appendix 14.1"""
from __future__ import annotations
import platform
import subprocess
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class VolumeControlSkill(BaseSkill):
    name: ClassVar[str] = "control_volume"
    description: ClassVar[str] = "Get or set system audio volume, or mute/unmute."
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "action": {"type": "string", "required": True,
                   "enum": ["get", "set", "mute", "unmute"]},
        "level":  {"type": "integer", "required": False},
    }
    permissions: ClassVar[list[str]] = ["audio.output"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, action: str, level: int | None = None) -> SkillResult:
        """SRS: FR-032"""
        try:
            sys = platform.system()
            if action == "get":
                return self._get_volume(sys)
            if action == "set":
                return self._set_volume(sys, level)
            if action == "mute":
                return self._mute(sys, True)
            if action == "unmute":
                return self._mute(sys, False)
            return SkillResult(success=False, error=f"Unknown action: '{action}'")
        except Exception as exc:
            logger.error("volume_failed", action=action, exc_info=exc)
            return SkillResult(success=False, error=f"Volume control failed: {exc}")

    def _get_volume(self, sys: str) -> SkillResult:
        if sys == "Windows":
            from ctypes import cast, POINTER  # type: ignore[import]
            from comtypes import CLSCTX_ALL  # type: ignore[import]
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import]
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            level = int(volume.GetMasterVolumeLevelScalar() * 100)
            return SkillResult(success=True, data={"level": level},
                               speak=f"Volume is at {level}%.")
        if sys == "Darwin":
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                    capture_output=True, text=True)
            level = int(result.stdout.strip())
            return SkillResult(success=True, data={"level": level},
                               speak=f"Volume is at {level}%.")
        # Linux
        result = subprocess.run(["amixer", "get", "Master"], capture_output=True, text=True)
        import re
        match = re.search(r"(\d+)%", result.stdout)
        level = int(match.group(1)) if match else 50
        return SkillResult(success=True, data={"level": level}, speak=f"Volume is at {level}%.")

    def _set_volume(self, sys: str, level: int | None) -> SkillResult:
        if level is None or not 0 <= level <= 100:
            return SkillResult(success=False, error="Level must be 0–100.")
        if sys == "Darwin":
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
        elif sys == "Linux":
            subprocess.run(["amixer", "set", "Master", f"{level}%"])
        else:
            from ctypes import cast, POINTER  # type: ignore[import]
            from comtypes import CLSCTX_ALL  # type: ignore[import]
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import]
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return SkillResult(success=True, data={"level": level}, speak=f"Volume set to {level}%.")

    def _mute(self, sys: str, mute: bool) -> SkillResult:
        action_str = "muted" if mute else "unmuted"
        if sys == "Darwin":
            val = "true" if mute else "false"
            subprocess.run(["osascript", "-e", f"set volume output muted {val}"])
        elif sys == "Linux":
            flag = "mute" if mute else "unmute"
            subprocess.run(["amixer", "set", "Master", flag])
        else:
            from ctypes import cast, POINTER  # type: ignore[import]
            from comtypes import CLSCTX_ALL  # type: ignore[import]
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import]
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol.SetMute(1 if mute else 0, None)
        return SkillResult(success=True, speak=f"Audio {action_str}.")
