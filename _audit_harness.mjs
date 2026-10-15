// 轻塑前端回归台：用 vm + DOM stub 直接跑仓库里那份 app.js（不是手搓参考实现）
// 用法:  node _audit_harness.mjs            → 当前源码，应全绿
//        node _audit_harness.mjs --mutant   → git HEAD 那版，应大面积红
import fs from "node:fs";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const JS_REL = "app/src/main/assets/app.js";
const MUTANT = process.argv.includes("--mutant");

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
      addEventListener() {},
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

  const win = {
    location: { protocol: "http:", hostname: "127.0.0.1", origin: "http://127.0.0.1", hash: "", search: "" },
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

  const sandbox = {
    window: win,
    document: {
      getElementById: mkEl,
      querySelector: (s) => mkEl("q" + s),
      querySelectorAll: () => [],
      createElement: (t) => newEl("dyn-" + (++dynSeq) + ":" + t),
      body: {
        appendChild() {}, removeChild() {},
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
  return { context, log, sandbox, mkEl, elems, listeners };
}

function loadJs(context) {
  const src = MUTANT
    ? execFileSync("git", ["show", "HEAD:" + JS_REL], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, JS_REL), "utf8");
  vm.runInContext(src, context, { filename: JS_REL });
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
  ["周期", "upgradeCyclePlan", `document.getElementById("cycle-input-weight").value="133";
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
  ["平台期", "感觉体重在平台期不掉了怎么办？", ["平台期", "真假"]],
  ["练后饿", "运动完晚上很饿能吃什么？", ["练后", "饿"]],
  ["补救", "今天不小心暴食了一顿怎么补救？", ["自适应", "晚餐"]],
  ["火锅", "在外聚餐吃火锅该怎么点？", ["锅底", "蘸料"]],
];
for (const [label, q, keys] of chips) {
  const ans = String(run(h.context, `generateAiResponse(${JSON.stringify(q)})`));
  const hit = keys.every(k => ans.includes(k));
  const isFallback = ans.includes("专属塑形顾问建议");
  check(`chip「${label}」拿到专答不是兜底`, hit && !isFallback, ans.replace(/\s+/g, " ").slice(0, 110));
}

// ===== 8. 公网大屏用户名不再当 HTML 插 =====
sandbox.__fetchHandler = () => Promise.resolve(failJson(404, "no"));
run(h.context, `loadPublicUserData("<img src=x onerror=alert(1)>");`);
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
  b3.includes("联网查询失败") && b3.includes("本地内置建议"), b3.slice(-180));

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
    ? execFileSync("git", ["show", "HEAD:" + rel], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
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
check("动作卡有标准分解按钮", exHtml.includes("标准动作分解"), "");
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
run(h.context, `state.token="tk"; try{localStorage.removeItem("QINGSU_NOTED_"+new Date().toISOString().slice(0,10))}catch(e){}`);
run(h.context, `notifyOnceToday("测试","内容")`);
run(h.context, `notifyOnceToday("测试","内容")`);
check("同一天只提醒一次", noteCount === 1, noteCount);

// 通知发不出去（没权限）时必须改成页面内提醒，不能静默丢掉
sandbox.window.AndroidBridge.tryNotify = (a, b) => { return false; };
run(h.context, `try{localStorage.removeItem("QINGSU_NOTED_"+new Date().toISOString().slice(0,10))}catch(e){}`);
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
run(h.context, `document.getElementById("cycle-input-weight").value="133";
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
check("切换按钮文案随之改变", txt2b("btn-view-toggle").includes("手机版"), txt2b("btn-view-toggle"));
run(h.context, `applyViewMode("mobile")`);
check("手机模式撤掉 desktop-view", !sandbox.document.body.classList.contains("desktop-view"), "");
function txt2b(id) { return String(run(h.context, `document.getElementById("${id}").innerText`)); }

check("首页有 header-row-1 结构", htmlSrc.includes('class="header-row-1"'), "");
check("档案摘要独立成行", htmlSrc.includes("header-profile-line"), "");
check("有视图切换按钮", htmlSrc.includes('id="btn-view-toggle"'), "");
check("有日子差异说明位", htmlSrc.includes('id="mode-diff-hint"'), "");
check("有每日状态条", htmlSrc.includes('class="daily-strip"'), "");
check("有拍摄标准指引", htmlSrc.includes("shoot-guide"), "");
check("CSS 有桌面双栏", cssSrc.includes("desktop-view main .view-panel") && cssSrc.includes("grid-template-columns"), "");
check("CSS 桌面横幅跨满", cssSrc.includes("grid-column: 1 / -1"), "");
check("标题不再是被挤的长句", /<h1>轻塑<\/h1>/.test(htmlSrc), "");
} catch (e) {
  check("本轮前端改动在该版本无法执行（等价于全红）", false, String(e && e.message));
}

const bad = R.filter(x => !x[1]);
console.log(`\n=== ${MUTANT ? "变异样本(HEAD 改动前)" : "当前源码"}：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
for (const [name, ok, detail] of R) console.log(`  ${ok ? "绿" : "红"} ${name}${ok ? "" : "  -> " + detail}`);
// 本轮块在缺实现的版本上会塌成一条（端点/函数根本不存在），所以阈值按 5 条算
const pass = MUTANT ? bad.length >= 5 : bad.length === 0;
console.log("EXIT=" + (pass ? 0 : 1));
process.exit(pass ? 0 : 1);
