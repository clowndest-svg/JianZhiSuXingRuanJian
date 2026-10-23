"""C09 异地备份的可验证性：解密后真还原（库完整性/外键/记录数/媒体抽样）与备份年龄。"""
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_backup():
    spec = importlib.util.spec_from_file_location("qingsu_pull_backup", ROOT / "scripts" / "pull-backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load_backup()


def build_db(rows=50, extra_bad_fk=False):
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id))")
    if extra_bad_fk:
        conn.execute("PRAGMA foreign_keys=OFF")
    for index in range(rows):
        conn.execute("INSERT INTO users(username) VALUES(?)", ("u%d" % index,))
        conn.execute("INSERT INTO logs(user_id) VALUES(?)", (index + 1 if not extra_bad_fk else 999,))
    conn.commit()
    conn.close()
    data = Path(path).read_bytes()
    os.unlink(path)
    return data


def build_bundle(db_bytes=None, media=(("uploads/a.jpg", b"jpeg-a"), ("uploads/b.jpg", b"jpeg-b")),
                 include_db=True, include_media=True):
    if db_bytes is None:
        db_bytes = build_db()
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as photos:
        for name, body in media:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            photos.addfile(info, io.BytesIO(body))
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as bundle:
        for name, body in (("qingsu.db", db_bytes), ("media.tar.gz", inner.getvalue())):
            if name == "qingsu.db" and not include_db:
                continue
            if name == "media.tar.gz" and not include_media:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(body)
            bundle.addfile(info, io.BytesIO(body))
    return out.getvalue()


def stamp(offset_hours, now):
    return "bundle-%s.p7m" % time.strftime("%Y%m%d-%H%M%S", time.localtime(now - offset_hours * 3600))


class StubResult(list):
    def fetchone(self):
        return self[0]

    def fetchall(self):
        return list(self)


class StubConnection:
    """只用来喂 integrity_check / foreign_key_check 的返回值：真实损坏不一定抛异常。"""

    def __init__(self, integrity, violations=()):
        self.integrity = integrity
        self.violations = violations

    def execute(self, sql):
        if "integrity_check" in sql:
            return StubResult([(self.integrity,)])
        if "foreign_key_check" in sql:
            return StubResult(self.violations)
        if "sqlite_master" in sql:
            return StubResult([("users",)])
        return StubResult([(3,)])

    def close(self):
        pass


class VerifyPlaintext(unittest.TestCase):
    def test_intact_bundle_reports_integrity_counts_and_sampled_media(self):
        result = backup.verify_plaintext(build_bundle())
        self.assertEqual(result["restored_integrity"], "ok")
        self.assertEqual(result["foreign_key_violations"], 0)
        self.assertEqual(result["row_counts"], {"users": 50, "logs": 50})
        self.assertEqual(result["media_files"], 2)
        self.assertEqual(result["media_restored"], 2)

    def test_media_is_sampled_not_fully_restored(self):
        many = tuple(("uploads/f%03d.jpg" % index, b"x" * 8) for index in range(60))
        result = backup.verify_plaintext(build_bundle(media=many), media_sample=25)
        self.assertEqual(result["media_files"], 60)
        self.assertEqual(result["media_restored"], 25)

    def test_corrupted_database_is_red_with_readable_reason(self):
        damaged = bytearray(build_db(rows=200))
        for offset in range(4096, 4600):
            damaged[offset] = 0xFF
        with self.assertRaises(backup.BackupVerifyError) as caught:
            backup.verify_plaintext(build_bundle(bytes(damaged)))
        self.assertIn("恢复数据库副本", str(caught.exception))

    def test_integrity_row_that_is_not_ok_is_red(self):
        # integrity_check 不抛异常、只把坏结果作为一行返回的那类损坏，也必须判红
        bundle = build_bundle()
        with mock.patch.object(sqlite3, "connect", lambda *a, **k: StubConnection("database disk image is malformed")):
            with self.assertRaises(backup.BackupVerifyError) as caught:
                backup.verify_plaintext(bundle)
        self.assertIn("integrity_check", str(caught.exception))

    def test_foreign_key_rows_are_counted_not_guessed(self):
        bundle = build_bundle()
        with mock.patch.object(sqlite3, "connect", lambda *a, **k: StubConnection("ok", violations=[("logs", 1, "users", 0)])):
            with self.assertRaises(backup.BackupVerifyError) as caught:
                backup.verify_plaintext(bundle)
        self.assertIn("1 条外键不自洽", str(caught.exception))

    def test_foreign_key_break_is_red(self):
        with self.assertRaises(backup.BackupVerifyError) as caught:
            backup.verify_plaintext(build_bundle(build_db(rows=3, extra_bad_fk=True)))
        self.assertIn("外键", str(caught.exception))

    def test_truncated_bundle_is_red(self):
        with self.assertRaises(backup.BackupVerifyError) as caught:
            backup.verify_plaintext(build_bundle()[:200])
        self.assertIn("tar", str(caught.exception))

    def test_missing_members_are_red_with_different_reasons(self):
        with self.assertRaises(backup.BackupVerifyError) as no_db:
            backup.verify_plaintext(build_bundle(include_db=False))
        with self.assertRaises(backup.BackupVerifyError) as no_media:
            backup.verify_plaintext(build_bundle(include_media=False))
        self.assertIn("qingsu.db", str(no_db.exception))
        self.assertIn("media.tar.gz", str(no_media.exception))
        self.assertNotEqual(str(no_db.exception), str(no_media.exception))

    def test_unsafe_media_members_are_refused(self):
        for name in ("../escape.jpg", "/etc/passwd", "uploads/../escape.jpg"):
            with self.subTest(member=name):
                with self.assertRaises(backup.BackupVerifyError):
                    backup.verify_plaintext(build_bundle(media=((name, b"z"),)))
        link = tarfile.TarInfo("uploads/alias.jpg")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as photos:
            photos.addfile(link)
        inner = io.BytesIO(out.getvalue())
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w") as archive:
            for name, body in (("qingsu.db", build_db(rows=2)), ("media.tar.gz", inner.getvalue())):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        with self.assertRaises(backup.BackupVerifyError) as caught:
            backup.verify_plaintext(bundle.getvalue())
        self.assertIn("链接", str(caught.exception))


class BackupAge(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.now = time.time()

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def place(self, name, pulled_hours_ago, body=b"p7m"):
        path = self.temp / name
        path.write_bytes(body)
        moment = self.now - pulled_hours_ago * 3600
        os.utime(path, (moment, moment))
        return path

    def test_fresh_copy_is_green(self):
        self.place(stamp(2, self.now), 1)
        entry = backup.age_report(self.temp, now=self.now)
        self.assertEqual(entry["state"], "green", entry["reason"])
        self.assertEqual(entry["copies"], 1)
        self.assertEqual(entry["server_age_hours"], 2.0)

    def test_missing_copy_is_red_and_not_zero_age(self):
        entry = backup.age_report(self.temp, now=self.now)
        self.assertEqual(entry["state"], "red")
        self.assertEqual(entry["status"], "无本地副本")
        self.assertIsNone(entry["pulled_hours_ago"], "没有副本却报了个年龄数字")
        self.assertEqual(entry["copies"], 0)

    def test_offline_machine_and_stale_server_get_different_reasons(self):
        self.place(stamp(41, self.now), 40)
        machine = backup.age_report(self.temp, now=self.now)
        self.assertEqual(machine["state"], "red")
        self.assertIn("这台电脑", machine["reason"])

        for stale in self.temp.glob("bundle-*.p7m"):
            stale.unlink()
        self.place(stamp(50, self.now), 2)
        server = backup.age_report(self.temp, now=self.now)
        self.assertEqual(server["state"], "red")
        self.assertIn("服务器", server["reason"])

        empty = backup.age_report(self.temp / "none", now=self.now)
        self.assertEqual(empty["state"], "red")
        reasons = {machine["reason"], server["reason"], empty["reason"]}
        self.assertEqual(len(reasons), 3, "三种红的原因必须互相区分得开")
        self.assertNotIn(empty["reason"], ("", "0"))

    def test_threshold_is_configurable(self):
        self.place(stamp(30, self.now), 29)
        self.assertEqual(backup.age_report(self.temp, threshold=26.0, now=self.now)["state"], "red")
        self.assertEqual(backup.age_report(self.temp, threshold=48.0, now=self.now)["state"], "green")


class EncryptedRoundTrip(unittest.TestCase):
    def test_real_cms_bundle_decrypts_and_verifies(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.x509.oid import NameOID
        import datetime

        if not shutil.which("openssl"):
            self.fail("本机没有 openssl：CMS 加密这一半链路没法证明，不能算验证通过")
        temp = Path(tempfile.mkdtemp())
        try:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Qingsu Test Recipient")])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(7)
                    .not_valid_before(now - datetime.timedelta(days=1))
                    .not_valid_after(now + datetime.timedelta(days=10))
                    .sign(key, hashes.SHA256()))
            keys = temp / "keys"
            keys.mkdir()
            password = b"test-passphrase"
            (keys / "backup-password.txt").write_bytes(password)
            (keys / "backup-private.pem").write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password)))
            (keys / "backup-recipient.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            plain = build_bundle()
            (temp / "bundle.tar").write_bytes(plain)
            target = temp / stamp(1, time.time())
            subprocess.run(["openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc", "-in",
                            str(temp / "bundle.tar"), "-out", str(target), "-outform", "DER",
                            str(keys / "backup-recipient.pem")], check=True)
            result = backup.verify_file(target, keys)
            self.assertEqual(result["restored_integrity"], "ok")
            self.assertEqual(result["row_counts"]["users"], 50)
            tampered = target.read_bytes()
            target.write_bytes(tampered[: len(tampered) // 2])
            with self.assertRaises(backup.BackupVerifyError) as caught:
                backup.verify_file(target, keys)
            self.assertIn("解密", str(caught.exception))
            with self.assertRaises(backup.BackupVerifyError):
                backup.verify_file(temp / "bundle-20260101-000000.p7m", keys)
        finally:
            shutil.rmtree(temp, ignore_errors=True)


class ReportFile(unittest.TestCase):
    def test_report_is_written_and_reloads_as_json(self):
        temp = Path(tempfile.mkdtemp())
        try:
            path = temp / "nested" / "verify-report.json"
            backup.write_report({"status": "red", "reason": "无本地副本", "age": backup.age_report(temp)}, path)
            reloaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["status"], "red")
            self.assertEqual(reloaded["age"]["status"], "无本地副本")
        finally:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
