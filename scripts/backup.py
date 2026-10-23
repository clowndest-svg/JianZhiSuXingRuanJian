"""Consistent local recovery snapshots. External/encrypted backups need a destination."""
import os,sqlite3,json,tarfile,subprocess,shutil,time,re,tempfile,fcntl
from pathlib import Path
from datetime import datetime
root=Path(os.environ.get('QINGSU_ROOT','/opt/qingsu')).resolve()
out=root/'backups'/'scheduled';out.mkdir(mode=0o700,parents=True,exist_ok=True)
lock=open(out/'.snapshot.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX)
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
while (out/f'qingsu-{stamp}.db').exists():
    time.sleep(.1);stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
if shutil.disk_usage(root).free<256*1024*1024:raise RuntimeError('Insufficient backup disk space')
# Freeze SQL commits only while capturing the database and pinning immutable
# media inodes. Compression runs after releasing the lock, so ordinary writes
# are not blocked for the duration of tar/gzip/encryption.
with tempfile.TemporaryDirectory(prefix='.snapshot-',dir=out) as snapshot:
    media=Path(snapshot)/'uploads';media.mkdir()
    snapshot_db=Path(snapshot)/'qingsu.db'
    snapshot_tar=Path(snapshot)/'media.tar.gz'
    guard=sqlite3.connect(root/'data/qingsu.db',timeout=10)
    try:
        guard.execute('BEGIN IMMEDIATE')
        source=sqlite3.connect(root/'data/qingsu.db')
        target=sqlite3.connect(snapshot_db)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Invalid backup')
        finally:target.close();source.close()
        for original in (root/'uploads').rglob('*'):
            if original.is_symlink():raise RuntimeError('Unexpected media symlink')
            pinned=media/original.relative_to(root/'uploads')
            if original.is_dir():pinned.mkdir(exist_ok=True)
            elif original.is_file():
                pinned.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(original,pinned)
                except FileNotFoundError:continue # unreferenced temporary upload removed before pin
    finally:guard.rollback();guard.close()
    with tarfile.open(snapshot_tar,'w:gz') as archive:
        archive.add(media,arcname='uploads')
    os.replace(snapshot_tar,out/f'media-{stamp}.tar.gz')
    os.replace(snapshot_db,out/f'qingsu-{stamp}.db')
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
