"""Operational smoke gate for the Chart Guy paper seat.

The historical 75% / three-trade blind exam is archival scoring only. This
gate checks routing, one no-trade, one in-memory close-only paper trade,
15-seat budgets on a registry copy, and the frozen 14-seat replay. It does
not start Market Watch and it does not write the canonical books.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.fx_technical.indicators import pair_indicators
from scripts.fx_technical.learning_ext import classify_signal_vs_execution, normalize_technical_setup
from scripts.fx_technical.packet import ensure_fx_technical
from scripts.fx_technical.research import build_technical_research
from scripts.overnight.books import empty_seat, realized_increment
from scripts.overnight.constants import ROOT, STARTING_NAV_USD
from scripts.rates.valuation import value_position
from scripts.trader_room.agent_config import (
    agent_for_role,
    build_pin,
    load_config,
)
from scripts.trading.learning import empty_scope, normalize_scope

ACTIVATION_DATE = "2026-11-07"
NY = ZoneInfo("America/New_York")


def _fail(failures: list[str], code: str) -> None:
    failures.append(code)


def _frontmatter_model(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    for line in text[4:end].splitlines():
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip()
    return None


def _series(start: date, n: int, *, last: float | None = None) -> dict[date, float]:
    out: dict[date, float] = {}
    for i in range(n):
        out[start + timedelta(days=i)] = round(1.10 + i * 0.001, 6)
    if last is not None and out:
        out[max(out)] = last
    return out


def _check_routing(root: Path, failures: list[str]) -> dict[str, Any]:
    agent = (root / ".cursor" / "agents" / "chart-guy.md").read_text(encoding="utf-8")
    command = (root / ".cursor" / "commands" / "trader-room.md").read_text(encoding="utf-8")
    model = _frontmatter_model(agent)
    if model != "grok-4.7[]":
        _fail(failures, "routing_model")
    required = (
        "technical-only close-based G10 spot FX",
        "Explicit no-trade is a complete decision",
        "Do not use candlestick patterns, ATR, or invented OHLC",
        "composer-2.5",
        "5-session and 20-session",
        "# Chart Guy Playbook",
    )
    if any(snippet not in agent for snippet in required):
        _fail(failures, "routing_instruction")
    if "express macro views through USD" in agent.lower():
        _fail(failures, "routing_macro_override")
    if "technical-only close-based G10 spot" not in command:
        _fail(failures, "routing_command_spot")
    if "except `no-trade-skeptic` and `chart-guy`" not in command:
        _fail(failures, "routing_command_no_trade")
    if "total Grok ceiling 31" not in command or "total model ceiling 61" not in command:
        _fail(failures, "routing_command_budget")
    cfg = load_config(honor_env=False)
    raw = json.loads((root / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8"))
    for item in raw["roster"]["traders"]:
        if item["id"] == "chart-guy":
            item["status"] = "active"
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    path = Path(handle.name)
    json.dump(raw, handle)
    handle.close()
    try:
        active_cfg = load_config(path, honor_env=False)
        pin = build_pin("daily", config=active_cfg, as_of=ACTIVATION_DATE)
        roles = pin["roles"]
        if agent_for_role(roles, "trader", "chart-guy") != "chart-guy":
            _fail(failures, "routing_daily_agent")
        if agent_for_role(roles, "advocate", "chart-guy") != "chart-guy":
            _fail(failures, "routing_advocate_agent")
        if roles["trader"] != "grok-4.7" or roles["advocate"] != "grok-4.7":
            _fail(failures, "routing_pin_model")
        if roles["advocate_subagent"] != "composer-2.5":
            _fail(failures, "routing_subagent_model")
    finally:
        path.unlink(missing_ok=True)
    row = next(item for item in cfg["roster"]["traders"] if item["id"] == "chart-guy")
    if row["expression_specialty"] != "spot_only" or not row["may_no_trade"]:
        _fail(failures, "routing_registry_remit")
    if row["activation_date"] != ACTIVATION_DATE:
        _fail(failures, "routing_activation_date")
    if row["status"] != "active":
        _fail(failures, "routing_registry_status")
    return {"model": model, "registry_status": row["status"]}


def _check_no_trade(failures: list[str]) -> dict[str, Any]:
    setup = normalize_technical_setup(
        {
            "setup_class": "no_trade",
            "instrument": "EURUSD",
            "indicators": ["macd_histogram"],
            "regime_conflict": "trend_up_macd_negative",
            "entry": None,
            "invalidation": None,
            "target": None,
            "expected_horizon": None,
            "actual_mark": None,
            "outcome": "no_trade",
            "as_of": ACTIVATION_DATE,
        }
    )
    if setup is None or setup["outcome"] != "no_trade" or setup["entry"] is not None:
        _fail(failures, "no_trade_normalize")
        return {}
    kind = classify_signal_vs_execution(
        direction=None,
        entry=None,
        invalidation=None,
        actual_mark=None,
        outcome="no_trade",
    )
    if kind != "not_yet_observed":
        _fail(failures, "no_trade_classify")
    scope = normalize_scope({**empty_scope(), "technical_setup": setup})
    if scope.get("technical_setup", {}).get("setup_class") != "no_trade":
        _fail(failures, "no_trade_learning_scope")
    return {"outcome": "no_trade", "signal_vs_execution": kind}


def _check_paper_trade(failures: list[str]) -> dict[str, Any]:
    entry = 1.10
    invalidation = 1.094
    target = 1.112
    mark = 1.111
    notional = 1_000_000.0
    position = {
        "position_id": "pos-smoke-eurusd",
        "asset_class": "spot_fx",
        "side": "long",
        "entry_price": entry,
        "mark_price": mark,
        "notional_usd": notional,
        "instrument": "EURUSD",
    }
    if any(key in position for key in ("open", "high", "low", "atr", "fill_intraday")):
        _fail(failures, "paper_ohlc_fields")
    valued = value_position(position)
    expected = round((mark - entry) / entry * notional, 2)
    if valued.get("pnl_unavailable") or valued.get("unrealized_pnl_usd") != expected:
        _fail(failures, "paper_mark_pnl")
    flat = dict(position)
    flat["mark_price"] = entry
    if value_position(flat).get("unrealized_pnl_usd") != 0.0:
        _fail(failures, "paper_flat_pnl")
    realized = realized_increment(position, exit_price=mark, closed_notional=notional)
    if round(realized, 2) != expected:
        _fail(failures, "paper_realized_pnl")
    seat = empty_seat(
        "chart-guy",
        remit_text="close-only G10 spot FX technical structure",
        expression_specialty="spot_only",
    )
    if seat["nav_usd"] != STARTING_NAV_USD or seat["positions"] or seat["expression_rule"] != "spot_only":
        _fail(failures, "paper_cold_seat")
    setup = normalize_technical_setup(
        {
            "setup_class": "trend_continuation",
            "instrument": "EURUSD",
            "indicators": ["sma_20", "sma_50"],
            "entry": entry,
            "invalidation": invalidation,
            "target": target,
            "expected_horizon": "5D",
            "actual_mark": 1.09,
            "outcome": "invalidation",
            "as_of": ACTIVATION_DATE,
        }
    )
    kind = classify_signal_vs_execution(
        direction="long_base",
        entry=entry,
        invalidation=invalidation,
        actual_mark=1.09,
        outcome="invalidation",
    )
    if kind != "weak_signal":
        _fail(failures, "paper_invalidation_is_close")
    if setup is None or setup["expected_horizon"] != "5D" or setup["actual_mark"] != 1.09:
        _fail(failures, "paper_learning_mark")
    held = classify_signal_vs_execution(
        direction="long_base",
        entry=entry,
        invalidation=invalidation,
        actual_mark=mark,
        outcome="target",
    )
    if held != "not_yet_observed":
        _fail(failures, "paper_target_not_intraday")
    return {
        "entry": entry,
        "mark": mark,
        "unrealized_pnl_usd": valued.get("unrealized_pnl_usd"),
        "realized_pnl_usd": round(realized, 2),
        "invalidation_class": kind,
        "nav_usd": seat["nav_usd"],
    }


def _check_no_lookahead(failures: list[str]) -> dict[str, Any]:
    start = date(2024, 1, 2)
    known = _series(start, 40)
    as_of = start + timedelta(days=30)
    future = start + timedelta(days=39)
    leaked = dict(known)
    leaked[future] = 9.5
    before = pair_indicators(known, as_of=as_of, clock=as_of, pair="EURUSD")
    after = pair_indicators(leaked, as_of=as_of, clock=as_of, pair="EURUSD")
    if before["close"] != after["close"] or before["sma_20"] != after["sma_20"]:
        _fail(failures, "lookahead_close")
    if before["observation_date"] > as_of.isoformat():
        _fail(failures, "lookahead_observation")
    stale = pair_indicators(known, as_of=as_of, clock=as_of + timedelta(days=10), pair="EURUSD")
    dead = pair_indicators(known, as_of=as_of, clock=as_of + timedelta(days=22), pair="EURUSD")
    if stale["status"] != "stale" or stale["close"] is None:
        _fail(failures, "stale_close_retained")
    if dead["status"] != "unavailable" or dead["close"] is not None:
        _fail(failures, "unavailable_close_invented")
    research = build_technical_research({"EURUSD": known}, as_of=as_of, clock=as_of)
    if research.get("vetoes_unrelated_trades") is not False:
        _fail(failures, "research_veto")
    if research.get("trade_recommendation") is not None:
        _fail(failures, "research_recommendation")
    for setup in research.get("setups") or []:
        if setup.get("trade_recommendation") is not None:
            _fail(failures, "setup_recommendation")
        if setup.get("as_of") and setup["as_of"] > as_of.isoformat():
            _fail(failures, "setup_lookahead")
    excluded = set((research.get("method") or {}).get("excluded") or [])
    if not {"ohlc", "atr", "candlestick", "intraday"} <= excluded:
        _fail(failures, "research_excludes_ohlc")
    packet = {"market_state": {"fx_technical": research}}
    ensure_fx_technical(packet)
    shared = packet["fx_technical"]
    if shared.get("type") != "FX_TECHNICAL_RESEARCH" or shared.get("vetoes_unrelated_trades") is not False:
        _fail(failures, "evidence_parity")
    if shared is research:
        _fail(failures, "evidence_not_copied")
    return {
        "observation_date": before["observation_date"],
        "stale_status": stale["status"],
        "unavailable_status": dead["status"],
        "pair_count": research.get("pair_count"),
    }


def _check_budgets(root: Path, failures: list[str]) -> dict[str, Any]:
    raw = json.loads((root / "scripts" / "trader_room" / "model_registry.json").read_text(encoding="utf-8"))
    for item in raw["roster"]["traders"]:
        if item["id"] == "chart-guy":
            item["status"] = "active"
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    path = Path(handle.name)
    json.dump(raw, handle)
    handle.close()
    try:
        cfg = load_config(path, honor_env=False)
        before = build_pin("daily", config=cfg, as_of="2026-11-06")
        on_day = build_pin("daily", config=cfg, as_of=ACTIVATION_DATE)
        before_od = build_pin("ondemand", config=cfg, as_of="2026-11-06")
        on_od = build_pin("ondemand", config=cfg, as_of=ACTIVATION_DATE)
    finally:
        path.unlink(missing_ok=True)
    if len(before["traders"]) != 14 or "chart-guy" in {row["id"] for row in before["traders"]}:
        _fail(failures, "budget_before_activation_date")
    daily_before = (
        before["budget"]["total_calls"],
        before["budget"]["grok_family_calls"],
        before["budget"]["composer_calls"],
    )
    if daily_before != (20, 18, 2):
        _fail(failures, "budget_14_daily")
    od_before = (
        before_od["budget"]["total_calls"],
        before_od["budget"]["grok_family_calls"],
        before_od["budget"]["composer_calls"],
    )
    if od_before != (57, 29, 28):
        _fail(failures, "budget_14_ondemand")
    ids = [row["id"] for row in on_day["traders"]]
    if ids.count("chart-guy") != 1 or len(ids) != 15:
        _fail(failures, "budget_15_roster")
    daily = (
        on_day["budget"]["total_calls"],
        on_day["budget"]["grok_family_calls"],
        on_day["budget"]["composer_calls"],
    )
    if daily != (21, 19, 2):
        _fail(failures, "budget_15_daily")
    ondemand = (
        on_od["budget"]["total_calls"],
        on_od["budget"]["grok_family_calls"],
        on_od["budget"]["composer_calls"],
    )
    if ondemand != (61, 31, 30):
        _fail(failures, "budget_15_ondemand")
    legacy = build_pin("daily", config=load_config(honor_env=False), as_of="2026-09-18")
    if "chart-guy" in {row["id"] for row in legacy["traders"]} or len(legacy["traders"]) != 14:
        _fail(failures, "budget_historical_day")
    return {"daily_15": daily, "ondemand_15": ondemand, "daily_14": daily_before}


def _check_historical_replay(root: Path, failures: list[str]) -> dict[str, Any]:
    rel = "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json"
    path = root / rel
    text = path.read_text(encoding="utf-8")
    snap = json.loads(text)
    pin = snap["agent_roster_pin"]
    ids = [row["id"] for row in pin["traders"]]
    if len(ids) != 14 or "chart-guy" in ids:
        _fail(failures, "replay_14_seats")
    budget = pin["budget"]
    if (budget["total_calls"], budget["grok_family_calls"], budget["composer_calls"]) != (20, 18, 2):
        _fail(failures, "replay_14_budget")
    if "fx_technical" in snap:
        _fail(failures, "replay_snapshot_rewritten")
    exam_path = root / "data" / "fx_technical" / "qualification_result.json"
    exam = json.loads(exam_path.read_text(encoding="utf-8"))
    rehearsal = exam.get("rehearsal") or {}
    summary = rehearsal.get("summary") or {}
    if exam.get("gate") == "pass" or rehearsal.get("qualifies_production_seat") is not False:
        _fail(failures, "historical_exam_misrepresented")
    if exam.get("production_exam", {}).get("ran") is not False:
        _fail(failures, "historical_exam_marked_run")
    if summary.get("gate") != "fail" or summary.get("passed_trade_ids") != ["USDNOK-2019-11-27"]:
        _fail(failures, "historical_exam_score_changed")
    if summary.get("pass_rate") != 1.0 or summary.get("passed") != 8:
        _fail(failures, "historical_exam_score_changed")
    return {
        "snapshot_traders": len(ids),
        "historical_exam_gate": summary.get("gate"),
        "historical_exam_is_activation_gate": False,
    }


def run_smoke_gate(root: Path | None = None) -> dict[str, Any]:
    repo = Path(root or ROOT)
    failures: list[str] = []
    checks = {
        "routing": _check_routing(repo, failures),
        "no_trade": _check_no_trade(failures),
        "paper_trade": _check_paper_trade(failures),
        "no_lookahead": _check_no_lookahead(failures),
        "budgets": _check_budgets(repo, failures),
        "historical_replay": _check_historical_replay(repo, failures),
    }
    return {
        "schema_version": 1,
        "type": "CHART_GUY_OPERATIONAL_SMOKE",
        "generated_at": datetime.now(NY).isoformat(),
        "gate": "pass" if not failures else "fail",
        "historical_blind_exam_is_activation_gate": False,
        "failures": failures,
        "checks": checks,
    }
