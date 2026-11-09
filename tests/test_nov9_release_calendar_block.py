"""Nov 9 pre-freeze release calendar block regression (no network)."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.evidence_calendar import build_evidence_calendar
from scripts.policy_calendar import BANK_CODES

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 11, 9, 5, 37, 50, tzinfo=ET)
IMMUTABLE_SNAPSHOT = (
    ROOT
    / "data/overnight/runs/overnight-20261109/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_PACKET_SHA256 = "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"

_NEAR_TERM_FAMILIES = frozenset(
    {
        "us_empsit",
        "us_cpi",
        "ca_lfs",
        "ca_cpi",
        "au_labour_force",
        "au_cpi",
        "ea_hicp",
        "jp_cpi",
    }
)


class Nov9ReleaseCalendarBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)

    def test_thirty_day_window_and_country_coverage(self) -> None:
        start = date.fromisoformat(self.block["window_start"])
        end = date.fromisoformat(self.block["window_end_exclusive"])
        self.assertEqual((end - start).days, 30)
        countries_with_events = {ev["country"] for ev in self.block["events"]}
        gap_countries = {g["country"] for g in self.block["coverage_gaps"] if g.get("country")}
        for ev in self.block["events"]:
            local = date.fromisoformat(ev["local_date"])
            self.assertGreaterEqual(local, start)
            self.assertLess(local, end)
        for cc in ("US", "CA", "EA", "AU", "NZ", "JP"):
            self.assertTrue(
                cc in countries_with_events or cc in gap_countries,
                msg=f"{cc} has neither events nor an explicit gap",
            )

    def test_policy_next_five_or_gap_per_bank(self) -> None:
        policy = self.block["policy_decisions"]
        for bank in BANK_CODES:
            self.assertIn(bank, policy)
            block = policy[bank]
            count = block.get("count", len(block.get("decisions") or []))
            if count:
                self.assertLessEqual(count, 5)
                self.assertGreaterEqual(count, 1)
            else:
                reasons = [
                    g["reason"]
                    for g in self.block["coverage_gaps"]
                    if g.get("kind") == "policy_calendar" and g.get("country") == bank
                ]
                self.assertTrue(reasons, msg=f"expected policy gap for {bank}")

    def test_grouped_same_release_and_alias_dedupe(self) -> None:
        empsit = [e for e in self.block["events"] if e.get("event_family") == "us_empsit"]
        self.assertTrue(empsit)
        payroll_ids = set(empsit[0].get("series_ids") or [])
        self.assertIn("US.Labor.payrolls", payroll_ids)
        self.assertIn("US.Labor.unemployment", payroll_ids)
        self.assertEqual(len(empsit), 1)
        cpi = [e for e in self.block["events"] if e.get("event_family") == "us_cpi"]
        self.assertEqual(len(cpi), 1)
        headline_ids = set(cpi[0].get("series_ids") or [])
        self.assertGreater(len(headline_ids), 1)

    def test_tba_event_retained(self) -> None:
        tba = [e for e in self.block["events"] if e.get("clock") == "tba"]
        self.assertTrue(tba, "expected at least one TBA release in the Nov 9 window")

    def test_post_as_of_retrieved_row_excluded_and_gapped(self) -> None:
        cache_path = ROOT / "data/dashboard_repair/official_release_cache.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(cache)
        us_events = mutated["countries"]["US"]["events"]
        target = next(e for e in us_events if e.get("event_family") == "us_empsit" and e["local_date"] == "2026-12-04")
        post = "2026-11-10T12:00:00Z"
        target["fetched_at"] = post
        import tempfile
        from scripts.dashboard_repair import evidence_calendar as ec_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir) / "official_release_cache.json"
            tmp.write_text(json.dumps(mutated), encoding="utf-8")
            original = ec_mod.fetch_official_schedules

            def _fetch(now, **kwargs):
                kwargs["cache_path"] = tmp
                return original(now, **kwargs)

            ec_mod.fetch_official_schedules = _fetch  # type: ignore[method-assign]
            try:
                block = build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)
            finally:
                ec_mod.fetch_official_schedules = original  # type: ignore[method-assign]
        empsit_dates = [e["local_date"] for e in block["events"] if e.get("event_family") == "us_empsit"]
        self.assertNotIn("2026-12-04", empsit_dates)
        leak_gaps = [
            g
            for g in block["coverage_gaps"]
            if g.get("reason") == "schedule row retrieved_at is after as_of"
            and g.get("event_family") == "us_empsit"
        ]
        self.assertTrue(leak_gaps)

    def test_deterministic_content_hash(self) -> None:
        other = build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)
        self.assertEqual(self.block["content_hash"], other["content_hash"])

    def test_immutable_evidence_snapshot_unchanged(self) -> None:
        self.assertTrue(IMMUTABLE_SNAPSHOT.is_file())
        before_bytes = IMMUTABLE_SNAPSHOT.read_bytes()
        snapshot = json.loads(before_bytes.decode("utf-8"))
        self.assertEqual(snapshot.get("packet_sha256"), EXPECTED_PACKET_SHA256)
        before_mtime = IMMUTABLE_SNAPSHOT.stat().st_mtime_ns
        build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)
        after_mtime = IMMUTABLE_SNAPSHOT.stat().st_mtime_ns
        self.assertEqual(before_mtime, after_mtime)
        self.assertEqual(IMMUTABLE_SNAPSHOT.read_bytes(), before_bytes)

    def test_near_term_jobs_cpi_present(self) -> None:
        families = {e["event_family"] for e in self.block["events"]}
        missing = _NEAR_TERM_FAMILIES - families
        self.assertFalse(
            missing,
            msg=f"missing near-term official families: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
