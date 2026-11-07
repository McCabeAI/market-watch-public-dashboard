"""Shared technical block: provenance, passthrough, and no veto."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from scripts.fx_technical.packet import (
    ensure_fx_technical,
    fx_technical_from_market_state,
    technical_research_for_snapshot,
)
from scripts.fx_technical.research import build_technical_research, unavailable_technical_research
from scripts.market_state import MarketStateError, build_snapshot
from scripts.trader_room.evidence import assemble_packet


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): value for i, value in enumerate(values)}


class PacketPassthroughTests(unittest.TestCase):
    def test_missing_feed_does_not_veto(self) -> None:
        block = fx_technical_from_market_state({})
        self.assertEqual(block["status"], "unavailable")
        self.assertFalse(block["vetoes_unrelated_trades"])
        self.assertIsNone(block["pairs"].get("EURUSD") if isinstance(block["pairs"], dict) else None)

    def test_freeze_copy_matches_market_state_and_cannot_veto(self) -> None:
        series = _series(date(2024, 1, 1), [1.1 + i * 0.001 for i in range(40)])
        built = build_technical_research({"EURUSD": series}, as_of=date(2024, 2, 20))
        built["vetoes_unrelated_trades"] = True
        market = {"fx_technical": built}
        frozen = fx_technical_from_market_state(market)
        again = fx_technical_from_market_state(market)
        self.assertEqual(frozen["pairs"]["EURUSD"]["close"], again["pairs"]["EURUSD"]["close"])
        self.assertFalse(frozen["vetoes_unrelated_trades"])
        self.assertEqual(frozen["pairs"]["EURUSD"]["close"], built["pairs"]["EURUSD"]["close"])
        self.assertTrue(built["vetoes_unrelated_trades"])

    def test_ondemand_packet_uses_the_same_block(self) -> None:
        series = _series(date(2024, 1, 1), [1.08 + i * 0.0005 for i in range(30)])
        block = technical_research_for_snapshot(
            fx_series={"EURUSD": series},
            as_of=date(2024, 1, 30),
            clock=date(2024, 2, 2),
        )
        market = {
            "status": "ok",
            "generated_at": "2026-11-06T12:00:00Z",
            "fx_technical": block,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market-state.json"
            path.write_text(json.dumps(market), encoding="utf-8")
            first = assemble_packet(topic="fx technical", market_state_path=path)
            second = assemble_packet(topic="fx technical", market_state_path=path)
        self.assertEqual(first["fx_technical"], second["fx_technical"])
        self.assertEqual(first["fx_technical"]["pairs"]["EURUSD"]["close"], block["pairs"]["EURUSD"]["close"])
        self.assertFalse(first["fx_technical"]["vetoes_unrelated_trades"])
        permissions = {"bookable": ["US_RATES"]}
        packet = {"trade_permissions": permissions, "market_state": {"status": "ok"}}
        ensure_fx_technical(packet)
        self.assertEqual(packet["trade_permissions"], permissions)
        self.assertEqual(packet["fx_technical"]["status"], "unavailable")
        self.assertFalse(packet["fx_technical"]["vetoes_unrelated_trades"])

    def test_builder_failure_is_explicit_and_non_vetoing(self) -> None:
        block = technical_research_for_snapshot(
            fx_series={"EURUSD": {"not-a-date": 1.1}},
            as_of=date(2024, 1, 2),
        )
        self.assertEqual(block["status"], "unavailable")
        self.assertFalse(block["vetoes_unrelated_trades"])
        self.assertIn("failed closed", block["reason"])

    def test_us10y_change_is_twenty_sessions_and_not_forward_filled(self) -> None:
        start = date(2024, 1, 1)
        yields = _series(start, [4.0 + i * 0.01 for i in range(30)])
        block = build_technical_research(
            {"EURUSD": _series(start, [1.1] * 30)},
            as_of=start + timedelta(days=29),
            rate_series={"US10Y": yields},
        )
        # 20 sessions back: index 29 vs index 9. 0.01 * 20 * 100 bp = 20 bp.
        self.assertEqual(block["context"]["rates"]["change_20_obs_bp"], 20.0)

    def test_snapshot_attaches_close_only_block_without_network(self) -> None:
        start = date(2026, 8, 1)
        fx_hist = _series(start, [1.1 + i * 0.001 for i in range(25)])
        fx = {
            f"{a}{b}": dict(fx_hist)
            for i, a in enumerate(("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY"))
            for b in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")[i + 1 :]
        }
        us = {tenor: _series(start, [4.0] * 25) for tenor in ("2Y", "5Y", "10Y", "30Y")}

        def _boom(*_args, **_kwargs):
            raise MarketStateError("offline fixture")

        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", side_effect=_boom
        ), mock.patch("scripts.market_state.fetch_au_rates", side_effect=_boom), mock.patch(
            "scripts.market_state.fetch_nz_rates", side_effect=_boom
        ), mock.patch("scripts.market_state.fetch_ea_bund_rates", side_effect=_boom), mock.patch(
            "scripts.market_state.fetch_jp_jgb_rates", side_effect=_boom
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            snapshot = build_snapshot(include_cross_assets=False, today=date(2026, 8, 30))
        block = snapshot["fx_technical"]
        self.assertEqual(block["type"], "FX_TECHNICAL_RESEARCH")
        self.assertFalse(block["vetoes_unrelated_trades"])
        self.assertEqual(block["method"]["price"], "close_only")
        self.assertIn("atr", block["method"]["excluded"])
        self.assertIn("candlestick", block["method"]["excluded"])
        self.assertEqual(block["pair_count"], 45)
        self.assertEqual(set(block["horizons"]["primary"]), {"5D", "20D"})
        self.assertEqual(set(block["horizons"]["context"]), {"1D", "10D"})
        for setup in block["setups"]:
            self.assertIsNone(setup["trade_recommendation"])
        copied = fx_technical_from_market_state(snapshot)
        self.assertEqual(copied["pairs"]["EURUSD"]["close"], block["pairs"]["EURUSD"]["close"])


if __name__ == "__main__":
    unittest.main()
