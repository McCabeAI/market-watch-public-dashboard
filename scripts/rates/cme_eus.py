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

from scripts.rates.cme_session import stamp_cme_publication_fields
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
CME_EUS_SER_URL = "https://www.cmegroup.com/content/dam/cmegroup/notices/ser/2022/09/SER-9059.pdf"
# SER-9059, Rulebook Chapter 481: each basis point of the spread is €25.
# Minimum increment for every EUS month is 0.0025 index points = €6.25.
EUS_BP_EUR = 25.0
EUS_TICK_INDEX = 0.0025
EUS_TICK_EUR = 6.25
EUS_ECONOMICS_SOURCE = (
    "CME SER-9059 Exhibit 1, Rulebook Chapter 481: the quote is the Euribor-minus-€STR "
    "basis in percent per annum, €25 per basis point; minimum price increment 0.0025 "
    "index points equals €6.25. Final settlement assigns the same named-month ESR future "
    "at 100 minus the Euribor fixing plus the EUS final settlement."
)
EUS_PAPER_BLOCKER = (
    "A long EUS final settlement assigns a long ESR future of the same named month. "
    "ESR remains observe_only, so EUS is not opened as a paper position."
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
                "economics": "ser_9059_eur_25_per_bp",
                "bp_value_eur": EUS_BP_EUR,
                "tick_index": EUS_TICK_INDEX,
                "tick_eur": EUS_TICK_EUR,
                "execution_eligible": False,
                "paper_trading": "observe_only",
                "paper_blocker": EUS_PAPER_BLOCKER,
                "economics_source": EUS_ECONOMICS_SOURCE,
                "period_note": (
                    "SER-9059 prices the spread over the same interest period as the "
                    "named-month Euribor and compounded €STR. The settlement file itself "
                    "does not reprint those fixing dates. Final settlement assigns ESR, "
                    "it does not leave an open spread."
                ),
            }
        )
    if not rows:
        raise ValueError("CME EUS settlement file contained no basis quotes")
    rows.sort(key=lambda row: row["expiry"])
    return rows


def eus_pnl_eur(entry_index: float, exit_index: float, lots: int, side: str) -> float | None:
    """EUR variation on the quoted basis. Long gains when the EUS index rises."""
    if lots < 0 or str(side).lower() not in {"long", "short"}:
        return None
    if lots == 0:
        return 0.0
    amount = (float(exit_index) - float(entry_index)) / 0.01 * EUS_BP_EUR * int(lots)
    if str(side).lower() == "short":
        amount = -amount
    return round(amount, 2)


def eus_pnl_usd(entry_index: float, exit_index: float, lots: int, side: str, eurusd: float | None) -> float | None:
    local = eus_pnl_eur(entry_index, exit_index, lots, side)
    if local is None or eurusd is None or eurusd <= 0:
        return None
    return round(local * float(eurusd), 2)


def eus_assignment_esr_price(euribor_percent: float, eus_final_settlement: float) -> float:
    """IMM index of the ESR future assigned to a long EUS at final settlement.

    SER-9059 example: Euribor 0.7600 and spread 0.4500 assign at 99.6900.
    """
    return round(100.0 - float(euribor_percent) + float(eus_final_settlement), 6)


def acquire_eus_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    now: datetime | None = None,
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
            freshness, pub = stamp_cme_publication_fields(
                curve_key="EUS",
                rows=rows,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
                now=now,
            )
            provenance = {
                "mark_kind": "official_settlement",
                "trade_date": rows[0]["observation_date"],
                "freshness_hint": freshness,
                "session_expected": pub["expected_session_if_published"],
                "publishable_session": pub["publishable_session"],
                "publication_status": pub,
                "ds_header": rows[0]["ds_header"],
                "via": attempt.get("via"),
                "execution_eligible": pub["execution_eligible"],
                "economics": "ser_9059_eur_25_per_bp",
                "economics_source": EUS_ECONOMICS_SOURCE,
                "paper_trading": "observe_only",
                "paper_blocker": EUS_PAPER_BLOCKER,
                "not_an_euribor_outright": True,
            }
            return rows, url, "CME EUS basis settlements", provenance
        except Exception as exc:
            last_error = exc
    raise ValueError(f"no usable CME EUS settlements: {last_error}")
