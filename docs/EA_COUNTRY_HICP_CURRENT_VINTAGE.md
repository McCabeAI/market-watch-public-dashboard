# EA country HICP current vintage

## Two-stage vintage

Country-level HICP context series (`EA.Inflation.hicp_de`, `hicp_fr`, `hicp_it`, `hicp_es`, `hicp_pt`) reconcile **national official** flash/preliminary prints with **Eurostat** `PRC_HICP_MINR` finals for the same reference month.

Vintage ranks (higher wins for a given period in the observation store and in projection history):

| Rank | Vintage | Meaning |
|------|---------|---------|
| 3 | `eurostat_final` | Eurostat statistics API final for `geo=DE|FR|IT|ES|PT` |
| 2 | `national_final` | National publisher definitive HICP |
| 1 | `national_preliminary` | National flash / provisional HICP |

Legacy rows with `revision_status=final` and a Eurostat `source_url` are treated as rank 3 even when `vintage` is `latest_available`.

Reconciliation keeps **one point per period**: Eurostat final always replaces a national point for that month; national points are pre-collapsed so `national_final` beats `national_preliminary`. A later lower-rank print does not replace a higher-rank row. The same rank with a different value is a revision and the later retrieval wins. The same value at a higher rank updates that row in place instead of storing a second observation. On that upgrade the row's `raw_sha256` becomes the hash of the higher-rank artifact, and the previous digest is kept as an alias.

## Provenance

Each stored observation's `raw_sha256` is the SHA-256 of the response body that was parsed into that observation. Eurostat months fingerprint the Eurostat statistics JSON. A national flash fingerprints that statistics office's press page or BDM document. Points do not inherit the payload-level digest, and a reconciled point list is never hashed in place of those bodies. A national row that was previously stored under another source's digest is rewritten to its own artifact hash when that same source is fetched again. The economic value, vintage rank, and source URL stay as they were.

## Official sources (parsed field)

Only **harmonised / HICP** year-on-year rates are parsed—not national CPI (IPC, VPI, etc.).

| Country | Listing URL | Parsed content |
|---------|-------------|----------------|
| Germany | [Destatis CPI/HICP theme](https://www.destatis.de/DE/Themen/Wirtschaft/Preise/Verbraucherpreisindex/_inhalt.html) | Press release: *Harmonisierter Verbraucherpreisindex* … % zum Vorjahresmonat |
| France | [INSEE Informations rapides Solr](https://www.insee.fr/fr/solr/consultation) + [BDM SDMX 011812232](https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/011812232?lastNObservations=6) | Press table row **Ensemble IPCH** (last numeric cell). The release title's month is the reference period. A title that says the print is provisional stays preliminary even when the body schedules a later *résultats définitifs*. BDM HICP YoY is included when the series title is HICP/harmonisé. |
| Italy | [Istat prezzi al consumo tag](https://www.istat.it/tag/prezzi-al-consumo/) | Newest `prezzi-al-consumo-dati-provvisori` release, absolute or relative href. IPCA rate before *su base annua* (not monthly %, not NIC). |
| Spain | [INE notas de prensa](https://www.ine.es/dyngs/Prensa/notasPrensa.htm) | Latest `adIPC` note (`/dyngs/Prensa/adIPCMMYY.htm` or the `/es/` variant). *variación anual del indicador adelantado del IPCA* (not IPC). |
| Portugal | [INE destaques Prices theme](https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_destaques&DESTAQUEStema=5414296&xlang=pt) | Newest highlight whose anchor says the CPI homologous rate *terá* (the flash), then the IHPC *variação homóloga* sentence on that page (not the IPC title). |

Eurostat endpoint on each catalog row remains the statistics URL (`PRC_HICP_MINR`, country `geo`).

## Scoring

`EA.Inflation.headline` and `EA.Inflation.underlying` (EA21) are the only **scored** EA inflation inputs. The five country HICP rows stay `role=context`, `weight=0`, and `score_input=false`.

No reference month (including September 2026) is hard-coded in ingestion logic; rates and periods come from publisher artifacts at fetch time.

## Repair provenance

This repair stays on pull request 152. It does not change EA21 headline or underlying inputs, score weights, Trader Room, books and P&L, accepted decisions, ACP, or the 20-call investment graph.

| Stage | Model | What it owned |
|-------|--------|----------------|
| Source and architecture | Grok 4.7 | Official primary sources, vintage ranks, and the rule that Eurostat final replaces the national print for the same month |
| Implementation | Composer 2.5 (`bc-d12ead33-e6d3-52c3-9ea7-1186c6f1ccab`) | Module, adapter dispatch, runner append, projection collapse, fixtures |
| Adversarial review | Grok 4.7 (`bc-85c06a23-69b2-5ed7-8b99-80238c37a5cc`) | Failed the first tree: Portugal could bind the flash to an earlier dateline month, and a France Solr loop reused `_attempt` and could recurse |
| Integration repair | Grok 4.7 | Those two defects, Italy/Spain/Portugal discovery against the live listing HTML, and equal-rank Eurostat revisions |
| Provenance repair | Grok 4.7 | Each observation's `raw_sha256` is the body that produced it. A later same-source fetch rewrites a digest that belongs to a different source URL. |

The Portugal flash month is read from tag-stripped headline text, with the same plain-text cap that stops before the year-ago comparison.
