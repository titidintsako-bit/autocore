from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autocore.build_auditor import audit_project
from autocore.server import create_server


def _request_json(url: str, method: str = "GET", body: dict[str, object] | None = None) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _start_server(*, state_dir: Path, mode: str, static_dir: Path | None = None):
    server = create_server(port=0, state_dir=state_dir, mode=mode, static_dir=static_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _live_guided_audit_smoke(root: Path, temp_dir: Path) -> dict[str, object]:
    server, thread, base_url = _start_server(state_dir=temp_dir / "live-state", mode="live")
    server.RequestHandlerClass.project_root = root
    try:
        health = _request_json(f"{base_url}/api/health")
        if not health.get("capabilities", {}).get("guided_audit"):
            raise RuntimeError("guided_audit capability is missing")

        guided_payload = _request_json(f"{base_url}/api/guided-audit", method="POST", body={})
        guided = guided_payload["guided_audit"]
        if guided["run"]["status"] != "approval_required":
            raise RuntimeError(f"guided audit did not create an approval run: {guided['run']['status']}")

        command = guided["run"]["commands"][0]
        approved = _request_json(
            f"{base_url}/api/runs/{guided['run']['id']}/commands/approve",
            method="POST",
            body={"command_id": command["id"]},
        )
        if approved["run"]["status"] != "evidence_ready":
            raise RuntimeError(f"approved run did not produce evidence: {approved['run']['status']}")

        evidence = _request_json(f"{base_url}/api/runs/{guided['run']['id']}/evidence")
        markdown = evidence["evidence"]["markdown"]
        if "# AutoCore Evidence Report" not in markdown:
            raise RuntimeError("evidence report markdown was not generated")
        return {"run_id": guided["run"]["id"], "status": approved["run"]["status"]}
    finally:
        _stop_server(server, thread)


def _public_read_only_smoke(root: Path, temp_dir: Path) -> dict[str, object]:
    static_dir = root / "dist"
    server, thread, base_url = _start_server(state_dir=temp_dir / "public-state", mode="public", static_dir=static_dir)
    try:
        project = _request_json(f"{base_url}/api/project")
        payload = json.dumps(project, sort_keys=True)
        if project["project"]["path"] != "public-demo-workspace":
            raise RuntimeError("public project path is not sanitized")
        if str(root) in payload or "OneDrive" in payload:
            raise RuntimeError("public project payload leaked a local path")

        request = urllib.request.Request(
            f"{base_url}/api/guided-audit",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise RuntimeError(f"public mutation returned {error.code}, expected 403") from error
        else:
            raise RuntimeError("public mutation was allowed")
        return {"project_path": project["project"]["path"], "mutations": "blocked"}
    finally:
        _stop_server(server, thread)


def run_release_smoke(root: Path) -> dict[str, object]:
    audit = audit_project(root)
    if audit["verdict"] != "ready" or not audit["no_mocked_data"]:
        raise RuntimeError(f"build auditor is not release-ready: {audit['verdict']}, no_mocked_data={audit['no_mocked_data']}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        live = _live_guided_audit_smoke(root, base)
        time.sleep(0.1)
        public = _public_read_only_smoke(root, base)

    return {
        "ok": True,
        "build_audit": {
            "verdict": audit["verdict"],
            "score": audit["overall"],
            "no_mocked_data": audit["no_mocked_data"],
            "quality_claim": audit["claims"]["quality"]["status"],
            "security_claim": audit["claims"]["security"]["status"],
        },
        "live_guided_audit": live,
        "public_read_only": public,
    }


def main() -> int:
    if "--check" in sys.argv:
        print(json.dumps({"ok": True, "script": "release-smoke", "checks": ["build_audit", "guided_audit", "public_read_only"]}, indent=2))
        return 0
    root_arg = next((item for item in sys.argv[1:] if item != "--check"), None)
    root = Path(root_arg) if root_arg else ROOT
    try:
        result = run_release_smoke(root.resolve())
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
