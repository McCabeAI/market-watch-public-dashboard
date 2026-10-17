# Phase 2 independent challenge

Checked the Phase 2 spec against the Phase 1 evidence files and the news-engine modules. This note binds the implementation.

## Safe to implement

- Non-required CNBC news sitemap `https://www.cnbc.com/sitemap_news.xml` plus optional Bing `site:cnbc.com` credit query. `REQUIRED_SOURCES` stays `bloomberg` and `reuters`. No Bloomberg markets firehose, no RBNZ URL, no CNBC section RSS pile.
- `REUTERS_CREDIT_QUERY` may add CoreWeave, CDS, and "credit default". That does not recover the 15 Oct CNBC URL.
- BoJ/BoE allow-list phrases: `bank rate`, `money market operations`, `complementary deposit facility`, `financial stability`, `intervention`, `official cash rate`. The three locked title-filter fixtures stay as they are.
- Subject suppress only when Vietnam+GDP, India trade-gap/import-bill, or Indonesia fire has no transmission role. Bare `oil` is not that role. The India import-bill fixture stays suppress.
- Remove both CoreWeave name-only shortcuts. The CDS distress headline stays `show` / `ai_capex_credit`. The AI-scare headline does not.
- Cluster alias `ormuz` → `hormuz`. Different facets do not merge. One-sided `coreweave` does not merge with Nvidia boilerplate.
- `publication_rows` is a sidecar on the shadow report. Accepted-news envelope keys stay unchanged.

## Defects the spec must not ship

- Gate 1 is not passed by a forward sitemap plus an injected headline. Wayback CDX for the CNBC news sitemap from 15–17 Oct 2026 was empty. Article HTML captures, including `20261015165635` inside the 24-hour window, are not discovery-feed evidence.
- Recall without a G10/rates score still drops Bank Rate, gilt sales, the money-market guideline, and OCR wording as `hold-for-review`. Bare `monetary policy` would also recall the 2027 MPC calendar.
- `palm oil` satisfies `\boil\b`. A fire story that says palm-oil exports would escape suppression unless the oil token ignores palm oil.
- A slot explainer that labels the research top-24 as `published`, or that copies the slice math into a second formula, does not explain the webpage.
- Same-facet clustering with four shared tokens is required for the CDS pair at Jaccard 0.545. It is not proof that every distinct incident is separated.

## Gate verdicts before the code change

| Gate | Verdict |
| --- | --- |
| 1. CoreWeave 15 Oct discoverable in-window from an implemented feed | UNRESOLVED BLOCKER |
| 2. Vietnam GDP and India trade gap suppressed; India oil-supply shock retained | Implementable. Not a pass until the palm-oil exclusion is tested |
| 3. BoJ/BoE/RBNZ releases not dropped only by the title filter | Not a pass. BoJ/BoE need a score, not only recall. RBNZ feed unverified (HTTP 403) |
| 4. Final 6/3/12 webpage trail | Not a pass until `published` is the refresh partition |
| 5. Distinct events clustered apart | Partial after the facet tests. Same-facet residual remains |
| 6. News engine only | Holds if ACP, workflows, and `accepted_public_news.json` stay untouched |
