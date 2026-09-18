from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
html = path.read_text()

research_list_start = '<div class="news-list">'
research_list_end = '<div class="coverage">'
ls = html.index(research_list_start) + len(research_list_start)
le = html.index(research_list_end, ls)
blob = html[ls:le]
card_re = re.compile(r'<article class="news-card[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*>.*?</article>', re.S)
cards = [(m.group(1), m.group(0)) for m in card_re.finditer(blob)]
if not cards:
    raise SystemExit("no central-bank research cards found after v11")
cutoff = date(2026, 8, 20)
kept = [card for d, card in cards if date.fromisoformat(d) >= cutoff]

additions = [
'''<article class="news-card n-nz new" data-date="2026-09-17">
<div class="news-meta"><span><b>NZ</b> · RBNZ</span><span>Sep 17 · Research / Financial Stability</span></div>
<h3>The Future of Banking Study: Future banking scenarios for NZ in 2035</h3><p>RBNZ develops three plausible scenarios for how technology, competition, consumer expectations and regulation could reshape New Zealand banking through 2035. This is forward-looking financial-stability research, not a monetary-policy signal.</p>
<div class="tags"><span class="tag primary">Financial Stability</span><span class="tag">Banking</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.rbnz.govt.nz/hub/publications/bulletin/2026/future-of-banking" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-g10 new" data-date="2026-09-17">
<div class="news-meta"><span><b>UK</b> · Bank of England</span><span>Sep 17 · Policy / QT</span></div>
<h3>September 2026 Monetary Policy Summary and Minutes</h3><p>The MPC held Bank Rate at 3.75% by 6–3, with three members preferring a 25bp hike, and judged inflation risks more tilted to the upside. It also adopted a multi-year plan to unwind the remaining monetary-policy gilt stock.</p>
<div class="tags"><span class="tag primary">Monetary Policy</span><span class="tag">QT</span><span class="tag">Inflation</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/september-2026" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-us new" data-date="2026-09-16">
<div class="news-meta"><span><b>US</b> · Federal Reserve</span><span>Sep 16 · Policy Decision</span></div>
<h3>FOMC raises the federal funds target range to 3.75–4.00%</h3><p>The Committee voted unanimously for a 25bp increase, describing activity as solid, domestic spending as resilient and inflation as elevated. This is a policy decision, not research.</p>
<div class="tags"><span class="tag primary">Monetary Policy</span><span class="tag">Inflation</span><span class="tag">Rates</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm" rel="noopener" target="_blank">Open official source ↗</a>
</article>''',
'''<article class="news-card n-us new" data-date="2026-09-16">
<div class="news-meta"><span><b>US</b> · Federal Reserve</span><span>Sep 16 · Economic Projections</span></div>
<h3>September 2026 Summary of Economic Projections</h3><p>The Federal Reserve released the September projections alongside the FOMC decision. Treat the distribution of participant projections as policy-path evidence, not a Committee commitment.</p>
<div class="tags"><span class="tag primary">Rates / Expectations</span><span class="tag">Forecasts</span><span class="tag newtag">NEW</span></div>
<a class="news-link" href="https://www.federalreserve.gov/monetarypolicy/fomcpresconf20260916.htm" rel="noopener" target="_blank">Open official source ↗</a>
</article>'''
]
new_cards = additions + kept
html = html[:ls] + ''.join(new_cards) + html[le:]
count = len(new_cards)
html = re.sub(r'<p><b>Window:</b> 16 Aug–14 Sep 2026\.', '<p><b>Window:</b> 20 Aug–18 Sep 2026.', html, count=1)
html = re.sub(r'<div class="scanline"><b>Last scanned:</b> 14 Sep 2026 · Rolling 30-day refresh</div>', '<div class="scanline"><b>Last scanned:</b> 18 Sep 2026 · Rolling 30-day refresh</div>', html, count=1)
html = re.sub(r'<div class="stitle">In scope now</div><div class="news-count">66</div>', f'<div class="stitle">In scope now</div><div class="news-count">{count}</div>', html, count=1)
html = re.sub(r'Research layer: 66 official central-bank publications remains below the 7-day news digest\.', f'Research layer: {count} official central-bank publications remains below the 7-day news digest.', html, count=1)

xs = html.index('<div class="x-signal">')
xe = html.index('<div class="news-divider">', xs)
x_status = '''<div class="x-signal"><div class="x-head"><div><div class="stitle">X Signal</div><p>Fast signal only. Official accounts can stand as primary statements; media/reporter posts require corroboration before promotion.</p></div><span class="signal-badge">18 SEP SCAN</span></div><div class="x-grid"><div class="x-card"><div class="xtype">NO FRESH PROMOTION</div><b>Public-web X scan</b><span>No qualifying public X post added a material USD/CAD/AUD/NZD fact beyond the confirmed official/Reuters tape. The personalized X source universe remains pending the requested archive, so this remains a bounded public-web scan.</span><div class="xdate">Refreshed Sep 18 · no score impact</div></div></div></div>'''
html = html[:xs] + x_status + html[xe:]

if html.count('class="news-card') != count:
    raise SystemExit('research card count mismatch')
if any(f'data-date="2026-08-{d:02d}"' in html[ls:] for d in range(1, 20)):
    raise SystemExit('expired research remains')
for required in ('Window:</b> 20 Aug–18 Sep 2026', 'Last scanned:</b> 18 Sep 2026', 'The Future of Banking Study', 'September 2026 Monetary Policy Summary and Minutes', 'FOMC raises the federal funds target range', '18 SEP SCAN'):
    if required not in html:
        raise SystemExit(f'missing required Sep 18 state: {required}')
path.write_text(html)
print(f'Sep 18 completeness refresh applied; research cards={count}')
