from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .build_auditor import audit_project
from .companion import companion_status, public_companion_status
from .containment import DockerContainmentRunner
from .connectors import build_connector_inventory
from .demo import demo_snapshot
from .guided_audit import run_guided_audit
from .inspector import inspect_project
from .prompt_lab import evaluate_prompt
from .project_picker import ProjectPickCancelled, ProjectPickerUnavailable, pick_project_folder
from .executor import CommandExecutor
from .runner import AutoCoreRuntime
from .safety import CommandPolicy, sandbox_profile
from .setup import live_setup_status, public_setup_status
from .taskpacks import get_task, get_task_pack, list_task_packs
from .version import AUTOCORE_CAPABILITIES, AUTOCORE_UI_MIN_VERSION, AUTOCORE_VERSION


class AutoCoreHandler(BaseHTTPRequestHandler):
    runtime: AutoCoreRuntime
    project_root: Path
    mode: str = "live"
    api_token: str | None = None
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    static_dir: Path | None = None

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allowed = self.allowed_origins or ("http://127.0.0.1:5173",)
        if "*" in allowed:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin and origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", allowed[0])
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-AutoCore-Token")

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message, "mode": self.mode}, status)

    def _send_bad_request(self) -> None:
        self._send_error_json("Bad request", HTTPStatus.BAD_REQUEST)

    def _authorized(self) -> bool:
        if not self.api_token:
            return True
        bearer = self.headers.get("Authorization", "")
        if bearer == f"Bearer {self.api_token}":
            return True
        return self.headers.get("X-AutoCore-Token") == self.api_token

    def _requires_auth(self, path: str) -> bool:
        if self.mode == "public" or not self.api_token:
            return False
        if path in {"/api/health", "/api/demo", "/api/task-packs"} or path.startswith("/api/task-packs/"):
            return False
        return path.startswith("/api/")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _project_payload(self) -> dict[str, Any]:
        root = Path(self.project_root).resolve()
        inspection = inspect_project(root) if root.exists() else {
            "stack": "Missing",
            "manifests": [],
            "scripts": {},
            "recommended_commands": [],
            "risk_surfaces": {},
        }
        return {
            "project": {
                "name": root.name,
                "path": str(root),
                "exists": root.exists(),
                "stack": inspection["stack"],
                "manifests": inspection["manifests"],
                "scripts": sorted(inspection["scripts"].keys()),
                "recommended_commands": [" ".join(command) for command in inspection["recommended_commands"]],
                "risk_surfaces": inspection["risk_surfaces"],
                "control": "AUTOCORE_PROJECT_ROOT",
            }
        }

    def _public_project_payload(self) -> dict[str, Any]:
        return {
            "project": {
                "name": "public-demo-workspace",
                "path": "public-demo-workspace",
                "exists": True,
                "stack": "React/Vite + Python runtime",
                "manifests": ["package.json", "vite.config.ts", "autocore/server.py"],
                "scripts": ["build", "backend", "dev", "test:backend"],
                "recommended_commands": ["npm run build"],
                "risk_surfaces": {
                    "public_demo_read_only": True,
                    "has_env": False,
                    "has_networked_provider": False,
                },
                "control": "AUTOCORE_MODE=public",
            }
        }

    def _public_connector_inventory(self) -> dict[str, Any]:
        inventory = build_connector_inventory(self.project_root, env={})
        for connector in inventory["connectors"]:
            connector["state"] = "not_connected"
            connector["source"] = "public_demo"
            connector["configured_env"] = []
            if connector["id"] == "local-repo":
                connector["state"] = "demo_connected"
                connector["evidence"] = {
                    "detail": "Public demo source is sanitized and read-only.",
                    "stack": "React/Vite + Python runtime",
                    "manifests": ["package.json", "vite.config.ts", "autocore/server.py"],
                    "workspace_name": "public-demo-workspace",
                }
        inventory["mode"] = "public"
        inventory["mocked"] = False
        inventory["project"] = {"name": "public-demo-workspace", "stack": "React/Vite + Python runtime"}
        inventory["summary"] = {
            "total": len(inventory["connectors"]),
            "active": 1,
            "guarded": 0,
            "attention": 0,
            "not_connected": len(inventory["connectors"]) - 1,
        }
        inventory["boundary"] = {
            "label": "Public read-only demo",
            "detail": "Public deployment serves sanitized demo evidence. Live local paths, env presence, approvals, and command execution are disabled.",
        }
        return inventory

    def _public_evidence_library(self) -> dict[str, Any]:
        snapshot = demo_snapshot(self.project_root)
        return {
            "reports": [
                {
                    "run_id": snapshot["run"]["id"],
                    "markdown_filename": snapshot["evidence"]["summary"]["markdown_filename"],
                    "json_filename": snapshot["evidence"]["summary"]["json_filename"],
                    "markdown_path": snapshot["evidence"]["markdown_path"],
                    "json_path": snapshot["evidence"]["json_path"],
                    "markdown_bytes": len(snapshot["evidence"]["markdown"].encode("utf-8")),
                    "json_bytes": len(json.dumps(snapshot["evidence"]["json"]).encode("utf-8")),
                    "updated_at": snapshot["run"]["updated_at"],
                }
            ]
        }

    def _send_static(self, path: str) -> bool:
        if not self.static_dir:
            return False
        root = self.static_dir.resolve()
        requested = path.lstrip("/") or "index.html"
        candidate = (root / requested).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send_error_json("Not found", HTTPStatus.NOT_FOUND)
            return True
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            return False
        data = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        try:
            if not path.startswith("/api/"):
                if self._send_static(path):
                    return
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            if self._requires_auth(path) and not self._authorized():
                self._send_error_json("Unauthorized", HTTPStatus.UNAUTHORIZED)
                return
            if path == "/api/health":
                self._send_json(
                    {
                        "ok": True,
                        "service": "autocore-runtime",
                        "version": AUTOCORE_VERSION,
                        "ui_min_version": AUTOCORE_UI_MIN_VERSION,
                        "capabilities": AUTOCORE_CAPABILITIES,
                        "mode": self.mode,
                        "live_enabled": self.mode == "live",
                    }
                )
            elif path == "/api/demo":
                self._send_json({"demo": demo_snapshot(self.project_root)})
            elif path == "/api/project":
                self._send_json(self._public_project_payload() if self.mode == "public" else self._project_payload())
            elif path == "/api/setup":
                self._send_json({"setup": public_setup_status() if self.mode == "public" else live_setup_status(self.project_root)})
            elif path == "/api/companion":
                if self.mode == "public":
                    self._send_json({"companion": public_companion_status()})
                else:
                    latest_audits = self.runtime.store.list_build_audits(limit=1)
                    self._send_json({"companion": companion_status(self.project_root, latest_audits[0] if latest_audits else None)})
            elif path == "/api/connectors":
                self._send_json(self._public_connector_inventory() if self.mode == "public" else build_connector_inventory(self.project_root))
            elif path == "/api/evidence":
                self._send_json(self._public_evidence_library() if self.mode == "public" else self.runtime.evidence_library())
            elif path == "/api/policy":
                self._send_json({"policy": sandbox_profile(self.runtime.policy)})
            elif path == "/api/task-packs":
                self._send_json({"task_packs": list_task_packs()})
            elif path.startswith("/api/task-packs/"):
                pack_id = path.strip("/").split("/")[2]
                self._send_json({"task_pack": get_task_pack(pack_id)})
            elif path == "/api/prompt-lab":
                if self.mode == "public":
                    self._send_json({"evaluations": []})
                else:
                    self._send_json({"evaluations": self.runtime.store.list_prompt_evaluations()})
            elif path == "/api/build-audits":
                if self.mode == "public":
                    self._send_json({"audits": []})
                else:
                    self._send_json({"audits": self.runtime.store.list_build_audits()})
            elif path == "/api/runs":
                if self.mode == "public":
                    self._send_json({"history": demo_snapshot(self.project_root)["history"]})
                    return
                query = parse_qs(parsed_url.query)
                limit = int(query.get("limit", ["25"])[0])
                self._send_json({"history": self.runtime.run_history(limit=limit)})
            elif path == "/api/runs/latest":
                if self.mode == "public":
                    self._send_json({"run": demo_snapshot(self.project_root)["run"]})
                    return
                run = self.runtime.latest_or_seed(self.project_root, "Repo hardening audit")
                self._send_json({"run": run})
            elif path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                run_id = parts[2]
                if self.mode == "public":
                    snapshot = demo_snapshot(self.project_root)
                    if len(parts) == 4 and parts[3] == "evidence":
                        self._send_json({"evidence": snapshot["evidence"]})
                    else:
                        self._send_json({"run": snapshot["run"]})
                    return
                if len(parts) == 4 and parts[3] == "evidence":
                    self._send_json({"evidence": self.runtime.evidence_bundle(run_id)})
                else:
                    self._send_json({"run": self.runtime.store.get_run(run_id)})
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception:
            self._send_bad_request()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if self.mode == "public":
                self._send_error_json("Public deployment is read-only.", HTTPStatus.FORBIDDEN)
                return
            if self._requires_auth(path) and not self._authorized():
                self._send_error_json("Unauthorized", HTTPStatus.UNAUTHORIZED)
                return
            body = self._read_json()
            if path == "/api/runs":
                run = self.runtime.create_run(
                    body.get("path") or self.project_root,
                    body.get("goal") or "",
                    task_pack_id=body.get("task_pack_id"),
                    task_id=body.get("task_id"),
                    prompt_evaluation_id=body.get("prompt_evaluation_id"),
                )
                self._send_json({"run": run}, HTTPStatus.CREATED)
            elif path == "/api/prompt-lab/evaluate":
                task_pack_id = body.get("task_pack_id") or "repo-readiness"
                task_id = body.get("task_id") or get_task_pack(task_pack_id)["default_task_id"]
                task = get_task(task_pack_id, task_id)
                provider = body.get("provider") or os.environ.get("AUTOCORE_PROVIDER", "offline")
                model = body.get("model") or {
                    "groq": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "openai": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    "ollama": os.environ.get("OLLAMA_MODEL", "llama3.1"),
                }.get(str(provider).lower(), "heuristic")
                evaluation = evaluate_prompt(
                    str(body.get("prompt") or ""),
                    task,
                    provider=str(provider),
                    model=str(model),
                    critique_enabled=bool(body.get("critique_enabled")),
                )
                self.runtime.store.save_prompt_evaluation(evaluation)
                self._send_json({"evaluation": evaluation}, HTTPStatus.CREATED)
            elif path == "/api/guided-audit":
                guided = run_guided_audit(self.runtime, self.project_root, body)
                self._send_json({"guided_audit": guided}, HTTPStatus.CREATED)
            elif path == "/api/build-audits":
                requested = Path(body.get("path") or self.project_root).expanduser().resolve()
                if not requested.exists() or not requested.is_dir():
                    self._send_json({"error": "Project path must be an existing directory."}, HTTPStatus.BAD_REQUEST)
                    return
                audit = audit_project(requested)
                self.runtime.store.save_build_audit(audit)
                self._send_json({"audit": audit}, HTTPStatus.CREATED)
            elif path == "/api/companion/audit":
                audit = audit_project(self.project_root)
                self.runtime.store.save_build_audit(audit)
                self._send_json({"audit": audit, "companion": companion_status(self.project_root, audit)}, HTTPStatus.CREATED)
            elif path == "/api/project/pick":
                try:
                    picked = pick_project_folder(self.project_root)
                except ProjectPickCancelled:
                    self._send_json({"picked": False, "project": self._project_payload()["project"]})
                    return
                except ProjectPickerUnavailable:
                    self._send_error_json("Native folder picker is unavailable. Paste the folder path instead.", HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                if not picked.exists() or not picked.is_dir():
                    self._send_json({"error": "Project path must be an existing directory."}, HTTPStatus.BAD_REQUEST)
                    return
                type(self).project_root = picked
                payload = self._project_payload()
                payload["picked"] = True
                self._send_json(payload)
            elif path == "/api/project":
                requested_path = Path(body.get("path") or "").expanduser().resolve()
                if not requested_path.exists() or not requested_path.is_dir():
                    self._send_json({"error": "Project path must be an existing directory."}, HTTPStatus.BAD_REQUEST)
                    return
                type(self).project_root = requested_path
                self._send_json(self._project_payload())
            elif path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                run_id = parts[2]
                if len(parts) == 5 and parts[3] == "commands" and parts[4] in {"approve", "hold"}:
                    command_id = body["command_id"]
                    if parts[4] == "approve":
                        run = self.runtime.approve_command(run_id, command_id)
                    else:
                        run = self.runtime.hold_command(run_id, command_id)
                    self._send_json({"run": run})
                else:
                    self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception:
            self._send_bad_request()


def _env_list(name: str, default: str) -> tuple[str, ...]:
    value = os.environ.get(name, default)
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def create_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    state_dir: str | Path = ".autocore",
    mode: str | None = None,
    api_token: str | None = None,
    allowed_origins: list[str] | tuple[str, ...] | None = None,
    static_dir: str | Path | None = None,
) -> ThreadingHTTPServer:
    project_root = Path(os.environ.get("AUTOCORE_PROJECT_ROOT", Path.cwd())).resolve()
    resolved_mode = (mode or os.environ.get("AUTOCORE_MODE", "live")).lower()
    if resolved_mode not in {"live", "public"}:
        raise ValueError("AUTOCORE_MODE must be 'live' or 'public'.")
    resolved_token = api_token if api_token is not None else os.environ.get("AUTOCORE_API_TOKEN")
    if resolved_mode == "live" and not _is_loopback_host(host) and not resolved_token and os.environ.get("AUTOCORE_ALLOW_UNAUTHENTICATED_LIVE") != "1":
        raise RuntimeError("Live mode bound to a network host requires AUTOCORE_API_TOKEN.")
    resolved_origins = tuple(allowed_origins) if allowed_origins is not None else _env_list(
        "AUTOCORE_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    resolved_static_dir = Path(static_dir or os.environ.get("AUTOCORE_STATIC_DIR", "dist")).resolve()
    policy = CommandPolicy(trust_project_scripts=_env_flag("AUTOCORE_TRUST_PROJECT_SCRIPTS"))
    containment_runner = DockerContainmentRunner() if _env_flag("AUTOCORE_ENABLE_DOCKER_CONTAINMENT") else None
    executor = CommandExecutor(policy=policy, containment_runner=containment_runner)
    handler = type(
        "BoundAutoCoreHandler",
        (AutoCoreHandler,),
        {
            "runtime": AutoCoreRuntime(state_dir=state_dir, policy=policy, executor=executor),
            "project_root": project_root,
            "mode": resolved_mode,
            "api_token": resolved_token,
            "allowed_origins": resolved_origins,
            "static_dir": resolved_static_dir if resolved_static_dir.exists() else None,
        },
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    port = int(os.environ.get("AUTOCORE_PORT", "8787"))
    host = os.environ.get("AUTOCORE_HOST", "127.0.0.1")
    server = create_server(host=host, port=port, state_dir=os.environ.get("AUTOCORE_STATE_DIR", ".autocore"))
    print(f"AutoCore runtime listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
