"""Observation bundle assembly for the Canada Prima-pressure proxy."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from scripts.policy_path_data import parse_boc_corra_json
from scripts.prima_pressure.contract import (
    BOC_CORRA_JSON,
    BOC_CORRA_PAGE,
    DISCLAIMER,
    LAST_MPR_ANCHOR,
    SCHEMA_VERSION,
    iso_date,
    sector_ppi_unavailable,
)
from scripts.canadian_cpi_release.sources.nrcan import collect_nrcan, collect_nrcan_weekly
from scripts.prima_pressure.bcpi import collect_bcpi_weekly
from scripts.prima_pressure.import_prices import collect_import_prices
from scripts.prima_pressure.curve import build_curve, build_refinery_margin, contract_history
from scripts.prima_pressure.mpr import build_mpr_comparison
from scripts.prima_pressure.producer import build_cpi_breadth_inputs, build_producer_prices

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

YAHOO_CHART_PATH = "/v8/finance/chart/"
_YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_RETRIABLE_HTTP_CODES = frozenset({429, 403, 408, 500, 502, 503, 504})
_URLLIB_BACKOFF_S = (0.4, 0.8, 1.6)

Opener = Callable[..., bytes]

_yahoo_chart_cache: dict[str, bytes] = {}


def _is_yahoo_chart_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host.endswith("finance.yahoo.com") and YAHOO_CHART_PATH in parsed.path


def _swap_yahoo_host(url: str, host: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(netloc=host))


def _curl_cffi_get(url: str) -> tuple[int, bytes] | None:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.8",
    }
    last: tuple[int, bytes] | None = None
    for impersonate in ("chrome", "safari18_0"):
        try:
            resp = cffi_requests.get(url, impersonate=impersonate, timeout=30, headers=headers)
        except Exception:
            continue
        code = int(getattr(resp, "status_code", 0) or 0)
        content = bytes(resp.content or b"")
        if code in (200, 404) and content:
            return code, content
        if code in _RETRIABLE_HTTP_CODES:
            last = (code, content)
    return last


def _http_code_from_error(exc: BaseException) -> int | None:
    if isinstance(exc, HTTPError):
        return exc.code
    text = str(exc).lower()
    for code in _RETRIABLE_HTTP_CODES:
        if str(code) in text:
            return code
    if "404" in text:
        return 404
    return None


def _is_retriable_http_error(exc: BaseException) -> bool:
    code = _http_code_from_error(exc)
    if code is not None:
        return code in _RETRIABLE_HTTP_CODES
    if isinstance(exc, (TimeoutError, URLError)):
        return True
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text


def _urllib_get_once(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,*/*"}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return response.read()


def _fetch_yahoo_chart(url: str) -> bytes:
    if url in _yahoo_chart_cache:
        return _yahoo_chart_cache[url]

    hosts = list(_YAHOO_HOSTS)
    parsed = urlparse(url)
    if parsed.hostname in hosts:
        hosts.remove(parsed.hostname)
        hosts.insert(0, parsed.hostname)

    last_exc: Exception | None = None
    for attempt in range(3):
        host = hosts[attempt % len(hosts)]
        fetch_url = _swap_yahoo_host(url, host)
        try:
            body = _urllib_get_once(fetch_url)
            _yahoo_chart_cache[url] = body
            return body
        except HTTPError as exc:
            if exc.code == 404:
                body = exc.read()
                _yahoo_chart_cache[url] = body
                return body
            last_exc = exc
            if not _is_retriable_http_error(exc):
                raise
            if attempt < 2:
                time.sleep(_URLLIB_BACKOFF_S[attempt])
        except Exception as exc:
            last_exc = exc
            if not _is_retriable_http_error(exc):
                raise
            if attempt < 2:
                time.sleep(_URLLIB_BACKOFF_S[attempt])

    for host in hosts:
        fetch_url = _swap_yahoo_host(url, host)
        cffi_result = _curl_cffi_get(fetch_url)
        if cffi_result is None:
            continue
        code, body = cffi_result
        if code == 200 and body:
            _yahoo_chart_cache[url] = body
            return body
        if code == 404 and body:
            _yahoo_chart_cache[url] = body
            return body
        if code in _RETRIABLE_HTTP_CODES:
            last_exc = HTTPError(fetch_url, code, "retriable", None, None)

    raise last_exc or RuntimeError("yahoo chart fetch failed")


def _urllib_opener(url: str, data: bytes | None = None, **_: Any) -> bytes:
    if data is None and _is_yahoo_chart_url(url):
        return _fetch_yahoo_chart(url)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            with urlopen(request, timeout=20) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_exc = exc
    raise last_exc or RuntimeError("request failed")


def _unavailable_curve(curve_id: str, as_of: date, *, reason: str) -> dict[str, Any]:
    return {
        "curve_id": curve_id,
        "as_of": iso_date(as_of),
        "status": "unavailable",
        "continuous_front_not_used": True,
        "points": [],
        "missing_maturities": [0, 3, 6, 12, 24],
        "reason": reason,
    }


def _nrcan_through_period(as_of: date) -> str:
    y, m = as_of.year, as_of.month
    m -= 1
    if m < 1:
        m = 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def attach_transmission_daily_bars(bundle: dict[str, Any], as_of: date, opener: Opener) -> None:
    """Attach front-contract daily bars for transmission staging (additive bundle field)."""
    bars: dict[str, list[dict[str, Any]]] = {}
    brent = (bundle.get("oil_curves") or {}).get("brent_last_day") or {}
    front = next((p for p in brent.get("points") or [] if p.get("maturity_months") == 0), None)
    if front and front.get("contract_month"):
        y, m = int(front["contract_month"][:4]), int(front["contract_month"][5:7])
        hist, _ = contract_history("BZ", y, m, as_of, opener)
        bars["brent_front"] = [{"date": iso_date(d), "close": c, "source_id": front.get("symbol")} for d, c in hist]
    rm = bundle.get("refinery_margin") or {}
    for key, root in (("rbob", "RB"), ("heating_oil", "HO")):
        leg = rm.get(key)
        if not leg or not leg.get("symbol"):
            continue
        try:
            from scripts.prima_pressure.expiry import parse_listed_symbol

            _root, y, m = parse_listed_symbol(str(leg["symbol"]))
        except Exception:
            continue
        hist, _ = contract_history(root, y, m, as_of, opener)
        bars[key] = [{"date": iso_date(d), "close": c, "source_id": leg.get("symbol")} for d, c in hist]
    if bars:
        bundle["transmission_daily_bars"] = bars


def _build_nrcan_fuel(as_of: date, opener: Opener) -> dict[str, Any]:
    through = _nrcan_through_period(as_of)
    out: dict[str, Any] = {
        "status": "unavailable",
        "through_period": through,
        "gasoline_cpl": None,
        "furnace_oil_cpl": None,
    }
    try:
        observations, _pages, notes = collect_nrcan(
            opener=opener,
            sleeper=None,
            retrieved_at=iso_date(as_of),
            through_period=through,
            require_full_history=False,
        )
        by_id: dict[str, dict[str, float]] = {}
        for obs in observations:
            by_id.setdefault(obs.canonical_id, {})[obs.period] = obs.value
        gas = by_id.get("nrcan_gasoline") or {}
        fo = by_id.get("nrcan_furnace_oil") or {}
        if through in gas:
            out["gasoline_cpl"] = gas[through]
        if through in fo:
            out["furnace_oil_cpl"] = fo[through]
        out["gasoline_by_month"] = gas
        out["furnace_oil_by_month"] = fo
        out["notes"] = notes
        out["status"] = "ok" if through in gas else "partial"
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
    return out


def build_demand_inputs(as_of: date, opener: Opener) -> dict[str, Any]:
    neutral = LAST_MPR_ANCHOR["neutral_rate"]
    out: dict[str, Any] = {
        "as_of": iso_date(as_of),
        "neutral_midpoint": neutral,
        "corra": {
            "status": "unavailable",
            "series_id": "AVG.INTWO",
            "source_url": BOC_CORRA_PAGE,
            "download_url": BOC_CORRA_JSON,
        },
    }
    try:
        raw = opener(BOC_CORRA_JSON)
        parsed = parse_boc_corra_json(raw.decode("utf-8"))
        out["corra"].update(
            status="ok",
            rate=parsed.get("rate"),
            as_of=parsed.get("as_of"),
            history=parsed.get("history"),
        )
    except Exception as exc:
        out["corra"]["error"] = str(exc)
    return out


def build_observation_bundle(
    as_of: date,
    *,
    opener: Opener | None = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    effective_opener: Opener | None = opener
    if effective_opener is None and allow_network:
        effective_opener = _urllib_opener

    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "as_of": iso_date(as_of),
        "disclaimer": DISCLAIMER,
    }

    if effective_opener is None:
        oil_curves = {
            "brent_last_day": _unavailable_curve(
                "brent_last_day", as_of, reason="network_disabled"
            ),
            "wti": _unavailable_curve("wti", as_of, reason="network_disabled"),
        }
        bundle["oil_curves"] = oil_curves
        bundle["refinery_margin"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "reason": "network_disabled",
        }
        bundle["producer_prices"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "sector_ppi": sector_ppi_unavailable("network_disabled"),
            "series": [],
        }
        bundle["cpi_breadth_inputs"] = {
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "series": [],
        }
        bundle["demand_inputs"] = {
            "as_of": iso_date(as_of),
            "neutral_midpoint": LAST_MPR_ANCHOR["neutral_rate"],
            "corra": {
                "status": "unavailable",
                "series_id": "AVG.INTWO",
                "source_url": BOC_CORRA_PAGE,
                "download_url": BOC_CORRA_JSON,
                "reason": "network_disabled",
            },
        }
        bundle["mpr_comparison"] = build_mpr_comparison(oil_curves, as_of=as_of)
        bundle["nrcan_fuel"] = {
            "status": "unavailable",
            "reason": "network_disabled",
        }
        for key in ("nrcan_weekly", "bcpi_weekly", "import_prices"):
            bundle[key] = {"status": "unavailable", "reason": "network_disabled"}
        return bundle

    oil_curves = {
        "brent_last_day": build_curve("brent_last_day", as_of, effective_opener),
        "wti": build_curve("wti", as_of, effective_opener),
    }
    bundle["oil_curves"] = oil_curves
    bundle["refinery_margin"] = build_refinery_margin(as_of, oil_curves["wti"], effective_opener)
    bundle["producer_prices"] = build_producer_prices(as_of, effective_opener)
    bundle["cpi_breadth_inputs"] = build_cpi_breadth_inputs(as_of, effective_opener)
    bundle["demand_inputs"] = build_demand_inputs(as_of, effective_opener)
    bundle["mpr_comparison"] = build_mpr_comparison(oil_curves, as_of=as_of)
    bundle["nrcan_fuel"] = _build_nrcan_fuel(as_of, effective_opener)
    attach_transmission_daily_bars(bundle, as_of, effective_opener)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for key, collector in (
        ("nrcan_weekly", lambda: collect_nrcan_weekly(as_of=as_of, opener=effective_opener, retrieved_at=retrieved_at)),
        ("bcpi_weekly", lambda: collect_bcpi_weekly(as_of=as_of, opener=effective_opener, retrieved_at=retrieved_at)),
        ("import_prices", lambda: collect_import_prices(as_of=as_of, opener=effective_opener, retrieved_at=retrieved_at)),
    ):
        try:
            bundle[key] = collector()
        except Exception as exc:
            bundle[key] = {
                "status": "unavailable",
                "reason": f"{type(exc).__name__}: {exc}",
                "retrieved_at": retrieved_at,
            }
    return bundle
