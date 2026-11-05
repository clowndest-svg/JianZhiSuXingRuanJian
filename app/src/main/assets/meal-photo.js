/* Photo meal review: no image persistence, no write before explicit confirmation. */
(()=>{
'use strict';
const esc=x=>escapeHtml(String(x??'')),copy=x=>JSON.parse(JSON.stringify(x));
const uuid=()=>crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
let draft=null,sequence=0,objectUrl='',watch,references=[];
const number=(v)=>v===''?null:Number(v);
const fields=[['grams','可食部重量 g'],['kcal100','热量 kcal / 100g'],['protein100','蛋白质 g / 100g'],['carbs100','碳水 g / 100g'],['fat100','脂肪 g / 100g']];
const empty=()=>({name:'',grams:100,kcal100:0,protein100:null,carbs100:null,fat100:null,gi:null,available_carbs100:null,gi_source:''});
const live=(d,s)=>draft===d&&s===sequence&&d.generation===sessionGeneration&&document.getElementById('meal-photo-editor')?.isConnected;
function release(){sequence++;draft=null;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl='';clearInterval(watch);}
function note(text,error=false){const el=document.getElementById('mp-status');if(el){el.textContent=text;el.dataset.err=error?'1':'0';}}
function collect(){
 if(!draft)return;
 draft.food_name=document.getElementById('mp-name').value;
 draft.slot=document.getElementById('mp-slot').value;
 document.querySelectorAll('[data-mp-row]').forEach(row=>{const c=draft.components[Number(row.dataset.mpRow)];row.querySelectorAll('[data-field]').forEach(input=>{c[input.dataset.field]=input.dataset.field==='name'||input.dataset.field==='gi_source'?input.value:number(input.value);});});
}
function totals(){
 const rows=draft.components,known=rows.length&&rows.every(x=>['protein100','carbs100','fat100'].every(k=>x[k]!==null&&Number.isFinite(x[k])));
 const total=k=>rows.reduce((s,c)=>s+(Number(c.grams)||0)*(Number(c[k])||0)/100,0);
 return {cal:Math.round(total('kcal100')),grams:rows.reduce((s,c)=>s+(Number(c.grams)||0),0),protein_g:known?total('protein100'):null,carbs_g:known?total('carbs100'):null,fat_g:known?total('fat100'):null,
 gl:rows.length&&rows.every(x=>x.gi!==null&&x.available_carbs100!==null&&x.gi_source.trim())?rows.reduce((s,c)=>s+c.grams*c.available_carbs100*c.gi/10000,0):null};
}
function summary(){
 const t=totals(),known=t.protein_g!==null,p=known?t.protein_g*4:0,c=known?t.carbs_g*4:0,f=known?t.fat_g*9:0,sum=p+c+f;
 const ring=document.getElementById('mp-ring');if(!ring)return;
 ring.style.background=sum?`conic-gradient(#368768 0 ${p/sum*100}%,#e8b44a ${p/sum*100}% ${(p+c)/sum*100}%,#e89579 ${(p+c)/sum*100}% 100%)`:'#e5ece8';
 document.getElementById('mp-cal').textContent=draft.components.length?t.cal:'—';
 for(const k of ['protein_g','carbs_g','fat_g'])document.getElementById('mp-'+k).textContent=t[k]===null?'未知':t[k].toFixed(1)+' g';
 document.getElementById('mp-weight').textContent=t.grams.toFixed(1)+' g';
 document.getElementById('mp-gl').textContent=t.gl===null?'未知 · 未填写完整GI资料':t.gl.toFixed(1)+'（按填写资料计算）';
}
function rowHtml(c,i){
 return `<fieldset class="mp-component" data-mp-row="${i}"><legend>食材 ${i+1}</legend><div class="mp-row-head"><label>食材名称<input data-field="name" value="${esc(c.name)}" maxlength="60" required></label><button type="button" data-remove="${i}" aria-label="删除食材${i+1}">删除</button></div><p class="mp-help">营养参考：${esc(c.reference||'本人填写或模型估算，未核验成分来源')}</p><label>改选参考食材（保留当前克重）<select data-reference="${i}"><option value="">请选择，或直接手填下方数据</option>${references.map((x,j)=>`<option value="${j}">${esc(x.name)}</option>`).join('')}</select></label><div class="mp-fields">${fields.map(([k,label])=>`<label>${label}<input data-field="${k}" type="number" min="${k==='grams'?'.1':'0'}" max="${k==='grams'?5000:k==='kcal100'?900:100}" step="any" inputmode="decimal" value="${esc(c[k])}" ${['grams','kcal100'].includes(k)?'required':''} placeholder="${k==='grams'?'请称重':'未知可留空'}"></label>`).join('')}</div><details><summary>血糖负荷资料（选填）</summary><p class="mp-help">只有核实过的GI和可利用碳水才能计算；照片不能测出血糖反应。</p><div class="mp-fields"><label>GI（0–100）<input data-field="gi" type="number" min="0" max="100" step="any" value="${esc(c.gi)}"></label><label>可利用碳水 g / 100g<input data-field="available_carbs100" type="number" min="0" max="100" step="any" value="${esc(c.available_carbs100)}"></label><label class="mp-wide">GI来源<input data-field="gi_source" maxlength="160" value="${esc(c.gi_source)}" placeholder="食品GI数据库或测定资料"></label></div></details></fieldset>`;
}
function render(){
 const root=document.getElementById('meal-photo-editor');if(!root||!draft)return;
 root.innerHTML=`<p class="mp-kicker">PHOTO MEAL · 照片识餐</p><p class="mp-help">照片看不准克重、烹调油和隐藏食材。请核对实际吃下的可食部，以下均为营养估算。</p>
 <div class="mp-preview">${objectUrl?`<img src="${esc(objectUrl)}" alt="本机所选餐食照片">`:'<span aria-hidden="true">🍽</span><p>拍下整盘，留意主食、配菜和酱汁</p>'}</div>
 <div class="mp-actions"><button type="button" id="mp-camera">拍照</button><button type="button" id="mp-album">从相册选择</button><input id="mp-camera-file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden><input id="mp-album-file" type="file" accept="image/jpeg,image/png,image/webp" hidden></div>
 <p id="mp-model" class="mp-help">${esc(draft.modelText||'正在读取视觉服务状态…')}</p><label class="mp-consent"><input type="checkbox" id="mp-consent" ${draft.consent?'checked':''}>我同意将所选照片提交给${draft.mode==='external'?esc(draft.provider||'管理员配置的外部视觉服务'):'轻塑服务器上的视觉服务'}进行识别。轻塑不保存照片；外部服务按其规则处理。</label>
 <button type="button" class="mp-primary" id="mp-recognize" ${!draft.file||draft.busy?'disabled':''}>${draft.busy?'识别中，请稍候…':'识别这张照片'}</button>
 <p id="mp-status" class="mp-help" role="status" aria-live="polite">${esc(draft.message||'尚未保存；也可以直接手动添加食材。')}</p>
 <div class="mp-summary"><div id="mp-ring" class="mp-ring"><div><strong id="mp-cal">—</strong><span>kcal · 估算</span></div></div><dl><dt>蛋白质</dt><dd id="mp-protein_g"></dd><dt>碳水化合物</dt><dd id="mp-carbs_g"></dd><dt>脂肪</dt><dd id="mp-fat_g"></dd></dl></div>
 <p class="mp-help">整餐可食部 <b id="mp-weight"></b> · 环图按已知宏量供能绘制</p>
 <div class="mp-meta"><label>餐名<input id="mp-name" maxlength="120" value="${esc(draft.food_name)}" required></label><label>餐次<select id="mp-slot">${['早餐','午餐','晚餐','加餐','餐食'].map(x=>`<option ${x===draft.slot?'selected':''}>${x}</option>`).join('')}</select></label></div>
 <div class="mp-portions" role="group" aria-label="整餐份量调整"><button type="button" data-scale="0.5">减为一半</button><button type="button" data-scale="2">增加一倍</button><span>相对当前重量；数值会同步更新</span></div>
 <div id="mp-rows">${draft.components.map(rowHtml).join('')}</div><button type="button" id="mp-add" ${draft.components.length>=12?'disabled':''}>＋ 添加食材</button>
 <div class="mp-notes"><p><b>健康评分</b> 未评定 · 缺少完整饮食与评估依据</p><p><b>血糖负荷 GL</b> <span id="mp-gl"></span></p><p>GL = GI × 该份可利用碳水 ÷ 100；多食材结果为近似合计，不代表个人血糖反应。<a href="https://glycemicindex.com/2021/11/glycemic-load-and-diabetes/" target="_blank" rel="noopener noreferrer">计算依据</a></p></div>
 <label class="mp-consent"><input type="checkbox" id="mp-confirm" ${draft.confirmed?'checked':''}>我已核对食材、可食部重量及营养估算</label><div class="mp-savebar"><button type="button" id="mp-cancel">暂不保存</button><button type="button" id="mp-save" class="mp-primary" ${!draft.components.length||draft.saving?'disabled':''}>${draft.saving?'保存中…':draft.recordId?'保存食材修正':'确认并记入饮食'}</button></div>`;
 root.querySelector('#mp-camera').onclick=()=>root.querySelector('#mp-camera-file').click();
 root.querySelector('#mp-album').onclick=()=>root.querySelector('#mp-album-file').click();
 for(const id of ['mp-camera-file','mp-album-file'])root.querySelector('#'+id).onchange=ev=>selectFile(ev.target.files[0]);
 root.querySelector('#mp-consent').onchange=ev=>draft.consent=ev.target.checked;
 root.querySelector('#mp-confirm').onchange=ev=>draft.confirmed=ev.target.checked;
 root.querySelector('#mp-recognize').onclick=recognize;
 root.querySelector('#mp-cancel').onclick=()=>document.getElementById('account-tools-dialog').close();
 root.querySelector('#mp-save').onclick=save;
 root.querySelector('#mp-add').onclick=()=>{if(draft.busy||draft.saving||draft.uncertain)return;collect();draft.components.push(empty());draft.confirmed=false;render();};
 root.querySelectorAll('[data-reference]').forEach(select=>select.onchange=()=>{if(select.value==='')return;collect();const i=Number(select.dataset.reference),ref=references[Number(select.value)];draft.components[i]={...empty(),...ref,grams:draft.components[i].grams};draft.confirmed=false;render();});
 root.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{if(draft.busy||draft.saving||draft.uncertain)return;collect();draft.components.splice(Number(b.dataset.remove),1);draft.confirmed=false;render();});
 root.querySelectorAll('[data-scale]').forEach(b=>b.onclick=()=>{if(draft.busy||draft.saving||draft.uncertain)return;collect();const factor=Number(b.dataset.scale);if(draft.components.some(c=>c.grams*factor>5000||c.grams*factor<=0)||draft.components.reduce((s,c)=>s+c.grams*factor,0)>5000){note('整餐重量需在0到5000g之间',true);return;}draft.components.forEach(c=>c.grams=Math.round(c.grams*factor*10)/10);draft.confirmed=false;render();});
 root.querySelectorAll('[data-field],#mp-name,#mp-slot').forEach(input=>input.oninput=()=>{collect();if(['name','kcal100','protein100','carbs100','fat100'].includes(input.dataset.field)){const i=Number(input.closest('[data-mp-row]').dataset.mpRow);draft.components[i].reference='';}draft.confirmed=false;root.querySelector('#mp-confirm').checked=false;summary();});
 if(draft.busy||draft.saving||draft.uncertain){root.querySelectorAll('[data-field],[data-reference],#mp-name,#mp-slot,#mp-camera,#mp-album,[data-scale],[data-remove],#mp-add,#mp-recognize').forEach(el=>el.disabled=true);}
 summary();
}
function selectFile(file){
 if(!file||!draft||draft.saving||draft.uncertain)return;
 if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024){note('请选择8MB以内的JPEG、PNG或WebP照片',true);return;}
 collect();sequence++;draft.busy=false;draft.file=file;draft.consent=false;draft.confirmed=false;
 if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(file);
 draft.message='照片仅在本机预览，勾选说明并点击识别后才会上传。';render();
}
async function recognize(){
 const d=draft,s=sequence;if(!d||!live(d,s)||d.busy||!d.file)return;
 collect();if(!d.consent||!['local','external'].includes(d.mode)){note('请等待服务状态读取完成，再阅读并勾选照片处理说明',true);return;}
 d.busy=true;d.message='正在识别，通常需要数十秒；离开后旧结果会被忽略。';render();
 const fd=new FormData();fd.append('photo',d.file);fd.append('consent','true');fd.append('mode',d.mode);fd.append('config_revision',d.configRevision||'');
 try{
  const r=await rawPostApi('/api/food/vision/recognize',fd,{timeout:120000,tag:'meal-photo-recognize'});
  if(!live(d,s))return;
  if(r.code!==0||!Array.isArray(r.components)||!r.components.length)throw new Error('未识别到可核对的食材');
  d.components=copy(r.components);d.food_name=r.food_name;d.confirmed=false;d.message=r.note||'识别完成，请核对各项后保存。';
 }catch(e){if(live(d,s))d.message='识别未完成：'+e.message+'；未保存饮食，可手动填写。';}
 finally{if(live(d,s)){d.busy=false;render();}}
}
async function save(){
 const d=draft,s=sequence;if(!d||!live(d,s)||d.saving)return;
 collect();if(!d.confirmed){note('请核对后勾选确认',true);return;}
 const root=document.getElementById('meal-photo-editor');
 const invalid=[...root.querySelectorAll('input[required],input[type=number]')].find(x=>!x.checkValidity());
 if(invalid){invalid.reportValidity();return;}
 if(!d.food_name.trim()||!d.components.length){note('请填写餐名并至少保留一项食材',true);return;}
 const t=totals();if(t.grams>5000||t.cal>10000){note('整餐不能超过5000g或10000kcal，请核对份量',true);return;}
 const body={food_name:d.food_name.trim(),slot:d.slot,components:copy(d.components)};
 if(!d.recordId)Object.assign(body,d.occurrence,{request_id:d.requestId});
 d.saving=true;d.message='正在保存，请稍候…';render();
 try{
  const r=await postApi(d.recordId?'/api/records/food/'+d.recordId+'/update':'/api/food/log',body);
  if(!live(d,s))return;
  if(r.code!==0||!(d.recordId?r.operation==='update':Number.isInteger(r.record_id)||r.duplicate===true))throw Object.assign(new Error('回执不完整，请保留当前内容并重试核对'),{status:0});
  document.getElementById('account-tools-dialog').close();callNativeToast(d.recordId?'食材明细已修正':'这一餐已保存');wbRows=null;
  await Promise.all([syncRemoteDashboard(),syncRemoteCharts(),loadRecentMeals()]);
 }catch(e){if(live(d,s)){d.uncertain=!e.status;d.message=e.message+(d.uncertain?'；已保留内容和重试标识，请点保存重试，避免重复记账':'；请核对食材数据');}}
 finally{if(live(d,s)){d.saving=false;render();}}
}
function open(row){
 if(!state.token){openAuthModal();return;}
 release();let components=[];if(row?.components_json)try{components=JSON.parse(row.components_json);}catch(e){}
 draft={generation:sessionGeneration,food_name:row?.food_name||'',slot:row?.slot||MEAL_SLOT_CN[state.selectedMealSlot]||'餐食',components,
   requestId:uuid(),recordId:row?.id||0,occurrence:occurrenceNow(),file:null,busy:false,saving:false,consent:false,confirmed:false};
 toolDialog(row?'核对食材明细':'拍照识餐','<div id="meal-photo-editor"></div>');render();
 const d=draft,s=sequence,dialog=document.getElementById('account-tools-dialog');
 if(!references.length)getJson('/api/food/vision/references').then(r=>{if(!Array.isArray(r.items))return;references=r.items;if(live(d,s)){collect();render();}}).catch(()=>{});
 dialog.addEventListener('close',()=>{if(draft===d)release();},{once:true});
 watch=setInterval(()=>{if(draft===d&&d.generation!==sessionGeneration){dialog.close();release();}},300);
 getJson('/api/food/vision/status').then(r=>{if(!live(d,s))return;collect();d.mode=r.mode;d.provider=r.provider;d.configRevision=r.config_revision;d.consent=false;d.modelText=!r.configured?'视觉服务尚未配置，可手动添加食材':r.last_failure_at&&(!r.last_success_at||r.last_failure_at>=r.last_success_at)?'视觉服务最近识别失败，可重试或手填 · '+r.model:r.last_success_at?'视觉服务最近识别成功 · '+r.model:'视觉服务已配置 · '+r.model+'（尚未验证本次照片）';render();}).catch(()=>{if(live(d,s)){collect();d.modelText='视觉状态暂未读到，可重试识别或手动填写';render();}});
}
document.getElementById('meal-photo-launch')?.addEventListener('click',()=>open());
const oldEdit=window.editMealRecord;window.editMealRecord=id=>{const row=state.mealDiary.find(x=>x.id===id);return row?.components_json?open(row):oldEdit(id);};
const oldHistory=window.editHistoryRecord;window.editHistoryRecord=id=>{const row=recordKind==='food'?recordRows.find(x=>x.id===id):null;return row?.components_json?open(row):oldHistory(id);};
window.QSMealPhoto={open};
})();
