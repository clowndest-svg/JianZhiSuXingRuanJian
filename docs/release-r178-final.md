# r178 / 2.2.17（62）更新弹窗长说明真的能上下滑

## 现象与根因

机主 10-22 14:03 实拍：更新到 2.2.16 的弹窗里，说明写到「…就把今」被硬生生截断，底下看不到，也滑不动。

根因是 r174 那次修法的**封顶加错了对象**：

```java
body.setMaxHeight(屏幕高 × 0.52);      // ← 加在 TextView 上
ScrollView scroll = new ScrollView();  // ← 里面这个容器永远撑不满
scroll.addView(body);
```

文本自己把高度裁到 52%，于是 ScrollView 的内容从来没有超过视口 —— **结构上"有滚动容器"，实际上滑不动**。当时的静态判据只查「有 ScrollView」「`setView(scroll)`」，所以全绿。这是「CI 绿 ≠ 真机好」的又一例。

## 改动

- 高度封顶改加在滚动容器上：新增 `ScrollCap extends ScrollView`，在 `onMeasure` 里把高度限成 `AT_MOST 屏幕高 × 0.52`。正文按真实高度撑开，超过视口就交给滑动。
- 滚动条常显（`setScrollbarFadingEnabled(false)`），让人看得出还能往下滑；滑到底时截图里滚动条也走到底。
- 建弹窗抽成 `UpdateManager.showUpdateDialog(...)`，让 Android 测试能走**产品同一个函数**量数字，而不是在测试里手搓一遍控件。
- 新增真机判据 `UpdateDialogTest`（两条）：
  - 合成 22 条长说明：视口 468px、内容 1868px → 必须滑到 `scrollY=1400`（=1868−468），到底后不能再往下滑；`content >= text_layout` 证明正文没被 TextView 自己裁掉；两个按钮底部 638 ≤ 窗口 668。
  - **线上清单的真实文案**（r177 那份，262 字）：视口 468、内容 536 —— 确实溢出 68px，正是被吃掉的那一截；现在滑到底 68px 全看得到，按钮仍在屏内。
- 静态判据同时补硬：钉住「封顶加在滚动容器而不是 TextView」（禁止 `body.setMaxHeight`）、滚动条常显、真机判据文件存在。改动前的 HEAD 在这三条上是红的（622 条里红 4）。

## 验证

真机（MuMu，Android 12 / API 32）：`am instrument -e class ...UpdateDialogTest` → **OK (2 tests)**，3.233s。截图 `update-dialog-top.png`（停在第 4 条、滚动条在上方）与 `update-dialog-bottom.png`（第 22 条 + 末句「安装仍需要你在系统设置里放行。」、滚动条在下方）。

本地：后端 622/622（含新增 3 条）、前端 355/355、集成 64/64、更新文案 3/3、chat-ui 全绿。

CI 与线上：run `r39734173380`（#92，source `c31ecdd`）android / integration / deploy 全绿；备份 `/opt/qingsu/backups/release-20261022-143606`；线上 `version.json` 62 / 2.2.17，APK SHA-256 `9d2c11b9a90f54da…`，下载复算与清单一致，仓库已同步同一字节；生产自检 18 资源 + 媒体 3 项 + API 12 项全通过、`remaining_users=2`；监控 14:36 窗口 CPU 2.2%、内存 70.0%、swap 13.6%、磁盘 35%、`errors_5xx=0`、p95 51.9ms、`problems: []`。

本轮公网没有新增夹具（弹窗判据跑在模拟器上，不写服务器数据）。

## 边界

- 弹窗正文仍是原生 `AlertDialog`，只在 Android 上出现。
- **量数字的方向不是机主那个方向**：MuMu 这台虚拟机的面板是 900×1600、`SurfaceOrientation=1`（横屏），`adb` 改 `user_rotation` 不生效（VM 层锁着），所以视口取的是短边——实测视口 468px。横屏是**更严**的一侧：视口更矮、更容易溢出，滑不动在横屏一定在竖屏也滑不动；机主竖屏下视口更高，同一段文案可能整段放得下、根本不需要滑。判据钉的是不变量：正文绝不被自己裁掉（`content >= text_layout`）、一旦溢出就必须滑得到底、两个按钮永远在窗口内——与方向无关。
- 机主手机要看到效果需更新到 62 版：新包的弹窗才是新代码；61 及以下仍是旧行为（封顶加在正文上）。
