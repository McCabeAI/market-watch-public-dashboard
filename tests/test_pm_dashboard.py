from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_trader_book_tab import apply_trader_book_tab
from scripts.pm.cli import init_layer
from scripts.pm.books import apply_decision, empty_books
from scripts.pm.constants import RISK_CAPITAL_LIMIT_USD
from scripts.pm.errors import SchemaError
from scripts.pm.public import build_public_state, emit_pm_json, validate_public_packet
from scripts.pm.store import PMStore
from tests.test_pm_books import MARKET, _open


REPO = Path(__file__).resolve().parents[1]


class PMDashboardTests(unittest.TestCase):
    def test_validate_public_packet_accepts_initial_awaiting_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PMStore(root=REPO, state_root=Path(tmp))
            init_layer(store)
            public = store.read_json(store.public_path())
            self.assertEqual(public["pm_count"], 4)
            statuses = {row["pm_id"]: row["decision_status"] for row in public["pms"]}
            self.assertEqual(statuses["chatgpt"], "awaiting_chatgpt_decision")
            self.assertEqual(statuses["swinger"], "awaiting_automated_pm_review")
            self.assertEqual(statuses["pragmatist"], "awaiting_automated_pm_review")
            self.assertEqual(statuses["grinder"], "awaiting_automated_pm_review")
            validate_public_packet(public)
            self.assertEqual(len(public["comparison"]), 4)
            self.assertIn("data_requests", public)

    def _mixed_state_books(self):
        books = empty_books(trader_room_run_id="tr-mixed")
        books = apply_decision(
            books,
            {
                "pm_id": "swinger",
                "actions": [_open(notional=200_000_000)],
                "thesis": "swing",
                "invalidation": "swing invalidated",
            },
            pm_id="swinger",
            market_state=MARKET,
            run_id="tr-mixed",
            evidence_cutoff="2026-09-19T21:40:00Z",
            review_packet_id="p-s",
            review_packet_sha256="h-s",
        )
        books = apply_decision(
            books,
            {
                "pm_id": "pragmatist",
                "actions": [_open(instrument="AUDUSD", notional=50_000_000)],
                "thesis": "grind",
                "invalidation": "grind invalidated",
            },
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="tr-mixed",
            evidence_cutoff="2026-09-19T21:40:00Z",
            review_packet_id="p-p",
            review_packet_sha256="h-p",
        )
        books = apply_decision(
            books,
            {"pm_id": "grinder", "actions": [{"action": "NO_TRADE"}], "thesis": "cash"},
            pm_id="grinder",
            market_state=MARKET,
            run_id="tr-mixed",
            evidence_cutoff="2026-09-19T21:40:00Z",
            review_packet_id="p-g",
            review_packet_sha256="h-g",
        )
        return books

    def test_validate_public_packet_mixed_active_no_trade_awaiting(self) -> None:
        from scripts.pm.data_requests import empty_registry

        books = self._mixed_state_books()
        public = build_public_state(books, empty_registry())
        statuses = {row["pm_id"]: row["decision_status"] for row in public["pms"]}
        self.assertEqual(statuses["chatgpt"], "awaiting_chatgpt_decision")
        self.assertEqual(statuses["swinger"], "active")
        self.assertEqual(statuses["pragmatist"], "active")
        self.assertEqual(statuses["grinder"], "no_trade")
        swinger = next(row for row in public["pms"] if row["pm_id"] == "swinger")
        self.assertEqual(len(swinger["positions"]), 1)
        self.assertEqual(swinger["positions"][0]["thesis"], "swing")
        self.assertEqual(swinger["positions"][0]["invalidation"], "swing invalidated")
        self.assertTrue(swinger["positions"][0]["opened_at"])
        validate_public_packet(public)

    def test_publication_emit_succeeds_for_mixed_state(self) -> None:
        from scripts.pm.data_requests import empty_registry

        with tempfile.TemporaryDirectory() as tmp:
            store = PMStore(root=REPO, state_root=Path(tmp))
            books = self._mixed_state_books()
            registry = empty_registry()
            store.write_books(books)
            store.write_requests(registry)
            public = build_public_state(books, registry)
            store.write_public(public)
            site = Path(tmp) / "_site"
            emit_pm_json(store, site)
            packet = json.loads((site / "pm-books.json").read_text(encoding="utf-8"))
            validate_public_packet(packet)

    def test_trader_book_js_has_pm_section_without_redesigning_seats(self) -> None:
        js = (REPO / "patch_v13" / "trader-book.js").read_text(encoding="utf-8")
        html = (REPO / "patch_v13" / "trader_book_page.html").read_text(encoding="utf-8")
        self.assertIn("Portfolio Managers", js)
        self.assertIn("pm-books.json", js)
        self.assertIn("PM Data Requests", js)
        self.assertIn("awaiting_chatgpt_decision", js)
        self.assertIn("function renderPosition", js)
        self.assertEqual(js.count("positions.map(renderPosition)"), 2)
        self.assertIn("14 Traders + 4 Portfolio Managers", html)
        self.assertIn("14 Traders · Total P&amp;L", html)
        self.assertIn("4 PMs · Total P&amp;L", html)
        self.assertIn("tb-trader-total", js)
        self.assertIn("tb-pm-total", js)
        self.assertIn("tb-position-trade", js)
        self.assertIn("tb-direction", js)
        self.assertIn("Risk limit", js)

    def test_emit_and_tab_stay_additive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "patch_v13").mkdir()
            for name in ("trader_book.css", "trader_book_page.html", "trader-book.js"):
                (root / "patch_v13" / name).write_text(
                    (REPO / "patch_v13" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            site = root / "_site"
            site.mkdir()
            html = """<style></style>
<input id="p-marketdata" name="page" type="radio"/>
<label for="p-marketdata">Market Data</label>
<section class="page marketdata">Market Data · official snapshot</section>
<section class="page relative"></section>
<div>Last 24 Hours · Desk Summary</div>
<div>Live 1–100 Score Board</div>
<div>7-Day Quick Digest</div>
"""
            # inject CSS anchors used by apply_trader_book_tab
            html = html.replace(
                "<style></style>",
                "<style>#p-marketdata:checked~.app .nav label[for=p-marketdata],x{}\n#p-marketdata:checked~.app .marketdata,y{}</style>",
            )
            target = site / "index.html"
            target.write_text(html, encoding="utf-8")
            apply_trader_book_tab(target, repo_root=root)
            out = target.read_text(encoding="utf-8")
            self.assertIn("Trader Book · paper P&L", out)
            self.assertIn("Last 24 Hours · Desk Summary", out)
            store = PMStore(root=REPO, state_root=root)
            init_layer(store)
            emit_pm_json(store, site)
            packet = json.loads((site / "pm-books.json").read_text(encoding="utf-8"))
            self.assertEqual(packet["pm_count"], 4)

    def test_stale_pre_risk_capital_public_json_is_rebuilt_from_canonical_books(self) -> None:
        from copy import deepcopy

        from scripts.pm.data_requests import empty_registry

        stale_repo = json.loads((REPO / "data" / "pm" / "public" / "latest.json").read_text(encoding="utf-8"))
        self.assertNotEqual(stale_repo.get("risk_capital_limit_usd"), RISK_CAPITAL_LIMIT_USD)
        with self.assertRaises(SchemaError):
            validate_public_packet(stale_repo)

        books_before = json.loads((REPO / "data" / "pm" / "books" / "latest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            store = PMStore(root=REPO, state_root=Path(tmp))
            store.write_books(deepcopy(books_before))
            store.write_requests(empty_registry())
            store.write_public(stale_repo)
            with self.assertRaises(SchemaError):
                validate_public_packet(store.read_json(store.public_path()))
            site = Path(tmp) / "_site"
            emit_pm_json(store, site)
            packet = json.loads((site / "pm-books.json").read_text(encoding="utf-8"))
            validate_public_packet(packet)
            self.assertEqual(packet["risk_capital_limit_usd"], RISK_CAPITAL_LIMIT_USD)
            self.assertEqual(packet["pm_count"], 4)
            persisted = store.read_json(store.public_path())
            self.assertNotEqual(persisted.get("risk_capital_limit_usd"), RISK_CAPITAL_LIMIT_USD)
            books_after = store.read_books()
            for pm_id, item in books_after["pms"].items():
                orig = books_before["pms"][pm_id]
                self.assertEqual(item["realized_pnl_usd"], orig["realized_pnl_usd"])
                self.assertEqual(len(item["positions"]), len(orig["positions"]))
                for pos, old in zip(item["positions"], orig["positions"]):
                    self.assertEqual(pos["position_id"], old["position_id"])
                    self.assertEqual(pos["notional_usd"], old["notional_usd"])

        site = Path(tempfile.mkdtemp())
        try:
            emit_pm_json(PMStore(root=REPO), site)
            live = json.loads((site / "pm-books.json").read_text(encoding="utf-8"))
            validate_public_packet(live)
            self.assertEqual(live["risk_capital_limit_usd"], RISK_CAPITAL_LIMIT_USD)
        finally:
            import shutil

            shutil.rmtree(site, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
