from __future__ import annotations

import math
import unittest
from datetime import date

from scripts.official_forward_curves import (
    ForwardCurveError,
    forward_swap_proxy,
    parse_boc_zero_csv,
    parse_fed_zero_csv,
    parse_rba_f17,
    validate_forward_curves,
)


class OfficialForwardCurveTests(unittest.TestCase):
    def test_fed_continuous_zero_yields_become_discount_factors(self):
        text = "\n".join([
            '"Note"',
            "Date,SVENF01,SVENF02,SVENF03,SVENF04,SVENY01,SVENY02,SVENY03,SVENY04",
            "2026-09-10,4.5,4.6,4.7,4.8,4.10,4.20,4.30,4.40",
            "2026-09-11,4.6,4.7,4.8,4.9,4.20,4.30,4.40,4.50",
            "2026-09-12,NA,NA,NA,NA,NA,NA,NA,NA",
        ])
        curve = parse_fed_zero_csv(text, today=date(2026, 9, 19))
        self.assertEqual(curve["as_of"], "2026-09-11")
        self.assertAlmostEqual(
            curve["discount_factors"]["2Y"]["discount_factor"],
            math.exp(-0.043 * 2),
            places=10,
        )
        self.assertEqual(curve["zero_yields_pct"]["4Y"]["value"], 4.5)

    def test_rba_uses_published_discount_factors_directly(self):
        discount = "\n".join([
            "F17 ZERO-COUPON INTEREST RATES – ANALYTICAL SERIES",
            "Title,Zero-coupon discount factor – 0 yrs,Zero-coupon discount factor – 2 yrs,Zero-coupon discount factor – 3 yrs,Zero-coupon discount factor – 4 yrs,Zero-coupon discount factor – 5 yrs",
            "Series ID,FZCD0D,FZCD200D,FZCD300D,FZCD400D,FZCD500D",
            "31-Aug-2026,1.0000,0.9200,0.8750,0.8300,0.7900",
        ])
        yields = "\n".join([
            "F17 ZERO-COUPON INTEREST RATES – ANALYTICAL SERIES",
            "Title,Zero-coupon yield – 0 yrs,Zero-coupon yield – 2 yrs,Zero-coupon yield – 3 yrs,Zero-coupon yield – 4 yrs,Zero-coupon yield – 5 yrs",
            "Series ID,FZCY0D,FZCY200D,FZCY300D,FZCY400D,FZCY500D",
            "31-Aug-2026,4.0,4.2,4.3,4.4,4.5",
        ])
        forwards = "\n".join([
            "F17 ZERO-COUPON INTEREST RATES – ANALYTICAL SERIES",
            "Title,Zero-coupon forward rate – 0 yrs,Zero-coupon forward rate – 2 yrs,Zero-coupon forward rate – 3 yrs,Zero-coupon forward rate – 4 yrs,Zero-coupon forward rate – 5 yrs",
            "Series ID,FZCF0D,FZCF200D,FZCF300D,FZCF400D,FZCF500D",
            "31-Aug-2026,4.0,4.4,4.5,4.6,4.7",
        ])
        curve = parse_rba_f17(
            discount,
            today=date(2026, 9, 19),
            yield_text=yields,
            forward_text=forwards,
        )
        self.assertEqual(curve["discount_factors"]["2Y"]["discount_factor"], 0.92)
        self.assertEqual(curve["zero_yields_pct"]["3Y"]["value"], 4.3)
        self.assertEqual(curve["instantaneous_or_published_forwards_pct"]["4Y"]["value"], 4.6)
        self.assertEqual(curve["status"], "stale")

    def test_boc_fixed_quarter_year_grid_and_decimal_yields(self):
        values = [0.03 + i * 0.0001 for i in range(120)]
        text = "2026-09-02," + ",".join(f"{x:.6f}" for x in values) + "\n"
        curve = parse_boc_zero_csv(text, today=date(2026, 9, 19))
        self.assertEqual(curve["as_of"], "2026-09-02")
        self.assertAlmostEqual(curve["zero_yields_pct"]["2Y"]["value"], values[7] * 100, places=8)
        self.assertAlmostEqual(
            curve["discount_factors"]["4Y"]["discount_factor"],
            math.exp(-values[15] * 4),
            places=10,
        )

    def test_forward_swap_proxy_2y2y(self):
        curve = {
            "as_of": "2026-09-18",
            "discount_factors": {
                "2Y": {"discount_factor": 0.93, "as_of": "2026-09-18"},
                "3Y": {"discount_factor": 0.88, "as_of": "2026-09-18"},
                "4Y": {"discount_factor": 0.83, "as_of": "2026-09-18"},
            },
        }
        mark = forward_swap_proxy(curve, start_years=2, tenor_years=2)
        expected = 100.0 * (0.93 - 0.83) / (0.88 + 0.83)
        self.assertAlmostEqual(mark["rate_pct"], expected, places=8)

    def test_validation_accepts_stale_official_proxy_but_requires_2y2y_inputs(self):
        def block(country):
            return {
                "status": "stale",
                "curve_type": "government_zero_curve_proxy",
                "as_of": "2026-09-01",
                "discount_factors": {
                    "2Y": {"discount_factor": 0.93},
                    "3Y": {"discount_factor": 0.88},
                    "4Y": {"discount_factor": 0.83},
                },
            }
        payload = {
            "status": "ok",
            "countries": {country: block(country) for country in ("US", "CA", "AU")},
            "method": {"model_calls": 0},
        }
        validate_forward_curves(payload)
        del payload["countries"]["CA"]["discount_factors"]["3Y"]
        with self.assertRaises(ForwardCurveError):
            validate_forward_curves(payload)


if __name__ == "__main__":
    unittest.main()
