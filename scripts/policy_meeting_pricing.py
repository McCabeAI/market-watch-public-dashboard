"""Policy meeting implied rates from short-rate futures windows."""

from __future__ import annotations

import json
import math
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


US_SR1_STEP_MEANING = (
    "SR1 step is the implied SOFR change versus the pre-meeting forward baseline. "
    "It is not the monthly-average gap, the spot SOFR fixing, or the Fed target lower bound."
)

CA_COA_STEP_MEANING = (
    "COA/CRA step is the change in overnight CORRA from the compounded futures curve. "
    "It is not an arithmetic monthly average, the spot CORRA fixing, or the BoC target."
)

AU_IB_STEP_MEANING = (
    "IB step is the change in the interbank overnight cash rate versus the prior-month forward average. "
    "It is not the RBA cash-rate target or the spot AONIA fixing."
)


def _easter_sunday_western(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _boc_statutory_holidays(year: int) -> list[date]:
    """Calendar dates of statutory holidays (before weekend substitution)."""
    easter = _easter_sunday_western(year)
    gf = easter - timedelta(days=2)
    # Victoria Day: Monday on or before May 24.
    may24 = date(year, 5, 24)
    victoria = may24 - timedelta(days=may24.weekday())
    labour = date(year, 9, 1)
    while labour.weekday() != 0:
        labour += timedelta(days=1)
    thanks = date(year, 10, 1)
    while thanks.weekday() != 0:
        thanks += timedelta(days=1)
    thanks += timedelta(days=7)
    return [
        date(year, 1, 1),
        gf,
        victoria,
        date(year, 7, 1),
        labour,
        date(year, 9, 30),
        thanks,
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    ]


def _boc_weekend_substitute(h: date) -> date:
    if h.weekday() == 5:
        return h - timedelta(days=1)
    if h.weekday() == 6:
        return h + timedelta(days=1)
    return h


def _boc_observed_nonbusiness_days(year: int) -> set[date]:
    """Dates that are non-business due to a statutory holiday (after substitution rules)."""
    out: set[date] = set()
    holidays = _boc_statutory_holidays(year)
    christmas = date(year, 12, 25)
    boxing = date(year, 12, 26)
    for h in holidays:
        if h == boxing and christmas.weekday() == 4:
            out.add(date(year, 12, 28))
            continue
        out.add(_boc_weekend_substitute(h))
    return out


def boc_business_day(d: date) -> bool:
    """True when d is a Bank of Canada business day.

    Weekends plus observed New Year's Day, Good Friday, Victoria Day, Canada Day,
    Labour Day (first Monday of September), National Day for Truth and Reconciliation,
    Thanksgiving (second Monday of October), Remembrance Day, Christmas, Boxing Day.
    Observance: Saturday→Friday and Sunday→Monday; when Christmas is Friday, Boxing Day is
    observed the following Monday (e.g. 2026-12-28), not on Saturday.
    """
    if d.weekday() >= 5:
        return False
    observed: set[date] = set()
    for y in (d.year - 1, d.year, d.year + 1):
        observed |= _boc_observed_nonbusiness_days(y)
    return d not in observed


def _first_boc_business_day_of_month(year: int, month: int) -> date:
    cur = date(year, month, 1)
    while not boc_business_day(cur):
        cur += timedelta(days=1)
    return cur


def coa_accrual_window(expiry: str) -> tuple[date, date]:
    """COA [start, end): first BoC business day of month through first BoC B.D. of next month, exclusive."""
    year_s, month_s = expiry.split("-")
    y, m = int(year_s), int(month_s)
    ny, nm = _add_months(y, m, 1)
    start = _first_boc_business_day_of_month(y, m)
    end = _first_boc_business_day_of_month(ny, nm)
    return start, end


def _coa_business_days_in_window(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur < end:
        if boc_business_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _coa_segment_weights(start: date, end: date) -> list[tuple[date, int]]:
    """(business_day_start, n_calendar_days) for COA compounding; end is exclusive."""
    bds = _coa_business_days_in_window(start, end)
    if not bds:
        return []
    segs: list[tuple[date, int]] = []
    for i, bd in enumerate(bds):
        n_i = (bds[i + 1] - bd).days if i + 1 < len(bds) else (end - bd).days
        segs.append((bd, n_i))
    return segs


def _pct_to_dec(c_pct: float) -> float:
    return c_pct / 100.0


def _coa_compound_factor_flat(
    start: date,
    end: date,
    overnight_pct: float,
) -> float:
    dec = _pct_to_dec(overnight_pct)
    prod = 1.0
    for _bd, n_i in _coa_segment_weights(start, end):
        prod *= 1.0 + dec * n_i / 365.0
    return prod


def coa_implied_percent_from_flat_overnight(start: date, end: date, overnight_pct: float) -> float:
    """Quoted implied R (percent) from constant overnight CORRA (percent), compounded BoC-segment ACT/365."""
    d_cal = (end - start).days
    if d_cal <= 0:
        raise ValueError("invalid COA window")
    prod = _coa_compound_factor_flat(start, end, overnight_pct)
    r_dec = (prod - 1.0) * 365.0 / float(d_cal)
    return r_dec * 100.0


def _bisect_generic(
    fn: Any,
    target: float,
    lo: float,
    hi: float,
    *,
    tol: float = 1e-10,
    expand_rounds: int = 80,
) -> float:
    def err(x: float) -> float:
        return float(fn(x)) - target

    e_lo, e_hi = err(lo), err(hi)
    er = 0
    while e_lo * e_hi > 0 and er < expand_rounds:
        lo -= 2.0
        hi += 2.0
        e_lo, e_hi = err(lo), err(hi)
        er += 1
    if e_lo * e_hi > 0:
        raise ValueError("bisection bracket failed")
    a, b = lo, hi
    for _ in range(200):
        mid = (a + b) / 2.0
        fm = err(mid)
        if abs(fm) < tol:
            return mid
        if err(a) * fm <= 0:
            b = mid
        else:
            a = mid
    return (a + b) / 2.0


def _bisect_solve_coa_flat(implied_target_pct: float, start: date, end: date) -> float:
    return _bisect_generic(
        lambda c: coa_implied_percent_from_flat_overnight(start, end, c),
        implied_target_pct,
        -5.0,
        50.0,
    )


def _split_segment_at_effective(bd: date, n_i: int, k_eff: date) -> list[tuple[int, str]]:
    """(n_days, 'pre'|'post') within one COA segment; calendar days."""
    out: list[tuple[int, str]] = []
    d = bd
    for _ in range(n_i):
        phase = "post" if d >= k_eff else "pre"
        if out and out[-1][1] == phase:
            out[-1] = (out[-1][0] + 1, phase)
        else:
            out.append((1, phase))
        d += timedelta(days=1)
    return out


def _coa_compound_product_pre_post(
    start: date,
    end: date,
    k_eff: date,
    pre_pct: float,
    post_pct: float,
) -> float:
    pre_d = _pct_to_dec(pre_pct)
    post_d = _pct_to_dec(post_pct)
    prod = 1.0
    for bd, n_i in _coa_segment_weights(start, end):
        for n_sub, phase in _split_segment_at_effective(bd, n_i, k_eff):
            r = pre_d if phase == "pre" else post_d
            prod *= 1.0 + r * n_sub / 365.0
    return prod


def coa_implied_percent_pre_post(
    start: date,
    end: date,
    k_eff: date,
    pre_pct: float,
    post_pct: float,
) -> float:
    d_cal = (end - start).days
    prod = _coa_compound_product_pre_post(start, end, k_eff, pre_pct, post_pct)
    r_dec = (prod - 1.0) * 365.0 / float(d_cal)
    return r_dec * 100.0


def _solve_coa_post_overnight(
    implied_target_pct: float,
    start: date,
    end: date,
    k_eff: date,
    pre_pct: float,
) -> float:
    return _bisect_generic(
        lambda post: coa_implied_percent_pre_post(start, end, k_eff, pre_pct, post),
        implied_target_pct,
        -5.0,
        50.0,
    )


def _coa_implied_percent_daily_piecewise(
    start: date,
    end: date,
    *,
    k_eff: date | None,
    observation_date: date | None,
    fixings_sorted: list[tuple[date, float]],
    pre_pct: float,
    post_pct: float | None,
) -> float:
    """Calendar-day ACT/365 compounding (same n_i=1 pattern as SR1 fixing strip)."""
    d_cal = (end - start).days
    if d_cal <= 0:
        raise ValueError("invalid window")
    prod = 1.0
    for d in _iter_calendar_days(start, end):
        if observation_date is not None and d < observation_date:
            r_pct = _sofr_print_for_elapsed_day(d, observation_date, fixings_sorted)
            if r_pct is None:
                raise ValueError("gap in CORRA fixings strip")
        elif k_eff is not None and d >= k_eff:
            if post_pct is None:
                raise ValueError("missing post overnight")
            r_pct = post_pct
        else:
            r_pct = pre_pct
        prod *= 1.0 + _pct_to_dec(float(r_pct)) / 365.0
    r_dec = (prod - 1.0) * 365.0 / float(d_cal)
    return r_dec * 100.0


def _solve_coa_overnight_month_strip(
    implied_target_pct: float,
    start: date,
    end: date,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
) -> float:
    """Constant forward overnight (percent) on D>=observation so implied matches the quote."""

    def err(g: float) -> float:
        return (
            _coa_implied_percent_daily_piecewise(
                start,
                end,
                k_eff=None,
                observation_date=observation_date,
                fixings_sorted=fixings_sorted,
                pre_pct=g,
                post_pct=None,
            )
            - implied_target_pct
        )

    return _bisect_generic(err, 0.0, -2.0, 50.0)


def _solve_coa_post_daily_strip(
    implied_target_pct: float,
    start: date,
    end: date,
    k_eff: date,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
    pre_pct: float,
) -> float:

    def err(post: float) -> float:
        return (
            _coa_implied_percent_daily_piecewise(
                start,
                end,
                k_eff=k_eff,
                observation_date=observation_date,
                fixings_sorted=fixings_sorted,
                pre_pct=pre_pct,
                post_pct=post,
            )
            - implied_target_pct
        )

    return _bisect_generic(err, 0.0, -2.0, 50.0)


def cra_implied_percent_piecewise_overnight(
    start: date,
    end: date,
    k_effs: list[date],
    levels_pct: list[float],
) -> float:
    """CRA quoted implied R (percent) from piecewise-constant overnight levels (same compounding as COA)."""
    if len(levels_pct) != len(k_effs) + 1:
        raise ValueError("levels_pct must align with meeting effective dates")
    d_cal = (end - start).days
    if d_cal <= 0:
        raise ValueError("invalid CRA window")
    prod = 1.0
    for bd, n_i in _coa_segment_weights(start, end):
        pos = 0
        d = bd
        for _ in range(n_i):
            while pos < len(k_effs) and k_effs[pos] <= d:
                pos += 1
            c_pct = levels_pct[pos]
            r = _pct_to_dec(c_pct)
            prod *= 1.0 + r / 365.0
            d += timedelta(days=1)
    r_dec = (prod - 1.0) * 365.0 / float(d_cal)
    return r_dec * 100.0


def _ca_compound_implied_from_rate_fn(start: date, end: date, rate_for_day: Any) -> float:
    """Quoted implied R from a day-by-day overnight CORRA schedule (percent), BoC segment compounding."""
    d_cal = (end - start).days
    if d_cal <= 0:
        raise ValueError("invalid accrual window")
    prod = 1.0
    for bd, n_i in _coa_segment_weights(start, end):
        d = bd
        for _ in range(n_i):
            prod *= 1.0 + _pct_to_dec(float(rate_for_day(d))) / 365.0
            d += timedelta(days=1)
    r_dec = (prod - 1.0) * 365.0 / float(d_cal)
    return r_dec * 100.0


def _ca_overnight_on_day(
    d: date,
    *,
    initial_overnight: float,
    solved_overnight: list[tuple[date, float]],
) -> float:
    """Piecewise overnight CORRA (percent) from initial level and solved post-meeting levels."""
    rate = initial_overnight
    for eff, post in sorted(solved_overnight, key=lambda item: item[0]):
        if eff <= d:
            rate = post
        else:
            break
    return rate


def _ca_cra_reconstruct_implied(
    start: date,
    end: date,
    *,
    initial_overnight: float,
    solved_overnight: list[tuple[date, float]],
    pending_k_effs: list[date],
    pending_posts: list[float],
    observation_date: date | None,
    fixings_sorted: list[tuple[date, float]],
) -> float:
    """Reconstruct CRA implied rate from a full overnight schedule including optional fixed CORRA strip."""

    unknown: dict[date, float] = dict(zip(pending_k_effs, pending_posts))

    def rate_for_day(d: date) -> float:
        if observation_date is not None and d < observation_date and fixings_sorted:
            fixed = _sofr_print_for_elapsed_day(d, observation_date, fixings_sorted)
            if fixed is not None:
                return fixed
        effs = sorted(solved_overnight, key=lambda x: x[0]) + sorted(
            ((k, unknown[k]) for k in unknown), key=lambda x: x[0]
        )
        rate = initial_overnight
        for eff, post in effs:
            if eff <= d:
                rate = post
            else:
                break
        return rate

    return _ca_compound_implied_from_rate_fn(start, end, rate_for_day)


def _ca_coa_reconstruct_implied(
    start: date,
    end: date,
    k_eff: date,
    pre_overnight: float,
    post_overnight: float,
    *,
    observation_date: date | None,
    fixings_sorted: list[tuple[date, float]],
) -> float:
    if observation_date is not None and fixings_sorted:
        return _coa_implied_percent_daily_piecewise(
            start,
            end,
            k_eff=k_eff,
            observation_date=observation_date,
            fixings_sorted=fixings_sorted,
            pre_pct=pre_overnight,
            post_pct=post_overnight,
        )
    return coa_implied_percent_pre_post(start, end, k_eff, pre_overnight, post_overnight)


def _ca_reconstruction_ok(implied: float, reconstructed: float, *, tol_bp: float = 0.5) -> bool:
    return abs(reconstructed - implied) <= tol_bp * 0.01


def _ca_contract_usage_key(row: dict) -> str:
    return f"{row.get('product')}:{row.get('expiry')}"


def _ca_contract_vintage_note(row: dict) -> str | None:
    missing: list[str] = []
    if row.get("observation_date") in (None, ""):
        missing.append("observation_date")
    if row.get("open_interest") in (None, ""):
        missing.append("open_interest")
    if row.get("volume") in (None, ""):
        missing.append("volume")
    if not missing:
        return None
    return "Contract row missing " + ", ".join(missing)


def _iter_calendar_days(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def _ib_forward_baseline(
    implied: float,
    n_cal: int,
    fixed_rates: list[float],
) -> float:
    fixed_sum = sum(fixed_rates)
    fwd = n_cal - len(fixed_rates)
    if fwd <= 0:
        return implied
    return (n_cal * implied - fixed_sum) / fwd


def _ib_monthly_from_levels(
    month_start: date,
    month_end: date,
    k_eff: date,
    f_prior: float | None,
    f_post: float,
) -> float:
    total = 0.0
    s = 0.0
    for d in _iter_calendar_days(month_start, month_end):
        total += 1
        if k_eff is None or d >= k_eff:
            s += f_post
        else:
            s += f_prior if f_prior is not None else f_post
    return s / total


def _ib_solve_post_for_meeting(
    implied_month: float,
    month_start: date,
    month_end: date,
    k_eff: date,
    *,
    pre_sum: float,
    n_pre: int,
    f_fwd_pre: float,
) -> float:
    """Solve arithmetic monthly average given pre days (fixed + forward flat) then post flat."""
    n_tot = (month_end - month_start).days
    if n_tot <= 0:
        raise ValueError("invalid IB window")
    n_post = n_tot - n_pre
    if n_post <= 0:
        raise ValueError("no post-meeting IB days")
    implied_sum = implied_month * n_tot
    return (implied_sum - pre_sum) / n_post


def _ib_pre_meeting_sum(
    *,
    month_start: date,
    month_end: date,
    k_eff: date,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
    f_fwd_pre: float,
) -> tuple[float, int, bool]:
    """Sum pre-meeting day rates inside the meeting month only (fixings then forward flat)."""
    n_tot = (month_end - month_start).days
    pre_end = min(k_eff, month_end)
    n_pre = (pre_end - month_start).days
    if n_pre < 0 or n_pre > n_tot:
        return 0.0, 0, False
    pre_sum = 0.0
    for d in _iter_calendar_days(month_start, pre_end):
        if d < observation_date:
            r = _sofr_print_for_elapsed_day(d, observation_date, fixings_sorted)
            if r is None:
                return 0.0, 0, False
            pre_sum += r
        else:
            pre_sum += f_fwd_pre
    return pre_sum, n_pre, True


def _ca_au_observation_gate(contracts: list[dict]) -> tuple[date | None, str | None]:
    obs_dates: list[date] = []
    has_missing = False
    for row in contracts:
        if row.get("implied_rate") is None:
            continue
        raw = row.get("observation_date")
        if raw in (None, ""):
            has_missing = True
            continue
        try:
            obs_dates.append(_parse_date(str(raw)))
        except ValueError:
            return None, "invalid observation_date on policy path futures"
    if not obs_dates:
        return None, None
    if has_missing:
        return None, "policy path futures mix dated and undated observation_date"
    if len(set(obs_dates)) != 1:
        return None, "policy path futures observation_date is mixed vintage"
    return obs_dates[0], None


def _sorted_pct_fixings(
    fixings: list[tuple[date, float]] | None,
) -> list[tuple[date, float]]:
    if not fixings:
        return []
    return sorted(fixings, key=lambda item: item[0])


def _expiry_month_key(expiry: str) -> tuple[int, int]:
    year_s, month_s = expiry.split("-")
    return int(year_s), int(month_s)


def _prior_month_expiry(expiry: str) -> str:
    y, m = _expiry_month_key(expiry)
    py, pm = _add_months(y, m, -1)
    return f"{py:04d}-{pm:02d}"


def _next_month_expiry(expiry: str) -> str:
    y, m = _expiry_month_key(expiry)
    ny, nm = _add_months(y, m, 1)
    return f"{ny:04d}-{nm:02d}"


def _meeting_month_sr1_expiry(k_eff: date) -> str:
    return f"{k_eff.year:04d}-{k_eff.month:02d}"


US_SR1_CROSS_MONTH_ESTIMATE_NOTE = (
    "Post-meeting SOFR is anchored from the meeting-free following month SR1 average "
    "under a flat inter-meeting SOFR assumption; the meeting month has fewer than "
    "seven post-meeting accrual days."
)


def _sorted_sofr_fixings(
    fixings: list[tuple[date, float]] | None,
) -> list[tuple[date, float]]:
    if not fixings:
        return []
    return sorted(fixings, key=lambda item: item[0])


def _sofr_print_for_elapsed_day(
    day: date,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
) -> float | None:
    """Rate applicable to calendar day D when D < observation_date; None if gap or no print."""
    if day >= observation_date:
        return None
    best: tuple[date, float] | None = None
    for eff, rate in fixings_sorted:
        if eff <= day:
            best = (eff, rate)
        else:
            break
    if best is None:
        return None
    eff, rate = best
    if (day - eff).days > 4:
        return None
    return rate


def _accrual_window_meeting_free(
    start: date,
    end: date,
    unresolved_meetings: list[dict],
) -> bool:
    """True when no unresolved (future) meeting has effective_date in [start, end)."""
    for m in unresolved_meetings:
        eff = _parse_date(m["effective_date"])
        if start <= eff < end:
            return False
    return True


def _sr1_contract_live(row_expiry: str, as_of: date) -> bool:
    _s, acc_end = accrual_window(row_expiry, "1m")
    return acc_end > as_of


def _fixed_day_rates_before_observation(
    expiry: str,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
) -> tuple[list[float], bool]:
    """Calendar days in the contract month with D < observation_date; fail if any gap."""
    start, acc_end = accrual_window(expiry, "1m")
    fixed: list[float] = []
    current = start
    while current < acc_end and current < observation_date:
        r = _sofr_print_for_elapsed_day(current, observation_date, fixings_sorted)
        if r is None:
            return [], False
        fixed.append(r)
        current += timedelta(days=1)
    return fixed, True


def _forward_baseline_rate(
    implied: float,
    n_calendar: int,
    fixed_rates: list[float],
) -> float:
    """F_baseline = (N * F - sum(fixed)) / forward_days, or mean(fixed) if forward_days == 0."""
    fixed_sum = sum(fixed_rates)
    forward_days = n_calendar - len(fixed_rates)
    if forward_days == 0:
        if not fixed_rates:
            raise ValueError("no fixed days for baseline")
        return fixed_sum / len(fixed_rates)
    return (n_calendar * implied - fixed_sum) / forward_days


def _sr1_unsolved_predecessor_eff(
    meeting_idx: int,
    unresolved: list[dict],
    solved_sofr: list[tuple[date, float]],
) -> date | None:
    """Effective date of the latest unresolved predecessor meeting lacking a solved SOFR post."""
    solved_effs = {eff for eff, _ in solved_sofr}
    for j in range(meeting_idx - 1, -1, -1):
        eff = _parse_date(unresolved[j]["effective_date"])
        if eff not in solved_effs:
            return eff
    return None


US_SR1_PREDECESSOR_GAP_REASON = (
    "A prior FOMC step is unavailable; the SR1-identified policy path is underdetermined"
)


def _sr1_month_pre_meeting_known_sum(
    *,
    month_start: date,
    month_end: date,
    k_eff: date,
    observation_date: date,
    fixings_sorted: list[tuple[date, float]],
    f_baseline: float,
    prev_meeting_eff: date | None,
    prev_f_sofr_post: float | None,
    unsolved_predecessor_eff: date | None = None,
) -> tuple[float, bool]:
    """Sum SOFR accrual factors for calendar days in [month_start, k_eff)."""
    gap_eff = unsolved_predecessor_eff if unsolved_predecessor_eff is not None else prev_meeting_eff
    total = 0.0
    d = month_start
    while d < k_eff and d < month_end:
        if d < observation_date:
            r = _sofr_print_for_elapsed_day(d, observation_date, fixings_sorted)
            if r is None:
                return 0.0, False
            total += r
        elif gap_eff is not None and d >= gap_eff:
            if prev_meeting_eff is not None and d >= prev_meeting_eff:
                if prev_f_sofr_post is None:
                    return 0.0, False
                total += prev_f_sofr_post
            else:
                return 0.0, False
        else:
            total += f_baseline
        d += timedelta(days=1)
    return total, True


def _contract_dict_for_output(row: dict, *, weight: float, role: str | None = None) -> dict:
    out: dict[str, Any] = {
        "product": row["product"],
        "expiry": row["expiry"],
        "weight": weight,
    }
    if role:
        out["role"] = role
    for key in (
        "price",
        "implied_rate",
        "source",
        "source_url",
        "observation_date",
        "as_of",
        "code",
    ):
        if key in row and row[key] is not None:
            out[key] = row[key]
    return out


def price_meetings(
    *,
    bank: str,
    as_of: date,
    anchor: float,
    basis: float,
    meetings: list[dict],
    contracts: list[dict],
    history: list[tuple[date, float]] | None = None,
    sofr_fixings: list[tuple[date, float]] | None = None,
    observation_date: date | None = None,
    calendar_meetings_us: list[dict] | None = None,
    contracts_zq: list[dict] | None = None,
    policy_state_us: dict | None = None,
) -> list[dict]:
    history = list(history or [])
    sorted_meetings = sorted(meetings, key=lambda m: _parse_date(m["effective_date"]))
    unresolved = [m for m in sorted_meetings if _parse_date(m["effective_date"]) > as_of]

    rows: list[dict] = []
    solved: list[tuple[date, float]] = []
    solved_sofr: list[tuple[date, float]] = []
    previous_post: float | None = None
    sr1_baseline_path_started = False
    us_sr1_path_gap = False

    fixings_sorted = _sorted_sofr_fixings(sofr_fixings)
    corra_fixings_sorted = _sorted_pct_fixings(sofr_fixings)
    cal_for_meeting_free = (
        calendar_meetings_us if (bank == "US" and calendar_meetings_us) else sorted_meetings
    )
    unresolved_cal = [m for m in cal_for_meeting_free if _parse_date(m["effective_date"]) > as_of]

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
        extras: dict | None = None,
    ) -> dict:
        out = {
            "decision_date": meeting["decision_date"],
            "effective_date": meeting["effective_date"],
            "post_rate": _round_rate(post) if post is not None else None,
            "incremental_bp": _round_bp(incremental) if incremental is not None else None,
            "cumulative_bp": _round_bp(cumulative) if cumulative is not None else None,
            "method": method,
            "contracts": contracts_used,
        }
        if extras:
            out.update(extras)
        return out

    def incremental_for(post: float) -> float:
        nonlocal previous_post
        base = previous_post if previous_post is not None else anchor
        inc = (post - base) * 100.0
        previous_post = post
        return inc

    sr1_by_expiry: dict[str, dict] = {}
    if bank == "US":
        for c in contracts:
            if (
                c.get("product") == "SR1"
                and c.get("period") == "1m"
                and c.get("implied_rate") is not None
                and isinstance(c.get("expiry"), str)
            ):
                sr1_by_expiry[str(c["expiry"])] = c

    if bank == "CA":
        coa_rows = [
            c
            for c in contracts
            if c.get("product") == "COA"
            and c.get("period") == "1m"
            and c.get("implied_rate") is not None
        ]
        cra_rows = [
            c
            for c in contracts
            if c.get("product") == "CRA"
            and c.get("period") == "3m"
            and c.get("implied_rate") is not None
        ]
        ca_obs, ca_gate_reason = _ca_au_observation_gate(coa_rows + cra_rows)
        if ca_gate_reason:
            return [_row(m, None, None, None, "unavailable", []) for m in unresolved]

        def _coa_live(expiry_s: str) -> bool:
            _s, acc_end = coa_accrual_window(expiry_s)
            return acc_end > as_of

        def _cra_live(expiry_s: str) -> bool:
            _s, acc_end = accrual_window(expiry_s, "3m")
            return acc_end > as_of

        coa_by_expiry = {str(r["expiry"]): r for r in coa_rows if _coa_live(str(r["expiry"]))}
        cra_by_expiry = {str(r["expiry"]): r for r in cra_rows if _cra_live(str(r["expiry"]))}

        initial_overnight = anchor + basis
        solved_overnight_path: list[tuple[date, float]] = []
        used_contract_keys: set[str] = set()

        def _ca_tail_unavailable(from_idx: int, reason: str) -> None:
            for tail in unresolved[from_idx:]:
                rows.append(
                    _row(
                        tail,
                        None,
                        None,
                        None,
                        "unavailable",
                        [],
                        extras={"reason": reason},
                    )
                )

        def _overnight_tail() -> float:
            if solved_overnight_path:
                return solved_overnight_path[-1][1]
            return initial_overnight

        def _emit_coa_row(
            meeting: dict,
            *,
            pre_o: float,
            post_o: float,
            method_ca: str,
            contracts_out: list[dict],
            estimate_note: str | None,
            vintage_note: str | None,
        ) -> bool:
            nonlocal previous_post
            implied_coa = float(contracts_out[0]["implied_rate"])
            win_start = coa_accrual_window(str(contracts_out[0]["expiry"]))[0]
            win_end = coa_accrual_window(str(contracts_out[0]["expiry"]))[1]
            k_eff_m = _parse_date(meeting["effective_date"])
            recon = _ca_coa_reconstruct_implied(
                win_start,
                win_end,
                k_eff_m,
                pre_o,
                post_o,
                observation_date=ca_obs,
                fixings_sorted=corra_fixings_sorted,
            )
            if not _ca_reconstruction_ok(implied_coa, recon):
                return False
            step_o = post_o - pre_o
            pol_prev = previous_post if previous_post is not None else anchor
            policy_post = pol_prev + step_o
            inc = _round_bp(step_o * 100.0)
            previous_post = policy_post
            cum = _round_bp((policy_post - anchor) * 100.0)
            extras_ca: dict[str, Any] = {
                "overnight_pre": _round_rate(pre_o),
                "overnight_post": _round_rate(post_o),
                "step_meaning": CA_COA_STEP_MEANING,
            }
            if estimate_note:
                extras_ca["estimate_note"] = estimate_note
            if vintage_note:
                extras_ca["vintage_note"] = vintage_note
            rows.append(
                _row(
                    meeting,
                    policy_post,
                    inc,
                    cum,
                    method_ca,
                    contracts_out,
                    extras=extras_ca,
                )
            )
            solved_overnight_path.append((k_eff_m, post_o))
            used_contract_keys.add(_ca_contract_usage_key(contracts_out[0]))
            return True

        i_ca = 0
        while i_ca < len(unresolved):
            meeting = unresolved[i_ca]
            k_eff = _parse_date(meeting["effective_date"])

            coa_candidates: list[tuple[dict, date, date]] = []
            for expiry_s, row in coa_by_expiry.items():
                if _ca_contract_usage_key(row) in used_contract_keys:
                    continue
                c_start, c_end = coa_accrual_window(expiry_s)
                if not (c_start <= k_eff < c_end):
                    continue
                if (c_end - k_eff).days < 1:
                    continue
                coa_candidates.append((row, c_start, c_end))

            used_coa = False
            if coa_candidates:
                chosen_coa, win_start, win_end = min(
                    coa_candidates, key=lambda item: item[0]["expiry"]
                )
                exp_key = str(chosen_coa["expiry"])
                y_m, m_m = _expiry_month_key(exp_key)
                cand_y, cand_m = y_m, m_m
                prior_coa: dict | None = None
                prior_exp: str | None = None
                prior_start: date | None = None
                prior_end: date | None = None
                for _ in range(24):
                    cand_y, cand_m = _add_months(cand_y, cand_m, -1)
                    prior_exp_try = f"{cand_y:04d}-{cand_m:02d}"
                    prow = coa_by_expiry.get(prior_exp_try)
                    if prow is None:
                        continue
                    ps, pe = coa_accrual_window(prior_exp_try)
                    if not _coa_live(prior_exp_try):
                        continue
                    if not _accrual_window_meeting_free(ps, pe, unresolved_cal):
                        continue
                    prior_coa = prow
                    prior_exp = prior_exp_try
                    prior_start, prior_end = ps, pe
                    break
                prior_ok = prior_coa is not None and prior_start is not None and prior_end is not None

                pre_o: float | None = None
                post_o: float | None = None
                method_ca = "estimated"
                estimate_note: str | None = None
                baseline_row: dict | None = None
                contracts_out: list[dict] = [
                    _contract_dict_for_output(chosen_coa, weight=1.0, role="meeting_month")
                ]

                vintage_note = _ca_contract_vintage_note(chosen_coa)
                if prior_ok or solved_overnight_path:
                    pass
                else:
                    rows.append(
                        _row(
                            meeting,
                            None,
                            None,
                            None,
                            "unavailable",
                            [],
                            extras={
                                "reason": "No prior COA month to strip realized CORRA or chain from a solved overnight path"
                            },
                        )
                    )
                    i_ca += 1
                    continue

                if solved_overnight_path:
                    pre_o = _overnight_tail()
                    post_o = _solve_coa_post_overnight(
                        float(chosen_coa["implied_rate"]),
                        win_start,
                        win_end,
                        k_eff,
                        pre_o,
                    )
                    method_ca = "estimated"
                    estimate_note = (
                        "Realized daily CORRA fixings were not stripped; this is not a fixing-adjusted step."
                    )
                    baseline_row = coa_by_expiry.get(_prior_month_expiry(exp_key))
                    if baseline_row is not None:
                        contracts_out.append(
                            _contract_dict_for_output(
                                baseline_row, weight=0.0, role="forward_baseline"
                            )
                        )
                    if _emit_coa_row(
                        meeting,
                        pre_o=pre_o,
                        post_o=post_o,
                        method_ca=method_ca,
                        contracts_out=contracts_out,
                        estimate_note=estimate_note,
                        vintage_note=vintage_note,
                    ):
                        used_coa = True
                    else:
                        rows.append(
                            _row(
                                meeting,
                                None,
                                None,
                                None,
                                "unavailable",
                                [],
                                extras={
                                    "reason": "COA implied rate does not reconstruct from the overnight path"
                                },
                            )
                        )
                    i_ca += 1
                    continue

                if ca_obs is not None and corra_fixings_sorted:
                    fixed_prior: list[float] = []
                    ok_strip = True
                    for d in _iter_calendar_days(prior_start, min(prior_end, ca_obs)):
                        r = _sofr_print_for_elapsed_day(d, ca_obs, corra_fixings_sorted)
                        if r is None:
                            ok_strip = False
                            break
                        fixed_prior.append(r)
                    if not ok_strip:
                        rows.append(
                            _row(
                                meeting,
                                None,
                                None,
                                None,
                                "unavailable",
                                [],
                                extras={"reason": "CORRA fixing gap in prior COA month"},
                            )
                        )
                        i_ca += 1
                        continue
                    if not fixed_prior:
                        pre_o = _bisect_solve_coa_flat(
                            float(prior_coa["implied_rate"]), prior_start, prior_end
                        )
                        post_o = _solve_coa_post_overnight(
                            float(chosen_coa["implied_rate"]),
                            win_start,
                            win_end,
                            k_eff,
                            pre_o,
                        )
                        method_ca = "estimated"
                        estimate_note = (
                            "Realized daily CORRA fixings were not stripped; this is not a fixing-adjusted step."
                        )
                    else:
                        g = _solve_coa_overnight_month_strip(
                            float(prior_coa["implied_rate"]),
                            prior_start,
                            prior_end,
                            ca_obs,
                            corra_fixings_sorted,
                        )
                        pre_o = g
                        post_o = _solve_coa_post_daily_strip(
                            float(chosen_coa["implied_rate"]),
                            win_start,
                            win_end,
                            k_eff,
                            ca_obs,
                            corra_fixings_sorted,
                            g,
                        )
                        method_ca = "identified"
                    baseline_row = prior_coa
                else:
                    pre_o = _bisect_solve_coa_flat(
                        float(prior_coa["implied_rate"]), prior_start, prior_end
                    )
                    post_o = _solve_coa_post_overnight(
                        float(chosen_coa["implied_rate"]),
                        win_start,
                        win_end,
                        k_eff,
                        pre_o,
                    )
                    method_ca = "estimated"
                    estimate_note = (
                        "Realized daily CORRA fixings were not stripped; this is not a fixing-adjusted step."
                    )
                    baseline_row = prior_coa

                if baseline_row is not None:
                    contracts_out.append(
                        _contract_dict_for_output(
                            baseline_row, weight=0.0, role="forward_baseline"
                        )
                    )
                if _emit_coa_row(
                    meeting,
                    pre_o=pre_o,
                    post_o=post_o,
                    method_ca=method_ca,
                    contracts_out=contracts_out,
                    estimate_note=estimate_note,
                    vintage_note=vintage_note,
                ):
                    used_coa = True
                else:
                    rows.append(
                        _row(
                            meeting,
                            None,
                            None,
                            None,
                            "unavailable",
                            [],
                            extras={
                                "reason": "COA implied rate does not reconstruct from the overnight path"
                            },
                        )
                    )
                i_ca += 1

            if used_coa:
                continue

            cra_candidates: list[tuple[date, dict, date, date]] = []
            for cra_row in cra_by_expiry.values():
                if _ca_contract_usage_key(cra_row) in used_contract_keys:
                    continue
                cs, ce = accrual_window(str(cra_row["expiry"]), "3m")
                days_after = sum(1 for day in _iter_days(cs, ce) if day >= k_eff)
                if days_after < 7:
                    continue
                skip_cra = False
                for day in _iter_days(cs, ce):
                    if day <= as_of and not _is_known_on_day(
                        day, as_of, anchor, history, solved, sorted_meetings
                    ):
                        skip_cra = True
                        break
                if skip_cra:
                    continue
                cra_candidates.append((ce, cra_row, cs, ce))
            if not cra_candidates:
                _ca_tail_unavailable(
                    i_ca,
                    "No CRA contract with at least 7 accrual days after the meeting",
                )
                break

            cra_priced = False
            for _ce, cra_row, cs, ce in sorted(cra_candidates, key=lambda item: item[0]):
                group_slice: list[dict] = []
                for m in unresolved[i_ca:]:
                    eff_m = _parse_date(m["effective_date"])
                    if eff_m < ce:
                        group_slice.append(m)
                    else:
                        break
                if not group_slice or group_slice[0] is not meeting:
                    continue

                effs_sorted = sorted(
                    _parse_date(m["effective_date"]) for m in group_slice
                )
                f_cra = float(cra_row["implied_rate"])
                vintage_note_cra = _ca_contract_vintage_note(cra_row)
                k_first = effs_sorted[0]
                pre_meeting_on = _ca_overnight_on_day(
                    k_first - timedelta(days=1),
                    initial_overnight=initial_overnight,
                    solved_overnight=solved_overnight_path,
                )

                posts: list[float] = []
                method_cr = "identified"
                try:
                    if len(effs_sorted) == 1:

                        def recon_identified(post_x: float) -> float:
                            return _ca_cra_reconstruct_implied(
                                cs,
                                ce,
                                initial_overnight=initial_overnight,
                                solved_overnight=solved_overnight_path,
                                pending_k_effs=effs_sorted,
                                pending_posts=[post_x],
                                observation_date=ca_obs,
                                fixings_sorted=corra_fixings_sorted,
                            )

                        post_o = _bisect_generic(
                            lambda x: recon_identified(x),
                            f_cra,
                            pre_meeting_on - 2.0,
                            pre_meeting_on + 5.0,
                        )
                        if not _ca_reconstruction_ok(f_cra, recon_identified(post_o)):
                            continue
                        posts = [post_o]
                    else:

                        def pack_step(s_step: float) -> list[float]:
                            cur = pre_meeting_on
                            out_posts: list[float] = []
                            for _ in effs_sorted:
                                cur += s_step
                                out_posts.append(cur)
                            return out_posts

                        def recon_equal(s_step: float) -> float:
                            p = pack_step(s_step)
                            return _ca_cra_reconstruct_implied(
                                cs,
                                ce,
                                initial_overnight=initial_overnight,
                                solved_overnight=solved_overnight_path,
                                pending_k_effs=effs_sorted,
                                pending_posts=p,
                                observation_date=ca_obs,
                                fixings_sorted=corra_fixings_sorted,
                            )

                        s_hat = _bisect_generic(
                            lambda s: recon_equal(s) - f_cra, 0.0, -1.0, 1.0
                        )
                        posts = pack_step(s_hat)
                        if not _ca_reconstruction_ok(f_cra, recon_equal(s_hat)):
                            continue
                        method_cr = "equal_step"
                except ValueError:
                    continue

                contract_cra = [
                    _contract_dict_for_output(cra_row, weight=1.0, role="meeting_month")
                ]
                pre_step = pre_meeting_on
                for j, gm in enumerate(group_slice):
                    post_on = posts[j]
                    step_o = post_on - pre_step
                    pol_prev = previous_post if previous_post is not None else anchor
                    policy_post = pol_prev + step_o
                    inc = _round_bp(step_o * 100.0)
                    previous_post = policy_post
                    cum = _round_bp((policy_post - anchor) * 100.0)
                    extras_cr: dict[str, Any] = {
                        "overnight_pre": _round_rate(pre_step),
                        "overnight_post": _round_rate(post_on),
                        "step_meaning": CA_COA_STEP_MEANING,
                    }
                    if vintage_note_cra:
                        extras_cr["vintage_note"] = vintage_note_cra
                    rows.append(
                        _row(
                            gm,
                            policy_post,
                            inc,
                            cum,
                            method_cr,
                            contract_cra,
                            extras=extras_cr,
                        )
                    )
                    solved_overnight_path.append(
                        (_parse_date(gm["effective_date"]), post_on)
                    )
                    pre_step = post_on

                used_contract_keys.add(_ca_contract_usage_key(cra_row))
                cra_priced = True
                i_ca += len(group_slice)
                break

            if not cra_priced:
                _ca_tail_unavailable(
                    i_ca,
                    "CRA contract implied rate does not reconstruct from the overnight path",
                )
                break

        return rows

    if bank == "AU":
        ib_rows = [
            c
            for c in contracts
            if c.get("product") == "IB"
            and c.get("period") == "1m"
            and c.get("implied_rate") is not None
        ]
        au_obs, au_gate_reason = _ca_au_observation_gate(ib_rows)
        if au_gate_reason:
            return [_row(m, None, None, None, "unavailable", []) for m in unresolved]

        ib_by_expiry = {
            str(r["expiry"]): r
            for r in ib_rows
            if accrual_window(str(r["expiry"]), "1m")[1] > as_of
        }

        solved_ib_post: float | None = None

        for meeting in unresolved:
            k_eff = _parse_date(meeting["effective_date"])
            ib_candidates: list[tuple[dict, date, date]] = []
            for expiry_s, row in ib_by_expiry.items():
                ms, me = accrual_window(expiry_s, "1m")
                if not (ms <= k_eff < me):
                    continue
                if (me - ms).days < 7:
                    continue
                ib_candidates.append((row, ms, me))
            if not ib_candidates:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue
            meeting_ib, month_start, month_end = min(ib_candidates, key=lambda x: x[0]["expiry"])
            n_tot = (month_end - month_start).days
            implied_m = float(meeting_ib["implied_rate"])
            y_m, m_m = _expiry_month_key(str(meeting_ib["expiry"]))
            cy, cm = y_m, m_m
            prior_ib: dict | None = None
            prior_start: date | None = None
            prior_end: date | None = None
            for _ in range(24):
                cy, cm = _add_months(cy, cm, -1)
                prior_exp_try = f"{cy:04d}-{cm:02d}"
                pib = ib_by_expiry.get(prior_exp_try)
                if pib is None:
                    continue
                ps, pe = accrual_window(prior_exp_try, "1m")
                if pe <= as_of:
                    continue
                if not _accrual_window_meeting_free(ps, pe, unresolved_cal):
                    continue
                prior_ib = pib
                prior_start, prior_end = ps, pe
                break
            if prior_ib is None or prior_start is None or prior_end is None:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue

            method_au = "estimated"
            estimate_note_au: str | None = None
            f_fwd_pre: float | None = None
            f_pre_flat: float | None = None
            pre_sum = 0.0
            n_pre = 0

            if au_obs is not None and corra_fixings_sorted:
                fixed_prior: list[float] = []
                ok_au = True
                for d in _iter_calendar_days(prior_start, min(prior_end, au_obs)):
                    r = _sofr_print_for_elapsed_day(d, au_obs, corra_fixings_sorted)
                    if r is None:
                        ok_au = False
                        break
                    fixed_prior.append(r)
                if not ok_au:
                    rows.append(_row(meeting, None, None, None, "unavailable", []))
                    continue
                if not fixed_prior:
                    f_fwd_pre = float(prior_ib["implied_rate"])
                    f_pre_flat = (
                        solved_ib_post if solved_ib_post is not None else f_fwd_pre
                    )
                    n_pre = sum(
                        1 for d in _iter_calendar_days(month_start, month_end) if d < k_eff
                    )
                    pre_sum = n_pre * f_pre_flat
                    method_au = "estimated"
                    estimate_note_au = (
                        "Realized daily cash-rate fixings were not stripped; this is not a fixing-adjusted step."
                    )
                else:
                    n_prior = (prior_end - prior_start).days
                    f_fwd_pre = _ib_forward_baseline(
                        float(prior_ib["implied_rate"]),
                        n_prior,
                        fixed_prior,
                    )
                    f_pre_flat = (
                        solved_ib_post if solved_ib_post is not None else f_fwd_pre
                    )
                    pre_sum, n_pre, ok_strip = _ib_pre_meeting_sum(
                        month_start=month_start,
                        month_end=month_end,
                        k_eff=k_eff,
                        observation_date=au_obs,
                        fixings_sorted=corra_fixings_sorted,
                        f_fwd_pre=f_pre_flat,
                    )
                    if not ok_strip:
                        rows.append(_row(meeting, None, None, None, "unavailable", []))
                        continue
                    method_au = "identified"
            else:
                f_fwd_pre = float(prior_ib["implied_rate"])
                f_pre_flat = solved_ib_post if solved_ib_post is not None else f_fwd_pre
                n_pre = sum(
                    1 for d in _iter_calendar_days(month_start, month_end) if d < k_eff
                )
                pre_sum = n_pre * f_pre_flat
                method_au = "estimated"
                estimate_note_au = (
                    "Realized daily cash-rate fixings were not stripped; this is not a fixing-adjusted step."
                )

            n_post = n_tot - n_pre
            if n_post <= 0:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue

            if f_pre_flat is None:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue

            try:
                f_post_ib = _ib_solve_post_for_meeting(
                    implied_m,
                    month_start,
                    month_end,
                    k_eff,
                    pre_sum=pre_sum,
                    n_pre=n_pre,
                    f_fwd_pre=f_pre_flat,
                )
            except ValueError:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue

            recon = (pre_sum + n_post * f_post_ib) / n_tot
            if abs(recon - implied_m) > 0.0005:
                rows.append(_row(meeting, None, None, None, "unavailable", []))
                continue

            ib_residual_bp = abs(recon - implied_m) * 100.0
            step_ib = f_post_ib - f_pre_flat
            pol_prev = previous_post if previous_post is not None else anchor
            policy_post = pol_prev + step_ib
            inc = _round_bp(step_ib * 100.0)
            previous_post = policy_post
            cum = _round_bp((policy_post - anchor) * 100.0)

            contracts_au = [
                _contract_dict_for_output(meeting_ib, weight=1.0, role="meeting_month"),
                _contract_dict_for_output(prior_ib, weight=0.0, role="forward_baseline"),
            ]
            extras_au: dict[str, Any] = {
                "ib_prior_forward": _round_rate(f_pre_flat),
                "ib_post_level": _round_rate(f_post_ib),
                "step_meaning": AU_IB_STEP_MEANING,
                "ib_month_days": n_tot,
                "n_pre": n_pre,
                "n_post": n_post,
                "ib_identity_residual_bp": _round_bp(ib_residual_bp),
            }
            if estimate_note_au:
                extras_au["estimate_note"] = estimate_note_au
            rows.append(
                _row(
                    meeting,
                    policy_post,
                    inc,
                    cum,
                    method_au,
                    contracts_au,
                    extras=extras_au,
                )
            )
            solved_ib_post = f_post_ib
        return rows

    idx = 0
    while idx < len(unresolved):
        meeting = unresolved[idx]
        k_eff = _parse_date(meeting["effective_date"])
        next_eff = (
            _parse_date(unresolved[idx + 1]["effective_date"])
            if idx + 1 < len(unresolved)
            else date.max
        )

        if bank == "US" and us_sr1_path_gap:
            while idx < len(unresolved):
                rows.append(
                    _row(
                        unresolved[idx],
                        None,
                        None,
                        None,
                        "unavailable",
                        [],
                        extras={"reason": US_SR1_PREDECESSOR_GAP_REASON},
                    )
                )
                idx += 1
            break

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

        used_sr1_forward = False
        if (
            bank == "US"
            and observation_date is not None
            and fixings_sorted
            and sr1_by_expiry
        ):
            obs_date = observation_date
            expiry_s = _meeting_month_sr1_expiry(k_eff)
            meeting_contract = sr1_by_expiry.get(expiry_s)
            if (
                meeting_contract is not None
                and meeting_contract.get("implied_rate") is not None
                and meeting_contract.get("period") == "1m"
                and _sr1_contract_live(expiry_s, as_of)
            ):
                month_start, month_end = accrual_window(expiry_s, "1m")
                n_cal = (month_end - month_start).days
                f_month = float(meeting_contract["implied_rate"])

                prior_exp = _prior_month_expiry(expiry_s)
                prior_row = sr1_by_expiry.get(prior_exp)
                prior_ok = (
                    prior_row is not None
                    and prior_row.get("implied_rate") is not None
                    and _sr1_contract_live(prior_exp, as_of)
                )

                _mt_fixed, meeting_fixed_ok = _fixed_day_rates_before_observation(
                    expiry_s, obs_date, fixings_sorted
                )
                realized_pre_meeting: list[float] = []
                for d in _iter_days(month_start, min(k_eff, obs_date)):
                    if d >= obs_date:
                        break
                    r = _sofr_print_for_elapsed_day(d, obs_date, fixings_sorted)
                    if r is not None:
                        realized_pre_meeting.append(r)

                use_sr1_forward = False
                f_baseline: float | None = None
                baseline_source_expiry: str | None = None
                baseline_contract_row: dict | None = None
                prior_fixed: list[float] = []
                n_prior_cal = 0

                if prior_ok and prior_row is not None:
                    pb_start, pb_end = accrual_window(prior_exp, "1m")
                    if _accrual_window_meeting_free(pb_start, pb_end, unresolved_cal):
                        prior_fixed, prior_ok_rates = _fixed_day_rates_before_observation(
                            prior_exp, obs_date, fixings_sorted
                        )
                        if prior_ok_rates:
                            n_prior_cal = (pb_end - pb_start).days
                            f_baseline = _forward_baseline_rate(
                                float(prior_row["implied_rate"]),
                                n_prior_cal,
                                prior_fixed,
                            )
                            baseline_source_expiry = prior_exp
                            baseline_contract_row = prior_row
                            use_sr1_forward = True

                if not use_sr1_forward and not prior_ok:
                    pre_days = [
                        d for d in _iter_days(month_start, k_eff) if d < obs_date
                    ]
                    rates_pre: list[float] = []
                    ok_pre = True
                    for d in pre_days:
                        r = _sofr_print_for_elapsed_day(d, obs_date, fixings_sorted)
                        if r is None:
                            ok_pre = False
                            break
                        rates_pre.append(r)
                    if ok_pre and rates_pre:
                        f_baseline = sum(rates_pre) / len(rates_pre)
                        use_sr1_forward = True

                prev_m = idx - 1
                prev_meeting_eff: date | None = None
                prev_f_post: float | None = None
                if prev_m >= 0:
                    prev_meeting_eff = _parse_date(unresolved[prev_m]["effective_date"])
                    for eff_d, f_v in solved_sofr:
                        if eff_d == prev_meeting_eff:
                            prev_f_post = f_v
                            break

                unsolved_pred_eff = _sr1_unsolved_predecessor_eff(
                    idx, unresolved, solved_sofr
                )

                sum_known_m, sk_ok = _sr1_month_pre_meeting_known_sum(
                    month_start=month_start,
                    month_end=month_end,
                    k_eff=k_eff,
                    observation_date=obs_date,
                    fixings_sorted=fixings_sorted,
                    f_baseline=f_baseline if f_baseline is not None else 0.0,
                    prev_meeting_eff=prev_meeting_eff,
                    prev_f_sofr_post=prev_f_post,
                    unsolved_predecessor_eff=unsolved_pred_eff,
                )

                n_pre = sum(
                    1 for d in _iter_days(month_start, month_end) if d < k_eff
                )
                n_post = n_cal - n_pre

                if (
                    use_sr1_forward
                    and f_baseline is not None
                    and sk_ok
                    and meeting_fixed_ok
                    and n_post >= 7
                ):
                    f_post_sofr = (n_cal * f_month - sum_known_m) / n_post
                    if not solved_sofr:
                        step_sofr = f_post_sofr - f_baseline
                        policy_post = anchor + step_sofr
                    else:
                        prev_f_sofr = solved_sofr[-1][1]
                        step_sofr = f_post_sofr - prev_f_sofr
                        pol_prev = (
                            previous_post if previous_post is not None else anchor
                        )
                        policy_post = pol_prev + step_sofr
                    inc = _round_bp(step_sofr * 100.0)
                    cum = _round_bp((policy_post - anchor) * 100.0)
                    previous_post = policy_post

                    contracts_out = [
                        _contract_dict_for_output(
                            meeting_contract, weight=1.0, role="meeting_month"
                        ),
                    ]
                    if baseline_contract_row is not None and baseline_source_expiry:
                        contracts_out.append(
                            _contract_dict_for_output(
                                baseline_contract_row,
                                weight=0.0,
                                role="forward_baseline",
                            )
                        )

                    if baseline_contract_row is not None:
                        fwd_days = n_prior_cal - len(prior_fixed)
                        fxd_days_ct = len(prior_fixed)
                        baseline_month_average = _round_rate(
                            float(baseline_contract_row["implied_rate"])
                        )
                    else:
                        fwd_days = None
                        fxd_days_ct = len(realized_pre_meeting)
                        baseline_month_average = None

                    extras: dict[str, Any] = {
                        "sofr_post_rate": _round_rate(f_post_sofr),
                        "zq_cross_check": None,
                        "baseline": {
                            "kind": "sr1_forward",
                            "rate": _round_rate(f_baseline),
                            "source_expiry": baseline_source_expiry,
                            "fixed_days": fxd_days_ct,
                            "forward_days": fwd_days,
                            "monthly_average": baseline_month_average,
                            "meeting_month_average": _round_rate(f_month),
                            "turn_adjustment_bp": None,
                        },
                        "step_meaning": US_SR1_STEP_MEANING,
                    }
                    if policy_state_us:
                        lower = policy_state_us.get("lower")
                        upper = policy_state_us.get("upper")
                        if lower is not None and upper is not None:
                            extras["target_lower"] = float(lower)
                            extras["target_upper"] = float(upper)

                    if contracts_zq:
                        zq_by_exp: dict[str, dict] = {}
                        zq_obs: set[str] = set()
                        for zrow in contracts_zq:
                            ex = str(zrow.get("expiry") or "")
                            od = zrow.get("observation_date")
                            if zrow.get("implied_rate") is None or not od:
                                continue
                            zq_by_exp[ex] = zrow
                            zq_obs.add(str(od))
                        if (
                            len(zq_obs) == 1
                            and str(next(iter(zq_obs))) == obs_date.isoformat()
                        ):
                            zq_prior = zq_by_exp.get(prior_exp)
                            zq_meet = zq_by_exp.get(expiry_s)
                            if (
                                zq_prior is not None
                                and zq_meet is not None
                                and n_post > 0
                            ):
                                f_nov_z = float(zq_prior["implied_rate"])
                                f_dec_z = float(zq_meet["implied_rate"])
                                implied_chg = (
                                    (f_dec_z - f_nov_z) * (n_cal / n_post) * 100.0
                                )
                                extras["zq_cross_check"] = {
                                    "implied_change_bp": _round_bp(implied_chg),
                                    "method": "adjacent_month_average",
                                    "note": (
                                        "ZQ is 30-day federal funds futures on EFFR, not SOFR. "
                                        "Not an input to the SR1 solve."
                                    ),
                                }

                    solved.append((k_eff, policy_post))
                    solved_sofr.append((k_eff, f_post_sofr))
                    rows.append(
                        _row(
                            meeting,
                            policy_post,
                            inc,
                            cum,
                            "identified",
                            contracts_out,
                            extras=extras,
                        )
                    )
                    idx += 1
                    used_sr1_forward = True
                    sr1_baseline_path_started = True

                elif (
                    0 < n_post < 7
                    and prev_f_post is not None
                    and unsolved_pred_eff is None
                ):
                    next_exp = _next_month_expiry(expiry_s)
                    next_row = sr1_by_expiry.get(next_exp)
                    next_start, next_end = accrual_window(next_exp, "1m")
                    cross_ok = (
                        next_row is not None
                        and next_row.get("implied_rate") is not None
                        and _sr1_contract_live(next_exp, as_of)
                        and _accrual_window_meeting_free(
                            next_start, next_end, unresolved_cal
                        )
                    )
                    if cross_ok:
                        f_post_sofr = float(next_row["implied_rate"])
                        cross_baseline = f_baseline
                        anchor_row = baseline_contract_row or next_row
                        anchor_expiry = baseline_source_expiry or next_exp
                        if cross_baseline is None:
                            next_fixed, next_fixed_ok = (
                                _fixed_day_rates_before_observation(
                                    next_exp, obs_date, fixings_sorted
                                )
                            )
                            if next_fixed_ok:
                                n_next_cal = (next_end - next_start).days
                                cross_baseline = _forward_baseline_rate(
                                    f_post_sofr, n_next_cal, next_fixed
                                )
                            else:
                                cross_baseline = f_post_sofr
                        sum_known_cross, sk_cross = _sr1_month_pre_meeting_known_sum(
                            month_start=month_start,
                            month_end=month_end,
                            k_eff=k_eff,
                            observation_date=obs_date,
                            fixings_sorted=fixings_sorted,
                            f_baseline=cross_baseline,
                            prev_meeting_eff=prev_meeting_eff,
                            prev_f_sofr_post=prev_f_post,
                            unsolved_predecessor_eff=None,
                        )
                        if sk_cross:
                            recon_avg = (sum_known_cross + n_post * f_post_sofr) / n_cal
                            strip_residual_bp = _round_bp(
                                (recon_avg - f_month) * 100.0
                            )
                            prev_f_sofr = solved_sofr[-1][1]
                            step_sofr = f_post_sofr - prev_f_sofr
                            pol_prev = (
                                previous_post if previous_post is not None else anchor
                            )
                            policy_post = pol_prev + step_sofr
                            inc = _round_bp(step_sofr * 100.0)
                            cum = _round_bp((policy_post - anchor) * 100.0)
                            previous_post = policy_post

                            contracts_out = [
                                _contract_dict_for_output(
                                    meeting_contract, weight=1.0, role="meeting_month"
                                ),
                                _contract_dict_for_output(
                                    next_row, weight=0.0, role="cross_month_anchor"
                                ),
                            ]
                            if (
                                anchor_row is not next_row
                                and baseline_source_expiry
                            ):
                                contracts_out.append(
                                    _contract_dict_for_output(
                                        anchor_row, weight=0.0, role="forward_baseline"
                                    )
                                )

                            extras_cross: dict[str, Any] = {
                                "sofr_post_rate": _round_rate(f_post_sofr),
                                "zq_cross_check": None,
                                "baseline": {
                                    "kind": "sr1_cross_month",
                                    "rate": _round_rate(cross_baseline),
                                    "source_expiry": anchor_expiry,
                                    "fixed_days": len(realized_pre_meeting),
                                    "forward_days": None,
                                    "monthly_average": _round_rate(
                                        float(anchor_row["implied_rate"])
                                    ),
                                    "meeting_month_average": _round_rate(f_month),
                                    "turn_adjustment_bp": None,
                                },
                                "step_meaning": US_SR1_STEP_MEANING,
                                "estimate_note": US_SR1_CROSS_MONTH_ESTIMATE_NOTE,
                                "n_pre": n_pre,
                                "n_post": n_post,
                                "strip_identity_residual_bp": strip_residual_bp,
                            }
                            if policy_state_us:
                                lower = policy_state_us.get("lower")
                                upper = policy_state_us.get("upper")
                                if lower is not None and upper is not None:
                                    extras_cross["target_lower"] = float(lower)
                                    extras_cross["target_upper"] = float(upper)

                            if contracts_zq:
                                zq_by_exp: dict[str, dict] = {}
                                zq_obs: set[str] = set()
                                for zrow in contracts_zq:
                                    ex = str(zrow.get("expiry") or "")
                                    od = zrow.get("observation_date")
                                    if zrow.get("implied_rate") is None or not od:
                                        continue
                                    zq_by_exp[ex] = zrow
                                    zq_obs.add(str(od))
                                if (
                                    len(zq_obs) == 1
                                    and str(next(iter(zq_obs))) == obs_date.isoformat()
                                ):
                                    zq_meet = zq_by_exp.get(expiry_s)
                                    zq_next = zq_by_exp.get(next_exp)
                                    if zq_meet is not None and zq_next is not None:
                                        extras_cross["zq_cross_check"] = {
                                            "implied_change_bp": _round_bp(
                                                (
                                                    float(zq_next["implied_rate"])
                                                    - float(zq_meet["implied_rate"])
                                                )
                                                * 100.0
                                            ),
                                            "method": "adjacent_month_effr",
                                            "note": (
                                                "ZQ is 30-day federal funds futures on EFFR, not SOFR. "
                                                "Not an input to the SR1 solve."
                                            ),
                                        }

                            solved.append((k_eff, policy_post))
                            solved_sofr.append((k_eff, f_post_sofr))
                            rows.append(
                                _row(
                                    meeting,
                                    policy_post,
                                    inc,
                                    cum,
                                    "estimated",
                                    contracts_out,
                                    extras=extras_cross,
                                )
                            )
                            idx += 1
                            used_sr1_forward = True
                            sr1_baseline_path_started = True

                if not used_sr1_forward:
                    if sr1_baseline_path_started or solved_sofr:
                        us_sr1_path_gap = True
                    gap_reason = (
                        US_SR1_PREDECESSOR_GAP_REASON
                        if unsolved_pred_eff is not None
                        else None
                    )
                    extras_unavail: dict[str, Any] | None = (
                        {"reason": gap_reason} if gap_reason else None
                    )
                    rows.append(
                        _row(
                            meeting,
                            None,
                            None,
                            None,
                            "unavailable",
                            [],
                            extras=extras_unavail,
                        )
                    )
                    idx += 1
                    continue

        if used_sr1_forward:
            continue

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
            sr1_skip_basis = (
                bank == "US"
                and str(contract.get("product")) == "SR1"
                and (
                    sr1_baseline_path_started
                    or (
                        observation_date is not None and bool(fixings_sorted)
                    )
                )
            )
            adj = 0.0 if sr1_skip_basis else basis
            x = (total * (f - adj) - known_sum) / unknown_count
            inc = incremental_for(x)
            cum = (x - anchor) * 100.0
            solved.append((k_eff, x))
            if bank == "US" and str(contract.get("product")) == "SR1":
                solved_sofr.append((k_eff, x))
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
        sr1_skip_basis_es = (
            bank == "US"
            and str(contract.get("product")) == "SR1"
            and (
                sr1_baseline_path_started
                or (observation_date is not None and bool(fixings_sorted))
            )
        )
        adj_es = 0.0 if sr1_skip_basis_es else basis
        step = (total * (f - adj_es) - sum_base) / sum_m

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
            base_c: dict[str, Any] = {
                "product": "SR1",
                "expiry": row["expiry"],
                "period": "1m",
                "implied_rate": float(row["implied_rate"]),
            }
            for key in (
                "price",
                "source",
                "source_url",
                "observation_date",
                "as_of",
                "code",
            ):
                if row.get(key) is not None:
                    base_c[key] = row[key]
            contracts.append(base_c)
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
            base = {
                "product": "COA",
                "expiry": row["expiry"],
                "period": "1m",
                "implied_rate": float(row["implied_rate"]),
            }
            for key in (
                "price",
                "source",
                "source_url",
                "observation_date",
                "as_of",
                "code",
            ):
                if row.get(key) is not None:
                    base[key] = row[key]
            contracts.append(base)
        for row in country_paths.get("contracts_3m") or []:
            base3 = {
                "product": "CRA",
                "expiry": row["expiry"],
                "period": "3m",
                "implied_rate": float(row["implied_rate"]),
            }
            for key in (
                "price",
                "source",
                "source_url",
                "observation_date",
                "as_of",
                "code",
            ):
                if row.get(key) is not None:
                    base3[key] = row[key]
            contracts.append(base3)
        return contracts, None
    if code == "AU":
        # RBA meeting path: ASX IB (30-day interbank cash / AONIA monthly average) only.
        # contracts_3m IR settlements are 90-day BBSW and are not meeting-pricing inputs.
        for row in country_paths.get("contracts_1m") or []:
            base = {
                "product": "IB",
                "expiry": row["expiry"],
                "period": "1m",
                "implied_rate": float(row["implied_rate"]),
            }
            for key in (
                "price",
                "source",
                "source_url",
                "observation_date",
                "as_of",
                "code",
            ):
                if row.get(key) is not None:
                    base[key] = row[key]
            contracts.append(base)
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
            return [], "ESR settlements unavailable"
        for row in rows:
            base: dict[str, Any] = {
                "product": "ESR",
                "expiry": row.get("expiry"),
                "period": "3m",
                "implied_rate": float(row["implied_rate"]),
            }
            for key in (
                "code",
                "price",
                "reference_start",
                "reference_end",
                "mark_kind",
                "trade_date_verified",
                "open_interest",
                "source",
                "source_url",
                "observation_date",
                "as_of",
            ):
                if row.get(key) is not None:
                    base[key] = row[key]
            contracts.append(base)
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


def _sofr_fixings_from_country_paths(country_paths: dict) -> list[tuple[date, float]]:
    return _overnight_history_fixings(country_paths)


def _overnight_history_fixings(country_paths: dict) -> list[tuple[date, float]]:
    benchmark = country_paths.get("benchmark") or {}
    if not isinstance(benchmark, dict):
        return []
    history = benchmark.get("history")
    if not isinstance(history, list):
        return []
    out: list[tuple[date, float]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        eff_s = item.get("effective_date")
        if eff_s is None or item.get("percent_rate") is None:
            continue
        try:
            eff = _parse_date(str(eff_s))
        except ValueError:
            continue
        out.append((eff, float(item["percent_rate"])))
    out.sort(key=lambda p: p[0])
    return out


def _us_filter_sr1_contracts(country_paths: dict, as_of: date) -> list[dict]:
    rows: list[dict] = []
    for row in country_paths.get("contracts_1m") or []:
        if not isinstance(row, dict) or row.get("implied_rate") is None:
            continue
        base: dict[str, Any] = {
            "product": "SR1",
            "expiry": row["expiry"],
            "period": "1m",
            "implied_rate": float(row["implied_rate"]),
        }
        for key in (
            "price",
            "source",
            "source_url",
            "observation_date",
            "as_of",
            "code",
        ):
            if row.get(key) is not None:
                base[key] = row[key]
        rows.append(base)
    return _filter_contracts(rows, as_of)


def _us_sr1_vintage_gate(sr1_rows: list[dict], as_of: date) -> tuple[date | None, str | None]:
    if not sr1_rows:
        return None, "US policy path has no SR1 (contracts_1m) contracts"
    obs_dates: list[date] = []
    for row in sr1_rows:
        raw = row.get("observation_date")
        if raw in (None, ""):
            return None, "SR1 futures are missing observation_date"
        try:
            obs_dates.append(_parse_date(str(raw)))
        except ValueError:
            return None, "SR1 futures have invalid observation_date"
    if len(set(obs_dates)) != 1:
        return None, "SR1 futures observation_date is mixed vintage"
    obs = obs_dates[0]
    if obs > as_of:
        return None, "SR1 futures observation_date is after as_of"
    if (as_of - obs).days > 8:
        return None, "SR1 futures observation is stale (older than 8 days)"
    return obs, None


def _us_current_target_bounds(policy_state: dict | None, as_of: date) -> dict | None:
    if not policy_state:
        return None
    resolved = resolve_country(policy_state, "US", as_of)
    if resolved.get("status") != "current":
        return None
    decision = resolved.get("decision") or {}
    lower = decision.get("lower")
    upper = decision.get("upper")
    if lower is None or upper is None:
        return None
    return {"lower": float(lower), "upper": float(upper)}


_PUBLICATION_NUMERIC_METHODS = frozenset({"identified", "equal_step", "estimated"})
_US_PUBLICATION_CASCADE_REASON = (
    "prior FOMC step unavailable; path underdetermined"
)
_CA_PUBLICATION_CASCADE_REASON = (
    "prior BoC step unavailable; cumulative path underdetermined"
)
_CA_PUBLICATION_RECON_REASON = (
    "COA/CRA row missing overnight reconstruction proof or implied mismatch"
)
_AU_PUBLICATION_IB_REASON = (
    "IB month identity checks failed or proof fields missing"
)
_FINITE_POST_REASON = "policy meeting row missing finite post rate"


def _publication_row_has_finite_post(row: dict) -> bool:
    post = row.get("post_rate")
    if post is None:
        return False
    try:
        value = float(post)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value)


def _downgrade_publication_meeting_row(row: dict, reason: str) -> None:
    row["method"] = "unavailable"
    row["post_rate"] = None
    row["incremental_bp"] = None
    row["cumulative_bp"] = None
    row["reason"] = reason
    if "sofr_post_rate" in row:
        row["sofr_post_rate"] = None


def _row_primary_implied(row: dict) -> float | None:
    contracts = row.get("contracts") or []
    for role in ("meeting_month", "meeting_window"):
        for contract in contracts:
            if contract.get("role") == role and contract.get("implied_rate") is not None:
                return float(contract["implied_rate"])
    for contract in contracts:
        weight = contract.get("weight")
        if weight is not None and float(weight) >= 1.0 and contract.get("implied_rate") is not None:
            return float(contract["implied_rate"])
    for contract in contracts:
        if contract.get("implied_rate") is not None:
            return float(contract["implied_rate"])
    return None


def _ca_publication_lead_contract(row: dict) -> dict | None:
    for contract in row.get("contracts") or []:
        if contract.get("implied_rate") is None:
            continue
        weight = contract.get("weight")
        if weight is not None and float(weight) > 0:
            return contract
    return None


def _ca_publication_row_recon_ok(
    row: dict,
    *,
    initial_overnight: float,
    overnight_path: list[tuple[date, float]],
    group: list[dict] | None = None,
) -> bool:
    rows = group if group is not None else [row]
    row0 = rows[0]
    pre = row0.get("overnight_pre")
    post_o = row0.get("overnight_post")
    if pre is None or post_o is None:
        return False
    lead = _ca_publication_lead_contract(row0)
    if lead is None:
        return False
    product = lead.get("product")
    expiry = str(lead.get("expiry"))
    implied = float(lead["implied_rate"])
    try:
        if product == "COA":
            win_start, win_end = coa_accrual_window(expiry)
            k_eff = _parse_date(str(row0["effective_date"]))
            recon = _ca_coa_reconstruct_implied(
                win_start,
                win_end,
                k_eff,
                float(pre),
                float(post_o),
                observation_date=None,
                fixings_sorted=[],
            )
            return _ca_reconstruction_ok(implied, recon)
        if product == "CRA":
            cs, ce = accrual_window(expiry, "3m")
            if len(rows) > 1 or row0.get("method") == "equal_step":
                k_effs = sorted(_parse_date(r["effective_date"]) for r in rows)
                posts = [float(r["overnight_post"]) for r in rows]
                recon = _ca_cra_reconstruct_implied(
                    cs,
                    ce,
                    initial_overnight=initial_overnight,
                    solved_overnight=[
                        t for t in overnight_path if t[0] < k_effs[0]
                    ],
                    pending_k_effs=k_effs,
                    pending_posts=posts,
                    observation_date=None,
                    fixings_sorted=[],
                )
                return _ca_reconstruction_ok(implied, recon)
            k_eff = _parse_date(str(row0["effective_date"]))
            post_on = float(post_o)
            recon = _ca_cra_reconstruct_implied(
                cs,
                ce,
                initial_overnight=initial_overnight,
                solved_overnight=[t for t in overnight_path if t[0] < k_eff],
                pending_k_effs=[k_eff],
                pending_posts=[post_on],
                observation_date=None,
                fixings_sorted=[],
            )
            return _ca_reconstruction_ok(implied, recon)
    except (ValueError, TypeError, KeyError):
        return False
    return False


def _guard_ca_publication_meetings(bank: dict) -> None:
    meetings = bank.get("meetings")
    if not isinstance(meetings, list):
        return
    anchor = bank.get("anchor")
    fixing = bank.get("fixing")
    initial_overnight: float | None
    if anchor is None or fixing is None:
        initial_overnight = None
    else:
        initial_overnight = float(anchor) + (float(fixing) - float(anchor))

    ordered = sorted(meetings, key=lambda row: row.get("effective_date") or "")
    overnight_path: list[tuple[date, float]] = []
    cascade = False
    idx = 0
    while idx < len(ordered):
        row = ordered[idx]
        if not isinstance(row, dict):
            idx += 1
            continue
        if cascade:
            if row.get("method") in _PUBLICATION_NUMERIC_METHODS and _publication_row_has_finite_post(
                row
            ):
                _downgrade_publication_meeting_row(row, _CA_PUBLICATION_CASCADE_REASON)
            idx += 1
            continue
        if row.get("method") == "unavailable":
            cascade = True
            idx += 1
            continue
        if row.get("method") not in _PUBLICATION_NUMERIC_METHODS:
            idx += 1
            continue
        if not _publication_row_has_finite_post(row):
            _downgrade_publication_meeting_row(row, _FINITE_POST_REASON)
            cascade = True
            idx += 1
            continue
        if initial_overnight is None:
            _downgrade_publication_meeting_row(row, _CA_PUBLICATION_RECON_REASON)
            cascade = True
            idx += 1
            continue

        if row.get("method") == "equal_step":
            lead = _ca_publication_lead_contract(row)
            if lead is None:
                _downgrade_publication_meeting_row(row, _CA_PUBLICATION_RECON_REASON)
                cascade = True
                idx += 1
                continue
            expiry = str(lead["expiry"])
            group: list[dict] = []
            j = idx
            while j < len(ordered):
                candidate = ordered[j]
                if candidate.get("method") != "equal_step":
                    break
                lead2 = _ca_publication_lead_contract(candidate)
                if lead2 is None or str(lead2.get("expiry")) != expiry:
                    break
                group.append(candidate)
                j += 1
            if not _ca_publication_row_recon_ok(
                row,
                initial_overnight=initial_overnight,
                overnight_path=overnight_path,
                group=group,
            ):
                for member in group:
                    _downgrade_publication_meeting_row(
                        member, _CA_PUBLICATION_RECON_REASON
                    )
                cascade = True
                idx = j
                continue
            for member in group:
                k_eff = _parse_date(str(member["effective_date"]))
                overnight_path.append((k_eff, float(member["overnight_post"])))
            idx = j
            continue

        if not _ca_publication_row_recon_ok(
            row,
            initial_overnight=initial_overnight,
            overnight_path=overnight_path,
        ):
            _downgrade_publication_meeting_row(row, _CA_PUBLICATION_RECON_REASON)
            cascade = True
            idx += 1
            continue
        k_eff = _parse_date(str(row["effective_date"]))
        overnight_path.append((k_eff, float(row["overnight_post"])))
        idx += 1


def _guard_au_publication_row(row: dict) -> str | None:
    method = row.get("method")
    if method not in _PUBLICATION_NUMERIC_METHODS:
        return None
    if not _publication_row_has_finite_post(row):
        return _FINITE_POST_REASON
    n_pre = row.get("n_pre")
    n_post = row.get("n_post")
    month_days = row.get("ib_month_days")
    residual = row.get("ib_identity_residual_bp")
    prior = row.get("ib_prior_forward")
    post_level = row.get("ib_post_level")
    if any(v is None for v in (prior, post_level)):
        return _AU_PUBLICATION_IB_REASON
    if n_pre is not None and n_post is not None and month_days is not None:
        if int(n_pre) + int(n_post) != int(month_days) or int(n_pre) > int(month_days):
            return _AU_PUBLICATION_IB_REASON
        if residual is not None and float(residual) > 0.05:
            return _AU_PUBLICATION_IB_REASON
        return None
    k_eff_s = row.get("effective_date")
    if not k_eff_s:
        return _AU_PUBLICATION_IB_REASON
    k_eff = _parse_date(k_eff_s)
    contracts = row.get("contracts") or []
    meeting_contract = next(
        (c for c in contracts if c.get("role") == "meeting_month"),
        None,
    )
    if meeting_contract is None or not meeting_contract.get("expiry"):
        return _AU_PUBLICATION_IB_REASON
    month_start, month_end = accrual_window(str(meeting_contract["expiry"]), "1m")
    n_tot = (month_end - month_start).days
    n_pre_ct = sum(1 for _ in _iter_calendar_days(month_start, min(k_eff, month_end)))
    n_post_ct = n_tot - n_pre_ct
    if n_pre_ct > n_tot or n_pre_ct + n_post_ct != n_tot:
        return _AU_PUBLICATION_IB_REASON
    implied = _row_primary_implied(row)
    if implied is None:
        return _AU_PUBLICATION_IB_REASON
    recon = _ib_monthly_from_levels(
        month_start, month_end, k_eff, float(prior), float(post_level)
    )
    if abs(recon - implied) * 100.0 > 0.05:
        return _AU_PUBLICATION_IB_REASON
    return None


def _guard_us_publication_meetings(meetings: list[dict]) -> None:
    ordered = sorted(meetings, key=lambda row: row.get("effective_date") or "")
    cascade = False
    for row in ordered:
        if cascade:
            if row.get("method") in _PUBLICATION_NUMERIC_METHODS and _publication_row_has_finite_post(row):
                _downgrade_publication_meeting_row(row, _US_PUBLICATION_CASCADE_REASON)
            continue
        if row.get("method") == "unavailable":
            cascade = True
            continue
        if row.get("method") in _PUBLICATION_NUMERIC_METHODS:
            if not _publication_row_has_finite_post(row):
                _downgrade_publication_meeting_row(row, _FINITE_POST_REASON)
                cascade = True


def guard_policy_meeting_prices_for_publication(block: dict | None) -> dict | None:
    """Downgrade individual meeting rows that fail publication invariants."""
    if not isinstance(block, dict):
        return block
    banks = block.get("banks")
    if not isinstance(banks, dict):
        return block
    for code, bank in banks.items():
        if not isinstance(bank, dict):
            continue
        meetings = bank.get("meetings")
        if not isinstance(meetings, list):
            continue
        if code == "US":
            _guard_us_publication_meetings(meetings)
        elif code == "CA":
            _guard_ca_publication_meetings(bank)
            continue
        for row in meetings:
            if not isinstance(row, dict):
                continue
            reason: str | None = None
            if code == "AU":
                reason = _guard_au_publication_row(row)
            elif row.get("method") in _PUBLICATION_NUMERIC_METHODS:
                if not _publication_row_has_finite_post(row):
                    reason = _FINITE_POST_REASON
            if reason:
                _downgrade_publication_meeting_row(row, reason)
    return block


def load_policy_meeting_prices_for_publication(path: Path) -> dict | None:
    """Load the checked-in sidecar and apply publication guards."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return guard_policy_meeting_prices_for_publication(payload)


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

        us_sr1_gate_reason: str | None = None
        us_obs_date: date | None = None
        if code == "US" and paths_status in {"ok", "partial"}:
            raw_sr1 = country_paths.get("contracts_1m")
            if str(country_paths.get("sr1_freshness") or "") == "stale":
                us_sr1_gate_reason = "SR1 futures are retained stale"
            elif not isinstance(raw_sr1, list) or not raw_sr1:
                us_sr1_gate_reason = (
                    "US policy path has no SR1 (contracts_1m) contracts"
                )
            else:
                sr1_for_gate = _us_filter_sr1_contracts(country_paths, as_of)
                us_obs_date, us_sr1_gate_reason = _us_sr1_vintage_gate(
                    sr1_for_gate, as_of
                )
            if not us_sr1_gate_reason and us_obs_date is not None:
                futures_as_of = us_obs_date.isoformat()

        ca_au_gate_reason: str | None = None
        ca_au_obs_date: date | None = None
        if code in {"CA", "AU"} and paths_status in {"ok", "partial"}:
            ca_au_rows: list[dict] = []
            if code == "CA":
                for row in country_paths.get("contracts_1m") or []:
                    if isinstance(row, dict) and row.get("implied_rate") is not None:
                        ca_au_rows.append(row)
                for row in country_paths.get("contracts_3m") or []:
                    if isinstance(row, dict) and row.get("implied_rate") is not None:
                        ca_au_rows.append(row)
            else:
                for row in country_paths.get("contracts_1m") or []:
                    if isinstance(row, dict) and row.get("implied_rate") is not None:
                        ca_au_rows.append(row)
            ca_au_obs_date, ca_au_gate_reason = _ca_au_observation_gate(ca_au_rows)
            if not ca_au_gate_reason and ca_au_obs_date is not None:
                futures_as_of = ca_au_obs_date.isoformat()
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

        if contract_reason in {"ESR settlements unavailable", "FST3 is absent"}:
            status = "unavailable"
            reason = (
                "ESR settlements unavailable"
                if contract_reason == "FST3 is absent"
                else contract_reason
            )
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

        if code == "EA":
            from scripts.rates.ecb_meeting_pricing import ECB_METHOD_NOTE, price_ecb_meetings

            hist_fixings: list[tuple[date, float]] = []
            benchmark = country_paths.get("benchmark") or {}
            for item in benchmark.get("history") or []:
                if not isinstance(item, dict):
                    continue
                eff = item.get("effective_date")
                rate = item.get("percent_rate")
                if eff and rate is not None:
                    hist_fixings.append((_parse_date(str(eff)), float(rate)))
            esr_fresh = str(country_paths.get("esr_freshness") or "unavailable")
            if esr_fresh not in {"fresh", "stale"}:
                esr_fresh = "unavailable"
            futures_as_of = country_paths.get("futures_as_of") or futures_as_of
            priced_rows, bank_reason = price_ecb_meetings(
                as_of=as_of,
                anchor=anchor,
                fixing=fixing,
                history=hist_fixings,
                meetings=meetings_cal,
                contracts=contract_list,
                futures_freshness=esr_fresh,
            )
            meetings_out = []
            for row in priced_rows:
                chg_1d, chg_1w = _lookup_history_changes(
                    history_doc,
                    as_of,
                    code,
                    row["decision_date"],
                    row.get("cumulative_bp"),
                )
                mt = {
                    "instrument_id": f"PM:{code}:{row['decision_date']}",
                    "decision_date": row["decision_date"],
                    "effective_date": row["effective_date"],
                    "post_rate": row.get("post_rate"),
                    "incremental_bp": row.get("incremental_bp"),
                    "cumulative_bp": row.get("cumulative_bp"),
                    "method": row.get("method"),
                    "contracts": row.get("contracts") or [],
                    "chg_1d_bp": chg_1d,
                    "chg_1w_bp": chg_1w,
                }
                if row.get("reason"):
                    mt["reason"] = row["reason"]
                meetings_out.append(mt)
            future_rows = [
                row
                for row in meetings_out
                if _parse_date(str(row["effective_date"])) > as_of
            ]
            if not future_rows:
                ea_status = "unavailable"
                ea_reason = bank_reason or "No future ECB meetings"
            elif all(row.get("method") == "identified" for row in future_rows):
                ea_status = "ok"
                ea_reason = None
            elif any(row.get("method") == "identified" for row in future_rows):
                ea_status = "partial"
                ea_reason = bank_reason
            else:
                ea_status = "unavailable"
                ea_reason = bank_reason or "ESR windows do not identify meetings"
            banks_out[code] = {
                "status": ea_status,
                "reason": ea_reason,
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": meetings_out,
                "step_meaning": ECB_METHOD_NOTE,
            }
            continue

        if code == "US" and us_sr1_gate_reason:
            banks_out[code] = {
                "status": "unavailable",
                "reason": us_sr1_gate_reason,
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": _unavailable_meeting_rows_for_bank(
                    code, meetings_cal, as_of
                ),
            }
            continue

        if code in {"CA", "AU"} and ca_au_gate_reason:
            banks_out[code] = {
                "status": "unavailable",
                "reason": ca_au_gate_reason,
                "anchor": anchor,
                "fixing": fixing,
                "basis_bp": basis_bp,
                "futures_as_of": futures_as_of,
                "calendar_retrieved_at": calendar_retrieved_at,
                "meetings": _unavailable_meeting_rows_for_bank(
                    code, meetings_cal, as_of
                ),
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
        cal_us = _calendar_meetings(calendar, "US")
        policy_us_bounds = _us_current_target_bounds(policy_state, as_of)
        contracts_zq = country_paths.get("contracts_zq")
        if not isinstance(contracts_zq, list):
            contracts_zq = None
        try:
            ca_au_hist = (
                _overnight_history_fixings(country_paths)
                if code in {"CA", "AU"}
                else []
            )
            priced_rows = price_meetings(
                bank=code,
                as_of=as_of,
                anchor=anchor,
                basis=basis,
                meetings=meetings_cal,
                contracts=contract_list,
                history=hist,
                sofr_fixings=_sofr_fixings_from_country_paths(country_paths)
                if code == "US"
                else ca_au_hist,
                observation_date=(
                    us_obs_date
                    if code == "US"
                    else ca_au_obs_date
                    if code in {"CA", "AU"}
                    else None
                ),
                calendar_meetings_us=cal_us if code == "US" else None,
                contracts_zq=contracts_zq if code == "US" else None,
                policy_state_us=policy_us_bounds if code == "US" else None,
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
            mt: dict[str, Any] = {
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
            for optional_key in (
                "baseline",
                "sofr_post_rate",
                "step_meaning",
                "target_lower",
                "target_upper",
                "zq_cross_check",
                "overnight_pre",
                "overnight_post",
                "ib_prior_forward",
                "ib_post_level",
                "estimate_note",
                "reason",
                "vintage_note",
                "ib_month_days",
                "n_pre",
                "n_post",
                "ib_identity_residual_bp",
                "strip_identity_residual_bp",
                "estimate_note",
            ):
                if optional_key in row:
                    mt[optional_key] = row[optional_key]
            meetings_out.append(mt)

        if status != "ok" and meetings_out:
            for row in meetings_out:
                if row["method"] != "unavailable":
                    status = "partial"
                    reason = None
                    break

        if code == "US" and status == "ok" and meetings_out:
            future_rows = [
                row
                for row in meetings_out
                if _parse_date(str(row["effective_date"])) > as_of
            ]
            if future_rows:
                methods = {str(row.get("method") or "") for row in future_rows}
                if "unavailable" in methods and methods & {"identified", "estimated"}:
                    status = "partial"
                elif methods == {"unavailable"}:
                    status = "unavailable"
                    reason = US_SR1_PREDECESSOR_GAP_REASON

        bank_block: dict[str, Any] = {
            "status": status,
            "reason": reason,
            "anchor": anchor,
            "fixing": fixing,
            "basis_bp": basis_bp,
            "futures_as_of": futures_as_of,
            "calendar_retrieved_at": calendar_retrieved_at,
            "meetings": meetings_out,
        }
        if code in {"US", "CA", "AU"}:
            for mt in meetings_out:
                if not isinstance(mt, dict):
                    continue
                if mt.get("step_meaning"):
                    bank_block["step_meaning"] = mt["step_meaning"]
                if mt.get("target_lower") is not None:
                    bank_block["target_lower"] = mt["target_lower"]
                if mt.get("target_upper") is not None:
                    bank_block["target_upper"] = mt["target_upper"]
                zq = mt.get("zq_cross_check")
                if zq is not None:
                    bank_block["zq_cross_check"] = zq
                if bank_block.get("step_meaning"):
                    break
        guard_policy_meeting_prices_for_publication(
            {"banks": {code: bank_block}}
        )
        banks_out[code] = bank_block

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
