// Clicks through every screen and the main actions in the local build, on a phone and a desktop.
const { chromium } = require('playwright');
const file='file://'+require('path').join(__dirname,'..','build','local.html');
(async()=>{const b=await chromium.launch();let fails=0;const ok=(c,t)=>{if(!c){fails++;console.log('  FAIL',t);}};
for(const [w,h] of [[390,844],[1440,900]]){
  const c=await b.newContext({viewport:{width:w,height:h},locale:'en-AU'});const p=await c.newPage();const errs=[];p.on('pageerror',e=>errs.push(e.message));
  const wide=w>=1024,nav=t=>p.click((wide?'.topnav':'.tabbar')+` [data-tab=${t}]`);
  const over=async l=>ok(!(await p.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth)),'no sideways scroll on '+l);
  await p.goto(file);console.log(w+'px');
  // Now: balance box, typing then Enter, then tab away
  const fig=async()=>(await p.textContent('.hero .big')).trim();
  const before=await fig();await p.fill('#s-bal','99999');await p.press('#s-bal','Enter');await p.press('#s-bal','Tab');
  ok(await p.locator('.hpill').textContent()==='Covered','pill says Covered after a big balance');
  ok(await fig()===before,'figure does not change with balance');
  ok((await p.textContent('.hint')).includes('more than needed'),'hint shows spare');
  await p.fill('#s-bal','');await p.dispatchEvent('#s-bal','change');ok(await p.locator('.hpill').count()===0,'no pill without balance');
  const need=+(await p.textContent('.hero .big')).replace(/[^0-9]/g,'');await p.click('#s-bal');await p.keyboard.type(String(Math.floor(need/2)));await p.waitForTimeout(450);ok((await p.textContent('.hpill')).startsWith('Short'),'figure updates while typing');
  await p.click('[data-act=showWorking]');ok(await p.locator('.working[open]').count()===1,'tightest-day tile opens the working');
  await p.click('.cyc details summary >> nth=1');ok(await p.locator('.cyc details[open] .items li').count()>1,'fortnight opens');
  await over('Now');
  // tile goes to that person's bills
  await p.click('.tile[data-act=ownerBills] >> nth=0');ok(await p.locator('.chip[data-own=p1][aria-pressed=true]').count()===1,'person tile filters Bills');
  // Bills: chips wrap (no horizontal scroll inside)
  const sc=await p.$$eval('.chips',a=>a.every(x=>x.scrollWidth<=x.clientWidth+1));ok(sc,'filter chips wrap');
  await p.click('.chip[data-own=all]');await p.click('.chip[data-cat=utilities]');const n=await p.locator('.blist .brow').count();ok(n===4,'category filter shows 4 utilities, got '+n);
  await p.click('.chip[data-cat=all]');
  if(wide){await p.click('.b-extra .tile >> nth=1');ok(await p.locator('.chip[data-own=p2][aria-pressed=true]').count()===1,'side tile filters');await p.click('.b-extra .tile >> nth=1');ok(await p.locator('.chip[data-own=all][aria-pressed=true]').count()===1,'tapping again clears');}
  // edit a bill, add an amount change, save
  await p.click('.brow:has-text("Aussie")');await p.fill('#c-amt','95');await p.fill('#c-from','2027-01-01');await p.click('[data-act=chAdd]');
  ok((await p.textContent('#e-chlist')).includes('$95.00'),'amount change listed');await p.fill('#e-name','Aussie BB');await p.click('[data-act=saveBill]');
  ok((await p.textContent('.blist')).includes('Aussie BB'),'bill renamed');ok((await p.textContent('.brow:has-text("Aussie BB")')).includes('$95.00 from'),'change shown on row');
  // add a bill, validation keeps typed text
  await p.click('[data-act=new] >> visible=true');await p.fill('#e-name','Water');await p.click('[data-act=saveBill]');
  ok(await p.inputValue('#e-name')==='Water'&&(await p.textContent('.editor .msg')).length>0,'validation keeps input');
  await p.fill('#e-amt','120');await p.fill('#e-date','2026-12-01');await p.selectOption('#e-own','p2');await p.click('[data-act=saveBill]');
  ok((await p.textContent('.blist')).includes('Water'),'bill added');await over('Bills');
  // Calendar
  await nav('calendar');await p.click('[data-act=calNext]');await p.click('.day:not(.blank) >> nth=2');ok(await p.locator('.cols.cal h2').count()>=2,'day detail');await over('Calendar');
  // Settings sections
  await nav('settings');
  for(const s of ['people','buffer','categories','statements','backup','reset']){await p.click(`[data-sec=${s}]`);ok(await p.locator(wide?'.sectitle':'.sethead h2').textContent()!=='', 'section '+s);await over('Settings '+s);if(!wide)await p.click('.sethead [data-sec=""]');}
  await p.click('[data-sec=people]');await p.click('[data-act=pedit] >> nth=1');await p.fill('#p-pay','2026-11-13');await p.fill('#p-in','300');await p.click('[data-act=psave]');const pt=await p.textContent('.blist');ok(pt.includes('$300'),'fixed pay-in saved: '+pt.replace(/\s+/g,' ').slice(0,200)+' | '+(await p.locator('.msg').allTextContents()));
  if(!wide)await p.click('.sethead [data-sec=""]');await p.click('[data-sec=categories]');await p.fill('#newCat','Kids');await p.click('[data-act=catAdd]');ok((await p.locator('.cats li').count())===6,'category added');
  if(!wide)await p.click('.sethead [data-sec=""]');await p.click('[data-sec=buffer]');await p.fill('#s-buf','500');await p.dispatchEvent('#s-buf','change');
  await nav('now');ok((await p.textContent('.glegend')).includes('$500'),'buffer flows to Now');
  // reset everything, app still works empty
  await nav('settings');if(!wide&&await p.locator('.sethead [data-sec=""]').count())await p.click('.sethead [data-sec=""]');await p.click('[data-sec=reset]');await p.click('[data-kind=all]');await p.click('[data-kind=all]');
  await nav('now');ok((await p.textContent('.hero')).includes('No bills yet'),'empty state after reset');await nav('bills');await nav('calendar');
  ok(!errs.length,'no page errors '+errs.join('; '));await c.close();}
process.exitCode=fails?1:0;console.log(fails?fails+' FAILED':'all smoke checks passed');await b.close();})();
