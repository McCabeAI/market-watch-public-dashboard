"""Canonical policy-rate state, independent of dashboard HTML.

Country Detail reads ``data/policy_state.json``. It does not parse rendered
news cards, headlines, or other presentation markup.

The United States record is refreshed from the Federal Reserve monetary-policy
press feed, the FOMC statement, and that statement's implementation note.
A standing decision stays current until a later decision is in force. Age in
days is not a freshness limit.

Canada, Australia, New Zealand, the euro area, and Japan do not have a
structured official target-rate series in this repository. Overnight
benchmarks (CORRA, AONIA, the uncollateralized call rate, €STR, TONA, SOFR)
are market fixings, not policy targets, and are not copied here. Those
countries stay ``unavailable`` until a real decision source is wired.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
POLICY_STATE_PATH = Path("data") / "policy_state.json"
SCHEMA_VERSION = 1
FED_MONETARY_FEED = "https://www.federalreserve.gov/feeds/press_monetary.xml"
USER_AGENT = "MarketWatchPolicyState/1.0"
COUNTRY_CODES = ("US", "CA", "AU", "NZ", "EA", "JP")

Fetch = Callable[[str], str]

_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
_DATE_TEXT = (
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s+(\d{4})"
)
_NUMBER = r"(?:\d+-\d+/\d+|\d+\.\d+|\d+)"
_STATEMENT_RANGE = re.compile(
    rf"target range for the federal funds rate\b.*?to\s+({_NUMBER})\s+to\s+({_NUMBER})\s+percent",
    re.I,
)
_IMPLEMENTATION_RANGE = re.compile(
    rf"Effective\s+{_DATE_TEXT}.{{0,800}}?target range of\s+({_NUMBER})\s+to\s+({_NUMBER})\s+percent",
    re.I,
)
_FED_STATEMENT_URL = re.compile(
    r"https://www\.federalreserve\.gov/newsevents/pressreleases/monetary\d{8}a\.htm$"
)


class PolicyStateError(ValueError):
    """Official policy text could not be turned into a decision."""


class PolicySourceUnavailable(PolicyStateError):
    """The official source could not be fetched. A standing decision stays."""


# Explicit gaps. These records carry no rate. Do not fill them with a
# hard-coded current setting or with an overnight fixing.
EXPLICIT_GAPS: dict[str, dict[str, str]] = {
    "CA": {
        "central_bank": "Bank of Canada",
        "instrument": "target overnight rate",
        "rate_type": "single",
        "gap": (
            "No structured Bank of Canada target-overnight-rate series is collected. "
            "scripts/policy_path_data.py records CORRA, an overnight financing benchmark, "
            "not the policy target. This record does not invent a target rate."
        ),
    },
    "AU": {
        "central_bank": "Reserve Bank of Australia",
        "instrument": "cash rate target",
        "rate_type": "single",
        "gap": (
            "No structured RBA cash-rate target decision is collected. "
            "RBA F1 AONIA is an overnight cash benchmark, not the cash-rate target. "
            "This record does not invent a target rate."
        ),
    },
    "NZ": {
        "central_bank": "Reserve Bank of New Zealand",
        "instrument": "official cash rate",
        "rate_type": "single",
        "gap": (
            "data/country_registry.json sets NZ has_policy_path to false, and no official "
            "OCR decision series is collected. This record does not invent a cash rate."
        ),
    },
    "EA": {
        "central_bank": "European Central Bank",
        "instrument": "deposit facility rate",
        "rate_type": "single",
        "gap": (
            "No structured ECB deposit-facility-rate decision is collected. "
            "Euro-area acquisition covers Bund yields and €STR futures, not the policy rates. "
            "This record does not invent a rate."
        ),
    },
    "JP": {
        "central_bank": "Bank of Japan",
        "instrument": "uncollateralized overnight call rate target",
        "rate_type": "single",
        "gap": (
            "No structured Bank of Japan policy-rate decision is collected. "
            "The JP rates bundle records the overnight call fixing and TONA futures, "
            "not the policy-rate decision. This record does not invent a rate."
        ),
    },
}


def _stamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gap_country(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "central_bank": spec["central_bank"],
        "instrument": spec["instrument"],
        "rate_type": spec["rate_type"],
        "status": "unavailable",
        "decisions": [],
        "gap": spec["gap"],
        "last_refresh_error": None,
    }


def empty_policy_state(now: datetime | None = None) -> dict[str, Any]:
    countries: dict[str, Any] = {
        "US": {
            "central_bank": "Federal Reserve",
            "instrument": "federal funds target range",
            "rate_type": "range",
            "status": "unavailable",
            "decisions": [],
            "gap": None,
            "last_refresh_error": None,
        }
    }
    for code, spec in EXPLICIT_GAPS.items():
        countries[code] = _gap_country(spec)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _stamp(now),
        "source_note": (
            "Structured policy settings produced by scripts/policy_state.py from official "
            "central-bank decisions. Country Detail reads this file. It does not parse "
            "dashboard HTML, news cards, or headlines."
        ),
        "countries": countries,
    }


def policy_state_file(root: Path | None = None) -> Path:
    return (root or ROOT) / POLICY_STATE_PATH


def load_policy_state(root: Path | None = None) -> dict[str, Any] | None:
    """Return the canonical document, or None when it is absent or unreadable."""
    path = policy_state_file(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    if not isinstance(payload.get("countries"), dict):
        return None
    return payload


def parse_fed_percent(token: str) -> float:
    """Parse an FOMC mixed number such as ``3-3/4`` or ``4`` into a percent."""
    mixed = re.fullmatch(r"(\d+)-(\d+)/(\d+)", token.strip())
    if mixed:
        whole = int(mixed.group(1))
        numerator = int(mixed.group(2))
        denominator = int(mixed.group(3))
        if denominator == 0:
            raise PolicyStateError(f"invalid Federal Reserve percent {token}")
        return whole + numerator / denominator
    try:
        return float(token)
    except ValueError as exc:
        raise PolicyStateError(f"invalid Federal Reserve percent {token}") from exc


def _parse_date(month: str, day: str, year: str) -> str:
    try:
        return date(int(year), _MONTHS[month], int(day)).isoformat()
    except (KeyError, ValueError) as exc:
        raise PolicyStateError(f"invalid Federal Reserve date {month} {day}, {year}") from exc


def html_to_text(page: str) -> str:
    stripped = re.sub(r"(?is)<script\b.*?</script>", " ", page)
    stripped = re.sub(r"(?is)<style\b.*?</style>", " ", stripped)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", unescape(stripped)).strip()


def _official_statement_url(url: str) -> str:
    cleaned = unescape(url).strip()
    if not _FED_STATEMENT_URL.fullmatch(cleaned):
        raise PolicyStateError(f"unexpected Federal Reserve statement URL {cleaned}")
    return cleaned


def latest_fomc_statement_url(feed_xml: str) -> str:
    """Latest 'issues FOMC statement' link. Projection releases are ignored."""
    candidates: list[tuple[str, str]] = []
    for item in re.findall(r"<item\b[^>]*>(.*?)</item>", feed_xml, flags=re.S):
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", item, flags=re.S)
        link_match = re.search(r"<link\b[^>]*>(.*?)</link>", item, flags=re.S)
        if not title_match or not link_match:
            continue
        title = unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title_match.group(1), flags=re.S))
        title = re.sub(r"\s+", " ", title).strip()
        if "issues FOMC statement" not in title:
            continue
        link = unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", link_match.group(1), flags=re.S)).strip()
        found = re.search(r"monetary(\d{8})a\.htm", link)
        if not found:
            continue
        if not link.startswith("https://www.federalreserve.gov/"):
            continue
        candidates.append((found.group(1), link.split("?", 1)[0]))
    if not candidates:
        raise PolicySourceUnavailable("Federal Reserve monetary feed has no FOMC statement")
    candidates.sort()
    return _official_statement_url(candidates[-1][1])


def implementation_note_url(statement_html: str, statement_url: str) -> str:
    match = re.search(
        r'href="([^"]+)"[^>]*>\s*Implementation Note',
        statement_html,
        flags=re.I,
    )
    if not match:
        raise PolicyStateError("FOMC statement has no implementation note link")
    resolved = urljoin(statement_url, unescape(match.group(1)).strip())
    if not resolved.startswith("https://www.federalreserve.gov/"):
        raise PolicyStateError(f"unexpected implementation note URL {resolved}")
    return resolved


def parse_fomc_statement(statement_html: str) -> dict[str, Any]:
    """Target range and decision date from an official FOMC statement page."""
    date_match = re.search(
        rf'class="article__time"[^>]*>\s*{_DATE_TEXT}\s*<',
        statement_html,
    )
    if not date_match:
        raise PolicyStateError("FOMC statement has no article date")
    text = html_to_text(statement_html)
    range_match = _STATEMENT_RANGE.search(text)
    if not range_match:
        raise PolicyStateError("FOMC statement has no federal funds target range")
    lower = parse_fed_percent(range_match.group(1))
    upper = parse_fed_percent(range_match.group(2))
    if not lower < upper:
        raise PolicyStateError("FOMC target range is not ordered")
    return {
        "lower": lower,
        "upper": upper,
        "decision_date": _parse_date(*date_match.groups()),
    }


def parse_fomc_implementation(implementation_html: str) -> dict[str, Any]:
    """Effective date and confirming target range from the implementation note."""
    text = html_to_text(implementation_html)
    match = _IMPLEMENTATION_RANGE.search(text)
    if not match:
        raise PolicyStateError("implementation note has no effective target range")
    month, day, year, lower_token, upper_token = match.groups()
    lower = parse_fed_percent(lower_token)
    upper = parse_fed_percent(upper_token)
    if not lower < upper:
        raise PolicyStateError("implementation target range is not ordered")
    return {
        "lower": lower,
        "upper": upper,
        "effective_date": _parse_date(month, day, year),
    }


def _same_range(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return round(float(left["lower"]), 4) == round(float(right["lower"]), 4) and round(
        float(left["upper"]), 4
    ) == round(float(right["upper"]), 4)


def acquire_us_decision(fetch: Fetch, retrieved_at: str) -> dict[str, Any]:
    """Fetch the latest official FOMC decision. Does not read dashboard HTML."""
    statement_url = latest_fomc_statement_url(fetch(FED_MONETARY_FEED))
    statement_html = fetch(statement_url)
    statement = parse_fomc_statement(statement_html)
    note_url = implementation_note_url(statement_html, statement_url)
    implementation = parse_fomc_implementation(fetch(note_url))
    if not _same_range(statement, implementation):
        raise PolicyStateError(
            "FOMC statement and implementation note target ranges disagree"
        )
    return {
        "lower": statement["lower"],
        "upper": statement["upper"],
        "decision_date": statement["decision_date"],
        "effective_date": implementation["effective_date"],
        "source_name": "Federal Reserve",
        "source_url": statement_url,
        "implementation_url": note_url,
        "retrieved_at": retrieved_at,
        "status": "current",
        "provenance": "official_fomc_statement",
    }


def _complete(decision: dict[str, Any]) -> bool:
    if decision.get("status") in {"stale", "unavailable"}:
        return False
    if not decision.get("source_name") or not decision.get("source_url"):
        return False
    if not str(decision.get("source_url", "")).startswith("https://"):
        return False
    if not decision.get("decision_date") or not decision.get("retrieved_at"):
        return False
    if decision.get("lower") is None or decision.get("upper") is None:
        if decision.get("rate") is None:
            return False
    return True


def _in_force(decision: dict[str, Any], as_of: date) -> bool:
    try:
        decided = date.fromisoformat(str(decision.get("decision_date")))
    except (TypeError, ValueError):
        return False
    if decided > as_of:
        return False
    effective = decision.get("effective_date")
    if effective:
        try:
            if date.fromisoformat(str(effective)) > as_of:
                return False
        except ValueError:
            return False
    return True


def _sort_key(decision: dict[str, Any]) -> tuple[str, str]:
    return (str(decision.get("effective_date") or decision.get("decision_date") or ""), str(decision.get("decision_date") or ""))


def resolve_country(state: dict[str, Any] | None, code: str, as_of: date) -> dict[str, Any]:
    """Display status for one country. Day count never changes the result.

    Returns ``status`` of current, superseded is not returned here: this picks
    the standing setting. Older decisions are classified by ``decision_status``.
    """
    if not state or not isinstance(state.get("countries"), dict) or code not in state["countries"]:
        return {"status": "missing", "decision": None}
    block = state["countries"][code]
    if not isinstance(block, dict):
        return {"status": "missing", "decision": None}
    decisions = [item for item in (block.get("decisions") or []) if isinstance(item, dict)]
    if not decisions:
        if block.get("status") == "stale":
            return {"status": "stale", "decision": None}
        return {"status": "unavailable", "decision": None}
    in_force = [item for item in sorted(decisions, key=_sort_key) if _in_force(item, as_of)]
    if not in_force:
        return {"status": "unavailable", "decision": None}
    latest = in_force[-1]
    if latest.get("status") == "stale":
        return {"status": "stale", "decision": None}
    if not _complete(latest):
        return {"status": "unavailable", "decision": None}
    return {"status": "current", "decision": latest}


def decision_status(state: dict[str, Any] | None, code: str, decision_date: str, as_of: date) -> str:
    """Status of one stored decision: current, superseded, stale, unavailable, or missing."""
    if not state or not isinstance(state.get("countries"), dict) or code not in state["countries"]:
        return "missing"
    block = state["countries"][code]
    decisions = [item for item in (block.get("decisions") or []) if isinstance(item, dict)]
    matches = [item for item in decisions if str(item.get("decision_date")) == decision_date]
    if not matches:
        return "missing"
    chosen = matches[-1]
    if chosen.get("status") == "stale":
        return "stale"
    if not _complete(chosen) or not _in_force(chosen, as_of):
        return "unavailable"
    resolved = resolve_country(state, code, as_of)
    standing = resolved.get("decision")
    if standing is not None and (
        standing is chosen
        or (
            standing.get("decision_date") == chosen.get("decision_date")
            and standing.get("source_url") == chosen.get("source_url")
        )
    ):
        return "current"
    in_force = [item for item in sorted(decisions, key=_sort_key) if _in_force(item, as_of)]
    latest = in_force[-1] if in_force else None
    if latest is not None and _sort_key(chosen) < _sort_key(latest):
        return "superseded"
    if standing is None:
        return resolved["status"]
    return "unavailable"


def _us_block(decisions: list[dict[str, Any]], *, error: str | None, as_of_status: str) -> dict[str, Any]:
    return {
        "central_bank": "Federal Reserve",
        "instrument": "federal funds target range",
        "rate_type": "range",
        "status": as_of_status,
        "decisions": decisions,
        "gap": None,
        "last_refresh_error": error,
    }


def _merge_us_decisions(previous: list[dict[str, Any]], new: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for old in previous:
        if not isinstance(old, dict):
            continue
        if old.get("decision_date") == new["decision_date"] and old.get("source_url") == new["source_url"]:
            continue
        if old.get("status") != "superseded" and str(old.get("decision_date") or "") < str(new["decision_date"]):
            old = {**old, "status": "superseded"}
        merged.append(old)
    merged.append(new)
    merged.sort(key=_sort_key)
    return merged


def refresh_policy_state(
    previous: dict[str, Any] | None,
    fetch: Fetch,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rebuild policy state from the official US source plus explicit gaps.

    A fetch or parse failure keeps the last verified US decisions. It does not
    expire them because a day count elapsed, and it does not invent a rate.
    """
    retrieved_at = _stamp(now)
    base = empty_policy_state(now)
    prior_us = []
    if previous and isinstance(previous.get("countries"), dict):
        prior_block = previous["countries"].get("US") or {}
        if isinstance(prior_block, dict):
            prior_us = deepcopy(prior_block.get("decisions") or [])
    try:
        decision = acquire_us_decision(fetch, retrieved_at)
    except PolicySourceUnavailable as exc:
        base["countries"]["US"] = _us_block(
            prior_us,
            error=str(exc),
            as_of_status="current" if any(item.get("status") != "superseded" for item in prior_us) else "unavailable",
        )
        return base
    except PolicyStateError as exc:
        base["countries"]["US"] = _us_block(
            prior_us,
            error=str(exc),
            as_of_status="current" if any(item.get("status") != "superseded" for item in prior_us) else "unavailable",
        )
        return base
    decisions = _merge_us_decisions(prior_us, decision)
    base["countries"]["US"] = _us_block(decisions, error=None, as_of_status="current")
    return base


def default_fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/xml, text/xml"})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise PolicySourceUnavailable(f"{url} {exc}") from exc
    charset = "utf-8"
    return raw.decode(charset, errors="replace")


def write_policy_state(state: dict[str, Any], root: Path | None = None) -> Path:
    path = policy_state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def refresh_and_write(root: Path | None = None, fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Update the canonical artifact. A failed fetch leaves an existing file unchanged."""
    previous = load_policy_state(root)
    updated = refresh_policy_state(previous, fetch or default_fetch, now)
    us = (updated.get("countries") or {}).get("US") or {}
    if us.get("last_refresh_error") and previous is not None:
        return updated
    write_policy_state(updated, root)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh canonical policy state from official sources")
    parser.add_argument("--refresh", action="store_true", help="Fetch the official FOMC decision and write data/policy_state.json")
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.error("--refresh is required")
    updated = refresh_and_write()
    us = (updated.get("countries") or {}).get("US") or {}
    error = us.get("last_refresh_error")
    if error:
        print(f"policy state refresh kept the previous US record: {error}")
        return 1
    print(f"policy state refreshed {updated.get('updated_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
