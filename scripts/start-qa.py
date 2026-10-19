"""Start an isolated candidate API on the server's private Docker bridge."""
import argparse,json,re,subprocess,time,urllib.error,urllib.request
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--release',required=True,help='candidate release folder name, for example r155')
args=parser.parse_args()
if not re.fullmatch(r'r[0-9]{3,}',args.release):raise SystemExit('Invalid release name')
releases=Path('/opt/qingsu/releases').resolve()
base=(releases/args.release).resolve()
if base.parent!=releases or not (base/'server.py').is_file():raise SystemExit('Candidate release not found')
config=json.loads((releases/'qa-config.json').read_text())
prefix=config['prefix']
if not re.fullmatch('qa-[a-f0-9]{16}',prefix):raise SystemExit('Invalid QA run id')
site_base=config.get('base')
if site_base!='http://172.17.0.1:18000':raise SystemExit('Invalid isolated QA service base')
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
Environment=QINGSU_SITE_BASE={site_base}
Environment=TZ=Asia/Taipei
Environment=QINGSU_CACHE_NAMESPACE=qingsu-qa
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/local/bin/uvicorn server:app --host 172.17.0.1 --port 18000 --no-access-log
Restart=on-failure
NoNewPrivileges=true
'''
Path('/etc/systemd/system/qingsu-qa.service').write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','qingsu-qa'],check=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline=time.monotonic()+45
while time.monotonic()<deadline:
    try:
        with opener.open(site_base+'/health/ready',timeout=2) as response:
            if response.status==200:
                break
    except (OSError,urllib.error.URLError):
        time.sleep(.25)
else:
    subprocess.run(['systemctl','stop','qingsu-qa'],check=False)
    raise SystemExit('Isolated QA service did not become ready on the private bridge')
print('Isolated candidate service started on the private bridge; production database and nginx are unchanged.')
