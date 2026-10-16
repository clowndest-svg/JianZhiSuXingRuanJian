"""Consistent local recovery snapshots. External/encrypted backups need a destination."""
import os,sqlite3,json,tarfile,subprocess,shutil,time,re
from pathlib import Path
from datetime import datetime
root=Path(os.environ.get('QINGSU_ROOT','/opt/qingsu')).resolve()
out=root/'backups'/'scheduled';out.mkdir(mode=0o700,parents=True,exist_ok=True)
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
if shutil.disk_usage(root).free<256*1024*1024:raise RuntimeError('Insufficient backup disk space')
source=sqlite3.connect(root/'data/qingsu.db')
target=sqlite3.connect(out/f'qingsu-{stamp}.db')
try:
    source.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Invalid backup')
finally:target.close();source.close()
with tarfile.open(out/f'media-{stamp}.tar.gz','w:gz') as archive:
    archive.add(root/'uploads',arcname='uploads')
for file in out.glob('*'+stamp+'*'):file.chmod(0o600)
recipient=root/'backup-recipient.pem'
if recipient.is_file():
    bundle=out/f'bundle-{stamp}.tar'
    with tarfile.open(bundle,'w') as archive:
        archive.add(out/f'qingsu-{stamp}.db',arcname='qingsu.db')
        archive.add(out/f'media-{stamp}.tar.gz',arcname='media.tar.gz')
        for original in (root/'backups').glob('orphan-archive-*.db'):
            if original.is_file() and not original.is_symlink():archive.add(original,arcname='quarantine/'+original.name)
    try:
        subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-cbc','-in',str(bundle),'-out',str(out/f'bundle-{stamp}.p7m'),'-outform','DER',str(recipient)],check=True)
        (out/f'bundle-{stamp}.p7m').chmod(0o600)
    finally:bundle.unlink(missing_ok=True)
for old in out.iterdir():
    if re.fullmatch(r'(qingsu|media|bundle)-\d{8}-\d{6}\.(db|tar\.gz|p7m)',old.name) and old.is_file() and not old.is_symlink() and time.time()-old.stat().st_mtime>14*86400:
        if old.resolve().parent==out.resolve():old.unlink()
print(json.dumps({'backup':stamp,'integrity':'ok'}))
