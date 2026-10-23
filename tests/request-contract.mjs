// B02 统一请求底座判据：用假 fetch 打真代码（app.js 的 requestBase/getJson/rawPostApi/postApi
// 与 features.js 的 patchJson/deleteJson/publicPost/上传口），不起服务、纯 node。
// 风格照 tests/frontend-integration.mjs：每段一个全新 ctx，段末 PASS 行。
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { makeCtx, loadJs } from './dom-fixture.mjs';

const ok = x => ({ ok: true, status: 200, json: async () => x });
const fail = (status, body) => ({ ok: false, status, json: async () => body });

// 每个测试块独立环境：载入 app.js+features.js 后把 setTimeout 换成手动计时器，
// 并补一个最小 AbortController（桩环境本来没有，底座据此才装超时）。
function fresh() {
    const h = makeCtx();
    loadJs(h.context, true);
    const timers = [];
    h.sandbox.setTimeout = (fn, ms) => { timers.push({ fn, ms, cancelled: false }); return timers.length; };
    h.sandbox.clearTimeout = id => { const t = timers[id - 1]; if (t) t.cancelled = true; };
    h.sandbox.__timers = timers;
    h.sandbox.__fire = i => { const t = timers[i]; if (t && !t.cancelled) t.fn(); };
    h.sandbox.AbortController = class {
        constructor() {
            const s = { aborted: false, __onaborts: [] };
            this.signal = s;
            this.abort = () => { if (s.aborted) return; s.aborted = true; s.__onaborts.forEach(f => f()); };
        }
    };
    const run = x => vm.runInContext(x, h.context);
    run('state.user={username:"alice"};state.token="alice-token";');
    return { h, run };
}

// 挂起不返回的假 fetch：signal 被 abort 时才以 AbortError 落败（模拟真实 fetch）。
function hanging(h) {
    const seen = [];
    h.sandbox.__fetchHandler = (url, opts) => new Promise((resolve, reject) => {
        const rec = { url, opts, resolve, reject };
        seen.push(rec);
        const sig = opts && opts.signal;
        const onAbort = () => { const e = new Error('The user aborted a request.'); e.name = 'AbortError'; reject(e); };
        if (sig) { if (sig.aborted) onAbort(); else sig.__onaborts.push(onAbort); }
    });
    return seen;
}

// ===== 1. GET 有 15 秒超时，会被中止而不是永久挂起 =====
{
    const { h, run } = fresh();
    const seen = hanging(h);
    const p = run('getJson("/api/records")');
    assert.equal(seen.length, 1);
    const t = h.sandbox.__timers;
    assert.equal(t.length, 1);
    assert.equal(t[0].ms, 15000, 'GET 超时必须挂在底座的 15 秒上');
    h.sandbox.__fire(0);
    const err = await p.then(() => null, e => e);
    assert.equal(err.code, 'timeout');
    assert.equal(err.status, 0);
    assert.equal(err.name, 'AbortError');
    assert.match(err.message, /网络/);
    assert.ok(seen[0].opts.signal.aborted, '超时后必须真的把 fetch 中止掉');
    assert.equal(t[0].cancelled, true, '落定后计时器要撤掉，不能留悬挂回调');
    console.log('PASS: GET 15s 超时会被中止，错误形状 status/code/message 齐全');
}

// ===== 2. 写请求 30 秒、上传 120 秒；上传不带 JSON 头 =====
{
    const { h, run } = fresh();
    const seen = hanging(h);
    const pW = run('rawPostApi("/api/food/log",{food_name:"x"})');
    assert.equal(h.sandbox.__timers[0].ms, 30000, 'JSON 写请求沿用原来的 30 秒');
    h.sandbox.__fire(0); await pW.then(() => null, () => null);
    const pU = run('(()=>{const fd=new FormData();fd.append("file",{size:1});return rawPostApi("/api/community/media",fd);})()');
    const up = seen[1].opts;
    assert.equal(h.sandbox.__timers[1].ms, 120000, 'FormData 上传必须是 120 秒，不能退回 30 秒');
    assert.ok(!up.headers['Content-Type'], 'FormData 不能被强塞 JSON 头');
    assert.ok(up.signal, '上传也要能被超时/取消中止');
    h.sandbox.__fire(1); await pU.then(() => null, () => null);
    console.log('PASS: 超时分级 read=15s / write=30s / upload=120s');
}

// ===== 3. 上传失败不许被当成成功 =====
{
    const { h, run } = fresh();
    h.sandbox.__fetchHandler = (url) => Promise.resolve(
        String(url).includes('/api/account/avatar') ? fail(400, { detail: '这张图太大或格式不对' }) : ok({}));
    run('document.getElementById("avatar-file").files=[{size:1024,name:"a.jpg"}];');
    await run('uploadAvatar()');
    const status = h.mkEl('avatar-status').textContent;
    assert.match(status, /格式不对/, '失败原因要原样说出来');
    assert.ok(!/头像已更新/.test(status), '上传失败绝不许写成功文案');
    // 底座级：上传接口 5xx 同样必须抛出带统一形状的错误，绝不静默
    h.sandbox.__fetchHandler = () => Promise.resolve(fail(500, { detail: '存储满了，图没收下' }));
    const err = await run('rawPostApi("/api/chat/media",(()=>{const fd=new FormData();fd.append("file",{size:1});return fd;})())')
        .then(() => null, e => e);
    assert.equal(err.status, 500); assert.match(err.message, /存储满了/);
    console.log('PASS: 上传失败有明确错误结果，界面不会静默播报成功');
}

// ===== 4. 切账号后旧响应不许写进界面；同账号迟到响应照常接受 =====
{
    const { h, run } = fresh();
    let settle = null;
    h.sandbox.__fetchHandler = () => new Promise((resolve, reject) => { settle = { resolve, reject }; });
    const pOld = run('getJson("/api/records")');
    run('sessionGeneration++;state.user={username:"bob"};state.token="b";');
    settle.resolve(ok({ rows: ['alice 的旧数据'] }));
    const err = await pOld.then(() => null, e => e);
    assert.match(err.message, /账号已切换/);
    assert.equal(err.status, 409);
    assert.equal(err.code, 'stale_session', '代次丢弃必须走统一的 409 形状');
    // 写路径同理：旧账号的成功响应也算失败，不许落草稿
    const pW = run('postApi("/api/food/log",{slot:"午餐",food_name:"alice meal"})');
    run('sessionGeneration++;state.user={username:"carol"};state.token="c";');
    settle.resolve(ok({ code: 0 }));
    const errW = await pW.then(() => null, e => e);
    assert.equal(errW.status, 409);
    assert.equal(run('readDrafts().length'), 0, '被代次丢弃的写不许伪装成本地草稿');
    // 正样本：同账号的迟到响应照常返回数据
    const pSame = run('getJson("/api/records")');
    settle.resolve(ok({ rows: ['carol 的数据'] }));
    assert.deepEqual(await pSame, { rows: ['carol 的数据'] });
    console.log('PASS: 旧账号迟到响应被 409 丢弃，同账号响应正常接受');
}

// ===== 5. 403 的 update_required 与 account_banned 是两条分路 =====
{
    const { h, run } = fresh();
    run('wallCalls=[];banCalls=[];showUpdateWall=function(p){wallCalls.push(p&&p.code);};handleAccountBanned=function(d){banCalls.push(d);};');
    // 故意不给 clone()：让全局 fetch 封装层跳过，单独验证底座自己的分路
    h.sandbox.__fetchHandler = () => Promise.resolve(fail(403, { code: 'update_required', detail: '请更新', min_build: 99 }));
    const e1 = await run('getJson("/api/dashboard")').then(() => null, e => e);
    assert.equal(JSON.stringify(run('wallCalls')), '["update_required"]');
    assert.equal(run('banCalls').length, 0, '强更门不许被当成封号');
    assert.equal(e1.code, 'update_required'); assert.equal(e1.status, 403);

    h.sandbox.__fetchHandler = () => Promise.resolve(fail(403, { code: 'account_banned', detail: '该账号已被停用：发布违规内容' }));
    const e2 = await run('deleteJson("/api/community/posts/1")').then(() => null, e => e);
    assert.equal(run('banCalls').length, 1, '封号分支必须被触发');
    assert.equal(run('wallCalls').length, 1, '封号不许顺手拉起强更门');
    assert.equal(e2.code, 'account_banned');
    assert.match(e2.message, /违规内容/);

    // 对照组：无机器码的普通 403（"只能删自己的帖子"）两扇门都不许碰
    h.sandbox.__fetchHandler = () => Promise.resolve(fail(403, { detail: '只能删自己的帖子' }));
    const e3 = await run('patchJson("/api/community/posts/1",{text:"x"})').then(() => null, e => e);
    assert.equal(run('wallCalls').length, 1);
    assert.equal(run('banCalls').length, 1);
    assert.equal(e3.status, 403); assert.equal(e3.code, '');
    assert.match(e3.message, /只能删自己的帖子/);
    console.log('PASS: 403 按机器码分成强更门/封号/普通拒绝三条互不串路');
}

// ===== 5b. 真 handleAccountBanned：清会话+说清原因，同一发 403 只播一遍 =====
{
    const { h, run } = fresh();
    run('localStorage.setItem(TOKEN_KEY,"tk");');
    // 带 clone()：全局 fetch 封装层与底座会各触发一次真函数，判的就是去重这一条
    const banResp = body => ({ ok: false, status: 403, clone() { return this; }, json: async () => body });
    h.sandbox.__fetchHandler = () => Promise.resolve(banResp({ code: 'account_banned', detail: '已被停用：违规' }));
    await run('getJson("/api/dashboard")').then(() => null, () => null);
    await new Promise(r => setImmediate(r));
    assert.equal(run('localStorage.getItem(TOKEN_KEY)'), null, '封号要清掉本机登录态');
    const banned = h.log.toasts.filter(t => t.includes('已被停用'));
    assert.equal(banned.length, 1, '同一发封号 403 只能播一次：' + banned.join('|'));
    console.log('PASS: 封号清会话、原因原样播报、几秒内不重复轰炸');
}

// ===== 6. 服务器 409：不重试、不写状态、登录态原样保留 =====
{
    const { h, run } = fresh();
    h.sandbox.__fetchHandler = () => Promise.resolve(fail(409, { detail: '恢复请求已变更，请重新登录' }));
    const err = await run('postApi("/api/food/log",{slot:"午餐",food_name:"x"})').then(() => null, e => e);
    assert.equal(err.status, 409);
    assert.equal(err.code, 'conflict');
    assert.equal(h.log.fetches.length, 1, '409 是明确的服务器答复，绝不自动重发');
    assert.equal(run('state.token'), 'alice-token', '409 不许顺手清掉登录态');
    assert.equal(run('readDrafts().length'), 0, '409 也不是网络不通，不许落草稿');
    console.log('PASS: 409 单次请求、统一形状、不改本机状态');
}

// ===== 7. 保存成功但响应丢失：重试必须复用同一个 request_id，不产生第二条 =====
{
    const { h, run } = fresh();
    let first = null;
    h.sandbox.__fetchHandler = (url, opts) => {
        const body = JSON.parse(opts.body);
        if (!first) { first = body; return Promise.reject(new TypeError('Failed to fetch')); } // 已落库、回执丢了
        return Promise.resolve(ok({ code: 0, duplicate: false, request_id: body.request_id }));
    };
    await run('postApi("/api/food/log",{slot:"午餐",food_name:"retry-me"})').then(() => null, () => null);
    assert.ok(first.request_id, '记录类写请求必须带幂等键');
    await run('postApi("/api/food/log",{slot:"午餐",food_name:"retry-me"})');
    const replay = JSON.parse(h.log.fetches[1][1].body);
    assert.equal(replay.request_id, first.request_id, '重试同一条必须复用原 request_id，否则服务端会存第二条');
    // 并发合并（pendingWrites）也要钉住：同键两发只出一个 fetch
    const before = h.log.fetches.length;
    await Promise.all([run('postApi("/api/workout/complete",{duration_minutes:20})'),
                       run('postApi("/api/workout/complete",{duration_minutes:20})')]);
    assert.equal(h.log.fetches.length - before, 1, '同时双击只能发出一条写请求');
    console.log('PASS: 响应丢失后的重试复用 request_id；并发点击合并成一条');
}

// ===== 8. 同一 tag 后发取消先发，旧结果不覆盖新结果 =====
{
    const { h, run } = fresh();
    const seen = hanging(h);
    const p1 = run('getJson("/api/community/feed?tab=new",{tag:"feed"})');
    const p2 = run('getJson("/api/community/feed?tab=new",{tag:"feed"})');
    // 若产品没真的中止旧 fetch，这里会判成 hung 而红，绝不会把判据自己挂死
    const raced = await Promise.race([
        p1.then(() => 'resolved', e => 'rejected:' + (e && e.code)),
        (async () => { for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r)); return 'hung'; })(),
    ]);
    assert.equal(raced, 'rejected:cancelled', '先发的同 tag 请求要被取消而不是继续占着');
    assert.ok(seen[0].opts.signal.aborted, '取消必须真的中止旧 fetch，不让它晚到');
    assert.equal(seen.length, 2, '取消是丢弃旧请求，不是替它重发');
    seen[1].resolve(ok({ items: ['fresh'] }));
    assert.deepEqual(await p2, { items: ['fresh'] });
    assert.equal(run('inflightByTag.size'), 0, '落定后要清出在途表，不能泄漏 tag');
    console.log('PASS: 同 tag 后发取消先发，在途表随落定清空');
}

// ===== 9. 网络错误的统一形状与草稿判定兼容 =====
{
    const { h, run } = fresh();
    h.sandbox.__fetchHandler = () => Promise.reject(new TypeError('Failed to fetch'));
    const err = await run('getJson("/api/records")').then(() => null, e => e);
    assert.equal(err.status, 0, '网络类错误必须无有效状态码，草稿判定靠这一点');
    assert.equal(err.code, 'network');
    assert.equal(err.name, 'TypeError', '原始错误名要保住，features.js 离线草稿按名字认领');
    assert.equal(run('readDrafts().length'), 0, 'GET 失败不落草稿');
    await run('postApi("/api/food/log",{slot:"午餐",food_name:"d"})').then(() => null, () => null);
    assert.equal(run('readDrafts().length'), 1, '写失败仍要落草稿（底座改造后口径不变）');
    console.log('PASS: 断网错误形状统一且不破坏离线草稿判定');
}

// ===== 10. publicPost 免鉴权但共用同一底座（超时/形状一致）=====
{
    const { h, run } = fresh();
    const seen = hanging(h);
    const p = run('publicPost("/api/account/forgot",{email:"a@b.c"})');
    assert.ok(!('Authorization' in seen[0].opts.headers), '免登录链路不许带鉴权头');
    assert.equal(h.sandbox.__timers[0].ms, 30000);
    h.sandbox.__fire(0); await p.then(() => null, () => null);
    h.sandbox.__fetchHandler = () => Promise.resolve(fail(400, { detail: '邮箱没绑过' }));
    const err = await run('publicPost("/api/account/forgot",{email:"a@b.c"})').then(() => null, e => e);
    assert.equal(err.status, 400); assert.match(err.message, /邮箱没绑过/);
    console.log('PASS: publicPost 走底座——无鉴权头、有超时、错误形状统一');
}

console.log('PASS: request-contract 全部判据通过');
