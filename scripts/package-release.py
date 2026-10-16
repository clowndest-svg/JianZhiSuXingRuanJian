"""Create a reviewable release archive from explicit application paths only."""
import argparse,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
with tarfile.open(args.output,'w') as archive:
    for name in ('server.py','app_modules','tests','requirements.txt','requirements.lock','requirements-dev.txt','scripts'):
        archive.add(root/name,arcname=name,filter=lambda m:None if '__pycache__' in m.name else m)
    for file in (root/'app/src/main/assets').iterdir():
        if file.is_file():archive.add(file,arcname='web/'+file.name)
    # 3D 依赖与模型在子目录里：以前这里只收顶层文件，网页版会 404 到
    # 只剩画块兜底，看起来像"3D 没生效"而不是"少发了文件"
    for sub in ('vendor','models'):
        base=root/'app/src/main/assets'/sub
        if not base.is_dir():raise SystemExit('缺少发布必需目录: '+str(base))
        for file in sorted(base.iterdir()):
            if file.is_file() and file.suffix.lower() in ('.js','.glb','.md','.json'):
                archive.add(file,arcname='web/'+sub+'/'+file.name)
    archive.add(root/'app/src/main/assets/guidance.json',arcname='app/src/main/assets/guidance.json')
    archive.add(root/'app/src/main/web_version.json',arcname='web/version.json')
    archive.add(root/'qingsu.apk',arcname='web/qingsu.apk')
print('Release archive created; keys, database, backups and scratch files excluded.')
