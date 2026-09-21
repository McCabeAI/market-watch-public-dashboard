"""Japan sovereign yields and policy-path sources (isolated P4 / I5 collector).

Official sources only — no vendor substitutes. Parent integrates into market_state.py.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

FetchBytes = Callable[..., bytes]

# --- MOF JGB benchmark par yields (2Y/5Y/10Y/30Y) ---
MOF_JGB_PAGE_EN = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
MOF_JGB_PAGE_JA = "https://www.mof.go.jp/jgbs/reference/interest_rate/"
MOF_JGB_CURRENT_EN = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
)
MOF_JGB_HISTORICAL_EN = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
)
MOF_JGB_CURRENT_JA = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
MOF_JGB_HISTORICAL_JA = (
    "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
)

JGB_TENORS = ("2Y", "5Y", "10Y", "30Y")
JGB_STALE_AFTER_DAYS = 4

# --- BOJ overnight / TONA policy benchmark ---
BOJ_CALL_MONEY_PAGE = "https://www.boj.or.jp/en/statistics/market/short/mutan/index.htm"
BOJ_FM01_PAGE = "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm01_d_1_en.html"
BOJ_TONA_SERIES_CODE = "STRDCLUCON"
BOJ_TONA_API_TEMPLATE = (
    "https://www.stat-search.boj.or.jp/api/v1/getDataCode?"
    "format=csv&lang=en&db=FM01&code={code}&startDate={start}&endDate={end}"
)

# --- JPX / OSE 3-Month TONA futures (JSCC daily settlement CSV) ---
JPX_TONA_PRODUCT_PAGE = (
    "https://www.jpx.co.jp/english/derivatives/products/interest-rate/3m-tona-futures/01.html"
)
JPX_SETTLEMENT_PAGE = (
    "https://www.jpx.co.jp/english/markets/derivatives/settlement-price/index.html"
)
JPX_SETTLEMENT_CSV_TEMPLATE = (
    "https://www.jpx.co.jp/english/markets/derivatives/settlement-price/"
    "tvdivq00000014l6-att/rb_e{yyyymmdd}.csv"
)
JPX_TONA_ISSUE_PREFIX = "FUT_TOA3M_"
JPX_TONA_UNDERLYING = "3-Month TONA"
JPX_TONA_ISSUE_CODE_SUFFIX = "091"
JPX_TONA_EXPECTED_CONTRACTS = 20

_ERA_YEAR_BASE = {
    "R": 2018,  # Reiwa 1 = 2019; R year n -> 2018 + n
    "H": 1988,  # Heisei
    "S": 1925,  # Showa
}


class JapanRatesError(RuntimeError):
    """Required Japan rates/policy source missing or unparsable."""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s.lower() in {"-", "—", "na", "n/a", "null", ".."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_mof_date(cell: str) -> date | None:
    s = str(cell or "").strip()
    if not s:
        return None
    if re.fullmatch(r"20\d{2}/\d{1,2}/\d{1,2}", s):
        return datetime.strptime(s, "%Y/%m/%d").date()
    m = re.fullmatch(r"([RHS])(\d+)\.(\d+)\.(\d+)", s)
    if m:
        base = _ERA_YEAR_BASE.get(m.group(1))
        if base is None:
            return None
        year = base + int(m.group(2))
        return date(year, int(m.group(3)), int(m.group(4)))
    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


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


def _contract_month_to_expiry(contract_month: str) -> str | None:
    s = re.sub(r"\D", "", str(contract_month or ""))
    if len(s) != 6:
        return None
    return f"{s[:4]}-{s[4:6]}"


def parse_mof_jgb(text: str) -> dict[str, dict[date, float]]:
    """Parse MOF English or Japanese JGB benchmark yield CSV (jgbcme/jgbcm family)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header_idx = None
    header: list[str] = []
    for i, row in enumerate(rows):
        if not row:
            continue
        joined = ",".join(row).lower()
        if "date" in joined or "基準日" in joined or joined.startswith("date,"):
            header = [c.strip() for c in row]
            header_idx = i
            break
    if header_idx is None:
        raise JapanRatesError("MOF JGB CSV missing Date header row")

    col_map: dict[str, int] = {}
    for idx, label in enumerate(header):
        norm = label.strip().upper().replace(" ", "")
        if norm in {"1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "15Y", "20Y", "25Y", "30Y", "40Y"}:
            col_map[norm] = idx
        elif label.strip() in {"1年", "2年", "3年", "4年", "5年", "6年", "7年", "8年", "9年", "10年", "15年", "20年", "25年", "30年", "40年"}:
            col_map[f"{label.strip().replace('年', '')}Y"] = idx

    missing = [t for t in JGB_TENORS if t not in col_map]
    if missing:
        raise JapanRatesError(f"MOF JGB CSV missing tenor columns: {missing}")

    out: dict[str, dict[date, float]] = {t: {} for t in JGB_TENORS}
    for row in rows[header_idx + 1 :]:
        if not row:
            continue
        d = _parse_mof_date(row[0])
        if d is None:
            continue
        for tenor in JGB_TENORS:
            idx = col_map[tenor]
            if idx < len(row):
                v = _num(row[idx])
                if v is not None:
                    out[tenor][d] = v
    if any(not out[t] for t in JGB_TENORS):
        raise JapanRatesError("MOF JGB CSV contains no observations for required tenors")
    return out


def _filter_rates(
    series: dict[str, dict[date, float]],
    start: date,
    end: date,
) -> dict[str, dict[date, float]]:
    return {
        tenor: {d: v for d, v in hist.items() if start <= d <= end}
        for tenor, hist in series.items()
    }


def fetch_jp_jgb_rates(
    start: date,
    end: date,
    fetch_bytes: FetchBytes | None = None,
) -> dict[str, dict[date, float]]:
    """Fetch MOF official JGB 2Y/5Y/10Y/30Y history for [start, end]."""
    if fetch_bytes is None:
        raise JapanRatesError("fetch_jp_jgb_rates requires fetch_bytes")
    raw = fetch_bytes(MOF_JGB_HISTORICAL_EN).decode("utf-8", errors="replace")
    parsed = parse_mof_jgb(raw)
    out = _filter_rates(parsed, start, end)
    missing = [t for t in JGB_TENORS if not out[t]]
    if missing:
        raise JapanRatesError(f"MOF JGB history missing required tenors after filter: {missing}")
    return out


def parse_boj_tona_api_csv(text: str) -> dict[date, float]:
    """Parse BOJ stat-search getDataCode CSV for STRDCLUCON (daily call rate)."""
    out: dict[date, float] = {}
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row or row[0] != "STRDCLUCON":
            continue
        if len(row) < 8:
            continue
        obs = str(row[6]).strip()
        val = _num(row[7])
        if not obs or val is None:
            continue
        if len(obs) == 8 and obs.isdigit():
            d = datetime.strptime(obs, "%Y%m%d").date()
        else:
            d = _parse_mof_date(obs.replace("-", "/"))
        if d is not None:
            out[d] = val
    if not out:
        raise JapanRatesError("BOJ TONA/call-rate API CSV contained no STRDCLUCON observations")
    return out


def _boj_api_month(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}"


def fetch_tona_history(
    start: date,
    end: date,
    fetch_bytes: FetchBytes | None = None,
) -> dict[date, float]:
    """Daily uncollateralized overnight call-rate average (BOJ FM01 STRDCLUCON)."""
    if fetch_bytes is None:
        raise JapanRatesError("fetch_tona_history requires fetch_bytes")
    url = BOJ_TONA_API_TEMPLATE.format(
        code=BOJ_TONA_SERIES_CODE,
        start=_boj_api_month(start),
        end=_boj_api_month(end),
    )
    text = fetch_bytes(url).decode("utf-8", errors="replace")
    if '"STATUS":400' in text[:200] or text.startswith("{"):
        raise JapanRatesError(f"BOJ TONA API error: {text[:300]}")
    parsed = parse_boj_tona_api_csv(text)
    return {d: v for d, v in parsed.items() if start <= d <= end}


def _latest_benchmark(history: dict[date, float]) -> dict[str, Any]:
    d = max(history)
    return {"rate": history[d], "as_of": d.isoformat(), "name": "TONA", "series_code": BOJ_TONA_SERIES_CODE}


def parse_jpx_settlement_page_html(text: str) -> str | None:
    """Extract the English daily settlement CSV URL (rb_eYYYYMMDD.csv) from the index page."""
    match = re.search(
        r"(/english/markets/derivatives/settlement-price/[^\"']+/rb_e\d{8}\.csv)",
        text,
    )
    if match:
        return "https://www.jpx.co.jp" + match.group(1)
    match = re.search(r"rb_e(\d{8})\.csv", text)
    if match:
        yyyymmdd = match.group(1)
        return JPX_SETTLEMENT_CSV_TEMPLATE.format(yyyymmdd=yyyymmdd)
    return None


def parse_jpx_ose_tona_settlement_csv(
    text: str,
    *,
    benchmark: float,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """Parse JPX rb_e*.csv rows for OSE 3-Month TONA futures (FUT_TOA3M_*)."""
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("Issue Code,") or ",Issue Code," in line),
        None,
    )
    if header_idx is None:
        raise JapanRatesError("JPX settlement CSV missing Issue Code header")
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])), skipinitialspace=True)
    contracts: list[dict[str, Any]] = []
    for row in reader:
        issue_name = (row.get("Issue Name") or "").strip()
        underlying = (row.get("Underlying Name") or "").strip()
        issue_code = (row.get("Issue Code") or "").strip()
        if not issue_name.startswith(JPX_TONA_ISSUE_PREFIX):
            continue
        if underlying.lower() != JPX_TONA_UNDERLYING.lower():
            raise JapanRatesError(f"unexpected TONA underlying label: {underlying!r}")
        if not issue_code.endswith(JPX_TONA_ISSUE_CODE_SUFFIX):
            raise JapanRatesError(f"unexpected TONA issue code suffix: {issue_code!r}")
        expiry = _contract_month_to_expiry(row.get("Contract Month") or "")
        if expiry is None:
            raise JapanRatesError(f"invalid TONA contract month: {row.get('Contract Month')!r}")
        price = _num(row.get("Settlement Price"))
        if price is None:
            continue
        code_tail = issue_name.split("_", 2)[-1] if "_" in issue_name else issue_name
        contracts.append(
            _contract_row(
                expiry=expiry,
                code=code_tail,
                price=price,
                benchmark=benchmark,
                source="JPX_OSE_TOA3M_SETTLEMENT",
            )
        )
    if not contracts:
        raise JapanRatesError("JPX settlement CSV contained no OSE 3M TONA futures")
    contracts.sort(key=lambda r: r["expiry"])
    return contracts


def _fetch_jpx_tona_settlement_csv(
    today: date,
    fetch_bytes: FetchBytes,
) -> tuple[bytes, str]:
    def _get(url: str) -> bytes:
        return fetch_bytes(url)

    page = _get(JPX_SETTLEMENT_PAGE).decode("utf-8", errors="replace")
    url = parse_jpx_settlement_page_html(page)
    if url:
        return _get(url), url
    for offset in range(0, 12):
        candidate = today - timedelta(days=offset)
        trial = JPX_SETTLEMENT_CSV_TEMPLATE.format(yyyymmdd=candidate.strftime("%Y%m%d"))
        try:
            payload = _get(trial)
        except Exception:
            continue
        if payload[:1] == b"{" or b"Issue Code" not in payload[:4000]:
            continue
        return payload, trial
    raise JapanRatesError("JPX OSE settlement CSV not found from index or recent walkback")


def _jgb_freshness(
    rates: dict[str, dict[date, float]],
    today: date,
) -> dict[str, Any]:
    latest: date | None = None
    for tenor in JGB_TENORS:
        if rates[tenor]:
            d = max(rates[tenor])
            latest = d if latest is None else max(latest, d)
    if latest is None:
        return {"status": "unavailable", "error": "no JGB observations"}
    age = (today - latest).days
    status = "ok" if age <= JGB_STALE_AFTER_DAYS else "stale"
    return {"status": status, "as_of": latest.isoformat(), "age_days": age}


def collect_jp_official_curve(
    today: date,
    fetch_bytes: FetchBytes,
) -> dict[str, Any]:
    """MOF benchmark par yields only (no BOJ/MOF Svensson term structure in scope)."""
    try:
        raw = fetch_bytes(MOF_JGB_CURRENT_EN).decode("utf-8", errors="replace")
        parsed = parse_mof_jgb(raw)
        as_of = max(max(parsed[t]) for t in JGB_TENORS)
        par_yields = {
            tenor: {
                "value": round(parsed[tenor][as_of], 6),
                "as_of": as_of.isoformat(),
                "maturity_years": float(tenor[:-1]),
                "source": "MOF_JGB_BENCHMARK",
            }
            for tenor in JGB_TENORS
        }
        return {
            "status": "ok",
            "kind": "benchmark_par_yields_only",
            "as_of": as_of.isoformat(),
            "par_yields": par_yields,
            "source_url": MOF_JGB_CURRENT_EN,
            "source_page": MOF_JGB_PAGE_EN,
            "note": "No richer official zero/Svensson JP curve pinned; MOF publishes daily par yields only.",
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "source_page": MOF_JGB_PAGE_EN,
        }


def collect_jp_policy_path(
    today: date,
    fetch_bytes: FetchBytes,
) -> dict[str, Any]:
    """Japan policy path block: overnight benchmark + OSE 3M TONA futures strip."""
    sources: dict[str, Any] = {
        "benchmark_series": BOJ_TONA_SERIES_CODE,
        "benchmark_url": BOJ_FM01_PAGE,
        "benchmark_api_template": BOJ_TONA_API_TEMPLATE,
        "futures_product_page": JPX_TONA_PRODUCT_PAGE,
        "futures_settlement_page": JPX_SETTLEMENT_PAGE,
    }
    try:
        window_start = today - timedelta(days=120)
        tona_hist = fetch_tona_history(window_start, today, fetch_bytes=fetch_bytes)
        benchmark = _latest_benchmark(tona_hist)
        benchmark.update(
            {
                "label": "TONA",
                "underlying_note": (
                    "Policy block uses BOJ FM01 STRDCLUCON (uncollateralized overnight call-rate "
                    "daily average). OSE 3M TONA futures settle on 3-month compounded confirmed "
                    "TONA (Act/365, 100 minus rate) per JPX contract specs — not the raw overnight "
                    "print."
                ),
                "source": "BOJ_STAT_SEARCH_FM01",
                "source_url": BOJ_FM01_PAGE,
                "call_money_page": BOJ_CALL_MONEY_PAGE,
            }
        )
        settlement_bytes, settlement_url = _fetch_jpx_tona_settlement_csv(today, fetch_bytes)
        contracts_3m = parse_jpx_ose_tona_settlement_csv(
            settlement_bytes.decode("utf-8", errors="replace"),
            benchmark=float(benchmark["rate"]),
        )
        tradable_status = "ok"
        tradable_error: str | None = None
        if len(contracts_3m) != JPX_TONA_EXPECTED_CONTRACTS:
            tradable_status = "unavailable"
            tradable_error = (
                f"expected {JPX_TONA_EXPECTED_CONTRACTS} TOA3M listings, got {len(contracts_3m)}"
            )
        sources["futures_settlement_url"] = settlement_url
        sources["status"] = "ok"
        terminal = None
        if contracts_3m:
            last = contracts_3m[-1]
            terminal = {
                "expiry": last["expiry"],
                "implied_rate": last["implied_rate"],
                "price": last["price"],
            }
        return {
            "status": "ok",
            "benchmark": benchmark,
            "contracts_3m": contracts_3m,
            "terminal": terminal,
            "tradable_curve": {
                "curve_id": "TONA",
                "status": tradable_status,
                "error": tradable_error,
                "product_code": "TOA3M",
                "contract_period_months": 3,
                "instrument": "OSE 3-Month TONA Futures",
                "mark_convention": "implied_rate = 100 - settlement price",
                "spec_url": JPX_TONA_PRODUCT_PAGE,
                "contracts": contracts_3m if tradable_status == "ok" else [],
            },
            "method": (
                "BOJ FM01 overnight call average plus 100 minus JPX/JSCC OSE 3M TONA "
                "daily settlement prices; research/reference, not meeting probabilities"
            ),
            "sources": sources,
        }
    except Exception as exc:
        sources["status"] = "unavailable"
        sources["error"] = str(exc)
        return {
            "status": "unavailable",
            "error": str(exc),
            "sources": sources,
        }


def validate_jp_rates_bundle(payload: Mapping[str, Any]) -> None:
    """Validate isolated JP rates/policy bundle before parent wiring."""
    if payload.get("country") != "JP":
        raise ValueError("jp rates bundle must set country=JP")
    rates = payload.get("rates")
    if not isinstance(rates, Mapping):
        raise ValueError("jp rates bundle missing rates map")
    for tenor in JGB_TENORS:
        series = rates.get(tenor)
        if not isinstance(series, Mapping) or not series:
            raise ValueError(f"jp rates missing {tenor}")
    freshness = payload.get("freshness") or {}
    if freshness.get("status") not in {"ok", "stale", "unavailable"}:
        raise ValueError("jp rates freshness invalid")

    policy = payload.get("policy") or {}
    if policy.get("status") == "unavailable":
        if not policy.get("error"):
            raise ValueError("jp policy unavailable without error")
        return
    if policy.get("status") != "ok":
        raise ValueError("jp policy invalid status")
    benchmark = policy.get("benchmark") or {}
    rate = _num(benchmark.get("rate"))
    if rate is None or not -2.0 < rate < 25.0:
        raise ValueError(f"jp policy implausible overnight rate {rate}")
    contracts = policy.get("contracts_3m") or []
    if not contracts:
        raise ValueError("jp policy missing contracts_3m")
    for row in contracts:
        implied = _num(row.get("implied_rate"))
        if implied is None or not -2.0 < implied < 25.0:
            raise ValueError(f"jp policy implausible implied rate {implied}")

    tradable = policy.get("tradable_curve") or {}
    if tradable.get("curve_id") != "TONA":
        raise ValueError("jp tradable curve_id must be TONA")
    if tradable.get("status") == "ok":
        t_rows = tradable.get("contracts") or []
        if len(t_rows) < 4:
            raise ValueError("jp tradable TONA strip too short")

    official = payload.get("official_curve") or {}
    if official.get("status") == "ok":
        par = official.get("par_yields") or {}
        for tenor in JGB_TENORS:
            row = par.get(tenor)
            if not isinstance(row, Mapping) or row.get("value") is None:
                raise ValueError(f"jp official curve missing {tenor}")


def build_jp_rates_bundle(
    *,
    today: date,
    fetch_bytes: FetchBytes,
    start: date | None = None,
) -> dict[str, Any]:
    """Convenience assembler used by tests and optional live smoke."""
    history_start = start or (today - timedelta(days=400))
    rates = fetch_jp_jgb_rates(history_start, today, fetch_bytes=fetch_bytes)
    # Serialize dates to ISO for JSON-friendly bundle
    rates_iso = {
        tenor: {d.isoformat(): v for d, v in series.items()}
        for tenor, series in rates.items()
    }
    policy = collect_jp_policy_path(today, fetch_bytes)
    official = collect_jp_official_curve(today, fetch_bytes)
    freshness = _jgb_freshness(rates, today)
    bundle = {
        "country": "JP",
        "rates": rates_iso,
        "freshness": freshness,
        "policy": policy,
        "official_curve": official,
        "sources": {
            "jgb": {
                "current_en": MOF_JGB_CURRENT_EN,
                "historical_en": MOF_JGB_HISTORICAL_EN,
                "page_en": MOF_JGB_PAGE_EN,
            },
            "overnight": {
                "series_code": BOJ_TONA_SERIES_CODE,
                "api_template": BOJ_TONA_API_TEMPLATE,
                "page": BOJ_FM01_PAGE,
            },
            "futures": {
                "product_page": JPX_TONA_PRODUCT_PAGE,
                "settlement_page": JPX_SETTLEMENT_PAGE,
            },
        },
    }
    validate_jp_rates_bundle(bundle)
    return bundle
