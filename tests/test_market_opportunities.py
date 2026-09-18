import json
import math
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from scripts.market_opportunities import summarize, relationship, build_opportunities
from scripts.cross_asset_data import parse_fred, parse_yahoo, collect_cross_assets, public_snapshot, SERIES

TODAY=date(2026,9,18)
def series(n=300, fn=lambda i:100+math.sin(i)):
    return {TODAY-timedelta(days=n-i-1):fn(i) for i in range(n)}

class AnalyticsTests(unittest.TestCase):
    def test_baseline_excludes_current_and_has_minimum(self):
        s=series();s[TODAY]=1000
        m=summarize(s,unit='bp',kind='difference',today=TODAY)
        self.assertEqual(m['n'],252);self.assertEqual(m['percentile'],100);self.assertGreater(m['z'],100)
        m=summarize(series(40),unit='bp',kind='difference',today=TODAY)
        self.assertIsNone(m['z']);self.assertIsNone(m['percentile']);self.assertIsNone(m['moves']['1D']['z'])
    def test_constant_sample_is_not_a_zero_z_signal(self):
        m=summarize(series(fn=lambda i:2),unit='bp',kind='difference',today=TODAY)
        self.assertIsNone(m['z']);self.assertIsNone(m['moves']['5D']['z'])
    def test_signed_moves_and_staleness(self):
        s=series(fn=lambda i:100+i)
        m=summarize(s,unit='bp',kind='difference',today=TODAY+timedelta(days=5))
        self.assertEqual(m['status'],'stale');self.assertEqual(m['moves']['5D']['value'],5)
        m=summarize(s,unit='spot',kind='price',today=TODAY)
        self.assertAlmostEqual(m['moves']['5D']['value'],100*math.log(399/394))
    def test_future_observations_excluded(self):
        s=series();s[TODAY+timedelta(days=1)]=1e9
        self.assertEqual(summarize(s,unit='bp',kind='difference',today=TODAY)['as_of'],TODAY.isoformat())
    def test_regression_out_of_sample_residual(self):
        x=series(fn=lambda i:100+i*.1+math.sin(i*.7))
        y={d:2*v+.01*math.sin(i*1.3) for i,(d,v) in enumerate(x.items())}
        y[TODAY]+=2
        m=relationship(y,x,y_kind='difference',x_kind='difference',today=TODAY)
        self.assertEqual(m['status'],'ok');self.assertAlmostEqual(m['beta'],2,places=2)
        self.assertGreater(m['z'],20);self.assertGreater(m['correlation'],.99)
        self.assertEqual(m['n'],126)
    def test_missing_common_dates_and_constant_fit(self):
        x=series(150);y={d+timedelta(days=1000):v for d,v in x.items()}
        self.assertEqual(relationship(y,x,today=TODAY)['status'],'insufficient')
        self.assertEqual(relationship(series(fn=lambda i:2),x,today=TODAY)['status'],'insufficient')
    def test_long_gaps_are_not_daily_changes(self):
        x={TODAY-timedelta(days=i*7):100+i for i in range(200)}
        self.assertEqual(relationship(x,x,today=TODAY)['n'],0)
    def test_curve_fly_units_common_dates_and_carry_orientation(self):
        rates={c:{t:series(fn=lambda i,v=v:v+.001*math.sin(i)) for t,v in [('2Y',2),('5Y',3),('10Y',3.5)]} for c in ['US','CA','AU','NZ']}
        rates['US']['2Y']=series(fn=lambda i:4)
        fx={'USDCAD':series(fn=lambda i:1.3+.01*math.sin(i))}
        p=build_opportunities(rates,fx,{}, {},TODAY)
        fly=next(s for s in p['series'] if s['id']=='CA_2s5s10s')
        self.assertAlmostEqual(fly['value'],50)
        r=p['carry'][0];self.assertEqual(r['long'],'USD');self.assertEqual(r['short'],'CAD')
        self.assertGreater(r['ratio'],0);self.assertAlmostEqual(r['differential_bps'],200-.1*math.sin(299))
    def test_parser_rejects_html_and_nonfinite(self):
        with self.assertRaises(ValueError):parse_fred(b'<html>bad</html>','X',TODAY,TODAY)
        s=parse_fred(b'observation_date,X\n2026-09-17,NaN\n2026-09-18,5\n','X',TODAY-timedelta(days=2),TODAY)
        self.assertEqual(s,{TODAY:5})
    def test_yahoo_excludes_unfinished_bar(self):
        def stamp(d):return int(__import__('datetime').datetime.combine(d,__import__('datetime').time(),tzinfo=__import__('datetime').timezone.utc).timestamp())
        blob=json.dumps({'chart':{'result':[{'timestamp':[stamp(TODAY-timedelta(days=1)),stamp(TODAY)],'indicators':{'quote':[{'close':[100,999]}]}}]}}).encode()
        self.assertEqual(list(parse_yahoo(blob,TODAY-timedelta(days=2),TODAY).values()),[100])
    def test_live_overnight_uses_current_generator(self):
        import tempfile
        from pathlib import Path
        from scripts.overnight.collect import collect_inputs
        from scripts.overnight.store import OvernightStore
        payload={'status':'ok','generated_at':'2026-09-18T20:00:00Z','cross_assets':{'series':{'GOLD':{'status':'ok'}}}}
        with tempfile.TemporaryDirectory() as temp, patch('scripts.market_state.build_snapshot',return_value=payload) as generator, patch('scripts.market_state.validate_snapshot') as validator:
            result=collect_inputs(OvernightStore(root=Path(__file__).resolve().parents[1],state_root=Path(temp)),run_id='overnight-20260918-test',offline=False)
            generator.assert_called_once_with();validator.assert_called_once_with(payload)
            self.assertEqual(result['families']['market_state']['status'],'fresh')
            self.assertIn('GOLD',result['families']['market_state']['data']['cross_assets']['series'])

    def test_public_snapshot_preserves_internal_data(self):
        packet={'opportunities':{'series':[{'id':'SP500','value':100,'history':[['2026-09-18',100]],'note':'Index','z':2}, {'id':'HY_OAS','value':270,'history':[], 'z':1,'moves':{'1D':1}}]}, 'cross_assets':{'series':{'HY_OAS':{'status':'ok'}}}}
        out=public_snapshot(packet)
        self.assertEqual(packet['opportunities']['series'][0]['value'],100)
        self.assertIsNone(out['opportunities']['series'][0]['value'])
        self.assertEqual(out['opportunities']['series'][0]['z'],2)
        self.assertEqual(out['opportunities']['series'][1]['status'],'internal_only')
        self.assertIsNone(out['opportunities']['series'][1]['z'])

    def test_source_failure_explicit_no_substitute(self):
        def fail(*args,**kwargs):raise ValueError('offline')
        raw,meta=collect_cross_assets(TODAY-timedelta(days=10),TODAY,fail)
        self.assertEqual(set(meta),set(SERIES));self.assertTrue(all(m['status']=='unavailable' for m in meta.values()))
        self.assertTrue(all(not v for v in raw.values()))

if __name__=='__main__':unittest.main()
