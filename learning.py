"""Auditable online forecasts. No orders; immutable predictions, delayed learning.

The shared ridge model estimates net log return over 5/21 sessions. Historical
warm-up is kept separate from genuinely recorded forward accuracy.
"""
from contextlib import contextmanager
import datetime as dt
import json
import math
import sqlite3
import statistics
import threading
from pathlib import Path

IST=dt.timezone(dt.timedelta(hours=5,minutes=30))
HORIZONS=(5,21)
DIM=9
COST_LOG=math.log(.998/1.002)
MODEL='online-ridge-v2-decay'


def features(bars, benchmark):
    """Only observations passed by the caller are visible here."""
    bm={r['date']:r for r in benchmark}
    a=[r for r in bars if r['date'] in bm]
    if len(a)<260:raise ValueError('Forecast needs 260 aligned sessions')
    c=[r['close'] for r in a];last=c[-1]
    ret=lambda n:math.log(last/c[-n-1])
    relative=ret(21)-math.log(bm[a[-1]['date']]['close']/bm[a[-22]['date']]['close'])
    vol=statistics.pstdev(math.log(c[i]/c[i-1]) for i in range(len(c)-21,len(c)))
    volume=a[-1]['volume']/max(1,statistics.fmean(r['volume'] for r in a[-21:-1]))
    clip=lambda x:max(-3,min(3,x))
    return [1,clip(ret(5)*10),clip(ret(21)*5),clip(ret(63)*3),clip(relative*5),clip((last/statistics.fmean(c[-200:])-1)*3),clip(vol*20),clip(math.log(max(.01,volume))),clip((last/max(c[-252:])-1)*3)]


def new_model():
    return {'xtx':[[0.0]*DIM for _ in range(DIM)],'xty':[0.0]*DIM,'n':0,'historical':0,'forward':0}


def fit_one(model,x,y,origin):
    # Bound influence of extreme outliers without altering the recorded outcome.
    if origin=='forward':
        model['xtx']=[[v*.995 for v in row] for row in model['xtx']]
        model['xty']=[v*.995 for v in model['xty']]
    y=max(-.7,min(.7,y))
    for i in range(DIM):
        model['xty'][i]+=x[i]*y
        for j in range(DIM):model['xtx'][i][j]+=x[i]*x[j]
    model['n']+=1;model[origin]+=1


def weights(model):
    a=[row[:]+[model['xty'][i]] for i,row in enumerate(model['xtx'])]
    for i in range(DIM):a[i][i]+=1 if i==0 else 10
    for i in range(DIM):
        pivot=max(range(i,DIM),key=lambda j:abs(a[j][i]));a[i],a[pivot]=a[pivot],a[i]
        divisor=a[i][i]
        a[i]=[v/divisor for v in a[i]]
        for j in range(DIM):
            if j!=i:
                scale=a[j][i];a[j]=[u-scale*v for u,v in zip(a[j],a[i])]
    return [row[-1] for row in a]


class Learner:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS models(horizon INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bootstraps(symbol TEXT, horizon INTEGER, PRIMARY KEY(symbol,horizon));
            CREATE TABLE IF NOT EXISTS forecasts(
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, horizon INTEGER NOT NULL,
                issued_at TEXT NOT NULL, issued_date TEXT NOT NULL, asof_date TEXT NOT NULL,
                features TEXT NOT NULL, predicted REAL NOT NULL, baseline REAL NOT NULL,
                band REAL, training_n INTEGER NOT NULL, model_version TEXT NOT NULL,
                entry_date TEXT, exit_date TEXT, actual REAL, resolved_at TEXT,
                UNIQUE(symbol,horizon,issued_date));
            CREATE INDEX IF NOT EXISTS forecast_pending ON forecasts(symbol,actual);
            CREATE INDEX IF NOT EXISTS forecast_resolved ON forecasts(horizon,resolved_at);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db:yield db
        finally:db.close()

    def registered(self,symbol):
        with self.lock,self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM bootstraps WHERE symbol=?',(symbol,)).fetchone()[0]==len(HORIZONS)

    def observe(self,symbol,bars,benchmark,when=None):
        when=when or dt.datetime.now(dt.timezone.utc)
        today=str(when.astimezone(IST).date())
        # Never train or settle against today's unfinished candle or supplied future bars.
        closed=when.astimezone(IST).hour>=16
        a=[r for r in bars if r['date']<today or (closed and r['date']==today)]
        b=[r for r in benchmark if r['date']<today or (closed and r['date']==today)]
        if not a or not b or a[-1]['date']!=b[-1]['date']:
            return {'status':'waiting','reason':'Stock and benchmark must have the same completed session','predictions':[]}
        asof=a[-1]['date']
        if (dt.date.fromisoformat(today)-dt.date.fromisoformat(asof)).days>7:
            return {'status':'waiting','reason':'Prices are too old for a new forecast','predictions':[]}
        x=features(a,b);by_date={r['date']:r for r in a};stamp=when.isoformat()
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for horizon in HORIZONS:
                found=db.execute('SELECT payload FROM models WHERE horizon=?',(horizon,)).fetchone()
                model=json.loads(found[0]) if found else new_model()
                pending=db.execute('SELECT * FROM forecasts WHERE symbol=? AND horizon=? AND actual IS NULL',(symbol,horizon)).fetchall()
                for old in pending:
                    # Start strictly AFTER actual issuance day, not after an old price date.
                    sessions=[r['date'] for r in b if r['date']>old['issued_date']]
                    if len(sessions)<=horizon:continue
                    entry,exit=sessions[0],sessions[horizon]
                    # Do not slide the horizon to disguise an incomplete source candle.
                    if entry not in by_date or exit not in by_date:continue
                    target=math.log(by_date[exit]['open']/by_date[entry]['open'])+COST_LOG
                    actual=math.expm1(target)
                    db.execute('UPDATE forecasts SET entry_date=?,exit_date=?,actual=?,resolved_at=? WHERE id=? AND actual IS NULL',(entry,exit,actual,stamp,old['id']))
                    fit_one(model,json.loads(old['features']),target,'forward')
                if not db.execute('SELECT 1 FROM bootstraps WHERE symbol=? AND horizon=?',(symbol,horizon)).fetchone():
                    # Historical warm-up, never presented as forward-tested accuracy.
                    for i in range(259,len(b)-horizon-1,horizon+1):
                        decision,entry,exit=b[i]['date'],b[i+1]['date'],b[i+horizon+1]['date']
                        if any(day not in by_date for day in (decision,entry,exit)):continue
                        prefix=[r for r in a if r['date']<=decision]
                        try:past_features=features(prefix,b[:i+1])
                        except ValueError:continue
                        target=math.log(by_date[exit]['open']/by_date[entry]['open'])+COST_LOG
                        fit_one(model,past_features,target,'historical')
                    db.execute('INSERT INTO bootstraps VALUES(?,?)',(symbol,horizon))
                db.execute('INSERT OR REPLACE INTO models VALUES(?,?)',(horizon,json.dumps(model)))
                # One outstanding forecast per stock/horizon; scans do not manufacture samples.
                if not db.execute('SELECT 1 FROM forecasts WHERE symbol=? AND horizon=? AND actual IS NULL',(symbol,horizon)).fetchone():
                    prediction=sum(v*w for v,w in zip(x,weights(model))) if model['n']>=30 else COST_LOG
                    prediction=math.expm1(max(-.4,min(.4,prediction)))
                    errors=sorted(abs(r['actual']-r['predicted']) for r in db.execute('SELECT actual,predicted FROM forecasts WHERE horizon=? AND actual IS NOT NULL ORDER BY id DESC LIMIT 200',(horizon,)))
                    band=errors[min(len(errors)-1,math.ceil(.9*len(errors))-1)] if len(errors)>=30 else None
                    db.execute('INSERT OR IGNORE INTO forecasts(symbol,horizon,issued_at,issued_date,asof_date,features,predicted,baseline,band,training_n,model_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(symbol,horizon,stamp,today,asof,json.dumps(x),prediction,math.expm1(COST_LOG),band,model['n'],MODEL+':'+str(model['n'])))
            rows=db.execute('SELECT * FROM forecasts WHERE symbol=? AND actual IS NULL ORDER BY horizon',(symbol,)).fetchall()
            return {'status':'paper','predictions':[self.public(r) for r in rows]}

    @staticmethod
    def public(row):
        return {k:row[k] for k in ('id','symbol','horizon','issued_at','asof_date','predicted','baseline','band','training_n','model_version','entry_date','exit_date','actual','resolved_at')}

    def summary(self,symbol=None):
        with self.lock,self.connect() as db:
            metrics=[]
            for horizon in HORIZONS:
                # Latest 200 forward outcomes measure current behaviour, not warm-up fit.
                rows=db.execute('SELECT * FROM forecasts WHERE horizon=? AND actual IS NOT NULL ORDER BY id DESC LIMIT 200',(horizon,)).fetchall()
                n=len(rows);mae=statistics.fmean(abs(r['actual']-r['predicted']) for r in rows) if n else None
                baseline=statistics.fmean(abs(r['actual']-r['baseline']) for r in rows) if n else None
                model=db.execute('SELECT payload FROM models WHERE horizon=?',(horizon,)).fetchone()
                m=json.loads(model[0]) if model else new_model()
                metrics.append({'horizon':horizon,'evaluated':n,'forwardTotal':m['forward'],'historicalTraining':m['historical'],'mae':mae,'baselineMae':baseline,'directionAccuracy':statistics.fmean((r['actual']>0)==(r['predicted']>0) for r in rows) if n else None,'status':'Too early to judge' if n<30 else 'Below baseline' if mae>=baseline else 'Lower error than baseline; not proof of future returns'})
            where=' WHERE symbol=?' if symbol else ''
            args=(symbol,) if symbol else ()
            recent=db.execute('SELECT * FROM forecasts'+where+' ORDER BY id DESC LIMIT 50',args).fetchall()
            return {'model':MODEL,'metrics':metrics,'pending':db.execute('SELECT COUNT(*) FROM forecasts WHERE actual IS NULL').fetchone()[0],'forecasts':[self.public(r) for r in recent]}
