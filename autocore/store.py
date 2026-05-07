from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .safety import command_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AutoCoreStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    task_pack_id TEXT NOT NULL DEFAULT 'repo-readiness',
                    task_id TEXT NOT NULL DEFAULT 'build-health',
                    status TEXT NOT NULL,
                    autonomy_score INTEGER NOT NULL,
                    safety_score INTEGER NOT NULL,
                    score_json TEXT NOT NULL DEFAULT '{}',
                    planner_json TEXT NOT NULL DEFAULT '{}',
                    inspection_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    command_text TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    state TEXT NOT NULL,
                    policy_allowed INTEGER NOT NULL,
                    policy_reason TEXT NOT NULL,
                    sandbox_json TEXT NOT NULL DEFAULT '{}',
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );

                CREATE TABLE IF NOT EXISTS prompt_evaluations (
                    id TEXT PRIMARY KEY,
                    prompt_preview TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS build_audits (
                    id TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    audit_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "runs", "task_pack_id", "TEXT NOT NULL DEFAULT 'repo-readiness'")
            self._ensure_column(conn, "runs", "task_id", "TEXT NOT NULL DEFAULT 'build-health'")
            self._ensure_column(conn, "runs", "score_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "runs", "planner_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "commands", "sandbox_json", "TEXT NOT NULL DEFAULT '{}'")
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_run(
        self,
        path: str | Path,
        goal: str,
        inspection: dict[str, Any],
        task_pack_id: str = "repo-readiness",
        task_id: str = "build-health",
        planner: dict[str, Any] | None = None,
    ) -> str:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, path, goal, task_pack_id, task_id, status, autonomy_score, safety_score,
                    score_json, planner_json, inspection_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(Path(path).resolve()),
                    goal,
                    task_pack_id,
                    task_id,
                    "approval_required",
                    74,
                    93,
                    "{}",
                    json.dumps(planner or {"provider": {"name": "offline", "model": "heuristic", "mode": "local"}}),
                    json.dumps(inspection),
                    now,
                    now,
                ),
            )
            conn.commit()
        return run_id

    def add_event(
        self,
        run_id: str,
        kind: str,
        title: str,
        detail: str,
        status: str = "ok",
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:10]}"
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO events (id, run_id, kind, title, detail, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, run_id, kind, title, detail, status, now),
            )
            conn.commit()
        return event_id

    def add_pending_command(
        self,
        run_id: str,
        command: Sequence[str],
        purpose: str,
        policy_allowed: bool = True,
        policy_reason: str = "Command matches safe check allowlist.",
        sandbox: dict[str, Any] | None = None,
    ) -> str:
        command_id = f"cmd_{uuid.uuid4().hex[:10]}"
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO commands (
                    id, run_id, command_json, command_text, purpose, state, policy_allowed,
                    policy_reason, sandbox_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    run_id,
                    json.dumps(list(command)),
                    command_text(command),
                    purpose,
                    "pending" if policy_allowed else "blocked",
                    1 if policy_allowed else 0,
                    policy_reason,
                    json.dumps(sandbox or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        return command_id

    def update_run(self, run_id: str, status: str, autonomy_score: int | None = None) -> None:
        now = utc_now()
        with closing(self.connect()) as conn:
            if autonomy_score is None:
                conn.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", (status, now, run_id))
            else:
                conn.execute(
                    "UPDATE runs SET status = ?, autonomy_score = ?, updated_at = ? WHERE id = ?",
                    (status, autonomy_score, now, run_id),
                )
            conn.commit()

    def update_scorecard(self, run_id: str, scorecard: dict[str, Any]) -> None:
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE runs SET autonomy_score = ?, score_json = ?, updated_at = ? WHERE id = ?",
                (scorecard["overall"], json.dumps(scorecard), now, run_id),
            )
            conn.commit()

    def save_prompt_evaluation(self, evaluation: dict[str, Any]) -> str:
        now = evaluation.get("created_at") or utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO prompt_evaluations (id, prompt_preview, prompt_hash, evaluation_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evaluation["id"],
                    evaluation["prompt_preview"],
                    evaluation.get("prompt_hash", ""),
                    json.dumps(evaluation),
                    now,
                ),
            )
            conn.commit()
        return evaluation["id"]

    def get_prompt_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT evaluation_json FROM prompt_evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        if row is None:
            raise KeyError(evaluation_id)
        return json.loads(row["evaluation_json"])

    def list_prompt_evaluations(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT evaluation_json FROM prompt_evaluations ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [json.loads(row["evaluation_json"]) for row in rows]

    def save_build_audit(self, audit: dict[str, Any]) -> str:
        now = audit.get("created_at") or utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO build_audits (id, project_name, verdict, audit_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    audit["id"],
                    audit.get("project", {}).get("name", "unknown"),
                    audit.get("verdict", "unknown"),
                    json.dumps(audit),
                    now,
                ),
            )
            conn.commit()
        return audit["id"]

    def get_build_audit(self, audit_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT audit_json FROM build_audits WHERE id = ?", (audit_id,)).fetchone()
        if row is None:
            raise KeyError(audit_id)
        return json.loads(row["audit_json"])

    def list_build_audits(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT audit_json FROM build_audits ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [json.loads(row["audit_json"]) for row in rows]

    def update_command_result(
        self,
        command_id: str,
        state: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> None:
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE commands
                SET state = ?, exit_code = ?, stdout = ?, stderr = ?, duration_ms = ?, updated_at = ?
                WHERE id = ?
                """,
                (state, exit_code, stdout, stderr, duration_ms, now, command_id),
            )
            conn.commit()

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        return self._command_row(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            events = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
            commands = conn.execute(
                "SELECT * FROM commands WHERE run_id = ? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
        return self._run_row(run, events, commands)

    def latest_run(self) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        return self.get_run(row["id"]) if row else None

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self.get_run(row["id"]) for row in rows]

    def _run_row(
        self,
        row: sqlite3.Row,
        events: Sequence[sqlite3.Row],
        commands: Sequence[sqlite3.Row],
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "path": row["path"],
            "goal": row["goal"],
            "task_pack_id": row["task_pack_id"],
            "task_id": row["task_id"],
            "status": row["status"],
            "autonomy_score": row["autonomy_score"],
            "safety_score": row["safety_score"],
            "scorecard": json.loads(row["score_json"] or "{}"),
            "planner": json.loads(row["planner_json"] or "{}"),
            "inspection": json.loads(row["inspection_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "events": [dict(event) for event in events],
            "commands": [self._command_row(command) for command in commands],
        }

    def _command_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "command": json.loads(row["command_json"]),
            "command_text": row["command_text"],
            "purpose": row["purpose"],
            "state": row["state"],
            "policy_allowed": bool(row["policy_allowed"]),
            "policy_reason": row["policy_reason"],
            "sandbox": json.loads(row["sandbox_json"] or "{}"),
            "exit_code": row["exit_code"],
            "stdout": row["stdout"],
            "stderr": row["stderr"],
            "duration_ms": row["duration_ms"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
