import tempfile
import unittest
from pathlib import Path

from scripts.apply_sal_market_data import apply


class ApplySalTests(unittest.TestCase):
    def test_injects_once_before_top_drivers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index.html"
            css = root / "sal.css"
            fragment = root / "sal.html"
            index.write_text('<html><style>.x{}</style><body><div class="stitle">Top Market Drivers</div></body></html>')
            css.write_text('.sal-market{}')
            fragment.write_text('<section id="sal-market-data">rates</section>')
            apply(index, css, fragment)
            out = index.read_text()
            self.assertEqual(out.count('id="sal-market-data"'), 1)
            self.assertIn('.sal-market{}\n</style>', out)
            self.assertLess(out.index('id="sal-market-data"'), out.index('Top Market Drivers'))

    def test_rejects_duplicate_patch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index.html"
            css = root / "sal.css"
            fragment = root / "sal.html"
            index.write_text('<style></style><section id="sal-market-data"></section><div class="stitle">Top Market Drivers</div>')
            css.write_text('.sal-market{}')
            fragment.write_text('<section id="sal-market-data">rates</section>')
            with self.assertRaises(SystemExit):
                apply(index, css, fragment)


if __name__ == "__main__":
    unittest.main()
