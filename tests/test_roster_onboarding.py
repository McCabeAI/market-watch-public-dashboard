"""Roster onboarding CLI and roster-aware books/pins."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.overnight.books import empty_books, ensure_roster_books, validate_books
from scripts.overnight.constants import STARTING_NAV_USD
from scripts.overnight.errors import SchemaError
from scripts.overnight.evidence import _prepare_prior_books, freeze_snapshot
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.trader_room.agent_config import (
    build_pin,
    head_traders,
    legacy_pin,
    load_config,
    ondemand_budget,
    daily_budget,
    pin_trader_ids,
    seal_pin,
)
from scripts.trader_room.runners import build_launch_plan
from scripts.trading.store import TradingStore
from scripts.trader_room import onboard_trader as onboard_mod

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "overnight" / "fixtures" / "market_state.json"
REAL_PERSONA = ROOT / ".cursor" / "agents" / "perma-bull.md"


def _build_temp_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="mw-roster-onboard-"))
    (tmp / "scripts" / "trader_room").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "scripts" / "trader_room" / "model_registry.json", tmp / "scripts" / "trader_room" / "model_registry.json")
    agents_src = ROOT / ".cursor" / "agents"
    agents_dst = tmp / ".cursor" / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)
    for path in agents_src.glob("*.md"):
        shutil.copy(path, agents_dst / path.name)
    books_dir = tmp / "data" / "overnight" / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    books = empty_books()
    (books_dir / "latest.json").write_text(json.dumps(books, indent=2) + "\n", encoding="utf-8")
    store = TradingStore(state_root=tmp)
    store.ensure_initialized()
    return tmp


def _persona_file(tmp: Path, *, text: str | None = None) -> Path:
    path = tmp / "persona.md"
    payload = text if text is not None else REAL_PERSONA.read_text(encoding="utf-8")
    path.write_text(payload, encoding="utf-8")
    return path


class RosterOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = _build_temp_root()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_onboard_pending_writes_agent_and_no_state(self) -> None:
        persona = _persona_file(self.tmp)
        summary = onboard_mod.onboard_pending(
            root=self.tmp,
            trader_id="synthetic-fifteenth",
            remit="synthetic fixture seat for roster onboarding tests",
            specialty="rates_first",
            activation_date="2026-11-02",
            description="Synthetic fifteenth seat for onboarding tests.",
            persona=persona.read_text(encoding="utf-8"),
            may_no_trade=False,
            dry_run=False,
        )
        self.assertEqual(summary["mode"], "pending")
        cfg = load_config(self.tmp / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        pending = [t for t in cfg["roster"]["traders"] if t["id"] == "synthetic-fifteenth"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")
        self.assertEqual(len(head_traders(cfg)), 14)
        agent_path = self.tmp / ".cursor" / "agents" / "synthetic-fifteenth.md"
        self.assertTrue(agent_path.is_file())
        self.assertIn("model: grok-4.6[]", agent_path.read_text(encoding="utf-8"))
        store = TradingStore(state_root=self.tmp)
        self.assertFalse((store.state_dir() / "trader" / "synthetic-fifteenth").exists())

    def test_onboard_rejects_placeholder_persona_and_duplicate_id(self) -> None:
        short = _persona_file(self.tmp, text="too short")
        with self.assertRaises(Exception):
            onboard_mod._validate_persona(short.read_text(encoding="utf-8"))
        placeholder = _persona_file(self.tmp, text=("x" * 200) + " TODO finish persona")
        with self.assertRaises(Exception):
            onboard_mod._validate_persona(placeholder.read_text(encoding="utf-8"))
        persona = _persona_file(self.tmp)
        onboard_mod.onboard_pending(
            root=self.tmp,
            trader_id="dup-seat",
            remit="first entry",
            specialty="rates_first",
            activation_date="2026-11-02",
            description="dup test",
            persona=persona.read_text(encoding="utf-8"),
            may_no_trade=False,
            dry_run=False,
        )
        with self.assertRaises(Exception):
            onboard_mod.onboard_pending(
                root=self.tmp,
                trader_id="dup-seat",
                remit="second entry",
                specialty="rates_first",
                activation_date="2026-11-02",
                description="dup test",
                persona=persona.read_text(encoding="utf-8"),
                may_no_trade=False,
                dry_run=False,
            )

    def test_activate_requires_confirm_flag(self) -> None:
        proc = subprocess.run(
            [
                "python3",
                "-m",
                "scripts.trader_room.onboard_trader",
                "--id",
                "synthetic-fifteenth",
                "--remit",
                "synthetic fixture seat",
                "--expression-specialty",
                "rates_first",
                "--activation-date",
                "2026-11-02",
                "--description",
                "Synthetic seat",
                "--persona-file",
                str(_persona_file(self.tmp)),
                "--activate",
                "--root",
                str(self.tmp),
            ],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("confirm-live-activation", proc.stdout + proc.stderr)

    def test_activate_cold_start_is_append_only(self) -> None:
        persona = _persona_file(self.tmp)
        store = TradingStore(state_root=self.tmp)
        books_path = self.tmp / "data" / "overnight" / "books" / "latest.json"
        books_before = json.loads(books_path.read_text(encoding="utf-8"))
        seat_hashes_before = {seat: sha256_json(payload) for seat, payload in books_before["seats"].items()}
        identity_hashes_before = {
            str(path.relative_to(store.state_dir())): sha256_json(json.loads(path.read_text(encoding="utf-8")))
            for path in (store.state_dir() / "trader").rglob("*.json")
        }
        summary = onboard_mod.onboard_activate(
            root=self.tmp,
            trader_id="synthetic-fifteenth",
            remit="synthetic fixture seat for roster onboarding tests",
            specialty="rates_first",
            activation_date="2026-11-02",
            description="Synthetic fifteenth seat for onboarding tests.",
            persona=persona.read_text(encoding="utf-8"),
            may_no_trade=False,
            dry_run=False,
        )
        self.assertTrue(summary.get("written"))
        cfg = load_config(self.tmp / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        self.assertEqual(len(head_traders(cfg)), 15)
        books_after = json.loads(books_path.read_text(encoding="utf-8"))
        for seat, digest in seat_hashes_before.items():
            self.assertEqual(sha256_json(books_after["seats"][seat]), digest)
        new_seat = books_after["seats"]["synthetic-fifteenth"]
        self.assertEqual(new_seat["nav_usd"], STARTING_NAV_USD)
        self.assertEqual(new_seat["positions"], [])
        self.assertEqual(new_seat["history"], [])
        identity_hashes_after = {
            str(path.relative_to(store.state_dir())): sha256_json(json.loads(path.read_text(encoding="utf-8")))
            for path in (store.state_dir() / "trader").rglob("*.json")
            if "synthetic-fifteenth" not in str(path)
        }
        self.assertEqual(identity_hashes_before, identity_hashes_after)

    def test_activate_refuses_existing_state(self) -> None:
        persona = _persona_file(self.tmp)
        onboard_mod.onboard_activate(
            root=self.tmp,
            trader_id="synthetic-fifteenth",
            remit="synthetic fixture seat for roster onboarding tests",
            specialty="rates_first",
            activation_date="2026-11-02",
            description="Synthetic fifteenth seat for onboarding tests.",
            persona=persona.read_text(encoding="utf-8"),
            may_no_trade=False,
            dry_run=False,
        )
        config_text_before = (self.tmp / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8")
        with self.assertRaises(Exception):
            onboard_mod.onboard_activate(
                root=self.tmp,
                trader_id="synthetic-fifteenth",
                remit="synthetic fixture seat for roster onboarding tests",
                specialty="rates_first",
                activation_date="2026-11-02",
                description="Synthetic fifteenth seat for onboarding tests.",
                persona=persona.read_text(encoding="utf-8"),
                may_no_trade=False,
                dry_run=False,
            )
        self.assertEqual(
            (self.tmp / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8"),
            config_text_before,
        )

    def test_dry_run_writes_nothing(self) -> None:
        persona = _persona_file(self.tmp)
        config_path = self.tmp / "scripts" / "trader_room" / "model_registry.json"
        before = config_path.read_text(encoding="utf-8")
        onboard_mod.onboard_pending(
            root=self.tmp,
            trader_id="synthetic-fifteenth",
            remit="synthetic fixture seat for roster onboarding tests",
            specialty="rates_first",
            activation_date="2026-11-02",
            description="Synthetic fifteenth seat for onboarding tests.",
            persona=persona.read_text(encoding="utf-8"),
            may_no_trade=False,
            dry_run=True,
        )
        self.assertEqual(config_path.read_text(encoding="utf-8"), before)
        self.assertFalse((self.tmp / ".cursor" / "agents" / "synthetic-fifteenth.md").exists())

    def test_subprocess_fifteen_seat_import(self) -> None:
        cfg = load_config(self.tmp / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        traders = list(cfg["roster"]["traders"])
        traders.append(
            {
                "id": "synthetic-fifteenth",
                "remit": "synthetic fixture seat for roster onboarding tests",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-11-02",
                "status": "active",
            }
        )
        cfg["roster"]["traders"] = traders
        cfg_path = self.tmp / "fifteen-seat-config.json"
        cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if k != "_source"}, indent=2) + "\n", encoding="utf-8")
        code = (
            "from scripts.trader_room.constants import STANDING_ADVOCATES; "
            "from scripts.overnight.constants import STANDING_SEATS; "
            "from scripts.overnight.books import empty_books; "
            "from scripts.trader_room.agent_config import daily_budget, ondemand_budget, build_pin; "
            "from scripts.trader_room.runners import build_launch_plan; "
            "assert len(STANDING_ADVOCATES)==15; "
            "assert len(STANDING_SEATS)==15; "
            "assert len(empty_books()['seats'])==15; "
            "assert daily_budget(15)['total_calls']==21; "
            "assert ondemand_budget(15)['total_calls']==61; "
            "pin=build_pin('daily'); "
            "assert pin['config_override'] is True; "
            "plan=build_launch_plan({'run_id':'tr-test','as_of':'2026-11-02','packet_sha256':'abc'}, pin=build_pin('ondemand')); "
            "assert plan['ceilings']['acp_parent_inclusive_total_ceiling']==61; "
            "assert plan['ceilings']['acp_parent_inclusive_grok_ceiling']==31"
        )
        proc = subprocess.run(
            ["python3", "-c", code],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT), "MW_AGENT_CONFIG_PATH": str(cfg_path)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_historical_fourteen_books_validate_against_legacy_pin(self) -> None:
        books = empty_books()
        legacy = legacy_pin("daily")
        validate_books(books, roster=pin_trader_ids(legacy), entries=legacy["traders"])
        cfg = load_config(self.tmp / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        traders = list(cfg["roster"]["traders"])
        traders.append(
            {
                "id": "synthetic-fifteenth",
                "remit": "synthetic fixture seat for roster onboarding tests",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-11-02",
                "status": "active",
            }
        )
        cfg_path = self.tmp / "fifteen-seat-roster.json"
        cfg15_raw = {k: v for k, v in cfg.items() if k != "_source"}
        cfg15_raw["roster"] = {**cfg["roster"], "traders": traders}
        cfg_path.write_text(json.dumps(cfg15_raw, indent=2) + "\n", encoding="utf-8")
        pin15 = build_pin("daily", config_path=cfg_path)
        before = {seat: sha256_json(payload) for seat, payload in books["seats"].items()}
        updated = ensure_roster_books(books, pin15["traders"])
        self.assertEqual(set(updated["seats"]), set(pin_trader_ids(pin15)))
        for seat, digest in before.items():
            self.assertEqual(sha256_json(updated["seats"][seat]), digest)
        self.assertIn("synthetic-fifteenth", updated["seats"])

    def test_ensure_roster_books_rejects_unknown_seat(self) -> None:
        books = empty_books()
        books["seats"]["unknown-seat"] = books["seats"]["perma-bull"]
        pin = build_pin("daily")
        with self.assertRaises(SchemaError):
            ensure_roster_books(books, pin["traders"])

    def test_freeze_prior_books_cold_starts_fifteenth_seat(self) -> None:
        cfg = load_config(self.tmp / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        traders = list(cfg["roster"]["traders"])
        traders.append(
            {
                "id": "synthetic-fifteenth",
                "remit": "synthetic fixture seat for roster onboarding tests",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-11-02",
                "status": "active",
            }
        )
        cfg_path = self.tmp / "fifteen-seat-roster.json"
        cfg15_raw = {k: v for k, v in cfg.items() if k != "_source"}
        cfg15_raw["roster"] = {**cfg["roster"], "traders": traders}
        cfg_path.write_text(json.dumps(cfg15_raw, indent=2) + "\n", encoding="utf-8")
        books_path = self.tmp / "data" / "overnight" / "books" / "latest.json"
        books_before = json.loads(books_path.read_text(encoding="utf-8"))
        seat_hashes_before = {seat: sha256_json(payload) for seat, payload in books_before["seats"].items()}
        prior_as_of = books_before["as_of"]
        store = OvernightStore(root=self.tmp, state_root=self.tmp)
        from datetime import datetime
        from zoneinfo import ZoneInfo

        when = datetime(2026, 11, 2, 1, 50, tzinfo=ZoneInfo("America/New_York"))
        pin = build_pin("daily", config_path=cfg_path)
        raw = store.read_books()
        merged = ensure_roster_books(raw, pin["traders"])
        self.assertEqual(merged["as_of"], prior_as_of)
        for seat, digest in seat_hashes_before.items():
            self.assertEqual(sha256_json(merged["seats"][seat]), digest)
        prior = _prepare_prior_books(store, pin, run_id="overnight-roster-freeze-test", when=when)
        self.assertEqual(prior["as_of"], prior_as_of)
        for seat in seat_hashes_before:
            self.assertEqual(prior["seats"][seat]["positions"], books_before["seats"][seat]["positions"])
            self.assertEqual(prior["seats"][seat]["history"], books_before["seats"][seat]["history"])
            self.assertEqual(prior["seats"][seat]["nav_usd"], books_before["seats"][seat]["nav_usd"])
        new_seat = prior["seats"]["synthetic-fifteenth"]
        self.assertEqual(new_seat["nav_usd"], STARTING_NAV_USD)
        self.assertEqual(new_seat["positions"], [])
        self.assertEqual(new_seat["history"], [])

    def test_freeze_embeds_pin(self) -> None:
        state_root = Path(tempfile.mkdtemp(prefix="mw-freeze-pin-"))
        self.addCleanup(lambda: shutil.rmtree(state_root, ignore_errors=True))
        store = OvernightStore(root=ROOT, state_root=state_root)
        run_id = "overnight-roster-pin-test"
        from scripts.overnight.pipeline import run_stage
        from datetime import datetime
        from zoneinfo import ZoneInfo

        when = datetime(2026, 9, 18, 1, 50, tzinfo=ZoneInfo("America/New_York"))
        for stage in ("collect", "pre_trader_delta"):
            run_stage(
                stage,
                root=ROOT,
                state_root=state_root,
                run_id=run_id,
                when=when,
                dry_run=True,
                market_state_path=FIXTURE,
            )
        packet = freeze_snapshot(store, run_id=run_id, when=when, reuse_open=False)
        self.assertIn("agent_roster_pin", packet)
        pin = packet["agent_roster_pin"]
        self.assertEqual(tuple(t["id"] for t in pin["traders"]), tuple(t["id"] for t in head_traders()))
        expected = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
        self.assertEqual(packet["packet_sha256"], expected)


if __name__ == "__main__":
    unittest.main()
