// The in-app passcode: turn on, sign in elsewhere, change, turn off, and the TrueNAS override.
const { chromium } = require('playwright');const { spawn } = require('child_process');const fs=require('fs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const DATA=process.env.BB_TEST_DATA||require('path').join(require('os').tmpdir(),'bb-test-data');let fails=0;
const ok=(c,t)=>{if(!c){fails++;console.log('  FAIL',t);}else console.log('  ok',t);};
const start=(port,pass,keep)=>{if(!keep)fs.rmSync(DATA,{recursive:true,force:true});return spawn('python3',['-u',require('path').join(__dirname,'..','server.py')],{env:{...process.env,BB_DATA:DATA,BB_PORT:String(port),BB_PASSCODE:pass}});};
(async()=>{const b=await chromium.launch();let srv=start(8171,'');await sleep(900);const U='http://localhost:8171/';
 const mk=async w=>{const c=await b.newContext({viewport:{width:w,height:900}});const p=await c.newPage();const e=[];p.on('pageerror',x=>e.push(x.message));await p.goto(U);await sleep(1200);return {p,e,w};};
 const A=await mk(1440),B=await mk(390);
 const openSec=async(P)=>{await P.p.click((P.w>=1024?'.topnav':'.tabbar')+' [data-tab=settings]');await P.p.click('[data-sec=passcode]');await sleep(500);};
 const pull=async P=>{await P.p.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));await sleep(900);};
 const msg=async P=>(await P.p.locator('.msg').allTextContents()).join(' ');
 await openSec(A);ok((await A.p.textContent('.setitem.on')).includes('Off'),'section shows Off');ok(await A.p.locator('[data-sec=sharing]').count()===0,'Sharing section gone');
 await A.p.fill('#pc-new','short');await A.p.fill('#pc-new2','short');await A.p.click('#pcOn button');await sleep(200);ok((await msg(A)).includes('8 characters'),'too short refused');
 await A.p.fill('#pc-new','correct horse');await A.p.fill('#pc-new2','correct hose');await A.p.click('#pcOn button');await sleep(200);ok((await msg(A)).includes("don't match"),'mismatch refused');
 await A.p.fill('#pc-new','correct horse');await A.p.fill('#pc-new2','correct horse');await A.p.click('#pcOn button');await sleep(1200);
 ok((await msg(A)).includes('Passcode on'),'turned on');const pf=fs.readFileSync(DATA+'/passcode.json','utf8');ok(!pf.includes('correct horse')&&JSON.parse(pf).iter>=100000,'stored as a slow salted hash, not plain text');
 ok((await A.p.textContent('#devList')).includes('This device'),'A listed as signed in');
 await A.p.reload();await sleep(1200);ok(await A.p.locator('.hero').count()===1,'A stays signed in after reload');
 ok((await fetch(U+'api/state')).status===401,'data now needs a token');
 await pull(B);ok(await B.p.locator('#signinForm').count()===1,'other device is asked to sign in');
 await B.p.fill('#si-pass','correct horse');await B.p.uncheck('#si-keep');await B.p.click('#signinForm button');await sleep(1300);
 ok(await B.p.locator('.hero').count()===1,'B signs in');
 ok(!JSON.parse(await B.p.evaluate(()=>localStorage.getItem('billbuffer.sync'))).token&&!!(await B.p.evaluate(()=>sessionStorage.getItem('billbuffer.sync.token'))),'unticked: sign-in kept only until the app closes');
 // change
 await openSec(A);await A.p.fill('#pc-cur','nope nope');await A.p.fill('#pc-new','battery staple');await A.p.fill('#pc-new2','battery staple');await A.p.click('#pcChange button');await sleep(1600);
 ok((await msg(A)).includes("isn't right"),'change needs the right current passcode');
 await A.p.fill('#pc-cur','correct horse');await A.p.fill('#pc-new','battery staple');await A.p.fill('#pc-new2','battery staple');await A.p.click('#pcChange button');await sleep(1300);
 ok((await msg(A)).includes('Passcode changed'),'changed');await pull(B);ok(await B.p.locator('#signinForm').count()===1,'other devices signed out after change');
 await B.p.fill('#si-pass','correct horse');await B.p.click('#signinForm button');await sleep(1600);ok((await B.p.textContent('#app')).includes("isn't right"),'old passcode no longer works');
 await B.p.fill('#si-pass','battery staple');await B.p.click('#signinForm button');await sleep(1300);ok(await B.p.locator('.hero').count()===1,'new passcode works');
 // turn off
 await openSec(A);await A.p.fill('#pc-off','battery staple');await A.p.click('#pcOff button');await sleep(1300);
 ok((await msg(A)).includes('Passcode off')&&!fs.existsSync(DATA+'/passcode.json'),'turned off, hash deleted');
 const C=await mk(390);ok(await C.p.locator('.hero').count()===1,'a new device opens without signing in');
 await openSec(B);ok((await B.p.textContent('.card h2')).includes('Turn on')&&await B.p.locator('#pcOn').count()===1,'B notices it is off when opening the section');
 ok(!A.e.length&&!B.e.length&&!C.e.length,'no page errors '+A.e.concat(B.e,C.e).join(';'));
 // passcode set in the app, then BB_PASSCODE set in TrueNAS: TrueNAS wins
 await openSec(A);await A.p.fill('#pc-new','in app pass');await A.p.fill('#pc-new2','in app pass');await A.p.click('#pcOn button');await sleep(1000);srv.kill();await sleep(400);
 srv=start(8172,'truenas passcode',true);await sleep(900);const V='http://localhost:8172/';
 ok((await (await fetch(V+'api/status')).json()).lock==='server','TrueNAS passcode takes priority');
 const D=await (async()=>{const c=await b.newContext({viewport:{width:390,height:860}});const p=await c.newPage();await p.goto(V);await sleep(1000);return {p,w:390};})();
 await D.p.fill('#si-pass','in app pass');await D.p.click('#signinForm button');await sleep(1600);ok((await D.p.textContent('#app')).includes("isn't right"),'app passcode ignored while TrueNAS one is set');
 await D.p.fill('#si-pass','truenas passcode');await D.p.click('#signinForm button');await sleep(1200);await openSec(D);
 ok((await D.p.textContent('#app')).includes('set in the container')&&await D.p.locator('#pcChange').count()===0,'section says change it in TrueNAS');
 const r=await fetch(V+'api/passcode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new:'whatever123'})});ok(r.status===409,'API refuses to change a TrueNAS passcode');
 srv.kill();await b.close();fs.rmSync(DATA,{recursive:true,force:true});process.exitCode=fails?1:0;console.log(fails?fails+' FAILED':'all passcode checks passed');})();
