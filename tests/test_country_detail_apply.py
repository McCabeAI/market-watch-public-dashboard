"""Glue test for injecting Country Detail into dashboard HTML."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.apply_country_detail import main

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "temperature_scores.json"

PAGE = """<!DOCTYPE html>
<html><head><style>
body { color: #111; }
</style></head><body>
<div class="cdetail us"><div class="temp-inputs"><div class="inner"><span>nested-us</span></div><p>US-STALE-SENTENCE-alpha</p></div><p>keep-us-tail</p></div>
<div class="cdetail ca"><div class="temp-inputs"><div><p>nested-ca</p></div><p>CA-STALE-SENTENCE-beta</p></div><p>keep-ca-tail</p></div>
</body></html>
"""


class CountryDetailApplyTest(unittest.TestCase):
    def test_replaces_temp_inputs_without_touching_scores(self) -> None:
        before = hashlib.sha256(SCORES.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(PAGE, encoding="utf-8")
            main([str(path)])
            out = path.read_text(encoding="utf-8")
        after = hashlib.sha256(SCORES.read_bytes()).hexdigest()

        self.assertEqual(before, after)
        self.assertNotIn("US-STALE-SENTENCE-alpha", out)
        self.assertNotIn("CA-STALE-SENTENCE-beta", out)
        self.assertIn("keep-us-tail", out)
        self.assertIn("keep-ca-tail", out)
        self.assertIn('class="country-detail"', out)
        self.assertIn('data-country="US"', out)
        self.assertIn('data-country="CA"', out)
        self.assertIn('class="temp-dimension score-detail"', out)
        self.assertIn("Country Detail — mobile-first", out)
        self.assertEqual(out.count("Country Detail — mobile-first"), 1)
        self.assertNotIn('class="temp-inputs"', out)
        us = out.split('<div class="cdetail ca">', 1)[0]
        self.assertLess(us.find('class="score-compact"'), us.find('class="what-matters-now"'))
        self.assertLess(us.find('class="what-matters-now"'), us.find("keep-us-tail"))
        self.assertLess(us.find("keep-us-tail"), us.find('class="country-evidence"'))
        self.assertIn("country-detail-evidence-filter", out)
        self.assertIn("evidence-search", out)
        self.assertIn("addEventListener('input'", out)
        self.assertIn("addEventListener('click'", out)
        self.assertEqual(out.count("country-detail-evidence-filter"), 1)


if __name__ == "__main__":
    unittest.main()
