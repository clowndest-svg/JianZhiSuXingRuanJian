"""Run every local regression sequentially, recording exits and skipped checks."""
import argparse,json,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=('python','node','browser'),required=True);args=p.parse_args()
    folder=ROOT/'_audit_sandbox'/('full-'+args.kind+'-'+str(int(time.time())));folder.mkdir()
    if args.kind=='python':files=sorted((ROOT/'tests').glob('test_*.py'))+[ROOT/'tests/legacy-backend.py']
    elif args.kind=='node':files=[ROOT/'tests'/n for n in ('legacy-frontend.mjs','frontend-integration.mjs','pwa-cache-contract.mjs','frontend-budget.mjs','request-contract.mjs','ai-status-ui.mjs','dm-asr-race.mjs','dm-state-call.mjs','exercise-video.mjs','home-first-screen.mjs')]
    else:files=[ROOT/'tests'/n for n in ('runtime-ui.mjs','bubble-themes-ui.mjs','chat-ui.mjs','chat-history-ui.mjs','training-ui.mjs','media-cache-ui.mjs','recovery-ui.mjs','offline-day-ui.mjs','a11y-dialog-contract.mjs','records-profile-permission.mjs','admin-pagination-ui.mjs')]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',QINGSU_REQUIRE_REDIS='1',QINGSU_TEST_PYTHON=sys.executable,QINGSU_APP_REPO=str(ROOT),QINGSU_ADMIN_REPO=str(ROOT.parent/'JianZhiSuXingRuanJianHouTai'))
    result=[]
    for file in files:
        start=time.monotonic();command=[sys.executable if args.kind=='python' else 'node',str(file)]
        try:
            done=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=360)
            output=done.stdout+'\n'+done.stderr;code=done.returncode
        except subprocess.TimeoutExpired as e:output='TIMEOUT';code=124
        (folder/(file.name+'.log')).write_text(output,encoding='utf-8')
        entry={'suite':file.name,'exit':code,'seconds':round(time.monotonic()-start,2),'skipped':re.findall(r'(?:skipped[= ]+|SKIPPED=)(\d+)',output,re.I)};result.append(entry)
        (folder/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(entry),flush=True)
    print('RESULTS='+str(folder),flush=True)
    return int(any(r['exit'] for r in result))
if __name__=='__main__':sys.exit(main())
