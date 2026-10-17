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
    try{const s=await postApi('/api/share/settings',{enabled:document.getElementById('share-enabled').checked,days:Number(document.getElementById('share-days').value),scope,rotate});state.publicUrl=s.public_url;updateUserUI(state.user.username);if(result){result.dataset.err='0';result.textContent=rotate?'已更新密钥，旧链接已失效；新链接请到「我的」里复制':'分享设置已保存';}
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

/** 顶栏那颗头像：没登录/没头像时保持原样，不塞一个假剪影进去。 */
function paintAccountBadge(){
    const host=document.getElementById('header-avatar-slot');
    if(!host)return;
    const url=accountCache&&accountCache.avatar_url;
    host.innerHTML=url?`<img class="header-avatar" src="${escapeHtml(API_BASE+url)}" alt="我的头像">`:'';
}

async function openAccountCenter(){
    if(!state.token){openAuthModal();return;}
    const a=await refreshAccount();
    if(!a){callNativeToast('个人中心没打开：请先登录');return;}
    const source=a.city_source==='gps'?'按定位就近认的':(a.city_source==='manual'?'你手填的':'来源未记');
    const cityLine=a.city?`${a.city}（${source}）`:'还没设置';
    const mailLine=a.mail==='up'?'邮件通道已接入，可以绑定邮箱找回密码'
                                 :'邮件通道未接入：'+(a.mail_why||'服务器上没有配置发信账号');
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
