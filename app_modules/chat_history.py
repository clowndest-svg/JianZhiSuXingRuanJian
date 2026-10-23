"""Private history controls; SQL visibility is per viewer, edits remain attributed."""
import json,secrets
from datetime import datetime,timezone,timedelta
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict

# Preserve the legacy field. Interpret naive values in the server process zone
# (verified Asia/Taipei in production), then publish an explicit app-time offset.
CHAT_ZONE=timezone(timedelta(hours=8))
def canonical_time(stamp):
    try:
        raw=str(stamp or '')
        if len(raw)<19 or raw[10] not in ' T':return ''
        value=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if value.tzinfo is None:value=value.astimezone()
        return value.astimezone(CHAT_ZONE).isoformat(timespec='seconds')
    except (ValueError,TypeError):return ''

def conversations(api,conn,uid):
    # Two bounded SQL statements, independent of the number of conversations.
    data=conn.execute('''WITH recent AS (
        SELECT c.*,CASE WHEN a_id=? THEN b_id ELSE a_id END AS peer,
        (SELECT m.id FROM messages m WHERE m.conv_key=c.conv_key AND NOT EXISTS
          (SELECT 1 FROM message_preferences p WHERE p.user_id=? AND p.message_id=m.id AND p.deleted=1)
          ORDER BY m.id DESC LIMIT 1) AS visible_id
        FROM conversations c WHERE a_id=? OR b_id=? ORDER BY last_at DESC LIMIT 100)
        SELECT c.conv_key,c.peer,m.body,m.kind,m.recalled_at,m.created_at,m.from_id,
        u.id,u.public_id,u.username,u.nickname,p.avatar_url,b.blocked AS blocked
        FROM recent c JOIN messages m ON m.id=c.visible_id
        LEFT JOIN users u ON u.id=c.peer LEFT JOIN profiles p ON p.user_id=c.peer
        LEFT JOIN user_blocks b ON b.blocker=? AND b.blocked=c.peer
        ORDER BY m.created_at DESC,m.id DESC''',(uid,uid,uid,uid,uid)).fetchall()
    if not data:return []
    keys=[r['conv_key'] for r in data]
    unread_counts={r['conv_key']:r['n'] for r in conn.execute('''SELECT m.conv_key,COUNT(*) AS n
        FROM messages m WHERE m.to_id=? AND m.read_at IS NULL AND NOT EXISTS
        (SELECT 1 FROM message_preferences p WHERE p.user_id=? AND p.message_id=m.id AND p.deleted=1)
        AND m.conv_key IN ('''+','.join('?' for _ in keys)+') GROUP BY m.conv_key',(uid,uid,*keys))}
    peers=[int(r['peer']) for r in data]
    ok,online=api['_redis_cmd'](['MGET',*[api['chat'].presence_key(i) for i in peers]])
    if not ok or not isinstance(online,list) or len(online)!=len(peers):
        now=api['now_ish']();online=[now-api['_presence_mem'].get(i,0)<45 for i in peers]
    out=[]
    for r,is_online in zip(data,online):
        brief=({'id':int(r['id']),'public_id':r['public_id'] or '',
                'name':(r['nickname'] or r['username'] or '').strip(),
                'avatar':api['signed_photo'](r['avatar_url']) if r['avatar_url'] else ''} if r['id'] else {})
        preview={'image':'［图片］','video':'［视频］','audio':'［语音］','sticker':'［表情］'}.get(r['kind'],r['body'][:60])
        out.append({'with':brief,'key':r['conv_key'],'last_body':'（已撤回）' if r['recalled_at'] else preview,
                    'last_at':r['created_at'],'last_from':int(r['from_id']),
                    'unread':int(unread_counts.get(r['conv_key'],0)),'online':bool(is_online),'blocked':bool(r['blocked'])})
    return out
class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message_id:int=Field(gt=0)
    text:str=Field(min_length=1,max_length=1000)
    expected_version:int=Field(ge=0)
class Delete(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message_ids:list[int]=Field(min_length=1,max_length=100)
class AsrState(BaseModel):
    model_config=ConfigDict(extra='forbid')
    message_id:int=Field(gt=0)
    request_id:str=Field(default='',max_length=96)

SELECT="SELECT m.*,COALESCE(p.asr_hidden,0) AS asr_hidden FROM messages m LEFT JOIN message_preferences p ON p.user_id=? AND p.message_id=m.id WHERE m.conv_key=? AND COALESCE(p.deleted,0)=0"
def rows(conn,uid,ck,cursor,size,q=''):
    sql=SELECT;args=[uid,ck]
    if cursor:sql+=' AND m.id<?';args.append(cursor)
    term=str(q or '').strip()
    if len(term)>100:raise HTTPException(400,'搜索词最多100字')
    if term:
        term=term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        sql+=" AND m.recalled_at IS NULL AND m.body LIKE ? ESCAPE '\\'";args.append('%'+term+'%')
    return conn.execute(sql+' ORDER BY m.id DESC LIMIT ?',(*args,size)).fetchall()
def accessible(conn,uid,mid):
    row=conn.execute("SELECT m.*,COALESCE(p.deleted,0) AS deleted,COALESCE(p.asr_hidden,0) AS asr_hidden FROM messages m LEFT JOIN message_preferences p ON p.user_id=? AND p.message_id=m.id WHERE m.id=? AND (m.from_id=? OR m.to_id=?)",(uid,mid,uid,uid)).fetchone()
    if not row or row['deleted']:raise HTTPException(404,'这条消息不可见或已删除')
    return row
def unread(conn,uid,ck=None):
    sql="SELECT COUNT(*) FROM messages m WHERE m.to_id=? AND m.read_at IS NULL AND NOT EXISTS(SELECT 1 FROM message_preferences p WHERE p.user_id=? AND p.message_id=m.id AND p.deleted=1)";args=[uid,uid]
    if ck:sql+=' AND m.conv_key=?';args.append(ck)
    return conn.execute(sql,args).fetchone()[0]
def mark_read(api,uid,peer,ids=None):
    if ids is not None and (not isinstance(ids,list) or len(ids)>120 or any(not isinstance(i,int) or isinstance(i,bool) or i<=0 for i in ids)):
        raise HTTPException(400,'已读消息列表无效')
    c=api['get_db']();ck=api['chat'].conv_key(uid,peer)
    try:
        c.execute('BEGIN IMMEDIATE');sql="SELECT m.id FROM messages m WHERE m.conv_key=? AND m.to_id=? AND m.read_at IS NULL AND NOT EXISTS(SELECT 1 FROM message_preferences p WHERE p.user_id=? AND p.message_id=m.id AND p.deleted=1)";args=[ck,uid,uid]
        if ids is not None:
            if not ids:return {'code':0,'marked':0,'message_ids':[],'unread_total':unread(c,uid),'unread_with':unread(c,uid,ck)}
            sql+=' AND m.id IN ('+','.join('?' for _ in ids)+')';args+=ids
        stamp=api['_now']()
        if ids is None:
            # Legacy clients acknowledge a whole conversation without materializing IDs.
            count=c.execute('UPDATE messages SET read_at=? WHERE id IN ('+sql+')',(stamp,*args)).rowcount;changed=None
        else:
            changed=[r[0] for r in c.execute(sql,args)];count=len(changed)
            if changed:c.execute('UPDATE messages SET read_at=? WHERE conv_key=? AND to_id=? AND id IN ('+','.join('?' for _ in changed)+')',(stamp,ck,uid,*changed))
        c.commit();result={'code':0,'marked':count,'message_ids':changed,'unread_total':unread(c,uid),'unread_with':unread(c,uid,ck)}
    finally:c.close()
    if count:api['_push'](peer,{'t':'read','by':uid,'marked':count,'message_ids':changed,'read_at':stamp})
    return result

def start_asr(conn,uid,mid,rid):
    conn.execute('BEGIN IMMEDIATE');row=accessible(conn,uid,mid)
    p=conn.execute('SELECT * FROM message_preferences WHERE user_id=? AND message_id=?',(uid,mid)).fetchone()
    if p and rid in json.loads(p['cancelled_requests'] or '[]'):conn.rollback();return False
    conn.execute("INSERT INTO message_preferences(user_id,message_id,asr_request,asr_hidden) VALUES (?,?,?,0) ON CONFLICT(user_id,message_id) DO UPDATE SET asr_request=excluded.asr_request,asr_hidden=0",(uid,mid,rid));conn.commit();return True

def asr_active(conn,uid,mid,rid):
    return bool(conn.execute("SELECT 1 FROM message_preferences p JOIN messages m ON m.id=p.message_id WHERE p.user_id=? AND p.message_id=? AND p.asr_request=? AND p.asr_hidden=0 AND p.deleted=0 AND m.recalled_at IS NULL",(uid,mid,rid)).fetchone())

def install(app,api):
    auth=api['get_current_user']
    @app.post('/api/chat/edit')
    def edit(req:Edit,user:dict=Depends(auth)):
        uid=int(user['id']);c=api['get_db']()
        try:
            c.execute('BEGIN IMMEDIATE');row=accessible(c,uid,req.message_id)
            if row['from_id']!=uid:raise HTTPException(403,'只能编辑自己发送的文字')
            if row['kind']!='text' or row['recalled_at']:raise HTTPException(400,'这条消息不能编辑')
            if row['edit_version']!=req.expected_version:raise HTTPException(409,'消息已被其他设备修改，请刷新后再编辑')
            try:text=api['community'].clean_body(req.text,1000,'私信')
            except ValueError as error:raise HTTPException(400,str(error))
            stamp=api['_now']()
            if text!=row['body']:
                c.execute('UPDATE messages SET body=?,edited_at=?,edit_version=edit_version+1 WHERE id=?',(text,stamp,req.message_id))
                c.execute('UPDATE conversations SET last_body=? WHERE conv_key=? AND ?=(SELECT MAX(id) FROM messages WHERE conv_key=?)',(text,row['conv_key'],req.message_id,row['conv_key']))
            c.commit();result=api['_message_dict'](accessible(c,uid,req.message_id));other=row['to_id']
        finally:c.close()
        for target in (uid,other):api['_push'](target,{'t':'message_edited','message':result})
        return {'code':0,'message':result}
    @app.post('/api/chat/delete')
    def delete(req:Delete,user:dict=Depends(auth)):
        uid=int(user['id']);ids=sorted(set(req.message_ids));c=api['get_db']()
        try:
            c.execute('BEGIN IMMEDIATE')
            for mid in ids:
                # Idempotent deletion but never allow another conversation's messages.
                row=c.execute('SELECT from_id,to_id FROM messages WHERE id=?',(mid,)).fetchone()
                if not row or uid not in (row['from_id'],row['to_id']):raise HTTPException(404,'找不到这条消息')
            for mid in ids:c.execute('INSERT INTO message_preferences(user_id,message_id,deleted,asr_hidden) VALUES (?,?,1,1) ON CONFLICT(user_id,message_id) DO UPDATE SET deleted=1,asr_hidden=1',(uid,mid))
            c.commit()
        finally:c.close()
        api['_push'](uid,{'t':'message_hidden','message_ids':ids})
        return {'code':0,'message_ids':ids}
    @app.post('/api/chat/asr/cancel')
    def cancel(req:AsrState,user:dict=Depends(auth)):
        uid=int(user['id']);c=api['get_db']()
        try:
            c.execute('BEGIN IMMEDIATE');m=accessible(c,uid,req.message_id)
            if m['kind']!='audio':raise HTTPException(400,'只有语音消息能取消转写')
            p=c.execute('SELECT * FROM message_preferences WHERE user_id=? AND message_id=?',(uid,req.message_id)).fetchone();cancelled=json.loads(p['cancelled_requests'] or '[]') if p else []
            if req.request_id:cancelled=list(dict.fromkeys(cancelled+[req.request_id]))[-16:]
            hiding=not req.request_id or not p or p['asr_request']==req.request_id
            active=p['asr_request'] if p else req.request_id
            if not req.request_id:active=secrets.token_urlsafe(12)
            c.execute("INSERT INTO message_preferences(user_id,message_id,asr_hidden,asr_request,cancelled_requests) VALUES (?,?,?,?,?) ON CONFLICT(user_id,message_id) DO UPDATE SET asr_hidden=excluded.asr_hidden,asr_request=excluded.asr_request,cancelled_requests=excluded.cancelled_requests",(uid,req.message_id,1 if hiding else p['asr_hidden'],active,json.dumps(cancelled)))
            c.commit()
        finally:c.close()
        if hiding:api['_push'](uid,{'t':'asr_hidden','message_id':req.message_id,'request_id':req.request_id})
        return {'code':0,'hidden':hiding}
    @app.get('/api/chat/context')
    def context(message_id:int,user:dict=Depends(auth)):
        uid=int(user['id']);c=api['get_db']()
        try:
            m=accessible(c,uid,message_id);ck=m['conv_key']
            before=c.execute(SELECT+' AND m.id<=? ORDER BY m.id DESC LIMIT 21',(uid,ck,message_id)).fetchall()
            after=c.execute(SELECT+' AND m.id>? ORDER BY m.id ASC LIMIT 20',(uid,ck,message_id)).fetchall()
            batch=list(reversed(before))+list(after);first=batch[0]['id'];last=batch[-1]['id']
            return {'code':0,'items':[api['_message_dict'](r) for r in batch],'more':bool(rows(c,uid,ck,first,1)),'next_cursor':first,'has_newer':bool(c.execute(SELECT+' AND m.id>? LIMIT 1',(uid,ck,last)).fetchone())}
        finally:c.close()
