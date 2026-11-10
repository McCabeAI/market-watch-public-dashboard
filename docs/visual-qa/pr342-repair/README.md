# PR #342 visual repair verification (2026-11-10)

Captured from offline fixtures after the legend/scoreboard layout repair.

| File | Viewport | What it checks |
| --- | --- | --- |
| `temp-legend-iphone-320.png` | 320×900 | Five legend tiles in **3 columns** (3+2), vertical swatch, label above value, no bordered boxes |
| `temp-legend-iphone-375.png` | 375×900 | Same layout at 375px |
| `temp-legend-iphone-390.png` | 390×900 | Same layout at 390px |
| `temp-legend-desktop-1280.png` | 1280×900 | Desktop legend retains 3-column grid |
| `scoreboard-iphone-390.png` | 390×900 | Six composite cards primary; legacy equal-weight table inside **closed** `<details>`; per-card **View country trends** jump |
| `scoreboard-desktop-1280.png` | 1280×900 | Same overview at desktop width |

HTML fixtures (`_legend_mini.html`, `_scoreboard_fixture.html`) are local capture inputs only.

Regenerate (optional):

```bash
python3 -m pip install playwright  # if missing
python3 -m playwright install chromium
# then rerun the capture helpers in the agent commit or rebuild fixtures manually
```
