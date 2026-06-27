"""System Monitor skill — CPU, RAM, disk, battery, network. SRS: FR-025"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class SystemMonitorSkill(BaseSkill):
    name: ClassVar[str] = "get_system_info"
    description: ClassVar[str] = (
        "Report CPU usage, RAM, disk space, battery level, and network stats."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "metric": {
            "type": "string", "required": False,
            "enum": ["cpu", "ram", "disk", "battery", "network", "all"],
            "default": "all",
        },
    }
    permissions: ClassVar[list[str]] = ["system.monitor"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, metric: str = "all") -> SkillResult:
        """SRS: FR-025, SRS Appendix 14.1"""
        try:
            import psutil  # type: ignore[import]
            data: dict[str, Any] = {}
            parts: list[str] = []

            if metric in ("cpu", "all"):
                cpu = psutil.cpu_percent(interval=0.5)
                data["cpu_percent"] = cpu
                parts.append(f"CPU at {cpu}%")

            if metric in ("ram", "all"):
                vm = psutil.virtual_memory()
                data["ram"] = {
                    "total_gb": round(vm.total / 1e9, 1),
                    "used_gb":  round(vm.used  / 1e9, 1),
                    "percent":  vm.percent,
                }
                parts.append(f"RAM {vm.percent}% used")

            if metric in ("disk", "all"):
                disk = psutil.disk_usage("/")
                data["disk"] = {
                    "total_gb": round(disk.total / 1e9, 1),
                    "used_gb":  round(disk.used  / 1e9, 1),
                    "free_gb":  round(disk.free  / 1e9, 1),
                    "percent":  disk.percent,
                }
                parts.append(f"Disk {disk.percent}% used")

            if metric in ("battery", "all"):
                batt = psutil.sensors_battery()
                if batt:
                    data["battery"] = {
                        "percent":   round(batt.percent, 1),
                        "plugged_in": batt.power_plugged,
                    }
                    status = "charging" if batt.power_plugged else "on battery"
                    parts.append(f"Battery {batt.percent:.0f}% ({status})")

            if metric in ("network", "all"):
                net = psutil.net_io_counters()
                data["network"] = {
                    "sent_mb":     round(net.bytes_sent / 1e6, 1),
                    "received_mb": round(net.bytes_recv / 1e6, 1),
                }
                parts.append(
                    f"Network sent {data['network']['sent_mb']} MB, "
                    f"received {data['network']['received_mb']} MB"
                )

            speak = "System status: " + ". ".join(parts) + "." if parts else "No data."
            return SkillResult(success=True, data=data, speak=speak)

        except Exception as exc:
            logger.error("system_monitor_failed", metric=metric, exc_info=exc)
            return SkillResult(success=False, error=f"System monitor failed: {exc}")
