from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_trader_room_tab import apply_trader_room_tab
from scripts.trader_room_public import build_public_packet


class TraderRoomDashboardTests(unittest.TestCase):
    def test_tab_is_additive_and_separate_from_trader_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "patch_v14").mkdir()
            repo_root = Path(__file__).resolve().parents[1]
            for name in ("trader_room.css", "trader_room_page.html", "trader-room.js"):
                (root / "patch_v14" / name).write_text(
                    (repo_root / "patch_v14" / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            site = root / "_site"
            site.mkdir()
            html = """<style></style>
<input id="p-traderbook" name="page" type="radio"/>
<label for="p-traderbook">Trader Book</label>
<section class="page traderbook">Trader Book · paper P&amp;L</section>
<section class="page relative"></section>
<div>Last 24 Hours · Desk Summary</div>
<div>Live 1–100 Score Board</div>
<div>Market Data · official snapshot</div>
"""
            target = site / "index.html"
            target.write_text(html, encoding="utf-8")
            apply_trader_room_tab(target, repo_root=root)
            out = target.read_text(encoding="utf-8")
            self.assertIn('id="p-traderroom"', out)
            self.assertIn('for="p-traderroom">Trader Room</label>', out)
            self.assertIn("Trader Room · adversarial ideas", out)
            self.assertIn("Trader Book · paper P&amp;L", out)
            self.assertTrue((site / "trader-room.js").is_file())

    def test_empty_public_packet_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = build_public_packet(Path(tmp))
            self.assertFalse(packet["available"])
            self.assertEqual(packet["status"], "no_published_run")
            self.assertEqual(packet["trades"], [])

    def test_public_packet_includes_trade_entry_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "trader-room" / "runs" / "tr-live-1"
            (run / "submissions").mkdir(parents=True)
            (run / "rebuttals").mkdir()
            (run / "pm_handoff.json").write_text(
                json.dumps({"run_id": "tr-live-1", "status": "AWAITING_CHATGPT_ARBITRATION"}),
                encoding="utf-8",
            )
            (run / "evidence_packet.json").write_text(
                json.dumps({"run_id": "tr-live-1", "as_of": "2026-09-18T18:30:00Z", "packet_sha256": "abc", "known_gaps": []}),
                encoding="utf-8",
            )
            (run / "conflict_map.json").write_text(json.dumps({"conflicts": [{"id": "c1"}]}), encoding="utf-8")
            (run / "submissions" / "rate-hawk.json").write_text(
                json.dumps({
                    "agent": "rate-hawk",
                    "stance_summary": "Front-end repricing is too dovish.",
                    "confidence": 72,
                    "why_now": ["The market prices more easing than the frozen macro evidence supports."],
                    "trade": {
                        "instrument": "CAD 2Y",
                        "direction": "short duration",
                        "expression": "Pay Canada 2Y",
                        "horizon": "3 months",
                        "entry": None,
                        "target": None,
                        "invalidation": "Labor data rolls over sharply",
                    },
                }),
                encoding="utf-8",
            )
            packet = build_public_packet(root)
            self.assertTrue(packet["available"])
            self.assertEqual(packet["seat_count"], 1)
            self.assertEqual(packet["conflict_count"], 1)
            self.assertEqual(packet["trades"][0]["agent"], "rate-hawk")
            self.assertIn("market prices more easing", packet["trades"][0]["entry_reason"])
            self.assertEqual(packet["trades"][0]["trade"]["instrument"], "CAD 2Y")


if __name__ == "__main__":
    unittest.main()
