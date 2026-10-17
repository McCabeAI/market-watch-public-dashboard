"""Deterministic news transmission scoring (stdlib only)."""

from __future__ import annotations

import copy
import re
from typing import Any

CHANNEL_WEIGHTS = {
    "usd_rates": 5,
    "g10_policy": 5,
    "oil_energy_tot": 5,
    "china_spillover": 5,
    "credit_funding": 5,
    "global_risk": 4,
    "geopolitics_haven": 4,
}

PRIMARY_CHANNEL_ORDER = (
    "oil_energy_tot",
    "g10_policy",
    "usd_rates",
    "credit_funding",
    "china_spillover",
    "geopolitics_haven",
    "global_risk",
)

COMPONENT_CHANNEL_KEYS = {
    "usd_rates": "channel_usd_rates",
    "g10_policy": "channel_g10_policy",
    "oil_energy_tot": "channel_oil_energy",
    "china_spillover": "channel_china_spillover",
    "credit_funding": "channel_credit_funding",
    "global_risk": "channel_global_risk",
    "geopolitics_haven": "channel_geopolitics",
}


def _blob(headline: str, summary: str) -> str:
    return f"{headline or ''} {summary or ''}".lower()


def _phrase(text: str, needle: str) -> bool:
    return needle.lower() in text


def _word(text: str, tok: str) -> bool:
    if " " in tok:
        return tok.lower() in text
    return re.search(rf"\b{re.escape(tok)}\b", text, flags=re.IGNORECASE) is not None


def _any_word(text: str, tokens: tuple[str, ...]) -> bool:
    return any(_word(text, t) for t in tokens)


def _any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_phrase(text, p) for p in phrases)


def _empty_components() -> dict[str, int]:
    return {
        "channel_usd_rates": 0,
        "channel_g10_policy": 0,
        "channel_oil_energy": 0,
        "channel_china_spillover": 0,
        "channel_credit_funding": 0,
        "channel_global_risk": 0,
        "channel_geopolitics": 0,
        "asset_named": 0,
        "shock": 0,
        "subject_penalty": 0,
    }


def _set_channel(comps: dict[str, int], channel_id: str) -> None:
    key = COMPONENT_CHANNEL_KEYS[channel_id]
    comps[key] = CHANNEL_WEIGHTS[channel_id]


def _primary_channel(fired: list[str]) -> str | None:
    if not fired:
        return None
    for cid in PRIMARY_CHANNEL_ORDER:
        if cid in fired:
            return cid
    return fired[0]


def _transmission_from_parts(
    *,
    disposition: str,
    affected_assets: list[str],
    channel: str | None,
    channels: list[str],
    reason_code: str,
    score: int,
    components: dict[str, int],
) -> dict[str, Any]:
    return {
        "disposition": disposition,
        "affected_assets": list(affected_assets),
        "channel": channel,
        "channels": list(channels),
        "reason_code": reason_code,
        "score": score,
        "components": dict(components),
    }


def _subject_rule(text: str) -> dict[str, Any] | None:
    comps = _empty_components()
    if _word(text, "vietnam") and _word(text, "gdp"):
        comps["subject_penalty"] = -8
        return _transmission_from_parts(
            disposition="suppress",
            affected_assets=[],
            channel=None,
            channels=[],
            reason_code="local_non_g10_macro",
            score=-8,
            components=comps,
        )
    if _word(text, "india") and _any_phrase(
        text, ("trade deficit", "trade gap", "import bill")
    ):
        comps["subject_penalty"] = -8
        return _transmission_from_parts(
            disposition="suppress",
            affected_assets=[],
            channel=None,
            channels=[],
            reason_code="incidental_link_only",
            score=-8,
            components=comps,
        )
    if _word(text, "indonesia") and (
        _any_word(text, ("fire", "fires", "forest")) or "forest fire" in text
    ):
        comps["subject_penalty"] = -8
        return _transmission_from_parts(
            disposition="suppress",
            affected_assets=[],
            channel=None,
            channels=[],
            reason_code="local_non_g10_macro",
            score=-8,
            components=comps,
        )
    noise_hit = _any_word(text, ("podcast", "golf", "celebrity"))
    supply_escape = _any_word(text, ("hormuz", "opec", "brent", "wti", "crude"))
    if noise_hit and not supply_escape:
        comps["subject_penalty"] = -10
        return _transmission_from_parts(
            disposition="suppress",
            affected_assets=[],
            channel=None,
            channels=[],
            reason_code="noise_non_market",
            score=-10,
            components=comps,
        )
    return None


def _hormuz_mentioned(text: str) -> bool:
    return (
        _phrase(text, "strait of hormuz")
        or _word(text, "hormuz")
        or _word(text, "ormuz")
        or _phrase(text, "estreito de ormuz")
    )


def _hormuz_acute(text: str) -> bool:
    return _any_phrase(
        text,
        (
            "won't soften",
            "wont soften",
            "rejected",
            "demands",
            "bounced",
            "crude bounced",
        ),
    )


def _hormuz_diplomatic(text: str) -> bool:
    return _any_word(text, ("reopening", "diplomatic", "easing"))


def _chicago_fed_activity(text: str) -> bool:
    return (
        _phrase(text, "chicago fed")
        or _word(text, "cfnai")
        or _phrase(text, "national activity index")
    )


def _coreweave_rule(text: str) -> bool:
    if _word(text, "coreweave"):
        return True
    cds_hit = _word(text, "cds") or _phrase(text, "credit default")
    context = _any_word(text, ("ai", "debt", "distress", "coreweave"))
    return cds_hit and context


def _china_spillover_match(text: str) -> bool:
    if not _word(text, "china"):
        return False
    clause_a = _any_word(
        text, ("stimulus", "property", "crude", "commodity", "demand", "pboc")
    )
    clause_b = _any_word(
        text, ("stimulus", "crude", "commodity", "iron", "oil", "copper", "aud")
    )
    return clause_a and clause_b


def _china_ambiguous(text: str) -> bool:
    return _word(text, "china") and not _china_spillover_match(text)


def _g10_trigger(text: str) -> bool:
    return _any_word(
        text,
        (
            "fed",
            "fomc",
            "ecb",
            "boe",
            "boj",
            "boc",
            "rba",
            "rbnz",
            "cpi",
            "inflation",
            "yield",
            "yields",
            "treasury",
            "payroll",
        ),
    ) or _any_phrase(
        text,
        (
            "bank of england",
            "bank of japan",
            "bank of canada",
            "reserve bank",
        ),
    )


def _g10_policy_fires(text: str) -> bool:
    return (
        _any_word(text, ("fed", "fomc", "ecb", "boe", "boj", "boc", "rba", "rbnz"))
        or _any_phrase(
            text,
            (
                "bank of england",
                "bank of japan",
                "bank of canada",
                "reserve bank",
                "policy rate",
            ),
        )
    )


def _usd_rates_fires(text: str) -> bool:
    return _any_word(
        text, ("cpi", "inflation", "yield", "yields", "treasury", "payroll")
    )


def _g10_assets(text: str, usd_rates: bool) -> list[str]:
    assets: list[str] = []
    if usd_rates:
        assets.extend(["USD", "UST"])
    if _word(text, "ecb"):
        assets.append("EUR")
    if _phrase(text, "bank of england") or _word(text, "boe"):
        assets.append("GBP")
    if _phrase(text, "bank of japan") or _word(text, "boj"):
        assets.append("JPY")
    if _phrase(text, "bank of canada") or _word(text, "boc"):
        assets.append("CAD")
    if _word(text, "rba"):
        assets.append("AUD")
    if _word(text, "rbnz"):
        assets.append("NZD")
    if _word(text, "fed") or _word(text, "fomc"):
        if "USD" not in assets:
            assets.append("USD")
    seen: list[str] = []
    for a in assets:
        if a not in seen:
            seen.append(a)
    return seen


def _sanctions_story(text: str) -> bool:
    return _word(text, "sanction") or _word(text, "sanctions")


def _energy_context(text: str) -> bool:
    return _any_word(text, ("oil", "crude", "diesel", "energy", "lng", "brent", "wti", "opec", "hormuz"))


def _fiscal_interest(text: str) -> bool:
    if _phrase(text, "interest cost") or _phrase(text, "debt snowball"):
        return True
    return _word(text, "debt") and _any_word(text, ("trillion", "treasury", "fiscal"))


def _bare_oil(text: str) -> bool:
    if _hormuz_mentioned(text):
        return False
    return _any_word(text, ("oil", "brent", "wti", "crude"))


def _credit_funding(text: str) -> bool:
    return (
        _phrase(text, "credit spread")
        or _phrase(text, "private credit")
        or _phrase(text, "high-yield")
        or _word(text, "clo")
        or _word(text, "repo")
        or _word(text, "sofr")
        or _phrase(text, "funding stress")
        or _phrase(text, "bank stress")
    )


def _ai_financing_recall(text: str) -> bool:
    ai_side = _any_word(
        text, ("ai", "coreweave", "hyperscaler", "neocloud")
    ) or _phrase(text, "data center")
    fin_side = _any_word(text, ("debt", "bond", "financing", "capex"))
    return ai_side and fin_side


def _hold_review() -> dict[str, Any]:
    comps = _empty_components()
    return _transmission_from_parts(
        disposition="hold-for-review",
        affected_assets=[],
        channel=None,
        channels=[],
        reason_code="ambiguous_transmission",
        score=0,
        components=comps,
    )


def score_transmission(headline: str, summary: str) -> dict[str, Any]:
    text = _blob(headline, summary)
    subject = _subject_rule(text)
    if subject is not None:
        return subject

    comps = _empty_components()

    if _chicago_fed_activity(text):
        _set_channel(comps, "usd_rates")
        comps["asset_named"] = 2
        comps["shock"] = 0
        score = 7
        return _transmission_from_parts(
            disposition="assess",
            affected_assets=["USD"],
            channel="usd_rates",
            channels=["usd_rates"],
            reason_code="us_activity_index",
            score=score,
            components=comps,
        )

    if _coreweave_rule(text):
        _set_channel(comps, "credit_funding")
        comps["asset_named"] = 3
        comps["shock"] = 3
        score = 11
        return _transmission_from_parts(
            disposition="show",
            affected_assets=["credit_spreads", "UST"],
            channel="credit_funding",
            channels=["credit_funding"],
            reason_code="ai_capex_credit",
            score=score,
            components=comps,
        )

    if _hormuz_mentioned(text):
        channels = ["oil_energy_tot", "geopolitics_haven"]
        _set_channel(comps, "oil_energy_tot")
        _set_channel(comps, "geopolitics_haven")
        if _hormuz_diplomatic(text) and not _hormuz_acute(text):
            comps["asset_named"] = 2
            comps["shock"] = 2
            score = 13
            assets = ["Brent", "USD"]
        else:
            comps["asset_named"] = 3
            comps["shock"] = 3
            score = 15
            assets = ["Brent", "USD", "WTI", "CAD", "UST"]
        return _transmission_from_parts(
            disposition="show",
            affected_assets=assets,
            channel="oil_energy_tot",
            channels=channels,
            reason_code="oil_supply_shock",
            score=score,
            components=comps,
        )

    if _word(text, "china"):
        if _china_spillover_match(text):
            _set_channel(comps, "china_spillover")
            comps["asset_named"] = 3
            comps["shock"] = 2
            score = 10
            return _transmission_from_parts(
                disposition="show",
                affected_assets=["AUD", "iron_ore"],
                channel="china_spillover",
                channels=["china_spillover"],
                reason_code="china_commodity_spillover",
                score=score,
                components=comps,
            )
        return _hold_review()

    if _g10_trigger(text):
        g10 = _g10_policy_fires(text)
        usd = _usd_rates_fires(text)
        fired: list[str] = []
        if g10:
            _set_channel(comps, "g10_policy")
            fired.append("g10_policy")
        if usd:
            _set_channel(comps, "usd_rates")
            fired.append("usd_rates")
        if g10 and usd:
            comps["asset_named"] = 3
        elif g10 or usd:
            comps["asset_named"] = 2
        comps["shock"] = 2
        channel_sum = sum(CHANNEL_WEIGHTS[c] for c in fired)
        score = channel_sum + comps["asset_named"] + comps["shock"]
        if score >= 10:
            disposition = "show"
        elif score >= 7:
            disposition = "assess"
        else:
            disposition = "assess"
        reason = "g10_policy_path" if g10 else "usd_rates_repricing"
        return _transmission_from_parts(
            disposition=disposition,
            affected_assets=_g10_assets(text, usd),
            channel=_primary_channel(fired),
            channels=fired,
            reason_code=reason,
            score=score,
            components=comps,
        )

    if _sanctions_story(text):
        _set_channel(comps, "geopolitics_haven")
        energy = _energy_context(text)
        if energy:
            _set_channel(comps, "oil_energy_tot")
            comps["asset_named"] = 3
            comps["shock"] = 2
            score = 14
            assets = ["Brent", "USD"]
            channels = ["oil_energy_tot", "geopolitics_haven"]
            disposition = "show"
        else:
            comps["asset_named"] = 2
            comps["shock"] = 2
            score = 8
            assets = ["USD"]
            channels = ["geopolitics_haven"]
            disposition = "assess"
        return _transmission_from_parts(
            disposition=disposition,
            affected_assets=assets,
            channel="geopolitics_haven" if not energy else "oil_energy_tot",
            channels=channels,
            reason_code="geopolitics_haven_or_oil",
            score=score,
            components=comps,
        )

    if _fiscal_interest(text):
        _set_channel(comps, "usd_rates")
        comps["asset_named"] = 2
        comps["shock"] = 2
        return _transmission_from_parts(
            disposition="assess",
            affected_assets=["USD", "UST"],
            channel="usd_rates",
            channels=["usd_rates"],
            reason_code="usd_rates_repricing",
            score=9,
            components=comps,
        )

    if _bare_oil(text):
        _set_channel(comps, "oil_energy_tot")
        comps["asset_named"] = 2
        comps["shock"] = 0
        score = 7
        return _transmission_from_parts(
            disposition="assess",
            affected_assets=["Brent", "WTI"],
            channel="oil_energy_tot",
            channels=["oil_energy_tot"],
            reason_code="oil_supply_shock",
            score=score,
            components=comps,
        )

    if _credit_funding(text):
        _set_channel(comps, "credit_funding")
        comps["asset_named"] = 2
        acute = _any_word(text, ("distress", "emergency"))
        comps["shock"] = 3 if acute else 2
        score = 10 if acute else 9
        disposition = "show" if acute else "assess"
        return _transmission_from_parts(
            disposition=disposition,
            affected_assets=["credit_spreads"],
            channel="credit_funding",
            channels=["credit_funding"],
            reason_code="credit_funding_stress",
            score=score,
            components=comps,
        )

    if _ai_financing_recall(text):
        _set_channel(comps, "credit_funding")
        comps["asset_named"] = 3
        comps["shock"] = 3
        score = 11
        return _transmission_from_parts(
            disposition="show",
            affected_assets=["credit_spreads", "UST"],
            channel="credit_funding",
            channels=["credit_funding"],
            reason_code="ai_capex_credit",
            score=score,
            components=comps,
        )

    return _hold_review()


def _noise_would_suppress(text: str) -> bool:
    noise_hit = _any_word(text, ("podcast", "golf", "celebrity"))
    supply_escape = _any_word(text, ("hormuz", "opec", "brent", "wti", "crude"))
    return noise_hit and not supply_escape


def _recall_positive_classes(text: str) -> bool:
    if _word(text, "coreweave"):
        return True
    if _chicago_fed_activity(text):
        return True
    if _any_word(
        text,
        (
            "credit",
            "cds",
            "spread",
            "high-yield",
            "clo",
            "repo",
            "sofr",
            "lending",
            "default",
            "distress",
            "bond",
            "loan",
            "financing",
        ),
    ):
        return True
    ai_side = _any_word(
        text, ("ai", "coreweave", "hyperscaler", "neocloud")
    ) or _phrase(text, "data center")
    fin_side = _any_word(text, ("debt", "bond", "financing", "cds", "capex"))
    if ai_side and fin_side:
        return True
    if _sanctions_story(text) or _fiscal_interest(text):
        return True
    if _word(text, "china") and _any_word(
        text,
        ("stimulus", "property", "pboc", "commodity", "crude", "iron", "aud"),
    ):
        return True
    if _any_word(
        text,
        (
            "fed",
            "fomc",
            "ecb",
            "boe",
            "boj",
            "boc",
            "rba",
            "rbnz",
            "cpi",
            "inflation",
            "yield",
            "treasury",
            "payroll",
            "oil",
            "brent",
            "wti",
            "crude",
            "hormuz",
            "ormuz",
            "opec",
            "tariff",
            "sanction",
            "dollar",
            "fx",
        ),
    ) or _any_phrase(
        text,
        (
            "bank of england",
            "bank of japan",
            "bank of canada",
            "reserve bank",
        ),
    ):
        return True
    equity = _any_word(text, ("selloff",)) or _phrase(text, "s&p") or _word(
        text, "nasdaq"
    ) or _phrase(text, "bank stock")
    macro_link = _any_word(text, ("fed", "yield", "dollar", "treasury"))
    if equity and macro_link:
        return True
    return False


def recall_candidate(headline: str, summary: str) -> bool:
    text = _blob(headline, summary)
    if _noise_would_suppress(text):
        return False
    if _recall_positive_classes(text):
        return True
    sole_macro = _any_word(text, ("gdp", "recession", "unemployment"))
    if sole_macro:
        return False
    return False


def apply_transmission(item: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(item)
    headline = str(out.get("headline") or "")
    summary = str(out.get("summary") or "")
    transmission = score_transmission(headline, summary)
    out["transmission"] = transmission
    tx_score = int(transmission["score"])
    comps = dict(transmission["components"])
    comps["recency"] = 0
    comps["novelty"] = 0
    comps["distribution_weight"] = 0
    source = str(out.get("source_name") or "")
    distribution = "high" if source == "Bloomberg" else "standard"
    out["market_salience"] = {
        "score": max(0, tx_score),
        "distribution": distribution,
        "components": comps,
    }
    return out


def public_news_rows(news: list[Any]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in news:
        if not isinstance(row, dict):
            continue
        scored = apply_transmission(row)
        disposition = (scored.get("transmission") or {}).get("disposition")
        if disposition in ("suppress", "hold-for-review"):
            continue
        kept.append(scored)
    return kept
