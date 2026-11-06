// A made-up three-month statement (Date, Description, Credit, Debit, Balance), dated back from today,
// so the tests never need anyone's real bank data.
module.exports=function sampleCsv(){
  const DAY=86400000,end=new Date();end.setUTCHours(0,0,0,0);const start=new Date(end.getTime()-92*DAY);
  let seed=7;const rnd=()=>{seed=(seed*16807)%2147483647;return seed/2147483647;};
  const rows=[],fmt=d=>`${String(d.getUTCDate()).padStart(2,'0')}/${String(d.getUTCMonth()+1).padStart(2,'0')}/${d.getUTCFullYear()}`;
  const monthly=[['RENT PAYMENT SUNSET PROPERTY',1850,3],['ORIGIN ENERGY ELECTRICITY',182.4,15],['TELSTRA MOBILE',65,22],['NETFLIX.COM',18.99,9],['AAMI CAR INSURANCE',112.4,27]];
  for(let d=new Date(start);d<end;d=new Date(d.getTime()+DAY)){
    const dom=d.getUTCDate(),n=Math.round((d-start)/DAY);
    monthly.forEach(([t,a,m])=>{if(dom===m)rows.push([d,t,0,a]);});
    if(n%14===4)rows.push([d,'ANYTIME FITNESS',0,34.95]);
    if(n%14===1)rows.push([d,'TRANSFER FROM PAY',1650,0]);
    if(rnd()<.35)rows.push([d,['WOOLWORTHS','COLES','BP FUEL','CAFE'][Math.floor(rnd()*4)],0,Math.round((5+rnd()*120)*100)/100]);
  }
  let bal=3000;const lines=['Date,Description,Credit,Debit,Balance'];
  rows.forEach(([d,t,c,a])=>{bal+=c-a;lines.push([fmt(d),t,c?c.toFixed(2):'',a?a.toFixed(2):'',bal.toFixed(2)].join(','));});
  return lines.join('\n')+'\n';
};
