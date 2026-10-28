"""Bounded query and media contracts against synthetic local data."""
import asyncio,importlib.util,io,os,sqlite3,sys,tempfile,threading,time,unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app_modules import companion,media
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

class OptimizationRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'_audit_sandbox')
        self.env=patch.dict(os.environ,{**{f'QINGSU_{k}_DIR':str(Path(self.tmp.name)/k) for k in ('DB','KEY','UPLOAD','WEB')},'QINGSU_SKIP_MIGRATE':'0'})
        self.env.start();spec=importlib.util.spec_from_file_location('runtime_test',ROOT/'server.py');self.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.s)
        self.s._redis_cmd=lambda *a,**k:(False,None)
        self.client=TestClient(self.s.app)
        self.user=self.client.post('/api/register',json={'username':'synthetic','password':'Runtime!123','age':30,'height':170,'weight_jin':160,'target_weight_jin':140}).json()
    def tearDown(self):self.client.close();self.env.stop();self.tmp.cleanup()
    def test_dashboard_queries_are_independent_of_missing_workout_days(self):
        c=self.s.get_db();c.execute("UPDATE users SET created_at='2026-01-01 00:00:00'");c.commit();user=dict(c.execute('SELECT * FROM users').fetchone());c.close()
        sql=[];original=self.s.get_db
        def traced():
            c=original();c.set_trace_callback(lambda x:sql.append(x) if x.lstrip().upper().startswith('SELECT') else None);return c
        with patch.object(self.s,'get_db',traced):result=self.s.compute_dashboard_data(user)
        self.assertEqual(result['consecutive_slacking_days'],7);self.assertLessEqual(len(sql),19,sql)
        print('dashboard_selects='+str(len(sql)))
    def test_goal_batch_preserves_counts_privacy_and_query_bound(self):
        c=self.s.get_db();uid=self.user['id'];today=date.today().isoformat()
        for i in range(30):
            g=c.execute('INSERT INTO shared_goals(owner_id,title,kind,target,start_date,end_date,invite_hash) VALUES (?,?,?,?,?,?,?)',(uid,'synthetic','workout' if i%2 else 'complete',3,today,today,str(i))).lastrowid
            c.execute('INSERT INTO shared_goal_members VALUES (?,?)',(g,uid))
        c.execute("INSERT INTO workout_logs(user_id,log_date,cal_burned) VALUES (?,?,0)",(uid,today));c.execute('INSERT INTO daily_reviews VALUES (?,?,1)',(uid,today));c.commit();sql=[];c.set_trace_callback(sql.append)
        result=companion.goal_summary(c,uid);c.close()
        self.assertEqual(len(result),30);self.assertTrue(all(g['members'][0]['days']==1 for g in result));self.assertLessEqual(len(sql),4)
        self.assertTrue(all(set(g['members'][0])=={'nickname','me','days'} for g in result))
        print('goals_selects='+str(len(sql)))
    def test_query_indexes_are_used(self):
        c=self.s.get_db()
        for query,args,index in [('SELECT * FROM body_cycles WHERE user_id=? ORDER BY cycle_num DESC LIMIT 1',(1,),'idx_body_cycles_user_cycle'),('SELECT * FROM training_sessions WHERE user_id=? AND deleted=0 ORDER BY id DESC LIMIT 21',(1,),'idx_training_sessions_user_id')]:
            text=str(c.execute('EXPLAIN QUERY PLAN '+query,args).fetchall()[0][3]);self.assertIn(index,text)
        c.close()
    def test_image_work_does_not_block_event_loop(self):
        async def check():
            started=threading.Event();done=threading.Event()
            def work():started.set();done.wait(2);return 'ok'
            task=asyncio.create_task(media.process(work))
            while not started.is_set():await asyncio.sleep(.001)
            await asyncio.sleep(.01);self.assertFalse(task.done());done.set();self.assertEqual(await task,'ok')
        asyncio.run(check())
    def test_processing_capacity_and_release_on_failure(self):
        async def check():
            with patch.object(media,'_SLOTS',threading.BoundedSemaphore(1)):
                media._SLOTS.acquire()
                try:
                    with self.assertRaises(HTTPException) as e:await media.process(lambda:None)
                    self.assertEqual(e.exception.status_code,503)
                finally:media._SLOTS.release()
                def fail():raise ValueError('synthetic')
                with self.assertRaises(ValueError):await media.process(fail)
                self.assertEqual(await media.process(lambda:42),42)
        asyncio.run(check())
    def test_upload_reader_never_reads_unbounded_body(self):
        class File:
            def __init__(self,data):self.data=data;self.read_sizes=[]
            async def read(self,n):self.read_sizes.append(n);out=self.data[:n];self.data=self.data[n:];return out
        async def check():
            f=File(b'x'*12)
            with self.assertRaises(HTTPException) as e:await media.read_upload(f,10,'large')
            self.assertEqual(e.exception.status_code,413);self.assertEqual(f.read_sizes,[11])
            self.assertEqual(await media.read_upload(File(b'x'*10),10,'large'),b'x'*10)
        asyncio.run(check())
    def test_photo_deletion_also_removes_thumbnail(self):
        raw=io.BytesIO();Image.new('RGB',(10,10)).save(raw,format='PNG')
        headers={'Authorization':'Bearer '+self.user['token']}
        response=self.client.post('/api/cycle/measure',headers=headers,data={'weight_jin':160,'waist_cm':70},files={'photo':('synthetic.png',raw.getvalue(),'image/png')})
        self.assertEqual(response.status_code,200,response.text)
        c=self.s.get_db();name=Path(c.execute('SELECT photo_url FROM body_cycles WHERE photo_url<>\'\' ORDER BY id DESC').fetchone()[0]).name;c.close()
        path=Path(self.s.UPLOAD_DIR)/name;thumb=self.s._ensure_thumb(name,str(path));self.assertTrue(Path(thumb).exists())
        self.assertEqual(self.client.post('/api/photo/delete',headers=headers).status_code,200);self.assertFalse(path.exists());self.assertFalse(Path(thumb).exists())

if __name__=='__main__':unittest.main(verbosity=2)
