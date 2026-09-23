"""Separate indicative quotes from completed candles used for model training."""
import datetime as dt
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import scanner

LOCK=threading.RLock()
SAVED=scanner.read_json(scanner.STATE/'quote-watch.json') or {}
WATCH=set(SAVED.get('symbols',scanner.PRIORITY[:5]))
QUOTES={}
ERRORS={}
LAST=None

def parse(payload,symbol):
    meta=payload['chart']['result'][0]['meta']
    price=meta.get('regularMarketPrice')
    previous=meta.get('chartPreviousClose',meta.get('previousClose'))
    stamp=meta.get('regularMarketTime')
    if meta.get('currency')!='INR' or not all(isinstance(v,(float,int)) and math.isfinite(v) and v>0 for v in (price,previous,stamp)):
        raise ValueError('Provider quote is incomplete')
    return dict(symbol=symbol,price=price,previousClose=previous,change=price-previous,changePercent=price/previous-1,quoteTime=dt.datetime.fromtimestamp(stamp,dt.timezone.utc).isoformat(),fetchedAt=scanner.now(),source='Yahoo Finance · indicative, may be delayed')

def fetch(symbol):
    payload=json.loads(scanner.request('https://query1.finance.yahoo.com/v8/finance/chart/'+quote(symbol+'.NS',safe='')+'?range=1d&interval=1m'))
    return parse(payload,symbol)

def refresh():
    global LAST
    with LOCK: symbols=list(WATCH)
    def one(symbol):
        try:
            q=fetch(symbol)
            with LOCK:QUOTES[symbol]=q;ERRORS.pop(symbol,None)
        except Exception as exc:
            with LOCK:ERRORS[symbol]=str(exc)[:180]
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(one,symbols))
    with LOCK:LAST=scanner.now()

def snapshot():
    with LOCK:return dict(quotes=dict(QUOTES),errors=dict(ERRORS),lastAttempt=LAST,intervalSeconds=60)

def run(stop):
    while not stop.is_set():
        refresh()
        stop.wait(60)
