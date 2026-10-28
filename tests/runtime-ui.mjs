// Real Chromium, CacheStorage, request races and isolated SQLite; no production data.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=fs.mkdtempSync(path.join(root,'_audit_sandbox','runtime-ui-'));
const base='http://127.0.0.1:18012',checks=[];
const proc=spawn(process.env.QINGSU_TEST_PYTHON||'python',['-m','uvicorn','server:app','--host','127.0.0.1','--port','18012','--no-access-log'],{cwd:root,env:{...process.env,QINGSU_SKIP_MIGRATE:'0',QINGSU_DB_DIR:folder+'/db',QINGSU_KEY_DIR:folder+'/keys',QINGSU_UPLOAD_DIR:folder+'/uploads',QINGSU_WEB_DIR:root+'/app/src/main/assets',QINGSU_CACHE_NAMESPACE:'runtime-ui-'+process.pid,PYTHONDONTWRITEBYTECODE:'1'}});
const log=fs.createWriteStream(folder+'/server.log');proc.stdout.pipe(log);proc.stderr.pipe(log);let browser;
try{
 for(let n=0;n<150;n++){try{if((await fetch(base+'/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext();const page=await context.newPage();
 const build=Number(/versionCode\s+(\d+)/.exec(fs.readFileSync(root+'/app/build.gradle','utf8'))[1]);
 const api=async(p,body,token)=>{const r=await fetch(base+p,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Build':String(build),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});const d=await r.json();assert.equal(r.status,200,JSON.stringify(d));return d;};
 const profile={password:'Synthetic!123',age:30,height:170,weight_jin:160,target_weight_jin:140};
 const a=await api('/api/register',{...profile,username:'runtime_a'}),b=await api('/api/register',{...profile,username:'runtime_b'});
 await page.addInitScript(a=>{localStorage.setItem('QINGSU_AUTH_TOKEN',a.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:a.id,username:'runtime_a'}));},a);
 const requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
 await page.goto(base);await page.waitForFunction(()=>state.dashboardLoaded);
 assert.equal(requests.includes('/exercise_poses.json'),false);await page.evaluate(()=>openExerciseDetail(0));await page.waitForFunction(()=>EX_POSES!==null);await page.evaluate(()=>closeExerciseDetail());checks.push('poses lazy load');
 await page.evaluate(()=>{window._oldWrite=queueProfileUpdate({height:173}).catch(e=>e.code);window._queuedWrite=queueProfileUpdate({age:32}).catch(e=>e.code);});
 // This first pair checks the normal same-account path, then races delayed writes below.
 await page.evaluate(()=>Promise.all([window._oldWrite,window._queuedWrite]));
 let release;await page.route('**/api/profile/update',async route=>{await new Promise(r=>{release=r;});await route.continue();});
 const writeRequest=page.waitForRequest('**/api/profile/update');
 await page.evaluate(()=>{window._oldWrite=queueProfileUpdate({height:175}).catch(e=>e.code);window._queuedWrite=queueProfileUpdate({age:33}).catch(e=>e.code);});
 await writeRequest;
 await page.evaluate(b=>{saveAuthSession(b.token,{id:b.id,username:'runtime_b'});},b);release();
 assert.equal(await page.evaluate(()=>window._queuedWrite),'stale_session');await page.evaluate(()=>window._oldWrite);await page.unroute('**/api/profile/update');
 const after=await api('/api/dashboard',null,b.token);assert.equal(after.profile.age,30);assert.equal(after.profile.height,170);checks.push('queued writes never change new account');
 await page.route('**/api/food/log',route=>route.fulfill({status:200,contentType:'application/json',body:'{"code":'}));
 const error=await page.evaluate(()=>postApi('/api/food/log',{food_name:'synthetic rice',slot:'午餐'}).then(()=>'',e=>e.code));assert.equal(error,'invalid_response');assert.equal(await page.evaluate(()=>readDrafts().length),1);await page.unroute('**/api/food/log');checks.push('truncated receipt retains draft');
 let estimateRelease;await page.route('**/api/food/estimate',async route=>{await new Promise(r=>{estimateRelease=r;});await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,cal:999,grams:200,status:{source:'synthetic'}})});});
 const estimateRequest=page.waitForRequest('**/api/food/estimate');
 await page.evaluate(()=>{openMealConfirm({food_name:'old meal',estimate:100});window._estimate=estimateMealByAi().catch(e=>{window._estimateError=String(e);});});
 await estimateRequest.catch(async error=>{console.log(await page.evaluate(()=>({error:window._estimateError,token:!!state.token,meal:pendingMeal?.food_name,output:document.getElementById('meal-ai-result')?.textContent})));throw error;});await page.evaluate(()=>openMealConfirm({food_name:'new meal',estimate:222}));estimateRelease();await page.evaluate(()=>window._estimate);assert.equal(await page.locator('#meal-confirm-cal').inputValue(),'222');checks.push('late estimate cannot overwrite another meal');
 await page.evaluate(()=>document.getElementById('account-tools-dialog').close());
 await page.evaluate(async id=>{await openDM(id);dmCall.state='active';dmCall.peer={name:'synthetic'};dmCall.stream={getAudioTracks:()=>[{enabled:true}],getTracks:()=>[]};dmCallRender();},a.id);
 await page.waitForFunction(()=>!document.getElementById('dm-call-layer').inert);
 await page.locator('.dm-call-down').click();await page.waitForFunction(()=>!document.getElementById('dm-call-mini').inert);
 await page.locator('#dm-call-mini-main').click();await page.waitForFunction(()=>!document.getElementById('dm-call-layer').inert);
 await page.locator('#dm-call-mute').click();assert.equal(await page.evaluate(()=>dmCall.muted),true);
 await page.evaluate(()=>{dmCallReset();qsCloseAllPages();});checks.push('call layer minimize and restore stays interactive');
 // Run the actual SW in a real browser Worker with the browser's real CacheStorage.
 const sw=fs.readFileSync(root+'/app/src/main/assets/sw.js','utf8');
 const result=await page.evaluate(async sw=>{
  const script=`const origin=${JSON.stringify(location.origin)};const handlers={};self.addEventListener=(t,f)=>{handlers[t]=f;};\n${sw}\nself.onmessage=async()=>{try{const c=await caches.open(CACHE);await Promise.all(Array.from({length:80},(_,i)=>remember(c,origin+'/app.js?v=test'+i,new Response(String(i)))));self.postMessage({count:(await c.keys()).length,first:!!(await c.match(origin+'/app.js?v=test0')),last:!!(await c.match(origin+'/app.js?v=test79'))});}catch(e){self.postMessage({error:String(e)});}};`;
  const url=URL.createObjectURL(new Blob([script],{type:'application/javascript'}));const worker=new Worker(url);try{return await new Promise((resolve,reject)=>{worker.onmessage=e=>resolve(e.data);worker.onerror=e=>reject(Error(e.message));worker.postMessage({});});}finally{worker.terminate();URL.revokeObjectURL(url);}
 },sw);
 assert.deepEqual(result,{count:64,first:false,last:true});checks.push('real CacheStorage concurrent trim');
 await page.evaluate(async()=>{
  await caches.delete('qingsu-shell-b'+APP_BUILD);
  await caches.open('qingsu-shell-b0');
  await navigator.serviceWorker.register('/sw.js');await navigator.serviceWorker.ready;
 });
 await page.reload();await page.waitForFunction(()=>navigator.serviceWorker.controller!==null&&state.dashboardLoaded);
 assert.equal(await page.evaluate(async()=>(await caches.keys()).includes('qingsu-shell-b0')),false);checks.push('real SW install activates current build only');
 await context.setOffline(true);await page.reload();await page.waitForFunction(()=>typeof openMealConfirm==='function');
 await page.evaluate(async()=>{const c=await caches.open('qingsu-shell-b'+APP_BUILD);if(await c.match('/api/dashboard'))throw Error('private API cached');});checks.push('offline shell loads without caching private API');
 console.log(JSON.stringify({checks,passed:checks.length,synthetic_only:true}));
}finally{
 if(browser)await browser.close();proc.kill();await new Promise(resolve=>proc.exitCode!==null?resolve():proc.once('exit',resolve));log.end();
 fs.rmSync(folder,{recursive:true,force:true});
}
