"""TENJIN Capability Discovery and Environment Inventory.

Performs real, non-simulated discovery of system architecture, installed toolchains,
version control systems, GitHub credentials, Antigravity integration surfaces,
and security analyzers.
"""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from tenjin.core.constants import ToolStatus


@dataclass
class ToolInfo:
    """Discovered information for an individual executable tool."""
    name: str
    status: ToolStatus
    path: Optional[str] = None
    version: Optional[str] = None
    category: str = "general"
    details: Optional[str] = None


@dataclass
class HardwareResources:
    """Discovered hardware capacity."""
    cpu_count: int = 1
    total_memory_gb: float = 0.0
    free_memory_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_free_gb: float = 0.0


@dataclass
class GitHubAuthInfo:
    """Real GitHub authentication state."""
    authenticated: bool = False
    active_account: Optional[str] = None
    auth_method: Optional[str] = None
    token_scopes: List[str] = field(default_factory=list)
    raw_status: Optional[str] = None


@dataclass
class AntigravityInfo:
    """Discovered Antigravity execution capabilities."""
    available: bool = False
    cli_path: Optional[str] = None
    cli_version: Optional[str] = None
    sdk_available: bool = False
    sdk_version: Optional[str] = None
    models: List[str] = field(default_factory=list)
    supported_interfaces: List[str] = field(default_factory=list)


@dataclass
class CapabilityInventory:
    """Complete machine and environment capability report."""
    os_name: str
    os_version: str
    os_release: str
    architecture: str
    is_64bit: bool
    python_path: str
    python_version: str
    sqlite_version: str
    powershell_available: bool
    task_scheduler_available: bool
    git_path: Optional[str]
    git_version: Optional[str]
    git_user_name: Optional[str]
    git_user_email: Optional[str]
    github_cli_path: Optional[str]
    github_cli_version: Optional[str]
    github_auth: GitHubAuthInfo
    antigravity: AntigravityInfo
    hardware: HardwareResources
    tools: Dict[str, ToolInfo] = field(default_factory=dict)

    def is_tool_available(self, name: str) -> bool:
        """Check if an external tool is available on the machine."""
        tool = self.tools.get(name.lower())
        return tool is not None and tool.status == ToolStatus.AVAILABLE

    def get_tool_path(self, name: str) -> Optional[str]:
        """Return the executable path for a discovered tool."""
        tool = self.tools.get(name.lower())
        return tool.path if tool and tool.status == ToolStatus.AVAILABLE else None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize inventory to a dictionary."""
        return asdict(self)


def _run_quick(cmd: List[str], timeout: float = 6.0) -> tuple[int, str, str]:
    """Execute command safely and capture output."""
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _find_executable(name: str, extra_paths: Optional[List[str]] = None) -> Optional[str]:
    """Dynamically discover executable in PATH and common platform locations."""
    # Standard PATH lookup
    found = shutil.which(name)
    if found:
        return found

    # Windows extensions if name lacks .exe
    if platform.system() == "Windows" and not name.lower().endswith((".exe", ".cmd", ".bat")):
        for ext in [".exe", ".cmd", ".bat"]:
            found = shutil.which(name + ext)
            if found:
                return found

    # Search user-provided extra paths
    if extra_paths:
        for p in extra_paths:
            candidate = Path(p) / name
            if candidate.is_file():
                return str(candidate)
            if platform.system() == "Windows":
                for ext in [".exe", ".cmd", ".bat"]:
                    cand_ext = Path(p) / (name + ext)
                    if cand_ext.is_file():
                        return str(cand_ext)

    return None


def discover_antigravity() -> AntigravityInfo:
    """Discover real Antigravity CLI and Python SDK availability."""
    info = AntigravityInfo()
    home = Path.home()

    # Search candidate locations for agy.exe
    extra_dirs = [
        str(home / ".gemini" / "bin"),
        str(home / "AppData" / "Local" / "Programs" / "Antigravity" / "bin"),
        str(home / "AppData" / "Local" / "Programs" / "Antigravity IDE" / "bin"),
    ]
    cli_path = _find_executable("agy", extra_dirs)

    if cli_path:
        info.cli_path = cli_path
        code, out, _ = _run_quick([cli_path, "--version"])
        if code == 0 and out:
            info.available = True
            info.cli_version = out.splitlines()[0].strip()
            info.supported_interfaces.append("cli_print")
            info.supported_interfaces.append("cli_json_schema")

        # Discover live models if CLI is functional
        code, out, _ = _run_quick([cli_path, "models"], timeout=8.0)
        if code == 0 and out:
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith("Fetching"):
                    parts = line.split("\t")
                    if parts:
                        info.models.append(parts[0].strip())

    # Check for Python SDK
    try:
        import importlib.metadata
        ver = importlib.metadata.version("google-antigravity")
        info.sdk_available = True
        info.sdk_version = ver
        info.supported_interfaces.append("python_sdk")
    except Exception:
        info.sdk_available = False

    return info


def discover_github_auth(gh_path: Optional[str]) -> GitHubAuthInfo:
    """Discover GitHub CLI authentication status and account details."""
    auth = GitHubAuthInfo()
    if not gh_path:
        return auth

    code, out, err = _run_quick([gh_path, "auth", "status"])
    full_output = f"{out}\n{err}".strip()
    auth.raw_status = full_output

    if code == 0:
        auth.authenticated = True
        # Extract account username from output
        for line in full_output.splitlines():
            line = line.strip()
            if "Logged in to github.com account" in line:
                parts = line.split("Logged in to github.com account")
                if len(parts) > 1:
                    auth.active_account = parts[1].strip().split()[0].strip("()")
            elif "Token scopes:" in line:
                scopes_str = line.split("Token scopes:")[1].strip()
                auth.token_scopes = [s.strip(" '\"") for s in scopes_str.split(",") if s.strip()]
        auth.auth_method = "gh_cli_keyring"
    else:
        # Check environment variable token fallback
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            auth.authenticated = True
            auth.auth_method = "environment_token"

    return auth


def discover_hardware() -> HardwareResources:
    """Discover CPU, RAM, and Disk space metrics dynamically."""
    res = HardwareResources()
    res.cpu_count = os.cpu_count() or 1

    # Disk space using root of current drive or /
    try:
        cwd = Path.cwd()
        disk_usage = shutil.disk_usage(cwd)
        res.disk_total_gb = round(disk_usage.total / (1024 ** 3), 2)
        res.disk_free_gb = round(disk_usage.free / (1024 ** 3), 2)
    except Exception:
        pass

    # Memory discovery via platform specifics
    try:
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                res.total_memory_gb = round(stat.ullTotalPhys / (1024 ** 3), 2)
                res.free_memory_gb = round(stat.ullAvailPhys / (1024 ** 3), 2)
        else:
            # POSIX memory fallback via sysconf if available
            sysconf_fn = getattr(os, "sysconf", None)
            if callable(sysconf_fn):
                pages = sysconf_fn("SC_PHYS_PAGES")
                page_size = sysconf_fn("SC_PAGE_SIZE")
                res.total_memory_gb = round((pages * page_size) / (1024 ** 3), 2)
    except Exception:
        pass

    return res


def discover_capabilities() -> CapabilityInventory:
    """Run full environment discovery and return complete capability inventory."""
    home = Path.home()
    extra_search_dirs = [
        str(home / ".local" / "bin"),
        str(home / ".cargo" / "bin"),
        str(home / "AppData" / "Roaming" / "npm"),
        str(home / "AppData" / "Local" / "Programs" / "DockerDesktop" / "resources" / "bin"),
        str(home / ".gemini" / "bin"),
    ]
    # Add active virtual environment scripts directory if running in venv
    venv_scripts = Path(sys.prefix) / ("Scripts" if platform.system() == "Windows" else "bin")
    if venv_scripts.is_dir():
        extra_search_dirs.insert(0, str(venv_scripts))

    # Git
    git_path = _find_executable("git")
    git_ver = None
    git_user = None
    git_email = None
    if git_path:
        c, out, _ = _run_quick([git_path, "--version"])
        git_ver = out if c == 0 else None
        _, out_user, _ = _run_quick([git_path, "config", "--get", "user.name"])
        git_user = out_user or None
        _, out_email, _ = _run_quick([git_path, "config", "--get", "user.email"])
        git_email = out_email or None

    # GitHub CLI
    gh_path = _find_executable("gh")
    gh_ver = None
    if gh_path:
        c, out, _ = _run_quick([gh_path, "--version"])
        gh_ver = out.splitlines()[0] if (c == 0 and out) else None

    gh_auth = discover_github_auth(gh_path)
    antigravity_info = discover_antigravity()
    hw = discover_hardware()

    # Task scheduler check
    schtasks_path = _find_executable("schtasks")
    task_sched = schtasks_path is not None if platform.system() == "Windows" else False

    # PowerShell check
    pwsh_path = _find_executable("pwsh") or _find_executable("powershell")
    pwsh_avail = pwsh_path is not None

    # Scanners and tools to probe
    tool_specs = [
        ("pytest", "python", ["--version"]),
        ("ruff", "python", ["--version"]),
        ("black", "python", ["--version"]),
        ("mypy", "python", ["--version"]),
        ("pyright", "python", ["--version"]),
        ("bandit", "python", ["--version"]),
        ("pip-audit", "python", ["--version"]),
        ("eslint", "javascript", ["--version"]),
        ("prettier", "javascript", ["--version"]),
        ("tsc", "javascript", ["--version"]),
        ("jest", "javascript", ["--version"]),
        ("vitest", "javascript", ["--version"]),
        ("npm", "javascript", ["--version"]),
        ("pnpm", "javascript", ["--version"]),
        ("yarn", "javascript", ["--version"]),
        ("cargo", "rust", ["--version"]),
        ("go", "go", ["version"]),
        ("docker", "container", ["--version"]),
        ("gitleaks", "security", ["version"]),
        ("semgrep", "security", ["--version"]),
        ("trivy", "security", ["--version"]),
        ("codeql", "security", ["version"]),
        ("clang-tidy", "cpp", ["--version"]),
        ("cmake", "cpp", ["--version"]),
    ]

    discovered_tools: Dict[str, ToolInfo] = {}
    for tool_name, category, ver_args in tool_specs:
        path = _find_executable(tool_name, extra_search_dirs)
        if path:
            version_str = None
            code, out, _ = _run_quick([path] + ver_args, timeout=4.0)
            if code == 0 and out:
                version_str = out.splitlines()[0].strip()
            discovered_tools[tool_name] = ToolInfo(
                name=tool_name,
                status=ToolStatus.AVAILABLE,
                path=path,
                version=version_str,
                category=category,
            )
        else:
            discovered_tools[tool_name] = ToolInfo(
                name=tool_name,
                status=ToolStatus.NOT_AVAILABLE,
                category=category,
            )

    return CapabilityInventory(
        os_name=platform.system(),
        os_version=platform.version(),
        os_release=platform.release(),
        architecture=platform.machine(),
        is_64bit=sys.maxsize > 2**32,
        python_path=sys.executable,
        python_version=platform.python_version(),
        sqlite_version=sqlite3.sqlite_version,
        powershell_available=pwsh_avail,
        task_scheduler_available=task_sched,
        git_path=git_path,
        git_version=git_ver,
        git_user_name=git_user,
        git_user_email=git_email,
        github_cli_path=gh_path,
        github_cli_version=gh_ver,
        github_auth=gh_auth,
        antigravity=antigravity_info,
        hardware=hw,
        tools=discovered_tools,
    )
