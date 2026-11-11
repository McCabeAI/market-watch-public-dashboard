# Canada PRiMA CPI transmission (v2)

Additive `transmission` block alongside the legacy five-vote `canada_prima_pressure_v1` proxy.
This is a deterministic Market Watch research view — **not** the Bank of Canada's proprietary PRiMA.

## Method (summary)

- **Numerical** direct-fuel coverage only (gasoline 4.01% + fuel oil 0.24%, 2025 basket).
- Brent listed **front** same-contract 1m USD change combined with **USDCAD** (CAD per USD) once:
  `combined = (1+r_usd)(1+r_fx)−1`.
- **Live path** (`provenance: live_observed`): staged gasoline/fuel-oil pp with auditable
  `stages.{B,C,curve}` — Stage B retail gap (NRCan), Stage C cost-to-pump (RBOB wholesale when
  bars available else Brent crude), curve adjustment mean(front,3m), and h3_6m mean(3m)→mean(3m,6m).
  Live point estimate uses tax factor **1.10** only (`pp_low = pp_mid = pp_high`).
- Reconstructed snapshots use a crude-cost-share **range** with `pp_low`/`pp_high` as numeric
  min/max across share scenarios (`range_basis: crude_cost_share 0.35/0.45/0.55`; fuel oil
  0.5/0.6/0.7). Country Detail caption: *crude-cost-share elasticity 0.35/0.45/0.55 (fuel oil
  0.5/0.6/0.7)* — **not** the live 1.10 tax factor.
- Live caption: *cost change × 1.10 ad-valorem tax / pump price, ~1 month pass-through*.
- Imported goods and food/inputs are **directional** (no invented import-price index).
- CORRA appears in `policy_context` only (legacy vote unchanged).

### Source identifiers

| Input | Source |
|-------|--------|
| Brent / WTI / RBOB / HO | NYMEX listed symbols via Yahoo chart (`scripts/prima_pressure/curve.py`) |
| USDCAD | ECB SDMX crosses in `scripts/market_state.py` (`build_fx_crosses`) |
| IPPI / RMPI | StatCan WDS vectors (`18-10-0265-01`, `18-10-0268-01`) |
| Sector PPI | `18-10-0292-01` (shadow layer) |
| NRCan pump (live only) | `scripts/canadian_cpi_release/sources/nrcan.py`, locationID 66 |
| CPI weights | `scripts/canadian_cpi_release/weights.py` (2025-01 vintage) |

### Not wired (this build)

- **Weekly NRCan** — monthly national fetch only; weekly frequency not implemented.
- **BoC BCPI** (`W.BCNE`, `W.AGRI`) — metadata verified on Valet (weekly, export-price index) but no fetcher added; food channel uses RMPI/IPPI bands only.
- **CPI gasoline vector** (`v41691136`) — optional per plan; not added.
- **Import price index** — remains `IMPORT_PRICE_MEASURE` unavailable.

### FX dating (reconstructed)

Accepted overnight snapshots supply USDCAD **spot** + **as_of** in
`families.market_state.data.fx.pairs.USDCAD`. Dated spots within 5 calendar days of Brent
`change_1m_base_date` / `observation_date` are preferred (`collect_fx_history_points`).
If no accepted snapshot has a spot on **2026-10-09** (nearest prior in-repo is **2026-10-20**,
beyond the 5-day window), reconstruction falls back to the same snapshot's `ret_1m`
(21 ECB business days) with `fx_window_approximate: true`.

## Example — reconstructed from `overnight-20261110/review-001`

Snapshot inputs: BZF27 front 92.57 USD/bbl (obs 2026-11-09), 1m −8.57% from 2026-10-09;
USDCAD 1.41026 (`ret_1m` −0.87%, `ret_3m` +1.27%); latest CPI month **2026-09**.

| Field | Value |
|-------|-------|
| `provenance` | `reconstructed_from_frozen_v1` |
| Brent-in-CAD `combined` | −9.37% |
| Fuel `h1_3m` `pp_mid` | −0.183 pp (range −0.222 … −0.143, low = most negative) |
| Fuel `h1_3m` `direction` | `mixed` (`prior_window_opposite_sign`) |
| `coverage` | `partial` (`2026-09-30 → 2026-10-09`) |
| `prior_window_evidence` | BZZ26 +20.0% (2026-09-30→2026-10-30); not netted with Jan-27 window |
| Fuel `h3_6m` | directional `down` (front 92.57 > 12m 78.28, backwardation) |
| Imported goods | `neutral` (FX not material; h1_3m *small, lagged*) |
| Food/inputs `h3_6m` | `down` (RMPI ex-crude −0.435% beyond band) |

**Country Detail overview (2026-11-10 snapshot, rendered)**

- **What changed** — Brent-in-CAD 1m −9.4% (2026-10-09→2026-11-09)
- **Where it is transmitting** — Producer stage: IPPI energy +12.1% m/m, RMPI crude +14.4% (Sep); CPI transport +0.3% m/m, breadth 5/8 majors up, trim accel +0.37 pp (Sep)
- **What remains** — Fuel 1–3m −0.18 pp from the Jan-27 repricing 2026-10-09→2026-11-09 only; the Dec-26 contract rose +20.0% 2026-09-30→2026-10-30 (expired), not netted — October CPI fuel may still rise; net sign unresolved; core mixed; fuel 3–6m down — downward if the futures curve is realised (front 92.57 vs 12m 78.28 USD/bbl)
- **Glance** — Fuel CPI 1–3m mixed (partial)
- **Status** — Reconstructed inputs 2026-11-10 · CPI 2026-09 · IPPI/RMPI 2026-09 (rel. 2026-10-22) · sector PPI 2026-Q2 (rel. 2026-10-09) · Brent 2026-10-09→2026-11-09; USD/CAD 21 ECB business days to 2026-11-09 · provenance `reconstructed_from_frozen_v1`
- **Core evidence** — CPI breadth 5/8 majors up · trim accel 0.37 pp (2026-09)

Abbreviated JSON (computed 2026-11-11):

```json
{
  "schema_version": "canada_prima_transmission_v2",
  "method_version": "ca_prima_tx_2026_11_v1",
  "provenance": "reconstructed_from_frozen_v1",
  "as_of": "2026-11-10",
  "cpi_reference_period": "2026-09",
  "channels": {
    "energy_direct_fuel": {
      "observed_change": {
        "decomposition": {
          "usd_leg": -0.08572839807581019,
          "fx_leg": -0.008698197633086546,
          "combined": -0.09368091315966542
        },
        "flags": ["fx_window_approximate"]
      },
      "remaining": {
        "h1_3m": {
          "basis": "range",
          "direction": "mixed",
          "pp_mid": -0.18253725929160808,
          "coverage": "partial",
          "uncovered_interval": "2026-09-30 → 2026-10-09"
        },
        "h3_6m": { "basis": "directional", "direction": "down" }
      }
    }
  }
}
```

## Example — live (synthetic fixture, offline test)

M_c `2026-09` pump 150.0 c/L; M_r `2026-10` pump 155.0 c/L; RBOB wholesale used for Stage C.

- **Stage B** = `4.01 × (155/150 − 1)` ≈ **+0.134 pp**
- **Stage C** = `(cost_now − avg_oct_wholesale) × 1.10 / 155 × 4.01` (wholesale c/L, ≥11 daily bars in M_r)
- **h1_3m** numerical sum of B + C + curve (≈ **+0.50 pp** in default fixture with RBOB 2.35 vs Oct avg 2.0)

```json
{
  "provenance": "live_observed",
  "channels": {
    "energy_direct_fuel": {
      "stages": {
        "B": { "pp_gasoline": 0.1337, "M_c": "2026-09", "M_r": "2026-10" },
        "C": { "pp_gasoline": 0.3684, "cost_basis": "wholesale" },
        "curve": { "pp_gasoline_h1": 0.0 }
      },
      "remaining": {
        "h1_3m": { "basis": "numerical", "pp_mid": 0.502, "direction": "up" }
      }
    }
  }
}
```

## Known limitations

- **Roll / uncovered interval:** Reconstructed fuel `h1_3m` pp applies only to the **current front contract's own** 1m Brent-in-CAD window (no splicing across listed contracts). When CPI is partial, accepted snapshots may supply `prior_window_evidence` for the prior prompt contract's same-contract window near month-end; opposite-sign moves set `direction: mixed` and are **not** netted into the pp range.
- CPI evidence release dates use CPI breadth / `data/temperature_history/ca.json` only — not IPPI/RMPI release times.

## Public interfaces (`scripts/prima_pressure/transmission.py`)

- `build_transmission(inputs, *, as_of) -> dict`
- `inputs_from_live(bundle, *, usdcad_history, nrcan, as_of) -> dict`
- `inputs_from_frozen(block, *, usdcad_pair, fx_history_points=(), as_of) -> dict`
- `transmission_for_snapshot(snapshot, *, fx_history_points=(), root=None) -> dict`
- `unavailable_transmission(reason) -> dict`
- `collect_fx_history_points(root) -> list[tuple[date, float, str]]`
