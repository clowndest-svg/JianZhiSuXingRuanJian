// B08 私信/通话状态判据：纯 node + 假 fetch + 假 WebSocket，不起服务、不开浏览器。
// 钉的是四件事：气泡四态常驻、失败可单条重试且复用 request_id、重连后补拉遗漏、
// 通话失败分型且取消/重试后不留"忙线"僵尸态。风格照 tests/request-contract.mjs。
//
// 2026-10-22 实现并接进 CI。产品侧的 cm.pending/cm.failed/dmRetrySend/failKind/重连补拉
// 都是这一轮加上的。判据自身修了三处（都是判据的错，不是产品的错，别记反）：
//  · pullsBefore 可能是 undefined（首次连接本来就不补拉），1 > undefined 恒假；
//  · 期望词写成产品文案里不存在的"没接听/挂"（产品写的是"没有接听/对方已挂断"）。
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { makeCtx, loadJs } from './dom-fixture.mjs';

const okJson = x => ({ ok: true, status: 200, json: async () => x });

function fresh(opts = {}) {
    const h = makeCtx();
    loadJs(h.context, true);
    const timers = [], intervals = [], sockets = [];
    h.sandbox.setTimeout = (fn, ms) => { timers.push({ fn, ms, cancelled: false }); return timers.length; };
    h.sandbox.clearTimeout = id => { const t = timers[id - 1]; if (t) t.cancelled = true; };
    h.sandbox.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
    h.sandbox.clearInterval = id => { const t = intervals[id - 1]; if (t) t.stopped = true; };
    h.sandbox.__timers = timers;
    // 到点触发最后挂上去的那只计时器（通话结束自动收起就靠它）
    h.sandbox.__fireLast = () => { const t = timers[timers.length - 1]; if (t && !t.cancelled) t.fn(); };
    class FakeSocket {
        constructor(url) {
            this.url = url; this.readyState = 0; this.sent = [];
            this.onopen = null; this.onclose = null; this.onerror = null; this.onmessage = null;
            sockets.push(this);
        }
        send(text) { this.sent.push(JSON.parse(text)); }
        close() { this.readyState = 3; }
    }
    h.sandbox.WebSocket = FakeSocket;
    h.sandbox.__sockets = sockets;
    h.sandbox.RTCPeerConnection = class {
        constructor() { this.connectionState = 'new'; this.localDescription = null; this.remoteDescription = null; }
        createOffer() { return Promise.resolve({ type: 'offer', sdp: 'v=0 fake' }); }
        createAnswer() { return Promise.resolve({ type: 'answer', sdp: 'v=0 fake' }); }
        setLocalDescription(d) { this.localDescription = d; return Promise.resolve(); }
        setRemoteDescription(d) { this.remoteDescription = d; return Promise.resolve(); }
        addTrack() {} addIceCandidate() { return Promise.resolve(); } close() { this.connectionState = 'closed'; }
    };
    h.sandbox.navigator.mediaDevices = {
        getUserMedia: async () => ({ getTracks: () => [], getAudioTracks: () => [] })
    };
    const seen = { sends: [], messages: opts.messages || [] };
    h.sandbox.__seen = seen;
    h.sandbox.__fetchHandler = (url, o) => {
        const u = String(url);
        if (u.includes('/api/chat/send')) {
            seen.sends.push(JSON.parse(o.body));
            if (opts.failSend) return Promise.reject(new TypeError('Failed to fetch'));
            const body = JSON.parse(o.body);
            return Promise.resolve(okJson({ code: 0, message: {
                id: 100 + seen.sends.length, from_id: 1, to_id: body.to, body: body.text,
                kind: body.kind || 'text', created_at: '2026-10-22 10:00:00', read_at: null,
                request_id: body.request_id } }));
        }
        if (u.includes('/api/chat/messages')) {
            seen.messagesPulled = (seen.messagesPulled || 0) + 1;
            return Promise.resolve(okJson({ code: 0, me_id: 1, items: seen.messages,
                partner: { id: 2, name: '对方', blocked: false, mutual_follow: true },
                more: false, next_cursor: 0 }));
        }
        if (u.includes('/api/rtc/ice')) return Promise.resolve(okJson({ ice_servers: [] }));
        return Promise.resolve(okJson({ code: 0 }));
    };
    const run = x => vm.runInContext(x, h.context);
    // 桩元素的 children/insertBefore/replaceWith 是空的，dmRenderBubbles 靠 keyed 复用
    // 来更新气泡，少一样就测不到"状态变了要重绘、没变不许重绘"。
    const shim = el => {
        if (el.__shim) return el;
        el.__shim = true; el._kids = [];
        Object.defineProperty(el, 'children', { get() { return this._kids.slice(); } });
        Object.defineProperty(el, 'firstElementChild', { get() { return this._kids[0] || null; } });
        el.appendChild = c => { el._kids.push(c); return c; };
        el.insertBefore = (c, ref) => { const i = el._kids.indexOf(ref); el._kids.splice(i < 0 ? el._kids.length : i, 0, c); return c; };
        el.replaceWith = function (next) { const i = el._kids.indexOf(this); if (i >= 0) el._kids[i] = next; else el._kids.push(next); };
        el.remove = function () { const i = el._kids.indexOf(this); if (i >= 0) el._kids.splice(i, 1); };
        el.scrollTop = 0; el.scrollHeight = 0; el.clientHeight = 0;
        return el;
    };
    const origCreate = h.sandbox.document.createElement;
    h.sandbox.document.createElement = t => shim(origCreate(t));
    ['thread-bubbles', 'dm-call-layer', 'dm-call-mini'].forEach(id => shim(h.mkEl(id)));
    run('state.user={id:1,username:"alice"};state.token="alice-token";'
        + 'QS_PAGES.push({name:"dm",arg:2,title:"私信",render:()=>{}});'
        + 'cm.thread={partner:{id:2,name:"对方",blocked:false,mutual_follow:true},more:false,cursor:0};'
        + 'cm.bubbles=[];cm.wsRetry=0;');
    // 先渲染一次线程：输入栏挂载时会 dmCleanup()，不预挂就把后面的判据全打成"界面过期"
    run('paintThread()');
    return { h, run, seen };
}

// ===== 1. 气泡必须有常驻的 发送中 / 已发送 / 已读 状态，不是一闪的 toast =====
{
    const { run } = fresh();
    const pending = run('cmBubbleHTML({id:0,from_id:1,to_id:2,body:"在吗",kind:"text",created_at:""},1,"pending")');
    assert.match(pending, /发送中/, '待发出去的气泡要一直写着发送中');
    assert.match(pending, /dm-status/, '状态得挂在气泡上，不能只靠 time 标签');
    const sent = run('cmBubbleHTML({id:5,from_id:1,to_id:2,body:"发了",kind:"text",created_at:"2026-10-22 10:00:00"},1,"")');
    assert.match(sent, /已发送/);
    assert.ok(!/已读/.test(sent), '还没人读就不许写已读');
    const read = run('cmBubbleHTML({id:6,from_id:1,to_id:2,body:"读了",kind:"text",read_at:"2026-10-22 10:01:00",created_at:"2026-10-22 10:00:00"},1,"")');
    assert.match(read, /已读/);
    const theirs = run('cmBubbleHTML({id:7,from_id:2,to_id:1,body:"对方说的",kind:"text",created_at:"2026-10-22 10:00:00"},1,"")');
    assert.ok(!/已发送|已读|发送中/.test(theirs), '对方那条不许挂我这边的投递状态');
    console.log('PASS: 气泡常驻状态 发送中/已发送/已读 三条分开，对方气泡不串状态');
}

// ===== 2. 失败的那条要常驻可见，并且能单条重试 =====
{
    const { run, seen } = fresh({ failSend: true });
    run('document.getElementById("dm-input").value="发不出去的一句话";');
    await run('sendDM()');
    assert.equal(Object.keys(run('cm.pending')).length, 0, '失败后不该继续占着发送中');
    assert.equal(Object.keys(run('cm.failed')).length, 1, '失败必须留在 cm.failed 里，不能只弹一次 toast');
    const rid = Object.keys(run('cm.failed'))[0];
    const html = run(`cmBubbleHTML(cm.failed[${JSON.stringify(rid)}].msg,1,"failed")`);
    assert.match(html, /没发出去|发送失败/, '失败的气泡要一眼看得出来');
    assert.match(html, /dmRetrySend/, '失败的那条必须自带单条重试按钮');
    // 退出再进来（换线程重绘）失败标记不能丢
    run('dmCleanup();QS_PAGES.push({name:"dm",arg:2,title:"私信",render:()=>{}});'
        + 'cm.thread={partner:{id:2,name:"对方",blocked:false},more:false,cursor:0};');
    assert.equal(Object.keys(run('cm.failed')).length, 1, '重进会话还得看得见那条失败');
    // 换账号必须清掉，否则上一个人的失败气泡会串到下一个账号
    run('resetCommunity()');
    assert.equal(Object.keys(run('cm.failed')).length, 0, '切账号不许把上一账号的失败留下');
    console.log('PASS: 失败常驻 + 单条重试入口在，重进会话不丢、切账号清干净');
}

// ===== 3. 单条重试复用同一个 request_id，服务端只落一条 =====
{
    const { h, run, seen } = fresh({ failSend: true });
    run('document.getElementById("dm-input").value="重试同一条";');
    await run('sendDM()');
    const rid = Object.keys(run('cm.failed'))[0];
    assert.equal(seen.sends.length, 1);
    assert.equal(seen.sends[0].request_id, rid, '首发就得带幂等键');
    assert.equal(run('document.getElementById("dm-input").value'), '重试同一条', '失败后原文要还给输入框，不能吞字');
    // 现在让网络恢复：点那条气泡上的重试
    const retries = [];
    h.sandbox.__fetchHandler = (url, o) => {
        const u = String(url);
        if (u.includes('/api/chat/send')) {
            const b = JSON.parse(o.body); retries.push(b);
            return Promise.resolve(okJson({ code: 0, message: { id: 200, from_id: 1, to_id: b.to,
                body: b.text, kind: 'text', created_at: '2026-10-22 10:02:00', read_at: null,
                request_id: b.request_id } }));
        }
        return Promise.resolve(okJson({ code: 0 }));
    };
    await run(`dmRetrySend(${JSON.stringify(rid)})`);
    assert.equal(retries.length, 1, '重试只许发一条请求');
    assert.equal(retries[0].request_id, rid, '重试必须复用原 request_id，否则服务端会存第二条');
    assert.equal(run('cm.bubbles.filter(m=>m.body==="重试同一条").length'), 1, 'ack 之后界面上只能有一条');
    assert.equal(Object.keys(run('cm.failed')).length, 0, '重试成功后失败标记要撤掉');
    assert.equal(Object.keys(run('cm.pending')).length, 0, 'ack 之后不该再有发送中');
    assert.match(run('cmBubbleHTML(cm.bubbles.find(m=>m.body==="重试同一条"),1,"")'), /已发送/);
    console.log('PASS: 单条重试复用 request_id、界面只留一条、状态转成已发送');
}

// ===== 4. 重连成功后必须补拉断连期间到达的消息 =====
{
    const { h, run, seen } = fresh();
    await run('connectChat()');
    const s1 = h.sandbox.__sockets[0];
    s1.readyState = 1; s1.onopen();
    assert.equal(run('cm.wsState'), 'connected');
    // 首次连接本来就不该补拉（没有"遗漏"），所以基线可能是 undefined：
    // 直接比 `1 > undefined` 恒假，会把"补拉已经发生"误判成没发生。
    const pullsBefore = seen.messagesPulled || 0;
    // 掉线：对端在断线期间发了一条，只有服务端历史里有
    s1.onclose({ code: 1006 });
    assert.equal(run('cm.wsState'), 'closed');
    seen.messages = seen.messages.concat([{ id: 9, from_id: 2, to_id: 1, body: '断线期间到的',
        kind: 'text', created_at: '2026-10-22 10:03:00' }]);
    await run('connectChat()');
    const s2 = h.sandbox.__sockets[1];
    s2.readyState = 1; s2.onopen();
    assert.ok(seen.messagesPulled > pullsBefore, '重连成功后必须重新拉一次历史，不能只把连接接上');
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));
    assert.ok(run('cm.bubbles.some(m=>m.body==="断线期间到的")'), '断连期间到达的消息要补回界面');
    // 补拉是幂等的：同一条消息不因 ws 推送 + 拉取各来一遍
    const dup = run('cm.bubbles.filter(m=>m.body==="断线期间到的").length');
    assert.equal(dup, 1, '补拉与推送不能存出两条');
    console.log('PASS: 重连后自动补拉遗漏消息且不重复');
}

// ===== 5. 通话失败要分得清是哪一种 =====
{
    const { h, run } = fresh();
    // 期望词取产品文案里真正出现的那几个字：要钉的是"五种失败各有各的说法"，
    // 不是钉某一句原文。写成产品里不存在的词（没接听 / 挂）会把好文案判成红。
    const cases = [['call_reject', '拒绝'], ['call_timeout', '接听'], ['call_busy', '忙'],
                   ['call_unavailable', '不在线'], ['call_end', '挂断']];
    for (const [kind, word] of cases) {
        run('dmCallReset();dmCall.state="outgoing";dmCall.id="cAbCdEfGhIj";dmCall.peer={id:2,name:"对方"};');
        run(`dmHandleCallEvent({t:${JSON.stringify(kind)},call_id:"cAbCdEfGhIj",from:{id:2,name:"对方"}})`);
        assert.equal(run('dmCall.state'), 'ended');
        const reason = run('dmCall.reason');
        assert.ok(new RegExp(word).test(reason), kind + ' 的失败文案要带「' + word + '」，实际：' + reason);
        assert.notEqual(run('dmCall.failKind'), '', kind + ' 必须记下失败类型');
        const html = run('dmCallLayer().innerHTML');
        assert.match(html, new RegExp(word), kind + ' 的界面要看得见原因');
    }
    // 麦克风没给 与 网络/TURN 不通 是两码事，不许都写成"通话失败"
    run('dmCallReset();dmCall.state="incoming";dmCall.id="cAbCdEfGhIj";dmCall.offer={type:"offer",sdp:"v=0"};');
    run('navigator.mediaDevices.getUserMedia = async () => { const e=new Error("Permission denied"); e.name="NotAllowedError"; return Promise.reject(e); };');
    await run('dmAcceptCall()');
    const micReason = run('dmCall.reason'), micKind = run('dmCall.failKind');
    assert.match(micReason, /麦克风|权限/, '拒麦克风要说清是没权限，实际：' + micReason);
    assert.equal(micKind, 'no_mic');
    run('dmCallReset();dmCall.state="outgoing";dmCall.id="cAbCdEfGhIj";dmCall.peer={id:2,name:"对方"};');
    run('dmCallFinish("网络不通或中继不可用（TURN）","network")');
    assert.equal(run('dmCall.failKind'), 'network');
    assert.match(run('dmCallLayer().innerHTML'), /TURN|网络/);
    console.log('PASS: 通话失败分成 拒绝/未接/忙线/不在线/没权限/网络-TURN 六种可读原因');
}

// ===== 6. 失败面板不许自己消失，也不许留"忙线"僵尸态 =====
{
    const { h, run } = fresh();
    run('dmCallReset();dmCall.state="outgoing";dmCall.id="cAbCdEfGhIj";');
    run('dmCancelCall()');
    assert.equal(run('dmCall.state'), 'ended');
    assert.equal(run('dmCall.failKind'), 'cancelled');
    // 失败/取消的原因必须留得够久，让人读得完（不是一闪就没）
    const t = h.sandbox.__timers[h.sandbox.__timers.length - 1];
    assert.ok(t.ms >= 5000, '通话结果面板至少要停 5 秒，实测 ' + t.ms + 'ms');
    h.sandbox.__fireLast();
    assert.equal(run('dmCall.state'), 'idle', '到点要自动收回，不能永远压在页面上');
    // 取消之后立刻重试：不能被"现在已经在通话里了"挡回去（这就是忙线僵尸态）
    run('dmCallReset();dmCall.state="ended";dmCall.failKind="cancelled";dmCall.reason="已取消";');
    const toastsBefore = h.log.toasts.length;
    run('cm.ws={readyState:1,send(){},onopen:null,onclose:null,onmessage:null,onerror:null};cm.wsState="connected";');
    await run('dmStartCall()');
    assert.ok(!h.log.toasts.slice(toastsBefore).some(x => /已经在通话里/.test(x)),
              '刚取消完再点呼叫不许被当成忙线');
    assert.equal(run('dmCall.state'), 'outgoing', '重试要真的重新发起呼叫');
    // 通话中收到新邀请仍然要拒掉，不许两通叠一起
    run('dmHandleCallEvent({t:"call_invite",call_id:"cZzZzZzZzZz",from:{id:3,name:"第三人"},sdp:{type:"offer",sdp:"v=0"}})');
    assert.equal(run('dmCall.state'), 'outgoing', '第二通邀请不许把当前这通话顶掉');
    run('dmCallReset();');
    assert.equal(run('dmCall.state'), 'idle');
    console.log('PASS: 取消/重试不留忙线僵尸态，失败面板停留够久且能自动收回');
}

// ===== 7. 已读回执要把状态从 已发送 翻成 已读 =====
{
    const { run } = fresh();
    run('cm.bubbles=[{id:1,from_id:1,to_id:2,body:"我发的",kind:"text",created_at:"2026-10-22 10:00:00",read_at:null}];');
    assert.match(run('cmBubbleHTML(cm.bubbles[0],1,"")'), /已发送/);
    run('handleWsEvent({data:JSON.stringify({t:"read",by:2})})');
    assert.ok(run('cm.bubbles[0].read_at'), '收到 read 事件要给本人的气泡补 read_at');
    assert.match(run('cmBubbleHTML(cm.bubbles[0],1,"")'), /已读/);
    console.log('PASS: ws 已读回执能把气泡状态从已发送翻到已读');
}

{
    const { h, run } = fresh();
    run('cm.thread.partner.mutual_follow=false;paintThread();');
    assert.match(run('document.getElementById("pl-slot").innerHTML'), /disabled title="互相关注后才能语音通话"/);
    let permissions=0;
    h.sandbox.dmEnsureMicrophone=async()=>{permissions++;return true;};
    await run('dmStartCall()');
    assert.equal(permissions,0,'非互关不应请求麦克风');
    assert.equal(run('dmCall.state'),'idle');
    assert.match(h.log.toasts.at(-1),/互相关注/);
    console.log('PASS: 非互关按钮禁用，直接调用也在申请麦克风前拒绝');
}
console.log('PASS: dm-state-call 全部判据通过');
