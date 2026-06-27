"""Calculator skill — safe math and unit conversions. SRS: FR-026"""
from __future__ import annotations
import ast
import operator
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_OPS: dict[type, Any] = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}

_CONVERSIONS: dict[tuple[str, str], float | None] = {
    ("km", "miles"): 0.621371, ("miles", "km"): 1.60934,
    ("kg", "lb"): 2.20462,    ("lb", "kg"): 0.453592,
    ("m", "ft"): 3.28084,     ("ft", "m"): 0.3048,
    ("celsius", "fahrenheit"): None, ("fahrenheit", "celsius"): None,
}


class CalculatorSkill(BaseSkill):
    name: ClassVar[str] = "calculate"
    description: ClassVar[str] = (
        "Evaluate a math expression or convert units, e.g. '144 / 12' or '10 km to miles'."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "expression": {"type": "string", "required": True},
    }
    permissions: ClassVar[list[str]] = []
    risk_level: ClassVar[str] = "low"

    async def execute(self, expression: str) -> SkillResult:
        """SRS: FR-026, NFR-018 (safe AST eval — never eval())"""
        expression = expression.strip()
        conv = self._try_unit_conversion(expression)
        if conv:
            return conv
        try:
            tree = ast.parse(expression, mode="eval")
            result = self._safe_eval(tree.body)
            return SkillResult(success=True,
                               data={"result": result, "expression": expression},
                               speak=f"{expression} equals {result}.")
        except (SyntaxError, TypeError, ZeroDivisionError, ValueError) as exc:
            return SkillResult(success=False, error=f"Cannot evaluate '{expression}': {exc}")

    def _safe_eval(self, node: ast.AST) -> float:
        """Recursive AST evaluator — whitelisted operators only. SRS: NFR-018"""
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            fn = _OPS.get(type(node.op))
            if fn is None:
                raise TypeError(f"Unsupported operator: {type(node.op).__name__}")
            return fn(self._safe_eval(node.left), self._safe_eval(node.right))
        if isinstance(node, ast.UnaryOp):
            fn = _OPS.get(type(node.op))
            if fn is None:
                raise TypeError(f"Unsupported unary: {type(node.op).__name__}")
            return fn(self._safe_eval(node.operand))
        raise TypeError(f"Unsupported node: {type(node).__name__}")

    def _try_unit_conversion(self, expression: str) -> SkillResult | None:
        words = expression.lower().split()
        if "to" not in words:
            return None
        try:
            to_idx = words.index("to")
            value = float(words[0])
            from_unit = words[1]
            to_unit = words[to_idx + 1]
        except (ValueError, IndexError):
            return None
        if from_unit == "celsius" and to_unit == "fahrenheit":
            result = round(value * 9 / 5 + 32, 4)
        elif from_unit == "fahrenheit" and to_unit == "celsius":
            result = round((value - 32) * 5 / 9, 4)
        else:
            factor = _CONVERSIONS.get((from_unit, to_unit))
            if factor is None:
                return None
            result = round(value * factor, 4)
        return SkillResult(success=True,
                           data={"result": result, "from_unit": from_unit, "to_unit": to_unit},
                           speak=f"{value} {from_unit} is {result} {to_unit}.")
