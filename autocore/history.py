from __future__ import annotations

from typing import Any

from .safety import command_text


def _score(run: dict[str, Any]) -> int:
    scorecard = run.get("scorecard") or {}
    return int(scorecard.get("overall", run.get("autonomy_score", 0)))


def _grade(run: dict[str, Any]) -> str:
    scorecard = run.get("scorecard") or {}
    return str(scorecard.get("grade", "unknown"))


def _provider(run: dict[str, Any]) -> str:
    provider = (run.get("planner") or {}).get("provider") or {}
    name = provider.get("name")
    model = provider.get("model")
    if name and model:
        return f"{name} / {model}"
    if name:
        return str(name)
    return "unrecorded"


def _selected_command(run: dict[str, Any]) -> str:
    planner_command = (run.get("planner") or {}).get("selected_command") or []
    if planner_command:
        return command_text(planner_command)
    commands = run.get("commands") or []
    return commands[0].get("command_text", "") if commands else ""


def _counter(run: dict[str, Any], key: str) -> int:
    scorecard = run.get("scorecard") or {}
    counters = scorecard.get("counters") or {}
    return int(counters.get(key, 0))


def _trend(delta: int) -> str:
    if delta >= 5:
        return "improving"
    if delta <= -5:
        return "regressing"
    return "stable"


def summarize_history(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_score(run) for run in runs]
    latest_score = scores[0] if scores else 0
    previous_score = scores[1] if len(scores) > 1 else latest_score
    delta = latest_score - previous_score
    average = round(sum(scores) / len(scores)) if scores else 0

    return {
        "summary": {
            "total_runs": len(runs),
            "latest_score": latest_score,
            "previous_score": previous_score,
            "score_delta": delta,
            "trend": _trend(delta),
            "average_score": average,
            "best_score": max(scores) if scores else 0,
            "worst_score": min(scores) if scores else 0,
        },
        "runs": [
            {
                "id": run["id"],
                "goal": run["goal"],
                "status": run["status"],
                "score": _score(run),
                "grade": _grade(run),
                "task_pack_id": run.get("task_pack_id", "repo-readiness"),
                "task_id": run.get("task_id", "build-health"),
                "provider": _provider(run),
                "selected_command": _selected_command(run),
                "duration_ms": _counter(run, "duration_ms"),
                "interventions": _counter(run, "interventions"),
                "blocked_actions": _counter(run, "blocked_actions"),
                "created_at": run["created_at"],
                "updated_at": run["updated_at"],
            }
            for run in runs
        ],
    }
