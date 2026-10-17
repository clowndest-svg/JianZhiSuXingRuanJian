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

（部署后补：线上 `min_build` 状态、清单与包指纹、公网回读、测试账号清理。）

## 6. 仍未覆盖（不写成通过）

- **线上没抬门**。`min_build` 停在 0，等机主在 vivo 上装完 22 再抬。所以"已装的 1.8.3 在真人手机上被挡"这一格本轮没有实拍证据；MuMu 上也只验了新包侧。
- 抬门后 `verify_live.py` 会扮成最新版（已带 `X-App-Build`），但**别的第三方调用方**（脚本、外部集成）如果存在，会被当成旧包挡掉——目前仓库里没有这类调用方，线上日志也没查过。
- 旧包被挡时屏上具体显示什么（403 走的是旧版自己的错误处理，很可能是"加载失败"而不是"请更新"）没验；旧包唯一像样的提示是它自带的启动更新弹窗。
- vivo 真机仍未连，3D 与新图标在真实 GPU/高密度屏上的表现依旧未知。
