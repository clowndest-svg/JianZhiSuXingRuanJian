"""Execute the deployment switch in an isolated tree with command failures injected."""
import contextlib,io,json,os,shutil,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

class DeploymentFailures(unittest.TestCase):
    def test_migration_restart_and_readiness_failures_restore_entire_surface(self):
        for failure in ('migration','restart','readiness'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);root=folder/'app';root.mkdir();(root/'backups').mkdir();(root/'data').mkdir();(root/'tls').mkdir()
                (root/'tls/default.conf').write_text('old-tls')
                (root/'server.py').write_text('old-server');(root/'release.json').write_text('{"release":"old"}');(root/'backup.py').write_text('old-backup')
                for n in ('app_modules','web'):(root/n).mkdir();(root/n/'old-file').write_text('old')
                import sqlite3
                c=sqlite3.connect(root/'data/qingsu.db');c.execute('CREATE TABLE marker(value)');c.execute("INSERT INTO marker VALUES ('preserved')");c.commit();c.close()
                units=folder/'units';units.mkdir();(units/'qingsu.service').write_text('[Service]\nEnvironment=TZ=Asia/Taipei\n')
                gateway=folder/'gateway';gateway.write_text('old-gateway')
                stage=root/'releases/rnew';stage.mkdir(parents=True);(stage/'server.py').write_text('new-server');(stage/'web').mkdir();(stage/'web/new-file').write_text('new')
                (stage/'app_modules').mkdir();(stage/'app_modules/__init__.py').write_text('');(stage/'app_modules/webpush.py').write_text('def provision(path): path.write_bytes(b"synthetic")\n')
                (stage/'scripts').mkdir()
                for n in ('backup.py','monitor.py','set-min-build.py','push-worker.py','release_state.py','migrate.py','ci-deploy-server.py'):(stage/'scripts'/n).write_text('pass\n')
                (root/'keys').mkdir()
                import ast
                class IsolatedPaths(ast.NodeTransformer):
                    def visit_Constant(self, node):
                        if isinstance(node.value,str):
                            if node.value=='/opt/qingsu':node.value=str(root)
                            elif node.value.startswith('/etc/systemd/system/'):
                                node.value=(units/node.value.removeprefix('/etc/systemd/system/')).as_posix()
                            elif node.value=='/usr/local/sbin/qingsu-ci-deploy':node.value=str(gateway)
                        return node
                source=ast.fix_missing_locations(IsolatedPaths().visit(ast.parse((ROOT/'scripts/deploy.py').read_text())))
                calls=[];triggered=False
                def run(command,**kwargs):
                    nonlocal triggered
                    calls.append(command)
                    is_migrate=command[:1]==['python3'] and str(command[-1]).endswith('migrate.py')
                    is_restart=command==['systemctl','restart','qingsu']
                    if not triggered and ((failure=='migration' and is_migrate) or (failure=='restart' and is_restart)):
                        triggered=True;raise subprocess.CalledProcessError(1,command)
                    if command[0]=='systemctl' and command[1]=='is-active':out='active'
                    elif command[0]=='systemctl' and command[1]=='is-enabled':out='enabled'
                    elif command[:2]==['docker','inspect']:out='172.17.0.2'
                    else:out='old-http'
                    return types.SimpleNamespace(stdout=out,returncode=0)
                class Opener:
                    def open(self,*a,**k):raise OSError('synthetic readiness failure')
                grp=types.SimpleNamespace(getgrnam=lambda n:types.SimpleNamespace(gr_gid=0))
                from app_modules import webpush
                with patch.object(sys,'argv',['deploy.py','--stage',str(stage),'--revision','a'*40]),patch.object(subprocess,'run',side_effect=run),patch.object(os,'geteuid',return_value=0,create=True),patch.object(os,'chown',create=True),patch.dict(sys.modules,{'grp':grp}),patch('urllib.request.build_opener',return_value=Opener()),patch('time.sleep'),patch.object(webpush,'provision',side_effect=lambda p:p.write_bytes(b'synthetic')),contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises((OSError,RuntimeError,subprocess.CalledProcessError)):exec(compile(source,'isolated-deploy','exec'),{'__name__':'__main__'})
                self.assertEqual((root/'server.py').read_text(),'old-server');self.assertEqual((root/'backup.py').read_text(),'old-backup');self.assertEqual((root/'release.json').read_text(),'{"release":"old"}')
                self.assertTrue((root/'web/old-file').exists());self.assertFalse((root/'web/new-file').exists());self.assertFalse((root/'monitor.py').exists());self.assertEqual(gateway.read_text(),'old-gateway')
                c=sqlite3.connect(root/'data/qingsu.db');self.assertEqual(c.execute('SELECT value FROM marker').fetchone()[0],'preserved');c.close()

if __name__=='__main__':unittest.main(verbosity=2)
