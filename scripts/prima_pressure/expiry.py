"""Authoritative listed-contract expiry for Prima oil futures.

Activity and quote freshness are different facts. A completed bar, however
recent, is not evidence that a futures contract is still the front month.

Rules, quoted from the exchange and applied with the holiday calendars below:

* Brent Last Day Financial Futures (BZ), NYMEX Rulebook Chapter 698,
  rule 698102.E (same termination day as ICE Brent):
  "Trading shall cease at the end of the designated settlement period on the
  last Business Day of the second month preceding the relevant contract month.
  If the day on which trading is due to cease would be either (i) the Business
  Day preceding Christmas Day, or (ii) the Business Day preceding New Year's
  Day, then trading shall cease on the next preceding Business Day."
  Sources:
  https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/6/698.pdf
  https://www.ice.com/products/219/Brent-Crude-Futures/expiry

  A Business Day here is a weekday that is not a public holiday in England
  and Wales (New Year's Day with weekend substitute, Good Friday, Easter
  Monday, the early-May / spring / summer bank holidays, Christmas and Boxing
  Day with weekend substitutes). An open ICE Brent session is not a London
  business day when the date is still an England-and-Wales bank holiday. Do
  not infer business days from the IFEU trading schedule.

* Light Sweet Crude Oil (CL), NYMEX Rulebook Chapter 200, rule 200102.F:
  "No trades in Light Sweet Crude Oil futures in the expiring contract month
  shall be made after the third business day prior to the twenty-fifth
  calendar day of the month preceding the delivery month for such expiring
  contract. If the twenty-fifth calendar day of the month is a non-business
  day, trading shall cease on the third business day prior to the last
  business day preceding the twenty-fifth calendar day of the month preceding
  the delivery month."
  If that date is an exchange holiday, expiration moves to the prior business
  day, as the same rule provides.
  Source: https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/2/200.pdf

* RBOB Gasoline (RB), NYMEX Chapter 191 rule 191102.F, and NY Harbor ULSD (HO),
  Chapter 150 rule 150102.F: no trades after the last business day of the month
  preceding the delivery month.
  Sources:
  https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/1a/191.pdf
  https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/1a/150.pdf

A NYMEX business day is a weekday that is not a full-closure holiday:
New Year's Day, Martin Luther King Jr. Day, Presidents' Day, Good Friday,
Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, and
Christmas, with Saturday/Sunday fixed-date holidays observed on Friday/Monday.
Early closes (the session after Thanksgiving, Christmas Eve when it is not the
Christmas observation) remain business days. Columbus Day and Veterans Day are
not NYMEX closures.

The contract is active on its final trade date, inclusive, because that date
is the last session on which trading occurs. It is inactive on every later
calendar day, including the weekend and the first business day after expiry.

Holiday coverage is the documented rule for 2025-2032. Outside that window
expiry metadata is unavailable and selection fails closed.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from scripts.prima_pressure.contract import MONTH_CODES, add_months, contract_symbol, period_key

CALENDAR_YEAR_MIN = 2025
CALENDAR_YEAR_MAX = 2032

BRENT_RULE_ID = "nymex_698102_e_brent_last_day"
BRENT_RULE_SOURCE = "https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/6/698.pdf"
LONDON_BUSINESS_DAY_SOURCE = "https://www.ice.com/products/219/Brent-Crude-Futures/expiry"

CL_RULE_ID = "nymex_200102_f_light_sweet_crude"
CL_RULE_SOURCE = "https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/2/200.pdf"

RB_RULE_ID = "nymex_191102_f_rbob"
RB_RULE_SOURCE = "https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/1a/191.pdf"

HO_RULE_ID = "nymex_150102_f_ny_harbor_ulsd"
HO_RULE_SOURCE = "https://www.cmegroup.com/content/dam/cmegroup/rulebook/NYMEX/1a/150.pdf"

_LISTED_SYMBOL_RE = re.compile(rf"^({'BZ|CL|RB|HO'})([FGHJKMNQUVXZ])(\d{{2}})\.NYM$")
_ROOTS = ("BZ", "CL", "RB", "HO")


class ExpiryError(Exception):
    """Deterministic expiry failure. ``reason`` is a stable machine code."""

    reason = "expiry_calendar_unavailable"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason


class ExpiryCalendarUnavailable(ExpiryError):
    reason = "expiry_calendar_unavailable"


class InvalidContractIdentity(ExpiryError):
    reason = "invalid_contract_identity"


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
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


def _require_year(year: int) -> None:
    if year < CALENDAR_YEAR_MIN or year > CALENDAR_YEAR_MAX:
        raise ExpiryCalendarUnavailable(
            f"expiry calendar is not documented for {year}; "
            f"coverage is {CALENDAR_YEAR_MIN}-{CALENDAR_YEAR_MAX}"
        )


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def _observed_weekday(year: int, month: int, day: int) -> date:
    """Saturday observes Friday; Sunday observes Monday. Weekdays stay put."""
    value = date(year, month, day)
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _new_years_observed(year: int) -> date:
    value = date(year, 1, 1)
    if value.weekday() == 5:
        return date(year - 1, 12, 31)
    if value.weekday() == 6:
        return date(year, 1, 2)
    return value


def nymex_full_closures(year: int) -> frozenset[date]:
    """Full-closure NYMEX dates in ``year``. Early closes are omitted on purpose."""
    _require_year(year)
    closures = {
        _new_years_observed(year),
        _nth_weekday(year, 1, 0, 3),  # MLK, third Monday
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_weekday(year, 6, 19),  # Juneteenth
        _observed_weekday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_weekday(year, 12, 25),
    }
    # Jan 1 on Saturday is observed the previous Friday, which falls in this year
    # when we are generating the prior year's set.
    if date(year + 1, 1, 1).weekday() == 5:
        closures.add(date(year, 12, 31))
    if date(year, 1, 1).weekday() == 5:
        closures.discard(date(year, 1, 1))
    return frozenset(d for d in closures if d.year == year)


def _nominal_england_wales_holidays(year: int) -> list[date]:
    easter = _easter_sunday(year)
    return [
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        _nth_weekday(year, 5, 0, 1),
        _last_weekday(year, 5, 0),
        _last_weekday(year, 8, 0),
        date(year, 12, 25),
        date(year, 12, 26),
    ]


def england_wales_bank_holidays(year: int) -> frozenset[date]:
    """England and Wales public holidays in ``year``, including weekend substitutes."""
    _require_year(year)
    nominals = sorted(_nominal_england_wales_holidays(year))
    holidays: set[date] = set()
    for nominal in nominals:
        if nominal.weekday() < 5:
            holidays.add(nominal)
    for nominal in nominals:
        if nominal.weekday() >= 5:
            cursor = nominal
            for _ in range(14):
                cursor += timedelta(days=1)
                if cursor.weekday() < 5 and cursor not in holidays:
                    holidays.add(cursor)
                    break
            else:
                raise ExpiryCalendarUnavailable(
                    f"no substitute weekday for England/Wales holiday {nominal.isoformat()}"
                )
    return frozenset(d for d in holidays if d.year == year)


def is_nymex_business_day(value: date) -> bool:
    _require_year(value.year)
    if value.weekday() >= 5:
        return False
    return value not in nymex_full_closures(value.year)


def is_london_business_day(value: date) -> bool:
    _require_year(value.year)
    if value.weekday() >= 5:
        return False
    return value not in england_wales_bank_holidays(value.year)


def _nth_prior(predicate, origin: date, n: int) -> date:
    if n < 1:
        raise ExpiryCalendarUnavailable(f"business-day count must be positive, got {n}")
    cursor = origin
    found = 0
    for _ in range(400):
        cursor -= timedelta(days=1)
        _require_year(cursor.year)
        if predicate(cursor):
            found += 1
            if found == n:
                return cursor
    raise ExpiryCalendarUnavailable(f"no business day {n} prior to {origin.isoformat()}")


def _previous(predicate, origin: date) -> date:
    return _nth_prior(predicate, origin, 1)


def _last_in_month(year: int, month: int, predicate) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    for _ in range(40):
        _require_year(cursor.year)
        if predicate(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise ExpiryCalendarUnavailable(f"no business day in {year:04d}-{month:02d}")


def brent_final_trade_date(year: int, month: int) -> date:
    """Last trading day of BZ year/month under rule 698102.E."""
    if month < 1 or month > 12:
        raise InvalidContractIdentity(f"month out of range: {month}")
    expiry_year, expiry_month = add_months(year, month, -2)
    candidate = _last_in_month(expiry_year, expiry_month, is_london_business_day)
    if expiry_month == 12:
        christmas = date(expiry_year, 12, 25)
        new_years = date(expiry_year + 1, 1, 1)
        preceding_christmas = _previous(is_london_business_day, christmas)
        preceding_new_years = _previous(is_london_business_day, new_years)
        if candidate in (preceding_christmas, preceding_new_years):
            candidate = _previous(is_london_business_day, candidate)
    _require_year(candidate.year)
    return candidate


def wti_final_trade_date(year: int, month: int) -> date:
    """Last trading day of CL year/month under rule 200102.F."""
    if month < 1 or month > 12:
        raise InvalidContractIdentity(f"month out of range: {month}")
    prior_year, prior_month = add_months(year, month, -1)
    anchor = date(prior_year, prior_month, 25)
    _require_year(anchor.year)
    if is_nymex_business_day(anchor):
        last = _nth_prior(is_nymex_business_day, anchor, 3)
    else:
        preceding = _previous(is_nymex_business_day, anchor)
        last = _nth_prior(is_nymex_business_day, preceding, 3)
    if not is_nymex_business_day(last):
        last = _previous(is_nymex_business_day, last)
    return last


def product_final_trade_date(year: int, month: int) -> date:
    """Last trading day of RB or HO: last NYMEX business day of the prior month."""
    if month < 1 or month > 12:
        raise InvalidContractIdentity(f"month out of range: {month}")
    prior_year, prior_month = add_months(year, month, -1)
    return _last_in_month(prior_year, prior_month, is_nymex_business_day)


def rule_for_root(root: str) -> dict[str, str]:
    if root == "BZ":
        return {
            "expiry_rule_id": BRENT_RULE_ID,
            "expiry_source": BRENT_RULE_SOURCE,
            "business_day_source": LONDON_BUSINESS_DAY_SOURCE,
        }
    if root == "CL":
        return {
            "expiry_rule_id": CL_RULE_ID,
            "expiry_source": CL_RULE_SOURCE,
            "business_day_source": CL_RULE_SOURCE,
        }
    if root == "RB":
        return {
            "expiry_rule_id": RB_RULE_ID,
            "expiry_source": RB_RULE_SOURCE,
            "business_day_source": RB_RULE_SOURCE,
        }
    if root == "HO":
        return {
            "expiry_rule_id": HO_RULE_ID,
            "expiry_source": HO_RULE_SOURCE,
            "business_day_source": HO_RULE_SOURCE,
        }
    raise InvalidContractIdentity(f"unsupported futures root: {root}")


def final_trade_date(root: str, year: int, month: int) -> date:
    if root == "BZ":
        return brent_final_trade_date(year, month)
    if root == "CL":
        return wti_final_trade_date(year, month)
    if root in ("RB", "HO"):
        return product_final_trade_date(year, month)
    raise InvalidContractIdentity(f"unsupported futures root: {root}")


def contract_is_active(root: str, year: int, month: int, as_of: date) -> bool:
    """True only through the final trade date. Quote age is not an input."""
    return as_of <= final_trade_date(root, year, month)


def parse_listed_symbol(symbol: str) -> tuple[str, int, int]:
    """Return root, year, month for a specific ``*.NYM`` contract symbol."""
    match = _LISTED_SYMBOL_RE.fullmatch(str(symbol or ""))
    if match is None:
        raise InvalidContractIdentity(f"invalid listed futures symbol: {symbol!r}")
    root = match.group(1)
    month = MONTH_CODES.index(match.group(2)) + 1
    year = 2000 + int(match.group(3))
    if root not in _ROOTS:
        raise InvalidContractIdentity(f"unsupported futures root: {root}")
    return root, year, month


def active_front_contract(as_of: date, root: str) -> dict[str, Any]:
    """Nearest listed month that is still active on ``as_of``.

    Enumeration is by the expiry calendar only. Expired months are recorded
    and are not eligible to become the front because a quote exists.
    """
    rule = rule_for_root(root)
    year, month = add_months(as_of.year, as_of.month, -1)
    rejections: list[dict[str, Any]] = []
    prior: dict[str, Any] | None = None
    for _ in range(24):
        try:
            last = final_trade_date(root, year, month)
        except ExpiryError:
            raise
        except Exception as exc:
            raise ExpiryCalendarUnavailable(str(exc)) from exc
        record = {
            "contract_month": period_key(year, month),
            "symbol": contract_symbol(root, year, month),
            "final_trade_date": last.isoformat(),
            "active_as_of": as_of <= last,
        }
        if as_of <= last:
            roll_reason = "first_listed_active" if prior is None else "prior_contract_past_final_trade"
            return {
                **rule,
                "root": root,
                "year": year,
                "month": month,
                "contract_month": record["contract_month"],
                "symbol": record["symbol"],
                "final_trade_date": last,
                "active_as_of": True,
                "as_of": as_of.isoformat(),
                "roll_reason": roll_reason,
                "prior_contract": prior,
                "rejected_expired": rejections,
            }
        record["reason"] = "expired_contract"
        rejections.append(record)
        prior = record
        year, month = add_months(year, month, 1)
    raise ExpiryCalendarUnavailable(
        f"no active {root} contract within 24 months of {as_of.isoformat()}"
    )


def maturity_contract(as_of: date, root: str, maturity_months: int) -> dict[str, Any]:
    """Listed month ``maturity_months`` after the active front. No substitution."""
    front = active_front_contract(as_of, root)
    year, month = add_months(front["year"], front["month"], int(maturity_months))
    last = final_trade_date(root, year, month)
    active = as_of <= last
    return {
        "maturity_months": int(maturity_months),
        "year": year,
        "month": month,
        "contract_month": period_key(year, month),
        "symbol": contract_symbol(root, year, month),
        "final_trade_date": last,
        "active_as_of": active,
        "front_contract_month": front["contract_month"],
        "expiry_rule_id": front["expiry_rule_id"],
        "expiry_source": front["expiry_source"],
        "reason": None if active else "expired_contract",
    }


def validate_stored_oil_row(row: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Check one stored futures input against the expiry rule for ``as_of``.

    Does not invent a replacement price or maturity. Invalid rows stay invalid.
    """
    symbol = row.get("symbol")
    contract_month = row.get("contract_month")
    maturity = row.get("maturity_months")
    base: dict[str, Any] = {
        "symbol": symbol,
        "contract_month": contract_month,
        "maturity_months": maturity,
        "valid": False,
        "reasons": [],
        "reason": None,
        "final_trade_date": None,
        "active_as_of": None,
        "expected_contract_month": None,
        "expected_symbol": None,
        "expiry_rule_id": None,
    }
    try:
        root, year, month = parse_listed_symbol(str(symbol or ""))
    except ExpiryError as exc:
        base["reasons"] = [exc.reason]
        base["reason"] = exc.reason
        base["detail"] = str(exc)
        return base

    identity_month = period_key(year, month)
    expected_symbol = contract_symbol(root, year, month)
    reasons: list[str] = []
    if contract_month != identity_month or symbol != expected_symbol:
        reasons.append("invalid_contract_identity")
    try:
        maturity_i = int(maturity)
    except (TypeError, ValueError):
        reasons.append("invalid_contract_identity")
        maturity_i = None
    try:
        last = final_trade_date(root, year, month)
        rule = rule_for_root(root)
        front = active_front_contract(as_of, root)
    except ExpiryError as exc:
        reasons.append(exc.reason)
        base["reasons"] = reasons
        base["reason"] = reasons[0]
        base["detail"] = str(exc)
        return base

    active = as_of <= last
    expected_month = None
    expected_listed = None
    if maturity_i is not None:
        try:
            target = maturity_contract(as_of, root, maturity_i)
            expected_month = target["contract_month"]
            expected_listed = target["symbol"]
        except ExpiryError as exc:
            reasons.append(exc.reason)
    if not active:
        reasons.append("expired_contract")
    if expected_month is not None and contract_month != expected_month:
        reasons.append("misanchored_maturity")

    unique: list[str] = []
    for item in reasons:
        if item not in unique:
            unique.append(item)
    base.update(
        {
            "valid": not unique,
            "reasons": unique,
            "reason": unique[0] if unique else None,
            "final_trade_date": last.isoformat(),
            "active_as_of": active,
            "expected_contract_month": expected_month,
            "expected_symbol": expected_listed,
            "expiry_rule_id": rule["expiry_rule_id"],
            "front_contract_month": front["contract_month"],
        }
    )
    return base


def assess_stored_shock_inputs(block: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Validate stored shock-persistence futures inputs for one accepted run.

    Runs with no listed futures inputs are left alone. Any invalid listed input
    makes the oil observation invalid. This does not rewrite the stored block
    and does not substitute another contract.
    """
    evidence = block.get("channel_evidence") if isinstance(block, dict) else None
    shock = evidence.get("shock_persistence") if isinstance(evidence, dict) else None
    inputs = shock.get("inputs") if isinstance(shock, dict) else None
    rows = [row for row in inputs or [] if isinstance(row, dict)]
    oil_rows = [
        row
        for row in rows
        if row.get("symbol") or row.get("contract_month") or row.get("maturity_months") is not None
    ]
    if not oil_rows:
        return {
            "status": "no_futures_inputs",
            "valid": True,
            "as_of": as_of.isoformat(),
            "findings": [],
        }
    findings = [validate_stored_oil_row(row, as_of) for row in oil_rows]
    invalid = [item for item in findings if not item["valid"]]
    return {
        "status": "invalid" if invalid else "valid",
        "valid": not invalid,
        "as_of": as_of.isoformat(),
        "findings": findings,
    }
