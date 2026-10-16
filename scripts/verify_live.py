"""Authorized deployment smoke test; cleans only the uniquely named fixture users."""
import json,urllib.request,urllib.error,secrets,sqlite3,os
base=os.environ.get('QINGSU_VERIFY_BASE','http://172.17.0.1:8000')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
username='releasecheck_'+secrets.token_hex(5)
def api(path,body=None,token=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with opener.open(req,timeout=15) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
checks=[]
try:
    body=dict(username=username,password=secrets.token_urlsafe(24),age=30,height=170,weight_jin=160,target_weight_jin=140)
    status,signup=api('/api/register',body);assert status==200
    token=signup['token']
    status,login=api('/api/login',dict(username=username,password=body['password']));assert status==200
    assert api('/api/dashboard',token=token)[0]==200;checks.append('two simultaneous sessions')
    d=api('/api/dashboard',token=token)[1]
    assert d['cycle_day']==1 and d['consecutive_slacking_days']==0
    assert '?k=' in d['public_url'];checks.append('fresh account and share URL')
    key=signup['public_url'].split('?k=')[1]
    assert api('/api/public/dashboard?username='+username+'&k='+key)[0]==200
    assert api('/api/public/dashboard?username='+username)[0]==404;checks.append('share access boundary')
    assert api('/api/weight/log',dict(weight_jin=150),token)[0]==200
    assert api('/api/charts',token=token)[1]['weight_history'][-1]['jin']==150;checks.append('latest daily weight')
    for _ in range(2):assert api('/api/workout/complete',dict(request_id='smoke-workout'),token)[0]==200
    assert api('/api/dashboard',token=token)[1]['today_burned']==220;checks.append('idempotent workout')
    assert api('/api/checklist',dict(state={'test':True}),token)[0]==200
    assert api('/api/dashboard',token=token)[1]['checklist']['test'];checks.append('checklist persistence')
    assert api('/api/logout',{},token)[0]==200 and api('/api/dashboard',token=token)[0]==401
    assert api('/api/dashboard',token=login['token'])[0]==200;checks.append('session revocation')
    print(json.dumps({'passed':checks},ensure_ascii=False))
finally:
    db=sqlite3.connect(os.environ.get('QINGSU_VERIFY_DB','/opt/qingsu/data/qingsu.db'));db.execute('PRAGMA foreign_keys=ON')
    ids=[r[0] for r in db.execute('SELECT id FROM users WHERE username=?',(username,))]
    for uid in ids:
        for table in ('sessions','profiles','food_logs','weight_logs','workout_logs','water_logs','body_cycles','takeout_events','checklist_state','ai_memory','cheers','private_ai_answers','daily_modes','request_receipts','daily_metrics','record_changes','share_settings','daily_reviews'):
            db.execute('DELETE FROM '+table+' WHERE user_id=?',(uid,))
        db.execute('DELETE FROM users WHERE id=?',(uid,))
    db.commit();print('remaining_users='+str(db.execute('SELECT COUNT(*) FROM users').fetchone()[0]));db.close()
