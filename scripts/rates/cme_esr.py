"""CME €STR (ESR) futures settlement and delayed-quote acquisition."""

from __future__ import annotations

import json
import re
import statistics
import urllib.error
from calendar import monthrange
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable

from scripts.rates.cme_session import (
    FRESH_MAX_AGE_DAYS,
    classify_mark_freshness,
    latest_expected_cme_session,
)

FetchBytes = Callable[..., bytes]

CME_ESR_PRODUCT_ID = "10247"
CME_ESR_SETTLEMENTS_TEMPLATE = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    f"{CME_ESR_PRODUCT_ID}/FUT?tradeDate={{trade_date}}&strategy=DEFAULT&pageSize=500"
)
CME_ESR_PAGE = "https://www.cmegroup.com/markets/interest-rates/stirs/euro-short-term-rate.html"
ESIGNAL_ESR_CHAIN_URL = "https://quotes.esignal.com/esignalprod/quote.action?symbol=ESR-CME"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_ESR_QUARTERLY = frozenset({"MAR", "JUN", "SEP", "DEC"})
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
_CODE_TO_MONTH = {v: k for k, v in _MONTH_CODES.items()}
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
_COMPOUNDING_FORMULA = (
    "R = [product_i (1 + di/360 * ri/100) - 1] * (360/D) * 100, "
    "di = calendar days to the next TARGET business day"
)
_SPEC_SOURCE = "CME Rulebook Chapter 480; named month starts the reference quarter"
_OUTLIER_BAND_PP = 0.75
_FALLBACK_MAX_INDEX_GAP = 0.02


def third_wednesday(year: int, month: int) -> date:
    """Return the calendar date of the third Wednesday in *month*."""
    count = 0
    for day in range(1, monthrange(year, month)[1] + 1):
        if date(year, month, day).weekday() == 2:
            count += 1
            if count == 3:
                return date(year, month, day)
    raise ValueError(f"no third Wednesday in {year}-{month:02d}")


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, (total % 12) + 1


def reference_quarter(named_month: str) -> dict[str, Any]:
    """€STR reference quarter from the listed contract month (start of quarter)."""
    year = int(named_month[:4])
    month = int(named_month[5:7])
    reference_start = third_wednesday(year, month)
    end_y, end_m = _add_months(year, month, 3)
    reference_end = third_wednesday(end_y, end_m)
    termination = reference_end - timedelta(days=1)
    while termination.weekday() >= 5:
        termination -= timedelta(days=1)
    return {
        "named_month": named_month,
        "reference_start": reference_start.isoformat(),
        "reference_end": reference_end.isoformat(),
        "termination_date": termination.isoformat(),
        "day_count": "ACT/360",
        "accrual_named_for": "start",
    }


def _num(value: object) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in {"-", "—", "UNCH", "N/A", "NA"}:
        return None
    try:
        return float(s)
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
    s = str(value).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%d-%b-%Y",
    ):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    if "T" in s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return None


def _parse_cme_update_time(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%A, %d %b %Y %I:%M %p",
        "%A, %d %b %Y %I:%M:%S %p",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.text: list[str] = []

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
            if any(cell for cell in self._row):
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


def _parse_month_label(label: str) -> tuple[str, str, str] | None:
    raw = _clean(label).upper()
    if not raw or raw == "TOTAL" or raw.startswith("TOTAL"):
        return None
    m = re.fullmatch(r"([A-Z]{3,9})\s+(\d{2}|\d{4})", re.sub(r"\s+", " ", raw))
    if not m:
        compact = re.sub(r"\s+", "", raw)
        m = re.fullmatch(r"([A-Z]{3,9})(\d{2}|\d{4})", compact)
    if not m:
        return None
    month_token = m.group(1)[:3]
    if month_token not in MONTHS:
        return None
    year_token = m.group(2)
    year = int(year_token) if len(year_token) == 4 else 2000 + int(year_token)
    named_month = f"{year:04d}-{MONTHS[month_token]:02d}"
    year_digit = str(year)[-1]
    return named_month, month_token, year_digit


def _settlement_price(item: dict[str, Any]) -> float | None:
    for key in ("settle", "settlement", "settlementPrice"):
        price = _num(item.get(key))
        if price is not None:
            return price
    return None


def _accrual_role(observation_date: str, rq: dict[str, Any]) -> str:
    obs = date.fromisoformat(observation_date)
    start = date.fromisoformat(rq["reference_start"])
    term = date.fromisoformat(rq["termination_date"])
    if obs < start:
        return "forward"
    if start <= obs < term:
        return "in_progress"
    return "expired"


def _base_row(
    *,
    named_month: str,
    code: str,
    price: float,
    benchmark: float | None,
    volume: int | None,
    open_interest: int | None,
) -> dict[str, Any]:
    implied = 100.0 - price
    month_num = int(named_month[5:7])
    month_abbr = next(abbr for abbr, num in MONTHS.items() if num == month_num)
    listing = "quarterly" if month_abbr in _ESR_QUARTERLY else "serial"
    rq = reference_quarter(named_month)
    row: dict[str, Any] = {
        "code": code,
        "expiry": named_month,
        "named_month": named_month,
        "listing": listing,
        "price": round(price, 6),
        "implied_rate": round(implied, 6),
        "volume": volume,
        "open_interest": open_interest,
        "change_from_overnight_bps": (
            round((implied - benchmark) * 100.0, 2) if benchmark is not None else None
        ),
        "compounding_formula": _COMPOUNDING_FORMULA,
        "spec_source": _SPEC_SOURCE,
        **rq,
    }
    return row


def _apply_liquidity(row: dict[str, Any]) -> None:
    oi = row.get("open_interest") or 0
    vol = row.get("volume") or 0
    if oi > 0:
        row["liquidity"] = "open_interest"
    elif vol > 0:
        row["liquidity"] = "volume_only"
    else:
        row["liquidity"] = "no_open_interest"


def _filter_esr_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: str | None,
    expiry_ref: str | None,
) -> list[dict[str, Any]]:
    """Drop expired, illiquid serials, and strip outliers."""
    if not rows:
        return []
    ref_date = date.fromisoformat(as_of) if as_of else None
    expiry_date = date.fromisoformat(expiry_ref) if expiry_ref else None

    surviving: list[dict[str, Any]] = []
    for row in rows:
        term = date.fromisoformat(row["termination_date"])
        if ref_date is not None and ref_date >= term:
            continue
        if ref_date is None and expiry_date is not None and term <= expiry_date:
            continue
        oi = row.get("open_interest") or 0
        vol = row.get("volume") or 0
        if row.get("listing") == "serial" and oi == 0 and vol == 0:
            continue
        surviving.append(row)

    anchors = [
        r
        for r in surviving
        if r.get("listing") == "quarterly" and ((r.get("open_interest") or 0) > 0 or (r.get("volume") or 0) > 0)
    ]
    if len(anchors) >= 2:
        median = statistics.median(float(r["implied_rate"]) for r in anchors)
        surviving = [
            r
            for r in surviving
            if abs(float(r["implied_rate"]) - median) <= _OUTLIER_BAND_PP
        ]

    out: list[dict[str, Any]] = []
    for row in surviving:
        _apply_liquidity(row)
        if as_of:
            row["accrual_role"] = _accrual_role(as_of, row)
            if row["accrual_role"] == "expired":
                continue
        out.append(row)

    out.sort(key=lambda r: (r["reference_start"], r["code"]))
    return out


def _verify_settlements_payload(payload: object, *, session_date: date) -> dict[str, Any]:
    if isinstance(payload, list):
        raise ValueError("bare list CME ESR settlements payload is undated")
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected CME ESR settlements payload type: {type(payload)!r}")
    report_type = payload.get("reportType")
    if report_type is None or str(report_type).strip().lower() != "final":
        raise ValueError(f"non-final CME ESR settlement reportType={report_type!r}")
    ds_header = payload.get("dsHeader")
    if ds_header is not None and "ESTR" not in str(ds_header).upper():
        raise ValueError(f"wrong CME ESR product dsHeader={ds_header!r}")
    settlements = payload.get("settlements")
    if not isinstance(settlements, list) or not settlements:
        raise ValueError("empty or missing CME ESR settlements list")
    observation_date = _iso_calendar_date(payload.get("tradeDate"))
    if not observation_date:
        raise ValueError("CME ESR settlements payload missing verified tradeDate")
    if observation_date != session_date.isoformat():
        raise ValueError(
            f"CME ESR tradeDate {observation_date!r} does not match "
            f"requested session {session_date.isoformat()!r}"
        )
    update_time = payload.get("updateTime")
    if update_time is not None and str(update_time).strip():
        updated = _parse_cme_update_time(update_time)
        if not updated:
            raise ValueError(f"unparseable CME ESR updateTime={update_time!r}")
        if updated != observation_date:
            raise ValueError(
                f"CME ESR updateTime date {updated!r} contradicts tradeDate {observation_date!r}"
            )
    return payload


def parse_cme_esr_settlements_json(
    text: str,
    *,
    benchmark: float | None,
    session_date: date,
    source_url: str | None,
) -> list[dict]:
    """Parse and validate official CME ESR (product 10247) settlement JSON."""
    payload = json.loads(text)
    verified = _verify_settlements_payload(payload, session_date=session_date)
    observation_date = _iso_calendar_date(verified.get("tradeDate"))
    assert observation_date is not None
    report_type = str(verified.get("reportType") or "").strip()

    rows: list[dict[str, Any]] = []
    for item in verified.get("settlements") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("month") or "")
        parsed = _parse_month_label(label)
        price = _settlement_price(item)
        if not parsed or price is None or not (90.0 < price < 100.5):
            continue
        named_month, month_abbr, year_digit = parsed
        code = f"ESR{_MONTH_CODES[month_abbr]}{year_digit}"
        row = _base_row(
            named_month=named_month,
            code=code,
            price=price,
            benchmark=benchmark,
            volume=_optional_count(item.get("volume")),
            open_interest=_optional_count(item.get("openInterest")),
        )
        row.update(
            {
                "observation_date": observation_date,
                "as_of": observation_date,
                "source": "CME_ESR_SETTLEMENT",
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
                "source_url": source_url,
                "report_type": report_type,
            }
        )
        rows.append(row)

    rows = _filter_esr_rows(rows, as_of=observation_date, expiry_ref=None)
    if not rows:
        raise ValueError("CME ESR settlement response contained no usable contracts after filters")
    return rows


def _extract_esignal_retrieval_date(text: str) -> str | None:
    match = re.search(
        r"Delayed data retrieved on\s+([A-Za-z]+\s+\d{1,2}\s+\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    return _iso_calendar_date(match.group(1))


def _esignal_quote_price(cell: str) -> float | None:
    m = re.fullmatch(r"\s*(9\d(?:\.\d+)?)\s*[s]?\s*", cell, re.I)
    return float(m.group(1)) if m else None


def parse_esignal_esr_html(text: str, *, benchmark: float | None) -> list[dict]:
    """Parse delayed ESR chain from eSignal HTML."""
    retrieved_on = _extract_esignal_retrieval_date(text)
    if not retrieved_on:
        raise ValueError("eSignal ESR page missing delayed data retrieval banner")

    retrieval_date = date.fromisoformat(retrieved_on)
    session_verified = False
    observation_date: str | None = None
    if retrieval_date.weekday() < 5:
        observation_date = retrieved_on

    parser = _TableParser()
    parser.feed(text)
    rows: list[dict[str, Any]] = []
    code_to_monthnum = {letter: MONTHS[abbr] for abbr, letter in _MONTH_CODES.items()}

    for table in parser.tables:
        for row in table:
            joined = " ".join(row)
            m = re.search(r"ESR\s+([FGHJKMNQUVXZ])(\d{2})-CME\b", joined, re.I)
            if not m:
                continue
            letter = m.group(1).upper()
            month_abbr = _CODE_TO_MONTH[letter]
            year = 2000 + int(m.group(2))
            named_month = f"{year:04d}-{code_to_monthnum[letter]:02d}"
            price = next(
                (p for p in (_esignal_quote_price(cell) for cell in row) if p is not None),
                None,
            )
            if price is None or not (90.0 < price < 100.5):
                continue
            code = f"ESR{letter}{m.group(2)[-1]}"
            built = _base_row(
                named_month=named_month,
                code=code,
                price=price,
                benchmark=benchmark,
                volume=None,
                open_interest=None,
            )
            built.update(
                {
                    "observation_date": observation_date,
                    "as_of": observation_date,
                    "source": "ESIGNAL_CME_ESR_DELAYED",
                    "mark_kind": "delayed_quote",
                    "trade_date_verified": False,
                    "session_verified": session_verified,
                    "retrieval_date": retrieved_on,
                }
            )
            rows.append(built)

    if not rows:
        blob = " ".join(parser.text)
        pattern = re.compile(
            r"ESR\s+([FGHJKMNQUVXZ])(\d{2})-CME.{0,160}?(9\d(?:\.\d+)?)\s*[s]?",
            re.I,
        )
        for m in pattern.finditer(blob):
            letter = m.group(1).upper()
            year = 2000 + int(m.group(2))
            named_month = f"{year:04d}-{MONTHS[_CODE_TO_MONTH[letter]]:02d}"
            code = f"ESR{letter}{m.group(2)[-1]}"
            price = float(m.group(3))
            if not (90.0 < price < 100.5):
                continue
            built = _base_row(
                named_month=named_month,
                code=code,
                price=price,
                benchmark=benchmark,
                volume=None,
                open_interest=None,
            )
            built.update(
                {
                    "observation_date": observation_date,
                    "as_of": observation_date,
                    "source": "ESIGNAL_CME_ESR_DELAYED",
                    "mark_kind": "delayed_quote",
                    "trade_date_verified": False,
                    "session_verified": session_verified,
                    "retrieval_date": retrieved_on,
                }
            )
            rows.append(built)

    rows = sorted({r["code"]: r for r in rows}.values(), key=lambda r: r["reference_start"])
    rows = _filter_esr_rows(
        rows,
        as_of=observation_date,
        expiry_ref=retrieved_on if observation_date is None else None,
    )
    if not rows:
        raise ValueError("eSignal delayed ESR quote board contained no usable contracts")
    return rows


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
    for impersonate in ("chrome", "safari18_0"):
        try:
            resp = cffi_requests.get(url, impersonate=impersonate, timeout=30, headers=headers)
        except Exception as exc:
            last = str(exc)
            continue
        if getattr(resp, "status_code", 0) == 200 and resp.content:
            return bytes(resp.content), f"curl_cffi/{impersonate}"
        last = f"http_{getattr(resp, 'status_code', '?')}"
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


def _accept_fresh_esr_rows(rows: list[dict[str, Any]], today: date) -> None:
    observed_raw = rows[0].get("observation_date") or rows[0].get("as_of")
    if not observed_raw:
        raise ValueError("ESR source missing verified observation date")
    delta = (today - date.fromisoformat(str(observed_raw))).days
    if delta > FRESH_MAX_AGE_DAYS:
        raise ValueError(f"ESR observation {observed_raw} is older than {FRESH_MAX_AGE_DAYS} days")
    if delta < -1:
        raise ValueError(f"ESR observation {observed_raw} is after the session date")


def _comparable_fallback(
    delayed: list[dict[str, Any]],
    last_official: list[dict],
) -> list[dict[str, Any]]:
    official_by_code = {str(r["code"]): r for r in last_official}
    liquid_official = {
        code: row
        for code, row in official_by_code.items()
        if row.get("liquidity") in {"open_interest", "volume_only"}
    }
    if not liquid_official:
        raise ValueError("last_official has no comparable liquid ESR contracts")
    delayed_by_code = {str(r["code"]): r for r in delayed}
    overlap = set(liquid_official) & set(delayed_by_code)
    if not overlap:
        raise ValueError("delayed ESR board not comparable to last official strip")
    for code in overlap:
        off_price = float(liquid_official[code]["price"])
        del_price = float(delayed_by_code[code]["price"])
        if abs(off_price - del_price) > _FALLBACK_MAX_INDEX_GAP:
            raise ValueError(
                f"delayed ESR price for {code} diverges from last official "
                f"({del_price} vs {off_price})"
            )
    return delayed


def _accept_delayed_without_official(delayed: list[dict[str, Any]], *, today: date, retrieved_on: str) -> None:
    retrieval = date.fromisoformat(retrieved_on)
    if retrieval.weekday() >= 5:
        raise ValueError("cannot verify ESR session from weekend delayed retrieval without official marks")
    delta = (today - retrieval).days
    if delta > FRESH_MAX_AGE_DAYS or delta < -1:
        raise ValueError(f"ESR delayed retrieval {retrieved_on} outside freshness window")
    quarterly = [r for r in delayed if r.get("listing") == "quarterly"]
    if len(quarterly) < 4:
        raise ValueError("insufficient quarterly ESR contracts on delayed board")


def acquire_esr_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    benchmark: float | None = None,
    last_official: list | None = None,
) -> tuple[list, str, str, dict]:
    """Acquire ESR strips from CME settlements, then optional eSignal fallback."""
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None

    for offset in range(0, 8):
        session = today - timedelta(days=offset)
        trade_date = session.strftime("%m/%d/%Y")
        url = CME_ESR_SETTLEMENTS_TEMPLATE.format(trade_date=trade_date)
        attempt: dict[str, Any] = {"url": url, "http_status": None, "error": None, "via": None}
        try:
            raw, attempt = _fetch_bytes(fetch_bytes, url, referer=CME_ESR_PAGE)
            body = raw.decode("utf-8", errors="replace")
            rows = parse_cme_esr_settlements_json(
                body,
                benchmark=benchmark,
                session_date=session,
                source_url=url,
            )
            _accept_fresh_esr_rows(rows, today)
            trade_iso = rows[0]["observation_date"]
            obs_date = date.fromisoformat(str(trade_iso))
            session_expected = latest_expected_cme_session(today).isoformat()
            freshness_hint = classify_mark_freshness(
                curve_key="ESR",
                observation=obs_date,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            )
            for row in rows:
                row["session_expected"] = session_expected
                row["freshness"] = freshness_hint
            provenance = {
                "attempts": attempts,
                "mark_kind": "official_settlement",
                "report_type": rows[0].get("report_type"),
                "trade_date": trade_iso,
                "via": attempt.get("via"),
                "freshness_hint": freshness_hint,
                "session_expected": session_expected,
            }
            attempts.append(attempt)
            return rows, url, "CME ESR settlements API", provenance
        except Exception as exc:
            last_error = exc
            attempt["error"] = str(exc)
            attempts.append(attempt)

    try:
        raw, attempt = _fetch_bytes(fetch_bytes, ESIGNAL_ESR_CHAIN_URL, referer=ESIGNAL_ESR_CHAIN_URL)
        attempts.append(attempt)
        html = raw.decode("utf-8", errors="replace")
        delayed = parse_esignal_esr_html(html, benchmark=benchmark)
        delayed_url = ESIGNAL_ESR_CHAIN_URL
        retrieved_on = delayed[0]["retrieval_date"]
        if last_official:
            delayed = _comparable_fallback(delayed, last_official)
        else:
            _accept_delayed_without_official(delayed, today=today, retrieved_on=retrieved_on)
        session_expected = latest_expected_cme_session(today).isoformat()
        obs_raw = delayed[0].get("observation_date")
        obs_date = date.fromisoformat(str(obs_raw)) if obs_raw else None
        freshness_hint = classify_mark_freshness(
            curve_key="ESR",
            observation=obs_date,
            today=today,
            mark_kind="delayed_quote",
            trade_date_verified=False,
        )
        for row in delayed:
            row["session_expected"] = session_expected
            row["freshness"] = freshness_hint
        provenance = {
            "attempts": attempts,
            "mark_kind": "delayed_quote",
            "report_type": None,
            "trade_date": delayed[0].get("observation_date"),
            "via": attempt.get("via"),
            "freshness_hint": freshness_hint,
            "session_expected": session_expected,
        }
        return delayed, delayed_url, "delayed CME ESR futures chain via eSignal", provenance
    except Exception as exc:
        last_error = exc
        attempts.append(
            {
                "url": ESIGNAL_ESR_CHAIN_URL,
                "http_status": None,
                "error": str(exc),
                "via": None,
            }
        )

    raise ValueError(
        f"no usable ESR contract marks in {FRESH_MAX_AGE_DAYS}-day lookback: {last_error}"
    )


def probe_cme_esr(fetch_bytes: FetchBytes, *, session_date: date) -> dict:
    """Single-session CME ESR settlements probe; never raises."""
    url = CME_ESR_SETTLEMENTS_TEMPLATE.format(trade_date=session_date.strftime("%m/%d/%Y"))
    out: dict[str, Any] = {
        "url": url,
        "http_status": None,
        "via": None,
        "ok": False,
        "report_type": None,
        "trade_date": None,
        "ds_header": None,
        "settlement_count": None,
        "schema_keys": None,
        "error": None,
        "body_excerpt": None,
    }
    try:
        raw, attempt = _fetch_bytes(fetch_bytes, url, referer=CME_ESR_PAGE)
        out["http_status"] = attempt.get("http_status")
        out["via"] = attempt.get("via")
        body = raw.decode("utf-8", errors="replace")
        out["body_excerpt"] = body[:180]
        payload = json.loads(body)
        if isinstance(payload, dict):
            out["schema_keys"] = sorted(payload.keys())
            out["report_type"] = payload.get("reportType")
            out["trade_date"] = payload.get("tradeDate")
            out["ds_header"] = payload.get("dsHeader")
            settlements = payload.get("settlements")
            if isinstance(settlements, list):
                out["settlement_count"] = len(settlements)
            try:
                _verify_settlements_payload(payload, session_date=session_date)
                out["ok"] = True
            except Exception as exc:
                out["error"] = str(exc)
        else:
            out["error"] = f"unexpected payload type {type(payload)!r}"
    except Exception as exc:
        out["error"] = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            out["http_status"] = exc.code
    return out
