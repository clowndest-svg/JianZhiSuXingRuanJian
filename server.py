import csv
import hmac
import math
import uuid
import logging
from app_modules.features import share_settings, public_projection, DEFAULT_SCOPE
import io
import os
import sqlite3
import hashlib
import json
from html import escape as html_escape, unescape as html_unescape
import secrets
import time
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from pydantic import BaseModel, Field, field_validator

DB_DIR = os.environ.get("QINGSU_DB_DIR", "/opt/qingsu/data")
UPLOAD_DIR = os.environ.get("QINGSU_UPLOAD_DIR", "/opt/qingsu/uploads")
WEB_DIR = os.environ.get("QINGSU_WEB_DIR", "/opt/qingsu/web")
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WEB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "qingsu.db")
SITE_BASE = os.environ.get("QINGSU_SITE_BASE", "https://124.220.54.64").rstrip("/")

app = FastAPI(title="轻塑·减脂塑形严管伴侣 API", version="5.0.0")

@app.middleware("http")
async def response_policy(request: Request, call_next):
    request_id=uuid.uuid4().hex
    started=time.monotonic()
    try:response=await call_next(request)
    except Exception as error:
        logging.getLogger('uvicorn.error').error('application_failure id=%s error=%s',request_id,type(error).__name__)
        response=JSONResponse({'detail':'服务器暂时无法处理，请稍后重试','request_id':request_id},status_code=500)
    response.headers["X-Request-ID"]=request_id
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["X-Frame-Options"]="DENY"
    if request.url.path.startswith(("/api/","/u/","/uploads/")):
        response.headers["Cache-Control"]="private, no-store"
    logging.getLogger("uvicorn.error").info("request id=%s path=%s status=%s elapsed_ms=%.1f",request_id,request.url.path.split("/")[1:2],response.status_code,(time.monotonic()-started)*1000)
    return response

app.add_middleware(
    CORSMiddleware,
    # 前端全部走 Authorization 头，不用 cookie，所以不需要也不应该带 credentials
    allow_origins=[SITE_BASE, "https://appassets.androidplatform.net"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nickname TEXT,
        token TEXT,
        created_at TEXT
    )
    """)
    # Profile table
    c.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        gender TEXT DEFAULT 'female',
        age INTEGER,
        height REAL,
        weight_jin REAL,
        target_weight_jin REAL,
        goal_type TEXT DEFAULT 'tone',
        dining_mode TEXT DEFAULT 'takeout',
        scene TEXT DEFAULT 'home',
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Food logs table (100% REAL)
    c.execute("""
    CREATE TABLE IF NOT EXISTS food_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        slot TEXT NOT NULL,
        food_name TEXT NOT NULL,
        cal INTEGER NOT NULL,
        protein_g REAL DEFAULT 0,
        carbs_g REAL DEFAULT 0,
        fat_g REAL DEFAULT 0,
        time_str TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Weight logs table (100% REAL)
    c.execute("""
    CREATE TABLE IF NOT EXISTS weight_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        weight_jin REAL NOT NULL,
        waist_cm REAL DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Workout logs table (100% REAL)
    c.execute("""
    CREATE TABLE IF NOT EXISTS workout_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        duration_minutes INTEGER DEFAULT 20,
        cal_burned REAL NOT NULL,
        plan_name TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Water logs table (100% REAL)
    c.execute("""
    CREATE TABLE IF NOT EXISTS water_logs (
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        cups_count INTEGER DEFAULT 0,
        updated_at TEXT,
        PRIMARY KEY(user_id, log_date),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Body cycle records & photos
    c.execute("""
    CREATE TABLE IF NOT EXISTS body_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        cycle_num INTEGER NOT NULL,
        cycle_name TEXT,
        photo_url TEXT,
        weight_jin REAL,
        waist_cm REAL,
        tone_score TEXT,
        ai_report TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # 外卖门禁真实事件流：拦截/退单/采纳平替/放行，全部由客户端在事件发生时上报
    c.execute("""
    CREATE TABLE IF NOT EXISTS takeout_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        cal_avoided REAL DEFAULT 0,
        dish_name TEXT,
        log_date TEXT NOT NULL,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    conn.commit()
    conn.close()

init_db()

# Mount uploaded photos
# Photos are served by the authenticated/signed media route below.



_ASSET_VER_CACHE = {}

def _asset_ver(path):
    """内容哈希当版本号：文件没变 URL 就不变，浏览器可以放心缓存一年；
    改了一个字节 URL 立刻换一个，不会再出现「部署了但用户还停在旧 app.js」。
    以前用 mtime，同一份内容重新部署也会换串，等于白让所有人重下一遍。"""
    try:
        stat = os.stat(path)
        stamp = (int(stat.st_mtime_ns), stat.st_size)
    except OSError:
        return "0"
    cached = _ASSET_VER_CACHE.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return "0"
    _ASSET_VER_CACHE[path] = (stamp, digest)
    return digest


def _asset_headers(path, wanted):
    """只有 URL 上带了正确的内容哈希，才给一年强缓存；
    对不上（旧链接、直接敲地址、爬虫）就退回必须回源校验，不会发错版本。"""
    current = _asset_ver(path)
    if wanted and current != "0" and wanted == current:
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return _no_cache()


def _no_cache():
    """这些响应以前完全没有 Cache-Control，浏览器按启发式长期缓存，
    于是部署新版后老访问者可能仍拿到旧 app.js，甚至旧 APK。"""
    return {"Cache-Control": "no-cache, must-revalidate"}


def render_index_html():
    """服务端这份首页在出口前改写三处引用，挂上版本号。

    只改服务端这一份：APK 里的 assets 通过 file:// 加载，不存在 HTTP 缓存问题，
    所以不需要为此重新打包。"""
    index_file = os.path.join(WEB_DIR, "index.html")
    if not os.path.exists(index_file):
        return None
    with open(index_file, "r", encoding="utf-8") as f:
        content = f.read()
    pairs = [
        ('href="style.css"', 'href="style.css?v=%s"', "style.css"),
        ('src="app.js"', 'src="app.js?v=%s"', "app.js"),
        ('src="features.js"', 'src="features.js?v=%s"', "features.js"),
        ('href="features.css"', 'href="features.css?v=%s"', "features.css"),
        ('href="/qingsu.apk"', 'href="/qingsu.apk?v=%s"', "qingsu.apk"),
    ]
    for old, fmt, name in pairs:
        content = content.replace(old, fmt % _asset_ver(os.path.join(WEB_DIR, name)))
    api_path=urllib.parse.urlsplit(SITE_BASE).path.rstrip('/')
    content=content.replace('<head>','<head>\n<script>window.__API_PATH__='+json.dumps(api_path).replace('<','\\u003c')+';</script>',1)
    return content


def _ensure_columns(c, table, cols):
    """缺列就补；SQLite 的 ALTER TABLE ADD COLUMN 是即时的，不必重建表。"""
    have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}
    for name, ddl in cols:
        if name not in have:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))


def migrate_db():
    """补安全列与每日语义列，并给老账号回填公开链接密钥。"""
    conn = get_db()
    c = conn.cursor()
    _ensure_columns(c, "users", [
        ("pw_salt", "TEXT"),
        ("token_hash", "TEXT"),
        ("share_secret", "TEXT"),
    ])
    _ensure_columns(c, "profiles", [
        ("day_mode", "TEXT DEFAULT 'rest'"),
        ("cycle_started_at", "TEXT"),
    ])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT id FROM users WHERE share_secret IS NULL OR share_secret = ''")
    for row in c.fetchall():
        c.execute("UPDATE users SET share_secret = ? WHERE id = ?",
                  (secrets.token_urlsafe(9), row["id"]))
    c.execute("SELECT user_id FROM profiles WHERE cycle_started_at IS NULL OR cycle_started_at = ''")
    for row in c.fetchall():
        c.execute("SELECT created_at FROM users WHERE id = ?", (row["user_id"],))
        u = c.fetchone()
        c.execute("UPDATE profiles SET cycle_started_at = ? WHERE user_id = ?",
                  (((u["created_at"] if u else now)[:10]), row["user_id"]))
    c.execute("""
    CREATE TABLE IF NOT EXISTS checklist_state (
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        state_json TEXT,
        updated_at TEXT,
        PRIMARY KEY(user_id, log_date),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_memory (
        user_id INTEGER NOT NULL,
        mem_key TEXT NOT NULL,
        mem_value TEXT NOT NULL,
        updated_at TEXT,
        PRIMARY KEY(user_id, mem_key),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS kb_entries (
        qkey TEXT PRIMARY KEY,
        answer TEXT,
        sources TEXT,
        fetched_at TEXT,
        hits INTEGER DEFAULT 0
    )
    """)
    # 访客打气：必须落到服务端，否则"已收到 N 枚"只数了访客自己这台设备
    c.execute("""
    CREATE TABLE IF NOT EXISTS cheers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        sender_hash TEXT NOT NULL,
        cheer_date TEXT NOT NULL,
        created_at TEXT,
        UNIQUE(user_id, kind, sender_hash, cheer_date),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    c.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL)")
    c.execute("INSERT OR IGNORE INTO sessions SELECT token_hash,id,? FROM users WHERE token_hash IS NOT NULL AND token_hash != ''", (int(time.time())+2592000,))
    c.execute("UPDATE users SET token_hash=NULL, token=NULL")
    c.execute("CREATE TABLE IF NOT EXISTS private_ai_answers (user_id INTEGER NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,question))")
    c.execute("CREATE TABLE IF NOT EXISTS daily_modes (user_id INTEGER NOT NULL, log_date TEXT NOT NULL, mode TEXT NOT NULL, PRIMARY KEY(user_id,log_date))")
    c.execute("CREATE TABLE IF NOT EXISTS request_receipts (user_id INTEGER NOT NULL, request_key TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,request_key,kind))")
    for table in ("food_logs","weight_logs","workout_logs","takeout_events"):
        c.execute("CREATE INDEX IF NOT EXISTS idx_%s_user_date ON %s(user_id,log_date)" % (table,table))
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    c.execute("CREATE TABLE IF NOT EXISTS daily_metrics (user_id INTEGER NOT NULL, log_date TEXT NOT NULL, metrics_json TEXT NOT NULL, origin TEXT NOT NULL, PRIMARY KEY(user_id,log_date))")
    c.execute("CREATE TABLE IF NOT EXISTS record_changes (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, record_id INTEGER NOT NULL, previous_json TEXT NOT NULL, operation TEXT NOT NULL, created_at TEXT NOT NULL)")
    _ensure_columns(c,"food_logs",[("source","TEXT DEFAULT 'legacy_estimate'"),("estimate_reason","TEXT")])
    conn.commit()
    conn.close()


migrate_db()


def new_token():
    return secrets.token_urlsafe(24)


def hash_token(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def _scrypt(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32).hex()


def make_pw(pw):
    """新口令一律 scrypt + 每用户随机盐。"""
    salt = secrets.token_hex(16)
    return salt, _scrypt(pw, salt)


def verify_pw(pw, user_row):
    """先按新算法验；老账号（无盐）退回历史 sha256，验中后由登录流程升级。"""
    # sqlite3.Row 没有 .get()，只能先确认列在再取值
    salt = user_row["pw_salt"] if "pw_salt" in (user_row.keys() or []) else None
    if salt:
        return _scrypt(pw, salt) == user_row["password_hash"]
    return hash_pw(pw) == user_row["password_hash"]


def public_url_for(user_row):
    """公开大屏必须带密钥，否则任何人都能靠猜用户名拖数据。"""
    keys = user_row.keys() if hasattr(user_row, "keys") else []
    uname = user_row["username"] if "username" in keys else ""
    share = user_row["share_secret"] if "share_secret" in keys else ""
    return "%s/u/%s?k=%s" % (SITE_BASE, urllib.parse.quote(str(uname or "")), share or "")


def check_share(conn, username, key):
    """校验公开访问密钥；不匹配一律返回 None，不给枚举留差异信号。"""
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),))
    user = c.fetchone()
    if not user or not key or key != (user["share_secret"] or ""):
        return None
    settings=share_settings(conn,user['id'])
    if not settings['enabled'] or (settings['expires_at'] and settings['expires_at']<time.time()):
        return None
    return dict(user)


_SHARE_LOST_HTML = (
    "<div style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:420px;"
    "margin:80px auto;padding:30px;background:#FFF;border-radius:16px;"
    "box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;'>"
    "<div style='font-size:44px;margin-bottom:10px;'>🔒</div>"
    "<h2 style='color:#1E293B;font-size:18px;'>链接不完整或已失效</h2>"
    "<p style='color:#64748B;font-size:13px;line-height:1.7;'>"
    "公开大屏需要对方分享的完整链接（末尾带 ?k=密钥）。<br>出于隐私考虑，这里不说明用户名是否存在。</p>"
    "<a href='/' style='display:inline-block;margin-top:16px;padding:10px 24px;background:#059669;"
    "color:#FFF;border-radius:20px;text-decoration:none;font-weight:600;'>返回轻塑主页</a></div>")


_LOGIN_WINDOW = 900
_LOGIN_MAX_FAILS = 5
_login_fails = {}
_public_hits = defaultdict(list)


def _ip(request):
    try:
        return request.client.host if request and request.client else "unknown"
    except Exception:
        return "unknown"


def _login_blocked(key):
    return rate_peek("login:" + key) >= _LOGIN_MAX_FAILS


def _login_fail(key):
    # 只记不判：上限给到极大，纯粹借它做"窗口内 +1 并在首次设 TTL"
    rate_hit("login:" + key, 10 ** 9, _LOGIN_WINDOW)


def _public_allowed(ip):
    """公开接口按 IP 限 60 次/分，堵住用户名枚举与拖库脚本。"""
    ok, _where, _n = rate_hit("pub:" + ip, 60, 60)
    return ok


def hash_pw(pw: str) -> str:
    """仅用于校验历史账号的旧 sha256 口令；新口令一律走 make_pw。"""
    return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token_hash = hash_token(authorization[7:].strip())
    with get_db() as conn:
        row = conn.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?", (token_hash,int(time.time()))).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    user=dict(row); user["_session_hash"]=token_hash
    return user

# Models
class ValidatedModel(BaseModel):
    @field_validator('*', mode='after')
    @classmethod
    def validate_values(cls, value, info):
        name=info.field_name
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("数字必须有限")
        if isinstance(value,str):
            if name in ('username','password','food_name','plan_name','question') and not value.strip():
                raise ValueError("内容不能为空")
            if len(value)> (2000 if name=='answer' else 500):
                raise ValueError("内容过长")
        limits={'weight_jin':(40,600),'target_weight_jin':(40,600),'waist_cm':(0,300),'age':(18,100),'height':(80,250),'cal':(0,10000),'duration_minutes':(1,1440),'cal_burned':(0,10000),'cups_count':(0,80),'cal_avoided':(0,10000)}
        if value is not None and name in limits and not limits[name][0]<=value<=limits[name][1]:
            raise ValueError("数值超出允许范围")
        if name=='gender' and value not in (None,'female','male'):
            raise ValueError("性别无效")
        if name=='day_mode' and value not in ('rest','workout'):
            raise ValueError("日模式无效")
        return value

class RegisterReq(ValidatedModel):
    username: str
    password: str
    nickname: Optional[str] = None
    gender: Optional[str] = "female"
    age: Optional[int] = None
    height: Optional[float] = None
    weight_jin: Optional[float] = None
    target_weight_jin: Optional[float] = None
    goal_type: Optional[str] = "tone"
    dining_mode: Optional[str] = "takeout"
    special_population: bool = False

class LoginReq(ValidatedModel):
    username: str
    password: str

class ProfileUpdateReq(ValidatedModel):
    gender: Optional[str] = None
    age: Optional[int] = None
    height: Optional[float] = None
    weight_jin: Optional[float] = None
    target_weight_jin: Optional[float] = None
    goal_type: Optional[str] = None
    dining_mode: Optional[str] = None
    scene: Optional[str] = None

class FoodLogReq(ValidatedModel):
    slot: str
    food_name: str
    cal: Optional[int] = None
    request_id: Optional[str] = None

class WeightLogReq(ValidatedModel):
    weight_jin: float
    waist_cm: Optional[float] = None

class WorkoutLogReq(ValidatedModel):
    duration_minutes: int = 20
    cal_burned: float = 220.0
    plan_name: str = "塑形训练"
    request_id: Optional[str] = None

class WaterLogReq(ValidatedModel):
    cups_count: int

class TakeoutEventReq(ValidatedModel):
    event_type: str
    cal_avoided: Optional[float] = 0
    dish_name: Optional[str] = None

class ModeReq(ValidatedModel):
    day_mode: str = "rest"

class ChecklistReq(ValidatedModel):
    state: Optional[dict] = None

class AskReq(ValidatedModel):
    question: str
    route_only: bool = False

# Helpers
def snapshot_metrics(c, user_id):
    row=c.execute("SELECT * FROM profiles WHERE user_id=?",(user_id,)).fetchone()
    if not row or any(row[k] is None for k in ("age","height","weight_jin","target_weight_jin")):return
    payload=json.dumps(compute_metrics(dict(row)))
    dates={r[0] for r in c.execute("SELECT log_date FROM food_logs WHERE user_id=? UNION SELECT log_date FROM workout_logs WHERE user_id=?",(user_id,user_id))}
    dates.add(date.today().isoformat())
    c.executemany("INSERT OR IGNORE INTO daily_metrics VALUES (?,?,?,?)",[(user_id,d,payload,"recorded" if d==date.today().isoformat() else "legacy_recalculation") for d in dates])

from app_modules.metrics import compute_metrics

# ==================== Auth Endpoints ====================

# 身高体重年龄是每日热量额度的输入。缺了或离谱了就明确报错，
# 绝不替用户编一个身体出来算 TDEE——这是这一轮假数据链的总根。
def _body_or_400(age, height, weight_jin, target_weight_jin):
    missing = [n for n, v in ((u'\u5e74\u9f84', age), (u'\u8eab\u9ad8', height),
                              (u'\u5f53\u524d\u4f53\u91cd', weight_jin),
                              (u'\u76ee\u6807\u4f53\u91cd', target_weight_jin)) if v is None]
    if missing:
        raise HTTPException(status_code=400,
                            detail=u'\u8bf7\u586b\u5199\uff1a' + u'\u3001'.join(missing)
                                   + u'\uff08\u8fd9\u4e9b\u76f4\u63a5\u51b3\u5b9a\u6bcf\u65e5\u70ed\u91cf\u989d\u5ea6\uff0c\u7cfb\u7edf\u4e0d\u66ff\u4f60\u731c\uff09')
    try:
        age = int(age); height = float(height)
        weight_jin = float(weight_jin); target_weight_jin = float(target_weight_jin)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=u'\u5e74\u9f84/\u8eab\u9ad8/\u4f53\u91cd\u8981\u586b\u6570\u5b57')
    if not (18 <= age <= 100):
        raise HTTPException(status_code=400, detail=u'\u5e74\u9f84\u8981\u5728 10~100 \u5c81\u4e4b\u95f4')
    if not (80 <= height <= 250):
        raise HTTPException(status_code=400, detail=u'\u8eab\u9ad8\u8981\u5728 80~250 \u5398\u7c73\u4e4b\u95f4')
    if not (40 <= weight_jin <= 600):
        raise HTTPException(status_code=400, detail=u'\u5f53\u524d\u4f53\u91cd\u8981\u5728 40~600 \u65a4\u4e4b\u95f4')
    if target_weight_jin / 2 / ((height / 100) ** 2) < 18.5:
        raise HTTPException(status_code=400, detail="目标体重对应BMI低于18.5，当前通用预算不适用于该目标，请调整目标或咨询专业人员")
    if not (40 <= target_weight_jin <= 600):
        raise HTTPException(status_code=400, detail=u'\u76ee\u6807\u4f53\u91cd\u8981\u5728 40~600 \u65a4\u4e4b\u95f4')
    return {'age': age, 'height': height,
            'weight_jin': weight_jin, 'target_weight_jin': target_weight_jin}


@app.post("/api/register")
def register(req: RegisterReq):
    if req.special_population:raise HTTPException(400,'本版本只提供一般成人记录预算，不适用于孕哺期或需要个性化营养治疗的情况')
    body = _body_or_400(req.age, req.height, req.weight_jin, req.target_weight_jin)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (req.username.strip(),))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="该用户名已存在，请直接登录或换一个用户名")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    token = new_token()
    salt, pw_hash = make_pw(req.password)
    share = secrets.token_urlsafe(9)
    nickname = req.nickname or req.username

    try:
        c.execute(
            "INSERT INTO users (username, password_hash, pw_salt, token_hash, share_secret, nickname, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (req.username.strip(), pw_hash, salt, None, share, nickname, now)
        )
        user_id = c.lastrowid
        c.execute('INSERT INTO share_settings VALUES (?,?,?,?)',(user_id,1,int(time.time())+7*86400,json.dumps(DEFAULT_SCOPE)))
        c.execute("INSERT INTO sessions VALUES (?,?,?)", (hash_token(token),user_id,int(time.time())+2592000))

        # Create profile
        c.execute("""
        INSERT INTO profiles (user_id, gender, age, height, weight_jin, target_weight_jin, goal_type, dining_mode, scene, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'home', ?)
        """, (user_id, req.gender, body["age"], body["height"], body["weight_jin"],
               body["target_weight_jin"], req.goal_type, req.dining_mode, now))

        # Log initial baseline weight
        today = date.today().isoformat()
        # 注册不采集围度，这里必须留 0：填任何数字都会被当成"基准腰围"参与后续增减计算
        c.execute("INSERT INTO weight_logs (user_id, log_date, weight_jin, waist_cm, created_at) VALUES (?, ?, ?, 0, ?)",
                  (user_id, today, req.weight_jin, now))

        # Initial cycle 1 baseline
        c.execute("""
        INSERT INTO body_cycles (user_id, cycle_num, cycle_name, photo_url, weight_jin, waist_cm, tone_score, ai_report, created_at)
        VALUES (?, 1, '第 1 周期 · 减脂启动期 (第1-7天)', '', ?, 0, '待首次打卡', ?, ?)
        """, (user_id, req.weight_jin,
              "初始基准档案已建立。今日目标热量按您填写的身高体重年龄算出；食谱与动作库按所选身形从内置方案中取一套，尚未做过任何照片分析。",
              now))

        c.execute("UPDATE profiles SET cycle_started_at=? WHERE user_id=?", (today,user_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback();raise HTTPException(409,"用户名已存在，请登录或换一个用户名")
    except Exception:conn.rollback();raise
    finally:conn.close()

    return {
        "code": 0,
        "msg": "注册成功！已为您建立专属真数据档案！",
        "token": token,
        "username": req.username,
        "nickname": nickname,
        "public_url": "%s/u/%s?k=%s" % (SITE_BASE, urllib.parse.quote(req.username.strip()), share)
    }

@app.post("/api/login")
def login(req: LoginReq, request: Request):
    key = "%s|%s" % (_ip(request), req.username.strip().lower())
    if _login_blocked(key):
        raise HTTPException(status_code=429, detail="失败次数过多，请 15 分钟后再试")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (req.username.strip(),))
    user = c.fetchone()
    if not user or not verify_pw(req.password, user):
        _login_fail(key)
        conn.close()
        # 不区分"用户不存在"与"密码错"，免得给枚举留信号
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    token = new_token()
    c.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
    c.execute("INSERT INTO sessions VALUES (?,?,?)", (hash_token(token),user["id"],int(time.time())+2592000))
    if not user["pw_salt"]:
        # 老账号在这次成功登录后透明升级成 scrypt + 随机盐
        salt, pw_hash = make_pw(req.password)
        c.execute("UPDATE users SET pw_salt = ?, password_hash = ? WHERE id = ?",
                  (salt, pw_hash, user["id"]))
    conn.commit()
    conn.close()
    rate_reset("login:" + key)
    user = dict(user)

    return {
        "code": 0,
        "msg": "登录成功！",
        "token": token,
        "username": user["username"],
        "nickname": user["nickname"],
        "public_url": public_url_for(user)
    }

@app.get("/api/me")
def get_me(user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
    p = dict(c.fetchone() or {})
    conn.close()
    metrics = compute_metrics(p)
    return {
        "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"]},
        "profile": p,
        "metrics": metrics,
        "public_url": public_url_for(user)
    }

@app.post("/api/profile/update")
def update_profile(req: ProfileUpdateReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
        cur = dict(c.fetchone() or {})

        snapshot_metrics(c,user["id"])
        gender = req.gender if req.gender is not None else cur.get("gender", "female")
        age = req.age if req.age is not None else cur.get("age")
        height = req.height if req.height is not None else cur.get("height")
        weight_jin = req.weight_jin if req.weight_jin is not None else cur.get("weight_jin")
        target_weight_jin = req.target_weight_jin if req.target_weight_jin is not None else cur.get("target_weight_jin")
        # 合并完再验一次：库里那行缺什么也要报错，不许拿 26/165/140/120 顶
        _body_or_400(age, height, weight_jin, target_weight_jin)
        goal_type = req.goal_type if req.goal_type is not None else cur.get("goal_type", "tone")
        dining_mode = req.dining_mode if req.dining_mode is not None else cur.get("dining_mode", "takeout")
        scene = req.scene if req.scene is not None else cur.get("scene", "home")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c.execute("""
        UPDATE profiles
        SET gender=?, age=?, height=?, weight_jin=?, target_weight_jin=?, goal_type=?, dining_mode=?, scene=?, updated_at=?
        WHERE user_id = ?
        """, (gender, age, height, weight_jin, target_weight_jin, goal_type, dining_mode, scene, now, user["id"]))

        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()

    return {"code": 0, "msg": "个人专属方案更新成功！"}

# ==================== Real Data Dashboard & Logs ====================

def compute_dashboard_data(user: dict) -> dict:
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()

    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
    p = dict(c.fetchone() or {})
    metrics = compute_metrics(p)

    # Real today food consumed
    c.execute("SELECT SUM(cal) as total_cal, SUM(protein_g) as total_p, SUM(carbs_g) as total_c, SUM(fat_g) as total_f FROM food_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    f_sum = c.fetchone()
    today_consumed = f_sum["total_cal"] or 0
    today_p = round(f_sum["total_p"] or 0, 1)
    today_c = round(f_sum["total_c"] or 0, 1)
    today_f = round(f_sum["total_f"] or 0, 1)

    # Real today workout burned
    c.execute("SELECT SUM(cal_burned) as total_burned FROM workout_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    w_sum = c.fetchone()
    today_burned = round(w_sum["total_burned"] or 0, 1)

    # Real today water cups
    c.execute("SELECT cups_count FROM water_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    w_log = c.fetchone()
    water_cups = w_log["cups_count"] if w_log else 0

    # Real today meals list
    c.execute("SELECT * FROM food_logs WHERE user_id = ? AND log_date = ? ORDER BY id DESC", (user["id"], today))
    today_meals = [dict(row) for row in c.fetchall()]

    # Real latest weight log
    c.execute("SELECT * FROM weight_logs WHERE user_id = ? ORDER BY log_date DESC,id DESC LIMIT 1", (user["id"],))
    latest_wt = c.fetchone()
    c.execute("SELECT weight_jin FROM weight_logs WHERE user_id = ? ORDER BY log_date ASC,id ASC LIMIT 1", (user["id"],))
    first_wt = c.fetchone()
    q_start = first_wt["weight_jin"] if first_wt else None
    current_weight = latest_wt["weight_jin"] if latest_wt else p.get("weight_jin", 140.0)

    # Calculate real remaining calorie budget
    # 运动日比休息日多 170 kcal（workout_cal - rest_cal），切换真的会改额度
    target_cal = metrics["target_cal"]
    mode_row=c.execute("SELECT mode FROM daily_modes WHERE user_id=? AND log_date=?", (user["id"],today)).fetchone()
    day_mode = mode_row["mode"] if mode_row else "rest"
    budget_cal = metrics["workout_cal"] if day_mode == "workout" else metrics["rest_cal"]
    remaining_cal = round(budget_cal - today_consumed)

    # Takeout lock status
    takeout_locked = remaining_cal <= 0
    takeout_warning = ""
    if takeout_locked:
        takeout_warning = f"今日已记热量超过估算预算 {abs(remaining_cal)} kcal。请先核对份量与记录；单日预算不用于诊断，也不建议通过断食补偿。"

    # Consecutive over-budget check (100% REAL)
    c.execute("""
    SELECT log_date, SUM(cal) as day_cal FROM food_logs
    WHERE user_id = ? AND log_date < ?
    GROUP BY log_date ORDER BY log_date DESC LIMIT 7
    """, (user["id"], today))
    past_days = c.fetchall()
    consecutive_over = 0
    over_cal_total = 0
    for day in past_days:
        day_cal = day["day_cal"] or 0
        if day_cal > target_cal + 100:
            consecutive_over += 1
            over_cal_total += round(day_cal - target_cal)
        else:
            break

    # Consecutive slacking check (100% REAL)
    consecutive_slacking = 0
    cur_d = date.today() - timedelta(days=1)
    joined=date.fromisoformat(user["created_at"][:10])
    for _ in range(7):
        if cur_d < joined: break
        ds = cur_d.isoformat()
        c.execute("SELECT id FROM workout_logs WHERE user_id = ? AND log_date = ?", (user["id"], ds))
        if not c.fetchone():
            consecutive_slacking += 1
            cur_d -= timedelta(days=1)
        else:
            break

    # 最近一次训练的真实日期：数据层要能回答"上次是什么时候"，
    # 否则这句会被丢给联网，回一句百科页里的日期糊弄人
    c.execute("SELECT log_date, cal_burned FROM workout_logs WHERE user_id = ? "
              "ORDER BY log_date DESC LIMIT 1", (user["id"],))
    lw = c.fetchone()
    if lw:
        last_workout_date = lw["log_date"]
        last_workout_cal = lw["cal_burned"] or 0
        last_workout_ago = (date.today() - date.fromisoformat(lw["log_date"])).days
    else:
        last_workout_date, last_workout_cal, last_workout_ago = None, 0, 0

    # 外卖自律真实统计：只算盘上有记录的事件，没有任何事件就是 0
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    c.execute("SELECT event_type, COALESCE(SUM(cal_avoided),0) as cal_sum, COUNT(*) as n "
              "FROM takeout_events WHERE user_id = ? GROUP BY event_type", (user["id"],))
    ev = {row["event_type"]: row for row in c.fetchall()}
    # sqlite3.Row 没有 .get()，只能先判存在再取下标
    def _n(t):
        return ev[t]["n"] if t in ev else 0

    def _cal(t):
        return ev[t]["cal_sum"] if t in ev else 0

    blocked_n, cancelled_n, substitute_n = _n("blocked"), _n("cancelled"), _n("substitute")
    cal_saved = round(_cal("substitute") + _cal("cancelled"))
    c.execute("SELECT COALESCE(SUM(CASE WHEN event_type='launched' THEN 1 ELSE 0 END),0) as launched, "
              "COUNT(*) as total FROM takeout_events WHERE user_id = ? AND log_date >= ?",
              (user["id"], week_start))
    wk = c.fetchone()

    # 每日状态：今天练没练、连续几天有记录、上次测量距今几天、清单勾选
    c.execute("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    today_workout_done = bool(c.fetchone()["n"])
    c.execute("SELECT log_date FROM (SELECT log_date FROM food_logs WHERE user_id=? "
              "UNION SELECT log_date FROM weight_logs WHERE user_id=? "
              "UNION SELECT log_date FROM workout_logs WHERE user_id=? "
              "UNION SELECT log_date FROM water_logs WHERE user_id=?)", (user["id"],) * 4)
    logged_days = {r["log_date"] for r in c.fetchall()}
    streak = 0
    cur_d = date.today()
    while cur_d.isoformat() in logged_days:
        streak += 1
        cur_d -= timedelta(days=1)
    c.execute("SELECT log_date, weight_jin FROM weight_logs WHERE user_id=? ORDER BY id DESC LIMIT 8", (user["id"],))
    wt_rows = list(reversed([dict(r) for r in c.fetchall()]))
    eta_days = None
    if len(wt_rows) >= 2:
        try:
            d0 = datetime.strptime(wt_rows[0]["log_date"], "%Y-%m-%d").date()
            d1 = datetime.strptime(wt_rows[-1]["log_date"], "%Y-%m-%d").date()
            span = max(1, (d1 - d0).days)
            rate = (wt_rows[-1]["weight_jin"] - wt_rows[0]["weight_jin"]) / span
            left = wt_rows[-1]["weight_jin"] - (p.get("target_weight_jin") or 0)
            if span >= 7 and rate < -0.01 and left > 0:
                eta_days = round(left / abs(rate))
        except (ValueError, TypeError, ZeroDivisionError):
            eta_days = None
    c.execute("SELECT substr(created_at,1,10) AS log_date FROM body_cycles WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],))
    last_meas = c.fetchone()
    days_since_measure = None
    if last_meas:
        try:
            days_since_measure = (date.today() - datetime.strptime(
                last_meas["log_date"], "%Y-%m-%d").date()).days
        except ValueError:
            pass
    c.execute("SELECT cycle_started_at FROM profiles WHERE user_id = ?", (user["id"],))
    pr_row = c.fetchone()
    cycle_day = _cycle_day(pr_row["cycle_started_at"] if pr_row else None)
    c.execute("SELECT state_json FROM checklist_state WHERE user_id = ? AND log_date = ?", (user["id"], today))
    cl = c.fetchone()
    try:
        checklist = json.loads(cl["state_json"]) if cl and cl["state_json"] else {}
    except ValueError:
        checklist = {}

    # Latest cycle report
    c.execute("SELECT * FROM body_cycles WHERE user_id = ? ORDER BY cycle_num DESC LIMIT 1", (user["id"],))
    latest_cycle = c.fetchone()

    # 完整日确认的当前状态：界面要知道今天到底确认过没有，
    # 不然按钮只能盲猜，用户看不见自己这一步做没做。
    # 必须在 conn.close() 之前查，放到返回字典里现查会 500。
    today_confirmed = bool(c.execute(
        "SELECT 1 FROM daily_reviews WHERE user_id=? AND log_date=? AND complete=1",
        (user["id"], today)).fetchone())
    conn.close()
    latest_cycle=dict(latest_cycle) if latest_cycle else None
    if latest_cycle and latest_cycle.get("photo_url"):
        latest_cycle["photo_url"]=signed_photo(latest_cycle["photo_url"])

    return {
        "today_date": today,
        "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"]},
        "metrics": metrics,
        "profile": p,
        "today_consumed": today_consumed,
        "today_burned": today_burned,
        "today_macros": {"protein": today_p, "carbs": today_c, "fat": today_f},
        "remaining_cal": remaining_cal,
        "day_mode": day_mode,
        "budget_cal": budget_cal,
        "today_workout_done": today_workout_done,
        "streak_days": streak,
        "eta_days": eta_days,
        "cycle_day": cycle_day,
        "days_since_measure": days_since_measure,
        "photo_due": (days_since_measure is None or days_since_measure >= 7),
        "checklist": checklist,
        "water_cups": water_cups,
        "water_ml": water_cups * 250,
        "water_target_ml": int(round((current_weight or 0) / 2.0 * 35 / 50.0) * 50),
        "current_weight_jin": current_weight,
        "today_meals": today_meals,
        "takeout_locked": takeout_locked,
        "takeout_warning": takeout_warning,
        "consecutive_over_days": consecutive_over,
        "consecutive_slacking_days": consecutive_slacking,
        "last_workout_date": last_workout_date,
        "last_workout_days_ago": last_workout_ago,
        "last_workout_cal": last_workout_cal,
        "latest_cycle": dict(latest_cycle) if latest_cycle else None,
        "body_suspect": body_looks_invented(p),
        "over_cal_total": over_cal_total,
        "start_weight_jin": q_start,
        "takeout_stats": {
            "intercepted": blocked_n + cancelled_n,
            "blocked": blocked_n,
            "cancelled": cancelled_n,
            "substituted": substitute_n,
            "cal_saved": cal_saved,
            "fat_jin": round(cal_saved / 7700.0 * 2, 1),
            "week_launched": (wk["launched"] if wk else 0),
            "week_events": (wk["total"] if wk else 0),
        },
        "public_url": public_url_for(user),
        "today": today,
        "today_confirmed": today_confirmed
    }

@app.get("/api/dashboard")
def get_dashboard(user: dict = Depends(get_current_user)):
    return compute_dashboard_data(user)

@app.get("/api/public/dashboard")
def get_public_dashboard(username: str, k: Optional[str] = None, request: Request = None):
    if not _public_allowed(_ip(request)):
        raise HTTPException(status_code=429, detail="访问过于频繁")
    conn = get_db()
    user = check_share(conn, username, k)
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="链接不完整或已失效")
    data = compute_dashboard_data(user)
    data.pop("checklist",None)
    cc = conn.cursor()
    cc.execute("SELECT COUNT(*) AS n FROM cheers WHERE user_id = ?", (user["id"],))
    row = cc.fetchone()
    data["cheer_total"] = int(row["n"] or 0) if row else 0
    settings=share_settings(conn,user['id'])
    conn.close()
    if settings['scope'].get('photos') and data.get('latest_cycle') and data['latest_cycle'].get('photo_url'):
        data['latest_cycle']['photo_url']=signed_photo(data['latest_cycle']['photo_url'],user)
    return public_projection(data,settings)


CHEER_KINDS = ("稳步减脂", "饮食超干净", "肌肉在生长", "喝水达人")


class CheerReq(ValidatedModel):
    username: str
    k: Optional[str] = None
    kind: str


@app.post("/api/cheer")
def post_cheer(req: CheerReq, request: Request = None):
    """打气只有写进服务端，"已收到 N 枚"才是别人真送的。"""
    ip = _ip(request)
    if not _public_allowed(ip):
        raise HTTPException(status_code=429, detail="访问过于频繁")
    allowed, store, _n = rate_hit("cheer:" + ip, 30, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="这台设备一小时内打气太多次了")
    kind = (req.kind or "").strip()
    if kind not in CHEER_KINDS:
        raise HTTPException(status_code=400, detail="只能送这几款打气徽章")
    conn = get_db()
    user = check_share(conn, req.username, req.k)
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="链接不完整或已失效")
    today = date.today().isoformat()
    sender = hashlib.sha256(("%s|%s|%s" % (ip, user["id"], today)).encode()).hexdigest()[:32]
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO cheers (user_id, kind, sender_hash, cheer_date, created_at) VALUES (?,?,?,?,?)",
              (user["id"], kind, sender, today,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    c.execute("SELECT COUNT(*) AS n FROM cheers WHERE user_id = ?", (user["id"],))
    total = int(c.fetchone()["n"] or 0)
    conn.close()
    return {"code": 0, "total": total, "kind": kind, "store": store}

# ==================== Real Food Logging with AI & Nutrition KB ====================

from app_modules.nutrition import FOOD_KB_ITEMS, parse_food_nutrition

@app.post("/api/food/log")
def log_food(req: FoodLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    snapshot_metrics(c,user["id"])
    request_id=getattr(req,"request_id",None)
    if request_id:
        c.execute("INSERT OR IGNORE INTO request_receipts VALUES (?,?,?,?)", (user["id"],request_id,"food",datetime.now().isoformat()))
        if c.rowcount==0:
            conn.close()
            return {"code":0,"duplicate":True,"msg":"这笔记录已保存，无需重复提交"}

    today = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    name = req.food_name.strip()
    est_cal = req.cal
    protein_g = 0.0
    carbs_g = 0.0
    fat_g = 0.0
    how_parsed = "direct"
    reason = ""

    if est_cal is not None:
        protein_g = carbs_g = fat_g = 0.0
        reason = "手填热量；宏量未知，不按比例倒推"
    else:
        parsed = parse_food_nutrition(name)
        est_cal = parsed["cal"]
        protein_g = parsed["protein_g"]
        carbs_g = parsed["carbs_g"]
        fat_g = parsed["fat_g"]
        how_parsed = parsed["source"]
        reason = parsed.get("reason", "")

    c.execute("""
    INSERT INTO food_logs (user_id, log_date, slot, food_name, cal, protein_g, carbs_g, fat_g, time_str, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user["id"], today, req.slot, name, est_cal, protein_g, carbs_g, fat_g, now_time, created_at))

    c.execute("UPDATE food_logs SET source=?,estimate_reason=? WHERE id=?",(how_parsed,reason,c.lastrowid))
    c.execute("DELETE FROM daily_reviews WHERE user_id=? AND log_date=?",(user["id"],today))
    conn.commit()
    conn.close()

    source_desc = {"nutrition_kb": "成分表匹配", "nutrition_kb_partial": "成分表部分匹配", "nutrition_heuristic": "关键词粗估", "direct": "你自己填的"}.get(how_parsed, "粗估")
    return {
        "code": 0,
        "msg": f"已成功记入【{req.slot}】：{name} ({est_cal} kcal · {source_desc})",
        "cal": est_cal,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "source": how_parsed,
        "reason": reason
    }

# ==================== Real Weight Logging ====================

@app.post("/api/weight/log")
def log_weight(req: WeightLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    snapshot_metrics(c,user["id"])
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    waist = req.waist_cm or 0

    c.execute("""
    INSERT INTO weight_logs (user_id, log_date, weight_jin, waist_cm, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (user["id"], today, req.weight_jin, waist, now))

    c.execute("UPDATE profiles SET weight_jin = ?, updated_at = ? WHERE user_id = ?",
              (req.weight_jin, now, user["id"]))

    c.execute("DELETE FROM daily_reviews WHERE user_id=? AND log_date=?",(user["id"],today))
    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"打卡成功！今日真实空腹体重：{req.weight_jin} 斤！"}

# ==================== Real Workout Logging ====================

@app.post("/api/workout/complete")
def log_workout(req: WorkoutLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    snapshot_metrics(c,user["id"])
    request_id=getattr(req,"request_id",None)
    if request_id:
        c.execute("INSERT OR IGNORE INTO request_receipts VALUES (?,?,?,?)", (user["id"],request_id,"workout",datetime.now().isoformat()))
        if c.rowcount==0:
            conn.close()
            return {"code":0,"duplicate":True,"msg":"这笔记录已保存，无需重复提交"}

    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
    INSERT INTO workout_logs (user_id, log_date, duration_minutes, cal_burned, plan_name, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user["id"], today, req.duration_minutes, req.cal_burned, req.plan_name, now))
    # 练了就是运动日：当天额度自动抬到 workout_cal，不用用户再手动切
    c.execute("INSERT INTO daily_modes VALUES (?,?,'workout') ON CONFLICT(user_id,log_date) DO UPDATE SET mode='workout'", (user["id"],today))

    c.execute("DELETE FROM daily_reviews WHERE user_id=? AND log_date=?",(user["id"],today))
    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"🏆 今日训练打卡成功！估算消耗 {req.cal_burned} kcal 已记录！"}

# ==================== Real Water Logging ====================

@app.post("/api/water/update")
def update_water(req: WaterLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
    INSERT INTO water_logs (user_id, log_date, cups_count, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id, log_date) DO UPDATE SET cups_count = excluded.cups_count, updated_at = excluded.updated_at
    """, (user["id"], today, req.cups_count, now))

    c.execute("DELETE FROM daily_reviews WHERE user_id=? AND log_date=?",(user["id"],today))
    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"饮水打卡：今日已喝水 {req.cups_count * 250} ml！"}

# ==================== Real Body Cycle & Photo Upgrade ====================

def _cycle_day(cycle_started_at):
    """按真实日历算本周期第几天，不再用"提交次数×7"冒充天数。"""
    try:
        start = datetime.strptime((cycle_started_at or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(1, (date.today() - start).days + 1)


def _progression(prev_weight, prev_waist, new_weight, new_waist, cycle_num, day, has_photo):
    """两次真实记录相减，按固定规则给下一周期安排。

    这是确定性规则，不是视觉模型：系统从不分析照片像素，报告里也只陈述数字。
    缺基准时明说缺，不编造增减。"""
    has_waist = bool(prev_waist) and bool(new_waist)
    has_weight = prev_weight is not None and new_weight is not None
    w_diff = round(new_weight - prev_weight, 1) if has_weight else None
    waist_diff = round(new_waist - prev_waist, 1) if has_waist else None

    if waist_diff is None:
        tone = "待补围度 (无基准)"
    elif waist_diff <= -2:
        tone = "极佳 (94分)"
    elif waist_diff <= 0:
        tone = "稳健 (88分)"
    else:
        tone = "需复核记录 (围度上升)"

    lines = []
    if w_diff is None:
        lines.append("• 体重：缺少上一次记录，本次只建立基准，暂不计算变化。")
    else:
        lines.append(f"• 体重变化 <strong>{w_diff:+.1f} 斤</strong>（两次空腹打卡实测，无补录）。")
    if waist_diff is None:
        lines.append("• 肚脐腰围：本次或上次缺测量值，<strong>围度结论不计算</strong>。")
    else:
        lines.append(f"• 肚脐腰围变化 <strong>{waist_diff:+.1f} cm</strong>。")
    lines.append("• 照片" + ("已存档，可与上次并排自行对照（系统未分析像素）。"
                 if has_photo else "未上传：本次改用你填写的数字，结论同样来自实测。"))

    if w_diff is None and waist_diff is None:
        plan = "本周期只建立了基准。下一次请同时填体重与腰围，才会得到进阶判断。"
    elif (waist_diff is not None and waist_diff <= -2) or (w_diff is not None and w_diff <= -2):
        plan = ("降得稳：每日缺口与身形方案保持不变，当前 4 个动作每组各加 2 次"
                "（例如 15 次→17 次），组间歇不变。")
    elif (waist_diff is not None and waist_diff > 0) or (w_diff is not None and w_diff > 0.5):
        plan = ("数字朝反方向走：先回看这两天有没有漏记酱料、油与饮品；"
                "确认无误后把每日目标下调 100 kcal，训练量不变。")
    elif w_diff is not None and abs(w_diff) <= 0.3 and (waist_diff is None or abs(waist_diff) <= 0.3):
        plan = ("基本不动属于常见适应：主食按现有量减 1/4（蛋白质不减），"
                "并把一次长时间有氧换成两次 25 分钟快走。")
    else:
        plan = "变化在正常区间：缺口、动作与组数都保持不变，继续按天记录。"

    day_txt = f"（本周期第 {day} 天）" if day else ""
    name = f"第 {cycle_num} 周期 · 进阶塑形期 {day_txt}"
    report = ("<br>".join(lines)
              + f"<br><br>🚀 <strong>第 {cycle_num} 周期安排（依据上面数字的规则判断，非视觉分析）</strong><br>"
              + plan
              + "<br>• 动作库与食谱不会因提交本表自动改写，换身形仍需在【档案】里选。")
    return name, tone, report, w_diff, waist_diff


async def _new_cycle(user, weight_jin, waist_cm, photo, label):
    if not math.isfinite(weight_jin) or not 40<=weight_jin<=600 or not math.isfinite(waist_cm or 0) or not 0<=(waist_cm or 0)<=300:
        raise HTTPException(status_code=400,detail="体重或围度超出范围")
    raw=None
    if photo and getattr(photo,"filename",None):
        raw=await photo.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise HTTPException(413,"照片请小于8MB")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(_persist_cycle,user,weight_jin,waist_cm,raw,label)


def _persist_cycle(user,weight_jin,waist_cm,raw,label):
    image_bytes=None
    if raw:
        try:
            from PIL import Image, ImageOps
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ("JPEG","PNG","WEBP") or image.width*image.height>20000000:
                    raise ValueError("图片格式或尺寸不支持")
                image=ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2400,2400)); out=io.BytesIO(); image.save(out,format="JPEG",quality=85)
                image_bytes=out.getvalue()
        except Exception:
            raise HTTPException(status_code=400,detail="请选择有效的JPEG、PNG或WebP图片")
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = date.today().isoformat()

        c.execute("SELECT * FROM body_cycles WHERE user_id = ? ORDER BY cycle_num DESC LIMIT 1", (user["id"],))
        last_cycle = c.fetchone()
        new_cycle_num = (last_cycle["cycle_num"] if last_cycle else 0) + 1

        photo_url = ""
        if image_bytes:
            fname=uuid.uuid4().hex+".jpg"
            with open(os.path.join(UPLOAD_DIR,fname),"wb") as f: f.write(image_bytes)
            photo_url=f"/uploads/{fname}"
        elif last_cycle and last_cycle["photo_url"]:
            photo_url = last_cycle["photo_url"]

        c.execute("SELECT cycle_started_at FROM profiles WHERE user_id = ?", (user["id"],))
        pr = c.fetchone()
        day = _cycle_day(pr["cycle_started_at"] if pr else None)

        cycle_name, tone_score, ai_report, _, _ = _progression(
            last_cycle["weight_jin"] if last_cycle else None,
            last_cycle["waist_cm"] if last_cycle else None,
            weight_jin, waist_cm, new_cycle_num, day, bool(photo_url))

        c.execute("""
        INSERT INTO body_cycles (user_id, cycle_num, cycle_name, photo_url, weight_jin, waist_cm, tone_score, ai_report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user["id"], new_cycle_num, cycle_name, photo_url, weight_jin, waist_cm or 0,
              tone_score, ai_report, now))
        c.execute("INSERT INTO weight_logs (user_id, log_date, weight_jin, waist_cm, created_at) VALUES (?, ?, ?, ?, ?)",
                  (user["id"], today, weight_jin, waist_cm or 0, now))
        c.execute("UPDATE profiles SET weight_jin = ?, cycle_started_at = ?, updated_at = ? WHERE user_id = ?",
                  (weight_jin, today, now, user["id"]))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
    return {"code": 0, "msg": f"🎉 {label}已记录，第 {new_cycle_num} 周期安排已生成",
            "cycle_num": new_cycle_num, "photo_url": signed_photo(photo_url) if photo_url else "",
            "cycle_day": day, "ai_report": ai_report}


@app.post("/api/cycle/upgrade")
async def upgrade_cycle(
    weight_jin: float = Form(...),
    waist_cm: float = Form(...),
    photo: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user)
):
    """带照片的周期提交。"""
    return await _new_cycle(user, weight_jin, waist_cm, photo, "身材照")


@app.post("/api/cycle/measure")
async def submit_measure(
    weight_jin: float = Form(...),
    waist_cm: Optional[float] = Form(0),
    photo: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user)
):
    """不想拍照的通道：只填体重与围度也能建立周期并拿到进阶安排。"""
    return await _new_cycle(user, weight_jin, waist_cm or 0, photo, "围度测量")


@app.post("/api/profile/mode")
def set_day_mode(req: ModeReq, user: dict = Depends(get_current_user)):
    """休息日与运动日的差别落在"今天被允许吃多少"上，不只是换个按钮颜色。"""
    mode = req.day_mode if req.day_mode in ("rest", "workout") else "rest"
    conn = get_db()
    conn.execute("INSERT INTO daily_modes VALUES (?,?,?) ON CONFLICT(user_id,log_date) DO UPDATE SET mode=excluded.mode", (user["id"],date.today().isoformat(),mode))
    conn.commit()
    conn.close()
    return {"code": 0, "day_mode": mode}


@app.post("/api/checklist")
def save_checklist(req: ChecklistReq, user: dict = Depends(get_current_user)):
    """采购清单按日期存，换一天自然是一张空表。"""
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO checklist_state (user_id, log_date, state_json, updated_at) VALUES (?, ?, ?, ?) "
              "ON CONFLICT(user_id, log_date) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at",
              (user["id"], today, json.dumps(req.state or {}, ensure_ascii=False), now))
    conn.commit()
    conn.close()
    return {"code": 0}


@app.get("/api/export.csv")
def export_csv(user: dict = Depends(get_current_user)):
    """本人全部流水导出，UTF-8 BOM 保证 Excel 打开不乱码。"""
    conn = get_db()
    c = conn.cursor()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["表", "日期", "项目", "数值", "备注"])
    for name, sql, cols in [
        ("饮食", "SELECT log_date, slot, food_name, cal, protein_g, carbs_g, fat_g, time_str, source, estimate_reason FROM food_logs WHERE user_id=? ORDER BY id",
         lambda r: [r["log_date"], r["slot"]+" · "+r["food_name"], r["cal"],
                    (f"蛋白{r['protein_g']}g 碳水{r['carbs_g']}g 脂肪{r['fat_g']}g（估算）" if r['source'] in ('nutrition_kb','nutrition_kb_partial') else "宏量未知")+f"；来源:{r['source']}；{r['estimate_reason'] or ''}"]),
        ("体重", "SELECT log_date, weight_jin, waist_cm FROM weight_logs WHERE user_id=? ORDER BY id",
         lambda r: [r["log_date"], "空腹体重", r["weight_jin"], f"腰围 {r['waist_cm'] or '未填'} cm"]),
        ("训练", "SELECT log_date, duration_minutes, cal_burned, plan_name FROM workout_logs WHERE user_id=? ORDER BY id",
         lambda r: [r["log_date"], r["plan_name"], r["cal_burned"], f"{r['duration_minutes']} 分钟"]),
        ("饮水", "SELECT log_date, cups_count FROM water_logs WHERE user_id=? ORDER BY log_date",
         lambda r: [r["log_date"], "饮水", r["cups_count"], f"{(r['cups_count'] or 0) * 250} ml"]),
        ("门禁事件", "SELECT log_date, event_type, cal_avoided, dish_name FROM takeout_events WHERE user_id=? ORDER BY id",
         lambda r: [r["log_date"], r["event_type"], r["cal_avoided"], r["dish_name"] or ""]),
        ("周期", "SELECT created_at, cycle_num, cycle_name, weight_jin, waist_cm, tone_score FROM body_cycles WHERE user_id=? ORDER BY cycle_num",
         lambda r: [(r["created_at"] or "")[:10], r["cycle_name"], r["weight_jin"],
                    f"腰围 {r['waist_cm'] or '未填'} cm · {r['tone_score']}"]),
    ]:
        for row in c.execute(sql, (user["id"],)):
            vals = cols(dict(row))
            w.writerow([("\'"+v) if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@","\t","\r")) else v for v in [name]+vals])
    conn.close()
    return Response(content="\ufeff" + out.getvalue(),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="qingsu_export.csv"',
                             "Cache-Control": "no-cache, must-revalidate"})




# ==================== 外卖门禁事件与顾问问答 ====================

@app.post("/api/takeout/event")
def log_takeout_event(req: TakeoutEventReq, user: dict = Depends(get_current_user)):
    """门禁真的拦下、用户真的退单或采纳平替时上报一条。

    只接受这四种事件；没有热量依据的（单纯被门禁拦下）一律记 0，
    绝不替用户编一个"省了多少"。"""
    et = (req.event_type or "").strip()
    if et not in ("blocked", "cancelled", "substitute", "launched"):
        raise HTTPException(status_code=400, detail="未知的事件类型")
    cal = 0.0 if et == "blocked" else max(0.0, float(req.cal_avoided or 0))
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO takeout_events (user_id, event_type, cal_avoided, dish_name, log_date, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              (user["id"], et, round(cal, 1), (req.dish_name or "")[:60],
               date.today().isoformat(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return {"code": 0, "msg": "已记录"}


_ASK_LIMIT_PER_MIN = 12
_ask_hits = defaultdict(list)


def _ask_allowed(user_id):
    """给联网出口加每用户限频，免得这个接口变成开放的免费代理。

    计数优先落 Redis：进程内字典一重启就清零，用户会觉得"刚限完又放开了"，
    而多进程部署时进程内计数各算各的，等于限流形同虚设。Redis 不通时
    rate_hit 自己退回内存，不会因为缓存挂了就把问答整个拒掉。
    """
    ok, _where, _n = rate_hit("ask:" + str(user_id), _ASK_LIMIT_PER_MIN, 60)
    return ok


def _strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def web_search(query, limit=4):
    """抓必应国内版的自然结果；抓不到就返回空列表，不编。"""
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&setmkt=zh-CN"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=12) as resp:
        page = resp.read().decode("utf-8", "replace")
    items = re.findall(
        r'<li class="b_algo".*?<h2>.*?<a[^>]*href="([^"]+)".*?>(.*?)</a>.*?<p[^>]*>(.*?)</p>',
        page, re.S)
    out = []
    for href, title, snip in items:
        title = html_escape(_strip_tags(title))
        href = (href or "").strip()
        if not title or not href.startswith("http"):
            continue
        out.append({"title": title,
                    "snippet": html_escape(_strip_tags(snip)[:180]),
                    "url": html_escape(href, quote=True),
                    "host": urllib.parse.urlparse(href).netloc})
        if len(out) >= limit:
            break
    return out


def answer_from_user_data(q, d):
    from app_modules.fact_scopes import answer as scoped_answer
    scoped=scoped_answer(q,d,get_db,_deficit_rows)
    if scoped:return scoped
    """能用自己的真实流水回答的问题优先在这里答，一句都不编。"""
    m = d["metrics"]
    consumed, burned = d["today_consumed"], d["today_burned"]
    wt = d["current_weight_jin"]
    tgt = (d.get("profile") or {}).get("target_weight_jin")
    mode_txt = "运动日" if d.get("day_mode") == "workout" else "休息日"

    # "平台期体重不掉"问的是为什么不掉，不是问现在几斤——别让体重分支把它抢走
    if any(k in q for k in ("多重", "体重", "几斤", "多少斤"))             and not any(k in q for k in ("平台期", "不掉", "不降", "卡住", "反弹")):
        gap = round(wt - tgt, 1) if tgt else None
        line = f"你最新记录的空腹体重是 <strong>{wt} 斤</strong>"
        if gap is not None and gap > 0:
            line += f"，离目标 {tgt} 斤还差 <strong>{gap} 斤</strong>"
        elif gap is not None:
            line += f"，目标 {tgt} 斤已达成（比目标低 {abs(gap)} 斤）"
        if d.get("start_weight_jin"):
            line += f"；从第一次记录的 {d['start_weight_jin']} 斤算起，累计变化 {round(wt - d['start_weight_jin'], 1)} 斤"
        if d.get("eta_days"):
            line += f"；按最近几天的真实速率，约还需 {d['eta_days']} 天到达标（速率一变就会重算，不是承诺）"
        return line + "。以上都来自你自己的打卡记录，没有补录也没有估算。"

    # "明天能不能吃一整个蛋糕"问的是未来那一顿，不是今天剩多少额度——
    # 让它落到场景层给折算算法，别用今天的余额糊过去
    if any(k in q for k in ("还剩", "额度", "能吃", "还能吃", "余量"))             and not any(k in q for k in ("明天", "后天", "一整个", "一顿吃完")):
        return (f"今天是{mode_txt}，预算 <strong>{d['budget_cal']} kcal</strong>，"
                f"还能吃 <strong>{d['remaining_cal']} kcal</strong>"
                f"（已摄入 {consumed}，训练已消耗 {burned}）。"
                f"休息日预算 {m['rest_cal']}、运动日 {m['workout_cal']}，差别就在这 170 kcal。"
                + ("额度已用完，外卖门禁会拦下你。" if d["remaining_cal"] <= 0 else ""))

    if any(k in q for k in ("运动日", "休息日", "切换成", "日子")) \
            and not any(k in q for k in ("酸奶", "牛奶", "肉", "水果", "和什么", "哪个")):
        return (f"当前是<strong>{mode_txt}</strong>。两者只差在当日预算：休息日 {m['rest_cal']} kcal，"
                f"运动日 {m['workout_cal']} kcal（多 170 kcal）。训练打卡成功后会自动切成运动日，"
                f"不需要你手动改。")

    if any(k in q for k in ("吃多", "吃撑", "补救", "补偿", "怎么补", "会不会胖", "长肉")):
        budget = d.get("budget_cal") or 0
        left = d.get("remaining_cal")
        mode_name = "运动日" if d.get("day_mode") == "workout" else "休息日"
        if not consumed:
            return ("今天还没有饮食记录，所以我不知道你到底吃进去多少。"
                    "先把这一餐记进【食谱/外卖】，我再按你的真实额度说晚上怎么安排——"
                    "没记录就开口给建议，那只能是编的。")
        line = (f"今天记录到摄入 <strong>{consumed}</strong> kcal，{mode_name}预算 {budget} kcal，"
                f"已消耗 {burned} kcal。")
        if left is not None and left < 0:
            line += (f" 超出 <strong>{abs(left)}</strong> kcal。按 7700 kcal 折 1 kg 脂肪粗算约 "
                     f"{round(abs(left) / 7700 * 2, 2)} 斤，这是折算不是实测。")
            line += (" 晚上只做一件事：把剩下的额度按正常餐次吃掉。不用断食、不用催吐、"
                     "也不要临时加练双倍来'抵债'——那套做法在这款应用里没有任何记账支持。")
        else:
            line += (f" 其实没有超，还剩 {left} kcal。你担心的'吃多'在数字上并没有发生，"
                     f"按原计划走完今天就行。")
        return line


    if any(k in q for k in ("吃了", "摄入", "吃什么了", "吃啥")):
        meals = d.get("today_meals") or []
        if not meals:
            return "今天还没有一条饮食记录，所以摄入按 0 计（不是按目标计）。记一笔才会有数字。"
        names = "、".join(f"{html_escape(x['food_name'])}({x['cal']}k)" for x in meals[:6])
        return (f"今天累计摄入 <strong>{consumed} kcal</strong>，共 {len(meals)} 条：{names}。"
                f"注意这些热量是系统按菜名关键词粗估的，不是营养成分表数据。")

    # 这一支只回答"我练了没有/练掉多少"，所以"要不要练/停不停"这类方法问句必须让路，
    # 否则"生理期要不要停训练"会被一句流水数字顶掉。
    if any(k in q for k in ("练了", "练过", "训练了吗", "今天练", "打卡了吗", "练得",
                            "训练消耗", "练了多久")) \
            and not any(k in q for k in ("要不要", "该不该", "能不能", "可不可以", "停", "要不要")):
        done = "今天已有训练记录" if d.get("today_workout_done") else "今天还没有训练记录"
        # 这个天数是从昨天往前数的，说成"已连续 N 天没练"会和上一句"今天已练"打脸
        tail = (f"；今天之前已连续 {d['consecutive_slacking_days']} 天没练"
                if d.get("consecutive_slacking_days") else "")
        return f"{done}，训练消耗记录为 <strong>{burned} kcal</strong>{tail}。"

    if any(k in q for k in ("上次训练", "最近一次练", "哪天练", "几天没练", "练于")):
        last = d.get("last_workout_date")
        if not last:
            return "还没有任何训练记录，所以没有「上次」可说。第一次练完点【记录今日训练打卡】才会有日期。"
        return (f"最近一次训练记录在 <strong>{html_escape(last)}</strong>"
                f"（{d.get('last_workout_days_ago', 0)} 天前），"
                f"当时记的消耗是 <strong>{d.get('last_workout_cal', 0)} kcal</strong>。"
                f"今天{'已经练过' if d.get('today_workout_done') else '还没练'}。")

    if any(k in q for k in ("维持代谢", "基础代谢", "TDEE", "tdee", "BMR")):
        return (f"公式估算的维持代谢（TDEE）约为 <strong>{m['tdee']} kcal</strong>，"
                f"基础代谢（BMR）约 {m.get('bmr', '—')} kcal。"
                f"净缺口按 TDEE + 当日训练消耗 − 当日摄入算，不是按 BMR 算——"
                f"按 BMR 记账会把每天的活动消耗漏掉。")

    if any(k in q for k in ("还要多久", "多久能", "什么时候能到", "几天能到")):
        eta = d.get("eta_days")
        if eta is None:
            return ("现在还算不出到达标还要多久：需要连续几天的真实体重记录才能算速率，"
                    "单点数据算出来的只是猜。多记几天再问我。")
        return (f"按最近几天的真实速率，约还需 <strong>{eta} 天</strong>到达 {tgt} 斤目标。"
                f"这个数每记一次就会重算，速率一变它就变，不是承诺。")

    if any(k in q for k in ("缺口", "赤字", "净缺")):
        if not consumed and not burned:
            return "今天没有可计算的完整摄入与训练记录，缺口未知；未记录不等于零摄入或零缺口。"
        net = round(m["tdee"] + burned - consumed)
        return (f"按已记内容暂算缺口 <strong>{net} kcal</strong>（未确认完整时不能代表全天）"
                f"（维持代谢 {m['tdee']} + 训练消耗 {burned} − 摄入 {consumed}），"
                f"你的身形目标缺口是 {m['deficit']} kcal。")

    if any(k in q for k in ("超标", "富余", "超了")):
        if not d["consecutive_over_days"]:
            return "最近没有连续超标的记录。"
        return (f"已连续 <strong>{d['consecutive_over_days']}</strong> 天超出目标，"
                f"累计富余约 <strong>{d['over_cal_total']} kcal</strong>（按每日超出部分累加）。")

    if any(k in q for k in ("拦截", "挡了", "自律", "功勋", "省下", "省了", "少摄入")):
        s = d["takeout_stats"]
        if not (s["intercepted"] or s["substituted"] or s["cal_saved"]):
            return "还没有任何拦截或平替记录。这个数字只统计真实发生过的事件，不会预先给你记功。"
        return (f"累计拦下 <strong>{s['intercepted']}</strong> 次（门禁硬拦 {s['blocked']} 次、审核后主动退单 {s['cancelled']} 次），"
                f"另采纳低卡平替 {s['substituted']} 次。有热量依据的少摄入合计 <strong>{s['cal_saved']} kcal</strong>"
                f"（只累计平替与退单两种算得出差额的事件），按 7700 kcal≈1 kg 纯脂肪折约 {s['fat_jin']} 斤。")

    if any(k in q for k in ("连续", "坚持", "几天", "streak")):
        return f"连续有记录的天数是 <strong>{d.get('streak_days', 0)}</strong> 天（任意一项打卡都算）。"

    if any(k in q for k in ("喝水", "饮水", "喝多少", "喝够水", "够水", "水喝")):
        return (f"今天记了 <strong>{d['water_cups']} 杯</strong>（约 {d['water_ml']} ml），"
                f"按你当前体重算的目标是 {d.get('water_target_ml')} ml（体重 kg × 35）。")

    if any(k in q for k in ("拍照", "身材照", "该拍", "围度", "周期", "腰围")):
        if d.get("photo_due"):
            gap = d.get("days_since_measure")
            why = "还没有过测量记录" if gap is None else f"距上次记录已 {gap} 天"
            return (f"<strong>该更新了</strong>（{why}）。两条路都行："
                    f"① 按同一光线、同一角度、空腹、卷尺水平绕肚脐拍一张；"
                    f"② 不想出镜就只填体重与肚脐腰围，进阶安排照样会更新。"
                    + (f" 当前是第 {d['cycle_day']} 天。" if d.get("cycle_day") else ""))
        return f"本周期第 {d.get('cycle_day') or '?'} 天，还没到 7 天的更新点，继续按天记录即可。"

    if any(k in q for k in ("蛋白质", "蛋白够", "蛋白吃", "宏量", "碳水", "脂肪")) \
            and not any(k in q for k in ("算不算", "优质蛋白吗", "是不是")):
        mc = d["today_macros"]
        return (f"目标：蛋白 {m['protein_g']}g / 慢碳 {m['carbs_g']}g / 脂肪 {m['fat_g']}g。"
                f"今天记录到的：蛋白 {mc['protein']}g / 碳水 {mc['carbs']}g / 脂肪 {mc['fat']}g。"
                f"这些是匹配食材的估算汇总；手填热量或未匹配食材的宏量未知，不能据此认定全天营养充足。")

    lc = d.get("latest_cycle")
    if lc and any(k in q for k in ("计划", "安排", "进阶", "下一步")):
        return f"当前{mode_txt}，第 {lc['cycle_num']} 周期：{lc['cycle_name']}，评级 {lc['tone_score']}。"

    return None


# ==================== Redis 与 AI 引擎状态（第五批后续） ====================
# Redis uses the bounded client in app_modules.cache.
# 所有 Redis 调用都允许失败并退回进程内实现——缓存挂了不能把整个应用带崩。
_REDIS_HOST = os.environ.get("QINGSU_REDIS_HOST", "127.0.0.1")
_REDIS_PORT = int(os.environ.get("QINGSU_REDIS_PORT", "6379"))
_redis_fail_until = [0.0]
_redis_last_err = [""]      # 最近一次 Redis 失败原因，状态接口要能说出来
_redis_seen = [False]


def _redis_cmd(args, timeout=0.35):
    if time.time() < _redis_fail_until[0]:return False,None
    try:
        from app_modules.cache import command
        value=command(args);_redis_seen[0]=True;_redis_last_err[0]=""
        return True,value
    except Exception as e:
        _redis_fail_until[0]=time.time()+30
        _redis_last_err[0]=type(e).__name__
        logging.getLogger("uvicorn.error").warning("cache_degraded error=%s",type(e).__name__)
        return False,None


def redis_up():
    ok, v = _redis_cmd(["PING"])
    return bool(ok and v == "PONG")


_mem_buckets = {}   # Redis 不可用时的进程内兜底


def rate_hit(key, limit, window_sec):
    """固定窗口计数。Redis 在就用 Redis（重启不清零、多进程共享），不在就用内存。

    这条是"失败要看得见"的落点：返回值第二个元素说明计数存在哪，
    状态接口会把它显示出来，免得 Redis 挂了很久而没人知道限流口径已经变了。
    """
    from app_modules.cache import LIMIT_SCRIPT
    ok, val = _redis_cmd(["EVAL", LIMIT_SCRIPT, 1, "qs:rl:" + key, window_sec])
    if ok and isinstance(val, int):
        return val <= limit, "redis", val
    now = time.time()
    if len(_mem_buckets)>10000:
        for stale in list(_mem_buckets):
            if not _mem_buckets[stale] or now-_mem_buckets[stale][-1]>900:_mem_buckets.pop(stale,None)
        if len(_mem_buckets)>10000:return False,"memory-capacity",limit+1
    bucket = _mem_buckets.setdefault(key, [])
    bucket[:] = [t for t in bucket if now - t < window_sec]
    bucket.append(now)
    return len(bucket) <= limit, "memory", len(bucket)


def rate_peek(key):
    """只读当前窗口计数，不自增。登录失败检查用这条——查一次不该等于失败一次。"""
    ok, val = _redis_cmd(["GET", "qs:rl:" + key])
    if ok:
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0
    now = time.time()
    return len([t for t in _mem_buckets.get(key, []) if now - t < _LOGIN_WINDOW])


def rate_reset_all_ask():
    """清掉所有问答限流窗口（回归台与运维临时放行用）。"""
    ok, val = _redis_cmd(["KEYS", "qs:rl:ask:*"])
    if ok and isinstance(val, list):
        for k in val:
            _redis_cmd(["DEL", k])
    for k in [x for x in list(_mem_buckets) if x.startswith("ask:")]:
        _mem_buckets.pop(k, None)


def rate_reset(key):
    """清掉一个限流窗口。测试要用，运维临时放行某人也只用得着这一句。"""
    _redis_cmd(["DEL", "qs:rl:" + key])
    _mem_buckets.pop(key, None)


def cache_get(k):
    ok, v = _redis_cmd(["GET", "qs:kb:" + k])
    return v if ok else None


def cache_set(k, val, ttl):
    ok, _ = _redis_cmd(["SETEX", "qs:kb:" + k, ttl, val])
    return ok


# ---------- 给本机（手机上的）AI 用的共享上下文与回写 ----------

# 2026-10-16 之前，注册与档案保存会用 26/165/140/120 这组字面量兜底，
# 于是有人从没填过年龄身高体重，额度却按这具没问过的身体算。代码已经修了，
# 库里存量的行还在——这里只负责认出来并提醒核对，绝不替用户编一组新数。
LEGACY_DEFAULT_BODY = (26, 165.0, 140.0, 120.0)


def body_looks_invented(p):
    try:
        got = (int(p.get("age") or 0), float(p.get("height") or 0),
               float(p.get("weight_jin") or 0), float(p.get("target_weight_jin") or 0))
    except (TypeError, ValueError):
        return False
    return got == LEGACY_DEFAULT_BODY


@app.get("/api/ai/status")
def ai_status(user: dict = Depends(get_current_user)):
    """引擎健康面：本机模型、服务器模型、Redis 各自通不通，前端据此决定用谁。"""
    ok = llm_chat("ping", max_tokens=4) is not None
    r_ok = redis_up()
    return {"code": 0,
            "server_model": "up" if ok else "down",
            "model_name": "qwen2.5-0.5b-instruct-q8_0",
            "redis": "up" if r_ok else "down",
            "redis_why": "" if r_ok else (_redis_last_err[0] or "冷却中或从未连上"),
            "kb_backend": "private-sqlite"}


@app.get("/api/ai/context")
def ai_context(user: dict = Depends(get_current_user)):
    """把本人真实数据摘要 + 长期记忆 + 知识库要点打包给客户端。

    两个引擎（手机本地的、服务器上的）读的是同一份，所以记忆与知识是共用的，
    换引擎不会让用户之前说过的话失效。
    """
    d = compute_dashboard_data(user)
    mem = memory_list(user["id"])
    conn = get_db()
    c = conn.cursor()
    conn.close()
    kb = []  # No unaudited global answers in personal prompts.
    digest = {
        "weight_jin": d["current_weight_jin"],
        "target_jin": (d.get("profile") or {}).get("target_weight_jin"),
        "budget_cal": d.get("budget_cal"),
        "today_consumed": d["today_consumed"],
        "today_burned": d["today_burned"],
        "remaining_cal": d.get("remaining_cal"),
        "day_mode": d.get("day_mode"),
        "cycle_day": d.get("cycle_day"),
        "streak_days": d.get("streak_days"),
        "water_target_ml": d.get("water_target_ml"),
    }
    return {"code": 0, "digest": digest, "memory": mem, "kb": kb}


class AiRecordReq(ValidatedModel):
    question: str
    answer: str
    sources: Optional[List[dict]] = None


@app.post("/api/ai/record")
def ai_record(req: AiRecordReq, user: dict = Depends(get_current_user)):
    q=(req.question or "").strip()[:120]; a=(req.answer or "").strip()[:1200]
    if not q or not a: raise HTTPException(status_code=400,detail="问题和答案不能为空")
    conn=get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO private_ai_answers VALUES (?,?,?,?)",(user["id"],q,_plain(a),datetime.now().isoformat()))
        conn.commit()
    finally: conn.close()
    return {"code":0,"stored":True,"scope":"private"}


class MemoryReq(ValidatedModel):
    text: Optional[str] = None
    forget_all: Optional[bool] = False


@app.post("/api/ai/memory")
def ai_memory(req: MemoryReq, user: dict = Depends(get_current_user)):
    """记忆的统一写入口：本机引擎也走这里，保证两边看到同一份记忆。"""
    if req.forget_all:
        n = memory_forget(user["id"], "")
        return {"code": 0, "cleared": n, "memory": memory_list(user["id"])}
    t = (req.text or "").strip()[:120]
    if not t:
        raise HTTPException(status_code=400, detail="要记的内容不能为空")
    saved = memory_put(user["id"], "记住" + t)
    return {"code": 0, "saved": bool(saved), "memory": memory_list(user["id"])}


@app.get("/api/dashboard/cached")
def dashboard_cached(user: dict = Depends(get_current_user)):
    """公开大屏用的缓存版：同一用户 8 秒内重复拉取走 Redis，不打穿到 SQLite。

    大屏是自动轮询的，用户量上来后这是最先压垮数据库的一条路。
    """
    key = "dash:" + str(user["id"])
    hit = cache_get(key)
    if hit:
        try:
            return json.loads(hit)
        except Exception:
            pass
    data = compute_dashboard_data(user)
    payload = {"code": 0, "data": data, "cached": False}
    cache_set(key, json.dumps(payload, ensure_ascii=False).replace("<", chr(92) + "u003c"), 8)
    return payload


# ==================== AI 顾问 v2 ====================
# 顺序固定：本人真实数据 → 长期记忆 → 本机知识库 → 联网检索 → 本机小模型合成。
# 数字类问题永远在前两层解决；模型只负责"照着查到的资料把话说通顺"，
# 它不通气时退化成原文摘录并写明是摘录——绝不让它凭空编。
_LLM_URL = "http://127.0.0.1:8081/v1/chat/completions"
_LLM_TIMEOUT = 25
_LLM_RETRY_AFTER = 60
_llm_block_until = [0.0]
_llm_last_error = [""]      # 最近一次调用失败的原因，界面要能说得出


def llm_ready():
    return time.time() >= _llm_block_until[0]


def llm_chat(prompt, max_tokens=200, temperature=0.2):
    """问本机 llama-server。不通就冷却 60 秒并返回 None（不静默当成没内容）。"""
    if not llm_ready():
        return None
    payload = {"messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": temperature}
    body = json.dumps(payload, ensure_ascii=False).replace("<", chr(92) + "u003c")
    req = urllib.request.Request(_LLM_URL, data=body.encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT) as resp:
            got = json.loads(resp.read().decode("utf-8", "replace"))
        txt = ((got.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        txt = txt.strip()
    except Exception as e:
        txt = ""
        _llm_last_error[0] = "%s: %s" % (type(e).__name__, str(e)[:80])
    if not txt:
        if _llm_block_until[0] <= time.time():
            _llm_block_until[0] = time.time() + _LLM_RETRY_AFTER
        return None
    _llm_last_error[0] = ""
    return txt


_FILLERS = ("请问", "帮我", "告诉我", "麻烦", "我想知道", "是不是真的", "有没有说法")
_TAIL_CUTS = ("怎么办", "怎么补救", "怎么调整", "怎么安排", "如何是好", "怎么吃")
_TIME_WORDS = ("中午", "晚上", "早上", "今晚", "今天", "昨天", "最近", "平时")


# 必应中文从这台服务器上抓下来经常给无关页：实测"平台期体重不掉"返回
# 微信公众平台、"喝黑咖啡"返回网易邮箱和腾讯视频。所以联网结果只能当
# "有对题命中才允许出现的参考"，答案本体一律来自本人流水与内置场景库。
DOMAIN_TERMS = [
    "火锅", "聚餐", "外卖", "点餐", "烧烤", "奶茶", "咖啡", "零食", "夜宵", "加餐",
    "早餐", "午餐", "晚餐", "主食", "米饭", "面条", "馒头", "粗粮", "糙米", "燕麦",
    "鸡蛋", "鸡胸", "牛肉", "鱼虾", "豆腐", "酸奶", "牛奶", "豆浆", "蔬菜", "水果",
    "坚果", "饮料", "玉米", "红薯", "苹果", "香蕉", "西兰花", "冬瓜", "生菜", "代餐",
    "蛋白粉", "无糖", "火锅底料", "蘸料", "可乐", "午睡", "晚饭", "早饭", "三餐",
    "热量", "跑步", "快走", "零食柜", "烧烤摊",
    "奶茶店", "轻食", "沙拉", "三明治", "寿司", "快餐", "食堂", "便当", "夜跑",
    "平台期", "体重", "腰围", "体脂", "基数", "反弹", "节食", "断食", "代谢", "便秘",
    "训练", "力量", "有氧", "拉伸", "睡眠", "生理期", "水肿",
]
_DICT_PAT = re.compile(r"（汉语|汉语词典|汉语国学|怎么读|的意思|的解释|拼音|组词|部首|笔顺|字词|字典")


def _question_terms(q):
    """问题里能确认的领域词。一个都没有就别联网搜——搜回来也不敢用。

    只认两个字以上的词：单字"糖"会让"口香糖"被当成饮食领域词误命中。"""
    return [t for t in DOMAIN_TERMS if len(t) >= 2 and t in q]


def _keep_relevant(items, terms):
    """两道闸：必须命中问题里的领域词；纯字词页（《喝（汉语文字）》）一律丢。"""
    keep = []
    for it in items:
        blob = (it.get("title") or "") + (it.get("snippet") or "")
        if not any(t in blob for t in terms):
            continue
        if _DICT_PAT.search(it.get("title") or ""):
            subject = re.split(r"[（_《\s]", it["title"])[0]
            if subject not in terms:
                continue
        keep.append(it)
    return keep


def _rewrite_query(q):
    """把口语问句压成能搜到东西的词。
    上一版整句去搜"中午吃多了晚上怎么自适应补救"，必应返回的是百度百科条目
    《中午（汉语词语）》。实测原因是必应咬住查询串的第一个词：首位是单字动词
    （喝/黑）就给字典页，所以领域词"减脂"一律打头，而不是问句里有就不加。"""
    s = " " + q + " "
    for f in _FILLERS:
        s = s.replace(f, " ")
    for t in _TAIL_CUTS:
        s = s.replace(t, " ")
    s = s.replace("?", " ").replace("？", " ").replace("。", " ").replace("，", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # 句末语气词留着会让必应更容易咬住句子开头的单字动词
    s = re.sub(r"[吗呢吧啊呀]+$", "", s).strip()
    if len(s) < 4:
        s = q.strip()
    # 实测对比过五种写法：整句中文必应不切词，直接咬开头两个字当词条查字典
    # （"在外聚餐吃火锅"→《在外》，"练完极饿"→《练》）；"减脂+整句"则永远返回
    # 同三篇泛泛减脂科普。只有空格分开的词袋能给对题结果。所以查询串一律由
    # 领域词拼成，领域词打头，末尾再带一个"减脂"限定领域。
    terms = _question_terms(q)
    parts = []
    for t in terms:
        if t not in parts:
            parts.append(t)
    if "减脂" not in parts:
        parts.append("减脂")
    return " ".join(parts)[:70]


def _qkey(q):
    return hashlib.sha256(("v2:"+re.sub(r"\s+"," ",q.strip().lower())).encode("utf-8")).hexdigest()


def kb_lookup(q):
    # Historical entries may contain personal model output. Quarantined until reviewed.
    return None


def kb_store(q, answer, items, how):
    # A generated answer is not a reviewed public knowledge source.
    return {"how":how,"stored":False}


def memory_put(user_id, q):
    """长期记忆只在用户明说「记住…」时写入，不做暗中推断——
    猜错一次的代价会被后面每次回答反复引用。"""
    m = re.search(r"记住(.+)", q)
    if not m:
        return None
    val = m.group(1).strip(" ，。,：:").strip()[:120]
    if not val:
        return None
    key = val[:16]
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO ai_memory (user_id, mem_key, mem_value, updated_at)
    VALUES (?, ?, ?, ?)
    """, (user_id, key, val, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return val


def memory_forget(user_id, q):
    conn = get_db()
    c = conn.cursor()
    n = c.execute("DELETE FROM ai_memory WHERE user_id = ?", (user_id,)).rowcount
    conn.commit()
    conn.close()
    return n


def memory_list(user_id):
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("SELECT mem_value FROM ai_memory WHERE user_id = ? "
                     "ORDER BY updated_at DESC LIMIT 20", (user_id,)).fetchall()
    conn.close()
    return [dict(r)["mem_value"] for r in rows]


def _plain(s):
    """必应摘要里混着 &ensp;/&#0183; 这类实体，而 web_search 出口又转义过一次，
    再转就成 &amp;amp;ensp;。内部一律还原成纯文本、把空白折叠掉，出口只转义一次。"""
    t = s or ""
    for _ in range(3):                       # 收敛式还原：几层转义都能回到原文
        n = html_unescape(t)
        if n == t:
            break
        t = n
    t = _strip_tags(t)
    for ch in (chr(160), chr(8199), chr(8239)):   # nbsp / figure space / narrow nbsp
        t = t.replace(ch, " ")
    return re.sub(r"\s+", " ", t).strip()


def _fmt_snippet(it):
    return "%s：%s" % (_plain(it["title"]), _plain(it["snippet"]))


def _rank_items(items, terms):
    """摘录兜底取的是 items[0]——那条恰好是"能量守恒"就完蛋了。
    按"标题命中领域词 > 摘要命中次数"排过再取，兜底的那一段才是真的最相关。"""
    def score(it):
        title = it.get("title") or ""
        snip = it.get("snippet") or ""
        return (2 if any(t in title for t in terms) else 0) + sum(snip.count(t) for t in terms)
    return sorted(items, key=score, reverse=True)


def synthesize(q, items, mem, terms=None):
    """有模型：照资料组织，禁止补资料里没有的数字。
    没模型：直接把最相关一条的原文摘出来，并标注是摘录。两条路都不给它自由发挥。"""
    if not items:
        return None, "none"
    ranked = _rank_items(items, terms or [])
    ctx = "\n".join("- " + _fmt_snippet(it) for it in ranked[:3])
    if mem:
        ctx += "\n（此人此前明确记下的：" + "；".join(mem[:5]) + "）"
    prompt = ("你在帮一个减脂用户查资料。只准用【资料】里的内容回答，"
              "资料里没有的数字、剂量、结论一律不许出现；"
              "先给一句结论，再补最多两句依据，用中文说完，不复述问题；"
              "不要写\"作为一个\"\"作为AI\"\"建议您\"\"抱歉\"\"无法回答\"这类话，"
              "资料互相矛盾时直说矛盾在哪。"
              "若资料不足以回答，就只回两个字：不够。\n"
              "【资料】\n%s\n【问题】%s\n【回答】" % (ctx, q))
    # 这是"照着资料归纳"，不是创作：温度压到 0.1，模型越自由越容易补出资料里没有的数字
    txt = llm_chat(prompt, temperature=0.1)
    from app_modules.ai_policy import grounded_summary
    if txt and "不够" not in txt[:6] and grounded_summary(txt,ranked):
        clean = html_escape(_plain(txt)[:600])
        return clean, "model"
    best = _plain(ranked[0]["snippet"])[:220]
    # 模型说"不够"和模型根本没跑是两回事，兜底文案必须分开——
    # 把前者写成后者就是把原因赖到一个没发生的事实上
    if txt:
        return html_escape(best), "insufficient" if "不够" in txt[:6] else "filtered"
    return html_escape(best), "extract"


# 版本清单：App 启动时读它决定要不要提醒更新。
# 必须 no-cache——这条要是被缓存住，用户会永远停在旧版还以为自己最新。
# 内容不在代码里写死，由 make_version_json.py 从 build.gradle 与 qingsu.apk 现算生成。
@app.get("/version.json")
def version_json():
    path = os.path.join(WEB_DIR, "version.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="版本清单还没发布")
    with io.open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    return Response(content=raw, media_type="application/json", headers=_no_cache())


# 内置场景库：这些是软件自己该知道的答案，不该拿去问搜索引擎。
# 文字与 app.js 的本地场景层逐条对应，判据核对两边关键词集合一致。




def load_guidance():
    path=os.path.join(WEB_DIR,"guidance.json")
    if not os.path.isfile(path):path=os.path.join(os.path.dirname(__file__),"app","src","main","assets","guidance.json")
    with open(path,encoding="utf-8") as f:rows=json.load(f)
    return [(tuple(row["keywords"]),html_escape(row["text"])) for row in rows]
SCENE_RULES=load_guidance()

def answer_from_scenes(q):
    """命中场景就给成体系的建议；这是答案，不是"参考链接"。

    一条问题可能同时命中多个场景（"生理期便秘"），取命中关键词最长的那条——
    越具体的词越贴近真实意图，按表顺序先到先得会让排在前面的一般场景抢走。"""
    best, best_len = None, 0
    for keys, text in SCENE_RULES:
        # 单字词一律不参与匹配：旧表里的"饿""糖"会让"嚼口香糖"被当成想喝甜的、
        # "饿得快是不是代谢好"被当成练后加餐。要覆盖就用两字以上的具体说法。
        hit = [k for k in keys if len(k) >= 2 and k in q]
        if not hit:
            continue
        longest = max(len(k) for k in hit)
        if longest > best_len:
            best, best_len = text, longest
    return best


@app.post("/api/ask")
def ask(req: AskReq, user: dict = Depends(get_current_user)):
    """AI 顾问总入口。返回 source 说明这条答案是从哪一层来的。"""
    q = (req.question or "").strip()[:120]
    if not q:
        raise HTTPException(status_code=400, detail="问题为空")

    if any(k in q for k in ("忘记所有", "清空记忆", "把记住的删掉")):
        n = memory_forget(user["id"], q)
        return {"code": 0, "source": "memory",
                "answer": html_escape("已清空你记下的 %d 条。" % n), "items": []}
    saved = memory_put(user["id"], q)
    if saved:
        return {"code": 0, "source": "memory",
                "answer": html_escape("记下了：%s。以后回答会带上这条；说「忘记所有」可清空。" % saved),
                "items": []}
    if any(k in q for k in ("你记得我", "我的忌口", "我说过", "记住了什么")):
        mem = memory_list(user["id"])
        if not mem:
            return {"code": 0, "source": "memory",
                    "answer": html_escape("还没有你明确记下的条目。说「记住某件事」我就存下来。"),
                    "items": []}
        return {"code": 0, "source": "memory",
                "answer": html_escape("你记下的：" + "；".join(mem)), "items": []}

    d = compute_dashboard_data(user)
    local = answer_from_user_data(q, d)
    if local:
        return {"code": 0, "source": "data", "answer": local, "items": []}

    scene = answer_from_scenes(q)
    if scene:
        return {"code": 0, "source": "scene", "answer": scene, "items": []}

    if req.route_only:
        return {"code":0,"source":"none","answer":"当前问题需要模型或外部参考","items":[]}

    # 认不出领域词就直接拒，这条判断不碰网络，所以不能算进每分钟配额——
    # 否则连问几个"量子计算是什么"会把真正需要联网的问题挤到限流后面
    if not _question_terms(q):
        return {"code": 0, "source": "none",
                "answer": "这个问题里我没有能确认的减脂相关词，联网搜回来的东西判断不了对不对题，"
                          "所以不拿它凑答案。换个带具体食物或场景的说法再问"
                          "（例：吃火锅怎么点、中午吃多了怎么办），或先看【食谱/外卖】里的内置建议。",
                "items": []}

    if not _ask_allowed(user["id"]):
        return {"code": 0, "source": "limited",
                "answer": f"联网查询太快了（每分钟最多 {_ASK_LIMIT_PER_MIN} 次），先等一会儿再问。",
                "items": []}

    mem = memory_list(user["id"])

    hit = kb_lookup(q)
    if hit:
        try:
            items = json.loads(hit["sources"] or "[]")
        except Exception:
            items = []
        note = html_escape("（这条来自本机知识库，%s 查证过，不是实时结果）" % hit["fetched_at"][:10])
        return {"code": 0, "source": "kb", "answer": hit["answer"] + note,
                "items": [{"title": it.get("title", ""), "url": html_escape(it.get("url", ""), quote=True),
                           "host": html_escape(it.get("host", ""), quote=True)} for it in items]}

    terms = _question_terms(q)
    search_q = _rewrite_query(q)
    try:
        items = web_search(search_q)
    except Exception as e:
        return {"code": 0, "source": "none",
                "answer": f"联网查询没成功（{type(e).__name__}）。我不编答案——"
                          f"你可以换个说法再问，或先看【食谱/外卖】里的内置建议。",
                "items": []}
    kept = _keep_relevant(items, terms)
    if not kept:
        return {"code": 0, "source": "none",
                "answer": "联网搜到的 %d 条结果里没有一条真正讲到「%s」，都是不相干的页面。"
                          "我不拿无关内容凑答案——可以换个说法再问，"
                          "或先看【食谱/外卖】里的内置建议。" % (len(items), "、".join(terms)),
                "items": []}
    items = kept

    answer, how = synthesize(q, items, mem, terms)
    if not answer:
        return {"code": 0, "source": "none", "answer": "查到的资料里没有可用内容。", "items": []}
    kb_store(q, answer, items, how)

    if how == "extract":
        tail = "（本机模型未运行，以下是原文摘录。原因：%s）" % (_llm_last_error[0] or "未知")
    elif how == "insufficient":
        tail = "（本机模型认为这些资料不足以回答，以下是原文摘录）"
    elif how == "filtered":
        tail = "（模型回答未通过资料一致性校验，以下改用原文摘录）"
    else:
        tail = ""
    tail += ("以上内容由第三方网站提供，不是本系统的减脂建议；"             "涉及用药与疾病请咨询医生。")
    src_rows = "".join(
        "<div style='margin:4px 0;padding:5px 8px;background:#F8FAFC;border-radius:8px;'>"
        "<div style='font-weight:700;'>{}</div>"
        "<div style='font-size:10px;color:#94A3B8;margin-top:2px;'>{} · 搜索词已改写</div></div>".format(
            it["title"], it["host"])
        for it in items[:3])
    # source 必须与答案的来历一致：只有模型真合成过才叫 web_model，
    # 摘录兜底（不管是模型没跑还是模型说资料不够）一律叫 web
    return {"code": 0, "source": "web_model" if how == "model" else "web",
            "answer": answer + html_escape(tail) + "<br>" + src_rows,
            "items": [{"title": it["title"], "url": it["url"], "host": it["host"]} for it in items]}
# ==================== 100% REAL Chart Data API ====================

def _deficit_rows(c, user_id: int, metrics: dict, days: int) -> list:
    start=(date.today()-timedelta(days=days-1)).isoformat()
    food={r["log_date"]:dict(r) for r in c.execute("SELECT log_date,SUM(cal) AS total,COUNT(*) AS n FROM food_logs WHERE user_id=? AND log_date>=? GROUP BY log_date",(user_id,start))}
    workout={r["log_date"]:dict(r) for r in c.execute("SELECT log_date,SUM(cal_burned) AS total,COUNT(*) AS n FROM workout_logs WHERE user_id=? AND log_date>=? GROUP BY log_date",(user_id,start))}
    saved={r["log_date"]:dict(r) for r in c.execute("SELECT * FROM daily_metrics WHERE user_id=? AND log_date>=?",(user_id,start))}
    completed={r["log_date"] for r in c.execute("SELECT log_date FROM daily_reviews WHERE user_id=? AND complete=1 AND log_date>=?",(user_id,start))}
    other_days={r[0] for r in c.execute("SELECT log_date FROM weight_logs WHERE user_id=? AND log_date>=? UNION SELECT log_date FROM water_logs WHERE user_id=? AND log_date>=?",(user_id,start,user_id,start))}
    rows=[]
    for i in range(days-1,-1,-1):
        d=date.today()-timedelta(days=i); ds=d.isoformat()
        consumed=(food.get(ds) or {}).get("total",0); burned=(workout.get(ds) or {}).get("total",0)
        nutrition=ds in food or ds in workout
        has=nutrition or ds in other_days or ds in completed
        historical=json.loads(saved[ds]["metrics_json"]) if ds in saved else metrics
        rows.append({"day":"今天" if i==0 else ["周一","周二","周三","周四","周五","周六","周日"][d.weekday()],"date":ds,"deficit":round(historical["tdee"]+burned-consumed) if nutrition or ds in completed else 0,"consumed":consumed,"burned":burned,"has_records":has,"record_status":"complete" if ds in completed else ("partial" if has else "missing"),"estimate_origin":saved[ds]["origin"] if ds in saved else "current_recalculation"})
    return rows


@app.get("/api/habits")
def get_habits(user: dict = Depends(get_current_user)):
    """30 天自律矩阵：前端画 30 格，后端就必须真给 30 天，不能只给 7 天让剩下 23 格永远灰。"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
    p = dict(c.fetchone() or {})
    rows = _deficit_rows(c, user["id"], compute_metrics(p), 30)
    conn.close()
    return {"days": rows, "window": 30}


def compute_charts_data(user: dict) -> dict:
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
    p = dict(c.fetchone() or {})
    metrics = compute_metrics(p)

    # 1. Real Weight History (ONLY actual points logged by user)
    c.execute("""
    SELECT log_date, weight_jin FROM weight_logs
    WHERE user_id = ?
    ORDER BY log_date ASC, id DESC
    """, (user["id"],))
    wt_rows = c.fetchall()
    weight_data = []
    seen_dates = set()
    for row in wt_rows:
        d = row["log_date"]
        if d not in seen_dates:
            seen_dates.add(d)
            # format MM-DD
            label = d[5:] if len(d) >= 10 else d
            weight_data.append({"full_date": d, "date": label, "val": round(row["weight_jin"] / 2.0, 1), "jin": row["weight_jin"]})

    # If user has no weight logs yet, fall back to profile baseline
    if not weight_data:
        today_label = date.today().strftime("%m-%d")
        weight_data.append({"date": today_label, "val": round(p.get("weight_jin", 140.0) / 2.0, 1), "jin": p.get("weight_jin", 140.0)})

    # 2. Real Deficit History (Past 7 Days actual data)
    deficit_data = _deficit_rows(c, user["id"], metrics, 7)

    # 3. Real Macros breakdown today
    today = date.today().isoformat()
    c.execute("SELECT SUM(protein_g) as p, SUM(carbs_g) as c, SUM(fat_g) as f, SUM(cal) as total FROM food_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    m_row = c.fetchone()
    unknown_macros=c.execute("SELECT COUNT(*) FROM food_logs WHERE user_id=? AND log_date=? AND COALESCE(source,'') <> 'nutrition_kb'",(user["id"],today)).fetchone()[0]
    total_cal = m_row["total"] or 0
    real_p = round(m_row["p"] or 0, 1)
    real_c = round(m_row["c"] or 0, 1)
    real_f = round(m_row["f"] or 0, 1)

    conn.close()

    return {
        "weight_history": weight_data,
        "deficit_history": deficit_data,
        "macros_today": {
            "total_cal": total_cal,
            "unknown_records": unknown_macros,
            "protein_g": real_p,
            "carbs_g": real_c,
            "fat_g": real_f,
            "target_protein_g": metrics["protein_g"],
            "target_carbs_g": metrics["carbs_g"],
            "target_fat_g": metrics["fat_g"]
        },
        "target_deficit": metrics["deficit"]
    }

@app.get("/api/charts")
def get_charts(user: dict = Depends(get_current_user)):
    return compute_charts_data(user)

@app.get("/api/public/charts")
def get_public_charts(username: str, k: Optional[str] = None, request: Request = None):
    if not _public_allowed(_ip(request)):
        raise HTTPException(status_code=429, detail="访问过于频繁")
    conn = get_db()
    user = check_share(conn, username, k)
    settings=share_settings(conn,user['id']) if user else None
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="链接不完整或已失效")
    result=compute_charts_data(user)
    if not settings['scope'].get('weight'):result['weight_history']=[]
    if not settings['scope'].get('meals'):
        result['deficit_history']=[];result['macros_today']={}
    if not settings['scope'].get('workout') or not settings['scope'].get('profile'):result['deficit_history']=[]
    if not settings['scope'].get('profile'):
        result.pop('target_deficit',None)
        result['macros_today']={k:v for k,v in result.get('macros_today',{}).items() if not k.startswith('target_')}
    return result

# ==================== Public Web Dashboard & Static Delivery ====================

@app.get("/style.css")
def get_style(v: str = None):
    path = os.path.join(WEB_DIR, "style.css")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/css", headers=_asset_headers(path, v))
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/app.js")
def get_app_js(v: str = None):
    path = os.path.join(WEB_DIR, "app.js")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/javascript", headers=_asset_headers(path, v))
    raise HTTPException(status_code=404, detail="app.js not found")

# 动作关键帧表：App 从 assets 直读，网页版必须也能取到，
# 否则网页永远只能用程序化回落，而界面看不出来差别（这条就是踩过 404 才发现的）
@app.get("/exercise_poses.json")
def get_exercise_poses(v: str = None):
    path = os.path.join(WEB_DIR, "exercise_poses.json")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/json", headers=_asset_headers(path, v))
    raise HTTPException(status_code=404, detail="动作姿态表未部署")


@app.get("/qingsu.apk")
def download_apk(v: str = None):
    apk_path = os.path.join(WEB_DIR, "qingsu.apk")
    if os.path.exists(apk_path):
        return FileResponse(apk_path, media_type="application/vnd.android.package-archive",
                             filename="轻塑减脂塑形_v5.0.apk", headers=_asset_headers(apk_path, v))
    raise HTTPException(status_code=404, detail="APK not found")

@app.get("/qr.svg")
def get_qr_svg(v: str = None):
    path = os.path.join(WEB_DIR, "qr.svg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/svg+xml", headers=_asset_headers(path, v))
    raise HTTPException(status_code=404, detail="qr.svg not found")

@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    content = render_index_html()
    if content is not None:
        return HTMLResponse(content, media_type="text/html", headers=_no_cache())
    return HTMLResponse("<h3>轻塑系统正在启动中...</h3>")

@app.get("/u/{username}", response_class=HTMLResponse)
def public_user_dashboard(username: str, k: Optional[str] = None, request: Request = None):
    if not _public_allowed(_ip(request)):
        return HTMLResponse(_SHARE_LOST_HTML, status_code=429)
    conn = get_db()
    user = check_share(conn, username, k)
    conn.close()
    if not user:
        # 用户名不存在与密钥不对返回同一页：既不泄露谁注册过，也不会对已注册用户
        # 谎称"暂未注册"（旧版这里会把 @用户名 原样印在页面上）
        return HTMLResponse(_SHARE_LOST_HTML, status_code=404)

    # Return the unified real web app with automatic target user binding & base path
    content = render_index_html()
    if content is not None:
        # json.dumps 出合法 JS 字符串，再把 < 转义掉，防用户名里的 </script> 提前闭合标签
        safe_js_name = json.dumps(username).replace("<", "\\u003c")
        base_path=urllib.parse.urlsplit(SITE_BASE).path.rstrip('/')+'/'
        injected = f"<base href=\"{html_escape(base_path,quote=True)}\">\n<script>window.__PUBLIC_USER__ = {safe_js_name};</script>\n"
        content = content.replace("<head>", "<head>\n" + injected)
        return HTMLResponse(content, headers=_no_cache())
    return HTMLResponse("<h3>轻塑系统正在启动中...</h3>")


@app.post("/api/logout")
def logout(user: dict = Depends(get_current_user)):
    conn=get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash=?",(user["_session_hash"],));conn.commit()
    finally: conn.close()
    return {"code":0}

def media_key():
    path=os.path.join(DB_DIR,"media-signing.key")
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as f: f.write(secrets.token_bytes(32))
    except FileExistsError: pass
    with open(path,"rb") as f: return f.read()

def signed_photo(url,share_user=None):
    name=os.path.basename(url.split("?",1)[0]); expiry=int(time.time())+900
    payload=f"{name}:{expiry}";audience=''
    if share_user:
        payload+=f":{share_user['id']}:{share_user['share_secret']}";audience=f"&audience={share_user['id']}"
    sig=hmac.new(media_key(),payload.encode(),hashlib.sha256).hexdigest()
    return f"/uploads/{name}?expires={expiry}&signature={sig}{audience}"

@app.get("/uploads/{name}")
def private_photo(name: str, expires: int=0, signature: str="",audience:int=0):
    payload=f"{name}:{expires}"
    if audience:
        c=get_db()
        try:
            user=c.execute('SELECT * FROM users WHERE id=?',(audience,)).fetchone()
            settings=share_settings(c,audience)
            owned=c.execute('SELECT 1 FROM body_cycles WHERE user_id=? AND photo_url=?',(audience,'/uploads/'+name)).fetchone()
        finally:c.close()
        if not user or not owned or not settings['enabled'] or not settings['scope'].get('photos') or (settings['expires_at'] and settings['expires_at']<time.time()):
            raise HTTPException(404,'照片授权已失效')
        payload+=f":{audience}:{user['share_secret']}"
    expected=hmac.new(media_key(),payload.encode(),hashlib.sha256).hexdigest()
    if expires<int(time.time()) or expires>time.time()+901 or not secrets.compare_digest(signature,expected):
        raise HTTPException(status_code=404,detail="照片不存在或授权已失效")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)",name,re.I):
        raise HTTPException(status_code=404,detail="照片不存在")
    path=os.path.join(UPLOAD_DIR,name)
    if not os.path.isfile(path):raise HTTPException(status_code=404,detail="照片不存在")
    return FileResponse(path,headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})

@app.post('/api/photo/delete')
def delete_latest_photo(user:dict=Depends(get_current_user)):
    c=get_db();url=''
    try:
        row=c.execute("SELECT photo_url FROM body_cycles WHERE user_id=? AND photo_url<>'' ORDER BY cycle_num DESC LIMIT 1",(user['id'],)).fetchone()
        if row:
            url=row['photo_url'];c.execute("UPDATE body_cycles SET photo_url='' WHERE user_id=? AND photo_url=?",(user['id'],url))
        c.commit()
    finally:c.close()
    name=os.path.basename(url)
    if re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)',name,re.I):
        try:os.unlink(os.path.join(UPLOAD_DIR,name))
        except FileNotFoundError:pass
    return {'code':0,'msg':'当前照片已删除；加密备份中的历史副本按保留期轮换'}
def release_identity():
    """上报"现在跑的是哪一版"，取自部署脚本落盘的 release.json。

    以前这里直接 return "r131"，而部署脚本又拿同一个死字去比对——两边都硬编码，
    发错版本也照样"就绪"，等于没有门禁。
    """
    for candidate in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "release.json"),
                      "/opt/qingsu/release.json"):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"release": str(data.get("release", "unknown")),
                    "source_revision": str(data.get("source_revision", "unknown"))}
        except Exception:
            continue
    return {"release": "unknown", "source_revision": "unknown"}

@app.get("/health/live")
def liveness():
    return {"status":"ok"}

@app.get("/health")
@app.get("/health/ready")
def health():
    conn=get_db()
    try: conn.execute("SELECT 1").fetchone()
    finally: conn.close()
    info = release_identity()
    info["status"] = "ok"
    return info


class RecordChangeReq(ValidatedModel):
    food_name: Optional[str]=None
    slot: Optional[str]=None
    cal: Optional[int]=None
    weight_jin: Optional[float]=None
    waist_cm: Optional[float]=None
    duration_minutes: Optional[int]=None
    cal_burned: Optional[float]=None
    plan_name: Optional[str]=None

def change_record(kind, record_id, req, user, deleting=False):
    tables={"food":"food_logs","weight":"weight_logs","workout":"workout_logs"}
    fields={"food":("food_name","slot","cal"),"weight":("weight_jin","waist_cm"),"workout":("duration_minutes","cal_burned","plan_name")}
    if kind not in tables:raise HTTPException(status_code=400,detail="记录类型无效")
    conn=get_db()
    try:
        table=tables[kind]
        row=conn.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?",(record_id,user["id"])).fetchone()
        if not row:raise HTTPException(status_code=404,detail="记录不存在")
        snapshot_metrics(conn,user["id"])
        conn.execute("INSERT INTO record_changes(user_id,kind,record_id,previous_json,operation,created_at) VALUES (?,?,?,?,?,?)",(user["id"],kind,record_id,json.dumps(dict(row),ensure_ascii=False),"delete" if deleting else "update",datetime.now().isoformat()))
        if deleting:conn.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?",(record_id,user["id"]))
        else:
            updates={k:getattr(req,k) for k in fields[kind] if getattr(req,k) is not None}
            if not updates:raise HTTPException(status_code=400,detail="没有要修改的字段")
            if kind=="food" and ("cal" in updates or "food_name" in updates):
                if "cal" not in updates:
                    parsed=parse_food_nutrition(updates["food_name"]);updates.update(cal=parsed["cal"],protein_g=parsed["protein_g"],carbs_g=parsed["carbs_g"],fat_g=parsed["fat_g"],source=parsed["source"],estimate_reason=parsed.get("reason",""))
                else:updates.update(protein_g=0,carbs_g=0,fat_g=0,source="manual",estimate_reason="手动修正热量，宏量未知")
            conn.execute(f"UPDATE {table} SET "+",".join(k+"=?" for k in updates)+" WHERE id=? AND user_id=?",(*updates.values(),record_id,user["id"]))
        if kind=="weight":
            latest=conn.execute("SELECT weight_jin FROM weight_logs WHERE user_id=? ORDER BY log_date DESC,id DESC LIMIT 1",(user["id"],)).fetchone()
            if latest:conn.execute("UPDATE profiles SET weight_jin=? WHERE user_id=?",(latest[0],user["id"]))
        conn.execute("DELETE FROM daily_reviews WHERE user_id=? AND log_date=?",(user["id"],row["log_date"]))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
    return {"code":0,"msg":"记录已删除" if deleting else "记录已更新"}

@app.post("/api/records/{kind}/{record_id}/update")
def update_record(kind:str,record_id:int,req:RecordChangeReq,user:dict=Depends(get_current_user)):
    return change_record(kind,record_id,req,user)

@app.post("/api/records/{kind}/{record_id}/delete")
def delete_record(kind:str,record_id:int,user:dict=Depends(get_current_user)):
    return change_record(kind,record_id,None,user,True)

from app_modules.features import install as install_features
install_features(app,globals())


def extension_asset(name):
    def serve(v: str = None):
        path=os.path.join(WEB_DIR,name)
        if name == "sw.js":
            headers={"Cache-Control":"no-store","Service-Worker-Allowed":"/"}
        else:headers=_asset_headers(path, v)
        if not os.path.isfile(path):raise HTTPException(404,"资源未部署")
        media={"js":"application/javascript","css":"text/css","svg":"image/svg+xml","webmanifest":"application/manifest+json","json":"application/json"}[name.rsplit(".",1)[-1]]
        return FileResponse(path,media_type=media,headers=headers)
    return serve

# 3D 依赖与模型：体积大且按版本发布，同样走内容哈希强缓存。
# 路径必须限定在 vendor/ 与 models/ 白名单里，绝不能变成任意文件读取。
_STATIC_SUBDIRS = {
    "vendor": {"three.module.js", "GLTFLoader.js", "BufferGeometryUtils.js"},
    "models": {"cesium_man.glb", "CREDITS.md"},
}
_SUBDIR_MEDIA = {
    ".js": "application/javascript",
    ".glb": "model/gltf-binary",
    ".md": "text/markdown; charset=utf-8",
}

def static_subdir(folder, name):
    allowed = _STATIC_SUBDIRS.get(folder)
    if not allowed or name not in allowed:
        raise HTTPException(status_code=404, detail="资源未部署")
    path = os.path.join(WEB_DIR, folder, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="资源未部署")
    ext = name[name.rfind("."):].lower()
    return FileResponse(path, media_type=_SUBDIR_MEDIA.get(ext, "application/octet-stream"),
                        headers=_asset_headers(path, None))

@app.get("/vendor/{name}")
def get_vendor(name: str):
    return static_subdir("vendor", name)

@app.get("/models/{name}")
def get_models(name: str):
    return static_subdir("models", name)

for asset in ("features.js","features.css","sw.js","manifest.webmanifest","app-icon.svg","guidance.json","body3d.js"):
    app.get("/"+asset)(extension_asset(asset))
