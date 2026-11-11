# r194 / 2.4.5（78）：一轮安全审计与修复

2026-11-11。对网页、下载入口、Android 包和服务端做了一轮以“注入与越权”为重点的检查；修掉的不只是配置问题，也包括两条真实的 XSS 入口和一条公开的 API 侦察面。

## 检查范围与方法

- **线上只读探测**：HTTPS/TLS 版本与证书、HSTS/安全响应头、HTTP→HTTPS 跳转、`version.json` 与实际 APK 的 MD5/SHA-256、签名方案、常见敏感路径（`/server.py`、`/.git`、数据库、备份、上传目录、`/docs`、`/openapi.json`）。
- **本地真服务攻击**：用独立临时数据库启动真实 `server.py`，实测 SQL 注入、存储/反射型 XSS、路径穿越、IDOR、签名链接篡改、上传伪装、CORS、强更门、WS 伪造票据、邮箱枚举和匿名接口限流。
- **静态审计**：服务端路由/鉴权/数据库/文件/外部请求；前端所有 `innerHTML` 与内联 `onclick` 字符串；Android Manifest、WebView 桥、导出组件、备份、明文、FileProvider；CI/部署脚本的路径与密钥处理；Python/Android 依赖的公开公告。
- **服务器配置只读核对**：监听地址、文件权限、服务 systemd 沙箱、QA 残留。

## 已确认并修复

### 1. AI 搜索结果来源行 XSS（存储型）

`/api/ask` 把第三方搜索结果的 `host` 原样拼进返回的 HTML，前端又用 `innerHTML` 渲染。已改为：来源行标题/域名先 `_plain`（剥标签、还原实体）再 `html_escape`；`items` 也改成纯文本，避免第二个出口漏网。`tests/test_security_hardening.py::test_ai_source_rows_are_escaped` 用带 `<img onerror>` 的假搜索结果覆盖。

### 2. 评论区 @ 面板昵称 XSS（DOM 型）

`renderAtList` 曾把昵称经 `escapeHtml` 后放进 `onclick="pickMention(3,'昵称')"`。`escapeHtml` 会把 `'` 转成 `&#39;`，但浏览器先解码属性再交给 JS，恶意昵称仍能提前闭合单引号字符串。改为按钮只传数字 id，昵称在 `cm.atRows` 里按 id 取（`pickMentionById`）；私信失败重试按钮也改成 `data-rid` + `dmRetrySendFrom(this)`，不再把请求 id 拼进内联 JS。`frontend-integration.mjs` 与 `legacy-frontend.mjs` 各补一条恶意昵称判据。

### 3. 公开的 API 地图

FastAPI 默认把 `/docs`、`/redoc`、`/openapi.json` 暴露在公网，实测 `/openapi.json` 列出 151 条路由与请求体形状。线上不再注册这三条路由；本地排查需显式 `QINGSU_DOCS=1`。

### 4. Pillow 12.3.0 的 JPEG 解码公告

用户上传的 JPEG 会进 Pillow 解码。OSV 对 12.3.0 返回多条公告（含 `ImagingJpegDecode` 堆越界等），13.0.0 全部标记为已修复。`requirements.txt` 与 `requirements.lock` 已钉到 `Pillow==13.0.0`，并新增版本下限判据；`test_integration`、`test_chat_media`、`test_meal_photo` 均在新版本下复跑。

### 5. 匿名/上传接口的可刷面

- `/api/login`、`/api/login/email` 增加按 IP 的 60 次/分钟总闸（原有限流只按“IP+账号”）。
- `/api/account/forgot` 增加 6 次/10 分钟匿名总闸；未绑定邮箱的请求以前完全绕过限流。
- `/api/community/media` 12 次/分钟、周期照片 12 次/小时、头像 20 次/分钟、CSV 导出 6 次/分钟、`/api/food/estimate` 20 次/分钟；`/api/ai/status` 的模型探测结果缓存 10 秒，避免反复烧本机/外部模型。
- 采购清单 `state` 限制 4KB；CSP 报告只读前 8KB，并按 4096 条上限回收去重表，避免匿名报告造成内存增长。
- 搜索结果页读取上限 2MB；本机模型/在线模型/ASR 响应各 1MB 上限；Bing 重定向只允许落在 `bing.com` 及其子域，挡住公开搜索入口的 SSRF 通道。

### 6. 邮箱与账号枚举

- `/api/login/email` 对“未绑定”和“已绑定但验证码错/过期/无验证码”统一回同一句，避免按文案枚举邮箱。
- `/api/login` 对不存在的用户名也执行一次同代价的 scrypt，避免按响应时间筛账号；配合新的 IP 总闸限制 CPU 消耗。
- 密码与分享密钥比较改用 `hmac.compare_digest`。

### 7. 文件与浏览器侧加固

- 媒体文件读取增加 `realpath` 目录边界复核（扩展名白名单之外的第二道门）。
- 响应头新增 `Permissions-Policy`（摄像头/支付/USB 关闭，定位与麦克风仅本站）；`/health*` 加 `no-store`。
- 离线页 `retry` 参数只接受 HTTPS + 本站源/现役域名，挡 `javascript:` 与外部跳转。
- Android 定位授权从 `startsWith` 改为按 URI 解析的精确 host/端口校验；震动上限 1 秒；本机模型回传的 `evaluateJavascript` 文本转义 U+2028/U+2029，避免老 WebView 字符串提前闭合。

### 8. 下载入口

线上 `version.json` 的 `apk_url` 由服务器按 `SITE_BASE` 现算，实测为 `https://scientificexploration.art/qingsu.apk`；下载到的 APK 与清单的 size/MD5/SHA-256 逐字段一致，`apksigner` 验证 v2/v3 签名通过，证书指纹仍为 `c6b15363…`。`make_version_json.py` 的清单默认地址也从 IP 改为现役域名，服务器路由继续保留 `build<45` 从 IP 取清单时回落 IP 的兼容分支。

## 判定与证据

- 新增 `tests/test_security_hardening.py` 8 条（API 地图、响应头与 health 缓存、来源行 XSS、非 ASCII 分享密钥回 404 而非 500、邮箱枚举、匿名找回限流、社区图片限流、Pillow 下限）。
- `tests/frontend-integration.mjs`、`tests/legacy-frontend.mjs` 增加 @ 昵称 XSS 判据；`legacy-frontend` 356 条全绿。
- 本地真服务探针（独立临时库）中，SQLi/路径穿越/IDOR/签名篡改/WS 伪造票据均未绕过；来源行 XSS 在修复前能复现、修复后消失。
- `tests/test_integration.py` 64 条、`tests/test_content_security.py` 24 条、`tests/test_native_media_contract.py` 21 条、`tests/test_optimization_security.py` 24 条、`tests/test_multiprocess.py` 25 条（Redis 在场）全绿。
- Android `assembleRelease lintRelease` 成功；lint 只剩依赖版本/图标形状提示，没有安全错误。
- 生产只读核对：8000/8055/8100 只绑 Docker 桥，不对公网；`/opt/qingsu/keys` 700，签名/WS 密钥 600，turn/webpush 密钥 640；`/opt/qingsu/backups` 700 root；服务以 `qingsu` 运行，`ProtectSystem=strict`、`ProtectHome=yes`、`NoNewPrivileges=yes`、只可写 data/uploads。

## 明确没有改的边界

- **CSP 仍是 Report-Only**：页面还有 186 处内联处理器，按既有设计，只有“内联清零且报告窗口无拦截”才允许转正式策略；本轮不拿界面赌这个开关。XSS 修复走的是输出转义，不是靠 CSP 兜底。
- **App 内 API 主机仍是 IP**：下载入口已统一到域名，但 API 流量换域名要单独评估旧客户端、证书链和备案状态，本轮未顺手改。
- **线上 `min_build` 仍为 0**：强更门处于人工刹车状态；抬门需要先在真实设备上确认用户能装上新包，本轮不擅自锁旧版。
- **未做**：第三方依赖之外的 OS/内核审计、管理员后台代码的独立渗透、真机重装/省电策略/多系统矩阵。`tests/test_chat_media.py` 本地需要显式 `QINGSU_FFMPEG`/`QINGSU_FFPROBE`（CI 装了系统 ffmpeg）。

## 发布与回读

（部署后回填：CI run、生产 `/docs`/`/openapi.json` 404、APK 指纹、`security.txt` 之外的入口一致性、回退快照。）

## 打开与入口

[软件](https://scientificexploration.art/) · [下载 APK](https://scientificexploration.art/qingsu.apk) ·
[后台](https://scientificexploration.art/ops/)
