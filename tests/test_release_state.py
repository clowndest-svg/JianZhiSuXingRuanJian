"""Release rollback restores files/absence and preserves live business data."""
import importlib.util,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import release_state as state

class ReleaseState(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'root';self.backup=Path(self.tmp.name)/'backup';self.units=Path(self.tmp.name)/'units';self.gateway=Path(self.tmp.name)/'gateway'
        for p in (self.root,self.backup,self.units):p.mkdir()
        for n in ('server.py','backup.py','monitor.py','migrate.py','release.json'):(self.root/n).write_text('old-'+n)
        for n in ('app_modules','web'):(self.root/n).mkdir();(self.root/n/'original').write_text('old')
        (self.units/'qingsu.service').write_text('old-service');self.gateway.write_text('old-gateway')
    def test_full_restore_preserves_database_and_removes_candidate_only_files(self):
        for name in ('server.py',):__import__('shutil').copy2(self.root/name,self.backup/name)
        for name in ('app_modules','web'):__import__('shutil').copytree(self.root/name,self.backup/name)
        state.capture(self.root,self.backup,self.units,self.gateway)
        for n in state.EXTRAS:(self.root/n).write_text('candidate')
        for n in state.UNITS:(self.units/n).write_text('candidate')
        self.gateway.write_text('candidate');(self.root/'web/new').write_text('candidate');(self.root/'database').write_text('new user data')
        state.restore_code(self.root,self.backup);state.restore(self.root,self.backup,self.units,self.gateway)
        self.assertEqual((self.root/'database').read_text(),'new user data')
        self.assertEqual((self.root/'release.json').read_text(),'old-release.json');self.assertEqual(self.gateway.read_text(),'old-gateway')
        self.assertFalse((self.root/'push-worker.py').exists());self.assertFalse((self.root/'web/new').exists());self.assertFalse((self.units/'qingsu-push.timer').exists())
    def test_partial_restore_can_be_repeated(self):
        state.capture(self.root,self.backup,self.units,self.gateway)
        with patch.object(state.shutil,'copy2',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):state.restore(self.root,self.backup,self.units,self.gateway)
        state.restore(self.root,self.backup,self.units,self.gateway);state.restore(self.root,self.backup,self.units,self.gateway)
        self.assertEqual((self.root/'backup.py').read_text(),'old-backup.py')
    def test_atomic_marker_preserves_previous_on_write_failure(self):
        marker=self.root/'release.json'
        with patch.object(state.os,'replace',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):state.atomic_json(marker,{'release':'new'})
        self.assertEqual(marker.read_text(),'old-release.json');self.assertEqual(list(self.root.glob('.release.json-*')),[])
    def test_candidate_marker_is_readable_by_service(self):
        marker=self.root/'release.json';state.atomic_json(marker,{'release':'new'},0o644)
        self.assertEqual(json.loads(marker.read_text())['release'],'new')
        if os.name!='nt':self.assertEqual(marker.stat().st_mode&0o777,0o644)
    def test_verify_never_creates_or_overwrites_missing_keys(self):
        import subprocess
        keys=self.root/'keys';keys.mkdir();private=keys/'backup-private.pem';private.write_bytes(b'protected-existing-key')
        for args in (['--verify-only'],['--prepare']):
            r=subprocess.run([sys.executable,str(ROOT/'scripts/pull-backup.py'),*args,'--key-dir',str(keys),'--backup-dir',str(self.root/'backups')],capture_output=True,timeout=20)
            self.assertNotEqual(r.returncode,0);self.assertEqual(private.read_bytes(),b'protected-existing-key');self.assertFalse((keys/'backup-password.txt').exists())
    def test_deployer_snapshots_before_writing_candidate_marker(self):
        source=(ROOT/'scripts/deploy.py').read_text();self.assertLess(source.index('capture(root,backup'),source.index("atomic_json(root/'release.json'"))
        self.assertIn('restore_code(root,backup)',source);self.assertIn('restore(root,backup',source)
    def test_encryption_publishes_only_complete_file(self):
        source=(ROOT/'scripts/backup.py').read_text();self.assertIn('os.replace(partial,encrypted)',source);self.assertIn('partial.unlink(missing_ok=True)',source)

if __name__=='__main__':unittest.main(verbosity=2)
