"""Nov 9 2026 launch: CME publication clock and ICE delayed-last boundaries."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.rates.cme_session import (
    cme_publication_status,
    classify_mark_freshness,
    expected_session_if_published,
    latest_publishable_official_session,
    stamp_cme_publication_fields,
)
from scripts.rates.short_rate_isolation import collect_usd_eur_short_rates
from scripts.rates.short_rate_store import load_store, remember_fresh, save_store

NY = ZoneInfo("America/New_York")
NOV6 = date(2026, 11, 6)
NOV7 = date(2026, 11, 7)
NOV8 = date(2026, 11, 8)
NOV9 = date(2026, 11, 9)
LAUNCH_NOW = datetime(2026, 11, 9, 5, 37, 50, tzinfo=NY)


class CmePublicationClockTests(unittest.TestCase):
    def test_friday_saturday_sunday_publishable_is_nov6(self) -> None:
        for day in (NOV6, NOV7, NOV8):
            self.assertEqual(
                latest_publishable_official_session(today=day, now=None),
                NOV6,
            )

    def test_monday_morning_publishable_is_friday_not_monday(self) -> None:
        self.assertEqual(
            latest_publishable_official_session(today=NOV9, now=LAUNCH_NOW),
            NOV6,
        )
        self.assertEqual(expected_session_if_published(NOV9), NOV9)

    def test_nov6_official_at_launch_status_dict(self) -> None:
        status = cme_publication_status(
            curve_key="ESR",
            observation=NOV6,
            today=NOV9,
            mark_kind="official_settlement",
            trade_date_verified=True,
            now=LAUNCH_NOW,
        )
        self.assertEqual(status["observed_session"], "2026-11-06")
        self.assertEqual(status["expected_session_if_published"], "2026-11-09")
        self.assertEqual(status["publishable_session"], "2026-11-06")
        self.assertTrue(status["research_eligible"])
        self.assertFalse(status["execution_eligible"])
        self.assertTrue(status["latest_available_official"])
        self.assertEqual(status["stale_age_days"], 3)

    def test_monday_after_verified_monday_print_execution_eligible(self) -> None:
        monday_evening = datetime(2026, 11, 9, 19, 0, tzinfo=NY)
        status = cme_publication_status(
            curve_key="ESR",
            observation=NOV9,
            today=NOV9,
            mark_kind="official_settlement",
            trade_date_verified=True,
            now=monday_evening,
        )
        self.assertTrue(status["execution_eligible"])
        self.assertTrue(status["research_eligible"])
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=NOV9,
                today=NOV9,
                mark_kind="official_settlement",
                trade_date_verified=True,
                now=monday_evening,
            ),
            "fresh",
        )

    def test_nov6_not_labeled_as_nov9_settlement(self) -> None:
        rows = [
            {
                "observation_date": "2026-11-06",
                "as_of": "2026-11-06",
                "trade_date_verified": True,
            }
        ]
        _fresh, status = stamp_cme_publication_fields(
            curve_key="ESR",
            rows=rows,
            today=NOV9,
            mark_kind="official_settlement",
            trade_date_verified=True,
            now=LAUNCH_NOW,
        )
        self.assertEqual(rows[0]["observation_date"], "2026-11-06")
        self.assertEqual(status["expected_session_if_published"], "2026-11-09")
        self.assertNotEqual(rows[0]["observation_date"], "2026-11-09")
        self.assertEqual(rows[0]["session_expected"], "2026-11-09")

    def test_date_only_monday_does_not_publish_monday(self) -> None:
        self.assertEqual(
            latest_publishable_official_session(today=NOV9, now=None),
            NOV6,
        )
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=NOV9,
                today=NOV9,
                mark_kind="official_settlement",
                trade_date_verified=True,
                now=None,
            ),
            "stale",
        )

    def test_ice_delayed_last_not_official(self) -> None:
        status = cme_publication_status(
            curve_key="EURIBOR",
            observation=NOV6,
            today=NOV9,
            mark_kind="delayed_last",
            trade_date_verified=False,
            now=LAUNCH_NOW,
        )
        self.assertFalse(status["latest_available_official"])
        self.assertFalse(status["execution_eligible"])
        self.assertFalse(status["research_eligible"])


def _esr_rows(obs: str = "2026-11-06") -> list[dict]:
    return [
        {
            "expiry": "2026-12",
            "implied_rate": 2.0,
            "observation_date": obs,
            "as_of": obs,
            "mark_kind": "official_settlement",
            "trade_date_verified": True,
        }
    ]


class CachePreserveOnFetchFail(unittest.TestCase):
    def test_failed_fetch_leaves_store_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "short_rate_last_good.json"
            seeded = remember_fresh(
                {"version": 1, "curves": {}},
                "ESR",
                rows=_esr_rows(),
                as_of="2026-11-06",
                source="seed",
                source_url="https://seed",
                mark_kind="official_settlement",
                provenance={},
            )
            save_store(store_path, seeded)
            before = store_path.read_bytes()
            digest = hashlib.sha256(before).hexdigest()

            def boom(*_a, **_k):
                raise ValueError("network down")

            collect_usd_eur_short_rates(
                today=NOV9,
                fetch_bytes=lambda *a, **k: b"",
                benchmark_usd=3.85,
                benchmark_eur=2.15,
                store_path=store_path,
                acquire_sr1=boom,
                acquire_sr3=boom,
                acquire_esr=boom,
                now=LAUNCH_NOW,
            )
            after = store_path.read_bytes()
            self.assertEqual(hashlib.sha256(after).hexdigest(), digest)
            self.assertEqual(json.loads(after.decode()), load_store(store_path))


if __name__ == "__main__":
    unittest.main()
