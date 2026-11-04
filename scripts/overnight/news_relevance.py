"""Deterministic news transmission scoring (stdlib only)."""

from __future__ import annotations

import copy
import re
from typing import Any

from scripts.overnight.clock import now_ny, parse_iso

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


def _without_palm_oil(text: str) -> str:
    """Drop palm-oil phrases before crude/oil tokens are tested."""
    out = text
    for phrase in ("crude palm-oil", "crude palm oil", "palm-oil", "palm oil"):
        out = out.replace(phrase, " ")
    return out


def _non_palm_oil_token(text: str) -> bool:
    return _any_word(_without_palm_oil(text), ("oil", "crude", "brent", "wti"))


def _india_named(text: str) -> bool:
    return _word(text, "india") or _word(text, "indian")


def _vietnam_named(text: str) -> bool:
    return _word(text, "vietnam") or _word(text, "vietnamese")


def _oil_supply_role(text: str) -> bool:
    if _hormuz_mentioned(text) or _word(text, "opec"):
        return True
    if _non_palm_oil_token(text) and _any_word(
        text,
        (
            "export",
            "exports",
            "halt",
            "halts",
            "embargo",
            "blockade",
            "outage",
            "shutdown",
            "supply",
        ),
    ):
        return True
    return False


def _official_policy_phrase(text: str) -> bool:
    return _any_phrase(
        text,
        (
            "bank rate",
            "gilt",
            "money market operations",
            "complementary deposit facility",
            "official cash rate",
            "monetary policy meeting",
            "monetary policy summary",
            "financial stability",
        ),
    ) or _any_word(text, ("ocr", "intervention"))


def _transmission_role(text: str) -> bool:
    return (
        _oil_supply_role(text)
        or _credit_funding(text)
        or _ai_financing_recall(text)
        or _g10_policy_fires(text)
        or _usd_rates_fires(text)
        or _fiscal_interest(text)
        or (_sanctions_story(text) and _energy_context(text))
        or _official_policy_phrase(text)
    )


def _subject_rule(text: str) -> dict[str, Any] | None:
    comps = _empty_components()
    if (
        _vietnam_named(text)
        and _word(text, "gdp")
        and not _transmission_role(text)
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
    if (
        _india_named(text)
        and _any_phrase(text, ("trade deficit", "trade gap", "import bill"))
        and not _transmission_role(text)
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
    if (
        _word(text, "indonesia")
        and (
            _any_word(text, ("fire", "fires", "forest")) or "forest fire" in text
        )
        and not _transmission_role(text)
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
    supply_escape = _hormuz_mentioned(text)
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
    if (
        _phrase(text, "bank of england")
        or _word(text, "boe")
        or _phrase(text, "bank rate")
        or _word(text, "gilt")
    ):
        assets.append("GBP")
    if _phrase(text, "money market operations") or _phrase(
        text, "complementary deposit facility"
    ):
        assets.append("JPY")
    if _phrase(text, "official cash rate") or _word(text, "ocr"):
        assets.append("NZD")
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
    stripped = _without_palm_oil(text)
    return _any_word(stripped, ("oil", "crude", "diesel", "energy", "lng", "brent", "wti", "opec", "hormuz"))


def _fiscal_interest(text: str) -> bool:
    if _phrase(text, "interest cost") or _phrase(text, "debt snowball"):
        return True
    return _word(text, "debt") and _any_word(text, ("trillion", "treasury", "fiscal"))


def _bare_oil(text: str) -> bool:
    if _hormuz_mentioned(text):
        return False
    return _non_palm_oil_token(text)


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


_ROUTINE_POLITICS = (
    "city council",
    "mayoral",
    "mayor race",
    "local election",
    "campaign rally",
    "town hall",
    "primary debate",
    "endorses",
    "endorsement",
)

_CONTROL_EVENT = (
    "control of congress",
    "congressional control",
    "control of the house",
    "control of the senate",
    "house majority",
    "senate majority",
    "parliamentary majority",
    "control of parliament",
    "change of government",
    "government collapses",
    "government collapsed",
    "no-confidence",
    "no confidence",
    "snap election",
    "general election",
    "presidential election",
    "national election",
    "midterm election",
    "midterms",
)

_NEUTRAL_POLITICAL = (
    "control unchanged",
    "too close to call",
    "results pending",
    "count continues",
    "retains control",
    "holds control",
    "no change in control",
)

_POLITY_ASSETS = {
    "US": ["USD", "UST"],
    "GB": ["GBP"],
    "JP": ["JPY"],
    "CA": ["CAD"],
    "AU": ["AUD"],
    "NZ": ["NZD"],
    "EA": ["EUR"],
}

# Full weight through 18 hours, then a linear fade to an archival floor at 7 days.
_FRESH_FULL_HOURS = 18
_ARCHIVE_HOURS = 24 * 7
_FRESH_FULL_WEIGHT = 1000
_FRESH_FLOOR_WEIGHT = 200


def _routine_politics(text: str) -> bool:
    return _any_phrase(text, _ROUTINE_POLITICS)


def _g10_polity(text: str) -> str | None:
    """Named G10 polity. Party labels are ignored; only the institution or country counts."""
    if (
        _any_word(text, ("congress", "congressional", "senate"))
        or _phrase(text, "house of representatives")
        or _phrase(text, "control of the house")
        or _phrase(text, "white house")
        or _phrase(text, "united states")
        or _phrase(text, "u.s.")
        or _phrase(text, "the us")
        or _phrase(text, "us national")
        or _phrase(text, "us election")
        or _phrase(text, "us presidential")
        or _phrase(text, "us congress")
    ):
        return "US"
    if _any_word(text, ("uk", "britain", "british")) or _phrase(text, "united kingdom"):
        return "GB"
    if _any_word(text, ("japan", "japanese")):
        return "JP"
    if _any_word(text, ("canada", "canadian")):
        return "CA"
    if _any_word(text, ("australia", "australian")):
        return "AU"
    if _phrase(text, "new zealand"):
        return "NZ"
    if (
        _any_word(text, ("germany", "german", "france", "french", "italy", "italian", "eurozone"))
        or _phrase(text, "euro area")
    ):
        return "EA"
    return None


_PRICE_MOVE_OBJECTS = (
    "yield",
    "yields",
    "treasury",
    "treasuries",
    "gilt",
    "gilts",
    "dollar",
    "fx",
    "euro",
    "yen",
    "pound",
    "sterling",
    "bond",
    "bonds",
    "stock",
    "stocks",
    "equities",
    "equity",
    "share",
    "shares",
    "crude",
    "oil",
    "brent",
    "wti",
    "gold",
    "spread",
    "spreads",
    "prices",
)

_RATES_MOVE_OBJECTS = (
    "yield",
    "yields",
    "treasury",
    "treasuries",
    "gilt",
    "gilts",
    "bond",
    "bonds",
)

_STOCK_MOVE_OBJECTS = ("stock", "stocks", "equities", "equity", "share", "shares")

_FX_MOVE_OBJECTS = ("dollar", "fx", "euro", "yen", "pound", "sterling")

_PRICE_MOVE_WORDS = frozenset(
    {
        "rise",
        "rises",
        "rose",
        "rising",
        "fall",
        "falls",
        "fell",
        "falling",
        "drop",
        "drops",
        "dropped",
        "jump",
        "jumps",
        "jumped",
        "slide",
        "slides",
        "slid",
        "rally",
        "rallies",
        "rallied",
        "strengthen",
        "strengthens",
        "strengthened",
        "weaken",
        "weakens",
        "weakened",
        "surge",
        "surges",
        "surged",
        "tumble",
        "tumbles",
        "tumbled",
        "climb",
        "climbs",
        "climbed",
        "gain",
        "gains",
        "gained",
        "higher",
        "lower",
        "rebound",
        "rebounds",
        "rebounded",
        "plunge",
        "plunges",
        "plunged",
        "soar",
        "soars",
        "soared",
        "slump",
        "slumps",
        "slumped",
        "advance",
        "advances",
        "advanced",
        "decline",
        "declines",
        "declined",
        "move",
        "moves",
        "moved",
        "selloff",
    }
)

_SPEECH_FRAMING_VERBS = frozenset(
    {
        "says",
        "said",
        "tells",
        "told",
        "debates",
        "debated",
        "discussed",
        "discusses",
        "discuss",
    }
)

_CLAUSE_BARRIER = frozenset({".", ";"})

_MODAL_FORECAST = frozenset(
    {
        "could",
        "would",
        "might",
        "may",
        "will",
        "wont",
        "won't",
        "expected",
        "expects",
        "expect",
        "expectation",
        "likely",
        "unlikely",
        "forecast",
        "forecasts",
        "forecasted",
        "predict",
        "predicts",
        "predicted",
        "prediction",
        "poll",
        "polls",
        "polling",
        "hope",
        "hopes",
        "hoped",
        "if",
        "unless",
        "think",
        "thinks",
        "thought",
        "says",
        "said",
        "tells",
        "told",
        "claims",
        "claimed",
        "vows",
        "vowed",
    }
)

_NEGATION_TOKENS = frozenset(
    {"not", "no", "never", "without", "didnt", "didn't", "dont", "don't"}
)

_OUTCOME_WORDS = frozenset(
    {
        "win",
        "wins",
        "won",
        "winner",
        "loses",
        "lost",
        "flips",
        "flipped",
        "flip",
    }
)

_ELECTION_CONTEXT = frozenset(
    {
        "election",
        "elections",
        "midterm",
        "midterms",
        "results",
        "result",
        "congress",
        "congressional",
        "house",
        "senate",
        "parliament",
    }
)

_RACE_CALL_VERBS = frozenset({"calls", "called", "call"})

_RACE_CALL_OBJECTS = frozenset({"house", "senate", "congress", "race"})

_CONTROL_PHRASE_PARTS: tuple[tuple[str, ...], ...] = (
    ("control", "of", "congress"),
    ("congressional", "control"),
    ("control", "of", "the", "house"),
    ("control", "of", "the", "senate"),
    ("house", "majority"),
    ("senate", "majority"),
    ("parliamentary", "majority"),
    ("control", "of", "parliament"),
    ("change", "of", "government"),
    ("government", "collapses"),
    ("government", "collapsed"),
    ("no", "confidence"),
    ("no-confidence",),
    ("takes", "the", "house"),
    ("take", "the", "house"),
    ("took", "the", "house"),
    ("takes", "control"),
    ("take", "control"),
    ("took", "control"),
    ("declared", "winner"),
    ("changes", "control"),
    ("change", "control"),
)

_CONTROL_PHRASES_NEEDING_ELECTION_CONTEXT = frozenset(
    {("changes", "control"), ("change", "control")}
)

_NO_CONFIDENCE_GOVERNMENT_CONTEXT = frozenset(
    {
        "government",
        "parliament",
        "vote",
        "cabinet",
        "minister",
        "prime",
        "coalition",
    }
)

_CONTROL_PHRASES_NEEDING_NO_CONFIDENCE_GOVERNMENT_CONTEXT = frozenset(
    {("no", "confidence"), ("no-confidence",)}
)


def _clause_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+|[.;]", text.lower())


def _price_tokens(text: str) -> list[str]:
    return _clause_tokens(text)


def _clause_start(tokens: list[str], index: int) -> int:
    start = 0
    for i in range(index):
        if tokens[i] in _CLAUSE_BARRIER:
            start = i + 1
    return start


def _clause_slice(tokens: list[str], index: int) -> list[str]:
    start = _clause_start(tokens, index)
    end = index + 1
    while end < len(tokens) and tokens[end] not in _CLAUSE_BARRIER:
        end += 1
    return tokens[start:end]


def _scan_window(tokens: list[str], index: int, max_back: int) -> list[str]:
    clause_start = _clause_start(tokens, index)
    start = max(clause_start, index - max_back)
    return [t for t in tokens[start:index] if t not in _CLAUSE_BARRIER]


def _modal_in_window(window: list[str]) -> bool:
    for tok in window:
        if tok in _MODAL_FORECAST:
            return True
        if tok == "won't":
            return True
    return False


def _token_unrealized(tokens: list[str], index: int) -> bool:
    return _modal_in_window(_scan_window(tokens, index, 6))


def _token_negated(tokens: list[str], index: int) -> bool:
    window = _scan_window(tokens, index, 3)
    if "not" in window and "only" in window:
        return False
    for tok in window:
        if tok in _NEGATION_TOKENS:
            return True
        if tok.endswith("n't"):
            return True
    return False


def _token_unresolved(tokens: list[str], index: int) -> bool:
    window = _scan_window(tokens, index, 4)
    return any(t in ("pending", "unresolved", "uncalled") for t in window)


def _phrase_starts(tokens: list[str], parts: tuple[str, ...]) -> list[int]:
    if not parts:
        return []
    n = len(parts)
    hits: list[int] = []
    for i in range(len(tokens)):
        if tokens[i] in _CLAUSE_BARRIER:
            continue
        if i + n > len(tokens):
            continue
        ok = True
        for j in range(n):
            t = tokens[i + j]
            if t in _CLAUSE_BARRIER or t != parts[j]:
                ok = False
                break
        if ok:
            hits.append(i)
    return hits


def _tokens_near(tokens: list[str], index: int, pool: frozenset[str], radius: int = 4) -> bool:
    lo = max(0, index - radius)
    hi = min(len(tokens), index + radius + 1)
    for j in range(lo, hi):
        if tokens[j] in _CLAUSE_BARRIER:
            continue
        if tokens[j] in pool:
            return True
    return False


def _clause_has_election_context(tokens: list[str], index: int) -> bool:
    clause = _clause_slice(tokens, index)
    return any(t in _ELECTION_CONTEXT for t in clause if t not in _CLAUSE_BARRIER)


def _clause_has_no_confidence_government_context(tokens: list[str], index: int) -> bool:
    clause = _clause_slice(tokens, index)
    return any(
        t in _NO_CONFIDENCE_GOVERNMENT_CONTEXT for t in clause if t not in _CLAUSE_BARRIER
    )


def _political_anchor_indices(tokens: list[str]) -> list[int]:
    anchors: list[int] = []
    for parts in _CONTROL_PHRASE_PARTS:
        if parts in _CONTROL_PHRASES_NEEDING_ELECTION_CONTEXT:
            for idx in _phrase_starts(tokens, parts):
                if _clause_has_election_context(tokens, idx):
                    anchors.append(idx)
        elif parts in _CONTROL_PHRASES_NEEDING_NO_CONFIDENCE_GOVERNMENT_CONTEXT:
            for idx in _phrase_starts(tokens, parts):
                if _clause_has_no_confidence_government_context(tokens, idx):
                    anchors.append(idx)
        else:
            anchors.extend(_phrase_starts(tokens, parts))
    for idx, tok in enumerate(tokens):
        if tok in _CLAUSE_BARRIER:
            continue
        if tok in _OUTCOME_WORDS and _clause_has_election_context(tokens, idx):
            anchors.append(idx)
    for idx, tok in enumerate(tokens):
        if tok in _CLAUSE_BARRIER:
            continue
        if tok in _RACE_CALL_VERBS and _tokens_near(tokens, idx, _RACE_CALL_OBJECTS, 4):
            anchors.append(idx)
    # de-dupe while preserving order
    seen: set[int] = set()
    ordered: list[int] = []
    for idx in anchors:
        if idx not in seen:
            seen.add(idx)
            ordered.append(idx)
    return ordered


def _anchor_realized(tokens: list[str], index: int) -> bool:
    if _token_unrealized(tokens, index):
        return False
    if _token_unresolved(tokens, index):
        return False
    return True


def _race_call_polity(text: str) -> str | None:
    tokens = _clause_tokens(text)
    for idx in _political_anchor_indices(tokens):
        if tokens[idx] not in _RACE_CALL_VERBS:
            continue
        if not _anchor_realized(tokens, idx):
            continue
        if _tokens_near(tokens, idx, frozenset({"house", "senate", "congress"}), 4):
            return "US"
    return None


def _effective_g10_polity(text: str) -> str | None:
    return _g10_polity(text) or _race_call_polity(text)


def _realized_political_anchors(text: str) -> bool:
    tokens = _clause_tokens(text)
    return any(_anchor_realized(tokens, idx) for idx in _political_anchor_indices(tokens))


def _pending_election_assess(text: str) -> bool:
    if not (
        _g10_polity(text)
        or _word(text, "election")
        or _any_word(text, ("midterm", "midterms", "results", "result"))
    ):
        return False
    if not _any_word(text, ("pending", "unresolved", "uncalled")):
        return False
    return not _realized_political_anchors(text)


def _move_token_at(tokens: list[str], index: int) -> bool:
    tok = tokens[index]
    if tok in _PRICE_MOVE_WORDS:
        return True
    if tok == "off" and index > 0 and tokens[index - 1] in ("sold", "sell"):
        return True
    return False


def _speech_framed_move(tokens: list[str], move_index: int) -> bool:
    for verb_index, tok in enumerate(tokens):
        if tok not in _SPEECH_FRAMING_VERBS:
            continue
        if verb_index < move_index <= verb_index + 6:
            return True
    return False


def _move_realized(tokens: list[str], move_index: int) -> bool:
    if _token_unrealized(tokens, move_index):
        return False
    if _token_negated(tokens, move_index):
        return False
    if _speech_framed_move(tokens, move_index):
        return False
    return True


def _recorded_price_move(text: str, *, objects: tuple[str, ...] | None = None) -> bool:
    """True when the source text records a price move (object within 4 tokens of a move word)."""
    allowed = frozenset(objects if objects is not None else _PRICE_MOVE_OBJECTS)
    tokens = _price_tokens(text)
    move_indices = [
        i
        for i in range(len(tokens))
        if _move_token_at(tokens, i) and _move_realized(tokens, i)
    ]
    price_indices = [i for i, tok in enumerate(tokens) if tok in allowed]
    for move_index in move_indices:
        for price_index in price_indices:
            if abs(move_index - price_index) <= 4:
                return True
    return False


def _recorded_rates_move(text: str) -> bool:
    return _recorded_price_move(text, objects=_RATES_MOVE_OBJECTS)


def _recorded_stock_move(text: str) -> bool:
    return _recorded_price_move(text, objects=_STOCK_MOVE_OBJECTS)


def _recorded_fx_move(text: str) -> bool:
    return _recorded_price_move(text, objects=_FX_MOVE_OBJECTS)


def _market_evidence(text: str) -> bool:
    """True only when the source records an actual price move."""
    return _recorded_price_move(text)


def _acute_central_bank_shock(text: str) -> bool:
    if not (_g10_policy_fires(text) or _official_policy_phrase(text)):
        return False
    if _any_word(
        text,
        (
            "hike",
            "hikes",
            "cut",
            "cuts",
            "surprise",
            "surprises",
            "emergency",
            "unexpected",
            "unexpectedly",
            "decision",
            "decides",
            "raises",
            "raise",
            "raised",
            "lowers",
            "lower",
            "lowered",
        ),
    ):
        return True
    return _any_phrase(
        text,
        ("rate cut", "rate hike", "policy rate", "bank rate", "official cash rate"),
    )


def _control_event(text: str) -> bool:
    """A result or a break in government, not a campaign calendar."""
    return _realized_political_anchors(text)


def _outcome_language(text: str) -> bool:
    tokens = _clause_tokens(text)
    for idx, tok in enumerate(tokens):
        if tok in _OUTCOME_WORDS and _clause_has_election_context(tokens, idx):
            return True
    return _any_phrase(
        text,
        ("takes control", "secures control", "loses control", "changes control", "declared winner"),
    )


def _political_neutral(text: str) -> bool:
    return _any_phrase(text, _NEUTRAL_POLITICAL)


def _material_political_event(text: str) -> bool:
    """National political information with a G10 transmission, or an explicit market link.

    Routine campaign color and local races are not material. Party names are not an input.
    """
    if _routine_politics(text) and not _any_phrase(
        text, ("government collapses", "government collapsed", "no-confidence", "no confidence")
    ):
        return False
    if _realized_political_anchors(text):
        if _effective_g10_polity(text):
            return True
        return _market_evidence(text)
    if _pending_election_assess(text):
        return True
    if (
        _word(text, "election")
        and _market_evidence(text)
        and not _g10_polity(text)
    ):
        return True
    return False


def _acute_geopolitics(text: str) -> bool:
    if _routine_politics(text):
        return False
    conflict = (
        _any_word(text, ("invasion", "invades", "coup", "missile", "airstrike", "blockade", "ceasefire"))
        or _phrase(text, "martial law")
        or _phrase(text, "declares war")
        or _phrase(text, "air strike")
    )
    if not conflict:
        return False
    theater = _g10_polity(text) or _any_word(
        text, ("russia", "ukraine", "taiwan", "iran", "israel")
    ) or _phrase(text, "middle east")
    return bool(theater or _market_evidence(text) or _energy_context(text))


def _with_claim(transmission: dict[str, Any], claim: str) -> dict[str, Any]:
    out = dict(transmission)
    out["claim"] = claim
    return out


def _score_political_or_geopolitics(text: str) -> dict[str, Any] | None:
    """Possible G10 channels unless the source itself states a market move."""
    if _material_political_event(text):
        comps = _empty_components()
        polity = _effective_g10_polity(text)
        evidenced = _market_evidence(text)
        assets = list(_POLITY_ASSETS.get(polity or "", []))
        if _recorded_fx_move(text) and "USD" not in assets:
            assets.append("USD")
        if _recorded_rates_move(text) and "UST" not in assets:
            assets.append("UST")
        if _recorded_stock_move(text) and "SPX" not in assets:
            assets.append("SPX")
        if _energy_context(text) and "Brent" not in assets:
            assets.append("Brent")
        claim = "evidenced" if evidenced else "possible"
        if polity is None:
            _set_channel(comps, "global_risk")
            comps["asset_named"] = 3
            comps["shock"] = 3
            return _with_claim(
                _transmission_from_parts(
                    disposition="show",
                    affected_assets=assets or ["USD"],
                    channel="global_risk",
                    channels=["global_risk"],
                    reason_code="political_risk_transmission",
                    score=10,
                    components=comps,
                ),
                claim,
            )
        if _political_neutral(text) or _pending_election_assess(text):
            _set_channel(comps, "geopolitics_haven")
            comps["asset_named"] = 2
            comps["shock"] = 2
            return _with_claim(
                _transmission_from_parts(
                    disposition="assess",
                    affected_assets=assets,
                    channel="geopolitics_haven",
                    channels=["geopolitics_haven"],
                    reason_code="political_risk_transmission",
                    score=8,
                    components=comps,
                ),
                claim,
            )
        _set_channel(comps, "geopolitics_haven")
        _set_channel(comps, "global_risk")
        channels = ["geopolitics_haven", "global_risk"]
        if _recorded_rates_move(text):
            _set_channel(comps, "usd_rates")
            channels.append("usd_rates")
        comps["asset_named"] = 3 if evidenced else 2
        comps["shock"] = 2
        score = 13 if evidenced else 12
        return _with_claim(
            _transmission_from_parts(
                disposition="show",
                affected_assets=assets,
                channel="geopolitics_haven",
                channels=channels,
                reason_code="political_risk_transmission",
                score=score,
                components=comps,
            ),
            claim,
        )

    if _acute_geopolitics(text):
        comps = _empty_components()
        energy = _energy_context(text)
        evidenced = _market_evidence(text)
        _set_channel(comps, "geopolitics_haven")
        channels = ["geopolitics_haven"]
        if energy:
            _set_channel(comps, "oil_energy_tot")
            channels = ["oil_energy_tot", "geopolitics_haven"]
            comps["asset_named"] = 3
            comps["shock"] = 2
            score = 14
            assets = ["Brent", "USD"]
            channel = "oil_energy_tot"
            claim = "evidenced" if _recorded_price_move(text) else "possible"
        elif evidenced:
            _set_channel(comps, "global_risk")
            channels = ["geopolitics_haven", "global_risk"]
            comps["asset_named"] = 2
            comps["shock"] = 1
            score = 11
            assets = ["USD"]
            channel = "geopolitics_haven"
            claim = "evidenced"
        else:
            comps["asset_named"] = 3
            comps["shock"] = 3
            score = 10
            assets = ["USD"]
            channel = "geopolitics_haven"
            claim = "possible"
        return _with_claim(
            _transmission_from_parts(
                disposition="show",
                affected_assets=assets,
                channel=channel,
                channels=channels,
                reason_code="geopolitics_haven_or_oil",
                score=score,
                components=comps,
            ),
            claim,
        )
    return None


def _hours_since(published_at: str | None, when) -> float | None:
    if not published_at:
        return None
    try:
        published = parse_iso(str(published_at))
    except ValueError:
        return None
    cutoff = now_ny(when)
    if published > cutoff:
        return None
    return (cutoff - published).total_seconds() / 3600.0


def freshness_weight(published_at: str | None, when) -> int:
    """Integer freshness weight. Recent evidence keeps full weight; week-old copy fades."""
    hours = _hours_since(published_at, when)
    if hours is None:
        return _FRESH_FLOOR_WEIGHT
    if hours <= _FRESH_FULL_HOURS:
        return _FRESH_FULL_WEIGHT
    if hours >= _ARCHIVE_HOURS:
        return _FRESH_FLOOR_WEIGHT
    span = _ARCHIVE_HOURS - _FRESH_FULL_HOURS
    drop = 800.0 * (hours - _FRESH_FULL_HOURS) / span
    return int(round(_FRESH_FULL_WEIGHT - drop))


def prominence_score(transmission_score: int, published_at: str | None, when) -> int:
    """Market significance scaled by freshness. Does not change disposition."""
    return max(0, int(transmission_score)) * freshness_weight(published_at, when) // _FRESH_FULL_WEIGHT


def story_currency(published_at: str | None, when) -> str:
    hours = _hours_since(published_at, when)
    if hours is None or hours > 24:
        return "archival"
    return "current"


def presentation_rank_tuple(
    transmission_score: int,
    published_at: str | None,
    when,
) -> tuple[int, int, str]:
    """Shared order for the saved supplement and the current-headlines panel."""
    score = max(0, int(transmission_score))
    return (
        prominence_score(score, published_at, when),
        score,
        str(published_at or ""),
    )


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
        if not (_material_political_event(text) or _acute_geopolitics(text)):
            return _hold_review()

    if not _acute_central_bank_shock(text):
        political = _score_political_or_geopolitics(text)
        if political is not None:
            return political

    if _g10_trigger(text) or _g10_policy_fires(text) or _official_policy_phrase(text):
        g10 = _g10_policy_fires(text) or _official_policy_phrase(text)
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
    supply_escape = _hormuz_mentioned(text)
    return noise_hit and not supply_escape


def _recall_positive_classes(text: str) -> bool:
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
            "bank rate",
            "gilt",
            "money market operations",
            "complementary deposit facility",
            "official cash rate",
            "monetary policy meeting",
            "monetary policy summary",
            "financial stability",
        ),
    ) or _any_word(text, ("ocr", "intervention")):
        return True
    equity = _any_word(text, ("selloff",)) or _phrase(text, "s&p") or _word(
        text, "nasdaq"
    ) or _phrase(text, "bank stock")
    macro_link = _any_word(text, ("fed", "yield", "dollar", "treasury"))
    if equity and macro_link:
        return True
    if _material_political_event(text) or _acute_geopolitics(text):
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
