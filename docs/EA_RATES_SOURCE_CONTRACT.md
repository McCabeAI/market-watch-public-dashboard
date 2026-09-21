# Euro-area rates / policy source contract (P3 / I4)

Status: **pinned for isolated collector** `scripts/euro_area_rates_data.py` (parent integrates into `market_state.py`).

## Scope boundaries

| Family | Role | Must not mix into |
|--------|------|-------------------|
| Bundesbank Bund yields (`rates.EA`) | German cash benchmark 2Y/5Y/10Y/30Y | Fragmentation or ECB curves |
| ECB €STR + Eurex FST3 | Policy path / short-rate futures | Bund cash tenors |
| ECB YC Svensson spots | `official_curves.EA` analytical proxy | Bund cash tenors |
| IT/FR/ES vs DE spreads | `fragmentation` context block | `rates.EA` tenor dict |

Germany is the **EUR cash-rates benchmark only**. EA temperature and `rates.EA` are not the same as peripheral spreads.

---

## 1. German sovereign benchmark yields (`rates.EA`)

**Authority:** Deutsche Bundesbank, time series database BBSSY (daily federal securities yields, percent, comma decimals).

| Tenor | Series key |
|-------|------------|
| 2Y | `BBSSY.D.REN.EUR.A610.000000WT0202.A` |
| 5Y | `BBSSY.D.REN.EUR.A620.000000WT0505.A` |
| 10Y | `BBSSY.D.REN.EUR.A630.000000WT1010.A` |
| 30Y | `BBSSY.D.REN.EUR.A640.000000WT3030.A` |

**API (CSV):**

```
https://api.statistiken.bundesbank.de/rest/data/BBSSY/{series_key}?format=csv&startPeriod=YYYY-MM-DD&endPeriod=YYYY-MM-DD
```

**Example:**

```
https://api.statistiken.bundesbank.de/rest/data/BBSSY/D.REN.EUR.A610.000000WT0202.A?format=csv&startPeriod=2024-01-01&endPeriod=2024-12-31
```

**Parser:** `parse_bundesbank_csv` → `{date: yield_percent}`; missing/`.` rows skipped.

The REST CSV dialect follows `Accept-Language`. German locale is semicolon-separated with comma decimals (`2,45`). English locale (including `scripts/market_state.py` `fetch_bytes`, which sends `Accept-Language: en-US`) is comma-separated with period decimals (`2.45`). The parser accepts both.

**Freshness:** `STALE_AFTER_DAYS = 4` (aligned with US Bund-equivalent daily cadence).

**Failure:** Missing 2Y/5Y/10Y/30Y after fetch → `EuroAreaRatesError`.

---

## 2. ECB €STR overnight

| Field | Value |
|-------|--------|
| Series key | `EST.B.EU000A2X2A25.WT` |
| Description | Euro short-term rate, volume-weighted trimmed mean, overnight unsecured |
| Units | Percent per annum |

**API (CSV):**

```
https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?format=csvdata&startPeriod=YYYY-MM-DD&endPeriod=YYYY-MM-DD
```

**Parser:** `parse_ecb_estr_csv` on ECB SDMX `csvdata` export.

---

## 3. Eurex 3M €STR futures (FST3)

**Contract:** Three-Month €STR futures, product code **FST3**.

**Quotation (STIR convention):** futures price = **100 − interest rate** (percent); implied rate = `100 - price`. Same convention as other Eurex short-term interest rate futures; see [Eurex contract specifications](https://www.eurex.com/ex-en/rules-regs/eurex-rules-and-regulations-contract-specifications) and the [FST3 product page](https://www.eurex.com/ex-en/markets/int/fixing/3-month-estr-futures-FST3).

**URLs tried from GitHub-hosted / cloud agents (2026-09-21):**

| URL | Result |
|-----|--------|
| `https://www.eurex.com/ex-en/markets/int/fixing/3-month-estr-futures-FST3` | HTML marketing page only |
| `https://www.eurex.com/ex-en/data/trading-files/product-and-price-report` | HTML navigation |
| `https://www.eurex.com/ex-en/data/market-statistics/settlement-prices/FST3` | HTML |
| `https://www.eurex.com/api/v1/marketdata/settlement/FST3` | 404 |
| `https://www.eurex.com/api/v2/marketdata/statistics/FST3/settlement` | 404 |

**Tradable declaration:** **NO** — no credential-free settlement CSV/JSON was retrieved reliably in this environment. Collector sets `tradable_curve.status = unavailable` and does **not** invent marks. Parser `parse_fst3_settlement_csv` exists for deterministic replay when a feed is pinned.

---

## 4. ECB euro-area analytical yield curve (`official_curves.EA`)

**Dataset:** ECB Financial market data – yield curve (**YC**), Svensson model, daily business week.

| Curve | SDMX prefix (spot keys `SR_2Y`, `SR_5Y`, `SR_10Y`, `SR_30Y`) |
|-------|------------------------------------------------------------------|
| All euro-area governments, all ratings | `B.U2.EUR.4F.G_N_C.SV_C_YM` |
| AAA only | `B.U2.EUR.4F.G_N_A.SV_C_YM` |

**Example (2Y spot, all ratings):**

```
https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_2Y?format=csvdata&startPeriod=YYYY-MM-DD&endPeriod=YYYY-MM-DD
```

**Compounding:** Continuously compounded zero yields (percent); see [technical notes](https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf).

**Not the same as:** Bundesbank Bund cash yields (different instrument and fitting methodology).

---

## 5. Fragmentation (I7) — IT/FR/ES vs Germany

**Spread definition:** `peripheral_yield − german_yield` on **exact common dates** only (no forward fill).

**German leg:** Bundesbank BBSSY (same as `rates.EA`).

**Peripheral legs (pinned / status):**

| Country | 2Y | 5Y | 10Y |
|---------|----|----|-----|
| IT | unavailable | unavailable | Eurostat MCBY monthly |
| FR | unavailable | unavailable | Eurostat MCBY monthly |
| ES | unavailable | unavailable | Eurostat MCBY monthly |

**10Y source (machine-readable):**

- Dataset: `irt_lt_mcby_m` — EMU convergence criterion bond yields (~10Y), monthly.
- API: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/irt_lt_mcby_m?geo=IT&geo=FR&geo=ES&geo=DE&format=JSON`
- Dates mapped to **month-end** for alignment across countries.

**2Y / 5Y:** No credential-free **daily** official series pinned (ECB per-country `YC.B.IT...` keys return 404; AFT France behind Cloudflare; Banca d'Italia SDMX not exposed). Marked `unavailable` — not vendor-filled.

**Sources attempted and rejected:**

- ECB `YC/B.IT.EUR...` / `B.FR` / `B.ES` — 404 no series
- Eurostat `irt_lt_gby_m` — not disseminated
- Banque de France `webstat.banque-france.fr` — no stable public CSV without session
- Banco de España `be1901.csv` — monthly mortgage/reference rates, not sovereign 2Y/5Y/10Y cash
- AFT `taux_10_ans.csv` — Cloudflare challenge in cloud runners

---

## Module API (parent import)

```python
class EuroAreaRatesError(RuntimeError): ...

def parse_bundesbank_csv(text) -> dict[date, float]
def fetch_ea_bund_rates(start, end, fetch_bytes=...) -> dict[str, dict[date, float]]

def fetch_estr_history(start, end, fetch_bytes=...) -> dict[date, float]

def collect_ea_policy_path(today, fetch_bytes) -> dict
def collect_ea_official_curve(today, fetch_bytes) -> dict
def collect_ea_fragmentation(today, fetch_bytes) -> dict

def validate_ea_rates_bundle(payload) -> None
```

**Policy path shape:** `benchmark` (€STR), `contracts_3m` (FST3 when available), `tradable_curve` (ESTR family; unavailable until FST3 feed works).

---

## Convention gotchas

- **Bundesbank CSV:** `;` separator, European decimal comma, header metadata rows before data.
- **ECB YC vs Bund:** fitted Svensson **spot** zeros vs **cash** benchmark on latest Federal security; levels differ.
- **ECB YC compounding:** continuous (not Act/360 money-market).
- **FST3:** price quoted as 100 − rate; settlement rate is compounded €STR over 3 months per contract specs (do not mix with €STR overnight level without contract math).
- **Fragmentation 10Y:** Eurostat MCBY is **monthly**; Bund leg is **daily** — spreads use month-end dates where both exist.

---

## Tests

```bash
PYTHONPATH=. python3 -m unittest tests.test_euro_area_rates_data
```

Optional live smoke: `EA_RATES_LIVE=1 PYTHONPATH=. python3 -m unittest tests.test_euro_area_rates_data.EuroAreaRatesLiveSmoke`
