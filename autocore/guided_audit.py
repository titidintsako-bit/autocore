from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .build_auditor import audit_project
from .prompt_lab import evaluate_prompt
from .runner import AutoCoreRuntime
from .taskpacks import get_task, get_task_pack


DEFAULT_GUIDED_PROMPT = (
    "Audit this project for Codex-generated risks, mocked data, missing tests, unsupported quality or security "
    "claims, deployment readiness, and evidence gaps. Run only guarded local checks, keep secrets unread, and "
    "produce a clear next action for a personal BYOK user."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_model(provider: str, env: Mapping[str, str]) -> str:
    normalized = provider.lower()
    if normalized == "groq":
        return env.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    if normalized == "openai":
        return env.get("OPENAI_MODEL", "gpt-4.1-mini")
    if normalized == "ollama":
        return env.get("OLLAMA_MODEL", "llama3.1")
    return "heuristic"


def _next_action(run: dict[str, Any], audit: dict[str, Any]) -> dict[str, str]:
    command = run.get("commands", [{}])[0]
    if run.get("status") == "approval_required" and command.get("state") == "pending":
        return {
            "id": "approve_safe_check",
            "label": "Approve the guarded check",
            "detail": f"Open Runs and approve `{command.get('command_text', 'the selected command')}` to capture command evidence.",
        }
    if run.get("status") == "blocked":
        return {
            "id": "review_policy_block",
            "label": "Review the blocked command",
            "detail": "Open Runs to see why the selected command was blocked before enabling trusted project execution.",
        }
    if audit.get("verdict") != "ready":
        return {
            "id": "fix_audit_findings",
            "label": "Fix audit findings",
            "detail": "Open Audit and address mocked-data, security, or evidence gaps before making public claims.",
        }
    return {
        "id": "review_evidence",
        "label": "Review the evidence",
        "detail": "Open Evidence after the run completes and use the report as the readiness proof.",
    }


def run_guided_audit(
    runtime: AutoCoreRuntime,
    project_root: str | Path,
    body: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    request = body or {}
    values = env or os.environ
    project_path = Path(request.get("path") or project_root).expanduser().resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise ValueError("Project path must be an existing directory.")

    task_pack_id = str(request.get("task_pack_id") or "repo-readiness")
    task_id = str(request.get("task_id") or get_task_pack(task_pack_id)["default_task_id"])
    task = get_task(task_pack_id, task_id)
    provider = str(request.get("provider") or values.get("AUTOCORE_PROVIDER", "offline"))
    model = str(request.get("model") or _default_model(provider, values))
    prompt = str(request.get("prompt") or DEFAULT_GUIDED_PROMPT)

    evaluation = evaluate_prompt(
        prompt,
        task,
        provider=provider,
        model=model,
        env=values,
        critique_enabled=bool(request.get("critique_enabled")),
    )
    runtime.store.save_prompt_evaluation(evaluation)

    audit = audit_project(project_path)
    runtime.store.save_build_audit(audit)

    run = runtime.create_run(
        project_path,
        evaluation["prompt_preview"],
        command=["python", "-m", "compileall", "."],
        task_pack_id=task_pack_id,
        task_id=task_id,
        prompt_evaluation_id=evaluation["id"],
    )
    runtime.store.add_event(
        run["id"],
        "guided_audit",
        "Guided audit bundle created",
        f"Attached Prompt Lab `{evaluation['id']}` and Build Auditor `{audit['id']}` to this operator workflow.",
        "ok" if audit.get("verdict") == "ready" else "attention",
    )
    run = runtime.store.get_run(run["id"])

    return {
        "id": f"guided_{uuid.uuid4().hex[:10]}",
        "status": run["status"],
        "project": {
            "name": audit["project"]["name"],
            "path": audit["project"]["path"],
            "stack": audit["project"]["stack"],
        },
        "prompt_evaluation": evaluation,
        "build_audit": audit,
        "run": run,
        "next_action": _next_action(run, audit),
        "created_at": _utc_now(),
    }
