"""Unit tests for futures strips and USD SOFR OIS builders."""

from __future__ import annotations

import unittest

from scripts.rates.ois import (
    OIS_TYPE,
    assess_ois,
    build_ois,
    instrument_id,
    ois_pnl_usd,
    par_from_sofr_ois_discount_factors,
)
from scripts.rates.strips import STRIP_TYPE, assess_strip, build_strip, strip_pnl_usd
from scripts.rates.structures import StructureError, update_leg_marks


def _curve(curve_id: str, rows: list[tuple[str, float]]) -> dict:
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-23"} for expiry, rate in rows],
    }


def _sofr_market(rows: list[tuple[str, float]]) -> dict:
    return {
        "generated_at": "2026-10-23T21:00:00Z",
        "fx": {"pairs": {}},
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {"SOFR": _curve("SOFR", rows)},
        },
    }


def _ois_block(**instruments: dict) -> dict:
    return {
        "status": "ok",
        "curve_kind": "sofr_ois",
        "source": "test_fixture",
        "as_of": "2026-10-23",
        "day_count": "ACT/360",
        "instruments": instruments,
    }


class StripBuildTests(unittest.TestCase):
    def test_four_quarter_sofr_strip_economics(self) -> None:
        expiries = ["2027-03", "2027-06", "2027-09", "2027-12"]
        market = _sofr_market([(e, 4.0) for e in expiries])
        expr = {"type": STRIP_TYPE, "curve_id": "SOFR", "expiries": expiries}
        pkg = build_strip(expr, side="long", notional_usd=4_000_000, market_state=market)
        self.assertEqual(len(pkg["legs"]), 4)
        for leg in pkg["legs"]:
            self.assertEqual(leg["contracts"], 1)
            self.assertEqual(leg["dv01_per_contract_local"], 25.0)
            self.assertEqual(leg["side"], "long")
        self.assertAlmostEqual(pkg["shock_dv01_usd"], 100.0, places=6)
        self.assertAlmostEqual(pkg["spread_dv01_usd"], 100.0, places=6)
        self.assertEqual(pkg["shock_policy"], "sum_leg_dv01")
        update_leg_marks(pkg["legs"], {leg["instrument"]: 3.99 for leg in pkg["legs"]})
        total = strip_pnl_usd(pkg["legs"])
        self.assertAlmostEqual(total or 0.0, 100.0, places=6)

    def test_sub_one_lot_per_leg_raises(self) -> None:
        expiries = ["2027-03", "2027-06", "2027-09", "2027-12"]
        market = _sofr_market([(e, 4.0) for e in expiries])
        expr = {"type": STRIP_TYPE, "curve_id": "SOFR", "expiries": expiries}
        with self.assertRaises(StructureError) as ctx:
            build_strip(expr, notional_usd=1_000_000, market_state=market)
        self.assertIn("below one exchange contract", str(ctx.exception))

    def test_corra_requires_fx(self) -> None:
        expiries = ["2027-03", "2027-06"]
        market = {
            "tradable_rate_curves": {
                "status": "ok",
                "curves": {"CORRA": _curve("CORRA", [(e, 3.0) for e in expiries])},
            },
        }
        expr = {"type": STRIP_TYPE, "curve_id": "CORRA", "expiries": expiries}
        face_one = 1_000_000 / 1.36
        with self.assertRaises(StructureError):
            build_strip(expr, notional_usd=2 * face_one, market_state=market)
        market["fx"] = {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-10-23"}}}
        pkg = build_strip(expr, notional_usd=2 * face_one, market_state=market)
        self.assertEqual(len(pkg["legs"]), 2)
        for leg in pkg["legs"]:
            self.assertEqual(leg["contracts"], 1)
            self.assertEqual(leg["product_code"], "CRA")
            self.assertAlmostEqual(leg["dv01_per_contract_local"], 25.0, places=6)


class StripAssessTests(unittest.TestCase):
    def test_assess_returns_none_for_other_types(self) -> None:
        self.assertIsNone(assess_strip({"type": "calendar_spread"}))

    def test_assess_executable(self) -> None:
        market = _sofr_market([("2027-03", 4.0)])
        verdict = assess_strip(
            {"type": STRIP_TYPE, "curve_id": "SOFR", "expiries": ["2027-03"]},
            notional_usd=1_000_000,
            market_state=market,
        )
        assert verdict is not None
        self.assertEqual(verdict["status"], "executable")
        self.assertTrue(verdict["bookable"])
        self.assertEqual(verdict["mark_status"], "ok")
        self.assertIn("tradable_rate_curves.SOFR", verdict["mark_source"] or "")


class OisBuildTests(unittest.TestCase):
    def test_receive_2y_dv01_and_pnl(self) -> None:
        state = {
            "usd_sofr_ois": _ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.0,
                    "annuity": 1.95,
                    "quote_type": "observed_par",
                    "source": "fixture_2y",
                    "as_of": "2026-10-23",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        }
        expr = {"type": OIS_TYPE, "start_years": 0, "tenor_years": 2}
        pos = build_ois(expr, side="long", notional_usd=10_000_000, market_state=state)
        self.assertAlmostEqual(pos["dv01_usd"], 1950.0, places=6)
        self.assertAlmostEqual(ois_pnl_usd(pos, mark_rate=3.99) or 0.0, 1950.0, places=6)
        pos_short = build_ois(expr, side="short", notional_usd=10_000_000, market_state=state)
        self.assertAlmostEqual(ois_pnl_usd(pos_short, mark_rate=3.99) or 0.0, -1950.0, places=6)

    def test_1y1y_long_loses_when_rate_rises(self) -> None:
        state = {
            "usd_sofr_ois": _ois_block(
                USD_SOFR_OIS_1Y1Y={
                    "start_years": 1,
                    "tenor_years": 1,
                    "par_rate_percent": 3.70,
                    "annuity": 0.96,
                    "quote_type": "observed_par",
                    "source": "fixture_1y1y",
                    "as_of": "2026-10-23",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        }
        expr = {"type": OIS_TYPE, "start_years": 1, "tenor_years": 1}
        pos = build_ois(expr, side="long", notional_usd=5_000_000, market_state=state)
        self.assertAlmostEqual(pos["dv01_usd"], 480.0, places=6)
        self.assertAlmostEqual(ois_pnl_usd(pos, mark_rate=3.71) or 0.0, -480.0, places=6)

    def test_missing_block_and_official_only(self) -> None:
        expr = {"type": OIS_TYPE, "start_years": 0, "tenor_years": 2}
        v1 = assess_ois(expr, notional_usd=1_000_000, market_state={})
        assert v1 is not None
        self.assertEqual(v1["status"], "missing_input")
        self.assertFalse(v1["bookable"])
        self.assertTrue(
            "not a SOFR OIS quote" in v1["reason"] or "usd_sofr_ois" in v1["missing_inputs"]
        )
        v2 = assess_ois(
            expr,
            notional_usd=1_000_000,
            market_state={"official_curves": {"US": {"2Y": 4.0}}},
        )
        assert v2 is not None
        self.assertEqual(v2["status"], "missing_input")
        self.assertIn("not a SOFR OIS quote", v2["reason"])

    def test_missing_annuity_path(self) -> None:
        state = {
            "usd_sofr_ois": _ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.0,
                    "quote_type": "observed_par",
                    "source": "x",
                    "as_of": "2026-10-23",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        }
        verdict = assess_ois(
            {"type": OIS_TYPE, "start_years": 0, "tenor_years": 2},
            notional_usd=1_000_000,
            market_state=state,
        )
        assert verdict is not None
        self.assertEqual(verdict["status"], "missing_input")
        joined = " ".join(verdict["missing_inputs"])
        self.assertIn("usd_sofr_ois.instruments.USD_SOFR_OIS_2Y.annuity", joined)

    def test_instrument_substitution_refused(self) -> None:
        state = {"usd_sofr_ois": _ois_block()}
        with self.assertRaises(StructureError) as ctx:
            build_ois(
                {
                    "type": OIS_TYPE,
                    "start_years": 1,
                    "tenor_years": 1,
                    "instrument": "USD_SOFR_OIS_2Y",
                },
                notional_usd=1_000_000,
                market_state=state,
            )
        self.assertIn("refusing silent substitution", str(ctx.exception))


class OisParFromDfTests(unittest.TestCase):
    def test_spot_2y_from_discount_factors(self) -> None:
        payments = [
            {"maturity_years": 1, "accrual_act_360": 1.0, "discount_factor": 0.96, "source": "df1"},
            {"maturity_years": 2, "accrual_act_360": 1.0, "discount_factor": 0.92, "source": "df2"},
        ]
        out = par_from_sofr_ois_discount_factors(
            payments,
            start_discount_factor=1.0,
            start_is_definitional=True,
            start_years=0,
        )
        self.assertAlmostEqual(out["annuity"], 1.88, places=6)
        expected_par = 100.0 * (1.0 - 0.92) / 1.88
        self.assertAlmostEqual(out["par_rate_percent"], expected_par, places=6)
        self.assertEqual(out["quote_type"], "derived_from_discount_factors")
        self.assertTrue(out["definitional_spot_discount_factor"])

    def test_definitional_start_refused_for_forward(self) -> None:
        with self.assertRaises(ValueError):
            par_from_sofr_ois_discount_factors(
                [{"maturity_years": 2, "accrual_act_360": 1.0, "discount_factor": 0.9, "source": "df"}],
                start_discount_factor=1.0,
                start_is_definitional=True,
                start_years=1,
            )


class OisInstrumentIdTests(unittest.TestCase):
    def test_ids(self) -> None:
        self.assertEqual(instrument_id(start_years=0, tenor_years=2), "USD_SOFR_OIS_2Y")
        self.assertEqual(instrument_id(start_years=1, tenor_years=1), "USD_SOFR_OIS_1Y1Y")


if __name__ == "__main__":
    unittest.main()
