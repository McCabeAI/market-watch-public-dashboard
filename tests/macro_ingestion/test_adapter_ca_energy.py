"""Canada physical energy / hard-activity ingestion (issue #139).

Deterministic coverage for: AER ST3 workbook parsing, StatCan WDS history
parsing, units, calendar-day normalisation, duplicate prevention, revision
handling, source-failure behaviour, the CREA gap row, and catalog hygiene.
The live smoke test is env-gated and otherwise validates the committed report.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openpyxl

from scripts.canada_energy_data import (
    CALENDAR_DAY_RATE,
    CALENDAR_DAY_RATE_FORMULA,
    MONTHLY_LEVEL,
    CanadaEnergyError,
    calendar_day_rate,
    days_in_period,
    parse_aer_st3_oil_workbook,
    statcan_vector_history_points,
    with_calendar_day_rates,
)
from scripts.macro_ingestion.adapters.ca import STATCAN_WDS_URL, fetch_series
from scripts.macro_ingestion.contract import index_series_rows, load_catalog
from scripts.macro_ingestion.runner import live_opener, run_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ca"
WDS_GAS_FIXTURE = FIXTURES / "wds_gas_marketable_v1864626177.json"
LIVE_REPORT_PATH = FIXTURES / "live_smoke_report_energy.json"

AER_CURRENT_URL = "https://www.aer.ca/documents/sts/st3/Oil_current.xlsx"
AER_2025_URL = "https://www.aer.ca/prd/documents/sts/st3/Oil_2025.xlsx"

NEW_ROW_IDS = (
    "CA.Energy.ab_oil_total_production",
    "CA.Energy.ab_oil_sands_production",
    "CA.Energy.ab_conventional_crude_production",
    "CA.Energy.ab_condensate_production",
    "CA.Energy.gas_marketable_production",
    "CA.Activity.real_manufacturing_sales",
    "CA.Consumer.retail_sales_volume",
    "CA.Activity.wholesale_sales_volume",
    "CA.Activity.real_building_investment",
    "CA.Activity.crude_export_volume",
    "CA.Housing.existing_home_sales",
)
AER_ROW_IDS = NEW_ROW_IDS[:4]
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _aer_workbook(
    *,
    year: int,
    run_date: str,
    conventional: dict[int, float],
    condensate: dict[int, float],
    oil_sands: dict[int, float],
    unit_line: str = "Unit = cubic metres (m3)",
) -> bytes:
    """Synthetic workbook mirroring the AER ST3 oil 'Data' sheet layout.

    Unpublished months are written as 0, exactly as the publisher does.
    """
    wb = openpyxl.Workbook()
    doc = wb.active
    doc.title = "Documentation"
    doc.append([None, "Total Production", None, "CALCULATED: SUM of ..."])
    data = wb.create_sheet("Data")
    data.append([None] * 22)
    data.append([None] * 8 + ["Supply and Disposition of Crude Oil and Equivalent"])
    data.append([None] * 7 + [unit_line])
    data.append([None, f" Run Date:  {run_date}"] + [None] * 14 + ["Year To Date"])
    data.append([None, None, None, *list(_MONTHS), None, str(year)])
    data.append([None, "SUPPLY"])
    data.append([None, "Opening Inventory", None, *[1.0] * 12])
    data.append([None, "Production"])
    data.append([None, "Crude Oil Production"])

    def month_row(label: str, values: dict[int, float]) -> list:
        return [None, label, None, *[float(values.get(m, 0.0)) for m in range(1, 13)]]

    data.append(month_row("Crude Oil Light", {m: v * 0.5 for m, v in conventional.items()}))
    data.append(month_row("Total Crude Oil Production", conventional))
    data.append(month_row("Condensate Production", condensate))
    data.append([None, "Oil Sands Production "])
    data.append(month_row("Total Oil Sands Production", oil_sands))
    total = {
        m: conventional.get(m, 0.0) + condensate.get(m, 0.0) + oil_sands.get(m, 0.0)
        for m in range(1, 13)
    }
    data.append(month_row("Total Production", total))
    data.append([None, "Receipts"])
    data.append([None, f" Run Date:  {run_date}"])
    data.append([None, None, None, *list(_MONTHS)])
    data.append([None, "DISPOSITION"])
    data.append(month_row("Total Production", {m: 999.0 for m in range(1, 13)}))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _current_2026() -> bytes:
    return _aer_workbook(
        year=2026,
        run_date="27 August 2026",
        conventional={m: 2_700_000.0 + m for m in range(1, 8)},
        condensate={m: 450_000.0 + m for m in range(1, 8)},
        oil_sands={1: 17_518_142.9, 2: 15_525_054.8, 3: 17_255_519.9, 4: 16_563_917.4, 5: 16_420_623.9, 6: 16_513_522.1, 7: 18_423_653.0},
    )


def _archive_2025(*, december_oil_sands: float = 18_460_947.0) -> bytes:
    return _aer_workbook(
        year=2025,
        run_date="27 February 2026",
        conventional={m: 2_600_000.0 + m for m in range(1, 13)},
        condensate={m: 420_000.0 + m for m in range(1, 13)},
        oil_sands={**{m: 17_000_000.0 + m for m in range(1, 12)}, 12: december_oil_sands},
    )


class _FixtureOpener:
    def __init__(self, bodies: dict[str, bytes | None], *, http_status: int = 200) -> None:
        self.bodies = bodies
        self.http_status = http_status
        self.calls: list[str] = []

    def __call__(self, url: str, *, timeout: float = 20) -> dict:
        self.calls.append(url)
        body = self.bodies.get(url)
        if body is None:
            return {"ok": False, "url": url, "http_status": 503, "body": b"", "error": "HTTP 503"}
        return {"ok": True, "url": url, "http_status": self.http_status, "body": body, "error": None}


class TestCalendarDayNormalisation(unittest.TestCase):
    def test_days_in_period_handles_leap_years_and_month_lengths(self) -> None:
        self.assertEqual(days_in_period("2024-02"), 29)
        self.assertEqual(days_in_period("2025-02"), 28)
        self.assertEqual(days_in_period("2026-06"), 30)
        self.assertEqual(days_in_period("2026-07"), 31)
        with self.assertRaises(ValueError):
            days_in_period("2026-13")
        with self.assertRaises(ValueError):
            days_in_period("2026-Q2")

    def test_calendar_day_rate_is_level_over_days(self) -> None:
        self.assertAlmostEqual(calendar_day_rate("2026-07", 31.0 * 1000.0), 1000.0)
        self.assertAlmostEqual(calendar_day_rate("2026-06", 30.0 * 1000.0), 1000.0)
        # Equal monthly totals in a 30- and a 31-day month are not equal daily rates.
        self.assertGreater(calendar_day_rate("2026-06", 100.0), calendar_day_rate("2026-07", 100.0))

    def test_with_calendar_day_rates_writes_units_and_derivation(self) -> None:
        points = [{"period": "2026-07", "value": 3100.0, "source_url": "u"}]
        out = with_calendar_day_rates(points, units="cubic metres")
        self.assertEqual([p["transformation"] for p in out], [MONTHLY_LEVEL, CALENDAR_DAY_RATE])
        self.assertEqual(out[0]["units"], "cubic metres")
        self.assertEqual(out[0]["value"], 3100.0)
        self.assertEqual(out[1]["units"], "cubic metres per calendar day")
        self.assertAlmostEqual(out[1]["value"], 100.0)
        self.assertEqual(out[1]["derivation"]["formula"], CALENDAR_DAY_RATE_FORMULA)
        self.assertEqual(out[1]["derivation"]["days_in_month"], 31)
        self.assertEqual(out[1]["derivation"]["derived_from_transformation"], MONTHLY_LEVEL)
        self.assertNotIn("derivation", out[0])


class TestAerWorkbookParsing(unittest.TestCase):
    def test_parse_extracts_series_units_run_date_and_drops_unpublished_months(self) -> None:
        parsed = parse_aer_st3_oil_workbook(_current_2026())
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(parsed["run_date"], "2026-08-27")
        self.assertEqual(parsed["units"], "cubic metres")
        series = parsed["series"]
        self.assertEqual(
            set(series),
            {
                "ab_oil_total_production",
                "ab_oil_sands_production",
                "ab_conventional_crude_production",
                "ab_condensate_production",
            },
        )
        self.assertEqual(sorted(series["ab_oil_sands_production"]), [f"2026-0{m}" for m in range(1, 8)])
        self.assertEqual(series["ab_oil_sands_production"]["2026-07"], 18_423_653.0)
        self.assertEqual(series["ab_conventional_crude_production"]["2026-03"], 2_700_003.0)
        self.assertEqual(series["ab_condensate_production"]["2026-03"], 450_003.0)
        self.assertAlmostEqual(
            series["ab_oil_total_production"]["2026-07"], 2_700_007.0 + 450_007.0 + 18_423_653.0
        )
        # Aug-Dec are zero-filled by the publisher and must not become observations.
        self.assertNotIn("2026-08", series["ab_oil_total_production"])
        self.assertNotIn("2026-12", series["ab_oil_total_production"])

    def test_month_at_or_after_run_date_month_is_unpublished_even_if_nonzero(self) -> None:
        body = _aer_workbook(
            year=2026,
            run_date="15 July 2026",
            conventional={m: 10.0 for m in range(1, 8)},
            condensate={m: 10.0 for m in range(1, 8)},
            oil_sands={m: 10.0 for m in range(1, 8)},
        )
        parsed = parse_aer_st3_oil_workbook(body)
        self.assertEqual(max(parsed["series"]["ab_oil_total_production"]), "2026-06")

    def test_disposition_block_does_not_overwrite_supply_rows(self) -> None:
        parsed = parse_aer_st3_oil_workbook(_current_2026())
        self.assertNotEqual(parsed["series"]["ab_oil_total_production"]["2026-01"], 999.0)

    def test_non_workbook_body_raises(self) -> None:
        with self.assertRaises(CanadaEnergyError):
            parse_aer_st3_oil_workbook(b"<html>Access Denied</html>")
        with self.assertRaises(CanadaEnergyError):
            parse_aer_st3_oil_workbook(b"%PDF-1.7 not a workbook")


class TestStatcanHistoryParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(WDS_GAS_FIXTURE.read_text(encoding="utf-8"))

    def test_history_points_keep_release_date_units_and_revision_flags(self) -> None:
        points = statcan_vector_history_points(
            self.payload, 1864626177, source_url="https://example.invalid/2510008601", uom_label="cubic metres"
        )
        self.assertEqual(len(points), 14)
        self.assertEqual(points[0]["period"], "2025-06")
        self.assertEqual(points[-1]["period"], "2026-07")
        latest = points[-1]
        self.assertEqual(latest["transformation"], MONTHLY_LEVEL)
        self.assertEqual(latest["units"], "thousands of cubic metres")
        self.assertEqual(latest["release_date"], "2026-09-23")
        self.assertEqual(latest["revision_status"], "final")
        self.assertEqual(latest["statcan_scalar_factor_code"], 3)
        # Earlier points carry their own (earlier) publisher release date.
        self.assertEqual(points[-2]["release_date"], "2026-08-24")

    def test_symbol_codes_map_to_preliminary_and_revised(self) -> None:
        payload = copy.deepcopy(self.payload)
        pts = payload[0]["object"]["vectorDataPoint"]
        pts[-1]["symbolCode"] = 1
        pts[-2]["symbolCode"] = 3
        points = statcan_vector_history_points(payload, 1864626177, source_url="u", uom_label="cubic metres")
        self.assertEqual(points[-1]["revision_status"], "preliminary")
        self.assertEqual(points[-2]["revision_status"], "revised")

    def test_other_vector_ids_are_ignored(self) -> None:
        self.assertEqual(
            statcan_vector_history_points(self.payload, 999, source_url="u", uom_label="cubic metres"), []
        )


class TestCanadaEnergyAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.by_id = index_series_rows(self.catalog["series"])
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _spec(self, row_id: str) -> dict:
        return copy.deepcopy(self.by_id[row_id])

    def _mini_catalog(self, *specs: dict) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [copy.deepcopy(s) for s in specs]
        return cat

    def _run(self, cat: dict, opener, *, now: datetime = NOW) -> dict:
        return run_ingestion(
            mode="offline",
            countries=["CA"],
            catalog=cat,
            now=now,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )

    def _store(self) -> list[dict]:
        path = self.obs_dir / "ca.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))["observations"]

    # -- catalog hygiene -------------------------------------------------

    def test_catalog_rows_are_context_weight_zero_with_pinned_official_ids(self) -> None:
        for row_id in NEW_ROW_IDS:
            row = self.by_id[row_id]
            self.assertEqual(row["role"], "context", row_id)
            self.assertEqual(float(row["weight"]), 0.0, row_id)
            self.assertEqual(row["country"], "CA")
            self.assertEqual(row["transform"], MONTHLY_LEVEL)
            self.assertEqual(row["adapter"], "scripts.macro_ingestion.adapters.ca")
        for row_id in AER_ROW_IDS:
            row = self.by_id[row_id]
            self.assertEqual(row["retrieval_method"], "aer_st3_oil_workbook")
            self.assertEqual(row["derived_transforms"], [CALENDAR_DAY_RATE])
            self.assertEqual(row["units"], "cubic metres")
            self.assertTrue(str(row["series_id"]).startswith("AER_ST3_"))
            self.assertIn("series_key", row["source_selector"])
        gas = self.by_id["CA.Energy.gas_marketable_production"]
        self.assertEqual(gas["series_id"], "v1864626177")
        self.assertEqual(gas["derived_transforms"], [CALENDAR_DAY_RATE])
        self.assertEqual(gas["seasonal_adjustment"], False)
        for row_id in NEW_ROW_IDS[5:10]:
            row = self.by_id[row_id]
            self.assertEqual(row["retrieval_method"], "statcan_wds_vector_history", row_id)
            self.assertRegex(str(row["series_id"]), r"^v\d+$")
            self.assertTrue(row["seasonal_adjustment"], row_id)
            self.assertNotIn("derived_transforms", row, row_id)
        crea = self.by_id["CA.Housing.existing_home_sales"]
        self.assertEqual(crea["retrieval_method"], "unavailable")
        self.assertIsNone(crea["series_id"])
        self.assertEqual(crea["classification"], "proprietary_blocked")

    def test_existing_canonical_retail_row_is_untouched(self) -> None:
        retail = self.by_id["CA.Consumer.retail"]
        self.assertEqual(retail["role"], "scored")
        self.assertEqual(retail["series_id"], "v1446859483")
        self.assertEqual(retail["transform"], "mom_sa_pct")
        volume = self.by_id["CA.Consumer.retail_sales_volume"]
        self.assertNotEqual(volume["series_id"], retail["series_id"])
        self.assertNotEqual(volume["endpoint"], retail["endpoint"])

    # -- AER adapter ------------------------------------------------------

    def test_aer_payload_units_derivation_vintage_and_backfill(self) -> None:
        opener = _FixtureOpener({AER_CURRENT_URL: _current_2026(), AER_2025_URL: _archive_2025()})
        payload = fetch_series(self._spec("CA.Energy.ab_oil_sands_production"), opener=opener, now=NOW)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["vintage"], "aer_st3_run_date:2026-08-27")
        self.assertEqual(payload["units"], "cubic metres")
        self.assertEqual(payload["backfill_errors"], [])
        points = payload["points"]
        periods = sorted({p["period"] for p in points})
        self.assertEqual(periods[0], "2025-01")
        self.assertEqual(periods[-1], "2026-07")
        self.assertEqual(len(periods), 19)
        self.assertEqual(len(points), 38)
        by_key = {(p["period"], p["transformation"]): p for p in points}
        level = by_key[("2026-07", MONTHLY_LEVEL)]
        daily = by_key[("2026-07", CALENDAR_DAY_RATE)]
        self.assertEqual(level["value"], 18_423_653.0)
        self.assertEqual(level["units"], "cubic metres")
        self.assertEqual(level["release_date"], "2026-08-27")
        self.assertEqual(level["source_url"], AER_CURRENT_URL)
        self.assertAlmostEqual(daily["value"], 18_423_653.0 / 31.0)
        self.assertEqual(daily["units"], "cubic metres per calendar day")
        self.assertEqual(daily["derivation"]["days_in_month"], 31)
        self.assertEqual(daily["derivation"]["formula"], CALENDAR_DAY_RATE_FORMULA)
        archive_point = by_key[("2025-12", MONTHLY_LEVEL)]
        self.assertEqual(archive_point["source_url"], AER_2025_URL)
        self.assertEqual(archive_point["release_date"], "2026-02-27")

    def test_aer_daily_rate_removes_month_length_effect(self) -> None:
        opener = _FixtureOpener({AER_CURRENT_URL: _current_2026(), AER_2025_URL: _archive_2025()})
        payload = fetch_series(self._spec("CA.Energy.ab_oil_sands_production"), opener=opener, now=NOW)
        by_key = {(p["period"], p["transformation"]): p["value"] for p in payload["points"]}
        level_change = by_key[("2026-07", MONTHLY_LEVEL)] / by_key[("2026-06", MONTHLY_LEVEL)] - 1.0
        daily_change = by_key[("2026-07", CALENDAR_DAY_RATE)] / by_key[("2026-06", CALENDAR_DAY_RATE)] - 1.0
        self.assertAlmostEqual((1.0 + daily_change) * (31.0 / 30.0), 1.0 + level_change)
        self.assertLess(daily_change, level_change)

    def test_aer_backfill_failure_does_not_fail_current_year(self) -> None:
        opener = _FixtureOpener({AER_CURRENT_URL: _current_2026(), AER_2025_URL: None})
        payload = fetch_series(self._spec("CA.Energy.ab_condensate_production"), opener=opener, now=NOW)
        self.assertTrue(payload["ok"])
        self.assertEqual(min(p["period"] for p in payload["points"]), "2026-01")
        self.assertEqual(len(payload["backfill_errors"]), 1)
        self.assertEqual(payload["backfill_errors"][0]["url"], AER_2025_URL)

    def test_aer_four_rows_each_read_the_workbook_independently(self) -> None:
        opener = _FixtureOpener({AER_CURRENT_URL: _current_2026(), AER_2025_URL: _archive_2025()})
        cat = self._mini_catalog(*(self._spec(row_id) for row_id in AER_ROW_IDS))
        result = self._run(cat, opener)
        self.assertEqual({row["status"] for row in result["rows"]}, {"new_observation"})
        self.assertEqual(opener.calls.count(AER_CURRENT_URL), 4)
        self.assertEqual(opener.calls.count(AER_2025_URL), 4)
        rows = self._store()
        self.assertEqual(len(rows), 4 * 19 * 2)
        self.assertEqual(
            {r["series_id"] for r in rows},
            {
                "AER_ST3_OIL_TOTAL_PRODUCTION_M3",
                "AER_ST3_OIL_SANDS_TOTAL_PRODUCTION_M3",
                "AER_ST3_CONVENTIONAL_CRUDE_PRODUCTION_M3",
                "AER_ST3_CONDENSATE_PRODUCTION_M3",
            },
        )

    def test_aer_source_failure_writes_nothing_and_is_not_carried_forward(self) -> None:
        spec = self._spec("CA.Energy.ab_oil_total_production")
        opener = _FixtureOpener({})
        payload = fetch_series(spec, opener=opener, now=NOW)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "source_failed")
        self.assertNotIn("points", payload)
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(result["rows"][0]["error"], "HTTP 503")
        self.assertEqual(self._store(), [])

    def test_aer_html_body_is_source_failed_not_an_observation(self) -> None:
        spec = self._spec("CA.Energy.ab_oil_total_production")
        opener = _FixtureOpener({AER_CURRENT_URL: b"<html><body>maintenance</body></html>"})
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(result["rows"][0]["error"], "aer_st3_body_not_xlsx")
        self.assertEqual(self._store(), [])

    def test_aer_challenge_body_is_license_gap(self) -> None:
        spec = self._spec("CA.Energy.ab_oil_total_production")
        opener = _FixtureOpener({AER_CURRENT_URL: b"<html>Access Denied - captcha</html>"})
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "license_gap")
        self.assertEqual(self._store(), [])

    def test_aer_runner_duplicate_prevention_then_revision(self) -> None:
        spec = self._spec("CA.Energy.ab_oil_sands_production")
        cat = self._mini_catalog(spec)
        opener = _FixtureOpener({AER_CURRENT_URL: _current_2026(), AER_2025_URL: _archive_2025()})

        first = self._run(cat, opener)
        self.assertEqual(first["rows"][0]["status"], "new_observation")
        rows = self._store()
        self.assertEqual(len(rows), 38)
        self.assertEqual(len({(r["series_id"], r["period"], r["transformation"]) for r in rows}), 38)
        self.assertEqual({r["series_id"] for r in rows}, {"AER_ST3_OIL_SANDS_TOTAL_PRODUCTION_M3"})

        second = self._run(cat, opener, now=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc))
        self.assertNotEqual(second["rows"][0]["status"], "new_observation")
        self.assertEqual(len(self._store()), 38)

        # Publisher restates July (>0.1%) in the next workbook.
        revised = _aer_workbook(
            year=2026,
            run_date="26 September 2026",
            conventional={m: 2_700_000.0 + m for m in range(1, 8)},
            condensate={m: 450_000.0 + m for m in range(1, 8)},
            oil_sands={1: 17_518_142.9, 2: 15_525_054.8, 3: 17_255_519.9, 4: 16_563_917.4, 5: 16_420_623.9, 6: 16_513_522.1, 7: 18_600_000.0},
        )
        opener_revised = _FixtureOpener({AER_CURRENT_URL: revised, AER_2025_URL: _archive_2025()})
        third = self._run(cat, opener_revised, now=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(third["rows"][0]["status"], "revision_applied")
        rows = self._store()
        self.assertEqual(len(rows), 40)
        july_levels = [r for r in rows if r["period"] == "2026-07" and r["transformation"] == MONTHLY_LEVEL]
        self.assertEqual([r["value"] for r in july_levels], [18_423_653.0, 18_600_000.0])
        self.assertEqual(july_levels[1]["earliest_release_vintage"], "2026-08-27")
        self.assertEqual(july_levels[1]["latest_release_vintage"], "2026-09-26")
        self.assertEqual(july_levels[1]["vintage"], "aer_st3_run_date:2026-09-26")
        july_daily = [r for r in rows if r["period"] == "2026-07" and r["transformation"] == CALENDAR_DAY_RATE]
        self.assertAlmostEqual(july_daily[-1]["value"], 18_600_000.0 / 31.0)
        # Unrevised June keeps a single row per transformation.
        june = [r for r in rows if r["period"] == "2026-06"]
        self.assertEqual(len(june), 2)

    # -- StatCan adapter ---------------------------------------------------

    def test_statcan_gas_runner_stores_level_and_daily_rate_history(self) -> None:
        spec = self._spec("CA.Energy.gas_marketable_production")
        opener = _FixtureOpener({STATCAN_WDS_URL: WDS_GAS_FIXTURE.read_bytes()})
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "new_observation")
        rows = self._store()
        self.assertEqual(len(rows), 28)
        levels = {r["period"]: r for r in rows if r["transformation"] == MONTHLY_LEVEL}
        daily = {r["period"]: r for r in rows if r["transformation"] == CALENDAR_DAY_RATE}
        self.assertEqual(len(levels), 14)
        self.assertEqual(levels["2026-07"]["units"], "thousands of cubic metres")
        self.assertEqual(levels["2026-07"]["release_date"], "2026-09-23")
        self.assertEqual(levels["2026-06"]["release_date"], "2026-08-24")
        self.assertAlmostEqual(daily["2026-07"]["value"], levels["2026-07"]["value"] / 31.0)
        self.assertAlmostEqual(daily["2026-06"]["value"], levels["2026-06"]["value"] / 30.0)
        self.assertEqual(daily["2026-07"]["units"], "thousands of cubic metres per calendar day")
        self.assertEqual(daily["2026-07"]["derivation"]["days_in_month"], 31)
        self.assertEqual(levels["2026-07"]["series_id"], "v1864626177")

        rerun = self._run(self._mini_catalog(spec), opener)
        self.assertNotEqual(rerun["rows"][0]["status"], "new_observation")
        self.assertEqual(len(self._store()), 28)

    def test_statcan_preliminary_restatement_is_revision_pending(self) -> None:
        spec = self._spec("CA.Energy.gas_marketable_production")
        opener = _FixtureOpener({STATCAN_WDS_URL: WDS_GAS_FIXTURE.read_bytes()})
        self._run(self._mini_catalog(spec), opener)
        payload = json.loads(WDS_GAS_FIXTURE.read_text(encoding="utf-8"))
        latest = payload[0]["object"]["vectorDataPoint"][-1]
        latest["value"] = float(latest["value"]) * 1.02
        latest["symbolCode"] = 1
        opener2 = _FixtureOpener({STATCAN_WDS_URL: json.dumps(payload).encode()})
        result = self._run(self._mini_catalog(spec), opener2, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(result["rows"][0]["status"], "revision_pending")
        july = [r for r in self._store() if r["period"] == "2026-07" and r["transformation"] == MONTHLY_LEVEL]
        self.assertEqual(len(july), 2)
        self.assertEqual(july[-1]["revision_status"], "preliminary")

    def test_statcan_activity_rows_have_no_daily_rate(self) -> None:
        payload = json.loads(WDS_GAS_FIXTURE.read_text(encoding="utf-8"))
        payload[0]["object"]["vectorId"] = 123263908
        for point in payload[0]["object"]["vectorDataPoint"]:
            point["scalarFactorCode"] = 6
        spec = self._spec("CA.Activity.real_manufacturing_sales")
        opener = _FixtureOpener({STATCAN_WDS_URL: json.dumps(payload).encode()})
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "new_observation")
        rows = self._store()
        self.assertEqual({r["transformation"] for r in rows}, {MONTHLY_LEVEL})
        self.assertEqual({r["units"] for r in rows}, {"millions of 2017 dollars"})
        self.assertEqual({r["series_id"] for r in rows}, {"v123263908"})

    def test_statcan_failure_and_invalid_json_write_nothing(self) -> None:
        spec = self._spec("CA.Energy.gas_marketable_production")
        result = self._run(self._mini_catalog(spec), _FixtureOpener({}))
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(self._store(), [])
        result = self._run(self._mini_catalog(spec), _FixtureOpener({STATCAN_WDS_URL: b"<html>oops</html>"}))
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(result["rows"][0]["error"], "statcan_wds_invalid_json")
        self.assertEqual(self._store(), [])

    def test_statcan_vector_missing_from_payload_is_source_failed(self) -> None:
        spec = self._spec("CA.Activity.crude_export_volume")
        opener = _FixtureOpener({STATCAN_WDS_URL: WDS_GAS_FIXTURE.read_bytes()})
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(self._store(), [])

    # -- gap row -----------------------------------------------------------

    def test_crea_gap_row_is_explicit_and_never_fetches(self) -> None:
        spec = self._spec("CA.Housing.existing_home_sales")
        opener = _FixtureOpener({})
        payload = fetch_series(spec, opener=opener, now=NOW)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "license_gap")
        self.assertIn("crea_existing_home_sales", payload["error"])
        self.assertEqual(opener.calls, [])
        result = self._run(self._mini_catalog(spec), opener)
        self.assertEqual(result["rows"][0]["status"], "license_gap")
        self.assertEqual(self._store(), [])

    # -- runner opt-in semantics -------------------------------------------

    def test_legacy_rows_ignore_point_transformation_without_opt_in(self) -> None:
        from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override

        spec = self._spec("CA.Labor.unemployment")
        self.assertNotIn("derived_transforms", spec)

        def fake_fetch(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "points": [
                    {"period": "2026-08", "value": 6.4, "transformation": "percent"},
                    {"period": "2026-08", "value": 0.21, "transformation": "calendar_day_rate"},
                ],
                "vintage": "latest_available:test",
                "raw_sha256": "abc",
                "http_status": 200,
            }

        register_adapter_override("CA", fake_fetch)
        try:
            self._run(self._mini_catalog(spec), _FixtureOpener({}))
        finally:
            clear_adapter_overrides()
        rows = self._store()
        # Both points collapse onto the row's own transform; the second one is
        # then a duplicate of the same (series, period, transform, sha) key.
        self.assertEqual({r["transformation"] for r in rows}, {"percent"})
        self.assertEqual(len(rows), 1)


class TestLiveSmokeEnergy(unittest.TestCase):
    """Live retrieval is opt-in (MACRO_INGESTION_LIVE_SMOKE=1) and records a report.

    Without the flag the committed report is validated: every official source
    must have been retrievable, and the July 2026 direction from the Sep 29
    analysis must be reproducible from the recorded points (not hard-coded).
    """

    def _mom(self, series: dict, transformation: str, later: str, earlier: str) -> float:
        by_key = {(p["period"], p["transformation"]): float(p["value"]) for p in series["tail_points"]}
        return by_key[(later, transformation)] / by_key[(earlier, transformation)] - 1.0

    def test_live_smoke_report(self) -> None:
        if os.environ.get("MACRO_INGESTION_LIVE_SMOKE") != "1":
            self.assertTrue(LIVE_REPORT_PATH.is_file(), "live_smoke_report_energy.json missing")
            report = json.loads(LIVE_REPORT_PATH.read_text(encoding="utf-8"))
            results = {entry["id"]: entry for entry in report["results"]}
            for row_id in NEW_ROW_IDS[:10]:
                self.assertTrue(results[row_id]["ok"], f"{row_id} was not retrievable live")
                self.assertGreaterEqual(results[row_id]["period_count"], 12, row_id)
                self.assertTrue(results[row_id]["raw_sha256"])
            self.assertEqual(results["CA.Housing.existing_home_sales"]["status"], "license_gap")
            oil_sands = results["CA.Energy.ab_oil_sands_production"]
            gas = results["CA.Energy.gas_marketable_production"]
            self.assertEqual(oil_sands["latest_period"], "2026-07")
            self.assertEqual(gas["latest_period"], "2026-07")
            # Oil sands: material rebound vs June once month length is removed.
            self.assertGreater(self._mom(oil_sands, CALENDAR_DAY_RATE, "2026-07", "2026-06"), 0.02)
            # Marketable gas: roughly flat / slightly softer on a daily-rate basis
            # even though the raw 31-day July total is higher than June.
            gas_daily = self._mom(gas, CALENDAR_DAY_RATE, "2026-07", "2026-06")
            gas_level = self._mom(gas, MONTHLY_LEVEL, "2026-07", "2026-06")
            self.assertGreater(gas_level, gas_daily)
            self.assertLessEqual(gas_daily, 0.005)
            self.assertGreaterEqual(gas_daily, -0.02)
            return

        catalog = load_catalog()
        by_id = index_series_rows(catalog["series"])
        report: dict = {
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "opener": "live_opener",
            "results": [],
        }
        for row_id in NEW_ROW_IDS:
            spec = by_id[row_id]
            payload = fetch_series(spec, opener=live_opener, now=datetime.now(timezone.utc), timeout=30)
            points = payload.get("points") or []
            periods = sorted({str(p["period"]) for p in points})
            tail = periods[-3:]
            entry = {
                "id": row_id,
                "series_id": spec.get("series_id"),
                "endpoint": spec.get("endpoint"),
                "retrieval_method": spec.get("retrieval_method"),
                "ok": bool(payload.get("ok")),
                "status": payload.get("status"),
                "error": payload.get("error"),
                "http_status": payload.get("http_status"),
                "raw_sha256": payload.get("raw_sha256"),
                "vintage": payload.get("vintage"),
                "units": (points[0].get("units") if points else spec.get("units")),
                "period_count": len(periods),
                "first_period": periods[0] if periods else None,
                "latest_period": periods[-1] if periods else None,
                "backfill_errors": payload.get("backfill_errors"),
                "tail_points": [
                    {k: p.get(k) for k in ("period", "transformation", "value", "units", "release_date", "revision_status")}
                    for p in points
                    if str(p["period"]) in tail
                ],
            }
            report["results"].append(entry)
        LIVE_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(LIVE_REPORT_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
