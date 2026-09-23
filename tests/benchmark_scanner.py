"""Controlled latency benchmark; not a claim about provider/network speed."""
import sys,time,json,statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scanner

items=[{'symbol':str(i)} for i in range(48)]
def fetch(symbol):
    time.sleep(.12 if int(symbol)%12==0 else .006)
    return symbol

def old():
    with ThreadPoolExecutor(max_workers=6) as pool:
        for offset in range(0,len(items),12):
            for job in as_completed([pool.submit(fetch,item['symbol']) for item in items[offset:offset+12]]):job.result()
def new():
    for item,job in scanner.completed_jobs(items,fetch,6):job.result()
def measure(fn):
    start=time.perf_counter();fn();return time.perf_counter()-start
if __name__=='__main__':
    before=statistics.median(measure(old) for _ in range(3));after=statistics.median(measure(new) for _ in range(3))
    print(json.dumps({'jobs':48,'workers':6,'runs':3,'oldSeconds':round(before,3),'newSeconds':round(after,3),'speedup':round(before/after,2),'kind':'simulated mixed-latency scheduling only'},indent=2))
