#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.asx_futures_cache import load_cache, save_product, validate_record


class AsxFuturesCacheTests(unittest.TestCase):
    def test_load_missing_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "missing.json")
            data = load_cache(path)
            self.assertEqual(data, {"version": 1, "products": {}})

    def test_corrupt_and_empty_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text("", encoding="utf-8")
            self.assertEqual(load_cache(str(path))["products"], {})
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_cache(str(path))["products"], {})

    def test_save_preserves_sibling_product(self) -> None:
        record_ib = {
            "product": "IB",
            "session_date": "2026-11-06",
            "as_of": "2026-11-06",
            "source_url": "https://example.test/ib",
            "contracts": [
                {
                    "expiry": "2026-12",
                    "price": 95.6,
                    "implied_rate": 4.4,
                    "as_of": "2026-11-06",
                }
            ],
        }
        record_ir = {
            "product": "IR",
            "session_date": "2026-11-05",
            "as_of": "2026-11-05",
            "source_url": "https://example.test/ir",
            "contracts": [
                {
                    "expiry": "2026-12",
                    "price": 95.03,
                    "implied_rate": 4.97,
                    "as_of": "2026-11-05",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cache.json")
            save_product(path, "IB", record_ib)
            save_product(path, "IR", record_ir)
            loaded = load_cache(path)
            self.assertIn("IB", loaded["products"])
            self.assertIn("IR", loaded["products"])
            self.assertEqual(loaded["products"]["IB"]["session_date"], "2026-11-06")
            self.assertEqual(loaded["products"]["IR"]["session_date"], "2026-11-05")

    def test_validate_rejects_absurd_record(self) -> None:
        bad = {
            "product": "IB",
            "session_date": "2026-11-06",
            "as_of": "2026-11-05",
            "source_url": "",
            "contracts": [],
        }
        self.assertFalse(validate_record(bad, product="IB"))

    def test_validate_accepts_good_record(self) -> None:
        good = {
            "product": "IR",
            "session_date": "2026-11-06",
            "as_of": "2026-11-06",
            "source_url": "https://example.test",
            "contracts": [
                {
                    "expiry": "2026-12",
                    "price": 95.05,
                    "implied_rate": 4.95,
                    "as_of": "2026-11-06",
                }
            ],
        }
        self.assertTrue(validate_record(good, product="IR"))


if __name__ == "__main__":
    unittest.main()
