"""B03 / B04 / B09 的服务端与结构判据（方案验收线，不是"代码长这样"）。

风格照 tests/test_optimization_data.py：借用运维台夹具的 disposable 主库，
每个用例一套空库，真发请求、真读库。界面上才验得出的那些（点一下输入框变没变、
探针挂了渲染成什么）在 tests/records-profile-permission.mjs 里跑真浏览器。

写这些判据时立的一条规矩：凡"分组覆盖全字段""扫满 300 笔"这类断言，必须正向钉每一项，
只证 子集⊆全集 证明不了没漏。
"""
import importlib.util
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADMIN = Path(os.environ.get('QINGSU_ADMIN_REPO', str(ROOT.parent / 'JianZhiSuXingRuanJianHouTai')))
spec = importlib.util.spec_from_file_location('ux_fixture', ADMIN / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

ASSETS = ROOT / 'app' / 'src' / 'main' / 'assets'

# B04 要拆的那 8 个字段：这是验收线写死的清单，不是从 PROFILE_GROUPS 里推出来的，
# 否则分组漏了某项，判据会跟着一起漏。
PROFILE_FIELDS = ['gender', 'age', 'height', 'weight_jin', 'target_weight_jin',
                  'goal_type', 'dining_mode', 'scene']


def asset(name):
    return (ASSETS / name).read_text(encoding='utf-8')


class UserContracts(fixture.OpsApi):

    # ------------------------------------------------------------ 小工具
    def auth_as(self, token):
        return {'Authorization': 'Bearer ' + token}

    def add_meals(self, uid, pairs):
        """按 (菜名, 次数) 直接写历史，绕开估算通道：这里要钉的是归属与聚合，不是估算。"""
        c = sqlite3.connect(self.db)
        try:
            for name, times in pairs:
                for n in range(times):
                    c.execute(
                        "INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,source,"
                        "estimate_reason,created_at) VALUES (?,?,'午餐',?,?, 'direct','判据造的',"
                        "'2026-01-01 12:00:00')", (uid, '2026-01-%02d' % (n % 28) + str(n % 9), name, 500))
            c.commit()
        finally:
            c.close()

    def recent(self, token, query=''):
        return self.app.get('/api/food/recent' + query, headers=self.auth_as(token))

    # ============================================================ B03
    def test_ux_recent_meals_only_returns_own_history(self):
        """/api/food/recent 只能长出自己的菜：B 记了 9 次的菜，A 一条都不许看到。

        这条是"常用餐食"的命门。它一旦混进全站热门菜，界面上写着"你自己常记的"
        就变成假的，用户照着点还会记错账。
        """
        mine, peer = self.signup['id'], self.other['id']
        self.add_meals(mine, [('番茄炒蛋', 3), ('鸡胸饭', 2), ('牛肉面', 1)])
        self.add_meals(peer, [('麻辣烫', 9), ('螺蛳粉', 7)])

        body = self.recent(self.signup['token'], '?limit=20').json()
        names = [x['food_name'] for x in body['items']]

        # 正向钉：别人的两个菜，一个都不许出现在我的列表里
        for foreign in ('麻辣烫', '螺蛳粉'):
            self.assertNotIn(foreign, names, '本人常用餐食里混进了别人的菜')
        self.assertEqual(set(names), {'番茄炒蛋', '鸡胸饭', '牛肉面'}, names)

        # 按出现次数从多到少排；times 必须是真数出来的次数
        times = [x['times'] for x in body['items']]
        self.assertEqual(times, sorted(times, reverse=True), '没按次数排序：%s' % times)
        self.assertEqual({x['food_name']: x['times'] for x in body['items']},
                         {'番茄炒蛋': 3, '鸡胸饭': 2, '牛肉面': 1}, body['items'])
        self.assertEqual(body['scoped'], 'self', body)

    def test_ux_recent_meals_note_admits_it_stopped_at_the_scan_cap(self):
        """扫满 RECENT_MEAL_SCAN_CAP 就必须在 note 里承认"只扫了这么多笔"。

        没读完却写"已读完全部"，用户会以为低频老菜被抹掉是真的没吃过；
        这条钉的是诚实，不是排序。
        """
        cap = self.app_mod.RECENT_MEAL_SCAN_CAP
        self.assertEqual(cap, 300, 'RECENT_MEAL_SCAN_CAP 被改了，note 那句话的口径要跟着重看')
        uid = self.signup['id']
        c = sqlite3.connect(self.db)
        try:
            # 比上限多写 20 笔，且让最早那几笔是一个独有的菜名：上限截断后它不该出现
            for n in range(cap + 20):
                c.execute("INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,created_at)"
                          " VALUES (?,?,'午餐',?,600,'2026-01-01 12:00:00')",
                          (uid, '2026-%02d-%02d' % (n // 28 + 1, n % 28 + 1),
                           '压箱底老菜' if n < 5 else ('近期菜' + str(n))))
            c.commit()
        finally:
            c.close()

        body = self.recent(self.signup['token'], '?limit=20').json()
        self.assertEqual(body['scanned'], cap, body)
        note = body['note']
        self.assertIn('只扫了最近', note, note)
        self.assertIn(str(cap), note, note)
        self.assertNotIn('已读完', note, '只扫了 %d 笔却宣称读完了全部：%s' % (cap, note))

        # 反面对照：记录没到上限时，"已读完"才允许出现
        other = self.app.post('/api/register', json=dict(
            self.app_body, username='uxfewmeals', password='Review!123', age=30,
            height=170, weight_jin=160, target_weight_jin=140)).json()
        self.add_meals(other['id'], [('清炒时蔬', 2)])
        few = self.recent(other['token'], '?limit=20').json()
        self.assertLess(few['scanned'], cap, few)
        self.assertIn('已读完', few['note'], few)

    def test_ux_recent_meals_rejects_out_of_range_limit(self):
        """limit 越界要当场 400；没登录不许读到任何人的菜。"""
        for bad in ('?limit=0', '?limit=21', '?limit=-1', '?limit=99999'):
            r = self.recent(self.signup['token'], bad)
            self.assertEqual(r.status_code, 400, '%s -> %s %s' % (bad, r.status_code, r.text))
        for good in ('?limit=1', '?limit=20'):
            self.assertEqual(self.recent(self.signup['token'], good).status_code, 200, good)
        anon = self.app.get('/api/food/recent')
        self.assertIn(anon.status_code, (401, 403), anon.text)

    def test_ux_weight_conversion_has_one_truth_only(self):
        """斤↔kg 的换算只许有一处真值（JIN_PER_KG），展示层不许再手算 /2 或 *2。

        库里存斤、kg 只是展示口径。谁在模板里再写一次 /2，某一天就会长出
        "顶栏 81.5 / 图表 82 / 档案 80"各说一套。
        """
        src = asset('app.js')
        decl = re.findall(r'const\s+JIN_PER_KG\s*=\s*([^;]+);', src)
        self.assertEqual(len(decl), 1, 'JIN_PER_KG 的定义应当且只能有一处：%s' % decl)
        self.assertEqual(decl[0].strip(), '2', '换算真值被改了：%s' % decl[0])

        # 每个换算函数都必须走 JIN_PER_KG，而不是自己带一个数字 2
        for fn in ('jinToKg', 'kgToJin'):
            body = re.search(r'function\s+%s\s*\([^)]*\)\s*\{(.*?)\n\}' % fn, src, re.S)
            self.assertTrue(body, '换算函数 %s 不见了' % fn)
            inner = body.group(1)
            self.assertIn('JIN_PER_KG', inner, '%s 没走那唯一一处真值：%s' % (fn, inner))
            self.assertNotIn(' 2 ', inner.replace('/JIN_PER_KG', ''),
                             '%s 里疑似手算了固定倍数：%s' % (fn, inner))

        # 格式化层不许自己乘除：formatKg / kgOf 只能转手调 jinToKg
        for fn in ('formatKg', 'kgOf', 'formatJin'):
            body = re.search(r'function\s+%s\s*\([^)]*\)\s*\{(.*?)\n\}' % fn, src, re.S)
            self.assertTrue(body, '展示函数 %s 不见了' % fn)
            inner = body.group(1)
            self.assertNotRegex(inner, r'[*/]\s*2(?![.\d])',
                                '%s 在展示层手算了换算倍数：%s' % (fn, inner))
        self.assertIn('jinToKg', re.search(r'function\s+formatKg.*?\n\}', src, re.S).group(0))
        self.assertIn('jinToKg', re.search(r'function\s+kgOf.*?\n\}', src, re.S).group(0))

    # ============================================================ B04
    def test_ux_profile_groups_cover_every_field_exactly_once(self):
        """档案四组必须不重不漏地盖住那 8 个字段——逐项正向钉。

        "每组的键 ⊆ 8 个字段"这种写法证明不了没漏：整组少写一个字段照样过。
        """
        src = asset('app.js')
        block = re.search(r'const PROFILE_GROUPS = \{(.*?)\n\};', src, re.S)
        self.assertTrue(block, 'app.js 里找不到 PROFILE_GROUPS')
        groups = {}
        # 按 keys: [...] 锚定来切组：最后一组（dining）收笔是 "}" 而不是 "},"，
        # 靠尾逗号切正则会把整组丢掉，漏项的判据就跟着一起漏了。
        for key, body in re.findall(
                r'(\w+)\s*:\s*\{.*?keys:\s*\[([^\]]*)\]', block.group(1), re.S):
            groups[key] = re.findall(r'"([^"]+)"', body)
        self.assertEqual(sorted(groups), ['basic', 'dining', 'goal', 'scene'],
                         '档案分组应当且只能是那四组：%s' % groups)

        # 正向：每个字段恰好属于一组（出现一次且仅一次）
        for field in PROFILE_FIELDS:
            owners = [g for g, ks in groups.items() if field in ks]
            self.assertEqual(len(owners), 1,
                             '%s 落在 %d 个组里（应为恰好 1 组）：%s' % (field, len(owners), owners))
        # 反向：组里不许出现清单外的字段
        flat = [k for ks in groups.values() for k in ks]
        self.assertEqual(sorted(flat), sorted(PROFILE_FIELDS),
                         '分组与 8 字段清单不齐：多/少 %s' % (set(flat) ^ set(PROFILE_FIELDS)))
        self.assertEqual(len(flat), len(set(flat)), '同一字段被分到两组：%s' % flat)

    def test_ux_saving_scene_group_touches_weight_and_other_groups_not(self):
        """只改训练场景并保存，体重与其他组的字段一个都不许动（真发请求，读库核对）。

        r176 之前这条路是全量重发，点一下场景就把档案里的旧体重写回，顶栏跟着变。
        """
        uid = self.signup['id']
        c = sqlite3.connect(self.db)
        # 注册那条基准就落在"今天"，留着它的话 latest 与档案值天然相等，
        # 分叉这个被测状态根本造不出来。清掉后写一条比档案新的称重。
        c.execute("DELETE FROM weight_logs WHERE user_id=?", (uid,))
        c.execute("INSERT INTO weight_logs(user_id,log_date,weight_jin,waist_cm,created_at)"
                  " VALUES (?, '2026-01-01', 155.5, 0, '2026-01-01 07:00:00')", (uid,))
        c.commit(); c.close()
        logs_before = len(self.sql("SELECT id FROM weight_logs WHERE user_id=?", (uid,)))
        self.assertEqual(logs_before, 1, logs_before)

        before = {r['k']: r['v'] for r in self.sql(
            "SELECT 'gender' AS k, gender AS v FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'age', age FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'height', height FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'weight_jin', weight_jin FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'target_weight_jin', target_weight_jin FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'goal_type', goal_type FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'dining_mode', dining_mode FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'scene', scene FROM profiles WHERE user_id=?", (uid,) * 8)}
        self.assertEqual(float(before['weight_jin']), 160.0, before)

        r = self.app.post('/api/profile/update', headers=self.auth_as(self.signup['token']),
                          json={'scene': 'gym'})
        self.assertEqual(r.status_code, 200, r.text)

        after = {x['k']: x['v'] for x in self.sql(
            "SELECT 'gender' AS k, gender AS v FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'age', age FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'height', height FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'weight_jin', weight_jin FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'target_weight_jin', target_weight_jin FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'goal_type', goal_type FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'dining_mode', dining_mode FROM profiles WHERE user_id=?"
            " UNION ALL SELECT 'scene', scene FROM profiles WHERE user_id=?", (uid,) * 8)}
        self.assertEqual(after['scene'], 'gym', after)
        for field in PROFILE_FIELDS:
            if field == 'scene':
                continue
            self.assertEqual(after[field], before[field],
                             '只存场景却把 %s 从 %r 改成了 %r' % (field, before[field], after[field]))
        # 也不许顺手补一条今天的称重记录（那是体重那条路该干的事）：
        # 补了就把 155.5 那次真称重盖掉，顶栏跟着从 155.5 跳回档案的 160。
        logs_after = self.sql("SELECT log_date, weight_jin FROM weight_logs WHERE user_id=?"
                              " ORDER BY log_date DESC, id DESC", (uid,))
        self.assertEqual(len(logs_after), logs_before,
                         '只存训练场景却往体重表写了东西：%s' % logs_after)
        self.assertEqual(float(logs_after[0]['weight_jin']), 155.5, logs_after)
        dash = self.app.get('/api/dashboard', headers=self.auth_as(self.signup['token'])).json()
        self.assertEqual(float(dash['current_weight_jin']), 155.5,
                         '存完场景顶栏体重被档案旧值顶掉了：%s' % dash['current_weight_jin'])

    def test_ux_dashboard_weight_is_the_latest_weighing_not_the_profile(self):
        """r177：顶栏那个体重读的是"最近一次称重"，不是档案里的 weight_jin。

        档案可能比打卡旧；拿档案值画顶栏，用户刚称完 155 顶栏还写 160。
        """
        uid = self.signup['id']
        c = sqlite3.connect(self.db)
        # 注册时已经按"今天"写过一条基准称重，它比我下面两个日期都新；
        # 不清掉的话 latest 永远是那条 160，判据测的就不是排序而是 fixture 的运气。
        c.execute("DELETE FROM weight_logs WHERE user_id=?", (uid,))
        # 档案停在 160，最近一次称重是 155.5 —— 两个数必须能分出胜负
        c.execute("INSERT INTO weight_logs(user_id,log_date,weight_jin,waist_cm,created_at)"
                  " VALUES (?, '2026-02-01', 155.5, 0, '2026-02-01 07:00:00')", (uid,))
        c.execute("INSERT INTO weight_logs(user_id,log_date,weight_jin,waist_cm,created_at)"
                  " VALUES (?, '2026-01-05', 170.0, 0, '2026-01-05 07:00:00')", (uid,))
        c.commit(); c.close()

        dash = self.app.get('/api/dashboard', headers=self.auth_as(self.signup['token'])).json()
        self.assertEqual(float(dash['current_weight_jin']), 155.5, dash['current_weight_jin'])
        profile = self.sql("SELECT weight_jin FROM profiles WHERE user_id=?", (uid,))[0]
        self.assertEqual(float(profile['weight_jin']), 160.0, profile)
        self.assertNotEqual(float(dash['current_weight_jin']), float(profile['weight_jin']),
                            '顶栏被档案值顶替了，r177 那条就白留了')

    # ============================================================ B09
    def test_ux_export_is_real_and_self_scoped(self):
        """导出这条路必须真的通、且只含本人流水——不能是个装了样子点了没动静的按钮。"""
        mine, peer = self.signup['id'], self.other['id']
        self.add_meals(mine, [('我的紫米饭', 1)])
        self.add_meals(peer, [('同事的卤肉饭', 1)])
        r = self.app.get('/api/export.csv', headers=self.auth_as(self.signup['token']))
        self.assertEqual(r.status_code, 200, r.text)
        text = r.text
        self.assertIn('我的紫米饭', text)
        self.assertNotIn('同事的卤肉饭', text, '导出里夹了别人的记录')
        self.assertEqual(self.app.get('/api/export.csv').status_code, 401,
                         '导出没鉴权，谁都能拉走别人的流水')

    def test_ux_no_user_side_account_deletion_endpoint(self):
        """本人侧没有"一键注销"这个接口——这是那条 B09 判据的前提。

        接口不存在时，界面上就只能说"提交了诉求、单号多少"，
        绝不许摆一颗写着已经注销/立即删除的按钮。records-profile-permission.mjs
        拿着这个前提去钉真实 DOM。
        """
        paths = sorted({getattr(rt, 'path', '') for rt in self.app_mod.app.routes})
        self.assertTrue(paths, '路由都枚举不出来，这条判据就形同没跑')
        deleting = [p for p in paths
                    if re.search(r'/api/(account/(delete|destroy)|users?/(me|self)/delete'
                                 r'|delete-account|deletion|deactivate)\b', p)]
        self.assertEqual(deleting, [], '出现了本人侧注销接口，界面那条判据要跟着重看：%s' % deleting)
        # 记录删除是另一回事（删一条流水），别把它当成注销账号的凭据
        self.assertTrue(any('records' in p and 'delete' in p for p in paths),
                        '连单条记录删除都没有，说明路由枚举没生效')

    def test_ux_deletion_request_lands_as_feedback_not_a_delete(self):
        """界面上那颗注销入口走的是意见反馈(kind=data)：真发一次，确认它只建单不删数据。"""
        before = self.sql("SELECT COUNT(*) AS n FROM users")
        r = self.app.post('/api/feedback', headers=self.auth_as(self.signup['token']),
                          json={'kind': 'data', 'text': '判据造的注销诉求', 'page': 'account-center',
                                'contact': ''})
        self.assertEqual(r.status_code, 200, r.text)
        ticket = r.json()['id']
        self.assertGreater(int(ticket), 0, r.text)
        mine = self.app.get('/api/feedback/mine', headers=self.auth_as(self.signup['token'])).json()
        row = [x for x in mine['items'] if x['id'] == ticket]
        self.assertEqual(len(row), 1, mine)
        self.assertEqual(row[0]['kind'], 'data', row[0])
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM users"), before,
                         '提个注销诉求就把用户删了')
        # 状态得答得出来，界面那句"现在什么状态"才不是空话
        self.assertIn('status', row[0], row[0])


if __name__ == '__main__':
    names = [n for n in unittest.defaultTestLoader.getTestCaseNames(UserContracts)
             if n.startswith('test_ux_')]
    suite = unittest.TestSuite(UserContracts(n) for n in names)
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
