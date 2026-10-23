"""Local operational checks; emits only aggregate numbers and service states."""
import json,math,os,pathlib,re,shutil,socket,struct,subprocess,time,urllib.request,ssl
from pathlib import Path
root=Path('/opt/qingsu');problems=[];report={'checked_at':int(time.time())}
ID_SEGMENT=re.compile(r'^(\d+|[0-9a-fA-F]{16,}(\.\w+)?|[0-9a-fA-F]{8}-[0-9a-fA-F-]{27})$')
ROUTE=re.compile(r'path=(.*?)\s+status=(\d+)\s+elapsed_ms=(\d+(?:\.\d+)?)')
FAILURE=re.compile(r'application_failure id=\S+ error=(\w+)')
CATEGORY_ORDER=('api','ai','media','ws','admin')

def route_template(token):
    """日志里的 path 片段归成路由模板：/api/posts/123 与 /api/posts/7 算同一个接口。

    server.py 现在只打首段（形如 ['api']），将来给到全路径时这里不用改。
    """
    parts=re.findall(r"'([^']*)'",token) if token.strip().startswith('[') else token.strip().split('/')
    return '/'+'/'.join('{id}' if ID_SEGMENT.match(part) else part for part in parts if part)

def request_rows(logs,category=None):
    """把日志抽成 (分类, 模板, 状态, 耗时)；抽不出来的行不算数，也不算 0。"""
    rows=[]
    for line in logs.splitlines():
        hit=ROUTE.search(line)
        if not hit:continue
        template=route_template(hit.group(1))
        rows.append((category or endpoint_category(template),template,int(hit.group(2)),float(hit.group(3))))
    return rows

def endpoint_category(template):
    parts=[part for part in template.split('/') if part]
    if not parts:return 'api'
    if parts[0]=='ws':return 'ws'
    if parts[0] in ('uploads','avatars','stickers') or 'media' in parts:return 'media'
    if any(part in ('ai','ask','asr') for part in parts):return 'ai'
    return 'admin' if parts[0] in ('admin','ops') else 'api'

def percentile(values,fraction=0.95):
    """近位排名：样本少的时候取的是偏大的那个，慢接口排名才可信。

    上面 report['p95_ms'] 那行老公式在样本数不足 20 时会落到最小值，那是既有告警口径，不跟着改。
    """
    if not values:return None
    ordered=sorted(values);index=max(0,min(len(ordered)-1,math.ceil(len(ordered)*fraction)-1))
    return round(ordered[index],1)

def slow_endpoints(rows,limit=5):
    """按模板给窗口内的接口排最慢前几名；没有读数就是 None，不写 0。"""
    buckets={}
    for _category,template,_status,elapsed in rows:buckets.setdefault(template,[]).append(elapsed)
    scored=[{'endpoint':template,'requests':len(values),'p95_ms':percentile(values)} for template,values in buckets.items()]
    return sorted(scored,key=lambda item:item['p95_ms'],reverse=True)[:limit]

def category_counts(rows,extra=None):
    counts={}
    for category in CATEGORY_ORDER:
        selected=[row for row in rows if row[0]==category]
        latencies=[row[3] for row in selected];statuses=[row[2] for row in selected]
        entry={'requests':len(selected) if selected else None,'errors_5xx':sum(status>=500 for status in statuses) if selected else None,
               'p95_ms':percentile(latencies),'readout':'无读数' if not selected else 'ok'}
        if extra and category in extra:entry.update(extra[category])
        counts[category]=entry
    return counts

def error_types(logs):
    found={}
    for name in FAILURE.findall(logs):found[name]=found.get(name,0)+1
    return found

def alert_state_path():
    # 落盘路径必须能覆盖：测试要能在临时目录里跑同一套去重逻辑
    return Path(os.environ.get('QINGSU_MONITOR_ALERT_STATE',str(root/'monitor/alerts.json')))

def read_alert_state(path):
    try:return json.loads(path.read_text())
    except Exception:return None

def diff_alerts(state,problems,now):
    """同一问题持续期间只报一次，消失时补一条恢复；上一轮状态从落盘文件读。"""
    previous=set((state or {}).get('problems',[]));current=set(problems)
    first_seen=dict((state or {}).get('first_seen',{}))
    for problem in current:first_seen.setdefault(problem,now)
    for problem in previous-current:first_seen.pop(problem,None)
    alerts={'new':sorted(current-previous),'recovered':sorted(previous-current),'ongoing':sorted(current&previous)}
    return alerts,{'problems':sorted(current),'first_seen':first_seen,'checked_at':now}

def journal(unit):
    return subprocess.run(['journalctl','-u',unit,'--since','5 minutes ago','--no-pager','-o','cat'],capture_output=True,text=True).stdout

def main():
    public_base=(root/'site-base').read_text().strip() if (root/'site-base').is_file() else 'https://124.220.54.64'
    if public_base not in ('https://124.220.54.64','https://scientificexploration.art'):raise SystemExit('Invalid active public site')
    for unit in ('qingsu','qingsu-llama','qingsu-backup.timer','qingsu-cert-renew.timer','coturn','qingsu-asr'):
        state=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True).stdout.strip();report[unit]=state
        if state!='active':problems.append(unit)
    ready=None
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(public_base+'/health/ready',timeout=10) as r:
            report['ready']=r.status;ready=json.load(r)
    except Exception:report['ready']=None;problems.append('https_readiness')
    try:
        probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);probe.settimeout(2)
        probe.sendto(struct.pack('!HHI',0x0001,0,0x2112A442)+bytes.fromhex('00112233445566778899aabb'),('127.0.0.1',3478))
        data,_=probe.recvfrom(256);probe.close()
        report['turn']=len(data)>=20 and struct.unpack('!H',data[:2])[0]==0x0101
    except Exception:
        report['turn']=False
    if not report['turn']:problems.append('turn')
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8071/health',timeout=5) as r:
            report['asr_http']=r.status
    except Exception:
        report['asr_http']=0
    if report['asr_http']!=200:problems.append('asr_http')

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
    logs=journal('qingsu')
    latencies=sorted(float(n) for n in re.findall(r'elapsed_ms=(\d+(?:\.\d+)?)',logs));statuses=re.findall(r'status=(\d+)',logs)
    report.update(requests=len(statuses),errors_5xx=sum(int(s)>=500 for s in statuses),p95_ms=round(latencies[max(0,int(len(latencies)*.95)-1)],1) if latencies else None,sqlite_lock_errors=logs.lower().count('database is locked'),cache_degraded=logs.count('cache_degraded'))
    if report['errors_5xx'] or report['sqlite_lock_errors'] or report['cache_degraded']:problems.append('application_errors')
    if report['p95_ms'] and report['p95_ms']>2000:problems.append('slow_requests')
    # 后台服务没装时不该把整轮监控判成红，但装了不看就是"后台坏了没人知道"
    ops=subprocess.run(['systemctl','is-active','qingsu-ops'],capture_output=True,text=True).stdout.strip()
    report['qingsu-ops']=ops
    if ops!='active' and subprocess.run(['systemctl','cat','qingsu-ops'],capture_output=True).returncode==0:problems.append('qingsu-ops')
    rows=request_rows(logs)+request_rows(journal('qingsu-ops'),'admin')
    report['slow_endpoints']=slow_endpoints(rows)
    # WS 这条链没有访问日志可归并，能借的只有 /health/ready 已有的连接与握手计数
    chat=ready.get('chat') if isinstance(ready,dict) else None
    report['categories']=category_counts(rows,{'ws':{'connected':chat.get('sockets'),'handshake_rejected':chat.get('rejected'),
        'redis':chat.get('redis')}} if chat else None)
    report['error_types']=error_types(logs)
    state_path=alert_state_path();alerts,state=diff_alerts(read_alert_state(state_path),problems,report['checked_at'])
    report['alerts']=alerts
    report['problems']=problems
    folder=root/'monitor';folder.mkdir(mode=0o700,exist_ok=True);(folder/'status.json').write_text(json.dumps(report))
    state_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);state_path.write_text(json.dumps(state))
    for line in ['ALERT problem=%s'%problem for problem in alerts['new']]+['RECOVERED problem=%s'%problem for problem in alerts['recovered']]:print(line)
    print(json.dumps(report));raise SystemExit(bool(problems))

if __name__=='__main__':main()
