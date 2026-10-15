# 轻塑 · 减脂塑形严管伴侣 v5.0

Android WebView 壳 + 单页 H5 + 腾讯云 FastAPI 后端的减脂记录工具。客户端本身不存业务数据，所有打卡都落云端 SQLite，每个用户有一条免登录的公网监督页。

这份文档按 2026-10-15 这轮审计后的实际行为写，不写"设计意图"。凡界面说的和代码做的不一致，一律以代码为准，并把差距列在「已知限制」里。

---

## 下载与部署状态

| 项目 | 实测值 |
| --- | --- |
| 公网直链 | http://124.220.54.64/qingsu.apk |
| 二维码 | http://124.220.54.64/qr.svg |
| 仓库内安装包（本轮重打） | 5,588,679 字节，md5 `da0f54c0fc38da7e9e3209904fbc7494` |
| 线上当前那份 | 5,554,752 字节，md5 `f1a75da39820dc32c4423c89e1b6e370`（**改动前的包，还没替换**） |
| 下载实测 | 0.33 MB/s，约 16 秒下完（这台服务器带宽就这个水平，别指望"高速"） |

服务器：腾讯云 OpenCloudOS 4C4G，Docker 里的 nginx 容器 `xiaoye-release` 反代到宿主机 `172.17.0.1:8000` 的 uvicorn（`qingsu.service` 守护）。**只有 HTTP 80 端口，没有域名、没有证书。**

> 本轮只改了仓库里的源码与安装包，**线上三样东西都还是旧的**：`/app.js` 是改动前的前端，`/qingsu.apk` 是改动前的包，`server.py` 也没热修——所以公网大屏那个 XSS 在线上此刻仍然可以触发。部署动作见文末。

---

## 功能与它的边界

### 打卡与热量账本
四张流水表：饮食、空腹体重、训练、饮水。用户填什么就存什么，没有自动补录。

- 饮食热量：不填 `cal` 时，服务端按菜名关键词粗估（基础 350 kcal，命中"米饭/牛肉/鸡胸/炸烤/青菜"等词加减），**不是查营养成分表得来的**。
- 三大宏量：拿到估算热量后按固定比例倒推——蛋白 25%、碳水 45%、脂肪 30%，再除以 4/4/9 换克数。**同一餐里"白水煮鸡胸"和"红烧排骨"的宏量比例是一模一样的。**
- 训练消耗：客户端写死 220 kcal / 20 分钟提交一条记录；界面计时器按每秒 0.18 kcal 累加，两者不是同一套算法，以入库的 220 为准。
- 剩余预算 = 每日目标热量 − 今日摄入 + 今日消耗。

### 图表（三条，全部由真实流水生成）
- 体重曲线：只画 `weight_logs` 里真实存在的那些日期，一天一个点；完全没有记录时退回档案基线一个点。
- 热量缺口柱（近 7 天）：`净缺口 = TDEE + 当日训练消耗 − 当日摄入`。**这一天一笔未记（包括今天）就是 0，不会拿目标值冒充"已创造赤字"。**
- 宏量配比环：今日没记录时画灰色空环写"今日无记录"；有记录时按真实热量占比分段，某项为 0 就不画那一段。

### 饭点外卖门禁
判据是"今日剩余预算 ≤ 0"。

做到：本 App 入口按钮被拦下 + 震动 + 蜂鸣 + 弹窗建议（温水排钠、豆腐汤）。预算够时把减脂备注写进剪贴板，再跳美团/饿了么；手机没装 App 就打开网页版。

做不到：**它无法锁定手机上别的外卖 App**。所谓"锁定点单通道"只是拦自己页面里那颗按钮。另外两种情况已修：未登录时不再谎报"今日已超标"，而是引导先登录；网络取不到今日额度时既不拦截也不放行，会明说"额度还没取到"。

跳转依赖 `getLaunchIntentForPackage()`，Android 11 起必须在清单里声明包可见性，否则恒返回 null（表现为"跳转"永远只打开网页）。本轮已补 `<queries>`。

### 身形目标与动作库
8 款：女 4（S型沙漏、修长轻盈、紧致力量、稳健脱脂）+ 男 4（倒三角、修长衣架子、饱满力量、啤酒肚专项）。每款一张内置 SVG 示意图（画的是理想形体，不是用户本人），驱动两件事：三宏量比例与热量缺口档位（420/500/+250/550 kcal），以及从 32 个动作里选出的那组 4 个。

### 周期身材照
提交体重 + 肚脐腰围（可选照片），服务端插一条 `body_cycles` 并生成一段报告。

- 照片原样存 `/uploads/` 供前后对照，**服务端从不调用任何图像识别，也不看像素**。
- 围度增减只在"上一次和这一次都有测量值"时才计算；注册时不采集腰围，所以第一次提交会写"待补围度"，而不是拿一个编造的基准算出"+7.0 cm"。
- "第 N 周期 (第 x-y 天)"里的天数是 `周期序号 × 7` 推算出来的字符串。**没有任何 7 天间隔校验**，一天提交五次就会得到五个周期。
- 报告说"训练动作进阶、饮食调配更新"只是文案：动作库和食谱不会因提交本表而改写，换方案要去【档案】里选身形。

### 问答顾问
纯本地关键词规则库，不联网、不调任何大模型、不需要任何 key。界面 5 颗预设问题，每条都有对应专答（本轮补齐了"平台期"和"练后饿"两条此前只会落到兜底话的）。命中不了就返回一段基于当前档案数字的通用建议。

### 公网监督大屏
`http://124.220.54.64/u/<用户名>`，家人朋友不用登录就能看。用户名来自 URL，本轮已修：404 页做 HTML 转义，注入到页面的用户名字符串走 `JSON` 编码并把 `<` 转义（此前 `/u/<img src=x onerror=alert(1)>` 可在线上直接执行脚本）。

---

## 架构

| 层 | 实测规模 |
| --- | --- |
| Android 壳 | `MainActivity.java` 130 行（WebView + 相册选择器 + 双击返回）、`WebAppInterface.java` 8 个 `@JavascriptInterface` 方法 |
| 前端 | `app.js` 约 2062 行 / `index.html` 1104 行 / `style.css`，全在 `file:///android_asset/` |
| 后端 | `server.py` 约 842 行，FastAPI + SQLite，19 条路由，7 张表（users, profiles, food_logs, weight_logs, workout_logs, water_logs, body_cycles） |
| 线上静态 | `/` `/app.js` `/style.css` `/qr.svg` `/qingsu.apk` 由服务端从 `/opt/qingsu/web` 读文件返回 |

线上当前三份前端与包都是 v5.0 那版。审计时（本轮改动之前）逐字节比过：`/` 首页、`/app.js`、`/style.css`、`/qr.svg` 与仓库内 assets 完全相同，说明"多端同步"当时是真的。本轮改了 `app.js` 后**尚未部署**，所以现在线上那份 `app.js` 比仓库旧一版。

---

## 本地构建

### Android
仓库里**没有 Gradle Wrapper**（`gradlew` / `gradle/wrapper` 都不存在），所以 `./gradlew assembleDebug` 跑不通，必须显式指定 Gradle：

```bat
cd /d/RuanJian/JiaZhiSuXianApk
"D:\RuanJian\AndroidTools\gradle\gradle-8.5\bin\gradle.bat" assembleDebug --offline
```

SDK 路径来自 `local.properties`（已 gitignore）：`D:\RuanJian\AndroidTools\android-sdk`。产物在 `app/build/outputs/apk/debug/app-debug.apk`。

### 后端
`server.py` 里 `DB_DIR/UPLOAD_DIR/WEB_DIR` 是写死的 Linux 绝对路径，Windows 下直接 import 会在当前盘根建 `/opt/qingsu`。线上部署走 `setup_server.sh`（systemd）+ `update_nginx.sh`（改容器里 nginx 配置，保留 `latest.json` 两条既有路由）。运维通道是 `remote_exec.py`，它用 `%TEMP%\test_key.pem`，密钥本身不入库（`.gitignore` 含 `*.pem`）。

---

## 回归台（本轮新增）

不装 FastAPI 也能验后端：`_audit_harness.py` 往 `sys.modules` 注入框架 stub，然后 exec 真实的 `server.py`，直接调用路由函数体和 SQLite 查询，沙箱目录落在项目内不碰系统盘。

```bash
python _audit_harness.py            # 当前源码，23 条判据应全绿
python _audit_harness.py --mutant   # 跑 git HEAD 那版，判据应大面积红（红了才说明判据不是恒真）

node _audit_harness.mjs             # 当前 app.js，28 条判据应全绿
node _audit_harness.mjs --mutant    # 同上，改动前那版实测红 21 条
```

2026-10-15 这轮标定结果：当前源码 23+28 全绿，改动前版本红 14+21 条，红的每一条都对应下面列出的一个真实缺陷。

---

## 线上部署（本轮未执行）

代码修完不等于线上修完。要三样都换过去，缺一不可：

```bash
python remote_exec.py --scp server.py                  /opt/qingsu/server.py
python remote_exec.py --scp app/src/main/assets/app.js  /opt/qingsu/web/app.js
python remote_exec.py --scp qingsu.apk                 /opt/qingsu/web/qingsu.apk
python remote_exec.py "systemctl restart qingsu && sleep 2 && systemctl is-active qingsu"
```

（依赖 `%TEMP%\test_key.pem`，密钥不入库。`index.html` 与 `style.css` 本轮没改，不用传。）

部署后的验收，三条 curl 就够：

1. `curl 'http://124.220.54.64/u/<img%20onerror=alert(1)>'` 里不应再出现 `<img`，应是 `&lt;img`；
2. 下载线上包算 md5，应等于 `da0f54c0fc38da7e9e3209904fbc7494`；
3. 取一个真实用户的 `/api/public/charts`，近 7 天里没有任何记录的那天，`deficit` 必须是 0。

**遗留脏数据**：改代码不会让历史库里那条伪造的 `waist_cm=78.0` 消失。本轮之前注册的用户，`weight_logs` 首条与 `body_cycles` 第 1 周期的腰围仍是 78，他们第一次提交周期照时依然会算出一个假的围度增减。部署时顺手查一下涉及多少人，要不要清这两处旧值是个数据决定，得单独定：

```bash
python remote_exec.py "sqlite3 /opt/qingsu/data/qingsu.db 'SELECT count(*) FROM users; SELECT count(*) FROM weight_logs WHERE waist_cm=78.0; SELECT count(*) FROM body_cycles WHERE waist_cm=78.0;'"
```

---

## 已知限制（没修的，都在这儿）

1. **全站 HTTP 明文**，密码和 token 在网络上裸奔；没有域名和证书，也无法强制 HTTPS。
2. **口令是未加盐的 SHA-256**，token 明文存在 `users` 表里，登录一次换发一个新 token（旧的自然失效，但没有过期时间）。
3. **公网大屏无任何鉴权**，`/api/public/dashboard?username=` 能拿到任意用户的当日每餐明细、体重和照片路径；用户名可枚举。这是产品卖点，也是敞口。
4. CORS 是 `allow_origins=["*"]` 且 `allow_credentials=True`。
5. `android:allowBackup="true"`，登录态会随系统备份走。
6. 食物热量与宏量是粗估口径（见上），不是营养学数据；对外别把它当膳食处方宣传。
7. 训练消耗固定 220 kcal，不区分动作、体重和强度。
8. "周期"与真实日历无关，只按提交次数命名。
9. `build.gradle` 里 `versionName "1.0.0"`，而原生桥返回的却是 `"5.0.0 (云端真数据与外卖严管版)"`，两处版本号没打通。
10. 问答顾问是规则匹配，别称它为大模型/AI 能力。

---

## 变更记录

### 2026-10-15 审计轮（本轮）
先逐条回源核对了 README 的每项承诺与线上真实行为，然后按证据修，判据正反样本都跑过：

- **Android 11+ 外卖跳转是哑的** → 清单补 `<queries>`。
- **四类打卡失败被提示成"成功"** → `saveWeight` / `completeWorkoutToday` / `logNaturalMeal` / `toggleWaterCup` / `upgradeCyclePlan` / `saveCustomProfile` 统一走 `postApi`：非 2xx 一律抛错，失败明确说"没保存"，401 说"登录失效"并拉回登录。旧版在 token 失效时会对每一笔打卡都播"体重打卡成功！"而实际一条都没落库。
- **外卖门禁把"额度未知"当"已超标"** → 加 `dashboardLoaded` 判据；未登录引导登录，取不到额度如实说明。
- **净缺口口径** → 基准从 `target_cal` 换成 `tdee`（旧算法吃满预算显示 0，真实缺口 420），且今天零记录不再凭空长出一根柱子（实测旧版新用户第一天就显示 1511 kcal "赤字"）。
- **注册伪造腰围 78 cm** → 改为留空，缺基准时报告不输出围度增减，评级写"待补围度"。
- **报告谎称"AI 视觉与围度诊断：内脏脂肪明显变薄"** → 改成只陈述两次打卡的差值，并写明照片未被分析过。
- **公网大屏反射型 XSS**（线上已实测可执行） → 404 页 HTML 转义，注入的用户名字符串改 JSON 编码并转义 `<`；前端横幅同步转义。
- **宏量环零记录画三等分假图** → 空数据画灰环；去掉每项 10% 的垫底，为 0 就不画那一段。
- **两颗问答按钮点了答非所问** → 补"平台期"和"练后饿"两条规则。
- **README 与代码不符** → 4 类身形实为男女 8 款、无 gradle wrapper、"锁定通道"只拦自己按钮、"自动进阶"仅文案、宏量是比例倒推、"每 7 天"无校验、AI 顾问是本地规则库——全部改写，并补上面这节「已知限制」。

### v5.0（2026-10-15 早先）
公网大屏集成 APK 下载弹窗与扫码；男女分流 8 款身形与 SVG 图示；云端多用户真数据。
