"""Release smoke: real decoder, media ownership and messages; exact fixture cleanup."""
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request

base = os.environ.get('QINGSU_VERIFY_BASE', 'http://172.17.0.1:8000')
db_path = os.environ.get('QINGSU_VERIFY_DB', '/opt/qingsu/data/qingsu.db')
default_uploads = str(Path(db_path).parent.parent / 'qa-uploads') if Path(db_path).parent.name == 'qa-data' else '/opt/qingsu/uploads'
uploads = Path(os.environ.get('QINGSU_VERIFY_UPLOAD', default_uploads))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(base + '/version.json', timeout=15) as response:
    build = str(json.load(response)['version_code'])
names = ['releasecheck_media_' + secrets.token_hex(6) for _ in range(2)]
checks = []


def api(path, body=None, token=None, binary=None, content_type=None):
    data = binary if binary is not None else None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={
        'Content-Type': content_type or 'application/json', 'X-App-Build': build,
        **({'Authorization': 'Bearer ' + token} if token else {})})
    try:
        with opener.open(req, timeout=25) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def upload(path, blob, mime, token, target=None):
    boundary = 'qingsu-' + secrets.token_hex(12)
    parts = []
    if target:
        parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="to"\r\n\r\n' + str(target) + '\r\n').encode())
    parts += [('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="fixture"\r\nContent-Type: ' + mime + '\r\n\r\n').encode(),
              blob, ('\r\n--' + boundary + '--\r\n').encode()]
    status, data = api(path, token=token, binary=b''.join(parts), content_type='multipart/form-data; boundary=' + boundary)
    assert status == 200 and data['code'] == 0, (status, data)
    return data


try:
    users = []
    for name in names:
        status, data = api('/api/register', dict(username=name, password='Release!' + secrets.token_hex(12), age=30,
            height=170, weight_jin=160, target_weight_jin=140))
        assert status == 200, (status, data)
        users.append(data)
    a, b = users
    with opener.open(base + '/stickers.json', timeout=15) as response:
        manifest = json.load(response)
    assert len(manifest['items']) == 18
    for item in manifest['items']:
        with opener.open(base + '/' + item['file'], timeout=15) as response:
            assert response.status == 200
    checks.append('18 official assets served')
    with tempfile.TemporaryDirectory() as temp:
        voice = Path(temp) / 'voice.ogg'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000',
            '-t', '1', '-c:a', 'libopus', str(voice)], check=True, timeout=20)
        up = upload('/api/chat/media', voice.read_bytes(), 'audio/ogg', a['token'], b['id'])
    assert up['kind'] == 'audio' and up['mime'] == 'audio/ogg' and 0 < up['duration'] <= 2
    body = dict(to=b['id'], kind='audio', media_name=up['name'], duration=999999, request_id='voice-smoke')
    status, sent = api('/api/chat/send', body, a['token'])
    assert status == 200 and sent['message']['duration'] == up['duration']
    status, again = api('/api/chat/send', body, a['token'])
    assert status == 200 and again['duplicate'] and again['message']['id'] == sent['message']['id']
    with opener.open(base + sent['message']['media_url'], timeout=15) as response:
        assert response.headers['Content-Type'].split(';')[0] == 'audio/ogg' and response.read(4) == b'OggS'
    assert api('/api/chat/send', dict(to=a['id'], kind='audio', media_name=up['name']), b['token'])[0] == 400
    checks.append('real voice normalize/send/read/retry; authoritative duration; stolen media rejected')
    from PIL import Image
    picture = io.BytesIO(); Image.new('RGB', (16, 16), (20, 180, 90)).save(picture, format='PNG')
    up = upload('/api/chat/stickers/upload', picture.getvalue(), 'image/png', a['token'])
    status, sent = api('/api/chat/send', dict(to=b['id'], kind='sticker', media_name=up['name'], request_id='sticker-smoke'), a['token'])
    assert status == 200 and sent['message']['media_url']
    status, sent = api('/api/chat/send', dict(to=b['id'], kind='sticker', text='qs:smile'), a['token'])
    assert status == 200
    assert api('/api/chat/recall', dict(message_id=sent['message']['id']), a['token'])[0] == 200
    checks.append('local/official stickers send without mutual follow; recall')
    if os.environ.get('QINGSU_VERIFY_NETWORK') == '1':
        status, result = api('/api/chat/stickers/search?q=happy', token=a['token'])
        assert status == 200 and result['available'] and result['items']
        status, up = api('/api/chat/stickers/import', dict(id=result['items'][0]['id']), a['token'])
        assert status == 200
        status, sent = api('/api/chat/send', dict(to=b['id'], kind='sticker', media_name=up['name']), a['token'])
        assert status == 200 and sent['message']['sticker_meta']['license'] == 'CC BY-SA 4.0'
        checks.append('LIVE OpenMoji search/import/send with attribution')
        status, result = api('/api/chat/stickers/search?provider=memegen&q=cat', token=a['token'])
        assert status == 200 and result['available'] and result['items'], (status, result)
        status, up = api('/api/chat/stickers/import', dict(id=result['items'][0]['id']), a['token'])
        assert status == 200, (status, up)
        status, sent = api('/api/chat/send', dict(to=b['id'], kind='sticker', media_name=up['name']), a['token'])
        assert status == 200 and sent['message']['sticker_meta']['source_url']
        checks.append('LIVE Memegen meme search/import/send with original source')
    print(json.dumps({'passed': checks, 'build': build}, ensure_ascii=False))
finally:
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys=ON');conn.execute('BEGIN IMMEDIATE');conn.execute('PRAGMA defer_foreign_keys=ON')
    ids = [r[0] for r in conn.execute('SELECT id FROM users WHERE username IN (?,?)', names)]
    media = [r[0] for uid in ids for r in conn.execute('SELECT name FROM media_uploads WHERE user_id=?', (uid,))]
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for uid in ids:
        for table in tables:
            cols = {r[1] for r in conn.execute('PRAGMA table_info("' + table + '")')}
            wanted = cols & {'user_id','follower_id','followee_id','from_id','to_id','blocker','blocked','reporter','actor_id','a_id','b_id','last_from'}
            for col in wanted: conn.execute('DELETE FROM "' + table + '" WHERE "' + col + '"=?', (uid,))
        conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit();conn.close()
    for name in media:
        target = (uploads / name).resolve()
        if target.parent != uploads.resolve(): raise RuntimeError('Unsafe fixture media path')
        target.unlink(missing_ok=True)
    print(json.dumps({'fixture_users_removed': len(ids), 'fixture_files_removed': len(media)}))
