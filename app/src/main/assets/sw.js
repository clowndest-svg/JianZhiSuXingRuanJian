const CACHE='qingsu-shell-r170';
const SHELL=['/','/app.js','/style.css','/features.js','/features.css','/companion.js','/exercise_poses.json','/manifest.webmanifest','/app-icon.png','/guidance.json','/stickers.json',
 ...['smile','laugh','cry','cheer','water','veg','run','fit','shy','sleep','love','cool','angry','sweat','drool','party','win','beg'].map(id=>'/stickers/'+id+'.svg')];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('qingsu-shell-')&&k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!SHELL.includes(url.pathname))return;
 event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(url.pathname,copy));}return response;}).catch(()=>caches.match(url.pathname)));
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
