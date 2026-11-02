"""Persist the existing HTTP gateway without changing its release endpoints.

Run as root on the release host. Docker cp remains compatible with the writable
directory mount used by the existing deployment and rollback scripts.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=120).stdout.strip()


def probe(expected):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, body in expected.items():
        with opener.open('http://127.0.0.1/' + name, timeout=10) as response:
            if response.read() != body:
                raise RuntimeError('HTTP manifest changed: ' + name)
    request = urllib.request.Request('http://127.0.0.1/', method='HEAD')
    with opener.open(request, timeout=15) as response:
        if not response.url.startswith('https://scientificexploration.art/'):
            raise RuntimeError('Canonical HTTPS redirect missing')


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the release host')
    root = Path('/opt/xiaoye-release')
    current = json.loads(run('docker', 'inspect', 'xiaoye-release'))[0]
    backup = Path('/opt/qingsu/backups') / ('http-persistence-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    (backup / 'container.json').write_text(json.dumps(current, indent=2))
    old_conf = run('docker', 'exec', 'xiaoye-release', 'cat',
                   '/etc/nginx/conf.d/default.conf') + '\n'
    (backup / 'default.conf').write_text(old_conf)
    conf = root / 'nginx'
    conf.mkdir(exist_ok=True)
    (conf / 'default.conf').write_text(old_conf)
    image = json.loads(run('docker', 'image', 'inspect', current['Image']))[0]
    image_ref = next((x for x in image.get('RepoDigests', [])
                      if x.startswith('nginx@sha256:')), current['Image'])
    compose = root / 'compose.yaml'
    if compose.exists():
        shutil.copy2(compose, backup / compose.name)
    compose.write_text('''name: xiaoye-release
services:
  http:
    image: ''' + image_ref + '''
    container_name: xiaoye-release
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - /opt/xiaoye-release/www:/usr/share/nginx/html:ro
      # Directory mount keeps docker cp in existing deployment scripts working.
      - /opt/xiaoye-release/nginx:/etc/nginx/conf.d
    network_mode: bridge
''')
    def dc(*args):
        return run('docker', 'compose', '-f', str(compose), *args)
    dc('config', '-q')
    run('docker', 'run', '--rm', '--network', 'none',
        '-v', str(conf) + ':/etc/nginx/conf.d:ro', image_ref, 'nginx', '-t')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    expected = {}
    for name in ('latest.json', 'latest-extensions.json', 'version.json'):
        with opener.open('http://127.0.0.1/' + name, timeout=15) as response:
            expected[name] = response.read()
    already_mounted = any(m['Destination'] == '/etc/nginx/conf.d'
                          and m['Source'] == str(conf) for m in current['Mounts'])
    retired = 'xiaoye-release-before-' + str(time.time_ns())
    try:
        if not already_mounted:
            run('docker', 'stop', 'xiaoye-release')
            run('docker', 'update', '--restart=no', 'xiaoye-release')
            run('docker', 'rename', 'xiaoye-release', retired)
        dc('up', '-d', '--pull', 'never', '--force-recreate')
        time.sleep(1)
        probe(expected)
        # Exercise the exact docker cp operation used by deployment/rollback.
        run('docker', 'cp', '/opt/qingsu/tls-http.conf',
            'xiaoye-release:/etc/nginx/conf.d/default.conf')
        run('docker', 'exec', 'xiaoye-release', 'nginx', '-t')
        run('docker', 'exec', 'xiaoye-release', 'nginx', '-s', 'reload')
        probe(expected)
        # A second recreation proves this config survives container replacement.
        dc('up', '-d', '--pull', 'never', '--force-recreate')
        time.sleep(1)
        probe(expected)
    except Exception:
        if not already_mounted:
            dc('down')
            run('docker', 'rename', retired, 'xiaoye-release')
            run('docker', 'update', '--restart=unless-stopped', 'xiaoye-release')
            run('docker', 'start', 'xiaoye-release')
        raise
    print(json.dumps({'backup': str(backup), 'compose': str(compose),
                      'manifest_preservation': 'ok', 'docker_cp': 'ok',
                      'container_recreation': 'ok',
                      'retired_container': None if already_mounted else retired}))


if __name__ == '__main__':
    main()
