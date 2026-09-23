#!/usr/bin/env python3
"""Optional localhost-only market proxy. Python 3.10+, standard library only."""
import argparse
import webbrowser
import datetime as dt
import json
import math
from pathlib import Path
import re
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
FILES = {'/usability.js':'usability.js','/learning-ui.js':'learning-ui.js','/scanner-ui.js':'scanner-ui.js','/scan-seed.js':'scan-seed.js','/portfolio-seed.js':'portfolio-seed.js','/market-data.js':'market-data.js','/': 'index.html', '/index.html': 'index.html', '/core.js': 'core.js', '/app.js': 'app.js', '/style.css': 'style.css'}
TYPES = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}
CACHE = {}
LOCK = threading.Lock()
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def normalize(payload, details=False):
    result = payload.get('chart', {}).get('result')
    if not result:
        raise ValueError('Provider returned no instrument data.')
    obj = result[0]
    if obj.get('meta', {}).get('currency') != 'INR':
        raise ValueError('Expected an INR instrument.')
    q = obj['indicators']['quote'][0]
    adj = obj['indicators']['adjclose'][0]['adjclose']
    clock = dt.datetime.now(IST)
    today = clock.date()
    rows = []
    skipped = []
    for i, timestamp in enumerate(obj['timestamp']):
        day = dt.datetime.fromtimestamp(timestamp, IST).date()
        if day > today or (day == today and clock.hour < 16):
            continue
        values = [q[k][i] for k in ('open','high','low','close','volume')] + [adj[i]]
        if any(v is None or not isinstance(v, (int,float)) or not math.isfinite(v) for v in values):
            skipped.append(str(day))
            continue
        opening, high, low, closing, volume, adjusted = values
        if min(opening, high, low, closing, adjusted) <= 0 or volume < 0:
            raise ValueError('Invalid price values from provider.')
        if high < max(opening,closing) or low > min(opening,closing) or high < low:
            raise ValueError('Inconsistent OHLC values from provider.')
        if rows and str(day) <= rows[-1]['date']:
            raise ValueError('Duplicate or unordered provider dates.')
        factor = adjusted / closing
        rows.append(dict(date=str(day), open=opening*factor, high=high*factor,
                         low=low*factor, close=adjusted, rawClose=closing, volume=volume))
    if len(rows) < 2:
        raise ValueError('Insufficient completed price history.')
    return (rows,skipped) if details else rows


def fetch_history(symbol):
    # Share the scanner's disk cache and in-flight symbol lock with research requests.
    from scanner import history
    return history(symbol)


class Handler(BaseHTTPRequestHandler):
    def send(self, code, content, mime='application/json'):
        self.send_response(code)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(content)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'} or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403,b'{"error":"Local access only"}')
        if self.path == '/api/watch':
            import quotes
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0 < length <= 4096: raise ValueError('Invalid request size')
                symbols=json.loads(self.rfile.read(length)).get('symbols')
                if not isinstance(symbols,list) or len(symbols)>40 or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',s) for s in symbols):raise ValueError('Invalid symbols')
                with quotes.LOCK:quotes.WATCH=set(symbols)
                quotes.scanner.atomic(quotes.scanner.STATE/'quote-watch.json',{'symbols':symbols})
                return self.send(200,b'{"ok":true}')
            except (ValueError,TypeError):return self.send(400,b'{"error":"Invalid watch request"}')
        if self.path != '/api/scan': return self.send(404,b'{}')
        import scanner
        scanner.start()
        self.send(202,b'{"started":true}')

    def do_GET(self):
        # Reject foreign origins and DNS rebinding; never expose a generic proxy.
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            return self.send(403,b'{"error":"Local access only."}')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403,b'{"error":"Cross-site access denied."}')
        parsed = urlparse(self.path)
        if parsed.path == '/api/quotes':
            import quotes
            return self.send(200,json.dumps(quotes.snapshot(),allow_nan=False).encode())
        if parsed.path == '/api/learning':
            import scanner
            symbol=parse_qs(parsed.query).get('symbol',[None])[0]
            if symbol and not re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',symbol):return self.send(400,b'{"error":"Invalid symbol"}')
            return self.send(200,json.dumps(scanner.learner().summary(symbol),allow_nan=False).encode())
        if parsed.path == '/api/scan':
            import scanner
            return self.send(200,json.dumps(scanner.snapshot(parse_qs(parsed.query).get('since',[None])[0]),allow_nan=False).encode())
        if parsed.path == '/api/news':
            import scanner
            try: return self.send(200,json.dumps(scanner.news(parse_qs(parsed.query).get('symbol',[''])[0])).encode())
            except Exception as exc: return self.send(502,json.dumps({'error':str(exc)}).encode())
        if parsed.path == '/api/health':
            return self.send(200,b'{"ok":true}')
        if parsed.path == '/api/history':
            symbol = parse_qs(parsed.query).get('symbol',[''])[0].upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',symbol):
                return self.send(400,b'{"error":"Invalid NSE symbol."}')
            try:
                return self.send(200,json.dumps(fetch_history(symbol),allow_nan=False).encode())
            except Exception as exc:
                # Never substitute synthetic data for a failed real request.
                message = 'Market history unavailable. The provider may be blocked or rate-limited. Import price CSVs or retry later. ' + str(exc)[:180]
                return self.send(502,json.dumps({'error':message}).encode())
        filename = FILES.get(parsed.path)
        if not filename:
            return self.send(404,b'{"error":"Not found."}')
        path=ROOT/filename
        if not path.exists() and filename in ('market-data.js','portfolio-seed.js','scan-seed.js'):
            variable={'market-data.js':'NIFTY_DATA','portfolio-seed.js':'NIFTY_PORTFOLIO','scan-seed.js':'NIFTY_SCAN'}[filename]
            return self.send(200,('window.'+variable+'='+('[]' if filename=='portfolio-seed.js' else '{}')+';').encode(),TYPES['.js'])
        self.send(200,path.read_bytes(),TYPES[path.suffix])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--no-scan',action='store_true',help='Developer option: do not start background scan')
    args=parser.parse_args()
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        raise SystemExit(f'Cannot start on port {args.port}: {exc}. Try --port 8766.')
    import scanner
    stop_event=threading.Event()
    if not args.no_scan:
        scanner.start()
        import quotes
        threading.Thread(target=quotes.run,args=(stop_event,),daemon=True).start()
        def rescan():
            while not stop_event.wait(1800):scanner.start()
        threading.Thread(target=rescan,daemon=True).start()
    if args.open: threading.Timer(.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    print(f'Open http://127.0.0.1:{args.port} — Ctrl+C to stop.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__=='__main__':
    main()
