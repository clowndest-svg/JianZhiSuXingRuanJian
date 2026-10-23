/* Per-viewer history tools. Reverse keyset pages, bounded rendering and visible-only receipts. */
(function(){
'use strict';
const MAX=120,pending=new Map(),hidden=new Set(),asrHidden=new Set(),newIds=new Set();
let detached=false,news=0,loading=false,epoch=0,observer,readTimer,readBusy=false,hostRef;
let refreshTimer,refreshDirty=false;
const visible=new Set();
const esc=s=>escapeHtml(String(s??''));
const current=id=>qsFindBubble(Number(id));
const alive=s=>dmScopeAlive(s)&&dmIsVisible();
const clock=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
function time(m){
 let raw=String(m?.created_at_iso||m?.created_at||'').trim();
 if(raw.length<19)return {label:'',iso:'',ms:NaN};
 if(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw))raw=raw.replace(' ','T')+'+08:00';
 const ms=raw?Date.parse(raw):NaN;if(!Number.isFinite(ms))return {label:'',iso:'',ms:NaN};
 return {label:clock.format(new Date(ms)),iso:new Date(ms).toISOString(),ms};
}
function rows(messages){const result=[];let previous;for(const m of messages){const t=time(m);if(t.label&&(!previous||t.label.slice(0,10)!==previous.label.slice(0,10)||t.ms-previous.ms>=300000||t.ms<previous.ms))result.push(['t'+m.id,null,'date',t.label]);result.push(['m'+m.id,m,'']);if(t.label)previous=t;}return result;}
function dateHTML(label){return '<time class="dm-date-separator" datetime="'+esc(label.replace(' ','T')+'+08:00')+'">'+esc(label)+'</time>';}
function timeHTML(m){const t=time(m);return t.label?'<time class="dm-exact-time" datetime="'+esc(t.iso)+'">'+esc(t.label)+'</time>':'';}
function menuTime(m){const t=time(m);return t.label?'<p class="dm-menu-time">发送于 '+esc(t.label)+'</p>':'';}
function mergeSnapshot(snapshot,startedAt){const last=Math.max(startedAt,0,...snapshot.map(m=>Number(m.id))),existing=new Map(cm.bubbles.map(m=>[Number(m.id),m]));const result=snapshot.map(m=>{const old=existing.get(Number(m.id));if(!old)return m;return {...m,...(Number(old.edit_version||0)>Number(m.edit_version||0)?{body:old.body,edited_at:old.edited_at,edit_version:old.edit_version}:{}),...(old.recalled_at?{recalled_at:old.recalled_at}:{}),read_at:old.read_at||m.read_at};});return result.concat(cm.bubbles.filter(m=>Number(m.id)>last)).sort((a,b)=>a.id-b.id);}
function scheduleRefresh(){refreshDirty=true;if(refreshTimer||document.hidden)return;const token=state.token;refreshTimer=setTimeout(()=>{refreshTimer=null;if(token!==state.token||document.hidden)return;refreshDirty=false;loadMessages();},500);}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&refreshDirty)scheduleRefresh();});
function bound(){cm.bubbles=cm.bubbles.filter(m=>!hidden.has(Number(m.id)));if(cm.bubbles.length>MAX)cm.bubbles=cm.bubbles.slice(-MAX);for(const m of cm.bubbles){const id=Number(m.id),p=pending.get(id);if(p&&!p.cancelled)m.asr_pending=true;if(asrHidden.has(id)){m.asr_text='';m.asr_hidden=true;m.asr_pending=false;}}}
function badge(){
 let b=document.getElementById('dm-latest');
 if(!dmIsVisible()||!detached&&!news){b?.remove();return;}
 if(!b){b=document.createElement('button');b.id='dm-latest';b.className='dm-latest';b.type='button';b.onclick=latest;document.getElementById('thread-bubbles')?.after(b);}
 b.textContent=news?news+' 条新消息 · 返回最新':'正在查看历史 · 返回最新';
}
function incoming(id){if(!detached)return false;if(!newIds.has(Number(id))){newIds.add(Number(id));news++;}badge();return true;}
function reset(){detached=false;news=0;newIds.clear();badge();}
async function latest(){epoch++;loading=false;readBusy=false;reset();dmUi.stickBottom=true;await refreshThread(true);}
function anchor(host){const top=host.getBoundingClientRect().top;const n=Array.from(host.querySelectorAll('[data-dm-key^="m"]')).find(n=>n.getBoundingClientRect().bottom>top+8);return n?{key:n.dataset.dmKey,y:n.getBoundingClientRect().top}:null;}
async function older(){
 if(loading||!cm.thread?.more||!cm.thread.cursor)return;
 const s=dmScope(),host=document.getElementById('thread-bubbles'),a=host&&anchor(host),version=++epoch;loading=true;readBusy=false;dmUi.stickBottom=false;
 try{
  const r=await getJson('/api/chat/messages?with_user='+s.threadId+'&limit=30&cursor='+cm.thread.cursor);
  if(!alive(s)||version!==epoch)return;
  const unique=new Map([...r.items,...cm.bubbles].map(m=>[Number(m.id),m]));let all=Array.from(unique.values()).sort((a,b)=>a.id-b.id);
  if(all.length>MAX){all=all.slice(0,MAX);detached=true;}
  cm.bubbles=all;cm.thread.more=!!r.more;cm.thread.cursor=r.next_cursor||0;paintThread();
  if(a){const n=host.querySelector('[data-dm-key="'+a.key+'"]');if(n)host.scrollTop+=n.getBoundingClientRect().top-a.y;}
  dmUi.stickBottom=false;badge();
 }catch(e){if(alive(s))callNativeToast('历史消息加载失败，向上滑动重试');}
 finally{if(version===epoch)loading=false;}
}
function onScroll(host){if(host.scrollTop<80&&host.scrollHeight>host.clientHeight+100)older();}
function foreground(){return document.visibilityState!=='hidden'&&!document.querySelector('dialog[open]')&&(!document.hasFocus||document.hasFocus());}
function isVisible(mid){const host=hostRef,n=host?.querySelector('[data-dm-key="m'+Number(mid)+'"]');if(!n)return false;const a=n.getBoundingClientRect(),b=host.getBoundingClientRect();return Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>=Math.min(24,a.height*.5);}
function scheduleRead(){clearTimeout(readTimer);if(foreground())readTimer=setTimeout(flushRead,350);}
async function flushRead(){
 if(readBusy||!dmIsVisible()||!foreground()||!cm.thread)return;
 const ids=Array.from(visible).filter(id=>{const m=current(id);return m&&Number(m.to_id)===Number(state.user?.id)&&!m.read_at&&isVisible(id);}).slice(0,120);
 if(!ids.length)return;
 const s=dmScope(),version=epoch;readBusy=true;
 try{
  const r=await postApi('/api/chat/read',{with_user:s.threadId,message_ids:ids});if(!alive(s)||version!==epoch)return;
  for(const id of r.message_ids||[]){const m=current(id);if(m)m.read_at=new Date().toISOString();}
  const conv=cm.convs.find(c=>Number(c.with?.id)===Number(s.threadId));if(conv)conv.unread=r.unread_with;
  if(cm.stats)cm.stats.dm_unread=r.unread_total;paintNavBadge();
 }catch(e){/* The next scroll, focus or incoming message retries; never mark on failure. */}
 finally{if(version===epoch)readBusy=false;}
}
function watch(host){
 hostRef=host;observer?.disconnect();visible.clear();
 if(typeof IntersectionObserver==='function'){
  observer=new IntersectionObserver(entries=>{for(const e of entries){const id=Number(e.target.dataset.dmKey?.slice(1));if(e.isIntersecting)visible.add(id);else visible.delete(id);}scheduleRead();},{root:host,threshold:[0,.1,.5,1]});
  host.querySelectorAll('[data-dm-key^="m"]').forEach(n=>observer.observe(n));
 }
 badge();
}
function rescan(){if(!dmIsVisible()||!hostRef)return;hostRef.querySelectorAll('[data-dm-key^="m"]').forEach(n=>visible.add(Number(n.dataset.dmKey.slice(1))));scheduleRead();}
window.addEventListener('focus',rescan);document.addEventListener('visibilitychange',rescan);document.addEventListener('close',rescan,true);
function cleanup(){epoch++;observer?.disconnect();clearTimeout(readTimer);clearTimeout(refreshTimer);refreshTimer=null;refreshDirty=false;visible.clear();hostRef=null;loading=false;readBusy=false;reset();hidden.clear();asrHidden.clear();document.getElementById('dm-latest')?.remove();for(const p of pending.values())p.cancelled=true;pending.clear();}
function event(data){
 if(data.t==='message_edited'){
  const m=current(data.message?.id);if(m&&Number(data.message.edit_version)>=Number(m.edit_version||0)){const {asr_pending,asr_failed}=m;Object.assign(m,data.message,{asr_pending,asr_failed});paintThread();}return true;
 }
 if(data.t==='message_hidden'){
  const ids=new Set((data.message_ids||[]).map(Number));for(const id of ids)hidden.add(id);cm.bubbles=cm.bubbles.filter(m=>!ids.has(Number(m.id)));if(ids.has(Number(dmUi.quote?.id)))dmUi.quote=null;
  if(cm.thread)paintThread();scheduleRefresh();return true;
 }
 if(data.t==='asr_hidden'){const id=Number(data.message_id),p=pending.get(id);if(p&&p.rid!==data.request_id)return true;asrHidden.add(id);const m=current(id);if(m){m.asr_hidden=true;m.asr_text='';m.asr_pending=false;paintThread();}if(p)p.cancelled=true;return true;}
 return false;
}
function menu(m,mine){const id=Number(m.id);return (mine&&(m.kind||'text')==='text'&&!m.recalled_at?'<button type="button" onclick="QSChatTools.edit('+id+')">重新编辑</button>':'')+'<button type="button" class="dm-delete-action" onclick="QSChatTools.remove('+id+')">删除记录</button>';}
function edit(id){
 qsHideMenu();const m=current(id);if(!m)return;const s=dmScope(),revision=Number(m.edit_version||0);
 toolDialog('重新编辑消息','<div class="td-body chat-edit"><p>修改后双方都会看到“已编辑”标记。</p><textarea id="dm-edit-text" maxlength="1000" aria-label="编辑消息内容">'+esc(m.body)+'</textarea><p id="dm-edit-error" role="status"></p><button class="td-btn" id="dm-edit-save" type="button">保存修改</button></div>');
 const input=document.getElementById('dm-edit-text'),button=document.getElementById('dm-edit-save'),dialog=input.closest('dialog');input.focus();
 button.onclick=async()=>{if(!alive(s))return;const text=input.value.trim();if(!text){document.getElementById('dm-edit-error').textContent='消息不能为空';return;}button.disabled=true;
  try{const r=await postApi('/api/chat/edit',{message_id:id,text,expected_version:revision});if(!alive(s))return;event({t:'message_edited',message:r.message});dialog.close();callNativeToast('消息已修改');}
  catch(e){if(dialog.isConnected)document.getElementById('dm-edit-error').textContent=String(e.message||'修改失败，请重试');}finally{button.disabled=false;}
 };
}
function remove(id){
 qsHideMenu();const s=dmScope();toolDialog('删除这条记录','<div class="td-body"><p>仅从你自己的聊天记录中删除，对方仍会保留。此操作无法恢复。</p><button type="button" class="td-btn dm-delete-action" id="dm-delete-confirm">删除记录</button></div>');
 const button=document.getElementById('dm-delete-confirm'),dialog=button.closest('dialog');button.onclick=async()=>{if(!alive(s))return;button.disabled=true;try{await postApi('/api/chat/delete',{message_ids:[id]});if(!alive(s))return;event({t:'message_hidden',message_ids:[id]});dialog.close();loadMessages();}catch(e){if(alive(s))callNativeToast(e.message||'删除失败');}finally{button.disabled=false;}};
}
function asrHTML(m){const id=Number(m.id);if(m.asr_pending)return '<p class="dm-asr pending" role="status">正在转文字… <button type="button" onclick="QSChatTools.cancelAsr('+id+')">取消</button></p>';if(m.asr_text&&!m.asr_hidden)return '<div class="dm-asr"><p>'+esc(m.asr_text)+'</p><button type="button" onclick="QSChatTools.cancelAsr('+id+')">收起转写</button></div>';if(m.asr_failed||m.asr_empty)return '<p class="dm-asr">'+(m.asr_failed?'转写失败':'没有听清内容')+' <button type="button" onclick="dmTranscribe('+id+')">重试</button></p>';return '';}
async function transcribe(id){
 qsHideMenu();id=Number(id);let m=current(id);if(!m||m.recalled_at||pending.has(id))return;
 const s=dmScope(),rid=crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random().toString(36).slice(2),p={rid,cancelled:false};pending.set(id,p);
 asrHidden.delete(id);m.asr_pending=true;m.asr_hidden=false;m.asr_failed=false;m.asr_empty=false;paintThread();
 try{const r=await postApi('/api/chat/asr',{message_id:id,request_id:rid},{timeout:90000,tag:'dm-asr-'+id});if(!alive(s)||p.cancelled)return;m=current(id);if(m&&!m.recalled_at){m.asr_text=String(r.text||'');m.asr_empty=!m.asr_text;m.asr_hidden=!!r.cancelled;}}
 catch(e){if(alive(s)&&!p.cancelled){m=current(id);if(m)m.asr_failed=true;}}
 finally{if(pending.get(id)===p)pending.delete(id);if(alive(s)&&!p.cancelled){m=current(id);if(m)m.asr_pending=false;paintThread();}}
}
async function cancelAsr(id){
 const s=dmScope(),m=current(id),p=pending.get(Number(id));if(!m)return;if(p)p.cancelled=true;
 const slot=typeof inflightByTag!=='undefined'&&inflightByTag.get('dm-asr-'+id);if(slot){slot.superseded=true;slot.ctl?.abort();}
 pending.delete(Number(id));asrHidden.add(Number(id));m.asr_text='';m.asr_pending=false;m.asr_failed=false;m.asr_empty=false;m.asr_hidden=true;paintThread();
 try{await postApi('/api/chat/asr/cancel',{message_id:Number(id),request_id:p?.rid||''});}catch(e){if(alive(s))callNativeToast('已在本页取消，保存未成功，请重新收起转写');}
}
function search(){
 if(!cm.thread)return;const s=dmScope();let sequence=0,cursor=0,query='';
 toolDialog('查找聊天记录','<div class="td-body chat-search"><form id="dm-history-form"><input id="dm-history-query" maxlength="100" type="search" placeholder="搜索当前聊天的文字" aria-label="搜索聊天记录"><button class="td-btn" type="submit">搜索</button></form><p>点击结果可查看前后消息。</p><div id="dm-history-results" aria-live="polite"></div><button type="button" id="dm-history-more" class="td-btn td-btn-quiet" hidden>更多结果</button></div>');
 const form=document.getElementById('dm-history-form'),input=document.getElementById('dm-history-query'),results=document.getElementById('dm-history-results'),more=document.getElementById('dm-history-more'),dialog=form.closest('dialog');
 async function fetchResults(append){const q=input.value.trim();if(!q)return;const seq=++sequence;more.disabled=true;if(!append){cursor=0;query=q;results.textContent='正在搜索…';}try{const r=await getJson('/api/chat/messages?with_user='+s.threadId+'&limit=30&cursor='+cursor+'&q='+encodeURIComponent(query));if(!alive(s)||seq!==sequence||!dialog.open)return;if(!append)results.textContent='';for(const m of [...r.items].reverse()){const b=document.createElement('button');b.type='button';b.className='chat-search-result';b.innerHTML='<small>'+esc(m.created_at)+(m.edited_at?' · 已编辑':'')+'</small><span>'+esc(m.body)+'</span>';b.onclick=()=>jump(m.id,s,dialog);results.append(b);}if(!results.children.length)results.textContent='没有找到匹配的消息';cursor=r.next_cursor||0;more.hidden=!r.more;}catch(e){if(seq===sequence)results.textContent='搜索失败，请重试';}finally{more.disabled=false;}}
 form.onsubmit=e=>{e.preventDefault();fetchResults(false);};more.onclick=()=>fetchResults(true);input.focus();
}
async function jump(id,s=dmScope(),dialog){
 try{const r=await getJson('/api/chat/context?message_id='+Number(id));if(!alive(s))return;epoch++;loading=false;readBusy=false;detached=!!r.has_newer;news=0;cm.bubbles=r.items;cm.thread.more=r.more;cm.thread.cursor=r.next_cursor;dmUi.stickBottom=false;dialog?.close();paintThread();const n=hostRef?.querySelector('[data-dm-key="m'+Number(id)+'"]');n?.scrollIntoView({block:'center'});n?.classList.add('dm-history-highlight');setTimeout(()=>n?.classList.remove('dm-history-highlight'),2200);badge();}catch(e){if(alive(s))callNativeToast('这条消息已删除或无法定位');}
}
window.QSChatTools={time,rows,dateHTML,timeHTML,menuTime,mergeSnapshot,scheduleRefresh,bound,watch,onScroll,older,incoming,reset,latest,cleanup,event,menu,edit,remove,asrHTML,transcribe,cancelAsr,search,jump,get detached(){return detached;},get windowVersion(){return epoch;}};
})();
