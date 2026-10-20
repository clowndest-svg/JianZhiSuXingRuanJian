# r161 / 2.2.0（45）交付记录

2026-10-20，Asia/Taipei。主应用、后台、网页和APK已上线，域名按用户确认留待备案后启用。

## 当前入口与代码

- [网页](https://124.220.54.64/)、[APK](https://124.220.54.64/qingsu.apk)、[后台](https://124.220.54.64/ops/)、[介绍与教程](https://124.220.54.64/about)。后台继续使用现有双层鉴权。
- 主应用代码：`64c590141ec3b1960583d531329a49e1310c0c65`，生产 release `r39408620022`。[构建、集成与部署全部成功](https://github.com/clowndest-svg/JianZhiSuXingRuanJian/actions/runs/39408620022)。
- 后台代码：`97e3cbea3ee1c89dd80c6f3392b4a22df5db4603`。[39项测试与部署成功](https://github.com/clowndest-svg/JianZhiSuXingRuanJianHouTai/actions/runs/39408628840)。
- 本记录所在的后续提交仅同步线上签名APK、生成清单和交付证据，使用 `[skip ci]`，不改变上述已部署源代码。

## 已交付与验收

新增7/30天私有回顾及PNG导出、共同目标、网页安装更新引导、介绍/教程/隐私页、浏览器会话绑定消息订阅；后台新增活动入口/待接入域名与发布状态、SMTP配置和连接认证检查，完善跨站写入拒绝及审计脱敏。实现范围和本地测试见 [执行记录](optimization-execution-r161.md)。

- 线上 `2.2.0 (45)`，APK 5,408,933字节，SHA-256：`c94a3886569fb39ff9b7e498863c2f7e584343248fb5752f1f930601b39b7cad`。
- 正式签名SHA-256：`c6b15363badb1035563e5c731874fb78d4b08eeb88e223ced625faaa8fbd738f`；v2/v3校验通过，与现役发布证书一致。
- 根目录 `qingsu.apk` 和 `app/src/main/web_version.json` 已从生产同步；APK的13项内置资源与仓库资源一致（文本按Git的LF规范比较）。生产四项主要网页资源与APK字节相同。
- 首页、介绍页、共同目标脚本、PWA清单、Service Worker、二维码、站点地图、robots均HTTP 200；旧客户端HTTP版本清单仍返回HTTPS下载地址。
- 后台公开页面与服务器文件SHA-256均为 `6f1f15fd61d7d3a1056d21dcc51e0b8321b1d2729db482d61faf62e0d5cd2b3f`。
- 应用、后台、模型服务及备份/证书续期/监控/推送定时任务均active；推送worker最近执行退出码0；VAPID私钥权限640 root:qingsu。健康检查正常，密钥未重建。
- 最终监控无5xx、SQLite锁冲突或缓存降级；这是发布后短时检查，不代表容量测试结论。
- CI已完成隔离候选验收和生产API冒烟；QA服务、配置与临时数据已清理。保留既有 `min_build=0` 运维覆盖，未强制锁住旧安装用户。
- 同服务器其他应用 `/latest.json`、`/latest-extensions.json` 在HTTP上的哈希与发布前一致。

## 备份与清理

上线前代码/数据备份：`/opt/qingsu/backups/release-20261020-184519`。后台备份：`/opt/qingsu/backups/admin-console-ci-39408628840-412d8f5a46ab`。

上线后加密备份 `bundle-20261020-184759.p7m` 已下载至本机受保护的 `.private-backups`，私钥留在仓库外。恢复验证：SQLite integrity_check=ok、外键异常0、图片文件2；临时明文恢复文件已删除。

服务器两轮清理共71项旧目录/压缩包/过时静态文件，合计540,795,257字节（约516 MiB，按待删文件逻辑大小统计）；保留 `r39408620022`、`r39392249378`、`r39386289394`。业务数据库、上传内容、密钥和正式备份保留；过时在线静态/后台副本在删除前另作备份。清理后重新执行线上资源、APK、健康与其他应用清单校验。服务器临时ACME探针也已删除。

本地永久删除被自动审批拦截，改用可恢复归档：7项临时目录/旧产物已移出项目至 `D:/RuanJian/ShuJuChunChu/qingsu-cleanup-archive/r161-20261020`，本地预览进程均已停止。结果见 `release-evidence-r161/local-cleanup.json`；当前签名APK、源码、交付截图、受保护备份和外部签名目录保留。

## 域名备案后如何启用

用户确认 `scientificexploration.art` 尚未备案，后续自行办理。当前权威DNS指向正确IP，但公网域名HTTP被腾讯云302到备案拦截页，不能通过ACME校验；证据见 `domain-block.json`。不再反复改DNS或申请证书。

1. 登录 [腾讯云ICP备案控制台](https://console.cloud.tencent.com/beian)，选择网站/域名，填写 `scientificexploration.art`，由系统判断首次备案类型。
2. 核对账号/域名实名认证与主体资料、选择符合要求的云资源，按实际省份和网站内容填写资料，完成核身、提交及短信核验，等待审核。具体材料与流程以 [腾讯云首次备案官方指引](https://cloud.tencent.com/document/product/243/97668) 为准；网站和APP有各自的服务类型入口，按实际服务分别处理。
3. 备案通过且腾讯云接入校验解除拦截后，再启用正式域名。已同步 `/opt/qingsu/enable-domain.py`，执行前先确认公网校验恢复；脚本成功取得可信证书、检查完整Nginx配置与HTTPS后才切换 SITE_BASE，含www规范跳转、二维码/分享入口和后续部署的持久配置。启用时还需按审核要求展示备案信息并重新验证客户端升级路径。

该脚本本次未激活域名，也未安装无效证书。现有IP入口用于本次发布验证，并不替代备案手续。

## 尚未验证或接入

- 无ADB设备，未实测真机安装、系统图片保存确认、苹果主屏安装或真实浏览器/锁屏推送到达；安卓厂商离线推送未接入。
- SMTP没有真实账号，配置与检查能力已完成，线上保持configured=false、enabled=false，未发送任何邮件。
- UI截图来自本地合成账号；后台浏览器夹具模拟外层Basic，真实双层鉴权由API测试覆盖。最终公网浏览器预览超时，线上HTTP/API/资源与APK核验已通过，不将本地截图当作公网浏览器验收。

原始聚合证据见 [release-evidence-r161](release-evidence-r161/) 中的 production-live、admin-live、workflow/jobs、apk-signature、apk-source-parity、backup-restore、server-cleanup 与 local-cleanup 文件。证据不含账号、邮件密码、私钥或推送订阅端点。
