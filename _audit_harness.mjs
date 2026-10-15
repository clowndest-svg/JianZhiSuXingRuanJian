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
  function mkEl(id) {
    if (elems.has(id)) return elems.get(id);
    const el = {
      id, innerText: "", innerHTML: "", value: "", textContent: "",
      style: {}, checked: false, files: null,
      width: 0, height: 0,
      classList: {
        _s: new Set(),
        add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
        contains(c) { return this._s.has(c); },
      },
      getContext() { return ctx2d; },
      appendChild() {}, remove() {}, select() {}, focus() {},
      addEventListener() {},
    };
    Object.defineProperty(el, "parentElement", { value: { clientWidth: 340 } });
    elems.set(id, el);
    return el;
  }

  const win = {
    location: { protocol: "http:", hostname: "127.0.0.1", origin: "http://127.0.0.1", hash: "", search: "" },
    addEventListener() {},
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

  const sandbox = {
    window: win,
    document: {
      getElementById: mkEl,
      querySelector: (s) => mkEl("q" + s),
      querySelectorAll: () => [],
      createElement: (t) => mkEl("new-" + t),
      body: { appendChild() {}, removeChild() {} },
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
    isNaN, parseInt, parseFloat, Set, Map,
  };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  return { context, log, sandbox, mkEl, elems };
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
const bad = R.filter(x => !x[1]);
console.log(`\n=== ${MUTANT ? "变异样本(HEAD 改动前)" : "当前源码"}：${R.length} 条，绿 ${R.length - bad.length}，红 ${bad.length} ===`);
for (const [name, ok, detail] of R) console.log(`  ${ok ? "绿" : "红"} ${name}${ok ? "" : "  -> " + detail}`);
const pass = MUTANT ? bad.length >= 10 : bad.length === 0;
console.log("EXIT=" + (pass ? 0 : 1));
process.exit(pass ? 0 : 1);
