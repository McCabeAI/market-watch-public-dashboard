"""ICE Three-Month EURIBOR futures (product I, spec 38527986).

The public contract-data endpoint returns per-contract last prices with a
timestamp in the body. Those lasts are delayed quotes, not official
settlements. The expiry CSV stamps first and last trading dates. It does
not stamp the three-month deposit window.

ICE ER3 (Three-Month €STR indexed future) uses the same month label with a
different last-trading day. Matching labels are not a basis.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Callable

from scripts.rates.cme_session import stamp_cme_publication_fields

FetchBytes = Callable[..., bytes]

ICE_PRODUCT_CODE = "I"
ICE_SPEC_ID = "38527986"
ICE_PRODUCT_ID = "15275"
ICE_HUB_ID = "17455"
ICE_SPEC_URL = "https://www.ice.com/products/38527986/three-month-euribor-futures"
ICE_DATA_URL = "https://www.ice.com/products/38527986/Three-Month-Euribor-Futures/data"
ICE_CONTRACT_DATA_URL = (
    "https://www.ice.com/marketdata/api/productguide/charting/contract-data"
    f"?productId={ICE_PRODUCT_ID}&hubId={ICE_HUB_ID}"
)
ICE_EXPIRY_CSV_URL = f"https://www.ice.com/api/productguide/spec/{ICE_SPEC_ID}/expiry/csv"
ER3_SPEC_ID = "82908552"
ER3_PRODUCT_ID = "28556"
ER3_HUB_ID = "29404"
ER3_CONTRACT_DATA_URL = (
    "https://www.ice.com/marketdata/api/productguide/charting/contract-data"
    f"?productId={ER3_PRODUCT_ID}&hubId={ER3_HUB_ID}"
)
ER3_EXPIRY_CSV_URL = f"https://www.ice.com/api/productguide/spec/{ER3_SPEC_ID}/expiry/csv"
ICE_SPREAD_SPEC_ID = "83050087"
ICE_SPREAD_PRODUCT_ID = "28596"
ICE_SPREAD_HUB_ID = "29427"
ICE_SPREAD_SPEC_URL = (
    "https://www.ice.com/products/83050087/Three-Month-ESTR-vs-Three-Month-Euribor-Spread"
)
ICE_SPREAD_CONTRACT_DATA_URL = (
    "https://www.ice.com/marketdata/api/productguide/charting/contract-data"
    f"?productId={ICE_SPREAD_PRODUCT_ID}&hubId={ICE_SPREAD_HUB_ID}"
)
# ICE spread page: minimum fluctuation 0.0025 (€6.25); quote is ER3 price minus I price.
ICE_SPREAD_TICK_INDEX = 0.0025
ICE_SPREAD_TICK_EUR = 6.25
ICE_SPREAD_BP_EUR = 25.0
# Sourced from the ICE product page body, not from a generic IMM assumption.
# Unit of trading: €2,500 × Rate Index. Minimum fluctuation 0.005 = €12.50.
ICE_TICK_INDEX = 0.005
ICE_TICK_EUR = 12.50
ICE_BP_EUR = 25.0
ICE_ECONOMICS_SOURCE = (
    "ICE product 38527986 page: unit of trading €2,500 × Rate Index; "
    "minimum price fluctuation 0.005 (€12.50); quotation 100 minus the rate; "
    "EDSP is three-month EURIBOR on the last trading day"
)

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_LETTERS = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}


def _invoke(fetch_bytes: FetchBytes, url: str) -> bytes:
    headers_referer = ICE_DATA_URL
    try:
        return fetch_bytes(url, retries=1, referer=headers_referer)
    except TypeError:
        return fetch_bytes(url)


def parse_strip_label(label: str) -> tuple[str, int, int] | None:
    match = re.fullmatch(r"([A-Za-z]{3})(\d{2})", str(label or "").strip())
    if not match:
        return None
    month = _MONTHS.get(match.group(1).upper())
    if month is None:
        return None
    year = 2000 + int(match.group(2))
    return f"{year:04d}-{month:02d}", year, month


def parse_body_timestamp(value: object) -> dict[str, str | None]:
    """Split a body timestamp. The calendar date is not a retrieval time."""
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return {"quote_time": None, "quote_date": None}
    parsed = None
    for fmt in ("%m/%d/%Y %I:%M %p GMT", "%m/%d/%Y %I:%M:%S %p GMT", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return {"quote_time": text, "quote_date": None}
    return {"quote_time": text, "quote_date": parsed.date().isoformat()}


def _csv_symbol(value: str) -> str:
    text = str(value or "").strip().strip('"')
    if text.startswith("="):
        text = text[1:].strip().strip('"')
    return text


def _csv_date(value: str) -> str | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_ice_expiry_csv(text: str) -> dict[str, dict[str, str | None]]:
    reader = csv.DictReader(io.StringIO(text))
    out: dict[str, dict[str, str | None]] = {}
    for row in reader:
        symbol = _csv_symbol(row.get("CONTRACT SYMBOL") or "")
        if not symbol:
            continue
        out[symbol] = {
            "symbol": symbol,
            "ftd": _csv_date(row.get("FTD") or ""),
            "ltd": _csv_date(row.get("LTD") or ""),
            "fsd": _csv_date(row.get("FSD") or ""),
        }
    if not out:
        raise ValueError("ICE expiry CSV contained no contracts")
    return out


def parse_ice_contract_data(
    payload: object,
    *,
    expiries: dict[str, dict[str, str | None]] | None,
    source_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("ICE contract-data payload is empty")
    raw_contracts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_contracts.append(dict(item))
        parsed = parse_strip_label(str(item.get("marketStrip") or ""))
        stamp = parse_body_timestamp(item.get("lastTime"))
        price = item.get("lastPrice")
        if parsed is None or price is None or stamp["quote_date"] is None:
            continue
        expiry, year, month = parsed
        if expiry in seen:
            continue
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        if not (70.0 < price_f < 100.25):
            continue
        seen.add(expiry)
        life = (expiries or {}).get(str(item.get("marketStrip"))) or {}
        letter = _LETTERS[month]
        rows.append(
            {
                "product": ICE_PRODUCT_CODE,
                "exchange": "ICE",
                "code": f"I{letter}{year % 100:02d}",
                "expiry": expiry,
                "named_month": expiry,
                "market_strip": item.get("marketStrip"),
                "market_id": item.get("marketId"),
                "price": round(price_f, 6),
                "implied_rate": round(100.0 - price_f, 6),
                "volume": item.get("volume"),
                "open_interest": None,
                "observation_date": stamp["quote_date"],
                "as_of": stamp["quote_date"],
                "quote_time": stamp["quote_time"],
                "retrieved_at": retrieved_at,
                "date_role": "body_last_time_not_official_settlement",
                "source": "ICE_EURIBOR_CONTRACT_DATA",
                "mark_kind": "delayed_last",
                "trade_date_verified": False,
                "quote_timestamp_in_body": True,
                "source_url": source_url,
                "spec_url": ICE_SPEC_URL,
                "underlying": "EURIBOR_3M",
                "ltd": life.get("ltd"),
                "fsd": life.get("fsd"),
                "fixing_date": life.get("fsd") or life.get("ltd"),
                "feed_end_date": _epoch_date(item.get("endDate")),
                "reference_start": None,
                "reference_end": None,
                "eligible_for_basis": False,
                "listing": "quarterly" if month in {3, 6, 9, 12} else "serial",
                "period_note": (
                    "ICE expiry CSV stamps LTD and FSD for this symbol. "
                    "The quote file's endDate is not the three-month deposit window. "
                    "EDSP is the three-month EURIBOR fixing on the last trading day."
                ),
                "execution_eligible": False,
            }
        )
    rows.sort(key=lambda row: row["expiry"])
    if not rows:
        raise ValueError("ICE contract-data contained no priced, dated contracts")
    return {"rows": rows, "raw_contracts": raw_contracts}


def _epoch_date(value: object) -> str | None:
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).date().isoformat()


def same_label_cross_check(
    euribor_rows: list[dict[str, Any]],
    er3_rows: list[dict[str, Any]],
    er3_expiries: dict[str, dict[str, str | None]],
    direct_spread_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """ICE pairs ER3 and I on the EURIBOR contract month. The legs expire separately.

    A same-label outright gap is an indicative delayed last, not an official
    spread settlement. The direct inter-commodity spread, when present, is the
    exchange quote for that same pairing.
    """
    er3_by = {str(row.get("market_strip")): row for row in er3_rows}
    direct_by = {str(row.get("market_strip")): row for row in direct_spread_rows or []}
    points = []
    for row in euribor_rows:
        symbol = str(row.get("market_strip") or "")
        other = er3_by.get(symbol)
        direct = direct_by.get(symbol)
        er3_life = er3_expiries.get(symbol) or {}
        i_ltd = row.get("ltd")
        er3_ltd = er3_life.get("ltd")
        indicative = None
        if other and other.get("price") is not None and row.get("price") is not None:
            indicative = round(100.0 * (float(other["price"]) - float(row["price"])), 6)
        same_clock = bool(
            other
            and row.get("quote_time")
            and other.get("quote_time")
            and row.get("quote_time") == other.get("quote_time")
        )
        points.append(
            {
                "market_strip": symbol,
                "pairing": "euribor_contract_series",
                "euribor_code": row.get("code"),
                "er3_code": None if other is None else other.get("code"),
                "i_ltd": i_ltd,
                "er3_ltd": er3_ltd,
                "independent_expiries": i_ltd != er3_ltd,
                "i_quote_time": row.get("quote_time"),
                "er3_quote_time": None if other is None else other.get("quote_time"),
                "indicative_basis_bp": indicative,
                "indicative_kind": "derived_delayed_last",
                "direct_spread_price": None if direct is None else direct.get("price"),
                "direct_spread_bp": None if direct is None else direct.get("basis_bp"),
                "direct_quote_time": None if direct is None else direct.get("quote_time"),
                "direct_kind": None if direct is None else direct.get("mark_kind"),
                "basis_bp": None if direct is None else direct.get("basis_bp"),
                "status": "exchange_paired" if other is not None or direct is not None else "unavailable",
                "exact_fra_ois": False,
                "execution_eligible": False,
                "same_quote_time": same_clock,
                "reason": (
                    "ICE lists this month on the EURIBOR series: buying the spread is long one ER3 "
                    f"and short one I. I LTD {i_ltd} and ER3 LTD {er3_ltd} are independent. "
                    "The outright price gap is an indicative delayed last"
                    + ("" if same_clock else " and the leg timestamps differ")
                    + ". It is not an official spread settlement and not an identical FRA/OIS period."
                ),
            }
        )
    paired = [row for row in points if row["status"] == "exchange_paired"]
    return {
        "curve_id": "EA_ICE_ER3_MINUS_I",
        "status": "indicative" if paired else "unavailable",
        "formula": "quote = ER3 futures price - I futures price; bp = 100 * that difference",
        "spread_side": "long ER3 and short I when the spread is bought",
        "exact_fra_ois": False,
        "execution_eligible": False,
        "points": points,
        "reason": None
        if paired
        else "No ER3 or direct ICE spread quote was paired to an EURIBOR month.",
    }


def parse_ice_spread_data(
    payload: object,
    *,
    source_url: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    """Direct inter-commodity spread lasts. Prices are small index differences, not 100-minus-rate."""
    if not isinstance(payload, list):
        raise ValueError("ICE spread contract-data payload must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed = parse_strip_label(str(item.get("marketStrip") or ""))
        stamp = parse_body_timestamp(item.get("lastTime"))
        price = item.get("lastPrice")
        if parsed is None or price is None or stamp["quote_date"] is None:
            continue
        expiry, _year, month = parsed
        if expiry in seen:
            continue
        price_f = float(price)
        seen.add(expiry)
        rows.append(
            {
                "product": "ER3-I",
                "exchange": "ICE",
                "code": f"ER3-I-{item.get('marketStrip')}",
                "expiry": expiry,
                "market_strip": item.get("marketStrip"),
                "price": round(price_f, 6),
                "basis_bp": round(price_f * 100.0, 6),
                "volume": item.get("volume"),
                "observation_date": stamp["quote_date"],
                "quote_time": stamp["quote_time"],
                "retrieved_at": retrieved_at,
                "mark_kind": "delayed_last",
                "trade_date_verified": False,
                "source_url": source_url,
                "spec_url": ICE_SPREAD_SPEC_URL,
                "quote_convention": "ER3 futures price minus I futures price",
                "long_leg": "ER3",
                "short_leg": "I",
                "listing": "quarterly" if month in {3, 6, 9, 12} else "serial",
                "execution_eligible": False,
                "tick_index": ICE_SPREAD_TICK_INDEX,
                "tick_eur": ICE_SPREAD_TICK_EUR,
            }
        )
    rows.sort(key=lambda row: row["expiry"])
    return rows


def ice_spread_pnl_eur(entry_price: float, exit_price: float, lots: int, side: str) -> float | None:
    """EUR PnL of the listed spread. Long is long ER3 and short I, and gains when the quote rises."""
    if lots < 0 or str(side).lower() not in {"long", "short"}:
        return None
    if lots == 0:
        return 0.0
    amount = (float(exit_price) - float(entry_price)) / ICE_SPREAD_TICK_INDEX * ICE_SPREAD_TICK_EUR * int(lots)
    if str(side).lower() == "short":
        amount = -amount
    return round(amount, 2)


def ice_i_pnl_eur(entry_index: float, exit_index: float, lots: int, side: str) -> float | None:
    """EUR PnL from the sourced €12.50 per 0.005 tick. Long gains when the index rises."""
    if lots < 0 or str(side).lower() not in {"long", "short"}:
        return None
    if lots == 0:
        return 0.0
    ticks = (float(exit_index) - float(entry_index)) / ICE_TICK_INDEX
    amount = ticks * ICE_TICK_EUR * int(lots)
    if str(side).lower() == "short":
        amount = -amount
    return round(amount, 2)


def ice_i_pnl_usd(
    entry_index: float,
    exit_index: float,
    lots: int,
    side: str,
    eurusd: float | None,
) -> float | None:
    local = ice_i_pnl_eur(entry_index, exit_index, lots, side)
    if local is None or eurusd is None or eurusd <= 0:
        return None
    return round(local * float(eurusd), 2)


def acquire_ice_euribor_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    retrieved_at: str | None = None,
    now: datetime | None = None,
) -> tuple[list, str, str, dict]:
    retrieved = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    raw = _invoke(fetch_bytes, ICE_CONTRACT_DATA_URL)
    payload = json.loads(raw.decode("utf-8"))
    expiry_text = _invoke(fetch_bytes, ICE_EXPIRY_CSV_URL).decode("utf-8", errors="replace")
    expiries = parse_ice_expiry_csv(expiry_text)
    parsed = parse_ice_contract_data(
        payload,
        expiries=expiries,
        source_url=ICE_CONTRACT_DATA_URL,
        retrieved_at=retrieved,
    )
    cross = {"status": "unavailable", "points": [], "reason": "ER3 comparison was not fetched"}
    try:
        er3_raw = json.loads(_invoke(fetch_bytes, ER3_CONTRACT_DATA_URL).decode("utf-8"))
        er3_exp = parse_ice_expiry_csv(
            _invoke(fetch_bytes, ER3_EXPIRY_CSV_URL).decode("utf-8", errors="replace")
        )
        er3_parsed = parse_ice_contract_data(
            er3_raw,
            expiries=er3_exp,
            source_url=ER3_CONTRACT_DATA_URL,
            retrieved_at=retrieved,
        )
        for row in er3_parsed["rows"]:
            row["product"] = "ER3"
            row["code"] = "ER3" + row["code"][1:]
        direct_rows: list[dict[str, Any]] = []
        try:
            spread_raw = json.loads(_invoke(fetch_bytes, ICE_SPREAD_CONTRACT_DATA_URL).decode("utf-8"))
            direct_rows = parse_ice_spread_data(
                spread_raw,
                source_url=ICE_SPREAD_CONTRACT_DATA_URL,
                retrieved_at=retrieved,
            )
        except Exception as spread_exc:
            direct_rows = []
            spread_error = str(spread_exc)
        else:
            spread_error = None
        cross = same_label_cross_check(
            parsed["rows"],
            er3_parsed["rows"],
            er3_exp,
            direct_spread_rows=direct_rows,
        )
        if spread_error:
            cross["direct_spread_error"] = spread_error
    except Exception as exc:
        cross = {"status": "unavailable", "points": [], "reason": f"ER3 cross-check unavailable: {exc}"}
    freshness_hint, pub = stamp_cme_publication_fields(
        curve_key="EURIBOR",
        rows=parsed["rows"],
        today=today,
        mark_kind="delayed_last",
        trade_date_verified=False,
        now=now,
    )
    for row in parsed["rows"]:
        row["official_settlement"] = False
    provenance = {
        "mark_kind": "delayed_last",
        "trade_date": parsed["rows"][0]["observation_date"],
        "quote_time": parsed["rows"][0]["quote_time"],
        "retrieved_at": retrieved,
        "freshness_hint": freshness_hint,
        "execution_eligible": False,
        "official_settlement": False,
        "publication_status": pub,
        "product_code": ICE_PRODUCT_CODE,
        "exchange": "ICE",
        "filled_from_feU3": False,
        "eus_used": False,
        "economics_source": ICE_ECONOMICS_SOURCE,
        "raw_contract_count": len(parsed["raw_contracts"]),
        "ice_er3_cross_check": cross,
        "qualification": {
            "status": "delayed_only",
            "canonical_exchange": "ICE",
            "canonical_product_code": ICE_PRODUCT_CODE,
            "primary_settlement_source": None,
            "delayed_alternative": {
                "url": ICE_CONTRACT_DATA_URL,
                "mark_kind": "delayed_last",
                "quote_date": parsed["rows"][0]["observation_date"],
                "quote_time": parsed["rows"][0]["quote_time"],
            },
            "execution_eligible": False,
            "blocker": "ICE contract-data lasts are not official settlements.",
            "compared": [
                {
                    "venue": "ICE",
                    "product_code": ICE_PRODUCT_CODE,
                    "url": ICE_CONTRACT_DATA_URL,
                    "usable_strip": True,
                    "official_settlement": False,
                    "trade_date_in_body": True,
                }
            ],
        },
    }
    return parsed["rows"], ICE_CONTRACT_DATA_URL, "ICE EURIBOR delayed last via contract-data", provenance
