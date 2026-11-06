"""C07：私信实时连接的跨进程投递、全局在线判定与跨进程通话状态。

单进程时代这三件事都靠 server.py 里的模块级字典，一旦加 --workers 就会各自为政：

* A 连在 worker1、B 连在 worker2，B 发的消息只进 worker1 的 _WS_HUB，永远推不到 A；
* worker1 上"本地最后一个 socket 断开就 DEL presence"会把 worker2 还持有的在线状态删掉，
  用户立刻显示离线；
* 通话忙线表也是进程内的，worker1 看不见 worker2 上那通电话，既能重复呼叫也解不开忙线。

这一层把"谁在线""通话归谁""消息往哪投"变成 Redis 里的一份全局事实。Redis 答不上来时
每项都返回 None，调用方退回原来的进程内行为，并如实上报 fanout=local-only——宁可承认降级，
也不能让界面显示在线而消息其实只在本进程投了一份。

事件循环注意事项：本模块的 Redis 调用都是同步的（走注入的 redis_cmd，保留那条 30 秒熔断
和测试打桩）。异步侧要么由调用方用 to_thread 包起来，要么走 publish() 这条出队线程，
绝不在事件循环里直接同步问 Redis。
"""
import atexit
import json
import os
import queue
import secrets
import threading
import time

from . import chat as _chat

PRESENCE_TTL = 45           # 在线状态寿命；进程崩溃后最晚 45 秒自动离线
WORKER_TTL = 90             # worker 心跳寿命，比在线寿命宽，避免抖动即判死
CALL_TTL_RING = 120         # 响铃中的通话记录寿命（响铃 45 秒 + 足够余量）
CALL_TTL_ACTIVE = 1800      # 已接通的通话记录寿命：崩溃后最坏遗留 30 分钟忙线，不是永久
OUTBOX_MAX = 4096
MAX_FRAME = 192 * 1024      # 超过这条的信令不进跨进程通道（单侧 SDP 上限 64KB，正常到不了）
SUBSCRIBE_WAIT = 1.5        # 状态接口最多等这么久确认订阅真的建起来了

WORKER_ID = secrets.token_hex(6)
WORKER_HEARTBEAT = 15.0

_redis_cmd = None           # 注入：server._redis_cmd，熔断/命名空间/测试打桩都只认这一条
_local_deliver = None       # 注入：fn(uid, payload) → 只投本进程手里的 socket
_control_sink = None        # 注入：fn(envelope) → 在本进程事件循环上安排一次控制帧处理
channel = _chat.channel_key()

_stats = {"published": 0, "received": 0, "dropped": 0, "oversize": 0,
          "publish_failed": 0, "self_skipped": 0, "controls": 0}

_outbox = queue.Queue(maxsize=OUTBOX_MAX)
_gen = [0]
_started = [False]
_redis_ok = [False]
_sub_up = threading.Event()
_reason = [""]
_lock = threading.Lock()      # 只保护"收发线程起没起、这一代还在不在"，不跨网络持有
_pubsub_factory = None      # 测试用：替换阻塞订阅连接来源


def namespace_channel():
    """pub/sub 的频道要自己拼命名空间。

    cache.command 只给参数里以 qs: 开头的键补前缀，订阅用的连接不经过它；
    不补这一层的话两个测试命名空间会串到同一个频道上互相投递。
    """
    raw = (os.environ.get("QINGSU_CACHE_NAMESPACE") or "qingsu-prod").strip()
    if not raw.replace("-", "").replace("_", "").isalnum():
        raw = "qingsu-prod"
    return "%s:%s" % (raw, channel[3:] if channel.startswith("qs:") else channel)


def bind(redis_cmd=None, deliver=None, control=None, worker_id=None):
    """server.py 在 import 期登记自己的原语。

    每次重新登记都换一个新的 worker 身份并让上一代的收发线程退休：同一台机器上
    先后加载两个 server 模块实例时（测试就是这么干的），旧实例留下的在线键不能
    被算到新实例头上。
    """
    global _redis_cmd, _local_deliver, _control_sink, WORKER_ID, channel
    with _lock:
        _gen[0] += 1
        if redis_cmd is not None:
            _redis_cmd = redis_cmd
        if deliver is not None:
            _local_deliver = deliver
        if control is not None:
            _control_sink = control
        if worker_id:
            WORKER_ID = str(worker_id)[:32]
        _redis_ok[0] = False
        _sub_up.clear()
        _started[0] = False
        _reason[0] = ""


def _answer(args):
    """唯一一条 Redis 出口：没绑定原语就是"没答话"，不许猜。"""
    if _redis_cmd is None:
        return False, None
    ok, value = _redis_cmd(args)
    if ok:
        _redis_ok[0] = True
    else:
        _reason[0] = "redis_unanswered"
    return ok, value


# ── 通道模式 ───────────────────────────────────────────────────────────

def mode(wait=False):
    """redis = 收发都真就绪；local-only = 退回单进程行为（这是要能看见的降级）。"""
    if _redis_cmd is None:
        _reason[0] = "unbound"
        return "local-only"
    if not _redis_ok[0]:
        ok, _ = _answer(["PING"])
        if not ok:
            _reason[0] = "redis_unanswered"
            return "local-only"
    _ensure_threads()
    if not _sub_up.is_set():
        if wait:
            _sub_up.wait(SUBSCRIBE_WAIT)
    if not _sub_up.is_set():
        _reason[0] = "subscriber_down"
        return "local-only"
    return "redis"


def status():
    """给 /health/ready 用：模式 + 身份 + 计数，降级原因必须说得出。"""
    current = mode(wait=True)
    return {"fanout": current, "worker": WORKER_ID, "reason": _reason[0],
            "queue": _outbox.qsize(), "delivered": _sub_up.is_set(), **dict(_stats)}


# ── 收发线程 ───────────────────────────────────────────────────────────

def _ensure_threads():
    with _lock:
        if _started[0]:
            return
        _started[0] = True
    gen = _gen[0]
    threading.Thread(target=_publish_loop, args=(gen,), daemon=True,
                     name="ws-fanout-publish").start()
    threading.Thread(target=_heartbeat_loop, args=(gen,), daemon=True,
                     name="ws-fanout-heartbeat").start()
    threading.Thread(target=_subscribe_loop, args=(gen,), daemon=True,
                     name="ws-fanout-subscribe").start()


def _publish_loop(gen):
    while gen == _gen[0]:
        try:
            item = _outbox.get(timeout=0.5)
        except queue.Empty:
            continue
        if item is None:
            continue
        blob = json.dumps(item, separators=(",", ":"))
        if len(blob) > MAX_FRAME:
            _stats["oversize"] += 1
            continue
        ok, _ = _answer(["PUBLISH", channel, blob])
        if ok:
            _stats["published"] += 1
        else:
            _stats["publish_failed"] += 1


def _out(envelope):
    """出队即返回：事件循环里绝不同步等 Redis。"""
    _ensure_threads()
    try:
        _outbox.put_nowait(envelope)
        return True
    except queue.Full:
        _stats["dropped"] += 1
        _reason[0] = "outbox_full"
        return False


def _make_client():
    import redis
    # 订阅用的连接必须没有读超时：阻塞等消息是它的正常工作，不是卡住了。
    return redis.Redis(host=os.environ.get("QINGSU_REDIS_HOST", "127.0.0.1"),
                       port=int(os.environ.get("QINGSU_REDIS_PORT", "6379")),
                       socket_connect_timeout=1.0, socket_timeout=None,
                       decode_responses=True)


def _on_frame(message):
    if message.get("type") != "message":
        return
    try:
        item = json.loads(message["data"])
    except (TypeError, ValueError):
        return
    _dispatch(item)


def _subscribe_loop(gen):
    _stats["backoff"] = 0.5
    while gen == _gen[0]:
        try:
            client = _make_client()
            handle = client.pubsub()
            handle.subscribe(namespace_channel())
        except Exception as error:
            _reason[0] = "subscribe_%s" % type(error).__name__
            _sub_up.clear()
            time.sleep(_stats["backoff"])
            _stats["backoff"] = min(_stats["backoff"] * 2, 5.0)
            continue
        _sub_up.set()
        _stats["backoff"] = 0.5
        _reason[0] = ""
        try:
            while gen == _gen[0]:
                try:
                    message = handle.get_message(ignore_subscribe_messages=True, timeout=0.5)
                except Exception as error:
                    _reason[0] = "subscriber_%s" % type(error).__name__
                    break
                if message:
                    _on_frame(message)
        finally:
            _sub_up.clear()
            for closer in (handle.close, client.close):
                try:
                    closer()
                except Exception:
                    pass
        time.sleep(0.2)     # 断了就重连，但别贴着重连把对端打满


def _shutdown():
    """进程退出前先把这一代线程退休。

    不退的话解释器开始拆模块、socket 先变成 None，订阅线程会在关闭途中抛一脸栈。
    """
    _gen[0] += 1
    deadline = time.time() + 1.0
    while time.time() < deadline and not _outbox.empty():
        time.sleep(0.02)


atexit.register(_shutdown)


def _dispatch(item):
    """同一条连接不能收到两次：本进程自己发出去的那一份是直接投给 socket 的，
    从频道回来的必须丢掉；别的进程发来的只投自己手里那些不同的连接。"""
    if item.get("from") == WORKER_ID:
        _stats["self_skipped"] += 1
        return
    _stats["received"] += 1
    if item.get("k") == "ctl":
        if _control_sink is not None:
            _control_sink(item)
        return
    if item.get("k") == "msg" and _local_deliver is not None:
        try:
            _local_deliver(int(item["uid"]), item["payload"])
        except (TypeError, ValueError, KeyError):
            pass


def publish(uid, payload):
    """把一次投递转发给其它进程。调用方已经本地投过一份了。"""
    if _redis_cmd is None:
        return False
    if not _redis_ok[0]:
        return False
    return _out({"k": "msg", "uid": int(uid), "payload": payload, "from": WORKER_ID})


def publish_control(op, **fields):
    if _redis_cmd is None or not _redis_ok[0]:
        return False
    return _out({"k": "ctl", "op": op, "from": WORKER_ID, **fields})


# ── worker 身份与在线判定 ──────────────────────────────────────────────

def _heartbeat_loop(gen):
    while gen == _gen[0]:
        _beat(time.time())
        time.sleep(WORKER_HEARTBEAT)


def _beat(now):
    ok, _ = _answer(["ZADD", chat_worker_key(), str(now), WORKER_ID])
    if ok:
        _answer(["ZREMRANGEBYSCORE", chat_worker_key(), "0", str(now - WORKER_TTL)])


def _live_workers():
    """只数还在心跳的 worker，永远不用 KEYS。"""
    own = [WORKER_ID]
    ok, value = _answer(["ZRANGEBYSCORE", chat_worker_key(),
                         "%.3f" % (time.time() - WORKER_TTL), "+inf"])
    if not ok:
        return None
    live = [str(x) for x in (value or []) if str(x) != WORKER_ID]
    for extra in sorted(live)[:64]:
        own.append(extra)
    return own


def conn_touch(uid):
    """连接活着才写这一份带 worker 身份的在线键。"""
    _ensure_threads()
    key = chat_presence_worker_key(uid, WORKER_ID)
    ok, _ = _answer(["SETEX", key, str(PRESENCE_TTL), "1"])
    if not ok:
        return False
    _beat(time.time())
    return True


def conn_drop(uid):
    """只删自己那一份。删完再确认还有没有别的 worker 持有这个用户，
    才决定聚合键（会话列表读的那一份）要不要跟着删——worker1 断开就把
    worker2 的在线状态删掉是最典型的误伤。"""
    ok, _ = _answer(["DEL", chat_presence_worker_key(uid, WORKER_ID)])
    if not ok:
        return False
    workers = _live_workers() or [WORKER_ID]
    others = [chat_presence_worker_key(uid, w) for w in workers if w != WORKER_ID]
    if others:
        alive, count = _answer(["EXISTS", *others])
        if not alive:
            return False
        if int(count or 0) > 0:
            return True
    _answer(["DEL", chat_presence_key(uid)])
    return True


def connected(uid):
    """"他在任何一个进程有没有连接"——True/False 是全局答案，None 才是 Redis 没答话。"""
    workers = _live_workers()
    if workers is None:
        return None
    keys = [chat_presence_worker_key(uid, w) for w in workers]
    ok, count = _answer(["EXISTS", *keys])
    if not ok:
        return None
    return int(count or 0) > 0


def presence_touch(uid):
    """会话列表那颗在线圆点读的聚合键。"""
    ok, _ = _answer(["SETEX", chat_presence_key(uid), str(PRESENCE_TTL), "1"])
    return bool(ok)


def presence_clear(uid):
    ok, _ = _answer(["DEL", chat_presence_key(uid)])
    return bool(ok)


# ── 通话状态：Redis 一份，进程崩了靠 TTL + worker 心跳回收 ─────────────

def call_reserve(call_id, a, b, record):
    """两个忙线位要一起占，抢不到就整笔不生效——分两步就可能出现"A 忙、B 空"的半通电话。"""
    ttl = record.get("ttl") or CALL_TTL_RING
    ok, value = _answer(["EVAL", RESERVE_SCRIPT, 3,
                         chat_call_user_key(a), chat_call_user_key(b), chat_call_key(call_id),
                         call_id, json.dumps(record, separators=(",", ":")), str(ttl)])
    if not ok:
        return None
    return int(value or 0) == 1


def call_write(call_id, record):
    ttl = record.get("ttl") or CALL_TTL_ACTIVE
    ok, value = _answer(["EVAL", WRITE_SCRIPT, 3,
                         chat_call_user_key(record["from"]), chat_call_user_key(record["to"]),
                         chat_call_key(call_id),
                         call_id, json.dumps(record, separators=(",", ":")), str(ttl)])
    if not ok:
        return None
    return int(value or 0) == 1


def call_get(call_id):
    ok, value = _answer(["GET", chat_call_key(call_id)])
    if not ok:
        return None
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def call_owner(uid):
    ok, value = _answer(["GET", chat_call_user_key(uid)])
    if not ok:
        return None
    return str(value) if value else ""


def call_drop(call_id, a=None, b=None):
    keys = [chat_call_key(call_id)]
    if a is not None:
        keys.append(chat_call_user_key(a))
    if b is not None:
        keys.append(chat_call_user_key(b))
    ok, _ = _answer(["EVAL", DROP_SCRIPT, len(keys), *keys, call_id])
    return bool(ok)


def call_ttl(call_id, ttl):
    ok, _ = _answer(["EXPIRE", chat_call_key(call_id), str(int(ttl))])
    return bool(ok)


def worker_alive(worker_id):
    """worker 不心跳了，它名下那通电话就是残骸，不能继续把用户锁成忙线。"""
    ok, value = _answer(["ZSCORE", chat_worker_key(), str(worker_id or "")])
    if not ok:
        return None
    if not value:
        return False
    try:
        return float(value) >= time.time() - WORKER_TTL
    except (TypeError, ValueError):
        return False


def gc_user(uid):
    """忙线位指向一通已经不存在的电话时顺手解掉，返回是否动过。"""
    owner = call_owner(uid)
    if owner is None:
        return None
    if not owner:
        return False
    record = call_get(owner)
    if record:
        alive = worker_alive(record.get("worker"))
        if alive is False:
            call_drop(owner, record.get("from"), record.get("to"))
            return True
        return False
    if record == {}:
        call_drop(owner, uid, uid)
        return True
    return False


# 键名统一由 app_modules.chat 拼，两个进程才不会各自拼出不同的键。
def chat_presence_key(uid):
    return _chat.presence_key(uid)


def chat_presence_worker_key(uid, worker_id):
    return _chat.presence_worker_key(uid, worker_id)


def chat_call_key(call_id):
    return _chat.call_key(call_id)


def chat_call_user_key(uid):
    return _chat.call_user_key(uid)


def chat_worker_key():
    return _chat.worker_registry_key()


RESERVE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
redis.call('SETEX', KEYS[3], ARGV[3], ARGV[2])
redis.call('SETEX', KEYS[1], ARGV[3], ARGV[1])
redis.call('SETEX', KEYS[2], ARGV[3], ARGV[1])
return 1
"""

WRITE_SCRIPT = """
if redis.call('EXISTS', KEYS[3]) == 0 then return 0 end
redis.call('SETEX', KEYS[3], ARGV[3], ARGV[2])
redis.call('SETEX', KEYS[1], ARGV[3], ARGV[1])
redis.call('SETEX', KEYS[2], ARGV[3], ARGV[1])
return 1
"""

DROP_SCRIPT = """
redis.call('DEL', KEYS[1])
for i = 2, #KEYS do
  if redis.call('GET', KEYS[i]) == ARGV[1] then redis.call('DEL', KEYS[i]) end
end
return 1
"""
