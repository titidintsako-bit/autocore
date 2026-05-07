from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ProviderResponse:
    commands: list[list[str]]
    risks: list[str]
    notes: str


class PlannerProvider(Protocol):
    def metadata(self) -> dict[str, str]:
        ...

    def propose_plan(self, request: dict[str, Any]) -> ProviderResponse:
        ...


class OfflineProvider:
    def metadata(self) -> dict[str, str]:
        return {"name": "offline", "model": "heuristic", "mode": "local"}

    def propose_plan(self, request: dict[str, Any]) -> ProviderResponse:
        inspection = request["inspection"]
        commands = [list(command) for command in inspection.get("recommended_commands", [])]
        risks: list[str] = []
        risk_surfaces = inspection.get("risk_surfaces", {})
        if risk_surfaces.get("has_env"):
            risks.append("Environment files are present; secret access must stay locked.")
        if risk_surfaces.get("has_ci"):
            risks.append("CI configuration exists; compare local checks with pipeline expectations.")
        if not commands:
            risks.append("No safe verification command was detected.")
        return ProviderResponse(
            commands=commands,
            risks=risks,
            notes="Offline heuristic selected the safest detected project check.",
        )


class OpenAICompatibleProvider:
    def __init__(self, name: str, base_url: str, api_key: str, model: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def metadata(self) -> dict[str, str]:
        return {"name": self.name, "model": self.model, "mode": "byok"}

    def propose_plan(self, request: dict[str, Any]) -> ProviderResponse:
        prompt = (
            "Return JSON only with keys commands, risks, notes. "
            "Commands must be arrays of argv strings and should be safe verification checks only.\n\n"
            + json.dumps(request, indent=2)
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You plan safe local agent verification runs for AutoCore."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"{self.name} planner request failed: {error}") from error

        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{self.name} planner returned non-JSON content") from error
        return ProviderResponse(
            commands=[list(command) for command in parsed.get("commands", []) if isinstance(command, list)],
            risks=[str(risk) for risk in parsed.get("risks", [])],
            notes=str(parsed.get("notes", "")),
        )


class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def metadata(self) -> dict[str, str]:
        return {"name": "ollama", "model": self.model, "mode": "local"}

    def propose_plan(self, request: dict[str, Any]) -> ProviderResponse:
        prompt = (
            "Return JSON only with keys commands, risks, notes. "
            "Commands must be argv arrays for safe local verification checks.\n\n"
            + json.dumps(request, indent=2)
        )
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"ollama planner request failed: {error}") from error
        content = body.get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        return ProviderResponse(
            commands=[list(command) for command in parsed.get("commands", []) if isinstance(command, list)],
            risks=[str(risk) for risk in parsed.get("risks", [])],
            notes=str(parsed.get("notes", "")),
        )


def select_provider(env: Mapping[str, str] | None = None) -> PlannerProvider:
    values = env or os.environ
    provider = values.get("AUTOCORE_PROVIDER", "offline").lower()

    if provider == "groq" and values.get("GROQ_API_KEY"):
        return OpenAICompatibleProvider(
            "groq",
            values.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            values["GROQ_API_KEY"],
            values.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )
    if provider == "openai" and values.get("OPENAI_API_KEY"):
        return OpenAICompatibleProvider(
            "openai",
            values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            values["OPENAI_API_KEY"],
            values.get("OPENAI_MODEL", "gpt-4.1-mini"),
        )
    if provider == "ollama":
        return OllamaProvider(values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), values.get("OLLAMA_MODEL", "llama3.1"))
    return OfflineProvider()
