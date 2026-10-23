// Real browser storage/network/clock and API replay, with a disposable database.
import {createRequire} from 'node:module';
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=fs.mkdtempSync(path.join(root,'_audit_sandbox','offline-day-'));
const python=process.env.QINGSU_TEST_PYTHON||'python';
const env={...process.env,QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')};
const child=spawn(python,['-m','uvicorn','server:app','--host','127.0.0.1','--port','18010'],{cwd:root,env,stdio:'ignore'});
let browser;
try{
 const base='http://127.0.0.1:18010';
 for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const response=await fetch(base+'/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'offlineui',password:'UiSecure!123',age:30,height:170,weight_jin:160,target_weight_jin:140})});
 assert.equal(response.status,200);const user=await response.json();
 const seeded=spawnSync(python,['-c',"import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(\"UPDATE users SET created_at='2026-01-01 00:00:00'\");c.commit();c.close()",path.join(folder,'db/qingsu.db')]);
 assert.equal(seeded.status,0);
 browser=await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH?{executablePath:process.env.QINGSU_CHROME_PATH}:{})});
 const context=await browser.newContext({viewport:{width:393,height:850},timezoneId:'Asia/Taipei'});
 const page=await context.newPage();
 await page.clock.install({time:new Date(Date.now()-86400000)});
 await page.addInitScript(user=>{localStorage.setItem('QINGSU_AUTH_TOKEN',user.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:user.id,username:user.username}));},user);
 await page.goto(base);await page.waitForFunction(()=>state.dashboardLoaded);
 await context.setOffline(true);
 await page.evaluate(async()=>{try{await postApi('/api/workout/complete',{duration_minutes:20,cal_burned:100,plan_name:'offline test'});}catch{}});
 const draft=await page.evaluate(()=>readDrafts()[0]);assert.ok(draft.body.log_date);
 await page.clock.setSystemTime(new Date());
 await context.setOffline(false);await page.reload();await page.waitForFunction(()=>state.dashboardLoaded);
 assert.notEqual(await page.evaluate(()=>localDay()),draft.body.log_date);
 await page.evaluate(()=>syncOfflineDrafts());
 assert.equal(await page.evaluate(()=>readDrafts().length),0);
 const getRows=async()=>{
   const r=await fetch(base+'/api/records?kind=workout',{headers:{Authorization:'Bearer '+user.token}});
   assert.equal(r.status,200);return (await r.json()).rows;
 };
 let rows=await getRows();assert.equal(rows.length,1);assert.equal(rows[0].log_date,draft.body.log_date);
 await page.evaluate(draft=>{setDrafts([draft]);return syncOfflineDrafts();},draft);
 assert.equal((await getRows()).length,1);
 await page.evaluate(()=>{setDrafts([{id:'legacy-day',path:'/api/food/log',unsubmitted:true,body:{food_name:'旧餐食',slot:'午餐',request_id:'legacy-day'}}]);openDraftManager();});
 await page.locator('#draft-date-0').fill(draft.body.log_date);
 await page.getByRole('button',{name:'确认日期',exact:true}).click();
 await page.getByRole('button',{name:'同步并核对',exact:true}).click();
 await page.waitForFunction(()=>readDrafts().length===0);
 await page.screenshot({path:path.join(folder,'completed.png')});
 console.log(JSON.stringify({result:'PASS',checks:['offline day preserved across reload and next-day upload','same request replay writes once','legacy date explicitly confirmed'],occurrence_day:draft.body.log_date,screenshot:path.join(folder,'completed.png')}));
}finally{
 if(browser)await browser.close();
 if(child.exitCode===null){child.kill();await new Promise(resolve=>child.once('exit',resolve));}
}
