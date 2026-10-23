"""Bounded QA-only sustained variant of the committed disposable workload."""
import json,pathlib,threading,time,sys,os,signal,hashlib
source=pathlib.Path(sys.argv[1]).resolve()
assert source.is_relative_to(pathlib.Path('/opt/qingsu/releases')) and source.name=='performance.py'
text=source.read_text()
anchor='with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:results=list(pool.map(call,range(400)))'
assert text.count(anchor)==1
text=text.replace(anchor,'with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:\n                    results=[]\n                    while time.perf_counter()-started<900:\n                        results.extend(pool.map(call,range(400)))')
text=text.replace("int(time.time())+600)","int(time.time())+7200)")
text=text.replace("'concurrency':20", "'concurrency':5")
text=text.replace("'5xx':errors", "'status_counts':{str(s):sum(x[1]==s for x in results) for s in set(x[1] for x in results)},'5xx':errors")
samples=[];stop=threading.Event();breach=[]
def sample():
    low=0
    while not stop.is_set():
        mem={k:int(v.split()[0]) for k,v in (l.split(':',1) for l in pathlib.Path('/proc/meminfo').read_text().splitlines())}
        vm=dict(l.split() for l in pathlib.Path('/proc/vmstat').read_text().splitlines())
        samples.append({'at':time.time(),'available_mb':round(mem['MemAvailable']/1024,1),'swap_used_mb':round((mem['SwapTotal']-mem['SwapFree'])/1024,1),'swap_in_pages':int(vm['pswpin']),'swap_out_pages':int(vm['pswpout'])})
        low=low+1 if mem['MemAvailable']<512*1024 else 0
        if low>=3:
            breach.append('MemAvailable below 512MiB for three samples');os.kill(os.getpid(),signal.SIGINT);return
        stop.wait(2)
t=threading.Thread(target=sample,daemon=True);t.start()
try:exec(compile(text,str(source),'exec'),{'__file__':str(source),'__name__':'__main__'})
finally:
    stop.set();t.join(3)
    cg=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/self/cgroup').read_text().split('::',1)[1].strip().lstrip('/')
    resource={'scope':'isolated disposable QA database and localhost API; not production account traffic','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'samples':samples,'minimum_available_mb':min(s['available_mb'] for s in samples),'safety_stop':breach,'cgroup':{n:(cg/n).read_text().strip() for n in ['memory.peak','memory.max','cpu.max','memory.events'] if (cg/n).exists()}}
    pathlib.Path('/opt/qingsu/releases/load-r180-5-resources.json').write_text(json.dumps(resource,indent=2))
