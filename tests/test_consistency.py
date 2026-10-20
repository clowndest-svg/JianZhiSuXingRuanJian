# -*- coding: utf-8 -*-
"""并发与一致性回归台：起一个真 Uvicorn，用真 SQLite，让同一批请求同时打进去。

判据只认"落到库里的样子"，不看接口怎么回话：
重复提交要么只有一行，要么回 duplicate 而不是 500；计数列必须和明细行数对得上；
并发下不许出现负计数、不许 5xx、不许 database is locked。

用法:
    python tests/test_consistency.py
"""
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:18002'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
checks = []
STATUSES = []


def check(name, ok, detail=''):
    checks.append((name, bool(ok), detail))


def api(path, body=None, token=None, timeout=30):
    req = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json',
                 **({'Authorization': 'Bearer ' + token} if token else {})})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            STATUSES.append(r.status)
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        STATUSES.append(e.code)
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except Exception as e:
        STATUSES.append(599)
        return 599, {'detail': type(e).__name__}


def burst(n, fn):
    """让 n 个线程尽量同时出发：Barrier 卡住再一起放。"""
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait()
        return fn(i)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def main():
    (ROOT / '_audit_sandbox').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / '_audit_sandbox') as temp:
        env = os.environ.copy()
        for kind in ('DB', 'UPLOAD', 'WEB'):
            env['QINGSU_' + kind + '_DIR'] = temp + '/' + kind
        env['QINGSU_CACHE_NAMESPACE'] = 'qingsu-consistency-%d-%d' % (os.getpid(), int(time.time()))
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        db_path = os.path.join(temp, 'DB', 'qingsu.db')
        log_path = os.path.join(temp, 'server.log')
        proc = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1',
             '--port', '18002', '--no-access-log'],
            cwd=str(ROOT), env=env,
            stdout=open(log_path, 'w'), stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with OPENER.open(BASE + '/health', timeout=1):
                        break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError('API 没起来')

            # ---- 夹具：4 个账号 ----
            users = []
            for i in range(4):
                st, body = api('/api/register', {
                    'username': 'cc%02d_%d' % (i, int(time.time() * 1000) % 100000),
                    'password': 'Passw0rd!%d' % i, 'age': 30, 'height': 170,
                    'weight_jin': 160, 'target_weight_jin': 140})
                assert st == 200, (st, body)
                users.append((body['token'], body['id']))
            tokens = [u[0] for u in users]
            ids = [u[1] for u in users]

            # ---- 1. 同一用户并发点赞同一帖：只能算一次 ----
            st, post = api('/api/community/posts', {'text': '并发点赞夹具'}, tokens[0])
            assert st == 200, (st, post)
            pid = post['post']['id']
            res = burst(20, lambda i: api('/api/community/posts/%d/like' % pid, {'on': True}, tokens[1]))
            likes = [r[1].get('like_count') for r in res if r[0] == 200]
            check('并发点赞同一帖不重复计数', likes and max(likes) == 1, likes[:5])
            check('并发点赞没有 5xx', all(r[0] < 500 for r in res), [r[0] for r in res][:5])

            # ---- 2. 三个人各并发点一次：计到 3 ----
            def like_by(i):
                return api('/api/community/posts/%d/like' % pid, {'on': True}, tokens[i % 3 + 1])
            res = burst(9, like_by)
            conn = sqlite3.connect(db_path)
            cnt = conn.execute('SELECT like_count FROM posts WHERE id=?', (pid,)).fetchone()[0]
            rows = conn.execute('SELECT COUNT(*) FROM post_likes WHERE post_id=?', (pid,)).fetchone()[0]
            check('多人并发点赞计数等于明细行数', cnt == rows == 3, {'like_count': cnt, 'rows': rows})
            conn.close()

            # ---- 3. 并发取消点赞：不许出现负数 ----
            res = burst(20, lambda i: api('/api/community/posts/%d/like' % pid, {'on': False}, tokens[1]))
            conn = sqlite3.connect(db_path)
            cnt = conn.execute('SELECT like_count FROM posts WHERE id=?', (pid,)).fetchone()[0]
            neg = conn.execute('SELECT COUNT(*) FROM posts WHERE like_count<0').fetchone()[0]
            conn.close()
            check('并发取消点赞不留负数', cnt >= 0 and neg == 0, {'like_count': cnt, 'negative_rows': neg})

            # ---- 4. 同一 request_id 并发打卡：只记一次 ----
            res = burst(20, lambda i: api('/api/workout/complete', {'request_id': 'wk-same'}, tokens[0]))
            conn = sqlite3.connect(db_path)
            n = conn.execute("SELECT COUNT(*) FROM workout_logs WHERE user_id=?", (ids[0],)).fetchone()[0]
            conn.close()
            ok_codes = [r[0] for r in res]
            check('同一 request_id 并发打卡只落一行', n == 1, {'rows': n, 'codes': sorted(set(ok_codes))})
            check('重复打卡回 duplicate 而不是报错',
                  all(c == 200 for c in ok_codes) and
                  sum(1 for r in res if r[1].get('duplicate')) == 19,
                  {'codes': sorted(set(ok_codes)),
                   'dups': sum(1 for r in res if r[1].get('duplicate'))})

            # ---- 5. 同一 request_id 并发发帖：只落一行（换一个人发，避开 6 篇/分钟的限流） ----
            res = burst(5, lambda i: api('/api/community/posts',
                                         {'text': '并发发帖夹具', 'request_id': 'p-same'}, tokens[3]))
            conn = sqlite3.connect(db_path)
            n = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=? AND request_id='p-same'",
                             (ids[3],)).fetchone()[0]
            conn.close()
            codes = [r[0] for r in res]
            check('同一 request_id 并发发帖只落一行', n == 1, {'rows': n, 'codes': codes})
            check('并发发帖不返回 5xx', all(c < 500 for c in codes), codes)

            # ---- 6. 同一 request_id 并发评论：只落一行 ----
            res = burst(10, lambda i: api('/api/community/posts/%d/comments' % pid,
                                          {'text': '并发评论夹具', 'request_id': 'c-same'}, tokens[1]))
            conn = sqlite3.connect(db_path)
            n = conn.execute("SELECT COUNT(*) FROM comments WHERE user_id=? AND request_id='c-same'",
                             (ids[1],)).fetchone()[0]
            conn.close()
            codes = [r[0] for r in res]
            check('同一 request_id 并发评论只落一行', n == 1, {'rows': n, 'codes': codes})
            check('并发评论不返回 5xx', all(c < 500 for c in codes), codes)

            # ---- 7. 同一 request_id 并发私信：只落一条 ----
            res = burst(20, lambda i: api('/api/chat/send',
                                          {'to': ids[2], 'text': '并发私信夹具',
                                           'request_id': 'm-same'}, tokens[0]))
            conn = sqlite3.connect(db_path)
            n = conn.execute("SELECT COUNT(*) FROM messages WHERE from_id=? AND request_id='m-same'",
                             (ids[0],)).fetchone()[0]
            conn.close()
            codes = [r[0] for r in res]
            check('同一 request_id 并发私信只落一条', n == 1, {'rows': n, 'codes': codes})
            check('并发私信不返回 5xx', all(c < 500 for c in codes), codes)

            # ---- 8. 并发关注：只落一行，且超阈值后开始 429（阈值 20/分钟） ----
            res = burst(24, lambda i: api('/api/community/users/%d/follow' % ids[2], {'on': True}, tokens[0]))
            conn = sqlite3.connect(db_path)
            n = conn.execute('SELECT COUNT(*) FROM follows WHERE follower_id=? AND followee_id=?',
                             (ids[0], ids[2])).fetchone()[0]
            conn.close()
            codes = [r[0] for r in res]
            check('并发关注只落一行', n == 1, {'rows': n, 'codes': sorted(set(codes))})
            check('关注超阈值后回 429 而不是硬扛', 429 in codes, sorted(set(codes)))

            # ---- 9. 并发注册同名：只能成功一个 ----
            same = 'dup_%d' % (int(time.time() * 1000) % 100000)
            res = burst(10, lambda i: api('/api/register', {
                'username': same, 'password': 'Passw0rd!dup', 'age': 30,
                'height': 170, 'weight_jin': 160, 'target_weight_jin': 140}))
            codes = [r[0] for r in res]
            conn = sqlite3.connect(db_path)
            n = conn.execute('SELECT COUNT(*) FROM users WHERE username=?', (same,)).fetchone()[0]
            conn.close()
            check('并发注册同名只成功一个', n == 1 and codes.count(200) == 1,
                  {'rows': n, 'codes': codes})
            check('并发注册没有 5xx', all(c < 500 for c in codes), codes)

            # ---- 10. 计数列与明细对得上 ----
            conn = sqlite3.connect(db_path)
            bad = conn.execute(
                'SELECT p.id, p.like_count, (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) '
                'FROM posts p').fetchall()
            conn.close()
            drift = [(r[0], r[1], r[2]) for r in bad if r[1] != r[2]]
            check('like_count 与点赞明细一致', not drift, drift[:3])

            # ---- 11. 库本身没坏 ----
            conn = sqlite3.connect(db_path)
            fk = conn.execute('PRAGMA foreign_key_check').fetchall()
            integ = conn.execute('PRAGMA integrity_check').fetchone()[0]
            conn.close()
            check('外键没有孤儿行', not fk, fk[:3])
            check('库完整性检查通过', integ == 'ok', integ)

            # ---- 12. 全程没有 5xx / 锁冲突 ----
            five = sum(1 for s in STATUSES if s >= 500)
            check('全程没有 5xx', five == 0, {'5xx': five, 'total': len(STATUSES)})
        finally:
            proc.terminate()
            proc.wait(timeout=15)
        text = Path(log_path).read_text(errors='replace').lower()
        locked = text.count('database is locked')
        check('全程没有 database is locked', locked == 0, {'locked': locked})

    green = [c for c in checks if c[1]]
    red = [c for c in checks if not c[1]]
    print('=== 并发与一致性：%d 条，绿 %d，红 %d ===' % (len(checks), len(green), len(red)))
    for name, ok, detail in checks:
        print('  %s %s%s' % ('绿' if ok else '红', name, '' if ok else '  -> ' + str(detail)))
    return 0 if not red else 1


if __name__ == '__main__':
    sys.exit(main())
