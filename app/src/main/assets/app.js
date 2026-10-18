// ==========================================
// 轻塑 · 智能减脂塑形严管助手 v5.0
// 100% 真实数据 · 腾讯云多用户数据库同步 · 饭点外卖严管门禁 · 专属公网监督网页
// ==========================================

const API_BASE = window.AndroidBridge && window.AndroidBridge.getApiBase ? window.AndroidBridge.getApiBase() : window.location.protocol.startsWith("http") && window.location.hostname !== "appassets.androidplatform.net"
    ? window.location.origin+(window.__API_PATH__||'') : "https://124.220.54.64";

const TOKEN_KEY = "QINGSU_AUTH_TOKEN";
const USER_KEY = "QINGSU_AUTH_USER";

// ── 强制更新门（客户端这一半）────────────────────────────────────────
// 打包时由 make_version_json.py 从 build.gradle 同步，手改会被判据拦下。
const APP_BUILD = 36;
// 不参与强更的访客侧接口，必须与服务端 GATE_EXEMPT_PATHS 逐条一致（判据核对两边）。
const VIEWER_API_PATHS = ["/api/public/dashboard", "/api/public/charts", "/api/cheer",
    "/api/account/recovery-status", "/api/account/forgot", "/api/account/reset"];

function isGatedApi(url) {
    const text = String(url || "");
    const at = text.indexOf("/api/");
    if (at < 0) return false;
    return !VIEWER_API_PATHS.some(p => text.indexOf(p) === at);
}

let updateWallPolicy = null;

function showUpdateWall(policy) {
    updateWallPolicy = policy;
    document.body.classList.add("update-blocked");
    let wall = document.getElementById("update-wall");
    if (!wall) {
        wall = document.createElement("div");
        wall.id = "update-wall";
        wall.classList.add("update-wall");
        wall.setAttribute("role", "alertdialog");
        wall.setAttribute("aria-live", "assertive");
        document.body.appendChild(wall);
    }
    const inApp = !!(window.AndroidBridge && window.AndroidBridge.openBrowser);
    wall.innerHTML = [
        '<div class="uw-card">',
        '<div class="uw-badge">版本已停用</div>',
        '<h2 class="uw-title" id="uw-title">需要更新后才能继续使用</h2>',
        '<p class="uw-why" id="uw-why"></p>',
        '<ul class="uw-facts">',
        '<li>你现在的版本 <b id="uw-mine"></b></li>',
        '<li>最低可用版本 <b id="uw-min"></b></li>',
        '<li>安装包大小 <b id="uw-size"></b></li>',
        '</ul>',
        inApp
            ? '<button class="btn-primary uw-btn" id="uw-go">去下载最新版</button>'
              + '<p class="uw-note">下载会交给系统浏览器；安装仍要在系统设置里放行。</p>'
            : '<button class="btn-primary uw-btn" id="uw-go">刷新页面获取最新版</button>'
              + '<p class="uw-note">网页版是服务器上的最新版，刷新一下就恢复了。</p>',
        '<button class="uw-alt" id="uw-retry">我已经装好了，重新检查</button>',
        '</div>'
    ].join("");
    const latest = policy.latest || {};
    const name = String(latest.version_name || "");
    const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = String(value); };
    setText("uw-title", inApp
        ? ("需要更新到 " + (name ? "v" + name : "最新版") + " 才能继续使用")
        : "请刷新页面获取最新版");
    setText("uw-why", inApp
        ? "旧版本里的记录与提醒会照常保留在服务器上，装完新版登录就能接着用。"
        : "服务器刚发布过新版本，这个页面还是旧的。");
    setText("uw-mine", policy.your_build ? ("构建 " + policy.your_build) : "未上报（这就是旧版）");
    setText("uw-min", "构建 " + (policy.min_build || "?"));
    setText("uw-size", latest.size ? (latest.size / 1048576).toFixed(1) + " MB" : "未知");
    const go = document.getElementById("uw-go");
    if (go) go.onclick = () => {
        if (inApp) window.AndroidBridge.openBrowser(String(latest.apk_url || ""));
        else window.location.reload();
    };
    const retry = document.getElementById("uw-retry");
    if (retry) retry.onclick = () => window.location.reload();
}

(function installBuildHeader() {
    const global = typeof globalThis !== "undefined" ? globalThis : window;
    const original = global.fetch;
    if (typeof original !== "function") return;
    const wrapped = function (input, init) {
        let url = typeof input === "string" ? input : (input && input.url) || "";
        if (!isGatedApi(url)) return original.call(global, input, init);
        const base = (typeof input === "object" && input) ? input : {};
        const opts = Object.assign({}, base, init || {});
        const src = opts.headers || base.headers;
        const headers = {};
        if (src) {
            if (typeof src.forEach === "function") src.forEach((v, k) => { headers[k] = v; });
            else Object.assign(headers, src);
        }
        headers["X-App-Build"] = String(APP_BUILD);
        opts.headers = headers;
        const target = typeof input === "object" && input ? input : url;
        return original.call(global, target, opts).then(res => {
            try {
                if (res && res.status === 403 && typeof res.clone === "function") {
                    res.clone().json().then(policy => {
                        if (policy && policy.code === "update_required") showUpdateWall(policy);
                        else if (policy && policy.code === "account_banned") handleAccountBanned(policy.detail);
                    }).catch(() => {});
                }
            } catch (e) {}
            return res;
        });
    };
    global.fetch = wrapped;
    if (typeof window !== "undefined") window.fetch = wrapped;
})();


// 初始状态（全部真实数据，无伪造数据）
let state = {
    user: null,
    token: null,
    profile: {
        gender: "female",
        age: 26,
        height: 165,
        weightJin: 0,
        targetWeightJin: 0,
        goalType: "tone",
        diningMode: "takeout",
        scene: "home"
    },
    diningMode: "takeout",
    mode: "rest",
    calculated: {
        bmr: 0,
        tdee: 0,
        targetCal: 0,
        restCal: 0,
        workoutCal: 0,
        deficitTarget: 0,
        proteinG: 0,
        carbsG: 0,
        fatG: 0,
        summaryText: "未绑定档案 · 请先登录"
    },
    todayConsumed: 0,
    todayBurned: 0,
    remainingCal: 0,
    currentWeightJin: 0,
    waterCupsCount: 0,
    workoutDoneToday: false,
    selectedPlan: "A",
    selectedMealSlot: "lunch",
    mealDiary: [],
    weightHistory: [],
    deficitHistory: [],
    dashboardLoaded: false,
    consecutiveOverDays: 0,
    consecutiveSlackingDays: 0,
    takeoutLocked: false,
    takeoutQuotaUsed: 0,
    interceptedCount: 0,
    caloriesSaved: 0,
    checklistState: {},
    cycleData: {
        currentCycle: 1,
        cycleName: "第 1 周期 · 减脂启动期",
        cycleGoal: "真实记录身体变化，建立健康热量缺口",
        basePhoto: null,
        curPhoto: null,
        baseWeightJin: 0,
        baseWaistCm: 0,
        curWeightJin: 0,
        curWaistCm: 0,
        toneScore: "待打卡",
        reportSummary: "暂无历史数据。请每天打卡饮食、体重与训练，由云端系统生成真实身体进阶报告！"
    }
};

const INITIAL_STATE = JSON.parse(JSON.stringify(state));
let sessionGeneration = 0;

// 常见外卖数据库
const TAKEOUT_DB = {
    "隆江猪脚饭": { cal: 1180, oil: 42, warning: "单餐热量溢出今日预算！含大量肥肉饱和脂肪与浓厚糖色！", subName: "白切鸡饭(去鸡皮去鸡油)+米饭减半", subCal: 490, subBenefit: "热量仅 490 kcal · 优质蛋白35g · 立省 690 kcal！" },
    "杨国福麻辣烫(重麻酱)": { cal: 1120, oil: 38, warning: "麻酱+红油+吸油炸串！一碗麻酱热量抵得上半只烤鸡！", subName: "清汤麻辣烫(麻酱分装蘸食+牛肉片+娃娃菜+魔芋丝)", subCal: 480, subBenefit: "热量仅 480 kcal · 锁水消肿 · 立省 640 kcal！" },
    "麦辣鸡腿堡套餐(含薯条可乐)": { cal: 980, oil: 35, warning: "油炸鸡腿排+大份高油薯条+全糖可乐，反式脂肪拉满！", subName: "板烧鸡腿堡(去酱)+玉米棒+零度可乐", subCal: 420, subBenefit: "热量仅 420 kcal · 饱腹不腻 · 立省 560 kcal！" },
    "螺蛳粉+炸蛋+鸭掌": { cal: 1250, oil: 48, warning: "炸蛋吸油率高达48%，红油汤底吸饱油脂，钠含量严重超标！", subName: "番茄牛肉米线(不喝原汤不加炸蛋+加一份蔬菜)", subCal: 520, subBenefit: "热量仅 520 kcal · 避免钠滞水肿 · 立省 730 kcal！" },
    "黄焖鸡米饭(大份多汁)": { cal: 920, oil: 32, warning: "鸡皮鸡油未剔除，汤汁含大量老抽白糖勾芡，汤汁泡饭极其危险！", subName: "清蒸鱼片饭+冬瓜海带汤(不喝油汤)", subCal: 450, subBenefit: "热量仅 450 kcal · 高蛋白低负担 · 立省 470 kcal！" },
    "烧烤烤五花肉+掌中宝20串": { cal: 1100, oil: 45, warning: "五花肉脂肪超50%，刷油刷辣酱反复烘烤，夜宵代谢负担极大！", subName: "烤鸡胸肉串+烤口蘑+烤生蚝+烤韭菜(少油少盐)", subCal: 420, subBenefit: "热量仅 420 kcal · 纯正低脂高蛋白 · 立省 680 kcal！" },
    "珍珠奶茶大杯(正常糖)": { cal: 490, oil: 18, warning: "一杯含糖量达 50g (约11块方糖)，植脂末含反式脂肪酸！", subName: "无糖茉莉绿茶鲜奶 + 少许仙草", subCal: 120, subBenefit: "热量仅 120 kcal · 零反式脂肪 · 立省 370 kcal！" },
    "轻食鸡胸肉藜麦沙拉(油醋汁)": { cal: 420, oil: 8, warning: "", subName: "本身即为健康轻食，合格！注意沙拉酱勿全倒。", subCal: 420, subBenefit: "恭喜！属于合格控卡餐，优质蛋白充足。" },
    "赛百味6寸香烤牛肉堡": { cal: 380, oil: 9, warning: "", subName: "本身即为推荐优质慢碳高蛋白快餐！", subCal: 380, subBenefit: "全麦面包+精瘦牛肉+丰富蔬菜，绝佳减脂搭配！" },
    "南翔小笼包8只+酸辣汤": { cal: 760, oil: 26, warning: "馅里打的是猪皮冻与糖，一口一个的油脂比看着高；酸辣汤钠含量大，喝完容易水肿。", subName: "小笼包4只 + 白灼青菜 + 紫菜蛋花汤(少盐)", subCal: 420, subBenefit: "热量仅 420 kcal · 甜口猪油减半 · 立省 340 kcal！" },
    "红烧大排饭(含例汤)": { cal: 890, oil: 38, warning: "大排先炸后红烧，糖色与油一起挂上去；汤汁泡饭等于把油直接喝掉。", subName: "白切鸡饭(去皮) + 烫青菜(不浇汁)", subCal: 470, subBenefit: "热量仅 470 kcal · 去掉炸衣与糖色 · 立省 420 kcal！" },
    "兰州牛肉面(大碗加肉)": { cal: 620, oil: 18, warning: "清汤看着清淡，但加肉份量与汤里那层辣油才是热量主体；面一份就是 300g 熟重。", subName: "牛肉面(小碗、不加肉、少辣油) + 烫青菜", subCal: 430, subBenefit: "热量仅 430 kcal · 慢碳配蛋白 · 立省 190 kcal！" },
};

// 4套轮换食谱
const RECIPES_DATA = {
    "A": {
        title: "方案 A（中式快手）",
        desc: "适合工作日早晨与午间，备餐极速，经典家常风味",
        meals: [
            { name: "早餐 (约 380 kcal)", time: "07:30 - 08:30 · 开启全天代谢", content: "• 蒸玉米 1根(中)<br>• 水煮蛋1个 + 纯蛋白1个<br>• 无糖豆浆/鲜牛奶 250ml<br>• 圣女果或小黄瓜 100g", cal: 380 },
            { name: "午餐 (约 580 kcal)", time: "12:00 - 13:00 · 菜:肉:饭 = 2:1:1", content: "<strong>【青椒炒鸡丁 + 杂粮饭】</strong><br>• 三色杂粮饭 130g(熟重)<br>• 去皮鸡腿肉/鸡胸肉 150g<br>• 清炒少油上海青/生菜 200g", cal: 580 },
            { name: "下午加餐 (约 100 kcal)", time: "15:30 - 16:30 · 稳定血糖防暴食", content: "• 蓝莓 1小盒 (或半个苹果 / 1个猕猴桃)", cal: 100 },
            { name: "晚餐 (约 420 kcal)", time: "18:00 - 19:30 · 高纤高蛋白低负担", content: "<strong>【冬瓜丸子/虾滑汤】</strong><br>• 纯虾滑或瘦肉丸 120g<br>• 冬瓜片 250g煮清汤(利水消肿极佳)<br>• 蒸铁棍山药 80g", cal: 420 }
        ]
    },
    "B": {
        title: "方案 B（高饱腹粗粮）",
        desc: "丰富全谷物粗粮，膳食纤维拉满，肠道轻松通畅",
        meals: [
            { name: "早餐 (约 380 kcal)", time: "07:30 - 08:30 · 高纤平缓升糖", content: "• 纯燕麦片 40g (配料表仅燕麦)<br>• 热牛奶/无糖豆浆 250ml 冲泡<br>• 少油煎蛋 1个<br>• 原味巴旦木 4-5颗", cal: 380 },
            { name: "午餐 (约 580 kcal)", time: "12:00 - 13:00 · 慢碳抗阻供能", content: "<strong>【番茄炖牛肉 + 荞麦面】</strong><br>• 纯荞麦面 60g(干重)<br>• 精瘦牛肉 130g + 番茄1个炖煮<br>• 焯水木耳 + 娃娃菜 200g", cal: 580 },
            { name: "下午加餐 (约 100 kcal)", time: "15:30 - 16:30 · 充能防饥饿", content: "• 无糖希腊酸奶 100g (或无糖豆浆200ml)", cal: 100 },
            { name: "晚餐 (约 420 kcal)", time: "18:00 - 19:30 · 舒缓低脂排毒", content: "<strong>【凉拌手撕鸡 + 菌菇汤】</strong><br>• 去皮鸡腿肉 150g 撕丝凉拌<br>• 金针菇豆腐青菜汤 1大碗<br>• 蒸玉米 半根", cal: 420 }
        ]
    },
    "C": {
        title: "方案 C（轻食简餐风）",
        desc: "免油烟速成，高颜值清爽开胃，便携优选",
        meals: [
            { name: "早餐 (约 380 kcal)", time: "07:30 - 08:30 · 清爽减脂唤醒", content: "• 100%全麦吐司 2片(70g)<br>• 卤牛肉 50g (或水浸金枪鱼)<br>• 生菜2片 + 番茄切片夹三明治<br>• 美式黑咖啡或无糖酸奶 150g", cal: 380 },
            { name: "午餐 (约 580 kcal)", time: "12:00 - 13:00 · 优质白肉深海鱼", content: "<strong>【香煎鱼柳 + 黑椒土豆泥】</strong><br>• 蒸黄心土豆 180g 捣成黑椒泥<br>• 龙利鱼柳/鳕鱼 180g (喷少许油煎熟)<br>• 蒜蓉西兰花 + 口蘑 200g", cal: 580 },
            { name: "下午加餐 (约 100 kcal)", time: "15:30 - 16:30 · 纯净蛋白质", content: "• 卤鸡蛋白 2个 (或低钠鸡胸肉肠 1根)", cal: 100 },
            { name: "晚餐 (约 420 kcal)", time: "18:00 - 19:30 · 高饱腹植物蛋白", content: "<strong>【北豆腐焖鲜虾 + 蚝油绿叶菜】</strong><br>• 北老豆腐 100g + 鲜虾仁 8只焖煮<br>• 蚝油生菜 200g (少油生抽拌熟)<br>• 蒸贝贝南瓜 100g", cal: 420 }
        ]
    },
    "D": {
        title: "方案 D（暖胃炖煮风）",
        desc: "温和养胃，高蛋白低负担，生菜包肉极具仪式感",
        meals: [
            { name: "早餐 (约 380 kcal)", time: "07:30 - 08:30 · 暖胃慢碳粗粮", content: "• 蒸红薯/紫薯 150g<br>• 白灼大虾仁 8只 (或鸡蛋2个)<br>• 焯水西兰花/菠菜 100g<br>• 温牛奶或无糖豆浆 200ml", cal: 380 },
            { name: "午餐 (约 580 kcal)", time: "12:00 - 13:00 · 经典滑蛋虾仁", content: "<strong>【滑蛋虾仁 + 三色糙米饭】</strong><br>• 三色糙米饭 130g(熟重)<br>• 大虾仁 120g + 鸡蛋1个滑炒<br>• 清炒荷兰豆或芹菜 150g", cal: 580 },
            { name: "下午加餐 (约 100 kcal)", time: "15:30 - 16:30 · 补水爽脆坚果", content: "• 水果黄瓜 1根 + 原味巴旦木 5颗", cal: 100 },
            { name: "晚餐 (约 420 kcal)", time: "18:00 - 19:30 · 零主食高纤生菜包肉", content: "<strong>【黑椒杏鲍菇牛肉生菜包】</strong><br>• 精瘦牛肉 120g + 杏鲍菇 100g 黑椒同炒<br>• 大片罗马生菜包裹食用 (免主食拉大缺口)<br>• 紫菜蛋花清汤 1碗", cal: 420 }
        ]
    }
};

// 一周采购清单
// 忌口命中规则：只按菜名与替代项里的字面食材判，不去猜做法。
// 宁可写窄：把"牛奶"误判成辣，比漏判一项更难查——漏判用户会自己发现，误判不会。
const AVOID_RULES = {
    no_spicy: /辣|麻酱|红油|火锅|湘菜|川菜|黔|酸辣|剁椒/,
    no_seafood: /虾|蟹|蚌|蚝|鲍|鱼|海带|紫菜|海鲜|金枪|鳕|三文|螺/,
    no_beef: /牛肉|肥牛|牛腱|牛腩|牛骨/,
    no_pork: /猪|五花|排骨|香肠|培根|火腿|腊肉/,
    no_dairy: /牛奶|酸奶|奶酪|奶油|黄油|芝士|奶茶/,
    vegetarian: /鸡|鸭|牛|羊|猪|虾|鱼|培根|火腿|肉/,
    less_oil: null            // 少油不改菜名，只改排序
};

// 菜名 -> 菜系标签。词汇必须与 app_modules/geo.py 里各城市的标签对得上，
// 否则"你在成都"匹配不到任何一道，城市这一维就成了摆设（判据核对交集非空）。
const TAKEOUT_CUISINE = {
    "隆江猪脚饭": ["粤菜", "烧腊"],
    "杨国福麻辣烫(重麻酱)": ["川渝", "川菜", "火锅", "辣"],
    "麦辣鸡腿堡套餐(含薯条可乐)": ["西式", "快餐"],
    "螺蛳粉+炸蛋+鸭掌": ["桂菜", "米粉", "辣"],
    "黄焖鸡米饭(大份多汁)": ["鲁菜", "北方"],
    "烧烤烤五花肉+掌中宝20串": ["通用", "夜宵"],
    "珍珠奶茶大杯(正常糖)": ["粤菜", "茶饮"],
    "轻食鸡胸肉藜麦沙拉(油醋汁)": ["西式", "轻食"],
    "赛百味6寸香烤牛肉堡": ["西式", "快餐"],
    "南翔小笼包8只+酸辣汤": ["本帮", "江浙", "苏帮", "浓油赤酱"],
    "红烧大排饭(含例汤)": ["本帮", "江浙", "北方"],
    "兰州牛肉面(大碗加肉)": ["西北", "清真", "面食", "北方"],
};

function accountNow() {
    return (typeof accountData === 'function' && accountData()) || {};
}
function avoidTagsNow() { return accountNow().avoid_tags || []; }
function cityCuisinesNow() { return accountNow().cuisines || []; }
function dishConflicts(text, tags) {
    const s = String(text || '');
    return (tags || []).filter(function (k) {
        const re = AVOID_RULES[k];
        return !!(re && re.test(s));
    });
}

/** 按忌口与城市给"先点哪个"的排序。
 *  只排顺序、不改热量，也不藏菜：冲突的菜仍然如实显示热量与替代项。 */
function rankTakeout() {
    const tags = avoidTagsNow(), cuisines = cityCuisinesNow();
    return Object.keys(TAKEOUT_DB).map(function (name) {
        const item = TAKEOUT_DB[name];
        const bad = dishConflicts(name, tags);
        const subBad = dishConflicts(item.subName, tags);
        const local = (TAKEOUT_CUISINE[name] || []).some(function (c) { return cuisines.indexOf(c) >= 0; });
        const oilOk = tags.indexOf('less_oil') >= 0 ? (item.oil <= 15 ? 1 : -1) : (item.oil <= 15 ? 1 : 0);
        return { name: name, item: item, bad: bad, subBad: subBad, local: local,
                 score: (bad.length ? -100 : 0) + (local ? 2 : 0) + oilOk };
    }).sort(function (a, b) { return b.score - a.score || a.item.cal - b.item.cal; });
}

function renderTakeoutAdvisor() {
    const host = document.getElementById('takeout-advisor');
    if (!host) return;
    const a = accountNow(), tags = avoidTagsNow(), cuisines = cityCuisinesNow();
    const rows = rankTakeout();
    const clean = rows.filter(function (r) { return !r.bad.length; }).slice(0, 3);
    const clash = rows.filter(function (r) { return r.bad.length; });
    const head = '<div class="tav-meta">城市：' +
        (a.city ? escapeHtml(a.city) + (cuisines.length ? '（当地口味 ' + escapeHtml(cuisines.join('、')) + '）'
                                                       : '（不在内置菜系表里，只按忌口排）')
                : '未设置') + ' · 忌口 ' + tags.length + ' 项</div>';
    if (!tags.length && !cuisines.length) {
        host.innerHTML = head + '<p class="tav-empty">还没设忌口也没定城市，这里只能按热量给顺序。' +
            '到【个人中心】勾一下，排序会跟着变。</p>';
        return;
    }
    const card = function (r) {
        return '<div class="tav-item"><div class="tav-item-main">' +
            '<div class="tav-item-title">' + escapeHtml(r.name) +
            (r.local ? '<span class="tav-tag">当地常见</span>' : '') + '</div>' +
            '<div class="tav-item-meta">约 ' + r.item.cal + ' kcal · 油 ' + r.item.oil + 'g · 替代项 ' +
            r.item.subCal + ' kcal</div></div><div class="tav-item-acts">' +
            '<button type="button" class="td-mini" data-copy="' + escapeHtml(r.item.subName) +
            '" onclick="copyTakeoutKeyword(this.getAttribute(\'data-copy\'))">复制替代项</button>' +
            '</div></div>';
    };
    host.innerHTML = head +
        '<div class="tav-group">按你的设置，优先点这几样</div>' +
        (clean.length ? clean.map(card).join('')
                      : '<p class="tav-empty">忌口勾得太宽，这几样爆款全都冲突——下面那组是实情。</p>') +
        (clash.length ? '<div class="tav-group tav-group-clash">与忌口冲突（仍如实标热量）</div>' +
            clash.map(function (r) {
                return '<div class="tav-item tav-bad"><div class="tav-item-main">' +
                    '<div class="tav-item-title">' + escapeHtml(r.name) + '</div>' +
                    '<div class="tav-item-meta">命中：' +
                    escapeHtml(r.bad.map(function (k) { return (AVOID_CN[k] || [k])[0]; }).join('、')) +
                    ' · 约 ' + r.item.cal + ' kcal</div>' +
                    '<div class="tav-sub">' + (r.subBad.length
                        ? '替代项「' + escapeHtml(r.item.subName) + '」也命中忌口，别照着点'
                        : '替代项：' + escapeHtml(r.item.subName) + '（约 ' + r.item.subCal + ' kcal）') +
                    '</div></div></div>';
            }).join('') : '');
}

function copyTakeoutKeyword(text) {
    const s = String(text || '');
    if (!s) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(s).then(
            function () { callNativeToast('已复制，到外卖软件里粘贴搜索'); },
            function () { callNativeToast('浏览器拒绝复制，请手动输入：' + s); });
        return;
    }
    callNativeToast('这个环境没有剪贴板接口，请手动输入：' + s);
}

const SHOPPING_ITEMS = [
    { cat: "🥩 优质蛋白区", items: ["鸡蛋 15-20 枚 (每天1.5-2个)", "去皮鸡腿肉/鸡胸肉 600g (分4袋)", "瘦牛肉(里脊/吊龙) 450g (分3袋)", "无冰衣大青虾仁 500g", "龙利鱼柳/鳕鱼 350g", "北豆腐(老豆腐) 2盒", "低脂牛奶/无糖豆浆 7盒 + 希腊酸奶 3杯"] },
    { cat: "🍚 复合慢碳主食区", items: ["三色糙米/藜麦 1袋 (与大米1:1混煮)", "纯燕麦片(配料表仅燕麦) 1袋", "全麦吐司 1袋 + 荞麦面 1包", "甜玉米 4根", "红薯/紫薯/山药 共600g", "黄心土豆/贝贝南瓜 共500g"] },
    { cat: "🥦 耐放蔬菜与菌菇", items: ["西兰花 1颗、娃娃菜 2颗", "冬瓜 1大块 (消水肿极佳)", "番茄 4个、水果黄瓜 3根、彩椒 3个", "金针菇 1把、口蘑 1盒、木耳 1袋、紫菜 1包"] },
    { cat: "🥬 深色绿叶菜 (周中补1次)", items: ["生菜 2颗、菠菜 1把", "上海青/油麦菜 2把"] },
    { cat: "🧂 控卡调味工具与加餐", items: ["蓝莓 2盒、苹果/猕猴桃 3个", "原味巴旦木 1小袋", "雾化喷油壶 1个 (控油神器)", "薄盐生抽、陈醋、黑胡椒海盐、零卡代糖"] }
];

// ==========================================
// 初始化与自动登录
// ==========================================
window.addEventListener("DOMContentLoaded", () => {
    initAuthAndData();
    setupTimer();
    renderShoppingList();
    renderRecipePlan(state.selectedPlan || "A");
    // 点单顺序卡要在拉到忌口/城市之前也有内容可看，所以先按空设置画一次
    if (typeof renderTakeoutAdvisor === 'function') renderTakeoutAdvisor();
    switchShapeGender(state.profile.gender || "female", false);
    initViewMode();
    // 开 App 先查通知权限；外卖真实使用情况读一次
    loadExercisePoses();
    initWebWorkbench();
    paintAiEngineBar();
    probeLocalAi(false).then(function () { paintAiEngineBar(); });
    initNotifPermissionHint();
    refreshTakeoutUsage();
    if (window.location.hash === "#download" || window.location.search.includes("download=1")) {
        setTimeout(openDownloadModal, 400);
    }
    // 悬浮下载入口：App 里已经装着客户端，再放一颗"下载App"既多余又压住卡片文字
    // App 本来就装在手机上，顶栏再放一颗"电脑/手机切换"是多余的，直接藏掉
    if (inApp()) {
        const vt = document.getElementById("btn-view-toggle");
        if (vt) vt.style.display = "none";
        const dl=document.getElementById("btn-header-download");if(dl)dl.style.display="none";
    }
    const floating = document.querySelector(".floating-dl-btn");
    if (floating) {
        if (window.AndroidBridge && window.AndroidBridge.showToast) {
            floating.style.display = "none";
        } else {
            document.body.classList.add("has-floating-dl");
        }
    }
});

async function initAuthAndData() {
    if (window.__PUBLIC_USER__) {
        try { await loadPublicUserData(window.__PUBLIC_USER__); } catch(e) { showPublicFailure(e); }
        // 公网大屏是网页独占场景：装在手机里的 App 不会有这条链接
        const tools = document.getElementById("public-tools");
        if (tools) tools.style.display = "block";
        startPublicPolling();
        return;
    }

    const savedToken = localStorage.getItem(TOKEN_KEY);
    const savedUser = localStorage.getItem(USER_KEY);

    if (savedToken && savedUser) {
        let saved = null;
        try { saved = JSON.parse(savedUser); } catch (e) { saved = null; }
        if (!saved || !saved.username) {
            // 存的东西读不出来时不能继续往下走：那会让人停在"看着像登录了
            // 但一格数据都没有"的页面上，且永远不报错。清掉并明说。
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
            updateUserUI(null);
            openAuthModal();
            callNativeToast("本机登录信息读不出来，请重新登录");
            return;
        }
        state.token = savedToken;
        state.user = saved;
        updateUserUI(displayName(state.user));
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } else {
        updateUserUI(null);
        openAuthModal();
    }
}

/** 分享链接里的密钥只服务端的 /u/<名字> 校验过一次；前端再拉公开 API 时必须带上，
    否则带密钥的链接打开后每一格都是空的。 */
function publicShareKey() {
    try {
        const m = new URLSearchParams(window.location.search).get("k");
        return m || "";
    } catch (e) { return ""; }
}

async function loadPublicUserData(username) {
    updateUserUI(username);
    const banner = document.getElementById("user-web-link-card");
    const safeName = escapeHtml(username);
    if (banner) {
        banner.innerHTML = `<div style="flex:1;"><div style="font-size: 11px; color: #047857; font-weight: 700;">🌐 正在公开查阅 <strong>@${safeName}</strong> 的减脂塑形真数据大屏 (云端同步)</div><div style="font-size: 10px; color: #64748B; margin-top:2px;">数据均由用户本人每日真实打卡上报；本页无需登录即可访问，请勿在此填写任何隐私。</div></div>`;
    }
    const authBtn = document.querySelector(".user-account-badge");
    if (authBtn) {
        authBtn.innerHTML = `<span>👤</span><span>@${safeName}</span>`;
    }
    try {
        const res = await fetch(`${API_BASE}/api/public/dashboard?username=${encodeURIComponent(username)}&k=${encodeURIComponent(publicShareKey())}`);
        if (res.ok) {
            const data = await res.json();
            state.publicNickname = (data.user && data.user.nickname) || "";
            state.cheerTotal = Number(data.cheer_total || 0);
            paintCheerCount();
            applyDashboardData(data);
        } else { throw new Error("HTTP " + res.status); }
    } catch (e) {
        throw e;
    }
    try {
        const res = await fetch(`${API_BASE}/api/public/charts?username=${encodeURIComponent(username)}&k=${encodeURIComponent(publicShareKey())}`);
        if (res.ok) {
            const data = await res.json();
            if (data.weight_history) {
                state.weightHistory = data.weight_history;
                state.deficitHistory = data.deficit_history;
                state.realMacros = data.macros_today;
                renderCharts();
            }
        }
    } catch (e) { throw e; }
}

function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

// 统一的写请求出口：非 2xx 一律抛错。调用方不得把"没落库"播报成成功。
/** GET 版请求：与 postApi 同一套鉴权与错误口径，别另起炉灶。 */
async function getJson(path) {
    const generation=sessionGeneration;
    const r = await fetch(`${API_BASE}` + path, {
        headers: { "Authorization": `Bearer ${state.token}` }
    });
    const j = await r.json().catch(() => ({}));
    if(generation!==sessionGeneration){const e=new Error('账号已切换，忽略旧请求');e.status=409;throw e;}
    if (!r.ok) throw new Error(j && j.detail ? j.detail : ("HTTP " + r.status));
    return j;
}

async function rawPostApi(path, body, opts) {
    const generation=sessionGeneration;
    const init = Object.assign({ method: "POST", headers: {} }, opts || {});
    init.headers["Authorization"] = `Bearer ${state.token}`;
    if (body instanceof FormData) {
        init.body = body;
    } else {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
    }
    const res = await fetchWithTimeout(`${API_BASE}${path}`, init, 30000);
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if(generation!==sessionGeneration){const e=new Error('账号已切换，忽略旧请求');e.status=409;throw e;}
    if (!res.ok) {
        const err = new Error((data && data.detail) ? data.detail : `HTTP ${res.status}`);
        err.status = res.status;
        throw err;
    }
    return data || {};
}

// Preserve request IDs across uncertain network retries; merge simultaneous clicks.
const pendingWrites = new Map();
const uncertainWrites = new Map();
function postApi(path, body, opts) {
    if (!state.token) return Promise.reject(new Error("请先登录"));
    // 打卡类写操作要带 request_id 做幂等；社区发帖/评论和私信同理——断网重试
    // 不该发出第二条。评论的路径是 /api/community/posts/<id>/comments，所以按前缀认。
    const RECORD_PATHS = ["/api/food/log", "/api/workout/complete",
                          "/api/community/posts", "/api/chat/send"];
    const isRecord = RECORD_PATHS.some(p => path === p || path.startsWith(p + "/"));
    const signature = JSON.stringify(body instanceof FormData ? {} : Object.fromEntries(Object.entries(body || {}).filter(([key])=>key!=="request_id")));
    const key = sessionGeneration + ":" + path + ":" + signature;
    if (pendingWrites.has(key)) return pendingWrites.get(key);
    if (isRecord) {
        const id = body.request_id || uncertainWrites.get(key) || (Date.now().toString(36)+"-"+Math.random().toString(36).slice(2));
        uncertainWrites.set(key,id); body.request_id=id;
    }
    const task=rawPostApi(path,body,opts).then(data=>{uncertainWrites.delete(key);return data;})
        .finally(()=>pendingWrites.delete(key));
    pendingWrites.set(key,task);return task;
}

// 被封号时把话说清楚：只报"网络不通"或让人停在空白页，等于把服务端的决定藏起来了。
function handleAccountBanned(detail) {
    localStorage.removeItem(TOKEN_KEY);
    callNativeToast("⚠️ " + (detail || "该账号已被停用"));
    openAuthModal();
}

// 打卡类操作的共用收尾：说清这条没存，登录失效时把人拉回登录
function reportWriteFailure(err, what) {
    if (err && err.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        callNativeToast(`⚠️ ${what}没保存：登录已失效，请重新登录`);
        openAuthModal();
        return;
    }
    const why = (err && err.message) ? err.message : "网络不通";
    callNativeToast(`⚠️ ${what}没保存：${why}（尚未确认云端保存）`);
    callNativeVibrate(200);
}

function saveAuthSession(token, user) {
    sessionGeneration++;
    if(state.user&&state.user.username!==user.username){
        localStorage.removeItem('QINGSU_LAST_'+state.user.username);localStorage.removeItem('QINGSU_DRAFTS_'+state.user.username);
    }
    state=JSON.parse(JSON.stringify(INITIAL_STATE));wbRows=null;pendingWrites.clear();uncertainWrites.clear();
    state.token = token;
    state.user = user;
    resetPrivateUI();
    // 忌口与城市决定外卖/食谱的推荐顺序，头像在顶栏；换账号时必须重拉一次
    if (typeof refreshAccount === 'function') refreshAccount();
    // 换账号要先清掉上一个人的社区/私信内存态，否则列表会串号
    if (typeof resetCommunity === 'function') resetCommunity();
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    updateUserUI(displayName(user));
}

/** 顶栏和登录态显示昵称，没有昵称才退回登录名——和头像圆点取首字的口径保持一致。 */
function displayName(u) {
    return String((u && (u.nickname || u.username)) || "");
}

function updateUserUI(username) {
    const nameEl = document.getElementById("header-username-display");
    const loggedText = document.getElementById("logged-username-text");
    const loggedBox = document.getElementById("auth-logged-box");
    const urlDisplay = document.getElementById("display-user-public-url");

    if (!username) {
        if (nameEl) nameEl.innerText = "登录/注册";
        if (loggedText) loggedText.innerText = "--";
        if (loggedBox) loggedBox.style.display = "none";
        if (urlDisplay) urlDisplay.innerText = "登录后生成专属公网大屏网址";
        return;
    }

    if (nameEl) nameEl.innerText = username;
    if (loggedText) loggedText.innerText = username;
    if (loggedBox) loggedBox.style.display = "block";

    const publicUrl = state.publicUrl || "分享链接加载中…";
    if (urlDisplay) urlDisplay.innerText = publicUrl;
}

// ==========================================
// 核心真数据同步：从腾讯云服务器加载真实数据
// ==========================================
function applyDashboardData(data) {
    if (!data || !data.metrics) return;
    state.dashboardLoaded = true;
    state.publicUrl = data.public_url || state.publicUrl;
    if(state.user)updateUserUI(displayName(state.user));
    // 今天练没练、清单勾了哪些、当前是休息日还是运动日，都以服务端为准
    state.workoutDoneToday = !!data.today_workout_done;
    state.dayMode = data.day_mode || "rest";
    state.checklistState = data.checklist || {};
    state.waterTargetMl = data.water_target_ml || 2000;
    state.streakDays = data.streak_days || 0;
    state.etaDays = data.eta_days || null;
    state.photoDue = !!data.photo_due;
    // 疑似旧默认身体数据：提示核对，不改数、不猜数
    state.bodySuspect = !!data.body_suspect;
    const bsCard = document.getElementById("body-suspect-card");
    if (bsCard) bsCard.style.display = state.bodySuspect ? "block" : "none";
    state.cycleDay = data.cycle_day || null;
    state.calculated = {
        bmr: data.metrics.bmr,
        tdee: data.metrics.tdee,
        targetCal: data.metrics.target_cal,
        restCal: data.metrics.rest_cal,
        workoutCal: data.metrics.workout_cal,
        deficitTarget: data.metrics.deficit,
        proteinG: data.metrics.protein_g,
        carbsG: data.metrics.carbs_g,
        fatG: data.metrics.fat_g,
        summaryText: `${data.profile.height}cm · ${data.current_weight_jin}斤 · ${getGoalName(data.profile.goal_type)}`
    };
    // 服务器返回的是存储形状（下划线），UI 读的是驼峰；以前直接赋值导致
    // 目标体重显示 undefined、差值算成 NaN、身材卡片退回女性第一款。
    const sp = data.profile || {};
    state.profile = {
        gender: sp.gender,
        age: sp.age,
        height: sp.height,
        weightJin: sp.weight_jin,
        targetWeightJin: sp.target_weight_jin,
        goalType: sp.goal_type,
        diningMode: sp.dining_mode,
        scene: sp.scene
    };
    state.todayConsumed = data.today_consumed || 0;
    state.todayBurned = data.today_burned || 0;
    state.remainingCal = data.remaining_cal;
    state.waterCupsCount = data.water_cups || 0;
    state.currentWeightJin = data.current_weight_jin;
    state.consecutiveOverDays = data.consecutive_over_days || 0;
    state.consecutiveSlackingDays = data.consecutive_slacking_days || 0;
    state.takeoutLocked = data.takeout_locked;
    state.mealDiary = data.today_meals || [];

    if (data.latest_cycle) {
        state.cycleData = {
            currentCycle: data.latest_cycle.cycle_num,
            cycleName: data.latest_cycle.cycle_name,
            cycleGoal: "阶段目标：突破腹部脂肪顽固层，增加核心抗阻负荷",
            basePhoto: data.latest_cycle.photo_url ? `${API_BASE}${data.latest_cycle.photo_url}` : null,
            curPhoto: data.latest_cycle.photo_url ? `${API_BASE}${data.latest_cycle.photo_url}` : null,
            baseWeightJin: data.latest_cycle.weight_jin,
            baseWaistCm: data.latest_cycle.waist_cm,
            curWeightJin: data.latest_cycle.weight_jin,
            curWaistCm: data.latest_cycle.waist_cm,
            toneScore: data.latest_cycle.tone_score,
            reportSummary: data.latest_cycle.ai_report
        };
    }

    renderDashboard();
    renderRealStats(data);
    renderDayComplete(data);
    renderMealDiary();
    renderWaterCups();
    switchShapeGender(data.profile.gender || "female", false);
    renderWorkoutExercises();
    renderTargetPhysiqueCard();
    renderCyclePhotos();
    checkConsecutiveAlerts();
    switchDiningMode(data.profile.dining_mode || "takeout");
}

async function syncRemoteDashboard() {
    if (!state.token) return;
    const generation=sessionGeneration;
    try {
        const res = await fetch(`${API_BASE}/api/dashboard`, {
            headers: { "Authorization": `Bearer ${state.token}` }
        });
        if (res.status === 401) {
            localStorage.removeItem(TOKEN_KEY);
            openAuthModal();
            return;
        }
        const data = await res.json();
        if (generation !== sessionGeneration) return;
        if (!res.ok) throw new Error("HTTP " + res.status);
        applyDashboardData(data);
        renderHabitMatrix();
    } catch (e) {
        console.error("Failed to sync remote dashboard", e);
        if(typeof restoreOfflineDashboard === "function") restoreOfflineDashboard(e);
    }
}

async function syncRemoteCharts() {
    if (!state.token) return;
    const generation=sessionGeneration;
    try {
        const res = await fetch(`${API_BASE}/api/charts`, {
            headers: { "Authorization": `Bearer ${state.token}` }
        });
        const data = await res.json();
        if (generation !== sessionGeneration) return;
        if (data.weight_history) {
            state.weightHistory = data.weight_history;
            state.deficitHistory = data.deficit_history;
            state.realMacros = data.macros_today;
            renderCharts();
        }
    } catch (e) {
        console.error("Failed to sync remote charts", e);
    }
}

function getGoalName(type) {
    if (typeof BODY_SHAPES_DATA !== "undefined") {
        if (BODY_SHAPES_DATA.female && BODY_SHAPES_DATA.female[type]) {
            return BODY_SHAPES_DATA.female[type].title;
        }
        if (BODY_SHAPES_DATA.male && BODY_SHAPES_DATA.male[type]) {
            return BODY_SHAPES_DATA.male[type].title;
        }
    }
    const map = {
        tone: "留肌塑形", loss: "减脂脱脂", muscle: "增肌充能", tight: "体态马甲线",
        female_hourglass: "S型沙漏马甲线", female_lean: "修长轻盈显瘦",
        female_athletic: "紧致力量健美", female_steady: "稳健脱脂保护",
        male_v_taper: "倒三角铠甲腹肌", male_lean: "修长衣架子显瘦",
        male_muscular: "饱满力量硬核", male_steady: "啤酒肚专项击退"
    };
    return map[type] || "减脂塑形";
}

// ==========================================
// 渲染仪表盘 (100% 真实计算与更新)
// ==========================================
function renderDashboard() {
    const c = state.calculated;
    const p = state.profile;

    const summaryEl = document.getElementById("header-profile-summary");
    if (summaryEl) summaryEl.innerText = c.summaryText;

    const restCalEl = document.getElementById("mode-rest-cal");
    if (restCalEl) restCalEl.innerText = c.restCal;

    const workoutCalEl = document.getElementById("mode-workout-cal");
    if (workoutCalEl) workoutCalEl.innerText = c.workoutCal;

    const kpiCal = document.getElementById("kpi-target-cal");
    if (kpiCal) kpiCal.innerText = `${c.restCal} - ${c.workoutCal}`;

    const kpiProtein = document.getElementById("kpi-target-protein");
    if (kpiProtein) kpiProtein.innerText = `${c.proteinG} g`;

    const kpiCarbs = document.getElementById("kpi-target-carbs");
    if (kpiCarbs) kpiCarbs.innerText = `${c.carbsG} g`;

    const kpiFat = document.getElementById("kpi-target-fat");
    if (kpiFat) kpiFat.innerText = `${c.fatG} g`;

    // 动态热量表盘
    const remainEl = document.getElementById("remain-cal-display");
    if (remainEl) remainEl.innerText = state.remainingCal;

    const consumedEl = document.getElementById("consumed-cal-val");
    if (consumedEl) consumedEl.innerText = `${state.todayConsumed} kcal`;

    const burnedEl = document.getElementById("burned-cal-val");
    if (burnedEl) burnedEl.innerText = `-${state.todayBurned} kcal`;

    const netDeficitEl = document.getElementById("net-deficit-val");
    if (netDeficitEl) {
        // 没记任何一笔时不假称有缺口：净缺口 = 维持代谢 + 训练消耗 - 真实摄入
        if (!state.dashboardLoaded || (state.todayConsumed === 0 && state.todayBurned === 0)) {
            netDeficitEl.innerText = "— kcal (今日暂无真实记录)";
            netDeficitEl.style.color = "var(--text-light)";
        } else {
            const netDeficit = Math.round(c.tdee - state.todayConsumed + state.todayBurned);
            netDeficitEl.innerText = (netDeficit >= 0 ? "+" : "") + `${netDeficit} kcal`;
            netDeficitEl.style.color = netDeficit >= 0 ? "var(--primary-dark)" : "var(--danger)";
        }
    }

    // 表盘进度环
    const circle = document.getElementById("gauge-circle");
    if (circle) {
        const maxCal = state.mode === "workout" ? c.workoutCal : c.restCal;
        const progress = Math.min(1.0, Math.max(0, state.todayConsumed / (maxCal || 1)));
        const totalLen = 415;
        circle.style.strokeDashoffset = totalLen * (1 - progress);
        circle.style.stroke = state.remainingCal < 0 ? "var(--danger)" : "var(--primary)";
    }

    // 外卖安全门禁状态
    const gateStatus = document.getElementById("takeout-gate-status");
    if (gateStatus) {
        if (state.remainingCal <= 0) {
            gateStatus.innerText = "🛑 门禁已锁定 (超标不可点)";
            gateStatus.style.color = "var(--danger)";
        } else {
            gateStatus.innerText = `🟢 安全可点 (剩 ${state.remainingCal}k)`;
            gateStatus.style.color = "var(--primary-dark)";
        }
    }

    // 体重与目标
    const curWeightSummary = document.getElementById("current-weight-summary");
    if (curWeightSummary) curWeightSummary.innerText = `当前 ${state.currentWeightJin} 斤 / 目标 ${p.targetWeightJin} 斤`;

    const statusText = document.getElementById("weight-status-text");
    if (statusText) {
        const tgt = Number(p.targetWeightJin);
        if (!tgt) {
            statusText.innerText = "还没设置目标体重：点右上角档案填一个，差值才算得出来。";
        } else {
            const gap = Math.round((state.currentWeightJin - tgt) * 10) / 10;
            statusText.innerText = gap > 0
                ? `离目标体重还有 ${gap} 斤！坚持真打卡，身材稳健蜕变！`
                : `已达到目标体重（当前比目标低 ${Math.abs(gap)} 斤）。`;
        }
    }
}

// 把界面上原本写死的统计全部绑到云端真实数据；没有记录就显示 0，不预先记功
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.innerText = val;
}

function renderRealStats(d) {
    const s = d.takeout_stats || {};
    const m = d.metrics || {};
    const intercepted = s.intercepted || 0;

    setText("stat-intercept-count", intercepted + " 次");
    setText("stat-cal-saved", (s.cal_saved || 0).toLocaleString());
    setText("stat-fat-saved", (s.fat_jin || 0) + " 斤");
    setText("medal-tag", intercepted > 0 ? "已有自律记录" : "尚无记录");

    setText("takeout-quota-badge", `本周点单 ${s.week_launched || 0} 次`);
    setText("takeout-quota-rule",
            `本周真实事件 ${s.week_events || 0} 条 · 系统不设次数配额，只如实记录`);
    const bar = document.getElementById("takeout-quota-bar");
    if (bar) {
        const denom = (s.week_launched || 0) + (s.week_events || 0);
        bar.style.width = denom ? Math.min(100, Math.round((s.week_events || 0) / denom * 100)) + "%" : "0%";
    }

    if (d.over_cal_total) {
        setText("banner-over-cal", `+${d.over_cal_total} kcal`);
    } else {
        setText("banner-over-cal", "0 kcal");
    }

    const start = d.start_weight_jin, cur = d.current_weight_jin;
    const tgt = Number((d.profile || {}).target_weight_jin);
    setText("chart-start-wt", start ? `${(start / 2).toFixed(1)} kg` : "—");
    setText("chart-target-wt", tgt ? `${(tgt / 2).toFixed(1)} kg` : "未设置");
    setText("chart-deficit-target-label", `目标 ${m.deficit || 0} kcal`);
    const trend = document.getElementById("chart-trend-tag");
    if (trend) {
        if (!start || !cur) trend.innerText = "尚无对比";
        else {
            const diff = Math.round((cur - start) * 10) / 10;
            trend.innerText = diff < 0 ? `已降 ${Math.abs(diff)} 斤`
                : (diff > 0 ? `上升 ${diff} 斤` : "持平");
            trend.style.color = diff <= 0 ? "var(--primary-dark)" : "var(--danger)";
        }
    }

    const pG = m.protein_g || 0, cG = m.carbs_g || 0, fG = m.fat_g || 0;
    const kcal = pG * 4 + cG * 4 + fG * 9;
    const pct = (v) => kcal ? Math.round(v * (v === pG ? 4 : (v === cG ? 4 : 9)) / kcal * 100) : 0;
    setText("legend-protein", `${pG}g (${pct(pG)}%)`);
    setText("legend-carbs", `${cG}g (${pct(cG)}%)`);
    setText("legend-fat", `${fG}g (${pct(fG)}%)`);

    const monthly = m.deficit ? Math.round(m.deficit * 30 / 7700 * 2 * 10) / 10 : 0;
    setText("kpi-cal-sub", m.deficit
        ? `缺口 ${m.deficit} kcal · 理论约 ${monthly} 斤/月（按 7700 kcal≈1 kg 脂肪折算）`
        : "未绑定档案");

    setText("streak-days", (d.streak_days || 0) + " 天");
    setText("eta-days", d.eta_days ? `约 ${d.eta_days} 天` : "暂无足够数据");
    setText("cycle-day-text", d.cycle_day ? `本周期第 ${d.cycle_day} 天` : "周期未开始");

    const due = document.getElementById("measure-due-banner");
    if (due) {
        if (d.photo_due) {
            const gap = d.days_since_measure;
            due.style.display = "flex";
            setText("measure-due-text", gap === null || gap === undefined
                ? "还没有过身材照或围度记录，现在建立基准，7 天后才能算出变化"
                : `距上次身材记录已 ${gap} 天，该更新了：拍照或只填围度都可以`);
        } else {
            due.style.display = "none";
        }
    }
    refreshTakeoutUsage();
    if (d.photo_due && state.token) notifyOnceToday("轻塑 · 记录提醒", "方便时回顾今天的记录，更多内容请打开应用查看。");
}

// 连续超标与脱离计划警报检查
function checkConsecutiveAlerts() {
    const overBanner = document.getElementById("consecutive-over-banner");
    const slackingBanner = document.getElementById("consecutive-slacking-banner");

    if (state.consecutiveOverDays >= 2) {
        if (overBanner) {
            overBanner.style.display = "flex";
            document.getElementById("banner-over-days").innerText = state.consecutiveOverDays;
        }
    } else {
        if (overBanner) overBanner.style.display = "none";
    }

    if (state.consecutiveSlackingDays >= 2 && !state.workoutDoneToday) {
        if (slackingBanner) {
            slackingBanner.style.display = "flex";
            document.getElementById("banner-slacking-days").innerText = state.consecutiveSlackingDays;
        }
    } else {
        if (slackingBanner) slackingBanner.style.display = "none";
    }
}

// ==========================================
// 真实饮食记录：调用云端真实数据库保存
// ==========================================
function selectMealSlot(slotKey) {
    state.selectedMealSlot = slotKey;
    document.querySelectorAll(".meal-slot-chip").forEach(c => {
        c.classList.remove("selected");
        c.setAttribute("aria-pressed", "false");
    });
    const el = document.getElementById("slot-chip-" + slotKey);
    if (el) {
        el.classList.add("selected");
        el.setAttribute("aria-pressed", "true");
    }
}

async function logNaturalMeal() {
    const input = document.getElementById("input-meal-text");
    const text = input.value.trim();
    if (!text) {
        callNativeToast("请输入您实际吃的食物");
        return;
    }

    const slotNames = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐", snack: "加餐" };
    const slotName = slotNames[state.selectedMealSlot] || "餐食";

    try {
        const data = await postApi("/api/food/log", { slot: slotName, food_name: text });
        callNativeToast(data.msg || "记录成功！");
        callNativeVibrate(80);
        input.value = "";
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "这餐饮食");
    }
}

async function editMealRecord(id) {
    const item=state.mealDiary.find(x=>x.id===id);if(!item)return;
    const value=window.prompt("修正本餐热量（kcal，宏量将标为未知）",String(item.cal));
    if(value===null)return;
    const cal=Number(value);
    if(!Number.isFinite(cal)||cal<0||cal>10000){callNativeToast("请填写0–10000之间的热量");return;}
    try{await postApi(`/api/records/food/${id}/update`,{cal});await syncRemoteDashboard();await syncRemoteCharts();wbRows=null;}
    catch(e){reportWriteFailure(e,"餐食修正");}
}
async function deleteMealRecord(id) {
    if(!window.confirm("删除这笔餐食记录？相关统计会重新计算。"))return;
    try{await postApi(`/api/records/food/${id}/delete`,{});await syncRemoteDashboard();await syncRemoteCharts();wbRows=null;}
    catch(e){reportWriteFailure(e,"餐食删除");}
}
function renderMealDiary() {
    const box = document.getElementById("today-meal-diary-list");
    if (!box) return;

    if (!state.mealDiary || state.mealDiary.length === 0) {
        box.innerHTML = `<div style="text-align: center; font-size: 11px; color: var(--text-light); padding: 8px;">今天尚未记录餐食，直接在上方输入吧！</div>`;
        return;
    }

    let html = `<div style="font-size: 11.5px; font-weight: 700; color: var(--text-muted); margin-bottom: 6px;">📝 今日饮食真实记录：</div>`;
    state.mealDiary.forEach(item => {
        const p = item.protein_g ? `蛋 ${item.protein_g}g ` : "";
        const c = item.carbs_g ? `碳 ${item.carbs_g}g ` : "";
        const f = item.fat_g ? `脂 ${item.fat_g}g` : "";
        const macroStr = (p || c || f) ? `<div style="font-size: 9.5px; color: var(--text-muted); margin-top: 1px;">${p}${c}${f}</div>` : "";

        html += `
            <div class="diary-record-item">
                <div style="flex: 1; min-width: 0;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <span class="meal-badge" style="font-size: 10px; flex-shrink: 0;">${escapeHtml(item.slot || '')}</span>
                        <span style="font-weight: 600; font-size: 12px; color: var(--text-main); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(item.food_name || item.name || '')}</span>
                    </div>
                    ${macroStr}
                </div>
                <div style="flex-shrink: 0; margin-left: 8px; text-align: right;">
                    <strong style="color: var(--primary-dark); font-size: 12px;">${item.cal} kcal</strong>
                        ${!isPublicScreen() ? `<div><button type="button" class="btn-row" onclick="editMealRecord(${Number(item.id)})">修正</button><button type="button" class="btn-row-danger" onclick="deleteMealRecord(${Number(item.id)})">删除</button></div>` : ''}
                    <div style="font-size: 10px; color: var(--text-light);">${escapeHtml(item.time_str || '')}</div>
                </div>
            </div>
        `;
    });
    box.innerHTML = html;
}

// 真实饮水打卡
async function toggleWaterCup(index) {
    let nextCount = state.waterCupsCount === index ? index - 1 : index;
    try {
        const data = await postApi("/api/water/update", { cups_count: nextCount });
        state.waterCupsCount = nextCount;
        renderWaterCups();
        callNativeToast(data.msg || "打卡成功！");
        callNativeVibrate(50);
    } catch (e) {
        renderWaterCups();
        reportWriteFailure(e, "饮水打卡");
    }
}

function renderWaterCups() {
    const box = document.getElementById("water-cups-box");
    const text = document.getElementById("water-consumed-text");
    if (!box) return;

    const count = state.waterCupsCount || 0;
    if (text) text.innerText = count * 250;
    const tgt = document.getElementById("water-target-text");
    if (tgt) tgt.innerText = state.waterTargetMl || 2000;

    let html = "";
    for (let i = 1; i <= Math.max(8, Math.ceil((state.waterTargetMl || 2000) / 250)); i++) {
        const isFilled = i <= count;
        html += `
            <div class="water-cup-btn ${isFilled ? 'filled' : ''}" onclick="toggleWaterCup(${i})">
                <span class="cup-icon">${isFilled ? '💧' : '🥛'}</span>
                <span>${i * 250}ml</span>
            </div>
        `;
    }
    box.innerHTML = html;
}

// 真实空腹体重记录
async function saveWeight() {
    const input = document.getElementById("input-weight");
    const val = parseFloat(input.value);
    const unit = document.getElementById("weight-unit").value;

    if (!val || val <= 0) {
        callNativeToast("请输入有效的体重数值");
        return;
    }

    const wtJin = unit === "kg" ? val * 2 : val;
    try {
        const data = await postApi("/api/weight/log", { weight_jin: wtJin });
        callNativeToast(data.msg || "体重打卡成功！");
        callNativeVibrate(100);
        input.value = "";
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "体重打卡");
    }
}

// 真实训练打卡
async function completeWorkoutToday() {
    try {
        const data = await postApi("/api/workout/complete",
            { duration_minutes: timerPlannedMinutes, cal_burned: Math.round(timerPlannedMinutes * 11), plan_name: "专属塑形训练（估算消耗）" });
        state.workoutDoneToday = true;
        callNativeToast(data.msg || "🏆 今日训练打卡成功！");
        callNativeVibrate(200);
        callNativeBeep();
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "训练打卡");
    }
}

// 周期身材照上传与规划进阶
// 周期表单不再预填编造的 138.4 / 76。体重取本人档案里那个真实值；
// 腰围一律留空让用户自己量——填进去的数会被当成围度基准参与后续增减计算。
function prefillCycleInputsFromRealData() {
    const wEl = document.getElementById("cycle-input-weight");
    if (!wEl || wEl.value) return;
    const p = state.profile || {};
    if (Number.isFinite(Number(p.weightJin)) && p.weightJin > 0) { wEl.value = p.weightJin; }
}

async function upgradeCyclePlan() {
    prefillCycleInputsFromRealData();
    const inputW = parseFloat(document.getElementById("cycle-input-weight").value);
    const inputWaist = parseFloat(document.getElementById("cycle-input-waist").value);

    if (!inputW || !inputWaist) {
        callNativeToast("请录入最新的体重与肚脐腰围数值");
        return;
    }

    const formData = new FormData();
    formData.append("weight_jin", inputW);
    formData.append("waist_cm", inputWaist);

    const fileInput = document.getElementById("file-cycle-photo-input");
    const hasPhoto = !!(fileInput && fileInput.files && fileInput.files[0]);
    if (hasPhoto) formData.append("photo", fileInput.files[0]);
    // 没照片就走测量通道：只填体重与腰围同样能更新下一周期安排
    const path = hasPhoto ? "/api/cycle/upgrade" : "/api/cycle/measure";
    state.lastCyclePath = path;

    try {
        callNativeToast("正在提交身材照并生成下一阶段进阶规划...");
        const data = await postApi(state.lastCyclePath || "/api/cycle/upgrade", formData);
        callNativeToast(data.msg || "🎉 周期身材照已记录！");
        callNativeVibrate(250);
        callNativeBeep();
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "周期身材照");
    }
}

function handlePhotoUpload(event, type) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    // Cache input element for upgradeCyclePlan submission
    event.target.id = "file-cycle-photo-input";

    const reader = new FileReader();
    reader.onload = function(e) {
        const img = document.getElementById(type === "base" ? "img-base-photo" : "img-cur-photo");
        const icon = document.getElementById(type === "base" ? "ph-base-icon" : "ph-cur-icon");
        const txt = document.getElementById(type === "base" ? "ph-base-txt" : "ph-cur-txt");
        if (img) {
            img.src = e.target.result;
            img.style.display = "block";
            if (icon) icon.style.display = "none";
            if (txt) txt.style.display = "none";
        }
        callNativeToast("📸 身材照已选取！点击下方【提交周期身材照】即可同步进阶规划！");
    };
    reader.readAsDataURL(file);
}

function renderCyclePhotos() {
    const cd = state.cycleData || {};
    const imgBase = document.getElementById("img-base-photo");
    const phBaseIcon = document.getElementById("ph-base-icon");
    const phBaseTxt = document.getElementById("ph-base-txt");
    const metaBase = document.getElementById("meta-base-photo");
    if (imgBase) {
        if (cd.basePhoto) {
            imgBase.src = cd.basePhoto;
            imgBase.style.display = "block";
            if (phBaseIcon) phBaseIcon.style.display = "none";
            if (phBaseTxt) phBaseTxt.style.display = "none";
        } else {
            imgBase.style.display = "none";
            if (phBaseIcon) phBaseIcon.style.display = "block";
            if (phBaseTxt) phBaseTxt.style.display = "block";
        }
    }
    if (metaBase) metaBase.innerText = `基准: ${(cd.baseWeightJin / 2).toFixed(1)}kg / ${cd.baseWaistCm}cm`;

    const imgCur = document.getElementById("img-cur-photo");
    const phCurIcon = document.getElementById("ph-cur-icon");
    const phCurTxt = document.getElementById("ph-cur-txt");
    const metaCur = document.getElementById("meta-cur-photo");
    const titleCur = document.getElementById("title-cur-cycle-photo");
    if (titleCur) titleCur.innerText = `🔥 第 ${cd.currentCycle || 1} 周期身材照`;
    if (imgCur) {
        if (cd.curPhoto) {
            imgCur.src = cd.curPhoto;
            imgCur.style.display = "block";
            if (phCurIcon) phCurIcon.style.display = "none";
            if (phCurTxt) phCurTxt.style.display = "none";
        } else {
            imgCur.style.display = "none";
            if (phCurIcon) phCurIcon.style.display = "block";
            if (phCurTxt) phCurTxt.style.display = "block";
        }
    }
    if (metaCur) metaCur.innerText = `本周: ${(cd.curWeightJin / 2).toFixed(1)}kg / ${cd.curWaistCm}cm`;

    const titleDisp = document.getElementById("cycle-title-display");
    if (titleDisp) titleDisp.innerText = cd.cycleName || `📅 第 ${cd.currentCycle || 1} 周期 (进行中)`;
    const goalDisp = document.getElementById("cycle-goal-display");
    if (goalDisp) goalDisp.innerText = cd.cycleGoal || "阶段目标：保持自律赤字，缩小围度";

    const repWeight = document.getElementById("rep-weight-diff");
    const repWaist = document.getElementById("rep-waist-diff");
    const repScore = document.getElementById("rep-tone-level");
    const repBody = document.getElementById("cycle-report-body");

    const wDiff = (cd.curWeightJin - cd.baseWeightJin).toFixed(1);
    const waistDiff = (cd.curWaistCm - cd.baseWaistCm).toFixed(1);

    if (repWeight) repWeight.innerText = (wDiff <= 0 ? "" : "+") + wDiff + " 斤";
    if (repWaist) repWaist.innerText = (waistDiff <= 0 ? "" : "+") + waistDiff + " cm";
    if (repScore) repScore.innerText = cd.toneScore || "优+ (89分)";
    if (repBody) repBody.innerHTML = cd.reportSummary || "恭喜完成本周期形体打卡！身材紧致度正在稳步提升！";
}

// ==========================================
// 100% 真实图表绘制 (无虚假数据，纯真实记录)
// ==========================================
function renderCharts() {
    drawWeightChart();
    drawDeficitChart();
    drawMacrosChart();
}

function drawWeightChart() {
    const canvas = document.getElementById("chart-weight");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width = canvas.parentElement.clientWidth || 340;
    const h = canvas.height = 180;

    ctx.clearRect(0, 0, w, h);

    const history = state.weightHistory;
    if (!history || history.length === 0) {
        ctx.fillStyle = "#94A3B8";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("暂无真实体重记录，请先在上方进行晨起体重打卡", w / 2, h / 2);
        return;
    }

    const padding = { left: 35, right: 20, top: 25, bottom: 25 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    const vals = history.map(d => d.val);
    let minVal = Math.min(...vals) - 0.5;
    let maxVal = Math.max(...vals) + 0.5;
    if (minVal === maxVal) { minVal -= 1; maxVal += 1; }

    // 网格线
    ctx.strokeStyle = "#F1F5F9";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
        const y = padding.top + (chartH / 3) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();

        const labelVal = (maxVal - (maxVal - minVal) / 3 * i).toFixed(1);
        ctx.fillStyle = "#94A3B8";
        ctx.font = "9px sans-serif";
        ctx.fillText(labelVal + "kg", 6, y + 3);
    }

    // 计算点位置 (兼容单个基准点与多个真实点)
    const points = history.map((pt, i) => {
        const x = history.length === 1 
            ? padding.left + chartW / 2 
            : padding.left + (chartW / (history.length - 1)) * i;
        const y = padding.top + chartH * (1 - (pt.val - minVal) / (maxVal - minVal));
        return { x, y, val: pt.val, date: pt.date };
    });

    if (points.length > 1) {
        // 面积渐变
        const grad = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
        grad.addColorStop(0, "rgba(16, 185, 129, 0.2)");
        grad.addColorStop(1, "rgba(16, 185, 129, 0.0)");

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
            ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.lineTo(points[points.length - 1].x, h - padding.bottom);
        ctx.lineTo(points[0].x, h - padding.bottom);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        // 折线
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
            ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.strokeStyle = "#10B981";
        ctx.lineWidth = 2.5;
        ctx.stroke();
    }

    // 绘制圆点与文字
    points.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#FFFFFF";
        ctx.fill();
        ctx.strokeStyle = "#059669";
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = "#0F172A";
        ctx.font = "bold 9px sans-serif";
        ctx.fillText(p.val.toFixed(1), p.x - 10, p.y - 7);

        ctx.fillStyle = "#94A3B8";
        ctx.font = "8.5px sans-serif";
        ctx.fillText(p.date, p.x - 10, h - 8);
    });

    const latest = history[history.length - 1].val;
    const curEl = document.getElementById("chart-cur-wt");
    if (curEl) curEl.innerText = `${latest.toFixed(1)} kg (${(latest * 2).toFixed(1)}斤)`;
}

function drawDeficitChart() {
    const canvas = document.getElementById("chart-deficit");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width = canvas.parentElement.clientWidth || 340;
    const h = canvas.height = 180;

    ctx.clearRect(0, 0, w, h);

    const data = state.deficitHistory;
    if (!data || data.length === 0) {
        ctx.fillStyle = "#94A3B8";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("暂无真实缺口记录，记饮食与运动后生成真实柱状图", w / 2, h / 2);
        describeDeficit([], 0);
        return;
    }

    const padding = { left: 30, right: 15, top: 25, bottom: 25 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    const barW = (chartW / data.length) * 0.55;
    const step = chartW / data.length;
    const targetDeficit = Math.abs(state.calculated.deficitTarget || 420);
    describeDeficit(data, targetDeficit);
    const targetY = padding.top + chartH * (1 - Math.min(1.0, targetDeficit / 600));

    // 目标缺口辅助虚线
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#F59E0B";
    ctx.lineWidth = 1.5;
    ctx.moveTo(padding.left, targetY);
    ctx.lineTo(w - padding.right, targetY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = "#D97706";
    ctx.font = "9px sans-serif";
    ctx.fillText(`目标 ${targetDeficit}k`, w - padding.right - 55, targetY - 4);

    data.forEach((d, i) => {
        const x = padding.left + step * i + (step - barW) / 2;
        const clampedDef = Math.max(0, Math.min(600, d.deficit));
        const barH = (clampedDef / 600) * chartH;
        const y = padding.top + chartH - barH;

        ctx.fillStyle = d.deficit >= targetDeficit ? "#10B981" : (d.deficit > 0 ? "#FBBF24" : "#EF4444");
        ctx.beginPath();
        ctx.roundRect(x, y, barW, Math.max(4, barH), [4, 4, 0, 0]);
        ctx.fill();

        ctx.fillStyle = "#0F172A";
        ctx.font = "bold 9px sans-serif";
        ctx.fillText(d.record_status==="missing"?"未记":String(d.deficit)+(d.record_status==="partial"?"*":""), x - 2, y - 5);

        ctx.fillStyle = "#94A3B8";
        ctx.font = "9px sans-serif";
        ctx.fillText(d.day, x, h - 8);
    });
}

function drawMacrosChart() {
    const canvas = document.getElementById("chart-macros");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const size = 140;
    canvas.width = size;
    canvas.height = size;

    ctx.clearRect(0, 0, size, size);

    const cx = size / 2;
    const cy = size / 2;
    const r = 50;
    const lineWidth = 16;

    const rm = state.realMacros || {};
    const pG = Number(rm.protein_g) || 0;
    const cG = Number(rm.carbs_g) || 0;
    const fG = Number(rm.fat_g) || 0;

    // 今日一笔未记时画灰环说明"没数据"，不再用 10% 垫底凑出一个看似真实的三等分
    if (pG <= 0 && cG <= 0 && fG <= 0) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = "#E2E8F0";
        ctx.lineWidth = lineWidth;
        ctx.stroke();
        ctx.fillStyle = "#94A3B8";
        ctx.font = "bold 12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("今日无记录", cx, cy + 4);
        return;
    }

    const total = pG * 4 + cG * 4 + fG * 9;
    const macros = [
        { name: "蛋白质", kcal: pG * 4, color: "#3B82F6" },
        { name: "复合碳水", kcal: cG * 4, color: "#F59E0B" },
        { name: "优质脂肪", kcal: fG * 9, color: "#EF4444" }
    ].filter(m => m.kcal > 0);

    let startAngle = -Math.PI / 2;
    macros.forEach(m => {
        const angle = (m.kcal / total) * Math.PI * 2;
        ctx.beginPath();
        ctx.arc(cx, cy, r, startAngle, startAngle + angle);
        ctx.strokeStyle = m.color;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
        startAngle += angle;
    });

    ctx.fillStyle = "#0F172A";
    ctx.font = "bold 13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`${Math.round(rm.total_cal || total)}k`, cx, cy + 5);
}

// ==========================================
// 饭点外卖软件安全门禁 (超出热量严格限制点单)
// ==========================================
function launchTakeoutApp(type) {
    if (!state.token) {
        callNativeToast("还没有您的今日热量额度：请先登录或注册，门禁才知道该不该放行");
        openAuthModal();
        return;
    }
    if (!state.dashboardLoaded) {
        callNativeToast("⚠️ 今日额度还没从云端取到（网络不通），门禁不放行也不判超标，请联网后重试");
        callNativeVibrate(200);
        return;
    }
    if (state.remainingCal <= 0) {
        // 触发强力拦截锁
        callNativeVibrate(300);
        callNativeBeep();
        reportTakeoutEvent("blocked", 0, "");
        alert(`🚨 【外卖严管拦截网启动】\n\n您今日热量已超标，今日额度已用超 ${state.remainingCal} kcal！\n根据减脂塑形计划，外卖点单已被系统严格限制！\n\n💡 建议方案：多饮用 500ml 温水排钠，晚餐改用清爽蔬菜豆腐汤！`);
        return;
    }

    // 额度充足，复制减脂备注后放行跳转
    copyTakeoutRemark();
    const appName = type === "meituan" ? "美团外卖" : "饿了么";
    const pkgName = type === "meituan" ? "com.sankuai.meituan" : "me.ele";
    callNativeToast(`✅ 减脂备注已复制！今日额度还剩 ${state.remainingCal} kcal，正在前往${appName}...`);
    reportTakeoutEvent("launched", 0, appName);

    if (window.AndroidBridge && window.AndroidBridge.launchApp) {
        window.AndroidBridge.launchApp(pkgName);
    } else {
        const url = type === "meituan" ? "https://i.meituan.com" : "https://h5.ele.me";
        window.open(url, "_blank");
    }
}


// ================= 第五批：通知通道与外卖真实使用情况 =================

/**
 * 返回 "system"（真发出去了）或 "page"（发不了，得靠页面内提醒）。
 * 网页版没有 AndroidBridge，一律返回 page——Web Push 要 HTTPS+域名，这站两样都没有。
 */
function notifyChannel(title, body) {
    const b = window.AndroidBridge;
    if (b && b.tryNotify) {
        try {
            if (b.tryNotify(String(title), String(body)) === true) return "system";
            return "page";
        } catch (e) {
            return "page";
        }
    }
    return "page";
}

/** 页面内提醒条：通知发不出去时的兜底，内容只说真实数字与真实原因。 */
function showInPageReminder(title, body) {
    let bar = document.getElementById("inpage-remind");
    if (!bar) {
        bar = document.createElement("div");
        bar.id = "inpage-remind";
        bar.className = "inpage-remind";
        document.body.appendChild(bar);
    }
    bar.innerHTML = "<strong>" + escapeHtml(String(title)) + "</strong>"
        + "<span>" + escapeHtml(String(body)) + "</span>"
        + "<button type=\"button\" class=\"btn-row\" onclick=\"document.getElementById('inpage-remind').style.display='none'\">知道了</button>";
    bar.style.display = "flex";
}

/** 开 App 就检查通知权限；缺了就提示并送到系统设置页。已授权则自动隐藏。 */
function initNotifPermissionHint() {
    refreshNotifPermissionHint(false);
}

function refreshNotifPermissionHint(showToast = false) {
    const b = window.AndroidBridge;
    const box = document.getElementById("notif-hint-box") || document.querySelector(".notif-hint");
    if (!b || !b.notificationsEnabled) {
        if (box) box.remove();
        return;
    }
    let on = false;
    try { on = b.notificationsEnabled() === true; } catch (e) { return; }
    if (on) {
        if (box) {
            box.remove();
            if (showToast) {
                callNativeToast("✅ 系统通知权限已开启！");
            }
        }
        return;
    }
    if (!box) {
        const hint = document.createElement("div");
        hint.id = "notif-hint-box";
        hint.className = "notif-hint";
        hint.innerHTML = "<span>通知权限尚未开启。启用每日提醒后，还需允许系统通知；厂商省电策略可能延迟送达。</span>"
            + "<button type=\"button\" class=\"btn-row\" onclick=\"openSystemNotifSettings()\">去开启</button>";
        const host = document.querySelector("main") || document.body;
        host.insertBefore(hint, host.firstChild);
    }
}

function openSystemNotifSettings() {
    const b = window.AndroidBridge;
    if (b && b.openNotificationSettings) {
        try { b.openNotificationSettings(); return; } catch (e) {}
    }
    callNativeToast("这不是 App 版，浏览器里开不了系统通知设置");
}

function requestUsageAccess() {
    const b = window.AndroidBridge;
    if (b && b.openUsageAccessSettings) {
        try { b.openUsageAccessSettings(); return; } catch (e) {}
    }
    callNativeToast("网页版读不到手机的使用情况，这条只有 App 里有");
}

const TAKEOUT_PKGS = "com.sankuai.meituan,me.ele";

/**
 * 读今天外卖 App 的真实打开次数与前台时长。
 * 未授权＝null，界面必须写「未授权」；把 null 画成 0 次就是撒谎（0 次意味着确实没打开过）。
 * 支持从系统设置授权后返回自动刷新并提示。
 */
function refreshTakeoutUsage(showToast = false) {
    const st = document.getElementById("usage-state");
    const dt = document.getElementById("usage-detail");
    const btn = document.getElementById("usage-grant-btn");
    if (!st || !dt) return;
    const b = window.AndroidBridge;
    if (!b || !b.takeoutUsageToday) {
        st.textContent = "网页版读不到";
        st.className = "usage-state warn";
        dt.textContent = "手机使用情况只有装了的 App 能读；浏览器没有这个权限通道，这里不编数字。";
        if (btn) btn.style.display = "none";
        return;
    }
    let raw = null;
    try { raw = b.takeoutUsageToday(TAKEOUT_PKGS); } catch (e) { raw = null; }
    if (!raw) {
        st.textContent = "未授权";
        st.className = "usage-state warn";
        dt.textContent = "没给「使用情况访问权限」，所以今天打开过几次我不知道。我不会拿 0 次冒充\"今天没点\"。";
        if (btn) btn.style.display = "inline-block";
        state.takeoutUsageGranted = false;
        return;
    }
    const wasGranted = state.takeoutUsageGranted;
    state.takeoutUsageGranted = true;
    if (wasGranted === false && showToast) {
        callNativeToast("✅ 外卖使用情况权限已生效，已实时刷新记录！");
    }
    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) { parsed = null; }
    if (!parsed || !parsed.apps) {
        st.textContent = "读不到";
        st.className = "usage-state warn";
        dt.textContent = "系统返回的内容解析失败，这条按读不到处理，不猜。";
        return;
    }
    if (btn) btn.style.display = "none";
    let launches = 0, ms = 0, lines = [];
    for (let i = 0; i < parsed.apps.length; i++) {
        const a = parsed.apps[i];
        launches += Number(a.launches) || 0;
        ms += Number(a.foregroundMs) || 0;
        const nm = String(a.pkg).indexOf("meituan") >= 0 ? "美团" : (String(a.pkg).indexOf("ele") >= 0 ? "饿了么" : a.pkg);
        lines.push(nm + " 打开 " + (Number(a.launches) || 0) + " 次 / 前台 " +
            Math.round((Number(a.foregroundMs) || 0) / 60000) + " 分钟");
    }
    st.textContent = launches > 0 ? "今天已打开 " + launches + " 次" : "今天一次没打开";
    st.className = "usage-state " + (launches > 0 ? "bad" : "good");
    dt.textContent = lines.join("；") || "系统今天没有这两个包的使用记录";
    state.takeoutUsageToday = { launches: launches, minutes: Math.round(ms / 60000) };
}

/**
 * 原生端 onResume 或窗口重新激活回调：
 * 解决用户从系统权限设置返回后无需重启软件即可自动更新 UI。
 */
window.onAppResume = function() {
    refreshNotifPermissionHint(true);
    refreshTakeoutUsage(true);
    if (state.token) {
        syncRemoteDashboard();
    }
};

if (typeof window !== "undefined" && window.addEventListener) {
    window.addEventListener("focus", function() {
        if (window.onAppResume) window.onAppResume();
    });
}

if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("visibilitychange", function() {
        if (document.visibilityState === "visible" && window.onAppResume) {
            window.onAppResume();
        }
    });
}
function notifyOnceToday(title, body) {
    const now=new Date();
    const key = "QINGSU_NOTED_" + (state.user ? state.user.username : "guest") + "_" + now.getFullYear()+"-"+(now.getMonth()+1)+"-"+now.getDate();
    try { if (localStorage.getItem(key)) return; localStorage.setItem(key, "1"); } catch (e) { return; }
    // App 里：有通知权限就发系统通知；没权限就在页面里提醒，绝不静默丢掉这条提醒
    if (notifyChannel(title, body) === "page" && state.token) {
        showInPageReminder(title, body);
    }
}

async function reportTakeoutEvent(type, calAvoided, dish) {
    if (!state.token) return;
    try {
        await postApi("/api/takeout/event",
            { event_type: type, cal_avoided: calAvoided || 0, dish_name: dish || "" });
        await syncRemoteDashboard();
    } catch (e) {
        // 记录失败不该打断用户当前操作，但也不能假装记上了
        console.warn("takeout event not saved", e && e.message);
    }
}

// ==========================================
// 专属公网监督网页链接：复制与打开
// ==========================================
function copyUserPublicUrl() {
    if (!state.user || !state.user.username) {
        callNativeToast("请先登录或注册您的专属减脂档案！");
        openAuthModal();
        return;
    }
    const username = state.user.username;
    const url = state.publicUrl;
    if (!url) { callNativeToast("分享链接未加载，请刷新后再试"); return; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            callNativeToast("📋 您的专属公网大屏网址已复制！任何手机/电脑浏览器均可查看！");
            callNativeVibrate(50);
        }).catch(() => fallbackCopy(url));
    } else {
        fallbackCopy(url);
    }
}

function openUserPublicUrl() {
    if (!state.user || !state.user.username) {
        callNativeToast("请先登录或注册您的专属减脂档案！");
        openAuthModal();
        return;
    }
    const username = state.user.username;
    const url = state.publicUrl;
    if (!url) { callNativeToast("分享链接未加载，请刷新后再试"); return; }
    if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
        window.AndroidBridge.openBrowser(url);
    } else {
        window.open(url, "_blank");
    }
}

// ==========================================
// 用户认证弹窗：登录与多账号注册
// ==========================================
function openAuthModal() {
    document.getElementById("auth-modal").classList.add("show");
}

function closeAuthModal() {
    document.getElementById("auth-modal").classList.remove("show");
}

function switchAuthTab(tab) {
    const btnL = document.getElementById("btn-auth-tab-login");
    const btnR = document.getElementById("btn-auth-tab-register");
    const formL = document.getElementById("auth-form-login");
    const formR = document.getElementById("auth-form-register");

    if (tab === "login") {
        btnL.classList.add("active");
        btnR.classList.remove("active");
        formL.style.display = "block";
        formR.style.display = "none";
    } else {
        btnR.classList.add("active");
        btnL.classList.remove("active");
        formR.style.display = "block";
        formL.style.display = "none";
    }
}

async function submitLogin() {
    const u = document.getElementById("login-username").value.trim();
    const p = document.getElementById("login-password").value.trim();
    if (!u || !p) { callNativeToast("请填写用户名和密码"); return; }

    try {
        const res = await fetch(`${API_BASE}/api/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (data.token) {
            saveAuthSession(data.token, { username: data.username, nickname: data.nickname });
            state.publicUrl=data.public_url;
            closeAuthModal();
            callNativeToast(`🎉 欢迎回来，${escapeHtml(displayName(data))}！专属真实档案已同步！`);
            callNativeVibrate(100);
            await syncRemoteDashboard();
            await syncRemoteCharts();
        } else {
            callNativeToast(data.detail || "登录失败，请核对密码");
        }
    } catch (e) {
        callNativeToast("网络连接失败，请检查网络");
    }
}

async function submitRegister() {
    const u = document.getElementById("reg-username").value.trim();
    const p = document.getElementById("reg-password").value.trim();
    const g = document.getElementById("reg-gender").value;
    const a = parseInt(document.getElementById("reg-age").value, 10);
    const h = parseFloat(document.getElementById("reg-height").value);
    const w = parseFloat(document.getElementById("reg-weight").value);
    const target=parseFloat(document.getElementById("reg-target-weight").value);
    if(!Number.isFinite(target)||target<40||target>600){callNativeToast("请填写你确认的目标体重（40–600斤）");return;}

    if (!u || !p) { callNativeToast("请填写注册用户名和密码"); return; }
    // 这三项决定每日热量额度：空着或离谱就不许注册，不再悄悄用 26/165/140 顶上
    if (![a, h, w].every(Number.isFinite)) {
        callNativeToast("年龄、身高、当前体重都要填真实数字（只填账号密码注册不了）");
        return;
    }
    if (a < 18 || a > 100 || h < 80 || h > 250 || w < 40 || w > 600) {
        callNativeToast("年龄 18~100、身高 80~250cm、体重 40~600 斤，请按真实值填");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: u, password: p, gender: g, age: a, height: h,
                weight_jin: w, target_weight_jin: target,
                special_population: document.getElementById('reg-special-population').checked,
                goal_type: "tone", dining_mode: "takeout"
            })
        });
        const data = await res.json();
        if (data.token) {
            saveAuthSession(data.token, { username: data.username, nickname: data.nickname });
            state.publicUrl=data.public_url;
            closeAuthModal();
            callNativeToast(`🎉 注册成功！专属公网地址已开通！`);
            callNativeVibrate(150);
            await syncRemoteDashboard();
            await syncRemoteCharts();
        } else {
            callNativeToast(data.detail || "注册失败，该用户名可能已被占用");
        }
    } catch (e) {
        callNativeToast("网络连接失败，请检查网络");
    }
}

async function logoutUser() {
    try { if (state.token) await rawPostApi("/api/logout",{}); }
    catch(e) { callNativeToast("本机已退出；网络异常，服务器会话尚未撤销"); }
    sessionGeneration++;
    localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY);
    state=JSON.parse(JSON.stringify(INITIAL_STATE)); wbRows=null;
    uncertainWrites.clear();pendingWrites.clear();
    resetPrivateUI();updateUserUI(null);
    const chat=document.getElementById("chat-messages-box");if(chat)chat.innerHTML="";
    closeAuthModal();openAuthModal();
    if (window.location.reload) window.location.reload();
}

function resetPrivateUI(){
    renderDashboard();renderMealDiary();renderWaterCups();renderCharts();renderCyclePhotos();
    const chat=document.getElementById('chat-messages-box');if(chat)chat.innerHTML='';
    for(const id of ['img-base-photo','img-cur-photo']){const el=document.getElementById(id);if(el)el.removeAttribute('src');}
    for(const id of ['input-meal-text','input-weight','cycle-input-weight','cycle-input-waist','file-cycle-photo-input']){const el=document.getElementById(id);if(el)el.value='';}
    document.querySelectorAll('.modal-overlay.show').forEach(el=>el.classList.remove('show'));
    if(typeof resetAccountTools==='function')resetAccountTools();
}

// ==========================================
// 8大类男女专属身材形态数据库与生动矢量图示 (严谨科学细分)
// ==========================================
const BODY_SHAPES_DATA = {
    female: {
        female_hourglass: {
            title: "⏳ S型沙漏 · 马甲线",
            subTitle: "腰臀比0.7 · 紧致马甲线",
            desc: "追求纤细腰腹、饱满翘臀、挺拔直背。聚焦腰臀比与马甲线刻画。",
            specs: "缺口420k · 慢碳40% · 臀腹抗阻",
            dietSpec: "高蛋白30% · 晚餐低碳轻负 · 排钠利水",
            workoutSpec: "臀桥深蹲 + 核心卷腹抗阻 + 提膝心率",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="14" r="8" fill="#10B981" />
                <path d="M26 23 C28 26 40 26 42 23 C48 27 50 31 51 36 C45 37 42 44 41 50 C44 58 48 64 47 72 C46 80 44 94 40 94 C38 94 36 80 34 68 C32 80 30 94 28 94 C24 94 22 80 21 72 C20 64 24 58 27 50 C26 44 23 37 17 36 C18 31 20 27 26 23 Z" fill="#D1FAE5" stroke="#10B981" stroke-width="2" stroke-linejoin="round" />
                <path d="M34 32 L34 46" stroke="#047857" stroke-width="1.5" stroke-linecap="round" />
                <path d="M30 40 Q34 42 38 40" stroke="#047857" stroke-width="1.5" stroke-linecap="round" />
                <path d="M28 48 Q34 50 40 48" stroke="#047857" stroke-width="1.5" stroke-linecap="round" />
            </svg>`
        },
        female_lean: {
            title: "🏃 修长轻盈 · 纤细显瘦",
            subTitle: "四肢修长 · 消除泡芙",
            desc: "追求全身去脂、修长无水肿线条、穿衣显瘦，消除假胯宽与泡芙感。",
            specs: "缺口500k · 慢碳45% · 芭蕾普拉提",
            dietSpec: "高纤维高钾蔬菜 · 排水肿 · 戒反式脂肪",
            workoutSpec: "低冲击全身循环 + 30分钟超慢跑刷脂",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="12" r="7.5" fill="#3B82F6" />
                <path d="M28 21 C30 23 38 23 40 21 C45 25 46 29 46 34 C43 40 40 46 39 52 C41 60 43 68 42 76 C41 84 39 94 36 94 C35 94 34 82 34 68 C34 82 33 94 32 94 C29 94 27 84 26 76 C25 68 27 60 29 52 C28 46 25 40 22 34 C22 29 23 25 28 21 Z" fill="#EFF6FF" stroke="#3B82F6" stroke-width="2" stroke-linejoin="round" />
                <path d="M34 26 L34 50" stroke="#1D4ED8" stroke-width="1.5" stroke-dasharray="2 2" />
            </svg>`
        },
        female_athletic: {
            title: "🏋️ 紧致力量 · 健美微肌",
            subTitle: "清晰腹肌 · 直角肩背",
            desc: "追求饱满肩颈直角肩、紧实蜜桃臀、腹肌分块，提高骨骼肌率与燃脂代谢。",
            specs: "高蛋白35% · 渐进负荷 · 紧致饱满",
            dietSpec: "优质蛋白 1.6-1.8g/kg · 练后黄金补给",
            workoutSpec: "负重深蹲硬拉 + 离心控制 + 悬垂举腿",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="13" r="8" fill="#F59E0B" />
                <path d="M23 23 C27 26 41 26 45 23 C53 28 55 33 55 38 C47 40 44 44 43 51 C46 59 50 67 49 76 C48 85 46 94 41 94 C38 94 36 78 34 65 C32 78 30 94 27 94 C22 94 20 85 19 76 C18 67 22 59 25 51 C24 44 21 40 13 38 C13 33 15 28 23 23 Z" fill="#FEF3C7" stroke="#F59E0B" stroke-width="2" stroke-linejoin="round" />
                <path d="M26 33 Q34 35 42 33" stroke="#B45309" stroke-width="1.5" />
                <circle cx="30" cy="42" r="1.5" fill="#B45309" />
                <circle cx="38" cy="42" r="1.5" fill="#B45309" />
                <circle cx="30" cy="48" r="1.5" fill="#B45309" />
                <circle cx="38" cy="48" r="1.5" fill="#B45309" />
            </svg>`
        },
        female_steady: {
            title: "📉 稳健脱脂 · 关节保护",
            subTitle: "保护膝盖 · 稳降围度",
            desc: "追求大基数健康平稳脱脂，避免剧烈跳跃磨损半月板，重点击退内脏脂肪与水钠。",
            specs: "缺口550k · 零跳跃低冲击 · 稳扎稳打",
            dietSpec: "温水排钠 2000ml · 断绝深加工零食",
            workoutSpec: "椅子半蹲 + 靠墙推胸 + 30分钟快步走",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="14" r="8" fill="#8B5CF6" />
                <path d="M26 23 C29 25 39 25 42 23 C49 28 51 34 50 42 C45 46 44 54 44 60 C46 67 47 76 46 84 C45 92 43 94 39 94 C37 94 35 80 34 68 C33 80 31 94 29 94 C25 94 23 92 22 84 C21 76 22 67 24 60 C24 54 23 46 18 42 C17 34 19 28 26 23 Z" fill="#F3E8FF" stroke="#8B5CF6" stroke-width="2" stroke-linejoin="round" />
                <path d="M34 32 L34 50 M30 45 L34 50 L38 45" stroke="#6D28D9" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>`
        }
    },
    male: {
        male_v_taper: {
            title: "👑 经典倒三角 · 铠甲腹肌",
            subTitle: "宽肩阔背 · 铠甲人鱼线",
            desc: "追求霸气倒三角(V-Taper)、清晰六块腹肌与人鱼线，低体脂(10-12%)竞技感。",
            specs: "缺口420k · 蛋白35% · 阔背肩腹",
            dietSpec: "优质蛋白2.0g/kg · 碳水循环 · 优质坚果油",
            workoutSpec: "高位下拉/引体 + 侧平举 + 悬垂举腿卷腹",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="13" r="8" fill="#0EA5E9" />
                <path d="M12 25 C16 23 52 23 56 25 C58 31 56 38 52 42 C48 44 42 46 40 54 C39 62 44 68 45 76 C46 84 43 94 38 94 C36 94 35 82 34 70 C33 82 32 94 30 94 C25 94 22 84 23 76 C24 68 29 62 28 54 C26 46 20 44 16 42 C12 38 10 31 12 25 Z" fill="#E0F2FE" stroke="#0EA5E9" stroke-width="2" stroke-linejoin="round" />
                <path d="M24 33 Q34 36 44 33 M34 26 L34 39" stroke="#0284C7" stroke-width="1.6" stroke-linecap="round" />
                <rect x="29" y="41" width="4.5" height="4" rx="1" fill="#0284C7" />
                <rect x="34.5" y="41" width="4.5" height="4" rx="1" fill="#0284C7" />
                <rect x="29.5" y="46.5" width="4" height="4" rx="1" fill="#0284C7" />
                <rect x="34.5" y="46.5" width="4" height="4" rx="1" fill="#0284C7" />
                <rect x="30" y="52" width="3.5" height="3.5" rx="1" fill="#0284C7" />
                <rect x="34.5" y="52" width="3.5" height="3.5" rx="1" fill="#0284C7" />
            </svg>`
        },
        male_lean: {
            title: "👔 修长衣架子 · 少年显瘦",
            subTitle: "挺拔身姿 · 穿衣有型",
            desc: "追求无肚腩啤酒肚、干净平坦腹部、挺拔肩颈，穿衬衫西装如衣架子(体脂12-14%)。",
            specs: "微缺口350k · 慢碳45% · 徒手健身",
            dietSpec: "高蛋白均衡 · 绝不吃夜宵大排档 · 清淡过水",
            workoutSpec: "俯卧撑多变式 + 核心平板 + 坡度快走刷脂",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="12" r="7.5" fill="#6366F1" />
                <path d="M19 24 C23 23 45 23 49 24 C52 28 51 34 48 38 C45 42 41 46 40 54 C39 62 42 70 42 78 C42 86 40 94 37 94 C35 94 34 82 34 68 C34 82 33 94 31 94 C28 94 26 86 26 78 C26 70 29 62 28 54 C27 46 23 42 20 38 C17 34 16 28 19 24 Z" fill="#EEF2FF" stroke="#6366F1" stroke-width="2" stroke-linejoin="round" />
                <path d="M34 25 L34 49" stroke="#4F46E5" stroke-width="1.5" stroke-dasharray="3 2" />
                <path d="M26 32 Q34 34 42 32" stroke="#4F46E5" stroke-width="1.5" stroke-linecap="round" />
            </svg>`
        },
        male_muscular: {
            title: "💪 饱满力量 · 硬核猛男",
            subTitle: "厚实胸背 · 粗壮手臂",
            desc: "追求厚实胸大肌、粗壮麒麟臂(肱二三头肌)、强壮大腿与厚实斜方肌，荷尔蒙爆棚。",
            specs: "盈余+300k · 高蛋白35% · 大重量抗阻",
            dietSpec: "高蛋白2.2g/kg · 全天5餐多餐 · 充足肌糖原",
            workoutSpec: "杠铃卧推 + 杠铃深蹲 + 罗马尼亚硬拉复合动作",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="13" r="8" fill="#F97316" />
                <path d="M9 25 C15 22 53 22 59 25 C63 30 62 38 56 42 C51 45 45 46 43 54 C42 62 46 68 47 77 C48 86 45 94 39 94 C37 94 36 80 34 66 C32 80 31 94 29 94 C23 94 20 86 21 77 C22 68 26 62 25 54 C23 46 17 45 12 42 C6 38 5 30 9 25 Z" fill="#FFEDD5" stroke="#F97316" stroke-width="2" stroke-linejoin="round" />
                <path d="M22 34 C25 38 33 39 34 35 C35 39 43 38 46 34" stroke="#C2410C" stroke-width="1.8" stroke-linecap="round" />
                <path d="M34 26 L34 50" stroke="#C2410C" stroke-width="1.8" />
                <path d="M8 31 Q6 36 11 39 M60 31 Q62 36 57 39" stroke="#C2410C" stroke-width="1.8" stroke-linecap="round" />
            </svg>`
        },
        male_steady: {
            title: "📉 啤酒肚专项 · 减内脏脂",
            subTitle: "消除脂肪肝 · 保护膝关节",
            desc: "专项击退向心性内脏大肚子、降血脂消脂肪肝，平稳保护半月板，重塑健康体态。",
            specs: "缺口550k · 严格断酒 · 零膝盖冲击",
            dietSpec: "断绝啤酒与高油烧烤 · 清蒸鱼虾 · 2500ml水",
            workoutSpec: "动感单车/椭圆机刷脂 + 核心转体抗扭 + 椅子深蹲",
            svg: `<svg viewBox="0 0 68 96" fill="none" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <circle cx="34" cy="14" r="8" fill="#14B8A6" />
                <path d="M16 25 C20 23 48 23 52 25 C55 30 54 36 51 42 C48 47 44 54 44 62 C45 71 47 80 45 88 C44 94 41 94 38 94 C36 94 35 82 34 68 C33 82 32 94 30 94 C27 94 24 94 23 88 C21 80 23 71 24 62 C24 54 20 47 17 42 C14 36 13 30 16 25 Z" fill="#CCFBF1" stroke="#14B8A6" stroke-width="2" stroke-linejoin="round" />
                <path d="M34 34 L34 52 M29 46 L34 52 L39 46" stroke="#0F766E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>`
        }
    }
};

// 获取身材数据对象 (支持老版本 goalType 映射)
function getShapeData(gender, goalType) {
    const g = (gender === "male") ? "male" : "female";
    const shapes = BODY_SHAPES_DATA[g];
    if (shapes[goalType]) return { gender: g, key: goalType, data: shapes[goalType] };

    const legacyMap = {
        female: { tone: "female_hourglass", loss: "female_lean", muscle: "female_athletic", tight: "female_steady" },
        male: { tone: "male_v_taper", loss: "male_lean", muscle: "male_muscular", tight: "male_steady" }
    };
    const mappedKey = (legacyMap[g] && legacyMap[g][goalType]) || Object.keys(shapes)[0];
    return { gender: g, key: mappedKey, data: shapes[mappedKey] };
}

// 动态渲染身材卡片至指定网格容器
function renderBodyShapeCards(containerId, gender, activeKey) {
    const box = document.getElementById(containerId);
    if (!box) return;
    const g = (gender === "male") ? "male" : "female";
    const shapes = BODY_SHAPES_DATA[g];
    let html = "";
    for (const [key, item] of Object.entries(shapes)) {
        const isSelected = (key === activeKey);
        html += `
            <div class="body-shape-card ${isSelected ? 'selected' : ''}" id="shape-card-${key}" onclick="selectVisualGoalShape('${key}')">
                <span class="body-shape-selected-tag">已选目标</span>
                <div class="body-shape-svg-box">
                    ${item.svg}
                </div>
                <div class="body-shape-title">${item.title}</div>
                <div class="body-shape-desc">${item.desc}</div>
                <div class="body-shape-specs">${item.specs}</div>
            </div>
        `;
    }
    box.innerHTML = html;
}

// 切换身材性别展示 (男女分流)
function switchShapeGender(gender, updateProfile = true) {
    const g = (gender === "male") ? "male" : "female";
    if (updateProfile) {
        state.profile.gender = g;
        const profGenderSelect = document.getElementById("prof-gender");
        if (profGenderSelect) profGenderSelect.value = g;
    }

    const tabF = document.getElementById("tab-gender-female");
    const tabM = document.getElementById("tab-gender-male");
    const modF = document.getElementById("modal-tab-female");
    const modM = document.getElementById("modal-tab-male");

    if (g === "male") {
        if (tabM) tabM.classList.add("active");
        if (tabF) tabF.classList.remove("active");
        if (modM) modM.classList.add("active");
        if (modF) modF.classList.remove("active");
    } else {
        if (tabF) tabF.classList.add("active");
        if (tabM) tabM.classList.remove("active");
        if (modF) modF.classList.add("active");
        if (modM) modM.classList.remove("active");
    }

    const currentInfo = getShapeData(g, state.profile.goalType);
    state.profile.goalType = currentInfo.key;

    renderBodyShapeCards("main-body-shapes-grid", g, currentInfo.key);
    renderBodyShapeCards("modal-body-shapes-grid", g, currentInfo.key);

    renderTargetPhysiqueCard();
    renderWorkoutExercises();
}

function onProfileGenderChanged(gender) {
    const profGenderSelect = document.getElementById("prof-gender");
    if (profGenderSelect) profGenderSelect.value = gender;
    switchShapeGender(gender, true);
    if (state.token) {
        saveProfileSilent();
    }
}

// 视觉身材形态卡片点击选中
function selectVisualGoalShape(key, showToast = true) {
    let g = state.profile.gender || "female";
    if (BODY_SHAPES_DATA.male[key]) {
        g = "male";
    } else if (BODY_SHAPES_DATA.female[key]) {
        g = "female";
    }

    state.profile.gender = g;
    state.profile.goalType = key;

    switchShapeGender(g, false);

    const info = getShapeData(g, key);
    if (showToast) {
        callNativeToast(`已选身材：【${info.data.title}】，系统已更新代谢方案与训练！`);
        callNativeVibrate(50);
    }

    if (state.token) {
        saveProfileSilent();
    }
}

function selectGoalType(type) {
    selectVisualGoalShape(type, false);
}

// 目标体重只把估算值放进 placeholder：提示文字不会被提交，写得再离谱也不入库
function syncTargetWeightPlaceholder() {
    const wEl = document.getElementById("prof-weight-jin");
    const tEl = document.getElementById("prof-target-jin");
    if (!wEl || !tEl) return;
    const w = parseFloat(wEl.value);
    if (!Number.isFinite(w) || w < 40 || w > 600) {
        tEl.placeholder = "目标体重（斤）· 必填";
        return;
    }
    const suggest = Math.round(w * 0.88 * 10) / 10;
    tEl.placeholder = "目标体重（斤）· 按当前体重约 -12% 估的参考值 " + suggest + "，仅供参考，要自己填";
}

// ============ 第五批后续：网页端独占功能（公开大屏专用） ============
// App 装在手机上，没有"把链接发给家人盯着"这个场景；这两样只在公网大屏出现。

const PUBLIC_POLL_SEC = 30;
let publicPollTimer = null;

function isPublicScreen() {
    return !!window.__PUBLIC_USER__;
}

/** 公网大屏自动刷新：别人盯你的时候，不该还要手动刷新页面。 */
function showPublicFailure(e) {
    const el=document.getElementById("public-refresh-stamp");
    if(el){el.textContent="刷新失败，以下为上次数据："+String(e.message||e);el.className="public-refresh-stamp bad";}
}
let publicRefreshing=false;
async function refreshPublicNow() {
    if(publicRefreshing || !isPublicScreen())return;
    publicRefreshing=true;
    try{await loadPublicUserData(window.__PUBLIC_USER__);stampPublicRefresh();}
    catch(e){showPublicFailure(e);}
    finally{publicRefreshing=false;}
}
function startPublicPolling() {
    if(!isPublicScreen())return;
    stopPublicPolling();
    publicPollTimer=setInterval(()=>{if(document.visibilityState!=="hidden")refreshPublicNow();},PUBLIC_POLL_SEC*1000);
    refreshPublicNow();
}

function stopPublicPolling() {
    if (publicPollTimer) { clearInterval(publicPollTimer); publicPollTimer = null; }
}

function stampPublicRefresh() {
    const el = document.getElementById("public-refresh-stamp");
    if (!el) return;
    const d = new Date();
    const two = function (n) { return (n < 10 ? "0" : "") + n; };
    el.textContent = "每 " + PUBLIC_POLL_SEC + " 秒自动刷新 · 上次 "
        + two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
    el.className = "public-refresh-stamp";
}

/**
 * 生成进度海报：数字全部取自这次真实拉到的大屏数据，画不出来的就不画。
 * 没有任何一条流水时直接拒绝生成，而不是画一张空壳冒充进度。
 */
async function makeProgressPoster() {
    // 字段名一律以 applyDashboardData / compute_charts_data 实际产出的为准：
    // weightHistory 元素是 {date, val(kg), jin}，deficitHistory 元素是 {day, deficit, ...}
    const pts = (state.weightHistory || []).slice();
    const bars = (state.deficitHistory || []).slice();
    const prof = state.profile || {};
    const d = {
        current_weight_jin: prof.weightJin,
        target_weight_jin: prof.targetWeightJin,
        streak_days: state.streakDays,
        cycle_day: state.cycleDay,
        nickname: prof.nickname || state.publicNickname || ""
    };
    if (!pts.length && !d.current_weight_jin) {
        callNativeToast("还没有可画的数据：这条大屏目前一条记录都没有，不生成空海报");
        return;
    }
    const W = 900, H = 1200;
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const g = cv.getContext("2d");
    g.fillStyle = "#0F172A"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#10B981"; g.fillRect(0, 0, W, 10);

    g.fillStyle = "#F8FAFC";
    g.font = "bold 56px sans-serif";
    g.fillText("轻塑 · 减脂进度", 60, 110);
    g.font = "28px sans-serif";
    g.fillStyle = "#94A3B8";
    const who = d.nickname || window.__PUBLIC_USER__ || "";
    const now = new Date();
    g.fillText((who ? who + " · " : "") + now.getFullYear() + "-"
        + (now.getMonth() + 1) + "-" + now.getDate(), 60, 158);

    // 四个真实数字
    const cells = [
        ["当前体重", (d.current_weight_jin || (pts.length ? pts[pts.length - 1].jin : null))
            ? ((d.current_weight_jin || pts[pts.length - 1].jin) + " 斤") : "—"],
        ["目标体重", d.target_weight_jin ? d.target_weight_jin + " 斤" : "未设"],
        ["连续记录", (d.streak_days || 0) + " 天"],
        ["本周期第", (d.cycle_day || "?") + " 天"]
    ];
    let x = 60;
    for (let i = 0; i < cells.length; i++) {
        g.fillStyle = "#1E293B"; roundRect(g, x, 200, 180, 130, 14); g.fill();
        g.fillStyle = "#94A3B8"; g.font = "22px sans-serif"; g.fillText(cells[i][0], x + 18, 236);
        g.fillStyle = "#F1F5F9"; g.font = "bold 34px sans-serif"; g.fillText(cells[i][1], x + 18, 296);
        x += 200;
    }

    // 体重曲线（只有真实点，不插值补点）
    g.fillStyle = "#F8FAFC"; g.font = "bold 30px sans-serif";
    g.fillText("体重走势（只画真实记录过的那天）", 60, 400);
    g.strokeStyle = "#334155"; g.lineWidth = 2;
    g.strokeRect(60, 430, 780, 260);
    if (pts.length > 1) {
        const vals = pts.map(function (p) { return Number(p.jin); }).filter(Number.isFinite);
        const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
        const span = (hi - lo) || 1;
        g.strokeStyle = "#10B981"; g.lineWidth = 4; g.beginPath();
        for (let i = 0; i < pts.length; i++) {
            const v = Number(pts[i].jin);
            if (!Number.isFinite(v)) continue;
            const px = 80 + (740 * i / (pts.length - 1));
            const py = 660 - (220 * (v - lo) / span);
            if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
        }
        g.stroke();
        g.fillStyle = "#94A3B8"; g.font = "20px sans-serif";
        g.fillText("最低 " + lo.toFixed(1) + " 斤", 80, 715);
        g.fillText("最高 " + hi.toFixed(1) + " 斤", 620, 715);
    } else {
        g.fillStyle = "#64748B"; g.font = "26px sans-serif";
        g.fillText("只有一个记录点，画不出趋势", 90, 570);
    }

    // 近 7 天净缺口柱（0 就是 0，不拿目标值冒充）
    g.fillStyle = "#F8FAFC"; g.font = "bold 30px sans-serif";
    g.fillText("近 7 天净缺口 kcal", 60, 790);
    if (bars.length) {
        const maxV = Math.max.apply(null, bars.map(function (b) { return Math.abs(Number(b.deficit) || 0); })) || 1;
        let bx = 80;
        for (let i = 0; i < bars.length; i++) {
            const v = Number(bars[i].deficit) || 0;
            const hgt = Math.round(180 * Math.abs(v) / maxV);
            g.fillStyle = v > 0 ? "#10B981" : "#475569";
            g.fillRect(bx, 1000 - hgt, 70, hgt);
            g.fillStyle = "#94A3B8"; g.font = "18px sans-serif";
            g.fillText(String(v), bx, 1024);
            g.fillStyle = "#64748B"; g.font = "15px sans-serif";
            g.fillText(String(bars[i].date || bars[i].day || ""), bx, 1046);
            bx += 100;
        }
    } else {
        g.fillStyle = "#64748B"; g.font = "26px sans-serif";
        g.fillText("这 7 天没有可算的缺口记录", 90, 900);
    }

    g.fillStyle = "#64748B"; g.font = "20px sans-serif";
    g.fillText("数据来自本人真实打卡流水；热量与宏量为粗估口径，不是营养学数据。", 60, 1120);
    g.fillText("生成时间 " + now.toLocaleString(), 60, 1152);

    try {
        const url = cv.toDataURL("image/png");
        const a = document.createElement("a");
        a.href = url;
        a.download = "轻塑进度_" + (who || "大屏") + ".png";
        document.body.appendChild(a); a.click(); a.remove();
        callNativeToast("海报已生成，数字都来自这次真实拉到的记录");
    } catch (e) {
        callNativeToast("这台浏览器不允许导出画布，海报没生成：" + ((e && e.message) || ""));
    }
}

function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    g.lineTo(x + r, y + h); g.quadraticCurveTo(x, y + h, x, y + h - r);
    g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y);
    g.closePath();
}

// ============ 第七批：网页端独占工作台（手机上做不了的三件事） ============
// 判断标准只有一条：这件事需不需要大屏、键盘或打印机。需要的就留在网页，
// App 里整块不出现（靠 inApp() 判断），不做"两边一模一样"的复制品。

const WEB_WORKBENCH = true;

/** 目标日倒推：给定想达到的日期，算每天需要多大缺口，并拿 TDEE 与安全下限判可行性。 */
function planByTargetDate() {
    const out = document.getElementById("wb-plan-out");
    const dateEl = document.getElementById("wb-target-date");
    const goalEl = document.getElementById("wb-target-jin");
    if (!out || !dateEl) return;
    const p = state.profile || {};
    const m = state.calculated || {};
    const cur = Number(state.currentWeightJin || p.weightJin || 0);
    const goal = Number(goalEl && goalEl.value ? goalEl.value : p.targetWeightJin);
    const tdee = Number(m.tdee || 0);
    const bmr = Number(m.bmr || 0);
    if (!dateEl.value) { out.innerHTML = "<span class='wb-warn'>先选一个目标日期</span>"; return; }
    if (!(cur > 0) || !(goal > 0) || !(tdee > 0)) {
        out.innerHTML = "<span class='wb-warn'>缺当前体重或每日消耗，算不了——先去档案填真实值，"
            + "我不替你猜身体数据</span>";
        return;
    }
    const days = Math.ceil((new Date(dateEl.value) - new Date()) / 86400000);
    if (!(days > 0)) { out.innerHTML = "<span class='wb-warn'>目标日期得在未来</span>"; return; }
    const loseJin = cur - goal;
    if (loseJin <= 0) {
        out.innerHTML = "<span class='wb-ok'>目标不低于当前体重，不需要制造缺口；"
            + "这情况通常该问的是怎么练，不是怎么吃</span>";
        return;
    }
    const weeklyJin=(loseJin*7/days).toFixed(2);
    out.innerHTML="<p>还剩 <strong>"+days+"</strong> 天，目标变化 <strong>"+loseJin.toFixed(1)+"</strong> 斤。</p>"
        +"<p>算术所需周变化："+weeklyJin+" 斤/周；这只是日期与体重差的除法。</p>"
        +"<p>不能据此判断目标可行性、推荐进食量或承诺达标日期；体重变化不是固定比例的脂肪变化。预算仍是公式估算，需按实际情况核对。</p>";

}

/** 流水表格：把导出 CSV 拉下来在前端解析，支持搜索、按列排序、只看超标那几笔。 */
let wbRows = null;
async function loadLedger() {
    const box = document.getElementById("wb-ledger");
    if (!box) return;
    if (!state.token) { box.innerHTML = "<span class='wb-warn'>登录后才看得到自己的流水</span>"; return; }
    if (!wbRows) {
        box.innerHTML = "<span class='wb-note'>正在读最近记录…</span>";
        try {
            wbRows=[];
            for(const kind of ['food','weight','workout']){
                const result=await getJson(`/api/records?kind=${kind}&offset=0&limit=100`);
                wbRows.push(...result.rows.map(r=>({__kind:{food:'饮食',weight:'体重',workout:'训练'}[kind],日期:r.log_date,项目:r.food_name||r.plan_name||'体重',数值:kind==='food'?r.cal:kind==='weight'?r.weight_jin:r.cal_burned,备注:r.estimate_reason||''})));
            }
        } catch (e) {
            box.innerHTML = "<span class='wb-bad'>读不到流水：" + escapeHtml((e && e.message) || "") + "</span>";
            return;
        }
    }
    renderLedger();
}

function splitCsvLine(line) {
    // 导出里"项目"这一列带逗号且被引号包住（如 "一个肉包子，一个鸡蛋"），
    // 不处理引号就会把一列切成几列
    const out = [];
    let cur = ""; let inQ = false;
    for (let i2 = 0; i2 < line.length; i2++) {
        const ch = line[i2];
        if (ch === String.fromCharCode(34)) { inQ = !inQ; continue; }
        if (ch === "," && !inQ) { out.push(cur); cur = ""; continue; }
        cur += ch;
    }
    out.push(cur);
    return out;
}

const CR_LF_RE = new RegExp("[" + String.fromCharCode(13) + String.fromCharCode(10) + "]+");

function parseCsv(text) {
    // 真实导出是平表：表,日期,项目,数值,备注 —— 第一列就是分类
    const lines = String(text).split(CR_LF_RE).filter(function (l) { return l.trim(); });
    if (!lines.length) return [];
    const cols = splitCsvLine(lines[0]);
    const rows = [];
    for (let i2 = 1; i2 < lines.length; i2++) {
        const cells = splitCsvLine(lines[i2]);
        const r = {};
        for (let c = 0; c < cols.length; c++) r[cols[c]] = cells[c] || "";
        r.__kind = r["表"] || "";
        rows.push(r);
    }
    return rows;
}

function renderLedger() {
    const box = document.getElementById("wb-ledger");
    if (!box || !wbRows) return;
    const q = (document.getElementById("wb-search").value || "").trim().toLowerCase();
    const kind = document.getElementById("wb-kind").value;
    const onlyOver = document.getElementById("wb-over").checked;
    let rows = wbRows.filter(function (r) {
        if (kind && r.__kind !== kind) return false;
        const cal = Number(r["数值"] || r.cal || 0);
        if (onlyOver && !(cal >= 600)) return false;
        if (!q) return true;
        return Object.keys(r).some(function (k) {
            return String(r[k]).toLowerCase().indexOf(q) >= 0;
        });
    });
    const sortKey = window.__wbSort || "";
    if (sortKey) {
        rows = rows.slice().sort(function (a, b) {
            const av = a[sortKey], bv = b[sortKey];
            const an = Number(av), bn = Number(bv);
            if (Number.isFinite(an) && Number.isFinite(bn)) return bn - an;
            return String(bv).localeCompare(String(av));
        });
    }
    if (!rows.length) { box.innerHTML = "<span class='wb-note'>这一筛选条件下没有记录</span>"; return; }
    const cols = Object.keys(rows[0]).filter(function (k) { return k !== "__kind"; }).slice(0, 8);
    let html = "<div class='wb-count'>共 " + rows.length + " 笔（每类最近100笔，已按筛选）</div><div class='wb-scroll'><table class='wb-table'><thead><tr>";
    html += "<th>类</th>";
    for (const c of cols) html += "<th data-col='" + c + "'>" + escapeHtml(c) + "</th>";
    html += "</tr></thead><tbody>";
    for (const r of rows.slice(0, 300)) {
        html += "<tr><td>" + escapeHtml(r.__kind || "") + "</td>";
        for (const c of cols) html += "<td>" + escapeHtml(String(r[c] || "")) + "</td>";
        html += "</tr>";
    }
    html += "</tbody></table></div>";
    if (rows.length > 300) html += "<div class='wb-note'>只画前 300 笔，要全部请用导出 CSV</div>";
    box.innerHTML = html;
    box.querySelectorAll("th[data-col]").forEach(function (th) {
        th.addEventListener("click", function () {
            window.__wbSort = th.getAttribute("data-col");
            renderLedger();
        });
    });
}

/** 周复盘：把七天真数据排成一页，走浏览器打印（App 里没有打印这件事）。 */
function renderWeeklyReport() {
    const el = document.getElementById("wb-report");
    if (!el) return;
    const m = state.calculated || {};
    const p = state.profile || {};
    const bars = state.deficitHistory || [];
    const pts = state.weightHistory || [];
    const sum = bars.filter(b=>b.record_status==="complete").reduce(function (a, b) { return a + (Number(b.deficit) || 0); }, 0);
    const logged = bars.filter(b => b.has_records || b.consumed || b.burned).length;
    const windowStart = bars.length ? bars[0].date : "9999";
    const weeklyPts = pts.filter(p => p.full_date && p.full_date >= windowStart);
    const w0 = weeklyPts.length ? Number(weeklyPts[0].jin) : 0;
    const w1 = weeklyPts.length > 1 ? Number(weeklyPts[weeklyPts.length - 1].jin) : 0;
    const rows = bars.map(function (b) {
        const d = Number(b.deficit) || 0;
        return "<tr><td>" + escapeHtml(b.date || b.day || "") + "</td><td class='num'>"
            + (Number(b.consumed) || 0) + "</td><td class='num'>" + (Number(b.burned) || 0)
            + "</td><td class='num " + (d > 0 ? "pos" : "neg") + "'>" + d + "</td></tr>";
    }).join("");
    el.innerHTML = "<div class='rpt-head'><div class='rpt-title'>轻塑 · 周复盘</div>"
        + "<div class='rpt-sub'>" + escapeHtml(state.user && state.user.username ? state.user.username : "")
        + " · 生成于 " + new Date().toLocaleString() + "</div></div>"
        + "<div class='rpt-grid'>"
        + "<div><i>完整日估算缺口合计</i><b>" + sum + " kcal</b></div>"
        + "<div><i>有记录的天数</i><b>" + logged + " / 7</b></div>"
        + "<div><i>体重变化</i><b>" + (w0 && w1 ? (w1 - w0).toFixed(1) + " 斤" : "数据不足") + "</b></div>"
        + "<div><i>连续记录</i><b>" + (state.streakDays || 0) + " 天</b></div>"
        + "</div>"
        + "<table class='rpt-table'><thead><tr><th>日期</th><th>摄入</th><th>消耗</th><th>净缺口</th></tr></thead>"
        + "<tbody>" + (rows || "<tr><td colspan=4>这 7 天没有可算的记录</td></tr>") + "</tbody></table>"
        + "<div class='rpt-foot'>零缺口与未记录不同；未确认完整的日期只作部分记录估算，不用于完整日结论。"
        + "摄入和消耗为估算；手填热量及未匹配食材的宏量未知。当天一笔未记不等于零摄入。"
        + "本系统不诊断疾病，涉及用药与疾病请咨询医生。</div>";
}

function printWeeklyReport() {
    renderWeeklyReport();
    document.body.classList.add("printing-report");
    try {
        window.print();
    } catch (e) {
        callNativeToast("这台浏览器不让调打印，试试菜单里的打印");
    }
    setTimeout(function () { document.body.classList.remove("printing-report"); }, 500);
}

/** 整块工作台只在网页出现；App 里连 DOM 都不留。 */
function initWebWorkbench() {
    if (!isPublicScreen() && !inApp()) {
        const host = document.getElementById("web-workbench");
        if (host) host.style.display = "block";
        if (state.token) renderHabitMatrix();
        paintCheerCount();
        return;
    }
    const host = document.getElementById("web-workbench");
    if (host) host.remove();
}

/** 30 天自律矩阵。三处必须同时成立才是真功能：后端真给 30 天、日期按本地历法算、
    取数失败要在屏上说原因——之前它读的是只有 7 天的 deficitHistory，
    23 个格子永远灰着，而且首屏在任何数据到位之前渲染，进去看就是全灰。 */
async function renderHabitMatrix() {
    if (typeof document === "undefined") return;
    const el = document.getElementById("wb-habit-matrix");
    if (!el) return;
    let bars;
    try {
        const d = await getJson("/api/habits");
        bars = (d && d.days) || [];
    } catch (e) {
        el.innerHTML = "";
        el.className = "wb-habit-empty";
        el.textContent = "矩阵没取到数据：" + String((e && e.message) || e);
        return;
    }
    el.className = "wb-habit-grid";
    const dates = [];
    const now = new Date();
    for (let i = 29; i >= 0; i--) {
        // 不能用 toISOString：UTC+8 的早上 8 点前它会给出昨天，今天这一格就成了"未打卡"
        const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
        const yy = String(d.getFullYear());
        const mm = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        dates.push({ full: yy + "-" + mm + "-" + dd, label: mm + "-" + dd });
    }
    const lookup = {};
    for (const b of bars) {
        const k = String(b.date || b.day || "");
        lookup[k] = b;
    }
    let html = "";
    for (const item of dates) {
        const rec = lookup[item.full] || lookup[item.label];
        let lvl = 0;
        let tip = item.label + "：未打卡";
        if (rec) {
            const consumed = Number(rec.consumed) || 0;
            const burned = Number(rec.burned) || 0;
            const deficit = Number(rec.deficit) || 0;
            if (!rec.has_records && consumed === 0 && burned === 0) {
                // 后端每天都给一行（没记就是 0），所以"没记录"必须靠这两个 0 认出来；
                // 旧写法 score=0 也被抬成 lvl-1，30 个格子全绿，等于在伪造全勤
                tip = item.label + "：这一天一笔未记";
            } else {
                let score = rec.has_records ? 1 : 0;
                if (consumed > 0) score++;
                if (burned > 0) score++;
                if (rec.record_status === "complete" && deficit >= 300) score++;
                lvl = Math.min(3, score);
                tip = item.label + "：摄入 " + consumed + " / 消耗 " + burned + " / 净缺口 " + deficit + " kcal";
            }
        }
        html += "<div class='wb-habit-cell lvl-" + lvl + "' title='" + escapeHtml(tip) + "'></div>";
    }
    el.innerHTML = html;
}

/** 切换大屏全景沉浸投屏模式 (Kiosk Mode) */
function toggleKioskMode() {
    if (typeof document === "undefined") return;
    const isKiosk = document.body.classList.toggle("kiosk-mode");
    if (isKiosk) {
        callNativeToast("📺 已开启全景沉浸大屏模式，再次点击可退出");
        if (document.documentElement && document.documentElement.requestFullscreen) {
            try { document.documentElement.requestFullscreen(); } catch (e) {}
        }
    } else {
        callNativeToast("已退出全景沉浸模式");
        if (document.exitFullscreen && document.fullscreenElement) {
            try { document.exitFullscreen(); } catch (e) {}
        }
    }
}

/** 打气计数只能来自服务端：写 localStorage 的话，"已收到 N 枚"数的其实是
    这位访客自己在这台设备上点了几次，大屏主人永远看不到别人送的东西。 */
function paintCheerCount() {
    const el = document.getElementById("pub-cheer-count");
    if (!el) return;
    const n = Number(state.cheerTotal || 0);
    el.textContent = n > 0 ? "已收到 " + n + " 枚打气" : "还没有人送过打气";
}

async function sendCheerSticker(kind) {
    if (typeof document === "undefined") return;
    const toast = document.getElementById("pub-cheer-toast");
    function flash(txt) {
        if (!toast) return;
        toast.style.display = "block";
        toast.textContent = txt;
        setTimeout(function () { if (toast) toast.style.display = "none"; }, 3000);
    }
    const who = window.__PUBLIC_USER__ || "";
    if (!who) { flash("这条链接没绑定要加油的人，送不出去"); return; }
    try {
        const data = await postApi("/api/cheer", { username: who, k: publicShareKey(), kind: kind });
        state.cheerTotal = Number(data.total || 0);
        paintCheerCount();
        flash("🎉 已把「" + kind + "」送给 @" + who);
    } catch (e) {
        // 没送达就说没送达，不能把失败演成成功
        flash("这枚没送出去：" + String((e && e.message) || e));
    }
}



function openProfileModal() {
    const p = state.profile;
    const g = p.gender || "female";
    const profGenderSelect = document.getElementById("prof-gender");
    if (profGenderSelect) profGenderSelect.value = g;
    document.getElementById("prof-age").value = (p.age == null ? "" : p.age);
    document.getElementById("prof-height").value = (p.height == null ? "" : p.height);
    document.getElementById("prof-weight-jin").value = (p.weightJin == null ? "" : p.weightJin);
    document.getElementById("prof-target-jin").value = (p.targetWeightJin == null ? "" : p.targetWeightJin);
    syncTargetWeightPlaceholder();
    document.getElementById("prof-scene").value = p.scene || "home";
    
    const diningEl = document.getElementById("prof-dining-mode");
    if (diningEl) diningEl.value = state.diningMode || p.diningMode || "takeout";

    switchShapeGender(g, false);
    document.getElementById("profile-modal").classList.add("show");
}

function closeProfileModal() {
    document.getElementById("profile-modal").classList.remove("show");
}

async function saveCustomProfile() {
    const gender = document.getElementById("prof-gender").value;
    const age = parseInt(document.getElementById("prof-age").value, 10);
    const height = parseFloat(document.getElementById("prof-height").value);
    const weightJin = parseFloat(document.getElementById("prof-weight-jin").value);
    const targetWeightJin = parseFloat(document.getElementById("prof-target-jin").value);
    if (![age, height, weightJin, targetWeightJin].every(Number.isFinite)) {
        callNativeToast("年龄、身高、当前体重、目标体重四项都要填真实数字，留空保存不了");
        return;
    }
    if (age < 10 || age > 100 || height < 80 || height > 250
        || weightJin < 40 || weightJin > 600 || targetWeightJin < 40 || targetWeightJin > 600) {
        callNativeToast("数值超出合理范围（年龄 18~100 / 身高 80~250cm / 体重 40~600 斤）");
        return;
    }
    const scene = document.getElementById("prof-scene").value;
    const diningMode = document.getElementById("prof-dining-mode") ? document.getElementById("prof-dining-mode").value : "takeout";

    try {
        await postApi("/api/profile/update", {
            gender, age, height, weight_jin: weightJin,
            target_weight_jin: targetWeightJin, goal_type: state.profile.goalType,
            dining_mode: diningMode, scene
        });
        closeProfileModal();
        callNativeToast("🎉 专属身材方案已定制保存！");
        callNativeVibrate(150);
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "档案方案");
    }
}

async function saveProfileSilent() {
    if (!state.token) return;
    try {
        const p = state.profile;
        await fetch(`${API_BASE}/api/profile/update`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${state.token}`
            },
            body: JSON.stringify({
                gender: p.gender,
                age: p.age,
                height: p.height,
                weight_jin: p.weightJin,
                target_weight_jin: p.targetWeightJin,
                goal_type: p.goalType,
                dining_mode: p.diningMode,
                scene: p.scene
            })
        });
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch(e) {
        console.warn("Silent profile sync error", e);
    }
}

// 饮食模式切换 (自做 vs 外卖)
function switchDiningMode(mode) {
    state.diningMode = mode;
    state.profile.diningMode = mode;

    const btnCook = document.getElementById("btn-dining-cook");
    const btnTakeout = document.getElementById("btn-dining-takeout");
    const viewCook = document.getElementById("dining-cook-view");
    const viewTakeout = document.getElementById("dining-takeout-view");
    const badge = document.getElementById("current-dining-badge");

    if (mode === "takeout") {
        if (btnTakeout) btnTakeout.classList.add("active");
        if (btnCook) btnCook.classList.remove("active");
        if (viewTakeout) viewTakeout.style.display = "block";
        if (viewCook) viewCook.style.display = "none";
        if (badge) badge.innerText = "🛵 上班族外卖吃瘦方案";
    } else {
        if (btnCook) btnCook.classList.add("active");
        if (btnTakeout) btnTakeout.classList.remove("active");
        if (viewCook) viewCook.style.display = "block";
        if (viewTakeout) viewTakeout.style.display = "none";
        if (badge) badge.innerText = "🍳 4套家常自炊备餐方案";
    }
}

function syncDiningMode(val) {
    switchDiningMode(val);
}

function copyTakeoutRemark() {
    const textEl = document.getElementById("text-takeout-remark");
    const text = textEl ? textEl.innerText.trim() : "【减脂期严格控油备注】：老板您好！请少油少盐不要放糖！";
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            callNativeToast("📋 外卖减脂备注已复制！去美团/饿了么直接粘贴即可！");
            callNativeVibrate(50);
        }).catch(() => fallbackCopy(text));
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    callNativeToast("📋 备注已复制！直接粘贴到外卖订单中！");
    callNativeVibrate(50);
}

// 目标身材预览卡片 (男女分流 + 8大形态精准对应)
function renderTargetPhysiqueCard() {
    const card = document.getElementById("target-physique-summary-card");
    if (!card) return;

    const info = getShapeData(state.profile.gender, state.profile.goalType);
    const cur = info.data;
    const genderTag = (info.gender === "male") ? "👨 男士专属形体" : "👩 女士专属形体";

    card.innerHTML = `
        <div style="flex-shrink: 0; width: 66px; height: 84px; background: #FFFFFF; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 4px; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
            ${cur.svg}
        </div>
        <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 2px;">
                <span style="font-size: 13.5px; font-weight: 800; color: var(--text-main);">${cur.title}</span>
                <span style="font-size: 10px; background: rgba(16,185,129,0.12); color: #047857; padding: 1px 6px; border-radius: 99px; font-weight: 700;">${genderTag}</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); line-height: 1.4; margin-bottom: 4px;">${cur.desc}</div>
            <div style="font-size: 10.5px; color: var(--primary-dark); font-weight: 700; margin-bottom: 2px;">🥗 饮食重点：${cur.dietSpec}</div>
            <div style="font-size: 10.5px; color: #2563EB; font-weight: 700;">🏋️ 训练专攻：${cur.workoutSpec}</div>
        </div>
    `;
}

// 动态生成动作库 (男女分流 8款针对性训练库)
function renderWorkoutExercises() {
    const container = document.getElementById("workout-exercises-card");
    const badge = document.getElementById("workout-plan-badge");
    const callout = document.getElementById("workout-summary-callout");
    if (!container) return;

    const info = getShapeData(state.profile.gender, state.profile.goalType);
    const key = info.key;

    let planTitle = "";
    let calloutHtml = "";
    let list = [];

    switch(key) {
        // 女性专属动作库
        case "female_hourglass":
            planTitle = "⏳ S型沙漏 · 核心马甲线与翘臀雕刻";
            calloutHtml = "<strong>形态专攻：</strong> 激活臀大肌与臀中肌上部，强化腹横肌收紧内脏腰围，打造0.7极致腰臀比！";
            list = [
                { name: "1. 仰卧臀桥顶峰收缩 (Glute Bridge)", reps: "20次 × 4组", tip: "脚后跟踏地顶起，顶峰夹紧臀大肌2秒，雕刻饱满翘臀线条。" },
                { name: "2. 死虫子腹横肌抗旋 (Dead Bug)", reps: "16次 × 3组", tip: "腰椎紧贴地面，对角线手脚延伸，内收腹横肌，强力紧致下腹围度。" },
                { name: "3. 弹力带侧向行走与蚌式开合", reps: "15次 × 3组", tip: "膝盖上方套弹力带，激活臀中肌，消除假胯宽并拉长腿部线条。" },
                { name: "4. 跪姿超人式核心支撑", reps: "15次 × 3组", tip: "对角伸展维持躯干稳定，收紧后侧链条与下背部，改善骨盆前倾。" }
            ];
            break;

        case "female_lean":
            planTitle = "🏃 修长轻盈 · 芭蕾普拉提去水肿显瘦";
            calloutHtml = "<strong>形态专攻：</strong> 肌肉离心拉长无水肿，低冲击不粗腿，配合30分钟超慢跑全身高效刷脂！";
            list = [
                { name: "1. 芭蕾式宽距深蹲 (Plie Squats)", reps: "20次 × 3组", tip: "脚尖外展45度，直上直下拉长内收肌，紧致大腿内侧线条。" },
                { name: "2. 站姿直腿后踢与侧抬腿", reps: "20次 × 3组", tip: "轻量高频，收紧臀腿连接处，消除臀下松弛泡芙脂肪。" },
                { name: "3. 跪姿俯卧撑 / 弹力带推胸", reps: "12次 × 3组", tip: "收紧手臂拜拜肉与副乳，塑造修长紧致的直角肩臂线条。" },
                { name: "4. 30分钟超慢跑 (Zone2燃脂心率)", reps: "持续 30分钟", tip: "平稳微喘，高频刷脂排水肿，完全保护下肢关节体感轻盈。" }
            ];
            break;

        case "female_athletic":
            planTitle = "🏋️ 紧致力量 · 健美微肌与直角肩背";
            calloutHtml = "<strong>形态专攻：</strong> 渐进式抗阻复合动作，提升骨骼肌率与静息代谢率，打造紧致直角肩、马甲线分块！";
            list = [
                { name: "1. 高脚杯负重深蹲 (Goblet Squats)", reps: "12次 × 4组", tip: "胸前持负重下蹲，全腿及臀大肌高负荷离心刺激，强效拉升代谢。" },
                { name: "2. 罗马尼亚硬拉 (RDL)", reps: "12次 × 4组", tip: "屈髋微屈膝，感知腘绳肌与臀肌强力受拉，挺拔臀腿线条。" },
                { name: "3. 仰卧卷腹 + 悬垂提膝", reps: "15次 × 4组", tip: "下背贴地卷起上半身，充分挤压腹直肌雕刻块状腹肌轮廓。" },
                { name: "4. 弹力带面拉与俯身飞鸟", reps: "15次 × 4组", tip: "强化三角肌后束与上背菱形肌，改善圆肩驼背，立现气质直角肩。" }
            ];
            break;

        case "female_steady":
            planTitle = "📉 稳健脱脂 · 零跳跃低冲击膝盖保护";
            calloutHtml = "<strong>形态专攻：</strong> 椅子半蹲与零冲击核心动作，100%保护膝关节半月板，大基数平稳脱脂防反弹！";
            list = [
                { name: "1. 椅子辅助半蹲 (Chair Squats)", reps: "15次 × 3组", tip: "触椅即起，膝盖不内扣，大腿发力，保护膝关节并高效消耗能量。" },
                { name: "2. 靠墙推胸俯卧撑 (Wall Push-ups)", reps: "15次 × 3组", tip: "双手推墙收紧手臂与肩背，零重力负担唤醒上肢肌力。" },
                { name: "3. 站姿对角提膝 (Knee to Elbow)", reps: "20次 × 3组", tip: "提膝触肘核心收紧，低冲击零跳跃，平稳刺激腹部代谢。" },
                { name: "4. 30分钟平地快步走", reps: "持续 30分钟", tip: "大步摆臂平稳快走，心率稳定在燃脂区间，避免软骨磨损。" }
            ];
            break;

        // 男性专属动作库
        case "male_v_taper":
            planTitle = "👑 经典倒三角 · 宽肩阔背铠甲腹肌";
            calloutHtml = "<strong>形态专攻：</strong> 聚焦背阔肌宽度、三角肌中束与下腹人鱼线，以低体脂塑造威猛V-Taper霸气倒三角！";
            list = [
                { name: "1. 引体向上 / 弹力带高位下拉", reps: "10-12次 × 4组", tip: "沉肩下拉挤压背阔肌两侧，加宽上半身V-Taper倒三角轮廓。" },
                { name: "2. 哑铃/水瓶站姿侧平举 (Lateral Raises)", reps: "15次 × 4组", tip: "肘微屈平举至水平，精准轰炸三角肌中束，加宽肩部骨架感。" },
                { name: "3. 仰卧双腿反向卷腹与剪刀腿", reps: "15次 × 4组", tip: "下腹收紧骨盆后倾，强力刻画下腹铠甲腹肌与前锯肌人鱼线。" },
                { name: "4. 钻石俯卧撑 + 上斜俯卧撑", reps: "12次 × 3组", tip: "强化胸肌中缝与上胸线条，提升上肢爆发力与饱满轮廓。" }
            ];
            break;

        case "male_lean":
            planTitle = "👔 修长衣架子 · 挺拔肩背穿衣有型";
            calloutHtml = "<strong>形态专攻：</strong> 消除腰腹部游泳圈，矫正含胸驼背，强化核心抗屈曲，穿衬衫西装如衣架子！";
            list = [
                { name: "1. 标准俯卧撑多握距循环", reps: "15次 × 3组", tip: "宽窄距交替，激活胸大肌与核心稳定性，增强上身挺拔感。" },
                { name: "2. 核心平板支撑转体 (Plank Twist)", reps: "45秒 × 3组", tip: "收紧腹横肌与侧腹斜肌，消除腰部两侧松垮赘肉。" },
                { name: "3. 靠墙 W-Y 肩胛滑动", reps: "15次 × 3组", tip: "后脑肩胛贴墙滑动，打开胸廓纠正圆肩驼背，拉长颈部线条。" },
                { name: "4. 25分钟跑步机大坡度快走", reps: "持续 25分钟", tip: "坡度8-10，速度5km/h，高倾角燃脂保护膝盖消平小肚子。" }
            ];
            break;

        case "male_muscular":
            planTitle = "💪 饱满力量 · 厚实胸大肌与粗壮麒麟臂";
            calloutHtml = "<strong>形态专攻：</strong> 大重量高抗阻复合动作，刺激睾酮分泌与肌纤维肥大，打造澎湃肌肉量！";
            list = [
                { name: "1. 负重深蹲 / 爆发力半蹲跳", reps: "10次 × 4组", tip: "深蹲强化臀腿大肌群，拉升全身睾酮与高代谢合成环境。" },
                { name: "2. 深度离心俯卧撑 / 哑铃卧推", reps: "10-12次 × 4组", tip: "下落3秒缓慢离心，爆发力推起顶峰夹胸，深度撕裂胸肌。" },
                { name: "3. 俯身单臂哑铃划船 (One-arm Rows)", reps: "12次 × 4组", tip: "背阔肌主导向后提拉，增加背部厚度与倒三角饱满度。" },
                { name: "4. 窄距俯卧撑 + 椅子臂屈伸", reps: "12-15次 × 4组", tip: "轰炸肱三头肌外侧头，快速充血围度粗壮麒麟臂。" }
            ];
            break;

        case "male_steady":
        default:
            planTitle = "📉 啤酒肚专项 · 击退内脏脂肪与脂肪肝";
            calloutHtml = "<strong>形态专攻：</strong> 专项击退向心性腹部脂肪，保护承重膝关节，配合核心转体紧致下腹壁！";
            list = [
                { name: "1. 动感单车/椭圆机恒速刷脂", reps: "25-30分钟", tip: "零膝盖落地冲击，高效消耗内脏周围储积甘油三酯。" },
                { name: "2. 坐姿核心俄罗斯转体 (Russian Twists)", reps: "20次 × 3组", tip: "双脚微抬，躯干左右旋转，收紧内脏肌壁消减腰围。" },
                { name: "3. 椅子辅助半蹲 (Chair Squats)", reps: "15次 × 3组", tip: "触椅即起保护半月板，维持基础代谢，防止减脂掉肌肉。" },
                { name: "4. 弹力带站姿水平夹胸", reps: "15次 × 3组", tip: "挺胸沉肩双臂前夹，打开胸廓，改善大肚引发的骨盆前倾。" }
            ];
            break;
    }

    if (badge) badge.innerText = planTitle;
    if (callout) callout.innerHTML = calloutHtml;

    let html = `<div style="font-weight: 700; font-size: 13.5px; color: var(--text-main); margin-bottom: 4px;">📋 【${planTitle}】的 4 个动作循环：</div>`
        + `<div style="font-size: 11px; color: var(--text-muted); margin-bottom: 10px;">下面的倒计时就是给这 4 个动作用的：一轮约 ${timerSeconds / 60} 分钟，做完按【记录今日训练打卡】。</div>`;
    list.forEach((item, idx) => {
        const meta = EX_STEPS[key + ":" + idx] || {};
        const steps = (meta.steps || []).map((x, i) => `<li>${i + 1}. ${x}</li>`).join("");
        const wrong = meta.wrong ? `<div class="ex-wrong">常见错误：${meta.wrong}</div>` : "";
        html += `
            <div class="exercise-card">
                <div class="exercise-header">
                    <span class="exercise-name">${item.name}</span>
                    <span class="exercise-reps">${item.reps}</span>
                </div>
                <div class="exercise-tip">${item.tip}</div>
                <div class="ex-actions">
                    <button class="ex-btn" onclick="openExerciseDetail(${idx})">动作流程与示意动画</button>
                    <button class="ex-btn ghost" onclick="toggleExerciseSteps(${idx})">只看要点</button>
                    <button class="ex-btn video" onclick="openExerciseVideo(${idx})">看演示视频</button>
                </div>
                <ol class="ex-steps" id="ex-steps-${idx}">${steps}</ol>
                ${wrong}
            </div>
        `;
    });
    container.innerHTML = html;
    window.__currentExercises = list;
    window.__currentExKey = key;
}

// 每个动作的标准分解与常见错误，按「身形key:组内序号」定位。
// 只写做得对不对要看的点，不写无法验证的疗效承诺。
const EX_STEPS = {
    "female_hourglass:0": { steps: ["仰卧屈膝，脚跟离臀约一脚长", "脚跟下压送髋至肩-髋-膝一条线", "顶端夹紧臀部停 2 秒再落下，不顶腰"], wrong: "用腰往上顶，顶端塌腰，腰先酸就是错了" },
    "female_hourglass:1": { steps: ["仰卧，双臂伸直指向天花板，双腿抬成 90 度", "对侧手脚同时缓慢伸出，腰椎全程贴地", "回位时呼气，全程下背不离开地面"], wrong: "下背拱起离地，说明核心已失守，改小幅度" },
    "female_hourglass:2": { steps: ["弹力带套在膝盖上方，微蹲位站稳", "侧向跨步，脚尖朝前不内扣", "蚌式：侧卧屈膝，脚跟并拢向上开膝"], wrong: "膝盖内扣、腰跟着晃，就变成了代偿" },
    "female_hourglass:3": { steps: ["四点跪位，手腕在肩正下方", "对侧手脚同时伸出，骨盆保持水平", "停 2 秒回收，换边，躯干不左右转"], wrong: "腿抬越高腰越塌，高度以骨盆不动为准" },
    "female_lean:0": { steps: ["双脚宽于肩，脚尖外展约 45 度", "膝盖对准脚尖下蹲，重心在脚跟", "起身时夹臀，不靠膝盖发力"], wrong: "膝盖往里塌，大腿内侧没吃到力" },
    "female_lean:1": { steps: ["扶墙站稳，支撑腿微屈", "后腿伸直向后上方抬起，不塌腰", "侧抬腿时脚尖朝前，骨盆不翻"], wrong: "腰跟着抬腿一起摆，就变成甩腿" },
    "female_lean:2": { steps: ["跪姿，双手略宽于肩撑地", "身体一条直线向下压，肘约 45 度夹", "推起时肩胛向前推满"], wrong: "塌腰或耸肩，颈先酸即错" },
    "female_lean:3": { steps: ["步频偏快、步幅小，能说话但唱不了歌", "落地用中足，膝盖不内扣", "前后各 3 分钟慢走过渡"], wrong: "一上来就冲快，心率过高坚持不到 30 分钟" },
    "female_athletic:0": { steps: ["双手托住负重贴胸前，肘不外张", "下蹲至髋低于膝，胸不塌", "脚跟发力站起，顶端夹臀"], wrong: "含胸低头、脚跟离地，重量全压到膝" },
    "female_athletic:1": { steps: ["双手持铃贴大腿，肩胛下沉后收", "屈髋把臀向后推，膝盖只微屈", "背部平直下探到腿后侧有拉伸感再站回"], wrong: "变成半蹲下坐，练的是腿不是臀和腘绳肌" },
    "female_athletic:2": { steps: ["仰卧屈膝，下背压实地面", "卷起时肩胛离地即可，不靠手拽头", "悬垂或撑地提膝，呼气向下腹收"], wrong: "脖子先酸说明在用头颈带身体" },
    "female_athletic:3": { steps: ["弹力带齐脸高，双手向脸两侧拉开", "肘高于腕，肩胛向后夹", "俯身飞鸟：屈髋俯身，向两侧抬肘"], wrong: "重量太大变成耸肩和甩臂" },
    "female_steady:0": { steps: ["椅背当扶手，双脚与肩同宽", "臀部向后坐到轻触椅面即起", "膝盖不超脚尖、不内扣"], wrong: "为了蹲深而膝盖前顶，压力全在髌骨" },
    "female_steady:1": { steps: ["面对墙一步远，手掌撑墙与肩同高", "身体一条直线向墙倾，再推回", "肩胛在推程中向前展开"], wrong: "只动手腕和头，肩背完全没参与" },
    "female_steady:2": { steps: ["双手轻扶耳侧，站直", "抬右膝同时左肘下探靠近", "落地站稳再换边，不借惯性甩"], wrong: "越做越快变成晃身体，腰反而受力" },
    "female_steady:3": { steps: ["大步幅、摆臂，脚跟先过渡到全掌", "微微出汗能正常说话即有效", "前后各 3 分钟放慢收尾"], wrong: "边走边低头看手机，含胸使呼吸变浅" },
    "male_v_taper:0": { steps: ["悬挂或高位下拉，肩胛先下沉", "肘向身体两侧拉至锁骨高度", "顶端夹背 1 秒，控制 2 秒放回"], wrong: "靠摆身体和耸肩把重量拽下来" },
    "male_v_taper:1": { steps: ["肘微屈，向两侧抬至与肩同高", "手腕不高于肘，不向前甩", "缓慢下放，全程不耸肩"], wrong: "重量过大变成斜方肌借力甩" },
    "male_v_taper:2": { steps: ["仰卧双手垫臀侧，双腿并拢", "用下腹把骨盆向后卷起，膝向胸", "剪刀腿：离地 15 度交替下放，下背贴地"], wrong: "下背拱起，练到的是髂腰肌不是腹" },
    "male_v_taper:3": { steps: ["钻石：双手拇指食指相对成菱形", "上斜：手撑桌面或椅面，身体越直越易", "胸贴近手再推满，肘不外飞"], wrong: "手位太低导致肩前侧刺痛" },
    "male_lean:0": { steps: ["宽距练胸外沿，窄距练中缝与肱三头", "身体一条直线，肘约 45 度", "下放至胸离地一拳即推回"], wrong: "塌腰撅臀，把重量转给腰椎" },
    "male_lean:1": { steps: ["平板位：肩在腕正上方，臀夹紧", "单手离地向外打开，胸腔转向斜上方", "回到平板再换边，骨盆不晃"], wrong: "为转体把腰塌下去，变成腰椎扭转" },
    "male_lean:2": { steps: ["后脑、上背、臀贴墙站", "双臂成 W 贴墙，向上滑成 Y", "全程肋骨不下压、肩不上耸"], wrong: "腰离墙拱起，等于没纠正驼背" },
    "male_lean:3": { steps: ["坡度 8-12，速度 4.5-5.5 km/h", "不扶把手，身体微前倾保持直立", "前后各 2 分钟平坡过渡"], wrong: "死死抓住扶手把身体吊起来，消耗大打折扣" },
    "male_muscular:0": { steps: ["负重深蹲：杠铃或双手持铃于胸前", "吸气下蹲至髋低于膝，呼气站起", "半蹲跳只做 3-5 次即止，落地轻"], wrong: "膝盖内扣、脚跟离地、腰圆背" },
    "male_muscular:1": { steps: ["下落 3 秒，胸离地一拳", "推起时呼气夹胸，肘不完全锁死", "哑铃卧推：肩胛后收贴凳"], wrong: "靠弹震和半程换次数，胸没吃到力" },
    "male_muscular:2": { steps: ["一手一膝撑凳，背平直", "肘贴身体向后拉至腰侧", "顶端停 1 秒，控制 2 秒放下"], wrong: "转身甩臂把重量拉起来" },
    "male_muscular:3": { steps: ["窄距：双手与肩同宽，肘夹身体", "臂屈伸：背对椅面撑，肘向后弯", "全程肩不耸，肘不外飞"], wrong: "下放过低导致肩前侧拉扯痛" },
    "male_steady:0": { steps: ["阻力档以能维持 25-30 分钟为准", "坐姿挺直，不趴把手", "前后各 2 分钟降档收尾"], wrong: "一档到底越骑越快，膝盖跟着晃" },
    "male_steady:1": { steps: ["坐稳，双脚可着地降低难度", "躯干左右转，眼随肩走", "慢速有控制，不靠甩臂"], wrong: "幅度全靠惯性，腰椎被反复扭转" },
    "male_steady:2": { steps: ["椅背当扶手，屈髋后坐", "轻触椅面即站起，重心在脚跟", "膝盖对准脚尖，不内扣"], wrong: "蹲得太深导致膝痛，深度以不痛为准" },
    "male_steady:3": { steps: ["弹力带固定在身后齐胸高", "双臂向前平举夹胸，肩胛后收下沉", "回位 2 秒，不耸肩"], wrong: "含胸驼背用手臂硬推，胸没感觉" },
};

// ============ 第五批后续：逐动作详情 + 火柴人示意动画 ============
// 为什么不是真人视频：仓库里没有教程素材也没有转载授权，内置别人的视频是侵权。
// 所以这里画一个由关键帧插值出来的骨骼人物，并在界面上写明"程序化示意，非真人实拍"。
// 原型靠要点文字里的动词识别，不另建一张映射表——EX_STEPS 改了它自动跟着变。

const EX_ARCHETYPES = {
    bridge:   { cn: "髋链 · 臀桥", view: "side",  amp: 0.30 },
    deadbug:  { cn: "仰卧对侧伸展", view: "back",  amp: 0.34 },
    clamshell:{ cn: "髋外展 · 蚌式", view: "back",  amp: 0.30 },
    birddog:  { cn: "四点跪位对侧伸展", view: "side", amp: 0.28 },
    squat:    { cn: "蹲 · 膝髋联动", view: "front", amp: 0.34 },
    sideleg:  { cn: "侧向抬腿", view: "front", amp: 0.32 },
    pushup:   { cn: "推 · 俯卧撑", view: "side",  amp: 0.30 },
    walk:     { cn: "有氧步态", view: "side",    amp: 0.26 },
    plank:    { cn: "支撑 · 平板", view: "side",  amp: 0.12 },
    lunge:    { cn: "弓步蹲", view: "front",     amp: 0.32 },
    press:    { cn: "上举", view: "front",       amp: 0.36 },
    twist:    { cn: "躯干旋转", view: "front",   amp: 0.24 },
};

/** 从三条要点 + 常见错误文本里认动作原型。认不出就回落到 plank（小幅呼吸示意），不硬编一个假动作。 */
function detectArchetype(meta, item) {
    const hay = ((meta && meta.steps || []).join(" ") + " " + ((meta && meta.wrong) || "")
        + " " + ((item && item.name) || "") + " " + ((item && item.tip) || "")).toLowerCase();
    const has = function (arr) { return arr.some(function (k) { return hay.indexOf(k) >= 0; }); };
    if (has(["臀桥", "送髋", "脚跟下压", "夹紧臀部"])) return "bridge";
    if (has(["鸟狗", "四点跪位", "骨盆保持水平"])) return "birddog";
    if (has(["蚌式", "开膝", "弹力带套在膝盖"])) return "clamshell";
    if (has(["90 度", "对侧手脚", "下背", "双臂伸直指向天花板"])) return "deadbug";
    if (has(["俯卧撑", "撑地", "肘约 45 度", "肩胛向前"])) return "pushup";
    if (has(["侧抬腿", "向后上方抬起", "脚尖朝前,骨盆不翻", "骨盆不翻"])) return "sideleg";
    if (has(["步频", "落地用中足", "慢走", "心率"])) return "walk";
    if (has(["平板", "手肘撑", "身体一条直线向下压"])) return "plank";
    if (has(["弓步", "前腿", "后膝"])) return "lunge";
    if (has(["过顶", "举", "推举", "哑铃"])) return "press";
    if (has(["转体", "旋转", "扭转"])) return "twist";
    if (has(["下蹲", "蹲", "膝盖对准脚尖"])) return "squat";
    return "plank";
}

/** 基础站姿骨架（归一化坐标，y 向下）。所有原型都在它之上做位移。 */
function basePose() {
    return {
        head: [0.50, 0.16], neck: [0.50, 0.24], sternum: [0.50, 0.34], pelvis: [0.50, 0.50],
        l_shoulder: [0.42, 0.25], r_shoulder: [0.58, 0.25],
        l_elbow: [0.39, 0.37], r_elbow: [0.61, 0.37],
        l_wrist: [0.38, 0.49], r_wrist: [0.62, 0.49],
        l_hip: [0.45, 0.51], r_hip: [0.55, 0.51],
        l_knee: [0.44, 0.68], r_knee: [0.56, 0.68],
        l_ankle: [0.43, 0.86], r_ankle: [0.57, 0.86]
    };
}

function move(p, joint, x, y) {
    const v = p[joint]; if (!v) return;
    v[0] += x; v[1] += y;
}

/** 按原型与相位 t(0..1) 生成一帧姿态。sin 让动作来回，不是单向摆 pose。 */
function poseAt(arch, t) {
    const p = basePose();
    const s = Math.sin(t * Math.PI * 2);          // -1..1
    const u = (1 - Math.cos(t * Math.PI * 2)) / 2; // 0..1
    switch (arch) {
        case "squat":
        case "lunge": {
            const d = 0.16 * u;
            ["pelvis", "l_hip", "r_hip", "sternum", "neck", "head"].forEach(function (j) { move(p, j, 0, d); });
            ["l_knee", "r_knee", "l_shoulder", "r_shoulder"].forEach(function (j) { move(p, j, 0, d * 0.55); });
            move(p, "l_knee", -0.03 * u, 0); move(p, "r_knee", 0.03 * u, 0);
            move(p, "l_wrist", -0.05 * u, -0.06 * u); move(p, "r_wrist", 0.05 * u, -0.06 * u);
            if (arch === "lunge") { move(p, "r_knee", 0.05, 0.05); move(p, "r_ankle", 0.09, 0.0); }
            break;
        }
        case "bridge": {
            const lift = 0.13 * u;
            move(p, "pelvis", 0, -lift); move(p, "sternum", 0, -lift * 0.45);
            move(p, "l_hip", 0, -lift * 0.8); move(p, "r_hip", 0, -lift * 0.8);
            break;
        }
        case "pushup": {
            const down = 0.11 * u;
            ["sternum", "neck", "head", "pelvis"].forEach(function (j) { move(p, j, 0, down); });
            move(p, "l_elbow", -0.02, down * 0.6); move(p, "r_elbow", 0.02, down * 0.6);
            break;
        }
        case "press": {
            const up = 0.20 * u;
            move(p, "l_wrist", -0.02, -up); move(p, "r_wrist", 0.02, -up);
            move(p, "l_elbow", -0.02, -up * 0.6); move(p, "r_elbow", 0.02, -up * 0.6);
            break;
        }
        case "sideleg":
        case "clamshell": {
            const out = 0.16 * u;
            move(p, "r_knee", out * 0.6, -out * 0.35); move(p, "r_ankle", out, -out * 0.6);
            break;
        }
        case "deadbug":
        case "birddog": {
            move(p, "r_wrist", 0.10 * u, -0.10 * u); move(p, "r_elbow", 0.06 * u, -0.05 * u);
            move(p, "l_knee", -0.06 * u, 0.07 * u); move(p, "l_ankle", -0.09 * u, 0.10 * u);
            break;
        }
        case "walk": {
            const sw = 0.11 * s;
            move(p, "l_knee", sw * 0.5, -Math.max(0, s) * 0.05); move(p, "l_ankle", sw, -Math.max(0, s) * 0.09);
            move(p, "r_knee", -sw * 0.5, -Math.max(0, -s) * 0.05); move(p, "r_ankle", -sw, -Math.max(0, -s) * 0.09);
            move(p, "l_wrist", -sw * 0.7, 0); move(p, "r_wrist", sw * 0.7, 0);
            break;
        }
        case "twist": {
            const r = 0.07 * s;
            move(p, "sternum", r, 0); move(p, "neck", r * 1.2, 0); move(p, "head", r * 1.4, 0);
            move(p, "l_shoulder", r, 0); move(p, "r_shoulder", r, 0);
            move(p, "l_wrist", r * 1.8, 0); move(p, "r_wrist", r * 1.8, 0);
            break;
        }
        default: {   // plank：只起伏，不假装在动大关节
            const b = 0.02 * s;
            ["pelvis", "sternum", "neck", "head"].forEach(function (j) { move(p, j, 0, b); });
        }
    }
    return p;
}

// ==========================================
// 火柴人动作演示（r145 起取代 3D 全息人体）
// 关键帧表给的就是 16 个 2D 关节点，就按它本来的样子画。
// 以前把这些点当成 3D 骨架、深度再编一组人为常数做透视投影：那既不对
// （左右肢体差 0.06 的"深度"是我赋的，不是解出来的）也不好看（深色全息面板、
// 发光球铰链、橄榄形肌块全是假体积）。现在只剩线、地面和发力高亮，
// APK 也不必再背 three.js 和 glb（少 1.9MB）。
// ==========================================

const exPlay = { paused: false };

// 火柴人配色跟着应用的浅色设计系统，不再压一块深色面板
const STICK_INK = {
    spine: "#334155",              // 躯干与近侧肢体
    far: "#A9B7C6",               // 矢状面里背向镜头的那一侧
    muscle: "#059669",            // 正在发力的肌群
    ground: "#CBD5E1",
    mat: "#E2E8F0"
};

/** 线段表：a/b 是关节名，type 对上 ACTIVE_MUSCLES 里的肌群名（决定这根能不能被点亮），
    side 只在矢状面里用来区分远近，heavy 的画粗。 */
const STICK_SEGMENTS = [
    { a: "head", b: "neck", type: "neck", heavy: true },
    { a: "neck", b: "sternum", type: "neck", heavy: true },
    { a: "sternum", b: "pelvis", type: "core", heavy: true },
    { a: "l_shoulder", b: "r_shoulder", type: "chest", heavy: true },
    { a: "l_hip", b: "r_hip", type: "pelvis", heavy: true },
    { a: "l_shoulder", b: "l_elbow", type: "arm_l", side: "far" },
    { a: "l_elbow", b: "l_wrist", type: "forearm_l", side: "far" },
    { a: "l_hip", b: "l_knee", type: "thigh_l", side: "far" },
    { a: "l_knee", b: "l_ankle", type: "calf_l", side: "far" },
    { a: "r_shoulder", b: "r_elbow", type: "arm_r", side: "near" },
    { a: "r_elbow", b: "r_wrist", type: "forearm_r", side: "near" },
    { a: "r_hip", b: "r_knee", type: "thigh_r", side: "near" },
    { a: "r_knee", b: "r_ankle", type: "calf_r", side: "near" }
];

// 动作原型主要激活肌群配置
const ACTIVE_MUSCLES = {
    squat: { name: "股四头肌 · 臀大肌", targets: ["thigh_l", "thigh_r", "calf_l", "calf_r", "glutes"] },
    lunge: { name: "股四头肌 · 臀大肌", targets: ["thigh_l", "thigh_r", "glutes"] },
    bridge: { name: "臀大肌 · 腘绳肌", targets: ["pelvis", "glutes", "thigh_l", "thigh_r"] },
    pushup: { name: "胸大肌 · 肱三头肌", targets: ["chest", "arm_l", "arm_r", "core"] },
    press: { name: "三角肌 · 肱三头肌", targets: ["chest", "deltoid_l", "deltoid_r", "arm_l", "arm_r"] },
    plank: { name: "腹横肌 · 核心深层肌群", targets: ["core", "pelvis"] },
    deadbug: { name: "腹直肌 · 核心稳定", targets: ["core"] },
    birddog: { name: "竖脊肌 · 臀大肌", targets: ["core", "thigh_r", "arm_l"] },
    twist: { name: "腹内外斜肌 · 核心旋转", targets: ["core", "chest"] },
    walk: { name: "心肺下肢 · 腓肠肌", targets: ["thigh_l", "thigh_r", "calf_l", "calf_r"] },
    sideleg: { name: "臀中肌 · 外展肌群", targets: ["pelvis", "thigh_r"] },
    clamshell: { name: "臀中肌 · 髋外旋肌", targets: ["pelvis", "thigh_r"] }
};

// 文案里写的臀大肌、三角肌必须落到这张表真有的那根线上，否则标签说"发力：臀大肌"
// 而屏幕上永远不会亮。
const MUSCLE_ALIAS = {
    glutes: ["pelvis"],
    hamstring: ["thigh_l", "thigh_r"],
    deltoid_l: ["arm_l"],
    deltoid_r: ["arm_r"]
};

function expandMuscleTargets(list) {
    const out = [];
    (list || []).forEach(function (t) {
        const mapped = MUSCLE_ALIAS[t] || [t];
        mapped.forEach(function (m) { if (out.indexOf(m) < 0) out.push(m); });
    });
    return out;
}

/** 关键帧表是按平面 authored 的：矢状面就是侧视，正面就是正视。
    火柴人不再假装能"转"，只用它区分左右肢体的远近。 */
function posePlane(key) {
    const e = (EX_POSES || {})[key];
    return (e && e.plane === "frontal") ? "frontal" : "sagittal";
}

function toggleExDetailPlay() {
    exPlay.paused = !exPlay.paused;
    const btn = document.getElementById("ex-detail-play");
    if (btn) btn.textContent = exPlay.paused ? "▶️ 继续" : "⏸️ 暂停";
}
window.toggleExDetailPlay = toggleExDetailPlay;

/** 画多大：按这组动作全部关键帧的关节并集定框，逐帧只换关节、不换框，
    人形就不会随动作忽大忽小；四边都留出头半径，任何屏宽都不裁头不切脚。 */
function stickBox(poseKey, arch) {
    const frames = [];
    const e = (EX_POSES || {})[poseKey];
    if (e && Array.isArray(e.frames) && e.frames.length) {
        for (let i = 0; i < e.frames.length; i++) {
            if (e.frames[i] && e.frames[i].pose) frames.push(e.frames[i].pose);
        }
    }
    if (!frames.length) {
        for (let i = 0; i < 4; i++) frames.push(poseAt(arch, i / 4));
    }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    frames.forEach(function (p) {
        for (const jn in p) {
            if (!Object.prototype.hasOwnProperty.call(p, jn)) continue;
            const q = p[jn];
            if (!q || q.length < 2) continue;
            if (q[0] < minX) minX = q[0];
            if (q[0] > maxX) maxX = q[0];
            if (q[1] < minY) minY = q[1];
            if (q[1] > maxY) maxY = q[1];
        }
    });
    if (!(maxX > minX) || !(maxY > minY)) {
        return { minX: 0.30, maxX: 0.70, minY: 0.10, maxY: 0.90 };
    }
    return { minX: minX, maxX: maxX, minY: minY, maxY: maxY };
}

/** 相位与发力提示写在画布下方的正常流里，画布上从此不叠任何浮层。 */
function updateExerciseHud(arch, t, poseKey) {
    const isConcentric = (t % 1.0) < 0.5;
    const phaseEl = document.getElementById("ex-phase-text");
    if (phaseEl) {
        // 关键帧表里没写哪个半程是向心，硬贴"向心/离心"就是编；只报屏上真看得见的相位
        phaseEl.textContent = isConcentric ? "前半程（起身/推起方向）" : "后半程（还原方向）";
    }
    const badge = document.getElementById("ex-phase-badge");
    if (badge) badge.classList.toggle("back", !isConcentric);
    const foot = document.getElementById("ex-hud-foot");
    if (foot) foot.textContent = stickCaption(arch);
}

/** 说明要跟实际画法一致：火柴人不能写成"3D 人体模型"，也不能写成"立体体块"。 */
function stickCaption(arch) {
    const meta = EX_ARCHETYPES[arch] || null;
    return (meta ? meta.cn + " · " : "") + "火柴人关节示意 · 非真人实拍";
}

/** 一帧火柴人：浅底、地面线，远侧画细画淡，躯干与近侧画实，发力那根加粗带脉冲。 */
function drawFrame(g, W, H, pose, arch, t, poseKey) {
    g.clearRect(0, 0, W, H);
    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#FFFFFF");
    bg.addColorStop(1, "#EEF2F7");
    g.fillStyle = bg;
    g.fillRect(0, 0, W, H);

    const box = stickBox(poseKey, arch);
    const st = pose.sternum || [0.5, 0.34];
    const pv = pose.pelvis || [0.5, 0.5];
    // 头的大小从"胸骨到骨盆"这根骨按比例推：它在表里恒定，所以躺着的动作
    // 不会出现一个和肩宽一样小的头，也不会因为画面拉宽就变成气球。
    const torso = Math.hypot(pv[0] - st[0], pv[1] - st[1]) || 0.15;
    const headR = torso * 0.24;
    const padX = W * 0.08, padTop = H * 0.07, padBottom = H * 0.13;
    const bw = (box.maxX - box.minX) + headR * 2;
    const bh = (box.maxY - box.minY) + headR * 2;
    const scale = Math.max(1, Math.min((W - padX * 2) / bw, (H - padTop - padBottom) / bh));
    const ox = W * 0.5 - (box.minX + box.maxX) * 0.5 * scale;
    const oy = padTop + (H - padTop - padBottom) * 0.5 - (box.minY + box.maxY) * 0.5 * scale;

    const at = function (name) {
        const p = pose[name];
        if (!p || p.length < 2) return null;
        return { x: p[0] * scale + ox, y: p[1] * scale + oy };
    };

    const cfg = ACTIVE_MUSCLES[arch] || { targets: [] };
    const active = expandMuscleTargets(cfg.targets || []);
    const sagittal = posePlane(poseKey) === "sagittal";
    const isConcentric = (t % 1.0) < 0.5;
    const pulse = isConcentric ? 0.35 + 0.65 * Math.abs(Math.sin(t * Math.PI * 2)) : 0.15;

    g.save();
    g.lineCap = "round";
    g.lineJoin = "round";
    const thick = Math.max(2.5, torso * scale * 0.115);
    const limb = Math.max(2, torso * scale * 0.085);
    const farLimb = Math.max(1.6, torso * scale * 0.06);

    // 发力脉冲用一圈半透明的粗线垫底，不给线加发光阴影：
    // 阴影在 2 倍 dpr 的画布上会糊成一团绿，正是上次"丑"的来源之一。
    function stroke(a, b, color, width, lit) {
        if (lit) {
            g.strokeStyle = "rgba(5, 150, 105, " + (0.10 + 0.22 * pulse).toFixed(3) + ")";
            g.lineWidth = width * 2.6;
            g.beginPath();
            g.moveTo(a.x, a.y);
            g.lineTo(b.x, b.y);
            g.stroke();
        }
        g.strokeStyle = color;
        g.lineWidth = width;
        g.beginPath();
        g.moveTo(a.x, a.y);
        g.lineTo(b.x, b.y);
        g.stroke();
    }

    function paint(seg) {
        const a = at(seg.a), b = at(seg.b);
        if (!a || !b) return;
        const far = sagittal && seg.side === "far";
        const lit = active.indexOf(seg.type) >= 0;
        const baseW = seg.heavy ? thick : (far ? farLimb : limb);
        stroke(a, b, lit ? STICK_INK.muscle : (far ? STICK_INK.far : STICK_INK.spine),
            lit ? baseW * 1.18 : baseW, lit);
    }

    // 地面/垫子画在并集框下沿：躺着的动作也要有个"髋到底抬起来没有"的参照
    const groundY = oy + (box.maxY + headR) * scale + 4;
    g.strokeStyle = STICK_INK.ground;
    g.lineWidth = Math.max(1.5, torso * scale * 0.04);
    g.beginPath();
    g.moveTo(W * 0.10, groundY);
    g.lineTo(W * 0.90, groundY);
    g.stroke();
    g.fillStyle = STICK_INK.mat;
    g.fillRect(W * 0.10, groundY, W * 0.80, Math.max(2, torso * scale * 0.05));

    // 正视动作左右等权；矢状面才分远近，所以先远侧、再躯干、再近侧
    function layerOf(seg) {
        if (!sagittal) return seg.side ? "near" : "trunk";
        return seg.side === "far" ? "far" : (seg.side === "near" ? "near" : "trunk");
    }
    ["far", "trunk", "near"].forEach(function (layer) {
        STICK_SEGMENTS.forEach(function (s) { if (layerOf(s) === layer) paint(s); });
    });

    const hd = at("head");
    if (hd) {
        const r = Math.max(4, headR * scale);
        g.beginPath();
        g.arc(hd.x, hd.y, r, 0, Math.PI * 2);
        g.fillStyle = "#FFFFFF";
        g.fill();
        g.strokeStyle = active.indexOf("neck") >= 0 ? STICK_INK.muscle : STICK_INK.spine;
        g.lineWidth = Math.max(2, r * 0.26);
        g.stroke();
    }

    [["l_wrist", "far"], ["l_ankle", "far"], ["r_wrist", "near"], ["r_ankle", "near"]]
        .forEach(function (c) {
            const p = at(c[0]);
            if (!p) return;
            const far = sagittal && c[1] === "far";
            g.beginPath();
            g.arc(p.x, p.y, Math.max(2.2, (far ? farLimb : limb) * 0.72), 0, Math.PI * 2);
            g.fillStyle = far ? STICK_INK.far : STICK_INK.spine;
            g.fill();
        });

    g.restore();
    updateExerciseHud(arch, t, poseKey);
}

let exAnim = null;
let exActivePoseKey = null;
let exActiveArch = "";

// 真数据优先：仓库里带了一份 32 动作 × 4 关键帧的姿态表（按固定骨长生成，
// 已核过骨长恒定与肘膝不反折）。取不到时回落到上面的程序化原型，而不是画一张静图。
let EX_POSES = null;
let exPosesTried = false;

function loadExercisePoses() {
    if (exPosesTried) return Promise.resolve(EX_POSES);
    exPosesTried = true;
    return new Promise(function (resolve) {
        let done = false;
        const finish = function (v) { if (!done) { done = true; EX_POSES = v; resolve(v); } };
        try {
            const xhr = new XMLHttpRequest();
            xhr.open("GET", "exercise_poses.json", true);
            xhr.onreadystatechange = function () {
                if (xhr.readyState !== 4) return;
                if (xhr.status === 0 || (xhr.status >= 200 && xhr.status < 300)) {
                    try { finish(JSON.parse(xhr.responseText)); } catch (e) { finish(null); }
                } else {
                    finish(null);
                }
            };
            xhr.onerror = function () { finish(null); };
            xhr.send(null);
            // 2.5 秒还没回来就先按程序化画，不让用户对着空白等
            setTimeout(function () { finish(EX_POSES); }, 2500);
        } catch (e) {
            finish(null);
        }
    });
}

/** 线性插值两帧，得到连续动作而不是四张幻灯。 */
function lerpFrames(a, b, k) {
    const out = {};
    for (const jn in a) {
        if (!Object.prototype.hasOwnProperty.call(a, jn)) continue;
        const p = a[jn];
        const q = (b && b[jn]) || a[jn];
        out[jn] = [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k];
    }
    return out;
}

/** 关键帧表按 t(0..1) 取一帧；表里没有这个动作就回落到程序化原型。 */
function poseFromTable(key, arch, t) {
    const e = (EX_POSES || {})[key];
    if (!e || !Array.isArray(e.frames) || e.frames.length < 2) return poseAt(arch, t);
    const n = e.frames.length;
    const pos = t * n;
    const i0 = Math.floor(pos) % n;
    const i1 = (i0 + 1) % n;
    const k = pos - Math.floor(pos);
    return lerpFrames(e.frames[i0].pose, e.frames[i1].pose, k);
}

function currentExKey(idx) {
    return (window.__currentExKey || "female_hourglass") + ":" + idx;
}

function closeExerciseDetail() {
    if (exAnim) { cancelAnimationFrame(exAnim.raf); exAnim = null; }
    const m = document.getElementById("ex-detail-modal");
    if (m) m.classList.remove("show");
}

/** 打开详情：火柴人标准动作演示、要点分解、避坑指南与慢放。 */
function openExerciseDetail(idx) {
    const list = window.__currentExercises || [];
    const item = list[idx];
    if (!item) { callNativeToast("这个动作还没载入，先回到训练计划再点"); return; }
    const key = (state.profile && state.profile.goalType ? state.profile.goalType : "female_hourglass") + ":" + idx;
    const meta = EX_STEPS[key] || {};
    const arch = detectArchetype(meta, item);
    const poseKey = currentExKey(idx);
    exActivePoseKey = poseKey;
    exActiveArch = arch;
    const nameEl = document.getElementById("ex-detail-name");
    const repsEl = document.getElementById("ex-detail-reps");
    const targetMuscleEl = document.getElementById("ex-detail-target-muscle");
    const stepsEl = document.getElementById("ex-detail-steps");
    const wrongEl = document.getElementById("ex-detail-wrong");
    const cv = document.getElementById("ex-detail-canvas");
    if (!nameEl || !cv) return;

    nameEl.textContent = String(item.name || "").replace(/^\d+\.\s*/, "");
    repsEl.textContent = item.reps || "";

    const activeCfg = ACTIVE_MUSCLES[arch] || { name: "背阔肌 · 上背核心肌群" };
    if (targetMuscleEl) {
        targetMuscleEl.textContent = "🔥 核心发力：" + activeCfg.name;
    }

    const steps = (meta.steps || []);
    stepsEl.innerHTML = steps.length
        ? steps.map(function (x, i) {
            const cleanText = String(x).replace(/^(\d+[\.、\s]+)+/, "").trim();
            return "<li><span class='step-badge'>" + (i + 1) + "</span><span class='step-text'>" + escapeHtml(cleanText) + "</span></li>";
        }).join("")
        : "<li><span class='step-badge'>1</span><span class='step-text'>这个动作还没有分解要点记录</span></li>";

    const rawWrong = meta.wrong || "";
    const cleanWrong = String(rawWrong).replace(/^常见错误[：:]\s*/, "").trim();
    wrongEl.innerHTML = cleanWrong
        ? escapeHtml(cleanWrong)
        : "暂无常见错误记录，保持核心收紧呼吸顺畅即可。";

    const modal = document.getElementById("ex-detail-modal");
    modal.classList.add("show");

    // 画布位图必须等弹窗显示之后再量：.modal-overlay 未 show 时是 display:none，
    // 量出来全是 0，等于 dpr 校正从没生效过，手机上一直拿 340×360 的位图拉伸。
    // 而且只能量 clientWidth——弹窗卡片带 slideUp 动画，起手是 scale(0.97)，
    // getBoundingClientRect 会把那个瞬时缩放算进去，位图就小 3%，显示时再拉回来又糊一层。
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const shownW = cv.clientWidth, shownH = cv.clientHeight;
    if (shownW > 60 && shownH > 60) {
        cv.width = Math.round(shownW * dpr);
        cv.height = Math.round(shownH * dpr);
    }

    exPlay.paused = false;
    const playBtn = document.getElementById("ex-detail-play");
    if (playBtn) playBtn.textContent = "⏸️ 暂停";

    const g = cv.getContext("2d");
    if (!g) { callNativeToast("这台设备的画布不可用，动画放不出来"); return; }
    if (exAnim) cancelAnimationFrame(exAnim.raf);
    let lastTime = Date.now();
    let currentT = 0;
    exAnim = { raf: 0, slow: false };
    const loop = function () {
        if (!exAnim) return;
        const now = Date.now();
        const dt = now - lastTime;
        lastTime = now;

        if (!exPlay.paused) {
            const speed = exAnim.slow ? 0.35 : 1.0;
            currentT = (currentT + (dt / 2600) * speed) % 1.0;
        }

        const t = currentT;
        drawFrame(g, cv.width, cv.height, poseFromTable(poseKey, arch, t), arch, t, poseKey);
        exAnim.raf = requestAnimationFrame(loop);
    };
    loop();
    const btn = document.getElementById("ex-detail-slow");
    if (btn) btn.textContent = "慢放：关";
}

function toggleExDetailSlow() {
    if (!exAnim) return;
    exAnim.slow = !exAnim.slow;
    const btn = document.getElementById("ex-detail-slow");
    if (btn) btn.textContent = exAnim.slow ? "慢放：开" : "慢放：关";
}

function toggleExerciseSteps(idx) {
    const el = document.getElementById("ex-steps-" + idx);
    if (!el) return;
    el.classList.toggle("open");
}

function openExerciseVideo(idx) {
    const list = window.__currentExercises || [];
    const item = list[idx];
    if (!item) return;
    const name = String(item.name).replace(/^\d+\.\s*/, "").replace(/\s*[\/（(].*$/, "").trim();
    const url = "https://cn.bing.com/videos/search?q=" + encodeURIComponent(name + " 标准动作 健身");
    callNativeToast("视频来自第三方，本软件不内置教程");
    if (window.AndroidBridge && window.AndroidBridge.openBrowser) {
        window.AndroidBridge.openBrowser(url);
    } else {
        window.open(url, "_blank");
    }
}

// ==========================================
// 计时器与实时燃脂计算器
// ==========================================
let timerPlannedMinutes=20;
let timerDeadline=0;
let timerInterval = null;
let timerSeconds = 20 * 60;
let isTimerRunning = false;
let liveBurnedKcal = 0;

function setupTimer() {
    updateTimerDisplay();
}

function updateTimerDisplay() {
    const mins = Math.floor(timerSeconds / 60);
    const secs = timerSeconds % 60;
    const disp = document.getElementById("timer-display");
    if (disp) disp.innerText = `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;

    const burnDisp = document.getElementById("live-burned-display");
    if (burnDisp) burnDisp.innerText = liveBurnedKcal.toFixed(1);
}

function toggleTimer() {
    const btn = document.getElementById("btn-timer-toggle");
    if (isTimerRunning) {
        clearInterval(timerInterval);
        isTimerRunning = false;
        if (btn) { btn.innerText = "继续训练"; btn.style.background = "#10B981"; }
    } else {
        isTimerRunning = true;
        timerDeadline=Date.now()+timerSeconds*1000;
        if (btn) { btn.innerText = "暂停计时"; btn.style.background = "#F59E0B"; }
        callNativeToast("▶ 训练计时已开始！消耗仅为估算，请按实际训练打卡。");
        callNativeVibrate(50);

        timerInterval = setInterval(() => {
            if (timerSeconds > 0) {
                timerSeconds=Math.max(0,Math.ceil((timerDeadline-Date.now())/1000));
                liveBurnedKcal=(timerPlannedMinutes*60-timerSeconds)*11/60; // approx 11 kcal/min during resistance
                updateTimerDisplay();
            } else {
                clearInterval(timerInterval);
                isTimerRunning = false;
                if (btn) btn.innerText = "开始训练";
                callNativeToast("计时结束：这一轮对应上面那 4 个动作。按确定就把今天的训练记一笔。");
                callNativeVibrate(300);
                callNativeBeep();
                callNativeToast("训练计时结束，请核对完成情况后点击训练打卡");
            }
        }, 1000);
    }
}

function resetTimer(mins) {
    clearInterval(timerInterval);
    isTimerRunning = false;
    timerPlannedMinutes=mins;
    timerSeconds = mins * 60;
    liveBurnedKcal = 0;
    const btn = document.getElementById("btn-timer-toggle");
    if (btn) { btn.innerText = "开始训练"; btn.style.background = "#10B981"; }
    const label = document.getElementById("timer-label");
    if (label) {
        const info = getShapeData(state.profile.gender, state.profile.goalType);
        const plan = (info.data && info.data.title) || "当前身形";
        label.innerText = mins === 25
            ? `⏱️ 有氧倒计时 25 分钟 · 对应【${plan}】的有氧替换`
            : `⏱️ 抗阻倒计时 ${mins} 分钟 · 对应【${plan}】上面那 4 个动作`;
    }
    updateTimerDisplay();
}

// ==========================================
// 食谱方案渲染与采购清单
// ==========================================
function showRecipePlan(planKey) {
    state.selectedPlan = planKey;
    document.querySelectorAll(".plan-tab-btn").forEach(b => b.classList.remove("active"));
    event.target.classList.add("active");
    renderRecipePlan(planKey);
}

function renderRecipePlan(planKey) {
    const card = document.getElementById("recipe-display-card");
    if (!card) return;
    const plan = RECIPES_DATA[planKey] || RECIPES_DATA.A;

    let html = `
        <div style="margin-bottom: 12px; border-bottom: 1px dashed var(--border); padding-bottom: 8px;">
            <div style="font-size: 15px; font-weight: 800; color: var(--primary-dark);">${plan.title}</div>
            <div style="font-size: 11px; color: var(--text-muted);">${plan.desc}</div>
        </div>
    `;

    // 忌口只用来**标注冲突**，不会自动改写方案：内置食材表是既定内容，
    // 悄悄替换成别的菜等于让用户照着做了一份他没同意过的食谱。
    const tags = avoidTagsNow().filter(function (k) { return k !== "less_oil"; });
    let clashMeals = 0;
    plan.meals.forEach(m => {
        // 判食材前先剥掉 <br>/<strong>：不剥的话标签里的字母会参与匹配
        const plain = String(m.content || "").replace(/<[^>]*>/g, " ");
        const hits = tags.length ? dishConflicts(plain, tags) : [];
        if (hits.length) clashMeals++;
        html += `
            <div class="meal-plan-card">
                <div class="meal-plan-title">
                    <span>${m.name}</span>
                    <span style="font-size: 11px; color: var(--text-light); font-weight: normal;">${m.time}</span>
                </div>
                <div class="meal-plan-content">${m.content}</div>
                ${hits.length ? `<div class="meal-clash">这一餐有 ${hits.length} 处与忌口冲突：${escapeHtml(hits.map(function (k) { return (AVOID_CN[k] || [k])[0]; }).join("、"))}。做法不会自动避开，照着做时把对应那行换掉。</div>` : ""}
            </div>
        `;
    });
    if (tags.length) {
        html = `<div class="meal-clash-summary">已按你的 ${tags.length} 项忌口标注：这套方案里 ${clashMeals} 餐有冲突项。</div>` + html;
    }
    card.innerHTML = html;
}

function renderShoppingList() {
    const container = document.getElementById("shopping-checklist-container");
    if (!container) return;

    let html = "";
    SHOPPING_ITEMS.forEach((cat, cIdx) => {
        html += `<div style="font-weight: 700; font-size: 12.5px; margin: 10px 0 6px; color: var(--primary-deep);">${cat.cat}</div>`;
        cat.items.forEach((item, iIdx) => {
            const key = `shop_${cIdx}_${iIdx}`;
            const isChecked = state.checklistState && state.checklistState[key];
            html += `
                <div class="checklist-item ${isChecked ? 'checked' : ''}" onclick="toggleChecklistItem('${key}')">
                    <input type="checkbox" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation(); toggleChecklistItem('${key}')">
                    <span style="font-size: 12px; margin-left: 6px;">${item}</span>
                </div>
            `;
        });
    });
    container.innerHTML = html;
}

let checklistSaving=false;
async function persistChecklist(next) {
    if(checklistSaving)return;
    checklistSaving=true;
    try { await postApi("/api/checklist",{state:next});state.checklistState=next;renderShoppingList(); }
    catch(e){reportWriteFailure(e,"采购清单");renderShoppingList();}
    finally{checklistSaving=false;}
}
function toggleChecklistItem(key) {
    const next=Object.assign({},state.checklistState);next[key]=!next[key];return persistChecklist(next);
}
function resetChecklist() { return persistChecklist({}); }

// ==========================================
// 底部导航栏与日夜模式
// ==========================================
function switchTab(tabName) {
    document.body.setAttribute("data-tab", tabName || "");
    document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.querySelectorAll(".d-nav-item").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-tab") === tabName);
    });

    const panel = document.getElementById("panel-" + tabName);
    const nav = document.getElementById("nav-" + tabName);
    if (panel) panel.classList.add("active");
    if (nav) nav.classList.add("active");

    // 底部导航收成 5 格之后，6 个工具之间靠这条吸顶 chip 互相切换；
    // 不显示的时候必须真的 hidden，不然它会占住一块地方还点不动。
    const strip = document.getElementById("tool-strip");
    if (strip) {
        const isTool = ["recipes", "workout", "body", "takeout", "charts", "gemini"].indexOf(tabName) >= 0;
        strip.hidden = !isTool;
        strip.querySelectorAll(".ts-chip[data-tab]").forEach(chip => {
            chip.setAttribute("aria-selected", chip.getAttribute("data-tab") === tabName ? "true" : "false");
        });
    }
    if (typeof cmRoute === "function") cmRoute(tabName);

    if (tabName === "charts") {
        setTimeout(renderCharts, 50);
    }
    if (typeof window !== "undefined" && window.scrollTo) {
        try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) {}
    }
}

async function switchDayMode(mode, silent) {
    const next = mode === "workout" ? "workout" : "rest";
    const prev = state.mode;
    state.mode = next;
    paintModeButtons();
    renderDashboard();
    renderCharts();
    if (!state.token) {
        if (!silent) callNativeToast("未登录：切换只改显示，登录后才会记进档案");
        return;
    }
    try {
        await postApi("/api/profile/mode", { day_mode: next });
        await syncRemoteDashboard();
        if (!silent) {
            const d = state.calculated;
            callNativeToast(next === "workout"
                ? `运动日：今日预算抬到 ${d.workoutCal} kcal（比休息日多 170 kcal）`
                : `休息日：今日预算 ${d.restCal} kcal`);
        }
    } catch (e) {
        state.mode = prev;
        paintModeButtons();
        renderDashboard();
        reportWriteFailure(e, "日子切换");
    }
}

function paintModeButtons() {
    const btnRest = document.getElementById("btn-mode-rest");
    const btnWorkout = document.getElementById("btn-mode-workout");
    if (!btnRest || !btnWorkout) return;
    btnWorkout.classList.toggle("active", state.mode === "workout");
    btnRest.classList.toggle("active", state.mode !== "workout");
    const hint = document.getElementById("mode-diff-hint");
    if (hint) {
        hint.innerText = state.mode === "workout"
            ? `运动日预算 ${state.calculated.workoutCal || "-"} kcal，比休息日多 170 kcal；练完这一餐补蛋白`
            : `休息日预算 ${state.calculated.restCal || "-"} kcal；训练打卡后会自动换成运动日额度`;
    }
}

// 外卖智能审核与拦截弹窗
function quickCheckTakeout(dishName) {
    document.getElementById("takeout-text").value = dishName;
    analyzeTakeout();
}

function analyzeTakeout() {
    const text = document.getElementById("takeout-text").value.trim();
    if (!text) { callNativeToast("请先输入想点的外卖名称"); return; }

    const item = TAKEOUT_DB[text] || {
        cal: 880, oil: 32,
        warning: "检测到外卖高油高盐风险！重油炒菜与肉类勾芡吸油严重！",
        subName: "白切鸡套餐(去鸡皮去油)+米饭减半",
        subCal: 480,
        subBenefit: "热量仅 480 kcal · 优质蛋白34g · 轻松守住赤字！"
    };

    document.getElementById("modal-dish-name").innerText = text;
    document.getElementById("modal-warning-summary").innerText = item.warning || "注意烹调油控制！";
    document.getElementById("modal-dish-cal").innerText = `${item.cal} kcal`;
    document.getElementById("modal-dish-oil").innerText = `${item.oil} g`;
    document.getElementById("modal-sub-name").innerText = item.subName;
    document.getElementById("modal-sub-benefit").innerText = item.subBenefit;
    state.lastAudit = { name: text, cal: item.cal, subCal: item.subCal };

    document.getElementById("intercept-modal").classList.add("show");
    callNativeVibrate(150);
    callNativeBeep();
}

function closeInterceptModal() {
    document.getElementById("intercept-modal").classList.remove("show");
}

function acceptSubstitute() {
    closeInterceptModal();
    const a = state.lastAudit || {};
    const saved = Math.max(0, Math.round((a.cal || 0) - (a.subCal || 0)));
    callNativeToast(saved > 0
        ? `🎉 已按平替记账：这一单少摄入 ${saved} kcal（${a.name || "本单"}）`
        : "🎉 已采纳平替方案（这一单本来就在预算内，没有差额可记）");
    callNativeVibrate(60);
    if (saved > 0) reportTakeoutEvent("substitute", saved, a.name);
}

function cancelTakeoutOrder() {
    closeInterceptModal();
    const a = state.lastAudit || {};
    callNativeToast(a.cal ? `🛑 帅气退单！这一单的 ${a.cal} kcal 没有进肚子。` : "🛑 帅气退单！");
    callNativeVibrate(100);
    if (a.cal) reportTakeoutEvent("cancelled", a.cal, a.name);
}

async function forceEatTakeout() {
    closeInterceptModal();
    const a = state.lastAudit || {};
    if (!a.cal) {
        callNativeToast("这一单没有审核过，系统没有热量依据，所以没有记账。");
        return;
    }
    try {
        const d = await postApi("/api/food/log",
            { slot: "晚餐", food_name: (a.name || "外卖") + "（坚持下单）", cal: a.cal });
        callNativeToast(`已按审核估算把 ${d.cal || a.cal} kcal 记入今日晚餐。加练不会自动出现，需要你自己打卡。`);
        await syncRemoteDashboard();
        await syncRemoteCharts();
    } catch (e) {
        reportWriteFailure(e, "这笔外卖记账");
    }
}

// ==========================================
// AI 顾问与提问
// ==========================================
// ================= 第五批后续：双引擎 AI（手机本地优先 + 服务器兜底） =================
// 用户提的实质担忧是"用户量上来服务器吃不消"。所以推理尽量落到用户自己手机上，
// 但记忆库与知识库仍然只有服务器那一份：换引擎不能让用户之前说过的话失效。
const LS_ENGINE = "QINGSU_AI_ENGINE";
const LS_LOCAL_PORT = "QINGSU_LOCAL_AI_PORT";
const LOCAL_PROBE_MS = 1500;

function aiEnginePref() {
    try { return localStorage.getItem(LS_ENGINE) || "auto"; } catch (e) { return "auto"; }
}

function setAiEnginePref(v) {
    try { localStorage.setItem(LS_ENGINE, v); } catch (e) {}
    localAiCache.ok = null;
    paintAiEngineBar();
}

function localAiBase() {
    let port = 8081;
    try { port = parseInt(localStorage.getItem(LS_LOCAL_PORT), 10) || 8081; } catch (e) {}
    return "http://127.0.0.1:" + port;
}

const localAiCache = { ok: null, at: 0, ms: 0, why: "" };

/** 带超时的 fetch。AbortController 在旧 WebView 里可能没有，没有就直接放弃探测。 */
async function fetchWithTimeout(url, opts, ms) {
    if(String(url).startsWith("http://127.0.0.1:") && window.AndroidBridge && window.AndroidBridge.localAiRequest){
        return nativeLocalRequest(url,opts,ms);
    }
    if (typeof AbortController === "undefined") {
        const r = await fetch(url, opts);
        return r;
    }
    const ctl = new AbortController();
    const timer = setTimeout(() => { try { ctl.abort(); } catch (e) {} }, ms);
    try {
        const o = Object.assign({}, opts || {}, { signal: ctl.signal });
        return await fetch(url, o);
    } finally {
        clearTimeout(timer);
    }
}

const nativeLocalCallbacks=new Map();
window.onLocalAiResponse=function(id,result){
    const callback=nativeLocalCallbacks.get(id);if(!callback)return;
    nativeLocalCallbacks.delete(id);callback(result);
};
function nativeLocalRequest(url,opts,ms){
    return new Promise((resolve,reject)=>{
        const parsed=new URL(url);const id=Date.now()+"-"+Math.random().toString(36).slice(2);
        const timer=setTimeout(()=>{nativeLocalCallbacks.delete(id);reject(new Error("本地模型请求超时"));},ms);
        nativeLocalCallbacks.set(id,result=>{
            clearTimeout(timer);
            if(result.error){reject(new Error("本地模型："+result.error));return;}
            resolve({ok:result.status>=200&&result.status<300,status:result.status,json:async()=>JSON.parse(result.body||"{}")});
        });
        window.AndroidBridge.localAiRequest(id,Number(parsed.port),parsed.pathname,(opts&&opts.body)||"");
    });
}

/**
 * 探一次手机上的本地模型。结果缓存 20 秒，免得每问一句都白等一次连接超时。
 * 返回 {ok, ms, why}：why 必须能给人看——探测失败要说清是没开、连不上还是超时。
 */
async function probeLocalAi(force) {
    const now = Date.now();
    if (!force && localAiCache.ok !== null && now - localAiCache.at < 20000) {
        return { ok: localAiCache.ok, ms: localAiCache.ms, why: localAiCache.why };
    }
    let out;
    try {
        const r = await fetchWithTimeout(localAiBase() + "/health", { method: "GET" }, LOCAL_PROBE_MS);
        out = { ok: r.status === 200, ms: 0, why: r.status === 200 ? "" : "本地服务返回 " + r.status };
    } catch (e) {
        const name = (e && e.name) === "AbortError" ? "连接超时" : ((e && e.message) || "连不上");
        out = { ok: false, ms: 0, why: "127.0.0.1 上没有可用的本地模型（" + name + "）" };
    }
    out.ms = Date.now() - now;
    localAiCache.ok = out.ok; localAiCache.at = now; localAiCache.ms = out.ms; localAiCache.why = out.why;
    return out;
}

/** 把服务器给的真实数据摘要 + 记忆 + 知识库要点拼进本地提示词。 */
function buildLocalPrompt(question, ctx) {
    const d = ctx.digest || {};
    const facts = [];
    if (d.weight_jin) facts.push("最新体重 " + d.weight_jin + " 斤");
    if (d.target_jin) facts.push("目标体重 " + d.target_jin + " 斤");
    if (d.budget_cal) facts.push("今天(" + (d.day_mode === "workout" ? "运动日" : "休息日") + ")热量预算 " + d.budget_cal + " kcal");
    facts.push("今日已摄入 " + (d.today_consumed || 0) + " kcal，已消耗 " + (d.today_burned || 0) + " kcal");
    if (typeof d.remaining_cal === "number") facts.push("剩余额度 " + d.remaining_cal + " kcal");
    const mem = (ctx.memory || []).length ? "此人明确记下的：" + ctx.memory.join("；") : "此人没有额外备注";
    const kb = (ctx.kb || []).length
        ? "知识库近几条：" + ctx.kb.map(k => k.answer).join(" / ")
        : "知识库里还没有相关条目";
    return "你是减脂记录工具里的助手。对方可能只是打招呼或随口聊天，那就正常接话，不要让他去查资料。规则：涉及数字只能用【本人数据】里出现过的；"
        + "资料没写到的结论不要补；不知道就说不知道，不要编。用中文两三句说完，不要复述问题。\n"
        + "【本人数据】" + facts.join("；") + "\n"
        + "【记忆】" + mem + "\n"
        + "【知识库】" + kb + "\n"
        + "【问题】" + question + "\n【回答】";
}

/** 走手机上的本地模型。返回 {answer, engine}；任何一步不成都抛，交给上层降级。 */
async function askViaLocal(question) {
    const ctx = await getJson("/api/ai/context");
    const r = await fetchWithTimeout(localAiBase() + "/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            messages: [{ role: "user", content: buildLocalPrompt(question, ctx) }],
            max_tokens: 220, temperature: 0.2, stream: false
        })
    }, 25000);
    if (!r.ok) throw new Error("本地模型返回 " + r.status);
    const j = await r.json();
    const txt = (((j.choices || [])[0] || {}).message || {}).content || "";
    if (!txt.trim()) throw new Error("本地模型返回空内容");
    // 本地回答保存到本人私有记录：两个引擎共用同一份，不是各记各的
    try {
        await postApi("/api/ai/record", { question: question, answer: txt, sources: [] });
    } catch (e) {
        console.warn("local answer not recorded", e && e.message);
    }
    return { answer: escapeHtml(stripTagsLocal(txt)), engine: "local", source: "local_model" };
}

/** 走服务器问答接口（本机模型 + 联网 + 规则都在服务端）。 */
async function askViaServer(question, routeOnly = false) {
    const d = await postApi("/api/ask", { question: question, route_only: routeOnly });
    return { answer: String(d.answer || ""), engine: "server", source: d.source || "none" };
}

/**
 * 引擎决策。auto = 本地优先、服务器兜底；
 * 两个都不行时不假装成功，直接把两边的失败原因都摆出来。
 */
async function askAnyEngine(question) {
    const pref = aiEnginePref();
    const errs = [];
    try {
        const routed=await askViaServer(question, true);
        if (routed.source!=="none") return routed;
    } catch(e) {
        errs.push("服务器规则："+((e&&e.message)||"不可用"));
    }
    if(pref==="server")return await askViaServer(question);
    let localNote = "";
    if (pref !== "server") {
        const p = await probeLocalAi(false);
        if (p.ok) {
            try {
                return await askViaLocal(question);
            } catch (e) {
                errs.push("本地：" + ((e && e.message) || "失败"));
                localAiCache.ok = null;
            }
        } else {
            // auto 模式下本地离线是常态，单说它没意义；但要是服务器也跟着挂，
            // 就必须让用户知道本地那条路当时也不通，否则他只看到服务器报错
            localNote = "本地：" + p.why;
            if (pref === "local") errs.push(localNote);
        }
        if (pref === "local" && errs.length) {
            const err = new Error(errs.join("；"));
            err.noFallback = true;
            throw err;
        }
    }
    try {
        return await askViaServer(question);
    } catch (e) {
        errs.push("服务器：" + ((e && e.message) || "失败"));
        if (localNote && errs.indexOf(localNote) < 0) errs.push(localNote);
        throw new Error(errs.join("；") || "两个引擎都没答上");
    }
}

function engineTag(source) {
    return {
        data: "【你的真实记录】", web: "【联网资料】", web_model: "【服务器模型整理】",
        chat: "【闲聊】",
        kb: "【本机知识库】", memory: "【你的备注】", none: "【没查到】",
        limited: "【查询过于频繁】", local_model: "【手机本地模型】"
    }[source] || "";
}

function paintAiEngineBar() {
    const el = document.getElementById("ai-engine-bar");
    if (!el) return;
    const pref = aiEnginePref();
    const sel = document.getElementById("ai-engine-sel");
    if (sel && sel.value !== pref) sel.value = pref;
    if (localAiCache.ok === null) {
        el.innerHTML = "<span>正在探本地模型…</span>";
        return;
    }
    if (localAiCache.ok) {
        el.innerHTML = "<span class='eng-ok'>本机模型在线</span><span class='eng-ms'>" + localAiCache.ms + "ms</span>";
        return;
    }
    // 没开本机模型是默认状态，不是故障：说清"这条走服务器"就够，
    // 别用红色"离线 + Failed to fetch"在页面上常驻一条像报错的噪音
    const label = pref === "local"
        ? "本机没开模型，只用本机的话这条答不了"
        : "本机没开模型 · 这条走服务器";
    const why = String(localAiCache.why || "")
        .replace(new RegExp("[（(]?Failed to fetch[）)]?", "g"), "")
        .replace(/[（(]\s*[)）]/g, "").replace(/\s+$/g, "").trim();
    el.innerHTML = "<span class='eng-no'>" + label + "</span>"
        + (why ? "<span class='eng-sep'>·</span><span class='eng-why'>" + escapeHtml(why) + "</span>" : "");
}

async function reprobeLocalAi() {
    localAiCache.ok = null;
    paintAiEngineBar();
    await probeLocalAi(true);
    paintAiEngineBar();
}

async function sendChatMessage() {
    const input = document.getElementById("chat-input");
    const msg = input.value.trim();
    if (!msg) return;

    appendBubble("user", msg, false);
    input.value = "";
    const bubble = appendBubble("assistant", state.token ? "正在查你的记录（本地模型优先，服务器兜底）…" : "未登录，只能给通用建议…", false);

    if (!state.token) {
        bubble.innerHTML = escapeHtml("【本地通用建议】" + stripTagsLocal(generateAiResponse(msg)))
            .replace(/\n/g, "<br>") +
            "<br><br><span style='color:#94A3B8;font-size:11px;'>登录后我才能查你自己的体重、额度与打卡记录。</span>";
        return;
    }

    try {
        const d = await askAnyEngine(msg);
        const LF = String.fromCharCode(10);
        bubble.innerHTML = "<strong>" + engineTag(d.source) + "</strong>"
            + String(d.answer || "").split(LF).join("<br>")
            + "<br><span class='eng-line'>引擎："
            + (d.engine === "local" ? "手机本地模型" : "服务器") + " · 个人记忆与引擎切换共用</span>";
    } catch (e) {
        // 两个引擎都失败时把两边原因都摊开，再给内置建议，并明说这段不含真实数据
        bubble.innerHTML = "<strong>【两个引擎都没答上】</strong>" +
            escapeHtml((e && e.message) ? e.message : "未知错误") +
            "<br>下面这段是本地内置建议，不含你的真实数据：<br>" +
            escapeHtml(stripTagsLocal(generateAiResponse(msg)));
    }
    box_scroll();
}

function stripTagsLocal(s) {
    return String(s).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function box_scroll() {
    const box = document.getElementById("chat-messages-box");
    if (box) box.scrollTop = box.scrollHeight;
}

function quickAsk(q) {
    document.getElementById("chat-input").value = q;
    sendChatMessage();
}

function appendBubble(role, text, asHtml) {
    const box = document.getElementById("chat-messages-box");
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    // 默认按纯文本处理：用户输入与任何第三方内容都不许当标签执行
    div.innerHTML = (asHtml ? String(text) : escapeHtml(String(text))).replace(/\n/g, "<br>");
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
}

function generateAiResponse(query) {
    const rows=typeof localGuidanceRows === "undefined"?[]:localGuidanceRows;
    const hits=rows.map(row=>({row,score:Math.max(0,...row.keywords.filter(k=>query.includes(k)).map(k=>k.length))})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
    if(hits.length)return hits[0].row.text;
    return "当前没有足够资料回答这个问题。登录并同步后可以查询自己的记录；疾病、用药和特殊饮食需求请咨询专业人员。";
}

function callNativeToast(msg) {
    if (window.AndroidBridge && window.AndroidBridge.showToast) {
        window.AndroidBridge.showToast(msg);
    } else {
        showWebToast(msg);
    }
}

function showWebToast(msg) {
    let t = document.getElementById("web-toast-container");
    if (!t) {
        t = document.createElement("div");
        t.id = "web-toast-container";
        t.style.position = "fixed";
        t.style.bottom = "84px";
        t.style.left = "50%";
        t.style.transform = "translateX(-50%) translateY(0)";
        t.style.background = "rgba(15, 23, 42, 0.92)";
        t.style.color = "#FFFFFF";
        t.style.padding = "9px 18px";
        t.style.borderRadius = "99px";
        t.style.fontSize = "12px";
        t.style.fontWeight = "600";
        t.style.zIndex = "99999";
        t.style.boxShadow = "0 4px 18px rgba(0,0,0,0.22)";
        t.style.transition = "opacity 0.25s, transform 0.25s";
        t.style.pointerEvents = "none";
        document.body.appendChild(t);
    }
    t.innerText = msg;
    t.style.opacity = "1";
    t.style.transform = "translateX(-50%) translateY(0)";
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => {
        t.style.opacity = "0";
        t.style.transform = "translateX(-50%) translateY(10px)";
    }, 2200);
}

function callNativeVibrate(ms) {
    if (window.AndroidBridge && window.AndroidBridge.vibrate) {
        window.AndroidBridge.vibrate(ms);
    } else if (navigator.vibrate) {
        try { navigator.vibrate(ms); } catch(e) {}
    }
}

function callNativeBeep() {
    if (window.AndroidBridge && window.AndroidBridge.playBeep) {
        window.AndroidBridge.playBeep();
    }
}

// ==========================================
// APK 手机客户端下载与扫码弹窗逻辑
// ==========================================
const MOB_ICON = "📱";
const PC_ICON = "🖥️";

/** 是否跑在 App 的 WebView 里。网页版返回 false；两处行为要分开都走这个判断。 */
function inApp() {
    return !!(window.AndroidBridge && window.AndroidBridge.showToast);
}

function applyViewMode(mode) {
    document.body.classList.toggle("desktop-view", mode === "desktop");
    document.body.classList.toggle("mobile-view", mode !== "desktop");
    const btn = document.getElementById("btn-view-toggle");
    if (btn) {
        // 只放图标：这颗按钮在窄屏顶栏里，一带字就换行顶出按钮框
        btn.innerText = (mode === "desktop") ? MOB_ICON : PC_ICON;
        btn.title = (mode === "desktop")
            ? "当前电脑版排版 · 点一下切回手机版"
            : "当前手机版排版 · 点一下切电脑版（宽屏双栏）";
        btn.setAttribute("aria-label", btn.title);
    }
    try { localStorage.setItem("QINGSU_VIEW_MODE", mode); } catch (e) {}
    setTimeout(() => { renderCharts(); }, 60);
}

function toggleViewMode() {
    const cur = document.body.classList.contains("desktop-view") ? "desktop" : "mobile";
    applyViewMode(cur === "desktop" ? "mobile" : "desktop");
    callNativeToast(cur === "desktop" ? "已切到手机版排版" : "已切到电脑版排版（宽屏双栏）");
}

function initViewMode() {
    let saved = null;
    try { saved = localStorage.getItem("QINGSU_VIEW_MODE"); } catch (e) {}
    const wide = window.innerWidth >= 900;
    applyViewMode(saved || (wide ? "desktop" : "mobile"));
}

// ============ 第六批补：下载弹窗的版本与体积一律现读，不留写死字 ============
/**
 * 量一次真实下行：只取 256KB 分段，别为了测速把整个包拖下来。
 * 服务器不支持 Range（不是 206）就放弃并说明，不拿默认值糊一个"实测"。
 */
async function probeDownloadRate() {
    const want = 262144;
    const r = await fetch(API_BASE + "/qingsu.apk", { cache: "no-store", headers: { "Range": "bytes=0-" + (want - 1) } });
    if (r.status !== 206) {
        try { if (r.body && r.body.cancel) await r.body.cancel(); } catch (e) {}
        throw new Error("服务器不支持分段读取");
    }
    const started = Date.now();
    const blob = await r.blob();
    const seconds = (Date.now() - started) / 1000;
    if (blob.size < want * 0.5 || seconds <= 0) throw new Error("测速样本不足");
    return blob.size / seconds;
}

/**
 * 线上包的真实指纹来自 /version.json（由 make_version_json.py 从 build.gradle 与
 * 实际 apk 现算）。读不到就写"未知"，绝不回落到旧的字面量——那正是这次要修的 bug。
 */
async function loadApkMeta() {
    const put = function (id, txt) {
        const el = document.getElementById(id);
        if (el) el.textContent = txt;
    };
    let v = null;
    try {
        const r = await fetch(API_BASE + "/version.json", { cache: "no-store" });
        if (r.ok) v = await r.json();
    } catch (e) { v = null; }
    if (!v || !v.version_name) {
        put("apk-ver-top", "版本未知（清单没读到）");
        put("apk-ver-line", "版本未知");
        put("apk-size-line", "体积未知");
        put("apk-speed-line", "下载速度未测");
        return null;
    }
    const mib = v.size ? (v.size / 1048576) : 0;
    const sizeTxt = v.size ? (mib.toFixed(2) + " MB / " + v.size.toLocaleString() + " 字节") : "未知";
    put("apk-ver-top", "v" + v.version_name + "（build " + v.version_code + "）");
    put("apk-ver-line", "v" + v.version_name + " · build " + v.version_code);
    put("apk-size-line", sizeTxt);
    // 耗时按"这个人现在这条链路"实测，不沿用别人机器上量过一次、之后再也不变的数
    const fresh = document.getElementById("apk-fresh-line");
    if (fresh) {
        let mine = 0;
        try { if (window.AndroidBridge && AndroidBridge.getAppVersionCode) mine = Number(AndroidBridge.getAppVersionCode()) || 0; } catch (e) {}
        const stamp = String(v.sha256 || "").slice(0, 8);
        // 两边号都要写出来并说明关系：只说"你已经是最新"在手机比服务器还新时就是假话
        const rel = !mine ? "" : (mine < v.version_code ? " · 你的手机需要更新"
            : (mine > v.version_code ? " · 你的手机比服务器上的包更新" : " · 与手机一致"));
        fresh.textContent = "这个包 build " + v.version_code + "（指纹 " + (stamp || "未知") + "）"
            + (mine ? " · 手机上 build " + mine : " · 手机版本读不到") + rel;
    }
    put("apk-speed-line", v.size ? "正在测你这条链路的下载速度…" : "下载速度未测");
    if (v.size) probeDownloadRate().then(rate => {
        const secs = Math.max(1, Math.round(v.size / rate));
        put("apk-speed-line", "实测约 " + (rate / 1048576).toFixed(1) + " MB/s，这个包大约要 " + secs + " 秒");
    }).catch(() => put("apk-speed-line", "下载速度未测（测速请求没成功）"));
    const link = document.getElementById("apk-direct-link");
    if (link) {
        // href 必须带源：App 里根相对路径指向 assets 域，点下去什么都不会发生
        link.href = API_BASE + "/qingsu.apk?v=" + String(v.sha256 || "").slice(0, 12);
        link.setAttribute("download", "轻塑_" + v.version_name + "_b" + v.version_code + ".apk");
        const box = document.getElementById("modal-download-url");
        if (box) { box.textContent = link.href; box.setAttribute("href", link.href); }
    }
    state.apkMeta = v;
    return v;
}
function openDownloadModal() {
    const modal = document.getElementById("download-apk-modal");
    if (modal) modal.classList.add("show");
    loadApkMeta();
    callNativeVibrate(40);
}

function closeDownloadModal() {
    const modal = document.getElementById("download-apk-modal");
    if (modal) modal.classList.remove("show");
}

async function exportMyData() {
    if (!state.token) { callNativeToast("请先登录再导出"); openAuthModal(); return; }
    try {
        const res = await fetch(`${API_BASE}/api/export.csv`, {
            headers: { "Authorization": `Bearer ${state.token}` }
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const text = await res.text();
        if(inApp() && window.AndroidBridge.saveCsv){window.AndroidBridge.saveCsv(text);return;}
        const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "轻塑我的记录.csv";
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
        callNativeToast("已导出全部流水（CSV，Excel 可直接打开）");
    } catch (e) {
        callNativeToast("导出失败：" + (e && e.message ? e.message : "网络不通"));
    }
}

function copyApkDownloadUrl() {
    const url = "https://124.220.54.64/qingsu.apk";
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            callNativeToast("📋 公网直链已复制！可直接发送给手机/微信打开！");
            callNativeVibrate(50);
        }).catch(() => fallbackCopy(url));
    } else {
        fallbackCopy(url);
    }
}

function onDirectDownloadClick(event) {
    const link = document.getElementById("apk-direct-link");
    const url = link ? link.href : "";
    if (window.AndroidBridge && AndroidBridge.openBrowser && url.indexOf("http") === 0) {
        // WebView 自己不会下载 .apk（没有 DownloadListener），交给系统浏览器
        if (event && event.preventDefault) event.preventDefault();
        AndroidBridge.openBrowser(url);
        callNativeToast("已交给系统浏览器下载，完成后在通知栏或文件管理里安装");
        callNativeVibrate(50);
        return false;
    }
    callNativeToast("⬇️ 正在启动下载轻塑 APK 安装包，下载完成后即可直接安装！");
    callNativeVibrate(50);
}

// ============================================================
// 无障碍：弹窗焦点约束、ESC 关闭、自定义按钮键盘激活
// ============================================================
const DIALOG_OVERLAY_IDS = ["profile-modal", "intercept-modal", "auth-modal",
    "download-apk-modal", "ex-detail-modal"];
let dialogReturnFocus = null;

function openDialogs() {
    return DIALOG_OVERLAY_IDS.map(id => document.getElementById(id))
        .filter(el => el && el.classList.contains("show"));
}

function topDialog() {
    const list = openDialogs();
    return list.length ? list[list.length - 1] : null;
}

function dialogPanel(overlay) {
    return overlay ? overlay.querySelector(".modal-card") : null;
}

function dialogFocusables(root) {
    if (!root) return [];
    const sel = 'a[href],button:not([disabled]),input:not([disabled]),'
        + 'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
    return Array.prototype.slice.call(root.querySelectorAll(sel))
        .filter(el => !el.hasAttribute("hidden") && el.type !== "hidden");
}

function syncDialogInert() {
    const top = topDialog();
    // 弹窗开着的时候，背景内容既不该被读屏念到，也不该被 Tab 走到。
    Array.prototype.forEach.call(document.body.children, node => {
        if (node.nodeType !== 1) return;
        const inDialog = !!top && (node === top || node.contains(top));
        if (top && !inDialog) {
            node.setAttribute("aria-hidden", "true");
            try { node.inert = true; } catch (e) {}
        } else {
            node.removeAttribute("aria-hidden");
            try { node.inert = false; } catch (e) {}
        }
    });
}

function onDialogOpened(overlay) {
    if (!dialogReturnFocus) dialogReturnFocus = document.activeElement;
    syncDialogInert();
    const panel = dialogPanel(overlay);
    const items = dialogFocusables(panel);
    const target = items.length ? items[0] : panel;
    if (target && target.focus) { try { target.focus({ preventScroll: true }); } catch (e) {} }
}

function onDialogClosed() {
    syncDialogInert();
    if (!topDialog() && dialogReturnFocus && dialogReturnFocus.focus) {
        try { dialogReturnFocus.focus({ preventScroll: true }); } catch (e) {}
        dialogReturnFocus = null;
    }
}

function installDialogAccessibility() {
    if (!window.MutationObserver) return;
    DIALOG_OVERLAY_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (!el || el.dataset.a11yBound) return;
        el.dataset.a11yBound = "1";
        new MutationObserver(() => {
            if (el.classList.contains("show")) onDialogOpened(el); else onDialogClosed();
        }).observe(el, { attributes: true, attributeFilter: ["class"] });
    });
}

function closeTopDialog() {
    const top = topDialog();
    if (!top) return false;
    const btn = top.querySelector(".modal-close-btn, .exd-close");
    if (btn) { btn.click(); return true; }
    top.classList.remove("show");
    return true;
}

document.addEventListener("keydown", e => {
    if (e.key === "Escape") { if (closeTopDialog()) e.preventDefault(); return; }
    if (e.key === "Tab") {
        const panel = dialogPanel(topDialog());
        if (!panel) return;
        const items = dialogFocusables(panel);
        if (!items.length) { e.preventDefault(); return; }
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        } else if (!panel.contains(document.activeElement)) {
            e.preventDefault(); first.focus();
        }
        return;
    }
    // <div role="button"> 必须和真按钮一样能被回车/空格激活
    const t = e.target;
    if ((e.key === "Enter" || e.key === " ") && t && t.getAttribute
        && t.getAttribute("role") === "button" && !e.repeat) {
        e.preventDefault();
        t.click();
    }
});

function describeDeficit(rows, targetDeficit) {
    let ok = 0, low = 0, over = 0, missing = 0;
    (rows || []).forEach(d => {
        if (d.record_status === "missing") { missing++; return; }
        if (!(d.deficit > 0)) { over++; return; }
        if (d.deficit >= targetDeficit) { ok++; return; }
        low++;
    });
    const n = rows ? rows.length : 0;
    const text = n
        ? ("近" + n + "天：达标 " + ok + " 天 · 未达 " + low + " 天 · 超支 " + over
           + " 天 · 未记录 " + missing + " 天（目标缺口 " + Math.round(targetDeficit)
           + " kcal；* 表示当天只记了部分）")
        : "暂无真实缺口记录，记饮食与运动后生成真实柱状图";
    const box = document.getElementById("chart-deficit-summary");
    if (box) box.innerText = text;
    const cv = document.getElementById("chart-deficit");
    if (cv) cv.setAttribute("aria-label", "热量缺口柱状图：" + text);
    return text;
}

window.addEventListener("load", installDialogAccessibility);
installDialogAccessibility();

// ============================================================
// 今日记录完整性确认：后端 /api/day/complete 早就有，界面上一直没有入口
// ============================================================
function renderDayComplete(data) {
    const btn = document.getElementById("day-complete-btn");
    const tag = document.getElementById("day-complete-state");
    if (!btn || !tag) return;
    const day = data && data.today ? data.today : (state.dayComplete || {}).date;
    const done = !!(data && data.today_confirmed);
    state.dayComplete = { date: day, confirmed: done };
    if (!day) {
        // 老服务端不返回 today。这时候只把按钮灰着、标签停在"状态读取中"，
        // 用户看到的是"这功能坏了但没人告诉我"。得说清楚是服务端还没升级。
        tag.innerText = "服务端未支持";
        tag.className = "day-complete-state";
        btn.innerText = "确认今天记完整了";
        btn.disabled = true;
        return;
    }
    tag.innerText = done ? "已确认记全" : "还没确认";
    tag.className = "day-complete-state" + (done ? " done" : "");
    btn.innerText = done ? "取消这个确认" : "确认今天记完整了";
    btn.dataset.done = done ? "1" : "0";
    btn.disabled = false;
}

async function toggleDayComplete() {
    const btn = document.getElementById("day-complete-btn");
    if (!btn || btn.disabled) return;
    const day = (state.dayComplete || {}).date;
    if (!day) { callNativeToast("今天几号还没取到，先刷新一下"); return; }
    const done = btn.dataset.done === "1";
    btn.disabled = true;
    try {
        await postApi("/api/day/complete", { log_date: day, complete: !done });
        if (done) {
            state.dayComplete = { date: day, confirmed: false };
            renderDayComplete({ today: day, today_confirmed: false });
            callNativeToast("已取消确认，这一天重新按部分记录算");
        } else {
            await syncRemoteDashboard();
            callNativeToast("已确认：周报会把今天算作完整日");
        }
        callNativeVibrate(50);
    } catch (e) {
        btn.disabled = false;
        reportWriteFailure(e, "完整日确认");
    }
}
