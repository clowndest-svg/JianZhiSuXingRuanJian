// C11 首屏与长任务的实测基线（真 Chromium + 真 uvicorn，弱网与 CPU 降速各跑一遍）。
//
// 方案对这一条的要求是"先测首屏与长任务，再分模块按需加载"，并且明确：
// LCP≤2.5s、CLS≤0.1、交互反馈≤200ms 是**拟定目标**，不能直接声称已经达到或违反。
// 所以这份判据分两种口径：
//   · 回归线（会判红）：实测体积/请求数/长任务数量比基线变差；
//   · 目标线（只报状态）：达到 / 未达到 / 未测到，达不到不等于失败。
// 数字全部现量，不抄文档。
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, '..');
const A = p => path.join(ROOT, 'app/src/main/assets', p);
const { chromium } = require('playwright');

const PORT = 18045;
const BASE = `http://127.0.0.1:${PORT}`;
const folder = fs.mkdtempSync(path.join(ROOT, '_audit_sandbox', 'firstscreen-'));

// 回归线＝本轮实测值留余量（本机 uvicorn 没挂 gzip 中间件，所以这里是**原始字节**，
// 线上经 nginx 压缩后另算——不要把这两个口径混成一个数）。要变好就往下改；要变差必须先在这里写清为什么。
const REGRESSION = {
  criticalBytes: 900_000,   // 首屏 HTML+JS+CSS 原始字节（实测 856,152）
  requests: 30,             // 首屏资源请求数（实测 26）
  longTasks: 6,             // 弱网 4× 降速下 3 秒内的长任务条数（实测 3）
  longestTaskMs: 1200,      // 单条长任务最长耗时（实测 483 ms）
};
// 拟定目标（方案原文），只报状态不判红。
const TARGETS = { lcpMs: 2500, cls: 0.1, interactionMs: 200 };

const results = [];
let failed = 0;
const check = (name, ok, detail) => { results.push([name, !!ok, detail]); if (!ok) failed++; };
const report = (name, detail) => { results.push([name, true, detail]); };

const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)],
  {
    cwd: ROOT, env: {
      ...process.env,
      QINGSU_DB_DIR: path.join(folder, 'db'), QINGSU_UPLOAD_DIR: path.join(folder, 'uploads'),
      QINGSU_KEY_DIR: path.join(folder, 'keys'), QINGSU_WEB_DIR: A(''),
      QINGSU_CACHE_NAMESPACE: `qingsu-firstscreen-${process.pid}`,
    },
  });

// 浏览器侧采集：LCP / CLS / 长任务 / 交互延迟。
// 资源计时缓冲默认 250 条会被模块请求填满，导致后面的请求看不见（本轮踩过），先放大。
const COLLECT = () => {
  try { performance.setResourceTimingBufferSize(5000); } catch (e) { }
  window.__fs = { lcp: null, cls: 0, long: [], inp: null };
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) window.__fs.lcp = e.startTime;
  }).observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) if (e.value) window.__fs.cls += e.value;
  }).observe({ type: 'layout-shift', buffered: true });
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) window.__fs.long.push({ dur: e.duration, start: e.startTime });
  }).observe({ type: 'longtask', buffered: true });
  // 交互反馈：点一个真实按钮到下一个帧之间的耗时
  new PerformanceObserver(l => {
    for (const e of l.getEntries()) if (e.duration) window.__fs.inp = Math.max(window.__fs.inp || 0, e.duration);
  }).observe({ type: 'event', durationThreshold: 16 });
};

async function waitUp() {
  for (let i = 0; i < 200; i++) {
    try { if ((await fetch(BASE + '/health')).ok) return true; } catch (e) { }
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error('首屏判据的服务没起来');
}

async function register() {
  const r = await fetch(BASE + '/api/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'fsuser', password: 'FirstScreen!123', age: 30, height: 170, weight_jin: 160, target_weight_jin: 140 }),
  });
  const body = await r.text();
  if (r.status !== 200) throw new Error('注册夹具失败 ' + body);
  return JSON.parse(body);
}

let browser;
try {
  await waitUp();
  const user = await register();
  browser = await chromium.launch({ headless: true, ...(process.env.QINGSU_CHROME_PATH ? { executablePath: process.env.QINGSU_CHROME_PATH } : {}) });

  // ── 一轮：普通网络 + 手机视口，量体积与请求数
  {
    const ctx = await browser.newContext({ viewport: { width: 393, height: 851 } });
    const page = await ctx.newPage();
    const seen = [];
    page.on('requestfinished', r => seen.push(r.url()));
    await page.addInitScript(u => {
      localStorage.setItem('QINGSU_AUTH_TOKEN', u.token);
      localStorage.setItem('QINGSU_AUTH_USER', JSON.stringify({ id: u.id, username: u.username }));
    }, user);
    await page.addInitScript(COLLECT);
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.getElementById('panel-dashboard') !== null);

    const res = await page.evaluate(() => performance.getEntriesByType('resource')
      .map(r => ({ name: r.name, kind: r.initiatorType, size: r.transferSize })));
    const critical = res.filter(r => /\.(js|css|html)(\?|$)/.test(r.name) || r.name.endsWith('/'));
    const criticalBytes = critical.reduce((a, b) => a + (b.size || 0), 0);
    const dupes = {};
    for (const url of seen) { const key = url.split('#')[0]; dupes[key] = (dupes[key] || 0) + 1; }
    const duplicated = Object.entries(dupes).filter(([, n]) => n > 1);
    // 图标那一类分开处理：同一个 png 被 <link rel=icon> 与 <img> 各要一次，
    // 是声明式引用的形状，不是代码里重复取数。方案这条要治的是 API/JS/CSS 的重复请求。
    const dataDupes = duplicated.filter(([u]) => !/\.(png|jpg|jpeg|webp|svg|ico)$/i.test(u));
    const imageDupes = duplicated.filter(([u]) => /\.(png|jpg|jpeg|webp|svg|ico)$/i.test(u));

    check('首屏关键资源字节没越过回归线', criticalBytes <= REGRESSION.criticalBytes,
      `实测 ${criticalBytes} B（原始，未压缩）/ 回归线 ${REGRESSION.criticalBytes} B`);
    check('首屏资源请求数没越过回归线', seen.length <= REGRESSION.requests,
      `实测 ${seen.length} 个 / 回归线 ${REGRESSION.requests}`);
    check('接口与脚本不被重复请求', dataDupes.length === 0,
      dataDupes.map(([u, n]) => `${n}× ${u.slice(-48)}`).join(' | '));
    report('图标类重复（不判红）', imageDupes.length ? imageDupes.map(([u, n]) => `${n}× ${u.slice(-32)}`).join(' | ') : '无');

    const lcp = await page.evaluate(() => window.__fs.lcp);
    const cls = await page.evaluate(() => Number(window.__fs.cls.toFixed(4)));
    report('拟定目标 LCP（不判红）', lcp === null ? '未测到' :
      `${Math.round(lcp)} ms ${lcp <= TARGETS.lcpMs ? '达到' : '未达到'}（目标 ≤${TARGETS.lcpMs}ms）`);
    report('拟定目标 CLS（不判红）', `${cls} ${cls <= TARGETS.cls ? '达到' : '未达到'}（目标 ≤${TARGETS.cls}）`);
    await ctx.close();
  }

  // ── 二轮：弱网 + 4× CPU 降速，量长任务与交互反馈
  {
    const ctx = await browser.newContext({ viewport: { width: 320, height: 640 } });
    const page = await ctx.newPage();
    await page.addInitScript(u => {
      localStorage.setItem('QINGSU_AUTH_TOKEN', u.token);
      localStorage.setItem('QINGSU_AUTH_USER', JSON.stringify({ id: u.id, username: u.username }));
    }, user);
    await page.addInitScript(COLLECT);
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false, latency: 150, downloadThroughput: 1_600_000 / 8, uploadThroughput: 750_000 / 8,
    });
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.getElementById('panel-dashboard') !== null, null, { timeout: 60000 });

    const long = await page.evaluate(() => window.__fs.long);
    const longest = long.reduce((a, b) => Math.max(a, b.dur), 0);
    check('弱网降速下长任务条数没越过回归线', long.length <= REGRESSION.longTasks,
      `实测 ${long.length} 条 / 回归线 ${REGRESSION.longTasks}`);
    check('弱网降速下单条长任务没越过回归线', longest <= REGRESSION.longestTaskMs,
      `最长 ${Math.round(longest)} ms / 回归线 ${REGRESSION.longestTaskMs} ms`);

    // 交互反馈：点首屏"今天三件事"里的记一餐入口，量事件处理耗时
    const before = await page.evaluate(() => window.__fs.inp);
    const clicked = await page.evaluate(() => {
      const el = document.getElementById('home-do-meal');
      if (!el) return false;
      el.click();
      return true;
    });
    await new Promise(r => setTimeout(r, 1200));
    const inp = await page.evaluate(() => window.__fs.inp);
    report('拟定目标 交互反馈（不判红）', !clicked ? '未测到（首屏入口不存在）' :
      (inp === null || inp === before ? '未测到（该次点击没有超过 16ms 的事件，属好消息）' :
        `${Math.round(inp)} ms ${inp <= TARGETS.interactionMs ? '达到' : '未达到'}（目标 ≤${TARGETS.interactionMs}ms）`));
    await ctx.close();
  }

  // ── 三件必须说清的事实：按需加载与 CSP 的当前状态
  {
    const html = fs.readFileSync(A('index.html'), 'utf8');
    const scripts = (html.match(/<script\b[^>]*>/g) || []);
    const deferred = scripts.filter(s => /defer|type="module"/.test(s)).length;
    report('脚本加载方式', `${scripts.length} 个 script 标签，其中 defer/module ${deferred} 个`);
    const inline = (html.match(/\son(click|input|change|submit|focus|blur|keydown|load|error)=/g) || []).length;
    report('正式 CSP 前提', `内联事件处理器 ${inline} 处：全部摘掉之前只能上 Report-Only`);
  }
} catch (e) {
  check('浏览器判据整段跑完（没有半路抛异常）', false, String(e).slice(0, 200));
} finally {
  if (browser) await browser.close();
  child.kill();
}

for (const [name, ok, detail] of results) {
  console.log(`  ${ok ? '绿' : '红'} ${name}${detail ? '  -> ' + detail : ''}`);
}
console.log(`=== C11 首屏实测：${results.length} 项，红 ${failed} ===`);
process.exit(failed ? 1 : 0);
