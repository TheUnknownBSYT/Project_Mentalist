import unittest,tempfile,threading,time,datetime as dt,json,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scanner
from test_scanner import series

class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(scanner,'STATE',Path(self.tmp.name));self.patch.start()
        self.data={'symbol':'TEST','bars':series(),'fetchedAt':scanner.now(),'sessionDate':str(dt.datetime.now(scanner.IST).date()),'quality':{'omittedIncompleteDates':[]}}
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_repeated_history_reuses_disk_without_network(self):
        with patch.object(scanner,'download_history',return_value=self.data) as fetch:
            self.assertEqual(scanner.history('TEST'),scanner.history('TEST'));self.assertEqual(fetch.call_count,1)
    def test_concurrent_same_symbol_fetch_is_deduplicated(self):
        with patch.object(scanner,'download_history',return_value=self.data) as fetch,ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(scanner.history,['TEST']*5));self.assertEqual(fetch.call_count,1)
    def test_next_session_invalidates_cache(self):
        stale={**self.data,'sessionDate':'2020-01-01'};scanner.atomic(scanner.STATE/'history/TEST.json.gz',stale)
        with patch.object(scanner,'download_history',return_value=self.data) as fetch:scanner.history('TEST');self.assertEqual(fetch.call_count,1)
    def test_corrupt_cache_is_refetched(self):
        p=scanner.STATE/'history/TEST.json.gz';p.parent.mkdir();p.write_bytes(b'invalid gzip')
        with patch.object(scanner,'download_history',return_value=self.data) as fetch:scanner.history('TEST');self.assertEqual(fetch.call_count,1)
    def test_failure_backoff_prevents_repeat_requests(self):
        with patch.object(scanner,'download_history',side_effect=OSError('offline')) as fetch:
            for _ in range(2):
                with self.assertRaises(Exception):scanner.history('TEST')
            self.assertEqual(fetch.call_count,1)
    def test_worker_refills_before_slowest_finishes(self):
        released=threading.Event();order=[]
        def work(symbol):
            if symbol=='SLOW':released.wait(1)
            if symbol=='NEXT':released.set()
            order.append(symbol);return symbol
        jobs=list(scanner.completed_jobs([{'symbol':s} for s in ['SLOW','FAST','NEXT']],work,2))
        self.assertEqual(len(jobs),3);self.assertLess(order.index('NEXT'),order.index('SLOW'))
    def test_unchanged_poll_omits_rows(self):
        snapshot=scanner.snapshot();small=scanner.snapshot(snapshot['version']);self.assertEqual(small,{'unchanged':True,'version':snapshot['version']})
    def test_universe_cache_avoids_http(self):
        scanner.atomic(scanner.STATE/'universe.json',{'records':[],'fetchedAt':scanner.now()})
        with patch.object(scanner,'request') as request:scanner.universe();request.assert_not_called()

if __name__=='__main__':unittest.main()
