"""Real API/SQLite contracts for private training data and existing statistics."""
import copy,csv,importlib.util,io,json,sys,unittest,uuid
from pathlib import Path
from datetime import date,timedelta
from pydantic import ValidationError
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('training_fixture',Path(__file__).with_name('test_bubble_themes.py'));fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from app_modules import training

class Training(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.BubbleThemes.setUpClass.__func__(cls);cls.a,cls.b=[u['id'] for u in cls.users];cls.h2={**cls.headers,'Authorization':'Bearer '+cls.users[1]['token']}
    def payload(self,**kw):
        p={'title':'测试训练','day':date.today().isoformat(),'status':'planned','scene':'gym','minutes':20,'energy':0,'request_id':str(uuid.uuid4()),'exercises':[{'name':'哑铃划船','kind':'reps','sets':[{'reps':10,'weight_kg':12.5,'done':True},{'reps':12,'weight_kg':10,'done':False}]}]};p.update(kw);return p
    def create(self,p=None,h=None):
        r=self.c.post('/api/training/sessions',headers=h or self.headers,json=p or self.payload());self.assertEqual(r.status_code,200,r.text);return r.json()['item']
    def count(self,table,uid=None):
        c=self.s.get_db()
        try:return c.execute('SELECT COUNT(*) FROM '+table+' WHERE user_id=?',(uid or self.a,)).fetchone()[0]
        finally:c.close()
    def test_plans_private_and_not_counted(self):
        n=self.count('workout_logs');r=self.create();self.assertFalse(r['counted']);self.assertEqual(self.count('workout_logs'),n)
        for method,path,body in [('get','/api/training/sessions/'+str(r['id']),None),('put','/api/training/sessions/'+str(r['id']),self.payload(expected_version=1)),('post','/api/training/sessions/'+str(r['id'])+'/delete',{'expected_version':1})]:
            res=getattr(self.c,method)(path,headers=self.h2,**({'json':body} if body else {}));self.assertEqual(res.status_code,404)
        self.assertEqual(self.c.get('/api/training/sessions').status_code,401)
        self.assertNotIn(r['id'],[x['id'] for x in self.c.get('/api/training/sessions',headers=self.h2).json()['items']])
    def test_completion_retry_and_conflicting_replay(self):
        p=self.payload(status='completed');before=self.count('workout_logs');x=self.create(p);self.assertTrue(x['counted']);y=self.create(p);self.assertEqual(x['id'],y['id']);self.assertEqual(self.count('workout_logs'),before+1)
        res=self.c.post('/api/training/sessions',headers=self.headers,json={**p,'minutes':35});self.assertEqual(res.status_code,409)
    def test_edit_and_delete_keep_summary_consistent(self):
        p=self.payload(status='completed',note='private note');x=self.create(p);sid=x['id'];before=self.count('workout_logs')
        r=self.c.put('/api/training/sessions/'+str(sid),headers=self.headers,json={**p,'minutes':30,'expected_version':1});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['item']['version'],2)
        c=self.s.get_db();linked=c.execute('SELECT workout_log_id FROM training_sessions WHERE id=?',(sid,)).fetchone()[0];self.assertEqual(c.execute('SELECT duration_minutes FROM workout_logs WHERE id=?',(linked,)).fetchone()[0],30);c.close()
        self.assertEqual(self.c.put('/api/training/sessions/'+str(sid),headers=self.headers,json={**p,'expected_version':1}).status_code,409)
        self.assertEqual(self.c.put('/api/training/sessions/'+str(sid),headers=self.headers,json={**p,'status':'planned','expected_version':2}).status_code,400)
        self.assertEqual(self.c.post('/api/records/workout/'+str(linked)+'/delete',headers=self.headers,json={}).status_code,409)
        rows=self.c.get('/api/records?kind=workout',headers=self.headers).json()['rows'];self.assertEqual(next(r for r in rows if r['id']==linked)['training_session_id'],sid)
        self.assertEqual(self.c.post('/api/training/sessions/'+str(sid)+'/delete',headers=self.headers,json={'expected_version':2}).status_code,200);self.assertEqual(self.count('workout_logs'),before-1)
        self.assertEqual(self.c.post('/api/training/sessions',headers=self.headers,json=p).status_code,409)
        c=self.s.get_db();row=c.execute('SELECT * FROM training_sessions WHERE id=?',(sid,)).fetchone();self.assertEqual(row['exercises_json'],'[]');self.assertEqual(row['note'],'');self.assertEqual(row['energy'],0);self.assertEqual(c.execute('SELECT COUNT(*) FROM training_sets WHERE session_id=?',(sid,)).fetchone()[0],0);self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[]);c.close()
    def test_templates_reset_completed_groups_and_are_private(self):
        p={k:v for k,v in self.payload().items() if k in ['title','scene','exercises','request_id']};r=self.c.post('/api/training/templates',headers=self.headers,json=p);self.assertEqual(r.status_code,200,r.text);x=r.json()['item'];self.assertFalse(x['exercises'][0]['sets'][0]['done'])
        self.assertEqual(self.c.post('/api/training/templates',headers=self.headers,json=p).json()['item']['id'],x['id'])
        self.assertEqual(self.c.put('/api/training/templates/'+str(x['id']),headers=self.h2,json={**p,'expected_version':1}).status_code,404)
        edited=self.c.put('/api/training/templates/'+str(x['id']),headers=self.headers,json={**p,'title':'修改后的模板','expected_version':1});self.assertEqual(edited.status_code,200);self.assertEqual(edited.json()['item']['version'],2)
        self.assertEqual(self.c.put('/api/training/templates/'+str(x['id']),headers=self.headers,json={**p,'expected_version':1}).status_code,409)
        self.assertEqual(self.c.post('/api/training/templates/'+str(x['id'])+'/delete',headers=self.headers,json={'expected_version':2}).status_code,200)
        self.assertEqual(self.c.post('/api/training/templates',headers=self.headers,json=p).status_code,409)
    def test_progress_only_done_and_completed_and_own(self):
        def ex(w,r,done=True):return [{'name':'Progress Squat','kind':'reps','sets':[{'weight_kg':w,'reps':r,'done':done}]}]
        a=self.create(self.payload(status='completed',exercises=ex(20,10)));b=self.create(self.payload(status='completed',exercises=ex(25,8)));self.create(self.payload(exercises=ex(500,500)))
        self.create(self.payload(status='completed',exercises=ex(100,10)),self.h2)
        p=self.c.get('/api/training/progress?exercise=progress%20squat',headers=self.headers).json();self.assertEqual(p['best']['max_weight_kg'],25);self.assertEqual(p['best']['sets'],2);self.assertEqual(p['best']['volume_kg_reps'],400);self.assertEqual(len(p['recent']),2)
        self.c.post('/api/training/sessions/'+str(a['id'])+'/delete',headers=self.headers,json={'expected_version':1});p=self.c.get('/api/training/progress?exercise=progress%20squat',headers=self.headers).json();self.assertEqual(p['best']['volume_kg_reps'],200)
    def test_calendar_separates_plans_and_actual_minutes(self):
        month=date.today().isoformat()[:7];before=self.c.get('/api/training/calendar?month='+month,headers=self.headers).json();old=next((r for r in before['days'] if r['day']==date.today().isoformat()),{'completed':0,'planned':0,'minutes':0})
        self.create(self.payload(status='planned',minutes=55));self.create(self.payload(status='completed',minutes=18));after=self.c.get('/api/training/calendar?month='+month,headers=self.headers).json();row=next(r for r in after['days'] if r['day']==date.today().isoformat());self.assertEqual(row['completed'],old['completed']+1);self.assertEqual(row['planned'],old['planned']+1);self.assertEqual(row['minutes'],old['minutes']+18)
        self.assertEqual(self.c.get('/api/training/calendar?month=2026-99',headers=self.headers).status_code,400)
    def test_validation_and_future_boundaries(self):
        for patch in [{'minutes':0,'status':'completed'},{'day':(date.today()+timedelta(days=1)).isoformat(),'status':'completed'},{'day':(date.today()+timedelta(days=366)).isoformat()},{'title':'   '},{'exercises':[]},{'user_id':self.b},{'energy':99999}]:
            r=self.c.post('/api/training/sessions',headers=self.headers,json=self.payload(**patch));self.assertIn(r.status_code,[400,422],r.text)
        bad=self.payload(status='completed');bad['exercises'][0]['sets'][0]['reps']=None;self.assertEqual(self.c.post('/api/training/sessions',headers=self.headers,json=bad).status_code,422)
        with self.assertRaises(ValidationError):training.SetEntry(weight_kg=float('nan'))
    def test_export_owner_and_formula_protection(self):
        self.create(self.payload(title='=1+2',note='@private'));self.create(self.payload(title='other-user-never-export'),self.h2)
        r=self.c.get('/api/training/export.csv',headers=self.headers);self.assertEqual(r.status_code,200);self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'));self.assertIn("'=1+2",r.text);self.assertIn("'@private",r.text);self.assertNotIn('other-user-never-export',r.text);self.assertIn('no-store',r.headers['cache-control'])
    def test_keyset_page_and_schema(self):
        for _ in range(3):self.create()
        a=self.c.get('/api/training/sessions?limit=2',headers=self.headers).json();b=self.c.get('/api/training/sessions?limit=2&cursor='+str(a['next_cursor']),headers=self.headers).json();self.assertTrue(a['more']);self.assertFalse({x['id'] for x in a['items']}&{x['id'] for x in b['items']});self.assertEqual(a['me_id'],self.a);self.assertEqual(self.s.migrations.SCHEMA_VERSION,14)
        self.assertEqual(self.c.get('/api/training/sessions?limit=51',headers=self.headers).status_code,400)
        c=self.s.get_db();training.migrate(c);training.migrate(c);c.close()
    def test_z_template_quota_does_not_consume_existing_retry(self):
        c=self.s.get_db();n=c.execute('SELECT COUNT(*) FROM training_templates WHERE user_id=? AND deleted=0',(self.a,)).fetchone()[0];c.close();last=None
        for _ in range(50-n):
            last={k:v for k,v in self.payload().items() if k in ['title','scene','exercises','request_id']};self.assertEqual(self.c.post('/api/training/templates',headers=self.headers,json=last).status_code,200)
        if last:self.assertEqual(self.c.post('/api/training/templates',headers=self.headers,json=last).status_code,200)
        last={k:v for k,v in self.payload().items() if k in ['title','scene','exercises','request_id']};self.assertEqual(self.c.post('/api/training/templates',headers=self.headers,json=last).status_code,400)

if __name__=='__main__':unittest.main()
