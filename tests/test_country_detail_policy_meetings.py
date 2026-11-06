from __future__ import annotations

import unittest

from scripts.country_detail.policy_meetings import render_policy_meetings

try:
    from scripts.country_detail.render import render_country_detail
except ImportError:  # pragma: no cover
    render_country_detail = None

from tests.test_country_detail_render import (
    SHARED_OBS_ID,
    synthetic_attention_populated,
    synthetic_projection,
    synthetic_score_state,
)

_BANKS = ("US", "CA", "AU", "NZ", "EA", "JP")
_NZ_REASON = "No NZD short-rate futures strip"


def _meeting(
    decision_date: str,
    *,
    post_rate: float,
    incremental_bp: float,
    cumulative_bp: float,
    method: str,
) -> dict:
    return {
        "decision_date": decision_date,
        "post_rate": post_rate,
        "incremental_bp": incremental_bp,
        "cumulative_bp": cumulative_bp,
        "chg_1d_bp": 0.5,
        "chg_1w_bp": -1.25,
        "method": method,
    }


def _priced_bank(code: str) -> dict:
    anchor = 4.25 if code == "US" else 3.5
    return {
        "status": "ok",
        "anchor": anchor,
        "basis_bp": 4.0,
        "futures_as_of": "2026-11-05T15:00:00Z",
        "calendar_retrieved_at": "2026-11-04",
        "meetings": [
            _meeting(
                "2026-12-10",
                post_rate=4.30 if code == "US" else 3.55,
                incremental_bp=-5.0,
                cumulative_bp=-5.0,
                method="identified",
            ),
            _meeting(
                "2027-01-28",
                post_rate=4.25 if code == "US" else 3.5,
                incremental_bp=0.0,
                cumulative_bp=-5.0,
                method="equal_step",
            ),
        ],
    }


def _snapshot() -> dict:
    prices = {"banks": {code: _priced_bank(code) for code in _BANKS if code != "NZ"}}
    prices["banks"]["NZ"] = {
        "status": "unavailable",
        "reason": _NZ_REASON,
        "meetings": [],
    }
    calendar = {
        "banks": {
            code: {
                "status": "verified",
                "retrieved_at": "2026-11-04",
                "decisions": [
                    {"decision_date": "2026-12-10", "state": "upcoming"},
                    {"decision_date": "2027-01-28", "state": "upcoming"},
                ],
            }
            for code in _BANKS
            if code != "NZ"
        }
    }
    calendar["banks"]["NZ"] = {
        "status": "unavailable",
        "reason": _NZ_REASON,
        "decisions": [],
    }
    return {"prices": prices, "calendar": calendar}


class CountryDetailPolicyMeetingsTest(unittest.TestCase):
    def test_six_countries_fold_and_nz_reason(self) -> None:
        snapshot = _snapshot()
        html_by_code: dict[str, str] = {}
        for code in _BANKS:
            prices = snapshot["prices"]["banks"].get(code)
            calendar = snapshot["calendar"]["banks"].get(code)
            html_by_code[code] = render_policy_meetings(code, prices, calendar)

        for html in html_by_code.values():
            self.assertIn('class="policy-meetings"', html)
            self.assertIn("<summary>Monetary policy</summary>", html)

        self.assertEqual(len(html_by_code), 6)
        self.assertIn(_NZ_REASON, html_by_code["NZ"])
        self.assertNotIn("<table>", html_by_code["NZ"])

        us_html = html_by_code["US"]
        self.assertIn("4.30%", us_html)
        self.assertEqual(us_html.count("<tr>"), 3)  # header + two meetings

        for code in ("CA", "AU", "EA", "JP"):
            self.assertEqual(html_by_code[code].count("<tr>"), 3)

    def test_missing_bank_block_still_renders_details(self) -> None:
        html = render_policy_meetings("US", None, None)
        self.assertIn('class="policy-meetings"', html)
        self.assertIn("<summary>Monetary policy</summary>", html)

    def test_reason_html_is_escaped(self) -> None:
        html = render_policy_meetings(
            "US",
            {"status": "unavailable", "reason": "<script>alert(1)</script>", "meetings": []},
            None,
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_render_country_detail_without_policy_meetings(self) -> None:
        if render_country_detail is None:
            self.skipTest("scripts.country_detail.render is not importable")
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
        )
        self.assertNotIn('class="policy-meetings"', html)

    def test_render_country_detail_with_policy_meetings(self) -> None:
        if render_country_detail is None:
            self.skipTest("scripts.country_detail.render is not importable")
        snapshot = _snapshot()
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_populated(SHARED_OBS_ID),
            synthetic_score_state(),
            policy_meetings=snapshot,
        )
        self.assertIn('class="policy-meetings"', html)
        self.assertIn("4.30%", html)
        compact = html.find('class="score-compact"')
        policy = html.find('class="policy-meetings"')
        wmn = html.find('class="what-matters-now"')
        self.assertTrue(0 <= compact < policy < wmn)


if __name__ == "__main__":
    unittest.main()
