"""B07 周报判据：三个维度、少量可执行反馈、两类禁止推导。

风格照 tests/test_optimization_ux.py：借用运维台夹具的 disposable 主库，
每个用例一套空库，真发请求、真读库。这里钉的是方案点名的那几条硬线：

- 完整记录日 = 当天餐食/体重/训练都记了；3 天只记体重 + 2 天记全 = 2，
  既不是 5（把只记体重的也算进去），也不是 0（只认 daily_reviews 的确认章）。
- 缺记的那天不产生"摄入 0"，也不进缺口均值。
- 体重只有一个日期：趋势字段是"数据不足"，界面不出现趋势结论。
- 反馈 2~3 条，每条的依据数字都能回到库里；输出不许出现确定性减重承诺。
"""
import importlib.util
import json
import os
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = Path(os.environ.get('QINGSU_ADMIN_REPO', str(ROOT.parent / 'JianZhiSuXingRuanJianHouTai')))
spec = importlib.util.spec_from_file_location('weekly_fixture', ADMIN / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

ASSETS = ROOT / 'app' / 'src' / 'main' / 'assets'

# 正向词表：命中一个就红。方案点名的"按这个速度你会减到 X 斤"属于这一类。
COMMITMENT_WORDS = ('一定会', '保证', '预计可达', '必定', '必然', '肯定', '确保',
                    '承诺', '一定能', '肯定会', '按这个速度', '预计减到', '能减到',
                    '会瘦到', '保证减')


class WeeklyReview(fixture.OpsApi):

    # ------------------------------------------------------------ 造数与取数
    def day(self, offset):
        return (date.today() + timedelta(days=offset)).isoformat()

    def seed(self, meals=(), workouts=(), weights=()):
        """直接写库，绕开估算通道：这里要钉的是聚合口径，不是食物识别。"""
        uid = self.signup['id']
        c = sqlite3.connect(self.db)
        try:
            for table in ('food_logs', 'workout_logs', 'weight_logs', 'daily_reviews'):
                c.execute('DELETE FROM %s WHERE user_id=?' % table, (uid,))
            for off, cal in meals:
                ds = self.day(off)
                # 一天两笔，避免"一天只有一笔"掩盖按天聚合的错误
                c.execute("INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,source)"
                          " VALUES (?,?,'午餐','判据午餐',?,'manual')", (uid, ds, cal // 2))
                c.execute("INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,source)"
                          " VALUES (?,?,'晚餐','判据晚餐',?,'manual')", (uid, ds, cal - cal // 2))
            for off, minutes, burned in workouts:
                c.execute("INSERT INTO workout_logs(user_id,log_date,duration_minutes,cal_burned,plan_name)"
                          " VALUES (?,?,?,?,'判据训练')", (uid, self.day(off), minutes, burned))
            for off, jin in weights:
                c.execute("INSERT INTO weight_logs(user_id,log_date,weight_jin)"
                          " VALUES (?,?,?)", (uid, self.day(off), jin))
            c.commit()
        finally:
            c.close()

    def metrics(self):
        return self.app_mod.compute_metrics(
            self.sql("SELECT * FROM profiles WHERE user_id=?", (self.signup['id'],))[0])

    def review(self, query='?days=7', token=None):
        return self.app.get('/api/weekly/review' + query,
                            headers={'Authorization': 'Bearer ' + (token or self.signup['token'])})

    def seed_full_week(self):
        """3 天只记体重 + 2 天餐食/体重/训练都记 + 2 天全空。"""
        target = self.metrics()['target_cal']
        self.seed(
            meals=[(-3, target), (-2, target - 600)],
            workouts=[(-3, 30, 120), (-2, 30, 120)],
            weights=[(-6, 160.0), (-5, 159.0), (-4, 158.0), (-3, 157.0), (-2, 156.0)])

    def texts(self, body):
        parts = [body.get('coverage_note') or '', body['weight_trend']['text']]
        for item in body['feedback']:
            parts.append(item['text'])
            parts.append(item['basis']['label'])
        return '\n'.join(parts)

    # ============================================================ 判据 1
    def test_weekly_full_record_day_needs_all_three(self):
        """完整记录日只数"餐食+体重+训练都记了"的天：这里是 2，不是 5，也不是 0。"""
        self.seed_full_week()
        body = self.review().json()
        self.assertEqual(body['full_record_days'], 2,
                         '完整记录日算成了 %s（3 天只记体重 + 2 天记全，应为 2）' % body['full_record_days'])
        self.assertNotEqual(body['full_record_days'], 5, '把只记体重的 3 天也算成了完整记录日')
        self.assertNotEqual(body['full_record_days'], 0, '只认 daily_reviews 的确认章，把真实记全的 2 天漏了')
        self.assertEqual(body['meal_days'], 2, body['meal_days'])
        self.assertEqual(body['training_days'], 2, body['training_days'])
        self.assertEqual(body['weight_days'], 5, body['weight_days'])
        # 逐日正向钉：哪两天该是完整记录日，写在断言里，不靠总数碰运气
        full = {r['date'] for r in body['rows'] if r['full_record']}
        self.assertEqual(full, {self.day(-3), self.day(-2)}, full)
        self.assertEqual({r['date'] for r in body['rows'] if r['recorded_kcal'] is not None},
                         {self.day(-3), self.day(-2)})

    # ============================================================ 判据 2
    def test_weekly_missing_day_is_not_zero_intake(self):
        """只记体重的 3 天：没有摄入记录，也没有缺口；缺口均值只除有餐食的 2 天。"""
        self.seed_full_week()
        metrics = self.metrics()
        body = self.review().json()
        weight_only = [r for r in body['rows'] if r['weight_jin'] is not None and r['recorded_kcal'] is None]
        self.assertEqual(len(weight_only), 3, weight_only)
        for row in weight_only:
            self.assertIsNone(row['recorded_kcal'], '缺记的那天被塞了摄入数：%s' % row)
            self.assertIsNone(row['deficit_kcal'], '缺记的那天被算出了缺口：%s' % row)
            self.assertNotEqual(row['recorded_kcal'], 0, '缺记被当成 0 卡：%s' % row)
            self.assertNotEqual(row['deficit_kcal'], 0, '缺记被当成 0 缺口：%s' % row)
        # 缺口只算有餐食的两天；expected 用库里的真实餐食与训练消耗重算
        expected = []
        for off, cal in ((-3, metrics['target_cal']), (-2, metrics['target_cal'] - 600)):
            expected.append(round(metrics['tdee'] + 120 - cal))
        self.assertEqual(body['deficit_sample_days'], 2, body['deficit_sample_days'])
        for row in body['rows']:
            if row['date'] == self.day(-3):
                self.assertEqual(row['deficit_kcal'], expected[0], row)
            if row['date'] == self.day(-2):
                self.assertEqual(row['deficit_kcal'], expected[1], row)
        self.assertEqual(body['average_deficit_kcal'], round(sum(expected) / 2),
                         '缺口均值把缺记日当成 0 掺进来了：%s' % body['average_deficit_kcal'])
        self.assertEqual(body['deficit_in_band_days'], 1, body['deficit_in_band_days'])
        # 文案里不许出现"摄入 0 / 0 卡"这类把缺记当零的说法。
        # 正则前面带负向环视，免得把"±200 kcal"里的 "0 kcal" 误判成零摄入。
        joined = self.texts(body)
        self.assertNotIn('摄入 0', joined, '缺记被写成零摄入：%s' % joined)
        self.assertNotRegex(joined, r'(?<![\d±])0\s*(?:kcal|卡路里|卡)',
                            '缺记被写成零摄入：%s' % joined)

    # ============================================================ 判据 3
    def test_weekly_single_weight_date_has_no_trend(self):
        """体重只有一个日期：趋势字段是数据不足，界面文案不许出现趋势结论。"""
        target = self.metrics()['target_cal']
        self.seed(meals=[(-3, target)], workouts=[(-3, 20, 100)], weights=[(-3, 158.0)])
        body = self.review().json()
        trend = body['weight_trend']
        self.assertEqual(trend['status'], 'insufficient', trend)
        self.assertIsNone(trend['change_jin'], trend)
        self.assertEqual(trend['distinct_days'], 1, trend)
        self.assertIn('数据不足', trend['text'], trend['text'])
        for conclusion in ('相差', '下降', '上升', '减少', '趋势是'):
            self.assertNotIn(conclusion, trend['text'],
                             '单个称重日期却给了趋势结论：%s' % trend['text'])
        self.assertNotIn('斤', trend['text'], '单个称重日期却给出了斤数变化：%s' % trend['text'])
        self.assertIsNone(body['weight_change_jin'], body['weight_change_jin'])

        # 界面照服务端的 status 分支渲染，不在前端自己算第二条趋势
        source = (ASSETS / 'companion.js').read_text(encoding='utf-8')
        self.assertIn('weight_trend.text', source, '界面没有渲染服务端的趋势文案')
        self.assertIn('weight_trend.status', source, '界面没有按趋势状态分支')
        self.assertIn("weight_trend.status==='ok'", source, '界面把单点记录也渲染成斤数变化')
        self.assertIn('数据不足', source, '界面没有单点记录时的"数据不足"文案')
        self.assertNotIn('weight_change_jin', source, '界面自己另算了一套首末变化')
        for ratio in ("' / '+d.days", "' / ' + d.days", '完成率', '达成率'):
            self.assertNotIn(ratio, source, '界面拿全周天数当分母了：%s' % ratio)

    # ============================================================ 判据 4
    def test_weekly_feedback_is_two_or_three_with_real_basis(self):
        """反馈 2~3 条；每条的依据数字都等于库里算出来的值，且文案里写着这个数。"""
        self.seed_full_week()
        body = self.review().json()
        items = body['feedback']
        self.assertGreaterEqual(len(items), 2, '可执行反馈少于 2 条：%s' % items)
        self.assertLessEqual(len(items), 3, '可执行反馈多于 3 条：%s' % items)

        # 从库里独立重算三个依据口径，不引用被测模块的中间变量
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        try:
            start, end = self.day(-6), self.day(0)
            food = {r['log_date'] for r in c.execute(
                "SELECT DISTINCT log_date FROM food_logs WHERE user_id=? AND log_date BETWEEN ? AND ?",
                (self.signup['id'], start, end))}
            workout = {r['log_date'] for r in c.execute(
                "SELECT DISTINCT log_date FROM workout_logs WHERE user_id=? AND log_date BETWEEN ? AND ?",
                (self.signup['id'], start, end))}
            weight = {r['log_date'] for r in c.execute(
                "SELECT DISTINCT log_date FROM weight_logs WHERE user_id=? AND log_date BETWEEN ? AND ?",
                (self.signup['id'], start, end))}
        finally:
            c.close()
        expected = {'full_record_days': len(food & workout & weight),
                    'deficit_sample_days': len(food),
                    'weight_days': len(weight)}
        seen = set()
        for item in items:
            self.assertIn('text', item, item)
            self.assertIn('basis', item, item)
            metric, value = item['basis']['metric'], item['basis']['value']
            self.assertIn(metric, expected, '依据口径不认识：%s' % item['basis'])
            self.assertEqual(value, expected[metric],
                             '%s 的依据写 %s，库里算出 %s' % (metric, value, expected[metric]))
            self.assertIn(str(value), item['text'],
                          '文案没写出依据数字 %s：%s' % (value, item['text']))
            for word in COMMITMENT_WORDS:
                self.assertNotIn(word, item['text'], '反馈出现确定性承诺：%s' % item['text'])
            seen.add(metric)
        self.assertEqual(seen, set(expected), '三个依据口径没有各出现一次：%s' % seen)

        # 整个响应（含趋势与覆盖说明）都不许出现确定性减重承诺
        dump = json.dumps(body, ensure_ascii=False)
        for word in COMMITMENT_WORDS:
            self.assertNotIn(word, dump, '响应出现确定性承诺词「%s」' % word)
        self.assertNotIn('完成率', dump)
        self.assertNotIn('达成率', dump)

    def test_weekly_sparse_week_says_which_days_exist_without_denominator(self):
        """缺数据时明说记录不足、先看哪几天；不许拿 7 天当分母算完成率。"""
        self.seed(meals=[(-3, 1500)], workouts=[(-3, 20, 100)],
                  weights=[(-5, 159.0), (-3, 158.0), (-1, 157.0)])
        body = self.review().json()
        note = body['coverage_note']
        self.assertIn('记录不足', note, note)
        self.assertIn('先看得到的是这 3 天', note, note)
        self.assertIn(self.day(-3)[5:], note, note)
        self.assertIn(self.day(-1)[5:], note, note)
        self.assertNotIn('/7', note.replace(' ', ''))
        self.assertNotIn('完成率', self.texts(body))
        self.assertEqual(body['full_record_days'], 1, body['full_record_days'])

    def test_weekly_auth_scope_and_window_limits(self):
        """只读接口也要登录；天数只认 7/30；别人的记录一条都不许混进来。"""
        self.assertEqual(self.app.get('/api/weekly/review').status_code, 401)
        self.seed_full_week()
        self.assertEqual(self.review('?days=999').status_code, 400)
        self.assertEqual(self.review('?end=2099-01-01').status_code, 400)
        month = self.review('?days=30')
        self.assertEqual(month.status_code, 200, month.text)
        self.assertEqual(month.json()['days'], 30)
        self.assertEqual(len(month.json()['rows']), 30)
        other = self.app.post('/api/register', json=dict(
            self.app_body, username='weeklyother')).json()
        peer = self.review(token=other['token']).json()
        self.assertEqual(peer['full_record_days'], 0, peer['full_record_days'])
        self.assertEqual(peer['meal_days'], 0, peer['meal_days'])
        self.assertEqual([r['date'] for r in peer['rows'] if r['recorded_kcal'] is not None], [])


if __name__ == '__main__':
    names = [n for n in unittest.defaultTestLoader.getTestCaseNames(WeeklyReview)
             if n.startswith('test_weekly_')]
    if len(sys.argv) > 1:
        names = [n for n in names if any(arg in n for arg in sys.argv[1:])]
    suite = unittest.TestSuite(WeeklyReview(n) for n in names)
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
