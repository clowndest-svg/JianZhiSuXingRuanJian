"""Second-batch database contracts against disposable main/admin fixtures."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADMIN = Path(os.environ.get('QINGSU_ADMIN_REPO', str(ROOT.parent / 'JianZhiSuXingRuanJianHouTai')))
spec = importlib.util.spec_from_file_location('batch2_fixture', ADMIN / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class DataContracts(fixture.OpsApi):
    def test_batch2_migration_registry_is_self_consistent(self):
        """登记表必须自洽：版本号＝清单最后一条，每条都答得出归属。

        加了一条迁移忘了抬版本，是这种改动里最容易犯、也最难事后发现的一种。
        """
        from app_modules import migrations
        self.assertEqual(migrations.SCHEMA_VERSION, max(v for v, *_ in migrations.MIGRATIONS),
                         'SCHEMA_VERSION 与迁移清单最后一条不一致')
        self.assertEqual(len({v for v, *_ in migrations.MIGRATIONS}), len(migrations.MIGRATIONS),
                         '迁移版本号重复')
        for version, name, owner, detail in migrations.MIGRATIONS:
            self.assertIn(owner, ('app', 'admin'), '第 %d 条没登记归属者' % version)
            self.assertTrue(name and detail, '第 %d 条没写清改了什么' % version)
        self.assertTrue(set(migrations.ADMIN_OWNED_TABLES),
                        '后台自有表必须登记，否则两仓会抢同一张表')

    def test_batch2_schema_version_is_registered_and_reported(self):
        from app_modules import migrations
        ready = self.app.get('/health/ready').json()
        self.assertEqual(ready['schema_version'], migrations.SCHEMA_VERSION,
                         '库里的结构版本没登记上，后台无法判断主服务够不够新')
        self.assertEqual(ready['schema_required'], migrations.SCHEMA_VERSION)
        # 后台是跨进程读主应用的，这里把那一跳换成真实读数：
        # 判据要钉的是"配对信息答没答得出"，不是本机 8100 端口通不通。
        with patch.object(self.ops_mod, 'json_get', return_value=(ready, None)):
            paired = self.ops.get('/api/version-pairing', headers=self.bearer).json()
        self.assertEqual(paired['missing_app_columns'], [],
                         '后台说缺列，但库其实是新的：%s' % paired)
        self.assertEqual(paired['app_schema_version'], migrations.SCHEMA_VERSION)
        self.assertTrue(paired['paired'], '两边版本一致却没报配对成功')
        with patch.object(self.ops_mod, 'json_get', return_value=(None, 'connection_refused')):
            silent = self.ops.get('/api/version-pairing', headers=self.bearer).json()
        self.assertFalse(silent['paired'], '主应用没答话却被当成版本已配对')
        self.assertEqual(silent['app_schema_version'], None, '拿不到读数却编了一个版本号')

    def test_batch2_guard_refuses_stale_or_unknown_schema(self):
        """SKIP_MIGRATE 模式下 import 不动结构，但库落后或版本未知时必须拒绝启动。"""
        from app_modules import migrations
        with patch.object(migrations, 'read', return_value=migrations.SCHEMA_VERSION - 1):
            with self.assertRaises(RuntimeError) as raised:
                self.app_mod.guard_schema_version()
        self.assertIn('结构版本', str(raised.exception))
        with patch.object(migrations, 'read', return_value=None):
            with self.assertRaises(RuntimeError):
                self.app_mod.guard_schema_version()
        with patch.object(migrations, 'read', return_value=migrations.SCHEMA_VERSION):
            self.assertEqual(self.app_mod.guard_schema_version(), migrations.SCHEMA_VERSION)

    def test_batch2_admin_refuses_high_risk_write_when_schema_behind(self):
        """后台要写的列还不存在时，必须在建单之前就拒，而不是写完才 500。"""
        original = dict(self.ops_mod.APP_REQUIRED_COLUMNS)
        self.ops_mod.APP_REQUIRED_COLUMNS.update({'users': ('a_column_nobody_added_yet',)})
        try:
            before = self.sql('SELECT pw_salt FROM users WHERE id=?', (self.signup['id'],))[0]['pw_salt']
            denied = self.ops.post('/api/users/%d/reset-password' % self.signup['id'],
                                   json={'expect_username': 'opsowner'}, headers=self.bearer)
            self.assertEqual(denied.status_code, 503, denied.text)
            self.assertIn('a_column_nobody_added_yet', denied.text, '没答得出到底缺哪一列')
            self.assertEqual(self.sql('SELECT pw_salt FROM users WHERE id=?',
                                      (self.signup['id'],))[0]['pw_salt'], before,
                             '结构不匹配却还是把口令改了')
        finally:
            self.ops_mod.APP_REQUIRED_COLUMNS.clear()
            self.ops_mod.APP_REQUIRED_COLUMNS.update(original)

    def test_batch2_cursor_pages_and_filters(self):
        self.ops_mod.audit('test', 'prepare')
        c = self.ops_mod.db()
        try:
            for n in range(123):
                c.execute("INSERT INTO users(id,username,password_hash,nickname,public_id) VALUES (?,?,?,?,?)", (n+100, 'page'+str(n), 'synthetic', 'page', str(n+50000000)))
                c.execute("INSERT INTO feedback(user_id,kind,body,app_build,created_at) VALUES (?,'bug','synthetic',62,'test')", (self.signup['id'],))
                c.execute("INSERT INTO content_reports(target_kind,target_id,reporter,reason,created_at) VALUES ('post',?,?,'synthetic','test')", (n+1, self.signup['id']))
                c.execute("INSERT INTO admin_audit(actor,action,target_kind,created_at) VALUES ('test','batch2','users','test')")
            c.commit()
        finally:
            c.close()
        for path in ('/api/users?q=page', '/api/feedback?kind=bug&build=62', '/api/reports?status=all&target_kind=post', '/api/audit?action=batch2&target_kind=users'):
            cursor, ids = 0, []
            while True:
                response = self.ops.get(path + '&limit=20&cursor=' + str(cursor), headers=self.bearer)
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertEqual(data['total'], 123)
                ids.extend(item['id'] for item in data['items'])
                if not data['more']:
                    self.assertEqual(data['next_cursor'], 0)
                    break
                self.assertLess(data['next_cursor'], cursor or float('inf'))
                cursor = data['next_cursor']
            self.assertEqual(len(ids), 123, path)
            self.assertEqual(len(set(ids)), 123, path)
            self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(self.ops.get('/api/feedback?kind=idea', headers=self.bearer).json()['total'], 0)
        self.assertEqual(self.ops.get('/api/audit?cursor=-1', headers=self.bearer).status_code, 422)
        first = self.ops.get('/api/users?q=page&limit=20', headers=self.bearer).json()
        c = self.ops_mod.db()
        c.execute("INSERT INTO users(id,username,password_hash,nickname,public_id) VALUES (9999,'page-new','synthetic','page','99999999')")
        c.commit(); c.close()
        second = self.ops.get('/api/users?q=page&limit=20&cursor='+str(first['next_cursor']), headers=self.bearer).json()
        self.assertFalse({item['id'] for item in first['items']} & {item['id'] for item in second['items']})
        self.assertNotIn(9999, {item['id'] for item in second['items']})

    def test_batch2_community_page_has_bounded_queries_and_correct_state(self):
        uid, peer = self.signup['id'], self.other['id']
        c = self.app_mod.get_db()
        try:
            for n in range(12):
                pid = c.execute("INSERT INTO posts(user_id,body,created_at) VALUES (?,?,'test')", (uid if n%2 else peer, str(n))).lastrowid
                c.execute("INSERT INTO post_favorites VALUES (?,?,'test')", (pid, uid))
                if n%2:
                    c.execute("INSERT INTO post_likes VALUES (?,?,'test')", (pid, uid))
            c.execute("INSERT INTO follows VALUES (?,?,'test')", (uid, peer))
            c.commit()
        finally:
            c.close()
        statements = []
        original = self.app_mod.get_db
        def traced():
            connection = original()
            connection.set_trace_callback(lambda sql: statements.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
            return connection
        with patch.object(self.app_mod, 'get_db', traced):
            result = self.app_mod.community_feed(tab='latest', cursor=0, limit=12, user={'id': uid})
        self.assertEqual(len(result['items']), 12)
        self.assertLessEqual(len(statements), 8, statements)
        for card in result['items']:
            self.assertEqual(card['favorite_count'], 1)
            self.assertTrue(card['favorited_by_me'])
            self.assertEqual(card['followed_by_me'], card['author']['id'] == peer)
            self.assertEqual(card['liked_by_me'], card['mine'])
        print('community_page_selects=' + str(len(statements)))

    def test_batch2_offline_occurrence_day_and_idempotency(self):
        c = self.app_mod.get_db()
        c.execute("UPDATE users SET created_at='2026-01-01 00:00:00' WHERE id=?", (self.signup['id'],))
        c.commit(); c.close()
        at = datetime.now(timezone.utc) - timedelta(days=2)
        offset = -480
        day = (at - timedelta(minutes=offset)).date().isoformat()
        occurrence = {'occurred_at': at.isoformat(), 'timezone_offset_minutes': offset, 'log_date': day}
        auth = {'Authorization': 'Bearer ' + self.signup['token']}
        for endpoint, body, table in [('/api/food/log', {'slot':'晚餐','food_name':'synthetic','cal':600}, 'food_logs'), ('/api/workout/complete', {'duration_minutes':20,'cal_burned':100}, 'workout_logs')]:
            payload = {**body, **occurrence, 'request_id': table+'-offline'}
            for _ in range(2):
                response = self.app.post(endpoint, headers=auth, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
            rows = self.sql('SELECT log_date,occurred_at,timezone_offset_minutes FROM '+table)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['log_date'], day)
            self.assertEqual(rows[0]['timezone_offset_minutes'], offset)
            bad = self.app.post(endpoint, headers=auth, json={**payload,'request_id':'bad-'+table,'log_date':'2026-01-02'})
            self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.sql('SELECT log_date FROM daily_modes')[0]['log_date'], day)
        future = self.app.post('/api/food/log', headers=auth, json={'food_name':'x','slot':'晚餐','log_date':'2099-01-01'})
        self.assertEqual(future.status_code, 400)


if __name__ == '__main__':
    suite = unittest.TestSuite(DataContracts(name) for name in unittest.defaultTestLoader.getTestCaseNames(DataContracts) if name.startswith('test_batch2_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
