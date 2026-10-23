// PWA 壳缓存契约：缓存键含查询串、静态壳白名单、条目上限、缓存名随构建号派生。
// 不起服务：sw.js 直接在 vm 里跑，CacheStorage 用手写的假实现（keys() 按写入顺序返回）。
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ORIGIN='https://example.test';
const MAX_ENTRIES=64;

class FakeCache{
  constructor(name){this.name=name;this.entries=[];}
  async put(key,response){
    const href=new URL(typeof key==='string'?key:key.url,ORIGIN).href;
    const body=await response.clone().text();
    const at=this.entries.findIndex(entry=>entry.url===href);
    if(at>=0)this.entries.splice(at,1);
    this.entries.push({url:href,body});
  }
  async delete(request){
    const href=new URL(typeof request==='string'?request:request.url,ORIGIN).href;
    const at=this.entries.findIndex(entry=>entry.url===href);
    if(at>=0)this.entries.splice(at,1);
    return at>=0;
  }
  async match(key){
    const href=new URL(typeof key==='string'?key:key.url,ORIGIN).href;
    const hit=this.entries.find(entry=>entry.url===href);
    return hit?new Response(hit.body,{status:200}):undefined;
  }
  async keys(){return this.entries.map(entry=>({request:{url:entry.url}}));}
  async addAll(urls){for(const url of urls)await this.put(url,new Response('bundled:'+url,{status:200}));}
}

function boot(source,{seed=[]}={}){
  const stores=new Map();
  const events={};
  let fetches=0;
  let offline=false;
  const cacheName='qingsu-shell-b'+Number(source.match(/const BUILD=(\d+);/)[1]);
  for(const name of seed)stores.set(name,new FakeCache(name));
  const current=()=>{if(!stores.has(cacheName))stores.set(cacheName,new FakeCache(cacheName));return stores.get(cacheName);};
  const self={location:{origin:ORIGIN,href:ORIGIN+'/'},addEventListener:(type,handler)=>{events[type]=handler;},
    skipWaiting(){},registration:{showNotification:async()=>{}}};
  const caches={
    open:async name=>{if(!stores.has(name))stores.set(name,new FakeCache(name));return stores.get(name);},
    keys:async()=>[...stores.keys()],
    delete:async name=>stores.delete(name),
    async match(key){for(const store of stores.values()){const hit=await store.match(key);if(hit)return hit;}},
  };
  const sandbox={self,caches,URL,Response,Request,Promise,console,
    clients:{matchAll:async()=>[],openWindow:async()=>{}},
    fetch:async request=>{fetches++;
      if(offline)throw new TypeError('offline');
      return new Response('body:'+new URL(request.url).pathname+new URL(request.url).search,{status:200});}};
  vm.createContext(sandbox);
  vm.runInContext(source,sandbox);
  const fire=async type=>{
    const waits=[];
    const event={waitUntil:promise=>waits.push(promise),respondWith:promise=>waits.push(promise),
      request:new Request(ORIGIN+'/'),notification:{close(){}}};
    await events[type](event);
    await Promise.all(waits);
  };
  const request=async input=>{
    const waits=[];
    let responded;
    const event={request:new Request(new URL(input,ORIGIN),{method:'GET'}),
      waitUntil:promise=>waits.push(promise),respondWith:promise=>{responded=promise;}};
    await events.fetch(event);
    if(!responded)return null;
    const response=await responded;
    await Promise.all(waits);
    if(!response)throw new TypeError('SW 接了请求却没给出响应：'+input);
    return response;
  };
  return {install:()=>fire('install'),activate:()=>fire('activate'),request,stores,current,
    goOffline:()=>{offline=true;},
    urls:async()=>(await current().keys()).map(entry=>entry.request.url),fetchCount:()=>fetches,cacheName};
}

const swSource=fs.readFileSync(path.join(root,'app/src/main/assets/sw.js'),'utf8');
const buildCode=Number(fs.readFileSync(path.join(root,'app/build.gradle'),'utf8').match(/versionCode\s+(\d+)/)[1]);
const swBuild=Number(swSource.match(/const BUILD=(\d+);/)[1]);
const versionSource=fs.readFileSync(path.join(root,'make_version_json.py'),'utf8');

assert.equal(swBuild,buildCode,'sw.js 的 BUILD 与 build.gradle 的 versionCode 分叉了（缓存名会停在旧壳）');
assert.ok(!/qingsu-shell-r\d/.test(swSource),'sw.js 里还留着写死的 rXXX 缓存名');
assert.ok(/const BUILD=(\d+);/.test(swSource)&&swSource.includes("CACHE='qingsu-shell-b'+BUILD"),'缓存名不是从构建号派生的');
assert.ok(versionSource.includes('def sync_sw_build(')&&versionSource.includes('sync_sw_build(code)'),
  'make_version_json.py 没有将构建号同步进 sw.js（等于再造一份手写真值）');

const worker=boot(swSource);
await worker.install();
assert.equal(worker.stores.has(worker.cacheName),true,'install 没有按构建号命名的缓存');

await worker.request('/app.js?v=aaaaaa');
await worker.request('/app.js?v=bbbbbb');
let urls=await worker.urls();
assert.ok(urls.includes(ORIGIN+'/app.js?v=aaaaaa'),'同一资源的旧版本被新版本覆盖掉了');
assert.ok(urls.includes(ORIGIN+'/app.js?v=bbbbbb'),'同一资源的新版本没进缓存');
await worker.request('/app.js?v=aaaaaa');
assert.equal((await worker.urls()).length,urls.length,'重复缓存同一键把条目数翻倍了');

const before=urls.length;
for(const url of ['/api/feed','/api/community/posts/12','/uploads/photo.jpg','/health/ready','/ws/chat']){
  assert.equal(await worker.request(url),null,'SW 不该接管 '+url+'（静态壳之外一律不拦）');
}
assert.equal((await worker.urls()).length,before,'非 SHELL 路径进了壳缓存（API/媒体不能进）');

const trimmer=boot(swSource);
for(let index=0;index<MAX_ENTRIES+6;index++)await trimmer.request('/app.js?v=p'+index);
urls=await trimmer.urls();
assert.equal(urls.length,MAX_ENTRIES,'缓存没有上限，现在有 '+urls.length+' 条');
assert.ok(!urls.includes(ORIGIN+'/app.js?v=p0'),'超限时最旧的条目没被淘汰');
assert.ok(!urls.includes(ORIGIN+'/app.js?v=p5'),'超限后第 6 旧的条目还在，淘汰位置不对');
assert.ok(urls.includes(ORIGIN+'/app.js?v=p6'),'被淘汰的不是最旧的 6 条');
assert.ok(urls.includes(ORIGIN+'/app.js?v=p'+(MAX_ENTRIES+5)),'最新条目被淘汰了（顺序反了）');

const replay=boot(swSource);
await replay.install();
await replay.request('/features.js?v=two');
await replay.request('/features.js?v=one');
replay.goOffline();
const replayCount=(await replay.urls()).length;
assert.equal(await (await replay.request('/features.js?v=one')).text(),'body:/features.js?v=one',
  '离线重放串版本了：缓存键没带上查询串');
assert.equal(await replay.request('/api/feed'),null,'离线时 API 请求不该被壳缓存接住');
assert.equal((await replay.urls()).length,replayCount,'离线时 API 响应进了壳缓存');

const upgraded=boot(swSource.replace(/const BUILD=\d+;/,'const BUILD=9999;'),
  {seed:['qingsu-shell-r178','qingsu-shell-b'+swBuild]});
await upgraded.install();
await upgraded.activate();
assert.equal(upgraded.stores.has('qingsu-shell-r178'),false,'activate 没删掉手写死名的旧缓存');
assert.equal(upgraded.stores.has('qingsu-shell-b'+swBuild),false,'activate 没删掉上一构建号的旧缓存');
assert.equal(upgraded.stores.has('qingsu-shell-b9999'),true,'activate 把当前版本缓存也删了');

console.log('PASS: pwa cache key keeps query string, static-only whitelist, '+MAX_ENTRIES+'-entry trim, build-derived cache name, offline replay');
