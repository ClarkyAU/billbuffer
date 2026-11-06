// Against the real server: the backup time is kept in the shared copy, and a change made while the app
// is checking for updates is never silently lost.
const { chromium } = require('playwright');const { spawn } = require('child_process');const fs=require('fs'),path=require('path'),os=require('os');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));let fails=0;const ok=(c,t)=>{if(!c){fails++;console.log('  FAIL',t);}else console.log('  ok',t);};
const DATA=process.env.BB_TEST_DATA||path.join(os.tmpdir(),'bb-test-data');fs.rmSync(DATA,{recursive:true,force:true});
const srv=spawn('python3',['-u',path.join(__dirname,'..','server.py')],{env:{...process.env,BB_DATA:DATA,BB_PORT:'8195',BB_PASSCODE:''}});
const U='http://localhost:8195/';
(async()=>{await sleep(900);const b=await chromium.launch();
 const c=await b.newContext({serviceWorkers:'block',acceptDownloads:true,viewport:{width:1440,height:900}});const p=await c.newPage();const errs=[];p.on('pageerror',e=>errs.push(e.message));
 await p.goto(U);await sleep(1200);
 // make a real save first so there is a shared copy
 await p.evaluate(()=>{S.settings.buffer=321;persist();});await sleep(900);
 const open=async()=>{await p.click('.topnav [data-tab=settings]');await p.click('[data-sec=backup]');};
 const pill=()=>p.evaluate(()=>[...document.querySelectorAll('section.card h2 .pill')].map(x=>x.textContent).join(','));
 await open();ok((await p.textContent('#app')).includes('Save a backup'),'button says Save a backup');
 await Promise.all([p.waitForEvent('download',{timeout:5000}).catch(()=>null),p.click('[data-act=backup]')]);await sleep(1200);
 ok((await pill())==='Up to date','up to date after backing up');
 await p.reload();await sleep(1500);await open();
 ok((await pill())==='Up to date','still up to date after reopening the app');
 // another device saves, then this one makes a change while its check for updates is still on the way
 const st=await (await fetch(U+'api/state')).json();
 const r=await fetch(U+'api/state',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({base:st.version,state:{...st.state,settings:{...st.state.settings,buffer:999}}})});
 ok(r.status===200,'other device saved');
let hit=false;
 await p.route(/api\/state\?since=/,async route=>{hit=true;await sleep(700);await route.continue();});
console.log('    state before:',await p.evaluate(()=>JSON.stringify({m:Sync.mode,d:Sync.dirty,b:Sync.busy,sv:serverVersion})));
 await p.evaluate(()=>{pullNow();setTimeout(()=>{S.settings.buffer=555;persist();},100);});
 await sleep(2500);
 const text=await p.textContent('#app');const buf=await p.evaluate(()=>S.settings.buffer);
 const disk=JSON.parse(fs.readFileSync(path.join(DATA,'state.json'))).state.settings.buffer;console.log('    update check delayed:',hit,'| page',buf,'server',disk,'notice',text.includes('saved a change just before you'));
 ok((buf===555&&disk===555)||text.includes('saved a change just before you'),'the change is saved, or the person is told it was not');
 ok(!errs.length,'no page errors '+errs.join(';'));
 await b.close();srv.kill();fs.rmSync(DATA,{recursive:true,force:true});
 process.exitCode=fails?1:0;console.log(fails?fails+' FAILED':'backup and update checks passed');})();
