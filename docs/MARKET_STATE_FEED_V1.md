# Market State Feed V1

Status: ACTIVE STANDALONE RESEARCH FEED

This is the path-of-least-resistance daily market-data feed for Market Watch. It is independent of the GitHub Pages dashboard build, Supabase persistence, paid APIs, and repository secrets.

The generator produces a compact JSON research snapshot. It is not executable pricing.

## Command

Trader Room agents and the weekday workflow use the same command:

```bash
PYTHONPATH=. python scripts/market_state.py --output /tmp/market-state/market-state.json
```

Optional test override:

```bash
PYTHONPATH=. python scripts/market_state.py --output /tmp/market-state/market-state.json --today 2026-09-17
```

If a host can download the official RBNZ B2 xlsx but Python cannot, pass the same official file through:

```bash
PYTHONPATH=. python scripts/market_state.py --output /tmp/market-state/market-state.json --nz-workbook /tmp/market-state/hb2-daily-close.xlsx
```

Dependency (RBNZ workbook only):

```bash
python -m pip install -r requirements-market-state.txt
```

No environment variables or API keys are required. Do not set `TWELVE_DATA_API_KEY`.

Exit codes:

- `0`: required sources parsed, calculations validated, JSON written
- `2`: hard failure printed as `MARKET STATE ERROR: ...`

A failed run writes no substitute packet. Do not invent yields, crosses, or lookbacks.

## Output contract

The JSON object always contains:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `generated_at` | UTC timestamp of the run (`...Z`) |
| `window_start` | Inclusive history start used for context (~5 years) |
| `status` | `ok` if every required source is within its expected publication lag; `stale` if one or more sources are older than that lag but still present |
| `stale_sources` | List of stale or blocked source keys, else `[]` |
| `unavailable_sources` | Official sources that could not be fetched (currently NZ-only), else `[]` |
| `rates` | `US`, `CA`, `AU`, `NZ` blocks |
| `rate_rv` | 15 matching-tenor spreads |
| `policy_paths` | US/Canada/Australia overnight benchmarks and policy-pricing context |
| `tradable_rate_curves` | Paper-tradable SOFR (`SR3`), CORRA (`CRA`) and AONIA (`IB`) futures strips |
| `official_curves` | Supplemental US/Canada/Australia government zero/forward curves for bond-curve expressions |
| `fx` | 45 G10 crosses from one ECB fixing |
| `positioning` | CFTC trader-class positioning plus CME daily futures/options open-interest context |
| `sources` | Name, public URL, download URL, observation date, status |
| `method` | Provenance of the calculation, including `credentials_required: []` |

Each country rates block includes:

- `latest_observation`, `age_days`, `status`
- `tenors`: latest yield; 1D/5D/1M/3M/6M/1Y basis-point changes; 1Y percentile/z-score; 5Y percentile/z-score when the fetched sample is long enough; and mechanically selected prior 1-month move analogs with subsequent 1M/3M outcomes
- `curves`: `2s10s` and `5s10s` in basis points, with the same change/distribution fields plus prior-move analogs

Required tenors:

- US: 2Y, 5Y, 10Y, 30Y
- Canada: 2Y, 5Y, 10Y, LONG
- Australia: 2Y, 5Y, 10Y
- New Zealand: 2Y, 5Y, 10Y

`rate_rv` keys are `{A}-{B}_{tenor}` for `CA-US`, `AU-US`, `NZ-US`, `AU-NZ`, `CA-AU` at 2Y, 5Y and 10Y. Spreads use the latest exact common observation date. One country is never forward-filled to match another.

Each FX pair includes spot, 1D/5D/1M/3M percent returns, 20D/60D annualized realized vol, and 1Y/5Y percentile or z-score when history supports it. Positive return means the base currency appreciated against the quote under the displayed pair key.


### Policy-path block

`policy_paths` is the monetary-policy **context** layer. It answers what the market is pricing around the current SOFR/CORRA/AONIA benchmark before a trader chooses an expression.

- **Canada:** Bank of Canada CORRA plus Montréal Exchange COA/CRA context.
- **United States:** New York Fed SOFR plus One-Month SOFR (`SR1`) context.
- **Australia:** RBA F1 AONIA, short OIS/bank-bill context and ASX cash-rate data.

This block is not the definition of the paper trading universe.

### Tradable rates curves

`tradable_rate_curves` is the primary short-rate trading universe used by Trader Room:

- **SOFR:** CME Three-Month SOFR futures, product `SR3`.
- **CORRA:** Montréal Exchange Three-Month CORRA futures, product `CRA`.
- **AONIA:** ASX 30-Day Interbank Cash Rate futures, product `IB`.

Each contract is marked in implied-rate space as `100 - futures price`. Public settlement/reference data are sufficient for the paper book; they are not represented as executable bid/offer quotes.

A position is permanently associated with the curve family and construction used at entry. Subsequent adds, reductions, closes and daily marks must replay that same family and expression. A bond trade is never silently migrated to SOFR/CORRA/AONIA and a futures-curve trade is never migrated to a government curve.

Forward windows and fwd-fwds on these curves use explicit contracts. Example:

```json
{"type":"futures_strip_average","curve_id":"SOFR","expiries":["2028-03","2028-06","2028-09","2028-12"]}
```

Optional positive weights may be supplied. The trader or permitted subagent chooses the contracts; deterministic code owns the mark arithmetic and replay.

### Supplemental government zero/forward curves

`official_curves` retains official government zero/forward data as a separate bond-curve family:

- **United States:** Federal Reserve staff Svensson nominal Treasury curve.
- **Canada:** Bank of Canada Government of Canada zero-coupon curve when the legacy download endpoint is reachable.
- **Australia:** RBA F17 analytical zero-coupon series.

These curves can support an explicitly selected government-bond curve or bond-curve forward expression. They are **supplemental**: failure of one of these feeds does not invalidate the SOFR/CORRA/AONIA trading universe, and they are not used to manufacture a substitute swap/OIS curve. Swap-spread trading is out of scope until both legs are deliberately supported.

`historical_move_analogs` are mechanical nearest prior 1-month moves from the retained history, with subsequent 1M/3M changes. They provide candidate episodes and math; advocates still must explain event/regime similarities and differences before calling an episode comparable.

The `positioning` block is deterministic and credential-free. CFTC TFF futures-only data is the ownership/crowding anchor for standard G10 FX futures and key US Treasury futures. For each mapped contract it records total open interest plus Dealer, Asset Manager, Leveraged Funds, Other Reportable and Non-Reportable long/short/net positions. Net positions are normalized as percent of open interest and contextualized with weekly change plus 1Y/3Y percentile and z-score. The selected CFTC market name and contract code are retained in the packet for auditability.

CME's public Volume & Open Interest service is a higher-frequency overlay. It records daily open interest and volume for standard CME G10 FX futures plus aggregate options open interest/volume on each product. The collector keeps a rolling 30-observation OI history, daily OI change, 30-day percentile/z-score, and options-to-futures OI ratio. CME data does not identify trader class and is not substituted for CFTC ownership data. The CME collector is best-effort: CME currently returns HTTP 403 to GitHub-hosted runners even when the request matches CME's public page XHR, so the production packet may mark CME OI `unavailable` with the exact error while retaining the complete CFTC positioning block. No proxy or third-party mirror is used.

The 10 G10 currencies are `EUR, GBP, AUD, NZD, USD, CAD, CHF, NOK, SEK, JPY`. Pair keys are `BASEQUOTE` in that order, so the matrix is exactly 45 unique crosses (`EURUSD`, `USDJPY`, `AUDNZD`, `NOKSEK`, ...).

`method.fx_source` is always `ecb_euro_reference_crosses`. `method.model_calls` is always `0`.

Null lookbacks stay null. A missing US, Canada, Australia, or ECB FX source, tenor, currency, overlapping non-NZ spread date, or sanity-gate failure is a hard error. A blocked official RBNZ download marks `rates.NZ` and NZ-dependent `rate_rv` entries (`NZ-US`, `AU-NZ`) as `unavailable` with explicit `error` / `reason` fields and does not stop the packet.

## Sources

| Block | Authority | Notes |
| --- | --- | --- |
| US rates | U.S. Treasury daily par yield curve | Daily official bond curve |
| US policy context | New York Fed SOFR + One-Month SOFR (`SR1`) | Overnight benchmark and near-term policy context |
| US tradable curve | CME Three-Month SOFR (`SR3`) | Quarterly CME SR3 strip carried on eSignal's public delayed quote board because CME rejects GitHub-hosted runners |
| US government zero/forward | Federal Reserve nominal Treasury Svensson curve | Supplemental bond-curve analytics |
| CA rates | Bank of Canada Valet benchmark bonds | Official 2Y/5Y/10Y/LONG bond yields |
| CA policy context | Bank of Canada CORRA + MX COA/CRA | Overnight benchmark and policy context |
| CA tradable curve | Montréal Exchange Three-Month CORRA (`CRA`) | Quarterly CORRA futures strip |
| CA government zero curve | Bank of Canada zero-coupon curve | Supplemental when the legacy download endpoint is reachable |
| AU rates | RBA F2 government-bond yields | Assessed government-bond curve |
| AU policy context | RBA F1 | AONIA, short OIS and bank-bill context |
| AU tradable curve | ASX 30-Day Interbank Cash Rate (`IB`) | AONIA-linked monthly futures strip |
| AU government zero/forward | RBA F17 | Supplemental discount factors, forwards and zero yields |
| NZ rates | RBNZ B2 wholesale interest rates | Best-effort context only; blocked source is reported rather than substituted |
| FX | ECB euro foreign-exchange reference rates | Same-fixing EUR legs; deterministic G10 crosses |
| Positioning ownership | CFTC TFF Futures Only | Weekly trader-class positions |
| Positioning OI overlay | CME public Volume & Open Interest | Supplemental daily product-level OI/volume |

Expected publication lag before `status=stale`: US/CA/NZ/FX 4 calendar days; AU 12 calendar days. Observations older than 21 calendar days fail the run.

## Workflow

`.github/workflows/daily-market-state.yml` runs weekdays at 12:30 UTC, on `workflow_dispatch`, and on PRs that touch the generator. It:

1. runs the deterministic unit tests
2. runs `python scripts/live_market_state_smoke.py` against live Treasury, BoC, RBA and ECB sources
3. runs the generator, including the CFTC and CME positioning collectors, and uploads `/tmp/market-state/market-state.json` as artifact `market-state` with 5-day retention (NZ or a supplemental positioning source may be `unavailable` with explicit provenance)

GitHub-hosted runners often receive HTTP 403 from `rbnz.govt.nz` (Cloudflare). The workflow does not substitute a vendor or media feed; NZ rates and NZ-dependent RV spreads are emitted as `unavailable` while US/CA/AU/ECB remain required.

The GitHub Pages deploy workflow also runs the same generator into `_site/market-state.json` when live official sources respond, and serves it to the dashboard **Market Data** tab (`patch_v12/`). Pages generation is best-effort (`continue-on-error`) so a live-source outage does not block the dashboard deploy. The daily market-state workflow remains the required packet producer. It does not write to Supabase and does not read repository secrets.

## Trader Room use

Immediately before a debate, generate and freeze the market-state packet. Advocates use `policy_paths` to understand what is priced, then choose an actual rates expression from `tradable_rate_curves` or the sovereign bond curves. A full Trader Room requires SOFR/SR3, CORRA/CRA and AONIA/IB to be present before model budget is spent.

The selected curve family is part of the trade definition and remains the mark source until close. Historical move analogs, positioning and cross-asset evidence remain context; they do not replace the tradable mark. Preserve source names, observation dates, `generated_at`, and staleness/provenance. Never fabricate a missing curve or silently substitute another family.

## Opportunity monitor extension (2026-09-18)

Every normal generator call now includes `cross_assets` source metadata and `opportunities` analytics. The core schema stays backward compatible. See [MARKET_OPPORTUNITIES.md](MARKET_OPPORTUNITIES.md) for added coverage, publication lags, screen formulas and limitations. The core packet status describes the original required rates/FX sources; `cross_assets.status` independently exposes partial broader coverage. Added-source failures never become zero-price or fabricated signals.
