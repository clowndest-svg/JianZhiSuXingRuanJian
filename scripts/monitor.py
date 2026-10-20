"""Local operational checks; emits only aggregate numbers and service states."""
import json,re,shutil,subprocess,time,urllib.request,ssl
from pathlib import Path
root=Path('/opt/qingsu');problems=[];report={'checked_at':int(time.time())}
public_base=(root/'site-base').read_text().strip() if (root/'site-base').is_file() else 'https://124.220.54.64'
if public_base not in ('https://124.220.54.64','https://scientificexploration.art'):raise SystemExit('Invalid active public site')
for unit in ('qingsu','qingsu-llama','qingsu-backup.timer','qingsu-cert-renew.timer'):
    state=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True).stdout.strip();report[unit]=state
    if state!='active':problems.append(unit)
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(public_base+'/health/ready',timeout=10) as r:report['ready']=r.status
except Exception:problems.append('https_readiness')
report['free_disk_mb']=shutil.disk_usage(root).free//1024//1024
if report['free_disk_mb']<512:problems.append('low_disk')
backups=list((root/'backups/scheduled').glob('bundle-*.p7m'))
report['backup_age_hours']=round((time.time()-max((x.stat().st_mtime for x in backups),default=0))/3600,1)
if report['backup_age_hours']>26:problems.append('stale_backup')
expiry=subprocess.run(['openssl','x509','-enddate','-noout','-in','/etc/letsencrypt/live/'+public_base.split('://')[1]+'/cert.pem'],capture_output=True,text=True).stdout.strip()
from email.utils import parsedate_to_datetime
report['certificate_hours_left']=round((parsedate_to_datetime(expiry.split('=',1)[1]).timestamp()-time.time())/3600,1)
if report['certificate_hours_left']<48:problems.append('certificate_expiring')
logs=subprocess.run(['journalctl','-u','qingsu','--since','5 minutes ago','--no-pager','-o','cat'],capture_output=True,text=True).stdout
latencies=sorted(float(n) for n in re.findall(r'elapsed_ms=(\d+(?:\.\d+)?)',logs));statuses=re.findall(r'status=(\d+)',logs)
report.update(requests=len(statuses),errors_5xx=sum(int(s)>=500 for s in statuses),p95_ms=round(latencies[max(0,int(len(latencies)*.95)-1)],1) if latencies else None,sqlite_lock_errors=logs.lower().count('database is locked'),cache_degraded=logs.count('cache_degraded'))
if report['errors_5xx'] or report['sqlite_lock_errors'] or report['cache_degraded']:problems.append('application_errors')
if report['p95_ms'] and report['p95_ms']>2000:problems.append('slow_requests')
report['problems']=problems
folder=root/'monitor';folder.mkdir(mode=0o700,exist_ok=True);(folder/'status.json').write_text(json.dumps(report))
print(json.dumps(report));raise SystemExit(bool(problems))
