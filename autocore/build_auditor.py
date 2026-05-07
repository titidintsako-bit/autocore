from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inspector import inspect_project
from .containment import docker_containment_status


SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".html", ".css"}
IGNORED_DIRS = {".git", ".autocore", "dist", "node_modules", "__pycache__", ".pytest_cache", "tests", "test", "coverage"}
MOCK_MARKERS = ("mock", "mocked", "fake", "dummy", "stub", "sample data", "placeholder data")
MOCK_IDENTIFIER_PATTERN = re.compile(r"\b(?:const|let|var)?\s*[A-Za-z0-9_]*(?:mock|mocked|fake|dummy|stub|sample)[A-Za-z0-9_]*\s*=", re.IGNORECASE)
MOCK_DOC_PATTERN = re.compile(r"\b(?:mocked?|fake|dummy|stub|sample|placeholder)\s+(?:data|customers?|users?|records?|fixtures?)\b", re.IGNORECASE)
MOCK_GUIDANCE_PHRASES = (
    "risk_markers =",
    "mock_markers =",
    "mock_identifier_pattern",
    "mock_doc_pattern",
    "focus on mocked data",
    "for codex-generated risks, mocked data",
    "mocked-data pattern",
    "no-mocked-data checks",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _iter_product_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in SCAN_EXTENSIONS:
            files.append(path)
    return files


def _find_mocked_data(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in _iter_product_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matched_lines: list[str] = []
        matched_markers: set[str] = set()
        for line_number, line in enumerate(text.splitlines(), start=1):
            lower_line = line.lower()
            if (
                "mock_" in lower_line
                or "no_mocked_data" in line
                or "no mocked data" in lower_line
                or "inspect mocked data" in lower_line
                or "mocked data found" in lower_line
                or "mocked-data" in lower_line
                or "mocked_findings" in line
                or '"mocked": False' in line
                or '"mocked": false' in line
                or any(phrase in lower_line for phrase in MOCK_GUIDANCE_PHRASES)
            ):
                continue
            if MOCK_IDENTIFIER_PATTERN.search(line) or MOCK_DOC_PATTERN.search(line):
                matched_markers.update(marker for marker in MOCK_MARKERS if marker in lower_line)
                matched_lines.append(f"{_relative(path, root)}:{line_number}")
        if matched_lines:
            findings.append(
                {
                    "path": _relative(path, root),
                    "markers": sorted(matched_markers),
                    "evidence": f"{', '.join(matched_lines[:3])} contains mocked-data pattern(s).",
                }
            )
    return findings


def _status(score: int) -> str:
    if score >= 80:
        return "pass"
    if score >= 55:
        return "warn"
    return "fail"


def _check(check_id: str, label: str, score: int, evidence: str) -> dict[str, Any]:
    return {"id": check_id, "label": label, "status": _status(score), "score": score, "evidence": evidence}


def _scan_text_pattern(root: Path, pattern: str, ignored_paths: set[str] | None = None) -> list[str]:
    matches: list[str] = []
    ignored = ignored_paths or set()
    for path in _iter_product_files(root):
        relative = _relative(path, root)
        if relative in ignored:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.lower() in line.lower():
                matches.append(f"{relative}:{line_number}")
    return matches


def _docker_context_check(root: Path) -> dict[str, Any]:
    dockerfile = root / "Dockerfile"
    dockerignore = root / ".dockerignore"
    if not dockerfile.exists():
        return _check("docker_context", "Docker Context", 55, "No Dockerfile found; container build context was not assessed.")
    try:
        text = dockerfile.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return _check("docker_context", "Docker Context", 45, "Dockerfile could not be read.")
    broad_copy = "copy . ." in text or "add . ." in text
    if broad_copy and not dockerignore.exists():
        return _check("docker_context", "Docker Context", 0, "Dockerfile uses broad workspace copy without .dockerignore.")
    if broad_copy:
        return _check("docker_context", "Docker Context", 70, "Dockerfile uses broad workspace copy, but .dockerignore is present.")
    return _check("docker_context", "Docker Context", 90, "Dockerfile copies explicit files or stages instead of the whole workspace.")


def _security_scan(root: Path, risk_surfaces: dict[str, Any]) -> dict[str, Any]:
    client_token_matches = _scan_text_pattern(root, "VITE_AUTOCORE_API_TOKEN", {"autocore/build_auditor.py"}) if root.exists() else []
    checks = [
        _check(
            "secrets",
            "Secret Hygiene",
            90
            if (root / ".gitignore").exists() and (root / ".env.example").exists() and not risk_surfaces.get("has_env", False)
            else 35
            if risk_surfaces.get("has_env", False)
            else 60,
            "Ignored env patterns and example env file are present without local .env in scope."
            if (root / ".gitignore").exists() and (root / ".env.example").exists() and not risk_surfaces.get("has_env", False)
            else "Secret hygiene evidence is partial; local env handling needs review.",
        ),
        _check(
            "client_token_boundary",
            "Client Token Boundary",
            0 if client_token_matches else 90,
            f"Client code references VITE_AUTOCORE_API_TOKEN at {', '.join(client_token_matches[:5])}."
            if client_token_matches
            else "No browser-visible AutoCore API token reference found in product files.",
        ),
        _docker_context_check(root),
    ]
    overall = round(sum(check["score"] for check in checks) / len(checks))
    return {
        "source": "local_static_security_scan",
        "status": "pass" if overall >= 80 else "warn" if overall >= 55 else "fail",
        "overall": overall,
        "checks": checks,
        "scope": "Static local scan for token exposure, env hygiene, and Docker build context. This is not a penetration test.",
    }


def _containment_status() -> dict[str, Any]:
    return docker_containment_status()


def _claim_readiness(
    no_mocked_data: bool,
    quality_evidence: list[str],
    security_scan: dict[str, Any],
    has_deploy_files: bool,
    containment: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "claim": "No mocked data",
            "status": "supported" if no_mocked_data else "blocked",
            "evidence": "No mocked-data patterns found." if no_mocked_data else "Mocked-data patterns were found in product files.",
        },
        {
            "claim": "Code quality evidence",
            "status": "supported" if len(quality_evidence) >= 2 else "limited",
            "evidence": "; ".join(quality_evidence) if quality_evidence else "Build/test/dependency evidence is incomplete.",
        },
        {
            "claim": "Security evidence",
            "status": "supported" if security_scan["status"] == "pass" else "limited",
            "evidence": f"Static security scan status: {security_scan['status']} / {security_scan['overall']}.",
        },
        {
            "claim": "Deep security",
            "status": "blocked",
            "evidence": "Deep security needs dedicated tooling, manual review, or contained dynamic execution evidence.",
        },
        {
            "claim": "Deployment readiness",
            "status": "supported" if has_deploy_files else "limited",
            "evidence": "Deployment-facing files are present." if has_deploy_files else "Deployment path evidence is incomplete.",
        },
        {
            "claim": "Contained execution",
            "status": "blocked",
            "evidence": f"{containment['notes']} This claim becomes supported only after a run records contained execution evidence.",
        },
    ]


def audit_project(path: str | Path) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    inspection = inspect_project(root)
    manifests = set(inspection.get("manifests", []))
    scripts = inspection.get("scripts", {})
    risk_surfaces = inspection.get("risk_surfaces", {})
    mocked_findings = _find_mocked_data(root) if root.exists() else []

    has_build = "build" in scripts or any(command[:3] == ["npm", "run", "build"] for command in inspection.get("recommended_commands", []))
    has_tests = bool({"test", "test:backend", "typecheck", "lint"} & set(scripts)) or (root / "tests").exists()
    lockfiles = sorted({"package-lock.json", "pnpm-lock.yaml", "yarn.lock"} & manifests)
    has_lockfile = bool(lockfiles)
    has_secret_hygiene = (root / ".gitignore").exists() and (root / ".env.example").exists() and not risk_surfaces.get("has_env", False)
    has_deploy_files = bool({"Dockerfile", "docker-compose.yml", "DEPLOYMENT.md"} & {item.name for item in root.iterdir()}) if root.exists() else False
    security_scan = _security_scan(root, risk_surfaces)
    containment = _containment_status()

    checks = [
        _check(
            "mocked_data",
            "No Mocked Data",
            100 if not mocked_findings else 0,
            "No product files contain mocked-data markers."
            if not mocked_findings
            else "; ".join(item["evidence"] for item in mocked_findings[:5]),
        ),
        _check(
            "build_path",
            "Build Path",
            90 if has_build else 45,
            "Build script or recommended build command is present." if has_build else "No build command evidence found.",
        ),
        _check(
            "test_path",
            "Test Path",
            85 if has_tests else 45,
            "Test, lint, typecheck script, or tests directory is present." if has_tests else "No test or static check evidence found.",
        ),
        _check(
            "dependency_lock",
            "Dependency Lock",
            85 if has_lockfile or inspection["stack"] == "Python" else 55,
            ", ".join(lockfiles)
            if has_lockfile
            else "Python-only project evidence exists."
            if inspection["stack"] == "Python"
            else "No package lockfile found.",
        ),
        _check(
            "secret_hygiene",
            "Secret Hygiene",
            90 if has_secret_hygiene else 60 if not risk_surfaces.get("has_env", False) else 35,
            "Ignored env patterns and example env file are present without local .env in scope."
            if has_secret_hygiene
            else "Secret hygiene evidence is partial; avoid claiming security depth until reviewed.",
        ),
        _check(
            "deployment_path",
            "Deployment Path",
            80 if has_deploy_files else 50,
            "Deployment-facing file is present." if has_deploy_files else "No deployment-facing file found.",
        ),
    ]

    overall = round(sum(check["score"] for check in checks) / len(checks))
    if mocked_findings:
        verdict = "not_ready"
    elif overall >= 78:
        verdict = "ready"
    elif overall >= 58:
        verdict = "watch"
    else:
        verdict = "not_ready"

    quality_evidence = [check["evidence"] for check in checks if check["id"] in {"build_path", "test_path", "dependency_lock"} and check["status"] == "pass"]
    security_evidence = [check["label"] for check in security_scan["checks"] if check["status"] == "pass"]
    claims = {
        "quality": {
            "status": "evidence_backed" if len(quality_evidence) >= 2 else "limited",
            "claim": "Code quality has local evidence from build/test/dependency signals."
            if len(quality_evidence) >= 2
            else "Code quality is not proven deeply yet; only partial local evidence exists.",
            "evidence": quality_evidence or ["No passing quality evidence collected yet."],
        },
        "security": {
            "status": "evidence_backed" if security_scan["status"] == "pass" else "limited",
            "claim": "Security claim is limited to stored static scan evidence and guarded execution controls."
            if security_scan["status"] == "pass"
            else "Security is not deeply proven yet; address static scan findings before making that claim.",
            "evidence": security_evidence or ["No passing security evidence collected yet."],
        },
    }
    claim_readiness = _claim_readiness(not mocked_findings, quality_evidence, security_scan, has_deploy_files, containment)

    recommendations = []
    if mocked_findings:
        recommendations.append("Replace product mocked-data markers with real connector/runtime data or clearly isolate them outside production surfaces.")
    if not has_tests:
        recommendations.append("Add a runnable test, lint, or typecheck path before claiming code quality.")
    if security_scan["status"] != "pass":
        recommendations.append("Fix static security scan warnings before claiming security readiness.")
    if not has_deploy_files:
        recommendations.append("Add deployment documentation or a container/release path before claiming deployability.")
    if not recommendations:
        recommendations.append("Run a live AutoCore verification command and attach evidence before public release.")

    return {
        "id": f"audit_{uuid.uuid4().hex[:10]}",
        "project": {
            "name": root.name,
            "path": str(root),
            "stack": inspection["stack"],
            "manifests": inspection["manifests"],
        },
        "verdict": verdict,
        "overall": overall,
        "no_mocked_data": not mocked_findings,
        "mocked_findings": mocked_findings,
        "checks": checks,
        "claims": claims,
        "claim_readiness": claim_readiness,
        "security_scan": security_scan,
        "containment": containment,
        "recommendations": recommendations,
        "source": "local_static_scan",
        "created_at": _utc_now(),
    }
