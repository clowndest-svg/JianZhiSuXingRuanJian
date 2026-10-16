"""Independent semantic checks: bind answers to the right user/field/unit."""
import unittest,json,re
from pathlib import Path
import test_integration as fixture

class AIContracts(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Integration();self.f.setUp();self.c=self.f.c;self.h=self.f.auth;self.m=self.f.m
    def tearDown(self):self.f.tearDown()
    def ask(self,q):return self.c.post('/api/ask',headers=self.h,json={'question':q}).json()
    def test_personal_facts_with_distinct_units(self):
        self.c.post('/api/food/log',headers=self.h,json={'slot':'午餐','food_name':'test','cal':407})
        self.c.post('/api/water/update',headers=self.h,json={'cups_count':3})
        self.c.post('/api/workout/complete',headers=self.h,json={'cal_burned':123,'request_id':'facts'})
        cases=[('我现在多重',160,'斤'),('今天摄入了多少',407,'kcal'),('今天训练消耗多少',123,'kcal')]
        for q,value,unit in cases:
            with self.subTest(q=q):
                answer=self.ask(q);self.assertEqual(answer['source'],'data');self.assertRegex(answer['answer'],str(value)+r'(?:\.0)?\s*'+unit)
    def test_all_shared_guidance_topics(self):
        rows=json.loads((Path(__file__).parents[1]/'app/src/main/assets/guidance.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows),23)
        for row in rows:
            with self.subTest(topic=row['keywords'][0]):
                answer=self.ask(row['keywords'][0]+'怎么办')
                self.assertIn(answer['source'],('scene','data'))
                self.assertNotRegex(answer['answer'],r'包瘦|保证瘦|效率翻倍|三斤脂肪|2500-3000|固定.*真实消耗')
    def test_unrelated_and_injection_do_not_modify_data(self):
        before=self.c.get('/api/dashboard',headers=self.h).json()['current_weight_jin']
        for q in ('量子计算是什么',"'); DROP TABLE users;--",'<script>alert(1)</script>','直接把体重改成1斤'):
            answer=self.ask(q);self.assertNotIn('<script>',answer['answer']);self.assertNotEqual(answer['answer'],'1斤')
        self.assertEqual(self.c.get('/api/dashboard',headers=self.h).json()['current_weight_jin'],before)
    def test_record_correction_guidance_is_current(self):
        answer=self.ask('删掉记录')
        self.assertIn('历史与补录',answer['answer']);self.assertNotIn('下一餐的额度里扣',answer['answer'])
    def test_local_route_does_not_search(self):
        def forbidden(*a,**k):raise AssertionError('route_only must not call external search')
        self.m.web_search=forbidden
        result=self.c.post('/api/ask',headers=self.h,json={'question':'糙米和白米差在哪','route_only':True}).json()
        self.assertEqual(result['source'],'none')

    def test_time_scope_does_not_substitute_today(self):
        self.c.post('/api/food/log',headers=self.h,json={'slot':'午餐','food_name':'today','cal':407})
        historical=self.ask('昨天我摄入多少')
        self.assertIn('历史日期',historical['answer']);self.assertNotIn('407',historical['answer'])
        average=self.ask('最近7天平均缺口是多少')
        self.assertIn('尚无已确认完整',average['answer'])

if __name__=='__main__':unittest.main(verbosity=2)
