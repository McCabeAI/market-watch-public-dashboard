from __future__ import annotations

import re
import unittest
from datetime import date

from scripts.country_detail.indicator import (
    contribution_sum_text,
    credible_release_dates,
    describe_window,
    headline,
    indicator_view,
    measure_kind,
    rationale,
    score_usage,
)
from scripts.country_detail.render import render_country_detail

OID = "9" * 64


def _monthly_history(values: list[float], *, start_year: int = 2025, start_month: int = 1, **extra) -> list[dict]:
    rows = []
    year, month = start_year, start_month
    for value in values:
        rows.append({"reference_period": f"{year}-{month:02d}", "value": value, **extra})
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return rows


def _retail(values: list[float], **overrides) -> dict:
    history = _monthly_history(values)
    obs = {
        "observation_id": OID,
        "label": "Retail trade sales, monthly percent change",
        "topic": "consumer",
        "series_id": "v1446859483",
        "reference_period": history[-1]["reference_period"],
        "value": values[-1],
        "units": "percent",
        "transformation": "mom_pct",
        "score_role": "scored",
        "score_input": True,
        "catalog_id": "CA.Consumer.retail_sales",
        "publisher": "Statistics Canada",
        "source_url": "https://example.invalid/ca/retail",
        "history": history,
    }
    obs.update(overrides)
    return obs


def _face(html: str) -> str:
    return re.sub(r"<details\b[^>]*>.*?</details>", "", html, flags=re.S)


class ReleaseDateTest(unittest.TestCase):
    def test_shared_vintage_stamp_belongs_to_newest_period_only(self) -> None:
        points = [
            {"reference_period": "2026-06", "release_date": "2026-08-22"},
            {"reference_period": "2026-07", "release_date": "2026-08-22"},
        ]
        self.assertEqual(credible_release_dates(points), {"2026-07": date(2026, 8, 22)})

    def test_dates_before_period_end_or_far_after_are_not_release_dates(self) -> None:
        points = [
            {"reference_period": "2026-08", "release_date": "2026-08-15"},
            {"reference_period": "2025-01", "release_date": "2026-09-20"},
            {"reference_period": "2026-Q2", "release_date": "2026-08-28"},
        ]
        self.assertEqual(credible_release_dates(points), {"2026-Q2": date(2026, 8, 28)})


class MeasureAndHeadlineTest(unittest.TestCase):
    def test_measure_kinds(self) -> None:
        self.assertEqual(measure_kind({"units": "percent", "transformation": "mom_pct"}), "pct_change")
        self.assertEqual(measure_kind({"units": "percent", "transformation": "percent", "label": "Unemployment rate"}), "rate")
        self.assertEqual(measure_kind({"units": "diffusion_index", "label": "Ivey PMI"}), "diffusion")
        self.assertEqual(
            measure_kind({"units": "thousands", "transformation": "mom_change_thousands_sa", "label": "Employment"}),
            "count_change",
        )

    def test_pct_change_headline_compares_with_prior_print(self) -> None:
        obs = _retail([0.2, -0.4, 0.6])
        view = indicator_view(obs)
        self.assertEqual(view["value_text"], "+0.60%")
        self.assertEqual(view["delta_text"], "+1.00 pp")
        self.assertEqual([p["period_label"] for p in view["prints"]], ["Mar 2025", "Feb 2025", "Jan 2025"])
        text = headline(obs, view)
        self.assertIn("rose 0.60%", text)
        self.assertIn("Mar 2025", text)
        self.assertIn("after -0.40% in Feb 2025", text)

    def test_pmi_headline_explains_the_fifty_line(self) -> None:
        history = _monthly_history([52.1, 48.7])
        obs = {
            "label": "Ivey Purchasing Managers Index",
            "units": "diffusion_index",
            "transformation": "level",
            "series_id": "IVEY",
            "reference_period": history[-1]["reference_period"],
            "value": 48.7,
            "history": history,
        }
        view = indicator_view(obs)
        self.assertTrue(view["pmi"])
        text = headline(obs, view)
        self.assertIn("48.7", text)
        self.assertIn("below the 50 no-change line", text)
        self.assertIn("more respondents report decreases than increases", text)
        self.assertIn("down 3.4 pts from Jan 2025", text)

    def test_short_history_uses_reason_prior_value(self) -> None:
        obs = _retail([0.6], history=[])
        text = headline(obs, indicator_view(obs), prior_value=-0.4)
        self.assertIn("after -0.40%", text)
        self.assertNotIn(" in the prior print", text)

    def test_rationale_has_no_detector_codes(self) -> None:
        obs = _retail([0.2, 0.3, -0.5])
        reversal = rationale({"travel_pattern": "reversal", "travel_run_length": 2, "travel_direction": -1}, obs)
        self.assertEqual(reversal, "Reversal: a decline after 2 straight months of increases.")
        flat = rationale(
            {"travel_pattern": "deceleration", "travel_run_length": 3, "travel_direction": 1},
            _retail([0.4, 0.5, 0.0]),
        )
        self.assertEqual(flat, "Slowdown: flat after 3 straight months of increases.")


class ViewModelTest(unittest.TestCase):
    def test_chart_keeps_twelve_months_and_eight_quarters(self) -> None:
        monthly = _retail([float(i % 5) / 10 for i in range(20)])
        self.assertEqual(len(indicator_view(monthly)["chart_points"]), 12)
        quarters = [{"reference_period": f"{2022 + i // 4}-Q{i % 4 + 1}", "value": 0.1 * i} for i in range(12)]
        quarterly = {
            "label": "Real GDP, quarterly percent change",
            "units": "percent",
            "transformation": "qoq_pct",
            "reference_period": quarters[-1]["reference_period"],
            "value": quarters[-1]["value"],
            "history": quarters,
        }
        view = indicator_view(quarterly)
        self.assertEqual(view["cadence"], "quarterly")
        self.assertEqual(len(view["chart_points"]), 8)

    def test_card_history_excludes_companion_series(self) -> None:
        history = _monthly_history([1.0, 2.0, 3.0], series_id="PRIMARY")
        history.append({"reference_period": "2025-02", "value": 99.0, "series_id": "OTHER"})
        obs = _retail([1.0, 2.0, 3.0], series_id="PRIMARY", history=history, companion_series=["OTHER"])
        view = indicator_view(obs)
        self.assertNotIn(99.0, [p["value"] for p in view["chart_points"]])
        self.assertTrue(any("1 other series is stored" in text for text in view["limitations"]))

    def test_missing_release_date_is_said_plainly(self) -> None:
        view = indicator_view(_retail([0.1, 0.2, 0.3]))
        self.assertEqual(view["release_text"], "Release date not recorded")
        history = _monthly_history([0.1, 0.2, 0.3])
        history[-1]["release_date"] = "2025-05-21"
        dated = indicator_view(_retail([0.1, 0.2, 0.3], history=history))
        self.assertEqual(dated["release_text"], "Released 21 May 2025")


class ScoreExplanationTest(unittest.TestCase):
    def _score_state(self, *, as_of: str, used: float, level: float = 54.0) -> dict:
        return {
            "baseline_score": 50,
            "countries": {
                "CA": {
                    "Consumer": {
                        "level": level,
                        "coverage": 1.0,
                        "component_state": {
                            "retail_sales": {
                                "observed": True,
                                "level": 54.0,
                                "weight": 1.0,
                                "as_of": as_of,
                                "transform_value": used,
                            }
                        },
                    }
                }
            },
        }

    def test_window_and_behind_latest(self) -> None:
        obs = _retail([0.2, -0.4, 0.6])
        window = {
            "observed": True,
            "transform": "trailing_mean_n2",
            "periods": ["2025-01", "2025-02"],
            "values": [0.2, -0.4],
            "series_ids": ["v1446859483"],
            "series_count": 1,
            "verified": True,
        }
        usage = score_usage(obs, "CA", self._score_state(as_of="2025-02", used=-0.1), window)
        self.assertTrue(usage["behind_latest"])
        self.assertFalse(usage["same_as_latest"])
        self.assertEqual(usage["used_text"], "-0.10%")
        self.assertEqual(usage["window_text"], "average of 2 months, Jan–Feb 2025: +0.20%, -0.40%")
        self.assertEqual(usage["contribution"]["text"], "+4.00 points in Consumer")

    def test_unverified_window_is_not_described(self) -> None:
        obs = _retail([0.2, -0.4, 0.6])
        window = {"observed": True, "transform": "trailing_mean_n2", "periods": ["2025-02", "2025-03"], "values": [-0.4, 0.6], "verified": False}
        usage = score_usage(obs, "CA", self._score_state(as_of="2025-03", used=0.1), window)
        self.assertEqual(usage["window_text"], "")

    def test_describe_annualised_window(self) -> None:
        obs = _retail([0.1, 0.2, 0.3])
        text = describe_window(
            {"transform": "mom_sa_compound_annualized_n3", "periods": ["2025-01", "2025-02", "2025-03"], "values": [0.1, 0.2, 0.3]},
            obs,
            "pct_change",
        )
        self.assertEqual(text, "3-month annualised rate, Jan–Mar 2025 (m/m +0.10%, +0.20%, +0.30%)")

    def test_reconciliation_only_when_stored_figures_add_up(self) -> None:
        state = self._score_state(as_of="2025-03", used=0.6)
        self.assertEqual(
            contribution_sum_text("CA", "Consumer", state, {"retail_sales": "Retail sales"})[0],
            "54.00 = 50 +4.00 retail sales",
        )
        off = self._score_state(as_of="2025-03", used=0.6, level=57.0)
        self.assertEqual(contribution_sum_text("CA", "Consumer", off, {})[0], "")


class CardFaceTest(unittest.TestCase):
    def _render(self, obs: dict, *, finding: bool) -> str:
        attention = {"finding_count": 0, "findings": [], "members": []}
        if finding:
            attention = {
                "finding_count": 1,
                "findings": [
                    {
                        "observation_id": OID,
                        "attention_status": "interesting",
                        "badge_text": "Interesting",
                        "headline_text": "mom pct 0.6",
                        "reason": "Reversal: mom pct ran -0.4 and 0.6 (insufficient_history).",
                        "travel_pattern": "reversal",
                        "travel_run_length": 1,
                        "travel_direction": 1,
                    }
                ],
                "members": [],
            }
        score_state = {
            "baseline_score": 50,
            "countries": {
                "CA": {
                    "Consumer": {
                        "level": 54.0,
                        "coverage": 1.0,
                        "component_state": {
                            "retail_sales": {"observed": True, "level": 54.0, "weight": 1.0, "as_of": obs["reference_period"], "transform_value": obs["value"]}
                        },
                    }
                }
            },
        }
        return render_country_detail("CA", {"observations": [obs]}, attention, score_state)

    def test_release_card_face_has_no_machine_codes(self) -> None:
        html = self._render(_retail([0.2, -0.4, 0.6]), finding=True)
        card = re.search(r'<article class="wmn-finding".*?</article>', html, flags=re.S).group(0)
        face = _face(card)
        text = re.sub(r"<[^>]+>", " ", face)
        for code in (OID, "v1446859483", "mom_pct", "insufficient_history", "CA.Consumer.retail_sales"):
            self.assertNotIn(code, text)
        self.assertIn("Mar 2025", face)
        self.assertIn("Release date not recorded", face)
        self.assertIn("+0.60%", face)
        self.assertIn('class="ind-prints"', face)
        self.assertIn("Feeds the", face)
        self.assertIn("+4.00 points in Consumer", face)
        self.assertIn("v1446859483", card)
        self.assertIn('class="ind-chart"', card)
        self.assertIn('class="history-table"', card)

    def test_score_driver_links_to_the_release_card(self) -> None:
        html = self._render(_retail([0.2, -0.4, 0.6]), finding=True)
        row = re.search(r'<div class="evidence-grid-row score-input".*?</details></div>', html, flags=re.S).group(0)
        self.assertIn(f'href="#wmn-{OID}"', row)
        self.assertIn("Score uses", row)
        self.assertIn("54.00 = 50 +4.00 retail sales", html)

    def test_evidence_card_face_has_no_machine_codes(self) -> None:
        html = self._render(_retail([0.2, -0.4, 0.6]), finding=False)
        card = re.search(rf'<article class="evidence-item" id="ev-{OID}".*?</article>', html, flags=re.S).group(0)
        summary = re.sub(r"<[^>]+>", " ", re.search(r"<summary>(.*?)</summary>", card, flags=re.S).group(1))
        for code in (OID, "v1446859483", "mom_pct"):
            self.assertNotIn(code, summary)
        self.assertIn("+0.60%", summary)
        self.assertIn("Mar 2025", summary)


if __name__ == "__main__":
    unittest.main()
