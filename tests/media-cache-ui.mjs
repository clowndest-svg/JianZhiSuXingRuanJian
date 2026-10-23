import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const root=new URL('../',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1');
const log=fs.createWriteStream(new URL('../_audit_sandbox/media-cache-browser.log',import.meta.url));
const child=spawn(process.env.QINGSU_TEST_PYTHON||'python',['tests/media-cache-server.py'],{cwd:root,env:process.env});
child.stdout.pipe(log);child.stderr.pipe(log);
let browser;
const base='http://127.0.0.1:18008';
try{
    for(let i=0;i<100;i++){
        try{if((await fetch(base+'/health')).ok)break;}catch{}
        if(child.exitCode!==null)throw Error('cache fixture exited');
        await new Promise(r=>setTimeout(r,150));
    }
    const links=await (await fetch(base+'/test/cache-info')).json();
    browser=await chromium.launch({headless:true,...(process.env.QINGSU_CHROME_PATH?{executablePath:process.env.QINGSU_CHROME_PATH}:{})});
    const page=await browser.newPage();await page.goto(base+'/health');
    const get=url=>page.evaluate(async url=>{const r=await fetch(url);await r.arrayBuffer();return {status:r.status,cache:r.headers.get('cache-control')};},url);
    const count=async()=>Number((await (await fetch(base+'/test/cache-count')).json()).requests);
    assert.equal((await get(links.community)).status,200);
    const first=await count();assert.equal((await get(links.community)).status,200);
    assert.equal(await count(),first,'community thumbnail should be reused while fresh');
    const p=await get(links.private);assert.equal(p.status,200);assert.ok(p.cache.includes('no-store'));
    const before=await count();await get(links.private);assert.equal(await count(),before+1,'private image must reach the server every time');
    assert.equal((await fetch(base+'/test/recall',{method:'POST'})).status,200);
    assert.equal((await get(links.private)).status,404,'saved private link must fail after recall');
    await new Promise(r=>setTimeout(r,4000));
    assert.equal((await get(links.community)).status,404,'browser must not reuse cached bytes after signature expiry');
    console.log('PASS: real Chromium cache hit, private no-store, recall revocation and expiry');
}finally{
    if(browser)await browser.close();
    if(child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}
    log.end();
}
