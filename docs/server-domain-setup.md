# scientificexploration.art 服务器维护

2026-11-02：主域名使用轻塑，网站备案号为湘ICP备2026050129号-1。
首页和介绍页的备案链接已同步到 `app/src/main/assets`，以后正常发布即可保留。
本次为静态页面与服务器配置维护，没有重新构建 APK 或修改业务发布标签。

## HTTP 网关持久化

将 `scripts/provision-release-http.py` 上传到服务器，以 root 执行。
脚本读取现有配置，保留发布清单、ACME 验证、旧版 `/version.json` 和域名跳转，
生成 `/opt/xiaoye-release/compose.yaml`，并将 Nginx 配置存入
`/opt/xiaoye-release/nginx/default.conf`。

配置目录整体挂载为可写，兼容既有发布和回滚脚本使用的 `docker cp`；静态文件仍只读。
镜像固定到当前已安装镜像的摘要，不拉取新版本。脚本在切换前备份，实际重建两次，
每次核对三个清单内容和 HTTPS 跳转，失败时恢复原容器。
原容器停用自动重启后作为恢复副本暂存，不再占用 80 端口。

以后重建使用：

```sh
docker compose -f /opt/xiaoye-release/compose.yaml up -d --pull never
```

不要直接用不带挂载的默认 Nginx 镜像替换容器。
TLS 入口已有 `/opt/qingsu/tls/default.conf` 与证书目录挂载。
证书续期由现有 `qingsu-cert-renew.timer` 每日运行两次。

## 验证

```sh
runuser -u qingsu -- env PYTHONDONTWRITEBYTECODE=1 \
  QINGSU_KEY_DIR=/opt/qingsu/keys python3 /opt/qingsu/verify-domain-live.py
```

此脚本会在生产服务创建两个唯一命名的临时账号，只让它们相互发消息、关注和呼叫；
结束时按精确账号清理数据库记录。验证 WSS、文字投递、呼叫接听、ICE 转发与挂断，
并检查 TURN 凭据可用，不代表麦克风音频或公网 TURN 媒体穿透已验证。
现有 `verify_live.py` 还覆盖注册登录、记录、分享访问边界、会话注销及真实媒体上传。

## 外部待办

- 用户确认公安备案已提交，等待审核；拿到公安备案号后再添加对应链接与图标。
- 当前 ADB 无设备，安卓实机、真实麦克风和双端通话留待设备到位验证。
- 小夜清单已按实际 r131 包体校验同步；下载地址留空遵循原有人工交付设计。

服务器维护记录位于 `/opt/qingsu/domain-delivery-20261102.md`。
