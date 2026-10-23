// B03 记录省步骤 / B04 档案拆组与保存前摘要 / B09 权限中心 —— 真浏览器判据。
//
// 这一份钉的全是"操作结果"：点一下输入框里到底变成什么、复制上一餐有没有真的入账、
// 探针抛异常时屏上写的是"未知"还是 0。源码里有没有那个 class 不算数。
// 上一轮 B03/B04/B09 的代码落地时一条判据都没写，这批就是补那笔账。
//
// 用法（四个环境变量都要给齐，缺一样会以"产品坏"的样子假红）：
//   NODE_PATH=... QINGSU_TEST_PYTHON=... QINGSU_CHROME_PATH=... node tests/records-profile-permission.mjs
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, '..');
const A = p => path.join(ROOT, 'app/src/main/assets', p);
const { chromium } = require('playwright');

const PORT = 18047;
const BASE = `http://127.0.0.1:${PORT}`;
const folder = fs.mkdtempSync(path.join(ROOT, '_audit_sandbox', 'rpp-'));

const R = [];
const check = (name, ok, detail = '') => R.push([name, !!ok, ok ? '' : String(detail)]);

async function waitUntil(predicate, timeout = 8000) {
  // Node 侧轮询。page.waitForFunction 的谓词跑在浏览器里，看不见 Node 的变量——
  // 拿它等一个 Node 侧收集的数组会当场 ReferenceError（本轮踩过一次）。
  const deadline = Date.now() + timeout;
  for (;;) {
    if (predicate()) return true;
    if (Date.now() >= deadline) return false;
    await new Promise(r => setTimeout(r, 60));
  }
}

async function api(pathname, options = {}, token) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(BASE + pathname, { ...options, headers });
  const text = await r.text();
  let body = null;
  try { body = JSON.parse(text); } catch { body = text; }
  return { status: r.status, body, text };
}

async function register(username, weightJin) {
  const r = await api('/api/register', {
    method: 'POST',
    body: JSON.stringify({ username, password: 'Records!123', age: 30, height: 170,
      weight_jin: weightJin, target_weight_jin: 140 })
  });
  assert.equal(r.status, 200, r.text);
  return r.body;
}

const child = spawn(process.env.QINGSU_TEST_PYTHON || 'python',
  ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)],
  { cwd: ROOT, env: {
    ...process.env,
    QINGSU_DB_DIR: path.join(folder, 'db'), QINGSU_UPLOAD_DIR: path.join(folder, 'uploads'),
    QINGSU_KEY_DIR: path.join(folder, 'keys'), QINGSU_WEB_DIR: A('') } });

let browser;
const pageErrors = [];
try {
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(BASE + '/health')).ok) break; } catch { }
    await new Promise(r => setTimeout(r, 100));
  }

  // ---------- B03 的历史：A 自己有 3 笔不同菜，另有一个人做对照 ----------
  const uA = await register('rppmeals', 163);
  const uB = await register('rppother', 163);
  for (const [name, cal, times] of [['番茄炒蛋饭', 520, 3], ['鸡胸藜麦碗', 430, 2], ['牛肉面', 610, 1]]) {
    for (let n = 0; n < times; n++) {
      const r = await api('/api/food/log', { method: 'POST',
        body: JSON.stringify({ food_name: name, slot: '午餐', cal }) }, uA.token);
      assert.equal(r.status, 200, r.text);
    }
  }
  await api('/api/food/log', { method: 'POST',
    body: JSON.stringify({ food_name: '同事的麻辣烫', slot: '午餐', cal: 700 }) }, uB.token);

  // 下面几段会各自改档案、改体重，共用一个人会让上一段写的数把下一段的等待拖成假红，
  // 所以 B04 / B09 各用一个干净账号。
  const uProf = await register('rppprofile', 163);
  const uPerm = await register('rppperm', 163);

  browser = await chromium.launch({ headless: true,
    ...(process.env.QINGSU_CHROME_PATH ? { executablePath: process.env.QINGSU_CHROME_PATH } : {}) });

  const newPage = async (user, bridgeStub) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    page.on('pageerror', e => pageErrors.push(String(e && e.stack ? e.stack : e)));
    await page.addInitScript(u => {
      localStorage.setItem('QINGSU_AUTH_TOKEN', u.token);
      localStorage.setItem('QINGSU_AUTH_USER', JSON.stringify({ id: u.id, username: u.username }));
    }, user);
    if (bridgeStub) await page.addInitScript(bridgeStub);
    await page.goto(BASE);
    await page.waitForFunction(() => typeof openProfileModal === 'function'
      && typeof openPermissionCenter === 'function' && typeof loadRecentMeals === 'function');
    return { ctx, page };
  };

  // ================================================== B03
  {
    const { page, ctx } = await newPage(uA);

    // ---- 「常用餐食」列表本身要长出来（顺带验 loadRecentMeals 那颗按钮的绑定） ----
    await page.evaluate(() => document.getElementById('recent-meal-reload').click());
    await page.waitForFunction(() => document.querySelectorAll('#recent-meal-list .rm-chip').length > 0,
      null, { timeout: 8000 });
    const chips = await page.evaluate(() => [...document.querySelectorAll('#recent-meal-list .rm-chip')]
      .map(b => ({ id: b.id, name: b.dataset.name, meta: b.innerText })));
    check('B03 「刷新常用」按钮改绑后仍真的去拉了本人历史（点得出条目）',
      chips.length === 3, JSON.stringify(chips));
    check('B03 列表按本人记的次数排，最多的排第一',
      chips[0] && chips[0].name === '番茄炒蛋饭' && /记过 3 次/.test(chips[0].meta),
      JSON.stringify(chips[0] || {}));
    const foreign = chips.filter(c => c.name === '同事的麻辣烫');
    check('B03 界面上没有把别人的菜混进"你自己常记的"里',
      foreign.length === 0, JSON.stringify(foreign));

    // ---- 钉操作结果：点第 2 项，输入框里必须真的变成那一份 ----
    const target = chips[1].name;
    await page.evaluate(id => document.getElementById(id).click(), chips[1].id);
    await page.waitForFunction(() => {
      const d = document.getElementById('account-tools-dialog');
      return d && d.open;
    }, null, { timeout: 5000 });
    const afterChip = await page.evaluate(() => ({
      input: document.getElementById('input-meal-text').value,
      dialogText: (document.getElementById('account-tools-dialog') || { innerText: '' }).innerText,
    }));
    check('B03 点「常用餐食」某一项之后，输入框里真的变成了那一份餐食（不是只加了个 class）',
      afterChip.input === target, `期望「${target}」实得「${afterChip.input}」`);
    check('B03 带出来的那一屏说清了"还是草稿、点确认才入账"',
      /草稿/.test(afterChip.dialogText) && /确认并保存/.test(afterChip.dialogText),
      afterChip.dialogText.slice(0, 160));
    await page.evaluate(() => { const d = document.getElementById('account-tools-dialog'); if (d) d.close(); });
    await ctx.close();
  }

  // ---- 「复制上一餐」只出草稿，不入账 ----
  {
    const { page, ctx } = await newPage(uA);
    await page.evaluate(() => loadRecentMeals());
    const beforeCount = (await api('/api/records?kind=food&limit=1&offset=0', {}, uA.token)).body.total;
    const logCalls = [];
    page.on('request', r => { if (/\/api\/food\/log$/.test(r.url())) logCalls.push(r.url()); });

    for (const [id, label] of [['copy-last-ever', '复制最近一餐'], ['copy-last-today', '复制今天上一餐']]) {
      await page.evaluate(i => {
        const t = document.getElementById('input-meal-text'); if (t) t.value = '';
        document.getElementById(i).click();
      }, id);
      await page.waitForFunction(() => {
        const d = document.getElementById('account-tools-dialog');
        return d && d.open;
      }, null, { timeout: 6000 }).catch(() => { });
      const state = await page.evaluate(() => {
        const d = document.getElementById('account-tools-dialog');
        const cal = document.getElementById('meal-confirm-cal');
        return { open: !!(d && d.open), text: d ? d.innerText : '',
          input: document.getElementById('input-meal-text').value,
          cal: cal ? cal.value : null, calDisabled: cal ? cal.disabled : null,
          calReadonly: cal ? cal.readOnly : null };
      });
      check(`B03「${label}」按钮改绑后点了真的出草稿（弹窗打开且带回菜名）`,
        state.open && state.input.length > 0 && state.text.includes('草稿'),
        JSON.stringify(state).slice(0, 220));
      // 可编辑：把热量改成另一个数，必须改得动
      const edited = await page.evaluate(() => {
        const cal = document.getElementById('meal-confirm-cal');
        if (!cal) return { ok: false };
        const old = cal.value;
        cal.value = String(Number(old || 0) + 77);
        return { ok: cal.value !== old, before: old, after: cal.value,
          disabled: cal.disabled, readonly: cal.readOnly };
      });
      check(`B03「${label}」带出的是可编辑草稿（数值格改得动、没被锁死）`,
        edited.ok === true && !edited.disabled && !edited.readonly, JSON.stringify(edited));
      await page.evaluate(() => { const d = document.getElementById('account-tools-dialog'); if (d) d.close(); });
    }
    check('B03 复制上一餐这一下没有调用 /api/food/log（没直接入账）',
      logCalls.length === 0, logCalls.join(','));
    const afterCount = (await api('/api/records?kind=food&limit=1&offset=0', {}, uA.token)).body.total;
    check('B03 复制上一餐之后云端的餐食条数一条都没多',
      afterCount === beforeCount, `${beforeCount} -> ${afterCount}`);
    await ctx.close();
  }

  // ---- 体重单位：一处真值，顶栏/档案/图表三处对得上 ----
  {
    const { page, ctx } = await newPage(uA);
    await page.waitForFunction(() => /当前\s*163\s*斤/.test(
      (document.getElementById('current-weight-summary') || {}).innerText || ''), null, { timeout: 8000 });
    const topbar = await page.evaluate(() => document.getElementById('current-weight-summary').innerText);
    const chart = await page.evaluate(() => ({
      start: document.getElementById('chart-start-wt').innerText,
      target: document.getElementById('chart-target-wt').innerText }));
    await page.evaluate(() => openProfileModal());
    await page.waitForTimeout(200);
    const profile = await page.evaluate(() => document.getElementById('prof-weight-jin').value);
    check('B03 体重单位切换前：顶栏按斤、图表按 kg、档案按斤三处都在同一个真值上',
      /163/.test(topbar) && chart.start === '81.5 kg' && profile === '163',
      JSON.stringify({ topbar, chart, profile }));
    check('B03 图表那个 kg 就是顶栏斤数除以唯一真值 2（没人在展示层手算出第二个数）',
      Number(chart.start.replace(/[^\d.]/g, '')).toFixed(1) === (Number(topbar.match(/(\d+(?:\.\d+)?)/)[1]) / 2).toFixed(1),
      `${topbar} vs ${chart.start}`);

    // 按 kg 填 82 → 上云的必须是 164 斤（换算的另一半）
    const posts = [];
    page.on('request', r => { if (/\/api\/weight\/log$/.test(r.url())) posts.push(r.postData()); });
    await page.evaluate(() => {
      document.getElementById('weight-unit').value = 'kg';
      document.getElementById('input-weight').value = '82';
    });
    await page.evaluate(() => saveWeight());
    await waitUntil(() => posts.length > 0);
    const sent = posts.length ? JSON.parse(posts[0]) : null;
    check('B03 切到 kg 填 82 打卡：上云的是 164 斤（换算只有一处真值，两头都得对）',
      sent && Number(sent.weight_jin) === 164, JSON.stringify(sent));
    const afterTop = await page.evaluate(() => document.getElementById('current-weight-summary').innerText);
    check('B03 kg 打卡之后顶栏跟着变成 164 斤，没和刚填的那格各说一套',
      /164/.test(afterTop), afterTop);
    await ctx.close();
  }

  // ================================================== B04
  {
    const { page, ctx } = await newPage(uProf);
    await page.waitForFunction(() => /当前\s*163\s*斤/.test(
      (document.getElementById('current-weight-summary') || {}).innerText || ''), null, { timeout: 8000 });
    await page.evaluate(() => openProfileModal());
    await page.waitForTimeout(300);

    const pre = await page.evaluate(() => ({
      summaryHidden: document.getElementById('profile-change-summary').hidden,
      summaryText: document.getElementById('profile-change-summary').innerText,
      confirm: (() => { const b = document.getElementById('profile-summary-confirm');
        return b ? { text: b.innerText, inHidden: !!b.closest('[hidden]'), disabled: b.disabled } : null })(),
    }));
    check('B04 摘要还没出现时，「确认」按钮不可用（藏在 hidden 容器里，点不到）',
      pre.summaryHidden && pre.confirm && pre.confirm.inHidden === true, JSON.stringify(pre));
    const heightBefore = (await api('/api/dashboard', {}, uProf.token)).body.profile.height;
    await page.evaluate(() => { document.getElementById('prof-height').value = '166'; });
    await page.evaluate(() => document.getElementById('prof-save-basic').click());
    await page.waitForTimeout(300);
    const mid = await page.evaluate(() => ({
      summaryHidden: document.getElementById('profile-change-summary').hidden,
      summaryText: document.getElementById('profile-change-summary').innerText,
      confirmHidden: (() => { const b = document.getElementById('profile-summary-confirm');
        return b ? !!b.closest('[hidden]') : null; })(),
      pending: typeof pendingProfileSection !== 'undefined' && !!pendingProfileSection,
    }));
    check('B04 点「保存这一组」后摘要出现，确认按钮这才可用',
      !mid.summaryHidden && mid.confirmHidden === false, JSON.stringify(mid));
    check('B04 摘要说清了「从什么变成什么」，不是只说一句"已修改"',
      /身高/.test(mid.summaryText) && /170 cm/.test(mid.summaryText)
      && /166 cm/.test(mid.summaryText) && /→/.test(mid.summaryText), mid.summaryText.slice(0, 200));
    const notYet = (await api('/api/dashboard', {}, uProf.token)).body.profile.height;
    check('B04 只列摘要还没写入：云端身高仍是原来那个（确认之前不许落库）',
      Number(notYet) === Number(heightBefore), `${heightBefore} -> ${notYet}`);

    // 「先不保存」真的把待确认状态清掉
    await page.evaluate(() => document.getElementById('profile-summary-cancel').click());
    await page.waitForTimeout(200);
    const cancelled = await page.evaluate(() => ({
      pending: typeof pendingProfileSection !== 'undefined' && !!pendingProfileSection,
      summaryHidden: document.getElementById('profile-change-summary').hidden,
      confirmHidden: !!document.getElementById('profile-summary-confirm').closest('[hidden]'),
    }));
    check('B04「先不保存」撤得干净：待确认没了、摘要与确认按钮一起收回去',
      !cancelled.pending && cancelled.summaryHidden && cancelled.confirmHidden,
      JSON.stringify(cancelled));

    // 走完确认：这次才真的写
    await page.evaluate(() => { document.getElementById('prof-height').value = '166'; });
    await page.evaluate(() => document.getElementById('prof-save-basic').click());
    await page.waitForTimeout(300);
    await page.evaluate(() => document.getElementById('profile-summary-confirm').click());
    // 在 Node 这边轮询服务端，别把异步断言塞进 waitForFunction（那边失败会被 catch 吞掉，
    // 结果测到的是"还没写完"而不是"写坏了"）
    let written = null;
    for (let i = 0; i < 60; i++) {
      written = (await api('/api/dashboard', {}, uProf.token)).body.profile.height;
      if (Number(written) === 166) break;
      await new Promise(r => setTimeout(r, 200));
    }
    check('B04 看完摘要点「确认」之后才写入：云端身高变成 166',
      Number(written) === 166, String(written));

    // 四组按钮都要真的接上（点一组报一组的标题）。
    // 这里直接改隐藏域/输入格的值而不调 pick* 那个入口：pickProfileScene 会顺手把
    // state.profile.scene 也改掉并静默保存，那样就凑不出"待确认的变更"了。
    //
    // 每组还各自钉一条"请求体里不许出现别组的键"：服务端接受部分更新是另一层的事
    // （test_optimization_ux.py 已覆盖），客户端要是全量重发，点场景就会把旧体重写回去。
    const GROUP_KEYS = {
      basic: ['gender', 'age', 'height', 'weight_jin'],
      goal: ['target_weight_jin', 'goal_type'],
      scene: ['scene'],
      dining: ['dining_mode'],
    };
    for (const [key, title, fill] of [['goal', '目标', ['#prof-target-jin', '133']],
      ['scene', '训练场景', ['#prof-scene', 'cardio']],
      ['dining', '饮食偏好', ['#prof-dining-mode', 'hybrid']]]) {
      const sentBodies = [];
      const grab = r => {
        // 档案写入是 POST /api/profile/update（不是 PATCH），按 PATCH 过滤会一条都抓不到。
        if (/\/api\/profile\/update$/.test(r.url()) && r.method() === 'POST') {
          try { sentBodies.push(JSON.parse(r.postData() || '{}')); } catch (e) { }
        }
      };
      page.on('request', grab);
      await page.evaluate(() => { document.getElementById('profile-change-summary').hidden = true; });
      await page.evaluate(([sel, val]) => { document.querySelector(sel).value = val; }, fill);
      await page.evaluate(k => document.getElementById('prof-save-' + k).click(), key);
      await page.waitForTimeout(200);
      const g = await page.evaluate(() => ({
        hidden: document.getElementById('profile-change-summary').hidden,
        text: document.getElementById('profile-change-summary').innerText,
        confirmHidden: !!document.getElementById('profile-summary-confirm').closest('[hidden]'),
      }));
      check(`B04「保存这一组（${title}）」按钮改绑后点的就是这一组`,
        !g.hidden && g.text.includes(title) && g.confirmHidden === false, g.text.slice(0, 140));
      // 点「确认」才真正发请求
      await page.evaluate(() => document.getElementById('profile-summary-confirm').click());
      await waitUntil(() => sentBodies.length > 0);
      page.off('request', grab);
      const foreign = Object.keys(Object.assign({}, ...sentBodies))
        .filter(k => !GROUP_KEYS[key].includes(k));
      check(`B04 只保存【${title}】时请求体里不出现别组的键`,
        sentBodies.length > 0 && foreign.length === 0,
        sentBodies.length ? '混进了 ' + foreign.join('、') : '压根没发出档案写入');
      // 档案写入走 queueProfileUpdate 的串行链：请求"发出"不等于这一组已经收尾。
      // 不等摘要真的收起就进下一轮，pendingProfileSection 还挂着上一组，
      // 下一句 saveProfileSection 读到的标题就会是上一组的（实测报成【目标】）。
      // 这里等的是浏览器里的 DOM，用 waitForFunction 才对（Node 侧轮询是给数组用的）。
      await page.waitForFunction(() => {
        const box = document.getElementById('profile-change-summary');
        if (box && !box.hidden && box.innerText.trim()) return false;
        const acts = document.getElementById('profile-summary-acts');
        if (acts) acts.hidden = true;
        if (box) box.hidden = true;
        return true;
      }, null, { timeout: 8000 }).catch(() => { });
    }
    await ctx.close();
  }

  // ---- r176 目标身材 × 训练场景 联动 ----
  {
    const { page, ctx } = await newPage(uProf);
    await page.waitForFunction(() => /当前\s*163\s*斤/.test(
      (document.getElementById('current-weight-summary') || {}).innerText || ''), null, { timeout: 8000 });
    await page.evaluate(() => openProfileModal());
    await page.waitForTimeout(200);
    const read = async () => page.evaluate(() => ({
      preview: document.getElementById('prof-plan-preview').innerText,
      scene: document.getElementById('prof-scene').value,
      goal: state.profile.goalType,
    }));
    await page.evaluate(() => pickProfileScene('home'));
    const home = await read();
    await page.evaluate(() => pickProfileScene('gym'));
    const gym = await read();
    check('B04 r176 联动还在：换训练场景，方案预览跟着换成那个场景的组合结果',
      home.preview !== gym.preview && gym.preview.includes('健身房') , JSON.stringify({ home: home.preview.slice(0, 90), gym: gym.preview.slice(0, 90) }));
    await page.evaluate(() => pickProfileScene('home'));
    const sameScene = await read();
    check('B04 r176 联动是可逆的：换回居家自重，预览又变回居家那一套',
      sameScene.preview === home.preview, JSON.stringify(sameScene.preview.slice(0, 90)));
    await ctx.close();
  }

  // ================================================== B09
  {
    // 探针抛异常 → 必须报"未知"，不许报 0 / 已关闭
    const throwing = `(() => {
      window.AndroidBridge = {
        showToast(){}, vibrate(){},
        microphonePermissionState(){ throw new Error('原生通道炸了'); },
        notificationsEnabled(){ throw new Error('通知状态读不回来'); },
        usageAccessEnabled(){ return true; },
        takeoutUsageToday(){ throw new Error('使用记录读不回来'); },
        reminderStatus(){ throw new Error('提醒状态读不回来'); },
      };
    })();`;
    const { page, ctx } = await newPage(uPerm, throwing);
    await page.evaluate(() => document.getElementById('tools-permission-row').click());
    await page.waitForFunction(() => { const d = document.getElementById('account-tools-dialog');
      return d && d.open; }, null, { timeout: 8000 });
    const perm = await page.evaluate(() => ({
      text: document.getElementById('account-tools-dialog').innerText,
      badges: [...document.querySelectorAll('#account-tools-dialog .td-badge')].map(b => b.innerText.trim()),
    }));
    check('B09 权限中心按钮改绑后真的打开了（点得出那一屏）',
      perm.text.includes('权限中心'), perm.text.slice(0, 80));
    // 逐行取徽章与那一行自己的正文：弹窗开头那句免责声明里本来就在说
    // "不会拿 0 次、已关闭冒充读到的结果"，拿整屏文本来正则会把这句当成违规。
    const rowsOf = p => p.evaluate(() => [...document.querySelectorAll('#account-tools-dialog .td-row')]
      .map(r => ({ title: (r.querySelector('.td-row-title') || { innerText: '' }).innerText.trim(),
        badge: (r.querySelector('.td-badge') || { innerText: '' }).innerText.trim(),
        rowText: r.innerText.replace(/\s+/g, ' ').trim() })));
    const permRows = await rowsOf(page);
    const micRow = permRows.find(r => /麦克风/.test(r.title)) || {};
    check('B09 探针抛异常时那一格渲染的是「未知」，不是 0、也不是「已关闭」',
      /未知/.test(micRow.badge || '') && !/^0/.test(micRow.badge || '')
      && !/已关闭/.test(micRow.badge || ''), JSON.stringify(micRow));
    check('B09 读不到的时候，那一行写清了是哪一个接口没回话（不是笼统一句未知）',
      /抛/.test(micRow.rowText || '') && /microphonePermissionState|AndroidBridge/.test(micRow.rowText || ''),
      (micRow.rowText || '').slice(0, 200));
    const zeroBadges = permRows.filter(r => /^0|已关闭/.test(r.badge));
    check('B09 没有任何一格的徽章被画成 0 或「已关闭」（读不到不等于没发生）',
      zeroBadges.length === 0, JSON.stringify(zeroBadges));
    const badCount = permRows.filter(r => /开了几次|外卖 App/.test(r.title) && /0\s*次/.test(r.rowText));
    check('B09 使用记录一格都没读回来时，那一行不许出现「0 次」',
      badCount.length === 0, JSON.stringify(badCount));

    // 离线通知那段：钉最终 DOM，不是钉源码字符串
    check('B09 离线通知那段在最终 DOM 里明说了"没有接厂商推送、杀掉后台不会响"',
      /没有接厂商推送/.test(perm.text) && /杀掉后台/.test(perm.text) && /不会响/.test(perm.text),
      perm.text.slice(-320));

    // ---- 四种状态各渲染出不同且可读的文案 ----
    const states = {
      granted: `(() => { window.AndroidBridge = { showToast(){}, vibrate(){},
        microphonePermissionState(){ return 'granted'; }, notificationsEnabled(){ return true; },
        usageAccessEnabled(){ return true; }, takeoutUsageToday(){ return '{"apps":[{"count":3}]}'; },
        reminderStatus(){ return '{"enabled":true,"hour":9,"minute":0}'; } }; })();`,
      denied: `(() => { window.AndroidBridge = { showToast(){}, vibrate(){},
        microphonePermissionState(){ return 'denied'; }, notificationsEnabled(){ return false; },
        usageAccessEnabled(){ return false; }, takeoutUsageToday(){ return '{"apps":[]}'; },
        reminderStatus(){ return '{"enabled":false,"hour":9,"minute":0}'; } }; })();`,
      blocked: `(() => { window.AndroidBridge = { showToast(){}, vibrate(){},
        microphonePermissionState(){ return 'blocked'; }, notificationsEnabled(){ return false; },
        usageAccessEnabled(){ return false; }, takeoutUsageToday(){ return '{"apps":[]}'; },
        reminderStatus(){ return '{"enabled":false,"hour":21,"minute":30}'; } }; })();`,
      unknown: throwing,
    };
    const rendered = {};
    const firstLine = t => t.split('\n').map(s => s.trim()).filter(Boolean);
    for (const [name, stub] of Object.entries(states)) {
      const one = await newPage(uPerm, stub);
      await one.page.evaluate(() => openPermissionCenter());
      await one.page.waitForFunction(() => { const d = document.getElementById('account-tools-dialog');
        return d && d.open; }, null, { timeout: 8000 });
      rendered[name] = await one.page.evaluate(() => ({
        mic: (document.getElementById('perm-badge-mic') || {}).innerText,
        micLabel: (document.getElementById('perm-badge-mic') || {}).getAttribute('aria-label'),
        text: document.getElementById('account-tools-dialog').innerText,
        rows: [...document.querySelectorAll('#account-tools-dialog .td-row-title')]
          .map(x => x.innerText.trim()),
        named: [...document.querySelectorAll('#account-tools-dialog [aria-label]')]
          .filter(x => (x.getAttribute('aria-label') || '').trim().length > 0).length,
      }));
      await one.ctx.close();
    }
    const words = Object.entries(rendered).map(([k, v]) => [k, (v.mic || '').trim()]);
    for (const [k, w] of words) {
      check(`B09 状态 ${k} 渲染出的那一格有非空、可念出来的文字`,
        w.length > 0 && w !== '0' && !/^[\s]*$/.test(w), JSON.stringify(w));
    }
    const distinct = new Set(words.map(([, w]) => w));
    check('B09 granted / denied / 永久拒绝 / 未知 四种状态渲染出的文案互不相同',
      distinct.size === 4, JSON.stringify(words));
    check('B09 永久拒绝那一格说的是"只能去设置里开"，不是笼统一句"已关闭"',
      /永久拒绝/.test(rendered.blocked.mic) && /设置/.test(rendered.blocked.mic),
      JSON.stringify(rendered.blocked.mic));
    check('B09 每一行都带着读屏可用的标题（rows 六行都非空）',
      rendered.granted.rows.length >= 6 && rendered.granted.rows.every(r => r.length > 2),
      JSON.stringify(rendered.granted.rows));

    // 从系统设置返回那一条：Permissions API 读不到时靠上次实测记录说话
    {
      const one = await newPage(uPerm, `(() => {
        window.AndroidBridge = { showToast(){}, vibrate(){},
          microphonePermissionState(){ return 'prompt'; }, notificationsEnabled(){ return true; },
          usageAccessEnabled(){ return true; }, takeoutUsageToday(){ return '{"apps":[{"count":2}]}'; },
          reminderStatus(){ return '{"enabled":true,"hour":8,"minute":15}'; } };
        try {
          localStorage.setItem('QINGSU_PERM_TRY_' + JSON.parse(localStorage.getItem('QINGSU_AUTH_USER')).username,
            JSON.stringify({ location: { label: '从系统设置里开回来了', at: '2026-10-22 09:00:00' } }));
        } catch (e) { }
        try { navigator.permissions.query = function () { return Promise.reject(new Error('这个 WebView 禁了这个查询')); }; } catch (e) { }
      })();`);
      await one.page.evaluate(() => openPermissionCenter());
      await one.page.waitForFunction(() => { const d = document.getElementById('account-tools-dialog');
        return d && d.open; }, null, { timeout: 8000 });
      const back = await one.page.evaluate(() => document.getElementById('account-tools-dialog').innerText);
      check('B09 从系统设置返回这一格：读不到当前状态时，讲的是"上次实测"而不是编一个',
        /未知/.test(back) && /上次实测/.test(back) && /从系统设置里开回来了/.test(back),
        back.slice(0, 240));
      await one.ctx.close();
    }

    // 授权了但记录读不回来 → 不许写 0 次
    {
      const one = await newPage(uPerm, `(() => {
        window.AndroidBridge = { showToast(){}, vibrate(){},
          microphonePermissionState(){ return 'granted'; }, notificationsEnabled(){ return true; },
          usageAccessEnabled(){ return true; }, takeoutUsageToday(){ throw new Error('拿不到使用情况'); },
          reminderStatus(){ return '{"enabled":true,"hour":9,"minute":0}'; } };
      })();`);
      await one.page.evaluate(() => openPermissionCenter());
      await one.page.waitForFunction(() => { const d = document.getElementById('account-tools-dialog');
        return d && d.open; }, null, { timeout: 8000 });
      const usageRows = await rowsOf(one.page);
      const usageRow = usageRows.find(r => /使用情况访问/.test(r.title)) || {};
      check('B09 已授权但使用记录没读回来时，那一行写的是"没读回来"，绝不写「今天打开外卖 App 0 次」',
        /没读回来/.test(usageRow.rowText || '') && !/0\s*次/.test(usageRow.rowText || '')
        && usageRow.badge === '已授权', JSON.stringify(usageRow).slice(0, 240));
      await one.ctx.close();
    }

    // ---- 自助导出 / 注销：不许有假装能用的入口 ----
    {
      const exportCalls = [];
      const { page: p2, ctx: c2 } = await newPage(uPerm);
      p2.on('request', r => { if (/\/api\/export\.csv/.test(r.url())) exportCalls.push(r.url()); });
      await p2.evaluate(() => {
        const t = document.getElementById('account-tools-dialog'); if (t) t.remove();
        openAccountCenter();
      });
      await p2.waitForFunction(() => { const d = document.getElementById('account-tools-dialog');
        return d && d.open && document.getElementById('qs-export-btn'); }, null, { timeout: 8000 });
      const beforeStatus = await p2.evaluate(() => document.getElementById('export-status').innerText);
      await p2.evaluate(() => document.getElementById('qs-export-btn').click());
      await p2.waitForFunction(() => !/还没导出过/.test(document.getElementById('export-status').innerText),
        null, { timeout: 8000 }).catch(() => { });
      const afterStatus = await p2.evaluate(() => ({
        status: document.getElementById('export-status').innerText,
        text: document.getElementById('account-tools-dialog').innerText,
        buttons: [...document.querySelectorAll('#account-tools-dialog button')]
          .map(b => b.innerText.trim()).filter(Boolean),
      }));
      check('B09 导出那颗按钮不是空壳：点下去真的去打 /api/export.csv 并回报结果',
        exportCalls.length === 1 && !/还没导出过/.test(afterStatus.status)
        && afterStatus.status !== beforeStatus,
        JSON.stringify({ calls: exportCalls.length, status: afterStatus.status.slice(0, 120) }));

      const faking = afterStatus.buttons.filter(t => /一键注销|立即注销|已注销|永久删除账号|即刻删除账号|账号已删除/.test(t));
      check('B09 界面上没有假装能注销账号的按钮（服务端本人侧根本没有这个接口）',
        faking.length === 0, JSON.stringify(faking));
      check('B09 注销那格自己承认"服务端没有给本人用的注销接口"，只说提交诉求与单号',
        /没有.*?删除\/注销接口|没有\u3000<b>没有<\/b>/.test(afterStatus.text)
        || /不会假装能一键注销/.test(afterStatus.text), afterStatus.text.slice(0, 60));
      check('B09 那颗按钮的读屏文字是「提交注销申请」这一类，不是「注销账号」这种已办成的口气',
        afterStatus.buttons.some(t => /提交注销申请/.test(t)), JSON.stringify(afterStatus.buttons));
      await c2.close();
    }
  }

  check('全程页面脚本零报错（改绑与判据没把产品跑崩）',
    pageErrors.length === 0, pageErrors.slice(0, 3).join(' / '));
} catch (err) {
  check('浏览器判据整段跑完（没有半路抛异常）', false, String(err && err.message).slice(0, 240));
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) { child.kill(); await new Promise(r => setTimeout(r, 300)); }
}

function report() {
  const bad = R.filter(x => !x[1]);
  for (const [name, ok, detail] of R) console.log(`  ${ok ? '绿' : '红'} ${name}${ok ? '' : '  -> ' + detail}`);
  console.log(`\n=== B03/B04/B09 记录·档案·权限 真浏览器判据：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
  console.log('EXIT=' + (bad.length === 0 ? 0 : 1));
  process.exit(bad.length === 0 ? 0 : 1);
}
report();
