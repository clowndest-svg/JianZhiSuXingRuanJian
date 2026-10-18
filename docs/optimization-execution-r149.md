# r149 执行记录（社区 / 私信 / 意见反馈 / 属地）

机主一次交代四件事，去睡觉前留了一句「按你的推荐想法来完成，全部完成后做全量测试，按流程收尾」。
这份记录写的是**做了什么、代价是什么、哪些没做到**，不写功能清单（清单在 CHANGELOG）。

线上：`release=r149`，`source_revision=d3ca20d24bf3494614b3727d9a77879d79fff146`，
`versionCode 32 / versionName 2.0.0`，回退快照 `/opt/qingsu/backups/release-20261018-134325`。

## 1. 服务器工具的选择：用了 Redis，没装 RabbitMQ

机主说「服务器还有 redis 和 rabbitmq 等工具，尽情使用」。实测结果和这句话不完全一致：

```
$ docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
qingsu-tls      nginx:alpine      Up
qingsu-redis    redis:7-alpine    Up 2 days
xiaoye-release  nginx:alpine      Up 6 days
```

**这台机器上没有 RabbitMQ**，也没有队列消费者。内存是 3655 MB 总量 / 1113 MB 已用 / 2541 MB 可用，
再拉一个 broker 起来不是问题——问题是没有用它的人：这一版所有异步需求（通知、未读、在线）
都能在请求内做完，队列只会多一个要监控、要重启、要占端口的进程。所以按「代价小 + 出问题能知道」
那条硬标准，选了不装，并把这条决定写在这里而不是默默跳过。

Redis 用在三处，每一处都保留进程内兜底，且**兜底状态是可见的**：

| 用途 | 键 | 拿不到 Redis 时 |
| --- | --- | --- |
| 在线状态 | `qs:presence:<uid>`（SETEX 45s） | 只认本进程持有的 socket，别人显示离线 |
| 票据防重放 | `qs:ticket:<nonce>`（SETNX，TTL 60s） | 进程内 set，重启后 30 秒内的旧票据可能再被用一次 |
| 限流 / KB 缓存 | `qs:rl:*`、`qs:kb:*` | 进程内桶（`_mem_buckets`） |

`/health/ready` 里 `chat.redis` 就是这个开关的读数。

## 2. 修掉一个「健康面自己说谎」的 bug

第一次读 `/health/ready` 拿到 `chat.redis=false`，而 Redis 明明是通的。在服务器上按真实代码路径量：

```
PING -> True        # 不是 "PONG"
SETEX -> True
GET -> '1'
EXISTS -> 1
DEL -> 1
```

`redis-py` 给 PING 挂了响应回调，`execute_command(['PING'])` 回来的是 `True`；
而 `redis_up()` 写的是 `v == "PONG"`。后果不是功能坏——presence、票据、限流全都真落在 Redis 上——
**坏的是读数**：`/health/ready` 和 `/api/ai/status` 会一直报「Redis 从未连上」，
下一个人会去查一台好着的机器。判据（`tests/legacy-backend.py`）不再查字符串，
改成把 `_redis_cmd` 分别打成 `(True,True)/(True,'PONG')/(False,None)` 三种形状去调真的 `redis_up()`；
变异标定过：还原成比字符串，只有 `bool` 那一格变红。

## 3. IP 属地：只到省，原始 IP 一个字节都不存

- 读取器自己实现（`app_modules/geoip.py`），不新增运行时依赖。xdb v3：256B 头 +
  8B/项向量索引 + 14B/段（sip4+eip4+dlen2+dptr4）+ 全量缓存 + 二分。
- **踩过的两个坑**：① 字段顺序是 `国家|省份|城市|运营商|国家代码`，不是文档里常见的
  `国家|区域|省|市|运营商`；② IPv4 段表的 sip/eip **按小端存**，正着比字节会把
  202.38.64.1 认成 Australia。两处都修了。
- 准确性拿官方 `py-ip2region 3.0.5` 在服务器上对拍 9 个 IP，逐个一致：
  `114.114.114.114→江苏`、`223.5.5.5→浙江`、`8.8.8.8→United States`、`127.0.0.1→空`。
- 线上库 `geoip={'ok':True,'version':3,'bytes':11122642}`。**没装库时显示「属地未知」**，
  绝不猜一个省出来——这条有判据钉着（`region_of` 任何异常都返回空串，界面走 `cmRegionTag('')`）。
- 隐私口径：`posts.region` / `community_profile.region` 存的是收敛后的省名，
  库里没有任何一列存原始 IP（判据「原始 IP 从不进 INSERT」）。

## 4. WebSocket：连接是加速器，落库是唯一真相

- 消息**只有一条存法**：`_deliver()` 先写 `messages` 再往连接推。WS 断了照样发得出去
  （6 秒等不到回执就用同一个 `request_id` 走 HTTP 重发，服务端按 `UNIQUE(user_id,request_id)` 判重）。
- 握手带不上 `Authorization`（浏览器 WebSocket 不让加头），所以改成 HTTP 先换一张
  **30 秒一次性 HMAC 票据**。这也顺手保住了强更门：门在 HTTP 中间件里，
  **WS 路由不经过中间件**，如果 token 直接进 URL，旧版客户端就能绕过门连进来。
- 未读不落第二份计数，全部现算 `messages.read_at IS NULL`。
- 现场排障两件事记在 `docs/operations.md`：uvicorn 要显式 `--ws websockets-sansio`
  （装了 websockets 17 但用 `--ws auto` 会把把握手当普通 HTTP，现场表现是路由 404 而它明明注册着）；
  nginx 的 `default.conf` 是**按 inode 绑进容器**的，用 `install`/`cp` 换 inode 之后
  `nginx -T` 里查不到新 location，必须 `cat >` 原地写 + `docker restart`。
- 公网自检：`/ws/chat?ticket=bad` → **403**（403 才是对的，404 说明中间层没透传）。

**没做的一件事要说清**：`_WS_HUB` 是进程内字典，跨进程不广播。现役 unit 是单 worker
（`ExecStart=/usr/local/bin/uvicorn server:app --host 172.17.0.1 --port 8000 ... --ws websockets-sansio`，
没有 `--workers`），所以现在是对的。**哪天加 worker，私信推送会静默半通**——
真要扩，正解是把 `channel_key` 走 Redis pub/sub，不是加机器。这条已经写在这里，不算没看见。

## 5. 前端：第一版只做到「能用」，看图之后又改了一轮

对着真机截图量出来的五处，都不是逻辑 bug，是"滥竽充数"那一类：

| 症状 | 成因 | 修法 |
| --- | --- | --- |
| 「小田属地 湖南 · 刚刚」连成一行 | `.cm-name`/`.cm-sub` 是 inline `<span>`，`overflow:hidden` 对 inline 无效 | 加 `display:block`，`.cm-row-*`/`.td-item-*` 一起 |
| 别人的帖子把「关注」按钮甩到下一行 | 卡片没有作者行容器，`.cm-who-btn` 是块级 flex 撑满整行 | 用 `.cm-card-head{display:flex}` 包住 |
| 「拉黑」撑成一整条白块 | 复用了 `.td-btn{flex:1 1 0}` | 换成设计系统里已有的 `.td-mini` |
| 「私信 TA」和「发送评论」一样绿 | 两颗都是主按钮 | 后者 `td-btn-quiet`，主/次一眼分得开 |
| 对话框里的人方角、外面圆角 | 复用了 `.td-glyph`（30px 方角功能块） | 加 `.cm-avatar.sm`，全站头像统一圆形 |

还有一个只有设了头像才会暴露的 bug：帖子详情把 `cmAvatarInner()` 的返回值又 `escapeHtml` 了一遍，
头像存在时屏上会印出 `<img src=...>` 字面量。判据补了一条「头像片段不再被二次转义」。

**两个真状态补上了**：卡片上的「关注」以前写死未关注（已关注的人发帖照样催你关注），
现在取服务端的 `followed_by_me`；拉黑按钮以前只看内存里的 `textContent`，
重开会话时明明已拉黑还写着「拉黑」，现在取 `/api/chat/messages` 回执里的 `partner.blocked`。
两条都有集成测试，正反方向都测（关注→取关、拉黑→取消拉黑）。

## 6. 判据与真机

- 后端 **471** 条、前端 **265** 条、集成 **37** 个、AI 契约 **6** 个，全绿；
  `tests/frontend-integration.mjs` PASS。
- 新增判据里真跑函数的部分：票据过期/篡改/重放、`_province` 收敛官方库样本、
  `notice_text` 逐类型、幂等白名单与模型字段对齐、
  正则扫「每一个 `/api/(community|chat|notifications)` 路由都要 `get_current_user`」、
  `redis_up` 三种返回形状、`followed_by_me`/`partner.blocked` 的初始态。
- 变异标定：抽掉 `.cm-name` 的 `display:block` → 只有排版那条红；
  把 `redis_up` 还原成比字符串 → 只有 Redis 那条红（且报的是 `bool:False`，正是线上那个形状）。
- 真机（MuMu，`am instrument`）一次跑完 5 个用例 `OK (5 tests)` 104.8 秒。
  社区那条主线 26.6 秒：发帖 → 点赞 → 评论 → 找人 → 主页 → 真 WebSocket 发私信 →
  杀进程重进验消息还在 → 我的主页 → 投反馈 → 更多页 → 320/393 两档排版。
- **真机这一档故意没覆盖什么，要写下来**：MuMu 上同一个 WebView 连续切账号时整个网络栈会挂死
  （连 GET 都不返回，跟这次改动无关）。所以跨账号互动（别人点赞/评论/关注带来的通知与计数）
  由 `tests/test_integration.py` 与外部 Chrome 覆盖，真机只跑单账号主线 + 重启持久性。
- 登录统一走 `loginAs()`：先登出、再等 `sessionGeneration` 停住。之前四个用例各自手搓登录，
  在同一次 instrument 进程里会被上一个账号的自动恢复抢掉会话号，
  报出来是「账号已切换，忽略旧请求」——看着像产品 bug，其实是夹具在跟自己撞。

## 7. 线上对账与清理

- 归档 `release-r149c.tar`（6,963,200 字节，sha256 `e4f2cb83047ee97f…`）本机与服务器双向一致；
  解出的 `web/qingsu.apk` 与本机 `qingsu.apk`、公网回读的 APK 三处同为
  5,371,941 字节 / sha256 `1277755a77d0f7cf…`。
- `deploy.py` 两次（第二次为带上 redis 修复），现役 `release=r149`、
  `source_revision=d3ca20d24bf3…` 等于当时 `git rev-parse HEAD`。
- 服务器内网 `verify_live.py` **8 项通过**。
- 公网独立复核（本机发请求，不看部署日志）：`/health/ready` 的
  `geoip.ok=true`、`chat.redis=true`、`gate.builds={"32":1}`；
  `/version.json` 的 `version_code/min_version_code=32`；`/ws/chat?ticket=bad` → 403；
  `/api/community/feed` 未登录 → 401；线上首页有 `class="td-mini" id="thread-block-btn"`，
  线上 `features.js` 有 `cm-card-head`/`followed_by_me`/`partner.blocked` 且
  `escapeHtml(cmAvatarInner` 为 0，线上 `features.css` 有 `.cm-name{display:block`
  与 `.me-avatar{...border-radius:50%`。
  （`/index.html` 这个路径本身 404，页面在 `/`，复核要抓根路径。）
- 测试账号：库里 77 个账号，删掉 id 191–265 共 **75 个**（全是 `uqa`/`usbqa` 前缀，
  非夹具命名的 0 个），去重后连带 **591 行**子表数据。
  删前逐条断言「恰好 75 个、首 191 尾 265、2 和 3 不在集内」；
  删后独立复核（拿删除前的库快照跟现役库逐表比）：真实账号 2/3 的各表行数前后一致、
  应删行数与表行数差值逐表相等、孤儿 0、`foreign_key_check` 0、`integrity_check` ok、
  剩余账号 `[2, 3]`。
- 清账号脚本本身修了两个 bug（外键顺序、按列重复计数），记录与标定见 commit `ccbded9`。
- 服务器 `/tmp` 里今晚自己造的探针文件已删（`geoip_probe.py`、`ip2lib/`、`ip2t/`、
  `xdb.done`、`xdb.err`、`__pycache__/`）；盘 8.5G/40G（22%）。
- 推送后 `git ls-remote` 回读 `refs/heads/main` 等于本地 HEAD。
  GitHub Actions 只在**每次 push 的头一笔**上跑检查：`ccbded9` 与文档这一笔
  `integration` / `android` 两个作业都 `completed / success`；
  **线上部署那一笔 `d3ca20d` 是中间提交，GitHub 没为它单独跑检查**——
  它和 `ccbded9` 之间只差那个清账号脚本，运行时代码一致，所以线上现役代码是被检查过的同一份。

## 8. 抬门仍然要机主亲手做

线上 `min_build=0`、`build_override=true`——门被人工刹住，这一版**没有抬**。
装完 2.0.0（32）之后要执行：

```
python3 /opt/qingsu/set-min-build.py 32
```

不抬的话旧客户端不会被挡，「已装的 1.9.8 在真人手机上被挡」这一格依旧没有实拍证据。

## 9. 没做到 / 别当成已通过

1. **AI 定制菜谱没做**。这一版只有确定性过滤（按忌口与城市调推荐顺序），
   没有按个人口味生成菜谱。
2. **邮箱找回要机主给 SMTP 账号**。配置只落在服务器本地 `/opt/qingsu/mail.json`（600，不进仓库），
   没配就是如实拒绝并说清原因，界面没有假装能发。
3. **RabbitMQ 没装**（理由见第 1 节）。要装的话先说清谁消费。
4. **WS 跨进程广播没做**（现役单 worker，见第 4 节）。
5. **举报只有入口没有后台**：`content_reports` 表在、界面能提交，
   但没有处理队列/管理页——投了没人看，等于只做了半个功能。
6. **图片只有归属校验，没有内容审核**：只认 `[0-9a-f]{32}.jpg` 且必须是本人上传过的文件名，
   黄图/暴图没有任何识别。
7. **属地精度按 IP 库本身**：移动网络出口经常只到省，境外只到国家；
   这不是"定位"，别当成定位精度宣传。
8. **搜索是 LIKE 前缀**：轻塑号要输全 8 位，昵称支持子串；没做拼音、纠错、分词。
9. **Redis 兜底是进程内的**：多 worker 下在线状态与票据防重放会各自为政。
10. **强更门不覆盖 WS**（设计如此，见第 4 节），所以"旧版客户端连不上私信"这件事
    是靠"必须先过 HTTP 换票据"间接保证的，不是门本身拦的。
