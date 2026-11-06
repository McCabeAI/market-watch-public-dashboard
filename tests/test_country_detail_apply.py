"""Glue test for injecting Country Detail into dashboard HTML."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.apply_country_detail import apply_country_detail, main
from scripts.country_detail.render import render_country_detail
from tests.test_country_detail_render import (
    SHARED_OBS_ID,
    synthetic_attention_populated,
    synthetic_projection,
    synthetic_score_state,
)

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "temperature_scores.json"

PAGE = """<!DOCTYPE html>
<html><head><style>
body { color: #111; }
</style></head><body>
<div class="cdetail us"><div class="temp-inputs"><div class="inner"><span>nested-us</span></div><p>US-STALE-SENTENCE-alpha</p></div><p>keep-us-tail</p></div>
<div class="cdetail ca"><div class="temp-inputs"><div><p>nested-ca</p></div><p>CA-STALE-SENTENCE-beta</p></div><p>keep-ca-tail</p></div>
</body></html>
"""

US_MEETING_DATES = (
    "2026-12-09",
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-09",
)


def _seed_policy_meeting_root(root: Path) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    for rel in ("country_registry.json", "policy_meetings.json"):
        src = ROOT / "data" / rel
        if src.is_file():
            shutil.copy2(src, data / rel)
    meetings = []
    for index, decision_date in enumerate(US_MEETING_DATES):
        meetings.append(
            {
                "instrument_id": f"PM:US:{decision_date}",
                "decision_date": decision_date,
                "effective_date": decision_date,
                "post_rate": 4.0 + index * 0.01,
                "incremental_bp": -5.0,
                "cumulative_bp": -5.0,
                "method": "identified" if index == 0 else "equal_step",
                "contracts": [{"product": "SR3", "expiry": "2026-12", "weight": 1.0}],
                "chg_1d_bp": 0.25,
                "chg_1w_bp": -0.5,
            }
        )
    prices = {
        "schema_version": 1,
        "construction_version": "policy_meeting_v1",
        "as_of": "2026-11-05",
        "banks": {
            "US": {
                "status": "ok",
                "anchor": 4.0,
                "basis_bp": 0.0,
                "futures_as_of": "2026-11-05T15:00:00Z",
                "calendar_retrieved_at": "2026-11-04",
                "meetings": meetings,
            }
        },
    }
    (data / "policy_meeting_prices.json").write_text(json.dumps(prices, indent=2) + "\n", encoding="utf-8")


class CountryDetailApplyTest(unittest.TestCase):
    def test_replaces_temp_inputs_without_touching_scores(self) -> None:
        before = hashlib.sha256(SCORES.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(PAGE, encoding="utf-8")
            main([str(path)])
            out = path.read_text(encoding="utf-8")
        after = hashlib.sha256(SCORES.read_bytes()).hexdigest()

        self.assertEqual(before, after)
        self.assertNotIn("US-STALE-SENTENCE-alpha", out)
        self.assertNotIn("CA-STALE-SENTENCE-beta", out)
        self.assertIn("keep-us-tail", out)
        self.assertIn("keep-ca-tail", out)
        self.assertIn('class="country-detail"', out)
        self.assertIn('data-country="US"', out)
        self.assertIn('data-country="CA"', out)
        self.assertIn('class="temp-dimension score-detail"', out)
        self.assertIn("Country Detail — mobile-first", out)
        self.assertEqual(out.count("Country Detail — mobile-first"), 1)
        self.assertNotIn('class="temp-inputs"', out)
        us = out.split('<div class="cdetail ca">', 1)[0]
        self.assertLess(us.find('class="score-compact"'), us.find('class="what-matters-now"'))
        self.assertLess(us.find('class="what-matters-now"'), us.find("keep-us-tail"))
        self.assertLess(us.find("keep-us-tail"), us.find('class="country-evidence"'))
        self.assertIn("country-detail-evidence-filter", out)
        self.assertIn("evidence-search", out)
        self.assertIn("addEventListener('input'", out)
        self.assertIn("addEventListener('click'", out)
        self.assertEqual(out.count("country-detail-evidence-filter"), 1)

    def test_policy_meeting_prices_render_in_country_detail(self) -> None:
        page = """<!DOCTYPE html><html><head><style></style></head><body>
<div class="cdetail us"><div class="temp-inputs"><p>US-STALE</p></div></div>
</body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_policy_meeting_root(root)
            from scripts.apply_country_detail import load_policy_meeting_view

            meetings = load_policy_meeting_view(root)
            section = render_country_detail(
                "US",
                synthetic_projection(SHARED_OBS_ID),
                synthetic_attention_populated(SHARED_OBS_ID),
                synthetic_score_state(),
                policy_meetings=meetings,
            )
            with mock.patch(
                "scripts.apply_country_detail.render_dashboard_sections",
                return_value={"US": section},
            ), mock.patch(
                "scripts.apply_country_detail.load_policy_state",
                return_value={"schema_version": 1, "countries": {}},
            ):
                out = apply_country_detail(page, root=root)
        self.assertIn('class="policy-meetings"', out)
        for decision_date in US_MEETING_DATES:
            self.assertIn(decision_date, out)
        self.assertIn("policy-meetings-source", out)
        self.assertIn("0.25", out)
        self.assertIn("Implied rate", out)
        start = out.find('class="policy-meetings"')
        end = out.find("</details>", start) + len("</details>")
        self.policy_meetings_snippet = out[start:end]

    def test_overlay_copy_isolates_policy_prices_without_a_launch(self) -> None:
        import hashlib
        import json

        from scripts.country_registry import history_files
        from scripts.market_watch_launch.research_pages import LAUNCHES_REL, prepare_overlay

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "scripts").mkdir(parents=True)
            data = source / "data"
            prices = data / "policy_meeting_prices.json"
            prices.parent.mkdir(parents=True)
            payload = '{"schema_version":1,"as_of":"2026-11-05","banks":{"US":{"meetings":[]}}}\n'
            prices.write_text(payload, encoding="utf-8")
            hist = data / "temperature_history"
            hist.mkdir()
            lineage = source / LAUNCHES_REL / "mwl-test" / "lineage" / "history"
            lineage.mkdir(parents=True)
            scores = lineage.parent / "temperature_scores.json"
            scores.write_text("{}\n", encoding="utf-8")
            for name in history_files().values():
                (lineage / name).write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(scores.read_bytes()).hexdigest()
            work = prepare_overlay(
                source,
                Path(tmp) / "work",
                {"launch_id": "mwl-test", "score_state_sha256": digest},
            )
            overlay = work / "data" / "policy_meeting_prices.json"
            self.assertTrue(overlay.is_file())
            self.assertFalse(overlay.is_symlink())
            overlay.write_text('{"overlay_only":true}\n', encoding="utf-8")
            self.assertEqual(prices.read_text(encoding="utf-8"), payload)
            self.assertNotIn("overlay_only", prices.read_text(encoding="utf-8"))

    def test_prepare_overlay_policy_prices_copy_does_not_mutate_source(self) -> None:
        from scripts.market_watch_launch import research_pages as rp

        prices_path = ROOT / "data" / "policy_meeting_prices.json"
        created = False
        if not prices_path.is_file():
            created = True
            prices_path.write_text('{"schema_version":1,"as_of":"2026-11-05","banks":{}}\n', encoding="utf-8")
        before = prices_path.read_bytes()
        try:
            contract = rp.research_contract(
                ROOT,
                launch_id="mwl-20261027T093212Z-9512d95d",
                now=datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc),
            )
        except Exception as exc:
            if created:
                prices_path.unlink(missing_ok=True)
            self.skipTest(f"research contract unavailable: {exc}")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                work = rp.prepare_overlay(ROOT, Path(tmp) / "work", contract)
                overlay = work / "data" / "policy_meeting_prices.json"
                self.assertTrue(overlay.is_file())
                self.assertFalse(overlay.is_symlink())
                overlay.write_text('{"overlay_only":true}\n', encoding="utf-8")
                self.assertEqual(prices_path.read_bytes(), before)
        finally:
            if created:
                prices_path.unlink(missing_ok=True)
            elif prices_path.read_bytes() != before:
                prices_path.write_bytes(before)


if __name__ == "__main__":
    unittest.main()
