"""Real framework integration checks. Always uses a disposable local database."""
import os,sys,tempfile,importlib.util,unittest,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from PIL import Image

class Integration(unittest.TestCase):
    def setUp(self):
        (ROOT/'_audit_sandbox').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'_audit_sandbox')
        for name in ('DB','UPLOAD','WEB'):
            os.environ['QINGSU_'+name+'_DIR']=str(Path(self.tmp.name)/name)
        spec=importlib.util.spec_from_file_location('review_server',ROOT/'server.py')
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.m._redis_cmd=lambda *a,**k:(False,None)
        self.m.web_search=lambda *a,**k:[]
        self.m.llm_chat=lambda *a,**k:None
        self.c=TestClient(self.m.app)
        self.body=dict(username='owner',password='Review!123',age=30,height=170,weight_jin=160,target_weight_jin=140)
        self.signup=self.c.post('/api/register',json=self.body).json()
        self.auth={'Authorization':'Bearer '+self.signup['token']}
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def test_sessions_and_logout(self):
        token=self.c.post('/api/login',json={'username':'owner','password':'Review!123'}).json()['token']
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).status_code,200)
        self.assertEqual(self.c.post('/api/logout',headers=self.auth).status_code,200)
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).status_code,401)
        self.assertEqual(self.c.get('/api/dashboard',headers={'Authorization':'Bearer '+token}).status_code,200)
    def test_validation(self):
        for path,data in [('/api/food/log',{'slot':'早餐','food_name':'x','cal':-1}),('/api/weight/log',{'weight_jin':-1}),('/api/workout/complete',{'duration_minutes':-1}),('/api/register',dict(self.body,username='',password=''))]:
            with self.subTest(path=path):self.assertEqual(self.c.post(path,headers=self.auth,json=data).status_code,422)
    def test_initial_state_and_share(self):
        d=self.c.get('/api/dashboard',headers=self.auth).json()
        self.assertEqual(d['cycle_day'],1);self.assertEqual(d['consecutive_slacking_days'],0)
        self.assertIn('?k=',d['public_url'])
        self.assertEqual(self.c.get('/api/public/dashboard',params={'username':'owner'}).status_code,404)
        key=d['public_url'].split('?k=')[1]
        self.assertEqual(self.c.get('/api/public/dashboard',params={'username':'owner','k':key}).status_code,200)
    def test_latest_weight_and_checklist(self):
        self.c.post('/api/weight/log',headers=self.auth,json={'weight_jin':150})
        ch=self.c.get('/api/charts',headers=self.auth).json()
        self.assertEqual(ch['weight_history'][-1]['jin'],150)
        self.c.post('/api/checklist',headers=self.auth,json={'state':{'a':True}})
        self.assertTrue(self.c.get('/api/dashboard',headers=self.auth).json()['checklist']['a'])
    def test_idempotency(self):
        for _ in range(2):self.c.post('/api/workout/complete',headers=self.auth,json={'request_id':'same'})
        d=self.c.get('/api/dashboard',headers=self.auth).json()
        self.assertEqual(d['today_burned'],220)
        self.c.post('/api/workout/complete',headers=self.auth,json={'request_id':'different'})
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['today_burned'],440)
    def test_private_knowledge(self):
        self.c.post('/api/ai/record',headers=self.auth,json={'question':'糙米和白米差在哪','answer':'PRIVATE_MARKER'})
        b=self.c.post('/api/register',json=dict(self.body,username='other')).json()
        h={'Authorization':'Bearer '+b['token']}
        self.assertNotIn('PRIVATE_MARKER',self.c.get('/api/ai/context',headers=h).text)
        self.assertNotIn('PRIVATE_MARKER',self.c.post('/api/ask',headers=h,json={'question':'糙米和白米差在哪'}).text)
        self.assertNotEqual(self.m._qkey('黑咖啡有什么优点'),self.m._qkey('黑咖啡有什么风险'))
    def test_images(self):
        fields={'weight_jin':'150','waist_cm':'80'}
        bad=self.c.post('/api/cycle/upgrade',headers=self.auth,data=fields,files={'photo':('bad.html',b'<h1>test</h1>','text/html')})
        self.assertEqual(bad.status_code,400)
        data=io.BytesIO();Image.new('RGB',(24,24)).save(data,format='PNG')
        good=self.c.post('/api/cycle/upgrade',headers=self.auth,data=fields,files={'photo':('good.png',data.getvalue(),'image/png')})
        self.assertEqual(good.status_code,200)
        raw=good.json()['photo_url'];self.assertEqual(self.c.get(raw.split('?')[0]).status_code,404)
        d=self.c.get('/api/dashboard',headers=self.auth).json()
        self.assertEqual(self.c.get(d['latest_cycle']['photo_url']).status_code,200)
        public=self.c.get('/api/public/dashboard',params={'username':'owner','k':self.signup['public_url'].split('?k=')[1]}).json()
        self.assertEqual(public['latest_cycle']['photo_url'],'')
    def test_login_counter(self):
        for _ in range(4):self.c.post('/api/login',json={'username':'owner','password':'bad'})
        self.assertEqual(self.c.post('/api/login',json={'username':'owner','password':'Review!123'}).status_code,200)
        self.c.post('/api/login',json={'username':'owner','password':'bad'})
        self.assertEqual(self.c.post('/api/login',json={'username':'owner','password':'Review!123'}).status_code,200)

    def test_record_correction_and_isolation(self):
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'早餐','food_name':'鸡蛋','cal':300})
        record=self.c.get('/api/dashboard',headers=self.auth).json()['today_meals'][0]['id']
        other=self.c.post('/api/register',json=dict(self.body,username='other')).json()
        self.assertEqual(self.c.post(f'/api/records/food/{record}/delete',headers={'Authorization':'Bearer '+other['token']}).status_code,404)
        self.assertEqual(self.c.post(f'/api/records/food/{record}/update',headers=self.auth,json={'cal':200}).status_code,200)
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['today_consumed'],200)
        self.assertEqual(self.c.post(f'/api/records/food/{record}/delete',headers=self.auth).status_code,200)
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['today_consumed'],0)

    def test_historical_metrics_and_day_mode(self):
        from datetime import date,timedelta
        yesterday=(date.today()-timedelta(days=1)).isoformat()
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'早餐','food_name':'鸡蛋','cal':500})
        conn=self.m.get_db();conn.execute('UPDATE food_logs SET log_date=?',(yesterday,));conn.execute('UPDATE daily_metrics SET log_date=?',(yesterday,));conn.commit();conn.close()
        before=self.c.get('/api/charts',headers=self.auth).json()['deficit_history'][-2]['deficit']
        self.c.post('/api/profile/update',headers=self.auth,json={'height':190})
        after=self.c.get('/api/charts',headers=self.auth).json()['deficit_history'][-2]['deficit']
        self.assertEqual(before,after)
        self.c.post('/api/profile/mode',headers=self.auth,json={'day_mode':'workout'})
        conn=self.m.get_db();conn.execute('UPDATE daily_modes SET log_date=?',(yesterday,));conn.commit();conn.close()
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['day_mode'],'rest')

    def test_share_scope_expiry_and_rotation(self):
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'午餐','food_name':'private meal','cal':500})
        old_key=self.signup['public_url'].split('?k=')[1]
        result=self.c.post('/api/share/settings',headers=self.auth,json={'enabled':True,'days':1,'scope':{'weight':False,'profile':False,'meals':False,'workout':True,'photos':False},'rotate':True}).json()
        self.assertEqual(self.c.get('/api/public/dashboard',params={'username':'owner','k':old_key}).status_code,404)
        key=result['public_url'].split('?k=')[1]
        public=self.c.get('/api/public/dashboard',params={'username':'owner','k':key}).json()
        self.assertEqual(public['today_meals'],[]);self.assertIsNone(public['current_weight_jin']);self.assertNotIn('age',public['profile'])
        charts=self.c.get('/api/public/charts',params={'username':'owner','k':key}).json()
        self.assertEqual(charts['weight_history'],[]);self.assertEqual(charts['deficit_history'],[])
        conn=self.m.get_db();conn.execute('UPDATE share_settings SET expires_at=1');conn.commit();conn.close()
        self.assertEqual(self.c.get('/api/public/dashboard',params={'username':'owner','k':key}).status_code,404)

    def test_completion_and_backfill(self):
        from datetime import date,timedelta
        today=date.today().isoformat()
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'午餐','food_name':'鸡蛋','cal':300})
        self.c.post('/api/day/complete',headers=self.auth,json={'log_date':today,'complete':True})
        self.assertEqual(self.c.get('/api/charts',headers=self.auth).json()['deficit_history'][-1]['record_status'],'complete')
        body={'kind':'food','log_date':today,'food_name':'牛奶','cal':100,'request_id':'backfill-test'}
        for _ in range(2):self.assertEqual(self.c.post('/api/records/backfill',headers=self.auth,json=body).status_code,200)
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['today_consumed'],400)
        self.assertEqual(self.c.get('/api/charts',headers=self.auth).json()['deficit_history'][-1]['record_status'],'partial')
        body['log_date']=(date.today()+timedelta(days=1)).isoformat();body['request_id']='future'
        self.assertEqual(self.c.post('/api/records/backfill',headers=self.auth,json=body).status_code,400)

    def test_history_pagination_owner(self):
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'午餐','food_name':'owned','cal':300})
        other=self.c.post('/api/register',json=dict(self.body,username='other')).json()
        rows=self.c.get('/api/records?kind=food',headers={'Authorization':'Bearer '+other['token']}).json()['rows']
        self.assertEqual(rows,[])
        self.assertEqual(self.c.get('/api/records?kind=food&limit=999',headers=self.auth).status_code,400)
        self.assertEqual(self.c.get('/api/records?kind=users',headers=self.auth).status_code,400)

    def test_daily_zero_is_not_missing(self):
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'加餐','food_name':'manual zero','cal':0})
        bar=self.c.get('/api/charts',headers=self.auth).json()['deficit_history'][-1]
        self.assertTrue(bar['has_records']);self.assertEqual(bar['record_status'],'partial')

    def test_sources_macros_and_portions(self):
        one=self.m.parse_food_nutrition('水煮蛋')['cal']
        self.assertEqual(self.m.parse_food_nutrition('两个水煮蛋')['cal'],one*2)
        self.assertAlmostEqual(self.m.parse_food_nutrition('半份水煮蛋')['cal'],round(one/2))
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'午餐','food_name':'水煮蛋'})
        row=self.c.get('/api/dashboard',headers=self.auth).json()['today_meals'][0]
        self.assertIn('nutrition_kb',row['source'])

    def test_share_allowlist_excludes_indirect_private_fields(self):
        key=self.signup['public_url'].split('?k=')[1]
        self.c.post('/api/share/settings',headers=self.auth,json={'scope':{k:False for k in ('weight','profile','meals','workout','photos')}})
        public=self.c.get('/api/public/dashboard',params={'username':'owner','k':key}).json()
        for key in ('water_target_ml','budget_cal','takeout_stats','consecutive_slacking_days','last_workout_cal','streak_days','checklist','photo_due'):
            self.assertNotIn(key,public)
        self.assertEqual(public['profile'],{'weight_jin':None,'target_weight_jin':None})

    def test_backdated_weight_does_not_replace_latest(self):
        from datetime import date,timedelta
        yesterday=(date.today()-timedelta(days=1)).isoformat()
        c=self.m.get_db();c.execute('UPDATE users SET created_at=?',(yesterday+' 00:00:00',));c.commit();c.close()
        self.c.post('/api/weight/log',headers=self.auth,json={'weight_jin':151})
        response=self.c.post('/api/records/backfill',headers=self.auth,json={'kind':'weight','log_date':yesterday,'weight_jin':180,'request_id':'backdated-weight'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.c.get('/api/dashboard',headers=self.auth).json()['current_weight_jin'],151)

    def test_csv_schema_unknown_macros_and_formula_escape(self):
        import csv
        self.c.post('/api/food/log',headers=self.auth,json={'slot':'午餐','food_name':'test','cal':300})
        self.c.post('/api/workout/complete',headers=self.auth,json={'plan_name':'=1+1','request_id':'csv'})
        result=self.c.get('/api/export.csv',headers=self.auth)
        rows=list(csv.reader(io.StringIO(result.text.lstrip('\ufeff'))))
        self.assertTrue(all(len(r)==5 for r in rows));self.assertIn('宏量未知',result.text)
        self.assertIn("'=1+1",result.text)

    def test_corrupt_profile_is_validation_error(self):
        c=self.m.get_db();c.execute('UPDATE profiles SET age=NULL');c.commit();c.close()
        self.assertEqual(self.c.post('/api/profile/update',headers=self.auth,json={'scene':'home'}).status_code,400)

    def test_public_photo_revocation_and_delete(self):
        image=io.BytesIO();Image.new('RGB',(20,20)).save(image,format='PNG')
        self.c.post('/api/cycle/upgrade',headers=self.auth,data={'weight_jin':150,'waist_cm':80},files={'photo':('fixture.png',image.getvalue(),'image/png')})
        key=self.signup['public_url'].split('?k=')[1]
        self.c.post('/api/share/settings',headers=self.auth,json={'scope':{'photos':True}})
        data=self.c.get('/api/public/dashboard',params={'username':'owner','k':key}).json()
        photo=data['latest_cycle']['photo_url'];self.assertEqual(self.c.get(photo).status_code,200)
        self.c.post('/api/share/settings',headers=self.auth,json={'scope':{'photos':False}})
        self.assertEqual(self.c.get(photo).status_code,404)
        owned=self.c.get('/api/dashboard',headers=self.auth).json()['latest_cycle']['photo_url']
        self.assertEqual(self.c.post('/api/photo/delete',headers=self.auth).status_code,200)
        self.assertEqual(self.c.get(owned).status_code,404)

    def test_special_population_budget_boundary(self):
        self.assertEqual(self.c.post('/api/register',json=dict(self.body,username='excluded',special_population=True)).status_code,400)

    def test_concurrent_registration_and_cycle_numbers(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            registrations=list(pool.map(lambda _:self.c.post('/api/register',json=dict(self.body,username='race')).status_code,range(2)))
        self.assertEqual(registrations.count(200),1);self.assertTrue(all(s in (200,400,409) for s in registrations))
        with ThreadPoolExecutor(max_workers=2) as pool:
            cycles=list(pool.map(lambda _:self.c.post('/api/cycle/measure',headers=self.auth,data={'weight_jin':150,'waist_cm':80}),range(2)))
        self.assertTrue(all(r.status_code==200 for r in cycles));self.assertEqual(len({r.json()['cycle_num'] for r in cycles}),2)

if __name__=='__main__':unittest.main(verbosity=2)
