from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


SHELL_TOKENS = (";", "&&", "||", "|", ">", "<", "`", "$(", "\n", "\r")
SHELL_PROGRAMS = {
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "bash",
    "sh",
    "rm",
    "del",
    "erase",
    "rmdir",
    "remove-item",
}
NETWORK_PROGRAMS = {
    "curl",
    "wget",
}
BLOCKED_PROGRAMS = SHELL_PROGRAMS | NETWORK_PROGRAMS
SECRET_MARKERS = (".env", "secret", "secrets", "token", "tokens", ".pem", "id_rsa", "credentials")
SAFE_CHECK_PREFIXES = (
    ("python", "-m", "compileall"),
    ("python", "-m", "py_compile"),
)
PROJECT_SCRIPT_PREFIXES = (
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("npm", "run", "typecheck"),
    ("python", "-m", "pytest"),
    ("pytest",),
)
SANDBOX_PROFILE = {
    "profile_id": "guarded.local",
    "control_type": "guarded_policy",
    "containment": "none",
    "filesystem": "workspace-read",
    "network": "deny",
    "secrets": "deny",
    "shell": "deny",
    "execution_warning": "Policy checks constrain argv and command prefixes, but they are not OS-contained.",
}
TRUSTED_PROJECT_PROFILE = {
    "profile_id": "trusted.project",
    "control_type": "trusted_project_execution",
    "containment": "none",
    "filesystem": "workspace",
    "network": "host-inherited",
    "secrets": "host-inherited",
    "shell": "project-script",
    "execution_warning": "Approved project scripts run as trusted local project code and are not OS-contained.",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    risk: str
    sandbox: dict[str, Any] = field(default_factory=dict)


class CommandPolicy:
    """Narrow allowlist for check/build commands that can run without a shell."""

    def __init__(
        self,
        allowed_prefixes: Iterable[Sequence[str]] | None = None,
        trusted_project_prefixes: Iterable[Sequence[str]] | None = None,
        workspace_root: str | Path | None = None,
        trust_project_scripts: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.trust_project_scripts = trust_project_scripts
        self.allowed_prefixes = tuple(
            tuple(part.lower() for part in prefix)
            for prefix in (allowed_prefixes or SAFE_CHECK_PREFIXES)
        )
        self.trusted_project_prefixes = tuple(
            tuple(part.lower() for part in prefix)
            for prefix in (trusted_project_prefixes or PROJECT_SCRIPT_PREFIXES)
        )

    def profile(self) -> dict[str, Any]:
        return {
            **SANDBOX_PROFILE,
            "allowed_prefixes": [" ".join(prefix) for prefix in self.allowed_prefixes],
            "trusted_project_prefixes": [" ".join(prefix) for prefix in self.trusted_project_prefixes],
            "trusted_project_scripts": self.trust_project_scripts,
            "blocked_programs": sorted(BLOCKED_PROGRAMS),
            "secret_markers": list(SECRET_MARKERS),
        }

    def evaluate(self, command: Sequence[str], workspace_root: str | Path | None = None) -> PolicyDecision:
        root = Path(workspace_root).resolve() if workspace_root else self.workspace_root
        capability = self._capability(command)
        checks: list[dict[str, str]] = []

        if not command:
            sandbox = self._sandbox(capability, checks)
            return PolicyDecision(False, "Command is empty.", "high", sandbox)

        normalized = tuple(part.strip().lower() for part in command)
        program = normalized[0]

        if program in NETWORK_PROGRAMS:
            checks.append({"id": "network", "status": "fail", "detail": "Network-capable programs are denied."})
            sandbox = self._sandbox(capability, checks)
            return PolicyDecision(False, "Network access is denied by guarded.local.", "high", sandbox)

        checks.append({"id": "network", "status": "pass", "detail": "No network-capable program detected."})

        if program in SHELL_PROGRAMS:
            checks.append({"id": "shell", "status": "fail", "detail": "Shell or destructive program denied."})
            sandbox = self._sandbox(capability, checks)
            return PolicyDecision(False, f"Program `{command[0]}` is not allowed.", "high", sandbox)

        checks.append({"id": "shell", "status": "pass", "detail": "Command is argv-only and shell-free."})

        for part in command:
            if not part or any(token in part for token in SHELL_TOKENS):
                checks.append({"id": "shell_tokens", "status": "fail", "detail": "Shell metacharacters are not allowed."})
                sandbox = self._sandbox(capability, checks)
                return PolicyDecision(False, "Shell metacharacters are not allowed.", "high", sandbox)

        checks.append({"id": "shell_tokens", "status": "pass", "detail": "No shell metacharacters detected."})

        if self._references_secret(command):
            checks.append({"id": "secret_access", "status": "fail", "detail": "Secret-like path or token detected."})
            sandbox = self._sandbox(capability, checks)
            return PolicyDecision(False, "Secret access is denied by guarded.local.", "high", sandbox)

        checks.append({"id": "secret_access", "status": "pass", "detail": "No secret-looking path detected."})

        if root and self._outside_workspace(command, root):
            checks.append({"id": "filesystem_scope", "status": "fail", "detail": "Command references a path outside the workspace."})
            sandbox = self._sandbox(capability, checks)
            return PolicyDecision(False, "Command references a path outside the guarded workspace policy.", "high", sandbox)

        checks.append({"id": "filesystem_scope", "status": "pass", "detail": "No path escapes the guarded workspace policy."})

        for prefix in self.allowed_prefixes:
            if self._matches_prefix(normalized, prefix):
                checks.append({"id": "allowlist", "status": "pass", "detail": f"Matched `{' '.join(prefix)}`."})
                sandbox = self._sandbox(capability, checks)
                return PolicyDecision(True, "Command matches safe check allowlist.", "medium", sandbox)

        for prefix in self.trusted_project_prefixes:
            if self._matches_prefix(normalized, prefix):
                if not self.trust_project_scripts:
                    checks.append(
                        {
                            "id": "project_trust",
                            "status": "fail",
                            "detail": "Project script runners require explicit trusted local mode.",
                        }
                    )
                    sandbox = self._sandbox(capability, checks)
                    return PolicyDecision(False, "Project script execution requires trusted local mode.", "high", sandbox)
                checks.append(
                    {
                        "id": "project_trust",
                        "status": "pass",
                        "detail": "Operator enabled trusted local mode for project scripts.",
                    }
                )
                sandbox = self._sandbox(capability, checks, trusted_project_code=True)
                return PolicyDecision(True, "Trusted project script execution enabled by operator.", "high", sandbox)

        checks.append({"id": "allowlist", "status": "fail", "detail": "Command prefix is not allowlisted."})
        sandbox = self._sandbox(capability, checks)
        return PolicyDecision(False, "Command does not match the safe check allowlist.", "high", sandbox)

    def _sandbox(self, capability: str, checks: list[dict[str, str]], trusted_project_code: bool = False) -> dict[str, Any]:
        profile = TRUSTED_PROJECT_PROFILE if trusted_project_code else SANDBOX_PROFILE
        return {**profile, "capability": capability, "checks": checks}

    def _capability(self, command: Sequence[str]) -> str:
        if not command:
            return "unknown"
        normalized = tuple(part.strip().lower() for part in command)
        if normalized[0] in NETWORK_PROGRAMS:
            return "network"
        if normalized[:3] == ("npm", "run", "build"):
            return "build"
        if normalized[:2] in {("npm", "test"), ("pytest",)} or normalized[:3] == ("npm", "run", "test") or normalized[:3] == ("python", "-m", "pytest"):
            return "test"
        if normalized[:3] in {("npm", "run", "lint"), ("npm", "run", "typecheck")}:
            return "static-analysis"
        if normalized[:3] in {("python", "-m", "compileall"), ("python", "-m", "py_compile")}:
            return "static-analysis"
        return "unknown"

    def _matches_prefix(self, normalized: Sequence[str], prefix: Sequence[str]) -> bool:
        return tuple(normalized[: len(prefix)]) == tuple(prefix)

    def _references_secret(self, command: Sequence[str]) -> bool:
        return any(marker in part.lower() for part in command for marker in SECRET_MARKERS)

    def _outside_workspace(self, command: Sequence[str], workspace_root: Path) -> bool:
        root = workspace_root.resolve()
        for part in command[1:]:
            candidate = Path(part)
            if not candidate.is_absolute():
                continue
            try:
                candidate.resolve().relative_to(root)
            except ValueError:
                return True
        return False


def command_text(command: Sequence[str]) -> str:
    return " ".join(command)


def sandbox_profile(policy: CommandPolicy | None = None) -> dict[str, Any]:
    return (policy or CommandPolicy()).profile()
