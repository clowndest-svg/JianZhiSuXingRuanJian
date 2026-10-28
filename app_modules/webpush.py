"""Session-bound Web Push subscriptions. Notifications never contain user data."""
import base64
import json
import os
import time
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

ALLOWED_HOSTS = ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com')


def valid_endpoint(value):
    try:
        u = urlsplit(value)
        host = u.hostname or ''
        allowed = host in ALLOWED_HOSTS or host.endswith('.notify.windows.com')
        return bool(allowed and u.scheme == 'https' and u.port in (None, 443) and not u.username and not u.password and not u.fragment and u.path.startswith('/') and len(value) <= 2048)
    except ValueError:
        return False


def public_key(path):
    try:
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        value = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(value).rstrip(b'=').decode()
    except (OSError, ValueError, ImportError):
        return ''


def provision(path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = Path(path)
    if path.exists():
        if not public_key(path):
            raise RuntimeError('Existing push key is unreadable; refusing to rotate subscriptions')
        return
    raw = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)


def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS push_subscriptions (
        endpoint TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
        keys_json TEXT NOT NULL, last_notice INTEGER NOT NULL, last_message INTEGER NOT NULL,
        failures INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id)')


def install(app, env):
    get_db, current = env['get_db'], env['get_current_user']
    path = os.path.join(env['KEY_DIR'], 'webpush-vapid.pem')

    class SubReq(BaseModel):
        endpoint: str = Field(max_length=2048)
        keys: dict[str, str]

    class DropReq(BaseModel):
        endpoint: str = Field(max_length=2048)

    @app.get('/api/push/config')
    def config(user: dict = Depends(current)):
        key = public_key(path)
        return {'code': 0, 'available': bool(key), 'public_key': key}

    @app.post('/api/push/subscribe')
    def subscribe(req: SubReq, user: dict = Depends(current)):
        if not public_key(path):
            raise HTTPException(503, '推送通道尚未就绪')
        if not valid_endpoint(req.endpoint):
            raise HTTPException(400, '不支持的浏览器推送服务')
        keys = req.keys
        try:
            p = base64.urlsafe_b64decode(keys.get('p256dh', '') + '=' * (-len(keys.get('p256dh', '')) % 4))
            a = base64.urlsafe_b64decode(keys.get('auth', '') + '=' * (-len(keys.get('auth', '')) % 4))
            if len(p) != 65 or p[0] != 4 or len(a) != 16:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, '浏览器订阅密钥无效')
        c = get_db()
        try:
            c.execute('BEGIN IMMEDIATE')
            count = c.execute('SELECT COUNT(*) FROM push_subscriptions WHERE user_id=? AND endpoint<>?', (user['id'], req.endpoint)).fetchone()[0]
            if count >= 8:
                raise HTTPException(400, '每个账号最多订阅8台浏览器')
            notice = c.execute('SELECT COALESCE(MAX(id),0) FROM notifications WHERE user_id=?', (user['id'],)).fetchone()[0]
            msg = c.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE to_id=?', (user['id'],)).fetchone()[0]
            c.execute('INSERT OR REPLACE INTO push_subscriptions VALUES (?,?,?,?,?,?,0,?)', (req.endpoint, user['id'], user['_session_hash'], json.dumps({k: keys[k] for k in ('p256dh', 'auth')}), notice, msg, int(time.time())))
            c.commit()
            return {'code': 0}
        finally:
            c.close()

    @app.post('/api/push/unsubscribe')
    def unsubscribe(req: DropReq, user: dict = Depends(current)):
        c = get_db()
        try:
            c.execute('DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?', (req.endpoint, user['id']))
            c.commit()
            return {'code': 0}
        finally:
            c.close()


def dispatch(c, key_path, send=None):
    """Bounded timer batch, coalescing unread events into one generic notice."""
    if send is None:
        from pywebpush import webpush
        send = webpush
    result = {'sent': 0, 'failed': 0, 'removed': 0}
    c.execute('DELETE FROM push_subscriptions WHERE session_hash NOT IN (SELECT token_hash FROM sessions WHERE expires_at>?)', (int(time.time()),))
    c.commit()
    rows = c.execute('SELECT p.* FROM push_subscriptions p JOIN users u ON p.user_id=u.id WHERE u.banned_at IS NULL ORDER BY p.updated_at LIMIT 100').fetchall()
    for r in rows:
        uid = r['user_id']
        notice = c.execute("SELECT COALESCE(MAX(id),0) FROM notifications WHERE user_id=? AND id>? AND read_at IS NULL AND kind IN ('comment','reply','mention')", (uid, r['last_notice'])).fetchone()[0]
        msg = c.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE to_id=? AND id>? AND read_at IS NULL AND COALESCE(recalled_at,'')=''", (uid, r['last_message'])).fetchone()[0]
        if not notice and not msg:
            c.execute('UPDATE push_subscriptions SET updated_at=? WHERE endpoint=?', (int(time.time()), r['endpoint']))
            c.commit()
            continue
        try:
            if not valid_endpoint(r['endpoint']):
                raise ValueError('Unsupported endpoint')
            send(subscription_info={'endpoint': r['endpoint'], 'keys': json.loads(r['keys_json'])},
                 vapid_private_key=str(key_path), vapid_claims={'sub': 'https://scientificexploration.art/about'}, ttl=300, timeout=8)
            c.execute('UPDATE push_subscriptions SET last_notice=MAX(last_notice,?),last_message=MAX(last_message,?),failures=0,updated_at=? WHERE endpoint=? AND session_hash=?', (notice, msg, int(time.time()), r['endpoint'], r['session_hash']))
            result['sent'] += 1
        except Exception as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            if status in (404, 410) or r['failures'] >= 4:
                c.execute('DELETE FROM push_subscriptions WHERE endpoint=? AND session_hash=?', (r['endpoint'], r['session_hash']))
                result['removed'] += 1
            else:
                c.execute('UPDATE push_subscriptions SET failures=failures+1,updated_at=? WHERE endpoint=? AND session_hash=?', (int(time.time()), r['endpoint'], r['session_hash']))
            result['failed'] += 1
        c.commit()
    return result
