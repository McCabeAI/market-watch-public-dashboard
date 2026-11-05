#!/usr/bin/env python3
"""Deterministic evidence extraction from pinned git commit only."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PINNED_COMMIT = "612666a21e621e6bb437802cb48ace011f181b7b"
REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_GIT_PATH = (
    "data/overnight/runs/overnight-20261104/reviews/review-001/evidence_snapshot.json"
)
REVIEW_GIT_PATH = "data/overnight/runs/overnight-20261104/reviews/review-001/review.json"
BOOK_GIT_PATH = "data/pm/books/latest.json"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "frozen_extract.json"

COUNTRIES = ("US", "CA", "AU", "EA", "JP", "NZ")
CASH_TENORS = ("2Y", "5Y", "10Y", "30Y")
CURVE_SPREADS = ("2s10s", "5s10s")
FX_SENSITIVITY_PAIRS = (
    "USDJPY",
    "AUDUSD",
    "NZDUSD",
    "AUDNZD",
    "USDCAD",
    "AUDCAD",
    "NZDCAD",
    "AUDJPY",
    "NZDJPY",
)

MACRO_SERIES_IDS = (
    "CA.Inflation.headline",
    "CA.Inflation.underlying",
    "CA.Labor.unemployment",
    "CA.Labor.employment",
    "CA.Labor.wages",
    "AU.Inflation.headline",
    "AU.Inflation.underlying",
    "US.Inflation.cpi_headline",
    "US.Inflation.cpi_core",
    "US.Inflation.core_pce",
    "US.Labor.unemployment",
)

TEMPERATURE_VALUE_MAP = {
    "CA.Inflation.headline": ("CA", "Inflation", "headline"),
    "CA.Inflation.underlying": ("CA", "Inflation", "underlying"),
    "CA.Labor.unemployment": ("CA", "Labor", "unemployment"),
    "CA.Labor.employment": ("CA", "Labor", "employment"),
    "CA.Labor.wages": ("CA", "Labor", "wages"),
    "AU.Inflation.headline": ("AU", "Inflation", "headline"),
    "AU.Inflation.underlying": ("AU", "Inflation", "underlying"),
    "US.Inflation.core_pce": ("US", "Inflation", "core_pce"),
    "US.Labor.unemployment": ("US", "Labor", "unemployment"),
}

CONTRACT_FIELDS = (
    "expiry",
    "code",
    "implied_rate",
    "price",
    "change_from_overnight_bps",
    "open_interest",
    "volume",
    "as_of",
    "observation_date",
    "source",
)

FX_FIELDS = (
    "spot",
    "as_of",
    "pctile_1y",
    "pctile_5y",
    "z_1y",
    "z_5y",
    "ret_1d",
    "ret_5d",
    "ret_1m",
    "ret_3m",
    "rv_20d",
    "rv_60d",
)


def git_show(path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{PINNED_COMMIT}:{path}"],
        capture_output=True,
        check=True,
    )
    return proc.stdout


def git_show_json(path: str) -> Any:
    return json.loads(git_show(path).decode("utf-8"))


def pick_contract(row: dict) -> dict:
    out = {k: row.get(k) for k in CONTRACT_FIELDS}
    if out["as_of"] is None and out["observation_date"] is None:
        out["as_of"] = None
        out["observation_date"] = None
    return out


def extract_cash_yields(ms: dict) -> dict:
    out: Dict[str, Any] = {}
    bp_keys = ("bp_1d", "bp_5d", "bp_1m", "bp_3m", "bp_1y", "bp_6m")
    for cc in COUNTRIES:
        block = ms["rates"][cc]
        cc_out: Dict[str, Any] = {
            "status": block.get("status"),
            "latest_observation": block.get("latest_observation"),
            "tenors": {},
            "curves": {},
        }
        if block.get("error") is not None:
            cc_out["error"] = block.get("error")
        for tenor in CASH_TENORS:
            t = block["tenors"].get(tenor, {})
            cc_out["tenors"][tenor] = {
                "tenor": tenor,
                "value": t.get("value"),
                "as_of": t.get("as_of"),
                "bp_changes": {k: t.get(k) for k in bp_keys},
                "pctile_1y": t.get("pctile_1y"),
                "pctile_5y": t.get("pctile_5y"),
                "z_1y": t.get("z_1y"),
                "z_5y": t.get("z_5y"),
            }
        curves = block.get("curves") or {}
        for spread in CURVE_SPREADS:
            c = curves.get(spread) or {}
            cc_out["curves"][spread] = {
                "bps": c.get("bps"),
                "as_of": c.get("as_of"),
                "pctile_1y": c.get("pctile_1y"),
                "pctile_5y": c.get("pctile_5y"),
                "z_1y": c.get("z_1y"),
                "z_5y": c.get("z_5y"),
                "bp_changes": {
                    "chg_1d_bps": c.get("chg_1d_bps"),
                    "chg_5d_bps": c.get("chg_5d_bps"),
                    "chg_1m_bps": c.get("chg_1m_bps"),
                    "chg_3m_bps": c.get("chg_3m_bps"),
                    "chg_1y_bps": c.get("chg_1y_bps"),
                    "chg_6m_bps": c.get("chg_6m_bps"),
                },
            }
        out[cc] = cc_out
    return out


def extract_futures(ms: dict) -> dict:
    trc = ms["tradable_rate_curves"]["curves"]
    pp = ms["policy_paths"]["countries"]

    def curve_contracts(curve_id: str) -> List[dict]:
        curve = trc[curve_id]
        rows = curve.get("contracts") or []
        return [pick_contract(r) for r in rows]

    corra_1m = [pick_contract(r) for r in pp["CA"].get("contracts_1m") or []]
    estr = trc["ESTR"]
    return {
        "SOFR_3M": curve_contracts("SOFR"),
        "CORRA_3M": curve_contracts("CORRA"),
        "CORRA_1M_policy_paths_CA": corra_1m,
        "AONIA_1M": curve_contracts("AONIA"),
        "TONA_3M": curve_contracts("TONA"),
        "ESTR_3M": {
            "contracts": curve_contracts("ESTR"),
            "status": estr.get("status"),
            "error": estr.get("error"),
        },
    }


def extract_benchmarks(ms: dict) -> dict:
    pp = ms["policy_paths"]["countries"]
    out: Dict[str, Any] = {}
    mapping = {
        "SOFR": pp["US"]["benchmark"],
        "CORRA": pp["CA"]["benchmark"],
        "AONIA": pp["AU"]["benchmark"],
        "TONA": pp["JP"]["benchmark"],
    }
    estr_b = ms["tradable_rate_curves"]["curves"]["ESTR"]
    for name, b in mapping.items():
        row = {
            "as_of": b.get("as_of"),
            "rate": b.get("rate"),
            "source": b.get("source"),
            "source_url": b.get("source_url"),
        }
        if name == "SOFR" and b.get("history"):
            hist = b["history"]
            row["history_span"] = {
                "count": len(hist),
                "first_effective_date": hist[0].get("effective_date"),
                "last_effective_date": hist[-1].get("effective_date"),
                "note": "Embedded fixing history in snapshot; not a backtest.",
            }
        out[name] = row
    out["ESTR"] = {
        "as_of": None,
        "rate": None,
        "status": estr_b.get("status"),
        "error": estr_b.get("error"),
    }
    return out


def extract_fx(ms: dict) -> dict:
    pairs = ms["fx"]["pairs"]
    out = {}
    for pair in sorted(pairs.keys()):
        p = pairs[pair]
        out[pair] = {k: p.get(k) for k in FX_FIELDS}
    meta = {
        "status": ms["fx"].get("status"),
        "age_days": ms["fx"].get("age_days"),
        "source_observation": ms["fx"].get("source_observation"),
    }
    return {"meta": meta, "pairs": out}


def extract_cross_assets(ms: dict) -> dict:
    return ms["cross_assets"]["compact"]


def search_inflation_market_paths(snapshot: dict) -> dict:
    terms = ("breakeven", "tips", "real_yield", "real_rate")
    key_hits: List[str] = []
    string_hits: List[dict] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else k
                if any(t in k.lower() for t in terms):
                    key_hits.append(p)
                walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            low = obj.lower()
            for t in terms:
                if t in low:
                    string_hits.append({"term": t, "path": path, "sample": obj[:160]})
                    break

    walk(snapshot, "")
    dedup_keys = sorted(set(key_hits))
    return {
        "key_paths": dedup_keys if dedup_keys else "ABSENT",
        "string_value_paths": string_hits if string_hits else "ABSENT",
        "market_level_breakeven_series": [
            "families.market_state.data.cross_assets.series.US_BE10",
            "families.market_state.data.cross_assets.series.US_REAL10",
            "families.market_state.data.opportunities.series (labels US 10Y breakeven / real yield)",
        ],
        "tips_dedicated_series": "ABSENT",
    }


def extract_canada_prima(snapshot: dict, ms: dict) -> dict:
    cpp = ms.get("canada_prima_pressure") or snapshot.get("canada_prima_pressure") or {}
    brent_levels = []
    for key in ("brent_deferred", "brent_forwards", "oil_forwards"):
        block = cpp.get(key)
        if isinstance(block, list):
            for row in block:
                if isinstance(row, dict) and row.get("price") is not None:
                    brent_levels.append({"path": f"canada_prima_pressure.{key}", **row})
    text = cpp.get("change_since_last_mpr") or ""
    brent_prose = None
    if "70" in text and "+14.88" in text:
        brent_prose = {
            "source": "change_since_last_mpr prose",
            "brent_end_2027_vs_prose_usd_per_bbl": 14.88,
            "prose_assumption_usd_per_bbl": 70.0,
            "conditioning_date_in_text": "2026-07-09",
        }
    return {
        "direction": cpp.get("direction"),
        "strength": cpp.get("strength"),
        "confidence": cpp.get("confidence"),
        "front_shock_classification": cpp.get("front_shock_classification"),
        "change_since_last_mpr": cpp.get("change_since_last_mpr"),
        "largest_drivers": cpp.get("largest_drivers"),
        "subcomponent_directions": cpp.get("subcomponent_directions"),
        "conditioning_date": cpp.get("conditioning_date"),
        "brent_forward_levels_found": brent_levels if brent_levels else "ABSENT except prose",
        "brent_prose_vs_70": brent_prose,
    }


def macro_component_index(snapshot: dict) -> Dict[str, dict]:
    comps = snapshot["families"]["macro_hard"]["components"]
    return {c["series_id"]: c for c in comps if c.get("series_id")}


def temperature_value(snapshot: dict, series_id: str) -> Optional[dict]:
    if series_id not in TEMPERATURE_VALUE_MAP:
        return None
    cc, dim, comp = TEMPERATURE_VALUE_MAP[series_id]
    ts = snapshot["families"]["macro_hard"]["temperature_scores"]["countries"]
    state = ts[cc][dim]["component_state"][comp]
    path = (
        f"families.macro_hard.temperature_scores.countries.{cc}.{dim}"
        f".component_state.{comp}"
    )
    return {
        "path": path,
        "transform_value": state.get("transform_value"),
        "level": state.get("level"),
        "as_of": state.get("as_of"),
        "release_date": state.get("release_date"),
        "note": "Value from temperature score state, not component.provenance/extra.",
    }


def extract_macro(snapshot: dict) -> dict:
    idx = macro_component_index(snapshot)
    out = {}
    for sid in MACRO_SERIES_IDS:
        comp = idx.get(sid)
        if comp is None:
            out[sid] = {
                "observation_period": None,
                "status": None,
                "research_status": None,
                "value": None,
                "numeric_fields": {},
                "looked_paths": [
                    "families.macro_hard.components[].series_id",
                ],
            }
            continue
        looked = [
            f"families.macro_hard.components[series_id={sid}].provenance",
            f"families.macro_hard.components[series_id={sid}] (no extra field on component)",
            "families.macro_hard.extra.score_lineage.appended",
        ]
        prov = comp.get("provenance")
        numeric = {}
        value = None
        if isinstance(prov, dict):
            for k in ("value", "transform_value", "yoy", "mom", "level"):
                if prov.get(k) is not None:
                    numeric[k] = prov.get(k)
            value = prov.get("value", prov.get("transform_value"))
        temp = temperature_value(snapshot, sid)
        if value is None and temp is not None:
            numeric["transform_value"] = temp.get("transform_value")
            numeric["level"] = temp.get("level")
            value = temp.get("transform_value")
        out[sid] = {
            "observation_period": comp.get("observation_period"),
            "status": comp.get("status"),
            "research_status": comp.get("research_status"),
            "value": value,
            "numeric_fields": numeric,
            "provenance_on_component": prov,
            "temperature_scores_supplement": temp,
            "looked_paths": looked,
        }
    return out


def extract_chatgpt_book(book_root: dict) -> dict:
    pm = book_root["pms"]["chatgpt"]
    pos = pm["positions"][0]
    realized = None
    for row in pm.get("history") or []:
        if row.get("action") == "REDUCE" and row.get("realized_pnl_usd") is not None:
            realized = row.get("realized_pnl_usd")
    return {
        "instrument": pos.get("instrument"),
        "side": pos.get("side"),
        "notional_usd": pos.get("notional_usd"),
        "entry": pos.get("entry_price"),
        "mark": pos.get("mark_price"),
        "mark_price_as_of": pos.get("mark_price_as_of"),
        "risk_capital_usd": pos.get("risk_capital_usd"),
        "unrealized_pnl_usd": pos.get("unrealized_pnl_usd"),
        "realized_pnl_usd": realized,
        "funding_cost_usd": pm.get("funding_cost_usd"),
        "funding_rate_annual": pm.get("funding_rate_annual"),
        "funding_convention": pm.get("funding_convention"),
        "funding_day_count": pm.get("funding_day_count"),
        "funding_percent_rate": pm.get("funding_percent_rate"),
        "nav_usd": pm.get("nav_usd"),
        "identity_check_unrealized_usd": (
            pos.get("notional_usd") * (pos.get("entry_price") - pos.get("mark_price")) / 100.0
            if pos.get("notional_usd") and pos.get("entry_price") and pos.get("mark_price")
            else None
        ),
    }


def extract_competition(snapshot: dict) -> dict:
    c = snapshot.get("competition") or {}
    return {
        "funding_rate_annual": c.get("funding_rate_annual"),
        "convention": c.get("funding_convention"),
        "day_count": c.get("funding_day_count"),
        "observation_date": c.get("funding_observation_date"),
        "source": c.get("funding_source"),
    }


def extract_news(snapshot: dict) -> dict:
    items = snapshot["families"]["news"]["items"]
    headlines = [
        {"headline": it.get("headline"), "published_at": it.get("published_at")} for it in items
    ]
    election_flag = any(
        "election" in (h.get("headline") or "").lower()
        and "yield" in (h.get("headline") or "").lower()
        for h in headlines
    )
    return {
        "count": len(headlines),
        "items": headlines,
        "election_yields_headline_in_freeze": election_flag,
    }


def build_article_context() -> dict:
    return {
        "source_updated": "2026-11-04T17:11:00Z",
        "cache_time": "2026-11-04T18:01:00Z",
        "receipt": "later in the Nov 4 Work conversation after the freeze; minute not captured",
        "narrative": {
            "ust2": 4.573,
            "ust10": 4.898,
            "ust30": 5.293,
            "wti": 88,
            "brent": 94,
        },
        "quote_table": {"ust2": 4.577, "ust30": 5.29},
        "stated_moves": {
            "ust2": "down >4bp",
            "ust10": "down >5bp",
            "ust30": "down >3bp",
            "wti": "about -8% toward 88",
            "brent": "about -8% toward 94",
        },
    }


def article_context_gaps(article: dict, ms: dict) -> dict:
    us = ms["rates"]["US"]["tenors"]
    compact = {m["id"]: m for m in ms["cross_assets"]["compact"]["marks"]}

    def gap(label: str, frozen: Optional[float], unsync: float) -> dict:
        if frozen is None:
            return {"label": label, "frozen": None, "unsynchronized": unsync, "gap": None}
        return {
            "label": label,
            "frozen": frozen,
            "unsynchronized": unsync,
            "gap_absolute": unsync - frozen,
            "gap_bp_where_rate": (unsync - frozen) * 100.0,
            "classification": "UNSYNCHRONIZED",
        }

    nar = article["narrative"]
    qt = article["quote_table"]
    gaps = {
        "versus_frozen_cash_yields": {
            "ust2_narrative_vs_US_2Y": gap("UST2Y", us["2Y"]["value"], nar["ust2"]),
            "ust10_narrative_vs_US_10Y": gap("UST10Y", us["10Y"]["value"], nar["ust10"]),
            "ust30_narrative_vs_US_30Y": gap("UST30Y", us["30Y"]["value"], nar["ust30"]),
        },
        "narrative_vs_quote_table": {
            "ust2": gap("narrative_vs_quote_2Y", qt["ust2"], nar["ust2"]),
            "ust30": gap("narrative_vs_quote_30Y", qt["ust30"], nar["ust30"]),
        },
        "oil_percent_vs_frozen_compact": {
            "wti": {
                "frozen": compact["WTI"]["value"],
                "unsynchronized_narrative": nar["wti"],
                "ratio_minus_one": (nar["wti"] / compact["WTI"]["value"]) - 1.0,
                "classification": "UNSYNCHRONIZED",
            },
            "brent": {
                "frozen": compact["BRENT"]["value"],
                "unsynchronized_narrative": nar["brent"],
                "ratio_minus_one": (nar["brent"] / compact["BRENT"]["value"]) - 1.0,
                "classification": "UNSYNCHRONIZED",
            },
        },
    }
    return gaps


def main() -> int:
    blob = git_show(SNAPSHOT_GIT_PATH)
    snapshot_sha256 = hashlib.sha256(blob).hexdigest()
    snapshot = json.loads(blob.decode("utf-8"))
    review = git_show_json(REVIEW_GIT_PATH)
    book = git_show_json(BOOK_GIT_PATH)
    ms = snapshot["families"]["market_state"]["data"]
    article = build_article_context()

    meta = {
        "pinned_commit": PINNED_COMMIT,
        "review_status": review.get("status"),
        "overnight_run_id": review.get("overnight_run_id"),
        "review_id": review.get("review_id"),
        "packet_sha256": review.get("packet_sha256"),
        "frozen_at": review.get("frozen_at"),
        "accepted_at": review.get("accepted_at"),
        "snapshot_file_sha256": snapshot_sha256,
        "market_state_generated_at": ms.get("generated_at"),
        "market_state_digest": snapshot["families"]["market_state"]["digest"],
        "snapshot_as_of": snapshot.get("as_of"),
    }

    payload = {
        "meta": meta,
        "cash_yields": extract_cash_yields(ms),
        "futures_contracts": extract_futures(ms),
        "benchmarks": extract_benchmarks(ms),
        "fx": extract_fx(ms),
        "cross_assets_compact": extract_cross_assets(ms),
        "breakeven_tips_real_search": search_inflation_market_paths(snapshot),
        "canada_prima_pressure": extract_canada_prima(snapshot, ms),
        "macro_series": extract_macro(snapshot),
        "chatgpt_position_economics": extract_chatgpt_book(book),
        "competition_funding": extract_competition(snapshot),
        "news_headlines": extract_news(snapshot),
        "article_context": article,
        "article_context_gaps": article_context_gaps(article, ms),
    }

    out_path = DEFAULT_OUTPUT
    if len(sys.argv) > 1:
        out_path = Path(sys.argv[1])
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
