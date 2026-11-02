"""Static checks for Market Data curve table contrast and mobile card layout."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "patch_v12" / "market_data.css").read_text(encoding="utf-8")
JS = (ROOT / "patch_v12" / "market-data.js").read_text(encoding="utf-8")

DARK_PANEL_TOKENS = ("var(--mw-panel-2)", "var(--md-panel)", "var(--mw-panel)")
LIGHT_INK_TOKENS = ("var(--md-ink)", "var(--mw-ink)", "var(--mw-ink-2)")
V6_LIGHT_ROW_BG = ("#f7fafc", "#eef5f9")


class MarketDataCurveMobileTests(unittest.TestCase):
    def test_even_row_uses_dark_panel_and_light_ink(self):
        m = re.search(
            r"\.marketdata\s+\.md-table\s+tbody\s+tr:nth-child\(even\)[^{]*\{[^}]+\}",
            CSS,
            re.S,
        )
        self.assertIsNotNone(m, "missing .marketdata .md-table even-row override")
        block = m.group(0)
        self.assertTrue(
            any(tok in block for tok in DARK_PANEL_TOKENS),
            f"even-row rule must use a dark panel token; got: {block[:200]}",
        )
        self.assertTrue(
            any(tok in block for tok in LIGHT_INK_TOKENS),
            f"even-row rule must set light ink color; got: {block[:200]}",
        )
        self.assertIn("td", block, "even-row override must include td for specificity")

    def test_no_v6_light_zebra_colors_in_market_data_css(self):
        lowered = CSS.lower()
        for color in V6_LIGHT_ROW_BG:
            self.assertNotIn(
                color,
                lowered,
                f"v6 light row background {color} must not appear in market_data.css",
            )

    def test_mobile_breakpoint_stacks_table_as_cards(self):
        m = re.search(r"@media\s*\(\s*max-width\s*:\s*430px\s*\)\s*\{", CSS)
        self.assertIsNotNone(m, "expected @media (max-width: 430px) block")
        start = m.start()
        depth = 0
        end = start
        for i, ch in enumerate(CSS[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = CSS[start:end]
        self.assertRegex(
            block,
            r"\.marketdata\s+\.md-table[^\{]*\{[^}]*min-width\s*:\s*0",
            "430px block must set .md-table min-width to 0",
        )
        self.assertRegex(
            block,
            r"\.marketdata\s+\.md-table\s+tr[^\{]*\{[^}]*display\s*:\s*block",
            "430px block must display rows as block (card stacking)",
        )

    def test_table_function_emits_data_labels_and_evidence(self):
        fn = re.search(r"function\s+table\s*\([^)]*\)\s*\{", JS)
        self.assertIsNotNone(fn, "table(rows) not found")
        start = fn.start()
        depth = 0
        end = start
        for i, ch in enumerate(JS[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        body = JS[start:end]
        for label in (
            "data-label=\"Move z\"",
            "data-label=\"Historical position\"",
            "data-label=\"Level z\"",
            "data-label=\"Observed\"",
        ):
            self.assertIn(label, body, f"missing {label} in table()")
        self.assertIn("data-label=\"${esc(hChange)}\"", body)
        self.assertIn("const hChange=`${horizon} change`", body)
        self.assertNotRegex(
            body,
            r"data-label=\"5D change\"",
            "horizon change label must follow horizon variable, not hard-coded 5D",
        )
        self.assertIn("<details>", body)
        self.assertIn("${evidence(s)}", body)


if __name__ == "__main__":
    unittest.main()
