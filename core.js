/* Pure research and accounting functions; shared by the browser and Node tests. */
(function (root) {
  'use strict';
  const DAY = 86400000;
  const RULES = ['Above 200-day average', '50-day above 200-day', 'Positive 63-day momentum', 'Outperforming Nifty ETF', 'Nifty ETF in an uptrend'];
  function assert(ok, message) { if (!ok) throw new Error(message); }
  function number(x, name = 'Value') { assert(x !== '' && x !== null && x !== undefined && typeof x !== 'boolean' && Number.isFinite(Number(x)), name + ' must be a finite number.'); return Number(x); }
  function date(x) { assert(typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x) && Number.isFinite(Date.parse(x)) && new Date(x).toISOString().slice(0,10) === x, 'Invalid date; use YYYY-MM-DD.'); return x; }
  function today() { return new Date(Date.now() + 5.5 * 3600000).toISOString().slice(0,10); }
  function symbol(x) { x = String(x).trim().toUpperCase().replace(/\.NS$/, ''); assert(/^[A-Z0-9][A-Z0-9&.\-]{0,29}$/.test(x), 'Enter an NSE symbol, such as INFY or M&M.'); return x; }
  function cost(x) { x = number(x); assert(x >= 0 && x <= 1000, 'Costs must be 0–1,000 basis points per side.'); return x / 10000; }
  const mean = a => a.reduce((x,y)=>x+y,0)/a.length;
  function validateBars(rows) {
    assert(Array.isArray(rows) && rows.length >= 2 && rows.length <= 20000, 'Provide 2–20,000 daily price rows.');
    const seen = new Set();
    const bars = rows.map(r => {
      const d = date(r.date); assert(!seen.has(d), 'Duplicate price date: ' + d); seen.add(d);
      const b = {date:d};
      for (const k of ['open','high','low','close','rawClose','volume']) b[k] = number(r[k], k);
      assert(['open','high','low','close','rawClose'].every(k=>b[k]>0) && b.volume>=0, 'Prices must be positive and volume nonnegative.');
      assert(b.high+1e-7 >= Math.max(b.open,b.close,b.low) && b.low-1e-7 <= Math.min(b.open,b.close,b.high), 'Invalid OHLC values on '+d);
      return b;
    }).sort((a,b)=>a.date.localeCompare(b.date));
    const closed=new Date(Date.now()+5.5*3600000).getUTCHours()>=16;
    assert(bars.every(b=>b.date<today()||(closed&&b.date===today())), 'Only completed market dates are accepted.');
    return bars;
  }
  function csvRows(text) {
    text = String(text).replace(/^\uFEFF/,''); const rows=[]; let row=[], cell='', quoted=false;
    for(let i=0;i<text.length;i++) { const c=text[i];
      if(c==='"') { if(quoted && text[i+1]==='"'){cell+='"';i++;} else quoted=!quoted; }
      else if(c===',' && !quoted){row.push(cell.trim());cell='';}
      else if((c==='\n'||c==='\r') && !quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell.trim());if(row.some(Boolean))rows.push(row);row=[];cell='';}
      else cell+=c;
    }
    assert(!quoted, 'Unclosed CSV quote.'); row.push(cell.trim());if(row.some(Boolean))rows.push(row);
    assert(rows.length>1,'CSV is empty.'); const header=rows.shift();
    assert(new Set(header).size===header.length,'Duplicate CSV columns.');
    return rows.map(r=>{assert(r.length===header.length,'CSV row has the wrong number of columns.');return Object.fromEntries(header.map((h,i)=>[h,r[i]]));});
  }
  function pricesCSV(text) {
    return validateBars(csvRows(text).map(r=>{
      const c=number(r.Close,'Close'), a=number(r['Adj Close'],'Adj Close');assert(c>0&&a>0,'Close and Adj Close must be positive.');const f=a/c;
      return {date:r.Date,open:number(r.Open)*f,high:number(r.High)*f,low:number(r.Low)*f,close:a,rawClose:c,volume:number(r.Volume)};
    }));
  }
  function features(stock, benchmark) {
    const lookup=new Map(benchmark.map(b=>[b.date,b]));
    const data=stock.filter(b=>lookup.has(b.date)).map(b=>({...b,bench:lookup.get(b.date).close,benchOpen:lookup.get(b.date).open}));
    assert(data.length>=260,'At least 260 matching stock and benchmark sessions are needed.');
    let sum50=0,sum200=0,sumBench=0;const trs=[];
    for(let i=0;i<data.length;i++) {const b=data[i];sum50+=b.close;sum200+=b.close;sumBench+=b.bench;
      if(i>=50)sum50-=data[i-50].close;if(i>=200){sum200-=data[i-200].close;sumBench-=data[i-200].bench;}
      b.ma50=i>=49?sum50/50:null;b.ma200=i>=199?sum200/200:null;
      b.momentum=i>=63?b.close/data[i-63].close-1:null;b.relative=i>=63?b.momentum-(b.bench/data[i-63].bench-1):null;
      const prev=i?data[i-1].close:b.close;trs.push(Math.max(b.high-b.low,Math.abs(b.high-prev),Math.abs(b.low-prev)));
      b.atr=i>=13?mean(trs.slice(i-13,i+1)):null;
      b.ready=i>=199;b.rules=[b.ready&&b.close>b.ma200,b.ready&&b.ma50>b.ma200,b.ready&&b.momentum>0,b.ready&&b.relative>0,b.ready&&b.bench>sumBench/200];
      b.score=b.rules.filter(Boolean).length*20;b.signal=b.ready&&b.rules.every(Boolean);
    }
    return data;
  }
  function stale(bars) { return (Date.parse(today())-Date.parse(bars.at(-1).date))/DAY>7; }
  function evidence(data, horizon=21, bps=20) {
    assert(Number.isInteger(horizon)&&horizon>0,'Invalid horizon.');const c=cost(bps),samples=[];
    for(let i=199;i+1+horizon<data.length;) {
      if(!data[i].signal){i++;continue;} const e=i+1,x=e+horizon;
      const r=data[x].open/data[e].open*(1-c)/(1+c)-1, br=data[x].benchOpen/data[e].benchOpen*(1-c)/(1+c)-1;
      samples.push({decision:data[i].date,entry:data[e].date,exit:data[x].date,return:r,benchmark:br,excess:r-br});i=x;
    }
    const n=samples.length,wins=samples.filter(s=>s.return>0).length;if(!n)return {n:0,rate:null,interval:null,samples};
    const p=wins/n,z=1.96,d=1+z*z/n,mid=(p+z*z/(2*n))/d,half=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;
    return {n,rate:p,interval:[Math.max(0,mid-half),Math.min(1,mid+half)],samples};
  }
  function backtest(data, start, bps=20) {
    date(start);const c=cost(bps),first=Math.max(200,data.findIndex(b=>b.date>=start));assert(start<=data.at(-1).date&&data.length-first>=30,'Choose a start with at least 30 sessions remaining.');
    let cash=1,units=0,orders=0,days=0;const benchUnits=1/(data[first].benchOpen*(1+c));const points=[{date:data[first].date,strategy:1,benchmark:1}];
    for(let i=first;i<data.length;i++){const b=data[i],want=data[i-1].signal;
      if(want&&!units){units=cash/(b.open*(1+c));cash=0;orders++;}
      else if(!want&&units){cash=units*b.open*(1-c);units=0;orders++;}
      if(units)days++;
      let v=cash+units*b.close,bv=benchUnits*b.bench;
      if(i===data.length-1){if(units){v-=units*b.close*c;orders++;}bv*=1-c;}
      points.push({date:b.date,strategy:v,benchmark:bv});
    }
    const years=Math.max((Date.parse(data.at(-1).date)-Date.parse(data[first].date))/DAY/365.25,1/365.25);
    function stats(key){let peak=1,dd=0;for(const p of points){peak=Math.max(peak,p[key]);dd=Math.min(dd,p[key]/peak-1);}const end=points.at(-1)[key];return {total:end-1,cagr:end**(1/years)-1,drawdown:dd};}
    return {points,strategy:stats('strategy'),benchmark:stats('benchmark'),orders,exposure:days/(data.length-first)};
  }
  function size({equity,cash,price,stop,existing=0,risk=.005,cap=.1,bps=20}) {
    [equity,cash,price,stop,existing,risk,cap].forEach(x=>number(x));assert(equity>0&&cash>=0&&existing>=0,'Fund your portfolio before sizing.');
    assert(stop>0&&stop<price,'Exit level must be positive and below the share price.');assert(risk>0&&risk<=1&&cap>0&&cap<=1,'Invalid risk or position cap.');
    const c=cost(bps),unitCost=price*(1+c),unitLoss=price-stop+(price+stop)*c;
    const limits={Cash:Math.floor(cash/unitCost),'Position cap':Math.floor(Math.max(0,equity*cap-existing)/price),'Loss budget':Math.floor(equity*risk/unitLoss)};
    const quantity=Math.max(0,Math.min(...Object.values(limits)));
    return {quantity,cost:quantity*unitCost,loss:quantity*unitLoss,limits,binding:Object.keys(limits).find(k=>limits[k]===quantity)};
  }
  const cents=x=>{const n=Math.round(number(x)*100);assert(Number.isSafeInteger(n)&&Math.abs(n)<=1e13,'Amount is too large.');return n;};
  function ledger(rows) {
    assert(Array.isArray(rows)&&rows.length<=20000,'Invalid ledger.');let cash=0,net=0,realized=0,dividends=0;const lots={},ids=new Set();
    const sorted=rows.map((r,i)=>({...r,_i:i})).sort((a,b)=>String(a.date).localeCompare(String(b.date))||a._i-b._i);
    for(const r of sorted){date(r.date);assert(r.date<=today(),'Transactions cannot be in the future.');assert(r.id&&typeof r.id==='string'&&!ids.has(r.id),'Transaction IDs must be unique.');ids.add(r.id);
      const q=number(r.quantity),p=number(r.price),feeValue=number(r.fees),fee=cents(feeValue);assert(q>=0&&p>=0&&feeValue>=0,'Amounts cannot be negative.');assert(q<=1e9&&p<=1e9,'Transaction is too large.');
      if(['DEPOSIT','WITHDRAW','DIVIDEND'].includes(r.kind)){assert(q===0&&fee===0&&p>0,'Cash events require only a positive amount.');const amount=cents(p);assert(amount>0,'Amount must be at least ₹0.01.');
        if(r.kind==='DEPOSIT'){cash+=amount;net+=amount;}else if(r.kind==='WITHDRAW'){cash-=amount;net-=amount;}else{cash+=amount;dividends+=amount;}
      } else {assert(['BUY','SELL','SPLIT'].includes(r.kind),'Unknown transaction type.');const s=symbol(r.symbol);const bucket=lots[s]||(lots[s]=[]);
        assert(q>0,'Quantity must be positive.');
        if(r.kind==='SPLIT'){assert(p===0&&fee===0&&bucket.length,'A split requires an existing holding and a ratio only.');for(const l of bucket){l.quantity*=q;assert(Number.isFinite(l.quantity)&&l.quantity<=1e9,'Invalid resulting split quantity.');}}
        else {assert(p>0,'Trade price must be positive.');const gross=cents(q*p);assert(gross>0,'Trade value must be at least ₹0.01.');
          if(r.kind==='BUY'){cash-=gross+fee;bucket.push({date:r.date,quantity:q,basis:gross+fee});}
          else {assert(q<=bucket.reduce((a,l)=>a+l.quantity,0)+1e-9,'Cannot sell more shares than you hold.');let left=q,basis=0;
            while(left>1e-9){const l=bucket[0],used=Math.min(left,l.quantity);const allocated=used>=l.quantity-1e-9?l.basis:Math.round(l.basis*used/l.quantity);basis+=allocated;l.basis-=allocated;l.quantity-=used;left-=used;if(l.quantity<1e-9)bucket.shift();}
            cash+=gross-fee;realized+=gross-fee-basis;
          }
        }
      }
      assert(cash>=0,'Insufficient cash on '+r.date+'. Add the funding deposit before this transaction.');assert(Number.isSafeInteger(cash)&&Math.abs(cash)<=1e13,'Portfolio exceeds supported size.');
    }
    const holdings=Object.fromEntries(Object.entries(lots).filter(([,ls])=>ls.length).map(([s,ls])=>{const quantity=ls.reduce((a,l)=>a+l.quantity,0),basis=ls.reduce((a,l)=>a+l.basis,0)/100;return [s,{quantity,basis,average:basis/quantity,first:ls[0].date,lots:ls}];}));
    return {cash:cash/100,net:net/100,realized:realized/100,dividends:dividends/100,holdings};
  }
  function valuation(book,marks) {let value=0,basis=0;for(const [s,h] of Object.entries(book.holdings)){assert(marks[s]!==undefined,'Missing price for '+s);const p=number(marks[s]);assert(p>0,'Invalid mark.');value+=h.quantity*p;basis+=h.basis;}return {equity:book.cash+value,invested:value,unrealized:value-basis,profit:book.cash+value-book.net};}
  function demo(s) {
    s=symbol(s);let seed=[...s].reduce((a,c)=>a*31+c.charCodeAt(0),7)>>>0;const random=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296;};
    const bases={INFY:1300,RELIANCE:1150,TCS:2800,HDFCBANK:750,ICICIBANK:900,LT:2300,ITC:360,SUNPHARMA:1250,NIFTYBEES:220};
    let price=bases[s]||800;const bars=[];const end=new Date('2026-09-18T00:00:00Z'),dates=[];for(let d=new Date(end);dates.length<850;d.setUTCDate(d.getUTCDate()-1)){if(d.getUTCDay()!==0&&d.getUTCDay()!==6)dates.unshift(d.toISOString().slice(0,10));}
    const bias=s==='INFY'?.0013:s==='TCS'?-.0004:.0003;
    for(let i=0;i<dates.length;i++){const open=price*(1+(random()-.5)*.005);const regime=Math.sin(i/85)*.0012;price=open*Math.exp(bias+regime+(random()-.49)*(s==='NIFTYBEES'?.012:.031));const high=Math.max(open,price)*(1+random()*.01),low=Math.min(open,price)*(1-random()*.01);bars.push({date:dates[i],open,high,low,close:price,rawClose:price,volume:Math.round(1e6+random()*4e6)});}
    return bars;
  }
  const api={RULES,assert,number,date,today,symbol,validateBars,csvRows,pricesCSV,features,stale,evidence,backtest,size,ledger,valuation,demo};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.Lab=api;
})(typeof globalThis!=='undefined'?globalThis:this);
