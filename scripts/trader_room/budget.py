"""Finite Grok/Composer ceilings. Retries may not silently exceed them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.trader_room import agent_config
from scripts.trader_room.errors import BudgetError, ModelPolicyError


@dataclass
class Invocation:
    role: str
    model: str
    agent: str | None
    purpose: str


_ROLE_TO_PIN: dict[str, str] = {
    "advocate": "advocate",
    "rebuttal": "rebuttal",
    "conflict-aggregator": "advocate",
    "final-aggregator": "advocate",
    "subagent": "advocate_subagent",
}


@dataclass
class BudgetLedger:
    grok: int = 0
    composer: int = 0
    rebuttals: int = 0
    composer_by_agent: dict[str, int] = field(default_factory=dict)
    invocations: list[Invocation] = field(default_factory=list)
    pin: dict[str, Any] | None = field(default=None, repr=False)

    def _resolved_pin(self) -> dict[str, Any]:
        if self.pin is None:
            self.pin = agent_config.assert_acceptable_pin(agent_config.build_pin("ondemand"))
        return self.pin

    def _budget(self) -> dict[str, Any]:
        return self._resolved_pin()["budget"]

    @property
    def _grok_ceiling(self) -> int:
        return int(self._budget()["grok_family_calls"])

    @property
    def _composer_ceiling(self) -> int:
        return int(self._budget()["composer_calls"])

    @property
    def _grok_baseline(self) -> int:
        return len(agent_config.pin_trader_ids(self._resolved_pin()))

    @property
    def _grok_rebuttal_max(self) -> int:
        return len(agent_config.pin_trader_ids(self._resolved_pin()))

    @property
    def _composer_per_advocate(self) -> int:
        nodes = self._budget().get("nodes") or {}
        return int(nodes.get("composer_per_advocate", 2))

    def remaining_grok(self) -> int:
        return self._grok_ceiling - self.grok

    def remaining_composer(self) -> int:
        return self._composer_ceiling - self.composer

    def charge(self, role: str, model: str, agent: str | None, purpose: str) -> None:
        pin = self._resolved_pin()
        mapped = _ROLE_TO_PIN.get(role)
        if mapped is None:
            raise BudgetError(f"unbudgeted role {role!r}")
        seat: str | None = agent if mapped in {"advocate", "rebuttal"} else None
        if mapped == "advocate_subagent":
            seat = None
        elif mapped == "advocate" and role in {"conflict-aggregator", "final-aggregator"}:
            seat = None
        try:
            if role in {"conflict-aggregator", "final-aggregator"}:
                expected = agent_config.normalize_model(str(pin["roles"]["advocate"]))
                normalized = agent_config.normalize_model(model)
                if normalized != expected:
                    raise ModelPolicyError(
                        f"role {role!r} expected {expected!r}, got {normalized!r}"
                    )
            else:
                normalized = agent_config.assert_role_model(pin, mapped, model, seat=seat)
        except ModelPolicyError as exc:
            raise BudgetError(str(exc)) from exc

        grok_ceiling = self._grok_ceiling
        composer_ceiling = self._composer_ceiling
        grok_rebuttal_max = self._grok_rebuttal_max
        composer_per = self._composer_per_advocate
        trader_ids = set(agent_config.pin_trader_ids(pin))

        family = agent_config.pin_model_family(pin, normalized)
        if family == "grok":
            if self.grok + 1 > grok_ceiling:
                raise BudgetError(
                    f"Grok ceiling {grok_ceiling} exceeded by {purpose} ({role})"
                )
            if role == "rebuttal":
                if self.rebuttals + 1 > grok_rebuttal_max:
                    raise BudgetError(
                        f"rebuttal Grok ceiling {grok_rebuttal_max} exceeded by {purpose}"
                    )
                self.rebuttals += 1
            self.grok += 1
        elif family == "composer":
            if role != "subagent":
                raise BudgetError(f"composer-2.5 may only be charged as subagent, not {role}")
            if agent not in trader_ids:
                raise BudgetError(f"composer subagent must belong to an initial advocate, got {agent}")
            used = self.composer_by_agent.get(agent or "", 0)
            if used + 1 > composer_per:
                raise BudgetError(
                    f"{agent} already used {used} composer subagents; max {composer_per}"
                )
            if self.composer + 1 > composer_ceiling:
                raise BudgetError(f"Composer ceiling {composer_ceiling} exceeded by {purpose}")
            self.composer_by_agent[agent or ""] = used + 1
            self.composer += 1
        else:
            raise BudgetError(f"unbudgeted model {normalized}")
        self.invocations.append(Invocation(role=role, model=normalized, agent=agent, purpose=purpose))

    def assert_baseline_room(self) -> None:
        grok_baseline = self._grok_baseline
        if grok_baseline > self._grok_ceiling:
            raise BudgetError("baseline Grok invocations exceed ceiling")
        if self.grok > self._grok_ceiling or self.composer > self._composer_ceiling:
            raise BudgetError("budget already exceeded")

    def snapshot(self) -> dict[str, Any]:
        pin = self._resolved_pin()
        return {
            "grok": self.grok,
            "composer": self.composer,
            "rebuttals": self.rebuttals,
            "composer_by_agent": dict(self.composer_by_agent),
            "ceilings": {
                "grok_baseline": self._grok_baseline,
                "grok_rebuttal_max": self._grok_rebuttal_max,
                "grok_ceiling": self._grok_ceiling,
                "composer_per_advocate": self._composer_per_advocate,
                "composer_ceiling": self._composer_ceiling,
            },
            "remaining": {"grok": self.remaining_grok(), "composer": self.remaining_composer()},
            "invocations": [
                {"role": i.role, "model": i.model, "agent": i.agent, "purpose": i.purpose}
                for i in self.invocations
            ],
            "agent_roster_pin_sha256": pin.get("pin_sha256"),
        }
