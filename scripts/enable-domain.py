"""Provision the canonical domain while retaining the IP upgrade endpoint.

Run as root on the release host. Existing proxy locations and other HTTP
services are preserved. Backups are retained and configuration is rolled back
if nginx validation or a local TLS probe fails.
"""
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

DOMAIN = 'scientificexploration.art'
ROOT = Path('/opt/qingsu')


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Command failed: ' + Path(args[0]).name + '\n' + result.stdout[-3000:] + result.stderr[-3000:])
    return result.stdout


def configure(tls, http):
    if 'server_name ' + DOMAIN + ';' not in tls:
        start = tls.index('server {')
        base = tls[start:]
        domain = base.replace('server_name 124.220.54.64;', 'server_name ' + DOMAIN + ';')
        domain = domain.replace('/live/124.220.54.64/', '/live/' + DOMAIN + '/')
        alias = '''
server {
    listen 443 ssl;
    server_name www.scientificexploration.art;
    ssl_certificate /etc/letsencrypt/live/scientificexploration.art/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/scientificexploration.art/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log off;
    return 308 https://scientificexploration.art$request_uri;
}
'''
        tls += '\n' + domain + '\n' + alias
    http = http.replace('https://124.220.54.64$request_uri', 'https://' + DOMAIN + '$request_uri')
    return tls, http


def main():
    import os
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the release host')
    # Uses the existing ACME webroot; port 80 remains available throughout.
    run('/opt/qingsu/certbot-env/bin/certbot', 'certonly', '--webroot',
        '-w', '/opt/xiaoye-release/www', '--cert-name', DOMAIN,
        '-d', DOMAIN, '-d', 'www.' + DOMAIN, '--non-interactive',
        '--agree-tos', '--register-unsafely-without-email', '--keep-until-expiring')
    path = ROOT / 'tls/default.conf'
    old_tls = path.read_text()
    old_http = run('docker', 'exec', 'xiaoye-release', 'cat', '/etc/nginx/conf.d/default.conf')
    new_tls, new_http = configure(old_tls, old_http)
    backup = ROOT / 'backups' / ('domain-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    unit = Path('/etc/systemd/system/qingsu.service')
    old_unit = unit.read_text()
    active = ROOT / 'site-base'
    old_active = active.read_text() if active.exists() else None
    (backup / 'qingsu.service').write_text(old_unit)
    (backup / 'tls.conf').write_text(old_tls)
    (backup / 'http.conf').write_text(old_http)
    http_path = ROOT / 'tls-http.conf'
    try:
        # Preserve inode: default.conf is a single-file bind mount.
        path.write_text(new_tls)
        run('docker', 'exec', 'qingsu-tls', 'nginx', '-t')
        run('docker', 'exec', 'qingsu-tls', 'nginx', '-s', 'reload')
        http_path.write_text(new_http)
        run('docker', 'cp', str(http_path), 'xiaoye-release:/etc/nginx/conf.d/default.conf')
        run('docker', 'exec', 'xiaoye-release', 'nginx', '-t')
        run('docker', 'exec', 'xiaoye-release', 'nginx', '-s', 'reload')
        time.sleep(1)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for host in (DOMAIN, 'www.' + DOMAIN, '124.220.54.64'):
            with opener.open('https://' + host + '/health/ready', timeout=15) as response:
                assert json.load(response)['status'] == 'ok'
        config = re.sub(r'Environment=QINGSU_SITE_BASE=.*', 'Environment=QINGSU_SITE_BASE=https://' + DOMAIN, old_unit)
        if 'Environment=QINGSU_SITE_BASE=' not in config:
            config = config.replace('[Service]', '[Service]\nEnvironment=QINGSU_SITE_BASE=https://' + DOMAIN)
        unit.write_text(config)
        active.write_text('https://' + DOMAIN + '\n')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'qingsu')
        for attempt in range(30):
            try:
                with opener.open('https://' + DOMAIN + '/health/ready', timeout=5) as response:
                    if json.load(response).get('site_base') == 'https://' + DOMAIN:
                        break
            except OSError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('Canonical site did not become active')
        print(json.dumps({'domain': DOMAIN, 'https': 'ok', 'ip_compatibility': 'ok', 'backup': str(backup)}))
    except Exception:
        unit.write_text(old_unit)
        if old_active is None:
            active.unlink(missing_ok=True)
        else:
            active.write_text(old_active)
        path.write_text(old_tls)
        run('docker', 'exec', 'qingsu-tls', 'nginx', '-s', 'reload')
        http_path.write_text(old_http)
        run('docker', 'cp', str(http_path), 'xiaoye-release:/etc/nginx/conf.d/default.conf')
        run('docker', 'exec', 'xiaoye-release', 'nginx', '-s', 'reload')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'qingsu')
        raise


if __name__ == '__main__':
    main()
