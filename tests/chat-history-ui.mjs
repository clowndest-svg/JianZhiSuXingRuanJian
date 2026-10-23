// Real Chromium + disposable Uvicorn/SQLite; no production accounts or data.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const root = path.resolve(import.meta.dirname, '..');
const folder = path.join(root, '_audit_sandbox', 'history-r184-' + process.pid);
fs.mkdirSync(folder, {recursive: true});
const base = 'http://127.0.0.1:18014';
const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python', ['-c',
  "import server,uvicorn;server.llm_chat=lambda *a,**k:None;server.web_search=lambda *a,**k:[];uvicorn.run(server.app,host='127.0.0.1',port=18014,log_level='warning',ws='websockets-sansio')"],
  {cwd: root, env: {...process.env, QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')}});
const log = fs.createWriteStream(path.join(folder,'server.log'));child.stdout.pipe(log);child.stderr.pipe(log);
let browser;
const checks=[];checks.push=function(...items){console.log("STEP",...items);return Array.prototype.push.apply(this,items);};
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

  const aid=a.id,bid=b.id;
  await page.addInitScript(({token,aid})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:aid,username:'uiowner'}));},{token:a.token,aid});
  const send=async(text,owner=a,to=bid)=>(await api('/api/chat/send',{to,kind:'text',text},owner.token)).message;
  const own=await send('原始消息等待编辑');const theirs=await send('对方的这条只在自己删除',b,aid);
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>typeof QSChatTools==='object');await page.evaluate(id=>openDM(id),bid);await page.waitForSelector('[data-mid="'+own.id+'"]');
  await page.locator('[data-mid="'+own.id+'"]').click({button:'right'});await page.getByRole('button',{name:'重新编辑',exact:true}).click();await page.locator('#dm-edit-text').fill('修改后的新消息');await page.locator('#dm-edit-save').click();
  await page.waitForFunction(id=>qsFindBubble(id)?.body==='修改后的新消息',own.id);assert.match(await page.locator('[data-mid="'+own.id+'"]').innerText(),/已编辑/);
  assert.equal((await api('/api/chat/messages?with_user='+aid,null,b.token)).items.find(m=>m.id===own.id).body,'修改后的新消息');checks.push('desktop right-click edits own text; API peer sees revision and edited marker');
  await page.locator('[data-mid="'+theirs.id+'"]').dispatchEvent('touchstart');await page.waitForTimeout(550);await page.locator('[data-mid="'+theirs.id+'"]').dispatchEvent('touchend');
  assert.equal(await page.getByRole('button',{name:'重新编辑',exact:true}).count(),0);await page.getByRole('button',{name:'删除记录',exact:true}).click();await page.locator('#dm-delete-confirm').click();await page.waitForFunction(id=>!qsFindBubble(id),theirs.id);
  assert.ok((await api('/api/chat/messages?with_user='+aid,null,b.token)).items.some(m=>m.id===theirs.id));checks.push('mobile long press offers personal deletion; peer keeps original and cannot edit incoming');
  await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>typeof openDM==='function');await page.evaluate(id=>openDM(id),bid);await page.waitForSelector('[data-mid="'+own.id+'"]');assert.equal(await page.locator('[data-mid="'+theirs.id+'"]').count(),0);checks.push('personal deletion persists across reload');
  // Seed a long real history quickly in the isolated database, then exercise actual HTTP paging.
  const {spawnSync}=await import('node:child_process');
  const seeded=spawnSync(process.env.QINGSU_TEST_PYTHON||'python',['-c',`import sqlite3,sys,datetime; c=sqlite3.connect(sys.argv[1]); ck='${Math.min(aid,bid)}:${Math.max(aid,bid)}'; stamp=datetime.datetime.now(datetime.timezone.utc).isoformat(); c.executemany('INSERT INTO messages(conv_key,from_id,to_id,body,created_at) VALUES (?,?,?,?,?)',[(ck,${bid},${aid},'长记录编号%04d'%i,stamp) for i in range(420)]);c.commit()`,path.join(folder,'db','qingsu.db')],{encoding:'utf8'});assert.equal(seeded.status,0,seeded.stderr);
  await page.evaluate(()=>refreshThread(true));await page.waitForFunction(()=>cm.bubbles.length>=30);
  const totalUnread=await page.evaluate(()=>cm.bubbles.filter(m=>!m.read_at).length);await page.waitForTimeout(850);
  const history=await api('/api/chat/messages?with_user='+bid+'&limit=100',null,a.token);assert.ok(history.items.some(m=>!m.read_at),'opening chat must leave offscreen messages unread');checks.push('only visible foreground incoming messages get read receipts; offscreen history stays unread');
  for(let i=0;i<7;i++){await page.evaluate(()=>{dmUi.stickBottom=false;document.getElementById('thread-bubbles').scrollTop=0;});await page.waitForTimeout(150);await page.evaluate(()=>loadOlderMessages());await page.waitForTimeout(80);}
  assert.ok(await page.evaluate(()=>cm.bubbles.length<=120));assert.ok(await page.locator('#thread-bubbles [data-dm-key^="m"]').count()<=120);assert.equal(await page.evaluate(()=>QSChatTools.detached),true);await page.waitForSelector('#dm-latest');
  checks.push('reverse pagination across 420 records keeps both memory and DOM at 120 messages');
  const before=await page.evaluate(()=>cm.bubbles.map(m=>m.id));await send('正在查历史时的新消息',b,aid);await page.waitForFunction(()=>document.getElementById('dm-latest')?.textContent.includes('新消息'));assert.deepEqual(await page.evaluate(()=>cm.bubbles.map(m=>m.id)),before);checks.push('incoming websocket messages preserve history window and show return-latest badge');
  await page.evaluate(()=>QSChatTools.search());await page.locator('#dm-history-query').fill('长记录编号0009');await page.locator('#dm-history-form button').click();await page.waitForSelector('.chat-search-result');await page.locator('.chat-search-result').first().click();await page.waitForSelector('.dm-history-highlight');assert.ok(await page.evaluate(()=>cm.bubbles.length<=41));checks.push('server-backed history search jumps to bounded surrounding context');
  await page.locator('#dm-latest').click();await page.waitForFunction(()=>cm.bubbles.some(m=>m.body==='正在查历史时的新消息'));assert.equal(await page.evaluate(()=>QSChatTools.detached),false);checks.push('return latest fetches newest cursor window');
  // A slow older page must not overwrite a later explicit return to the newest page.
  let releaseOlder,notifyOlder;const olderWait=new Promise(r=>releaseOlder=r),seenOlder=new Promise(r=>notifyOlder=r);let captured;
  await page.route('**/api/chat/messages?*',async route=>{const u=new URL(route.request().url());if(Number(u.searchParams.get('cursor'))>0&&!u.searchParams.has('q')){captured=await route.fetch();notifyOlder();await olderWait;await route.fulfill({response:captured}).catch(()=>{});}else await route.continue();});
  await page.evaluate(()=>{loadOlderMessages();});await Promise.race([seenOlder,new Promise((_,reject)=>setTimeout(()=>reject(new Error('older request did not start')),5000))]);
  await page.evaluate(()=>QSChatTools.latest());const fresh=await page.evaluate(()=>cm.bubbles.map(m=>m.id));releaseOlder();await page.waitForTimeout(300);assert.deepEqual(await page.evaluate(()=>cm.bubbles.map(m=>m.id)),fresh);await page.unroute('**/api/chat/messages?*');checks.push('late older-page response cannot replace an explicit latest window');
  const last=await send('精准回执等待测试');await page.waitForFunction(id=>!!qsFindBubble(id),last.id);await page.evaluate(id=>handleWsEvent({data:JSON.stringify({t:'read',by:cm.thread.partner.id,message_ids:[id],read_at:'now'})}),last.id);assert.match(await page.locator('[data-mid="'+last.id+'"]').innerText(),/已读/);checks.push('targeted read event repaints sender status immediately');
  // Cancellation uses the real UI; deliberately late network text must be ignored.
  await page.evaluate(()=>{cm.bubbles.push({id:999999,from_id:state.user.id,to_id:cm.thread.partner.id,kind:'audio',created_at:new Date().toISOString(),duration:2,body:'',media_url:''});paintThread();});
  let release;const waiting=new Promise(r=>release=r);await page.route('**/api/chat/asr',async route=>{await waiting;await route.fulfill({json:{code:0,text:'不应显示的迟到结果'}}).catch(()=>{});});await page.route('**/api/chat/asr/cancel',route=>route.fulfill({json:{code:0,hidden:true}}));
  await page.evaluate(()=>{dmTranscribe(999999);});await page.waitForSelector('[data-mid="999999"] .dm-asr.pending');await page.locator('[data-mid="999999"] .dm-asr button').click();release();await page.waitForTimeout(500);assert.equal(await page.evaluate(()=>qsFindBubble(999999).asr_text),'');assert.equal(await page.locator('[data-mid="999999"] .dm-asr.pending').count(),0);checks.push('cancel ASR dismisses pending state and discards late transcription');
  await page.evaluate(()=>{cm.bubbles=cm.bubbles.filter(m=>m.id!==999999);cm.myTheme='skin-ai';paintThread();});
  for(const width of [320,393,1200]){await page.setViewportSize({width,height:850});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await page.setViewportSize({width:393,height:850});await page.evaluate(()=>openBubbleTheme());await shot(page,'r184-bubbles.png');await page.getByRole('button',{name:'聊天背景',exact:true}).click();await shot(page,'r184-backgrounds.png');checks.push('refined theme/background panels stay within 320/393/1200 widths');
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
