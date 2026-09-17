#!/usr/bin/env python3
"""Production entrypoint for the minimal no-secret Market Watch state feed.

The deterministic Sal analytics module stays unchanged. This entrypoint only
adapts Canadian benchmark yields to the public Bank of Canada selected-bonds
page because the Valet observation route is currently returning 404 in GitHub
Actions. FX remains the no-key ECB reference-rate implementation.
"""
from __future__ import annotations

import sys
from datetime import date
from html.parser import HTMLParser

from scripts import sal_market_data as sal

BOC_SELECTED_BONDS_URL = "https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/"


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_boc_selected_bonds_html(text: str, start: date, end: date) -> dict[str, dict[date, float]]:
    parser = _TableRows()
    parser.feed(text)
    out = {"2Y": {}, "5Y": {}, "10Y": {}, "LONG": {}}
    dates: list[date] = []
    for row in parser.rows:
        parsed_dates = [sal.parse_date(cell) for cell in row[1:]]
        if len(row) >= 3 and sum(d is not None for d in parsed_dates) >= 2:
            dates = [d for d in parsed_dates if d is not None]
            continue
        if not dates or not row:
            continue
        label = row[0].strip().lower()
        tenor = None
        if label == "2 year":
            tenor = "2Y"
        elif label == "5 year":
            tenor = "5Y"
        elif label == "10 year":
            tenor = "10Y"
        elif label == "long-term" and not out["LONG"]:
            tenor = "LONG"
        if tenor is None:
            continue
        values = [sal.to_float(cell) for cell in row[1 : 1 + len(dates)]]
        for d, value in zip(dates, values):
            if start <= d <= end and value is not None:
                out[tenor][d] = value
    if any(not out[t] for t in sal.RATE_TENORS):
        raise sal.SalError("Bank of Canada selected-bonds page missing required benchmark tenors")
    return out


def fetch_ca_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    html = sal.fetch_bytes(BOC_SELECTED_BONDS_URL).decode("utf-8", errors="replace")
    return parse_boc_selected_bonds_html(html, start, end)


_original_build_snapshot = sal.build_snapshot


def build_snapshot(*, today: date | None = None) -> dict:
    snapshot = _original_build_snapshot(today=today)
    ca = snapshot["rates"]["CA"]
    ca["history_limited"] = True
    ca["history_note"] = "Bank of Canada public selected-bonds page currently supplies the recent displayed observations only; distribution statistics are suppressed for Canadian rates and CA-linked spreads."
    for metrics in ca["tenors"].values():
        for key in ("pctile_1y", "pctile_5y", "z_1y", "z_5y"):
            metrics[key] = None
    for metrics in ca["curves"].values():
        for key in ("pctile_1y", "pctile_5y", "z_1y", "z_5y"):
            metrics[key] = None
    for key, metrics in snapshot["rate_rv"].items():
        if key.startswith("CA-"):
            for field in ("pctile_1y", "pctile_5y", "z_1y", "z_5y"):
                metrics[field] = None
    snapshot["sources"]["CA_rates"] = {
        "name": "Bank of Canada selected benchmark bond yields",
        "url": BOC_SELECTED_BONDS_URL,
        "note": "Recent public table fallback while Valet observations are unavailable from GitHub Actions; Canadian distribution statistics are intentionally suppressed.",
    }
    snapshot["method"]["ca_rate_history"] = "recent Bank of Canada selected-bonds table; latest/moves only"
    return snapshot


sal.fetch_ca_rates = fetch_ca_rates
sal.build_snapshot = build_snapshot


if __name__ == "__main__":
    try:
        raise SystemExit(sal.main())
    except sal.SalError as exc:
        print(f"MARKET STATE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
