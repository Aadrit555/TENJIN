"""TENJIN Real Antigravity Agent Invocation Engine.

Dispatches bounded engineering repair tasks to the real local Antigravity CLI (`agy`)
or Python SDK. Passes strict schemas, enforces timeouts, captures output, and validates
return schemas without simulation.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

from tenjin.agents.output_parser import (
    AgentRepairResult,
    get_agent_output_json_schema,
    parse_agent_output,
)
from tenjin.core.capabilities import _find_executable
from tenjin.security.isolation import get_sanitized_environment
from tenjin.security.redaction import redact_secrets

logger = logging.getLogger("tenjin.agents.antigravity")


class AntigravityInvocationError(Exception):
    """Raised when an Antigravity execution fails or times out."""
    pass


class AntigravityRunner:
    """Executes the local Antigravity agent against an isolated workspace."""

    def __init__(self, cli_path: Optional[str] = None, timeout_seconds: float = 300.0):
        home = Path.home()
        extra_dirs = [
            str(home / ".gemini" / "bin"),
            str(home / "AppData" / "Local" / "Programs" / "Antigravity" / "bin"),
            str(home / "AppData" / "Local" / "Programs" / "Antigravity IDE" / "bin"),
        ]
        self.cli_path = cli_path or _find_executable("agy", extra_dirs)
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Check if Antigravity CLI is executable on the host."""
        return self.cli_path is not None and Path(self.cli_path).is_file()

    def run_repair_task(
        self,
        workspace_path: Path,
        task_prompt: str,
        model_name: Optional[str] = None,
    ) -> Tuple[AgentRepairResult, str, float]:
        """Invoke Antigravity CLI non-interactively with structured schema enforcement.

        Returns: (parsed_result, raw_output, duration_seconds)
        """
        if not self.is_available():
            raise AntigravityInvocationError("Antigravity CLI ('agy') is not available on this system.")

        schema = get_agent_output_json_schema()

        # Write schema to a temporary file for the CLI flag
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as schema_file:
            json.dump(schema, schema_file, indent=2)
            schema_path = schema_file.name

        cmd = [
            str(self.cli_path),
            "--print",
            "--dangerously-skip-permissions",
            "--output-format",
            "json",
            "--json-schema",
            schema_path,
            "--add-dir",
            str(workspace_path),
        ]

        if model_name:
            cmd.extend(["--model", model_name])

        cmd.extend(["-p", task_prompt])

        start_time = time.time()
        logger.info("Invoking Antigravity for workspace %s (timeout: %.1fs)", workspace_path.name, self.timeout_seconds)

        try:
            clean_env = get_sanitized_environment()
            res = subprocess.run(
                cmd,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=clean_env,
            )
            duration = round(time.time() - start_time, 2)

            raw_out = f"{res.stdout}\n{res.stderr}".strip()
            if res.returncode != 0:
                logger.error("Antigravity exited with code %d: %s", res.returncode, redact_secrets(res.stderr))
                raise AntigravityInvocationError(
                    f"Antigravity execution failed (code {res.returncode}): {redact_secrets(res.stderr)}"
                )

            parsed = parse_agent_output(res.stdout)
            return parsed, raw_out, duration

        except subprocess.TimeoutExpired as e:
            duration = round(time.time() - start_time, 2)
            raise AntigravityInvocationError(f"Antigravity execution timed out after {self.timeout_seconds} seconds") from e
        finally:
            try:
                Path(schema_path).unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Failed to clean up temporary schema file %s: %s", schema_path, e)
