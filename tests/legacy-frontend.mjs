// 轻塑前端回归台：用 vm + DOM stub 直接跑仓库里那份 app.js（不是手搓参考实现）
// 用法:  node tests/legacy-frontend.mjs            → 当前源码，应全绿
//        node tests/legacy-frontend.mjs --mutant   → git HEAD 那版，应大面积红
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const JS_REL = "app/src/main/assets/app.js";
const MUT_ARG = process.argv.find(a => a === "--mutant" || a.startsWith("--mutant=")) || "";
// 提交之后 HEAD 就等于当前源码，反样本必须能钉住改动前那一版，否则标定自己会过期。
const MUT_REF = MUT_ARG.startsWith("--mutant=") ? MUT_ARG.split("=")[1] : "HEAD";
const MUTANT = MUT_ARG !== "";

// ------------------------------------------------------------------ stub 层
function makeCtx() {
  const log = { toasts: [], alerts: [], arcs: [], texts: [], vib: 0, fetches: [] };

  const mkCanvasCtx = () => ({
    canvas: null,
    clearRect() {}, beginPath() {}, closePath() {}, moveTo() {}, lineTo() {},
    fill() {}, stroke() {}, setLineDash() {}, roundRect() {},
    createLinearGradient() { return { addColorStop() {} }; },
    fillText(t) { log.texts.push(String(t)); },
    fillStyle: "", strokeStyle: "", font: "", textAlign: "", lineWidth: 0, strokeDashoffset: 0,
  });

  const ctx2d = mkCanvasCtx();
  // 统一记录 arc，用来判断"灰环一圈"还是"三段假配比"
  const instrument = (c) => {
    c.arc = (x, y, r, a0, a1) => { log.arcs.push([a0, a1]); };
    return c;
  };
  instrument(ctx2d);

  const elems = new Map();
  let dynSeq = 0;
  function newEl(id) {
    let _html = "";
    const el = {
      id, value:"",
      style: {}, checked: false, files: null,
      width: 0, height: 0,
      classList: {
        _s: new Set(),
        add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
        contains(c) { return this._s.has(c); },
        toggle(c, on) {
          if (on === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
          else { on ? this._s.add(c) : this._s.delete(c); }
        },
      },
      getContext() { return ctx2d; },
      _children: [],
      appendChild(c) { this._children.push(c); return c; },
      remove() {}, select() {}, focus() {}, click() { log.clicks = (log.clicks || 0) + 1 },
      querySelectorAll() { return []; },
      // 元素级 querySelector 以前恒返回 null，于是"弹窗里找关闭按钮"
      // "弹窗里找可聚焦元素"这类代码在桩里永远走空分支，测不到东西。
      querySelector(sel) { return mkEl(this.id + "|q|" + sel); },
      addEventListener() {},
      // 弹窗绑定用 el.dataset.a11yBound 去重；桩没有 dataset 就整段抛掉。
      dataset: {},
      // 桩缺 setAttribute 会让代码一调就抛、异常被 init 吞掉，
      // 表现成"逻辑没生效"而真因是桩少方法——这类假红上一批已经踩过一次。
      _attrs: {},
      nodeType: 1,
      setAttribute(k, v) { this._attrs[String(k)] = String(v); },
      hasAttribute(k) { return this._attrs[String(k)] !== undefined; },
      // 弹窗遮罩那段会问"这个节点包含它吗"，桩没有 contains 就整段抛掉。
      contains(other) { return other === this; },
      getAttribute(k) { const v = this._attrs[String(k)]; return v === undefined ? null : v; },
      removeAttribute(k) { delete this._attrs[String(k)]; },
    };
    // innerHTML 必须有真实父子语义：写 innerHTML 会清掉子节点，appendChild 的内容要能读回来。
    // 否则 appendBubble 写进去的气泡在断言里永远是空串，测不出任何东西。
    Object.defineProperty(el, "innerHTML", {
      enumerable: true,
      get() { return _html + this._children.map(c => c.innerHTML).join(""); },
      set(v) { _html = String(v); this._children = []; },
    });

    // innerText 与 textContent 在真实 DOM 里都会反映元素文本；桩里分成两个独立字段，
    // 于是代码写 textContent、判据读 innerText，读到空串——上一批"未授权显示未授权"
    // 就是这么红了 5 条却根本不是产品的错。两个名字共用一份后备，并回退到 innerHTML。
    let _text = null;
    function _readText() {
      if (_text !== null) return _text;
      return _html + this._children.map(c => _readOf(c)).join("");
    }
    function _readOf(node) {
      if (!node) return "";
      if (typeof node._peekText === "function") return node._peekText();
      return node.innerHTML || "";
    }
    el._peekText = () => (_text !== null ? _text : _html);
    // title / placeholder / value 这类在真实 DOM 里与内容属性双向反射，
    // 桩里只存 JS 属性的话，代码写 btn.title 而判据读 getAttribute("title") 就永远读到 null。
    for (const reflected of ["title", "placeholder"]) {
      Object.defineProperty(el, reflected, {
        get() { return el._attrs[reflected] === undefined ? "" : el._attrs[reflected]; },
        set(v) { el._attrs[reflected] = String(v); },
      });
    }
    Object.defineProperty(el, "textContent", {
      get() { return _readText.call(el); },
      set(v) { _text = String(v); },
    });
    Object.defineProperty(el, "innerText", {
      get() { return _readText.call(el); },
      set(v) { _text = String(v); },
    });
    Object.defineProperty(el, "parentElement", { value: { clientWidth: 340 } });
    return el;
  }
  function mkEl(id) {
    // getElementById 走缓存（同一个 id 永远是同一个节点）
    if (!elems.has(id)) elems.set(id, newEl(id));
    return elems.get(id);
  }

  const muts = [];
  const win = {
    // 桩里的观察器只记账不自动派发，测试自己 flush，
    // 否则"背景被屏蔽"这类断言只能靠直接调函数糊过去。
    MutationObserver: class {
      constructor(cb) { this.cb = cb; }
      observe(target) { muts.push({ target, cb: this.cb }); }
    },
    location: { protocol: "http:", hostname: "app.test", origin: "http://app.test", hash: "", search: "" },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    AndroidBridge: {
      showToast(m) { log.toasts.push(String(m)); },
      vibrate(m) { log.vib++; },
      playBeep() {},
      launchApp() { return true; },
      openBrowser() {},
    },
    open() {},
  };
  win.window = win;
  const listeners = {};
  const docListeners = {};

  const sandbox = {
    window: win,
    // 浏览器里 MutationObserver 是全局对象，代码里不会写 window. 前缀，
    // 桩必须同样暴露全局名，否则测的是桩的形状而不是浏览器的形状。
    MutationObserver: win.MutationObserver,
    document: {
      getElementById: mkEl,
      querySelector: (s) => mkEl("q" + s),
      querySelectorAll: () => [],
      // 弹窗无障碍那段注册的是 document 级 keydown；桩以前没这个方法，
      // 加载 app.js 会直接抛 TypeError 并被 init 吞掉，变成"逻辑没跑"的假绿。
      addEventListener(ev, fn) { (docListeners[ev] = docListeners[ev] || []).push(fn); },
      activeElement: null,
      createElement: (t) => newEl("dyn-" + (++dynSeq) + ":" + t),
      body: {
        appendChild() {}, removeChild() {},
        // 把桩里出现过的元素都当作 body 的直接子节点；否则 syncDialogInert
        // 遍历到空数组，"背景被屏蔽"这条断言会永远绿却什么都没测到。
        get children() { return Array.from(elems.values()); },
        classList: {
          _s: new Set(),
          add(c) { this._s.add(c); },
          remove(c) { this._s.delete(c); },
          contains(c) { return this._s.has(c); },
          toggle(c, on) {
            if (on === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
            else { on ? this._s.add(c) : this._s.delete(c); }
          },
        },
      },
      execCommand() {},
    },
    navigator: { vibrate: () => true, clipboard: { writeText: () => Promise.resolve() } },
    localStorage: (() => { const t = {}; return {
      getItem: (k) => (k in t ? t[k] : null),
      setItem: (k, v) => { t[k] = String(v); },
      removeItem: (k) => { delete t[k]; },
    }; })(),
    setTimeout: (fn) => { try { fn(); } catch (e) {} return 0; },
    clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
      log.fetches.push([url, opts]);
      const h = sandbox.__fetchHandler;
      if (!h) throw new Error("no fetch handler");
      return h(url, opts);
    },
    alert: (m) => { log.alerts.push(String(m)); },
    console: { log() {}, warn(...a) { log.toasts.push("warn:" + a.join(" ")); }, error() {} },
    FormData: class { constructor() { this.f = {}; } append(k, v) { this.f[k] = v; } },
    FileReader: class { readAsDataURL() {} },
    Math, Number, String, Object, Array, JSON, Date, RegExp, Error, Promise, encodeURIComponent,
    Blob: class { constructor(parts) { this.parts = parts; } },
    URL: { createObjectURL: () => 'blob:fake', revokeObjectURL() {} },
    isNaN, parseInt, parseFloat, Set, Map,
  };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  return { context, log, sandbox, mkEl, elems, listeners, docListeners, muts };
}

function loadJs(context) {
  const src = MUTANT
    ? execFileSync("git", ["show", MUT_REF + ":" + JS_REL], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, JS_REL), "utf8");
  vm.runInContext(src, context, { filename: JS_REL });
  vm.runInContext("var localGuidanceRows="+fs.readFileSync(path.join(ROOT,"app/src/main/assets/guidance.json"),"utf8"),context);
}

// ------------------------------------------------------------------ 判据
const R = [];
const check = (name, ok, detail = "") => R.push([name, !!ok, String(detail).slice(0, 170)]);
const run = (ctx, code) => vm.runInContext(code, ctx);

const h = makeCtx();
loadJs(h.context);
const { log, sandbox } = h;

function okJson(obj) {
  return { ok: true, status: 200, json: async () => obj };
}
function failJson(status, detail) {
  return { ok: false, status, json: async () => ({ detail }) };
}

// ===== 1. 打卡失败绝不再播"成功" =====
run(h.context, `state.token="tk"; state.user={username:"u1"}; state.waterCupsCount=1;`);
sandbox.__fetchHandler = () => { throw new TypeError("Failed to fetch"); };

const writes = [
  ["体重", "saveWeight", `document.getElementById("input-weight").value="135";
                          document.getElementById("weight-unit").value="jin"; saveWeight();`],
  ["训练", "completeWorkoutToday", "completeWorkoutToday();"],
  ["饮食", "logNaturalMeal", `document.getElementById("input-meal-text").value="米饭";
                             logNaturalMeal();`],
  ["饮水", "toggleWaterCup", "toggleWaterCup(3);"],
  ["档案", "saveCustomProfile", `["prof-gender","prof-age","prof-height","prof-weight-jin",
      "prof-target-jin","prof-scene","prof-dining-mode"].forEach(i=>document.getElementById(i).value=
      i==="prof-age"?"26":i==="prof-height"?"165":i==="prof-weight-jin"?"140":i==="prof-target-jin"?"120":"takeout");
      saveCustomProfile();`],
  ["周期", "upgradeCyclePlan", `state.token="tk";document.getElementById("cycle-input-weight").value="133";
                               document.getElementById("cycle-input-waist").value="80";
                               upgradeCyclePlan();`],
];

for (const [label, fnName, setup] of writes) {
  log.toasts.length = 0;
  run(h.context, setup);
  vm.runInContext("new Promise(r=>r()).then(()=>0)", h.context);
}
// 上面同步触发的 promise 微任务需要一轮 drain
await new Promise(r => setImmediate(r));
await new Promise(r => setImmediate(r));

const allToasts = log.toasts.join(" | ");
check("断网时六类打卡都报失败", (log.toasts.filter(t => t.includes("没保存")).length) >= 6,
      `共 ${log.toasts.length} 条: ` + allToasts.slice(0, 150));
check("断网时没有任何一条谎称成功", !/打卡成功|已计入|已更新|记录成功/.test(allToasts), allToasts.slice(0, 150));

// ===== 2. 登录失效(401)要说清并拉回登录 =====
log.toasts.length = 0;
sandbox.__fetchHandler = (u) => Promise.resolve(failJson(401, "登录已失效，请重新登录"));
run(h.context, `document.getElementById("input-weight").value="135";
                document.getElementById("weight-unit").value="jin"; saveWeight();`);
await new Promise(r => setImmediate(r));
await new Promise(r => setImmediate(r));
check("401 提示登录失效", log.toasts.some(t => t.includes("登录已失效")), log.toasts.join(" | "));
check("401 不谎称成功", !log.toasts.some(t => /体重打卡成功/.test(t)), log.toasts.join(" | "));

// ===== 3. 成功路径仍走服务端原文 =====
log.toasts.length = 0;
sandbox.__fetchHandler = (u) => Promise.resolve(
  String(u).includes("/api/weight/log") ? okJson({ code: 0, msg: "云端已记录 135 斤" })
                                        : okJson({ metrics: { bmr: 1200, tdee: 1620, target_cal: 1500, rest_cal: 1450, workout_cal: 1620, deficit: 420, protein_g: 130, carbs_g: 150, fat_g: 42 }, profile: { height: 165, weight_jin: 135, goal_type: "tone", gender: "female", dining_mode: "takeout" }, today_consumed: 900, today_burned: 220, remaining_cal: 820, water_cups: 2, current_weight_jin: 135, today_meals: [], takeout_locked: false, consecutive_over_days: 0, consecutive_slacking_days: 0, latest_cycle: null, today_macros: { protein_g: 50, carbs_g: 90, fat_g: 25, total_cal: 800 }, weight_history: [], deficit_history: [] }));
run(h.context, `state.token="tk"; document.getElementById("input-weight").value="135";
                document.getElementById("weight-unit").value="jin"; saveWeight();`);
await new Promise(r => setImmediate(r));
await new Promise(r => setImmediate(r));
check("真成功时播报服务端原文", log.toasts.some(t => t.includes("云端已记录")), log.toasts.join(" | "));
check("成功后 dashboardLoaded 置真", run(h.context, "state.dashboardLoaded") === true, "");

// ===== 4. 外卖门禁：未登录 / 额度未知都不得谎称超标 =====
function gate(label, prep) {
  log.toasts.length = 0; log.alerts.length = 0;
  run(h.context, prep);
  run(h.context, `launchTakeoutApp("meituan")`);
  await0();
  return { toasts: log.toasts.slice(), alerts: log.alerts.slice() };
}
const await0 = () => {};

const g1 = gate("未登录", `state.token=null; state.dashboardLoaded=false; state.remainingCal=0;`);
check("未登录点外卖不弹超标警报", g1.alerts.length === 0, JSON.stringify(g1));
check("未登录改为引导登录", g1.toasts.some(t => /登录|注册/.test(t)), JSON.stringify(g1.toasts));

const g2 = gate("额度未知", `state.token="tk"; state.dashboardLoaded=false; state.remainingCal=0;`);
check("额度取不到时不判超标", g2.alerts.length === 0, JSON.stringify(g2));
check("额度取不到时如实说明", g2.toasts.some(t => /没|未|取不到|网络/.test(t)), JSON.stringify(g2.toasts));

const g3 = gate("真超标", `state.token="tk"; state.dashboardLoaded=true; state.remainingCal=-120;`);
check("真超标仍然拦截", g3.alerts.length === 1 && g3.alerts[0].includes("超标"), JSON.stringify(g3));
check("超标文案不再写'仅剩 0'", !/-?\d+ kcal/.test(g3.alerts[0]) || !/仅剩 -120/.test(g3.alerts[0]),
      g3.alerts[0]);

const g4 = gate("放行", `state.token="tk"; state.dashboardLoaded=true; state.remainingCal=500;`);
check("额度充足不拦截", g4.alerts.length === 0, JSON.stringify(g4));

// ===== 5. 宏量环：零记录不得凑出三等分假配比 =====
function drawMacros(macros) {
  log.arcs.length = 0; log.texts.length = 0;
  run(h.context, `state.realMacros = ${JSON.stringify(macros)}; drawMacrosChart();`);
  return { arcs: log.arcs.slice(), texts: log.texts.slice() };
}
const empty = drawMacros({ protein_g: 0, carbs_g: 0, fat_g: 0, total_cal: 0 });
check("零记录只画一圈灰环", empty.arcs.length === 1, JSON.stringify(empty.arcs));
check("零记录写明今日无记录", empty.texts.some(t => t.includes("今日无记录")), JSON.stringify(empty.texts));
check("零记录不再打'真实配比'假字", !empty.texts.some(t => t === "真实配比"), JSON.stringify(empty.texts));

const only1 = drawMacros({ protein_g: 100, carbs_g: 0, fat_g: 0, total_cal: 400 });
check("只记了蛋白时不再凭空出现三段", only1.arcs.length === 1, JSON.stringify(only1.arcs));

const three = drawMacros({ protein_g: 50, carbs_g: 90, fat_g: 25, total_cal: 800 });
if (three.arcs.length === 3) {
  const span = (a) => a[1] - a[0];
  const tot = [50 * 4, 90 * 4, 25 * 9];
  const sum = tot.reduce((x, y) => x + y, 0);
  const want = tot.map(v => v / sum * Math.PI * 2);
  const got = three.arcs.map(span);
  const worst = Math.max(...got.map((g, i) => Math.abs(g - want[i])));
  check("三段角度等于真实热量占比", worst < 0.02,
        "got=" + got.map(g => g.toFixed(3)) + " want=" + want.map(w => w.toFixed(3)));
  const nonePadded = got.every((g, i) => g > 0.01 || want[i] < 0.01);
  check("没有 10% 垫底痕迹", nonePadded, JSON.stringify(got));
} else {
  check("三段角度等于真实热量占比", false, "arc 段数=" + three.arcs.length);
  check("没有 10% 垫底痕迹", false, "");
}

// ===== 6. 净赤字：没记录时不显示数字 =====
function deficitText(loaded, consumed, burned, tdee) {
  log.texts.length = 0;
  run(h.context, `state.dashboardLoaded=${loaded}; state.todayConsumed=${consumed};
                  state.todayBurned=${burned}; state.remainingCal=${tdee - consumed + burned};
                  state.calculated={bmr:1200,tdee:${tdee},targetCal:${tdee - 420},restCal:${tdee - 470},
                    workoutCal:${tdee - 300},deficitTarget:420,proteinG:130,carbsG:150,fatG:42,summaryText:"x"};
                  state.mealDiary=[]; state.waterCupsCount=0; state.cycleData={};
                  renderDashboard();`);
  return String(run(h.context, `document.getElementById("net-deficit-val").innerText`));
}
const d0 = deficitText(false, 0, 0, 1620);
check("未同步时净赤字不给数字", d0.includes("暂无"), d0);
const d1 = deficitText(true, 0, 0, 1620);
check("同步了但没记录也不给数字", d1.includes("暂无"), d1);
const d2 = deficitText(true, 900, 220, 1620);
check("有记录时净赤字=940", d2.includes("940"), d2);

// ===== 7. 两颗快捷 chip 必须有真专答 =====
const chips = [
  ["平台期", "感觉体重在平台期不掉了怎么办？", ["平台期", "趋势"]],
  ["练后饿", "运动完晚上很饿能吃什么？", ["饿", "记录"]],
  ["补救", "今天不小心暴食了一顿怎么补救？", ["惩罚", "规律"]],
  ["火锅", "在外聚餐吃火锅该怎么点？", ["份量", "记录"]],
];
for (const [label, q, keys] of chips) {
  const ans = String(run(h.context, `generateAiResponse(${JSON.stringify(q)})`));
  const hit = keys.every(k => ans.includes(k));
  const isFallback = ans.includes("专属塑形顾问建议");
  check(`chip「${label}」拿到专答不是兜底`, hit && !isFallback, ans.replace(/\s+/g, " ").slice(0, 110));
}

// ===== 8. 公网大屏用户名不再当 HTML 插 =====
sandbox.__fetchHandler = () => Promise.resolve(failJson(404, "no"));
run(h.context, `loadPublicUserData("<img src=x onerror=alert(1)>").catch(()=>{});`);
await new Promise(r => setImmediate(r));
await new Promise(r => setImmediate(r));
const bannerHtml = String(run(h.context, `document.getElementById("user-web-link-card").innerHTML`));
check("大屏横幅不回显标签", !bannerHtml.includes("<img src=x onerror"), bannerHtml.slice(0, 140));
check("大屏横幅已转义", bannerHtml.includes("&lt;img"), bannerHtml.slice(0, 140));

// ------------------------------------------------------------------ 汇总
// ===== 9. profile 映射：目标体重不该再是 undefined / NaN =====
function feed(over) {
  const d = Object.assign({
    metrics: { bmr: 1500, tdee: 2118, target_cal: 1698, rest_cal: 1648, workout_cal: 1818,
               deficit: 420, protein_g: 148, carbs_g: 191, fat_g: 47 },
    profile: { gender: "male", age: 28, height: 175, weight_jin: 140, target_weight_jin: 120,
               goal_type: "male_v_taper", dining_mode: "takeout", scene: "home" },
    today_consumed: 900, today_burned: 220, today_macros: { protein: 56, carbs: 101, fat: 30 },
    remaining_cal: 1018, water_cups: 2, current_weight_jin: 140, today_meals: [],
    takeout_locked: false, consecutive_over_days: 0, consecutive_slacking_days: 0,
    over_cal_total: 0, start_weight_jin: 145, latest_cycle: null,
    takeout_stats: { intercepted: 0, blocked: 0, cancelled: 0, substituted: 0,
                     cal_saved: 0, fat_jin: 0, week_launched: 0, week_events: 0 },
    public_url: "http://124.220.54.64/u/x",
  }, over);
  run(h.context, `applyDashboardData(${JSON.stringify(d)})`);
}
const txt = (id) => String(run(h.context, `document.getElementById("${id}").innerText`));

feed({});
check("目标体重映射为数字(不再 undefined)", run(h.context, "state.profile.targetWeightJin") === 120, "");
check("身形 goalType 映射正确", run(h.context, "state.profile.goalType") === "male_v_taper", "");
check("体重 weightJin 映射正确", run(h.context, "state.profile.weightJin") === 140, "");
let st = txt("weight-status-text");
check("差值文案无 undefined/NaN", !/undefined|NaN/.test(st), st);
check("差值给出真实 20 斤", st.includes("20"), st);

feed({ current_weight_jin: 115 });
check("已达标时说明已达成", txt("weight-status-text").includes("已达到目标体重"), txt("weight-status-text"));

feed({ profile: { gender: "male", age: 28, height: 175, weight_jin: 140, target_weight_jin: 0,
                  goal_type: "male_v_taper", dining_mode: "takeout", scene: "home" } });
check("未设目标时提示去档案", txt("weight-status-text").includes("还没设置目标体重"), txt("weight-status-text"));

// ===== 10. 统计全部绑真实数据；没记录就是 0 =====
feed({});
check("拦截次数真实 0", txt("stat-intercept-count") === "0 次", txt("stat-intercept-count"));
check("少摄入真实 0", txt("stat-cal-saved") === "0", txt("stat-cal-saved"));
check("规避脂肪真实 0", txt("stat-fat-saved") === "0 斤", txt("stat-fat-saved"));
check("称号反映无记录", txt("medal-tag").includes("尚无"), txt("medal-tag"));
check("配额徽章改为真实点单数", txt("takeout-quota-badge").includes("本周点单 0 次"), txt("takeout-quota-badge"));

feed({ takeout_stats: { intercepted: 3, blocked: 1, cancelled: 2, substituted: 1, cal_saved: 1670,
                        fat_jin: 0.4, week_launched: 2, week_events: 5 } });
check("有记录时三颗给真实值",
  txt("stat-intercept-count") === "3 次" && txt("stat-cal-saved") === "1,670" && txt("stat-fat-saved") === "0.4 斤",
  [txt("stat-intercept-count"), txt("stat-cal-saved"), txt("stat-fat-saved")].join(" / "));
check("走势按真实首末体重计算", txt("chart-trend-tag").includes("已降 5"), txt("chart-trend-tag"));
check("起点 kg 绑真实记录", txt("chart-start-wt") === "72.5 kg", txt("chart-start-wt"));
check("缺口标签绑真实 deficit", txt("chart-deficit-target-label").includes("420"), txt("chart-deficit-target-label"));
check("宏量图例绑真实克数", txt("legend-protein").startsWith("148g"), txt("legend-protein"));
check("月减承诺按真实缺口折算", txt("kpi-cal-sub").includes("420 kcal"), txt("kpi-cal-sub"));

// ===== 11. 门禁事件真的上报 =====
const drain = async (n) => { for (let i = 0; i < (n || 8); i++) await new Promise(r => setImmediate(r)); };
function lastBody(urlPart) {
  const hit = log.fetches.filter(f => String(f[0]).includes(urlPart)).pop();
  if (!hit || !hit[1] || typeof hit[1].body !== "string") return null;
  try { return JSON.parse(hit[1].body); } catch (e) { return null; }
}
sandbox.__fetchHandler = () => Promise.resolve(okJson({ code: 0, msg: "ok" }));
run(h.context, `state.token="tk"; state.dashboardLoaded=true;`);

log.fetches.length = 0;
run(h.context, `state.remainingCal=-50; launchTakeoutApp("meituan")`);
await drain();
let ev = lastBody("/api/takeout/event");
check("被拦下上报 blocked", !!ev && ev.event_type === "blocked", JSON.stringify(ev));

log.fetches.length = 0;
run(h.context, `state.lastAudit={name:"隆江猪脚饭", cal:1180, subCal:490}; acceptSubstitute();`);
await drain();
ev = lastBody("/api/takeout/event");
check("采纳平替上报差额 690", !!ev && ev.event_type === "substitute" && ev.cal_avoided === 690, JSON.stringify(ev));

log.fetches.length = 0;
run(h.context, `cancelTakeoutOrder();`);
await drain();
ev = lastBody("/api/takeout/event");
check("主动退单上报 1180", !!ev && ev.event_type === "cancelled" && ev.cal_avoided === 1180, JSON.stringify(ev));

log.fetches.length = 0;
run(h.context, `forceEatTakeout();`);
await drain();
const eat = lastBody("/api/food/log");
check("坚持下单真的记一笔 1180", !!eat && eat.cal === 1180 && /猪脚饭/.test(eat.food_name || ""), JSON.stringify(eat));

log.fetches.length = 0;
run(h.context, `state.remainingCal=800; launchTakeoutApp("meituan")`);
await drain();
ev = lastBody("/api/takeout/event");
check("放行时上报 launched", !!ev && ev.event_type === "launched", JSON.stringify(ev));

// ===== 12. 顾问走后端、气泡转义、失败退回本地 =====
sandbox.__fetchHandler = () => Promise.resolve(
  okJson({ code: 0, source: "data", answer: "你最新记录的空腹体重是 <strong>140 斤</strong>", items: [] }));
run(h.context, `document.getElementById("chat-input").value="我多重"; sendChatMessage();`);
await drain();
const askCall = log.fetches.filter(f => String(f[0]).includes("/api/ask")).pop();
check("顾问请求 /api/ask", !!askCall && JSON.parse(askCall[1].body).question === "我多重", "");
check("气泡渲染后端答案", txt2().includes("140 斤"), txt2().slice(-140));

run(h.context, `document.getElementById("chat-input").value="<img src=x onerror=alert(1)>"; sendChatMessage();`);
await drain();
const b2 = txt2();
check("用户输入不被当标签执行", !b2.includes("<img src=x onerror"), b2.slice(-140));
check("用户输入被转义显示", b2.includes("&lt;img"), b2.slice(-140));

sandbox.__fetchHandler = () => { throw new TypeError("Failed to fetch"); };
run(h.context, `document.getElementById("chat-input").value="我多重"; sendChatMessage();`);
await drain();
const b3 = txt2();
check("查询失败明说并退回本地建议",
  b3.includes("两个引擎都没答上") && b3.includes("本地内置建议"), b3.slice(-180));
// 双引擎之后，失败必须把两边原因都摊开——只报一边等于把另一边的故障藏起来
check("失败时给出服务器侧原因", b3.includes("Failed to fetch"), b3.slice(-200));

function txt2() { return String(run(h.context, `document.getElementById("chat-messages-box").innerHTML`)); }

// ===== 13. 悬浮下载入口：App 内隐藏，网页版留白 =====
const hApp = makeCtx();
loadJs(hApp.context);
const hAppErrs = [];
(hApp.listeners["DOMContentLoaded"] || []).forEach(fn => { try { fn(); } catch (e) { hAppErrs.push(String(e && e.message)); } });
check("App 初始化不抛异常", hAppErrs.length === 0, hAppErrs.join(" / "));
const fl = hApp.sandbox.document.querySelector(".floating-dl-btn");
check("App 内隐藏悬浮下载", fl.style.display === "none", JSON.stringify(fl.style));

const hWeb = makeCtx();
delete hWeb.sandbox.window.AndroidBridge;
loadJs(hWeb.context);
const hWebErrs = [];
(hWeb.listeners["DOMContentLoaded"] || []).forEach(fn => { try { fn(); } catch (e) { hWebErrs.push(String(e && e.message)); } });
check("网页版初始化不抛异常", hWebErrs.length === 0, hWebErrs.join(" / "));
check("网页版给主内容留出底部空间",
  hWeb.sandbox.document.body.classList.contains("has-floating-dl"), "");
check("网页版仍显示悬浮下载", hWeb.sandbox.document.querySelector(".floating-dl-btn").style.display !== "none", "");


try {
// ===== 14. 本轮第三批：日子切换、动作要点、视图切换、导出、每日提醒 =====
// 静态判据必须与 --mutant 同源：变异模式下要读 HEAD 那份，否则永远绿
function srcOf(rel) {
  return MUTANT
    ? execFileSync("git", ["show", MUT_REF + ":" + rel], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, rel), "utf8");
}
const jsSrc = srcOf("app/src/main/assets/app.js");
const htmlSrc = srcOf("app/src/main/assets/index.html");
const cssSrc = srcOf("app/src/main/assets/style.css");

// 动作要点：32 条，每条 3 步 + 1 条常见错误
const exBlock = jsSrc.slice(jsSrc.indexOf("const EX_STEPS"), jsSrc.indexOf("function toggleExerciseSteps"));
const exKeys = [...exBlock.matchAll(/"[a-z_]+:\d":/g)].map(m => m[0]);
check("动作要点覆盖 32 个动作", exKeys.length === 32, exKeys.length);
const badSteps = [...exBlock.matchAll(/steps: \[([^\]]*)\]/g)].filter(m => (m[1].match(/", "/g) || []).length + 1 < 3);
check("每条要点至少 3 步", badSteps.length === 0, badSteps.length);
check("每条都写了常见错误", (exBlock.match(/wrong: "/g) || []).length === 32,
      (exBlock.match(/wrong: "/g) || []).length);
check("要点不含疗效承诺", !/立刻见效|一周瘦|月瘦\d+斤|保证/.test(exBlock), "");

// 渲染出的动作卡带两个按钮
sandbox.__fetchHandler = () => Promise.resolve(okJson({ code: 0 }));
run(h.context, `state.profile.gender="male"; state.profile.goalType="male_v_taper"; renderWorkoutExercises();`);
const exHtml = String(run(h.context, `document.getElementById("workout-exercises-card").innerHTML`));
check("动作卡有详情入口（原标准分解已升级为流程加示意动画）",
      exHtml.includes("动作流程与示意动画"), exHtml.slice(0, 160));
check("详情入口不取代只看要点", exHtml.includes("只看要点"), "");
check("动作卡有视频按钮", exHtml.includes("看演示视频"), "");
check("动作卡写明倒计时对应这 4 个动作", exHtml.includes("这 4 个动作"), exHtml.slice(0, 120));
check("要点已渲染进卡片", exHtml.includes("肩胛先下沉"), "");
run(h.context, `toggleExerciseSteps(0)`);
check("点开后要点容器加 open 类",
      run(h.context, `document.getElementById("ex-steps-0").classList.contains("open")`), "");

// 视频跳转：走原生桥，不内置声称
let opened = null;
sandbox.window.AndroidBridge.openBrowser = (u) => { opened = u; };
run(h.context, `openExerciseVideo(1)`);
check("视频按钮跳必应视频搜索", !!opened && opened.includes("bing.com/videos/search") &&
      encodeURIComponent("侧平举").slice(0, 6).length > 0, opened);
check("跳转前声明视频来自第三方",
      log.toasts.some(t => t.includes("第三方") && t.includes("不内置")), "");

// 日子切换真的打到后端
log.fetches.length = 0;
sandbox.__fetchHandler = (u) => Promise.resolve(okJson({ code: 0, day_mode: "workout" }));
run(h.context, `state.token="tk"; switchDayMode("workout", true)`);
await drain();
const modeCall = log.fetches.find(f => String(f[0]).includes("/api/profile/mode"));
check("切换日子调用 /api/profile/mode", !!modeCall && JSON.parse(modeCall[1].body).day_mode === "workout", "");

// 切换失败要回滚，不能留下"看着切了其实没切"
sandbox.__fetchHandler = () => { throw new TypeError("net down"); };
run(h.context, `state.mode="rest"; switchDayMode("workout", true)`);
await drain();
check("切换失败后 mode 回滚", run(h.context, "state.mode") === "rest", run(h.context, "state.mode"));
check("切换失败要说没保存", log.toasts.some(t => t.includes("没保存")), "");

// 每日状态入 state
feed({ today_workout_done: true, day_mode: "workout", checklist: { shop_0_1: true },
       water_target_ml: 2450, streak_days: 5, eta_days: 38, photo_due: true, cycle_day: 4,
       days_since_measure: 9 });
check("今日已练状态来自服务端", run(h.context, "state.workoutDoneToday") === true, "");
check("日子来自服务端", run(h.context, "state.dayMode") === "workout", "");
check("清单来自服务端", run(h.context, "state.checklistState.shop_0_1") === true, "");
check("饮水目标来自服务端", run(h.context, "state.waterTargetMl") === 2450, "");
check("连续天数上屏", txt("streak-days").includes("5"), txt("streak-days"));
check("达标预估上屏", txt("eta-days").includes("38"), txt("eta-days"));
check("周期进度按真实天数上屏", txt("cycle-day-text").includes("第 4 天"), txt("cycle-day-text"));
check("到期时提醒横幅显示",
      run(h.context, `document.getElementById("measure-due-banner").style.display`) === "flex", "");
check("提醒文案带真实间隔天数", txt("measure-due-text").includes("9 天"), txt("measure-due-text"));
feed({ photo_due: false, days_since_measure: 2 });
check("未到期时横幅隐藏",
      run(h.context, `document.getElementById("measure-due-banner").style.display`) === "none", "");
check("没数据时预估显示暂无足够数据", txt("eta-days").includes("暂无"), txt("eta-days"));

// 每日只提醒一次（注意：判据 stub 的必须是代码真正调用的那个方法。
// 原来 stub 的是 showNotification，代码换成 tryNotify 后这条读到 0，测的是旧接口）
let noteCount = 0;
sandbox.window.AndroidBridge.tryNotify = (a, b) => { noteCount++; return true; };
run(h.context, `state.token="tk"; try{localStorage.removeItem("QINGSU_NOTED_"+(state.user?state.user.username:"guest")+"_"+new Date().getFullYear()+"-"+(new Date().getMonth()+1)+"-"+new Date().getDate())}catch(e){}`);
run(h.context, `notifyOnceToday("测试","内容")`);
run(h.context, `notifyOnceToday("测试","内容")`);
check("同一天只提醒一次", noteCount === 1, noteCount);

// 通知发不出去（没权限）时必须改成页面内提醒，不能静默丢掉
sandbox.window.AndroidBridge.tryNotify = (a, b) => { return false; };
run(h.context, `try{localStorage.removeItem("QINGSU_NOTED_"+(state.user?state.user.username:"guest")+"_"+new Date().getFullYear()+"-"+(new Date().getMonth()+1)+"-"+new Date().getDate())}catch(e){}`);
run(h.context, `notifyOnceToday("该称重了","今天还没记录体重")`);
const inpage = txt("inpage-remind");
check("通知发不出时转为页面内提醒", inpage.includes("该称重了"), inpage.slice(0, 60));

// 外卖真实使用情况：未授权要说未授权，绝不能画成 0 次
sandbox.window.AndroidBridge.takeoutUsageToday = (pkgs) => null;
run(h.context, `refreshTakeoutUsage()`);
check("未授权显示未授权", txt("usage-state").includes("未授权"), txt("usage-state"));
check("未授权时不谎称 0 次", !txt("usage-detail").includes("0 次") || txt("usage-detail").includes("不会拿 0 次"), txt("usage-detail").slice(0,70));
check("未授权时给出授权入口", run(h.context, `document.getElementById("usage-grant-btn").style.display`) === "inline-block", "");

sandbox.window.AndroidBridge.takeoutUsageToday = (pkgs) => JSON.stringify({
    granted: true, since: 0,
    apps: [{pkg: "com.sankuai.meituan", launches: 3, foregroundMs: 245000},
           {pkg: "me.ele", launches: 1, foregroundMs: 60000}]});
run(h.context, `refreshTakeoutUsage()`);
check("授权后显示真实次数", txt("usage-state").includes("4 次"), txt("usage-state"));
check("真实次数按包拆开写", txt("usage-detail").includes("美团 打开 3 次") && txt("usage-detail").includes("饿了么 打开 1 次"), txt("usage-detail").slice(0,90));
check("前台时长折算成分钟", txt("usage-detail").includes("4 分钟"), txt("usage-detail").slice(0,90));

// 导出走带凭证的请求
log.fetches.length = 0;
log.clicks = 0;
sandbox.__fetchHandler = () => Promise.resolve({ ok: true, status: 200, text: async () => "a,b\n1,2" });
run(h.context, `exportMyData()`);
await drain();
const expCall = log.fetches.find(f => String(f[0]).includes("/api/export.csv"));
check("导出带 Authorization 头", !!expCall && /Bearer/.test(expCall[1].headers.Authorization || ""), "");
check("导出真的触发下载点击", (log.clicks || 0) >= 1, log.clicks);
run(h.context, `state.token=null; exportMyData()`);
await drain();
check("未登录导出会提示先登录", log.toasts.some(t => t.includes("请先登录")), "");

// 无照片走测量通道
log.fetches.length = 0;
sandbox.__fetchHandler = () => Promise.resolve(okJson({ code: 0, msg: "ok" }));
run(h.context, `state.token="tk";document.getElementById("cycle-input-weight").value="133";
                document.getElementById("cycle-input-waist").value="82";
                const fe=document.getElementById("file-cycle-photo-input"); fe.files=null;
                upgradeCyclePlan();`);
await drain();
check("没照片时提交到测量端点",
      log.fetches.some(f => String(f[0]).includes("/api/cycle/measure")),
      log.fetches.map(f => String(f[0])).join(","));

// 视图切换与顶部新结构
run(h.context, `applyViewMode("desktop")`);
check("桌面模式加上 desktop-view 类",
      sandbox.document.body.classList.contains("desktop-view"), "");
const vtTxt = txt2b("btn-view-toggle");
const vtTitle = String(run(h.context, `document.getElementById("btn-view-toggle").getAttribute("title")`));
// 按钮已按实拍反馈改成纯图标：文字不该再出现在按钮里，而应在 title 上
check("切换按钮只剩图标不含中文", !/[一-龥]/.test(vtTxt), vtTxt);
check("切换按钮说明挂在 title 上", vtTitle.includes("手机版"), vtTitle);
run(h.context, `applyViewMode("mobile")`);
check("切回手机模式时图标随之改变",
      txt2b("btn-view-toggle") !== vtTxt, vtTxt + " -> " + txt2b("btn-view-toggle"));
run(h.context, `applyViewMode("desktop")`);
run(h.context, `applyViewMode("mobile")`);
check("手机模式撤掉 desktop-view", !sandbox.document.body.classList.contains("desktop-view"), "");
function txt2b(id) { return String(run(h.context, `document.getElementById("${id}").innerText`)); }

check("首页有 header-row-1 结构", htmlSrc.includes('class="header-row-1"'), "");
check("档案摘要挂在品牌第二行（顶栏不再三层堆叠）",
      htmlSrc.includes('class="brand-profile"') && !htmlSrc.includes("header-profile-line"), "");
check("顶栏账号入口是头像圆点 + 昵称",
      htmlSrc.includes('class="account-chip"') && htmlSrc.includes('class="avatar-dot"'), "");
// 机主嫌"用户名那样展示好丑"：uqa1792267853 这类登录名不该出现在顶栏。
// 这里真的调用 displayName，不是查字符串在不在——名字取错时函数照样存在。
check("顶栏名字取昵称，没有昵称才退回登录名",
      String(run(h.context, "displayName({nickname:'小田',username:'uqa1792267853'})")) === "小田"
      && String(run(h.context, "displayName({username:'uqa1792267853'})")) === "uqa1792267853", "");
check("登录态不再把登录名直接写进顶栏",
      !jsSrc.includes("updateUserUI(state.user.username)"), "");
check("登录提示语也叫昵称而不是登录名",
      jsSrc.indexOf("欢迎回来，${escapeHtml(displayName(data))}") >= 0, "");
check("有视图切换按钮", htmlSrc.includes('id="btn-view-toggle"'), "");
check("有日子差异说明位", htmlSrc.includes('id="mode-diff-hint"'), "");
check("有每日状态条", htmlSrc.includes('class="daily-strip"'), "");
check("有拍摄标准指引", htmlSrc.includes("shoot-guide"), "");
check("桌面端不做面板级分栏",
      !/\.view-panel[^{]*\{[^}]*column-count/.test(cssSrc) && !/\.view-panel\.active[^{]*\{[^}]*grid-template-columns/.test(cssSrc),
      "还残留分栏");
check("没有规则让某个面板常驻显示",
      !/body\.desktop-view\s+#panel-[a-z-]+\s*\{[^}]*display:\s*block\s*!important/.test(cssSrc),
      "有面板被 !important 钉成永远显示——切 tab 它也压在别人上面");
check("标题不再是被挤的长句", /<h1>轻塑<\/h1>/.test(htmlSrc), "");
} catch (e) {
  check("本轮前端改动在该版本无法执行（等价于全红）", false, String(e && e.message));
}


// 共用守卫：被测版本缺某个函数时，把这一组判据逐条记红后跳过。
// 直接跑会抛 ReferenceError 把整个变异台带走（本轮踩过），
// 而 try/catch 一句带过又会把"没做到"洗成"没测"。
function needSymbols(list, names) {
  let missing = [];
  for (const n of names) {
    let t = "?";
    try { t = run(h.context, `typeof ` + n); } catch (e) { t = "throw:" + e.message; }
    if (t !== "function" && t !== "object") missing.push(n + "=" + t);
  }
  if (missing.length) {
    for (const nm of list) check(nm, false, "该版本缺少 " + missing.join(", "));
    return false;
  }
  return true;   // 返回 false 时调用方必须跳过整段，否则后面的 run() 会抛异常带走全表
}
// ============ 第五批后续：双引擎决策表（跑真 askAnyEngine，不另写一份逻辑） ============
// 手机上的原生推理这台机验不了（没 NDK、没设备），但"本地不行换服务器、服务器不行换本地"
// 这条切换逻辑是纯前端代码，可以用真的 askAnyEngine + 真的 fetch 桩跑出来。
{
    let calls = [];
    const realFetch = sandbox.__fetchHandler;
    const OK_LOCAL = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "本地答：按你的记录看没问题" } }] }) };
    const OK_CTX = { ok: true, status: 200, json: async () => ({ code: 0, digest: { weight_jin: 151, target_jin: 132, budget_cal: 1604, today_consumed: 620, today_burned: 220, remaining_cal: 1204, day_mode: "rest" }, memory: ["不吃香菜"], kb: [] }) };
    const OK_SRV = { ok: true, status: 200, json: async () => ({ code: 0, source: "web_model", answer: "服务器答：资料里这么说" }) };
    const OK_REC = { ok: true, status: 200, json: async () => ({ code: 0, stored: true }) };

    function install(mode) {
        calls = [];
        sandbox.__fetchHandler = (url, opts) => {
            calls.push((opts && opts.method ? opts.method : "GET") + " " + String(url).slice(0, 46));
            if (String(url).indexOf("/api/ai/context") >= 0) return Promise.resolve(OK_CTX);
            if (String(url).indexOf("/api/ai/record") >= 0) return Promise.resolve(OK_REC);
            if (String(url).indexOf("127.0.0.1") >= 0) {
                if (mode === "local_down") return Promise.reject(new TypeError("Failed to fetch"));
                if (mode === "local_bad") return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
                if (mode === "local_empty") return Promise.resolve({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "  " } }] }) });
                if (String(url).indexOf("/health") >= 0) return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
                return Promise.resolve(OK_LOCAL);
            }
            if (String(url).indexOf("/api/ask") >= 0) {
                if (mode === "server_down") return Promise.reject(new TypeError("server unreachable"));
                if(JSON.parse(opts.body).route_only)return Promise.resolve(okJson({code:0,source:"none",answer:""}));
                return Promise.resolve(OK_SRV);
            }
            return Promise.reject(new Error("unexpected " + url));
        };
    }

    function resetPref(p) {
        run(h.context, `state.token="engine-fixture";`);
        run(h.context, `try{localStorage.setItem("QINGSU_AI_ENGINE", ${JSON.stringify(p)})}catch(e){}`);
        run(h.context, `localAiCache.ok=null; localAiCache.at=0;`);
    }

    const ENGINE_NAMES = [
        "自动模式本地在线时走本地", "本地答案保存到本人私有记录", "本地引擎读服务器上下文（记忆共用）",
        "本地提示词带本人真实体重", "本地不通时降级到服务器", "本地返回 500 时降级到服务器",
        "本地返回空内容时降级到服务器", "只选本地时不偷偷走服务器", "报错要说清是本地不行",
        "只选服务器时不探本地端口", "只选服务器时走 /api/ask", "两引擎全挂时报错含本地原因",
        "两引擎全挂时报错含服务器原因", "本地探测结果被缓存复用",
    ];
    const ENGINE_SUITE = (async () => {
        if (!needSymbols(ENGINE_NAMES, ["askAnyEngine", "probeLocalAi", "localAiCache", "aiEnginePref"])) {
            return;
        }
        // A) 默认自动：本地在线就用本地，并把答案回写共享知识库
        install("ok"); resetPref("auto");
        let r = await run(h.context, `askAnyEngine("我多重")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("自动模式本地在线时走本地", r.engine === "local" && r.source === "local_model", r);
        check("本地答案保存到本人私有记录", calls.some(c => c.indexOf("/api/ai/record") >= 0), calls);
        check("本地引擎读服务器上下文（记忆共用）", calls.some(c => c.indexOf("/api/ai/context") >= 0), calls);
        check("本地提示词带本人真实体重",
              String(r.answer || "").length > 0 && calls.length >= 3, calls.length);

        // B) 本地挂了：自动降级到服务器，且不能谎称用了本地
        install("local_down"); resetPref("auto");
        r = await run(h.context, `askAnyEngine("喝黑咖啡会影响减脂吗")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("本地不通时降级到服务器", r.engine === "server" && !r.err, r);

        // C) 本地返回 500 / 空内容：都算本地失败，也要降级
        install("local_bad"); resetPref("auto");
        r = await run(h.context, `askAnyEngine("测试")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("本地返回 500 时降级到服务器", r.engine === "server", r);
        install("local_empty"); resetPref("auto");
        r = await run(h.context, `askAnyEngine("测试")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("本地返回空内容时降级到服务器", r.engine === "server", r);

        // D) 只用本地：本地挂了必须报错，绝不偷偷用服务器冒充本地
        install("local_down"); resetPref("local");
        r = await run(h.context, `askAnyEngine("测试")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("只选本地时不偷偷走服务器", !!r.err && !r.engine, r);
        check("报错要说清是本地不行", /本地/.test(String(r.err || "")), r.err);

        // E) 只用服务器：不该去探 127.0.0.1
        install("ok"); resetPref("server");
        r = await run(h.context, `askAnyEngine("测试")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("只选服务器时不探本地端口", !calls.some(c => c.indexOf("127.0.0.1") >= 0), calls);
        check("只选服务器时走 /api/ask", calls.some(c => c.indexOf("/api/ask") >= 0), calls);

        // F) 两个都不行：两边的原因都要摊出来，不能只报一边
        install("both_down"); resetPref("auto");
        calls = [];
        sandbox.__fetchHandler = (url) => Promise.reject(new TypeError("down:" + String(url).slice(-12)));
        r = await run(h.context, `askAnyEngine("测试")`).then(d => d, e => ({ err: String(e && e.message) }));
        await drain();
        check("两引擎全挂时报错含本地原因", /本地/.test(String(r.err || "")), r.err);
        check("两引擎全挂时报错含服务器原因", /服务器/.test(String(r.err || "")), r.err);

        // G) 探测结果要缓存，不能每问一句都重连一次 127.0.0.1
        install("local_down"); resetPref("auto");
        let probeCalls = 0;
        sandbox.__fetchHandler = (url, opts) => {
            if (String(url).indexOf("127.0.0.1") >= 0) probeCalls++;
            if (String(url).indexOf("/api/ask") >= 0) return Promise.resolve(OK_SRV);
            return Promise.reject(new TypeError("nope"));
        };
        await run(h.context, `askAnyEngine("第一问")`).then(() => {}, () => {}); await drain();
        await run(h.context, `askAnyEngine("第二问")`).then(() => {}, () => {}); await drain();
        check("本地探测结果被缓存复用", probeCalls <= 1, "探测次数=" + probeCalls);

        sandbox.__fetchHandler = realFetch;
        run(h.context, `try{localStorage.removeItem("QINGSU_AI_ENGINE")}catch(e){}`);
    })();
    // 必须 await：上一版没等它，14 条判据一条都没登记，判据总数纹丝不动却全绿
    await ENGINE_SUITE;
}



// ============ 第五批后续：网页独占功能（公网大屏专用） ============

const WEBONLY_NAMES = ["首页有网页独占工具卡", "工具卡默认隐藏（App 里不该出现）",
    "工具卡上有海报按钮", "海报按钮说明数据来自真实流水", "大屏开启自动刷新定时器",
    "刷新戳写明周期与时刻", "无数据时拒绝生成空海报"];
const HAS_WEBONLY = needSymbols(WEBONLY_NAMES, ["startPublicPolling", "makeProgressPoster", "stampPublicRefresh"]);
if (HAS_WEBONLY) {

// 这里取不到上面那个 htmlSrc（它声明在更早的嵌套作用域里），直接走顶层 srcOf()，
// 顺带保证 --mutant 下读的也是 HEAD 那一份。
const PUB_REL = "app/src/main/assets/index.html";
// 顶层看不到 srcOf()/htmlSrc（它们声明在更早的嵌套块里），这里自己取一次，
// 并且照样跟随 --mutant：静态判据读的必须是被测那一份，否则变异样本永远绿。
const pubHtml = MUTANT
  ? execFileSync("git", ["show", MUT_REF + ":" + PUB_REL], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
  : fs.readFileSync(path.join(ROOT, PUB_REL), "utf8");
check("首页有网页独占工具卡", pubHtml.includes('id="public-tools"'), "");
check("工具卡默认隐藏（App 里不该出现）",
      pubHtml.includes('id="public-tools" style="display:none;"'), "");
check("工具卡上有海报按钮", pubHtml.includes("makeProgressPoster()"), "");
check("海报按钮说明数据来自真实流水", pubHtml.includes("真实拉到的打卡流水"), "");

// 大屏轮询：真调 startPublicPolling，验它确实排了定时器并写出真实时间戳
let pollTimers = 0;
sandbox.setInterval = (fn, ms) => { pollTimers++; return 1; };
sandbox.clearInterval = () => {};
run(h.context, `window.__PUBLIC_USER__="someone"; startPublicPolling();stampPublicRefresh();`);
check("大屏开启自动刷新定时器", pollTimers >= 1, pollTimers);
const stampTxt = txt("public-refresh-stamp");
check("刷新戳写明周期与时刻", stampTxt.includes("30") && stampTxt.includes("上次"), stampTxt.slice(0, 60));

// 一条记录都没有时不许生成空海报
run(h.context, `state.weightHistory=[]; state.deficitHistory=[]; state.profile={};`);
run(h.context, `makeProgressPoster();`);
await drain();
check("无数据时拒绝生成空海报",
      log.toasts.some(t => String(t).includes("不生成空海报")), log.toasts.slice(-3));
}


// ============ 第五批后续：动作详情与程序化示意动画 ============

const ANIM_NAMES = ["首页有动作详情弹窗", "详情弹窗里有画布", "动画标明是程序化示意非真人",
    "动作要点条目仍是 32 条", "每个动作都认得出原型", "原型分布不是全塞进一类",
    "蹲姿两帧至少有 6 个关节发生位移", "支撑类动作只起伏不大动", "各原型全相位不出现反关节",
    "动作卡调用详情层而不是只展开文字", "身形 key 与要点表同源"];
const HAS_ANIM = needSymbols(ANIM_NAMES, ["poseAt", "detectArchetype", "EX_ARCHETYPES", "openExerciseDetail"]);
if (HAS_ANIM) {

const exHtmlTop = fs.readFileSync(path.join(ROOT, "app/src/main/assets/index.html"), "utf8");
check("首页有动作详情弹窗", exHtmlTop.includes('id="ex-detail-modal"'), "");
check("详情弹窗里有画布", exHtmlTop.includes('id="ex-detail-canvas"'), "");
check("动画标明是程序化示意非真人", exHtmlTop.includes("不是真人示范视频"), "");

// 32 个动作都要能认出原型，且认不出时要回落而不是瞎编
const archRes = run(h.context, `(function(){
  var keys = Object.keys(EX_STEPS);
  var out = {n: keys.length, bad: [], arch: {}};
  for (var i=0;i<keys.length;i++){
    var m = EX_STEPS[keys[i]];
    var a = detectArchetype(m, {name: keys[i], tip: ""});
    if (!EX_ARCHETYPES[a]) out.bad.push(keys[i]+":"+a);
    out.arch[a] = (out.arch[a]||0)+1;
  }
  return JSON.stringify(out);
})()`);
const AR = JSON.parse(archRes);
check("动作要点条目仍是 32 条", AR.n === 32, AR.n);
check("每个动作都认得出原型", AR.bad.length === 0, AR.bad);
check("原型分布不是全塞进一类", Object.keys(AR.arch).length >= 5, AR.arch);

// 动画必须真在动：不同相位的关键帧坐标要有位移，否则就是一张静图冒充动画
const frameRes = run(h.context, `(function(){
  var a = poseAt("squat", 0), b = poseAt("squat", 0.5);
  var moved = 0;
  for (var k in a) { if (Math.abs(a[k][1]-b[k][1]) > 0.005 || Math.abs(a[k][0]-b[k][0]) > 0.005) moved++; }
  // 取四分之一相位：plank 的起伏是正弦，挑 t=0 与 t=0.5 两个过零点会量到位移 0，
  // 那是测试取点错，不是动作没动
  var c = poseAt("plank", 0), d2 = poseAt("plank", 0.25);
  var pelvisMoved = Math.abs(c.pelvis[1]-d2.pelvis[1]);
  return JSON.stringify({moved: moved, pelvisMoved: pelvisMoved});
})()`);
const FR = JSON.parse(frameRes);
check("蹲姿两帧至少有 6 个关节发生位移", FR.moved >= 6, FR);
check("支撑类动作只起伏不大动",
      FR.pelvisMoved > 0.005 && FR.pelvisMoved < 0.05, JSON.stringify(FR));

// 关节不许反折：膝/肘夹角不得翻到反向（这是"示意动画"最基本的合理性）
const jointRes = run(h.context, `(function(){
  var bad = [];
  var archs = Object.keys(EX_ARCHETYPES);
  for (var i=0;i<archs.length;i++){
    for (var t=0;t<=1.001;t+=0.1){
      var p = poseAt(archs[i], t);
      if (p.knee_below_hip !== true) { }
      if (p.l_ankle[1] < p.l_knee[1] - 0.02 && archs[i] !== "bridge" && archs[i] !== "pushup") bad.push(archs[i]+"@"+t.toFixed(1)+":ankle above knee");
      if (p.l_knee[1] < p.l_hip[1] - 0.28) bad.push(archs[i]+"@"+t.toFixed(1)+":knee past hip");
    }
  }
  return JSON.stringify(bad.slice(0,6));
})()`);
const JB = JSON.parse(jointRes);
check("各原型全相位不出现反关节", JB.length === 0, JB);


const jsSrcForEx = fs.readFileSync(path.join(ROOT, "app/src/main/assets/app.js"), "utf8");
check("动作卡调用详情层而不是只展开文字",
      jsSrcForEx.includes("openExerciseDetail(${idx})"), "");
check("身形 key 与要点表同源", jsSrcForEx.includes("window.__currentExKey = key;"), "");
// 真数据姿态表：32 条都要能取到，插值后骨长不能漂
const POSE_SRC = fs.readFileSync(path.join(ROOT, "app/src/main/assets/exercise_poses.json"), "utf8");
const POSES = JSON.parse(POSE_SRC);
check("姿态表覆盖 32 个动作", Object.keys(POSES).length === 32, Object.keys(POSES).length);
const poseBad = [];
for (const k of Object.keys(POSES)) {
  const f = POSES[k].frames;
  if (!Array.isArray(f) || f.length < 2) { poseBad.push(k + ":帧数" + (f||[]).length); continue; }
  for (const fr of f) {
    const need = ["head","neck","sternum","pelvis","l_shoulder","l_elbow","l_wrist","r_shoulder","r_elbow","r_wrist","l_hip","r_hip","l_knee","r_knee","l_ankle","r_ankle"];
    for (const jn of need) if (!fr.pose || !Array.isArray(fr.pose[jn])) { poseBad.push(k + ":" + jn + " 缺"); }
  }
}
check("每帧 16 个关节齐全且帧数够", poseBad.length === 0, poseBad.slice(0, 4));
check("姿态表已接进渲染器", jsSrcForEx.includes("poseFromTable(poseKey, arch, t)"), "");
check("取不到姿态表时回落程序化而不是画静图",
      jsSrcForEx.includes("return poseAt(arch, t);"), "");

// 火柴人不许被裁：三种屏宽 × 32 个动作 × 全相位，逐帧记下每个落笔坐标，
// 只要有一个出界就是红。上一版"人被裁掉一半"正是取景按当前帧算出来的，
// 光看源码里"有没有留 padding"证明不了没裁，所以这里真跑 drawFrame。
run(h.context, `EX_POSES = ${POSE_SRC}`);
const STICK_CLIP = run(h.context, `(function(){
  var keys = Object.keys(EX_POSES), bad = [], thin = [], seen = {};
  var sizes = [[288,288],[324,324],[440,340]];
  function mkctx(pts, colors, body) {
    // pts 收全部落笔点（出界判据用它）；body 只收人形本身的点（占幅判据用它）。
    // 背景矩形和地面/垫子不属于人，混进 body 就会永远"占满画面"，判据失效。
    var ground = false, inGround = false;
    body = body || [];
    return {
      clearRect: function(){ ground = true; }, save: function(){}, restore: function(){},
      beginPath: function(){}, closePath: function(){},
      stroke: function(){ colors.push(this.strokeStyle); },
      fill: function(){ colors.push(this.fillStyle); },
      moveTo: function(x, y){
        pts.push([x, y]);
        if (ground) inGround = true;
        else body.push([x, y]);
      },
      lineTo: function(x, y){
        pts.push([x, y]);
        if (inGround) { inGround = false; ground = false; return; }
        body.push([x, y]);
      },
      arc: function(x, y, r){ body.push([x - r, y - r], [x + r, y - r], [x - r, y + r], [x + r, y + r]); },
      fillRect: function(x, y, w, h){ pts.push([x, y], [x + w, y + h]); },
      createLinearGradient: function(){ return { addColorStop: function(){} }; },
      strokeStyle: "", fillStyle: "", lineWidth: 0, lineCap: "", lineJoin: ""
    };
  }
  for (var ki = 0; ki < keys.length; ki++) {
    var k = keys[ki];
    var arch = detectArchetype(EX_STEPS[k] || {}, { name: EX_POSES[k].name });
    seen[arch] = 1;
    for (var si = 0; si < sizes.length; si++) {
      var W = sizes[si][0], H = sizes[si][1], colors = [];
      var span = { minX: 1e9, minY: 1e9, maxX: -1e9, maxY: -1e9 };
      for (var q = 0; q < 10; q++) {
        var t = q / 10, pts = [];
        var body = [];
        var g2 = mkctx(pts, colors, body);
        drawFrame(g2, W, H, poseFromTable(k, arch, t), arch, t, k);
        for (var pi = 0; pi < pts.length; pi++) {
          var p = pts[pi];
          if (!isFinite(p[0]) || !isFinite(p[1]) || p[0] < -1 || p[0] > W + 1 || p[1] < -1 || p[1] > H + 1) {
            bad.push(k + " " + W + "x" + H + " t=" + t.toFixed(1) + " 出界 " + Math.round(p[0]) + "," + Math.round(p[1]));
          }
        }
        for (var bi = 0; bi < body.length; bi++) {
          span.minX = Math.min(span.minX, body[bi][0]); span.maxX = Math.max(span.maxX, body[bi][0]);
          span.minY = Math.min(span.minY, body[bi][1]); span.maxY = Math.max(span.maxY, body[bi][1]);
        }
      }
      // 人形必须真占住画面：取景框一旦被写死成整张画布，线条全部落在里面、
      // "不出界"照样绿，但手机上看到的就是缩在中间的一小条。这条单独计，
      // 红的时候才分得清是"裁了"还是"缩了"。
      var fracW = (span.maxX - span.minX) / W, fracH = (span.maxY - span.minY) / H;
      if (Math.max(fracW, fracH) <= 0.45) {
        thin.push(k + " " + W + "x" + H + " 人形只占宽 " + fracW.toFixed(2) + " 高 " + fracH.toFixed(2));
      }
      // 正视动作左右等权；矢状面才把背向镜头那一侧画淡。画淡色只允许出现在矢状面。
      var far = colors.indexOf("#A9B7C6") >= 0;
      if (EX_POSES[k].plane === "frontal" && far) bad.push(k + " 正视动作出现了淡色远侧肢体");
      if (EX_POSES[k].plane === "sagittal" && !far) bad.push(k + " 矢状面动作没区分远近侧");
    }
  }
  var litBad = [];
  Object.keys(ACTIVE_MUSCLES).forEach(function(a){
    var pts = [], colors = [];
    drawFrame(mkctx(pts, colors), 300, 300, poseFromTable(keys[0], a, 0.2), a, 0.2, keys[0]);
    if (colors.indexOf("#059669") < 0) litBad.push(a);
  });
  return { bad: bad.slice(0, 8), n: bad.length, thin: thin.slice(0, 8), tn: thin.length,
           poses: keys.length, litBad: litBad, archs: Object.keys(seen).length };
})()`);
check("32 个动作在三种屏宽下都没有被裁", STICK_CLIP.n === 0,
      `${STICK_CLIP.n} 处出界: ` + JSON.stringify(STICK_CLIP.bad));
check("32 个动作都占住画面一半以上，没缩成一小条", STICK_CLIP.tn === 0,
      `${STICK_CLIP.tn} 处过窄: ` + JSON.stringify(STICK_CLIP.thin));
check("动作覆盖到 11 类以上原型", STICK_CLIP.archs >= 11, STICK_CLIP.archs);
check("每个发力肌群标签都真有一根线段会亮", STICK_CLIP.litBad.length === 0,
      JSON.stringify(STICK_CLIP.litBad));

// 取景框必须包住这组动作每一帧的每个关节。上一版"人被裁掉一半"就是因为取景
// 按当前帧算；光在源码里钉一句"读了 e.frames"证明不了包得住，这里真量坐标。
try {
  const BOX = run(h.context, `(function(){
    var out = [], keys = Object.keys(EX_POSES);
    for (var ki = 0; ki < keys.length; ki++) {
      var k = keys[ki], b = stickBox(k, detectArchetype(EX_STEPS[k] || {}, { name: EX_POSES[k].name }));
      var f = EX_POSES[k].frames, n = 0;
      // 期望框：这组动作全部帧全部关节的并集。框必须正好等于它——
      // 只要求"包住"的话，把框写死成整张画布也能绿，人缩成一小条却没人报警。
      var u = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
      for (var i = 0; i < f.length; i++) {
        for (var jn in f[i].pose) {
          var p = f[i].pose[jn];
          if (p[0] < b.minX - 1e-6 || p[0] > b.maxX + 1e-6 || p[1] < b.minY - 1e-6 || p[1] > b.maxY + 1e-6) n++;
          u.minX = Math.min(u.minX, p[0]); u.maxX = Math.max(u.maxX, p[0]);
          u.minY = Math.min(u.minY, p[1]); u.maxY = Math.max(u.maxY, p[1]);
        }
      }
      if (n) out.push(k + " 有 " + n + " 个关节在框外，实得框 " + [b.minX, b.maxX, b.minY, b.maxY]
                       + " 期望 " + [u.minX, u.maxX, u.minY, u.maxY]);
      else if (Math.abs(b.minX - u.minX) > 1e-6 || Math.abs(b.maxX - u.maxX) > 1e-6
            || Math.abs(b.minY - u.minY) > 1e-6 || Math.abs(b.maxY - u.maxY) > 1e-6)
        out.push(k + " 框没贴住身体 期望 " + [u.minX, u.maxX, u.minY, u.maxY] + " 实得 " + [b.minX, b.maxX, b.minY, b.maxY]);
    }
    return { bad: out.slice(0, 5), n: out.length, total: keys.length };
  })()`);
  check("取景框等于全部帧关节的并集（既不漏也缩）", BOX.n === 0 && BOX.total === 32, JSON.stringify(BOX.bad));
} catch (e) {
  check("取景框等于全部帧关节的并集（既不漏也缩）", false, "取景函数没跑起来: " + String(e && e.message).slice(0, 70));
}
}




// ============ r146：忌口与城市真的改变了推荐，而不是摆设 ============
const AVOID_BLOCK = (function () {
  try {
    return run(h.context, `(function(){
      var out = {rules: {}, hidden: 0, localHit: 0, order: []};
      // 每条规则单独开：必须至少咬到一道，又不能把九道全咬掉（全咬等于这个开关没有意义）
      Object.keys(AVOID_RULES).forEach(function (k) {
        if (!AVOID_RULES[k]) return;
        var hit = Object.keys(TAKEOUT_DB).filter(function (n) { return dishConflicts(n, [k]).length; });
        out.rules[k] = hit.length;
      });
      var all = Object.keys(AVOID_RULES).filter(function (k) { return AVOID_RULES[k]; });
      var allHit = Object.keys(TAKEOUT_DB).filter(function (n) { return dishConflicts(n, all).length; });
      out.allHit = allHit.length;
      out.total = Object.keys(TAKEOUT_DB).length;
      // 排序层：设成"不吃辣 + 成都"，冲突项必须排到后面但**仍在列表里**
      accountData = function () { return { avoid_tags: ["no_spicy"], cuisines: ["川菜", "辣"], city: "成都" }; };
      var r = rankTakeout();
      out.order = r.map(function (x) { return x.name; });
      out.firstBad = r.findIndex(function (x) { return x.bad.length; });
      out.lastClean = r.map(function (x) { return x.bad.length ? -1 : 1; }).lastIndexOf(1);
      out.localHit = r.filter(function (x) { return x.local; }).length;
      // 替代项自己也可能与忌口冲突，必须如实标出来而不是推荐一个用户不能吃的
      var la = r.filter(function (x) { return x.name.indexOf("麻辣烫") >= 0; })[0];
      out.subBad = !!(la && la.subBad.length);
      return out;
    })()`);
  } catch (e) {
    return { error: String(e && e.message).slice(0, 80) };
  }
})();
if (AVOID_BLOCK.error) {
  check("每条忌口规则都真能咬到菜", false, "跑不起来: " + AVOID_BLOCK.error);
  check("忌口不会把所有爆款全判死", false, "同上");
  check("排序把冲突项排到后面但不藏起来", false, "同上");
  check("当地菜系真的点亮了至少一道", false, "同上");
  check("替代项自己撞忌口时会标出来", false, "同上");
} else {
  const bites = Object.entries(AVOID_BLOCK.rules).filter(([, n]) => n === 0).map(([k]) => k);
  check("每条忌口规则都真能咬到菜", bites.length === 0, "咬不到任何菜的规则: " + JSON.stringify(bites));
  check("忌口不会把所有爆款全判死", AVOID_BLOCK.allHit < AVOID_BLOCK.total,
        [AVOID_BLOCK.allHit, AVOID_BLOCK.total]);
  check("排序把冲突项排到后面但不藏起来",
        AVOID_BLOCK.firstBad > AVOID_BLOCK.lastClean && AVOID_BLOCK.order.length === AVOID_BLOCK.total,
        [AVOID_BLOCK.firstBad, AVOID_BLOCK.lastClean, AVOID_BLOCK.order.length]);
  check("当地菜系真的点亮了至少一道", AVOID_BLOCK.localHit >= 1, AVOID_BLOCK.localHit);
  check("替代项自己撞忌口时会标出来", AVOID_BLOCK.subBad === true, AVOID_BLOCK.subBad);
}

// ============ 第六批补：下载弹窗不许有写死的版本与体积 ============
const DL_NAMES = ["下载弹窗无写死体积","下载弹窗无写死版本号","版本与体积改为待填占位",
    "清单读不到时显示未知而不是回落假数","下载文件名带真实版本","不再宣称高速直链"];
const DLN = DL_NAMES;
const dlHtml = MUTANT
  ? execFileSync("git", ["show", MUT_REF + ":app/src/main/assets/index.html"], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
  : fs.readFileSync(path.join(ROOT, "app/src/main/assets/index.html"), "utf8");
const dlJs = MUTANT
  ? execFileSync("git", ["show", MUT_REF + ":app/src/main/assets/app.js"], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
  : fs.readFileSync(path.join(ROOT, "app/src/main/assets/app.js"), "utf8");
if (!/loadApkMeta/.test(dlJs)) {
  for (const nm of DLN) check(nm, false, "该版本没有对应实现");
} else {
  check("下载弹窗无写死体积", !/\(\s*5\.5MB\s*\)/.test(dlHtml) && !/安装包 \(\d/.test(dlHtml),
        (dlHtml.match(/安装包 \([^)]*\)/) || [""])[0]);
  check("下载弹窗无写死版本号", !/v5\.0/.test(dlHtml), (dlHtml.match(/v5\.0[^<"]{0,14}/g) || []).slice(0,3));
  check("版本与体积改为待填占位", dlHtml.includes("版本待读取") && !dlHtml.includes("apk-size-line")
    && dlHtml.includes("apk-ver-line"), "");
  check("清单读不到时显示未知而不是回落假数",
        dlJs.includes("版本未知") && dlJs.includes("体积未知"), "");
  check("下载文件名带真实版本",
        dlJs.includes("setAttribute") && dlJs.includes("轻塑_") && dlJs.includes("version_code"), "");
  check("不再宣称高速直链", !/高速直链/.test(dlHtml), (dlHtml.match(/.{0,10}直链/) || [""])[0]);
}


// ============ 第七批：网页端独占工作台 ============
const WB_NAMES = ["工作台只在网页出现","App 里整块移除","目标日倒推算得出真数字",
    "身体数据缺失时拒绝倒推不猜数","倒推不安全时判做不到","流水表能解析分节CSV",
    "流水表筛选生效","周复盘写明0是未记录而非零缺口","打印样式只留复盘页","工作台无未量过承诺"];
const WB_HTML = fs.readFileSync(path.join(ROOT, "app/src/main/assets/index.html"), "utf8");
const WB_JS = fs.readFileSync(path.join(ROOT, "app/src/main/assets/app.js"), "utf8");
check("工作台只在网页出现", WB_HTML.includes('id="web-workbench"'), "");
check("App 里整块移除", WB_JS.includes("host.remove()") && WB_JS.includes("inApp()"), "");
check("工作台无未量过承诺", !/毫秒级|绝对隐私|永久免费|高速直链/.test(WB_HTML.slice(WB_HTML.indexOf("web-workbench"), WB_HTML.indexOf("web-workbench") + 4000)), "");

// 关键：真调 planByTargetDate 并断言它算出数字。
// 之前我用了个从没被写过的 state.metricsCache，功能会永远走「数据不足」却看不出来。
run(h.context, `state.currentWeightJin=151; state.profile={targetWeightJin:132, weightJin:151};`
    + ` state.calculated={tdee:2024,bmr:1499,restCal:1604,workoutCal:1774};`
    + ` document.getElementById("wb-target-jin").value="132";`
    + ` var d=new Date(Date.now()+120*86400000);`
    + ` document.getElementById("wb-target-date").value=d.toISOString().slice(0,10);`
    + ` planByTargetDate();`);
const planTxt = txt("wb-plan-out").replace(/<[^>]+>/g, "");
check("目标日倒推算得出真数字", /还剩\s*\d+\s*天/.test(planTxt) && /周变化/.test(planTxt) && /\d+/.test(planTxt), planTxt.slice(0, 150));
check("日期算术不承诺可行性或进食量",
      /不能据此判断目标可行性/.test(planTxt), planTxt.slice(0, 90));

// 身体数据缺失时必须拒绝，不能拿默认值凑
run(h.context, `state.currentWeightJin=0; state.profile={}; state.calculated={};`
    + ` planByTargetDate();`);
const planEmpty = txt("wb-plan-out");
check("身体数据缺失时拒绝倒推不猜数",
      planEmpty.includes("不替你猜") || planEmpty.includes("填真实值"), planEmpty.slice(0, 90));

// 导出 CSV 是分节的，解析要能归类并支持筛选
const LF2 = String.fromCharCode(10);
const csv = ["表,日期,项目,数值,备注",
  "饮食,2026-10-16,牛肉面,620,午餐",
  "饮食,2026-10-16," + String.fromCharCode(34) + "一个肉包子，一个鸡蛋" + String.fromCharCode(34) + ",80,早餐",
  "体重,2026-10-16,空腹体重,151,"].join(LF2);
run(h.context, `wbRows = parseCsv(${JSON.stringify(csv)});`
    + ` document.getElementById("wb-search").value="";`
    + ` document.getElementById("wb-kind").value="饮食";`
    + ` document.getElementById("wb-over").checked=false;`
    + ` renderLedger();`);
const led = txt("wb-ledger");
check("流水表能解析真实平表CSV并按类筛选", /共 2 笔/.test(led.replace(/<[^>]+>/g, "")), led.slice(0, 120));
check("含逗号带引号的字段不被切错", led.replace(/<[^>]+>/g, "").includes("一个肉包子，一个鸡蛋"), led.slice(0, 140));
run(h.context, `document.getElementById("wb-over").checked=true; renderLedger();`);
const led2 = txt("wb-ledger");
check("流水表筛选生效", /共 1 笔/.test(led2.replace(/<[^>]+>/g, "")), led2.slice(0, 120));

// 周复盘：0 缺口必须解释成「当天没记」，不能让人以为真的零缺口
run(h.context, `state.deficitHistory=[{date:"10-15",deficit:0,consumed:0,burned:0},`
    + ` {date:"10-16",deficit:420,consumed:1200,burned:160}];`
    + ` state.weightHistory=[{date:"10-15",jin:152},{date:"10-16",jin:151}];`
    + ` state.streakDays=3; state.user={username:"tester"};`
    + ` renderWeeklyReport();`);
const rpt = txt("wb-report");
check("周复盘写明0是未记录而非零缺口", rpt.includes("当天一笔未记"), rpt.slice(0, 120));
const WB_CSS = fs.readFileSync(path.join(ROOT, "app/src/main/assets/style.css"), "utf8");
check("打印样式只留复盘页",
      WB_CSS.includes("@media print") && WB_CSS.includes("printing-report")
      && WB_CSS.includes("#wb-report"), "");

// ============ r124 第八批：审另一个 Agent 交付的四个提交 ============
// 每条都对应一次实测抓到的缺陷（那位 Agent 的提交说明里声称"已修复"的正是这些）。
{
  // 判据用的 srcOf 在那个块里是块级作用域，这里自己再开一份，同样按 --mutant 取源
  const pick = (rel) => MUTANT
    ? execFileSync("git", ["show", MUT_REF + ":" + rel], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, rel), "utf8");
  const rHtml = pick("app/src/main/assets/index.html");
  const rJs = pick("app/src/main/assets/app.js");
  const rCss = pick("app/src/main/assets/style.css");
  const val = (id) => String(run(h.context,
    `(function(){var e=document.getElementById(${JSON.stringify(id)});`
    + `return String((e&&((e.textContent||"")+ "| " + (e.innerText||"")))||"");})()`));

  // 1) 电脑版顶栏：那颗按钮点的面板必须真的存在——旧版有两颗点了会把整屏清空
  const dTabs = [...rHtml.matchAll(/class="d-nav-item[^"]*"\s+data-tab="([^"]+)"/g)].map(m => m[1]);
  check("顶栏按钮数量符合预期", dTabs.length >= 6, dTabs);
  const dMissing = dTabs.filter(t => !rHtml.includes(`id="panel-${t}"`));
  check("顶栏每颗按钮都有对应面板", dMissing.length === 0, "缺面板: " + JSON.stringify(dMissing));
  const mTabs = [...rHtml.matchAll(/class="nav-item[^"]*"[^>]*onclick="switchTab\('([^']+)'\)/g)].map(m => m[1]);
  check("底部导航也都指向存在的面板",
        mTabs.filter(t => !rHtml.includes(`id="panel-${t}"`)).length === 0,
        JSON.stringify(mTabs.filter(t => !rHtml.includes(`id="panel-${t}"`))));

  // 2) CSS 里点不存在的面板＝那条排版规则永远不生效（#panel-ai 就是这一类）
  const cssPanels = [...new Set([...rCss.matchAll(/#panel-([a-z-]+)/g)].map(m => m[1]))];
  const cssMissing = cssPanels.filter(t => !rHtml.includes(`id="panel-${t}"`));
  check("样式引用的面板 id 都真实存在", cssMissing.length === 0,
        "样式点了不存在的面板: " + JSON.stringify(cssMissing));

  // 3) 窄屏媒体查询：旧版改的是 grid-template-columns，而那时元素是 block + column-count，规则恒不生效
  check("窄屏身材库仍收得住", /@media \(max-width: 900px\)[\s\S]{0,300}#main-body-shapes-grid[^}]*repeat\(2/.test(rCss),
        rCss.slice(rCss.indexOf("@media (max-width: 900px)"), rCss.indexOf("@media (max-width: 900px)") + 160));

  // 4) 自律矩阵：三处都得对，否则首屏永远是一片灰格子
  const syncBody = rJs.slice(rJs.indexOf("async function syncRemoteDashboard"),
                             rJs.indexOf("async function syncRemoteCharts"));
  check("矩阵渲染排在数据到位之后",
        /applyDashboardData\(data\);\s*\n\s*renderHabitMatrix\(\);/.test(syncBody), syncBody.slice(-150));
  const matAt = rJs.indexOf("async function renderHabitMatrix");
  const matBody = matAt < 0 ? "" : rJs.slice(matAt, matAt + 1500);
  check("矩阵按本地历法铺日期",
        /new Date\(now\.getFullYear\(\), now\.getMonth\(\), now\.getDate\(\) - i\)/.test(matBody),
        matBody.slice(0, 130));
  check("矩阵向后端要满 30 天", matBody.includes("/api/habits"), matBody.slice(0, 90));
  check("矩阵取数失败会在屏上说原因",
        matBody.includes("矩阵没取到数据") && rCss.includes(".wb-habit-empty"), "");

  // 5) 访客打气：计数必须来自服务端
  check("打气不再拿本机 localStorage 充当人数", !rJs.includes("qingsu_cheers"), "");
  const cheerAt = rJs.indexOf("async function sendCheerSticker");
  const cheerBody = cheerAt < 0 ? "" : rJs.slice(cheerAt, cheerAt + 1200);
  check("打气真的发到服务端", cheerBody.includes('postApi("/api/cheer"') && cheerBody.includes("publicShareKey()"),
        cheerBody.slice(0, 120));
  check("打气失败要说没送出去而不是成功", cheerBody.includes("这枚没送出去"), cheerBody.slice(-150));

  // 6) 分享链接：服务端认了 k，前端拉公开 API 也必须带上，否则整屏空白
  const pubDash = rJs.match(/\/api\/public\/dashboard[^;]*/g) || [];
  const pubCharts = rJs.match(/\/api\/public\/charts[^;]*/g) || [];
  check("公开大屏请求带密钥", pubDash.some(u => u.includes("&k=") && u.includes("publicShareKey()")), pubDash);
  check("公开图表请求带密钥", pubCharts.some(u => u.includes("&k=") && u.includes("publicShareKey()")), pubCharts);

  // 7) 动作详情弹窗
  const odBody = rJs.slice(rJs.indexOf("function openExerciseDetail"), rJs.indexOf("function resetChecklist"));
  check("画布位图按显示尺寸建", odBody.includes("cv.clientWidth") && /cv\.width\s*=/.test(odBody),
        odBody.slice(0, 130));
  check("弹窗里没有写死的组数占位",
        /id="ex-detail-reps"><\/span>/.test(rHtml) && /id="ex-detail-target-muscle"><\/span>/.test(rHtml), "");
  check("画面文案不声称生物力学解算",
        !rJs.includes("生物力学") && !rHtml.includes("生物力学") && rJs.includes("火柴人关节示意 · 非真人实拍"),
        [rJs.includes("生物力学"), rHtml.includes("生物力学")]);
  // 撤了 3D 就不许再有任何对外文案宣称是模型/体块，否则说明与实际画法对不上。
  // 只钉屏幕上真出现的那两处（说明函数 + 首页静态文案），不扫全份 js——注释里
  // 提一句"不能再写成 3D 模型"是给人看的，扫进来只会误伤。
  const capAt = rJs.indexOf("function stickCaption");
  const capBody = rJs.slice(capAt, rJs.indexOf("\n}", capAt) + 2);
  const exdHtml = rHtml.slice(rHtml.indexOf('id="ex-detail-modal"'), rHtml.indexOf('id="ex-detail-steps"'));
  check("说明文案只说火柴人，不提模型或体块",
        capAt >= 0 && capBody.includes("火柴人") && !capBody.includes("3D") && !capBody.includes("体块")
        && !exdHtml.includes("3D") && !exdHtml.includes("体块") && !exdHtml.includes("拖拽"),
        capBody.slice(0, 120));
  check("相位只报屏上看得见的半程",
        rJs.includes("前半程（起身/推起方向）") && !rJs.includes("向心收缩 (爆发发力)"), "");

  // 7.5) 用户实拍那一屏：发几条消息后气泡压到下一张卡上，根因是分栏子元素规则
  //      强加 display:inline-block，把 .chat-container 本来的 flex 顶掉了
  const kidAt = rCss.indexOf(".view-panel.active > *");
  const kidRule = kidAt < 0 ? "" : rCss.slice(kidAt, kidAt + 260);
  check("面板子元素规则不抢 display",
        kidRule.length > 20 && !/display:/.test(kidRule.slice(0, kidRule.indexOf("}") + 1)),
        kidRule.slice(0, 130));
  // 一屏只排一条轴：CSS 里不能再有面板级分栏
  check("CSS 里没有面板级 column-count", !/\.view-panel[^{]*\{[^}]*column-count/.test(rCss), "");
  // 工作台/公开工具/身体数据提示必须归在监控大屏面板里，否则每个模块页都会把它们带出来
  // 网页独占的三块必须落在 panel-dashboard 与 panel-takeout 之间：
  // 它们原先挂在 main 下、面板之间，于是每个模块页都会把它们带出来，
  // 用户看到的"点了训练计划，计划模块跑到最下面"就是这个
  const dashPos = rHtml.indexOf('id="panel-dashboard"');
  const nextPos = rHtml.indexOf('id="panel-takeout"');
  const zone = dashPos < 0 || nextPos < 0 || nextPos < dashPos ? "" : rHtml.slice(dashPos, nextPos);
  const stray = ["web-workbench", "public-tools", "body-suspect-card"]
    .filter(id => zone.indexOf('id="' + id + '"') < 0);
  check("网页独占模块都挂在监控大屏里", stray.length === 0 && zone.length > 200,
        "跑到面板外的: " + JSON.stringify(stray) + " zone=" + zone.length);
  const mainInner = rHtml.slice(rHtml.indexOf("<main"), rHtml.indexOf("</main>"));
  const mainKids = [...mainInner.matchAll(/<section[^>]*id="(panel-[a-z-]+)"/g)].map(x => x[1]);
  const CM_PANELS = ["dashboard", "recipes", "workout", "body", "takeout", "charts", "gemini",
                     "community", "messages", "me", "tools"];
  const panelSet = new Set(mainKids.map(k => k.replace("panel-", "")));
  check("面板清单与导航设计一致",
        mainKids.length === CM_PANELS.length && CM_PANELS.every(t => panelSet.has(t)), mainKids);
  // 光数个数证明不了"每块都到得了"：底部 5 槽 + 桌面顶栏 + 工具 chip 条三个入口合起来
  // 必须覆盖所有面板，且不许有不存在的目标（点了没反应的面板比少一块更糟）。
  const navTargets = new Set([...rHtml.matchAll(/switchTab\('([a-z-]+)'\)/g)].map(m => m[1]));
  const orphan = CM_PANELS.filter(x => !navTargets.has(x));
  const dead = [...navTargets].filter(x => !panelSet.has(x));
  check("每个面板都有入口、每个入口都有面板", orphan.length === 0 && dead.length === 0,
        "没入口: " + JSON.stringify(orphan) + " 没面板: " + JSON.stringify(dead));
  // 跨栏/半栏规则里写的类名必须真的在页面里，否则那条规则永远不命中（.chat-box 就是这一类）
  const clsRefs = [...new Set([...rCss.matchAll(/body\.desktop-view[^{]*>\.([a-z][a-z0-9-]*)/g)].map(m => m[1]))];
  const clsDead = clsRefs.filter(cn => !new RegExp("\b" + cn + "\b").test(rHtml));
  check("桌面样式引用的类名都真实存在", clsDead.length === 0,
        "死选择器: " + JSON.stringify(clsDead) + " 共 " + clsRefs.length + " 条");
  // 电脑版只留顶栏一排：底部 dock 必须藏掉，否则同一组按钮出现两次
  const dockAt = rCss.indexOf("body.desktop-view .bottom-nav {");
  check("桌面端只有一排导航", dockAt >= 0 && /display:\s*none/.test(rCss.slice(dockAt, dockAt + 160)),
        dockAt < 0 ? "没有桌面端 dock 规则" : rCss.slice(dockAt, dockAt + 120));
  check("本机没开模型不写成故障", !rJs.includes("本地模型离线") && rJs.includes("本机没开模型 · 这条走服务器"),
        rJs.includes("本地模型离线"));

  // 8) 标签说要亮的肌肉，屏幕上必须真有一块体块会亮（正向核对，不是"包含于"）
  try {
    const list = run(h.context, `Object.keys(ACTIVE_MUSCLES)`);
    const types = run(h.context, `STICK_SEGMENTS.map(s => s.type)`);
    const dead = (list || []).filter(k => {
      const lit = run(h.context, `expandMuscleTargets(ACTIVE_MUSCLES[${JSON.stringify(k)}].targets)`);
      return !(lit || []).some(t => (types || []).includes(t));
    });
    check("每个发力肌群标签都能点亮至少一块体块", dead.length === 0, JSON.stringify(dead));
    check("肌群配置覆盖到的原型数量", (list || []).length >= 12, list);
  } catch (e) {
    check("每个发力肌群标签都能点亮至少一块体块", false, "该版本没有对应实现: " + String(e && e.message).slice(0, 60));
    check("肌群配置覆盖到的原型数量", false, "同上");
  }

  // 9) 真跑一遍：取数失败与打气成功分别会画成什么
  const R124_NAMES = ["矩阵取数失败真的画出了原因", "矩阵把没记录的天画成灰格", "矩阵有记录那天按三项打满", "打气计数用的是服务端返回的总数", "没送达时提示词说的是没送出去"];
  const SUITE124 = (async () => {
    if (!needSymbols(R124_NAMES, ["renderHabitMatrix", "sendCheerSticker", "paintCheerCount"])) return;
    const real = sandbox.__fetchHandler;
    // 后端每天都返回一行（没记的那两天是 0/0），矩阵必须自己把"未记录"认出来
    const rows = [];
    for (let i = 29; i >= 0; i--) {
      const dt = new Date(); dt.setDate(dt.getDate() - i);
      const iso = dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0")
        + "-" + String(dt.getDate()).padStart(2, "0");
      rows.push({ day: "d", date: iso, consumed: i === 0 ? 1200 : 0,
                  burned: i === 0 ? 220 : 0, deficit: i === 0 ? 300 : 0,record_status:i===0?"complete":"missing",has_records:i===0 });
    }
    sandbox.__fetchHandler = (u) => String(u).indexOf("/api/habits") >= 0
      ? Promise.resolve(okJson({ days: rows, window: 30 }))
      : Promise.reject(new Error("unexpected " + u));
    await run(h.context, `renderHabitMatrix()`).then(() => {}, () => {});
    await drain();
    const mHtml = String(run(h.context, `String(document.getElementById("wb-habit-matrix").innerHTML || "")`) || "");
    check("矩阵把没记录的天画成灰格", (mHtml.match(/lvl-0/g) || []).length === 29,
          "灰格 " + (mHtml.match(/lvl-0/g) || []).length + "/30");
    check("矩阵有记录那天按三项打满", /lvl-3/.test(mHtml) && /净缺口 300/.test(mHtml), mHtml.slice(-140));

    sandbox.__fetchHandler = () => Promise.reject(new TypeError("network down"));
    await run(h.context, `renderHabitMatrix()`).then(() => {}, () => {});
    await drain();
    check("矩阵取数失败真的画出了原因", val("wb-habit-matrix").includes("矩阵没取到数据"),
          val("wb-habit-matrix").slice(0, 100));

    sandbox.__fetchHandler = (u) => String(u).indexOf("/api/cheer") >= 0
      ? Promise.resolve(okJson({ code: 0, total: 7, kind: "稳步减脂" }))
      : Promise.reject(new Error("unexpected " + u));
    run(h.context, `window.__PUBLIC_USER__ = "someone"; state.token = "TK124";`);
    await run(h.context, `sendCheerSticker("稳步减脂")`).then(() => {}, () => {});
    await drain();
    check("打气计数用的是服务端返回的总数", val("pub-cheer-count").includes("已收到 7 枚打气"), val("pub-cheer-count"));
    sandbox.__fetchHandler = () => Promise.reject(new TypeError("server down"));
    await run(h.context, `sendCheerSticker("稳步减脂")`).then(() => {}, () => {});
    await drain();
    check("没送达时提示词说的是没送出去", val("pub-cheer-toast").includes("这枚没送出去"), val("pub-cheer-toast").slice(0, 100));
    sandbox.__fetchHandler = real;
  })();
  await SUITE124;
}

// ===== 14. 弹窗键盘行为、背景屏蔽与缺口文字摘要 =====
{
  const h14 = makeCtx();
  loadJs(h14.context);
  const errs14 = [];
  (h14.listeners["DOMContentLoaded"] || []).forEach(fn => { try { fn(); } catch (e) { errs14.push(String(e && e.message)); } });
  check("无障碍改造后初始化不抛异常", errs14.length === 0, errs14.join(" / "));
  const d14 = h14.sandbox.document;
  const kd = h14.docListeners["keydown"] || [];
  check("document 上挂了键盘监听", kd.length > 0, String(kd.length));
  let prevented = 0;
  const fire = (ev) => { ev.preventDefault = () => { prevented++; }; ev.repeat = !!ev.repeat; kd.forEach(fn => fn(ev)); };
  // 桩里的观察器只记账不自动派发，测试自己 flush 等价于浏览器投递变更记录
  const flush = () => h14.muts.forEach(m => { try { m.cb([]); } catch (e) { errs14.push(String(e && e.message)); } });
  check("五个弹窗都绑上了观察器", h14.muts.length === 5, String(h14.muts.length));

  // 旧版本根本没有这些函数，直接 run 会把整台砸崩；缺实现必须逐条记红而不是"没测"。
  const guard = (name, fn) => {
    try { const r = fn(); check(name, !!r[0], String(r.length > 1 && r[1] !== undefined ? r[1] : "")); }
    catch (e) { check(name, false, "缺实现或抛异常: " + String(e && e.message).slice(0, 70)); }
  };
  const exec = (code) => run(h14.context, code);

  // 未登录时 init 会自己弹登录框，两层一起开着就没法判断谁在最上面
  guard("清场：关掉已打开的弹窗", () => {
    exec('openDialogs().forEach(el => el.classList.remove("show"))');
    flush();
    return [true];
  });

  guard("打开档案弹窗", () => { exec('openProfileModal()'); flush(); return [d14.getElementById("profile-modal").classList.contains("show")]; });
  const prof = d14.getElementById("profile-modal");
  const auth = d14.getElementById("auth-modal");
  guard("弹窗开着时背景弹窗被屏蔽", () => [auth.getAttribute("aria-hidden") === "true", String(auth.getAttribute("aria-hidden"))]);
  guard("正在打开的弹窗自己不屏蔽", () => [prof.getAttribute("aria-hidden") === null, String(prof.getAttribute("aria-hidden"))]);
  guard("背景节点被置为 inert", () => [auth.inert === true, String(auth.inert)]);

  guard("Tab 被约束在弹窗内而不是跑到背景", () => {
    prevented = 0;
    fire({ key: "Tab", target: d14.getElementById("prof-age"), shiftKey: false });
    return [prevented > 0, String(prevented)];
  });

  guard("ESC 走的是弹窗自己的关闭按钮", () => {
    const before = h14.log.clicks || 0;
    fire({ key: "Escape", target: d14.getElementById("prof-age") });
    return [(h14.log.clicks || 0) > before, String(h14.log.clicks)];
  });

  guard("关闭后背景解除屏蔽", () => {
    exec('closeProfileModal()'); flush();
    return [auth.getAttribute("aria-hidden") === null, String(auth.getAttribute("aria-hidden"))];
  });
  guard("关闭后 inert 复位", () => [auth.inert === false, String(auth.inert)]);
  guard("没有弹窗时 ESC 不空点一下", () => {
    const before = h14.log.clicks || 0;
    fire({ key: "Escape", target: d14.getElementById("prof-age") });
    return [(h14.log.clicks || 0) === before, String(h14.log.clicks)];
  });

  // <div role="button"> 必须和真按钮一样可键盘激活
  const chip = d14.getElementById("slot-chip-lunch");
  chip.setAttribute("role", "button");
  guard("回车激活 role=button", () => {
    const before = h14.log.clicks || 0;
    fire({ key: "Enter", target: chip });
    return [(h14.log.clicks || 0) > before, String(h14.log.clicks)];
  });
  guard("空格激活 role=button", () => {
    const before = h14.log.clicks || 0;
    fire({ key: " ", target: chip });
    return [(h14.log.clicks || 0) > before, String(h14.log.clicks)];
  });
  guard("按住不放不重复提交", () => {
    const before = h14.log.clicks || 0;
    fire({ key: "Enter", target: chip, repeat: true });
    return [(h14.log.clicks || 0) === before, String(h14.log.clicks)];
  });
  guard("普通输入框回车不会被抢走", () => {
    const before = h14.log.clicks || 0;
    fire({ key: "Enter", target: d14.getElementById("prof-age") });
    return [(h14.log.clicks || 0) === before, String(h14.log.clicks)];
  });

  // 缺口文字摘要：达标与否必须能用文字读出来，不能只靠柱子颜色
  const rows = [
    { day: "10-01", deficit: 500, record_status: "complete" },
    { day: "10-02", deficit: 100, record_status: "partial" },
    { day: "10-03", deficit: -200, record_status: "complete" },
    { day: "10-04", deficit: 0, record_status: "missing" },
  ];
  const box = d14.getElementById("chart-deficit-summary");
  const cv = d14.getElementById("chart-deficit");
  let desc = "";
  guard("达标/未达/超支/未记录各算各的", () => {
    desc = String(exec('describeDeficit(' + JSON.stringify(rows) + ', 400)'));
    return [desc.includes("达标 1") && desc.includes("未达 1") && desc.includes("超支 1")
      && desc.includes("未记录 1"), desc.slice(0, 150)];
  });
  guard("摘要真的写进了界面节点", () => [String(box.innerText || "").includes("达标"), String(box.innerText).slice(0, 140)]);
  guard("图表 aria-label 同步成同一句话", () => [
    String(cv.getAttribute("aria-label") || "").includes("超支"), String(cv.getAttribute("aria-label")).slice(0, 140)]);
  guard("没有记录时不编造天数", () => {
    const empty = String(exec('describeDeficit([], 400)'));
    return [empty.includes("暂无真实缺口记录"), empty.slice(0, 120)];
  });
  guard("空数据时界面也跟着改口", () => [!String(box.innerText || "").includes("达标"), String(box.innerText).slice(0, 120)]);
  check("flush 过程没抛异常", errs14.length === 0, errs14.join(" / "));
}


// ===== 15. 本机登录信息被写坏时，不能把人留在空页面上 =====
{
  const hBad = makeCtx();
  loadJs(hBad.context);
  hBad.sandbox.localStorage.setItem("QINGSU_AUTH_TOKEN", "tok");
  hBad.sandbox.localStorage.setItem("QINGSU_AUTH_USER", "not-json");
  let thrown = "";
  try { run(hBad.context, "initAuthAndData()"); } catch (e) { thrown = String(e && e.message); }
  check("损坏的登录信息不把异常抛到调用方", thrown === "", thrown);
  check("读不出来的会话被清掉而不是留着",
    !hBad.sandbox.localStorage.getItem("QINGSU_AUTH_TOKEN")
    && !hBad.sandbox.localStorage.getItem("QINGSU_AUTH_USER"), "");
  check("损坏会话弹登录框并说明原因",
    hBad.sandbox.document.getElementById("auth-modal").classList.contains("show")
    && hBad.log.toasts.some(t => String(t).includes("重新登录")),
    JSON.stringify(hBad.log.toasts.slice(-3)));
}

// ===== 16. 强制更新门：请求自报构建号，被挡时整屏盖住 =====
{
  const hg = makeCtx();
  loadJs(hg.context);
  const css = fs.readFileSync(path.join(ROOT, "app/src/main/assets/style.css"), "utf8");
  const gradle = fs.readFileSync(path.join(ROOT, "app/build.gradle"), "utf8");
  const gcode = (gradle.match(/versionCode\s+(\d+)/) || [])[1] || "?";
  const drain = async () => { for (let i = 0; i < 4; i++) await new Promise(r => setImmediate(r)); };
  const reported = String(run(hg.context, "typeof APP_BUILD === 'number' ? String(APP_BUILD) : '?'"));
  check("构建号就是 gradle 那一版，不是 app.js 里另一套手抄", reported === gcode,
        "app.js=" + reported + " gradle=" + gcode);

  hg.sandbox.__fetchHandler = () => Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
  run(hg.context, 'fetch(API_BASE + "/api/dashboard", { headers: { Authorization: "Bearer tk" } })');
  await drain();
  const last = hg.log.fetches[hg.log.fetches.length - 1] || [null, {}];
  const hdr = (last[1] && last[1].headers) || {};
  check("业务请求自报构建号", String(hdr["X-App-Build"]) === gcode, JSON.stringify(hdr));
  check("加头没把鉴权头挤掉", String(hdr["Authorization"] || "").startsWith("Bearer "), JSON.stringify(hdr));

  hg.log.fetches.length = 0;
  run(hg.context, 'fetch(API_BASE + "/api/cheer", { method: "POST", body: "{}" })');
  await drain();
  const vhdr = ((hg.log.fetches[hg.log.fetches.length - 1] || [null, {}])[1] || {}).headers;
  check("访客接口不被当成待更新客户端", !vhdr || !("X-App-Build" in vhdr), JSON.stringify(vhdr));

  const policy = { code: "update_required", detail: "请更新到 v1.9.0", min_build: 22, your_build: 21,
                   latest: { version_code: 22, version_name: "1.9.0",
                             apk_url: "https://124.220.54.64/qingsu.apk", size: 5322721 } };
  const gated403 = (payload) => () => Promise.resolve(
    { ok: false, status: 403, json: async () => payload, clone() { return this; } });
  hg.sandbox.__fetchHandler = gated403(policy);
  run(hg.context, 'fetch(API_BASE + "/api/dashboard", { headers: { Authorization: "Bearer tk" } })');
  await drain();
  const d = hg.sandbox.document;
  const wall = d.getElementById("update-wall");
  check("被挡时整屏盖住", hg.sandbox.document.body.classList.contains("update-blocked")
        && String(wall.innerHTML).includes("uw-card"), String(wall.innerHTML).slice(0, 90));
  check("遮罩写清当前版本与最低可用版本",
        String(d.getElementById("uw-mine").textContent).indexOf("21") >= 0
        && String(d.getElementById("uw-min").textContent).indexOf("22") >= 0,
        d.getElementById("uw-mine").textContent + " / " + d.getElementById("uw-min").textContent);
  check("包体积按清单现算", String(d.getElementById("uw-size").textContent).includes("5.1"),
        String(d.getElementById("uw-size").textContent));
  check("App 内给的是去下载而不是刷新", String(wall.innerHTML).includes("去下载"), "");

  const noSize = JSON.parse(JSON.stringify(policy)); noSize.latest.size = 0;
  hg.sandbox.__fetchHandler = gated403(noSize);
  run(hg.context, 'fetch(API_BASE + "/api/dashboard")');
  await drain();
  check("体积读不到就显示未知，不回落成上一版的数字",
        String(d.getElementById("uw-size").textContent).includes("未知"),
        String(d.getElementById("uw-size").textContent));

  const hw = makeCtx();
  delete hw.sandbox.window.AndroidBridge;
  loadJs(hw.context);
  hw.sandbox.__fetchHandler = gated403(policy);
  run(hw.context, 'fetch(API_BASE + "/api/dashboard")');
  await drain();
  const wallW = hw.sandbox.document.getElementById("update-wall");
  check("网页版只让人刷新，不诱导下载 APK", String(wallW.innerHTML).includes("刷新页面")
        && !String(wallW.innerHTML).includes("去下载"), String(wallW.innerHTML).slice(0, 120));

  const hn = makeCtx();
  loadJs(hn.context);
  hn.sandbox.__fetchHandler = gated403({ detail: "不能改别人的记录" });
  run(hn.context, 'fetch(API_BASE + "/api/records/weight/1/update", { method: "POST", body: "{}" })');
  await drain();
  check("普通 403 不会误触发强更遮罩",
        !hn.sandbox.document.body.classList.contains("update-blocked"), "");

  const at = css.indexOf(".update-wall");
  check("遮罩压得住整屏且在最上层",
        at >= 0 && /position:\s*fixed/.test(css.slice(at, at + 260))
        && /z-index:\s*9{3,}/.test(css.slice(at, at + 260)), at < 0 ? "找不到 .update-wall" : css.slice(at, at + 120));

// ===== r149 社区：只测真能测的（桩 DOM 不承载页面结构，DOM 类判据留给真机） =====
try {
  const FEAT_REL = "app/src/main/assets/features.js";
  const featSrc = MUTANT ? execFileSync("git", ["show", MUT_REF + ":" + FEAT_REL],
      { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 }) : fs.readFileSync(path.join(ROOT, FEAT_REL), "utf8");
  // features.js 依赖 app.js 的全局（escapeHtml/postApi…），但两份都声明了
  // localGuidanceRows，同一个上下文跑两遍会撞车。这里先装 app.js，再把那一句声明去掉。
  const hCm = makeCtx();
  loadJs(hCm.context);
  const featRun = featSrc.replace(/^\s*let localGuidanceRows\s*=\s*\[\s*\]\s*;\s*$/m, "/* 由 app.js 声明 */");
  const cmErrs = [];
  check("features.js 里那句重复声明确实被去掉了（改了写法要跟着改这里）",
        featRun.length < featSrc.length, featSrc.length - featRun.length);
  try { run(hCm.context, featRun); } catch (e) { cmErrs.push(String(e && e.message)); }
  check("features.js 在 app.js 之后加载不抛异常", cmErrs.length === 0, cmErrs.join(" / "));
  const cmRun = code => run(hCm.context, code);

  // 昵称首字：emoji 开头时按下标取会切出半个码元，界面上是一个乱码方块
  const emo = String(cmRun('cmAvatarInner({name:"\\u{1F383}小田"})'));
  check("昵称首字按码元取，不切坏 emoji", emo === "\u{1F383}" && !/[\uD800-\uDBFF]$/.test(emo), JSON.stringify(emo));
  check("没名字时落回品牌首字，不显示空白", cmRun('cmAvatarInner({name:"   "})') === "轻", "");
  check("有头像就出 img，不拼没转义的 URL",
        /^<img src="[^"]*" alt="">$/.test(String(cmRun('cmAvatarInner({name:"甲",avatar:"/uploads/a.jpg?x=1"})'))),
        cmRun('cmAvatarInner({name:"甲",avatar:"/uploads/a.jpg?x=1"})'));
  check("注销账号不显示成空白名字", cmRun('cmName(null)') === "已注销用户", "");
  check("时间戳为空时不显示 NaN",
        cmRun('cmAgo("")') !== "NaN" && !/NaN/.test(cmRun('cmAgo("乱码")'))
        && !/NaN/.test(cmRun('cmTime("")')), [cmRun('cmAgo("")'), cmRun('cmTime("2026-10-18 04:05:06")')]);
  check("相对时间只说分钟/小时/天，超过一周退回日期",
        /刚刚|分钟前|小时前|天前|^\\d{4}-\\d{2}-\\d{2}$/.test(String(cmRun(
          'cmAgo(new Date(Date.now()-3*60000).toISOString().replace("T"," ").slice(0,19))'))), "");
  check("列表类型不认识时不改动当前状态（防脏参数把面板清空）",
        cmRun('(function(){setCommunityTab("magic");return cm.feed;})()') === "latest", "");
  check("反馈类型同样不认脏值",
        cmRun('(function(){setFeedbackKind("magic");return cm.feedbackKind;})()') === "bug", "");
  check("属地缺失时界面说未知，不留空",
        cmRun('cmRegionTag("")') === "属地未知" && cmRun('cmRegionTag("湖南")').indexOf("湖南") >= 0, "");
  check("私信回执认 request_id，不认自己造的第二套键",
        /t === "ack"/.test(featSrc) && /data\.request_id/.test(featSrc), "");
} catch (e) {
  check("r149 社区判据块本身跑通了", false, String(e && e.message));
}

try {
  const F150_REL = "app/src/main/assets/features.js";
  const feat150 = MUTANT ? execFileSync("git", ["show", MUT_REF + ":" + F150_REL],
      { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, F150_REL), "utf8");
  const h150 = makeCtx();
  loadJs(h150.context);
  const clean150 = feat150.replace(/^\s*let localGuidanceRows\s*=\s*\[\s*\]\s*;\s*$/m, "/* 由 app.js 声明 */");
  const errs150 = [];
  try { run(h150.context, clean150); } catch (e) { errs150.push(String(e && e.message)); }
  check("r150 这块能真的把 features.js 跑起来", errs150.length === 0, errs150.join(" / "));
  const r150 = code => run(h150.context, code);

  check("五个整页都注册了（主页/帖子/私信/统计/收藏）",
        r150('Object.keys(QS_PAGE_DEF).sort().join(",")') === "dm,favorites,member,post,stats",
        r150('Object.keys(QS_PAGE_DEF).sort().join(",")'));
  check("未知页名不会把栈弄脏",
        r150('(function(){openPage("magic",1);return QS_PAGES.length+":"+qsPageOpen();})()') === "0:false", "");
  check("栈空时返回 false（硬件返回键据此决定要不要吞掉）",
        r150('closePage()') === false, "");
  check("同城页签被认下来",
        r150('(function(){setCommunityTab("city");const f=cm.feed;setCommunityTab("magic");return f+"/"+cm.feed;})()')
          === "city/city", "脏值把已选的同城也清掉了");
  r150('setCommunityTab("latest")');

  // 撤回：气泡要变成一句说明，且不再显示原话
  const recalled = String(r150('cmBubbleHTML({id:7,from_id:1,body:"原话",created_at:"2026-10-18 10:00:00",recalled_at:"2026-10-18 10:01:00"},1)'));
  check("撤回的气泡只说撤回，不印原话",
        recalled.indexOf("你撤回了一条消息") >= 0 && recalled.indexOf("原话") < 0, recalled.slice(0, 80));
  const them = String(r150('cmBubbleHTML({id:8,from_id:2,body:"对方撤的",created_at:"2026-10-18 10:00:00",recalled_at:"x"},1)'));
  check("对方撤回时文案是对方那句", them.indexOf("对方撤回了一条消息") >= 0, them.slice(0, 60));
  const live = String(r150('cmBubbleHTML({id:9,from_id:1,body:"在呢",created_at:"2026-10-18 10:00:00"},1)'));
  check("正常气泡带得上右键与长按入口",
        live.indexOf("oncontextmenu=") >= 0 && live.indexOf("ontouchstart=") >= 0
        && live.indexOf('data-mid="9"') >= 0, live.slice(0, 120));
  check("装扮只改自己一侧",
        r150('cmBubbleHTML({id:1,from_id:2,body:"对方",created_at:"x"},1)').indexOf("data-t=") < 0, "");

  // 撤回窗口：4 分钟给撤、6 分钟不给（服务端还有一道，这里是按钮该不该出现）。
  // 注意要用本地时间串——服务端 _now() 写的就是本地时间，toISOString 是 UTC，差 8 小时。
  const win = String(r150('(function(){function f(d){var p=function(n){return String(n).length<2?"0"+n:""+n};'
    + 'return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+" "+p(d.getHours())+":"+p(d.getMinutes())+":"+p(d.getSeconds());}'
    + 'return qsWithin(f(new Date(Date.now()-4*60000)),300)+"/"+qsWithin(f(new Date(Date.now()-6*60000)),300)'
    + '+"/"+qsWithin("",300)+"/"+qsWithin("不是时间",300);})()'));
  check("撤回窗口按 5 分钟判，读不懂的时间不给撤",
        win === "true/false/false/false", win);

  // 复制：值走 data 属性。上一版把内容拼进 onclick 的转义里，直接写出过一个语法错的按钮
  run(h150.context, 'window.__copied=null; qsCopy=function(t,l){window.__copied=t+"|"+l;return true;}');
  run(h150.context, 'qsCopyFrom({getAttribute:function(k){return k==="data-copy"?"34003457":"轻塑号";}})');
  check("复制按钮交出去的是 data-copy 里的真值",
        String(r150('window.__copied')) === "34003457|轻塑号", String(r150('window.__copied')));
  check("资料页的复制按钮用 data-copy，不把值拼进 onclick",
        feat150.indexOf('data-copy="') >= 0 && /onclick="qsCopyFrom\(this\)"/.test(feat150), "");

  // 会话列表要就地顶上最新消息（机主："要刷新才会展示最新消息"）
  r150('cm.convs=[{with:{id:55},last_body:"上一句",last_at:"2026-10-18 10:00:00",unread:0}];'
       + 'cm.msgTab="notices";cm.thread=null;');
  r150('bumpConversation(55,"新的一句","me")');
  check("自己发出去之后会话摘要立刻更新",
        String(r150('cm.convs[0].last_body')) === "新的一句", String(r150('cm.convs[0].last_body')));
  check("自己发的不算未读", String(r150('cm.convs[0].unread')) === "0", String(r150('cm.convs[0].unread')));
  r150('bumpConversation(55,"对方来的","them")');
  check("对方来的算一条未读", String(r150('cm.convs[0].unread')) === "1", String(r150('cm.convs[0].unread')));
  r150('cm.convs=[];cm.msgTab="notices";');
  // 统计格：接口给的是对的数，渲染层把三元组的下标写串过——屏上四个数全是 NaN。
  // 这条不依赖 DOM，直接跑纯函数，钉"数字位上是数字、标签位上是标签"。
  const statsHtml = String(r150('qsStatsHTML([["posts","帖子",3],["followers","粉丝",0],'
    + '["following","关注",12],["likes","获赞",1]], 7)'));
  check("统计格渲染的是数字不是标签（防下标写串成 NaN）",
        statsHtml.indexOf("<b>3</b><span>帖子</span>") >= 0
        && statsHtml.indexOf("<b>12</b><span>关注</span>") >= 0
        && statsHtml.indexOf("NaN") < 0, statsHtml.slice(0, 120));
  check("统计格每个都能点进明细",
        (statsHtml.match(/onclick="openStats\('/g) || []).length === 4
        && statsHtml.indexOf("openStats('likes',7)") >= 0, statsHtml.slice(-140));
  check("脏数字落成 0 而不是 NaN",
        r150('qsStatsHTML([["posts","帖子","不是数"]],7)').indexOf("NaN") < 0, "");
} catch (e) {
  check("r150 判据块本身跑通了", false, String(e && e.message));
}
}

// ===== r151：后台封号之后，客户端要清会话、说清原因，且不能把普通 403 误判成封号 =====
try {
  const banResp = (body) => ({ ok: false, status: 403, clone() { return this; }, json: async () => body });

  log.toasts.length = 0;
  run(h.context, `var authOpened=0; openAuthModal=function(){authOpened++;};
                  localStorage.setItem("QINGSU_AUTH_TOKEN","tk-ban"); state.token="tk-ban";`);
  sandbox.__fetchHandler = () => Promise.resolve(banResp(
    { detail: "该账号已被停用：发布违规内容", code: "account_banned" }));
  run(h.context, `fetch("/api/dashboard",{headers:{Authorization:"Bearer tk-ban"}});`);
  await drain(8);
  check("封号会清掉本机登录态",
        run(h.context, `localStorage.getItem("QINGSU_AUTH_TOKEN")`) === null,
        String(run(h.context, `localStorage.getItem("QINGSU_AUTH_TOKEN")`)));
  check("封号原因原样播报，不说成网络不通",
        log.toasts.some(t => t.includes("已被停用") && t.includes("发布违规内容")),
        log.toasts.join(" | "));
  check("封号之后把人带回登录页", run(h.context, "authOpened") >= 1, String(run(h.context, "authOpened")));

  // 对照组：这个服务里 403 还用于"只能删自己的帖子"，那种拒绝不许清会话
  log.toasts.length = 0;
  run(h.context, `authOpened=0; localStorage.setItem("QINGSU_AUTH_TOKEN","tk2");`);
  sandbox.__fetchHandler = () => Promise.resolve(banResp({ detail: "只能删自己的帖子" }));
  run(h.context, `fetch("/api/community/comments/1",{method:"DELETE"});`);
  await drain(8);
  check("没有机器码的普通 403 不被当成封号（登录态必须还在）",
        run(h.context, `localStorage.getItem("QINGSU_AUTH_TOKEN")`) === "tk2"
        && run(h.context, "authOpened") === 0,
        `token=${run(h.context, "localStorage.getItem(\"QINGSU_AUTH_TOKEN\")")} authOpened=${run(h.context, "authOpened")}`);

  // 对照组：强更门那套不能被封号逻辑抢走（两者都是 403，靠 code 区分）
  log.toasts.length = 0;
  sandbox.__fetchHandler = () => Promise.resolve(banResp(
    { detail: "当前 App 版本已停用，请更新到 v1.9.9 后再继续使用", code: "update_required", min_build: 31 }));
  run(h.context, `fetch("/api/dashboard",{headers:{Authorization:"Bearer tk2"}});`);
  await drain(8);
  check("强更门仍然走门的那条路，没被误判成封号",
        run(h.context, `localStorage.getItem("QINGSU_AUTH_TOKEN")`) === "tk2",
        String(run(h.context, `localStorage.getItem("QINGSU_AUTH_TOKEN")`)));
} catch (e) {
  check("r151 判据块本身跑通了", false, String(e && e.message));
}

// ===== r152：私信左右分侧与 id 容错（features.js 需要 app.js 的全局）=====
try {
  const F152_REL = "app/src/main/assets/features.js";
  const feat152 = MUTANT ? execFileSync("git", ["show", MUT_REF + ":" + F152_REL],
      { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, F152_REL), "utf8");
  const h152 = makeCtx();
  loadJs(h152.context);
  const clean152 = feat152.replace(/^\s*let localGuidanceRows\s*=\s*\[\s*\]\s*;\s*$/m, "/* 由 app.js 声明 */");
  run(h152.context, clean152);
  const r152 = code => run(h152.context, code);

  check("id 比较能容下字符串/数字两种形态",
        r152('qsSameId(2,"2")') === true && r152('qsSameId("x",2)') === false, "");
  r152('state.user={id:"2",username:"u",nickname:"u"}; cm.thread={partner:{id:3,nickname:"p"}}; cm.myTheme="green";');
  const mineHtml = r152('cmBubbleHTML({id:9,from_id:2,body:"hi",created_at:"2026-10-18 12:00:00"},"2")');
  const theirHtml = r152('cmBubbleHTML({id:10,from_id:3,body:"yo",created_at:"2026-10-18 12:00:00"},"2")');
  check("自己的消息靠右：dm-row me 且气泡在头像前",
        mineHtml.indexOf("dm-row me") >= 0
        && mineHtml.indexOf("cm-bubble") < mineHtml.indexOf("dm-avatar"), mineHtml.slice(0, 140));
  check("对方的消息靠左：dm-row them 且头像在气泡前",
        theirHtml.indexOf("dm-row them") >= 0
        && theirHtml.indexOf("dm-avatar") < theirHtml.indexOf("cm-bubble"), theirHtml.slice(0, 140));
  r152('state.user={username:"old-session"};cm.thread={partner:{id:3,nickname:"p"}};');
  const oldSessionMine = r152('cmBubbleHTML({id:12,from_id:2,to_id:3,body:"旧缓存里的我",created_at:"2026-10-18 12:00:00"},undefined)');
  const oldSessionThem = r152('cmBubbleHTML({id:13,from_id:3,to_id:2,body:"对方",created_at:"2026-10-18 12:00:00"},undefined)');
  check("旧登录缓存缺少用户 id 时仍按会话对端识别发送者",
        oldSessionMine.indexOf("dm-row me") >= 0 && oldSessionThem.indexOf("dm-row them") >= 0,
        oldSessionMine.slice(0, 100) + " / " + oldSessionThem.slice(0, 100));
  const nested = r152('qsCommentsHTML([{id:1,body:"主评论",reply_to:null,author:{id:2,username:"mumu",nickname:"木木"},created_at:"x"},{id:2,body:"子评论",reply_to:1,reply_to_user_id:2,reply_to_name:"木木",author:{id:3,username:"reply",nickname:"回复者"},created_at:"x"}],9)');
  check("子评论嵌在主评论下，并在正文前标明回复对象",
        nested.indexOf("pd-cmt-replies") >= 0 && nested.indexOf("data-comment=\"1\"") < nested.indexOf("data-comment=\"2\"")
          && nested.indexOf("（回复 ") >= 0 && nested.indexOf("木木") >= 0, nested.slice(0, 240));
  check("评论头像和昵称都可打开对应主页",
        nested.indexOf("openMemberHome(2)") >= 0 && nested.indexOf("openMemberHome(3)") >= 0, "");
  const featuresCss152 = fs.readFileSync(path.join(ROOT, "app/src/main/assets/features.css"), "utf8");
  check("少量私信从聊天区顶部开始显示，不再沉在大块空白下方",
        featuresCss152.includes(".cm-bubbles.page{background:#EDEDED;gap:14px;padding:16px 12px;justify-content:flex-start}"), "");
  check("窄屏与桌面模式的弹窗最大宽度都受视口约束",
        featuresCss152.includes("max-width:min(420px,calc(100vw - 24px))")
          && featuresCss152.includes("body.desktop-view .modal-card{max-width:min(480px,calc(100vw - 24px))}"), "");
  check("私信联系人标题可直接打开主页",
        feat152.includes("class=\"pl-title-profile\"") && feat152.includes("openMemberHome(' + partnerId + ')"), "");
  check("撤回提示不再用气泡样式",
        r152('cmBubbleHTML({id:11,from_id:3,recalled_at:"x",body:""},"2")').indexOf("dm-recall") >= 0, "");

  // 页面栈 × 历史：用一个假 history 驱动真实的 openPage/closePage/popstate
  r152('QS_PAGE_DEF.__t={title:"t",render:function(){}};' +
       'history={stack:[],state:null,pushState:function(s){this.stack.push(s);this.state=s;},' +
       'back:function(){this.stack.pop();this.state=this.stack[this.stack.length-1]||null;},' +
       'go:function(n){while(n<0){this.stack.pop();n++;}this.state=this.stack[this.stack.length-1]||null;}};');
  r152('openPage("__t",1);openPage("__t","1");');
  check("连续点击同一头像/姓名不会重复堆叠当前页",
        r152('QS_PAGES.length+":"+history.stack.length') === "1:1", r152('QS_PAGES.length+":"+history.stack.length'));
  r152('qsCloseAllPages();');
  r152('openPage("__t",1);openPage("__t",2);');
  check("打开两页 = 页面栈两层 + 历史两层",
        r152('QS_PAGES.length+":"+history.stack.length') === "2:2", r152('QS_PAGES.length+":"+history.stack.length'));
  r152('history.back();');
  const pops = h152.listeners["popstate"] || [];
  pops.forEach(fn => { try { fn(); } catch (e) {} });
  check("浏览器返回一次，页面栈跟着回到一层",
        r152('QS_PAGES.length') === 1 && r152('history.state && history.state.qsPage') === 1,
        r152('QS_PAGES.length') + ":" + r152('history.state && history.state.qsPage'));
  r152('qsCloseAllPages();');
  check("切 tab 收层时历史也一起退回，不留幽灵页",
        r152('QS_PAGES.length') === 0 && r152('history.stack.length') === 0,
        r152('QS_PAGES.length') + ":" + r152('history.stack.length'));
} catch (e) {
  check("r152 判据块本身跑通了", false, String(e && e.message));
}

// ===== r159：底部导航那颗真头像（真的调用函数，不是查字符串）=====
try {
  const F159_REL = "app/src/main/assets/features.js";
  const feat159 = MUTANT ? execFileSync("git", ["show", MUT_REF + ":" + F159_REL],
      { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, F159_REL), "utf8");
  const h159 = makeCtx();
  loadJs(h159.context);
  run(h159.context, feat159.replace(/^\s*let localGuidanceRows\s*=\s*\[\s*\]\s*;\s*$/m, "/* 由 app.js 声明 */"));
  const r159 = code => String(run(h159.context, code));

  r159('state.user={id:"2",username:"tiangang",nickname:"田刚"};');
  r159('paintMeAvatars("/uploads/av.jpg?expires=1700000000&signature=abc");');
  const nav159 = r159('document.getElementById("nav-me-avatar").innerHTML');
  const dnav159 = r159('document.getElementById("dnav-me-avatar").innerHTML');
  check("带头像时底部那颗和桌面那颗都换成真图片，不是字母章",
        nav159.indexOf("<img src=") >= 0 && nav159.indexOf("av.jpg") >= 0
          && dnav159.indexOf("<img src=") >= 0, nav159.slice(0, 120));
  check("头像链接带上签名参数（过期链接不能拼成裸文件名）",
        nav159.indexOf("expires=1700000000") >= 0 && nav159.indexOf("signature=abc") >= 0, nav159.slice(0, 160));
  r159('paintMeAvatars("");');
  const noAv = r159('document.getElementById("nav-me-avatar").innerHTML');
  check("没有头像时才回落字母章，取的是昵称首字",
        noAv.indexOf("<img") < 0 && noAv.trim() === "田", noAv);
  const cell159 = r159('typeof qsAvatarCell==="function"?qsAvatarCell():"missing"');
  check("头像那一格能整格重画，没头像时留明确占位",
        cell159.indexOf("td-avatar-empty") >= 0 && cell159.indexOf("还没头像") >= 0, cell159.slice(0, 120));

  // 「我的」主页大字该写谁：真跑一遍 loadMe，别只查源码里有没有那行字
  const meRound = async (nickVal) => {
    h159.sandbox.__fetchHandler = (url) => {
      const u = String(url);
      const body = u.indexOf("/api/community/stats") >= 0
        ? { code: 0, public_id: "34003457", posts: 1, followers: 2, following: 3,
            likes_received: 4, region: "浙江", bubble_theme: "green" }
        : u.indexOf("/api/account") >= 0
        ? { code: 0, user: { id: "2", username: "tiangang", nickname: nickVal, public_id: "34003457",
                             created_at: "2026-10-01 09:00:00" },
            avatar_url: "/uploads/nav.jpg?expires=1700000009&signature=zz", bio: "慢慢来", region: "浙江", discoverable: 1 }
        : { code: 0, items: [] };
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    };
    run(h159.context, `state.token="tk-me";`);
    run(h159.context, `loadMe();`);
    await drain(12);
    return { name: String(r159('document.getElementById("me-name").textContent')),
             login: String(r159('document.getElementById("me-login").innerHTML')),
             nav: String(r159('document.getElementById("nav-me-avatar").innerHTML')) };
  };
  const withNick = await meRound("田刚");
  check("设过昵称：主页大字是昵称", withNick.name === "田刚", withNick.name);
  check("读完「我的」页之后底部那颗仍是真头像，不会被字母章抹回去",
        withNick.nav.indexOf("nav.jpg") >= 0 && withNick.nav.indexOf("signature=zz") >= 0,
        withNick.nav.slice(0, 140));
  const noNick = await meRound("");
  check("没设昵称：主页明说还没设置，登录名挪到单独一行",
        noNick.name === "还没设置昵称" && noNick.login.indexOf("tiangang") >= 0
          && noNick.login.indexOf("me-login-name") >= 0,
        noNick.name + " / " + noNick.login.slice(0, 120));
} catch (e) {
  check("r159 判据块本身跑通了", false, String(e && e.message));
}

const bad = R.filter(x => !x[1]);
console.log(`\n=== ${MUTANT ? "变异样本(HEAD 改动前)" : "当前源码"}：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
for (const [name, ok, detail] of R) console.log(`  ${ok ? "绿" : "红"} ${name}${ok ? "" : "  -> " + detail}`);
// 本轮块在缺实现的版本上会塌成一条（端点/函数根本不存在），所以阈值按 5 条算
const pass = MUTANT ? bad.length >= 5 : bad.length === 0;
console.log("EXIT=" + (pass ? 0 : 1));
process.exit(pass ? 0 : 1);
