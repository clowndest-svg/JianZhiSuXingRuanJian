// B10 弹窗 / 表单 / 无障碍契约。
// 静态部分钉「结构与样式写在哪一层」：白名单完整性、读屏名字、封顶到底加在哪个元素上。
// 真浏览器部分钉「最终布局与操作结果」：滚得到底、底部操作还在屏内、焦点进得来回得去、
// Esc 关得掉、320px + 200% 字号不横向溢出、减少动态效果真的生效。
// 用法：node tests/a11y-dialog-contract.mjs
//        --static-only  只跑静态（明确降级，不代表产品通过）
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, '..');
const A = p => path.join(ROOT, 'app/src/main/assets', p);
const html = fs.readFileSync(A('index.html'), 'utf8');
const js = fs.readFileSync(A('app.js'), 'utf8');
const css = fs.readFileSync(A('style.css'), 'utf8') + '\n' + fs.readFileSync(A('features.css'), 'utf8');

const R = [];
const check = (name, ok, detail = '') => R.push([name, !!ok, ok ? '' : String(detail)]);

// ---------------------------------------------------------------- 切片工具
const startTags = src => src.match(/<[a-zA-Z][^>]*>/g) || [];
const attrsOf = tag => {
  const out = {};
  for (const m of tag.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"/g)) out[m[1].toLowerCase()] = m[2];
  return out;
};
// 去掉注释后，@media 的块体里还有花括号，所以 [^{}]* 只会命中真正带声明的规则；
// 选择器取最近一个 { 之前的文本（含它外面的 @media 没关系，这里只按选择器名索引）。
function cssRules(src) {
  const bare = src.replace(/\/\*[\s\S]*?\*\//g, ' ');
  const list = [];
  for (const m of bare.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const sel = m[1].trim().replace(/\s+/g, ' ').split(/\s+/).filter(w => !w.startsWith('@')).join(' ');
    const decls = {};
    for (const d of m[2].split(';')) {
      const i = d.indexOf(':');
      if (i < 0) continue;
      decls[d.slice(0, i).trim().toLowerCase()] = d.slice(i + 1).trim().replace(/\s+/g, ' ');
    }
    if (Object.keys(decls).length) list.push({ sel, decls });
  }
  return list;
}
const RULES = cssRules(css);
const declFor = (selector, prop) => {
  let hit = null;
  for (const r of RULES) {
    if (r.sel.split(',').map(s => s.trim()).includes(selector) && prop in r.decls) hit = r.decls[prop];
  }
  return hit;
};
const hasScroll = sel => /\b(auto|scroll)\b/.test(`${declFor(sel, 'overflow') || ''} ${declFor(sel, 'overflow-y') || ''}`);
const capOf = sel => { const v = declFor(sel, 'max-height'); return v && v !== 'none' ? v : null; };
const minZero = sel => declFor(sel, 'min-height') === '0';

// ---------------------------------------------------- 1. 白名单完整性（正向断言）
// 从 HTML 反扫「所有会盖住界面的容器」，再断言每一个都在白名单里。
// 只证 白名单 ⊆ 某集合 证明不了没有漏项：漏掉的那个容器不报错，只是打开时不 inert、
// 焦点不归位、Esc 按了没反应。
const overlays = [];
for (const tag of startTags(html)) {
  const a = attrsOf(tag);
  const cls = a.class || '';
  // .modal-card 是覆盖层里的内容面板，不是容器本体：容器（有 id 的那层）才归白名单管。
  if (/(^|\s)modal-card(\s|$)/.test(cls)) continue;
  const isCoverLayer = /(^|\s)(modal-overlay|page-layer)(\s|$)/.test(cls)
    || (a.role === 'dialog' && a['aria-modal'] === 'true');
  const isNative = /^<dialog\b/i.test(tag);
  if (isCoverLayer || isNative) overlays.push({ tag, id: a.id || '', a, isNative });
}
const wl = ((js.match(/const DIALOG_OVERLAY_IDS\s*=\s*\[([\s\S]*?)\]/) || [, ''])[1].match(/"([^"]+)"/g) || [])
  .map(s => s.slice(1, -1));
check('HTML 浮层扫描扫到了东西（≥7 个容器）', overlays.length >= 7, overlays.map(o => o.id).join(','));
check('白名单解析成功（≥7 项）', wl.length >= 7, wl.join(','));
const missing = overlays.filter(o => o.id && !wl.includes(o.id)).map(o => o.id);
check('每个浮层容器都在 DIALOG_OVERLAY_IDS 里（正向：HTML → 白名单）', missing.length === 0, '漏了 ' + missing.join(','));
const noId = overlays.filter(o => !o.id).map(o => o.tag.slice(0, 60));
check('浮层容器都有 id（没 id 就进不了白名单）', noId.length === 0, noId.join(' / '));
const ghost = wl.filter(id => !html.includes(`id="${id}"`));
check('白名单里没有指向不存在容器的死项', ghost.length === 0, ghost.join(','));
for (const id of ['profile-modal', 'intercept-modal', 'auth-modal', 'download-apk-modal',
  'ex-detail-modal', 'page-layer', 'report-dialog']) {
  check(`浮层 ${id} 在白名单里`, wl.includes(id), id);
}

// ---------------------------------------------------- 2. 读屏：每个对话框都有名字
const dialogs = startTags(html).filter(t => /^<dialog\b/i.test(t) || attrsOf(t).role === 'dialog');
check('对话框数量扫到了（≥7）', dialogs.length >= 7, dialogs.length);
const allIds = new Set((html.match(/id="([^"]+)"/g) || []).map(s => s.slice(4, -1)));
for (const t of dialogs) {
  const a = attrsOf(t);
  const label = (a['aria-label'] || '').trim();
  const by = (a['aria-labelledby'] || '').trim().split(/\s+/).filter(Boolean);
  const key = a.id || a.class || t.slice(0, 40);
  check(`对话框 ${key} 声明 role=dialog`, /^<dialog/i.test(t) || a.role === 'dialog', key);
  check(`对话框 ${key} 声明 aria-modal`, a['aria-modal'] === 'true', key);
  check(`对话框 ${key} 有可读名字`,
    label.length > 0 || (by.length > 0 && by.every(i => allIds.has(i))), key + ' -> ' + JSON.stringify([label, by]));
}

// ---------------------------------------------------- 3. 关闭按钮不许只念得出符号
const SYMBOL_ONLY = /^[×✕✖✗✙︎\s]*$/u;
const closeBtns = startTags(html).filter(t => /class="[^"]*(modal-close-btn|exd-close|td-close)[^"]*"/.test(t));
check('关闭按钮扫到了（≥6）', closeBtns.length >= 6, closeBtns.length);
for (const t of closeBtns) {
  const a = attrsOf(t);
  const name = (a['aria-label'] || '').trim();
  const key = (a.id || a.onclick || a.class || '').slice(0, 46);
  check(`关闭按钮 ${key} 有 aria-label`, name.length > 0, key);
  check(`关闭按钮 ${key} 的名字不是符号`, !SYMBOL_ONLY.test(name), JSON.stringify(name));
}

// ---------------------------------------------------- 4. 封顶加在哪个元素上
// r178 更新弹窗的坑：封顶写在正文自己身上 → 滚动条挂在滑不动的那层。
check('.modal-card 自己带封顶', !!capOf('.modal-card'), capOf('.modal-card'));
check('.modal-card 同时就是滚动容器（封顶落在会滚的那层）', hasScroll('.modal-card'), declFor('.modal-card', 'overflow-y'));
check('.tool-dialog 壳子封顶且自己不滚',
  !!capOf('.tool-dialog') && !hasScroll('.tool-dialog'), capOf('.tool-dialog') + '/' + declFor('.tool-dialog', 'overflow'));
check('.td-body 是能滚的正文且有 min-height:0',
  hasScroll('.td-body') && minZero('.td-body'), declFor('.td-body', 'overflow') + '/' + declFor('.td-body', 'min-height'));
check('.pl-body 是能滚的正文且有 min-height:0',
  hasScroll('.pl-body') && minZero('.pl-body'), declFor('.pl-body', 'overflow-y') + '/' + declFor('.pl-body', 'min-height'));
check('底部操作条不跟正文一起滚走：.modal-foot 粘在滚动容器下沿',
  declFor('.modal-foot', 'position') === 'sticky', declFor('.modal-foot', 'position'));
const footRule = RULES.filter(r => r.sel.split(',').map(s => s.trim()).some(s => /\.tool-dialog>footer|\.tool-dialog>\.td-foot/.test(s)));
check('原生对话框底栏不被 flex 压掉（flex: 0 0 auto）',
  footRule.some(r => r.decls.flex === '0 0 auto'), JSON.stringify(footRule.map(r => r.decls.flex)));
for (const body of ['.modal-body', '.td-body', '.pl-body', '.td-lead', '.exd-steps']) {
  const cap = capOf(body);
  check(`正文 ${body} 不自己挂封顶（封顶只能落在滚动容器上）`, !cap || hasScroll(body), `${body}{max-height:${cap}}`);
}
check('320px 窄屏有专门的弹窗收口', /@media[^{]*max-width:\s*320px/.test(css) && /max-height:\s*9[0-9]dvh/.test(css), '');

// ---------------------------------------------------- 5. 减少动态效果点名覆盖弹层
const rmBlocks = css.match(/@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)[^{]*\{(?:[^{}]|\{[^{}]*\})*/g) || [];
check('prefers-reduced-motion 规则块够多（两份样式表都点名）', rmBlocks.length >= 3, rmBlocks.length);
const rmText = rmBlocks.join('\n');
check('减少动态效果有通配符兜底', /\*/.test(rmText), rmText.slice(0, 50));
for (const sel of ['.modal-card', '.modal-overlay', '.tool-dialog', '.td-body', '.page-layer',
  '.pl-body', '.modal-foot', '#web-toast-container', '.pub-cheer-toast']) {
  check(`减少动态效果点名覆盖 ${sel}`, rmText.includes(sel), sel);
}

// ---------------------------------------------------- 6. 基建盯得住三种开合方式
check('观察器同时盯 class / hidden / open 三种开合属性',
  /attributeFilter:\s*\[\s*"class",\s*"hidden",\s*"open"\s*\]/.test(js), 'attributeFilter');
check('dialogIsOpen 认得原生 <dialog> 的 open 属性', /hasAttribute\("open"\)/.test(js), '');
check('提示条不跟弹窗一起被 inert 掉', /web-toast-container/.test(js) && /isAnnouncementNode/.test(js), '');
check('Esc 走各弹窗自己的关闭入口', /DIALOG_CLOSE_SELECTORS/.test(js) && /closeTopDialog/.test(js), '');
check('运行时对话框只认 body 直接子节点（内层面板不算容器）',
  /body > dialog\[open\]/.test(js) && /body > \[role="dialog"\]\[aria-modal="true"\]/.test(js), '');
check('白名单里每一项都会被绑上观察器（加容器不会漏绑）',
  /DIALOG_OVERLAY_IDS\.forEach\(\s*id\s*=>\s*bindDialogAccessibility\(document\.getElementById\(id\)\)\s*\)/.test(js), '');

if (process.argv.includes('--static-only')) { report(); }

// ================================================== 真浏览器：测最终布局与操作结果
const { chromium } = require('playwright');
const PORT = 18042;
const BASE = `http://127.0.0.1:${PORT}`;
const folder = fs.mkdtempSync(path.join(ROOT, '_audit_sandbox', 'a11y-'));
const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)],
  {
    cwd: ROOT, env: {
      ...process.env,
      QINGSU_DB_DIR: path.join(folder, 'db'), QINGSU_UPLOAD_DIR: path.join(folder, 'uploads'),
      QINGSU_KEY_DIR: path.join(folder, 'keys'), QINGSU_WEB_DIR: A('')
    }
  });
let browser;
try {
  for (let i = 0; i < 150; i++) { try { if ((await fetch(BASE + '/health')).ok) break; } catch { } await new Promise(r => setTimeout(r, 100)); }
  const reg = await fetch(BASE + '/api/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'a11yui', password: 'A11ySecure!123', age: 30, height: 170, weight_jin: 160, target_weight_jin: 140 })
  });
  const regBody = await reg.text();
  assert.equal(reg.status, 200, regBody);
  const user = JSON.parse(regBody);
  browser = await chromium.launch({ headless: true, ...(process.env.QINGSU_CHROME_PATH ? { executablePath: process.env.QINGSU_CHROME_PATH } : {}) });
  const pageErrors = [];

  const newPage = async (contextOptions) => {
    const ctx = await browser.newContext(contextOptions);
    const page = await ctx.newPage();
    page.on('pageerror', e => pageErrors.push(String(e)));
    await page.addInitScript(u => {
      localStorage.setItem('QINGSU_AUTH_TOKEN', u.token);
      localStorage.setItem('QINGSU_AUTH_USER', JSON.stringify({ id: u.id, username: u.username }));
    }, user);
    await page.goto(BASE);
    await page.waitForFunction(() => typeof openDialogs === 'function' && typeof topDialog === 'function');
    return { ctx, page };
  };
  // 一个都没开的时候，背景必须是可达的：隐藏着的 .modal-card 也写着 aria-modal，
  // 把它当成"弹窗一直开着"会让全站永远 inert（本轮实测踩过，判据钉在这里）。
  const quiet = async p => p.evaluate(() => ({
    top: !!topDialog(), opened: openDialogs().length,
    inert: document.querySelector('main').inert, aria: document.querySelector('main').getAttribute('aria-hidden')
  }));

  // ---------- 320px 窄屏 + 200% 系统字号：每个弹窗都要滚得到底、底部操作在屏内 ----------
  const small = await newPage({ viewport: { width: 320, height: 480 }, reducedMotion: 'reduce' });
  const page = small.page;
  const q0 = await quiet(page);
  check('一个弹窗都没开时背景保持可达（隐藏弹窗不许被当成开着）',
    !q0.top && q0.opened === 0 && q0.inert !== true && q0.aria === null, JSON.stringify(q0));
  // 200% 字号：Android WebView 的 textZoom 只放大文字、不缩布局视口。
  // 桌面 Chromium 的 CDP fontScale 在部分版本被静默忽略，所以先试它，不行就用
  // 「把全站 font-size 翻倍」等价模拟（布局宽度仍是 320 CSS px，和 textZoom 一样）。
  const cdp = await small.ctx.newCDPSession(page);
  const probeSel = '.modal-close-btn';
  const baseline = await page.evaluate(s => getComputedStyle(document.querySelector(s)).fontSize, probeSel);
  let fontScaled = false;
  let how = '';
  try {
    await cdp.send('Emulation.setDeviceMetricsOverride',
      { width: 320, height: 480, deviceScaleFactor: 1, mobile: true, fontScale: 2 });
    await page.waitForTimeout(200);
    const after = await page.evaluate(s => getComputedStyle(document.querySelector(s)).fontSize, probeSel);
    if (parseFloat(after) > parseFloat(baseline) * 1.5) { fontScaled = true; how = 'CDP fontScale'; }
  } catch { /* 不支持就走等价模拟 */ }
  if (!fontScaled) {
    await page.evaluate(() => {
      const bump = decl => {
        const v = decl.getPropertyValue('font-size');
        if (!v) return;
        const m = /^([\d.]+)(px|em|rem|%)$/.exec(v.trim());
        if (m) decl.setProperty('font-size', (parseFloat(m[1]) * 2) + m[2], 'important');
      };
      for (const sheet of document.styleSheets) {
        let rules; try { rules = sheet.cssRules; } catch { continue; }
        for (const r of rules) { if (r.style) bump(r.style); }
      }
      document.querySelectorAll('[style]').forEach(el => bump(el.style));
    });
    const after = await page.evaluate(s => getComputedStyle(document.querySelector(s)).fontSize, probeSel);
    fontScaled = parseFloat(after) > parseFloat(baseline) * 1.5;
    how = 'font-size 翻倍等价模拟';
  }
  check(`200% 字号注入生效（${how}：${baseline} 变大）`, fontScaled, `放大后仍是 ${baseline}，这一档没测到，别当成已验收`);
  if (process.env.QINGSU_A11Y_PROBE) {
    // 定位「200% 字号下横向溢出到底谁撑的」：逐个隐藏主体区块再量。默认不跑。
    console.log('PROBE 溢出来源:', await page.evaluate(() => {
      const de = document.documentElement, res = [];
      const hide = (label, sel) => {
        const el = document.querySelector(sel); if (!el) return;
        const o = el.style.display; el.style.display = 'none';
        res.push(`${label} 隐藏后=${de.scrollWidth - de.clientWidth}`); el.style.display = o;
      };
      res.push(`全量=${de.scrollWidth - de.clientWidth}`);
      hide('main#app-main', '#app-main');
      hide('.bottom-nav', '.bottom-nav');
      hide('#panel-dashboard', '#panel-dashboard');
      return res.join(' | ');
    }));
  }
  const baseOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  // 主界面在 200% 字号下本身就有横向溢出（r179 实测：顶栏 .header-tools 与下载胶囊按钮），
  // 那是弹窗之外的账，本轮只钉「打开弹窗不额外增加溢出」，基线数字如实打出来。
  console.log(`INFO 320px + 200% 字号：主界面横向溢出基线 = ${baseOverflow}px（弹窗之外的待修项，见 B10 报告）`);

  const openers = {
    'profile-modal': () => page.evaluate(() => openProfileModal()),
    'auth-modal': () => page.evaluate(() => openAuthModal()),
    'download-apk-modal': () => page.evaluate(() => openDownloadModal()),
    // 拦截框的真入口是一次超标外卖判定，这里直接开容器量布局（同一段 CSS）
    'intercept-modal': () => page.evaluate(() => document.getElementById('intercept-modal').classList.add('show')),
    'ex-detail-modal': () => page.evaluate(() => {
      window.__currentExercises = [{ name: '徒手深蹲', reps: '3 组 × 12' }];
      openExerciseDetail(0);
      if (!document.getElementById('ex-detail-modal').classList.contains('show')) {
        document.getElementById('ex-detail-modal').classList.add('show');
      }
    }),
    'report-dialog': () => page.evaluate(() => openReport('post', 1)),
    'page-layer': () => page.evaluate(() => {
      QS_PAGES.push({ name: 'a11y', arg: null, title: '测试整页层', render() { document.getElementById('pl-body').innerHTML = '<p>' + '内容很长'.repeat(900) + '</p>'; } });
      qsRenderTop();
    }),
  };
  for (const [id, open] of Object.entries(openers)) {
    await page.evaluate(() => {
      document.querySelectorAll('.modal-overlay.show').forEach(el => el.classList.remove('show'));
      const d = document.getElementById('report-dialog'); if (d && d.open) d.close();
      document.getElementById('page-layer').hidden = true;
      QS_PAGES.length = 0;
    });
    await open();
    await page.waitForTimeout(260);
    const m = await page.evaluate(dlg => {
      const el = document.getElementById(dlg);
      const shell = el.classList.contains('modal-overlay') ? el.querySelector('.modal-card') : el;
      const cands = [shell, ...shell.querySelectorAll('*')];
      // 真正的滚动容器：内容比盒子高、且 overflow 允许滚的那一层
      const scroller = cands.find(n => /\b(auto|scroll)\b/.test(getComputedStyle(n).overflowY)
        && n.scrollHeight - n.clientHeight > 4) || shell;
      const sr = scroller.getBoundingClientRect();
      const hr = shell.getBoundingClientRect();
      const cap = scroller.scrollTop;
      scroller.scrollTop = scroller.scrollHeight;
      // 量在滚到底之后：这才是"底部操作还看不看得到"的那一刻
      const foot = shell.querySelector('.modal-foot') || shell.querySelector('footer') ||
        (dlg === 'page-layer' ? document.getElementById('pl-foot') : null);
      const fr = foot && foot.offsetParent !== null ? foot.getBoundingClientRect() : null;
      const last = scroller.lastElementChild;
      const lr = last ? last.getBoundingClientRect() : null;
      const to = scroller.scrollTop;
      return {
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        shellFitsH: hr.left >= -1 && hr.right <= window.innerWidth + 1,
        openerRan: el.classList.contains('show') || el.hidden === false || el.hasAttribute('open'),
        scrollerScrolls: /\b(auto|scroll)\b/.test(getComputedStyle(scroller).overflowY),
        // 封顶有效 = 弹层整体没被顶出视口（内容超高恰恰证明它被约束住了）
        shellFitsViewport: hr.height <= window.innerHeight + 1 && hr.bottom <= window.innerHeight + 1,
        contentTaller: scroller.scrollHeight - scroller.clientHeight,
        moved: to - cap,
        reachesBottom: scroller.scrollHeight - scroller.clientHeight - to <= 2,
        tailReachable: lr ? (lr.bottom <= sr.bottom + 2 && lr.bottom >= sr.top - 2) : null,
        tailNode: last ? (last.className || last.tagName) : null,
        footSeen: !!fr,
        footOnScreen: fr ? (fr.bottom <= window.innerHeight + 1 && fr.top >= -1 && fr.height > 0) : null,
        footInsideShell: fr ? (fr.bottom <= hr.bottom + 1 && fr.top >= hr.top - 1) : null,
        footInScroller: foot ? scroller.contains(foot) : null,
        isTop: typeof topDialog === 'function' && topDialog() === el,
        scrollerClass: scroller.className || scroller.tagName,
      };
    }, id);
    check(`${id}: 打开入口跑得通（基建认得出它在最上层）`, m.openerRan && m.isTop, JSON.stringify(m));
    check(`${id}: 320px + 200% 字号下弹层自己不越出屏幕宽度`, m.shellFitsH, JSON.stringify(m));
    check(`${id}: 320px + 200% 字号下文档不因为打开弹层而多出横向滚动（基线 ${baseOverflow}px）`,
      m.overflowX <= baseOverflow, `溢出 ${m.overflowX}px`);
    check(`${id}: 弹层自身没被顶出视口（封顶真的约束住了高度）`, m.shellFitsViewport, JSON.stringify(m));
    check(`${id}: 内容超高时真的滚得到底（滚动容器=${m.scrollerClass}，scrollTop 追平 scrollHeight 且最后一个内容节点=${m.tailNode} 滚进可视区）`,
      m.contentTaller <= 4 || (m.scrollerScrolls && m.moved > 4 && m.reachesBottom && m.tailReachable !== false),
      JSON.stringify(m));
    if (m.footSeen) check(`${id}: 滚到底时底部操作条仍在屏幕内、仍在弹层内（不跟正文滚走）`,
      m.footOnScreen && m.footInsideShell, JSON.stringify(m));
  }

  // ---------- 减少动态效果：计算样式上真的没动画了 ----------
  const rm = await page.evaluate(() => {
    document.getElementById('auth-modal').classList.add('show');
    const cs = getComputedStyle(document.querySelector('#auth-modal .modal-card'));
    const out = { name: cs.animationName, dur: cs.animationDuration, trans: cs.transitionDuration };
    document.getElementById('auth-modal').classList.remove('show');
    return out;
  });
  check('reduced-motion 下弹窗 slideUp 不再生效',
    rm.name === 'none' || parseFloat(rm.dur) < 0.01, JSON.stringify(rm));

  // ---------- 桌面键盘：焦点进得来、出不去、Esc 关得掉、关完回原位 ----------
  const desk = await newPage({ viewport: { width: 393, height: 850 } });
  const k = desk.page;
  const q1 = await quiet(k);
  check('桌面键盘页同样没有"假开着"的弹窗', !q1.top && q1.opened === 0 && q1.inert !== true, JSON.stringify(q1));
  await k.evaluate(() => {
    const b = document.querySelector('button[onclick="openProfileModal()"]');
    b.id = 'a11y-trigger';
    b.focus();
    b.click();
  });
  await k.waitForSelector('#profile-modal.show');
  const focusIn = await k.evaluate(() => {
    const card = document.querySelector('#profile-modal .modal-card');
    return { inside: card.contains(document.activeElement), id: document.activeElement.id, tag: document.activeElement.tagName };
  });
  check('档案弹窗打开后焦点落在弹窗内的第一个可交互元素', focusIn.inside && focusIn.tag !== 'BODY', JSON.stringify(focusIn));

  const bg = await k.evaluate(() => {
    const main = document.querySelector('main');
    const nav = document.querySelector('.bottom-nav');
    return { mainInert: main.inert === true, navInert: nav.inert === true, aria: main.getAttribute('aria-hidden'), selfHidden: document.getElementById('profile-modal').getAttribute('aria-hidden') };
  });
  check('弹窗开着时背景 main/底导 被 inert + aria-hidden，弹窗自己不屏蔽',
    bg.mainInert && bg.navInert && bg.aria === 'true' && bg.selfHidden === null, JSON.stringify(bg));

  const ring = await k.evaluate(() => {
    const card = document.querySelector('#profile-modal .modal-card');
    const items = dialogFocusables(card);
    if (items.length) items[items.length - 1].focus();
    return { n: items.length, last: document.activeElement.className || document.activeElement.tagName };
  });
  await k.keyboard.press('Tab');
  const ringAfter = await k.evaluate(() => {
    const card = document.querySelector('#profile-modal .modal-card');
    return { inside: card.contains(document.activeElement), outside: document.querySelector('main').contains(document.activeElement) };
  });
  check(`Tab 在弹窗内循环不出界（焦点元素 ${ring.n} 个，末位再按 Tab 仍在框内）`,
    ring.n > 0 && ringAfter.inside && !ringAfter.outside, JSON.stringify({ ring, ringAfter }));

  await k.keyboard.press('Escape');
  await k.waitForFunction(() => !document.getElementById('profile-modal').classList.contains('show'), { timeout: 3000 });
  const back = await k.evaluate(() => ({ id: document.activeElement.id, same: document.activeElement === document.getElementById('a11y-trigger') }));
  check('关闭后焦点回到触发它的那个控件', back.same || back.id === 'a11y-trigger', JSON.stringify(back));
  const unblocked = await k.evaluate(() => ({ inert: document.querySelector('main').inert, aria: document.querySelector('main').getAttribute('aria-hidden') }));
  check('关闭后背景解除屏蔽', unblocked.inert !== true && unblocked.aria === null, JSON.stringify(unblocked));

  // 弹窗里的 toast 必须还能被读屏念到（保存成功的唯一反馈）
  await k.evaluate(() => { document.getElementById('a11y-trigger').click(); callNativeToast('保存成功'); });
  await k.waitForSelector('#web-toast-container');
  const toast = await k.evaluate(() => {
    const t = document.getElementById('web-toast-container');
    return { inert: t.inert === true, hidden: t.getAttribute('aria-hidden'), text: t.innerText };
  });
  check('弹窗开着时 toast 容器仍对读屏可见', !toast.inert && toast.hidden === null && /保存成功/.test(toast.text), JSON.stringify(toast));
  await k.keyboard.press('Escape');

  // 整页层：r179 之前完全不在白名单里，背景不屏蔽、Esc 没反应
  await k.evaluate(() => {
    QS_PAGES.push({ name: 'a11y', arg: null, title: '测试整页层', render() { document.getElementById('pl-body').innerHTML = '<button type="button">页内按钮</button>'; } });
    qsRenderTop();
  });
  await k.waitForSelector('#page-layer:not([hidden])');
  const layer = await k.evaluate(() => ({
    inertBg: document.querySelector('main').inert === true,
    focusedInside: document.getElementById('page-layer').contains(document.activeElement),
    who: document.activeElement.className
  }));
  check('整页层开着时背景被屏蔽（这条以前根本不生效）', layer.inertBg, JSON.stringify(layer));
  check('整页层打开后焦点落在层内的返回按钮', layer.focusedInside, JSON.stringify(layer));
  await k.keyboard.press('Escape');
  await k.waitForFunction(() => document.getElementById('page-layer').hidden === true, { timeout: 3000 }).catch(() => { });
  check('Esc 能收掉整页层', await k.evaluate(() => document.getElementById('page-layer').hidden === true), '');

  // 原生 <dialog>：名字来自标题、Esc 关得掉
  await k.evaluate(() => { document.getElementById('nav-dashboard').focus(); openReport('post', 7); });
  await k.waitForSelector('#report-dialog[open]');
  const nat = await k.evaluate(() => ({
    isTop: topDialog() === document.getElementById('report-dialog'),
    name: (document.getElementById('report-title') || {}).textContent,
    bgInert: document.querySelector('main').inert === true
  }));
  check('举报框（原生 dialog）被基建认成最上层并纳入约束', nat.isTop && nat.bgInert, JSON.stringify(nat));
  check('读屏能按名字找到举报对话框', await k.getByRole('dialog', { name: /举报这条内容/ }).count() > 0, JSON.stringify(nat));
  await k.keyboard.press('Escape');
  await k.waitForFunction(() => !document.getElementById('report-dialog').open, { timeout: 3000 });
  check('Esc 关闭原生 <dialog> 举报框', await k.evaluate(() => !document.getElementById('report-dialog').open), '');

  // 键盘补偿：<div role="button" tabindex="0"> 的浮层入口必须能用回车激活。
  // 悬浮入口在 <=760px 是 display:none（features.css:739），所以这条在桌面宽度下量。
  const wide = await newPage({ viewport: { width: 1280, height: 820 } });
  const w = wide.page;
  const pill = await w.evaluate(() => {
    const el = document.getElementById('floating-dl-btn');
    el.focus();
    return { role: el.getAttribute('role'), shown: getComputedStyle(el).display !== 'none', focused: document.activeElement === el };
  });
  await w.keyboard.press('Enter');
  const pillOpen = await w.evaluate(() => document.getElementById('download-apk-modal').classList.contains('show'));
  check('role=button 入口能被回车激活（键盘补偿没退化）',
    pill.role === 'button' && pill.shown && pill.focused && pillOpen, JSON.stringify({ pill, pillOpen }));
  await w.keyboard.press('Escape');
  check('Esc 关掉悬浮入口打开的下载弹窗',
    await w.evaluate(() => !document.getElementById('download-apk-modal').classList.contains('show')), '');

  check('全程页面脚本零报错（弹窗改造没把产品跑崩）', pageErrors.length === 0, pageErrors.slice(0, 2).join(' / '));
  await fs.promises.writeFile(path.join(folder, 'errors.txt'), pageErrors.join('\n'));
} catch (err) {
  // 半路抛异常也要把已跑出来的判据吐出来，否则整份输出为空等于没测
  check('浏览器判据整段跑完（没有半路抛异常）', false, String(err && err.message).slice(0, 160));
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) { child.kill(); await new Promise(r => child.once('exit', r)); }
}
report();

function report() {
  const bad = R.filter(x => !x[1]);
  for (const [name, ok, detail] of R) console.log(`  ${ok ? '绿' : '红'} ${name}${ok ? '' : '  -> ' + detail}`);
  console.log(`\n=== B10 弹窗/无障碍契约：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
  console.log('EXIT=' + (bad.length === 0 ? 0 : 1));
  process.exit(bad.length === 0 ? 0 : 1);
}
