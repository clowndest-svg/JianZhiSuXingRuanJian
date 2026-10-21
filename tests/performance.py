"""Disposable 100-user/year workload against a real local Uvicorn process."""
import concurrent.futures,hashlib,importlib.util,json,os,sqlite3,subprocess,sys,tempfile,time,urllib.request
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
    (ROOT/'_audit_sandbox').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'_audit_sandbox') as temp:
        env=os.environ.copy()
        for kind in ('DB','UPLOAD','WEB'):env['QINGSU_'+kind+'_DIR']=temp+'/'+kind
        env['QINGSU_CACHE_NAMESPACE']='qingsu-performance';env['PYTHONDONTWRITEBYTECODE']='1'
        os.environ.update({k:v for k,v in env.items() if k.startswith('QINGSU_')})
        spec=importlib.util.spec_from_file_location('perf_server',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        c=m.get_db();start=date.today()-timedelta(days=364);stamp=start.isoformat()+' 00:00:00'
        c.executemany('INSERT INTO users(id,username,password_hash,nickname,created_at) VALUES (?,?,?,?,?)',[(i,'synthetic'+str(i),'not-a-login-hash','synthetic',stamp) for i in range(1,101)])
        c.executemany('INSERT INTO profiles(user_id,gender,age,height,weight_jin,target_weight_jin,goal_type,cycle_started_at) VALUES (?,?,?,?,?,?,?,?)',[(i,'female',30,170,160,140,'tone',stamp) for i in range(1,101)])
        c.executemany('INSERT INTO sessions(user_id,token_hash,expires_at) VALUES (?,?,?)',[(i,hashlib.sha256(('perf-'+str(i)).encode()).hexdigest(),int(time.time())+600) for i in range(1,101)])
        for uid in range(1,101):
            rows=[(uid,(start+timedelta(days=d)).isoformat()) for d in range(365)]
            c.executemany("INSERT INTO food_logs(user_id,log_date,slot,food_name,cal,created_at) VALUES (?,?,'午餐','synthetic',600,'synthetic')",rows)
            c.executemany("INSERT INTO weight_logs(user_id,log_date,weight_jin,created_at) VALUES (?,?,160,'synthetic')",rows)
            c.executemany("INSERT INTO workout_logs(user_id,log_date,duration_minutes,cal_burned,created_at) VALUES (?,?,20,180,'synthetic')",rows)
        c.commit();c.close()
        base='http://127.0.0.1:18001';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with open(temp+'/server.log','w') as log:
            proc=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','18001','--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(80):
                    try:
                        with opener.open(base+'/health',timeout=1):break
                    except Exception:time.sleep(.1)
                else:raise RuntimeError('Performance API did not start')
                def call(n):
                    uid=n%100+1;path=['/api/dashboard','/api/charts','/api/habits','/api/water/update'][n%4]
                    body=b'{"cups_count":3}' if path.endswith('update') else None
                    req=urllib.request.Request(base+path,data=body,headers={'Authorization':'Bearer perf-'+str(uid),'Content-Type':'application/json'})
                    t=time.perf_counter()
                    try:
                        with opener.open(req,timeout=30) as response:response.read();status=response.status
                    except Exception:status=599
                    return path,status,(time.perf_counter()-t)*1000
                started=time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:results=list(pool.map(call,range(400)))
                latency=sorted(x[2] for x in results);errors=sum(x[1]>=500 for x in results)
                report={'users':100,'days_per_user':365,'seeded_rows':109500,'concurrency':20,'requests':len(results),'elapsed_s':round(time.perf_counter()-started,2),'p50_ms':round(latency[len(latency)//2],1),'p95_ms':round(latency[int(len(latency)*.95)-1],1),'5xx':errors}
            finally:proc.terminate();proc.wait(timeout=15)
        text=Path(temp+'/server.log').read_text(errors='replace');report['sqlite_lock_errors']=text.lower().count('database is locked')
        # Module initialization holds a timed rotating file handler here on Windows.
        # Close only handlers backed by this disposable test directory.
        import logging
        for handler in list(logging.getLogger().handlers):
            filename=getattr(handler,'baseFilename','')
            if filename and Path(filename).resolve().is_relative_to(Path(temp).resolve()):
                logging.getLogger().removeHandler(handler);handler.close()
        print(json.dumps(report));return int(errors>0 or report['sqlite_lock_errors']>0 or report['p95_ms']>=500)
if __name__=='__main__':sys.exit(main())
