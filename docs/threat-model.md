# TENJIN Threat Model

This document outlines potential adversarial threat vectors against TENJIN when running on developer workstations, evaluating attack paths, potential impact, implemented mitigations, and residual risks.

---

## Threat Matrix

| Threat Vector | Attack Path | Potential Impact | Implemented Mitigation | Residual Risk |
|---|---|---|---|---|
| **Prompt Injection** | Malicious instructions embedded in `README.md`, issues, comments, or docstrings trying to override agent constraints. | Agent attempts to modify unauthorized files, execute arbitrary commands, or weaken tests. | Strict instruction hierarchy, pattern defanging (`sanitize_untrusted_content`), XML untrusted data boundaries. | Novel natural language jailbreak phrasing that evades heuristics. |
| **Secret Theft / Exfiltration** | Repository script or agent attempts to print environment variables or send tokens to external servers. | Compromise of GitHub tokens, cloud API keys, SSH keys. | Subprocess environment scrubbing (`get_sanitized_environment`), centralized output redaction across all persistence channels. | Outbound network calls if workspace scripts are allowed unrestricted internet access. |
| **Malicious Build Scripts** | `setup.py`, `package.json` scripts, or `Makefile` contains trojaned commands during project build. | Execution of malicious code on workstation. | Commands are executed in isolated workspace contexts with scrubbed environment and strict execution timeouts. | Code execution is permitted to run genuine tests; sandboxing relies on OS process controls. |
| **Directory Traversal** | Agent or workspace path references `../../` to modify host system files outside workspace. | Corruption or deletion of host files. | `verify_path_containment` validates that all file targets are strictly children of `workspaces/`. | None for local filesystem paths. |
| **Unverified AI Code Changes** | Agent produces plausible-looking code that introduces subtle logic bugs or backdoors. | Silent introduction of vulnerabilities into codebase. | Independent verification engine: test suite execution, linter validation, and full 10-layer re-audit prior to commit. | Bugs not covered by existing or newly generated tests. |
| **Destructive Git Operations** | Accidental or malicious `git reset --hard` or `git clean -fd` destroys uncommitted user work. | Irreversible loss of developer source code. | Destructive git commands are strictly prohibited in the codebase; workspaces are checked for uncommitted changes. | None. |
| **Branch Overwrite / Force Push** | Agent attempts to push directly to `main` or force-push over remote commit history. | Remote repository corruption or disruption of team members. | Push operations use non-fast-forward protections; pushes directly to default branches are rejected. | None. |
| **Excessive CI Permissions** | Workflow files modified to include `permissions: write-all` or `pull_request_target`. | Fork-based repository compromise via GitHub Actions. | CI/CD layer detects and blocks high-risk workflow triggers; `.github/workflows/**` is in default protected paths. | None when protected paths policy is active. |
| **Webhook Spoofing** | Adversary sends fake GitHub webhook payloads to trigger arbitrary runs. | Resource exhaustion or unexpected automated execution. | HMAC-SHA256 signature verification using shared secret; webhook event deduplication. | Negligible if shared secret is kept private. |
| **Local Dashboard Exposure** | Dashboard server bound to `0.0.0.0` allowing local network access. | Unauthorized viewing of findings or trigger of pause/run endpoints. | Dashboard binds strictly to `127.0.0.1` (localhost) by default; no browser-to-shell bridge exists. | Host-level malware running as current user. |
