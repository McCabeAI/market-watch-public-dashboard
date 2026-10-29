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

    def test_period_keyed_break_blocks_until_the_series_continues(self) -> None:
        unresolved = self._comp([{"period": "2024-01", "note": "base year"}], last="2023-12")
        self.assertTrue(_methodology_blocks(unresolved, "2024-01"))
        self.assertTrue(_methodology_blocks(unresolved, "2024-02"))
        continued = self._comp([{"period": "2024-01", "note": "base year"}], last="2024-03")
        self.assertTrue(_methodology_blocks(continued, "2024-01"))
        self.assertFalse(_methodology_blocks(continued, "2024-06"))

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
        self.assertEqual(points[-1]["revision_status"], "final")
        self.assertNotIn("latest_release_vintage", points[-1])
        # Earlier months share a later vintage. That date is a revision, not a first release.
        revised = {p["period"]: p for p in points[:-1]}
        self.assertEqual(revised["2026-04"]["latest_release_vintage"], "2026-09-24")
        self.assertEqual(revised["2026-07"]["latest_release_vintage"], "2026-10-23")
        self.assertEqual(revised["2026-06"]["latest_release_vintage"], "2026-10-23")
        for point in points[:-1]:
            self.assertIsNone(point.get("release_date"))
            self.assertEqual(point["revision_status"], "revised")
            self.assertNotEqual(point.get("latest_release_vintage"), point.get("release_date"))

    def test_month_gap_is_not_bridged(self) -> None:
        levels = [("2026-04", 100.0), ("2026-05", 101.0), ("2026-07", 103.0)]
        self.assertEqual([p for p, _ in ca._mom_pct_series_from_levels(levels)], ["2026-05"])

    def test_other_transforms_still_emit_latest_only(self) -> None:
        spec = {"series_id": "v2062815", "transform": "percent", "endpoint": "https://example.invalid"}
        payload = json.loads((ROOT / "tests/macro_ingestion/fixtures/ca/wds_unemployment_v2062815.json").read_text())
        self.assertEqual(len(ca._statcan_points(spec, ca._wds_points_by_vector(payload))), 1)


class RetailReachesConsumerScoreTests(unittest.TestCase):
    """Replay the 28 Oct 2026 fetch through the real store-to-history path."""

    def _store_dir(self, tmp: Path, *, reverse_retail: bool = False) -> Path:
        obs = tmp / "observations"
        shutil.copytree(LAUNCH_OBS, obs)
        store = json.loads((obs / "ca.json").read_text(encoding="utf-8"))
        template = next(o for o in store["observations"] if o["series_id"] == "v1446859483")
        store["observations"] = [o for o in store["observations"] if o["series_id"] != "v1446859483"]
        retail = []
        for point in _adapter_points():
            row = dict(template)
            row.update(
                period=point["period"],
                value=point["value"],
                release_date=point.get("release_date"),
                revision_status=point.get("revision_status"),
                latest_release_vintage=point.get("latest_release_vintage"),
            )
            retail.append(row)
        if reverse_retail:
            retail.reverse()
        store["observations"].extend(retail)
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
        self.assertEqual(result["appended"], [])
        retail_skips = {s["reason"] for s in result["skipped"] if s["id"] == "CA.Consumer.retail"}
        # Revisions of already-scored Apr-Jun stay out (forward-only identity rule).
        self.assertIn("partial_series_mismatch", retail_skips)
        self.assertIn("duplicate_value", retail_skips)
        rows = {o["reference_period"]: o for o in histories["CA"]["components"]["Consumer.retail"]["observations"]}
        self.assertEqual(len([p for p in rows if p in ("2026-07", "2026-08")]), 2)
        self.assertEqual(rows["2026-08"]["release_date"], "2026-10-23")
        self.assertEqual(rows["2026-08"]["revision_status"], "final")
        self.assertNotIn("latest_release_vintage", rows["2026-08"])
        # July's 2026-10-23 stamp is the August publication revising July, not July's first release.
        self.assertNotIn("release_date", rows["2026-07"])
        self.assertEqual(rows["2026-07"]["latest_release_vintage"], "2026-10-23")
        self.assertEqual(rows["2026-07"]["revision_status"], "revised")
        self.assertNotEqual(rows["2026-07"].get("release_date"), rows["2026-07"]["latest_release_vintage"])
        frozen = {
            o["reference_period"]: o
            for o in base["CA"]["components"]["Consumer.retail"]["observations"]
            if o["reference_period"] <= "2026-06"
        }
        for period, prior in frozen.items():
            self.assertEqual(rows[period], prior)
        self.assertEqual(rows["2026-06"]["value"], 0.6)
        self.assertEqual(rows["2026-06"]["release_date"], "2026-08-21")
        for code, hist in histories.items():
            if code == "CA":
                for key, comp in hist["components"].items():
                    if key != "Consumer.retail":
                        self.assertEqual(comp, base["CA"]["components"][key])
            else:
                self.assertEqual(hist, base[code])

        before = build_score_state(cal, compute_state(cal, base))["countries"]
        after = build_score_state(cal, compute_state(cal, histories))["countries"]
        retail = after["CA"]["Consumer"]["component_state"]["retail"]
        self.assertEqual(retail["as_of"], "2026-08")
        self.assertEqual(before["CA"]["Consumer"], after["CA"]["Consumer"])
        self.assertEqual(before_sha, (_sha(HISTORY_DIR / "ca.json"), _sha(SCORES_PATH)))

    def test_august_listed_before_july_still_includes_both(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        base = load_history(HISTORY_DIR)
        with tempfile.TemporaryDirectory() as tmp:
            points = points_from_observation_stores(
                observations_dir=self._store_dir(Path(tmp), reverse_retail=True),
                checked_at=CHECKED_AT,
            )
        histories = copy.deepcopy(base)
        result = merge_scored_points(histories, cal, points, checked_at=CHECKED_AT)
        self.assertEqual(result["appended"], [])
        rows = {o["reference_period"]: o for o in histories["CA"]["components"]["Consumer.retail"]["observations"]}
        self.assertEqual(len([p for p in rows if p in ("2026-07", "2026-08")]), 2)
        periods = [o["reference_period"] for o in histories["CA"]["components"]["Consumer.retail"]["observations"]]
        self.assertEqual(periods.count("2026-07"), 1)
        self.assertEqual(periods.count("2026-08"), 1)
        self.assertNotIn("release_date", rows["2026-07"])
        self.assertEqual(rows["2026-07"]["latest_release_vintage"], "2026-10-23")
        self.assertEqual(rows["2026-08"]["release_date"], "2026-10-23")
        self.assertEqual(rows["2026-06"]["value"], 0.6)
        self.assertEqual(rows["2026-06"]["release_date"], "2026-08-21")

    def test_pre_break_print_does_not_rewrite_stored_history(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = copy.deepcopy(load_history(HISTORY_DIR))
        retail = histories["CA"]["components"]["Consumer.retail"]
        before = copy.deepcopy(retail["observations"])
        point = {
            "country": "CA",
            "catalog_id": "CA.Consumer.retail",
            "role": "scored",
            "series_id": "retail_total_sa_v1446859483",
            "period": "2023-02",
            "value": 9.9,
            "transformation": "mom_sa_pct",
            "revision_status": "final",
            "release_date": "2023-04-21",
            "source_url": "https://example.invalid/ca/retail",
        }
        result = merge_scored_points(histories, cal, [point], checked_at=CHECKED_AT)
        self.assertEqual(result["appended"], [])
        self.assertEqual(
            [row for row in result["skipped"] if row["id"] == "CA.Consumer.retail"],
            [{"id": "CA.Consumer.retail", "reason": "methodology_break_guard"}],
        )
        self.assertEqual(retail["observations"], before)

    def test_store_keeps_revision_vintage_off_the_release_date(self) -> None:
        from scripts.macro_ingestion.vintage import append_observation

        store = {"country": "CA", "observations": []}
        append_observation(
            store,
            series_id="v1446859483",
            period="2026-07",
            transformation="mom_sa_pct",
            value=-0.81,
            raw_sha256="a" * 64,
            retrieved_at=CHECKED_AT,
            release_date=None,
            revision_status="revised",
            latest_release_vintage="2026-10-23",
        )
        append_observation(
            store,
            series_id="v1446859483",
            period="2026-08",
            transformation="mom_sa_pct",
            value=1.2,
            raw_sha256="b" * 64,
            retrieved_at=CHECKED_AT,
            release_date="2026-10-23",
            revision_status="final",
        )
        july, august = store["observations"]
        self.assertIsNone(july["release_date"])
        self.assertEqual(july["latest_release_vintage"], "2026-10-23")
        self.assertEqual(july["revision_status"], "revised")
        self.assertNotEqual(july["retrieved_at"][:10], july["latest_release_vintage"])
        self.assertEqual(august["release_date"], "2026-10-23")
        # A first release's current vintage is that same publication day.
        self.assertEqual(august["latest_release_vintage"], "2026-10-23")
        self.assertNotEqual(july["release_date"], august["release_date"])


class CommittedScoresUnchangedTests(unittest.TestCase):
    """This repair changes ingestion only; the published score file is untouched."""

    def test_committed_scores_reproduce_from_committed_history(self) -> None:
        before = {path.name: _sha(path) for path in HISTORY_DIR.glob("*.json")}
        before[SCORES_PATH.name] = _sha(SCORES_PATH)
        cal = load_calibration(CALIBRATION_PATH)
        state = build_score_state(cal, compute_state(cal, load_history(HISTORY_DIR)))
        committed = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["countries"]["CA"]["Consumer"], committed["countries"]["CA"]["Consumer"])
        self.assertEqual(committed["countries"]["CA"]["Consumer"]["component_state"]["retail"]["as_of"], "2026-08")
        after = {path.name: _sha(path) for path in HISTORY_DIR.glob("*.json")}
        after[SCORES_PATH.name] = _sha(SCORES_PATH)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
