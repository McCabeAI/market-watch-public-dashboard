"""ASX futures EOD report parser (IB 30-day cash rate and IR 90-day bank bills).

ASX business-day holidays (NSW / ASX 24) used for last-trading-day calendar logic,
not downloaded live:

2026: 2026-01-01, 2026-01-26, 2026-04-03, 2026-04-06, 2026-06-08, 2026-12-25, 2026-12-28
2027: 2027-01-01, 2027-01-26, 2027-03-26, 2027-03-29, 2027-04-26, 2027-06-14, 2027-12-27, 2027-12-28
2028: 2028-01-03, 2028-01-26, 2028-04-14, 2028-04-17, 2028-04-25, 2028-06-12, 2028-12-25, 2028-12-26
2029: 2029-01-01, 2029-01-26, 2029-03-30, 2029-04-02, 2029-04-25, 2029-06-11, 2029-12-25, 2029-12-26
2030: 2030-01-01, 2030-01-28, 2030-04-19, 2030-04-22, 2030-04-25, 2030-06-10, 2030-12-25, 2030-12-26
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, FrozenSet

from scripts.asx_futures_cache import (
    default_cache_path,
    load_cache,
    save_product,
    validate_record,
)

FetchBytes = Callable[..., bytes]

ASX_EOD_TEMPLATE = (
    "https://www.asx.com.au/data/futures/reports/EODWebMarketSummary{yymmdd}SFD.htm"
)
CURRENT_MAX_CALENDAR_DAYS = 4
STALE_MAX_CALENDAR_DAYS = 10

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}

_QUARTERLY_MONTHS = frozenset({3, 6, 9, 12})

_IR_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}

_ASX_HOLIDAYS: dict[int, frozenset[date]] = {
    2026: frozenset(
        date.fromisoformat(s)
        for s in (
            "2026-01-01", "2026-01-26", "2026-04-03", "2026-04-06",
            "2026-06-08", "2026-12-25", "2026-12-28",
        )
    ),
    2027: frozenset(
        date.fromisoformat(s)
        for s in (
            "2027-01-01", "2027-01-26", "2027-03-26", "2027-03-29",
            "2027-04-26", "2027-06-14", "2027-12-27", "2027-12-28",
        )
    ),
    2028: frozenset(
        date.fromisoformat(s)
        for s in (
            "2028-01-03", "2028-01-26", "2028-04-14", "2028-04-17",
            "2028-04-25", "2028-06-12", "2028-12-25", "2028-12-26",
        )
    ),
    2029: frozenset(
        date.fromisoformat(s)
        for s in (
            "2029-01-01", "2029-01-26", "2029-03-30", "2029-04-02",
            "2029-04-25", "2029-06-11", "2029-12-25", "2029-12-26",
        )
    ),
    2030: frozenset(
        date.fromisoformat(s)
        for s in (
            "2030-01-01", "2030-01-28", "2030-04-19", "2030-04-22",
            "2030-04-25", "2030-06-10", "2030-12-25", "2030-12-26",
        )
    ),
}

_PRODUCT_HEADER = re.compile(r"^[A-Z]{1,3}\s*-\s")
_TRADE_DATE_BODY = re.compile(
    r"close of trade date\s+(\d{2})/(\d{2})/(\d{2})",
    re.IGNORECASE,
)
_REPORT_TIME = re.compile(
    r"Report Generation Time:\s*"
    r"([A-Za-z]{3},\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)

IB_SECTION_LABEL = "IB - 30 DAY INTERBANK CASH RATE"
IR_SECTION_LABEL = "IR - 90-DAY BANK BILLS"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _num(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in {"-", "—", "UNCH", "N/A", "NA"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
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
        if self._cell is not None:
            self._cell.append(cleaned)


def _all_rows(text: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(text)
    rows: list[list[str]] = []
    for table in parser.tables:
        rows.extend(table)
    return rows


def _parse_expiry(label: str) -> str | None:
    s = _clean(label).upper()
    match = re.search(
        r"\b(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|"
        r"JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
        r"[\s-]+(20\d{2})\b",
        s,
    )
    if not match:
        return None
    month = MONTHS[match.group(1)]
    return f"{match.group(2)}-{month:02d}"


def _is_business_day(d: date, extra_holidays: FrozenSet[date] = frozenset()) -> bool:
    if d.weekday() >= 5:
        return False
    year_holidays = _ASX_HOLIDAYS.get(d.year, frozenset())
    return d not in year_holidays and d not in extra_holidays


def _prev_business_day(d: date, extra_holidays: FrozenSet[date] = frozenset()) -> date:
    cur = d - timedelta(days=1)
    while not _is_business_day(cur, extra_holidays):
        cur -= timedelta(days=1)
    return cur


def _last_calendar_day(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def second_friday_of_month(year: int, month: int) -> date:
    first = date(year, month, 1)
    days_to_friday = (4 - first.weekday()) % 7
    first_friday = first + timedelta(days=days_to_friday)
    return first_friday + timedelta(days=7)


def ir_settlement_day(expiry: str) -> date:
    year_s, month_s = expiry.split("-")
    return second_friday_of_month(int(year_s), int(month_s))


def ir_last_trading_day(
    expiry: str,
    extra_holidays: FrozenSet[date] = frozenset(),
) -> date:
    settlement = ir_settlement_day(expiry)
    return _prev_business_day(settlement, extra_holidays)


def ib_last_trading_day(
    expiry: str,
    extra_holidays: FrozenSet[date] = frozenset(),
) -> date:
    year_s, month_s = expiry.split("-")
    year, month = int(year_s), int(month_s)
    cur = _last_calendar_day(year, month)
    while not _is_business_day(cur, extra_holidays):
        cur -= timedelta(days=1)
    return cur


def _ir_contract_code(expiry: str) -> str:
    year_s, month_s = expiry.split("-")
    return f"IR{_IR_MONTH_CODES[int(month_s)]}{year_s[2:]}"


def _parse_trade_date_ddmmyy(day: str, month: str, year_2: str) -> date:
    return date(2000 + int(year_2), int(month), int(day))


def _extract_trade_dates(text: str) -> tuple[date | None, date | None, str | None]:
    """Return (title_trade_date, body_trade_date, document_error)."""
    title_match = re.search(
        r"<title>\s*([^<]+)</title>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    title_date: date | None = None
    if title_match:
        tm = _TRADE_DATE_BODY.search(title_match.group(1))
        if tm:
            title_date = _parse_trade_date_ddmmyy(tm.group(1), tm.group(2), tm.group(3))

    body_dates: list[date] = []
    for m in _TRADE_DATE_BODY.finditer(text):
        body_dates.append(_parse_trade_date_ddmmyy(m.group(1), m.group(2), m.group(3)))

    body_date: date | None = None
    if body_dates:
        body_date = body_dates[0]
        if any(d != body_date for d in body_dates[1:]):
            return title_date, body_date, "ASX EOD report body trade dates disagree"

    if title_date and body_date and title_date != body_date:
        return title_date, body_date, "ASX EOD title and body trade dates disagree"

    return title_date, body_date, None


def _extract_publication_time(text: str) -> str | None:
    match = _REPORT_TIME.search(text)
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1).strip(), "%a, %d %b %Y %H:%M:%S")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _row_is_product_header(row: list[str]) -> bool:
    joined = _clean(" ".join(row))
    return bool(_PRODUCT_HEADER.match(joined))


def _section_for_product(rows: list[list[str]], marker: str) -> list[list[str]] | None:
    start_idx: int | None = None
    for i, row in enumerate(rows):
        joined = _clean(" ".join(row)).upper()
        if marker in joined and _row_is_product_header(row):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    section: list[list[str]] = []
    for row in rows[start_idx:]:
        if _row_is_product_header(row):
            break
        section.append(row)
    return section


def _price_plausible(price: float | None) -> bool:
    return price is not None and 90.0 < price < 100.5


def _parse_product_rows(
    section: list[list[str]],
    *,
    product_code: str,
    source: str,
    session_date: str,
    publication_time: str | None,
    source_url: str | None,
    benchmark: float | None,
    extra_holidays: FrozenSet[date],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows: list[dict[str, Any]] = []
    session = date.fromisoformat(session_date)

    for row in section:
        if not row:
            continue
        joined = _clean(" ".join(row)).upper()
        if joined.startswith("EXPIRY"):
            continue
        if "CLICK HERE" in joined:
            continue
        expiry = _parse_expiry(row[0])
        if not expiry:
            continue
        open_ = _num(row[1]) if len(row) > 1 else None
        high = _num(row[2]) if len(row) > 2 else None
        low = _num(row[3]) if len(row) > 3 else None
        last = _num(row[4]) if len(row) > 4 else None
        price = _num(row[5]) if len(row) > 5 else None
        sett_chg = _num(row[6]) if len(row) > 6 else None
        oi = _num(row[7]) if len(row) > 7 else None
        oi_chg = _num(row[8]) if len(row) > 8 else None
        volume = _num(row[9]) if len(row) > 9 else None

        year_s, month_s = expiry.split("-")
        month_i = int(month_s)
        listing_role = "monthly" if product_code == "IB" else (
            "quarterly" if month_i in _QUARTERLY_MONTHS else "serial"
        )

        if product_code == "IB":
            ltd = ib_last_trading_day(expiry, extra_holidays)
            settlement_day = ltd
            code = None
        else:
            settlement_day = ir_settlement_day(expiry)
            ltd = ir_last_trading_day(expiry, extra_holidays)
            code = _ir_contract_code(expiry)

        tradable = False
        exclusion_reason: str | None = None
        implied: float | None = None

        if not _price_plausible(price):
            exclusion_reason = "invalid"
        elif session > ltd:
            exclusion_reason = "expired"
        elif product_code == "IR" and listing_role == "serial":
            has_flow = (volume or 0) > 0 or (oi or 0) > 0
            if not has_flow:
                exclusion_reason = "illiquid_serial"
            else:
                tradable = True
        else:
            tradable = True

        if _price_plausible(price):
            implied = round(100.0 - float(price), 6)

        record: dict[str, Any] = {
            "expiry": expiry,
            "code": code,
            "price": round(float(price), 6) if _price_plausible(price) else price,
            "implied_rate": implied,
            "open": open_,
            "high": high,
            "low": low,
            "last": last,
            "settlement_change": sett_chg,
            "volume": volume,
            "open_interest": oi,
            "open_interest_change": oi_chg,
            "listing_role": listing_role,
            "tradable": tradable,
            "exclusion_reason": exclusion_reason,
            "last_trading_day": ltd.isoformat(),
            "settlement_day": settlement_day.isoformat(),
            "source": source,
            "observation_date": session_date,
            "as_of": session_date,
            "publication_time": publication_time,
            "source_url": source_url,
            "product_code": product_code,
        }
        if product_code == "IB" and benchmark is not None and implied is not None:
            record["change_from_overnight_bps"] = round((implied - benchmark) * 100.0, 2)

        raw_rows.append(record)

    raw_rows.sort(key=lambda r: r["expiry"])
    contracts = [r for r in raw_rows if r.get("tradable")]
    return contracts, raw_rows


def _empty_product_block(
    *,
    session_date: str | None,
    publication_time: str | None,
    source_url: str | None,
    error: str | None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "error": error,
        "contracts": [],
        "raw_contracts": [],
        "session_date": session_date,
        "publication_time": publication_time,
        "source_url": source_url,
    }


def _finalize_product_block(
    contracts: list[dict[str, Any]],
    raw_contracts: list[dict[str, Any]],
    *,
    session_date: str,
    publication_time: str | None,
    source_url: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    valid = [r for r in raw_contracts if r.get("implied_rate") is not None]
    status = "ok" if valid else "unavailable"
    return {
        "status": status,
        "error": error,
        "contracts": contracts,
        "raw_contracts": raw_contracts,
        "session_date": session_date,
        "publication_time": publication_time,
        "source_url": source_url,
    }


def parse_asx_eod_products(
    text: str,
    *,
    benchmark: float | None = None,
    source_url: str | None = None,
    extra_holidays: FrozenSet[date] = frozenset(),
) -> dict[str, Any]:
    title_date, body_date, date_error = _extract_trade_dates(text)
    publication_time = _extract_publication_time(text)
    rows = _all_rows(text)

    session_date: str | None = None
    document_error = date_error
    if body_date is None:
        document_error = document_error or "ASX EOD report body is missing the trade date"
    else:
        session_date = body_date.isoformat()

    products: dict[str, dict[str, Any]] = {}

    if document_error or session_date is None:
        err = document_error or "ASX EOD report body is missing the trade date"
        products["IB"] = _empty_product_block(
            session_date=session_date,
            publication_time=publication_time,
            source_url=source_url,
            error=err,
        )
        products["IR"] = _empty_product_block(
            session_date=session_date,
            publication_time=publication_time,
            source_url=source_url,
            error=err,
        )
        return {
            "session_date": session_date,
            "publication_time": publication_time,
            "document_error": err,
            "products": products,
        }

    for code, marker, source in (
        ("IB", IB_SECTION_LABEL, "ASX_30D_AONIA"),
        ("IR", IR_SECTION_LABEL, "ASX_90D_BBSW"),
    ):
        try:
            section = _section_for_product(rows, marker)
            if section is None:
                products[code] = _empty_product_block(
                    session_date=session_date,
                    publication_time=publication_time,
                    source_url=source_url,
                    error=f"ASX EOD report missing {code} section",
                )
                continue
            contracts, raw_contracts = _parse_product_rows(
                section,
                product_code=code,
                source=source,
                session_date=session_date,
                publication_time=publication_time,
                source_url=source_url,
                benchmark=benchmark if code == "IB" else None,
                extra_holidays=extra_holidays,
            )
            products[code] = _finalize_product_block(
                contracts,
                raw_contracts,
                session_date=session_date,
                publication_time=publication_time,
                source_url=source_url,
            )
        except Exception as exc:
            products[code] = _empty_product_block(
                session_date=session_date,
                publication_time=publication_time,
                source_url=source_url,
                error=str(exc),
            )

    _ = title_date  # validated via document_error when mismatched
    return {
        "session_date": session_date,
        "publication_time": publication_time,
        "document_error": document_error,
        "products": products,
    }


def legacy_ib_rows(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    parsed = parse_asx_eod_products(text, benchmark=benchmark)
    block = parsed["products"]["IB"]
    rows_source = block.get("raw_contracts", [])
    if block["status"] != "ok" and not rows_source:
        err = parsed.get("document_error") or ""
        if err and "missing the trade date" in err:
            section = _section_for_product(_all_rows(text), IB_SECTION_LABEL)
            if section is not None:
                _, rows_source = _parse_product_rows(
                    section,
                    product_code="IB",
                    source="ASX_30D_AONIA",
                    session_date="2099-01-01",
                    publication_time=None,
                    source_url=None,
                    benchmark=benchmark,
                    extra_holidays=frozenset(),
                )
    if not rows_source:
        raise ValueError("ASX EOD report did not expose 30-day cash-rate futures")
    legacy: list[dict[str, Any]] = []
    for row in rows_source:
        if row.get("implied_rate") is None:
            continue
        price = row.get("price")
        if not _price_plausible(_num(price) if price is not None else None):
            continue
        legacy.append(
            {
                "expiry": row["expiry"],
                "code": None,
                "price": row["price"],
                "implied_rate": row["implied_rate"],
                "change_from_overnight_bps": row.get("change_from_overnight_bps"),
                "volume": row.get("volume"),
                "open_interest": row.get("open_interest"),
                "source": "ASX_30D_AONIA",
            }
        )
    legacy = sorted({row["expiry"]: row for row in legacy}.values(), key=lambda r: r["expiry"])
    if not legacy:
        raise ValueError("ASX EOD report did not expose 30-day cash-rate futures")
    for row in legacy:
        if row.get("change_from_overnight_bps") is None and benchmark is not None:
            row["change_from_overnight_bps"] = round(
                (row["implied_rate"] - benchmark) * 100.0, 2
            )
    return legacy


def _product_freshness(session_date: date, today: date) -> tuple[str, bool, str] | None:
    age = (today - session_date).days
    if age < -1:
        return None
    if age > STALE_MAX_CALENDAR_DAYS:
        return None
    if age <= CURRENT_MAX_CALENDAR_DAYS:
        return "ok", True, "current"
    return "stale", False, "stale"


def _cache_product_block(
    record: dict[str, Any],
    *,
    today: date,
    product: str,
) -> dict[str, Any] | None:
    if not validate_record(record, product=product):
        return None
    session_date = date.fromisoformat(record["session_date"])
    fresh = _product_freshness(session_date, today)
    if fresh is None:
        return None
    _status, _eligible, _fresh = fresh
    status = "stale"
    execution_eligible = False
    freshness = "stale"
    contracts = record.get("contracts", [])
    return {
        "status": status,
        "freshness": freshness,
        "execution_eligible": execution_eligible,
        "error": None,
        "contracts": contracts,
        "raw_contracts": list(contracts),
        "as_of": record["session_date"],
        "observation_date": record["session_date"],
        "source_url": record.get("source_url"),
        "provenance": "last_good_cache",
        "publication_time": record.get("publication_time"),
        "session_date": record["session_date"],
    }


def _report_product_block(
    block: dict[str, Any],
    *,
    today: date,
    product: str,
) -> dict[str, Any] | None:
    if block.get("status") != "ok":
        return None
    session_s = block.get("session_date")
    if not session_s:
        return None
    session_date = date.fromisoformat(session_s)
    fresh = _product_freshness(session_date, today)
    if fresh is None:
        return None
    status, execution_eligible, freshness = fresh
    return {
        "status": status,
        "freshness": freshness,
        "execution_eligible": execution_eligible,
        "error": block.get("error"),
        "contracts": block.get("contracts", []),
        "raw_contracts": block.get("raw_contracts", []),
        "as_of": session_s,
        "observation_date": session_s,
        "source_url": block.get("source_url"),
        "provenance": "asx_eod_report",
        "publication_time": block.get("publication_time"),
        "session_date": session_s,
    }


def _build_cache_record(block: dict[str, Any], product: str) -> dict[str, Any] | None:
    if block.get("status") != "ok":
        return None
    contracts = block.get("contracts") or []
    if not contracts:
        return None
    session_date = block.get("session_date")
    if not session_date:
        return None
    stamped = []
    for row in contracts:
        copy = dict(row)
        copy["as_of"] = session_date
        copy["observation_date"] = session_date
        stamped.append(copy)
    return {
        "product": product,
        "session_date": session_date,
        "as_of": session_date,
        "source_url": block.get("source_url") or "",
        "publication_time": block.get("publication_time"),
        "contracts": stamped,
    }


def acquire_asx_cash_futures(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    benchmark: float | None = None,
    cache_path: str | None = None,
    lookback_days: int = 8,
) -> dict[str, Any]:
    path = cache_path or default_cache_path()
    cache = load_cache(path)

    accepted: dict[str, Any] | None = None
    accepted_url: str | None = None
    fetch_error: str | None = None
    errors: list[str] = []

    for offset in range(lookback_days):
        candidate = today - timedelta(days=offset)
        url = ASX_EOD_TEMPLATE.format(yymmdd=candidate.strftime("%y%m%d"))
        try:
            raw = fetch_bytes(
                url,
                user_agent=_BROWSER_UA,
                referer="https://www.asx.com.au/",
            )
            if isinstance(raw, str):
                body = raw
            else:
                body = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        parsed = parse_asx_eod_products(
            body,
            benchmark=benchmark,
            source_url=url,
        )
        if parsed.get("document_error"):
            errors.append(f"{url}: {parsed['document_error']}")
            continue
        session_s = parsed.get("session_date")
        if not session_s:
            errors.append(f"{url}: missing session date")
            continue
        if date.fromisoformat(session_s) != candidate:
            errors.append(f"{url}: session {session_s} != candidate {candidate.isoformat()}")
            continue
        session_date = date.fromisoformat(session_s)
        age = (today - session_date).days
        if age < -1 or age > STALE_MAX_CALENDAR_DAYS:
            errors.append(f"{url}: freshness age {age} out of range")
            continue
        accepted = parsed
        accepted_url = url
        break

    if accepted is None:
        fetch_error = "; ".join(errors) if errors else "no usable ASX EOD report in lookback"

    result_products: dict[str, dict[str, Any]] = {}
    top_session: str | None = None
    top_publication: str | None = None

    for product in ("IB", "IR"):
        block: dict[str, Any] | None = None
        if accepted is not None:
            src_block = accepted["products"][product]
            block = _report_product_block(src_block, today=today, product=product)
            if block is None and src_block.get("status") != "ok":
                block = None
            elif block is not None:
                record = _build_cache_record(src_block, product)
                if record and validate_record(record, product=product):
                    save_product(path, product, record)

        if block is None:
            cached = cache.get("products", {}).get(product)
            block = _cache_product_block(cached, today=today, product=product) if cached else None

        if block is None:
            block = {
                "status": "unavailable",
                "freshness": None,
                "execution_eligible": False,
                "error": fetch_error if accepted is None else accepted["products"][product].get("error"),
                "contracts": [],
                "raw_contracts": [],
                "as_of": None,
                "observation_date": None,
                "source_url": accepted_url if accepted else None,
                "provenance": None,
                "publication_time": None,
                "session_date": None,
            }
        result_products[product] = block
        if block.get("as_of") and top_session is None:
            top_session = block.get("session_date") or block.get("as_of")
            top_publication = block.get("publication_time")

    if accepted is not None:
        top_session = accepted.get("session_date")
        top_publication = accepted.get("publication_time")

    return {
        "source_url": accepted_url,
        "session_date": top_session,
        "publication_time": top_publication if accepted else top_publication,
        "fetch_error": fetch_error,
        "products": result_products,
    }


def bbsw_ois_basis_evidence(
    *,
    cash_basis: dict[str, Any] | None,
    ir_product: dict[str, Any] | None,
    ib_product: dict[str, Any] | None,
) -> dict[str, Any]:
    _ = ir_product, ib_product
    reason = (
        "Futures FRA-OIS basis is unavailable: IR settlements imply 90-day BBSW per contract, "
        "RBA F1 provides only spot 1m/3m/6m BBSW and OIS, and IB is the monthly average AONIA "
        "(not an aligned FRA-OIS pair with IR); IR minus nearest IB is not computed."
    )
    out: dict[str, Any] = {
        "status": "unavailable",
        "reason": reason,
        "fra_ois_basis_bps": None,
    }
    if isinstance(cash_basis, dict):
        if cash_basis.get("status") == "unavailable_cross_vintage":
            out["spot_3m_bank_bill_minus_ois"] = dict(cash_basis)
            return out
        if cash_basis.get("status") == "ok":
            out["spot_3m_bank_bill_minus_ois"] = {
                **cash_basis,
                "reference": (
                    "RBA F1 spot 3-month bank bill minus spot 3-month OIS; "
                    "not a futures FRA-OIS and not IR minus IB"
                ),
            }
    return out
