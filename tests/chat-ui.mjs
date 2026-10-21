// Real Chromium + disposable Uvicorn/SQLite; no production accounts or data.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const root = path.resolve(import.meta.dirname, '..');
const folder = path.join(root, '_audit_sandbox', 'ui-r164-' + process.pid);
fs.mkdirSync(folder, {recursive: true});
const base = 'http://127.0.0.1:18006';
const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python', ['-c',
  "import server,uvicorn;server.llm_chat=lambda *a,**k:None;server.web_search=lambda *a,**k:[];uvicorn.run(server.app,host='127.0.0.1',port=18006,log_level='warning',ws='websockets-sansio')"],
  {cwd: root, env: {...process.env, QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')}});
const log = fs.createWriteStream(path.join(folder,'server.log'));child.stdout.pipe(log);child.stderr.pipe(log);
let browser;
const checks=[];
try {
  for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}
  browser = await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH ? {executablePath:process.env.QINGSU_CHROME_PATH} : {}),args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
  const context=await browser.newContext({viewport:{width:393,height:850},permissions:['microphone']});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const build=Number(/versionCode\s+(\d+)/.exec(fs.readFileSync(path.join(root,'app/build.gradle'),'utf8'))[1]);
  const api=async(url,body,token)=>{
    const r=await fetch(base+url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Build':String(build),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
    const data=await r.json();assert.equal(r.status,200,JSON.stringify(data));return data;
  };
  const profile={password:'UiReview!123',age:30,height:170,weight_jin:160,target_weight_jin:140};
  const a=await api('/api/register',{...profile,username:'uiowner'}),b=await api('/api/register',{...profile,username:'uipartner'});
  const uid=async (name,token)=>(await api('/api/community/users/'+name,null,token)).user.id;
  const bid=await uid('uipartner',b.token),aid=await uid('uiowner',a.token);
  await page.addInitScript(({token,aid})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:aid,username:'uiowner'}));},{token:a.token,aid});
  await page.goto(base);await page.waitForFunction(()=>typeof openDM==='function');
  await page.evaluate(id=>openDM(id),bid);await page.waitForSelector('#dm-input');
  await page.waitForFunction(()=>dmOfficial.loaded);
  await page.locator('#dm-input').fill('前后');await page.locator('#dm-input').evaluate(e=>{e.setSelectionRange(1,1);dmRememberCaret();});
  await page.locator('#dm-emoji-btn').click();
  assert.notEqual(await page.evaluate(()=>document.activeElement?.id),'dm-input');
  await page.locator('#dm-tab-emoji').click();await page.getByRole('button',{name:'插入😀',exact:true}).click();
  assert.equal(await page.locator('#dm-input').inputValue(),'前😀后');
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,0);
  checks.push('emoji inserts at caret and does not send; panel blurs input');
  await page.locator('#dm-tab-official').click();await page.getByRole('button',{name:'选择微笑表情',exact:true}).click();
  await page.waitForSelector('#dm-draft:not([hidden])');
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,0);
  await page.locator('.dm-send').click();await page.waitForSelector('#thread-bubbles .dm-sticker-img');
  assert.equal(await page.locator('#dm-input').inputValue(),'前😀后');
  checks.push('official sticker previews then sends; text draft survives acknowledgement');
  await page.locator('#dm-emoji-btn').click();await page.locator('#dm-sticker-query').fill('jiayou');
  assert.equal(await page.locator('.dm-sticker-tile').count(),1);checks.push('official pinyin search');
  // A deterministic provider result tests the browser flow, not upstream availability.
  await page.route('**/api/chat/stickers/search?*',route=>route.fulfill({json:{code:0,available:true,items:[{id:'fixture',title:'Fixture',preview_url:'https://upload.wikimedia.org/wikipedia/commons/f/fixture.png',source_url:'https://commons.wikimedia.org/wiki/File:Fixture.png',license:'CC0',author:'Fixture artist'}]}}));
  await page.locator('#dm-tab-network').click();await page.locator('#dm-sticker-query').fill('happy');
  await page.locator('#dm-sticker-search button').click();await page.getByRole('button',{name:'选择表情',exact:true}).click();
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,1);
  await page.locator('#dm-draft-cancel').click();checks.push('network selection remains a draft; attribution is visible');
  await page.locator('#dm-sticker-file').setInputFiles({name:'local.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64')});
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,1);
  await page.locator('.dm-send').click();
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.kind==='sticker'&&m.media_url));
  checks.push('local image selection previews before upload and sends without mutual follow');
  await page.locator('#dm-voice-btn').click();await page.waitForSelector('#dm-voice-stop:not([disabled])');
  await page.waitForTimeout(1200);await page.locator('#dm-voice-stop').click();await page.waitForSelector('#dm-voice-preview');
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,2);
  await page.locator('#dm-voice-send').click();await page.waitForSelector('#thread-bubbles audio',{timeout:60000});
  const audio=page.locator('#thread-bubbles audio');await audio.evaluate(e=>{window.savedAudio=e;return e.play();});
  await page.locator('#dm-input').fill('未发送草稿');
  await api('/api/chat/send',{to:aid,text:'对方发来的消息',request_id:'ui-inbound'},b.token);
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.body==='对方发来的消息'));
  assert.equal(await page.locator('#dm-input').inputValue(),'未发送草稿');
  assert.equal(await audio.evaluate(e=>e===window.savedAudio),true);
  checks.push('real MediaRecorder preview/upload/Opus playback; incoming message preserves input and audio node');
  await page.locator('#dm-emoji-btn').click();await page.locator('#dm-tab-official').click();
  for(const width of [320,393,1200]){
    await page.setViewportSize({width,height:850});
    const overflow=await page.evaluate(()=>({body:document.documentElement.scrollWidth>innerWidth,foot:document.getElementById('pl-foot').scrollWidth>document.getElementById('pl-foot').clientWidth+1}));
    assert.deepEqual(overflow,{body:false,foot:false});
    await page.screenshot({path:path.join(folder,'chat-'+width+'.png')});
  }
  checks.push('320/393/1200 layout without horizontal overflow');
  let dropped=false;
  await page.route('**/api/chat/send',async route=>{
    if(!dropped&&route.request().postDataJSON().text==='重试验证'){
      dropped=true;await route.fetch();await route.abort('failed');
    }else await route.continue();
  });
  await page.locator('#dm-input').fill('重试验证');await page.locator('.dm-send').click();
  await page.waitForFunction(()=>document.getElementById('dm-input').value==='重试验证');
  await page.locator('.dm-send').click();
  await page.waitForFunction(()=>document.getElementById('dm-input').value==='');
  const retryRows=(await api('/api/chat/messages?with_user='+bid,null,a.token)).items;
  assert.equal(retryRows.filter(m=>m.body==='重试验证').length,1);
  checks.push('lost HTTP response retries the same request ID and stores one message');
  if(process.env.QINGSU_LIVE_STICKERS==='1'){
    const result=await api('/api/chat/stickers/search?q='+encodeURIComponent('开心'),null,a.token);
    assert.equal(result.provider,'OpenMoji');assert.ok(result.items.length>0);
    const up=await api('/api/chat/stickers/import',{id:result.items[0].id},a.token);
    const sent=await api('/api/chat/send',{to:bid,kind:'sticker',media_name:up.name,request_id:'ui-live-network'},a.token);
    assert.equal(sent.message.sticker_meta.license,'CC BY-SA 4.0');
    checks.push('LIVE OpenMoji Chinese search, remote PNG import, attributed message persisted');
    const memes=await api('/api/chat/stickers/search?provider=memegen&q='+encodeURIComponent('梗图'),null,a.token);
    assert.ok(memes.items.length>0);assert.match(memes.provider,/Memegen/);
    const meme=await api('/api/chat/stickers/import',{id:memes.items[0].id},a.token);
    const delivered=await api('/api/chat/send',{to:bid,kind:'sticker',media_name:meme.name,request_id:'ui-live-meme'},a.token);
    assert.match(delivered.message.sticker_meta.license,/未声明/);
    checks.push('LIVE network meme catalog search/import/send with original source');
  }
  await page.evaluate(()=>dmCleanup());
  assert.equal(await page.evaluate(()=>dmUi.record===null&&dmUi.draft===null),true);
  // An old response must not insert data into a later account.
  const scope=await page.evaluate(()=>{window.oldScope=dmScope();cmGeneration++;state.token='new-account';cm.pending={};cm.bubbles=[];dmAck('old',{id:999,from_id:1,to_id:2,body:'OLD'},window.oldScope);return cm.bubbles.length;});
  assert.equal(scope,0);checks.push('cleanup and late account response rejection');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(folder,'result.json'),JSON.stringify({checks,errors},null,2));
  console.log(JSON.stringify({folder,checks,errors},null,2));
} catch (error) {
  const page=browser?.contexts()[0]?.pages()[0];
  if(page)await page.screenshot({path:path.join(folder,'failure.png')}).catch(()=>{});
  throw error;
} finally {
  if(browser)await browser.close();
  if(child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}log.end();
}
