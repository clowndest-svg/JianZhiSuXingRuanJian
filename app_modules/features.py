import json
import time
import secrets
from datetime import date, datetime
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

DEFAULT_SCOPE = {'weight': True, 'profile': False, 'meals': False, 'workout': True, 'photos': False}

def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS share_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id), enabled INTEGER NOT NULL, expires_at INTEGER NOT NULL, scope TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS daily_reviews(user_id INTEGER NOT NULL REFERENCES users(id), log_date TEXT NOT NULL, complete INTEGER NOT NULL, PRIMARY KEY(user_id,log_date));
    ''')
    conn.execute('INSERT OR IGNORE INTO share_settings SELECT id,1,?,? FROM users',(int(time.time())+7*86400,json.dumps(DEFAULT_SCOPE)))
    conn.commit()

def share_settings(conn, uid):
    row=conn.execute('SELECT * FROM share_settings WHERE user_id=?',(uid,)).fetchone()
    if row:return {'enabled':bool(row['enabled']),'expires_at':row['expires_at'],'scope':json.loads(row['scope'])}
    return {'enabled':True,'expires_at':int(time.time())+7*86400,'scope':dict(DEFAULT_SCOPE)}

def public_projection(data, settings):
    scope=settings['scope']
    # Explicit allowlist prevents newly added private dashboard fields leaking by default.
    d={'today_date':data['today_date'],'user':{k:data['user'][k] for k in ('username','nickname')},
       'share_scope':scope,'cheer_total':int(data.get('cheer_total',0)),'profile':{},'metrics':{},'today_meals':[],
       'current_weight_jin':None,'today_consumed':None,'latest_cycle':{'photo_url':''}}
    if scope.get('weight'):
        for key in ('current_weight_jin','start_weight_jin','eta_days'):d[key]=data.get(key)
        d['profile'].update({k:data['profile'].get(k) for k in ('weight_jin','target_weight_jin')})
    else:d['profile'].update(weight_jin=None,target_weight_jin=None)
    if scope.get('profile'):
        d['profile'].update({k:data['profile'].get(k) for k in ('age','height')})
        d['metrics']=data.get('metrics',{})
    if scope.get('meals'):
        d['today_consumed']=data['today_consumed'];d['today_macros']=data['today_macros']
        d['today_meals']=[{k:r.get(k) for k in ('slot','food_name','cal','protein_g','carbs_g','fat_g','source','estimate_reason')} for r in data['today_meals']]
    if scope.get('workout'):
        for key in ('today_workout_done','today_burned','last_workout_date'):d[key]=data.get(key)
    if scope.get('photos') and data.get('latest_cycle'):
        d['latest_cycle']={'photo_url':data['latest_cycle'].get('photo_url','')}
    return d


def install(app, env):
    get_db=env['get_db'];current=env['get_current_user']
    with get_db() as c:migrate(c)
    c.close()

    class ShareReq(BaseModel):
        enabled:bool=True
        days:int=Field(default=7,ge=1,le=90)
        scope:dict[str,bool]=Field(default_factory=lambda:dict(DEFAULT_SCOPE))
        rotate:bool=False

    @app.get('/api/share/settings')
    def read_share(user:dict=Depends(current)):
        c=get_db()
        try:settings=share_settings(c,user['id'])
        finally:c.close()
        return {**settings,'public_url':env['public_url_for'](user)}

    @app.post('/api/share/settings')
    def save_share(req:ShareReq,user:dict=Depends(current)):
        if any(k not in DEFAULT_SCOPE for k in req.scope):raise HTTPException(400,'分享字段无效')
        c=get_db()
        try:
            scope={k:bool(req.scope.get(k,False)) for k in DEFAULT_SCOPE}
            expires=int(time.time())+req.days*86400
            c.execute('INSERT OR REPLACE INTO share_settings VALUES (?,?,?,?)',(user['id'],int(req.enabled),expires,json.dumps(scope)))
            if req.rotate:c.execute('UPDATE users SET share_secret=? WHERE id=?',(secrets.token_urlsafe(24),user['id']))
            c.commit();updated=dict(c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())
            return {**share_settings(c,user['id']),'public_url':env['public_url_for'](updated)}
        finally:c.close()

    class DayReq(BaseModel):
        log_date:date
        complete:bool

    @app.post('/api/day/complete')
    def complete_day(req:DayReq,user:dict=Depends(current)):
        if req.log_date>date.today():raise HTTPException(400,'不能确认未来日期')
        c=get_db()
        try:c.execute('INSERT OR REPLACE INTO daily_reviews VALUES (?,?,?)',(user['id'],req.log_date.isoformat(),int(req.complete)));c.commit()
        finally:c.close()
        return {'code':0,'complete':req.complete}

    class PreviewReq(BaseModel):
        food_name:str=Field(min_length=1,max_length=500)

    @app.post('/api/food/preview')
    def food_preview(req:PreviewReq,user:dict=Depends(current)):
        return env['parse_food_nutrition'](req.food_name)

    class EstimateReq(BaseModel):
        food_name:str=Field(min_length=1,max_length=500)
        grams:Optional[float]=None

    @app.post('/api/food/estimate')
    def food_estimate(req:EstimateReq,user:dict=Depends(current)):
        """让在线模型按菜名估热量。没配置就如实返回原因，绝不给一个来路不明的数。"""
        from app_modules.online_ai import online_estimate_food, online_status
        if req.grams is not None and not 1<=float(req.grams)<=3000:
            raise HTTPException(400,'重量要在 1 到 3000 克之间')
        ok,why=online_estimate_food(req.food_name,req.grams)
        if not ok:
            return {'code':1,'ok':False,'why':why or '在线模型没给结果','status':online_status()}
        return {'code':0,'ok':True,'status':online_status(),**ok}

    @app.get('/api/records')
    def records(kind:str='food',offset:int=0,limit:int=50,user:dict=Depends(current)):
        table={'food':'food_logs','weight':'weight_logs','workout':'workout_logs'}.get(kind)
        if not table or offset<0 or not 1<=limit<=100:raise HTTPException(400,'无效的分页或记录类型')
        c=get_db()
        try:
            rows=[dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE user_id=? ORDER BY log_date DESC,id DESC LIMIT ? OFFSET ?',(user['id'],limit,offset))]
            for row in rows:row.pop('user_id',None)
            return {'rows':rows,'offset':offset,'limit':limit}
        finally:c.close()

    class BackfillReq(BaseModel):
        kind:str
        log_date:date
        food_name:str=Field(default='',max_length=500)
        slot:str='加餐'
        cal:int|None=Field(default=None,ge=0,le=10000)
        weight_jin:float|None=Field(default=None,ge=40,le=600,allow_inf_nan=False)
        duration_minutes:int=Field(default=20,ge=1,le=1440)
        cal_burned:float=Field(default=0,ge=0,le=10000,allow_inf_nan=False)
        request_id:str=Field(min_length=1,max_length=100)

    @app.post('/api/records/backfill')
    def backfill(req:BackfillReq,user:dict=Depends(current)):
        if req.log_date>date.today() or req.log_date<date.fromisoformat(user['created_at'][:10]):raise HTTPException(400,'补录日期须在注册日至今天之间')
        if req.kind not in ('food','weight','workout'):raise HTTPException(400,'记录类型无效')
        c=get_db();stamp=datetime.now().isoformat();ds=req.log_date.isoformat()
        try:
            c.execute('INSERT OR IGNORE INTO request_receipts VALUES (?,?,?,?)',(user['id'],req.request_id,'backfill',stamp))
            if c.execute('SELECT changes()').fetchone()[0]==0:return {'code':0,'duplicate':True}
            env['snapshot_metrics'](c,user['id'])
            if req.kind=='food':
                if not req.food_name.strip():raise HTTPException(400,'请填写餐食')
                n=env['parse_food_nutrition'](req.food_name)
                c.execute('INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,protein_g,carbs_g,fat_g,time_str,created_at,source,estimate_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(user['id'],ds,req.slot,req.food_name,req.cal if req.cal is not None else n['cal'],n['protein_g'] if req.cal is None else 0,n['carbs_g'] if req.cal is None else 0,n['fat_g'] if req.cal is None else 0,'补录',stamp,'manual' if req.cal is not None else n['source'],'用户补录；手填热量时宏量未知' if req.cal is not None else n['reason']))
            elif req.kind=='weight':
                if req.weight_jin is None:raise HTTPException(400,'请填写体重')
                c.execute('INSERT INTO weight_logs(user_id,log_date,weight_jin,created_at) VALUES (?,?,?,?)',(user['id'],ds,req.weight_jin,stamp))
                latest=c.execute('SELECT weight_jin FROM weight_logs WHERE user_id=? ORDER BY log_date DESC,id DESC LIMIT 1',(user['id'],)).fetchone()
                c.execute('UPDATE profiles SET weight_jin=? WHERE user_id=?',(latest[0],user['id']))
            else:c.execute('INSERT INTO workout_logs(user_id,log_date,duration_minutes,cal_burned,plan_name,created_at) VALUES (?,?,?,?,?,?)',(user['id'],ds,req.duration_minutes,req.cal_burned,'补录训练（消耗为估算）',stamp))
            c.execute('DELETE FROM daily_reviews WHERE user_id=? AND log_date=?',(user['id'],ds))
            c.commit();return {'code':0,'msg':'补录已保存'}
        except Exception:c.rollback();raise
        finally:c.close()
