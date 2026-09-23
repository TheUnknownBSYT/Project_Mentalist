"""NSE-wide, resumable EOD research scanner. Standard library; no orders."""
import csv, io, json, math, statistics, threading, time, datetime as dt
import gzip, os, tempfile, re, hashlib
from urllib.error import HTTPError
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from urllib.request import Request, urlopen
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.scanner'
UNIVERSE_URL='https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv'
PRIORITY=['JSWENERGY','HINDCOPPER','TATASTEEL','PERSISTENT','COALINDIA','RELIANCE','INFY','HDFCBANK','ICICIBANK','TCS','LT','ITC','SUNPHARMA','SBIN','BHARTIARTL','HINDUNILVR']
LOCK=threading.RLock()
STATUS={'running':False,'total':0,'done':0,'rows':{},'errors':{},'message':'Starting scanner','updatedAt':None}
NEWS={}
LEARNER=None

def learner():
    global LEARNER
    with LOCK:
        if LEARNER is None:
            from learning import Learner
            LEARNER=Learner(STATE/'learning.sqlite')
        return LEARNER

# Bounded concurrency: removing batch barriers matters more than flooding the feed.
WORKERS=max(1,min(16,int(os.environ.get('MENTALIST_SCAN_WORKERS','8'))))
HISTORY_TTL=1800
UNIVERSE_TTL=24*3600
CACHE_LOCKS={}
BACKOFF_UNTIL=0.0
IST=dt.timezone(dt.timedelta(hours=5,minutes=30))


def cache_age(payload):
    try:
        age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(payload['fetchedAt'])).total_seconds()
        return age if age>=0 else float('inf')
    except (KeyError,ValueError,TypeError):return float('inf')


def read_json(path):
    try:
        with (gzip.open(path,'rt',encoding='utf-8') if path.suffix=='.gz' else path.open(encoding='utf-8')) as f:return json.load(f)
    except (OSError,ValueError,EOFError):return None


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def request(url):
    global BACKOFF_UNTIL
    with LOCK: delay=BACKOFF_UNTIL-time.monotonic()
    if delay>0: time.sleep(delay)
    try:
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'*/*','Accept-Encoding':'gzip'}),timeout=12) as response:
            data=response.read(8_000_001)
            if len(data)>8_000_000:raise ValueError('Provider response too large')
            if response.headers.get('Content-Encoding')=='gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:data=stream.read(8_000_001)
    except HTTPError as exc:
        if exc.code==429:
            try:retry=max(60,float(exc.headers.get('Retry-After','60')))
            except (ValueError,TypeError):retry=60
            with LOCK:
                BACKOFF_UNTIL=max(BACKOFF_UNTIL,time.monotonic()+retry)
                STATUS['message']='Provider rate limit; backing off before more requests'
        raise
    if len(data)>8_000_000:raise ValueError('Provider response too large')
    return data


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    os.close(fd)
    try:
        opener=gzip.open if path.suffix=='.gz' else open
        with opener(temp,'wt',encoding='utf-8') as f:json.dump(value,f,separators=(',',':'),allow_nan=False)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def parse_universe(content):
    rows=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    records={}
    for raw in rows:
        row={k.strip():v.strip() for k,v in raw.items() if k and v is not None}
        if row.get('SERIES')=='EQ' and re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',row.get('SYMBOL','')):
            records[row['SYMBOL']]={'symbol':row['SYMBOL'],'name':row['NAME OF COMPANY'],'series':'EQ'}
    return list(records.values())


def universe():
    cached=read_json(STATE/'universe.json')
    if cached and cache_age(cached)<UNIVERSE_TTL:return cached
    try:
        records=parse_universe(request(UNIVERSE_URL))
        if len(records)<500: raise ValueError('Unexpectedly small NSE universe')
        result={'source':UNIVERSE_URL,'fetchedAt':now(),'records':records}
        atomic(STATE/'universe.json',result)
        return result
    except Exception as exc:
        for path in (STATE/'universe.json',ROOT/'universe.json'):
            if path.exists():
                result=json.loads(path.read_text());result['warning']='Universe refresh failed: '+str(exc);return result
        raise

def download_history(symbol):
    from server import normalize
    last=None
    for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
        try:
            payload=json.loads(request(f'https://{host}/v8/finance/chart/{quote(symbol+".NS",safe="")}?range=2y&interval=1d&events=div%2Csplits'))
            rows,omitted=normalize(payload,details=True)
            return {'symbol':symbol,'source':'Yahoo Finance daily history','bars':rows,'fetchedAt':now(),'sessionDate':str(dt.datetime.now(IST).date()),'quality':{'omittedIncompleteDates':omitted}}
        except HTTPError as exc:
            # Switching hosts must not bypass rate limits or retry permanent failures.
            if exc.code in (400,401,403,404,429):raise
            last=exc
        except Exception as exc:last=exc
    raise last


def history(symbol):
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',symbol):raise ValueError('Invalid NSE symbol')
    with LOCK: symbol_lock=CACHE_LOCKS.setdefault(symbol,threading.Lock())
    with symbol_lock:
        path=STATE/'history'/(symbol+'.json.gz')
        cached=read_json(path)
        ttl=900 if symbol=='NIFTYBEES' else HISTORY_TTL
        today=str(dt.datetime.now(IST).date())
        if cached and cached.get('symbol')==symbol and cached.get('bars') and cached.get('sessionDate')==today and cache_age(cached)<ttl:
            return cached
        failure=read_json(STATE/'failures'/(symbol+'.json'))
        if failure and cache_age(failure)<failure.get('ttl',120):raise RuntimeError(failure['error'])
        try:
            result=download_history(symbol)
            atomic(path,result)
            # Retain the old priority-cache format for evaluation compatibility.
            if symbol in PRIORITY or symbol=='NIFTYBEES':atomic(STATE/(symbol+'.json'),result)
            return result
        except Exception as exc:
            atomic(STATE/'failures'/(symbol+'.json'),{'fetchedAt':now(),'error':str(exc)[:180],'ttl':3600 if isinstance(exc,HTTPError) and exc.code in (400,404) else 120})
            raise


def completed_jobs(items, fetcher, workers=WORKERS):
    """One replacement submitted immediately per completion; at most workers in flight."""
    iterator=iter(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={}
        for _ in range(workers):
            item=next(iterator,None)
            if item is not None:futures[pool.submit(fetcher,item['symbol'])]=item
        while futures:
            ready,_=wait(futures,return_when=FIRST_COMPLETED)
            for future in ready:
                item=futures.pop(future)
                yield item,future
                following=next(iterator,None)
                if following is not None:futures[pool.submit(fetcher,following['symbol'])]=following


def clamp(x): return max(0,min(100,x))
def avg(a): return statistics.fmean(a)
def scores(bars, benchmark, symbol='', name='', today=None):
    today=today or dt.datetime.now(dt.timezone(dt.timedelta(hours=5,minutes=30))).date()
    bm={r['date']:r for r in benchmark}
    a=[r for r in bars if r['date'] in bm and r['date']<str(today)]
    if len(a)<260: raise ValueError('Needs 260 aligned completed sessions')
    last=a[-1];c=last['close'];cl=[r['close'] for r in a];ma50=avg(cl[-50:]);ma200=avg(cl[-200:])
    ret=lambda n: c/cl[-n-1]-1
    bre=lambda n: bm[last['date']]['close']/bm[a[-n-1]['date']]['close']-1
    r126=ret(126);r21=ret(21);r5=ret(5);relative=r126-bre(126)
    volatility=statistics.pstdev([math.log(cl[i]/cl[i-1]) for i in range(len(cl)-63,len(cl))])*math.sqrt(252)
    drawdown=c/max(cl[-252:])-1
    prev=a[-21:-1];high=max(r['high'] for r in prev);vr=last['volume']/max(1,avg([r['volume'] for r in prev]))
    tr=[max(a[i]['high']-a[i]['low'],abs(a[i]['high']-a[i-1]['close']),abs(a[i]['low']-a[i-1]['close'])) for i in range(len(a)-14,len(a))]
    atr=avg(tr)/c
    longparts={'6-month relative strength':clamp(50+relative*200),'Long trend':clamp(50+(c/ma200-1)*200),'Trend persistence':clamp(50+(ma50/ma200-1)*300),'Drawdown resilience':clamp(100+drawdown*200),'Volatility control':clamp(100-volatility*100)}
    shortparts={'20-session breakout':clamp(50+(c/high-1)*1000),'Volume confirmation':clamp((vr-0.5)*50),'1-month relative strength':clamp(50+(r21-bre(21))*400),'5-session acceleration':clamp(50+(r5-r21/4)*500),'Not overextended':clamp(100-max(0,r5-.04)*600-max(0,atr-.03)*600)}
    lt=round(sum(longparts[k]*w for k,w in zip(longparts,[.3,.25,.2,.15,.1])),1)
    st=round(sum(shortparts[k]*w for k,w in zip(shortparts,[.3,.2,.2,.15,.15])),1)
    combined=round(.6*lt+.4*st,1)
    turnover=statistics.median([r['rawClose']*r['volume'] for r in a[-20:]])
    stale=(today-dt.date.fromisoformat(last['date'])).days>7
    bmclose=[bm[r['date']]['close'] for r in a]; market=bmclose[-1]>avg(bmclose[-200:])
    reasons=[]
    if stale: reasons.append('Price history is more than 7 calendar days old')
    if turnover<10_000_000: reasons.append('Median daily turnover below ₹1 crore')
    if not market: reasons.append('Nifty ETF is below its 200-session trend')
    if c<ma200: reasons.append('Price is below its 200-session trend')
    if r5>.15: reasons.append('Already up more than 15% in five sessions')
    if atr>.06: reasons.append('Daily price range is unusually large')
    entry=not reasons and lt>=65 and st>=65 and vr>=1.2
    breakdown=c<ma200 and r21<-.08
    eligible=not stale and turnover>=10_000_000
    action='ENTRY SETUP' if entry else 'WATCH'
    if not eligible: action='DATA OLD' if stale else 'LOW LIQUIDITY'
    stop=max(2*atr,.05)
    return {'modelVersion':4,'symbol':symbol,'name':name,'date':last['date'],'price':round(last['rawClose'],4),'long':lt,'short':st,'combined':combined,'longParts':{k:round(v,1) for k,v in longparts.items()},'shortParts':{k:round(v,1) for k,v in shortparts.items()},'action':action,'entry':entry,'riskReview':breakdown and not stale,'eligible':eligible,'reasons':reasons,'momentum21':r21,'volumeRatio':round(vr,2),'turnover':round(turnover),'atrPct':atr,'stopFraction':stop,'marketOn':market,'fetchedAt':now(),'coverage':'Price + volume only; fundamentals not scored'}

def load():
    for p in (STATE/'state.json',ROOT/'scan-seed.json'):
        try:
            data=json.loads(p.read_text())
            with LOCK: STATUS.update(data);STATUS['running']=False
            return
        except (OSError,ValueError): pass

def snapshot(since=None):
    with LOCK:
        version=hashlib.sha256(json.dumps([STATUS.get(k) for k in ('updatedAt','done','total','running','message','error')]).encode()).hexdigest()[:20]
        if since==version:return {'unchanged':True,'version':version}
        out={k:v for k,v in STATUS.items() if k not in ('rows','errors')}
        out['version']=version
        out['rows']=[dict(r,entry=False,eligible=False,riskReview=False,refreshError=STATUS['errors'][s]) if s in STATUS['errors'] else dict(r) for s,r in STATUS['rows'].items()];out['errors']=dict(STATUS['errors']);out['serverTime']=now()
        return out

def save():
    with LOCK: payload={**STATUS,'rows':dict(STATUS['rows']),'errors':dict(STATUS['errors'])}
    atomic(STATE/'state.json',payload)

def scan():
    try:
        u=universe();records=u['records'];lookup={r['symbol']:r for r in records}
        import hashlib
        ordered=[lookup.pop(s) for s in PRIORITY if s in lookup]+sorted(lookup.values(),key=lambda r:hashlib.sha256(r['symbol'].encode()).hexdigest())
        benchmark_data=history('NIFTYBEES');atomic(STATE/'NIFTYBEES.json',benchmark_data);benchmark=benchmark_data['bars'];latest=benchmark[-1]['date']
        with LOCK:
            # Drop delisted/out-of-universe rows rather than silently ranking them.
            valid={r['symbol'] for r in records};STATUS['rows']={s:r for s,r in STATUS['rows'].items() if s in valid}
            STATUS.update(total=len(records),done=0,cached=0,processed=0,errors={},universeDate=u['fetchedAt'],universeWarning=u.get('warning'),benchmarkDate=latest,startedAt=now(),message='Scanning all NSE EQ equities')
        pending=[]
        for item in ordered:
            old=STATUS['rows'].get(item['symbol'])
            if old and old.get('benchmarkDate',old['date'])==latest and old['date']==latest and old.get('modelVersion')==4 and learner().registered(item['symbol']):
                with LOCK: STATUS['done']+=1;STATUS['cached']+=1
            else: pending.append(item)
        failures=0
        last_checkpoint=time.monotonic()
        jobs=completed_jobs(pending,history)
        try:
            for item,future in jobs:
                symbol=item['symbol'];obtained=False
                try:
                    data=future.result();obtained=True
                    row=scores(data['bars'],benchmark,symbol,item['name'])
                    row['omittedDates']=data['quality']['omittedIncompleteDates']
                    row['benchmarkDate']=latest
                    try:row['forecast']=learner().observe(symbol,data['bars'],benchmark)
                    except Exception as exc:row['forecastError']=str(exc)[:180]
                    with LOCK:STATUS['rows'][symbol]=row
                    failures=0
                except Exception as exc:
                    with LOCK:STATUS['errors'][symbol]=str(exc)[:180]
                    failures=0 if obtained else failures+1
                with LOCK:
                    STATUS['done']+=1;STATUS['processed']+=1;STATUS['updatedAt']=now()
                if time.monotonic()-last_checkpoint>=3:
                    save();last_checkpoint=time.monotonic()
                if failures>=24:raise RuntimeError('Provider repeatedly failing. Progress saved; retry later.')
        finally:jobs.close()
        with LOCK: STATUS['message']='Scan finished. Failed or insufficient-history symbols are listed separately.';STATUS['finishedAt']=now()
    except Exception as exc:
        with LOCK: STATUS['message']=str(exc);STATUS['error']=str(exc)
    finally:
        with LOCK: STATUS['running']=False;STATUS['updatedAt']=now()
        save()

def start():
    with LOCK:
        if STATUS['running']: return False
        STATUS['running']=True;STATUS['error']=None;STATUS['message']='Loading NSE universe and benchmark'
    threading.Thread(target=scan,daemon=True).start();return True

def news(symbol):
    import re,email.utils
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9&.\-]{0,29}',symbol): raise ValueError('Invalid NSE symbol')
    if symbol in NEWS and time.time()-NEWS[symbol][0]<1800:return NEWS[symbol][1]
    with LOCK: name=STATUS['rows'].get(symbol,{}).get('name',symbol)
    query=quote('"'+name+'" stock when:7d')
    root=ET.fromstring(request('https://news.google.com/rss/search?q='+query+'&hl=en-IN&gl=IN&ceid=IN:en'))
    items=[];seen=set()
    for item in root.findall('./channel/item'):
        title=item.findtext('title','');link=item.findtext('link','');date=item.findtext('pubDate','')
        if title in seen or not link.startswith('https://'):continue
        try:
            published=email.utils.parsedate_to_datetime(date)
            if not 0 <= (dt.datetime.now(dt.timezone.utc)-published).total_seconds() <= 8*86400:continue
        except Exception:continue
        seen.add(title);items.append({'title':title,'url':link,'published':published.isoformat(),'source':item.findtext('source','')})
        if len(items)==6:break
    result={'symbol':symbol,'items':items,'fetchedAt':now(),'note':'Headlines are context, not a verified price catalyst. News does not change the score.'}
    NEWS[symbol]=(time.time(),result);return result

load()
if __name__=='__main__':
    start()
    while STATUS['running']:
        print(json.dumps({k:v for k,v in snapshot().items() if k not in ('rows','errors')}),flush=True);time.sleep(15)
    print('Completed:',len(STATUS['rows']),'scored;',len(STATUS['errors']),'unavailable',flush=True)
