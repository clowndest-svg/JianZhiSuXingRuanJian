"""Pull a public-key-encrypted server backup and verify restore locally.

The decrypting key never leaves this workstation. Files are not Git artifacts.
"""
import argparse,subprocess,json,tempfile,sqlite3,io,tarfile,hashlib,re,time
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from datetime import datetime,timedelta,timezone
import secrets

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--key-dir',default=r'D:\RuanJian\ShuJuChunChu\qingsu-signing');args=parser.parse_args()
keys=Path(args.key_dir);private=keys/'backup-private.pem';cert=keys/'backup-recipient.pem';password=keys/'backup-password.txt'
if not private.exists():
    secret=secrets.token_urlsafe(48).encode();password.write_bytes(secret)
    key=rsa.generate_private_key(public_exponent=65537,key_size=4096)
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(secret)))
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Qingsu Backup Recipient')]);now=datetime.now(timezone.utc)
    certificate=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650)).sign(key,hashes.SHA256())
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
if args.prepare:print('Public encryption certificate prepared; private key remains local.');raise SystemExit(0)
ssh_key=keys/'backup-access.pem'
base=['ssh','-i',str(ssh_key),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@124.220.54.64']
subprocess.run([*base,'python3 /opt/qingsu/backup.py'],check=True)
remote=subprocess.check_output([*base,"find /opt/qingsu/backups/scheduled -maxdepth 1 -name 'bundle-*.p7m' -type f | sort | tail -1"],text=True).strip()
if not remote.startswith('/opt/qingsu/backups/scheduled/bundle-') or not remote.endswith('.p7m'):raise RuntimeError('Unexpected backup name')
out=root/'.private-backups';out.mkdir(exist_ok=True)
local=out/Path(remote).name
subprocess.run(['scp','-i',str(ssh_key),'-o','BatchMode=yes','root@124.220.54.64:'+remote,str(local)],check=True)
key=serialization.load_pem_private_key(private.read_bytes(),password.read_bytes())
plain=pkcs7.pkcs7_decrypt_der(local.read_bytes(),x509.load_pem_x509_certificate(cert.read_bytes()),key,[])
with tarfile.open(fileobj=io.BytesIO(plain)) as archive:
    db_member=next(x for x in archive.getmembers() if x.name.endswith('.db'))
    with tempfile.TemporaryDirectory(dir=out) as temp:
        db=Path(temp)/'restored.db';db.write_bytes(archive.extractfile(db_member).read())
        c=sqlite3.connect(db);integrity=c.execute('PRAGMA integrity_check').fetchone()[0];c.close()
        if integrity!='ok':raise RuntimeError('Restored backup is invalid')
    media=next(x for x in archive.getmembers() if x.name=='media.tar.gz')
    restored_media_files=0
    with tarfile.open(fileobj=io.BytesIO(archive.extractfile(media).read()),mode='r:gz') as photos:
        with tempfile.TemporaryDirectory(dir=out) as temp:
            for member in photos.getmembers():
                relative=Path(member.name)
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='uploads' or member.issym() or member.islnk():raise RuntimeError('Unsafe media archive member')
                if member.isfile():
                    target=Path(temp)/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    original=photos.extractfile(member).read();target.write_bytes(original)
                    if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(original).digest():raise RuntimeError('Media restore mismatch')
                    restored_media_files+=1
    print(json.dumps({'encrypted_file':local.name,'restored_integrity':'ok','restored_media_files':restored_media_files}))
for old in out.iterdir():
    if re.fullmatch(r'bundle-\d{8}-\d{6}\.p7m',old.name) and old.is_file() and not old.is_symlink() and time.time()-old.stat().st_mtime>30*86400:old.unlink()
