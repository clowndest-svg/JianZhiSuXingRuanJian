"""Authorized deployment smoke test; cleans only the uniquely named fixture users."""
import json,urllib.request,urllib.error,secrets,sqlite3,os
base=os.environ.get('QINGSU_VERIFY_BASE','http://172.17.0.1:8000')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
username='releasecheck_'+secrets.token_hex(5)
# 抬门之后，不带构建号的调用方和旧包长得一样，会被一起挡掉——发布自检必须扮成最新版
with opener.open(base+'/version.json',timeout=15) as response:
    build=str(json.load(response).get('version_code') or 0)
assert build!='0','线上清单没有 version_code，自检无法冒充现行客户端'
def _user_refs(conn):
    """所有指向 users 的 (表, 列)。社区那批表里 follows/messages/user_blocks 的列名
    都不叫 user_id，写死一张旧清单就会"删不掉"或者留孤儿行——改成从外键定义现读。"""
    out = []
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for table in names:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        fks = {fk[3] for fk in conn.execute("PRAGMA foreign_key_list(%s)" % table).fetchall()
               if fk[2] == "users"}
        wanted = fks | {c for c in cols if c in (
            "user_id", "follower_id", "followee_id", "from_id", "to_id", "blocker",
            "blocked", "reporter", "actor_id", "a_id", "b_id", "last_from")}
        out += [(table, c) for c in sorted(wanted)]
    return out


def api(path,body=None,token=None,build_no=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-App-Build':str(build_no or build),**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with opener.open(req,timeout=15) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as e:return e.code,json.load(e)

def new_code(email,purpose='register'):
    """自检自己签发一枚验证码：它本来就有目标库路径，不需要真的发信。
    这样注册路径走的是真实的"邮箱验证码"校验，而不是绕过它。"""
    import sys
    from pathlib import Path
    db=Path(os.environ.get('QINGSU_VERIFY_DB','/opt/qingsu/data/qingsu.db')).resolve()
    for candidate in (Path(__file__).resolve().parents[1],db.parent.parent,Path('/opt/qingsu')):
        if (candidate/'server.py').is_file():
            sys.path.insert(0,str(candidate))
            break
    else:
        raise SystemExit('server.py not found for code provisioning')
    import server as srv
    conn=sqlite3.connect(str(db))
    try:
        conn.row_factory=sqlite3.Row
        return srv._issue_email_code(conn,email,purpose)
    finally:conn.close()

checks=[]
try:
    email=username+'@releasecheck.invalid'
    body=dict(username=username,password=secrets.token_urlsafe(24),age=30,height=170,weight_jin=160,target_weight_jin=140,
              email=email,email_code=new_code(email))
    status,signup=api('/api/register',body);assert status==200,signup
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
    summary=api('/api/summary?days=30',token=token)
    assert summary[0]==200 and summary[1]['days']==30 and summary[1]['workout_days']==1
    checks.append('private 30-day summary')
    status,goal=api('/api/goals',dict(title='Release verification',kind='workout',target=3,days=7),token)
    assert status==200 and goal.get('invite')
    goals=api('/api/goals',token=token)[1]['items'];assert len(goals)==1 and goals[0]['members'][0]['days']==1
    assert api('/api/goals/'+str(goal['id'])+'/leave',{},token)[0]==200
    checks.append('shared goal creation, real progress and removal')
    assert isinstance(api('/api/push/config',token=token)[1]['available'],bool)
    with opener.open(base+'/about',timeout=15) as response:assert response.status==200
    checks.append('push capability and public guide')
    assert api('/api/logout',{},token)[0]==200 and api('/api/dashboard',token=token)[0]==401
    assert api('/api/dashboard',token=login['token'])[0]==200;checks.append('session revocation')
    with opener.open(base+'/health/ready',timeout=15) as response:ready=json.load(response)
    # 门开没开必须落在发布记录里：抬不动门最坏的形状是"以为生效了"
    assert 'min_build' in ready and 'gate' in ready,'健康检查没上报强更门状态'
    checks.append('update gate min_build=%s override=%s blocked=%s'%(ready['min_build'],ready['build_override'],ready['gate']['blocked']))
    # 新版注册必须带邮箱验证码（只在邮件通道在线时强制；没接好时服务端会降级，不在这里判红）
    mail_state=api('/api/account/recovery-status')[1].get('mail')
    if mail_state=='up':
        status,gate=api('/api/register',dict(username=username+'_gate',password=secrets.token_urlsafe(16),age=30,height=170,weight_jin=160,target_weight_jin=140))
        assert status==400 and '邮箱' in str(gate.get('detail','')),gate
        checks.append('new-client registration requires an email code')
    print(json.dumps({'passed':checks},ensure_ascii=False))
finally:
    db=sqlite3.connect(os.environ.get('QINGSU_VERIFY_DB','/opt/qingsu/data/qingsu.db'));db.execute('PRAGMA foreign_keys=ON')
    ids=[r[0] for r in db.execute('SELECT id FROM users WHERE username=?',(username,))]
    for uid in ids:
        # 表清单不能写死：社区那批表里 follows/messages/user_blocks 用的列名都不是 user_id，
        # 漏一张就是"删不掉"或者留孤儿行。改成从外键定义现读。
        for table, col in _user_refs(db):
            try:
                db.execute('DELETE FROM %s WHERE %s=?' % (table, col), (uid,))
            except sqlite3.OperationalError:
                pass
        db.execute('DELETE FROM users WHERE id=?',(uid,))
    db.commit();print('remaining_users='+str(db.execute('SELECT COUNT(*) FROM users').fetchone()[0]));db.close()

# Candidate and production both enter through this script, including gateways
# installed before r164. Keep the real media smoke behind the same rollback gate.
from pathlib import Path
import subprocess,sys
subprocess.run([sys.executable, str(Path(__file__).with_name('verify-chat-media-live.py'))], check=True)
