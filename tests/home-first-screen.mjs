// B01 首页围绕“今天需要做什么”判据：纯 node 读产品源码 + 假 DOM 跑真 app.js，不起浏览器。
// 每条都按“正向顺序 / 真点击 / 两种状态 / 未知不是 0 / 规则会变 / 能力没丢”钉住，
// 任何一条被改坏都必须红，否则这条判据等于没写。
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { makeCtx, loadJs } from './dom-fixture.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const HTML = fs.readFileSync(path.join(ROOT, 'app/src/main/assets/index.html'), 'utf8');
const DASH = HTML.slice(HTML.indexOf('id="panel-dashboard"'), HTML.indexOf('id="panel-takeout"'));

const R = [];
let bad = 0;
function check(name, fn) {
  try {
    fn();
    R.push('绿 ' + name);
  } catch (e) {
    bad++;
    R.push('红 ' + name + '\n      ' + String((e && e.message) || e).split('\n')[0]);
  }
}
function need(cond, why) {
  if (!cond) throw new Error(why);
}

// 一个全新 vm：载入仓库里那份 app.js，再加一个“今天”的固定坐标，不依赖跑测试那天的真实日期。
const h = makeCtx();
loadJs(h.context);
const run = (x) => vm.runInContext(x, h.context);
const txt = (id) => String(h.mkEl(id).innerText);
run('state.user={username:"alice"};state.token="tk";state.dashboardLoaded=true;state.todayDate="2026-10-23";');

// ===== 1. 首屏 DOM 顺序：三件事 → 同步状态 → 下一步 → 净缺口/进度环/体重读数 =====
check('首屏三组顺序是“三件事→同步→下一步”，且都排在净缺口/进度环/体重之前', () => {
  const at = (id) => DASH.indexOf('id="' + id + '"');
  for (const id of ['home-today', 'home-sync', 'home-next', 'net-deficit-val', 'gauge-circle', 'current-weight-summary']) {
    need(at(id) >= 0, '#panel-dashboard 里找不到 ' + id);
  }
  need(at('home-today') < at('home-sync'), '“今天三件事”必须排在同步状态之前');
  need(at('home-sync') < at('home-next'), '同步状态必须排在下一步动作之前');
  need(at('home-next') < at('net-deficit-val'), '下一步动作必须排在净缺口之前');
  need(at('home-next') < at('gauge-circle'), '下一步动作必须排在进度环之前');
  need(at('net-deficit-val') < at('current-weight-summary'), '体重读数必须还在“今天该做什么”之后');
  // 三件事自己的先后：记餐食 → 称体重 → 练一次
  need(at('home-do-meal') < at('home-do-weight'), '三件事顺序应为记餐食、称体重、练一次');
  need(at('home-do-weight') < at('home-do-workout'), '三件事顺序应为记餐食、称体重、练一次');
});

// ===== 2. 三项各有可点入口，点下去真的触发对应动作 =====
check('三项入口点下去真的跳到对应输入/训练页', () => {
  run('__hit=[];__meal=document.getElementById("input-meal-text");__meal.focus=function(){__hit.push("meal")};' +
      '__wt=document.getElementById("input-weight");__wt.focus=function(){__hit.push("weight")};' +
      'switchTab=function(t){__hit.push("tab:"+t)};renderHomeToday();');
  for (const id of ['home-do-meal', 'home-do-weight', 'home-do-workout']) {
    need(typeof h.mkEl(id).onclick === 'function', id + ' 没有可点处理器');
  }
  h.mkEl('home-do-meal').onclick();
  h.mkEl('home-do-weight').onclick();
  h.mkEl('home-do-workout').onclick();
  const hit = JSON.stringify(run('__hit'));
  need(hit === '["meal","weight","tab:workout"]', '点击落点不对：' + hit);
});

// ===== 3. 状态机两个方向：未记录要催办，已记录要明说“今天已记” =====
check('未记录三件事都在催；已记录三项都写“今天已记”', () => {
  run('state.mealDiary=[];state.weightHistory=[{full_date:"2026-10-22"}];state.workoutDoneToday=false;renderHomeToday();');
  for (const id of ['home-state-meal', 'home-state-weight', 'home-state-workout']) {
    need(txt(id).includes('还没'), id + ' 未记录时没有催办：' + txt(id));
    need(!txt(id).includes('今天已记'), id + ' 未记录却写成已记：' + txt(id));
  }
  run('state.mealDiary=[{id:1,cal:520}];state.weightHistory=[{full_date:"2026-10-22"},{full_date:"2026-10-23"}];state.workoutDoneToday=true;renderHomeToday();');
  for (const id of ['home-state-meal', 'home-state-weight', 'home-state-workout']) {
    need(txt(id).includes('今天已记'), id + ' 已记录却没有写“今天已记”：' + txt(id));
  }
  need(h.mkEl('home-do-workout').classList.contains('done'), '已记录项没有标成完成态');
});

// ===== 4. 同步状态：拿不到就是“未知”，一个数字 0 都不许出现；真实的零才写“都已同步” =====
check('同步状态读不到时显示“未知”，且不出现数字 0', () => {
  const store = h.sandbox.localStorage;
  const origGet = store.getItem;
  store.getItem = () => { throw new Error('blocked'); };
  try {
    run('renderHomeToday()');
  } finally {
    store.getItem = origGet;
  }
  const sync = txt('home-sync-draft') + ' / ' + txt('home-sync-at');
  need(sync.includes('未知'), '拿不到数据时没有写“未知”：' + sync);
  need(!/[0-9]/.test(sync), '拿不到数据时出现了数字（不许拿 0 冒充）：' + sync);
});

check('确实没有待同步草稿时才写“都已同步”，不写 0；成功同步过才写时间', () => {
  run('renderHomeToday()');
  need(txt('home-sync-draft') === '都已同步', '零草稿应写“都已同步”：' + txt('home-sync-draft'));
  run('homeMarkSync();renderHomeToday()');
  need(/\d{1,2}:\d{2}$/.test(txt('home-sync-at')), '同步成功后应写具体时间：' + txt('home-sync-at'));
  need(/\d+ 笔待同步/.test(run('(function(){localStorage.setItem("QINGSU_DRAFTS_alice",JSON.stringify([{id:"a"},{id:"b"}]));renderHomeToday();return document.getElementById("home-sync-draft").innerText})()')),
       '有草稿时应报笔数');
});

// ===== 5. 下一步动作是按规则算出来的：固定输入给确定文案，换输入文案就变 =====
check('下一步动作由记录状态算出（换一组输入文案必须变）', () => {
  run('state.dashboardLoaded=true;state.todayDate="2026-10-23";state.mealDiary=[];state.weightHistory=[];state.workoutDoneToday=false;renderHomeToday();');
  const empty = txt('home-next-text');
  need(empty === '先记今天吃的第一餐', '今天没记餐时的建议不对：' + empty);
  run('state.mealDiary=[{id:1}];state.weightHistory=[];state.workoutDoneToday=false;renderHomeToday();');
  const mid = txt('home-next-text');
  need(mid !== empty, '只记了餐，建议却没变：' + mid);
  run('state.mealDiary=[{id:1}];state.weightHistory=[{full_date:"2026-10-23"}];state.workoutDoneToday=true;renderHomeToday();');
  const full = txt('home-next-text');
  need(full === '今天记全了，去看看这周的完成度', '三件都记满时的建议不对：' + full);
  need(full !== mid && full !== empty, '三件记满后建议没有跟着状态变');
});

// ===== 6. 现有能力没丢：净缺口、进度环、体重读数、训练卡片都还在，且排在三件事之后 =====
check('净缺口/进度环/体重读数/训练卡片四个 id 都还在', () => {
  for (const id of ['net-deficit-val', 'gauge-circle', 'current-weight-summary', 'workout-exercises-card']) {
    need(HTML.indexOf('id="' + id + '"') >= 0, '现有能力丢了：' + id);
  }
  need(HTML.indexOf('id="workout-exercises-card"') > HTML.indexOf('id="home-today"'), '训练卡片应排在“今天该做什么”之后');
  // 五个底部导航入口原样保留：方案要求先测可发现性再谈改导航
  need((HTML.match(/class="nav-item/g) || []).length === 5, '底部导航不再是五个入口');
  for (const t of ['dashboard', 'community', 'messages', 'me', 'tools']) {
    need(HTML.includes('id="nav-' + t + '"'), '导航入口丢了：' + t);
  }
});

for (const line of R) console.log('  ' + line);
console.log(`\n=== B01 首页首屏：${R.length} 条，绿 ${R.length - bad}，红 ${bad} ===`);
process.exit(bad ? 1 : 0);
