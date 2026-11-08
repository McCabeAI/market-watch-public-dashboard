"""CME EUS basis-spread futures, product 10248.

The settlement is the quoted basis, not a 100-minus-rate index and not an
EURIBOR outright. A final report stamps tradeDate in the body. Contract
tick value and notional were not present in a machine-readable spec body
from this runner, so PnL stays unavailable.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from scripts.rates.cme_session import classify_mark_freshness, latest_expected_cme_session
from scripts.rates.cme_zq import CME_ZQ_PAGE, _fetch_bytes

FetchBytes = Callable[..., bytes]

CME_EUS_PRODUCT_ID = "10248"
CME_EUS_SETTLEMENTS_TEMPLATE = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    f"{CME_EUS_PRODUCT_ID}/FUT?tradeDate={{trade_date}}&strategy=DEFAULT&pageSize=500"
)
CME_EUS_SPECS_URL = (
    "https://www.cmegroup.com/markets/interest-rates/stirs/"
    "euro-short-term-rate-spread.contractSpecs.html"
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


def _num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _month(label: str) -> tuple[str, int, int] | None:
    raw = re.sub(r"\s+", " ", str(label or "").strip().upper())
    if not raw or raw.startswith("TOTAL"):
        return None
    match = re.fullmatch(r"([A-Z]{3})\s+(\d{2}|\d{4})", raw)
    if not match or match.group(1) not in _MONTHS:
        return None
    year = int(match.group(2)) if len(match.group(2)) == 4 else 2000 + int(match.group(2))
    month = _MONTHS[match.group(1)]
    return f"{year:04d}-{month:02d}", year, month


def _iso_trade_date(value: object) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_cme_eus_settlements_json(
    text: str,
    *,
    session_date: date,
    source_url: str | None,
) -> list[dict[str, Any]]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("CME EUS payload must be an object")
    if str(payload.get("reportType") or "").strip().lower() != "final":
        raise ValueError(f"non-final CME EUS reportType={payload.get('reportType')!r}")
    header = str(payload.get("dsHeader") or "")
    upper = header.upper()
    if "ESTR" not in upper and "EURO SHORT-TERM" not in upper:
        raise ValueError(f"wrong CME EUS header {header!r}")
    if "SPREAD" not in upper and "BASIS" not in upper:
        raise ValueError(f"CME EUS header is not a basis spread: {header!r}")
    trade_date = _iso_trade_date(payload.get("tradeDate"))
    if trade_date != session_date.isoformat():
        raise ValueError(
            f"CME EUS tradeDate {trade_date} does not match {session_date.isoformat()}"
        )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload.get("settlements") or []:
        if not isinstance(item, dict):
            continue
        parsed = _month(str(item.get("month") or ""))
        settle = _num(item.get("settle"))
        if parsed is None or settle is None:
            continue
        expiry, year, month = parsed
        if expiry in seen:
            continue
        seen.add(expiry)
        rows.append(
            {
                "product": "EUS",
                "exchange": "CME",
                "code": f"EUS{_LETTERS[month]}{year % 100:02d}",
                "expiry": expiry,
                "price": round(settle, 6),
                "settlement": round(settle, 6),
                "basis_bp": round(settle * 100.0, 6),
                "implied_rate": None,
                "quote_convention": "direct basis settlement in index points, not 100 minus a rate",
                "volume": _num(item.get("volume")),
                "open_interest": _num(item.get("openInterest")),
                "observation_date": trade_date,
                "as_of": trade_date,
                "source": "CME_EUS_SETTLEMENT",
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
                "source_url": source_url,
                "spec_url": CME_EUS_SPECS_URL,
                "report_type": payload.get("reportType"),
                "ds_header": header,
                "economics": "unverified_tick",
                "execution_eligible": False,
                "period_note": (
                    "CME names the contract month. The settlement file does not stamp "
                    "the EURIBOR fixing day or the €STR compound window, so this quote "
                    "is not mapped onto an ICE I or ESR period."
                ),
            }
        )
    if not rows:
        raise ValueError("CME EUS settlement file contained no basis quotes")
    rows.sort(key=lambda row: row["expiry"])
    return rows


def acquire_eus_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
) -> tuple[list, str, str, dict]:
    last_error: Exception | None = None
    for offset in range(0, 8):
        session = today - timedelta(days=offset)
        url = CME_EUS_SETTLEMENTS_TEMPLATE.format(trade_date=session.strftime("%m/%d/%Y"))
        try:
            raw, attempt = _fetch_bytes(fetch_bytes, url, referer=CME_ZQ_PAGE)
            rows = parse_cme_eus_settlements_json(
                raw.decode("utf-8", errors="replace"),
                session_date=session,
                source_url=url,
            )
            obs = date.fromisoformat(rows[0]["observation_date"])
            freshness = classify_mark_freshness(
                curve_key="EUS",
                observation=obs,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            )
            session_expected = latest_expected_cme_session(today).isoformat()
            for row in rows:
                row["freshness"] = freshness
                row["session_expected"] = session_expected
            provenance = {
                "mark_kind": "official_settlement",
                "trade_date": rows[0]["observation_date"],
                "freshness_hint": freshness,
                "ds_header": rows[0]["ds_header"],
                "via": attempt.get("via"),
                "execution_eligible": False,
                "economics": "unverified_tick",
                "not_an_euribor_outright": True,
            }
            return rows, url, "CME EUS basis settlements", provenance
        except Exception as exc:
            last_error = exc
    raise ValueError(f"no usable CME EUS settlements: {last_error}")
