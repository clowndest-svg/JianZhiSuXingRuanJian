"""Start an isolated candidate API behind a temporary, random TLS path."""
import json,re,subprocess
from pathlib import Path
base=Path('/opt/qingsu/releases/r131');config=json.loads(Path('/opt/qingsu/releases/qa-config.json').read_text())
prefix=config['prefix']
if not re.fullmatch('qa-[a-f0-9]{16}',prefix):raise SystemExit('Invalid QA path')
for name in ('qa-data','qa-uploads'):
    folder=base/name;folder.mkdir(exist_ok=True)
    subprocess.run(['chown','-R','qingsu:qingsu',str(folder)],check=True)
unit=f'''[Unit]
Description=Isolated Qingsu candidate API
[Service]
User=qingsu
WorkingDirectory={base}
Environment=QINGSU_DB_DIR={base}/qa-data
Environment=QINGSU_UPLOAD_DIR={base}/qa-uploads
Environment=QINGSU_WEB_DIR={base}/web
Environment=QINGSU_SITE_BASE={config['base']}
Environment=TZ=Asia/Taipei
Environment=QINGSU_CACHE_NAMESPACE=qingsu-qa
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/local/bin/uvicorn server:app --host 172.17.0.1 --port 18000 --no-access-log
Restart=on-failure
NoNewPrivileges=true
'''
Path('/etc/systemd/system/qingsu-qa.service').write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','qingsu-qa'],check=True)
nginx=Path('/opt/qingsu/tls/default.conf');s=nginx.read_text()
if f'location /{prefix}/' not in s:
    location=f'''    location /{prefix}/ {{
        proxy_pass http://172.17.0.1:18000/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }}
'''
    s=s.replace('    location / {',location+'    location / {');nginx.write_text(s)
subprocess.run(['docker','exec','qingsu-tls','nginx','-t'],check=True);subprocess.run(['docker','exec','qingsu-tls','nginx','-s','reload'],check=True)
print('Isolated candidate service started; production database unchanged.')
