"""Local operational checks; emits only aggregate numbers and service states."""
import json,os,pathlib,re,shutil,socket,struct,subprocess,time,urllib.request,ssl
from pathlib import Path
root=Path('/opt/qingsu');problems=[];report={'checked_at':int(time.time())}
public_base=(root/'site-base').read_text().strip() if (root/'site-base').is_file() else 'https://124.220.54.64'
if public_base not in ('https://124.220.54.64','https://scientificexploration.art'):raise SystemExit('Invalid active public site')
for unit in ('qingsu','qingsu-llama','qingsu-backup.timer','qingsu-cert-renew.timer','coturn'):
    state=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True).stdout.strip();report[unit]=state
    if state!='active':problems.append(unit)
try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(public_base+'/health/ready',timeout=10) as r:report['ready']=r.status
except Exception:problems.append('https_readiness')
try:
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);probe.settimeout(2)
    probe.sendto(struct.pack('!HHI',0x0001,0,0x2112A442)+bytes.fromhex('00112233445566778899aabb'),('127.0.0.1',3478))
    data,_=probe.recvfrom(256);probe.close()
    report['turn']=len(data)>=20 and struct.unpack('!H',data[:2])[0]==0x0101
except Exception:
    report['turn']=False
if not report['turn']:problems.append('turn')

THRESHOLDS={'cpu_percent':85.0,'memory_percent':85.0,'swap_percent':25.0,'load_per_core':1.5,'disk_percent':85.0}
for _threshold in tuple(THRESHOLDS):
    _override=os.environ.get('QINGSU_MONITOR_'+_threshold.upper())
    if _override:
        try:THRESHOLDS[_threshold]=float(_override)
        except ValueError:pass
try:
    def _cpu_snapshot():
        parts=[int(x) for x in pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
        return sum(parts), parts[3]+(parts[4] if len(parts)>4 else 0)
    total1,idle1=_cpu_snapshot(); time.sleep(1); total2,idle2=_cpu_snapshot()
    report['cpu_percent']=round(100.0*(1-(idle2-idle1)/max(1,total2-total1)),1)
except Exception:
    report['cpu_percent']=None
try:
    mem={}
    for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1);mem[key]=int(value.strip().split()[0])
    total=mem.get('MemTotal',0); available=mem.get('MemAvailable',mem.get('MemFree',0))
    swap_total=mem.get('SwapTotal',0); swap_free=mem.get('SwapFree',0)
    report['memory_percent']=round(100.0*(total-available)/total,1) if total else None
    report['memory_available_mb']=available//1024
    report['swap_percent']=round(100.0*(swap_total-swap_free)/swap_total,1) if swap_total else 0.0
except Exception:
    report['memory_percent']=None;report['memory_available_mb']=None;report['swap_percent']=None
try:
    report['load1']=round(float(pathlib.Path('/proc/loadavg').read_text().split()[0]),2)
    cores=max(1,os.cpu_count() or 1)
    report['load_per_core']=round(report['load1']/cores,2)
except Exception:
    report['load1']=None;report['load_per_core']=None
usage=shutil.disk_usage('/')
report['free_disk_mb']=usage.free//1024//1024
report['disk_percent']=round(100.0*usage.used/usage.total,1) if usage.total else None
report['thresholds']=THRESHOLDS
if report['cpu_percent'] is not None and report['cpu_percent']>THRESHOLDS['cpu_percent']:problems.append('high_cpu')
if report['memory_percent'] is not None and report['memory_percent']>THRESHOLDS['memory_percent']:problems.append('low_memory')
if report['swap_percent'] is not None and report['swap_percent']>THRESHOLDS['swap_percent']:problems.append('high_swap')
if report['load_per_core'] is not None and report['load_per_core']>THRESHOLDS['load_per_core']:problems.append('high_load')
if report['free_disk_mb']<512 or (report['disk_percent'] is not None and report['disk_percent']>THRESHOLDS['disk_percent']):problems.append('low_disk')
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
