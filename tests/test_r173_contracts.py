"""r173 contracts: email-code accounts, weight sync, quote replies and image thumbs."""
import importlib.util
import io
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from PIL import Image

CODE_RE = re.compile(r"验证码：(\d{6})")
SENT = []


def fake_send(to_addr, subject, text, purpose=""):
    hit = CODE_RE.search(text or "")
    SENT.append({"to": to_addr, "purpose": purpose, "code": hit.group(1) if hit else ""})
    return True, ""


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        for key in ("DB", "UPLOAD", "KEY"):
            os.environ["QINGSU_" + key + "_DIR"] = str(folder / key)
        os.environ["QINGSU_WEB_DIR"] = str(ROOT / "app/src/main/assets")
        spec = importlib.util.spec_from_file_location("contract_server", ROOT / "server.py")
        cls.m = importlib.util.module_from_spec(spec)
        sys.modules["contract_server"] = cls.m
        spec.loader.exec_module(cls.m)
        cls.c = TestClient(cls.m.app)
        cls.headers = {"X-App-Build": "57"}
        cls.patches = [patch.object(cls.m.mailer, "status", return_value={"ok": True, "sender_domain": "example.com"}),
                       patch.object(cls.m.mailer, "send", side_effect=fake_send)]
        for p in cls.patches:
            p.start()
            cls.addClassCleanup(p.stop)

    def send_code(self, email, purpose):
        SENT.clear()
        # 同一 IP 十分钟只有 4 次发信额度；测试里把窗口清掉，只测业务规则。
        self.m.rate_reset("mail:ip:testclient")
        self.m.rate_reset("mail:to:%s:%s" % (purpose, self.m.hash_token(email)))
        r = self.c.post("/api/auth/email/send", headers=self.headers,
                        json={"email": email, "purpose": purpose})
        return r, (SENT[-1]["code"] if SENT else "")

    def register(self, name, email=None, weight=140.0):
        body = dict(username=name, password="Passw0rd!123", age=30, height=170,
                    weight_jin=weight, target_weight_jin=120, gender="male")
        if email:
            r, code = self.send_code(email, "register")
            self.assertEqual(r.status_code, 200, r.text)
            body.update(email=email, email_code=code)
        r = self.c.post("/api/register", headers=self.headers, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_register_requires_email_for_new_builds(self):
        r = self.c.post("/api/register", headers=self.headers,
                        json=dict(username="noemail", password="Passw0rd!123", age=30,
                                  height=170, weight_jin=140, target_weight_jin=120))
        self.assertEqual(r.status_code, 400)
        self.assertIn("邮箱", r.json()["detail"])
        # 老客户端（56）仍可按原流程注册
        old = self.c.post("/api/register", headers={"X-App-Build": "56"},
                          json=dict(username="oldclient", password="Passw0rd!123", age=30,
                                    height=170, weight_jin=140, target_weight_jin=120))
        self.assertEqual(old.status_code, 200, old.text)

    def test_email_code_cooldown_register_login_and_reset(self):
        email = "user@example.com"
        r1, code1 = self.send_code(email, "register")
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertRegex(code1, r"^\d{6}$")
        again, _ = self.send_code(email, "register")
        self.assertEqual(again.status_code, 429)
        self.assertIn("秒后再试", again.json()["detail"])
        reg = self.c.post("/api/register", headers=self.headers,
                          json=dict(username="mailuser", password="Passw0rd!123", age=30, height=170,
                                    weight_jin=140, target_weight_jin=120, gender="male",
                                    email=email, email_code=code1))
        self.assertEqual(reg.status_code, 200, reg.text)
        # 邮箱验证码登录
        r2, code2 = self.send_code(email, "login")
        self.assertEqual(r2.status_code, 200, r2.text)
        login = self.c.post("/api/login/email", headers=self.headers, json={"email": email, "code": code2})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()["token"])
        # 找回密码：拿 reset 验证码，设新密码后用新密码登录
        SENT.clear()
        forgot = self.c.post("/api/account/forgot", headers=self.headers, json={"email": email})
        self.assertEqual(forgot.status_code, 200, forgot.text)
        reset_code = SENT[-1]["code"]
        reset = self.c.post("/api/account/reset", headers=self.headers,
                            json={"email": email, "code": reset_code, "new_password": "NewPass!987"})
        self.assertEqual(reset.status_code, 200, reset.text)
        relogin = self.c.post("/api/login", headers=self.headers,
                              json={"username": "mailuser", "password": "NewPass!987"})
        self.assertEqual(relogin.status_code, 200, relogin.text)

    def test_profile_weight_updates_dashboard(self):
        user = self.register("weightuser", email="weight@example.com", weight=140)
        token = user["token"]
        h = {"Authorization": "Bearer " + token, "X-App-Build": "57"}
        before = self.c.get("/api/dashboard", headers=h).json()["current_weight_jin"]
        self.assertEqual(before, 140)
        saved = self.c.post("/api/profile/update", headers=h,
                            json={"weight_jin": 132, "height": 173})
        self.assertEqual(saved.status_code, 200, saved.text)
        after = self.c.get("/api/dashboard", headers=h).json()["current_weight_jin"]
        self.assertEqual(after, 132)
        conn = sqlite3.connect(os.path.join(os.environ["QINGSU_DB_DIR"], "qingsu.db"))
        try:
            rows = conn.execute("SELECT weight_jin FROM weight_logs w JOIN users u ON u.id=w.user_id "
                                "WHERE u.username='weightuser'").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 1, "改档案不该在体重日志里多插一条")

    def test_quote_reply_snapshot_and_scope(self):
        a = self.register("quotea", email="qa@example.com")
        b = self.register("quoteb", email="qb@example.com")
        c = self.register("quotec", email="qc@example.com")
        ha = {"Authorization": "Bearer " + a["token"], "X-App-Build": "57"}
        hb = {"Authorization": "Bearer " + b["token"], "X-App-Build": "57"}
        hc = {"Authorization": "Bearer " + c["token"], "X-App-Build": "57"}
        ids = {}
        conn = self.m.get_db()
        try:
            ids = {name: conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]
                   for name in ("quotea", "quoteb", "quotec")}
        finally:
            conn.close()
        first = self.c.post("/api/chat/send", headers=ha,
                            json={"to": ids["quoteb"], "text": "今晚一起跑步吗", "request_id": "q-1"}).json()["message"]
        reply = self.c.post("/api/chat/send", headers=hb,
                            json={"to": ids["quotea"], "text": "几点？", "request_id": "q-2",
                                  "quote_id": first["id"]}).json()["message"]
        self.assertEqual(reply["quote"]["id"], first["id"])
        self.assertEqual(reply["quote"]["text"], "今晚一起跑步吗")
        self.assertTrue(reply["quote"]["name"])
        listed = self.c.get("/api/chat/messages?with_user=%d" % ids["quoteb"], headers=ha).json()["items"]
        row = [m for m in listed if m["id"] == reply["id"]][0]
        self.assertEqual(row["quote"]["text"], "今晚一起跑步吗")
        # 不同会话的消息不能被拿来引用
        bad = self.c.post("/api/chat/send", headers=hc,
                          json={"to": ids["quoteb"], "text": "试试", "request_id": "q-3",
                                "quote_id": first["id"]})
        self.assertEqual(bad.status_code, 400)

    def test_feed_uses_image_thumbnails(self):
        user = self.register("thumbuser", email="thumb@example.com")
        h = {"Authorization": "Bearer " + user["token"], "X-App-Build": "57"}
        out = io.BytesIO()
        Image.new("RGB", (1200, 1200), (30, 160, 90)).save(out, format="JPEG", quality=92)
        up = self.c.post("/api/community/media", headers=h,
                         files={"file": ("big.jpg", out.getvalue(), "image/jpeg")})
        self.assertEqual(up.status_code, 200, up.text)
        name = up.json()["name"]
        post = self.c.post("/api/community/posts", headers=h,
                           json={"title": "缩略图", "text": "", "images": [name]})
        self.assertEqual(post.status_code, 200, post.text)
        pid = post.json()["post"]["id"]
        feed = self.c.get("/api/community/feed?tab=mine&limit=5", headers=h).json()["items"]
        card = [p for p in feed if p["id"] == pid][0]
        self.assertTrue(card["image_thumbs"][0].endswith("&thumb=1"))
        thumb = self.c.get(card["image_thumbs"][0])
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["content-type"], "image/jpeg")
        self.assertIn("max-age=86400", thumb.headers.get("cache-control", ""))
        self.assertLess(len(thumb.content), 1200 * 1200)


if __name__ == "__main__":
    unittest.main()
