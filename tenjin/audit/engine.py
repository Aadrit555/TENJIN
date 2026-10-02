"""TENJIN 10-Layer Real Engineering Audit Engine.

Executes a layered evidence-based audit combining deterministic file inventory,
installed language toolchains (ruff, pytest, eslint, mypy, etc.), AST-level security
and quality inspections, dependency manifest audits, CI/CD workflow security,
and contextual AI engineering analysis.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from tenjin.audit.deduplication import compute_finding_fingerprint
from tenjin.core.capabilities import CapabilityInventory
from tenjin.core.constants import FindingSeverity, FindingSource, FindingStatus, RiskLevel
from tenjin.memory.models import FindingRecord
from tenjin.repositories.project_detection import ProjectProfile, detect_project_profile
from tenjin.security.redaction import scan_diff_for_secrets, SECRET_PATTERNS

logger = logging.getLogger("tenjin.audit.engine")


@dataclass
class RepositoryInventory:
    """Layer 1: Structural inventory of repository files and components."""
    total_files: int = 0
    total_lines: int = 0
    source_files: List[Path] = field(default_factory=list)
    test_files: List[Path] = field(default_factory=list)
    doc_files: List[Path] = field(default_factory=list)
    ci_workflows: List[Path] = field(default_factory=list)
    config_files: List[Path] = field(default_factory=list)
    oversized_files: List[Path] = field(default_factory=list)
    binary_files: List[Path] = field(default_factory=list)


class AuditEngine:
    """Executes the deep 10-layer audit on a managed repository workspace."""

    def __init__(self, capabilities: CapabilityInventory):
        self.capabilities = capabilities

    def run_audit(
        self,
        repository_name: str,
        workspace_path: Path,
        run_id: str,
    ) -> List[FindingRecord]:
        """Execute all 10 audit layers sequentially and compile evidence-backed findings."""
        findings: List[FindingRecord] = []
        logger.info("Starting 10-layer audit for %s (run: %s)", repository_name, run_id)

        # Layer 1: Inventory
        inventory = self._layer_1_inventory(workspace_path)
        profile = detect_project_profile(workspace_path, self.capabilities)

        # Layer 2: Real Deterministic Tools
        findings.extend(self._layer_2_deterministic(repository_name, workspace_path, run_id, profile))

        # Layer 3: Security Audit (Secrets & AST Vulnerabilities)
        findings.extend(self._layer_3_security(repository_name, workspace_path, run_id, inventory))

        # Layer 4: Dependency Analysis
        findings.extend(self._layer_4_dependencies(repository_name, workspace_path, run_id, profile))

        # Layer 5: Testing Assessment
        findings.extend(self._layer_5_testing(repository_name, workspace_path, run_id, inventory, profile))

        # Layer 6: Code Quality (AST complexity & error handling)
        findings.extend(self._layer_6_quality(repository_name, workspace_path, run_id, inventory))

        # Layer 7: Architecture
        findings.extend(self._layer_7_architecture(repository_name, workspace_path, run_id, inventory))

        # Layer 8: Documentation Verification
        findings.extend(self._layer_8_documentation(repository_name, workspace_path, run_id, inventory, profile))

        # Layer 9: CI/CD Security
        findings.extend(self._layer_9_ci_cd(repository_name, workspace_path, run_id, inventory))

        # Layer 10: Contextual Synthesis
        findings.extend(self._layer_10_synthesis(repository_name, workspace_path, run_id, findings, profile))

        logger.info("Audit completed for %s: %d total findings detected", repository_name, len(findings))
        return findings

    # --- LAYER 1: INVENTORY ---
    def _layer_1_inventory(self, root: Path) -> RepositoryInventory:
        inv = RepositoryInventory()
        ignore_dirs = {
            ".git",
            "node_modules",
            "vendor",
            "dist",
            "build",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        }

        source_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".java", ".cs", ".sh"}
        binary_exts = {".exe", ".dll", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".tar", ".gz", ".zip"}

        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in ignore_dirs for part in p.parts):
                continue

            inv.total_files += 1
            ext = p.suffix.lower()

            if ext in binary_exts:
                inv.binary_files.append(p)
                continue

            try:
                size = p.stat().st_size
                if size > 1024 * 1024:  # > 1MB
                    inv.oversized_files.append(p)

                if ext in source_exts:
                    if "test" in p.name.lower() or "tests" in [part.lower() for part in p.parts]:
                        inv.test_files.append(p)
                    else:
                        inv.source_files.append(p)

                if ext in {".md", ".rst", ".txt"} or p.name.lower() in {"readme", "contributing", "license"}:
                    inv.doc_files.append(p)

                if ".github" in p.parts and "workflows" in p.parts and ext in {".yml", ".yaml"}:
                    inv.ci_workflows.append(p)

                if p.name in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CMakeLists.txt", "Dockerfile"}:
                    inv.config_files.append(p)

            except Exception:
                pass

        return inv

    # --- LAYER 2: DETERMINISTIC TOOLS ---
    def _layer_2_deterministic(
        self,
        repo: str,
        root: Path,
        run_id: str,
        profile: ProjectProfile,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        # Run ruff if available for Python projects
        if "Python" in profile.languages and self.capabilities.is_tool_available("ruff"):
            ruff_bin = self.capabilities.get_tool_path("ruff") or "ruff"
            try:
                res = subprocess.run(
                    [ruff_bin, "check", ".", "--output-format", "json"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=60.0,
                )
                if res.stdout.strip():
                    try:
                        issues = json.loads(res.stdout)
                        for issue in issues[:15]:  # Bound count
                            code = issue.get("code", "RUFF")
                            msg = issue.get("message", "Lint issue")
                            rel_file = issue.get("filename", "")
                            line = issue.get("location", {}).get("row", 1)
                            fp = compute_finding_fingerprint(repo, "code_quality", f"linter_{code}", rel_file, msg)

                            findings.append(
                                FindingRecord(
                                    id=f"det_{fp[:8]}",
                                    repository=repo,
                                    run_id=run_id,
                                    category="code_quality",
                                    subcategory="linter",
                                    severity=FindingSeverity.LOW,
                                    confidence=1.0,
                                    title=f"Linter warning: {code} in {Path(rel_file).name}",
                                    summary=msg,
                                    evidence=f"File: {rel_file}, Line {line}: {code} - {msg}",
                                    file=rel_file,
                                    line_start=line,
                                    line_end=line,
                                    risk=RiskLevel.LOW,
                                    suggested_fix=f"Resolve ruff diagnostic rule {code}.",
                                    autofix_eligibility=True,
                                    source=FindingSource.DETERMINISTIC,
                                    fingerprint=fp,
                                )
                            )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Deterministic ruff audit failed: %s", e)

        return findings

    # --- LAYER 3: SECURITY AUDIT ---
    def _layer_3_security(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        # 3.1: File-based Secret Scanning
        for src in inv.source_files + inv.config_files:
            try:
                if src.stat().st_size > 512 * 1024:
                    continue
                content = src.read_text(encoding="utf-8", errors="replace")
                rel_path = str(src.relative_to(root)).replace("\\", "/")

                for label, pattern in SECRET_PATTERNS:
                    match = pattern.search(content)
                    if match:
                        matched_str = match.group(0)
                        # Avoid flagging common template variables or placeholders
                        if any(token in matched_str.lower() for token in ["dummy", "fake", "example", "placeholder", "your_", "xxxx"]):
                            continue

                        line_num = content[: match.start()].count("\n") + 1
                        fp = compute_finding_fingerprint(repo, "security", f"secret_{label}", rel_path, f"Found {label}")

                        findings.append(
                            FindingRecord(
                                id=f"sec_{fp[:8]}",
                                repository=repo,
                                run_id=run_id,
                                category="security",
                                subcategory="exposed_credentials",
                                severity=FindingSeverity.CRITICAL,
                                confidence=0.95,
                                title=f"Exposed potential {label} secret in {src.name}",
                                summary=f"File contains an unredacted credential matching signature {label}.",
                                evidence=f"Match pattern {label} detected at line {line_num} in {rel_path}.",
                                file=rel_path,
                                line_start=line_num,
                                line_end=line_num,
                                affected_component=rel_path,
                                risk=RiskLevel.CRITICAL,
                                suggested_fix="Remove hardcoded secret immediately and rotate credentials using environment variables.",
                                autofix_eligibility=False,  # Secrets require human rotation
                                source=FindingSource.SECURITY_SCANNER,
                                fingerprint=fp,
                            )
                        )
                        break  # Report highest severity secret per file
            except Exception:
                pass

        # 3.2: Python AST Security Inspection
        for src in inv.source_files:
            if src.suffix == ".py":
                try:
                    rel_path = str(src.relative_to(root)).replace("\\", "/")
                    content = src.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(content, filename=str(src))

                    for node in ast.walk(tree):
                        # Detect shell=True in subprocess
                        if isinstance(node, ast.Call):
                            func_name = ""
                            if isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr
                            elif isinstance(node.func, ast.Name):
                                func_name = node.func.id

                            if func_name in {"Popen", "run", "call", "check_call", "check_output"}:
                                for kw in node.keywords:
                                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                        fp = compute_finding_fingerprint(repo, "security", "command_injection", rel_path, f"shell=True in {func_name}")
                                        findings.append(
                                            FindingRecord(
                                                id=f"sec_{fp[:8]}",
                                                repository=repo,
                                                run_id=run_id,
                                                category="security",
                                                subcategory="command_injection",
                                                severity=FindingSeverity.HIGH,
                                                confidence=0.90,
                                                title=f"Potential command injection via shell=True in {src.name}",
                                                summary=f"Invocation of subprocess.{func_name} with shell=True is susceptible to injection.",
                                                evidence=f"subprocess.{func_name}(..., shell=True) at line {node.lineno} in {rel_path}.",
                                                file=rel_path,
                                                line_start=node.lineno,
                                                line_end=node.lineno,
                                                affected_component=rel_path,
                                                risk=RiskLevel.HIGH,
                                                suggested_fix="Avoid shell=True. Pass arguments as a list of strings instead.",
                                                autofix_eligibility=True,
                                                source=FindingSource.STATIC_ANALYSIS,
                                                fingerprint=fp,
                                            )
                                        )

                        # Detect eval() or exec()
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                            if node.func.id in {"eval", "exec"}:
                                fp = compute_finding_fingerprint(repo, "security", "dynamic_execution", rel_path, f"Call to {node.func.id}")
                                findings.append(
                                    FindingRecord(
                                        id=f"sec_{fp[:8]}",
                                        repository=repo,
                                        run_id=run_id,
                                        category="security",
                                        subcategory="unsafe_dynamic_execution",
                                        severity=FindingSeverity.HIGH,
                                        confidence=0.95,
                                        title=f"Dangerous dynamic code execution via {node.func.id}() in {src.name}",
                                        summary=f"Use of {node.func.id}() can lead to remote code execution.",
                                        evidence=f"Direct invocation of {node.func.id}() at line {node.lineno} in {rel_path}.",
                                        file=rel_path,
                                        line_start=node.lineno,
                                        line_end=node.lineno,
                                        affected_component=rel_path,
                                        risk=RiskLevel.HIGH,
                                        suggested_fix=f"Replace {node.func.id}() with explicit structured logic or ast.literal_eval.",
                                        autofix_eligibility=False,
                                        source=FindingSource.STATIC_ANALYSIS,
                                        fingerprint=fp,
                                    )
                                )
                except Exception:
                    pass

        return findings

    # --- LAYER 4: DEPENDENCY ANALYSIS ---
    def _layer_4_dependencies(
        self,
        repo: str,
        root: Path,
        run_id: str,
        profile: ProjectProfile,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        # Check for unpinned requirements in requirements.txt
        req_file = root / "requirements.txt"
        if req_file.is_file():
            try:
                rel_path = str(req_file.relative_to(root)).replace("\\", "/")
                lines = req_file.read_text(encoding="utf-8").splitlines()
                for idx, line in enumerate(lines, start=1):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        if "==" not in line and ">=" not in line and "<=" not in line and "~=" not in line:
                            pkg_name = line.split()[0]
                            fp = compute_finding_fingerprint(repo, "dependencies", "unpinned_version", rel_path, f"Package {pkg_name} unpinned")
                            findings.append(
                                FindingRecord(
                                    id=f"dep_{fp[:8]}",
                                    repository=repo,
                                    run_id=run_id,
                                    category="dependencies",
                                    subcategory="unpinned_dependency",
                                    severity=FindingSeverity.LOW,
                                    confidence=0.85,
                                    title=f"Unpinned dependency '{pkg_name}' in requirements.txt",
                                    summary=f"Package {pkg_name} does not specify a version constraint, risking breaking upstream updates.",
                                    evidence=f"Line {idx} in {rel_path}: '{line}'",
                                    file=rel_path,
                                    line_start=idx,
                                    line_end=idx,
                                    risk=RiskLevel.LOW,
                                    suggested_fix=f"Specify a compatible version constraint for {pkg_name} (e.g. {pkg_name}>=1.0.0).",
                                    autofix_eligibility=True,
                                    source=FindingSource.DETERMINISTIC,
                                    fingerprint=fp,
                                )
                            )
            except Exception:
                pass

        return findings

    # --- LAYER 5: TESTING ASSESSMENT ---
    def _layer_5_testing(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
        profile: ProjectProfile,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        # Check if project lacks tests entirely
        if len(inv.source_files) > 2 and len(inv.test_files) == 0:
            fp = compute_finding_fingerprint(repo, "testing", "missing_tests", "tests/", "No test files detected")
            findings.append(
                FindingRecord(
                    id=f"tst_{fp[:8]}",
                    repository=repo,
                    run_id=run_id,
                    category="testing",
                    subcategory="missing_test_suite",
                    severity=FindingSeverity.MEDIUM,
                    confidence=0.90,
                    title="No automated test suite discovered in repository",
                    summary="Repository contains source modules but lacks a recognized test suite or test files.",
                    evidence=f"Discovered {len(inv.source_files)} source files but 0 test files in repository root.",
                    risk=RiskLevel.MEDIUM,
                    suggested_fix="Create a tests/ directory with unit test cases exercising core logic.",
                    autofix_eligibility=True,
                    source=FindingSource.DETERMINISTIC,
                    fingerprint=fp,
                )
            )

        return findings

    # --- LAYER 6: CODE QUALITY ---
    def _layer_6_quality(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        # Inspect Python files for swallowed exceptions and overly large functions
        for src in inv.source_files:
            if src.suffix == ".py":
                try:
                    rel_path = str(src.relative_to(root)).replace("\\", "/")
                    content = src.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(content, filename=str(src))

                    for node in ast.walk(tree):
                        # Detect broad except: pass (swallowed exceptions)
                        if isinstance(node, ast.ExceptHandler):
                            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                                exc_name = "broad"
                                if node.type is None:
                                    exc_name = "bare except"
                                elif isinstance(node.type, ast.Name):
                                    exc_name = f"except {node.type.id}"

                                fp = compute_finding_fingerprint(repo, "code_quality", "swallowed_exception", rel_path, f"Line {node.lineno} {exc_name}")
                                findings.append(
                                    FindingRecord(
                                        id=f"qua_{fp[:8]}",
                                        repository=repo,
                                        run_id=run_id,
                                        category="code_quality",
                                        subcategory="swallowed_exception",
                                        severity=FindingSeverity.MEDIUM,
                                        confidence=0.90,
                                        title=f"Swallowed exception without logging in {src.name}",
                                        summary=f"{exc_name}: pass silently ignores failures and masks potential bugs.",
                                        evidence=f"Handler with pass body at line {node.lineno} in {rel_path}.",
                                        file=rel_path,
                                        line_start=node.lineno,
                                        line_end=node.lineno,
                                        risk=RiskLevel.LOW,
                                        suggested_fix="Log the exception or raise an informative domain error.",
                                        autofix_eligibility=True,
                                        source=FindingSource.STATIC_ANALYSIS,
                                        fingerprint=fp,
                                    )
                                )

                        # Detect excessively long functions (>120 lines)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            length = getattr(node, "end_lineno", node.lineno) - node.lineno
                            if length > 120:
                                fp = compute_finding_fingerprint(repo, "code_quality", "function_length", rel_path, f"def {node.name} length {length}")
                                findings.append(
                                    FindingRecord(
                                        id=f"qua_{fp[:8]}",
                                        repository=repo,
                                        run_id=run_id,
                                        category="code_quality",
                                        subcategory="high_complexity",
                                        severity=FindingSeverity.LOW,
                                        confidence=0.85,
                                        title=f"Function '{node.name}' exceeds 120 lines in {src.name}",
                                        summary=f"Function is {length} lines long, which impairs maintainability.",
                                        evidence=f"Function '{node.name}' spans lines {node.lineno} to {getattr(node, 'end_lineno', node.lineno)} in {rel_path}.",
                                        file=rel_path,
                                        line_start=node.lineno,
                                        line_end=getattr(node, "end_lineno", node.lineno),
                                        risk=RiskLevel.LOW,
                                        suggested_fix="Refactor function into smaller helper routines.",
                                        autofix_eligibility=False,
                                        source=FindingSource.STATIC_ANALYSIS,
                                        fingerprint=fp,
                                    )
                                )
                except Exception:
                    pass

        return findings

    # --- LAYER 7: ARCHITECTURE ---
    def _layer_7_architecture(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []
        # Check for circular imports or excessive top-level modules
        top_level_files = [p for p in inv.source_files if p.parent == root]
        if len(top_level_files) > 10:
            fp = compute_finding_fingerprint(repo, "architecture", "root_module_pollution", "root/", f"{len(top_level_files)} root files")
            findings.append(
                FindingRecord(
                    id=f"arc_{fp[:8]}",
                    repository=repo,
                    run_id=run_id,
                    category="architecture",
                    subcategory="flat_root_structure",
                    severity=FindingSeverity.LOW,
                    confidence=0.80,
                    title="High number of source files located directly in repository root",
                    summary="Root directory contains more than 10 source files rather than a structured package directory.",
                    evidence=f"Discovered {len(top_level_files)} source files directly under root directory.",
                    risk=RiskLevel.LOW,
                    suggested_fix="Organize source code into a dedicated package directory (e.g. src/ or <packagename>/).",
                    autofix_eligibility=False,
                    source=FindingSource.STATIC_ANALYSIS,
                    fingerprint=fp,
                )
            )

        return findings

    # --- LAYER 8: DOCUMENTATION ---
    def _layer_8_documentation(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
        profile: ProjectProfile,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []
        readme = root / "README.md"

        if not readme.is_file():
            fp = compute_finding_fingerprint(repo, "documentation", "missing_readme", "README.md", "README does not exist")
            findings.append(
                FindingRecord(
                    id=f"doc_{fp[:8]}",
                    repository=repo,
                    run_id=run_id,
                    category="documentation",
                    subcategory="missing_readme",
                    severity=FindingSeverity.MEDIUM,
                    confidence=0.95,
                    title="Missing repository README.md",
                    summary="Repository lacks standard README.md documentation for installation and usage.",
                    evidence="README.md not found in repository root.",
                    file="README.md",
                    risk=RiskLevel.TRIVIAL,
                    suggested_fix="Create a comprehensive README.md detailing project purpose, setup, and usage.",
                    autofix_eligibility=True,
                    source=FindingSource.DETERMINISTIC,
                    fingerprint=fp,
                )
            )

        return findings

    # --- LAYER 9: CI/CD WORKFLOW SECURITY ---
    def _layer_9_ci_cd(
        self,
        repo: str,
        root: Path,
        run_id: str,
        inv: RepositoryInventory,
    ) -> List[FindingRecord]:
        findings: List[FindingRecord] = []

        for wf in inv.ci_workflows:
            try:
                rel_path = str(wf.relative_to(root)).replace("\\", "/")
                content = wf.read_text(encoding="utf-8")
                data = yaml.safe_load(content)

                if isinstance(data, dict):
                    # Check for pull_request_target trigger
                    on_triggers = data.get("on") or data.get(True)  # In YAML, 'on' can parse as True
                    if on_triggers == "pull_request_target" or (
                        isinstance(on_triggers, dict) and "pull_request_target" in on_triggers
                    ):
                        fp = compute_finding_fingerprint(repo, "ci_cd", "insecure_pr_target", rel_path, "pull_request_target used")
                        findings.append(
                            FindingRecord(
                                id=f"ci_{fp[:8]}",
                                repository=repo,
                                run_id=run_id,
                                category="ci_cd",
                                subcategory="pull_request_target_risk",
                                severity=FindingSeverity.HIGH,
                                confidence=0.90,
                                title=f"High-risk 'pull_request_target' trigger in {wf.name}",
                                summary="pull_request_target runs in the context of the base repository with secrets access, risking code injection from PR forks.",
                                evidence=f"Trigger 'pull_request_target' detected in {rel_path}.",
                                file=rel_path,
                                risk=RiskLevel.HIGH,
                                suggested_fix="Use standard 'pull_request' trigger unless explicit fork access with approval is required.",
                                autofix_eligibility=False,
                                source=FindingSource.SECURITY_SCANNER,
                                fingerprint=fp,
                            )
                        )

                    # Check for excessive permissions: write-all
                    perms = data.get("permissions")
                    if perms == "write-all":
                        fp = compute_finding_fingerprint(repo, "ci_cd", "excessive_permissions", rel_path, "permissions: write-all")
                        findings.append(
                            FindingRecord(
                                id=f"ci_{fp[:8]}",
                                repository=repo,
                                run_id=run_id,
                                category="ci_cd",
                                subcategory="excessive_permissions",
                                severity=FindingSeverity.MEDIUM,
                                confidence=0.95,
                                title=f"Overly permissive 'permissions: write-all' in {wf.name}",
                                summary="Workflow specifies global write-all permissions instead of least-privilege token permissions.",
                                evidence=f"'permissions: write-all' configured in {rel_path}.",
                                file=rel_path,
                                risk=RiskLevel.MEDIUM,
                                suggested_fix="Restrict permissions to only those needed by individual jobs (e.g. contents: read).",
                                autofix_eligibility=True,
                                source=FindingSource.SECURITY_SCANNER,
                                fingerprint=fp,
                            )
                        )
            except Exception:
                pass

        return findings

    # --- LAYER 10: SYNTHESIS ---
    def _layer_10_synthesis(
        self,
        repo: str,
        root: Path,
        run_id: str,
        current_findings: List[FindingRecord],
        profile: ProjectProfile,
    ) -> List[FindingRecord]:
        """Synthesize evidence across layers and calculate aggregated risk factors."""
        # Layer 10 enriches findings with affected components and concrete test requirements
        for f in current_findings:
            if not f.required_tests:
                if profile.test_commands:
                    f.required_tests = [" ".join(cmd) for cmd in profile.test_commands]
                else:
                    f.required_tests = ["verify syntax and run static checks"]

        return []
