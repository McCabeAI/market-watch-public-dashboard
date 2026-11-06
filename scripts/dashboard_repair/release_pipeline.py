"""Six-economy official release fetch: adapters → events → slots + cache."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.release_contract import (
    COUNTRIES,
    EconomicReleaseEvent,
    events_to_slots,
)
from scripts.dashboard_repair.schedules import au, ca, ea, jp, nz, us

ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")
USER_AGENT = "MarketWatchDashboard/1.0"

_ADAPTER_MODULES: dict[str, tuple[Any, Any]] = {
    "US": (us, us.ADAPTER),
    "CA": (ca, ca.ADAPTER),
    "EA": (ea, ea.ADAPTER),
    "AU": (au, au.ADAPTER),
    "NZ": (nz, nz.ADAPTER),
    "JP": (jp, jp.ADAPTER),
}

_CACHE_VERSION = 1
_DEFAULT_CACHE_REL = Path("data/dashboard_repair/official_release_cache.json")

_RETENTION_SUFFIX = (
    " Retained from committed cache fetched {old_fetched_at} because the live fetch failed or returned no dates."
)


def _default_cache_path() -> Path:
    return ROOT / _DEFAULT_CACHE_REL


def _default_get(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _fetch_page(url: str, getter: Callable[[str, float], str], timeout: float) -> dict[str, Any]:
    try:
        body = getter(url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"url": url, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "html": ""}
    if not body or "Just a moment" in body or "cf-browser-verification" in body:
        return {"url": url, "status": "failed", "error": "page blocked or empty", "html": ""}
    return {"url": url, "status": "ok", "error": "", "html": body}


def _collect_gaps(adapter_mod: Any, adapter: Any) -> tuple[str, ...]:
    chunks: list[str] = []
    for bag in (getattr(adapter, "gaps", None), getattr(adapter_mod, "GAPS", ())):
        if not bag:
            continue
        if isinstance(bag, str):
            chunks.append(bag)
        else:
            chunks.extend(str(s).strip() for s in bag if str(s).strip())
    seen: set[str] = set()
    out: list[str] = []
    for g in chunks:
        if g and g not in seen:
            seen.add(g)
            out.append(g)
    return tuple(out)


def _event_from_cache_dict(payload: dict[str, Any]) -> EconomicReleaseEvent:
    ld = payload.get("local_date") or ""
    local_date = date.fromisoformat(str(ld)[:10])
    lt = payload.get("local_time")
    if lt is None or lt == "":
        local_time = None
    else:
        local_time = str(lt)
    sid = payload.get("series_ids") or []
    series_ids = tuple(str(s) for s in sid) if isinstance(sid, list) else ()
    return EconomicReleaseEvent(
        event_family=str(payload.get("event_family") or ""),
        country=str(payload.get("country") or ""),
        title=str(payload.get("title") or ""),
        publisher=str(payload.get("publisher") or ""),
        local_date=local_date,
        local_time=local_time,
        timezone=str(payload.get("timezone") or "UTC"),
        reference_period=str(payload.get("reference_period") or ""),
        source_url=str(payload.get("source_url") or ""),
        fetched_at=str(payload.get("fetched_at") or ""),
        status=str(payload.get("status") or "tba"),
        series_ids=series_ids,
        provenance=str(payload.get("provenance") or ""),
        date_confidence=str(payload.get("date_confidence") or "confirmed"),
    )


def _event_to_jsonable(ev: EconomicReleaseEvent) -> dict[str, Any]:
    return {
        "event_family": ev.event_family,
        "country": ev.country,
        "title": ev.title,
        "publisher": ev.publisher,
        "local_date": ev.local_date.isoformat(),
        "local_time": ev.local_time,
        "timezone": ev.timezone,
        "reference_period": ev.reference_period,
        "source_url": ev.source_url,
        "fetched_at": ev.fetched_at,
        "status": ev.status,
        "series_ids": list(ev.series_ids),
        "provenance": ev.provenance,
        "date_confidence": ev.date_confidence,
    }


def _load_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
        return None
    countries = raw.get("countries")
    if not isinstance(countries, dict):
        return None
    return raw


def _parse_cache_fetched_at(iso: str) -> datetime | None:
    if not iso or not str(iso).strip():
        return None
    text = str(iso).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _in_horizon(local_d: date, *, horizon_start: date, horizon_end: date) -> bool:
    return horizon_start <= local_d <= horizon_end


def _counts_by_source_url(events: list[EconomicReleaseEvent]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ev in events:
        u = str(ev.source_url or "")
        if not u:
            continue
        out[u] = out.get(u, 0) + 1
    return out


def fetch_official_schedules(
    now: datetime,
    *,
    timeout: float = 6.0,
    getter: Callable[[str, float], str] | None = None,
    cache_path: Path | str | None = None,
    write_cache: bool = True,
) -> dict[str, Any]:
    """Fetch official schedule URLs, parse per country, optional cache retention and write."""
    fetch = getter or _default_get
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    clock = now.astimezone(ET)
    today_et = clock.date()
    horizon_start = today_et - timedelta(days=7)
    horizon_end = today_et + timedelta(days=200)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    cpath = Path(cache_path) if cache_path is not None else _default_cache_path()
    prior_cache = _load_cache(cpath)

    url_to_meta: dict[str, tuple[str, str]] = {}
    all_urls: list[str] = []
    country_docs: dict[str, dict[str, str]] = {cc: {} for cc in _ADAPTER_MODULES}

    for cc, (_mod, adapter) in _ADAPTER_MODULES.items():
        for doc in adapter.source_plan():
            url_to_meta[doc.url] = (cc, doc.key)
            all_urls.append(doc.url)

    seen_url: set[str] = set()
    unique_urls: list[str] = []
    for u in all_urls:
        if u not in seen_url:
            seen_url.add(u)
            unique_urls.append(u)

    raw_pages: dict[str, dict[str, Any]] = {}
    max_workers = min(16, max(4, len(unique_urls)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_page, url, fetch, timeout): url for url in unique_urls}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                raw_pages[url] = fut.result()
            except Exception as exc:  # noqa: BLE001
                raw_pages[url] = {
                    "url": url,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "html": "",
                }

    for url, page in raw_pages.items():
        meta = url_to_meta.get(url)
        if not meta:
            continue
        cc, key = meta
        if page["status"] == "ok" and page.get("html"):
            country_docs[cc][key] = str(page["html"])
        else:
            country_docs[cc][key] = ""

    countries_diag: dict[str, dict[str, Any]] = {}
    published_events: list[EconomicReleaseEvent] = []
    all_errors: list[str] = []
    per_country_published: dict[str, list[EconomicReleaseEvent]] = {cc: [] for cc in _ADAPTER_MODULES}
    retained_fetched_at: dict[str, str] = {}

    for cc in COUNTRIES:
        if cc not in _ADAPTER_MODULES:
            continue
        adapter_mod, adapter = _ADAPTER_MODULES[cc]
        docs_map = country_docs.get(cc) or {}

        status_flag = "ok"
        retained_from_cache = False
        cache_fetched_at_flag: str | None = None
        event_count = 0
        parse_errors: list[str] = []
        chosen_events: list[EconomicReleaseEvent] = []

        live_events: list[EconomicReleaseEvent] = []
        parse_failed = False
        try:
            live_events = adapter.parse_documents(
                docs_map,
                now=now,
                fetched_at=retrieved_at,
            )
        except Exception as exc:  # noqa: BLE001
            parse_failed = True
            parse_errors.append(f"{type(exc).__name__}: {exc}")
        gaps = _collect_gaps(adapter_mod, adapter)

        if not parse_failed:
            filtered_live = [
                ev
                for ev in live_events
                if _in_horizon(ev.local_date, horizon_start=horizon_start, horizon_end=horizon_end)
            ]
            if filtered_live:
                chosen_events = filtered_live
                status_flag = "ok"
            else:
                # Parse ran but nothing printable in the horizon window.
                status_flag = "empty"
        else:
            status_flag = "failed"

        if parse_failed or status_flag == "empty":
            retained_events: list[EconomicReleaseEvent] = []
            if prior_cache:
                blob = (prior_cache.get("countries") or {}).get(cc)
                if isinstance(blob, dict):
                    cache_fetch_at = str(blob.get("fetched_at") or "")
                    cache_dt = _parse_cache_fetched_at(cache_fetch_at)
                    now_utc = now.astimezone(timezone.utc)
                    if cache_dt is not None and (now_utc - cache_dt) <= timedelta(days=45):
                        for raw_ev in blob.get("events") or []:
                            if not isinstance(raw_ev, dict):
                                continue
                            try:
                                ev = _event_from_cache_dict(raw_ev)
                            except (ValueError, TypeError, KeyError):
                                continue
                            if not _in_horizon(ev.local_date, horizon_start=horizon_start, horizon_end=horizon_end):
                                continue
                            suf = _RETENTION_SUFFIX.format(old_fetched_at=cache_fetch_at)
                            prov = str(ev.provenance or "")
                            if suf.strip() not in prov:
                                ev = EconomicReleaseEvent(
                                    event_family=ev.event_family,
                                    country=ev.country,
                                    title=ev.title,
                                    publisher=ev.publisher,
                                    local_date=ev.local_date,
                                    local_time=ev.local_time,
                                    timezone=ev.timezone,
                                    reference_period=ev.reference_period,
                                    source_url=ev.source_url,
                                    fetched_at=ev.fetched_at,
                                    status=ev.status,
                                    series_ids=ev.series_ids,
                                    provenance=(prov + suf).strip(),
                                    date_confidence=ev.date_confidence,
                                )
                            retained_events.append(ev)
            if retained_events:
                chosen_events = retained_events
                status_flag = "retained"
                retained_from_cache = True
                cache_fetched_at_flag = str(
                    (prior_cache.get("countries") or {}).get(cc, {}).get("fetched_at") or ""
                )
                retained_fetched_at[cc] = cache_fetched_at_flag
            elif parse_failed:
                status_flag = "failed"
            else:
                status_flag = "empty"

        event_count = len(chosen_events)
        if chosen_events:
            published_events.extend(chosen_events)
            per_country_published[cc] = chosen_events

        countries_diag[cc] = {
            "status": status_flag,
            "event_count": event_count,
            "gaps": list(gaps),
            "errors": parse_errors,
            "retained_from_cache": retained_from_cache,
            "cache_fetched_at": cache_fetched_at_flag,
        }

    # Per-URL report rows
    report_pages: list[dict[str, Any]] = []
    for url in unique_urls:
        cc, _key = url_to_meta.get(url, ("", ""))
        pg = raw_pages.get(url, {"url": url, "status": "failed", "error": "not fetched", "html": ""})
        st = pg.get("status", "failed")
        err = str(pg.get("error") or "")
        parsed = 0
        if st == "ok":
            counts = _counts_by_source_url(per_country_published.get(cc) or [])
            parsed = int(counts.get(url, 0))
        if st != "ok" and err:
            all_errors.append(f"{url} ({err})")
        report_pages.append(
            {
                "url": url,
                "status": st,
                "error": err,
                "parsed": parsed,
                "country": cc,
            }
        )

    slots = events_to_slots(published_events) if published_events else []

    cache_notes = [
        f"countries={len(countries_diag)}",
        f"events_published={len(published_events)}",
        f"slots={len(slots)}",
        f"cache_file={cpath.name}",
    ]

    if write_cache:
        country_payload: dict[str, Any] = {}
        for cc, evs in per_country_published.items():
            if not evs:
                continue
            _mod, adapter = _ADAPTER_MODULES[cc]
            country_payload[cc] = {
                "fetched_at": retained_fetched_at.get(cc) or retrieved_at,
                "source_urls": [d.url for d in adapter.source_plan()],
                "events": [_event_to_jsonable(e) for e in evs],
            }
        out_obj = {"version": _CACHE_VERSION, "countries": country_payload}
        try:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(out_obj, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    return {
        "attempted": True,
        "retrieved_at": retrieved_at,
        "pages": report_pages,
        "errors": all_errors[:24],
        "slots": slots,
        "countries": countries_diag,
        "cache": cache_notes,
    }


def seed_cache_from_fixtures(
    *,
    fixture_root: Path | None = None,
    output_path: Path | None = None,
    fetched_at: str = "2026-11-06T18:00:00Z",
    horizon_center: date | None = None,
) -> dict[str, Any]:
    """Populate cache JSON from tests/fixtures/release_calendar (seed helper)."""
    fr = fixture_root or (ROOT / "tests/fixtures/release_calendar")
    out = output_path or _default_cache_path()
    center = horizon_center or date(2026, 11, 6)
    horizon_start = date(2026, 10, 30)
    horizon_end = date(2027, 5, 25)
    now = datetime(center.year, center.month, center.day, 12, 0, 0, tzinfo=ET)

    doc_maps: dict[str, dict[str, str]] = {
        "US": {
            "bls_empsit": (fr / "us/bls_empsit.md").read_text(encoding="utf-8"),
            "bls_cpi": (fr / "us/bls_cpi.md").read_text(encoding="utf-8"),
            "bls_ppi": (fr / "us/bls_ppi.md").read_text(encoding="utf-8"),
            "bls_jolts": (fr / "us/bls_jolts.md").read_text(encoding="utf-8"),
            "bea_schedule": (fr / "us/bea_schedule.html").read_text(encoding="utf-8"),
            "fomc": (fr / "us/fomc.html").read_text(encoding="utf-8"),
            "ism": (fr / "us/ism.md").read_text(encoding="utf-8"),
            "us_retail": (fr / "us/us_retail.txt").read_text(encoding="utf-8"),
        },
        "CA": {
            "primary_table": (fr / "ca/release_dates_2026.txt").read_text(encoding="utf-8"),
            "daily_clock": (fr / "ca/daily_clock.html").read_text(encoding="utf-8"),
            "lfs_daily": (fr / "ca/lfs_daily.html").read_text(encoding="utf-8"),
            "boc_rate": (fr / "ca/boc_key.html").read_text(encoding="utf-8"),
        },
        "EA": {
            "ecb_hicp": (fr / "ea/ecb_hicp_excerpt.html").read_text(encoding="utf-8"),
            "eurostat_qna": (fr / "ea/eurostat_qna_excerpt.txt").read_text(encoding="utf-8"),
            "ecb_gc": (fr / "ea/ecb_gc_excerpt.html").read_text(encoding="utf-8"),
        },
        "AU": {
            "abs_wpi": (fr / "au/abs_wpi.html").read_text(encoding="utf-8"),
            "abs_month": (fr / "au/abs_month.html").read_text(encoding="utf-8"),
            "rba_int_rate": (fr / "au/rba_int_rate.html").read_text(encoding="utf-8"),
        },
        "NZ": {
            "stats_nz_calendar": (fr / "nz/stats_nz_calendar_ics_snippet.txt").read_text(encoding="utf-8"),
            "stats_nz_gdp": (fr / "nz/stats_nz_gdp_latest_release.html").read_text(encoding="utf-8"),
            "stats_nz_cpi": (fr / "nz/stats_nz_cpi_latest.html").read_text(encoding="utf-8"),
            "rbnz_ocr": (fr / "nz/rbnz_statistics_ocr.html").read_text(encoding="utf-8"),
        },
        "JP": {
            "cao_gdp": (fr / "jp/cao_gdp.html").read_text(encoding="utf-8"),
            "estat": (fr / "jp/estat_schedule_excerpt.txt").read_text(encoding="utf-8"),
            "boj_mpm": (fr / "jp/boj_mpm.html").read_text(encoding="utf-8"),
            "boj_calendar": (fr / "jp/boj_calendar_nov2026.html").read_text(encoding="utf-8"),
        },
    }

    country_payload: dict[str, Any] = {}
    for cc, (_mod, adapter) in _ADAPTER_MODULES.items():
        docs = doc_maps[cc]
        events = adapter.parse_documents(docs, now=now, fetched_at=fetched_at)
        filtered = [e for e in events if horizon_start <= e.local_date <= horizon_end]
        country_payload[cc] = {
            "fetched_at": fetched_at,
            "source_urls": [d.url for d in adapter.source_plan()],
            "events": [_event_to_jsonable(e) for e in filtered],
        }

    obj = {"version": _CACHE_VERSION, "countries": country_payload}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return obj


__all__ = ["fetch_official_schedules", "seed_cache_from_fixtures", "ROOT"]
