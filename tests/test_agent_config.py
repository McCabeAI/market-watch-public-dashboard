from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.trader_room.agent_config import (
    AgentConfigError,
    agent_for_role,
    assert_acceptable_pin,
    build_pin,
    check_agents,
    current_graph_marker_for,
    daily_budget,
    head_traders,
    launch_agents,
    legacy_equivalent,
    legacy_pin,
    load_config,
    ondemand_budget,
    overnight_policy_marker,
    pin_model_family,
    render_agents,
    scheduled_traders,
    seal_pin,
    set_role_model,
    today_ny,
    trader_room_policy_marker,
    verify_pin,
)
from scripts.trader_room.constants import ADVOCATE_REMITS, STANDING_ADVOCATES

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / ".cursor" / "commands"


class AgentConfigTests(unittest.TestCase):
    def test_legacy_pin_ignores_config(self) -> None:
        with patch("scripts.trader_room.agent_config.load_config", side_effect=AgentConfigError("boom")):
            pin = legacy_pin("daily")
        self.assertEqual(len(pin["traders"]), 14)
        self.assertTrue(pin["legacy"])

    def test_legacy_pin_matches_head_roster(self) -> None:
        pin = legacy_pin("daily")
        head = head_traders()
        legacy_ids = tuple(t["id"] for t in pin["traders"])
        self.assertEqual(legacy_ids, tuple(i for i in STANDING_ADVOCATES if i != "chart-guy"))
        self.assertNotIn("chart-guy", legacy_ids)
        head_by_id = {t["id"]: t for t in head}
        for pt in pin["traders"]:
            ht = head_by_id[pt["id"]]
            self.assertEqual(pt["id"], ht["id"])
            self.assertEqual(pt["remit"], ht["remit"])
            self.assertEqual(pt["remit"], ADVOCATE_REMITS[ht["id"]])
            self.assertEqual(pt["expression_specialty"], ht["expression_specialty"])
            self.assertEqual(pt["may_no_trade"], ht["may_no_trade"])
            self.assertEqual(pt["activation_date"], ht["activation_date"])

    def test_budgets_14_and_15(self) -> None:
        b14 = daily_budget(14)
        self.assertEqual(b14["total_calls"], 20)
        self.assertEqual(b14["grok_family_calls"], 18)
        self.assertEqual(b14["composer_calls"], 2)
        b15 = daily_budget(15)
        self.assertEqual(b15["total_calls"], 21)
        self.assertEqual(b15["grok_family_calls"], 19)
        self.assertEqual(b15["composer_calls"], 2)

        o14 = ondemand_budget(14)
        self.assertEqual(o14["total_calls"], 57)
        self.assertEqual(o14["grok_family_calls"], 29)
        self.assertEqual(o14["composer_calls"], 28)
        o15 = ondemand_budget(15)
        self.assertEqual(o15["total_calls"], 61)
        self.assertEqual(o15["grok_family_calls"], 31)
        self.assertEqual(o15["composer_calls"], 30)

        with self.assertRaises(AgentConfigError):
            ondemand_budget(0)

    def test_active_profile_pins_without_candidate_flag(self) -> None:
        pin = build_pin("daily")
        self.assertEqual(pin["profile_id"], "candidate-grok-4.7")
        self.assertFalse(pin["candidate"])
        roles = pin["roles"]
        for role in ("parent", "trader", "advocate", "rebuttal", "pm_principal"):
            self.assertEqual(roles[role], "grok-4.7")
        for role in ("synthesis", "learning_examiner", "advocate_subagent"):
            self.assertEqual(roles[role], "composer-2.5")
        assert_acceptable_pin(pin)
        with self.assertRaises(AgentConfigError):
            build_pin("daily", profile_id="current-production-grok-4.6")

    def test_candidate_status_still_requires_flag_and_is_refused(self) -> None:
        raw = _raw_config()
        raw["profiles"]["fixture-candidate"] = json.loads(json.dumps(raw["profiles"]["candidate-grok-4.7"]))
        raw["profiles"]["fixture-candidate"]["status"] = "candidate"
        path = _write_tmp_config(raw)
        try:
            cfg = load_config(path)
            with self.assertRaises(AgentConfigError):
                build_pin("daily", profile_id="fixture-candidate", config=cfg)
            pin = build_pin("daily", profile_id="fixture-candidate", config=cfg, allow_candidate=True)
            self.assertTrue(pin["candidate"])
            self.assertEqual(pin["roles"]["trader"], "grok-4.7")
            with self.assertRaises(AgentConfigError):
                assert_acceptable_pin(pin)
        finally:
            path.unlink(missing_ok=True)

    def test_env_path_stamps_config_override(self) -> None:
        cfg = load_config()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({k: v for k, v in cfg.items() if k != "_source"}, handle)
            path = handle.name
        try:
            loaded = load_config(Path(path))
            self.assertEqual(loaded["_source"], "override")
            pin = build_pin("daily", config=loaded)
            self.assertTrue(pin["config_override"])

            proc = subprocess.run(
                [
                    "python3",
                    "-c",
                    "from scripts.trader_room.agent_config import load_config, build_pin; "
                    "c=load_config(); p=build_pin('daily', config=c); "
                    "assert c['_source']=='override'; assert p['config_override']",
                ],
                cwd=str(ROOT),
                env={**os.environ, "PYTHONPATH": str(ROOT), "MW_AGENT_CONFIG_PATH": path},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_seal_and_verify_roundtrip(self) -> None:
        pin = build_pin("ondemand")
        sealed = seal_pin(dict(pin))
        verify_pin(sealed)
        bad = dict(sealed)
        bad["traders"] = [dict(bad["traders"][0])]
        bad["traders"][0]["remit"] = "tampered"
        with self.assertRaises(AgentConfigError):
            verify_pin(bad)

    def test_reject_prefix_family_auto_and_trader_advocate_drift(self) -> None:
        base = load_config()
        raw = {k: v for k, v in base.items() if not str(k).startswith("_")}

        def write_cfg(mutator) -> Path:
            data = json.loads(json.dumps(raw))
            mutator(data)
            handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(data, handle)
            handle.close()
            return Path(handle.name)

        def assert_bad(mutator) -> None:
            path = write_cfg(mutator)
            try:
                with self.assertRaises(AgentConfigError):
                    load_config(path)
            finally:
                path.unlink(missing_ok=True)

        pid = base["active_profile"]
        prof = raw["profiles"][pid]

        assert_bad(lambda d: d["profiles"][pid]["roles"].update({"trader": "grok-4.7-high-fast"}))
        assert_bad(lambda d: d["profiles"][pid]["roles"].update({"trader": "auto"}))
        assert_bad(lambda d: d["profiles"][pid]["roles"].update({"trader": "inherit"}))
        assert_bad(lambda d: d["profiles"][pid]["roles"].update({"trader": "composer-2.5"}))
        assert_bad(lambda d: d["profiles"][pid]["roles"].update({"synthesis": "grok-4.6"}))
        assert_bad(
            lambda d: d["profiles"][pid]["roles"].update(
                {"advocate": "grok-4.6", "rebuttal": "grok-4.7"}
            )
        )
        assert_bad(lambda d: d["profiles"][pid]["roles"].pop("parent"))
        assert_bad(
            lambda d: (
                d["profiles"].setdefault("extra-active", json.loads(json.dumps(prof))),
                d["profiles"]["extra-active"].update({"status": "active"}),
            )
        )
        assert_bad(lambda d: d.update({"active_profile": "current-production-grok-4.6"}))

    def test_pending_seat_excluded_from_head_and_pin(self) -> None:
        base = load_config()
        raw = {k: v for k, v in base.items() if not str(k).startswith("_")}
        raw["roster"]["traders"] = list(raw["roster"]["traders"]) + [
            {
                "id": "pending-seat",
                "remit": "synthetic pending trader for fixture",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-09-18",
                "status": "pending",
            }
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(raw, handle)
            path = Path(handle.name)
        try:
            cfg = load_config(path)
            self.assertEqual(len(head_traders(cfg)), len(head_traders()))
            pin = build_pin("daily", config=cfg)
            self.assertEqual(len(pin["traders"]), len(head_traders()))
            self.assertTrue(all(t["id"] != "pending-seat" for t in pin["traders"]))
        finally:
            path.unlink(missing_ok=True)

    def test_check_agents_passes_on_repo(self) -> None:
        errors = check_agents(ROOT)
        self.assertEqual(errors, [])

    def test_render_agents_rewrites_only_model_line(self) -> None:
        base = load_config()
        raw = {k: v for k, v in base.items() if not str(k).startswith("_")}
        raw["active_profile"] = "candidate-grok-4.7"
        raw["profiles"]["current-production-grok-4.6"]["status"] = "retired"
        raw["profiles"]["candidate-grok-4.7"]["status"] = "active"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            agents_src = ROOT / ".cursor" / "agents"
            agents_dst = tmp_root / ".cursor" / "agents"
            agents_dst.mkdir(parents=True)
            for path in agents_src.glob("*.md"):
                text = path.read_text(encoding="utf-8")
                (agents_dst / path.name).write_text(text, encoding="utf-8")

            cfg_path = tmp_root / "cfg.json"
            cfg_path.write_text(json.dumps(raw), encoding="utf-8")
            cfg = load_config(cfg_path)
            with patch.dict(os.environ, {"MW_AGENT_CONFIG_PATH": str(cfg_path)}):
                render_agents(tmp_root)
            for entry in head_traders(cfg):
                text = (agents_dst / f"{entry['id']}.md").read_text(encoding="utf-8")
                self.assertIn("model: grok-4.7[]", text)

    def test_legacy_markers_stay_v1_and_live_commands_do_not_embed_them(self) -> None:
        legacy = legacy_pin("daily")
        overnight = overnight_policy_marker(legacy)
        graph = current_graph_marker_for(legacy)
        self.assertIn('"version":1', overnight)
        self.assertIn('"parent_model":"grok-4.6"', overnight)
        self.assertIn('"version":1', graph)
        tr_marker = trader_room_policy_marker(legacy_pin("ondemand"))
        self.assertIn('"parent_model":"grok-4.6"', tr_marker)

        active = build_pin("daily")
        active_marker = overnight_policy_marker(active)
        self.assertIn('"version":2', active_marker)
        self.assertIn('"parent_model":"grok-4.7"', active_marker)
        self.assertIn(active["roster_sha256"], active_marker)
        bull = (ROOT / ".cursor" / "agents" / "perma-bull.md").read_text(encoding="utf-8")
        swinger = (ROOT / ".cursor" / "agents" / "swinger.md").read_text(encoding="utf-8")
        self.assertIn(f"model: {active['roles']['advocate']}[]", bull)
        self.assertIn(f"model: {active['roles']['pm_principal']}[]", swinger)

        live_commands = (
            COMMANDS / "manual-market-watch-review.md",
            COMMANDS / "overnight-scheduled.md",
            COMMANDS / "trader-room.md",
        )
        for path in live_commands:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(overnight, text, path.name)
            self.assertNotIn(graph, text, path.name)
            self.assertNotIn(tr_marker, text, path.name)
            self.assertNotIn("MW_OVERNIGHT_RUN_POLICY={", text, path.name)
            self.assertNotIn("MW_TRADER_ROOM_RUN_POLICY={", text, path.name)
            self.assertNotIn("MW_CURRENT_GRAPH={", text, path.name)
            self.assertNotIn("grok-4.6", text, path.name)
        manual = (COMMANDS / "manual-market-watch-review.md").read_text(encoding="utf-8")
        overnight_cmd = (COMMANDS / "overnight-scheduled.md").read_text(encoding="utf-8")
        trader_room = (COMMANDS / "trader-room.md").read_text(encoding="utf-8")
        self.assertIn("markers --kind daily --snapshot", manual)
        self.assertIn("markers --kind daily --snapshot", overnight_cmd)
        self.assertIn("markers --kind ondemand", trader_room)

    def test_v2_marker_for_fifteen(self) -> None:
        pin = build_pin("daily")
        traders = list(pin["traders"]) + [
            {
                "id": "fifteenth-seat",
                "remit": "fixture fifteenth active trader",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-09-18",
            }
        ]
        body = dict(pin)
        body["traders"] = traders
        seat_count = len(traders)
        body["budget"] = daily_budget(seat_count)
        body["legacy"] = False
        sealed = seal_pin(body)
        self.assertFalse(legacy_equivalent(sealed))
        marker = overnight_policy_marker(sealed)
        self.assertIn('"version":2', marker)
        self.assertIn(f'"traders":{seat_count}', marker)
        self.assertIn(sealed["roster_sha256"], marker)


def _raw_config() -> dict:
    return {k: v for k, v in load_config().items() if not str(k).startswith("_")}


def _write_tmp_config(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, handle, indent=2)
    handle.close()
    return Path(handle.name)


def _copy_agents(dst_root: Path) -> Path:
    agents_dst = dst_root / ".cursor" / "agents"
    agents_dst.mkdir(parents=True)
    for path in (ROOT / ".cursor" / "agents").glob("*.md"):
        (agents_dst / path.name).write_bytes(path.read_bytes())
    return agents_dst


class SplitWorkflowModelTests(unittest.TestCase):
    """Daily trader vs on-demand advocate models through separate custom agents."""

    def _split_raw(self) -> dict:
        raw = _raw_config()
        pid = raw["active_profile"]
        roles = raw["profiles"][pid]["roles"]
        roles["trader"] = "grok-4.6"
        roles["advocate"] = "grok-4.7"
        roles["rebuttal"] = "grok-4.7"
        return raw

    def test_split_profile_loads_and_pins_both_models(self) -> None:
        path = _write_tmp_config(self._split_raw())
        try:
            cfg = load_config(path)
            daily = build_pin("daily", config=cfg)
            ondemand = build_pin("ondemand", config=cfg)
            self.assertEqual(daily["roles"]["trader"], "grok-4.6")
            self.assertEqual(ondemand["roles"]["advocate"], "grok-4.7")
            self.assertEqual(daily["model_families"]["grok-4.7"], "grok")
            self.assertFalse(legacy_equivalent(daily))
            self.assertEqual(daily["budget"]["grok_family_calls"], len(daily["traders"]) + 4)
            rows = {r["tag"]: r for r in launch_agents(daily) if "tag" in r}
            self.assertEqual(rows["MW_ROLE=trader:perma-bull"]["agent"], "daily-perma-bull")
            self.assertEqual(rows["MW_ROLE=trader:perma-bull"]["model"], "grok-4.6")
            rows_od = {r["tag"]: r for r in launch_agents(ondemand) if "tag" in r}
            self.assertEqual(rows_od["MW_ROLE=advocate:perma-bull"]["agent"], "perma-bull")
            self.assertEqual(agent_for_role(daily["roles"], "pm_principal", "swinger"), "swinger")
            self.assertIsNone(agent_for_role(daily["roles"], "synthesis", None))
        finally:
            path.unlink(missing_ok=True)

    def test_render_split_then_unsplit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = _copy_agents(root)
            split_path = root / "split.json"
            split_path.write_text(json.dumps(self._split_raw()), encoding="utf-8")
            with patch.dict(os.environ, {"MW_AGENT_CONFIG_PATH": str(split_path)}):
                self.assertTrue(check_agents(root))
                render_agents(root)
                self.assertEqual(check_agents(root), [])
            daily = (agents / "daily-perma-bull.md").read_text(encoding="utf-8")
            base = (agents / "perma-bull.md").read_text(encoding="utf-8")
            self.assertIn("name: daily-perma-bull", daily)
            self.assertIn("model: grok-4.6[]", daily)
            self.assertIn("model: grok-4.7[]", base)
            self.assertEqual(daily.split("\n---\n", 1)[1], base.split("\n---\n", 1)[1])
            self.assertEqual(len(list(agents.glob("daily-*.md"))), len(head_traders()))

            (agents / "daily-perma-bull.md").write_text(daily + "\nHand edit.\n", encoding="utf-8")
            with patch.dict(os.environ, {"MW_AGENT_CONFIG_PATH": str(split_path)}):
                self.assertTrue(any("daily-perma-bull" in e for e in check_agents(root)))

            plain_path = root / "plain.json"
            plain_path.write_text(json.dumps(_raw_config()), encoding="utf-8")
            with patch.dict(os.environ, {"MW_AGENT_CONFIG_PATH": str(plain_path)}):
                self.assertTrue(any("stale" in e for e in check_agents(root)))
                render_agents(root)
                self.assertEqual(check_agents(root), [])
            self.assertEqual(list(agents.glob("daily-*.md")), [])
            for path in (ROOT / ".cursor" / "agents").glob("*.md"):
                self.assertEqual((agents / path.name).read_bytes(), path.read_bytes(), path.name)

    def test_advocate_rebuttal_split_rejected_with_reason(self) -> None:
        raw = _raw_config()
        pid = raw["active_profile"]
        raw["profiles"][pid]["roles"]["rebuttal"] = "grok-4.6"
        path = _write_tmp_config(raw)
        try:
            with self.assertRaisesRegex(AgentConfigError, "one frontmatter model"):
                load_config(path)
        finally:
            path.unlink(missing_ok=True)

    def test_unbudgeted_family_is_an_explicit_constraint(self) -> None:
        raw = _raw_config()
        raw["model_families"]["claude-opus-5-5"] = "claude"
        path = _write_tmp_config(raw)
        try:
            with self.assertRaisesRegex(AgentConfigError, "re-budget"):
                load_config(path)
        finally:
            path.unlink(missing_ok=True)

        raw = _raw_config()
        pid = raw["active_profile"]
        raw["profiles"][pid]["roles"]["trader"] = "composer-2.5"
        path = _write_tmp_config(raw)
        try:
            with self.assertRaisesRegex(AgentConfigError, "re-budget"):
                load_config(path)
        finally:
            path.unlink(missing_ok=True)

    def test_unapproved_or_runtime_slug_models_rejected(self) -> None:
        for bad in ("grok-4.7-high", "cursor-grok-4.7-high", "Auto", "default", "grok-4.5", "composer-2.5-fast"):
            raw = _raw_config()
            raw["profiles"]["candidate-grok-4.7"]["roles"]["trader"] = bad
            path = _write_tmp_config(raw)
            try:
                with self.assertRaises(AgentConfigError, msg=bad):
                    load_config(path)
            finally:
                path.unlink(missing_ok=True)

    def test_reserved_agent_names_rejected_as_trader_ids(self) -> None:
        for bad_id in ("daily-perma-bull", "final-aggregator"):
            raw = _raw_config()
            raw["roster"]["traders"].append(
                {
                    "id": bad_id,
                    "remit": "synthetic",
                    "expression_specialty": "rates_first",
                    "may_no_trade": False,
                    "activation_date": "2026-09-18",
                    "status": "pending",
                }
            )
            path = _write_tmp_config(raw)
            try:
                with self.assertRaises(AgentConfigError, msg=bad_id):
                    load_config(path)
            finally:
                path.unlink(missing_ok=True)


class PinIntegrityTests(unittest.TestCase):
    def test_verify_pin_never_reads_head_config(self) -> None:
        pin = build_pin("daily")
        with patch("scripts.trader_room.agent_config.load_config", side_effect=AgentConfigError("boom")):
            verify_pin(pin)
            legacy = legacy_pin("daily")
            verify_pin(legacy)
            self.assertFalse(legacy_equivalent(pin))
            self.assertEqual(pin_model_family(pin, pin["roles"]["parent"]), "grok")
            self.assertEqual(pin_model_family(legacy, "grok-4.6"), "grok")

    def test_pin_family_tamper_rejected(self) -> None:
        pin = build_pin("daily")
        body = dict(pin)
        body["model_families"] = {**pin["model_families"], "grok-4.6": "composer"}
        with self.assertRaises(AgentConfigError):
            verify_pin(seal_pin(body))
        body = {k: v for k, v in pin.items() if k != "model_families"}
        with self.assertRaises(AgentConfigError):
            verify_pin(seal_pin(body))
        body = dict(pin)
        body["model_families"] = {**pin["model_families"], "grok-4.8": "grok"}
        with self.assertRaises(AgentConfigError):
            verify_pin(seal_pin(body))

    def test_active_pin_is_grok_4_7_and_legacy_pin_stays_4_6(self) -> None:
        for kind, budget_fn in (("daily", daily_budget), ("ondemand", ondemand_budget)):
            pin = assert_acceptable_pin(build_pin(kind))
            self.assertFalse(legacy_equivalent(pin))
            self.assertEqual(pin["profile_id"], "candidate-grok-4.7")
            self.assertEqual(pin["roles"]["parent"], "grok-4.7")
            self.assertEqual(pin["roles"]["synthesis"], "composer-2.5")
            self.assertFalse(pin["candidate"])
            budget = pin["budget"]
            expected = budget_fn(len(pin["traders"]))
            self.assertEqual(
                (budget["total_calls"], budget["grok_family_calls"], budget["composer_calls"]),
                (expected["total_calls"], expected["grok_family_calls"], expected["composer_calls"]),
            )
            legacy = legacy_pin(kind)
            self.assertTrue(legacy_equivalent(legacy))
            self.assertEqual(legacy["roles"]["parent"], "grok-4.6")
            self.assertEqual(len(legacy["traders"]), 14)
            self.assertNotIn("chart-guy", [row["id"] for row in legacy["traders"]])


class PinConsumerTests(unittest.TestCase):
    def _pin_with_model_absent_from_head(self) -> dict:
        body = dict(build_pin("ondemand"))
        body["roles"] = {**body["roles"], "advocate": "grok-4.8", "rebuttal": "grok-4.8"}
        body["model_families"] = {**body["model_families"], "grok-4.8": "grok"}
        return seal_pin(body)

    def test_budget_ledger_charges_from_pin_families(self) -> None:
        from scripts.trader_room.budget import BudgetError, BudgetLedger

        pin = self._pin_with_model_absent_from_head()
        verify_pin(pin)
        ledger = BudgetLedger(pin=pin)
        ledger.charge("advocate", "grok-4.8", "perma-bull", "round1")
        self.assertEqual(ledger.grok, 1)
        with self.assertRaises(BudgetError):
            ledger.charge("advocate", "grok-4.6", "perma-bear", "round1")

    def test_dry_run_runner_charges_pinned_models(self) -> None:
        from scripts.trader_room.budget import BudgetLedger
        from scripts.trader_room.runners import _pinned_role_model

        pin = self._pin_with_model_absent_from_head()
        ledger = BudgetLedger(pin=pin)
        self.assertEqual(_pinned_role_model(ledger, "advocate", "grok-4.6"), "grok-4.8")
        self.assertEqual(_pinned_role_model(ledger, "advocate_subagent", "composer-2.5"), "composer-2.5")

    def test_handshake_fallback_pins_on_session_date(self) -> None:
        from scripts.market_watch_launch import acp_handshake

        seen: dict = {}
        real = acp_handshake.agent_config.build_pin

        def capture(kind, **kwargs):
            seen.update(kwargs)
            return real(kind, **kwargs)

        with patch.object(acp_handshake.agent_config, "build_pin", side_effect=capture):
            acp_handshake._resolve_daily_pin({"session_date": "2026-11-03"}, None)
        self.assertEqual(seen.get("as_of"), "2026-11-03")


class ActivationDateTests(unittest.TestCase):
    def _raw_with_seat(self, activation_date: str, status: str = "active") -> dict:
        raw = _raw_config()
        raw["roster"]["traders"].append(
            {
                "id": "synthetic-fifteenth",
                "remit": "synthetic fifteenth seat for activation-date tests",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": activation_date,
                "status": status,
            }
        )
        return raw

    def test_future_active_seat_not_pinned_until_date(self) -> None:
        path = _write_tmp_config(self._raw_with_seat("2026-12-01"))
        try:
            cfg = load_config(path)
            live = len(head_traders())
            before = build_pin("daily", config=cfg, as_of="2026-11-30")
            self.assertEqual(len(before["traders"]), live)
            self.assertEqual(before["roster_as_of"], "2026-11-30")
            self.assertEqual(before["budget"]["total_calls"], daily_budget(live)["total_calls"])
            self.assertEqual([t["id"] for t in scheduled_traders(cfg, as_of="2026-11-30")], ["synthetic-fifteenth"])
            on_day = build_pin("daily", config=cfg, as_of="2026-12-01")
            self.assertEqual(len(on_day["traders"]), live + 1)
            expected = daily_budget(live + 1)
            self.assertEqual(
                (on_day["budget"]["total_calls"], on_day["budget"]["grok_family_calls"], on_day["budget"]["composer_calls"]),
                (expected["total_calls"], expected["grok_family_calls"], expected["composer_calls"]),
            )
            od = build_pin("ondemand", config=cfg, as_of="2026-12-01")
            expected_od = ondemand_budget(live + 1)
            self.assertEqual(
                (od["budget"]["total_calls"], od["budget"]["grok_family_calls"], od["budget"]["composer_calls"]),
                (expected_od["total_calls"], expected_od["grok_family_calls"], expected_od["composer_calls"]),
            )
            od_before = build_pin("ondemand", config=cfg, as_of="2026-11-30")
            self.assertEqual(od_before["budget"]["total_calls"], ondemand_budget(live)["total_calls"])
        finally:
            path.unlink(missing_ok=True)

    def test_as_of_uses_new_york_date(self) -> None:
        from datetime import datetime, timezone

        late_utc = datetime(2026, 12, 1, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(today_ny(late_utc).isoformat(), "2026-11-30")
        path = _write_tmp_config(self._raw_with_seat("2026-12-01"))
        try:
            cfg = load_config(path)
            self.assertEqual(len(head_traders(cfg, as_of=late_utc)), len(head_traders()))
        finally:
            path.unlink(missing_ok=True)


class ChartGuySeatTests(unittest.TestCase):
    def test_chart_guy_is_active_only_on_and_after_his_activation_date(self) -> None:
        raw = _raw_config()
        row = next(item for item in raw["roster"]["traders"] if item["id"] == "chart-guy")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["activation_date"], "2026-11-07")
        before = build_pin("daily", as_of="2026-11-06")
        self.assertEqual(len(before["traders"]), 14)
        self.assertNotIn("chart-guy", [item["id"] for item in before["traders"]])
        self.assertEqual(
            (before["budget"]["total_calls"], before["budget"]["grok_family_calls"], before["budget"]["composer_calls"]),
            (20, 18, 2),
        )
        on_day = build_pin("daily", as_of="2026-11-07")
        self.assertEqual(len(on_day["traders"]), 15)
        self.assertEqual([item["id"] for item in on_day["traders"]].count("chart-guy"), 1)
        self.assertEqual(
            (on_day["budget"]["total_calls"], on_day["budget"]["grok_family_calls"], on_day["budget"]["composer_calls"]),
            (21, 19, 2),
        )
        legacy = legacy_pin("daily")
        self.assertEqual(len(legacy["traders"]), 14)
        self.assertNotIn("chart-guy", [item["id"] for item in legacy["traders"]])

    def test_chart_guy_joins_only_on_activation_date(self) -> None:
        raw = _raw_config()
        for item in raw["roster"]["traders"]:
            if item["id"] == "chart-guy":
                item["status"] = "active"
        path = _write_tmp_config(raw)
        try:
            cfg = load_config(path)
            before = build_pin("daily", config=cfg, as_of="2026-11-06")
            self.assertEqual(len(before["traders"]), 14)
            self.assertNotIn("chart-guy", [row["id"] for row in before["traders"]])
            self.assertEqual(
                (before["budget"]["total_calls"], before["budget"]["grok_family_calls"], before["budget"]["composer_calls"]),
                (20, 18, 2),
            )
            on_day = build_pin("daily", config=cfg, as_of="2026-11-07")
            self.assertEqual([row["id"] for row in on_day["traders"]].count("chart-guy"), 1)
            self.assertEqual(len(on_day["traders"]), 15)
            self.assertEqual(
                (on_day["budget"]["total_calls"], on_day["budget"]["grok_family_calls"], on_day["budget"]["composer_calls"]),
                (21, 19, 2),
            )
            ondemand = build_pin("ondemand", config=cfg, as_of="2026-11-07")
            self.assertEqual(
                (ondemand["budget"]["total_calls"], ondemand["budget"]["grok_family_calls"], ondemand["budget"]["composer_calls"]),
                (61, 31, 30),
            )
            before_od = build_pin("ondemand", config=cfg, as_of="2026-11-06")
            self.assertEqual(
                (before_od["budget"]["total_calls"], before_od["budget"]["grok_family_calls"], before_od["budget"]["composer_calls"]),
                (57, 29, 28),
            )
        finally:
            path.unlink(missing_ok=True)
        legacy = legacy_pin("daily")
        self.assertEqual(len(legacy["traders"]), 14)
        self.assertNotIn("chart-guy", [row["id"] for row in legacy["traders"]])

    def test_accepted_20261106_snapshot_stays_fourteen_seats(self) -> None:
        path = ROOT / "data" / "overnight" / "runs" / "overnight-20261106" / "reviews" / "review-001" / "evidence_snapshot.json"
        self.assertTrue(path.is_file())
        snap = json.loads(path.read_text(encoding="utf-8"))
        pin = snap["agent_roster_pin"]
        self.assertEqual(len(pin["traders"]), 14)
        self.assertNotIn("chart-guy", [row["id"] for row in pin["traders"]])
        self.assertEqual(pin["budget"]["total_calls"], 20)
        self.assertNotIn("fx_technical", snap)
        from scripts.overnight.books import validate_books
        from scripts.trader_room.agent_config import pin_trader_ids

        validate_books(snap["prior_books"], roster=pin_trader_ids(pin), entries=pin["traders"])


class SetRoleTests(unittest.TestCase):
    def test_set_role_guards_and_pairs_debate_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model_registry.json"
            original = (ROOT / "scripts" / "trader_room" / "model_registry.json").read_bytes()
            path.write_bytes(original)
            with self.assertRaisesRegex(AgentConfigError, "ACP-owned"):
                set_role_model("candidate-grok-4.7", "parent", "grok-4.6", config_path=path)
            with self.assertRaisesRegex(AgentConfigError, "active production profile"):
                set_role_model("candidate-grok-4.7", "trader", "grok-4.6", config_path=path)
            with self.assertRaises(AgentConfigError):
                set_role_model("current-production-grok-4.6", "trader", "composer-2.5", config_path=path)
            with self.assertRaises(AgentConfigError):
                set_role_model("current-production-grok-4.6", "advocate", "grok-4.7-high", config_path=path)
            self.assertEqual(path.read_bytes(), original)

            changed = set_role_model("current-production-grok-4.6", "advocate", "grok-4.7", config_path=path)
            self.assertEqual(changed, ["advocate", "rebuttal"])
            cfg = load_config(path, honor_env=False)
            roles = cfg["profiles"]["current-production-grok-4.6"]["roles"]
            self.assertEqual((roles["trader"], roles["advocate"], roles["rebuttal"]), ("grok-4.6", "grok-4.7", "grok-4.7"))
            self.assertEqual(cfg["profiles"]["candidate-grok-4.7"]["status"], "active")
            self.assertEqual(cfg["active_profile"], "candidate-grok-4.7")


if __name__ == "__main__":
    unittest.main()
