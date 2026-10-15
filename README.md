# 轻塑 · 减脂塑形严管伴侣 v5.0

Android WebView 壳 + 单页 H5 + 腾讯云 FastAPI 后端的减脂记录工具。客户端本身不存业务数据，所有打卡都落云端 SQLite，每个用户有一条免登录的公网监督页。

这份文档按 2026-10-15 这轮审计后的实际行为写，不写"设计意图"。凡界面说的和代码做的不一致，一律以代码为准，并把差距列在「已知限制」里。

---

## 下载与部署状态

| 项目 | 实测值 |
| --- | --- |
| 公网直链 | http://124.220.54.64/qingsu.apk |
| 二维码 | http://124.220.54.64/qr.svg |
| 用户监督大屏 | http://124.220.54.64/u/&lt;用户名&gt; |
| 安装包（2026-10-16 重打） | 5,560,565 字节，md5 `c3fee3c4c4c92a0e2325da0dfccde27c` |
| 线上当前那份 | 同上，已部署并核对一致 |
| 下载实测 | 0.33 MB/s，约 16 秒下完（这台服务器带宽就这个水平，别指望"高速"） |

服务器：腾讯云 OpenCloudOS 4C4G，Docker 里的 nginx 容器 `xiaoye-release` 反代到宿主机 `172.17.0.1:8000` 的 uvicorn（`qingsu.service` 守护）。**只有 HTTP 80 端口，没有域名、没有证书。**

仓库内只保留 `qingsu.apk` 一份安装包：此前另有一个中文名副本，md5 与之完全相同（纯属重复占仓库体积），2026-10-16 已删除。

> 本轮改动**已于 2026-10-15 23:15 上线**（后端 `server.py`、前端 `web/app.js`、安装包 `web/qingsu.apk` 三样都换了，服务已重启）。上线后从公网重新拉取做了四项独立验收，逐条结果见文末「线上部署」一节。历史脏数据也已在同日清理完毕。

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

### 外卖自律统计（真实事件流）

功勋榜那三颗数字以前是 HTML 里写死的 `5 次 / 3,850 / 1.1 斤`，服务端连一张记录表都没有——任何人打开都显示"5 次"。现在改成真实事件流：

- 新表 `takeout_events`，四种事件：`blocked`（门禁拦下）、`cancelled`（审核后主动退单）、`substitute`（采纳低卡平替）、`launched`（额度充足放行跳转）。
- 少摄入热量只累计 `substitute` 与 `cancelled` 这两种**算得出差额**的事件；`blocked` 上报时带的任何热量都被服务端强制归零，因为系统不知道你本来要点多少。
- 折算脂肪按 `7700 kcal ≈ 1 kg`，界面与回答里都写明这是折算不是实测。
- 没有事件时三颗就是 `0 次 / 0 / 0 斤`，称号显示"尚无记录"，不预先记功。

同类被清掉的写死数据：`本周外卖配额 剩余 1 次`（系统从来没有配额机制，改成"本周真实点单 N 次"）、`自制控油率 92%`（无来源，删）、`连续超标总富余 +580 kcal`（改为按每日超出部分真实累加）、图表的 `起点 70.0kg / 目标 60.0kg / 当前 69.2kg / 目标 450 kcal / 图例 110g·145g·45g`（全部绑真实档案）、`下行稳健`（改为按首末体重算出"已降 X 斤"）、`今日训练已完成！`（那其实是个还没按的打卡按钮，改成"记录今日训练打卡（按 220 kcal 计入）"）。

### 界面显示修复

实拍反馈的三处已修。顶栏窄屏下标题被挤成四行、右上档案胶囊文字竖排溢出：改为顶栏可换行、长文本走省略号。悬浮"下载App"按钮压住卡片文字：App 内直接隐藏这颗按钮（已经装着客户端了，不该再引导下载一次），网页版保留但给主内容留 140px 底部空间。`当前 140 斤 / 目标 undefined 斤`、`离目标体重还有 NaN 斤`：根因是服务端返回下划线字段而前端读驼峰，已在入口处显式映射，并补上"已达标"与"未设目标"两种文案。

### 身形目标与动作库
8 款：女 4（S型沙漏、修长轻盈、紧致力量、稳健脱脂）+ 男 4（倒三角、修长衣架子、饱满力量、啤酒肚专项）。每款一张内置 SVG 示意图（画的是理想形体，不是用户本人），驱动两件事：三宏量比例与热量缺口档位（420/500/+250/550 kcal），以及从 32 个动作里选出的那组 4 个。

### 周期身材照
提交体重 + 肚脐腰围（可选照片），服务端插一条 `body_cycles` 并生成一段报告。

- 照片原样存 `/uploads/` 供前后对照，**服务端从不调用任何图像识别，也不看像素**。
- 围度增减只在"上一次和这一次都有测量值"时才计算；注册时不采集腰围，所以第一次提交会写"待补围度"，而不是拿一个编造的基准算出"+7.0 cm"。
- "第 N 周期 (第 x-y 天)"里的天数是 `周期序号 × 7` 推算出来的字符串。**没有任何 7 天间隔校验**，一天提交五次就会得到五个周期。
- 报告说"训练动作进阶、饮食调配更新"只是文案：动作库和食谱不会因提交本表而改写，换方案要去【档案】里选身形。

### 问答顾问（三层，按顺序命中）

1. **先答你自己的真实记录**（`/api/ask`，登录态）。问"我多重""还能吃多少""今天吃了什么""练了没""净缺口""拦截了几次""喝水没""宏量目标""周期腰围"这类问题时，答案直接从你的流水表算出来，不联网、不调模型。以前问"我多重"只会拿到一段通用套话，而体重本来就躺在库里。
2. **答不上再联网**：抓必应国内版的自然搜索结果，返回标题、摘要与来源站点，并在回答开头标明"以下是联网查到的资料（由第三方网站提供，不是本系统的减脂建议）"。实测服务器到 `cn.bing.com`、`baike.baidu.com`、`www.baidu.com` 均 200（0.07~0.16 秒），`api.duckduckgo.com` 与 `zh.wikipedia.org` 不通，所以只走国内可达的那条。第三方标题与摘要在服务端就做了去标签 + HTML 转义，URL 也转义，避免把别人的网页内容当标签执行。
3. **联网失败就明说**：返回"联网查询没成功/没查到可用结果"，前端退回本地规则建议并标注"不含你的真实数据"。**任何一层都不编答案。**

本地规则库（不登录时的兜底）仍是纯关键词匹配，不调任何大模型、不需要 key，界面 5 颗预设问题各有专答。

限频：每用户每分钟 12 次联网查询，避免这个接口变成免费的公开代理。

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

本轮上线后再次逐字节比对：线上 `/app.js` md5 `618b697b6331e08fa50a7b34279feae8`、线上 `qingsu.apk` 内 `assets/app.js` 也是同一个 md5，与仓库源码一致。审计当时（改动前）线上三份前端与仓库也逐字节相同，说明"多端同步"这条一直是真的。

### 缓存：你打开的到底是不是刚部署的那版

后端在 `/`、`/u/{username}`、`/app.js`、`/style.css`、`/qr.svg`、`/qingsu.apk` 的响应上都加了 `Cache-Control: no-cache, must-revalidate`。在这之前这些响应**一个 `Cache-Control` 都没有**，浏览器按启发式长期缓存，于是出现过这种局面：服务器已经换成新版，老访问者的浏览器还在用缓存里的旧 `app.js`，甚至旧 APK。

首页还在出口前给三处引用挂上版本号（取自盘上文件的 mtime）：`src="app.js?v=…"`、`href="style.css?v=…"`、`href="/qingsu.apk?v=…"`。这样即使某个旧条目已经被缓存在浏览器里，URL 一变它就必须重新取。实测：`touch` 服务器上的 `qingsu.apk`（只动时间戳、内容 md5 仍是 `da0f54c0…`）之后，首页给出的下载链接立刻从 `?v=1792077189` 变成 `?v=1792079653`——**页面上那个下载按钮永远对应盘上当前那份包**。

版本号只在服务端改写，仓库里的 `index.html` 保持裸引用不动。原因是 APK 内的 assets 走 `file://` 加载，没有 HTTP 缓存这回事，所以**这次改动不需要重新打包**。

两个代价写在这，别当成免费的：

1. **全站不返回 304。** Starlette 的 `FileResponse` 只发 `ETag`/`Last-Modified`，并不处理 `If-None-Match`；nginx 那层是纯 `proxy_pass`，没开 `proxy_cache`。实测带 `If-None-Match` 请求 `/app.js` 与 `/qingsu.apk` 都照旧返回 200 全量。所以 `no-cache` 的落地成本是每次访问重传首页 69.5 KB + `app.js` 97.4 KB + `style.css` 38 KB ≈ 205 KB。要省掉它得自己实现条件请求（约二十行），本轮没做。
2. **改了 `app.js` 必须重新打 APK 才影响 App 用户。** 手机 App 的前端打包在安装包里，服务器再怎么更新都到不了已装的 App。这条是这轮审计里"多端同步"最容易踩的暗坑：网页版和 APK 版是两个独立分发渠道，只有当 `qingsu.apk` 内 `assets/app.js` 的 md5 与仓库一致时，两边才算同一版。


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

## 线上部署（已于 2026-10-15 23:15 执行）

下面这套命令本轮已照做并验收通过，留在这里是为了下次能一模一样复现，**顺序不能打乱**。**只动 qingsu 服务与 `/opt/qingsu/web` 下两个文件，不碰 nginx 配置，`latest.json` 与 `latest-extensions.json` 那两份既有清单不受影响。**

### 坑：Git Bash 下 `--scp` 会静默换路径

`remote_exec.py --scp` 调的是 PortableGit 自带的 scp.exe，它会把远程路径 `/opt/qingsu/server.py.new` 按 MSYS 规则当成本地路径处理（实测变成 `…/qoder-cn/bin/git/opt/qingsu/server.py.new` 然后报 upload failed）。必须关掉转换：

```bash
MSYS2_ARG_CONV_EXCL='*' MSYS_NO_PATHCONV=1 python remote_exec.py --scp server.py /opt/qingsu/server.py.new
```

而且**别把这条命令接 `| tail`**——那会让 `$?` 变成 `tail` 的退出码，实测能把失败的传输读成 `SCP_EXIT=0`。要拿真码就单独 `echo $?`，或用 `${PIPESTATUS[0]}`。同理别随手 `2>/dev/null`：本轮清理 SQL 第一次执行就是靠 `sqlite3 -encoding` 这个不存在的选项失败，而 stderr 被吞掉后只剩一个孤零零的退出码 1。

先量影响面（只读，不改任何东西）：

```bash
cd /d/RuanJian/JiaZhiSuXianApk
python remote_exec.py "sqlite3 /opt/qingsu/data/qingsu.db \"SELECT 'users='||count(*) FROM users; SELECT '假腰围weight='||count(*) FROM weight_logs WHERE waist_cm=78.0; SELECT '假腰围cycles='||count(*) FROM body_cycles WHERE waist_cm=78.0;\""
```

后端预检——先传到 `.new`，用服务器自己的 python3 编译，通过才允许覆盖现役文件：

```bash
python remote_exec.py --scp server.py /opt/qingsu/server.py.new
python remote_exec.py "cd /opt/qingsu && python3 -m py_compile server.py.new && echo COMPILE_OK"
```

备份现役，再落位、重启：

```bash
python remote_exec.py "cd /opt/qingsu && cp server.py server.py.bak-raudit && cp web/app.js web/app.js.bak-raudit && cp web/qingsu.apk web/qingsu.apk.bak-raudit"
python remote_exec.py "cd /opt/qingsu && mv -f server.py.new server.py"
python remote_exec.py --scp app/src/main/assets/app.js /opt/qingsu/web/app.js
python remote_exec.py --scp qingsu.apk /opt/qingsu/web/qingsu.apk
python remote_exec.py "systemctl restart qingsu; sleep 2; systemctl is-active qingsu"
```

（依赖 `%TEMP%\test_key.pem`，密钥不入库。`index.html` 与 `style.css` 本轮没改，不用传。）

**验收要重新从公网拉一遍，别复用上面任何输出**：

```bash
curl -s 'http://124.220.54.64/u/<img%20src=x%20onerror=alert(1)>' | grep -c '<img src=x'   # 必须是 0
curl -s 'http://124.220.54.64/u/<img%20src=x%20onerror=alert(1)>' | grep -c '&lt;img'        # 必须 ≥1
curl -s http://124.220.54.64/app.js | grep -c 'reportWriteFailure'                          # 必须是 1（线上前端已是新版）
curl -s --max-time 180 -o /tmp/chk.apk http://124.220.54.64/qingsu.apk && md5sum /tmp/chk.apk  # 须等于 da0f54c0fc38da7e9e3209904fbc7494
```

第 4 条要等十几秒——这台机只有 0.33 MB/s。

任一条不达标就回滚：

```bash
python remote_exec.py "cd /opt/qingsu && cp server.py.bak-raudit server.py && cp web/app.js.bak-raudit web/app.js && cp web/qingsu.apk.bak-raudit web/qingsu.apk && systemctl restart qingsu"
```

**历史脏数据（本轮已清理）**：改了代码不会让库里已存在的伪造 `waist_cm=78.0` 消失，所以后端上线后必须再跑一次数据清理，否则老用户提交周期照时照样算出假的围度增减。本轮的执行结果记在本节末尾。清理脚本如下，**必须在部署新版后端之后跑**，顺序反了会白清一遍。

### 清理注册时伪造的 78cm 腰围

先备份库（用 sqlite3 的 `.backup` 而不是 `cp`，服务在写的时候直接拷文件可能拷到半截页）：

```bash
python remote_exec.py "sqlite3 /opt/qingsu/data/qingsu.db '.backup /opt/qingsu/data/qingsu.db.bak-raudit' && ls -l /opt/qingsu/data/"
```

**判据要先看清，不能拿 `WHERE waist_cm=78.0` 一把梭**——78 cm 是一个完全可能的真实腰围。只清"注册那一刻由服务端自动生成"的行，用账号创建时间戳做身份指纹：

```sql
-- 1) 先看命中范围（应远小于"所有等于78的行"）
SELECT 'wl_注册生成='||count(*) FROM weight_logs
 WHERE waist_cm=78.0 AND (user_id, created_at) IN (SELECT id, created_at FROM users);
SELECT 'wl_真实78='||count(*) FROM weight_logs
 WHERE waist_cm=78.0 AND (user_id, created_at) NOT IN (SELECT id, created_at FROM users);
SELECT 'bc1_注册生成='||count(*) FROM body_cycles WHERE cycle_num=1 AND waist_cm=78.0;

-- 2) 归零：注册那条体重记录
UPDATE weight_logs SET waist_cm=0
 WHERE waist_cm=78.0 AND (user_id, created_at) IN (SELECT id, created_at FROM users);

-- 3) 归零 + 对齐新版口径：第 1 周期
UPDATE body_cycles SET waist_cm=0, tone_score='待首次打卡'
 WHERE cycle_num=1 AND waist_cm=78.0;

-- 4) 被这个假基准污染过的后续周期报告：围度结论标注为无效
UPDATE body_cycles
   SET tone_score='历史数据（围度基准无效）',
       ai_report='<p style="color:#B45309;">⚠️ 本次对比的上一周期腰围为系统早期预填值，该条围度结论无效，请以最新一次提交为准。</p>' || ai_report
 WHERE (user_id, cycle_num) IN (
     SELECT c2.user_id, c2.cycle_num
       FROM body_cycles c1
       JOIN body_cycles c2 ON c2.user_id = c1.user_id AND c2.cycle_num = c1.cycle_num + 1
      WHERE c1.cycle_num = 1 AND c1.waist_cm = 78.0);
```

第 4 条用的是子查询而不是 `UPDATE ... FROM`，因为 `UPDATE...FROM` 要 SQLite 3.33+，服务器上的 sqlite3 版本没量过，别赌。同理 `.backup` / `.restore` 要 3.27+，跑第一句时若报 `unknown command`，就改用 `systemctl stop qingsu && cp /opt/qingsu/data/qingsu.db /opt/qingsu/data/qingsu.db.bak-raudit && systemctl start qingsu`。

第 4 条要在第 3 条**之前**跑（它靠 `c1.waist_cm=78.0` 找受害者，基准被归零后就找不到了）。正确顺序：备份 → 查命中范围 → 第 4 条 → 第 3 条 → 第 2 条。

跑完独立复核，三条都必须成立：

```sql
SELECT '残留bc1='||count(*) FROM body_cycles WHERE cycle_num=1 AND waist_cm=78.0;  -- 必须 0
SELECT '残留wl='||count(*) FROM weight_logs
 WHERE waist_cm=78.0 AND (user_id, created_at) IN (SELECT id, created_at FROM users);  -- 必须 0
SELECT 'users='||count(*) FROM users;   -- 与清理前一致
SELECT 'food='||count(*) FROM food_logs; -- 与清理前一致（本清理不该碰饮食）
```

真实测过 78cm 的用户（第 1 条查询里的 `wl_真实78`）不该被动过，复核时他们的值仍应是 78.0。回滚只需要一句：`sqlite3 /opt/qingsu/data/qingsu.db '.restore /opt/qingsu/data/qingsu.db.bak-raudit'`（服务需先 `systemctl stop qingsu`）。

### 第二轮部署记录（2026-10-16 00:50）

上线五样：`server.py`、`web/app.js`、`web/index.html`、`web/style.css`、`web/qingsu.apk`。现役文件先各自备份成 `*.bak-r2`，后端仍走"传 `.new` → 服务器 python3 编译 → 才 `mv`"。

公网侧独立验收：首页里 `3,850`、`>5 次<`、`自制控油率`、`剩余 1 次`、`+580 kcal`、`69.2 kg`、`今日训练已完成` 残留**全部为 0**；`id="medal-tag"` 与 `id="chart-trend-tag"` 各 1 次；`app.js?v=` 与 `qingsu.apk?v=` 仍在；`/app.js` md5 `dfe67286…`、线上包 md5 `c3fee3c4…` 均与仓库一致；`/api/public/dashboard?username=tiangang` 已带 `takeout_stats`（全 0，因为该用户确实没有事件）。

端到端另开临时账号 `_selftest_r16` 真跑一遍：问"我多重"返回 `source=data` 与真实 150 斤、差 20 斤；上报三条事件后统计为 `intercepted=2 / cal_saved=1670 / fat_jin=0.4`；问"量子计算是什么"走联网拿到 4 条带来源的结果。测完按 `user_id` 清干净，复核 `users=2`、`takeout_events=0`，没留测试数据。

### 第一轮部署记录（2026-10-15 23:15）

`.backup` 先落了一份 45056 字节的 `qingsu.db.bak-raudit`，然后在 `BEGIN…COMMIT` 里跑完三条 UPDATE。实际影响行数：

| 步骤 | 命中 |
| --- | --- |
| 第 4 条（标注被假基准污染的后续周期报告） | 0 行——库里只有 2 条 `cycle_num=1`，还没有第二次提交 |
| 第 3 条（第 1 周期腰围归零 + 评级改"待首次打卡"） | 2 行 |
| 第 2 条（注册生成的体重记录腰围归零） | 2 行 |

复核四条全过：`残留bc1=0`、`残留wl=0`，且 `users=2 / food=1 / weight=2 / cycles=2` 与清理前完全一致（本清理不该碰饮食和记录条数）。再从公网 API 侧确认，不看数据库只看接口：`tiangang` 与 `木木` 的 `latest_cycle.waist_cm` 均为 `0.0`、`tone_score` 均为"待首次打卡"。

线上四项验收同时通过：`/u/<img src=x onerror=alert(1)>` 裸标签 0 次、`&lt;img` 出现 1 次；`/app.js` md5 与仓库一致且含 `reportWriteFailure`(7 处)、`dashboardLoaded`(4 处) 与平台期专答；`/qingsu.apk` 下载的包 5,588,679 字节、md5 `da0f54c0…`，用 aapt 解其清单可见 `E: queries` 带 `com.sankuai.meituan`；真实用户 `tiangang` 的 7 天缺口序列 `[0,0,0,0,0,0,0]`（改动前这里今天那根会是 1511）。

现存两个账号是 `tiangang`（2026-10-15 18:20 注册）和 `木木`（18:40 注册），共 1 条饮食记录——也就是说这个部署还没有真实使用量，上面这些改动对用户侧的实际影响面为零。

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
10. 顾问的三层里**没有一层是大模型**：第 1 层查你自己的流水表，第 2 层抓必应搜索结果的标题与摘要（是检索不是生成），第 3 层是本地关键词规则。别把它宣传成 AI 对话能力。
11. 联网查询依赖必应国内版可访问性与页面结构，对方改版就会取不到结果；那种情况返回"没查到"，不会编。
12. `takeout_events` 是本轮新建的表，老用户此前的拦截行为无从追溯，统计从 2026-10-16 起才开始累积。

---

## 变更记录

### 2026-10-16 假数据与体验轮（用户实拍反馈触发）

上一轮我只通读了 `app.js` 与 `server.py`，**没有通读 `index.html` 那 1100 行**，于是漏掉了整类问题：写死在 HTML 里的统计数字。用户拿截图指出"没拦截过却显示拦截 5 次"后，把审计改成可执行的自动检查，一次性扫出 **15 处 JS 从不赋值的永久假数据**与 **32 处加载前会闪的占位假数**。

- 新增 `takeout_events` 表与 `POST /api/takeout/event`，功勋榜三颗改为真实聚合；`blocked` 的热量强制归零，没有记录就是 0。
- 新增 `POST /api/ask`：先查用户自己的流水回答，答不上再抓必应国内版并给来源，联网失败明说"没查到"；每用户每分钟 12 次限频；第三方标题/摘要/URL 全部去标签并转义。
- 修 `applyDashboardData` 的字段映射（服务端下划线 → 前端驼峰），连带修掉 `目标 undefined 斤`、`离目标还有 NaN 斤`、男性用户身材卡片退回女性第一款、`saveProfileSilent` 静默丢字段。
- 修三处界面遮挡；App 内隐藏悬浮下载入口。
- "坚持下单"以前只弹一句"已记录超标热量并追加加练"而什么都没记，现在真的按估算热量记一笔，并明说加练不会自动出现。
- 训练打卡按钮不再写"今日训练已完成"。
- 回归台从 36 条扩到 **122 条**（后端 63 + 前端 59），改动前那版分别红 14 与 29 条。新增的静态审计判据会检查"界面里含数字的元素是否都被 JS 绑定、假数黑名单是否复活"。
- 过程中三次踩到同一类坑并当场修正：`FileResponse` stub 不读文件内容导致"页面不含某串"恒真；`appendChild` 是空操作导致气泡断言读不到内容；`createElement` 复用同一对象导致三条气泡内容相同。**mock 不忠实比没有 mock 更危险**，因为它给出的是绿色的假结论。

### 2026-10-15 审计轮
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
