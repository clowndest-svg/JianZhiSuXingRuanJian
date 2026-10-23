import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=fs.mkdtempSync(path.join(root,'_audit_sandbox','admin-pages-'));
const log=fs.createWriteStream(path.join(folder,'server.log'));
const server=spawn(process.env.QINGSU_TEST_PYTHON||'python',['tests/admin-pagination-server.py'],{cwd:root,env:process.env});
server.stdout.pipe(log);server.stderr.pipe(log);
let browser;
try{
 const base='http://127.0.0.1:18009';
 for(let i=0;i<100;i++){try{if((await fetch(base)).status===401)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH?{executablePath:process.env.QINGSU_CHROME_PATH}:{})});
 const context=await browser.newContext({httpCredentials:{username:'qingsu',password:'dev-basic-pw'},viewport:{width:1280,height:850}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(base);
 await page.locator('#token').fill('dev-token-please-rotate');
 await page.locator('#dologin').click();
 await page.locator('nav').waitFor({state:'visible'});
 const scenarios=[['feedback-workspace','fb-pages'],['reports-workspace','report-pages'],['users','user-pages'],['audit','audit-pages']];
 for(const [section,pager] of scenarios){
   await page.locator(`nav [data-go="${section}"]`).click();
   if(section==='users'){await page.locator('#q').fill('page');await page.locator('#search').click();}
   if(section==='audit'){await page.locator('#audit-action').fill('batch2');await page.locator('#reload-audit').click();}
   await page.waitForFunction(id=>document.querySelector('#'+id+' span').textContent.includes('共 123 条'),pager);
   await page.locator('#'+pager+' [data-page="next"]').click();
   await page.waitForFunction(id=>document.querySelector('#'+id+' span').textContent.includes('第 2 页'),pager);
   assert.equal(await page.locator('#'+pager+' [data-page="previous"]').isDisabled(),false);
   await page.locator('#'+pager+' [data-page="previous"]').click();
   await page.waitForFunction(id=>document.querySelector('#'+id+' span').textContent.includes('第 1 页'),pager);
 }
 await page.locator('nav [data-go="feedback-workspace"]').click();
 await page.locator('#fb-kind').selectOption('idea');
 await page.waitForFunction(()=>document.querySelector('#fb-pages span').textContent.includes('共 0 条'));
 assert.equal(await page.locator('#fb-pages [data-page="next"]').isDisabled(),true);
 await page.screenshot({path:path.join(folder,'empty-filter.png')});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({result:'PASS',checks:['four real paginated workspaces','previous page','filtered total and empty state'],screenshot:path.join(folder,'empty-filter.png')}));
}finally{
 if(browser)await browser.close();
 if(server.exitCode===null){server.kill();await new Promise(resolve=>server.once('exit',resolve));}log.end();
}
