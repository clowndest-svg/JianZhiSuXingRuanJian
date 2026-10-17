# r139 执行记录：强制更新门 + 换图标

日期：2026-10-17。版本：versionCode 22 / 1.9.0。承接 r138。

## 1. 要解决的问题

机主的要求：线上 APK 一更新，旧版 App 就不能再用，必须更新完才能继续。

先量了一场地基，因为这类功能的成败不在"有没有弹窗"，而在**服务端能不能认出调用方是哪一版**：

| 实测项 | 结果 | 后果 |
|---|---|---|
| 自定义 WebView UA | 全仓 `setUserAgentString` 命中 0 | 旧包在 HTTP 层没有任何身份特征 |
| 旧包 `app.js` | 不发任何版本头 | 缺头本身就是可用的判据 |
| 已有更新逻辑 | `UpdateManager.decide()` 只弹建议式对话框，`setCancelable(true)` + "这次不更新" | 拦不住任何人 |
| `version.json` | 有 version_code 等 7 个字段，**没有 min_version_code** | 需要新增策略字段 |
| CORS | `allow_headers=["*"]`，且鉴权请求本来就因 `Authorization` 走预检 | 加自定义头不新增往返 |
| 本地未同步数据 | 无（`pendingWrites` 只是请求去重 Map） | 硬拦不会吞用户记录，才敢做 |

关键结论：**旧包的代码已经装在用户手机上，改不动**。所以对已装的 1.8.3 只能做到"让它取不到数据"，做不到"给它一块体面的强更页"——体面的门只有装了新包之后才存在。策略因此写成"缺 `X-App-Build` 即按太旧处理"，而不是"头低于最小值才拒绝"：后者对旧包完全无效。

## 2. 落地形态

- **客户端**（`app.js`）：`const APP_BUILD = 22` + 一层 `window.fetch` 包装，只对 `/api/` 业务请求加头，收到 403 且 `code==='update_required'` 时整屏盖住。包装只装一处，覆盖 13 个调用点（`app.js` 12 + `features.js` 1）。
- **服务端**（`server.py`）：`update_gate()` 挂在既有 `response_policy` 中间件里（CORS 在最外层，预检不会被挡）。403 体里带 `min_build`/`your_build`/`latest{version_code,version_name,apk_url,size}`，文案里的版本号取自清单。
- **豁免**：`/api/public/dashboard`、`/api/public/charts`、`/api/cheer`。挡来看监督大屏的人没有任何意义，且访客可能拿着部署前缓存的旧 `app.js`。前后端各写一份清单，判据逐条核对两边一致。
- **刹车**：`DB_DIR/min_build` 文件在时以它为准，否则回落到清单的 `min_version_code`（默认=最新版，即发版即抬门）。`scripts/set-min-build.py 0|22|auto|show`，改完独立回读 `/health/ready` 核对；`/health/ready` 同时上报 `min_build`、`build_override`、`gate.blocked` 和**还在调用的构建号分布**（抬门前先看得见会被挡的是谁）。
- **构建号同源**：`make_version_json.py` 从 `build.gradle` 同步 `APP_BUILD`，并打开 `qingsu.apk` 回查包内那份 `assets/app.js` 的常量——清单指纹对得上但资产常量是上一版，正是"先发版后改常量"的顺序坑。

## 3. 图标

机主给了新图（黑底 + 银色身形剪影 + 绿色度量环与新芽）。八份产物改由 `scripts/make-icons.py` 一次生成：五档密度 `ic_launcher.png` + `ic_launcher_round.png`、自适应前景（artwork 占画布 88%，圆形遮罩切不到人物）、单色层（按明度出轮廓，深色底变透明）、网页 `app-icon.png` 与 `manifest.webmanifest`。旧的矢量 `ic_launcher_foreground.xml`/`ic_launcher_monochrome.xml` 一并删除——同名资源同时存在于 `drawable/` 与 `drawable-nodpi/` 最容易留下"改了没生效"。自适应背景色从 artwork 四角取样（`#000000`），避免图标外圈出现第二种黑。

## 4. 判据与标定

判据 **后端 310（+15）+ 前端 237（+12）+ 真实框架集成 26（+1）+ AI 语义契约 6**，全绿。

- 反样本 `--mutant=HEAD`（改动前的 r138）：后端红 **7** 条（自报构建号、构建号与 gradle 同源、豁免清单两边一致、缺头按太旧、门只管 /api/、健康检查可见、网页清单指向的图标有路由），前端红 **8** 条（遮罩出现、写清当前/最低版本、体积现算、App 内给下载、体积缺失显示未知、网页版只给刷新等）。
- **四条针对门本身的变异**（改完跑真实中间件用例，全部被抓）：缺头当成很新的号 → FAIL；访客接口也一起挡 → FAIL；运维刹车不生效 → FAIL；门扩大到非 `/api/` → FAIL。
- 真机（MuMu，正式包 versionCode 22）：`clientIdentifiesItselfAndBlocksTheScreen` `OK (1 test)`——页面自报构建号 == `PackageManager.versionCode`、真 Blink 上的接口分类正确、遮罩 `offsetHeight>=innerHeight` 且 `elementFromPoint` 命中的是遮罩本身（挡得住底下的按钮）。完整回归 `releaseUserJourney` `OK (1 test)`。
- 证据：`docs/release-evidence-2026-10-17/mumu-update-wall.png`（真机强更屏）、`mumu-launcher-icon.png`（桌面新图标）。

有一条判据我先写错、被自己抓住：设备测试里我把 fetch 记录器装在 App 包装层**之后**，看到的是加头之前的参数，断言当场红。记录器位置决定它能不能证明那一步——最后把这条改成"只有设备能证的事"（真引擎上的接口分类），把"头真的带上了"交给前端台（记录器在包装层下游，记的就是 fetch 收到的最终参数）。

## 5. 上线与对账

- 部署：`{"deployed":"r139","backup":"/opt/qingsu/backups/release-20261017-190252","source_revision":"5a5ce1f6c5d5…"}`。
- `/health/ready` 回读 `r139` + 同一提交号，`min_build=0`、`build_override=true`、`gate.blocked=0`。
- **门在线上确实在跑**：跑完发布自检后 `gate.builds` 是 `{"22":14}`——这个计数只有新代码会写。抬门之前先看得见"还有谁在调用"，这条设计兑现了。
- 清单：`version_code 22 / 1.9.0`、`min_version_code 22`、`size 5941497`、`md5 6d5ccc92`、`sha256 e49dcbd0…`，与仓库那份逐字节一致。
- 包：公网下回来的 `qingsu.apk` SHA-256 与本地、与清单三处相同（`e49dcbd0…`）。
- 资产：`app.js`、`body3d.js`、`app-icon.png`、`vendor/three.module.js`、`models/cesium_man.glb`、`exercise_poses.json` 六个线上 SHA-256 逐个 MATCH；归档两端 MD5 一致（`a64d046c…`）。
- `verify_live.py` 8 项通过，其中新增一项 `update gate min_build=0 override=True blocked=0`。
- 测试账号：只删 id 99（`usbqa1792234654569`，本轮 MuMu 回归建的），删前按 18 张带 `user_id` 的表逐一断言，删后 `foreign_key_check` 0 条、真实账号（tiangang、木木）各表行数前后一致、`integrity_check` ok。

## 6. 线上自查抓到的一个真 bug（判据形状值得记）

部署完照例逐个 URL 回读，发现 **`/app-icon.png` 返 500**：`extension_asset` 里那张按扩展名取 MIME 的表只有 js/css/svg/webmanifest/json，没有 png——路由注册了、文件也上传了，请求进来才 KeyError。

我那条「静态件都有显式公网路由」的判据是绿的：它核的是源码里有没有 `@app.get("/app-icon.png")` 这个串，**证明的是注册，不是服务**。这类形状（注册在、文件在、类型没登记）静态判据永远看不见。

补了两层：

- 集成判据 `test_public_static_assets_really_serve`：把十件公网静态件真的 GET 一遍，  钉 200 与 content-type 前缀。**改之前它当场红**（500），改完绿——这条判据是被这个 bug 挣来的。
- 启动校验：扩展名没登记 MIME 就在 import 时抛 `RuntimeError`，不留到用户请求。  变异标定：从表里删掉 `png` → 启动即炸（ERROR）；只关掉启动校验 → 服务照常 200（等价变异，如实记）。

- 同一批自查里还抓到 **`set-min-build.py show` 只回退出码、一个字不打印**：第一次在服务器上跑它，文件在、EXIT=0、屏幕上什么都没有。判据补了一条真跑子进程、要求 stdout 是含三个字段的 JSON；把 show 改回直接调 `live()` 当场红。修好后线上打印 `{override:"0", manifest_min_version_code:22, effective_min_build_live:0, gate.builds:{"22":15,"0":2}}`——那两个 `"0"` 就是本轮无头的探针请求，说明"谁还在用旧形状调用"真的看得见。

重发一次：`{"deployed":"r139b","backup":"/opt/qingsu/backups/release-20261017-191136","source_revision":"e686c2ea7152…"}`，归档两端 MD5 一致（`40fd48ad…`），`/app-icon.png` 现在 200 / image/png / 214,919 字节且 SHA-256 与仓库一致；`verify_live.py` 8 项通过，库里只剩 `tiangang`、`木木`。APK 没动（图标 500 只影响网页侧），所以 `qingsu.apk` 与 `version.json` 沿用上一次的对账结果。
## 7. 仍未覆盖（不写成通过）

- **线上没抬门**。`min_build` 停在 0，等机主在 vivo 上装完 22 再抬。所以"已装的 1.8.3 在真人手机上被挡"这一格本轮没有实拍证据；MuMu 上也只验了新包侧。
- 抬门后 `verify_live.py` 会扮成最新版（已带 `X-App-Build`），但**别的第三方调用方**（脚本、外部集成）如果存在，会被当成旧包挡掉——目前仓库里没有这类调用方，线上日志也没查过。
- 旧包被挡时屏上具体显示什么（403 走的是旧版自己的错误处理，很可能是"加载失败"而不是"请更新"）没验；旧包唯一像样的提示是它自带的启动更新弹窗。
- **判据盲区仍在**：「路由注册了」和「请求进得来」是两件事，这次靠人工逐个 URL 回读才发现。十件静态件已进集成判据，但**带参数的路由与子目录白名单**（`/vendor/{name}`、`/models/{name}`）仍只核注册，没核真取。
- vivo 真机仍未连，3D 与新图标在真实 GPU/高密度屏上的表现依旧未知。
