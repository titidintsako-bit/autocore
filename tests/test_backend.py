import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autocore.executor import CommandExecutor, CommandResult, resolve_executable, strip_ansi
from autocore.containment import DockerContainmentRunner, docker_containment_status
from autocore.connectors import build_connector_inventory
from autocore.build_auditor import audit_project
from autocore.companion import companion_status
from autocore.inspector import inspect_project
from autocore.planner import AgentPlanner
from autocore.prompt_lab import evaluate_prompt, parse_groq_rate_limit_headers, parse_openai_usage_cost_payload
from autocore.providers import OfflineProvider, ProviderResponse, select_provider
from autocore.runner import AutoCoreRuntime
from autocore.safety import CommandPolicy
from autocore.scoring import compute_scorecard
from autocore.server import create_server
from autocore.store import AutoCoreStore
from autocore.taskpacks import default_task, get_task, get_task_pack, list_task_packs

try:
    from autocore.demo import demo_snapshot
except ImportError:
    demo_snapshot = None


class InspectorTests(unittest.TestCase):
    def test_inspects_vite_project_and_recommends_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "tsc -b && vite build", "dev": "vite"},
                        "dependencies": {"react": "^19.0.0"},
                        "devDependencies": {"vite": "^7.0.0", "typescript": "^5.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "vite.config.ts").write_text("export default {}", encoding="utf-8")

            result = inspect_project(root)

        self.assertEqual(result["stack"], "React/Vite")
        self.assertIn("package.json", result["manifests"])
        self.assertIn(["npm", "run", "build"], result["recommended_commands"])
        self.assertTrue(result["risk_surfaces"]["has_package_lock"] is False)

    def test_python_project_recommends_safe_static_check_before_pytest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.1'\n", encoding="utf-8")
            (root / "module.py").write_text("print('ok')\n", encoding="utf-8")

            result = inspect_project(root)

        self.assertEqual(result["stack"], "Python")
        self.assertEqual(result["recommended_commands"][0], ["python", "-m", "compileall", "."])
        self.assertIn(["python", "-m", "pytest"], result["recommended_commands"])


class RuntimeCapabilityTests(unittest.TestCase):
    def test_health_endpoint_exposes_version_and_capabilities_for_ui_handshake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(payload["service"], "autocore-runtime")
        self.assertRegex(payload["version"], r"^0\.\d+\.\d+")
        self.assertTrue(payload["capabilities"]["guided_audit"])
        self.assertTrue(payload["capabilities"]["prompt_lab"])
        self.assertTrue(payload["capabilities"]["build_auditor"])
        self.assertIn("ui_min_version", payload)


class LauncherTests(unittest.TestCase):
    def test_start_local_check_resolves_busy_ports_before_printing_plan(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as backend_socket, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as frontend_socket:
            backend_socket.bind(("127.0.0.1", 0))
            frontend_socket.bind(("127.0.0.1", 0))
            backend_socket.listen(1)
            frontend_socket.listen(1)
            backend_port = backend_socket.getsockname()[1]
            frontend_port = frontend_socket.getsockname()[1]

            result = subprocess.run(
                [
                    "node",
                    "scripts/start-local.mjs",
                    "--check",
                    "--backend-port",
                    str(backend_port),
                    "--frontend-port",
                    str(frontend_port),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["backend"]["requested_port"], backend_port)
        self.assertEqual(plan["frontend"]["requested_port"], frontend_port)
        self.assertNotEqual(plan["backend"]["port"], backend_port)
        self.assertNotEqual(plan["frontend"]["port"], frontend_port)
        self.assertEqual(plan["backend"]["port_status"], "busy")
        self.assertEqual(plan["frontend"]["port_status"], "busy")
        self.assertTrue(any("busy" in warning.lower() for warning in plan["warnings"]))
        self.assertIn(f":{plan['frontend']['port']}/?section=setup", plan["frontend"]["url"])


class SetupGuideTests(unittest.TestCase):
    def test_setup_status_translates_runtime_state_into_plain_next_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "vite build"},
                        "dependencies": {"react": "^19.0.0"},
                        "devDependencies": {"vite": "^7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            state = Path(temp_dir) / "state"
            server = create_server(port=0, state_dir=state, mode="live")
            server.RequestHandlerClass.project_root = project
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/setup", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        setup = payload["setup"]
        self.assertEqual(setup["mode"], "live")
        self.assertEqual(setup["project"]["name"], "project")
        self.assertTrue(setup["project"]["exists"])
        self.assertEqual(setup["project"]["stack"], "React/Vite")
        self.assertGreaterEqual(setup["readiness"]["score"], 50)
        self.assertTrue(any(check["id"] == "project" and check["status"] == "ready" for check in setup["checks"]))
        self.assertTrue(any(step["id"] == "run_audit" for step in setup["next_steps"]))
        self.assertTrue(any(option["id"] == "personal_live" and option["available"] for option in setup["modes"]))

    def test_public_setup_status_is_read_only_and_has_no_local_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="public")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/setup", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        setup_text = json.dumps(payload)
        setup = payload["setup"]
        self.assertEqual(setup["mode"], "public")
        self.assertTrue(setup["read_only"])
        self.assertEqual(setup["project"]["path"], "public-demo-workspace")
        self.assertFalse("C:\\Users\\user" in setup_text)
        self.assertTrue(any(step["id"] == "switch_live" for step in setup["next_steps"]))


class ProjectPickerTests(unittest.TestCase):
    def test_local_project_picker_updates_project_without_typing_a_path(self):
        previous = os.environ.get("AUTOCORE_PROJECT_PICKER_RESULT")
        with tempfile.TemporaryDirectory() as temp_dir:
            initial = Path(temp_dir) / "initial"
            picked = Path(temp_dir) / "picked"
            initial.mkdir()
            picked.mkdir()
            (picked / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "vite build"},
                        "dependencies": {"react": "^19.0.0"},
                        "devDependencies": {"vite": "^7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            os.environ["AUTOCORE_PROJECT_PICKER_RESULT"] = str(picked)
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live")
            server.RequestHandlerClass.project_root = initial
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/project/pick",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    picked_payload = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/setup", timeout=5) as response:
                    setup_payload = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/companion", timeout=5) as response:
                    companion_payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                if previous is None:
                    os.environ.pop("AUTOCORE_PROJECT_PICKER_RESULT", None)
                else:
                    os.environ["AUTOCORE_PROJECT_PICKER_RESULT"] = previous

        self.assertEqual(picked_payload["project"]["name"], "picked")
        self.assertEqual(picked_payload["project"]["stack"], "React/Vite")
        self.assertEqual(setup_payload["setup"]["project"]["name"], "picked")
        self.assertEqual(companion_payload["companion"]["project"]["name"], "picked")

    def test_public_project_picker_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="public")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/project/pick",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(raised.exception.code, 403)


class CompanionModeTests(unittest.TestCase):
    def test_companion_status_flags_changed_files_for_codex_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^19.0.0"}}),
                encoding="utf-8",
            )
            src = project / "src"
            src.mkdir()
            (src / "App.tsx").write_text("const fakeUsers = [{ id: 1, name: 'Placeholder' }];\nexport default function App() { return null }\n", encoding="utf-8")
            (project / "README.md").write_text("# Demo\nNo tests described yet.\n", encoding="utf-8")

            payload = companion_status(project)

        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["project"]["name"], "project")
        self.assertEqual(payload["verdict"], "needs_audit")
        self.assertGreaterEqual(payload["summary"]["changed_files"], 2)
        self.assertGreaterEqual(payload["summary"]["high_risk_files"], 1)
        self.assertTrue(any(file["path"] == "src/App.tsx" and file["risk"] == "high" for file in payload["changed_files"]))
        self.assertTrue(any("mocked" in signal for file in payload["changed_files"] for signal in file["signals"]))
        self.assertTrue(any(step["id"] == "audit_latest_codex_changes" for step in payload["next_steps"]))
        self.assertIn("changed files", payload["suggested_prompt"].lower())

    def test_companion_api_runs_audit_for_latest_codex_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^19.0.0"}}),
                encoding="utf-8",
            )
            (project / "App.tsx").write_text("const fakeRecords = [];\nexport default function App() { return null }\n", encoding="utf-8")
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live")
            server.RequestHandlerClass.project_root = project
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/companion", timeout=5) as response:
                    companion = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/companion/audit",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    audited = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(companion["companion"]["verdict"], "needs_audit")
        self.assertIn("audit", audited)
        self.assertIn("companion", audited)
        self.assertFalse(audited["audit"]["no_mocked_data"])
        self.assertEqual(audited["companion"]["latest_audit"]["id"], audited["audit"]["id"])

    def test_public_companion_is_read_only_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="public")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/companion", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/companion/audit",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        companion = payload["companion"]
        self.assertEqual(companion["mode"], "public")
        self.assertTrue(companion["read_only"])
        self.assertEqual(companion["changed_files"], [])
        self.assertFalse("C:\\Users\\user" in json.dumps(payload))
        self.assertEqual(raised.exception.code, 403)


class GuidedAuditTests(unittest.TestCase):
    def test_guided_audit_creates_prompt_eval_build_audit_and_approval_gated_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "vite build"},
                        "dependencies": {"react": "^19.0.0"},
                        "devDependencies": {"vite": "^7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            src = project / "src"
            src.mkdir()
            (src / "App.tsx").write_text(
                "const fakeAccounts = [];\nexport default function App() { return null }\n",
                encoding="utf-8",
            )
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live")
            server.RequestHandlerClass.project_root = project
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/guided-audit",
                    data=json.dumps({"task_pack_id": "repo-readiness", "task_id": "build-health"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/prompt-lab", timeout=5) as response:
                    evaluations_payload = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build-audits", timeout=5) as response:
                    audits_payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        guided = payload["guided_audit"]
        self.assertEqual(guided["project"]["name"], "project")
        self.assertEqual(guided["status"], "approval_required")
        self.assertEqual(guided["prompt_evaluation"]["verdict"], "ready")
        self.assertFalse(guided["build_audit"]["no_mocked_data"])
        self.assertEqual(guided["build_audit"]["source"], "local_static_scan")
        self.assertEqual(guided["run"]["status"], "approval_required")
        self.assertEqual(guided["run"]["planner"]["prompt_evaluation"]["id"], guided["prompt_evaluation"]["id"])
        self.assertEqual(guided["next_action"]["id"], "approve_safe_check")
        self.assertEqual(evaluations_payload["evaluations"][0]["id"], guided["prompt_evaluation"]["id"])
        self.assertEqual(audits_payload["audits"][0]["id"], guided["build_audit"]["id"])
        payload_text = json.dumps(payload, sort_keys=True)
        self.assertNotIn("const fakeAccounts", payload_text)


class PolicyTests(unittest.TestCase):
    def test_policy_allows_known_safe_checks_and_blocks_shell_forms(self):
        policy = CommandPolicy()

        self.assertTrue(policy.evaluate(["python", "-m", "compileall", "."]).allowed)
        self.assertTrue(policy.evaluate(["python", "-m", "py_compile", "autocore/server.py"]).allowed)
        self.assertFalse(policy.evaluate(["npm", "run", "build"]).allowed)
        self.assertFalse(policy.evaluate(["python", "-m", "pytest"]).allowed)
        self.assertFalse(policy.evaluate(["npm", "install"]).allowed)
        self.assertFalse(policy.evaluate(["powershell", "-Command", "Remove-Item", "-Recurse", "."]).allowed)
        self.assertFalse(policy.evaluate(["npm", "run", "build;rm", "-rf", "."]).allowed)

    def test_policy_allows_project_scripts_only_when_operator_trusts_repo(self):
        default_policy = CommandPolicy()
        trusted_policy = CommandPolicy(trust_project_scripts=True)

        blocked = default_policy.evaluate(["npm", "run", "build"])
        allowed = trusted_policy.evaluate(["npm", "run", "build"])

        self.assertFalse(blocked.allowed)
        self.assertIn("trusted local mode", blocked.reason)
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.sandbox["profile_id"], "trusted.project")
        self.assertEqual(allowed.sandbox["network"], "host-inherited")
        self.assertTrue(any(check["id"] == "project_trust" and check["status"] == "pass" for check in allowed.sandbox["checks"]))
        self.assertEqual(blocked.sandbox["control_type"], "guarded_policy")
        self.assertEqual(blocked.sandbox["containment"], "none")
        self.assertEqual(allowed.sandbox["control_type"], "trusted_project_execution")
        self.assertEqual(allowed.sandbox["containment"], "none")
        self.assertIn("not OS-contained", allowed.sandbox["execution_warning"])

    def test_policy_attaches_sandbox_profile_and_denies_network_or_secret_access(self):
        policy = CommandPolicy(workspace_root=ROOT)

        allowed = policy.evaluate(["python", "-m", "compileall", "."])
        network = policy.evaluate(["curl", "https://example.com"])
        secret = policy.evaluate(["python", "-m", "py_compile", ".env"])

        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.sandbox["profile_id"], "guarded.local")
        self.assertEqual(allowed.sandbox["network"], "deny")
        self.assertEqual(allowed.sandbox["secrets"], "deny")
        self.assertEqual(allowed.sandbox["capability"], "static-analysis")
        self.assertTrue(any(check["id"] == "allowlist" and check["status"] == "pass" for check in allowed.sandbox["checks"]))
        self.assertFalse(network.allowed)
        self.assertEqual(network.sandbox["capability"], "network")
        self.assertTrue(any(check["id"] == "network" and check["status"] == "fail" for check in network.sandbox["checks"]))
        self.assertFalse(secret.allowed)
        self.assertTrue(any(check["id"] == "secret_access" and check["status"] == "fail" for check in secret.sandbox["checks"]))

    def test_policy_denies_filesystem_paths_outside_workspace_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            outside = Path(temp_dir) / "outside"
            workspace.mkdir()
            outside.mkdir()
            policy = CommandPolicy(workspace_root=workspace)

            decision = policy.evaluate(["python", "-m", "compileall", str(outside)])

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "Command references a path outside the guarded workspace policy.")
        self.assertTrue(any(check["id"] == "filesystem_scope" and check["status"] == "fail" for check in decision.sandbox["checks"]))


class ExecutorTests(unittest.TestCase):
    def test_resolves_npm_shim_on_windows_without_shell(self):
        resolved = resolve_executable(["npm", "--version"])

        if os.name == "nt":
            self.assertTrue(resolved[0].lower().endswith(("npm.cmd", "npm.exe")))
        else:
            self.assertEqual(resolved[0], "npm")

    def test_strips_terminal_ansi_sequences_from_command_output(self):
        text = "\x1b[36mvite\x1b[39m \x1b[32mbuild completed\x1b[0m"

        self.assertEqual(strip_ansi(text), "vite build completed")

    def test_docker_containment_runner_builds_locked_down_command(self):
        runner = DockerContainmentRunner(docker_path="docker", image="python:3.13-slim")
        command = runner.docker_command(["python", "-m", "compileall", "."], ROOT)
        command_text = " ".join(command)

        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("PYTHONPYCACHEPREFIX=/tmp/pycache", command_text)
        self.assertIn("target=/workspace,readonly", command_text.replace("\\", "/"))
        self.assertEqual(command[-4:], ["python", "-m", "compileall", "."])
        self.assertTrue(runner.supports(["python", "-m", "compileall", "."]))
        self.assertFalse(runner.supports(["npm", "run", "build"]))

    def test_executor_routes_safe_static_check_through_available_containment_runner(self):
        class FakeContainmentRunner:
            def __init__(self):
                self.calls = []

            def available(self):
                return True

            def supports(self, command):
                return command[:3] == ["python", "-m", "compileall"]

            def profile(self):
                return {"mode": "docker", "engine": "fake-docker", "network": "none", "workspace": "read-only"}

            def run(self, command, cwd, timeout_seconds):
                self.calls.append((list(command), str(cwd), timeout_seconds))
                return CommandResult(0, "contained ok", "", 12, containment={"mode": "docker", "engine": "fake-docker"})

        runner = FakeContainmentRunner()
        executor = CommandExecutor(containment_runner=runner)
        decision = executor.policy_decision(["python", "-m", "compileall", "."], cwd=ROOT)
        result = executor.run(["python", "-m", "compileall", "."], cwd=ROOT)

        self.assertEqual(decision.sandbox["control_type"], "contained_execution")
        self.assertEqual(decision.sandbox["containment"], "docker")
        self.assertEqual(result.stdout, "contained ok")
        self.assertEqual(result.containment["engine"], "fake-docker")
        self.assertEqual(len(runner.calls), 1)

    def test_docker_containment_status_is_truthful_when_docker_missing_or_disabled(self):
        disabled = docker_containment_status(env={}, docker_path=None)
        enabled_missing = docker_containment_status(env={"AUTOCORE_ENABLE_DOCKER_CONTAINMENT": "1"}, docker_path="")
        enabled_no_probe = docker_containment_status(
            env={"AUTOCORE_ENABLE_DOCKER_CONTAINMENT": "1"},
            docker_path="docker",
            probe_daemon=False,
        )

        self.assertEqual(disabled["mode"], "not_configured")
        self.assertFalse(disabled["available"])
        self.assertEqual(enabled_missing["mode"], "docker_unavailable")
        self.assertFalse(enabled_missing["available"])
        self.assertEqual(enabled_no_probe["mode"], "docker_available")
        self.assertTrue(enabled_no_probe["available"])


class TaskPackTests(unittest.TestCase):
    def test_builtin_task_pack_defines_repo_readiness_eval(self):
        packs = list_task_packs()
        pack = packs[0]
        task = get_task("repo-readiness", "build-health")

        self.assertEqual(pack["id"], "repo-readiness")
        self.assertEqual(task["id"], "build-health")
        self.assertEqual(task["category"], "coding")
        self.assertIn("task_success", task["scoring_dimensions"])

    def test_builtin_task_pack_catalog_spans_multiple_eval_domains(self):
        packs = list_task_packs()
        ids = {pack["id"] for pack in packs}
        categories = {pack["category"] for pack in packs}

        self.assertGreaterEqual(len(packs), 4)
        self.assertIn("repo-readiness", ids)
        self.assertIn("research-reliability", ids)
        self.assertIn("data-sanity", ids)
        self.assertIn("browser-workflow", ids)
        self.assertGreaterEqual({"coding", "research", "data", "browser"} & categories, {"coding", "research", "data", "browser"})
        for pack in packs:
            self.assertIn("default_task_id", pack)
            self.assertTrue(any(task["id"] == pack["default_task_id"] for task in pack["tasks"]))
            self.assertIn("risk_level", pack)
            self.assertTrue(pack["tags"])

    def test_task_lookup_includes_pack_metadata_and_requirements(self):
        pack = get_task_pack("research-reliability")
        task = get_task("research-reliability", "source-grounding")
        default_research_task = default_task("research-reliability")

        self.assertEqual(pack["default_task_id"], "source-grounding")
        self.assertEqual(task["task_pack_id"], "research-reliability")
        self.assertEqual(task["task_pack_category"], "research")
        self.assertEqual(task["task_pack_risk_level"], "medium")
        self.assertIn("evidence_requirements", task)
        self.assertIn("tool_scope", task)
        self.assertEqual(default_research_task["id"], "source-grounding")


class ProviderTests(unittest.TestCase):
    def test_default_provider_is_offline_without_env(self):
        provider = select_provider({})

        self.assertIsInstance(provider, OfflineProvider)
        self.assertEqual(provider.metadata()["name"], "offline")
        self.assertEqual(provider.metadata()["model"], "heuristic")


class PromptLabTests(unittest.TestCase):
    def test_prompt_evaluator_scores_prompt_without_storing_raw_secret_values(self):
        task = get_task("repo-readiness", "build-health")
        prompt = (
            "Audit this repo for deployment readiness, run the safe build check, "
            "capture evidence, and do not read SECRET_TOKEN=abc123."
        )

        evaluation = evaluate_prompt(
            prompt,
            task,
            provider="groq",
            model="llama-3.3-70b-versatile",
            env={"GROQ_API_KEY": "present"},
        )
        payload = json.dumps(evaluation, sort_keys=True)

        self.assertEqual(evaluation["provider_signal"]["provider"], "groq")
        self.assertEqual(evaluation["provider_signal"]["quota_known"], False)
        self.assertEqual(evaluation["token_forecast"]["est_input_tokens"] > 0, True)
        self.assertGreaterEqual(evaluation["scores"]["clarity"], 70)
        self.assertIn(evaluation["verdict"], {"ready", "revise", "blocked"})
        self.assertIn("SECRET_TOKEN=[redacted]", evaluation["prompt_preview"])
        self.assertNotIn("abc123", payload)
        self.assertTrue(evaluation["recommendations"])

    def test_prompt_evaluator_blocks_empty_or_too_vague_prompts(self):
        task = get_task("research-reliability", "source-grounding")

        evaluation = evaluate_prompt("help", task, provider="offline", model="heuristic")

        self.assertEqual(evaluation["verdict"], "blocked")
        self.assertLess(evaluation["scores"]["clarity"], 50)
        self.assertTrue(any("specific" in finding["message"].lower() for finding in evaluation["findings"]))

    def test_provider_signal_parsers_keep_quota_truthful(self):
        groq = parse_groq_rate_limit_headers(
            {
                "x-ratelimit-remaining-tokens": "12000",
                "x-ratelimit-remaining-requests": "42",
            },
            provider="groq",
            model="llama-3.3-70b-versatile",
        )
        openai = parse_openai_usage_cost_payload(
            {
                "data": [
                    {
                        "results": [
                            {"input_tokens": 1000, "output_tokens": 250},
                            {"input_tokens": 500, "output_tokens": 100},
                        ]
                    }
                ]
            },
            provider="openai",
            model="gpt-4.1-mini",
        )

        self.assertTrue(groq["quota_known"])
        self.assertEqual(groq["remaining_tokens"], 12000)
        self.assertEqual(groq["remaining_requests"], 42)
        self.assertFalse(openai["quota_known"])
        self.assertTrue(openai["usage_known"])
        self.assertEqual(openai["used_tokens"], 1850)

    def test_store_persists_redacted_prompt_evaluations_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AutoCoreStore(Path(temp_dir) / "autocore.db")
            task = get_task("repo-readiness", "build-health")
            evaluation = evaluate_prompt(
                "Audit deployment with api_key=live-secret-value and produce evidence.",
                task,
                provider="offline",
                model="heuristic",
            )

            evaluation_id = store.save_prompt_evaluation(evaluation)
            saved = store.get_prompt_evaluation(evaluation_id)
            history = store.list_prompt_evaluations()
            with closing(sqlite3.connect(Path(temp_dir) / "autocore.db")) as conn:
                rows = conn.execute("SELECT * FROM prompt_evaluations").fetchall()
                columns = [column[1] for column in conn.execute("PRAGMA table_info(prompt_evaluations)").fetchall()]

        payload = json.dumps(saved, sort_keys=True)
        self.assertEqual(saved["id"], evaluation_id)
        self.assertEqual(history[0]["id"], evaluation_id)
        self.assertIn("api_key=[redacted]", payload)
        self.assertNotIn("live-secret-value", payload)
        self.assertNotIn("prompt", columns)
        self.assertEqual(len(rows), 1)

    def test_prompt_lab_api_evaluates_and_lists_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/prompt-lab/evaluate",
                    data=json.dumps(
                        {
                            "prompt": "Audit repo readiness, run a safe check, capture evidence, and flag deployment risks.",
                            "task_pack_id": "repo-readiness",
                            "task_id": "build-health",
                            "provider": "offline",
                            "model": "heuristic",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    created = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/prompt-lab", timeout=5) as response:
                    listing = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertIn("evaluation", created)
        self.assertTrue(created["evaluation"]["id"].startswith("peval_"))
        self.assertEqual(listing["evaluations"][0]["id"], created["evaluation"]["id"])
        self.assertNotIn("Audit repo readiness, run a safe check", json.dumps(listing))

    def test_prompt_lab_is_read_only_in_public_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="public")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/prompt-lab", timeout=5) as response:
                    listing = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/prompt-lab/evaluate",
                    data=json.dumps({"prompt": "Audit this repo"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(listing["evaluations"], [])
        self.assertEqual(raised.exception.code, 403)

    def test_saved_prompt_evaluation_can_be_attached_to_run_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "check.py").write_text("print('ok')\n", encoding="utf-8")
            runtime = AutoCoreRuntime(state_dir=Path(temp_dir) / "state")
            task = get_task("repo-readiness", "build-health")
            evaluation = evaluate_prompt(
                "Audit this Python repo with safe compile checks and capture evidence.",
                task,
                provider="offline",
                model="heuristic",
            )
            evaluation_id = runtime.store.save_prompt_evaluation(evaluation)

            run = runtime.create_run(project, evaluation["prompt_preview"], prompt_evaluation_id=evaluation_id)
            bundle = runtime.evidence_bundle(run["id"])

        attached = bundle["json"]["planner"]["prompt_evaluation"]
        self.assertEqual(attached["id"], evaluation_id)
        self.assertIn("Prompt Lab", bundle["markdown"])
        self.assertNotIn("safe compile checks and capture evidence.", json.dumps(bundle["json"]))


class BuildAuditorTests(unittest.TestCase):
    def test_build_auditor_flags_mocked_data_and_limits_quality_security_claims_to_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^19.0.0", "vite": "^7.0.0"}}),
                encoding="utf-8",
            )
            (root / "README.md").write_text("Demo uses mocked customers for screenshots only.", encoding="utf-8")
            src = root / "src"
            src.mkdir()
            (src / "App.tsx").write_text("const mockedData = [{ name: 'demo' }];\nexport default function App() { return null }\n", encoding="utf-8")

            audit = audit_project(root)
            payload = json.dumps(audit, sort_keys=True).lower()

        self.assertEqual(audit["verdict"], "not_ready")
        self.assertFalse(audit["no_mocked_data"])
        self.assertTrue(any(item["id"] == "mocked_data" and item["status"] == "fail" for item in audit["checks"]))
        self.assertTrue(any("src/App.tsx" in item["evidence"] for item in audit["checks"] if item["id"] == "mocked_data"))
        self.assertEqual(audit["claims"]["quality"]["status"], "limited")
        self.assertEqual(audit["claims"]["security"]["status"], "limited")
        self.assertIn("claim_readiness", audit)
        self.assertTrue(any(item["claim"] == "No mocked data" and item["status"] == "blocked" for item in audit["claim_readiness"]))
        self.assertTrue(any(item["claim"] == "Deep security" and item["status"] == "blocked" for item in audit["claim_readiness"]))
        self.assertIn("security_scan", audit)
        self.assertTrue(any(item["id"] == "secrets" for item in audit["security_scan"]["checks"]))
        self.assertEqual(audit["containment"]["mode"], "not_configured")
        self.assertNotIn("deep code quality", payload)
        self.assertNotIn('"deep security", "status": "supported"', payload)

    def test_build_auditor_does_not_treat_its_own_mock_detection_guidance_as_mocked_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            product = root / "autocore"
            product.mkdir()
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}, "devDependencies": {"vite": "^7.0.0"}}),
                encoding="utf-8",
            )
            (product / "companion.py").write_text(
                "RISK_MARKERS = re.compile(r\"\\\\b(mocked?|fake|dummy|stub|placeholder|sample data)\\\\b\")\n"
                "PROMPT = 'Audit the changed files. Focus on mocked data, missing tests, and evidence.'\n",
                encoding="utf-8",
            )

            audit = audit_project(root)

        self.assertTrue(audit["no_mocked_data"])
        self.assertEqual(audit["mocked_findings"], [])

    def test_build_auditor_can_report_ready_without_mocked_data_when_evidence_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "vite build", "test": "python -m unittest"},
                        "dependencies": {"react": "^19.0.0", "vite": "^7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            (root / "README.md").write_text("Local-first audit console.", encoding="utf-8")
            src = root / "src"
            src.mkdir()
            (src / "App.tsx").write_text("export default function App() { return null }\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_app.py").write_text("import unittest\n", encoding="utf-8")

            audit = audit_project(root)

        self.assertEqual(audit["verdict"], "ready")
        self.assertTrue(audit["no_mocked_data"])
        self.assertEqual(audit["claims"]["quality"]["status"], "evidence_backed")
        self.assertIn("package-lock.json", audit["claims"]["quality"]["evidence"])
        self.assertTrue(any(item["claim"] == "Code quality evidence" and item["status"] == "supported" for item in audit["claim_readiness"]))
        self.assertTrue(any(item["claim"] == "Deep security" and item["status"] == "blocked" for item in audit["claim_readiness"]))
        self.assertTrue(audit["recommendations"])

    def test_build_auditor_security_scan_flags_client_token_and_docker_context_risks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")
            (root / "Dockerfile").write_text("FROM node:22\nCOPY . .\n", encoding="utf-8")
            src = root / "src"
            src.mkdir()
            (src / "runtime.ts").write_text("const token = import.meta.env.VITE_AUTOCORE_API_TOKEN;\n", encoding="utf-8")

            audit = audit_project(root)

        security_checks = {item["id"]: item for item in audit["security_scan"]["checks"]}
        self.assertEqual(security_checks["client_token_boundary"]["status"], "fail")
        self.assertEqual(security_checks["docker_context"]["status"], "fail")
        self.assertEqual(audit["claims"]["security"]["status"], "limited")
        self.assertTrue(any(item["claim"] == "Deep security" and item["status"] == "blocked" for item in audit["claim_readiness"]))

    def test_build_auditor_store_persists_recent_audits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AutoCoreStore(Path(temp_dir) / "autocore.db")
            root = Path(temp_dir) / "project"
            root.mkdir()
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            audit = audit_project(root)

            audit_id = store.save_build_audit(audit)
            saved = store.get_build_audit(audit_id)
            history = store.list_build_audits()

        self.assertEqual(saved["id"], audit_id)
        self.assertEqual(history[0]["id"], audit_id)
        self.assertEqual(saved["project"]["name"], "project")

    def test_build_auditor_api_runs_and_is_public_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            server = create_server(port=0, state_dir=Path(temp_dir) / "state")
            server.RequestHandlerClass.project_root = project
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/build-audits", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=5) as response:
                    created = json.loads(response.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build-audits", timeout=5) as response:
                    listing = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertIn("audit", created)
        self.assertTrue(created["audit"]["id"].startswith("audit_"))
        self.assertEqual(listing["audits"][0]["id"], created["audit"]["id"])

        with tempfile.TemporaryDirectory() as temp_dir:
            public_server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="public")
            thread = threading.Thread(target=public_server.serve_forever, daemon=True)
            thread.start()
            try:
                port = public_server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build-audits", timeout=5) as response:
                    public_listing = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/build-audits", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            finally:
                public_server.shutdown()
                public_server.server_close()
                thread.join(timeout=2)

        self.assertEqual(public_listing["audits"], [])
        self.assertEqual(raised.exception.code, 403)


class ConnectorTests(unittest.TestCase):
    def test_connector_inventory_reports_real_local_repo_without_mocked_external_connections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^19.0.0", "vite": "^7.0.0"}}),
                encoding="utf-8",
            )
            (root / "README.md").write_text("Personal repo", encoding="utf-8")

            inventory = build_connector_inventory(root, env={})

        connectors = {item["id"]: item for item in inventory["connectors"]}
        self.assertFalse(inventory["mocked"])
        self.assertEqual(connectors["local-repo"]["state"], "live_connected")
        self.assertEqual(connectors["local-repo"]["source"], "workspace")
        self.assertIn("package.json", connectors["local-repo"]["evidence"]["manifests"])
        self.assertEqual(connectors["github"]["state"], "not_connected")
        self.assertEqual(connectors["slack"]["state"], "not_connected")
        self.assertNotIn("demo_connected", {item["state"] for item in inventory["connectors"]})

    def test_connector_inventory_uses_env_presence_without_exposing_secret_values(self):
        inventory = build_connector_inventory(
            ROOT,
            env={
                "GITHUB_TOKEN": "ghp_secret_value",
                "SLACK_BOT_TOKEN": "xoxb-secret-value",
            },
        )

        connectors = {item["id"]: item for item in inventory["connectors"]}
        payload = json.dumps(inventory, sort_keys=True)
        self.assertEqual(connectors["github"]["state"], "paused")
        self.assertEqual(connectors["slack"]["state"], "paused")
        self.assertIn("GITHUB_TOKEN", connectors["github"]["required_env"])
        self.assertNotIn("ghp_secret_value", payload)
        self.assertNotIn("xoxb-secret-value", payload)

    def test_connector_endpoint_serves_inventory_from_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/connectors", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertIn("connectors", payload)
        self.assertFalse(payload["mocked"])
        self.assertIn("local-repo", {item["id"] for item in payload["connectors"]})


class PersonalAuditFlowTests(unittest.TestCase):
    def test_project_endpoint_serves_current_target_and_inspection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "target"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "echo ok"}, "dependencies": {"react": "^19.0.0", "vite": "^7.0.0"}}),
                encoding="utf-8",
            )
            previous_root = os.environ.get("AUTOCORE_PROJECT_ROOT")
            os.environ["AUTOCORE_PROJECT_ROOT"] = str(project)
            try:
                server = create_server(port=0, state_dir=Path(temp_dir) / "state")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/project", timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
            finally:
                if previous_root is None:
                    os.environ.pop("AUTOCORE_PROJECT_ROOT", None)
                else:
                    os.environ["AUTOCORE_PROJECT_ROOT"] = previous_root

        self.assertEqual(payload["project"]["name"], "target")
        self.assertEqual(payload["project"]["stack"], "React/Vite")
        self.assertTrue(payload["project"]["exists"])
        self.assertIn("package.json", payload["project"]["manifests"])
        self.assertIn("AUTOCORE_PROJECT_ROOT", payload["project"]["control"])

    def test_evidence_endpoint_lists_generated_reports_after_approved_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "target"
            project.mkdir()
            (project / "demo.py").write_text("print('ok')\n", encoding="utf-8")
            runtime = AutoCoreRuntime(state_dir=Path(temp_dir) / "state")

            run = runtime.create_run(project, "Audit target")
            command = run["commands"][0]
            self.assertEqual(command["command_text"], "python -m compileall .")
            completed = runtime.approve_command(run["id"], command["id"])

            listing = runtime.evidence_library()

        self.assertEqual(completed["status"], "evidence_ready")
        self.assertGreaterEqual(len(listing["reports"]), 1)
        latest = listing["reports"][0]
        self.assertEqual(latest["run_id"], run["id"])
        self.assertEqual(latest["markdown_filename"], f"{run['id']}.md")
        self.assertEqual(latest["json_filename"], f"{run['id']}.json")
        self.assertGreater(latest["markdown_bytes"], 0)
        self.assertGreater(latest["json_bytes"], 0)


class DeploymentSafetyTests(unittest.TestCase):
    def test_release_docs_are_self_hosted_byok_and_avoid_sandbox_claims(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8").lower()
        case_study = (ROOT / "PORTFOLIO_CASE_STUDY.md").read_text(encoding="utf-8").lower()
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").lower()
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8").lower()
        public_docs = "\n".join([readme, deployment, case_study, security, contributing, roadmap])

        self.assertIn("self-hosted", public_docs)
        self.assertIn("byok", public_docs)
        self.assertIn("open-source", public_docs)
        self.assertIn("guarded policy", public_docs)
        self.assertIn("contained execution", public_docs)
        self.assertIn("v0.1.0-alpha", public_docs)
        self.assertNotIn("sandbox", public_docs)
        self.assertNotIn("deep security", public_docs)

    def test_public_launch_docs_exist_and_keep_beginner_friendly_scope(self):
        for filename in ("SECURITY.md", "CONTRIBUTING.md", "ROADMAP.md"):
            self.assertTrue((ROOT / filename).exists(), filename)

        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8").lower()
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()

        self.assertIn("plain-english workflow", readme)
        self.assertIn("beginner-readable workflow", roadmap)
        self.assertIn("do not publish yet", roadmap)
        self.assertIn("does not currently claim full security coverage", security)

    def test_easy_start_scripts_exist_for_public_and_private_modes(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]

        self.assertEqual(scripts["build:public"], "node scripts/build-public.mjs")
        self.assertEqual(scripts["start:local"], "node scripts/start-local.mjs")
        self.assertEqual(scripts["start:public"], "node scripts/start-public.mjs")
        self.assertEqual(scripts["start:live"], "node scripts/start-live.mjs")
        self.assertEqual(scripts["start:contained"], "node scripts/start-live.mjs --containment")
        self.assertEqual(scripts["export:demo"], "python scripts/export_demo_snapshot.py")
        self.assertTrue((ROOT / "scripts" / "build-public.mjs").exists())
        self.assertTrue((ROOT / "scripts" / "start-local.mjs").exists())
        self.assertTrue((ROOT / "scripts" / "start-public.mjs").exists())
        self.assertTrue((ROOT / "scripts" / "start-live.mjs").exists())

    def test_local_launcher_check_reports_one_command_setup_without_starting_servers(self):
        result = subprocess.run(
            ["node", "scripts/start-local.mjs", "--check"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["command"], "npm run start:local")
        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["backend"]["requested_port"], 8787)
        self.assertEqual(payload["frontend"]["requested_port"], 5173)
        self.assertEqual(payload["backend"]["url"], f"http://127.0.0.1:{payload['backend']['port']}")
        self.assertEqual(payload["frontend"]["url"], f"http://127.0.0.1:{payload['frontend']['port']}/?section=setup")
        self.assertEqual(payload["environment"]["VITE_AUTOCORE_API_URL"], payload["backend"]["url"])
        self.assertTrue(payload["opens_browser"])
        self.assertTrue(any(check["id"] == "python" for check in payload["prerequisites"]))
        self.assertTrue(any(check["id"] == "node" for check in payload["prerequisites"]))
        self.assertTrue(any(check["id"] == "npm" for check in payload["prerequisites"]))

    def test_static_public_deploy_has_snapshot_and_vercel_config(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        api_source = (ROOT / "src" / "runtime" / "api.ts").read_text(encoding="utf-8")
        app_source = (ROOT / "src" / "App.tsx").read_text(encoding="utf-8")
        snapshot_path = ROOT / "public" / "demo-snapshot.json"
        task_pack_path = ROOT / "public" / "task-packs.json"
        setup_path = ROOT / "public" / "setup-status.json"
        companion_path = ROOT / "public" / "companion-status.json"

        self.assertEqual(vercel["buildCommand"], "npm run build:public")
        self.assertEqual(vercel["outputDirectory"], "dist")
        self.assertEqual(package["scripts"]["build:public"], "node scripts/build-public.mjs")
        self.assertIn("VITE_AUTOCORE_PUBLIC_SNAPSHOT", api_source)
        self.assertIn("PUBLIC_SNAPSHOT_MODE", app_source)
        self.assertTrue(snapshot_path.exists())
        self.assertTrue(task_pack_path.exists())
        self.assertTrue(setup_path.exists())
        self.assertTrue(companion_path.exists())
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        task_packs = json.loads(task_pack_path.read_text(encoding="utf-8"))
        setup = json.loads(setup_path.read_text(encoding="utf-8"))
        companion = json.loads(companion_path.read_text(encoding="utf-8"))
        self.assertTrue(snapshot["demo"]["read_only"])
        self.assertTrue(snapshot["demo"]["public_safe"])
        self.assertGreaterEqual(len(task_packs["task_packs"]), 4)
        self.assertTrue(setup["setup"]["read_only"])
        self.assertTrue(companion["companion"]["read_only"])

    def test_untrusted_project_scripts_are_blocked_before_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "untrusted"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"build": "node -e \"require('fs').writeFileSync('autocore_poc.txt', 'ran')\""},
                        "devDependencies": {"vite": "^7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            runtime = AutoCoreRuntime(state_dir=Path(temp_dir) / "state")

            run = runtime.create_run(project, "Audit untrusted project")
            command = run["commands"][0]
            updated = runtime.approve_command(run["id"], command["id"])

            self.assertEqual(command["command_text"], "npm run build")
            self.assertEqual(command["state"], "blocked")
            self.assertIn("trusted local mode", command["policy_reason"])
            self.assertEqual(updated["status"], "blocked")
            self.assertFalse((project / "autocore_poc.txt").exists())

    def test_dockerignore_excludes_private_runtime_artifacts(self):
        dockerignore = ROOT / ".dockerignore"

        self.assertTrue(dockerignore.exists())
        content = dockerignore.read_text(encoding="utf-8")
        for pattern in (".env", ".env.*", "!.env.example", ".autocore/", "qa/", "node_modules/", "dist/", "__pycache__/", "*.tsbuildinfo"):
            self.assertIn(pattern, content)

    def test_vercelignore_excludes_private_runtime_artifacts(self):
        vercelignore = ROOT / ".vercelignore"

        self.assertTrue(vercelignore.exists())
        content = vercelignore.read_text(encoding="utf-8")
        for pattern in (".env", ".env.*", "!.env.example", ".autocore/", "qa/", "node_modules/", "dist/", "__pycache__/", "*.tsbuildinfo"):
            self.assertIn(pattern, content)

    def test_frontend_does_not_embed_static_api_token(self):
        api_source = (ROOT / "src" / "runtime" / "api.ts").read_text(encoding="utf-8")
        durable_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "README.md", ROOT / "DEPLOYMENT.md", ROOT / ".env.example")
        )

        self.assertNotIn("VITE_AUTOCORE_API_TOKEN", api_source)
        self.assertNotIn("VITE_AUTOCORE_API_TOKEN", durable_docs)
        self.assertNotIn("Authorization: `Bearer ${API_TOKEN}`", api_source)

    def test_public_mode_serves_static_demo_and_blocks_mutations_without_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir) / "dist"
            static_dir.mkdir()
            (static_dir / "index.html").write_text("<!doctype html><title>AutoCore</title>", encoding="utf-8")
            server = create_server(
                port=0,
                state_dir=Path(temp_dir) / "state",
                mode="public",
                static_dir=static_dir,
                allowed_origins=["https://autocore.example"],
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/project", timeout=5) as response:
                    project_payload = json.loads(response.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/runs",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertIn("AutoCore", html)
        self.assertEqual(project_payload["project"]["path"], "public-demo-workspace")
        self.assertEqual(raised.exception.code, 403)

    def test_live_network_bind_requires_api_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(RuntimeError):
                create_server(host="0.0.0.0", port=0, state_dir=Path(temp_dir) / "state", mode="live")

    def test_live_auth_token_protects_sensitive_api_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live", api_token="dev-secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/project", timeout=5)
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/project",
                    headers={"Authorization": "Bearer dev-secret"},
                    method="GET",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(raised.exception.code, 401)
        self.assertIn("project", payload)

    def test_live_api_errors_are_generic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state", mode="live", api_token="dev-secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/runs",
                    data=json.dumps({"task_pack_id": "missing-pack", "task_id": "missing-task"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer dev-secret"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                body = raised.exception.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        payload = json.loads(body)
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(payload["error"], "Bad request")
        self.assertNotIn("missing-pack", body)
        self.assertNotIn("Unknown task", body)


class ReleaseIntegrityGateTests(unittest.TestCase):
    def test_release_integrity_gate_is_wired_to_real_scripts(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(package["scripts"]["verify:release"], "node scripts/verify-release.mjs")
        for script_name in ("verify-release.mjs", "secret-scan.py", "public-safety-scan.py", "release-smoke.py"):
            self.assertTrue((ROOT / "scripts" / script_name).exists(), script_name)

    def test_secret_scan_fails_on_real_token_patterns_but_allows_placeholders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "src"
            source.mkdir()
            (source / "settings.py").write_text(
                "OPENAI_API_KEY='sk-testsecretvalue1234567890abcdef'\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "scripts/secret-scan.py", str(root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("settings.py", result.stdout)
        self.assertIn("secret", result.stdout.lower())

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env.example").write_text(
                "OPENAI_API_KEY=your-local-key\nGROQ_API_KEY=...\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "Set `AUTOCORE_API_TOKEN=replace-with-a-long-random-token` before networked live mode.\n",
                encoding="utf-8",
            )

            clean = subprocess.run(
                [sys.executable, "scripts/secret-scan.py", str(root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)

    def test_public_safety_scan_fails_on_local_paths_and_env_leaks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dist = root / "dist"
            dist.mkdir()
            (dist / "assets.js").write_text(
                'window.__AUTOCORE__="C:\\\\Users\\\\user\\\\project\\\\.env";',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "scripts/public-safety-scan.py", str(root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("assets.js", result.stdout)
        self.assertIn("local_path", result.stdout)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            public = root / "public"
            public.mkdir()
            (public / "demo-snapshot.json").write_text(
                json.dumps({"project": {"path": "public-demo-workspace"}, "read_only": True}),
                encoding="utf-8",
            )
            (public / "client.js").write_text(
                "const publicFlag = import.meta.env.VITE_AUTOCORE_PUBLIC_SNAPSHOT;\n",
                encoding="utf-8",
            )

            clean = subprocess.run(
                [sys.executable, "scripts/public-safety-scan.py", str(root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)


class FakeProvider:
    def metadata(self):
        return {"name": "fake", "model": "unit-test", "mode": "mocked"}

    def propose_plan(self, request):
        return ProviderResponse(
            commands=[["npm", "install"], ["npm", "run", "build"]],
            risks=["Provider requested dependency installation.", "Validate production build before release."],
            notes="Fake provider plan",
        )


class PlannerTests(unittest.TestCase):
    def test_planner_filters_provider_commands_through_policy(self):
        inspection = {
            "stack": "React/Vite",
            "recommended_commands": [["npm", "run", "build"]],
            "risk_surfaces": {"has_env": True},
        }
        task = get_task("repo-readiness", "build-health")
        plan = AgentPlanner(provider=FakeProvider(), policy=CommandPolicy(trust_project_scripts=True)).create_plan("Audit repo", inspection, task)

        self.assertEqual(plan["provider"]["name"], "fake")
        self.assertEqual(plan["selected_command"], ["npm", "run", "build"])
        self.assertEqual(plan["blocked_proposals"][0]["command"], ["npm", "install"])
        self.assertTrue(any("env" in risk.lower() for risk in plan["risks"]))
        self.assertGreater(plan["confidence"], 0)


class ScoringTests(unittest.TestCase):
    def test_scorecard_rewards_successful_checked_run_with_evidence(self):
        task = get_task("repo-readiness", "build-health")
        run = {
            "status": "evidence_ready",
            "events": [
                {"kind": "intake", "status": "ok"},
                {"kind": "approval", "status": "ok"},
                {"kind": "execute", "status": "ok"},
            ],
            "commands": [
                {
                    "state": "completed",
                    "exit_code": 0,
                    "duration_ms": 900,
                    "stdout": "built",
                    "stderr": "",
                }
            ],
            "inspection": {"stack": "React/Vite", "manifests": ["package.json"]},
        }

        scorecard = compute_scorecard(run, task)

        self.assertGreaterEqual(scorecard["overall"], 80)
        self.assertEqual(scorecard["grade"], "ready")
        self.assertEqual(scorecard["counters"]["completed_commands"], 1)
        self.assertTrue(any(item["id"] == "evidence_completeness" for item in scorecard["dimensions"]))

    def test_scorecard_labels_human_dependency_metric_clearly(self):
        task = get_task("repo-readiness", "build-health")
        run = {
            "status": "evidence_ready",
            "events": [{"kind": "approval", "status": "ok"}],
            "commands": [{"state": "completed", "exit_code": 0, "duration_ms": 100, "stdout": "ok", "stderr": ""}],
            "inspection": {"stack": "React/Vite", "manifests": ["package.json"]},
        }

        scorecard = compute_scorecard(run, task)
        dimension = next(item for item in scorecard["dimensions"] if item["id"] == "intervention_efficiency")

        self.assertEqual(dimension["label"], "Hands-off Autonomy")
        self.assertIn("operator dependency", dimension["evidence"])

    def test_scorecard_penalizes_failed_or_blocked_runs(self):
        task = get_task("repo-readiness", "build-health")
        run = {
            "status": "failed",
            "events": [{"kind": "blocked", "status": "blocked"}, {"kind": "approval", "status": "attention"}],
            "commands": [{"state": "failed", "exit_code": 1, "duration_ms": 100, "stdout": "", "stderr": "boom"}],
            "inspection": {"stack": "React/Vite", "manifests": []},
        }

        scorecard = compute_scorecard(run, task)

        self.assertLess(scorecard["overall"], 60)
        self.assertEqual(scorecard["grade"], "not_ready")
        self.assertEqual(scorecard["counters"]["blocked_actions"], 1)


class StoreTests(unittest.TestCase):
    def test_store_persists_run_events_and_pending_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AutoCoreStore(Path(temp_dir) / "autocore.db")
            run_id = store.create_run(path=ROOT, goal="Audit repo", inspection={"stack": "React/Vite"})
            decision = CommandPolicy().evaluate(["npm", "run", "build"])
            command_id = store.add_pending_command(
                run_id,
                ["npm", "run", "build"],
                "Production build",
                sandbox=decision.sandbox,
            )
            store.add_event(run_id, kind="approval", title="Approval required", detail="Build is pending")

            run = store.get_run(run_id)

        self.assertEqual(run["id"], run_id)
        self.assertIn("planner", run)
        self.assertEqual(run["planner"]["provider"]["name"], "offline")
        self.assertEqual(run["task_pack_id"], "repo-readiness")
        self.assertEqual(run["task_id"], "build-health")
        self.assertEqual(run["commands"][0]["id"], command_id)
        self.assertEqual(run["commands"][0]["state"], "pending")
        self.assertEqual(run["commands"][0]["sandbox"]["profile_id"], "guarded.local")
        self.assertEqual(run["commands"][0]["sandbox"]["capability"], "build")
        self.assertEqual(run["events"][0]["title"], "Approval required")

    def test_store_lists_recent_runs_newest_first_with_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AutoCoreStore(Path(temp_dir) / "autocore.db")
            older_id = store.create_run(path=ROOT, goal="Older audit", inspection={"stack": "React/Vite"})
            newer_id = store.create_run(path=ROOT, goal="Newer audit", inspection={"stack": "React/Vite"})

            runs = store.list_runs(limit=1)

        self.assertEqual([run["id"] for run in runs], [newer_id])
        self.assertNotIn(older_id, [run["id"] for run in runs])


class HistoryTests(unittest.TestCase):
    def _seed_scored_run(self, store, goal, score, grade, duration_ms=100, interventions=1, blocked=0):
        scorecard = {
            "overall": score,
            "grade": grade,
            "task_pack_id": "repo-readiness",
            "task_pack_name": "Repo Readiness",
            "task_id": "build-health",
            "task_title": "Build Health",
            "dimensions": [],
            "counters": {
                "completed_commands": 1 if grade == "ready" else 0,
                "failed_commands": 0 if grade == "ready" else 1,
                "pending_commands": 0,
                "blocked_actions": blocked,
                "interventions": interventions,
                "duration_ms": duration_ms,
            },
        }
        planner = {
            "provider": {"name": "offline", "model": "heuristic", "mode": "local"},
            "selected_command": ["npm", "run", "build"],
        }
        run_id = store.create_run(
            path=ROOT,
            goal=goal,
            inspection={"stack": "React/Vite", "manifests": ["package.json"]},
            planner=planner,
        )
        command_id = store.add_pending_command(run_id, ["npm", "run", "build"], "Build check")
        command_state = "completed" if grade == "ready" else "failed"
        store.update_command_result(command_id, command_state, 0 if grade == "ready" else 1, "ok", "", duration_ms)
        store.add_event(run_id, "approval", "Approved", "Operator approved execution.", "ok")
        store.update_run(run_id, "evidence_ready" if grade == "ready" else "failed")
        store.update_scorecard(run_id, scorecard)
        return run_id

    def test_runtime_history_summarizes_score_drift_and_run_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AutoCoreStore(Path(temp_dir) / "autocore.db")
            older_id = self._seed_scored_run(store, "Baseline audit", 64, "watch", duration_ms=900)
            newer_id = self._seed_scored_run(store, "Hardened audit", 86, "ready", duration_ms=700)
            runtime = AutoCoreRuntime(store=store)

            history = runtime.run_history(limit=10)

        self.assertEqual(history["summary"]["total_runs"], 2)
        self.assertEqual(history["summary"]["latest_score"], 86)
        self.assertEqual(history["summary"]["previous_score"], 64)
        self.assertEqual(history["summary"]["score_delta"], 22)
        self.assertEqual(history["summary"]["trend"], "improving")
        self.assertEqual(history["summary"]["average_score"], 75)
        self.assertEqual(history["summary"]["best_score"], 86)
        self.assertEqual(history["summary"]["worst_score"], 64)
        self.assertEqual(history["runs"][0]["id"], newer_id)
        self.assertEqual(history["runs"][1]["id"], older_id)
        self.assertEqual(history["runs"][0]["provider"], "offline / heuristic")
        self.assertEqual(history["runs"][0]["selected_command"], "npm run build")
        self.assertEqual(history["runs"][0]["duration_ms"], 700)


class DemoReleaseTests(unittest.TestCase):
    def test_demo_snapshot_is_read_only_public_safe_and_sanitized(self):
        self.assertIsNotNone(demo_snapshot, "demo_snapshot should expose the public demo contract")

        snapshot = demo_snapshot(ROOT)
        payload = json.dumps(snapshot, sort_keys=True)

        self.assertEqual(snapshot["mode"], "demo")
        self.assertTrue(snapshot["read_only"])
        self.assertTrue(snapshot["public_safe"])
        self.assertNotIn(str(ROOT), payload)
        self.assertNotIn("OneDrive", payload)
        self.assertNotIn(".env", payload)
        self.assertEqual(snapshot["run"]["path"], "public-demo-workspace")
        self.assertEqual(snapshot["run"]["status"], "evidence_ready")
        self.assertEqual(snapshot["run"]["commands"][0]["state"], "completed")
        self.assertEqual(snapshot["run"]["commands"][0]["sandbox"]["profile_id"], "trusted.project")
        self.assertEqual(snapshot["evidence"]["json"]["id"], snapshot["run"]["id"])
        self.assertIn("## Guarded Policy", snapshot["evidence"]["markdown"])

    def test_demo_snapshot_includes_portfolio_case_study_and_history(self):
        self.assertIsNotNone(demo_snapshot, "demo_snapshot should expose the public demo contract")

        snapshot = demo_snapshot(ROOT)

        self.assertGreaterEqual(len(snapshot["case_study"]["proof_points"]), 4)
        self.assertGreaterEqual(len(snapshot["onboarding"]), 3)
        self.assertIn("open_ui", snapshot["artifacts"])
        self.assertIn("api_demo", snapshot["artifacts"])
        self.assertEqual(snapshot["history"]["summary"]["total_runs"], 1)
        self.assertEqual(snapshot["history"]["runs"][0]["id"], snapshot["run"]["id"])

    def test_demo_snapshot_uses_current_build_evidence_copy(self):
        self.assertIsNotNone(demo_snapshot, "demo_snapshot should expose the public demo contract")

        snapshot = demo_snapshot(ROOT)
        payload = json.dumps(snapshot, sort_keys=True)

        self.assertIn("vite v7.3.2", payload)
        self.assertNotIn("vite v7.2.4", payload)
        self.assertNotIn("Future agents need proof", payload)

    def test_demo_endpoint_serves_read_only_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = create_server(port=0, state_dir=Path(temp_dir) / "state")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/demo", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(payload["demo"]["mode"], "demo")
        self.assertTrue(payload["demo"]["read_only"])
        self.assertEqual(payload["demo"]["run"]["path"], "public-demo-workspace")


class RuntimeTests(unittest.TestCase):
    def test_runtime_records_contained_execution_evidence_when_runner_is_available(self):
        class FakeContainmentRunner:
            def available(self):
                return True

            def supports(self, command):
                return command[:3] == ["python", "-m", "compileall"]

            def profile(self):
                return {"mode": "docker", "engine": "fake-docker", "network": "none", "workspace": "read-only"}

            def run(self, command, cwd, timeout_seconds):
                return CommandResult(0, "contained compile ok", "", 10, containment={"mode": "docker", "engine": "fake-docker"})

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            (project / "module.py").write_text("print('ok')\n", encoding="utf-8")
            executor = CommandExecutor(containment_runner=FakeContainmentRunner())
            runtime = AutoCoreRuntime(state_dir=Path(temp_dir) / "state", executor=executor, policy=executor.policy)

            run = runtime.create_run(project, "Run contained static check")
            command = run["commands"][0]
            updated = runtime.approve_command(run["id"], command["id"])
            bundle = runtime.evidence_bundle(run["id"])

        completed = updated["commands"][0]
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["sandbox"]["control_type"], "contained_execution")
        self.assertEqual(completed["sandbox"]["containment"], "docker")
        self.assertIn("contained compile ok", completed["stdout"])
        self.assertIn("Containment: `docker`", bundle["markdown"])

    def test_runtime_uses_selected_task_pack_goal_when_goal_is_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "echo ok"}, "devDependencies": {"vite": "^7.0.0"}}),
                encoding="utf-8",
            )
            runtime = AutoCoreRuntime(state_dir=Path(temp_dir) / "state")

            run = runtime.create_run(
                project,
                "",
                task_pack_id="research-reliability",
                task_id="source-grounding",
            )

        task = get_task("research-reliability", "source-grounding")
        self.assertEqual(run["goal"], task["goal"])
        self.assertEqual(run["task_pack_id"], "research-reliability")
        self.assertEqual(run["task_id"], "source-grounding")
        self.assertEqual(run["scorecard"]["task_pack_id"], "research-reliability")
        self.assertEqual(run["scorecard"]["task_title"], task["title"])
        self.assertIn(task["goal"], run["events"][0]["detail"])

    def test_runtime_approves_and_executes_allowlisted_command_with_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.1'\n", encoding="utf-8")
            script = project / "check.py"
            script.write_text("print('autocore check ok')\n", encoding="utf-8")

            state_dir = Path(temp_dir) / "state"
            runtime = AutoCoreRuntime(
                state_dir=state_dir,
                executor=CommandExecutor(timeout_seconds=10),
            )
            run = runtime.create_run(project, "Run safe check", command=["python", "-m", "compileall", str(project)])
            command_id = run["commands"][0]["id"]

            updated = runtime.approve_command(run["id"], command_id)
            evidence = runtime.write_evidence(run["id"])
            evidence_bundle = runtime.evidence_bundle(run["id"])

            command = updated["commands"][0]
            self.assertEqual(command["state"], "completed")
            self.assertEqual(command["exit_code"], 0)
            self.assertIn("compileall", command["command_text"])
            self.assertEqual(updated["task_pack_id"], "repo-readiness")
            self.assertEqual(updated["scorecard"]["grade"], "ready")
            self.assertEqual(updated["planner"]["selected_command"], ["python", "-m", "compileall", str(project)])
            self.assertEqual(command["sandbox"]["profile_id"], "guarded.local")
            self.assertEqual(command["sandbox"]["filesystem"], "workspace-read")
            self.assertEqual(command["sandbox"]["network"], "deny")
            self.assertEqual(command["sandbox"]["secrets"], "deny")
            self.assertTrue(Path(evidence["markdown_path"]).exists())
            self.assertTrue(Path(evidence["json_path"]).exists())
            self.assertIn("# AutoCore Evidence Report", evidence_bundle["markdown"])
            self.assertIn("## Guarded Policy", evidence_bundle["markdown"])
            self.assertEqual(evidence_bundle["json"]["id"], run["id"])
            self.assertEqual(evidence_bundle["summary"]["grade"], "ready")
            self.assertEqual(evidence_bundle["summary"]["commands"], 1)


if __name__ == "__main__":
    unittest.main()
