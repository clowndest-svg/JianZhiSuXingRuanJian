# -*- coding: utf-8 -*-
"""Voice-call signalling and TURN credential contracts (no real media)."""
import base64
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient


class CallSignalling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        for key in ("DB", "UPLOAD", "KEY"):
            os.environ["QINGSU_" + key + "_DIR"] = str(cls.folder / key)
        os.environ["QINGSU_WEB_DIR"] = str(ROOT / "app/src/main/assets")
        spec = importlib.util.spec_from_file_location("call_test_server", ROOT / "server.py")
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.m._redis_cmd = lambda *a, **k: (False, None)
        cls.m.rate_hit = lambda *a, **k: (True, "test", 1)
        cls.c = TestClient(cls.m.app)
        cls.addClassCleanup(cls.c.close)
        cls.users = {}
        for name in ("caller", "callee", "third"):
            r = cls.c.post("/api/register", headers={"X-App-Build": "99"}, json={
                "username": name, "password": "Review!123", "age": 30, "height": 170,
                "weight_jin": 160, "target_weight_jin": 140})
            assert r.status_code == 200, r.text
            body = r.json()
            cls.users[name] = {"token": body["token"], "id": body["id"]}

    def auth(self, name):
        return {"Authorization": "Bearer " + self.users[name]["token"], "X-App-Build": "99"}

    def setUp(self):
        c = self.m.get_db()
        c.execute('DELETE FROM follows')
        a, b, third = (self.users[n]['id'] for n in ('caller', 'callee', 'third'))
        c.executemany('INSERT INTO follows VALUES (?,?,?)',
                      [(a,b,'test'),(b,a,'test'),(third,b,'test'),(b,third,'test')])
        c.commit(); c.close()

    def invite(self, socket):
        socket.send_json({'t':'call_invite','to':self.users['callee']['id'],
                          'sdp':{'type':'offer','sdp':'v=0\r\n'}})

    def test_no_follow_or_one_way_follow_cannot_ring_or_reserve_call(self):
        a,b = (self.users[n]['id'] for n in ('caller','callee'))
        with self.ws('caller') as ca, self.ws('callee') as cb:
            ca.receive_json(); cb.receive_json()
            for edges in ([],[(a,b)],[(b,a)]):
                c=self.m.get_db();c.execute('DELETE FROM follows')
                c.executemany('INSERT INTO follows VALUES (?,?,?)',[(x,y,'test') for x,y in edges])
                c.commit();c.close()
                self.invite(ca);error=ca.receive_json()
                self.assertEqual(error['t'],'call_error');self.assertIn('互相关注',error['detail'])
                self.assertFalse(self.m._CALLS);self.assertFalse(self.m._CALL_BY_USER)

    def test_stale_invite_cannot_be_accepted_after_relation_removed(self):
        with self.ws('caller') as ca, self.ws('callee') as cb:
            ca.receive_json();cb.receive_json();self.invite(ca)
            ident=ca.receive_json()['call_id'];cb.receive_json()
            c=self.m.get_db();c.execute('DELETE FROM follows');c.commit();c.close()
            cb.send_json({'t':'call_accept','call_id':ident,'sdp':{'type':'answer','sdp':'v=0\r\n'}})
            for sock in (ca,cb):self.assertEqual(sock.receive_json()['t'],'call_end')
            self.assertFalse(self.m._CALLS);self.assertFalse(self.m._CALL_BY_USER)

    def test_unfollow_ends_ringing_and_active_calls(self):
        for accept in (False,True):
            self.setUp()
            with self.ws('caller') as ca, self.ws('callee') as cb:
                ca.receive_json();cb.receive_json();self.invite(ca)
                ident=ca.receive_json()['call_id'];cb.receive_json()
                if accept:
                    cb.send_json({'t':'call_accept','call_id':ident,'sdp':{'type':'answer','sdp':'v=0\r\n'}})
                    self.assertEqual(ca.receive_json()['t'],'call_accept');self.assertEqual(cb.receive_json()['t'],'call_active')
                r=self.c.post('/api/community/users/'+str(self.users['callee']['id'])+'/follow',
                              headers=self.auth('caller'),json={'on':False})
                self.assertEqual(r.status_code,200,r.text)
                for sock in (ca,cb):
                    end=sock.receive_json();self.assertEqual(end['t'],'call_end');self.assertIn('互相关注',end['reason'])
                self.assertFalse(self.m._CALLS);self.assertFalse(self.m._CALL_BY_USER)

    def ticket(self, name):
        r = self.c.post("/api/chat/ticket", headers=self.auth(name), json={})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["ticket"]

    def ws(self, name):
        return self.c.websocket_connect("/ws/chat?ticket=" + self.ticket(name))

    def test_invite_accept_ice_end_and_offline(self):
        with patch.object(self.m, "_CALLS", {}), patch.object(self.m, "_CALL_BY_USER", {}):
            with self.ws("caller") as ca, self.ws("callee") as cb:
                self.assertEqual(ca.receive_json()["t"], "ready")
                self.assertEqual(cb.receive_json()["t"], "ready")
                ca.send_json({"t": "call_invite", "to": self.users["callee"]["id"],
                              "sdp": {"type": "offer", "sdp": "v=0\r\n"}})
                ringing = ca.receive_json()
                self.assertEqual(ringing["t"], "call_ringing")
                call_id = ringing["call_id"]
                invite = cb.receive_json()
                self.assertEqual(invite["t"], "call_invite")
                self.assertEqual(invite["from"]["id"], self.users["caller"]["id"])
                cb.send_json({"t": "call_accept", "call_id": call_id,
                              "sdp": {"type": "answer", "sdp": "v=0\r\n"}})
                self.assertEqual(ca.receive_json()["t"], "call_accept")
                self.assertEqual(cb.receive_json()["t"], "call_active")
                ca.send_json({"t": "call_ice", "call_id": call_id,
                              "candidate": {"candidate": "candidate:1 1 udp 1 1.2.3.4 5000 typ host",
                                            "sdpMid": "0", "sdpMLineIndex": 0}})
                self.assertEqual(cb.receive_json()["t"], "call_ice")
                cb.send_json({"t": "call_end", "call_id": call_id})
                self.assertEqual(ca.receive_json()["t"], "call_end")

            with self.ws("caller") as ca:
                ca.receive_json()
                ca.send_json({"t": "call_invite", "to": self.users["callee"]["id"],
                              "sdp": {"type": "offer", "sdp": "v=0\r\n"}})
                self.assertEqual(ca.receive_json()["t"], "call_unavailable")

    def test_busy_reject_and_validation(self):
        with patch.object(self.m, "_CALLS", {}), patch.object(self.m, "_CALL_BY_USER", {}):
            with self.ws("caller") as ca, self.ws("callee") as cb, self.ws("third") as cc:
                for sock in (ca, cb, cc):
                    self.assertEqual(sock.receive_json()["t"], "ready")
                ca.send_json({"t": "call_invite", "to": self.users["callee"]["id"],
                              "sdp": {"type": "offer", "sdp": "v=0\r\n"}})
                call_id = ca.receive_json()["call_id"]
                self.assertEqual(cb.receive_json()["t"], "call_invite")
                cc.send_json({"t": "call_invite", "to": self.users["callee"]["id"],
                              "sdp": {"type": "offer", "sdp": "v=0\r\n"}})
                self.assertEqual(cc.receive_json()["t"], "call_busy")
                cb.send_json({"t": "call_reject", "call_id": call_id})
                self.assertEqual(ca.receive_json()["t"], "call_reject")
                ca.send_json({"t": "call_invite", "to": self.users["caller"]["id"],
                              "sdp": {"type": "offer", "sdp": "v=0\r\n"}})
                self.assertEqual(ca.receive_json()["t"], "call_error")
                ca.send_json({"t": "call_ice", "call_id": "not-a-call",
                              "candidate": {"candidate": "x"}})
                self.assertEqual(ca.receive_json()["t"], "call_error")

    def test_turn_credentials_are_short_lived_and_signed(self):
        secret = "a" * 64
        with patch.dict(os.environ, {"QINGSU_TURN_SECRET": secret}):
            r = self.c.get("/api/rtc/ice", headers=self.auth("caller"))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["turn"])
        server = body["ice_servers"][0]
        self.assertIn("turn:", " ".join(server["urls"]))
        self.assertIn("stun:", " ".join(server["urls"]))
        username = server["username"]
        expiry, uid = username.split(":")
        self.assertEqual(int(uid), self.users["caller"]["id"])
        self.assertTrue(0 < int(expiry) - int(time.time()) <= 3600)
        expected = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(server["credential"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
