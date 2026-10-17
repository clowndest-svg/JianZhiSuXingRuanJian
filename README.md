# 轻塑：Android 与网页记录工具

当前版本：r138 / Android **1.8.3（21）**。

- 网页：https://124.220.54.64/
- 安装包：https://124.220.54.64/qingsu.apk
- 版本与指纹：https://124.220.54.64/version.json
- 就绪检查：https://124.220.54.64/health/ready

支持本人饮食、体重、训练、饮水和周期记录；训练动作配火柴人关键帧演示（按姿态表逐帧插值画出关节轨迹，矢状面区分远近侧、发力肌群高亮；不宣称是真人示范，也不再依赖 WebGL）；提供历史修正/删除/补录、份量确认、分享权限与撤销、完整日确认、离线草稿、Android 每日提醒及 CSV 保存。所有热量、预算、宏量和消耗均为估算；系统不分析照片，也不提供个人诊疗或营养处方。

## 构建与测试

需要 Python 3.11+、Node.js、JDK 17、Android SDK 34。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python tests/test_integration.py
.venv/Scripts/python tests/test_ai_contract.py
.venv/Scripts/python tests/legacy-backend.py
node tests/legacy-frontend.mjs
node tests/frontend-integration.mjs
./gradlew.bat assembleRelease lintRelease
```

`requirements.lock` 锁定本轮验证的完整 Python 依赖。CI 执行真实框架集成测试、语义契约、原回归台、前端逻辑和 Android 构建/lint。CI 只生成未签名 APK；生产签名在受保护的发布机完成。

```powershell
python scripts/sign-release.py --input app/build/outputs/apk/release/app-release-unsigned.apk --output qingsu.apk
python make_version_json.py
python scripts/package-release.py --output release.tar
```

生产 API 默认使用 `https://124.220.54.64`；隔离 QA 可通过 Gradle 属性 `qingsuApiBase` 指定完整入口，**QA 包不得作为正式安装包发布**。网页使用同源 API，支持服务端配置的隔离路径。

## 数据、隐私与运维

- `server.py` 负责 HTTP/数据库编排；`app_modules/` 分离分享/历史功能、营养估算、预算公式、模型输出校验与 Redis 客户端。
- 独立会话有效期30天；退出仅撤销本会话。个人模型回答不进入全局知识库。
- 分享默认只开放体重与训练，有效期7天；可选择字段、关闭、续期和轮换密钥。公开照片链接随权限撤销立即失效。
- 上传图片校验真实格式、大小和像素，重编码并清除 EXIF；私人媒体不再公开挂载。删除当前照片会移除历史周期引用，备份按保留期轮换。
- `sw.js` 仅缓存静态外壳；API、监督链接和照片不进入 Service Worker 缓存。草稿与最后同步快照保存在当前设备，按账号隔离，退出清除。
- 静态资源按内容哈希挂一年强缓存：文件没变 URL 不变，改一个字节 URL 立刻换，重新部署不再逼老浏览器重下一遍安装包。
- 弹窗是真正的对话框：焦点进弹窗、Tab 不外逃、ESC 关闭、关闭后焦点归位；背景对读屏和点击同时屏蔽。
- 达标与否与完整日确认状态都用文字表达，不依赖颜色；本机登录信息损坏时清掉并说明原因，不停在"看着像登录了却一格数据都没有"的页面。
- 正式签名通过 v3 lineage 兼容旧安装；Android 9+ 使用正式证书，Android 7/8 兼容路径仍使用历史签名。私钥、密码和恢复密钥均不进仓库。
- 服务器使用专用账号、SQLite WAL、原子限流和有界 Redis 降级；8000不对公网提供服务。
- IP 可信证书采用短有效期证书，每日两次检查续期。数据库/媒体每日备份，服务器保留14天；本机每日拉取加密副本并恢复验证，保留30天。

详细操作见 [运维手册](docs/operations.md)；变更与验收见 [r134 执行记录](docs/optimization-execution-r134.md)、[r132 执行记录](docs/optimization-execution-r132.md)、[r131 执行记录](docs/optimization-execution-2026-10-16.md) 和 [原始审查方案](docs/optimization-plan-2026-10-16.md)。原审查证据与 r130/r131 记录属于历史快照，不能当作 r132 当前状态。

**强制更新**：`/api/*` 业务请求必须带 `X-App-Build`。构建号由 `make_version_json.py` 从 `build.gradle` 同步进 `app.js`，并回查已打出来的包里那份 `assets/app.js`；低于清单里的 `min_version_code` 或缺这个头（旧包根本不会发）一律 403 `update_required`，客户端整屏盖住并给出下载地址。
访客侧 `/api/public/*` 与 `/api/cheer` 不参与强更——把来看监督大屏的人挡在门外没有意义。默认策略就是"只许最新版"，所以发版即抬门；要放行旧版，在服务器上 `python3 /opt/qingsu/set-min-build.py 0|22|auto|show`，改完会独立回读 `/health/ready` 核对服务真的读到了，门的状态与还在调用的构建号也都在 `/health/ready` 里可见。

## 验证边界

真实设备为 vivo V2309A / Android 16。单机实测不能代表所有 Android 版本、桌面浏览器、省电策略或整夜锁屏行为。相机实拍、系统文件选择器实际确认、多系统矩阵、放大字号后的可读性与键盘遮挡仍需人工验收；原生按钮的回车激活在自动化按键通道下不可验证（该通道只送非可信事件），也已留作人工项。不将编译或回调测试写成这些项目已经通过。提醒为系统非精确定时，可能被厂商省电策略延迟。一般成人之外的适用情况不自动生成成人预算。

旧客户端升级兼容：HTTP `/version.json` 仅返回公开版本元数据，安装包地址为HTTPS；这是为不跟随跨协议重定向的旧Java客户端保留的升级引导，不提供登录/业务/照片接口。其余轻塑HTTP入口跳转HTTPS。旧客户端在升级前自身发出的HTTP请求无法由服务端追溯加密，应尽快安装正式版本。
强更门的拦截效果由真实中间件用例加四条变异覆盖（缺头当新号、把访客接口一起挡、运维刹车不生效、门扩到静态件——各红一条）。本轮没有抬起线上 `min_build`，所以"已装的 1.8.3 在真人手机上被挡"没有实拍证据：抬门前得先确认真实用户装得上新包。

