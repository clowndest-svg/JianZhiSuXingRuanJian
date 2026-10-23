"""Disposable localhost fixture for real Chromium HTTP-cache acceptance."""
import hashlib,hmac,importlib.util,io,os,sys,time
from pathlib import Path
from PIL import Image
import uvicorn
ROOT=Path(__file__).resolve().parents[1]
admin=Path(os.environ.get('QINGSU_ADMIN_REPO',str(ROOT.parent/'JianZhiSuXingRuanJianHouTai')))
spec=importlib.util.spec_from_file_location('cache_fixture',admin/'tests/test_ops_api.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
f=fixture.OpsApi();f.setUp();app=f.app_mod.app
blob=io.BytesIO();Image.new('RGB',(100,100)).save(blob,format='JPEG')
def upload():
    r=f.app.post('/api/community/media',headers=f.auth(),files={'file':('synthetic.jpg',blob.getvalue(),'image/jpeg')})
    assert r.status_code==200,r.text
    return r.json()['name']
public_name=upload();private_name=upload()
c=f.app_mod.get_db()
try:
    uid,peer=f.signup['id'],f.other['id']
    c.executemany('INSERT INTO follows VALUES (?,?,?)',[(uid,peer,'test'),(peer,uid,'test')]);c.commit()
    message,_=f.app_mod._deliver(c,{'id':uid},peer,'','cache-test',kind='image',media_name=private_name)
finally:c.close()
stats={'requests':0}
@app.get('/test/cache-info')
def info():
    expiry=int(time.time())+3
    signature=hmac.new(f.app_mod.media_key(),f'{public_name}:{expiry}'.encode(),hashlib.sha256).hexdigest()
    return {'community':f'/uploads/{public_name}?expires={expiry}&signature={signature}&thumb=1','private':message['media_url']+'&thumb=1'}
@app.get('/test/cache-count')
def count():return stats
@app.post('/test/recall')
def recall():return f.app_mod.chat_recall(f.app_mod.RecallReq(message_id=message['id']),{'id':uid})
async def counted(scope,receive,send):
    if scope['type']=='http' and scope['path'].startswith('/uploads/'):stats['requests']+=1
    await app(scope,receive,send)
try:uvicorn.run(counted,host='127.0.0.1',port=18008,log_level='warning')
finally:f.tearDown()
