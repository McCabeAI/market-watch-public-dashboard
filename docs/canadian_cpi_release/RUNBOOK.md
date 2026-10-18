# Canadian CPI pre-release nowcast — runbook

Human-triggered B2 nowcast for Statistics Canada CPI reference months. The frozen fixture excludes **October 19, 2026** StatCan actuals; September 2026 is a pre-release replay as of **2026-10-16**.

## Sample nowcast (offline fixture)

```bash
PYTHONPATH=. python3 -m scripts.canadian_cpi_release nowcast \
  --release 2026-09 \
  --as-of 2026-10-16 \
  --out /tmp/ca_cpi_out \
  --fixture scripts/canadian_cpi_release/fixtures/pre_2026-10-19/snapshot.json
```

Writes `nowcast.json` and `nowcast.txt`; prints the text report on stdout. Exit **0** when `status` is `ok`, **2** when blocked.

### Live fetch archive

`--live` writes an immutable run directory and does not replace an earlier archive:

```text
<out>/runs/<release>-asof-<as-of>-<snapshot_sha12>/
  snapshot.json
  manifest.json
  raw/                  # StatCan JSON and NRCan HTML actually fetched
  nowcast.json
  nowcast.txt
```

The report prints that path and the snapshot sha256. Replay the same forecast with no network:

```bash
PYTHONPATH=. python3 -m scripts.canadian_cpi_release nowcast \
  --release 2026-09 \
  --as-of 2026-10-16 \
  --fixture <out>/runs/<release>-asof-<as-of>-<snapshot_sha12>/snapshot.json \
  --out /tmp/ca_cpi_replay
```

A different snapshot already stored under that directory is a hard failure (`archive_conflict` or `archive_raw_missing`), exit 2, and the previous files stay in place. Fixture mode still writes directly under `--out`.

### September 2026 result (fixture, as-of 2026-10-16)

| Field | Value |
| --- | --- |
| Headline NSA MoM (B2) | 0.1325763171949602 % |
| Index | 170.02511458659706 |
| YoY | 3.1080136971479932 % |
| SA MoM | 0.49794661424806275 % |
| Gasoline leaf contribution | 0.21333902085517664 pp |
| Fuel oil leaf | 0.02795882171649898 pp |
| Transportation ex gasoline | -0.17100059384701227 pp |
| Shelter ex fuel oil (nested diagnostic) | 0.050717363127041865 pp (not in leaf sum) |
| Ex-food-and-energy NSA / SA / YoY | 0.038294418499958086 / 0.23609669270469724 / 2.2270344508223516 |
| Ex-energy NSA / SA / YoY | -0.03422140158634876 / unavailable / 2.1817687643883366 |
| Ex-gasoline NSA MoM | -0.03605326318533214 |
| CPI-trim YoY / MoM / 3m ann. | 1.845111358920981 / 0.18233403061207837 / 2.5795664639642 |
| CPI-median YoY / MoM / 3m ann. | 1.903946499405218 / 0.1790690085466895 / 2.532899042534198 |
| CPI-common | unavailable |

Astra research reference headline NSA MoM **0.1325244** (not a model input): absolute gap ≈ **5×10⁻⁵** pp → `reproduced_within_0_001_pp` is true.

Basket: **2025** basket year, link month **2026-04**.

## Headline backtest (pseudo-OOS, latest vintage)

```bash
PYTHONPATH=. python3 -m scripts.canadian_cpi_release backtest \
  --as-of 2026-10-16 \
  --through 2026-08 \
  --start 2017-01 \
  --out /tmp/ca_cpi_bt \
  --fixture scripts/canadian_cpi_release/fixtures/pre_2026-10-19/snapshot.json
```

Writes `backtest.json` with per-month rows and `metrics`. Label: **pseudo-OOS latest vintage** (not a full real-time vintage study).

### MAE vs `docs/research/ca_cpi_reference/aggregate_metrics.csv` (regime `all`)

| Model | Engine MAE | Astra CSV MAE | Match |
| --- | --- | --- | --- |
| A | 0.26601393675895185 | 0.26601393675895185 | exact |
| season5 | 0.2597626232098794 | 0.2597626232098794 | exact |
| B2 | 0.20426140267960316 | — | research text ≈ 0.204 |
| B (CSV only) | — | 0.2048751819052762 | **gasoline-only research baseline, not B2** |

## Provenance and inputs

- **StatCan WDS** vectors and coordinates are locked in `scripts/canadian_cpi_release/contract.py` (tables 18-10-0004 NSA, 18-10-0006 SA, 18-10-0256 core trim/median, 18-10-0205 NHPI house-only vector **111955443**, 18-10-0007 weights).
- **Weights**: price-updated shares from table 18-10-0007 at basket-year January, link-month and t−1 index levels (`share = (w%/100) × (index_prev/index_link) / (all_prev/all_link)`).
- **NRCan** regular gasoline **productID=1** and furnace oil **productID=7**, **locationID=66** (Canada). HTML archived under fixture `raw/` with sha256; **NRCan does not archive per-observation retrieval timestamps**.
- **Furnace oil**: official NRCan monthly table has **no 2017-08** row; the gap is noted in snapshot notes, not filled from the research CSV.

## Vintage and scope caveats

- Backtest and uncertainty bands are **pseudo-OOS on the latest index vintage** in the snapshot, not a full StatCan real-time vintage replay.
- Table **18-10-0259** (CPI vintages) was **not** bulk-downloaded; known cube coverage is reference through **2026-03** / release through **2026-04-20**.
- CPI-trim and CPI-median forecasts are a **3/6-month blend of official indexes**, not a 55-component replication.
- No consensus or market edge is claimed.

## Failure behavior (exit 2)

Publication is blocked when any of the following apply:

- Missing target-month **NRCan** fuel price (mandatory bridge inputs).
- Missing **prior-month CPI** majors/children visible at `as_of` (e.g. forecasting September before August CPI is published 2026-09-14).
- **Stale basket** weights relative to `as_of`.
- **Contribution residual** (disjoint leaves do not sum to headline B2).
- **Future leakage** (observations with `published_at` after `as_of` are ignored; stale fixture for release → `fixture_stale_for_release`).
- **Fixture stale for release**: latest `cpi_nsa_all_items` period earlier than release minus one month.

## PENDING AUTHORIZATION

Explicit approval is required before adding **any** file under `.github/workflows/`. Proposed design only:

```yaml
# NOT AUTHORIZED — do not commit without review
name: ca-cpi-nowcast-manual
on:
  workflow_dispatch:
    inputs:
      release:
        description: CPI reference month (YYYY-MM)
        required: true
      as_of:
        description: Information cutoff (YYYY-MM-DD)
        required: true
jobs:
  nowcast:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Run Canadian CPI nowcast (--live)
        run: |
          PYTHONPATH=. python3 -m scripts.canadian_cpi_release nowcast \
            --release "${{ inputs.release }}" \
            --as-of "${{ inputs.as_of }}" \
            --out ./artifacts/ca_cpi \
            --live
      - uses: actions/upload-artifact@v4
        with:
          name: ca-cpi-nowcast
          path: artifacts/ca_cpi/
```

No schedule, `repository_dispatch`, `workflow_run`, cron, LLM calls, auto-merge, or deployment.
