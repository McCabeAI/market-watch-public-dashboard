#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from scripts.apply_overnight_news_refresh import apply_overnight_news_refresh
from scripts.overnight.accepted_news import overlay_accepted_research
from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.errors import PublicationError
from scripts.overnight.freshness import publication_decision
from scripts.overnight.pipeline import run_stage
from scripts.overnight.publish import publication_gate
from scripts.overnight.scheduled_output import (
    AGENT_PACKET_TYPE,
    SCHEDULE_ID,
    simulate_output,
)
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.pm.grinder import synthetic_grinder_hurdle
from scripts.pm.portfolio import synthetic_portfolio_construction

AS_OF = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
ACCEPTED_ARTIFACT = ROOT / "data" / "overnight" / "accepted_public_news.json"
SEP18_HTML = """
<div class="last24">
  <div class="last24-head">
    <div class="last24-window"><b>Window</b>stale<br>Last refreshed 18 Sep 2026 · 04:00 ET</div>
  </div>
  <div class="last24-grid"><b>Stale Sep 18 headline only</b></div>
</div>
<div class="stitle">Top Market Drivers</div><div class="driver-grid">OLD</div>
<div class="x-signal"><div>X</div></div>
"""

FRESH_NEWS_ITEM = {
    "country_codes": ["US"],
    "headline": "Oil rebounds in early 22 September trade on U.S.–Iran headlines and supply risks",
    "primary_category": "energy",
    "published_at": "2026-09-22T04:22:00-04:00",
    "source_name": "CNBC",
    "summary": "Brent and WTI rebounded in early Tuesday trade.",
    "url": "https://www.cnbc.com/2026/09/22/oil-iran-us-bessent-un-crude.html",
}
ACTIVITY_ITEM = {
    "country_codes": ["US"],
    "headline": "Chicago Fed national activity index slips to -0.04 in August",
    "primary_category": "activity",
    "published_at": "2026-09-21T08:30:00-04:00",
    "source_name": "Federal Reserve Bank of Chicago",
    "summary": "The Chicago Fed CFNAI for August 2026 was -0.04.",
    "url": "https://www.chicagofed.org/research/data/cfnai/current-data",
}


def _dataset_from_accepted() -> dict:
    artifact = json.loads((ROOT / "data" / "overnight" / "accepted_public_news.json").read_text(encoding="utf-8"))
    return {
        "type": "OVERNIGHT_MORNING_DATASET",
        "overnight_run_id": artifact["overnight_run_id"],
        "agent_research_cutoff": artifact["as_of"],
        "agent_research": {
            "summary": artifact.get("summary"),
            "news": artifact["news"],
            "central_bank_research": artifact["central_bank_research"],
        },
    }


def _skeptic_funding_view() -> dict:
    return {
        "current_sofr": "Frozen official NY Fed SOFR fixing in funding_context.",
        "sr3_forward_view": "Frozen SR3 contracts are the relevant forward-funding path.",
        "forward_funding_assessment": "about_the_same",
        "implication": "Remain at the zero official-SOFR benchmark unless a packet-supported trade beats SOFR charged on shocked-risk capital. Flat cash is not alpha.",
    }


def _spot_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated USD spot seat.",
    }


class AcceptedNewsArchitectureTests(unittest.TestCase):
    def test_overlay_upgrades_stale_freeze_news_without_mutating_input(self) -> None:
        families = {
            "news": {"status": "stale", "as_of": "2026-09-18T04:00:00", "items": [{"headline": "old"}]},
            "macro_hard": {"status": "fresh", "as_of": "2026-09-22T04:00:00"},
            "market_state": {"status": "fresh", "as_of": "2026-09-22T04:00:00"},
            "central_bank_research": {"status": "stale", "as_of": "2026-09-18T04:00:00", "items": []},
        }
        packet = {
            "evidence_cutoff": "2026-09-22T06:52:19-04:00",
            "research_supplement": {
                "summary": "Energy rebounded.",
                "news": [FRESH_NEWS_ITEM, ACTIVITY_ITEM],
                "central_bank_research": [],
            },
        }
        original_status = families["news"]["status"]
        out = overlay_accepted_research(families, packet, when=AS_OF)
        self.assertEqual(original_status, "stale")
        self.assertEqual(out["news"]["status"], "fresh")
        self.assertEqual(out["news"]["items"][0]["headline"], FRESH_NEWS_ITEM["headline"])
        self.assertEqual(families["news"]["status"], "stale")

    def test_pages_refresh_replaces_sep18_visible_news(self) -> None:
        out = apply_overnight_news_refresh(SEP18_HTML, _dataset_from_accepted())
        self.assertIn("Last refreshed 22 Sep 2026", out)
        self.assertIn("Oil rebounds in early 22 September trade", out)
        self.assertIn("Chicago Fed national activity index slips", out)
        self.assertNotIn("Stale Sep 18 headline only", out)

    def test_publication_fails_without_trusted_fresh_news(self) -> None:
        families = {
            "macro_hard": {"status": "fresh", "as_of": isoformat(AS_OF)},
            "news": {"status": "stale", "as_of": "2026-09-18T04:00:00"},
            "central_bank_research": {"status": "stale", "as_of": "2026-09-18T04:00:00"},
            "market_state": {"status": "fresh", "as_of": isoformat(AS_OF)},
        }
        decision = publication_decision(families=families, trader_review_status="fresh")
        self.assertFalse(decision["may_publish"])
        self.assertIn("news", decision["catastrophic_families"])

    def test_publication_gate_rejects_stale_visible_html(self) -> None:
        tmp = tempfile.mkdtemp(prefix="mw-news-gate-")
        self.addCleanup(shutil.rmtree, tmp)
        site = Path(tmp) / "_site"
        site.mkdir()
        (site / "index.html").write_text(SEP18_HTML, encoding="utf-8")
        store = OvernightStore(root=ROOT, state_root=Path(tmp))
        run_dir = store.run_dir("overnight-20260922")
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ROOT / "data" / "overnight" / "runs" / "overnight-20260922" / "assembled_dataset.json",
            run_dir / "assembled_dataset.json",
        )
        with self.assertRaises(PublicationError):
            publication_gate(store, run_id="overnight-20260922", require_dataset=True, site_dir=site)


class ScheduledOutputNewsOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.run_id = "overnight-20260922-news-overlay"
        self.when = datetime.fromisoformat("2026-09-22T06:55:00-04:00")
        self._artifact_backup = None
        if ACCEPTED_ARTIFACT.is_file():
            self._artifact_backup = ACCEPTED_ARTIFACT.read_text(encoding="utf-8")
            ACCEPTED_ARTIFACT.unlink()
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=self.run_id,
                when=self.when,
                dry_run=True,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
            )
        self.store = OvernightStore(root=ROOT, state_root=self.state_root)
        self.base = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.assertEqual(self.base["families"]["news"]["as_of"], "2026-09-18T04:00:00")
        self.payload = self._payload()

    def tearDown(self) -> None:
        if self._artifact_backup is not None:
            ACCEPTED_ARTIFACT.write_text(self._artifact_backup, encoding="utf-8")
        elif not ACCEPTED_ARTIFACT.is_file():
            # Another test class may need the committed canonical artifact.
            from scripts.overnight.accepted_news import build_accepted_public_news, write_accepted_public_news
            import json

            ds = json.loads(
                (ROOT / "data/overnight/runs/overnight-20260922/assembled_dataset.json").read_text(encoding="utf-8")
            )
            research = ds["agent_research"]
            write_accepted_public_news(
                ROOT,
                build_accepted_public_news(
                    overnight_run_id=ds["overnight_run_id"],
                    as_of=ds["agent_research_cutoff"],
                    summary=research.get("summary"),
                    news=research.get("news") or [],
                    central_bank_research=research.get("central_bank_research") or [],
                    source="seed-from-overnight-20260922-assembled",
                ),
            )
        self.tmp.cleanup()

    def _payload_for(self, base: dict, run_id: str) -> dict:
        final_cutoff = isoformat(parse_iso(base["as_of"]) + timedelta(minutes=10))
        packet = {
            "schema_version": 1,
            "type": AGENT_PACKET_TYPE,
            "overnight_run_id": run_id,
            "review_id": base["review_id"],
            "base_packet_sha256": base["packet_sha256"],
            "base_evidence_cutoff": base["as_of"],
            "evidence_cutoff": final_cutoff,
            "competition": base["competition"],
            "research_supplement": {
                "summary": "Energy rebounded while U.S. activity data stayed mixed.",
                "news": [FRESH_NEWS_ITEM, ACTIVITY_ITEM],
                "central_bank_research": [],
                "sources": [],
            },
        }
        packet["packet_sha256"] = sha256_json(packet)
        memo = _spot_memo()
        decisions = {
            seat: {
                "seat": seat,
                "overnight_run_id": run_id,
                "packet_sha256": packet["packet_sha256"],
                "evidence_cutoff": packet["evidence_cutoff"],
                "conviction": 25,
                "thesis": "No incremental edge.",
                "invalidation": None,
                "required_pitch": None,
                "risk_put_on": None,
                "expression_memo": memo,
                "actions": [{"action": "HOLD", "expression_memo": memo}],
                "alerts": [],
                **({"funding_view": _skeptic_funding_view()} if seat == "no-trade-skeptic" else {}),
            }
            for seat in STANDING_SEATS
        }
        decisions["dollar-king"] = {
            **decisions["dollar-king"],
            "thesis": "USD expression with fresh accepted news.",
            "memory_context_sha256": base["seat_memory"]["hashes"]["dollar-king"],
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": memo,
            }],
        }
        pm = {
            pm_id: {
                "pm_id": pm_id,
                "overnight_run_id": run_id,
                "packet_sha256": packet["packet_sha256"],
                "evidence_cutoff": packet["evidence_cutoff"],
                "principal_model": "grok-4.6",
                "subagent_count": 0,
                "subagent_models": [],
                "actions": [{"action": "HOLD"}],
                "thesis": "Await cleaner setup.",
                "invalidation": None,
                "conviction": 20,
            }
            for pm_id in ("swinger", "pragmatist", "grinder")
        }
        pm["pragmatist"]["portfolio_construction"] = synthetic_portfolio_construction(
            opportunities=[{"instrument": "USDCAD", "rationale": "markable", "markable": True}],
            existing_book="Flat.",
            rationale="Evaluated handoff.",
        )
        pm["grinder"]["deployment_hurdle"] = synthetic_grinder_hurdle()
        return {
            "schema_version": 1,
            "type": "OVERNIGHT_SCHEDULED_OUTPUT",
            "schedule_id": SCHEDULE_ID,
            "overnight_run_id": run_id,
            "review_id": base["review_id"],
            "base_packet_sha256": base["packet_sha256"],
            "agent_packet": packet,
            "decisions": decisions,
            "pm_decisions": pm,
            "execution": {
                "parent_model": "grok-4.6",
                "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
                "total_model_cap": 20,
                "grok_cap": 18,
                "composer_cap": 2,
                "declared_total_model_calls": 19,
                "declared_grok_calls": 18,
                "declared_composer_calls": 1,
                "other_models_calls": 0,
                "auto_used": False,
            },
        }

    def _payload(self) -> dict:
        return self._payload_for(self.base, self.run_id)

    def test_open_not_blocked_by_stale_freeze_news_after_overlay(self) -> None:
        review = simulate_output(self.store, self.payload)
        seat = review["books"]["seats"]["dollar-king"]
        self.assertEqual(len(seat["positions"]), 1)
        self.assertNotEqual(seat["history"][-1]["result"], "blocked_freshness")

    def test_stale_market_state_still_blocks_open(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        state_root = Path(tmp.name)
        run_id = "overnight-20260922-news-overlay-stale-ms"
        artifact_backup = None
        if ACCEPTED_ARTIFACT.is_file():
            artifact_backup = ACCEPTED_ARTIFACT.read_text(encoding="utf-8")
            ACCEPTED_ARTIFACT.unlink()
        stale_ms = state_root / "stale_market_state.json"
        stale_ms.write_text(
            json.dumps(
                {
                    "status": "stale",
                    "generated_at": "2026-09-10T00:07:00-04:00",
                    "fx": {"USDCAD": {"spot": 1.36}},
                }
            ),
            encoding="utf-8",
        )
        try:
            for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
                run_stage(
                    stage,
                    root=ROOT,
                    state_root=state_root,
                    run_id=run_id,
                    when=self.when,
                    dry_run=True,
                    market_state_path=stale_ms,
                )
            store = OvernightStore(root=ROOT, state_root=state_root)
            base = store.read_artifact(run_id, "evidence_snapshot.json")
            self.assertEqual(base["families"]["market_state"]["status"], "stale")
            payload = self._payload_for(base, run_id)
            review = simulate_output(store, payload)
            seat = review["books"]["seats"]["dollar-king"]
            self.assertEqual(seat["positions"], [])
            self.assertEqual(seat["history"][-1]["result"], "blocked_freshness")
        finally:
            if artifact_backup is not None:
                ACCEPTED_ARTIFACT.write_text(artifact_backup, encoding="utf-8")
            tmp.cleanup()

if __name__ == "__main__":
    unittest.main()
