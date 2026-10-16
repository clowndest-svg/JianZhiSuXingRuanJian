"""Server-side release switch with consistent backups and automatic code rollback."""
import argparse,json,os,shutil,sqlite3,subprocess,time,urllib.request
from datetime import datetime
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--revision',required=True);args=p.parse_args()
root=Path('/opt/qingsu');stage=Path(args.stage).resolve()
if os.geteuid()!=0 or stage.parent!=root/'releases' or not (stage/'server.py').is_file():raise SystemExit('Expected root and a prepared release directory')
def run(*cmd):return subprocess.run(cmd,check=True,capture_output=True,text=True).stdout.strip()
backup=root/'backups'/('release-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(mode=0o700)
for name in ('server.py','app_modules','web'):
    source=root/name
    if source.is_dir():shutil.copytree(source,backup/name)
    elif source.is_file():shutil.copy2(source,backup/name)
unit=Path('/etc/systemd/system/qingsu.service');shutil.copy2(unit,backup/'qingsu.service')
tls=root/'tls/default.conf';old_tls=tls.read_text();(backup/'nginx-tls.conf').write_text(old_tls)
old_http=run('docker','exec','xiaoye-release','cat','/etc/nginx/conf.d/default.conf');(backup/'nginx-http.conf').write_text(old_http)
source=sqlite3.connect(root/'data/qingsu.db');dest=sqlite3.connect(backup/'qingsu.db')
try:source.backup(dest);assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
finally:source.close();dest.close()
# A complete media snapshot is produced before the switch by the maintained backup task.
run('python3',str(root/'backup.py'))
def copy_files(src,dst):
    dst.mkdir(exist_ok=True)
    for file in src.iterdir():
        if file.is_file():
            temp=dst/(file.name+'.new');shutil.copy2(file,temp);os.replace(temp,dst/file.name)
def restart():run('systemctl','daemon-reload');run('systemctl','restart','qingsu')
try:
    shutil.copy2(stage/'server.py',root/'server.py.new');os.replace(root/'server.py.new',root/'server.py')
    if (root/'app_modules').exists():shutil.rmtree(root/'app_modules')
    shutil.copytree(stage/'app_modules',root/'app_modules');copy_files(stage/'web',root/'web')
    for name in ('backup.py','monitor.py'):shutil.copy2(stage/'scripts'/name,root/name)
    ips=[run('docker','inspect','-f','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',name) for name in ('xiaoye-release','qingsu-tls')]
    config=unit.read_text();import re
    config=re.sub(r'--forwarded-allow-ips=\S+','--forwarded-allow-ips='+','.join(ips),config)
    if 'QINGSU_CACHE_NAMESPACE=' not in config:config=config.replace('Environment=TZ=', 'Environment=QINGSU_CACHE_NAMESPACE=qingsu-prod\nEnvironment=TZ=')
    unit.write_text(config);restart()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(20):
        try:
            with opener.open('http://172.17.0.1:8000/health',timeout=2) as r:
                if json.load(r)['release']=='r131':break
        except Exception:time.sleep(.5)
    else:raise RuntimeError('Candidate readiness failed')
    # Keep QA routing until its final smoke test has completed; remove explicitly afterwards.
    new_tls=old_tls if 'gzip_min_length 1024;' in old_tls else old_tls.replace('    client_max_body_size 10m;','''    client_max_body_size 10m;
    access_log off;
    add_header Strict-Transport-Security "max-age=2592000" always;
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types application/json application/javascript text/css image/svg+xml;''')
    tls.write_text(new_tls);run('docker','exec','qingsu-tls','nginx','-t');run('docker','exec','qingsu-tls','nginx','-s','reload')
    # Preserve the unrelated release manifests and the ACME challenge route on port 80.
    redirected=re.sub(r'    location / \{.*?\n    \}', '    location / { return 308 https://124.220.54.64$request_uri; }',old_http,flags=re.S)
    if 'location = /version.json' not in redirected:
        redirected=redirected.replace('    location / {', '''    # Public update bootstrap for old Java HTTP clients that do not follow HTTPS redirects.
    location = /version.json { proxy_pass http://172.17.0.1:8000/version.json; }
    location / {''',1)
    if 'access_log off;' not in redirected:redirected=redirected.replace('server {','server {\n    access_log off;',1)
    http_file=root/'tls-http.conf';http_file.write_text(redirected)
    run('docker','cp',str(http_file),'xiaoye-release:/etc/nginx/conf.d/default.conf');run('docker','exec','xiaoye-release','nginx','-t');run('docker','exec','xiaoye-release','nginx','-s','reload')
    with opener.open('https://124.220.54.64/health/ready',timeout=10) as r:assert json.load(r)['release']=='r131'
    for kind,text in {'service':'''[Unit]
Description=Qingsu operational checks
[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/python3 /opt/qingsu/monitor.py
''','timer':'''[Unit]
Description=Check Qingsu health, errors, latency, backups, disk and certificate
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true
[Install]
WantedBy=timers.target
'''}.items():Path('/etc/systemd/system/qingsu-monitor.'+kind).write_text(text)
    run('systemctl','daemon-reload');run('systemctl','enable','--now','qingsu-monitor.timer')
    (root/'release.json').write_text(json.dumps({'release':'r131','source_revision':args.revision,'backup':str(backup)}))
    print(json.dumps({'deployed':'r131','backup':str(backup),'source_revision':args.revision}))
except Exception:
    shutil.copy2(backup/'server.py',root/'server.py')
    if (backup/'app_modules').exists():
        shutil.rmtree(root/'app_modules');shutil.copytree(backup/'app_modules',root/'app_modules')
    copy_files(backup/'web',root/'web');shutil.copy2(backup/'qingsu.service',unit)
    tls.write_text(old_tls);run('docker','exec','qingsu-tls','nginx','-s','reload')
    (root/'tls-http.conf').write_text(old_http);run('docker','cp',str(root/'tls-http.conf'),'xiaoye-release:/etc/nginx/conf.d/default.conf');run('docker','exec','xiaoye-release','nginx','-s','reload')
    restart();raise
