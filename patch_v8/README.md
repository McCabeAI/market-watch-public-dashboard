# v8 temperature-score restoration

This patch restores the 1–100 Temperature Inputs interface that appeared in the earlier v2 dashboard.

Recovered v2 scores:

| Country | Inflation | Labor | Activity | Consumer |
| --- | ---: | ---: | ---: | ---: |
| United States | 72 | 75 | 69 | 74 |
| Canada | 55 | 38 | 66 | 45 |
| Australia | 82 | 50 | 54 | 48 |
| New Zealand | 80 | 32 | 47 | 38 |

Display mapping:

- 1–20: Cold
- 21–40: Cool
- 41–60: Neutral
- 61–80: Warm
- 81–100: Hot

These are recovered prototype interface scores, not canonical Market Watch country baselines. Direction remains a separate dimension and carries more trading weight under the research methodology.

Deployment applies this patch only after the exact v7 artifact has passed its byte-count and SHA-256 gate. The final v8 artifact must be exactly 146,902 bytes with SHA-256 `c3a962f36e6fb3bff5fa251a5f5df065d753bc865f7054242af80b64b03312d7`.
