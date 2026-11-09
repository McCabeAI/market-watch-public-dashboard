"""Isolation and last-good persistence for USD SOFR vs EUR ESR."""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from scripts.rates.short_rate_isolation import (
    collect_usd_eur_short_rates,
    run_isolated,
)
from scripts.rates.short_rate_store import (
    load_store,
    recall,
    remember_fresh,
    save_store,
)


def _row(obs: str = "2026-11-05", rate: float = 4.0) -> dict:
    return {
        "expiry": "2026-12",
        "implied_rate": rate,
        "observation_date": obs,
        "as_of": obs,
    }


def _rows(obs: str = "2026-11-05", rate: float = 4.0) -> list[dict]:
    return [_row(obs, rate)]


def _acquire_ok(obs: str = "2026-11-05", method: str = "test official"):
    def _inner(_fetch, *, today, benchmark, last_official=None):
        prov = {"bench": benchmark, "last": last_official is not None}
        rows = _rows(obs)
        if method.upper().startswith("ESR"):
            for row in rows:
                row["mark_kind"] = "official_settlement"
                row["trade_date_verified"] = True
        return (rows, f"https://example/{obs}", method, prov)

    return _inner


class ShortRateIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmp.name) / "short_rate_last_good.json"
        self.today = date(2026, 11, 6)

    def tearDown(self):
        self.tmp.cleanup()

    def _collect(
        self,
        *,
        sr1=None,
        sr3=None,
        esr=None,
        today=None,
    ):
        return collect_usd_eur_short_rates(
            today=today or self.today,
            fetch_bytes=lambda *a, **k: b"",
            benchmark_usd=3.85,
            benchmark_eur=2.15,
            store_path=self.store_path,
            acquire_sr1=sr1 or _acquire_ok("2026-11-05", "SR1 official"),
            acquire_sr3=sr3 or _acquire_ok("2026-11-05", "SR3 official"),
            acquire_esr=esr or _acquire_ok("2026-11-06", "ESR official"),
        )

    def test_both_usd_and_eur_succeed(self):
        out = self._collect()
        self.assertEqual(out["SR1"]["status"], "ok")
        self.assertEqual(out["SR3"]["status"], "ok")
        self.assertEqual(out["ESR"]["status"], "ok")
        self.assertEqual(out["SR1"]["freshness"], "fresh")
        self.assertEqual(out["ESR"]["freshness"], "fresh")
        self.assertEqual(out["SR1"]["as_of"], "2026-11-05")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-06")
        store = load_store(self.store_path)
        self.assertIn("SR1", store["curves"])
        self.assertIn("ESR", store["curves"])
        self.assertEqual(store["curves"]["SR1"]["as_of"], "2026-11-05")
        self.assertEqual(store["curves"]["ESR"]["as_of"], "2026-11-06")

    def test_esr_raises_sr_fresh_retains_esr(self):
        save_store(
            self.store_path,
            remember_fresh(
                {"version": 1, "curves": {}},
                "ESR",
                rows=_rows("2026-11-04"),
                as_of="2026-11-04",
                source="seed",
                source_url="https://seed",
                mark_kind="official_settlement",
                provenance={},
            ),
        )

        def esr_fail(*_a, **_k):
            raise ValueError("ESR down")

        out = self._collect(esr=esr_fail)
        self.assertEqual(out["SR1"]["status"], "ok")
        self.assertEqual(out["SR3"]["status"], "ok")
        self.assertEqual(out["ESR"]["status"], "stale")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-04")
        self.assertNotIn("ESR down", out["SR1"].get("error") or "")
        self.assertTrue(out["ESR"]["retained"])
        store = load_store(self.store_path)
        self.assertEqual(store["curves"]["ESR"]["as_of"], "2026-11-04")

    def test_sr3_raises_others_fresh(self):
        def sr3_fail(*_a, **_k):
            raise RuntimeError("SR3 broken")

        out = self._collect(sr3=sr3_fail)
        self.assertEqual(out["SR1"]["status"], "ok")
        self.assertEqual(out["ESR"]["status"], "ok")
        self.assertEqual(out["SR3"]["status"], "unavailable")
        self.assertIn("SR3 broken", out["SR3"]["error"])

    def test_all_raise_within_ttl_each_stale(self):
        for key, obs in (("SR1", "2026-11-05"), ("SR3", "2026-11-04"), ("ESR", "2026-11-03")):
            store = load_store(self.store_path)
            store = remember_fresh(
                store,
                key,
                rows=_rows(obs),
                as_of=obs,
                source=key,
                source_url=None,
                mark_kind="official_settlement",
            )
            save_store(self.store_path, store)

        def boom(*_a, **_k):
            raise ValueError("all down")

        out = self._collect(sr1=boom, sr3=boom, esr=boom)
        self.assertEqual(out["SR1"]["status"], "stale")
        self.assertEqual(out["SR3"]["status"], "stale")
        self.assertEqual(out["ESR"]["status"], "stale")
        self.assertEqual(out["SR1"]["as_of"], "2026-11-05")
        self.assertEqual(out["SR3"]["as_of"], "2026-11-04")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-03")

    def test_all_raise_expired_unavailable_rows_empty(self):
        old = "2026-10-20"
        store = {"version": 1, "curves": {}}
        for key in ("SR1", "SR3", "ESR"):
            store = remember_fresh(
                store,
                key,
                rows=_rows(old),
                as_of=old,
                source=key,
                source_url=None,
                mark_kind="official_settlement",
            )
        save_store(self.store_path, store)

        def boom(*_a, **_k):
            raise ValueError("fetch failed")

        out = self._collect(sr1=boom, sr3=boom, esr=boom, today=date(2026, 11, 6))
        for key in ("SR1", "SR3", "ESR"):
            self.assertEqual(out[key]["status"], "unavailable")
            self.assertEqual(out[key]["rows"], [])
            self.assertIn(old, out[key]["error"])
        still = load_store(self.store_path)
        self.assertEqual(still["curves"]["SR1"]["as_of"], old)

    def test_esr_only_failure_mode_sr_still_fresh(self):
        def esr_fail(*_a, **_k):
            raise ValueError("official and fallback failed")

        out = self._collect(esr=esr_fail)
        self.assertEqual(out["SR1"]["freshness"], "fresh")
        self.assertEqual(out["SR3"]["freshness"], "fresh")
        self.assertIn("unavailable", (out["ESR"]["status"], out["ESR"]["freshness"]))

    def test_refresh_replaces_only_updated_curve(self):
        out1 = self._collect(
            esr=_acquire_ok("2026-11-05"),
            sr3=_acquire_ok("2026-11-05"),
        )
        self.assertEqual(out1["ESR"]["as_of"], "2026-11-05")

        out2 = self._collect(esr=_acquire_ok("2026-11-06"))
        self.assertEqual(out2["ESR"]["as_of"], "2026-11-06")
        store = load_store(self.store_path)
        self.assertEqual(store["curves"]["ESR"]["as_of"], "2026-11-06")
        self.assertEqual(store["curves"]["SR3"]["as_of"], "2026-11-05")

    def test_future_as_of_not_remembered(self):
        out = self._collect(esr=_acquire_ok("2026-12-01"))
        self.assertEqual(out["ESR"]["status"], "unavailable")
        self.assertEqual(out["ESR"]["rows"], [])
        store = load_store(self.store_path)
        self.assertNotIn("ESR", store.get("curves", {}))

    def test_run_isolated_one_raises_other_returns(self):
        def slow_fail():
            time.sleep(0.05)
            raise RuntimeError("boom")

        def fast_ok():
            return "ok-value"

        results = run_isolated({"bad": slow_fail, "good": fast_ok})
        self.assertEqual(results["good"]["status"], "ok")
        self.assertEqual(results["good"]["value"], "ok-value")
        self.assertEqual(results["bad"]["status"], "error")
        self.assertIn("boom", results["bad"]["error"])

    def test_remember_fresh_esr_does_not_alias_sr3_rows(self):
        sr3_rows = _rows("2026-11-05", rate=3.9)
        store = {"version": 1, "curves": {}}
        store = remember_fresh(
            store,
            "SR3",
            rows=sr3_rows,
            as_of="2026-11-05",
            source="SR3",
            source_url=None,
            mark_kind="official_settlement",
        )
        esr_rows = _rows("2026-11-05", rate=2.0)
        store = remember_fresh(
            store,
            "ESR",
            rows=esr_rows,
            as_of="2026-11-05",
            source="ESR",
            source_url=None,
            mark_kind="official_settlement",
        )
        esr_rows[0]["implied_rate"] = 99.0
        self.assertNotEqual(
            store["curves"]["SR3"]["rows"][0]["implied_rate"],
            99.0,
        )

    def test_recall_missing_unavailable(self):
        recalled = recall({"version": 1, "curves": {}}, "SR1", today=self.today)
        self.assertEqual(recalled["status"], "unavailable")
        self.assertEqual(recalled["rows"], [])

    def test_corrupt_store_still_fetches_fresh(self):
        self.store_path.write_text("{not json", encoding="utf-8")

        out = self._collect()
        self.assertEqual(out["SR1"]["status"], "ok")
        store = load_store(self.store_path)
        self.assertIn("SR1", store["curves"])

    def test_sr_acquire_3_tuple(self):
        def sr1_three(_f, *, today, benchmark):
            return (_rows(), "https://sr1", "SR1 three-tuple")

        out = self._collect(sr1=sr1_three)
        self.assertEqual(out["SR1"]["status"], "ok")
        self.assertEqual(out["SR1"]["provenance"], {})

    def test_esr_sunday_nov6_fresh(self):
        out = self._collect(
            today=date(2026, 11, 8),
            esr=_acquire_ok("2026-11-06", "ESR official"),
        )
        self.assertEqual(out["ESR"]["freshness"], "fresh")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-06")
        self.assertTrue(out["ESR"]["mark_fresh"])

    def test_esr_sunday_nov3_stale_not_fresh(self):
        out = self._collect(
            today=date(2026, 11, 8),
            esr=_acquire_ok("2026-11-03", "ESR official"),
        )
        self.assertEqual(out["ESR"]["freshness"], "stale")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-03")
        self.assertFalse(out["ESR"]["mark_fresh"])
        self.assertEqual(out["ESR"]["status"], "stale")

    def test_esr_fetch_fail_recalls_nov6_stale_sunday(self):
        save_store(
            self.store_path,
            remember_fresh(
                {"version": 1, "curves": {}},
                "ESR",
                rows=_rows("2026-11-06"),
                as_of="2026-11-06",
                source="seed",
                source_url="https://seed",
                mark_kind="official_settlement",
                provenance={},
            ),
        )

        def esr_fail(*_a, **_k):
            raise ValueError("ESR down")

        out = self._collect(esr=esr_fail, today=date(2026, 11, 8))
        self.assertEqual(out["ESR"]["status"], "stale")
        self.assertEqual(out["ESR"]["as_of"], "2026-11-06")
        self.assertFalse(out["ESR"]["mark_fresh"])
        self.assertEqual(out["ESR"]["freshness"], "stale")

    def test_fetch_failure_store_file_bytes_unchanged(self):
        save_store(
            self.store_path,
            remember_fresh(
                {"version": 1, "curves": {}},
                "ESR",
                rows=_rows("2026-11-06"),
                as_of="2026-11-06",
                source="seed",
                source_url="https://seed",
                mark_kind="official_settlement",
                provenance={},
            ),
        )
        before = self.store_path.read_bytes()

        def boom(*_a, **_k):
            raise ValueError("all down")

        self._collect(sr1=boom, sr3=boom, esr=boom)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_sr3_three_days_before_today_still_fresh(self):
        obs = (date(2026, 11, 8) - __import__("datetime").timedelta(days=3)).isoformat()
        out = self._collect(
            today=date(2026, 11, 8),
            sr3=_acquire_ok(obs, "SR3 official"),
        )
        self.assertEqual(out["SR3"]["freshness"], "fresh")
        self.assertEqual(out["SR3"]["status"], "ok")
        self.assertEqual(out["SR3"]["as_of"], obs)


if __name__ == "__main__":
    unittest.main()
