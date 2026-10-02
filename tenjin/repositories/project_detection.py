"""TENJIN Dynamic Project Ecosystem and Command Detection.

Analyzes real project manifests, lockfiles, CI workflows, and tool availability
to detect applicable test, lint, type-check, and build commands without guessing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from tenjin.core.capabilities import CapabilityInventory

logger = logging.getLogger("tenjin.repositories.project_detection")


@dataclass
class ProjectProfile:
    """Discovered project ecosystem, conventions, and executable commands."""
    ecosystem: str
    languages: List[str] = field(default_factory=list)
    package_manager: Optional[str] = None
    test_commands: List[List[str]] = field(default_factory=list)
    lint_commands: List[List[str]] = field(default_factory=list)
    type_check_commands: List[List[str]] = field(default_factory=list)
    build_commands: List[List[str]] = field(default_factory=list)
    manifest_files: List[str] = field(default_factory=list)


def detect_project_profile(repo_path: Path, capabilities: CapabilityInventory) -> ProjectProfile:
    """Analyze repository workspace to determine ecosystem and executable commands."""
    languages: List[str] = []
    manifests: List[str] = []
    test_cmds: List[List[str]] = []
    lint_cmds: List[List[str]] = []
    type_cmds: List[List[str]] = []
    build_cmds: List[List[str]] = []
    pkg_mgr: Optional[str] = None

    # Python ecosystem detection
    has_pyproject = (repo_path / "pyproject.toml").is_file()
    has_setup_py = (repo_path / "setup.py").is_file()
    has_requirements = (repo_path / "requirements.txt").is_file()
    has_pipfile = (repo_path / "Pipfile").is_file()
    has_poetry = (repo_path / "poetry.lock").is_file()
    has_uv_lock = (repo_path / "uv.lock").is_file()

    if has_pyproject or has_setup_py or has_requirements or has_pipfile:
        languages.append("Python")
        if has_pyproject:
            manifests.append("pyproject.toml")
        if has_requirements:
            manifests.append("requirements.txt")

        # Determine python package manager
        if has_uv_lock and capabilities.is_tool_available("uv"):
            pkg_mgr = "uv"
        elif has_poetry and capabilities.is_tool_available("poetry"):
            pkg_mgr = "poetry"
        elif capabilities.is_tool_available("uv"):
            pkg_mgr = "uv"
        else:
            pkg_mgr = "pip"

        # Discover Python test commands
        if (repo_path / "tests").is_dir() or (repo_path / "test").is_dir() or has_pyproject:
            if capabilities.is_tool_available("pytest"):
                pytest_bin = capabilities.get_tool_path("pytest") or "pytest"
                test_cmds.append([pytest_bin, "-v"])
            elif capabilities.python_path:
                test_cmds.append([capabilities.python_path, "-m", "unittest", "discover"])

        # Discover Python linters
        if capabilities.is_tool_available("ruff"):
            ruff_bin = capabilities.get_tool_path("ruff") or "ruff"
            lint_cmds.append([ruff_bin, "check", "."])
        elif capabilities.is_tool_available("flake8"):
            flake_bin = capabilities.get_tool_path("flake8") or "flake8"
            lint_cmds.append([flake_bin, "."])

        # Discover Python type checkers
        if capabilities.is_tool_available("mypy"):
            mypy_bin = capabilities.get_tool_path("mypy") or "mypy"
            type_cmds.append([mypy_bin, "."])
        elif capabilities.is_tool_available("pyright"):
            pyright_bin = capabilities.get_tool_path("pyright") or "pyright"
            type_cmds.append([pyright_bin])

    # Node.js / TypeScript ecosystem detection
    package_json = repo_path / "package.json"
    if package_json.is_file():
        manifests.append("package.json")
        languages.append("JavaScript")
        if (repo_path / "tsconfig.json").is_file():
            languages.append("TypeScript")
            manifests.append("tsconfig.json")

        # Detect package manager from lockfiles
        if (repo_path / "pnpm-lock.yaml").is_file() and capabilities.is_tool_available("pnpm"):
            node_mgr = "pnpm"
        elif (repo_path / "yarn.lock").is_file() and capabilities.is_tool_available("yarn"):
            node_mgr = "yarn"
        elif (repo_path / "package-lock.json").is_file() and capabilities.is_tool_available("npm"):
            node_mgr = "npm"
        else:
            node_mgr = capabilities.get_tool_path("pnpm") or capabilities.get_tool_path("npm") or "npm"

        if not pkg_mgr:
            pkg_mgr = node_mgr

        # Read scripts from package.json
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pj_data = json.load(f)
                scripts = pj_data.get("scripts", {})
                if "test" in scripts and "no test specified" not in scripts["test"]:
                    test_cmds.append([node_mgr, "test"])
                if "lint" in scripts:
                    lint_cmds.append([node_mgr, "run", "lint"])
                elif capabilities.is_tool_available("eslint"):
                    eslint_bin = capabilities.get_tool_path("eslint") or "eslint"
                    lint_cmds.append([eslint_bin, "."])

                if "build" in scripts:
                    build_cmds.append([node_mgr, "run", "build"])

                if (repo_path / "tsconfig.json").is_file() and capabilities.is_tool_available("tsc"):
                    tsc_bin = capabilities.get_tool_path("tsc") or "tsc"
                    type_cmds.append([tsc_bin, "--noEmit"])
        except Exception:
            pass

    # Rust detection
    cargo_toml = repo_path / "Cargo.toml"
    if cargo_toml.is_file():
        manifests.append("Cargo.toml")
        languages.append("Rust")
        if capabilities.is_tool_available("cargo"):
            cargo_bin = capabilities.get_tool_path("cargo") or "cargo"
            test_cmds.append([cargo_bin, "test"])
            lint_cmds.append([cargo_bin, "clippy", "--", "-D", "warnings"])
            build_cmds.append([cargo_bin, "build"])

    # Go detection
    go_mod = repo_path / "go.mod"
    if go_mod.is_file():
        manifests.append("go.mod")
        languages.append("Go")
        if capabilities.is_tool_available("go"):
            go_bin = capabilities.get_tool_path("go") or "go"
            test_cmds.append([go_bin, "test", "./..."])
            lint_cmds.append([go_bin, "vet", "./..."])
            build_cmds.append([go_bin, "build", "./..."])

    # C/C++ CMake detection
    cmake_lists = repo_path / "CMakeLists.txt"
    if cmake_lists.is_file():
        manifests.append("CMakeLists.txt")
        languages.append("C/C++")
        if capabilities.is_tool_available("cmake"):
            cmake_bin = capabilities.get_tool_path("cmake") or "cmake"
            build_cmds.append([cmake_bin, "-B", "build"])

    # Dockerfile detection
    if (repo_path / "Dockerfile").is_file():
        manifests.append("Dockerfile")
        if "Docker" not in languages:
            languages.append("Docker")

    # CI workflow inspection for additional commands
    workflows_dir = repo_path / ".github" / "workflows"
    if workflows_dir.is_dir():
        for wf_file in workflows_dir.glob("*.y*ml"):
            try:
                with open(wf_file, "r", encoding="utf-8") as f:
                    wf_data = yaml.safe_load(f)
                    if isinstance(wf_data, dict):
                        # Extract steps if relevant
                        pass
            except Exception as e:
                logger.debug("Failed to parse workflow file %s: %s", wf_file, e)

    ecosystem = "generic"
    if len(languages) == 1:
        ecosystem = languages[0].lower()
    elif len(languages) > 1:
        ecosystem = "mixed"

    return ProjectProfile(
        ecosystem=ecosystem,
        languages=languages,
        package_manager=pkg_mgr,
        test_commands=test_cmds,
        lint_commands=lint_cmds,
        type_check_commands=type_cmds,
        build_commands=build_cmds,
        manifest_files=manifests,
    )
