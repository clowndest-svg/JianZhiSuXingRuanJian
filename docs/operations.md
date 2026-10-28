# 运行与恢复

主机为 124.220.54.64，应用根目录 `/opt/qingsu`。使用用户提供的 SSH 密钥连接；不在命令行/日志/仓库中记录密钥内容。正式签名及加密备份密钥保存在发布机仓库外的受限目录 `D:/RuanJian/ShuJuChunChu/qingsu-signing`，该目录及其密码文件必须另行妥善保管。

## 发布

1. 执行 README 中全部检查，生成正式 `qingsu.apk` 和自动版本清单。
2. `python scripts/package-release.py --output release.tar`。此归档只包含白名单代码、网页、安装包、测试和运维脚本，不含数据库、照片、私钥或备份。
3. 将归档上传至服务器，在 `/opt/qingsu/releases/<release>` 中解压。执行 `python3 scripts/start-qa.py --release <release>`，在随机 TLS 路径、隔离数据库和独立端口验收；禁止将压测指向生产。
4. 在服务器执行 `python3 scripts/deploy.py --stage /opt/qingsu/releases/<release> --revision <已提交的源码SHA>`。脚本先创建 SQLite 一致性备份及媒体快照、备份代码/网页/service/nginx，后切换代码；就绪失败自动恢复代码和配置，不覆盖生产数据库。
5. 执行 `python3 scripts/verify_live.py`；只使用随机命名的临时账号，结束时按该账号ID清理。检查公网回读脚本/APK的 SHA-256、证书验证、HTTP重定向与版本清单一致性。
6. 移除临时 QA 路由、停用 QA service，保留正式回退快照。不得删除 `data/`、`uploads/`、受保护的密钥或有效恢复备份。


## WebSocket 与 nginx（r149 起）

- 私聊走 `/ws/chat`。两件事缺一不可，缺任何一条现场都只表现为「实时连接用不了」，
  而发消息照样能成功（前端会退回 HTTP），所以坏在暗处：
  1. `uvicorn` 必须显式 `--ws websockets-sansio`。装了 `websockets` 但版本是 15+（旧版
     legacy 实现被删）时，`--ws auto` 会退化到不支持升级，把握手当普通 HTTP 转给应用，
     现场看到 `/ws/chat` 404 —— 而路由其实注册着。现役 unit 里已写死该参数，
     正本备份在 `backups/qingsu.service.before-ws`。
  2. nginx 要有 `location /ws/` 并带 `proxy_http_version 1.1` + `Upgrade`/`Connection` 两颗头。
     配置正本在仓库 `scripts/qingsu-tls.conf`，落盘到 `/opt/qingsu/tls/default.conf`。
- **改这个文件必须用 `cat 新内容 > 目标`，不能用 `install`/`cp` 换 inode**：容器把该文件
  按路径绑成只读挂载，绑的是当时那个 inode；换 inode 之后 `nginx -s reload` 读到的还是旧内容
  （实测 `nginx -T` 里查不到新 location）。改完要 `docker restart qingsu-tls` 才会重新解析。
- 自检：`curl -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13'`
  打 `https://…/ws/chat?ticket=bad`，**403 才是对的**（票据被应用拒），404 说明中间某层没透传。

## 正式服务

### r164 私聊媒体验收

服务器需安装 `ffmpeg` / `ffprobe` 并包含 libopus。发布入口 `verify_live.py` 在11项常规冒烟之后调用 `verify-chat-media-live.py`：验证18枚官方素材、真实语音转码/时长/发送/重试/归属、图片表情与撤回；仅按随机夹具账号ID回收数据库行和对应媒体。隔离QA自动根据 `QINGSU_VERIFY_DB` 选择其 qa-uploads，生产使用 `/opt/qingsu/uploads`。

显式 `QINGSU_VERIFY_NETWORK=1 python3 .../verify-chat-media-live.py` 可检查真实 OpenMoji 搜索、下载与带署名发送。外部来源网络故障不应被当作本地流程通过；CI中的网络界面检查使用固定夹具，正式网络实测另记。OpenMoji17.0.0索引和许可说明位于app_modules，原图按需下载；Commons从当前主机握手超时，界面明确提示。

r167 起网络表情默认是中文梗图：服务端检索 360 图片（主）和百度图片（兜底），只取检索结果的 HTTPS 缩略图，来源页、作者和“版权归原作者、未声明许可”随消息保留；关键词会发送给对应检索服务。360 拒绝或无结果时切百度；两者都没结果时客户端用 Memegen 模板或内置背景生成一张带用户文字的图，走现有本地表情上传。搜索缓存 10 分钟、结果 token 15 分钟、Memegen 模板缓存 1 小时，Memegen 预览图使用 `?width=240`，导入仍取原图。360/百度的图片 URL 走主机+路径白名单，不跟随重定向，避免 SSRF；上游 HTTP 错误不会当成成功。

### 语音通话（r168 起）

服务器运行 coturn（UDP 3478 + UDP 49160–49180），WebRTC 媒体优先点对点，必要时经 TURN 中继；信令复用现有 `/ws/chat`，不落库、不录音。TURN 使用短时 REST 凭证：`server.py` 从 `/opt/qingsu/keys/turn-secret` 读取共享密钥，`/api/rtc/ice` 返回 1 小时有效的用户名/密码。`scripts/provision-coturn.sh` 可重建 coturn 配置；`/etc/coturn/turnserver.conf` 与密钥文件都必须 root 只读，不能进仓库。腾讯云安全组需放行 UDP 3478 与 49160–49180；未放行时只能依赖点对点，不能承诺接通。

当前只支持双方都在 App 内在线时的 1:1 通话；App 被系统杀掉或后台断网时没有厂商推送，不会后台响铃。TURN 关闭 TCP/TLS，UDP 被运营商封锁的网络无法通话，会明确提示失败并保留语音消息。`/health` 的 `chat.turn` 和监控的 `turn` 字段可看出 TURN 是否可用。

### 资源保护与监控阈值

Directus 和本地 llama 都是后台服务，给它们设硬上限，避免某个查询或模型任务把 qingsu/coturn 挤掉：

- Directus：容器 768MB 内存（无 swap）、1 核；配置在 `/opt/qingsu/admin-console/docker-compose.override.yml`，当前容器用 `docker update` 生效。
- llama：`MemoryHigh=1000M`、`MemoryMax=1200M`、`CPUQuota=200%`（2 核）；drop-in 在 `/etc/systemd/system/qingsu-llama.service.d/limits.conf`。
- qingsu 与 coturn：`CPUWeight=500`，高峰时优先拿 CPU；不限制其内存，避免误伤主服务。
- 重建服务器时执行 `scripts/provision-resource-limits.sh`；Directus 的 768MB 是当前 210MB 的约 3.6 倍余量，llama 的 1.2GB 是当前约 217MB 的约 5.5 倍余量，正常任务不会被误杀。

`monitor.py` 每 5 分钟额外记录 `cpu_percent`、`memory_percent`、`swap_percent`、`load_per_core`、`disk_percent`，阈值分别为 85%、85%、25%、1.5、85%，任一越线会把对应名称写进 `problems` 并让 service 失败；报告里同时保留阈值原文，避免以后忘记口径。可用 `QINGSU_MONITOR_CPU_PERCENT=-1` 这类环境变量临时覆盖单个阈值做自检；生产服务不设置这些变量。1Panel 里“网站/应用 0”只是它没接管 Docker/手工服务，不是资源使用指标。

- `systemctl status qingsu`：专用账号运行，只读代码，数据与媒体目录可写。
- 发布脚本显式将代码/网页目录设为root所有、目录755、文件644，避免Windows归档的可写权限进入服务器。服务账号不可写`server.py`；数据和媒体继续由服务账号管理。
- `systemctl list-timers qingsu-*`：备份每日03:10（随机最多5分钟）；短期证书每日00/12点检查（随机最多10分钟）；监控每5分钟。
- `python3 /opt/qingsu/monitor.py`：检查 HTTPS readiness、服务、证书剩余寿命、磁盘、备份时效及近5分钟请求 P95、5xx、SQLite 锁和缓存退化。结果为聚合 JSON，保存在 `/opt/qingsu/monitor/status.json`；异常以 service 非零状态和 journal 报告。
- 日志不记录 query、token、分享密钥、照片或健康原文。nginx access log 关闭；应用日志保留 request_id、状态与耗时。
- 目前告警落在本机 systemd/journal，没有向第三方邮箱/聊天发送通知。未配置外部值守渠道时，不宣称无人值守故障一定会通知到人。
- `docker inspect` 确认 nginx 容器IP；网段/容器改变后重新生成 service 的 `forwarded-allow-ips`。不要信任任意来源的转发头。

## TLS

r161 预留域名为 `scientificexploration.art`，当前受腾讯云备案校验拦截，继续使用 HTTPS IP 入口。备案/腾讯云接入通过后，使用 `python3 scripts/enable-domain.py` 申请含主域名与www的证书并切换代理，失败保留原配置。成功后www经HTTPS 308跳转主域名，并将验证通过的入口写入 `/opt/qingsu/site-base`；服务的分享链接、下载二维码、运维监控与后续部署沿用它。域名证书位于 `/etc/letsencrypt/live/scientificexploration.art/`，与 IP 证书共同由现有续期 timer 管理；部署钩子重载 TLS 容器。IP独立证书和旧客户端升级清单继续保留。

### 浏览器消息提醒

发布时一次性生成 `/opt/qingsu/keys/webpush-vapid.pem`（root:qingsu，640），后续部署保留此密钥。`qingsu-push.timer` 每分钟读取未读私信及评论/回复/@，合并发送不带正文的通用通知；订阅绑定有效会话，退出或后台撤销会话后清除。无订阅时不发送。永久失效订阅删除，连续失败5次后删除并由用户重新开启；接口不接受任意推送主机，防止请求内网。浏览器、系统或网络不支持时明确提示，不宣称必达。安卓目前保留本地每日提醒，原生离线私信推送需要另外接入厂商通道。

### 邮件配置

在 `/ops/` 的「邮件接入」填写服务商 SMTP 配置。服务器文件为 `/opt/qingsu/mail.json`，由root写入、qingsu只读；不进入Git或运维审计。服务读取配置变更无需重启。界面检查只建立可信TLS连接并认证，不发邮件，不代表收件箱已收到验证码；真实投递必须另行验证。

当前状态（2026-10-20 接入）：QQ 邮箱个人账号，`smtp.qq.com:465`，`tls=ssl`，发件人与登录账号同为 `2379323670@qq.com`，密码为 16 位 SMTP 授权码（只存在于服务器 `mail.json`，权限 `640 root:qingsu`，不进仓库、不进日志）。已用 qingsu 账号以 `app_modules/mailer.send` 真实投递一封测试邮件成功，`/api/account/recovery-status` 由 `down` 变为 `up`。

限制与后续：QQ 免费邮箱有每日发信量上限，只够验证码/找回密码这类事务邮件，不可用于群发，超限或投诉会停用 SMTP 权限；发件域名是 `qq.com`，用户可能怀疑真伪。域名 `scientificexploration.art` 接入通过后，建议换阿里云邮件推送（免费额度每日 200 封，需配置 SPF/DKIM），送达率更好。腾讯云出站 25 端口封锁，只走 465/587。

IP证书路径 `/etc/letsencrypt/live/124.220.54.64`，Certbot运行时 `/opt/qingsu/certbot-env`。HTTP 80 保留 `/.well-known/acme-challenge/` 与已有 `latest.json`、`latest-extensions.json`；轻塑入口跳转HTTPS。443容器 `qingsu-tls` 的证书挂载只读。

`/opt/qingsu/certbot-env/bin/certbot renew --dry-run --run-deploy-hooks` 可在维护窗口验证续期；已有本轮成功记录。短有效期证书不能依赖一年一次的人工续期。公网入站 TCP 80/443 需持续开放。

## 备份与恢复

`/opt/qingsu/backup.py` 使用 SQLite backup API，记录 integrity_check，并打包媒体与隔离的孤儿档案。服务器本地快照root私有、保留14天；公钥加密的 `.p7m` 不需要把解密私钥放到服务器。

Windows 任务 `QingsuEncryptedBackup` 每日04:00运行 `scripts/pull-backup.py`，从服务器拉取加密副本至仓库内被忽略且权限受限的 `.private-backups/`；保留30天，恢复数据库副本并实际还原媒体文件验证。计划任务使用当前用户交互登录，已启用错过后补跑；电脑关闭、离线或用户未登录时无法完成异地拉取，因此异地 RPO 依赖这台电脑在线；服务器每日本地备份独立运行。

拉取后同一脚本会做一次真验证：解密 → `PRAGMA integrity_check` → `PRAGMA foreign_key_check` → 各表记录数 → 媒体成员逐个核路径（拒绝绝对路径、`..`、链接成员）并按抽样真实还原再比 SHA-256。结果写进 `.private-backups/verify-report.json`（`--report` 或 `QINGSU_BACKUP_REPORT` 可改路径），任何一步失败都以非零退出并在报告里留下中文原因。报告同时带"备份年龄"：默认阈值26小时（`--age-threshold-hours`/`QINGSU_BACKUP_AGE_HOURS`），主口径是副本文件名里的服务器产出时刻，本机落地时刻用来区分病因——拉取准点但数据年龄超标＝服务器没产出新备份，两者都超标＝这台电脑没跑成（关机、离线或未登录），本机一个副本都没有＝异地拉取从没落地。

**未做（不要当成已完成）**：目前不存在与这台电脑无关的独立异地副本。要满足"电脑离线时仍有异地一份"，需要对象存储凭据（腾讯云 COS 或等价），本轮没有凭据、没有配置、也没有演练过，因此 RPO≤24h 与 RTO≤2h 只是建议目标，不是达成状态。`verify-report.json` 只能证明"拉回来的那一份可用"，不能证明服务器仍在产出新备份；服务器侧备份年龄监控见 `scripts/monitor.py` 的 `backup_age_hours`。

恢复必须在空的隔离目录进行，先解密到内存/临时受限目录，验证 SQLite 完整性、外键、记录数和媒体文件，再停止服务并选择恢复时间点；不要直接覆盖正在运行的数据库。生产回退默认只回退代码和配置，schema保留前向兼容。历史58条孤儿记录已放在 root 私有隔离数据库中，未猜测归属或不可恢复地删除。

## 发布顺序与版本配对（2026-10-22 起，方案 C03/C05）

两仓共用同一个业务库，后台要写的列由主应用的迁移创建。**必须先发主应用、再发后台**；
这条现在不再只写在文档里，有三处会拦：

1. `scripts/deploy.py` 在备份之后、重启之前显式跑 `scripts/migrate.py`，并在起来之后
   复核 `/health/ready` 的 `schema_version == schema_required`，对不上直接失败回退。
2. 服务进程的 unit 带 `Environment=QINGSU_SKIP_MIGRATE=1`：import 期不再改结构，
   库落后于代码时 `guard_schema_version()` 拒绝启动，而不是静默补列或等第一条请求炸。
3. 后台 CI 按 `JianZhiSuXingRuanJianHouTai/deploy/APP_REVISION` 里钉住的**精确 SHA** 跑跨仓判据
   （占位值会让 CI 直接红）；发布入口 `admin_smoke` 读 `/api/version-pairing`，
   `paired` 为假就拒绝发布后台，配对结果写进 `admin-console/release.json`。

结构版本与表归属登记在 `app_modules/migrations.py`：业务表归主应用，`ops_*` 归后台。
加一条迁移要在 `MIGRATIONS` 追加并把 `SCHEMA_VERSION` 抬到该条的号——
`tests/test_optimization_data.py` 会核对"版本号＝清单最后一条"，忘了抬会红。

## 后台会话与降权（2026-10-22 起，方案 A02/C01）

- 后台 Cookie 是服务端登记的随机会话号（库里只存 SHA-256），退出真的撤销服务端那行。
  空闲 2 小时（`SESSION_IDLE_TTL`）与绝对 8 小时（`SESSION_TTL`）分别到期；
  会话记 `credential_fp`，**换掉某个命名账号的口令即撤销它名下所有会话**。
- 命名操作者来自 `console.json` 的 `operators`（或本地 `OPS_OPERATORS_JSON`）；
  没配时回落成单把 `ops_token`，审计里的身份变成 `console`（浏览器）/`script:console`（脚本直调）。
  两把凭据共用同一口令且请求没带 `operator` 时会拒绝登录——猜不出是谁就不该顶掉某个具体的人。
- `/ops/` 的「后台会话」页能看现在谁在线、各自还剩多久到期；撤销别人的会话要原样带回确认短语。
- 运维服务从 `User=root` 改为 `User=qingsu-ops`，需要 root 的三件事改经 sudo 调
  `qingsu-{backup,set-gate,container-health}` 三个参数白名单 helper（不给 ALL、不进 docker 组）。
  **上生产的前置**：`console.json`/`mail-check.json` 改 `root:qingsu-ops 640`、
  `mail.json` 给服务账号可写、sudoers 落 `/etc/sudoers.d/qingsu-ops`（`visudo -c` 不过就撤掉）、
  helper 装到 `/usr/local/sbin`，然后跑 `deploy/verify-ops.sh`。
  `NoNewPrivileges=yes` 故意没进 unit——它和"经 sudo 调 setuid helper"互斥，
  要开得换成 socket 激活的 root helper。
- **未做**：以上都是仓库侧状态，生产尚未切账号。切失败会让后台整体不可用，
  回退办法是先把 unit 改回 `User=root` 再 `systemctl daemon-reload && systemctl restart qingsu-ops`。

## 媒体缓存分层（2026-10-22 起，方案 A14）

`/uploads/{name}` 的 `Cache-Control` 按"撤销靠什么生效"分三层：

| 素材 | 策略 | 为什么 |
| --- | --- | --- |
| 身材照（带 `audience`） | `private, no-store` | 分享开关一改就该看不见 |
| 社区/列表缩略图（`thumb=1`） | `private, max-age=300` | 这张图能不能拿到本来就只由 15 分钟签名决定，路由不回查帖子状态；no-store 只买到重复下载 |
| 私信媒体、原图、头像 | `private, no-store` | 撤回与换设备不该被缓存兜住 |

`COMMUNITY_THUMB_MAX_AGE=300` 必须明显短于签名 900 秒，判据钉住这个大小关系。
**已被用户保存到设备的内容无法远程收回**，这句要如实写在对外说明里。

## r188 迁移、回退与本机全量测试

候选结构版本15：基础表与扩展表统一在显式事务中迁移，最后登记版本；已有轻塑号不重分配。服务进程的 `QINGSU_SKIP_MIGRATE=1` 和 `migrate.py --check` 不创建/回填业务结构。当前代码落盘后 `/opt/qingsu/migrate.py` 能从应用根目录正确导入服务。

发布前 `release-state.json` 登记旧发布标记、维护脚本、helper、主服务与监控/推送单元是否存在；回退恢复文件和原本不存在的状态，数据库保持前向兼容，绝不以旧库覆盖新数据。加密备份完成后才原子发布 `.p7m`；本机拉取/验证不再隐式生成替换密钥，仅显式 `--prepare` 可在空目录初始化。

全量测试入口为 `scripts/test-all.py --kind python|node|browser`，逐套保存退出码、耗时与日志至被忽略的 `_audit_sandbox/full-*`。浏览器仍需要固定版本 Playwright/Chromium；媒体测试需要ffmpeg/ffprobe；Redis缺失时多进程判据不能当作通过。Linux备份快照测试和实体Android验收分别记录，不能用Windows跳过或编译结果代替。

## 容量与性能

`python tests/performance.py` 只创建临时数据库与本机18001端口，结束后清理。基准为100个模拟用户、每人365天、109500条记录、20并发400次普通读写；AI推理不混入普通接口指标。它验证服务端应用与 SQLite，不代表公网时延、浏览器 LCP/CLS 或未来所有负载。

## 签名与设备验收

`sign-release.py` 生成旧证书到正式证书的轮换证明。Android 9+正式证书 SHA-256：`c6b15363badb1035563e5c731874fb78d4b08eeb88e223ced625faaa8fbd738f`。历史签名只用于低版本兼容，不能称所有版本已摆脱旧证书。

真机测试入口：`com.fitcoach.shapemaster.test/androidx.test.runner.AndroidJUnitRunner`。测试APK和正式APK都需按兼容签名安装；vivo超级守护的安装授权由机主在手机上操作。测试用合成账号与合成图片，截图仅记录测试账号。不能把本地HTTP协议夹具称为手机真实模型推理。

旧客户端升级兼容：HTTP `/version.json` 仅返回公开版本元数据，安装包地址为HTTPS；这是为不跟随跨协议重定向的旧Java客户端保留的升级引导，不提供登录/业务/照片接口。其余轻塑HTTP入口跳转HTTPS。旧客户端在升级前自身发出的HTTP请求无法由服务端追溯加密，应尽快安装正式版本。
