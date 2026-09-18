from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
html = path.read_text()

research_start = '<div class="news-intro">\n<div class="panel"><div class="stitle">Central Bank Research · 30-day window</div>'
research_list_start = '<div class="news-list">'
research_list_end = '<div class="coverage">'
if html.count(research_start) != 1 or html.count(research_list_start) != 1 or html.count(research_list_end) != 1:
    raise SystemExit("research section anchors changed")

html = html.replace(
    '<p><b>Window:</b> 10 Aug–8 Sep 2026. Official central-bank publications only. The feed prioritizes macro, rates and cross-asset relevance; administrative, personnel and narrow regulatory notices are excluded unless they change the macro transmission read.</p>',
    '<p><b>Window:</b> 16 Aug–14 Sep 2026. Official central-bank publications only. The feed prioritizes macro, rates and cross-asset relevance; administrative, personnel and narrow regulatory notices are excluded unless they change the macro transmission read.</p>',
    1,
)
html = html.replace(
    '<div class="scanline"><b>Last scanned:</b> 8 Sep 2026 · Initial 30-day backfill</div>',
    '<div class="scanline"><b>Last scanned:</b> 14 Sep 2026 · Rolling 30-day refresh</div>',
    1,
)
html = html.replace('<div class="stitle">In scope now</div><div class="news-count">73</div>', '<div class="stitle">In scope now</div><div class="news-count">66</div>', 1)
html = html.replace('Research layer: 73 official central-bank publications remains below the 7-day news digest.', 'Research layer: 66 official central-bank publications remains below the 7-day news digest.', 1)

sig_start = html.index('<div class="signal-wrap">')
sig_end = html.index('<div class="newsfilters">', sig_start)
sig = html[sig_start:sig_end]
rba_signal_re = re.compile(r'<a class="signal-card" href="https://www\.rba\.gov\.au/publications/smp/2026/aug/overview\.html".*?</a>')
if len(rba_signal_re.findall(sig)) != 1:
    raise SystemExit("RBA high-signal card anchor changed")
ecb_signal = (
    '<a class="signal-card" href="https://www.ecb.europa.eu/press/projections/html/ecb.projections202609_ecbstaff~8e340fc69d.en.html" rel="noopener" target="_blank">'
    '<div class="sm">EA · Sep 10 · Inflation / Growth</div><b>ECB September Staff Projections</b>'
    '<span>Energy pressure lifts the baseline to 3.0% HICP in 2026, 2.5% in 2027 and 2.1% in 2028, while growth is projected at 0.9%, 1.4% and 1.5%.</span></a>'
)
sig = rba_signal_re.sub(ecb_signal, sig, count=1)
html = html[:sig_start] + sig + html[sig_end:]

ls = html.index(research_list_start) + len(research_list_start)
le = html.index(research_list_end, ls)
old_cards_blob = html[ls:le]
card_re = re.compile(r'<article class="news-card[^>]*>.*?</article>', re.S)
cards = card_re.findall(old_cards_blob)
if len(cards) != 73:
    raise SystemExit(f"expected 73 pre-refresh research cards, found {len(cards)}")
expired_dates = ("Aug 10", "Aug 11", "Aug 12", "Aug 13", "Aug 14")
kept = []
removed = []
for card in cards:
    expire = any(d in card for d in expired_dates)
    wrong_sma = "ECB Survey of Monetary Analysts — September 2026" in card
    if expire or wrong_sma:
        removed.append(card)
    else:
        kept.append(card)
if len(removed) != 12:
    raise SystemExit(f"expected 12 research removals, found {len(removed)}")

additions = [
'''<article class="news-card n-g10 new" data-date="2026-09-11">
<div class="news-meta"><span><b>EA</b> · European Central Bank</span><span>Sep 11 · Survey / Expectations</span></div>
<h3>ECB Survey of Monetary Analysts — September 2026, Aggregate Results</h3><p>The official aggregate results capture market participants’ policy, money-market and macro expectations from the survey round conducted before the September Governing Council meeting. Use it as an expectations cross-check, not as a post-meeting policy signal.</p>
<div class="tags"><span class="tag primary">Rates / Expectations</span><span class="tag">Monetary Policy</span><span class="tag">Markets</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.ecb.europa.eu/stats/ecb_surveys/sma/html/index.en.html" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-g10 new" data-date="2026-09-10">
<div class="news-meta"><span><b>EA</b> · European Central Bank</span><span>Sep 10 · Staff Projections</span></div>
<h3>ECB Staff Macroeconomic Projections — September 2026</h3><p>The baseline puts headline inflation at 3.0% in 2026, 2.5% in 2027 and 2.1% in 2028, with real GDP growth at 0.9%, 1.4% and 1.5%. Energy remains the central inflation risk and the staff scenarios show a wide adverse tail if the shock persists.</p>
<div class="tags"><span class="tag primary">Inflation</span><span class="tag">GDP</span><span class="tag">Energy</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.ecb.europa.eu/press/projections/html/ecb.projections202609_ecbstaff~8e340fc69d.en.html" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-g10 new" data-date="2026-09-10">
<div class="news-meta"><span><b>EA</b> · European Central Bank</span><span>Sep 10 · Policy Decision</span></div>
<h3>ECB raises its three key policy rates by 25 basis points</h3><p>The deposit rate rises to 2.50%, the main refinancing rate to 2.65% and the marginal lending rate to 2.90% effective September 16. The Governing Council cited Middle East energy pressure and inflation remaining above target for an extended period.</p>
<div class="tags"><span class="tag primary">Monetary Policy</span><span class="tag">Inflation</span><span class="tag">Rates</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-nz new" data-date="2026-09-09">
<div class="news-meta"><span><b>NZ</b> · RBNZ</span><span>Sep 9 · Speech / Bulletin</span></div>
<h3>The repo market: global trends and a New Zealand perspective</h3><p>RBNZ says repo is increasingly important for liquidity management and monetary-policy implementation. Weekly repo operations now sit at the centre of the Bank’s liquidity framework, while deeper private repo markets can reduce the settlement-cash footprint required from the central bank.</p>
<div class="tags"><span class="tag primary">Liquidity / Repo</span><span class="tag">Monetary Policy</span><span class="tag">Financial Conditions</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.rbnz.govt.nz/hub/publications/bulletin/2026/the-repo-market-global-trends-and-a-new-zealand-perspective" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-us new" data-date="2026-09-09">
<div class="news-meta"><span><b>US</b> · Richmond Fed</span><span>Sep 9 · Research / Labor</span></div>
<h3>Measuring AI Adoption</h3><p>New firm-and-worker measurement work finds AI adoption is high in some large firms and sectors but far from ubiquitous across the economy. Current use is predominantly task augmentation rather than substitution, making the evidence more relevant to productivity and task redesign than broad near-term job displacement.</p>
<div class="tags"><span class="tag primary">AI / Productivity</span><span class="tag">Jobs</span><span class="tag">Business</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.richmondfed.org/podcasts/speaking_of_the_economy/2026/speaking_2026_09_09_measuring_ai_adoption" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
]
new_cards = additions + kept
if len(new_cards) != 66:
    raise SystemExit(f"expected 66 post-refresh research cards, found {len(new_cards)}")
html = html[:ls] + "".join(new_cards) + html[le:]

html = html.replace('<div class="coverage-item"><b>RBNZ</b><span>policy outlook · uncertainty</span></div>', '<div class="coverage-item"><b>RBNZ</b><span>policy outlook · repo / liquidity</span></div>', 1)
html = html.replace('<div class="coverage-item"><b>ECB</b><span>inflation · labor transmission</span></div>', '<div class="coverage-item"><b>ECB</b><span>policy · projections · expectations</span></div>', 1)

xs = html.index('<div class="x-signal">')
xe = html.index('<div class="news-divider">', xs)
x_status = '''<div class="x-signal"><div class="x-head"><div><div class="stitle">X Signal</div><p>Fast signal only. Official accounts can stand as primary statements; media/reporter posts require corroboration before promotion.</p></div><span class="signal-badge">14 SEP SCAN</span></div><div class="x-grid"><div class="x-card"><div class="xtype">NO FRESH PROMOTION</div><b>Public-web X scan</b><span>No qualifying Sep 13–14 post was found that added a material USD/CAD/AUD/NZD fact beyond the confirmed news and official-source tape already promoted above. The personalized X source universe remains pending Kevin’s X archive, so this is a bounded public-web scan rather than a complete Following feed.</span><div class="xdate">Refreshed Sep 14 · no score impact</div></div></div></div>'''
html = html[:xs] + x_status + html[xe:]

old_catalysts = '<div class="catalysts"><div class="cat"><b>Sep 10</b>US PPI</div><div class="cat"><b>Sep 11</b>US CPI</div><div class="cat"><b>Sep 16</b>FOMC</div><div class="cat"><b>Sep 29</b>Canada July GDP</div><div class="cat"><b>Sep 29</b>RBA decision</div><div class="cat"><b>Sep 30</b>US PCE/GDP update</div></div>'
new_catalysts = '<div class="catalysts"><div class="cat"><b>Sep 16</b>FOMC + SEP</div><div class="cat"><b>Sep 29</b>Canada July GDP</div><div class="cat"><b>Sep 29</b>RBA decision</div><div class="cat"><b>Sep 30</b>US PCE + GDP update</div><div class="cat"><b>Oct 28</b>BoC + MPR</div></div>'
if html.count(old_catalysts) != 1:
    raise SystemExit("catalyst anchor changed")
html = html.replace(old_catalysts, new_catalysts, 1)

old_kpi = '<div class="name">Core CPI</div><div class="num">2.5%</div>'
if html.count(old_kpi) != 1:
    raise SystemExit("US Core CPI KPI anchor changed")
html = html.replace(old_kpi, '<div class="name">Core CPI</div><div class="num">2.4%</div>', 1)

core_cpi_row = re.compile(r'<tr>\s*<td><span class="ctry us">US</span></td>\s*<td>Inflation</td><td><b>Core CPI</b>.*?</tr>', re.S)
matches = core_cpi_row.findall(html)
if len(matches) != 1:
    raise SystemExit(f"expected one US Core CPI feed row, found {len(matches)}")
new_core_cpi_row = '''<tr>
<td><span class="ctry us">US</span></td>
<td>Inflation</td><td><b>Core CPI</b><small>Approx. annualized from rounded published m/m changes; 12m = y/y</small></td><td class="latest">2.4% y/y</td>
<td>≈2.0%</td><td>≈2.6%</td><td>n/a*</td><td>2.4%</td>
<td class="method">Aug 2026</td>
</tr>'''
html = core_cpi_row.sub(new_core_cpi_row, html, count=1)

release_marker = '<section class="page releases">'
rs = html.index(release_marker)
tbody = html.index('<tbody>', rs) + len('<tbody>')
if 'data-label="Release">August CPI' in html[rs:] or 'data-label="Release">August PPI' in html[rs:]:
    raise SystemExit("August CPI/PPI release rows already applied")
release_rows = '''<tr><td data-label="Date">Sep 11</td><td data-label="Country">US</td><td data-label="Theme">Inflation</td><td data-label="Release">August CPI</td><td data-label="Actual">+0.4% m/m · 3.4% y/y</td><td data-label="Context">Core +0.3% m/m · 2.4% y/y; headline CPI has zero standalone Core PCE score weight</td><td data-label="Source">BLS</td></tr>
<tr><td data-label="Date">Sep 10</td><td data-label="Country">US</td><td data-label="Theme">Inflation</td><td data-label="Release">August PPI</td><td data-label="Actual">+0.4% m/m · 5.4% y/y</td><td data-label="Context">Goods +1.1%; headline PPI has no standalone score weight and only mapped Core PCE components can affect the indexed score</td><td data-label="Source">BLS</td></tr>
'''
html = html[:tbody] + release_rows + html[tbody:]

if html.count('class="news-card') != 66:
    raise SystemExit(f"expected 66 research cards, found {html.count('class=\"news-card')}")
if any(f'>{d} ·' in html[html.index(research_list_start):html.index(research_list_end)] for d in expired_dates):
    raise SystemExit("expired Aug 10–14 research card remains")
for required in (
    'Window:</b> 16 Aug–14 Sep 2026',
    'Last scanned:</b> 14 Sep 2026 · Rolling 30-day refresh',
    '<div class="stitle">In scope now</div><div class="news-count">66</div>',
    'ECB Staff Macroeconomic Projections — September 2026',
    'The repo market: global trends and a New Zealand perspective',
    'NO FRESH PROMOTION',
    '<b>Sep 16</b>FOMC + SEP',
    '<b>Oct 28</b>BoC + MPR',
    '<div class="name">Core CPI</div><div class="num">2.4%</div>',
    'August CPI</td><td data-label="Actual">+0.4% m/m · 3.4% y/y',
    'August PPI</td><td data-label="Actual">+0.4% m/m · 5.4% y/y',
):
    if required not in html:
        raise SystemExit(f"missing v11 marker: {required[:70]}")
for stale in ('<b>Sep 10</b>US PPI', '<b>Sep 11</b>US CPI', '@ReserveBankofNZ', '@MarkJCarney', 'Bloomberg @business'):
    if stale in html:
        raise SystemExit(f"stale v11 content remains: {stale}")
if html.count('class="temp-dimension score-detail"') != 16 or html.count('/100') != 16:
    raise SystemExit("score drawer count changed")
if 'LINEAGE GAP · August CPI bridge' not in html:
    raise SystemExit("US CPI bridge lineage gap lost")

path.write_text(html)
