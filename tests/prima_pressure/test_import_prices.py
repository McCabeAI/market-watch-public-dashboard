"""Import merchandise price index collector (StatCan 12-10-0168-01)."""

from __future__ import annotations

import json
import os
import unittest
from datetime import date

from scripts.prima_pressure.bundle import _urllib_opener
from scripts.prima_pressure.import_prices import (
    IMPORT_PRICE_PRODUCT_ID,
    IMPORT_PRICE_SERIES,
    collect_import_prices,
)

RELEASE = "2026-11-04T08:30"


def _point(ref: str, value: float, *, release: str | None = RELEASE) -> dict:
    return {
        "refPer": ref,
        "value": value,
        "releaseTime": release,
        "frequencyCode": 6,
    }


def _block(vector_id: int, coordinate: str, points: list[dict]) -> dict:
    return {
        "status": "SUCCESS",
        "object": {
            "productId": IMPORT_PRICE_PRODUCT_ID,
            "coordinate": coordinate,
            "vectorId": vector_id,
            "frequencyCode": 6,
            "vectorDataPoint": points,
        },
    }


def _fixtures_opener(blocks: list[dict]):
    payload = json.dumps(blocks).encode("utf-8")

    def opener(url: str, data: bytes | None = None) -> bytes:
        return payload

    return opener


class TestImportPrices(unittest.TestCase):
    def test_pinned_series_vector(self) -> None:
        row = IMPORT_PRICE_SERIES[0]
        self.assertEqual(row["series_id"], "import_price_total")
        self.assertEqual(row["vector_id"], 1566914271)
        self.assertEqual(row["coordinate"], "1.1.2.2.1.2.1.0.0.0")

    def test_release_time_gating(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [
            _block(
                spec["vector_id"],
                spec["coordinate"],
                [
                    _point("2026-08-01", 150.2),
                    _point("2026-09-01", 151.5, release="2026-12-01T08:30"),
                ],
            )
        ]
        out = collect_import_prices(
            as_of=date(2026, 11, 10),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        series = out["series"]["import_price_total"]
        self.assertEqual(series["status"], "ok")
        self.assertEqual(len(series["observations"]), 1)
        self.assertEqual(series["latest_period"], "2026-08")

    def test_mom_and_3m_arithmetic(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [
            _block(
                spec["vector_id"],
                spec["coordinate"],
                [
                    _point("2026-06-01", 150.8),
                    _point("2026-07-01", 148.9),
                    _point("2026-08-01", 150.2),
                    _point("2026-09-01", 151.5),
                ],
            )
        ]
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        series = out["series"]["import_price_total"]
        self.assertAlmostEqual(series["mom_pct_decimal"], 151.5 / 150.2 - 1.0)
        self.assertAlmostEqual(series["change_3m_pct_decimal"], 151.5 / 150.8 - 1.0)

    def test_gap_yields_none_mom(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [
            _block(
                spec["vector_id"],
                spec["coordinate"],
                [
                    _point("2026-06-01", 150.8),
                    _point("2026-08-01", 150.2),
                ],
            )
        ]
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        series = out["series"]["import_price_total"]
        self.assertIsNone(series["mom_pct_decimal"])

    def test_stale_when_more_than_three_months_behind(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [
            _block(
                spec["vector_id"],
                spec["coordinate"],
                [_point("2026-05-01", 145.3)],
            )
        ]
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        series = out["series"]["import_price_total"]
        self.assertTrue(series["stale"])
        self.assertEqual(series["status"], "stale")
        self.assertEqual(out["status"], "partial")

    def test_opener_failure_unavailable(self) -> None:
        def bad_opener(url: str, data: bytes | None = None) -> bytes:
            raise OSError("network down")

        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=bad_opener,
            retrieved_at="2026-11-11T12:00:00",
        )
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("statcan_wds_fetch_failed", out["reason"])

    def test_empty_vector_unavailable(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [_block(spec["vector_id"], spec["coordinate"], [])]
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(
            out["series"]["import_price_total"]["reason"],
            "no_points_released_by_as_of",
        )

    def test_notes_document_missing_ex_energy_member(self) -> None:
        spec = IMPORT_PRICE_SERIES[0]
        blocks = [_block(spec["vector_id"], spec["coordinate"], [_point("2026-09-01", 151.5)])]
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_fixtures_opener(blocks),
            retrieved_at="2026-11-11T12:00:00",
        )
        joined = " ".join(out["notes"])
        self.assertIn("import_price_ex_energy", joined)
        self.assertIn("excluding energy", joined.lower())


@unittest.skipUnless(os.environ.get("PRIMA_LIVE_SMOKE") == "1", "set PRIMA_LIVE_SMOKE=1")
class TestImportPricesLiveSmoke(unittest.TestCase):
    def test_live_collect(self) -> None:
        out = collect_import_prices(
            as_of=date(2026, 11, 11),
            opener=_urllib_opener,
            retrieved_at="2026-11-11T13:20:00",
            latest_n=13,
        )
        self.assertIn(out["status"], ("ok", "partial"))
        series = out["series"]["import_price_total"]
        self.assertEqual(series["status"], "ok")
        self.assertIsNotNone(series["latest_value"])
        self.assertEqual(series["latest_period"], "2026-09")
        self.assertGreaterEqual(len(series["observations"]), 3)


if __name__ == "__main__":
    unittest.main()
