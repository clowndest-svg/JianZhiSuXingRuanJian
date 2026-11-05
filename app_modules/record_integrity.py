"""Atomic write receipts and optimistic versions for the shared record ledger."""
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException

SCHEMA = """CREATE TABLE IF NOT EXISTS record_write_receipts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_key TEXT NOT NULL, scope TEXT NOT NULL, payload_hash TEXT NOT NULL,
    response_json TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(user_id,request_key,scope))"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def revision(conn, kind, row):
    # Audit sequence prevents an old edit from overwriting an intervening edit,
    # even if the values were later changed back or a deleted SQLite id is reused.
    data = dict(row)
    data.pop('revision', None)
    seq = conn.execute('SELECT MAX(id) FROM record_changes WHERE user_id=? AND kind=? AND record_id=?',
                       (data['user_id'], kind, data['id'])).fetchone()[0]
    return digest([data, seq])


def replay(conn, uid, key, scope, payload):
    if not key:
        return None
    row = conn.execute('SELECT payload_hash,response_json FROM record_write_receipts '
                       'WHERE user_id=? AND request_key=? AND scope=?', (uid, key, scope)).fetchone()
    if row is None:
        return None
    if row['payload_hash'] != digest(payload):
        raise HTTPException(409, '重试内容与原请求不同，请刷新记录后重新提交，未覆盖原记录')
    return {**json.loads(row['response_json']), 'duplicate': True}


def remember(conn, uid, key, scope, payload, result):
    if key:
        conn.execute('INSERT INTO record_write_receipts VALUES (?,?,?,?,?,?)',
                     (uid, key, scope, digest(payload), json.dumps(result, ensure_ascii=False),
                      datetime.now().isoformat()))


def check_revision(conn, kind, row, expected):
    if expected and expected != revision(conn, kind, row):
        raise HTTPException(409, '这条记录已在其他页面或设备修改，请刷新后核对，未覆盖新记录')
