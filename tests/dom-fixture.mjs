// 轻塑前端回归台：用 vm + DOM stub 直接跑仓库里那份 app.js（不是手搓参考实现）
// 用法:  node _audit_harness.mjs            → 当前源码，应全绿
//        node _audit_harness.mjs --mutant   → git HEAD 那版，应大面积红
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

function loadJs(context,features=false) {
  const src = MUTANT
    ? execFileSync("git", ["show", "HEAD:" + JS_REL], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 24 })
    : fs.readFileSync(path.join(ROOT, JS_REL), "utf8");
  vm.runInContext(src, context, { filename: JS_REL });
  if(features)vm.runInContext(fs.readFileSync(path.join(ROOT,'app/src/main/assets/features.js'),'utf8'),context);
  else vm.runInContext('var localGuidanceRows=[]',context);
  vm.runInContext("localGuidanceRows="+fs.readFileSync(path.join(ROOT,"app/src/main/assets/guidance.json"),"utf8"),context);
}

// ------------------------------------------------------------------ 判据
export {makeCtx,loadJs};
