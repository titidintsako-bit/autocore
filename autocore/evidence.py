from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_evidence_files(run: dict[str, Any], evidence_dir: str | Path) -> dict[str, str]:
    target = Path(evidence_dir)
    target.mkdir(parents=True, exist_ok=True)
    markdown_path = target / f"{run['id']}.md"
    json_path = target / f"{run['id']}.json"

    completed = [command for command in run["commands"] if command["state"] == "completed"]
    blocked = [command for command in run["commands"] if command["state"] == "blocked"]

    lines = [
        f"# AutoCore Evidence Report: {run['id']}",
        "",
        f"- Goal: {run['goal']}",
        f"- Project: `{run['path']}`",
        f"- Status: `{run['status']}`",
        f"- Autonomy score: `{run['autonomy_score']}`",
        f"- Safety score: `{run['safety_score']}`",
        f"- Task pack: `{run.get('task_pack_id', 'repo-readiness')}`",
        f"- Task: `{run.get('task_id', 'build-health')}`",
        f"- Stack: `{run['inspection'].get('stack', 'Unknown')}`",
        f"- Completed commands: `{len(completed)}`",
        f"- Blocked commands: `{len(blocked)}`",
        "",
    ]
    scorecard = run.get("scorecard") or {}
    planner = run.get("planner") or {}
    prompt_evaluation = planner.get("prompt_evaluation") if planner else None
    if prompt_evaluation:
        lines.extend(
            [
                "## Prompt Lab",
                "",
                f"- Evaluation: `{prompt_evaluation.get('id', 'unknown')}`",
                f"- Verdict: `{prompt_evaluation.get('verdict', 'unknown')}`",
                f"- Score: `{prompt_evaluation.get('overall', 'unknown')}`",
                f"- Prompt preview: {prompt_evaluation.get('prompt_preview', '')}",
                f"- Token estimate: `{prompt_evaluation.get('token_forecast', {}).get('est_total_tokens', 'unknown')}`",
                f"- Provider signal: `{prompt_evaluation.get('provider_signal', {}).get('source', 'unknown')}`",
                "",
            ]
        )
        recommendations = prompt_evaluation.get("recommendations") or []
        if recommendations:
            lines.extend(["### Prompt Lab Recommendations", ""])
            for recommendation in recommendations:
                lines.append(f"- {recommendation}")
            lines.append("")
    if planner:
        lines.extend(
            [
                "## Agent Planner",
                "",
                f"- Provider: `{planner.get('provider', {}).get('name', 'unknown')}`",
                f"- Model: `{planner.get('provider', {}).get('model', 'unknown')}`",
                f"- Mode: `{planner.get('provider', {}).get('mode', 'unknown')}`",
                f"- Confidence: `{planner.get('confidence', 0)}`",
                f"- Selected command: `{ ' '.join(planner.get('selected_command', [])) }`",
                f"- Notes: {planner.get('notes', 'No planner notes captured.')}",
                "",
            ]
        )
        if planner.get("provider", {}).get("fallback_reason"):
            lines.extend(
                [
                    f"- Fallback reason: {planner['provider']['fallback_reason']}",
                    "",
                ]
            )
        if planner.get("risks"):
            lines.append("### Risk Notes")
            lines.append("")
            for risk in planner["risks"]:
                lines.append(f"- {risk}")
            lines.append("")
        if planner.get("proposals"):
            lines.append("### Command Proposals")
            lines.append("")
            for proposal in planner["proposals"]:
                state = "allowed" if proposal.get("allowed") else "blocked"
                lines.append(f"- `{proposal.get('command_text', '')}` - {state}, risk `{proposal.get('risk', 'unknown')}`")
            lines.append("")
    if scorecard:
        lines.extend(["## Scorecard", ""])
        for dimension in scorecard.get("dimensions", []):
            lines.append(
                f"- {dimension['label']}: `{dimension['score']}` "
                f"(weight `{dimension['weight']}`) - {dimension['evidence']}"
            )
        lines.append("")
    policies = [command.get("sandbox") or {} for command in run["commands"] if command.get("sandbox")]
    if policies:
        policy = policies[0]
        lines.extend(
            [
                "## Guarded Policy",
                "",
                f"- Profile: `{policy.get('profile_id', 'unknown')}`",
                f"- Control type: `{policy.get('control_type', 'guarded_policy')}`",
                f"- Containment: `{policy.get('containment', 'none')}`",
                f"- Filesystem: `{policy.get('filesystem', 'unknown')}`",
                f"- Network: `{policy.get('network', 'unknown')}`",
                f"- Secrets: `{policy.get('secrets', 'unknown')}`",
                f"- Shell: `{policy.get('shell', 'unknown')}`",
                f"- Capability: `{policy.get('capability', 'unknown')}`",
                f"- Execution warning: {policy.get('execution_warning', 'Guarded policy checks are not real OS containment.')}",
                "",
            ]
        )
        checks = policy.get("checks") or []
        if checks:
            lines.extend(["### Guarded Policy Checks", ""])
            for check in checks:
                lines.append(f"- {check.get('id', 'check')}: `{check.get('status', 'unknown')}` - {check.get('detail', '')}")
            lines.append("")
    lines.extend(["## Commands", ""])
    for command in run["commands"]:
        policy = command.get("sandbox") or {}
        lines.extend(
            [
                f"### {command['command_text']}",
                "",
                f"- State: `{command['state']}`",
                f"- Exit code: `{command['exit_code']}`",
                f"- Purpose: {command['purpose']}",
                f"- Policy: {command['policy_reason']}",
                f"- Guarded policy: `{policy.get('profile_id', 'unknown')}` / `{policy.get('capability', 'unknown')}` / containment `{policy.get('containment', 'none')}`",
                "",
                "```text",
                (command["stdout"] or command["stderr"] or "").strip()[:4000],
                "```",
                "",
            ]
        )

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps(run, indent=2), encoding="utf-8")

    return {"markdown_path": str(markdown_path), "json_path": str(json_path)}
