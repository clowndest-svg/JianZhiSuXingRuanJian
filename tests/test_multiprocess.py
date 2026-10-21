# -*- coding: utf-8 -*-
"""多进程限流回归：证明"限流计数"是全局一份，不是每个 worker 各算一份。

为什么要单独立一条：限流键存在 Redis 里时多进程才准；Redis 不可用会退回进程内内存，
那时两个 worker 各放行一份，实际阈值悄悄变成 N 倍——功能看着正常，防护已经形同虚设。

判据：两个独立 Uvicorn 进程打同一个键，加起来只放行 limit 次；
      两边 /health/ready 都要如实报 rate.store=redis。

Redis 不在就跳过共享计数断言（不静默通过）；但两个进程的冷启动始终要验，
否则"多进程"这条连进程都起不来也能算绿。

用法:
    python tests/test_multiprocess.py
"""
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


def main():
    shared = redis_ready()

    (ROOT / '_audit_sandbox').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / '_audit_sandbox',
                                     ignore_cleanup_errors=True) as temp:
        env = os.environ.copy()
        for kind in ('DB', 'UPLOAD', 'WEB'):
            env['QINGSU_' + kind + '_DIR'] = temp + '/' + kind
        env['QINGSU_CACHE_NAMESPACE'] = 'qingsu-mp-%d-%d' % (os.getpid(), int(time.time()))
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        procs = []
        logs = []
        try:
            for port in PORTS:
                log = open(os.path.join(temp, 'srv-%d.log' % port), 'w')
                logs.append(log)
                procs.append(subprocess.Popen(
                    [sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1',
                     '--port', str(port), '--no-access-log'],
                    cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
                    # Windows 上另起一个进程组：否则 terminate 会把跑测试的这个 shell 一起带走
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                   if os.name == 'nt' else 0)))
            for port, proc in zip(PORTS, procs):
                if not wait_up(port, proc):
                    log = os.path.join(temp, 'srv-%d.log' % port)
                    detail = ''
                    if os.path.exists(log):
                        detail = Path(log).read_text(errors='replace')[-600:]
                    print('红 进程 %d 没起来' % port)
                    print(detail)
                    return 1
            print('绿 两个独立进程能在同一个数据库上同时冷启动')
            if not shared:
                print('跳过：本机没有可用的 Redis，多进程共享计数无从验证')
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

            print('=== 多进程限流：2 条判据 ===')
            print('  %s 两边都报 rate.store=redis  -> %s' % ('绿' if ok_store else '红', stores))
            print('  %s 两个进程合计只放行 %d 次（放行 %d / 拒绝 %d）'
                  % ('绿' if (allowed == LIMIT and limited == 24 - LIMIT) else '红',
                     LIMIT, allowed, limited))
            return 0 if (ok_store and allowed == LIMIT) else 1
        finally:
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


if __name__ == '__main__':
    sys.exit(main())
