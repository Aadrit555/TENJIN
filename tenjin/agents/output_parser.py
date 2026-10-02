"""TENJIN Agent Output Schema and Parser.

Validates structured repair output returned by Antigravity, ensuring compliance
with required engineering fields and strict schema enforcement.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

logger = logging.getLogger("tenjin.agents.parser")


class AgentRepairResult(BaseModel):
    """Structured output schema returned by the Antigravity repair agent."""
    status: str = Field(description="'success', 'invalid_finding', 'failed', or 'needs_approval'")
    validated_findings: List[str] = Field(default_factory=list)
    finding_ids: List[str] = Field(default_factory=list)
    files_changed: List[str] = Field(default_factory=list)
    tests_added: List[str] = Field(default_factory=list)
    tests_run: List[str] = Field(default_factory=list)
    tests_passed: bool = False
    tests_failed: bool = False
    verification_notes: str = ""
    risk_notes: str = ""
    remaining_issues: List[str] = Field(default_factory=list)
    suggested_commit_message: str = Field(default="fix: resolve audit finding")
    should_commit: bool = False
    should_push: bool = False
    needs_human_approval: bool = False


def get_agent_output_json_schema() -> Dict[str, Any]:
    """Return JSON Schema dict for enforcing structured agent output."""
    return AgentRepairResult.model_json_schema()


def parse_agent_output(raw_output: str) -> AgentRepairResult:
    """Parse and validate JSON agent output, handling markdown fences if present."""
    if not raw_output or not raw_output.strip():
        raise ValueError("Empty output returned from Antigravity agent")

    text = raw_output.strip()

    # Strip markdown ```json ... ``` blocks if present
    if "```json" in text:
        parts = text.split("```json")
        if len(parts) > 1:
            json_part = parts[1].split("```")[0].strip()
            text = json_part
    elif "```" in text:
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].strip()

    try:
        data = json.loads(text)
        return AgentRepairResult(**data)
    except Exception as e:
        logger.error("Failed to parse agent output as valid schema: %s", e)
        raise ValueError(f"Agent output did not match required schema: {e}") from e
