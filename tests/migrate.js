// Older saves: payday lived in settings. It must move onto each person, and old fields must drop out.
const fs=require('fs'),path=require('path');const js=fs.readFileSync(path.join(__dirname,'..','build','app.js'),'utf8');const logic=js.split('/*LOGIC_START*/')[1].split('/*LOGIC_END*/')[0];
eval(logic+`
const v1={v:1,example:false,settings:{nextPayday:'2026-11-06',payDays:7,buffer:350,balance:'1234.5',contribution:90},bills:[{id:'d:RENT',name:'Rent',amount:1850,cadence:'monthly',anchor:'2026-10-03',dom:3,include:true,src:'auto',edited:true}],txns:[],files:[],meta:{}};
const m=cleanState(v1,true);let ok=true;const chk=(c,t)=>{if(!c){ok=false;console.log('FAIL',t);}};
chk(m.people.every(p=>p.nextPayday==='2026-11-06'&&p.freq==='weekly'),'payday moved to people');
chk(JSON.stringify(Object.keys(m.settings).sort())==='["autoStrip","balance","buffer"]','only current settings kept: '+Object.keys(m.settings));
chk(m.settings.buffer===350&&m.settings.balance===1234.5,'buffer and balance kept');
chk(m.bills[0].locked&&m.bills[0].category==='housing','edited bill locked and categorised');
S=buildExample();const P=computePlan();chk(P.required>0&&P.people.length===2&&!('nextPay' in P),'example plan');
console.log(ok?'migration checks passed':'migration checks FAILED');if(!ok)process.exit(1);`);
