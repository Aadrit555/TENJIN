# TENJIN Agent Workflow & Delegation Protocol

This document explains how TENJIN prepares, bounds, delegates, and independently verifies code repairs executed by Antigravity.

---

## The Delegation Workflow

```
[Finding Approved for Repair]
              │
              ▼
  [1. Isolated Branch Created] ──► forge/<run_id>_<finding_id>
              │
              ▼
  [2. Evidence Package Built]  ──► Bounded context (snippets, tests, instructions)
              │
              ▼
  [3. Antigravity Invocaton]   ──► agy --print --json-schema ...
              │
              ▼
  [4. Schema Validation]       ──► Ensures required fields are returned
              │
              ▼
  [5. Independent Verif]       ──► Diff scope, secret scan, linters, tests, re-audit
              │
      ┌───────┴───────┐
      │               │
  [Passed]        [Failed]
      │               │
      ▼               ▼
 [Git Commit]     [Revert & Retry or Quarantine]
```

---

## 1. Context Construction & Bounded Scope

TENJIN does not dump entire repositories into the agent context. Instead, it builds an evidence package:
1. **Targeted Code Snippet**: Reads only the affected lines (±15 surrounding lines) of the target file.
2. **Finding Evidence**: The exact AST pattern, linter output, or vulnerability match.
3. **Repository Instructions**: Any project conventions extracted from `AGENTS.md` or `README.md`, protected inside untrusted XML boundaries.
4. **Allowed Scope**: Explicitly restricts the agent to modifying only the file associated with the finding.
5. **Prohibited Paths**: List of sensitive files that must never be altered.

---

## 2. Antigravity Invocation

Antigravity is invoked using the discovered local CLI:
```bash
agy --print --mode accept-edits --output-format json --json-schema schema.json --add-dir <workspace> -p <prompt>
```
All executions have strict timeouts (`agent_timeout_seconds`), validate expected account identity (`jhonbailey456@gmail.com`), and run in a scrubbed environment without access to developer credentials.

---

## 3. Independent Verification Mandate

Antigravity is never trusted as its own sole verifier. TENJIN executes an independent 6-point verification gate:
1. **File Scope**: Confirms the agent only touched files within allowed boundaries.
2. **Secret Scan**: Inspects all added lines in the git diff for credentials.
3. **Linter & Type Checks**: Runs project linters (`ruff`, `eslint`, `mypy`, `tsc`).
4. **Automated Tests**: Runs the project test suite in the isolated worktree.
5. **Re-Audit**: Re-runs the 10-layer audit engine to verify that the original finding is resolved.
6. **Regression Check**: Confirms that no new critical or high findings were introduced.

If any check fails, the commit is aborted, the workspace is cleaned safely, and the finding retry count is incremented.
