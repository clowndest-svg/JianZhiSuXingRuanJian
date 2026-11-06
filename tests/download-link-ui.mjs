// 下载弹窗的地址一致性：看到的、点下去的、复制到的、扫的，必须是同一条。
//
// 为什么不能只在模板里 grep：这四处分别由模板字面量、JS 拼串、复制函数和服务端二维码
// 生成，任何一处漏改都会"看着像修了"。本轮用户截图里那条 IP 就是模板写死后没人更新造成的。
// 所以这里用真 Chromium 打开真服务，把四个出口的实际值取出来互相比对。
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, '..');
const { chromium } = require('playwright');

const PORT = 18049;
const BASE = `http://127.0.0.1:${PORT}`;
const SITE = BASE;          // 这份服务的现役入口，SITE_BASE 指到它
const folder = fs.mkdtempSync(path.join(ROOT, '_audit_sandbox', 'dl-link-'));
const results = [];
let failed = 0;
const check = (name, ok, detail) => { results.push([name, !!ok, detail]); if (!ok) failed++; };

// 清单由发布流程算出来，这里拿仓内那份真值，只把它放进隔离的 WEB 目录
const web = path.join(folder, 'WEB');
fs.cpSync(path.join(ROOT, 'app/src/main/assets'), web, { recursive: true });
fs.copyFileSync(path.join(ROOT, 'app/src/main/web_version.json'), path.join(web, 'version.json'));
const manifestFile = JSON.parse(fs.readFileSync(path.join(web, 'version.json'), 'utf8'));

// Host 头要能改（fetch 会吞掉它），所以清单的三条分支用裸 http 打
function getManifest(headers) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path: '/version.json', headers },
      res => { let b = ''; res.on('data', d => b += d); res.on('end', () => resolve({ status: res.statusCode, body: b })); });
    req.on('error', reject);
    req.end();
  });
}

const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)],
  {
    cwd: ROOT,
    env: {
      ...process.env,
      QINGSU_DB_DIR: path.join(folder, 'db'), QINGSU_UPLOAD_DIR: path.join(folder, 'uploads'),
      QINGSU_KEY_DIR: path.join(folder, 'keys'), QINGSU_WEB_DIR: web,
      QINGSU_SITE_BASE: SITE,
      QINGSU_CACHE_NAMESPACE: `qingsu-dllink-${process.pid}`,
    },
    stdio: ['ignore', fs.openSync(path.join(folder, 'srv.log'), 'w'),
            fs.openSync(path.join(folder, 'srv.log'), 'a')],
  });

const wait = ms => new Promise(r => setTimeout(r, ms));

// 参照二维码用服务端同一套参数现生成（qrcode 只在 Python 侧有），
// 这样"编码了什么"是可比的，而不是靠人眼扫一下。
function refQrSvg(url) {
  return new Promise((resolve, reject) => {
    const py = process.env.QINGSU_TEST_PYTHON || 'python';
    const code = 'import io,qrcode,qrcode.image.svg as s;'
      + 'b=io.BytesIO();qrcode.make(' + JSON.stringify(url) + ',image_factory=s.SvgPathImage,box_size=8,border=4).save(b);'
      + 'import sys;sys.stdout.buffer.write(b.getvalue())';
    const p = spawn(py, ['-c', code], { cwd: ROOT });
    const chunks = [];
    p.stdout.on('data', d => chunks.push(d));
    p.on('error', reject);
    p.on('close', c => c === 0 ? resolve(Buffer.concat(chunks).toString()) : reject(Error('py ' + c)));
  });
}

let browser;
try {
  let up = false;
  for (let i = 0; i < 90; i++) {
    try { const r = await fetch(BASE + '/health/ready'); if (r.status < 500) { up = true; break; } } catch (e) { }
    await wait(1000);
  }
  if (!up) throw new Error(fs.readFileSync(path.join(folder, 'srv.log'), 'utf8').slice(-800));

  // 清单是这份地址的唯一真源：服务端按 SITE_BASE 现算，不看文件里写的是什么
  const modern = JSON.parse((await getManifest({ 'X-App-Build': String(manifestFile.version_code) })).body);
  check('version.json 的 apk_url 就是本站现算的入口地址',
    modern.apk_url === SITE + '/qingsu.apk', modern.apk_url);
  const legacy = JSON.parse((await getManifest({
    'X-App-Build': '44', Host: '124.220.54.64' })).body);
  check('build<45 且从 IP 入口取清单时仍回落 IP（旧客户端不因此装不上）',
    legacy.apk_url === 'https://124.220.54.64/qingsu.apk', legacy.apk_url);
  const modernViaIpHost = JSON.parse((await getManifest({
    'X-App-Build': String(manifestFile.version_code), Host: '124.220.54.64' })).body);
  check('新客户端即使从 IP 入口拿清单，也照样给现役入口地址',
    modernViaIpHost.apk_url === SITE + '/qingsu.apk', modernViaIpHost.apk_url);

  browser = await chromium.launch({
    headless: true,
    ...(process.env.QINGSU_CHROME_PATH ? { executablePath: process.env.QINGSU_CHROME_PATH } : {}),
  });
  const page = await (await browser.newContext()).newPage();
  await page.goto(BASE + '/', { waitUntil: 'load' });

  // 模板里不许再留任何绝对下载地址：JS 没跑之前屏幕上不能出现一个可能过期的地址
  const rawHtml = await (await fetch(BASE + '/')).text();
  check('首页模板里没有写死的绝对 APK 地址',
    !/https?:\/\/[^\s<>]+\/qingsu\.apk/.test(rawHtml),
    (rawHtml.match(/https?:\/\/[^\s<>]+\/qingsu\.apk/g) || []).slice(0, 2));

  await page.evaluate(() => {
    window.__copied = null;
    const real = navigator.clipboard && navigator.clipboard.writeText;
    navigator.clipboard.writeText = t => {
      window.__copied = String(t);
      return real ? real.call(navigator.clipboard, t) : Promise.resolve();
    };
    window.__toasts = [];
    const old = window.callNativeToast;
    window.callNativeToast = m => { window.__toasts.push(String(m)); if (old) return old(m); };
  });
  await page.evaluate(() => openDownloadModal());
  await page.waitForFunction(() => {
    const l = document.getElementById('apk-direct-link');
    return l && /v=[0-9a-f]{6,}/.test(l.href);
  }, null, { timeout: 25000 });

  const view = await page.evaluate(() => {
    const l = document.getElementById('apk-direct-link');
    const qr = document.getElementById('download-qr-img');
    return {
      text: l.textContent.trim(), href: l.href, download: l.getAttribute('download'),
      qrSrc: qr ? qr.src : null, qrLoaded: qr ? qr.naturalWidth > 0 : false,
      ver: (document.getElementById('apk-ver-line') || {}).textContent,
    };
  });
  const expected = SITE + '/qingsu.apk';
  check('屏幕上写的地址 = 点下去的地址', view.text === view.href, { 写的: view.text, 点的: view.href });
  check('两者都来自 version.json 的 apk_url（含指纹查询串）',
    view.href.startsWith(expected + '?v='), view.href);
  check('下载文件名带上真实版本', !!view.download && view.download.includes(manifestFile.version_name),
    view.download);
  check('版本行也是清单里的真值，不是模板字面量',
    view.ver === 'v' + manifestFile.version_name + ' · build ' + manifestFile.version_code, view.ver);

  await page.evaluate(() => copyApkDownloadUrl());
  await page.waitForFunction(() => window.__copied !== null, null, { timeout: 8000 });
  const copied = await page.evaluate(() => ({ url: window.__copied, toasts: window.__toasts.slice(-1) }));
  check('复制到的就是屏幕上那一条', copied.url === view.text, { 复制到: copied.url });
  check('复制结果当场说给用户', /已复制/.test(copied.toasts.join('')), copied.toasts);

  check('二维码由服务端现生成（src 带清单指纹，不是模板里那张死的）',
    !!view.qrSrc && view.qrSrc.startsWith(BASE + '/qr.svg?v=') && view.qrLoaded, view.qrSrc);

  // 服务端那份必须编码"这台服务器的 SITE_BASE"，而不是回落到包里那张死的图。
  // 两者在这套环境里必然不同（SITE 是 127.0.0.1，包内那张是现役域名），所以这条能真分辨。
  const servedQr = await (await fetch(BASE + '/qr.svg')).text();
  const packagedQr = fs.readFileSync(path.join(ROOT, 'app/src/main/assets/qr.svg'), 'utf8');
  const mods = t => (t.match(/[0-9.]{2,}/g) || []).slice(0, 80).join(',');
  const refQr = await refQrSvg(SITE + '/qingsu.apk');
  check('服务端二维码编码的就是本站入口地址', mods(servedQr) === mods(refQr),
    { 本站生成: mods(refQr).slice(0, 40), 服务端返回: mods(servedQr).slice(0, 40) });
  check('它不是包内那张静态图（静态图只作离线兜底）', mods(servedQr) !== mods(packagedQr),
    mods(servedQr) === mods(packagedQr) ? '两张一模一样' : '不同');
  check('服务端二维码取到了 SVG', servedQr.includes('<svg'), servedQr.slice(0, 40));
} catch (error) {
  check('整条判据跑完了', false, String(error).slice(0, 220));
} finally {
  if (browser) await browser.close();
  child.kill();
  try { fs.rmSync(folder, { recursive: true, force: true }); } catch (e) { }
}

for (const [name, ok, detail] of results) {
  console.log(`  ${ok ? '绿' : '红'} ${name} -> ${JSON.stringify(detail)}`);
}
console.log(`下载地址一致性：${results.length - failed} 绿 / ${failed} 红`);
process.exit(failed ? 1 : 0);
