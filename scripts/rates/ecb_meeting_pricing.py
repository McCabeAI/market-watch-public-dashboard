"""ECB meeting pricing from CME ESR €STR futures (compound accrual, not equal-step SR1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from scripts.rates.cme_session import latest_publishable_official_session

RateOnDay = Callable[[date], float | None]


def _parse_date(value: str) -> date:
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def _round_rate(value: float) -> float:
    return round(value, 4)


def _round_bp(value: float) -> float:
    return round(value, 2)

ECB_METHOD_NOTE = (
    "CME ESR compound accrual (ACT/360, weekday business days; Friday's rate covers "
    "Saturday/Sunday via di); no TARGET holiday calendar on the accrual path"
)


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _next_weekday(d: date) -> date:
    nxt = d + timedelta(days=1)
    while not _is_weekday(nxt):
        nxt += timedelta(days=1)
    return nxt


def compound_growth(start: date, end: date, rate_on_day: RateOnDay) -> float:
    """Rule 48003-style growth product over [start, end) with weekday business days."""
    if start >= end:
        return 1.0
    growth = 1.0
    d = start
    while d < end:
        if not _is_weekday(d):
            d += timedelta(days=1)
            continue
        rate = rate_on_day(d)
        if rate is None:
            raise ValueError(f"missing €STR rate for accrual day {d.isoformat()}")
        nxt = _next_weekday(d)
        if nxt > end:
            nxt = end
        di = (nxt - d).days
        growth *= 1.0 + (di / 360.0) * (rate / 100.0)
        d = nxt
    return growth


def futures_implied_growth(
    implied_rate_percent: float,
    reference_start: date,
    reference_end: date,
) -> float:
    cal_days = (reference_end - reference_start).days
    return 1.0 + (implied_rate_percent / 100.0) * (cal_days / 360.0)


def _history_map(history: list[tuple[date, float]] | None) -> dict[date, float]:
    if not history:
        return {}
    return {d: r for d, r in history}


def _estr_on_day(
    day: date,
    *,
    as_of: date,
    fixing: float,
    history: dict[date, float],
    meetings: list[dict],
    post_meeting_rate: float | None,
    meeting_eff: date,
) -> float | None:
    if day >= meeting_eff:
        return post_meeting_rate
    if day <= as_of:
        if day in history:
            return history[day]
        return None
    future_inside = [
        _parse_date(str(m["effective_date"]))
        for m in meetings
        if _parse_date(str(m["effective_date"])) > as_of
        and _parse_date(str(m["effective_date"])) <= day
    ]
    if future_inside:
        return None
    return fixing


def _window_calendar_days(reference_start: str, reference_end: str) -> int | None:
    try:
        rs = _parse_date(reference_start)
        re = _parse_date(reference_end)
    except ValueError:
        return None
    return (re - rs).days


def _meetings_in_window(
    meetings: list[dict],
    *,
    as_of: date,
    ref_start: date,
    ref_end: date,
) -> list[tuple[date, dict]]:
    hits: list[tuple[date, dict]] = []
    for m in meetings:
        eff = _parse_date(str(m["effective_date"]))
        if eff <= as_of:
            continue
        if ref_start <= eff < ref_end:
            hits.append((eff, m))
    return hits


def _contract_usable(contract: dict) -> bool:
    for key in ("reference_start", "reference_end", "implied_rate"):
        if contract.get(key) is None:
            return False
    days = _window_calendar_days(
        str(contract["reference_start"]),
        str(contract["reference_end"]),
    )
    if days is None or not (80 <= days <= 100):
        return False
    return True


def _post_day_count(
    *,
    ref_start: date,
    ref_end: date,
    meeting_eff: date,
) -> int:
    start = max(ref_start, meeting_eff)
    if start >= ref_end:
        return 0
    return (ref_end - start).days


def _solve_post_estr(
    *,
    reference_start: date,
    reference_end: date,
    meeting_eff: date,
    as_of: date,
    fixing: float,
    history: dict[date, float],
    meetings: list[dict],
    target_growth: float,
) -> float | None:

    def rate_fn(post: float) -> RateOnDay:
        def inner(day: date) -> float | None:
            return _estr_on_day(
                day,
                as_of=as_of,
                fixing=fixing,
                history=history,
                meetings=meetings,
                post_meeting_rate=post,
                meeting_eff=meeting_eff,
            )

        return inner

    lo, hi = -1.0, 25.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        try:
            g = compound_growth(reference_start, reference_end, rate_fn(mid))
        except ValueError:
            return None
        if abs(g - target_growth) / max(target_growth, 1e-12) < 1e-8:
            return mid
        if g < target_growth:
            lo = mid
        else:
            hi = mid
    mid = (lo + hi) / 2.0
    try:
        g = compound_growth(reference_start, reference_end, rate_fn(mid))
    except ValueError:
        return None
    if abs(g - target_growth) / max(target_growth, 1e-12) < 1e-8:
        return mid
    return None


def _has_official_verified(contracts: list[dict]) -> bool:
    for row in contracts:
        if row.get("mark_kind") == "official_settlement" and row.get("trade_date_verified") is True:
            return True
    return False


def _qualifying_esr_research_strip(
    contracts: list[dict],
    *,
    as_of: date,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """True when contracts carry a latest-publishable official verified ESR mark."""
    if not contracts:
        return False, "ESR strip empty"
    publishable = latest_publishable_official_session(today=as_of, now=now)
    saw_official = False
    for row in contracts:
        kind = str(row.get("mark_kind") or "")
        if kind in {"delayed_quote", "delayed_last"}:
            return False, "ESR strip uses delayed quotes; not official settlement"
        if row.get("trade_date_verified") is False:
            return False, "ESR strip trade date not verified"
        if kind == "official_settlement" and row.get("trade_date_verified") is True:
            saw_official = True
            raw = row.get("observation_date") or row.get("as_of")
            try:
                obs = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if obs == publishable:
                return True, None
    if not saw_official:
        return False, "ESR strip lacks official settlement with verified trade date"
    return (
        False,
        f"ESR strip observation is not the latest publishable session ({publishable.isoformat()})",
    )


def price_ecb_meetings(
    *,
    as_of: date,
    anchor: float | None,
    fixing: float | None,
    history: list[tuple[date, float]] | None,
    meetings: list[dict],
    contracts: list[dict],
    futures_freshness: str,
    now: datetime | None = None,
) -> tuple[list[dict], str | None]:
    future_meetings = sorted(
        [m for m in meetings if _parse_date(m["effective_date"]) > as_of],
        key=lambda m: _parse_date(m["effective_date"]),
    )

    def unavailable_rows(reason: str) -> tuple[list[dict], str]:
        rows: list[dict] = []
        for m in future_meetings:
            rows.append(
                {
                    "decision_date": m["decision_date"],
                    "effective_date": m["effective_date"],
                    "post_rate": None,
                    "incremental_bp": None,
                    "cumulative_bp": None,
                    "method": "unavailable",
                    "contracts": [],
                    "reason": reason,
                }
            )
        return rows, reason

    if futures_freshness == "unavailable":
        rows, bank_reason = unavailable_rows("ESR futures strip not available")
        return rows, bank_reason

    research_ok, research_reason = _qualifying_esr_research_strip(
        contracts, as_of=as_of, now=now
    )
    if not research_ok:
        rows, bank_reason = unavailable_rows(research_reason or "ESR strip not research-eligible")
        return rows, bank_reason

    if futures_freshness not in {"fresh", "stale"}:
        rows, bank_reason = unavailable_rows("ESR futures strip freshness unknown")
        return rows, bank_reason

    if anchor is None or fixing is None:
        rows, bank_reason = unavailable_rows("€STR–deposit-facility basis unavailable")
        return rows, bank_reason

    basis = fixing - anchor
    hist = _history_map(history)

    candidates: dict[str, list[tuple[int, float, dict]]] = {}
    for contract in contracts:
        if not _contract_usable(contract):
            continue
        ref_start = _parse_date(str(contract["reference_start"]))
        ref_end = _parse_date(str(contract["reference_end"]))
        in_window = _meetings_in_window(
            future_meetings,
            as_of=as_of,
            ref_start=ref_start,
            ref_end=ref_end,
        )
        if len(in_window) != 1:
            continue
        eff, meeting = in_window[0]
        post_days = _post_day_count(
            ref_start=ref_start,
            ref_end=ref_end,
            meeting_eff=eff,
        )
        if post_days <= 0:
            continue

        implied = float(contract["implied_rate"])
        target_g = futures_implied_growth(implied, ref_start, ref_end)
        post_estr = _solve_post_estr(
            reference_start=ref_start,
            reference_end=ref_end,
            meeting_eff=eff,
            as_of=as_of,
            fixing=fixing,
            history=hist,
            meetings=future_meetings,
            target_growth=target_g,
        )
        if post_estr is None:
            continue
        policy_post = post_estr - basis
        oi = float(contract.get("open_interest") or 0)
        dec = meeting["decision_date"]
        candidates.setdefault(dec, []).append((post_days, oi, contract, policy_post, meeting))

    identified: dict[str, dict] = {}
    for dec, group in candidates.items():
        group.sort(key=lambda item: (item[0], -item[1]))
        post_days, _oi, contract, policy_post, meeting = group[0]
        identified[dec] = {
            "meeting": meeting,
            "policy_post": policy_post,
            "contract": contract,
        }

    rows: list[dict] = []
    previous_post: float | None = None
    for m in future_meetings:
        dec = m["decision_date"]
        if dec in identified:
            info = identified[dec]
            post = _round_rate(info["policy_post"])
            base = previous_post if previous_post is not None else anchor
            incr = _round_bp((post - base) * 100.0)
            cum = _round_bp((post - anchor) * 100.0)
            c = info["contract"]
            rows.append(
                {
                    "decision_date": m["decision_date"],
                    "effective_date": m["effective_date"],
                    "post_rate": post,
                    "incremental_bp": incr,
                    "cumulative_bp": cum,
                    "method": "identified",
                    "contracts": [
                        {
                            "product": "ESR",
                            "expiry": c.get("expiry"),
                            "code": c.get("code"),
                            "weight": 1.0,
                            "reference_start": c.get("reference_start"),
                            "reference_end": c.get("reference_end"),
                        }
                    ],
                }
            )
            previous_post = post
        else:
            rows.append(
                {
                    "decision_date": m["decision_date"],
                    "effective_date": m["effective_date"],
                    "post_rate": None,
                    "incremental_bp": None,
                    "cumulative_bp": None,
                    "method": "unavailable",
                    "contracts": [],
                    "reason": "ESR contract window does not uniquely identify meeting",
                }
            )

    if not identified:
        return rows, "ESR quarterly windows do not identify ECB meetings"
    if all(r["method"] == "identified" for r in rows):
        return rows, None
    if any(r["method"] == "identified" for r in rows):
        return rows, None
    return rows, "ESR quarterly windows do not identify ECB meetings"
