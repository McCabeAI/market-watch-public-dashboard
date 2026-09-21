from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.pipeline import run_stage
from scripts.overnight.scheduled_output import (
    AGENT_PACKET_TYPE,
    SCHEDULE_ID,
    apply_output,
    simulate_output,
    validate_output,
)
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.trade_presentation import PresentationError, validate_trade_presentation
from scripts.pm.portfolio import synthetic_portfolio_construction

AS_OF = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
POLICY = {
    "version": 1,
    "schedule_id": SCHEDULE_ID,
    "total_model_cap": 19,
    "grok_cap": 18,
    "composer_cap": 2,
    "parent_model": "grok-4.6",
    "parent_total": 1,
    "parent_grok": 1,
}


def _presentation(expression: str = "Stay flat") -> dict:
    return {
        "market_expression": expression,
        "punchline": f"{expression}. No incremental edge in this fixture.",
        "support": ["The fixture is testing workflow mechanics, not a live investment view."],
        "take_profit": {
            "objective": "N/A while flat",
            "basis": "No position is being opened in this fixture.",
            "pnl_target_usd": None,
        },
        "invalidation": "A live validated decision replaces this fixture.",
    }


def _pm_block(run_id: str, packet_hash: str, cutoff: str) -> dict:
    out = {}
    for pm_id in ("swinger", "pragmatist", "grinder"):
        out[pm_id] = {
            "pm_id": pm_id,
            "overnight_run_id": run_id,
            "packet_sha256": packet_hash,
            "evidence_cutoff": cutoff,
            "principal_model": "grok-4.6",
            "subagent_count": 0,
            "subagent_models": [],
            "actions": [{"action": "HOLD"}],
            "thesis": "Await cleaner setup.",
            "invalidation": None,
            "presentation": _presentation(),
            "conviction": 20,
        }
        if pm_id == "pragmatist":
            out[pm_id]["portfolio_construction"] = synthetic_portfolio_construction(
                existing_book="Pragmatist book is flat in this scheduled-output fixture.",
                rationale="No independent markable complementary trade improves the opportunistic book; HOLD is explicit.",
            )
    return out


def _skeptic_funding_view() -> dict:
    return {
        "current_sofr": "Frozen official NY Fed SOFR fixing in funding_context.",
        "sr3_forward_view": "Frozen SR3 contracts are the relevant forward-funding path.",
        "forward_funding_assessment": "about_the_same",
        "implication": "Remain at the zero official-SOFR benchmark unless a packet-supported trade beats SOFR charged on shocked-risk capital. Flat cash is not alpha.",
    }


def _hold_decision(seat: str, run_id: str, packet_hash: str, cutoff: str) -> dict:
    return {
        "seat": seat,
        "overnight_run_id": run_id,
        "packet_sha256": packet_hash,
        "evidence_cutoff": cutoff,
        "conviction": 25,
        "thesis": "No incremental edge.",
        "invalidation": None,
        "presentation": _presentation(),
        "required_pitch": None,
        "risk_put_on": None,
        "expression_memo": {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "Hold existing risk.",
        },
        "actions": [
            {
                "action": "HOLD",
                "expression_memo": {
                    "rates_candidate": None,
                    "spot_candidate": None,
                    "options_candidate": None,
                    "selected": "none",
                    "rationale": "Hold existing risk.",
                },
            }
        ],
        "alerts": [],
        **({"funding_view": _skeptic_funding_view()} if seat == "no-trade-skeptic" else {}),
    }


class ScheduledOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.run_id = "overnight-20260918"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=self.run_id,
                when=AS_OF,
                dry_run=True,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
            )
        self.store = OvernightStore(root=ROOT, state_root=self.state_root)
        self.base = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.payload = self._payload()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _payload(self) -> dict:
        packet = {
            "schema_version": 1,
            "type": AGENT_PACKET_TYPE,
            "overnight_run_id": self.run_id,
            "base_packet_sha256": self.base["packet_sha256"],
            "base_evidence_cutoff": self.base["as_of"],
            "evidence_cutoff": "2026-09-18T02:20:00-04:00",
            "competition": self.base["competition"],
            "research_supplement": {
                "summary": "No material new research after the deterministic cutoff.",
                "news": [],
                "central_bank_research": [],
                "sources": [],
            },
        }
        packet["packet_sha256"] = sha256_json(packet)
        return {
            "schema_version": 1,
            "type": "OVERNIGHT_SCHEDULED_OUTPUT",
            "schedule_id": SCHEDULE_ID,
            "overnight_run_id": self.run_id,
            "base_packet_sha256": self.base["packet_sha256"],
            "agent_packet": packet,
            "decisions": {
                seat: _hold_decision(seat, self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
                for seat in STANDING_SEATS
            },
            "pm_decisions": _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"]),
            "execution": {
                "parent_model": "grok-4.6",
                "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
                "total_model_cap": 19,
                "grok_cap": 18,
                "composer_cap": 2,
                "declared_total_model_calls": 19,
                "declared_grok_calls": 18,
                "declared_composer_calls": 1,
                "other_models_calls": 0,
                "auto_used": False,
            },
        }

    def test_valid_output_simulates_without_model_book_state(self) -> None:
        validate_output(self.store, self.payload)
        review = simulate_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        self.assertEqual(review["model_calls"], 19)
        self.assertIn("pm_books", review)
        self.assertIn("pm_packets", review)
        self.assertEqual(set(review["reviews"]), set(STANDING_SEATS))

    def test_apply_writes_books_and_marks_trader_stage(self) -> None:
        review = apply_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        run = self.store.read_artifact(self.run_id, "run.json")
        self.assertEqual(run["stages"]["trader_review"]["status"], "succeeded")
        self.assertEqual(self.store.read_books()["last_successful_review_run_id"], self.run_id)

    def test_no_trade_hold_requires_daily_funding_view(self) -> None:
        del self.payload["decisions"]["no-trade-skeptic"]["funding_view"]
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_scheduled_open_uses_frozen_mid_not_model_price(self) -> None:
        memo = {
            "rates_candidate": None,
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Dedicated USD spot seat.",
        }
        decision = self.payload["decisions"]["dollar-king"]
        decision["expression_memo"] = memo
        decision["thesis"] = "USD remains the cleanest G10 expression in the frozen packet."
        decision["memory_context_sha256"] = self.base["seat_memory"]["hashes"]["dollar-king"]
        decision["actions"] = [{
            "action": "OPEN",
            "instrument": "USDCAD",
            "side": "long",
            "notional_usd": 10_000_000,
            "price": 9.99,
            "asset_class": "spot_fx",
            "expression_memo": memo,
        }]
        packet = self.payload["agent_packet"]
        pm = self.payload["pm_decisions"]
        pm["pragmatist"]["portfolio_construction"] = synthetic_portfolio_construction(
            opportunities=[
                {
                    "instrument": "USDCAD",
                    "rationale": "Independent markable USD-CAD handoff from the frozen overnight review.",
                    "markable": True,
                },
            ],
            existing_book="Pragmatist book is flat in this scheduled-output fixture.",
            rationale="Evaluated the USD-CAD handoff; HOLD remains valid for the opportunistic book.",
        )
        review = simulate_output(self.store, self.payload)
        pos = review["books"]["seats"]["dollar-king"]["positions"][0]
        self.assertEqual(pos["entry_price"], 1.36)
        self.assertEqual(pos["mark_price"], 1.36)
        self.assertIn("market_state.fx.USDCAD.spot", pos["entry_price_source"])

    def test_rejects_model_calculated_book_state(self) -> None:
        self.payload["books"] = {"nav_usd": 999}
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_rejects_changed_competition_contract(self) -> None:
        self.payload["agent_packet"]["competition"]["funding_rate_annual"] = 0.0
        self.payload["agent_packet"]["packet_sha256"] = sha256_json(
            {k: v for k, v in self.payload["agent_packet"].items() if k != "packet_sha256"}
        )
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_rejects_wrong_packet_hash(self) -> None:
        self.payload["agent_packet"]["packet_sha256"] = "bad"
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_workflows_have_no_direct_cursor_runtime(self) -> None:
        overnight = (ROOT / ".github" / "workflows" / "overnight-pipeline.yml").read_text(encoding="utf-8")
        gate = (ROOT / ".github" / "workflows" / "overnight-scheduled-output.yml").read_text(encoding="utf-8")
        for forbidden in ("CURSOR_API_KEY", "curl https://cursor.com/install", "agent -p", "--model \"grok-4.6\""):
            self.assertNotIn(forbidden, overnight)
            self.assertNotIn(forbidden, gate)
        self.assertNotIn('"5 2 * * 1-5"', overnight)
        self.assertIn("pull_request_target", gate)
        self.assertIn("scheduled_output.py validate", gate)
        self.assertIn("scheduled_output.py apply", gate)
        self.assertIn("data/trading", gate)
        for cron in ('"7 0 * * 1-5"', '"40 1 * * 1-5"', '"50 1 * * 1-5"', '"35 3 * * 1-5"', '"50 3 * * 1-5"', '"7 4 * * 1-5"'):
            self.assertIn(cron, overnight)
        self.assertIn("market-watch-weekday-0205", (ROOT / "docs" / "OVERNIGHT_PIPELINE_V1.md").read_text(encoding="utf-8"))


class BudgetHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = Path("/tmp/mw-overnight-active.json")
        self.lock = Path("/tmp/mw-overnight-budget.lock")
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        marker = "MW_OVERNIGHT_RUN_POLICY=" + json.dumps(POLICY, separators=(",", ":"))
        self.transcript.write_text(marker + "\n", encoding="utf-8")
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        run_id = f"overnight-{today}"
        run_dir = self.repo / "data" / "overnight" / "runs" / run_id
        run_dir.mkdir(parents=True)
        run = {"stages": {"freeze_evidence": {"status": "succeeded"}}}
        snapshot = {
            "schema_version": 1,
            "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
            "overnight_run_id": run_id,
            "as_of": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        }
        unsigned = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        snapshot["packet_sha256"] = hashlib.sha256(unsigned.encode("utf-8")).hexdigest()
        (run_dir / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
        (run_dir / "evidence_snapshot.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "seed trusted freeze"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _call(self, parent: str, model: str, *, child_id: str | None = None) -> subprocess.CompletedProcess:
        event = {
            "subagent_id": child_id or f"sub-{model}-{os.urandom(4).hex()}",
            "subagent_type": "generalPurpose",
            "task": "test",
            "parent_conversation_id": parent,
            "tool_call_id": "tc",
            "subagent_model": model,
            "is_parallel_worker": False,
            "transcript_path": str(self.transcript),
        }
        return subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=self.repo,
            check=False,
        )

    def test_budget_enforces_total_and_per_model_caps(self) -> None:
        # Parent already counted: total=1, grok=1
        self.assertEqual(self._call("root", "composer-2.5").returncode, 0)
        for _ in range(14):
            self.assertEqual(self._call("root", "grok-4.6").returncode, 0)
        for _ in range(3):
            self.assertEqual(self._call("root", "grok-4.6").returncode, 0)
        blocked_grok = self._call("root", "grok-4.6")
        self.assertNotEqual(blocked_grok.returncode, 0)
        self.assertIn("cap", blocked_grok.stdout.lower())
        blocked_composer = self._call("root", "composer-2.5")
        self.assertNotEqual(blocked_composer.returncode, 0)
        self.assertIn("cap", blocked_composer.stdout.lower())

    def test_missing_committed_freeze_blocks_first_child(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        snapshot = self.repo / "data" / "overnight" / "runs" / f"overnight-{today}" / "evidence_snapshot.json"
        subprocess.run(["git", "rm", "-q", str(snapshot.relative_to(self.repo))], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "remove freeze"], cwd=self.repo, check=True)
        blocked = self._call("root", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("trusted freeze", blocked.stdout.lower())

    def test_nested_child_is_denied(self) -> None:
        self.assertEqual(self._call("root", "composer-2.5").returncode, 0)
        blocked = self._call("child-conversation", "grok-4.6")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("nested", blocked.stdout.lower())

    def test_other_model_is_denied(self) -> None:
        blocked = self._call("root", "claude-sonnet-5")
        self.assertNotEqual(blocked.returncode, 0)


class OvernightRuntimeHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-runtime.py"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _call(self, marker: str) -> subprocess.CompletedProcess:
        self.transcript.write_text(marker + "\nresearch notes\n", encoding="utf-8")
        event = {
            "tool_name": "WebSearch",
            "transcript_path": str(self.transcript),
        }
        return subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def test_unfrozen_parent_may_use_tools(self) -> None:
        proc = self._call("MW_OVERNIGHT_RUN_POLICY={\"version\":1}")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("allow", proc.stdout)

    def test_frozen_trader_tools_denied(self) -> None:
        proc = self._call("MW_TRADER_FROZEN=1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("trader", proc.stdout.lower())

    def test_frozen_pm_tools_denied(self) -> None:
        proc = self._call("MW_PM_FROZEN=1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("pm", proc.stdout.lower())

    def test_conflicting_frozen_markers_denied(self) -> None:
        proc = self._call("MW_TRADER_FROZEN=1\nMW_PM_FROZEN=1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("conflict", proc.stdout.lower())


class TradePresentationValidationTests(unittest.TestCase):
    def _valid(self, **overrides):
        base = {
            "market_expression": "Receive H7 CORRA",
            "punchline": "Receive H7 CORRA — Mar-27 still prices too much hiking.",
            "support": ["Core and labor have not validated the priced 2027 path."],
            "take_profit": {
                "objective": "Take profit if implied cheapens toward Z6 CORRA.",
                "basis": "Historical analog when front-end cuts arrive before the belly.",
                "pnl_target_usd": None,
            },
            "invalidation": "Close if BoC endorses the priced 2027 path.",
        }
        base.update(overrides)
        return base

    def test_accepts_desk_shorthand(self) -> None:
        out = validate_trade_presentation(self._valid(), label="fixture", required=True)
        self.assertEqual(out["market_expression"], "Receive H7 CORRA")

    def test_rejects_normalized_ids_and_robot_labels(self) -> None:
        with self.assertRaises(PresentationError):
            validate_trade_presentation(
                self._valid(punchline="Hold CORRA_2027-03 receive."),
                label="fixture",
                required=True,
            )
        with self.assertRaises(PresentationError):
            validate_trade_presentation(
                self._valid(punchline="FACT: still receive H7 CORRA."),
                label="fixture",
                required=True,
            )

    def test_optional_when_not_required(self) -> None:
        self.assertIsNone(validate_trade_presentation(None, label="fixture", required=False))


if __name__ == "__main__":
    unittest.main()
