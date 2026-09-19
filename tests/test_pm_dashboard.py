from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_trader_book_tab import apply_trader_book_tab
from scripts.pm.cli import init_layer
from scripts.pm.public import build_public_state, emit_pm_json
from scripts.pm.store import PMStore


REPO = Path(__file__).resolve().parents[1]


class PMDashboardTests(unittest.TestCase):
    def test_public_json_renders_awaiting_state(self) -> None:
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
            self.assertEqual(len(public["comparison"]), 4)
            self.assertIn("data_requests", public)

    def test_trader_book_js_has_pm_section_without_redesigning_seats(self) -> None:
        js = (REPO / "patch_v13" / "trader-book.js").read_text(encoding="utf-8")
        html = (REPO / "patch_v13" / "trader_book_page.html").read_text(encoding="utf-8")
        self.assertIn("Portfolio Managers", js)
        self.assertIn("pm-books.json", js)
        self.assertIn("PM Data Requests", js)
        self.assertIn("awaiting_chatgpt_decision", js)
        self.assertIn("Overnight 14-seat books", html)
        self.assertIn("Fourteen paper traders compete", html)

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


if __name__ == "__main__":
    unittest.main()
