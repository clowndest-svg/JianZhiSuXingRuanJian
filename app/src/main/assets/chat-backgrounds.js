/* Original vector wallpapers and private per-account, per-chat local image storage. */
(function(){
'use strict';
const items=[
 ['mist','薄雾青山','山水','#edf4ef','#a9c4b7','#6f9d92'],['sakura','樱花微雨','花园','#fff1f4','#f2c7d5','#c98fa7'],
 ['moon','月光海岸','月夜','#e8ecfa','#a6b3db','#6d82b4'],['mint','薄荷晴空','云海','#eaf9f3','#b8dfd5','#81b9b1'],
 ['dune','奶油沙丘','沙丘','#fcf4e6','#e2ccad','#c7ab87'],['aurora','极光漫游','星空','#e4f4f6','#b0cddc','#7bacae'],
 ['forest','森间来信','森林','#edf4e9','#c2d5ae','#8ba782'],['ocean','海盐浪花','海洋','#e9f6fb','#b8dcea','#7eb6c9'],
 ['peach','蜜桃花园','花园','#fff0e8','#f1c9b6','#d5a4a0'],['lavender','薰衣草原','花园','#f4effb','#d7c6e9','#ad96c6'],
 ['city','蓝调天际','城市','#eaf0fa','#bdcde2','#849cbd'],['cyber','全息之城','城市','#edeefa','#c4bfdf','#8e99be'],
 ['orbit','失重星河','星空','#eeedfa','#c8c2e4','#9e9bc7'],['whale','鲸游深海','海洋','#e8f1fa','#bfd6e7','#8baecb'],
 ['lemon','柠檬假日','花园','#fcf9e8','#e8dfb1','#baba83'],['snow','初雪远山','山水','#eff4fa','#cfdae6','#a0b4c8'],
 ['sunset','落日邮局','沙丘','#fff0e7','#eac8bc','#c6a6ad'],['cloud','云朵梦乡','云海','#f6f0fc','#ddcfea','#b7abd1'],
 ['rain','雨落竹林','森林','#eaf2ef','#bed3cc','#8baea2'],['rose','玫瑰星笺','月夜','#faedf1','#dec2d4','#b098ba']
].map(([id,name,kind,bg,mid,ink])=>({id,name,kind,bg,mid,ink}));
const uri=s=>'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(s);
function art(t){
 let scene='';const{bg,mid,ink,kind}=t;
 if(['山水','沙丘','海洋'].includes(kind))for(let n=0;n<5;n++)scene+='<path d="M-100 '+(1020+n*120)+' Q130 '+(650+n*120)+' 440 '+(1020+n*95)+' T1000 '+(960+n*140)+' V1700H-100Z" fill="'+(n%2?ink:mid)+'" opacity="'+(.12+n*.055)+'"/>';
 if(kind==='森林')for(let i=0;i<25;i++){let x=i*41-40,y=950+(i%5)*65;scene+='<path d="M'+x+' '+y+'l-65 240h43l-65 150h180l-64-150h40Z" fill="'+ink+'" opacity="'+(.07+(i%4)*.025)+'"/>';}
 if(kind==='城市')for(let i=0;i<22;i++){let x=i*45-20,h=150+(i*83%420);scene+='<rect x="'+x+'" y="'+(1600-h)+'" width="39" height="'+h+'" rx="5" fill="'+ink+'" opacity=".16"/>';for(let y=1620-h;y<1580;y+=32)scene+='<path d="M'+(x+9)+' '+y+'h8m8 0h6" stroke="'+bg+'" stroke-width="5" opacity=".8"/>';}
 if(kind==='花园')for(let i=0;i<24;i++){let x=(i*239)%980-40,y=i%3===0?(i*107)%450:1250+(i*73)%430,r=8+i%5*3;scene+='<g transform="translate('+x+' '+y+')" fill="'+mid+'" opacity=".55"><ellipse cy="-'+r+'" rx="'+r+'" ry="'+(r*1.4)+'"/><ellipse cy="'+r+'" rx="'+r+'" ry="'+(r*1.4)+'"/><ellipse cx="-'+r+'" rx="'+(r*1.4)+'" ry="'+r+'"/><ellipse cx="'+r+'" rx="'+(r*1.4)+'" ry="'+r+'"/><circle r="'+(r*.6)+'" fill="#fff9df"/></g>';}
 if(['云海','月夜','星空'].includes(kind)){
 scene+='<circle cx="720" cy="210" r="85" fill="#fffdf5" opacity=".75"/>';
 if(kind==='月夜')scene+='<circle cx="755" cy="182" r="76" fill="'+bg+'"/>';
 for(let i=0;i<30;i++){let x=(i*197)%900,y=(i*149)%1550;scene+='<path d="M'+x+' '+y+'v10m-5-5h10" stroke="'+ink+'" opacity=".2" stroke-width="2"/>';}
 for(let i=0;i<5;i++)scene+='<ellipse cx="'+(i*240-70)+'" cy="'+(1400+i%2*100)+'" rx="245" ry="120" fill="'+mid+'" opacity=".22"/>';
 }
 if(t.id==='whale')scene+='<g transform="translate(570 1210)" fill="'+ink+'" opacity=".24"><path d="M0 90Q-5 0 95 10q105 10 100 90 55 10 65-35 15 75-65 90Q20 205 0 90Z"/><path d="M80 5Q55-50 35-20M82 4q15-65 42-32" fill="none" stroke="'+ink+'" stroke-width="7"/></g>';
 if(t.id==='orbit')scene+='<g opacity=".3"><circle cx="190" cy="1170" r="80" fill="'+ink+'"/><ellipse cx="190" cy="1170" rx="132" ry="23" transform="rotate(-22 190 1170)" fill="none" stroke="'+mid+'" stroke-width="17"/></g>';
 if(t.id==='aurora')scene+='<path d="M-150 260Q260 20 550 380T1050 220M-150 330Q260 90 550 450T1050 290" fill="none" stroke="'+ink+'" stroke-width="35" opacity=".1"/>';
 if(t.id==='rain')for(let i=0;i<5;i++)scene+='<path d="M'+(60+i*45)+' 1600v-600m-10 60h20m-20 120h20m-20 120h20m-20 120h20" fill="none" stroke="'+ink+'" stroke-width="12" opacity=".13"/>';
 if(t.id==='lemon')scene+='<g transform="translate(670 1280) rotate(-25)" opacity=".4"><ellipse rx="70" ry="96" fill="#dfd47d"/><ellipse rx="54" ry="79" fill="#fff5bb"/><path d="M0-70v140M-45-35l90 70M45-35-45 35" stroke="#dfd47d" stroke-width="5"/></g>';
 if(t.id==='lavender')for(let i=0;i<12;i++){let x=30+i*45;scene+='<path d="M'+x+' 1600q30-100 0-220" stroke="'+ink+'" opacity=".2" fill="none" stroke-width="3"/>';for(let j=0;j<5;j++)scene+='<ellipse cx="'+(x+(j%2?7:-7))+'" cy="'+(1400+j*18)+'" rx="9" ry="15" fill="'+ink+'" opacity=".2"/>';}
 if(t.id==='cyber')scene+='<path d="M0 240h180l80 80v140h160M900 600H730l-80 80v140H500" stroke="'+ink+'" fill="none" stroke-width="3" opacity=".18"/>';
 return uri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1600"><defs><linearGradient id="b" x2=".6" y2="1"><stop stop-color="'+bg+'"/><stop offset="1" stop-color="'+mid+'" stop-opacity=".2"/></linearGradient><pattern id="p" width="27" height="27" patternUnits="userSpaceOnUse"><circle cx="3" cy="4" r=".7" fill="'+ink+'" opacity=".09"/></pattern></defs><rect width="900" height="1600" fill="'+bg+'"/><rect width="900" height="1600" fill="url(#b)"/>'+scene+'<rect width="900" height="1600" fill="url(#p)"/></svg>');
}
const urls=new Map(items.map(t=>[t.id,art(t)]));
const key=()=>state.token&&Number(state.user?.id)>0&&Number(cm.thread?.partner?.id)>0?Number(state.user.id)+':'+Number(cm.thread.partner.id):null;
let dbPromise;
function db(){return dbPromise||(dbPromise=new Promise((resolve,reject)=>{const r=indexedDB.open('qingsu-chat-backgrounds',1);r.onupgradeneeded=()=>r.result.createObjectStore('settings');r.onsuccess=()=>resolve(r.result);r.onerror=()=>{dbPromise=null;reject(r.error);};}));}
async function read(k){const d=await db();return new Promise((resolve,reject)=>{const r=d.transaction('settings').objectStore('settings').get(k);r.onsuccess=()=>resolve(r.result||{id:'default'});r.onerror=()=>reject(r.error);});}
async function save(k,value){const d=await db();return new Promise((resolve,reject)=>{const tr=d.transaction('settings','readwrite');if(value)tr.objectStore('settings').put(value,k);else tr.objectStore('settings').delete(k);tr.oncomplete=resolve;tr.onerror=()=>reject(tr.error);tr.onabort=()=>reject(tr.error);});}
const hosts=new WeakMap();let generation=0,activeHost=null;
async function apply(host,force=false){
 const k=key(),token=state.token;if(!k)return;if(activeHost&&activeHost!==host){const stale=hosts.get(activeHost);if(stale?.url)URL.revokeObjectURL(stale.url);hosts.delete(activeHost);}activeHost=host;const old=hosts.get(host);if(old?.key===k&&!force)return;const ticket=++generation;hosts.set(host,{key:k,ticket,url:old?.url});
 try{const value=await read(k);if(!host.isConnected||key()!==k||state.token!==token||hosts.get(host)?.ticket!==ticket)return;
 if(old?.url)URL.revokeObjectURL(old.url);const url=value.id==='custom'&&value.blob?URL.createObjectURL(value.blob):urls.get(value.id);
 host.style.backgroundImage=url?'url("'+url+'")':'';host.style.backgroundColor=items.find(t=>t.id===value.id)?.bg||'';host.classList.toggle('wallpaper-active',!!url);hosts.set(host,{key:k,ticket,url:value.id==='custom'?url:null});
 }catch(e){hosts.delete(host);}
}
async function imageBlob(file){
 if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('请选择 JPG、PNG 或 WebP 图片');
 if(file.size>12*1024*1024)throw Error('图片不能超过12MB');
 const bitmap=await createImageBitmap(file);try{if(bitmap.width*bitmap.height>32000000)throw Error('图片尺寸过大，请换一张');const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height)),c=document.createElement('canvas');c.width=Math.round(bitmap.width*scale);c.height=Math.round(bitmap.height*scale);c.getContext('2d').fillStyle='#fff';c.getContext('2d').fillRect(0,0,c.width,c.height);c.getContext('2d').drawImage(bitmap,0,0,c.width,c.height);return await new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error('图片处理失败')),'image/jpeg',.86));}finally{bitmap.close();}
}
async function open(){
 const k=key(),token=state.token;if(!k)return;let selected;try{selected=await read(k);}catch(e){callNativeToast('浏览器无法保存本机背景，请检查存储权限');return;}if(key()!==k||state.token!==token)return;
 toolDialog('聊天背景','<section class="wallpaper-panel"><p>仅当前账号的这段聊天生效，背景和相册图片保存在本机。</p><div class="wallpaper-preview"><span>把今天的小确幸，分享给你。</span></div><div class="wallpaper-toolbar"><label class="td-btn td-btn-quiet">上传图片<input type="file" accept="image/jpeg,image/png,image/webp" hidden data-wallpaper-upload></label><button type="button" data-wallpaper-reset>恢复默认</button><button type="button" data-wallpaper-delete>删除本机背景</button></div><p class="wallpaper-hint" role="status">支持 JPG / PNG / WebP，最大12MB，自动优化图片尺寸。</p><div class="wallpaper-grid">'+items.map(t=>'<button type="button" data-wallpaper-id="'+t.id+'"><i style="background-image:url(&quot;'+urls.get(t.id)+'&quot;)"></i><strong>'+t.name+'</strong><small>'+t.kind+'</small></button>').join('')+'</div><footer><button type="button" class="td-btn" data-wallpaper-apply>使用这个背景</button></footer></section>');
 const dialog=document.getElementById('account-tools-dialog');dialog.classList.add('wallpaper-dialog');let previewURL=null,busy=false;const hint=dialog.querySelector('.wallpaper-hint');
 function preview(){if(previewURL)URL.revokeObjectURL(previewURL);previewURL=selected.id==='custom'&&selected.blob?URL.createObjectURL(selected.blob):null;const u=previewURL||urls.get(selected.id);dialog.querySelector('.wallpaper-preview').style.backgroundImage=u?'url("'+u+'")':'';dialog.querySelectorAll('[data-wallpaper-id]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.wallpaperId===selected.id)));}
 dialog.addEventListener('close',()=>{if(previewURL)URL.revokeObjectURL(previewURL);},{once:true});preview();
 dialog.addEventListener('change',async e=>{if(!e.target.matches('[data-wallpaper-upload]')||!e.target.files[0])return;busy=true;dialog.querySelector('[data-wallpaper-apply]').disabled=true;try{const blob=await imageBlob(e.target.files[0]);if(key()!==k||state.token!==token||!dialog.isConnected||!dialog.open)return;selected={id:'custom',blob};preview();hint.textContent='图片已就绪，点击下方按钮保存。';}catch(err){hint.textContent=err.message||'图片无法读取';}finally{busy=false;if(dialog.isConnected)dialog.querySelector('[data-wallpaper-apply]').disabled=false;e.target.value='';}});
 dialog.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b||busy)return;if(b.dataset.wallpaperId){selected={id:b.dataset.wallpaperId};preview();return;}if(b.hasAttribute('data-wallpaper-reset')){selected={id:'default'};preview();return;}
 const deleting=b.hasAttribute('data-wallpaper-delete');if(!deleting&&!b.hasAttribute('data-wallpaper-apply'))return;if(key()!==k||state.token!==token){dialog.close();return;}busy=true;b.disabled=true;try{await save(k,deleting?null:selected);if(key()!==k||state.token!==token)return;const host=document.getElementById('thread-bubbles');if(host)await apply(host,true);dialog.close();callNativeToast(deleting?'已删除本机背景':'背景换好了');}catch(err){hint.textContent='保存失败，请检查本机存储空间后重试';}finally{busy=false;b.disabled=false;}});
}
window.QSWallpapers={items,open,apply,preview:id=>urls.get(id)};
})();
