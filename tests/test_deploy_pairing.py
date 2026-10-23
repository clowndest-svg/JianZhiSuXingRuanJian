"""发布入口那道"主后台版本配对"门的契约（方案 C03/C05）。

跑的是 scripts/ci-deploy-server.py 里真的 admin_smoke，只把网络那一层换成假的：
这条判据要钉的是"配对没对上时发布会被拒"，不是钉源码里有没有那句 if。
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]

# 这个脚本只在服务器（Linux）上跑，用了 fcntl 做发布串行锁。
# 本机是 Windows，import 不了，所以判据先把这一层补上——补的是"能不能 import"，
# 不是"门有没有生效"：门那部分由下面的用例真跑 admin_smoke 来钉。
if "fcntl" not in sys.modules:
    stub = types.ModuleType("fcntl")
    stub.LOCK_EX = 2
    stub.LOCK_UN = 8
    stub.flock = lambda *a, **k: None
    sys.modules["fcntl"] = stub

spec = importlib.util.spec_from_file_location("ci_deploy_under_test",
                                              ROOT / "scripts" / "ci-deploy-server.py")
deploy = importlib.util.module_from_spec(spec)
sys.modules["ci_deploy_under_test"] = deploy
spec.loader.exec_module(deploy)

HEALTH = {"app": {"status": "ok"}, "console_container": "running"}


class FakeResponse:
    def __init__(self, blob):
        self._blob = blob

    def read(self):
        return self._blob

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """按 URL 回不同内容；version-pairing 的内容由每条用例决定。"""

    def __init__(self, pairing, html=b"<html>ops</html>", privileged=None):
        self.pairing = pairing
        self.privileged = privileged if privileged is not None else {'gate':True,'backup':True,'health':True,'effective_uid':1001}
        self.html = html
        self.asked = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        if "/api/health" in url:
            return FakeResponse(json.dumps(HEALTH).encode())
        if "/api/version-pairing" in url:
            return FakeResponse(json.dumps(self.pairing).encode())
        if "/api/privileged" in url:
            return FakeResponse(json.dumps(self.privileged).encode())
        if "/ops/" in url:
            return FakeResponse(self.html)
        raise AssertionError("判据没预料到这一跳: " + url)


class PairingGate(unittest.TestCase):
    def setUp(self):
        self.saved_opener = deploy.urllib.request.build_opener
        self.saved_credentials = deploy.admin_credentials
        self.saved_base = deploy.PUBLIC_BASE
        deploy.admin_credentials = lambda: ("u", "p", "t")
        deploy.PUBLIC_BASE = "https://example.test"
        self.addCleanup(self.restore)

    def restore(self):
        deploy.urllib.request.build_opener = self.saved_opener
        deploy.admin_credentials = self.saved_credentials
        deploy.PUBLIC_BASE = self.saved_base

    def drive(self, pairing, html=b"<html>ops</html>", privileged=None):
        fake = FakeOpener(pairing, html, privileged)
        deploy.urllib.request.build_opener = lambda *a, **k: fake
        import hashlib
        deploy.admin_smoke(hashlib.sha256(html).hexdigest())
        return fake

    def test_paired_release_passes_and_asks_the_pairing_endpoint(self):
        good = {"paired": True, "missing_app_columns": [], "app_schema_version": 12,
                "app_release": "c31ecdd", "app_error": None}
        fake = self.drive(good)
        self.assertTrue(any("/api/version-pairing" in url for url in fake.asked),
                        "冒烟检查根本没问过配对接口，那道门是摆设")

    def test_missing_column_blocks_the_release(self):
        """后台先发到旧主服务上：这就是必须拦住的那一种。"""
        with self.assertRaises(RuntimeError) as raised:
            self.drive({"paired": False,
                        "missing_app_columns": ["users.reset_expires_at"],
                        "app_schema_version": 11, "app_error": None})
        self.assertIn("users.reset_expires_at", str(raised.exception))
        self.assertIn("拒绝发布", str(raised.exception))

    def test_unapplied_privilege_configuration_blocks_release(self):
        for cfg in [{'gate':False,'backup':True,'health':True,'effective_uid':1001},
                    {'gate':True,'backup':True,'health':True,'effective_uid':0}]:
            with self.subTest(cfg=cfg),self.assertRaises(RuntimeError):
                self.drive({'paired':True},privileged=cfg)

    def test_unreachable_app_blocks_instead_of_passing(self):
        """主应用答不出等于没验证过，不能当成"大概没问题"就放行。"""
        with self.assertRaises(RuntimeError):
            self.drive({"paired": False, "missing_app_columns": [],
                        "app_schema_version": None, "app_error": "connection_refused"})

    def test_incomplete_health_still_fails_first(self):
        class Healthless(FakeOpener):
            def open(self, request, timeout=None):
                if "/api/health" in request.full_url:
                    return FakeResponse(b'{"console_container":"running"}')
                return super().open(request, timeout)

        deploy.urllib.request.build_opener = lambda *a, **k: Healthless({"paired": True})
        with self.assertRaises(RuntimeError) as raised:
            deploy.admin_smoke("0" * 64)
        self.assertIn("incomplete", str(raised.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
