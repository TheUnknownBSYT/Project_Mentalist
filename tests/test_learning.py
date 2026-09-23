import unittest,tempfile,datetime as dt,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from learning import Learner,IST
from test_scanner import series

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'learn.sqlite';self.l=Learner(self.path)
        self.a=series(550,.001);self.b=series(550,.0002)
        self.date=lambda i:dt.datetime.fromisoformat(self.a[i]['date']+'T12:00:00+05:30')
    def tearDown(self):self.tmp.cleanup()
    def initial(self):return self.l.observe('TEST',self.a[:400],self.b[:400],self.date(400))
    def test_initial_forecasts_recorded_but_warmup_not_accuracy(self):
        r=self.initial();self.assertEqual(len(r['predictions']),2);s=self.l.summary();self.assertEqual(s['pending'],2);self.assertTrue(all(m['evaluated']==0 and m['historicalTraining']>0 for m in s['metrics']))
    def test_repeat_scan_does_not_change_prediction_or_retrain(self):
        a=self.initial();summary=self.l.summary();b=self.initial();self.assertEqual(a,b);self.assertEqual(summary,self.l.summary())
    def test_future_rows_cannot_change_issue_prediction(self):
        a=self.initial()
        other=Learner(Path(self.tmp.name)/'other.sqlite')
        b=other.observe('TEST',self.a,self.b,self.date(400))
        self.assertEqual(a,b)
    def test_only_finished_horizon_learns_and_issue_is_immutable(self):
        original=self.initial()['predictions'][0]
        self.l.observe('TEST',self.a[:405],self.b[:405],self.date(405))
        self.assertEqual(self.l.summary()['metrics'][0]['forwardTotal'],0)
        self.l.observe('TEST',self.a[:407],self.b[:407],self.date(407))
        summary=self.l.summary();self.assertEqual(summary['metrics'][0]['forwardTotal'],1);self.assertEqual(summary['metrics'][1]['forwardTotal'],0)
        old=next(r for r in summary['forecasts'] if r['id']==original['id'])
        self.assertEqual(old['predicted'],original['predicted']);self.assertEqual(old['model_version'],original['model_version']);self.assertEqual(old['entry_date'],self.a[401]['date']);self.assertEqual(old['exit_date'],self.a[406]['date'])
        self.assertAlmostEqual(old['actual'],self.a[406]['open']/self.a[401]['open']*.998/1.002-1)
        self.l.observe('TEST',self.a[:407],self.b[:407],self.date(407));self.assertEqual(self.l.summary()['metrics'][0]['forwardTotal'],1)
    def test_missing_exit_bar_does_not_slide_horizon(self):
        self.initial();stock=self.a[:409];stock=[r for r in stock if r['date']!=self.a[406]['date']]
        self.l.observe('TEST',stock,self.b[:409],self.date(409));self.assertEqual(self.l.summary()['metrics'][0]['forwardTotal'],0)
    def test_reopen_keeps_record_and_model(self):
        self.initial();self.assertEqual(self.l.summary(),Learner(self.path).summary())
    def test_stale_or_misaligned_data_cannot_issue(self):
        self.assertEqual(self.l.observe('TEST',self.a[:390],self.b[:400],self.date(400))['status'],'waiting')
        self.assertEqual(self.l.observe('TEST',self.a[:390],self.b[:390],self.date(400))['status'],'waiting')
        self.assertEqual(self.l.summary()['pending'],0)
    def test_model_coefficients_update_after_label(self):
        self.initial()
        with self.l.connect() as db:before=db.execute('SELECT payload FROM models WHERE horizon=5').fetchone()[0]
        self.l.observe('TEST',self.a[:407],self.b[:407],self.date(407))
        with self.l.connect() as db:after=db.execute('SELECT payload FROM models WHERE horizon=5').fetchone()[0]
        self.assertNotEqual(json.loads(before)['xty'],json.loads(after)['xty'])
    def test_no_overlapping_pending_same_horizon(self):
        self.initial();self.l.observe('TEST',self.a[:401],self.b[:401],self.date(401));self.assertEqual(self.l.summary()['pending'],2)

    def test_today_candle_eligible_only_after_close_buffer(self):
        afternoon=self.date(400).replace(hour=16)
        r=self.l.observe('TEST',self.a[:401],self.b[:401],afternoon)
        self.assertTrue(all(p['asof_date']==self.a[400]['date'] for p in r['predictions']))
        other=Learner(Path(self.tmp.name)/'morning.sqlite')
        morning=other.observe('TEST',self.a[:401],self.b[:401],self.date(400))
        self.assertTrue(all(p['asof_date']==self.a[399]['date'] for p in morning['predictions']))

if __name__=='__main__':unittest.main()
