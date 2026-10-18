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
            <div class="td-actions td-ai-row"><button type="button" class="td-btn-quiet" id="meal-ai-btn" onclick="estimateMealByAi()">让服务器模型估一下</button></div>
            <p id="meal-ai-result" class="td-status" role="status"></p>
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
/* 在线模型估热量。没配置时按钮上就写着没配置，不点出一个"看起来像答案"的数。 */
async function estimateMealByAi(){
    const out=document.getElementById('meal-ai-result');
    const btn=document.getElementById('meal-ai-btn');
    const grams=document.getElementById('meal-grams').value;
    if(out){out.dataset.err='0';out.textContent='在算，稍一下…';}
    let r=null;
    try{
        r=await postApi('/api/food/estimate',{food_name:(pendingMeal&&pendingMeal.food_name)||document.getElementById('input-meal-text').value.trim(),grams:grams?Number(grams):null});
    }catch(e){ if(out){out.dataset.err='1';out.textContent='估算请求没成功：'+((e&&e.message)||'未知原因');} return; }
    if(!r||!r.ok){
        if(out){out.dataset.err='1';out.textContent=(r&&r.why)||'在线模型没给结果';}
        if(btn&&r&&r.status&&!r.status.ok)btn.textContent='模型通道不可用';
        return;
    }
    const cal=document.getElementById('meal-confirm-cal');
    if(cal)cal.value=String(r.cal);
    const src=(r.status&&r.status.source)||'模型';
    if(out){out.textContent='按 '+r.grams+' g 估到 '+r.cal+' kcal（'+(r.basis||'依据未给')+'，来源：'
        +src+'）——已填进上面那格，不对就直接改。';out.dataset.err='0';}
}
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
    document.body.appendChild(d);
    // showModal 失败时（已有别的模态在场）必须退到 show()，绝不能留下一个
    // "在文档流里但关不掉"的裸 dialog——那正是机主说的"固定在那上面动都动不了"
    try{d.showModal();}catch(e){try{d.show();}catch(e2){d.remove();}}
    return d;
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
    try{const s=await postApi('/api/share/settings',{enabled:document.getElementById('share-enabled').checked,days:Number(document.getElementById('share-days').value),scope,rotate});state.publicUrl=s.public_url;updateUserUI(displayName(state.user));if(result){result.dataset.err='0';result.textContent=rotate?'已更新密钥，旧链接已失效；新链接请到「我的」里复制':'分享设置已保存';}
        const dlg=document.getElementById('account-tools-dialog');if(dlg&&dlg.open)setTimeout(()=>dlg.close(),700);}
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
           ['👤','个人中心','头像、改密码、邮箱找回、城市与忌口','openAccountCenter()'],
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
    accountCache=null;
}

// ================ 个人中心：头像 / 改密 / 邮箱绑定与找回 / 城市与忌口 ================
// 这里的标签名必须与 server.py 的 AVOID_TAGS 逐条一致（判据会核对）。漂一条的后果是
// "用户勾了不吃辣、服务端存了个没人认识的字符串"，界面还提示保存成功——最难查的那种。
const AVOID_TAGS=['no_spicy','no_seafood','no_beef','no_pork','no_dairy','vegetarian','less_oil'];
const AVOID_CN={
    no_spicy:['不吃辣','麻酱、红油、湘菜、火锅这类往后排'],
    no_seafood:['海鲜过敏','虾、鱼、贝、海带紫菜都算'],
    no_beef:['不吃牛肉','含肥牛、牛腱、牛肉汤底'],
    no_pork:['不吃猪肉','含五花、排骨、香肠培根'],
    no_dairy:['不喝奶制品','牛奶、酸奶、奶酪'],
    vegetarian:['素食优先','所有肉禽海鲜都往后排'],
    less_oil:['只要少油','按油量排序，不排除菜名']
};
let accountCache=null;
function accountData(){return accountCache;}

function tdStatus(id,msg,isErr){
    const el=document.getElementById(id);if(!el)return;
    el.textContent=msg;
    if(isErr)el.setAttribute('data-err','1');else el.removeAttribute('data-err');
}

async function refreshAccount(){
    if(!state.token){accountCache=null;paintAccountBadge();return null;}
    try{
        accountCache=await getJson('/api/account');
        // 昵称可能在别的入口改过，或这是旧版本存下的会话：顶栏名字要跟着这次回读刷新，
        // 不能一直停在登录那一刻读到的值。
        if(accountCache&&accountCache.user){
            state.user=Object.assign({},state.user,accountCache.user);
            updateUserUI(displayName(state.user));
        }
        paintAccountBadge();
        // 忌口与城市变了，外卖点单顺序和食谱冲突标注必须跟着重画；
        // 不重画的话"保存成功"和屏幕上看到的推荐会对不上
        if(typeof renderTakeoutAdvisor==='function')renderTakeoutAdvisor();
        if(typeof renderRecipePlan==='function'&&state.selectedPlan)renderRecipePlan(state.selectedPlan);
    }catch(e){
        // 拉不到就沿用上一次的缓存，但要让人看见它没刷新：
        // 静默用旧值会让人以为"改了没生效"，实际是这条请求失败了
        if(!accountCache)callNativeToast('个人中心没读到：'+(e.message||'请重新登录'));
    }
    return accountCache;
}

/** 顶栏圆点：有头像放头像，没头像用昵称首字做字母章，一个字符都没有才落回"轻"。
    用 Array.from 而不是 [0]：昵称可能以 emoji 开头，直接按下标取会切出半个码元变成乱码。 */
function paintAccountBadge(){
    const host=document.getElementById('header-avatar-slot');
    const u=(accountCache&&accountCache.user)||state.user||{};
    const who={name:String(u.nickname||u.username||'').trim(),avatar:accountCache&&accountCache.avatar_url};
    if(host)host.innerHTML=cmAvatarInner(who);
    // 底部导航与桌面顶栏里那颗"我的"用的是同一张脸，三处必须同时换，
    // 不然改了头像之后只有顶栏变了、下面还是旧字母。
    ["nav-me-avatar","dnav-me-avatar"].forEach(id=>{
        const el=document.getElementById(id);
        if(el)el.innerHTML=cmAvatarInner(who);
    });
    const slot=document.getElementById('cm-compose-avatar');
    if(slot)slot.innerHTML=cmAvatarInner(who);
}

async function openAccountCenter(){
    if(!state.token){openAuthModal();return;}
    const a=await refreshAccount();
    if(!a){callNativeToast('个人中心没打开：请先登录');return;}
    const source=a.city_source==='gps'?'按定位就近认的':(a.city_source==='manual'?'你手填的':'来源未记');
    const cityLine=a.city?`${a.city}（${source}）`:'还没设置';
    // 服务端那句 why 本身已经写了"邮件通道未接入：…"，这里再拼一次前缀就成了结巴
    const mailLine=a.mail==='up'?'邮件通道已接入，可以绑定邮箱找回密码'
                                 :(a.mail_why||'邮件通道未接入');
    toolDialog('个人中心',`
      <p class="td-lead">头像、密码、邮箱找回、所在城市与忌口都在这。忌口会真的改变外卖与食谱的推荐顺序；城市是按坐标就近认的粗匹配，不对就手改。</p>
      <div class="td-group-label">头像</div>
      <div class="td-group">
        <div class="td-avatar-row">
          ${a.avatar_url?`<img class="td-avatar" src="${escapeHtml(API_BASE+a.avatar_url)}" alt="当前头像">`:'<span class="td-avatar td-avatar-empty">还没头像</span>'}
          <label class="td-field-row"><span class="td-field-label">选一张图（JPEG / PNG / WebP，4MB 内）</span><input type="file" id="avatar-file" accept="image/*"></label>
        </div>
        <div class="td-actions"><button type="button" class="td-btn" onclick="uploadAvatar()">上传头像</button></div>
        <p id="avatar-status" class="td-status" role="status"></p>
        <p class="td-note">上传前会去掉照片里的位置等隐藏信息，并压到 512 像素。</p>
      </div>
      <div class="td-group-label">城市与定位</div>
      <div class="td-group">
        ${tdValueRow('当前城市',cityLine,a.cuisines&&a.cuisines.length?'当地常见口味：'+a.cuisines.join('、'):'这个城市不在内置菜系表里，推荐只按忌口过滤')}
        <label class="td-field-row"><span class="td-field-label">手填城市</span><input id="city-input" maxlength="40" placeholder="例：成都" value="${escapeHtml(a.city||'')}"></label>
        <div class="td-actions">
          <button type="button" class="td-btn-quiet" onclick="useMyLocation()">用浏览器定位</button>
          <button type="button" class="td-btn" onclick="saveCityManual()">保存手填城市</button>
        </div>
        <p id="city-status" class="td-status" role="status">${a.loc_updated_at?'上次定位：'+escapeHtml(a.loc_updated_at):'还没有定位记录'}</p>
      </div>
      <div class="td-group-label">忌口（影响外卖与食谱推荐）</div>
      <div class="td-group">${AVOID_TAGS.map(k=>tdToggleRow('avoid-'+k,(a.avoid_tags||[]).indexOf(k)>=0,AVOID_CN[k][0],AVOID_CN[k][1])).join('')}</div>
      <div class="td-actions"><button type="button" class="td-btn" onclick="saveAvoidTags()">保存忌口</button></div>
      <p id="avoid-status" class="td-status" role="status"></p>
      <div class="td-group-label">邮箱与找回密码</div>
      <div class="td-group">
        ${tdValueRow('已绑邮箱',a.email_bound?a.email_masked+(a.email_verified?'（已验证）':'（未验证）'):'未绑定')}
        <label class="td-field-row"><span class="td-field-label">邮箱</span><input id="bind-email" type="email" maxlength="200" placeholder="用于找回密码"></label>
        <label class="td-field-row"><span class="td-field-label">验证码</span><input id="bind-code" inputmode="numeric" maxlength="6" placeholder="十分钟内有效"></label>
        <div class="td-actions">
          <button type="button" class="td-btn-quiet" onclick="sendBindCode()">发验证码</button>
          <button type="button" class="td-btn" onclick="verifyBindCode()">绑定并验证</button>
        </div>
        <p id="email-status" class="td-status" role="status" ${a.mail==='up'?'':'data-err="1"'}>${escapeHtml(mailLine)}</p>
      </div>
      <div class="td-group-label">修改密码</div>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">原密码</span><input id="pw-old" type="password" maxlength="200" autocomplete="current-password"></label>
        <label class="td-field-row"><span class="td-field-label">新密码（至少 8 位）</span><input id="pw-new" type="password" maxlength="200" autocomplete="new-password"></label>
        <label class="td-field-row"><span class="td-field-label">再输一遍新密码</span><input id="pw-new2" type="password" maxlength="200" autocomplete="new-password"></label>
        <div class="td-actions"><button type="button" class="td-btn" onclick="changePassword()">修改密码</button></div>
        <p id="pw-status" class="td-status" role="status"></p>
        <p class="td-note">改成功后其他设备会掉线需要重新登录，这台机器不受影响。</p>
      </div>
      <div class="td-group-label">去过的城市</div>
      <div class="td-group">${(a.cities_seen||[]).length
        ?(a.cities_seen||[]).map(x=>tdValueRow(x.city,'首次 '+String(x.first_seen).slice(0,10)+' · 最近 '+String(x.last_seen).slice(0,10))).join('')
        :'<p class="td-note">还没有第二个城市。出差或旅行时定位到别处，这里会多一行——换城市最容易打乱点单，回来能对照看。</p>'}</div>
    `);
}

async function uploadAvatar(){
    const input=document.getElementById('avatar-file');
    const file=input&&input.files&&input.files[0];
    if(!file){tdStatus('avatar-status','先选一张图',true);return;}
    if(file.size>4*1024*1024){tdStatus('avatar-status','这张图超过 4MB，换小一点的',true);return;}
    const fd=new FormData();fd.append('photo',file);
    tdStatus('avatar-status','正在上传…');
    try{
        const r=await postApi('/api/account/avatar',fd);
        tdStatus('avatar-status',r.msg||'头像已更新');
        await refreshAccount();
        const img=document.querySelector('.td-avatar');
        if(img&&accountCache&&accountCache.avatar_url)img.src=API_BASE+accountCache.avatar_url;
    }catch(e){tdStatus('avatar-status',e.message||'头像上传失败',true);}
}

function useMyLocation(){
    if(!navigator.geolocation){tdStatus('city-status','这个浏览器没有定位接口，请手填城市',true);return;}
    tdStatus('city-status','正在请求定位…（浏览器或系统会先问你是否允许）');
    navigator.geolocation.getCurrentPosition(async pos=>{
        const p=pos&&pos.coords||{};
        try{
            const r=await postApi('/api/account/location',{lat:Number(p.latitude),lng:Number(p.longitude),accuracy:p.accuracy==null?null:Number(p.accuracy)});
            tdStatus('city-status',r.msg);
            await refreshAccount();
            const box=document.getElementById('city-input');
            if(box&&r.city)box.value=r.city;
        }catch(e){tdStatus('city-status',e.message||'定位结果没存上',true);}
    },err=>{
        const why=err&&err.code===1?'你拒绝了定位授权'
                 :(err&&err.code===3?'定位超时，信号可能不好':'当前拿不到位置');
        tdStatus('city-status',why+'；可以手填城市，或到系统设置里给浏览器/本应用打开定位权限',true);
    },{timeout:12000,maximumAge:300000,enableHighAccuracy:false});
}

async function saveCityManual(){
    const box=document.getElementById('city-input');
    const city=(box&&box.value||'').trim();
    if(!city){tdStatus('city-status','城市名是空的',true);return;}
    try{
        const r=await postApi('/api/account/city',{city});
        tdStatus('city-status',r.msg);
        await refreshAccount();
    }catch(e){tdStatus('city-status',e.message||'城市没保存',true);}
}

async function saveAvoidTags(){
    const tags=AVOID_TAGS.filter(k=>{
        const el=document.getElementById('avoid-'+k);
        return !!(el&&el.checked);
    });
    try{
        const r=await postApi('/api/account/preferences',{avoid_tags:tags});
        accountCache=Object.assign({},accountCache,{avoid_tags:r.avoid_tags||tags});
        tdStatus('avoid-status','已保存 '+tags.length+' 项忌口'+(tags.length?'，外卖与食谱推荐会跟着变':'（全部取消，推荐不再排除菜名）'));
        if(typeof renderTakeoutAdvisor==='function')renderTakeoutAdvisor();
        if(typeof renderRecipePlan==='function')renderRecipePlan();
    }catch(e){tdStatus('avoid-status',e.message||'忌口没保存',true);}
}

async function sendBindCode(){
    const box=document.getElementById('bind-email');
    const email=(box&&box.value||'').trim();
    if(!email){tdStatus('email-status','先填邮箱',true);return;}
    try{
        const r=await postApi('/api/account/email/send',{email});
        tdStatus('email-status',r.msg+'（'+r.ttl_minutes+' 分钟内有效）');
    }catch(e){tdStatus('email-status',e.message||'验证码没发出去',true);}
}

async function verifyBindCode(){
    const email=((document.getElementById('bind-email')||{}).value||'').trim();
    const code=((document.getElementById('bind-code')||{}).value||'').trim();
    if(!email||!code){tdStatus('email-status','邮箱和验证码都要填',true);return;}
    try{
        const r=await postApi('/api/account/email/verify',{email,code});
        tdStatus('email-status',r.msg);
        await refreshAccount();
    }catch(e){tdStatus('email-status',e.message||'验证没通过',true);}
}

async function changePassword(){
    const old=(document.getElementById('pw-old').value||'');
    const nw=(document.getElementById('pw-new').value||'');
    const nw2=(document.getElementById('pw-new2').value||'');
    if(nw!==nw2){tdStatus('pw-status','两次输入的新密码不一样',true);return;}
    if(nw.length<8){tdStatus('pw-status','新密码至少 8 位',true);return;}
    try{
        const r=await postApi('/api/account/password',{old_password:old,new_password:nw});
        tdStatus('pw-status',r.msg+'（已下线 '+(r.revoked_sessions||0)+' 个其他会话）');
        document.getElementById('pw-old').value='';
        document.getElementById('pw-new').value='';
        document.getElementById('pw-new2').value='';
    }catch(e){tdStatus('pw-status',e.message||'密码没改成',true);}
}

// ============ 忘记密码（登录页入口，免登录） ============
// 这条链路必须在强更门豁免清单里：抬门之后如果把它也挡住，
// 忘密码的人就彻底回不来了——那正是"更新门"最坏的误伤。
// 也不能复用 postApi：那条要求已登录，而走到这里的人恰恰是没登录的。
async function publicPost(path,body){
    const res=await fetch(`${API_BASE}${path}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    let data=null;try{data=await res.json();}catch(e){data=null;}
    if(!res.ok)throw new Error((data&&data.detail)||`HTTP ${res.status}`);
    return data||{};
}

async function openForgotPassword(){
    toolDialog('找回密码',`
      <p class="td-lead">只有<b>已绑定并通过验证</b>的邮箱能走这条路。重置成功后所有设备都会下线。</p>
      <div class="td-group-label">第 1 步：发验证码</div>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">注册时绑定的邮箱</span><input id="fg-email" type="email" maxlength="200"></label>
        <div class="td-actions"><button type="button" class="td-btn" onclick="sendForgotCode()">发送验证码</button></div>
      </div>
      <div class="td-group-label">第 2 步：填验证码与新密码</div>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">验证码</span><input id="fg-code" inputmode="numeric" maxlength="6"></label>
        <label class="td-field-row"><span class="td-field-label">新密码（至少 8 位）</span><input id="fg-pw" type="password" maxlength="200" autocomplete="new-password"></label>
        <div class="td-actions"><button type="button" class="td-btn" onclick="submitForgotReset()">重置密码</button></div>
      </div>
      <p id="fg-status" class="td-status" role="status"></p>
      <p class="td-note">没绑过邮箱的账号找不回来：本软件不采集手机号，也没有人工客服通道。这条限制是明摆着的，不做"假装能找回"。</p>`);
    try{
        const res=await fetch(`${API_BASE}/api/account/recovery-status`);
        const s=await res.json();
        if(s&&s.mail!=='up')tdStatus('fg-status','邮件通道未接入：'+(s.mail_why||'')+'，现在发不出验证码',true);
    }catch(e){/* 状态读不到不拦人，真正发送时会给出明确失败原因 */}
}

async function sendForgotCode(){
    const email=((document.getElementById('fg-email')||{}).value||'').trim();
    if(!email){tdStatus('fg-status','先填邮箱',true);return;}
    try{
        const r=await publicPost('/api/account/forgot',{email});
        // 服务端对"绑过"和"没绑过"给同一句话，这里也不许加区别
        tdStatus('fg-status',r.msg);
    }catch(e){tdStatus('fg-status',e.message||'验证码没发出去',true);}
}

async function submitForgotReset(){
    const email=((document.getElementById('fg-email')||{}).value||'').trim();
    const code=((document.getElementById('fg-code')||{}).value||'').trim();
    const pw=((document.getElementById('fg-pw')||{}).value||'');
    if(!email||!code){tdStatus('fg-status','邮箱和验证码都要填',true);return;}
    if(pw.length<8){tdStatus('fg-status','新密码至少 8 位',true);return;}
    try{
        const r=await publicPost('/api/account/reset',{email,code,new_password:pw});
        tdStatus('fg-status',r.msg);
        const dlg=document.getElementById('account-tools-dialog');
        if(dlg&&dlg.open)setTimeout(()=>dlg.close(),1200);
    }catch(e){tdStatus('fg-status',e.message||'重置没成功',true);}
}

/* ============================================================
   r149 社区 / 私信 / 我的主页
   这一整块都遵循同三件事：
   1. 屏上出现的每个数字都从接口来，没有读数就写"没有"，不拿 0 或占位字顶；
   2. 发帖、评论、私信全部带 request_id 幂等，重试不该产生第二条；
   3. WebSocket 只是加速器，发不出去会自动退回 HTTP——断了也不许"看起来发了"。
   ============================================================ */
const CM_LIMITS = { post: 1000, comment: 500, dm: 1000, bio: 60, feedback: 800 };
const CM_TOOLS = ["recipes", "workout", "body", "takeout", "charts", "gemini"];
const cm = {
    feed: "latest", items: [], cursor: 0, more: false, loading: false, loaded: false,
    msgTab: "chats", convs: [], notices: [], loadingMsg: false,
    thread: null, bubbles: [], pending: {},
    ws: null, wsState: "idle", wsRetry: 0, wsTimer: null,
    stats: null, feedbackKind: "bug", images: [],
    myTheme: "green", unreadTotal: 0, postId: 0
};

/* 换账号必须把社区与私信的内存状态一起清掉：
   上一版的教训是 sessionGeneration 只管住了请求，界面还留着上一个人的列表。 */
function resetCommunity() {
    if (cm.ws) { try { cm.ws.onclose = null; cm.ws.close(); } catch (e) {} cm.ws = null; }
    cm.wsRetry = 0;
    cm.wsState = "idle";
    cm.feed = "latest"; cm.items = []; cm.cursor = 0; cm.more = false;
    cm.loading = false; cm.loaded = false; cm.loadingMsg = false;
    cm.convs = []; cm.notices = []; cm.thread = null; cm.bubbles = [];
    cm.pending = {}; cm.stats = null; cm.images = []; cm.myTheme = "green";
    cm.unreadTotal = 0; cm.postId = 0;
    qsCloseAllPages();
    paintNavBadge();
}

function cmEl(id) { return document.getElementById(id); }
function cmText(id, text) { const el = cmEl(id); if (el) el.textContent = text || ""; }

/* ── 整页跳转层 ─────────────────────────────────────────────
   机主要求：看内容一律整页（带返回），弹窗只留给"确认一件小事"。
   栈里只存"这一页怎么渲染"，不存渲染结果——返回时重新拉一遍，
   省得拿到一份过期的 DOM（上一版私信线程就是靠重渲染保持一致的）。 */
const QS_PAGES = [];
const QS_PAGE_DEF = {};

function qsRenderTop() {
    const top = QS_PAGES[QS_PAGES.length - 1];
    const layer = cmEl("page-layer");
    if (!top || !layer) return;
    layer.hidden = false;
    document.body.classList.add("qs-page-open");
    // 聊天页会把正文区改成弹性布局，每页开头统一复位，免得串页
    const bodyEl = cmEl("pl-body");
    if (bodyEl) bodyEl.className = "pl-body";
    cmText("pl-title", typeof top.title === "function" ? top.title() : top.title);
    top.render(top.arg);
}

function openPage(name, arg) {
    const def = QS_PAGE_DEF[name];
    if (!def) return;
    QS_PAGES.push({ name: name, arg: arg, title: def.title, render: def.render });
    qsRenderTop();
}

/** 关掉最上面一页；栈空时整层收起。返回 true 表示这一层还开着（给硬件返回键判断用）。 */
function closePage() {
    if (!QS_PAGES.length) return false;
    QS_PAGES.pop();
    if (QS_PAGES.length) { qsRenderTop(); return true; }
    const layer = cmEl("page-layer");
    if (layer) { layer.hidden = true; cmEl("pl-body").innerHTML = ""; cmEl("pl-foot").innerHTML = ""; }
    document.body.classList.remove("qs-page-open");
    return false;
}

/** 真在页面里（不是被压在栈底下）才算"当前页"，切 tab 时要先把栈清空。 */
function qsPageOpen() { return QS_PAGES.length > 0; }
function qsCloseAllPages() { while (QS_PAGES.length) { QS_PAGES.pop(); }
    const layer = cmEl("page-layer");
    if (layer) layer.hidden = true;
    document.body.classList.remove("qs-page-open");
}

function qsSetFoot(html) {
    const foot = cmEl("pl-foot");
    if (!foot) return;
    foot.innerHTML = html || "";
    foot.hidden = !html;
}

/** 复制按钮的通用出口：值放在 data-copy 里，避免把内容拼进 onclick 时踩引号转义。 */
function qsCopyFrom(btn) {
    qsCopy(btn.getAttribute("data-copy") || "", btn.getAttribute("data-label") || "内容");
}

/** 复制一段文本。剪贴板 API 在非安全上下文或被拒时会退回 execCommand，
 *  两条路都没走通就明说没成功并让人照着抄——不许"没复制上还说已复制"。 */
async function qsCopy(text, label) {
    const s = String(text == null ? "" : text);
    if (!s) { callNativeToast((label || "内容") + "是空的，没什么可复制"); return false; }
    let done = false;
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(s);
            done = true;
        }
    } catch (e) { done = false; }
    if (!done) {
        try {
            const ta = document.createElement("textarea");
            ta.value = s;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.top = "-1000px";
            document.body.appendChild(ta);
            ta.select();
            done = document.execCommand("copy");
            document.body.removeChild(ta);
        } catch (e) { done = false; }
    }
    callNativeToast(done ? ((label || "内容") + "已复制") : ("复制没成功，可以照着抄：" + s));
    return done;
}

function cmTime(stamp) {
    const s = String(stamp || "");
    return s.length >= 16 ? s.slice(5, 16).replace("T", " ") : s;
}

function cmAgo(stamp) {
    const s = String(stamp || "").replace(" ", "T");
    const t = Date.parse(s);
    if (!isFinite(t)) return cmText0(stamp);
    const mins = Math.floor((Date.now() - t) / 60000);
    if (mins < 1) return "刚刚";
    if (mins < 60) return mins + " 分钟前";
    if (mins < 60 * 24) return Math.floor(mins / 60) + " 小时前";
    if (mins < 60 * 24 * 7) return Math.floor(mins / 1440) + " 天前";
    return cmText0(stamp);
}
function cmText0(stamp) { return String(stamp || "").slice(0, 10); }

/* 头像点：有图用图，没图用昵称首字（Array.from 防 emoji 被按下标切半个码元） */
function cmAvatarInner(user, fallback) {
    const url = user && user.avatar;
    if (url) return '<img src="' + escapeHtml(API_BASE + url) + '" alt="">';
    const nm = String((user && user.name) || fallback || "").trim();
    const first = nm ? Array.from(nm)[0] : "轻";
    return escapeHtml(first.toUpperCase());
}

function cmName(user) { return (user && user.name) ? user.name : "已注销用户"; }
function cmRegionTag(region) { return region ? "属地 " + escapeHtml(region) : "属地未知"; }

function cmState(id, text) { cmText(id, text || ""); }

function cmRoute(tab) {
    // 切 tab 时先把整页层收掉：从帖子页里点底部导航，不该还盖着一层页
    if (qsPageOpen()) qsCloseAllPages();
    if (tab === "community" && !cm.loaded && !cm.loading) loadCommunity(false);
    if (tab === "messages") { loadMessages(); connectChat(); }
    if (tab === "me") loadMe();
    if (tab === "tools") syncFeedbackHints();
}

/* ── 社区列表 ───────────────────────────────────────────────── */
function setCommunityTab(which) {
    if (!["latest", "follow", "mine", "city"].includes(which)) return;
    cm.feed = which;
    document.querySelectorAll("#panel-community .td-seg-btn").forEach(b =>
        b.setAttribute("aria-selected", b.getAttribute("data-feed") === which ? "true" : "false"));
    cm.items = []; cm.cursor = 0; cm.more = false;
    loadCommunity(false);
}

/* 广场卡片上的两个数字都从 cm.items 现写：点赞/评论之后只改内存不改 DOM，
   界面就会一直停在旧值，用户以为没生效又点一次。 */
function syncCardCounts(postId) {
    const item = cm.items.find(x => x.id === Number(postId));
    const card = document.getElementById("post-" + postId);
    if (!item || !card) return;
    const nums = card.querySelectorAll(".cm-act b");
    if (nums[0]) nums[0].textContent = String(Number(item.like_count));
    if (nums[1]) nums[1].textContent = String(Number(item.comment_count));
    const like = card.querySelector(".cm-act");
    if (like) like.setAttribute("aria-pressed", item.liked_by_me ? "true" : "false");
}

function cmCardHTML(p, withId) {
    const imgs = (p.images || []).length
        ? '<div class="cm-grid">' + p.images.map(u =>
            '<img src="' + escapeHtml(API_BASE + u) + '" alt="帖子配图" loading="lazy" onclick="viewPostImage(\'' +
            escapeHtml(API_BASE + u).replace(/'/g, "%27") + '\')">').join("") + "</div>"
        : "";
    const mine = p.author && p.author.id === (state.user && state.user.id);
    return '<article class="cm-card"' + (withId ? ' id="post-' + p.id + '"' : '') + ' data-post="' + p.id + '">'
        + '<div class="cm-card-head">'
        + '<button type="button" class="cm-who-btn" onclick="openMemberHome(' + (p.author ? p.author.id : 0) + ')">'
        + '<span class="cm-avatar">' + cmAvatarInner(p.author) + "</span>"
        + '<span class="cm-who"><span class="cm-name">' + escapeHtml(cmName(p.author)) + "</span>"
        + '<span class="cm-sub">' + cmRegionTag(p.region) + " · " + escapeHtml(cmAgo(p.created_at)) + "</span></span></button>"
        + (mine ? "" : '<button type="button" class="cm-follow" aria-pressed="' + (p.followed_by_me ? "true" : "false") +
            '" onclick="toggleFollow(' + (p.author ? p.author.id : 0) + ',this)">' +
            (p.followed_by_me ? "已关注" : "关注") + "</button>")
        + "</div>"
        + '<div class="cm-body">' + escapeHtml(p.body) + "</div>" + imgs
        + '<div class="cm-acts">'
        + '<button type="button" class="cm-act" aria-pressed="' + (p.liked_by_me ? "true" : "false") + '" '
        + 'onclick="toggleLike(' + p.id + ',this)">❤ <b data-like>' + Number(p.like_count) + "</b></button>"
        + '<button type="button" class="cm-act" onclick="openPostDetail(' + p.id + ')">💬 <b>' + Number(p.comment_count) + "</b></button>"
        + (mine ? '<button type="button" class="cm-act" style="margin-left:auto" onclick="deletePost(' + p.id + ')">删除</button>' : "")
        + "</div></article>";
}

function renderFeed() {
    const host = cmEl("cm-feed");
    if (!host) return;
    host.innerHTML = cm.items.map(function (p) { return cmCardHTML(p, true); }).join("");
    const more = cmEl("cm-more");
    if (more) more.hidden = !cm.more;
    if (cmState("cm-feed-state", ""), !cm.items.length) {
        cmState("cm-feed-state", cm.feed === "mine" ? "你还没有发过帖子，上面那条就是入口。"
            : cm.feed === "follow" ? "关注的人发的帖子会出现在这里。现在还没有。"
            : cm.feed === "city" ? "同城还没有帖子。属地是发帖子或评论时按 IP 认出来的，只到省一级。"
            : "广场还空着，第一条可以你来发。");
    }
}

async function loadCommunity(append) {
    if (!state.token) { cm.items = []; renderFeed(); cmState("cm-feed-state", "登录后才能看社区。"); return; }
    if (cm.loading) return;
    cm.loading = true;
    if (!append) cmState("cm-feed-state", "在读…");
    try {
        const q = "?tab=" + cm.feed + "&limit=12" + (append && cm.cursor ? "&cursor=" + cm.cursor : "");
        const r = await getJson("/api/community/feed" + q);
        cm.items = append ? cm.items.concat(r.items || []) : (r.items || []);
        cm.cursor = r.next_cursor || 0;
        cm.more = !!r.more;
        cm.loaded = true;   // 读完一次才算 loaded；失败时留着 false，切回来会自己重试
        renderFeed();
    } catch (e) {
        cmState("cm-feed-state", "列表没读到：" + (e.message || "网络不通") + "，点上面任意一处重试。");
    } finally {
        cm.loading = false;
    }
}

function expandComposer() {
    if (!state.token) { openAuthModal(); return; }
    const c = cmEl("cm-compose-collapsed"), o = cmEl("cm-compose-open");
    if (c) c.hidden = true;
    if (o) o.hidden = false;
    syncComposerCount();
    const t = cmEl("cm-post-text");
    if (t) t.focus();
}

function syncComposerCount() {
    const t = cmEl("cm-post-text");
    cmText("cm-post-count", ((t && t.value ? t.value.length : 0)) + " / " + CM_LIMITS.post);
}

function syncFeedbackCounters() {
    const t = cmEl("fb-text");
    cmText("fb-count", ((t && t.value ? t.value.length : 0)) + " / " + CM_LIMITS.feedback);
}

async function attachPostImage(input) {
    const file = input && input.files && input.files[0];
    if (!file) return;
    if (!state.token) { openAuthModal(); return; }
    cmState("cm-post-err", "图片在上传…");
    try {
        const form = new FormData();
        form.append("file", file);
        const r = await rawPostApi("/api/community/media", form);
        if (cm.images.length >= 6) cmState("cm-post-err", "一条帖子最多 6 张图，多余的没加进来");
        else cm.images.push({ name: r.name, url: r.url });
        renderThumbs();
        cmState("cm-post-err", "");
    } catch (e) {
        cmState("cm-post-err", "图片没传上去：" + (e.message || "格式或大小不合适"));
    } finally {
        input.value = "";
    }
}

function renderThumbs() {
    const host = cmEl("cm-thumbs");
    if (!host) return;
    host.innerHTML = cm.images.map((im, i) =>
        '<span class="cm-thumb"><img src="' + escapeHtml(im.url.startsWith("http") ? im.url : API_BASE + im.url) +
        '" alt="待发布配图"><button type="button" aria-label="移除这张图" onclick="dropPostImage(' + i + ')">✕</button></span>'
    ).join("");
}

function dropPostImage(i) { cm.images.splice(i, 1); renderThumbs(); }

async function submitPost() {
    const t = cmEl("cm-post-text");
    const text = (t && t.value || "").trim();
    if (!text && !cm.images.length) { cmState("cm-post-err", "正文和图片至少给一个"); return; }
    cmState("cm-post-err", "");
    try {
        const r = await postApi("/api/community/posts", { text, images: cm.images.map(x => x.name) });
        cm.images = []; renderThumbs();
        if (t) t.value = "";
        syncComposerCount();
        const open = cmEl("cm-compose-open"), collapsed = cmEl("cm-compose-collapsed");
        if (open) open.hidden = true;
        if (collapsed) collapsed.hidden = false;
        callNativeToast("发出去了");
        if (cm.feed === "mine" || cm.feed === "latest") {
            cm.items = [r.post].concat(cm.items);
            renderFeed();
        } else {
            loadCommunity(false);
        }
    } catch (e) {
        cmState("cm-post-err", e.message || "发帖没成功，内容还留着，可以再试");
    }
}

function viewPostImage(url) {
    toolDialog("帖子配图", '<div class="td-body"><img src="' + escapeHtml(url) +
        '" alt="帖子配图" style="width:100%;border-radius:12px;object-fit:contain"></div>');
}

async function toggleLike(id, btn) {
    const card = btn.closest(".cm-card");
    const cur = btn.getAttribute("aria-pressed") === "true";
    btn.setAttribute("aria-pressed", cur ? "false" : "true");
    try {
        const r = await postApi("/api/community/posts/" + id + "/like", { on: !cur });
        const b = card && card.querySelector("[data-like]");
        if (b) b.textContent = Number(r.like_count);
        const item = cm.items.find(x => x.id === id);
        if (item) { item.like_count = r.like_count; item.liked_by_me = r.liked; }
        syncCardCounts(id);
    } catch (e) {
        btn.setAttribute("aria-pressed", cur ? "true" : "false");
        callNativeToast("点赞没生效：" + (e.message || "网络不通"));
    }
}

/* postApi 只会 POST，删除要单独走一条，失败原因照样要说出来 */
async function deleteJson(path) {
    const r = await fetch(API_BASE + path, {
        method: "DELETE", headers: { "Authorization": "Bearer " + state.token }
    });
    if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        const err = new Error(j && j.detail ? j.detail : ("HTTP " + r.status));
        err.status = r.status;
        throw err;
    }
    return r.json().catch(() => ({}));
}

async function deletePost(id) {
    if (!confirm("删掉这条帖子？删了就找不回来了。")) return;
    try {
        await deleteJson("/api/community/posts/" + id);
        cm.items = cm.items.filter(x => x.id !== id);
        renderFeed();
        callNativeToast("已删除");
    } catch (e) {
        callNativeToast("没删掉：" + (e.message || "网络不通"));
    }
}

/* 帖子详情：整页跳转（机主："帖子不要做成弹窗，跳转页面，参考微博"）。
   正文大一号、配图单独一块、时间退到分割线下面，评论区铺满，输入框固定在底部。 */
async function qsRenderPost(id) {
    const body = cmEl("pl-body");
    if (!body) return;
    qsSetFoot("");
    body.innerHTML = '<p class="cm-state">在读…</p>';
    let r;
    try {
        r = await getJson("/api/community/posts/" + id);
    } catch (e) {
        body.innerHTML = '<p class="cm-state">这条帖子打不开：' + escapeHtml(e.message || "网络不通") + "</p>";
        return;
    }
    const p = r.post;
    if (!p) { body.innerHTML = '<p class="cm-state">这条帖子已经不在了。</p>'; return; }
    cm.postId = Number(id);
    cmText("pl-title", cmName(p.author) + " 的帖子");
    const mine = p.author && state.user && p.author.id === state.user.id;
    const imgs = (p.images || []).length
        ? '<div class="pd-imgs' + (p.images.length === 1 ? " one" : "") + '">' + p.images.map(u =>
            '<img src="' + escapeHtml(API_BASE + u) + '" alt="帖子配图" onclick="viewPostImage(\'' +
            escapeHtml(API_BASE + u).replace(/'/g, "%27") + '\')">').join("") + "</div>"
        : "";
    const comments = (r.comments || []).map(c => '<div class="pd-cmt">'
        + '<span class="cm-avatar sm">' + cmAvatarInner(c.author) + "</span>"
        + '<div class="pd-cmt-main"><div class="pd-cmt-name">' + escapeHtml(cmName(c.author)) + "</div>"
        + '<div class="pd-cmt-text">' + escapeHtml(c.body) + "</div>"
        + '<div class="pd-cmt-sub"><span>' + cmRegionTag(c.region) + " · " + escapeHtml(cmAgo(c.created_at)) + "</span>"
        + '<button type="button" class="pd-reply" onclick="setReplyTarget(' + c.id + ",'" +
          escapeHtml(cmName(c.author)).replace(/'/g, "%27") + '\')">回复</button>'
        + (c.deletable ? '<button type="button" class="pd-reply" onclick="removeComment(' + c.id + ',' + p.id + ')">删除</button>' : "")
        + "</div></div></div>").join("");
    body.innerHTML = '<article class="pd-post">'
        + '<div class="pd-who"><button type="button" class="cm-who-btn" onclick="openPage(\'member\',' + (p.author ? p.author.id : 0) + ')">'
        + '<span class="cm-avatar">' + cmAvatarInner(p.author) + "</span>"
        + '<span class="cm-who"><span class="cm-name">' + escapeHtml(cmName(p.author)) + "</span>"
        + '<span class="cm-sub">' + cmRegionTag(p.region) + "</span></span></button>"
        + (mine ? "" : '<button type="button" class="cm-follow" aria-pressed="' + (p.followed_by_me ? "true" : "false") +
            '" onclick="toggleFollow(' + (p.author ? p.author.id : 0) + ',this)">' +
            (p.followed_by_me ? "已关注" : "关注") + "</button>")
        + "</div>"
        + '<div class="pd-text">' + escapeHtml(p.body) + "</div>" + imgs
        + '<div class="pd-meta">' + escapeHtml(cmTime(p.created_at)) + " · " + cmRegionTag(p.region) + "</div>"
        + '<div class="pd-acts">'
        + '<button type="button" class="td-mini" aria-pressed="' + (p.liked_by_me ? "true" : "false") + '" '
        + 'onclick="toggleLike(' + p.id + ',this)">❤ 赞 ' + Number(p.like_count) + "</button>"
        + '<button type="button" class="td-mini" onclick="focusCommentInput()">💬 评论 ' + Number(p.comment_count) + "</button>"
        + (p.author && !mine ? '<button type="button" class="td-mini" onclick="openDM(' + p.author.id + ')">私信 TA</button>' : "")
        + (mine ? '<button type="button" class="td-mini" style="margin-left:auto" onclick="deletePostFromDetail(' + p.id + ')">删除</button>' : "")
        + "</div></article>"
        + '<h3 class="pd-sec">评论 ' + Number(p.comment_count) + "</h3>"
        + (comments || '<p class="td-empty">还没有人评论，说第一句。</p>');
    qsSetFoot('<input id="cm-comment-text" type="text" maxlength="' + CM_LIMITS.comment +
        '" placeholder="' + (cmReplyTo ? "回复 @" + escapeHtml(cmReplyTo.name) : "友善一点，别报体重之外的数字") +
        '" aria-label="评论内容" onkeydown="if(event.key===\'Enter\'){event.preventDefault();submitComment(' + p.id + ');}">'
        + '<button type="button" class="td-btn" onclick="submitComment(' + p.id + ')">发送</button>');
}

function focusCommentInput() {
    const input = cmEl("cm-comment-text");
    if (input) input.focus();
}

async function deletePostFromDetail(id) {
    if (!confirm("删掉这条帖子？删了就找不回来了。")) return;
    try {
        await deleteJson("/api/community/posts/" + id);
        cm.items = cm.items.filter(x => x.id !== id);
        renderFeed();
        qsCloseAllPages();
        callNativeToast("已删除");
    } catch (e) { callNativeToast("没删掉：" + (e.message || "网络不通")); }
}

async function removeComment(id, postId) {
    if (!confirm("删掉这条评论？")) return;
    try {
        await deleteJson("/api/community/comments/" + id);
        qsRenderPost(postId);
        syncCardCounts(postId);
        callNativeToast("评论已删除");
    } catch (e) { callNativeToast("没删掉：" + (e.message || "网络不通")); }
}

QS_PAGE_DEF.post = { title: "帖子详情", render: qsRenderPost };

/* 旧入口保留成一行跳转，别的地方还在按老名字调它们 */
function openPostDetail(id) { if (id) openPage("post", id); }
function openThread(uid) { if (uid) openPage("dm", uid); }

let cmReplyTo = null;
function setReplyTo(id) { cmReplyTo = id; }
function setReplyTarget(id, name) {
    cmReplyTo = { id: id, name: name };
    const input = cmEl("cm-comment-text");
    if (input) { input.placeholder = "回复 @" + name; input.focus(); }
}

async function submitComment(postId) {
    const input = cmEl("cm-comment-text");
    const text = (input && input.value || "").trim();
    if (!text) { callNativeToast("评论不能为空"); if (input) input.focus(); return; }
    try {
        await postApi("/api/community/posts/" + postId + "/comments",
            { text, reply_to: cmReplyTo ? cmReplyTo.id : null });
        cmReplyTo = null;
        callNativeToast("评论发出去了");
        if (input) input.value = "";
        qsRenderPost(postId);
        const item = cm.items.find(x => x.id === Number(postId));
        if (item) item.comment_count = Number(item.comment_count || 0) + 1;
        syncCardCounts(postId);
    } catch (e) {
        callNativeToast(e.message || "评论没成功");
    }
}

async function toggleFollow(uid, btn) {
    const on = btn.getAttribute("aria-pressed") === "true";
    try {
        const r = await postApi("/api/community/users/" + uid + "/follow", { on: !on });
        btn.setAttribute("aria-pressed", r.following ? "true" : "false");
        btn.textContent = r.following ? "已关注" : "关注";
    } catch (e) {
        callNativeToast("关注没生效：" + (e.message || "网络不通"));
    }
}

async function searchMembers() {
    const input = cmEl("cm-search-input");
    const q = (input && input.value || "").trim();
    const host = cmEl("cm-search-results");
    if (!host) return;
    if (!q) { host.hidden = true; host.innerHTML = ""; return; }
    host.hidden = false;
    host.innerHTML = '<p class="td-empty">在找…</p>';
    try {
        const r = await getJson("/api/community/search?q=" + encodeURIComponent(q));
        const items = r.items || [];
        host.innerHTML = items.length ? items.map(u =>
            '<button type="button" class="cm-row" onclick="openMemberHome(' + u.id + ')">'
            + '<span class="cm-avatar">' + cmAvatarInner(u) + "</span>"
            + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(cmName(u)) + "</span>"
            + '<span class="cm-row-meta">轻塑号 ' + escapeHtml(u.public_id || "—") +
            (u.region ? " · 属地 " + escapeHtml(u.region) : "") + "</span></span></button>").join("")
            : '<p class="td-empty">没找到这个人。轻塑号要输全 8 位，昵称可以只输几个字。</p>';
    } catch (e) {
        host.innerHTML = '<p class="td-empty">搜索没成功：' + escapeHtml(e.message || "网络不通") + "</p>";
    }
}

async function qsRenderMember(ident) {
    const body = cmEl("pl-body");
    if (!body) return;
    qsSetFoot("");
    body.innerHTML = '<p class="cm-state">在读…</p>';
    let r;
    try {
        r = await getJson("/api/community/users/" + ident);
    } catch (e) {
        body.innerHTML = '<p class="cm-state">主页打不开：' + escapeHtml(e.message || "网络不通") + "</p>";
        return;
    }
    const u = r.user;
    if (!u) { body.innerHTML = '<p class="cm-state">看不了这个主页（对方可能关掉了「允许别人搜到我」）。</p>'; return; }
    cmText("pl-title", cmName(u));
    cmEl("pl-slot").innerHTML = u.is_me ? "" :
        '<button type="button" class="td-mini" onclick="openDM(' + u.id + ')">私信</button>';
    const stats = [["posts", "帖子", u.posts], ["followers", "粉丝", u.followers],
                   ["following", "关注", u.following], ["likes", "获赞", u.likes_received]];
    body.innerHTML = '<div class="card me-hero"><span class="me-avatar">' + cmAvatarInner(u) + "</span>"
        + '<div class="me-hero-main"><div class="me-name">' + escapeHtml(cmName(u)) + "</div>"
        + '<div class="me-line">轻塑号 <b>' + escapeHtml(u.public_id || "—") + "</b>"
        + '<button type="button" class="me-copy" data-copy="' + escapeHtml(String(u.public_id || "")) + '" data-label="轻塑号" onclick="qsCopyFrom(this)">复制</button></div>'
        + '<div class="me-line">' + cmRegionTag(u.region) + (u.is_me ? " · 这是你自己" : "") + "</div>"
        + '<div class="me-bio">' + escapeHtml(u.bio || "还没有签名") + "</div></div></div>"
        + '<div class="card me-stats">' + stats.map(s =>
            '<button type="button" class="me-stat" onclick="openStats(\'' + s[0] + "'," + u.id + ')">'
            + '<b>' + Number(s[1]) + "</b><span>" + s[2] + "</span></button>").join("") + "</div>"
        + (u.is_me ? "" : '<div class="td-actions">'
            + '<button type="button" class="td-btn" aria-pressed="' + (u.followed ? "true" : "false") + '" onclick="toggleFollow(' + u.id + ',this)">' +
            (u.followed ? "已关注" : "关注") + '</button><button type="button" class="td-btn td-btn-quiet" onclick="openDM(' + u.id + ')">私信</button></div>')
        + '<h3 class="pd-sec">' + (u.is_me ? "我的帖子" : "TA 的帖子") + "</h3>"
        + '<div class="cm-feed">'
        + ((r.items || []).length ? r.items.map(function (x) { return cmCardHTML(x, false); }).join("")
            : '<p class="td-empty">还没有公开的帖子。</p>') + "</div>";
}

QS_PAGE_DEF.member = { title: "主页", render: qsRenderMember };

/* 旧入口保留：点名字、点头像统一走整页（带返回），不再弹窗 */
function openMemberHome(ident) { if (ident) openPage("member", ident); }

/* ── 消息：私信 + 互动通知 ─────────────────────────────────── */
function setMessageTab(which) {
    cm.msgTab = which;
    document.querySelectorAll("#panel-messages .td-seg-btn").forEach(b =>
        b.setAttribute("aria-selected", b.getAttribute("data-msg") === which ? "true" : "false"));
    renderMessages();
}

function paintNavBadge() {
    const badge = cmEl("nav-msg-badge");
    if (!badge) return;
    const dm = (cm.stats && cm.stats.dm_unread) || 0;
    const nt = (cm.stats && cm.stats.notices_unread) || 0;
    const total = dm + nt;
    badge.hidden = total <= 0;
    badge.textContent = total > 99 ? "99+" : String(total);
}

async function loadMessages() {
    if (!state.token) { cmState("msg-state", "登录后才能看消息。"); return; }
    if (cm.loadingMsg) return;
    cm.loadingMsg = true;
    try {
        if (cm.msgTab === "chats") {
            const r = await getJson("/api/chat/conversations");
            cm.convs = r.items || [];
        } else {
            const n = await getJson("/api/notifications?limit=30");
            cm.notices = n.items || [];
            cm.unreadTotal = n.unread || 0;
        }
        const s = await getJson("/api/community/stats");
        cm.stats = s;
        paintNavBadge();
        renderMessages();
    } catch (e) {
        cmState("msg-state", "消息没读到：" + (e.message || "网络不通"));
    } finally {
        cm.loadingMsg = false;
    }
}

function renderMessages() {
    const host = cmEl("msg-list");
    if (!host) return;
    if (cm.msgTab === "chats") {
        host.innerHTML = cm.convs.map(c =>
            '<button type="button" class="cm-row" onclick="openThread(' + c.with.id + ')">'
            + '<span class="cm-avatar">' + cmAvatarInner(c.with) + "</span>"
            + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(cmName(c.with)) +
            (c.online ? " · 在线" : "") + (c.blocked ? " · 已拉黑" : "") + "</span>"
            + '<span class="cm-row-meta">' + escapeHtml(c.last_body || "还没有消息") + "</span></span>"
            + '<span class="cm-row-side">' + escapeHtml(cmAgo(c.last_at))
            + (c.unread ? '<br><span class="td-badge">' + Number(c.unread) + "</span>" : "") + "</span></button>"
        ).join("");
        if (!cm.convs.length) cmState("msg-state", "还没有人跟你说过话。在帖子或主页上点「私信」就能开口。");
        else cmState("msg-state", "");
    } else {
        const rows = cm.notices.map(n =>
            '<div class="cm-row" style="cursor:default"><span class="cm-avatar">' + cmAvatarInner(n.actor) + "</span>"
            + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(n.text || cmName(n.actor)) + "</span>"
            + '<span class="cm-row-meta">' + escapeHtml(cmAgo(n.created_at)) + (n.read_at ? "" : " · 未读") + "</span></span>"
            + (n.post_id ? '<span class="cm-row-side"><button type="button" class="td-btn td-btn-quiet" onclick="openPostDetail(' +
                n.post_id + ')">看帖子</button></span>' : "") + "</div>"
        ).join("");
        const markAll = (cm.unreadTotal || 0) > 0
            ? '<button type="button" class="td-btn td-btn-quiet cm-more" onclick="markNoticesRead()">全部标为已读（'
              + Number(cm.unreadTotal) + " 条未读）</button>"
            : "";
        host.innerHTML = rows + markAll;
        if (!cm.notices.length) cmState("msg-state", "还没有人给你点赞或评论。");
        else cmState("msg-state", (cm.unreadTotal || 0) > 0 ? "" : "都读过了。");
    }
}

/* 全部标为已读。上一版这个按钮绑了一个根本不存在的函数，
   于是未读红点永远消不掉——这条是那份清单里的 P0 第 1 项。 */
async function markNoticesRead() {
    if (!state.token) { openAuthModal(); return; }
    try {
        const r = await postApi("/api/notifications/read", { all: true });
        cm.notices = cm.notices.map(n => Object.assign({}, n, { read_at: n.read_at || "just now" }));
        cm.unreadTotal = 0;
        if (cm.stats) cm.stats.notices_unread = 0;
        paintNavBadge();
        renderMessages();
        callNativeToast("都标成已读了（" + Number((r && r.changed) || 0) + " 条）");
    } catch (e) {
        callNativeToast("没标上：" + (e.message || "网络不通"));
    }
}

/* ── 统计格点进去：粉丝 / 关注 / 获赞 / 帖子 ─────────────────── */
const QS_STAT_TITLES = { followers: "粉丝", following: "关注", likes: "收到的赞", posts: "全部帖子" };

function openStats(kind, uid) {
    if (!QS_STAT_TITLES[kind]) return;
    openPage("stats", { kind: kind, uid: uid });
}

async function qsRenderStats(arg) {
    const body = cmEl("pl-body");
    if (!body) return;
    qsSetFoot("");
    const kind = arg.kind, uid = arg.uid || (state.user && state.user.id);
    cmText("pl-title", QS_STAT_TITLES[kind] || "列表");
    body.innerHTML = '<p class="cm-state">在读…</p>';
    try {
        if (kind === "followers" || kind === "following") {
            const r = await getJson("/api/community/connections?user_id=" + uid + "&kind=" + kind + "&limit=30");
            const items = r.items || [];
            cmText("pl-title", (QS_STAT_TITLES[kind]) + " " + Number(r.total != null ? r.total : items.length));
            body.innerHTML = items.length ? '<div class="cm-list">' + items.map(u =>
                '<button type="button" class="cm-row" onclick="openPage(\'member\',' + u.id + ')">'
                + '<span class="cm-avatar">' + cmAvatarInner(u) + "</span>"
                + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(cmName(u)) + "</span>"
                + '<span class="cm-row-meta">轻塑号 ' + escapeHtml(u.public_id || "—")
                + (u.region ? " · 属地 " + escapeHtml(u.region) : "") + "</span></span>"
                + '<span class="cm-row-side">' + (u.followed_by_me ? "已互相关注" : "") + "</span></button>").join("")
                + "</div>"
                : '<p class="td-empty">' + (kind === "followers" ? "还没有粉丝。" : "还没关注任何人。") + "</p>";
            return;
        }
        const sort = kind === "likes" ? "likes" : "recent";
        const r = await getJson("/api/community/posts-of?user_id=" + uid + "&sort=" + sort + "&limit=30");
        const items = r.items || [];
        cmText("pl-title", QS_STAT_TITLES[kind] + " " + Number(items.length));
        body.innerHTML = items.length ? '<div class="cm-feed">'
            + items.map(function (x) { return cmCardHTML(x, false); }).join("") + "</div>"
            : '<p class="td-empty">' + (kind === "likes" ? "还没有人给你点赞。" : "还没有发过帖子。") + "</p>";
    } catch (e) {
        body.innerHTML = '<p class="cm-state">读不到：' + escapeHtml(e.message || "网络不通") + "</p>";
    }
}

QS_PAGE_DEF.stats = { title: "列表", render: qsRenderStats };

async function openDM(uid) {
    if (!state.token) { openAuthModal(); return; }
    if (!uid) return;
    const dlg = cmEl("account-tools-dialog");
    if (dlg && dlg.open) dlg.close();
    // 以前是从「消息」tab 里点开的，连接由那次 switchTab 顺手拉起；
    // 现在私信是整页，从主页直接进来，连接得在这里自己发起。
    connectChat();
    openPage("dm", uid);
}

async function qsRenderDm(uid) {
    const body = cmEl("pl-body");
    if (!body) return;
    body.className = "pl-body chat";
    if (!cm.thread || cm.thread.partner.id !== Number(uid)) {
        cm.thread = { partner: { id: Number(uid) }, more: false, cursor: 0 };
        cm.bubbles = [];
        body.innerHTML = '<div class="cm-bubbles page" id="thread-bubbles"><p class="cm-state">在读…</p></div>';
        qsSetFoot("");
        await refreshThread();
        return;
    }
    body.innerHTML = '<div class="cm-bubbles page" id="thread-bubbles"></div>';
    paintThread();
}

QS_PAGE_DEF.dm = { title: "私信", render: qsRenderDm };

function closeThread() {
    cm.thread = null;
    qsCloseAllPages();
    loadMessages();
}

async function refreshThread() {
    if (!cm.thread) return;
    const uid = cm.thread.partner.id;
    try {
        const r = await getJson("/api/chat/messages?with_user=" + uid + "&limit=30");
        cm.thread.partner = r.partner || cm.thread.partner;
        cm.bubbles = r.items || [];
        cm.thread.more = !!r.more;
        cm.thread.cursor = r.next_cursor || 0;
        paintThread();
        await postApi("/api/chat/read", { with_user: uid });
        // 读完要把未读徽标一起结掉，否则红点会一直挂着（上一版就是这么坏的）
        const conv = cm.convs.find(c => c.with && c.with.id === Number(uid));
        if (conv) conv.unread = 0;
        if (cm.stats) cm.stats.dm_unread = 0;
        paintNavBadge();
    } catch (e) {
        const host = cmEl("thread-bubbles");
        if (host) host.innerHTML = '<p class="cm-state">记录没读到：' + escapeHtml(e.message || "网络不通") + "</p>";
    }
}

function paintThread() {
    if (!cm.thread) return;
    const me = state.user && state.user.id;
    const p = cm.thread.partner;
    cmText("pl-title", cmName(p));
    const slot = cmEl("pl-slot");
    if (slot) {
        const blocked = !!(p && p.blocked);
        slot.innerHTML = '<button type="button" class="td-mini" id="thread-block-btn" aria-pressed="' +
            (blocked ? "true" : "false") + '" onclick="toggleBlock()">' + (blocked ? "取消拉黑" : "拉黑") + "</button>"
            + '<button type="button" class="td-mini" onclick="openBubbleTheme()">气泡</button>';
    }
    const host = cmEl("thread-bubbles");
    if (!host) return;
    const rows = [];
    if (cm.thread.more) rows.push('<button type="button" class="td-btn td-btn-quiet" style="align-self:center" onclick="loadOlderMessages()">看更早的消息</button>');
    rows.push(...cm.bubbles.map(m => cmBubbleHTML(m, me)));
    Object.keys(cm.pending).forEach(rid => rows.push(cmBubbleHTML(cm.pending[rid].msg, me, true)));
    host.innerHTML = rows.join("");
    host.scrollTop = host.scrollHeight;
    qsSetFoot('<input id="dm-input" type="text" maxlength="' + CM_LIMITS.dm +
        '" placeholder="说点什么…" aria-label="私信内容" onkeydown="if(event.key===\'Enter\'){event.preventDefault();sendDM();}">'
        + '<button type="button" class="td-btn" onclick="sendDM()">发送</button>');
}

function cmBubbleHTML(m, me, pending) {
    const mine = m.from_id === me;
    if (m.recalled_at) {
        return '<div class="cm-bubble recalled">' + (mine ? "你撤回了一条消息" : "对方撤回了一条消息") + "</div>";
    }
    const mid = Number(m.id || 0);
    return '<div class="cm-bubble ' + (mine ? "me" : "them") + (pending ? " pending" : "") + '"'
        + (mine && cm.myTheme && cm.myTheme !== "green" ? ' data-t="' + escapeHtml(cm.myTheme) + '"' : "")
        + ' data-mid="' + mid + '" data-mine="' + (mine ? 1 : 0) + '"'
        + ' oncontextmenu="return qsBubbleMenu(event,' + mid + ')"'
        + ' ontouchstart="qsBubbleHold(event,' + mid + ')" ontouchend="qsBubbleCancel()" ontouchmove="qsBubbleCancel()">'
        + escapeHtml(m.body) + "<time>" + escapeHtml(pending ? "发送中" : cmAgo(m.created_at)) + "</time></div>";
}

/* 气泡菜单：右击（桌面）或长按（手机）都能出，给"复制"和"撤回"。
   机主原话："对话框不能鼠标复制文本也不能右击删除修改"。 */
let qsHoldTimer = null;
function qsFindBubble(mid) { return cm.bubbles.find(b => Number(b.id) === Number(mid)); }
function qsHideMenu() { const m = cmEl("bubble-menu"); if (m) m.remove(); }
function qsBubbleHold(ev, mid) {
    const t = ev.currentTarget;
    qsHoldTimer = setTimeout(() => qsShowMenu(t, mid), 480);
}
function qsBubbleCancel() { if (qsHoldTimer) { clearTimeout(qsHoldTimer); qsHoldTimer = null; } }
function qsBubbleMenu(ev, mid) {
    ev.preventDefault();
    qsShowMenu(ev.currentTarget, mid, ev.clientX, ev.clientY);
    return false;
}
function qsShowMenu(anchor, mid, x, y) {
    qsHideMenu();
    const m = qsFindBubble(mid);
    if (!m || !anchor) return;
    const me = state.user && state.user.id;
    const mine = m.from_id === me;
    const menu = document.createElement("div");
    menu.id = "bubble-menu";
    menu.className = "bubble-menu";
    const canRecall = mine && !m.recalled_at && qsWithin(m.created_at, 300);
    menu.innerHTML = '<button type="button" onclick="qsCopyBubble(' + Number(mid) + ')">复制</button>'
        + (canRecall ? '<button type="button" onclick="recallDM(' + Number(mid) + ')">撤回</button>' : "");
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    const px = x == null ? (r.left + r.width / 2) : x;
    const py = y == null ? r.top : y;
    const w = menu.offsetWidth || 140;
    menu.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, px - w / 2)) + "px";
    menu.style.top = Math.max(8, py - (menu.offsetHeight || 42) - 8) + "px";
    setTimeout(() => document.addEventListener("click", qsHideMenu, { once: true }), 0);
}
function qsCopyBubble(mid) {
    const m = qsFindBubble(mid);
    qsHideMenu();
    if (m) qsCopy(m.body, "消息");
}
function qsWithin(stamp, seconds) {
    const t = Date.parse(String(stamp || "").replace(" ", "T"));
    return isFinite(t) && (Date.now() - t) <= seconds * 1000;
}
async function recallDM(mid) {
    qsHideMenu();
    try {
        await postApi("/api/chat/recall", { message_id: mid });
        const m = qsFindBubble(mid);
        if (m) m.recalled_at = new Date().toISOString();
        paintThread();
        callNativeToast("已撤回");
    } catch (e) { callNativeToast("撤回没成功：" + (e.message || "网络不通")); }
}

/* 气泡装扮：只改自己这一侧，存进 community_profile.bubble_theme */
const QS_THEMES = [["green", "墨绿"], ["blue", "蓝"], ["rose", "玫红"], ["ink", "黑"], ["amber", "琥珀"]];
function openBubbleTheme() {
    toolDialog("气泡装扮", '<div class="td-body"><p class="td-lead">只有你自己看到的气泡颜色，对方那边不变。</p>'
        + '<div class="theme-dots">' + QS_THEMES.map(t =>
            '<button type="button" class="theme-dot" data-t="' + t[0] + '" aria-label="' + t[1] + '气泡"'
            + ' aria-pressed="' + ((cm.myTheme || "green") === t[0] ? "true" : "false") + '" onclick="pickBubbleTheme(\'' + t[0] + '\')"></button>').join("")
        + "</div></div>");
}
async function pickBubbleTheme(t) {
    try {
        await postApi("/api/community/profile", { bubble_theme: t });
        cm.myTheme = t;
        const dlg = cmEl("account-tools-dialog");
        if (dlg && dlg.open) dlg.close();
        paintThread();
        callNativeToast("气泡换好了");
    } catch (e) { callNativeToast("没换成：" + (e.message || "网络不通")); }
}

async function loadOlderMessages() {
    if (!cm.thread || !cm.thread.cursor) return;
    const uid = cm.thread.partner.id;
    try {
        const r = await getJson("/api/chat/messages?with_user=" + uid + "&limit=30&cursor=" + cm.thread.cursor);
        cm.bubbles = (r.items || []).concat(cm.bubbles);
        cm.thread.more = !!r.more;
        cm.thread.cursor = r.next_cursor || 0;
        paintThread();
    } catch (e) { callNativeToast("更早的消息没读到"); }
}

async function sendDM() {
    const input = cmEl("dm-input");
    const text = (input && input.value || "").trim();
    if (!text || !cm.thread) return;
    if (!state.token) { openAuthModal(); return; }
    const uid = cm.thread.partner.id;
    const rid = "dm-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
    cm.pending[rid] = { rid, msg: { from_id: state.user && state.user.id, to_id: uid, body: text, created_at: "" } };
    input.value = "";
    paintThread();
    // 会话列表先就地顶上这一条：不然发完回到列表还是上一句，得像机主说的那样"刷新才更新"
    bumpConversation(uid, text, "me");
    wsSend({ t: "send", to: uid, text, request_id: rid });
    // 6 秒没等到回执就退回 HTTP 重发：request_id 一样，服务端只会把原来那条还回来，
    // 不会出现"看着丢了、其实发了两条"。
    setTimeout(() => {
        if (!cm.pending[rid]) return;
        delete cm.pending[rid];
        postApi("/api/chat/send", { to: uid, text, request_id: rid })
            .then(r => dmAck(rid, r.message))
            .catch(e => {
                callNativeToast("这条没发出去：" + (e.message || "网络不通"));
                paintThread();
            });
    }, 6000);
}

/** 本地顶一条会话摘要。列表和聊天窗共用这一份 cm.convs，
 *  所以发出去、收到、撤回三处都走它，不会再出现"要刷新才更新"。 */
function bumpConversation(uid, body, side) {
    const nowIso = new Date().toISOString().replace("T", " ").slice(0, 19);
    let conv = cm.convs.find(c => c.with && Number(c.with.id) === Number(uid));
    if (!conv) { loadMessages(); return; }
    conv.last_body = body;
    conv.last_at = nowIso;
    conv.last_from = side === "me" ? (state.user && state.user.id) : Number(uid);
    if (side !== "me") conv.unread = Number(conv.unread || 0) + 1;
    cm.convs.sort((a, b) => String(b.last_at || "").localeCompare(String(a.last_at || "")));
    if (cm.msgTab === "chats" && !cm.thread) renderMessages();
}

function dmAck(rid, message) {
    delete cm.pending[rid];
    if (message) {
        if (cm.thread && (message.from_id === cm.thread.partner.id || message.to_id === cm.thread.partner.id)) {
            if (!cm.bubbles.some(b => b.id === message.id)) cm.bubbles.push(message);
        }
        bumpConversation(message.from_id === (state.user && state.user.id) ? message.to_id : message.from_id,
            message.body, message.from_id === (state.user && state.user.id) ? "me" : "them");
    }
    paintThread();
}

/* ── WebSocket ──────────────────────────────────────────────── */
function wsOpen() { return !!(cm.ws && cm.ws.readyState === 1); }

function setWsState(state, why) {
    cm.wsState = state;
    const map = { connected: "实时连接：已连上", idle: "", connecting: "实时连接：在连…",
                  closed: "实时连接：断了，正在重试", unavailable: "实时连接：用不了，发消息走普通请求",
                  error: "实时连接：出错，发消息走普通请求" };
    const text = map[state] || "";
    cmText("cm-ws-state", text && why ? text + "（" + why + "）" : text);
}

async function connectChat() {
    if (!state.token) { setWsState("idle"); return; }
    if (wsOpen() || cm.wsState === "connecting") return;
    if (cm.wsRetry > 5) { setWsState("unavailable"); return; }
    cm.wsState = "connecting";
    try {
        const t = await postApi("/api/chat/ticket", {});
        const base = String(API_BASE || "").replace(/^http/, "ws");
        const sock = new WebSocket(base + t.ws_path + "?ticket=" + encodeURIComponent(t.ticket));
        cm.ws = sock;
        sock.onopen = () => { cm.wsRetry = 0; setWsState("connected"); };
        sock.onmessage = ev => handleWsEvent(ev);
        sock.onerror = () => setWsState("error");
        sock.onclose = () => {
            cm.ws = null;
            cm.wsRetry++;
            setWsState("closed");
            clearTimeout(cm.wsTimer);
            cm.wsTimer = setTimeout(connectChat, Math.min(30000, 2000 * cm.wsRetry));
        };
    } catch (e) {
        cm.wsRetry++;
        setWsState("unavailable", (e && e.message) || "握手失败");
    }
}

function wsSend(obj) {
    if (!wsOpen()) return false;
    try { cm.ws.send(JSON.stringify(obj)); return true; } catch (e) { return false; }
}

function handleWsEvent(ev) {
    let data = null;
    try { data = JSON.parse(ev.data); } catch (e) { return; }
    if (!data) return;
    const me = state.user && state.user.id;
    if (data.t === "msg" && data.message) {
        const m = data.message;
        if (cm.thread && (m.from_id === cm.thread.partner.id || m.to_id === cm.thread.partner.id)) {
            cm.bubbles.push(m);
            paintThread();
            if (m.from_id === cm.thread.partner.id) wsSend({ t: "read", with: cm.thread.partner.id });
        } else if (m.from_id !== me) {
            callNativeToast("有人私信你：" + String(m.body || "").slice(0, 20));
        }
        loadMessages();
    } else if (data.t === "ack") {
        dmAck(data.request_id || (data.message && data.message.request_id), data.message);
    } else if (data.t === "error") {
        if (data.client_key || data.request_id) dmAck(data.request_id || data.client_key, null);
        cmText("cm-ws-state", "这条没发出去：" + (data.detail || "服务端拒了"));
    } else if (data.t === "read") {
        if (cm.thread && data.by === cm.thread.partner.id) {
            cm.bubbles = cm.bubbles.map(b => Object.assign({}, b, { read_at: b.read_at || new Date().toISOString() }));
        }
    } else if (data.t === "recall") {
        // 对方撤回了：气泡要就地变成"对方撤回了一条消息"，不能等他重进会话才变
        cm.bubbles = cm.bubbles.map(b => Number(b.id) === Number(data.message_id)
            ? Object.assign({}, b, { recalled_at: data.recalled_at || "just now" }) : b);
        if (cm.thread) paintThread();
    }
}

async function toggleBlock() {
    if (!cm.thread) return;
    const uid = cm.thread.partner.id;
    const btn = cmEl("thread-block-btn");
    const on = !!(btn && btn.getAttribute("aria-pressed") === "true");
    try {
        await postApi("/api/chat/block", { with_user: uid, on: !on });
        if (btn) { btn.textContent = on ? "拉黑" : "取消拉黑"; btn.setAttribute("aria-pressed", on ? "false" : "true"); }
        callNativeToast(on ? "已经取消拉黑" : "已拉黑，对方不能再私信你");
    } catch (e) { callNativeToast("操作没生效：" + (e.message || "网络不通")); }
}

/* ── 我的主页与反馈 ─────────────────────────────────────────── */
async function loadMe() {
    if (!state.token) { cmText("me-name", "未登录"); return; }
    try {
        const [s, acc] = await Promise.all([getJson("/api/community/stats"),
                                            getJson("/api/account").catch(() => null)]);
        cm.stats = s;
        const u = (acc && acc.user) || state.user || {};
        cmText("me-name", u.nickname || u.username || "未登录");
        cmText("me-public-id", s.public_id || u.public_id || "—");
        const bio = acc && acc.profile && acc.profile.bio;
        cmText("me-bio", (acc && acc.bio) || bio || "还没有签名，点下面的「编辑签名」写一句");
        const region = s.region || (acc && acc.region) || "";
        cmText("me-region", region ? "属地 " + region : "属地未知（登录时按 IP 认，换网络后会自动跟上）");
        const disc = acc && typeof acc.discoverable !== "undefined" ? acc.discoverable : 1;
        const badge = cmEl("me-discoverable-badge");
        if (badge) badge.textContent = disc ? "已开启" : "已关闭";
        cmText("me-discoverable-hint", disc ? "别人可以用轻塑号或昵称搜到你" : "别人搜不到你，但你仍能看和发");
        const slot = cmEl("me-avatar");
        if (slot) {
            const url = acc && acc.avatar_url;
            slot.innerHTML = url ? '<img src="' + escapeHtml(API_BASE + url) + '" alt="我的头像">'
                : cmAvatarInner({ name: u.nickname || u.username });
        }
        paintMeAvatars();
        cm.myTheme = s.bubble_theme || "green";
        const meId = (state.user && state.user.id) || 0;
        const stats = [["posts", "帖子", s.posts], ["followers", "粉丝", s.followers],
                       ["following", "关注", s.following], ["likes", "获赞", s.likes_received]];
        const host = cmEl("me-stats");
        if (host) host.innerHTML = stats.map(x =>
            '<button type="button" class="me-stat" onclick="openStats(\'' + x[0] + "'," + meId + ')">'
            + '<b>' + Number(x[1]) + "</b><span>" + x[2] + "</span></button>").join("");
        paintNavBadge();
        syncFeedbackHints();
        const feed = await getJson("/api/community/feed?tab=mine&limit=6");
        const posts = cmEl("me-posts");
        if (posts) posts.innerHTML = (feed.items || []).map(function (x) { return cmCardHTML(x, false); }).join("");
        cmText("me-posts-state", (feed.items || []).length ? "" : "还没有发过帖子。");
    } catch (e) {
        cmText("me-name", "读不到：" + (e.message || "网络不通"));
    }
}

function paintMeAvatars() {
    const u = state.user || {};
    const inner = cmAvatarInner({ name: u.nickname || u.username });
    ["nav-me-avatar", "dnav-me-avatar"].forEach(id => {
        const el = cmEl(id);
        if (el) el.innerHTML = inner;
    });
    const slot = cmEl("cm-compose-avatar");
    if (slot) slot.innerHTML = inner;
}

/* 复制轻塑号：剪贴板在 WebView 里不一定给，失败就说失败并给出手抄的余地，
   不许不管结果一律弹"已复制"。 */
async function copyPublicId() {
    const el = cmEl("me-public-id");
    const id = ((el && el.textContent) || "").trim();
    if (!/^\d{8}$/.test(id)) { callNativeToast("轻塑号还没读到，稍等一下再复制"); return; }
    let done = false;
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(id);
            done = true;
        }
    } catch (e) { done = false; }
    if (!done) {
        try {
            const ta = document.createElement("textarea");
            ta.value = id;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.top = "-1000px";
            document.body.appendChild(ta);
            ta.select();
            done = document.execCommand("copy");
            document.body.removeChild(ta);
        } catch (e) { done = false; }
    }
    callNativeToast(done ? ("轻塑号 " + id + " 已复制") : ("复制没成功，可以照着抄：" + id));
}

async function editBio() {
    const cur = (cmEl("me-bio") || {}).textContent || "";
    const text = prompt("签名（最多 " + CM_LIMITS.bio + " 字）", cur === "还没有签名，点下面的「编辑签名」写一句" ? "" : cur);
    if (text === null) return;
    try {
        await postApi("/api/community/profile", { bio: text.trim() });
        callNativeToast("签名改好了");
        loadMe();
    } catch (e) { callNativeToast("没改掉：" + (e.message || "网络不通")); }
}

async function toggleDiscoverable() {
    const badge = cmEl("me-discoverable-badge");
    const on = badge && badge.textContent === "已开启";
    if (!confirm(on ? "关掉之后别人搜不到你，确定吗？" : "打开后别人可以用轻塑号或昵称找到你，确定吗？")) return;
    try {
        await postApi("/api/community/profile", { discoverable: on ? 0 : 1 });
        loadMe();
    } catch (e) { callNativeToast("没改掉：" + (e.message || "网络不通")); }
}

function setFeedbackKind(kind) {
    if (!["bug", "idea", "data", "other"].includes(kind)) return;
    cm.feedbackKind = kind;
    document.querySelectorAll("#fb-kinds .td-seg-btn").forEach(b =>
        b.setAttribute("aria-selected", b.getAttribute("data-kind") === kind ? "true" : "false"));
}

function syncFeedbackHints() {
    syncFeedbackCounters();
    const active = document.querySelector(".view-panel.active");
    cmText("fb-page", active ? active.id.replace("panel-", "") : "—");
    const build = cmEl("fb-build");
    if (build) build.textContent = typeof APP_BUILD !== "undefined" ? String(APP_BUILD) : "未知";
}

async function submitFeedback() {
    const t = cmEl("fb-text");
    const text = (t && t.value || "").trim();
    if (!text) { cmText("fb-result", "写一句再投，空的一条我这边没法看"); return; }
    const active = document.querySelector(".view-panel.active");
    try {
        const r = await postApi("/api/feedback", {
            kind: cm.feedbackKind, text,
            page: active ? active.id.replace("panel-", "") : "",
            contact: (cmEl("fb-contact").value || "").trim()
        });
        if (t) t.value = "";
        syncFeedbackCounters();
        cmText("fb-result", "收到了，编号 #" + r.id + "。处理进度在「我的 → 我的反馈」里能看。");
    } catch (e) {
        cmText("fb-result", "没投出去：" + (e.message || "网络不通") + "，内容还留着");
    }
}

async function openMyFeedback() {
    try {
        const r = await getJson("/api/feedback/mine");
        const names = r.status_names || {};
        const rows = (r.items || []).map(f =>
            '<li class="td-item"><span class="td-glyph">' + ({ bug: "🐞", idea: "💡", data: "🔢", other: "📝" }[f.kind] || "📝") + "</span>"
            + '<span class="td-item-main"><span class="td-item-title">' + escapeHtml(f.body) + "</span>"
            + '<span class="td-item-meta">' + escapeHtml(cmTime(f.created_at)) + " · " + escapeHtml(names[f.status] || f.status) + "</span>"
            + (f.reply ? '<span class="td-item-meta">回复：' + escapeHtml(f.reply) + "</span>" : "") + "</span></li>").join("");
        toolDialog("我的反馈", '<div class="td-body"><ul class="td-items">'
            + (rows || '<li class="td-empty">还没投过意见。在「我的」页最下面那一块就能投。</li>') + "</ul></div>");
    } catch (e) {
        callNativeToast("反馈列表没读到：" + (e.message || "网络不通"));
    }
}
