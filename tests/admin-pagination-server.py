"""Disposable admin browser fixture. Never loads production credentials."""
import importlib.util
import os
from pathlib import Path
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
ADMIN = Path(os.environ.get('QINGSU_ADMIN_REPO', str(ROOT.parent / 'JianZhiSuXingRuanJianHouTai')))
spec = importlib.util.spec_from_file_location('browser_admin_fixture', ADMIN / 'tests/test_ops_api.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
case = fixture.OpsApi()
case.setUp()
case.ops_mod.audit('test', 'prepare')
c = case.ops_mod.db()
try:
    for n in range(123):
        c.execute('INSERT INTO users(id,username,password_hash,nickname,public_id) VALUES (?,?,?,?,?)', (100+n, 'page'+str(n), 'synthetic', 'page', str(50000000+n)))
        c.execute("INSERT INTO feedback(kind,body,app_build,created_at) VALUES ('bug',?,62,'test')", ('feedback '+str(n),))
        c.execute("INSERT INTO content_reports(target_kind,target_id,reporter,reason,created_at) VALUES ('post',?,?,'synthetic','test')", (n+1,case.signup['id']))
        c.execute("INSERT INTO admin_audit(actor,action,target_kind,created_at) VALUES ('test','batch2','users','test')")
    c.commit()
finally:
    c.close()
try:
    uvicorn.run(case.ops_mod.app, host='127.0.0.1', port=18009, log_level='warning')
finally:
    case.ops.close(); case.app.close(); case.bare.close(); case.tearDown()
