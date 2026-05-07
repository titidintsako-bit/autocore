from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SCAN_DIRS = ("dist", "public")
SCAN_SUFFIXES = {".css", ".html", ".js", ".json", ".map", ".mjs", ".txt"}
TOKEN_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b")
ENV_FILE_PATTERN = re.compile(r"(?:^|[\\/'\"\s])\.env(?:\.[A-Za-z0-9_-]+)?(?:[\\/'\"\s]|$)")
ENV_NAMES = ("OPENAI_API_KEY", "GROQ_API_KEY", "AUTOCORE_API_TOKEN", "VITE_AUTOCORE_API_TOKEN")


def _public_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
                files.append(path)
    return files


def _scan_file(path: Path, root: Path) -> list[dict[str, object]]:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings: list[dict[str, object]] = []
    relative = path.relative_to(root).as_posix()
    normalized = content.replace("\\\\", "\\")
    if "C:\\Users\\" in normalized or "\\Users\\" in normalized or "/Users/" in content or "/home/" in content:
        findings.append({"file": relative, "kind": "local_path", "detail": "public artifact includes a local filesystem path"})
    if ENV_FILE_PATTERN.search(normalized):
        findings.append({"file": relative, "kind": "env_leak", "detail": "public artifact references an env file"})
    for env_name in ENV_NAMES:
        if env_name in content:
            findings.append({"file": relative, "kind": "env_name", "detail": f"public artifact includes {env_name}"})
    if TOKEN_PATTERN.search(content):
        findings.append({"file": relative, "kind": "secret_token", "detail": "public artifact includes a secret-like token"})
    return findings


def scan(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    findings: list[dict[str, object]] = []
    for path in _public_files(resolved):
        findings.extend(_scan_file(path, resolved))
    return {"ok": not findings, "files_scanned": len(_public_files(resolved)), "findings": findings}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    result = scan(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
