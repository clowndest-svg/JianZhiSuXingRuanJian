let localGuidanceRows=[];
/* Account tools, explicit sharing, offline drafts and record correction. */
const localDay = () => { const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const draftKey = () => 'QINGSU_DRAFTS_'+(state.user ? state.user.username : 'guest');
function occurrenceNow(){const now=new Date();return {log_date:localDay(),occurred_at:now.toISOString(),timezone_offset_minutes:now.getTimezoneOffset()};}
let pendingMeal=null;
/* 记录省步骤（B03）：确认弹窗同时服务三条入口——现打原文、常用餐食、复制上一餐。
   共同点：都是"草稿"，只有点了「确认并保存」才入账。 */
const MEAL_SLOT_CN={breakfast:'早餐',lunch:'午餐',dinner:'晚餐',snack:'加餐'};
const MEAL_SLOT_KEY={'早餐':'breakfast','午餐':'lunch','晚餐':'dinner','加餐':'snack'};
/* 份量档：倍数是相对"这份餐原本的估算"，点完只是把数字填进那格，还能手改。 */
const MEAL_PORTIONS=[[0.5,'半份'],[1,'正常一份'],[1.5,'加一半'],[2,'双份']];
/* 这些来源是成分表/关键词算出来的，重记同一道菜让服务端再算一次就行，
   不必把数字当"用户填的"发回去——发回去反而丢掉宏量与来源（服务端会记 direct）。 */
const MEAL_REPARSE_SOURCES=['nutrition_kb','nutrition_kb_partial','nutrition_heuristic','legacy_estimate','direct_estimate'];

function mealConfirmHtml(){
    const p=pendingMeal;
    return `<div class="td-meal-head">
              <div class="td-meal-name">${escapeHtml(p.food_name)}</div>
              <div class="td-meal-why"><span class="td-chip">${Number(p.estimate)} kcal</span><span class="td-chip">${escapeHtml(MEAL_SLOT_CN[p.slotKey]||p.slot)}</span>${escapeHtml(p.why||'按名称估算，非称重结果')}</div>
            </div>
            ${p.origin?`<p class="td-note td-meal-origin">${escapeHtml(p.origin)}</p>`:''}
            <div class="td-group">
              <label class="td-field-row"><span class="td-field-label">本餐热量（kcal，可修正）</span><input id="meal-confirm-cal" type="number" min="0" max="10000" value="${Number(p.estimate)}" inputmode="numeric"></label>
            </div>
            <div class="td-group-label">份量快捷选择</div>
            <div class="td-portion-row" id="meal-portion-row" role="group" aria-label="份量快捷选择">
              ${MEAL_PORTIONS.map(([f,n])=>`<button type="button" class="td-portion" id="meal-portion-${String(f).replace('.','_')}" data-factor="${f}" aria-pressed="false" onclick="pickMealPortion(${f})">${n}</button>`).join('')}
            </div>
            <p id="meal-portion-note" class="td-status" role="status">倍的是「${escapeHtml(p.basisLabel || ('那份 ' + Number(p.estimate) + ' kcal'))}」；选完还能在上面那格直接改数字。</p>
            <div class="td-actions td-ai-row"><button type="button" class="td-btn-quiet" id="meal-ai-btn" onclick="estimateMealByAi()">让服务器模型估一下</button></div>
            <p id="meal-ai-result" class="td-status" role="status"></p>
            <p id="meal-ai-status" class="td-status" role="status">正在读取模型状态…</p>
            <div class="td-group-label">按包装称重换算（选填）</div>
            <div class="td-group">
              <label class="td-field-row"><span class="td-field-label">实际重量（g）</span><input id="meal-grams" type="number" min="0" step="0.1" inputmode="decimal" placeholder="例：260"></label>
              <label class="td-field-row"><span class="td-field-label">包装每 100g 热量（kcal）</span><input id="meal-per100" type="number" min="0" step="0.1" inputmode="decimal" placeholder="照包装背面抄"></label>
            </div>
            <p class="td-note">填了这两项就按重量换算覆盖上面那个数；手动热量只能算热量，推不出真实宏量。</p>
            <p id="meal-confirm-result" class="td-status" role="status"></p>
            <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="document.getElementById('account-tools-dialog').close()">先不记</button><button type="button" class="td-btn" onclick="confirmMealRecord()">确认并保存</button></div>`;
}

/** 开确认弹窗。pending 里没 occurrence 就当场取今天的发生时间。 */
function openMealConfirm(pending){
    pendingMeal=Object.assign({why:'按名称估算，非称重结果'},pending);
    if(!pendingMeal.log_date)Object.assign(pendingMeal,occurrenceNow());
    toolDialog('核对餐食与份量',mealConfirmHtml());
    refreshMealAiStatus();
    return pendingMeal;
}

async function refreshMealAiStatus(){
    const box=document.getElementById('meal-ai-status');
    if(!box)return;
    try{
        const r=await getJson('/api/ai/status');
        if(document.getElementById('meal-ai-status')!==box)return;
        const when=value=>value?new Date(Number(value)*1000).toLocaleString():'暂无';
        const status=!r.online_configured?'未配置':r.online_model==='untested'?'已配置，尚未跑通':r.online_model==='up'?'最近请求成功':'最近请求失败';
        box.textContent=`模型状态：${status}；上次成功：${when(r.online_last_success_at)}；模型：${r.online_last_success_model||'暂无'}；耗时：${r.online_last_elapsed_ms==null?'暂无':r.online_last_elapsed_ms+'ms'}；最近失败：${when(r.online_last_failure_at)}（${r.online_last_failure_kind||'无'}）。`;
    }catch(e){if(document.getElementById('meal-ai-status')===box)box.textContent='模型状态暂时读不到，尚未确认可用；可以手动填写热量。';}
}

/* 份量档只在"这一份有明确基准数字"时才折算；称重那两格填了就听称重的。 */
function pickMealPortion(factor){
    if(!pendingMeal)return;
    const base=Number(pendingMeal.base_cal);
    if(!Number.isFinite(base)){callNativeToast('这一份没有可折算的基准数字，直接在热量格里填就行');return;}
    const cal=Math.max(0,Math.round(base*Number(factor)));
    const box=document.getElementById('meal-confirm-cal');
    if(box)box.value=String(cal);
    pendingMeal.portion=Number(factor);
    for(const [f] of MEAL_PORTIONS){
        const chip=document.getElementById('meal-portion-'+String(f).replace('.','_'));
        if(!chip)continue;
        const on=Number(f)===Number(factor);
        chip.classList.toggle('is-on',on);
        chip.setAttribute('aria-pressed',on?'true':'false');
    }
    const note=document.getElementById('meal-portion-note');
    if(note)note.textContent=`已按 ${factor}× 折算成 ${cal} kcal（基准 ${base} kcal）。数字就在上面那格，还能自己改。`;
}

logNaturalMeal=async function(){
    const text=document.getElementById('input-meal-text').value.trim();if(!text){callNativeToast('请填写实际吃的餐食');return;}
    if(!state.token){openAuthModal();return;}
    const occurrence=occurrenceNow();
    const slotKey=state.selectedMealSlot;
    const slot=MEAL_SLOT_CN[slotKey]||'餐食';
    try{
        const result=await postApi('/api/food/preview',{food_name:text});
        openMealConfirm({food_name:text,slot,slotKey,estimate:Number(result.cal),base_cal:Number(result.cal),
            reparse:true,why:result.reason||'按名称估算，非称重结果',origin:'',...occurrence});
    }catch(e){
        // Preview is optional: preserve the user's original description as a draft.
        if(!e.status){const rows=readDrafts();const id=Date.now()+'-'+Math.random().toString(36).slice(2);rows.push({id,path:'/api/food/log',unsubmitted:true,body:{food_name:text,slot,request_id:id,...occurrence}});setDrafts(rows);callNativeToast('无法联网估算，原始餐食已存本机草稿，联网后可同步');}
        else callNativeToast(e.message);
    }
};

/* ---------- 最近常用餐食：只从本人历史长出来（B03） ---------- */
async function loadRecentMeals(){
    if(!state.token){state.recentMeals=[];renderRecentMeals();return state.recentMeals;}
    try{
        const d=await getJson('/api/food/recent?limit=12',{tag:'recent-meals'});
        state.recentMeals=Array.isArray(d.items)?d.items:[];
        state.recentMealsNote=d.scanned>=300?('只翻了你最近 '+d.scanned+' 笔餐食'):(d.note||'');
    }catch(e){
        // 读不到就明说读不到，绝不拿别人的热门菜或凭印象编一份"你常吃的"
        state.recentMeals=[];state.recentMealsNote='常用餐食没读到：'+((e&&e.message)||'网络不通');
    }
    renderRecentMeals();
    return state.recentMeals;
}

function renderRecentMeals(){
    const box=document.getElementById('recent-meal-list');
    if(!box)return;
    const rows=state.recentMeals||[];
    if(!rows.length){
        box.innerHTML=`<div class="rm-empty">${escapeHtml(state.recentMealsNote||'还没有可复用的餐食')}${state.recentMealsNote&&state.recentMealsNote.indexOf('还没')<0?'':' —— 记满一笔之后这里会长出你自己的常用菜'}</div>`;
        return;
    }
    box.innerHTML=`<div class="rm-lead">你自己常记的（不是全站热门）· ${escapeHtml(state.recentMealsNote||'按你记的次数排')}</div>`
        +rows.map((m,i)=>`<button type="button" class="rm-chip" id="recent-meal-${i}" data-name="${escapeHtml(m.food_name)}" aria-label="把 ${escapeHtml(m.food_name)} 带进确认弹窗，那份估算 ${escapeHtml(String(m.last_cal==null?'无读数':m.last_cal))} 千卡" onclick="useRecentMeal(${i})"><span class="rm-name">${escapeHtml(m.food_name)}</span><span class="rm-meta">记过 ${Number(m.times)} 次 · 上次 ${escapeHtml(String(m.last_log_date||'—'))} · ${escapeHtml(String(m.last_cal==null?'无读数':m.last_cal))} kcal</span></button>`).join('');
}

/** 点一下常用菜：带出菜名 + 上次那份估算，仍然只是草稿；不直接入账。 */
function useRecentMeal(index){
    const m=(state.recentMeals||[])[index];
    if(!m){callNativeToast('这一条常用餐食已经不在列表里了，重新打开「更多功能」刷一下');return;}
    if(!state.token){openAuthModal();return;}
    const slot=m.last_slot&&MEAL_SLOT_CN[m.last_slot]?m.last_slot:(m.last_slot||'餐食');
    const slotKey=MEAL_SLOT_KEY[slot]||state.selectedMealSlot;
    if(typeof selectMealSlot==='function')selectMealSlot(slotKey);
    const cal=Number(m.last_cal);
    const known=Number.isFinite(cal);
    document.getElementById('input-meal-text').value=m.food_name;
    openMealConfirm({food_name:m.food_name,slot,slotKey,
        estimate:known?cal:0,base_cal:known?cal:null,
        reparse:known&&MEAL_REPARSE_SOURCES.indexOf(m.last_source)>=0,
        why:known?('上次那笔的来源：'+tdSourceLabel(m.last_source)):'上次那笔没存下热量数字',
        origin:`这是你记过 ${Number(m.times)} 次的菜，最近一次 ${String(m.last_log_date||'—')}。现在还是草稿，点「确认并保存」才入账。`,
        ...occurrenceNow()});
}

/* ---------- 复制上一餐：只填草稿，不入账（B03） ---------- */
async function copyLastMeal(scope){
    if(!state.token){openAuthModal();return;}
    let row=null;
    if(scope==='today'){
        const d=state.mealDiary||[];   // 服务端按 id 倒序给，第 0 条就是今天最近那一笔
        row=d.length?d[0]:null;
        if(!row){callNativeToast('今天还没有一笔餐食可以复制');return;}
    }else{
        try{const r=await getJson('/api/records?kind=food&limit=1&offset=0',{tag:'copy-last-meal'});row=(r.rows&&r.rows[0])||null;}
        catch(e){callNativeToast('最近一餐没读到：'+((e&&e.message)||'网络不通'));return;}
        if(!row){callNativeToast('你还没有过餐食记录，没有可复制的上一餐');return;}
    }
    const slot=row.slot&&MEAL_SLOT_CN[row.slot]?row.slot:(row.slot||'餐食');
    const slotKey=MEAL_SLOT_KEY[slot]||state.selectedMealSlot;
    if(typeof selectMealSlot==='function')selectMealSlot(slotKey);
    const cal=Number(row.cal);
    const known=Number.isFinite(cal);
    document.getElementById('input-meal-text').value=row.food_name||'';
    openMealConfirm({food_name:(row.food_name||'').trim()||'未命名餐食',slot,slotKey,
        estimate:known?cal:0,base_cal:known?cal:null,
        reparse:known&&MEAL_REPARSE_SOURCES.indexOf(row.source)>=0,
        why:known?('抄的是 '+(row.log_date||'—')+' 那笔，来源：'+tdSourceLabel(row.source)):'那笔没存下热量数字',
        origin:`草稿：抄自${scope==='today'?'今天最近那一餐':'最近一餐'}（${String(row.log_date||'—')}）。改完点「确认并保存」才入账，现在云端什么都没动。`,
        ...occurrenceNow()});
}
/* 省步骤入口与权限中心改用事件绑定（C11：内联 onclick 要一路往下减，
   正式 CSP 才有落地的可能）。函数本身一个都没动，只是接线方式换了。 */
function bindMealQuickAndPermissionActions(){
    [['copy-last-today',()=>copyLastMeal('today')],
     ['copy-last-ever',()=>copyLastMeal('latest')],
     ['recent-meal-reload',()=>loadRecentMeals()],
     ['tools-permission-row',()=>openPermissionCenter()]]
    .forEach(([id,fn])=>{const el=document.getElementById(id);if(el)el.addEventListener('click',fn);});
}

/* 在线模型估热量。没配置时按钮上就写着没配置，不点出一个"看起来像答案"的数。 */
async function estimateMealByAi(){
    const out=document.getElementById('meal-ai-result');
    const btn=document.getElementById('meal-ai-btn');
    const grams=document.getElementById('meal-grams').value;
    if(out){out.dataset.err='0';out.textContent='在算，稍一下…';}
    let r=null;
    try{
        r=await postApi('/api/food/estimate',{food_name:(pendingMeal&&pendingMeal.food_name)||document.getElementById('input-meal-text').value.trim(),grams:grams?Number(grams):null});
    }catch(e){ if(out){out.dataset.err='1';out.textContent='估算请求没成功：'+((e&&e.message)||'未知原因');} refreshMealAiStatus(); return; }
    refreshMealAiStatus();
    if(!r||!r.ok){
        if(out){out.dataset.err='1';out.textContent=(r&&r.why)||'在线模型没给结果';}
        if(btn&&r&&r.status&&!r.status.ok)btn.textContent='模型通道不可用';
        return;
    }
    const cal=document.getElementById('meal-confirm-cal');
    if(cal)cal.value=String(r.cal);
    // 模型给的数是新的基准：份量档要按它折算，不能再按原来那份估算折
    if(pendingMeal){pendingMeal.base_cal=Number(r.cal);pendingMeal.reparse=false;}
    const src=(r.status&&r.status.source)||'模型';
    if(out){out.textContent='按 '+r.grams+' g 估到 '+r.cal+' kcal（'+(r.basis||'依据未给')+'，来源：'
        +src+'）——已填进上面那格，不对就直接改。';out.dataset.err='0';}
}
async function confirmMealRecord(){
    if(!pendingMeal)return;
    const body={food_name:pendingMeal.food_name,slot:pendingMeal.slot,log_date:pendingMeal.log_date,occurred_at:pendingMeal.occurred_at,timezone_offset_minutes:pendingMeal.timezone_offset_minutes};
    const grams=document.getElementById('meal-grams').value;const per100=document.getElementById('meal-per100').value;
    const edited=Number(document.getElementById('meal-confirm-cal').value);
    if(grams!==''||per100!==''){
        if(grams===''||per100===''||!Number.isFinite(Number(grams))||!Number.isFinite(Number(per100))||Number(grams)<=0||Number(per100)<0){callNativeToast('重量和每100g热量需同时填写有效数字');return;}
        body.cal=Math.round(Number(grams)*Number(per100)/100);
    }else if(edited!==pendingMeal.estimate)body.cal=edited;
    // 数字没动：常用菜/复制来的那份如果本来就出自成分表，就让服务端重新按名字解析，
    // 这样宏量和"来源"仍是同一条口径；手填过的数字（或模型给的）必须原样发回去，
    // 不能装作"没填"让服务端换个数出来。
    else if(!pendingMeal.reparse)body.cal=Number.isFinite(edited)?edited:pendingMeal.estimate;
    try{const result=await postApi('/api/food/log',body);document.getElementById('account-tools-dialog').close();document.getElementById('input-meal-text').value='';pendingMeal=null;callNativeToast(result.msg);await Promise.all([syncRemoteDashboard(),syncRemoteCharts(),loadRecentMeals()]);}
    catch(e){document.getElementById('meal-confirm-result').textContent=e.message;}
}
const readDrafts = () => {try{const rows=JSON.parse(localStorage.getItem(draftKey())||'[]');return Array.isArray(rows)?rows.filter(x=>x&&typeof x.id==='string'&&['/api/food/log','/api/workout/complete'].includes(x.path)&&x.body&&typeof x.body==='object'):[];}catch(e){return [];}};
function setDrafts(rows){localStorage.setItem(draftKey(),JSON.stringify(rows));paintDrafts();}
function paintDrafts(){const el=document.getElementById('draft-status');if(!el)return;const n=readDrafts().length;el.textContent=n?String(n):'已同步';el.dataset.empty=n?'0':'1';el.setAttribute('aria-label',n+('笔待同步草稿'));}
const tdRow=(title,o)=>{const c=o||{};return `<div class="td-row"><div class="td-row-main"><div class="td-row-title">${escapeHtml(title)}</div>${c.hint?`<div class="td-row-hint">${escapeHtml(c.hint)}</div>`:''}</div>${c.control||''}</div>`;};
const tdSwitch=(id,on,label)=>`<input class="td-switch" id="${id}" type="checkbox" ${on?'checked':''} aria-label="${escapeHtml(label)}">`;
const tdToggleRow=(id,on,title,hint)=>tdRow(title,{hint,control:tdSwitch(id,on,title)});
const tdValueRow=(title,value,hint)=>tdRow(title,{hint,control:`<span class="td-row-value">${escapeHtml(String(value))}</span>`});
const TD_SOURCE_CN={direct:'本人填写',manual:'本人填写',legacy_estimate:'按名称粗估',nutrition_kb:'成分表匹配',nutrition_heuristic:'按关键词粗估',nutrition_kb_partial:'部分食材已匹配成分表'};
const tdSourceLabel=source=>TD_SOURCE_CN[source]||'估算来源未知';
function openDraftManager(){
    const rows=readDrafts();
    const body=rows.length?rows.map((d,i)=>`<div class="td-item"><div class="td-item-main"><div class="td-item-title">${escapeHtml(d.body.food_name||d.body.plan_name||'训练记录')}</div><div class="td-item-meta">${d.unsubmitted?'尚未提交，可编辑餐食原文':'保存结果尚不确定；请先同步核对，再到历史记录修正，避免重复记账'} · ${escapeHtml(d.body.log_date||'日期待确认')}</div>${!d.body.log_date?`<label class="td-field"><span>记录发生日期</span><input type="date" id="draft-date-${i}" max="${localDay()}"><button type="button" onclick="confirmDraftDate(${i})">确认日期</button></label>`:''}${d.unsubmitted?`<label class="td-field"><span class="td-field-label">餐食原文</span><textarea id="draft-edit-${i}" maxlength="500">${escapeHtml(d.body.food_name||'')}</textarea><button type="button" class="td-mini" onclick="editUnsubmittedDraft(${i})">保存本机修改</button>`:''}</div><div class="td-item-acts"><button type="button" class="td-mini" onclick="discardLocalDraft(${i})">移除本机草稿</button></div></div>`).join('')+'<div class="td-actions"><button type="button" class="td-btn" onclick="syncOfflineDrafts()">同步并核对</button></div>':'<div class="td-empty">没有待同步草稿，本机记录都已对上云端</div>';
    toolDialog('本机待同步草稿',`<p class="td-lead">断网时新记的餐食与训练先留在本机，联网后同步即可入账；草稿不会重复记账。</p>${body}`);
}
function confirmDraftDate(index){
    const rows=readDrafts(),draft=rows[index];if(!draft)return;
    const value=document.getElementById('draft-date-'+index).value;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||value>localDay()){callNativeToast('请选择有效的发生日期');return;}
    draft.body.log_date=value;setDrafts(rows);openDraftManager();
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
    // Runtime native dialogs also need close/open observation: native focus
    // restoration can occur before the close event, leaving our background inert.
    if(typeof bindDialogAccessibility==='function')bindDialogAccessibility(d);
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
            +'<button type="button" role="tab" aria-selected="false" onclick="openBackfill()">补录</button>'
            +'<button type="button" role="tab" aria-selected="false" onclick="openChangeLog()">修正流水</button>';
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
    try{const r=await postApi(`/api/records/${recordKind}/${id}/update`,body);showRecordImpact(r,'已修正');
        await syncRemoteDashboard();await syncRemoteCharts();await openRecordManager(recordKind,recordOffset);}
    catch(e){callNativeToast(e.message);}
}
async function deleteHistoryRecord(id){
    if(!window.confirm('删除此记录并重新计算统计？'))return;
    try{const r=await postApi(`/api/records/${recordKind}/${id}/delete`,{});showRecordImpact(r,'已删除');
        await syncRemoteDashboard();await syncRemoteCharts();await openRecordManager(recordKind,recordOffset);}
    catch(e){callNativeToast(e.message);}
}

/* 修正与删除的流水：改掉的值要能读回来，不然"我记得昨天改过"没有凭据。 */
const CHANGE_OP_CN={update:'修正',delete:'删除'};
async function openChangeLog(offset=0){
    if(!state.token){openAuthModal();return;}
    try{
        const d=await getJson(`/api/records/changes?offset=${offset}&limit=20`);
        const names={food:'餐食',weight:'体重',workout:'训练'};
        const fieldOf=x=>x.kind==='food'?`${x.previous&&x.previous.cal} kcal`
            :x.kind==='weight'?`${x.previous&&x.previous.weight_jin} 斤`
            :`${x.previous&&x.previous.duration_minutes} 分钟`;
        const rows=d.rows.length?`<div class="td-items">${d.rows.map(x=>`<div class="td-item"><div class="td-item-main"><div class="td-item-title">${escapeHtml(String(x.created_at).slice(0,16).replace('T',' '))} · ${CHANGE_OP_CN[x.operation]||x.operation}${escapeHtml(names[x.kind]||x.kind)} #${x.record_id}</div><div class="td-item-meta">改之前那一份记的是 ${escapeHtml(fieldOf(x))}${x.previous&&x.previous.log_date?' · 归属日 '+escapeHtml(x.previous.log_date):''}${x.previous&&x.previous.food_name?' · '+escapeHtml(x.previous.food_name):''}</div></div></div>`).join('')}</div>`
            :'<div class="td-empty">还没有修正或删除过任何一条记录，所以现在没有流水。</div>';
        toolDialog('修正与删除流水',`<p class="td-lead">这里是你自己改过、删过的那些笔：每条留的是改动前那一份的值，用来核对"我到底改了什么"。界面只读，不能在这里撤销。</p>${rows}
          <div class="td-pager"><button type="button" class="td-mini" ${offset===0?'disabled':''} onclick="openChangeLog(${Math.max(0,offset-20)})">上一页</button><span class="td-pager-pos">${d.rows.length?`第 ${offset+1}–${offset+d.rows.length} 条`:'第 1 页'}</span><button type="button" class="td-mini" ${d.rows.length<20?'disabled':''} onclick="openChangeLog(${offset+20})">下一页</button></div>`);
    }catch(e){callNativeToast(e.message);}
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
        <label class="td-field-row"><span class="td-field-label">训练估算消耗（kcal）</span><input id="backfill-burned" type="number" min="0" max="10000" value="0" inputmode="numeric"><span class="td-field-hint">填 0 表示本次不计入消耗，不会自动补成 220 kcal</span></label>
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
        if(!draft.body.log_date){
            callNativeToast('旧草稿缺少发生日期，请先在草稿管理中确认日期');openDraftManager();return;
        }
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
    if(record&&!body.log_date)Object.assign(body,occurrenceNow());
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
logoutUser=async function(reload=true){localStorage.removeItem(draftKey());localStorage.removeItem('QINGSU_LAST_'+(state.user?.username||'guest'));return accountLogout(reload);};
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
    bindMealQuickAndPermissionActions();
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
    // 常用餐食是本人的账：换号/退出必须一起清掉，不能留在上一个人的列表里
    state.recentMeals=[];state.recentMealsNote='';
    if(typeof renderRecentMeals==='function')renderRecentMeals();
    const dialog=document.getElementById('account-tools-dialog');if(dialog)dialog.remove();
    accountCache=null;
}

// ================ 权限中心（B09）================
// 铁律：读不到就是"未知"，绝不画成 0 或"已关闭"。
// 0 次的含义是"确实一次都没打开"，"已关闭"的含义是"确实读到了 off"——
// 把未知冒充成这两种，用户就分不清"没发生"和"没权限"。
const PERM_TONE = { granted: 'on', denied: 'warn', blocked: 'off', prompt: 'off',
    unknown: 'off', absent: 'off', unsupported: 'off' };
const PERM_CN = {
    granted: '已授权', denied: '这次拒绝了（还能再问一次）',
    blocked: '永久拒绝：系统不再弹窗，只能去设置里开',
    prompt: '还没问过：用到时系统会弹窗',
    unknown: '未知（读不到实际状态）',
    absent: '这个运行环境没有这条通道',
    unsupported: '这个浏览器不支持该接口'
};

/** 统一成 {state, detail, why} —— 三条路必须分得开：读到了、读不到、这个环境根本没这条通道。 */
function permCall(read, name) {
    const b = window.AndroidBridge;
    if (!b || typeof b[name] !== 'function') {
        return { state: 'absent', detail: '', why: '这里没有 ' + name + ' 这个原生通道（网页版 or 旧安装包），所以状态是"读不到"，不是"已关闭"。' };
    }
    try {
        const v = read(b);
        if (v === true) return { state: 'granted', detail: '', why: '' };
        if (v === false) return { state: 'denied', detail: '', why: '原生接口回的是 false。' };
        return { state: 'unknown', detail: String(v == null ? '' : v), why: '原生接口回了个认不出来的值，不猜。' };
    } catch (e) {
        return { state: 'unknown', detail: '', why: '原生接口抛了：' + ((e && e.message) || '未知原因') };
    }
}

function permReadMicrophone() {
    const b = window.AndroidBridge;
    if (!b || typeof b.microphonePermissionState !== 'function') {
        return { state: 'absent', detail: '', why: '网页版读不到安卓的麦克风授权状态；在浏览器里发语音用的是浏览器自己的权限，两者不是一个东西。' };
    }
    let s = '';
    try { s = String(b.microphonePermissionState()); } catch (e) { return { state: 'unknown', detail: '', why: '读麦克风状态时抛异常了，不猜成"已关闭"。' }; }
    if (PERM_CN[s]) return { state: s, detail: '', why: s === 'granted' ? '' : '要发语音或通话，点右边的入口去开。' };
    return { state: 'unknown', detail: s, why: '原生回了个没见过的状态名，不替你判断。' };
}

function permReadLocation() {
    if (!navigator.geolocation) {
        return Promise.resolve({ state: 'unsupported', detail: '', why: '这个浏览器没有定位接口，城市只能手填。' });
    }
    const last = permLastTry('location');
    if (!navigator.permissions || typeof navigator.permissions.query !== 'function') {
        return Promise.resolve({ state: 'unknown', detail: '', why: '这里读不到 Permissions API 的真实状态'
            + (last ? '；上次实测是「' + last.label + '」（' + last.at + '）' : '，也还没实测过') });
    }
    return navigator.permissions.query({ name: 'geolocation' })
        .then(r => {
            const map = { granted: 'granted', denied: 'blocked', prompt: 'prompt' };
            const st = map[r.state];
            if (!st) return { state: 'unknown', detail: r.state, why: 'Permissions API 回了个认不出来的状态名。' };
            return { state: st, detail: r.state, why: st === 'granted' ? '' : '没授权时点定位只会走到"你拒绝了定位授权"，城市可以手填。' };
        })
        .catch(() => Promise.resolve({ state: 'unknown', detail: '', why: 'Permissions API 查询失败（部分 WebView 会禁这个查询）'
            + (last ? '；上次实测是「' + last.label + '」（' + last.at + '）' : '') }));
}

function permReadNotifications() {
    const sys = permCall(b => b.notificationsEnabled(), 'notificationsEnabled');
    let web = { state: 'absent', detail: '', why: '网页通知接口（Notification）在这个环境里不存在，App 的 WebView 就是这种情况。' };
    if (typeof Notification !== 'undefined' && Notification.permission) {
        const map = { granted: 'granted', denied: 'blocked', default: 'prompt' };
        web = { state: map[Notification.permission] || 'unknown', detail: Notification.permission, why: '' };
    } else if (typeof Notification !== 'undefined') {
        web = { state: 'unknown', detail: '', why: '有 Notification 接口但读不到 permission 字段。' };
    }
    return { sys, web };
}

function permReadUsage() {
    const r = permCall(b => b.usageAccessEnabled(), 'usageAccessEnabled');
    if (r.state === 'granted') {
        // 授权之后才去读真实条数；没授权绝对不许画 0 次
        let raw = null;
        try { raw = window.AndroidBridge.takeoutUsageToday ? window.AndroidBridge.takeoutUsageToday(TAKEOUT_PKGS) : null; } catch (e) { raw = null; }
        let n = null;
        try { const p = JSON.parse(raw || 'null'); if (p && p.apps) n = p.apps.reduce((s, x) => s + Number(x.count || 0), 0); } catch (e) { n = null; }
        return Object.assign(r, { detail: n === null ? '授权了，但今天的使用记录没读回来' : '今天打开外卖 App ' + n + ' 次' });
    }
    if (r.state === 'absent') return Object.assign(r, { detail: '今天点了外卖 App 几次这条读不到' });
    return Object.assign(r, { detail: '没授权时这里只会写"读不到"，不会写 0 次 —— 0 次的含义是"确实一次都没打开"。' });
}

function permReadReminder() {
    const b = window.AndroidBridge;
    if (!b || typeof b.reminderStatus !== 'function') {
        return { state: 'absent', detail: '每日提醒是安卓本地闹钟，网页版没有这条通道', why: '' };
    }
    try {
        const s = JSON.parse(b.reminderStatus());
        return { state: s.enabled ? 'granted' : 'denied',
            detail: '排在 ' + String(s.hour).padStart(2, '0') + ':' + String(s.minute).padStart(2, '0')
                + (s.enabled ? '（已开启）' : '（未开启）'), why: '' };
    } catch (e) {
        return { state: 'unknown', detail: '', why: '提醒状态读回来解析失败，不猜。' };
    }
}

const PERM_TRY_KEY = () => 'QINGSU_PERM_TRY_' + (state.user ? state.user.username : 'guest');
function permLastTry(kind) {
    try {
        const all = JSON.parse(localStorage.getItem(PERM_TRY_KEY()) || '{}');
        return all && all[kind] ? all[kind] : null;
    } catch (e) { return null; }
}
/** 记一次实测结果：Permissions API 读不到时，"上次点定位到底放没放行"是唯一凭据。 */
function permRecordTry(kind, label) {
    let all = {};
    try { all = JSON.parse(localStorage.getItem(PERM_TRY_KEY()) || '{}') || {}; } catch (e) { all = {}; }
    all[kind] = { label, at: new Date().toLocaleString('zh-CN', { hour12: false }) };
    try { localStorage.setItem(PERM_TRY_KEY(), JSON.stringify(all)); } catch (e) {}
}

function permRow(item) {
    const tone = PERM_TONE[item.state] || 'off';
    const badge = `<span class="td-badge" data-tone="${tone}" id="perm-badge-${item.id}">${escapeHtml(PERM_CN[item.state] || '未知')}</span>`;
    const lines = [item.detail, item.why,
        item.measure ? ('读取依据：' + item.measure) : '读取依据：这条没读到任何接口返回值']
        .filter(s => s && String(s).trim());
    return `<div class="td-row"><div class="td-row-main">
        <div class="td-row-title">${escapeHtml(item.title)} ${badge}</div>
        ${lines.map(t => `<div class="td-row-hint">${escapeHtml(String(t))}</div>`).join('')}
      </div>${item.action ? `<button type="button" class="td-mini" id="perm-act-${item.id}" onclick="${item.action}">${escapeHtml(item.actionLabel || '去开启')}</button>` : '<span class="td-row-hint">没有可点的开启入口</span>'}</div>`;
}

async function openPermissionCenter() {
    const mic = permReadMicrophone();
    const loc = await permReadLocation();
    const notif = permReadNotifications();
    const usage = permReadUsage();
    const remind = permReadReminder();
    const rows = [
        Object.assign(mic, { id: 'mic', title: '麦克风（发语音、语音通话）',
            measure: 'AndroidBridge.microphonePermissionState()',
            action: 'permGo("mic")', actionLabel: mic.state === 'granted' ? '再确认一次' : '去申请' }),
        Object.assign(loc, { id: 'loc', title: '定位（把城市认出来，给外卖排序）',
            measure: 'navigator.permissions.query({name:"geolocation"})',
            action: 'permGo("loc")', actionLabel: '用浏览器定位试一次' }),
        Object.assign(notif.sys, { id: 'notifsys', title: '系统通知（App 内的每日提醒能不能弹出来）',
            measure: 'AndroidBridge.notificationsEnabled()',
            action: 'permGo("notifsys")', actionLabel: '去系统通知设置' }),
        Object.assign(notif.web, { id: 'notifweb', title: '浏览器推送（网页版新消息提醒）',
            measure: typeof Notification !== 'undefined' ? 'Notification.permission' : '这个环境没有 Notification 接口',
            action: 'permGo("notifweb")', actionLabel: '去开浏览器提醒' }),
        Object.assign(usage, { id: 'usage', title: '使用情况访问（今天外卖 App 开了几次）',
            measure: 'AndroidBridge.usageAccessEnabled() + takeoutUsageToday()',
            action: 'permGo("usage")', actionLabel: '去系统设置开启' }),
        Object.assign(remind, { id: 'remind', title: '安卓本地每日提醒（本地闹钟）',
            measure: 'AndroidBridge.reminderStatus()',
            action: 'permGo("remind")', actionLabel: '去设置提醒时间' })
    ];
    toolDialog('权限中心', `<p class="td-lead">这里只报<b>真的读到的</b>状态。读不到就写"未知"并说明是哪一个接口没回话，不会拿 0 次、"已关闭"冒充读到的结果。</p>
      <div class="td-group">${rows.map(permRow).join('')}</div>
      <div class="td-group-label">离线通知能力，说清楚到哪一步</div>
      <div class="td-group"><p class="td-note">现在只有两条提醒通道：① 网页版的浏览器推送（要 HTTPS＋域名＋浏览器订阅成功，国内网络常常订阅不上）；② 安卓本地的每日提醒（系统闹钟，App 没被杀时按点到）。<b>没有接厂商推送（小米/华为/OPPO/vivo 那条离线通道）</b>，所以杀掉后台、重启手机之后不会响；这条不是"通知权限没开"，是能力本身还没有。</p></div>
      <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="openPermissionCenter()">重新读一次</button></div>`);
}

// ================ 自助账号处置（B09）================
// 只有"真的存在的通道"才做成按钮：
//   导出 = GET /api/export.csv（六张表，本人鉴权，本来就有）
//   注销 = POST /api/feedback(kind=data) + GET /api/feedback/mine 追踪状态
// 服务端没有面向本人账号的注销接口，所以这里绝不写成"已注销"，
// 也只说"提交了诉求、单号是多少、现在什么状态"。
const DELETION_TEXT = '申请注销我的轻塑账号。请核对我的数据依赖后按运维流程执行：'
    + '个人数据导出（A03）、社区与私信依赖、注销队列与媒体清理（A07）。'
    + '这条只是诉求单，不代表已经删除。';

async function qsExportMyData() {
    const box = document.getElementById('export-status');
    if (box) { box.removeAttribute('data-err'); box.textContent = '正在拉取 CSV（只含本人六张表的流水，不含私信正文与照片）…'; }
    let ok = false;
    try { ok = await exportMyData(); }
    catch (e) { ok = false; }
    if (box) {
        if (ok) { box.removeAttribute('data-err'); box.textContent = '导出已发起：文件名「轻塑我的记录.csv」。这份里没有私信正文、社区帖子和身材照片 —— 那部分要走运维侧完整导出。'; }
        else { box.setAttribute('data-err', '1'); box.textContent = '导出没成功：登录、网络或这条 CSV 接口的问题，按上面那条提示核对。'; }
    }
    return ok;
}

async function requestAccountDeletion() {
    if (!state.token) { openAuthModal(); return; }
    const box = document.getElementById('deletion-status');
    if (!window.confirm('这会以意见反馈（类型 data）提交一条注销申请。\n账号不会因为点了这个就自动删除，要等运维侧执行。\n确定提交？')) return;
    if (box) { box.removeAttribute('data-err'); box.textContent = '正在提交…'; }
    try {
        const r = await postApi('/api/feedback', { kind: 'data', text: DELETION_TEXT, page: 'account-center', contact: '' });
        if (box) {
            box.removeAttribute('data-err');
            box.textContent = '申请已提交，单号 #' + r.id + '。状态可以点下面「查看申请处理状态」跟；'
                + '这一步不等于注销完成，运维那边做完才是。';
        }
        callNativeToast('注销申请已提交（单号 #' + r.id + '），还没删除任何数据');
    } catch (e) {
        if (box) { box.setAttribute('data-err', '1'); box.textContent = '申请没提交出去：' + ((e && e.message) || '未知原因'); }
        callNativeToast('注销申请没提交出去：' + ((e && e.message) || '网络不通'));
    }
}

async function openDeletionRequests() {
    if (!state.token) { openAuthModal(); return; }
    try {
        const d = await getJson('/api/feedback/mine');
        const rows = (d.items || []).filter(x => x.kind === 'data');
        const body = rows.length ? `<div class="td-items">${rows.map(x => `<div class="td-item"><div class="td-item-main"><div class="td-item-title">单号 #${Number(x.id)} · ${escapeHtml(d.status_names[x.status] || x.status || '状态未知')}</div><div class="td-item-meta">提交于 ${escapeHtml(String(x.created_at || '').slice(0, 16))}${x.replied_at ? ' · 回复于 ' + escapeHtml(String(x.replied_at).slice(0, 16)) : ' · 还没回复'}${x.reply ? '<br>回复：' + escapeHtml(x.reply) : ''}</div></div></div>`).join('')}</div>`
            : '<div class="td-empty">还没有注销申请。没提交过就不会有单号，这里不编一条"处理中"给你看。</div>';
        toolDialog('注销申请与处理状态', `<p class="td-lead">这是你自己提过的数据类诉求单（含注销）。状态由后台运维改：待处理 / 处理中 / 已处理 / 暂不做。</p>${body}
          <p class="td-note">「已处理」指这条诉求被处理完；账号真正注销要运维侧走双因子的注销队列（A07），这个界面里没有那一步的凭据。</p>`);
    } catch (e) { callNativeToast('申请状态没读到：' + ((e && e.message) || '网络不通')); }
}

function permGo(id) {
    if (id === 'mic') {
        if (window.AndroidBridge && typeof window.AndroidBridge.requestMicrophonePermission === 'function') {
            permRecordTry('mic', '已发起系统弹窗');
            window.AndroidBridge.requestMicrophonePermission();
            callNativeToast('系统弹窗已发起，回来点「重新读一次」');
        } else callNativeToast('网页版申请不了安卓权限；浏览器会在真正录音那一刻自己问');
        return;
    }
    if (id === 'loc') {
        permRecordTry('loc', '点过一次定位入口');
        if (typeof useMyLocation === 'function') useMyLocation();
        else callNativeToast('这个页面没有定位入口');
        return;
    }
    if (id === 'notifsys') {
        if (typeof openSystemNotifSettings === 'function') openSystemNotifSettings();
        return;
    }
    if (id === 'notifweb') {
        if (typeof Notification === 'undefined') { callNativeToast('这个环境没有浏览器通知接口，开不了浏览器推送'); return; }
        permRecordTry('notifweb', '点过浏览器提醒');
        if (typeof openWebPush === 'function') { openWebPush(); return; }
        callNativeToast('浏览器提醒入口在「我的」页，这里没接到那个函数');
        return;
    }
    if (id === 'usage') {
        if (typeof requestUsageAccess === 'function') requestUsageAccess();
        return;
    }
    if (id === 'remind') {
        if (typeof openReminderSettings === 'function') openReminderSettings();
        return;
    }
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
    // 通话来电只需要实时连接，不要求用户先停在消息页；登录后就把 WS 拉起来。
    try { if (typeof connectChat === "function") connectChat(); } catch (e) {}
    try{
        accountCache=await getJson('/api/account');
        if(accountCache)rememberAvatar(accountCache.avatar_url||'');
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
    用 Array.from 而不是 [0]：昵称可能以 emoji 开头，直接按下标取会切出半个码元变成乱码。
    头像地址本地留一份：冷启动时 /api/account 还没回来，先用上次的地址，
    否则每次进 App 都会先闪一下字母章。 */
function cachedAvatar(){ try{ return localStorage.getItem('QINGSU_AVATAR_DATA')||''; }catch(e){ return ''; } }
function rememberAvatar(url){
    try{
        if(!url){ localStorage.removeItem('QINGSU_AVATAR_DATA'); localStorage.removeItem('QINGSU_AVATAR_SRC'); return; }
        // 头像走签名链接，15 分钟就过期，直接缓存 URL 过一晚就是坏图。
        // 缓存成 data URL：冷启动先画这一张，账号接口回来后再用新的。
        const full=/^(data:|https?:)/.test(url)?url:API_BASE+url;
        if(/^data:image\//.test(full)){ try{localStorage.setItem('QINGSU_AVATAR_DATA',full);}catch(e){} return; }
        const path=full.split('?')[0];
        // 同一张头像不重复下载；签名串每次刷新都会变，只比路径
        if(localStorage.getItem('QINGSU_AVATAR_SRC')===path&&cachedAvatar())return;
        fetch(full).then(r=>r.ok?r.blob():null).then(blob=>{
            if(!blob||blob.size>300*1024)return;
            const reader=new FileReader();
            reader.onload=()=>{
                try{
                    localStorage.setItem('QINGSU_AVATAR_DATA',String(reader.result||''));
                    localStorage.setItem('QINGSU_AVATAR_SRC',path);
                }catch(e){}
            };
            reader.readAsDataURL(blob);
        }).catch(()=>{});
    }catch(e){}
}
function paintAccountBadge(){
    const host=document.getElementById('header-avatar-slot');
    const u=(accountCache&&accountCache.user)||state.user||{};
    const avatar=((accountCache&&accountCache.avatar_url)||cachedAvatar()||'');
    const who={name:String(u.nickname||u.username||'').trim(),avatar};
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
    const usr=a.user||{};
    const nick=String(usr.nickname||'').trim();
    // 注册时没填昵称，服务端会把登录名直接当昵称存下来；这两种情况要提醒，
    // 否则用户看到主页那串英文账号，会以为"昵称根本改不动"。
    const sameNick=!!nick&&nick===String(usr.username||'').trim();
    toolDialog('个人中心',`
      <p class="td-lead">头像、昵称、密码、邮箱找回、所在城市与忌口都在这。忌口会真的改变外卖与食谱的推荐顺序；城市是按坐标就近认的粗匹配，不对就手改。</p>
      <div class="td-group-label">头像与昵称</div>
      <div class="td-group">
        <div class="td-identity">
          <div class="td-avatar-cell" id="td-avatar-cell">${qsAvatarCell()}</div>
          <div class="td-identity-main">
            <div class="td-identity-name">${escapeHtml(nick||'还没设置昵称')}${nick?'':'<span class="td-id-tag td-id-tag-warn">未设置</span>'}</div>
            <div class="td-identity-meta"><span class="td-id-tag">登录名</span><span class="td-id-login">${escapeHtml(usr.username||'—')}</span></div>
            <div class="td-identity-meta">轻塑号 <b>${escapeHtml(usr.public_id||'—')}</b> · ${escapeHtml(String(usr.created_at||'').slice(0,10))||'—'} 加入 · ${(a.region||'').trim()?'属地 '+escapeHtml(a.region.trim()):'属地未知'}</div>
            <div class="td-identity-bio">${escapeHtml((a.bio||'').trim()||'还没有签名，到「我的」页点编辑签名')}</div>
          </div>
        </div>
        <label class="td-field-row"><span class="td-field-label">昵称（20 字内，主页与帖子旁显示的就是它）</span>
          <input id="nick-input" maxlength="20" placeholder="例：小田要瘦十斤" value="${escapeHtml(nick)}">
          <span class="td-field-hint">${sameNick?'现在昵称和登录名一模一样。登录名改不了也不用给别人看，把昵称改成一个好记的名字。':'登录名是账号本身，不能改；主页大字位置只显示昵称，不会再拿登录名顶替。'}</span></label>
        <div class="td-actions"><button type="button" class="td-btn" onclick="saveNickname()">保存昵称</button></div>
        <p id="nick-status" class="td-status" role="status"></p>
        <div class="td-field-row"><span class="td-field-label">头像图片（JPEG / PNG / WebP，4MB 内）</span>
            <input type="file" id="avatar-file" accept="image/*" class="file-hidden" onchange="qsPickAvatarName(this)">
            <span class="td-file-line"><button type="button" class="td-btn td-btn-quiet" onclick="document.getElementById('avatar-file').click()">选择图片</button>
            <span class="td-file-name" id="avatar-file-name">未选择</span>
            <button type="button" class="td-btn td-file-upload" onclick="uploadAvatar()">上传头像</button></span></div>
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
      <div class="td-group">${AVOID_TAGS.map(k=>tdToggleRow('avoid-'+k,(a.avoid_tags||[]).indexOf(k)>=0,AVOID_CN[k][0],AVOID_CN[k][1])).join('')}
        <div class="td-actions"><button type="button" class="td-btn" onclick="saveAvoidTags()">保存忌口</button></div>
        <p id="avoid-status" class="td-status" role="status"></p></div>
      <div class="td-group-label">邮箱与找回密码</div>
      <div class="td-group">
        ${tdValueRow('已绑邮箱',a.email_bound?a.email_masked+(a.email_verified?'（已验证）':'（未验证）'):'未绑定')}
        <label class="td-field-row"><span class="td-field-label">邮箱</span><input id="bind-email" type="email" maxlength="200" placeholder="用于找回密码"></label>
        <label class="td-field-row"><span class="td-field-label">验证码</span><input id="bind-code" inputmode="numeric" maxlength="6" placeholder="先点“发验证码”，再填收到的 6 位数字"></label>
        <div class="td-actions">
          <button type="button" class="td-btn-quiet" id="bind-code-btn" onclick="sendBindCode()">发验证码</button>
          <button type="button" class="td-btn" onclick="verifyBindCode()">绑定并验证</button>
        </div>
        <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="openForgotPassword()">用邮箱验证码重置密码</button></div>
        <p class="td-note">验证码 10 分钟有效，60 秒内只能发一次。重置密码会要求填新密码，成功后所有设备下线。</p>
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
      <div class="td-group-label">数据与账号处置（自助）</div>
      <div class="td-group">
        <div class="td-row"><div class="td-row-main">
          <div class="td-row-title">导出我的数据</div>
          <div class="td-row-hint">走已有的 /api/export.csv：饮食、体重、训练、饮水、门禁事件、周期六张表，UTF-8 BOM 的 CSV。私信正文、社区帖子与身材照片不在这份里 —— 后台那份完整导出（A03）是运维侧双因子接口，没有对普通账号开放。</div></div>
          <button type="button" class="td-mini" id="qs-export-btn" onclick="qsExportMyData()">导出 CSV</button></div>
        <p id="export-status" class="td-status" role="status">还没导出过。</p>
        <div class="td-row"><div class="td-row-main">
          <div class="td-row-title">申请注销账号</div>
          <div class="td-row-hint">点「提交注销申请」只是把你这条诉求写进意见反馈（kind=data）并留个单号，方便追踪处理状态；账号不会因此自动删除。服务端目前<b>没有</b>给用户自助用的删除/注销接口，真正执行注销仍然只有运维侧那条双因子通道（A07：先算依赖、媒体清理、再删）。缺的那一层是「本人身份再次验证 + 自助注销任务队列」，补上之前这里不会假装能一键注销。</div></div>
          <button type="button" class="td-mini" id="qs-delete-btn" onclick="requestAccountDeletion()">提交注销申请</button></div>
        <p id="deletion-status" class="td-status" role="status">还没提交过申请。</p>
        <div class="td-actions"><button type="button" class="td-btn-quiet" onclick="openDeletionRequests()">查看申请处理状态</button></div>
      </div>
      <div class="td-group-label">账号</div>
      <div class="td-group">
        ${tdValueRow('当前登录',escapeHtml(((a.user&&(a.user.nickname||a.user.username))||state.user&&(state.user.nickname||state.user.username)||'—')))}
        <div class="td-actions">
          <button type="button" class="td-btn" onclick="switchAccount()">切换账号</button>
          <button type="button" class="td-btn-danger" onclick="logoutUser()">退出登录</button>
        </div>
        <p class="td-note">切换账号会退出当前账号并直接弹出登录框，不用等整页刷新。</p>
      </div>
      <div class="td-group-label">权限中心</div>
      <div class="td-group">
        <div class="td-row"><div class="td-row-main">
          <div class="td-row-title">麦克风 / 定位 / 通知 / 使用情况</div>
          <div class="td-row-hint">看每一条到底读到的是什么状态，以及从哪儿开。</div></div>
          <button type="button" class="td-mini" onclick="openPermissionCenter()">打开</button></div>
      </div>
      <div class="td-group-label">去过的城市</div>
      <div class="td-group">${(a.cities_seen||[]).length
        ?(a.cities_seen||[]).map(x=>tdValueRow(x.city,'首次 '+String(x.first_seen).slice(0,10)+' · 最近 '+String(x.last_seen).slice(0,10))).join('')
        :'<p class="td-note">还没有第二个城市。出差或旅行时定位到别处，这里会多一行——换城市最容易打乱点单，回来能对照看。</p>'}</div>
    `);
}

/** 个人中心头像那一格：有头像放图，没有留明确占位，重画时整格替换，
    这样"第一张头像上传成功"也能立刻看见，不必重开弹窗。 */
function qsAvatarCell(){
    const url=accountCache&&accountCache.avatar_url;
    return url?`<img class="td-avatar" src="${escapeHtml(API_BASE+url)}" alt="当前头像">`
              :'<span class="td-avatar td-avatar-empty">还没头像</span>';
}

async function saveNickname(){
    const box=document.getElementById('nick-input');
    const nick=(box&&box.value||'').trim();
    if(!nick){tdStatus('nick-status','昵称不能是空的',true);return;}
    try{
        const r=await postApi('/api/account/nickname',{nickname:nick});
        tdStatus('nick-status',r.msg||'昵称已更新');
        await refreshAccount();
        const nameEl=document.querySelector('.td-identity-name');
        if(nameEl)nameEl.textContent=nick;
        // 「我的」页那张卡片就在弹窗后面，改完不重画就成了"说改了但看到的还是旧的"
        const me=document.getElementById('me-name');
        if(me)me.textContent=nick;
    }catch(e){tdStatus('nick-status',e.message||'昵称没改掉',true);}
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
        const cell=document.getElementById('td-avatar-cell');
        if(cell)cell.innerHTML=qsAvatarCell();
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
    const btn=document.getElementById('bind-code-btn');
    if(btn&&btn.disabled)return;
    try{
        const r=await postApi('/api/account/email/send',{email});
        tdStatus('email-status',r.msg+'（'+r.ttl_minutes+' 分钟内有效）');
        startCodeCountdown(btn);
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
async function publicPost(path, body){
    // 免登录链路：不带鉴权头，但超时、错误形状与其余请求同一口径（底座 auth:false 分支）
    return requestBase(path, { method: "POST", body, auth: false });
}

async function openForgotPassword(){
    toolDialog('找回密码',`
      <p class="td-lead">只有<b>已绑定并通过验证</b>的邮箱能走这条路。重置成功后所有设备都会下线。</p>
      <div class="td-group-label">第 1 步：发验证码</div>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">注册时绑定的邮箱</span><input id="fg-email" type="email" maxlength="200"></label>
        <div class="td-actions"><button type="button" class="td-btn" id="fg-code-btn" onclick="sendForgotCode()">发送验证码</button></div>
      </div>
      <div class="td-group-label">第 2 步：填验证码与新密码</div>
      <div class="td-group">
        <label class="td-field-row"><span class="td-field-label">验证码</span><input id="fg-code" inputmode="numeric" maxlength="6"></label>
        <label class="td-field-row"><span class="td-field-label">新密码（至少 8 位）</span><input id="fg-pw" type="password" maxlength="200" autocomplete="new-password"></label>
        <label class="td-field-row"><span class="td-field-label">再输一遍新密码</span><input id="fg-pw2" type="password" maxlength="200" autocomplete="new-password"></label>
        <div class="td-actions"><button type="button" class="td-btn" onclick="submitForgotReset()">重置密码</button></div>
        <p class="td-note">验证码 60 秒内只能发一次；重置成功后所有设备下线，请用新密码登录。</p>
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
    const btn=document.getElementById('fg-code-btn');
    if(btn&&btn.disabled)return;
    try{
        const r=await publicPost('/api/account/forgot',{email});
        // 服务端对"绑过"和"没绑过"给同一句话，这里也不许加区别
        tdStatus('fg-status',r.msg);
        startCodeCountdown(btn);
    }catch(e){tdStatus('fg-status',e.message||'验证码没发出去',true);}
}

async function submitForgotReset(){
    const email=((document.getElementById('fg-email')||{}).value||'').trim();
    const code=((document.getElementById('fg-code')||{}).value||'').trim();
    const pw=((document.getElementById('fg-pw')||{}).value||'');
    const pw2=((document.getElementById('fg-pw2')||{}).value||'');
    if(!email||!code){tdStatus('fg-status','邮箱和验证码都要填',true);return;}
    if(pw.length<8){tdStatus('fg-status','新密码至少 8 位',true);return;}
    if(pw!==pw2){tdStatus('fg-status','两次输入的新密码不一样',true);return;}
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
const CM_LIMITS = { title: 20, post: 1000, postImages: 9, comment: 500, dm: 1000, bio: 60, feedback: 800, cmtImages: 3 };
const CM_TOOLS = ["recipes", "workout", "body", "takeout", "charts", "gemini"];
let cmGeneration = 0;
const cm = {
    feed: "latest", items: [], cursor: 0, more: false, loading: false, loaded: false,
    msgTab: "chats", convs: [], notices: [], loadingMsg: false, msgAgain: false,
    thread: null, bubbles: [], pending: {}, failed: {},
    ws: null, wsState: "idle", wsRetry: 0, wsTimer: null, wsBlind: false,
    stats: null, feedbackKind: "bug", images: [],
    myTheme: "green", unreadTotal: 0, postId: 0,
    // 评论草稿态：配图、@ 到的人、当前展开的面板，换帖子或发出去都要清干净
    cmtImages: [], cmtMentions: [], cmtPanel: "", atRows: [], atQuery: "", atSeq: 0, stickers: null
};

/* 换账号必须把社区与私信的内存状态一起清掉：
   上一版的教训是 sessionGeneration 只管住了请求，界面还留着上一个人的列表。 */
function resetCommunity() {
    cmGeneration++; dmCleanup();
    try { dmCallReset(); } catch (e) {}
    if (cm.ws) { try { cm.ws.onclose = null; cm.ws.close(); } catch (e) {} cm.ws = null; }
    clearTimeout(cm.wsTimer);
    cm.wsRetry = 0;
    cm.wsState = "idle";
    cm.feed = "latest"; cm.items = []; cm.cursor = 0; cm.more = false;
    cm.loading = false; cm.loaded = false; cm.loadingMsg = false;
    cm.convs = []; cm.notices = []; cm.thread = null; cm.bubbles = [];
    cm.pending = {}; cm.failed = {}; cm.stats = null; cm.images = []; cm.myTheme = "green";
    cm.unreadTotal = 0; cm.postId = 0; cm.wsBlind = false;
    cm.cmtImages = []; cm.cmtMentions = []; cm.cmtPanel = ""; cm.atRows = []; cm.atQuery = "";
    qsCloseAllPages();
    paintNavBadge();
}

function qsSameId(a, b) {
    const x = Number(a), y = Number(b);
    return isFinite(x) && isFinite(y) && x === y;
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
    // 顶栏右侧槽位与底栏都归每一页自己管：不清的话，上一页的「私信」会挂在
    // 统计页头上——按钮还在，点了却没有上下文。
    const slotEl = cmEl("pl-slot");
    if (slotEl) slotEl.innerHTML = "";
    cmText("pl-title", typeof top.title === "function" ? top.title() : top.title);
    top.render(top.arg);
}

function openPage(name, arg) {
    const def = QS_PAGE_DEF[name];
    if (!def) return;
    const top = QS_PAGES[QS_PAGES.length - 1];
    // Repeated taps on the current avatar/name must not create duplicate
    // history entries that force the user to press Back several times.
    if (top && top.name === name && String(top.arg == null ? "" : top.arg) === String(arg == null ? "" : arg)) {
        return false;
    }
    if (top && top.name === "dm") { dmCleanup(); cm.thread = null; }
    QS_PAGES.push({ name: name, arg: arg, title: def.title, render: def.render });
    // 给每一页补一条历史记录：安卓的返回键/侧滑手势走的是 WebView.canGoBack，
    // 没有这条记录时它只能退出 App（机主截图里的"再按一次退出"）。
    try { history.pushState({ qsPage: QS_PAGES.length }, ""); } catch (e) {}
    qsRenderTop();
    return true;
}

/** 关掉最上面一页；栈空时整层收起。返回 true 表示这一层还开着（给硬件返回键判断用）。 */
function closePage(fromHistory) {
    if (!QS_PAGES.length) return false;
    if (!fromHistory) {
        // 点顶栏的返回时也先退历史，真正的出栈交给 popstate——
        // 否则历史里会留下一条"已经关掉的页"，再按返回要空按一次。
        if (history.state && history.state.qsPage) { history.back(); return true; }
    }
    if (QS_PAGES[QS_PAGES.length - 1].name === "dm") { dmCleanup(); cm.thread = null; }
    QS_PAGES.pop();
    if (QS_PAGES.length) { qsRenderTop(); return true; }
    const layer = cmEl("page-layer");
    if (layer) { layer.hidden = true; cmEl("pl-body").innerHTML = ""; cmEl("pl-foot").innerHTML = ""; }
    document.body.classList.remove("qs-page-open");
    return false;
}

/** 真在页面里（不是被压在栈底下）才算"当前页"，切 tab 时要先把栈清空。 */
function qsPageOpen() { return QS_PAGES.length > 0; }
function qsCloseAllPages() {
    dmCleanup(); cm.thread = null;
    const depth = QS_PAGES.length;
    while (QS_PAGES.length) { QS_PAGES.pop(); }
    // 切 tab 时把页面层整个收掉：历史也要一起退回去，不然返回键会按到"幽灵页"
    if (depth) { try { history.go(-depth); } catch (e) {} }
    const layer = cmEl("page-layer");
    if (layer) layer.hidden = true;
    document.body.classList.remove("qs-page-open");
}

window.addEventListener("popstate", function () {
    const depth = (history.state && history.state.qsPage) || 0;
    while (QS_PAGES.length > depth) closePage(true);
});

function qsSetFoot(html) {
    const foot = cmEl("pl-foot");
    if (!foot) return;
    foot.innerHTML = html || "";
    foot.hidden = !html;
    // 私聊与评论的输入区都是竖排（工具栏 + 面板 + 输入），别把帖子详情那种单行输入也带成竖排
    foot.classList.toggle("dm-foot", !!html && html.indexOf("dm-tools") >= 0);
    foot.classList.toggle("cmt-foot", !!html && html.indexOf("cmt-tools") >= 0);
}

/** 复制按钮的通用出口：值放在 data-copy 里，避免把内容拼进 onclick 时踩引号转义。 */

/** 统计格（帖子/粉丝/关注/获赞）。抽成一个纯函数：两处各写一遍时，
 *  下标写串会同时坏两遍，而接口是对的——只有渲染层能看出来。 */
function qsStatsHTML(rows, uid) {
    return rows.map(function (r) {
        var v = Number(r[2]);
        return '<button type="button" class="me-stat" onclick="openStats(\'' + r[0] + "'," + Number(uid) + ')">'
            + '<b>' + (isFinite(v) ? v : 0) + "</b><span>" + escapeHtml(String(r[1])) + "</span></button>";
    }).join("");
}

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
    if (url) return '<img src="' + escapeHtml(/^(data:|https?:)/.test(url) ? url : API_BASE + url) + '" alt="">';
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

/* 广场卡片上的数字从 cm.items 现写：点赞之后只改内存不改 DOM，
   界面就会一直停在旧值，用户以为没生效又点一次。
   r160 起卡片只有点赞（评论数与收藏收进详情页，照小红书的卡片密度）。 */
function syncCardCounts(postId) {
    const item = cm.items.find(x => x.id === Number(postId));
    const card = document.getElementById("post-" + postId);
    if (!item || !card) return;
    const num = card.querySelector("[data-like]");
    if (num) num.textContent = String(Number(item.like_count));
    const like = card.querySelector(".cm-act");
    if (like) like.setAttribute("aria-pressed", item.liked_by_me ? "true" : "false");
}

/* 小红书式卡片：封面在上（首图，没图就用一句文字卡垫底）、标题两行、
   底下一行作者 + 点赞。以前是"头像昵称在最上 + 整段正文 + 九宫格"，
   一屏只能容两条，看着像时间线不像广场。 */
function cmCardHTML(p, withId) {
    const imgs = p.images || [];
    const thumbs = p.image_thumbs || [];
    const hasImg = imgs.length > 0;
    // 封面用 480px 缩略图：原图动辄 200~600KB，两列瀑布流一屏就是上 MB。
    const coverSrc = API_BASE + (thumbs[0] || imgs[0] || "");
    const fullSrc = API_BASE + (imgs[0] || "");
    const cover = hasImg
        ? '<img src="' + escapeHtml(coverSrc) + '" alt="帖子配图" loading="lazy" decoding="async"'
          + ' onclick="event.stopPropagation();viewPostImage(\'' +
          escapeHtml(fullSrc).replace(/'/g, "%27") + '\')"'
          + ' ondblclick="dblLikePost(' + p.id + ',this)">'
          + (imgs.length > 1 ? '<span class="cm-cover-more">' + imgs.length + ' 张图</span>' : "")
        : '<span class="cm-cover-none">' + escapeHtml((p.title || p.body || "").slice(0, 60) || "这条只有一句话") + "</span>";
    const line = hasImg ? (p.title || p.body || "") : (p.title ? (p.body || "") : "");
    const titleLine = line ? '<button type="button" class="cm-title" onclick="openPostDetail(' + p.id + ')">'
        + escapeHtml(line) + "</button>" : "";
    return '<article class="cm-card"' + (withId ? ' id="post-' + p.id + '"' : '') + ' data-post="' + p.id + '">'
        + '<button type="button" class="cm-cover" onclick="openPostDetail(' + p.id + ')" aria-label="打开这条帖子">' + cover + "</button>"
        + '<div class="cm-card-main">' + titleLine
        + '<div class="cm-card-foot">'
        + '<button type="button" class="cm-who-btn" onclick="openMemberHome(' + (p.author ? p.author.id : 0) + ')">'
        + '<span class="cm-avatar sm">' + cmAvatarInner(p.author) + "</span>"
        + '<span class="cm-name">' + escapeHtml(cmName(p.author)) + "</span></button>"
        + '<button type="button" class="cm-act" aria-pressed="' + (p.liked_by_me ? "true" : "false") + '" '
        + 'onclick="toggleLike(' + p.id + ',this)">❤ <b data-like>' + Number(p.like_count) + "</b></button>"
        + "</div></div></article>";
}

function renderFeed() {
    const host = cmEl("cm-feed");
    if (!host) return;
    host.innerHTML = cm.items.map(function (p) { return cmCardHTML(p, true); }).join("");
    const more = cmEl("cm-more");
    if (more) more.hidden = !cm.more;
    setupFeedMoreObserver();
    if (cmState("cm-feed-state", ""), !cm.items.length) {
        cmState("cm-feed-state", cm.feed === "mine" ? "你还没有发过帖子，上面那条就是入口。"
            : cm.feed === "follow" ? "关注的人发的帖子会出现在这里。现在还没有。"
            : cm.feed === "city" ? "同城还没有帖子。属地是发帖子或评论时按 IP 认出来的，只到省一级。"
            : "广场还空着，第一条可以你来发。");
    }
}

/** 滚到“看更早的”时自动拉下一页；按钮本身保留给网页端手动点。 */
function setupFeedMoreObserver() {
    const more = cmEl("cm-more");
    if (!more || more.dataset.observed || typeof IntersectionObserver !== "function") return;
    more.dataset.observed = "1";
    new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; }) && cm.more && !cm.loading) loadCommunity(true);
    }, { rootMargin: "240px 0px" }).observe(more);
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
    const t = cmEl("cm-post-title");
    if (t) t.focus();
}

function syncComposerCount() {
    const t = cmEl("cm-post-text"), h = cmEl("cm-post-title");
    cmText("cm-post-count", ((h && h.value ? h.value.length : 0)) + " / " + CM_LIMITS.title
        + " · " + ((t && t.value ? t.value.length : 0)) + " / " + CM_LIMITS.post);
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
        if (cm.images.length >= CM_LIMITS.postImages) cmState("cm-post-err", "一条帖子最多 " + CM_LIMITS.postImages + " 张图，多余的没加进来");
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
    const t = cmEl("cm-post-text"), h = cmEl("cm-post-title");
    const text = (t && t.value || "").trim();
    const title = (h && h.value || "").trim();
    if (!text && !title && !cm.images.length) { cmState("cm-post-err", "标题、正文和图片至少给一个"); return; }
    cmState("cm-post-err", "");
    try {
        const r = await postApi("/api/community/posts",
            { title, text, images: cm.images.map(x => x.name) });
        cm.images = []; renderThumbs();
        if (t) t.value = "";
        if (h) h.value = "";
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

async function toggleFavorite(id, btn) {
    const cur = btn.getAttribute("aria-pressed") === "true";
    btn.setAttribute("aria-pressed", cur ? "false" : "true");
    try {
        const r = await postApi("/api/community/posts/" + id + "/favorite", { on: !cur });
        const card = btn.closest(".cm-card");
        const b = card && card.querySelector("[data-fav]");
        if (b) b.textContent = Number(r.favorite_count);
        const item = cm.items.find(x => x.id === id);
        if (item) { item.favorite_count = r.favorite_count; item.favorited_by_me = r.favorited; }
        const detailB = document.querySelector(".pd-acts [data-fav]");
        if (detailB) detailB.textContent = Number(r.favorite_count);
    } catch (e) {
        btn.setAttribute("aria-pressed", cur ? "true" : "false");
        callNativeToast("收藏没生效：" + (e.message || "网络不通"));
    }
}

/* PATCH 同样单独走一条：帖子编辑用它。改走 app.js 的请求底座（30 秒超时、代次检查、统一错误形状） */
async function patchJson(path, body) {
    return requestBase(path, { method: "PATCH", body: body || {} });
}

/* postApi 只会 POST，删除要单独走一条，失败原因照样要说出来 */
async function deleteJson(path) {
    return requestBase(path, { method: "DELETE" });
}

/** 把正文里 @昵称 换成可点的按钮。只替换服务端确认过的那几个人，前端不猜谁是用户。
    一次扫完，不能逐个 split/join：两个人同名时，第二次替换会把第一颗按钮
    再包一层，而 HTML 不许 button 套 button，浏览器会把外面那颗截成空按钮。 */
function qsMentionHTML(escaped, mentions) {
    const list = (mentions || []).filter(m => m && m.name)
        .sort((a, b) => String(b.name).length - String(a.name).length);
    if (!list.length) return escaped;
    const map = {}, pattern = [];
    list.forEach(function (m) {
        const token = "@" + escapeHtml(m.name);
        if (!(token in map)) map[token] = Number(m.id) || 0;
        pattern.push(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    });
    return String(escaped).replace(new RegExp(pattern.join("|"), "g"), function (token) {
        return '<button type="button" class="pd-at" onclick="openMemberHome(' + map[token] + ')">' + token + "</button>";
    });
}

function qsCommentHTML(c, isReply, postId) {
    const author = c.author || {};
    const authorId = Number(author.id) || 0;
    const name = cmName(author);
    const avatar = '<button type="button" class="pd-cmt-profile" aria-label="打开 ' + escapeHtml(name) + ' 的主页"'
        + ' onclick="openMemberHome(' + authorId + ')"><span class="cm-avatar sm">'
        + cmAvatarInner(author) + "</span></button>";
    const replyId = Number(c.reply_to_user_id) || 0;
    const replyName = String(c.reply_to_name || "原评论");
    const prefix = isReply
        ? '<span class="pd-reply-prefix">（回复 '
            + (replyId ? '<button type="button" class="pd-reply-target" onclick="openMemberHome(' + replyId + ')">' + escapeHtml(replyName) + "</button>"
                : escapeHtml(replyName)) + "）</span> "
        : "";
    const imgs = (c.images || []).length
        ? '<div class="pd-cmt-imgs">' + c.images.map(u => '<img src="' + escapeHtml(API_BASE + u)
            + '" alt="评论配图" loading="lazy" onclick="viewPostImage(\''
            + escapeHtml(API_BASE + u).replace(/'/g, "%27") + '\')">').join("") + "</div>"
        : "";
    const cid = Number(c.id);
    return '<div class="pd-cmt' + (isReply ? " pd-cmt-reply" : "") + '" data-comment="' + cid + '">'
        + avatar + '<div class="pd-cmt-main"><button type="button" class="pd-cmt-name" aria-label="打开 ' + escapeHtml(name) + ' 的主页"'
        + ' onclick="openMemberHome(' + authorId + ')">' + escapeHtml(name) + "</button>"
        + '<div class="pd-cmt-content">' + prefix + '<span class="pd-cmt-text">'
        + qsMentionHTML(escapeHtml(c.body), c.mentions) + "</span></div>" + imgs
        + '<div class="pd-cmt-meta"><span class="pd-cmt-time">' + cmRegionTag(c.region) + " · " + escapeHtml(cmAgo(c.created_at)) + "</span>"
        + '<button type="button" class="pd-cmt-act pd-cmt-like" aria-pressed="' + (c.liked_by_me ? "true" : "false") + '" '
        + 'onclick="toggleCommentLike(' + cid + ',' + Number(postId) + ',this)">❤ <b>' + Number(c.like_count || 0) + "</b></button>"
        + '<button type="button" class="pd-cmt-act" data-reply-id="' + cid + '" data-reply-name="' + escapeHtml(name)
        + '" onclick="setReplyTargetFromButton(this)">回复</button>'
        + (c.deletable ? '<button type="button" class="pd-cmt-act pd-cmt-del" onclick="removeComment(' + cid + ',' + Number(postId) + ')">删除</button>' : "")
        + "</div></div></div>";
}

function qsCommentsHTML(comments, postId) {
    const rows = Array.isArray(comments) ? comments : [];
    const byId = new Map(rows.map(c => [Number(c.id), c]));
    const roots = [];
    const replies = new Map();
    rows.forEach(c => {
        const parent = c.reply_to == null ? null : byId.get(Number(c.reply_to));
        if (!parent) { roots.push(c); return; }
        let root = parent;
        const seen = new Set();
        while (root.reply_to != null && byId.has(Number(root.reply_to)) && !seen.has(Number(root.id))) {
            seen.add(Number(root.id));
            root = byId.get(Number(root.reply_to));
        }
        if (Number(root.id) === Number(c.id)) { roots.push(c); return; }
        const key = Number(root.id);
        if (!replies.has(key)) replies.set(key, []);
        replies.get(key).push(c);
    });
    return roots.map(root => {
        const nested = replies.get(Number(root.id)) || [];
        return qsCommentHTML(root, root.reply_to != null, postId)
            + (nested.length ? '<div class="pd-cmt-replies">' + nested.map(c => qsCommentHTML(c, true, postId)).join("") + "</div>" : "");
    }).join("");
}

/* 帖子详情：整页跳转（机主："帖子不要做成弹窗，跳转页面，参考微博"）。
   正文大一号、配图单独一块、时间退到分割线下面，评论区铺满，输入框固定在底部。 */
async function qsRenderPost(arg) {
    // arg 可以是 12，也可以是 "12:34"——后者来自 @ 提醒，点进去要停在那条评论上
    const seg = String(arg == null ? "" : arg).split(":");
    const id = Number(seg[0]) || 0;
    const focusCid = Number(seg[1]) || 0;
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
    if (Number(cm.postId) !== id) {
        // 换帖子必须把上一张的草稿丢掉，否则"我以为在给这条评论配图"其实是带着另一张的图发出去
        cmReplyTo = null; cm.cmtImages = []; cm.cmtMentions = []; cm.atRows = []; cm.atQuery = "";
    }
    cm.postId = id;
    cmText("pl-title", cmName(p.author) + " 的帖子");
    const mine = p.author && qsSameId(p.author.id, state.user && state.user.id);
    const imgs = (p.images || []).length
        ? '<div class="pd-imgs' + (p.images.length === 1 ? " one" : "") + '">' + p.images.map(u =>
            '<img src="' + escapeHtml(API_BASE + u) + '" alt="帖子配图" onclick="viewPostImage(\'' +
            escapeHtml(API_BASE + u).replace(/'/g, "%27") + '\')">').join("") + "</div>"
        : "";
    const titleLine = p.title ? '<h2 class="pd-title">' + escapeHtml(p.title) + "</h2>" : "";
    // Keep replies under their parent and identify the person being answered.
    const comments = qsCommentsHTML(r.comments || [], p.id);
    body.innerHTML = '<article class="pd-post">'
        + '<div class="pd-who"><button type="button" class="cm-who-btn" onclick="openPage(\'member\',' + (p.author ? p.author.id : 0) + ')">'
        + '<span class="cm-avatar">' + cmAvatarInner(p.author) + "</span>"
        + '<span class="cm-who"><span class="cm-name">' + escapeHtml(cmName(p.author)) + "</span>"
        + '<span class="cm-sub">' + cmRegionTag(p.region) + "</span></span></button>"
        + (mine ? "" : '<button type="button" class="cm-follow" aria-pressed="' + (p.followed_by_me ? "true" : "false") +
            '" onclick="toggleFollow(' + (p.author ? p.author.id : 0) + ',this)">' +
            (p.followed_by_me ? "已关注" : "关注") + "</button>")
        + "</div>"
        + titleLine
        + '<div class="pd-text">' + escapeHtml(p.body) + "</div>" + imgs
        + '<div class="pd-meta">' + escapeHtml(cmTime(p.created_at)) + " · " + cmRegionTag(p.region)
        + (p.edited_at ? " · 已编辑" : "") + "</div>"
        + '<div class="pd-acts">'
        + '<button type="button" class="td-mini" aria-pressed="' + (p.liked_by_me ? "true" : "false") + '" '
        + 'onclick="toggleLike(' + p.id + ',this)">❤ 赞 ' + Number(p.like_count) + "</button>"
        + '<button type="button" class="td-mini" onclick="focusCommentInput()">💬 评论 ' + Number(p.comment_count) + "</button>"
        + '<button type="button" class="td-mini" aria-pressed="' + (p.favorited_by_me ? "true" : "false") + '" '
        + 'onclick="toggleFavorite(' + p.id + ',this)">★ 收藏 <b data-fav>' + Number(p.favorite_count || 0) + "</b></button>"
        + '<span class="pd-acts-extra">'
        + (mine ? '<button type="button" class="td-mini" onclick="editPostFromDetail(' + p.id + ')">编辑</button>'
            + '<button type="button" class="td-mini pd-danger" onclick="deletePostFromDetail(' + p.id + ')">删除</button>'
            : (p.author ? '<button type="button" class="td-mini pd-report" onclick="openReport(&#39;post&#39;,' + p.id + ')">举报</button>'
                + '<button type="button" class="td-mini" onclick="openDM(' + p.author.id + ')">私信 TA</button>' : ""))
        + "</span>"
        + "</div></article>"
        + '<h3 class="pd-sec">评论 ' + Number(p.comment_count) + "</h3>"
        + (comments || '<p class="td-empty">还没有人评论，说第一句。</p>');
    qsSetFoot(cmtFootHTML(p.id));
    syncCmtDraft();
    if (focusCid) qsFocusComment(focusCid);
}

/** 从通知点进来时停在那条评论上：滚到中间、亮两秒。
    找不到（已被删）就明说，不许静默停在帖子顶部让人自己找。 */
function qsFocusComment(cid) {
    const el = document.querySelector('[data-comment="' + Number(cid) + '"]');
    if (!el) { callNativeToast("那条评论已经不在了"); return; }
    el.classList.add("pd-cmt-flash");
    try { el.scrollIntoView({ block: "center" }); } catch (e) { try { el.scrollIntoView(); } catch (e2) {} }
    setTimeout(function () { el.classList.remove("pd-cmt-flash"); }, 2400);
}

function editPostFromDetail(id) {
    const art = document.querySelector(".pd-post");
    if (!art) return;
    const textEl = art.querySelector(".pd-text");
    if (!textEl || art.querySelector(".pd-editor")) return;
    const titleEl = art.querySelector(".pd-title");
    const original = textEl.textContent || "";
    const originalTitle = titleEl ? titleEl.textContent : "";
    textEl.outerHTML = '<div class="pd-editor">'
        + '<input id="pd-edit-title" type="text" maxlength="' + CM_LIMITS.title + '" placeholder="标题（20 字内，可留空）" value="'
        + escapeHtml(originalTitle) + '" aria-label="编辑标题">'
        + '<textarea id="pd-edit-text" maxlength="' + CM_LIMITS.post + '" aria-label="编辑帖子">'
        + escapeHtml(original) + "</textarea>"
        + '<div class="pd-editor-acts"><button type="button" class="td-btn td-btn-quiet" onclick="qsRenderPost(' + id + ')">取消</button>'
        + '<button type="button" class="td-btn" onclick="savePostEdit(' + id + ')">保存</button></div></div>';
    const area = cmEl("pd-edit-text");
    if (area) { area.focus(); area.setSelectionRange(area.value.length, area.value.length); }
}

async function savePostEdit(id) {
    const area = cmEl("pd-edit-text"), titleEl = cmEl("pd-edit-title");
    const text = ((area && area.value) || "").trim();
    const title = ((titleEl && titleEl.value) || "").trim();
    if (!text && !title) { callNativeToast("标题和正文不能都空着"); return; }
    try {
        const r = await patchJson("/api/community/posts/" + id, { title: title, text: text });
        const item = cm.items.find(x => x.id === id);
        if (item && r.post) { item.title = r.post.title; item.body = r.post.body; item.edited_at = r.post.edited_at; }
        renderFeed();
        qsRenderPost(id);
        callNativeToast("已保存");
    } catch (e) { callNativeToast("没保存：" + (e.message || "网络不通")); }
}

function focusCommentInput() {
    const input = cmEl("cm-comment-text");
    if (input) input.focus();
}

function qsPickAvatarName(input) {
    const name = cmEl("avatar-file-name");
    if (!name) return;
    const f = input && input.files && input.files[0];
    name.textContent = f ? f.name : "未选择";
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

/* ── 评论区输入区：表情 / @ 人 / 配图 / 我的动图 ────────────────────
   形状照私信那一套（工具行 + 可展开面板 + 输入行），但状态是自己的：
   评论的图发出去就清，私信的待发媒体跟着会话走，两者混用会出现"换了帖子
   还把上一个帖子的草稿带过来"。 */
function cmtFootHTML(postId) {
    const emoji = DM_EMOJIS.map(function (group) {
        return '<section class="dm-emoji-group"><h4>' + escapeHtml(group[0]) + "</h4>"
            + '<div class="dm-emoji-grid">' + group[1].map(function (e) {
                return '<button type="button" class="dm-emoji" aria-label="插入表情 ' + escapeHtml(e) +
                    '" onclick="cmtInsert(\'' + e + '\')">' + e + "</button>";
            }).join("") + "</div></section>";
    }).join("");
    const pid = Number(postId) || 0;
    return '<div class="cmt-draft" id="cmt-draft" hidden></div>'
        + '<div class="cmt-tools">'
        + '<button type="button" class="dm-tool" id="cmt-emoji-btn" aria-label="表情面板" aria-expanded="false" onclick="toggleCmtPanel(\'emoji\')">☺</button>'
        + '<button type="button" class="dm-tool" id="cmt-at-btn" aria-label="@ 谁" aria-expanded="false" onclick="toggleCmtPanel(\'at\')">@</button>'
        + '<button type="button" class="dm-tool" id="cmt-gif-btn" aria-label="我的动图" aria-expanded="false" onclick="toggleCmtPanel(\'gif\')">动</button>'
        + '<button type="button" class="dm-tool" id="cmt-img-btn" aria-label="配一张图" onclick="cmtPickImage()">🖼</button>'
        + "</div>"
        + '<div class="dm-panel" id="cmt-emoji-panel" hidden>' + emoji + "</div>"
        + '<div class="dm-panel" id="cmt-at-panel" hidden><div class="cmt-at-list" id="cmt-at-list"></div></div>'
        + '<div class="dm-panel" id="cmt-gif-panel" hidden><div class="cmt-gif-grid" id="cmt-gif-grid"></div></div>'
        + '<div class="cmt-input-row">'
        + '<input id="cm-comment-text" type="text" maxlength="' + CM_LIMITS.comment +
        '" placeholder="' + (cmReplyTo ? "回复 @" + escapeHtml(cmReplyTo.name) : "友善一点，好好说话") +
        '" aria-label="评论内容" oninput="onCmtInput()" onkeydown="if(event.key===\'Enter\'){event.preventDefault();submitComment(' + pid + ');;}">'
        + '<button type="button" class="td-btn" onclick="submitComment(' + pid + ')">发送</button></div>'
        + '<input type="file" id="cmt-image-file" accept="image/*" class="file-hidden" onchange="attachCommentImage(this)">';
}

function closeCmtPanel() {
    ["emoji", "at", "gif"].forEach(function (k) {
        const panel = cmEl("cmt-" + k + "-panel");
        if (panel) panel.hidden = true;
        const btn = cmEl("cmt-" + k + "-btn");
        if (btn) btn.setAttribute("aria-expanded", "false");
    });
    cm.cmtPanel = "";
}

function toggleCmtPanel(which) {
    const target = cmEl("cmt-" + which + "-panel");
    if (!target) return;
    const wasOpen = !target.hidden;
    closeCmtPanel();
    if (wasOpen) return;
    target.hidden = false;
    cm.cmtPanel = which;
    const btn = cmEl("cmt-" + which + "-btn");
    if (btn) btn.setAttribute("aria-expanded", "true");
    if (which === "at") refreshAtList();
    if (which === "gif") loadMyStickers();
}

function cmtInput() { return cmEl("cm-comment-text"); }

function cmtInsert(text) {
    const input = cmtInput();
    if (!input) return;
    const start = input.selectionStart == null ? input.value.length : input.selectionStart;
    const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    input.focus();
    const caret = start + text.length;
    try { input.setSelectionRange(caret, caret); } catch (e) {}
    syncCmtDraft();
}

/* 光标前正在打 @xxx 就把 @ 面板打开并跟着这个词搜人；打完空格就收起来。 */
function atTokenAtCursor(value) {
    const m = /@([^\s@]{0,16})$/.exec(value || "");
    return m ? m[1] : null;
}

function onCmtInput() {
    const input = cmtInput();
    const value = (input && input.value) || "";
    const term = atTokenAtCursor(value);
    if (term !== null) {
        if (cm.atQuery !== term) {
            cm.atQuery = term;
            const panel = cmEl("cmt-at-panel");
            if (panel && panel.hidden) { closeCmtPanel(); panel.hidden = false; cm.cmtPanel = "at"; }
            refreshAtList();
        }
    } else if (cm.atQuery) {
        cm.atQuery = "";
        if (cm.cmtPanel === "at") closeCmtPanel();
    }
    syncCmtDraft();
}

async function refreshAtList() {
    const seq = ++cm.atSeq;
    const term = String(cm.atQuery || "").trim().slice(0, 16);
    try {
        const r = term
            ? await getJson("/api/community/search?q=" + encodeURIComponent(term))
            : await getJson("/api/community/connections?kind=following&limit=24");
        if (seq !== cm.atSeq) return;   // 只认最后一次输入的结果，早回来的旧搜索不许盖上来
        cm.atRows = (r.items || []).filter(u => !qsSameId(u.id, state.user && state.user.id)).slice(0, 24);
        renderAtList("");
    } catch (e) {
        if (seq !== cm.atSeq) return;
        cm.atRows = [];
        renderAtList("人没读到：" + (e.message || "网络不通"));
    }
}

function renderAtList(errText) {
    const host = cmEl("cmt-at-list");
    if (!host) return;
    if (errText) { host.innerHTML = '<p class="cm-state">' + escapeHtml(errText) + "</p>"; return; }
    if (!cm.atRows.length) {
        host.innerHTML = '<p class="td-empty">' + (String(cm.atQuery || "").trim()
            ? "没搜到这个名字。昵称要完全对上才准，别人把你改名了就搜不到。"
            : "你还没有关注的人。先在帖子或主页点「关注」，或直接在这里打 @ 搜昵称。") + "</p>";
        return;
    }
    host.innerHTML = cm.atRows.map(function (u) {
        // 一排全是"小田"时选错就 @ 错人，所以把轻塑号一起显示出来分辨
        const sub = cmRegionTag(u.region) + (u.public_id ? " · #" + escapeHtml(String(u.public_id)) : "");
        return '<button type="button" class="cmt-at-row" onclick="pickMention(' + Number(u.id) + ",'"
            + escapeHtml(u.name || "").replace(/'/g, "%27") + "')\">"
            + '<span class="cm-avatar sm">' + cmAvatarInner(u) + "</span>"
            + '<span class="cmt-at-name">' + escapeHtml(u.name || "已注销用户") + "</span>"
            + '<span class="cmt-at-sub">' + sub + "</span></button>";
    }).join("");
}

function pickMention(uid, name) {
    if (cm.cmtMentions.length >= 5 && !cm.cmtMentions.some(m => qsSameId(m.id, uid))) {
        callNativeToast("一条评论最多 @ 五个人"); return;
    }
    const input = cmtInput();
    // 把已经打了一半的 @xxx 换回完整的 @昵称，不然会留下 "@小" + "@小田" 这种半截
    if (input) input.value = input.value.replace(/@([^\s@]{0,16})$/, "");
    if (!cm.cmtMentions.some(m => qsSameId(m.id, uid))) cm.cmtMentions.push({ id: uid, name: name });
    cm.atQuery = "";
    closeCmtPanel();
    cmtInsert("@" + name + " ");
}

function cmtPickImage() {
    const f = cmEl("cmt-image-file");
    if (f) f.click();
}

async function attachCommentImage(input) {
    const file = input && input.files && input.files[0];
    if (!file) return;
    if (cm.cmtImages.length >= CM_LIMITS.cmtImages) {
        callNativeToast("一条评论最多 " + CM_LIMITS.cmtImages + " 张图");
        input.value = ""; return;
    }
    try {
        const form = new FormData();
        form.append("file", file);
        const r = await rawPostApi("/api/community/media", form);
        cm.cmtImages.push({ name: r.name, url: r.url, kind: r.kind || "image" });
        syncCmtDraft();
    } catch (e) {
        callNativeToast("图没传上去：" + (e.message || "格式或大小不合适"));
    } finally {
        input.value = "";
    }
}

async function loadMyStickers() {
    const host = cmEl("cmt-gif-grid");
    if (!host) return;
    host.innerHTML = '<p class="cm-state">在读…</p>';
    try {
        const r = await getJson("/api/community/stickers");
        cm.stickers = r.items || [];
    } catch (e) { cm.stickers = []; }
    host.innerHTML = (cm.stickers || []).length
        ? cm.stickers.map(function (s) {
            return '<button type="button" class="cmt-gif" aria-label="再用一次这张动图" onclick="pickSticker(\''
                + escapeHtml(s.name) + "','" + escapeHtml(s.url).replace(/'/g, "%27") + "')\">"
                + '<img src="' + escapeHtml(API_BASE + s.url) + '" alt="我的动图" loading="lazy"></button>';
        }).join("")
        : '<p class="td-empty">还没有你自己的动图。点 🖼 选一张 GIF 传上去，之后就能在这里一键再发。</p>';
}

function pickSticker(name, url) {
    if (cm.cmtImages.some(x => x.name === name)) { closeCmtPanel(); return; }
    if (cm.cmtImages.length >= CM_LIMITS.cmtImages) { callNativeToast("一条评论最多 " + CM_LIMITS.cmtImages + " 张图"); return; }
    cm.cmtImages.push({ name: name, url: url, kind: "gif" });
    closeCmtPanel();
    syncCmtDraft();
}

function dropCmtImage(i) { cm.cmtImages.splice(i, 1); syncCmtDraft(); }
function dropCmtMention(i) { cm.cmtMentions.splice(i, 1); syncCmtDraft(); }

/** 待发区：图、@ 到的人、回复对象都摊开可见可撤。
    藏在输入框后面不清不楚，就会出现"我以为没 @ 他，其实带着呢"。 */
function syncCmtDraft() {
    const host = cmEl("cmt-draft");
    if (!host) return;
    const chips = [];
    if (cmReplyTo) chips.push('<span class="cmt-chip">回复 ' + escapeHtml(cmReplyTo.name)
        + '<button type="button" aria-label="取消回复" onclick="cancelReply()">✕</button></span>');
    cm.cmtMentions.forEach(function (m, i) {
        chips.push('<span class="cmt-chip cmt-chip-at">@' + escapeHtml(m.name)
            + '<button type="button" aria-label="取消提到这个人" onclick="dropCmtMention(' + i + ')">✕</button></span>');
    });
    cm.cmtImages.forEach(function (im, i) {
        chips.push('<span class="cmt-thumb"><img src="' + escapeHtml(im.url.startsWith("http") ? im.url : API_BASE + im.url)
            + '" alt="待发配图"' + (im.kind === "gif" ? ' data-gif="1"' : "")
            + '><button type="button" aria-label="移除这张图" onclick="dropCmtImage(' + i + ')">✕</button></span>');
    });
    host.innerHTML = chips.join("");
    host.hidden = !chips.length;
}

function cancelReply() { cmReplyTo = null; const i = cmtInput(); if (i) i.placeholder = "友善一点，好好说话"; syncCmtDraft(); }

async function toggleCommentLike(cid, postId, btn) {
    const on = btn.getAttribute("aria-pressed") === "true";
    btn.setAttribute("aria-pressed", on ? "false" : "true");
    try {
        const r = await postApi("/api/community/comments/" + cid + "/like", { on: !on });
        const b = btn.querySelector("b");
        if (b) b.textContent = String(Number(r.like_count));
        const row = document.querySelector('[data-comment="' + cid + '"]');
        if (row && !on) { row.classList.remove("cmt-pop"); void row.offsetWidth; row.classList.add("cmt-pop"); }
    } catch (e) {
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        callNativeToast("点赞没生效：" + (e.message || "网络不通"));
    }
}

/* 双击封面点赞（小红书那一下）：已经点过就只弹心，不再取消——
   取消点赞是明确动作，交给那颗按钮，别让手滑把赞弄没。 */
function dblLikePost(postId, node) {
    const item = cm.items.find(x => x.id === Number(postId));
    const btn = document.querySelector('#post-' + postId + " .cm-act");
    if (item && !item.liked_by_me && btn) toggleLike(postId, btn);
    if (node) {
        node.classList.remove("cm-hearted");
        void node.offsetWidth;
        node.classList.add("cm-hearted");
        setTimeout(function () { node.classList.remove("cm-hearted"); }, 700);
    }
}

QS_PAGE_DEF.post = { title: "帖子详情", render: qsRenderPost };

/* 旧入口保留成一行跳转，别的地方还在按老名字调它们。
   第二个参数是"进去要停在哪条评论"——@ 提醒与回复通知靠它定位。 */
function openPostDetail(id, commentId) {
    if (!id) return;
    openPage("post", Number(commentId) ? Number(id) + ":" + Number(commentId) : Number(id));
}
function openThread(uid) { if (uid) openPage("dm", uid); }

let cmReplyTo = null;
function setReplyTo(id) { cmReplyTo = id; }
function setReplyTarget(id, name) {
    cmReplyTo = { id: id, name: name };
    const input = cmEl("cm-comment-text");
    if (input) { input.placeholder = "回复 @" + name; input.focus(); }
    syncCmtDraft();
}
function setReplyTargetFromButton(button) {
    if (!button) return;
    setReplyTarget(Number(button.getAttribute("data-reply-id")), button.getAttribute("data-reply-name") || "");
}

async function submitComment(postId) {
    const input = cmEl("cm-comment-text");
    const text = (input && input.value || "").trim();
    if (!text && !cm.cmtImages.length) { callNativeToast("评论写一句，或者配一张图"); if (input) input.focus(); return; }
    try {
        const r = await postApi("/api/community/posts/" + postId + "/comments", {
            text,
            images: cm.cmtImages.map(x => x.name),
            mentions: cm.cmtMentions.map(m => Number(m.id)),
            reply_to: cmReplyTo ? cmReplyTo.id : null
        });
        cmReplyTo = null;
        cm.cmtImages = []; cm.cmtMentions = []; cm.atQuery = "";
        callNativeToast((r && r.comment && r.comment.mentions && r.comment.mentions.length)
            ? "评论发出去了，也点到他们了" : "评论发出去了");
        if (input) input.value = "";
        qsRenderPost(postId);
        const item = cm.items.find(x => x.id === Number(postId));
        if (item) item.comment_count = Number(item.comment_count || 0) + 1;
        syncCardCounts(postId);
    } catch (e) {
        callNativeToast(e.message || "评论没成功，内容还留着");
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

let cmReport = { kind: "post", id: 0 };

function openReport(kind, id) {
    if (!state.token) { openAuthModal(); return; }
    cmReport = { kind: kind || "post", id: Number(id) || 0 };
    const dlg = cmEl("report-dialog");
    if (!dlg) return;
    const note = cmEl("report-note");
    if (note) note.value = "";
    dlg.querySelectorAll("#report-reasons .td-seg-btn").forEach(b =>
        b.setAttribute("aria-selected", b.dataset.reason === "垃圾广告" ? "true" : "false"));
    dlg.showModal();
}

async function submitReport() {
    const active = document.querySelector('#report-reasons .td-seg-btn[aria-selected="true"]');
    const noteEl = cmEl("report-note");
    const note = (noteEl && noteEl.value || "").trim().slice(0, 120);
    const reason = (active ? active.dataset.reason : "其他") + (note ? "：" + note : "");
    try {
        await postApi("/api/community/report", { kind: cmReport.kind, target_id: cmReport.id, reason: reason });
        const dlg = cmEl("report-dialog");
        if (dlg) dlg.close();
        callNativeToast("已提交，后台会处理");
    } catch (e) {
        callNativeToast("没提交上：" + (e.message || "网络不通"));
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
        const posts = r.posts || [];
        const usersHtml = items.length ? items.map(u =>
            '<button type="button" class="cm-row" onclick="openMemberHome(' + u.id + ')">'
            + '<span class="cm-avatar">' + cmAvatarInner(u) + "</span>"
            + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(cmName(u)) + "</span>"
            + '<span class="cm-row-meta">轻塑号 ' + escapeHtml(u.public_id || "—") +
            (u.region ? " · 属地 " + escapeHtml(u.region) : "") + "</span></span></button>").join("")
            : '<p class="td-empty">没找到这个人。轻塑号要输全 8 位，昵称可以只输几个字。</p>';
        const postsHtml = posts.length
            ? '<h3 class="pd-sec">相关帖子</h3>' + posts.map(x => cmCardHTML(x, false)).join("")
            : "";
        host.innerHTML = usersHtml + postsHtml;
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
        + '<div class="card me-stats">' + qsStatsHTML(stats, u.id) + "</div>"
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
    // 切类别必须补一次读：进「消息」页时只读了当前这一类（默认是私信），
    // 光靠 renderMessages 画内存，第一次点「互动通知」就是空的——别人 @ 了你你也看不见。
    renderMessages();
    loadMessages();
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
    if (cm.loadingMsg) { cm.msgAgain = true; return; }
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
        // 这一趟在飞的时候用户又切了类别：不能把那次切换吞掉，否则停在旧类别的数据上
        if (cm.msgAgain) { cm.msgAgain = false; loadMessages(); }
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
        const rows = cm.notices.map(n => {
            // 整行可点：通知就是一条"去哪儿看"的路径，只让那颗小按钮可点太难按到
            const go = n.post_id ? ' role="button" tabindex="0" onclick="openPostDetail(' + Number(n.post_id)
                + "," + (Number(n.comment_id) || 0) + ')"' : ' style="cursor:default"';
            const where = n.comment_id ? "看评论" : (n.post_id ? "看帖子" : "");
            return '<div class="cm-row"' + go + '><span class="cm-avatar">' + cmAvatarInner(n.actor) + "</span>"
                + '<span class="cm-row-main"><span class="cm-row-title">' + escapeHtml(n.text || cmName(n.actor)) + "</span>"
                + '<span class="cm-row-meta">' + escapeHtml(cmAgo(n.created_at)) + (n.read_at ? "" : " · 未读") + "</span></span>"
                + (where ? '<span class="cm-row-side">' + where + '<br><span class="td-chevron"></span></span>' : "") + "</div>";
        }).join("");
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
        dmUi.stickBottom = true;
        body.innerHTML = '<div class="cm-bubbles page" id="thread-bubbles"><p class="cm-state">在读…</p></div>';
        qsSetFoot("");
        await refreshThread();
        return;
    }
    body.innerHTML = '<div class="cm-bubbles page" id="thread-bubbles"></div>';
    paintThread();
}

async function openFavorites() {
    if (!state.token) { openAuthModal(); return; }
    openPage("favorites", 0);
}

async function qsRenderFavorites() {
    const body = cmEl("pl-body");
    if (!body) return;
    body.innerHTML = '<p class="cm-state">在读…</p>';
    try {
        const r = await getJson("/api/community/favorites?limit=12");
        body.innerHTML = '<div class="cm-feed">' + ((r.items || []).length
            ? r.items.map(x => cmCardHTML(x, false)).join("")
            : '<p class="td-empty">还没有收藏。看到喜欢的帖子，点一下星标。</p>') + "</div>";
    } catch (e) {
        body.innerHTML = '<p class="cm-state">没读到：' + escapeHtml(e.message || "网络不通") + "</p>";
    }
}

QS_PAGE_DEF.favorites = { title: "我的收藏", render: qsRenderFavorites };
QS_PAGE_DEF.dm = { title: "私信", render: qsRenderDm };

function closeThread() {
    cm.thread = null;
    qsCloseAllPages();
    loadMessages();
}

async function refreshThread() {
    if (!cm.thread) return;
    const uid = cm.thread.partner.id, scope = dmScope();
    try {
        const r = await getJson("/api/chat/messages?with_user=" + uid + "&limit=30");
        if (!dmScopeAlive(scope) || !dmIsVisible()) return;
        // A pre-community local session may not have an id cached. The server
        // knows the token owner, so hydrate it before assigning message sides.
        const meId = Number(r.me_id);
        if (Number.isFinite(meId) && meId > 0) {
            state.user = Object.assign({}, state.user || {}, { id: meId });
            try { localStorage.setItem(USER_KEY, JSON.stringify(state.user)); } catch (e) {}
        }
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
    if (!cm.thread || !dmIsVisible()) return;
    const me = state.user && state.user.id;
    const p = cm.thread.partner;
    const title = cmEl("pl-title");
    if (title) {
        const partnerId = Number(p && p.id) || 0;
        title.innerHTML = '<button type="button" class="pl-title-profile" aria-label="打开 ' + escapeHtml(cmName(p)) + ' 的主页"'
            + ' onclick="openMemberHome(' + partnerId + ')"><span class="cm-avatar sm">' + cmAvatarInner(p) + "</span>"
            + "<span>" + escapeHtml(cmName(p)) + "</span></button>";
    }
    const slot = cmEl("pl-slot");
    if (slot) {
        const blocked = !!(p && p.blocked);
        slot.innerHTML = (blocked ? '' : '<button type="button" class="td-mini dm-call-btn" id="thread-call-btn" onclick="dmStartCall()" aria-label="语音通话">语音</button>')
            + '<button type="button" class="td-mini" id="thread-block-btn" aria-pressed="' +
            (blocked ? "true" : "false") + '" onclick="toggleBlock()">' + (blocked ? "取消拉黑" : "拉黑") + "</button>"
            + '<button type="button" class="td-mini" onclick="openBubbleTheme()">气泡</button>';
    }
    const host = cmEl("thread-bubbles");
    if (!host) return;
    dmMountComposer();
    dmRenderBubbles();
}

/* r164：输入栏只挂载一次；消息按 id 更新，草稿与媒体节点不随回执重建。
   图片和视频保留互关限制；表情与语音不需要互关。 */
const DM_EMOJIS = [
    ["开心", ["😀", "😄", "😁", "😆", "🤣", "😂", "🙂", "😉", "😊", "😍", "🥰", "😘", "😎", "🤔", "😴", "🥳"]],
    ["手势", ["👍", "👏", "🙌", "🙏", "💪", "🤝", "✌️", "👌", "🤙", "👋", "🫶", "❤️", "💚", "💛", "💙", "💜"]],
    ["氛围", ["🎉", "🔥", "✨", "⭐", "🌟", "💯", "🍀", "🌈", "☀️", "🌙", "💐", "🎂", "🍰", "🍜", "🧋", "🍉"]],
    ["小动物", ["🐱", "🐶", "🐼", "🐰", "🦊", "🐻", "🐨", "🐯", "🦁", "🐸", "🐵", "🐔", "🦄", "🐟", "🦋", "🌸"]]
];
const DM_PHRASES = ["在呢", "哈哈哈哈", "晚点聊", "收到～", "好滴", "加油！"];

const dmUi = { threadId: 0, generation: 0, panel: "", tab: "official", query: "",
    searchSeq: 0, results: [], busy: false, composing: false, record: null, draft: null, caret: [0, 0],
    stickBottom: true, voiceMode: false, quote: null, searchPage: 0, searchHasMore: false };
const dmSearchCache = new Map();
const dmHold = {pending:false,timer:0,held:false,released:false,cancelled:false,startY:0};
const dmCall = {
    state: "idle", id: "", peer: null, role: "", pc: null, stream: null, audio: null,
    offer: null, pendingIce: [], localIce: [], timer: 0, ring: 0, timeout: 0,
    startedAt: 0, muted: false, speaker: false, reason: "", endTimer: 0, minimized: false,
    failKind: ""
};
const dmOfficial = { items: [], byId: new Map(), loaded: false, task: null };
const DM_AUDIO_MAX = 5 * 1024 * 1024;
function dmScope() {
    return { generation: cmGeneration, session: sessionGeneration, token: state.token,
        threadId: Number(cm.thread && cm.thread.partner.id), ui: dmUi.generation };
}
function dmAccountAlive(s) {
    return !!s && s.generation === cmGeneration && s.session === sessionGeneration && s.token === state.token;
}
function dmScopeAlive(s) {
    return dmAccountAlive(s) && s.ui === dmUi.generation && cm.thread && qsSameId(s.threadId, cm.thread.partner.id);
}
function dmIsVisible() {
    const top = QS_PAGES[QS_PAGES.length - 1];
    return !!(top && top.name === "dm" && cm.thread && qsSameId(top.arg, cm.thread.partner.id));
}
function dmRequestId() { return "dm-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10); }
function dmPending(rid, s, data) {
    cm.pending[rid] = { rid, scope: s, msg: Object.assign({ from_id: state.user && state.user.id,
        to_id: s.threadId, body: "", created_at: "", request_id: rid }, data) };
}
/* 失败必须留在界面上。上一版只弹一次 toast 就把那条抹掉，机主原话是
   「发没发出去我根本不知道」；现在它常驻标「没发出去」并带单条重试。 */
function dmFail(rid, why) {
    const p = cm.pending[rid];
    delete cm.pending[rid];
    if (p) cm.failed[rid] = Object.assign({}, p, { why: why || "网络不通" });
}
function dmClosePanels() {
    dmUi.panel = "";
    ["emoji", "plus"].forEach(k => {
        const p = cmEl("dm-" + k + "-panel"), b = cmEl("dm-" + k + "-btn");
        if (p) p.hidden = true;
        if (b) b.setAttribute("aria-expanded", "false");
    });
}
function dmBlurKeyboard() {
    const el = document.activeElement;
    if (el && /^(INPUT|TEXTAREA)$/.test(el.tagName) && el.blur) el.blur();
}
function dmReleasePlayback(root) {
    if (!root) return;
    root.querySelectorAll("audio,video").forEach(el => {
        try { el.pause(); el.removeAttribute("src"); el.load(); } catch (e) {}
    });
}
function dmCleanup() {
    dmUi.generation++;
    dmUi.searchSeq++;
    dmCancelRecording(); dmMicRelease(); dmClearDraft();
    dmReleasePlayback(cmEl("thread-bubbles"));
    dmBlurKeyboard();
    dmClosePanels();
    dmUi.threadId = 0; dmUi.query = ""; dmUi.results = []; dmUi.tab = "official";
    dmUi.busy = false; dmUi.composing = false; dmUi.textRetry = null; dmUi.stickBottom = true;
    dmUi.quote = null; dmUi.searchPage = 0; dmUi.searchHasMore = false;
    qsBubbleCancel(); qsHideMenu();
}
function dmScrollLatest(force) {
    const host = cmEl('thread-bubbles');
    if (!host || !dmIsVisible()) return;
    if (force || dmUi.stickBottom) host.scrollTop = host.scrollHeight;
}
function dmViewportChanged() {
    if (dmUi.stickBottom) dmScrollLatest(true);
}
function dmTrackThreadScroll(event) {
    const host = event.target;
    if (!host || host.id !== 'thread-bubbles') return;
    dmUi.stickBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 120;
}
document.addEventListener('scroll', dmTrackThreadScroll, true);
window.addEventListener('resize', dmViewportChanged);
if (window.visualViewport) window.visualViewport.addEventListener('resize', dmViewportChanged);
function dmInputFocus() {
    dmClosePanels(); dmCancelRecording();
    dmUi.stickBottom = true;
    requestAnimationFrame(() => dmScrollLatest(true));
    setTimeout(() => dmScrollLatest(true), 260);
}
function dmRememberCaret() { const i = cmEl("dm-input"); if (i) dmUi.caret = [i.selectionStart ?? i.value.length, i.selectionEnd ?? i.value.length]; }
function dmInputKey(ev) {
    if (ev.key === "Enter" && !ev.isComposing && !dmUi.composing && ev.keyCode !== 229) {
        ev.preventDefault(); sendDM();
    } else if (ev.key === "Escape") { dmClosePanels(); dmBlurKeyboard(); }
}

function dmFootHTML() {
    const tile = (label, action, media) => '<button type="button" class="dm-plus-tile"'
        + (media ? ' data-dm-mutual="1"' : '') + ' onclick="' + action + '">' + label + '</button>';
    return '<div class="dm-tools">'
        + '<button type="button" class="dm-tool" id="dm-mode-btn" aria-label="切换到语音输入" onclick="dmToggleInputMode()"></button>'
        + '<div class="dm-input-slot">'
        + '<input id="dm-input" type="text" maxlength="' + CM_LIMITS.dm + '" placeholder="说点什么…" aria-label="私信内容"'
        + ' onfocus="dmInputFocus()" onselect="dmRememberCaret()" onkeyup="dmRememberCaret()" onclick="dmRememberCaret()" oninput="dmRememberCaret()" oncompositionstart="dmUi.composing=true" oncompositionend="dmUi.composing=false" onkeydown="dmInputKey(event)">'
        + '<button type="button" class="dm-input-mic" id="dm-input-mic" aria-label="切换到语音输入" onclick="dmToggleInputMode()"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/></svg></button>'
        + '<button type="button" class="dm-hold-bar" id="dm-hold-bar" hidden aria-label="按住说话，松开发送" onpointerdown="dmHoldDown(event)" onpointermove="dmHoldMove(event)" onpointerup="dmHoldUp(event)" onpointercancel="dmHoldCancel()" oncontextmenu="return false">按住 说话</button>'
        + '</div>'
        + '<button type="button" class="dm-tool" id="dm-emoji-btn" aria-label="表情面板" aria-controls="dm-emoji-panel" aria-expanded="false" onclick="toggleDmPanel(\'emoji\')">'
        + '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 14q4 5 8 0M8 8h.01M16 8h.01"/></svg></button>'
        + '<button type="button" class="dm-tool" id="dm-plus-btn" aria-label="更多功能" aria-controls="dm-plus-panel" aria-expanded="false" onclick="toggleDmPanel(\'plus\')">'
        + '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M4 12h16"/></svg></button>'
        + '<button type="button" class="td-btn dm-send" id="dm-send-btn" onclick="sendDM()">发送</button></div>'
        + '<section class="dm-panel" id="dm-emoji-panel" aria-label="表情" hidden>'
        + '<div class="dm-sticker-tabs" role="tablist" aria-label="表情来源">'
        + [['official','轻小团'],['emoji','普通表情'],['network','网络表情'],['local','本地表情']].map(t => '<button type="button" role="tab" id="dm-tab-' + t[0]
            + '" aria-controls="dm-sticker-content" aria-selected="' + (t[0] === 'official') + '" onclick="dmSelectStickerTab(\'' + t[0] + '\')">' + t[1] + '</button>').join('')
        + '</div><form class="dm-sticker-search" id="dm-sticker-search" onsubmit="event.preventDefault();dmSearchStickers()">'
        + '<div class="dm-source-row" id="dm-source-row" hidden><label for="dm-provider">来源</label><div class="dm-select-wrap"><select id="dm-provider" aria-label="网络表情来源" onchange="dmUi.searchSeq++;dmUi.results=[]"><option value="cn" selected>中文梗图（360 / 百度）</option><option value="memegen">Memegen 模板</option><option value="openmoji">OpenMoji 表情</option><option value="commons">Commons 图片</option></select></div></div>'
        + '<div class="dm-search-row"><input id="dm-sticker-query" type="search" maxlength="60" aria-label="搜索表情" placeholder="搜梗图/表情，如 你好、猫、无语" oninput="dmFilterOfficial()">'
        + '<button type="submit" class="dm-search-btn" aria-label="搜索"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg><span>搜索</span></button></div></form><div id="dm-sticker-content" role="tabpanel" aria-labelledby="dm-tab-official">'
        + '<p class="dm-panel-note" role="status">正在读取轻小团…</p></div></section>'
        + '<section class="dm-panel" id="dm-plus-panel" aria-label="更多功能" hidden><div class="dm-plus-grid">'
        + tile('相册', "document.getElementById('dm-image-file').click()", true)
        + tile('拍照', "document.getElementById('dm-camera-file').click()", true)
        + tile('视频', "document.getElementById('dm-video-file').click()", true)
        + tile('常用语', 'dmShowPhrases()', false) + '</div>'
        + '<p class="dm-lock-hint" id="dm-lock-hint">互相关注后才能发图片和视频；表情、语音不受此限制。</p>'
        + '<div class="dm-phrases" id="dm-phrases" hidden>' + DM_PHRASES.map(p => '<button type="button" onclick="dmUsePhrase(\'' + escapeHtml(p) + '\')">' + escapeHtml(p) + '</button>').join('') + '</div></section>'
        + '<section id="dm-quote-bar" class="dm-quote-bar" hidden></section>'
        + '<section id="dm-draft" class="dm-draft" aria-label="待发送附件" hidden></section>'
        + '<section class="dm-panel dm-voice-panel" id="dm-voice-panel" aria-label="语音录制与预览" hidden></section>'
        + '<input type="file" id="dm-sticker-file" accept="image/gif,image/png,image/webp,image/jpeg" class="file-hidden" onchange="dmPickSticker(this)">'
        + '<input type="file" id="dm-image-file" accept="image/*" class="file-hidden" onchange="dmPickMedia(this,\'image\')">'
        + '<input type="file" id="dm-camera-file" accept="image/*" capture="environment" class="file-hidden" onchange="dmPickMedia(this,\'image\')">'
        + '<input type="file" id="dm-video-file" accept="video/mp4,video/webm" class="file-hidden" onchange="dmPickMedia(this,\'video\')">';
}
function dmMountComposer() {
    const uid = Number(cm.thread.partner.id);
    if (dmUi.threadId !== uid || !cmEl("dm-input")) {
        dmCleanup(); dmUi.threadId = uid;
        qsSetFoot(dmFootHTML());
        try { dmUi.voiceMode = localStorage.getItem('QINGSU_DM_INPUT_MODE') === 'voice'; } catch (e) { dmUi.voiceMode = false; }
        dmPaintInputMode();
        dmBindStickerScroll();
        const s = dmScope();
        dmLoadOfficial().then(() => { if (dmScopeAlive(s)) { dmPaintOfficial(); dmRenderBubbles(); } });
    }
    const mutual = !!cm.thread.partner.mutual_follow;
    dmPaintQuote();
    const foot = cmEl("pl-foot");
    if (foot) foot.querySelectorAll("[data-dm-mutual]").forEach(el => { el.disabled = !mutual; });
    const hint = cmEl("dm-lock-hint"); if (hint) hint.hidden = mutual;
}
async function dmLoadOfficial() {
    if (dmOfficial.loaded) return;
    if (dmOfficial.task) return dmOfficial.task;
    dmOfficial.task = (async () => {
        try {
            // APK assets and the website share the same relative asset root. Never use API_BASE here.
            const r = await fetch(new URL("stickers.json", document.baseURI).href, { credentials: "omit" });
            if (!r.ok) throw new Error("清单未读到");
            const manifest = await r.json();
            if (!manifest || !Array.isArray(manifest.items)) throw new Error("清单格式不正确");
            const seen = new Set();
            dmOfficial.items = manifest.items.filter(x => x && /^[a-z0-9_-]{1,64}$/i.test(x.id)
                && /^stickers\/[a-z0-9_-]+\.svg$/i.test(x.file) && typeof x.name === "string" && !seen.has(x.id) && seen.add(x.id))
                .map(x => Object.assign({}, x, { url: new URL(x.file, document.baseURI).href }));
            dmOfficial.byId = new Map(dmOfficial.items.map(x => [x.id, x]));
            dmOfficial.loaded = true;
        } catch (e) { /* Inline fallback stays usable; reopening retries the manifest. */ }
        finally { dmOfficial.task = null; }
    })();
    return dmOfficial.task;
}
function dmPaintOfficial() {
    if (dmUi.tab !== "official") return;
    const host = cmEl("dm-sticker-content"); if (!host) return;
    const q = dmUi.query.toLowerCase().trim();
    const items = dmOfficial.items.filter(x => [x.name, x.group, x.pinyin, ...(Array.isArray(x.tags) ? x.tags : [])].join(' ').toLowerCase().includes(q));
    host.innerHTML = '<p class="dm-panel-note">轻小团 · 选择后预览，确认再发送</p>'
        + (items.length ? '<div class="dm-sticker-grid">' + items.map(x => '<button type="button" class="dm-sticker-tile" aria-label="选择' + escapeHtml(x.name)
            + '表情" onclick="sendSticker(\'qs:' + x.id + '\')"><img src="' + escapeHtml(x.url) + '" alt="" loading="lazy"><span>' + escapeHtml(x.name) + '</span></button>').join('') + '</div>'
        : '<p class="dm-panel-note" role="status">' + (dmOfficial.loaded ? '没有匹配的轻小团，试试“加油”或 jiayou。' : '官方表情暂未读到，重新打开可重试；也可上传本地表情。') + '</p>');
}
function dmFilterOfficial() {
    dmUi.query = (cmEl("dm-sticker-query")?.value || "").slice(0, 60);
    if (dmUi.tab === "official") dmPaintOfficial();
    else { dmUi.searchSeq++; dmUi.results = []; }
}
function dmStickerStart() {
    return '<div class="dm-empty dm-empty-start"><div class="dm-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg></div>'
        + '<b>搜中文梗图</b><p>来源：360 / 百度图片公开检索；版权归原作者，未声明许可。选择后先预览，确认再发送。</p>'
        + '<div class="dm-suggest">' + ['你好', '猫', '无语', '开心'].map(word => '<button type="button" onclick="dmSuggestion(\'' + word + '\')">' + word + '</button>').join('') + '</div></div>';
}
function dmSuggestion(q) {
    const input = cmEl('dm-sticker-query'); if (input) input.value = q;
    dmSearchStickers();
}
function dmSelectStickerTab(tab) {
    if (!["official", "emoji", "network", "local"].includes(tab)) return;
    dmUi.tab = tab; dmUi.searchSeq++; dmUi.results = []; dmUi.query = "";
    const input = cmEl("dm-sticker-query"); if (input) { input.value = ""; input.placeholder = tab === "network" ? "搜梗图/表情，如 你好、猫、无语" : "搜名称、拼音或关键词"; }
    const form = cmEl("dm-sticker-search"); if (form) form.hidden = tab === "local" || tab === "emoji";
    const sourceRow = cmEl('dm-source-row'); if (sourceRow) sourceRow.hidden = tab !== 'network';
    ["official", "emoji", "network", "local"].forEach(k => cmEl("dm-tab-" + k)?.setAttribute("aria-selected", String(k === tab)));
    const host = cmEl("dm-sticker-content"); if (!host) return;
    host.setAttribute("aria-labelledby", "dm-tab-" + tab);
    if (tab === "official") { dmPaintOfficial(); return; }
    if (tab === "emoji") {
        host.innerHTML = DM_EMOJIS.map(g => '<section class="dm-emoji-group"><h4>' + escapeHtml(g[0]) + '</h4><div class="dm-emoji-grid">'
            + g[1].map(e => '<button type="button" class="dm-emoji" aria-label="插入' + e + '" onclick="sendSticker(\'' + e + '\')">' + e + '</button>').join('') + '</div></section>').join('');
        return;
    }
    host.innerHTML = tab === "network" ? dmStickerStart()
        : '<div class="dm-local-sticker"><button type="button" onclick="document.getElementById(\'dm-sticker-file\').click()"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m4 16 5-5 4 4 3-3 4 4"/><circle cx="9" cy="9" r="1.3"/></svg><span>选择本地表情</span></button><p class="dm-panel-note">GIF、PNG、WEBP 或 JPEG；只上传你有权使用的图片。不需要互关。</p></div>';
}
function dmExternalURL(value) {
    try { const u = new URL(String(value)); return u.protocol === "https:" && !u.username && !u.password ? u.href : ""; }
    catch (e) { return ""; }
}
function dmAttributionHidden(meta) {
    if (!meta) return false;
    if (meta.attribution === "hidden") return true;
    return /未声明/.test(String(meta.license || ""));
}
function dmNetworkItemHTML(item, index) {
    const preview = dmExternalURL(item.preview_url);
    return '<article class="dm-network-item"><div class="dm-network-thumb">'
        + (preview ? '<img src="' + escapeHtml(preview) + '" alt="' + escapeHtml(item.title || '素材预览')
            + '" crossorigin="anonymous" referrerpolicy="no-referrer" loading="lazy">' : '<span class="dm-panel-note">无可用预览</span>')
        + '</div><div class="dm-network-body"><b>' + escapeHtml(item.title || '未命名素材') + '</b>'
        + '<button type="button" data-dm-import="1" aria-label="选择表情" onclick="dmImportSticker(' + index + ')">选择</button></div></article>';
}
function dmStickerEmpty(detail) {
    const q = dmUi.query || (cmEl('dm-sticker-query')?.value || '').trim();
    return '<div class="dm-empty"><div class="dm-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg></div>'
        + '<b>' + (q ? '没搜到“' + escapeHtml(q) + '”' : '没搜到梗图') + '</b><p>' + escapeHtml(detail || '换个更短的关键词，或用这句话生成一张。') + '</p>'
        + '<div class="dm-suggest">' + ['你好', '猫', '无语', '开心'].map(word => '<button type="button" onclick="dmSuggestion(\'' + word + '\')">' + word + '</button>').join('') + '</div>'
        + '<button type="button" class="dm-generate-btn" onclick="dmGenerateMeme()">用这句话生成梗图</button></div>';
}
function dmPaintNetwork(result, provider, append) {
    const host = cmEl('dm-sticker-content'); if (!host) return;
    const items = (Array.isArray(result.items) ? result.items : []).filter(x => x && typeof x.id === 'string');
    const first = !append;
    dmUi.results = append ? dmUi.results.concat(items) : items;
    dmUi.searchHasMore = !!result.has_more;
    if (result.available === false && !dmUi.results.length) {
        host.innerHTML = dmStickerEmpty(result.detail || '这个来源暂时不可用');
        return;
    }
    if (!dmUi.results.length) {
        host.innerHTML = dmStickerEmpty(result.detail || '');
        return;
    }
    host.innerHTML = (first ? '<div class="dm-results-head"><p class="dm-panel-note">中文梗图</p>'
        + '<button type="button" class="dm-generate-link" onclick="dmGenerateMeme()">按文字生成</button></div>' : '')
        + '<div class="dm-network-grid">' + dmUi.results.map(dmNetworkItemHTML).join('') + '</div>'
        + (dmUi.searchHasMore
            ? '<div class="dm-more-wrap"><button type="button" class="dm-more-btn" id="dm-more-btn" onclick="dmLoadMoreStickers()">加载更多</button></div>'
            : '<p class="dm-panel-note dm-end-note">没有更多了</p>');
}
async function dmLoadMoreStickers() {
    if (dmUi.tab !== 'network' || dmUi.busy || dmUi.moreLoading || !dmUi.searchHasMore || !dmUi.query) return;
    dmUi.moreLoading = true;
    const s = dmScope(), seq = dmUi.searchSeq, page = dmUi.searchPage + 1, provider = dmUi.provider;
    const btn = cmEl('dm-more-btn'); if (btn) { btn.disabled = true; btn.textContent = '正在加载…'; }
    try {
        const r = await getJson('/api/chat/stickers/search?q=' + encodeURIComponent(dmUi.query)
            + '&provider=' + encodeURIComponent(provider) + '&page=' + page);
        if (!dmScopeAlive(s) || seq !== dmUi.searchSeq || dmUi.tab !== 'network') return;
        if (r.code !== 0) {
            if (btn) { btn.disabled = false; btn.textContent = '加载更多'; }
            callNativeToast(r.detail || '加载失败，稍后再试');
            return;
        }
        dmUi.searchPage = page;
        dmPaintNetwork(r, provider, true);
    } catch (e) {
        if (dmScopeAlive(s) && seq === dmUi.searchSeq) {
            if (btn) { btn.disabled = false; btn.textContent = '加载更多'; }
            callNativeToast(e.message || '网络不通');
        }
    } finally {
        dmUi.moreLoading = false;
    }
}
function dmBindStickerScroll() {
    const panel = cmEl('dm-emoji-panel');
    if (!panel || panel.dataset.scrollBound) return;
    panel.dataset.scrollBound = '1';
    panel.addEventListener('scroll', () => {
        if (dmUi.tab !== 'network' || !dmUi.searchHasMore || dmUi.moreLoading) return;
        if (panel.scrollHeight - panel.scrollTop - panel.clientHeight < 180) dmLoadMoreStickers();
    }, { passive: true });
}
async function dmSearchStickers() {
    if (dmUi.tab === "official") { dmFilterOfficial(); return; }
    if (dmUi.tab !== "network" || dmUi.busy || !cm.thread) return;
    const q = (cmEl("dm-sticker-query")?.value || "").trim().slice(0, 60);
    if (!q) { callNativeToast("先输入要搜索的关键词"); return; }
    const provider = cmEl('dm-provider')?.value || dmUi.provider || 'cn';
    dmUi.provider = provider;
    dmUi.query = q; dmUi.results = []; dmUi.searchPage = 0; dmUi.searchHasMore = false;
    const key = String(state.user && state.user.id) + '\n' + provider + '\n' + q, cached = dmSearchCache.get(key);
    if (cached && Date.now() - cached.at < 5 * 60 * 1000) {
        dmUi.searchPage = Number(cached.data.page || 0);
        dmPaintNetwork(cached.data, provider);
        return;
    }
    const s = dmScope(), seq = ++dmUi.searchSeq, host = cmEl("dm-sticker-content");
    host.innerHTML = '<div class="dm-search-loading" role="status"><span class="dm-spinner"></span>正在搜「' + escapeHtml(q) + '」…</div>';
    try {
        const r = await getJson("/api/chat/stickers/search?q=" + encodeURIComponent(q) + '&provider=' + encodeURIComponent(provider) + '&page=0');
        if (!dmScopeAlive(s) || seq !== dmUi.searchSeq || dmUi.tab !== "network") return;
        if (r.code !== 0) { host.innerHTML = dmStickerEmpty(r.detail || '搜索没成功，请稍后再试'); return; }
        if (r.available !== false && Array.isArray(r.items) && r.items.length) {
            dmSearchCache.set(key, { at: Date.now(), data: r });
            while (dmSearchCache.size > 20) dmSearchCache.delete(dmSearchCache.keys().next().value);
        }
        dmPaintNetwork(r, provider);
    } catch (e) {
        if (dmScopeAlive(s) && seq === dmUi.searchSeq) host.innerHTML = dmStickerEmpty(e.message || '网络不通');
    }
}
function dmLoadMemeImage(src) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        if (/^https:/i.test(src)) image.crossOrigin = 'anonymous';
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error('模板图没取到'));
        image.src = src;
    });
}
function dmFallbackMemeBackground() {
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 420;
    const ctx = canvas.getContext('2d'), gradient = ctx.createLinearGradient(0, 0, 640, 420);
    gradient.addColorStop(0, '#0F766E'); gradient.addColorStop(1, '#065F46');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 640, 420);
    ctx.globalAlpha = 0.12; ctx.fillStyle = '#FFFFFF';
    ctx.beginPath(); ctx.arc(520, 80, 150, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(90, 360, 120, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    canvas.__fallback = true;
    return canvas;
}
async function dmMemeBackground() {
    const src = window.__QS_TEST_MEME_BG__ || 'https://api.memegen.link/images/drake.jpg?width=640';
    try { return await dmLoadMemeImage(src); }
    catch (error) { if (window.__QS_TEST_MEME_BG__) throw error; return dmFallbackMemeBackground(); }
}
function dmRenderMeme(text, background) {
    const sourceWidth = background.naturalWidth || background.width || 640;
    const sourceHeight = background.naturalHeight || background.height || 420;
    const width = Math.min(720, sourceWidth), height = Math.max(240, Math.round(width * sourceHeight / sourceWidth));
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d'); ctx.drawImage(background, 0, 0, width, height);
    const maxChars = Math.max(5, Math.floor(width / 44));
    const lines = []; let line = '';
    for (const char of text) {
        if (line && (line + char).length > maxChars) { lines.push(line); line = char; }
        else line += char;
    }
    if (line) lines.push(line);
    const font = Math.max(26, Math.min(50, Math.floor(width / 12)));
    ctx.font = '800 ' + font + 'px "Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(0,0,0,.82)'; ctx.lineWidth = Math.max(6, Math.round(font / 7)); ctx.fillStyle = '#FFFFFF';
    let y = Math.round(height * 0.07);
    for (const textLine of lines.slice(0, 3)) {
        ctx.strokeText(textLine, width / 2, y); ctx.fillText(textLine, width / 2, y);
        y += Math.round(font * 1.12);
    }
    return new Promise((resolve, reject) => {
        if (!canvas.toBlob) { reject(new Error('当前客户端不支持导出图片')); return; }
        canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('导出失败')), 'image/png');
    });
}
async function dmGenerateMeme() {
    const q = (cmEl('dm-sticker-query')?.value || dmUi.query || '').trim().slice(0, 40);
    if (!q) { callNativeToast('先输入一句话再生成'); return; }
    if (dmUi.busy || !cm.thread) return;
    dmStickerBusy(true); callNativeToast('正在生成梗图…');
    try {
        const background = await dmMemeBackground();
        const blob = await dmRenderMeme(q, background);
        const file = typeof File === 'function' ? new File([blob], 'text-meme.png', { type: 'image/png' }) : blob;
        dmStickerBusy(false);
        dmSetDraft({ kind: 'sticker', file, url: URL.createObjectURL(blob), objectURL: true, label: '文字梗图：' + q,
            meta: { license: background.__fallback ? '文字卡片，无外部模板' : '模板原图许可未声明',
                    author: background.__fallback ? '轻塑生成' : 'Memegen 模板' } });
    } catch (e) {
        dmStickerBusy(false);
        callNativeToast('生成没成功：' + (e.message || '网络不通'));
    }
}
function dmStickerBusy(on) {
    dmUi.busy = on;
    cmEl("dm-sticker-content")?.querySelectorAll("[data-dm-import],.dm-local-sticker button,.dm-generate-btn,.dm-generate-link,.dm-suggest button").forEach(b => { b.disabled = on; });
}
function dmImportSticker(index) {
    const item = dmUi.results[index];
    if (!item || dmUi.busy || !cm.thread) return;
    dmSetDraft({ kind: 'sticker', providerId: item.id, url: dmExternalURL(item.preview_url), label: item.title || '网络表情', meta: item });
}
function dmPickSticker(input) {
    const file = input?.files?.[0]; if (input) input.value = '';
    if (!file || !cm.thread || dmUi.busy) return;
    if (!/^image\/(gif|png|webp|jpeg)$/i.test(file.type || '') && !/\.(gif|png|webp|jpe?g)$/i.test(file.name || '')) { callNativeToast('请选择 GIF、PNG、WEBP 或 JPEG 表情'); return; }
    if (file.size > 8 * 1024 * 1024) { callNativeToast('表情图片不能超过 8MB'); return; }
    dmSetDraft({ kind: 'sticker', file, url: URL.createObjectURL(file), objectURL: true, label: '本地表情' });
}
function dmClearDraft() {
    const d = dmUi.draft; dmUi.draft = null;
    if (d?.objectURL) URL.revokeObjectURL(d.url);
    const host = cmEl('dm-draft'); if (host) { dmReleasePlayback(host); host.innerHTML = ''; host.hidden = true; }
}
function dmPaintQuote() {
    const host = cmEl('dm-quote-bar'); if (!host) return;
    const q = dmUi.quote;
    if (!q) { host.hidden = true; host.innerHTML = ''; return; }
    host.hidden = false;
    host.innerHTML = '<div class="dm-quote-main"><b>' + escapeHtml(q.name || '消息') + '：</b>'
        + escapeHtml(q.text || '') + '</div>'
        + '<button type="button" aria-label="取消引用" onclick="dmClearQuote()">×</button>';
}
function dmClearQuote() { dmUi.quote = null; dmPaintQuote(); }
function dmStartQuote(mid) {
    qsHideMenu();
    const m = qsFindBubble(Number(mid));
    if (!m || m.recalled_at) return;
    const kind = m.kind || 'text';
    const text = kind === 'text' ? String(m.body || '').trim().replace(/\n/g, ' ').slice(0, 60)
        : ({ image: '[图片]', video: '[视频]', audio: '[语音]', sticker: '[表情]' }[kind] || '[消息]');
    const mine = qsSameId(m.from_id, state.user && state.user.id);
    const who = mine ? (state.user || {}) : ((cm.thread && cm.thread.partner) || {});
    dmUi.quote = { id: Number(m.id), name: String(cmName(who) || '').slice(0, 20), text };
    dmPaintQuote();
    dmInputFocus();
}
function dmJumpQuote(mid) {
    const node = document.querySelector('#thread-bubbles [data-dm-key="m' + Number(mid) + '"]');
    if (node) { node.scrollIntoView({ block: 'center', behavior: 'smooth' }); node.classList.add('dm-quote-flash'); setTimeout(() => node.classList.remove('dm-quote-flash'), 900); }
    else callNativeToast('这条消息不在当前加载范围里');
}
function dmSetDraft(d) {
    if (dmUi.busy) { if (d.objectURL) URL.revokeObjectURL(d.url); return; }
    dmCancelRecording(); dmClearDraft(); dmClosePanels(); dmBlurKeyboard();
    d.scope = dmScope(); d.rid = dmRequestId(); dmUi.draft = d;
    const host = cmEl('dm-draft'); if (!host) return;
    host.hidden = false;
    host.innerHTML = (d.kind === 'video' ? '<video controls playsinline src="' + escapeHtml(d.url) + '"></video>' : '<img src="' + escapeHtml(d.url) + '" alt="待发送预览" referrerpolicy="no-referrer">')
        + '<div><b>' + escapeHtml(d.label || '待发送附件') + '</b>' + (d.meta && !dmAttributionHidden(d.meta) ? '<p>' + escapeHtml(d.meta.license || '') + ' · ' + escapeHtml(d.meta.author || '') + '</p>' : '')
        + '<p id="dm-draft-status" role="status">确认后点发送</p></div><button type="button" id="dm-draft-cancel" onclick="dmClearDraft()">取消</button>';
}
async function dmSendDraft() {
    const d = dmUi.draft;
    if (!d || dmUi.busy || !dmScopeAlive(d.scope)) return;
    const s = d.scope, rid = d.rid;
    dmStickerBusy(true);
    const cancel = cmEl('dm-draft-cancel'); if (cancel) cancel.disabled = true;
    cmText('dm-draft-status', '发送中…');
    try {
        if (!d.text && !d.mediaName) {
            let up;
            if (d.providerId) up = await rawPostApi('/api/chat/stickers/import', { id: d.providerId });
            else {
                const fd = new FormData(); fd.append('file', d.file);
                if (d.kind !== 'sticker') fd.append('to', String(s.threadId));
                up = await rawPostApi(d.kind === 'sticker' ? '/api/chat/stickers/upload' : '/api/chat/media', fd);
            }
            if (!dmScopeAlive(s) || dmUi.draft !== d) return;
            if (!up?.name || up.kind !== d.kind) throw new Error('附件上传结果不完整');
            d.mediaName = up.name;
        }
        if (!dmScopeAlive(s) || dmUi.draft !== d) return;
        dmPending(rid, s, { kind: d.kind, body: d.text || '', media_url: d.url }); paintThread();
        const quote = dmUi.quote;
        const r = await rawPostApi('/api/chat/send', { to: s.threadId, kind: d.kind, text: d.text || '', media_name: d.mediaName || '', request_id: rid, quote_id: quote ? quote.id : 0 });
        dmAck(rid, r.message, s);
        if (quote && dmUi.quote && dmUi.quote.id === quote.id) dmClearQuote();
        if (dmScopeAlive(s) && dmUi.draft === d) dmClearDraft();
    } catch (e) {
        if (dmAccountAlive(s)) delete cm.pending[rid];
        if (dmScopeAlive(s) && dmUi.draft === d) { cmText('dm-draft-status', '发送未确认，可重试：' + (e.message || '网络不通')); paintThread(); }
    } finally { if (dmScopeAlive(s)) { dmStickerBusy(false); if (cancel) cancel.disabled = false; } }
}
function toggleDmPanel(which) {
    if (!["emoji", "plus"].includes(which)) return;
    const target = cmEl("dm-" + which + "-panel"), open = target && !target.hidden;
    dmRememberCaret(); dmCancelRecording(); dmBlurKeyboard(); dmClosePanels();
    if (target && !open) {
        target.hidden = false; dmUi.panel = which;
        cmEl("dm-" + which + "-btn")?.setAttribute("aria-expanded", "true");
        if (which === "emoji" && dmUi.tab === "official") {
            const s = dmScope(); dmLoadOfficial().then(() => { if (dmScopeAlive(s)) { dmPaintOfficial(); dmRenderBubbles(); } });
        }
    }
}
function dmShowPhrases() { const box = cmEl("dm-phrases"); if (box) box.hidden = !box.hidden; }
function dmUsePhrase(text) { const input = cmEl("dm-input"); if (input) { input.value = text; input.focus(); } }
function sendSticker(text) {
    if (!cm.thread || dmUi.busy) return;
    if (text.startsWith('qs:')) {
        const item = dmOfficial.byId.get(text.slice(3));
        if (!item) { callNativeToast('这枚表情尚未读取，请重试'); return; }
        dmSetDraft({ kind: 'sticker', text, url: item.url, label: item.name });
    } else {
        const i = cmEl('dm-input'); if (!i) return;
        const [start, end] = dmUi.caret;
        const value = i.value.slice(0, start) + text + i.value.slice(end);
        if (value.length > CM_LIMITS.dm) return;
        i.value = value; dmUi.caret = [start + text.length, start + text.length];
        i.setSelectionRange?.(...dmUi.caret);
    }
}
function dmPickMedia(input, kind) {
    const file = input?.files?.[0]; if (input) input.value = '';
    if (!file || !cm.thread || !['image', 'video'].includes(kind) || dmUi.busy) return;
    if (!cm.thread.partner.mutual_follow) { callNativeToast('互相关注后才能发图片和视频'); return; }
    if (file.size > (kind === 'image' ? 8 : 30) * 1024 * 1024) { callNativeToast('附件过大，请缩小后重试'); return; }
    dmSetDraft({ kind, file, url: URL.createObjectURL(file), objectURL: true, label: kind === 'image' ? '图片' : '视频' });
}

function dmNow() { return typeof performance !== 'undefined' ? performance.now() : Date.now(); }
function dmStopTracks(stream) { if (stream) stream.getTracks().forEach(t => { try { t.stop(); } catch (e) {} }); }
// 麦克风热流：WebView 里 getUserMedia 冷启动要 1~3 秒，按住才去要就会一直卡在“准备麦克风”。
// 进语音模式或按下时先要，录音器直接复用它；录完保留 20 秒，下一条消息按下即录。
const dmMic = { stream: null, pending: null, timer: 0 };
function dmMicLive() {
    const s = dmMic.stream;
    return !!(s && s.getAudioTracks().some(t => t.readyState === 'live'));
}
function dmMicRelease() {
    clearTimeout(dmMic.timer); dmMic.timer = 0;
    const s = dmMic.stream; dmMic.stream = null;
    dmStopTracks(s);
}
function dmMicKeep(ms) {
    clearTimeout(dmMic.timer);
    dmMic.timer = setTimeout(dmMicRelease, ms || 20000);
}
function dmWarmMic() {
    if (dmMicLive()) { dmMicKeep(); return Promise.resolve(dmMic.stream); }
    if (dmMic.pending) return dmMic.pending;
    const p = (async () => {
        if (dmCall.state !== 'idle') throw new Error('通话中不能录音');
        const allowed = await dmEnsureMicrophone();
        if (!allowed) { const err = new Error('麦克风权限未获准'); err.name = 'NotAllowedError'; throw err; }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (dmCall.state !== 'idle') { dmStopTracks(stream); throw new Error('通话中不能录音'); }
        dmMic.stream = stream; dmMicKeep();
        return stream;
    })();
    dmMic.pending = p;
    const clear = () => { if (dmMic.pending === p) dmMic.pending = null; };
    p.then(clear, clear);
    return p;
}
function dmCancelRecording() {
    clearTimeout(dmHold.timer); dmHold.pending = false; dmHold.held = false;
    const rec = dmUi.record; dmUi.record = null;
    if (rec) {
        rec.cancelled = true; clearInterval(rec.tick); clearTimeout(rec.limit);
        try { if (rec.recorder && rec.recorder.state !== 'inactive') rec.recorder.stop(); } catch (e) {}
        if (rec.url) { dmReleasePlayback(cmEl('dm-voice-panel')); URL.revokeObjectURL(rec.url); rec.url = ''; }
        rec.chunks = []; rec.blob = null;
    }
    if (dmMicLive()) dmMicKeep();
    const panel = cmEl('dm-voice-panel'); if (panel) { panel.hidden = true; panel.innerHTML = ''; }
    cmEl('dm-hold-bar')?.setAttribute('aria-expanded', 'false');
    dmHoldPaint();
    dmHoldRender();
}
function dmPaintVoice(rec) {
    const panel = cmEl('dm-voice-panel'); if (!panel || dmUi.record !== rec) return;
    cmEl('dm-hold-bar')?.setAttribute('aria-expanded', 'true');
    if (rec.hold) {
        panel.hidden = true; panel.innerHTML = '';
        dmHoldRender();
        return;
    }
    panel.hidden = false;
    if (rec.status === 'preview') {
        panel.innerHTML = '<div class="dm-voice-head"><b>语音预览</b><span>' + rec.duration + ' 秒' + (rec.autoStopped ? ' · 已达 10 分钟上限' : '') + '</span></div>'
            + '<audio id="dm-voice-preview" src="' + escapeHtml(rec.url) + '" controls preload="metadata" aria-label="试听录制的语音"></audio>'
            + '<p class="dm-panel-note" id="dm-voice-status" role="status">仅保存在本机，确认发送后才上传。</p>'
            + '<div class="dm-voice-actions"><button type="button" onclick="dmCancelRecording()">取消</button><button type="button" class="dm-confirm" id="dm-voice-send" onclick="dmSendAudio()">发送语音</button></div>';
    } else {
        panel.innerHTML = '<div class="dm-voice-head"><b>' + (rec.status === 'starting' ? '正在请求麦克风…' : '正在录音') + '</b><span id="dm-voice-time" role="timer">0:00 / 10:00</span></div>'
            + '<p class="dm-panel-note">停止后可试听；退出聊天或切到后台会取消录音。</p><div class="dm-voice-actions">'
            + '<button type="button" onclick="dmCancelRecording()">取消</button><button type="button" class="dm-confirm" id="dm-voice-stop"'
            + (rec.status === 'starting' ? ' disabled' : '') + ' onclick="dmStopRecording()">停止并试听</button></div>';
    }
}
function dmMicHelp(message) {
    const text = message || '麦克风权限没打开。发语音需要麦克风权限，去系统设置里允许后回来重试。';
    let go = false;
    try { go = window.confirm(text + '\n\n现在去设置？'); } catch (e) { go = false; }
    if (!go) return;
    if (window.AndroidBridge && typeof window.AndroidBridge.openAppSettings === 'function') {
        try { window.AndroidBridge.openAppSettings(); return; } catch (e) { /* fall through */ }
    }
    callNativeToast('请到系统设置里允许轻塑使用麦克风');
}
async function dmEnsureMicrophone() {
    const bridge = window.AndroidBridge;
    if (!bridge || typeof bridge.requestMicrophonePermission !== 'function') return true;
    let state = 'unknown';
    try {
        if (typeof bridge.microphonePermissionState === 'function') state = bridge.microphonePermissionState();
    } catch (e) { state = 'unknown'; }
    if (state === 'granted') return true;
    if (state === 'blocked') return false;
    return await new Promise(resolve => {
        let settled = false;
        const finish = ok => {
            if (settled) return;
            settled = true; window.qsMicPermissionResult = null; resolve(!!ok);
        };
        window.qsMicPermissionResult = finish;
        try { bridge.requestMicrophonePermission(); }
        catch (e) { finish(true); return; }
        setTimeout(() => finish(false), 20000);
    });
}
const DM_HOLD_HTML = '<div class="dm-hold-bubble" aria-hidden="true">'
    + '<span class="dm-hold-wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>'
    + '<span class="dm-hold-sec" id="dm-hold-sec">0″</span></div>'
    + '<div class="dm-hold-pills">'
    + '<button type="button" class="dm-hold-pill" onclick="dmHoldCancelTap()">取消</button>'
    + '<div class="dm-hold-pill is-hint">上滑取消</div>'
    + '</div>'
    + '<div class="dm-hold-sheet">'
    + '<div class="dm-hold-sheet-top"><span class="dm-hold-live" id="dm-hold-live">正在录音</span><span id="dm-hold-time" role="timer">0:00</span></div>'
    + '<b id="dm-hold-sheet-main" aria-live="polite">松开 发送</b>'
    + '</div>';
function dmHoldLayer() {
    let layer = cmEl('dm-hold-layer');
    if (!layer) {
        layer = document.createElement('section');
        layer.id = 'dm-hold-layer';
        layer.className = 'dm-hold-layer';
        layer.hidden = true;
        document.body.appendChild(layer);
    }
    return layer;
}
function dmHoldRender() {
    const layer = dmHoldLayer();
    if (!dmHold.pending && !dmHold.held) {
        if (!layer.hidden) { layer.hidden = true; layer.innerHTML = ''; }
        return;
    }
    if (!layer.innerHTML) layer.innerHTML = DM_HOLD_HTML;
    layer.hidden = false;
    const rec = dmUi.record;
    const starting = !rec || rec.status === 'starting';
    layer.classList.toggle('cancel', !!dmHold.cancelled);
    layer.classList.toggle('starting', starting);
    cmText('dm-hold-live', dmHold.cancelled ? '松开会取消' : (starting ? '正在准备麦克风…' : '正在录音'));
    cmText('dm-hold-sheet-main', dmHold.cancelled ? '松开 取消' : '松开 发送');
}
function dmHoldCancelTap() {
    if (!dmHold.pending && !dmHold.held) return;
    clearTimeout(dmHold.timer);
    dmCancelRecording();
    dmHoldPaint();
    dmHoldRender();
    callNativeToast('已取消语音');
}
function dmHoldDown(event) {
    if (event && event.button !== undefined && event.button !== 0) return;
    clearTimeout(dmHold.timer);
    dmHold.pending = false; dmHold.held = true; dmHold.released = false;
    dmHold.cancelled = false; dmHold.startY = event.clientY;
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch (e) {}
    dmHoldRender();
    callNativeVibrate(12);
    dmHoldPaint();
    // 按下就开录（麦克风已热则 10~20ms 就绪）；太短/轻点由松开时统一判掉。
    dmStartRecording(true);
    if (event.cancelable) event.preventDefault();
}
function dmHoldMove(event) {
    if (!dmHold.pending && !dmHold.held) return;
    const cancel = event.clientY < dmHold.startY - 55;
    if (cancel !== dmHold.cancelled) {
        dmHold.cancelled = cancel;
        dmHoldPaint(); dmHoldRender();
        if (cancel) callNativeVibrate(20);
    }
}
function dmHoldUp(event) {
    clearTimeout(dmHold.timer);
    if (dmHold.pending && !dmHold.held) {
        dmHold.pending = false;
        if (dmHold.cancelled) { dmHold.cancelled = false; callNativeToast('已取消语音'); }
        else callNativeToast('按住说话，松开发送');
        dmHoldPaint(); dmHoldRender();
        return;
    }
    if (!dmHold.held) return;
    dmHold.held = false; dmHold.pending = false; dmHold.released = true;
    dmHoldPaint();
    const rec = dmUi.record;
    if (dmHold.cancelled) { dmHold.cancelled = false; dmCancelRecording(); dmHoldRender(); callNativeToast('已取消语音'); return; }
    dmHoldRender();
    if (!rec) { callNativeToast('按住说话，松开发送'); return; }
    if (rec.status === 'starting') { dmCancelRecording(); dmHoldRender(); callNativeToast('说话时间太短，按住说话'); return; }
    if (rec.status !== 'recording') return;
    if (dmNow() - rec.started < 600) { dmCancelRecording(); dmHoldRender(); callNativeToast('说话时间太短，按住说话'); return; }
    callNativeVibrate(10);
    dmStopRecording(true);
}
function dmHoldCancel() {
    clearTimeout(dmHold.timer); dmHold.pending = false;
    if (dmHold.held) { dmHold.held = false; dmCancelRecording(); }
    dmHoldPaint(); dmHoldRender();
}
const DM_VOICE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/></svg>';
const DM_KEYBOARD_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/></svg>';
function dmHoldPaint() {
    const bar = cmEl('dm-hold-bar'); if (!bar) return;
    bar.textContent = dmHold.held ? (dmHold.cancelled ? '松开 取消' : '松开 发送') : '按住 说话';
    bar.classList.toggle('holding', dmHold.held && !dmHold.cancelled);
    bar.classList.toggle('cancel', dmHold.held && dmHold.cancelled);
}
function dmPaintInputMode() {
    const voice = !!dmUi.voiceMode;
    const mode = cmEl('dm-mode-btn'), input = cmEl('dm-input'), mic = cmEl('dm-input-mic');
    const bar = cmEl('dm-hold-bar'), send = cmEl('dm-send-btn');
    if (mode) { mode.innerHTML = voice ? DM_KEYBOARD_ICON : DM_VOICE_ICON; mode.setAttribute('aria-label', voice ? '切换到文字输入' : '切换到语音输入'); }
    if (input) input.hidden = voice;
    if (mic) mic.hidden = voice;
    if (bar) bar.hidden = !voice;
    if (send) send.hidden = voice;
    dmHoldPaint();
}
function dmToggleInputMode() {
    dmUi.voiceMode = !dmUi.voiceMode;
    try { localStorage.setItem('QINGSU_DM_INPUT_MODE', dmUi.voiceMode ? 'voice' : 'text'); } catch (e) {}
    dmCancelRecording(); dmClosePanels(); dmPaintInputMode();
    if (dmUi.voiceMode) { dmBlurKeyboard(); dmWarmMic().catch(() => {}); }
    else { dmMicRelease(); dmInputFocus(); const input = cmEl('dm-input'); if (input) { input.focus(); dmScrollLatest(true); } }
}
async function dmStartRecording(hold) {
    if (!cm.thread) return;
    if (!state.token) { openAuthModal(); return; }
    if (dmUi.busy || dmUi.draft) { callNativeToast('请先发送或取消待发送附件'); return; }
    if (dmUi.record) { callNativeToast('请先发送或取消当前语音'); return; }
    const Recorder = typeof MediaRecorder !== 'undefined' ? MediaRecorder : null;
    const mime = Recorder && typeof Recorder.isTypeSupported === 'function'
        && ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg'].find(t => Recorder.isTypeSupported(t));
    if (!mime || !navigator.mediaDevices?.getUserMedia) { callNativeToast('当前浏览器或客户端不支持语音录制，可发送文字'); return; }
    dmClosePanels(); dmBlurKeyboard();
    const holdMode = hold === true;
    const rec = { scope: dmScope(), status: 'starting', chunks: [], bytes: 0, mime, cancelled: false,
        hold: holdMode, autoSend: holdMode };
    dmUi.record = rec; dmPaintVoice(rec);
    if (!dmScopeAlive(rec.scope) || dmUi.record !== rec || rec.cancelled || document.hidden) return;
    try {
        const stream = await dmWarmMic();
        if (!dmScopeAlive(rec.scope) || dmUi.record !== rec || rec.cancelled || document.hidden) return;
        rec.stream = stream;
        rec.recorder = new Recorder(stream, { mimeType: mime, audioBitsPerSecond: 20000 });
        rec.recorder.ondataavailable = ev => {
            if (rec.cancelled || !ev.data?.size) return;
            rec.chunks.push(ev.data); rec.bytes += ev.data.size;
            if (rec.bytes > DM_AUDIO_MAX && dmUi.record === rec) { dmCancelRecording(); callNativeToast('语音超过 5MB，已取消；请缩短录音'); }
        };
        rec.recorder.onerror = () => { if (dmUi.record === rec) { dmCancelRecording(); callNativeToast('录音中断，未上传；请重试'); } };
        rec.recorder.onstop = () => {
            clearInterval(rec.tick); clearTimeout(rec.limit); if (dmMicLive()) dmMicKeep();
            if (rec.cancelled || dmUi.record !== rec || !dmScopeAlive(rec.scope)) return;
            rec.blob = new Blob(rec.chunks, { type: rec.recorder.mimeType || rec.mime }); rec.chunks = [];
            if (!rec.blob.size || rec.blob.size > DM_AUDIO_MAX) { dmCancelRecording(); callNativeToast('没有录到可发送的语音，请重试'); return; }
            rec.url = URL.createObjectURL(rec.blob); rec.status = 'preview'; dmPaintVoice(rec);
            if (rec.hold && rec.rid && cm.pending[rec.rid]) {
                cm.pending[rec.rid].msg.media_url = rec.url;
                if (dmIsVisible()) paintThread();
            }
            if (rec.autoSend) { rec.autoSend = false; dmSendAudio(); }
        };
        rec.started = dmNow(); rec.status = 'recording'; rec.recorder.start(1000); dmPaintVoice(rec);
        if (rec.hold && dmHold.cancelled) { dmCancelRecording(); return; }
        if (rec.hold && dmHold.released) {
            dmHold.released = false;
            if (dmNow() - rec.started < 600) { dmCancelRecording(); callNativeToast('说话时间太短，按住说话'); return; }
            dmStopRecording(true);
        }
        rec.tick = setInterval(() => {
            if (dmUi.record !== rec || !dmScopeAlive(rec.scope)) return;
            const n = Math.min(600, Math.floor((dmNow() - rec.started) / 1000));
            const clock = Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
            cmText('dm-voice-time', clock + ' / 10:00');
            cmText('dm-hold-time', clock);
            cmText('dm-hold-sec', n + '″');
        }, 1000);
        rec.limit = setTimeout(() => { if (dmUi.record === rec) dmStopRecording(true); }, 599000);
    } catch (e) {
        dmMicRelease();
        if (dmUi.record !== rec || !dmScopeAlive(rec.scope)) return;
        dmCancelRecording();
        const name = String(e.name || '');
        if (/通话/.test(String(e.message || ''))) callNativeToast('通话中不能录音');
        else if (/NotAllowed|Permission|Security/.test(name)) dmMicHelp('麦克风权限未获准，语音发不了。去系统设置允许后回来重试。');
        else if (/NotReadable|TrackStart/.test(name)) callNativeToast('麦克风正被其他应用占用，关掉占用后重试');
        else if (/NotFound|DevicesNotFound/.test(name)) callNativeToast('这台设备没有可用麦克风，发文字吧');
        else if (/Abort/.test(name)) callNativeToast('录音被系统中断了，请重试');
        else callNativeToast('麦克风不可用（' + (name || '未知错误') + '），请重试或检查系统设置');
    }
}
function dmStopRecording(auto) {
    const rec = dmUi.record; if (!rec || rec.status !== 'recording') return;
    rec.duration = Math.min(600, Math.max(1, Math.round((dmNow() - rec.started) / 1000))); rec.autoStopped = !!auto;
    rec.status = 'stopping'; clearInterval(rec.tick); clearTimeout(rec.limit);
    if (dmMicLive()) dmMicKeep();
    // 松开就先把气泡放上屏（上传还没开始），别让用户盯着空白等服务器。
    if (rec.autoSend && !rec.rid) {
        rec.rid = dmRequestId();
        dmPending(rec.rid, rec.scope, { kind: 'audio', duration: rec.duration });
        if (dmIsVisible()) paintThread();
    }
    const btn = cmEl('dm-voice-stop'); if (btn) { btn.disabled = true; btn.textContent = '正在准备试听…'; }
    try { rec.recorder.stop(); } catch (e) { dmCancelRecording(); callNativeToast('录音未能保存，请重试'); }
}
async function dmSendAudio() {
    const rec = dmUi.record;
    if (!rec || rec.status !== 'preview' || rec.uploading || !dmScopeAlive(rec.scope)) return;
    rec.uploading = true; rec.rid = rec.rid || dmRequestId();
    const s = rec.scope, rid = rec.rid, btn = cmEl('dm-voice-send');
    if (btn) { btn.disabled = true; btn.textContent = '发送中…'; }
    cmText('dm-voice-status', '正在上传语音…');
    if (!cm.pending[rid]) dmPending(rid, s, { kind: 'audio', duration: rec.duration });
    if (dmIsVisible()) paintThread();
    try {
        if (!rec.mediaName) {
            const fd = new FormData(), ext = rec.mime.includes('mp4') ? 'm4a' : (rec.mime.includes('ogg') ? 'ogg' : 'webm');
            fd.append('to', String(s.threadId)); fd.append('file', rec.blob, 'voice.' + ext);
            const up = await rawPostApi('/api/chat/media', fd);
            if (!dmScopeAlive(s) || dmUi.record !== rec) { if (dmAccountAlive(s)) delete cm.pending[rid]; return; }
            if (!up?.name || up.kind !== 'audio') throw new Error('语音上传结果不完整');
            rec.mediaName = up.name;
        }
        if (!dmScopeAlive(s) || dmUi.record !== rec) return;
        cmText('dm-voice-status', '正在确认发送…');
        const r = await rawPostApi('/api/chat/send', { to: s.threadId, kind: 'audio', media_name: rec.mediaName, duration: rec.duration, request_id: rid, quote_id: dmUi.quote ? dmUi.quote.id : 0 });
        dmAck(rid, r.message, s);
        if (dmUi.quote) dmClearQuote();
        if (rec.hold) callNativeToast('语音已发送');
        if (dmScopeAlive(s) && dmUi.record === rec) dmCancelRecording();
    } catch (e) {
        if (!dmAccountAlive(s)) return;
        delete cm.pending[rid]; paintThread();
        if (!dmScopeAlive(s) || dmUi.record !== rec) return;
        rec.uploading = false;
        if (rec.hold) {
            // 按住录音失败要看得见：气泡撤回，回到可试听/重试的面板。
            rec.hold = false; rec.autoSend = false;
            dmPaintVoice(rec);
            callNativeToast('语音没发出去，点“发送语音”重试');
        }
        const retry = cmEl('dm-voice-send');
        if (retry) retry.textContent = '重试发送';
        cmText('dm-voice-status', '未确认发送成功：' + (e.message || '网络不通') + '。可用同一条语音重试。');
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        dmCancelRecording();
        dmMicRelease();
        cmEl('thread-bubbles')?.querySelectorAll('audio,video').forEach(el => el.pause());
    }
});
window.addEventListener('pagehide', dmCleanup);

function dmMediaURL(value) {
    if (!value) return '';
    if (/^blob:/.test(value)) return value;
    return /^\/uploads\/[A-Za-z0-9_.-]+\?/.test(String(value)) ? API_BASE + value : '';
}
function dmBubbleInner(m, kind, pending) {
    if (kind === 'sticker' && !m.media_url) {
        const item = dmOfficial.byId.get(String(m.body || '').replace(/^qs:/, ''));
        return item ? '<img class="dm-sticker-img" src="' + escapeHtml(item.url) + '" alt="' + escapeHtml(item.name) + '">'
            : '<span class="dm-sticker">' + escapeHtml(String(m.body || '').startsWith('qs:') ? '［官方表情］' : m.body || '') + '</span>';
    }
    if (['image', 'video', 'audio', 'sticker'].includes(kind)) {
        const url = dmMediaURL(m.media_url), src = escapeHtml(url);
        if (!url) {
            if (kind === 'audio' && pending) return dmAudioPendingBubble(m);
            return '<span class="dm-media-wait">' + (pending ? '发送中…' : '附件暂不可用') + '</span>';
        }
        if (kind === 'audio') return dmAudioBubble(m, src);
        if (kind === 'video') return '<video class="dm-media-video" src="' + src + '" controls playsinline preload="metadata" onplay="dmExclusivePlayback(this)" oncontextmenu="event.stopPropagation();return true"></video>';
        const meta = m.sticker_meta || {}, source = dmExternalURL(meta.source_url);
        return '<img class="' + (kind === 'sticker' ? 'dm-sticker-img' : 'dm-media-img') + '" src="' + src + '" alt="' + (kind === 'sticker' ? '图片表情' : '图片消息') + '" loading="lazy" onclick="viewPostImage(this.src)">'
            + ((source && !dmAttributionHidden(meta)) ? '<small class="dm-attribution"><a href="' + escapeHtml(source) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(meta.title || '来源') + '</a><br>' + escapeHtml(meta.author || '') + ' · ' + escapeHtml(meta.license || '') + '</small>' : '');
    }
    return escapeHtml(m.body || '');
}
function dmAudioPendingBubble(m) {
    const duration = Math.max(1, Number(m.duration || 0));
    return '<div class="dm-audio-wx pending" aria-label="语音发送中">'
        + '<span class="dm-audio-play" aria-hidden="true"><span class="dm-audio-spin"></span></span>'
        + '<span class="dm-audio-wave" aria-hidden="true"><i></i><i></i><i></i></span>'
        + '<span class="dm-audio-time">' + duration + '"</span></div>';
}
function dmAudioBubble(m, src) {    const duration = Math.max(1, Number(m.duration || 0));
    return '<div class="dm-audio-wx" role="button" tabindex="0" aria-label="播放 ' + duration + ' 秒语音" onclick="dmToggleAudio(this)">'
        + '<span class="dm-audio-play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span>'
        + '<span class="dm-audio-wave" aria-hidden="true"><i></i><i></i><i></i></span>'
        + '<span class="dm-audio-time">' + duration + '"</span>'
        + '<audio preload="metadata" src="' + src + '" style="display:none" onplay="dmAudioPlay(this)" onpause="dmAudioPause(this)" onended="dmAudioStop(this)" oncontextmenu="event.stopPropagation();return true"></audio>'
        + '</div>';
}
function dmAudioBox(audio) { return audio && audio.closest ? audio.closest('.dm-audio-wx') : null; }
function dmAudioPlay(audio) { const box = dmAudioBox(audio); if (box) box.classList.add('playing'); }
function dmAudioPause(audio) { const box = dmAudioBox(audio); if (box) box.classList.remove('playing'); }
function dmAudioStop(audio) { dmAudioPause(audio); }
function dmToggleAudio(box) {
    const audio = box && box.querySelector('audio'); if (!audio) return;
    if (audio.paused) audio.play().catch(() => callNativeToast('语音播放失败，请重试'));
    else audio.pause();
}
function dmExclusivePlayback(active) {
    document.querySelectorAll('#thread-bubbles audio,#thread-bubbles video').forEach(el => { if (el !== active) el.pause(); });
}
function dmRenderBubbles() {
    const host = cmEl('thread-bubbles'); if (!host || !cm.thread) return;
    const me = state.user && state.user.id, uid = cm.thread.partner.id;
    const stick = dmUi.stickBottom !== false;
    const nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 100;
    const previousHeight = host.scrollHeight;
    const rows = cm.bubbles.map(m => ['m' + m.id, m, '']);
    Object.values(cm.pending).filter(p => qsSameId(p.msg.to_id, uid)).forEach(p => rows.push(['p' + p.rid, p.msg, 'pending']));
    Object.values(cm.failed).filter(p => qsSameId(p.msg.to_id, uid)).forEach(p => rows.push(['f' + p.rid, p.msg, 'failed']));
    const nodes = new Map(Array.from(host.children).map(n => [n.dataset.dmKey, n]));
    const wanted = new Set();
    if (cm.thread.more) rows.unshift(['older', null, '']);
    let cursor = host.firstElementChild;
    for (const [key, m, state] of rows) {
        wanted.add(key);
        const signature = m ? JSON.stringify([m.id, m.body, m.kind, m.recalled_at, m.duration, String(m.media_url || '').split('?')[0], cm.myTheme, m.asr_text, !!m.asr_pending, !!m.asr_failed, !!m.asr_empty, m.quote ? m.quote.id : 0, state, !!m.read_at, m.request_id || '']) : 'older';
        let node = nodes.get(key);
        if (!node || node.dataset.signature !== signature) {
            const next = document.createElement('div'); next.dataset.dmKey = key; next.dataset.signature = signature; next.className = 'dm-message';
            next.innerHTML = m ? cmBubbleHTML(m, me, state) : '<button type="button" class="td-btn td-btn-quiet" onclick="loadOlderMessages()">看更早的消息</button>';
            if (node) { dmReleasePlayback(node); if (cursor === node) cursor = next; node.replaceWith(next); }
            node = next;
        }
        if (node !== cursor) host.insertBefore(node, cursor);
        cursor = node.nextElementSibling;
    }
    for (const child of Array.from(host.children)) if (!wanted.has(child.dataset.dmKey)) { dmReleasePlayback(child); child.remove(); }
    if (stick || nearBottom) host.scrollTop = host.scrollHeight;
    else if (host.firstElementChild?.dataset.dmKey === 'older') host.scrollTop += host.scrollHeight - previousHeight;
    dmUi.stickBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 120;
}

function cmBubbleHTML(m, me, st) {
    const pending = st === true || st === "pending";
    const failed = st === "failed";
    const hasMeId = me !== undefined && me !== null && Number.isFinite(Number(me)) && Number(me) > 0;
    const partnerId = cm.thread && cm.thread.partner && cm.thread.partner.id;
    const mine = qsSameId(m.from_id, me) || (!hasMeId && qsSameId(m.to_id, partnerId));
    if (m.recalled_at) {
        return '<div class="dm-recall">' + (mine ? "你撤回了一条消息" : "对方撤回了一条消息") + "</div>";
    }
    const mid = Number(m.id || 0);
    const who = mine ? (state.user || {}) : ((cm.thread && cm.thread.partner) || {});
    const avatar = '<span class="cm-avatar dm-avatar">' + cmAvatarInner(who) + "</span>";
    const kind = m.kind || "text";
    const isMedia = ["image", "video", "audio"].includes(kind);
    // 投递状态常驻在气泡上：发送中 / 已发送 / 已读 / 没发出去，一眼看得出这一条到哪一步了。
    const status = pending ? (isMedia && !m.media_url ? "上传中" : "发送中")
        : failed ? "没发出去" : mine ? (m.read_at ? "已读" : "已发送") : "";
    const statusCls = failed ? "dm-status-fail" : pending ? "dm-status-wait" : "dm-status-ok";
    const bubble = '<div class="cm-bubble ' + (mine ? "me" : "them")
        + (kind === "sticker" ? " sticker" : "") + (isMedia ? " media" : "")
        + (pending ? " pending" : "") + (failed ? " failed" : "") + '"'
        + (mine && cm.myTheme && cm.myTheme !== "green" ? ' data-t="' + escapeHtml(cm.myTheme) + '"' : "")
        + ' data-mid="' + mid + '" data-mine="' + (mine ? 1 : 0) + '"'
        + ' oncontextmenu="return qsBubbleMenu(event,' + mid + ')"'
        + ' ontouchstart="qsBubbleHold(event,' + mid + ')" ontouchend="qsBubbleCancel()" ontouchmove="qsBubbleCancel()">'
        + (m.quote ? '<button type="button" class="dm-quote-inline" onclick="dmJumpQuote(' + Number(m.quote.id) + ')"><b>'
            + escapeHtml(m.quote.name || '') + '</b> ' + escapeHtml(m.quote.text || '') + '</button>' : '')
        + dmBubbleInner(m, kind, pending)
        + ((kind === "audio" && !pending && !m.recalled_at) ? dmAsrHTML(m) : "")
        + ((kind === "audio" && !pending && !m.recalled_at && !m.asr_text && !m.asr_pending && !m.asr_failed && !m.asr_empty)
            ? '<button type="button" class="dm-asr-btn" onclick="dmTranscribe(' + mid + ')">转文字</button>' : "")
        + "<time>" + escapeHtml(pending || failed ? "" : cmAgo(m.created_at)) + "</time>"
        + (status ? '<span class="dm-status ' + statusCls + '">' + status
            + (failed ? '<button type="button" class="dm-retry" onclick="dmRetrySend(\''
                + escapeHtml(m.request_id || "") + '\')">重试</button>' : "") + "</span>" : "")
        + "</div>";
    // 自己发的靠右、对方靠左，各带一个头像——小红书的私信就是这条规矩；
    // 只靠 align-self 时气泡和背景同色，看起来像"没有气泡"（截图里的样子）。
    return '<div class="dm-row ' + (mine ? "me" : "them") + '">'
        + (mine ? bubble + avatar : avatar + bubble) + "</div>";
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
    const mine = qsSameId(m.from_id, me);
    const menu = document.createElement("div");
    menu.id = "bubble-menu";
    menu.className = "bubble-menu";
    menu.dataset.dialogOwner = "page-layer";
    const canRecall = mine && !m.recalled_at && qsWithin(m.created_at, 300);
    const isAudio = (m.kind || 'text') === 'audio' && !m.recalled_at;
    menu.innerHTML = (isAudio ? '<button type="button" onclick="dmTranscribe(' + Number(mid) + ')">转文字</button>' : '')
        + (m.recalled_at ? '' : '<button type="button" onclick="dmStartQuote(' + Number(mid) + ')">引用</button>')
        + '<button type="button" onclick="qsCopyBubble(' + Number(mid) + ')">复制</button>'
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
async function dmTranscribe(mid) {
    qsHideMenu();
    let m = qsFindBubble(Number(mid));
    const scope = dmScope();
    if (!m || (m.kind || "text") !== "audio" || m.recalled_at) return;
    if (m.asr_text) { callNativeToast("这条语音已经转成文字了"); return; }
    if (m.asr_pending) return;
    m.asr_pending = true; m.asr_failed = false; m.asr_empty = false;
    if (dmIsVisible()) paintThread();
    try {
        const r = await postApi("/api/chat/asr", { message_id: Number(mid) });
        if (!dmScopeAlive(scope)) return;
        // Read receipts can replace message objects while the request is pending.
        m = qsFindBubble(Number(mid));
        if (!m || m.recalled_at) return;
        m.asr_text = String(r.text || "");
        m.asr_empty = !m.asr_text;
        if (!m.asr_text) callNativeToast("没听清，再说一遍试试");
    } catch (e) {
        if (!dmScopeAlive(scope)) return;
        m = qsFindBubble(Number(mid));
        if (!m || m.recalled_at) return;
        m.asr_failed = true;
        const message = String((e && e.message) || "");
        callNativeToast(/503|暂不可用/.test(message) ? "语音转文字暂不可用" : "转文字失败，长按重试");
    } finally {
        if (m) m.asr_pending = false;
        if (dmScopeAlive(scope) && dmIsVisible()) paintThread();
    }
}
function dmAsrHTML(m) {
    if (m.asr_pending) return '<p class="dm-asr pending" role="status">正在转文字…</p>';
    if (m.asr_text) return '<p class="dm-asr">' + escapeHtml(m.asr_text) + '</p>';
    if (m.asr_failed) return '<p class="dm-asr failed">转文字失败，长按重试</p>';
    if (m.asr_empty) return '<p class="dm-asr">（没有听清内容）</p>';
    return "";
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
    dmUi.stickBottom = false;
    const uid = cm.thread.partner.id, scope = dmScope();
    try {
        const r = await getJson("/api/chat/messages?with_user=" + uid + "&limit=30&cursor=" + cm.thread.cursor);
        if (!dmScopeAlive(scope)) return;
        cm.bubbles = (r.items || []).concat(cm.bubbles);
        cm.thread.more = !!r.more;
        cm.thread.cursor = r.next_cursor || 0;
        paintThread();
    } catch (e) { callNativeToast("更早的消息没读到"); }
}

/* 一条私信的真正出口：首发与单条重试共用同一段，request_id 从第一条就带上，
   重试走的是同一个键，服务端 UNIQUE(from_id,request_id) 保证不会存出第二条。 */
async function dmSendNow(rid, s, data, restore) {
    try {
        const r = await rawPostApi('/api/chat/send', { to: s.threadId, kind: data.kind || 'text',
            text: data.body || '', media_name: data.media_name || '', request_id: rid,
            quote_id: data.quote ? data.quote.id : 0 });
        dmAck(rid, r.message, s);
        if (dmScopeAlive(s) && dmUi.textRetry && dmUi.textRetry.rid === rid) dmUi.textRetry = null;
        return true;
    } catch (e) {
        if (!dmAccountAlive(s)) return false;
        dmFail(rid, (e && e.message) || '网络不通');
        if (dmScopeAlive(s)) {
            if (restore) { const i = cmEl('dm-input'); if (i && !i.value) i.value = data.body; }
            paintThread();
            callNativeToast('这条没发出去，点气泡上的重试：' + ((e && e.message) || '网络不通'));
        }
        return false;
    }
}

async function dmRetrySend(rid) {
    const f = cm.failed[rid];
    if (!f) return;
    delete cm.failed[rid];
    if (!dmAccountAlive(f.scope)) { if (dmIsVisible()) paintThread(); return; }
    cm.pending[rid] = f;
    if (dmScopeAlive(f.scope)) paintThread();
    await dmSendNow(rid, f.scope, f.msg, false);
}

async function sendDM() {
    if (dmUi.draft) { await dmSendDraft(); return; }
    if (dmUi.record) { await dmSendAudio(); return; }
    const input = cmEl('dm-input'), text = (input?.value || '').trim();
    if (!text || !cm.thread || dmUi.composing) return;
    if (!state.token) { openAuthModal(); return; }
    const s = dmScope(), rid = dmUi.textRetry?.text === text ? dmUi.textRetry.rid : dmRequestId();
    dmUi.textRetry = { text, rid };
    const quote = dmUi.quote;
    dmPending(rid, s, { body: text, kind: 'text', quote: quote ? { id: quote.id, name: quote.name, text: quote.text } : null }); input.value = ''; dmUi.caret = [0, 0]; paintThread();
    if (await dmSendNow(rid, s, cm.pending[rid] ? cm.pending[rid].msg : { body: text }, true)
        && quote && dmUi.quote && dmUi.quote.id === quote.id) dmClearQuote();
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

function dmAck(rid, message, scope) {
    const pending = cm.pending[rid];
    if (scope && !dmAccountAlive(scope)) return;
    if (pending?.scope && !dmAccountAlive(pending.scope)) return;
    delete cm.pending[rid];
    // 回执也可能晚于"失败"到达（先超时、后 ack）：ack 一到失败标记必须撤，
    // 否则界面上同一句话会同时挂着"没发出去"和已发送两条。
    delete cm.failed[rid];
    if (message) {
        if (cm.thread && (qsSameId(message.from_id, cm.thread.partner.id) || qsSameId(message.to_id, cm.thread.partner.id))) {
            if (!cm.bubbles.some(b => qsSameId(b.id, message.id))) cm.bubbles.push(message);
        }
        const preview = ({ image: '［图片］', video: '［视频］', audio: '［语音］', sticker: '［表情］' })[message.kind] || message.body;
        bumpConversation(qsSameId(message.from_id, state.user?.id) ? message.to_id : message.from_id, preview, qsSameId(message.from_id, state.user?.id) ? 'me' : 'them');
    }
    if (dmIsVisible()) paintThread();
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
    const scope = dmScope();
    try {
        const t = await postApi("/api/chat/ticket", {});
        if (!dmAccountAlive(scope)) return;
        const base = String(API_BASE || "").replace(/^http/, "ws");
        const sock = new WebSocket(base + t.ws_path + "?ticket=" + encodeURIComponent(t.ticket));
        cm.ws = sock;
        sock.onopen = () => {
            // 断连期间对方发的消息只落在服务端历史里：光把连接接上不算恢复，
            // 必须回头补拉一次，否则用户看到的就是"少了几天消息"。
            const back = cm.wsBlind || cm.wsRetry > 0;
            cm.wsRetry = 0; cm.wsBlind = false;
            setWsState("connected");
            if (back) dmCatchUp();
        };
        sock.onmessage = ev => { if (dmAccountAlive(scope) && cm.ws === sock) handleWsEvent(ev); };
        sock.onerror = () => setWsState("error");
        sock.onclose = () => {
            if (!dmAccountAlive(scope) || cm.ws !== sock) return;
            cm.ws = null;
            if (["incoming", "outgoing", "connecting", "active"].includes(dmCall.state)) dmCallFinish("实时连接断了，通话结束", "network");
            cm.wsRetry++;
            cm.wsBlind = true;
            setWsState("closed");
            clearTimeout(cm.wsTimer);
            cm.wsTimer = setTimeout(connectChat, Math.min(30000, 2000 * cm.wsRetry));
        };
    } catch (e) {
        cm.wsRetry++;
        setWsState("unavailable", (e && e.message) || "握手失败");
    }
}

/** 重连后的补拉：会话列表与当前线程都回读一次，把断连期间到达的补回来。
    服务端历史是唯一事实源，本地只做展示，所以重复拉取不会造出第二条。

     服务端历史是唯一事实源，本地只做展示，所以重复拉取不会造出第二条。 */
function dmCatchUp() {
    loadMessages();
    if (cm.thread && dmIsVisible()) refreshThread();
}

function wsSend(obj) {
    if (!wsOpen()) return false;
    try { cm.ws.send(JSON.stringify(obj)); return true; } catch (e) { return false; }
}

/* ── 语音通话（WebRTC + 现有聊天 WebSocket 信令）────────────── */
function dmCallSupported() {
    return typeof RTCPeerConnection === "function" && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}
function dmCallName(peer) {
    return String((peer && (peer.name || peer.nickname || peer.username)) || "对方").slice(0, 40);
}
function dmCallLayer() {
    let layer = cmEl("dm-call-layer");
    if (!layer) {
        layer = document.createElement("section");
        layer.id = "dm-call-layer";
        layer.className = "dm-call-layer";
        layer.setAttribute("role", "dialog");
        layer.setAttribute("aria-modal", "true");
        document.body.appendChild(layer);
    }
    return layer;
}
function dmCallPaintControls() {
    const mute = cmEl("dm-call-mute");
    if (mute) { mute.classList.toggle("active", dmCall.muted); mute.setAttribute("aria-pressed", String(dmCall.muted)); }
    const speaker = cmEl("dm-call-speaker");
    if (speaker) { speaker.classList.toggle("active", dmCall.speaker); speaker.setAttribute("aria-pressed", String(dmCall.speaker)); }
}
function dmCallTimeText() {
    if (!dmCall.startedAt) return "0:00";
    const seconds = Math.max(0, Math.floor((Date.now() - dmCall.startedAt) / 1000));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
}
function dmCallTick() {
    const text = dmCallTimeText();
    cmText("dm-call-timer", text);
    cmText("dm-call-mini-time", text);
}
function dmCallMiniRender() {
    let mini = cmEl("dm-call-mini");
    if (!mini) {
        mini = document.createElement("div");
        mini.id = "dm-call-mini";
        mini.className = "dm-call-mini";
        document.body.appendChild(mini);
    }
    mini.hidden = false;
    mini.innerHTML = '<button type="button" class="dm-call-mini-main" id="dm-call-mini-main" onclick="dmCallRestore()">'
        + '<span class="dm-call-mini-dot" aria-hidden="true"></span><b>' + escapeHtml(dmCallName(dmCall.peer)) + '</b>'
        + '<span id="dm-call-mini-time">' + dmCallTimeText() + '</span></button>'
        + '<button type="button" class="dm-call-mini-hang" onclick="dmEndCall()">挂断</button>';
}
function dmCallMiniHide() {
    const mini = cmEl("dm-call-mini");
    if (mini) { mini.hidden = true; mini.innerHTML = ""; }
}
function dmCallMinimize() {
    if (!["connecting", "active"].includes(dmCall.state)) return;
    dmCall.minimized = true;
    dmCallRender();
}
function dmCallRestore() {
    dmCall.minimized = false;
    dmCallRender();
    if (dmCall.state === "active") { dmCallPaintControls(); dmCallTick(); }
}
function dmCallPeerTop(name, kicker, sub) {
    return '<div class="dm-call-top"><div class="dm-call-avatar"><span class="cm-avatar">' + cmAvatarInner(dmCall.peer || {}) + '</span></div>'
        + '<h2>' + name + '</h2><p class="dm-call-kicker">' + kicker + '</p>'
        + (sub ? '<p class="dm-call-sub">' + sub + '</p>' : '') + '</div>';
}
/* 通话失败必须说清是哪一种。「通话失败」四个字等于没说：
   对方拒绝、没人接听、没给麦克风权限、网络或中继不可用，用户要做的事完全不同。 */
const DM_CALL_WHY = {
    rejected: "对方拒绝了这个通话", timeout: "响铃太久，对方没有接听",
    no_mic: "没拿到麦克风权限，通话没起来", network: "网络不通或中继服务器（TURN）不可用",
    busy: "对方正忙，已经在另一通电话里", offline: "对方不在线，通话要两边都在应用里",
    cancelled: "已取消呼叫", ended: "通话已结束", failed: "呼叫失败"
};
function dmCallErrKind(error) {
    const text = String((error && error.name) || "") + " " + String((error && error.message) || "");
    return /NotAllowed|Permission|denied|麦克风/i.test(text) ? "no_mic" : "network";
}
function dmCallRound(id, cls, label, icon, action, active) {
    return '<button type="button"' + (id ? ' id="' + id + '"' : '') + ' class="dm-call-round ' + cls + (active ? ' active' : '') + '"'
        + (id ? ' aria-pressed="' + (active ? 'true' : 'false') + '"' : '') + ' onclick="' + action + '">' + icon + '<span>' + label + '</span></button>';
}
function dmCallRender() {
    const layer = dmCallLayer();
    if (dmCall.state === "idle") {
        layer.hidden = true;
        layer.innerHTML = "";
        dmCallMiniHide();
        return;
    }
    if (dmCall.minimized && ["connecting", "active"].includes(dmCall.state)) {
        layer.hidden = true;
        layer.innerHTML = "";
        dmCallMiniRender();
        return;
    }
    dmCallMiniHide();
    layer.hidden = false;
    const peer = dmCall.peer || {};
    const name = escapeHtml(dmCallName(peer));
    const hangIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15c4-3 8-3 12 0l1.5 1.5-2.5 3-2.5-1.5c-1.7.5-3.3.5-5 0L7 19.5l-2.5-3z"/></svg>';
    const acceptIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l4 4 10-10"/></svg>';
    const muteIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/></svg>';
    const speakerIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h3l4 4V5L7 9zM15 9a4 4 0 0 1 0 6M17.5 6.5a7 7 0 0 1 0 11"/></svg>';
    let body = "";
    if (dmCall.state === "incoming") {
        body = dmCallPeerTop(name, "语音通话邀请", "响铃中，接听即可通话")
            + '<div class="dm-call-page-actions">'
            + dmCallRound("", "reject dm-call-btn-reject", "拒绝", hangIcon, "dmRejectCall()")
            + dmCallRound("", "accept dm-call-btn-accept", "接听", acceptIcon, "dmAcceptCall()")
            + '</div>';
    } else if (dmCall.state === "outgoing") {
        body = dmCallPeerTop(name, "正在呼叫", "等待对方接听…")
            + '<div class="dm-call-page-actions">'
            + dmCallRound("", "hang dm-call-btn-hang", "取消", hangIcon, "dmCancelCall()") + '</div>';
    } else if (dmCall.state === "connecting") {
        body = '<button type="button" class="dm-call-down" aria-label="最小化" onclick="dmCallMinimize()">⌄</button>'
            + dmCallPeerTop(name, "已接听，正在接通", "还在建立语音通道，稍等一下")
            + '<div class="dm-call-page-actions">'
            + dmCallRound("", "hang dm-call-btn-hang", "挂断", hangIcon, "dmEndCall()") + '</div>';
    } else if (dmCall.state === "active") {
        const canSpeaker = !!(window.AndroidBridge && typeof window.AndroidBridge.setVoiceCallSpeaker === "function");
        body = '<button type="button" class="dm-call-down" aria-label="最小化" onclick="dmCallMinimize()">⌄</button>'
            + dmCallPeerTop(name, "已接通", "通话中")
            + '<p class="dm-call-timer" id="dm-call-timer">' + dmCallTimeText() + '</p>'
            + '<div class="dm-call-page-actions">'
            + dmCallRound("dm-call-mute", "", "静音", muteIcon, "dmToggleMute()", dmCall.muted)
            + (canSpeaker ? dmCallRound("dm-call-speaker", "", "免提", speakerIcon, "dmToggleSpeaker()", dmCall.speaker) : '')
            + dmCallRound("", "hang dm-call-btn-hang", "挂断", hangIcon, "dmEndCall()")
            + '</div>';
    } else if (dmCall.state === "ended") {
        // 失败的那几种要留在屏幕上让人读完，还给一条出路：关页面 / 重拨。
        const bad = dmCall.failKind && dmCall.failKind !== "ended";
        body = dmCallPeerTop(name, bad ? "通话没成" : "语音通话", escapeHtml(dmCall.reason || "通话结束"))
            + (bad ? '<div class="dm-call-page-actions">'
                + (dmCall.role === "caller" ? dmCallRound("", "accept dm-call-btn-accept", "重拨", acceptIcon, "dmCallRetry()") : '')
                + dmCallRound("", "hang dm-call-btn-hang", "关闭", hangIcon, "dmCallReset()") + '</div>' : '');
    }
    layer.innerHTML = '<div class="dm-call-card dm-call-page">' + body + '</div>';
    if (dmCall.state === "active") { dmCallPaintControls(); dmCallTick(); }
}
function dmCallRingStop() {
    clearInterval(dmCall.ring);
    dmCall.ring = 0;
}
function dmCallRingStart() {
    dmCallRingStop();
    const beep = () => {
        try {
            if (window.AndroidBridge && window.AndroidBridge.playBeep) window.AndroidBridge.playBeep();
            if (window.AndroidBridge && window.AndroidBridge.vibrate) window.AndroidBridge.vibrate(400);
        } catch (e) { /* 浏览器里没有原生桥，静默 */ }
    };
    beep();
    dmCall.ring = setInterval(beep, 1900);
}
function dmCallAudioStart() {
    try {
        if (window.AndroidBridge && window.AndroidBridge.startVoiceCallAudio) {
            window.AndroidBridge.startVoiceCallAudio(!!dmCall.speaker);
        }
    } catch (e) { /* 路由失败不阻断媒体 */ }
}
function dmCallAudioStop() {
    try {
        if (window.AndroidBridge && window.AndroidBridge.stopVoiceCallAudio) window.AndroidBridge.stopVoiceCallAudio();
    } catch (e) {}
}
function dmCallAttachRemote(stream) {
    let audio = dmCall.audio;
    if (!audio) {
        audio = document.createElement("audio");
        audio.id = "dm-call-audio";
        audio.autoplay = true;
        audio.setAttribute("playsinline", "");
        audio.style.display = "none";
        document.body.appendChild(audio);
        dmCall.audio = audio;
    }
    audio.srcObject = stream;
    const played = audio.play();
    if (played && played.catch) played.catch(() => callNativeToast("点一下屏幕让通话声音播放"));
}
function dmCallCleanupMedia() {
    clearInterval(dmCall.timer); dmCall.timer = 0;
    clearTimeout(dmCall.timeout); dmCall.timeout = 0;
    clearTimeout(dmCall.endTimer); dmCall.endTimer = 0;
    dmCallRingStop();
    const pc = dmCall.pc;
    dmCall.pc = null;
    if (pc) {
        pc.onicecandidate = null;
        pc.ontrack = null;
        pc.onconnectionstatechange = null;
        try { pc.close(); } catch (e) {}
    }
    if (dmCall.stream) {
        dmCall.stream.getTracks().forEach(track => { try { track.stop(); } catch (e) {} });
        dmCall.stream = null;
    }
    if (dmCall.audio) {
        try { dmCall.audio.srcObject = null; dmCall.audio.remove(); } catch (e) {}
        dmCall.audio = null;
    }
    dmCallAudioStop();
}
function dmCallReset() {
    dmCallCleanupMedia();
    dmCall.state = "idle"; dmCall.id = ""; dmCall.peer = null; dmCall.role = "";
    dmCall.offer = null; dmCall.pendingIce = []; dmCall.localIce = [];
    dmCall.startedAt = 0; dmCall.muted = false; dmCall.speaker = false; dmCall.reason = "";
    dmCall.failKind = "";
    dmCall.minimized = false; dmCallMiniHide();
    dmCallRender();
}
function dmCallFinish(reason, kind) {
    if (dmCall.state === "idle" || dmCall.state === "ended") return;
    const wasActive = ["outgoing", "connecting", "active"].includes(dmCall.state);
    dmCallCleanupMedia();
    dmCall.minimized = false;
    dmCallMiniHide();
    dmCall.state = "ended";
    dmCall.failKind = kind || (wasActive ? "ended" : "failed");
    dmCall.reason = reason || DM_CALL_WHY[dmCall.failKind] || "通话结束";
    dmCall.startedAt = 0;
    dmCallRender();
    // 正常挂断 1.8 秒收起就够了；失败原因得留够时间让人读完，
    // 一闪就没等于没告诉用户到底是哪一种失败。
    const hold = dmCall.failKind === "ended" ? 1800 : 8000;
    dmCall.endTimer = setTimeout(() => { if (dmCall.state === "ended") dmCallReset(); }, hold);
}
/* 失败面板上的「重拨」：先把上一通彻底收干净再发起，
   不然状态还挂在 ended/outgoing 上，dmStartCall 只会回一句"现在已经在通话里了"。 */
function dmCallRetry() {
    dmCallReset();
    dmStartCall();
}
function dmCallFlushLocalIce() {
    if (!dmCall.id) return;
    const queued = dmCall.localIce.splice(0);
    queued.forEach(candidate => wsSend({ t: "call_ice", call_id: dmCall.id, candidate }));
}
function dmCallFlushRemoteIce() {
    if (!dmCall.pc || !dmCall.pc.remoteDescription) return;
    const queued = dmCall.pendingIce.splice(0);
    queued.forEach(candidate => dmCall.pc.addIceCandidate(candidate).catch(() => {}));
}
function dmCallWirePeer(pc) {
    pc.onicecandidate = event => {
        if (!event.candidate) return;
        const candidate = event.candidate.toJSON ? event.candidate.toJSON() : {
            candidate: event.candidate.candidate, sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex
        };
        if (dmCall.id) wsSend({ t: "call_ice", call_id: dmCall.id, candidate });
        else dmCall.localIce.push(candidate);
    };
    pc.ontrack = event => {
        const stream = (event.streams && event.streams[0]) || new MediaStream([event.track]);
        dmCallAttachRemote(stream);
    };
    pc.onconnectionstatechange = () => {
        const state = pc.connectionState;
        if (state === "connected") dmCallSetActive();
        else if (state === "failed") dmCallFinish(DM_CALL_WHY.network, "network");
        else if (state === "closed" && dmCall.state === "active") dmCallFinish(DM_CALL_WHY.ended, "ended");
    };
}
function dmCallSetActive() {
    if (dmCall.state === "active") return;
    if (!["outgoing", "connecting", "incoming"].includes(dmCall.state)) return;
    clearTimeout(dmCall.timeout); dmCall.timeout = 0;
    dmCall.state = "active"; dmCall.startedAt = Date.now();
    dmCallAudioStart();
    clearInterval(dmCall.timer);
    dmCall.timer = setInterval(dmCallTick, 1000);
    dmCallRender();
}
async function dmCallMedia(pc) {
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }
    });
    dmCall.stream = stream;
    stream.getTracks().forEach(track => pc.addTrack(track, stream));
    return stream;
}
async function dmCallIceServers() {
    const result = await getJson("/api/rtc/ice");
    return Array.isArray(result.ice_servers) ? result.ice_servers : [];
}
function dmCallNewPeer(iceServers) {
    const pc = new RTCPeerConnection({
        iceServers,
        iceTransportPolicy: window.__QS_FORCE_RELAY__ ? "relay" : "all"
    });
    dmCall.pc = pc;
    dmCallWirePeer(pc);
    return pc;
}
async function dmStartCall() {
    // 上一通刚结束（含失败/取消）时状态还挂在 ended 上，这时点呼叫算重试，
    // 不许被当成"已经在通话里"挡回去——那正是机主说的忙线僵尸态。
    if (dmCall.state === "ended") dmCallReset();
    if (dmCall.state !== "idle") { callNativeToast("现在已经在通话里了"); return; }
    if (!cm.thread) return;
    const peer = cm.thread.partner;
    if (!peer || peer.blocked) { callNativeToast("现在不能给这个人打电话"); return; }
    if (!dmCallSupported()) { callNativeToast("当前客户端不支持语音通话，请升级系统 WebView"); return; }
    if (!wsOpen()) { callNativeToast("实时连接还没连上，正在重连"); connectChat(); return; }
    const allowed = await dmEnsureMicrophone();
    if (!allowed) { dmMicHelp(); return; }
    dmCancelRecording(); dmMicRelease(); dmClosePanels(); dmBlurKeyboard();
    dmCall.state = "outgoing"; dmCall.peer = { id: peer.id, name: cmName(peer) };
    dmCall.role = "caller"; dmCall.id = ""; dmCall.offer = null; dmCall.pendingIce = []; dmCall.localIce = [];
    dmCall.muted = false; dmCall.speaker = false; dmCall.reason = "";
    dmCall.minimized = false;
    dmCallRender();
    try {
        const iceServers = await dmCallIceServers();
        const pc = dmCallNewPeer(iceServers);
        await dmCallMedia(pc);
        const offer = await pc.createOffer({ offerToReceiveAudio: true });
        await pc.setLocalDescription(offer);
        if (!wsSend({ t: "call_invite", to: peer.id, sdp: { type: offer.type, sdp: offer.sdp } })) {
            throw new Error("实时连接没连上");
        }
        dmCall.timeout = setTimeout(() => {
            if (dmCall.state === "outgoing") {
                wsSend({ t: "call_cancel", call_id: dmCall.id || "" });
                dmCallFinish(DM_CALL_WHY.timeout, "timeout");
            }
        }, 45000);
    } catch (error) {
        const kind = dmCallErrKind(error);
        dmCallFinish(kind === "no_mic" ? DM_CALL_WHY.no_mic
            : DM_CALL_WHY.network + "：" + (error.message || "网络不通"), kind);
    }
}
async function dmAcceptCall() {
    if (dmCall.state !== "incoming" || !dmCall.offer) return;
    dmCallRingStop();
    dmCancelRecording(); dmMicRelease();
    const allowed = await dmEnsureMicrophone();
    if (!allowed) {
        wsSend({ t: "call_reject", call_id: dmCall.id || "", reason: DM_CALL_WHY.no_mic });
        dmCallFinish(DM_CALL_WHY.no_mic, "no_mic");
        dmMicHelp();
        return;
    }
    dmCall.state = "connecting";
    dmCallRender();
    try {
        const iceServers = await dmCallIceServers();
        const pc = dmCallNewPeer(iceServers);
        await dmCallMedia(pc);
        await pc.setRemoteDescription(dmCall.offer);
        dmCallFlushRemoteIce();
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        if (!wsSend({ t: "call_accept", call_id: dmCall.id, sdp: { type: answer.type, sdp: answer.sdp } })) {
            throw new Error("实时连接没连上");
        }
    } catch (error) {
        const kind = dmCallErrKind(error);
        wsSend({ t: "call_reject", call_id: dmCall.id || "", reason: DM_CALL_WHY[kind] });
        dmCallFinish(kind === "no_mic" ? DM_CALL_WHY.no_mic
            : DM_CALL_WHY.network + "：" + (error.message || "网络不通"), kind);
    }
}
function dmRejectCall() {
    wsSend({ t: "call_reject", call_id: dmCall.id || "", reason: "已拒绝" });
    dmCallFinish("已拒绝这个通话", "rejected");
}
function dmCancelCall() {
    // 没拿到 call_id 之前取消也必须通知服务端，否则那通呼叫一直挂在忙线表里，
    // 下一次拨号只会收到"对方正忙"。
    wsSend({ t: "call_cancel", call_id: dmCall.id || "" });
    dmCallFinish(DM_CALL_WHY.cancelled, "cancelled");
}
function dmEndCall() {
    wsSend({ t: "call_end", call_id: dmCall.id || "" });
    dmCallFinish(DM_CALL_WHY.ended, "ended");
}
function dmToggleMute() {
    if (!dmCall.stream) return;
    dmCall.muted = !dmCall.muted;
    dmCall.stream.getAudioTracks().forEach(track => { track.enabled = !dmCall.muted; });
    dmCallPaintControls();
}
function dmToggleSpeaker() {
    dmCall.speaker = !dmCall.speaker;
    try {
        if (window.AndroidBridge && window.AndroidBridge.setVoiceCallSpeaker) {
            window.AndroidBridge.setVoiceCallSpeaker(dmCall.speaker);
        }
    } catch (e) {}
    dmCallPaintControls();
}
function dmHandleCallEvent(data) {
    const kind = data && data.t;
    if (!kind) return;
    if (kind === "call_invite") {
        if (dmCall.state !== "idle") {
            wsSend({ t: "call_reject", call_id: data.call_id });
            return;
        }
        if (!dmCallSupported()) {
            wsSend({ t: "call_reject", call_id: data.call_id });
            callNativeToast("当前客户端不支持语音通话");
            return;
        }
        dmCall.state = "incoming"; dmCall.id = data.call_id; dmCall.peer = data.from || null;
        dmCall.role = "callee"; dmCall.offer = data.sdp; dmCall.pendingIce = []; dmCall.localIce = [];
        dmCall.muted = false; dmCall.speaker = false; dmCall.reason = "";
        dmCall.minimized = false;
        dmCallRender(); dmCallRingStart();
        return;
    }
    if (kind === "call_ringing") {
        if (dmCall.state !== "outgoing") return;
        dmCall.id = data.call_id;
        if (data.peer) dmCall.peer = data.peer;
        dmCallRender(); dmCallFlushLocalIce();
        return;
    }
    if (kind === "call_accept") {
        if (!dmCall.pc || !data.sdp) return;
        dmCall.pc.setRemoteDescription(data.sdp).then(() => {
            dmCallFlushRemoteIce();
            if (dmCall.state === "outgoing") { dmCall.state = "connecting"; dmCallRender(); }
        }).catch(() => dmCallFinish(DM_CALL_WHY.network, "network"));
        return;
    }
    if (kind === "call_active") {
        if (dmCall.state === "connecting" || dmCall.state === "incoming") dmCallRender();
        return;
    }
    if (kind === "call_ice") {
        if (!data.candidate) return;
        if (dmCall.pc && dmCall.pc.remoteDescription) dmCall.pc.addIceCandidate(data.candidate).catch(() => {});
        else dmCall.pendingIce.push(data.candidate);
        return;
    }
    if (kind === "call_reject") { dmCallFinish(data.reason || DM_CALL_WHY.rejected, "rejected"); return; }
    if (kind === "call_cancel") { dmCallFinish(data.reason || "对方取消了呼叫", "cancelled"); return; }
    if (kind === "call_timeout") { dmCallFinish(DM_CALL_WHY.timeout, "timeout"); return; }
    if (kind === "call_end") { dmCallFinish(data.reason || "对方已挂断", "ended"); return; }
    if (kind === "call_busy") { dmCallFinish(data.detail || DM_CALL_WHY.busy, "busy"); return; }
    if (kind === "call_unavailable") { dmCallFinish(data.detail || DM_CALL_WHY.offline, "offline"); return; }
    if (kind === "call_error") { dmCallFinish(data.detail || DM_CALL_WHY.failed, "failed"); }
}
function handleWsEvent(ev) {
    let data = null;
    try { data = JSON.parse(ev.data); } catch (e) { return; }
    if (!data) return;
    const me = state.user && state.user.id;
    if (data.t === "msg" && data.message) {
        const m = data.message;
        if (cm.thread && (m.from_id === cm.thread.partner.id || m.to_id === cm.thread.partner.id)) {
            if (!cm.bubbles.some(b => qsSameId(b.id, m.id))) cm.bubbles.push(m);
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
    } else if (typeof data.t === "string" && data.t.startsWith("call_")) {
        dmHandleCallEvent(data);
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
        // 大字只放昵称。登录名是账号本身，过去 nickname||username 一起兜底，
        // 没设过昵称的人主页上显示的就是自己的登录名，看着像"昵称改不动"。
        const nick = String(u.nickname || "").trim();
        cmText("me-name", nick || "还没设置昵称");
        const loginLine = cmEl("me-login");
        if (loginLine) loginLine.innerHTML = '登录名 <b class="me-login-name">'
            + escapeHtml(u.username || "—") + '</b>'
            + (nick ? "" : '<button type="button" class="me-copy" onclick="openAccountCenter()">去设置昵称</button>');
        cmText("me-public-id", s.public_id || u.public_id || "—");
        const bio = acc && acc.profile && acc.profile.bio;
        cmText("me-bio", (acc && acc.bio) || bio || "还没有签名，点下面的「编辑签名」写一句");
        const region = s.region || (acc && acc.region) || "";
        cmText("me-region", region ? "属地 " + region : "属地未知（登录时按 IP 认，换网络后会自动跟上）");
        const disc = acc && typeof acc.discoverable !== "undefined" ? acc.discoverable : 1;
        const badge = cmEl("me-discoverable-badge");
        if (badge) { badge.textContent = disc ? "已开启" : "已关闭"; badge.dataset.tone = disc ? "on" : "off"; }
        cmText("me-discoverable-hint", disc ? "别人可以用轻塑号或昵称搜到你" : "别人搜不到你，但你仍能看和发");
        const slot = cmEl("me-avatar");
        if (slot) {
            const url = acc && acc.avatar_url;
            slot.innerHTML = url ? '<img src="' + escapeHtml(API_BASE + url) + '" alt="我的头像">'
                : cmAvatarInner({ name: u.nickname || u.username });
        }
        paintMeAvatars(acc && acc.avatar_url);
        cm.myTheme = s.bubble_theme || "green";
        const meId = (state.user && state.user.id) || 0;
        const stats = [["posts", "帖子", s.posts], ["followers", "粉丝", s.followers],
                       ["following", "关注", s.following], ["likes", "获赞", s.likes_received]];
        const host = cmEl("me-stats");
        if (host) host.innerHTML = qsStatsHTML(stats, meId);
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

function paintMeAvatars(avatarUrl) {
    const u = state.user || {};
    // 不传就用个人中心那次回读的结果。以前这里只取名字不取头像，
    // 于是"我的"页一重画就把底部导航的真头像抹回字母章。
    const url = typeof avatarUrl === "string" ? avatarUrl : ((accountCache && accountCache.avatar_url) || "");
    const inner = cmAvatarInner({ name: u.nickname || u.username, avatar: url });
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


function openRecoveryPasswordDialog(){
    toolDialog('设置新密码', `<p class="td-lead">临时口令只能登录一次，请在30分钟内设置新密码。</p><label class="td-field-row"><span class="td-field-label">新密码（至少8位）</span><input id="recovery-password" type="password" autocomplete="new-password"></label><label class="td-field-row"><span class="td-field-label">再次输入</span><input id="recovery-password-again" type="password" autocomplete="new-password"></label><button type="button" class="td-btn" onclick="finishRecoveryPassword()">保存新密码</button><button type="button" class="td-btn-quiet" onclick="logoutUser()">退出并重新登录</button><p id="recovery-error" role="status"></p>`);
}
async function finishRecoveryPassword(){
    const password=document.getElementById('recovery-password').value;
    const error=document.getElementById('recovery-error');
    if(password!==document.getElementById('recovery-password-again').value){error.textContent='两次密码不一致';return;}
    try{
        await postApi('/api/account/recovery-password',{new_password:password});
        state.user.password_change_required=false;
        localStorage.setItem(USER_KEY,JSON.stringify(state.user));
        document.getElementById('account-tools-dialog').close();
        await Promise.all([syncRemoteDashboard(),syncRemoteCharts()]);
        callNativeToast('新密码已设置');
    }catch(e){error.textContent=e.message;}
}
