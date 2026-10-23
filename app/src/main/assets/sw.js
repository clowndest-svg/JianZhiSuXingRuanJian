// 缓存名挂构建号，构建号只认 build.gradle：手抄一次的后果是升级后还在发上一版壳
const BUILD=69;
const CACHE='qingsu-shell-b'+BUILD;
const SHELL=['/','/app.js','/style.css','/features.js','/features.css','/bubble-themes.js','/bubble-themes.css','/chat-backgrounds.js','/chat-backgrounds.css','/chat-tools.js','/chat-tools.css','/companion.js','/exercise_poses.json','/manifest.webmanifest','/app-icon.png','/guidance.json','/stickers.json',
 ...['smile','laugh','cry','cheer','water','veg','run','fit','shy','sleep','love','cool','angry','sweat','drool','party','win','beg'].map(id=>'/stickers/'+id+'.svg')];
const MAX_ENTRIES=64;
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('qingsu-shell-')&&k!==CACHE).map(k=>caches.delete(k))))));
async function remember(cache,key,response){
 await cache.put(key,response);
 const keys=await cache.keys();
 // 查询串进 key 后同一资源每个 ?v= 版本各占一条，不设上限就会把整份壳撑到无限增长
 for(const stale of keys.slice(0,Math.max(0,keys.length-MAX_ENTRIES)))await cache.delete(stale.request);
}
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||(!SHELL.includes(url.pathname)&&!['/bubble-ai.png','/bubble-moon.png'].includes(url.pathname)))return;
 const key=url.pathname+url.search;
 event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();event.waitUntil(caches.open(CACHE).then(c=>remember(c,key,copy)));}return response;}).catch(()=>caches.match(key)));
});
self.addEventListener('message',event=>{if(event.data?.type==='activate-update')self.skipWaiting();});
self.addEventListener('push',event=>event.waitUntil(self.registration.showNotification('轻塑 · 有新消息',{
 body:'你有新的私信或互动，打开轻塑查看。',icon:'/app-icon.png',badge:'/app-icon.png',tag:'qingsu-messages',data:{path:'/'},
})));
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(async windows=>{
   const target=windows.find(w=>new URL(w.url).origin===self.location.origin && new URL(w.url).pathname==='/');
   if(target){await target.focus();target.postMessage({type:'open-messages'});return;}
   return clients.openWindow('/?open=messages');
 }));
});
