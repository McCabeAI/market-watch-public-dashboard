from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.apply_temperature_scores import (
    LINEAGE_ANCHOR_PHRASE,
    SCORE_KEY_TEXT,
    _patch_dimension,
    _patch_top_board,
    all_levels,
    apply_scores,
    load_state,
    temperature_class,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_V3 = Path(__file__).resolve().parent / "fixtures" / "temperature_scores_v3_minimal.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_V3.read_text(encoding="utf-8"))


def _mini_dashboard_html() -> str:
    parts = ['<div class="stitle">Temperature Board</div>']
    for key in ("us", "ca", "au", "nz"):
        block = (ROOT / "patch_v8" / f"{key}.html").read_text(encoding="utf-8")
        parts.append(f'<div class="cdetail {key}">\n{block}\n</div>')
    return "\n".join(parts)


class TemperatureScoresTest(unittest.TestCase):
    def test_v3_levels_from_fixture(self) -> None:
        state = _load_fixture()
        levels = all_levels(state)
        self.assertAlmostEqual(levels["US"]["Inflation"], 63.0)
        self.assertAlmostEqual(levels["CA"]["Activity"], 64.0)
        self.assertEqual(len(levels), 4)

    def test_top_board_shows_level_and_direction_arrows(self) -> None:
        state = _load_fixture()
        levels = all_levels(state)
        html = '<div class="stitle">Temperature Board</div><div>legacy cards</div>'
        out = _patch_top_board(html, levels, state)
        self.assertIn('data-score-overview="live"', out)
        self.assertIn("Live 1–100 Score Board", out)
        self.assertIn("Macro Snapshot", out)
        self.assertIn("Inf 63↑", out)
        self.assertIn("Con 46↓", out)
        self.assertNotIn("Temperature Board", out)

    def test_us_drawer_patches_level_impulse_and_lineage(self) -> None:
        state = _load_fixture()
        block = (ROOT / "patch_v8" / "us.html").read_text(encoding="utf-8")
        for dimension in ("Inflation", "Labor", "Activity", "Consumer"):
            spec = state["countries"]["US"][dimension]
            block = _patch_dimension(block, "US", dimension, spec["level"], spec, state)
        self.assertIn("63/100", block)
        self.assertIn("Warming · impulse +2", block)
        self.assertIn("Cooling · impulse -1.2", block)
        self.assertEqual(block.count(LINEAGE_ANCHOR_PHRASE), 4)
        self.assertNotIn("transition anchor", block.lower())

    def test_apply_scores_full_dashboard(self) -> None:
        state = _load_fixture()
        out = apply_scores(_mini_dashboard_html(), state)
        self.assertEqual(out.count('class="temp-dimension score-detail"'), 16)
        self.assertEqual(out.count(LINEAGE_ANCHOR_PHRASE), 16)
        self.assertEqual(out.count(SCORE_KEY_TEXT), 4)
        self.assertNotIn("Reindexed to 50 on 2026-09-17", out)
        self.assertNotIn("lineage-pinned", out)
        self.assertNotIn("contributing −", out)
        self.assertNotIn("contributing -1.0 point", out)
        self.assertIsNone(
            re.search(
                r"CONFIDENCE EVIDENCE · SCORED</span>.*?Michigan sentiment.*?47\.8",
                out,
                flags=re.S | re.I,
            )
        )
        self.assertIn("3.05", out)
        self.assertNotIn("≈2.4%", out)

    def test_apply_scores_real_state_us_inflation_hard_inputs(self) -> None:
        from scripts.trader_room.evidence import load_temperature_gauges

        state = load_state()
        out = apply_scores(_mini_dashboard_html(), state)
        self.assertNotIn("lineage-pinned", out)
        self.assertIn("3.0478", out)
        gauges = load_temperature_gauges(ROOT)
        us_inf = next(g for g in gauges if g["id"] == "temp:US:inflation")
        self.assertTrue(
            any(
                hi.get("coverage_contribution") is not None or hi.get("weight") is not None
                for hi in us_inf["hard_inputs"]
            )
        )
        self.assertNotEqual(us_inf["staleness"], "as_of:2026-09")

    def test_trader_room_staleness_uses_period_order_not_lexicographic(self) -> None:
        from scripts.trader_room.evidence import load_temperature_gauges

        gauges = load_temperature_gauges(ROOT)
        nz_con = next(g for g in gauges if g["id"] == "temp:NZ:consumer")
        self.assertEqual(nz_con["staleness"], "as_of:2026-Q1")

    def test_load_state_requires_v3_on_disk(self) -> None:
        try:
            load_state()
        except ValueError as exc:
            self.assertIn("version 3", str(exc))
        else:
            state = load_state()
            self.assertEqual(state.get("version"), 3)

    def test_temperature_bands(self) -> None:
        self.assertEqual(temperature_class(20), "cold")
        self.assertEqual(temperature_class(40), "cool")
        self.assertEqual(temperature_class(50), "neutral")
        self.assertEqual(temperature_class(80), "warm")
        self.assertEqual(temperature_class(81), "hot")

    def test_trader_room_load_temperature_gauges_v3(self) -> None:
        from scripts.trader_room.evidence import load_temperature_gauges

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            shutil.copy(FIXTURE_V3, root / "data" / "temperature_scores.json")
            gauges = load_temperature_gauges(root)
        self.assertEqual(len(gauges), 16)
        us_inf = next(g for g in gauges if g["id"] == "temp:US:inflation")
        self.assertEqual(us_inf["score"], 63.0)
        self.assertEqual(us_inf["direction"], "warming")
        self.assertEqual(us_inf["impulse"], 2.0)
        self.assertEqual(us_inf["source"], "data/temperature_scores.json")
        self.assertEqual(us_inf["hard_inputs"][0]["name"], "core_pce")
        self.assertEqual(us_inf["hard_inputs"][0]["coverage_contribution"], 1.0)
        self.assertEqual(us_inf["hard_inputs"][0]["weight"], 1.0)


if __name__ == "__main__":
    unittest.main()
