from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Sequence

from .safety import CommandPolicy, PolicyDecision


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    containment: dict | None = None


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def resolve_executable(command: Sequence[str]) -> list[str]:
    if not command:
        return []

    program = command[0]
    if program.lower() == "npm":
        resolved = which("npm.cmd") or which("npm.exe") or which("npm")
        if resolved:
            return [resolved, *command[1:]]
    return list(command)


class CommandExecutor:
    def __init__(self, policy: CommandPolicy | None = None, timeout_seconds: int = 60, containment_runner: object | None = None) -> None:
        self.policy = policy or CommandPolicy()
        self.timeout_seconds = timeout_seconds
        self.containment_runner = containment_runner

    def policy_decision(self, command: Sequence[str], cwd: str | Path) -> PolicyDecision:
        decision = self.policy.evaluate(command, workspace_root=Path(cwd).resolve())
        if not decision.allowed:
            return decision
        if not self._can_contain(command):
            return decision
        profile = self.containment_runner.profile()
        sandbox = {
            **decision.sandbox,
            "control_type": "contained_execution",
            "containment": profile.get("mode", "docker"),
            "containment_profile": profile,
            "execution_warning": "Command is routed through contained execution with no container network and a read-only workspace mount.",
        }
        return PolicyDecision(decision.allowed, "Command matches safe check allowlist and will use contained execution.", "medium", sandbox)

    def run(self, command: Sequence[str], cwd: str | Path) -> CommandResult:
        decision = self.policy_decision(command, cwd)
        if not decision.allowed:
            return CommandResult(None, "", decision.reason, 0)

        if decision.sandbox.get("control_type") == "contained_execution" and self._can_contain(command):
            return self.containment_runner.run(command, Path(cwd).resolve(), self.timeout_seconds)

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                resolve_executable(command),
                cwd=str(Path(cwd).resolve()),
                shell=False,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return CommandResult(
                completed.returncode,
                strip_ansi(completed.stdout),
                strip_ansi(completed.stderr),
                duration_ms,
            )
        except subprocess.TimeoutExpired as error:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return CommandResult(
                None,
                strip_ansi(error.stdout or ""),
                strip_ansi((error.stderr or "") + f"\nCommand timed out after {self.timeout_seconds}s."),
                duration_ms,
                timed_out=True,
            )

    def _can_contain(self, command: Sequence[str]) -> bool:
        runner = self.containment_runner
        if runner is None:
            return False
        return bool(runner.available() and runner.supports(command))
