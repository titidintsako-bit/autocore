from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from .connectors import connector_env
from .containment import docker_containment_status
from .inspector import inspect_project


def _tool_check(tool: str, label: str) -> dict[str, Any]:
    path = shutil.which(tool)
    return {
        "id": tool,
        "label": label,
        "status": "ready" if path else "missing",
        "detail": f"{label} is available." if path else f"{label} was not found on PATH.",
        "value": Path(path).name if path else None,
    }


def _provider_checks(env: Mapping[str, str]) -> list[dict[str, Any]]:
    providers = [
        ("openai", "OpenAI", ["OPENAI_API_KEY"]),
        ("groq", "Groq", ["GROQ_API_KEY"]),
        ("ollama", "Ollama", ["OLLAMA_HOST"]),
    ]
    checks: list[dict[str, Any]] = []
    for provider_id, label, keys in providers:
        configured = [key for key in keys if env.get(key)]
        if provider_id == "ollama" and not configured:
            configured = ["local default"] if os.environ.get("AUTOCORE_PROVIDER", "").lower() == "ollama" else []
        checks.append(
            {
                "id": provider_id,
                "label": label,
                "status": "ready" if configured else "optional",
                "detail": f"{label} provider can be used." if configured else f"{label} is optional. Add your own key when you want model critique or provider quota signals.",
                "configured": bool(configured),
                "configured_env": [] if configured == ["local default"] else configured,
            }
        )
    return checks


def _status_score(checks: list[dict[str, Any]]) -> int:
    if not checks:
        return 0
    weights = {"ready": 1.0, "optional": 0.7, "attention": 0.45, "missing": 0.0, "blocked": 0.0}
    score = sum(weights.get(str(check["status"]), 0.0) for check in checks) / len(checks)
    return round(score * 100)


def public_setup_status() -> dict[str, Any]:
    checks = [
        {
            "id": "public_snapshot",
            "label": "Public preview",
            "status": "ready",
            "detail": "This deployment is a read-only product snapshot.",
            "value": "read-only",
        },
        {
            "id": "live_runtime",
            "label": "Personal live runtime",
            "status": "optional",
            "detail": "Run AutoCore locally when you want to audit your own projects.",
            "value": None,
        },
    ]
    return {
        "mode": "public",
        "read_only": True,
        "headline": "Review the product snapshot, then run locally for real audits.",
        "project": {
            "name": "public-demo-workspace",
            "path": "public-demo-workspace",
            "exists": True,
            "stack": "React/Vite + Python runtime",
            "recommended_command": "npm run start:live",
        },
        "modes": [
            {"id": "public_snapshot", "label": "Public snapshot", "available": True, "detail": "Safe to share. No mutations."},
            {"id": "personal_live", "label": "Personal live", "available": False, "detail": "Available after cloning and running locally."},
            {"id": "contained_checks", "label": "Contained checks", "available": False, "detail": "Requires local Docker."},
        ],
        "checks": checks,
        "providers": _provider_checks({}),
        "readiness": {"score": _status_score(checks), "label": "preview ready"},
        "next_steps": [
            {"id": "review_snapshot", "label": "Review the snapshot", "detail": "Open Lab, Audit, Runs, and Evidence to see what AutoCore proves."},
            {"id": "switch_live", "label": "Use it on your own project", "detail": "Clone the repo and run npm run start:live plus npm run dev."},
        ],
    }


def live_setup_status(project_root: str | Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    resolved_env = connector_env(root, env)
    inspection = inspect_project(root) if root.exists() else {
        "stack": "Missing",
        "manifests": [],
        "scripts": {},
        "recommended_commands": [],
        "risk_surfaces": {},
    }
    docker = docker_containment_status()
    checks = [
        {
            "id": "project",
            "label": "Project folder",
            "status": "ready" if root.exists() and root.is_dir() else "blocked",
            "detail": "AutoCore can inspect this project." if root.exists() and root.is_dir() else "Choose an existing project folder.",
            "value": root.name if root.exists() else None,
        },
        {
            "id": "stack",
            "label": "Project stack",
            "status": "ready" if inspection["stack"] != "Missing" else "attention",
            "detail": f"Detected {inspection['stack']}." if inspection["stack"] != "Missing" else "AutoCore needs a recognizable project manifest.",
            "value": inspection["stack"],
        },
        _tool_check("python", "Python"),
        _tool_check("node", "Node.js"),
        {
            "id": "docker",
            "label": "Docker containment",
            "status": "ready" if docker["available"] else "optional",
            "detail": docker["notes"],
            "value": docker["engine"],
        },
    ]
    providers = _provider_checks(resolved_env)
    recommended = inspection["recommended_commands"][0] if inspection["recommended_commands"] else None
    next_steps = [
        {"id": "choose_project", "label": "Confirm project", "detail": "Make sure the selected folder is the project you want AutoCore to audit."},
        {"id": "guided_audit", "label": "Check this project", "detail": "Create a Prompt Lab score, Build Auditor scan, and approval-gated run in one click."},
        {"id": "run_prompt_lab", "label": "Preflight a custom task", "detail": "Paste a specific task into Lab when you want a narrower run."},
        {"id": "run_audit", "label": "Start a manual run", "detail": "Run a task pack directly, approve the proposed check, then review the evidence report."},
    ]
    if not any(provider["configured"] for provider in providers):
        next_steps.insert(1, {"id": "optional_byok", "label": "Optional BYOK", "detail": "Add OPENAI_API_KEY or GROQ_API_KEY only if you want model critique or provider signals."})
    return {
        "mode": "live",
        "read_only": False,
        "headline": "Point AutoCore at a project, preflight the goal, then run one guided audit.",
        "project": {
            "name": root.name,
            "path": str(root),
            "exists": root.exists(),
            "stack": inspection["stack"],
            "manifests": inspection["manifests"],
            "recommended_command": " ".join(recommended) if recommended else None,
        },
        "modes": [
            {"id": "public_snapshot", "label": "Public snapshot", "available": True, "detail": "Safe read-only product preview."},
            {"id": "personal_live", "label": "Personal live", "available": True, "detail": "Runs against your selected local project."},
            {"id": "contained_checks", "label": "Contained checks", "available": bool(docker["available"]), "detail": docker["notes"]},
        ],
        "checks": checks,
        "providers": providers,
        "readiness": {"score": _status_score(checks), "label": "ready" if _status_score(checks) >= 70 else "needs setup"},
        "next_steps": next_steps,
    }
