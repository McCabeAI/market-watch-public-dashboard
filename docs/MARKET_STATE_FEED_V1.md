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
| `fx` | 45 G10 crosses from one ECB fixing |
| `positioning` | CFTC trader-class positioning plus CME daily futures/options open-interest context |
| `sources` | Name, public URL, download URL, observation date, status |
| `method` | Provenance of the calculation, including `credentials_required: []` |

Each country rates block includes:

- `latest_observation`, `age_days`, `status`
- `tenors`: latest yield; 1D/5D/1M/3M basis-point changes; 1Y percentile/z-score; 5Y percentile/z-score when the fetched sample is long enough
- `curves`: `2s10s` and `5s10s` in basis points, with the same change/percentile/z-score fields

Required tenors:

- US: 2Y, 5Y, 10Y, 30Y
- Canada: 2Y, 5Y, 10Y, LONG
- Australia: 2Y, 5Y, 10Y
- New Zealand: 2Y, 5Y, 10Y

`rate_rv` keys are `{A}-{B}_{tenor}` for `CA-US`, `AU-US`, `NZ-US`, `AU-NZ`, `CA-AU` at 2Y, 5Y and 10Y. Spreads use the latest exact common observation date. One country is never forward-filled to match another.

Each FX pair includes spot, 1D/5D/1M/3M percent returns, 20D/60D annualized realized vol, and 1Y/5Y percentile or z-score when history supports it. Positive return means the base currency appreciated against the quote under the displayed pair key.

The `positioning` block is deterministic and credential-free. CFTC TFF futures-only data is the ownership/crowding anchor for standard G10 FX futures and key US Treasury futures. For each mapped contract it records total open interest plus Dealer, Asset Manager, Leveraged Funds, Other Reportable and Non-Reportable long/short/net positions. Net positions are normalized as percent of open interest and contextualized with weekly change plus 1Y/3Y percentile and z-score. The selected CFTC market name and contract code are retained in the packet for auditability.

CME Daily Bulletin data is a higher-frequency overlay. It records previous-trade-date open interest and daily OI change for standard CME G10 FX futures, plus call/put/total OI and put/call OI ratio for the major monthly FX option products where the bulletin exposes them. CME data does not identify trader class and is not substituted for CFTC ownership data.

The 10 G10 currencies are `EUR, GBP, AUD, NZD, USD, CAD, CHF, NOK, SEK, JPY`. Pair keys are `BASEQUOTE` in that order, so the matrix is exactly 45 unique crosses (`EURUSD`, `USDJPY`, `AUDNZD`, `NOKSEK`, ...).

`method.fx_source` is always `ecb_euro_reference_crosses`. `method.model_calls` is always `0`.

Null lookbacks stay null. A missing US, Canada, Australia, or ECB FX source, tenor, currency, overlapping non-NZ spread date, or sanity-gate failure is a hard error. A blocked official RBNZ download marks `rates.NZ` and NZ-dependent `rate_rv` entries (`NZ-US`, `AU-NZ`) as `unavailable` with explicit `error` / `reason` fields and does not stop the packet.

## Sources

| Block | Authority | Notes |
| --- | --- | --- |
| US rates | U.S. Treasury daily par yield curve | Daily official CSV |
| CA rates | Bank of Canada Valet benchmark bonds | Official `bond_yields_benchmark` group (`BD.CDN.2YR/5YR/10YR/LONG.DQ.YLD`) |
| AU rates | RBA F2 government-bond yields | Assessed closing yields; research context; typically weekly with a two-business-day lag |
| NZ rates | RBNZ B2 wholesale interest rates | Official `hb2-daily-close.xlsx`; indicative government-bond closes; one-day publication lag. A Cloudflare block marks NZ unavailable in the packet; no vendor mirror. |
| FX | ECB euro foreign-exchange reference rates | Official Data Portal SDMX daily `EXR` series; same-fixing EUR legs only; not executable prices. Combined G10 query first; per-currency SDMX fallback on 5xx/timeout. No vendor substitute. |
| Positioning ownership | CFTC Traders in Financial Futures (TFF), Futures Only | Weekly trader-class positions. Core crowding source for the Positioning Cynic; official public API dataset `gpe5-46if`. |
| Positioning OI overlay | CME Group Daily Bulletin FX Futures and Options | Previous-trade-date official exchange OI/change plus major monthly options call/put OI. Supplemental to CFTC trader identity. |

Expected publication lag before `status=stale`: US/CA/NZ/FX 4 calendar days; AU 12 calendar days. Observations older than 21 calendar days fail the run.

## Workflow

`.github/workflows/daily-market-state.yml` runs weekdays at 12:30 UTC, on `workflow_dispatch`, and on PRs that touch the generator. It:

1. runs the deterministic unit tests
2. runs `python scripts/live_market_state_smoke.py` against live Treasury, BoC, RBA and ECB sources
3. runs the generator, including the positioning collectors, and uploads `/tmp/market-state/market-state.json` as artifact `market-state` with 5-day retention (NZ or a supplemental positioning source may be `unavailable` with explicit provenance)

GitHub-hosted runners often receive HTTP 403 from `rbnz.govt.nz` (Cloudflare). The workflow does not substitute a vendor or media feed; NZ rates and NZ-dependent RV spreads are emitted as `unavailable` while US/CA/AU/ECB remain required.

The GitHub Pages deploy workflow also runs the same generator into `_site/market-state.json` when live official sources respond, and serves it to the dashboard **Market Data** tab (`patch_v12/`). Pages generation is best-effort (`continue-on-error`) so a live-source outage does not block the dashboard deploy. The daily market-state workflow remains the required packet producer. It does not write to Supabase and does not read repository secrets.

## Trader Room use

Immediately before a debate, run the command above and attach the JSON as research/reference `market_levels` / `rates_and_policy` evidence. The complete `positioning` block travels with the same frozen packet, so Positioning Cynic and other seats can use CFTC crowding and CME OI context without private web fetches. Preserve source names, URLs, observation dates, `generated_at`, and `stale_sources`. Do not treat ECB crosses or official yields as tradable quotes. If the generator exits `2`, record the hard failure as a known gap and do not fabricate replacements.

## Opportunity monitor extension (2026-09-18)

Every normal generator call now includes `cross_assets` source metadata and `opportunities` analytics. The core schema stays backward compatible. See [MARKET_OPPORTUNITIES.md](MARKET_OPPORTUNITIES.md) for added coverage, publication lags, screen formulas and limitations. The core packet status describes the original required rates/FX sources; `cross_assets.status` independently exposes partial broader coverage. Added-source failures never become zero-price or fabricated signals.
