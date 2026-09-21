# Temperature V1 independent verification (Composer V1)

**Repository:** McCabeAI/market-watch-public-dashboard  
**Branch:** `cursor/rebase-market-watch-temperature-gauges-on-one-year-of-data-5986`  
**HEAD:** `8c25f14e6fe7e119e25db3c882cf72573e03e601` (2026-09-21)  
**PR:** https://github.com/McCabeAI/market-watch-public-dashboard/pull/66  
**Verifier:** V1 (did not implement I1/I2/G1 rebuild)  
**Date:** 2026-09-21  

## Verdict: **PASS-WITH-FINDINGS**

No blocking correctness defects found in the integrated V1 LEVEL engine, canonical `data/temperature_scores.json`, Trader Room gauge loader, or dashboard patch path. Findings are documentation / artifact staleness and expected quarterly-GDP impulse magnitude (non-blocking).

---

## 1. Hand recomputation of four component LEVELs (±0.05)

Formula (from `scripts/temperature_level.py` `component_level`):  
`LEVEL = clip(50 + hot_direction × (transform_value − anchor) × scale_per_unit, 1, 100)`.

| Component | History inputs (verified) | Hand math | Stored (`temperature_scores.json`) | Δ |
|-----------|---------------------------|-----------|-----------------------------------|---|
| **US Inflation `core_pce`** | `mom_sa_pct` May–Jul 2026: 0.359343, 0.146757, 0.245516 → 3m compound annualized **3.047776%** | 50 + 1×(3.047776−2)×12.5 = **63.097** | transform 3.0478, level **63.1** | 0.003 |
| **US Labor `unemployment`** | UNRATE **2026-08 = 4.1%** | 50 + (−1)×(4.1−4.2)×20 = **52.0** | **52.0** | 0 |
| **CA Inflation `underlying`** | Trim 1.9% + median 2.0% y/y **2026-08** → equal mean **1.95%** | 50 + 1×(1.95−2)×12.5 = **49.375** | **49.38** | 0.005 |
| **NZ Activity `gdp_domestic_demand`** | Production GDP `SNEQ.SG01RSC01B01PC` q/q **2026-Q2 = 0.2%** → SAAR **0.8024%** | 50 + 1×(0.8024−2)×10 = **38.024** | **38.02** | 0.004 |

Full engine recompute (`compute_state(..., cutoff="2026-09")`) matches on-disk `data/temperature_scores.json` for all 16 dimensions (zero mismatches).

---

## 2. LEVEL is not `50 + Σ old impulses`; no calendar drift

- **Not cumulative impulse index:** Dimension LEVELs are coverage-weighted anchored component LEVELs (e.g. US Labor **50.0** while component impulses sum to +5.1; US Consumer **46.47** vs sum of component impulses +13.19). No dimension equals `50 + sum(component impulses)` within 0.01 except trivial cases.
- **No calendar drift without new data:** `compute_state(..., cutoff="2026-09")` and `cutoff="2099-12"` produce identical LEVEL tables (same latest observation periods under `period_leq(cutoff)`). Matches `tests.test_temperature_level.test_level_stable_when_no_new_observations`.

---

## 3. Missing components reduce coverage (not imputed as 50)

| Country | Dimension | Expected coverage | Actual | Missing component(s) |
|---------|-----------|-------------------|--------|----------------------|
| CA | Activity | 0.60 | **0.60** | `business_surveys` `observed: false` |
| CA | Consumer | 0.75 | **0.75** | `confidence` not observed |
| AU | Activity | 0.60 | **0.60** | `business_surveys` |
| AU | Consumer | 0.75 | **0.75** | `retail` not observed |

Unobserved components have `level: null` in `component_state`; they do not contribute 50 to aggregates (see AU Consumer `retail` in tests).

---

## 4. Weights unchanged vs docs

`data/temperature_calibration.json`: `"weights_changed": false`. Labor **0.7 / 0.2 / 0.1** (unemployment / wages / employment|payrolls) for all four countries; Inflation **0.6 / 0.4** underlying|headline (US core_pce **1.0**); Activity **0.6 / 0.4**; Consumer **0.25 × 4**. Aligns with `docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md`.

---

## 5. Trader Room `load_temperature_gauges()`

- **Source:** `data/temperature_scores.json` version 3 (`scripts/trader_room/evidence.py`); not `patch_v8`.
- **Count:** 16 gauges.
- **Parity:** All 16 `score` / `impulse` / `direction` fields match JSON (independent check on repo root).
- **Not prototype 72/75:** `source` is `data/temperature_scores.json`; US Inflation score **63.1**, not patch_v8 **72.0**.

---

## 6. `apply_temperature_scores` on mini dashboard (patch_v8 blocks)

Built HTML via `apply_scores(_mini_dashboard_html(), load_state())` (same pattern as `tests/test_temperature_scores.py`):

- All **16** LEVEL strings present (e.g. US Inflation **63.1/100**, CA Activity **64.39/100**).
- **16** separate `score-impulse` rows (LEVEL vs print-to-print impulse).
- **16** lineage notes with phrase **`50 = structural/policy neutral anchor`**; **no** `Reindexed to 50 on 2026-09-17`.
- Unpatched `patch_v8/us.html` still embeds **72.0/100** (legacy placeholder); patched output contains **no** `72.0/100`.

---

## 7. Automated checks (this workspace)

```text
PYTHONPATH=. python3 -m unittest \
  tests.test_temperature_history_audit \
  tests.test_temperature_level \
  tests.test_temperature_scores \
  tests.test_trader_room_ondemand \
  tests.test_trader_room_dashboard
→ Ran 50 tests in ~1.9s — OK (skipped=1: fixture dir absent for reproducibility fixture test)

PYTHONPATH=. python3 scripts/validate_score_sources.py → exit 0
PYTHONPATH=. python3 scripts/validate_trader_room.py → exit 0
```

---

## 8. `score_paths.json` pathology (CA / NZ Activity impulses)

Large Activity impulses are **explained by quarterly GDP → SAAR level jumps**, not wrong series selection:

| Country | Latest q/q | Prior q/q | SAAR levels | Component impulse |
|---------|------------|-----------|-------------|-------------------|
| **CA** | 2026-Q2 **+0.8%** | 2026-Q1 **+0.1%** | 64.39 vs 36.01 | **+28.38** |
| **NZ** | 2026-Q2 **+0.2%** | 2026-Q1 **+0.9%** | 38.02 vs 66.49 | **−28.46** |

NZ scoring uses **production** GDP `SNEQ.SG01RSC01B01PC` only; expenditure GDP `SNEQ.SG02RSC31B15PC` remains in history but is **excluded** by `series_id` filter (test `test_nz_gdp_pins_production_series_only`). Not a lookback-row-as-latest bug for 2026-Q2.

`score_paths.json` `pathology.findings` flag month-to-month LEVEL jumps >15 on Activity around GDP release months (2025-12, 2026-03, 2026-06); consistent with legitimate quarterly prints.

---

## 9. US `mapped_bridge` excluded from Inflation LEVEL

- Calibration: `unscored_components.US.Inflation.mapped_bridge.enters_level: false`.
- Live state: US Inflation `components` = **`core_pce` only**, `coverage` **1.0**.
- History retains `Inflation.mapped_bridge` for audit; engine weights do not include it.

---

## 10. Stale competing score paths (hunt)

| Location | Status |
|----------|--------|
| `patch_v8/*.html` | Legacy placeholders (e.g. US Inflation **72.0**); **overwritten at Pages build** by `apply_temperature_scores.py`. |
| `data/temperature_scores.json` v3 | **Canonical live LEVEL + impulse** — consistent with engine. |
| `all_scores` | **Not present** in repo (grep). |
| Notion temperature DB | Retired per docs; GitHub canonical — no live Notion score path found in code. |
| `scripts/trader_room/evidence.py` | **Fixed** — reads JSON (G0 doc claim about parsing patch_v8 is **stale**). |
| `data/pm/review_packets/**` | Historical packets still mention `dashboard_v8_retained` / 2026-09-17 overlay text — **artifact staleness**, not runtime loader. |
| `patch_v8/README.md` | Still describes pre-V1 reindex narrative; build-time patch supersedes displayed values. |

---

## 16-score table (independent recompute vs JSON)

All **Match OK** (recompute ≡ stored).

| Country | Dimension | LEVEL | Impulse | Direction | Coverage |
|---------|-----------|------:|--------:|-----------|----------|
| US | Inflation | 63.1 | −0.81 | static | 1.00 |
| US | Labor | 50.0 | +0.36 | static | 1.00 |
| US | Activity | 49.06 | −6.0 | cooling | 1.00 |
| US | Consumer | 46.47 | +3.55 | warming | 1.00 |
| CA | Inflation | 54.78 | 0.0 | static | 1.00 |
| CA | Labor | 42.16 | −2.52 | cooling | 1.00 |
| CA | Activity | 64.39 | +28.38 | warming | 0.60 |
| CA | Consumer | 62.12 | +4.53 | warming | 0.75 |
| AU | Inflation | 63.25 | −1.5 | cooling | 1.00 |
| AU | Labor | 50.12 | −0.3 | static | 1.00 |
| AU | Activity | 43.6 | +4.04 | warming | 0.60 |
| AU | Consumer | 54.34 | +20.0 | warming | 0.75 |
| NZ | Inflation | 64.25 | +4.25 | warming | 1.00 |
| NZ | Labor | 36.6 | −2.1 | cooling | 1.00 |
| NZ | Activity | 38.02 | −28.46 | cooling | 0.60 |
| NZ | Consumer | 48.38 | −4.5 | cooling | 1.00 |

---

## Non-blocking findings (recommended follow-ups)

1. Update **`docs/TEMPERATURE_CALIBRATION_G0.md`** item 2 — Trader Room now loads v3 JSON, not patch_v8.
2. Refresh **`patch_v8/README.md`** to match V1 structural-anchor lineage (avoid implying live site still uses cumulative reindex).
3. Large **quarterly GDP impulses** on CA/NZ Activity (and AU Consumer spending +28 impulse) are economically loud but **methodologically consistent** with SAAR mapping and print-to-print impulse definition.
4. **Proprietary / gap** components (CA/AU business surveys, CA confidence, AU retail) remain absent with reduced coverage — by design.
5. **Latest-vintage history** and partial US `mapped_bridge` history remain audit limitations per C5 doc — do not affect LEVEL.

---

## Blocking issues

**None identified.**

---

*Report path:* `docs/TEMPERATURE_V1_VERIFICATION.md` (not committed per V1 instructions).
