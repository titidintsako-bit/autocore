from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .inspector import inspect_project


ConnectorState = str


PERMISSION_MODEL = [
    {
        "label": "Read-only",
        "detail": "AutoCore can inspect approved source data, but it cannot write comments, commits, files, or tickets.",
        "status": "allow",
    },
    {
        "label": "Metadata-only",
        "detail": "Default setup indexes names, status, owners, timestamps, and references before any content-level read.",
        "status": "guarded",
    },
    {
        "label": "Evidence export",
        "detail": "Runs can attach markdown/json evidence packages with source references and redaction notes.",
        "status": "allow",
    },
    {
        "label": "No mutation",
        "detail": "State-changing actions stay blocked unless a future policy profile explicitly promotes them.",
        "status": "deny",
    },
]


STATE_LEGEND = [
    {
        "state": "not_connected",
        "label": "Not connected",
        "detail": "Credentials or local access are missing. AutoCore cannot read from this source yet.",
    },
    {
        "state": "demo_connected",
        "label": "Demo connected",
        "detail": "A seeded public demo source is mounted. No external account is touched.",
    },
    {
        "state": "live_connected",
        "label": "Live connected",
        "detail": "A real local source is reachable through the guarded runtime policy.",
    },
    {
        "state": "failed_auth",
        "label": "Failed auth",
        "detail": "Auth is present but invalid, expired, or outside the approved workspace.",
    },
    {
        "state": "syncing",
        "label": "Syncing",
        "detail": "A read-only sync is indexing metadata and evidence references.",
    },
    {
        "state": "paused",
        "label": "Paused",
        "detail": "Credentials are present, but live validation is not enabled for this connector.",
    },
]


ONBOARDING_STEPS = [
    {
        "title": "Choose source",
        "detail": "Select the system of record AutoCore should audit first.",
    },
    {
        "title": "Verify permissions",
        "detail": "Review scopes, redactions, and mutation blocks before connecting.",
    },
    {
        "title": "Run audit",
        "detail": "Start a guarded task pack using read-only source context.",
    },
    {
        "title": "Review evidence",
        "detail": "Open the evidence bundle, transcript, replay, and scorecard.",
    },
]


EXTERNAL_CONNECTORS = [
    {
        "id": "github",
        "name": "GitHub",
        "category": "Code host",
        "description": "Repository metadata, pull requests, issues, workflow status, and release evidence.",
        "scopes": ["repo:read", "actions:read", "issues:read", "pull_requests:read"],
        "required_env": ["GITHUB_TOKEN", "GH_TOKEN"],
        "risk": "low",
        "evidence_detail": "Links runs to commits, checks, PRs, issue state, and release notes.",
    },
    {
        "id": "slack",
        "name": "Slack",
        "category": "Team signal",
        "description": "Channel summaries, approval handoffs, incident context, and deployment notes.",
        "scopes": ["channels:history", "channels:read", "users:read"],
        "required_env": ["SLACK_BOT_TOKEN", "SLACK_USER_TOKEN"],
        "risk": "medium",
        "evidence_detail": "Captures cited decision context without posting messages or changing channels.",
    },
    {
        "id": "linear-jira",
        "name": "Linear/Jira",
        "category": "Work tracker",
        "description": "Ticket state, ownership, labels, milestone risk, and acceptance criteria.",
        "scopes": ["issues:read", "projects:read", "comments:read"],
        "required_env": ["LINEAR_API_KEY", "JIRA_API_TOKEN", "JIRA_BASE_URL"],
        "risk": "medium",
        "evidence_detail": "Binds task packs to issue requirements and completion proof.",
    },
    {
        "id": "google-drive",
        "name": "Google Drive",
        "category": "Docs",
        "description": "Design docs, specs, runbooks, and public-safe evidence attachments.",
        "scopes": ["drive.metadata.readonly", "documents.readonly"],
        "required_env": ["GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "risk": "medium",
        "evidence_detail": "References source docs while redacting secrets and private paths.",
    },
    {
        "id": "cloud-logs",
        "name": "Cloud Logs",
        "category": "Runtime",
        "description": "Build logs, deploy logs, observability events, and incident traces.",
        "scopes": ["logs:read", "deployments:read", "metrics:read"],
        "required_env": [
            "AWS_ACCESS_KEY_ID",
            "AWS_PROFILE",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "AZURE_CLIENT_ID",
            "VERCEL_TOKEN",
        ],
        "risk": "high",
        "evidence_detail": "Correlates automation decisions with deployment health and runtime output.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env_file(project_root: str | Path) -> dict[str, str]:
    env_path = Path(project_root) / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def connector_env(project_root: str | Path, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env.update(load_env_file(project_root))
    return env


def _configured_env(required: list[str], env: Mapping[str, str]) -> list[str]:
    return [name for name in required if env.get(name)]


def _external_connector(definition: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    configured = _configured_env(definition["required_env"], env)
    state: ConnectorState = "paused" if configured else "not_connected"
    source = "environment" if configured else "missing_env"
    return {
        "id": definition["id"],
        "name": definition["name"],
        "category": definition["category"],
        "state": state,
        "source": source,
        "description": definition["description"],
        "scopes": definition["scopes"],
        "required_env": definition["required_env"],
        "configured_env": configured,
        "permissions": [item["label"] for item in PERMISSION_MODEL],
        "risk": definition["risk"],
        "evidence": {
            "detail": definition["evidence_detail"],
            "validated": False,
            "redacted": True,
        },
    }


def _local_repo_connector(project_root: str | Path) -> dict[str, Any]:
    inspection = inspect_project(project_root)
    return {
        "id": "local-repo",
        "name": "Local Repo",
        "category": "Workspace",
        "state": "live_connected",
        "source": "workspace",
        "description": "Local manifests, scripts, tests, generated reports, and run history.",
        "scopes": ["workspace:read", "manifest:read", "commands:allowlisted"],
        "required_env": [],
        "configured_env": [],
        "permissions": [item["label"] for item in PERMISSION_MODEL],
        "risk": "low",
        "evidence": {
            "detail": "Feeds the current command policy, task packs, run replay, and evidence bundle.",
            "stack": inspection["stack"],
            "manifests": inspection["manifests"],
            "scripts": sorted(inspection["scripts"].keys()),
            "recommended_commands": [" ".join(command) for command in inspection["recommended_commands"]],
            "risk_surfaces": inspection["risk_surfaces"],
            "workspace_name": Path(project_root).resolve().name,
        },
    }


def _summary(connectors: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(connectors),
        "active": sum(1 for item in connectors if item["state"] in {"demo_connected", "live_connected"}),
        "guarded": sum(1 for item in connectors if item["state"] in {"paused", "syncing"}),
        "attention": sum(1 for item in connectors if item["state"] == "failed_auth"),
        "not_connected": sum(1 for item in connectors if item["state"] == "not_connected"),
    }


def build_connector_inventory(project_root: str | Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    connector_environment = connector_env(root, env)
    connectors = [_external_connector(definition, connector_environment) for definition in EXTERNAL_CONNECTORS]
    connectors.append(_local_repo_connector(root))
    return {
        "mode": "live",
        "mocked": False,
        "generated_at": utc_now(),
        "project": {
            "name": root.name,
            "stack": connectors[-1]["evidence"]["stack"],
        },
        "summary": _summary(connectors),
        "permissions": PERMISSION_MODEL,
        "state_legend": STATE_LEGEND,
        "onboarding": ONBOARDING_STEPS,
        "boundary": {
            "label": "Live local connector inventory",
            "detail": "Connector cards are backed by local workspace inspection and environment/config presence. Token values are never returned.",
        },
        "connectors": connectors,
    }
