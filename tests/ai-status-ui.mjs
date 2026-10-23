import vm from 'node:vm';
import assert from 'node:assert/strict';
import {makeCtx,loadJs} from './dom-fixture.mjs';
const h=makeCtx();loadJs(h.context,true);
const box=h.sandbox.document.getElementById('meal-ai-status');
for(const [data,words] of [
 [{online_configured:false},['未配置']],
 [{online_configured:true,online_model:'untested'},['尚未跑通']],
 [{online_configured:true,online_model:'up',online_last_success_at:1,online_last_success_model:'test-model',online_last_elapsed_ms:0},['最近请求成功','test-model','0ms']],
 [{online_configured:true,online_model:'down',online_last_success_at:1,online_last_failure_at:2,online_last_failure_kind:'http_503'},['最近请求失败','http_503']],
]){
 h.sandbox.getJson=async()=>data;
 await vm.runInContext('refreshMealAiStatus()',h.context);
 for(const word of words)assert.ok(box.textContent.includes(word),box.textContent);
}
h.sandbox.getJson=async()=>{throw Error('offline');};
await vm.runInContext('refreshMealAiStatus()',h.context);
assert.ok(box.textContent.includes('尚未确认可用'));
console.log('PASS: AI status UI distinguishes unconfigured, untested, success, failure and offline; zero latency preserved');
