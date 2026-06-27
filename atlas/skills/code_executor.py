"""Code Executor skill — runs Python/shell in a sandbox. SRS: FR-024"""
from __future__ import annotations
import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class CodeExecutorSkill(BaseSkill):
    name: ClassVar[str] = "run_code"
    description: ClassVar[str] = (
        "Write and execute a Python or shell script. Returns stdout, stderr, and exit code."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "language":    {"type": "string",  "required": True, "enum": ["python", "bash"]},
        "code":        {"type": "string",  "required": True},
        "timeout_sec": {"type": "integer", "required": False, "default": 30},
    }
    permissions: ClassVar[list[str]] = ["process.execute", "filesystem.write"]
    risk_level: ClassVar[str] = "critical"   # Always requires Tier 2 re-auth (FR-090)

    async def execute(
        self,
        language: str,
        code: str,
        timeout_sec: int = 30,
    ) -> SkillResult:
        """
        Run code in a temporary file subprocess — never eval().
        SRS: FR-024, NFR-018 (no eval on LLM output)
        """
        try:
            timeout_sec = max(1, min(timeout_sec, 120))
            suffix = ".py" if language == "python" else ".sh"

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = f.name

            try:
                if language == "python":
                    cmd = [sys.executable, tmp_path]
                else:
                    cmd = ["bash", tmp_path]

                t0 = asyncio.get_event_loop().time()
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout_b, stderr_b = await asyncio.wait_for(
                        proc.communicate(), timeout=float(timeout_sec)
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    return SkillResult(
                        success=False,
                        error=f"Code execution timed out after {timeout_sec}s.",
                    )

                elapsed_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                stdout = stdout_b.decode("utf-8", errors="replace").strip()
                stderr = stderr_b.decode("utf-8", errors="replace").strip()
                rc     = proc.returncode

                speak = f"Code ran in {elapsed_ms}ms with exit code {rc}."
                if stdout:
                    speak += f" Output: {stdout[:200]}"

                return SkillResult(
                    success=(rc == 0),
                    data={
                        "stdout": stdout, "stderr": stderr,
                        "return_code": rc, "execution_time_ms": elapsed_ms,
                    },
                    speak=speak,
                    error=stderr if rc != 0 else None,
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        except Exception as exc:
            logger.error("code_executor_failed", language=language, exc_info=exc)
            return SkillResult(success=False, error=f"Code execution failed: {exc}")
