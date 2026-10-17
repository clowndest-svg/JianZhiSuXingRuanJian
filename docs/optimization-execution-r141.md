# r141 执行记录：品牌位换成真 logo，顺带查出通知栏一直挂着系统警告三角

日期：2026-10-17。版本：versionCode 24 / 1.9.2。承接 r140。

## 1. 机主框出来的那一处，以及顺着查出来的另外几处

顶栏那颗绿底白字的「塑」换成启动图标。查了一圈，还有三处同样是"品牌位但不是品牌"：

| 位置 | 原来是什么 | 现在 |
|---|---|---|
| 顶栏 `.brand-icon` | 渐变方块 + 文字「塑」 | `<img src="app-icon.png">` 34×34 |
| 下载弹窗头部 | 📱 emoji | 同一张 logo，带一圈白边（绿底上黑图不描边会显得陷进去） |
| 访客监督页标题 | 纯文字 | 标题前挂 40×40 logo |
| **通知栏小图标** | **`android.R.drawable.ic_dialog_alert`（Android 自带的警告三角）** | **自己的白色剪影 `ic_stat_qingsu`** |

最后一条是这轮真正的发现：每日提醒和外卖拦截通知在状态栏里长得跟系统告警一模一样，
跟这个 App 没有任何视觉关系，而且这个洞不影响任何功能，所以从来没被任何判据或人眼抓到过。

## 2. 通知小图标为什么不能直接拿启动图标用

Android 会把通知小图标**整体染色**（状态栏里只保留 alpha 通道），所以只能给
「白色剪影 + 透明底」。直接塞彩色启动图标，在状态栏里会糊成一团。
`scripts/make-icons.py` 因此多产四档 `drawable-{m,h,x,xx}dpi/ic_stat_qingsu.png`，
alpha 取自 artwork 明度（黑底变透明、人形与绿环保留），24/36/48/72 px，
实测非透明像素约 74%。

## 3. 判据

新增 7 条静态判据 + 2 条真机判据，判据规模 **后端 329 + 前端 237 + 集成 27 + AI 契约 6**，全绿。

- 静态：顶栏必须是 `<img>` 且不许再出现 `class="brand-icon">塑<`；下载弹窗头部不许还有 📱；
  监督页要有品牌图；`app-icon.png` 必须有显式公网路由；通知小图标不许出现 `android.R.drawable.`；
  `ic_stat_qingsu` 四档都在；脚本必须从同一张 artwork 生成剪影。
- 真机：顶栏图 `complete && naturalWidth>=64`（图没加载出来是最容易犯的错）、
  宽高差 ≤1px（防被拉成椭圆）、边长 28–44px；下载弹窗头部图同样验一遍。截图 `brand-header.png`。
- **一条判据差点没标定成功**：通知图标那条我一开始用磁盘直读，`--mutant=HEAD` 时看到的
  却是已经改完的 `WebAppInterface.java`，于是它在旧版上是绿的——等于从来没被标定过。
  改成跟着反样本 `git show` 取文件后，旧版当场红。这个错在同一份台子里已经犯过一次。
- 反样本 `--mutant=HEAD`：后端红 **5** 条（顶栏文字占位、下载弹窗 emoji、监督页无图、
  通知借用系统图标、构建号与 gradle 不同源）。
  另有两条（四档图标文件在不在、脚本会不会生成）是**产物/脚本检查**，不跟随 `--mutant`，
  在旧版上恒绿是实情，不当作标定证据。
- 完整回归 `releaseUserJourney` 与 `toolDialogsAreReadableOnDevice` 在 MuMu 上均 `OK (1 test)`。

## 4. 上线与对账

- 部署 `r141`，备份 `/opt/qingsu/backups/release-20261017-204332`，`source_revision=92542ed7…`；
  归档两端 MD5 一致（`2880fc74…`）。
- `/health/ready` 回读 `r141` + 同一提交号，`min_build=0`（强更刹车仍踩着）。
- 包：`version_code 24 / 1.9.2`、`size 5,962,201`、`sha256 1e31ca4b8902…`，
  公网下回来与仓库逐字节一致。
- 资产：`app.js 217d73`、`features.js 03f7c4`、`style.css 78e868` 线上与本地一致；
  `index.html` 两端不同是设计如此（出口挂 `?v=`），已确认线上首页确实出现
  `class="brand-icon" src="app-icon.png"` 与 `class="brand-mark" src="app-icon.png"`，
  且 `>塑<` 已经不在页面上。
- `verify_live.py` 8 项通过。测试账号：这次先 `SELECT COUNT(*)` 再列全量（不再用会被截断的管道），
  删掉 115、116 两个设备夹具，`users_left=[tiangang,木木]`、`foreign_key_check` 0 条、
  真实账号各表行数前后一致、`integrity_check` ok。

## 5. 仍未覆盖（不写成通过）

- **通知栏小图标在真实状态栏里长什么样没看过**：vivo 没连，MuMu 的状态栏截图也不代表各厂商染色；
  只验到资源存在、代码引用它、剪影 alpha 合理。
- 图标在圆形/方形/圆角遮罩下的观感只在 MuMu 桌面上看过一张（r139 的 `mumu-launcher-icon.png`），
  各厂商桌面（小米/华为/三星）的遮罩与自适应处理仍未覆盖。
- 观感依旧没有真判据：这次钉的是"图加载出来了、是方的、尺寸在范围内、没有文字占位"，
  "好不好看"仍然是我看了截图说的。
- 强更门本轮依旧没抬（`min_build=0`）。
