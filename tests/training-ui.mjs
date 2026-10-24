// Real Chromium + disposable Uvicorn/SQLite; no production accounts or data.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const root = path.resolve(import.meta.dirname, '..');
const folder = path.join(root, '_audit_sandbox', 'training-r187-' + process.pid);
fs.mkdirSync(folder, {recursive: true});
const base = 'http://127.0.0.1:18015';
const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python', ['-c',
  "import server,uvicorn;server.llm_chat=lambda *a,**k:None;server.web_search=lambda *a,**k:[];uvicorn.run(server.app,host='127.0.0.1',port=18015,log_level='warning',ws='websockets-sansio')"],
  {cwd: root, env: {...process.env, QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')}});
const log = fs.createWriteStream(path.join(folder,'server.log'));child.stdout.pipe(log);child.stderr.pipe(log);
let browser;
const checks=[];
const pageErrors=[];
const shotsDir=process.env.QINGSU_SHOTS_DIR;
if(shotsDir)fs.mkdirSync(shotsDir,{recursive:true});
const shot=(page,name)=>shotsDir?page.screenshot({path:path.join(shotsDir,name)}):Promise.resolve();
const cleanShot=async(page,name)=>{
  if(!shotsDir)return;
  await page.evaluate(()=>{const t=document.getElementById('web-toast-container');if(t)t.remove();}).catch(()=>{});
  await page.screenshot({path:path.join(shotsDir,name)});
};
try {
  for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}
  browser = await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH ? {executablePath:process.env.QINGSU_CHROME_PATH} : {}),args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const context=await browser.newContext({viewport:{width:393,height:850},permissions:['microphone']});
  const page=await context.newPage();
  page.on('pageerror',e=>pageErrors.push(String(e)));
  const build=Number(/versionCode\s+(\d+)/.exec(fs.readFileSync(path.join(root,'app/build.gradle'),'utf8'))[1]);
  const api=async(url,body,token)=>{
    const r=await fetch(base+url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Build':String(build),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
    const data=await r.json();assert.equal(r.status,200,JSON.stringify(data));return data;
  };
  const profile={password:'UiReview!123',age:30,height:170,weight_jin:160,target_weight_jin:140};
  const a=await api('/api/register',{...profile,username:'uiowner'}),b=await api('/api/register',{...profile,username:'uipartner'});

  const aid=a.id,bid=b.id;let sid;
  await page.addInitScript(({a})=>{if(!localStorage.getItem('QINGSU_AUTH_TOKEN')){localStorage.setItem('QINGSU_AUTH_TOKEN',a.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:a.id,username:'uiowner'}));}},{a});
  page.on('dialog',async d=>{assert.match(d.message(),/本机草稿|确认|删除/);await d.accept();});
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.QSTraining&&typeof switchTab==='function');await page.evaluate(()=>switchTab('workout'));await page.locator('#training-launch-btn').click();await page.waitForSelector('.train-tabs');
  assert.equal(await page.locator('.train-record').count(),0);assert.equal(await page.locator('.train-tabs button').count(),4);checks.push('workout entry opens private notebook with records/calendar/templates/progress and an honest empty state');
  await page.locator('[data-train=current]').click();assert.equal(await page.locator('.train-exercise').count(),4);assert.equal(await page.locator('.train-check input:checked').count(),0);checks.push('current workout imports as uncompleted targets, not fabricated completed sets');
  await page.locator('[data-train=back]').click();await page.locator('[data-train=blank]').click();await page.locator('#train-title').fill('力量记录 A');
  await page.locator('[data-field=name]').fill('Test Squat');await page.locator('[data-field=reps]').fill('10');await page.locator('[data-field=weight_kg]').fill('20');await page.locator('[data-field=done]').check();
  await page.locator('[data-train=save-completed]').click();assert.match(await page.locator('#train-error').innerText(),/实际训练时长/);assert.equal((await api('/api/records?kind=workout',null,a.token)).rows.length,0);checks.push('unfinished form gives a clear local validation message without writing a workout');
  await page.locator('[data-train=add-exercise]').click();const second=page.locator('.train-exercise').nth(1);await second.locator('[data-field=name]').fill('Plank');await second.locator('[data-field=kind]').selectOption('time');assert.equal(await page.locator('.train-exercise').first().locator('[data-field=done]').isChecked(),true,'changing one action type must preserve other completed groups');await second.locator('[data-field=seconds]').fill('45');
  const initial=await api('/api/training/sessions',null,a.token);const day=initial.today;const future=new Date(day+'T00:00:00Z');future.setUTCDate(future.getUTCDate()+1);const futureDay=future.toISOString().slice(0,10);
  await page.locator('#train-day').fill(futureDay);await page.locator('[data-train=save-plan]').click();await page.waitForSelector('.train-record');let rows=await api('/api/training/sessions',null,a.token);sid=rows.items[0].id;assert.equal(rows.items[0].status,'planned');assert.equal((await api('/api/records?kind=workout',null,a.token)).rows.length,0);checks.push('future plan saves privately without creating a workout or calories');
  await page.locator('[data-view=calendar]').click();await page.waitForSelector('.train-calendar');if(futureDay.slice(0,7)!==day.slice(0,7))await page.locator('[data-train=month-next]').click();await page.locator('[data-day="'+futureDay+'"]').click();await page.waitForSelector('.train-record');assert.equal(await page.locator('.train-record').count(),1);checks.push('calendar marks plans and opens a day-filtered record list');
  await page.locator('[data-train=edit]').click();await page.waitForSelector('#train-day');await page.locator('#train-day').fill(day);await page.locator('.train-summary [data-field=minutes]').fill('20');await page.locator('.train-exercise').nth(1).locator('[data-field=done]').check();await page.locator('[data-train=save-completed]').click();await page.waitForSelector('.train-record');
  let logs=(await api('/api/records?kind=workout',null,a.token)).rows;assert.equal(logs.length,1);assert.equal(logs[0].duration_minutes,20);assert.equal(logs[0].cal_burned,0);assert.equal(logs[0].training_session_id,sid);assert.equal((await api('/api/dashboard',null,a.token)).today_workout_done,true);checks.push('completing checked groups writes one linked workout and updates existing dashboard statistics without invented calorie burn');
  await page.locator('[data-view=progress]').click();await page.waitForSelector('#train-progress-select');await page.locator('#train-progress-select').selectOption({label:'Test Squat · 次数'});await page.waitForSelector('.train-progress-kpis');assert.match(await page.locator('.train-progress-kpis').innerText(),/20kg/);checks.push('factual action progress uses only this account completed sets');
  await page.locator('.train-progress-list [data-train=edit]').click();await page.waitForSelector('#train-title');await page.locator('.train-exercise').first().locator('[data-field=weight_kg]').fill('25');await page.locator('[data-train=save-completed]').click();await page.waitForSelector('.train-record');assert.equal((await api('/api/records?kind=workout',null,a.token)).rows.length,1);checks.push('editing a completed session updates its linked summary instead of making another workout');
  await page.locator('[data-train=edit]').click();await page.waitForSelector('#train-title');await page.locator('[data-train=as-template]').click();await page.waitForFunction(()=>!document.querySelector('[data-train=as-template]').disabled);await page.locator('[data-train=back]').click();await page.locator('[data-view=templates]').click();await page.waitForSelector('[data-train=use-template]');await page.locator('[data-train=use-template]').click();assert.equal(await page.locator('.train-check input:checked').count(),0);assert.equal(await page.locator('.train-exercise').count(),2);checks.push('personal template reuses actions and targets while clearing completed flags');
  await page.locator('.train-summary [data-field=minutes]').fill('10');await page.locator('.train-exercise').first().locator('[data-field=done]').check();let serverSaved=0,once=true;
  await page.route('**/api/training/sessions',async route=>{if(once&&route.request().method()==='POST'){once=false;const response=await route.fetch();serverSaved=(await response.json()).item.id;await route.abort('failed');}else await route.continue();});
  await page.locator('[data-train=save-completed]').click();await page.waitForFunction(()=>document.getElementById('train-error')?.textContent.includes('本机草稿'));await page.locator('[data-train=save-completed]').click();await page.waitForSelector('.train-record');await page.unroute('**/api/training/sessions');assert.ok(serverSaved>0);assert.equal((await api('/api/records?kind=workout',null,a.token)).rows.length,2);checks.push('lost save response keeps the same request ID; retry creates no second session or workout');
  const downloadEvent=page.waitForEvent('download');await page.locator('[data-train=export]').click();const download=await downloadEvent;assert.equal(download.suggestedFilename(),'轻塑训练手账.csv');await download.saveAs(path.join(folder,'training-export.csv'));assert.ok(fs.readFileSync(path.join(folder,'training-export.csv')).subarray(0,3).equals(Buffer.from([239,187,191])));checks.push('private training CSV downloads in browser with a UTF-8 BOM');
  await page.locator('[data-train=blank]').click();await page.locator('#train-title').fill('断网保留的草稿');await page.locator('[data-field=name]').fill('恢复动作');
  await page.route('**/api/training/sessions?*',route=>route.abort('failed'));await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.QSTraining);await page.evaluate(()=>QSTraining.open());await page.waitForSelector('#train-title');assert.equal(await page.locator('#train-title').inputValue(),'断网保留的草稿');await page.unroute('**/api/training/sessions?*');checks.push('account-specific local draft survives reload when training API is unavailable');
  await page.locator('[data-train=rest]').click();assert.match(await page.locator('#train-rest-clock').innerText(),/60 秒/);await page.waitForTimeout(1100);assert.match(await page.locator('#train-rest-clock').innerText(),/5[89] 秒/);await page.locator('[data-train=cancel-rest]').click();assert.match(await page.locator('#train-rest-clock').innerText(),/已取消/);checks.push('local rest countdown ticks and cancels without creating training data');
  for(const width of [320,393,1200]){await page.setViewportSize({width,height:850});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'training editor horizontal overflow');}await page.setViewportSize({width:393,height:850});await shot(page,'training-editor.png');checks.push('editor fits 320/393/1200 widths');
  await page.evaluate(({b})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',b.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:b.id,username:'uipartner'}));},{b});await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.QSTraining);await page.evaluate(()=>QSTraining.open());await page.waitForSelector('.train-tabs');assert.equal(await page.locator('[data-train=restore]').count(),0);assert.equal(await page.locator('.train-record').count(),0);checks.push('switching account does not reveal another account records or draft');
  await page.evaluate(({a})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',a.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:a.id,username:'uiowner'}));},{a});await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.QSTraining);await page.evaluate(()=>QSTraining.open());await page.waitForSelector('[data-train=restore]');await shot(page,'training-records.png');await page.evaluate(id=>QSTraining.edit(id),sid);await page.waitForSelector('#train-title');await page.locator('[data-train=delete]').click();await page.locator('#train-delete-confirm').click();await page.waitForSelector('.train-tabs');await page.waitForFunction(()=>!document.getElementById('account-tools-dialog')?.open);assert.equal((await api('/api/records?kind=workout',null,a.token)).rows.length,1);checks.push('deleting notebook session removes only its linked workout and recalculates statistics');
  assert.deepEqual(pageErrors,[]);fs.writeFileSync(path.join(folder,'result.json'),JSON.stringify({checks,errors:pageErrors},null,2));console.log(JSON.stringify({folder,checks,errors:pageErrors},null,2));
} catch (error) {
  const page=browser?.contexts()[0]?.pages()[0];
  console.error('PAGE_ERRORS', pageErrors);
  if(page){
    const diag=await page.evaluate(()=>({
      header: document.getElementById('header-profile-summary')?.innerText||'',
      modal: document.getElementById('profile-modal')?.className||'',
      toast: (document.getElementById('native-toast')?.innerText)||''
    })).catch(()=>null);
    console.error('DIAG', diag);
    await page.screenshot({path:path.join(folder,'failure.png')}).catch(()=>{});
  }
  throw error;
} finally {
  if(browser)await browser.close();
  if(child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}log.end();
}
