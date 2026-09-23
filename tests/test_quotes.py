import unittest,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import quotes
from learning import fit_one,new_model

class QuoteTests(unittest.TestCase):
    def payload(self):return {'chart':{'result':[{'meta':{'currency':'INR','regularMarketPrice':450,'chartPreviousClose':440,'regularMarketTime':1770000000}}]}}
    def test_daily_change_uses_previous_close(self):
        q=quotes.parse(self.payload(),'COALINDIA')
        self.assertEqual(q['change'],10)
        self.assertAlmostEqual(q['changePercent'],10/440)
    def test_missing_previous_close_is_not_zero_change(self):
        p=self.payload();del p['chart']['result'][0]['meta']['chartPreviousClose']
        with self.assertRaises(ValueError):quotes.parse(p,'COALINDIA')
    def test_invalid_quote_rejected(self):
        p=self.payload();p['chart']['result'][0]['meta']['regularMarketPrice']=float('nan')
        with self.assertRaises(ValueError):quotes.parse(p,'COALINDIA')
    def test_failed_refresh_preserves_timestamped_quote(self):
        q=quotes.parse(self.payload(),'TEST')
        with patch.object(quotes,'WATCH',{'TEST'}),patch.object(quotes,'QUOTES',{'TEST':q}),patch.object(quotes,'ERRORS',{}),patch.object(quotes,'fetch',side_effect=ValueError('offline')):
            quotes.refresh();s=quotes.snapshot()
            self.assertEqual(s['quotes']['TEST'],q);self.assertEqual(s['errors']['TEST'],'offline')
    def test_forward_update_decays_old_weight_once(self):
        m=new_model();x=[1.0]*9
        fit_one(m,x,.1,'historical');fit_one(m,x,.2,'forward')
        self.assertAlmostEqual(m['xtx'][0][0],1.995)
        self.assertEqual(m['forward'],1);self.assertEqual(m['historical'],1)
