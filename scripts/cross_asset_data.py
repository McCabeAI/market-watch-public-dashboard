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
    'WTI': ('WTI futures', 'CL=F', 'USD/bbl', 'price', 4),
    'BRENT': ('Brent futures', 'BZ=F', 'USD/bbl', 'price', 4),
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
        yahoo=symbol in ['GC=F','CL=F','BZ=F','HG=F','^RUT']
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


COMPACT_MARK_IDS = ("WTI", "BRENT", "GOLD", "SP500", "NASDAQ", "DOW", "RUSSELL", "COPPER", "VIX")


def stamp_latest_values(cross_raw, cross_meta):
    """Copy the newest completed observation onto series metadata before freeze."""
    for key, values in (cross_raw or {}).items():
        meta = (cross_meta or {}).get(key)
        if not isinstance(meta, dict) or not values:
            continue
        asof = max(values)
        meta["value"] = values[asof]
        meta.setdefault("as_of", asof.isoformat())
    return cross_meta


def compact_cross_assets(market_state):
    """Small oil/gold/equity block safe to copy into trader, PM, and agent packets."""
    market_state = market_state if isinstance(market_state, dict) else {}
    block = market_state.get("cross_assets") if isinstance(market_state.get("cross_assets"), dict) else {}
    series = block.get("series") if isinstance(block.get("series"), dict) else {}
    opportunities = market_state.get("opportunities") if isinstance(market_state.get("opportunities"), dict) else {}
    by_id = {}
    for row in opportunities.get("series") or []:
        if isinstance(row, dict) and row.get("id"):
            by_id[str(row["id"])] = row
    marks = []
    for key in COMPACT_MARK_IDS:
        meta = series.get(key) if isinstance(series.get(key), dict) else {}
        opp = by_id.get(key) or {}
        if not meta and not opp:
            continue
        value = meta.get("value", opp.get("value"))
        marks.append(
            {
                "id": key,
                "symbol": meta.get("symbol"),
                "label": meta.get("label") or opp.get("label"),
                "value": value,
                "unit": meta.get("unit") or opp.get("unit"),
                "as_of": meta.get("as_of") or opp.get("as_of"),
                "status": meta.get("status") or opp.get("status"),
                "source": meta.get("source"),
            }
        )
    return {
        "status": block.get("status") or ("ok" if marks else "missing"),
        "generated_at": market_state.get("generated_at"),
        "provenance": "frozen_market_state",
        "marks": marks,
    }


def frozen_cross_assets_from_evidence(packet):
    """Compact marks from a frozen evidence snapshot or a bare market-state object."""
    if not isinstance(packet, dict):
        return compact_cross_assets({})
    families = packet.get("families") if isinstance(packet.get("families"), dict) else None
    if families is not None:
        block = families.get("market_state") if isinstance(families.get("market_state"), dict) else {}
        data = block.get("data") if isinstance(block.get("data"), dict) else block
        return compact_cross_assets(data)
    if isinstance(packet.get("market_state"), dict):
        market = packet["market_state"]
        data = market.get("data") if isinstance(market.get("data"), dict) else market
        return compact_cross_assets(data)
    return compact_cross_assets(packet)


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
