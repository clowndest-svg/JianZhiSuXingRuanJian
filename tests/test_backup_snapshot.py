"""Linux snapshot tests with private synthetic files, never the live root."""
import os, pathlib, sqlite3, subprocess, sys, tarfile, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform.startswith('linux'), 'production backup uses Linux flock/hardlinks')
class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        (self.root/'data').mkdir();(self.root/'uploads').mkdir()
        self.media=self.root/'uploads/photo.jpg';self.media.write_bytes(b'synthetic-photo')
        c=sqlite3.connect(self.root/'data/qingsu.db')
        c.execute('CREATE TABLE media(name TEXT)');c.execute("INSERT INTO media VALUES ('photo.jpg')");c.commit();c.close()

    def run_backup(self, hook=''):
        code="import runpy,tarfile,pathlib,sqlite3,os\n"+hook+"\nrunpy.run_path("+repr(str(ROOT/'scripts/backup.py'))+")"
        return subprocess.run([sys.executable,'-c',code],env={**os.environ,'QINGSU_ROOT':str(self.root)},capture_output=True,text=True,timeout=20)

    def test_deletion_after_pin_keeps_database_and_media_consistent(self):
        hook='''original=tarfile.open
def hooked(name,*args,**kwargs):
    if str(name).endswith('media.tar.gz') and args and args[0]=='w:gz':
        root=pathlib.Path(os.environ['QINGSU_ROOT'])
        c=sqlite3.connect(root/'data/qingsu.db');c.execute('DELETE FROM media');c.commit();c.close()
        (root/'uploads/photo.jpg').unlink()
    return original(name,*args,**kwargs)
tarfile.open=hooked
'''
        result=self.run_backup(hook);self.assertEqual(result.returncode,0,result.stderr)
        folder=self.root/'backups/scheduled'
        with sqlite3.connect(next(folder.glob('qingsu-*.db'))) as c:
            self.assertEqual(c.execute('SELECT name FROM media').fetchall(),[('photo.jpg',)])
        with tarfile.open(next(folder.glob('media-*.tar.gz'))) as archive:
            self.assertEqual(archive.extractfile('uploads/photo.jpg').read(),b'synthetic-photo')
        self.assertFalse(self.media.exists())
        self.assertFalse(list(folder.glob('.snapshot-*')))

    def test_symlinks_are_rejected(self):
        (self.root/'uploads/link.jpg').symlink_to(self.media)
        result=self.run_backup()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unexpected media symlink',result.stderr)
        self.assertFalse(list((self.root/'backups/scheduled').glob('qingsu-*.db')))

    def test_repeated_backups_do_not_overwrite_snapshots(self):
        for _ in range(2):
            r=self.run_backup();self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(list((self.root/'backups/scheduled').glob('qingsu-*.db'))),2)
        self.assertEqual(self.media.read_bytes(),b'synthetic-photo')

if __name__=='__main__':unittest.main(verbosity=2)
