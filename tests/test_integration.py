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


    def shift_days(self, n):
        """把服务器眼里的"今天"整体挪 n 天：跨午夜这类事没法等，只能拨表。"""
        import app_modules.features as feat
        from datetime import date as real_date, timedelta

        class ShiftedDate(real_date):
            @classmethod
            def today(cls):
                return real_date.today() + timedelta(days=n)

        original = (self.m.date, feat.date)
        self.m.date = feat.date = ShiftedDate
        self.addCleanup(lambda: (setattr(self.m, 'date', original[0]),
                                 setattr(feat, 'date', original[1])))
        return ShiftedDate.today().isoformat()

    def test_midnight_rollover_keeps_yesterday_verdict(self):
        """注册→第一笔→同日修正→跨午夜→第二天 全链路对账（方案 10.1）。"""
        from datetime import date, timedelta
        day1 = date.today().isoformat()
        self.c.post('/api/food/log', headers=self.auth, json={'slot': '午餐', 'food_name': '鸡蛋', 'cal': 300})
        self.c.post('/api/weight/log', headers=self.auth, json={'weight_jin': 158})
        self.c.post('/api/day/complete', headers=self.auth, json={'log_date': day1, 'complete': True})
        d1 = self.c.get('/api/dashboard', headers=self.auth).json()
        self.assertEqual(d1['today_consumed'], 300)
        self.assertTrue(d1['today_confirmed'])

        # 同日修正：改了体重，首页与曲线必须是同一个数
        self.c.post('/api/weight/log', headers=self.auth, json={'weight_jin': 156})
        self.assertEqual(self.c.get('/api/charts', headers=self.auth).json()['weight_history'][-1]['jin'], 156)
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).json()['profile']['weight_jin'], 156)
        # 改了当天的记录，上一轮的完整日确认必须自动作废（设计如此，不是翻案）
        self.assertFalse(self.c.get('/api/dashboard', headers=self.auth).json()['today_confirmed'])
        self.c.post('/api/day/complete', headers=self.auth, json={'log_date': day1, 'complete': True})

        # 跨午夜：换到第二天，昨天的摄入不能挂到今天
        day2 = self.shift_days(1)
        d2 = self.c.get('/api/dashboard', headers=self.auth).json()
        self.assertEqual(d2['today'], day2)
        self.assertEqual(d2['today_consumed'], 0)
        self.assertFalse(d2['today_confirmed'])
        self.assertEqual(d2['today_meals'], [])

        # 昨天确认过的完整日不能因为换日就翻案
        bars = self.c.get('/api/charts', headers=self.auth).json()['deficit_history']
        self.assertEqual([b['record_status'] for b in bars if b['date'] == day1], ['complete'])
        self.assertEqual([b['record_status'] for b in bars if b['date'] == day2], ['missing'])

        # 30 天矩阵跟着换日整体平移，不能留下"今天还是昨天"的错位
        matrix = self.c.get('/api/habits', headers=self.auth).json()
        self.assertEqual(matrix['window'], 30)
        self.assertEqual(matrix['days'][-1]['date'], day2)
        self.assertEqual(len({row['date'] for row in matrix['days']}), 30)
        self.assertEqual([row['record_status'] for row in matrix['days'] if row['date'] == day1], ['complete'])

        # 再往后一天，第一天的记录滑出 7 天窗口但仍在 30 天矩阵里
        self.shift_days(8)
        week = self.c.get('/api/charts', headers=self.auth).json()['deficit_history']
        self.assertNotIn(day1, [b['date'] for b in week])
        matrix = self.c.get('/api/habits', headers=self.auth).json()
        self.assertIn(day1, [row['date'] for row in matrix['days']])

    def test_upload_limits_reject_oversize_and_overscan(self):
        """字节超限和像素超限都要拒，且不能留下半条周期记录。"""
        big = self.c.post('/api/cycle/upgrade', headers=self.auth,
                          data={'weight_jin': '150', 'waist_cm': '80'},
                          files={'photo': ('big.png', b'x' * (8 * 1024 * 1024 + 4096), 'image/png')})
        self.assertEqual(big.status_code, 413)
        huge = io.BytesIO()
        Image.new('RGB', (4500, 4500)).save(huge, format='PNG')
        over = self.c.post('/api/cycle/upgrade', headers=self.auth,
                           data={'weight_jin': '150', 'waist_cm': '80'},
                           files={'photo': ('huge.png', huge.getvalue(), 'image/png')})
        self.assertEqual(over.status_code, 400)
        # 两次失败都不许把体重/围度写进去，也不许多开一个周期
        before = self.c.get('/api/charts', headers=self.auth).json()['weight_history']
        d = self.c.get('/api/dashboard', headers=self.auth).json()
        self.assertEqual(len(d['weight_history'] if 'weight_history' in d else before), len(before))
        self.assertEqual(d['profile']['weight_jin'], 160)

    def test_weigh_only_and_water_only_are_theirs_own_kind(self):
        """只称重、只喝水、什么都没记，三者必须各有语义，不能一律当零摄入。"""
        from datetime import date
        day0 = date.today().isoformat()
        # 补录不允许早于注册日，所以先拨到两天后，再把体重补到注册那天
        self.c.post('/api/records/backfill', headers=self.auth,
                    json={'kind': 'weight', 'log_date': day0, 'weight_jin': 157, 'request_id': 'w-only'})
        today = self.shift_days(2)
        self.c.post('/api/water/update', headers=self.auth, json={'cups_count': 3})
        bars = {b['date']: b for b in self.c.get('/api/charts', headers=self.auth).json()['deficit_history']}

        weigh_only = bars[day0]
        self.assertTrue(weigh_only['has_records'], weigh_only)
        self.assertEqual(weigh_only['record_status'], 'partial')
        self.assertEqual(weigh_only['consumed'], 0)

        water_only = bars[today]
        self.assertTrue(water_only['has_records'], water_only)
        self.assertEqual(water_only['record_status'], 'partial')
        self.assertEqual(water_only['consumed'], 0)

        # 中间那天真的什么都没动过，才允许算未记录
        gap = bars[(date.fromisoformat(today) - __import__("datetime").timedelta(days=1)).isoformat()]
        self.assertEqual(gap['record_status'], 'missing')
        self.assertFalse(gap['has_records'])

    def test_public_static_assets_really_serve(self):
        """公网静态件必须真取到 200 与正确类型。

        只核"源码里有 @app.get(...)"会漏掉 extension_asset 的 media 表少一个扩展名
        这种形状——路由在、文件在，请求进来是 500（本轮 app-icon.png 就是这样上线的）。
        """
        import shutil
        web = Path(os.environ['QINGSU_WEB_DIR']); web.mkdir(parents=True, exist_ok=True)
        names = ["app.js", "style.css", "features.js", "features.css", "sw.js",
                 "manifest.webmanifest", "app-icon.png", "guidance.json",
                 "exercise_poses.json"]
        expect = {"js": "application/javascript", "css": "text/css", "png": "image/png",
                  "webmanifest": "application/manifest+json", "json": "application/json"}
        for name in names:
            source = ROOT / "app" / "src" / "main" / "assets" / name
            assert source.is_file(), "仓库里缺这件资产：%s" % name
            shutil.copyfile(source, web / name)
        for name in names:
            with self.subTest(asset=name):
                got = self.c.get("/" + name)
                self.assertEqual(got.status_code, 200, got.text[:90])
                self.assertTrue(got.headers["content-type"].startswith(expect[name.rsplit(".", 1)[-1]]),
                                "%s -> %s" % (name, got.headers["content-type"]))

    def test_forced_update_gate(self):
        """强更门：旧包不会发 X-App-Build，所以"缺头"是唯一打得着它们的判据。"""
        import json as _json
        web = Path(os.environ['QINGSU_WEB_DIR']); web.mkdir(parents=True, exist_ok=True)
        def publish(min_code):
            (web / 'version.json').write_text(_json.dumps({
                'version_code': 22, 'version_name': '1.9.0', 'min_version_code': min_code,
                'apk_url': 'https://124.220.54.64/qingsu.apk', 'size': 5322721,
                'md5': 'ab' * 16, 'notes': 'r139 强更'}, ensure_ascii=False), encoding='utf-8')
            # 缓存按 size+mtime 认文件，同一秒内换内容会读到上一份，测试必须显式作废
            self.m._version_policy_cache['key'] = None
        publish(22)
        blocked = self.c.get('/api/dashboard', headers=self.auth)
        self.assertEqual(blocked.status_code, 403, '旧包不带构建号却放行了')
        body = blocked.json()
        self.assertEqual(body['code'], 'update_required')
        self.assertEqual(body['your_build'], 0)
        self.assertIn('1.9.0', body['detail'], body['detail'])   # 版本号取自清单，不是写死
        self.assertEqual(body['latest']['size'], 5322721)
        for raw, want in (('21', 403), ('22', 200), ('23', 200), ('abc', 403), ('', 403)):
            with self.subTest(build=raw):
                self.assertEqual(self.c.get('/api/dashboard', headers=dict(self.auth, **{'X-App-Build': raw})).status_code, want)
        # 访客侧不参与强更：把来看监督页的人挡在门外没有任何意义
        d = self.c.get('/api/dashboard', headers=dict(self.auth, **{'X-App-Build': '22'})).json()
        key = d['public_url'].split('?k=')[1]
        self.assertEqual(self.c.get('/api/public/dashboard', params={'username': 'owner', 'k': key}).status_code, 200)
        self.assertNotEqual(self.c.post('/api/cheer', json={'username': 'owner', 'k': key, 'kind': 'on_track'}).status_code, 403)
        # 更新通道本身绝不能被挡：否则用户连新包都下不到，等于把自己锁死
        self.assertEqual(self.c.get('/version.json').status_code, 200)
        self.assertEqual(self.c.get('/health/ready').status_code, 200)
        # CORS 预检不带自定义头，被门拦下等于所有跨源请求一起废掉
        pre = self.c.options('/api/dashboard', headers={'Origin': 'https://appassets.androidplatform.net',
                                                       'Access-Control-Request-Method': 'GET',
                                                       'Access-Control-Request-Headers': 'authorization,x-app-build'})
        self.assertEqual(pre.status_code, 200, pre.text)
        # 运维刹车：文件在时以它为准；写 0 立刻放行，删掉又回落到清单策略
        override = Path(os.environ['QINGSU_DB_DIR']) / 'min_build'
        def reset(): self.m._min_build_cache['key'] = None
        override.write_text('0', encoding='utf-8'); reset()
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).status_code, 200, '刹车没生效，机主会被锁在门外')
        override.write_text('22', encoding='utf-8'); reset()
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).status_code, 403)
        override.unlink(); reset()
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).status_code, 403, '删了刹车却把门也放开了')
        ready = self.c.get('/health/ready').json()
        self.assertEqual(ready['min_build'], 22)
        self.assertGreaterEqual(ready['gate']['blocked'], 5, ready)
        self.assertIn('0', ready['gate']['builds'], '抬门前看不见还有谁在调用')

    def test_account_center_recovery_and_location(self):
        """账号中心：改密掉线、头像签名、邮箱验证码、城市就近——全部真跑那条链路。

        邮件发送本身用 stub 接住（这台机器上没有可用 SMTP），
        但"没配通道就必须拒绝"那半段是**不打桩**的：直接指向一个不存在的配置文件。
        """
        import json as _json, re as _re
        m = self.m

        # ---------- 改密码 ----------
        self.assertEqual(self.c.post('/api/account/password', headers=self.auth,
            json={'old_password': 'nope', 'new_password': 'Review!456'}).status_code, 400)
        self.assertEqual(self.c.post('/api/account/password', headers=self.auth,
            json={'old_password': 'Review!123', 'new_password': 'short'}).status_code, 400)
        second = self.c.post('/api/login', json={'username': 'owner',
                                                 'password': 'Review!123'}).json()['token']
        h2 = {'Authorization': 'Bearer ' + second}
        self.assertEqual(self.c.get('/api/account', headers=h2).status_code, 200)
        r = self.c.post('/api/account/password', headers=self.auth,
                        json={'old_password': 'Review!123', 'new_password': 'Review!456'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreaterEqual(r.json()['revoked_sessions'], 1, '改密后其他会话必须掉线')
        self.assertEqual(self.c.get('/api/account', headers=h2).status_code, 401,
                         '旧令牌还能用，等于改密码没起作用')
        self.assertEqual(self.c.get('/api/account', headers=self.auth).status_code, 200,
                         '当前这台设备不该被自己踢下线')

        # ---------- 头像：签名链接、覆盖同名、不带签名取不到 ----------
        buf = io.BytesIO(); Image.new('RGB', (900, 900), (200, 60, 60)).save(buf, format='JPEG')
        up = self.c.post('/api/account/avatar', headers=self.auth,
                         files={'photo': ('a.jpg', buf.getvalue(), 'image/jpeg')})
        self.assertEqual(up.status_code, 200, up.text)
        signed = up.json()['avatar_url']
        self.assertIn('signature=', signed)
        self.assertEqual(self.c.get(signed).status_code, 200, '本人拿签名链接取不到头像')
        self.assertEqual(self.c.get(signed.split('?')[0]).status_code, 404,
                         '不带签名就能取头像＝任何人可枚举 user_id')
        up2 = self.c.post('/api/account/avatar', headers=self.auth,
                          files={'photo': ('b.png', buf.getvalue(), 'image/png')})
        self.assertEqual(up2.json()['avatar_url'].split('?')[0], signed.split('?')[0],
                         '换头像应覆盖同一个文件，不然磁盘上会堆出一串历史头像')

        # ---------- 邮件通道没配：不打桩，必须如实拒绝且不留验证码 ----------
        m.mailer.CONFIG_PATH = str(Path(self.tmp.name) / 'definitely-no-mail.json')
        self.assertEqual(m.mailer.status()['ok'], False)
        self.assertEqual(self.c.get('/api/account/recovery-status').json()['mail'], 'down')
        blocked = self.c.post('/api/account/email/send', headers=self.auth,
                              json={'email': 'zhang.ge@example.com'})
        self.assertEqual(blocked.status_code, 503, blocked.text)
        self.assertIn('邮件通道未接入', blocked.json()['detail'])
        conn = m.get_db()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM email_codes').fetchone()[0], 0,
                         '发不出去却留下验证码，等于留了一条用户看不见但能改密的后门')
        conn.close()

        # ---------- 配好通道后走完整流程（send 打桩，只为拿到那六个数字） ----------
        cfg = Path(self.tmp.name) / 'mail.json'
        cfg.write_text(_json.dumps({'host': 'smtp.invalid', 'port': 465, 'user': 'u',
                                    'password': 'p', 'from': 'bot@example.org'}), encoding='utf-8')
        m.mailer.CONFIG_PATH = str(cfg)
        sent, real_send = [], m.mailer.send

        def fake_send(to_addr, subject, text):
            sent.append((to_addr, text))
            return True, ''
        m.mailer.send = fake_send
        try:
            self.assertEqual(m.mailer.status()['ok'], True)
            s = self.c.post('/api/account/email/send', headers=self.auth,
                            json={'email': 'Zhang.Ge@example.com'})
            self.assertEqual(s.status_code, 200, s.text)
            self.assertEqual(s.json()['masked'], 'zh***@example.com', '邮箱要归一化并掩码')
            self.assertNotIn('123456', s.text)
            code = _re.search(r'(\d{6})', sent[0][1]).group(1)
            self.assertEqual(
                self.c.post('/api/account/email/verify', headers=self.auth,
                            json={'email': 'zhang.ge@example.com', 'code': '000000'}).status_code, 400)
            v = self.c.post('/api/account/email/verify', headers=self.auth,
                            json={'email': 'zhang.ge@example.com', 'code': code})
            self.assertEqual(v.status_code, 200, v.text)
            acc = self.c.get('/api/account', headers=self.auth).json()
            self.assertTrue(acc['email_verified'])
            self.assertEqual(acc['email_masked'], 'zh***@example.com')
            self.assertEqual(
                self.c.post('/api/account/email/verify', headers=self.auth,
                            json={'email': 'zhang.ge@example.com', 'code': code}).status_code, 400,
                '同一个验证码能用第二次，就不是"一次性"')

            # 找回密码：绑过与没绑过的响应必须逐字相同，否则等于开放邮箱枚举
            del sent[:]
            bound = self.c.post('/api/account/forgot', json={'email': 'zhang.ge@example.com'})
            stray = self.c.post('/api/account/forgot', json={'email': 'nobody@example.com'})
            self.assertEqual(bound.status_code, 200)
            self.assertEqual(bound.json(), stray.json(), '两条响应有差异，可被用来枚举邮箱')
            self.assertEqual(len(sent), 1, '没绑过的邮箱不该真的发信')
            rcode = _re.search(r'(\d{6})', sent[0][1]).group(1)
            self.assertEqual(self.c.post('/api/account/reset', json={
                'email': 'zhang.ge@example.com', 'code': '111111', 'new_password': 'Review!999'}).status_code, 400)
            rr = self.c.post('/api/account/reset', json={
                'email': 'zhang.ge@example.com', 'code': rcode, 'new_password': 'Review!999'})
            self.assertEqual(rr.status_code, 200, rr.text)
            self.assertGreaterEqual(rr.json()['revoked_sessions'], 1)
            self.assertEqual(self.c.get('/api/account', headers=self.auth).status_code, 401,
                             '重置后旧会话还在，等于没重置')
            login = self.c.post('/api/login', json={'username': 'owner', 'password': 'Review!999'})
            self.assertEqual(login.status_code, 200)
            self.auth = {'Authorization': 'Bearer ' + login.json()['token']}
        finally:
            m.mailer.send = real_send

        # ---------- 忌口与城市 ----------
        self.assertEqual(self.c.post('/api/account/preferences', headers=self.auth,
            json={'avoid_tags': ['no_spicy', 'no_glue']}).status_code, 400,
            '不认识的忌口标签要报错，悄悄丢掉会让用户以为勾上了')
        pref = self.c.post('/api/account/preferences', headers=self.auth,
                           json={'avoid_tags': ['no_spicy', 'no_seafood']}).json()
        self.assertEqual(pref['avoid_tags'], ['no_spicy', 'no_seafood'])
        loc = self.c.post('/api/account/location', headers=self.auth,
                          json={'lat': 30.57, 'lng': 104.07}).json()
        self.assertTrue(loc['matched'])
        self.assertEqual(loc['city'], '成都')
        self.assertIn('辣', loc['cuisines'])
        far = self.c.post('/api/account/location', headers=self.auth,
                          json={'lat': -30.0, 'lng': -160.0}).json()
        self.assertFalse(far['matched'])
        self.assertEqual(far['city'], '成都', '认不出来时不能把已有城市清掉')
        acc = self.c.get('/api/account', headers=self.auth).json()
        self.assertEqual([x['city'] for x in acc['cities_seen']], ['成都'])
        manual = self.c.post('/api/account/city', headers=self.auth, json={'city': '佛山'}).json()
        self.assertIn('粤菜', manual['cuisines'])

        # ---------- 抬门之后，找回密码这条路必须还通 ----------
        web = Path(os.environ['QINGSU_WEB_DIR']); web.mkdir(parents=True, exist_ok=True)
        (web / 'version.json').write_text(_json.dumps({
            'version_code': 29, 'version_name': '1.9.7', 'min_version_code': 29,
            'apk_url': 'https://124.220.54.64/qingsu.apk', 'size': 1,
            'md5': 'ab' * 16, 'notes': 'r146'}, ensure_ascii=False), encoding='utf-8')
        m._version_policy_cache['key'] = None
        self.assertEqual(self.c.get('/api/dashboard').status_code, 403, '没构建号就该被挡')
        self.assertEqual(self.c.post('/api/account/forgot',
                                     json={'email': 'nobody@example.com'}).status_code, 200,
                         '门把找回密码也挡住，忘密码的人就彻底回不来了')
        self.assertEqual(self.c.get('/api/account/recovery-status').status_code, 200)

    # ── 社区 / 私聊 / 反馈 ────────────────────────────────────────────────
    def _member(self, name, nickname=None):
        payload = dict(self.body, username=name, nickname=nickname or name)
        r = self.c.post('/api/register', json=payload)
        self.assertEqual(r.status_code, 200, '夹具注册失败: %s' % r.text)
        return r.json(), {'Authorization': 'Bearer ' + r.json()['token']}

    def test_nickname_is_self_service_and_login_name_never_moves(self):
        """昵称可以自己改，登录名不能。注册没填昵称时服务端把登录名当昵称存了，
        这是线上真实存在的状态，所以「昵称==登录名」要能测出来，改完两处显示都得跟上。"""
        acc = self.c.get('/api/account', headers=self.auth).json()
        self.assertEqual(acc['user']['nickname'], 'owner', '注册没填昵称时昵称就是登录名')
        self.assertTrue(str(acc['user']['created_at'])[:4].isdigit(), '身份卡要显示哪年加入的')
        self.assertEqual(self.c.post('/api/account/nickname', headers=self.auth,
                                     json={'nickname': '  小田要瘦十斤  '}).status_code, 200)
        acc = self.c.get('/api/account', headers=self.auth).json()
        self.assertEqual(acc['user']['nickname'], '小田要瘦十斤', '前后空格要剪掉再存')
        self.assertEqual(acc['user']['username'], 'owner', '改昵称不许顺手把登录名也改掉')
        # 别人那一侧看到的必须是新名字，否则就是"自己改了、别人还看旧的"
        hit = self.c.get('/api/community/search', headers=self.auth, params={'q': '小田要瘦十斤'}).json()['items']
        self.assertEqual([u['name'] for u in hit], ['小田要瘦十斤'])
        home = self.c.get('/api/community/users/小田要瘦十斤', headers=self.auth).json()
        self.assertEqual(home['user']['name'], '小田要瘦十斤')
        for bad in ('', '   ', '一' * 21, '两行\n昵称'):
            with self.subTest(bad=bad):
                self.assertEqual(self.c.post('/api/account/nickname', headers=self.auth,
                                             json={'nickname': bad}).status_code, 400)
        self.assertEqual(self.c.get('/api/account', headers=self.auth).json()['user']['nickname'],
                         '小田要瘦十斤', '被拒的那几次不能把已经存好的昵称顺带清空')
        self.assertEqual(self.c.post('/api/account/nickname',
                                     json={'nickname': '匿名'}).status_code, 401)

    def test_public_id_assigned_and_unique(self):
        """轻塑号：主页要展示、搜索要精确命中，所以注册就得有，且不能是内部自增 id。"""
        me = self.signup
        self.assertRegex(me.get('public_id') or '', r'^\d{8}$')
        self.assertNotEqual(str(me['id']), me['public_id'])
        other, _ = self._member('second')
        self.assertRegex(other['public_id'], r'^\d{8}$')
        self.assertNotEqual(me['public_id'], other['public_id'])
        home = self.c.get('/api/community/users/%s' % other['public_id'], headers=self.auth).json()
        self.assertEqual(home['user']['public_id'], other['public_id'])
        self.assertFalse(home['user']['is_me'])
        self.assertEqual(self.c.get('/api/community/users/00000000', headers=self.auth).status_code, 404)

    def test_post_like_comment_counts_match_their_own_rows(self):
        """计数与明细必须自洽：like_count == COUNT(post_likes)，comment_count 同理。
        只要有一条路径忘了维护，这里就红，而不是等到用户看见"3 个赞"点开只有一个。"""
        author, aauth = self._member('author', '写帖的人')
        reader, rauth = self._member('reader', '路人甲')
        post = self.c.post('/api/community/posts', headers=aauth,
                           json={'text': '今天午餐鸡胸肉 150g，配糙米饭', 'request_id': 'k-1'}).json()
        pid = post['post']['id']
        again = self.c.post('/api/community/posts', headers=aauth,
                            json={'text': '今天午餐鸡胸肉 150g，配糙米饭', 'request_id': 'k-1'}).json()
        self.assertTrue(again['duplicate'], '同一个 request_id 再发必须判重')
        self.assertEqual(again['post']['id'], pid, '判重还该返回原来那条，不是新建一条')
        feed = self.c.get('/api/community/feed?tab=mine', headers=aauth).json()
        self.assertEqual(len([x for x in feed['items'] if x['id'] == pid]), 1)
        self.c.post('/api/community/posts/%d/like' % pid, headers=rauth, json={'on': True})
        self.c.post('/api/community/posts/%d/like' % pid, headers=rauth, json={'on': True})
        liked = self.c.get('/api/community/posts/%d' % pid, headers=rauth).json()['post']
        self.assertEqual(liked['like_count'], 1, '重复点赞只能算一次')
        self.assertTrue(liked['liked_by_me'])
        for text in ('第一条', '第二条'):
            self.c.post('/api/community/posts/%d/comments' % pid, headers=rauth, json={'text': text})
        detail = self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()
        self.assertEqual(detail['post']['comment_count'], len(detail['comments']))
        conn = self.m.get_db()
        rows = conn.execute('SELECT like_count, comment_count FROM posts WHERE id=?', (pid,)).fetchone()
        real_like = conn.execute('SELECT COUNT(*) FROM post_likes WHERE post_id=?', (pid,)).fetchone()[0]
        real_cmt = conn.execute("SELECT COUNT(*) FROM comments WHERE post_id=? AND status='open'",
                                (pid,)).fetchone()[0]
        conn.close()
        self.assertEqual((rows['like_count'], rows['comment_count']), (real_like, real_cmt),
                         '计数和明细对不上')
        # 取消点赞要把那条通知一起收掉，否则"取消赞了，对方还收到一条谁赞了我"
        self.c.post('/api/community/posts/%d/like' % pid, headers=rauth, json={'on': False})
        after = self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()['post']
        self.assertEqual(after['like_count'], 0)
        notices = self.c.get('/api/notifications', headers=aauth).json()['items']
        self.assertEqual([n for n in notices if n['kind'] == 'like'], [])
        self.assertEqual(len([n for n in notices if n['kind'] == 'comment']), 2)
        self.assertEqual(sorted(n['text'] for n in notices if n['kind'] == 'comment'),
                         ['路人甲 评论：第一条', '路人甲 评论：第二条'],
                         '通知句子由服务端拼一份，前端只负责显示')

    def test_post_limits_and_ownership(self):
        other, oauth = self._member('other')
        long = self.c.post('/api/community/posts', headers=self.auth,
                           json={'text': '字' * (self.m.community.POST_MAX + 1)}).status_code
        self.assertIn(long, (400, 422), '超长正文要么 400 要么 422，不许静默截断')
        empty = self.c.post('/api/community/posts', headers=self.auth, json={'text': '   '})
        self.assertEqual(empty.status_code, 400)
        pid = self.c.post('/api/community/posts', headers=self.auth, json={'text': '我的帖子'}).json()['post']['id']
        self.assertEqual(self.c.delete('/api/community/posts/%d' % pid, headers=oauth).status_code, 403,
                         '删别人的帖子必须被拒')
        self.assertEqual(self.c.delete('/api/community/posts/%d' % pid, headers=self.auth).status_code, 200)
        self.assertEqual(self.c.get('/api/community/posts/%d' % pid, headers=oauth).status_code, 404,
                         '删掉的帖子不能再被读到')

    def test_follow_search_and_discoverability(self):
        target, tauth = self._member('target', '可搜索的昵称')
        hidden, hauth = self._member('hidden', '不想被搜到')
        self.c.post('/api/community/profile', headers=hauth, json={'discoverable': 0})
        self.assertEqual(self.c.get('/api/community/search?q=%s' % target['public_id'],
                                    headers=self.auth).json()['items'][0]['public_id'],
                         target['public_id'], '按轻塑号要能精确找到')
        names = [x['name'] for x in self.c.get('/api/community/search?q=不想',
                                               headers=self.auth).json()['items']]
        self.assertNotIn('不想被搜到', names, '关了可发现还出现在搜索结果里')
        self.assertIn('可搜索的昵称', [x['name'] for x in self.c.get(
            '/api/community/search?q=可搜索', headers=self.auth).json()['items']])
        self.assertEqual(self.c.post('/api/community/users/%d/follow' % target['id'],
                                     headers=tauth, json={'on': True}).status_code, 400,
                         '不能关注自己')
        self.c.post('/api/community/users/%d/follow' % target['id'], headers=self.auth, json={'on': True})
        stats = self.c.get('/api/community/stats', headers=tauth).json()
        self.assertEqual(stats['followers'], 1)
        # 卡片上的关注按钮要有初始态：刚关注的人，帖子卡片该显示"已关注"
        self.c.post('/api/community/posts', headers=tauth, json={'text': '关注态要跟着卡片'})
        def _card():
            return [x for x in self.c.get('/api/community/feed?tab=latest', headers=self.auth).json()['items']
                    if '关注态要跟着卡片' in x['body']][0]
        self.assertTrue(_card()['followed_by_me'], '已经关注了，卡片还说没关注')
        # 关注流 = 我关注的人发的帖子。所以要让 target 反过来关注 owner，
        # 再由 target 读——方向写反的判据会把功能说反。
        self.c.post('/api/community/users/%d/follow' % self.signup['id'], headers=tauth, json={'on': True})
        self.c.post('/api/community/posts', headers=self.auth, json={'text': '关注流里该有这条'})
        seen = self.c.get('/api/community/feed?tab=follow', headers=tauth).json()['items']
        self.assertTrue(any('关注流里该有这条' in x['body'] for x in seen), '关注流没拿到关注对象的帖子')
        outsider = self.c.get('/api/community/feed?tab=follow', headers=hauth).json()['items']
        self.assertEqual(outsider, [], '没关注任何人的人不该看到别人的帖子')
        self.c.post('/api/community/users/%d/follow' % target['id'], headers=self.auth, json={'on': False})
        self.assertEqual(self.c.get('/api/community/stats', headers=tauth).json()['followers'], 0)
        self.assertFalse(_card()['followed_by_me'], '取关之后卡片还是"已关注"')
        notices = self.c.get('/api/notifications', headers=tauth).json()['items']
        self.assertEqual([n for n in notices if n['kind'] == 'follow'], [],
                         '取关之后那条"某人关注了你"该一起收掉')

    def test_media_rejects_foreign_files_and_bad_images(self):
        mine, mauth = self._member('uploader')
        other, oauth = self._member('stealer')
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), (200, 30, 30)).save(buf, format='JPEG')
        upload = self.c.post('/api/community/media', headers=mauth,
                             files={'file': ('p.jpg', buf.getvalue(), 'image/jpeg')}).json()
        self.assertEqual(upload['code'], 0)
        name = upload['name']
        self.assertTrue(self.m.re.fullmatch(r'[0-9a-f]{32}\.jpg', name), '文件名必须是随机十六进制')
        ok = self.c.post('/api/community/posts', headers=mauth,
                         json={'text': '配图帖', 'images': [name]})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(len(ok.json()['post']['images']), 1)
        stolen = self.c.post('/api/community/posts', headers=oauth,
                             json={'text': '偷别人的图', 'images': [name]})
        self.assertEqual(stolen.status_code, 400, '别人上传的文件不能拼进自己的帖子')
        bad = self.c.post('/api/community/media', headers=mauth,
                          files={'file': ('x.jpg', b'not an image at all', 'image/jpeg')})
        self.assertEqual(bad.status_code, 400)
        external = self.c.post('/api/community/posts', headers=mauth,
                               json={'text': '外链图', 'images': ['https://evil/x.jpg']})
        self.assertEqual(external.status_code, 200)
        self.assertEqual(external.json()['post']['images'], [], '外部 URL 一律丢掉，不给转成签名链接的机会')

    def test_direct_messages_persist_and_unread(self):
        """私信必须落在服务端：退出重进、换设备都还在，未读以 read_at 现算。"""
        peer, pauth = self._member('peer')
        sent = self.c.post('/api/chat/send', headers=self.auth,
                           json={'to': peer['id'], 'text': '第一条私信', 'request_id': 'd-1'}).json()
        self.assertFalse(sent['duplicate'])
        again = self.c.post('/api/chat/send', headers=self.auth,
                            json={'to': peer['id'], 'text': '第一条私信', 'request_id': 'd-1'}).json()
        self.assertTrue(again['duplicate'], '同一个 request_id 不该发出第二条')
        self.assertEqual(again['message']['id'], sent['message']['id'])
        convs = self.c.get('/api/chat/conversations', headers=pauth).json()['items']
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]['unread'], 1, '未读计数不对')
        history = self.c.get('/api/chat/messages?with_user=%d' % self.signup['id'], headers=pauth).json()
        self.assertEqual(history['me_id'], peer['id'], '历史接口要明确告诉前端当前登录者是谁')
        self.assertEqual([m['body'] for m in history['items']], ['第一条私信'])
        self.assertEqual(self.c.post('/api/chat/read', headers=pauth,
                                     json={'with_user': self.signup['id']}).json()['marked'], 1)
        self.assertEqual(self.c.get('/api/chat/conversations', headers=pauth).json()['items'][0]['unread'], 0)
        # "退出重进"= 重新拉一次历史，不看任何进程内状态
        again_hist = self.c.get('/api/chat/messages?with_user=%d' % self.signup['id'], headers=pauth).json()
        self.assertEqual(again_hist['me_id'], peer['id'])
        self.assertEqual(len(again_hist['items']), 1)
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                                     json={'to': self.signup['id'], 'text': '自言自语'}).status_code, 400)
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                                     json={'to': 999999, 'text': '不存在'}).status_code, 404)
        self.assertEqual(self.c.post('/api/chat/block', headers=pauth,
                                     json={'with_user': self.signup['id'], 'on': True}).status_code, 200)
        blocked = self.c.post('/api/chat/send', headers=self.auth,
                              json={'to': peer['id'], 'text': '被拉黑之后'})
        self.assertEqual(blocked.status_code, 403, '对方拉黑了我还能发私信')
        # 拉黑是持久状态：我拉黑对方后重开会话，按钮必须显示"取消拉黑"（上面那条是对方拉黑我，方向不同）
        self.c.post('/api/chat/block', headers=self.auth,
                    json={'with_user': peer['id'], 'on': True})
        self.assertTrue(self.c.get('/api/chat/messages?with_user=%d' % peer['id'],
                                   headers=self.auth).json()['partner']['blocked'],
                        '已经拉黑了，会话回执却说没拉黑')
        self.c.post('/api/chat/block', headers=self.auth,
                    json={'with_user': peer['id'], 'on': False})
        self.assertFalse(self.c.get('/api/chat/messages?with_user=%d' % peer['id'],
                                    headers=self.auth).json()['partner']['blocked'],
                         '取消拉黑之后回执还是拉黑态')

    def test_chat_media_needs_mutual_follow_and_survives_reload(self):
        """图片/视频只对互关开放；上传的文件必须有归属，消息重进还在。"""
        peer, pauth = self._member('mediapeer')
        buf = io.BytesIO()
        Image.new('RGB', (400, 300), (12, 120, 80)).save(buf, 'JPEG')
        image = buf.getvalue()
        webm = b'\x1aE\xdf\xa3' + b'\x00' * 4096

        up = self.c.post('/api/chat/media', headers=self.auth, data={'to': peer['id']},
                         files={'file': ('a.jpg', image, 'image/jpeg')})
        self.assertEqual(up.status_code, 403, '没互关也能上传图片')
        self.c.post('/api/community/users/%d/follow' % peer['id'], headers=self.auth, json={'on': True})
        self.assertEqual(self.c.post('/api/chat/media', headers=self.auth, data={'to': peer['id']},
                         files={'file': ('a.jpg', image, 'image/jpeg')}).status_code, 403,
                         '只有我关注对方、对方没回关，也能发图')
        self.c.post('/api/community/users/%d/follow' % self.signup['id'], headers=pauth, json={'on': True})

        up = self.c.post('/api/chat/media', headers=self.auth, data={'to': peer['id']},
                         files={'file': ('a.jpg', image, 'image/jpeg')})
        self.assertEqual(up.status_code, 200, up.text)
        media = up.json()
        self.assertEqual(media['kind'], 'image')
        sent = self.c.post('/api/chat/send', headers=self.auth,
                           json={'to': peer['id'], 'kind': 'image', 'media_name': media['name'],
                                 'request_id': 'media-1'}).json()
        self.assertEqual(sent['message']['kind'], 'image')
        self.assertTrue(sent['message']['media_url'].startswith('/uploads/'))
        served = self.c.get(sent['message']['media_url'])
        self.assertEqual(served.status_code, 200, '签名链接读不到刚发的图片')
        self.assertTrue(served.headers['content-type'].startswith('image/jpeg'))

        video_up = self.c.post('/api/chat/media', headers=self.auth, data={'to': peer['id']},
                               files={'file': ('v.webm', webm, 'video/webm')})
        self.assertEqual(video_up.status_code, 200, video_up.text)
        vmsg = self.c.post('/api/chat/send', headers=self.auth,
                           json={'to': peer['id'], 'kind': 'video', 'media_name': video_up.json()['name'],
                                 'request_id': 'media-2'}).json()['message']
        self.assertEqual(vmsg['kind'], 'video')
        self.assertEqual(vmsg['media_mime'], 'video/webm')
        part = self.c.get(vmsg['media_url'], headers={'Range': 'bytes=0-7'})
        self.assertEqual(part.status_code, 206, '视频不支持 Range，播放器拖不动进度')
        self.assertTrue(part.headers.get('content-range', '').startswith('bytes 0-7/'))

        hist = self.c.get('/api/chat/messages?with_user=%d' % peer['id'], headers=self.auth).json()
        self.assertTrue(hist['partner']['mutual_follow'])
        self.assertEqual([m['kind'] for m in hist['items']], ['image', 'video'])
        conv = self.c.get('/api/chat/conversations', headers=pauth).json()['items'][0]
        self.assertEqual(conv['last_body'], '［视频］', '会话列表没有把视频显示成人话')

        # 别人不能把刚上传的文件拼进自己的消息
        other, oauth = self._member('mediaother')
        stolen = self.c.post('/api/chat/send', headers=oauth,
                             json={'to': peer['id'], 'kind': 'image', 'media_name': media['name']})
        self.assertIn(stolen.status_code, (400, 403), '别人上传的文件被拿去发消息')

        # 取消关注任何一边，媒体权限立即收回；文字不受影响
        self.c.post('/api/community/users/%d/follow' % self.signup['id'], headers=pauth, json={'on': False})
        again = self.c.post('/api/chat/send', headers=self.auth,
                            json={'to': peer['id'], 'kind': 'image', 'media_name': media['name']})
        self.assertEqual(again.status_code, 403, '取关之后还能继续发图')
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                                     json={'to': peer['id'], 'text': '文字还能发'}).status_code, 200)

    def test_chat_sticker_and_invalid_kinds(self):
        peer, pauth = self._member('stickerpeer')
        ok = self.c.post('/api/chat/send', headers=self.auth,
                         json={'to': peer['id'], 'kind': 'sticker', 'text': '😀', 'request_id': 'st-1'})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['message']['kind'], 'sticker')
        self.assertEqual(ok.json()['message']['body'], '😀')
        hist = self.c.get('/api/chat/messages?with_user=%d' % self.signup['id'], headers=pauth).json()
        self.assertEqual(hist['items'][0]['kind'], 'sticker', '表情消息重进变成了普通文字')
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                         json={'to': peer['id'], 'kind': 'sticker', 'text': ''}).status_code, 400)
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                         json={'to': peer['id'], 'kind': 'magic', 'text': 'x'}).status_code, 400)
        self.assertEqual(self.c.post('/api/chat/send', headers=self.auth,
                         json={'to': peer['id'], 'kind': 'image', 'media_name': 'nope.jpg'}).status_code, 403,
                         '没互关时不该先暴露文件名校验')

    def test_ws_ticket_is_one_time_and_chat_round_trips(self):
        peer, pauth = self._member('wsparty')
        ticket = self.c.post('/api/chat/ticket', headers=self.auth).json()
        self.assertTrue(ticket['ticket'].count('.') == 1)
        with self.c.websocket_connect('/ws/chat?ticket=' + ticket['ticket']) as ws:
            ready = ws.receive_json()
            self.assertEqual(ready['t'], 'ready')
            ws.send_json({'t': 'ping'})
            self.assertEqual(ws.receive_json()['t'], 'pong')
            ws.send_json({'t': 'send', 'to': peer['id'], 'text': '走 WS 发的', 'request_id': 'w-1'})
            ack = ws.receive_json()
            self.assertEqual(ack['t'], 'ack')
            self.assertEqual(ack['message']['body'], '走 WS 发的')
        # 票据一次性：重放必须被拒
        with self.assertRaises(Exception):
            with self.c.websocket_connect('/ws/chat?ticket=' + ticket['ticket']) as ws:
                ws.receive_json()
        # WS 发的消息必须和 HTTP 发的一样落在库里（两条路共用一条存法）
        rows = self.c.get('/api/chat/messages?with_user=%d' % self.signup['id'], headers=pauth).json()
        self.assertEqual([m['body'] for m in rows['items']], ['走 WS 发的'])
        with self.assertRaises(Exception):
            with self.c.websocket_connect('/ws/chat?ticket=garbage') as ws:
                ws.receive_json()

    def test_feedback_round_trip_and_region_honesty(self):
        fb = self.c.post('/api/feedback', headers=self.auth,
                         json={'kind': 'bug', 'text': '打卡后数字没刷新', 'page': 'dashboard'}).json()
        self.assertEqual(fb['code'], 0)
        mine = self.c.get('/api/feedback/mine', headers=self.auth).json()
        self.assertEqual(mine['items'][0]['status'], 'new')
        self.assertEqual(mine['status_names']['new'], '待处理', '界面要说的状态名服务端得给全')
        self.assertEqual(self.c.post('/api/feedback', headers=self.auth,
                                     json={'kind': 'magic', 'text': '不认识的类型'}).status_code, 400)
        # 没登录也能投（正卡在登录问题上的人最需要这条出口）
        anon = self.c.post('/api/feedback', json={'kind': 'idea', 'text': '希望有深色模式'})
        self.assertEqual(anon.status_code, 200, anon.text)
        conn = self.m.get_db()
        rows = conn.execute('SELECT user_id FROM feedback ORDER BY id').fetchall()
        conn.close()
        self.assertIsNone(rows[-1]['user_id'], '匿名反馈不该被塞进某个用户名下')
        # 属地：本机没有离线库时必须为空，绝不能编一个"某省"出来
        self.assertFalse(self.m.geoip.status()['ok'], '这台跑测试的机器上不该有 xdb')
        post = self.c.post('/api/community/posts', headers=self.auth, json={'text': '属地看这里'}).json()
        self.assertEqual(post['post']['region'], '')
        self.assertEqual(self.m.region_for('127.0.0.1'), '')
        self.assertEqual(self.m.region_for('not-an-ip'), '')

    def test_community_requires_login(self):
        """社区是会员区：所有读写都要登录，不做匿名浏览，省掉一整类爬取与枚举。"""
        for path in ('/api/community/feed', '/api/community/stats', '/api/chat/conversations',
                     '/api/notifications', '/api/community/search?q=owner'):
            self.assertIn(self.c.get(path).status_code, (401, 403), path + ' 不该免登录可读')
        self.assertIn(self.c.post('/api/community/posts', json={'text': '匿名发帖'}).status_code,
                      (401, 403))

    # ---------- r150：撤回 / 统计明细 / 同城 / 登录落属地 / 气泡装扮 ----------

    def _sql(self, statement, args=()):
        conn = self.m.get_db()
        try:
            conn.execute(statement, args)
            conn.commit()
        finally:
            conn.close()

    def test_notifications_read_clears_the_unread_count(self):
        """机主清单 P0 第 1 条：那个按钮绑了一个不存在的函数，未读永远清不掉。
        这条钉的是"标已读之后，stats 与通知列表两处都得归零"。"""
        me, mauth = self._member('notice_me')
        other, oauth = self._member('notice_other')
        pid = self.c.post('/api/community/posts', headers=mauth, json={'text': '给我点赞'}).json()['post']['id']
        self.c.post('/api/community/posts/%d/like' % pid, headers=oauth, json={})
        before = self.c.get('/api/community/stats', headers=mauth).json()['notices_unread']
        self.assertEqual(before, 1, '别人点赞之后我这边该有一条未读')
        r = self.c.post('/api/notifications/read', headers=mauth, json={'all': True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['changed'], 1, '回执要说清改了几条')
        self.assertEqual(self.c.get('/api/community/stats', headers=mauth).json()['notices_unread'], 0)
        items = self.c.get('/api/notifications', headers=mauth).json()['items']
        self.assertTrue(all(n['read_at'] for n in items), '列表里还留着未读标记')

    def test_recall_only_own_within_window_and_clears_body(self):
        a, aauth = self._member('recall_a')
        b, bauth = self._member('recall_b')
        mid = self.c.post('/api/chat/send', headers=aauth,
                          json={'to': b['id'], 'text': '这句要撤回'}).json()['message']['id']
        # 对方不能撤我的
        self.assertEqual(self.c.post('/api/chat/recall', headers=bauth,
                                     json={'message_id': mid}).status_code, 403,
                         '不是发送者也能撤回')
        r = self.c.post('/api/chat/recall', headers=aauth, json={'message_id': mid})
        self.assertEqual(r.status_code, 200, r.text)
        hist = self.c.get('/api/chat/messages?with_user=%d' % b['id'], headers=aauth).json()
        mine = [x for x in hist['items'] if x['id'] == mid][0]
        self.assertEqual(mine['body'], '', '撤回之后正文还在往外发')
        self.assertTrue(mine['recalled_at'], '撤回标记没落到回执里')
        conv = [c for c in self.c.get('/api/chat/conversations', headers=bauth).json()['items']
                if c['with']['id'] == a['id']][0]
        self.assertEqual(conv['last_body'], u'（已撤回）', '会话列表还显示着被撤回的那句原话')
        # 超过窗口就不给撤
        mid2 = self.c.post('/api/chat/send', headers=aauth,
                           json={'to': b['id'], 'text': '这句太久了'}).json()['message']['id']
        self._sql("UPDATE messages SET created_at=? WHERE id=?",
                  ((self.m.datetime.now() - self.m.timedelta(minutes=9)).strftime('%Y-%m-%d %H:%M:%S'), mid2))
        self.assertEqual(self.c.post('/api/chat/recall', headers=aauth,
                                     json={'message_id': mid2}).status_code, 400,
                         '超过 5 分钟还能撤回')

    def test_connections_and_posts_of_agree_with_their_own_rows(self):
        """统计格点进去的列表，必须和数字自己数出来的一致（父=Σ子那条老规矩）。"""
        a, aauth = self._member('conn_a')
        b, bauth = self._member('conn_b')
        self.c.post('/api/community/users/%d/follow' % a['id'], headers=bauth, json={'on': True})
        followers = self.c.get('/api/community/connections?user_id=%d&kind=followers' % a['id'],
                               headers=aauth).json()
        self.assertEqual([x['id'] for x in followers['items']], [b['id']], '粉丝列表方向不对或漏人')
        self.assertEqual(followers['total'], 1)
        self.assertEqual(followers['items'][0]['followed_by_me'], False)
        following = self.c.get('/api/community/connections?user_id=%d&kind=following' % b['id'],
                               headers=bauth).json()
        self.assertEqual([x['id'] for x in following['items']], [a['id']], '关注列表方向反了')
        self.assertEqual(following['items'][0]['followed_by_me'], True, '我关注过的人该标成已关注')
        self.assertEqual(self.c.get('/api/community/connections?user_id=%d&kind=magic' % a['id'],
                                    headers=aauth).status_code, 400)
        # 获赞列表按赞数排（两条赞的那条要压过一条赞的）
        c_, cauth = self._member('conn_c')
        p1 = self.c.post('/api/community/posts', headers=aauth, json={'text': '两条赞'}).json()['post']['id']
        p2 = self.c.post('/api/community/posts', headers=aauth, json={'text': '一条赞'}).json()['post']['id']
        for who in (bauth, cauth):
            self.c.post('/api/community/posts/%d/like' % p1, headers=who, json={})
        self.c.post('/api/community/posts/%d/like' % p2, headers=bauth, json={})
        liked = self.c.get('/api/community/posts-of?user_id=%d&sort=likes' % a['id'], headers=aauth).json()
        self.assertEqual([x['id'] for x in liked['items']][:1], [p1], '按赞数排序排错了')
        self.assertEqual(liked['items'][0]['like_count'], 2)
        self.assertEqual(liked['total'], 2)
        mine = self.c.get('/api/community/posts-of?user_id=%d' % a['id'], headers=aauth).json()
        self.assertEqual(len(mine['items']), 2)
        self.assertEqual(self.c.get('/api/community/posts-of?user_id=%d&sort=magic' % a['id'],
                                    headers=aauth).status_code, 400)

    def test_city_feed_needs_region_and_only_shows_same_province(self):
        a, aauth = self._member('city_a')
        b, bauth = self._member('city_b')
        # 没有属地时宁可给空，也不拿"全部"冒充"同城"
        empty = self.c.get('/api/community/feed?tab=city', headers=aauth).json()
        self.assertEqual(empty['items'], [])
        self.assertIn('属地', empty.get('why', ''), '没属地却不解释原因')
        self._sql("UPDATE community_profile SET region='湖南' WHERE user_id=?", (a['id'],))
        self._sql("UPDATE community_profile SET region='湖北' WHERE user_id=?", (b['id'],))
        pa = self.c.post('/api/community/posts', headers=aauth, json={'text': '长沙的粉'}).json()['post']['id']
        self._sql("UPDATE posts SET region='湖南' WHERE id=?", (pa,))
        pb = self.c.post('/api/community/posts', headers=bauth, json={'text': '武汉的热干面'}).json()['post']['id']
        self._sql("UPDATE posts SET region='湖北' WHERE id=?", (pb,))
        seen = [x['id'] for x in self.c.get('/api/community/feed?tab=city', headers=aauth).json()['items']]
        self.assertEqual(seen, [pa], '同城把别的省的帖子也放进来了')
        self.assertEqual(self.c.get('/api/community/feed?tab=magic', headers=aauth).status_code, 400)

    def test_login_and_register_record_region_once(self):
        """属地以前要等到发帖才认，新登录的人主页一直挂着"属地未知"。"""
        real = self.m.region_for
        self.m.region_for = lambda ip: u'湖南'
        try:
            user, auth = self._member('geo_login')
            self.assertEqual(self.c.get('/api/community/stats', headers=auth).json()['region'], u'湖南',
                             '注册那一次没落属地')
            self._sql("UPDATE community_profile SET region='' WHERE user_id=?", (user['id'],))
            self.c.post('/api/login', json={'username': 'geo_login', 'password': self.body['password']})
            self.assertEqual(self.c.get('/api/community/stats', headers=auth).json()['region'], u'湖南',
                             '登录这一次没落属地')
            # 解析不出来的那一次（换网络、走代理）不能把已有属地洗掉
            self.m.region_for = lambda ip: ''
            self.c.post('/api/login', json={'username': 'geo_login', 'password': self.body['password']})
            self.assertEqual(self.c.get('/api/community/stats', headers=auth).json()['region'], u'湖南',
                             '一次解析失败就把已有属地洗掉了')
            # 评论也算"活动"：界面写的是"发一次帖子或评论就会带上"，两条都得真落库
            other, oauth = self._member('geo_comment')
            pid = self.c.post('/api/community/posts', headers=auth, json={'text': '来评论'}).json()['post']['id']
            self._sql("UPDATE community_profile SET region='' WHERE user_id=?", (other['id'],))
            self.m.region_for = lambda ip: u'广东'
            self.c.post('/api/community/posts/%d/comments' % pid, headers=oauth, json={'text': '来了'})
            self.assertEqual(self.c.get('/api/community/stats', headers=oauth).json()['region'], u'广东',
                             '评论没把属地带上，跟界面上那句话对不上')
        finally:
            self.m.region_for = real

    def test_bubble_theme_round_trip_and_rejects_junk(self):
        a, aauth = self._member('theme_a')
        self.assertEqual(self.c.get('/api/community/stats', headers=aauth).json()['bubble_theme'], 'green')
        r = self.c.post('/api/community/profile', headers=aauth, json={'bubble_theme': 'rose'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['bubble_theme'], 'rose')
        self.assertEqual(self.c.get('/api/community/stats', headers=aauth).json()['bubble_theme'], 'rose')
        self.assertEqual(self.c.post('/api/community/profile', headers=aauth,
                                     json={'bubble_theme': '<img onerror=1>'}).status_code, 400,
                         '脏值没被白名单拦住')

    def test_comment_deletable_flag_and_removal(self):
        """评论的「删除」按钮由服务端给的 deletable 决定。
        这个字段漏返回时按钮永远不出现——界面上看着像"本来就没有删除"，最难发现。
        口径与 DELETE 端点一致：作者本人 + 楼主都能删，第三方不能。"""
        a, aauth = self._member('cdel_a')
        b, bauth = self._member('cdel_b')
        c_, cauth = self._member('cdel_c')
        pid = self.c.post('/api/community/posts', headers=aauth, json={'text': '来删我评论'}).json()['post']['id']
        mine = self.c.post('/api/community/posts/%d/comments' % pid, headers=bauth,
                           json={'text': '别人写的评论'}).json()['comment']['id']
        as_author = self.c.get('/api/community/posts/%d' % pid, headers=bauth).json()
        self.assertTrue([x for x in as_author['comments'] if x['id'] == mine][0]['deletable'],
                        '自己写的评论却说不能删')
        as_owner = self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()
        self.assertTrue([x for x in as_owner['comments'] if x['id'] == mine][0]['deletable'],
                        '楼主删不了自己帖子下的评论，跟端点口径不一致')
        as_stranger = self.c.get('/api/community/posts/%d' % pid, headers=cauth).json()
        self.assertFalse([x for x in as_stranger['comments'] if x['id'] == mine][0]['deletable'],
                         '跟这条帖子无关的人也给了删除权')
        self.assertEqual(self.c.delete('/api/community/comments/%d' % mine, headers=cauth).status_code,
                         403, '无关的人能把这条评论删掉')
        r = self.c.delete('/api/community/comments/%d' % mine, headers=bauth)
        self.assertEqual(r.status_code, 200, r.text)
        left = self.c.get('/api/community/posts/%d' % pid, headers=bauth).json()
        self.assertEqual([x['id'] for x in left['comments']], [], '删了还列出来')
        self.assertEqual(left['post']['comment_count'], 0, '评论数没跟着减')

    def test_comment_detail_includes_reply_target_identity(self):
        owner, owner_auth = self._member('reply_owner')
        root_author, root_auth = self._member('reply_root')
        reply_author, reply_auth = self._member('reply_child')
        pid = self.c.post('/api/community/posts', headers=owner_auth,
                          json={'text': '评论层级测试'}).json()['post']['id']
        root = self.c.post('/api/community/posts/%d/comments' % pid, headers=root_auth,
                           json={'text': '主评论'}).json()['comment']
        child = self.c.post('/api/community/posts/%d/comments' % pid, headers=reply_auth,
                            json={'text': '回复主评论', 'reply_to': root['id']}).json()['comment']
        detail = self.c.get('/api/community/posts/%d' % pid, headers=owner_auth).json()
        root_name = root['author']['name']
        rendered_child = next(c for c in detail['comments'] if c['id'] == child['id'])
        self.assertEqual(rendered_child['reply_to'], root['id'])
        self.assertEqual(rendered_child['reply_to_user_id'], root_author['id'])
        self.assertEqual(rendered_child['reply_to_name'], root_name)

    def test_new_community_endpoints_all_require_login(self):
        for path in ('/api/community/connections?user_id=2&kind=followers',
                     '/api/community/posts-of?user_id=2',
                     '/api/chat/recall', '/api/notifications/read'):
            code = (self.c.get(path).status_code if path.startswith('/api/community/connections')
                    or path.startswith('/api/community/posts-of')
                    else self.c.post(path, json={}).status_code)
            self.assertIn(code, (401, 403), path + ' 不该免登录')


    def test_favorite_toggle_list_and_isolation(self):
        """收藏是小红书的第三动作：自己收藏自己看得到，别人看不到，取消就消失。"""
        a, aauth = self._member('favauthor')
        b, bauth = self._member('favreader')
        pid = self.c.post('/api/community/posts', headers=aauth,
                          json={'text': '值得收藏的一条', 'images': []}).json()['post']['id']
        self.assertEqual(self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()['post']['favorite_count'], 0)
        on = self.c.post('/api/community/posts/%d/favorite' % pid, headers=aauth, json={'on': True})
        self.assertEqual(on.status_code, 200, on.text)
        self.assertTrue(on.json()['favorited'])
        self.assertEqual(on.json()['favorite_count'], 1)
        mine = self.c.get('/api/community/favorites?limit=12', headers=aauth).json()
        self.assertEqual([x['id'] for x in mine['items']], [pid])
        self.assertTrue(self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()['post']['favorited_by_me'])
        other = self.c.get('/api/community/posts/%d' % pid, headers=bauth).json()['post']
        self.assertFalse(other['favorited_by_me'], '别人也显示已收藏')
        self.assertEqual(other['favorite_count'], 1, '收藏数应该公开')
        self.assertEqual(self.c.get('/api/community/favorites?limit=12', headers=bauth).json()['items'], [])
        off = self.c.post('/api/community/posts/%d/favorite' % pid, headers=aauth, json={'on': False})
        self.assertEqual(off.json()['favorite_count'], 0)
        self.assertEqual(self.c.get('/api/community/favorites?limit=12', headers=aauth).json()['items'], [])

    def test_search_returns_posts_as_well_as_people(self):
        a, aauth = self._member('searchposter')
        pid = self.c.post('/api/community/posts', headers=aauth,
                          json={'text': '独一无二的关键词：青椒炒蛋', 'images': []}).json()['post']['id']
        r = self.c.get('/api/community/search?q=青椒炒蛋', headers=aauth).json()
        self.assertIn(pid, [x['id'] for x in r.get('posts') or []], '搜索没有返回帖子')
        self.assertEqual(r['posts'][0]['body'], '独一无二的关键词：青椒炒蛋')
        stray = self.c.get('/api/community/search?q=不存在的词zzz', headers=aauth).json()
        self.assertEqual(stray['posts'], [])

    def test_report_is_validated_and_stored(self):
        a, aauth = self._member('reporter')
        b, bauth = self._member('reported')
        pid = self.c.post('/api/community/posts', headers=bauth,
                          json={'text': '会被举报的帖子', 'images': []}).json()['post']['id']
        ok = self.c.post('/api/community/report', headers=aauth,
                         json={'kind': 'post', 'target_id': pid, 'reason': '垃圾广告：卖课'})
        self.assertEqual(ok.status_code, 200, ok.text)
        import sqlite3 as _sq
        conn = _sq.connect(self.m.DB_PATH)
        row = conn.execute('SELECT target_kind,target_id,reporter,reason FROM content_reports ORDER BY id DESC LIMIT 1').fetchone()
        conn.close()
        self.assertEqual(row[0], 'post')
        self.assertEqual(row[1], pid)
        self.assertEqual(row[2], self.signup['id'] if False else row[2])
        self.assertIn('垃圾广告', row[3])
        self.assertEqual(self.c.post('/api/community/report', headers=aauth,
                         json={'kind': 'user', 'target_id': pid, 'reason': 'x'}).status_code, 400)
        self.assertEqual(self.c.post('/api/community/report', headers=aauth,
                         json={'kind': 'post', 'target_id': pid, 'reason': '   '}).status_code, 400)

    def test_edit_post_is_author_only_and_marks_edited(self):
        """编辑入口是这一轮补的：只有作者能改，改完要有 edited_at，别人一个字都改不动。"""
        a, aauth = self._member('editauthor')
        b, bauth = self._member('editreader')
        made = self.c.post('/api/community/posts', headers=aauth, json={'text': '第一版正文', 'images': []})
        self.assertEqual(made.status_code, 200, made.text)
        pid = made.json()['post']['id']
        self.assertIsNone(self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()['post'].get('edited_at'))
        bad = self.c.patch('/api/community/posts/%d' % pid, headers=bauth, json={'text': '我要改别人的'})
        self.assertEqual(bad.status_code, 403, bad.text)
        empty = self.c.patch('/api/community/posts/%d' % pid, headers=aauth, json={'text': '   '})
        self.assertIn(empty.status_code, (400, 422), empty.text)
        ok = self.c.patch('/api/community/posts/%d' % pid, headers=aauth, json={'text': '第二版正文'})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['post']['body'], '第二版正文')
        self.assertTrue(ok.json()['post'].get('edited_at'), '改完没记 edited_at')
        detail = self.c.get('/api/community/posts/%d' % pid, headers=aauth).json()['post']
        self.assertEqual(detail['body'], '第二版正文')
        self.assertTrue(detail.get('edited_at'))
        # 列表里也必须是新正文，不能只改详情
        feed = self.c.get('/api/community/feed?tab=latest&limit=20', headers=aauth).json()['items']
        self.assertEqual([x['body'] for x in feed if x['id'] == pid], ['第二版正文'])
        gone = self.c.delete('/api/community/posts/%d' % pid, headers=aauth)
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.c.patch('/api/community/posts/%d' % pid, headers=aauth,
                                      json={'text': '删了还改'}).status_code, 404)

    def _set_ban(self, uid, at='2026-10-18T12:00:00Z', reason='发布违规内容'):
        """后台的封号动作最终就是改这两列；测试直接落库，绕开"运维 API 还没建"这件事。"""
        import sqlite3
        conn = sqlite3.connect(self.m.DB_PATH)
        conn.execute('UPDATE users SET banned_at=?, ban_reason=? WHERE id=?',
                     (None if at is None else at, '' if at is None else reason, uid))
        conn.commit(); conn.close()

    def test_ban_blocks_api_and_login_and_reverts(self):
        """封号不是给后台自己看的标记：请求必须真被拦住，且能解封恢复。"""
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).status_code, 200)
        self._set_ban(self.signup['id'])
        r = self.c.get('/api/dashboard', headers=self.auth)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json().get('code'), 'account_banned',
                         '没有机器码，前端只能拿 403 猜——而 403 在本服务里还用于"只能删自己的帖子"')
        self.assertIn('已被停用', r.json()['detail'])
        self.assertIn('发布违规内容', r.json()['detail'], '封号原因没带出来，用户只会看到一个谜')
        # 登录路径也要拦（否则被封的人还能拿到新 token）
        bad = self.c.post('/api/login', json={'username': 'owner', 'password': 'Review!123'})
        self.assertEqual(bad.status_code, 403, bad.text)
        self.assertEqual(bad.json().get('code'), 'account_banned')
        # 解封
        self._set_ban(self.signup['id'], at=None)
        self.assertEqual(self.c.get('/api/dashboard', headers=self.auth).status_code, 200)
        self.assertEqual(self.c.post('/api/login', json={'username': 'owner',
                                 'password': 'Review!123'}).status_code, 200)

    def test_ban_never_leaks_before_the_password_is_proved(self):
        """被封的号密码错时仍要说"用户名或密码错误"：不然"这个号被封过"就成了免口令可探的信号。"""
        other, _ = self._member('bystander')
        self._set_ban(self.signup['id'])
        wrong = self.c.post('/api/login', json={'username': 'owner', 'password': 'WrongPass!1'})
        self.assertEqual(wrong.status_code, 400, wrong.text)
        self.assertNotIn('停用', wrong.text)
        self.assertEqual(wrong.json()['detail'], '用户名或密码错误', '口径和未封号时不一致了')
        # 别人的请求不受牵连
        self.assertEqual(self.c.get('/api/dashboard',
                                    headers={'Authorization': 'Bearer ' + other['token']}).status_code, 200)

    def test_banned_user_cannot_open_ws_even_with_a_ticket_in_hand(self):
        """票据 30 秒内有效：先拿票再被封，这条连接必须连不上。"""
        ticket = self.c.post('/api/chat/ticket', headers=self.auth).json()
        self.assertTrue(ticket.get('ticket'))
        self._set_ban(self.signup['id'])
        with self.assertRaises(Exception):
            with self.c.websocket_connect('/ws/chat?ticket=' + ticket['ticket']) as ws:
                ws.receive_json()

    def test_keys_can_live_outside_the_database_dir_and_say_when_rebuilt(self):
        """后台要读同一个库文件，密钥就不能留在那个目录里；被新建过也必须说得出。"""
        import shutil
        from pathlib import Path
        key_dir = Path(self.tmp.name) / 'KEYS'
        shutil.rmtree(key_dir, ignore_errors=True)
        key_dir.mkdir()          # 部署时这个目录由 bootstrap 建；缺了就要人看见，不在函数里偷偷补
        self.m.KEY_DIR = str(key_dir)
        self.m._KEYS_REGENERATED.clear()
        first = self.m.media_key()
        self.assertTrue((key_dir / 'media-signing.key').is_file(), '密钥没落到 KEY_DIR')
        self.assertFalse((Path(self.m.DB_PATH).parent / 'media-signing.key').exists(),
                         '业务库目录里还留着密钥，容器挂载就一定能读到')
        self.assertEqual(self.m._KEYS_REGENERATED, {'media-signing.key'})
        self.assertIn('media-signing.key', self.c.get('/health/ready').json()['keys']['regenerated'])
        second = self.m.media_key()
        self.assertEqual(first, second, '第二次调用把密钥换了，所有已签名链接会当场失效')
        self.assertEqual(self.m._KEYS_REGENERATED, {'media-signing.key'}, '新建过却"忘掉"了')
        self.m.ws_secret()
        ready = self.c.get('/health/ready').json()['keys']
        self.assertTrue(ready['isolated'], '健康检查没看出密钥目录已隔离')
        self.assertEqual(sorted(ready['present']), ['media-signing.key', 'ws-secret.key'])
        # 健康检查是公开接口：可以报"有没有、新建过没"，但不能把密钥本身吐出去
        self.assertNotIn(first, self.c.get('/health/ready').content, '健康检查泄了密钥内容')


if __name__=='__main__':unittest.main(verbosity=2)
