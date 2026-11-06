"""Paper booking for synthetic policy-meeting instruments.

The quote, the lot count, and the DV01 used at entry are the same ones used
on later marks, adds, reduces, closes, and settlement. This is not a second
ledger. Positions stay on the existing book.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from scripts.overnight.errors import SchemaError
from scripts.policy_meeting_pricing import quote_for_expression
from scripts.rates.contract_economics import current_fx_quote, whole_lots

CONSTRUCTION_VERSION = "policy_meeting_v1"
VALUATION_METHOD = "policy_meeting_dv01"
BOOKABLE_METHODS = frozenset({"identified", "equal_step"})

# Published bp values. JP is not added to contract_economics.SPECS.
_ANCHOR = {
    "US": {"product": "SR3", "currency": "USD", "face": 1_000_000.0, "dv01": 25.0, "pair": None},
    "CA": {"product": "CRA", "currency": "CAD", "face": 1_000_000.0, "dv01": 25.0, "pair": "USDCAD"},
    "AU": {"product": "IB", "currency": "AUD", "face": 3_000_000.0, "dv01": 24.66, "pair": "AUDUSD"},
    "JP": {"product": "TOA3M", "currency": "JPY", "face": 100_000_000.0, "dv01": 2500.0, "pair": "USDJPY"},
}


class PolicyMeetingHeld(Exception):
    """The entry date is no longer on the calendar. Keep the last mark."""


def _prices(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(market_state, Mapping):
        raise SchemaError("policy meeting mark needs market_state")
    block = market_state.get("policy_meeting_prices")
    if not isinstance(block, dict):
        raise SchemaError("policy_meeting_prices missing")
    return block


def _bank_block(prices: Mapping[str, Any], bank: str) -> dict[str, Any]:
    banks = prices.get("banks") if isinstance(prices.get("banks"), dict) else {}
    block = banks.get(bank)
    if not isinstance(block, dict):
        raise SchemaError(f"policy meeting prices missing for {bank}")
    return block


def _fx_usd(currency: str, market_state: Mapping[str, Any] | None, *, locked: float | None = None) -> float:
    if locked is not None:
        return float(locked)
    if currency == "USD":
        return 1.0
    quote = current_fx_quote(currency, market_state)
    if quote.get("status") == "ok" and quote.get("usd_per_unit") is not None:
        return float(quote["usd_per_unit"])
    spec = next(row for row in _ANCHOR.values() if row["currency"] == currency)
    pair = spec["pair"]
    fx = (market_state or {}).get("fx") if isinstance(market_state, Mapping) else None
    pairs = fx.get("pairs") if isinstance(fx, Mapping) else None
    row = pairs.get(pair) if isinstance(pairs, Mapping) and pair else None
    spot = row.get("spot") if isinstance(row, Mapping) else None
    if spot in (None, "") or pair is None:
        raise SchemaError(f"{currency} USD conversion unavailable for a policy meeting")
    spot_f = float(spot)
    if spot_f <= 0:
        raise SchemaError(f"{currency} FX spot is not positive")
    if pair.startswith("USD"):
        return 1.0 / spot_f
    return spot_f


def lots_for(notional_usd: float, bank: str, fx_usd_per_unit: float) -> int:
    spec = _ANCHOR[bank]
    face_usd = spec["face"] * fx_usd_per_unit
    if face_usd <= 0 or notional_usd <= 0:
        return 0
    return whole_lots(notional_usd / face_usd)


def _official_rate(decision: Mapping[str, Any]) -> float | None:
    if decision.get("lower") is not None and decision.get("upper") is not None:
        return (float(decision["lower"]) + float(decision["upper"])) / 2.0
    if decision.get("rate") is not None:
        return float(decision["rate"])
    return None


def attach_outcomes(
    block: dict[str, Any],
    policy_state: Mapping[str, Any] | None,
    as_of: date,
    calendar: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy official outcomes onto the price block so settlement does not reread a file."""
    from datetime import date as date_cls

    def _parse_day(value: str) -> date_cls | None:
        try:
            return date_cls.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    cal_banks = (calendar or {}).get("banks") if isinstance(calendar, Mapping) else {}
    if not isinstance(cal_banks, Mapping):
        cal_banks = {}

    def _calendar_decisions(code: str) -> list[Mapping[str, Any]]:
        bank_cal = cal_banks.get(code) if isinstance(cal_banks, Mapping) else None
        if not isinstance(bank_cal, Mapping):
            return []
        rows = bank_cal.get("decisions") or []
        return [row for row in rows if isinstance(row, Mapping)]

    def _us_own_decision_key(decision: Mapping[str, Any]) -> bool:
        if decision.get("lower") is not None and decision.get("upper") is not None:
            return True
        return str(decision.get("provenance") or "") == "official_fomc_statement"

    def _map_to_calendar_decision(code: str, series_day: str) -> tuple[str, str] | None:
        series = _parse_day(series_day)
        if series is None:
            return None
        best: tuple[str, str, date_cls] | None = None
        for row in _calendar_decisions(code):
            eff_text = str(row.get("effective_date") or "")
            eff = _parse_day(eff_text)
            dec = str(row.get("decision_date") or "")
            if eff is None or not dec:
                continue
            if eff <= series and (best is None or eff > best[2]):
                best = (dec, eff_text, eff)
        if best is None:
            return None
        return best[0], best[1]

    countries = (policy_state or {}).get("countries") if isinstance(policy_state, Mapping) else {}
    outcomes: dict[str, dict[str, Any]] = {}
    if isinstance(countries, Mapping):
        for code, country in countries.items():
            if not isinstance(country, Mapping):
                continue
            bucket: dict[str, Any] = {}
            for decision in country.get("decisions") or []:
                if not isinstance(decision, dict):
                    continue
                rate = _official_rate(decision)
                decided = str(decision.get("decision_date") or "")
                if rate is None or not decided:
                    continue
                if str(code) == "US" and _us_own_decision_key(decision):
                    outcome_key = decided
                    effective = str(decision.get("effective_date") or decided)
                else:
                    mapped = _map_to_calendar_decision(str(code), decided)
                    if mapped is None:
                        continue
                    outcome_key, effective = mapped
                bucket[outcome_key] = {
                    "rate": round(rate, 4),
                    "effective_date": effective,
                }
            if bucket:
                outcomes[str(code)] = bucket
    block["outcomes"] = outcomes
    block.setdefault("as_of", as_of.isoformat())
    return block


def _row(block: Mapping[str, Any], decision_date: str) -> dict[str, Any] | None:
    for row in block.get("meetings") or []:
        if isinstance(row, Mapping) and str(row.get("decision_date")) == decision_date:
            return dict(row)
    return None


def _settled_row(prices: Mapping[str, Any], bank: str, decision_date: str, row: dict[str, Any] | None) -> dict[str, Any] | None:
    outcomes = (prices.get("outcomes") or {}).get(bank) or {}
    outcome = outcomes.get(decision_date) if isinstance(outcomes, Mapping) else None
    if not isinstance(outcome, Mapping):
        return row
    as_of_text = str(prices.get("as_of") or "")
    effective = str(outcome.get("effective_date") or decision_date)
    if as_of_text and effective > as_of_text:
        return row
    settled = dict(row or {})
    settled["decision_date"] = decision_date
    settled["effective_date"] = effective
    settled["post_rate"] = outcome["rate"]
    settled["method"] = "official"
    settled["instrument_id"] = settled.get("instrument_id") or f"PM:{bank}:{decision_date}"
    anchor = None
    banks = prices.get("banks") if isinstance(prices.get("banks"), dict) else {}
    bank_block = banks.get(bank) if isinstance(banks, Mapping) else None
    if isinstance(bank_block, Mapping):
        anchor = bank_block.get("anchor")
    if anchor is not None and settled.get("cumulative_bp") is None:
        settled["cumulative_bp"] = round((float(outcome["rate"]) - float(anchor)) * 100.0, 2)
    return settled


def resolve_policy_meeting_mark(
    market_state: Mapping[str, Any],
    expression: Mapping[str, Any],
    *,
    stored_bases: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if expression.get("type") != "policy_meeting":
        raise SchemaError("expression type must be policy_meeting")
    if expression.get("construction_version") not in (None, CONSTRUCTION_VERSION):
        raise SchemaError("policy meeting construction_version is not policy_meeting_v1")
    prices = _prices(market_state)
    kind = str(expression.get("kind") or "")
    dates = [str(item) for item in (expression.get("decision_dates") or [])]
    if kind == "cross_country":
        banks = [str(item) for item in (expression.get("banks") or [])]
        if len(banks) != 2 or len(dates) != 2:
            raise SchemaError("cross_country needs two banks and two decision dates")
        first = _bank_block(prices, banks[0])
        second = _bank_block(prices, banks[1])
        row_a = _settled_row(prices, banks[0], dates[0], _row(first, dates[0]))
        row_b = _settled_row(prices, banks[1], dates[1], _row(second, dates[1]))
        if row_a is None or row_b is None:
            raise PolicyMeetingHeld(f"calendar no longer has {banks}:{dates}")
        peer = dict(second)
        peer["meetings"] = [row_b]
        block = dict(first)
        block["meetings"] = [row_a]
        bases = dict(stored_bases or expression.get("bases") or {})
        stored = {"peer_block": peer, "bases": bases}
    else:
        bank = str(expression.get("bank") or "")
        block = dict(_bank_block(prices, bank))
        rows = []
        for decision_date in dates:
            found = _settled_row(prices, bank, decision_date, _row(block, decision_date))
            if found is None:
                raise PolicyMeetingHeld(f"calendar no longer has {bank} {decision_date}")
            rows.append(found)
        block["meetings"] = rows
        stored = {"base_rate": (stored_bases or {}).get("base_rate", expression.get("base_rate"))}
    try:
        quoted = quote_for_expression(block, dict(expression), stored)
    except ValueError as exc:
        raise SchemaError(str(exc)) from exc
    return {
        "value": quoted["value"],
        "quote_unit": quoted["quote_unit"],
        "source": f"policy_meeting_prices.{quoted.get('source')}",
        "as_of": prices.get("as_of"),
        "kind": "derived" if quoted.get("method") == "equal_step" else "direct",
        "method": quoted.get("method"),
        "expression": dict(expression),
    }


def assess_policy_meeting(
    expression: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
) -> dict[str, Any]:
    from scripts.rates.executable_catalog import _verdict

    if not isinstance(expression, Mapping) or expression.get("type") != "policy_meeting":
        return _verdict(
            status="unsupported",
            reason="policy_meeting expression required",
            family="policy_meeting",
            expression_type="policy_meeting",
        )
    if expression.get("construction_version") != CONSTRUCTION_VERSION:
        return _verdict(
            status="unsupported",
            reason="construction_version must be policy_meeting_v1",
            family="policy_meeting",
            expression_type="policy_meeting",
        )
    try:
        prices = _prices(market_state)
        kind = str(expression.get("kind") or "")
        dates = [str(item) for item in (expression.get("decision_dates") or [])]
        if kind == "cross_country":
            banks = [str(item) for item in (expression.get("banks") or [])]
            checked = list(zip(banks, dates))
        else:
            checked = [(str(expression.get("bank") or ""), item) for item in dates]
        if not checked:
            raise SchemaError("policy meeting expression has no dates")
        for bank, decision_date in checked:
            if bank not in _ANCHOR:
                raise SchemaError(f"{bank} policy meetings are not bookable")
            block = _bank_block(prices, bank)
            row = _row(block, decision_date)
            if row is None or row.get("method") not in BOOKABLE_METHODS or row.get("post_rate") is None:
                raise SchemaError(f"{bank} {decision_date} is not a priced meeting")
        anchor_bank = checked[0][0]
        if notional_usd is not None:
            fx = _fx_usd(_ANCHOR[anchor_bank]["currency"], market_state)
            if lots_for(float(notional_usd), anchor_bank, fx) < 1:
                raise SchemaError("notional is below one anchor futures lot")
    except (SchemaError, PolicyMeetingHeld, KeyError, TypeError, ValueError) as exc:
        return _verdict(
            status="unavailable",
            reason=str(exc),
            family="policy_meeting",
            expression_type="policy_meeting",
            mark_status="unavailable",
        )
    return _verdict(
        status="executable",
        reason="priced policy meeting",
        family="policy_meeting",
        expression_type="policy_meeting",
        mark_status="ok",
        mark_source="policy_meeting_prices",
    )


def install_policy_meeting(position: dict[str, Any], market_state: Mapping[str, Any] | None) -> None:
    expression = position.get("paper_expression")
    if not isinstance(expression, dict):
        raise SchemaError("policy_meeting OPEN requires paper_expression")
    verdict_reason = assess_policy_meeting(expression, market_state, float(position.get("notional_usd") or 0.0))
    if not verdict_reason.get("bookable"):
        raise SchemaError(str(verdict_reason.get("reason") or "policy meeting is not bookable"))
    kind = str(expression.get("kind") or "")
    if kind == "cross_country":
        bank = str(expression["banks"][0])
    else:
        bank = str(expression["bank"])
    spec = _ANCHOR[bank]
    fx = _fx_usd(spec["currency"], market_state)
    lots = lots_for(float(position.get("notional_usd") or 0.0), bank, fx)
    if lots < 1:
        raise SchemaError("notional is below one anchor futures lot")
    prices = _prices(market_state)
    block = _bank_block(prices, bank)
    expression = dict(expression)
    expression["construction_version"] = CONSTRUCTION_VERSION
    if kind == "cross_country":
        bases = {}
        for code in expression["banks"]:
            bases[str(code)] = _bank_block(prices, str(code)).get("anchor")
        expression["bases"] = bases
    elif kind in {"cumulative", "meeting", "calendar_spread"}:
        expression["base_rate"] = block.get("anchor")
    quoted = resolve_policy_meeting_mark(market_state, expression)
    if position.get("entry_price") in (None, ""):
        position["entry_price"] = quoted["value"]
    position["mark_price"] = quoted["value"]
    position["paper_expression"] = expression
    position["valuation_method"] = VALUATION_METHOD
    position["quote_unit"] = quoted["quote_unit"]
    position["contracts"] = lots
    position["local_dv01"] = spec["dv01"]
    position["currency"] = spec["currency"]
    position["face_notional"] = spec["face"]
    position["anchor_product"] = spec["product"]
    position["entry_fx_usd_per_unit"] = fx
    position["mark_fx_usd_per_unit"] = fx
    position["mark_fx_status"] = "ok"
    position["dv01_usd"] = round(lots * spec["dv01"] * fx, 2)
    position["underlying"] = []
    dates = expression.get("decision_dates") or []
    banks = expression.get("banks") or [bank]
    price_banks = prices.get("banks") or {}
    for code, decision_date in zip(banks if kind == "cross_country" else [bank] * len(dates), dates):
        row = _row(price_banks.get(code) or {}, str(decision_date)) or {}
        position["underlying"].extend(list(row.get("contracts") or []))
    position["construction_version"] = CONSTRUCTION_VERSION
    position["mark_status"] = "ok"
    position["isolated"] = False


def meeting_pnl(
    position: Mapping[str, Any],
    *,
    exit_price: float | None = None,
    closed_notional: float | None = None,
) -> dict[str, Any]:
    entry = position.get("entry_price")
    mark = exit_price if exit_price is not None else position.get("mark_price")
    if entry in (None, "") or mark in (None, ""):
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "policy meeting mark or entry missing",
            "valuation_method": VALUATION_METHOD,
            "isolated": True,
        }
    if position.get("mark_status") == "unavailable" and exit_price is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "policy meeting mark unavailable",
            "valuation_method": VALUATION_METHOD,
            "isolated": True,
        }
    expression = position.get("paper_expression") if isinstance(position.get("paper_expression"), Mapping) else {}
    kind = str(expression.get("kind") or "meeting")
    bank = str(expression.get("banks", [expression.get("bank")])[0] if kind == "cross_country" else expression.get("bank") or "")
    if bank not in _ANCHOR:
        bank = str(position.get("anchor_product") or "")
        bank = next((code for code, spec in _ANCHOR.items() if spec["product"] == bank), bank)
    spec = _ANCHOR.get(bank)
    if spec is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "policy meeting anchor missing",
            "valuation_method": VALUATION_METHOD,
            "isolated": True,
        }
    fx = position.get("entry_fx_usd_per_unit")
    if fx in (None, ""):
        fx = position.get("mark_fx_usd_per_unit")
    if fx in (None, ""):
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "policy meeting FX missing",
            "valuation_method": VALUATION_METHOD,
            "isolated": True,
        }
    notional = closed_notional if closed_notional is not None else position.get("notional_usd")
    lots = lots_for(float(notional or 0.0), bank, float(fx))
    local = float(position.get("local_dv01") or spec["dv01"])
    delta = (float(mark) - float(entry)) * (100.0 if kind == "meeting" or position.get("quote_unit") == "percent" else 1.0)
    side = position.get("side")
    sign = 1 if side == "long" else -1 if side == "short" else None
    if sign is None:
        raise SchemaError(f"side must be long or short, got {side}")
    pnl = -sign * delta * lots * local * float(fx)
    return {
        "unrealized_pnl_usd": round(pnl, 2),
        "pnl_unavailable": False,
        "pnl_note": None,
        "valuation_method": VALUATION_METHOD,
        "isolated": False,
        "currency": spec["currency"],
        "price_unit": position.get("quote_unit") or "percent",
    }


def meeting_shock_usd(position: Mapping[str, Any]) -> float | None:
    expression = position.get("paper_expression") if isinstance(position.get("paper_expression"), Mapping) else {}
    kind = str(expression.get("kind") or "meeting")
    bank = str(expression["banks"][0]) if kind == "cross_country" else str(expression.get("bank") or "")
    if bank not in _ANCHOR:
        return None
    fx = position.get("mark_fx_usd_per_unit") or position.get("entry_fx_usd_per_unit")
    if fx in (None, ""):
        return None
    lots = lots_for(float(position.get("notional_usd") or 0.0), bank, float(fx))
    local = float(position.get("local_dv01") or _ANCHOR[bank]["dv01"])
    return round(abs(lots * local * float(fx) * 100.0), 2)
