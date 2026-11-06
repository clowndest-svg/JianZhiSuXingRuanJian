# -*- coding: utf-8 -*-
"""多进程回归：限流计数、实时投递、通话、在线状态、统一撤销都必须是"全局一份"。

为什么限流要单独立一条：限流键存在 Redis 里时多进程才准；Redis 不可用会退回进程内内存，
那时两个 worker 各放行一份，实际阈值悄悄变成 N 倍——功能看着正常，防护已经形同虚设。

为什么 C07 的这几条也必须真起两个进程：跨进程投递、通话忙线、在线判定这三件事在
单进程里"全绿"是最容易骗人的——本地字典什么都能答对，一模成两个 worker 就全错。
所以这里每条都是拿两个独立 Uvicorn 进程 + 两条真 WebSocket 连接打出来的，
不用单元测试模拟。

Redis 不在就跳过共享判定（不静默通过）；QINGSU_REQUIRE_REDIS=1 时缺 Redis 直接判红。
但两个进程的冷启动始终要验，否则"多进程"这条连进程都起不来也能算绿。

用法:
    python tests/test_multiprocess.py
    QINGSU_REQUIRE_REDIS=1 python tests/test_multiprocess.py
"""
import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORTS = (18003, 18004)
LIMIT = 20          # FOLLOW_RATE_LIMIT：每人每分钟 20 次
SWEEP = "3"         # 空闲连接重新问库的间隔；判据用它区分"当场撤销"和"等下一次心跳"
DEAD_REDIS_PORT = "6399"    # 没人听的端口：专门用来验降级说不说真话


def api(port, path, body=None, token=None, timeout=30):
    req = urllib.request.Request(
        'http://127.0.0.1:%d%s' % (port, path),
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json',
                 **({'Authorization': 'Bearer ' + token} if token else {})})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except Exception as e:
        return 599, {'detail': type(e).__name__}


def wait_up(port, proc, seconds=30):
    for _ in range(int(seconds * 4)):
        if proc.poll() is not None:
            return False
        try:
            with OPENER.open('http://127.0.0.1:%d/health' % port, timeout=.25):
                return True
        except Exception:
            time.sleep(.1)
    return False


def redis_ready():
    try:
        import redis
        redis.Redis(host='127.0.0.1', port=6379, socket_connect_timeout=.4,
                    decode_responses=True).ping()
        return True
    except Exception:
        return False


def boot(temp, env, ports):
    """起 N 个独立进程，共用同一份数据库。"""
    procs, logs = [], []
    for port in ports:
        log = open(os.path.join(temp, 'srv-%d-%s.log' % (port, env.get('_TAG', ''))), 'w')
        logs.append(log)
        procs.append(subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1',
             '--port', str(port), '--no-access-log'],
            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
            # Windows 上另起一个进程组：否则 terminate 会把跑测试的这个 shell 一起带走
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)))
    for port, proc in zip(ports, procs):
        if not wait_up(port, proc):
            detail = ''
            path = os.path.join(temp, 'srv-%d-%s.log' % (port, env.get('_TAG', '')))
            if os.path.exists(path):
                detail = Path(path).read_text(errors='replace')[-600:]
            print('红 进程 %d 没起来' % port)
            print(detail)
            shutdown(procs, logs)
            return None
    return procs, logs


def shutdown(procs, logs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()
    # Windows 上句柄不关，临时目录删不掉，清理会盖掉真正的判据结果
    for log in logs:
        try:
            log.close()
        except Exception:
            pass


# ── WebSocket 部分：两条真连接，一人一条 worker ─────────────────────────

async def ws_open(port, ticket):
    import websockets
    return await websockets.connect('ws://127.0.0.1:%d/ws/chat?ticket=%s' % (port, ticket),
                                    open_timeout=15, close_timeout=5, ping_interval=None)


async def ws_recv(sock, seconds=6.0):
    """空闲检查会自己发 pong，等具体信令时要把这些心跳跳过，不然判据会被心跳撞歪。"""
    deadline = time.time() + seconds
    while True:
        frame = json.loads(await asyncio.wait_for(sock.recv(), max(.2, deadline - time.time())))
        if frame.get('t') != 'pong':
            return frame


async def ws_expect_none(sock, seconds=1.5):
    """确认这段时间里真的什么都没有（重复投递就是在这里被抓出来的）。"""
    try:
        frame = await ws_recv(sock, seconds)
    except (asyncio.TimeoutError, TimeoutError):
        return None
    return None if frame.get('t') == 'pong' else frame


async def ws_drain_ready(sock):
    frame = await ws_recv(sock)
    assert frame.get('t') == 'ready', frame
    return frame


async def ws_close(sock):
    try:
        await sock.close()
    except Exception:
        pass


def ticket_for(port, token):
    st, body = api(port, '/api/chat/ticket', {}, token)
    assert st == 200, (st, body)
    return body['ticket']


def make_users(count, stamp, prefix='mp'):
    """两个进程共用的注册走左边那个 worker。"""
    made = []
    for i in range(count):
        st, body = api(PORTS[0], '/api/register', {
            'username': '%s%d_%d' % (prefix, i, stamp), 'password': 'Passw0rd!mp',
            'age': 30, 'height': 170, 'weight_jin': 160, 'target_weight_jin': 140})
        assert st == 200, (st, body)
        made.append(body)
    return made


def pair_follow(a, b):
    """通话门禁要互相关注，两边各点一次。"""
    for left, right in ((a, b), (b, a)):
        st, body = api(PORTS[0], '/api/community/users/%d/follow' % right['id'],
                       {'on': True}, left['token'])
        assert st == 200, (st, body)


async def section_message():
    """判据 1：A 在自己连的那个 worker 上发消息，连在另一个 worker 的 B 必须收到，
    而且同一条连接不能收到两次。"""
    a, b = make_users(2, int(time.time() * 1000) % 100000, 'xmsg')
    w1 = await ws_open(PORTS[0], ticket_for(PORTS[0], a['token']))
    w2 = await ws_open(PORTS[1], ticket_for(PORTS[1], b['token']))
    try:
        await ws_drain_ready(w1)
        await ws_drain_ready(w2)
        rid = 'x-%d' % int(time.time() * 1000)
        await w1.send(json.dumps({'t': 'send', 'to': b['id'], 'text': '跨进程一条',
                                  'request_id': rid}))
        got_b, ack_a = await ws_recv(w2), await ws_recv(w1)
        hit = got_b.get('t') == 'msg' and got_b.get('message', {}).get('body') == '跨进程一条'
        extra_b = await ws_expect_none(w2)
        extra_a = await ws_expect_none(w1)
        return [('绿' if hit else '红', 'A@worker1 发的消息到达连在 worker2 的 B',
                 got_b.get('t')),
                ('绿' if (ack_a.get('t') == 'ack' and extra_a is None) else '红',
                 '发送方只收到一条 ack，没有被重复投递',
                 [ack_a.get('t'), (extra_a or {}).get('t')]),
                ('绿' if extra_b is None else '红', '接收方同一条连接只收到一次',
                 (extra_b or {}).get('t'))]
    finally:
        await ws_close(w1)
        await ws_close(w2)


async def section_call():
    """判据 2：跨进程呼叫要打得通、拒绝要传得回，而且两边都不许残留忙线。"""
    a, b = make_users(2, int(time.time() * 1000) % 100000, 'xcal')
    pair_follow(a, b)
    w1 = await ws_open(PORTS[0], ticket_for(PORTS[0], a['token']))
    w2 = await ws_open(PORTS[1], ticket_for(PORTS[1], b['token']))
    rows = []
    try:
        await ws_drain_ready(w1)
        await ws_drain_ready(w2)
        offer = {'type': 'offer', 'sdp': 'v=0\r\no=- 1 IN IP4 127.0.0.1\r\n'}
        await w1.send(json.dumps({'t': 'call_invite', 'to': b['id'], 'sdp': offer}))
        ringing = await ws_recv(w1)
        invite = await ws_recv(w2)
        rows.append(('绿' if invite.get('t') == 'call_invite' else '红',
                     'A@worker1 呼叫连在 worker2 的 B，B 收到 call_invite', invite.get('t')))
        call_id = ringing.get('call_id') or invite.get('call_id')
        await w2.send(json.dumps({'t': 'call_reject', 'call_id': call_id}))
        reject = await ws_recv(w1)
        rows.append(('绿' if reject.get('t') == 'call_reject' else '红',
                     'B 在另一个 worker 上拒绝，A 当场收到', reject.get('t')))
        await asyncio.sleep(1.0)
        await w1.send(json.dumps({'t': 'call_invite', 'to': b['id'], 'sdp': offer}))
        again = await ws_recv(w1)
        rows.append(('绿' if again.get('t') == 'call_ringing' else '红',
                     '拒绝后立刻再呼叫：不许残留忙线（回 call_busy 就是遗留）', again.get('t')))
        if again.get('t') == 'call_ringing':
            await w1.send(json.dumps({'t': 'call_cancel', 'call_id': again['call_id']}))
            await ws_recv(w2)
        await asyncio.sleep(1.0)
        await w1.send(json.dumps({'t': 'call_invite', 'to': b['id'], 'sdp': offer}))
        third = await ws_recv(w1)
        rows.append(('绿' if third.get('t') == 'call_ringing' else '红',
                     '取消后再呼叫：同样不许残留忙线', third.get('t')))
        if third.get('t') == 'call_ringing':
            await w1.send(json.dumps({'t': 'call_cancel', 'call_id': third['call_id']}))
            await ws_recv(w2)
        return rows
    finally:
        await ws_close(w1)
        await ws_close(w2)


async def section_crash_recovery():
    """判据 6：持有通话的那个进程真的崩了，忙线不能把用户锁死。

    这里 kill -9 掉创建那通电话的 worker（连接随之消失、心跳从此不再刷新），
    再把心跳有序集合里那条记录的时间压到 WORKER_TTL 以外——等价于"崩溃已经过了
    90 秒"，不然判据要干等一分半。回收走的是 call_reserve 里的 gc_user，
    不是测试自己手工删键：删错了也算通过就证明不了产品会自愈。
    """
    a, b, c = make_users(3, int(time.time() * 1000) % 100000, 'xcrash')
    pair_follow(a, b)
    pair_follow(b, c)
    ready = {port: (api(port, '/health/ready')[1].get('chat') or {}) for port in PORTS}
    wid = {port: ready[port].get('worker') for port in PORTS}
    w1 = await ws_open(PORTS[0], ticket_for(PORTS[0], a['token']))   # A 死在 worker1
    w2 = await ws_open(PORTS[1], ticket_for(PORTS[1], b['token']))
    w3 = await ws_open(PORTS[1], ticket_for(PORTS[1], c['token']))
    rows = []
    try:
        for sock in (w1, w2, w3):
            await ws_drain_ready(sock)
        offer = {'type': 'offer', 'sdp': 'v=0\r\n'}
        await w1.send(json.dumps({'t': 'call_invite', 'to': b['id'], 'sdp': offer}))
        ringing = await ws_recv(w1)
        await ws_recv(w2)
        call_id = ringing.get('call_id')
        client = redis_keys()
        busy_before = client.exists('%s:calluser:%d' % (os.environ['QINGSU_TEST_NAMESPACE'], b['id']))
        # 崩溃：不是优雅退出，进程直接被杀掉
        PROCS[0].kill()
        PROCS[0].wait(timeout=20)
        client.zadd('%s:wsworkers' % os.environ['QINGSU_TEST_NAMESPACE'],
                    {wid[PORTS[0]]: time.time() - 200})
        await asyncio.sleep(0.4)
        # B 改叫第三个人：如果崩溃留下的忙线没人回收，这里只会得到 call_busy
        await w2.send(json.dumps({'t': 'call_invite', 'to': c['id'], 'sdp': offer}))
        again = await ws_recv(w2, 8.0)
        rows.append(('绿' if (busy_before and ringing.get('t') == 'call_ringing') else '红',
                     '崩溃前那通电话确实把 B 锁成了忙线（前提成立，否则下一条是空话）',
                     {'响铃': ringing.get('t'), 'B 忙线位': int(busy_before)}))
        rows.append(('绿' if again.get('t') == 'call_ringing' else '红',
                     '崩溃 worker 名下的忙线被自动回收，B 能重新拨通（不靠重启服务）',
                     again.get('t')))
        if again.get('t') == 'call_ringing':
            await w2.send(json.dumps({'t': 'call_cancel', 'call_id': again['call_id']}))
            await ws_recv(w3)
        return rows
    finally:
        for sock in (w2, w3):
            await ws_close(sock)

async def section_same_worker():
    """判据 2b：两个用户连在同一个 worker 上时，同一条连接不许收到两次。

    跨进程频道对"本进程自己发出去的那一条"必须丢掉。上一条判据把两人分别放在两个
    worker，正好绕开了这条路径：本地已经投过一份，从频道回来的那份会在同一个进程里
    再投一次。把 A、B 都连到 worker1 才会真的撞上。
    """
    a, b = make_users(2, int(time.time() * 1000) % 100000, 'wsame')
    w1 = await ws_open(PORTS[0], ticket_for(PORTS[0], a['token']))
    w2 = await ws_open(PORTS[0], ticket_for(PORTS[0], b['token']))
    try:
        await ws_drain_ready(w1)
        await ws_drain_ready(w2)
        rid = 's-%d' % int(time.time() * 1000)
        await w1.send(json.dumps({'t': 'send', 'to': b['id'], 'text': '同进程一条',
                                  'request_id': rid}))
        got_b = await ws_recv(w2)
        dup_b = await ws_expect_none(w2)
        got_a = await ws_recv(w1)
        dup_a = await ws_expect_none(w1)
        return [('绿' if (got_b.get('t') == 'msg' and dup_b is None) else '红',
                 '同一个 worker 上的两个用户：接收方只收到一条',
                 {'第一条': got_b.get('t'), '多出来的': (dup_b or {}).get('t')}),
                ('绿' if (got_a.get('t') == 'ack' and dup_a is None) else '红',
                 '发送方只有一条 ack，频道回投没有变成第二条消息',
                 {'第一条': got_a.get('t'), '多出来的': (dup_a or {}).get('t')})]
    finally:
        await ws_close(w1)
        await ws_close(w2)


def redis_keys():
    import redis
    return redis.Redis(host='127.0.0.1', port=6379, socket_connect_timeout=.5,
                       decode_responses=True)


async def section_presence():
    """判据 3：worker1 上的连接断开，不能把 worker2 还持有的在线状态删掉。"""
    host, guest = make_users(2, int(time.time() * 1000) % 100000, 'xpre')
    pair_follow(host, guest)
    ready = {}
    for port in PORTS:
        st, body = api(port, '/health/ready')
        ready[port] = (body.get('chat') or {})
    wid = {port: (ready[port] or {}).get('worker') for port in PORTS}
    a = await ws_open(PORTS[0], ticket_for(PORTS[0], host['token']))     # 同一账号两个 worker
    b = await ws_open(PORTS[1], ticket_for(PORTS[1], host['token']))
    g = await ws_open(PORTS[0], ticket_for(PORTS[0], guest['token']))
    try:
        for sock in (a, b, g):
            await ws_drain_ready(sock)
        await asyncio.sleep(.4)
        await ws_close(a)                 # 断开连在 worker1 的那一条
        await asyncio.sleep(1.2)          # 留时间给"错误的全局 DEL"露出来
        client = redis_keys()
        agg = client.exists('%s:presence:%d' % (os.environ['QINGSU_TEST_NAMESPACE'], host['id']))
        gone = client.exists('%s:presence:%d@%s'
                             % (os.environ['QINGSU_TEST_NAMESPACE'], host['id'], wid[PORTS[0]]))
        kept = client.exists('%s:presence:%d@%s'
                             % (os.environ['QINGSU_TEST_NAMESPACE'], host['id'], wid[PORTS[1]]))
        # 用户可观察的那一面：guest 就在 worker1 上，他呼叫 host 必须能响
        offer = {'type': 'offer', 'sdp': 'v=0\r\n'}
        await g.send(json.dumps({'t': 'call_invite', 'to': host['id'], 'sdp': offer}))
        ring = await ws_recv(g)
        call_id = ring.get('call_id')
        bframe = await ws_recv(b) if ring.get('t') == 'call_ringing' else None
        rows = [('绿' if (agg and kept) else '红',
                 'worker1 断开后：全局在线键仍在，只剩 worker2 那一份',
                 {'聚合键': int(agg), 'worker1 那份': int(gone), 'worker2 那份': int(kept)}),
                ('绿' if ring.get('t') == 'call_ringing' else '红',
                 '连在 worker1 的呼叫方看到的仍是"对方在线"（不会误判离线）', ring.get('t')),
                ('绿' if (bframe or {}).get('t') == 'call_invite' else '红',
                 '响铃确实送到了 worker2 上那条连接', (bframe or {}).get('t'))]
        if call_id:
            await b.send(json.dumps({'t': 'call_reject', 'call_id': call_id}))
            await ws_recv(g)
        return rows
    finally:
        for sock in (b, g):
            await ws_close(sock)


async def section_revoke():
    """判据 4：在一个 worker 上撤销会话，连在另一个 worker 的存量连接要当场失效，
    而不是等到下一次空闲检查（空闲检查本身也必须在双进程下成立，见判据 5）。"""
    user = make_users(1, int(time.time() * 1000) % 100000, 'xrev')[0]
    a = await ws_open(PORTS[0], ticket_for(PORTS[0], user['token']))
    b = await ws_open(PORTS[1], ticket_for(PORTS[1], user['token']))
    try:
        await ws_drain_ready(a)
        await ws_drain_ready(b)

        # 计时必须从"发起撤销"那一刻算起，而不是从两条观察协程开跑算起：
        # api() 会阻塞这个线程，观察协程在此之前根本没开始计数，量出来会是假的 0.00s。
        async def watch(sock):
            try:
                await ws_recv(sock, SWEEP_SECONDS + 1)
                return None, time.time() - t0
            except Exception as error:
                return getattr(getattr(error, 'rcvd', None), 'code', None), time.time() - t0

        both = asyncio.ensure_future(asyncio.gather(watch(a), watch(b)))
        await asyncio.sleep(0)        # 让两条观察真的开始
        t0 = time.time()
        st, body = await asyncio.to_thread(api, PORTS[0], '/api/logout', {}, user['token'])
        assert st == 200, (st, body)
        results = await both
        codes = [r[0] for r in results]
        times = [r[1] for r in results]
        slowest = max(times)
        fast = slowest < 1.5
        return [('绿' if (codes[0] == 4401 and times[0] < 1.5) else '红',
                 '本进程的连接当场被关掉（4401 且 <1.5s）',
                 {'关闭码': codes[0], '用时': '%.2fs' % times[0]}),
                ('绿' if (codes[1] == 4401 and times[1] < 1.5) else '红',
                 '另一个 worker 上的连接也当场被关掉（4401 且 <1.5s）',
                 {'关闭码': codes[1], '用时': '%.2fs' % times[1]}),
                ('绿' if fast else '红',
                 '关闭事件跨进程送达，不靠 %ss 空闲检查兜底（最慢 %.2fs）' % (SWEEP, slowest),
                 '%.2fs < 1.5s' % slowest if fast else '%.2fs（等于空闲检查才关的）' % slowest)]
    finally:
        for sock in (a, b):
            await ws_close(sock)


async def section_db_authority():
    """判据 5：封号写在库里，另一个进程的空闲连接必须在空闲检查里被关掉（4403）。"""
    user = make_users(1, int(time.time() * 1000) % 100000, 'xban')[0]
    sock = await ws_open(PORTS[1], ticket_for(PORTS[1], user['token']))
    try:
        await ws_drain_ready(sock)
        db = os.environ['QINGSU_TEST_DB']
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')

        def ban():
            import sqlite3
            conn = sqlite3.connect(db, timeout=5)
            try:
                conn.execute("UPDATE users SET banned_at=? WHERE id=?", (stamp, user['id']))
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(ban)
        code = None
        try:
            await ws_recv(sock, float(SWEEP) * 2.5)
        except Exception as error:
            code = getattr(getattr(error, 'rcvd', None), 'code', None)
        return [('绿' if code == 4403 else '红',
                 '以库为准的空闲检查在双进程下仍然成立（封号 %ss 内断开）' % SWEEP, code)]
    finally:
        await ws_close(sock)


async def section_local_only():
    """判据 6：Redis 不在时必须显式降级——状态说 local-only，跨进程投递不许假装成功。"""
    rows = []
    reports = {}
    for port in PORTS:
        st, body = api(port, '/health/ready')
        reports[port] = (body.get('chat') or {}).get('fanout')
    rows.append(('绿' if all(v == 'local-only' for v in reports.values()) else '红',
                 'Redis 不可用时两边都如实报 chat.fanout=local-only', reports))
    a, b = make_users(2, int(time.time() * 1000) % 100000, 'xlol')
    pair_follow(a, b)      # 门禁顺序是先看关系再看在线，不互关就只会回"互相关注后才能语音通话"
    w1 = await ws_open(PORTS[0], ticket_for(PORTS[0], a['token']))
    w2 = await ws_open(PORTS[1], ticket_for(PORTS[1], b['token']))
    try:
        await ws_drain_ready(w1)
        await ws_drain_ready(w2)
        await w1.send(json.dumps({'t': 'send', 'to': b['id'], 'text': '降级期消息',
                                  'request_id': 'l-%d' % int(time.time() * 1000)}))
        ack = await ws_recv(w1)
        crossed = None
        try:
            crossed = await ws_recv(w2, 2.0)
        except Exception:
            pass
        rows.append(('绿' if (ack.get('t') == 'ack' and crossed is None) else '红',
                     'local-only 下跨进程确实不投（不谎报"已投递"）',
                     {'本进程 ack': ack.get('t'), '另一进程收到': (crossed or {}).get('t')}))
        offer = {'type': 'offer', 'sdp': 'v=0\r\n'}
        await w1.send(json.dumps({'t': 'call_invite', 'to': b['id'], 'sdp': offer}))
        gate = await ws_recv(w1, 4.0)
        rows.append(('绿' if gate.get('t') == 'call_unavailable' else '红',
                     '降级时通话门禁不谎报对方在线', gate.get('t')))
        return rows
    finally:
        await ws_close(w1)
        await ws_close(w2)


PROCS = []        # boot() 之后填进来：崩溃回收判据要真的杀掉其中一个
EXPECTED_ROWS = 25   # 本文件在 Redis 在场时应当跑到的判据行数，多一节/少一节都会在这里对不上


def run_async(coro, seconds=120):
    return asyncio.run(asyncio.wait_for(coro, seconds))


def report(title, rows, tally=None):
    print('=== %s ===' % title)
    failed = 0
    for flag, text, evidence in rows:
        print('  %s %s -> %s' % (flag, text, json.dumps(evidence, ensure_ascii=False, default=str)))
        if flag != '绿':
            failed += 1
    if tally is not None:
        tally[0] += len(rows)
        tally[1] += failed
    return failed



SWEEP_SECONDS = float(SWEEP)


def main():
    shared = redis_ready()

    (ROOT / '_audit_sandbox').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / '_audit_sandbox',
                                     ignore_cleanup_errors=True) as temp:
        namespace = 'qingsu-mp-%d-%d' % (os.path.abspath(__file__) and os.getpid(),
                                         int(time.time()))
        env = os.environ.copy()
        for kind in ('DB', 'UPLOAD', 'WEB'):
            env['QINGSU_' + kind + '_DIR'] = temp + '/' + kind
        env['QINGSU_CACHE_NAMESPACE'] = namespace
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['QINGSU_WS_AUTH_SWEEP_SEC'] = SWEEP
        os.environ['QINGSU_TEST_NAMESPACE'] = namespace
        os.environ['QINGSU_TEST_DB'] = os.path.join(temp, 'DB', 'qingsu.db')
        procs, logs = [], []
        tally = [0, 0]      # [发过的判据数, 其中红了多少]
        try:
            started = boot(temp, dict(env, _TAG='main'), PORTS)
            if not started:
                return 1
            procs, logs = started
            PROCS[:] = procs
            print('绿 两个独立进程能在同一个数据库上同时冷启动')
            if not shared:
                # 跳过要单独计数、单独定性：CI 一旦给 Redis，缺 Redis 就是红而不是"没测"。
                # 否则这些判据可以常年以"绿"的名义什么都不验。
                print('SKIPPED=%d 本机没有可用的 Redis：共享计数与全部跨进程判据未验证' % EXPECTED_ROWS)
                if os.environ.get('QINGSU_REQUIRE_REDIS') == '1':
                    print('红 CI 声明了 Redis 服务却连不上：这条不能算跳过')
                    return 1
                print('结论：本文件 1 条通过 / %d 条跳过（未验证，不等于通过）' % EXPECTED_ROWS)
                return 0

            stamp = int(time.time() * 1000) % 100000
            made = []
            for i in range(3):
                st, body = api(PORTS[0], '/api/register', {
                    'username': 'mp%d_%d' % (i, stamp), 'password': 'Passw0rd!mp',
                    'age': 30, 'height': 170, 'weight_jin': 160, 'target_weight_jin': 140})
                if st != 200:
                    print('红 夹具注册失败', st, body)
                    return 1
                made.append((body['token'], body['id']))
            follower, target = made[0], made[2]

            stores = {}
            for port in PORTS:
                st, ready = api(port, '/health/ready')
                stores[port] = (ready.get('rate') or {}).get('store')
            ok_store = all(v == 'redis' for v in stores.values())

            # 两个进程各打 12 次，加起来 24 次；共享计数时只该放行 20 次
            barrier = threading.Barrier(24)

            def hit(i):
                port = PORTS[i % 2]
                barrier.wait()
                return port, api(port, '/api/community/users/%d/follow' % target[1],
                                 {'on': True}, follower[0])

            with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
                res = list(pool.map(hit, range(24)))
            codes = [r[1][0] for r in res]
            allowed = codes.count(200)
            limited = codes.count(429)

            report('多进程限流', [
                ('绿' if ok_store else '红', '两个进程都报 rate.store=redis', stores),
                ('绿' if (allowed == LIMIT and limited == 24 - LIMIT) else '红',
                 '两个进程合计只放行 %d 次（放行 %d / 拒绝 %d）' % (LIMIT, allowed, limited),
                 {'放行': allowed, '拒绝': limited})], tally)

            fanout = {}
            workers = {}
            for port in PORTS:
                st, ready = api(port, '/health/ready')
                info = ready.get('chat') or {}
                fanout[port] = info.get('fanout')
                workers[port] = info.get('worker')
            report('C07 跨进程：投递层就绪', [
                ('绿' if all(v == 'redis' for v in fanout.values()) else '红',
                 '两个 worker 都如实报 chat.fanout=redis（投递层真的起来了）', fanout),
                ('绿' if len(set(w for w in workers.values() if w)) == 2 else '红',
                 '两个进程有各自的 worker 身份（否则跨进程判定是在骗自己）', workers)], tally)

            for title, coro in (('跨进程消息投递', section_message()),
                                ('同进程投递不重复', section_same_worker()),
                                ('跨进程通话', section_call()),
                                ('在线状态不被别的 worker 误删', section_presence()),
                                ('统一撤销跨进程当场生效', section_revoke()),
                                ('以库为准的空闲检查（封号）', section_db_authority()),
                                ('崩溃进程的忙线回收', section_crash_recovery())):
                try:
                    report(title, run_async(coro), tally)
                except Exception as error:
                    print('  红 %s 判据没跑完：%s: %s' % (title, type(error).__name__, error))
                    tally[0] += 1
                    tally[1] += 1
        finally:
            shutdown(procs, logs)

        # Redis 掉了要"看得见地降级"，不是继续声称跨进程能投
        procs, logs = [], []
        try:
            dead = dict(env, QINGSU_REDIS_PORT=DEAD_REDIS_PORT, _TAG='deadredis')
            started = boot(temp, dead, PORTS)
            if started:
                procs, logs = started
                report('Redis 不可用时的诚实降级（两个进程都连不上 Redis）',
                       run_async(section_local_only(), 90), tally)
            else:
                tally[0] += 3
                tally[1] += 3
        except Exception as error:
            print('  红 Redis 降级判据没跑完：%s: %s' % (type(error).__name__, error))
            tally[0] += 3
            tally[1] += 3
        finally:
            shutdown(procs, logs)

        passed, failed = tally[0] - tally[1], tally[1]
        counted = tally[0] == EXPECTED_ROWS
        print('  %s 判据条数自证：实跑 %d 条与声明的 %d 条一致（对不上＝有整节没跑到）'
              % ('绿' if counted else '红', tally[0], EXPECTED_ROWS))
        print('结论：本文件 %d 条判据通过 / %d 条红（Redis 在场，跨进程判据全部实测）'
              % (passed, failed))
        return 1 if (failed or not counted) else 0


if __name__ == '__main__':
    sys.exit(main())
