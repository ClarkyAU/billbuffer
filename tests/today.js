const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch();let fails=0;const ok=(c,t)=>{if(!c){fails++;console.log('FAIL',t);}else console.log('ok',t);};
for(const [w,cs] of [[390,'light'],[1440,'dark']]){
const p=await b.newPage({viewport:{width:w,height:900},colorScheme:cs});const errs=[];p.on('pageerror',e=>errs.push(e.message));
await p.goto('file://'+require('path').join(__dirname,'..','build','local.html'));
// make the rent fall due today
await p.evaluate(()=>{const r=S.bills.find(b=>/RENT/i.test(b.name));r.anchor=toISO(today());r.dom=ymd(today())[2];r.userDates=true;persist();render();});
const fig=async()=>+(await p.textContent('.hero .big')).replace(/[^0-9]/g,'');
const before=await fig();ok(await p.locator('#todayBox .today li').count()>=1,w+': card lists today\'s bill');
await p.check('[data-gone]');await p.waitForTimeout(200);const after=await fig();
ok(before-after===1850,w+': figure dropped by the rent ('+before+' to '+after+')');
ok((await p.textContent('#todayBox .note')).includes('gone out'),'note says all gone');
await p.reload();ok(await p.locator('[data-gone]:checked').count()===1,'tick survives reload');

await p.uncheck('[data-gone]');await p.waitForTimeout(200);ok(await fig()===before,'unticking restores the figure');
// a tick from yesterday no longer applies
await p.evaluate(()=>{S.paid={d:today()-1,ids:S.bills.map(b=>b.id)};persist();render();});ok(await fig()===before,'yesterday\'s ticks are ignored');
ok(!errs.length,'no errors '+errs);await p.close();}
process.exitCode=fails?1:0;console.log(fails?fails+' FAILED':'today checks passed');await b.close();})();
