"""Read-only source audit with writes confined to a new local fixture database."""
import sys, json, types, shutil, hashlib, zipfile, time
from pathlib import Path
from datetime import date, timedelta
ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'server.py').is_file())
BASE = ROOT / '_audit_sandbox/review-20261016'
sys.path.insert(0, str(BASE / 'deps'))
from fastapi.testclient import TestClient

def load():
    run = BASE / ('real-' + str(time.time_ns()))
    src = (ROOT / 'server.py').read_text(encoding='utf-8')
    for kind in ('data', 'uploads', 'web'):
        dest = run / kind
        dest.mkdir(parents=True, exist_ok=True)
        src = src.replace('"/opt/qingsu/' + kind + '"', repr(str(dest)))
    for p in (ROOT / 'app/src/main/assets').iterdir():
        if p.is_file(): shutil.copy2(p, run / 'web' / p.name)
    shutil.copy2(ROOT / 'app/src/main/web_version.json', run / 'web/version.json')
    mod = types.ModuleType('audit_real_server')
    mod.__file__ = str(ROOT / 'server.py')
    exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
    # External model/search/Redis are explicitly excluded from the local probe.
    mod._redis_cmd = lambda *a, **k: (False, None)
    mod.web_search = lambda *a, **k: []
    mod.llm_chat = lambda *a, **k: None
    return mod, run

m, run = load()
client = TestClient(m.app, raise_server_exceptions=False)
results = {'scope': 'real FastAPI/Pydantic/Starlette/SQLite; external Redis/model/search disabled', 'fixture': str(run)}
body = dict(username='audit_owner', password='ReviewOnly!123', age=30, height=170, weight_jin=160, target_weight_jin=140)
r = client.post('/api/register', json=body)
assert r.status_code == 200, r.text
signup = r.json()
old = {'Authorization': 'Bearer ' + signup['token']}
r = client.post('/api/login', json={'username': body['username'], 'password': body['password']})
auth = {'Authorization': 'Bearer ' + r.json()['token']}
results['multi_device'] = {'first_session_status': client.get('/api/dashboard', headers=old).status_code, 'second_session_status': client.get('/api/dashboard', headers=auth).status_code}
d = client.get('/api/dashboard', headers=auth).json()
results['fresh_account'] = {'cycle_day': d['cycle_day'], 'slacking_days': d['consecutive_slacking_days'], 'dashboard_share_has_key': '?k=' in d['public_url'], 'registration_share_has_key': '?k=' in signup['public_url'], 'water_target_ml': d['water_target_ml']}
client.post('/api/weight/log', headers=auth, json={'weight_jin': 150})
d = client.get('/api/dashboard', headers=auth).json()
ch = client.get('/api/charts', headers=auth).json()
results['same_day_weight'] = {'dashboard_jin': d['current_weight_jin'], 'chart_jin': ch['weight_history'][-1]['jin']}
client.post('/api/workout/complete', headers=auth, json={})
client.post('/api/workout/complete', headers=auth, json={})
d = client.get('/api/dashboard', headers=auth).json()
results['duplicate_workout'] = {'burned': d['today_burned'], 'done': d['today_workout_done']}
conn = m.get_db()
conn.execute('UPDATE workout_logs SET log_date=?', ((date.today()-timedelta(days=1)).isoformat(),))
conn.commit(); conn.close()
d = client.get('/api/dashboard', headers=auth).json()
results['day_mode_carryover'] = {'today_workout_done': d['today_workout_done'], 'day_mode': d['day_mode']}
# A harmless HTML marker tests type acceptance and unauthenticated delivery, with no script execution.
r = client.post('/api/cycle/upgrade', headers=auth, data={'weight_jin':150,'waist_cm':80}, files={'photo':('audit-marker.html',b'<h1>audit harmless upload marker</h1>','text/html')})
up = r.json()
anonymous = client.get(up['photo_url']) if r.status_code == 200 else None
results['upload_boundary'] = {'upload_status':r.status_code, 'anonymous_get_status':anonymous.status_code if anonymous is not None else None, 'content_type':anonymous.headers.get('content-type') if anonymous is not None else None}
# Global knowledge isolation: two disposable users, unique harmless text.
client.post('/api/ai/record', headers=auth, json={'question':'糙米和白米差在哪','answer':'AUDIT_PRIVATE_MARKER user-specific test context','sources':[]})
other = dict(body, username='audit_reader')
ot = client.post('/api/register', json=other).json()['token']
oa = {'Authorization':'Bearer ' + ot}
ctx = client.get('/api/ai/context', headers=oa).json()
reply = client.post('/api/ask', headers=oa, json={'question':'糙米和白米差在哪'}).json()
results['global_knowledge'] = {'other_context_contains_marker':'AUDIT_PRIVATE_MARKER' in json.dumps(ctx), 'other_answer_contains_marker':'AUDIT_PRIVATE_MARKER' in json.dumps(reply), 'source':reply.get('source')}
results['knowledge_key_collision'] = {'queries':['黑咖啡有什么优点','黑咖啡有什么风险'], 'same_key':m._qkey('黑咖啡有什么优点') == m._qkey('黑咖啡有什么风险')}
client.post('/api/food/log',headers=auth,json={'slot':'早餐','food_name':'review fixture','cal':500})
conn=m.get_db();conn.execute('UPDATE food_logs SET log_date=?',((date.today()-timedelta(days=1)).isoformat(),));conn.commit();conn.close()
before=client.get('/api/charts',headers=auth).json()['deficit_history'][-2]['deficit']
client.post('/api/profile/update',headers=auth,json={'height':190})
after=client.get('/api/charts',headers=auth).json()['deficit_history'][-2]['deficit']
results['historical_metric_drift']={'yesterday_before':before,'yesterday_after_height_change':after}
bad = {}
for name, path, payload in [('negative_food','/api/food/log',{'slot':'早餐','food_name':'review','cal':-500}),('negative_weight','/api/weight/log',{'weight_jin':-1}),('negative_workout','/api/workout/complete',{'duration_minutes':-10,'cal_burned':-100})]:
    rr = client.post(path, headers=oa, json=payload)
    bad[name] = rr.status_code
bad['empty_credentials'] = client.post('/api/register', json=dict(body, username='',password='')).status_code
results['input_validation'] = bad
# Existing login failure counters should reset after a successful login.
failures = [client.post('/api/login',json={'username':body['username'],'password':'wrong'}).status_code for _ in range(4)]
good = client.post('/api/login',json={'username':body['username'],'password':body['password']}).status_code
client.post('/api/login',json={'username':body['username'],'password':'wrong'})
next_good = client.post('/api/login',json={'username':body['username'],'password':body['password']}).status_code
results['login_counter_reset'] = {'four_wrong':failures, 'good':good, 'good_after_one_more_wrong':next_good}
conn = m.get_db()
results['sqlite'] = {'journal_mode':conn.execute('PRAGMA journal_mode').fetchone()[0], 'foreign_keys':conn.execute('PRAGMA foreign_keys').fetchone()[0], 'food_indexes':[list(x) for x in conn.execute('PRAGMA index_list(food_logs)')]}
conn.close()
results['apk_assets'] = {}
with zipfile.ZipFile(ROOT / 'qingsu.apk') as z:
    for name in ['app.js','index.html','style.css','exercise_poses.json']:
        results['apk_assets'][name] = z.read('assets/' + name) == (ROOT / 'app/src/main/assets' / name).read_bytes()
results['packages'] = {}
import importlib.metadata
for name in ['fastapi','starlette','pydantic','httpx','uvicorn']:
    results['packages'][name] = importlib.metadata.version(name)
(BASE / 'api-findings.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(results, ensure_ascii=False, indent=2))
# Create a clean fixture server for UI review, independent of invalid-data API probes.
if '--serve' in sys.argv:
    m, run = load()
    c = TestClient(m.app)
    account = c.post('/api/register',json=dict(body, username='ui_review')).json()
    # Only local fixture metadata is saved; no production credentials used.
    (BASE / 'ui-fixture.json').write_text(json.dumps({'username':'ui_review','password':body['password'],'share_path':account['public_url'].split('124.220.54.64',1)[1]},ensure_ascii=False),encoding='utf-8')
    print('UI_SERVER http://localhost:8765', flush=True)
    import uvicorn
    uvicorn.run(m.app, host='127.0.0.1', port=8765, log_level='warning')
