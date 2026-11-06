"""Policy meeting implied rates from short-rate futures windows."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.policy_state import resolve_country

BANK_CODES = ("US", "CA", "AU", "NZ", "EA", "JP")
CONSTRUCTION_VERSION = "policy_meeting_v1"
SCHEMA_VERSION = 1
HISTORY_PATH = Path("data") / "policy_meeting_history.json"
HISTORY_MAX_SESSIONS = 10


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _third_wednesday(year: int, month: int) -> date:
    count = 0
    for day in range(1, monthrange(year, month)[1] + 1):
        if date(year, month, day).weekday() == 2:
            count += 1
            if count == 3:
                return date(year, month, day)
    raise ValueError(f"no third Wednesday in {year}-{month:02d}")


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, (total % 12) + 1


def accrual_window(expiry: str, period: str) -> tuple[date, date]:
    """Return [start, end) for a futures accrual window."""
    year_s, month_s = expiry.split("-")
    year, month = int(year_s), int(month_s)
    if period == "1m":
        start = date(year, month, 1)
        end_y, end_m = _add_months(year, month, 1)
        end = date(end_y, end_m, 1)
        return start, end
    if period == "3m":
        start = _third_wednesday(year, month)
        end_y, end_m = _add_months(year, month, 3)
        end = _third_wednesday(end_y, end_m)
        return start, end
    raise ValueError(f"unsupported period {period!r}")


def _iter_days(start: date, end: date):
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def _policy_on_day(
    day: date,
    anchor: float,
    history: list[tuple[date, float]],
    solved: list[tuple[date, float]],
) -> float | None:
    rate = anchor
    for eff, post in sorted(history, key=lambda item: item[0]):
        if eff <= day:
            rate = post
        else:
            break
    for eff, post in sorted(solved, key=lambda item: item[0]):
        if eff <= day:
            rate = post
        else:
            break
    return rate


def _is_known_on_day(
    day: date,
    as_of: date,
    anchor: float,
    history: list[tuple[date, float]],
    solved: list[tuple[date, float]],
    meetings: list[dict],
) -> bool:
    if day <= as_of:
        for meeting in meetings:
            eff = _parse_date(meeting["effective_date"])
            if eff <= day and eff <= as_of:
                if not any(h[0] == eff for h in history):
                    return False
        return _policy_on_day(day, anchor, history, solved) is not None
    return True


def _meeting_known(
    meeting: dict,
    as_of: date,
    history: list[tuple[date, float]],
) -> bool:
    eff = _parse_date(meeting["effective_date"])
    if eff > as_of:
        return False
    return any(h[0] == eff for h in history)


def _round_rate(value: float) -> float:
    return round(value, 4)


def _round_bp(value: float) -> float:
    return round(value, 2)


def price_meetings(
    *,
    bank: str,
    as_of: date,
    anchor: float,
    basis: float,
    meetings: list[dict],
    contracts: list[dict],
    history: list[tuple[date, float]] | None = None,
) -> list[dict]:
    history = list(history or [])
    sorted_meetings = sorted(meetings, key=lambda m: _parse_date(m["effective_date"]))
    unresolved = [m for m in sorted_meetings if _parse_date(m["effective_date"]) > as_of]

    rows: list[dict] = []
    solved: list[tuple[date, float]] = []
    previous_post: float | None = None

    def emit_unavailable(from_idx: int) -> None:
        for meeting in unresolved[from_idx:]:
            rows.append(_row(meeting, None, None, None, "unavailable", []))

    def _row(
        meeting: dict,
        post: float | None,
        incremental: float | None,
        cumulative: float | None,
        method: str,
        contracts_used: list[dict],
    ) -> dict:
        return {
            "decision_date": meeting["decision_date"],
            "effective_date": meeting["effective_date"],
            "post_rate": _round_rate(post) if post is not None else None,
            "incremental_bp": _round_bp(incremental) if incremental is not None else None,
            "cumulative_bp": _round_bp(cumulative) if cumulative is not None else None,
            "method": method,
            "contracts": contracts_used,
        }

    def incremental_for(post: float) -> float:
        nonlocal previous_post
        base = previous_post if previous_post is not None else anchor
        inc = (post - base) * 100.0
        previous_post = post
        return inc

    idx = 0
    while idx < len(unresolved):
        meeting = unresolved[idx]
        k_eff = _parse_date(meeting["effective_date"])
        next_eff = (
            _parse_date(unresolved[idx + 1]["effective_date"])
            if idx + 1 < len(unresolved)
            else date.max
        )

        contract_rows: list[tuple[dict, date, date, int, date]] = []
        for contract in contracts:
            start, end = accrual_window(contract["expiry"], contract["period"])
            eligible = True
            unknown_days = 0
            for day in _iter_days(start, end):
                if day <= as_of and not _is_known_on_day(
                    day, as_of, anchor, history, solved, sorted_meetings
                ):
                    eligible = False
                    break
                if day < k_eff:
                    continue
                if next_eff is not date.max and day >= next_eff:
                    eligible = False
                    break
                unknown_days += 1
            if not eligible or unknown_days < 7:
                continue
            contract_rows.append((contract, start, end, unknown_days, start))

        contract_rows.sort(
            key=lambda item: (
                0 if item[0]["period"] == "1m" else 1,
                -item[3],
                item[4],
            )
        )

        if contract_rows:
            contract, start, end, _, _ = contract_rows[0]
            total = 0.0
            known_sum = 0.0
            unknown_count = 0
            for day in _iter_days(start, end):
                total += 1
                if day >= k_eff and (next_eff is date.max or day < next_eff):
                    unknown_count += 1
                else:
                    pol = _policy_on_day(day, anchor, history, solved)
                    assert pol is not None
                    known_sum += pol
            f = float(contract["implied_rate"])
            x = (total * (f - basis) - known_sum) / unknown_count
            inc = incremental_for(x)
            cum = (x - anchor) * 100.0
            solved.append((k_eff, x))
            rows.append(
                _row(
                    meeting,
                    x,
                    inc,
                    cum,
                    "identified",
                    [
                        {
                            "product": contract["product"],
                            "expiry": contract["expiry"],
                            "weight": 1.0,
                        }
                    ],
                )
            )
            idx += 1
            continue

        # equal_step
        candidates: list[tuple[date, int, dict, date, date]] = []
        for contract in contracts:
            start, end = accrual_window(contract["expiry"], contract["period"])
            days_after = sum(1 for day in _iter_days(start, end) if day >= k_eff)
            if days_after < 7:
                continue
            skip = False
            for day in _iter_days(start, end):
                if day <= as_of and not _is_known_on_day(
                    day, as_of, anchor, history, solved, sorted_meetings
                ):
                    skip = True
                    break
            if skip:
                continue
            period_rank = 0 if contract["period"] == "1m" else 1
            candidates.append((end, period_rank, contract, start, end))

        if not candidates:
            emit_unavailable(idx)
            break

        candidates.sort(key=lambda item: (item[0], item[1]))
        _, _, contract, start, end = candidates[0]
        group: list[dict] = []
        for m in unresolved[idx:]:
            eff = _parse_date(m["effective_date"])
            if eff < end:
                group.append(m)
            elif eff >= end:
                break
        if not group:
            emit_unavailable(idx)
            break

        first_eff = _parse_date(group[0]["effective_date"])
        pre = _policy_on_day(first_eff - timedelta(days=1), anchor, history, solved)
        if pre is None:
            pre = anchor

        total = 0.0
        sum_base = 0.0
        sum_m = 0.0
        group_effs = [_parse_date(m["effective_date"]) for m in group]
        for day in _iter_days(start, end):
            if day < first_eff:
                pol = _policy_on_day(day, anchor, history, solved)
                assert pol is not None
                base_d = pol
            else:
                base_d = pre
            m_d = sum(1 for eff in group_effs if eff <= day)
            total += 1
            sum_base += base_d
            sum_m += m_d

        f = float(contract["implied_rate"])
        if sum_m == 0:
            emit_unavailable(idx)
            break
        step = (total * (f - basis) - sum_base) / sum_m

        contract_used = [
            {
                "product": contract["product"],
                "expiry": contract["expiry"],
                "weight": 1.0,
            }
        ]
        for i, gm in enumerate(group):
            post = pre + (i + 1) * step
            eff = _parse_date(gm["effective_date"])
            solved.append((eff, post))
            inc = incremental_for(post)
            cum = (post - anchor) * 100.0
            rows.append(_row(gm, post, inc, cum, "equal_step", contract_used))
        idx += len(group)

    return rows


def _anchor_from_policy(policy_state: dict | None, code: str, as_of: date) -> float | None:
    resolved = resolve_country(policy_state, code, as_of)
    if resolved.get("status") != "current":
        return None
    decision = resolved.get("decision") or {}
    if code == "US":
        lower = decision.get("lower")
        upper = decision.get("upper")
        if lower is None or upper is None:
            return None
        return (float(lower) + float(upper)) / 2.0
    rate = decision.get("rate")
    if rate is None:
        return None
    return float(rate)


def _history_from_policy(
    policy_state: dict | None, code: str, as_of: date
) -> list[tuple[date, float]]:
    if not policy_state or not isinstance(policy_state.get("countries"), dict):
        return []
    block = policy_state["countries"].get(code) or {}
    steps: list[tuple[date, float]] = []
    for item in block.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        eff_s = item.get("effective_date")
        if not eff_s:
            continue
        eff = _parse_date(eff_s)
        if eff > as_of:
            continue
        if code == "US":
            lower = item.get("lower")
            upper = item.get("upper")
            if lower is None or upper is None:
                continue
            rate = (float(lower) + float(upper)) / 2.0
        else:
            if item.get("rate") is None:
                continue
            rate = float(item["rate"])
        steps.append((eff, rate))
    steps.sort(key=lambda pair: pair[0])
    return steps


def _contracts_for_bank(
    code: str,
    country_paths: dict,
    *,
    paths_ok: bool,
) -> tuple[list[dict], str | None]:
    contracts: list[dict] = []
    if code == "US":
        for row in country_paths.get("contracts_1m") or []:
            contracts.append(
                {
                    "product": "SR1",
                    "expiry": row["expiry"],
                    "period": "1m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        for row in country_paths.get("contracts_3m") or []:
            contracts.append(
                {
                    "product": "SR3",
                    "expiry": row["expiry"],
                    "period": "3m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        return contracts, None
    if code == "CA":
        for row in country_paths.get("contracts_1m") or []:
            contracts.append(
                {
                    "product": "COA",
                    "expiry": row["expiry"],
                    "period": "1m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        for row in country_paths.get("contracts_3m") or []:
            contracts.append(
                {
                    "product": "CRA",
                    "expiry": row["expiry"],
                    "period": "3m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        return contracts, None
    if code == "AU":
        for row in country_paths.get("contracts_1m") or []:
            contracts.append(
                {
                    "product": "IB",
                    "expiry": row["expiry"],
                    "period": "1m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        return contracts, None
    if code == "JP":
        if not paths_ok:
            return [], "Policy paths unavailable"
        for row in country_paths.get("contracts_3m") or []:
            contracts.append(
                {
                    "product": "TOA3M",
                    "expiry": row["expiry"],
                    "period": "3m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        return contracts, None
    if code == "EA":
        rows = country_paths.get("contracts_3m") or []
        if not rows:
            return [], "FST3 is absent"
        for row in rows:
            contracts.append(
                {
                    "product": "FST3",
                    "expiry": row["expiry"],
                    "period": "3m",
                    "implied_rate": float(row["implied_rate"]),
                }
            )
        return contracts, None
    if code == "NZ":
        return [], "No NZD short-rate futures strip"
    return [], "unsupported bank"


def _calendar_meetings(calendar: dict, code: str) -> list[dict]:
    banks = calendar.get("banks") or {}
    block = banks.get(code) or {}
    out: list[dict] = []
    for item in block.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("decision_date") or not item.get("effective_date"):
            continue
        out.append(
            {
                "decision_date": str(item["decision_date"]),
                "effective_date": str(item["effective_date"]),
            }
        )
    out.sort(key=lambda m: _parse_date(m["effective_date"]))
    return out


def _lookup_history_changes(
    history_doc: dict | None,
    as_of: date,
    bank: str,
    decision_date: str,
    current_cumulative: float | None,
) -> tuple[float | None, float | None]:
    if history_doc is None or current_cumulative is None:
        return None, None
    sessions = sorted(
        [
            (key, block)
            for key, block in (history_doc.get("sessions") or {}).items()
            if isinstance(block, dict)
        ],
        key=lambda item: item[0],
    )
    chg_1d: float | None = None
    chg_1w: float | None = None
    as_of_s = as_of.isoformat()
    prior_sessions = [s for s in sessions if s[0] < as_of_s]
    if prior_sessions:
        _, block = prior_sessions[-1]
        row = ((block.get(bank) or {}).get(decision_date)) or {}
        if row.get("cumulative_bp") is not None:
            chg_1d = _round_bp(current_cumulative - float(row["cumulative_bp"]))
    week_cutoff = (as_of - timedelta(days=7)).isoformat()
    week_candidates = [s for s in sessions if s[0] <= week_cutoff]
    if week_candidates:
        _, block = week_candidates[-1]
        row = ((block.get(bank) or {}).get(decision_date)) or {}
        if row.get("cumulative_bp") is not None:
            chg_1w = _round_bp(current_cumulative - float(row["cumulative_bp"]))
    return chg_1d, chg_1w


def _overnight_fixing(country_paths: dict, as_of: date) -> float | None:
    benchmark = country_paths.get("benchmark") or {}
    if not isinstance(benchmark, dict):
        return None
    if str(benchmark.get("status") or "") == "unavailable":
        return None
    if benchmark.get("rate") is None:
        return None
    as_of_raw = benchmark.get("as_of")
    if as_of_raw not in (None, ""):
        try:
            bench_day = _parse_date(str(as_of_raw))
            if (as_of - bench_day).days > 21:
                return None
        except ValueError:
            pass
    return float(benchmark["rate"])


def _filter_contracts(contracts: list[dict], as_of: date) -> list[dict]:
    as_of_ym = (as_of.year, as_of.month)
    kept: list[dict] = []
    for row in contracts:
        if row.get("implied_rate") is None:
            continue
        expiry = str(row.get("expiry") or "")
        if len(expiry) != 7 or expiry[4] != "-":
            continue
        try:
            year = int(expiry[:4])
            month = int(expiry[5:7])
        except ValueError:
            continue
        if (year, month) < as_of_ym:
            continue
        kept.append(row)
    return kept


def _unavailable_meeting_rows_for_bank(code: str, meetings_cal: list[dict], as_of: date) -> list[dict]:
    rows: list[dict] = []
    for meeting in meetings_cal:
        if _parse_date(meeting["effective_date"]) <= as_of:
            continue
        decision_date = meeting["decision_date"]
        rows.append(
            {
                "instrument_id": f"PM:{code}:{decision_date}",
                "decision_date": decision_date,
                "effective_date": meeting["effective_date"],
                "post_rate": None,
                "incremental_bp": None,
                "cumulative_bp": None,
                "method": "unavailable",
                "contracts": [],
                "chg_1d_bp": None,
                "chg_1w_bp": None,
            }
        )
    return rows


def build_policy_meeting_prices(
    *,
    as_of: date,
    calendar: dict,
    policy_state: dict,
    policy_paths: dict,
    history_doc: dict | None = None,
) -> dict:
    countries = (policy_paths or {}).get("countries") or {}
    banks_out: dict[str, Any] = {}
    for code in BANK_CODES:
        meetings_cal = _calendar_meetings(calendar, code)
        anchor = _anchor_from_policy(policy_state, code, as_of)
        country_paths = countries.get(code) or {}
        paths_status = str(country_paths.get("status") or "")
        paths_ok = paths_status == "ok"
        contract_list, contract_reason = _contracts_for_bank(
            code, country_paths, paths_ok=paths_ok
        )
        if paths_status == "unavailable":
            contract_list = []

        contract_list = _filter_contracts(contract_list, as_of)

        fixing = _overnight_fixing(country_paths, as_of)

        basis_bp: float | None = None
        basis = 0.0
        if anchor is not None and fixing is not None:
            basis = fixing - anchor
            basis_bp = _round_bp(basis * 100.0)

        futures_as_of = country_paths.get("futures_as_of") or policy_paths.get("as_of")
        cal_block = (calendar.get("banks") or {}).get(code) or {}
        calendar_retrieved_at = cal_block.get("retrieved_at")

        if code == "NZ":
            status = "unavailable"
            reason = contract_reason
            meeting_rows: list[dict] = []
            for m in meetings_cal:
                if _parse_date(m["effective_date"]) > as_of:
                    meeting_rows.append(
                        {
                            "instrument_id": f"PM:{code}:{m['decision_date']}",
                            "decision_date": m["decision_date"],
                            "effective_date": m["effective_date"],
                            "post_rate": None,
                            "incremental_bp": None,
                            "cumulative_bp": None,
                            "method": "unavailable",
                            "contracts": [],
                            "chg_1d_bp": None,
                            "chg_1w_bp": None,
                        }
                    )
            banks_out[code] = {
                "status": status,
                "reason": reason,
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": meeting_rows,
            }
            continue

        if contract_reason == "FST3 is absent":
            status = "unavailable"
            reason = contract_reason
            priced: list[dict] = []
            for m in meetings_cal:
                if _parse_date(m["effective_date"]) > as_of:
                    priced.append(
                        {
                            "instrument_id": f"PM:{code}:{m['decision_date']}",
                            "decision_date": m["decision_date"],
                            "effective_date": m["effective_date"],
                            "post_rate": None,
                            "incremental_bp": None,
                            "cumulative_bp": None,
                            "method": "unavailable",
                            "contracts": [],
                            "chg_1d_bp": None,
                            "chg_1w_bp": None,
                        }
                    )
            banks_out[code] = {
                "status": status,
                "reason": reason,
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": priced,
            }
            continue

        if anchor is None:
            status = "unavailable"
            reason = "No policy anchor"
            priced = []
            for m in meetings_cal:
                if _parse_date(m["effective_date"]) > as_of:
                    priced.append(
                        {
                            "instrument_id": f"PM:{code}:{m['decision_date']}",
                            "decision_date": m["decision_date"],
                            "effective_date": m["effective_date"],
                            "post_rate": None,
                            "incremental_bp": None,
                            "cumulative_bp": None,
                            "method": "unavailable",
                            "contracts": [],
                            "chg_1d_bp": None,
                            "chg_1w_bp": None,
                        }
                    )
            banks_out[code] = {
                "status": status,
                "reason": reason,
                "anchor": None,
                "fixing": fixing,
                "basis_bp": None,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": priced,
            }
            continue

        if fixing is None:
            banks_out[code] = {
                "status": "unavailable",
                "reason": "No overnight fixing",
                "anchor": anchor,
                "fixing": None,
                "basis_bp": None,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": _unavailable_meeting_rows_for_bank(code, meetings_cal, as_of),
            }
            continue

        if not contract_list:
            banks_out[code] = {
                "status": "unavailable",
                "reason": contract_reason or "No contracts",
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": _unavailable_meeting_rows_for_bank(code, meetings_cal, as_of),
            }
            continue

        status = "ok"
        reason = None

        hist = _history_from_policy(policy_state, code, as_of)
        try:
            priced_rows = price_meetings(
                bank=code,
                as_of=as_of,
                anchor=anchor,
                basis=basis,
                meetings=meetings_cal,
                contracts=contract_list,
                history=hist,
            )
        except Exception as exc:
            banks_out[code] = {
                "status": "unavailable",
                "reason": str(exc),
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": [],
            }
            continue

        meetings_out: list[dict] = []
        for row in priced_rows:
            chg_1d, chg_1w = _lookup_history_changes(
                history_doc,
                as_of,
                code,
                row["decision_date"],
                row.get("cumulative_bp"),
            )
            meetings_out.append(
                {
                    "instrument_id": f"PM:{code}:{row['decision_date']}",
                    "decision_date": row["decision_date"],
                    "effective_date": row["effective_date"],
                    "post_rate": row["post_rate"],
                    "incremental_bp": row["incremental_bp"],
                    "cumulative_bp": row["cumulative_bp"],
                    "method": row["method"],
                    "contracts": row["contracts"],
                    "chg_1d_bp": chg_1d,
                    "chg_1w_bp": chg_1w,
                }
            )

        if status != "ok" and meetings_out:
            for row in meetings_out:
                if row["method"] != "unavailable":
                    status = "partial"
                    reason = None
                    break

        banks_out[code] = {
            "status": status,
            "reason": reason,
            "anchor": anchor,
            "fixing": fixing,
            "basis_bp": basis_bp,
            "futures_as_of": futures_as_of,
            "calendar_retrieved_at": calendar_retrieved_at,
            "meetings": meetings_out,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "construction_version": CONSTRUCTION_VERSION,
        "as_of": as_of.isoformat(),
        "banks": banks_out,
    }


def quote_for_expression(
    block: dict,
    expression: dict,
    stored: dict | None = None,
) -> dict:
    stored = stored or {}
    kind = expression.get("kind")
    if expression.get("type") != "policy_meeting":
        raise ValueError("expression type must be policy_meeting")

    def meeting_row(bank: str, decision_date: str) -> dict:
        for row in (block.get("meetings") or []):
            if row.get("decision_date") == decision_date:
                return row
        for row in (block.get("meetings") or []):
            if decision_date in str(row.get("instrument_id", "")):
                return row
        raise ValueError(f"missing meeting {bank}:{decision_date}")

    anchor = block.get("anchor")
    if kind == "meeting":
        bank = expression["bank"]
        decision_date = expression["decision_dates"][0]
        row = meeting_row(bank, decision_date)
        if row.get("method") == "unavailable" or row.get("post_rate") is None:
            raise ValueError("meeting unavailable")
        return {
            "value": row["post_rate"],
            "quote_unit": "percent",
            "method": row["method"],
            "source": row.get("instrument_id"),
        }

    if kind == "cumulative":
        bank = expression["bank"]
        decision_date = expression["decision_dates"][0]
        row = meeting_row(bank, decision_date)
        if row.get("method") == "unavailable" or row.get("post_rate") is None:
            raise ValueError("meeting unavailable")
        base = stored.get("base_rate")
        if base is None:
            if anchor is None:
                raise ValueError("missing anchor")
            base = anchor
        value = (float(row["post_rate"]) - float(base)) * 100.0
        return {
            "value": _round_bp(value),
            "quote_unit": "bp",
            "method": row["method"],
            "source": row.get("instrument_id"),
        }

    if kind == "calendar_spread":
        bank = expression["bank"]
        d0, d1 = expression["decision_dates"]
        row0 = meeting_row(bank, d0)
        row1 = meeting_row(bank, d1)
        for row in (row0, row1):
            if row.get("method") == "unavailable" or row.get("post_rate") is None:
                raise ValueError("meeting unavailable")
        value = (float(row1["post_rate"]) - float(row0["post_rate"])) * 100.0
        return {
            "value": _round_bp(value),
            "quote_unit": "bp",
            "method": row1["method"],
            "source": f"{row0.get('instrument_id')}:{row1.get('instrument_id')}",
        }

    if kind == "cross_country":
        bank_a, bank_b = expression["banks"]
        d_a, d_b = expression["decision_dates"]
        row_a = meeting_row(bank_a, d_a)
        peer = stored.get("peer_block") or {}
        row_b = None
        for row in peer.get("meetings") or []:
            if row.get("decision_date") == d_b:
                row_b = row
                break
        if row_b is None:
            raise ValueError(f"missing meeting {bank_b}:{d_b}")
        for row in (row_a, row_b):
            if row.get("method") == "unavailable" or row.get("post_rate") is None:
                raise ValueError("meeting unavailable")
        bases = stored.get("bases") or {}
        base_a = bases.get(bank_a, block.get("anchor"))
        base_b = bases.get(bank_b, peer.get("anchor"))
        cum_a = (float(row_a["post_rate"]) - float(base_a)) * 100.0
        cum_b = (float(row_b["post_rate"]) - float(base_b)) * 100.0
        return {
            "value": _round_bp(cum_a - cum_b),
            "quote_unit": "bp",
            "method": row_a["method"],
            "source": f"{row_a.get('instrument_id')}:{row_b.get('instrument_id')}",
        }

    raise ValueError(f"unsupported kind {kind!r}")


def load_history(root: Path | str) -> dict:
    path = Path(root) / HISTORY_PATH
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "sessions": {}}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def append_history(root: Path | str, as_of: date, block: dict) -> dict:
    doc = load_history(root)
    sessions: dict[str, Any] = dict(doc.get("sessions") or {})
    as_of_key = as_of.isoformat()
    session_block: dict[str, Any] = dict(sessions.get(as_of_key) or {})
    for code, bank_block in (block.get("banks") or {}).items():
        bank_out: dict[str, Any] = dict(session_block.get(str(code)) or {})
        for row in bank_block.get("meetings") or []:
            decision_date = row.get("decision_date")
            if not decision_date:
                continue
            if row.get("post_rate") is None and row.get("method") == "unavailable":
                continue
            bank_out[str(decision_date)] = {
                "post_rate": row.get("post_rate"),
                "cumulative_bp": row.get("cumulative_bp"),
                "method": row.get("method"),
            }
        if bank_out:
            session_block[str(code)] = bank_out
    sessions[as_of_key] = session_block
    ordered = sorted(sessions.keys())
    if len(ordered) > HISTORY_MAX_SESSIONS:
        for old in ordered[: len(ordered) - HISTORY_MAX_SESSIONS]:
            del sessions[old]
    doc["schema_version"] = SCHEMA_VERSION
    doc["sessions"] = sessions
    doc["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = Path(root) / HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
        handle.write("\n")
    return doc
