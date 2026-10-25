"""Deterministic tests for NZ rates paper-trade admission and seat isolation."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.freeze import _trade_permissions
from scripts.market_watch_launch.quality_gate import evaluate_gate
from scripts.overnight.books import (
    apply_action,
    empty_books as empty_trader_books,
    empty_seat,
    mark_to_market,
    public_books_view,
)
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed
from scripts.overnight.paper_marks import PaperMarkError, hydrate_action_mids, refresh_positions, resolve_paper_mid
from scripts.overnight.scheduled_output import _scan_decision_new_risk
from scripts.pm.books import apply_decision, empty_books, empty_pm_book
from scripts.trader_room.rates_scan import with_tenor_scan

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
WHEN_OCT14 = datetime(2026, 10, 14, 12, 0, tzinfo=NY)
WHEN_OCT16 = datetime(2026, 10, 16, 12, 0, tzinfo=NY)

_HISTORICAL_SHA256 = {
    "data/trading/trades/trd-trader-value-guy-pos-f895a4694dd7.json": (
        "bf9bb0752f0596d2043782732e590c17f3ae15d07e0365314407566672942951"
    ),
    "data/trading/trades/trd-pm-pragmatist-pm-pragmatist-3afafe53c6d7.json": (
        "6875e0cbb71f1f8f36dc91ffd4d17c86ad43d3fc6553bc9644f71761c0d72a9c"
    ),
    "data/overnight/books/latest.json": (
        "a05a020de9a8669e44a27f425df2caf8d67f076bf1f1bd2fd9314239b886516d"
    ),
    "data/pm/books/latest.json": (
        "6ac5462f6a4869a731a4e4e9f2fcf340695a653bc5d96214d3ab5f485d6b2cf8"
    ),
}


def _fresh_market_packet(**overrides) -> dict:
    packet = {
        "status": "ok",
        "preflight_status": "ok",
        "stale_sources": [],
        "preflight_stale_sources": [],
        "unavailable_sources": [],
        "rates": {
            "US": {
                "status": "ok",
                "latest_observation": "2026-10-13",
                "tenors": {"10Y": {"value": 5.21, "as_of": "2026-10-13"}},
            },
            "CA": {
                "status": "ok",
                "latest_observation": "2026-10-13",
                "tenors": {"10Y": {"value": 3.05, "as_of": "2026-10-13"}},
            },
            "AU": {
                "status": "ok",
                "latest_observation": "2026-10-13",
                "tenors": {"10Y": {"value": 4.35, "as_of": "2026-10-13"}},
            },
            "NZ": {
                "status": "ok",
                "latest_observation": "2026-10-13",
                "tenors": {"10Y": {"value": 4.98, "as_of": "2026-10-13"}},
            },
            "EA": {"status": "ok", "latest_observation": "2026-10-13"},
            "JP": {"status": "ok", "latest_observation": "2026-10-13"},
        },
        "rate_rv": {
            "NZ-US_10Y": {"bps": -23, "as_of": "2026-10-13", "status": "ok"},
        },
        "fx": {
            "status": "ok",
            "source_observation": "2026-10-13",
            "pairs": {
                "NZDUSD": {"spot": 0.5613, "as_of": "2026-10-13"},
                "USDCAD": {"spot": 1.36, "as_of": "2026-10-13"},
                "AUDUSD": {"spot": 0.66, "as_of": "2026-10-13"},
            },
        },
        "policy_paths": {"status": "ok", "countries": {"US": {"status": "ok"}, "CA": {"status": "ok"}}},
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "CORRA": {"status": "ok", "contracts": [{"expiry": "2027-03", "implied_rate": 2.7}]},
            },
        },
    }
    packet.update(overrides)
    return packet


def _families(packet: dict, *, family_status: str = "fresh") -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": family_status, "data": packet},
    }


def _rates_memo(instrument: str, *, asset_class: str = "rates", expression: dict | None = None) -> dict:
    rates_candidate: dict = {
        "instrument": instrument,
        "asset_class": asset_class,
        "rationale": "rates leg",
    }
    if expression is not None:
        rates_candidate["paper_expression"] = expression
    return with_tenor_scan(
        {
            "rates_candidate": rates_candidate,
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alt"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Tenor scan complete.",
        }
    )


def _spot_memo(instrument: str = "NZDUSD") -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Spot expression.",
    }


def _scored_rows_g5() -> list[dict]:
    rows: list[dict] = []
    for code in ("US", "CA", "AU", "EA", "JP"):
        rows.append(
            {
                "series_id": f"{code}.Inflation.core",
                "country": code,
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-08",
                "due_period": "2026-08",
            }
        )
    return rows


def _nz_combo_expression() -> dict:
    return {
        "type": "linear_combo",
        "output_unit": "bps",
        "legs": [
            {"instrument": "NZ_10Y", "asset_class": "rates", "weight": 1},
            {"instrument": "US_10Y", "asset_class": "rates", "weight": -1},
        ],
    }


def _value_guy_nz_position(*, mark_price: float | None = -23) -> dict:
    return {
        "position_id": "pos-f895a4694dd7",
        "instrument": "NZ-US_10Y",
        "asset_class": "rates_rv",
        "side": "short",
        "notional_usd": 80_000_000,
        "entry_price": -23,
        "mark_price": mark_price,
    }


class HistoricalNzTradeIntegrityTests(unittest.TestCase):
    def test_historical_files_byte_identical_and_open_nz_us_10y_short(self) -> None:
        for rel_path, expected in _HISTORICAL_SHA256.items():
            path = ROOT / rel_path
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, expected, rel_path)
        trader_trade = json.loads(
            (ROOT / "data/trading/trades/trd-trader-value-guy-pos-f895a4694dd7.json").read_text()
        )
        pm_trade = json.loads(
            (ROOT / "data/trading/trades/trd-pm-pragmatist-pm-pragmatist-3afafe53c6d7.json").read_text()
        )
        for trade, owner, position_id in (
            (trader_trade, "value-guy", "pos-f895a4694dd7"),
            (pm_trade, "pragmatist", "pm-pragmatist-3afafe53c6d7"),
        ):
            self.assertEqual(trade["status"], "open")
            self.assertEqual(trade["instrument"], "NZ-US_10Y")
            self.assertEqual(trade["side"], "short")
            self.assertEqual(trade["initial_notional_usd"], 80_000_000)
            self.assertEqual(trade["entry_mark"], -23)
            self.assertEqual(trade["position_id"], position_id)
            self.assertEqual(trade["owner_id"], owner)


class Oct14AdmissionDenialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _fresh_market_packet()
        self.families = _families(self.packet)
        self.market_state = self.packet

    def test_numeric_nz_rv_mark_does_not_admit_new_risk(self) -> None:
        mark = resolve_paper_mid(self.packet, "NZ-US_10Y", asset_class="rates_rv")
        self.assertEqual(mark["value"], -23.0)
        with self.assertRaises(FreshnessError) as ctx:
            assert_action_allowed(
                "OPEN",
                self.families,
                seat="value-guy",
                instrument="NZ-US_10Y",
                asset_class="rates_rv",
            )
        self.assertIn("unsupported_mark_source", str(ctx.exception))

    def test_trader_and_pm_blocked_admission_with_controls_still_open(self) -> None:
        seat = empty_seat("value-guy")
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "NZ-US_10Y",
                "side": "short",
                "notional_usd": 10_000_000,
                "price": -23,
                "asset_class": "rates_rv",
                "expression_memo": _rates_memo("NZ-US_10Y", asset_class="rates_rv"),
            },
            families=self.families,
            run_id="tr-nz-deny",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(seat["positions"], [])
        self.assertEqual(seat["history"][-1]["result"], "blocked_admission")
        self.assertIn("unsupported_mark_source", seat["blocked_opens"][-1]["reason"])

        combo = _nz_combo_expression()
        seat_combo = empty_seat("value-guy")
        apply_action(
            seat_combo,
            {
                "action": "OPEN",
                "instrument": "BASKET",
                "side": "short",
                "notional_usd": 10_000_000,
                "price": -23,
                "asset_class": "rates_rv",
                "paper_expression": combo,
                "expression_memo": _rates_memo("BASKET", asset_class="rates_rv", expression=combo),
            },
            families=self.families,
            run_id="tr-nz-combo",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(seat_combo["positions"], [])
        self.assertEqual(seat_combo["history"][-1]["result"], "blocked_admission")
        self.assertIn("unsupported_mark_source", seat_combo["blocked_opens"][-1]["reason"])

        books = apply_decision(
            empty_books(),
            {
                "pm_id": "pragmatist",
                "actions": [
                    {
                        "action": "OPEN",
                        "instrument": "NZ-US_10Y",
                        "side": "short",
                        "notional_usd": 10_000_000,
                        "asset_class": "rates_rv",
                    }
                ],
            },
            pm_id="pragmatist",
            market_state=self.market_state,
            run_id="pm-nz-deny",
            evidence_cutoff="2026-10-14T12:00:00-04:00",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        prag = books["pms"]["pragmatist"]
        self.assertEqual(prag["positions"], [])
        blocked = [row for row in prag["history"] if row.get("result") == "blocked_admission"]
        self.assertTrue(blocked)
        self.assertNotIn("HOLD", {row.get("action") for row in blocked})
        self.assertIn("unsupported_mark_source", blocked[-1].get("reason", ""))

        hawk = empty_seat("rate-hawk")
        apply_action(
            hawk,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=self.families,
            run_id="tr-us-ok",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(len(hawk["positions"]), 1)

        carry = empty_seat("carry-is-king")
        apply_action(
            carry,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=self.families,
            run_id="tr-au-ok",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(len(carry["positions"]), 1)

        ca = empty_seat("rate-dove")
        apply_action(
            ca,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=self.families,
            run_id="tr-ca-ok",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(len(ca["positions"]), 1)

        hedge = empty_seat("value-guy")
        apply_action(
            hedge,
            {
                "action": "HEDGE",
                "instrument": "NZ-US_10Y",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": -23,
                "asset_class": "rates_rv",
                "expression_memo": _rates_memo("NZ-US_10Y", asset_class="rates_rv"),
            },
            families=self.families,
            run_id="tr-nz-hedge",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(hedge["positions"], [])
        self.assertEqual(hedge["history"][-1]["result"], "blocked_admission")
        self.assertIn("unsupported_mark_source", hedge["blocked_opens"][-1]["reason"])

        actions = [
            {
                "action": "OPEN",
                "instrument": "NZ-US_10Y",
                "asset_class": "rates_rv",
                "price": -23,
                "mark_price": -23,
            }
        ]
        hydrate_action_mids(actions, self.market_state)
        self.assertNotIn("price", actions[0])
        self.assertIn("unsupported_mark_source", actions[0]["_paper_mark_error"])

        memo_only = _scan_decision_new_risk(
            {
                "expression_memo": _rates_memo("NZ-US_10Y", asset_class="rates_rv"),
                "actions": [{"action": "OPEN", "side": "short", "notional_usd": 10_000_000}],
            },
            seat="value-guy",
            positions=[],
            unresolved_position_ids=set(),
        )
        self.assertEqual(memo_only[0]["reason"], "unsupported_mark_source")
        self.assertEqual(memo_only[0]["action"], "OPEN")

        dk = empty_seat("dollar-king")
        apply_action(
            dk,
            {
                "action": "OPEN",
                "instrument": "NZDUSD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 0.5613,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("NZDUSD"),
            },
            families=self.families,
            run_id="tr-nzd-ok",
            when=WHEN_OCT14,
            market_state=self.market_state,
        )
        self.assertEqual(len(dk["positions"]), 1)

        books = apply_decision(
            books,
            {
                "pm_id": "chatgpt",
                "actions": [
                    {
                        "action": "OPEN",
                        "instrument": "USDCAD",
                        "side": "long",
                        "notional_usd": 10_000_000,
                        "asset_class": "spot_fx",
                    }
                ],
            },
            pm_id="chatgpt",
            market_state=self.market_state,
            run_id="pm-fx-ok",
            evidence_cutoff="2026-10-14T12:00:00-04:00",
            review_packet_id="p2",
            review_packet_sha256="h2",
        )
        self.assertEqual(len(books["pms"]["chatgpt"]["positions"]), 1)


class Oct16UnmarkableIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = _fresh_market_packet()
        self.packet["rates"]["NZ"] = {"status": "unavailable", "error": "RBNZ blocked"}
        self.packet["unavailable_sources"] = ["NZ_rates"]
        self.packet["rate_rv"] = {}
        self.families = _families(self.packet)
        self.positions = [
            {
                "position_id": "pos-f895a4694dd7",
                "seat": "value-guy",
                "instrument": "NZ-US_10Y",
                "asset_class": "rates_rv",
            },
            {
                "position_id": "pm-pragmatist-3afafe53c6d7",
                "seat": "pragmatist",
                "instrument": "NZ-US_10Y",
                "asset_class": "rates_rv",
            },
        ]

    def test_quality_gate_isolates_research_only_seats(self) -> None:
        result = evaluate_gate(
            rows=_scored_rows_g5(),
            families=self.families,
            positions=self.positions,
        )
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["coverage"], "PARTIAL")
        self.assertIsNone(result.get("reason"))
        self.assertEqual(sorted(result["restricted_seats"]), ["pragmatist", "value-guy"])
        self.assertEqual(result["seat_risk"], {"pragmatist": "unavailable_new_risk", "value-guy": "unavailable_new_risk"})
        self.assertEqual(result["quarantine_reason"], "unsupported_mark_source")
        self.assertEqual(result["hold_decisions_emitted"], 0)
        self.assertFalse(result["synthetic_holds"])
        self.assertEqual(set(result["trade_eligible_countries"]), {"US", "CA", "AU", "EA", "JP"})
        self.assertNotIn("NZ", result["trade_eligible_countries"])
        quarantined = {row["position_id"]: row for row in result["quarantined_positions"]}
        self.assertEqual(set(quarantined), {"pos-f895a4694dd7", "pm-pragmatist-3afafe53c6d7"})
        for row in quarantined.values():
            self.assertTrue(row["quarantined"])
            self.assertFalse(row["live_marked"])
            self.assertFalse(row["pnl_available"])
            self.assertFalse(row["scoring"])

    def test_unresolved_seat_clears_marks_and_blocks_peer_opens(self) -> None:
        seat = empty_seat("value-guy")
        seat["positions"].append(_value_guy_nz_position())
        refresh_positions(seat["positions"], self.packet)
        mark_to_market(seat)
        pos = seat["positions"][0]
        self.assertIsNone(pos["mark_price"])
        self.assertTrue(pos["pnl_unavailable"])
        books = empty_trader_books(overnight_run_id="tr-nz-view", when=WHEN_OCT16)
        books["seats"]["value-guy"] = seat
        view = public_books_view(books)
        vg = next(row for row in view["seats"] if row["seat"] == "value-guy")
        self.assertIsNone(vg.get("competition_rank"))

        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=self.families,
            run_id="tr-seat-block",
            when=WHEN_OCT16,
            market_state=self.packet,
        )
        self.assertEqual(len(seat["positions"]), 1)
        self.assertEqual(seat["history"][-1]["result"], "blocked_admission")
        self.assertIn("entry_not_approved", seat["blocked_opens"][-1]["reason"])

        apply_action(
            seat,
            {
                "action": "ADD",
                "position_id": "pos-f895a4694dd7",
                "notional_usd": 1_000_000,
                "price": -23,
                "expression_memo": _rates_memo("NZ-US_10Y", asset_class="rates_rv"),
            },
            families=self.families,
            run_id="tr-nz-add",
            when=WHEN_OCT16,
            market_state=self.packet,
        )
        self.assertEqual(seat["history"][-1]["result"], "blocked_admission")
        self.assertIn("unsupported_mark_source", seat["blocked_opens"][-1]["reason"])
        self.assertEqual(seat["positions"][0]["notional_usd"], 80_000_000)

        dk = empty_seat("dollar-king")
        apply_action(
            dk,
            {
                "action": "OPEN",
                "instrument": "NZDUSD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 0.5613,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("NZDUSD"),
            },
            families=self.families,
            run_id="tr-nzd-peer",
            when=WHEN_OCT16,
            market_state=self.packet,
        )
        self.assertEqual(len(dk["positions"]), 1)

        hawk = empty_seat("rate-hawk")
        apply_action(
            hawk,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=self.families,
            run_id="tr-us-peer",
            when=WHEN_OCT16,
            market_state=self.packet,
        )
        self.assertEqual(len(hawk["positions"]), 1)

        books = apply_decision(
            empty_books(),
            {
                "pm_id": "chatgpt",
                "actions": [
                    {
                        "action": "OPEN",
                        "instrument": "AUDUSD",
                        "side": "long",
                        "notional_usd": 10_000_000,
                        "asset_class": "spot_fx",
                    }
                ],
            },
            pm_id="chatgpt",
            market_state=self.packet,
            run_id="pm-empty-open",
            evidence_cutoff="2026-10-16T12:00:00-04:00",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        self.assertEqual(len(books["pms"]["chatgpt"]["positions"]), 1)

        prag_book = empty_pm_book("pragmatist")
        prag_book["positions"] = [
            {
                "position_id": "pm-pragmatist-3afafe53c6d7",
                "instrument": "NZ-US_10Y",
                "asset_class": "rates_rv",
                "side": "short",
                "notional_usd": 80_000_000,
                "entry_price": -23,
                "mark_price": None,
            }
        ]
        books = empty_books()
        books["pms"]["pragmatist"] = prag_book
        for instrument in ("US_10Y", "NZ-US_10Y"):
            books = apply_decision(
                books,
                {
                    "pm_id": "pragmatist",
                    "actions": [
                        {
                            "action": "OPEN",
                            "instrument": instrument,
                            "side": "short" if instrument == "NZ-US_10Y" else "long",
                            "notional_usd": 10_000_000,
                            "asset_class": "rates" if instrument == "US_10Y" else "rates_rv",
                            "price": 5.21 if instrument == "US_10Y" else -23,
                        }
                    ],
                },
                pm_id="pragmatist",
                market_state=self.packet,
                run_id=f"pm-prag-{instrument}",
                evidence_cutoff="2026-10-16T12:00:00-04:00",
                review_packet_id="p",
                review_packet_sha256="h",
            )
            self.assertEqual(books["pms"]["pragmatist"]["history"][-1]["result"], "blocked_admission")

    def test_freeze_trade_permissions_copy_gate_fields(self) -> None:
        gate = evaluate_gate(rows=_scored_rows_g5(), families=self.families, positions=self.positions)
        launch = {"stages": {"03_quality_gate": {"details": gate}}}
        permissions = _trade_permissions(launch)
        self.assertEqual(sorted(permissions["restricted_seats"]), ["pragmatist", "value-guy"])
        self.assertEqual(permissions["quarantine_reason"], "unsupported_mark_source")
        self.assertEqual(
            {row["position_id"] for row in permissions["quarantined_positions"]},
            {"pos-f895a4694dd7", "pm-pragmatist-3afafe53c6d7"},
        )
        self.assertEqual(permissions["hold_decisions_emitted"], 0)
        self.assertFalse(permissions["synthetic_holds"])


class ValuationRestoredAdmissionTests(unittest.TestCase):
    def test_marks_return_without_reopening_nz_entry(self) -> None:
        packet = _fresh_market_packet()
        families = _families(packet)
        seat = empty_seat("value-guy")
        seat["positions"].append(_value_guy_nz_position())
        refresh_positions(seat["positions"], packet)
        mark_to_market(seat)
        pos = seat["positions"][0]
        self.assertEqual(pos["mark_price"], -23)
        self.assertFalse(pos["pnl_unavailable"])

        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 2.7,
                "asset_class": "rates",
                "expression_memo": _rates_memo("CORRA_2027-03"),
            },
            families=families,
            run_id="tr-us-after-mark",
            when=WHEN_OCT16,
            market_state=packet,
        )
        self.assertEqual(len(seat["positions"]), 2)

        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "NZ-US_10Y",
                "side": "short",
                "notional_usd": 10_000_000,
                "price": -23,
                "asset_class": "rates_rv",
                "expression_memo": _rates_memo("NZ-US_10Y", asset_class="rates_rv"),
            },
            families=families,
            run_id="tr-nz-still-blocked",
            when=WHEN_OCT16,
            market_state=packet,
        )
        nz_positions = [p for p in seat["positions"] if p["instrument"] == "NZ-US_10Y"]
        self.assertEqual(len(nz_positions), 1)
        self.assertEqual(nz_positions[0]["position_id"], "pos-f895a4694dd7")
        self.assertEqual(nz_positions[0]["notional_usd"], 80_000_000)


class BadProvenanceAdmissionTests(unittest.TestCase):
    def test_stale_or_missing_rv_blocks_marks_and_nz_entry(self) -> None:
        stale_packet = _fresh_market_packet()
        stale_packet["rates"]["NZ"] = {
            "status": "stale",
            "latest_observation": "2026-10-01",
            "tenors": {"10Y": {"value": 4.98, "as_of": "2026-10-01"}},
        }
        stale_packet["rate_rv"] = {"NZ-US_10Y": {"bps": -23, "as_of": "2026-10-01", "status": "ok"}}
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(stale_packet, "NZ-US_10Y", asset_class="rates_rv")
        with self.assertRaises(FreshnessError) as ctx:
            assert_action_allowed(
                "OPEN",
                _families(stale_packet),
                seat="value-guy",
                instrument="NZ-US_10Y",
                asset_class="rates_rv",
            )
        self.assertIn("unsupported_mark_source", str(ctx.exception))

        null_rv = _fresh_market_packet()
        null_rv["rate_rv"] = {"NZ-US_10Y": {"bps": None, "as_of": "2026-10-13", "status": "ok"}}
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(null_rv, "NZ-US_10Y", asset_class="rates_rv")
        with self.assertRaises(FreshnessError) as ctx2:
            assert_action_allowed(
                "OPEN",
                _families(null_rv),
                seat="value-guy",
                instrument="NZ-US_10Y",
                asset_class="rates_rv",
            )
        self.assertIn("unsupported_mark_source", str(ctx2.exception))

    def test_approved_instrument_invalid_rates_and_unknown_sovereign(self) -> None:
        invalid_us = _fresh_market_packet()
        invalid_us["rates"]["US"] = {
            "status": "invalid",
            "latest_observation": "2026-10-13",
            "tenors": {"10Y": {"value": 5.21, "as_of": "2026-10-13"}},
        }
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(invalid_us, "US_10Y", asset_class="rates")

        with self.assertRaises(FreshnessError) as ctx:
            assert_action_allowed(
                "OPEN",
                _families(_fresh_market_packet()),
                seat="rate-hawk",
                instrument="ZZ_10Y",
                asset_class="rates",
            )
        self.assertIn("entry_not_approved", str(ctx.exception))


class ApprovedUnmarkableBookTests(unittest.TestCase):
    def test_stale_ca_usdcad_still_halts_book(self) -> None:
        packet = _fresh_market_packet(
            stale_sources=["CA_rates"],
            preflight_stale_sources=["CA_rates"],
        )
        packet["rates"]["CA"] = {"status": "stale", "latest_observation": "2026-10-08"}
        families = _families(packet, family_status="stale")
        positions = [
            {
                "position_id": "pos-cad",
                "seat": "dollar-king",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
            }
        ]
        result = evaluate_gate(rows=_scored_rows_g5(), families=families, positions=positions)
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["reason"], "existing_book_unmarkable")
        self.assertIn("US", result["trade_eligible_countries"])


if __name__ == "__main__":
    unittest.main()
