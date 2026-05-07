from __future__ import annotations

from pathlib import Path
from typing import Sequence
from datetime import datetime, timezone

from .evidence import write_evidence_files
from .executor import CommandExecutor
from .history import summarize_history
from .inspector import inspect_project
from .planner import AgentPlanner
from .prompt_lab import evaluation_summary
from .safety import CommandPolicy
from .scoring import compute_scorecard
from .store import AutoCoreStore
from .taskpacks import default_task, get_task


DEFAULT_STATE_DIR = Path(".autocore")


class AutoCoreRuntime:
    def __init__(
        self,
        state_dir: str | Path = DEFAULT_STATE_DIR,
        store: AutoCoreStore | None = None,
        executor: CommandExecutor | None = None,
        policy: CommandPolicy | None = None,
        planner: AgentPlanner | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.store = store or AutoCoreStore(self.state_dir / "autocore.db")
        self.policy = policy or CommandPolicy()
        self.executor = executor or CommandExecutor(self.policy)
        self.planner = planner or AgentPlanner(policy=self.policy)
        self.evidence_dir = self.state_dir / "evidence"

    def create_run(
        self,
        path: str | Path,
        goal: str,
        command: Sequence[str] | None = None,
        task_pack_id: str | None = None,
        task_id: str | None = None,
        prompt_evaluation_id: str | None = None,
    ) -> dict:
        project_path = Path(path).expanduser().resolve()
        inspection = inspect_project(project_path)
        task = get_task(task_pack_id, task_id) if task_pack_id and task_id else default_task(task_pack_id)
        run_goal = goal or task["goal"]
        plan = self.planner.create_plan(run_goal, inspection, task, override_command=list(command) if command else None)
        if prompt_evaluation_id:
            plan["prompt_evaluation"] = evaluation_summary(self.store.get_prompt_evaluation(prompt_evaluation_id))
        run_id = self.store.create_run(project_path, run_goal, inspection, task["task_pack_id"], task["id"], planner=plan)
        self.store.add_event(run_id, "intake", "Goal intake", f"Created run for `{run_goal}`.", "ok")
        if prompt_evaluation_id:
            self.store.add_event(run_id, "prompt_lab", "Prompt Lab preflight attached", "Attached redacted prompt evaluation summary to this run.", "ok")
        self.store.add_event(run_id, "inspect", "Workspace inspect", f"Detected {inspection['stack']} project.", "ok")
        self.store.add_event(run_id, "plan", "Plan draft", "Prepared safe verification plan from local evidence.", "ok")

        selected = plan["selected_command"]
        decision = self.executor.policy_decision(selected, cwd=project_path)
        self.store.add_pending_command(
            run_id,
            selected,
            "Verify project health with an allowlisted local check.",
            policy_allowed=decision.allowed,
            policy_reason=decision.reason,
            sandbox=decision.sandbox,
        )
        if decision.allowed:
            self.store.add_event(run_id, "approval", "Approval required", "Safe command is waiting for operator approval.", "attention")
        else:
            self.store.add_event(run_id, "blocked", "Command blocked", decision.reason, "blocked")
            self.store.update_run(run_id, "blocked", autonomy_score=62)

        run = self.store.get_run(run_id)
        self._score(run_id)
        return self.store.get_run(run_id)

    def latest_or_seed(self, path: str | Path, goal: str) -> dict:
        existing = self.store.latest_run()
        if existing:
            return existing
        return self.create_run(path, goal)

    def run_history(self, limit: int = 25) -> dict:
        return summarize_history(self.store.list_runs(limit=limit))

    def approve_command(self, run_id: str, command_id: str) -> dict:
        command = self.store.get_command(command_id)
        if command is None or command["run_id"] != run_id:
            raise KeyError(command_id)
        if command["state"] != "pending":
            return self.store.get_run(run_id)

        run = self.store.get_run(run_id)
        decision = self.executor.policy_decision(command["command"], cwd=run["path"])
        if not decision.allowed:
            self.store.update_command_result(command_id, "blocked", None, "", decision.reason, 0)
            self.store.add_event(run_id, "blocked", "Command blocked", decision.reason, "blocked")
            self.store.update_run(run_id, "blocked", autonomy_score=62)
            return self.store.get_run(run_id)

        self.store.add_event(run_id, "approval", "Safe checks approved", "Operator approved allowlisted command execution.", "ok")
        result = self.executor.run(command["command"], cwd=run["path"])
        state = "completed" if result.exit_code == 0 else "failed"
        self.store.update_command_result(
            command_id,
            state,
            result.exit_code,
            result.stdout,
            result.stderr,
            result.duration_ms,
        )
        self.store.add_event(
            run_id,
            "execute",
            "Command executed" if state == "completed" else "Command failed",
            f"`{command['command_text']}` exited with {result.exit_code}.",
            "ok" if state == "completed" else "attention",
        )
        self.store.update_run(run_id, "evidence_ready" if state == "completed" else "failed", autonomy_score=81 if state == "completed" else 58)
        self._score(run_id)
        self.write_evidence(run_id)
        return self.store.get_run(run_id)

    def hold_command(self, run_id: str, command_id: str) -> dict:
        command = self.store.get_command(command_id)
        if command is None or command["run_id"] != run_id:
            raise KeyError(command_id)
        self.store.update_command_result(command_id, "blocked", None, "", "Operator held execution.", 0)
        self.store.add_event(run_id, "hold", "Execution held", "Operator kept the command paused.", "attention")
        self.store.update_run(run_id, "blocked", autonomy_score=68)
        self._score(run_id)
        return self.store.get_run(run_id)

    def write_evidence(self, run_id: str) -> dict[str, str]:
        return write_evidence_files(self.store.get_run(run_id), self.evidence_dir)

    def evidence_bundle(self, run_id: str) -> dict:
        paths = self.write_evidence(run_id)
        run = self.store.get_run(run_id)
        markdown_path = Path(paths["markdown_path"])
        json_path = Path(paths["json_path"])
        scorecard = run.get("scorecard") or {}
        return {
            **paths,
            "markdown": markdown_path.read_text(encoding="utf-8"),
            "json": self.store.get_run(run_id),
            "summary": {
                "run_id": run_id,
                "status": run["status"],
                "score": run["autonomy_score"],
                "grade": scorecard.get("grade", "unknown"),
                "commands": len(run.get("commands", [])),
                "events": len(run.get("events", [])),
                "markdown_filename": markdown_path.name,
                "json_filename": json_path.name,
            },
        }

    def evidence_library(self) -> dict:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        reports = []
        for markdown_path in self.evidence_dir.glob("*.md"):
            run_id = markdown_path.stem
            json_path = self.evidence_dir / f"{run_id}.json"
            markdown_stat = markdown_path.stat()
            json_stat = json_path.stat() if json_path.exists() else None
            reports.append(
                {
                    "run_id": run_id,
                    "markdown_filename": markdown_path.name,
                    "json_filename": json_path.name if json_path.exists() else "",
                    "markdown_path": str(Path(".autocore") / "evidence" / markdown_path.name),
                    "json_path": str(Path(".autocore") / "evidence" / json_path.name) if json_path.exists() else "",
                    "markdown_bytes": markdown_stat.st_size,
                    "json_bytes": json_stat.st_size if json_stat else 0,
                    "updated_at": datetime.fromtimestamp(markdown_stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                }
            )
        reports.sort(key=lambda report: report["updated_at"], reverse=True)
        return {"reports": reports}

    def _score(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        task = get_task(run["task_pack_id"], run["task_id"])
        scorecard = compute_scorecard(run, task)
        self.store.update_scorecard(run_id, scorecard)
        return scorecard
