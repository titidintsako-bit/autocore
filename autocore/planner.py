from __future__ import annotations

from typing import Any

from .providers import OfflineProvider, PlannerProvider, ProviderResponse
from .safety import CommandPolicy, command_text


class AgentPlanner:
    def __init__(
        self,
        provider: PlannerProvider | None = None,
        policy: CommandPolicy | None = None,
    ) -> None:
        self.provider = provider or OfflineProvider()
        self.policy = policy or CommandPolicy()

    def create_plan(
        self,
        goal: str,
        inspection: dict[str, Any],
        task: dict[str, Any],
        override_command: list[str] | None = None,
    ) -> dict[str, Any]:
        request = {
            "goal": goal,
            "inspection": inspection,
            "task": {
                "id": task["id"],
                "title": task["title"],
                "success_criteria": task["success_criteria"],
            },
        }
        try:
            response = self.provider.propose_plan(request)
            provider_meta = self.provider.metadata()
        except Exception as error:
            response = OfflineProvider().propose_plan(request)
            provider_meta = {**OfflineProvider().metadata(), "fallback_reason": str(error)}

        commands = [list(override_command)] if override_command else []
        commands.extend(response.commands)
        commands.extend(list(command) for command in inspection.get("recommended_commands", []))

        proposals: list[dict[str, Any]] = []
        selected: list[str] | None = None
        blocked_fallback: list[str] | None = None
        seen: set[str] = set()
        for command in commands:
            key = command_text(command)
            if key in seen:
                continue
            seen.add(key)
            decision = self.policy.evaluate(command)
            proposal = {
                "command": command,
                "command_text": key,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "risk": decision.risk,
                "sandbox": decision.sandbox,
            }
            proposals.append(proposal)
            if selected is None and decision.allowed:
                selected = command
            elif blocked_fallback is None:
                blocked_fallback = command

        risks = self._merge_risks(response.risks, inspection)
        return {
            "provider": provider_meta,
            "goal": goal,
            "task_pack_id": task["task_pack_id"],
            "task_id": task["id"],
            "notes": response.notes,
            "risks": risks,
            "proposals": proposals,
            "blocked_proposals": [proposal for proposal in proposals if not proposal["allowed"]],
            "selected_command": selected or blocked_fallback or [],
            "confidence": self._confidence(selected, proposals, risks),
        }

    def _merge_risks(self, provider_risks: list[str], inspection: dict[str, Any]) -> list[str]:
        risks = list(provider_risks)
        surfaces = inspection.get("risk_surfaces", {})
        if surfaces.get("has_env"):
            risks.append("Environment files detected; keep secret access locked.")
        if surfaces.get("has_package_lock"):
            risks.append("Lockfile present; prefer existing dependency graph over installs.")
        if surfaces.get("has_ci"):
            risks.append("CI configuration detected; evidence should mention local vs pipeline coverage.")
        deduped: list[str] = []
        seen: set[str] = set()
        for risk in risks:
            normalized = risk.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                deduped.append(normalized)
        return deduped

    def _confidence(self, selected: list[str] | None, proposals: list[dict[str, Any]], risks: list[str]) -> int:
        if not selected:
            return 15
        base = 78
        base += min(10, len(proposals))
        base -= min(25, len(risks) * 5)
        return max(20, min(95, base))
