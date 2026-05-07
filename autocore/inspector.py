from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_package_json(path: Path) -> dict[str, Any]:
    package_path = path / "package.json"
    if not package_path.exists():
        return {}
    try:
        return json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def inspect_project(path: str | Path) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    package = _read_package_json(root)
    scripts = package.get("scripts", {}) if isinstance(package.get("scripts"), dict) else {}
    dependencies = {
        **(package.get("dependencies", {}) if isinstance(package.get("dependencies"), dict) else {}),
        **(package.get("devDependencies", {}) if isinstance(package.get("devDependencies"), dict) else {}),
    }

    manifests: list[str] = []
    for filename in (
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "requirements.txt",
        "vite.config.ts",
        "vite.config.js",
        "tsconfig.json",
        "README.md",
    ):
        if (root / filename).exists():
            manifests.append(filename)

    if "vite" in dependencies or "vite.config.ts" in manifests or "vite.config.js" in manifests:
        stack = "React/Vite" if "react" in dependencies else "Vite"
    elif "package.json" in manifests:
        stack = "Node"
    elif "pyproject.toml" in manifests or "requirements.txt" in manifests:
        stack = "Python"
    else:
        stack = "Unknown"

    commands: list[list[str]] = []
    if "build" in scripts:
        commands.append(["npm", "run", "build"])
    if "test" in scripts:
        commands.append(["npm", "test"])
    if "lint" in scripts:
        commands.append(["npm", "run", "lint"])
    if "typecheck" in scripts:
        commands.append(["npm", "run", "typecheck"])
    if "pyproject.toml" in manifests or "requirements.txt" in manifests:
        commands.append(["python", "-m", "compileall", "."])
        commands.append(["python", "-m", "pytest"])
    if not commands:
        commands.append(["python", "-m", "compileall", "."])

    risk_surfaces = {
        "has_env": any((root / name).exists() for name in (".env", ".env.local", ".env.production")),
        "has_package_lock": (root / "package-lock.json").exists(),
        "has_git": (root / ".git").exists(),
        "has_ci": any((root / name).exists() for name in (".github", "azure-pipelines.yml", ".gitlab-ci.yml")),
    }

    return {
        "path": str(root),
        "stack": stack,
        "manifests": manifests,
        "scripts": scripts,
        "recommended_commands": commands,
        "risk_surfaces": risk_surfaces,
    }
