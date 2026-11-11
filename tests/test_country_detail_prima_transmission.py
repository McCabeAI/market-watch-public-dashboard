"""Country Detail transmission v2 UI (offline)."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_detail._prima_section import render_prima_pressure_block
from scripts.country_detail.projection import build_projection
from scripts.country_detail.render import render_country_detail, _esc
from scripts.prima_pressure.presentation import build_presentation
from scripts.temperature_level import load_state
from scripts.prima_pressure.transmission import unavailable_transmission
from scripts.prima_pressure.transmission_contract import TRANSMISSION_PROVENANCE_LIVE

CSS_PATH = ROOT / "scripts/country_detail/country_detail.css"
TEMP_SCORES = ROOT / "data/temperature_scores.json"


def _prima_excerpt(html: str) -> str:
    return html.split('data-prima-pressure="ca"', 1)[1].split('class="evidence-block context"', 1)[0]


class CountryDetailPrimaTransmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.projection = build_projection(ROOT)
        cls.attention = {"finding_count": 0, "findings": [], "members": []}
        cls.scores = load_state(TEMP_SCORES)

    def test_presentation_includes_transmission(self) -> None:
        p = build_presentation(ROOT)
        self.assertIn("transmission", p)
        self.assertIn("transmission_history", p)
        self.assertGreaterEqual(len(p["transmission_history"]), 3)
        fuel = p["transmission"]["summary"]["direct_fuel"]["h1_3m"]
        self.assertAlmostEqual(fuel["pp_mid"], -0.183, delta=0.02)
        self.assertEqual(fuel["coverage"], "partial")

    def test_e2e_real_snapshot_overview_text(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_country_detail(
            "CA",
            {**self.projection["countries"]["CA"], "prima_pressure": presentation},
            self.attention,
            self.scores,
        )
        tx = _prima_excerpt(html).split('data-prima-legacy="v1"', 1)[0]
        self.assertIn("What changed", tx)
        self.assertIn("Where it is transmitting", tx)
        self.assertIn("What remains · 1–3m · 3–6m", tx)
        self.assertIn("−0.18 pp", tx)
        self.assertIn("not netted", tx)
        self.assertIn("October CPI fuel may still rise", tx)
        self.assertIn("2026-09-30", tx)
        self.assertIn("Reconstructed from frozen v1 inputs", tx)
        self.assertIn("context only, not a pressure input", tx)
        self.assertIn("Legacy comparison", _prima_excerpt(html))
        self.assertNotRegex(tx, r"\bNone\b")
        self.assertNotRegex(tx, r"\bnan\b")
        self.assertNotRegex(tx, r"\bnull\b")

    def test_unavailable_whole_transmission(self) -> None:
        block = {"transmission": unavailable_transmission("offline")}
        html = render_prima_pressure_block(block, _esc)
        self.assertIn('data-prima-tx-provenance="unavailable"', html)
        self.assertIn("Transmission unavailable", html)

    def test_energy_guard_clears_numerics(self) -> None:
        presentation = build_presentation(ROOT)
        tx = copy.deepcopy(presentation["transmission"])
        energy = tx["channels"]["energy_direct_fuel"]
        for horizon in ("h1_3m", "h3_6m"):
            h = energy["remaining"][horizon]
            h["pp_low"] = h["pp_mid"] = h["pp_high"] = None
            h["basis"] = "unavailable"
            h["direction"] = "unavailable"
            h.pop("roll_narrative", None)
        energy.pop("prior_window_evidence", None)
        energy["status"] = "unavailable"
        tx["summary"]["direct_fuel"]["h1_3m"]["pp_mid"] = None
        pres = {**presentation, "transmission": tx}
        html = render_prima_pressure_block(pres, _esc)
        fuel = html.split("prima-tx-fuel", 1)[1][:400]
        self.assertNotIn("−0.18", fuel)
        self.assertIn("unavailable", fuel.lower())

    def test_sparkline_skipped_under_three_points(self) -> None:
        presentation = build_presentation(ROOT)
        presentation["transmission_history"] = presentation["transmission_history"][:2]
        html = render_prima_pressure_block(presentation, _esc)
        self.assertNotIn("prima-tx-spark", html)

    def test_live_observed_provenance_badge(self) -> None:
        presentation = build_presentation(ROOT)
        tx = copy.deepcopy(presentation["transmission"])
        tx["provenance"] = TRANSMISSION_PROVENANCE_LIVE
        pres = {**presentation, "transmission": tx}
        html = render_prima_pressure_block(pres, _esc)
        self.assertIn("Live-observed", html)

    def test_mobile_overflow_css_rules(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertIn(".prima-tx", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("min-width: 0", css)
        self.assertIn(".prima-tx-spark-svg", css)

    def test_method_not_boc_prima(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_prima_pressure_block(presentation, _esc)
        self.assertIn('data-prima-raw="tx-method"', html)
        self.assertIn("not the Bank of Canada", html)

    def test_rendered_text_no_none_nan_leaks(self) -> None:
        from scripts.prima_pressure.transmission import unavailable_transmission

        cases = [
            {"transmission": unavailable_transmission("offline")},
            build_presentation(ROOT),
        ]
        tx_markers = (
            'class="prima-tx"',
            'class="prima-tx-unavailable"',
        )
        for block in cases:
            html = render_prima_pressure_block(block, _esc)
            tx_html = html
            for marker in tx_markers:
                if marker in html:
                    start = html.index(marker)
                    end = html.find("</section>", start)
                    tx_html = html[start:end if end > start else len(html)]
                    break
            self.assertNotIn("None", tx_html)
            self.assertNotRegex(tx_html, r"\b[nN]a[nN]\b")
            self.assertNotRegex(tx_html, r"\bnull\b")
            self.assertNotIn("()", tx_html)

    def test_imported_observed_labels_human_readable(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_prima_pressure_block(presentation, _esc)
        chunk = html.split('data-prima-tx-channel="imported_non_energy_goods"', 1)[1][:900]
        self.assertIn("USD/CAD 1m", chunk)
        self.assertNotIn("ret_1m", chunk)
        self.assertNotIn("-0.00%", chunk)

    def test_reconstructed_assumptions_exclude_tax_factor(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_prima_pressure_block(presentation, _esc)
        fuel = html.split('data-prima-tx-channel="energy_direct_fuel"', 1)[1][:2500]
        self.assertIn("Crude-cost-share elasticity", fuel)
        self.assertNotIn("tax_pass_through", fuel)

    def test_sector_ppi_energy_label_qoq(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_prima_pressure_block(presentation, _esc)
        self.assertIn("Sector PPI energy (q/q)", html)
        self.assertIn("19.85% q/q", html)

    def test_glance_mixed_when_prior_roll_opposite(self) -> None:
        from scripts.country_detail._prima_section import _tx_glance_chip

        presentation = build_presentation(ROOT)
        chip = _tx_glance_chip(presentation["transmission"])
        self.assertIn("mixed", chip.lower())
        self.assertNotIn("−0.18", chip)

    def test_reconstructed_caption_uses_cost_share_not_tax(self) -> None:
        presentation = build_presentation(ROOT)
        html = render_prima_pressure_block(presentation, _esc)
        self.assertIn("crude-cost-share elasticity", html)
        self.assertNotIn("1.10 tax factor", html.split("prima-tx-caption", 1)[1][:500])


if __name__ == "__main__":
    unittest.main()
