"""Opt-in live HTTPS/WebSocket smoke using only disposable fixture accounts.

Run as qingsu on the release host. This verifies signalling, not microphone audio.
"""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time
import urllib.request
from websockets.sync.client import connect

sys.path.insert(0, '/opt/qingsu')
import server as srv

BASE = 'https://scientificexploration.art'
DB = Path('/opt/qingsu/data/qingsu.db')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
names = ['domaincheck_' + secrets.token_hex(6) for _ in range(2)]
emails = [name + '@releasecheck.invalid' for name in names]
checks = []


def api(path, token=None, body=None):
    request = urllib.request.Request(BASE + path,
        data=None if body is None else json.dumps(body).encode(), headers={
            'Content-Type': 'application/json', 'X-App-Build': build,
            **({'Authorization': 'Bearer ' + token} if token else {})})
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def receive(socket, kind):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        data = json.loads(socket.recv(timeout=max(.1, deadline - time.monotonic())))
        if data.get('t') == kind:
            return data
        if data.get('t') == 'call_error':
            raise RuntimeError('Unexpected call error: ' + data.get('detail', ''))
    raise RuntimeError('Missing WebSocket event: ' + kind)


try:
    with opener.open(BASE + '/version.json', timeout=15) as response:
        build = str(json.load(response)['version_code'])
    users = []
    for name, email in zip(names, emails):
        with sqlite3.connect(DB) as conn:
            code = srv._issue_email_code(conn, email, 'register')
        users.append(api('/api/register', body={
            'username': name, 'email': email, 'email_code': code,
            'password': secrets.token_urlsafe(24), 'age': 30, 'height': 170,
            'weight_jin': 160, 'target_weight_jin': 140}))
    a, b = users
    for user, peer in ((a, b), (b, a)):
        api('/api/community/users/' + str(peer['id']) + '/follow',
            user['token'], {'on': True})
    tickets = [api('/api/chat/ticket', user['token'], {})['ticket'] for user in users]
    uri = BASE.replace('https:', 'wss:') + '/ws/chat?ticket='
    with connect(uri + tickets[0], origin=BASE, open_timeout=10, close_timeout=3) as ca, \
         connect(uri + tickets[1], origin=BASE, open_timeout=10, close_timeout=3) as cb:
        receive(ca, 'ready')
        receive(cb, 'ready')
        checks.append('two authenticated WSS connections through public nginx')
        sent = api('/api/chat/send', a['token'], {
            'to': b['id'], 'kind': 'text', 'text': 'Disposable domain verification',
            'request_id': 'domain-' + secrets.token_hex(8)})
        assert receive(cb, 'msg')['message']['id'] == sent['message']['id']
        checks.append('HTTP text send delivered over WSS to fixture peer')
        ca.send(json.dumps({'t': 'call_invite', 'to': b['id'],
                           'sdp': {'type': 'offer', 'sdp': 'v=0\r\n'}}))
        call_id = receive(ca, 'call_ringing')['call_id']
        assert receive(cb, 'call_invite')['call_id'] == call_id
        cb.send(json.dumps({'t': 'call_accept', 'call_id': call_id,
                           'sdp': {'type': 'answer', 'sdp': 'v=0\r\n'}}))
        receive(ca, 'call_accept')
        receive(cb, 'call_active')
        ca.send(json.dumps({'t': 'call_ice', 'call_id': call_id, 'candidate': {
            'candidate': 'candidate:1 1 udp 1 192.0.2.1 5000 typ host',
            'sdpMid': '0', 'sdpMLineIndex': 0}}))
        receive(cb, 'call_ice')
        cb.send(json.dumps({'t': 'call_end', 'call_id': call_id}))
        receive(ca, 'call_end')
        checks.append('invite, accept, ICE forwarding and hangup signalling')
    ice = api('/api/rtc/ice', a['token'])
    assert ice.get('turn') and ice.get('ice_servers')
    checks.append('TURN credentials available (no real media traversal tested)')
    print(json.dumps({'passed': checks, 'physical_audio_tested': False}))
finally:
    with sqlite3.connect(DB) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('PRAGMA defer_foreign_keys=ON')
        ids = [r[0] for r in conn.execute(
            'SELECT id FROM users WHERE username IN (?,?)', names)]
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for uid in ids:
            for table in tables:
                columns = {r[1] for r in conn.execute('PRAGMA table_info("' + table + '")')}
                refs = {r[3] for r in conn.execute('PRAGMA foreign_key_list("' + table + '")')
                        if r[2] == 'users'}
                refs |= columns & {'user_id', 'follower_id', 'followee_id', 'from_id',
                    'to_id', 'blocker', 'blocked', 'reporter', 'actor_id', 'a_id', 'b_id', 'last_from'}
                for column in refs:
                    conn.execute('DELETE FROM "' + table + '" WHERE "' + column + '"=?', (uid,))
            conn.execute('DELETE FROM users WHERE id=?', (uid,))
        for email in emails:
            conn.execute('DELETE FROM email_codes WHERE email_hash=?', (srv.hash_token(email),))
        assert conn.execute('SELECT COUNT(*) FROM users WHERE username IN (?,?)', names).fetchone()[0] == 0
    print(json.dumps({'fixture_users_removed': len(ids), 'fixture_users_remaining': 0}))
