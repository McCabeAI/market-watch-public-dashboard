#!/usr/bin/env python3
"""Growth-shock decision source map extraction (standard library only)."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[5]
SOURCE_DIR = Path(__file__).resolve().parent
OUT_JSON = SOURCE_DIR / "source_map.json"
OUT_MD = SOURCE_DIR / "source_map.md"

INPUT_COMMIT = "680297f3898081789794d20b765a5c908b6b93fe"
BOOK_COMMIT_BLOB_EXPECTED = "3bb1cfa3ae7259b263f094f9cd072ef316b95fff"
HEAD_BOOK_BLOB_EXPECTED = "f52d0682ceb06f253c2a80216e97bfd42b0c28d8"

EXPECTED_SNAPSHOT_BLOB = "d875ddc64fab7258cbcf72c6b4a7df0a4ec64d33"
EXPECTED_PACKET_SHA256_SNAPSHOT = "57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8"
EXPECTED_RAW_SNAPSHOT_SHA256 = "e7fc28a6109a744129133d55e3a789ce950d4373d01f6c12aef30660a5d08931"
EXPECTED_AGENT_PACKET_SHA256 = "2e2b6a923502895d6478c0d4c3ca5aea94fb9ca9e46b5ca07b540a615e8f879c"
EXPECTED_AGENT_BASE_PACKET_SHA256 = "57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8"
EXPECTED_AGENT_FILE_SHA256 = "4b0af5690bd5f09c12335abeb6e25487fabaf7602673c31b6d5b0fae56b6a9cc"
EXPECTED_AGENT_BLOB = "72ded24c2ae62faabe3d8ae864c49297ec8728fc"
EXPECTED_SCHEDULED_BLOB = "6bec37cfa0e24e4e638d58a1b7aaf779d76339f8"
EXPECTED_RESEARCH_SHA256 = "2379d1a520b69dc85bfc2a017073b5aa5ae286dd6d507c87e45502503803c627"
MISSING_COMMIT = "f0cadc27229365e20ad9484fbb1eb8409de794d3"

SNAPSHOT_PATH = REPO_ROOT / (
    "data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json"
)
SCHEDULED_REVIEW_PATH = REPO_ROOT / (
    "data/overnight/runs/overnight-20261106/reviews/review-001/scheduled_output.json"
)
SCHEDULED_INBOX_PATH = REPO_ROOT / (
    "data/overnight/inbox/overnight-20261106/scheduled_output.json"
)
AGENT_PACKET_PATH = REPO_ROOT / (
    "data/overnight/runs/overnight-20261106/reviews/review-001/agent_evidence_packet.json"
)
LESSONS_PATH = REPO_ROOT / "data/trading/pm/chatgpt/lessons.json"
RESEARCH_INDEX_PATH = REPO_ROOT / "data/trading/pm/chatgpt/research/index.json"
EDGE_PROFILE_PATH = REPO_ROOT / "data/trading/pm/chatgpt/research/edge/profile.json"
HYPOTHESES_DIR = REPO_ROOT / "data/trading/pm/chatgpt/research/hypotheses"

SERIES_IDS = [
    "EURUSD", "AUDJPY", "AUDNZD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "GBPUSD",
    "NASDAQ", "DOW", "SP500", "VIX", "WTI", "BRENT", "GOLD", "HY_OAS", "US_BE10",
    "US_REAL10", "BROAD_USD", "COPPER", "RUSSELL",
    "US_2Y", "US_5Y", "US_10Y", "US_30Y", "US_2s10s",
    "CA_2Y", "CA_5Y", "CA_10Y", "CA_2s10s",
    "AU_2Y", "AU_5Y", "AU_10Y", "AU_2s10s",
    "JP_2Y", "JP_5Y", "JP_10Y",
    "EA_2Y", "EA_5Y", "EA_10Y",
    "CA-US_2Y", "CA-US_10Y", "AU-US_2Y", "AU-US_10Y",
    "NZ-US_2Y", "NZ-US_5Y", "NZ-US_10Y",
    "AU-NZ_2Y", "AU-NZ_5Y", "AU-NZ_10Y",
]

FX_PAIR_IDS = [
    "EURUSD", "AUDJPY", "AUDNZD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "GBPUSD",
    "EURAUD", "AUDCAD", "NZDJPY",
]

CROSS_ASSET_IDS = [
    "BRENT", "WTI", "NASDAQ", "DOW", "SP500", "VIX", "GOLD", "HY_OAS", "US_BE10",
    "US_REAL10", "BROAD_USD", "COPPER", "RUSSELL",
]

TEMP_COUNTRIES = ("US", "CA", "AU", "JP", "NZ", "EA")
TEMP_DIMS = ("Labor", "Inflation", "Activity")

LEAD_SEATS = (
    "mean-reverter", "positioning-cynic", "value-guy", "trend-follower",
    "rate-hawk", "pragmatist",
)

CHATGPT_POSITION_IDS = ("pm-chatgpt-595561a1b90f", "pm-chatgpt-aef5bacd43d3")

BOOK_PM_FIELDS = (
    "evidence_cutoff",
    "funding_cost_usd",
    "funding_percent_rate",
    "funding_convention",
    "funding_day_count",
    "funded_draw_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "total_pnl_usd",
    "last_action",
    "gross_utilization_usd",
)


def run_git(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def agree_rel(stored: Optional[float], recomputed: Optional[float]) -> Optional[bool]:
    if stored is None or recomputed is None:
        return None
    if stored == 0 and recomputed == 0:
        return True
    tol_abs = 1e-4
    tol_rel = 1e-6
    diff = abs(stored - recomputed)
    if diff <= tol_abs:
        return True
    denom = max(abs(stored), abs(recomputed), 1e-300)
    return diff / denom <= tol_rel


def recompute_1d(
    history: Optional[List], moves_1d: Optional[Dict[str, Any]]
) -> Tuple[Optional[float], str]:
    if not history or len(history) < 2:
        return None, "insufficient_history"
    prev_v = history[-2][1]
    last_v = history[-1][1]
    unit = (moves_1d or {}).get("unit") or ""
    ulow = str(unit).lower()
    if "log" in ulow:
        if prev_v is None or last_v is None or prev_v <= 0 or last_v <= 0:
            return None, "log_requires_positive"
        return 100.0 * math.log(last_v / prev_v), "100*ln(last/prev)_when_positive"
    if "bp" in ulow:
        return float(last_v) - float(prev_v), "last_minus_prev_bp"
    return float(last_v) - float(prev_v), "last_minus_prev_default"


def extract_series_record(
    sid: str, series_obj: Optional[Dict[str, Any]], json_path: str
) -> Dict[str, Any]:
    if series_obj is None:
        return {
            "json_path": json_path,
            "id": sid,
            "missing_in_snapshot": True,
        }
    hist = series_obj.get("history")
    hist_list = hist if isinstance(hist, list) else None
    hist_len = len(hist_list) if hist_list is not None else 0
    n_top = series_obj.get("n")
    moves = series_obj.get("moves") or {}
    m1 = moves.get("1D") if isinstance(moves, dict) else None
    n_move = m1.get("n") if isinstance(m1, dict) else None
    n_disagree = None
    if n_top is not None and hist_len:
        n_disagree = n_top != hist_len
    if m1 and isinstance(m1, dict) and m1.get("n") is not None and hist_len:
        if m1.get("n") != hist_len:
            n_disagree = True
    rec_val, rec_rule = recompute_1d(hist_list, m1 if isinstance(m1, dict) else None)
    stored_val = m1.get("value") if isinstance(m1, dict) else None
    first_dt = last_dt = first_v = last_v = None
    if hist_list:
        first_dt, first_v = hist_list[0][0], hist_list[0][1]
        last_dt, last_v = hist_list[-1][0], hist_list[-1][1]
    pct = series_obj.get("percentile")
    z_scr = series_obj.get("z")
    screen_fields: Dict[str, Any] = {}
    if pct is not None:
        screen_fields["percentile"] = {
            "value": pct,
            "label": "screen_not_recomputed_from_126d_history",
        }
    if z_scr is not None:
        screen_fields["z"] = {
            "value": z_scr,
            "label": "screen_not_recomputed_from_126d_history",
        }
    out: Dict[str, Any] = {
        "json_path": json_path,
        "id": sid,
        "unit": series_obj.get("unit"),
        "as_of": series_obj.get("as_of"),
        "value": series_obj.get("value"),
        "len_history": hist_len,
        "first_date": first_dt,
        "last_date": last_dt,
        "first_value": first_v,
        "last_value": last_v,
        "n_field": n_top,
        "n_or_moves_1d_n_disagrees_with_len_history": n_disagree,
        "stored_moves_1d": m1,
        "recomputed_1d": rec_val,
        "recompute_rule": rec_rule,
        "agrees_stored_moves_1d_value_within_tolerance": agree_rel(
            float(stored_val) if stored_val is not None else None, rec_val
        ),
        "note": series_obj.get("note"),
        "history": hist_list,
    }
    if screen_fields:
        out["screen_fields"] = screen_fields
    return out


def strip_policy_meeting_prices(obj: Dict[str, Any]) -> Dict[str, Any]:
    banks_out: Dict[str, Any] = {}
    banks = obj.get("banks") or {}
    for bkey, bval in banks.items():
        if not isinstance(bval, dict):
            banks_out[bkey] = bval
            continue
        bank_row: Dict[str, Any] = {
            k: v for k, v in bval.items()
            if k not in ("anchor", "fixing", "basis_bp")
        }
        mts = bval.get("meetings")
        if isinstance(mts, list):
            clean_meetings = []
            for m in mts:
                if not isinstance(m, dict):
                    continue
                clean_meetings.append({
                    "bank": m.get("bank"),
                    "decision_date": m.get("decision_date"),
                    "effective_date": m.get("effective_date"),
                    "instrument_id": m.get("instrument_id"),
                    "method": m.get("method"),
                })
            bank_row["meetings"] = clean_meetings
        banks_out[bkey] = bank_row
    outcomes = obj.get("outcomes")
    outcomes_meta: Dict[str, Any] = {"path": "families.market_state.data.policy_meeting_prices.outcomes"}
    if isinstance(outcomes, dict):
        outcomes_meta["date_keys"] = sorted(
            k for k in outcomes.keys() if k != "schema_version"
        )
        if "schema_version" in outcomes:
            outcomes_meta["schema_version"] = outcomes["schema_version"]
    return {
        "path": "families.market_state.data.policy_meeting_prices",
        "construction_version": obj.get("construction_version"),
        "as_of": obj.get("as_of"),
        "banks": banks_out,
        "outcomes": outcomes_meta,
    }


def quarantine_policy_paths_terminal(policy_paths: Dict[str, Any]) -> List[Dict[str, Any]]:
    quarantine: List[Dict[str, Any]] = []
    countries = (policy_paths.get("countries") or {})
    if not isinstance(countries, dict):
        return quarantine
    for ckey, cval in countries.items():
        if not isinstance(cval, dict):
            continue
        term = cval.get("terminal")
        if term is not None:
            quarantine.append({
                "path": f"families.market_state.data.policy_paths.countries.{ckey}.terminal",
                "reason": "derived spread / not a meeting quote for inference",
                "presence_only": True,
            })
        for subk, subv in cval.items():
            if not isinstance(subv, dict):
                continue
            if subv.get("change_from_overnight_bps") is not None:
                quarantine.append({
                    "path": (
                        f"families.market_state.data.policy_paths.countries.{ckey}.{subk}"
                        ".change_from_overnight_bps"
                    ),
                    "reason": "derived spread / not a meeting quote for inference",
                    "presence_only": True,
                })
    return quarantine


def contract_price_ok(price: Any, implied: Any) -> Optional[bool]:
    try:
        return abs(float(price) - (100.0 - float(implied))) <= 1e-6
    except (TypeError, ValueError):
        return None


def strip_sofr_history_urls(sofr_obj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(sofr_obj)
    hist = out.get("history")
    if isinstance(hist, list):
        out["history"] = [
            {k: v for k, v in h.items() if k != "source_url"}
            if isinstance(h, dict) else h
            for h in hist
        ]
    if "source_url" in out:
        del out["source_url"]
    return out


def field_diff(
    prior: Dict[str, Any], book: Dict[str, Any], prefix: str = ""
) -> List[Dict[str, Any]]:
    diffs: List[Dict[str, Any]] = []
    keys = set(prior.keys()) | set(book.keys())
    for k in sorted(keys):
        path = f"{prefix}.{k}" if prefix else k
        a, b = prior.get(k), book.get(k)
        if isinstance(a, dict) and isinstance(b, dict):
            diffs.extend(field_diff(a, b, path))
        elif a != b:
            diffs.append({
                "field": path,
                "snapshot_prior_pm_books_pms_chatgpt": a,
                "input_commit_latest_json_pms_chatgpt": b,
            })
    return diffs


def build_markdown(doc: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Source map index")
    lines.append("")
    cb = doc.get("clocks", {})
    lines.append("## Clocks")
    for k in sorted(cb.keys()):
        lines.append(f"- **{k}**: {cb[k]}")
    lines.append("")
    bd = doc.get("bindings", {})
    apf = bd.get("agent_packet_fields") or {}
    lines.append("## Bindings")
    lines.append(f"- snapshot_blob_head: `{bd.get('snapshot_blob_head')}`")
    lines.append(f"- snapshot_blob_at_input_commit: `{bd.get('snapshot_blob_at_input_commit')}`")
    lines.append(f"- embedded_packet_sha256_in_snapshot: `{bd.get('embedded_packet_sha256_in_snapshot')}`")
    lines.append(f"- raw_file_sha256_snapshot: `{bd.get('raw_file_sha256_snapshot')}`")
    lines.append(f"- agent_packet_packet_sha256: `{apf.get('packet_sha256')}`")
    lines.append(f"- agent_packet_base_packet_sha256: `{apf.get('base_packet_sha256')}`")
    lines.append(f"- agent_file_sha256: `{bd.get('agent_file_sha256')}`")
    lines.append(f"- agent_file_git_blob: `{bd.get('agent_file_git_blob')}`")
    lines.append(f"- scheduled_output_review_blob: `{bd.get('scheduled_output_review_blob')}`")
    lines.append(f"- scheduled_output_inbox_blob: `{bd.get('scheduled_output_inbox_blob')}`")
    lines.append(f"- inbox_blob_skipped_parse_matches_review: {bd.get('inbox_blob_skipped_parse_matches_review')}")
    lines.append(f"- research_index_research_sha256: `{bd.get('research_index_research_sha256')}`")
    lines.append(f"- book_blob_at_input_commit: `{bd.get('book_blob_at_input_commit')}`")
    lines.append(f"- head_book_blob_recorded_not_used: `{bd.get('head_book_blob_recorded_not_used')}`")
    lim = bd.get("limitations", [])
    if lim:
        lines.append("- limitations:")
        for x in lim:
            lines.append(f"  - {x}")
    lines.append("")
    series_list = doc.get("series", [])
    lines.append("## Opportunity series")
    disagree = 0
    for rec in series_list:
        if rec.get("n_or_moves_1d_n_disagrees_with_len_history"):
            disagree += 1
        sid = rec.get("id")
        lines.append(f"### {sid}")
        if rec.get("missing_in_snapshot"):
            lines.append("- (missing in snapshot)")
            lines.append("")
            continue
        lines.append(f"- as_of: {rec.get('as_of')}")
        lines.append(f"- unit: {rec.get('unit')}")
        lines.append(f"- n_history: {rec.get('len_history')} vs n_field: {rec.get('n_field')}")
        lines.append(f"- last_value: {rec.get('last_value')}")
        lines.append(f"- stored 1D move value: {(rec.get('stored_moves_1d') or {}).get('value')}")
        lines.append(f"- recomputed 1D: {rec.get('recomputed_1d')} ({rec.get('recompute_rule')})")
        agr = rec.get("agrees_stored_moves_1d_value_within_tolerance")
        lines.append(f"- agrees within tolerance: {agr}")
        lines.append("")
    lines.append(f"(history-length disagree count in series table: {disagree})")
    lines.append("")
    q = doc.get("quarantine", {})
    lines.append("## Quarantine")
    lines.append(q.get("statement", ""))
    pm = q.get("policy_meeting_prices_omitted_fields", [])
    if pm:
        lines.append(f"- policy_meeting_prices omitted/stripped: {', '.join(pm)}")
    lines.append("")
    cur = doc.get("tradable_curves", {})
    corra = cur.get("CORRA", {})
    lines.append("## CORRA implied rates (four-leg 2027 strip)")
    for c in corra.get("contracts_subset_2027_HMUZ", []):
        lines.append(f"- {c.get('code')} expiry={c.get('expiry')} implied_rate={c.get('implied_rate')}")
    lines.append("")
    leads = doc.get("scheduled_output_leads", {})
    lines.append("## Scheduled-output leads (submitted_action_not_a_fill)")
    for seat in LEAD_SEATS:
        block = leads.get(seat, {})
        acts = block.get("actions", [])
        lines.append(f"### {seat}")
        for a in acts:
            if not isinstance(a, dict):
                continue
            lines.append(
                f"- {a.get('action')} | {a.get('instrument')} | "
                f"notional_usd={a.get('notional_usd')}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    errors: List[str] = []

    snapshot_blob_head = run_git("rev-parse", f"HEAD:{SNAPSHOT_PATH.relative_to(REPO_ROOT).as_posix()}")
    snapshot_blob_pin = run_git(
        "rev-parse", f"{INPUT_COMMIT}:{SNAPSHOT_PATH.relative_to(REPO_ROOT).as_posix()}"
    )
    if snapshot_blob_head != EXPECTED_SNAPSHOT_BLOB:
        errors.append(f"snapshot_blob_head mismatch: got {snapshot_blob_head}")
    if snapshot_blob_pin != EXPECTED_SNAPSHOT_BLOB:
        errors.append(f"snapshot_blob_at_input_commit mismatch: got {snapshot_blob_pin}")

    raw_sha = file_sha256(SNAPSHOT_PATH)
    if raw_sha != EXPECTED_RAW_SNAPSHOT_SHA256:
        errors.append(f"raw snapshot sha256 mismatch: got {raw_sha}")

    snap = load_json(SNAPSHOT_PATH)
    if snap.get("packet_sha256") != EXPECTED_PACKET_SHA256_SNAPSHOT:
        errors.append(
            f"embedded snapshot packet_sha256 mismatch: got {snap.get('packet_sha256')}"
        )

    # Agent packet top fields only (already limited read)
    with AGENT_PACKET_PATH.open("r", encoding="utf-8") as f:
        agent_top = json.load(f)
    ap_fields = {
        "packet_sha256": agent_top.get("packet_sha256"),
        "base_packet_sha256": agent_top.get("base_packet_sha256"),
        "evidence_cutoff": agent_top.get("evidence_cutoff"),
        "base_evidence_cutoff": agent_top.get("base_evidence_cutoff"),
    }
    if ap_fields["packet_sha256"] != EXPECTED_AGENT_PACKET_SHA256:
        errors.append(f"agent packet_sha256 mismatch: got {ap_fields['packet_sha256']}")
    if ap_fields["base_packet_sha256"] != EXPECTED_AGENT_BASE_PACKET_SHA256:
        errors.append(
            f"agent base_packet_sha256 mismatch: got {ap_fields['base_packet_sha256']}"
        )

    agent_sha = file_sha256(AGENT_PACKET_PATH)
    if agent_sha != EXPECTED_AGENT_FILE_SHA256:
        errors.append(f"agent file sha256 mismatch: got {agent_sha}")
    agent_blob = run_git(
        "rev-parse",
        f"HEAD:{AGENT_PACKET_PATH.relative_to(REPO_ROOT).as_posix()}",
    )
    if agent_blob != EXPECTED_AGENT_BLOB:
        errors.append(f"agent blob mismatch: got {agent_blob}")

    rev_blob = run_git(
        "rev-parse",
        f"HEAD:{SCHEDULED_REVIEW_PATH.relative_to(REPO_ROOT).as_posix()}",
    )
    inbox_blob = run_git(
        "rev-parse",
        f"HEAD:{SCHEDULED_INBOX_PATH.relative_to(REPO_ROOT).as_posix()}",
    )
    if rev_blob != EXPECTED_SCHEDULED_BLOB:
        errors.append(f"scheduled review blob mismatch: got {rev_blob}")
    if inbox_blob != EXPECTED_SCHEDULED_BLOB:
        errors.append(f"scheduled inbox blob mismatch: got {inbox_blob}")

    scheduled_full = load_json(SCHEDULED_REVIEW_PATH)
    base_sched = scheduled_full.get("base_packet_sha256")
    if base_sched != EXPECTED_AGENT_BASE_PACKET_SHA256:
        errors.append(f"scheduled_output base_packet_sha256 mismatch: got {base_sched}")

    idx = load_json(RESEARCH_INDEX_PATH)
    rs = idx.get("research_sha256")
    if rs != EXPECTED_RESEARCH_SHA256:
        errors.append(f"research_sha256 mismatch: got {rs}")

    book_blob_in = run_git("rev-parse", f"{INPUT_COMMIT}:data/pm/books/latest.json")
    head_book_blob = run_git("rev-parse", "HEAD:data/pm/books/latest.json")
    if book_blob_in != BOOK_COMMIT_BLOB_EXPECTED:
        errors.append(f"book blob at input commit mismatch: got {book_blob_in}")
    if head_book_blob != HEAD_BOOK_BLOB_EXPECTED:
        errors.append(f"HEAD book blob unexpected: got {head_book_blob}")

    missing_git = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-t", MISSING_COMMIT],
        capture_output=True,
        text=True,
    )
    limitations: List[str] = []
    if missing_git.returncode == 0:
        errors.append(f"commit {MISSING_COMMIT} unexpectedly exists")
    else:
        limitations.append(f"git cat-file -t {MISSING_COMMIT} fails ({missing_git.stderr.strip()})")

    market = snap["families"]["market_state"]
    ms_data = market["data"]
    opportunities = ms_data["opportunities"]
    series_by_id = {s["id"]: s for s in opportunities.get("series", []) if isinstance(s, dict)}

    series_out: List[Dict[str, Any]] = []
    hist_disagree_count = 0
    for sid in SERIES_IDS:
        so = series_by_id.get(sid)
        jp = f"families.market_state.data.opportunities.series[{sid}]"
        rec = extract_series_record(sid, so, jp)
        series_out.append(rec)
        if rec.get("n_or_moves_1d_n_disagrees_with_len_history"):
            hist_disagree_count += 1

    audnzd_rel = None
    for rel in opportunities.get("relationships", []):
        if isinstance(rel, dict) and rel.get("id") == "AUDNZD~AU-NZ_2Y":
            audnzd_rel = {
                "id": rel.get("id"),
                "status": rel.get("status"),
                "reason": rel.get("reason"),
                "history_length": len(rel["history"]) if isinstance(rel.get("history"), list) else None,
            }
            break

    fx_block = ms_data.get("fx") or {}
    fx_pairs = fx_block.get("pairs") or {}
    fx_screen: Dict[str, Any] = {}
    for pid in FX_PAIR_IDS:
        p = fx_pairs.get(pid)
        if not isinstance(p, dict):
            fx_screen[pid] = None
            continue
        fx_screen[pid] = {
            "label": "screen_fields",
            "spot": p.get("spot"),
            "as_of": p.get("as_of"),
            "ret_1d": p.get("ret_1d"),
            "ret_5d": p.get("ret_5d"),
            "ret_1m": p.get("ret_1m"),
            "pctile_1y": p.get("pctile_1y"),
            "pctile_5y": p.get("pctile_5y"),
            "z_1y": p.get("z_1y"),
            "z_5y": p.get("z_5y"),
            "rv_20d": p.get("rv_20d"),
            "rv_60d": p.get("rv_60d"),
            "note_126d_vs_5y": (
                "126-day history cannot recompute a five-year percentile (screen metadata)."
            ),
        }
    fx_meta = {
        "source_observation": fx_block.get("source_observation"),
        "as_of": fx_block.get("as_of"),
        "age_days": fx_block.get("age_days"),
    }

    ca = ms_data.get("cross_assets") or {}
    ca_series = ca.get("series") or {}
    cross_latest: Dict[str, Any] = {}
    for aid in CROSS_ASSET_IDS:
        ent = ca_series.get(aid)
        if not isinstance(ent, dict):
            cross_latest[aid] = None
            continue
        cross_latest[aid] = {
            "value": ent.get("value"),
            "unit": ent.get("unit"),
            "as_of": ent.get("as_of"),
            "note": "no observation time series array in cross_assets.series (metadata/level only)",
        }

    curves_root = ms_data.get("tradable_rate_curves") or {}
    curves = curves_root.get("curves") or {}
    corra = curves.get("CORRA") or {}
    sofr = curves.get("SOFR") or {}

    corra_contracts = []
    for c in corra.get("contracts") or []:
        if not isinstance(c, dict):
            continue
        corra_contracts.append({
            "code": c.get("code"),
            "expiry": c.get("expiry"),
            "price": c.get("price"),
            "implied_rate": c.get("implied_rate"),
            "as_of": c.get("as_of"),
            "observation_date": c.get("observation_date"),
            "source": c.get("source"),
            "price_equals_100_minus_implied_rate_ok": contract_price_ok(
                c.get("price"), c.get("implied_rate")
            ),
        })
    corra_2027 = [
        c for c in corra_contracts
        if c.get("expiry") in ("2027-03", "2027-06", "2027-09", "2027-12")
    ]

    sofr_benchmark = sofr.get("benchmark") or {}
    sofr_bench_hist = sofr_benchmark.get("history")
    sofr_bench_hist_len = len(sofr_bench_hist) if isinstance(sofr_bench_hist, list) else None
    sofr_first = sofr_bench_hist[0] if isinstance(sofr_bench_hist, list) and sofr_bench_hist else None
    sofr_last = sofr_bench_hist[-1] if isinstance(sofr_bench_hist, list) and sofr_bench_hist else None

    sofr_contracts_out = []
    for c in sofr.get("contracts") or []:
        if not isinstance(c, dict):
            continue
        row = {
            "code": c.get("code"),
            "expiry": c.get("expiry"),
            "price": c.get("price"),
            "implied_rate": c.get("implied_rate"),
            "as_of": c.get("as_of"),
            "observation_date": c.get("observation_date"),
            "source": c.get("source"),
            "price_equals_100_minus_implied_rate_ok": contract_price_ok(
                c.get("price"), c.get("implied_rate")
            ),
        }
        sofr_contracts_out.append(row)

    fc = snap.get("funding_context") or {}
    sofr_fc = fc.get("sofr")
    sofr_fc_out = None
    if isinstance(sofr_fc, dict):
        sofr_fc_out = {
            "label": "financing_fixing_distinct_from_SR3",
            "convention": sofr_fc.get("convention"),
            "day_count": sofr_fc.get("day_count"),
            "effective_date": sofr_fc.get("effective_date"),
            "observation_date": sofr_fc.get("observation_date"),
            "percent_rate": sofr_fc.get("percent_rate"),
            "rate": sofr_fc.get("rate"),
            "name": sofr_fc.get("name"),
            "source": sofr_fc.get("source"),
            "history_full": strip_sofr_history_urls({"history": sofr_fc.get("history")}).get(
                "history"
            ),
        }

    policy_mtg = strip_policy_meeting_prices(ms_data.get("policy_meeting_prices") or {})

    policy_paths = ms_data.get("policy_paths") or {}
    pp_quarantine = quarantine_policy_paths_terminal(policy_paths)

    us_paths = (policy_paths.get("countries") or {}).get("US") or {}
    sr1_raw = us_paths.get("contracts_1m") or []
    sr1_out = []
    for c in sr1_raw:
        if not isinstance(c, dict):
            continue
        sr1_out.append({
            "field_class": "one_month_futures_quote",
            "code": c.get("code"),
            "expiry": c.get("expiry"),
            "price": c.get("price"),
            "implied_rate": c.get("implied_rate"),
            "note": "Must not be converted into a meeting-step path.",
        })

    ca_country = (policy_paths.get("countries") or {}).get("CA") or {}
    contracts_3m_note = {
        "path": "families.market_state.data.policy_paths.countries.CA.contracts_3m",
        "note": (
            "Duplicates CORRA CRA curve; canonical full contract set is under "
            "tradable_rate_curves.curves.CORRA.contracts (not duplicated here)."
        ),
    }

    mh = snap["families"].get("macro_hard") or {}
    components_in = mh.get("components") or []
    macro_components: List[Dict[str, Any]] = []
    for comp in components_in:
        if not isinstance(comp, dict):
            continue
        sid = comp.get("series_id") or ""
        country = comp.get("country")
        is_ca = country == "CA"
        labor_inf = ("Labor" in sid) or ("Inflation" in sid)
        activity = "Activity" in sid
        if labor_inf or (is_ca and activity):
            macro_components.append({
                "series_id": comp.get("series_id"),
                "country": comp.get("country"),
                "observation_period": comp.get("observation_period"),
                "due_period": comp.get("due_period"),
                "status": comp.get("status"),
                "research_status": comp.get("research_status"),
                "role": comp.get("role"),
                "provenance": comp.get("provenance"),
            })

    ts_root = mh.get("temperature_scores") or {}
    ts_countries = ts_root.get("countries") or {}
    temperature_blocks: Dict[str, Any] = {
        "score_inputs_last_ingested_at": ts_root.get("score_inputs_last_ingested_at"),
        "score_inputs_latest_reference_period": ts_root.get("score_inputs_latest_reference_period"),
        "scoring_cutoff": ts_root.get("scoring_cutoff"),
        "as_of": ts_root.get("as_of"),
        "countries": {},
    }
    for c in TEMP_COUNTRIES:
        cd = ts_countries.get(c) or {}
        temperature_blocks["countries"][c] = {}
        for d in TEMP_DIMS:
            blk = cd.get(d)
            if not isinstance(blk, dict):
                temperature_blocks["countries"][c][d] = None
                continue
            cs = blk.get("component_state") or {}
            cs_light: Dict[str, Any] = {}
            for ck, cv in cs.items():
                if not isinstance(cv, dict):
                    cs_light[ck] = cv
                    continue
                cs_light[ck] = {
                    "transform_value": cv.get("transform_value"),
                    "impulse": cv.get("impulse"),
                    "level": cv.get("level"),
                    "observed": cv.get("observed"),
                    "retrieved_at": cv.get("retrieved_at"),
                    "release_date_status": cv.get("release_date_status"),
                }
            temperature_blocks["countries"][c][d] = {
                "label": "temperature_score_not_a_raw_print",
                "not_consensus": True,
                "level": blk.get("level"),
                "impulse": blk.get("impulse"),
                "direction": blk.get("direction"),
                "temperature_class": blk.get("temperature_class"),
                "as_of": blk.get("as_of"),
                "latest_reference_period": blk.get("latest_reference_period"),
                "coverage": blk.get("coverage"),
                "lineage": blk.get("lineage"),
                "component_state": cs_light,
            }

    news_root = snap["families"].get("news") or {}
    cbr = snap["families"].get("central_bank_research") or {}
    news_items_out: List[Dict[str, Any]] = []
    for it in news_root.get("items", [])[:5000]:
        if not isinstance(it, dict):
            continue
        news_items_out.append({
            "label": "do_not_fetch",
            "id": it.get("id"),
            "published_at": it.get("published_at"),
            "headline": it.get("headline"),
            "summary": it.get("summary"),
            "source_name": it.get("source_name"),
            "country_codes": it.get("country_codes"),
            "primary_category": it.get("primary_category"),
        })
    cbr_items_out: List[Dict[str, Any]] = []
    for it in cbr.get("items", [])[:100]:
        if not isinstance(it, dict):
            continue
        cbr_items_out.append({
            "label": "do_not_fetch",
            "id": it.get("id"),
            "published_at": it.get("published_at"),
            "headline": it.get("headline"),
            "summary": it.get("summary"),
            "source_name": it.get("source_name"),
            "country_codes": it.get("country_codes"),
            "primary_category": it.get("primary_category"),
        })

    book_json_str = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{INPUT_COMMIT}:data/pm/books/latest.json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    book_root = json.loads(book_json_str)
    book_chatgpt = book_root.get("pms", {}).get("chatgpt")
    if not isinstance(book_chatgpt, dict):
        errors.append("input-commit book missing pms.chatgpt")
        book_chatgpt = {}

    prior_chatgpt = (snap.get("prior_pm_books") or {}).get("pms", {}).get("chatgpt")
    if not isinstance(prior_chatgpt, dict):
        prior_chatgpt = {}

    def book_subset(pm: Dict[str, Any], book_root: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: pm.get(k) for k in BOOK_PM_FIELDS}
        row["as_of"] = pm.get("as_of") or book_root.get("as_of")
        row["overnight_run_id"] = pm.get("overnight_run_id") or book_root.get("overnight_run_id")
        pos = []
        for p in pm.get("positions") or []:
            if isinstance(p, dict) and p.get("position_id") in CHATGPT_POSITION_IDS:
                pos.append(dict(sorted(p.items())))
        row["positions"] = sorted(pos, key=lambda x: x.get("position_id", ""))
        rc_sum = 0.0
        rc_any = False
        for p in row["positions"]:
            v = p.get("risk_capital_usd")
            if v is not None:
                rc_sum += float(v)
                rc_any = True
        row["risk_capital_usd_sum_positions"] = rc_sum if rc_any else None
        return dict(sorted(row.items()))

    book_extract = book_subset(book_chatgpt, book_root)
    prior_extract = book_subset(prior_chatgpt, snap.get("prior_pm_books") or {})
    book_position_diff = field_diff(prior_extract, book_extract)

    lessons_doc = load_json(LESSONS_PATH)
    lessons = lessons_doc.get("lessons") or []
    lessons_out = []
    for le in lessons:
        if not isinstance(le, dict):
            continue
        lessons_out.append({
            "lesson_id": le.get("lesson_id"),
            "status": le.get("status"),
            "scope": le.get("scope"),
            "text": le.get("text"),
            "label": "memory_not_market_evidence",
        })

    hypotheses_out: List[Dict[str, Any]] = []
    for hyp_path in sorted(HYPOTHESES_DIR.glob("*.json")):
        hd = load_json(hyp_path)
        hyp_id = hd.get("hypothesis_id") or hyp_path.stem
        stmt = hd.get("statement") or hd.get("claim") or hd.get("title") or hd.get("summary")
        hypotheses_out.append({
            "file": str(hyp_path.relative_to(REPO_ROOT)),
            "id": hyp_id,
            "status": hd.get("status"),
            "statement_or_claim_or_title": stmt,
            "created": hd.get("created_at") or hd.get("created"),
            "updated": hd.get("updated_at") or hd.get("updated"),
            "label": "memory_not_market_evidence",
        })

    edge_prof = load_json(EDGE_PROFILE_PATH)

    decisions = scheduled_full.get("decisions") or {}
    pm_decisions = scheduled_full.get("pm_decisions") or {}

    leads_out: Dict[str, Any] = {}
    for seat in LEAD_SEATS:
        if seat == "pragmatist":
            block = pm_decisions.get("pragmatist")
        else:
            block = decisions.get(seat)
        if not isinstance(block, dict):
            leads_out[seat] = None
            continue
        acts = []
        for a in block.get("actions") or []:
            if not isinstance(a, dict):
                continue
            acts.append({
                "action": a.get("action"),
                "instrument": a.get("instrument"),
                "asset_class": a.get("asset_class"),
                "notional_usd": a.get("notional_usd"),
                "position_id": a.get("position_id"),
                "rationale": a.get("rationale"),
                "reason": a.get("reason"),
            })
        leads_out[seat] = {
            "label": "submitted_action_not_a_fill",
            "thesis": block.get("thesis"),
            "invalidation": block.get("invalidation"),
            "actions": acts,
        }

    clocks = {
        "snapshot_as_of": snap.get("as_of"),
        "snapshot_collect_as_of": snap.get("collect_as_of"),
        "market_state_as_of": market.get("as_of"),
        "market_state_generated_at": ms_data.get("generated_at"),
        "families_macro_hard_temperature_scores_score_inputs_last_ingested_at": (
            (mh.get("temperature_scores") or {}).get("score_inputs_last_ingested_at")
        ),
        "families_central_bank_research_as_of": cbr.get("as_of"),
        "families_news_acquisition_cutoff": (news_root.get("acquisition") or {}).get("cutoff"),
    }

    inputs_list = [
        str(SNAPSHOT_PATH.relative_to(REPO_ROOT)),
        str(SCHEDULED_REVIEW_PATH.relative_to(REPO_ROOT)),
        str(SCHEDULED_INBOX_PATH.relative_to(REPO_ROOT)),
        str(AGENT_PACKET_PATH.relative_to(REPO_ROOT)),
        f"git show {INPUT_COMMIT}:data/pm/books/latest.json (pms.chatgpt only)",
        str(LESSONS_PATH.relative_to(REPO_ROOT)),
        str(RESEARCH_INDEX_PATH.relative_to(REPO_ROOT)),
        str(EDGE_PROFILE_PATH.relative_to(REPO_ROOT)),
        "data/trading/pm/chatgpt/research/hypotheses/*.json",
    ]

    quarantine_block = {
        "statement": (
            "Derived meeting-price and Fed path estimates are excluded per quarantine: "
            "policy_meeting_prices calendar rows keep scheduling metadata only (no rate levels "
            "or step deltas); policy_paths terminal nodes and overnight delta fields are named "
            "only as quarantined paths; SR1 one-month futures quotes are listed without overnight "
            "deltas and flagged as not meeting steps."
        ),
        "policy_meeting_prices_omitted_fields": [
            "anchor",
            "fixing",
            "basis_bp",
            "chg_1d_bp",
            "chg_1w_bp",
            "contracts",
            "incremental_step_fields",
            "level_fields",
            "post_meeting_rate_fields",
            "price",
            "step_cumulative_fields",
        ],
        "policy_paths_quarantine": pp_quarantine,
        "contracts_1m_sr1": sr1_out,
        "contracts_3m_duplicate_corra": contracts_3m_note,
    }

    out_doc: Dict[str, Any] = {
        "clocks": clocks,
        "bindings": {
            "snapshot_blob_head": snapshot_blob_head,
            "snapshot_blob_at_input_commit": snapshot_blob_pin,
            "embedded_packet_sha256_in_snapshot": snap.get("packet_sha256"),
            "raw_file_sha256_snapshot": raw_sha,
            "agent_packet_fields": ap_fields,
            "agent_file_sha256": agent_sha,
            "agent_file_git_blob": agent_blob,
            "scheduled_output_review_blob": rev_blob,
            "scheduled_output_inbox_blob": inbox_blob,
            "inbox_blob_skipped_parse_matches_review": rev_blob == inbox_blob,
            "research_index_research_sha256": rs,
            "book_blob_at_input_commit": book_blob_in,
            "head_book_blob_recorded_not_used": head_book_blob,
            "limitations": limitations,
        },
        "inputs": inputs_list,
        "series": series_out,
        "series_meta": {
            "requested_count": len(SERIES_IDS),
            "history_length_disagreement_count": hist_disagree_count,
        },
        "relationship_audnzd_au_nz_2y": audnzd_rel,
        "fx": {
            "pairs_screen": fx_screen,
            "fx_block_meta": fx_meta,
            "note": "fx.pairs fields are screen metadata; 126d history does not back five-year percentiles.",
        },
        "cross_assets_latest": cross_latest,
        "tradable_curves": {
            "CORRA": {
                "instrument": corra.get("instrument"),
                "product_code": corra.get("product_code"),
                "contract_period_months": corra.get("contract_period_months"),
                "mark_convention": corra.get("mark_convention"),
                "status": corra.get("status"),
                "benchmark": corra.get("benchmark"),
                "contracts": corra_contracts,
                "contracts_subset_2027_HMUZ": corra_2027,
            },
            "SOFR": {
                "instrument": sofr.get("instrument"),
                "product_code": sofr.get("product_code"),
                "contract_period_months": sofr.get("contract_period_months"),
                "mark_convention": sofr.get("mark_convention"),
                "status": sofr.get("status"),
                "benchmark": {
                    "name": sofr_benchmark.get("name"),
                    "rate": sofr_benchmark.get("rate"),
                    "as_of": sofr_benchmark.get("as_of"),
                    "history_length": sofr_bench_hist_len,
                    "first_benchmark_history_point": sofr_first,
                    "last_benchmark_history_point": sofr_last,
                    "history_full": sofr_bench_hist,
                },
                "contracts": sofr_contracts_out,
            },
            "funding_context_sofr": sofr_fc_out,
        },
        "policy_meeting_prices_redacted": policy_mtg,
        "quarantine": quarantine_block,
        "macro_components_filtered": macro_components,
        "temperature_scores": temperature_blocks,
        "news_items": news_items_out,
        "central_bank_research": {
            "as_of": cbr.get("as_of"),
            "items": cbr_items_out,
        },
        "book": {
            "source": f"git show {INPUT_COMMIT}:data/pm/books/latest.json",
            "pms_chatgpt": book_extract,
        },
        "snapshot_prior_pm_books_chatgpt": {
            "source": "prior_pm_books.pms.chatgpt in evidence_snapshot.json",
            "subset": prior_extract,
        },
        "book_field_diff_snapshot_prior_vs_input_commit": {
            "label": "snapshot prior book vs input commit",
            "diffs": book_position_diff,
        },
        "scheduled_output": {
            "decisions_keys": sorted(decisions.keys()),
            "pm_decisions_keys": sorted(pm_decisions.keys()),
            "leads": leads_out,
        },
        "memory": {
            "label": "memory_not_newer_market_evidence",
            "lessons": lessons_out,
            "research_index": {
                "as_of": idx.get("as_of"),
                "research_sha256": idx.get("research_sha256"),
            },
            "edge_profile": {"updated_at": edge_prof.get("updated_at")},
            "hypotheses": hypotheses_out,
        },
    }

    OUT_JSON.write_text(
        json.dumps(out_doc, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    OUT_MD.write_text(build_markdown(out_doc), encoding="utf-8")

    leak_pat = ("post_rate", "cumulative_bp", "incremental_bp")
    txt = OUT_JSON.read_text(encoding="utf-8")
    leaks = [p for p in leak_pat if p in txt]
    if leaks:
        errors.append(f"quarantine leak into source_map.json: {leaks}")

    if errors:
        sys.stderr.write("BINDING OR QUARANTINE ERRORS:\n" + "\n".join(errors) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
