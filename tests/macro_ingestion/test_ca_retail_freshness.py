"""Canada retail sales reaches the Consumer score once StatCan publishes it.

From late September 2026 every launch fetched newer months of table
20-10-0056 (vector v1446859483), but the merge skipped them as
``methodology_break_guard``: the series' only break is keyed by ``date``, not
``period``. The Consumer score stayed on June 2026.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import ca
from scripts.macro_ingestion.canonical_bridge import _append_row, _methodology_blocks, merge_scored_points
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.score_bridge import points_from_observation_stores
from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
)

PAYLOAD = ROOT / "tests/macro_ingestion/fixtures/ca/wds_retail_v1446859483_20261028.json"
HISTORY_DIR = ROOT / "data/temperature_history"
SCORES_PATH = ROOT / "data/temperature_scores.json"
LAUNCH_OBS = ROOT / "data/market_watch_launches/mwl-20261028T092641Z-4c970004/ingestion/observations"
CHECKED_AT = "2026-10-28T09:26:41Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retail_spec() -> dict:
    return next(row for row in load_catalog()["series"] if row["id"] == "CA.Consumer.retail")


def _adapter_points() -> list[dict]:
    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    return ca._statcan_points(_retail_spec(), ca._wds_points_by_vector(payload))


class MethodologyBreakKeyTests(unittest.TestCase):
    def _comp(self, breaks: list, last: str = "2026-06") -> dict:
        return {"methodology_breaks": breaks, "observations": [{"reference_period": last, "value": 1.0}]}

    def test_date_keyed_break_already_continued_does_not_block(self) -> None:
        comp = self._comp([{"date": "2023-03-24", "note": "table replaced"}])
        self.assertFalse(_methodology_blocks(comp, "2026-08"))

    def test_date_keyed_break_still_blocks_a_print_at_or_before_it(self) -> None:
        comp = self._comp([{"date": "2023-03-24"}], last="2023-02")
        self.assertTrue(_methodology_blocks(comp, "2023-03"))
        self.assertTrue(_methodology_blocks(comp, "2023-04"))

    def test_date_keyed_break_bounds_quarterly_series(self) -> None:
        comp = self._comp([{"date": "2025-02-10"}], last="2025-Q2")
        self.assertTrue(_methodology_blocks(comp, "2025-Q1"))
        self.assertFalse(_methodology_blocks(comp, "2025-Q3"))

    def test_break_without_period_or_date_still_blocks(self) -> None:
        # US ISM rows carry only a note; that stays fail-closed.
        self.assertTrue(_methodology_blocks(self._comp([{"note": "harvested from press"}]), "2026-09"))
        self.assertTrue(_methodology_blocks(self._comp([{"date": "March 2023"}]), "2026-09"))

    def test_committed_ca_retail_break_no_longer_blocks(self) -> None:
        history = load_history(HISTORY_DIR)
        comp = history["CA"]["components"]["Consumer.retail"]
        self.assertEqual([set(b) for b in comp["methodology_breaks"]], [{"date", "note"}])
        self.assertFalse(_methodology_blocks(comp, "2026-08"))


class AppendRowTemplateTests(unittest.TestCase):
    def test_new_print_does_not_inherit_release_date_or_level(self) -> None:
        template = {
            "reference_period": "2026-06",
            "value": 0.6,
            "release_date": "2026-08-21",
            "release_date_status": "recorded",
            "raw_level": 74282968.0,
            "series_id": "retail_total_sa_v1446859483",
            "transformation": "mom_sa_pct",
            "publisher": "Statistics Canada",
            "units": "percent",
        }
        rows: list[dict] = []
        common = dict(series_id="retail_total_sa_v1446859483", transformation="mom_sa_pct", checked_at=CHECKED_AT, cal_as_of="2026-09-21")
        _append_row(rows, template=template, point={}, period="2026-07", value=-0.81, **common)
        _append_row(rows, template=template, point={"release_date": "2026-10-23"}, period="2026-08", value=1.2, **common)
        july, august = rows
        for key in ("release_date", "release_date_status", "raw_level"):
            self.assertNotIn(key, july)
        self.assertEqual(august["release_date"], "2026-10-23")
        self.assertEqual(july["publisher"], "Statistics Canada")
        self.assertEqual(template["release_date"], "2026-08-21")


class AdapterWindowTests(unittest.TestCase):
    def test_emits_every_consecutive_month_with_release_date_on_newest_only(self) -> None:
        points = _adapter_points()
        self.assertEqual([p["period"] for p in points], ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])
        values = {p["period"]: p["value"] for p in points}
        self.assertAlmostEqual(values["2026-07"], (73684586.0 / 74289929.0 - 1) * 100)
        self.assertAlmostEqual(values["2026-08"], (74567349.0 / 73684586.0 - 1) * 100)
        self.assertEqual(points[-1]["release_date"], "2026-10-23")
        # Older months carry a revision vintage date, not their first release.
        self.assertTrue(all(p.get("release_date") is None for p in points[:-1]))

    def test_month_gap_is_not_bridged(self) -> None:
        levels = [("2026-04", 100.0), ("2026-05", 101.0), ("2026-07", 103.0)]
        self.assertEqual([p for p, _ in ca._mom_pct_series_from_levels(levels)], ["2026-05"])

    def test_other_transforms_still_emit_latest_only(self) -> None:
        spec = {"series_id": "v2062815", "transform": "percent", "endpoint": "https://example.invalid"}
        payload = json.loads((ROOT / "tests/macro_ingestion/fixtures/ca/wds_unemployment_v2062815.json").read_text())
        self.assertEqual(len(ca._statcan_points(spec, ca._wds_points_by_vector(payload))), 1)


class RetailReachesConsumerScoreTests(unittest.TestCase):
    """Replay the 28 Oct 2026 fetch through the real store-to-history path."""

    def _store_dir(self, tmp: Path) -> Path:
        obs = tmp / "observations"
        shutil.copytree(LAUNCH_OBS, obs)
        store = json.loads((obs / "ca.json").read_text(encoding="utf-8"))
        template = next(o for o in store["observations"] if o["series_id"] == "v1446859483")
        store["observations"] = [o for o in store["observations"] if o["series_id"] != "v1446859483"]
        for point in _adapter_points():
            row = dict(template)
            row.update(period=point["period"], value=point["value"], release_date=point.get("release_date"))
            store["observations"].append(row)
        (obs / "ca.json").write_text(json.dumps(store), encoding="utf-8")
        return obs

    def test_july_and_august_merge_and_only_ca_consumer_moves(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        base = load_history(HISTORY_DIR)
        before_sha = (_sha(HISTORY_DIR / "ca.json"), _sha(SCORES_PATH))
        with tempfile.TemporaryDirectory() as tmp:
            points = points_from_observation_stores(observations_dir=self._store_dir(Path(tmp)), checked_at=CHECKED_AT)
        histories = copy.deepcopy(base)
        result = merge_scored_points(histories, cal, points, checked_at=CHECKED_AT)
        self.assertEqual(
            [(a["id"], a["reference_period"]) for a in result["appended"]],
            [("CA.Consumer.retail", "2026-07"), ("CA.Consumer.retail", "2026-08")],
        )
        retail_skips = {s["reason"] for s in result["skipped"] if s["id"] == "CA.Consumer.retail"}
        # Revisions of already-scored Apr-Jun stay out (forward-only identity rule).
        self.assertEqual(retail_skips, {"partial_series_mismatch"})
        rows = {o["reference_period"]: o for o in histories["CA"]["components"]["Consumer.retail"]["observations"]}
        self.assertEqual(rows["2026-08"]["release_date"], "2026-10-23")
        self.assertNotIn("release_date", rows["2026-07"])
        self.assertEqual(rows["2026-06"]["value"], 0.6)

        before = build_score_state(cal, compute_state(cal, base))["countries"]
        after = build_score_state(cal, compute_state(cal, histories))["countries"]
        retail = after["CA"]["Consumer"]["component_state"]["retail"]
        self.assertEqual(retail["as_of"], "2026-08")
        self.assertEqual(retail["release_date"], "2026-10-23")
        self.assertEqual(retail["release_date_status"], "recorded")
        self.assertAlmostEqual(retail["transform_value"], (0.6 + rows["2026-07"]["value"] + rows["2026-08"]["value"]) / 3, places=3)
        changed = [
            (code, dim)
            for code, dims in before.items()
            for dim, spec in dims.items()
            if isinstance(spec, dict) and spec.get("level") != after[code][dim].get("level")
        ]
        self.assertEqual(changed, [("CA", "Consumer")])
        self.assertEqual(before_sha, (_sha(HISTORY_DIR / "ca.json"), _sha(SCORES_PATH)))


class CommittedScoresUnchangedTests(unittest.TestCase):
    """This repair changes ingestion only; the published score file is untouched."""

    def test_committed_scores_reproduce_from_committed_history(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        state = build_score_state(cal, compute_state(cal, load_history(HISTORY_DIR)))
        committed = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["countries"]["CA"]["Consumer"], committed["countries"]["CA"]["Consumer"])
        self.assertEqual(committed["countries"]["CA"]["Consumer"]["component_state"]["retail"]["as_of"], "2026-06")


if __name__ == "__main__":
    unittest.main()
