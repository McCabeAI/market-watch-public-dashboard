"""Credential-free policy-path and money-market context for Market Watch.

This module keeps the policy benchmark separate from the sovereign curve:
- Canada: BoC CORRA + Montréal Exchange 1M/3M CORRA futures.
- United States: NY Fed SOFR + 1M SOFR futures (CME preferred; delayed ICE/eSignal hosted-runner fallback).
- Australia: RBA F1 AONIA/OIS/BAB data + ASX 30-day cash-rate futures.

Exchange/web prices are delayed research/reference data, never executable marks.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable

FetchBytes = Callable[..., bytes]

BOC_CORRA_PAGE = "https://www.bankofcanada.ca/rates/interest-rates/corra/"
BOC_CORRA_JSON = "https://www.bankofcanada.ca/valet/observations/group/CORRA/json?recent=10"
MX_EXPECTATIONS_URL = "https://www.m-x.ca/en/trading/tools/canadian-interest-rate-expectations"
NYFED_SOFR_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/10.json"
NYFED_SOFR_PAGE = "https://www.newyorkfed.org/markets/reference-rates/sofr"
CME_SOFR_URL = "https://www.cmegroup.com/markets/interest-rates/stirs/one-month-sofr.quotes.html"
CME_SOFR_BULLETIN_URL = "https://www.cmegroup.com/daily_bulletin/current/Section10_Interest_Rate_Futures_Continued.pdf"
ESIGNAL_SOFR_CHAIN_URL = "https://quotes.esignal.com/esignalprod/quote.action?symbol=SR1"
CME_SOFR_PRODUCT_ID = "8463"
CME_SOFR_SETTLEMENTS_TEMPLATE = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
    + CME_SOFR_PRODUCT_ID
    + "/FUT?tradeDate={trade_date}&strategy=DEFAULT&pageSize=500"
)
RBA_F1_URL = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"
RBA_F1_PAGE = "https://www.rba.gov.au/statistics/tables/"
ASX_EOD_TEMPLATE = "https://www.asx.com.au/data/futures/reports/EODWebMarketSummary{yymmdd}SFD.htm"
ASX_IR_HISTORY = (
    "https://www.asx.com.au/markets/trade-our-derivatives-market/overview/"
    "interest-rate-derivatives/interest-rate-derivatives-settlement-history"
)

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}


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


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


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


def _contract_row(
    *,
    expiry: str,
    code: str | None,
    price: float,
    benchmark: float,
    source: str,
    volume: float | None = None,
    open_interest: float | None = None,
) -> dict[str, Any]:
    implied = 100.0 - price
    return {
        "expiry": expiry,
        "code": code,
        "price": round(price, 6),
        "implied_rate": round(implied, 6),
        "change_from_overnight_bps": round((implied - benchmark) * 100.0, 2),
        "volume": volume,
        "open_interest": open_interest,
        "source": source,
    }


def parse_boc_corra_json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    observations = payload.get("observations") or []
    for row in observations:
        cell = row.get("AVG.INTWO")
        rate = _num(cell.get("v") if isinstance(cell, dict) else cell)
        if rate is not None:
            return {"rate": rate, "as_of": row.get("d")}
    raise ValueError("BoC CORRA group did not expose AVG.INTWO")


def parse_boc_corra_html(text: str) -> dict[str, Any]:
    """Compatibility parser for page fixtures; live collection uses Valet JSON."""
    parser = _TableParser()
    parser.feed(text)
    for table in parser.tables:
        header_dates: list[str] = []
        for row in table:
            if not row:
                continue
            if not header_dates:
                header_dates = [cell for cell in row if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", cell)]
            if row and "Canadian Overnight Repo Rate Average (CORRA)" in row[0]:
                values = [x for x in (_num(cell) for cell in row[1:]) if x is not None]
                if values:
                    return {"rate": values[-1], "as_of": header_dates[-1] if header_dates else None}
    raise ValueError("BoC CORRA page did not expose a current rate")

def parse_mx_expectations_html(text: str, *, benchmark: float) -> dict[str, Any]:
    parser = _TableParser()
    parser.feed(text)
    contracts: dict[str, list[dict[str, Any]]] = {"1m": [], "3m": []}
    for table in parser.tables:
        header = " | ".join(" | ".join(row) for row in table[:3]).upper()
        family = "3m" if "CRA CONTRACT" in header else "1m" if "COA CONTRACT" in header else None
        if family is None:
            continue
        for row in table:
            if not row:
                continue
            expiry = _parse_expiry(row[0])
            if not expiry:
                continue
            code_match = re.search(r"\(([A-Z0-9]+)\)", row[0].upper())
            nums = [_num(cell) for cell in row[1:]]
            price = next((x for x in nums if x is not None and 90.0 < x < 100.5), None)
            if price is None:
                continue
            contracts[family].append(
                _contract_row(
                    expiry=expiry,
                    code=code_match.group(1) if code_match else None,
                    price=price,
                    benchmark=benchmark,
                    source="MX_CORRA_FUTURES",
                )
            )
    if not contracts["1m"] and not contracts["3m"]:
        raise ValueError("MX expectations page did not expose CORRA futures rows")
    for family in contracts:
        contracts[family].sort(key=lambda row: row["expiry"])
    return contracts


def parse_nyfed_sofr_json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    rows = payload.get("refRates") or payload.get("rates") or []
    for row in rows:
        kind = str(row.get("type") or row.get("rateType") or "").upper()
        if "SOFR" not in kind:
            continue
        rate = _num(row.get("percentRate") or row.get("rate") or row.get("value"))
        if rate is None:
            continue
        return {
            "rate": rate,
            "as_of": row.get("effectiveDate") or row.get("effective_date") or row.get("date"),
        }
    raise ValueError("NY Fed response did not contain SOFR")


def _parse_cme_month(label: str) -> str | None:
    m = re.fullmatch(r"([A-Z]{3})\s+(\d{2})", _clean(label).upper())
    if not m or m.group(1) not in MONTHS:
        return None
    year = 2000 + int(m.group(2))
    return f"{year:04d}-{MONTHS[m.group(1)]:02d}"


def parse_cme_sofr_settlements_json(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    payload = json.loads(text)
    rows: list[dict[str, Any]] = []
    for item in payload.get("settlements") or []:
        expiry = _parse_cme_month(str(item.get("month") or ""))
        price = _num(item.get("settle"))
        if not expiry or price is None or not 90.0 < price < 100.5:
            continue
        rows.append(
            _contract_row(
                expiry=expiry,
                code=None,
                price=price,
                benchmark=benchmark,
                source="CME_1M_SOFR_SETTLEMENT",
                volume=_num(item.get("volume")),
                open_interest=_num(item.get("openInterest")),
            )
        )
    rows.sort(key=lambda row: row["expiry"])
    if not rows:
        raise ValueError("CME 1M SOFR settlement response contained no usable contracts")
    return rows


def parse_cme_sofr_bulletin_text(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    """Parse SR1 rows from CME's official Section 10 Daily Bulletin text."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    try:
        start = next(i for i, line in enumerate(lines) if line == "SR1 FUT")
    except StopIteration as exc:
        raise ValueError("CME Daily Bulletin did not contain SR1 FUT") from exc
    rows: list[dict[str, Any]] = []
    for line in lines[start + 1 :]:
        if line.startswith("TOTAL SR1 FUT"):
            break
        m = re.match(
            r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})\s+"
            r"(?:----\s+){0,3}.*?\s(9\d\.\d{3,4})\s+\(\s*([0-9.]+)\)",
            line,
        )
        if not m:
            continue
        expiry = f"20{m.group(2)}-{MONTHS[m.group(1)]:02d}"
        price = float(m.group(3))
        rows.append(
            _contract_row(
                expiry=expiry,
                code=None,
                price=price,
                benchmark=benchmark,
                source="CME_DAILY_BULLETIN_SR1",
            )
        )
    if not rows:
        raise ValueError("CME Daily Bulletin SR1 block contained no usable contracts")
    return rows


def parse_cme_sofr_bulletin_pdf(data: bytes, *, benchmark: float) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf required for CME Daily Bulletin") from exc
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_cme_sofr_bulletin_text(text, benchmark=benchmark)


def parse_esignal_sofr_html(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    """Parse delayed ICE One-Month SOFR index futures chain from eSignal."""
    parser = _TableParser()
    parser.feed(text)
    rows: list[dict[str, Any]] = []
    month_codes = {"F":1,"G":2,"H":3,"J":4,"K":5,"M":6,"N":7,"Q":8,"U":9,"V":10,"X":11,"Z":12}
    for table in parser.tables:
        for row in table:
            joined = " ".join(row)
            m = re.search(r"SR1\s+([FGHJKMNQUVXZ])(\d{2})", joined, re.I)
            if not m:
                continue
            nums = [_num(cell) for cell in row]
            price = next((x for x in nums if x is not None and 90.0 < x < 100.5), None)
            if price is None:
                continue
            year = 2000 + int(m.group(2))
            expiry = f"{year:04d}-{month_codes[m.group(1).upper()]:02d}"
            rows.append(
                _contract_row(
                    expiry=expiry,
                    code=f"SR1{m.group(1).upper()}{m.group(2)}",
                    price=price,
                    benchmark=benchmark,
                    source="ESIGNAL_ICE_1M_SOFR_DELAYED",
                )
            )
    if not rows:
        # Some quote-board responses are layout text rather than table markup.
        blob = " ".join(parser.text)
        pattern = re.compile(
            r"SR1\s+([FGHJKMNQUVXZ])(\d{2}).{0,80}?([9][0-9]\.\d{2,4})\s+[sey]?",
            re.I,
        )
        for m in pattern.finditer(blob):
            year = 2000 + int(m.group(2))
            rows.append(
                _contract_row(
                    expiry=f"{year:04d}-{month_codes[m.group(1).upper()]:02d}",
                    code=f"SR1{m.group(1).upper()}{m.group(2)}",
                    price=float(m.group(3)),
                    benchmark=benchmark,
                    source="ESIGNAL_ICE_1M_SOFR_DELAYED",
                )
            )
    rows = sorted({row["expiry"]: row for row in rows}.values(), key=lambda row: row["expiry"])
    if not rows:
        raise ValueError("eSignal delayed SOFR quote board exposed no usable contracts")
    return rows


def parse_cme_sofr_html(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(text)
    out: list[dict[str, Any]] = []
    for table in parser.tables:
        for row in table:
            if not row:
                continue
            first = row[0].upper()
            if "SR1" not in first:
                continue
            expiry = _parse_expiry(first)
            code = re.search(r"\b(SR1[A-Z]\d)\b", first)
            if not expiry or not code:
                continue
            # Quote table is Month, Options, Chart, Last, Change, Prior Settle, ...
            price = None
            if len(row) >= 4:
                price = _num(row[3])
            if price is None or not 90.0 < price < 100.5:
                # Defensive fallback: first plausible 90-100 quote after the contract cell.
                for cell in row[1:]:
                    candidate = _num(cell)
                    if candidate is not None and 90.0 < candidate < 100.5:
                        price = candidate
                        break
            if price is None:
                continue
            volume = _num(row[9]) if len(row) > 9 else None
            out.append(
                _contract_row(
                    expiry=expiry,
                    code=code.group(1),
                    price=price,
                    benchmark=benchmark,
                    source="CME_1M_SOFR",
                    volume=volume,
                )
            )
    dedup = {row["code"]: row for row in out}
    rows = sorted(dedup.values(), key=lambda row: row["expiry"])
    if not rows:
        raise ValueError("CME 1M SOFR page did not expose quote rows")
    return rows


def parse_rba_f1_csv(text: str) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    titles: list[str] | None = None
    series_ids: list[str] | None = None
    series_row = None
    for i, row in enumerate(rows):
        if not row:
            continue
        key = row[0].strip().lower()
        if key == "title":
            titles = row
        elif key == "series id":
            series_ids = row
            series_row = i
            break
    if titles is None or series_ids is None or series_row is None:
        raise ValueError("RBA F1 metadata rows missing")
    wanted = {
        "Interbank Overnight Cash Rate": "aonia",
        "EOD 1-month BABs/NCDs": "bill_1m",
        "EOD 3-month BABs/NCDs": "bill_3m",
        "EOD 6-month BABs/NCDs": "bill_6m",
        "1-month OIS": "ois_1m",
        "3-month OIS": "ois_3m",
        "6-month OIS": "ois_6m",
    }
    columns: dict[str, int] = {}
    for idx, title in enumerate(titles):
        if title in wanted:
            columns[wanted[title]] = idx
    missing = set(wanted.values()) - set(columns)
    if missing:
        raise ValueError(f"RBA F1 missing columns {sorted(missing)}")

    series: dict[str, list[tuple[str, float]]] = {key: [] for key in columns}
    for row in rows[series_row + 1 :]:
        if not row:
            continue
        d = row[0].strip()
        if not re.match(r"\d{2}-[A-Za-z]{3}-\d{4}$", d):
            continue
        for key, idx in columns.items():
            if idx >= len(row):
                continue
            value = _num(row[idx])
            if value is not None:
                series[key].append((d, value))
    if not series["aonia"]:
        raise ValueError("RBA F1 has no AONIA observations")

    def latest(key: str) -> dict[str, Any] | None:
        if not series[key]:
            return None
        d, value = series[key][-1]
        return {"as_of": d, "rate": value}

    aonia = latest("aonia")
    assert aonia is not None
    ois = {tenor: latest(f"ois_{tenor}") for tenor in ("1m", "3m", "6m")}
    bills = {tenor: latest(f"bill_{tenor}") for tenor in ("1m", "3m", "6m")}
    basis: dict[str, Any] = {}
    for tenor in ("1m", "3m", "6m"):
        o = ois[tenor]
        b = bills[tenor]
        if not o or not b:
            basis[tenor] = None
        else:
            o_date = datetime.strptime(o["as_of"], "%d-%b-%Y").date()
            b_date = datetime.strptime(b["as_of"], "%d-%b-%Y").date()
            if abs((b_date - o_date).days) > 7:
                basis[tenor] = {
                    "status": "unavailable_cross_vintage",
                    "ois_as_of": o["as_of"],
                    "bank_bill_as_of": b["as_of"],
                    "bank_bill_minus_ois_bps": None,
                }
            else:
                basis[tenor] = {
                    "status": "ok",
                    "as_of": min(o["as_of"], b["as_of"]),
                    "bank_bill_minus_ois_bps": round((b["rate"] - o["rate"]) * 100.0, 2),
                }
    return {
        "benchmark": {"name": "AONIA", **aonia},
        "ois": ois,
        "bank_bills": bills,
        "bank_bill_minus_ois": basis,
    }


def parse_asx_cash_futures_html(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(text)
    out: list[dict[str, Any]] = []
    for table in parser.tables:
        in_ib = False
        for row in table:
            joined = " ".join(row).upper()
            if "IB - 30 DAY INTERBANK CASH RATE" in joined:
                in_ib = True
                continue
            if in_ib and re.match(r"^[A-Z]{1,3} - ", joined) and "30 DAY INTERBANK CASH RATE" not in joined:
                in_ib = False
            if not in_ib or not row:
                continue
            expiry = _parse_expiry(row[0])
            if not expiry:
                continue
            # ASX EOD product rows: Expiry Open High Low Last Sett Sett Chg OI OI Chg Volume.
            price = _num(row[5]) if len(row) > 5 else None
            if price is None or not 90.0 < price < 100.5:
                continue
            oi = _num(row[7]) if len(row) > 7 else None
            volume = _num(row[9]) if len(row) > 9 else None
            out.append(
                _contract_row(
                    expiry=expiry,
                    code=None,
                    price=price,
                    benchmark=benchmark,
                    source="ASX_30D_AONIA",
                    volume=volume,
                    open_interest=oi,
                )
            )
    rows = sorted({row["expiry"]: row for row in out}.values(), key=lambda row: row["expiry"])
    if not rows:
        raise ValueError("ASX EOD report did not expose 30-day cash-rate futures")
    return rows


def _terminal_summary(contracts: list[dict[str, Any]]) -> dict[str, Any] | None:
    liquid = [
        row for row in contracts
        if row.get("implied_rate") is not None and (row.get("volume") or 0) > 0
    ]
    usable = liquid or contracts
    if not usable:
        return None
    terminal = usable[-1]
    return {
        "expiry": terminal["expiry"],
        "implied_rate": terminal["implied_rate"],
        "change_from_overnight_bps": terminal["change_from_overnight_bps"],
    }


def collect_policy_paths(
    *,
    today: date,
    fetch_bytes: FetchBytes,
) -> dict[str, Any]:
    countries: dict[str, Any] = {}
    sources: dict[str, Any] = {}

    # Canada
    try:
        corra_json = fetch_bytes(BOC_CORRA_JSON).decode("utf-8", errors="replace")
        corra = parse_boc_corra_json(corra_json)
        mx_html = fetch_bytes(MX_EXPECTATIONS_URL).decode("utf-8", errors="replace")
        mx = parse_mx_expectations_html(mx_html, benchmark=float(corra["rate"]))
        preferred = mx["1m"] if mx["1m"] else mx["3m"]
        countries["CA"] = {
            "status": "ok",
            "benchmark": {"name": "CORRA", **corra},
            "contracts_1m": mx["1m"],
            "contracts_3m": mx["3m"],
            "terminal": _terminal_summary(preferred or mx["3m"]),
            "method": "100 minus public MX CORRA futures price; research/reference path, not meeting probabilities",
        }
        sources["CA_policy"] = {
            "status": "ok",
            "benchmark_url": BOC_CORRA_PAGE,
            "path_url": MX_EXPECTATIONS_URL,
        }
    except Exception as exc:
        countries["CA"] = {"status": "unavailable", "error": str(exc)}
        sources["CA_policy"] = {"status": "unavailable", "error": str(exc), "benchmark_url": BOC_CORRA_PAGE, "path_url": MX_EXPECTATIONS_URL}

    # United States
    try:
        sofr_payload = fetch_bytes(NYFED_SOFR_URL).decode("utf-8", errors="replace")
        sofr = parse_nyfed_sofr_json(sofr_payload)
        us_curve_source = CME_SOFR_BULLETIN_URL
        us_curve_method = "CME Daily Bulletin SR1 settlements"
        try:
            bulletin = fetch_bytes(
                CME_SOFR_BULLETIN_URL,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
                referer="https://www.cmegroup.com/market-data/daily-bulletin.html",
            )
            contracts = parse_cme_sofr_bulletin_pdf(bulletin, benchmark=float(sofr["rate"]))
        except Exception:
            fallback = fetch_bytes(
                ESIGNAL_SOFR_CHAIN_URL,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
            ).decode("utf-8", errors="replace")
            contracts = parse_esignal_sofr_html(fallback, benchmark=float(sofr["rate"]))
            us_curve_source = ESIGNAL_SOFR_CHAIN_URL
            us_curve_method = "delayed ICE One-Month SOFR futures chain via eSignal fallback because CME blocks hosted runners"
        countries["US"] = {
            "status": "ok",
            "benchmark": {"name": "SOFR", **sofr},
            "contracts_1m": contracts,
            "terminal": _terminal_summary(contracts),
            "method": f"100 minus {us_curve_method}; monthly average SOFR, not FOMC target probabilities",
        }
        sources["US_policy"] = {
            "status": "ok",
            "benchmark_url": NYFED_SOFR_PAGE,
            "path_url": us_curve_source,
        }
    except Exception as exc:
        countries["US"] = {"status": "unavailable", "error": str(exc)}
        sources["US_policy"] = {"status": "unavailable", "error": str(exc), "benchmark_url": NYFED_SOFR_PAGE, "path_url": CME_SOFR_URL}

    # Australia
    try:
        f1_text = fetch_bytes(RBA_F1_URL).decode("utf-8-sig", errors="replace")
        f1 = parse_rba_f1_csv(f1_text)
        benchmark = float(f1["benchmark"]["rate"])
        asx_rows: list[dict[str, Any]] = []
        asx_url = None
        last_error: Exception | None = None
        for offset in range(0, 8):
            d = today - timedelta(days=offset)
            url = ASX_EOD_TEMPLATE.format(yymmdd=d.strftime("%y%m%d"))
            try:
                body = fetch_bytes(
                    url,
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    ),
                    referer="https://www.asx.com.au/",
                ).decode("utf-8", errors="replace")
                asx_rows = parse_asx_cash_futures_html(body, benchmark=benchmark)
                asx_url = url
                break
            except Exception as exc:
                last_error = exc
        if not asx_rows:
            raise ValueError(f"no usable ASX 30-day cash futures report in 8-day lookback: {last_error}")
        countries["AU"] = {
            "status": "ok",
            "benchmark": f1["benchmark"],
            "ois": f1["ois"],
            "bank_bills": f1["bank_bills"],
            "bank_bill_minus_ois": f1["bank_bill_minus_ois"],
            "contracts_1m": asx_rows,
            "terminal": _terminal_summary(asx_rows),
            "method": (
                "RBA F1 official AONIA/OIS/BAB context plus 100 minus ASX 30-day "
                "interbank cash-rate futures settlement; bank-bill-minus-OIS is a credit/basis proxy, not exact FRA-OIS"
            ),
        }
        sources["AU_policy"] = {
            "status": "ok",
            "benchmark_url": RBA_F1_PAGE,
            "path_url": asx_url,
            "settlement_history_url": ASX_IR_HISTORY,
        }
    except Exception as exc:
        countries["AU"] = {"status": "unavailable", "error": str(exc)}
        sources["AU_policy"] = {"status": "unavailable", "error": str(exc), "benchmark_url": RBA_F1_PAGE, "path_url": ASX_IR_HISTORY}

    statuses = [row.get("status") for row in countries.values()]
    status = "ok" if statuses and all(x == "ok" for x in statuses) else "partial" if any(x == "ok" for x in statuses) else "unavailable"
    return {
        "status": status,
        "countries": countries,
        "sources": sources,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": "policy expectations context before sovereign-curve/RV trade construction",
        },
    }


def validate_policy_paths(payload: dict[str, Any]) -> None:
    if payload.get("status") not in {"ok", "partial", "unavailable"}:
        raise ValueError("policy_paths invalid status")
    if payload.get("method", {}).get("model_calls") != 0:
        raise ValueError("policy_paths must use zero model calls")
    if payload.get("method", {}).get("credentials_required") not in ([], None):
        raise ValueError("policy_paths must not require credentials")
    countries = payload.get("countries") or {}
    if set(countries) != {"US", "CA", "AU"}:
        raise ValueError("policy_paths must contain US, CA and AU")
    for country, block in countries.items():
        if block.get("status") == "unavailable":
            if not block.get("error"):
                raise ValueError(f"{country} unavailable policy path missing error")
            continue
        benchmark = block.get("benchmark") or {}
        rate = _num(benchmark.get("rate"))
        if rate is None or not -2.0 < rate < 25.0:
            raise ValueError(f"{country} implausible overnight benchmark {rate}")
        if country in {"US", "CA", "AU"}:
            contracts = block.get("contracts_1m") or block.get("contracts_3m") or []
            if not contracts:
                raise ValueError(f"{country} available policy path has no futures contracts")
            for row in contracts:
                implied = _num(row.get("implied_rate"))
                if implied is None or not -2.0 < implied < 25.0:
                    raise ValueError(f"{country} implausible implied policy rate {implied}")
