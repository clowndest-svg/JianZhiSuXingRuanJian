const CACHE='qingsu-shell-r150-1';
const SHELL=['/','/app.js','/style.css','/features.js','/features.css','/exercise_poses.json','/manifest.webmanifest','/app-icon.png','/guidance.json'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('qingsu-shell-')&&k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!SHELL.includes(url.pathname))return;
 event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(url.pathname,copy));}return response;}).catch(()=>caches.match(url.pathname)));
});
