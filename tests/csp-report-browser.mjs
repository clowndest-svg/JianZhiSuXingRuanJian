// C11 CSP 的真实回环：真 Chromium + 真 uvicorn，验证"报告模式确实在收违规"。
//
// 为什么不能只在 Python 里 POST 一份我自己造的 JSON：
// 浏览器出门的形状是 {"csp-report":{...}}，没有 blocked 布尔，只有 disposition
// 和 blocked-uri。按假形状写的解析照样全绿，真浏览器的报告却会被归成 unknown，
// 统计有数、一条没分类，转正门槛形同不存在。这条判据钉的就是那个真实形状。
//
// 口径：只报"发的是哪种头 / 违规有没有被真实归类 / 页面功能有没有受影响"。
// 正式策略何时能开由 tests/test_content_security.py 的门槛判据说，这里不替它背书。
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, '..');
const { chromium } = require('playwright');

const PORT = 18047;
const BASE = `http://127.0.0.1:${PORT}`;
const folder = fs.mkdtempSync(path.join(ROOT, '_audit_sandbox', 'csp-report-'));
const results = [];
let failed = 0;
const check = (name, ok, detail) => { results.push([name, !!ok, detail]); if (!ok) failed++; };

const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)],
  {
    cwd: ROOT,
    env: {
      ...process.env,
      QINGSU_DB_DIR: path.join(folder, 'db'), QINGSU_UPLOAD_DIR: path.join(folder, 'uploads'),
      QINGSU_KEY_DIR: path.join(folder, 'keys'),
      QINGSU_WEB_DIR: path.join(ROOT, 'app/src/main/assets'),
      // report-uri 用的是 SITE_BASE。不指回本机就把一条测试违规发到生产上去，
      // 而且这条判据也就验不到"本站收得到"这件事。
      QINGSU_SITE_BASE: BASE,
      QINGSU_CACHE_NAMESPACE: `qingsu-cspreport-${process.pid}`,
    },
    stdio: ['ignore', fs.openSync(path.join(folder, 'srv.log'), 'w'),
            fs.openSync(path.join(folder, 'srv.log'), 'a')],
  });

const wait = ms => new Promise(r => setTimeout(r, ms));
async function up() {
  for (let i = 0; i < 90; i++) {
    try { const r = await fetch(BASE + '/health/ready'); if (r.status < 500) return true; } catch (e) { }
    await wait(1000);
  }
  return false;
}

let browser;
try {
  if (!await up()) {
    console.log(fs.readFileSync(path.join(folder, 'srv.log'), 'utf8').slice(-1200));
    throw new Error('测试服务没起来');
  }
  browser = await chromium.launch({
    headless: true,
    ...(process.env.QINGSU_CHROME_PATH ? { executablePath: process.env.QINGSU_CHROME_PATH } : {}),
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  const reports = [];
  const pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 120)));
  page.on('request', r => {
    if (r.url().endsWith('/csp-report')) reports.push({ body: r.postData(), ctype: r.headers()['content-type'] });
  });

  const resp = await page.goto(BASE + '/');
  const headers = resp.headers();
  const reportOnly = headers['content-security-policy-report-only'] || '';
  const enforce = headers['content-security-policy'] || '';
  check('浏览器收到的是 Report-Only，不是正式策略', reportOnly && !enforce,
    { 报告模式: !!reportOnly, 正式策略: !!enforce });
  check('report-uri 指向本站绝对地址（APK 源不同，相对路径收不到）',
    new RegExp(`report-uri ${BASE.replace(/[.]/g, '\\.')}/csp-report`).test(reportOnly),
    (reportOnly.match(/report-uri [^;]+/) || [''])[0]);

  // 真违规：img-src 不含这个跨源图片，浏览器应当自己把报告送回来
  await page.evaluate(() => {
    const i = new Image();
    i.src = 'https://qs-csp-probe.invalid/x.png?secret=SHOULD_NOT_BE_KEPT';
  });
  const until = Date.now() + 12000;
  while (!reports.length && Date.now() < until) await wait(300);
  check('浏览器真的往 /csp-report 发了一条', reports.length >= 1,
    reports.length ? { 条数: reports.length, 类型: reports[0].ctype } : '12 秒内没有任何报告');

  let parsed = null;
  try { parsed = JSON.parse(reports[0].body); } catch (e) { }
  const inner = parsed && (parsed['csp-report'] || parsed);
  check('报告形状就是浏览器那种外层 csp-report 包裹', !!inner && !!inner['effective-directive'],
    inner ? Object.keys(inner).slice(0, 6) : 'body 解析失败');
  check('浏览器发的报告里没有 blocked 布尔（所以产品不能只认它）',
    !!inner && !('blocked' in inner) && !!inner.disposition,
    inner ? { disposition: inner.disposition, 有blocked: 'blocked' in inner } : '');

  const health = await page.evaluate(() => fetch('/health/ready').then(r => r.json()));
  const csp = health.csp || {};
  check('这条真违规被归到 img-src 名下，不是 unknown',
    csp.by_directive && csp.by_directive['img-src'],
    { by_directive: Object.keys(csp.by_directive || {}), unknown: (csp.by_directive || {}).unknown });
  check('报告模式下 disposition=report：算作"转正会被拦"，不算"已经拦了"',
    csp.blocked === 0 && (csp.by_directive['img-src'] || {}).would_block >= 1,
    { blocked: csp.blocked, would_block: (csp.by_directive['img-src'] || {}).would_block });
  check('违规来源没把查询串里的敏感值留下',
    !JSON.stringify(csp).includes('SHOULD_NOT_BE_KEPT'), JSON.stringify(csp.by_directive));
  check('报告仍然计入健康接口，运维看得见', csp.count >= 1, { count: csp.count, mode: csp.mode });

  // 报告模式不许影响页面功能：内联处理器依赖的全局函数还在，脚本报错为零
  const handlerAlive = await page.evaluate(() => typeof window.onDirectDownloadClick);
  check('报告模式下页面脚本照常执行（内联处理器要的全局函数在）',
    handlerAlive === 'function' && !pageErrors.length,
    { onDirectDownloadClick: handlerAlive, 页面报错: pageErrors.slice(0, 3) });

  // 没数出来的 HTML 不许被当成"0 处内联"从而放行转正
  check('转正门槛现在说的是实测数，不是猜的',
    csp.inline_handlers > 0 && csp.can_enforce === false && (csp.blockers || []).length >= 1,
    { inline_handlers: csp.inline_handlers, blockers: csp.blockers });
} catch (error) {
  check('整条判据跑完了', false, String(error).slice(0, 200));
} finally {
  if (browser) await browser.close();
  child.kill();
  try { fs.rmSync(folder, { recursive: true, force: true }); } catch (e) { }
}

for (const [name, ok, detail] of results) {
  console.log(`  ${ok ? '绿' : '红'} ${name}${detail === '' ? '' : ' -> ' + JSON.stringify(detail)}`);
}
console.log(`CSP 真实回环：${results.length - failed} 绿 / ${failed} 红`);
process.exit(failed ? 1 : 0);
