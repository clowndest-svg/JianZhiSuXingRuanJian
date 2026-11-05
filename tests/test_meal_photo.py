"""Real HTTP provider, API/SQLite and bounded image contracts; isolated data only."""
import copy,importlib.util,io,json,sys,threading,unittest,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
from pydantic import ValidationError
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('meal_fixture',Path(__file__).with_name('test_bubble_themes.py'));fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from app_modules import meal_photo as mp

RICE={'name':'米饭','grams':200,'kcal100':130,'protein100':2.7,'carbs100':28,'fat100':.3}
CHICKEN={'name':'鸡胸肉','grams':150,'kcal100':165,'protein100':31,'carbs100':0,'fat100':3.6}

class PhotoMeals(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixture.BubbleThemes.setUpClass.__func__(cls)
  cls.peer={**cls.headers,'Authorization':'Bearer '+cls.users[1]['token']}
  out=io.BytesIO();Image.new('RGB',(64,48),'orange').save(out,format='JPEG');cls.photo=out.getvalue()
  cls.provider_response={'food_name':'米饭鸡肉','components':[RICE,CHICKEN]};cls.requests=[]
  class Provider(BaseHTTPRequestHandler):
   def do_POST(self):
    cls.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
    b=json.dumps({'choices':[{'message':{'content':cls.provider_response if isinstance(cls.provider_response,str) else json.dumps(cls.provider_response,ensure_ascii=False)}}]}).encode()
    self.send_response(200);self.end_headers();self.wfile.write(b)
   def log_message(self,*args):pass
  cls.http=ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=cls.http.serve_forever,daemon=True).start();cls.addClassCleanup(cls.http.server_close);cls.addClassCleanup(cls.http.shutdown)
  cls.cfg={'local':False,'enabled':True,'model':'fixture','api_key':'fixture-secret','base_url':'http://127.0.0.1:'+str(cls.http.server_port)+'/v1'}
 def setUp(self):
  self.__class__.provider_response={'food_name':'米饭鸡肉','components':[RICE,CHICKEN]}
 def count(self):
  c=self.s.get_db();n=c.execute('SELECT COUNT(*) FROM food_logs').fetchone()[0];c.close();return n
 def payload(self,**kw):
  return dict({'food_name':'米饭鸡肉','slot':'午餐','components':[copy.deepcopy(RICE),copy.deepcopy(CHICKEN)],'request_id':str(uuid.uuid4())},**kw)
 def recognize(self,raw=None,consent='true',headers=None):
  return self.c.post('/api/food/vision/recognize',headers=headers or self.headers,data={'consent':consent,'mode':'external','config_revision':mp.identity(self.cfg)},files={'photo':('food.jpg',raw if raw is not None else self.photo,'image/jpeg')})
 def test_auth_consent_unconfigured_and_no_write(self):
  self.assertEqual(self.c.get('/api/food/vision/status').status_code,401)
  with patch.object(mp,'read_config',return_value=None):
   self.assertFalse(self.c.get('/api/food/vision/status',headers=self.headers).json()['configured'])
   self.assertEqual(self.recognize().status_code,503)
   self.assertEqual(self.recognize(consent='false').status_code,400)
 def test_real_provider_validated_and_photo_not_saved(self):
  before=self.count();files=set(Path(self.s.UPLOAD_DIR).iterdir())
  with patch.object(mp,'read_config',return_value=self.cfg):r=self.recognize()
  self.assertEqual(r.status_code,200,r.text);x=r.json();self.assertEqual(x['totals']['cal'],508);self.assertEqual(x['totals']['protein_g'],51.9);self.assertIsNone(x['totals']['health_score']);self.assertIsNone(x['totals']['glycemic_load'])
  self.assertEqual(self.count(),before);self.assertEqual(set(Path(self.s.UPLOAD_DIR).iterdir()),files)
  sent=self.requests[-1];self.assertEqual(len(sent['messages']),1);self.assertNotIn(self.users[0]['token'],json.dumps(sent));self.assertTrue(sent['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
 def test_bad_image_size_format_and_pixels(self):
  with patch.object(mp,'read_config',return_value=self.cfg):
   self.assertEqual(self.recognize(b'not-image').status_code,400)
   self.assertEqual(self.recognize(b'x'*(8*1024*1024+1)).status_code,413)
   o=io.BytesIO();Image.new('1',(5000,5000)).save(o,format='PNG');self.assertEqual(self.recognize(o.getvalue()).status_code,400)
 def test_model_bad_json_nonfood_invalid_numbers_rejected(self):
  for result in ['plain caption',{'food_name':'','components':[]},{'food_name':'x','components':[{**RICE,'grams':-1}]},{'food_name':'x','components':[{**RICE,'protein100':99,'fat100':99}]},{'food_name':'x','components':[{**RICE,'gi':50}]}]:
   self.__class__.provider_response=result
   with patch.object(mp,'read_config',return_value=self.cfg):r=self.recognize()
   self.assertEqual(r.status_code,502,r.text)
 def test_confirm_recomputes_idempotently_and_private_history(self):
  p=self.payload();before=self.count();r=self.c.post('/api/food/log',headers=self.headers,json=p);self.assertEqual(r.status_code,200,r.text);sid=r.json()['record_id'];self.assertEqual(r.json()['cal'],508)
  self.assertTrue(self.c.post('/api/food/log',headers=self.headers,json=p).json()['duplicate']);self.assertEqual(self.count(),before+1)
  rows=self.c.get('/api/records?kind=food',headers=self.headers).json()['rows'];row=next(x for x in rows if x['id']==sid);self.assertEqual(json.loads(row['components_json'])[0]['grams'],200);self.assertEqual(row['source'],'meal_components')
  other=self.c.get('/api/records?kind=food',headers=self.peer).json()['rows'];self.assertNotIn(sid,[x['id'] for x in other])
  self.assertEqual(self.c.post('/api/records/food/'+str(sid)+'/update',headers=self.peer,json={'components':[RICE]}).status_code,404)
 def test_edit_components_then_manual_clear_then_delete(self):
  r=self.c.post('/api/food/log',headers=self.headers,json=self.payload());sid=r.json()['record_id'];url='/api/records/food/'+str(sid)
  r=self.c.post(url+'/update',headers=self.headers,json={'components':[{**RICE,'grams':100}]});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['day_before']['consumed_cal']-r.json()['day_after']['consumed_cal'],378)
  r=self.c.post(url+'/update',headers=self.headers,json={'cal':333});self.assertEqual(r.status_code,200)
  c=self.s.get_db();row=c.execute('SELECT * FROM food_logs WHERE id=?',(sid,)).fetchone();self.assertIsNone(row['components_json']);self.assertEqual(row['protein_g'],0);c.close()
  self.assertEqual(self.c.post(url+'/delete',headers=self.headers,json={}).status_code,200)
 def test_unknown_macros_gl_and_bounds(self):
  unknown={'name':'包装食物','grams':100,'kcal100':123};self.assertIsNone(mp.summarize([unknown])['protein_g']);self.assertEqual(mp.summarize([{**RICE,'gi':50,'available_carbs100':28,'gi_source':'Synthetic GI fixture'}])['glycemic_load'],28)
  for bad in [{**RICE,'grams':float('nan')},{**RICE,'protein100':None},{**RICE,'gi':0},{**RICE,'name':'   '}]:
   with self.assertRaises(ValidationError):mp.Component.model_validate(bad)
  for p in [self.payload(cal=500),self.payload(components=[{**RICE,'grams':4000},{**RICE,'grams':4000}]),self.payload(components=[])]:
   self.assertEqual(self.c.post('/api/food/log',headers=self.headers,json=p).status_code,422)
 def test_legacy_logging_and_new_schema(self):
  r=self.c.post('/api/food/log',headers=self.headers,json={'food_name':'米饭','slot':'午餐','cal':234});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['cal'],234);self.assertEqual(r.json()['protein_g'],0)
  c=self.s.get_db();self.assertEqual(c.execute('SELECT version FROM schema_version').fetchone()[0],16);self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[]);c.close()
 def test_local_caption_uses_reference_not_model_numbers(self):
  rows=mp.local_components('A plate of rice and chicken breast. 9999 kcal, 5000 grams.')
  self.assertEqual(len(rows),2);self.assertTrue(all(x.grams==100 for x in rows));self.assertEqual(mp.summarize(rows)['cal'],295);self.assertTrue(all(x.reference.startswith('USDA') for x in rows))
  with self.assertRaises(ValueError):mp.local_components('A car on the road, no food.')
  with patch.object(mp,'read_config',return_value={**self.cfg,'local':True}):self.assertEqual(self.recognize().status_code,409)

if __name__=='__main__':unittest.main()
