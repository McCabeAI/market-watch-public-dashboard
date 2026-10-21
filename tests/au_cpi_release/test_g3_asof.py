"""G3: as-of filtering and the post-release snapshot refusal."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.au_cpi_release.contract import Observation, Snapshot
from scripts.au_cpi_release.sources.acquire import (
    InformationSetError,
    load_snapshot,
    require_pre_release_view,
    visible,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "au_cpi_release"
    / "fixtures"
    / "pre_2026-10-28"
    / "snapshot.json"
)
RELEASE = "2026-10-28T11:30:00+11:00"


class AsOfTests(unittest.TestCase):
    def test_future_print_is_invisible_before_release_and_does_not_change_the_set(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        fake = Observation(
            canonical_id="headline_nsa_mom",
            period="2026-09",
            value=9.9,
            published_at=RELEASE,
            source_id="injected",
            regime="complete_monthly_cpi",
            vintage="abs_api",
        )
        injected = Snapshot(
            observations=snapshot.observations + (fake,),
            source_records=snapshot.source_records,
            retrieved_at=snapshot.retrieved_at,
            notes=snapshot.notes,
            schema_version=snapshot.schema_version,
        )
        before = visible(snapshot, "2026-10-27")
        after_injection = visible(injected, "2026-10-27")
        self.assertEqual(before, after_injection)
        self.assertFalse(any(obs.period == "2026-09" and obs.value == 9.9 for obs in after_injection))
        self.assertTrue(
            any(
                obs.canonical_id == "headline_nsa_index"
                and obs.period == "2026-08"
                and obs.vintage == "abs_api"
                for obs in after_injection
            )
        )
        on_release = visible(injected, RELEASE)
        self.assertTrue(any(obs.period == "2026-09" and obs.value == 9.9 for obs in on_release))

    def test_snapshot_retrieved_at_release_is_refused(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        require_pre_release_view(snapshot, RELEASE)
        late = Snapshot(
            observations=snapshot.observations,
            source_records=snapshot.source_records,
            retrieved_at=RELEASE,
            notes=snapshot.notes,
            schema_version=snapshot.schema_version,
        )
        with self.assertRaises(InformationSetError) as caught:
            require_pre_release_view(late, RELEASE)
        self.assertEqual(caught.exception.code, "snapshot_retrieved_after_release")
        later = Snapshot(
            observations=snapshot.observations,
            source_records=snapshot.source_records,
            retrieved_at="2026-10-28T11:30:01+11:00",
            notes=snapshot.notes,
            schema_version=snapshot.schema_version,
        )
        with self.assertRaises(InformationSetError):
            require_pre_release_view(later, RELEASE)

    def test_fixture_has_no_september_2026_api_print(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        leaked = [
            obs
            for obs in snapshot.observations
            if obs.vintage == "abs_api" and obs.period == "2026-09" and obs.canonical_id.startswith("headline")
        ]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
