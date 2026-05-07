from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
TEST_MARKERS = ("test", "tests", "spec", "__tests__")
DOC_EXTENSIONS = {".md", ".mdx", ".txt"}
CONFIG_FILES = {
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "vite.config.ts",
    "tsconfig.json",
}
IGNORED_PARTS = {".git", ".autocore", "dist", "node_modules", "__pycache__", ".pytest_cache", "coverage"}
RISK_MARKERS = re.compile(r"\b(mocked?|fake|dummy|stub|placeholder|sample data|todo|fixme)\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _git_status(root: Path) -> list[tuple[str, str]]:
    if not (root / ".git").exists():
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    files: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or "changed"
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append((status, path.replace("\\", "/")))
    return files


def _workspace_files(root: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if len(files) >= 80:
            break
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_PARTS for part in relative_parts):
            continue
        if path.name in CONFIG_FILES or path.suffix.lower() in SOURCE_EXTENSIONS | DOC_EXTENSIONS | {".json", ".css", ".html"}:
            files.append(("workspace", _relative(path, root)))
    return files


def _category(path: str) -> str:
    name = Path(path).name
    parts = set(Path(path).parts)
    suffix = Path(path).suffix.lower()
    lowered = path.lower()
    if name in CONFIG_FILES:
        return "config"
    if any(marker in lowered for marker in TEST_MARKERS):
        return "test"
    if suffix in DOC_EXTENSIONS:
        return "docs"
    if suffix in {".tsx", ".jsx", ".css", ".html"}:
        return "product_ui"
    if suffix in SOURCE_EXTENSIONS:
        return "source"
    if "public" in parts:
        return "public_asset"
    return "project"


def _signals(root: Path, path: str, category: str) -> list[str]:
    signals: list[str] = []
    if category in {"product_ui", "source"}:
        signals.append("product code changed")
    if category == "config":
        signals.append("build or dependency config changed")
    full_path = root / path
    try:
        text = full_path.read_text(encoding="utf-8", errors="ignore")[:20000]
    except OSError:
        text = ""
    if text and RISK_MARKERS.search(text):
        signals.append("mocked or placeholder marker found")
    if category in {"product_ui", "source"} and not any(marker in path.lower() for marker in TEST_MARKERS):
        signals.append("needs test evidence")
    return signals


def _risk(category: str, signals: list[str]) -> str:
    if "mocked or placeholder marker found" in signals:
        return "high"
    if category == "config":
        return "medium"
    if category in {"product_ui", "source"}:
        return "medium"
    return "low"


def _changed_files(root: Path) -> list[dict[str, Any]]:
    raw_files = _git_status(root) or _workspace_files(root)
    changed: list[dict[str, Any]] = []
    for status, path in raw_files[:80]:
        category = _category(path)
        signals = _signals(root, path, category)
        changed.append(
            {
                "path": path,
                "status": status,
                "category": category,
                "risk": _risk(category, signals),
                "signals": signals,
            }
        )
    return changed


def public_companion_status() -> dict[str, Any]:
    return {
        "mode": "public",
        "read_only": True,
        "project": {"name": "public-demo-workspace", "path": "public-demo-workspace", "stack": "React/Vite + Python runtime"},
        "verdict": "preview_only",
        "summary": {"changed_files": 0, "high_risk_files": 0, "tests_changed": 0, "docs_changed": 0},
        "changed_files": [],
        "latest_audit": None,
        "suggested_prompt": "Clone AutoCore locally, point it at the repo Codex is editing, then audit the latest changes.",
        "next_steps": [
            {"id": "review_snapshot", "label": "Review public proof", "detail": "Use the hosted preview to understand the workflow."},
            {"id": "switch_live", "label": "Run locally with Codex", "detail": "Use npm run start:local next to your Codex workspace."},
        ],
        "created_at": utc_now(),
    }


def companion_status(project_root: str | Path, latest_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    changed = _changed_files(root)
    high_risk = [item for item in changed if item["risk"] == "high"]
    tests_changed = [item for item in changed if item["category"] == "test"]
    docs_changed = [item for item in changed if item["category"] == "docs"]
    verdict = "clean" if not changed else "needs_audit"
    if latest_audit and latest_audit.get("verdict") == "ready" and not high_risk:
        verdict = "audit_current"
    next_steps = [
        {
            "id": "audit_latest_codex_changes",
            "label": "Audit latest Codex changes",
            "detail": "Run the Build Auditor against the current working tree and store evidence.",
        },
        {
            "id": "preflight_next_prompt",
            "label": "Preflight the next Codex prompt",
            "detail": "Use Prompt Lab before asking Codex for another large change.",
        },
        {
            "id": "review_claims",
            "label": "Review what you can claim",
            "detail": "Open Audit to separate supported quality/security claims from unsupported ones.",
        },
    ]
    if high_risk:
        next_steps.insert(
            0,
            {
                "id": "inspect_high_risk_files",
                "label": "Inspect high-risk files",
                "detail": "Review files with mocked-data markers, placeholders, or product-code changes before publishing.",
            },
        )
    return {
        "mode": "live",
        "read_only": False,
        "project": {"name": root.name, "path": str(root), "stack": "local workspace"},
        "verdict": verdict,
        "summary": {
            "changed_files": len(changed),
            "high_risk_files": len(high_risk),
            "tests_changed": len(tests_changed),
            "docs_changed": len(docs_changed),
        },
        "changed_files": changed,
        "latest_audit": (
            {
                "id": latest_audit.get("id"),
                "verdict": latest_audit.get("verdict"),
                "overall": latest_audit.get("overall"),
                "created_at": latest_audit.get("created_at"),
            }
            if latest_audit
            else None
        ),
        "suggested_prompt": (
            "Audit the changed files from my latest Codex work. Focus on mocked data, missing tests, "
            "unsupported quality/security claims, risky config changes, and evidence needed before publishing."
        ),
        "next_steps": next_steps,
        "created_at": utc_now(),
    }
