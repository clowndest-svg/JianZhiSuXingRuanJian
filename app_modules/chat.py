"""私聊：会话键、一次性 WS 票据、在线/未读的键名。

票据存在的原因：WebSocket 握手带不上自定义头，把登录 token 塞进 query 就会被
任何一层中间代理记进日志。改成"HTTP 先换一张 30 秒一次性票据，WS 只拿票据"，
这样强更门与鉴权仍然在 HTTP 侧完成（那里有中间件），WS 侧只做票据核对。
"""
import base64
import hashlib
import hmac
import json
import time

TICKET_TTL = 30
CONV_SEP = ":"


def conv_key(a, b):
    lo, hi = sorted((int(a), int(b)))
    return "%d%s%d" % (lo, CONV_SEP, hi)


def conv_partners(key):
    try:
        lo, hi = str(key).split(CONV_SEP)
        return int(lo), int(hi)
    except ValueError:
        return None, None


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text or "") + pad)


def mint_ticket(secret, user_id, build, nonce, now=None, session_hash=""):
    """nonce 由调用方给（secrets.token_urlsafe(8)），保证同一秒内的两张票也不同。"""
    payload = {"u": int(user_id), "b": int(build or 0), "n": str(nonce),
               "exp": int((now if now is not None else time.time())) + TICKET_TTL}
    payload["s"] = session_hash
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
    return "%s.%s" % (body, _b64(sig))


def read_ticket(secret, token, now=None):
    """返回 payload dict；任何不合格式/签名/过期的输入一律 None，不抛。"""
    try:
        body, _, sig = str(token or "").partition(".")
        if not body or not sig:
            return None
        want = _b64(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        payload = json.loads(_unb64(body).decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(now if now is not None else time.time()):
            return None
        if int(payload.get("u", 0)) <= 0:
            return None
        return payload
    except Exception:
        return None


def presence_key(user_id):
    return "qs:presence:%d" % int(user_id)


def unread_key(user_id):
    return "qs:unread:%d" % int(user_id)


def channel_key():
    return "qs:chat-events"


def ticket_seen_key(nonce):
    return "qs:wsticket:%s" % str(nonce)[:64]
