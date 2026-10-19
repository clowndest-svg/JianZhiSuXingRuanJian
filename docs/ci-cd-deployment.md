# GitHub Actions 自动部署

主应用仓库在推送 `main` 后会依次构建 Android、运行现有后端与前端集成检查，全部通过后才进入生产部署。Pull request 只构建和检查，不读取生产环境密钥。

部署任务会比较本次提交与线上版本：只改后端或网页时，复用线上已签名 APK、版本清单和对应的 `app.js`；修改 Android 源码时，要求 `app/build.gradle` 的 `versionCode` 高于线上版本，再用生产签名密钥签包。签名完成后会检查 APK、H5 构建号和版本清单一致，并在服务器内网隔离端口和临时 QA 数据库验收，再切换生产代码。QA 不改生产 Nginx。服务器发布脚本会保留代码、配置与数据库备份；生产冒烟检查失败时恢复旧代码并保留线上数据库。

## GitHub 环境和 Secrets

仓库需要名为 `production` 的 GitHub Environment，只允许 `main` 分支部署。密钥放在此环境的 Secrets：

- `QINGSU_CI_SSH_KEY`：专用 `qingsu-ci` SSH 私钥。不要使用个人 root 登录密钥。
- 主应用仓库另需 `ANDROID_SIGNING_BUNDLE_BASE64`：Base64 编码的 gzip tar，内含 `keys/release.p12`、`keys/password.txt`、`keys/signing-lineage.bin` 和 `keys/legacy-debug.keystore`。私钥材料只能通过 GitHub Secrets 传入运行器，不提交到仓库。

Android 产物只在可信 `main` 部署任务中解码签名包。Android 源码发布必须递增 `versionCode`；CI 会拒绝与线上版本相同或更低的构建号。

## 服务器权限

`qingsu-ci` 账号只能上传到 `/opt/qingsu/ci-incoming`，并且 sudo 仅允许调用 `/usr/local/sbin/qingsu-ci-deploy`。该入口校验归档 SHA-256、拒绝链接和越界路径、串行化发布，并只接受 `main` 或 `admin` 两种目标。主应用成功发布后会更新服务器入口；发布备份保留在 `/opt/qingsu/backups`。

后台仓库 `JianZhiSuXingRuanJianHouTai` 有自己的工作流：先运行隔离的运维 API 测试，再仅更新线上 `admin_api.py` 与 `console.html`，重启并以只读健康接口和受 Basic 认证保护的 `/ops/` 页面验证。失败时自动恢复这两个文件。

线上 SSH 主机指纹固定在 `.github/deploy_known_hosts`。如服务器更换主机密钥，应先通过独立可信渠道核验，再更新该文件。
