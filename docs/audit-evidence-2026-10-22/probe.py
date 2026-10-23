"""Read-only repository audit; all mutations use OpsApi's disposable local fixture.

Run from the main repository: .venv/Scripts/python docs/audit-evidence-2026-10-22/probe.py
No production credentials, databases, emails or endpoints are used.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import warnings

warnings.filterwarnings('ignore', category=DeprecationWarning)
ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT.parent / 'JianZhiSuXingRuanJianHouTai'
spec = importlib.util.spec_from_file_location('audit_ops_fixture', ADMIN / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
case = fixture.OpsApi()
case.setUp()
results = {}
try:
    m, ops, app = case.ops_mod, case.ops, case.app
    uid, peer = case.signup['id'], case.other['id']
    auth = {'Authorization': 'Bearer ' + case.signup['token']}
    # Existing sockets must lose privileges when the account is banned or its session is revoked.
    ticket = app.post('/api/chat/ticket', headers=auth, json={}).json()['ticket']
    with app.websocket_connect('/ws/chat?ticket=' + ticket) as ws:
        ws.receive_json()
        m.ban(uid, {'expect_username': 'opsowner', 'reason': 'isolated audit'}, 'audit')
        ws.send_json({'t': 'send', 'to': peer, 'text': 'synthetic-ban-probe', 'request_id': 'audit-ban'})
        reply = ws.receive_json()
        results['active_socket_after_ban'] = {'event': reply.get('t'), 'persisted': bool(reply.get('message', {}).get('id')),
                                            'http_status': app.get('/api/me', headers=auth).status_code}
        m.unban(uid, {'expect_username': 'opsowner'}, 'audit')
        m.revoke_sessions(uid, {'expect_username': 'opsowner'}, 'audit')
        ws.send_json({'t': 'send', 'to': peer, 'text': 'synthetic-revoke-probe', 'request_id': 'audit-revoke'})
        reply = ws.receive_json()
        results['active_socket_after_revoke'] = {'event': reply.get('t'), 'persisted': bool(reply.get('message', {}).get('id')),
                                               'http_status': app.get('/api/me', headers=auth).status_code}
    # Generic export should apply the same recall policy as the dedicated conversation export.
    c = m.db()
    c.execute("UPDATE messages SET recalled_at=? WHERE from_id=?", ('2026-10-22 10:00:00', uid))
    c.execute("ALTER TABLE users ADD COLUMN future_sensitive_probe TEXT")
    c.execute("UPDATE users SET future_sensitive_probe='synthetic-only' WHERE id=?", (uid,))
    c.commit()
    results['new_column_default'] = {'included_in_safe_columns': 'future_sensitive_probe' in m.safe_columns(c, 'users')}
    c.close()
    export = m.export_user(uid, 'audit')
    results['generic_export_recalled_message'] = {'exposes_body': any(r.get('recalled_at') and r.get('body') for r in export['tables'].get('messages', []))}
    # Logout must invalidate the previously-issued artifact, not only clear the browser cookie.
    ops.post('/api/login', json={'token': os.environ['OPS_TOKEN']})
    cookie = ops.cookies.get('qops')
    ops.post('/api/logout', json={})
    results['admin_logout_cookie_replay'] = {'status': ops.get('/api/whoami', headers={'Cookie': 'qops=' + cookie}).status_code}
    # Labelled one-time password currently behaves like an ordinary persistent password.
    reset = m.reset_password(uid, {'expect_username': 'opsowner'}, 'audit')
    statuses = [app.post('/api/login', json={'username': 'opsowner', 'password': reset['one_time_password']}).status_code for _ in range(2)]
    results['reset_password_reuse'] = {'login_statuses': statuses}
    # Gate must be bounded by a verified installable version.
    m.json_get = lambda *_a, **_k: ({'min_build': int(Path(m.MIN_BUILD_FILE).read_text()), 'gate': {}}, None)
    gate = m.gate_set({'expect_current': 0, 'new': 99999}, 'audit')
    results['gate_above_published_build'] = {'manifest_code': 34, 'accepted_value': gate['written']}
    Path(m.MIN_BUILD_FILE).write_text('0')
    # Inject an audit storage failure and inspect the committed business row.
    saved_audit = m.audit
    def fail_audit(*_a, **_k):
        raise RuntimeError('synthetic audit write failure')
    m.audit = fail_audit
    try:
        m.ban(uid, {'expect_username': 'opsowner', 'reason': 'audit-write-failure'}, 'audit')
    except RuntimeError:
        pass
    finally:
        m.audit = saved_audit
    c = m.db()
    results['audit_atomicity'] = {'business_write_survived_audit_failure': bool(c.execute('SELECT banned_at FROM users WHERE id=?', (uid,)).fetchone()[0])}
    # Count actual SQL statements for one default community page.
    for n in range(12):
        c.execute("INSERT INTO posts(user_id,body,created_at) VALUES (?,?,?)", (uid, 'synthetic post ' + str(n), '2026-10-22 10:00:00'))
    post_id = c.execute('SELECT MAX(id) FROM posts').fetchone()[0]
    c.commit()
    queries = []
    original_get_db = case.app_mod.get_db
    def traced_db():
        connection = original_get_db()
        connection.set_trace_callback(lambda sql: queries.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
        return connection
    case.app_mod.get_db = traced_db
    try:
        page = case.app_mod.community_feed(tab='latest', cursor=0, limit=12, user={'id': uid})
    finally:
        case.app_mod.get_db = original_get_db
    results['community_page_queries'] = {'cards': len(page['items']), 'selects_excluding_auth': len(queries)}
    comment_file = Path(case.root, 'UPLOAD', 'synthetic-comment.jpg')
    comment_file.write_bytes(b'synthetic comment attachment')
    comment_id = c.execute('INSERT INTO comments(post_id,user_id,body,created_at,images) VALUES (?,?,?,?,?)',
                           (post_id, peer, 'synthetic comment', '2026-10-22 10:00:00', json.dumps([comment_file.name]))).lastrowid
    c.execute('INSERT INTO comment_likes(comment_id,user_id,created_at) VALUES (?,?,?)', (comment_id, peer, '2026-10-22 10:00:00'))
    c.commit()
    orphan_report = m.media_orphans('audit')
    results['comment_media_orphan_detection'] = {k: orphan_report[k] for k in ('files', 'referenced', 'orphans')}
    plan = m.delete_account(uid, {'expect_username': 'opsowner', 'plan_only': True}, 'audit')
    try:
        m.delete_account(uid, {'expect_username': 'opsowner', 'confirm_rows': plan['rows']}, 'audit')
        results['delete_with_other_users_comment_like'] = {'status': 200}
    except Exception as error:
        results['delete_with_other_users_comment_like'] = {'status': getattr(error, 'status_code', None), 'type': type(error).__name__}
    # Remove only that synthetic dependency so the separate file-cleanup probe can proceed.
    c.execute('DELETE FROM comment_likes WHERE comment_id=?', (comment_id,))
    c.commit()
    # Account deletion should have a media cleanup result as well as a DB result.
    owned_file = Path(case.root, 'UPLOAD', 'synthetic-avatar.jpg')
    owned_file.write_bytes(b'synthetic-not-a-real-image')
    c.execute('UPDATE profiles SET avatar_url=? WHERE user_id=?', ('/uploads/' + owned_file.name, uid))
    c.commit(); c.close()
    plan = m.delete_account(uid, {'expect_username': 'opsowner', 'plan_only': True}, 'audit')
    deleted = m.delete_account(uid, {'expect_username': 'opsowner', 'confirm_rows': plan['rows']}, 'audit')
    results['account_delete_media'] = {'delete_code': deleted['code'], 'owned_avatar_file_remains': owned_file.exists()}
finally:
    case.ops.close(); case.app.close(); case.bare.close()
    for logger in [logging.getLogger()] + [x for x in logging.Logger.manager.loggerDict.values() if isinstance(x, logging.Logger)]:
        for h in list(logger.handlers):
            name = getattr(h, 'baseFilename', '')
            if name and Path(name).resolve().is_relative_to(Path(case.tmp.name).resolve()):
                logger.removeHandler(h); h.close()
    case.tearDown()
output = Path(__file__).with_name('findings.json')
output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(results, ensure_ascii=False, indent=2))
