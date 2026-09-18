"""Bounded public daily collection; failures remain explicit per series."""
from __future__ import annotations
import csv
import io
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from urllib.parse import quote

# Source identity never changes on failure. Futures are explicitly continuous
# vendor front-contract histories, not spot or roll-adjusted total returns.
SERIES = {
    'SP500': ('S&P 500', 'SP500', 'index', 'price', 4),
    'NASDAQ': ('Nasdaq Composite', 'NASDAQCOM', 'index', 'price', 4),
    'DOW': ('Dow Jones', 'DJIA', 'index', 'price', 4),
    'RUSSELL': ('Russell 2000', '^RUT', 'index', 'price', 4),
    'GOLD': ('Gold futures', 'GC=F', 'USD/oz', 'price', 4),
    'WTI': ('WTI spot', 'DCOILWTICO', 'USD/bbl', 'price', 10),
    'BRENT': ('Brent spot', 'DCOILBRENTEU', 'USD/bbl', 'price', 10),
    'COPPER': ('Copper futures', 'HG=F', 'USD/lb', 'price', 4),
    'VIX': ('VIX', 'VIXCLS', 'points', 'difference', 4),
    'HY_OAS': ('US high-yield spread', 'BAMLH0A0HYM2', 'bp', 'difference', 4),
    'US_REAL10': ('US 10Y real yield', 'DFII10', 'bp', 'difference', 4),
    'US_BE10': ('US 10Y breakeven', 'T10YIE', 'bp', 'difference', 4),
    'BROAD_USD': ('Broad trade-weighted USD', 'DTWEXBGS', 'index', 'price', 7),
}


def parse_fred(blob, symbol, start, today):
    rows = csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))
    if symbol not in (rows.fieldnames or []): raise ValueError('FRED response lacks requested series column')
    out={}
    for r in rows:
        try: d=date.fromisoformat(r.get('observation_date',r.get('DATE',''))); v=float(r[symbol])
        except (ValueError,TypeError): continue
        if start <= d <= today and math.isfinite(v): out[d]=v
    if not out: raise ValueError('No observations in requested window')
    return out


def parse_yahoo(blob, start, today):
    result=json.loads(blob)['chart']['result'][0]
    closes=result['indicators']['quote'][0]['close']; out={}
    for ts,v in zip(result['timestamp'],closes):
        d=datetime.fromtimestamp(ts,timezone.utc).date()
        # Never include a potentially incomplete current-day bar.
        if v is not None and start <= d < today and math.isfinite(v) and v>0: out[d]=float(v)
    if not out: raise ValueError('No completed daily bars')
    return out


def collect_cross_assets(start, today, fetch):
    def one(item):
        key,(label,symbol,unit,kind,lag)=item
        yahoo=symbol in ['GC=F','HG=F','^RUT']
        url=f'https://finance.yahoo.com/quote/{quote(symbol,safe="")}/history/' if yahoo else f'https://fred.stlouisfed.org/series/{symbol}'
        download=f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe="")}?range=5y&interval=1d' if yahoo else f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={symbol}&cosd={start.isoformat()}&coed={today.isoformat()}'
        note='Daily completed close. Futures history includes contract rolls; roll jumps can distort screens.' if yahoo and '=' in symbol else 'Daily source observation; publication and market close times differ.'
        meta={'label':label,'symbol':symbol,'unit':unit,'kind':kind,'lag':lag,'url':url,'download_url':download,
              'source':'Yahoo Finance' if yahoo else 'FRED / original series publisher','note':note}
        try:
            blob=fetch(download,timeout=20,retries=2)
            values=parse_yahoo(blob,start,today) if yahoo else parse_fred(blob,symbol,start,today)
            if unit=='bp':values={d:v*100 for d,v in values.items()}
            asof=max(values); age=(today-asof).days
            meta.update(status='ok' if age<=lag else 'stale',as_of=asof.isoformat(),age_days=age,observations=len(values))
            return key,values,meta
        except Exception as exc:
            meta.update(status='unavailable',error=str(exc),as_of=None,observations=0)
            return key,{},meta
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(one,SERIES.items()))
    return {k:v for k,v,m in results}, {k:m for k,v,m in results}


def public_snapshot(packet):
    """Do not redistribute licensed index histories in the public Pages JSON."""
    import copy
    out=copy.deepcopy(packet)
    # S&P/Dow history stays in the internal daily artifact. Only our derived
    # statistical screens are public. ICE explicitly restricts index statistics
    # as well, so its OAS series is source-link-only in the public read model.
    for row in out.get('opportunities',{}).get('series',[]):
        if row['id'] in ['SP500','DOW']:
            row['value']=None; row['history']=[]
            row['note']+=' Underlying licensed index observations are omitted from this public page.'
        if row['id']=='HY_OAS':
            row.update(value=None,history=[],moves={},z=None,percentile=None,status='internal_only',
                       note='Collected for internal research. ICE index data and statistics require permission for public redistribution; use the source link.')
    if 'HY_OAS' in out.get('cross_assets',{}).get('series',{}):
        out['cross_assets']['series']['HY_OAS']['status']='internal_only'
        out['cross_assets']['series']['HY_OAS']['note']='Collected internally; public redistribution is restricted by the source.'
    return out
