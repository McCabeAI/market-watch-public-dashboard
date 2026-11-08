"""Three-month EURIBOR futures source qualification.

ICE Three-Month Euribor (product code I) and Eurex FEU3 are different
listings. This module never mixes their prices and never treats a delayed
vendor print as an official settlement.

Live acquisition returns rows only when a response is a body-stamped
settlement document for one chosen product. If neither exchange exposes
that document from the runner, acquisition fails and the caller publishes
an unavailable EURIBOR status. No settlement is invented.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

FetchBytes = Callable[..., bytes]

ICE_PRODUCT_CODE = "I"
EUREX_PRODUCT_CODE = "FEU3"
ICE_PRODUCT_URL = "https://www.ice.com/products/37650330/Three-Month-Euribor-Futures"
ICE_REPORTS_URL = "https://www.theice.com/marketdata/reports/176"
EUREX_FEU3_URL = "https://www.eurex.com/api/v1/overallstatistics/FEU3"
EUREX_PAGE = "https://www.eurex.com/ex-en/markets/productSearch"
ESIGNAL_PROBE_URLS = (
    "https://quotes.esignal.com/esignalprod/quote.action?symbol=I",
    "https://quotes.esignal.com/esignalprod/quote.action?symbol=FEU3",
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# CME lists EUS (product 10248) as a €STR single-contract basis spread.
# It is not a EURIBOR futures strip and is not an input here.
EUS_NOT_USED = {
    "product_code": "EUS",
    "cme_product_id": "10248",
    "used": False,
    "reason": (
        "CME EUS is a €STR basis-spread future, not an ICE or Eurex "
        "three-month EURIBOR strip. It is not a mark for this curve."
    ),
}

_PROBES = (
    {
        "venue": "ICE",
        "product_code": ICE_PRODUCT_CODE,
        "role": "authoritative_exchange_candidate",
        "url": ICE_PRODUCT_URL,
    },
    {
        "venue": "ICE",
        "product_code": ICE_PRODUCT_CODE,
        "role": "report_index",
        "url": ICE_REPORTS_URL,
    },
    {
        "venue": "EUREX",
        "product_code": EUREX_PRODUCT_CODE,
        "role": "authoritative_exchange_candidate",
        "url": EUREX_FEU3_URL,
    },
    {
        "venue": "ESIGNAL",
        "product_code": ICE_PRODUCT_CODE,
        "role": "delayed_alternative",
        "url": ESIGNAL_PROBE_URLS[0],
    },
    {
        "venue": "ESIGNAL",
        "product_code": EUREX_PRODUCT_CODE,
        "role": "delayed_alternative",
        "url": ESIGNAL_PROBE_URLS[1],
    },
)


def _invoke(fetch_bytes: FetchBytes, url: str) -> bytes:
    try:
        return fetch_bytes(url, retries=1, user_agent=UA)
    except TypeError:
        return fetch_bytes(url)


def _excerpt(body: bytes) -> str:
    return body[:240].decode("utf-8", errors="replace").replace("\n", " ")


def _body_has_stamped_strip(body: bytes, product_code: str) -> bool:
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("product_code") or "").upper() != product_code.upper():
        return False
    if payload.get("trade_date") in (None, ""):
        return False
    contracts = payload.get("contracts")
    return isinstance(contracts, list) and any(
        isinstance(row, dict) and row.get("price") is not None and row.get("named_month")
        for row in contracts
    )


def qualify_euribor_sources(fetch_bytes: FetchBytes, *, today: date) -> dict[str, Any]:
    """Compare ICE and Eurex paths. Select a canonical source only when a body proves it."""
    compared: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for probe in _PROBES:
        record: dict[str, Any] = {
            "venue": probe["venue"],
            "product_code": probe["product_code"],
            "role": probe["role"],
            "url": probe["url"],
            "http_status": None,
            "usable_strip": False,
            "trade_date_in_body": False,
            "body_excerpt": None,
            "error": None,
        }
        try:
            raw = _invoke(fetch_bytes, probe["url"])
            record["http_status"] = 200
            record["body_excerpt"] = _excerpt(raw)
            record["usable_strip"] = _body_has_stamped_strip(raw, probe["product_code"])
            record["trade_date_in_body"] = record["usable_strip"]
            if (
                selected is None
                and record["usable_strip"]
                and probe["role"] == "authoritative_exchange_candidate"
            ):
                selected = {
                    "venue": probe["venue"],
                    "product_code": probe["product_code"],
                    "url": probe["url"],
                    "body": raw,
                }
        except Exception as exc:
            code = getattr(exc, "code", None)
            record["http_status"] = code
            record["error"] = str(exc)
            body = b""
            if hasattr(exc, "read"):
                try:
                    body = exc.read()
                except Exception:
                    body = b""
            if body:
                record["body_excerpt"] = _excerpt(body)
        compared.append(record)

    if selected is None:
        return {
            "status": "unavailable",
            "as_of": today.isoformat(),
            "canonical_exchange": None,
            "canonical_product_code": None,
            "primary_settlement_source": None,
            "delayed_alternative": None,
            "compared": compared,
            "eus": EUS_NOT_USED,
            "blocker": (
                "No body-stamped ICE Three-Month Euribor (I) or Eurex FEU3 "
                "settlement strip was accessible. Delayed pages that lack a "
                "demonstrable observation date are not used. US ZQ is independent."
            ),
        }

    return {
        "status": "ok",
        "as_of": today.isoformat(),
        "canonical_exchange": selected["venue"],
        "canonical_product_code": selected["product_code"],
        "primary_settlement_source": selected["url"],
        "delayed_alternative": None,
        "compared": compared,
        "eus": EUS_NOT_USED,
        "blocker": None,
        "_body": selected["body"],
    }


def parse_euribor_settlement_document(
    payload: dict[str, Any],
    *,
    session_date: date,
    source_url: str | None,
) -> dict[str, Any]:
    """Validate one exchange document. Raw rows are kept beside eligible rows.

    A row without an explicit fixing date and accrual window stays in
    ``raw_contracts`` and is not eligible for the basis join.
    """
    if not isinstance(payload, dict):
        raise ValueError("EURIBOR settlement document must be an object")
    exchange = str(payload.get("exchange") or "").upper()
    product = str(payload.get("product_code") or "").upper()
    if exchange not in {"ICE", "EUREX"}:
        raise ValueError(f"unsupported EURIBOR exchange {exchange!r}")
    expected = ICE_PRODUCT_CODE if exchange == "ICE" else EUREX_PRODUCT_CODE
    if product != expected:
        raise ValueError(
            f"{exchange} document product_code {product!r} does not match {expected}"
        )
    trade_date = str(payload.get("trade_date") or "")[:10]
    try:
        observed = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(f"EURIBOR document missing trade_date ({trade_date!r})") from exc
    if observed != session_date:
        raise ValueError(
            f"EURIBOR trade_date {trade_date} does not match requested session {session_date.isoformat()}"
        )
    quote_kind = str(payload.get("quote_kind") or "")
    if quote_kind not in {"official_settlement", "delayed_quote"}:
        raise ValueError(f"EURIBOR quote_kind {quote_kind!r} is not explicit")
    if quote_kind == "delayed_quote" and payload.get("trade_date_verified") is not False:
        raise ValueError("delayed EURIBOR quotes must set trade_date_verified false")
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ValueError("EURIBOR document has no contracts")

    raw_contracts: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in contracts:
        if not isinstance(item, dict):
            continue
        raw_contracts.append(dict(item))
        named_month = str(item.get("named_month") or item.get("expiry") or "")
        if len(named_month) < 7:
            continue
        try:
            year = int(named_month[:4])
            month = int(named_month[5:7])
            date(year, month, 1)
        except ValueError:
            continue
        price = item.get("price")
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        if not (70.0 < price_f < 100.25):
            continue
        code = str(item.get("code") or "")
        if not code or named_month in seen:
            continue
        seen.add(named_month)
        reference_start = item.get("reference_start")
        reference_end = item.get("reference_end")
        fixing_date = item.get("fixing_date")
        period_ok = bool(reference_start and reference_end and fixing_date)
        row = {
            "product": product,
            "exchange": exchange,
            "code": code,
            "expiry": named_month[:7],
            "named_month": named_month[:7],
            "price": round(price_f, 6),
            "implied_rate": round(100.0 - price_f, 6),
            "volume": item.get("volume"),
            "open_interest": item.get("open_interest"),
            "observation_date": trade_date,
            "as_of": trade_date,
            "source": f"{exchange}_{product}_SETTLEMENT" if quote_kind == "official_settlement" else f"{exchange}_{product}_DELAYED",
            "mark_kind": quote_kind,
            "trade_date_verified": quote_kind == "official_settlement",
            "source_url": source_url or payload.get("source_url"),
            "reference_start": reference_start,
            "reference_end": reference_end,
            "fixing_date": fixing_date,
            "underlying": "EURIBOR_3M",
            "eligible_for_basis": period_ok,
            "listing": item.get("listing") or ("quarterly" if month in {3, 6, 9, 12} else "serial"),
            "period_note": item.get("period_note"),
        }
        if period_ok:
            eligible.append(row)
    eligible.sort(key=lambda row: row["expiry"])
    if not raw_contracts:
        raise ValueError("EURIBOR document preserved no raw contracts")
    return {
        "rows": eligible,
        "raw_contracts": raw_contracts,
        "exchange": exchange,
        "product_code": product,
        "observation_date": trade_date,
        "mark_kind": quote_kind,
    }


def acquire_euribor_contracts(
    fetch_bytes: FetchBytes,
    *,
    today: date,
    benchmark: float | None = None,
    last_official: list | None = None,
) -> tuple[list, str, str, dict]:
    """Return a verified strip, or raise when no exchange document is accessible."""
    del benchmark, last_official
    qualification = qualify_euribor_sources(fetch_bytes, today=today)
    body = qualification.pop("_body", None)
    provenance = {
        "qualification": qualification,
        "mark_kind": None,
        "filled_from_other_curve": False,
        "eus_used": False,
    }
    if body is None or qualification.get("status") != "ok":
        raise ValueError(qualification.get("blocker") or "EURIBOR strip unavailable")
    session = today
    trade_date = None
    try:
        payload = json.loads(body.decode("utf-8"))
        trade_date = str(payload.get("trade_date") or "")[:10]
        session = date.fromisoformat(trade_date)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"selected EURIBOR body is not a dated document: {exc}") from exc
    parsed = parse_euribor_settlement_document(
        payload,
        session_date=session,
        source_url=qualification.get("primary_settlement_source"),
    )
    rows = parsed["rows"]
    if not rows:
        raise ValueError("EURIBOR document had raw rows but none were eligible")
    provenance["mark_kind"] = parsed["mark_kind"]
    provenance["trade_date"] = parsed["observation_date"]
    provenance["raw_contract_count"] = len(parsed["raw_contracts"])
    provenance["freshness_hint"] = "stale" if parsed["mark_kind"] == "delayed_quote" else None
    method = (
        f"{parsed['exchange']} {parsed['product_code']} settlements"
        if parsed["mark_kind"] == "official_settlement"
        else f"delayed {parsed['exchange']} {parsed['product_code']} quotes"
    )
    return rows, str(qualification.get("primary_settlement_source")), method, provenance


def qualification_for_publication(qualification: dict[str, Any]) -> dict[str, Any]:
    """Drop any raw body before the object is stored on a market snapshot."""
    out = dict(qualification)
    out.pop("_body", None)
    return out
