"""TENJIN Repository Instructions Extractor.

Inspects `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTRIBUTING.md`, and `README.md`
to extract project conventions and style rules, while strictly enforcing prompt injection
defense and treating all file contents as untrusted data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from tenjin.security.prompt_injection import sanitize_untrusted_content

logger = logging.getLogger("tenjin.repositories.instructions")

INSTRUCTION_CANDIDATE_FILENAMES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "README.md",
]


@dataclass
class RepositoryInstructions:
    """Discovered instructions and conventions from repository documentation."""
    found_files: List[str] = field(default_factory=list)
    sanitized_text: str = ""
    security_warnings: List[str] = field(default_factory=list)
    style_rules: List[str] = field(default_factory=list)
    custom_conventions: Dict[str, str] = field(default_factory=dict)


def extract_repository_instructions(repo_path: Path) -> RepositoryInstructions:
    """Discover, read, sanitize, and extract instructions from candidate files."""
    instructions = RepositoryInstructions()
    collected_text_blocks: List[str] = []

    for rel_path in INSTRUCTION_CANDIDATE_FILENAMES:
        cand_file = repo_path / rel_path
        if cand_file.is_file():
            try:
                # Limit size to prevent memory exhaustion
                if cand_file.stat().st_size > 1024 * 1024:
                    logger.warning("Instruction file %s exceeds 1MB; skipping", rel_path)
                    continue

                raw_content = cand_file.read_text(encoding="utf-8", errors="replace")
                sanitized, warnings = sanitize_untrusted_content(raw_content, source_name=rel_path)

                instructions.found_files.append(rel_path)
                if warnings:
                    instructions.security_warnings.extend(warnings)

                collected_text_blocks.append(f"--- File: {rel_path} ---\n{sanitized}")

                # Heuristic extraction of style rules
                for line in sanitized.splitlines():
                    lower_line = line.strip().lower()
                    if any(key in lower_line for key in ["convention:", "rule:", "style:", "always:", "never:"]):
                        if len(line.strip()) < 200:
                            instructions.style_rules.append(line.strip())
            except Exception as e:
                logger.warning("Error reading instruction file %s: %s", rel_path, e)

    instructions.sanitized_text = "\n\n".join(collected_text_blocks)
    return instructions
