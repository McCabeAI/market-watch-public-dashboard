#!/usr/bin/env python3
"""End-to-end ASX IB/IR integration through policy paths, curves, and trading hooks."""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.asx_eod import ASX_EOD_TEMPLATE
from scripts.asx_futures_cache import save_product
from scripts.country_registry import required_tradable_curve_ids
from scripts.overnight.freshness import _dependency_status, expression_dependencies
from scripts.policy_meeting_pricing import _contracts_for_bank, price_meetings
from scripts.policy_path_data import (
    RBA_F1_URL,
    build_tradable_rate_curves,
    collect_policy_paths,
    validate_policy_paths,
    validate_tradable_rate_curves,
)
from scripts.rates.bbsw_valuation import contract_value_aud, ir_pnl_aud, ir_pnl_usd
from scripts.rates.contract_economics import parse_contract_id
from scripts.rates.executable_catalog import assess_expression
from scripts.rates.strips import build_strip
from scripts.rates.structures import build_structure, structure_pnl_usd

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "asx"
TODAY = date(2026, 11, 8)

RBA_F1_SAMPLE = """F1 INTEREST RATES AND YIELDS – MONEY MARKET
Title,Cash Rate Target,Interbank Overnight Cash Rate,EOD 1-month BABs/NCDs,EOD 3-month BABs/NCDs,EOD 6-month BABs/NCDs,1-month OIS,3-month OIS,6-month OIS
Description,target,aonia,b1,b3,b6,o1,o3,o6
Series ID,FIRMMCRTD,FIRMMCRID,FIRMMBAB30D,FIRMMBAB90D,FIRMMBAB180D,FIRMMOIS1D,FIRMMOIS3D,FIRMMOIS6D
17-Sep-2026,4.35,4.35,4.41,4.68,5.07,4.62,4.62,4.65
"""


def _load(name: str) -> bytes:
    return FIXTURES.joinpath(name).read_bytes()


def _strip_product(html: str, product_head: str) -> str:
    start = html.find(product_head)
    if start < 0:
        return html
    end = html.find('<TR class="Headbold"', start + 1)
    if end < 0:
        return html[:start]
    return html[:start] + html[end:]


def _fetch_factory(
    *,
    asx_name: str = "EODWebMarketSummary261106SFD.htm",
    f1_text: str | None = RBA_F1_SAMPLE,
    f1_raises: bool = False,
    asx_raises: bool = False,
) -> object:
    yymmdd = "261105" if "261105" in asx_name else "261106"
    bodies = {ASX_EOD_TEMPLATE.format(yymmdd=yymmdd): _load(asx_name)}

    def fetch_bytes(url: str, **kwargs: object) -> bytes:
        if url == RBA_F1_URL:
            if f1_raises:
                raise OSError("RBA F1 down")
            return (f1_text or "").encode("utf-8")
        if asx_raises:
            raise OSError("ASX down")
        if url in bodies:
            return bodies[url]
        raise FileNotFoundError(url)

    return fetch_bytes


def _collect(**kwargs: object) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        cache = f"{tmp}/cache.json"
        import os

        os.environ["MW_ASX_FUTURES_CACHE"] = cache
        try:
            return collect_policy_paths(today=TODAY, fetch_bytes=_fetch_factory(**kwargs))  # type: ignore[arg-type]
        finally:
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)


class AsxIrIntegrationTests(unittest.TestCase):
    def test_sunday_lookback_nov6_fresh_both_products(self) -> None:
        paths = _collect()
        au = paths["countries"]["AU"]
        self.assertEqual(au["contracts_1m_as_of"], "2026-11-06")
        self.assertEqual(au["contracts_3m_as_of"], "2026-11-06")
        self.assertEqual(au["contracts_1m_freshness"], "current")
        self.assertEqual(au["contracts_3m_freshness"], "current")
        self.assertEqual(au["contracts_1m_status"], "ok")
        self.assertEqual(au["contracts_3m_status"], "ok")
        by_expiry = {r["expiry"]: r for r in au["contracts_3m"]}
        self.assertAlmostEqual(by_expiry["2026-12"]["implied_rate"], 4.95)
        self.assertAlmostEqual(by_expiry["2027-03"]["implied_rate"], 4.96)
        self.assertAlmostEqual(by_expiry["2027-06"]["implied_rate"], 4.88)
        self.assertAlmostEqual(by_expiry["2027-09"]["implied_rate"], 4.77)
        self.assertAlmostEqual(by_expiry["2027-12"]["implied_rate"], 4.67)
        dec = by_expiry["2026-12"]
        self.assertEqual(dec.get("open_interest"), 418277.0)
        self.assertEqual(dec.get("volume"), 35082.0)
        listed = {r["expiry"]: r for r in au["listed_contracts_3m"]}
        self.assertEqual(listed["2026-11"]["exclusion_reason"], "illiquid_serial")
        self.assertFalse(listed["2026-11"]["tradable"])
        self.assertNotIn("2026-11", by_expiry)
        validate_policy_paths(paths)

    def test_adjacent_session_as_of_nov5(self) -> None:
        paths = _collect(asx_name="EODWebMarketSummary261105SFD.htm")
        au = paths["countries"]["AU"]
        self.assertEqual(au["contracts_3m_as_of"], "2026-11-05")
        dec = next(r for r in au["contracts_3m"] if r["expiry"] == "2026-12")
        self.assertAlmostEqual(dec["implied_rate"], 4.97)

    def test_ib_only_ir_unavailable_country_ok(self) -> None:
        html = _strip_product(_load("EODWebMarketSummary261106SFD.htm").decode("utf-8", errors="replace"), "IR - 90-Day Bank Bills")
        bodies = {ASX_EOD_TEMPLATE.format(yymmdd="261106"): html.encode()}

        def fetch(url: str, **kwargs: object) -> bytes:
            if url == RBA_F1_URL:
                return RBA_F1_SAMPLE.encode()
            return bodies[url]

        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["MW_ASX_FUTURES_CACHE"] = f"{tmp}/cache.json"
            paths = collect_policy_paths(today=TODAY, fetch_bytes=fetch)
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)
        au = paths["countries"]["AU"]
        self.assertEqual(au["status"], "ok")
        self.assertTrue(au["contracts_1m"])
        self.assertEqual(au["contracts_3m_status"], "unavailable")
        self.assertEqual(au["benchmark"]["rate"], 4.35)

    def test_ir_only_no_cache_ib_unavailable(self) -> None:
        html = _strip_product(_load("EODWebMarketSummary261106SFD.htm").decode("utf-8", errors="replace"), "IB - 30 Day Interbank Cash Rate")
        bodies = {ASX_EOD_TEMPLATE.format(yymmdd="261106"): html.encode()}

        def fetch(url: str, **kwargs: object) -> bytes:
            if url == RBA_F1_URL:
                return RBA_F1_SAMPLE.encode()
            return bodies[url]

        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["MW_ASX_FUTURES_CACHE"] = f"{tmp}/cache.json"
            paths = collect_policy_paths(today=TODAY, fetch_bytes=fetch)
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)
        au = paths["countries"]["AU"]
        self.assertIn(au["status"], {"partial", "unavailable"})
        self.assertTrue(au["contracts_3m"])
        self.assertEqual(au["contracts_1m_status"], "unavailable")
        self.assertEqual(au["benchmark"]["rate"], 4.35)

    def test_fetch_raises_cache_stale_ib_only_no_ir_invention(self) -> None:
        record = {
            "product": "IB",
            "session_date": "2026-11-06",
            "as_of": "2026-11-06",
            "source_url": "https://example.test",
            "contracts": [
                {
                    "expiry": "2026-12",
                    "price": 95.6,
                    "implied_rate": 4.4,
                    "as_of": "2026-11-06",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            import os

            path = f"{tmp}/cache.json"
            save_product(path, "IB", record)
            os.environ["MW_ASX_FUTURES_CACHE"] = path
            paths = collect_policy_paths(today=TODAY, fetch_bytes=_fetch_factory(asx_raises=True))
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)
        au = paths["countries"]["AU"]
        self.assertEqual(au["contracts_1m_status"], "stale")
        self.assertFalse(au["contracts_1m_execution_eligible"])
        self.assertEqual(au["contracts_1m_as_of"], "2026-11-06")
        self.assertEqual(au["contracts_3m_status"], "unavailable")
        self.assertFalse(au["contracts_3m"])

    def test_corrupt_cache_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os

            path = Path(tmp) / "cache.json"
            path.write_text("{not-json", encoding="utf-8")
            os.environ["MW_ASX_FUTURES_CACHE"] = str(path)
            paths = collect_policy_paths(today=TODAY, fetch_bytes=_fetch_factory())
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)
        self.assertEqual(paths["countries"]["AU"]["contracts_3m_status"], "ok")

    def test_f1_down_ir_ok_bbsw_curve_ok(self) -> None:
        paths = _collect(f1_raises=True)
        au = paths["countries"]["AU"]
        self.assertIn("f1_error", au)
        self.assertNotIn("benchmark", au)
        self.assertNotEqual(au["status"], "ok")
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["BBSW"]["status"], "ok")
        self.assertEqual(curves["curves"]["AONIA"]["status"], "ok")

    def test_ib_ok_ir_missing_aonia_ok_bbsw_unavailable(self) -> None:
        html = _strip_product(_load("EODWebMarketSummary261106SFD.htm").decode("utf-8", errors="replace"), "IR - 90-Day Bank Bills")
        bodies = {ASX_EOD_TEMPLATE.format(yymmdd="261106"): html.encode()}

        def fetch(url: str, **kwargs: object) -> bytes:
            if url == RBA_F1_URL:
                return RBA_F1_SAMPLE.encode()
            return bodies[url]

        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["MW_ASX_FUTURES_CACHE"] = f"{tmp}/c.json"
            paths = collect_policy_paths(today=TODAY, fetch_bytes=fetch)
            os.environ.pop("MW_ASX_FUTURES_CACHE", None)
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["AONIA"]["status"], "ok")
        self.assertEqual(curves["curves"]["BBSW"]["status"], "unavailable")

    def test_top_level_ok_without_bbsw_required(self) -> None:
        paths = {
            "status": "ok",
            "countries": {
                "US": {
                    "status": "ok",
                    "benchmark": {"rate": 4.0},
                    "contracts_3m": [{"expiry": "2027-03", "implied_rate": 4.0}],
                },
                "CA": {
                    "status": "ok",
                    "benchmark": {"rate": 3.0},
                    "contracts_3m": [{"expiry": "2027-03", "implied_rate": 3.0}],
                },
                "AU": _collect()["countries"]["AU"],
            },
            "sources": {},
        }
        curves = build_tradable_rate_curves(paths)
        validate_tradable_rate_curves(curves)
        self.assertEqual(curves["status"], "ok")
        self.assertIn("BBSW", curves["curves"])
        required = required_tradable_curve_ids()
        self.assertEqual(set(required), {"SOFR", "CORRA", "AONIA"})

    def test_stale_bbsw_blocks_ir_not_sofr(self) -> None:
        paths = _collect()
        curves = build_tradable_rate_curves(paths)
        curves["curves"]["BBSW"]["status"] = "stale"
        curves["curves"]["BBSW"]["execution_eligible"] = False
        curves["curves"]["BBSW"]["error"] = "stale test"
        fx = {
            "status": "ok",
            "pairs": {"AUDUSD": {"status": "ok", "spot": 0.65, "as_of": "2026-11-06"}},
        }
        packet = {"tradable_rate_curves": curves, "policy_paths": paths, "fx": fx}
        ir_verdict = assess_expression("BBSW_2026-12", market_state=packet)
        self.assertNotEqual(ir_verdict.get("status"), "executable")
        self.assertEqual(ir_verdict.get("mark_status"), "stale")
        sofr = assess_expression(
            "SOFR_2027-06",
            market_state={
                **packet,
                "fx": {**fx, "pairs": {**fx["pairs"], "EURUSD": {"status": "ok", "spot": 1.1}}},
            },
        )
        self.assertIn(sofr.get("status"), {"executable", "missing_input", "unavailable"})
        self.assertIn("BBSW_curve", expression_dependencies("BBSW_2026-12"))
        self.assertEqual(_dependency_status(packet, "BBSW_curve"), "stale")

    def test_policy_meeting_ignores_ir_contracts(self) -> None:
        paths = _collect()
        au = paths["countries"]["AU"]
        rows, err = _contracts_for_bank("AU", au, paths_ok=True)
        self.assertIsNone(err)
        products = {r.get("product") for r in rows}
        self.assertEqual(products, {"IB"})
    def test_valuation_five_percent_anchor(self) -> None:
        self.assertAlmostEqual(float(contract_value_aud(5.0)), 987821.38, places=2)

    def test_ir_pnl_not_linear_dv01(self) -> None:
        aud = float(ir_pnl_aud(5.0, 4.95, 1, "long"))
        usd = float(ir_pnl_usd(5.0, 4.95, 1, "long", 0.65))
        self.assertAlmostEqual(aud, 120.32, places=2)
        self.assertAlmostEqual(usd, aud * 0.65, places=2)
        linear = 5 * 24.06 * 0.65
        self.assertNotAlmostEqual(usd, linear, places=2)

    def test_ibz6_parses_aonia(self) -> None:
        parsed = parse_contract_id("IBZ6")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.spec.curve_id, "AONIA")

    def test_bbsw_structures_and_strips(self) -> None:
        paths = _collect()
        curves = build_tradable_rate_curves(paths)
        market = {
            "tradable_rate_curves": curves,
            "fx": {"status": "ok", "pairs": {"AUDUSD": {"status": "ok", "spot": 0.65, "as_of": "2026-11-06"}}},
        }
        cal = build_structure(
            {"type": "calendar_spread", "curve_id": "BBSW", "near_expiry": "2026-12", "far_expiry": "2027-03"},
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertGreaterEqual(cal["legs"][0]["contracts"], 1)
        bf = build_structure(
            {
                "type": "butterfly",
                "curve_id": "BBSW",
                "wing1_expiry": "2026-12",
                "body_expiry": "2027-03",
                "wing2_expiry": "2027-06",
            },
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertEqual(len(bf["legs"]), 3)
        rv = build_structure(
            {
                "type": "outright_rv",
                "receive": {"curve_id": "BBSW", "expiry": "2026-12"},
                "pay": {"curve_id": "SOFR", "expiry": "2027-06"},
            },
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertEqual({leg["curve_id"] for leg in rv["legs"]}, {"BBSW", "SOFR"})
        expiries_all = [r["expiry"] for r in curves["curves"]["BBSW"]["contracts"]]
        for count in (4, 8, 12):
            expiries = expiries_all[:count]
            if len(expiries) < count:
                self.skipTest(f"fixture has only {len(expiries)} BBSW quarterlies")
            pkg = build_strip(
                {"type": "futures_strip_average", "curve_id": "BBSW", "expiries": expiries},
                market_state=market,
                notional_usd=1_000_000 * count,
            )
            dvs = {leg["expiry"]: leg["dv01_per_contract_local"] for leg in pkg["legs"]}
            self.assertGreater(len(set(dvs.values())), 1)
            moved = []
            for leg in pkg["legs"]:
                copy = dict(leg)
                copy["mark_rate"] = float(leg["mark_rate"]) - 0.05
                moved.append(copy)
            pnl = structure_pnl_usd(moved)
            self.assertIsNotNone(pnl)


if __name__ == "__main__":
    unittest.main()
