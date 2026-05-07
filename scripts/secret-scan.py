from __future__ import annotations

import json
import re
import sys
from pathlib import Path


EXCLUDED_DIRS = {
    ".autocore",
    ".git",
    ".pytest_cache",
    ".vercel",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "qa",
    "tests",
}

SCANNED_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

TOKEN_PATTERNS = (
    ("openai_token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)

ASSIGNMENT_PATTERN = re.compile(
    r"\b(?P<name>[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)[A-Z0-9_]*)\b"
    r"\s*[:=]\s*"
    r"(?P<quote>['\"]?)(?P<value>[^'\"\s,#]+)",
)

PLACEHOLDER_VALUES = {
    "",
    "...",
    "<redacted>",
    "[redacted]",
    "redacted",
    "replace-me",
    "replace_with_value",
    "replace-with-value",
    "replace-with-a-long-random-token",
    "your-api-key",
    "your-key",
    "your-local-key",
    "your-token",
}


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    if normalized in PLACEHOLDER_VALUES:
        return True
    return any(marker in normalized for marker in ("example", "placeholder", "replace-with", "your-"))


def _is_secret_name(name: str) -> bool:
    if name != name.upper():
        return False
    if name.endswith(("PATTERN", "PATTERNS", "MARKER", "MARKERS", "MATCH", "MATCHES")):
        return False
    return any(marker in name for marker in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY"))


def _looks_sensitive_value(value: str) -> bool:
    normalized = value.strip().strip("'\"")
    if not normalized or normalized[0] in "([{":
        return False
    if normalized.lower().startswith(("os.environ", "process.env", "import.meta.env", "env.get", "getenv")):
        return False
    return len(normalized) >= 12 and any(char.isalpha() for char in normalized) and any(char.isdigit() for char in normalized)


def _should_scan(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part in EXCLUDED_DIRS for part in relative_parts[:-1]):
        return False
    if path.name in {"secret-scan.py"}:
        return False
    if path.name.startswith(".env"):
        return True
    return path.suffix.lower() in SCANNED_SUFFIXES


def _scan_file(path: Path, root: Path) -> list[dict[str, object]]:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings: list[dict[str, object]] = []
    relative = path.relative_to(root).as_posix()
    lines = content.splitlines()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for kind, pattern in TOKEN_PATTERNS:
            for match in pattern.finditer(line):
                if not _is_placeholder(match.group(0)):
                    findings.append({"file": relative, "line": line_number, "kind": kind, "detail": "secret-like token"})
        for match in ASSIGNMENT_PATTERN.finditer(line):
            name = match.group("name")
            value = match.group("value")
            if value and _is_secret_name(name) and _looks_sensitive_value(value) and not _is_placeholder(value):
                findings.append(
                    {
                        "file": relative,
                        "line": line_number,
                        "kind": "secret_assignment",
                        "detail": f"{name} has a non-placeholder value",
                    }
                )
    return findings


def scan(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    findings: list[dict[str, object]] = []
    for path in resolved.rglob("*"):
        if path.is_file() and _should_scan(path, resolved):
            findings.extend(_scan_file(path, resolved))
    return {"ok": not findings, "findings": findings}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    result = scan(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
