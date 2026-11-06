// Run: node tests/figures.js  (BB_CSV=path/to/statement.csv to check against a real statement)
// Independent check of "Should be in the account now", including amount changes.
// Own date maths and own day-by-day walk; only the bill list and settings come from the app.
const fs=require('fs'),path=require('path');const js=fs.readFileSync(path.join(__dirname,'..','build','app.js'),'utf8');const logic=js.split('/*LOGIC_START*/')[1].split('/*LOGIC_END*/')[0];
const app={};eval(logic+';Object.assign(app,{extract,redetect,defaults,computePlan,toISO,today,setS:x=>{S=x},getS:()=>S});');
const DAY=86400000,iso=d=>d.toISOString().slice(0,10),addDays=(d,n)=>new Date(d.getTime()+n*DAY),dt=s=>new Date(s+'T00:00:00Z');
function monthly(anchor,dom,step,from,to){const out=[];for(let k=-40;k<=40;k++){const y=anchor.getUTCFullYear(),m=anchor.getUTCMonth()+k*step;const last=new Date(Date.UTC(y,m+1,0)).getUTCDate();const d=new Date(Date.UTC(y,m,Math.min(dom,last)));if(d>=from&&d<to)out.push(iso(d));}return out;}
function every(anchor,step,from,to){const out=[];let d=anchor;while(d>from)d=addDays(d,-step);while(d<to){if(d>=from)out.push(iso(d));d=addDays(d,step);}return out;}
function billDates(b,from,to){const a=dt(b.anchor);if(b.cadence==='weekly')return every(a,7,from,to);if(b.cadence==='fortnightly')return every(a,14,from,to);return monthly(a,b.dom||a.getUTCDate(),b.cadence==='quarterly'?3:b.cadence==='yearly'?12:1,from,to);}
function payDays(p,from,to){const a=dt(p.nextPayday);if(p.freq==='monthly')return monthly(a,a.getUTCDate(),1,from,to);return every(a,{weekly:7,fortnightly:14,'4weekly':28}[p.freq],from,to);}
function amountOn(b,dIso){ // latest-starting change covering the day wins
  let a=b.amount,start='';for(const c of (b.changes||[])){if(c.from<=dIso&&(!c.until||dIso<=c.until)&&c.from>=start){start=c.from;a=c.amount;}}return a;}
const perYear={weekly:365.25/7,fortnightly:365.25/14,monthly:12,quarterly:4,yearly:1},payPer={weekly:365.25/7,fortnightly:365.25/14,'4weekly':365.25/28,monthly:12};
function independent(S,todayISO){
  const T=dt(todayISO),buf=+S.settings.buffer||0,horizon=addDays(T,400);
  const bills=S.bills.filter(b=>b.include&&(b.amount>0||(b.changes||[]).length));
  const people=S.people.map(p=>{const own=bills.filter(b=>b.owner===p.id),custom=(p.payIn!==''&&p.payIn!=null);
    const nextBill=(b,d)=>billDates(b,dt(d),addDays(dt(d),800))[0];
    const payOn=d=>custom?+p.payIn:Math.max(0,Math.ceil(own.reduce((n,b)=>{const nb=nextBill(b,d);return n+amountOn(b,nb||d)*perYear[b.cadence];},0)/payPer[p.freq]-1e-9));
    return {payOn,dates:payDays(p,T,horizon)};});
  let until=addDays(T,14);people.forEach(r=>{if(!r.dates.length)return;const e=dt(r.dates[r.dates[0]===todayISO?2:1]);if(e>until)until=e;});
  const out={},inn={};bills.forEach(b=>billDates(b,T,until).forEach(d=>(out[d]=out[d]||[]).push(amountOn(b,d))));
  people.forEach(r=>r.dates.forEach(d=>{if(d!==todayISO)inn[d]=(inn[d]||0)+r.payOn(d);}));
  let net=0,worst=0;for(let d=T;d<until;d=addDays(d,1)){const k=iso(d);net+=inn[k]||0;for(const a of (out[k]||[])){net-=a;worst=Math.min(worst,net);}}
  return {required:buf-worst,until:iso(until)};
}
const tx=app.extract(process.env.BB_CSV?fs.readFileSync(process.env.BB_CSV,'utf8'):require('./sample.js')()).txns;
const S0=app.defaults();S0.txns=tx;app.setS(S0);app.redetect();const base=app.getS().bills;if(base.length<5){console.log('FAILED: only '+base.length+' bills found in the statement');process.exit(1);}
let seed=11;const rnd=()=>{seed=(seed*16807)%2147483647;return seed/2147483647;};
const freqs=['weekly','fortnightly','fortnightly','4weekly','monthly'],T=app.toISO(app.today()),tnum=app.today();
let worst=0,fails=[];
for(let i=0;i<500;i++){
  const S=app.defaults();S.txns=tx;S.bills=JSON.parse(JSON.stringify(base));const np=1+Math.floor(rnd()*3);
  S.people=Array.from({length:np},(_,j)=>({id:'p'+j,name:'P'+j,nextPayday:app.toISO(tnum+Math.floor(rnd()*15)),freq:freqs[Math.floor(rnd()*5)],payIn:rnd()<.15?String(Math.floor(500+rnd()*2500)):''}));
  S.bills.forEach(b=>{b.owner='p'+Math.floor(rnd()*np);if(rnd()<.1)b.include=false;b.changes=[];
    const k=rnd()<.35?1+Math.floor(rnd()*2):0;for(let c=0;c<k;c++){const f=tnum-10+Math.floor(rnd()*70);const temp=rnd()<.5;
      b.changes.push({id:'x'+c,amount:Math.round(b.amount*(0.5+rnd()*1.5)*100)/100,from:app.toISO(f),until:temp?app.toISO(f+5+Math.floor(rnd()*60)):null});}});
  S.settings.buffer=Math.floor(rnd()*500);
  app.setS(S);const P=app.computePlan(),I=independent(S,T),d=Math.abs(P.required-I.required);
  worst=Math.max(worst,d);if(d>0.01||app.toISO(P.until)!==I.until)fails.push({i,app:P.required.toFixed(2),ind:I.required.toFixed(2)});
}
console.log('scenarios with amount changes: 500 | largest difference: $'+worst.toFixed(2)+' | mismatches:',fails.length);fails.slice(0,3).forEach(f=>console.log(' ',JSON.stringify(f)));if(fails.length||worst>0.01)process.exit(1);
