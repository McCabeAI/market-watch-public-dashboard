#!/usr/bin/env python3
"""Production entrypoint for Sal V1.

Keeps source-specific retrieval corrections isolated from the deterministic
analytics module. No model calls.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Mapping, Sequence

from scripts import sal_market_data as sal

BOC_SERIES = {"V39051": "2Y", "V39053": "5Y", "V39055": "10Y", "V39056": "LONG"}
BOC_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
TWELVE_DATA_DOCS = "https://twelvedata.com/docs/advanced"


def fetch_ca_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    """Fetch each BoC benchmark series explicitly."""
    qs = urllib.parse.urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
    out = {tenor: {} for tenor in BOC_SERIES.values()}
    for series_id, tenor in BOC_SERIES.items():
        url = f"{BOC_URL.format(series=series_id)}?{qs}"
        payload = json.loads(sal.fetch_bytes(url).decode("utf-8"))
        for obs in payload.get("observations", []):
            d = sal.parse_date(obs.get("d"))
            if not d:
                continue
            cell = obs.get(series_id)
            value = cell.get("v") if isinstance(cell, dict) else cell
            v = sal.to_float(value)
            if v is not None:
                out[tenor][d] = v
    if any(not out[k] for k in sal.RATE_TENORS):
        raise sal.SalError("BoC single-series calls missing required benchmark tenors")
    return out


def direct_fx_symbols() -> list[str]:
    """Return the 45 G10 instruments in Sal's established market orientation."""
    return [
        f"{base}/{quote}"
        for i, base in enumerate(sal.FX_ORDER)
        for quote in sal.FX_ORDER[i + 1 :]
    ]


def _parse_twelve_series(block: Mapping, symbol: str, start: date) -> dict[date, float]:
    if block.get("status") == "error":
        raise sal.SalError(f"Twelve Data error for {symbol}: {block.get('message', 'unknown error')}")
    values = block.get("values")
    if not isinstance(values, list):
        raise sal.SalError(f"Twelve Data missing time series for {symbol}")
    out: dict[date, float] = {}
    for row in values:
        if not isinstance(row, Mapping):
            continue
        dt = str(row.get("datetime", ""))[:10]
        d = sal.parse_date(dt)
        close = sal.to_float(row.get("close"))
        if d and d >= start and close is not None and close > 0:
            out[d] = close
    if not out:
        raise sal.SalError(f"Twelve Data returned no usable daily closes for {symbol}")
    return out


def parse_twelve_batch(payload: Mapping, symbols: Sequence[str], start: date) -> dict[str, dict[date, float]]:
    """Parse direct-pair Twelve Data batch output into Sal's pair-key format."""
    out: dict[str, dict[date, float]] = {}
    if len(symbols) == 1 and "values" in payload:
        symbol = symbols[0]
        out[symbol.replace("/", "")] = _parse_twelve_series(payload, symbol, start)
        return out
    for symbol in symbols:
        block = payload.get(symbol)
        if not isinstance(block, Mapping):
            raise sal.SalError(f"Twelve Data batch response missing {symbol}")
        out[symbol.replace("/", "")] = _parse_twelve_series(block, symbol, start)
    return out


def fetch_twelve_batch(symbols: Sequence[str], start: date, end: date, api_key: str) -> dict[str, dict[date, float]]:
    params = urllib.parse.urlencode({
        "symbol": ",".join(symbols),
        "interval": "1day",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "UTC",
    })
    req = urllib.request.Request(
        f"{TWELVE_DATA_URL}?{params}",
        headers={
            "User-Agent": sal.USER_AGENT,
            "Accept": "application/json",
            "Authorization": f"apikey {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=sal.DEFAULT_TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise sal.SalError(f"Twelve Data HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise sal.SalError(f"Twelve Data request failed: {exc}") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise sal.SalError("Twelve Data returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise sal.SalError("Twelve Data returned an unexpected response shape")
    return parse_twelve_batch(payload, symbols, start)


def fetch_fx(start: date) -> dict[str, dict[date, float]]:
    """Fetch all 45 G10 crosses as direct Twelve Data instruments.

    No pair is reconstructed from currency legs. Basic-plan-safe defaults use
    batches of eight symbols because API credits replenish each minute. Paid
    plans can raise TWELVE_DATA_BATCH_SIZE to their per-minute allowance.
    """
    api_key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        raise sal.SalError("TWELVE_DATA_API_KEY is required for direct G10 FX data")
    batch_size = int(os.environ.get("TWELVE_DATA_BATCH_SIZE", "8"))
    delay = float(os.environ.get("TWELVE_DATA_BATCH_DELAY_SECONDS", "61"))
    if batch_size < 1 or batch_size > 45:
        raise sal.SalError("TWELVE_DATA_BATCH_SIZE must be between 1 and 45")
    symbols = direct_fx_symbols()
    end = date.today()
    out: dict[str, dict[date, float]] = {}
    batches = [symbols[i : i + batch_size] for i in range(0, len(symbols), batch_size)]
    for idx, batch in enumerate(batches):
        out.update(fetch_twelve_batch(batch, start, end, api_key))
        if idx + 1 < len(batches) and delay > 0:
            time.sleep(delay)
    expected = {s.replace("/", "") for s in symbols}
    if set(out) != expected or any(not series for series in out.values()):
        missing = sorted(expected - set(out))
        raise sal.SalError(f"Twelve Data did not populate all 45 direct G10 pairs; missing={missing}")
    return out


_original_build_snapshot = sal.build_snapshot
_original_render_html = sal.render_html


def build_snapshot(*, today: date | None = None) -> dict:
    snapshot = _original_build_snapshot(today=today)
    snapshot["sources"]["FX"] = {
        "name": "Twelve Data Forex API v2",
        "url": TWELVE_DATA_DOCS,
        "note": "Direct composite FX instruments. Sal does not construct synthetic cross rates.",
    }
    snapshot["method"]["fx_source"] = "twelve_data_direct_composite"
    snapshot["method"]["fx_cross_construction"] = False
    return snapshot


def render_html(snapshot: Mapping) -> str:
    html = _original_render_html(snapshot)
    html = html.replace("FX: ECB daily reference rates", "FX: Twelve Data direct composite pairs")
    html = html.replace(
        "FX values are research reference rates, not executable prices. Crosses are deterministic ratios of same-fixing ECB EUR reference rates.",
        "FX values are direct composite pair bars from Twelve Data for research context, not executable prices. No synthetic crosses are constructed by Sal.",
    )
    return html


sal.fetch_ca_rates = fetch_ca_rates
sal.fetch_fx = fetch_fx
sal.build_snapshot = build_snapshot
sal.render_html = render_html


if __name__ == "__main__":
    try:
        raise SystemExit(sal.main())
    except sal.SalError as exc:
        print(f"SAL ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
