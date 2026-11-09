"""Authoritative trader-book and publication roster validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.market_watch_launch import publication_release as pr
from scripts.market_watch_launch import research_pages as rp
from scripts.market_watch_launch.pages_dispatch import assert_public_dataset
from scripts.overnight.books import match_authoritative_roster, published_book_roster
from scripts.overnight.constants import STANDING_SEATS
from scripts.pm.constants import AUTOMATED_PM_IDS
from scripts.trader_room.agent_config import legacy_pin

REPO = Path(__file__).resolve().parents[1]
LEGACY_IDS = tuple(str(row["id"]) for row in legacy_pin("daily")["traders"])
NOV9_LAUNCH = "mwl-20261109T103750Z-a4e987d1"
NOV9_REVIEW = "review-001"
NOV9_PACKET = "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
NOV9_NOW = datetime.fromisoformat("2026-11-09T05:37:50.499948-05:00")


def _seat_rows(ids: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    return [{"seat": sid} for sid in ids]


def _pm_rows() -> list[dict[str, str]]:
    return [{"pm_id": pm_id} for pm_id in AUTOMATED_PM_IDS]


class LegacyStandingRelationship(unittest.TestCase):
    def test_chart_guy_is_the_only_standing_extension(self) -> None:
        self.assertEqual(len(STANDING_SEATS), 15)
        self.assertEqual(len(LEGACY_IDS), 14)
        self.assertEqual(set(STANDING_SEATS) - set(LEGACY_IDS), {"chart-guy"})


class MatchAuthoritativeRosterTests(unittest.TestCase):
    def test_legacy_fourteen_passes_regardless_of_order(self) -> None:
        self.assertEqual(match_authoritative_roster(LEGACY_IDS), LEGACY_IDS)
        self.assertEqual(match_authoritative_roster(reversed(LEGACY_IDS)), LEGACY_IDS)

    def test_standing_fifteen_passes_regardless_of_order(self) -> None:
        self.assertEqual(match_authoritative_roster(STANDING_SEATS), tuple(STANDING_SEATS))
        self.assertEqual(match_authoritative_roster(reversed(STANDING_SEATS)), tuple(STANDING_SEATS))

    def test_published_book_roster_accepts_both_rosters(self) -> None:
        self.assertEqual(published_book_roster(_seat_rows(LEGACY_IDS)), LEGACY_IDS)
        self.assertEqual(published_book_roster(_seat_rows(STANDING_SEATS)), tuple(STANDING_SEATS))

    def test_failure_cases(self) -> None:
        cases = [
            list(LEGACY_IDS)[:13],
            [*LEGACY_IDS[:-1], "chart-guy"],
            [*STANDING_SEATS, "unknown-trader"],
            [*STANDING_SEATS, STANDING_SEATS[0]],
            [*LEGACY_IDS, LEGACY_IDS[0]],
            ["not-a-real-seat"],
            [*LEGACY_IDS[1:], "not-in-roster"],
            "",
            " chart-guy",
            14,
            None,
        ]
        for seat_ids in cases:
            with self.subTest(seat_ids=seat_ids):
                self.assertIsNone(match_authoritative_roster(seat_ids))

    def test_published_book_roster_shape_failures(self) -> None:
        good = _seat_rows(LEGACY_IDS)
        cases = [
            [],
            None,
            "bad",
            good + ["x"],
            good + [{"seat": LEGACY_IDS[0]}],
            [{"seat": "  "}],
            [{"seat": ""}],
            [{"seat": 1}],
            ["not-a-dict"],
        ]
        for seats in cases:
            with self.subTest(seats=seats):
                self.assertIsNone(published_book_roster(seats))


class AssertPublicDatasetRosterTests(unittest.TestCase):
    def _assert_ok(self, ids: tuple[str, ...]) -> None:
        trader = {
            "seats": _seat_rows(ids),
            "seat_count": len(ids),
            "publication": {"overnight_run_id": "overnight-20261022"},
        }
        assert_public_dataset(
            html="<h1>Trader Book</h1>",
            trader=trader,
            pm={"pms": _pm_rows()},
            overnight_run_id="overnight-20261022",
        )

    def test_accepts_legacy_and_standing_rosters(self) -> None:
        self._assert_ok(LEGACY_IDS)
        self._assert_ok(tuple(STANDING_SEATS))

    def test_rejects_malformed_rosters(self) -> None:
        base = {
            "publication": {"overnight_run_id": "overnight-20261022"},
            "seat_count": 14,
        }
        pm = {"pms": _pm_rows()}
        html = "<h1>Trader Book</h1>"
        bad_seats = [
            _seat_rows(LEGACY_IDS)[:13],
            _seat_rows([*LEGACY_IDS[:-1], "chart-guy"]),
            _seat_rows([*STANDING_SEATS, "unknown-trader"]),
            _seat_rows([*STANDING_SEATS, STANDING_SEATS[0]]),
        ]
        for seats in bad_seats:
            with self.subTest(seats=len(seats)):
                with self.assertRaises(SystemExit):
                    assert_public_dataset(
                        html=html,
                        trader={**base, "seats": seats},
                        pm=pm,
                        overnight_run_id="overnight-20261022",
                    )
        trader = {**base, "seats": _seat_rows(LEGACY_IDS), "seat_count": 15}
        with self.assertRaises(SystemExit):
            assert_public_dataset(
                html=html,
                trader=trader,
                pm=pm,
                overnight_run_id="overnight-20261022",
            )


class Nov9ResearchEditionSmoke(unittest.TestCase):
    launch_dir = REPO / "data" / "market_watch_launches" / NOV9_LAUNCH

    def test_nov9_research_site_builds_with_fifteen_seat_books(self) -> None:
        if not self.launch_dir.is_dir():
            self.fail(f"expected launch {NOV9_LAUNCH} on this checkout")
        launch_path = self.launch_dir / "launch.json"
        freeze_path = self.launch_dir / "remote_freeze.json"
        books_path = REPO / "data" / "overnight" / "books" / "latest.json"
        packet_path = (
            REPO
            / "data"
            / "overnight"
            / "runs"
            / "overnight-20261109"
            / "reviews"
            / NOV9_REVIEW
            / "evidence_snapshot.json"
        )
        for path in (launch_path, freeze_path, books_path, packet_path):
            self.assertTrue(path.is_file(), path)

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        before = {
            "books": digest(books_path),
            "launch": digest(launch_path),
            "remote_freeze": digest(freeze_path),
            "packet": digest(packet_path),
        }
        books = json.loads(books_path.read_text(encoding="utf-8"))
        before_seat_ids = set((books.get("seats") or {}).keys())

        contract = rp.research_contract(
            REPO,
            NOV9_LAUNCH,
            now=NOV9_NOW,
            expected_review_id=NOV9_REVIEW,
            expected_packet_sha256=NOV9_PACKET,
        )
        self.assertEqual(contract["packet_sha256"], NOV9_PACKET)
        self.assertEqual(contract["review_id"], NOV9_REVIEW)
        self.assertNotEqual(contract["books"]["packet_sha256"], NOV9_PACKET)
        self.assertEqual(contract["books"]["books_run_id"], "overnight-20261106")
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            rp.build_research_site(
                REPO,
                site,
                contract,
                channel=pr.CHANNEL_LOCAL,
                now=NOV9_NOW,
                fetch_schedules=False,
            )
            trader = json.loads((site / "trader-books.json").read_text(encoding="utf-8"))
            room = json.loads((site / "trader-room.json").read_text(encoding="utf-8"))

        self.assertEqual(trader["publication"]["trader_books_status"], "previous_cycle")
        self.assertEqual(trader["books_as_of"], "2026-11-06T06:25:49.281876-05:00")
        self.assertEqual(trader["books_run_id"], "overnight-20261106")
        published_ids = {row["seat"] for row in trader["seats"]}
        self.assertEqual(published_ids, set(STANDING_SEATS))
        self.assertEqual(len(trader["seats"]), len(published_ids))
        self.assertIn("chart-guy", published_ids)

        room_agents = {row["agent"] for row in room.get("trades") or [] if isinstance(row, dict)}
        self.assertEqual(room.get("available"), True)
        self.assertEqual(room_agents, set(LEGACY_IDS))
        self.assertNotIn("chart-guy", room_agents)

        after = {
            "books": digest(books_path),
            "launch": digest(launch_path),
            "remote_freeze": digest(freeze_path),
            "packet": digest(packet_path),
        }
        self.assertEqual(before, after)
        self.assertEqual(before_seat_ids, set((json.loads(books_path.read_text(encoding="utf-8")).get("seats") or {}).keys()))


if __name__ == "__main__":
    unittest.main()
