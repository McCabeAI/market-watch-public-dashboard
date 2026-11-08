"""Two clean-run retention and CME runner probe tests (no network)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from unittest import mock
import urllib.error
from datetime import date
from pathlib import Path

from scripts.rates.cme_esr_runner_probe import build_probe
from scripts.rates.short_rate_isolation import collect_usd_eur_short_rates
from scripts.rates.short_rate_store import load_store

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cme_esr"
NOV6_BODY = (FIXTURE_DIR / "settlement_final_2026-11-06.json").read_text(encoding="utf-8")

OBS = "2026-11-06"
TODAY = date(2026, 11, 8)


def _row(obs: str = OBS, rate: float = 4.0) -> dict:
    return {
        "expiry": "2026-12",
        "implied_rate": rate,
        "observation_date": obs,
        "as_of": obs,
    }


def _rows(obs: str = OBS, rate: float = 4.0) -> list[dict]:
    return [_row(obs, rate)]


def _acquire_ok(obs: str = OBS, rate: float = 4.0, method: str = "test official"):
    def _inner(_fetch, *, today, benchmark, last_official=None):
        prov = {"bench": benchmark, "last": last_official is not None}
        return (_rows(obs, rate), f"https://example/{obs}", method, prov)

    return _inner


def _collect_in_dir(
    store_dir: Path,
    *,
    sr1=None,
    sr3=None,
    esr=None,
) -> dict:
    store_path = store_dir / "short_rate_last_good.json"
    return collect_usd_eur_short_rates(
        today=TODAY,
        fetch_bytes=lambda *a, **k: b"",
        benchmark_usd=3.85,
        benchmark_eur=2.15,
        store_path=store_path,
        acquire_sr1=sr1 or _acquire_ok(),
        acquire_sr3=sr3 or _acquire_ok(),
        acquire_esr=esr or _acquire_ok(method="ESR official"),
    )


class CmeEsrRunnerProbeTests(unittest.TestCase):
    def test_final_fixture_verified(self) -> None:
        body = NOV6_BODY.encode()

        def fetch(url: str, **_kwargs) -> bytes:
            return body

        report = build_probe(fetch, date(2026, 11, 6))
        self.assertEqual(report["runner_claim"], "verified")
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["usable_quarterly_count"] or 0, 4)

    def test_403_style_blocked(self) -> None:
        def fetch(url: str, **_kwargs) -> bytes:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        report = build_probe(fetch, date(2026, 11, 6))
        self.assertEqual(report["http_status"], 403)
        self.assertEqual(report["runner_claim"], "blocked_or_unconfirmed")
        self.assertFalse(report["ok"])

    def test_main_exits_clean_on_blocked(self) -> None:
        from scripts.rates import cme_esr_runner_probe

        def fake_fetch(url: str, **_kwargs) -> bytes:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        with mock.patch("scripts.market_state.fetch_bytes", fake_fetch):
            code = cme_esr_runner_probe.main(["--session", "2026-11-06"])
        self.assertEqual(code, 0)


class ShortRateCacheRunsTests(unittest.TestCase):
    def test_two_clean_run_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_a:
            dir_a = Path(tmp_a)
            out_a = _collect_in_dir(dir_a)
            store_a = dir_a / "short_rate_last_good.json"
            self.assertTrue(store_a.is_file())
            self.assertEqual(out_a["ESR"]["freshness"], "fresh")
            self.assertEqual(out_a["ESR"]["as_of"], OBS)

            with tempfile.TemporaryDirectory() as tmp_b:
                dir_b = Path(tmp_b)
                shutil.copy2(store_a, dir_b / "short_rate_last_good.json")

                def esr_fail(*_a, **_k):
                    raise ValueError("ESR blocked on runner")

                out_b = _collect_in_dir(
                    dir_b,
                    esr=esr_fail,
                    sr3=_acquire_ok(rate=4.12, method="SR3 refresh"),
                )
                self.assertEqual(out_b["ESR"]["freshness"], "stale")
                self.assertEqual(out_b["ESR"]["as_of"], OBS)
                self.assertNotEqual(out_b["ESR"]["freshness"], "fresh")
                self.assertEqual(out_b["SR3"]["freshness"], "fresh")
                self.assertEqual(out_b["SR3"]["rows"][0]["implied_rate"], 4.12)
                self.assertIn("ESR blocked", out_b["ESR"]["error"] or "")
                self.assertIsNone(out_b["SR3"].get("error"))

            with tempfile.TemporaryDirectory() as tmp_c:
                dir_c = Path(tmp_c)
                shutil.copy2(store_a, dir_c / "short_rate_last_good.json")

                def sr3_fail(*_a, **_k):
                    raise RuntimeError("SR3 down")

                out_c = _collect_in_dir(dir_c, sr3=sr3_fail)
                self.assertEqual(out_c["SR3"]["freshness"], "stale")
                self.assertEqual(out_c["SR3"]["as_of"], OBS)
                self.assertEqual(out_c["ESR"]["freshness"], "fresh")
                self.assertEqual(out_c["SR1"]["freshness"], "fresh")

    def test_corrupt_store_still_collects_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "short_rate_last_good.json"
            store_path.write_text("{", encoding="utf-8")
            out = collect_usd_eur_short_rates(
                today=TODAY,
                fetch_bytes=lambda *a, **k: b"",
                benchmark_usd=3.85,
                benchmark_eur=2.15,
                store_path=store_path,
                acquire_sr1=_acquire_ok(),
                acquire_sr3=_acquire_ok(),
                acquire_esr=_acquire_ok(method="ESR official"),
            )
            for key in ("SR1", "SR3", "ESR"):
                self.assertEqual(out[key]["freshness"], "fresh")
                self.assertEqual(out[key]["as_of"], OBS)
            repaired = load_store(store_path)
            self.assertIn("SR1", repaired["curves"])


if __name__ == "__main__":
    unittest.main()
