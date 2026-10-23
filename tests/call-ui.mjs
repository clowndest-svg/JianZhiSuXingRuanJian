// Real two-browser voice call: local API + production coturn, forced TURN relay.
// Requires QINGSU_TURN_SECRET in the environment (read from the server, never printed).
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require('playwright');
const root=path.resolve(import.meta.dirname,'..');
const folder=path.join(root,'_audit_sandbox','call-ui-'+process.pid);
fs.mkdirSync(folder,{recursive:true});
const base='http://127.0.0.1:18008';
const build=Number(/versionCode\s+(\d+)/.exec(fs.readFileSync(path.join(root,'app/build.gradle'),'utf8'))[1]);
if(!process.env.QINGSU_TURN_SECRET)throw new Error('QINGSU_TURN_SECRET is required');
const child=spawn(process.env.QINGSU_TEST_PYTHON||'python',['-c',
 "import server,uvicorn;server.llm_chat=lambda *a,**k:None;server.web_search=lambda *a,**k:[];uvicorn.run(server.app,host='127.0.0.1',port=18008,log_level='warning',ws='websockets-sansio')"],
 {cwd:root,env:{...process.env,QINGSU_DB_DIR:path.join(folder,'db'),QINGSU_UPLOAD_DIR:path.join(folder,'uploads'),QINGSU_KEY_DIR:path.join(folder,'keys'),QINGSU_WEB_DIR:path.join(root,'app/src/main/assets')}});
const log=fs.createWriteStream(path.join(folder,'server.log'));child.stdout.pipe(log);child.stderr.pipe(log);
let browser;
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/health')).ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}
 const api=async(url,body,token)=>{const r=await fetch(base+url,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-App-Build':String(build),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});const d=await r.json();if(r.status!==200)throw new Error(url+' '+r.status+' '+JSON.stringify(d));return d;};
 const profile={password:'Call!12345',age:30,height:170,weight_jin:160,target_weight_jin:140};
 const a=await api('/api/register',{...profile,username:'callowner'}),b=await api('/api/register',{...profile,username:'callpartner'});
 await api('/api/community/users/'+b.id+'/follow',{on:true},a.token);
 await api('/api/community/users/'+a.id+'/follow',{on:true},b.token);
 browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
 const mk=async(user)=>{const context=await browser.newContext({viewport:{width:393,height:850},permissions:['microphone']});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(({token,id,name})=>{localStorage.setItem('QINGSU_AUTH_TOKEN',token);localStorage.setItem('QINGSU_AUTH_USER',JSON.stringify({id,username:name}));window.__QS_FORCE_RELAY__=true;window.__speakerCalls=[];window.AndroidBridge={playBeep(){},vibrate(){},startVoiceCallAudio(){},stopVoiceCallAudio(){},setVoiceCallSpeaker(v){window.__speakerCalls.push(v);}};},{token:user.token,id:user.id,name:user.username});
  await page.goto(base,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>typeof openDM==='function');
  await page.waitForFunction(()=>typeof wsOpen==='function'&&wsOpen(),null,{timeout:15000});
  return {page,errors};
 };
 const A=await mk(a),B=await mk(b);
 await A.page.evaluate(id=>openDM(id),b.id);await A.page.waitForSelector('#thread-call-btn');
 const checks=[];
 await A.page.locator('#thread-call-btn').click();
 await B.page.waitForSelector('#dm-call-layer:not([hidden])',{timeout:20000});
 assert.ok((await B.page.locator('.dm-call-btn-accept').count())===1);
 await B.page.screenshot({path:path.join(folder,'call-incoming.png')});
 checks.push('incoming call overlay reached the other browser');
 await B.page.locator('.dm-call-btn-accept').click();
 await A.page.waitForFunction(()=>dmCall.state==='active',{timeout:30000});
 await B.page.waitForFunction(()=>dmCall.state==='active',{timeout:30000});
 await A.page.screenshot({path:path.join(folder,'call-active.png')});
 checks.push('both ends reached active');
 if(await A.page.locator('#dm-call-speaker').count()!==1)throw new Error('speaker button missing on the call page');
 await A.page.locator('#dm-call-speaker').click();
 assert.equal(await A.page.evaluate(()=>dmCall.speaker),true);
 assert.equal(await A.page.evaluate(()=>window.__speakerCalls.at(-1)),true);
 assert.equal(await A.page.locator('#dm-call-speaker').getAttribute('aria-pressed'),'true');
 await A.page.screenshot({path:path.join(folder,'call-speaker.png')});
 checks.push('speaker button renders, toggles state and reaches the native bridge');
 if(await A.page.locator('.dm-call-down').count()!==1)throw new Error('call page minimize button missing');
 await A.page.locator('.dm-call-down').click();
 await A.page.waitForSelector('#dm-call-mini:not([hidden])');
 await A.page.screenshot({path:path.join(folder,'call-mini.png')});
 if(await A.page.locator('#dm-call-layer').isVisible())throw new Error('call page should hide when minimized');
 await A.page.locator('#dm-call-mini-main').click();
 await A.page.waitForSelector('#dm-call-layer:not([hidden])');
 checks.push('call page minimizes to a floating bar and restores');
 const stats=await A.page.evaluate(async()=>{
  const pc=dmCall.pc;if(!pc)return null;const rows=[];const all=[];const report=await pc.getStats();
  report.forEach(x=>all.push(x));
  const pairs=all.filter(x=>x.type==='candidate-pair'&&x.state==='succeeded');
  const local=all.find(x=>x.type==='local-candidate'&&pairs.some(p=>p.localCandidateId===x.id));
  const remote=all.find(x=>x.type==='remote-candidate'&&pairs.some(p=>p.remoteCandidateId===x.id));
  return {connection:pc.connectionState,pair:!!pairs.length,local:local&&local.candidateType,remote:remote&&remote.candidateType,audio:!!dmCall.audio,remoteTracks:!!(dmCall.audio&&dmCall.audio.srcObject&&dmCall.audio.srcObject.getAudioTracks().length)};
 });
 assert.equal(stats.pair,true,JSON.stringify(stats));
 assert.equal(stats.local,'relay',JSON.stringify(stats));
 assert.equal(stats.remote,'relay',JSON.stringify(stats));
 assert.equal(stats.remoteTracks,true,JSON.stringify(stats));
 checks.push('forced TURN relay candidate pair and remote audio track');
 await A.page.locator('#dm-call-mute').click();
 assert.equal(await A.page.evaluate(()=>dmCall.stream.getAudioTracks()[0].enabled),false);
 checks.push('mute disables the local track');
 await A.page.locator('.dm-call-btn-hang').click();
 await B.page.waitForFunction(()=>dmCall.state==='ended'||dmCall.state==='idle',{timeout:15000});
 checks.push('hangup reaches the other end');
 assert.deepEqual(A.errors,[]);assert.deepEqual(B.errors,[]);
 console.log(JSON.stringify({checks,stats}));
}finally{if(browser)await browser.close();child.kill();}
