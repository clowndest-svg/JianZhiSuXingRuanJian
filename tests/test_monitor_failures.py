"""Monitoring failures must publish an explicit unknown/red report, not stale green."""
import contextlib,importlib.util,io,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def load():
    spec=importlib.util.spec_from_file_location('monitor_failure',ROOT/'scripts/monitor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class MonitorFailures(unittest.TestCase):
    def test_bad_certificate_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=load();m.root=Path(tmp)
            def run(command,**kwargs):
                if command[0]=='openssl':raise subprocess.TimeoutExpired(command,10)
                return SimpleNamespace(stdout='active' if command[0]=='systemctl' else '',returncode=0)
            class Response:
                status=200
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,*args):return b'{"chat":{"sockets":0,"rejected":0,"redis":true}}'
            with patch.object(m.subprocess,'run',side_effect=run),patch.object(m.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda *a,**k:Response())),patch.object(m.socket,'socket',side_effect=OSError()),patch.object(m.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):m.main()
            report=json.loads((Path(tmp)/'monitor/status.json').read_text())
            self.assertIsNone(report['certificate_hours_left']);self.assertIn('certificate_unreadable',report['problems'])
    def test_atomic_report_keeps_previous_on_failure(self):
        m=load()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json';path.write_text('{"old":true}')
            with patch.object(m.os,'replace',side_effect=OSError('synthetic')):
                with self.assertRaises(OSError):m.write_report(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True});self.assertFalse(list(Path(tmp).glob('.report.json-*')))
    def test_percentile_does_not_underestimate_small_sample(self):
        self.assertEqual(load().percentile([1,5000]),5000)
if __name__=='__main__':unittest.main(verbosity=2)
