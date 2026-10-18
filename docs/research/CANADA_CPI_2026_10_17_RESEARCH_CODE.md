## evidence/analyze.py

```python
"""Research only. Frozen downloaded inputs; no production imports or writes.
Latest-vintage pseudo-OOS, with actual release-order gates. See report limitations.
"""
from pathlib import Path
import json,re,hashlib
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

P=Path(__file__).resolve().parent; R=P/'raw'; O=P/'results'; O.mkdir(exist_ok=True)
END='2026-09'; TRAIN=120
ca_long=pd.read_csv(R/'18100004_canada.csv',low_memory=False)
ca=ca_long.pivot(index='REF_DATE',columns='Products and product groups',values='VALUE').loc['1997-01':'2026-08']
ca.index=pd.PeriodIndex(ca.index,freq='M'); ix=pd.period_range('1997-01',END,freq='M');ca=ca.reindex(ix)
sa=pd.read_csv(R/'18100006_canada.csv').pivot(index='REF_DATE',columns='Products and product groups',values='VALUE');sa.index=pd.PeriodIndex(sa.index,freq='M');sa=sa.reindex(ix)
def blspanel(file):
 d=pd.read_csv(file,low_memory=False);d.columns=d.columns.str.strip()
 d['period']=d.period.str.strip();d=d[d.period.isin([f'M{i:02}' for i in range(1,13)])].copy()
 d['date']=d.year.astype(str)+'-'+d.period.str[1:];d['value']=pd.to_numeric(d.value,errors='coerce');d['series_id']=d.series_id.str.strip()
 a=d.pivot(index='date',columns='series_id',values='value');a.index=pd.PeriodIndex(a.index,freq='M');return a.reindex(ix)
us=blspanel(R/'us_cpi.csv')
wpids=['WPU01','WPU02','WPU0571','WPU057203','WPU1411','WPU03','WPU12']
if not (R/'ppi_selected.csv').exists():
 d=pd.read_csv(R/'wp.data.0.Current',sep='\t',low_memory=False);d.columns=d.columns.str.strip();d['series_id']=d.series_id.str.strip();d[d.series_id.isin(wpids)].to_csv(R/'ppi_selected.csv',index=False)
ppi=blspanel(R/'ppi_selected.csv')
def mom(a):return a.pct_change(fill_method=None)*100
y=mom(ca);u=mom(us);pp=mom(ppi)
oil=pd.read_csv(R/'WTI.csv');oil.iloc[:,0]=pd.to_datetime(oil.iloc[:,0]);oil.iloc[:,1]=pd.to_numeric(oil.iloc[:,1],errors='coerce');oil=oil.set_index(oil.columns[0]).resample('MS').mean();oil.index=oil.index.to_period('M');oil=mom(oil.iloc[:,0]).reindex(ix)
fx=pd.read_csv(R/'fxold.csv');fx.iloc[:,0]=pd.to_datetime(fx.iloc[:,0]);fx.iloc[:,1]=pd.to_numeric(fx.iloc[:,1],errors='coerce');fx=fx.set_index(fx.columns[0]).resample('MS').mean();fx.index=fx.index.to_period('M');fx=mom(fx.iloc[:,0]).reindex(ix)
cal=json.load(open(R/'release_calendar.json'))
def eligible(t,family):
 s=str(t);return s in cal['ca'] and s in cal[family] and cal[family][s]<cal['ca'][s]
rows=[]
for f in R.glob('nrcan_20*.html'):
 s=BeautifulSoup(f.read_text(),'html.parser')
 for tr in s.select('#pricesTable tr'):
  c=[a.get_text(' ',strip=True) for a in tr.select('td,th')]
  if len(c)==5 and re.fullmatch(r'\d{4}-\d{2}',c[0]):rows.append(c)
nr=pd.DataFrame(rows,columns=['period','gas','tax','marketing','refining']).drop_duplicates('period').set_index('period').apply(pd.to_numeric,errors='coerce');nr.index=pd.PeriodIndex(nr.index,freq='M');nr=nr.sort_index().loc[:END];nr.to_csv(O/'canadian_fuel_monthly.csv');gas=mom(nr.gas).reindex(ix)

# Economic mappings, not title-matching. Broader pairs retain mismatch labels.
maps={
'Gasoline':'SETB01','Energy':'SA0E','Food purchased from stores':'SAF11',
'Meat':'SAF11211','Fish, seafood and other marine products':'SEFG',
'Dairy products':'SEFJ','Eggs':'SEFH','Bakery and cereal products (excluding baby food)':'SAF111',
'Fresh fruit':'SEFK','Fresh vegetables':'SEFL','Food purchased from restaurants':'SEFV',
'Purchase of new passenger vehicles (202204=100)':'SETA01','Purchase of used passenger vehicles (202204=100)':'SETA02',
'Purchase of passenger vehicles':'SETA01','Clothing':'SA311','Clothing and footwear':'SAA',
'Furniture':'SEHJ','Household equipment':'SEHK','Household furnishings and equipment':'SAH31',
'Sporting and exercise equipment':'SERC','Toys, games (excluding video games) and hobby supplies':'SS61011',
'Computer equipment, software and supplies (201104=100)':'SEEE01','Video equipment':'SERA01',
'Air transportation':'SETG01','Traveller accommodation':'SEHB',
'Health care goods':'SAM1','Health care services':'SAM2','Personal care supplies and equipment':'SEGB',
'Personal care services':'SEGC','Rent':'SEHA','Shelter':'SAH1',
}
maps={k:v for k,v in maps.items() if k in y and 'CUUR0000'+v in u}
pmap={k:('WPU0571' if k in ['Gasoline','Energy'] else 'WPU057203' if k=='Air transportation' else 'WPU1411' if 'vehicles' in k else 'WPU03' if 'Clothing' in k else 'WPU12' if ('Furniture' in k or 'Household' in k) else 'WPU02') for k in maps}
names=json.load(open(P/'core55_names.json'))
allnames=list(dict.fromkeys(names+list(maps)+['All-items','All-items excluding food and energy','All-items excluding gasoline']))
months=pd.get_dummies(ix.month,prefix='m',dtype=float);months.index=ix
def feature(yy,extra=[]):
 a=months.copy();a['lag']=yy.shift(1);a['mean3']=yy.shift(1).rolling(3).mean()
 for n,s in extra:a[n]=s
 return a
def fitpred(yy,X,t,minn=60):
 loc=ix.get_loc(t);idx=ix[max(0,loc-TRAIN):loc];z=pd.concat([yy.rename('y'),X],axis=1).loc[idx].dropna()
 if len(z)<minn or X.loc[t].isna().any():return np.nan
 a=z.iloc[:,1:].to_numpy(float);b=z.y.to_numpy(float);test=X.loc[t].to_numpy(float)
 # Small fixed ridge on nonseasonal predictors, scaled only within training.
 scale=np.std(a,axis=0);scale[scale<1e-9]=1;a=a/scale;test=test/scale
 pen=np.eye(a.shape[1])*1.;pen[:12,:12]=0
 coef=np.linalg.solve(a.T@a+pen+np.eye(a.shape[1])*1e-8,a.T@b)
 return float(test@coef)
records=[];corr=[];live={};preds={}
for name in allnames:
 yy=y[name];X=feature(yy);pred=pd.DataFrame(index=ix,columns=['actual','carry','mean3','season5','AR1','A','Canada','US','USfx','USlag','PPI','B','C','D','chosen'],dtype=object);pred['actual']=yy
 sid=maps.get(name);uu=u['CUUR0000'+sid] if sid else None
 feats={'A':X,'Canada':feature(yy,[('fx',fx),('oil',oil)])}
 if sid:
  feats.update({'US':feature(yy,[('us',uu)]),'USfx':feature(yy,[('us',uu),('fx',fx),('oil',oil)]),'USlag':feature(yy,[('uslag',uu.shift(1))]),'PPI':feature(yy,[('ppi',pp[pmap[name]])])})
 if name=='Gasoline':feats['B']=feature(yy,[('pump',gas)])
 for t in ix[ix>=pd.Period('2010-01')]:
  past=yy.loc[:t-1].dropna();n=len(past)
  if n<24:continue
  pred.loc[t,'carry']=past.iloc[-1];pred.loc[t,'mean3']=past.iloc[-3:].mean()
  same=past[past.index.month==t.month].iloc[-5:];pred.loc[t,'season5']=same.mean() if len(same) else past.iloc[-3:].mean()
  minimum=24 if n<60 else 60
  a=fitpred(yy,X,t,minimum)
  if np.isnan(a):a=pred.loc[t,'season5']
  pred.loc[t,'A']=a
  ar=pd.DataFrame({'const':1.,'lag':yy.shift(1)},index=ix)
  # Ordinary AR(1), same rolling 120 months, minimal 24.
  z=pd.concat([yy.rename('y'),ar],axis=1).loc[:t-1].tail(TRAIN).dropna()
  pred.loc[t,'AR1']=float(ar.loc[t].to_numpy()@np.linalg.lstsq(z[['const','lag']].to_numpy(),z.y.to_numpy(),rcond=None)[0])
  for model,xx in feats.items():
   if model=='A':continue
   valid=not ((model in ['US','USfx'] and not eligible(t,'cpi')) or (model=='PPI' and not eligible(t,'ppi')) or (model=='USlag' and not (str(t-1) in cal['cpi'] and str(t) in cal['ca'] and cal['cpi'][str(t-1)]<cal['ca'][str(t)])))
   v=fitpred(yy,xx,t,24 if model=='B' else minimum) if valid else np.nan
   pred.loc[t,model]=a if np.isnan(v) else v
  if name!='Gasoline':pred.loc[t,'B']=a
  # Online eligibility uses only previously realized errors; no end-sample selection.
  history=pred.loc[:t-1].tail(36);candidates=['Canada']+(['US','USfx','USlag','PPI'] if sid else [])
  best='A';besterr=np.inf
  if len(history.dropna(subset=['actual','A']))>=24:
   baseerr=(pd.to_numeric(history.A)-history.actual).abs().mean()
   for m in candidates:
    err=(pd.to_numeric(history[m])-history.actual).abs().mean()
    if np.isfinite(err) and err<baseerr*.95 and err<besterr:best=m;besterr=err
  c=float(pred.loc[t,best]);b=float(pred.loc[t,'B'])
  pred.loc[t,'C']=c;pred.loc[t,'D']=b if name=='Gasoline' else .5*a+.5*c;pred.loc[t,'chosen']=best
  if str(t)>='2017-01':
   for m in ['carry','mean3','season5','AR1','A','Canada','US','USfx','USlag','PPI','B','C','D']:
    v=pred.loc[t,m]
    if pd.notna(v):records.append({'component':name,'period':str(t),'model':m,'forecast':float(v),'actual':None if pd.isna(yy[t]) else float(yy[t]),'us_available':eligible(t,'cpi'),'ppi_available':eligible(t,'ppi')})
 preds[name]=pred;live[name]={m:float(pred.loc[pd.Period(END),m]) for m in ['A','B','C','D','carry','mean3','season5'] if pd.notna(pred.loc[pd.Period(END),m])};live[name]['chosen']=pred.loc[pd.Period(END),'chosen']
 if sid:
  z=pd.DataFrame({'ca':yy,'us':uu,'lagus':uu.shift(1),'fx':fx,'oil':oil}).loc['1997-01':'2026-08'].dropna()
  for regime,zz in [('full',z),('pre2020',z.loc[:'2019-12']),('post2020',z.loc['2020-01':]),('post2022method',z.loc['2022-05':]),('trade2025',z.loc['2025-01':])]:
   if len(zz)<10:continue
   seas=pd.get_dummies(zz.index.month,dtype=float);seas.index=zz.index
   a=zz.ca-zz.groupby(zz.index.month).ca.transform('mean');b=zz.us-zz.groupby(zz.index.month).us.transform('mean')
   xx=pd.concat([seas,zz[['us','fx','oil']]],axis=1).to_numpy();beta=np.linalg.lstsq(xx,zz.ca,rcond=None)[0][-3]
   corr.append(dict(component=name,regime=regime,n=len(zz),correlation_mom=zz.ca.corr(zz.us),correlation_deseasonalized=a.corr(b),lag1_correlation=zz.ca.corr(zz.lagus),beta_us_month_fx_oil=float(beta)))
  roll=z.ca.rolling(60,min_periods=36).corr(z.us);live[name]['rolling_corr_min']=float(roll.min());live[name]['rolling_corr_max']=float(roll.max())
 print(name,live[name],flush=True)
pd.DataFrame(records).to_csv(O/'component_predictions.csv',index=False);pd.DataFrame(corr).to_csv(O/'correlations.csv',index=False);(O/'live_component_forecasts.json').write_text(json.dumps(live,indent=2))
pd.DataFrame([dict(component=k,us_nsa='CUUR0000'+v,us_sa='CUSR0000'+v,ppi=pmap[k],ca_vector=ca_long[ca_long['Products and product groups']==k].VECTOR.iloc[0]) for k,v in maps.items()]).to_csv(O/'cross_border_mapping.csv',index=False)
def metrics(g):
 e=g.forecast-g.actual
 return pd.Series({'n':len(g),'MAE':e.abs().mean(),'RMSE':np.sqrt((e*e).mean()),'bias':e.mean(),'direction':(np.sign(g.forecast)==np.sign(g.actual)).mean()})
d=pd.DataFrame(records).dropna(subset=['actual'])
out=[]
for regime,dd in [('all',d),('pre2020',d[d.period<'2020-01']),('2021_23',d[(d.period>='2021-01')&(d.period<='2023-12')]),('2024_26',d[d.period>='2024-01']),('2025_26',d[d.period>='2025-01'])]:
 mm=dd.groupby(['component','model']).apply(metrics,include_groups=False).reset_index();mm['regime']=regime;out.append(mm)
pd.concat(out).to_csv(O/'component_metrics.csv',index=False)
(O/'calendar_gates.json').write_text(json.dumps({k:{'eligible':sum(eligible(t,k) for t in ix if '2017-01'<=str(t)<='2026-08'),'months':116,'not_eligible':[str(t) for t in ix if '2017-01'<=str(t)<='2026-08' and not eligible(t,k)]} for k in ['cpi','ppi']},indent=2))

# Aggregate using the eight official groups, then replace disjoint child forecasts.
major=['Food','Shelter','Household operations, furnishings and equipment','Clothing and footwear','Transportation','Health and personal care','Recreation, education and reading','Alcoholic beverages, tobacco products and recreational cannabis']
wlong=pd.read_csv(R/'18100007_canada.csv');wlong=wlong[wlong['Price period of weight'].str.contains('link')].drop_duplicates(['REF_DATE','Products and product groups']);ww=wlong.pivot(index='REF_DATE',columns='Products and product groups',values='VALUE')/100
links={1986:'1988-12',1992:'1994-12',1996:'1997-12',2001:'2002-12',2005:'2007-04',2009:'2011-04',2011:'2013-01',2013:'2014-12',2015:'2016-12',2017:'2018-12',2020:'2021-05',2021:'2022-04',2022:'2023-04',2023:'2024-04',2024:'2025-04',2025:'2026-04'}
def weights(t):
 years=[k for k,l in links.items() if pd.Period(l)<t and k in ww.index];k=max(years);l=pd.Period(links[k]);base=ww.loc[k].copy();ans={}
 for n in base.dropna().index:
  if n in ca and l in ca.index and pd.notna(ca.loc[l,n]) and pd.notna(ca.loc[t-1,n]):ans[n]=base[n]*(ca.loc[t-1,n]/ca.loc[l,n])/(ca.loc[t-1,'All-items']/ca.loc[l,'All-items'])
 return pd.Series(ans),k,l
agg=[];contrib=[]
for t in ix[ix>=pd.Period('2017-01')]:
 ws,k,l=weights(t);mr={}
 for n in major:
  if n in preds:mr[n]=preds[n].loc[t]
  else:
   yy=y[n];a=fitpred(yy,feature(yy),t);past=yy.loc[:t-1].dropna();mr[n]={'A':a,'carry':past.iloc[-1],'mean3':past.iloc[-3:].mean(),'season5':past[past.index.month==t.month].iloc[-5:].mean()}
 vals={m:sum(ws.get(n,0)*float(mr[n][m]) for n in major) for m in ['A','carry','mean3','season5']}
 # B replaces gasoline only. C adds online-accepted US/Canada predictions for disjoint children.
 gasbase=float(preds['Gasoline'].loc[t,'A']);gasdirect=float(preds['Gasoline'].loc[t,'B']);vals['B']=vals['A']+ws['Gasoline']*(gasdirect-gasbase)
 vals['C']=vals['B'];details=[]
 # Parents are never replaced alongside their children. Shelter is deliberately Canada-only.
 replace=['Meat','Fish, seafood and other marine products','Dairy products','Eggs','Bakery and cereal products (excluding baby food)','Fresh fruit','Fresh vegetables','Food purchased from restaurants','Clothing','Furniture','Household equipment','Air transportation','Traveller accommodation','Health care goods','Personal care supplies and equipment','Personal care services','Sporting and exercise equipment']
 if t>=pd.Period('2024-05'):replace+=['Purchase of new passenger vehicles (202204=100)','Purchase of used passenger vehicles (202204=100)']
 for n in replace:
  if n not in preds:continue
  key=re.sub(r' \(\d+=100\)$','',n);delta=ws.get(n,ws.get(key,0))*(float(preds[n].loc[t,'C'])-float(preds[n].loc[t,'A']))
  vals['C']+=delta;details.append((n,float(delta)))
 vals['D']=.5*vals['B']+.5*vals['C']
 for m,v in vals.items():agg.append(dict(period=str(t),model=m,forecast=v,actual=y.loc[t,'All-items'],gas_shock=abs(y.loc[t,'Gasoline'])>=5))
 if str(t)==END:
  for n in major:
   v=ws[n]*float(mr[n]['A']);contrib.append(dict(component=n,weight=ws[n]*100,mom=float(mr[n]['A']),contribution=v,status='modeled Canadian seasonal AR'))
  contrib.append(dict(component='Gasoline replacement of baseline',weight=ws.Gasoline*100,mom=gasdirect,contribution=ws.Gasoline*(gasdirect-gasbase),status='Canadian pump proxy, fitted bridge minus baseline'))
  for n,v in details:
   if abs(v)>1e-8:contrib.append(dict(component=n+' ensemble revision',weight=None,mom=None,contribution=v*.5,status='online selected predictor, half weight'))
  (O/'live_weights.json').write_text(json.dumps({'basket':int(k),'link':str(l),'weights':ws.to_dict()},indent=2))
ad=pd.DataFrame(agg);ad.to_csv(O/'aggregate_predictions.csv',index=False);pd.DataFrame(contrib).to_csv(O/'contributions.csv',index=False)
aa=ad.dropna(subset=['actual']);parts=[]
for reg,dd in [('all',aa),('gas_shocks',aa[aa.gas_shock]),('2020_26',aa[aa.period>='2020-01']),('2021_23',aa[(aa.period>='2021-01')&(aa.period<='2023-12')]),('2025_26',aa[aa.period>='2025-01'])]:
 m=dd.groupby('model').apply(metrics,include_groups=False).reset_index();m['regime']=reg;parts.append(m)
pd.concat(parts).to_csv(O/'aggregate_metrics.csv',index=False)
print('AGGREGATES',ad[ad.period==END].to_dict('records'),flush=True)
print(pd.concat(parts).to_string(index=False),flush=True)

```

## evidence/supplement.py

```python
"""Additional research diagnostics. Never imports or changes production code."""
from pathlib import Path
import json,re
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
P=Path(__file__).resolve().parent;R=P/'raw';O=P/'results'
ix=pd.period_range('1997-01','2026-09',freq='M');target=ix[-1]
def panel(file,dim):
 d=pd.read_csv(R/file,low_memory=False);a=d.pivot(index='REF_DATE',columns=dim,values='VALUE');a.index=pd.PeriodIndex(a.index,freq='M');return a.reindex(ix)
ca=panel('18100004_canada.csv','Products and product groups');sa=panel('18100006_canada.csv','Products and product groups');core=panel('18100256_canada.csv','Alternative measures')
y=ca.pct_change(fill_method=None)*100;say=sa.pct_change(fill_method=None)*100
names=json.load(open(P/'core55_names.json'))
wl=pd.read_csv(R/'18100007_canada.csv');wl=wl[wl['Price period of weight'].str.contains('link')].drop_duplicates(['REF_DATE','Products and product groups']);w=wl.pivot(index='REF_DATE',columns='Products and product groups',values='VALUE')/100
links={1996:'1997-12',2001:'2004-06',2005:'2007-04',2009:'2011-04',2011:'2013-01',2013:'2014-12',2015:'2016-12',2017:'2018-12',2020:'2021-05',2021:'2022-04',2022:'2023-04',2023:'2024-04',2024:'2025-04',2025:'2026-04'}
def basket(t):return max(k for k,v in links.items() if pd.Period(v)<t)
def weight(t,n):
 k=basket(t);l=pd.Period(links[k]);return w.loc[k,n]*ca.loc[t-1,n]/ca.loc[l,n]/(ca.loc[t-1,'All-items']/ca.loc[l,'All-items'])
def design(yy,extras={}):
 x=pd.get_dummies(ix.month,dtype=float);x.index=ix;x['lag']=yy.shift(1);x['mean3']=yy.shift(1).rolling(3).mean()
 for k,v in extras.items():x[k]=v
 return x
def fit(yy,x,t,minn=24):
 z=pd.concat([yy.rename('y'),x],axis=1).loc[:t-1].tail(120).dropna()
 if len(z)<minn or x.loc[t].isna().any():return np.nan
 a=z.iloc[:,1:].to_numpy(float);b=z.y.to_numpy(float);test=x.loc[t].to_numpy(float);sd=a.std(axis=0);sd[sd<1e-9]=1;a/=sd;test/=sd
 pen=np.eye(a.shape[1]);pen[:12,:12]=0
 return float(test@np.linalg.solve(a.T@a+pen+np.eye(a.shape[1])*1e-8,a.T@b))
def stats(actual,forecast):
 a=pd.DataFrame({'actual':actual,'forecast':forecast}).dropna();e=a.forecast-a.actual
 return dict(n=len(a),MAE=float(e.abs().mean()),RMSE=float(np.sqrt((e*e).mean())),bias=float(e.mean()),direction=float((np.sign(a.actual)==np.sign(a.forecast)).mean()))
def fuel(prefix):
 rows=[]
 for f in R.glob(prefix+'_20*.html'):
  for tr in BeautifulSoup(f.read_text(),'html.parser').select('#pricesTable tr'):
   c=[a.get_text(' ',strip=True) for a in tr.select('td,th')]
   if len(c)>=2 and re.fullmatch(r'\d{4}-\d{2}',c[0]):rows.append((c[0],float(c[1])))
 s=pd.Series(dict(rows)).sort_index();s.index=pd.PeriodIndex(s.index,freq='M');return s.reindex(ix).pct_change(fill_method=None)*100
gas=fuel('nrcan');furnace=fuel('furnace')
u=pd.read_csv(R/'us_cpi.csv');u.columns=u.columns.str.strip();u.series_id=u.series_id.str.strip();u.period=u.period.str.strip();u=u[u.period.str.match('M(0[1-9]|1[012])')];u['date']=u.year.astype(str)+'-'+u.period.str[1:];uu=u.pivot(index='date',columns='series_id',values='value');uu.index=pd.PeriodIndex(uu.index,freq='M');uu=uu.reindex(ix).apply(pd.to_numeric,errors='coerce').pct_change(fill_method=None)*100
cal=json.load(open(R/'release_calendar.json'));records=[]
nh=panel('nhpi_canada.csv','New housing price indexes')['House only'].pct_change(fill_method=None).shift(1)*100
lo=pd.read_csv(R/'loan.csv');lr=lo[lo['Unit of measure']=='Interest rate'].pivot(index='REF_DATE',columns='Components',values='VALUE');lb=lo[lo['Unit of measure']=='Dollars'].pivot(index='REF_DATE',columns='Components',values='VALUE')
kn=['Total, outstanding balances, residential mortgages, insured','Total, outstanding balances, residential mortgages, uninsured'];rate=(lr[kn]*lb[kn]).sum(axis=1)/lb[kn].sum(axis=1);rate.index=pd.PeriodIndex(rate.index,freq='M');rate=rate.reindex(ix).pct_change(fill_method=None).shift(2)*100
tests={'Gasoline':{'direct':{'pump':gas},'direct_US':{'pump':gas,'us':uu.CUUR0000SETB01}},'Fuel oil and other fuels':{'direct':{'furnace':furnace}},"Homeowners' replacement cost":{'lag_NHPI':{'nhpi':nh}},'Mortgage interest cost':{'lag_stock_rate':{'stock_rate':rate}}}
for name,models in tests.items():
 for t in ix[ix>=pd.Period('2019-01')]:
  baseline=fit(y[name],design(y[name]),t,60)
  for model,extra in models.items():
   pred=fit(y[name],design(y[name],extra),t)
   if model=='direct_US' and not (str(t) in cal['cpi'] and str(t) in cal['ca'] and cal['cpi'][str(t)]<cal['ca'][str(t)]):pred=fit(y[name],design(y[name],{'pump':gas}),t)
   records.append(dict(component=name,period=str(t),model=model,forecast=pred,baseline=baseline,actual=y.loc[t,name]))
dd=pd.DataFrame(records);dd.to_csv(O/'additional_component_predictions.csv',index=False);mm=[]
for (name,model),g in dd.dropna().groupby(['component','model']):
 for reg,h in [('all',g),('2021_23',g[(g.period>='2021-01')&(g.period<='2023-12')]),('2025_26',g[g.period>='2025-01'])]:
  mm.append(dict(component=name,model=model,regime=reg,**stats(h.actual,h.forecast),baseline_MAE=stats(h.actual,h.baseline)['MAE']))
pd.DataFrame(mm).to_csv(O/'additional_component_metrics.csv',index=False)

# Diagnostic only: tax-inclusive, causal seasonal correction, incomplete legacy 55 mapping.
prox=[]
for t in ix[ix>=pd.Period('2007-01')]:
 k=basket(t);wt=w.loc[k].reindex(names);past=y.loc[:t-1,names].tail(120);adj=past[past.index.month==t.month].mean()-past.mean()
 rates=y.loc[t,names]-adj
 if t==target:
  live=json.load(open(O/'live_component_forecasts.json'));rates=pd.Series({n:live[n]['A'] for n in names})-adj;rates['Gasoline']=dd[(dd.component=='Gasoline')&(dd.model=='direct')&(dd.period==str(t))].forecast.iloc[0]-adj.Gasoline
 z=pd.DataFrame({'r':rates,'w':wt}).dropna().sort_values('r');coverage=z.w.sum();z.w=z.w/coverage;c=z.w.cumsum();overlap=np.maximum(0,np.minimum(c,.8)-np.maximum(c-z.w,.2));trim=(overlap*z.r).sum()/.6;median=z.r.iloc[np.searchsorted(c.to_numpy(),.5)]
 prox.append(dict(period=str(t),trim=trim,median=median,weight_coverage=coverage))
proxy=pd.DataFrame(prox).set_index('period');proxy.index=pd.PeriodIndex(proxy.index,freq='M');metrics=[];summary={}
for typ in ['trim','median']:
 idx=core[[c for c in core if 'CPI-'+typ+' (index' in c][0]];official_yoy=core[[c for c in core if 'CPI-'+typ+' (year-over-year' in c][0]];cm=idx.pct_change(fill_method=None)*100;pyoy=(1+proxy[typ]/100).rolling(12).apply(np.prod,raw=True)*100-100
 proxy[typ+'_official_mom']=cm;proxy[typ+'_proxy_yoy']=pyoy;proxy[typ+'_official_yoy']=official_yoy
 for reg,start,end in [('all','2017-01','2026-08'),('2025_26','2025-01','2026-08')]:
  for metric,a,b in [('mom',cm,proxy[typ]),('yoy',official_yoy,pyoy)]:metrics.append(dict(measure=typ,regime=reg,metric=metric,**stats(a.loc[start:end],b.loc[start:end])))
 hist=cm.dropna();est=hist.tail(3).mean();lv=idx.loc[target-1]*(1+est/100);yy=(lv/idx.loc[target-12]-1)*100
 summary[typ]=dict(mom=float(est),yoy=float(yy),index=float(lv),base=float(idx.loc[target-12]),previous_index=float(idx.loc[target-1]),annualized3m=float(((lv/idx.loc[target-3])**4-1)*100),proxy_mom=float(proxy.loc[target,typ]))
proxy.to_csv(O/'core_reconstruction.csv');pd.DataFrame(metrics).to_csv(O/'core_reconstruction_metrics.csv',index=False)

# Genuine release-vintage core forecasts. Use prior release's index history, score next first-print YoY.
v=pd.read_csv(R/'18100259_canada.csv',low_memory=False);v=v[v.VALUE.notna()].copy();v['release_date']=pd.to_datetime(v.Release);v['period']=pd.PeriodIndex(v.REF_DATE,freq='M');releases=sorted(v.release_date.unique());vr=[]
for j in range(1,len(releases)):
 old=v[v.release_date==releases[j-1]];new=v[v.release_date==releases[j]];t=new.period.max()
 if old.period.max()!=t-1:continue
 for typ in ['trim','median']:
  oi=old[old['Alternative measures'].str.contains('CPI-'+typ+' \(index',regex=True)].set_index('period').VALUE.sort_index();ny=new[(new.period==t)&new['Alternative measures'].str.contains('CPI-'+typ+' \(year-over-year',regex=True)].VALUE
  oy=old[(old.period==t-1)&old['Alternative measures'].str.contains('CPI-'+typ+' \(year-over-year',regex=True)].VALUE
  if len(ny)==0:continue
  if len(oy):vr.append(dict(measure=typ,period=str(t),model='yoy_carry',forecast=float(oy.iloc[0]),actual=float(ny.iloc[0])))
  if t-12 not in oi.index or len(oi)<24:continue
  m=oi.pct_change(fill_method=None)*100
  for model,pred in [('mom_carry',m.iloc[-1]),('mean3',m.iloc[-3:].mean()),('mean6',m.iloc[-6:].mean())]:
   f=(oi.iloc[-1]*(1+pred/100)/oi.loc[t-12]-1)*100;vr.append(dict(measure=typ,period=str(t),model=model,forecast=float(f),actual=float(ny.iloc[0])))
vd=pd.DataFrame(vr);vd.to_csv(O/'core_vintage_predictions.csv',index=False);vm=[]
for typ in ['trim','median']:
 common=set(vd[(vd.measure==typ)&(vd.model=='mean3')].period)
 for model,g in vd[(vd.measure==typ)&vd.period.isin(common)].groupby('model'):vm.append(dict(measure=typ,model=model,start=g.period.min(),end=g.period.max(),**stats(g.actual,g.forecast)))
pd.DataFrame(vm).to_csv(O/'core_vintage_metrics.csv',index=False)
for typ in ['trim','median']:
 g=vd[(vd.measure==typ)&(vd.model=='mean3')];e=g.actual-g.forecast;summary[typ]['vintage_error_10_90']=e.quantile([.1,.9]).tolist()

# Causal Canadian seasonal bridge; never substitute American seasonal factors.
season=[]
for name in ['All-items','All-items excluding food and energy']:
 diff=say[name]-y[name]
 for t in ix[ix>=pd.Period('2017-01')]:
  past=diff.loc[:t-1].dropna();same=past[past.index.month==t.month].tail(5);bridge=same.median()
  season.append(dict(component=name,period=str(t),forecast_bridge=bridge,actual_bridge=diff.loc[t]))
sd=pd.DataFrame(season);sd.to_csv(O/'seasonal_bridge.csv',index=False)
summary['seasonal_bridges']=sd[sd.period==str(target)].to_dict('records')
live=json.load(open(O/'live_component_forecasts.json'))
summary['special_aggregates']={}
for name in ['All-items excluding food and energy','All-items excluding gasoline']:
 m=live[name]['A'];yy=(ca.loc[target-1,name]*(1+m/100)/ca.loc[target-12,name]-1)*100
 summary['special_aggregates'][name]=dict(mom=m,yoy=float(yy),previous_index=float(ca.loc[target-1,name]),base=float(ca.loc[target-12,name]))
summary['additional_live']=dd[dd.period==str(target)].to_dict('records')
(O/'supplement_summary.json').write_text(json.dumps(summary,indent=2,allow_nan=True))
print(json.dumps(summary,indent=2));print(pd.DataFrame(mm).to_string(index=False));print(pd.DataFrame(vm).to_string(index=False));print(pd.DataFrame(metrics).to_string(index=False))

```

## evidence/sa_diagnostics.py

```python
from pathlib import Path
import numpy as np,pandas as pd
P=Path(__file__).resolve().parent
exec((P/'supplement.py').read_text().split("tests={")[0])
rows=[];cs=[]
for name,sid in [('All-items','SA0'),('Food','SAF1'),('Shelter','SAH1'),('Clothing and footwear','SAA'),('Transportation','SAT'),('All-items excluding food and energy','SA0L1E')]:
 us=uu.get('CUSR0000'+sid)
 if us is None:continue
 yy=say[name];z=pd.DataFrame({'ca':yy,'us':us}).loc['1997-01':'2026-08'].dropna()
 for reg,zz in [('full',z),('pre2020',z.loc[:'2019-12']),('post2020',z.loc['2020-01':])]:cs.append(dict(component=name,regime=reg,SA_correlation=zz.ca.corr(zz.us),n=len(zz)))
 for t in ix[ix>=pd.Period('2017-01')]:
  a=fit(yy,design(yy),t,60);b=fit(yy,design(yy,{'us':us}),t,60)
  if not(str(t) in cal['ca'] and str(t) in cal['cpi'] and cal['cpi'][str(t)]<cal['ca'][str(t)]):b=a
  rows.append(dict(component=name,period=str(t),A=a,US=b,actual=yy.loc[t]))
d=pd.DataFrame(rows);d.to_csv(O/'sa_predictions.csv',index=False);pd.DataFrame(cs).to_csv(O/'sa_correlations.csv',index=False)
m=[]
for n,g in d.groupby('component'):
 for model in ['A','US']:m.append(dict(component=n,model=model,**stats(g.actual,g[model])))
pd.DataFrame(m).to_csv(O/'sa_metrics.csv',index=False)
mp=pd.read_csv(O/'cross_border_mapping.csv');cr=[]
for _,r in mp.iterrows():
 for reg,start,end in [('full','1997-01','2026-08'),('pre_air_change','1997-01','2018-02'),('post_air_change','2019-11','2026-08')]:
  for lag in range(4):
   z=pd.DataFrame({'ca':y[r.component],'us':uu[r.us_nsa].shift(lag)}).loc[start:end].dropna()
   cr.append(dict(component=r.component,regime=reg,lag=lag,n=len(z),r=z.ca.corr(z.us)))
pd.DataFrame(cr).to_csv(O/'lag_correlations.csv',index=False)
print(pd.DataFrame(m).to_string(index=False))

```

## evidence/finalize_analysis.py

```python
"""Aggregate evaluated direct bridges and produce evidence tables and error bands."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
P=Path(__file__).resolve().parent;R=P/'raw';O=P/'results'
ca=pd.read_csv(R/'18100004_canada.csv',low_memory=False).pivot(index='REF_DATE',columns='Products and product groups',values='VALUE');ca.index=pd.PeriodIndex(ca.index,freq='M')
w=pd.read_csv(R/'18100007_canada.csv');w=w[w['Price period of weight'].str.contains('link')].drop_duplicates(['REF_DATE','Products and product groups']).pivot(index='REF_DATE',columns='Products and product groups',values='VALUE')/100
links={2015:'2016-12',2017:'2018-12',2020:'2021-05',2021:'2022-04',2022:'2023-04',2023:'2024-04',2024:'2025-04',2025:'2026-04'}
def weight(t,n):
 k=max(k for k,l in links.items() if pd.Period(l)<t);l=pd.Period(links[k]);return w.loc[k,n]*ca.loc[t-1,n]/ca.loc[l,n]/(ca.loc[t-1,'All-items']/ca.loc[l,'All-items'])
def stats(g):
 g=g.dropna(subset=['actual','forecast']);e=g.forecast-g.actual
 return dict(n=len(g),MAE=float(e.abs().mean()),RMSE=float(np.sqrt((e*e).mean())),bias=float(e.mean()),direction=float((np.sign(g.actual)==np.sign(g.forecast)).mean()))
a=pd.read_csv(O/'aggregate_predictions.csv');extra=pd.read_csv(O/'additional_component_predictions.csv');rows=[]
for t,gg in a.groupby('period'):
 tt=pd.Period(t);delta=0
 for name,model in [('Fuel oil and other fuels','direct'),("Homeowners' replacement cost",'lag_NHPI')]:
  q=extra[(extra.period==t)&(extra.component==name)&(extra.model==model)]
  if len(q) and pd.notna(q.forecast.iloc[0]):delta+=weight(tt,name)*(q.forecast.iloc[0]-q.baseline.iloc[0])
 for parent,new in [('B','B2'),('C','C2'),('D','D2')]:
  d=gg[gg.model==parent].iloc[0].to_dict();d['model']=new;d['forecast']+=delta;rows.append(d)
a=pd.concat([a,pd.DataFrame(rows)],ignore_index=True);a.to_csv(O/'final_aggregate_predictions.csv',index=False)
metrics=[]
for regime,g in [('all',a[a.period<'2026-09']),('2019_26',a[(a.period>='2019-01')&(a.period<'2026-09')]),('2021_23',a[(a.period>='2021-01')&(a.period<='2023-12')]),('2025_26',a[(a.period>='2025-01')&(a.period<'2026-09')]),('gas_shocks',a[a.gas_shock])]:
 for model,h in g.groupby('model'):metrics.append(dict(regime=regime,model=model,**stats(h)))
pd.DataFrame(metrics).to_csv(O/'final_aggregate_metrics.csv',index=False)
rng=np.random.default_rng(20261016);boot=[]
p=a[a.period<'2026-09'].pivot(index='period',columns='model',values='forecast');act=a.drop_duplicates('period').set_index('period').actual.reindex(p.index)
for m1,m2 in [('B2','A'),('B2','season5'),('C2','B2'),('D2','B2')]:
 d=((p[m2]-act).abs()-(p[m1]-act).abs()).to_numpy();n=len(d);starts=rng.integers(0,n,size=(10000,int(np.ceil(n/6))));ix=(starts[:,:,None]+np.arange(6))%n;means=d[ix.reshape(10000,-1)[:,:n]].mean(axis=1)
 boot.append(dict(model=m1,benchmark=m2,MAE_improvement=float(d.mean()),CI95=np.quantile(means,[.025,.975]).tolist()))
live=a[a.period=='2026-09'].set_index('model').forecast.to_dict();err=a[(a.model=='B2')&(a.period>='2019-01')&(a.period<'2026-09')];errors=err.actual-err.forecast
summary=dict(live=live,bootstrap=boot,headline_B2_error_quantiles=errors.quantile([.05,.1,.25,.5,.75,.9,.95]).to_dict())
pred=live['B2'];summary['headline_yoy']=(ca.loc['2026-08','All-items']*(1+pred/100)/ca.loc['2025-09','All-items']-1)*100
summary['headline_index']=ca.loc['2026-08','All-items']*(1+pred/100)
ss=json.load(open(O/'supplement_summary.json'));summary['headline_sa']=pred+ss['seasonal_bridges'][0]['forecast_bridge']
# Contributions for the selected direct Canadian model; decomposition within parent is an attribution bridge.
c=pd.read_csv(O/'contributions.csv');c=c.iloc[:8].copy();c=c.set_index('component');lw=json.load(open(O/'live_component_forecasts.json'));ws=json.load(open(O/'live_weights.json'))['weights']
gas=lw['Gasoline']['B'];gasbase=lw['Gasoline']['A'];c.loc['Transportation','contribution']+=ws['Gasoline']*(gas-gasbase)
for name,model in [('Fuel oil and other fuels','direct'),("Homeowners' replacement cost",'lag_NHPI')]:
 z=extra[(extra.period=='2026-09')&(extra.component==name)&(extra.model==model)].iloc[0];c.loc['Shelter','contribution']+=ws[name]*(z.forecast-z.baseline)
for name in c.index:c.loc[name,'mom']=100*c.loc[name,'contribution']/c.loc[name,'weight']
c['status']='modeled';c.loc['Transportation','status']='Canadian gasoline bridge plus modeled remainder';c.loc['Shelter','status']='Canadian heating-oil/NHPI bridges plus modeled remainder';c.to_csv(O/'final_major_contributions.csv')
detail=[dict(component=n,contribution=float(c.loc[n,'contribution'])) for n in c.index if n not in ['Shelter','Transportation']]
detail+=[dict(component='Gasoline',contribution=ws['Gasoline']*gas),dict(component='Transportation excluding gasoline',contribution=float(c.loc['Transportation','contribution'])-ws['Gasoline']*gas)]
fuel=extra[(extra.period=='2026-09')&(extra.component=='Fuel oil and other fuels')].forecast.iloc[0];detail+=[dict(component='Fuel oil and other fuels',contribution=ws['Fuel oil and other fuels']*fuel),dict(component='Shelter excluding fuel oil',contribution=float(c.loc['Shelter','contribution'])-ws['Fuel oil and other fuels']*fuel)]
pd.DataFrame(detail).to_csv(O/'final_contributions.csv',index=False)
assert abs(sum(x['contribution'] for x in detail)-pred)<1e-8
# Core 3/6-month mean ensemble, evaluated against first-published YoY.
v=pd.read_csv(O/'core_vintage_predictions.csv');core=pd.read_csv(R/'18100256_canada.csv').pivot(index='REF_DATE',columns='Alternative measures',values='VALUE');cr=[]
for typ in ['trim','median']:
 g=v[v.measure==typ].pivot(index='period',columns='model',values='forecast').dropna();actual=v[v.measure==typ].drop_duplicates('period').set_index('period').actual;est=.5*(g.mean3+g.mean6);er=actual.reindex(g.index)-est
 cr.append(dict(measure=typ,model='ensemble3_6',**stats(pd.DataFrame({'actual':actual.reindex(g.index),'forecast':est}))))
 idx=core[[n for n in core if 'CPI-'+typ+' (index' in n][0]];mom=idx.pct_change(fill_method=None)*100;m=.5*(mom.tail(3).mean()+mom.tail(6).mean());level=idx.iloc[-1]*(1+m/100);yy=(level/idx.loc['2025-09']-1)*100
 summary[typ]=dict(mom=float(m),yoy=float(yy),annualized3m=float(((level/idx.loc['2026-06'])**4-1)*100),error10_90=er.quantile([.1,.9]).tolist())
pd.DataFrame(cr).to_csv(O/'core_ensemble_metrics.csv',index=False)
# Cross-border comparison table, all statistics calculated on monthly changes.
cor=pd.read_csv(O/'correlations.csv');met=pd.read_csv(O/'component_metrics.csv');out=[]
for n in cor.component.unique():
 q=cor[cor.component==n].set_index('regime');m=met[(met.component==n)&(met.regime=='all')].set_index('model');row={'component':n,**{k:float(q.loc['full',k]) for k in ['correlation_mom','correlation_deseasonalized','lag1_correlation','beta_us_month_fx_oil']}}
 for reg in ['pre2020','post2020','post2022method','trade2025']:row['r_'+reg]=q.loc[reg,'correlation_mom'] if reg in q.index else np.nan
 for model in ['A','Canada','US','USfx','USlag','PPI','C']:row['MAE_'+model]=m.loc[model,'MAE']
 row['rolling60_min']=lw[n].get('rolling_corr_min');row['rolling60_max']=lw[n].get('rolling_corr_max');out.append(row)
pd.DataFrame(out).to_csv(O/'cross_border_summary.csv',index=False)
(O/'final_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2));print(pd.DataFrame(metrics).to_string(index=False))

```

## evidence/README.md

```md
# Canadian September 2026 CPI research evidence

Research-only snapshot. Quantitative information cutoff: October 16, 2026. Completed October 17. No production modules are imported and no production files are written.

Read the accompanying `Canadian-CPI-September-2026-Research.md` first. This is an exploratory, latest-history pseudo-out-of-sample study with actual U.S./Canadian release-order gates. It is not a completely vintage-clean forecast experiment. The core release-vintage test is separately identified and ends in March 2026 reference data.

## Reproduce

Requires Python 3.12, numpy, pandas 2.2 or newer, beautifulsoup4. All required inputs are included; no network calls are made by the analysis scripts.

Run in this order from the evidence directory:

```bash
python analyze.py
python supplement.py
python sa_diagnostics.py
python finalize_analysis.py
```

`analyze.py` regenerates the long component experiment and original aggregate models. `supplement.py` evaluates Canadian direct bridges, tax-inclusive approximate core reconstruction, official core vintage forecasts and Canadian seasonal bridges. `sa_diagnostics.py` checks official-SA aggregate pairs and lags 0–3. `finalize_analysis.py` combines the evaluated direct bridges, generates final contributions and block-bootstrap comparisons, and evaluates the simple core ensemble.

The report recommends B2, not the numerically marginally best C2. All result CSVs retain precision beyond the rounded report. Additional small diagnostic tables (bias correction, YoY error conversion, SA bridge scoring and research registry) are retained for inspection; the four commands reproduce the central forecast and principal backtests.

## Main evidence files

* `results/final_summary.json`: final estimates, error quantiles, block-bootstrap intervals.
* `results/final_aggregate_predictions.csv`: every headline model forecast and actual.
* `results/final_aggregate_metrics.csv`: headline MAE, RMSE, bias, direction and regime slices.
* `results/final_contributions.csv`: disjoint monthly contribution table that sums to B2.
* `results/component_predictions.csv` and `component_metrics.csv`: component-level predictions and all benchmark scores.
* `results/cross_border_summary.csv`, `correlations.csv`, `lag_correlations.csv`: monthly correlations, controls, regime splits and rolling ranges.
* `results/cross_border_mapping.csv`: exact Canadian vectors and U.S. CPI/PPI identifiers.
* `results/additional_component_predictions.csv`: Canadian pump/furnace/NHPI/mortgage bridge tests.
* `results/core_reconstruction.csv`: clearly labeled tax-inclusive research proxy, not official core.
* `results/core_vintage_predictions.csv`: forecasts based on the prior release's history, scored against the next first-published official YoY.
* `results/sa_predictions.csv`: separate official-SA aggregate experiment, using latest revised histories.
* `results/calendar_gates.json` and `raw/release_calendar.json`: actual-date eligibility, excluding same-day U.S. releases.
* `results/component_registry_research.csv`: published August Canadian vectors, 2025 link weights and legacy-55 flags; not a production registry.
* `core55_names.json`: official legacy appendix labels. Their directly matched current weights cover 99.19%, not 100%.

## Source provenance

Statistics Canada complete-table CSV endpoints follow `https://www150.statcan.gc.ca/n1/tbl/csv/TABLE-eng.zip`. Included normalized national extracts are from 18100004, 18100006, 18100007, 18100256 and 18100259. NHPI is 18100205; lending rates/balances are 10100006. The source ZIP hashes initially recorded are in `raw/downloads.json`; table metadata is also retained.

BLS CPI normalized input is filtered from `https://download.bls.gov/pub/time.series/cu/cu.data.0.Current`, with identities from `cu.series`. Selected PPI data come from `https://download.bls.gov/pub/time.series/wp/wp.data.0.Current`. The analysis does not need the large unfiltered bulk files because normalized/selected observations are included. Actual release dates were extracted from BLS archived-release pages and StatCan vintage-release dates plus 2026 published dates. Missing October 2025 CPI and other release-order exceptions are not assumed available. Lagged U.S. predictors also require their release to precede Canada's target release.

NRCan HTML follows `https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm?productID=1&locationID=66&frequency=M&priceYear=2026`, varying year and product: 1 gasoline, 7 furnace oil, 5 diesel. The analysis discards months later than September 2026 even if a captured page contains an October partial-month value. Historical publication timestamps are not fully reconstructed.

FX and oil are FRED graph CSVs for DEXCAUS (Federal Reserve Board daily CAD per USD) and DCOILWTICO (EIA WTI). Daily observations are aggregated to reference-month means before computing changes; October values never enter September predictors. FRED is the distribution route, not a claim that the Canadian CPI uses these series.

The repository was inspected at commit `887c93436fe8b65b2b05c04c879543de28df842c`; its files were not changed. The report describes reusable architecture rather than importing the U.S. economic mappings.

## Interpretation limits

No full historical consensus panel was acquired. No claim of beating consensus is made. Data-source availability and vintage limitations are detailed in the report. In particular, revised PPI and SA histories may flatter pseudo-out-of-sample results; retrospective NRCan pages do not prove their exact historical posting times. The direct-model design was selected in exploratory research, not tested on a subsequently untouched sample. Preserve this caveat when reusing any metric.

```