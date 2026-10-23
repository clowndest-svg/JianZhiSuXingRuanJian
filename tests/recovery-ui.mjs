// Real browser recovery flow against a disposable local database.
import {createRequire} from 'node:module';
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=fs.mkdtempSync(path.join(root,'_audit_sandbox','recovery-ui-'));
const python=process.env.QINGSU_TEST_PYTHON||'python';
const env={...process.env,QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')};
const child=spawn(python,['-m','uvicorn','server:app','--host','127.0.0.1','--port','18008'],{cwd:root,env,stdio:'ignore'});
let browser;
try{
 const base='http://127.0.0.1:18008';
 for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const signup=await fetch(base+'/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'recoveryui',password:'Temporary!123',age:30,height:170,weight_jin:160,target_weight_jin:140})});
 assert.equal(signup.status,200,await signup.text());
 const prepared=spawnSync(python,['-c',"import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1]);c.execute('UPDATE users SET reset_expires_at=?,reset_consumed=0',(int(time.time())+1800,));c.commit();c.close()",path.join(folder,'db/qingsu.db')]);
 assert.equal(prepared.status,0);
 browser=await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH?{executablePath:process.env.QINGSU_CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:393,height:850}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(base);
 await page.locator('#login-username').fill('recoveryui');
 await page.locator('#login-password').fill('Temporary!123');
 await page.evaluate(()=>submitLogin());
 await page.waitForSelector('#recovery-password');
 await page.reload();
 await page.waitForSelector('#recovery-password');
 await page.locator('#recovery-password').fill('NewSecure!123');
 await page.locator('#recovery-password-again').fill('wrong');
 await page.evaluate(()=>finishRecoveryPassword());
 assert.match(await page.locator('#recovery-error').textContent(),/不一致/);
 await page.locator('#recovery-password-again').fill('NewSecure!123');
 await page.evaluate(()=>finishRecoveryPassword());
 await page.waitForFunction(()=>state.dashboardLoaded);
 assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem(USER_KEY)).password_change_required),false);
 await page.screenshot({path:path.join(folder,'completed.png')});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'PASS',checks:['temporary login prompts for new password','reload preserves recovery flow','mismatch stays in dialog','new password unlocks dashboard'],screenshot:path.join(folder,'completed.png')}));
}finally{
 if(browser)await browser.close();
 if(child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}
}
