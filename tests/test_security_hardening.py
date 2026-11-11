"""Security hardening regressions: no public API map, escaped AI source rows,
no email-enumeration oracle, and bounded anonymous/upload endpoints."""
import importlib.util
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from PIL import Image


class Hardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "_audit_sandbox")
        for name in ("DB", "KEY", "UPLOAD"):
            os.environ["QINGSU_" + name + "_DIR"] = os.path.join(cls.tmp.name, name)
        os.environ["QINGSU_WEB_DIR"] = str(ROOT / "app" / "src" / "main" / "assets")
        os.environ["QINGSU_MIN_BUILD_FILE"] = os.path.join(cls.tmp.name, "DB", "min_build")
        os.environ.pop("QINGSU_DOCS", None)
        spec = importlib.util.spec_from_file_location("security_hardening_server", ROOT / "server.py")
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.m._redis_cmd = lambda *a, **k: (False, None)
        cls.c = TestClient(cls.m.app, raise_server_exceptions=False)
        cls.addClassCleanup(cls.c.close)
        cls.addClassCleanup(cls.tmp.cleanup)
        body = dict(username="hardening", password="Hardening!123", age=30, height=170,
                    weight_jin=160, target_weight_jin=140)
        signup = cls.c.post("/api/register", json=body)
        assert signup.status_code == 200, signup.text
        cls.auth = {"Authorization": "Bearer " + signup.json()["token"]}
        cls.uid = signup.json()["id"]

    def test_api_map_is_not_public(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.c.get(path).status_code, 404,
                                 path + " 是给攻击者的免费侦察地图，线上不该有")

    def test_non_ascii_secrets_are_rejected_not_500(self):
        """compare_digest 对非 ASCII str 会抛 TypeError；公开签名/分享入口不能因此 500。"""
        r = self.c.get("/api/public/dashboard",
                       params={"username": "hardening", "k": "错误密钥"})
        self.assertEqual(r.status_code, 404, r.text)
        r = self.c.get("/uploads/nope.jpg",
                       params={"expires": int(__import__("time").time()) + 60,
                               "signature": "错误签名"})
        self.assertEqual(r.status_code, 404, r.text)

    def test_security_headers_and_health_cache(self):
        page = self.c.get("/")
        self.assertIn("camera=()", page.headers.get("permissions-policy", ""))
        self.assertIn("geolocation=(self)", page.headers.get("permissions-policy", ""))
        self.assertIn("Content-Security-Policy-Report-Only", page.headers)
        ready = self.c.get("/health/ready")
        self.assertIn("no-store", ready.headers.get("cache-control", ""))

    def test_ai_source_rows_are_escaped(self):
        """上游搜索结果的 host 以前原样拼进 innerHTML；现在必须转义掉标签。"""
        self.m.web_search = lambda *a, **k: [dict(
            title="咖啡因与减脂", snippet="咖啡因对减脂有影响",
            url="https://evil.example/x", host="<img src=x onerror=alert(1)>")]
        self.m.llm_chat = lambda *a, **k: None
        r = self.c.post("/api/ask", headers=self.auth,
                        json={"question": "咖啡因对减脂的影响"})
        self.assertEqual(r.status_code, 200, r.text)
        low = r.text.lower()
        self.assertNotIn("<img", low)
        self.assertNotIn("onerror=", low)

    def test_email_login_does_not_say_whether_the_mailbox_is_bound(self):
        conn = self.m.get_db()
        try:
            conn.execute("UPDATE profiles SET email=?, email_verified_at=? WHERE user_id=?",
                         ("bound@example.com", "2026-11-10 00:00:00", self.uid))
            conn.commit()
        finally:
            conn.close()
        unknown = self.c.post("/api/login/email", json={"email": "nobody@example.com", "code": "000000"})
        known = self.c.post("/api/login/email", json={"email": "bound@example.com", "code": "000000"})
        self.assertEqual(unknown.status_code, 400, unknown.text)
        self.assertEqual(known.status_code, 400, known.text)
        self.assertEqual(unknown.json()["detail"], known.json()["detail"],
                         "两条错误文案不同就能枚举哪些邮箱注册过")

    def test_forgot_has_an_anonymous_rate_limit(self):
        self.m.mailer.status = lambda: {"ok": False, "why": "test: mail intentionally off"}
        statuses = [self.c.post("/api/account/forgot", json={"email": "nobody@example.com"}).status_code
                    for _ in range(7)]
        self.assertEqual(statuses[-1], 429, statuses)
        self.assertNotIn(200, statuses, statuses)

    def test_pillow_has_the_jpeg_decoder_fix(self):
        """用户上传的 JPEG 会进 Pillow；12.3.0 有可触发的解码器内存破坏公告。"""
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        hit = re.search(r"Pillow==(\d+)\.(\d+)\.(\d+)", text, re.I)
        self.assertIsNotNone(hit, "requirements.txt 里找不到 Pillow 的钉版")
        self.assertGreaterEqual(tuple(int(x) for x in hit.groups()), (13, 0, 0),
                                "Pillow 低于 13.0.0，JPEG 解码公告未修")

    def test_community_media_upload_is_rate_limited(self):
        buf = io.BytesIO()
        Image.new("RGB", (24, 24), (20, 120, 200)).save(buf, format="PNG")
        blob = buf.getvalue()
        statuses = []
        for _ in range(13):
            statuses.append(self.c.post(
                "/api/community/media", headers=self.auth,
                files={"file": ("tiny.png", blob, "image/png")}).status_code)
        self.assertEqual(statuses[-1], 429, statuses)


if __name__ == "__main__":
    unittest.main(verbosity=2)
