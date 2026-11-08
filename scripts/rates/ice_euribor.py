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
) -> dict[str, Any]:
    """Show why an ER3-minus-I price gap is not a basis when LTDs differ."""
    er3_by = {str(row.get("market_strip")): row for row in er3_rows}
    points = []
    for row in euribor_rows:
        symbol = str(row.get("market_strip") or "")
        other = er3_by.get(symbol)
        er3_life = er3_expiries.get(symbol) or {}
        i_ltd = row.get("ltd")
        er3_ltd = er3_life.get("ltd")
        gap = None
        if other and other.get("price") is not None and row.get("price") is not None:
            gap = round(100.0 * (float(other["price"]) - float(row["price"])), 6)
        aligned = bool(i_ltd and er3_ltd and i_ltd == er3_ltd)
        points.append(
            {
                "market_strip": symbol,
                "euribor_code": row.get("code"),
                "er3_code": None if other is None else other.get("code"),
                "i_ltd": i_ltd,
                "er3_ltd": er3_ltd,
                "i_quote_time": row.get("quote_time"),
                "er3_quote_time": None if other is None else other.get("quote_time"),
                "unaligned_price_gap_bp": None if aligned else gap,
                "basis_bp": gap if aligned else None,
                "status": "period_aligned" if aligned else "unavailable",
                "reason": None
                if aligned
                else (
                    f"ICE I {symbol} LTD {i_ltd} and ER3 {symbol} LTD {er3_ltd} "
                    "are not the same contract period. The price gap is not a basis."
                ),
            }
        )
    usable = [row for row in points if row["status"] == "period_aligned" and row.get("basis_bp") is not None]
    return {
        "curve_id": "EA_ICE_ER3_MINUS_I",
        "status": "ok" if usable else "unavailable",
        "formula": "100 * (ER3 last - I last) = 100 * ((100 - I) - (100 - ER3))",
        "exact_fra_ois": False,
        "execution_eligible": False,
        "points": points,
        "reason": None
        if usable
        else "Same ICE month labels do not share a last trading day, so ER3 minus I is not a basis.",
    }


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
) -> tuple[list, str, str, dict]:
    del today
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
        cross = same_label_cross_check(parsed["rows"], er3_parsed["rows"], er3_exp)
    except Exception as exc:
        cross = {"status": "unavailable", "points": [], "reason": f"ER3 cross-check unavailable: {exc}"}
    provenance = {
        "mark_kind": "delayed_last",
        "trade_date": parsed["rows"][0]["observation_date"],
        "quote_time": parsed["rows"][0]["quote_time"],
        "retrieved_at": retrieved,
        "freshness_hint": "stale",
        "execution_eligible": False,
        "official_settlement": False,
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
