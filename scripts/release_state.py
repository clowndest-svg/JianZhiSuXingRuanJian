"""Snapshot the complete mutable release surface; business data and keys are excluded."""
import json,os,shutil,tempfile
from pathlib import Path

EXTRAS=('release.json','backup.py','monitor.py','set-min-build.py','push-worker.py','migrate.py','release_state.py')
UNITS=('qingsu.service','qingsu-monitor.service','qingsu-monitor.timer','qingsu-push.service','qingsu-push.timer')

def atomic_json(path, value, mode=0o600):
    path=Path(path);fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            json.dump(value,output);output.flush();os.fsync(output.fileno())
        os.chmod(name,mode)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)

def capture(root, backup, units, gateway):
    root,backup,units,gateway=map(Path,(root,backup,units,gateway))
    entries={}
    for label,path in [(n,root/n) for n in EXTRAS]+[(n,units/n) for n in UNITS]+[('qingsu-ci-deploy',gateway)]:
        if path.is_symlink():raise RuntimeError('Unexpected release symlink')
        entries[label]=path.is_file()
        if entries[label]:shutil.copy2(path,backup/label)
    atomic_json(backup/'release-state.json',entries)

def restore(root, backup, units, gateway):
    root,backup,units,gateway=map(Path,(root,backup,units,gateway))
    entries=json.loads((backup/'release-state.json').read_text())
    for label,path in [(n,root/n) for n in EXTRAS]+[(n,units/n) for n in UNITS]+[('qingsu-ci-deploy',gateway)]:
        if entries[label]:shutil.copy2(backup/label,path)
        else:path.unlink(missing_ok=True)

def restore_code(root,backup):
    root,backup=map(Path,(root,backup))
    shutil.copy2(backup/'server.py',root/'server.py')
    for name in ('app_modules','web'):
        target=root/name
        if target.is_symlink():raise RuntimeError('Unexpected release symlink')
        if target.exists():shutil.rmtree(target)
        shutil.copytree(backup/name,target)
