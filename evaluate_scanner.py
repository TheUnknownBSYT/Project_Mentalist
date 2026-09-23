"""Reproducible forward-outcome audit of the scanner. Not a trained model backtest.
Uses local price caches only; `python3 evaluate_scanner.py` writes evaluation.json.
"""
import datetime as dt,json,statistics
from pathlib import Path
from scanner import scores,STATE,ROOT

def evaluate(histories):
    benchmark=histories['NIFTYBEES']['bars'];bm={r['date']:r for r in benchmark};result={}
    for horizon,field,threshold in [(21,'short',.05),(126,'long',.10)]:
        observations=[]
        for symbol,payload in histories.items():
            if symbol=='NIFTYBEES':continue
            a=[r for r in payload['bars'] if r['date'] in bm]
            # Labels never overlap within one stock/horizon. Across-stock dependence remains.
            for i in range(259,len(a)-horizon-1,horizon+1):
                decision=a[i]['date'];today=dt.date.fromisoformat(decision)+dt.timedelta(days=1)
                r=scores(a[:i+1],benchmark,symbol,symbol,today)
                entry=a[i+1];exit=a[i+horizon+1];cost=.002
                ret=exit['open']*(1-cost)/(entry['open']*(1+cost))-1
                benchmark_return=bm[exit['date']]['open']*(1-cost)/(bm[entry['date']]['open']*(1+cost))-1
                observations.append({'symbol':symbol,'decision':decision,'entry':entry['date'],'exit':exit['date'],'score':r[field],'return':ret,'benchmarkReturn':benchmark_return,'targetHit':ret>=threshold})
        def summary(rows):
            return {'count':len(rows),'targetFrequency':sum(r['targetHit'] for r in rows)/len(rows) if rows else None,'meanReturn':statistics.fmean(r['return'] for r in rows) if rows else None,'meanExcessReturn':statistics.fmean(r['return']-r['benchmarkReturn'] for r in rows) if rows else None}
        result[field]={'horizonSessions':horizon,'targetReturn':threshold,'all':summary(observations),'scoreAtLeast65':summary([r for r in observations if r['score']>=65]),'observations':observations}
    return {'modelVersion':4,'builtAt':dt.datetime.now(dt.timezone.utc).isoformat(),'caveat':'Historical diagnostic on selected available symbols. Not independent validation, a calibrated probability, or proof of future returns. No point-in-time fundamentals or historical index membership. Symbols share market exposure.', 'perSideCost':.002,'results':result}

if __name__=='__main__':
    histories={p.stem:json.loads(p.read_text()) for p in STATE.glob('*.json') if p.stem not in ('state','universe')}
    if 'NIFTYBEES' not in histories:
        text=(ROOT/'market-data.js').read_text();histories=json.loads(text.split('=',1)[1].rstrip(';'))
    out=evaluate(histories);(ROOT/'evaluation.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:{j:v for j,v in r.items() if j!='observations'} for k,r in out['results'].items()},indent=2))
