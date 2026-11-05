"""Role-tag and pin-aware guards for Market Watch budget hooks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.acp_handshake import build_delegation_request
from scripts.overnight.constants import ROOT
from scripts.overnight.errors import SchemaError
from scripts.overnight.scheduled_output import validate_execution
from scripts.trader_room import agent_config
from scripts.trader_room.budget import BudgetError, BudgetLedger
from scripts.trader_room.errors import ModelPolicyError

LEGACY_DAILY = agent_config.legacy_pin("daily")
DAILY_TRADERS = agent_config.pin_trader_ids(LEGACY_DAILY)
DAILY_PMS = list(LEGACY_DAILY["automated_pms"])
LEGACY_ONDEMAND = agent_config.legacy_pin("ondemand")
ONDEMAND_TRADERS = agent_config.pin_trader_ids(LEGACY_ONDEMAND)


def _daily_pin_with_extra_trader() -> dict:
    body = agent_config.build_pin("daily")
    traders = list(body["traders"])
    traders.append(
        {
            "id": "rates-first-extra",
            "remit": "synthetic fifteenth seat for pin guard tests",
            "expression_specialty": "rates_first",
            "may_no_trade": False,
            "activation_date": "2026-11-02",
        }
    )
    stripped = {k: v for k, v in body.items() if k not in ("budget", "roster_sha256", "pin_sha256")}
    stripped["traders"] = traders
    stripped["budget"] = agent_config.daily_budget(len(traders))
    return agent_config.seal_pin(stripped)


def _ondemand_pin_with_extra_trader() -> dict:
    body = agent_config.build_pin("ondemand")
    traders = list(body["traders"])
    traders.append(
        {
            "id": "rates-first-extra",
            "remit": "synthetic fifteenth seat",
            "expression_specialty": "rates_first",
            "may_no_trade": False,
            "activation_date": "2026-11-02",
        }
    )
    stripped = {k: v for k, v in body.items() if k not in ("budget", "roster_sha256", "pin_sha256")}
    stripped["traders"] = traders
    stripped["budget"] = agent_config.ondemand_budget(len(traders))
    return agent_config.seal_pin(stripped)


OVERNIGHT_POLICY_V1 = {
    "version": 1,
    "schedule_id": "market-watch-weekday-0205",
    "total_model_cap": 20,
    "grok_cap": 18,
    "composer_cap": 2,
    "parent_model": "grok-4.6",
    "parent_total": 1,
    "parent_grok": 1,
}

TR_POLICY_V1 = {
    "version": 1,
    "run_type": "trader-room-ondemand",
    "total_model_cap": 57,
    "grok_cap": 29,
    "composer_cap": 28,
    "parent_model": "grok-4.6",
    "parent_total": 1,
    "parent_grok": 1,
}


def _daily_pin_split_trader_model() -> dict:
    body = agent_config.build_pin("daily")
    roles = dict(body["roles"])
    if roles["trader"] == roles["advocate"]:
        other = "grok-4.6" if roles["trader"] != "grok-4.6" else "grok-4.7"
        roles["advocate"] = other
        roles["rebuttal"] = other
    families = dict(body["model_families"])
    known = {"grok-4.6": "grok", "grok-4.7": "grok", "composer-2.5": "composer"}
    needed = set(roles.values()) | set(body.get("pm_subagent_models") or [])
    for model in needed:
        families[model] = families.get(model) or known[model]
    stripped = {k: v for k, v in body.items() if k not in ("roster_sha256", "pin_sha256")}
    stripped["roles"] = roles
    stripped["model_families"] = families
    return agent_config.seal_pin(stripped)


class RoleGuardTests(unittest.TestCase):
    script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"
    shell_hook = ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        self.overnight_active = Path("/tmp/mw-overnight-active.json")
        self.overnight_lock = Path("/tmp/mw-overnight-budget.lock")
        self.tr_active = Path("/tmp/mw-trader-room-active.json")
        self.tr_lock = Path("/tmp/mw-trader-room-budget.lock")
        for path in (self.overnight_active, self.overnight_lock, self.tr_active, self.tr_lock):
            path.unlink(missing_ok=True)

    def tearDown(self) -> None:
        for path in (self.overnight_active, self.overnight_lock, self.tr_active, self.tr_lock):
            path.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _seed_overnight_repo(self, *, snapshot: dict | None = None) -> Path:
        repo = Path(self.tmp.name) / f"repo-{os.urandom(3).hex()}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        run_id = f"overnight-{today}"
        run_dir = repo / "data" / "overnight" / "runs" / run_id
        run_dir.mkdir(parents=True)
        run = {"stages": {"freeze_evidence": {"status": "succeeded"}}}
        snap = dict(
            snapshot
            or {
                "schema_version": 1,
                "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
                "as_of": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            }
        )
        snap["overnight_run_id"] = run_id
        unsigned = json.dumps(snap, indent=2, sort_keys=True) + "\n"
        snap["packet_sha256"] = hashlib.sha256(unsigned.encode("utf-8")).hexdigest()
        (run_dir / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
        (run_dir / "evidence_snapshot.json").write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "seed overnight"], cwd=repo, check=True)
        return repo

    def _seed_tr_repo(self, registry: dict | None = None) -> Path:
        repo = Path(self.tmp.name) / f"tr-{os.urandom(3).hex()}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        dst = repo / "scripts" / "trader_room" / "model_registry.json"
        dst.parent.mkdir(parents=True)
        if registry is None:
            shutil.copy2(ROOT / "scripts" / "trader_room" / "model_registry.json", dst)
        else:
            dst.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "seed registry"], cwd=repo, check=True)
        return repo

    def _write_marker(self, marker_line: str) -> None:
        self.transcript.write_text(marker_line + "\n", encoding="utf-8")

    def _hook(
        self,
        *,
        repo: Path,
        parent: str,
        model: str,
        task: str,
        child: str | None = None,
        subagent_type: str = "generalPurpose",
        active: Path | None = None,
    ) -> subprocess.CompletedProcess:
        event = {
            "subagent_id": child or f"child-{os.urandom(4).hex()}",
            "subagent_type": subagent_type,
            "task": task,
            "parent_conversation_id": parent,
            "tool_call_id": "tc",
            "subagent_model": model,
            "is_parallel_worker": False,
            "transcript_path": str(self.transcript),
        }
        env = os.environ.copy()
        if active is not None:
            pass
        return subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=repo,
            check=False,
            env=env,
        )

    def _shell_hook(self, *, model: str, transcript_text: str) -> subprocess.CompletedProcess:
        self.transcript.write_text(transcript_text + "\n", encoding="utf-8")
        return subprocess.run(
            ["sh", str(self.shell_hook), json.dumps({"subagent_model": model, "transcript_path": str(self.transcript)})],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )

    def _overnight_marker(self, pin: dict | None = None) -> str:
        if pin is None:
            return "MW_OVERNIGHT_RUN_POLICY=" + json.dumps(OVERNIGHT_POLICY_V1, separators=(",", ":"))
        return agent_config.overnight_policy_marker(pin)

    def _committed_ondemand_pin(self, repo: Path) -> dict:
        cfg = dict(
            agent_config.load_config(repo / "scripts" / "trader_room" / "model_registry.json", honor_env=False)
        )
        cfg["_source"] = "default"
        return agent_config.assert_acceptable_pin(agent_config.build_pin("ondemand", config=cfg))

    def test_untagged_daily_child_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task="no role here")
        self.assertNotEqual(blocked.returncode, 0)

    def test_pm_before_traders_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=pm:{DAILY_PMS[0]}")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("all pinned traders first", blocked.stdout)

    def test_traders_admitted_without_optional_synthesis(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        for seat in DAILY_TRADERS:
            admitted = self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{seat}")
            self.assertEqual(admitted.returncode, 0, admitted.stdout)
        late = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(late.returncode, 0)
        self.assertIn("before the first trader", late.stdout)

    def test_examiner_before_pms_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        for seat in DAILY_TRADERS:
            self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{seat}")
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=learning_examiner")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("requires all traders and PMs first", blocked.stdout)

    def test_synthesis_after_trader_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{DAILY_TRADERS[0]}")
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)

    def test_duplicate_seat_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        seat = DAILY_TRADERS[0]
        self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{seat}")
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{seat}")
        self.assertNotEqual(blocked.returncode, 0)

    def test_unknown_seat_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task="MW_ROLE=trader:not-a-real-seat")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("not-a-real-seat", blocked.stdout)

    def test_wrong_model_for_role_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        blocked = self._hook(
            repo=repo,
            parent="root",
            model="composer-2.5",
            task=f"MW_ROLE=trader:{DAILY_TRADERS[0]}",
        )
        self.assertNotEqual(blocked.returncode, 0)
        blocked_auto = self._hook(repo=repo, parent="root", model="auto", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked_auto.returncode, 0)
        blocked_grok47 = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.7",
            task="MW_ROLE=synthesis",
        )
        self.assertNotEqual(blocked_grok47.returncode, 0)

    def test_full_daily_graph_14_admits_exactly_20(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        for seat in DAILY_TRADERS:
            self.assertEqual(
                self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{seat}").returncode,
                0,
            )
        for pm_id in DAILY_PMS:
            self.assertEqual(
                self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=pm:{pm_id}").returncode,
                0,
            )
        self.assertEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=learning_examiner").returncode,
            0,
        )
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=f"MW_ROLE=trader:{DAILY_TRADERS[0]}")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_fifteen_seat_pin_allows_21_19_2(self) -> None:
        pin = _daily_pin_with_extra_trader()
        snap = {
            "schema_version": 1,
            "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
            "agent_roster_pin": pin,
        }
        repo = self._seed_overnight_repo(snapshot=snap)
        self._write_marker(self._overnight_marker(pin))
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        trader_model = pin["roles"]["trader"]
        pm_model = pin["roles"]["pm_principal"]
        for t in pin["traders"]:
            self._hook(repo=repo, parent="root", model=trader_model, task=f"MW_ROLE=trader:{t['id']}")
        for pm_id in DAILY_PMS:
            self._hook(repo=repo, parent="root", model=pm_model, task=f"MW_ROLE=pm:{pm_id}")
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=learning_examiner")
        blocked = self._hook(repo=repo, parent="root", model=trader_model, task="MW_ROLE=trader:rates-first-extra")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_v1_marker_rejected_when_pin_not_legacy(self) -> None:
        pin = _daily_pin_with_extra_trader()
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        self._write_marker(self._overnight_marker())
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)

    def test_v1_marker_accepted_on_legacy_snapshot(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        allowed = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertEqual(allowed.returncode, 0)

    def test_candidate_pin_denied(self) -> None:
        raw = agent_config.build_pin("daily")
        body = {k: v for k, v in raw.items() if k not in ("roster_sha256", "pin_sha256")}
        body["candidate"] = True
        body["profile_status"] = "candidate"
        pin = agent_config.seal_pin(body)
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        self._write_marker(agent_config.overnight_policy_marker(pin))
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)

    def test_config_override_pin_denied(self) -> None:
        cfg = agent_config.load_config(honor_env=False)
        cfg = dict(cfg)
        cfg["_source"] = "override"
        pin = agent_config.build_pin("daily", config=cfg)
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        self._write_marker(agent_config.overnight_policy_marker(pin))
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)

    def test_no_marker_allows(self) -> None:
        self.transcript.write_text("plain transcript\n", encoding="utf-8")
        allowed = subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(
                {
                    "subagent_id": "x",
                    "subagent_type": "generalPurpose",
                    "task": "MW_ROLE=synthesis",
                    "parent_conversation_id": "root",
                    "tool_call_id": "tc",
                    "subagent_model": "grok-4.6",
                    "transcript_path": str(self.transcript),
                }
            ),
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(allowed.returncode, 0)

    def test_ondemand_14_max_57(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        advocate = pin["roles"]["advocate"]
        self._write_marker("MW_TRADER_ROOM_RUN_POLICY=" + json.dumps(TR_POLICY_V1, separators=(",", ":")))
        blocked_v1 = self._hook(
            repo=repo,
            parent="root",
            model=advocate,
            task=f"MW_ROLE=advocate:{ONDEMAND_TRADERS[0]}",
            child="v1-denied",
        )
        self.assertNotEqual(blocked_v1.returncode, 0)
        self.tr_active.unlink(missing_ok=True)
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        advocates = []
        for seat in ONDEMAND_TRADERS:
            child = f"adv-{seat}"
            advocates.append(child)
            self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=advocate:{seat}", child=child)
        for seat in ONDEMAND_TRADERS:
            self._hook(
                repo=repo,
                parent="root",
                model=advocate,
                task=f"MW_ROLE=rebuttal:{seat}",
                child=f"reb-{seat}",
            )
        for adv in advocates:
            self._hook(repo=repo, parent=adv, model="composer-2.5", task="MW_ROLE=advocate_subagent", child=f"{adv}-a")
            self._hook(repo=repo, parent=adv, model="composer-2.5", task="MW_ROLE=advocate_subagent", child=f"{adv}-b")
        blocked = self._hook(
            repo=repo,
            parent="root",
            model=advocate,
            task=f"MW_ROLE=advocate:{ONDEMAND_TRADERS[0]}",
            child="extra",
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_ondemand_fifteen_max_61(self) -> None:
        registry = json.loads((ROOT / "scripts" / "trader_room" / "model_registry.json").read_text())
        registry["roster"]["traders"].append(
            {
                "id": "rates-first-extra",
                "remit": "synthetic fifteenth seat",
                "expression_specialty": "rates_first",
                "may_no_trade": False,
                "activation_date": "2026-11-02",
                "status": "active",
            }
        )
        repo = self._seed_tr_repo(registry)
        cfg = dict(agent_config.load_config(repo / "scripts" / "trader_room" / "model_registry.json", honor_env=False))
        cfg["_source"] = "default"
        pin = agent_config.build_pin("ondemand", config=cfg)
        policy = json.loads(agent_config.trader_room_policy_marker(pin).split("=", 1)[1])
        self._write_marker("MW_TRADER_ROOM_RUN_POLICY=" + json.dumps(policy, separators=(",", ":")))
        seats = agent_config.pin_trader_ids(pin)
        advocate = pin["roles"]["advocate"]
        advocates = []
        for seat in seats:
            child = f"adv-{seat}"
            advocates.append(child)
            self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=advocate:{seat}", child=child)
        for seat in seats:
            self._hook(
                repo=repo,
                parent="root",
                model=advocate,
                task=f"MW_ROLE=rebuttal:{seat}",
                child=f"reb-{seat}",
            )
        for adv in advocates:
            self._hook(repo=repo, parent=adv, model="composer-2.5", task="helper", child=f"{adv}-a")
            self._hook(repo=repo, parent=adv, model="composer-2.5", task="helper", child=f"{adv}-b")
        blocked = self._hook(
            repo=repo,
            parent="root",
            model=advocate,
            task=f"MW_ROLE=advocate:{seats[0]}",
            child="overflow",
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_rebuttal_requires_advocate_and_once(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        advocate = pin["roles"]["advocate"]
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        seat = ONDEMAND_TRADERS[0]
        blocked = self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=rebuttal:{seat}")
        self.assertNotEqual(blocked.returncode, 0)
        self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=advocate:{seat}", child="adv")
        self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=rebuttal:{seat}", child="reb1")
        blocked_dup = self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=rebuttal:{seat}", child="reb2")
        self.assertNotEqual(blocked_dup.returncode, 0)

    def test_rebuttal_cannot_launch_subagent(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        advocate = pin["roles"]["advocate"]
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        seat = ONDEMAND_TRADERS[0]
        self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=advocate:{seat}", child="adv")
        self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=rebuttal:{seat}", child="reb")
        blocked = self._hook(repo=repo, parent="reb", model="composer-2.5", task="MW_ROLE=advocate_subagent")
        self.assertNotEqual(blocked.returncode, 0)

    def test_third_composer_denied(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        advocate = pin["roles"]["advocate"]
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        seat = ONDEMAND_TRADERS[0]
        self._hook(repo=repo, parent="root", model=advocate, task=f"MW_ROLE=advocate:{seat}", child="adv")
        self._hook(repo=repo, parent="adv", model="composer-2.5", task="MW_ROLE=advocate_subagent", child="c1")
        self._hook(repo=repo, parent="adv", model="composer-2.5", task="MW_ROLE=advocate_subagent", child="c2")
        blocked = self._hook(repo=repo, parent="adv", model="composer-2.5", task="MW_ROLE=advocate_subagent", child="c3")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_subagent_type_mismatch_denied(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        advocate = pin["roles"]["advocate"]
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        seat = ONDEMAND_TRADERS[0]
        other = ONDEMAND_TRADERS[1]
        blocked = self._hook(
            repo=repo,
            parent="root",
            model=advocate,
            task=f"MW_ROLE=advocate:{seat}",
            subagent_type=other,
        )
        self.assertNotEqual(blocked.returncode, 0)

    def test_validate_execution_with_fifteen_pin(self) -> None:
        pin = _daily_pin_with_extra_trader()
        budget = pin["budget"]
        good = {
            "parent_model": pin["roles"]["parent"],
            "total_model_cap": budget["total_calls"],
            "grok_cap": budget["grok_family_calls"],
            "composer_cap": budget["composer_calls"],
            "declared_total_model_calls": budget["total_calls"],
            "declared_grok_calls": budget["grok_family_calls"],
            "declared_composer_calls": budget["composer_calls"],
            "other_models_calls": 0,
            "auto_used": False,
        }
        validate_execution(good, pin=pin)
        bad = dict(good, total_model_cap=20, grok_cap=18)
        with self.assertRaises(SchemaError):
            validate_execution(bad, pin=pin)

    def test_validate_execution_legacy_allowlist_still_required(self) -> None:
        execution = {
            "parent_model": "grok-4.6",
            "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
            "total_model_cap": 20,
            "grok_cap": 18,
            "composer_cap": 2,
            "declared_total_model_calls": 20,
            "declared_grok_calls": 18,
            "declared_composer_calls": 2,
            "other_models_calls": 0,
            "auto_used": False,
        }
        validate_execution(execution)

    def test_validate_execution_candidate_parent(self) -> None:
        raw = agent_config.build_pin("daily", profile_id="candidate-grok-4.7", allow_candidate=True)
        stripped = {k: v for k, v in raw.items() if k not in ("budget", "roster_sha256", "pin_sha256")}
        stripped["candidate"] = False
        stripped["budget"] = agent_config.daily_budget(len(stripped["traders"]))
        pin = agent_config.seal_pin(stripped)
        execution = {
            "parent_model": "grok-4.7",
            "total_model_cap": pin["budget"]["total_calls"],
            "grok_cap": pin["budget"]["grok_family_calls"],
            "composer_cap": pin["budget"]["composer_calls"],
            "declared_total_model_calls": pin["budget"]["total_calls"],
            "declared_grok_calls": pin["budget"]["grok_family_calls"],
            "declared_composer_calls": pin["budget"]["composer_calls"],
            "other_models_calls": 0,
            "auto_used": False,
        }
        validate_execution(execution, pin=pin)
        with self.assertRaises(SchemaError):
            validate_execution({**execution, "parent_model": "grok-4.6"}, pin=pin)
        validate_execution({**execution, "allowed_subagent_models": None}, pin=pin)

    def test_ondemand_budget_ledger_15(self) -> None:
        pin = _ondemand_pin_with_extra_trader()
        ledger = BudgetLedger(pin=pin)
        seats = agent_config.pin_trader_ids(pin)
        for seat in seats:
            ledger.charge("advocate", pin["roles"]["advocate"], seat, f"advocate {seat}")
        for seat in seats:
            ledger.charge("rebuttal", pin["roles"]["rebuttal"], seat, f"rebuttal {seat}")
        for seat in seats:
            ledger.charge("subagent", pin["roles"]["advocate_subagent"], seat, "sub1")
            ledger.charge("subagent", pin["roles"]["advocate_subagent"], seat, "sub2")
        with self.assertRaises(BudgetError):
            ledger.charge("subagent", pin["roles"]["advocate_subagent"], seats[0], "sub3")

    def test_ondemand_ledger_rejects_grok_4_7_on_4_6_pin(self) -> None:
        ledger = BudgetLedger(pin=agent_config.legacy_pin("ondemand"))
        seat = ONDEMAND_TRADERS[0]
        with self.assertRaises(BudgetError):
            ledger.charge("advocate", "grok-4.7", seat, "bad model")
        active = BudgetLedger()
        active.charge("advocate", "grok-4.7", seat, "active advocate")
        with self.assertRaises(BudgetError):
            active.charge("advocate", "grok-4.6", seat, "retired model")

    def test_delegation_request_shape_unchanged(self) -> None:
        request = build_delegation_request(
            {
                "launch_id": "mwl-test",
                "session_date": "2026-10-02",
                "review_id": "review-001",
                "request": {},
            }
        )
        budget = request["budget"]
        expected_keys = {
            "launcher_id",
            "legacy_schedule_id_inactive",
            "total_model_cap",
            "grok_cap",
            "composer_cap",
            "parent_model",
            "frozen_command",
            "launch_command",
            "current_graph",
        }
        self.assertEqual(set(budget.keys()), expected_keys)
        self.assertEqual(
            (budget["total_model_cap"], budget["grok_cap"], budget["composer_cap"], budget["parent_model"]),
            (20, 18, 2, "grok-4.7"),
        )

    def test_repeated_identical_mw_role_tag_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        seat = DAILY_TRADERS[0]
        dup = f"MW_ROLE=trader:{seat} MW_ROLE=trader:{seat}"
        blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=dup)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("exactly one MW_ROLE", blocked.stdout)

        repo_tr = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo_tr)
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        dup_adv = f"MW_ROLE=advocate:{seat} MW_ROLE=advocate:{seat}"
        blocked_adv = self._hook(repo=repo_tr, parent="root", model=pin["roles"]["advocate"], task=dup_adv)
        self.assertNotEqual(blocked_adv.returncode, 0)

    def test_nested_repeated_advocate_subagent_tag_denied(self) -> None:
        repo = self._seed_tr_repo()
        pin = self._committed_ondemand_pin(repo)
        self._write_marker(agent_config.trader_room_policy_marker(pin))
        seat = ONDEMAND_TRADERS[0]
        self._hook(repo=repo, parent="root", model=pin["roles"]["advocate"], task=f"MW_ROLE=advocate:{seat}", child="adv")
        blocked = self._hook(
            repo=repo,
            parent="adv",
            model="composer-2.5",
            task="MW_ROLE=advocate_subagent MW_ROLE=advocate_subagent",
            child="c1",
        )
        self.assertNotEqual(blocked.returncode, 0)

    def test_malformed_mw_role_tags_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        seat = DAILY_TRADERS[0]
        for task in (
            f"MW_ROLE=trader:{seat}/extra",
            f"MW_ROLE=trader:{seat}.bad",
            f"MW_ROLE=trader:{seat}:extra",
            f"mw_role=trader:{seat}",
            f"XMW_ROLE=trader:{seat}",
        ):
            blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=task)
            self.assertNotEqual(blocked.returncode, 0, task)

        backtick = f"`MW_ROLE=trader:{seat}`"
        allowed = self._hook(repo=repo, parent="root", model="grok-4.6", task=backtick)
        self.assertEqual(allowed.returncode, 0, allowed.stdout)

    def test_own_line_and_closing_punctuation_accepted(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        seat = DAILY_TRADERS[0]
        cases = (
            ("grok-4.6", f"MW_ROLE=trader:{seat}\n"),
            ("grok-4.6", f"Review the book.\nMW_ROLE=trader:{seat}\n"),
            ("grok-4.6", f"MW_ROLE=trader:{seat}."),
            ("grok-4.6", f"MW_ROLE=trader:{seat},"),
            ("grok-4.6", f"MW_ROLE=trader:{seat}, then the book"),
            ("grok-4.6", f"(MW_ROLE=trader:{seat})"),
            ("grok-4.6", f"**MW_ROLE=trader:{seat}**"),
            ("composer-2.5", "MW_ROLE=synthesis."),
        )
        for model, task in cases:
            self.overnight_active.unlink(missing_ok=True)
            allowed = self._hook(repo=repo, parent="root", model=model, task=task)
            self.assertEqual(allowed.returncode, 0, (task, allowed.stdout))

    def test_glued_punctuation_suffix_still_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        seat = DAILY_TRADERS[0]
        for task in (
            f"MW_ROLE=trader:{seat}.bad",
            f"MW_ROLE=trader:{seat},extra",
            f"MW_ROLE=trader:{seat})more",
            f"**MW_ROLE=trader:{seat}**extra",
            f"MW_ROLE=synthesis.extra",
            f"MW_ROLE=trader:{seat}. MW_ROLE=trader:{seat}",
        ):
            blocked = self._hook(repo=repo, parent="root", model="grok-4.6", task=task)
            self.assertNotEqual(blocked.returncode, 0, task)

    def test_unknown_role_and_seat_rules_denied(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        blocked_role = self._hook(repo=repo, parent="root", model="grok-4.6", task="MW_ROLE=advocate:perma-bull")
        self.assertNotEqual(blocked_role.returncode, 0)
        blocked_seat = self._hook(repo=repo, parent="root", model="grok-4.6", task="MW_ROLE=trader")
        self.assertNotEqual(blocked_seat.returncode, 0)
        blocked_syn = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis:perma-bull")
        self.assertNotEqual(blocked_syn.returncode, 0)

    def test_subagent_type_seat_rules(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        seat = DAILY_TRADERS[0]
        other = DAILY_TRADERS[1]
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        blocked = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.6",
            task=f"MW_ROLE=trader:{seat}",
            subagent_type=other,
        )
        self.assertNotEqual(blocked.returncode, 0)
        allowed = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.6",
            task=f"MW_ROLE=trader:{seat}",
            subagent_type=seat,
        )
        self.assertEqual(allowed.returncode, 0, allowed.stdout)

    def test_split_pin_daily_agent_subagent_type(self) -> None:
        pin = _daily_pin_split_trader_model()
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        self._write_marker(agent_config.overnight_policy_marker(pin))
        seat = agent_config.pin_trader_ids(pin)[0]
        daily_name = f"daily-{seat}"
        self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        blocked_seat = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.7",
            task=f"MW_ROLE=trader:{seat}",
            subagent_type=seat,
        )
        self.assertNotEqual(blocked_seat.returncode, 0)
        blocked_model = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.6",
            task=f"MW_ROLE=trader:{seat}",
            subagent_type=daily_name,
        )
        self.assertNotEqual(blocked_model.returncode, 0)
        allowed = self._hook(
            repo=repo,
            parent="root",
            model="grok-4.7",
            task=f"MW_ROLE=trader:{seat}",
            subagent_type=daily_name,
        )
        self.assertEqual(allowed.returncode, 0, allowed.stdout)

    def test_v1_marker_first_then_v2_denied(self) -> None:
        pin = _daily_pin_with_extra_trader()
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        v2 = agent_config.overnight_policy_marker(pin)
        self.transcript.write_text(
            "MW_OVERNIGHT_RUN_POLICY=" + json.dumps(OVERNIGHT_POLICY_V1, separators=(",", ":")) + "\n" + v2 + "\n",
            encoding="utf-8",
        )
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("non-legacy", blocked.stdout.lower())

    def test_later_quoted_marker_does_not_block_legacy_run(self) -> None:
        repo = self._seed_overnight_repo()
        self.transcript.write_text(
            self._overnight_marker()
            + "\n(tool output) docs say: MW_OVERNIGHT_RUN_POLICY={\"version\":1,...}\n",
            encoding="utf-8",
        )
        allowed = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertEqual(allowed.returncode, 0, allowed.stdout)

    def test_v2_marker_validation(self) -> None:
        pin = _daily_pin_with_extra_trader()
        snap = {"schema_version": 1, "type": "OVERNIGHT_EVIDENCE_SNAPSHOT", "agent_roster_pin": pin}
        repo = self._seed_overnight_repo(snapshot=snap)
        good = json.loads(agent_config.overnight_policy_marker(pin).split("=", 1)[1])
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(good, separators=(",", ":")))
        self.assertEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis").returncode,
            0,
        )

        extra = dict(good, extra_key=1)
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(extra, separators=(",", ":")))
        self.assertNotEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis").returncode,
            0,
        )

        bad_profile = dict(good, profile_id="wrong-profile")
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(bad_profile, separators=(",", ":")))
        self.assertNotEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis").returncode,
            0,
        )

        bad_roster = dict(good, roster_sha256="0" * 64)
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(bad_roster, separators=(",", ":")))
        self.assertNotEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis").returncode,
            0,
        )

        bad_traders = dict(good, traders=99)
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(bad_traders, separators=(",", ":")))
        self.assertNotEqual(
            self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis").returncode,
            0,
        )

    def test_v1_marker_wrong_parent_model_denied(self) -> None:
        repo = self._seed_overnight_repo()
        bad = dict(OVERNIGHT_POLICY_V1, parent_model="grok-4.7")
        self._write_marker("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(bad, separators=(",", ":")))
        blocked = self._hook(repo=repo, parent="root", model="composer-2.5", task="MW_ROLE=synthesis")
        self.assertNotEqual(blocked.returncode, 0)

    def test_mw_agent_config_path_does_not_override_hook(self) -> None:
        repo = self._seed_overnight_repo()
        self._write_marker(self._overnight_marker())
        permissive = Path(self.tmp.name) / "permissive_registry.json"
        shutil.copy2(ROOT / "scripts" / "trader_room" / "model_registry.json", permissive)
        env = os.environ.copy()
        env["MW_AGENT_CONFIG_PATH"] = str(permissive)
        event = {
            "subagent_id": "child-x",
            "subagent_type": "generalPurpose",
            "task": "MW_ROLE=synthesis",
            "parent_conversation_id": "root",
            "tool_call_id": "tc",
            "subagent_model": "grok-4.7",
            "transcript_path": str(self.transcript),
        }
        proc = subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=repo,
            check=False,
            env=env,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_shell_hook_overnight_marker_models(self) -> None:
        marker = self._overnight_marker()
        profile = agent_config.get_profile()
        daily = {
            profile["roles"]["synthesis"],
            profile["roles"]["trader"],
            profile["roles"]["pm_principal"],
            profile["roles"]["learning_examiner"],
        }
        for model in sorted(daily):
            proc = self._shell_hook(model=model, transcript_text=marker)
            self.assertEqual(proc.returncode, 0, (model, proc.stdout))
        for model in ("grok-4.6", "grok-4.7-high", "auto"):
            proc = self._shell_hook(model=model, transcript_text=marker)
            self.assertNotEqual(proc.returncode, 0, model)

    def test_shell_hook_acp_overrides_overnight_marker(self) -> None:
        marker = self._overnight_marker()
        acp = 'ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["grok-4.7","composer-2.5"]}'
        transcript = acp + "\n" + marker
        self.assertEqual(self._shell_hook(model="grok-4.7", transcript_text=transcript).returncode, 0)
        self.assertEqual(self._shell_hook(model="composer-2.5", transcript_text=transcript).returncode, 0)
        self.assertNotEqual(self._shell_hook(model="grok-4.6", transcript_text=transcript).returncode, 0)


if __name__ == "__main__":
    unittest.main()
