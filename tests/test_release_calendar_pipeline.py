"""End-to-end tests for the six-economy official schedule pipeline (no network)."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.calendar_view import build_release_model, render_releases
from scripts.dashboard_repair.release_pipeline import fetch_official_schedules
from scripts.dashboard_repair.schedules import au, ca, ea, jp, nz, us

# Eurostat QNA PDF URL (adapter constant; used in selective getter tests)
_EUROSTAT_QNA_URL = "https://ec.europa.eu/eurostat/documents/24987/6642470/QNA_release_calendar.pdf"
_ECB_HICP_URL = "https://www.ecb.europa.eu/press/calendars/statscal/ges/html/sthicp.en.html"
_ECB_GC_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"

ET = ZoneInfo("America/New_York")
_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "release_calendar"
_COMMITTED_CACHE = (
    Path(__file__).resolve().parents[1] / "data" / "dashboard_repair" / "official_release_cache.json"
)

_US_FILES = {
    "bls_empsit": "bls_empsit.md",
    "bls_cpi": "bls_cpi.md",
    "bls_ppi": "bls_ppi.md",
    "bls_jolts": "bls_jolts.md",
    "bea_schedule": "bea_schedule.html",
    "fomc": "fomc.html",
    "ism": "ism.md",
    "us_retail": "us_retail.txt",
}


def _fixture_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for doc in us.ADAPTER.source_plan():
        name = _US_FILES.get(doc.key)
        if name:
            out[doc.url] = (_FIXTURE_ROOT / "us" / name).read_text(encoding="utf-8")
    ca_files = {
        "primary_table": "release_dates_2026.txt",
        "daily_clock": "daily_clock.html",
        "lfs_daily": "lfs_daily.html",
        "boc_rate": "boc_key.html",
    }
    for doc in ca.ADAPTER.source_plan():
        fn = ca_files.get(doc.key)
        if fn:
            out[doc.url] = (_FIXTURE_ROOT / "ca" / fn).read_text(encoding="utf-8")
    ea_files = {"ecb_hicp": "ecb_hicp_excerpt.html", "eurostat_qna": "eurostat_qna_excerpt.txt", "ecb_gc": "ecb_gc_excerpt.html"}
    for doc in ea.ADAPTER.source_plan():
        fn = ea_files.get(doc.key)
        if fn:
            out[doc.url] = (_FIXTURE_ROOT / "ea" / fn).read_text(encoding="utf-8")
    au_files = {"abs_wpi": "abs_wpi.html", "abs_month": "abs_month.html", "rba_int_rate": "rba_int_rate.html"}
    for doc in au.ADAPTER.source_plan():
        fn = au_files.get(doc.key)
        if fn:
            out[doc.url] = (_FIXTURE_ROOT / "au" / fn).read_text(encoding="utf-8")
    nz_files = {
        "stats_nz_calendar": "stats_nz_calendar_ics_snippet.txt",
        "stats_nz_gdp": "stats_nz_gdp_latest_release.html",
        "stats_nz_cpi": "stats_nz_cpi_latest.html",
        "rbnz_ocr": "rbnz_statistics_ocr.html",
    }
    for doc in nz.ADAPTER.source_plan():
        fn = nz_files.get(doc.key)
        if fn:
            out[doc.url] = (_FIXTURE_ROOT / "nz" / fn).read_text(encoding="utf-8")
    jp_files = {
        "cao_gdp": "cao_gdp.html",
        "estat": "estat_schedule_excerpt.txt",
        "boj_mpm": "boj_mpm.html",
        "boj_calendar": "boj_calendar_nov2026.html",
    }
    for doc in jp.ADAPTER.source_plan():
        fn = jp_files.get(doc.key)
        if fn:
            out[doc.url] = (_FIXTURE_ROOT / "jp" / fn).read_text(encoding="utf-8")
    return out


_URL_BODIES = _fixture_map()


def _fixture_getter(url: str, timeout: float) -> str:
    return _URL_BODIES.get(url, "not found")


def _is_us_url(url: str) -> bool:
    host = url.split("/")[2] if "://" in url else ""
    return host.endswith("bls.gov") or host.endswith("bea.gov") or host.endswith("federalreserve.gov") or host.endswith(
        "ismworld.org"
    ) or host.endswith("census.gov")


def _us_down_getter(url: str, timeout: float) -> str:
    if _is_us_url(url):
        raise RuntimeError("simulated US fetch failure")
    return _fixture_getter(url, timeout)


def _all_rows(model: dict) -> list:
    return list(model["upcoming"]) + list(model["recent"]) + list(model["later"])


def _events_list(fetch: dict) -> list:
    """Slots from ``fetch_official_schedules`` (one dict per event with event_family, source_url, …)."""
    return list(fetch.get("slots") or [])


def _statcan_pdf_url() -> str:
    return next(d.url for d in ca.ADAPTER.source_plan() if d.key == "primary_table")


def _boc_url() -> str:
    return next(d.url for d in ca.ADAPTER.source_plan() if d.key == "boc_rate")


class ReleaseCalendarPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmpdir.name) / "official_release_cache.json"
        shutil.copyfile(_COMMITTED_CACHE, self.cache_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_fixture_pipeline_all_countries_dup_lfs_and_displays(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        fetched = fetch_official_schedules(
            now,
            timeout=6.0,
            getter=_fixture_getter,
            cache_path=self.cache_path,
            write_cache=False,
        )
        model = build_release_model(now=now, fetched_slots=fetched["slots"], schedule_fetch=fetched)
        rows = _all_rows(model)
        countries = {str(r.get("country")) for r in rows}
        for code in ("US", "CA", "EA", "AU", "NZ", "JP"):
            self.assertIn(code, countries, msg=f"missing {code} release in model")

        lfs_oct_recent = [
            r
            for r in model["recent"]
            if str(r.get("event_family") or "") == "ca_lfs"
            and "2026-10" in str(r.get("reference_period") or "")
        ]
        self.assertEqual(len(lfs_oct_recent), 1, msg="expected one grouped LFS card for Oct 2026 reference in recent")
        series_set = set(lfs_oct_recent[0].get("series_ids") or [])
        self.assertTrue(
            {"CA.Labor.unemployment", "CA.Labor.wages", "CA.Labor.employment"}.issubset(series_set),
            series_set,
        )

        wpi = next(
            r
            for r in rows
            if r.get("country") == "AU"
            and str(r.get("event_family") or "") == "au_wpi"
            and "2026-Q3" in str(r.get("reference_period") or "")
        )
        self.assertIn("2026-11-18", str(wpi.get("local_display") or ""))
        self.assertIn("2026-11-17 19:30", str(wpi.get("et_display") or "").replace(" ET", ""))

        gdp = next(
            r
            for r in rows
            if r.get("country") == "JP"
            and str(r.get("event_family") or "") == "jp_gdp"
            and "first preliminary" in str(r.get("name") or "").lower()
        )
        self.assertIn("2026-11-16", str(gdp.get("local_display") or ""))
        self.assertIn("08:50", str(gdp.get("local_display") or ""))
        self.assertIn("2026-11-15 18:50", str(gdp.get("et_display") or "").replace(" ET", ""))

        tba_row = next(
            r
            for r in rows
            if r.get("clock") == "tba"
            and str(r.get("event_family") or "") in {"nz_selected_prices", "ea_hicp"}
        )
        self.assertIsNotNone(tba_row)
        html = render_releases(model)
        self.assertIn("TBA", html)

        self.assertIn('data-release-country="CA"', html)
        self.assertIn('data-release-country="AU"', html)
        self.assertIn('data-release-country="JP"', html)
        self.assertIn("Labour Force Survey", html)
        self.assertIn("Wage Price Index", html)
        self.assertIn(gdp["name"], html)

    def test_lfs_in_upcoming_at_7am_et(self) -> None:
        now = datetime(2026, 11, 6, 7, 0, 0, tzinfo=ET)
        fetched = fetch_official_schedules(
            now, getter=_fixture_getter, cache_path=self.cache_path, write_cache=False
        )
        model = build_release_model(now=now, fetched_slots=fetched["slots"], schedule_fetch=fetched)
        lfs_up = [r for r in model["upcoming"] if str(r.get("event_family") or "") == "ca_lfs"]
        lfs_recent = [r for r in model["recent"] if str(r.get("event_family") or "") == "ca_lfs"]
        self.assertEqual(len(lfs_up), 1)
        self.assertEqual(lfs_recent, [])

    def test_lfs_in_recent_at_noon_et(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        fetched = fetch_official_schedules(
            now, getter=_fixture_getter, cache_path=self.cache_path, write_cache=False
        )
        model = build_release_model(now=now, fetched_slots=fetched["slots"], schedule_fetch=fetched)
        lfs_recent = [r for r in model["recent"] if str(r.get("event_family") or "") == "ca_lfs"]
        lfs_up = [r for r in model["upcoming"] if str(r.get("event_family") or "") == "ca_lfs"]
        self.assertEqual(len(lfs_recent), 1)
        self.assertEqual(lfs_up, [])

    def test_us_fetch_failure_retains_cache(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        fetched = fetch_official_schedules(
            now,
            getter=_us_down_getter,
            cache_path=self.cache_path,
            write_cache=False,
        )
        diag = fetched.get("countries") or {}
        self.assertTrue(diag.get("US", {}).get("retained_from_cache"))
        model = build_release_model(now=now, fetched_slots=fetched["slots"], schedule_fetch=fetched)
        us_rows = [r for r in _all_rows(model) if r.get("country") == "US"]
        self.assertTrue(any("US.Labor.payrolls" in (r.get("series_ids") or []) for r in us_rows))
        original_us = json.loads(self.cache_path.read_text(encoding="utf-8"))["countries"]["US"]["fetched_at"]
        fetch_official_schedules(
            now,
            getter=_us_down_getter,
            cache_path=self.cache_path,
            write_cache=True,
        )
        written_us = json.loads(self.cache_path.read_text(encoding="utf-8"))["countries"]["US"]["fetched_at"]
        self.assertEqual(written_us, original_us)

    def test_stale_cache_not_retained(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        stale = json.loads(_COMMITTED_CACHE.read_text(encoding="utf-8"))
        stale["countries"]["US"] = copy.deepcopy(stale["countries"].get("US", {}))
        stale["countries"]["US"]["fetched_at"] = "2025-01-01T12:00:00Z"
        path = Path(self._tmpdir.name) / "stale.json"
        path.write_text(json.dumps(stale), encoding="utf-8")
        fetched = fetch_official_schedules(
            now,
            getter=_us_down_getter,
            cache_path=path,
            write_cache=False,
        )
        self.assertFalse(fetched.get("countries", {}).get("US", {}).get("retained_from_cache"))

    def test_ca_pdf_fetch_fails_retains_lfs_adds_boc_from_fixture(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        statcan = _statcan_pdf_url()

        def getter(url: str, timeout: float) -> str:
            if url == statcan:
                raise RuntimeError("simulated StatCan PDF failure")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        lfs_nov = [
            e
            for e in evs
            if str(e.get("event_family")) == "ca_lfs"
            and str(e.get("local_date")) == "2026-11-06"
            and e.get("source_url") == statcan
        ]
        self.assertEqual(len(lfs_nov), 1)
        self.assertEqual(lfs_nov[0].get("fetched_at"), "2026-11-06T18:00:00Z")
        self.assertTrue(any(str(e.get("event_family")) == "ca_boc" for e in evs))

    def test_ca_boc_fetch_fails_retains_boc_lfs_from_live_pdf(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        boc = _boc_url()
        cache_before = json.loads(self.cache_path.read_text(encoding="utf-8"))
        boc_cached_fa = next(
            e["fetched_at"]
            for e in cache_before["countries"]["CA"]["events"]
            if e.get("event_family") == "ca_boc"
        )

        def getter(url: str, timeout: float) -> str:
            if url == boc:
                raise RuntimeError("simulated BoC failure")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        boc_rows = [e for e in evs if str(e.get("event_family")) == "ca_boc"]
        self.assertTrue(boc_rows)
        self.assertEqual(boc_rows[0].get("fetched_at"), boc_cached_fa)
        self.assertTrue(
            any(
                str(e.get("event_family")) == "ca_lfs" and "2026-11-06" in str(e.get("local_date"))
                for e in evs
            )
        )

    def test_ea_eurostat_fails_retains_gdp_flash_ecb_fixture_adds_hicp(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)

        def getter(url: str, timeout: float) -> str:
            if url == _EUROSTAT_QNA_URL:
                raise RuntimeError("simulated Eurostat PDF failure")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        self.assertTrue(any(str(e.get("event_family")) == "ea_gdp_flash" for e in evs))
        families = {str(e.get("event_family")) for e in evs}
        self.assertTrue("ea_hicp" in families or "ea_ecb_mp" in families)

    def test_ea_ecb_urls_fail_eurostat_fixture_yields_gdp_retains_cached_ecb_fetched_at(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        cache_before = json.loads(self.cache_path.read_text(encoding="utf-8"))
        ea_events = cache_before["countries"]["EA"]["events"]
        hicp_cached_fa = next(
            e["fetched_at"]
            for e in ea_events
            if str(e.get("event_family")) == "ea_hicp" and str(e.get("local_date")) == "2026-11-18"
        )
        mp_cached_fa = next(
            e["fetched_at"]
            for e in ea_events
            if str(e.get("event_family")) == "ea_ecb_mp" and str(e.get("local_date")) == "2026-12-17"
        )

        def getter(url: str, timeout: float) -> str:
            if url in (_ECB_HICP_URL, _ECB_GC_URL):
                raise RuntimeError("simulated ECB fetch failure")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        self.assertTrue(
            any(str(e.get("event_family")) in ("ea_gdp_flash", "ea_gdp") for e in evs),
        )
        hicp_rows = [
            e
            for e in evs
            if str(e.get("event_family")) == "ea_hicp" and str(e.get("local_date")) == "2026-11-18"
        ]
        self.assertTrue(hicp_rows)
        self.assertEqual(hicp_rows[0].get("fetched_at"), hicp_cached_fa)
        mp_rows = [
            e
            for e in evs
            if str(e.get("event_family")) == "ea_ecb_mp" and str(e.get("local_date")) == "2026-12-17"
        ]
        self.assertTrue(mp_rows)
        self.assertEqual(mp_rows[0].get("fetched_at"), mp_cached_fa)

    def test_au_wpi_fetch_fails_retains_wpi_other_abs_fixture_events_present(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        wpi_url = au._URL_ABS_WPI

        def getter(url: str, timeout: float) -> str:
            if url == wpi_url:
                raise RuntimeError("simulated ABS WPI failure")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        wpi = [e for e in evs if str(e.get("event_family")) == "au_wpi"]
        self.assertTrue(wpi)
        self.assertEqual(wpi[0].get("fetched_at"), "2026-11-06T18:00:00Z")
        self.assertTrue(
            any("labour" in str(e.get("title", "")).lower() for e in evs)
            or any(str(e.get("event_family", "")).startswith("au_cpi") for e in evs)
        )

    def test_ca_updated_statcan_snippet_replaces_cached_nov6_lfs(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        statcan = _statcan_pdf_url()
        minimal_pdf_text = (
            "LabourForceSurvey\n\nDecember 4, 2026 November 2026\n"
        )

        def getter(url: str, timeout: float) -> str:
            if url == statcan:
                return minimal_pdf_text
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        from_pdf = [e for e in evs if e.get("source_url") == statcan and e.get("event_family") == "ca_lfs"]
        ids = {f'{e.get("country")}:{e.get("event_family")}:{e.get("local_date")}:{e.get("reference_period")}' for e in from_pdf}
        self.assertNotIn("CA:ca_lfs:2026-11-06:2026-10", ids)
        self.assertIn("CA:ca_lfs:2026-12-04:2026-11", ids)

    def test_stale_source_fetched_at_not_retained_horizon_drop(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)
        empsit = "https://www.bls.gov/schedule/news_release/empsit.htm"
        stale_path = Path(self._tmpdir.name) / "stale_src.json"
        base = json.loads(_COMMITTED_CACHE.read_text(encoding="utf-8"))
        us = copy.deepcopy(base["countries"]["US"])
        us["sources"] = {
            empsit: {
                "status": "ok",
                "fetched_at": "2025-01-01T12:00:00Z",
                "event_count": 1,
                "retained_from_cache": False,
            }
        }
        us["events"] = [
            e
            for e in us["events"]
            if e.get("source_url") != empsit or e.get("reference_period") != "2026-11"
        ]
        us["events"].append(
            {
                "event_family": "us_empsit",
                "country": "US",
                "title": "Employment Situation",
                "publisher": "Bureau of Labor Statistics",
                "local_date": "2026-12-04",
                "local_time": "08:30",
                "timezone": "America/New_York",
                "reference_period": "2026-11",
                "source_url": empsit,
                "fetched_at": "2025-01-01T12:00:00Z",
                "status": "verified",
                "series_ids": ["US.Labor.payrolls"],
                "provenance": "synthetic stale",
                "date_confidence": "confirmed",
            }
        )
        base["countries"]["US"] = us
        stale_path.write_text(json.dumps(base), encoding="utf-8")

        def getter(url: str, timeout: float) -> str:
            if "bls.gov" in url:
                raise RuntimeError("bls down")
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=stale_path, write_cache=False
        )
        evs = _events_list(fetched)
        self.assertFalse(
            any(
                e.get("source_url") == empsit
                and str(e.get("reference_period")) == "2026-11"
                and str(e.get("local_date")) == "2026-12-04"
                for e in evs
            )
        )

        horizon_path = Path(self._tmpdir.name) / "horizon.json"
        base2 = json.loads(_COMMITTED_CACHE.read_text(encoding="utf-8"))
        us2 = copy.deepcopy(base2["countries"]["US"])
        us2["sources"] = {
            empsit: {
                "status": "ok",
                "fetched_at": "2026-11-06T18:00:00Z",
                "event_count": 1,
                "retained_from_cache": False,
            }
        }
        us2["events"] = [
            e
            for e in us2["events"]
            if e.get("source_url") != empsit or e.get("reference_period") != "2026-09"
        ]
        us2["events"].append(
            {
                "event_family": "us_empsit",
                "country": "US",
                "title": "Employment Situation",
                "publisher": "Bureau of Labor Statistics",
                "local_date": "2026-10-01",
                "local_time": "08:30",
                "timezone": "America/New_York",
                "reference_period": "2026-09",
                "source_url": empsit,
                "fetched_at": "2026-11-06T18:00:00Z",
                "status": "verified",
                "series_ids": ["US.Labor.payrolls"],
                "provenance": "synthetic old horizon",
                "date_confidence": "confirmed",
            }
        )
        base2["countries"]["US"] = us2
        horizon_path.write_text(json.dumps(base2), encoding="utf-8")

        fetched2 = fetch_official_schedules(
            now, getter=getter, cache_path=horizon_path, write_cache=False
        )
        evs2 = _events_list(fetched2)
        self.assertFalse(any(e.get("local_date") == "2026-10-01" for e in evs2))

    def test_success_empty_body_clears_cached_events_for_that_source(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)

        def getter(url: str, timeout: float) -> str:
            if url == _ECB_HICP_URL:
                return "<html><body><p>no release table</p></body></html>"
            return _fixture_getter(url, timeout)

        fetched = fetch_official_schedules(
            now, getter=getter, cache_path=self.cache_path, write_cache=False
        )
        evs = _events_list(fetched)
        self.assertFalse(
            any(
                str(e.get("event_family", "")).startswith("ea_hicp")
                and e.get("source_url") == _ECB_HICP_URL
                for e in evs
            )
        )

    def test_second_write_cache_does_not_refresh_retained_fetched_at(self) -> None:
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=ET)

        def getter(url: str, timeout: float) -> str:
            if url == _statcan_pdf_url():
                raise RuntimeError("pdf fail")
            return _fixture_getter(url, timeout)

        fetch_official_schedules(now, getter=getter, cache_path=self.cache_path, write_cache=True)
        first = json.loads(self.cache_path.read_text(encoding="utf-8"))
        lfs_fa_1 = next(
            e["fetched_at"]
            for e in first["countries"]["CA"]["events"]
            if e.get("event_family") == "ca_lfs"
            and str(e.get("local_date")) == "2026-11-06"
        )
        boc_fa_1 = next(
            e["fetched_at"]
            for e in first["countries"]["CA"]["events"]
            if e.get("event_family") == "ca_boc"
        )

        fetch_official_schedules(now, getter=getter, cache_path=self.cache_path, write_cache=True)
        second = json.loads(self.cache_path.read_text(encoding="utf-8"))
        lfs_fa_2 = next(
            e["fetched_at"]
            for e in second["countries"]["CA"]["events"]
            if e.get("event_family") == "ca_lfs"
            and str(e.get("local_date")) == "2026-11-06"
        )
        boc_fa_2 = next(
            e["fetched_at"]
            for e in second["countries"]["CA"]["events"]
            if e.get("event_family") == "ca_boc"
        )
        self.assertEqual(lfs_fa_1, lfs_fa_2)
        self.assertEqual(boc_fa_1, boc_fa_2)


if __name__ == "__main__":
    unittest.main()
