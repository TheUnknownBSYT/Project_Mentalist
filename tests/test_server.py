import importlib.util
import json
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('server',Path(__file__).resolve().parents[1]/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()
    def get(self,path,headers=None):
        try:
            with urlopen(Request(self.url+path,headers=headers or {})) as response:
                return response.status,response.read(),response.headers
        except HTTPError as error:
            return error.code,error.read(),error.headers
    def test_index_and_health(self):
        status,body,headers=self.get('/')
        self.assertEqual(status,200);self.assertIn(b'Nifty Lab',body)
        self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(self.get('/api/health')[0],200)
    def test_internal_files_not_served(self):
        for path in ['/server.py','/README.md','/../server.py','/tests/test_server.py']:
            self.assertEqual(self.get(path)[0],404)
    def test_invalid_symbols_rejected(self):
        self.assertEqual(self.get('/api/history?symbol=http://evil')[0],400)
    def test_foreign_host_and_origin_rejected(self):
        self.assertEqual(self.get('/',{'Host':'evil.example'})[0],403)
        self.assertEqual(self.get('/',{'Sec-Fetch-Site':'cross-site'})[0],403)
    def test_provider_failure_is_explicit_and_never_synthetic(self):
        with patch.object(server,'fetch_history',side_effect=ValueError('rate limit')):
            status,body,_=self.get('/api/history?symbol=INFY')
            self.assertEqual(status,502);self.assertIn('rate limit',json.loads(body)['error']);self.assertNotIn('bars',json.loads(body))
    def test_mocked_provider_data_flows_through(self):
        with patch.object(server,'fetch_history',return_value={'symbol':'INFY','bars':[]}):
            status,body,_=self.get('/api/history?symbol=INFY')
            self.assertEqual(status,200);self.assertEqual(json.loads(body)['symbol'],'INFY')
    def payload(self):
        return {'chart':{'result':[{'meta':{'currency':'INR'},'timestamp':[1704153600,1704240000], 'indicators':{'quote':[{'open':[100,102],'high':[110,112],'low':[90,92],'close':[100,102],'volume':[1000,1000]}],'adjclose':[{'adjclose':[50,51]}]}}]}}
    def test_adjustment_uses_consistent_ohlc(self):
        rows=server.normalize(self.payload());self.assertEqual(rows[0]['open'],50);self.assertEqual(rows[0]['rawClose'],100)
    def test_wrong_currency_and_missing_prices_rejected(self):
        data=self.payload();data['chart']['result'][0]['meta']['currency']='USD'
        with self.assertRaises(ValueError):server.normalize(data)
        data=self.payload();data['chart']['result'][0]['indicators']['quote'][0]['open'][0]=None
        with self.assertRaises(ValueError):server.normalize(data)

if __name__=='__main__':unittest.main()
