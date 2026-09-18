"""Deterministic research screens. No trade recommendations or model calls."""
from __future__ import annotations
import math
import statistics as st

HORIZONS = {'1D': 1, '5D': 5, '1M': 21, '3M': 63}
MIN_HISTORY = 200


def finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def rank(values, x):
    return 100 * (sum(v < x for v in values) + .5 * sum(v == x for v in values)) / len(values)


def score(values, x):
    sd = st.pstdev(values) if len(values) > 1 else 0
    return (x - st.fmean(values)) / sd if sd > 1e-10 else None


def summarize(series, *, unit, kind, today, lag=4):
    items = sorted((d, v) for d, v in series.items() if d <= today and finite(v))
    if not items: return {'status': 'unavailable', 'reason': 'No finite observations'}
    ds, vs = zip(*items)
    prior = list(vs[-253:-1]); age = (today - ds[-1]).days
    out = {'as_of': ds[-1].isoformat(), 'age_days': age, 'status': 'ok' if age <= lag else 'stale',
           'max_age_days': lag, 'value': vs[-1], 'unit': unit, 'n': len(prior), 'z': None, 'percentile': None,
           'history': [[d.isoformat(), v] for d, v in items[-126:]], 'moves': {}}
    if len(prior) >= MIN_HISTORY: out.update(z=score(prior, vs[-1]), percentile=rank(prior, vs[-1]))
    for label, n in HORIZONS.items():
        def change(i):
            if kind == 'price': return 100 * math.log(vs[i] / vs[i-n]) if vs[i] > 0 and vs[i-n] > 0 else None
            return vs[i] - vs[i-n]
        val = change(len(vs)-1) if len(vs) > n else None
        prior_moves = [change(i) for i in range(max(n, len(vs)-253), len(vs)-1)]
        prior_moves = [v for v in prior_moves if finite(v)]
        out['moves'][label] = {'value': val, 'unit': '% log' if kind == 'price' else unit,
                               'z': score(prior_moves, val) if finite(val) and len(prior_moves) >= 60 else None, 'n': len(prior_moves)}
    return out


def relationship(y, x, *, y_kind='price', x_kind='price', today, lag=4):
    """OLS on aligned daily changes. Latest observation excluded from estimation."""
    common = sorted(set(y) & set(x)); obs = []
    for a, b in zip(common, common[1:]):
        if b > today or (b-a).days > 4: continue
        def delta(s, kind):
            if kind == 'price': return 100 * math.log(s[b]/s[a]) if s[b] > 0 and s[a] > 0 else None
            return s[b]-s[a]
        dy, dx = delta(y, y_kind), delta(x, x_kind)
        if finite(dy) and finite(dx): obs.append((b, dy, dx))
    if len(obs) < 127: return {'status': 'insufficient', 'reason': 'Requires 126 prior matched daily changes', 'n': max(0, len(obs)-1)}
    train, latest = obs[-127:-1], obs[-1]
    ys, xs = [r[1] for r in train], [r[2] for r in train]
    vx, vy = st.pvariance(xs), st.pvariance(ys)
    if min(vx, vy) < 1e-12: return {'status':'insufficient','reason':'Constant or near-constant history','n':126}
    cov = st.fmean((a-st.fmean(xs))*(b-st.fmean(ys)) for a,b in zip(xs,ys))
    beta = cov/vx; alpha = st.fmean(ys)-beta*st.fmean(xs); corr = cov/math.sqrt(vx*vy)
    recent_corr = st.correlation(xs[-20:], ys[-20:]) if min(st.pvariance(xs[-20:]), st.pvariance(ys[-20:])) > 1e-12 else 0
    errors = [a-alpha-beta*b for a,b in zip(ys,xs)]
    residual = latest[1]-alpha-beta*latest[2]; z = score(errors,residual)
    status = 'stale' if (today-latest[0]).days > lag else 'weak' if abs(corr) < .35 or corr*recent_corr <= 0 else 'ok'
    return {'status':status, 'max_age_days':lag, 'as_of':latest[0].isoformat(), 'n':126, 'correlation':corr,
            'correlation_20d':recent_corr, 'beta':beta, 'r_squared':corr*corr, 'z':z,
            'actual':latest[1], 'expected':alpha+beta*latest[2], 'residual':residual,
            'unit':'% log' if y_kind=='price' else 'bp',
            'reason': 'Daily close times differ; association is not causation or fair value.',
            'history':[[row[0].isoformat(), e] for row,e in zip(train,errors)] + [[latest[0].isoformat(),residual]]}


def build_opportunities(rates, fx, cross, cross_meta, today):
    series = []; raw = {}
    def add(key, label, category, values, unit, kind, countries, note, lag=4):
        raw[key] = values
        m = summarize(values, unit=unit, kind=kind, today=today, lag=lag)
        series.append(dict(m, id=key, label=label, category=category, countries=countries, note=note))
    for c, tenors in rates.items():
        lag = 12 if c=='AU' else 4
        for t, values in tenors.items():
            if values: add(f'{c}_{t}',f'{c} {t} yield','Rates',{d:v*100 for d,v in values.items()},'bp','difference',[c], 'Sovereign yield history; richness requires a valuation thesis.',lag)
        if not all(tenors.get(t) for t in ['2Y','5Y','10Y']): continue
        common=set.intersection(*(set(tenors[t]) for t in ['2Y','5Y','10Y']))
        for name, coeff in [('2s5s',(-1,1,0)),('2s10s',(-1,0,1)),('5s10s',(0,-1,1)),('2s5s10s',(-1,2,-1))]:
            values={d:100*sum(a*tenors[t][d] for a,t in zip(coeff,['2Y','5Y','10Y'])) for d in common}
            note = '2 × 5Y − 2Y − 10Y. Positive = 5Y yield cheap to wings; equal yield weights, not DV01-neutral.' if name=='2s5s10s' else 'Long yield minus short yield. Positive change = steepening.'
            add(f'{c}_{name}',f'{c} {name}','Curves',values,'bp','difference',[c],note,lag)
    for a,b in [('CA','US'),('AU','US'),('NZ','US'),('AU','NZ'),('CA','AU')]:
        for t in ['2Y','5Y','10Y']:
            left,right=rates[a].get(t,{}),rates[b].get(t,{})
            add(f'{a}-{b}_{t}',f'{a} − {b} {t}','Relative rates',{d:100*(left[d]-right[d]) for d in left.keys() & right.keys()},'bp','difference',[a,b],'First-country yield minus second; exact common dates, no filling.',12 if 'AU' in [a,b] else 4)
    for pair,values in fx.items():
        add(pair,pair[:3]+'/'+pair[3:],'FX',values,'spot','price',[pair[:3],pair[3:]],'ECB same-fixing reference cross. A historical extreme is not proof of mispricing.')
    for key,values in cross.items():
        meta=cross_meta[key]
        add(key,meta['label'],'Macro drivers',values,meta['unit'],meta['kind'],[],meta['note'],meta.get('lag',4))
    relationships=[]
    specs=[('USDCAD','WTI'),('AUDUSD','COPPER'),('AUDUSD','SP500'),('NZDUSD','SP500'),('GOLD','US_REAL10'),('SP500','VIX'),('USDCAD','CA-US_2Y'),('AUDUSD','AU-US_2Y'),('AUDNZD','AU-NZ_2Y'),('BRENT','WTI')]
    for y,x in specs:
        x_kind='difference' if x.endswith('_2Y') or x in ['US_REAL10','VIX'] else 'price'
        m=relationship(raw.get(y,{}),raw.get(x,{}),x_kind=x_kind,today=today,lag=12 if 'AU-' in x else 4)
        relationships.append(dict(m,id=y+'~'+x,label=y+' vs '+x,y=y,x=x))
    carry=[]; mapping={'USD':'US','CAD':'CA','AUD':'AU','NZD':'NZ'}
    for pair in fx:
        base,quote=pair[:3],pair[3:]
        if base not in mapping or quote not in mapping:continue
        a,b=rates[mapping[base]].get('2Y',{}),rates[mapping[quote]].get('2Y',{})
        common=sorted(d for d in set(a)&set(b)&set(fx[pair]) if d<=today)
        row={'pair':pair,'status':'unavailable','reason':'Requires both 2Y yields and FX on a common date.'}
        if common:
            d=common[-1]; items=sorted((day,v) for day,v in fx[pair].items() if day<=d)[-61:]
            rets=[math.log(v/items[i-1][1]) for i,(_,v) in enumerate(items) if i]
            vol=st.pstdev(rets)*math.sqrt(252)*100 if len(rets)==60 else None; diff=a[d]-b[d]
            row.update(max_age_days=12 if 'AUD' in [base,quote] else 4,as_of=d.isoformat(),status='ok' if (today-d).days <= (12 if 'AUD' in [base,quote] else 4) else 'stale',
                       long=base if diff>=0 else quote,short=quote if diff>=0 else base,differential_bps=abs(diff)*100,
                       vol=vol,ratio=abs(diff)/vol if vol and vol>0 else None,
                       reason='2Y sovereign yield differential / 60D annualized FX volatility. Not forward carry, funding, roll-down or expected return.')
        carry.append(row)
    carry.sort(key=lambda m:m.get('ratio') or 0,reverse=True)
    return {'version':1,'series':series,'relationships':relationships,'carry':carry,
            'method':{'level_window':252,'minimum_level_history':MIN_HISTORY,'move_minimum':60,'regression_window':126,'correlation_gate':.35,
                      'note':'Baselines exclude the latest observation. Horizons count observations, not calendar days. Screens are research prompts; no probability or expected-return estimates.'}}
