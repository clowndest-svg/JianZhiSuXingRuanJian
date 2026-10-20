"""Real isolated database tests for summaries, goal privacy and push lifecycle."""
import base64
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app_modules import webpush


class Companion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for key in ('DB', 'UPLOAD', 'WEB', 'KEY'):
            os.environ['QINGSU_' + key + '_DIR'] = str(self.root / key)
        spec = importlib.util.spec_from_file_location('companion_server', ROOT / 'server.py')
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.m._redis_cmd = lambda *a, **k: (False, None)
        self.c = TestClient(self.m.app)
        self.users = []
        for name in ('owner', 'friend', 'stranger'):
            r = self.c.post('/api/register', json=dict(username=name, password='Review!123', age=30, height=170, weight_jin=160, target_weight_jin=140))
            self.assertEqual(r.status_code, 200, r.text)
            self.users.append(r.json())
        self.auth = self.headers(0)

    def headers(self, who):
        return {'Authorization': 'Bearer ' + self.users[who]['token']}

    def post(self, path, body, who=0):
        return self.c.post(path, json=body, headers=self.headers(who))

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_summary_missing_data_and_account_boundary(self):
        d = self.c.get('/api/summary', headers=self.auth).json()
        self.assertEqual(d['days'], 7)
        self.assertIsNone(d['average_recorded_kcal'])
        self.assertIsNone(d['weight_change_jin'])
        self.assertTrue(all(r['recorded_kcal'] is None for r in d['rows']))
        self.post('/api/food/log', {'slot': '午餐', 'food_name': '面包', 'cal': 500})
        today = date.today().isoformat()
        self.post('/api/day/complete', {'log_date': today, 'complete': True})
        d = self.c.get('/api/summary?days=30', headers=self.auth).json()
        self.assertEqual(d['calorie_sample_days'], 1)
        self.assertEqual(d['average_recorded_kcal'], 500)
        self.assertEqual(self.c.get('/api/summary', headers=self.headers(1)).json()['calorie_sample_days'], 0)
        self.assertEqual(self.c.get('/api/summary').status_code, 401)
        self.assertEqual(self.c.get('/api/summary?days=999', headers=self.auth).status_code, 400)
        self.assertEqual(self.c.get('/api/summary?end=2099-01-01', headers=self.auth).status_code, 400)

    def test_weight_trend_requires_two_distinct_dates(self):
        for weight in (150, 149):
            self.post('/api/weight/log', {'weight_jin': weight})
        self.assertIsNone(self.c.get('/api/summary', headers=self.auth).json()['weight_change_jin'])
        c = self.m.get_db()
        c.execute('INSERT INTO weight_logs(user_id,log_date,weight_jin) VALUES (?,?,?)', (self.users[0]['id'], (date.today() - timedelta(days=1)).isoformat(), 152))
        c.commit(); c.close()
        self.assertEqual(self.c.get('/api/summary', headers=self.auth).json()['weight_change_jin'], -3)

    def test_shared_goal_consent_privacy_and_repeated_join(self):
        made = self.post('/api/goals', {'title': '一起训练', 'target': 3}).json()
        self.assertEqual(self.c.get('/api/goals', headers=self.headers(1)).json()['items'], [])
        for _ in range(2):
            self.assertEqual(self.post('/api/goals/join', {'code': made['invite']}, 1).status_code, 200)
        self.post('/api/workout/complete', {'request_id': 'goal-one'})
        self.post('/api/workout/complete', {'request_id': 'goal-two'})
        r = self.c.get('/api/goals', headers=self.headers(1)).json()
        g = r['items'][0]
        self.assertEqual(len(g['members']), 2)
        self.assertEqual(g['members'][0]['days'], 1)
        for forbidden in ('weight', 'cal', 'token', 'invite_hash', 'owner_id', 'photo'):
            self.assertNotIn(forbidden, json.dumps(r))
        self.assertEqual(self.post('/api/goals/' + str(made['id']) + '/leave', {}, 2).status_code, 404)
        self.post('/api/goals/' + str(made['id']) + '/leave', {})
        self.assertEqual(self.c.get('/api/goals', headers=self.headers(1)).json()['items'], [])
        self.assertEqual(self.post('/api/goals/join', {'code': made['invite']}, 1).status_code, 404)

    def test_goals_reject_expired_invite_and_invalid_target(self):
        self.assertEqual(self.post('/api/goals', {'title': 'x', 'target': 8, 'days': 7}).status_code, 400)
        made = self.post('/api/goals', {'title': 'x'}).json()
        c = self.m.get_db(); c.execute('UPDATE shared_goals SET end_date=?', ('2000-01-01',)); c.commit(); c.close()
        self.assertEqual(self.post('/api/goals/join', {'code': made['invite']}, 1).status_code, 404)

    def provision(self):
        key = self.root / 'KEY/webpush-vapid.pem'
        webpush.provision(key)
        self.endpoint = 'https://fcm.googleapis.com/fcm/send/fixture'
        enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        self.sub = {'endpoint': self.endpoint, 'keys': {'p256dh': enc(b'\x04' + b'x' * 64), 'auth': enc(b'a' * 16)}}
        self.assertEqual(self.post('/api/push/subscribe', self.sub).status_code, 200)
        return key

    def test_push_endpoint_allowlist(self):
        self.provision()
        for url in ('http://fcm.googleapis.com/x', 'https://127.0.0.1/x', 'https://fcm.googleapis.com.evil.test/x', 'https://user@fcm.googleapis.com/x', 'https://fcm.googleapis.com:444/x'):
            with self.subTest(url=url):
                self.assertEqual(self.post('/api/push/subscribe', dict(self.sub, endpoint=url)).status_code, 400)
        self.assertEqual(self.post('/api/push/subscribe', dict(self.sub, keys={})).status_code, 400)

    def test_dispatch_deduplicates_and_never_sends_message_content(self):
        key = self.provision()
        self.post('/api/chat/send', {'to': self.users[0]['id'], 'text': 'PRIVATE_BODY', 'request_id': 'p-one'}, 1)
        c = self.m.get_db(); calls = []
        result = webpush.dispatch(c, key, send=lambda **kw: calls.append(kw))
        self.assertEqual(result['sent'], 1)
        self.assertNotIn('PRIVATE_BODY', repr(calls))
        self.assertNotIn('data', calls[0])
        self.assertEqual(webpush.dispatch(c, key, send=lambda **kw: calls.append(kw))['sent'], 0)
        self.post('/api/logout', {})
        self.assertEqual(webpush.dispatch(c, key, send=lambda **kw: calls.append(kw))['sent'], 0)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0], 0)
        c.close()

    def test_subscription_moves_to_new_account_and_cannot_be_removed_by_previous(self):
        self.provision()
        self.post('/api/push/subscribe', self.sub, 1)
        self.post('/api/push/unsubscribe', {'endpoint': self.endpoint})
        c = self.m.get_db()
        self.assertEqual(c.execute('SELECT user_id FROM push_subscriptions').fetchone()[0], self.users[1]['id'])
        c.close()

    def test_legacy_ip_manifest_remains_upgradeable(self):
        p = self.root / 'WEB/version.json'
        p.write_text(json.dumps({'version_code': 45, 'apk_url': 'https://scientificexploration.art/qingsu.apk'}))
        self.assertEqual(self.c.get('/version.json', headers={'Host': '124.220.54.64'}).json()['apk_url'], 'https://124.220.54.64/qingsu.apk')
        self.assertEqual(self.c.get('/version.json', headers={'Host': 'scientificexploration.art'}).json()['apk_url'], 'https://scientificexploration.art/qingsu.apk')


if __name__ == '__main__':
    unittest.main(verbosity=2)
