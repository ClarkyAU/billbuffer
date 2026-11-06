// End-to-end against the real server: shared copy, live sync, conflicts, passcode, and HTTP details.
const { chromium } = require('playwright');const { spawn } = require('child_process');const fs=require('fs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const DATA=process.env.BB_TEST_DATA||require('path').join(require('os').tmpdir(),'bb-test-data');let fails=0;const ok=(c,t)=>{if(!c){fails++;console.log('  FAIL',t);}else console.log('  ok',t);};
const start=(port,pass)=>{fs.rmSync(DATA,{recursive:true,force:true});return spawn('python3',['-u',require('path').join(__dirname,'..','server.py')],{env:{...process.env,BB_DATA:DATA,BB_PORT:String(port),BB_PASSCODE:pass}});};
(async()=>{const b=await chromium.launch();
 // ---- open mode, two devices
 let srv=start(8161,'');await sleep(900);const U='http://localhost:8161/';
 const mk=async w=>{const c=await b.newContext({viewport:{width:w,height:900}});const p=await c.newPage();const e=[];p.on('pageerror',x=>e.push(x.message));await p.goto(U);await sleep(1200);return {p,e};};
 const A=await mk(390),B=await mk(1440);
 ok(await A.p.locator('#signinForm').count()===0,'open mode: no sign-in');
 ok(await A.p.evaluate(()=>localStorage.getItem('billbuffer.v1'))===null,'no bills copy on the device');
 await A.p.click('.tabbar [data-tab=settings]');await A.p.click('[data-sec=people]');await A.p.click('[data-act=pedit] >> nth=0');await A.p.fill('#p-pay','2026-11-06');await A.p.click('[data-act=psave]');
 await A.p.click('.tabbar [data-tab=bills]');await A.p.click('[data-act=new] >> visible=true');await A.p.fill('#e-name','Water');await A.p.fill('#e-amt','120');await A.p.fill('#e-date','2026-12-01');await A.p.selectOption('#e-own','p1');await A.p.click('[data-act=saveBill]');
 await A.p.click('.tabbar [data-tab=now]');await A.p.click('#s-bal');await A.p.keyboard.type('777');await sleep(1200);
 let st=JSON.parse(fs.readFileSync(DATA+'/state.json'));ok(st.state.bills.some(x=>x.name==='Water')&&st.state.settings.balance===777,'server has the bill and balance (v'+st.version+')');
 await B.p.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));await sleep(800);
 ok((await B.p.textContent('.glegend')).includes('$777'),'second device sees the new balance');
 // conflict: B edits from an old version
 await B.p.evaluate(()=>{serverVersion=1;});await B.p.click('.topnav [data-tab=bills]');await B.p.click('.brow:has-text("Water")');await B.p.fill('#e-amt','130');await B.p.click('[data-act=saveBill]');await sleep(1200);
 ok((await B.p.textContent('#app')).includes('saved a change just before you'),'stale save refused and explained');
 st=JSON.parse(fs.readFileSync(DATA+'/state.json'));ok(st.state.bills.find(x=>x.name==='Water').amount===120,'newer version not overwritten');
 // HTTP details
 const h=await fetch(U+'api/status',{method:'HEAD'});ok(h.status===200&&(await h.text())==='','HEAD has no body');
 ok((await fetch(U+'fonts/missing.woff2')).status===404,'missing asset is a 404');
 ok((await fetch(U+'some/page')).headers.get('content-type').startsWith('text/html'),'other paths open the app');
 ok((await fetch(U+'api/state',{method:'PUT',headers:{'Origin':'http://evil.example','Content-Type':'application/json'},body:'{}'})).status===403,'cross-site write refused');
 ok(!A.e.length&&!B.e.length,'no page errors '+A.e.concat(B.e).join(';'));srv.kill();await sleep(300);
 // ---- passcode mode
 srv=start(8162,'correct horse battery');await sleep(900);const V='http://localhost:8162/';
 const c=await b.newContext({viewport:{width:390,height:860}});const p=await c.newPage();await p.goto(V);await sleep(1000);
 ok(await p.locator('#signinForm').count()===1,'passcode mode asks to sign in');
 ok((await fetch(V+'api/state')).status===401,'data needs a token');
 await p.fill('#si-pass','wrong one');await p.click('#signinForm button');await sleep(1600);ok((await p.textContent('.msg')).includes('tries left'),'wrong passcode explained');
 await p.fill('#si-pass','correct horse battery');await p.click('#signinForm button');await sleep(1500);ok(await p.locator('.hero').count()===1,'signed in');
 const tk=JSON.parse(fs.readFileSync(DATA+'/tokens.json'));ok(Object.keys(tk).every(k=>/^[0-9a-f]{64}$/.test(k)),'only token hashes stored');
 await p.click('.tabbar [data-tab=settings]');await p.click('[data-sec=passcode]');await sleep(600);ok((await p.textContent('#devList')).includes('This device'),'device list');
 await p.click('[data-act=signOut]');await sleep(600);ok(await p.locator('#signinForm').count()===1,'signed out');
 srv.kill();await b.close();fs.rmSync(DATA,{recursive:true,force:true});
 process.exitCode=fails?1:0;console.log(fails?fails+' FAILED':'all server checks passed');})();
