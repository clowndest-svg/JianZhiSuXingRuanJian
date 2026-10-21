# r168 / 2.2.7（52）语音通话验收

本版新增私聊 1:1 语音通话：双方都在 App 内在线时，私信页点“语音”呼叫；对方全屏来电，可接听/拒绝；通话中可静音、切换听筒/扬声器、挂断并计时。媒体优先点对点，NAT 不配合时走自建 coturn 中继；不录音、不落库。

## 服务器是否扛得住

实测生产机 4 vCPU、负载 0.10/0.08/0.02、可用内存 2.1GB、磁盘剩 30GB、到本机 RTT 27ms、出站约 379KB/s（约 3Mbps）。coturn RSS 约 13.7MB（cgroup memory 约 6MB），1:1 Opus 通话中继约 40–80kbps；对现有聊天、SQLite、表情和后台没有可见影响。安全组已放行 **UDP 3478 + UDP 49160–49180**；TCP 5349 未启用。

## 实现

- **信令**：复用现有 `/ws/chat`。服务端校验在线、拉黑、忙线、SDP/ICE 大小和每用户呼叫频率；45 秒未接听自动超时；WS 断开通知对端。呼叫状态只在内存，不落库。
- **TURN**：`/api/rtc/ice` 用 `/opt/qingsu/keys/turn-secret` 生成 1 小时有效的 REST 用户名/密码；coturn 使用同一密钥，关闭 TCP/TLS/DTLS，禁止私网 peer。密钥只在服务器 root/qingsu 可读，不进仓库；`scripts/provision-coturn.sh` 可在重装时恢复配置。
- **客户端**：`RTCPeerConnection` 音频，优先 P2P，失败走 TURN；来电全局覆盖层（不在私信页也能收到）、接听/拒绝、计时、静音、扬声器、挂断；安卓原生 `AudioManager` 切 `MODE_IN_COMMUNICATION`、音频焦点、扬声器/听筒和常亮；Web 端隐藏扬声器切换。登录恢复会话后即建立 WS，不必先停在消息页。
- **冷启动修复**：全量回归再次抓到两个 worker 同时 `PRAGMA journal_mode=WAL` 报 `database is locked`。已把 `busy_timeout` 放到 WAL 之前并对 locked 做短重试；多进程冷启动连续 5/5 通过。

## 验证

- 本地：后端原回归 619/619、前端 334/334、框架集成 62、并发一致性 24、通话信令 3、媒体 15、原生契约 21、多进程冷启动/限流 3 项（连跑 5 次）、真实 Chromium 14 项，全部通过。
- 双浏览器真实通话（强制 TURN relay）：来电覆盖层、双方 active、`local=relay / remote=relay`、远端音轨、静音、挂断全部通过。
- 线上：`r39581453023` / source `37dd0a3` / 2.2.7（52），APK SHA-256 `5d2ad7e0c0acceed5bfcbd9a6b895e445fb71804667d912291c36e085a7f42e3`，备份 `/opt/qingsu/backups/release-20261021-181022`。公网双浏览器强制 TURN 通话 4/4 通过；`/health/ready` 报 `chat.turn=true`；监控 18:12 `coturn=active`、`turn=true`、`problems: []`、`errors_5xx=0`；邮件 up、计数对账 0 漂移、`qingsu-qa` inactive。
- 测试数据：删除公网通话夹具 2 个账号；最终真实用户 2、夹具 0、外键 0、完整性 ok。

## 边界

只支持双方都在 App 内在线时的 1:1 通话；App 被系统杀掉或后台断网时没有厂商推送，不会后台响铃；没有 PSTN/手机号呼入、没有通话录音/历史记录。TURN 只有 UDP，运营商封锁 UDP 的网络会失败并提示，语音消息仍可用。当前无 ADB 设备，实体手机的系统麦克风弹窗、听筒/扬声器实际路由和厂商输入法/后台策略仍需真机各点一次；Chromium 假麦克风与强制 relay 不能替代这些人工项。
