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
    assert_acceptable_pin,
    build_pin,
    check_agents,
    current_graph_marker_for,
    daily_budget,
    head_traders,
    legacy_equivalent,
    legacy_pin,
    load_config,
    ondemand_budget,
    overnight_policy_marker,
    render_agents,
    seal_pin,
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
        self.assertEqual(tuple(t["id"] for t in pin["traders"]), STANDING_ADVOCATES)
        for pt, ht in zip(pin["traders"], head, strict=True):
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

    def test_candidate_pin_requires_flag_and_is_stamped(self) -> None:
        with self.assertRaises(AgentConfigError):
            build_pin("daily", profile_id="candidate-grok-4.7")
        pin = build_pin("daily", profile_id="candidate-grok-4.7", allow_candidate=True)
        self.assertTrue(pin["candidate"])
        roles = pin["roles"]
        for role in ("parent", "trader", "advocate", "rebuttal", "pm_principal"):
            self.assertEqual(roles[role], "grok-4.7")
        for role in ("synthesis", "learning_examiner", "advocate_subagent"):
            self.assertEqual(roles[role], "composer-2.5")
        with self.assertRaises(AgentConfigError):
            assert_acceptable_pin(pin)

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
                {"trader": "grok-4.6", "rebuttal": "grok-4.7"}
            )
        )
        assert_bad(lambda d: d["profiles"][pid]["roles"].pop("parent"))
        assert_bad(
            lambda d: (
                d["profiles"].setdefault("extra-active", json.loads(json.dumps(prof))),
                d["profiles"]["extra-active"].update({"status": "active"}),
            )
        )
        assert_bad(lambda d: d.update({"active_profile": "candidate-grok-4.7"}))

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
            self.assertEqual(len(head_traders(cfg)), 14)
            pin = build_pin("daily", config=cfg)
            self.assertEqual(len(pin["traders"]), 14)
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

    def test_markers_legacy_bytes_match_commands(self) -> None:
        pin = legacy_pin("daily")
        overnight = overnight_policy_marker(pin)
        graph = current_graph_marker_for(pin)
        manual = (COMMANDS / "manual-market-watch-review.md").read_text(encoding="utf-8")
        overnight_cmd = (COMMANDS / "overnight-scheduled.md").read_text(encoding="utf-8")
        self.assertIn(overnight, manual)
        self.assertIn(overnight, overnight_cmd)
        self.assertIn(graph, manual)
        self.assertIn(graph, overnight_cmd)

        tr_pin = legacy_pin("ondemand")
        tr_marker = trader_room_policy_marker(tr_pin)
        trader_room = (COMMANDS / "trader-room.md").read_text(encoding="utf-8")
        self.assertIn(tr_marker, trader_room)

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
        body["budget"] = daily_budget(15)
        body["legacy"] = False
        sealed = seal_pin(body)
        self.assertFalse(legacy_equivalent(sealed))
        marker = overnight_policy_marker(sealed)
        self.assertIn('"version":2', marker)
        self.assertIn('"traders":15', marker)
        self.assertIn(sealed["roster_sha256"], marker)


if __name__ == "__main__":
    unittest.main()
