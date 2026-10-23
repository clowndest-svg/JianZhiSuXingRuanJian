// Real Chromium, real isolated API: catalogue, save/reload, reading safe area and motion.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=path.join(root,'_audit_sandbox','bubble-ui-'+process.pid);fs.mkdirSync(folder,{recursive:true});
const base='http://127.0.0.1:18013';
const child=spawn(process.env.QINGSU_TEST_PYTHON||'python',['-c',"import server,uvicorn;server.llm_chat=lambda *a,**k:None;uvicorn.run(server.app,host='127.0.0.1',port=18013,log_level='warning',ws='websockets-sansio')"],{cwd:root,env:{...process.env,QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')}});
const log=fs.createWriteStream(path.join(folder,'server.log'));child.stdout.pipe(log);child.stderr.pipe(log);
let browser;const checks=[],errors=[];
const api=async(url,body,token)=>{
 const build=Number(/versionCode\s+(\d+)/.exec(fs.readFileSync(path.join(root,'app/build.gradle'),'utf8'))[1]);
 const r=await fetch(base+url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Build':String(build),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
 const d=await r.json();assert.equal(r.status,200,JSON.stringify(d));return d;
};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const profile={password:'ThemeReview!123',age:30,height:170,weight_jin:160,target_weight_jin:140};
 const a=await api('/api/register',{...profile,username:'wardrobeowner'}),b=await api('/api/register',{...profile,username:'wardrobepeer'});
 await api('/api/chat/send',{to:b.id,text:'今天也要开心呀',request_id:'theme-short'},a.token);
 await api('/api/chat/send',{to:b.id,text:'长消息也要清楚可读。'.repeat(30),request_id:'theme-long'},a.token);
 await api('/api/chat/send',{to:a.id,text:'对方的气泡保持原样',request_id:'theme-peer'},b.token);
 browser=await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH?{executablePath:process.env.QINGSU_CHROME_PATH}:{}),args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
 const context=await browser.newContext({viewport:{width:393,height:850}});const page=await context.newPage();
 page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(({a})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',a.token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id:a.id,username:'wardrobeowner'}));},{a});
 await page.goto(base);await page.waitForFunction(()=>window.QSBubbles&&typeof openDM==='function');
 await page.evaluate(id=>openDM(id),b.id);await page.waitForSelector('#dm-input');
 const items=await page.evaluate(()=>QSBubbles.items);assert.equal(items.length,20);assert.equal(new Set(items.map(t=>t.shape)).size,20);
 await page.getByRole('button',{name:'气泡',exact:true}).click();await page.waitForSelector('.skin-card');
 assert.equal(await page.locator('.skin-card').count(),20);
 await page.locator('[data-skin-category="AI娘"]').click();assert.equal(await page.locator('.skin-card').count(),2);
 await page.locator('[data-pick-skin="skin-luna"]').click();assert.equal((await api('/api/community/stats',null,a.token)).bubble_theme,'green');
 await page.locator('#account-tools-dialog .td-close').click();assert.equal(await page.locator('#dm-input').isEditable(),true);
 checks.push('20 unique silhouettes; category filters; preview and cancel do not save or lock chat');
 await page.getByRole('button',{name:'气泡',exact:true}).click();
 await page.locator('[data-pick-skin="skin-ai"]').click();
 await page.route('**/api/community/profile',route=>route.fulfill({status:503,json:{detail:'fixture unavailable'}}));
 await page.locator('[data-skin-apply]').click();await page.waitForFunction(()=>!document.querySelector('[data-skin-apply]').disabled);
 assert.equal((await api('/api/community/stats',null,a.token)).bubble_theme,'green');
 assert.equal(await page.locator('#account-tools-dialog').evaluate(el=>el.open),true);
 await page.unroute('**/api/community/profile');await page.locator('#account-tools-dialog .td-close').click();
 checks.push('failed save keeps current theme and allows retry without closing preview');
 const shapes=new Set(),palettes=new Set();
 for(const t of items){
  await page.getByRole('button',{name:'气泡',exact:true}).click();
  await page.locator('[data-pick-skin="'+t.id+'"]').click();
  assert.equal(await page.locator('.skin-selected-name').textContent(),t.name);
  shapes.add(await page.locator('.skin-live .skin-frame path').first().getAttribute('d'));
  await page.locator('[data-skin-apply]').click();await page.waitForFunction(()=>!document.getElementById('account-tools-dialog')?.open);
  await page.waitForSelector('.cm-bubble.me[data-skin="'+t.id+'"]');
  const actual=(await api('/api/community/stats',null,a.token)).bubble_theme;assert.equal(actual,t.id);
  palettes.add(await page.locator('.cm-bubble.me[data-skin]').first().evaluate(el=>getComputedStyle(el).backgroundImage));
  assert.equal(await page.locator('.cm-bubble.them[data-skin]').count(),0);
  assert.equal(await page.locator('.cm-bubble.me[data-skin] .dm-status').count(),2);
  assert.equal(await page.locator('#dm-input').isEditable(),true);
 }
 assert.equal(shapes.size,20);assert.equal(palettes.size,20);checks.push('all 20 save through API, update actual short/long messages and keep peer bubbles/status unchanged');
 await page.reload();await page.waitForFunction(()=>window.QSBubbles&&typeof openDM==='function');await page.evaluate(id=>openDM(id),b.id);
 await page.waitForSelector('.cm-bubble.me[data-skin="skin-whale"]');checks.push('theme survives browser reload and API settings hydration');
 await page.screenshot({path:path.join(folder,'chat-whale-393.png')});
 for(const width of [320,393,1200]){
  await page.setViewportSize({width,height:850});await page.getByRole('button',{name:'气泡',exact:true}).click();
  const geometry=await page.evaluate(()=>{const d=document.querySelector('.skin-dialog').getBoundingClientRect(),b=document.querySelector('[data-skin-apply]').getBoundingClientRect(),g=document.querySelector('.skin-grid');return {w:d.width,x:d.x,right:d.right,bottom:b.bottom,view:innerHeight,scroll:g.scrollHeight>g.clientHeight,overflow:document.documentElement.scrollWidth>innerWidth};});
  assert.ok(geometry.x>=0&&geometry.right<=width+1&&!geometry.overflow,JSON.stringify(geometry));assert.ok(geometry.bottom<=geometry.view,JSON.stringify(geometry));assert.ok(geometry.scroll);
  assert.ok(await page.locator('.skin-card').first().evaluate(el=>el.getBoundingClientRect().height>=150),'cards must retain room for illustration and name');
  await page.locator('.skin-grid').evaluate(el=>el.scrollTop=el.scrollHeight);await page.locator('[data-pick-skin="skin-whale"]').click();
  await page.screenshot({path:path.join(folder,'wardrobe-'+width+'.png')});await page.locator('#account-tools-dialog .td-close').click();
 }
 checks.push('320/393/1200: dialog fits viewport, all cards scrollable, apply button visible');
 await page.setViewportSize({width:393,height:850});await page.getByRole('button',{name:'气泡',exact:true}).click();
 await page.locator('[data-pick-skin="skin-ai"]').click();
 await page.screenshot({path:path.join(folder,'wardrobe-ai-393.png')});
 await page.emulateMedia({reducedMotion:'reduce'});
 assert.equal(await page.locator('.skin-live .skin-art-main').evaluate(el=>getComputedStyle(el).animationName),'none');
 await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('[data-skin-motion]').uncheck();
 assert.equal(await page.locator('.skin-live .skin-art-main').evaluate(el=>getComputedStyle(el).animationName),'none');
 checks.push('system reduced motion and explicit motion switch stop ornament animation');
 await page.locator('.skin-legacy summary').click();await page.locator('[data-legacy-skin="blue"]').click();
 await page.waitForFunction(()=>!document.getElementById('account-tools-dialog')?.open);assert.equal((await api('/api/community/stats',null,a.token)).bubble_theme,'blue');
 assert.equal(await page.locator('.cm-bubble.me[data-skin]').count(),0);checks.push('all legacy colors remain available; classic clears decorative frame');
 // Real generated art requests, not empty PNG placeholders.
 for(const f of ['bubble-ai.png','bubble-moon.png']){const r=await fetch(base+'/'+f);assert.equal(r.status,200);assert.ok(Number(r.headers.get('content-length'))>100000);}
 assert.deepEqual(errors,[]);checks.push('original illustrations delivered and no page errors');
 const gallery=await context.newPage();await gallery.setViewportSize({width:1400,height:1100});
 await gallery.setContent('<html lang="zh-CN"><head><base href="'+base+'/"><link rel="stylesheet" href="bubble-themes.css"><style>body{margin:0;background:#eef2f4;font-family:"Microsoft YaHei",sans-serif;color:#273d48}main{padding:36px 44px}h1{font-size:30px;margin:0 0 8px}.note{font-size:15px;color:#72858d;margin:0 0 24px}.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:18px}.skin-card{padding-bottom:18px;border-radius:21px}.skin-stage{height:155px;padding:38px 24px 20px}.skin-sample{padding:25px 15px 20px;font-size:13px}.skin-stage .skin-art-main{width:46px;height:46px;top:-24px;left:-10px}.skin-stage .skin-art-main.skin-portrait{width:72px;height:72px;top:-45px;left:-22px}.skin-card-name{font-size:15px}.skin-card-kind{font-size:11px}.foot{margin-top:22px;font-size:13px;color:#7d8c96}</style></head><body><main><h1>轻塑 · 气泡图鉴</h1><p class="note">20 款原创装扮 / 轮廓、角饰与色彩各有不同</p><div class="grid"></div><p class="foot">AI 娘 · 动漫 · 科幻 · 浪漫 · 萌趣 · 自然 · 梦幻　｜　支持动态与静态切换</p></main></body></html>');
 await gallery.addScriptTag({url:base+'/bubble-themes.js'});
 await gallery.evaluate(()=>{document.querySelector('.grid').innerHTML=QSBubbles.items.map(t=>'<article class="skin-card">'+QSBubbles.preview(t.id,false)+'<strong class="skin-card-name">'+t.name+'</strong><span class="skin-card-kind">'+t.type+(t.motion?' · 动态':' · 静态')+'</span></article>').join('');});
 await gallery.waitForFunction(()=>Array.from(document.images).every(i=>i.complete));await gallery.waitForTimeout(800);
 await gallery.screenshot({path:path.join(folder,'all-20.png'),fullPage:true});
 const result={folder,checks,errors,theme_count:items.length};fs.writeFileSync(path.join(folder,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}finally{if(browser)await browser.close();if(child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}log.end();}
