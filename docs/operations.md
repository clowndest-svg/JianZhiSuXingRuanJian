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

显式 `QINGSU_VERIFY_NETWORK=1 python3 .../verify-chat-media-live.py` 可检查真实 OpenMoji 搜索、下载与带署名发送。外部来源网络故障不应被当作本地流程通过；CI中的网络界面检查使用固定夹具，正式网络实测另记。OpenMoji17.0.0索引和许可说明位于app_modules，原图按需下载；Commons从当前主机握手超时，界面明确提示。两来源都不是全网梗图搜索。

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

恢复必须在空的隔离目录进行，先解密到内存/临时受限目录，验证 SQLite 完整性、外键、记录数和媒体文件，再停止服务并选择恢复时间点；不要直接覆盖正在运行的数据库。生产回退默认只回退代码和配置，schema保留前向兼容。历史58条孤儿记录已放在 root 私有隔离数据库中，未猜测归属或不可恢复地删除。

## 容量与性能

`python tests/performance.py` 只创建临时数据库与本机18001端口，结束后清理。基准为100个模拟用户、每人365天、109500条记录、20并发400次普通读写；AI推理不混入普通接口指标。它验证服务端应用与 SQLite，不代表公网时延、浏览器 LCP/CLS 或未来所有负载。

## 签名与设备验收

`sign-release.py` 生成旧证书到正式证书的轮换证明。Android 9+正式证书 SHA-256：`c6b15363badb1035563e5c731874fb78d4b08eeb88e223ced625faaa8fbd738f`。历史签名只用于低版本兼容，不能称所有版本已摆脱旧证书。

真机测试入口：`com.fitcoach.shapemaster.test/androidx.test.runner.AndroidJUnitRunner`。测试APK和正式APK都需按兼容签名安装；vivo超级守护的安装授权由机主在手机上操作。测试用合成账号与合成图片，截图仅记录测试账号。不能把本地HTTP协议夹具称为手机真实模型推理。

旧客户端升级兼容：HTTP `/version.json` 仅返回公开版本元数据，安装包地址为HTTPS；这是为不跟随跨协议重定向的旧Java客户端保留的升级引导，不提供登录/业务/照片接口。其余轻塑HTTP入口跳转HTTPS。旧客户端在升级前自身发出的HTTP请求无法由服务端追溯加密，应尽快安装正式版本。
