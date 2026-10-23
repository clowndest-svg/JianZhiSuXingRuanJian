**2026-10-22 优化执行记录（2026-10-23 复核校正）**

> 后续接手：本轮已获用户授权实施与发布，实际修复、验收和线上结果见 [r180 报告](release-r180-final.md)。下文仍保留 Qoder 施工阶段的历史结论；不得据历史“已完成”推断生产状态。

总方案：[optimization-plan-2026-10-22.md](optimization-plan-2026-10-22.md)。这份是阶段记录，逐项标注「已实现并本地验证 / 仓库侧已改、生产未发布 / 未做」。

**历史状态解释与复核入口：** 接手前 Qoder 仍在施工，正式验收尚未开始。本文“已完成”仅表示当时记录的仓库实现/本地验证，不表示原方案全部验收条件已通过。第四节为历史运行数字，中途检查见 [10 月 23 日复核记录](optimization-review-2026-10-23.md)。当前 **A14 中途复现待处理、B06 界面缺口、B08 真实双端网络/设备验收、配置与后台降权**均应进入交付后的 [验收清单](optimization-acceptance-2026-10-23.md)。正文保留当时过程证据；接手后实际修复与线上结果见 r180 报告。

## 一、A01–A14 权限与数据边界（施工阶段记录；待交付后正式验收）

| 编号 | 状态 | 落地位置与要点 |
| --- | --- | --- |
| A01 | 已完成 | WS 票据绑定登录会话（`chat.mint_ticket(..., session_hash=)`），握手、每条事件、15 秒空闲检查都以数据库为授权依据；失效关连接（4403/4401）并走既有通话清理。不依赖 Redis 通知是否送达 |
| A02 | 已完成 | 后台会话改服务端登记（`ops_sessions` 存哈希）；命名操作者、空闲 2h 与绝对 8h 分别到期、凭据指纹轮换即撤销；退出写审计；新增 `/api/sessions` 与 `/api/sessions/revoke`（撤他人要原样带回确认短语） |
| A03 | 已完成 | 个人导出清除撤回正文/ASR/媒体/引用并去重、留导出审计；Directus 日常读消息只给元数据 |
| A04 | 已完成 | 运维 API 与 Directus 播种都改显式白名单 `READ_FIELDS`，未知表/列默认不可读；Directus 业务写权限从播种撤销（`WRITES = {}`） |
| A05 | 已完成 | 改名、封/解封、撤销会话、重置口令、注销的成功审计与业务修改同事务（`audit_in`） |
| A06 | 发布物部分一致性已实现；安装与生效待验 | 抬门前校验文件存在、大小、SHA-256 和包内 JS 的 `APP_BUILD`；**这不证明 Android 包有效、签名正确或可升级安装**。借业务库写锁串行化 + 唯一临时文件 + fsync + replace；写后回读主应用 `min_build`，答话不一致回退并报 503，联系不上则报 `confirmed:false` 不回退；后者必须在界面显示“已写入、未确认”，不能算成功生效。多种坏包的测试夹具仍需逐案构建，见复核报告 |
| A07 | 已完成 | 补评论点赞/提及的间接依赖；注销在写事务内算计划；媒体清理任务持久化，提交后扫存量引用再删原图与缩略图；`/ops/api/media/cleanup` 可重试 |
| A08 | 已完成 | 临时口令 30 分钟有效、仅允许登录一次，登录后只能改密或退出；`get_current_user` 按路径白名单拦截 |
| A09 | 已完成 | 用户/反馈/举报/审计统一 cursor/limit/more/next_cursor + total，并补类型、构建号、对象状态筛选；运维页四个工作台真翻页 |
| A10 | 已完成 | 孤儿盘点补评论配图、个人表情，**并补缩略图随原图一起算引用**（本轮接手时还漏着，已加判据） |
| A11 | 已完成 | 社区卡片批量投影（`app_modules/post_cards.py`）；实测一页 12 条 **SELECT 从 73 降到 6** |
| A12 | 已完成 | 离线草稿保留 `occurred_at`/本地日期/时区，服务端区分"发生日"与"收到日"；缺日期的旧草稿要求确认，不擅自推断 |
| A13 | 已完成 | 补录文案改"填 0 表示本次不计入消耗"，与后端实际一致 |
| A14 | **中途复现待处理；最终结果待交付后验收** | 现有实现主要按 `audience`/`thumb` 参数选缓存，没有完整回查媒体业务授权。本次隔离复现：私信图片撤回后旧 URL 仍 200，添加 `thumb=1` 返回 `private,max-age=300`；签名剩 1 秒仍给 300 秒缓存。需补用途分类、原图/缩略图同等授权与按剩余有效期收紧 TTL。`no-store` 不等于服务端撤销。已被用户保存的副本无法远程收回；新请求能否读取仍必须修复与验收 |

## 二、B 组体验（部分完成）

- **B02 统一请求层**：已完成。抽出 `requestBase` 统一超时（读 15s / 写 30s / 上传 120s）、`AbortController`、401/403/409 与账号代次处理；`getJson`/`patchJson`/`deleteJson`/`publicPost` 全部改走底座；`postApi` 的幂等 `request_id`、并发合并、`RECORD_PATHS` 语义保留。判据 `tests/request-contract.mjs`。
- **B10 弹窗与无障碍**：已完成。实测发现白名单漏了 `page-layer` 与 `report-dialog`（打开时背景不 inert、焦点不归位、Esc 无反应），已补并改为运行时扫描 `body > dialog[open]` / `[role=dialog][aria-modal]`；关闭后焦点回触发控件；封顶高度留在滚动容器上；4 个只有 `✕` 的按钮补可读名字；reduced-motion 点名弹层/抽屉/toast。判据 `tests/a11y-dialog-contract.mjs`（真 Chromium，320px + 200% 字号逐弹窗量）。
- **B03 记录更省步骤**：已完成。新增只读接口 `/api/food/recent`（**只从本人历史长出来**，`RECENT_MEAL_SCAN_CAP=300` 扫满时 `note` 明说"只扫了最近 300 笔"而不是"已读完全部"）；常用餐食点击、复制上一餐（产出**可编辑草稿**不直接入账）、份量快捷、体重单位单一真值。判据 `tests/test_optimization_ux.py` + `tests/records-profile-permission.mjs`。
- **B04 档案拆组**：已完成。`PROFILE_GROUPS` 四组（基础资料/目标/训练场景/饮食偏好）覆盖那 8 个字段**不重不漏**；保存前必须先看到变更摘要、确认按钮才可用；每组只发本组的键。保留 r176 身材×场景联动与 r177 顶栏体重=最近称重，各钉一条判据。
- **B09 权限中心**：已完成。麦克风/定位/通知/使用情况四条实际状态；探针失败时显示"未知"，**不显示 0 也不显示"已关闭"**；四种状态（granted/denied/永久拒绝/从设置返回）文案可区分且读屏名非空。自助导出是真接口；**注销没有本人侧接口，界面上就不放"注销账号"按钮**，只放"提交注销申请"并明说服务端没有本人侧注销接口。离线通知能力如实写明"没有厂商推送、杀后台不会响"。
- **B01 / B06 / B07 / B08**：见「七、后续收口与仍待验证事项」。
- **B05 完整训练进阶、B07 更深入周报、B09 自助注销全流程、原生厂商推送**：按方案属「后续增强」，**未做**。

## 三、C 组工程与运维

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| C01 | 仓库侧已改，**生产未发布** | 运维服务 `User=root` → `User=qingsu-ops`；备份/改门/容器健康拆成三个参数白名单 helper + 最小 sudoers（不给 ALL、不进 docker 组）；unit 加 `ProtectSystem=strict`/`PrivateTmp`/`ReadWritePaths`。**`NoNewPrivileges=yes` 故意没加**——它和"经 sudo 调 setuid helper"互斥，要开得换成 socket 激活的 root helper。`admin_api.py` 三处调用已改走 helper，未配置时退回直接做（本地/测试形状），并在 `/api/privileged` 里点名还缺哪个 |
| C02 | 已完成（仓库侧） | 播种只给 read；新增真跑播种、查落库权限行的判据 |
| C03 | 部分（配对门已有，配置发布仍待补齐） | 发布入口加"主后台版本配对门"，配对结果写进 `release.json`；但后台归档与部署入口仍只替换 API/HTML 两文件，策略、helper、sudoers、systemd 与镜像配置的安装/验证/回退不因此自动完成 |
| C04 | 部分 | 后台 `deploy/APP_REVISION` 已填 `610f8b406a0c3d2d7dff7e87b6c5b3194b550ceb`，不再是占位值；但这不等于生产已配对。主仓 CI 仍按后台浮动 `main` 签出，需固定并记录两仓 SHA。Playwright 已钉 1.64.1；生产 Directus RepoDigest 已在 10 月 23 日只读取得（见证据 JSON），配置落盘与重建验证尚未执行 |
| C05 | 已完成（仓库侧） | 新增 `app_modules/migrations.py`：带版本号的迁移登记表 + 表归属（业务表归主应用、`ops_*` 归后台）；`/health/ready` 报 `schema_version`/`schema_required`；`QINGSU_SKIP_MIGRATE=1` 时 import 不改结构、库落后即拒绝启动；`scripts/migrate.py` 显式迁移；`deploy.py` 在备份后、重启前跑迁移并复核版本 |
| C06 | 部分 | 本轮拆出 `post_cards.py`、`record_time.py`、`migrations.py`、`long_tasks.py`；全量按域拆分属后续 |
| C07 | **未做** | 仍单 worker；进程内连接与通话状态未做跨进程投递。本轮只减少了 WS 每事件的重复建连开销，未消除单进程约束 |
| C08 | 已完成（仓库侧） | `monitor.py` 补路由模板归并、按 api/ai/media/ws/admin 分类、慢接口前 5、错误类型；告警去重与恢复通知（`ALERT`/`RECOVERED` 落 journal）。**未接任何外部渠道**，不宣称无人值守会通知到人 |
| C09 | 部分（仓库侧） | `pull-backup.py` 拉取后自动解密 + integrity_check + 外键 + 记录数 + 媒体抽样还原，结果落 JSON 报告；备份年龄超 26 小时报红并区分"电脑没开机"与"服务器没备份"。**独立异地副本仍未落地**，异地 RPO 依旧依赖这台电脑在线 |
| C10 | 部分（持久备份任务已有） | `app_modules/long_tasks.py` 持久任务表（dedup、原子 claim、心跳、reap）；`/api/backup` 支持 `{"async":true}` 回任务号，`/api/backup/{id}` 查状态；默认同步行为不变，原方案的导出分块/异步与实际页面长任务体验仍需另验 |
| C11 | 判据已就位，优化未做 | 新增 `tests/frontend-budget.mjs`：现量体积钉预算（app.js 260,615 B raw / 85,795 B gzip 等）、内联处理器只许降（基线 186 处）、CSP 现状显式标注为未启用。**按需加载与正式 CSP 未做**——186 处内联处理器还在，先上 CSP 会挡掉 WebView 桥 |
| C12 | 已完成 | `sw.js` 缓存 key 改 `pathname + search`、条目上限 64 与淘汰、缓存名由构建号派生（`make_version_json.py` 同步 `BUILD`，不造第二份真值）。判据 `tests/pwa-cache-contract.mjs` |
| C13 | 部分，存在测试覆盖与 CI 缺口 | Redis、业务失败与落账断言等已有改进；历史 Redis 命名空间隔离修复保留。10 月 23 日复核发现：A14 实际撤回访问未被现有测试覆盖，A06 多坏包用例共用最后一次变异夹具；后台 data/ux 测试接入只存在于未提交工作区。须补有效反例与实际流水线结果，不能仅凭当前全绿标完成 |
| C14 | 已完成 | 后台 README 状态段拆成「当前状态 / 历史证据（带日期）/ 待验」，并把"未打勾不许说成已完成"写在原地 |

## 四、施工阶段历史验证（原记录数字；非本次全量重跑）

| 检查 | 结果 |
| --- | --- |
| `tests/test_integration.py` | 64 项通过 |
| `tests/test_optimization_security.py` | 21 项通过（本轮新增 A06 闭环、A02 会话生命周期、C01 helper、C10 长任务、A10 缩略图共 8 条） |
| `tests/test_optimization_data.py` | 7 项通过（新增迁移登记表自洽、结构版本回读、SKIP_MIGRATE 拒绝启动、结构落后拒发高危操作） |
| 后台 `tests/test_ops_api.py` | 40 项通过（新增"日常策略只读"真跑播种那条） |
| `tests/test_long_tasks.py` / `test_monitor_alerts.py` / `test_backup_verify.py` | 15 / 15 / 15 项通过 |
| `tests/test_deploy_pairing.py` | 4 项通过 |
| `tests/test_chat_media.py` | 18 项通过（需 `QINGSU_FFMPEG`/`QINGSU_FFPROBE`；CI 走 apt 安装） |
| `tests/test_r173_contracts.py` | 6 项通过（新增缓存分层那条） |
| `tests/test_ai_contract / test_update_copy / test_companion / test_native_media_contract / test_calls` | 6 / 3 / 8 / 21 / 3 项通过 |
| `tests/test_consistency.py` | 全绿 |
| `tests/test_multiprocess.py`（`QINGSU_REQUIRE_REDIS=1`） | 2 条判据全绿，两进程合计只放行 20 次 |
| `tests/legacy-backend.py` | 622 条，绿 622，红 0（连跑两轮验证 Redis 隔离修复后不再漂移） |
| `tests/legacy-frontend.mjs` | 355 条，绿 355，红 0（其中"观察器数量写死 5"改为按白名单逐项正向断言） |
| `tests/frontend-integration.mjs` | 5 组通过 |
| `tests/pwa-cache-contract.mjs` / `frontend-budget.mjs` | 通过 / 13 条全绿 |
| `node tests/chat-ui.mjs`、`recovery-ui.mjs`、`offline-day-ui.mjs`、`a11y-dialog-contract.mjs` | 通过（真 Chromium；a11y 那条 134 项） |
| `tests/performance.py` | 100 用户 × 365 天 × 109,500 行、20 并发 400 请求：4.25s，P50 181.9ms、P95 380.7ms、P99 407.4ms，5xx/4xx/业务码失败/SQLite 锁均 0，水记录实际落账 25 行 |
| `deploy/tests-helpers.sh` | 66 项全绿（含注入 `;rm`、路径穿越、非白名单容器名被拒） |
| 变异验证 | 本轮新增判据逐条打反样本：A06/A02 共 7 条、C01 共 5 条、C02 2 条、C10 1 条、A10 1 条，全部命中，无一条"假绿" |

原始日志在本地 `_audit_sandbox/*-batch2.log`、`*-optimization.log`（该目录被 git 忽略）。`docs/audit-evidence-2026-10-22/findings.json` 保留的是**缺陷复现快照**，不覆盖成"修好后的结果"。

## 六、本轮顺手挖出的两个**判据自身**缺陷

这类问题比产品 bug 更贵，因为它让"全绿"失去意义：

1. **`legacy-backend.py` 的弹窗正文提取会漂**。它用"从 `toolDialog(` 往后找第一个反引号"取正文，
   遇到 `'a' + x + 'b'` 拼接式模板（后面根本没有反引号）就一路漂到很后面的无关字面量——
   实测出现"四个不同调用点回同一份正文"，也就是说"每个弹窗都用结构件 / 正文开头就是结构件 /
   按钮都带样式类 / 输入框都挂在表单行上"这四条**一直在漏检**。
   已改成按参数扫描（跳过 `function toolDialog(` 定义本身、对单层 `name()` helper 求值）。
   修好后立刻露出两个真问题：`.theme-dot` 被"必须带 td- 前缀"误判成裸按钮；
   而一个 `class="nope"` 的假样式类反而能过。断言因此改成
   "有 type、有类、且至少一个类在样式表里真的存在"（允许纯钩子类如 `td-file-upload`），
   并做了变异验证（全部类名拼错→红；还原→623/623）。
2. **三个套件共用真 Redis 的 `qingsu-prod` 命名空间**。本机 Redis 开着时限流计数跨轮次、跨套件残留，
   上一轮把某个窗口打满，下一轮同名的键一上来就是 429 —— 实测把 `legacy-backend.py`
   打成"红 4 条"，形状完全像产品坏了。已改为每轮唯一命名空间
   （`legacy-backend.py` / `performance.py` / `test_r173_contracts.py`），连跑两轮 622→623 条全绿。

另外补了一处**覆盖漏洞**：客户端"只保存某一组时请求体里不许出现别组的键"原先没有任何判据钉
（`test_optimization_ux.py` 那条测的是服务端接受部分更新，看不见 app.js）。
已在真浏览器里抓发出的请求体补上，并验证它会红（硬塞 `weight_jin` → 三组全红）。

## 七、后续收口与仍待验证事项

| 项 | 状态 | 缺什么 |
| --- | --- | --- |
| B01 首页围绕"今天需要做什么" | **已完成**（2026-10-22） | 首屏三组：今天三件事 → 同步状态 → 下一步动作；净缺口/进度环/训练卡仍在但其后。判据 `tests/home-first-screen.mjs` 7 条。**未做**：可发现性对比数据、真机 200% 字号视觉验收 |
| B06 估算结果可解释 | **部分完成** | 模块与 `/api/ai/status` 已输出 configured / last_success / last_failure 和三态；8 项判据测模块与状态函数。当前前端资产没有该状态接口/字段的消费入口，不能称“界面三态已完成”；还需实际展示配置、最近成功、失败与耗时，并做浏览器验证 |
| B07 周报可执行反馈 | **已完成**（2026-10-22） | 只读 `GET /api/weekly/review`：完整记录日/训练日/体重趋势三维 + 2~3 条带依据数字的反馈。判据 `tests/test_optimization_weekly.py` 6 项。**未做**：30 天文案抽样、健康建议专业审校 |
| B08 私信/通话状态体验 | 实现与模拟契约通过；真实链路待验 | 常驻四态与单条重试、重连补拉去重、通话失败分型已有实现；文末「九」的判据使用假 fetch/WS，不证明双设备切网、权限拒绝和 TURN 实际体验 |
| C07 跨进程 WS/通话 | **未做** | 仍是单 worker；本轮只减少了 WS 每事件的重复建连，没消除单进程约束 |
| C11 按需加载与正式 CSP | **未做**（预算棘轮与内联计数判据已就位） | 186 处内联处理器还在，先上 CSP 会挡掉 WebView 桥 |

## 八、发布前必须完成（当前状态）

1. **截至 10 月 23 日生产优化尚未部署**：只读回读主服务仍为 `c31ecdd` / r178。主仓远端 `main` 已为 `838a284`，不能再写“没有推送”；后台本地 `2c33a45`、远端 `e320b49`，另有一处预先存在的未提交工作流改动。本次文档审查未提交、推送或部署，也未改动该工作区改动。
2. 发布顺序**必须**是先主应用后后台：后台依赖主应用新增的 `users.reset_expires_at/reset_consumed` 与 `food_logs/workout_logs.occurred_at`。这条现在有门拦着（`/api/version-pairing` + CI 部署门 + 后台启动核对），不再只靠文档提醒。
3. Android 需升构建号、重新构建签名、生成一致版本清单并验升级安装；旧 APK 没有恢复对话框，正式发版要给升级入口。
4. `deploy/APP_REVISION` 已填真实 SHA `610f8b4...`；发布前确认选择的最终主仓版本与它兼容，并在主服务升级后实际验配对，不能只验字符串非空。
5. `DIRECTUS_IMAGE_PIN` 的现网 RepoDigest 已读取，见 [server-current.json](audit-evidence-2026-10-23/server-current.json)；尚未设置生产配置或重建容器。
6. C01 降权上生产的前置：`console.json`/`mail-check.json` 改 `root:qingsu-ops 640`、sudoers 落盘、helper 装到 `/usr/local/sbin`，然后跑 `verify-ops.sh`。**这一步失败会让后台整个不可用，需要能立刻回退到 root 单元**。

## 九、B08 收口（2026-10-22 深夜）

产品侧新增：气泡四态常驻（发送中 / 已发送 / 已读 / 失败）、失败留在 `cm.failed` 而不是只弹一次提示、
失败气泡自带单条重试并**复用原 request_id**、重进会话失败标记不丢、切账号清干净、
重连成功后 `dmCatchUp()` 补拉一次历史并按服务端历史去重、通话失败按
拒绝 / 未接 / 忙线 / 不在线 / 没权限 / 网络-TURN 分型、取消与重试不留"忙线"僵尸态。
判据 `tests/dm-state-call.mjs`（纯 node + 假 fetch + 假 WebSocket，8 组全绿），已接进 CI。

**收口时差点记错因果，留个记号**：第一轮跑这条判据红了，我一度以为抓到两个产品 bug
（重连补拉被可见性挡住、信令事件名与文案表对不上）。做完变异才发现两处都是**判据自己的错**：
`pullsBefore` 可能是 `undefined`（首次连接本来就不补拉，`1 > undefined` 恒假），
期望词写成了产品里不存在的"没接听 / 挂"（产品写的是"没有接听 / 对方已挂断"）。
据此撤掉了两处投机改动（其中"事件名归一映射"是死代码——事件分支早把归一名传进去了），
只保留判据修复。决定性变异（把 `if (back) dmCatchUp();` 改成 `if (false)`）会让它红，
证明"重连补拉"这条断言是实的。

**教训写在这里**：判据红了先怀疑判据。这一轮如果直接把"两个产品 bug"写进上面那张表，
后面所有人都会以为 B08 修过两处真实缺陷，而实际产品根本没那两处问题。

## 十、B06 收口（模块层，2026-10-22 深夜）

`app_modules/online_ai.py` 原来只有一个 `ok`，含义是"配置在"，界面据此显示"已接入"——
模型挂了很久也照样显示可用。现在拆成三件事，各自独立：

| 字段 | 含义 |
| --- | --- |
| `configured` | 配置在不在。**静态事实，不证明能跑** |
| `last_success_at` / `last_success_model` / `last_elapsed_ms` | 真的成功过吗、什么时候、哪个模型、花了多久 |
| `last_failure_at` / `last_failure_kind` / `last_failure_ms` | 最后一次失败的**类型**（`http_503`、`TimeoutError`、`empty_content`…）与耗时 |

两条实现上的坑，都写进了代码注释：
- 失败**不抹掉**上一次成功的时间——两个事实一旦合并，就再也答不出"上次好用是什么时候"。
- 有没有跑过用**时间戳**判断，不能用 `ms or None`：几毫秒的调用是 0，被 `or None` 吞掉会变成"从没跑过"，
  正好把这个字段要回答的问题答反。

只记类型与耗时，**不记提示词、不记模型回复**。判据 `tests/test_optimization_ai_status.py`（6 项，已进 CI）
专门钉"状态里不许出现提示词"，变异验证 3/3 命中（配置冒充跑通、失败不细分、把提示词写进状态）。

**仍未做的界面层（10 月 23 日复核）**：`server.py` 已有三态与诊断字段，`app.js` / `features.js` 尚无相应状态接口与字段消费；还需展示“配置在但从未成功过”、最近成功与失败。现有 8 项模块测试没有覆盖该 UI，不能把函数返回三态作为页面展示证据。

## 十一、10 月 23 日独立复核与补做顺序

本次独立重跑：安全 21/21、数据 7/7（12 条社区列表实测 6 次 SELECT）、AI 状态 8/8；request、dm-state、PWA 三套 Node 契约通过。新媒体探针复现 A14 三项漏边界，结果单列为缺陷，不并入“通过”计数。没有重跑全部历史测试、浏览器缓存、真机、真实通话或生产变更验收。

先补 A14 与有效负例、B06 UI 和跨仓 CI，再做主后台配置/策略/降权隔离演练、资源混合负载与独立备份恢复；通过后才进入受控发布。本次新增的整机预算、存储取舍、迁移与验收要求见总方案 D01–D05。阶段证据和未验证项目详见 [复核报告](optimization-review-2026-10-23.md)。
