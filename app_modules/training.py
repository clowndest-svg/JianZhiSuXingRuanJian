"""Private training notebook, reusable templates, calendar and factual progress.
No inference, background jobs or automatic load prescriptions.
"""
import calendar,csv,hashlib,io,json,unicodedata
from datetime import date,datetime,timedelta
from typing import Literal
from fastapi import Depends,HTTPException,Query
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,model_validator

class SetEntry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reps:int|None=Field(default=None,ge=1,le=500)
    weight_kg:float|None=Field(default=None,ge=0,le=500,allow_inf_nan=False)
    seconds:int|None=Field(default=None,ge=1,le=7200)
    done:bool=False
class Exercise(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=60)
    kind:Literal['reps','time']='reps'
    sets:list[SetEntry]=Field(min_length=1,max_length=12)
    @model_validator(mode='after')
    def clean(self):
        self.name=' '.join(self.name.split())
        if not self.name:raise ValueError('动作名称不能为空')
        for s in self.sets:
            if s.done and ((self.kind=='reps' and s.reps is None) or (self.kind=='time' and s.seconds is None)):
                raise ValueError('完成的组需要填写实际次数或秒数')
            if self.kind=='time':s.reps=None;s.weight_kg=None
            else:s.seconds=None
        return self
class Content(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=60)
    scene:Literal['home','band','gym','cardio','custom']='custom'
    exercises:list[Exercise]=Field(min_length=1,max_length=12)
    @model_validator(mode='after')
    def clean(self):
        self.title=self.title.strip()
        if not self.title:raise ValueError('名称不能为空')
        return self
class Session(Content):
    day:date
    status:Literal['planned','completed']='planned'
    minutes:int=Field(default=0,ge=0,le=600)
    energy:float=Field(default=0,ge=0,le=5000,allow_inf_nan=False)
    effort:float|None=Field(default=None,ge=1,le=10,allow_inf_nan=False)
    note:str=Field(default='',max_length=500)
    request_id:str=Field(min_length=1,max_length=96)
    expected_version:int=Field(default=0,ge=0)
    @model_validator(mode='after')
    def complete(self):
        if self.status=='completed' and (self.minutes<1 or not any(s.done for e in self.exercises for s in e.sets)):
            raise ValueError('完成训练需要实际时长和至少一组已完成记录')
        return self
class Template(Content):
    request_id:str=Field(min_length=1,max_length=96)
    expected_version:int=Field(default=0,ge=0)
class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(ge=0)

def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS training_sessions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,
      day TEXT NOT NULL,title TEXT NOT NULL,scene TEXT NOT NULL,status TEXT NOT NULL,
      minutes INTEGER NOT NULL,energy REAL NOT NULL,effort REAL,note TEXT NOT NULL,exercises_json TEXT NOT NULL,
      workout_log_id INTEGER UNIQUE REFERENCES workout_logs(id) ON DELETE SET NULL,
      deleted INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(user_id,request_id));
    CREATE INDEX IF NOT EXISTS idx_training_sessions_user_day ON training_sessions(user_id,deleted,day,id);
    CREATE TABLE IF NOT EXISTS training_sets(
      session_id INTEGER NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,position INTEGER NOT NULL,
      exercise_key TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,reps INTEGER,weight_kg REAL,seconds INTEGER,done INTEGER NOT NULL,
      PRIMARY KEY(session_id,position));
    CREATE INDEX IF NOT EXISTS idx_training_sets_user_action ON training_sets(user_id,exercise_key,kind,session_id);
    CREATE TABLE IF NOT EXISTS training_templates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,title TEXT NOT NULL,scene TEXT NOT NULL,exercises_json TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
      UNIQUE(user_id,request_id));
    ''')

def key(name):return unicodedata.normalize('NFKC',' '.join(name.split())).casefold()
def packed(req,template=False):
    ex=[e.model_dump() for e in req.exercises]
    if template:
        for e in ex:
            for s in e['sets']:s['done']=False
    return json.dumps(ex,ensure_ascii=False,separators=(',',':'))
def digest(req):
    return hashlib.sha256(json.dumps(req.model_dump(mode='json',exclude={'request_id','expected_version'}),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def owned(c,table,uid,rid):
    r=c.execute('SELECT * FROM '+table+' WHERE id=? AND user_id=? AND deleted=0',(rid,uid)).fetchone()
    if not r:raise HTTPException(404,'记录不存在或已删除')
    return r
def item(r,details=True):
    d={k:r[k] for k in ['id','title','scene','version','created_at','updated_at']}
    if 'day' in r.keys():
        d.update({k:r[k] for k in ['day','status','minutes','energy','effort','note']})
        d['counted']=r['workout_log_id'] is not None
    if details:d['exercises']=json.loads(r['exercises_json'])
    return d
def check_day(req,user):
    start=date.fromisoformat(str(user['created_at'])[:10]);end=date.today()+(timedelta(days=365) if req.status=='planned' else timedelta())
    if not start<=req.day<=end:raise HTTPException(400,'完成日期须在注册日至今天；计划最多安排未来一年')
def index_sets(c,uid,sid,req):
    c.execute('DELETE FROM training_sets WHERE session_id=?',(sid,));rows=[]
    for ei,e in enumerate(req.exercises):
        for si,s in enumerate(e.sets):rows.append((sid,uid,ei*12+si,key(e.name),e.name,e.kind,s.reps,s.weight_kg,s.seconds,int(s.done)))
    c.executemany('INSERT INTO training_sets VALUES (?,?,?,?,?,?,?,?,?,?)',rows)
def invalidate(c,uid,*days):
    for day in set(days):c.execute('DELETE FROM daily_reviews WHERE user_id=? AND log_date=?',(uid,day))
def sync_summary(api,c,uid,req,old=None):
    link=old['workout_log_id'] if old else None
    if req.status!='completed':return None
    api['snapshot_metrics'](c,uid);stamp=api['_now']()
    if old and old['status']=='completed':
        # A removed summary is never silently recreated.
        if link:
            row=c.execute('SELECT * FROM workout_logs WHERE id=? AND user_id=?',(link,uid)).fetchone()
            if row:
                c.execute('INSERT INTO record_changes(user_id,kind,record_id,previous_json,operation,created_at) VALUES (?,?,?,?,?,?)',(uid,'workout',link,json.dumps(dict(row),ensure_ascii=False),'update',stamp))
                c.execute('UPDATE workout_logs SET log_date=?,duration_minutes=?,cal_burned=?,plan_name=?,occurred_at=NULL,timezone_offset_minutes=NULL WHERE id=? AND user_id=?',(req.day.isoformat(),req.minutes,req.energy,req.title,link,uid))
    else:
        link=c.execute('INSERT INTO workout_logs(user_id,log_date,duration_minutes,cal_burned,plan_name,created_at) VALUES (?,?,?,?,?,?)',(uid,req.day.isoformat(),req.minutes,req.energy,req.title,stamp)).lastrowid
    if link:c.execute("INSERT INTO daily_modes VALUES (?,?,'workout') ON CONFLICT(user_id,log_date) DO UPDATE SET mode='workout'",(uid,req.day.isoformat()))
    invalidate(c,uid,req.day.isoformat(),old['day'] if old else req.day.isoformat());return link

def install(app,api):
    auth=api['get_current_user'];db=api['get_db']
    def write_budget(user):
        if not api['rate_hit']('training-write:'+str(user['id']),60,60)[0]:raise HTTPException(429,'保存太频繁，请稍后重试')
    @app.get('/api/training/sessions')
    def sessions(cursor:int=0,limit:int=20,day:str='',status:str='',user:dict=Depends(auth)):
        if cursor<0 or not 1<=limit<=50 or status not in ('','planned','completed'):raise HTTPException(400,'分页或筛选无效')
        sql='SELECT * FROM training_sessions WHERE user_id=? AND deleted=0';args=[user['id']]
        if cursor:sql+=' AND id<?';args.append(cursor)
        if day:
            try:date.fromisoformat(day)
            except ValueError:raise HTTPException(400,'日期无效')
            sql+=' AND day=?';args.append(day)
        if status:sql+=' AND status=?';args.append(status)
        c=db()
        try:r=c.execute(sql+' ORDER BY id DESC LIMIT ?',(*args,limit+1)).fetchall()
        finally:c.close()
        return {'code':0,'items':[item(x,False) for x in r[:limit]],'more':len(r)>limit,'next_cursor':r[limit-1]['id'] if len(r)>limit else 0,'today':date.today().isoformat(),'joined_day':str(user['created_at'])[:10],'me_id':int(user['id'])}
    @app.get('/api/training/sessions/{sid}')
    def detail(sid:int,user:dict=Depends(auth)):
        c=db()
        try:return {'code':0,'item':item(owned(c,'training_sessions',user['id'],sid))}
        finally:c.close()
    @app.post('/api/training/sessions')
    def create(req:Session,user:dict=Depends(auth)):
        write_budget(user);check_day(req,user);uid=user['id'];c=db();h=digest(req)
        try:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM training_sessions WHERE user_id=? AND request_id=?',(uid,req.request_id)).fetchone()
            if old:
                if old['deleted'] or old['payload_hash']!=h:raise HTTPException(409,'这个草稿已保存或删除，请重新打开云端记录后再修改')
                return {'code':0,'item':item(old),'duplicate':True}
            stamp=api['_now']();link=sync_summary(api,c,uid,req)
            sid=c.execute('INSERT INTO training_sessions(user_id,request_id,payload_hash,day,title,scene,status,minutes,energy,effort,note,exercises_json,workout_log_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid,req.request_id,h,req.day.isoformat(),req.title,req.scene,req.status,req.minutes,req.energy,req.effort,req.note,packed(req),link,stamp,stamp)).lastrowid
            index_sets(c,uid,sid,req);c.commit();return {'code':0,'item':item(owned(c,'training_sessions',uid,sid)),'duplicate':False}
        finally:c.close()
    @app.put('/api/training/sessions/{sid}')
    def update(sid:int,req:Session,user:dict=Depends(auth)):
        write_budget(user);check_day(req,user);uid=user['id'];c=db()
        try:
            c.execute('BEGIN IMMEDIATE');old=owned(c,'training_sessions',uid,sid)
            if old['version']!=req.expected_version:raise HTTPException(409,'记录已被其他设备修改，请重新打开；本机草稿仍会保留')
            if old['status']=='completed' and req.status!='completed':raise HTTPException(400,'已完成记录可以更正或删除；要安排新计划请复制一份')
            link=sync_summary(api,c,uid,req,old)
            c.execute('UPDATE training_sessions SET day=?,title=?,scene=?,status=?,minutes=?,energy=?,effort=?,note=?,exercises_json=?,workout_log_id=?,version=version+1,updated_at=? WHERE id=? AND user_id=?',(req.day.isoformat(),req.title,req.scene,req.status,req.minutes,req.energy,req.effort,req.note,packed(req),link,api['_now'](),sid,uid))
            index_sets(c,uid,sid,req);c.commit();return {'code':0,'item':item(owned(c,'training_sessions',uid,sid))}
        finally:c.close()
    @app.post('/api/training/sessions/{sid}/delete')
    def delete(sid:int,req:Revision,user:dict=Depends(auth)):
        write_budget(user);uid=user['id'];c=db()
        try:
            c.execute('BEGIN IMMEDIATE');r=owned(c,'training_sessions',uid,sid)
            if r['version']!=req.expected_version:raise HTTPException(409,'记录已变更，请重新打开后删除')
            if r['workout_log_id']:
                row=c.execute('SELECT * FROM workout_logs WHERE id=? AND user_id=?',(r['workout_log_id'],uid)).fetchone()
                if row:c.execute('INSERT INTO record_changes(user_id,kind,record_id,previous_json,operation,created_at) VALUES (?,?,?,?,?,?)',(uid,'workout',r['workout_log_id'],json.dumps(dict(row),ensure_ascii=False),'delete',api['_now']()))
                c.execute('DELETE FROM workout_logs WHERE id=? AND user_id=?',(r['workout_log_id'],uid))
            c.execute('DELETE FROM training_sets WHERE session_id=?',(sid,));c.execute("UPDATE training_sessions SET deleted=1,title='',note='',exercises_json='[]',minutes=0,energy=0,effort=NULL,workout_log_id=NULL,version=version+1,updated_at=? WHERE id=?",(api['_now'](),sid));invalidate(c,uid,r['day']);c.commit()
            return {'code':0}
        finally:c.close()
    @app.get('/api/training/calendar')
    def month(month:str=Query(pattern=r'^\d{4}-\d{2}$'),user:dict=Depends(auth)):
        try:start=date.fromisoformat(month+'-01');end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        except ValueError:raise HTTPException(400,'月份无效')
        c=db()
        try:rows=c.execute("SELECT day,SUM(status='planned') AS planned,SUM(status='completed') AS completed,SUM(CASE WHEN status='completed' THEN minutes ELSE 0 END) AS minutes FROM training_sessions WHERE user_id=? AND deleted=0 AND day BETWEEN ? AND ? GROUP BY day",(user['id'],start.isoformat(),end.isoformat())).fetchall()
        finally:c.close()
        return {'code':0,'month':month,'days':[dict(r) for r in rows],'today':date.today().isoformat()}
    @app.get('/api/training/templates')
    def templates(user:dict=Depends(auth)):
        c=db()
        try:return {'code':0,'items':[item(r) for r in c.execute('SELECT * FROM training_templates WHERE user_id=? AND deleted=0 ORDER BY id DESC LIMIT 50',(user['id'],))]}
        finally:c.close()
    def save_template(req,user,tid=None):
        write_budget(user);uid=user['id'];c=db();h=digest(req);stamp=api['_now']()
        try:
            c.execute('BEGIN IMMEDIATE')
            if tid:
                old=owned(c,'training_templates',uid,tid)
                if old['version']!=req.expected_version:raise HTTPException(409,'模板已被其他设备修改，请重新打开')
                c.execute('UPDATE training_templates SET title=?,scene=?,exercises_json=?,version=version+1,updated_at=? WHERE id=?',(req.title,req.scene,packed(req,True),stamp,tid))
            else:
                old=c.execute('SELECT * FROM training_templates WHERE user_id=? AND request_id=?',(uid,req.request_id)).fetchone()
                if old:
                    if old['deleted'] or old['payload_hash']!=h:raise HTTPException(409,'模板已保存或删除，请重新打开后修改')
                    return {'code':0,'item':item(old),'duplicate':True}
                if c.execute('SELECT COUNT(*) FROM training_templates WHERE user_id=? AND deleted=0',(uid,)).fetchone()[0]>=50:raise HTTPException(400,'最多保存50个模板，请先整理不用的模板')
                tid=c.execute('INSERT INTO training_templates(user_id,request_id,payload_hash,title,scene,exercises_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(uid,req.request_id,h,req.title,req.scene,packed(req,True),stamp,stamp)).lastrowid
            c.commit();return {'code':0,'item':item(owned(c,'training_templates',uid,tid))}
        finally:c.close()
    @app.post('/api/training/templates')
    def template_create(req:Template,user:dict=Depends(auth)):return save_template(req,user)
    @app.put('/api/training/templates/{tid}')
    def template_update(tid:int,req:Template,user:dict=Depends(auth)):return save_template(req,user,tid)
    @app.post('/api/training/templates/{tid}/delete')
    def template_delete(tid:int,req:Revision,user:dict=Depends(auth)):
        write_budget(user)
        c=db()
        try:
            c.execute('BEGIN IMMEDIATE');r=owned(c,'training_templates',user['id'],tid)
            if r['version']!=req.expected_version:raise HTTPException(409,'模板已变更，请重新打开')
            c.execute("UPDATE training_templates SET deleted=1,title='',exercises_json='[]',version=version+1,updated_at=? WHERE id=?",(api['_now'](),tid));c.commit();return {'code':0}
        finally:c.close()
    @app.get('/api/training/progress')
    def progress(exercise:str='',kind:Literal['reps','time']='reps',user:dict=Depends(auth)):
        if len(exercise)>60:raise HTTPException(400,'动作名称过长')
        c=db();uid=user['id'];base=" FROM training_sets t JOIN training_sessions s ON s.id=t.session_id WHERE t.user_id=? AND s.user_id=? AND s.deleted=0 AND s.status='completed' AND t.done=1"
        try:
            choices=[dict(r) for r in c.execute('SELECT t.name,t.kind,COUNT(*) AS sets'+base+' GROUP BY t.exercise_key,t.kind ORDER BY MAX(s.id) DESC LIMIT 100',(uid,uid))]
            if not exercise:return {'code':0,'choices':choices,'best':None,'recent':[]}
            where=base+' AND t.exercise_key=? AND t.kind=?';args=(uid,uid,key(exercise),kind)
            best=dict(c.execute('SELECT COUNT(*) AS sets,COUNT(DISTINCT s.id) AS sessions,MAX(t.weight_kg) AS max_weight_kg,MAX(t.reps) AS max_reps,MAX(t.seconds) AS max_seconds,SUM(CASE WHEN t.weight_kg IS NOT NULL THEN t.weight_kg*t.reps ELSE NULL END) AS volume_kg_reps'+where,args).fetchone())
            recent=[dict(r) for r in c.execute('SELECT s.id,s.day,s.title,COUNT(*) AS sets,MAX(t.weight_kg) AS weight_kg,MAX(t.reps) AS reps,SUM(t.seconds) AS seconds,SUM(t.weight_kg*t.reps) AS volume_kg_reps'+where+' GROUP BY s.id ORDER BY s.day DESC,s.id DESC LIMIT 20',args)]
            return {'code':0,'choices':choices,'best':best,'recent':recent}
        finally:c.close()
    @app.get('/api/training/export.csv')
    def export(user:dict=Depends(auth)):
        if not api['rate_hit']('training-export:'+str(user['id']),4,60)[0]:raise HTTPException(429,'导出太频繁，请稍后再试')
        c=db()
        try:rows=c.execute('''SELECT s.day,s.title,s.status,s.minutes,s.energy,s.note,t.name,t.kind,t.reps,t.weight_kg,t.seconds,t.done FROM training_sessions s JOIN training_sets t ON t.session_id=s.id WHERE s.user_id=? AND t.user_id=? AND s.deleted=0 ORDER BY s.id DESC,t.position LIMIT 10001''',(user['id'],user['id'])).fetchall()
        finally:c.close()
        out=io.StringIO();w=csv.writer(out);w.writerow(['日期','训练','状态','分钟','消耗kcal(手填)','备注','动作','类型','次数','负重kg','秒','完成'])
        def safe(x):return "'"+x if isinstance(x,str) and (x[:1] in ('\t','\r','\n') or x.lstrip(' \t\r\n\ufeff').startswith(('=','+','-','@'))) else x
        for r in rows[:10000]:
            values=list(r);values[2]={'planned':'计划中','completed':'已完成'}[r['status']];values[7]='计时' if r['kind']=='time' else '次数';values[11]='是' if r['done'] else '否';w.writerow([safe(x) for x in values])
        if len(rows)>10000:w.writerow(['已到10000组导出上限，仅包含最近记录'])
        return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="qingsu-training.csv"','Cache-Control':'no-store','X-Qingsu-Truncated':'1' if len(rows)>10000 else '0'})
