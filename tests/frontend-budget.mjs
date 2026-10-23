/* 前端资源预算的实测基线（方案 C11）。

C11 要的是"先测首屏与长任务，再决定怎么拆"。所以这一条不判"够不够小"，
只判两件事：
  1. 数字是现量的，不是文档里手抄的（方案原文写"近 472KB"，实测已经变了）；
  2. 谁把它撑大了，要当场看得见，而不是等上线后用户说"打开慢"。
预算值就是当前实测值向上取整：改动越过这条线就判红，逼着人要么认下来更新基线、
要么把新代码拆成按需加载。基线不写"目标"，只写"现在在哪"。
*/
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import assert from "node:assert";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ASSETS = path.join(ROOT, "app/src/main/assets");

// 预算＝本轮实测值向上取整到 2KB。要变小就往下改，要变大必须先在这里说清为什么。
// 2026-10-22 r179：B03/B04/B09（常用餐食、档案四段、权限中心）与 B08（私信四态、
// 单条重试、重连补拉、通话失败分型）落地，按实测抬高。B08 让 features.js 多了约 7KB，
// 这是功能本身的大小，不是顺手塞进来的；要再往上抬请先回答"这批字节买到了什么"。
const BUDGET = {
  "app.js": { raw: 280_576, gzip: 92_160 },
  "features.js": { raw: 270_336, gzip: 79_872 },
  "index.html": { raw: 122_880, gzip: 30_720 },
  "style.css": { raw: 88_064, gzip: 20_480 },
  "features.css": { raw: 81_920, gzip: 22_528 },
  // r182: 20 original frames and wardrobe live in their own bounded files.
  "bubble-themes.js": { raw: 32_768, gzip: 10_240 },
  "bubble-themes.css": { raw: 24_576, gzip: 6_144 },
};

const results = [];
let failed = 0;
function check(name, ok, detail) {
  results.push(`${ok ? "绿" : "红"} ${name}${detail ? "  -> " + detail : ""}`);
  if (!ok) failed++;
}

const measured = {};
for (const file of Object.keys(BUDGET)) {
  const text = fs.readFileSync(path.join(ASSETS, file));
  measured[file] = { raw: text.length, gzip: zlib.gzipSync(text, { level: 9 }).length };
}

for (const [file, limit] of Object.entries(BUDGET)) {
  const now = measured[file];
  check(`${file} 原始体积没越过预算`, now.raw <= limit.raw,
        `实测 ${now.raw} B / 预算 ${limit.raw} B`);
  check(`${file} gzip 后没越过预算`, now.gzip <= limit.gzip,
        `实测 ${now.gzip} B / 预算 ${limit.gzip} B`);
}

const shell = Object.values(measured).reduce((sum, file) => sum + file.gzip, 0);
const artBytes=['bubble-ai.png','bubble-moon.png'].reduce((sum,file)=>sum+fs.statSync(path.join(ASSETS,file)).size,0);
check('两款原创插画总量有界，按需加载', artBytes<=4_500_000, `${artBytes} B / 4500000 B；不加入首页预缓存`);
check("首屏关键资源（HTML+JS+CSS）gzip 合计有数可报", shell > 0, `${shell} B`);

// 内联事件处理器：C11 要逐步移除后引入 CSP。这里量的是"还剩多少"，
// 每移掉一处这条线就该往下走；只许降不许升，防止新代码继续用内联写法。
const html = fs.readFileSync(path.join(ASSETS, "index.html"), "utf8");
const inline = (html.match(/\son(click|input|change|submit|focus|blur|keydown|load|error)=/g) || []).length;
// 基线用本文件这个正则现量得到（含 focus/blur/load/error）。
// 只许降不许升：C11 的前提是先移除内联处理器，再谈正式 CSP。
//
// 2026-10-22 r179 这里发生了一次回退：B03/B04/B09 的新弹窗沿用了仓库里既有的
// onclick="..." 写法，从 186 涨到 196。基线跟着抬到实测值，但把回退写在输出里，
// 不洗成"一直就是这样"——下一批要先把这 10 处连同原有的一并按模块摘掉。
const INLINE_BASELINE = 196;
const INLINE_AT_FIRST_MEASURE = 186;
check("index.html 内联事件处理器没有变多", inline <= INLINE_BASELINE,
      `实测 ${inline} 处 / 基线 ${INLINE_BASELINE} 处`);
if (inline > INLINE_AT_FIRST_MEASURE) {
  results.push(`红 内联处理器比首次量得的多出 ${inline - INLINE_AT_FIRST_MEASURE} 处，` +
               `CSP 前提在往后退（首次 ${INLINE_AT_FIRST_MEASURE} → 现在 ${inline}）`);
  failed++;
}

// CSP 还没上（要先移除内联处理器），但"没上"必须是看得见的状态而不是没人想起。
const hasCsp = /Content-Security-Policy/.test(
  fs.readFileSync(path.join(ROOT, "server.py"), "utf8")) ||
  /Content-Security-Policy/.test(fs.readFileSync(path.join(ASSETS, "index.html"), "utf8"));
check("CSP 现状要么已启用、要么明确记为未启用", true,
      hasCsp ? "已出现 CSP 头，需按 WebView 桥/音视频/导出逐项验放行"
             : "未启用：内联处理器仍有 " + inline + " 处，正式 CSP 要等这一步做完");

console.log(JSON.stringify(measured, null, 0));
for (const line of results) console.log("  " + line);
console.log(failed ? `FAIL: ${failed} 条红` : `PASS: ${results.length} 条全绿`);
process.exit(failed ? 1 : 0);
