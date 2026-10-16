# 运行与恢复

主机为 124.220.54.64，应用根目录 `/opt/qingsu`。使用用户提供的 SSH 密钥连接；不在命令行/日志/仓库中记录密钥内容。正式签名及加密备份密钥保存在发布机仓库外的受限目录 `D:/RuanJian/ShuJuChunChu/qingsu-signing`，该目录及其密码文件必须另行妥善保管。

## 发布

1. 执行 README 中全部检查，生成正式 `qingsu.apk` 和自动版本清单。
2. `python scripts/package-release.py --output release.tar`。此归档只包含白名单代码、网页、安装包、测试和运维脚本，不含数据库、照片、私钥或备份。
3. 将归档上传至服务器，在 `/opt/qingsu/releases/<release>` 中解压。在隔离数据库和独立端口完成验收；禁止将压测指向生产。
4. 在服务器执行 `python3 scripts/deploy.py --stage /opt/qingsu/releases/r131 --revision <已提交的源码SHA>`。脚本先创建 SQLite 一致性备份及媒体快照、备份代码/网页/service/nginx，后切换代码；就绪失败自动恢复代码和配置，不覆盖生产数据库。
5. 执行 `python3 scripts/verify_live.py`；只使用随机命名的临时账号，结束时按该账号ID清理。检查公网回读脚本/APK的 SHA-256、证书验证、HTTP重定向与版本清单一致性。
6. 移除临时 QA 路由、停用 QA service，保留正式回退快照。不得删除 `data/`、`uploads/`、受保护的密钥或有效恢复备份。

## 正式服务

- `systemctl status qingsu`：专用账号运行，只读代码，数据与媒体目录可写。
- `systemctl list-timers qingsu-*`：备份每日03:10（随机最多5分钟）；短期证书每日00/12点检查（随机最多10分钟）；监控每5分钟。
- `python3 /opt/qingsu/monitor.py`：检查 HTTPS readiness、服务、证书剩余寿命、磁盘、备份时效及近5分钟请求 P95、5xx、SQLite 锁和缓存退化。结果为聚合 JSON，保存在 `/opt/qingsu/monitor/status.json`；异常以 service 非零状态和 journal 报告。
- 日志不记录 query、token、分享密钥、照片或健康原文。nginx access log 关闭；应用日志保留 request_id、状态与耗时。
- 目前告警落在本机 systemd/journal，没有向第三方邮箱/聊天发送通知。未配置外部值守渠道时，不宣称无人值守故障一定会通知到人。
- `docker inspect` 确认 nginx 容器IP；网段/容器改变后重新生成 service 的 `forwarded-allow-ips`。不要信任任意来源的转发头。

## TLS

IP证书路径 `/etc/letsencrypt/live/124.220.54.64`，Certbot运行时 `/opt/qingsu/certbot-env`。HTTP 80 保留 `/.well-known/acme-challenge/` 与已有 `latest.json`、`latest-extensions.json`；轻塑入口跳转HTTPS。443容器 `qingsu-tls` 的证书挂载只读。

`/opt/qingsu/certbot-env/bin/certbot renew --dry-run --run-deploy-hooks` 可在维护窗口验证续期；已有本轮成功记录。短有效期证书不能依赖一年一次的人工续期。公网入站 TCP 80/443 需持续开放。

## 备份与恢复

`/opt/qingsu/backup.py` 使用 SQLite backup API，记录 integrity_check，并打包媒体与隔离的孤儿档案。服务器本地快照root私有、保留14天；公钥加密的 `.p7m` 不需要把解密私钥放到服务器。

Windows 任务 `QingsuEncryptedBackup` 每日04:00运行 `scripts/pull-backup.py`，从服务器拉取加密副本至仓库内被忽略且权限受限的 `.private-backups/`；保留30天，恢复数据库副本并实际还原媒体文件验证。电脑关闭/离线时无法完成异地拉取，因此异地 RPO 依赖这台电脑在线；服务器每日本地备份独立运行。

恢复必须在空的隔离目录进行，先解密到内存/临时受限目录，验证 SQLite 完整性、外键、记录数和媒体文件，再停止服务并选择恢复时间点；不要直接覆盖正在运行的数据库。生产回退默认只回退代码和配置，schema保留前向兼容。历史58条孤儿记录已放在 root 私有隔离数据库中，未猜测归属或不可恢复地删除。

## 容量与性能

`python tests/performance.py` 只创建临时数据库与本机18001端口，结束后清理。基准为100个模拟用户、每人365天、109500条记录、20并发400次普通读写；AI推理不混入普通接口指标。它验证服务端应用与 SQLite，不代表公网时延、浏览器 LCP/CLS 或未来所有负载。

## 签名与设备验收

`sign-release.py` 生成旧证书到正式证书的轮换证明。Android 9+正式证书 SHA-256：`c6b15363badb1035563e5c731874fb78d4b08eeb88e223ced625faaa8fbd738f`。历史签名只用于低版本兼容，不能称所有版本已摆脱旧证书。

真机测试入口：`com.fitcoach.shapemaster.test/androidx.test.runner.AndroidJUnitRunner`。测试APK和正式APK都需按兼容签名安装；vivo超级守护的安装授权由机主在手机上操作。测试用合成账号与合成图片，截图仅记录测试账号。不能把本地HTTP协议夹具称为手机真实模型推理。

旧客户端升级兼容：HTTP `/version.json` 仅返回公开版本元数据，安装包地址为HTTPS；这是为不跟随跨协议重定向的旧Java客户端保留的升级引导，不提供登录/业务/照片接口。其余轻塑HTTP入口跳转HTTPS。旧客户端在升级前自身发出的HTTP请求无法由服务端追溯加密，应尽快安装正式版本。
