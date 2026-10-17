let localGuidanceRows=[];
/* Account tools, explicit sharing, offline drafts and record correction. */
const localDay = () => { const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const draftKey = () => 'QINGSU_DRAFTS_'+(state.user ? state.user.username : 'guest');
let pendingMeal=null;
logNaturalMeal=async function(){
    const text=document.getElementById('input-meal-text').value.trim();if(!text){callNativeToast('请填写实际吃的餐食');return;}
    if(!state.token){openAuthModal();return;}
    const slot={breakfast:'早餐',lunch:'午餐',dinner:'晚餐',snack:'加餐'}[state.selectedMealSlot]||'餐食';
    try{
        const result=await postApi('/api/food/preview',{food_name:text});pendingMeal={food_name:text,slot,estimate:result.cal};
        toolDialog('核对餐食与份量',`<div class="td-meal-head">
              <div class="td-meal-name">${escapeHtml(text)}</div>
              <div class="td-meal-why"><span class="td-chip">${Number(result.cal)} kcal</span>${escapeHtml(result.reason||'按名称估算，非称重结果')}</div>
            </div>
            <div class="td-group">
              <label class="td-field-row"><span class="td-field-label">本餐热量（kcal，可修正）</span><input id="meal-confirm-cal" type="number" min="0" max="10000" value="${Number(result.cal)}" inputmode="numeric"></label>
            </div>
            <div class="td-group-label">按包装称重换算（选填）</div>
            <div class="td-group">
              <label class="td-field-row"><span class="td-field-label">实际重量（g）</span><input id="meal-grams" type="number" min="0" step="0.1" inputmode="decimal" placeholder="例：260"></label>
              <label class="td-field-row"><span class="td-field-label">包装每 100g 热量（kcal）</span><input id="meal-per100" type="number" min="0" step="0.1" inputmode="decimal" placeholder="照包装背面抄"></label>
            </div>
            <p class="td-note">填了这两项就按重量换算覆盖上面那个数；手动热量只能算热量，推不出真实宏量。</p>
            <p id="meal-confirm-result" class="td-status" role="status"></p>
            <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="document.getElementById('account-tools-dialog').close()">先不记</button><button type="button" class="td-btn" onclick="confirmMealRecord()">确认并保存</button></div>`);
    }catch(e){
        // Preview is optional: preserve the user's original description as a draft.
        if(!e.status){const rows=readDrafts();const id=Date.now()+'-'+Math.random().toString(36).slice(2);rows.push({id,path:'/api/food/log',unsubmitted:true,body:{food_name:text,slot,request_id:id}});setDrafts(rows);callNativeToast('无法联网估算，原始餐食已存本机草稿，联网后可同步');}
        else callNativeToast(e.message);
    }
};
async function confirmMealRecord(){
    if(!pendingMeal)return;
    const body={food_name:pendingMeal.food_name,slot:pendingMeal.slot};
    const grams=document.getElementById('meal-grams').value;const per100=document.getElementById('meal-per100').value;
    const edited=Number(document.getElementById('meal-confirm-cal').value);
    if(grams!==''||per100!==''){
        if(grams===''||per100===''||!Number.isFinite(Number(grams))||!Number.isFinite(Number(per100))||Number(grams)<=0||Number(per100)<0){callNativeToast('重量和每100g热量需同时填写有效数字');return;}
        body.cal=Math.round(Number(grams)*Number(per100)/100);
    }else if(edited!==pendingMeal.estimate)body.cal=edited;
    try{const result=await postApi('/api/food/log',body);document.getElementById('account-tools-dialog').close();document.getElementById('input-meal-text').value='';pendingMeal=null;callNativeToast(result.msg);await syncRemoteDashboard();await syncRemoteCharts();}
    catch(e){document.getElementById('meal-confirm-result').textContent=e.message;}
}
const readDrafts = () => {try{const rows=JSON.parse(localStorage.getItem(draftKey())||'[]');return Array.isArray(rows)?rows.filter(x=>x&&typeof x.id==='string'&&['/api/food/log','/api/workout/complete'].includes(x.path)&&x.body&&typeof x.body==='object'):[];}catch(e){return [];}};
function setDrafts(rows){localStorage.setItem(draftKey(),JSON.stringify(rows));paintDrafts();}
function paintDrafts(){const el=document.getElementById('draft-status');if(!el)return;const n=readDrafts().length;el.textContent=n?String(n):'已同步';el.dataset.empty=n?'0':'1';el.setAttribute('aria-label',n+('笔待同步草稿'));}
const tdRow=(title,o)=>{const c=o||{};return `<div class="td-row"><div class="td-row-main"><div class="td-row-title">${escapeHtml(title)}</div>${c.hint?`<div class="td-row-hint">${escapeHtml(c.hint)}</div>`:''}</div>${c.control||''}</div>`;};
const tdSwitch=(id,on,label)=>`<input class="td-switch" id="${id}" type="checkbox" ${on?'checked':''} aria-label="${escapeHtml(label)}">`;
const tdToggleRow=(id,on,title,hint)=>tdRow(title,{hint,control:tdSwitch(id,on,title)});
const tdValueRow=(title,value,hint)=>tdRow(title,{hint,control:`<span class="td-row-value">${escapeHtml(String(value))}</span>`});
const TD_SOURCE_CN={direct:'本人填写',manual:'本人填写',legacy_estimate:'按名称粗估',nutrition_heuristic:'按关键词粗估',nutrition_kb_partial:'部分食材已匹配成分表'};
const tdSourceLabel=source=>TD_SOURCE_CN[source]||'估算来源未知';
function openDraftManager(){
    const rows=readDrafts();
    const body=rows.length?rows.map((d,i)=>`<div class="td-item"><div class="td-item-main"><div class="td-item-title">${escapeHtml(d.body.food_name||d.body.plan_name||'训练记录')}</div><div class="td-item-meta">${d.unsubmitted?'尚未提交，可编辑餐食原文':'保存结果尚不确定；请先同步核对，再到历史记录修正，避免重复记账'}</div>${d.unsubmitted?`<label class="td-field"><span class="td-field-label">餐食原文</span><textarea id="draft-edit-${i}" maxlength="500">${escapeHtml(d.body.food_name||'')}</textarea><button type="button" class="td-mini" onclick="editUnsubmittedDraft(${i})">保存本机修改</button>`:''}</div><div class="td-item-acts"><button type="button" class="td-mini" onclick="discardLocalDraft(${i})">移除本机草稿</button></div></div>`).join('')+'<div class="td-actions"><button type="button" class="td-btn" onclick="syncOfflineDrafts()">同步并核对</button></div>':'<div class="td-empty">没有待同步草稿，本机记录都已对上云端</div>';
    toolDialog('本机待同步草稿',`<p class="td-lead">断网时新记的餐食与训练先留在本机，联网后同步即可入账；草稿不会重复记账。</p>${body}`);
}
function editUnsubmittedDraft(index){
    const rows=readDrafts();const draft=rows[index];if(!draft?.unsubmitted)return;
    const text=document.getElementById('draft-edit-'+index).value.trim();if(!text){callNativeToast('请填写餐食原文');return;}
    draft.body.food_name=text;setDrafts(rows);callNativeToast('本机草稿已修改，尚未提交云端');
}
function discardLocalDraft(index){
    const id=readDrafts()[index]?.id;if(!id)return;
    if(!confirm('仅移除本机草稿，不会撤回可能已经成功的云端记录。确定继续？'))return;
    setDrafts(readDrafts().filter(x=>x.id!==id));openDraftManager();
}
function toolDialog(title,html){
    let d=document.getElementById('account-tools-dialog');if(d)d.remove();
    d=document.createElement('dialog');d.id='account-tools-dialog';d.className='tool-dialog';
    d.innerHTML=`<header><h2>${escapeHtml(title)}</h2><button type="button" class="td-close" aria-label="关闭" onclick="document.getElementById('account-tools-dialog').close()">✕</button></header><div class="td-body">${html}</div>`;
    document.body.appendChild(d);d.showModal();return d;
}
const TD_SCOPES=[['weight','体重与目标','当前体重、目标体重与本周期进度'],
 ['profile','年龄、身高和预算','只给看基础数值，不含每日流水'],
 ['meals','餐食与营养记录','每一条餐食名称与估算热量'],
 ['workout','训练记录','训练计划与完成情况'],
 ['photos','身材照片','最近一张已确认的身材记录']];
async function openSharingSettings(){
    if(!state.token){openAuthModal();return;}
    try{
        const s=await getJson('/api/share/settings');
        const expires=s.expires_at?new Date(s.expires_at*1000).toLocaleString('zh-CN',{hour12:false}):'尚未设置';
        toolDialog('分享与隐私',`<p class="td-lead">只有拿到完整链接（含密钥）的人能看到你勾选的内容。关掉总开关或更新密钥，旧链接立刻失效。</p>
          <div class="td-group-label">总开关</div>
          <div class="td-group">${tdToggleRow('share-enabled',s.enabled,'允许监督链接访问','关掉之后，已发出去的链接全部打不开')}</div>
          <div class="td-group-label">大屏显示什么</div>
          <div class="td-group">${TD_SCOPES.map(([k,n,h])=>tdToggleRow('scope-'+k,!!s.scope[k],n,h)).join('')}</div>
          <div class="td-group-label">有效期</div>
          <div class="td-group">${tdValueRow('当前到期时间',expires)}
            <div class="td-row"><div class="td-row-main"><div class="td-row-title">保存后有效天数</div><div class="td-row-hint">1 到 90 天，到期后需重新开启</div></div>
            <input id="share-days" type="number" min="1" max="90" value="7" aria-label="保存后有效天数"></div></div>
          <p id="share-result" class="td-status" role="status"></p>
          <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="saveSharing(true)">更新密钥</button><button type="button" class="td-btn" onclick="saveSharing(false)">保存权限与有效期</button></div>`);
    }catch(e){callNativeToast(e.message);}
}
async function saveSharing(rotate){
    const scope={};for(const [k] of TD_SCOPES)scope[k]=document.getElementById('scope-'+k).checked;
    const result=document.getElementById('share-result');
    try{const s=await postApi('/api/share/settings',{enabled:document.getElementById('share-enabled').checked,days:Number(document.getElementById('share-days').value),scope,rotate});state.publicUrl=s.public_url;updateUserUI(state.user.username);if(result){result.dataset.err='0';result.textContent=rotate?'已更新密钥，旧链接已失效；新链接请到「我的」里复制':'分享设置已保存';}}
    catch(e){if(result){result.dataset.err='1';result.textContent=e.message;}}
}
let recordKind='food';let recordOffset=0;let recordRows=[];
let lastBackfill={signature:'',id:''};
async function openRecordManager(kind='food',offset=0){
    if(!state.token){openAuthModal();return;}
    recordKind=kind;recordOffset=offset;
    try{
        const d=await getJson(`/api/records?kind=${kind}&offset=${offset}&limit=20`);recordRows=d.rows;
        const names={food:'餐食',weight:'体重',workout:'训练'};
        const titleOf=x=>kind==='food'?(x.food_name||'未命名餐食'):kind==='workout'?(x.plan_name||'训练'):(x.weight_jin+' 斤');
        const metaOf=x=>kind==='food'?`<span class="td-chip">${x.cal} kcal</span> ${escapeHtml(tdSourceLabel(x.source))}`
            :kind==='workout'?`<span class="td-chip">${x.duration_minutes} 分钟</span> ${x.cal_burned} kcal（估算）`:'';
        const tabs=Object.entries(names).map(([k,n])=>`<button type="button" role="tab" aria-selected="${k===kind}" onclick="openRecordManager('${k}')">${n}</button>`).join('')
            +'<button type="button" role="tab" aria-selected="false" onclick="openBackfill()">补录</button>';
        toolDialog('历史记录',`<nav class="td-seg" role="tablist" aria-label="记录类型">${tabs}</nav>
          ${d.rows.length?`<div class="td-items">${d.rows.map(x=>`<div class="td-item"><div class="td-item-main"><div class="td-item-title">${escapeHtml(x.log_date)} · ${escapeHtml(titleOf(x))}</div><div class="td-item-meta">${metaOf(x)}</div></div><div class="td-item-acts"><button type="button" class="td-mini" onclick="editHistoryRecord(${Number(x.id)})">修正</button><button type="button" class="td-mini" onclick="deleteHistoryRecord(${Number(x.id)})">删除</button></div></div>`).join('')}</div>`:`<div class="td-empty">还没有${names[kind]}记录，可以去「补录」加一条</div>`}
          <div class="td-pager"><button type="button" class="td-mini" ${offset===0?'disabled':''} onclick="openRecordManager('${kind}',${Math.max(0,offset-20)})">上一页</button><span class="td-pager-pos">${d.rows.length?`第 ${offset+1}–${offset+d.rows.length} 条`:'第 1 页'}</span><button type="button" class="td-mini" ${d.rows.length<20?'disabled':''} onclick="openRecordManager('${kind}',${offset+20})">下一页</button></div>`);
    }catch(e){callNativeToast(e.message);}
}
async function editHistoryRecord(id){
    const row=recordRows.find(x=>x.id===id);if(!row)return;
    const field=recordKind==='food'?'cal':recordKind==='weight'?'weight_jin':'duration_minutes';
    const label={cal:'餐食热量（kcal，修正后宏量未知）',weight_jin:'体重（斤）',duration_minutes:'训练时长（分钟）'}[field];
    const text=window.prompt(label,String(row[field]));if(text===null)return;
    if(!text.trim()||!Number.isFinite(Number(text))){callNativeToast('请填写数字');return;}
    const body={[field]:Number(text)};
    if(recordKind==='food'){const name=window.prompt('餐食名称',row.food_name);if(name===null)return;if(!name.trim()){callNativeToast('餐食名称不能为空');return;}body.food_name=name.trim();}
    try{await postApi(`/api/records/${recordKind}/${id}/update`,body);await syncRemoteDashboard();await syncRemoteCharts();await openRecordManager(recordKind,recordOffset);}
    catch(e){callNativeToast(e.message);}
}
async function deleteHistoryRecord(id){
    if(!window.confirm('删除此记录并重新计算统计？'))return;
    try{await postApi(`/api/records/${recordKind}/${id}/delete`,{});await syncRemoteDashboard();await syncRemoteCharts();await openRecordManager(recordKind,recordOffset);}
    catch(e){callNativeToast(e.message);}
}
function openBackfill(){
    toolDialog('补录记录',`<p class="td-lead">补的是历史某一天的真实记录，会重算那天的统计；填错可以到「历史记录」里修正。</p>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">类型</span><select id="backfill-kind"><option value="food">餐食</option><option value="weight">体重</option><option value="workout">训练</option></select></label>
        <label class="td-field-row"><span class="td-field-label">日期</span><input id="backfill-date" type="date" max="${localDay()}" value="${localDay()}"></label>
        <label class="td-field-row"><span class="td-field-label">餐食名称</span><input id="backfill-name" maxlength="500" placeholder="例：一碗牛肉面"></label>
        <label class="td-field-row"><span class="td-field-label">餐食热量（kcal）</span><input id="backfill-cal" type="number" min="0" max="10000" inputmode="numeric"><span class="td-field-hint">留空则按名称估算</span></label>
        <label class="td-field-row"><span class="td-field-label">体重（斤）</span><input id="backfill-weight" type="number" min="40" max="600" step="0.1" inputmode="decimal"></label>
        <label class="td-field-row"><span class="td-field-label">训练分钟</span><input id="backfill-duration" type="number" min="1" max="1440" value="20" inputmode="numeric"></label>
        <label class="td-field-row"><span class="td-field-label">训练估算消耗（kcal）</span><input id="backfill-burned" type="number" min="0" max="10000" value="0" inputmode="numeric"><span class="td-field-hint">不知道就留 0，按 220 kcal 兜底</span></label>
      </div>
      <p id="backfill-result" class="td-status" role="status"></p>
      <div class="td-actions"><button type="button" class="td-btn" onclick="saveBackfill()">保存补录</button></div>`);
}
async function saveBackfill(){
    const value=id=>document.getElementById('backfill-'+id).value;
    const body={kind:value('kind'),log_date:value('date'),food_name:value('name'),duration_minutes:Number(value('duration')),cal_burned:Number(value('burned')),request_id:Date.now()+'-'+Math.random().toString(36).slice(2)};
    if(value('cal')!=='')body.cal=Number(value('cal'));if(value('weight')!=='')body.weight_jin=Number(value('weight'));
    const signature=JSON.stringify({...body,request_id:undefined});
    if(lastBackfill.signature!==signature)lastBackfill={signature,id:body.request_id};
    body.request_id=lastBackfill.id;
    try{await postApi('/api/records/backfill',body);document.getElementById('backfill-result').textContent='补录已保存';await syncRemoteDashboard();await syncRemoteCharts();}
    catch(e){document.getElementById('backfill-result').textContent=e.message;}
}
async function confirmTodayComplete(){
    if(!window.confirm('确认今天的餐食与活动已记录完整？仍可继续修正，修正后需要重新确认。'))return;
    try{await postApi('/api/day/complete',{log_date:localDay(),complete:true});callNativeToast('今日已确认记录完整');await syncRemoteCharts();}
    catch(e){callNativeToast(e.message);}
}
async function syncOfflineDrafts(){
    if(!state.token){openAuthModal();return;}
    const owner=state.user.username;const generation=sessionGeneration;
    const rows=readDrafts();for(const draft of rows){
        if(generation!==sessionGeneration||state.user?.username!==owner)return;
        try{await rawPostApi(draft.path,draft.body);if(generation!==sessionGeneration)return;setDrafts(readDrafts().filter(x=>x.id!==draft.id));}
        catch(e){callNativeToast('草稿未同步：'+e.message);break;}
    }
    await syncRemoteDashboard();await syncRemoteCharts();paintDrafts();
}
function openReminderSettings(){
    if(!inApp()||!AndroidBridge.reminderStatus){callNativeToast('系统后台提醒仅在Android客户端提供；网页显示应用内提醒');return;}
    const status=JSON.parse(AndroidBridge.reminderStatus());
    toolDialog('每日提醒',`<p class="td-lead">系统会在所选时间附近提醒一次；厂商省电策略可能延迟，请允许通知。锁屏通知里不包含任何身体数据。</p>
      <div class="td-group">${tdToggleRow('reminder-enabled',status.enabled,'开启每日提醒','每天最多提醒一次，同日不重复')}
        <label class="td-field-row"><span class="td-field-label">提醒时间</span><input id="reminder-time" type="time" value="${String(status.hour).padStart(2,'0')}:${String(status.minute).padStart(2,'0')}"></label></div>
      <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="openSystemNotifSettings()">通知权限设置</button><button type="button" class="td-btn" onclick="saveReminderSettings()">保存</button></div>`);
}
function saveReminderSettings(){const [hour,minute]=document.getElementById('reminder-time').value.split(':').map(Number);if(AndroidBridge.configureReminder(document.getElementById('reminder-enabled').checked,hour,minute)){document.getElementById('account-tools-dialog').close();callNativeToast('提醒安排已保存');}}
function handleNativeBack(){
    const d=document.querySelector('dialog[open]');if(d){d.close();return true;}
    if(document.querySelector('#exercise-detail-modal.show')){closeExerciseDetail();return true;}
    const overlays=[...document.querySelectorAll('.modal-overlay.show')];if(overlays.length){overlays[overlays.length-1].classList.remove('show');return true;}
    return false;
}
const accountPostApi=postApi;
postApi=function(path,body,opts){
    const record=path==='/api/food/log'||path==='/api/workout/complete';
    const owner=state.user?.username;const generation=sessionGeneration;
    return accountPostApi(path,body,opts).catch(error=>{
        if(record && owner && generation===sessionGeneration && state.user?.username===owner && !error.status && (error.name==='TypeError'||error.name==='AbortError'||/fetch|network|网络/i.test(error.message))){
            const rows=readDrafts();if(!rows.some(x=>x.id===body.request_id)){rows.push({id:body.request_id,path,body});setDrafts(rows);}
            error.message='已保存在本机待同步草稿；尚未确认云端保存';
        }
        throw error;
    });
};
function restoreOfflineDashboard(error){
    if(!state.user)return;
    try{
        const cached=JSON.parse(localStorage.getItem('QINGSU_LAST_'+state.user.username)||'null');
        if(cached){accountApply(cached.data);state.dashboardLoaded=false;}
        let el=document.getElementById('sync-offline-banner');
        if(!el){el=document.createElement('p');el.id='sync-offline-banner';el.setAttribute('role','status');document.getElementById('panel-dashboard').prepend(el);}
        el.textContent=cached?'同步失败，以下是 '+new Date(cached.saved_at).toLocaleString()+' 的历史数据；新记录可保存草稿':'无法同步：'+error.message;
    }catch(e){callNativeToast('网络不可用，无法读取历史缓存');}
}
const accountLogout=logoutUser;
logoutUser=async function(){localStorage.removeItem(draftKey());localStorage.removeItem('QINGSU_LAST_'+(state.user?.username||'guest'));return accountLogout();};
const accountApply=applyDashboardData;
applyDashboardData=function(data){
    if(isPublicScreen()){renderPublicView(data);return;}
    accountApply(data);
    const foodNote=document.getElementById('today-meal-diary-list');if(foodNote&&data.today_meals?.some(x=>['direct','manual','legacy_estimate','nutrition_heuristic','nutrition_kb_partial'].includes(x.source))){const note=document.createElement('p');note.className='field-hint';note.textContent='部分餐食宏量未知；图表仅汇总已匹配食材的估算，不代表完整营养摄入。';foodNote.appendChild(note);}
    const offline=document.getElementById('sync-offline-banner');if(offline)offline.remove();
    if(!isPublicScreen()&&state.user){try{localStorage.setItem('QINGSU_LAST_'+state.user.username,JSON.stringify({saved_at:new Date().toISOString(),data}));}catch(e){}paintDrafts();}
};
function renderPublicView(data){
    document.body.classList.add('public-readonly');
    let host=document.getElementById('public-view');
    if(!host){host=document.createElement('main');host.id='public-view';document.body.appendChild(host);}
    const scope=data.share_scope||{};
    const rows=[];
    if(scope.weight){rows.push(['当前体重',data.current_weight_jin==null?'未记录':data.current_weight_jin+' 斤']);rows.push(['目标体重',data.profile?.target_weight_jin==null?'未设置':data.profile.target_weight_jin+' 斤']);}
    if(scope.workout)rows.push(['今天训练',data.today_workout_done?'已记录':'尚未记录']);
    if(scope.meals)rows.push(['已记摄入',data.today_consumed+' kcal（估算）']);
    if(scope.profile){rows.push(['身高',data.profile.height+' cm']);rows.push(['年龄',data.profile.age+' 岁']);}
    host.innerHTML=`<header><h1><img class="public-brand" src="app-icon.png" alt="轻塑" width="40" height="40">轻塑 · ${escapeHtml(data.user.nickname||data.user.username)}的监督页</h1><p>以下只显示本人选择分享的字段。无需登录，不能在此修改记录。</p></header><section class="card"><dl>${rows.map(([k,v])=>`<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('')}</dl>${scope.meals?'<h2>今日已记餐食</h2><ul>'+data.today_meals.map(x=>`<li>${escapeHtml(x.food_name)} · ${x.cal} kcal</li>`).join('')+'</ul>':'<p>本人未分享餐食详情</p>'}${scope.photos&&data.latest_cycle?.photo_url?`<img class="shared-photo" alt="本人授权分享的身材记录" src="${escapeHtml(API_BASE+data.latest_cycle.photo_url)}">`:''}</section><section class="card"><p id="public-refresh-stamp" role="status">正在刷新</p><button onclick="refreshPublicNow()">立即刷新</button><p id="pub-cheer-count">收到 ${Number(data.cheer_total||0)} 枚打气</p><button onclick="sendCheerSticker('稳步减脂')">送一枚打气</button></section>`;
    state.publicNickname=data.user.nickname;state.cheerTotal=data.cheer_total||0;
}
window.addEventListener('DOMContentLoaded',()=>{
    fetch('guidance.json').then(r=>r.json()).then(rows=>{localGuidanceRows=rows;}).catch(()=>{});
    if(isPublicScreen())document.body.classList.add('public-readonly');
    else {
        const host=document.createElement('section');host.id='account-tool-card';host.className='card account-tools';
        host.innerHTML=`<h3>我的记录与设置</h3><nav>
        ${[['📋','历史与补录','查看和修正每一条记录','openRecordManager()'],
           ['🔗','分享与隐私','控制监督大屏显示什么、多久过期','openSharingSettings()'],
           ['⏰','每日提醒','设置提醒时间','openReminderSettings()'],
           ['✅','确认今日完整','把今天标为完整日参与统计','confirmTodayComplete()'],
           ['🗑️','删除当前身材照','只删照片，历史周期数字保留','deleteLatestPhoto()']]
          .map(([g,t,h,fn])=>`<button type="button" class="td-row" onclick="${fn}"><span class="td-glyph">${g}</span><span class="td-row-main"><span class="td-row-title">${t}</span><span class="td-row-hint">${h}</span></span><span class="td-chevron" aria-hidden="true"></span></button>`).join('')}
        <button type="button" class="td-row" onclick="openDraftManager()"><span class="td-glyph">📥</span><span class="td-row-main"><span class="td-row-title">本机待同步草稿</span><span class="td-row-hint">断网时记的东西在这里</span></span><span id="draft-status" class="td-badge" role="status"></span><span class="td-chevron" aria-hidden="true"></span></button>
        <button type="button" class="td-row" onclick="syncOfflineDrafts()"><span class="td-glyph">↻</span><span class="td-row-main"><span class="td-row-title">同步离线草稿</span><span class="td-row-hint">逐条核对后再上传，不会重复记账</span></span><span class="td-chevron" aria-hidden="true"></span></button>
      </nav>
      <div class="td-foot"><p class="field-hint">热量是估算；只有确认完整的日期才用于完整日统计。</p></div>`;
        document.getElementById('panel-dashboard').prepend(host);paintDrafts();
    }
    if(!inApp()&&'serviceWorker' in navigator&&location.protocol==='https:'&&API_BASE===location.origin)navigator.serviceWorker.register('/sw.js').catch(()=>{});
});
window.addEventListener('offline',()=>callNativeToast('当前离线；新的餐食和训练可保存在本机草稿，联网后点击同步'));
window.addEventListener('online',()=>{paintDrafts();callNativeToast('网络已恢复，可同步离线草稿');});

async function deleteLatestPhoto(){
    if(!state.token){openAuthModal();return;}
    if(!confirm('删除当前照片及其历史周期引用？加密备份按保留期轮换。'))return;
    try{const r=await postApi('/api/photo/delete',{});callNativeToast(r.msg);await syncRemoteDashboard();}catch(e){callNativeToast(e.message);}
}
function resetAccountTools(){
    pendingMeal=null;recordRows=[];recordOffset=0;lastBackfill={signature:'',id:''};
    const dialog=document.getElementById('account-tools-dialog');if(dialog)dialog.remove();
}
