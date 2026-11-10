"""Integrator acceptance checks not covered elsewhere (news soft gate, inventory)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.overnight.errors import PublicationError
from scripts.overnight.publish import publication_gate
from scripts.overnight.store import OvernightStore

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "docs" / "publication_gate_inventory.json"


class PublicationAcceptanceTests(unittest.TestCase):
    def test_inventory_documents_soft_news_and_tab_marker_removal(self):
        gates = {row["id"]: row for row in json.loads(INVENTORY.read_text(encoding="utf-8"))["gates"]}
        self.assertEqual(gates["books.publish_check_news_html"]["decision"], "BECOME_ISSUE")
        self.assertIn("soft", gates["books.publish_check_news_html"].get("note", "").lower())
        self.assertIn("REMOVE", gates["render.trader_book_tab"].get("note", ""))

    def test_publish_gate_soft_skips_wall_clock_news_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "_site"
            site.mkdir()
            (site / "index.html").write_text("<html><body>placeholder</body></html>", encoding="utf-8")
            diag = Path(tmp) / "diag.jsonl"
            store = OvernightStore(root=REPO)
            ctx = {"as_of": "2020-01-01T00:00:00Z", "news": []}
            with mock.patch("scripts.overnight.publish.load_assembled", return_value=None):
                with mock.patch("scripts.overnight.publish.effective_public_news_context", return_value=ctx):
                    with mock.patch("scripts.overnight.publish.age_status", return_value="stale"):
                        with mock.patch.dict(os.environ, {"MW_RENDER_DIAGNOSTICS": str(diag)}):
                            gate = publication_gate(
                                store,
                                run_id=None,
                                require_dataset=False,
                                site_dir=site,
                                news_policy="soft",
                            )
            self.assertTrue(gate.get("may_publish"))
            self.assertTrue(diag.is_file())
            lines = [json.loads(line) for line in diag.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(row.get("code") == "news_freshness_soft" for row in lines))

    def test_publish_gate_strict_still_raises_on_stale_news(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "_site"
            site.mkdir()
            (site / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OvernightStore(root=REPO)
            ctx = {"as_of": "2020-01-01T00:00:00Z", "news": []}
            with mock.patch("scripts.overnight.publish.load_assembled", return_value=None):
                with mock.patch("scripts.overnight.publish.effective_public_news_context", return_value=ctx):
                    with mock.patch("scripts.overnight.publish.age_status", return_value="stale"):
                        with self.assertRaises(PublicationError):
                            publication_gate(
                                store,
                                run_id=None,
                                require_dataset=False,
                                site_dir=site,
                                news_policy="strict",
                            )


if __name__ == "__main__":
    unittest.main()
