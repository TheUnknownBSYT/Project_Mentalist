import unittest,sys,datetime as dt,math,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scanner

def series(n=420,growth=.001):
    rows=[];d=dt.date(2024,1,1)
    for i in range(n):
        price=100*math.exp(growth*i)*(1+.008*math.sin(i/6))
        rows.append(dict(date=str(d+dt.timedelta(days=i)),open=price,high=price*1.01,low=price*.99,close=price,rawClose=price,volume=2_000_000))
    return rows

class ScannerTests(unittest.TestCase):
    def setUp(self):self.a=series();self.b=series(growth=.0003);self.today=dt.date.fromisoformat(self.a[-1]['date'])+dt.timedelta(days=1)
    def score(self,a=None,b=None,today=None):return scanner.scores(a or self.a,b or self.b,'TEST','Test',today or self.today)
    def test_three_scores_bounded_and_combined_weighted(self):
        r=self.score();self.assertTrue(all(0<=r[k]<=100 for k in ['long','short','combined']));self.assertEqual(r['combined'],round(.6*r['long']+.4*r['short'],1))
    def test_future_rows_cannot_change_past_scores(self):
        r=self.score();future=series(500);future[-1]['close']=1e9
        s=self.score(self.a+future[420:],self.b+future[420:])
        for k in ('long','short','combined','entry','riskReview'):self.assertEqual(r[k],s[k])
    def test_insufficient_history_explicit(self):
        with self.assertRaisesRegex(ValueError,'260'):self.score(self.a[:200],self.b[:200])
    def test_stale_cannot_rank_or_enter(self):
        r=self.score(today=self.today+dt.timedelta(days=30));self.assertFalse(r['eligible']);self.assertFalse(r['entry']);self.assertFalse(r['riskReview'])
    def test_low_liquidity_filtered(self):
        for row in self.a:row['volume']=1
        r=self.score();self.assertFalse(r['eligible']);self.assertEqual(r['action'],'LOW LIQUIDITY')
    def test_market_regime_blocks_entry(self):
        r=self.score(b=series(growth=-.002));self.assertFalse(r['entry']);self.assertFalse(r['marketOn'])
    def test_breakdown_requires_long_trend_and_month_loss(self):
        for row in self.a[-20:]:
            for k in ['close','high','low','open','rawClose']:row[k]*=.7
        self.assertTrue(self.score()['riskReview'])
    def test_missing_benchmark_sessions_are_aligned(self):
        r=self.score(b=self.b[:-3]);self.assertEqual(r['date'],self.b[-4]['date'])
    def test_news_symbol_cannot_be_url(self):
        with self.assertRaises(ValueError):scanner.news('http://evil')
    def test_checkpoint_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';scanner.atomic(p,{'rows':{'TEST':self.score()}});self.assertEqual(json.loads(p.read_text())['rows']['TEST']['symbol'],'TEST')
    def test_duplicate_scan_not_started(self):
        with patch.dict(scanner.STATUS,{'running':True}):self.assertFalse(scanner.start())
    def test_official_universe_parser_filters_and_deduplicates(self):
        records=scanner.parse_universe(b'SYMBOL,NAME OF COMPANY, SERIES\nTEST,Test Limited,EQ\nTEST,Test Limited,EQ\nOTHER,Other Limited,BE\n')
        self.assertEqual(records,[{'symbol':'TEST','name':'Test Limited','series':'EQ'}])

    def test_scan_visits_all_universe_entries_and_counts_failures(self):
        import copy
        old=copy.deepcopy(scanner.STATUS)
        records=[{'symbol':s,'name':s,'series':'EQ'} for s in ['AAA','BBB','IPO']]
        def hist(symbol):return {'bars':self.a[:50] if symbol=='IPO' else self.a,'quality':{'omittedIncompleteDates':[]}}
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(scanner,'STATE',Path(tmp)),patch.object(scanner,'universe',return_value={'records':records,'fetchedAt':'2026-09-20'}),patch.object(scanner,'history',side_effect=hist),patch.object(scanner.time,'sleep'),patch.object(scanner,'LEARNER',None):
                scanner.STATUS.update(rows={},errors={},running=True)
                scanner.scan();self.assertEqual(scanner.STATUS['done'],3);self.assertEqual(scanner.STATUS['total'],3);self.assertEqual(set(scanner.STATUS['rows']),{'AAA','BBB'});self.assertIn('IPO',scanner.STATUS['errors']);self.assertFalse(scanner.STATUS['running'])
        finally:scanner.STATUS.clear();scanner.STATUS.update(old)
    def test_failed_refresh_cannot_leave_an_actionable_old_row(self):
        with patch.dict(scanner.STATUS,{'rows':{'TEST':self.score()},'errors':{'TEST':'connection failed'}}):
            row=scanner.snapshot()['rows'][0];self.assertFalse(row['entry']);self.assertFalse(row['eligible']);self.assertFalse(row['riskReview']);self.assertEqual(row['refreshError'],'connection failed')

if __name__=='__main__':unittest.main()
