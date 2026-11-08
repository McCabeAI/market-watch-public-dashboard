"""CME ESR isolation, ECB meeting pricing, and policy-path integration."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from scripts.policy_path_data import (
    CME_SR3_QUOTES_V2_URL,
    CME_SR3_URL,
    CME_SOFR_BULLETIN_URL,
    EA_ESTR_BENCHMARK_DEADLINE_SEC,
    ESIGNAL_SR3_CHAIN_URL,
    build_tradable_rate_curves,
    collect_policy_paths,
    join_ea_benchmark,
)
from scripts.rates.cme_esr import reference_quarter
from scripts.rates.cme_session import classify_mark_freshness, latest_expected_cme_session
from scripts.rates.ecb_meeting_pricing import compound_growth, price_ecb_meetings
from scripts.rates.short_rate_store import remember_fresh, save_store

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cme_esr"
EA_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ea_rates"
NOV6_ESR = (FIXTURE_DIR / "settlement_final_2026-11-06.json").read_text(encoding="utf-8")
_ECB_ESTR_SAMPLE = (EA_FIXTURES / "ecb_estr_sample.csv").read_bytes()


def _minimal_sofr_json() -> bytes:
    return json.dumps(
        {
            "refRates": [
                {"type": "SOFR", "effectiveDate": "2026-10-15", "percentRate": 3.64},
            ]
        }
    ).encode()


def _sr3_final(trade_mdy: str) -> bytes:
    return json.dumps(
        {
            "reportType": "Final",
            "tradeDate": trade_mdy,
            "updateTime": "Thursday, 15 Oct 2026 11:55 PM",
            "settlements": [
                {"month": "MAR 27", "settle": "96.50"},
                {"month": "SEP 27", "settle": "96.25"},
            ],
        }
    ).encode()


def _policy_fetch(
    *,
    settlement_by_trade_date: dict[str, bytes] | None = None,
    esr_by_trade_date: dict[str, bytes] | None = None,
    esr_raise: bool = False,
    call_log: list[str] | None = None,
):
    settlement_by_trade_date = settlement_by_trade_date or {}
    esr_by_trade_date = esr_by_trade_date or {}

    def fetch(url: str, **_kwargs: object) -> bytes:
        if call_log is not None:
            call_log.append(url)
        if "newyorkfed.org" in url:
            return _minimal_sofr_json()
        if "8462" in url and "Settlements" in url:
            for trade_date, body in settlement_by_trade_date.items():
                if f"tradeDate={trade_date}" in url:
                    return body
            raise RuntimeError(f"SR3 settlement denied: {url}")
        if "10247" in url and "Settlements" in url:
            if esr_raise:
                raise RuntimeError("ESR settlement denied")
            for trade_date, body in esr_by_trade_date.items():
                if f"tradeDate={trade_date}" in url:
                    return body
            raise RuntimeError(f"ESR settlement denied: {url}")
        if "quotes.esignal" in url and "ESR" in url:
            raise RuntimeError("eSignal ESR denied")
        if url == CME_SR3_QUOTES_V2_URL:
            raise RuntimeError("SR3 quotes denied")
        if url == CME_SR3_URL:
            raise RuntimeError("SR3 html denied")
        if url == CME_SOFR_BULLETIN_URL:
            raise RuntimeError("SR1 bulletin denied")
        if url == ESIGNAL_SR3_CHAIN_URL:
            raise RuntimeError("eSignal SR3 denied")
        if "bankofcanada.ca" in url:
            raise RuntimeError("CA denied")
        if "rba.gov.au" in url:
            raise RuntimeError("AU denied")
        if "ecb.europa.eu" in url or "data-api.ecb.europa.eu" in url:
            raise RuntimeError("EA estr denied")
        if "eurex.com" in url:
            raise RuntimeError("FST3 denied")
        if "boj" in url or "jpx" in url or "mof" in url:
            raise RuntimeError("JP denied")
        raise RuntimeError(f"unhandled url {url}")

    return fetch


class EcbCompoundTests(unittest.TestCase):
    def test_compound_roundtrip_meeting_on_reference_start(self) -> None:
        rq = reference_quarter("2027-03")
        ref_start = date.fromisoformat(rq["reference_start"])
        ref_end = date.fromisoformat(rq["reference_end"])
        basis = 1.90 - 2.00
        post_estr = 3.25
        anchor = 2.0
        fixing = 1.90

        def rate_on_day(day: date) -> float | None:
            if day < ref_start:
                return fixing
            return post_estr

        growth = compound_growth(ref_start, ref_end, rate_on_day)
        implied = ((growth - 1.0) * 360.0 / (ref_end - ref_start).days) * 100.0
        meetings = [
            {
                "decision_date": "2027-03-10",
                "effective_date": ref_start.isoformat(),
            }
        ]
        contracts = [
            {
                "reference_start": rq["reference_start"],
                "reference_end": rq["reference_end"],
                "implied_rate": implied,
                "expiry": "2027-03",
                "code": "ESRH7",
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
                "open_interest": 100,
            }
        ]
        rows, reason = price_ecb_meetings(
            as_of=date(2026, 11, 1),
            anchor=anchor,
            fixing=fixing,
            history=None,
            meetings=meetings,
            contracts=contracts,
            futures_freshness="fresh",
        )
        self.assertIsNone(reason)
        pol = rows[0]["post_rate"]
        self.assertIsNotNone(pol)
        self.assertAlmostEqual(pol, implied - basis, delta=0.02)

    def test_two_meetings_in_one_quarter_unpriced(self) -> None:
        rq = reference_quarter("2027-06")
        meetings = [
            {"decision_date": "2027-05-01", "effective_date": "2027-06-16"},
            {"decision_date": "2027-07-01", "effective_date": "2027-07-15"},
        ]
        implied = 2.65
        contracts = [
            {
                "reference_start": rq["reference_start"],
                "reference_end": rq["reference_end"],
                "implied_rate": implied,
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
            }
        ]
        rows, _ = price_ecb_meetings(
            as_of=date(2027, 1, 1),
            anchor=2.0,
            fixing=1.9,
            history=None,
            meetings=meetings,
            contracts=contracts,
            futures_freshness="fresh",
        )
        for row in rows:
            if date.fromisoformat(row["effective_date"]) > date(2027, 1, 1):
                self.assertIsNone(row["post_rate"])
                self.assertNotEqual(row["post_rate"], implied)


class JoinEaBenchmarkTests(unittest.TestCase):
    def test_join_uses_done_future_past_deadline(self) -> None:
        payload = {
            "status": "ok",
            "country": "EA",
            "benchmark": {"name": "€STR", "rate": 1.91},
            "contracts_3m": [],
        }
        future: Future[dict] = Future()
        future.set_result(payload)
        elapsed = EA_ESTR_BENCHMARK_DEADLINE_SEC + 5.0
        self.assertIs(join_ea_benchmark(future, elapsed=elapsed), payload)

    def test_join_not_done_past_deadline_unavailable_without_blocking(self) -> None:
        gate = threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)

        def slow_collect() -> dict:
            gate.wait(timeout=60)
            return {"status": "ok", "country": "EA"}

        try:
            pending = executor.submit(slow_collect)
            started = time.perf_counter()
            out = join_ea_benchmark(
                pending,
                elapsed=EA_ESTR_BENCHMARK_DEADLINE_SEC + 1.0,
            )
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 1.0)
            self.assertEqual(out["status"], "unavailable")
            self.assertIn("timed out", str(out.get("error", "")).lower())
        finally:
            gate.set()
            executor.shutdown(wait=False)


class PolicyPathIsolationTests(unittest.TestCase):
    def test_slow_ecb_does_not_block_sr3(self) -> None:
        base = _policy_fetch(
            settlement_by_trade_date={"10/15/2026": _sr3_final("10/15/2026")},
        )
        calls: list[str] = []

        def fetch(url: str, **_kwargs: object) -> bytes:
            calls.append(url)
            if "data-api.ecb.europa.eu" in url or "/service/data/EST" in url:
                time.sleep(30)
                return _ECB_ESTR_SAMPLE
            return base(url, **_kwargs)

        started = time.perf_counter()
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=date(2026, 10, 16), fetch_bytes=fetch)
        elapsed = time.perf_counter() - started

        us = paths["countries"]["US"]
        self.assertLess(elapsed, 25.0, f"collect_policy_paths took {elapsed:.2f}s")
        self.assertIn(us["status"], {"ok", "partial"})
        self.assertTrue(us["contracts_3m"])
        ea = paths["countries"]["EA"]
        bench = (ea.get("benchmark") or {}).get("rate")
        ea_err = str(ea.get("error") or "")
        self.assertTrue(bench is None or "timeout" in ea_err.lower(), ea)
        self.assertFalse(any("eurex.com" in url for url in calls))

    def test_esr_fail_us_ok_estr_unavailable(self) -> None:
        fetch = _policy_fetch(
            settlement_by_trade_date={"10/15/2026": _sr3_final("10/15/2026")},
            esr_raise=True,
        )
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=date(2026, 10, 16), fetch_bytes=fetch)
        us = paths["countries"]["US"]
        self.assertEqual(us["status"], "ok")
        self.assertTrue(us["contracts_3m"])
        self.assertIsNone(us.get("sr3_error"))
        us_err = us.get("error")
        if us_err:
            self.assertNotRegex(str(us_err), r"^\s*ESR\b", msg=us_err)
        self.assertFalse(any("ESR" in str(us.get(k)) for k in us if "error" in str(k)))
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["ESTR"]["status"], "unavailable")
        ea = paths["countries"]["EA"]
        self.assertNotEqual(ea.get("esr_freshness"), "ok")

    def test_sr3_fail_esr_still_attempted(self) -> None:
        esr_body = json.loads(NOV6_ESR)
        esr_body["tradeDate"] = "11/06/2026"
        esr_payload = json.dumps(esr_body).encode()
        calls: list[str] = []
        fetch = _policy_fetch(
            esr_by_trade_date={"11/06/2026": esr_payload},
            call_log=calls,
        )
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=date(2026, 11, 6), fetch_bytes=fetch)
        us = paths["countries"]["US"]
        self.assertEqual(us["benchmark"]["rate"], 3.64)
        self.assertEqual(us["contracts_3m"], [])
        self.assertTrue(us.get("sr3_error"))
        self.assertTrue(any("10247" in url for url in calls))

    def test_both_sr3_and_esr_fail_no_exception(self) -> None:
        fetch = _policy_fetch(esr_raise=True)
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=date(2026, 10, 16), fetch_bytes=fetch)
        us = paths["countries"]["US"]
        self.assertIn(us["status"], {"partial", "unavailable"})
        self.assertEqual(paths["countries"]["US"]["benchmark"]["rate"], 3.64)
        curves = build_tradable_rate_curves(paths)
        self.assertEqual(curves["curves"]["ESTR"]["status"], "unavailable")

    def test_stale_retention_separate_as_ofs(self) -> None:
        today = date(2026, 11, 9)
        old = (today - timedelta(days=3)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "short_rate_last_good.json"
            seeded = {"version": 1, "curves": {}}
            for key, rate in (("SR3", 3.5), ("ESR", 2.5)):
                seeded = remember_fresh(
                    seeded,
                    key,
                    rows=[
                        {
                            "expiry": "2027-03",
                            "code": "SR3H7" if key == "SR3" else "ESRH7",
                            "implied_rate": rate,
                            "change_from_overnight_bps": 0.0,
                            "observation_date": old,
                            "as_of": old,
                            "reference_start": "2027-03-17",
                            "reference_end": "2027-06-16",
                            "mark_kind": "official_settlement",
                            "trade_date_verified": True,
                        }
                    ],
                    as_of=old,
                    source=key,
                    source_url=f"https://example/{key}",
                    mark_kind="official_settlement",
                )
            save_store(store, seeded)
            fetch = _policy_fetch(esr_raise=True)
            with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
                paths = collect_policy_paths(
                    today=today,
                    fetch_bytes=fetch,
                    short_rate_store=store,
                )
            us = paths["countries"]["US"]
            ea = paths["countries"]["EA"]
            self.assertEqual(us.get("status"), "partial")
            self.assertEqual(us.get("sr3_freshness"), "stale")
            self.assertNotEqual(us["contracts_3m"][0].get("as_of"), today.isoformat())
            self.assertEqual(ea.get("esr_freshness"), "stale")
            self.assertNotEqual(ea.get("futures_as_of"), today.isoformat())
            curves = build_tradable_rate_curves(paths)
            self.assertEqual(curves["curves"]["SOFR"]["status"], "stale")
            self.assertEqual(curves["curves"]["SOFR"]["as_of"], old)
            self.assertEqual(curves["curves"]["ESTR"]["status"], "stale")
            self.assertNotEqual(curves["curves"]["ESTR"]["status"], "ok")

    def test_stale_retention_30d_not_served(self) -> None:
        today = date(2026, 11, 9)
        old = (today - timedelta(days=30)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "short_rate_last_good.json"
            seeded = remember_fresh(
                {"version": 1, "curves": {}},
                "SR3",
                rows=[{"expiry": "2027-03", "implied_rate": 3.5, "observation_date": old, "as_of": old}],
                as_of=old,
                source="SR3",
                source_url=None,
                mark_kind="official_settlement",
            )
            save_store(store, seeded)
            fetch = _policy_fetch(esr_raise=True)
            with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
                paths = collect_policy_paths(
                    today=today,
                    fetch_bytes=fetch,
                    short_rate_store=store,
                )
            us = paths["countries"]["US"]
            self.assertEqual(us["contracts_3m"], [])

    def test_stale_official_esr_refuses_identified_meetings(self) -> None:
        rq = reference_quarter("2027-03")
        meetings = [
            {
                "decision_date": "2027-03-10",
                "effective_date": rq["reference_start"],
            }
        ]
        contracts = [
            {
                "reference_start": rq["reference_start"],
                "reference_end": rq["reference_end"],
                "implied_rate": 2.45,
                "expiry": "2027-03",
                "code": "ESRH7",
                "mark_kind": "official_settlement",
                "trade_date_verified": True,
                "observation_date": "2026-11-03",
                "as_of": "2026-11-03",
                "open_interest": 100,
            }
        ]
        rows, _reason = price_ecb_meetings(
            as_of=date(2026, 11, 8),
            anchor=2.0,
            fixing=1.9,
            history=None,
            meetings=meetings,
            contracts=contracts,
            futures_freshness="stale",
        )
        for row in rows:
            self.assertNotEqual(row.get("method"), "identified")

    def test_sunday_nov6_esr_mark_fresh(self) -> None:
        today = date(2026, 11, 8)
        expected = latest_expected_cme_session(today)
        self.assertEqual(expected, date(2026, 11, 6))
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=expected,
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "fresh",
        )
        self.assertEqual(
            classify_mark_freshness(
                curve_key="ESR",
                observation=date(2026, 11, 3),
                today=today,
                mark_kind="official_settlement",
                trade_date_verified=True,
            ),
            "stale",
        )
        esr_body = json.loads(NOV6_ESR)
        esr_body["tradeDate"] = "11/06/2026"
        esr_payload = json.dumps(esr_body).encode()
        fetch = _policy_fetch(
            settlement_by_trade_date={"11/06/2026": _sr3_final("11/06/2026")},
            esr_by_trade_date={"11/06/2026": esr_payload},
        )
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=today, fetch_bytes=fetch)
        ea = paths["countries"]["EA"]
        self.assertEqual(ea.get("esr_freshness"), "fresh")

    def test_duplicate_trade_date_not_todays_mark(self) -> None:
        payload = json.loads(NOV6_ESR)
        payload["tradeDate"] = "11/05/2026"
        esr_payload = json.dumps(payload).encode()
        fetch = _policy_fetch(
            settlement_by_trade_date={"10/15/2026": _sr3_final("10/15/2026")},
            esr_by_trade_date={"11/06/2026": esr_payload, "11/05/2026": esr_payload},
        )
        with mock.patch("scripts.policy_path_data._curl_cffi_get", side_effect=AssertionError):
            paths = collect_policy_paths(today=date(2026, 11, 6), fetch_bytes=fetch)
        ea = paths["countries"]["EA"]
        if ea.get("contracts_3m"):
            obs = ea["contracts_3m"][0].get("observation_date")
            self.assertNotEqual(obs, "2026-11-06")


if __name__ == "__main__":
    unittest.main()
