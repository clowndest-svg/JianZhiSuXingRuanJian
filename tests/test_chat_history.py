"""Authorization, viewer isolation, cursor windows and cancellation races on real SQLite/API."""
import json,unittest,time,threading,sys,importlib.util
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('history_fixture',Path(__file__).with_name('test_bubble_themes.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from app_modules import chat_history

class ChatHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.BubbleThemes.setUpClass.__func__(cls)
        cls.a,cls.b=(u['id'] for u in cls.users)
        cls.h2={'Authorization':'Bearer '+cls.users[1]['token'],'X-App-Build':'99'}
    def send(self,text='history sample',headers=None):
        h=headers or self.headers;peer=self.a if h is self.h2 else self.b
        r=self.c.post('/api/chat/send',headers=h,json={'to':peer,'kind':'text','text':text});self.assertEqual(r.status_code,200,r.text);return r.json()['message']
    def history(self,h=None,**params):
        h=h or self.headers;peer=self.a if h is self.h2 else self.b
        return self.c.get('/api/chat/messages',headers=h,params={'with_user':peer,**params}).json()
    def test_edit_permissions_revision_and_attribution(self):
        m=self.send();payload={'message_id':m['id'],'text':'更新的消息','expected_version':0}
        self.assertEqual(self.c.post('/api/chat/edit',headers=self.h2,json=payload).status_code,403)
        r=self.c.post('/api/chat/edit',headers=self.headers,json=payload);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['message']['edit_version'],1);self.assertTrue(r.json()['message']['edited_at'])
        self.assertEqual(self.c.post('/api/chat/edit',headers=self.headers,json=payload).status_code,409)
        self.assertEqual(next(i for i in self.history(self.h2)['items'] if i['id']==m['id'])['body'],'更新的消息')
        self.assertEqual(self.c.post('/api/chat/edit',headers=self.headers,json={**payload,'text':'   ','expected_version':1}).status_code,400)
    def test_personal_delete_and_search_context_preview(self):
        marker='私藏_%文本';m=self.send(marker,self.h2)
        self.assertEqual(len(self.history(q=marker)['items']),1)
        r=self.c.post('/api/chat/delete',headers=self.headers,json={'message_ids':[m['id']]});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.history(q=marker)['items'],[])
        self.assertEqual(len(self.history(self.h2,q=marker)['items']),1)
        self.assertEqual(self.c.get('/api/chat/context',headers=self.headers,params={'message_id':m['id']}).status_code,404)
        self.assertEqual(self.c.post('/api/chat/edit',headers=self.headers,json={'message_id':m['id'],'text':'bad','expected_version':0}).status_code,404)
        convs=self.c.get('/api/chat/conversations',headers=self.headers).json()
        self.assertNotIn(marker,json.dumps(convs,ensure_ascii=False))
        self.assertEqual(self.c.post('/api/chat/delete',headers=self.headers,json={'message_ids':[m['id']]}).status_code,200)
    def test_receipt_only_targeted_visible_ids(self):
        x=self.send('unseen one',self.h2);y=self.send('seen two',self.h2);own=self.send('outgoing')
        r=self.c.post('/api/chat/read',headers=self.headers,json={'with_user':self.b,'message_ids':[y['id'],own['id']]})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['message_ids'],[y['id']])
        c=self.s.get_db()
        try:self.assertIsNone(c.execute('SELECT read_at FROM messages WHERE id=?',(x['id'],)).fetchone()[0])
        finally:c.close()
        self.assertEqual(self.c.post('/api/chat/read',headers=self.headers,json={'with_user':self.b,'message_ids':[]}).json()['marked'],0)
    def test_cancellation_before_start_and_stale_cancel(self):
        m=self.send();c=self.s.get_db();c.execute("UPDATE messages SET kind='audio',asr_text='cached' WHERE id=?",(m['id'],));c.commit();c.close()
        url='/api/chat/asr/cancel';mid=m['id']
        self.assertEqual(self.c.post(url,headers=self.headers,json={'message_id':mid,'request_id':'first'}).status_code,200)
        c=self.s.get_db();self.assertFalse(chat_history.start_asr(c,self.a,mid,'first'));self.assertTrue(chat_history.start_asr(c,self.a,mid,'second'));c.close()
        r=self.c.post(url,headers=self.headers,json={'message_id':mid,'request_id':'first'});self.assertFalse(r.json()['hidden'])
        c=self.s.get_db();self.assertTrue(chat_history.asr_active(c,self.a,mid,'second'));c.close()
        self.c.post(url,headers=self.headers,json={'message_id':mid})
        a=next(i for i in self.history()['items'] if i['id']==mid);b=next(i for i in self.history(self.h2)['items'] if i['id']==mid)
        self.assertTrue(a['asr_hidden']);self.assertEqual(a['asr_text'],'');self.assertEqual(b['asr_text'],'cached')
        r=self.c.post('/api/chat/asr',headers=self.headers,json={'message_id':mid,'request_id':'third'});self.assertEqual(r.json()['text'],'cached')
    def test_cancel_inflight_drops_late_result(self):
        m=self.send();mid=m['id'];c=self.s.get_db();c.execute("UPDATE messages SET kind='audio',media_name='history.wav' WHERE id=?",(mid,));c.commit();c.close()
        from pathlib import Path
        Path(self.s.UPLOAD_DIR,'history.wav').write_bytes(b'fixture');entered=threading.Event();release=threading.Event();old=self.s.asr.transcribe
        def transcribe(path):entered.set();release.wait(5);return 'late words'
        self.s.asr.transcribe=transcribe;result=[]
        try:
            t=threading.Thread(target=lambda:result.append(self.c.post('/api/chat/asr',headers=self.headers,json={'message_id':mid,'request_id':'slow'})));t.start();self.assertTrue(entered.wait(5))
            self.assertEqual(self.c.post('/api/chat/asr/cancel',headers=self.headers,json={'message_id':mid,'request_id':'slow'}).status_code,200);release.set();t.join(8)
            self.assertTrue(result[0].json()['cancelled']);c=self.s.get_db();self.assertEqual(c.execute('SELECT asr_text FROM messages WHERE id=?',(mid,)).fetchone()[0],'');c.close()
        finally:release.set();self.s.asr.transcribe=old
    def test_many_messages_keyset_query_and_legacy_read(self):
        c=self.s.get_db();ck=self.s.chat.conv_key(self.a,self.b);stamp=self.s._now()
        c.executemany('INSERT INTO messages(conv_key,from_id,to_id,body,created_at) VALUES (?,?,?,?,?)',[(ck,self.b,self.a,'bulk-%04d'%i,stamp) for i in range(10000)]);c.commit()
        plan=' '.join(str(tuple(r)) for r in c.execute('EXPLAIN QUERY PLAN '+chat_history.SELECT+' AND m.id<? ORDER BY m.id DESC LIMIT ?',(self.a,ck,999999999,31)))
        self.assertIn('INDEX',plan);c.close();start=time.monotonic();first=self.history(limit=30);second=self.history(limit=30,cursor=first['next_cursor'])
        self.assertTrue(first['more']);self.assertEqual(len(first['items']),30);self.assertFalse({m['id'] for m in first['items']}&{m['id'] for m in second['items']})
        context=self.c.get('/api/chat/context',headers=self.headers,params={'message_id':second['items'][10]['id']}).json();self.assertLessEqual(len(context['items']),41)
        self.assertEqual(self.c.post('/api/chat/read',headers=self.headers,json={'with_user':self.b}).status_code,200)
        print('10000-message fixture: two keyset pages/context/legacy receipt %.3fs'%(time.monotonic()-start))
    def test_schema_and_public_modules(self):
        self.assertEqual(self.s.migrations.SCHEMA_VERSION,13)
        for name in ['chat-tools.js','chat-tools.css']:self.assertEqual(self.c.get('/'+name).status_code,200)
    def test_server_time_explicit_offset_and_legacy_unchanged(self):
        with patch.object(self.s,'_now',return_value='2026-10-24 00:00:01'):m=self.send('server timestamp')
        from datetime import datetime
        self.assertEqual(m['created_at'],'2026-10-24 00:00:01');self.assertEqual(m['created_at_iso'],datetime.fromisoformat(m['created_at']).astimezone(chat_history.CHAT_ZONE).isoformat(timespec='seconds'))
        self.assertEqual(chat_history.canonical_time('2026-10-23T16:00:03Z'),'2026-10-24T00:00:03+08:00')
        self.assertEqual(chat_history.canonical_time('not a time'),'')
        self.assertEqual(chat_history.canonical_time('2026-10-24'),'')
    def test_conversation_list_uses_two_queries_and_one_presence_batch(self):
        c=self.s.get_db();peers=[];stamp='2026-10-24 01:02:03'
        for i in range(30):
            peer=c.execute('INSERT INTO users(username,password_hash,created_at) VALUES (?,?,?)',('batchpeer'+str(i),'not-a-login-hash',stamp)).lastrowid;peers.append(peer);ck=self.s.chat.conv_key(self.a,peer)
            c.execute('INSERT INTO conversations(conv_key,a_id,b_id,created_at,last_at) VALUES (?,?,?,?,?)',(ck,min(self.a,peer),max(self.a,peer),stamp,stamp))
            c.execute('INSERT INTO messages(conv_key,from_id,to_id,body,created_at) VALUES (?,?,?,?,?)',(ck,peer,self.a,'visible-'+str(i),stamp))
            hidden=c.execute('INSERT INTO messages(conv_key,from_id,to_id,body,created_at) VALUES (?,?,?,?,?)',(ck,peer,self.a,'must stay hidden',stamp)).lastrowid
            c.execute('INSERT INTO message_preferences(user_id,message_id,deleted) VALUES (?,?,1)',(self.a,hidden))
        c.execute('INSERT INTO user_blocks(blocker,blocked,created_at) VALUES (?,?,?)',(self.a,peers[-1],stamp));c.commit();sql=[];calls=[]
        c.set_trace_callback(lambda s:sql.append(s) if s.lstrip().upper().startswith(('SELECT','WITH')) else None)
        def redis(args):calls.append(args);return True,['1' if k==self.s.chat.presence_key(peers[-1]) else None for k in args[1:]]
        with patch.object(self.s,'_redis_cmd',side_effect=redis):out=chat_history.conversations(vars(self.s),c,self.a)
        c.close();self.assertEqual(len(sql),2);self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],'MGET')
        rows={r['with'].get('id'):r for r in out}
        for i,peer in enumerate(peers):self.assertEqual(rows[peer]['last_body'],'visible-'+str(i));self.assertEqual(rows[peer]['unread'],1)
        self.assertTrue(rows[peers[-1]]['online']);self.assertTrue(rows[peers[-1]]['blocked']);self.assertFalse(rows[peers[0]]['online'])
        print('30 conversations: 2 SQL statements, 1 Redis MGET; per-viewer previews/unread/block flags preserved')
    def test_outsider_and_atomic_delete_and_nontext_edit(self):
        r=self.c.post('/api/register',headers={'X-App-Build':'99'},json={'username':'historyoutsider','password':'Theme!12345','age':30,'height':170,'weight_jin':160,'target_weight_jin':140});self.assertEqual(r.status_code,200,r.text)
        stranger={'Authorization':'Bearer '+r.json()['token'],'X-App-Build':'99'};m=self.send('authorization boundary')
        for path,payload in [('/api/chat/edit',{'message_id':m['id'],'text':'bad','expected_version':0}),('/api/chat/delete',{'message_ids':[m['id']]}),('/api/chat/asr/cancel',{'message_id':m['id']})]:
            self.assertEqual(self.c.post(path,headers=stranger,json=payload).status_code,404)
        self.assertEqual(self.c.get('/api/chat/context',headers=stranger,params={'message_id':m['id']}).status_code,404)
        self.assertEqual(self.c.post('/api/chat/delete',headers=self.headers,json={'message_ids':[m['id'],999999999]}).status_code,404)
        self.assertEqual(self.c.get('/api/chat/context',headers=self.headers,params={'message_id':m['id']}).status_code,200)
        c=self.s.get_db();c.execute("UPDATE messages SET kind='audio' WHERE id=?",(m['id'],));c.commit();c.close()
        self.assertEqual(self.c.post('/api/chat/edit',headers=self.headers,json={'message_id':m['id'],'text':'bad','expected_version':0}).status_code,400)

if __name__=='__main__':unittest.main()
