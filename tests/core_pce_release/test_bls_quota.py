"""BLS daily quota ledger, pacing, and live arm wiring."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.acquire import acquire_official
from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.bls_quota import (
    BLSQuotaLedger,
    PacketArmLock,
    earliest_request_offset_seconds,
)
from scripts.core_pce_release.cli import main
from scripts.core_pce_release.packet import prepare

G0_CENTRAL = "0.3688405280179773205064998201"
FIRST_LINE = "HOT baseline 0.3688% low 0.1759% high 0.5031%"
EASTERN = ZoneInfo("America/New_York")
NOT_BEFORE = datetime(2026, 10, 15, 8, 30, tzinfo=EASTERN)


def _advancing_clocks(start_wall: datetime):
    wall = {"t": start_wall}
    mono = {"t": 0.0}

    def wall_clock():
        return wall["t"]

    def monotonic():
        return mono["t"]

    def sleeper(seconds):
        wall["t"] = wall["t"] + timedelta(seconds=float(seconds))
        mono["t"] += float(seconds)

    return wall_clock, monotonic, sleeper


def _success_document(series_ids: list[str], periods: tuple[str, ...] = ("2026-09", "2026-08")) -> dict:
    data = []
    for period in periods:
        month = period.split("-")[1]
        data.append({"year": "2026", "period": f"M{month}", "value": "101.0" if period.endswith("09") else "100.0", "footnotes": []})
    return {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {"series": [{"seriesID": sid, "data": data} for sid in series_ids]},
    }


class PacingArithmeticTests(unittest.TestCase):
    def test_ceiling_eight_offsets(self):
        expected = [0, 20, 40, 348, 636, 924, 1212, 1500]
        actual = [earliest_request_offset_seconds(n, 8) for n in range(1, 9)]
        self.assertEqual(actual, expected)


class QuotaArmSimulationTests(unittest.TestCase):
    def _run_arm_polls(
        self,
        *,
        start_wall: datetime,
        steps: int,
        interval: float,
        poster=None,
        ceiling: int = 8,
    ) -> list[int]:
        calls: list[int] = []

        def counting_poster(series_ids, start_year, end_year, timeout, registration_key=None):
            calls.append(len(series_ids))
            return _success_document(series_ids)

        wall = {"t": start_wall}

        def wall_clock():
            return wall["t"]

        mono = {"t": 0.0}

        def sleeper(seconds):
            wall["t"] = wall["t"] + timedelta(seconds=seconds)
            mono["t"] += float(seconds)

        def monotonic():
            return mono["t"]

        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            inbox = packet / "inbox"
            prepare("ppi", "2026-09", packet)
            inbox.mkdir(parents=True)
            argv = [
                "arm",
                "--packet",
                str(packet),
                "--inbox",
                str(inbox),
                "--max-runtime-seconds",
                str(steps * interval),
                "--interval-seconds",
                str(interval),
                "--bls-daily-ceiling",
                str(ceiling),
                "--not-before",
                NOT_BEFORE.isoformat(),
            ]
            with redirect_stdout(io.StringIO()):
                main(
                    argv,
                    poster=poster or counting_poster,
                    wall_clock=wall_clock,
                    monotonic=monotonic,
                    sleeper=sleeper,
                )
        return calls

    def test_one_eighty_polls_from_not_before_caps_posters(self):
        calls = self._run_arm_polls(start_wall=NOT_BEFORE, steps=180, interval=10.0)
        self.assertGreaterEqual(len(calls), 1)
        self.assertLessEqual(len(calls), 8)

    def test_one_eighty_polls_before_not_before_no_posters(self):
        start = NOT_BEFORE - timedelta(seconds=1800)
        calls = self._run_arm_polls(start_wall=start, steps=180, interval=10.0)
        self.assertEqual(len(calls), 0)


class FetchQuotaLedgerTests(unittest.TestCase):
    def test_timeout_retry_counts_two_slots(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bls_quota.json"
            wall = {"t": NOT_BEFORE}

            def wall_clock():
                return wall["t"]

            ledger = BLSQuotaLedger(
                path,
                release="2026-09",
                kind="ppi",
                ceiling=8,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=wall_clock,
            )
            calls = {"n": 0}

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                calls["n"] += 1
                raise TimeoutError("offline")

            fetch_series(["S1"], poster=poster, sleep=lambda _: None, quota=ledger, max_attempts_per_request=2)
            self.assertEqual(calls["n"], 2)
            self.assertEqual(ledger._document["requests_today"], 2)

    def test_secondary_batch_respects_ceiling_one(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bls_quota.json"
            ledger = BLSQuotaLedger(
                path,
                release="2026-09",
                kind="ppi",
                ceiling=1,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=lambda: NOT_BEFORE,
            )
            calls: list[int] = []

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                calls.append(len(series_ids))
                return _success_document(series_ids)

            acquire_official(["PCU622---622---"], "2026-09", quota=ledger, poster=poster)
            self.assertEqual(len(calls), 1)

    def test_secondary_batch_runs_with_high_ceiling(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bls_quota.json"
            ledger = BLSQuotaLedger(
                path,
                release="2026-09",
                kind="ppi",
                ceiling=50,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=lambda: NOT_BEFORE,
            )
            calls: list[int] = []

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                calls.append(len(series_ids))
                return _success_document(series_ids)

            acquire_official(["PCU622---622---"], "2026-09", quota=ledger, poster=poster)
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(ledger._document["requests_today"], len(calls))

    def test_ledger_persists_across_objects_and_rearm(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            path = packet / "bls_quota.json"
            wall = {"t": NOT_BEFORE}

            def wall_clock():
                return wall["t"]

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                return _success_document(series_ids)

            ledger1 = BLSQuotaLedger.open_ledger(
                packet,
                release="2026-09",
                kind="ppi",
                ceiling=2,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=wall_clock,
            )
            fetch_series(["S1"], poster=poster, quota=ledger1, sleep=lambda _: None)
            first_count = ledger1._document["requests_today"]
            ledger2 = BLSQuotaLedger.open_ledger(
                packet,
                release="2026-09",
                kind="ppi",
                ceiling=2,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=wall_clock,
            )
            self.assertEqual(ledger2._document["requests_today"], first_count)
            argv = [
                "arm",
                "--packet",
                str(packet),
                "--inbox",
                str(inbox),
                "--max-runtime-seconds",
                "5",
                "--interval-seconds",
                "1",
                "--bls-daily-ceiling",
                "2",
                "--not-before",
                NOT_BEFORE.isoformat(),
            ]
            mono = {"t": 0.0}

            def sleeper(seconds):
                mono["t"] += float(seconds)

            with redirect_stdout(io.StringIO()):
                main(
                    argv,
                    poster=poster,
                    wall_clock=wall_clock,
                    monotonic=lambda: mono["t"],
                    sleeper=sleeper,
                )
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertLessEqual(document["requests_today"], 2)

    def test_eastern_day_rollover_resets_today_keeps_history(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bls_quota.json"
            day_one = datetime(2026, 10, 15, 12, 0, tzinfo=EASTERN)
            wall = {"t": day_one}

            def wall_clock():
                return wall["t"]

            ledger = BLSQuotaLedger(
                path,
                release="2026-09",
                kind="ppi",
                ceiling=8,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=wall_clock,
            )
            permitted, _, row = ledger.begin_attempt(series_count=1)
            self.assertTrue(permitted)
            ledger.record_http_outcome(row, "ok", 200)
            self.assertEqual(ledger._document["requests_today"], 1)
            wall["t"] = datetime(2026, 10, 16, 12, 0, tzinfo=EASTERN)
            reopened = BLSQuotaLedger(
                path,
                release="2026-09",
                kind="ppi",
                ceiling=8,
                not_before=NOT_BEFORE,
                key_present=False,
                wall_clock=wall_clock,
            )
            self.assertEqual(reopened._document["requests_today"], 0)
            self.assertEqual(reopened._document["per_day_requests"]["2026-10-15"], 1)
            anchors = reopened._document.get("pacing_anchor_by_day") or {}
            self.assertNotIn("2026-10-16", anchors)
            allowed, reason, _row = reopened.begin_attempt(series_count=1)
            self.assertTrue(allowed)
            self.assertIsNone(reason)
            self.assertEqual(reopened._document["requests_today"], 1)


class ConcurrentArmTests(unittest.TestCase):
    def test_second_lock_blocks_main_arm(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            first_line_before = (packet / "flash.txt").read_text(encoding="utf-8").splitlines()[0]
            lock = PacketArmLock(packet)
            self.assertTrue(lock.acquire())
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = main(
                        [
                            "arm",
                            "--packet",
                            str(packet),
                            "--inbox",
                            str(inbox),
                            "--max-runtime-seconds",
                            "0",
                            "--interval-seconds",
                            "1",
                            "--not-before",
                            NOT_BEFORE.isoformat(),
                        ],
                        poster=lambda *a, **k: _success_document(a[0]),
                        wall_clock=lambda: NOT_BEFORE,
                        monotonic=lambda: 0.0,
                        sleeper=lambda _: None,
                    )
                self.assertEqual(code, 2)
                self.assertIn("concurrent_arm_blocked", buf.getvalue())
            finally:
                lock.release()
            first_line_after = (packet / "flash.txt").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line_before, FIRST_LINE)
            self.assertEqual(first_line_after, FIRST_LINE)


class ForecastThroughQuotaWrapperTests(unittest.TestCase):
    def test_ppi_update_after_not_before(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            calls = {"n": 0}
            wall_clock, monotonic, sleeper = _advancing_clocks(NOT_BEFORE)

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                calls["n"] += 1
                return _success_document(series_ids, ("2026-09", "2026-08"))

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "1",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=wall_clock,
                    monotonic=monotonic,
                    sleeper=sleeper,
                )
            flash = (packet / "flash.txt").read_text(encoding="utf-8")
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertIn("PPI updated", flash)
            self.assertNotEqual(detailed["central_mom_percent"], G0_CENTRAL)
            updated_central = detailed["central_mom_percent"]
            calls_after = calls["n"]
            wall_clock2, monotonic2, sleeper2 = _advancing_clocks(NOT_BEFORE)
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "1",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=wall_clock2,
                    monotonic=monotonic2,
                    sleeper=sleeper2,
                )
            self.assertGreaterEqual(calls["n"], calls_after)
            detailed_again = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed_again["central_mom_percent"], updated_central)


class ThrottleAndQuotaMessageTests(unittest.TestCase):
    def test_http_429_throttles_without_changing_baseline(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            calls = {"n": 0}

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                calls["n"] += 1
                raise urllib.error.HTTPError("url", 429, "too many", {}, None)

            wall_clock, monotonic, sleeper = _advancing_clocks(NOT_BEFORE)
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "5",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=wall_clock,
                    monotonic=monotonic,
                    sleeper=sleeper,
                )
            self.assertEqual(calls["n"], 1)
            self.assertEqual((packet / "flash.txt").read_text(encoding="utf-8").splitlines()[0], FIRST_LINE)
            self.assertIn("bls_throttled", buf.getvalue())

    def test_daily_threshold_message_not_persisted(self):
        secret = "SECRET-KEY-VALUE"
        with mock.patch.dict(os.environ, {"BLS_REGISTRATION_KEY": secret}):
            with tempfile.TemporaryDirectory() as raw:
                packet = Path(raw) / "packet"
                prepare("ppi", "2026-09", packet)
                inbox = packet / "inbox"
                inbox.mkdir()

                def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                    return {
                        "status": "REQUEST_NOT_PROCESSED",
                        "message": [
                            "Request could not be serviced, as the daily threshold for total number of "
                            f"requests allocated to the user with registration key {secret} has been reached."
                        ],
                    }

                wall_clock, monotonic, sleeper = _advancing_clocks(NOT_BEFORE)
                with redirect_stdout(io.StringIO()):
                    main(
                        [
                            "arm",
                            "--packet",
                            str(packet),
                            "--inbox",
                            str(inbox),
                            "--max-runtime-seconds",
                            "1",
                            "--interval-seconds",
                            "1",
                            "--not-before",
                            NOT_BEFORE.isoformat(),
                        ],
                        poster=poster,
                        wall_clock=wall_clock,
                        monotonic=monotonic,
                        sleeper=sleeper,
                    )
                leaked = []
                for path in packet.rglob("*"):
                    if not path.is_file():
                        continue
                    if secret in path.read_text(encoding="utf-8", errors="replace"):
                        leaked.append(str(path.relative_to(packet)))
                self.assertEqual(leaked, [])
                document = json.loads((packet / "bls_quota.json").read_text(encoding="utf-8"))
                self.assertTrue(document["throttled_days"]["2026-10-15"])
                self.assertEqual(document["attempts"][-1]["outcome"], "bls_quota")

    def test_august_only_success_not_quota_exhausted(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                return _success_document(series_ids, ("2026-08",))

            wall_clock, monotonic, sleeper = _advancing_clocks(NOT_BEFORE)
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "1",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=wall_clock,
                    monotonic=monotonic,
                    sleeper=sleeper,
                )
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["central_mom_percent"], G0_CENTRAL)
            self.assertIn("awaiting current PPI", (packet / "flash.txt").read_text(encoding="utf-8"))


class SecretAndCancelTests(unittest.TestCase):
    def test_status_and_ledgeromit_key(self):
        secret = "SECRET-KEY-VALUE"
        with mock.patch.dict(os.environ, {"BLS_REGISTRATION_KEY": secret}, clear=False):
            with tempfile.TemporaryDirectory() as raw:
                packet = Path(raw) / "packet"
                prepare("ppi", "2026-09", packet)
                inbox = packet / "inbox"
                inbox.mkdir()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    main(
                        [
                            "arm",
                            "--packet",
                            str(packet),
                            "--inbox",
                            str(inbox),
                            "--max-runtime-seconds",
                            "0",
                            "--interval-seconds",
                            "1",
                            "--not-before",
                            NOT_BEFORE.isoformat(),
                        ],
                        poster=lambda *a, **k: _success_document(a[0]),
                        wall_clock=lambda: NOT_BEFORE,
                        monotonic=lambda: 0.0,
                        sleeper=lambda _: None,
                    )
                self.assertNotIn(secret, buf.getvalue())
                self.assertNotIn(secret, (packet / "bls_quota.json").read_text(encoding="utf-8"))
                document = json.loads((packet / "bls_quota.json").read_text(encoding="utf-8"))
                self.assertTrue(document["key_present"])
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            with mock.patch.dict(os.environ, {}, clear=True):
                for name in ("BLS_API_KEY", "BLS_REGISTRATION_KEY"):
                    os.environ.pop(name, None)
                BLSQuotaLedger.open_ledger(
                    packet,
                    release="2026-09",
                    kind="ppi",
                    ceiling=8,
                    not_before=NOT_BEFORE,
                    key_present=False,
                    wall_clock=lambda: NOT_BEFORE,
                )
                document = json.loads((packet / "bls_quota.json").read_text(encoding="utf-8"))
                self.assertFalse(document["key_present"])

    def test_cancel_during_quota_arm(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            wall = {"t": NOT_BEFORE}
            mono = {"t": 0.0}

            def poster(series_ids, start_year, end_year, timeout, registration_key=None):
                (packet / "CANCEL").write_text("1\n", encoding="utf-8")
                return _success_document(series_ids, ("2026-08",))

            def sleeper(_s):
                mono["t"] += 1

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "60",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=lambda: wall["t"],
                    monotonic=lambda: mono["t"],
                    sleeper=sleeper,
                )
            self.assertIn("stopped: cancelled", buf.getvalue())
            self.assertEqual((packet / "flash.txt").read_text(encoding="utf-8").splitlines()[0], FIRST_LINE)

    def test_no_live_fetch_skips_poster(self):
        calls = {"n": 0}

        def poster(*_a, **_k):
            calls["n"] += 1
            return _success_document([])

        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "0",
                        "--no-live-fetch",
                    ],
                    poster=poster,
                )
            self.assertEqual(calls["n"], 0)
            self.assertFalse((packet / "bls_quota.json").exists())

    def test_negative_ceiling_does_not_fetch(self):
        calls = {"n": 0}

        def poster(*_a, **_k):
            calls["n"] += 1
            return _success_document([])

        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "30",
                        "--interval-seconds",
                        "10",
                        "--bls-daily-ceiling",
                        "-1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=lambda: NOT_BEFORE,
                    monotonic=lambda: 0.0,
                    sleeper=lambda _s: None,
                )
            self.assertEqual(code, 2)
            self.assertIn("invalid_bls_daily_ceiling", buf.getvalue())
            self.assertEqual(calls["n"], 0)
            self.assertEqual((packet / "flash.txt").read_text(encoding="utf-8").splitlines()[0], FIRST_LINE)

    def test_unreadable_ledger_blocks_http_and_is_not_reset(self):
        calls = {"n": 0}

        def poster(*_a, **_k):
            calls["n"] += 1
            return _success_document([])

        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            inbox = packet / "inbox"
            inbox.mkdir()
            ledger_path = packet / "bls_quota.json"
            ledger_path.write_text("{not-json", encoding="utf-8")
            mono = {"t": 0.0}
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(
                    [
                        "arm",
                        "--packet",
                        str(packet),
                        "--inbox",
                        str(inbox),
                        "--max-runtime-seconds",
                        "3",
                        "--interval-seconds",
                        "1",
                        "--not-before",
                        NOT_BEFORE.isoformat(),
                    ],
                    poster=poster,
                    wall_clock=lambda: NOT_BEFORE,
                    monotonic=lambda: mono["t"],
                    sleeper=lambda seconds: mono.__setitem__("t", mono["t"] + float(seconds)),
                )
            self.assertEqual(calls["n"], 0)
            self.assertEqual(ledger_path.read_text(encoding="utf-8"), "{not-json")
            self.assertIn("ledger_unreadable", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
