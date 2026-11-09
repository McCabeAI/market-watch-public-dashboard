# Nov 9 derived decision exposure (read-only)

**Scope:** `data/overnight/runs/overnight-20261109/reviews/review-001/` trader and PM outputs.  
**Evidence:** `evidence_snapshot.json` was not modified; `packet_sha256` remains `36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11`.

## Search targets

Corrupt policy-meeting figures: `9.2639`, `538.89`, `516.83`, `6.035`, `214.63`, `-131.98`.  
Decision dates: US `2027-03-17`, AU `2026-12-08`, BoC `2027-12-08`.

## Findings

A read-only JSON scan found the corrupt numerics only inside the frozen **`evidence_snapshot.json`** embed at `families.market_state.data.policy_meeting_prices` (US Mar 2027 phantom post/cum/inc, CA BoC path outliers, AU Sep 2027 cumulative `-131.98`). **`trader_review.json`**, **`scheduled_output.json`**, and **`review.json`** in review-001 contain **none** of those figure strings and do not reference the listed decision dates in trader seat payloads. No PM packet under review-001 (`pm_memory/`, review-scoped trader outputs) cited the corrupt figures; the only PM-adjacent hit outside the evidence tree was `data/pm/review_packets/chatgpt/latest.json`, which mentions `2027-03-17` only as a generic policy-calendar reference without the phantom rates. **No trader seat or PM decision artifact in review-001 was found to have consumed the corrupt US/AU/BoC priced rows for trading or scheduling text.**
