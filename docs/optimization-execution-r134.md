# r134 执行记录：3D 动作演示换成真骨骼人体

日期：2026-10-17。版本：versionCode 17 / 1.7.0。
承接 r133（工具栏遮挡）与机主两条反馈：`这能看个屁`（遮挡）与
`3d人物太过臃肿，动作动画看着很不舒服`（观感）。
机主在方案选择时明确要 `下载真实骨骼模型 + WebGL`，没有采纳"重画程序化人体"的建议。

## 1. 做了什么

- `app/src/main/assets/body3d.js`（新增）：加载 `models/cesium_man.glb`，按 `BONES`
  表把 17 根语义骨对应到模型骨骼名，逐骨用"绑定轴→目标方向"的最短弧四元数解算，
  局部旋转 = `inv(父骨当前世界旋转) · Δ · 绑定世界旋转`，骨长始终由模型决定。
- 外壳：模型自带的蒙皮网格整体 `visible=false`，只取它的骨长与关节位置；
  画面上的身体由 `BONE_R`/`JOINT_R` 两张表按关节现算（骨头=圆柱、关节=球）。
  原因写进 `models/CREDITS.md`：那张 2013 年的兼容性测试人台一摆躺姿蒙皮就塌陷，
  比原来的 2D 画法还难看，"用了真模型"不等于"看得清动作"。
- 2D 画块法整体退居兜底：`Body3D.status !== 'ready'` 或这一帧一根骨头都没驱动时，
  照旧画方块并说明原因，不白屏、不假装 3D 生效。
- 视角提示与相位标签在 r133 已挪到左上角竖排；本轮把宽度改成
  `min(calc(64% - 8px), calc(100% - 24px))`，右边界恒等于画布宽度的 64%，
  不再随画布变窄而吃掉厂商悬浮侧栏的位置。
- `server.py` 新增 `/vendor/{name}`、`/models/{name}` 白名单路由（同一份
  `_STATIC_SUBDIRS` 白名单，不做任意路径拼接），`package-release.py` 归档时
  硬要求这两个目录存在。
- 窄屏真 bug：`.chat-input-bar input` 只有 `flex:1` 没有 `min-width:0`，
  `<input>` 的固有宽度约 324px，在 320 视口下把整页布局视口顶到 410px。

## 2. 本轮抓到并修掉的"假绿"

这一节是本轮最主要的产出，逐条记下来，防止下次再用同样的口径自欺。

| 现象 | 为什么是假绿 | 处理 |
| --- | --- | --- |
| 320/360/390 三档实测都报 `innerWidth=410` | 判据把"请求宽度"当"实际宽度"，窄屏档其实量的是同一块屏 | 每档硬校验 CSS 视口宽度等于请求值，切完七个页签后再复核一次 |
| `documentElement.scrollWidth<=innerWidth+1` 一直绿 | 浏览器把布局视口撑到 410 之后，"不溢出"是自我比较 | 根因是聊天输入框；修完后 320 档 scrollWidth 真为 320 |
| 工具栏遮挡判据 `overlayRightFrac=0.69` | `getBoundingClientRect` 是视口绝对坐标，画布左边还有 81px 页面边距，量成了"标签离屏幕左边多远" | 改成按画布自身坐标算，并加"右上角至少留 48px"的绝对口径 |
| `triangles>0 && coverage>6` 判 3D 生效 | 相机被算到 5 亿米外时三角形照样统计，画面是空的；覆盖率对站/跪两种姿势本身差几十倍 | 改成 `fill`（人体占画面长边的比例）+ `ndcMax`（有没有肢体被裁出画面）双判据 |
| 取景距离逐帧逼近，自测拿"上一帧"的距离量"这一帧"的姿势 | 换动作瞬间测出来的 ndcMax 偏小，看着合格其实会裁 | selfTest 先把距离钉到本帧目标值再渲染第二遍 |
| `adb shell rm -rf qa` 之后截图目录里还有上一轮的 `overflow.json` | MuMu 共享存储没真删，旧证据被当成本轮证据读 | 测试开跑前先清自己目录里的 png/json，只留当轮产物 |
| gradle 失败后 `&&` 链断掉，脚本照样打印上一轮日志里的 `AssertionError` | 读的是旧日志文件 | 每轮 instrument 写独立带时间戳的日志，先看退出码再看内容 |
| `scripts/deploy.py` 的 `copy_files` 只搬 `is_file()` | `web/vendor/`、`web/models/` 整目录会被跳过：线上 3D 静默退回 2D，部署流程一路绿灯，`/health/ready` 也报本次提交 | 子目录先整体拷到临时名再换；补静态判据"部署脚本会搬 web 下的子目录"，在 r133 反样本上是红的 |
| `am instrument -e class X#不存在的方法` 返回 `OK (0 tests)` | 0 条测试也是"OK" | 记为口径缺陷；本轮所有跑法都用真实方法名并核对 `Tests run` 数 |

代码层的三个真 bug：

1. `let ... maxZ = 1e9`（应为 `-1e9`）：包围盒上界初值写反，`cz` 恒为 5e8，
   相机距离算到 1.9 亿米，画面全空但 `triangles` 照常统计。
2. 没有目标的骨头（手、脚末端）退回的是**绑定世界四元数**而不是**绑定局部四元数**，
   模型根节点带 Z_UP 旋转时会把父链旋转重复算一次，末端肢体歪出去。
3. 父链一旦中毒（四元数非有限）会顺着骨骼树往下染，一帧内 15 根骨头全变 NaN。
   现在单根退回绑定姿态并计数（`nanBones`），判据要求它为 0，不静默修平。

## 3. 判据与实测

本地三套（`.venv` 的 Python 3.12，不是系统 3.14）：

- `tests/test_integration.py`：25 组全过。
- `tests/legacy-backend.py`：290 条，绿 290，红 0。
- `tests/legacy-frontend.mjs`：225 条，绿 225，红 0。

反样本标定（`--mutant=d9591c9`，即 r133、本轮改动前那一版）：

- 后端 290 条里红 9 条，正好是本轮新增里能对旧版判定的 9 条：3D 模块加载、画块兜底、
  零驱动不冒充、绑定姿态自检、文案区分两种渲染模式、静态子目录白名单、
  信息标签右边界不漂移、聊天输入框 `min-width:0`、部署脚本会搬 web 子目录。
- 本轮还有 1 条不参与该标定："更新说明只讲当前这一版"拿磁盘上的 CHANGELOG 与清单
  现比，属于防今后漂移的一致性判据，在旧版上同样会绿，别当成反样本已验证。
- 前端 225 条在反样本上全绿：**本轮没有给前端加新判据**，3D 的正确性只由真机
  仪表测试和浏览器实测覆盖（见下）。这条要如实记着，不能算标定通过。

真机（MuMu 模拟器 `127.0.0.1:16384`，正式 release 包 versionCode 17，非 debuggable，
与正式包同一套签名）：

- `DeviceSmokeTest#releaseUserJourney`：`OK (1 test)`，30.1 秒。
- 宽度矩阵 320/360/390/768/1440：每档 CSS 视口宽度硬校验通过，
  七页签切换后仍不弹回；`qa/layout.json` 五档 requested==width==scroll。
- 断点覆盖：从 CSSOM 现读断点 `[340, 380, 900]`，四档区间全覆盖，`gaps` 为空。
- 3D：`status=ready`、17 根骨、13 根被驱动、`nanBones=0`、`badFrame=null`；
  训练计划里 4 个动作逐个过 `selfTest`，`fill` 72~84%、`ndcMax` 0.70~0.78、
  `endOn` 0.02~0.49，全部 `ok=true`。
- `WebGLProbeTest#webglActuallyRasterizes`：`OK (1 test)`（真画出一个三角形并
  `readPixels` 回读到中心红、角上清屏色，纹理上限 ≥2048）。

浏览器（本机 `http://127.0.0.1:8199`，Chrome）：

- `/body3d.js`、`/vendor/three.module.js`、`/models/cesium_man.glb` 均 200，
  走的是白名单路由；控制台 0 条消息（无报错、无警告）。
- 4 个动作逐个 `selfTest`：`fill` 71.9~83.5、`ndcMax` 0.699~0.775、`ok` 全 true。
- 3D 初始化耗时（含模型下载与解析）在本地回环下 < 2 秒；公网时延未测。

## 4. 发布物与线上对账

- 提交：`08f61d6ce06511ebd3195575c8fac80768445399`（本轮共三个提交：
  `68cd915` 3D 与窄屏整改、`352a9cd` 部署脚本补搬子目录、`08f61d6` 更新说明截断）。
- `qingsu.apk`：5314529 字节，MD5 `7fcd9db9a216ca619ab5e7e16873f6a1`，
  SHA-256 `82192ea029de095dc92ce882ce1883d3811f93af8f54e4c9095ef9338b8b6dd8`。
  线上回读同一份安装包，前 12 位一致（`82192ea029de`）。
- 归档 `release.tar` 上传后两端 MD5 一致（`e67be44a...`），解压后
  `chown -R root:root`；回退快照 `/opt/qingsu/backups/release-20261017-055335`。
- `GET /health/ready` → `{"release":"r134","source_revision":"08f61d6…","status":"ok"}`，
  与本次提交逐字相同，不是脚本自己跟自己比出来的。
- 3D 依赖逐个比哈希（本地 vs 线上，全部 MATCH）：`body3d.js` `8e49f905e3b5`、
  `vendor/three.module.js` `76dea8151bc9`、`vendor/GLTFLoader.js` `1f9b02acfbf2`、
  `vendor/BufferGeometryUtils.js` `3a6701d824ad`、`models/cesium_man.glb` `659349b0a374`、
  `models/CREDITS.md` `f4666e2c34d8`。
- 缓存：带正确哈希 → `public, max-age=31536000, immutable`；带错哈希 → `no-cache, must-revalidate`；
  无哈希的 `/vendor/*` → `no-cache` 且 `x-content-type-options: nosniff`。
- 路径白名单：`/vendor/requirements.txt`、`/vendor/../../etc/passwd`、
  `/models/%2e%2e/server.py` 全部 404。
- HTTP 入口仍 `308 → https://124.220.54.64/`。
- 浏览器实测线上页（不是本机回环）：登录后 4 个动作逐个 `selfTest`，
  `fill` 71.9~83.5、`ndcMax` 0.699~0.775、`ok` 全 true，
  `solvedBones=13`、`nanBones=0`、`badFrame=null`、单帧 0.5ms，控制台 0 条消息。
- 生产数据收尾：本轮真机与线上验收产生的 23 个 `usbqa*/probe*` 测试账号和
  1 个 `live134*` 账号按 id 逐个删除（含各 user_id 子表），
  删后 `users` 只剩 `tiangang`、`木木`，`pragma foreign_key_check` 0 条，
  两个真实账号在各表的行数删前删后逐项相同。

## 5. 仍未覆盖（不写成通过）

- **真机只有模拟器**：vivo 那台手机本轮没有连着 USB，3D 在真实 GPU（Adreno）上
  的帧率、驱动兼容与厂商悬浮侧栏的实际遮挡情况都还是未知。MuMu 的 WebGL 走
  宿主显卡转译，不能替代真机结论。
- 3D 的**主观观感**没有判据：`fill`/`ndcMax` 只能证明"画全了、没裁"，
  不能证明"好看"。人台外壳是工程折中，不是美术成品。
- 前端静态判据本轮 0 新增，反样本上全绿，等于没有标定过 3D 相关的前端断言。
- 只有当前目标（`female_hourglass`）计划里的 4 个动作被逐个验过；
  其余目标类型的动作列表未展开测。
- 慢放、暂停与拖拽旋转的交互在真机上没有逐条判据（只验证了三个视角按钮能切换）。
- 公网 LCP/CLS 与 4G 下的模型加载耗时未测；模型 490KB + Three.js 约 700KB，
  首屏不阻塞（懒初始化，打开动作详情才加载）。
- 模拟器 `devicePixelRatio` 报 1.5 但窗口宽度按 1.5 精确换算，此前记录的
  "MuMu 钳视口到 410" 其实是聊天输入框那个真 bug，不是环境差异。
