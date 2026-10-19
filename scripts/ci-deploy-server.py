#!/usr/bin/env python3
"""Narrow root-side deployment entry point for the dedicated qingsu-ci user.

Install this file as /usr/local/sbin/qingsu-ci-deploy, owned by root and mode
0755. The qingsu-ci account may sudo only this entry point. It accepts signed
release archives uploaded to /opt/qingsu/ci-incoming and never a shell command.
"""
import base64
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath


ROOT = Path("/opt/qingsu")
INCOMING = ROOT / "ci-incoming"
RELEASES = ROOT / "releases"
BACKUPS = ROOT / "backups"
PUBLIC_BASE = "https://124.220.54.64"


def run(label, *command, env=None, check=True):
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    if check and result.returncode:
        raise RuntimeError("%s failed (exit %d)" % (label, result.returncode))
    return result


def check_args(product, run_id, expected_hash, revision):
    if product not in ("main", "admin"):
        raise SystemExit("deployment target must be main or admin")
    if not re.fullmatch(r"[0-9]{3,}", run_id):
        raise SystemExit("invalid workflow run id")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
        raise SystemExit("invalid archive checksum")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise SystemExit("invalid Git revision")


def copy_verified_upload(product, run_id, expected_hash):
    source = INCOMING / (product + "-" + run_id + ".tar")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(source, flags)
    digest = hashlib.sha256()
    target = None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError("uploaded archive is not a regular file")
        if os.fstat(fd).st_size > 300 * 1024 * 1024:
            raise RuntimeError("uploaded archive exceeds the size limit")
        target_fd, target_name = tempfile.mkstemp(prefix="ci-" + product + "-", suffix=".tar", dir=str(ROOT))
        target = Path(target_name)
        with os.fdopen(target_fd, "wb") as output, os.fdopen(fd, "rb", closefd=False) as uploaded:
            while True:
                block = uploaded.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected_hash:
            raise RuntimeError("uploaded archive checksum mismatch")
        return target
    except Exception:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)


def safe_extract(archive_path, destination, allowed_roots, exact_files=None):
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    total = 0
    names = set()
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            if len(members) > 50000:
                raise RuntimeError("archive contains too many entries")
            for member in members:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                    raise RuntimeError("archive contains an unsafe path")
                if relative.parts[0] not in allowed_roots:
                    raise RuntimeError("archive contains an unexpected top-level path")
                if not (member.isdir() or member.isfile()):
                    raise RuntimeError("archive contains a link or special file")
                if member.isfile():
                    total += member.size
                    if total > 700 * 1024 * 1024:
                        raise RuntimeError("archive expands beyond the size limit")
                names.add(relative.as_posix())
                target = destination.joinpath(*relative.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("archive escapes its release directory")
                if member.isdir():
                    target.mkdir(mode=0o755, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("archive member could not be read")
                with stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        if exact_files is not None and names != exact_files:
            raise RuntimeError("admin archive must contain exactly the two expected files")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def atomic_write(path, contents, mode=0o644, uid=0, gid=0):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".new-", dir=str(path.parent))
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temp, uid, gid)
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def start_qa_config(release, prefix):
    config = RELEASES / "qa-config.json"
    if config.exists():
        raise RuntimeError("an existing QA config needs cleanup before a new deployment")
    payload = json.dumps({"prefix": prefix, "base": PUBLIC_BASE + "/" + prefix}, separators=(",", ":")).encode()
    atomic_write(config, payload, 0o600)
    run("start QA service", "python3", str(RELEASES / release / "scripts" / "start-qa.py"), "--release", release)


def cleanup_qa(release, prefix):
    config_path = RELEASES / "qa-config.json"
    nginx = ROOT / "tls" / "default.conf"
    cleanup_error = None
    if re.fullmatch(r"qa-[a-f0-9]{16}", prefix or "") and nginx.is_file():
        content = nginx.read_text(encoding="utf-8")
        pattern = re.compile(r"(?m)^    location /" + re.escape(prefix) + r"/ \{\n.*?^    \}\n?", re.S)
        changed, count = pattern.subn("", content, count=1)
        if count:
            try:
                atomic_write(nginx, changed.encode(), stat.S_IMODE(nginx.stat().st_mode), nginx.stat().st_uid, nginx.stat().st_gid)
                run("validate QA nginx cleanup", "docker", "exec", "qingsu-tls", "nginx", "-t")
                run("reload QA nginx cleanup", "docker", "exec", "qingsu-tls", "nginx", "-s", "reload")
            except Exception as error:
                cleanup_error = error
                atomic_write(nginx, content.encode(), stat.S_IMODE(nginx.stat().st_mode), nginx.stat().st_uid, nginx.stat().st_gid)
                run("restore QA nginx config after cleanup error", "docker", "exec", "qingsu-tls", "nginx", "-s", "reload", check=False)
    try:
        run("stop QA service", "systemctl", "stop", "qingsu-qa", check=False)
        unit = Path("/etc/systemd/system/qingsu-qa.service")
        unit.unlink(missing_ok=True)
        run("reload systemd after QA cleanup", "systemctl", "daemon-reload", check=False)
    except Exception as error:
        cleanup_error = cleanup_error or error
    stage = (RELEASES / release).resolve()
    if stage.parent == RELEASES.resolve():
        for name in ("qa-data", "qa-uploads"):
            folder = stage / name
            if folder.is_dir() and folder.parent == stage:
                shutil.rmtree(folder)
    if config_path.exists():
        try:
            if json.loads(config_path.read_text()).get("prefix") == prefix:
                config_path.unlink()
        except Exception:
            pass
    if cleanup_error:
        raise RuntimeError("QA cleanup did not finish cleanly") from cleanup_error


def production_verify(stage, release, revision):
    env = dict(os.environ, QINGSU_VERIFY_BASE="http://172.17.0.1:8000",
               QINGSU_VERIFY_DB=str(ROOT / "data" / "qingsu.db"), PYTHONDONTWRITEBYTECODE="1")
    run("production API smoke test", "python3", str(stage / "scripts" / "verify_live.py"), env=env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(PUBLIC_BASE + "/health/ready", timeout=15) as response:
        ready = json.load(response)
    if ready.get("source_revision") != revision or ready.get("release") != release:
        raise RuntimeError("public health endpoint does not report the deployed revision")
    with opener.open(PUBLIC_BASE + "/version.json", timeout=15) as response:
        manifest = json.load(response)
    if int(manifest.get("version_code", 0)) <= 0:
        raise RuntimeError("public Android release manifest is invalid")
    digest = hashlib.sha256()
    with opener.open(PUBLIC_BASE + "/qingsu.apk?ci=" + release, timeout=30) as response:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if digest.hexdigest() != manifest.get("sha256"):
        raise RuntimeError("public APK does not match the public release manifest")


def restore_main(backup, previous_release):
    run("stop service before rollback", "systemctl", "stop", "qingsu")
    shutil.copy2(backup / "server.py", ROOT / "server.py")
    old_modules = ROOT / "app_modules"
    if old_modules.exists():
        shutil.rmtree(old_modules)
    shutil.copytree(backup / "app_modules", old_modules)
    old_web = ROOT / "web"
    temp_web = ROOT / "web.ci-rollback"
    shutil.rmtree(temp_web, ignore_errors=True)
    shutil.copytree(backup / "web", temp_web)
    if old_web.exists():
        shutil.rmtree(old_web)
    os.replace(temp_web, old_web)
    unit = Path("/etc/systemd/system/qingsu.service")
    shutil.copy2(backup / "qingsu.service", unit)
    if (backup / "qingsu-ci-deploy").is_file():
        shutil.copy2(backup / "qingsu-ci-deploy", "/usr/local/sbin/qingsu-ci-deploy")
    tls = ROOT / "tls" / "default.conf"
    shutil.copy2(backup / "nginx-tls.conf", tls)
    http_temp = ROOT / "tls-http-ci-rollback.conf"
    shutil.copy2(backup / "nginx-http.conf", http_temp)
    run("restore TLS nginx configuration", "docker", "exec", "qingsu-tls", "nginx", "-t")
    run("reload restored TLS nginx configuration", "docker", "cp", str(tls), "qingsu-tls:/etc/nginx/conf.d/default.conf")
    run("test restored TLS nginx configuration", "docker", "exec", "qingsu-tls", "nginx", "-t")
    run("reload restored TLS nginx", "docker", "exec", "qingsu-tls", "nginx", "-s", "reload")
    run("restore HTTP nginx configuration", "docker", "cp", str(http_temp), "xiaoye-release:/etc/nginx/conf.d/default.conf")
    run("test restored HTTP nginx configuration", "docker", "exec", "xiaoye-release", "nginx", "-t")
    run("reload restored HTTP nginx", "docker", "exec", "xiaoye-release", "nginx", "-s", "reload")
    run("reload systemd during rollback", "systemctl", "daemon-reload")
    run("restart restored service", "systemctl", "restart", "qingsu")
    metadata = ROOT / "release.json"
    if previous_release is None:
        metadata.unlink(missing_ok=True)
    else:
        atomic_write(metadata, previous_release, 0o600)
    http_temp.unlink(missing_ok=True)


def deploy_main(run_id, expected_hash, revision, archive):
    release = "r" + run_id
    stage = RELEASES / release
    if stage.exists():
        raise RuntimeError("release directory already exists")
    safe_extract(archive, stage, {"server.py", "app_modules", "tests", "requirements.txt",
                                 "requirements.lock", "requirements-dev.txt", "scripts", "web", "app"})
    required = (stage / "server.py", stage / "app_modules", stage / "web" / "version.json",
                stage / "web" / "qingsu.apk", stage / "scripts" / "deploy.py",
                stage / "scripts" / "start-qa.py", stage / "scripts" / "verify_live.py")
    if not all(path.exists() for path in required):
        raise RuntimeError("release archive is missing required application files")
    previous_release = (ROOT / "release.json").read_bytes() if (ROOT / "release.json").is_file() else None
    prefix = "qa-" + os.urandom(8).hex()
    config_started = False
    deploy_succeeded = False
    deploy_result = None
    try:
        if (RELEASES / "qa-config.json").exists():
            raise RuntimeError("an existing QA config needs cleanup before a new deployment")
        config_started = True
        start_qa_config(release, prefix)
        qa_base = PUBLIC_BASE + "/" + prefix
        env = dict(os.environ, QINGSU_VERIFY_BASE=qa_base,
                   QINGSU_VERIFY_DB=str(stage / "qa-data" / "qingsu.db"), PYTHONDONTWRITEBYTECODE="1")
        run("isolated candidate API smoke test", "python3", str(stage / "scripts" / "verify_live.py"), env=env)
        result = run("production deployment", "python3", str(stage / "scripts" / "deploy.py"),
                     "--stage", str(stage), "--revision", revision, "--release", release)
        deploy_result = json.loads(result.stdout.strip().splitlines()[-1])
        deploy_succeeded = True
        try:
            production_verify(stage, release, revision)
        except Exception:
            backup = Path(deploy_result["backup"]).resolve()
            if backup.parent != BACKUPS.resolve() or not (backup / "server.py").is_file():
                raise RuntimeError("production smoke test failed and automatic code rollback could not locate its backup")
            restore_main(backup, previous_release)
            raise
    finally:
        if config_started:
            cleanup_qa(release, prefix)
        archive.unlink(missing_ok=True)
    if not deploy_succeeded:
        raise RuntimeError("production deployment did not complete")
    print(json.dumps({"target": "main", "release": release, "revision": revision,
                      "backup": deploy_result.get("backup")}, separators=(",", ":")))


def admin_credentials():
    path = Path("/opt/qingsu/admin/console.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    user = data.get("basic_user", "")
    password = data.get("basic_password", "")
    token = data.get("ops_token", "")
    if not all((user, password, token)):
        raise RuntimeError("admin console credentials are not configured")
    return user, password, token


def admin_smoke(expected_html_hash):
    user, password, token = admin_credentials()
    auth = "Basic " + base64.b64encode((user + ":" + password).encode()).decode()
    headers = {"Authorization": auth, "X-Qingsu-Token": token}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def open_after_restart(url, request_headers):
        deadline = time.monotonic() + 45
        last_error = None
        while time.monotonic() < deadline:
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with opener.open(request, timeout=8) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code not in (502, 503, 504):
                    raise
                last_error = error
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
            time.sleep(1)
        raise RuntimeError("admin service did not become reachable after restart") from last_error

    health = json.loads(open_after_restart("http://172.17.0.1:8100/api/health", headers))
    if not isinstance(health, dict) or "app" not in health or "console_container" not in health:
        raise RuntimeError("admin API health response is incomplete")
    body = open_after_restart(PUBLIC_BASE + "/ops/?ci=" + expected_html_hash[:12],
                              {"Authorization": auth})
    if hashlib.sha256(body).hexdigest() != expected_html_hash:
        raise RuntimeError("public admin console HTML does not match the deployed file")


def deploy_admin(run_id, revision, archive):
    base = ROOT / "admin-console" / "ops"
    targets = {"ops/admin_api.py": base / "admin_api.py", "ops/console.html": base / "console.html"}
    temp = ROOT / ("admin-ci-" + run_id)
    backup = BACKUPS / ("admin-console-ci-" + run_id)
    if backup.exists():
        raise RuntimeError("admin backup directory already exists")
    safe_extract(archive, temp, {"ops"}, exact_files=set(targets))
    backup.mkdir(mode=0o700)
    previous = {}
    try:
        for name, target in targets.items():
            if not target.is_file():
                raise RuntimeError("expected admin deployment file is missing")
            shutil.copy2(target, backup / Path(name).name)
            previous[name] = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode),
                              target.stat().st_uid, target.stat().st_gid)
        for name, target in targets.items():
            source = temp / name
            if not source.is_file():
                raise RuntimeError("admin archive is missing an expected file")
            mode, uid, gid = previous[name][1:]
            atomic_write(target, source.read_bytes(), mode, uid, gid)
        run("restart admin console", "systemctl", "restart", "qingsu-ops")
        deadline = time.time() + 30
        while time.time() < deadline:
            status = run("check admin service", "systemctl", "is-active", "qingsu-ops", check=False)
            if status.returncode == 0 and status.stdout.strip() == "active":
                break
            time.sleep(1)
        else:
            raise RuntimeError("admin service did not become active")
        expected_html_hash = hashlib.sha256((temp / "ops" / "console.html").read_bytes()).hexdigest()
        admin_smoke(expected_html_hash)
    except Exception:
        for name, target in targets.items():
            if name in previous:
                contents, mode, uid, gid = previous[name]
                atomic_write(target, contents, mode, uid, gid)
        run("restart admin console after rollback", "systemctl", "restart", "qingsu-ops", check=False)
        raise
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        archive.unlink(missing_ok=True)
    metadata = {"source_revision": revision, "backup": str(backup), "run_id": run_id}
    atomic_write(ROOT / "admin-console" / "release.json", json.dumps(metadata).encode(), 0o600)
    print(json.dumps({"target": "admin", "revision": revision, "backup": str(backup)}, separators=(",", ":")))


def main():
    if os.geteuid() != 0:
        raise SystemExit("deployment entry point must run as root")
    if len(sys.argv) != 5:
        raise SystemExit("usage: qingsu-ci-deploy <main|admin> <run-id> <sha256> <revision>")
    product, run_id, expected_hash, revision = sys.argv[1:]
    check_args(product, run_id, expected_hash, revision)
    lock_fd = os.open("/var/lock/qingsu-ci-deploy.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    archive = None
    try:
        archive = copy_verified_upload(product, run_id, expected_hash)
        if product == "main":
            deploy_main(run_id, expected_hash, revision, archive)
        else:
            deploy_admin(run_id, revision, archive)
    except Exception as error:
        print("deployment failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    finally:
        if archive is not None:
            archive.unlink(missing_ok=True)
        os.close(lock_fd)


if __name__ == "__main__":
    main()
