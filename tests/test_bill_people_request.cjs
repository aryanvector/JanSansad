const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync('frontend/bills.js','utf8');
const helper=source.slice(source.indexOf('async function fetchBillPeople('),source.indexOf("\n$('bill-results').addEventListener('toggle'"));
async function main(){
 let callback,cleared=0,route,signal;
 const ctx=vm.createContext({AbortController,encodeURIComponent,
  setTimeout:fn=>{callback=fn;return 1;},clearTimeout:id=>{assert.equal(id,1);cleared++;},
  fetch:async(url,options)=>{route=url;signal=options.signal;return {ok:true,json:async()=>({people:[]})};}});
 vm.runInContext(helper,ctx);
 assert.equal((await ctx.fetchBillPeople('B test')).people.length,0);
 assert.equal(route,'/api/bills/B%20test/people');
 assert.equal(signal.aborted,false);assert.equal(cleared,1);
 ctx.fetch=async()=>({ok:false});
 await assert.rejects(ctx.fetchBillPeople('B'),/Reopen this bill to retry/);
 assert.equal(cleared,2);
 ctx.fetch=(url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{const e=new Error('aborted');e.name='AbortError';reject(e);}));
 const pending=ctx.fetchBillPeople('B');callback();
 await assert.rejects(pending,/timed out.*Official documents remain available/);
 assert.equal(cleared,3);
 console.log('Bill presenter request: success, upstream failure and timeout checks passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
