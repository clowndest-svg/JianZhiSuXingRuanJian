"""Install the pinned Apache-2.0 local vision model without replacing text AI.

Run as root on the existing Qingsu Linux host. Downloads contain weights only;
no remote Python code or installer is executed. Existing API settings survive.
"""
import grp,hashlib,json,os,pathlib,pwd,subprocess,urllib.request
ROOT=pathlib.Path('/opt/qingsu')
REPO='ggml-org/InternVL3-1B-Instruct-GGUF'
REVISION='c622c04f3b46dc8ef733ca64ffb25a800c4041cc'
FILES={'InternVL3-1B-Instruct-Q8_0.gguf':'e87f98e2945c91da1a324034143f2f3bad014dcf6b34d440fcf885c00704378f',
       'mmproj-InternVL3-1B-Instruct-Q8_0.gguf':'2d92c4d3dd95ae6a5974f48a1e6a77817ef6970b0eb09a48dd63ad95b69ea7e5'}

def digest(p):
    with p.open('rb') as h:return hashlib.file_digest(h,'sha256').hexdigest()

def main():
    if os.name!='posix' or os.geteuid()!=0:raise SystemExit('Run as root on the Qingsu Linux host')
    binary=ROOT/'llama/llama-b11669/llama-server'
    if not binary.is_file():raise SystemExit('Expected existing pinned llama.cpp b11669 runtime')
    models=ROOT/'models/internvl3-1b';models.mkdir(parents=True,exist_ok=True)
    for name,expected in FILES.items():
        target=models/name
        if target.is_file() and digest(target)==expected:continue
        partial=target.with_suffix('.gguf.part')
        try:
            with urllib.request.urlopen('https://hf-mirror.com/'+REPO+'/resolve/'+REVISION+'/'+name,timeout=60) as response,partial.open('wb') as output:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    output.write(chunk)
            if digest(partial)!=expected:raise RuntimeError('Model checksum mismatch')
            partial.replace(target)
        finally:partial.unlink(missing_ok=True)
    (models/'source.json').write_text(json.dumps({'repo':REPO,'revision':REVISION,'sha256':FILES,'license':'Apache-2.0'}))
    gid=grp.getgrnam('qingsu').gr_gid;uid=pwd.getpwnam('qingsu-ops').pw_uid
    folder=ROOT/'vision-config';folder.mkdir(exist_ok=True);os.chown(folder,uid,gid);folder.chmod(0o750)
    cfg=folder/'vision.json'
    if not cfg.exists():cfg.write_text(json.dumps({'enabled':True,'mode':'local','base_url':'http://127.0.0.1:8082/v1','model':'internvl3-1b','api_key':''}))
    os.chown(cfg,uid,gid);cfg.chmod(0o640)
    unit=pathlib.Path('/etc/systemd/system/qingsu-vision.service')
    unit.write_text('''[Unit]
Description=Qingsu local open source food vision
After=network.target
[Service]
User=qingsu
Group=qingsu
ExecStart=/opt/qingsu/llama/llama-b11669/llama-server -m /opt/qingsu/models/internvl3-1b/InternVL3-1B-Instruct-Q8_0.gguf --mmproj /opt/qingsu/models/internvl3-1b/mmproj-InternVL3-1B-Instruct-Q8_0.gguf --host 127.0.0.1 --port 8082 --alias internvl3-1b -c 4096 -t 2 --parallel 1 --no-warmup
Restart=on-failure
RestartSec=10
MemoryHigh=1100M
MemoryMax=1400M
CPUQuota=150%
Nice=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
''')
    dropin=pathlib.Path('/etc/systemd/system/qingsu-ops.service.d/vision.conf');dropin.parent.mkdir(exist_ok=True)
    dropin.write_text('[Service]\nReadWritePaths=/opt/qingsu/vision-config\n')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','qingsu-vision'],check=True)
    subprocess.run(['systemctl','restart','qingsu-ops'],check=True)
    print(json.dumps({'model':'internvl3-1b','revision':REVISION,'sha256':FILES,'listen':'127.0.0.1:8082'}))

if __name__=='__main__':main()
