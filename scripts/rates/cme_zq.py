"""CME 30-day Federal Funds (ZQ) futures settlement acquisition.

Primary source is the CME settlements report for product 305 (Globex ZQ,
clearing 41, dsHeader "30 Day Federal Funds Future"). The price is
100 minus the arithmetic average of the daily effective federal funds rate
over the contract month. SR1 and SR3 rows are never copied in to fill a gap.

A dated eSignal chain (symbol ``ZQ``, not ``ZQ-CME``) is only a delayed
quote. Its retrieval banner is not an official trade date, and a weekend
retrieval does not invent a session.
"""

from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable

from scripts.rates.cme_session import (
    FRESH_MAX_AGE_DAYS,
    stamp_cme_publication_fields,
)

FetchBytes = Callable[..., bytes]

CME_ZQ_PRODUCT_ID = "305"
CME_ZQ_SETTLEMENTS_TEMPLATE = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    f"{CME_ZQ_PRODUCT_ID}/FUT?tradeDate={{trade_date}}&strategy=DEFAULT&pageSize=500"
)
CME_ZQ_PAGE = "https://www.cmegroup.com/markets/interest-rates/stirs/30-day-federal-fund.settlements.html"
CME_ZQ_SPECS_URL = "https://www.cmegroup.com/markets/interest-rates/stirs/30-day-federal-fund.contractSpecs.html"
ESIGNAL_ZQ_CHAIN_URL = "https://quotes.esignal.com/esignalprod/quote.action?symbol=ZQ"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_MONTH_CODES = {
    "JAN": "F",
    "FEB": "G",
    "MAR": "H",
    "APR": "J",
    "MAY": "K",
    "JUN": "M",
    "JUL": "N",
    "AUG": "Q",
    "SEP": "U",
    "OCT": "V",
    "NOV": "X",
    "DEC": "Z",
}
_CODE_TO_MONTH = {letter: abbr for abbr, letter in _MONTH_CODES.items()}
MONTHS = {
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
_UNDERLYING = (
    "arithmetic average of the daily effective federal funds rate (EFFR) "
    "over each calendar day of the contract month"
)


def contract_month_window(named_month: str) -> dict[str, Any]:
    year = int(named_month[:4])
    month = int(named_month[5:7])
    last = monthrange(year, month)[1]
    return {
        "named_month": named_month,
        "reference_start": date(year, month, 1).isoformat(),
        "reference_end": date(year, month, last).isoformat(),
        "day_count_days": last,
        "underlying": "EFFR",
        "underlying_definition": _UNDERLYING,
        "day_count": "calendar month; contract value ACT/360 on days in the month",
    }


def zq_code(named_month: str) -> str:
    year = int(named_month[:4])
    month = int(named_month[5:7])
    abbr = next(name for name, num in MONTHS.items() if num == month)
    return f"ZQ{_MONTH_CODES[abbr]}{year % 100:02d}"


def _num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "—", "UNCH", "N/A", "NA"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _optional_count(value: object) -> int | None:
    parsed = _num(value)
    if parsed is None:
        return None
    return int(parsed)


def _iso_calendar_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d %b %Y",
        "%b %d %Y",
        "%B %d %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _parse_cme_update_time(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%A, %d %b %Y %I:%M %p", "%A, %d %b %Y %I:%M:%S %p"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _parse_month_label(label: str) -> str | None:
    raw = _clean(label).upper()
    if not raw or raw.startswith("TOTAL"):
        return None
    match = re.fullmatch(r"([A-Z]{3,9})\s+(\d{2}|\d{4})", raw)
    if not match:
        compact = re.sub(r"\s+", "", raw)
        match = re.fullmatch(r"([A-Z]{3,9})(\d{2}|\d{4})", compact)
    if not match:
        return None
    month_token = match.group(1)[:3]
    if month_token not in MONTHS:
        return None
    year_token = match.group(2)
    year = int(year_token) if len(year_token) == 4 else 2000 + int(year_token)
    return f"{year:04d}-{MONTHS[month_token]:02d}"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.text: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(_clean(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        cleaned = _clean(data)
        if not cleaned:
            return
        self.text.append(cleaned)
        if self._cell is not None:
            self._cell.append(cleaned)


def _row_from_price(
    *,
    named_month: str,
    price: float,
    volume: int | None,
    open_interest: int | None,
    observation_date: str | None,
    source: str,
    mark_kind: str,
    trade_date_verified: bool,
    source_url: str | None,
) -> dict[str, Any]:
    window = contract_month_window(named_month)
    implied = 100.0 - price
    row = {
        "product": "ZQ",
        "code": zq_code(named_month),
        "expiry": named_month,
        "price": round(price, 6),
        "implied_rate": round(implied, 6),
        "volume": volume,
        "open_interest": open_interest,
        "observation_date": observation_date,
        "as_of": observation_date,
        "source": source,
        "mark_kind": mark_kind,
        "trade_date_verified": trade_date_verified,
        "source_url": source_url,
        "quote_convention": "100 minus monthly average EFFR",
        **window,
    }
    oi = open_interest or 0
    vol = volume or 0
    if oi > 0:
        row["liquidity"] = "open_interest"
    elif vol > 0:
        row["liquidity"] = "volume_only"
    else:
        row["liquidity"] = "no_open_interest"
    return row


def _verify_settlements_payload(payload: object, *, session_date: date) -> dict[str, Any]:
    if isinstance(payload, list):
        raise ValueError("bare list CME ZQ settlements payload is undated")
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected CME ZQ settlements payload type: {type(payload)!r}")
    report_type = payload.get("reportType")
    if report_type is None or str(report_type).strip().lower() != "final":
        raise ValueError(f"non-final CME ZQ settlement reportType={report_type!r}")
    header = str(payload.get("dsHeader") or "")
    upper = header.upper()
    if "FEDERAL FUNDS" not in upper or "FUTURE" not in upper:
        raise ValueError(f"wrong CME ZQ product dsHeader={header!r}")
    if "OPTION" in upper:
        raise ValueError(f"CME ZQ payload is options, not futures: {header!r}")
    settlements = payload.get("settlements")
    if not isinstance(settlements, list) or not settlements:
        raise ValueError("empty or missing CME ZQ settlements list")
    observation_date = _iso_calendar_date(payload.get("tradeDate"))
    if not observation_date:
        raise ValueError("CME ZQ settlements payload missing verified tradeDate")
    if observation_date != session_date.isoformat():
        raise ValueError(
            f"CME ZQ tradeDate {observation_date!r} does not match "
            f"requested session {session_date.isoformat()!r}"
        )
    update_time = payload.get("updateTime")
    if update_time is not None and str(update_time).strip():
        updated = _parse_cme_update_time(update_time)
        if updated and updated != observation_date:
            raise ValueError(
                f"CME ZQ updateTime date {updated!r} contradicts tradeDate {observation_date!r}"
            )
    return payload


def _select_strip(
    candidates: list[dict[str, Any]],
    *,
    observation_date: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the full unexpired month strip. Duplicates are rejected, not averaged."""
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    obs = date.fromisoformat(observation_date) if observation_date else None
    for row in candidates:
        expiry = str(row.get("expiry") or "")
        end = row.get("reference_end")
        if obs is not None and end and date.fromisoformat(str(end)) < obs:
            rejected.append({**row, "rejection": "contract month ended before the observation"})
            continue
        if expiry in seen:
            rejected.append({**row, "rejection": f"duplicate contract month {expiry}"})
            continue
        seen[expiry] = row
        eligible.append(row)
    eligible.sort(key=lambda item: item["expiry"])
    return eligible, rejected


def parse_cme_zq_settlements_json(
    text: str,
    *,
    session_date: date,
    source_url: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (eligible strip, rejected raw records) for one final ZQ report."""
    payload = json.loads(text)
    verified = _verify_settlements_payload(payload, session_date=session_date)
    observation_date = _iso_calendar_date(verified.get("tradeDate"))
    assert observation_date is not None
    report_type = str(verified.get("reportType") or "").strip()
    raw_records: list[dict[str, Any]] = []
    built: list[dict[str, Any]] = []
    for item in verified.get("settlements") or []:
        if not isinstance(item, dict):
            continue
        raw_records.append(dict(item))
        named_month = _parse_month_label(str(item.get("month") or ""))
        price = None
        for key in ("settle", "settlement", "settlementPrice"):
            price = _num(item.get(key))
            if price is not None:
                break
        if named_month is None or price is None or not (70.0 < price < 100.25):
            continue
        row = _row_from_price(
            named_month=named_month,
            price=price,
            volume=_optional_count(item.get("volume")),
            open_interest=_optional_count(item.get("openInterest")),
            observation_date=observation_date,
            source="CME_ZQ_SETTLEMENT",
            mark_kind="official_settlement",
            trade_date_verified=True,
            source_url=source_url,
        )
        row["report_type"] = report_type
        row["raw_month"] = item.get("month")
        built.append(row)
    eligible, rejected = _select_strip(built, observation_date=observation_date)
    if not eligible:
        raise ValueError("CME ZQ settlement response contained no usable contracts")
    return eligible, rejected


def _extract_esignal_retrieval_date(text: str) -> str | None:
    match = re.search(
        r"Delayed data retrieved on\s+([A-Za-z]+\s+\d{1,2}\s+\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    return _iso_calendar_date(match.group(1))


def parse_esignal_zq_html(text: str) -> list[dict[str, Any]]:
    """Parse a delayed ZQ chain. Never labels the print as an official settlement."""
    retrieved_on = _extract_esignal_retrieval_date(text)
    if not retrieved_on:
        raise ValueError("eSignal ZQ page missing delayed data retrieval banner")
    retrieval = date.fromisoformat(retrieved_on)
    observation_date = retrieved_on if retrieval.weekday() < 5 else None
    parser = _TableParser()
    parser.feed(text)
    built: list[dict[str, Any]] = []
    pattern = re.compile(r"ZQ\s*([FGHJKMNQUVXZ])(\d{2})\b", re.I)

    def consume(blob: str, cells: list[str]) -> None:
        match = pattern.search(blob)
        if not match:
            return
        letter = match.group(1).upper()
        year = 2000 + int(match.group(2))
        named_month = f"{year:04d}-{MONTHS[_CODE_TO_MONTH[letter]]:02d}"
        price = None
        for cell in cells:
            parsed = _num(cell)
            if parsed is not None and 70.0 < parsed < 100.25:
                price = parsed
                break
        if price is None:
            found = re.search(r"(9\d(?:\.\d+)?)", blob)
            if found:
                candidate = float(found.group(1))
                if 70.0 < candidate < 100.25:
                    price = candidate
        if price is None:
            return
        row = _row_from_price(
            named_month=named_month,
            price=price,
            volume=None,
            open_interest=None,
            observation_date=observation_date,
            source="ESIGNAL_CME_ZQ_DELAYED",
            mark_kind="delayed_quote",
            trade_date_verified=False,
            source_url=ESIGNAL_ZQ_CHAIN_URL,
        )
        row["retrieval_date"] = retrieved_on
        row["session_verified"] = False
        built.append(row)

    for table in parser.tables:
        for cells in table:
            consume(" ".join(cells), cells)
    if not built:
        consume(" ".join(parser.text), parser.text)
    eligible, _rejected = _select_strip(built, observation_date=observation_date or retrieved_on)
    if not eligible:
        raise ValueError("eSignal delayed ZQ quote board contained no usable contracts")
    return eligible


def _is_production_fetch_bytes(fetch_bytes: FetchBytes) -> bool:
    return (
        getattr(fetch_bytes, "__module__", None) == "scripts.market_state"
        and getattr(fetch_bytes, "__name__", None) == "fetch_bytes"
    )


def _curl_cffi_get(url: str, *, referer: str | None = None) -> tuple[bytes | None, str | None]:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None, "curl_cffi_unavailable"
    headers = {"Accept": "*/*", "Accept-Language": "en-US,en;q=0.8"}
    if referer:
        headers["Referer"] = referer
    last = "curl_cffi_failed"
    for impersonate in ("chrome", "safari18_0"):
        try:
            response = cffi_requests.get(url, impersonate=impersonate, timeout=30, headers=headers)
        except Exception as exc:
            last = str(exc)
            continue
        if getattr(response, "status_code", 0) == 200 and response.content:
            return bytes(response.content), f"curl_cffi/{impersonate}"
        last = f"http_{getattr(response, 'status_code', '?')}"
    return None, last


def _invoke_fetch_bytes(fetch_bytes: FetchBytes, url: str, **kwargs: Any) -> bytes:
    try:
        return fetch_bytes(url, retries=1, user_agent=UA, **kwargs)
    except TypeError:
        return fetch_bytes(url, **kwargs)


def _fetch_bytes(
    fetch_bytes: FetchBytes,
    url: str,
    *,
    referer: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    attempt: dict[str, Any] = {"url": url, "http_status": None, "error": None, "via": None}
    kwargs: dict[str, Any] = {}
    if referer:
        kwargs["referer"] = referer
    try:
        data = _invoke_fetch_bytes(fetch_bytes, url, **kwargs)
        attempt["http_status"] = 200
        attempt["via"] = "fetch_bytes"
        return data, attempt
    except Exception as primary_exc:
        attempt["error"] = str(primary_exc)
        if not _is_production_fetch_bytes(fetch_bytes):
            raise
        data, via = _curl_cffi_get(url, referer=referer)
        if data:
            attempt["http_status"] = 200
            attempt["via"] = via
            attempt["error"] = None
            return data, attempt
        raise primary_exc


def _stamp_freshness(
    rows: list[dict[str, Any]],
    today: date,
    mark_kind: str,
    *,
    now: datetime | None = None,
) -> str:
    verified = bool(rows[0].get("trade_date_verified"))
    freshness, _pub = stamp_cme_publication_fields(
        curve_key="ZQ",
        rows=rows,
        today=today,
        mark_kind=mark_kind,
        trade_date_verified=verified,
        now=now,
    )
    return freshness


def acquire_zq_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    benchmark: float | None = None,
    last_official: list | None = None,
    now: datetime | None = None,
) -> tuple[list, str, str, dict]:
    """Acquire the ZQ strip. ``benchmark`` and ``last_official`` are ignored.

    They exist so the short-rate acquire signature can pass them without
    letting an SR1/SR3 print fill a missing ZQ strip.
    """
    del benchmark, last_official
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for offset in range(0, 8):
        session = today - timedelta(days=offset)
        trade_date = session.strftime("%m/%d/%Y")
        url = CME_ZQ_SETTLEMENTS_TEMPLATE.format(trade_date=trade_date)
        attempt: dict[str, Any] = {"url": url, "http_status": None, "error": None, "via": None}
        try:
            raw, attempt = _fetch_bytes(fetch_bytes, url, referer=CME_ZQ_PAGE)
            body = raw.decode("utf-8", errors="replace")
            rows, rejected = parse_cme_zq_settlements_json(body, session_date=session, source_url=url)
            freshness = _stamp_freshness(rows, today, "official_settlement", now=now)
            provenance = {
                "attempts": attempts + [attempt],
                "mark_kind": "official_settlement",
                "report_type": rows[0].get("report_type"),
                "trade_date": rows[0].get("observation_date"),
                "via": attempt.get("via"),
                "freshness_hint": freshness,
                "session_expected": rows[0].get("session_expected"),
                "rejected_count": len(rejected),
                "product_id": CME_ZQ_PRODUCT_ID,
                "globex": "ZQ",
                "filled_from_sr1_sr3": False,
            }
            return rows, url, "CME ZQ settlements API", provenance
        except Exception as exc:
            last_error = exc
            attempt["error"] = str(exc)
            attempts.append(attempt)

    try:
        raw, attempt = _fetch_bytes(fetch_bytes, ESIGNAL_ZQ_CHAIN_URL, referer=ESIGNAL_ZQ_CHAIN_URL)
        attempts.append(attempt)
        delayed = parse_esignal_zq_html(raw.decode("utf-8", errors="replace"))
        freshness = _stamp_freshness(delayed, today, "delayed_quote")
        provenance = {
            "attempts": attempts,
            "mark_kind": "delayed_quote",
            "report_type": None,
            "trade_date": delayed[0].get("observation_date"),
            "retrieval_date": delayed[0].get("retrieval_date"),
            "via": attempt.get("via"),
            "freshness_hint": freshness,
            "session_expected": delayed[0].get("session_expected"),
            "note": "Delayed eSignal chain is not an official CME settlement.",
            "filled_from_sr1_sr3": False,
        }
        return delayed, ESIGNAL_ZQ_CHAIN_URL, "delayed CME ZQ futures chain via eSignal", provenance
    except Exception as exc:
        last_error = exc
        attempts.append({"url": ESIGNAL_ZQ_CHAIN_URL, "http_status": None, "error": str(exc), "via": None})

    raise ValueError(f"no usable ZQ contract marks in {FRESH_MAX_AGE_DAYS}-day lookback: {last_error}")


def probe_cme_zq(fetch_bytes: FetchBytes, *, session_date: date) -> dict[str, Any]:
    """Single-session CME ZQ settlements probe. Never raises."""
    url = CME_ZQ_SETTLEMENTS_TEMPLATE.format(trade_date=session_date.strftime("%m/%d/%Y"))
    out: dict[str, Any] = {
        "url": url,
        "http_status": None,
        "via": None,
        "ok": False,
        "report_type": None,
        "trade_date": None,
        "ds_header": None,
        "settlement_count": None,
        "error": None,
        "body_excerpt": None,
    }
    try:
        raw, attempt = _fetch_bytes(fetch_bytes, url, referer=CME_ZQ_PAGE)
        out["http_status"] = attempt.get("http_status")
        out["via"] = attempt.get("via")
        body = raw.decode("utf-8", errors="replace")
        out["body_excerpt"] = body[:180]
        payload = json.loads(body)
        if isinstance(payload, dict):
            out["report_type"] = payload.get("reportType")
            out["trade_date"] = payload.get("tradeDate")
            out["ds_header"] = payload.get("dsHeader")
            settlements = payload.get("settlements")
            if isinstance(settlements, list):
                out["settlement_count"] = len(settlements)
            _verify_settlements_payload(payload, session_date=session_date)
            out["ok"] = True
        else:
            out["error"] = f"unexpected payload type {type(payload)!r}"
    except Exception as exc:
        out["error"] = str(exc)
    return out
