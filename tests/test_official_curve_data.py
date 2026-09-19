from __future__ import annotations

import io
import math
import zipfile
import unittest

from scripts.official_curve_data import (
    parse_boc_zero_curve_bytes,
    parse_fed_nominal_curve_csv,
    parse_rba_f17,
    validate_official_curves,
)


class OfficialCurveParserTests(unittest.TestCase):
    def test_fed_zero_curve_builds_discount_factors(self):
        text = "\n".join([
            "Note: fixture",
            "Series,Compounding Convention,Mnemonic(s)",
            "Zero-coupon yield,Continuously Compounded,SVENYXX",
            "",
            "Date,SVENY02,SVENY03,SVENY04,SVENF02,SVENF03,SVENF04",
            "2026-09-11,4.00,4.10,4.20,4.20,4.30,4.40",
        ])
        block = parse_fed_nominal_curve_csv(text)
        self.assertEqual(block["as_of"], "2026-09-11")
        self.assertAlmostEqual(block["zero_yields"]["2Y"]["value"], 4.0)
        self.assertAlmostEqual(
            block["discount_factors"]["2Y"]["value"],
            math.exp(-0.04 * 2),
            places=9,
        )
        self.assertEqual(block["forward_rates"]["4Y"]["value"], 4.4)

    def test_boc_120_point_curve_builds_quarter_year_discount_grid(self):
        values = [0.03 + i * 0.00001 for i in range(120)]
        csv_text = "2026-09-02," + ",".join(str(x) for x in values) + "\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("yield_curves.csv", csv_text)
        block = parse_boc_zero_curve_bytes(buf.getvalue())
        self.assertEqual(block["as_of"], "2026-09-02")
        self.assertIn("0.25Y", block["discount_factors"])
        self.assertIn("2Y", block["discount_factors"])
        self.assertIn("3Y", block["discount_factors"])
        self.assertIn("4Y", block["discount_factors"])
        self.assertAlmostEqual(block["zero_yields"]["0.25Y"]["value"], 3.0)

    def test_rba_f17_uses_published_discount_forward_and_yield_curves(self):
        header = "F17 ZERO-COUPON INTEREST RATES – ANALYTICAL SERIES\n"
        def fixture(label: str, vals: tuple[float, float, float]) -> str:
            return header + "\n".join([
                f"Title,{label} – 2 yrs,{label} – 3 yrs,{label} – 4 yrs",
                "Frequency,Daily,Daily,Daily",
                "Series ID,A,B,C",
                f"04-Sep-2026,{vals[0]},{vals[1]},{vals[2]}",
            ])
        block = parse_rba_f17(
            fixture("Zero-coupon discount factor", (0.93, 0.89, 0.85)),
            fixture("Zero-coupon forward rate", (4.1, 4.2, 4.3)),
            fixture("Zero-coupon yield", (4.0, 4.05, 4.1)),
        )
        self.assertEqual(block["as_of"], "2026-09-04")
        self.assertEqual(block["discount_factors"]["3Y"]["value"], 0.89)
        self.assertEqual(block["forward_rates"]["4Y"]["value"], 4.3)
        self.assertEqual(block["zero_yields"]["2Y"]["value"], 4.0)

    def test_validator_requires_tradeable_2_to_4_year_curve(self):
        def country():
            return {
                "status": "ok",
                "discount_factors": {
                    t: {"value": v, "as_of": "2026-09-11"}
                    for t, v in {"2Y": 0.93, "3Y": 0.89, "4Y": 0.85}.items()
                },
            }
        payload = {
            "status": "ok",
            "countries": {"US": country(), "CA": country(), "AU": country()},
            "method": {"model_calls": 0, "credentials_required": []},
        }
        validate_official_curves(payload)


if __name__ == "__main__":
    unittest.main()
