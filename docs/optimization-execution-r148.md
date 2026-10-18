# r148 执行记录：顶栏重排 + 用户名展示改成昵称

机主一句话里塞了两件事：「顶部这个排版一上一下一点也不好看」「这个用户名的展示方式好丑哦
不要这样展示哦弄好看些哦」，附一张 vivo 00:49 的实拍，还自己用红框把两处圈了出来。
这一版就是照着那两个红框改的。

## 1. 红框里到底是哪几件事

把那张截图按像素读了一遍（1080 宽 / 3 倍密度 = **360 CSS 宽**，这是真实目标档位）：

1. 品牌块（图标 + 轻塑 + 副标题）在**左上**，账号入口那颗胶囊在**右中偏下**——
   两者不在一条线上，中间空出一大块白。这就是「一上一下」。
2. 账号入口里面是「👤 蓝色小人 emoji + 蓝字 tiangang + 一圈描边」。这就是「用户名那样展示好丑」。
3. 再下面还有一条整宽的绿色胶囊「165cm · 140斤 · 👑经典倒三角 · 铠甲腹肌 [调整]」，
   顶栏因此是三层。
4. 右边那颗齿轮点的和上面那条档案胶囊是**同一个** `openProfileModal()`。

## 2. 改了什么

- **档案摘要挂进品牌块当第二行**：`.brand-profile` 无边框无底色，整行可点，尾部一个 ✎。
  顶栏从三层压成两层，右侧不再悬空。
- **账号入口改成头像圆点 + 深色昵称**：有头像显示头像，没头像用昵称首字做字母章。
  取首字走 `Array.from`——昵称是 emoji 开头时按下标取会切出半个码元，显示成乱码。
  一个字符都没有才落回品牌首字「轻」。点它直接进个人中心。
- **齿轮删掉**：重复入口，窄屏上还白占 40px。顶栏只留排版切换那颗（网页版需要）。
- **顶栏显示昵称而不是登录名**：新增 `displayName(u)`（昵称优先，退回登录名），
  登录、恢复会话、刷大屏三处统一走它；`/api/account` 回读到新昵称时顶栏一起重画，
  不用重开 App 才换名字。登录成功那句提示语原来也直接拼 `data.username`，一起改掉。

## 3. 窄屏这一档返工了一轮

第一版按「账号入口不许收缩」改（`flex:0 0 auto`），因为更早的实测里它被长标题压到只剩
padding 的 16px。结果反向翻车：393 档它把品牌行挤掉，档案摘要截成「170cm · 160斤 · …」。
而 `≤380` 那条 `flex-wrap` 又把整颗 chip 甩到第二行——正是机主指着的「一上一下」。

现在的口径：**可收缩 + 92px 下限 + 窄屏不换行**，昵称超长由 `.account-name` 自己出省略号。
上限用 `min(240px, 60vw)` 而不是百分比——百分比的参照是工具组自身宽度，
那是个 shrink-to-fit 的循环量，各引擎算出来不一样。

下限差点白写：文件末尾那组「右侧按钮组」覆盖规则里混着 `.account-chip`，
它的 `min-width:0` 隔着一千行把上面的 92px 盖掉了。**只看自己那条规则是查不出来的**，
补了一条按选择器分词扫全表的判据（`_css_rules` + 命中 `.account-chip` 的块不许出现 `min-width: 0`）。

## 4. 判据

后端 435 条、前端 252 条、集成 28 条、AI 契约 6 条，全绿。这一版新增：

| 判据 | 钉的是 |
| --- | --- |
| 顶栏账号入口可收缩但有下限 | `flex: 0 1 auto` + `min-width: 92px` 都在 `.account-chip` 块里 |
| 账号入口宽度上限用视口单位而不是自指百分比 | 有 `min(240px, 60vw)`、没有 `max-width: 52%` |
| 账号入口的收缩下限没被后面的覆盖组抹掉 | 全表扫选择器分词，命中 `.account-chip` 的块不许写 `min-width: 0` |
| 顶栏只剩排版切换一颗图标按钮 | header 段里 `class="header-icon-btn"` 恰好 1 个 |
| 窄屏不再把账号入口挤到品牌下面一行 | features.css 里 `.header-row-1{flex-wrap:wrap}` 与 `.header-tools{flex:1 1 100%` 必须不存在 |
| 顶栏名字取昵称，没有昵称才退回登录名 | 在 vm 沙箱里**真的调用** `displayName()` 比对返回值 |
| 登录态不再把登录名直接写进顶栏 | `updateUserUI(state.user.username)` 全库为 0 |
| 登录提示语也叫昵称而不是登录名 | 提示语模板里是 `escapeHtml(displayName(data))` |
| 个人中心回读到新昵称时顶栏跟着重画 | features.js 里有 `updateUserUI(displayName(state.user))` |

标定：把三处契约逐条改回旧写法（chip 不许收缩 / 加回齿轮 / 加回窄屏换行），
判据红 4 条且**只有这 4 条**红；再把 `.account-chip` 塞回末尾那组覆盖规则，
级联那条单独红。改完原样还原，两套判据回到 435/252 全绿。

顺带修掉一处判据本身的坑：`--mutant=HEAD` 这一档对 r148 的判据**不适用**——
HEAD 还是 r147 的 HTML，没有 `.brand-profile`，几条老判据直接
`ValueError: substring not found` 崩在解析阶段。反样本只能拿当前文件做定向变异。

## 5. 真机（MuMu 127.0.0.1:16384，正式包 versionCode 31）

`DeviceSmokeTest` 4 个用例全过（`Time: 54.661`）。顶栏度量原样落档：

- **桌面 1280**（`header-desktop.json`）：
  `topDiff 0`、`chipH 32`、`iconH 34`、`extraIcons 0`、`nameText 小田`、
  圆点 `26×26` 正圆、`nameLines 1`、`profLeft 142 == titleLeft 142`、
  `hdrH 162`、`tiers 3`、右侧留白 `984-968=16`、`overflow false`。
- **手机 320**（`header-narrow.json`，先 `applyViewMode('mobile')` 真切到手机排版再量）：
  `rowDiff 0`（账号入口和品牌图标同一行中线，也就是没再「一上一下」）、
  `chipPct 29`（chip 只占视口 29%，没压住品牌）、`profH 16`、`profText 45`
  （DOM 里是整条，省略号只是显示层）、`overflow false`。
- **定位这一轮真的给了 fix**：`location.txt` 记的是 `ok:28.24,112.94`，
  走的是城市落库那条分支（`matched=true`、城市名长度 ≥2 都断言过），不是 err 分支。

截图：`header-desktop.png`（1280）、`header-393.png`（手机常见档）、`header-320.png`（最窄档）。
三张里顶栏都是「品牌 + 档案第二行 …… 圆点 + 小田」一行排完，齿轮已不在。

**网页版那一档单独补测了**：App 里 `#btn-header-download` 被隐藏，网页版窄屏顶栏是
「品牌 + 下载App + 账号入口」三件，比我拍到的两档更挤。窄屏矩阵里每档把那颗按钮
真的放回 DOM 再量一遍：320/360/380/412 四档 `scrollWidth <= innerWidth` 且
账号入口仍与品牌图标同一行中线（夹具这个账号没有昵称，chip 里是 17 个字符的登录名，
是最宽的一种）。`releaseUserJourney` 单跑 `OK (1 test)` 34.6 秒。

## 6. 线上对账与清理

- 归档 `release-r148.tar`（6,758,400 字节，sha256 `e880a9d6…`）本机与服务器双向核对一致；
  解出的 `web/qingsu.apk` 与本机 `qingsu.apk` 同为 5,355,557 字节、sha256 `f612f398…`。
- `deploy.py --stage /opt/qingsu/releases/r148 --revision e578848fcce76958510173d440bb6fe0369856f1`
  成功，回退快照 `/opt/qingsu/backups/release-20261018-044546`。
- 服务器内网 `verify_live.py` **8 项通过**。
- 公网独立复核（从本机发请求，不看部署日志）：
  `/health/ready` 报 `release=r148`、`source_revision` 等于本次提交、`builds={"31":14}`；
  `/version.json` 的 `version_code/min_version_code=31`、`size=5355557`、
  `md5=0aa0bb1e…`、`sha256=f612f398…` 与本机 APK 和公网回读的 APK 三处一致；
  `/api/account` 未登录 401；`/api/account/recovery-status` 免登录 200 且照实报 `mail=down`；
  线上首页 `class="account-chip"` 在、`header-icon-btn` 恰好 1 颗、header 段里没有 ⚙️；
  线上 `app.js` 有 `function displayName(u)`、提示语走 `displayName(data)`、
  `updateUserUI(state.user.username)` 为 0；线上 `style.css` 有 `min-width: 92px`
  且末尾覆盖组里不再有 `.account-chip`；线上 `features.css` 没有 `.header-row-1{flex-wrap:wrap}`；
  线上 `features.js` 有 `updateUserUI(displayName(state.user))`。
- 测试账号：只删今天建的 31 个 `uqa/usbqa` 账号（id 152–182，删前逐条断言过
  「恰好 31 个、首 152 尾 182、2 和 3 不在集内」），连带 19 张带 `user_id` 的子表共 240 行。
  删后：库里只剩 id 2（tiangang）和 id 3（木木），真实账号各表行数前后一致（合计 33 行），
  无孤儿行，`foreign_key_check` 0 条，`integrity_check` ok，`email_codes` 本来就 0 行。

## 7. 抬门仍然要机主亲手做

线上 `min_build` 还停在 0（`/health/ready` 里 `build_override=true`）。装完 1.9.9（31）之后
要执行 `python3 /opt/qingsu/set-min-build.py 31`，否则旧版客户端不会被挡。
这一版没抬门，所以"已装的 1.9.8 在真人手机上被挡"这一格依旧没有实拍证据。

## 8. 没做到 / 别当成已通过

- **vivo 真机没连**：320/393 是 MuMu 上把 WebView 窗口压到该宽度量的，
  MuMu 镜像缺 emoji 字体（截图里 tab 图标是方框），厂商浏览器的字重渲染没看过。
- 320 档档案摘要在**显示层**仍是省略号截断的，机主那条「165cm · 140斤 · 经典倒三角 · 铠甲腹肌」
  在 320 上放不下——这是取舍，不是没做；要看全的点开就是。
- 「食谱按 AI 定制」这版仍未做，这轮只做了内置菜品库 + 忌口的确定性过滤与冲突标注。
- 邮箱找回密码的 SMTP 账号还没有，通道状态照实报 `mail=down`。
