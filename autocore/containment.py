from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from shutil import which
from typing import Any, Mapping, Sequence

from .executor import CommandResult, strip_ansi


CONTAINABLE_PREFIXES = (
    ("python", "-m", "compileall"),
    ("python", "-m", "py_compile"),
)


def _env_flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _docker_daemon_ready(docker_path: str, timeout_seconds: int = 3) -> bool:
    try:
        completed = subprocess.run(
            [docker_path, "info", "--format", "{{.ServerVersion}}"],
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())


def docker_containment_status(env: Mapping[str, str] | None = None, docker_path: str | None = None, probe_daemon: bool = True) -> dict[str, Any]:
    resolved_env = os.environ if env is None else env
    requested = _env_flag(resolved_env, "AUTOCORE_ENABLE_DOCKER_CONTAINMENT")
    resolved_docker = docker_path if docker_path is not None else which("docker")
    if not requested:
        return {
            "mode": "not_configured",
            "available": False,
            "engine": None,
            "notes": "Docker containment is disabled. AutoCore uses guarded local policy.",
        }
    if not resolved_docker:
        return {
            "mode": "docker_unavailable",
            "available": False,
            "engine": "docker",
            "notes": "Docker containment was requested, but the Docker executable was not found.",
        }
    if probe_daemon and not _docker_daemon_ready(resolved_docker):
        return {
            "mode": "docker_daemon_unavailable",
            "available": False,
            "engine": "docker",
            "notes": "Docker is installed, but the Docker daemon is not reachable.",
        }
    return {
        "mode": "docker_available",
        "available": True,
        "engine": "docker",
        "notes": "Docker containment is available for supported safe static checks.",
    }


class DockerContainmentRunner:
    def __init__(self, docker_path: str | None = None, image: str = "python:3.13-slim") -> None:
        self.docker_path = docker_path if docker_path is not None else which("docker")
        self.image = image
        self._available_cache: bool | None = None

    def available(self) -> bool:
        if not self.docker_path:
            return False
        if self._available_cache is None:
            self._available_cache = _docker_daemon_ready(self.docker_path)
        return self._available_cache

    def supports(self, command: Sequence[str]) -> bool:
        normalized = tuple(part.strip().lower() for part in command)
        return any(tuple(normalized[: len(prefix)]) == prefix for prefix in CONTAINABLE_PREFIXES)

    def profile(self) -> dict[str, Any]:
        return {
            "mode": "docker",
            "engine": "docker",
            "image": self.image,
            "network": "none",
            "workspace": "read-only",
        }

    def docker_command(self, command: Sequence[str], cwd: str | Path) -> list[str]:
        workspace = str(Path(cwd).resolve())
        return [
            self.docker_path or "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--workdir",
            "/workspace",
            "--env",
            "PYTHONPYCACHEPREFIX=/tmp/pycache",
            "--mount",
            f"type=bind,source={workspace},target=/workspace,readonly",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            self.image,
            *command,
        ]

    def run(self, command: Sequence[str], cwd: str | Path, timeout_seconds: int) -> CommandResult:
        if not self.available():
            return CommandResult(None, "", "Docker containment requested, but Docker is not available.", 0)
        if not self.supports(command):
            return CommandResult(None, "", "Command is not supported by Docker containment profile.", 0)

        started = time.perf_counter()
        docker_command = self.docker_command(command, cwd)
        try:
            completed = subprocess.run(
                docker_command,
                cwd=str(Path(cwd).resolve()),
                shell=False,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return CommandResult(
                completed.returncode,
                strip_ansi(completed.stdout),
                strip_ansi(completed.stderr),
                duration_ms,
                containment=self.profile(),
            )
        except subprocess.TimeoutExpired as error:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return CommandResult(
                None,
                strip_ansi(error.stdout or ""),
                strip_ansi((error.stderr or "") + f"\nContained command timed out after {timeout_seconds}s."),
                duration_ms,
                timed_out=True,
                containment=self.profile(),
            )
