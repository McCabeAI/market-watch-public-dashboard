"""CSS contract for country-detail temperature legend mobile layout."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "scripts" / "country_detail" / "country_detail.css").read_text(encoding="utf-8")


class TemperatureLegendCssTests(unittest.TestCase):
    def test_legend_defaults_to_three_columns_without_narrow_two_column_breakpoint(self) -> None:
        legend_block = re.search(r"\.country-detail \.temp-legend\{([^}]+)\}", CSS)
        self.assertIsNotNone(legend_block)
        assert legend_block is not None
        self.assertIn("repeat(3,minmax(0,1fr))", legend_block.group(1))
        self.assertNotRegex(
            CSS,
            r"@media \(min-width:375px\)\{[^}]*\.country-detail \.temp-legend",
        )

    def test_tiles_drop_bordered_card_boxes_and_stack_label_above_value(self) -> None:
        self.assertIn(".country-detail .temp-tile-body{", CSS)
        tile_block = re.search(r"\.country-detail \.temp-tile\{([^}]+)\}", CSS)
        self.assertIsNotNone(tile_block)
        assert tile_block is not None
        body = tile_block.group(1)
        self.assertIn("background:transparent", body)
        self.assertIn("border:none", body)
        body_block = re.search(r"\.country-detail \.temp-tile-body\{([^}]+)\}", CSS)
        self.assertIsNotNone(body_block)
        assert body_block is not None
        self.assertIn("flex-direction:column", body_block.group(1))
