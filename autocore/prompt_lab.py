from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping


MODEL_CONTEXT_WINDOWS = {
    "heuristic": 8192,
    "llama-3.3-70b-versatile": 131072,
    "llama3.1": 128000,
    "gpt-4.1-mini": 1000000,
    "gpt-4.1": 1000000,
}

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?token|access[_-]?token|password)\s*=\s*([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})"),
    re.compile(r"\b(ghp_[A-Za-z0-9_]{8,})"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{8,})"),
]

ACTION_WORDS = {
    "audit",
    "build",
    "capture",
    "check",
    "compare",
    "deploy",
    "evaluate",
    "explain",
    "flag",
    "inspect",
    "measure",
    "produce",
    "record",
    "run",
    "scan",
    "test",
    "verify",
}

EVIDENCE_WORDS = {"capture", "evidence", "report", "trace", "output", "score", "record", "proof"}
RISK_WORDS = {"deploy", "delete", "write", "network", "secret", "token", "credential", "browser", "public", "production"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, round(len(stripped) / 4))


def redact_prompt(prompt: str, max_length: int = 32) -> str:
    redacted = prompt.strip()
    for pattern in SECRET_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            if len(match.groups()) == 2:
                return f"{match.group(1)}=[redacted]"
            return "[redacted]"

        redacted = pattern.sub(replace, redacted)
    redacted = " ".join(redacted.split())
    marker = re.search(r"(?i)\b(api[_-]?key|secret[_-]?token|access[_-]?token|password)=\[redacted\]", redacted)
    if marker and len(redacted) > max_length:
        prefix = redacted[:24].rstrip()
        return f"{prefix}... {marker.group(0)}"
    if len(redacted) > max_length:
        return f"{redacted[: max_length - 3].rstrip()}..."
    return redacted


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def model_context_window(model: str) -> int:
    return MODEL_CONTEXT_WINDOWS.get(model, 32000)


def parse_groq_rate_limit_headers(
    headers: Mapping[str, str],
    provider: str = "groq",
    model: str = "unknown",
) -> dict[str, Any]:
    lower = {key.lower(): value for key, value in headers.items()}

    def as_int(name: str) -> int | None:
        value = lower.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    remaining_tokens = as_int("x-ratelimit-remaining-tokens")
    remaining_requests = as_int("x-ratelimit-remaining-requests")
    return {
        "provider": provider,
        "model": model,
        "source": "groq-rate-limit-headers",
        "quota_known": remaining_tokens is not None or remaining_requests is not None,
        "usage_known": False,
        "remaining_tokens": remaining_tokens,
        "remaining_requests": remaining_requests,
        "used_tokens": None,
        "freshness": "response-header" if remaining_tokens is not None or remaining_requests is not None else "unknown",
        "notes": "Groq response headers expose remaining request/token windows when a live provider call has returned them.",
    }


def parse_openai_usage_cost_payload(
    payload: Mapping[str, Any],
    provider: str = "openai",
    model: str = "unknown",
) -> dict[str, Any]:
    used_tokens = 0
    for bucket in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
        for result in bucket.get("results", []) if isinstance(bucket, dict) else []:
            if not isinstance(result, dict):
                continue
            used_tokens += int(result.get("input_tokens") or 0)
            used_tokens += int(result.get("output_tokens") or 0)
    return {
        "provider": provider,
        "model": model,
        "source": "openai-organization-usage",
        "quota_known": False,
        "usage_known": used_tokens > 0,
        "remaining_tokens": None,
        "remaining_requests": None,
        "used_tokens": used_tokens if used_tokens else None,
        "freshness": "usage-api" if used_tokens else "unknown",
        "notes": "OpenAI usage/cost APIs can show usage, but they do not provide a universal per-key tokens-left value.",
    }


def provider_signal(provider: str, model: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    normalized = (provider or "offline").lower()
    if normalized == "groq":
        configured = bool(values.get("GROQ_API_KEY"))
        return {
            "provider": "groq",
            "model": model,
            "source": "configured-env" if configured else "missing-env",
            "quota_known": False,
            "usage_known": False,
            "remaining_tokens": None,
            "remaining_requests": None,
            "used_tokens": None,
            "freshness": "unknown",
            "notes": (
                "Groq quota is unknown until a live response returns rate-limit headers."
                if configured
                else "GROQ_API_KEY is not configured, so no provider quota signal is available."
            ),
        }
    if normalized == "openai":
        configured = bool(values.get("OPENAI_API_KEY"))
        return {
            "provider": "openai",
            "model": model,
            "source": "configured-env" if configured else "missing-env",
            "quota_known": False,
            "usage_known": False,
            "remaining_tokens": None,
            "remaining_requests": None,
            "used_tokens": None,
            "freshness": "unknown",
            "notes": (
                "OpenAI quota is not exposed as a universal tokens-left value; use usage/cost data when configured."
                if configured
                else "OPENAI_API_KEY is not configured, so no provider usage signal is available."
            ),
        }
    return {
        "provider": normalized or "offline",
        "model": model,
        "source": "local-estimate",
        "quota_known": False,
        "usage_known": False,
        "remaining_tokens": None,
        "remaining_requests": None,
        "used_tokens": None,
        "freshness": "local",
        "notes": "Local/offline providers do not expose account quota; AutoCore shows context-fit estimates only.",
    }


def evaluate_prompt(
    prompt: str,
    task: dict[str, Any],
    provider: str = "offline",
    model: str = "heuristic",
    env: Mapping[str, str] | None = None,
    critique_enabled: bool = False,
) -> dict[str, Any]:
    text = prompt.strip()
    words = re.findall(r"[A-Za-z0-9_'-]+", text.lower())
    unique_words = set(words)
    est_input_tokens = estimate_tokens(text)
    context_window = model_context_window(model)
    est_output_tokens = max(350, min(2500, 120 + len(task.get("evidence_requirements", [])) * 180 + len(task.get("success_criteria", [])) * 120))
    total_estimate = est_input_tokens + est_output_tokens
    context_remaining = max(0, context_window - total_estimate)

    clarity = 20
    if len(words) >= 8:
        clarity += 25
    if ACTION_WORDS & unique_words:
        clarity += 25
    if any(token in text for token in (".", ",", ";", ":")):
        clarity += 10
    if len(words) >= 20:
        clarity += 20

    success_criteria = 25
    if {"safe", "allowed", "do", "dont", "don't", "avoid", "must", "should"} & unique_words:
        success_criteria += 30
    if ACTION_WORDS & unique_words:
        success_criteria += 20
    if EVIDENCE_WORDS & unique_words:
        success_criteria += 25

    task_terms = set(re.findall(r"[A-Za-z0-9_'-]+", " ".join(task.get("tool_scope", []) + task.get("evidence_requirements", [])).lower()))
    context_fit = 55 + min(35, len(task_terms & unique_words) * 7)
    if task.get("category", "").lower() in unique_words:
        context_fit += 10

    evidence_plan = 35 + min(50, len(EVIDENCE_WORDS & unique_words) * 14)
    if "evidence" in unique_words:
        evidence_plan += 15

    risk_hits = RISK_WORDS & unique_words
    tool_risk = 88 - min(45, len(risk_hits) * 9)
    if re.search(r"(?i)(delete|remove|credential|password|secret)", text):
        tool_risk -= 20

    budget_fit = 100 if total_estimate < context_window * 0.35 else 78 if total_estimate < context_window * 0.75 else 35

    scores = {
        "clarity": max(0, min(100, clarity)),
        "success_criteria": max(0, min(100, success_criteria)),
        "context_fit": max(0, min(100, context_fit)),
        "evidence_plan": max(0, min(100, evidence_plan)),
        "tool_risk": max(0, min(100, tool_risk)),
        "budget_fit": max(0, min(100, budget_fit)),
    }
    overall = round(
        scores["clarity"] * 0.22
        + scores["success_criteria"] * 0.2
        + scores["context_fit"] * 0.16
        + scores["evidence_plan"] * 0.18
        + scores["tool_risk"] * 0.14
        + scores["budget_fit"] * 0.1
    )

    findings: list[dict[str, str]] = []
    recommendations: list[str] = []
    if len(words) < 8:
        findings.append({"severity": "blocked", "message": "Prompt is too short to be specific enough for a reliable agent run."})
        recommendations.append("Add the target, expected output, success criteria, and evidence requirements.")
    if not ACTION_WORDS & unique_words:
        findings.append({"severity": "warning", "message": "No clear action verb was found."})
        recommendations.append("Start with a concrete action such as audit, verify, compare, or capture.")
    if not EVIDENCE_WORDS & unique_words:
        findings.append({"severity": "warning", "message": "Evidence expectations are not explicit."})
        recommendations.append("Ask for command output, trace, scorecard, or report evidence.")
    if tool_risk < 70:
        findings.append({"severity": "warning", "message": "Prompt mentions higher-risk tools or sensitive surfaces."})
        recommendations.append("State permission boundaries and what must stay read-only.")
    if budget_fit < 70:
        findings.append({"severity": "warning", "message": "Estimated prompt plus response may stress the selected model context."})
        recommendations.append("Narrow the scope or summarize context before running.")

    if not recommendations:
        recommendations.append("Run as a task-pack evaluation and attach the Prompt Lab summary to the evidence bundle.")
    if context_remaining > 5000:
        recommendations.append("Enough context remains for a normal evidence-producing run.")
    elif context_remaining > 1000:
        recommendations.append("Use a concise evidence report or split the run into phases.")

    if not text or len(words) < 3 or scores["clarity"] < 45:
        verdict = "blocked"
    elif overall >= 76 and scores["tool_risk"] >= 55:
        verdict = "ready"
    else:
        verdict = "revise"

    critique = None
    if critique_enabled:
        critique = {
            "enabled": True,
            "source": "local",
            "note": "BYOK model critique is advisory; the local rubric remains the score of record.",
        }

    return {
        "id": f"peval_{uuid.uuid4().hex[:10]}",
        "task_pack_id": task["task_pack_id"],
        "task_id": task["id"],
        "prompt_preview": redact_prompt(text),
        "prompt_hash": prompt_hash(text),
        "verdict": verdict,
        "overall": overall,
        "scores": scores,
        "findings": findings,
        "recommendations": recommendations,
        "token_forecast": {
            "est_input_tokens": est_input_tokens,
            "est_output_tokens": est_output_tokens,
            "est_total_tokens": total_estimate,
            "context_window": context_window,
            "context_remaining": context_remaining,
            "confidence": "estimate",
            "notes": "Token counts are local estimates until a provider response returns actual usage.",
        },
        "provider_signal": provider_signal(provider, model, env=env),
        "model_critique": critique,
        "created_at": utc_now(),
    }


def evaluation_summary(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": evaluation["id"],
        "verdict": evaluation["verdict"],
        "overall": evaluation["overall"],
        "prompt_preview": evaluation["prompt_preview"],
        "token_forecast": evaluation["token_forecast"],
        "provider_signal": evaluation["provider_signal"],
        "recommendations": list(evaluation.get("recommendations", []))[:3],
        "created_at": evaluation["created_at"],
    }
