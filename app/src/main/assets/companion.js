/* Installation, private summaries and explicitly shared activity goals. */
let installPrompt = null;
let currentPeriod = null;
window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); installPrompt = event;
    const b=document.getElementById('install-browser-app'); if(b)b.hidden=false;
});
window.addEventListener('appinstalled',()=>{installPrompt=null;callNativeToast('轻塑已添加到设备');});

function openInstallGuide(){
    if(inApp()){callNativeToast('你正在使用轻塑安卓客户端');return;}
    toolDialog('把轻塑放到桌面', `<p class="td-lead">手机和电脑都可以通过网页记录，数据随账号同步。</p>
      <div class="td-group"><button class="td-row" id="install-browser-app" ${installPrompt?'':'hidden'} onclick="installBrowserApp()">添加到设备</button></div>
      <p>苹果手机：在 Safari 打开本网站，点分享，再选「添加到主屏幕」。</p>
      <p>安卓或电脑：在浏览器菜单中寻找「安装应用」或「添加到主屏幕」。菜单没有出现时，可以先收藏网址。</p>
      <p class="td-note">断网后可以查看本机缓存并保存餐食、训练草稿；重新联网后请同步核对。浏览器通知是否可用取决于设备、浏览器和网络。</p>
      <p><a href="${escapeHtml(API_BASE)}/about">软件介绍与使用教程</a></p>`);
}
async function installBrowserApp(){
    if(!installPrompt)return;
    const pending=installPrompt;installPrompt=null;
    await pending.prompt();const choice=await pending.userChoice;
    callNativeToast(choice.outcome==='accepted'?'已提交安装请求':'可以随时从浏览器菜单添加');
}

async function openPeriodSummary(days=7){
    if(!state.token){openAuthModal();return;}
    const generation=sessionGeneration;
    try{
        const d=await getJson('/api/weekly/review?days='+days);
        if(generation!==sessionGeneration)return;
        currentPeriod=d;
        const trendValue=d.weight_trend.status==='ok'?d.weight_trend.change_jin+' 斤':'数据不足';
        toolDialog(days===7?'最近7天回顾':'最近30天回顾', `
          <div class="td-actions"><button class="td-btn-quiet" onclick="openPeriodSummary(7)">最近7天</button><button class="td-btn-quiet" onclick="openPeriodSummary(30)">最近30天</button></div>
          <p class="td-lead">${escapeHtml(d.start)} — ${escapeHtml(d.end)}</p>
          <dl class="period-stats"><div><dt>完整记录日</dt><dd>${d.full_record_days} 天</dd></div>
          <div><dt>训练完成日</dt><dd>${d.training_days} 天</dd></div>
          <div><dt>体重趋势</dt><dd>${escapeHtml(trendValue)}</dd></div>
          <div><dt>有称重日期</dt><dd>${d.weight_days} 天</dd></div></dl>
          <p class="td-note">${escapeHtml(d.weight_trend.text)}</p>
          ${d.coverage_note?`<p class="td-note">${escapeHtml(d.coverage_note)}</p>`:''}
          <p class="td-note">有餐食记录的 ${d.meal_days} 天，平均已记热量：${d.average_recorded_kcal==null?'暂无数据':d.average_recorded_kcal+' kcal（估算）'}。</p>
          <div class="td-group" aria-label="可执行建议">${d.feedback.map((f,i)=>`<div class="td-row"><span class="td-row-main"><span class="td-row-title">${i+1}. ${escapeHtml(f.text)}</span><span class="td-row-hint">依据：${escapeHtml(f.basis.label)} ${f.basis.value} ${escapeHtml(f.basis.unit)}（本周真实记录）</span></span></div>`).join('')}</div>
          <div class="period-table"><table><thead><tr><th>日期</th><th>记全</th><th>已记热量</th><th>训练分钟</th></tr></thead><tbody>${d.rows.map(r=>`<tr><td>${escapeHtml(r.date.slice(5))}</td><td>${r.full_record?'已记全':'未记全'}</td><td>${r.recorded_kcal==null?'未记录':r.recorded_kcal}</td><td>${r.workout_minutes==null?'未记录':r.workout_minutes}</td></tr>`).join('')}</tbody></table></div>
          <p class="td-note">未记录不代表零摄入或零运动；缺口按当前档案预算估算，只算有餐食记录的日子。补录和修正会影响结果，报告不用于诊断。</p>
          <div class="td-actions"><button class="td-btn" onclick="savePeriodImage()">生成回顾图片</button></div>`);
    }catch(e){callNativeToast(e.message);}
}
function savePeriodImage(){
    if(!currentPeriod)return;
    const d=currentPeriod,c=document.createElement('canvas');c.width=900;c.height=980;
    const x=c.getContext('2d');x.fillStyle='#f5faf6';x.fillRect(0,0,900,980);
    x.fillStyle='#16603c';x.font='bold 48px sans-serif';x.fillText('轻塑 · 我的'+d.days+'天回顾',56,100);
    x.fillStyle='#475569';x.font='28px sans-serif';x.fillText(d.start+' — '+d.end,56,160);
    const trendValue=d.weight_trend.status==='ok'?d.weight_trend.change_jin+' 斤':'数据不足';
    const average=d.average_recorded_kcal==null?'暂无数据':d.average_recorded_kcal+' kcal（估算）';
    const rows=[['完整记录日',d.full_record_days+' 天'],['训练完成日',d.training_days+' 天'],['体重趋势',trendValue],['有餐食记录',d.meal_days+' 天'],['平均已记热量',average]];
    rows.forEach((r,i)=>{x.fillStyle='#475569';x.font='28px sans-serif';x.fillText(r[0],56,255+i*96);x.fillStyle='#172b20';x.font='bold 36px sans-serif';x.fillText(r[1],480,255+i*96);});
    x.fillStyle='#64748b';x.font='24px sans-serif';x.fillText('未记录不代表零；缺口只算有餐食记录的日子。',56,840);x.fillText('热量为估算，不用于诊断。',56,880);
    const image=c.toDataURL('image/png');
    const nativeSave=inApp()&&window.AndroidBridge&&AndroidBridge.savePng;
    toolDialog('我的回顾图片',`<p class="td-note">图片包含你的记录，请确认后再分享。${nativeSave?'点击保存后选择文件位置。':'手机可长按图片保存；浏览器也可点击下载。'}</p><img id="period-export-image" style="width:100%;border-radius:16px" src="${image}" alt="我的${d.days}天记录回顾"><div class="td-actions">${nativeSave?'<button class="td-btn" onclick="AndroidBridge.savePng(document.getElementById(\'period-export-image\').src)">保存回顾图片</button>':`<a class="td-btn" href="${image}" download="轻塑-${d.end}-${d.days}天.png">下载图片</a>`}</div>`);
}

async function openSharedGoals(){
    if(!state.token){openAuthModal();return;}
    const generation=sessionGeneration;
    try{
        const d=await getJson('/api/goals');if(generation!==sessionGeneration)return;
        toolDialog('和朋友一起坚持',`<p class="td-lead">加入后，组内只展示昵称和达成天数。体重、饮食、照片与私信不会分享到这里。</p>
          <div class="td-actions"><button class="td-btn" onclick="openNewGoal()">创建共同目标</button><button class="td-btn-quiet" onclick="openJoinGoal()">输入邀请码</button></div>
          ${d.items.length?d.items.map(g=>`<article class="goal-card"><h3>${escapeHtml(g.title)}</h3><p>${escapeHtml(g.start_date)} — ${escapeHtml(g.end_date)} · ${g.kind==='workout'?'训练':'确认完整记录'} ${g.target} 天</p>
          ${g.members.map(m=>`<p>${escapeHtml(m.nickname||'轻塑用户')}${m.me?'（我）':''}<strong> ${m.days} / ${g.target} 天</strong></p>`).join('')}
          <button class="td-btn-quiet" onclick="leaveSharedGoal(${Number(g.id)},${g.owner})">${g.owner?'结束并删除此目标':'退出目标'}</button></article>`).join(''):'<p class="td-note">还没有共同目标。可以邀请朋友记录一周训练，也可以独自开始。</p>'}`);
    }catch(e){callNativeToast(e.message);}
}
function openNewGoal(){
    toolDialog('创建共同目标',`<label class="td-field">名称<input id="goal-title" maxlength="30" value="一起坚持训练"></label>
      <label class="td-field">目标类型<select id="goal-kind"><option value="workout">有训练记录的天数</option><option value="complete">确认完整记录的天数</option></select></label>
      <label class="td-field">周期<select id="goal-days"><option value="7">7天</option><option value="30">30天</option></select></label>
      <label class="td-field">期望达成天数<input id="goal-target" type="number" min="1" max="30" value="3"></label>
      <p class="td-note">每天多次训练只计1天。最多8人；邀请码仅在创建时显示，转发前请确认接收人。</p><button class="td-btn" onclick="createSharedGoal(this)">创建并获取邀请码</button>`);
}
async function createSharedGoal(button){
    button.disabled=true;
    try{
        const r=await postApi('/api/goals',{title:document.getElementById('goal-title').value,kind:document.getElementById('goal-kind').value,days:Number(document.getElementById('goal-days').value),target:Number(document.getElementById('goal-target').value)});
        toolDialog('目标已创建',`<p>把这段邀请码发给希望一起坚持的朋友：</p><input readonly aria-label="邀请码" value="${escapeHtml(r.invite)}" onclick="this.select()"><p class="td-note">邀请码到周期结束时失效。结束目标后所有成员都会退出。</p><button class="td-btn" onclick="openSharedGoals()">查看目标</button>`);
    }catch(e){callNativeToast(e.message);button.disabled=false;}
}
function openJoinGoal(){toolDialog('加入共同目标','<label class="td-field">邀请码<input id="goal-invite" maxlength="80" autocomplete="off"></label><p class="td-note">加入后，其他成员可以看到你的昵称与达成天数。</p><button class="td-btn" onclick="joinSharedGoal(this)">同意并加入</button>');}
async function joinSharedGoal(button){button.disabled=true;try{await postApi('/api/goals/join',{code:document.getElementById('goal-invite').value.trim()});await openSharedGoals();}catch(e){callNativeToast(e.message);button.disabled=false;}}
async function leaveSharedGoal(id,owner){if(!confirm(owner?'结束并删除这个共同目标？所有成员的个人原始记录都会保留。':'退出此目标？个人原始记录会保留。'))return;try{await postApi('/api/goals/'+id+'/leave',{});await openSharedGoals();}catch(e){callNativeToast(e.message);}}

window.addEventListener('DOMContentLoaded',()=>{
    if(isPublicScreen())return;
    const host=document.getElementById('account-tool-card');if(!host)return;
    const group=document.createElement('nav');group.setAttribute('aria-label','回顾与陪伴');
    group.innerHTML=[['📅','周报与月报','真实记录回顾，可生成图片','openPeriodSummary()'],['🤝','共同目标','和朋友分享坚持的天数','openSharedGoals()'],['🔔','网页消息提醒','查看当前设备的通知能力','openWebPushSettings()'],['📲','添加到桌面','苹果、安卓和电脑使用指引','openInstallGuide()']].map(([g,t,h,fn])=>`<button type="button" class="td-row" onclick="${fn}"><span class="td-glyph">${g}</span><span class="td-row-main"><span class="td-row-title">${t}</span><span class="td-row-hint">${h}</span></span><span class="td-chevron" aria-hidden="true">›</span></button>`).join('');
    host.appendChild(group);
    if(!inApp()&&'serviceWorker' in navigator){navigator.serviceWorker.addEventListener('message',e=>{if(e.data?.type==='open-messages')switchTab('messages');});navigator.serviceWorker.getRegistration().then(reg=>{if(!reg)return;reg.addEventListener('updatefound',()=>{const w=reg.installing;if(w)w.addEventListener('statechange',()=>{if(w.state==='installed'&&navigator.serviceWorker.controller){const p=document.createElement('p');p.className='field-hint';p.innerHTML='网页有新版本。<button type="button">刷新使用新版</button>';p.querySelector('button').onclick=()=>{navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});reg.waiting?.postMessage({type:'activate-update'});};host.prepend(p);}});});});}
    if(new URLSearchParams(location.search).get('open')==='messages')switchTab('messages');
});

async function openWebPushSettings(){
    if(!state.token){openAuthModal();return;}
    if(inApp()){toolDialog('消息提醒','<p>安卓客户端支持每日系统提醒；私信实时连接在应用打开时生效。</p><p>网页的后台消息提醒需要在支持通知的浏览器中单独开启，不会自动启用。</p><button class="td-btn" onclick="openReminderSettings()">设置每日提醒</button>');return;}
    if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){toolDialog('当前浏览器暂不支持','<p>可以在支持通知的浏览器中打开轻塑。苹果手机请先添加到主屏幕，再从桌面打开。</p>');return;}
    try{
        const d=await getJson('/api/push/config');
        const reg=await navigator.serviceWorker.ready;const sub=await reg.pushManager.getSubscription();
        toolDialog('网页消息提醒',`<p class="td-lead">${sub?'当前浏览器已有订阅':'当前浏览器尚未订阅'}；通知权限：${escapeHtml(Notification.permission)}。</p><p>开启后，新私信、评论回复或被 @ 时会收到通用提示。通知不包含聊天正文或身体数据。</p><p class="td-note">送达取决于浏览器推送服务、网络和系统设置；国内网络下可能无法订阅或延迟。</p>${!d.available?'<p>服务器推送通道尚未就绪。</p>':`<button class="td-btn" onclick="enableWebPush(this)">${sub?'绑定到当前账号':'开启消息提醒'}</button>`}${sub?'<button class="td-btn-quiet" onclick="disableWebPush(this)">关闭此浏览器提醒</button>':''}`);
    }catch(e){callNativeToast(e.message);}
}
async function enableWebPush(button){
    button.disabled=true;let fresh=null;const generation=sessionGeneration;
    try{
        const permission=await Notification.requestPermission();if(permission!=='granted')throw new Error('未获得通知权限，请在浏览器设置中调整');
        const d=await getJson('/api/push/config');const reg=await navigator.serviceWorker.ready;
        const key=Uint8Array.from(atob(d.public_key.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(d.public_key.length/4)*4,'=')),x=>x.charCodeAt(0));
        if(generation!==sessionGeneration)throw new Error('账号已变化，请重新打开提醒设置');
        fresh=await reg.pushManager.getSubscription()||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
        if(generation!==sessionGeneration)throw new Error('账号已变化，请重新打开提醒设置');
        await postApi('/api/push/subscribe',fresh.toJSON());callNativeToast('已订阅；实际送达仍受浏览器、网络与系统设置影响');await openWebPushSettings();
    }catch(e){callNativeToast('未完成开启：'+e.message);button.disabled=false;}
}
async function disableWebPush(button){button.disabled=true;try{const reg=await navigator.serviceWorker.ready;const sub=await reg.pushManager.getSubscription();if(sub){await postApi('/api/push/unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}await openWebPushSettings();}catch(e){callNativeToast(e.message);button.disabled=false;}}

const resetCompanionTools=resetAccountTools;
resetAccountTools=function(){currentPeriod=null;return resetCompanionTools();};
