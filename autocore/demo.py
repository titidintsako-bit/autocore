from __future__ import annotations

from pathlib import Path
from typing import Any

from .history import summarize_history
from .safety import CommandPolicy, command_text
from .scoring import compute_scorecard
from .taskpacks import get_task


DEMO_RUN_ID = "demo_public_release"
DEMO_PATH = "public-demo-workspace"
DEMO_CREATED_AT = "2026-05-02T10:30:00Z"
DEMO_UPDATED_AT = "2026-05-02T10:31:12Z"


def _demo_events() -> list[dict[str, Any]]:
    return [
        {
            "id": "demo_evt_intake",
            "run_id": DEMO_RUN_ID,
            "kind": "intake",
            "title": "Public demo loaded",
            "detail": "Seeded read-only run selected for portfolio review.",
            "status": "ok",
            "created_at": DEMO_CREATED_AT,
        },
        {
            "id": "demo_evt_plan",
            "run_id": DEMO_RUN_ID,
            "kind": "plan",
            "title": "Planner proposed safe proof path",
            "detail": "Offline planner selected the local production build check and attached guarded policy checks.",
            "status": "ok",
            "created_at": "2026-05-02T10:30:18Z",
        },
        {
            "id": "demo_evt_approval",
            "run_id": DEMO_RUN_ID,
            "kind": "approval",
            "title": "Operator approval recorded",
            "detail": "Human approval was required before terminal execution.",
            "status": "ok",
            "created_at": "2026-05-02T10:30:44Z",
        },
        {
            "id": "demo_evt_execute",
            "run_id": DEMO_RUN_ID,
            "kind": "execute",
            "title": "Verification completed",
            "detail": "Command output, exit code, guarded policy profile, and scorecard were captured.",
            "status": "ok",
            "created_at": DEMO_UPDATED_AT,
        },
    ]


def _demo_stdout() -> str:
    return "\n".join(
        [
            "> autocore-command-center@0.1.0 build",
            "> tsc -b && vite build",
            "",
            "vite v7.3.2 building for production...",
            "dist/index.html  0.48 kB",
            "dist/assets/index.css  37.47 kB",
            "dist/assets/index.js  249.50 kB",
            "production build completed for public demo snapshot",
        ]
    )


def _demo_run() -> dict[str, Any]:
    task = get_task("repo-readiness", "build-health")
    command = ["npm", "run", "build"]
    decision = CommandPolicy(trust_project_scripts=True).evaluate(command)
    command_row = {
        "id": "demo_cmd_build",
        "run_id": DEMO_RUN_ID,
        "command": command,
        "command_text": command_text(command),
        "purpose": "Verify the command-center frontend can build before release.",
        "state": "completed",
        "policy_allowed": decision.allowed,
        "policy_reason": decision.reason,
        "sandbox": decision.sandbox,
        "exit_code": 0,
        "stdout": _demo_stdout(),
        "stderr": "",
        "duration_ms": 720,
        "created_at": "2026-05-02T10:30:44Z",
        "updated_at": DEMO_UPDATED_AT,
    }
    run = {
        "id": DEMO_RUN_ID,
        "path": DEMO_PATH,
        "goal": "Public autonomy readiness demo",
        "task_pack_id": task["task_pack_id"],
        "task_id": task["id"],
        "status": "evidence_ready",
        "autonomy_score": 0,
        "safety_score": 100,
        "scorecard": {},
        "inspection": {
            "stack": "React/Vite + Python runtime",
            "manifests": ["package.json", "vite.config.ts", "autocore/server.py"],
            "recommended_commands": [command],
            "risk_surfaces": {
                "has_env": False,
                "has_package_lock": True,
                "has_networked_provider": False,
                "public_demo_read_only": True,
            },
        },
        "planner": {
            "provider": {"name": "offline", "model": "heuristic", "mode": "local"},
            "goal": "Public autonomy readiness demo",
            "task_pack_id": task["task_pack_id"],
            "task_id": task["id"],
            "notes": "Snapshot mode uses seeded evidence and disables live mutations for portfolio review.",
            "risks": [
                "Do not expose local filesystem paths in public screenshots.",
                "Keep command execution behind approval in live mode.",
                "Treat provider output as a proposal, not authority.",
            ],
            "proposals": [
                {
                    "command": command,
                    "command_text": command_text(command),
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "risk": decision.risk,
                    "sandbox": decision.sandbox,
                }
            ],
            "blocked_proposals": [
                {
                    "command": ["curl", "https://example.com"],
                    "command_text": "curl https://example.com",
                    "allowed": False,
                    "reason": "Network access is denied by guarded.local.",
                    "risk": "high",
                    "sandbox": CommandPolicy().evaluate(["curl", "https://example.com"]).sandbox,
                }
            ],
            "selected_command": command,
            "confidence": 0.82,
        },
        "created_at": DEMO_CREATED_AT,
        "updated_at": DEMO_UPDATED_AT,
        "events": _demo_events(),
        "commands": [command_row],
    }
    scorecard = compute_scorecard(run, task)
    run["scorecard"] = scorecard
    run["autonomy_score"] = scorecard["overall"]
    return run


def _demo_markdown(run: dict[str, Any]) -> str:
    command = run["commands"][0]
    policy = command["sandbox"]
    checks = policy.get("checks") or []
    lines = [
        f"# AutoCore Evidence Report: {run['id']}",
        "",
        f"- Goal: {run['goal']}",
        f"- Project: `{run['path']}`",
        f"- Status: `{run['status']}`",
        f"- Autonomy score: `{run['autonomy_score']}`",
        f"- Safety score: `{run['safety_score']}`",
        f"- Task pack: `{run['task_pack_id']}`",
        f"- Task: `{run['task_id']}`",
        f"- Stack: `{run['inspection']['stack']}`",
        "",
        "## Agent Planner",
        "",
        "- Provider: `offline`",
        "- Model: `heuristic`",
        "- Mode: `local`",
        f"- Selected command: `{command['command_text']}`",
        "- Notes: Snapshot mode uses seeded evidence and disables live mutations for portfolio review.",
        "",
        "## Scorecard",
        "",
    ]
    for dimension in run["scorecard"]["dimensions"]:
        lines.append(
            f"- {dimension['label']}: `{dimension['score']}` "
            f"(weight `{dimension['weight']}`) - {dimension['evidence']}"
        )
    lines.extend(
        [
            "",
            "## Guarded Policy",
            "",
            f"- Profile: `{policy['profile_id']}`",
            f"- Control type: `{policy.get('control_type', 'guarded_policy')}`",
            f"- Containment: `{policy.get('containment', 'none')}`",
            f"- Filesystem: `{policy['filesystem']}`",
            f"- Network: `{policy['network']}`",
            f"- Secrets: `{policy['secrets']}`",
            f"- Shell: `{policy['shell']}`",
            f"- Capability: `{policy['capability']}`",
            f"- Execution warning: {policy.get('execution_warning', 'Guarded policy checks are not real OS containment.')}",
            "",
            "### Guarded Policy Checks",
            "",
        ]
    )
    for check in checks:
        lines.append(f"- {check['id']}: `{check['status']}` - {check['detail']}")
    lines.extend(
        [
            "",
            "## Commands",
            "",
            f"### {command['command_text']}",
            "",
            f"- State: `{command['state']}`",
            f"- Exit code: `{command['exit_code']}`",
            f"- Purpose: {command['purpose']}",
            f"- Policy: {command['policy_reason']}",
            f"- Guarded policy: `{policy['profile_id']}` / `{policy['capability']}` / containment `{policy.get('containment', 'none')}`",
            "",
            "```text",
            command["stdout"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _demo_evidence(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "markdown_path": ".autocore/evidence/demo_public_release.md",
        "json_path": ".autocore/evidence/demo_public_release.json",
        "markdown": _demo_markdown(run),
        "json": run,
        "summary": {
            "run_id": run["id"],
            "status": run["status"],
            "score": run["scorecard"]["overall"],
            "grade": run["scorecard"]["grade"],
            "commands": len(run["commands"]),
            "events": len(run["events"]),
            "markdown_filename": "demo_public_release.md",
            "json_filename": "demo_public_release.json",
        },
    }


def demo_snapshot(project_root: str | Path | None = None) -> dict[str, Any]:
    """Return a deterministic, sanitized demo payload for public portfolio review."""

    _ = Path(project_root).name if project_root else None
    run = _demo_run()
    return {
        "mode": "demo",
        "read_only": True,
        "public_safe": True,
        "case_study": {
            "title": "AutoCore evidence console",
            "problem": "A read-only release snapshot with task pack, guarded command policy, transcript, scorecard, and evidence bundle attached.",
            "solution": "AutoCore wraps agent plans with task packs, guarded policy, approvals, scorecards, replay, and evidence exports.",
            "proof_points": [
                "Local runtime API with SQLite run history.",
                "Approval-gated command execution with guarded policy checks.",
                "Task packs for coding, research, data, and browser workflows.",
                "Connector readiness model with read-only scopes and demo/live boundaries.",
                "Replayable evidence bundle with markdown and json output.",
                "Public-safe demo mode with seeded read-only data.",
            ],
            "next_steps": [
                "Wire authenticated read-only source connectors behind explicit scopes.",
                "Add authenticated remote demo hosting.",
                "Add richer browser replay artifacts.",
            ],
        },
        "onboarding": [
            {"title": "Open demo", "detail": "Load the UI with query parameter demo=1 to avoid live mutations."},
            {"title": "Review connectors", "detail": "Open section=connect to inspect source scopes, states, and demo/live boundaries."},
            {"title": "Inspect proof", "detail": "Review planner proposals, guarded policy checks, command output, scorecard, and report markdown."},
            {"title": "Switch to live", "detail": "Run the local backend to create real approval-gated evals."},
        ],
        "artifacts": {
            "open_ui": "http://127.0.0.1:5173/?demo=1",
            "connect_ui": "http://127.0.0.1:5173/?demo=1&section=connect",
            "api_demo": "http://127.0.0.1:8787/api/demo",
            "api_policy": "http://127.0.0.1:8787/api/policy",
            "evidence": ".autocore/evidence/demo_public_release.md",
        },
        "redactions": [
            "No local absolute paths.",
            "No secrets or provider keys.",
            "No write or approval actions in demo mode.",
        ],
        "run": run,
        "history": summarize_history([run]),
        "evidence": _demo_evidence(run),
    }
