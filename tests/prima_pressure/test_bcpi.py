"""Tests for weekly BCPI Valet collector."""

from __future__ import annotations

import json
import os
import unittest
from datetime import date
from typing import Any

from scripts.prima_pressure.bcpi import (
    BCPI_WEEKLY_SERIES,
    change_since,
    collect_bcpi_weekly,
    _grouped_url,
)
from scripts.prima_pressure.bundle import _urllib_opener


def _fixture_payload(*, omit_mtls: bool = False, gap_week: bool = False) -> dict[str, Any]:
    """Valet-shaped fixture mirroring live grouped BCPI response (trimmed history)."""
    observations = [
        {"d": "2025-09-03", "W.BCNE": {"v": "500.00"}, "W.AGRI": {"v": "300.00"}, "W.MTLS": {"v": "900.00"}},
        {"d": "2025-09-10", "W.BCNE": {"v": "501.00"}, "W.AGRI": {"v": "301.00"}, "W.MTLS": {"v": "905.00"}},
        {"d": "2025-09-17", "W.BCNE": {"v": "502.00"}, "W.AGRI": {"v": "302.00"}, "W.MTLS": {"v": "910.00"}},
        {"d": "2025-09-24", "W.BCNE": {"v": "503.00"}, "W.AGRI": {"v": "303.00"}, "W.MTLS": {"v": "915.00"}},
        {"d": "2025-10-01", "W.BCNE": {"v": "504.00"}, "W.AGRI": {"v": "304.00"}, "W.MTLS": {"v": "920.00"}},
        {"d": "2025-10-08", "W.BCNE": {"v": "505.00"}, "W.AGRI": {"v": "305.00"}, "W.MTLS": {"v": "925.00"}},
        {"d": "2025-10-15", "W.BCNE": {"v": "506.00"}, "W.AGRI": {"v": "306.00"}, "W.MTLS": {"v": "930.00"}},
        {"d": "2025-10-22", "W.BCNE": {"v": "507.00"}, "W.AGRI": {"v": "307.00"}, "W.MTLS": {"v": "935.00"}},
        {"d": "2025-10-29", "W.BCNE": {"v": "508.00"}, "W.AGRI": {"v": "308.00"}, "W.MTLS": {"v": "940.00"}},
        {"d": "2025-11-05", "W.BCNE": {"v": "509.00"}, "W.AGRI": {"v": "309.00"}, "W.MTLS": {"v": "945.00"}},
        {"d": "2025-11-12", "W.BCNE": {"v": "510.00"}, "W.AGRI": {"v": "310.00"}, "W.MTLS": {"v": "950.00"}},
        {"d": "2025-11-19", "W.BCNE": {"v": "511.00"}, "W.AGRI": {"v": "311.00"}, "W.MTLS": {"v": "955.00"}},
        {"d": "2025-11-26", "W.BCNE": {"v": "512.00"}, "W.AGRI": {"v": "312.00"}, "W.MTLS": {"v": "960.00"}},
        {"d": "2025-12-03", "W.BCNE": {"v": "513.00"}, "W.AGRI": {"v": "313.00"}, "W.MTLS": {"v": "965.00"}},
        {"d": "2025-12-10", "W.BCNE": {"v": "520.00"}, "W.AGRI": {"v": "320.00"}, "W.MTLS": {"v": "1000.00"}},
        {"d": "2025-12-17", "W.BCNE": {"v": "530.00"}, "W.AGRI": {"v": "330.00"}, "W.MTLS": {"v": "1010.00"}},
        {"d": "2025-12-24", "W.BCNE": {"v": "535.00"}, "W.AGRI": {"v": "335.00"}, "W.MTLS": {"v": "1015.00"}},
        {"d": "2025-12-31", "W.BCNE": {"v": "540.00"}, "W.AGRI": {"v": "340.00"}, "W.MTLS": {"v": "1020.00"}},
        {"d": "2026-01-07", "W.BCNE": {"v": "545.00"}, "W.AGRI": {"v": "345.00"}, "W.MTLS": {"v": "1025.00"}},
        {"d": "2026-01-14", "W.BCNE": {"v": "550.00"}, "W.AGRI": {"v": "350.00"}, "W.MTLS": {"v": "1030.00"}},
    ]
    if gap_week:
        skip = {
            "2025-12-10",
            "2025-12-17",
            "2025-12-24",
            "2025-12-31",
        }
        observations = [o for o in observations if o["d"] not in skip]
    if omit_mtls:
        observations = [
            {k: v for k, v in row.items() if k != "W.MTLS"}
            for row in observations
        ]

    return {
        "terms": {"url": "https://www.bankofcanada.ca/terms/"},
        "seriesDetail": {
            sid: {
                "label": meta["label"],
                "description": meta["description"],
                "dimension": {"key": "d", "name": "Date"},
                "dateFormat": "weekly",
                "metadata": {},
            }
            for sid, meta in BCPI_WEEKLY_SERIES.items()
        },
        "observations": observations,
    }


class TestBcpiWeeklyCollector(unittest.TestCase):
    def _opener_from_fixture(self, payload: dict[str, Any]):
        body = json.dumps(payload).encode("utf-8")

        def opener(url: str, data: bytes | None = None) -> bytes:
            if data is not None:
                raise RuntimeError("unexpected POST")
            return body

        return opener

    def test_parse_and_four_week_change(self) -> None:
        payload = _fixture_payload()
        out = collect_bcpi_weekly(
            as_of=date(2026, 1, 14),
            opener=self._opener_from_fixture(payload),
            retrieved_at="2026-01-14T12:00:00",
            recent=30,
        )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["published_at"], None)
        bcne = out["series"]["W.BCNE"]
        self.assertEqual(bcne["series_id"], "W.BCNE")
        self.assertEqual(bcne["label"], BCPI_WEEKLY_SERIES["W.BCNE"]["label"])
        self.assertAlmostEqual(bcne["change_4w_pct_decimal"], 550.0 / 530.0 - 1.0)  # vs 2025-12-17
        self.assertIsNotNone(bcne["change_13w_pct_decimal"])
        self.assertFalse(bcne["stale"])

    def test_as_of_drops_future_rows(self) -> None:
        payload = _fixture_payload()
        out = collect_bcpi_weekly(
            as_of=date(2025, 12, 10),
            opener=self._opener_from_fixture(payload),
            retrieved_at="2025-12-10T12:00:00",
        )
        bcne = out["series"]["W.BCNE"]
        self.assertEqual(bcne["latest"]["date"], "2025-12-10")
        self.assertTrue(any("dropped" in n for n in out["notes"]))

    def test_gap_sets_four_week_change_none(self) -> None:
        payload = _fixture_payload(gap_week=True)
        out = collect_bcpi_weekly(
            as_of=date(2026, 1, 14),
            opener=self._opener_from_fixture(payload),
            retrieved_at="2026-01-14T12:00:00",
        )
        bcne = out["series"]["W.BCNE"]
        self.assertIsNone(bcne["change_4w_pct_decimal"])
        self.assertTrue(any("change_4w" in n for n in out["notes"]))

    def test_stale_when_latest_older_than_fourteen_days(self) -> None:
        payload = _fixture_payload()
        out = collect_bcpi_weekly(
            as_of=date(2026, 2, 1),
            opener=self._opener_from_fixture(payload),
            retrieved_at="2026-02-01T12:00:00",
        )
        self.assertTrue(out["series"]["W.BCNE"]["stale"])

    def test_partial_when_one_series_missing(self) -> None:
        payload = _fixture_payload(omit_mtls=True)
        out = collect_bcpi_weekly(
            as_of=date(2026, 1, 14),
            opener=self._opener_from_fixture(payload),
            retrieved_at="2026-01-14T12:00:00",
        )
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["series"]["W.MTLS"]["status"], "unavailable")

    def test_malformed_opener_returns_unavailable_without_raise(self) -> None:
        def bad_opener(url: str, data: bytes | None = None) -> bytes:
            raise ConnectionError("network down")

        out = collect_bcpi_weekly(
            as_of=date(2026, 1, 14),
            opener=bad_opener,
            retrieved_at="2026-01-14T12:00:00",
        )
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("reason", out)

    def test_change_since_anchor_selection(self) -> None:
        block = {
            "observations": [
                {"date": "2025-10-01", "value": 100.0},
                {"date": "2025-11-01", "value": 110.0},
                {"date": "2025-12-01", "value": 120.0},
            ]
        }
        mid = change_since(block, date(2025, 10, 15))
        self.assertEqual(mid["anchor_date"], "2025-10-01")
        self.assertAlmostEqual(mid["change_pct_decimal"], 0.2)

        before = change_since(block, date(2025, 9, 1))
        self.assertIsNone(before["anchor_date"])
        self.assertIsNone(before["change_pct_decimal"])


class TestBcpiLiveSmoke(unittest.TestCase):
    def test_live_smoke_collect(self) -> None:
        if os.environ.get("PRIMA_LIVE_SMOKE") != "1":
            self.skipTest("set PRIMA_LIVE_SMOKE=1 to run live BoC Valet smoke")
        out = collect_bcpi_weekly(
            as_of=date(2026, 11, 11),
            opener=_urllib_opener,
            retrieved_at="2026-11-11T12:00:00Z",
            recent=30,
        )
        self.assertIn(out["status"], ("ok", "partial"))
        for sid in BCPI_WEEKLY_SERIES:
            series = out["series"][sid]
            if series["status"] == "ok":
                self.assertTrue(series["observations"])
                self.assertEqual(series["series_id"], sid)
        self.assertEqual(out["source_url"], _grouped_url(30))


if __name__ == "__main__":
    unittest.main()
