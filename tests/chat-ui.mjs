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
  let stickerSearch = {code:0,available:true,sources:['360 图片'],items:[{id:'fixture',title:'Fixture',preview_url:'https://upload.wikimedia.org/wikipedia/commons/f/fixture.png',source_url:'https://commons.wikimedia.org/wiki/File:Fixture.png',license:'CC0',author:'Fixture artist',source_label:'360 图片'}]};
  await page.route('**/api/chat/stickers/search?*',route=>{
    const pageNo=Number(new URL(route.request().url()).searchParams.get('page')||0);
    if(stickerSearch.available===false)return route.fulfill({json:stickerSearch});
    const base=stickerSearch.items[0];
    const items=[0,1].map(i=>Object.assign({},base,{id:'fixture-'+pageNo+'-'+i,title:'Fixture '+pageNo+'-'+i}));
    route.fulfill({json:Object.assign({},stickerSearch,{page:pageNo,has_more:pageNo===0,items})});
  });
  await page.locator('#dm-tab-network').click();await page.locator('#dm-sticker-query').fill('happy');
  await page.locator('#dm-sticker-search button').click();
  await page.waitForSelector('.dm-network-item');
  assert.equal(await page.locator('.dm-network-item').count(),2);
  await page.locator('#dm-more-btn').click();
  await page.waitForFunction(()=>document.querySelectorAll('.dm-network-item').length===4);
  assert.match(await page.locator('#dm-sticker-content').textContent(),/没有更多了/);
  checks.push('network search loads the next page at the bottom');
  assert.equal(await page.locator('.dm-network-source').count(),0);
  assert.equal(await page.locator('.dm-network-item .dm-license').count(),0);
  assert.equal(await page.locator('.dm-network-item a').count(),0);
  assert.equal(await page.evaluate(()=>dmAttributionHidden({license:'版权归原作者，来源未声明许可'})),true);
  assert.equal(await page.evaluate(()=>dmAttributionHidden({license:'CC BY-SA 4.0'})),false);
  await page.locator('.dm-network-item button').first().click();
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,1);
  await page.locator('#dm-draft-cancel').click();checks.push('network selection remains a draft; list has no source links or license text');
  await page.locator('#dm-sticker-file').setInputFiles({name:'local.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64')});
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,1);
  await page.locator('.dm-send').click();
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.kind==='sticker'&&m.media_url));
  checks.push('local image selection previews before upload and sends without mutual follow');
  await page.locator('#thread-bubbles img.dm-sticker-img').last().click();
  await page.waitForFunction(()=>document.getElementById('account-tools-dialog').open);
  assert.ok(await page.locator('#account-tools-dialog img').count());
  await page.evaluate(()=>document.getElementById('account-tools-dialog').close());
  await page.waitForFunction(()=>!document.getElementById('page-layer').inert);
  checks.push('sent image sticker opens the full-size image viewer');
  const messagesBeforeVoice=(await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length;
  await shot(page,'dm-mode-text.png');
  await page.locator('#dm-mode-btn').click();
  assert.equal(await page.locator('#dm-hold-bar').isVisible(),true);
  assert.equal(await page.locator('#dm-input').isVisible(),false);
  assert.equal(await page.locator('#dm-send-btn').isVisible(),false);
  await shot(page,'dm-mode-voice.png');
  // 上传故意拖慢 900ms：验证“松开立刻出气泡”不依赖服务器返回
  await page.route('**/api/chat/media',async route=>{await new Promise(r=>setTimeout(r,900));await route.continue();});
  const voiceBox=await page.locator('#dm-hold-bar').boundingBox();
  await page.mouse.move(voiceBox.x+voiceBox.width/2,voiceBox.y+voiceBox.height/2);
  await page.mouse.down();await page.waitForTimeout(700);
  assert.equal(await page.locator('#dm-hold-layer').isVisible(),true);
  assert.match(await page.locator('#dm-hold-sheet-main').textContent(),/松开 发送/);
  assert.match(await page.locator('#dm-hold-live').textContent(),/正在录音|正在准备麦克风/);
  await page.mouse.move(voiceBox.x+voiceBox.width/2,voiceBox.y+voiceBox.height/2-120);
  await page.waitForFunction(()=>document.querySelector('#dm-hold-layer.cancel'));
  assert.match(await page.locator('#dm-hold-sheet-main').textContent(),/松开 取消/);
  await page.mouse.move(voiceBox.x+voiceBox.width/2,voiceBox.y+voiceBox.height/2);
  await page.waitForFunction(()=>!document.querySelector('#dm-hold-layer.cancel'));
  checks.push('sliding up shows the cancel state and sliding back re-arms sending');
  await page.waitForTimeout(500);
  await shot(page,'dm-hold-holding.png');
  await page.mouse.up();
  const releasedAt=Date.now();
  await page.waitForSelector('#dm-hold-layer',{state:'hidden'});
  await page.waitForSelector('#thread-bubbles .cm-bubble.pending',{timeout:2000});
  const pendingMs=Date.now()-releasedAt;
  assert.ok(pendingMs<600,`pending bubble took ${pendingMs}ms`);
  checks.push('wechat-style hold overlay prompts on press and hides on release');
  await page.waitForSelector('#thread-bubbles .cm-bubble.pending .dm-audio-wx:not(.pending)',{timeout:5000});
  checks.push('sending voice bubble appears before the upload finishes');
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.kind==='audio'),null,{timeout:60000});
  await page.unroute('**/api/chat/media');
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,messagesBeforeVoice+1);
  assert.equal(await page.locator('#thread-bubbles .dm-audio-wx').count(),1);
  assert.match(await page.locator('#web-toast-container').textContent(),/语音已发送/);
  checks.push('voice mode hold-to-talk sends the released recording immediately and toasts');
  const audio=page.locator('#thread-bubbles .dm-audio-wx audio');await audio.evaluate(e=>{window.savedAudio=e;return e.play();});
  await page.waitForFunction(()=>{const a=document.querySelector('#thread-bubbles .dm-audio-wx.playing audio');return !!(a&&a.currentTime>0);},null,{timeout:15000});
  await shot(page,'dm-audio-playing.png');
  checks.push('wechat-style audio bubble marks itself playing and decodes authoritative audio');
  // 转文字：气泡下方有入口，长按菜单也能转；结果落在气泡里（真实模型走服务端契约测试，这里钉界面接线）
  assert.equal(await page.locator('#thread-bubbles .dm-asr-btn').count(),1);
  await page.route('**/api/chat/asr',route=>route.fulfill({json:{code:0,text:'今天下午三点开会，别忘了带电脑。'}}));
  await page.locator('#thread-bubbles .cm-bubble.media').last().click({button:'right'});
  await page.waitForSelector('#bubble-menu button');
  assert.match(await page.locator('#bubble-menu').textContent(),/转文字/);
  await page.locator('#bubble-menu button').first().click();
  await page.waitForFunction(()=>/下午三点/.test(document.querySelector('#thread-bubbles .dm-asr')?.textContent||''));
  assert.equal(await page.locator('#thread-bubbles .dm-asr-btn').count(),0);
  await page.unroute('**/api/chat/asr');
  await shot(page,'dm-asr.png');
  checks.push('voice bubble converts to text and shows the transcript');
  // 转文字会重绘气泡（节点本来就会换）；重新记下当前 audio 节点，
  // 后面的检查仍然是“收到新消息的重绘不许把正在播的节点换掉”。
  await audio.evaluate(e=>{window.savedAudio=e;});
  // 失败要看得见：上传被掐断时气泡撤回、语音面板回来可重试，而不是静默消失
  const failedBefore=(await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length;
  await page.route('**/api/chat/media',route=>route.abort());
  await page.mouse.move(voiceBox.x+voiceBox.width/2,voiceBox.y+voiceBox.height/2);
  await page.mouse.down();await page.waitForTimeout(1200);await page.mouse.up();
  await page.waitForSelector('#dm-voice-panel:not([hidden])',{timeout:10000});
  await page.waitForFunction(()=>/未确认发送成功/.test(document.querySelector('#dm-voice-status')?.textContent||''),null,{timeout:10000});
  assert.match(await page.locator('#web-toast-container').textContent(),/没发出去/);
  assert.equal((await api('/api/chat/messages?with_user='+bid,null,a.token)).items.length,failedBefore);
  assert.equal(await page.locator('#thread-bubbles .cm-bubble.pending').count(),0);
  await page.unroute('**/api/chat/media');
  await page.locator('#dm-voice-panel button').first().click();
  assert.equal(await page.locator('#dm-voice-panel').isVisible(),false);
  checks.push('failed voice upload is visible, recoverable and leaves no pending bubble');
  await page.locator('#dm-mode-btn').click();
  assert.equal(await page.locator('#dm-input').isVisible(),true);
  assert.equal(await page.locator('#dm-send-btn').isVisible(),true);
  assert.equal(await page.locator('#dm-hold-bar').isVisible(),false);
  checks.push('left button switches voice and text input modes');
  await page.locator('#dm-input').fill('未发送草稿');
  await api('/api/chat/send',{to:aid,text:'对方发来的消息',request_id:'ui-inbound'},b.token);
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.body==='对方发来的消息'));
  assert.equal(await page.locator('#dm-input').inputValue(),'未发送草稿');
  assert.equal(await audio.evaluate(e=>e===window.savedAudio),true);
  const audioMenuPrevented=await audio.evaluate(e=>{const ev=new MouseEvent('contextmenu',{bubbles:true,cancelable:true});e.dispatchEvent(ev);return ev.defaultPrevented;});
  assert.equal(audioMenuPrevented,false,'audio contextmenu must keep the browser menu');
  const featuresSource=fs.readFileSync(path.join(root,'app/src/main/assets/features.js'),'utf8');
  assert.match(featuresSource,/<video[^>]*oncontextmenu="event\.stopPropagation\(\);return true"/);
  checks.push('Opus playback; incoming message preserves input and audio node');
  checks.push('audio playback and audio/video native context menus survive bubble handling');
  // 引用回复：长按菜单 → 引用 → 输入区出现引用条 → 发送后气泡带引用块并清空引用条
  await page.locator('#dm-input').fill('');
  await page.locator('#thread-bubbles .cm-bubble.them').filter({hasText:'对方发来的消息'}).last().click({button:'right'});
  await page.waitForSelector('#bubble-menu button');
  await page.getByRole('button',{name:'引用',exact:true}).click();
  await page.waitForSelector('#dm-quote-bar:not([hidden])');
  assert.match(await page.locator('#dm-quote-bar').textContent(),/对方发来的消息/);
  await page.locator('#dm-input').fill('收到，马上到');
  await page.locator('#dm-send-btn').click();
  await page.waitForFunction(()=>cm.bubbles.some(m=>m.body==='收到，马上到'&&m.quote));
  await page.waitForFunction(()=>/对方发来的消息/.test(document.querySelector('#thread-bubbles .dm-quote-inline')?.textContent||''));
  assert.equal(await page.locator('#dm-quote-bar').isVisible(),false);
  checks.push('quote reply shows the original and clears after sending');
  const micGate=await page.evaluate(async()=>{const saved=window.AndroidBridge;window.AndroidBridge={microphonePermissionState:()=> 'blocked',requestMicrophonePermission(){}};const blocked=await dmEnsureMicrophone();window.AndroidBridge={microphonePermissionState:()=> 'granted',requestMicrophonePermission(){}};const granted=await dmEnsureMicrophone();window.AndroidBridge=saved;return {blocked,granted};});
  assert.deepEqual(micGate,{blocked:false,granted:true});
  checks.push('microphone preflight blocks blocked state and passes granted state');
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
  stickerSearch={code:0,available:false,items:[],detail:'上游暂时没返回'};
  await page.locator('#dm-emoji-btn').click();
  await page.locator('#dm-tab-network').click();
  await page.locator('#dm-sticker-query').fill('你好');
  await page.locator('#dm-sticker-search button').click();
  await page.waitForSelector('.dm-generate-btn');
  await page.evaluate(()=>{window.__QS_TEST_MEME_BG__='data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="420"><rect width="640" height="420" fill="#0F766E"/></svg>');});
  await page.locator('.dm-generate-btn').click();
  await page.waitForSelector('#dm-draft:not([hidden]) img');
  assert.ok((await page.locator('#dm-draft img').getAttribute('src')).startsWith('blob:'));
  const stickersBefore=await page.locator('#thread-bubbles img.dm-sticker-img').count();
  await page.locator('.dm-send').click();
  await page.waitForFunction(n=>document.querySelectorAll('#thread-bubbles img.dm-sticker-img').length>n,stickersBefore);
  checks.push('empty upstream offers a generated text meme and sends it as a sticker');
  await page.locator('#dm-input').focus();
  await page.setViewportSize({width:393,height:520});
  await page.waitForTimeout(450);
  const keyboardState=await page.evaluate(()=>{const host=document.getElementById('thread-bubbles'),last=host.lastElementChild,hr=host.getBoundingClientRect(),lr=last.getBoundingClientRect();return {atBottom:host.scrollHeight-host.scrollTop-host.clientHeight<2,inside:lr.bottom<=hr.bottom+2&&lr.top>=hr.top-2};});
  assert.deepEqual(keyboardState,{atBottom:true,inside:true});
  await page.setViewportSize({width:393,height:850});
  checks.push('keyboard-sized viewport keeps the latest message visible');
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
  // 档案保存：顶栏的身高与体重都要立刻变，训练场景选择要走自定义卡片
  await api('/api/weight/log',{weight_jin:152},a.token);
  await page.evaluate(()=>syncRemoteDashboard());
  await page.waitForFunction(()=>Number(state.currentWeightJin)===152,null,{timeout:15000});
  await page.evaluate(()=>openProfileModal());
  assert.equal(await page.locator('#prof-weight-jin').inputValue(),'152','档案弹窗要预填顶栏那个数');
  await page.locator('#prof-height').fill('173');
  await page.locator('#prof-weight-jin').fill('138.5');
  await page.locator('#prof-scene-cards .choice-card[data-value="band"]').click();
  assert.equal(await page.locator('#prof-scene').inputValue(),'band');
  assert.match(await page.locator('#prof-plan-preview').innerText(),/弹力带塑形/);
  await cleanShot(page,'profile-scene-band.png');
  await page.evaluate(()=>saveCustomProfile());
  await page.waitForFunction(()=>{const t=document.getElementById('header-profile-summary')?.innerText||'';return /173cm/.test(t)&&/138\.5斤/.test(t);},null,{timeout:15000});
  const dash=await api('/api/dashboard',null,a.token);
  assert.equal(dash.current_weight_jin,138.5);
  assert.equal(dash.profile.height,173);
  checks.push('saving the profile updates the header weight and height immediately');
  // 训练计划必须由「目标身材 × 场景」共同决定；切场景不刷新页面
  await page.evaluate(()=>switchTab('workout'));
  await page.waitForFunction(()=>document.querySelector('#workout-scene-switch .scene-btn[data-value="band"]')?.classList.contains('active'),null,{timeout:10000});
  assert.match(await page.locator('#workout-context-title').innerText(),/弹力带塑形/);
  assert.match(await page.locator('#workout-exercises-card').innerText(),/弹力带臀桥/);
  assert.equal(await page.locator('#btn-timer-main').innerText(),'重置主课 30 分');
  assert.equal(await page.locator('#timer-display').innerText(),'30:00');
  await cleanShot(page,'workout-band.png');
  checks.push('profile scene selection changes the workout plan and timer');
  await page.evaluate(()=>{window.__sceneSwitchNoReload=1;});
  await page.locator('#workout-scene-switch .scene-btn[data-value="gym"]').click();
  await page.waitForFunction(()=>document.querySelector('#workout-scene-switch .scene-btn[data-value="gym"]')?.classList.contains('active'),null,{timeout:10000});
  assert.match(await page.locator('#workout-exercises-card').innerText(),/杠铃\/哑铃臀推/);
  assert.equal(await page.evaluate(()=>window.__sceneSwitchNoReload===1),true,'scene switch must not reload the page');
  let sceneSaved=false;
  for(let i=0;i<60;i++){const d=await api('/api/dashboard',null,a.token);if(d.profile.scene==='gym'){sceneSaved=true;break;}await new Promise(r=>setTimeout(r,100));}
  assert.equal(sceneSaved,true,'scene switch must persist');
  await cleanShot(page,'workout-gym.png');
  checks.push('workout-tab scene switch updates the plan immediately and persists without reload');
  await page.evaluate(()=>openProfileModal());
  await page.locator('#modal-body-shapes-grid #shape-card-female_lean').click();
  await page.waitForFunction(()=>document.querySelector('#workout-exercises-card')?.innerText.includes('史密斯机宽距深蹲'),null,{timeout:10000});
  assert.match(await page.locator('#workout-context-title').innerText(),/修长轻盈/);
  assert.equal(await page.locator('#workout-scene-switch .scene-btn[data-value="gym"]').evaluate(el=>el.classList.contains('active')),true);
  await cleanShot(page,'profile-plan-preview.png');
  await page.evaluate(()=>closeProfileModal());
  await page.setViewportSize({width:320,height:740});
  await page.waitForTimeout(120);
  await page.evaluate(()=>{const t=document.getElementById('web-toast-container');if(t)t.remove();});
  const narrow=await page.evaluate(()=>{
    const p=document.getElementById('panel-workout');
    return {doc:document.documentElement.scrollWidth,body:document.body.scrollWidth,w:innerWidth,
            panel:p?p.getBoundingClientRect().width:0,panelScroll:p?p.scrollWidth:0};
  });
  assert.ok(narrow.doc<=321&&narrow.body<=321&&narrow.panelScroll<=321,JSON.stringify(narrow));
  await cleanShot(page,'workout-320.png');
  await page.setViewportSize({width:393,height:850});
  let shapeSaved=false;
  for(let i=0;i<40;i++){const d=await api('/api/dashboard',null,a.token);if(d.profile.goal_type==='female_lean'){shapeSaved=true;break;}await new Promise(r=>setTimeout(r,100));}
  assert.equal(shapeSaved,true,'body shape must persist while the scene stays gym');
  checks.push('changing body shape keeps the scene and regenerates that scene version');
  // 账号入口：个人中心要能切换账号/退出登录
  await page.evaluate(()=>openAccountCenter());
  await page.waitForSelector('#account-tools-dialog[open]');
  const accountText=await page.locator('#account-tools-dialog').textContent();
  assert.match(accountText,/切换账号/);assert.match(accountText,/退出登录/);
  checks.push('account center exposes switch-account and logout');
  // 点“切换账号”必须是清会话+弹登录框，而不是整页刷新（用页面内标志证明没导航）
  await page.evaluate(()=>{window.__switchNoReload=1;});
  await page.getByRole('button',{name:'切换账号',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('auth-modal')?.classList.contains('show'),null,{timeout:10000});
  assert.equal(await page.evaluate(()=>window.__switchNoReload===1),true,'switch-account must not reload the page');
  assert.equal(await page.evaluate(()=>!localStorage.getItem('QINGSU_AUTH_TOKEN')),true);
  await page.evaluate(()=>closeAuthModal());
  checks.push('switch-account clears the session and opens login without a reload');
  await page.evaluate(()=>dmCleanup());
  assert.equal(await page.evaluate(()=>dmUi.record===null&&dmUi.draft===null),true);
  // An old response must not insert data into a later account.
  const scope=await page.evaluate(()=>{window.oldScope=dmScope();cmGeneration++;state.token='new-account';cm.pending={};cm.bubbles=[];dmAck('old',{id:999,from_id:1,to_id:2,body:'OLD'},window.oldScope);return cm.bubbles.length;});
  assert.equal(scope,0);checks.push('cleanup and late account response rejection');
  assert.deepEqual(pageErrors,[]);
  fs.writeFileSync(path.join(folder,'result.json'),JSON.stringify({checks,errors:pageErrors},null,2));
  console.log(JSON.stringify({folder,checks,errors:pageErrors},null,2));
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
