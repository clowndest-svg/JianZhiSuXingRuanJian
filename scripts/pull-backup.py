"""Pull a public-key-encrypted server backup and verify restore locally.

The decrypting key never leaves this workstation. Files are not Git artifacts.
"""
import argparse,subprocess,json,tempfile,sqlite3,io,tarfile,hashlib,re,time,shutil,os
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from datetime import datetime,timedelta,timezone
import secrets

root=Path(__file__).resolve().parents[1]
BUNDLE=re.compile(r'bundle-(\d{8})-(\d{6})\.p7m')
RETENTION_DAYS=30
DEFAULT_AGE_THRESHOLD=26.0

class BackupVerifyError(RuntimeError):
    """验证失败；文本直接进报告的 reason，不许只留一个退出码。"""

def bundle_stamp(name,now=None):
    """文件名里的服务器时间（服务器与本机同为东八区，所以按本地时间折秒）。"""
    hit=BUNDLE.fullmatch(name)
    if not hit:return None
    try:return time.mktime(time.strptime(hit.group(1)+'-'+hit.group(2),'%Y%m%d-%H%M%S'))
    except ValueError:return None

def age_report(directory,threshold=DEFAULT_AGE_THRESHOLD,now=None):
    """本机加密副本的年龄与容量；red 时必须说清是"这台电脑没跑成"还是"服务器没产出"。

    副本文件名里的时间是服务器产出时刻，mtime 是这台电脑落地时刻，两个都要看：
    只看落地时间会把"每天准时拉回一份三天前的旧备份"判成绿的。
    """
    now=now if now is not None else time.time()
    directory=Path(directory)
    if not directory.is_dir():
        return {'threshold_hours':round(threshold,1),'copies':0,'bytes':0,'free_disk_mb':None,
                'state':'red','status':'无本地副本','pulled_hours_ago':None,'server_age_hours':None,
                'reason':'本机备份目录 %s 都不存在，异地拉取从没落地（不是"年龄 0 小时"）'%directory}
    bundles=[item for item in directory.glob('bundle-*.p7m') if item.is_file() and not item.is_symlink()]
    usage=shutil.disk_usage(directory)
    entry={'threshold_hours':round(threshold,1),'copies':len(bundles),
           'bytes':sum(item.stat().st_size for item in bundles),'free_disk_mb':usage.free//1024//1024}
    if not bundles:
        return dict(entry,state='red',status='无本地副本',pulled_hours_ago=None,server_age_hours=None,
                    reason='这台电脑上一个加密副本都没有，异地备份根本没落地')
    newest=max(bundles,key=lambda item:item.stat().st_mtime)
    pulled=(now-newest.stat().st_mtime)/3600
    stamp=bundle_stamp(newest.name)
    data_age=(now-stamp)/3600 if stamp is not None else None
    entry.update(newest=newest.name,pulled_hours_ago=round(pulled,1),
                 server_age_hours=round(data_age,1) if data_age is not None else None)
    if data_age is None:entry.update(state='red' if pulled>threshold else 'green',
        reason='' if pulled<=threshold else '最新副本的文件名不是 bundle-YYYYMMDD-HHMMSS.p7m，只能按落地时间判：%s 小时'%round(pulled,1))
    elif data_age<-1:entry.update(state='red',reason='文件名里的服务器时间比落地时间还新，本机时钟或副本名有问题')
    elif data_age<=threshold and pulled<=threshold:entry.update(state='green',reason='')
    elif pulled<=threshold:entry.update(state='red',
        reason='拉取一直在跑，但拉回来的这份在服务器上已经放了 %s 小时——服务器没产出新备份'%round(data_age,1))
    else:entry.update(state='red',
        reason='这台电脑已经 %s 小时没拉成备份（计划任务没跑：关机、离线或用户未登录），最新一份数据年龄 %s 小时'
               %(round(pulled,1),round(data_age,1)))
    return entry

def decrypt_bundle(path,cert,private,password):
    if not path.is_file():raise BackupVerifyError('找不到加密副本：%s'%path)
    if not cert.is_file() or not private.is_file() or not password.is_file():
        raise BackupVerifyError('解密用的证书/私钥/口令不齐：%s'%cert.parent)
    try:
        key=serialization.load_pem_private_key(private.read_bytes(),password.read_bytes())
        return pkcs7.pkcs7_decrypt_der(path.read_bytes(),x509.load_pem_x509_certificate(cert.read_bytes()),key,[])
    except BackupVerifyError:raise
    except Exception as error:raise BackupVerifyError('解密失败（私钥口令不对或副本被截断）：%s'%type(error).__name__)

def safe_member(name,allowed_prefix):
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!=allowed_prefix:
        raise BackupVerifyError('备份里有不安全的路径成员：%s'%name)

def verify_plaintext(plain,media_sample=25):
    """解密后的 tar：库做完整性+外键+记录数，媒体全量核路径、抽样真还原并比哈希。"""
    try:
        archive=tarfile.open(fileobj=io.BytesIO(plain))
    except tarfile.TarError as error:
        raise BackupVerifyError('解密出来的东西不是合法 tar（副本被截断？）：%s'%error)
    with archive:
        members={item.name:item for item in archive.getmembers()}
        if 'qingsu.db' not in members:raise BackupVerifyError('备份包里没有 qingsu.db')
        if 'media.tar.gz' not in members:raise BackupVerifyError('备份包里没有 media.tar.gz')
        # 临时目录自己清：Windows 上 sqlite 句柄释放比 TemporaryDirectory 晚，用它会在成功之后抛 PermissionError
        temp=tempfile.mkdtemp()
        try:
            db=Path(temp)/'restored.db';db.write_bytes(archive.extractfile(members['qingsu.db']).read())
            try:
                conn=sqlite3.connect(db);conn.execute('PRAGMA busy_timeout=5000')
                integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
                violations=conn.execute('PRAGMA foreign_key_check').fetchall()
                tables=[row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                counts={name:conn.execute('SELECT COUNT(*) FROM "%s"'%name.replace('"','""')).fetchone()[0] for name in tables}
                conn.close()
            except sqlite3.Error as error:
                raise BackupVerifyError('恢复数据库副本打不开：%s'%error)
        finally:
            shutil.rmtree(temp,ignore_errors=True)
        if integrity!='ok':raise BackupVerifyError('解出来的库 integrity_check=%s，不是 ok'%integrity)
        if violations:raise BackupVerifyError('解出来的库有 %d 条外键不自洽'%len(violations))
        photos_raw=archive.extractfile(members['media.tar.gz']).read()
        try:
            photos_tar=tarfile.open(fileobj=io.BytesIO(photos_raw),mode='r:gz')
        except tarfile.TarError as error:
            raise BackupVerifyError('媒体包打不开（不是合法 tar.gz）：%s'%error)
        with photos_tar as photos:
            files=[item for item in photos.getmembers() if item.isfile()]
            for item in photos.getmembers():
                if item.issym() or item.islnk():raise BackupVerifyError('媒体包里带链接成员：%s'%item.name)
                safe_member(item.name,'uploads')
            # 抽样而不是全量：一次 30MB 视频的整包还原会把计划任务拖到天亮
            step=max(1,len(files)//max(1,media_sample))
            picked=files[::step][:media_sample]
            temp=tempfile.mkdtemp()
            try:
                for member in picked:
                    safe_member(member.name,'uploads')
                    target=Path(temp)/Path(member.name);target.parent.mkdir(parents=True,exist_ok=True)
                    original=photos.extractfile(member).read();target.write_bytes(original)
                    if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(original).digest():
                        raise BackupVerifyError('媒体还原后哈希对不上：%s'%member.name)
            finally:
                shutil.rmtree(temp,ignore_errors=True)
        return {'restored_integrity':'ok','foreign_key_violations':len(violations),'tables':len(tables),
                'row_counts':counts,'media_files':len(files),'media_restored':len(picked)}

def verify_file(path,keys,media_sample=25):
    return verify_plaintext(decrypt_bundle(path,keys/'backup-recipient.pem',keys/'backup-private.pem',keys/'backup-password.txt'),media_sample)

def ensure_keys(keys):
    private=keys/'backup-private.pem';cert=keys/'backup-recipient.pem';password=keys/'backup-password.txt'
    if not private.exists():
        keys.mkdir(parents=True,exist_ok=True)
        secret=secrets.token_urlsafe(48).encode();password.write_bytes(secret)
        key=rsa.generate_private_key(public_exponent=65537,key_size=4096)
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(secret)))
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Qingsu Backup Recipient')]);now=datetime.now(timezone.utc)
        certificate=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650)).sign(key,hashes.SHA256())
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return private,cert,password

def write_report(report,path):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=1))

def prune(directory):
    for old in directory.iterdir():
        if BUNDLE.fullmatch(old.name) and old.is_file() and not old.is_symlink() and time.time()-old.stat().st_mtime>RETENTION_DAYS*86400:
            old.unlink()

def pull(keys,out,remote_dir='/opt/qingsu/backups/scheduled'):
    ssh_key=keys/'backup-access.pem'
    base=['ssh','-i',str(ssh_key),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@124.220.54.64']
    subprocess.run([*base,'python3 /opt/qingsu/backup.py'],check=True)
    remote=subprocess.check_output([*base,"find %s -maxdepth 1 -name 'bundle-*.p7m' -type f | sort | tail -1"%remote_dir],text=True).strip()
    if not remote.startswith(remote_dir+'/bundle-') or not remote.endswith('.p7m'):raise RuntimeError('Unexpected backup name')
    out.mkdir(exist_ok=True);local=out/Path(remote).name
    subprocess.run(['scp','-i',str(ssh_key),'-o','BatchMode=yes','root@124.220.54.64:'+remote,str(local)],check=True)
    return local

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--key-dir',default=os.environ.get('QINGSU_BACKUP_KEY_DIR',r'D:\RuanJian\ShuJuChunChu\qingsu-signing'))
    parser.add_argument('--backup-dir',default=os.environ.get('QINGSU_BACKUP_LOCAL_DIR',str(root/'.private-backups')))
    parser.add_argument('--report',default=os.environ.get('QINGSU_BACKUP_REPORT'))
    parser.add_argument('--age-threshold-hours',type=float,default=float(os.environ.get('QINGSU_BACKUP_AGE_HOURS',DEFAULT_AGE_THRESHOLD)))
    args=parser.parse_args()
    keys=Path(args.key_dir);out=Path(args.backup_dir)
    key_files=(keys/'backup-private.pem',keys/'backup-recipient.pem',keys/'backup-password.txt')
    if args.prepare:
        if any(p.exists() for p in key_files) and not all(p.is_file() for p in key_files):
            raise BackupVerifyError('密钥材料不齐，拒绝覆盖已有材料；请从受保护备份恢复')
        ensure_keys(keys)
        print('Public encryption certificate prepared; private key remains local.');raise SystemExit(0)
    if not all(p.is_file() for p in key_files):
        raise BackupVerifyError('密钥材料不齐，验证/拉取不会自动生成替换密钥')
    report={'checked_at':int(time.time()),'backup_dir':str(out),'status':'unknown','reason':'','age':None,'verify':None}
    try:
        if args.verify_only:
            bundles=[item for item in out.glob('bundle-*.p7m') if item.is_file() and not item.is_symlink()]
            if not bundles:raise BackupVerifyError('本机没有加密副本可验')
            local=max(bundles,key=lambda item:item.stat().st_mtime)
        else:local=pull(keys,out)
        report['verify']=verify_file(local,keys);report['verify']['encrypted_file']=local.name
    except Exception as error:
        report['status']='red'
        report['reason']=str(error) if isinstance(error,BackupVerifyError) else '%s：%s'%(type(error).__name__,str(error) or '无信息')
    report['age']=age_report(out,args.age_threshold_hours)
    if report['status']!='red':
        if report['age']['state']=='green':report['status']='green'
        else:report['status']='red';report['reason']=report['age']['reason']
    report['retention_days']=RETENTION_DAYS
    path=Path(args.report) if args.report else out/'verify-report.json'
    try:write_report(report,path)
    except OSError as error:report['report_error']=str(error)
    prune(out)
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(1 if report['status']=='red' else 0)

if __name__=='__main__':main()
