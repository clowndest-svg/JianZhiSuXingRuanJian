# 3D 人体模型来源与授权

## cesium_man.glb

- 文件：`cesium_man.glb`（复制自 `CesiumMan.glb`，未改动几何）
- 来源仓库：KhronosGroup / glTF-Sample-Models，路径 `2.0/CesiumMan/glTF-Binary/CesiumMan.glb`
- 上游作者：Cesium（作为 glTF 兼容性测试模型捐赠）
- 许可证：**Creative Commons Attribution 4.0 International（CC-BY 4.0）**
  - 允许：商用、修改、再分发
  - 要求：署名
  - 依据：该模型目录下 `README.md` 的 "License Information" 原文
    > Donated by Cesium for glTF testing. Please follow the Cesium Trademark Terms and Conditions.
    > This model is licensed under a Creative Commons Attribution 4.0 International License.
- SHA-256：`659349b0a374b73d5362a61070039bc8601401bbdeacbece4f3680fb4bfd41b0`
- 体积：490956 字节，19 根骨骼，单网格 3273 顶点

### 实际用到的是它的骨骼，不是它的网格

`body3d.js` 加载这个模型后把蒙皮网格整体 `visible=false`，只保留骨架：
骨长与关节位置取自真实人形（躺姿、屈膝这些比例不会靠手搓常数去猜），
外壳则由 `BONE_R`/`JOINT_R` 两张表按关节现算圆柱+球。原因是这份 2013 年的
兼容性测试人台在摆出非 T 姿时蒙皮会塌陷成一团，观感比 2D 画法还差。

### 署名位置

CC-BY 要求署名，本项目在 App 与网页的「关于/说明」区域以及本文件三处注明：

> 3D 人体模型 CesiumMan © Cesium，CC-BY 4.0（Khronos glTF-Sample-Models）

同时须遵守 Cesium 商标条款：不得把本产品声称为 Cesium 出品或与 Cesium 官方相关。

## vendor/three.module.js 与 vendor/GLTFLoader.js

- 来源：three.js **r160.1**（`three@0.160.1/build/three.module.js`、`examples/jsm/loaders/GLTFLoader.js`）
- 许可证：**MIT**（Copyright 2010-2024 three.js authors）
- 本地改动：仅把 `GLTFLoader.js` 顶部的裸模块说明符 `from 'three'` 改写为
  `from './three.module.js'`，以便在 APK 内通过 WebViewAssetLoader 以相对路径离线加载
  （ES Module 在 `file://` 下会被 CORS 拦截，本项目页面已由 `WebViewAssetLoader` 以
  `https://appassets.androidplatform.net/assets/` 提供，故可正常使用模块）。
- 不做 tree-shaking、不升级不降级：换版本必须重新验证 3D 演示。

## 为什么不是别家模型

- Mixamo：可直接使用但**不允许把原始角色/动画文件单独再分发**，且下载需 Adobe 账号，
  资产来源难以在仓库里留证。
- Quaternius：早期包为 CC0，站点现已改挂 **QAL v1.0**（可免费商用、无需署名，
  但不得把素材本身作为独立资源再分发），且分发渠道在 itch.io，直链与版本难以固定。
- Kenney：3D 包以道具与场景为主，没有带骨骼的人形。
- three.js examples 里的 `Soldier.glb`（2.16 MB，标准 Mixamo 命名）视觉更细，
  但该仓库未对这个资产单独声明许可，来源难以坐实；本项目要把授权写死在仓库里，
  所以选了条款明确的 CC-BY 4.0 模型，并把体积从 +3.5MB 压到 +1.9MB。

## 换模型时要改什么

骨骼映射不靠模型里的名字猜，而是集中在 `../body3d.js` 的 `BONES` 一张表里：
每根语义骨写清"模型里的骨骼名 + 从哪个关节到哪个关节"。`body3d.js` 加载后会
1) 校验 17 根骨骼是否齐全，缺任何一根就整段退回 2D 画法并给出原因；
2) 校验绑定姿态本身站不站得住（头在骨盆上方、膝在髋与踝之间）——
   映射写错时画面照样能渲染，只是画出一个蜷起来的团，所以这一步不能省；
3) 每帧统计真正被驱动的骨头数，一根都没驱动时不冒充动画生效。
