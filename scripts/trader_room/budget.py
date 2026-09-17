"""Finite Grok/Composer ceilings. Retries may not silently exceed them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    COMPOSER_CEILING,
    COMPOSER_PER_ADVOCATE,
    GROK_BASELINE,
    GROK_CEILING,
    GROK_REBUTTAL_MAX,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.errors import BudgetError
from scripts.trader_room.models import assert_allowed_role_model


@dataclass
class Invocation:
    role: str
    model: str
    agent: str | None
    purpose: str


@dataclass
class BudgetLedger:
    grok: int = 0
    composer: int = 0
    rebuttals: int = 0
    composer_by_agent: dict[str, int] = field(default_factory=dict)
    invocations: list[Invocation] = field(default_factory=list)

    def remaining_grok(self) -> int:
        return GROK_CEILING - self.grok

    def remaining_composer(self) -> int:
        return COMPOSER_CEILING - self.composer

    def charge(self, role: str, model: str, agent: str | None, purpose: str) -> None:
        normalized = assert_allowed_role_model(role, model)
        if normalized == ADVOCATE_MODEL:
            if self.grok + 1 > GROK_CEILING:
                raise BudgetError(
                    f"Grok ceiling {GROK_CEILING} exceeded by {purpose} ({role})"
                )
            if role == "rebuttal":
                if self.rebuttals + 1 > GROK_REBUTTAL_MAX:
                    raise BudgetError(
                        f"rebuttal Grok ceiling {GROK_REBUTTAL_MAX} exceeded by {purpose}"
                    )
                self.rebuttals += 1
            self.grok += 1
        elif normalized == SUBAGENT_MODEL:
            if role != "subagent":
                raise BudgetError(f"composer-2.5 may only be charged as subagent, not {role}")
            if agent not in STANDING_ADVOCATES:
                raise BudgetError(f"composer subagent must belong to an initial advocate, got {agent}")
            used = self.composer_by_agent.get(agent, 0)
            if used + 1 > COMPOSER_PER_ADVOCATE:
                raise BudgetError(
                    f"{agent} already used {used} composer subagents; max {COMPOSER_PER_ADVOCATE}"
                )
            if self.composer + 1 > COMPOSER_CEILING:
                raise BudgetError(f"Composer ceiling {COMPOSER_CEILING} exceeded by {purpose}")
            self.composer_by_agent[agent] = used + 1
            self.composer += 1
        else:
            raise BudgetError(f"unbudgeted model {normalized}")
        self.invocations.append(Invocation(role=role, model=normalized, agent=agent, purpose=purpose))

    def assert_baseline_room(self) -> None:
        if GROK_BASELINE > GROK_CEILING:
            raise BudgetError("baseline Grok invocations exceed ceiling")
        if self.grok > GROK_CEILING or self.composer > COMPOSER_CEILING:
            raise BudgetError("budget already exceeded")

    def snapshot(self) -> dict[str, Any]:
        return {
            "grok": self.grok,
            "composer": self.composer,
            "rebuttals": self.rebuttals,
            "composer_by_agent": dict(self.composer_by_agent),
            "ceilings": {
                "grok_baseline": GROK_BASELINE,
                "grok_rebuttal_max": GROK_REBUTTAL_MAX,
                "grok_ceiling": GROK_CEILING,
                "composer_per_advocate": COMPOSER_PER_ADVOCATE,
                "composer_ceiling": COMPOSER_CEILING,
            },
            "remaining": {"grok": self.remaining_grok(), "composer": self.remaining_composer()},
            "invocations": [
                {"role": i.role, "model": i.model, "agent": i.agent, "purpose": i.purpose}
                for i in self.invocations
            ],
        }
