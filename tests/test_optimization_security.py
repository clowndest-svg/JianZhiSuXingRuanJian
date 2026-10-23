"""Cross-repository security regressions, using disposable local fixtures only."""
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ops_fixture', Path(os.environ.get('QINGSU_ADMIN_REPO', str(ROOT.parent / 'JianZhiSuXingRuanJianHouTai'))) / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Security(fixture.OpsApi):
    # Run only these regressions; the inherited suite is run separately.

    # ---- A06 抬门闭环 ----
    def test_optimization_gate_refuses_a_release_nobody_can_install(self):
        """清单说 34，就得真有一个"对得上"的包：包不见、哈希被换、包内自报旧构建号，三种都要拒。"""
        cases = ['包不在', '哈希不符', '包内自报旧构建号']
        for label in cases:
            with self.subTest(label):
                apk = fixture.write_fake_release(self.root, 34)
                manifest_path = self.root / 'WEB' / 'version.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if label == '包不在':
                    apk.unlink()
                elif label == '哈希不符':
                    manifest['sha256'] = 'deadbeef'
                else:
                    with zipfile.ZipFile(apk, 'w') as archive:
                        archive.writestr('assets/app.js', 'const APP_BUILD = 33;\n')
                    blob = apk.read_bytes()
                    manifest.update(size=len(blob), sha256=hashlib.sha256(blob).hexdigest())
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                with patch.object(self.ops_mod, 'json_get', return_value=({'min_build': 0, 'gate': {}}, None)):
                    with self.assertRaises(Exception) as raised:
                        self.ops_mod.gate_set({'expect_current': 0, 'new': 34}, 'test')
                self.assertEqual(raised.exception.status_code, 409, label + '：门居然被抬了')
                self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), '0',
                                 label + '：被拒之后门文件还是被动过')
        self.assertGreaterEqual(len(self.audits('raise_gate_refused')), 3,
                                '拒了三次却一条没记，事后查不到谁试过抬装不上的版本')

    def test_optimization_gate_read_back_mismatch_is_reverted(self):
        """主应用答话了、答的不是刚写进去的值：这才是真不一致，必须回退并说清。"""
        fixture.write_fake_release(self.root, 34)
        with patch.object(self.ops_mod, 'json_get', return_value=({'min_build': 20, 'gate': {}}, None)):
            with self.assertRaises(Exception) as raised:
                self.ops_mod.gate_set({'expect_current': 0, 'new': 34}, 'test')
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), '0',
                         '回读不一致却没回退，用户会被挡在一个没人确认的门外面')
        reverted = self.audits('raise_gate_reverted')
        self.assertTrue(reverted, '回退了但审计里没有这一笔')
        self.assertIn('20', json.dumps(reverted, ensure_ascii=False), '回退记录没留下主应用实际答的值')

    def test_optimization_gate_when_app_is_silent_says_unconfirmed(self):
        """主应用联系不上 ≠ 读回不一致：门文件已写对，不能谎称生效，也不该悄悄回退。"""
        fixture.write_fake_release(self.root, 34)
        with patch.object(self.ops_mod, 'json_get', return_value=(None, 'connection_refused')):
            out = self.ops_mod.gate_set({'expect_current': 0, 'new': 34}, 'test')
        self.assertFalse(out['confirmed'], '主应用没答话却报了已确认')
        self.assertIsNone(out['reported_by_app'], '没拿到回读就编了一个生效值')
        self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), '34',
                         '联系不上就把门退回去，等于这次操作凭空消失')
        self.assertTrue(self.audits('raise_gate_unconfirmed'), '未确认这件事没落审计')

    def test_optimization_gate_two_threads_one_writer(self):
        """两个线程同时抬门：借的是业务库写锁 + 期望旧值，必须只有一个改得动。

        同线程测不出锁——sqlite3 的连接在同一线程里根本不会互相挡。
        """
        fixture.write_fake_release(self.root, 34)
        results = []
        barrier = threading.Barrier(2)

        def worker(new):
            barrier.wait()
            try:
                out = self.ops_mod.gate_set({'expect_current': 0, 'new': new}, 'test')
                results.append(('ok', out['written']))
            except Exception as error:
                results.append(('err', getattr(error, 'status_code', type(error).__name__)))

        with patch.object(self.ops_mod, 'json_get',
                          return_value=(None, 'connection_refused')):
            threads = [threading.Thread(target=worker, args=(code,)) for code in (33, 34)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len([r for r in results if r[0] == 'ok']), 1,
                         '两个并发抬门都成功了：门文件被后写的盖掉，前一次操作静默丢失 %r' % results)
        final = Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip()
        self.assertIn(final, ('33', '34'), '门停在一个谁都没写过的值上：%s' % final)

    # ---- A02 后台会话生命周期 ----
    def _session_row(self, cookie):
        c = self.ops_mod.db()
        try:
            return c.execute('SELECT * FROM ops_sessions WHERE token_hash=?',
                             (hashlib.sha256(cookie.encode()).hexdigest(),)).fetchone()
        finally:
            c.close()

    def _age_session(self, cookie, **changes):
        c = self.ops_mod.db()
        try:
            sets = ', '.join(key + '=?' for key in changes)
            c.execute('UPDATE ops_sessions SET ' + sets + ' WHERE token_hash=?',
                      (*changes.values(), hashlib.sha256(cookie.encode()).hexdigest()))
            c.commit()
        finally:
            c.close()

    def test_optimization_admin_session_idle_absolute_and_rotation(self):
        """空闲到期、绝对到期、凭据轮换三条路各自都要能把旧会话挡在门外。"""
        self.ops.post('/api/login', json={'token': 'dev-token-please-rotate'})
        cookie = self.ops.cookies.get('qops')
        self.assertTrue(self._session_row(cookie), '登录没在服务端留下会话')
        row = self._session_row(cookie)
        self.assertEqual(row['actor'], 'console', '会话里没记是谁')
        self.assertGreater(row['absolute_expires_at'], row['created_at'], '绝对到期没写')

        self._age_session(cookie, last_seen_at=int(time.time()) - self.ops_mod.SESSION_IDLE_TTL - 5)
        self.assertEqual(self.ops.get('/api/whoami', headers={'Cookie': 'qops=' + cookie}).status_code,
                         401, '空闲到期的会话还在用')
        self.assertIsNone(self._session_row(cookie), '到期会话只是被拒，没被清掉')

        self.ops.post('/api/login', json={'token': 'dev-token-please-rotate'})
        cookie = self.ops.cookies.get('qops')
        self._age_session(cookie, absolute_expires_at=int(time.time()) - 1)
        self.assertEqual(self.ops.get('/api/whoami', headers={'Cookie': 'qops=' + cookie}).status_code,
                         401, '绝对到期的会话还在用')

        self.ops.post('/api/login', json={'token': 'dev-token-please-rotate'})
        cookie = self.ops.cookies.get('qops')
        os.environ['OPS_OPERATORS_JSON'] = json.dumps({'console': 'rotated-secret'})
        try:
            self.assertEqual(self.ops.get('/api/whoami', headers={'Cookie': 'qops=' + cookie}).status_code,
                             401, '口令换过了，旧会话还认')
            self.ops.cookies.clear()
            denied = self.ops.post('/api/login', json={'token': 'dev-token-please-rotate'})
            self.assertEqual(denied.status_code, 401, '旧口令轮换后还能登录')
            granted = self.ops.post('/api/login', json={'operator': 'console', 'token': 'rotated-secret'})
            self.assertEqual(granted.status_code, 200, granted.text)
        finally:
            os.environ.pop('OPS_OPERATORS_JSON', None)

    def test_optimization_named_operators_and_revoke(self):
        """多管理员：审计要分得清是谁；一把口令对多个人时不许顶掉某个具体的人。"""
        os.environ['OPS_OPERATORS_JSON'] = json.dumps({'xiaotian': 'token-a', 'runner': 'token-b'})
        try:
            self.ops.post('/api/login', json={'token': 'token-a'})
            self.assertEqual(self.ops.get('/api/whoami').json()['actor'], 'xiaotian',
                             '唯一命中时没认出命名账号，审计还是查不到人')
            shared = self.ops.post('/api/login', json={'operator': 'runner', 'token': 'token-b'})
            self.assertEqual(shared.status_code, 200, shared.text)
            self.assertEqual(self.ops.get('/api/whoami').json()['actor'], 'runner')
            online = self.ops.get('/api/sessions').json()['items']
            self.assertEqual({row['actor'] for row in online}, {'xiaotian', 'runner'},
                             '在线会话列不出来：换人时不知道该撤谁')
            replay = self.ops.cookies.get('qops')
            self.ops.post('/api/logout', json={})
            self.assertEqual(self.ops.get('/api/whoami', headers={'Cookie': 'qops=' + replay}).status_code,
                             401, 'runner 退出后旧 Cookie 还能用')
        finally:
            os.environ.pop('OPS_OPERATORS_JSON', None)
        os.environ['OPS_OPERATORS_JSON'] = json.dumps({'xiaotian': 'same', 'runner': 'same'})
        try:
            self.ops.cookies.clear()
            ambiguous = self.ops.post('/api/login', json={'token': 'same'})
            self.assertEqual(ambiguous.status_code, 401,
                             '两把凭据共用一个口令时，不带 operator 也放行了——登录的人到底算谁')
            named = self.ops.post('/api/login', json={'operator': 'xiaotian', 'token': 'same'})
            self.assertEqual(named.status_code, 200, named.text)
            self.assertEqual(self.ops.get('/api/whoami').json()['actor'], 'xiaotian')
            wrong = self.ops.post('/api/login', json={'operator': 'nobody', 'token': 'same'})
            self.assertEqual(wrong.status_code, 401, '报了个不存在的 operator 还给了登录态')
        finally:
            os.environ.pop('OPS_OPERATORS_JSON', None)

    def test_optimization_revoke_needs_confirm_for_others(self):
        os.environ['OPS_OPERATORS_JSON'] = json.dumps({'xiaotian': 'token-a', 'runner': 'token-b'})
        try:
            self.ops.post('/api/login', json={'operator': 'runner', 'token': 'token-b'})
            runner_cookie = self.ops.cookies.get('qops')
            self.ops.cookies.clear()
            self.ops.post('/api/login', json={'operator': 'xiaotian', 'token': 'token-a'})
            self.assertEqual(self.ops.post('/api/sessions/revoke',
                                             json={'target_actor': 'runner'}).status_code, 409,
                             '撤别人的会话不给确认短语就放行')
            self.assertTrue(self.ops.get('/api/whoami',
                                         headers={'Cookie': 'qops=' + runner_cookie}).json()['actor'])
            done = self.ops.post('/api/sessions/revoke',
                                 json={'target_actor': 'runner',
                                       'confirm': '撤销 runner 的全部后台会话'})
            self.assertEqual(done.status_code, 200, done.text)
            self.assertEqual(done.json()['revoked'], 1)
            self.assertEqual(self.ops.get('/api/whoami',
                                          headers={'Cookie': 'qops=' + runner_cookie}).status_code, 401)
            self.assertTrue(self.audits('revoke_admin_sessions'))
        finally:
            os.environ.pop('OPS_OPERATORS_JSON', None)

    # ---- C01 降权后必须经 helper ----
    def test_optimization_privileged_actions_go_through_helpers(self):
        """服务账号降权之后，改门/备份/查容器只能经 sudo 调 helper。

        这条钉的是"配了 helper 就不许自己直接写"：一旦回退成直接写，
        要么进程还是 root（降权白做），要么写不动却报成功。
        """
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))

            class Done:
                returncode, stdout, stderr = 0, '', ''
            return Done()

        fixture.write_fake_release(self.root, 34)
        original = Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip()
        with patch.object(self.ops_mod, 'GATE_HELPER', '/usr/local/sbin/qingsu-set-gate'), \
                patch.object(self.ops_mod.subprocess, 'run', fake_run):
            self.ops_mod.write_min_build(30)
        self.assertEqual(calls, [['sudo', '-n', '/usr/local/sbin/qingsu-set-gate', '30']],
                         '没按参数白名单的形状调用 helper')
        self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), original,
                         '配了 helper 却还是本进程直接把门写了')

    def test_optimization_helper_failure_is_not_a_success(self):
        fixture.write_fake_release(self.root, 34)
        original = Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip()

        class Denied:
            returncode, stdout, stderr = 1, '', 'sudo: a password is required'

        with patch.object(self.ops_mod, 'GATE_HELPER', '/usr/local/sbin/qingsu-set-gate'), \
                patch.object(self.ops_mod.subprocess, 'run', lambda *a, **k: Denied()):
            with self.assertRaises(Exception) as raised:
                self.ops_mod.write_min_build(31)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn('password', raised.exception.detail)
        self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), original,
                         'helper 失败了，门却像是改过了')

    def test_optimization_privileged_endpoint_reports_missing_helpers(self):
        with patch.object(self.ops_mod, 'GATE_HELPER', ''), \
                patch.object(self.ops_mod, 'BACKUP_HELPER', '/usr/local/sbin/qingsu-backup'), \
                patch.object(self.ops_mod, 'HEALTH_HELPER', ''):
            out = self.ops.get('/api/privileged', headers=self.bearer).json()
        self.assertEqual(sorted(out['missing_helpers']), ['gate', 'health'],
                         '缺哪个 helper 必须点名，不能只说"未配置"')
        self.assertFalse(out['gate'])

    def test_optimization_backup_verifies_even_when_dir_is_not_readable(self):
        """降权后备份目录 root:700 读不到：校验要改读脚本自己打的那行 JSON，读不到就红。"""
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))

            class Done:
                returncode, stdout, stderr = 0, json.dumps({'backup': 'qingsu-synthetic.db',
                                                            'integrity': 'ok'}), ''
            return Done()

        with patch.object(self.ops_mod, 'BACKUP_HELPER', '/usr/local/sbin/qingsu-backup'), \
                patch.object(self.ops_mod.subprocess, 'run', fake_run), \
                patch.object(self.ops_mod.os, 'listdir', side_effect=PermissionError):
            out = self.ops.post('/api/backup', json={}, headers=self.bearer)
        self.assertEqual(out.status_code, 200, out.text)
        self.assertFalse(out.json()['directory_readable'], '读不到目录却说读得到')
        self.assertEqual(out.json()['integrity'], 'ok')
        self.assertEqual(calls, [['sudo', '-n', '/usr/local/sbin/qingsu-backup']],
                         '备份 helper 不该收任何参数')



        def fake_run_bad(argv, **kwargs):
            class Done:
                returncode, stdout, stderr = 0, '没有那行 JSON', ''
            return Done()

        with patch.object(self.ops_mod, 'BACKUP_HELPER', '/usr/local/sbin/qingsu-backup'), \
                patch.object(self.ops_mod.subprocess, 'run', fake_run_bad), \
                patch.object(self.ops_mod.os, 'listdir', side_effect=PermissionError):
            bad = self.ops.post('/api/backup', json={}, headers=self.bearer)
        self.assertEqual(bad.status_code, 500,
                         '脚本没给出可核验的校验结果，接口却当备份成功')
        self.assertIn('verifiable', bad.text)

    def test_optimization_orphan_scan_counts_thumbnails_as_referenced(self):
        """缩略图不落表（按需生成，名字是 原图名 + .thumb.jpg）。

        只按"表里出现过的文件名"比对的话，每张有效图的缩略图都会被报成孤儿——
        A10 当初报的就是这个形状（有效评论配图被误报），换个文件类型又犯一次。
        """
        upload = Path(self.ops_mod.UPLOAD_DIR)
        keep = upload / 'referenced-post.jpg'
        keep.write_bytes(b'synthetic-original')
        (upload / 'referenced-post.jpg.thumb.jpg').write_bytes(b'synthetic-thumb')
        (upload / 'genuinely-lost.jpg').write_bytes(b'synthetic-orphan')
        c = self.ops_mod.db()
        try:
            c.execute("INSERT INTO posts(user_id,body,created_at,images) VALUES (?,?,?,?)",
                      (self.signup['id'], '带图帖子', 'test', json.dumps(['/uploads/' + keep.name])))
            c.commit()
        finally:
            c.close()
        # 接口只回计数与体积——文件名本身是敏感列，不能从后台读回来。
        # 所以这条钉的是"三个文件里到底几个被算成孤儿"，不是钉某个名字出现在响应里。
        out = self.ops.get('/api/media/orphans', headers=self.bearer).json()
        self.assertEqual(out['files'], 3, out)
        self.assertEqual(out['referenced'], 2,
                         '缩略图没跟着原图算进引用集：有效帖子的缩略图会被报成孤儿')
        self.assertEqual(out['orphans'], 1, '孤儿数不是 1，要么漏报要么误伤')

    # ---- C10 长任务 ----
    def test_optimization_async_backup_returns_task_and_dedups(self):
        """浏览器关掉不能把结果一起关掉：异步备份要回任务号，连点两下只能有一份在跑。"""
        with patch.object(self.ops_mod, '_spawn_backup_task', lambda task_id, actor: None):
            first = self.ops.post('/api/backup', json={'async': True}, headers=self.bearer).json()
            second = self.ops.post('/api/backup', json={'async': True}, headers=self.bearer).json()
        self.assertTrue(first['task_id'], '没给任务号，关掉页面就再也查不回来')
        self.assertEqual(first['task_id'], second['task_id'],
                         '同一操作者连点两下起了两份备份：' + str((first, second)))
        # 两次请求都可能各起一个线程，真正的闸门是 claim 的原子性：
        # 只允许把 pending 改成 running 的那一次去跑备份，第二次必须领不到。
        ran = []
        store = self.ops_mod.long_tasks()
        with patch.object(self.ops_mod, 'backup_now',
                          side_effect=lambda *a, **k: ran.append(1) or {'code': 0}):
            first_run = self.ops_mod.run_backup_task(first['task_id'], 'test')
            second_run = self.ops_mod.run_backup_task(first['task_id'], 'test')
        self.assertEqual(len(ran), 1, '同一份任务被跑了两遍，等于连点两下真备份两次')
        self.assertEqual(first_run['claimed'], True)
        self.assertEqual(second_run['claimed'], False, '已终态的任务还能被领走重跑')
        looked_up = self.ops.get('/api/backup/' + first['task_id'], headers=self.bearer)
        self.assertEqual(looked_up.status_code, 200, looked_up.text)
        self.assertEqual(looked_up.json()['task']['kind'], 'backup')
        self.assertEqual(self.ops.get('/api/backup/nope-nope', headers=self.bearer).status_code, 404,
                         '查一个不存在的任务号却给了东西')

    def test_optimization_async_backup_failure_is_recorded_not_swallowed(self):
        """备份在线程里失败必须落到任务终态：否则界面永远显示"进行中"，而活其实早死了。

        终态名跟着任务模块的口径走：可重试的失败记成 interrupted（能被下一轮领走），
        不可重试才记 failed。这里要钉的是"停在非 running 的可查状态 + 原因在结果里"。
        """
        store = self.ops_mod.long_tasks()
        task = store.enqueue('backup', args={}, owner='test', dedup_key='manual-fail')
        with patch.object(self.ops_mod, 'backup_now',
                          side_effect=self.ops_mod.HTTPException(500, '合成失败')):
            outcome = self.ops_mod.run_backup_task(task['id'], 'test')
        self.assertEqual(outcome['status'], 'failed', outcome)
        final = store.status(task['id'])
        self.assertEqual(final['status'], 'interrupted',
                         '任务停在 %s：要么没落终态，要么可重试的口径被改掉了' % final['status'])
        self.assertIn('合成失败', json.dumps(final['result_json'], ensure_ascii=False),
                      '失败原因没跟着任务落下来，运维只能看到"红了"')
        retried = store.enqueue('backup', args={}, owner='test', dedup_key='manual-fail')
        self.assertEqual(retried['id'], task['id'], '可重试的失败没被同一 dedup_key 复用重跑')
        # attempts 是"领走一次加一"，不是"排队一次加一"：领走才算真跑过一趟
        self.assertTrue(store.claim(task['id'], 'test'), '可重试的任务领不走，重跑这条路是断的')
        self.assertEqual(store.status(task['id'])['attempts'], 2,
                         '重跑没累加次数，看不出这是第几次')

    def test_optimization_async_backup_success_lands_result(self):
        store = self.ops_mod.long_tasks()
        task = store.enqueue('backup', args={}, owner='test', dedup_key='manual-done')
        with patch.object(self.ops_mod, 'backup_now', return_value={'code': 0, 'integrity': 'ok'}):
            outcome = self.ops_mod.run_backup_task(task['id'], 'test')
        self.assertEqual(outcome['status'], 'done', outcome)
        final = store.status(task['id'])
        self.assertEqual(final['status'], 'done')
        self.assertEqual(final['result_json']['result']['integrity'], 'ok',
                         '结果没存进任务，查状态等于什么都没查到')

    def test_optimization_temporary_password_is_restricted_and_single_use(self):
        result = self.ops_mod.reset_password(self.signup['id'], {'expect_username': 'opsowner'}, 'test')
        body = {'username': 'opsowner', 'password': result['one_time_password']}
        first = self.app.post('/api/login', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()['password_change_required'])
        self.assertEqual(self.app.post('/api/login', json=body).status_code, 400)
        headers = {'Authorization': 'Bearer ' + first.json()['token']}
        self.assertEqual(self.app.get('/api/dashboard', headers=headers).status_code, 403)
        self.assertEqual(self.app.post('/api/chat/ticket', headers=headers).status_code, 403)
        finish = self.app.post('/api/account/recovery-password', headers=headers, json={'new_password': 'NewSecure!123'})
        self.assertEqual(finish.status_code, 200, finish.text)
        self.assertEqual(self.app.get('/api/dashboard', headers=headers).status_code, 200)
        self.assertEqual(self.app.post('/api/login', json=body).status_code, 400)
        self.assertEqual(self.app.post('/api/login', json={'username': 'opsowner', 'password': 'NewSecure!123'}).status_code, 200)

    def test_optimization_expired_temporary_password_is_rejected(self):
        result = self.ops_mod.reset_password(self.signup['id'], {'expect_username': 'opsowner'}, 'test')
        c = self.ops_mod.db()
        c.execute('UPDATE users SET reset_expires_at=1 WHERE id=?', (self.signup['id'],))
        c.commit(); c.close()
        self.assertEqual(self.app.post('/api/login', json={'username': 'opsowner', 'password': result['one_time_password']}).status_code, 400)

    def test_optimization_socket_revoke_and_ban(self):
        from starlette.websockets import WebSocketDisconnect
        auth = {'Authorization': 'Bearer ' + self.signup['token']}
        for operation, code in [('ban', 4403), ('revoke', 4401)]:
            ticket = self.app.post('/api/chat/ticket', headers=auth, json={}).json()['ticket']
            with self.app.websocket_connect('/ws/chat?ticket=' + ticket) as ws:
                self.assertEqual(ws.receive_json()['t'], 'ready')
                payload = {'expect_username': 'opsowner', 'reason': 'test'}
                if operation == 'ban':
                    self.ops_mod.ban(self.signup['id'], payload, 'test')
                else:
                    self.ops_mod.revoke_sessions(self.signup['id'], payload, 'test')
                ws.send_json({'t': 'send', 'to': self.other['id'], 'text': 'must not persist'})
                with self.assertRaises(WebSocketDisconnect) as raised:
                    ws.receive_json()
                self.assertEqual(raised.exception.code, code)
            if operation == 'ban':
                self.ops_mod.unban(self.signup['id'], payload, 'test')
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM messages')[0]['n'], 0)

    def test_optimization_cookie_replay_and_unknown_column(self):
        self.ops.post('/api/login', json={'token': 'dev-token-please-rotate'})
        cookie = self.ops.cookies.get('qops')
        self.ops.post('/api/logout', json={})
        self.assertEqual(self.ops.get('/api/whoami', headers={'Cookie': 'qops=' + cookie}).status_code, 401)
        c = self.ops_mod.db()
        try:
            c.execute('ALTER TABLE users ADD COLUMN future_secret TEXT')
            self.assertNotIn('future_secret', self.ops_mod.safe_columns(c, 'users'))
        finally:
            c.close()

    def test_optimization_audit_failure_rolls_back_and_gate_bounds(self):
        with patch.object(self.ops_mod, 'audit_in', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                self.ops_mod.ban(self.signup['id'], {'expect_username': 'opsowner', 'reason': 'test'}, 'test')
        self.assertFalse(self.sql('SELECT banned_at FROM users WHERE id=?', (self.signup['id'],))[0]['banned_at'])
        with patch.object(self.ops_mod, 'json_get', return_value=({'min_build': 0}, None)):
            with self.assertRaises(Exception) as raised:
                self.ops_mod.gate_set({'expect_current': 0, 'new': 99999}, 'test')
            self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(Path(self.ops_mod.MIN_BUILD_FILE).read_text().strip(), '0')

    def test_optimization_export_recall_and_media_delete(self):
        c = self.ops_mod.db()
        uid, peer = self.signup['id'], self.other['id']
        try:
            self.app_mod._deliver(c, {'id': uid}, peer, 'RECALLED_SECRET', 'test-recall')
            c.execute("UPDATE messages SET recalled_at='2026-10-22 10:00:00'")
            avatar = self.root / 'UPLOAD' / 'owned.jpg'
            avatar.write_bytes(b'synthetic')
            c.execute('UPDATE profiles SET avatar_url=? WHERE user_id=?', ('/uploads/owned.jpg', uid))
            post = c.execute("INSERT INTO posts(user_id,body,created_at) VALUES (?,'post','test')", (uid,)).lastrowid
            comment = c.execute("INSERT INTO comments(post_id,user_id,body,created_at) VALUES (?,?,'comment','test')", (post, peer)).lastrowid
            c.execute("INSERT INTO comment_likes VALUES (?,?,'test')", (comment, peer))
            c.commit()
        finally:
            c.close()
        exported = self.ops_mod.export_user(uid, 'test')
        self.assertNotIn('RECALLED_SECRET', json.dumps(exported))
        payload = {'expect_username': 'opsowner', 'plan_only': True}
        plan = self.ops_mod.delete_account(uid, payload, 'test')
        result = self.ops_mod.delete_account(uid, {'expect_username': 'opsowner', 'confirm_rows': plan['rows']}, 'test')
        self.assertEqual(result['code'], 0)
        self.assertFalse(avatar.exists())
        self.assertEqual(self.sql('PRAGMA foreign_key_check'), [])


    def test_optimization_media_recall_scope_and_expiry(self):
        import io
        from PIL import Image
        raw = io.BytesIO()
        Image.new('RGB', (600,600), (30,60,90)).save(raw, format='JPEG')
        up = self.app.post('/api/community/media', headers=self.auth(), files={'file':('test.jpg',raw.getvalue(),'image/jpeg')})
        self.assertEqual(up.status_code, 200, up.text)
        name = up.json()['name']
        url = up.json()['url']
        expiry = int(url.split('expires=')[1].split('&')[0])
        with patch.object(self.app_mod.time, 'time', return_value=expiry-1):
            near = self.app.get(url+'&thumb=1')
        self.assertEqual(near.status_code, 200)
        self.assertIn('max-age=1', near.headers['cache-control'])
        uid,peer = self.signup['id'],self.other['id']
        conn = self.app_mod.get_db()
        try:
            conn.executemany('INSERT INTO follows VALUES (?,?,?)',[(uid,peer,'test'),(peer,uid,'test')])
            conn.commit()
            message,_ = self.app_mod._deliver(conn,{'id':uid},peer,'','media-security',kind='image',media_name=name)
        finally: conn.close()
        media = message['media_url']
        self.assertIn('no-store', self.app.get(media+'&thumb=1').headers['cache-control'])
        self.assertEqual(self.app.get(media.replace('scope=message','scope=post')).status_code,404)
        recalled = self.app.post('/api/chat/recall',headers=self.auth(),json={'message_id':message['id']})
        self.assertEqual(recalled.status_code,200,recalled.text)
        self.assertEqual(self.app.get(media).status_code,404)
        self.assertEqual(self.app.get(media+'&thumb=1').status_code,404)
        self.assertEqual(self.app.get(url).status_code,404)

    def test_optimization_post_image_scope_follows_visibility(self):
        import io
        from PIL import Image
        raw=io.BytesIO(); Image.new('RGB',(100,100)).save(raw,format='JPEG')
        up=self.app.post('/api/community/media',headers=self.auth(),files={'file':('p.jpg',raw.getvalue(),'image/jpeg')})
        name=up.json()['name']
        conn=self.app_mod.get_db()
        try:
            pid=conn.execute("INSERT INTO posts(user_id,body,images,created_at) VALUES (?,'post',?,'test')",(self.signup['id'],json.dumps([name]))).lastrowid
            conn.commit()
            url=self.app_mod.signed_photo('/uploads/'+name,scope='post',ref=pid)
            self.assertEqual(self.app.get(url).status_code,200)
            conn.execute("UPDATE posts SET status='hidden' WHERE id=?",(pid,));conn.commit()
            self.assertEqual(self.app.get(url).status_code,404)
            self.assertEqual(self.app.get(url+'&thumb=1').status_code,404)
        finally:conn.close()

    def test_optimization_health_survives_private_backup_directory(self):
        original = self.ops_mod.os.listdir
        def restricted(path):
            if str(path) == str(self.ops_mod.BACKUP_DIR): raise PermissionError('restricted')
            return original(path)
        with patch.object(self.ops_mod.os, 'listdir', side_effect=restricted), patch.object(self.ops_mod,'json_get',return_value=({'status':'ok'},None)), patch.object(self.ops_mod,'run_privileged',return_value={'stdout':'running','returncode':0}):
            r=self.ops.get('/api/health',headers=self.bearer)
        self.assertEqual(r.status_code,200,r.text)
        self.assertIsNone(r.json()['recent_backups'])
        self.assertEqual(r.json()['backup_listing'],'restricted')

if __name__ == '__main__':
    suite = unittest.TestSuite(Security(name) for name in unittest.defaultTestLoader.getTestCaseNames(Security) if name.startswith('test_optimization_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
