"""
BaseSkill abstract class and SkillResult schema.

Every skill in ATLAS inherits from BaseSkill and is auto-discovered
at startup from the atlas/skills/ directory.

SRS: SRS Section 9.1 (Skill Interface Contract), SRS 9.2 (SkillResult),
     NFR-025 (zero core-code changes to add a skill), FR-113 (chain_to)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass
class SkillResult:
    """
    Standard return type for every skill execution.
    SRS: SRS Section 9.2
    """
    success: bool
    data: dict[str, Any] | None = None
    speak: str | None = None
    display: dict[str, Any] | None = None
    error: str | None = None
    requires_confirm: bool = False
    chain_to: str | None = None


class BaseSkill(ABC):
    """
    Abstract base class all ATLAS skills must inherit from.

    SRS: SRS Section 9.1, NFR-025

    Example:
        class WeatherSkill(BaseSkill):
            name        = "get_weather"
            description = "Fetch current weather for a city"
            parameters  = {"city": {"type": "string", "required": True}}
            permissions = ["network.outbound"]
            risk_level  = "low"

            async def execute(self, city: str) -> SkillResult:
                ...
    """
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, dict[str, Any]]] = {}
    permissions: ClassVar[list[str]] = []
    risk_level: ClassVar[RiskLevel] = "low"

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """
        Execute the skill. Must never raise — always return SkillResult.
        SRS: SRS Section 5.3, NFR-033
        """

    @classmethod
    def validate_args(cls, args: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate arguments against the parameters schema.
        SRS: SRS Section 9.1
        """
        for param_name, spec in cls.parameters.items():
            if spec.get("required") and param_name not in args:
                return False, f"Missing required parameter: '{param_name}'"
            if param_name in args and "enum" in spec:
                if args[param_name] not in spec["enum"]:
                    return False, (
                        f"Invalid value for '{param_name}': must be one of "
                        f"{spec['enum']}, got '{args[param_name]}'"
                    )
        return True, None

    @classmethod
    def to_tool_schema(cls) -> dict[str, Any]:
        """
        Convert this skill into an OpenAI-compatible tool schema.
        SRS: FR-113 (LLM tool-calling for skill dispatch)
        """
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, spec in cls.parameters.items():
            prop: dict[str, Any] = {"type": spec.get("type", "string")}
            if "enum" in spec:
                prop["enum"] = spec["enum"]
            if "default" in spec:
                prop["default"] = spec["default"]
            properties[param_name] = prop
            if spec.get("required"):
                required.append(param_name)
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
