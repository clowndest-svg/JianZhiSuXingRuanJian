# -*- coding: utf-8 -*-
"""邮件发送通道：可插拔，没配置就如实说发不出去，绝不假装已发送。

配置只放服务器本地文件（默认 /opt/qingsu/mail.json，chmod 600，已进 .gitignore）：
    {"host","port","user","password","from","tls"}
它的内容不进仓库、不进日志、不进任何接口响应——status() 只回"通不通"和发信域名。

为什么不做成"没配置就本地打开发件箱"：验证码发不出去却告诉用户"已发送"，
等于把他的账号锁在门外，还会让他反复点。所以未配置必须是**看得见的失败**。
"""
import json
import os
import smtplib
import ssl
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

CONFIG_PATH = os.environ.get("QINGSU_MAIL_CONFIG", "/opt/qingsu/mail.json")

_lock = threading.Lock()
_cache = {"key": None, "cfg": None, "read_at": 0.0}

# 邮箱形状只挡明显打不到的地址；最终能不能收到由发信服务器说了算，
# 这里不做 RFC 校验，免得把合法但少见的地址挡在外面。
_LOCAL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")


def email_shape_ok(addr):
    addr = (addr or "").strip()
    if not addr or addr.count("@") != 1 or len(addr) > 200:
        return False
    local, _, domain = addr.partition("@")
    if not local or local[0] == "." or "." not in domain or domain.startswith("."):
        return False
    if any(ch not in _LOCAL for ch in local):
        return False
    labels = domain.lower().split(".")
    if any(not l or len(l) > 63 for l in labels):
        return False
    return labels[-1].isalpha() and len(labels[-1]) >= 2


def normalize(addr):
    return (addr or "").strip().lower()


def _config():
    """按 mtime+size 缓存配置：改了不用重启服务，读不到就当没配。"""
    try:
        st = os.stat(CONFIG_PATH)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    now = time.time()
    with _lock:
        if _cache["key"] == key and now - _cache["read_at"] < 30:
            return _cache["cfg"]
        cfg = None
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cand = {
                "host": str(raw.get("host") or "").strip(),
                "port": int(raw.get("port") or 465),
                "user": str(raw.get("user") or "").strip(),
                "password": str(raw.get("password") or ""),
                "from": str(raw.get("from") or raw.get("user") or "").strip(),
                "tls": str(raw.get("tls") or "ssl").strip().lower(),
            }
            if raw.get('enabled', True) and cand["tls"] in ('ssl', 'starttls', 'tls') and cand["host"] and cand["user"] and cand["password"] and cand["from"]:
                cfg = cand
        except Exception:
            cfg = None
        _cache.update(key=key, cfg=cfg, read_at=now)
        return cfg


def status():
    """只报通道状态。绝不把 host/user/password 往外带。"""
    cfg = _config()
    if not cfg:
        return {"ok": False, "why": "邮件通道未接入：服务器上没有配置发信账号"}
    return {"ok": True, "sender_domain": cfg["from"].split("@")[-1].lower()}


def send(to_addr, subject, text, purpose=""):
    """成功 (True, "")；失败 (False, 人话原因)。不把异常抛给调用方。

    失败原因只留异常类型名——smtplib 的报错里常带主机名、用户名甚至服务器应答原文，
    那些一旦进日志或进响应就等于把发信账号泄露出去。
    正文同时给纯文本与极简 HTML：只有 HTML 或只有一行的信更像群发垃圾。
    """
    cfg = _config()
    if not cfg:
        return False, "邮件通道未接入，暂时发不出验证码"
    if not email_shape_ok(to_addr):
        return False, "邮箱格式不对，收不到信"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("轻塑", cfg["from"]))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["from"].split("@")[-1])
    msg["Reply-To"] = cfg["from"]
    msg["X-Auto-Response-Suppress"] = "All"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    title = {"bind": "绑定邮箱", "reset": "重置密码", "register": "注册",
             "login": "邮箱登录"}.get(purpose, "账号操作")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    code = ""
    if lines:
        code = lines[0].split("：")[-1].strip()[-6:]
    rest = " ".join(lines[1:])
    html = ('<div style="font-family:-apple-system,\'PingFang SC\',sans-serif;font-size:15px;'
            'color:#1f2937;line-height:1.7">'
            '<p>你正在进行「' + title + '」，验证码：</p>'
            '<p style="font-size:28px;font-weight:700;letter-spacing:6px;color:#047857">' +
            code + '</p><p style="color:#4b5563">' + rest + '</p></div>')
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        if cfg["tls"] in ("starttls", "tls"):
            smtp = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
        else:
            smtp = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15,
                                    context=ssl.create_default_context())
        try:
            if cfg["tls"] in ("starttls", "tls"):
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["from"], [to_addr], msg.as_string())
        finally:
            smtp.quit()
    except Exception as error:
        return False, "邮件发送失败（%s）" % type(error).__name__
    return True, ""
