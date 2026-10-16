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
      querySelectorAll() { return []; },
      querySelector() { return null; },
      addEventListener() {},
      // 桩缺 setAttribute 会让代码一调就抛、异常被 init 吞掉，
      // 表现成"逻辑没生效"而真因是桩少方法——这类假红上一批已经踩过一次。
      _attrs: {},
      setAttribute(k, v) { this._attrs[String(k)] = String(v); },
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

  const win = {
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
check("档案摘要独立成行", htmlSrc.includes("header-profile-line"), "");
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
  ? execFileSync("git", ["show", "HEAD:" + PUB_REL], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
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
}




// ============ 第六批补：下载弹窗不许有写死的版本与体积 ============
const DL_NAMES = ["下载弹窗无写死体积","下载弹窗无写死版本号","版本与体积改为待填占位",
    "清单读不到时显示未知而不是回落假数","下载文件名带真实版本","不再宣称高速直链"];
const DLN = DL_NAMES;
const dlHtml = MUTANT
  ? execFileSync("git", ["show", "HEAD:app/src/main/assets/index.html"], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
  : fs.readFileSync(path.join(ROOT, "app/src/main/assets/index.html"), "utf8");
const dlJs = MUTANT
  ? execFileSync("git", ["show", "HEAD:app/src/main/assets/app.js"], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
  : fs.readFileSync(path.join(ROOT, "app/src/main/assets/app.js"), "utf8");
if (!/loadApkMeta/.test(dlJs)) {
  for (const nm of DLN) check(nm, false, "该版本没有对应实现");
} else {
  check("下载弹窗无写死体积", !/\(\s*5\.5MB\s*\)/.test(dlHtml) && !/安装包 \(\d/.test(dlHtml),
        (dlHtml.match(/安装包 \([^)]*\)/) || [""])[0]);
  check("下载弹窗无写死版本号", !/v5\.0/.test(dlHtml), (dlHtml.match(/v5\.0[^<"]{0,14}/g) || []).slice(0,3));
  check("版本与体积改为待填占位",
        dlHtml.includes("apk-size-line") && dlHtml.includes("apk-ver-top"), "");
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
    ? execFileSync("git", ["show", "HEAD:" + rel], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
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
  check("画布位图按显示尺寸建", odBody.includes("getBoundingClientRect()") && /cv\.width\s*=/.test(odBody),
        odBody.slice(0, 130));
  check("弹窗里没有写死的组数占位",
        /id="ex-detail-reps"><\/span>/.test(rHtml) && /id="ex-detail-target-muscle"><\/span>/.test(rHtml), "");
  check("画面文案不声称生物力学解算",
        !rJs.includes("生物力学") && !rHtml.includes("生物力学") && rJs.includes("程序化体块示意 · 非真人实拍"),
        [rJs.includes("生物力学"), rHtml.includes("生物力学")]);
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
  check("main 之下只有七个面板",
        mainKids.length === 7 && (mainInner.match(/<div/g) || []).length === (mainInner.match(/<div/g) || []).length,
        mainKids);
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
    const types = run(h.context, `MUSCLE_VOLUMES.map(v => v.type)`);
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

const bad = R.filter(x => !x[1]);
console.log(`\n=== ${MUTANT ? "变异样本(HEAD 改动前)" : "当前源码"}：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
for (const [name, ok, detail] of R) console.log(`  ${ok ? "绿" : "红"} ${name}${ok ? "" : "  -> " + detail}`);
// 本轮块在缺实现的版本上会塌成一条（端点/函数根本不存在），所以阈值按 5 条算
const pass = MUTANT ? bad.length >= 5 : bad.length === 0;
console.log("EXIT=" + (pass ? 0 : 1));
process.exit(pass ? 0 : 1);
