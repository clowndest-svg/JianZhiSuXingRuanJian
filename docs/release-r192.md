# r192 / 2.4.3（76）：跨进程实时投递就绪与首屏/CSP 报告模式

2026-11-06（UTC+8）。本轮把优化方案里最后两项"没做也没验证"的工程项落地：**C07 WebSocket 与通话状态的跨进程化**、**C11 首屏实测 + CSP 报告模式**，并修掉两处判据自身的漏洞。生产仍是单 worker，正式 CSP 仍未开——这两条是边界，不是遗漏。

目标：让"消息互达、呼叫互达、统一撤销"这三件事在两个进程下变成有实测证据的能力，而不是等真加 workers 时才发现只能单进程；同时把首屏体积/重复请求和 CSP 能不能转正，都变成有数可看的问题。本轮不改动产品入口，旧客户端完全兼容。

## 实现范围

| 关联 | 本轮行为 |
| --- | --- |
| 私信实时投递 | `_push` 先投本进程连接，再经 Redis 频道转发给其它进程；订阅端丢掉本进程自己发出的那一条，同一条连接不会收到两次 |
| 在线判定 | 在线键带 worker 身份（45 秒 TTL），worker 心跳进有序集合（90 秒）；断开只删自己那份，聚合键要确认别的 worker 都不再持有才删 |
| 通话忙线 | 通话与每人一条忙线位存 Redis，两个忙线位用一条 Lua 一起占；占位前检查持有那通电话的 worker 是否还在心跳，停心跳即回收残骸 |
| 统一撤销 | 退出/改密/恢复口令广播控制帧，按会话哈希精确关闭各进程连接；后台写库的封号靠"以库为准"的空闲检查兜底 |
| 降级可见 | Redis 答不上来时逐项退回进程内行为，`/health/ready` 报 `chat.fanout=local-only` 与 `chat.reason`，不谎报在线 |
| 首屏 | 真 Chromium + CDP 弱网/降速实测关键资源、请求数、LCP/CLS/长任务；抓出并修掉首屏两次 `/api/habits`，请求 26→25 |
| CSP | 默认 `Content-Security-Policy-Report-Only` + `POST /csp-report` 回收 + `/health/ready` 的 `csp`；转正要过两道实测门槛（内联处理器清零、`would_block=0`），`QINGSU_CSP_ENFORCE=1` 只代表请求 |

## 实现边界（不要按"已完成扩容/已收紧"理解）

- **生产仍是单 worker。** systemd 的 uvicorn 参数没动。加 `--workers` 还差 7 项前置（SQLite 单写者的锁竞争与混合负载实测、本机磁盘上的 uploads/缩略图/备份、空闲检查频率的两端代价、`chat.fanout != redis` 的告警与恢复通知、反压计数 `chat.dropped`/`chat.oversize`、TURN 并发预算、发布后按 worker 分开回读），逐条写在运维手册里。
- **正式 CSP 没开。** 内联事件处理器实测 186 处（从真要下发的那份 `index.html` 数），`script-src` 还离不开 `'unsafe-inline'`；报告窗口里也已经有"转正后会被拦"的条目。CSP 当前只覆盖经 HTTPS 下发的 H5：APK 的本地 assets 由 WebView 直接加载，不经过本站中间件，那一侧响应里没有 CSP 头。
- 本轮没有声称发现任何 XSS，也没有把"没报告出违规"说成"没有漏洞"。
- 跨进程判据依赖 Redis：没有 Redis 时记为 25 条跳过而不是通过；CI 声明了 Redis 却连不上直接判红。

## 验证与发布记录

开发验证（本机，Redis 在场）：`tests/test_multiprocess.py` 25 条跨进程判据全绿——两个独立 uvicorn 进程、两条真 WebSocket，覆盖消息互达、同进程不重复、跨进程呼叫/拒绝/再呼叫不残留忙线、在线不被别的 worker 误删、统一撤销 0.03 秒内两个进程同时关闭、以库为准的封号检查、真 kill 进程后的忙线回收、Redis 掉线时的诚实降级，另加一条"实跑条数与声明条数一致"的自证。`tests/test_content_security.py` 24 条、`tests/csp-report-browser.mjs` 11 条、`tests/frontend-firstscreen.mjs` 11 条全绿；首屏实测（收尾在最终代码上单跑复验）关键资源 856,552 字节、请求 25 个、LCP 844ms、CLS 0.0002、弱网 4× 降速长任务 2 条（最长 448ms）；改动前那次实测是 856,152 字节 / 26 个请求 / LCP 1064ms / 长任务 3 条（最长 483ms），两次都留在这句话里，避免只报好看的那个。

判据有效性（变异在副本上跑，不破坏施工工作区）：C07 七个变异、CSP 十一个变异全部被抓到。其中两次是"变异没被抓到"反过来暴露判据本身的漏洞，都已补齐并复验——把 A、B 放在同一个 worker 才会撞上的重复投递路径（跨进程那节两个 worker 正好绕开），以及真浏览器报告的真实形状 `{"csp-report":{...}}`（Python 判据一直在用自造的顶层字段喂解析器，假形状能过、真形状会被归成 `unknown`）。还有一个接线错误是被不相干的缓存判据抓到的：新端点插进了 `@app.get("/health")` 与 `@app.get("/health/ready")` 之间，把 `/health` 变成恒返回 204 的处理函数；已复位并补了一条"三条路由各自归属"的判据。

流水线补漏：`tests/frontend-firstscreen.mjs` 与 `tests/csp-report-browser.mjs` 此前不在 CI、也不在 `scripts/test-all.py --kind browser`，也就是"写了判据但没人跑"，本轮两处都接上（方案 C13 要防的正是这种漏法）。文档同步纠正两处与代码不符的说法：执行记录里"B06 界面层仍未做"作废（三态与上次成功/失败已渲染并有判据覆盖），验收索引中 C07/C11 的延期表述改为实测结论加边界。

| 发布对象 | 已部署源码 | 正式 CI |
| --- | --- | --- |
| 主应用 | ca3fb619a57349ef6b5326edb4f1a4cf9a7a33b6 | [42158793408](https://github.com/clowndest-svg/JianZhiSuXingRuanJian/actions/runs/42158793408)：android / integration / deploy 三项全部 success（integration 里含本轮新接入的两份浏览器判据） |
| 后台 | a4a7adb（`deploy/APP_REVISION` 由 c1d7c0bbb 改指 ca3fb619a） | Run #15 success；本机跨仓 `tests/test_ops_api.py` 在主仓同一版源码上 exit 0 |

配对回读：生产 `source_revision=ca3fb619a…` 与后台 `deploy/APP_REVISION=ca3fb619a…` 指向同一版主应用源码，
跨仓判据不再跟着 `main` 浮动。匿名 REST 配额用尽后改用 Actions 运行页确认结论，没有把"取不到"写成"通过"。

## 尚未落地（不写进"已完成"）

- **C09 独立异地副本**：现有链路是"本机拉取 → 自动解密 → 完整性/外键/记录数/媒体抽样还原 → 备份年龄告警"，仓库侧与验证都做了，但异地那一份仍然依赖这台 Windows 电脑在线。要真正达成"电脑离线也有一份独立加密副本"，需要先定下异地目标与凭据（涉及第三方账号、密钥保管与费用），这属于要用户点头才能接的外部服务；本轮没有替它选供应商，也没有把现有验证写成 RPO/RTO 达成。
- 正式 CSP、186 处内联处理器迁移、C06 全量模块拆分、B05 完整训练进阶、B07 更深入周报、B09 自助账号流程、实体 Android 安装/相机与双实体设备通话验收。

## 生产回读与产物

健康接口（`https://scientificexploration.art/health/ready`，本轮实测）：`release=r42158793408`、
`source_revision=ca3fb619a57349ef6b5326edb4f1a4cf9a7a33b6`、`schema 17/17` 配对、`status=ok`；
`chat.fanout=redis`、`chat.worker=9337a8207e90`（跨进程投递层在生产上真的起来了，但只有被负载均衡到的那一个进程）；
`csp.mode=report-only`、`csp.inline_handlers=186`（在生产真要下发的 `index.html` 上数出来的，不是文档里的旧数字）、
`csp.can_enforce=false`、`csp.report_endpoint=https://scientificexploration.art/csp-report`；
`rate.store=redis`；`min_build=0` 且 `build_override=true`（强更门由运维开关控制，本轮没动它）。
发布前那份回读留在证据里（`live-before.json`）：当时 `release=r42072201117`、`source_revision=c1d7c0bbb`、
没有 `csp` 字段、`chat` 里也没有 `fanout`/`worker`——两条对照能看出这轮确实换上了。

首页响应头实测带 `content-security-policy-report-only`，且**没有** `content-security-policy`；
`/csp-report` 用 GET 打是 405（路由确实挂上了，而不是 404）。真 Chromium 打生产页面 9 项通过：
页面脚本照常执行（`APP_BUILD=76`、内联处理器要的全局函数在）、9 个 script 标签全部加载、
同站 `/health/ready` 在 CSP 下正常可达、除本地探测外零页面报错零请求失败。
其中"本地视觉服务探测失败"那一条第一版判据把它算成了页面错误判红——那是判据写得太粗：
`auto` 引擎探不到本机 8081 时按设计回退线上引擎，这台机器没开那个服务，属于预期路径，
不是产品缺陷也不是 CSP 拦的；改成单列之后复跑通过。

安装包：`https://scientificexploration.art/qingsu.apk` 实际下载 **9,417,027 字节**，
SHA-256 `41aef127fb483431ba34986173009b0df0d0edb95b76a5fb7c32e03dee1d3c40`、
MD5 `63916bc2969d884be27c36cf465ca86f`，与线上 `version.json`（76 / 2.4.3 / min 76）逐字段一致。
包内 `assets/app.js` 与 `assets/sw.js` 的构建标识都是 **76**，说明这版 APK 是重新构建签名的，
不是复用上一版。仓内 `app/src/main/web_version.json` 已同步成线上那份（原先与线上不同，现在逐字节相同）。

资源一致性：线上 15 项静态资源与仓库对比，14 项逐字节相同；唯一不同的是 `manifest.webmanifest`，
逐行文本完全相同、只差行尾（仓库工作区 26 个 CRLF，线上与包内都是 0 个，且线上那份与包内字节完全一致）
——是工作区行尾，不是线上跑了另一版资源。签名证书哈希与 v2/v3 校验由正式 CI 的签名步骤完成，
本机没有重复签包。

全量回归（在最终代码上重跑，不用修复前的批次充数）：Python 32 套最终全部 exit 0
（含 `legacy-backend`、`test_multiprocess` 25 条、`test_content_security` 24 条）；Node 批 exit 0；
Chromium 批 14 份全部 exit 0。首屏判据在机器空闲时单独复跑，11 项 0 红。

这一轮跑出过三处红，逐个定性、没有一处被"重跑一次绿了"糊过去：

- `test_consistency.py`：清理竞态。子进程的 `server.log` 句柄还没释放，`TemporaryDirectory` 退出时抛
  `PermissionError`，把已经跑完的判据整段吞掉——日志里只剩栈，一条结果都没留下。这是判据自身的脆弱点，
  改成与其它套件同样的 `ignore_cleanup_errors` 口径后复跑 exit 0。
- `media-cache-ui.mjs`：抓到的是真的接线错误。`/csp-report` 被插进了 `@app.get("/health")` 与
  `@app.get("/health/ready")` 这两个堆叠装饰器之间，于是 `/health` 变成恒返回 204 的那个处理函数——
  接口不报错、健康检查"看着也通"，只是浏览器再也拿不到文档。修完新增一条「三条路由各自归属」判据，
  下次再插错位置会直接被钉住，而不是靠一条不相干的缓存判据偶然抓到。
- `legacy-backend.py` 两条：`version.json` 与实际包体不一致、包内 `app.js` 还是 75。摊开数字才看清：
  清单已经是 r192 的线上包（md5 `63916bc2`），而判据读的是仓库根上那份**上一版留下的现役包**
  （md5 `13da252e`、包内构建号 75）。判据没错，是工件过期。把线上现役 APK 取回覆盖 `qingsu.apk` 后
  两条都绿。过期工件和真缺陷长得一模一样，只有把 md5/size/包内构建号摆出来才分得开——
  这也是为什么这里不写"重跑一次就绿了"。

## 本轮没有重新实测的（不计入通过）

这轮没有新增或修改任何 SQLite 迁移（生产仍是 schema 17/17，与发布前同一版），新增的只有 Redis 侧的
在线/通话/心跳键——里面不存业务数据，且都靠 TTL 与心跳自然过期，所以数据形状的风险面限于此。
以下项目本轮**没有**从这台机器重新实测，不写进通过项：发布前后完整业务行集合摘要、真实用户与轻塑号计数、
SQLite `integrity_check`/外键违规计数、临时验收账号清理结果、加密备份的隔离恢复演练、监控 `problems` 与 5xx 曲线。
这些入口在服务器侧（`scripts/monitor.py`、后台特权接口、`pull-backup.py`），需要服务器凭据；
本轮的发布流程覆盖到 CI 的发布前备份、隔离 QA 验收与冒烟切换，具体数字以那一步的执行结果为准，
不在这里替它填数。

## 打开与入口

[软件](https://scientificexploration.art/) · [下载 APK](https://scientificexploration.art/qingsu.apk) ·
[后台](https://scientificexploration.art/ops/) · [证据目录](release-evidence-r192/)
（`main-ci.json`、`admin-ci.json`、`live-before.json`、`live-after.json`、`live-browser.json`、
`public-readback.json`、`apk-verification.json`、`local-gates.json`、`c07-multiprocess.json`、
`c07-mutations.json`、`csp-mutations.json`、`c11-firstscreen.json`）。
