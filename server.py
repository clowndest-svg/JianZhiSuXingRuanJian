import os
import sqlite3
import hashlib
import json
from html import escape as html_escape
import time
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

DB_DIR = "/opt/qingsu/data"
UPLOAD_DIR = "/opt/qingsu/uploads"
WEB_DIR = "/opt/qingsu/web"
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WEB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "qingsu.db")

app = FastAPI(title="轻塑·减脂塑形严管伴侣 API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
        age INTEGER DEFAULT 26,
        height REAL DEFAULT 165.0,
        weight_jin REAL DEFAULT 140.0,
        target_weight_jin REAL DEFAULT 120.0,
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
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")



def _asset_ver(path):
    """拿文件修改时间当版本号：重新部署一次就换一个串，
    让已经被缓存住的浏览器不得不去取新 URL。"""
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


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
        ('href="/qingsu.apk"', 'href="/qingsu.apk?v=%s"', "qingsu.apk"),
    ]
    for old, fmt, name in pairs:
        content = content.replace(old, fmt % _asset_ver(os.path.join(WEB_DIR, name)))
    return content


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.replace("Bearer ", "").strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE token = ?", (token,))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return dict(user)

# Models
class RegisterReq(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None
    gender: Optional[str] = "female"
    age: Optional[int] = 26
    height: Optional[float] = 165.0
    weight_jin: Optional[float] = 140.0
    target_weight_jin: Optional[float] = 120.0
    goal_type: Optional[str] = "tone"
    dining_mode: Optional[str] = "takeout"

class LoginReq(BaseModel):
    username: str
    password: str

class ProfileUpdateReq(BaseModel):
    gender: Optional[str] = None
    age: Optional[int] = None
    height: Optional[float] = None
    weight_jin: Optional[float] = None
    target_weight_jin: Optional[float] = None
    goal_type: Optional[str] = None
    dining_mode: Optional[str] = None
    scene: Optional[str] = None

class FoodLogReq(BaseModel):
    slot: str
    food_name: str
    cal: Optional[int] = None

class WeightLogReq(BaseModel):
    weight_jin: float
    waist_cm: Optional[float] = None

class WorkoutLogReq(BaseModel):
    duration_minutes: int = 20
    cal_burned: float = 220.0
    plan_name: str = "塑形训练"

class WaterLogReq(BaseModel):
    cups_count: int

class TakeoutEventReq(BaseModel):
    event_type: str
    cal_avoided: Optional[float] = 0
    dish_name: Optional[str] = None

class AskReq(BaseModel):
    question: str

# Helpers
def compute_metrics(p):
    wt_kg = p["weight_jin"] / 2.0
    ht_cm = p["height"]
    age = p["age"]
    gender = p.get("gender", "female")

    if gender == "male":
        bmr = 10 * wt_kg + 6.25 * ht_cm - 5 * age + 5
    else:
        bmr = 10 * wt_kg + 6.25 * ht_cm - 5 * age - 161
    bmr = round(bmr)
    tdee = round(bmr * 1.35)

    gt = p.get("goal_type", "female_hourglass")
    if gt in ["male_v_taper", "tone", "female_hourglass"]:
        deficit = 420
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.35, 0.40, 0.25
    elif gt in ["male_lean", "loss", "female_lean"]:
        deficit = 500
        target = max(1200, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.45, 0.25
    elif gt in ["male_muscular", "muscle", "female_athletic"]:
        deficit = -250  # 盈余促肌肥大
        target = tdee + 250
        protein_ratio, carbs_ratio, fat_ratio = 0.35, 0.45, 0.20
    elif gt in ["male_steady", "tight", "female_steady"]:
        deficit = 550  # 大基数/啤酒肚稳健减脂
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.45, 0.25
    else:
        deficit = 420
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.40, 0.30

    rest_cal = target - 50
    workout_cal = target + 120

    return {
        "bmr": bmr,
        "tdee": tdee,
        "target_cal": target,
        "rest_cal": rest_cal,
        "workout_cal": workout_cal,
        "deficit": deficit,
        "protein_g": round(target * protein_ratio / 4),
        "carbs_g": round(target * carbs_ratio / 4),
        "fat_g": round(target * fat_ratio / 9)
    }

# ==================== Auth Endpoints ====================

@app.post("/api/register")
def register(req: RegisterReq):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (req.username.strip(),))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="该用户名已存在，请直接登录或换一个用户名")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    token = hashlib.sha256(f"{req.username}_{time.time()}_{os.urandom(8)}".encode()).hexdigest()
    pw_hash = hash_pw(req.password)
    nickname = req.nickname or req.username

    c.execute(
        "INSERT INTO users (username, password_hash, nickname, token, created_at) VALUES (?, ?, ?, ?, ?)",
        (req.username.strip(), pw_hash, nickname, token, now)
    )
    user_id = c.lastrowid

    # Create profile
    c.execute("""
    INSERT INTO profiles (user_id, gender, age, height, weight_jin, target_weight_jin, goal_type, dining_mode, scene, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'home', ?)
    """, (user_id, req.gender, req.age, req.height, req.weight_jin, req.target_weight_jin, req.goal_type, req.dining_mode, now))

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

    conn.commit()
    conn.close()

    return {
        "code": 0,
        "msg": "注册成功！已为您建立专属真数据档案！",
        "token": token,
        "username": req.username,
        "nickname": nickname,
        "public_url": f"http://124.220.54.64/u/{req.username}"
    }

@app.post("/api/login")
def login(req: LoginReq):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (req.username.strip(),))
    user = c.fetchone()
    if not user or user["password_hash"] != hash_pw(req.password):
        conn.close()
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    token = hashlib.sha256(f"{req.username}_{time.time()}_{os.urandom(8)}".encode()).hexdigest()
    c.execute("UPDATE users SET token = ? WHERE id = ?", (token, user["id"]))
    conn.commit()
    conn.close()

    return {
        "code": 0,
        "msg": "登录成功！",
        "token": token,
        "username": user["username"],
        "nickname": user["nickname"],
        "public_url": f"http://124.220.54.64/u/{user['username']}"
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
        "public_url": f"http://124.220.54.64/u/{user['username']}"
    }

@app.post("/api/profile/update")
def update_profile(req: ProfileUpdateReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],))
    cur = dict(c.fetchone() or {})

    gender = req.gender if req.gender is not None else cur.get("gender", "female")
    age = req.age if req.age is not None else cur.get("age", 26)
    height = req.height if req.height is not None else cur.get("height", 165.0)
    weight_jin = req.weight_jin if req.weight_jin is not None else cur.get("weight_jin", 140.0)
    target_weight_jin = req.target_weight_jin if req.target_weight_jin is not None else cur.get("target_weight_jin", 120.0)
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
    conn.close()

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
    c.execute("SELECT * FROM weight_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user["id"],))
    latest_wt = c.fetchone()
    c.execute("SELECT weight_jin FROM weight_logs WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user["id"],))
    first_wt = c.fetchone()
    q_start = first_wt["weight_jin"] if first_wt else None
    current_weight = latest_wt["weight_jin"] if latest_wt else p.get("weight_jin", 140.0)

    # Calculate real remaining calorie budget
    target_cal = metrics["target_cal"]
    remaining_cal = round(target_cal - today_consumed + today_burned)

    # Takeout lock status
    takeout_locked = remaining_cal <= 0
    takeout_warning = ""
    if takeout_locked:
        takeout_warning = f"🚨 今日热量已超标 {abs(remaining_cal)} kcal！外卖点单已被严格限制！请饮用温开水或冬瓜汤消水肿！"

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
    for _ in range(7):
        ds = cur_d.isoformat()
        c.execute("SELECT id FROM workout_logs WHERE user_id = ? AND log_date = ?", (user["id"], ds))
        if not c.fetchone():
            consecutive_slacking += 1
            cur_d -= timedelta(days=1)
        else:
            break

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

    # Latest cycle report
    c.execute("SELECT * FROM body_cycles WHERE user_id = ? ORDER BY cycle_num DESC LIMIT 1", (user["id"],))
    latest_cycle = c.fetchone()

    conn.close()

    return {
        "today_date": today,
        "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"]},
        "metrics": metrics,
        "profile": p,
        "today_consumed": today_consumed,
        "today_burned": today_burned,
        "today_macros": {"protein": today_p, "carbs": today_c, "fat": today_f},
        "remaining_cal": remaining_cal,
        "water_cups": water_cups,
        "water_ml": water_cups * 250,
        "current_weight_jin": current_weight,
        "today_meals": today_meals,
        "takeout_locked": takeout_locked,
        "takeout_warning": takeout_warning,
        "consecutive_over_days": consecutive_over,
        "consecutive_slacking_days": consecutive_slacking,
        "latest_cycle": dict(latest_cycle) if latest_cycle else None,
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
        "public_url": f"http://124.220.54.64/u/{user['username']}"
    }

@app.get("/api/dashboard")
def get_dashboard(user: dict = Depends(get_current_user)):
    return compute_dashboard_data(user)

@app.get("/api/public/dashboard")
def get_public_dashboard(username: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail=f"未找到用户 @{username}")
    return compute_dashboard_data(dict(user))

# ==================== Real Food Logging ====================

@app.post("/api/food/log")
def log_food(req: FoodLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Smart calorie & macro calculation based on food keywords
    name = req.food_name.strip()
    est_cal = req.cal
    if not est_cal:
        est_cal = 350
        if any(k in name for k in ["米饭", "面条", "包子", "饺子", "馒头", "粉", "面包"]): est_cal += 180
        if any(k in name for k in ["牛肉", "羊肉", "猪肉", "排骨", "肉片"]): est_cal += 160
        if any(k in name for k in ["鸡胸", "大虾", "鱼柳", "鸡蛋", "豆腐", "蛋白"]): est_cal += 100
        if any(k in name for k in ["炸", "烤", "红油", "麻酱", "猪脚", "奶茶", "全糖"]): est_cal += 360
        if any(k in name for k in ["生菜", "黄瓜", "番茄", "西兰花", "冬瓜", "青菜"]): est_cal -= 60
        est_cal = max(100, est_cal)

    protein_g = round(est_cal * 0.25 / 4, 1)
    carbs_g = round(est_cal * 0.45 / 4, 1)
    fat_g = round(est_cal * 0.30 / 9, 1)

    c.execute("""
    INSERT INTO food_logs (user_id, log_date, slot, food_name, cal, protein_g, carbs_g, fat_g, time_str, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user["id"], today, req.slot, name, est_cal, protein_g, carbs_g, fat_g, now_time, created_at))

    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"已成功记入【{req.slot}】：{name} ({est_cal} kcal)", "cal": est_cal}

# ==================== Real Weight Logging ====================

@app.post("/api/weight/log")
def log_weight(req: WeightLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    waist = req.waist_cm or 0

    c.execute("""
    INSERT INTO weight_logs (user_id, log_date, weight_jin, waist_cm, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (user["id"], today, req.weight_jin, waist, now))

    c.execute("UPDATE profiles SET weight_jin = ?, updated_at = ? WHERE user_id = ?",
              (req.weight_jin, now, user["id"]))

    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"打卡成功！今日真实空腹体重：{req.weight_jin} 斤！"}

# ==================== Real Workout Logging ====================

@app.post("/api/workout/complete")
def log_workout(req: WorkoutLogReq, user: dict = Depends(get_current_user)):
    conn = get_db()
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
    INSERT INTO workout_logs (user_id, log_date, duration_minutes, cal_burned, plan_name, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user["id"], today, req.duration_minutes, req.cal_burned, req.plan_name, now))

    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"🏆 今日训练打卡成功！真实消耗 -{req.cal_burned} kcal 已计入！"}

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

    conn.commit()
    conn.close()

    return {"code": 0, "msg": f"饮水打卡：今日已喝水 {req.cups_count * 250} ml！"}

# ==================== Real Body Cycle & Photo Upgrade ====================

@app.post("/api/cycle/upgrade")
async def upgrade_cycle(
    weight_jin: float = Form(...),
    waist_cm: float = Form(...),
    photo: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user)
):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get latest cycle num
    c.execute("SELECT * FROM body_cycles WHERE user_id = ? ORDER BY cycle_num DESC LIMIT 1", (user["id"],))
    last_cycle = c.fetchone()
    new_cycle_num = (last_cycle["cycle_num"] if last_cycle else 0) + 1

    photo_url = ""
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1] or ".jpg"
        fname = f"user_{user['id']}_cycle_{new_cycle_num}_{int(time.time())}{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        contents = await photo.read()
        with open(fpath, "wb") as f:
            f.write(contents)
        photo_url = f"/uploads/{fname}"
    elif last_cycle and last_cycle["photo_url"]:
        photo_url = last_cycle["photo_url"]

    # Compute deltas —— 基准缺失就不能算差值
    base_w = last_cycle["weight_jin"] if last_cycle else weight_jin
    raw_base_waist = last_cycle["waist_cm"] if last_cycle else waist_cm
    w_diff = round(weight_jin - base_w, 1)
    # 上一周期腰围为 0（注册时留空）或本次未填，就没有可比基准，不得输出"缩减/增加 X cm"
    has_waist_base = bool(raw_base_waist) and bool(waist_cm)
    waist_diff = round(waist_cm - raw_base_waist, 1) if has_waist_base else None

    cycle_name = f"第 {new_cycle_num} 周期 · 进阶塑形期 (第{(new_cycle_num-1)*7+1}-{new_cycle_num*7}天)"
    if waist_diff is None:
        tone_score = "待补围度 (无基准)"
        waist_line = "• 肚脐腰围：本次或与上次缺一个测量值，<strong>围度变化暂不计算</strong>。<br>"
    else:
        tone_score = "极佳 (94分)" if waist_diff <= 0 else "稳健 (88分)"
        waist_color = "#047857" if waist_diff <= 0 else "#B91C1C"
        waist_line = f"• 肚脐腰围变化：<strong style='color: {waist_color};'>{waist_diff:+.1f} cm</strong>。<br>"

    # 照片只是原样存档，服务端从未读过它的像素，报告里不能声称做过"视觉诊断"
    photo_line = ("• 身材照已存档，可在本页与上一周期照片自行对照（系统未对照片做任何自动分析）。<br>"
                  if photo_url else "• 本次未上传照片。<br>")
    ai_report = f"""
    <strong>🎉 第 {new_cycle_num-1} 周期数据检视：</strong><br>
    • 体重变化：<strong>{w_diff:+.1f} 斤</strong>（空腹体重，来自两次打卡记录）。<br>
    {waist_line}
    {photo_line}<br>
    🚀 <strong>第 {new_cycle_num} 周期安排（提交后自动生效）：</strong><br>
    1. <strong>训练动作：</strong>当前身形对应的 4 个动作保持不变，建议每组再增 3-5 次力竭收缩；<br>
    2. <strong>饮食调配：</strong>每日热量目标仍按身高体重年龄实时计算，下午加餐可增加约 10g 蛋白质；<br>
    3. <strong>说明：</strong>动作库与食谱方案不会因提交本表而自动改写，需要换身形请在【档案】里选。
    """

    c.execute("""
    INSERT INTO body_cycles (user_id, cycle_num, cycle_name, photo_url, weight_jin, waist_cm, tone_score, ai_report, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user["id"], new_cycle_num, cycle_name, photo_url, weight_jin, waist_cm, tone_score, ai_report, now))

    # Also log into weight logs
    today = date.today().isoformat()
    c.execute("INSERT INTO weight_logs (user_id, log_date, weight_jin, waist_cm, created_at) VALUES (?, ?, ?, ?, ?)",
              (user["id"], today, weight_jin, waist_cm, now))
    c.execute("UPDATE profiles SET weight_jin = ?, updated_at = ? WHERE user_id = ?",
              (weight_jin, now, user["id"]))

    conn.commit()
    conn.close()

    return {
        "code": 0,
        "msg": f"🎉 恭喜！周期身材照已记录，全新进阶规划已生效！",
        "cycle_num": new_cycle_num,
        "photo_url": photo_url,
        "ai_report": ai_report
    }


# ==================== 外卖门禁事件与顾问问答 ====================

@app.post("/api/takeout/event")
def log_takeout_event(req: TakeoutEventReq, user: dict = Depends(get_current_user)):
    """门禁真的拦下、用户真的退单或采纳平替时上报一条。

    只接受这四种事件类型；热量差额由客户端按审核库里的真实数值给出，
    没有热量依据的（比如单纯被门禁拦下）记 0，绝不替用户编一个"省了多少"。"""
    et = (req.event_type or "").strip()
    if et not in ("blocked", "cancelled", "substitute", "launched"):
        raise HTTPException(status_code=400, detail="未知的事件类型")
    cal = req.cal_avoided or 0
    if et == "blocked":
        cal = 0
    cal = round(max(0.0, float(cal)), 1)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO takeout_events (user_id, event_type, cal_avoided, dish_name, log_date, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              (user["id"], et, cal, (req.dish_name or "")[:60], date.today().isoformat(),
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return {"code": 0, "msg": "已记录"}


_ASK_LIMIT_PER_MIN = 12
_ask_hits = defaultdict(list)


def _ask_allowed(user_id):
    """给联网出口加每用户限频，免得这个接口变成开放的免费代理被人刷。"""
    now = time.time()
    bucket = _ask_hits[user_id]
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= _ASK_LIMIT_PER_MIN:
        return False
    bucket.append(now)
    return True


def _strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def web_search(query, limit=4):
    """抓必应国内版的自然结果，返回带来源的条目；抓不到就返回空列表。"""
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&setmkt=zh-CN"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", "replace")
    items = re.findall(
        r'<li class="b_algo".*?<h2>.*?<a[^>]*href="([^"]+)".*?>(.*?)</a>.*?<p[^>]*>(.*?)</p>',
        html, re.S)
    out = []
    for href, title, snip in items:
        # 先去标签、再转义；先截断再转义，免得把 &amp; 这类实体截成半截
        title = html_escape(_strip_tags(title))
        href = (href or "").strip()
        if not title or not href.startswith("http"):
            continue
        out.append({
            "title": title,
            "snippet": html_escape(_strip_tags(snip)[:180]),
            "url": html_escape(href, quote=True),
            "host": urllib.parse.urlparse(href).netloc,
        })
        if len(out) >= limit:
            break
    return out


def answer_from_user_data(q, d):
    """能用自己的真实流水回答的问题，优先在这里答，一句都不编。"""
    m = d["metrics"]
    consumed = d["today_consumed"]
    burned = d["today_burned"]
    net = round(m["tdee"] + burned - consumed) if (consumed or burned) else None
    wt = d["current_weight_jin"]
    tgt = (d.get("profile") or {}).get("target_weight_jin")

    if any(k in q for k in ("多重", "体重", "几斤", "多少斤")):
        gap = round(wt - tgt, 1) if tgt else None
        line = f"你最新记录的空腹体重是 <strong>{wt} 斤</strong>"
        if gap is not None and gap > 0:
            line += f"，离目标 {tgt} 斤还差 <strong>{gap} 斤</strong>"
        elif gap is not None:
            line += f"，目标 {tgt} 斤已经达成（比目标低 {abs(gap)} 斤）"
        start = d.get("start_weight_jin")
        if start:
            line += f"；从第一次记录的 {start} 斤算起，累计变化 {round(wt - start, 1)} 斤"
        return line + "。以上都来自你自己的打卡记录，没有补录也没有估算。"

    if any(k in q for k in ("还剩", "额度", "能吃", "还能吃", "余量")):
        return (f"今天还能吃 <strong>{d['remaining_cal']} kcal</strong>："
                f"目标 {m['target_cal']} kcal，已摄入 {consumed} kcal，训练已消耗 {burned} kcal。"
                + ("额度已用完，外卖门禁会拦下你。" if d["remaining_cal"] <= 0 else ""))

    if any(k in q for k in ("吃了", "摄入", "吃什么了", "吃啥")):
        meals = d.get("today_meals") or []
        if not meals:
            return f"今天还没有一条饮食记录，所以摄入按 0 计（不是按目标计）。记一笔才会有数字。"
        names = "、".join(f"{html_escape(x['food_name'])}({x['cal']}k)" for x in meals[:6])
        return (f"今天累计摄入 <strong>{consumed} kcal</strong>，共 {len(meals)} 条：{names}。"
                f"注意这些热量是系统按菜名关键词粗估的，不是营养成分表数据。")

    if any(k in q for k in ("练了", "训练", "运动", "消耗")):
        tail = (f"，已连续 {d['consecutive_slacking_days']} 天没有训练记录"
                if d["consecutive_slacking_days"] else "，昨天也练过")
        return f"今天训练消耗记录为 <strong>{burned} kcal</strong>{tail}。"

    if any(k in q for k in ("缺口", "赤字", "净缺")):
        if net is None:
            return "今天还没有任何摄入或训练记录，所以缺口是 0——没有记录就没有缺口，我不猜。"
        return (f"今天净缺口 <strong>{net} kcal</strong>"
                f"（维持代谢 {m['tdee']} + 训练消耗 {burned} − 摄入 {consumed}），"
                f"你的身形目标缺口是 {m['deficit']} kcal。")

    if any(k in q for k in ("超标", "富余", "超了")):
        if not d["consecutive_over_days"]:
            return "最近没有连续超标的记录。"
        return (f"已连续 <strong>{d['consecutive_over_days']}</strong> 天超出目标，"
                f"累计富余约 <strong>{d['over_cal_total']} kcal</strong>（按每日目标 {m['target_cal']} kcal 以上部分累加）。")

    if any(k in q for k in ("拦截", "挡了", "自律", "功勋")):
        s = d["takeout_stats"]
        if not (s["intercepted"] or s["substituted"] or s["cal_saved"]):
            return "还没有任何拦截或平替记录。这个数字只统计真实发生过的事件，不会预先给你记功。"
        return (f"累计拦下 <strong>{s['intercepted']}</strong> 次（门禁硬拦 {s['blocked']} 次、审核后主动退单 {s['cancelled']} 次），"
                f"另采纳低卡平替 {s['substituted']} 次。"
                f"有热量依据的少摄入合计 <strong>{s['cal_saved']} kcal</strong>"
                f"（只累计平替与退单两种算得出差额的事件，单纯被门禁拦下不折算），"
                f"按 7700 kcal≈1 kg 纯脂肪折约 {s['fat_jin']} 斤。")

    if any(k in q for k in ("喝水", "水", "饮水")):
        return f"今天记了 <strong>{d['water_cups']} 杯</strong>（约 {d['water_ml']} ml）。"

    if any(k in q for k in ("蛋白", "碳水", "脂肪", "宏量")):
        mc = d["today_macros"]
        return (f"目标：蛋白 {m['protein_g']}g / 慢碳 {m['carbs_g']}g / 脂肪 {m['fat_g']}g。"
                f"今天记录到的：蛋白 {mc['protein']}g / 碳水 {mc['carbs']}g / 脂肪 {mc['fat']}g。"
                f"注意实际克数是按估算热量的 25%/45%/30% 固定比例倒推的，不是真实营养数据。")

    if any(k in q for k in ("周期", "腰围", "身材照", "围度")):
        lc = d.get("latest_cycle")
        if not lc:
            return "还没有周期记录。上传一次身材照并填体重与肚脐腰围才会建立。"
        waist = lc.get("waist_cm")
        wtxt = f"{waist} cm" if waist else "未填（注册时不采集腰围，所以第一次提交只会标『待补围度』）"
        return (f"当前是第 {lc['cycle_num']} 周期，体重 {lc['weight_jin']} 斤，腰围 {wtxt}，"
                f"评级：{lc['tone_score']}。")

    return None


@app.post("/api/ask")
def ask(req: AskReq, user: dict = Depends(get_current_user)):
    q = (req.question or "").strip()[:120]
    if not q:
        raise HTTPException(status_code=400, detail="问题为空")

    d = compute_dashboard_data(user)
    local = answer_from_user_data(q, d)
    if local:
        return {"code": 0, "source": "data", "answer": local, "items": []}

    if not _ask_allowed(user["id"]):
        return {"code": 0, "source": "limited",
                "answer": f"联网查询太快了（每分钟最多 {_ASK_LIMIT_PER_MIN} 次），先等一会儿再问。",
                "items": []}

    try:
        items = web_search(q)
    except Exception as e:
        items = []
        note = f"联网查询没成功（{type(e).__name__}）"
    else:
        note = ""

    if not items:
        return {"code": 0, "source": "none",
                "answer": (note or "联网没查到可用结果") +
                          "。我不编答案——你可以换个说法再问，或者先看【食谱/外卖】里的内置建议。",
                "items": []}

    rows = "".join(
        f"<div style='margin:6px 0;padding:6px 8px;background:#F8FAFC;border-radius:8px;'>"
        f"<div style='font-weight:700;'>{it['title']}</div>"
        f"<div style='color:#475569;font-size:11px;margin-top:2px;'>{it['snippet']}</div>"
        f"<div style='font-size:10px;color:#94A3B8;margin-top:2px;'>来源 {it['host']}</div></div>"
        for it in items)
    return {"code": 0, "source": "web",
            "answer": f"以下是联网查到的资料（由第三方网站提供，不是本系统的减脂建议，"
                      f"涉及用药与疾病请咨询医生）：<br>{rows}",
            "items": [{"title": it["title"], "url": it["url"], "host": it["host"]} for it in items]}


# ==================== 100% REAL Chart Data API ====================

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
    ORDER BY log_date ASC
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
            weight_data.append({"date": label, "val": round(row["weight_jin"] / 2.0, 1), "jin": row["weight_jin"]})

    # If user has no weight logs yet, fall back to profile baseline
    if not weight_data:
        today_label = date.today().strftime("%m-%d")
        weight_data.append({"date": today_label, "val": round(p.get("weight_jin", 140.0) / 2.0, 1), "jin": p.get("weight_jin", 140.0)})

    # 2. Real Deficit History (Past 7 Days actual data)
    deficit_data = []
    weekdays_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(6, -1, -1):
        target_d = date.today() - timedelta(days=i)
        ds = target_d.isoformat()
        day_label = "今天" if i == 0 else weekdays_zh[target_d.weekday()]

        c.execute("SELECT SUM(cal) as c_sum FROM food_logs WHERE user_id = ? AND log_date = ?", (user["id"], ds))
        c_res = c.fetchone()["c_sum"] or 0

        c.execute("SELECT SUM(cal_burned) as b_sum FROM workout_logs WHERE user_id = ? AND log_date = ?", (user["id"], ds))
        b_res = c.fetchone()["b_sum"] or 0

        # 真实净缺口 = 维持代谢(TDEE) + 当日真实训练消耗 - 当日真实摄入
        # 用 target_cal 当基准会少算一个 deficit：吃满预算时缺口显示 0，而实际仍有 420 的缺口
        if c_res == 0 and b_res == 0:
            # 这一天一笔未记，缺口为 0，不拿目标值冒充"已创造赤字"（旧写法漏了今天）
            day_def = 0
        else:
            day_def = round(metrics["tdee"] + b_res - c_res)

        deficit_data.append({"day": day_label, "date": ds, "deficit": day_def, "consumed": c_res, "burned": b_res})

    # 3. Real Macros breakdown today
    today = date.today().isoformat()
    c.execute("SELECT SUM(protein_g) as p, SUM(carbs_g) as c, SUM(fat_g) as f, SUM(cal) as total FROM food_logs WHERE user_id = ? AND log_date = ?", (user["id"], today))
    m_row = c.fetchone()
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
def get_public_charts(username: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail=f"未找到用户 @{username}")
    return compute_charts_data(dict(user))

# ==================== Public Web Dashboard & Static Delivery ====================

@app.get("/style.css")
def get_style():
    path = os.path.join(WEB_DIR, "style.css")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/css", headers=_no_cache())
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/app.js")
def get_app_js():
    path = os.path.join(WEB_DIR, "app.js")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/javascript", headers=_no_cache())
    raise HTTPException(status_code=404, detail="app.js not found")

@app.get("/qingsu.apk")
def download_apk():
    apk_path = os.path.join(WEB_DIR, "qingsu.apk")
    if os.path.exists(apk_path):
        return FileResponse(apk_path, media_type="application/vnd.android.package-archive",
                             filename="轻塑减脂塑形_v5.0.apk", headers=_no_cache())
    raise HTTPException(status_code=404, detail="APK not found")

@app.get("/qr.svg")
def get_qr_svg():
    path = os.path.join(WEB_DIR, "qr.svg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/svg+xml", headers=_no_cache())
    raise HTTPException(status_code=404, detail="qr.svg not found")

@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    content = render_index_html()
    if content is not None:
        return HTMLResponse(content, media_type="text/html", headers=_no_cache())
    return HTMLResponse("<h3>轻塑系统正在启动中...</h3>")

@app.get("/u/{username}", response_class=HTMLResponse)
def public_user_dashboard(username: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = c.fetchone()
    conn.close()
    if not user:
        # username 直接来自 URL，未转义时 /u/<img src=x onerror=...> 会在浏览器里执行（已在线上实测）
        safe_name = html_escape(username, quote=True)
        return HTMLResponse(
            f"<div style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:400px;margin:80px auto;padding:30px;background:#FFF;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.08);text-align:center;'>"
            f"<div style='font-size:48px;margin-bottom:12px;'>🔍</div>"
            f"<h2 style='color:#1E293B;font-size:18px;'>用户 @{safe_name} 暂未注册</h2>"
            f"<p style='color:#64748B;font-size:13px;line-height:1.6;'>该用户暂未在轻塑·减脂塑形伴侣中创建数据档案。<br>您可以下载轻塑 APP 注册属于您的真数据大屏！</p>"
            f"<a href='/' style='display:inline-block;margin-top:16px;padding:10px 24px;background:#059669;color:#FFF;border-radius:20px;text-decoration:none;font-weight:600;'>返回轻塑主页</a>"
            f"</div>",
            status_code=404
        )

    # Return the unified real web app with automatic target user binding & base path
    content = render_index_html()
    if content is not None:
        # json.dumps 出合法 JS 字符串，再把 < 转义掉，防用户名里的 </script> 提前闭合标签
        safe_js_name = json.dumps(username).replace("<", "\\u003c")
        injected = f"<base href=\"/\">\n<script>window.__PUBLIC_USER__ = {safe_js_name};</script>\n"
        content = content.replace("<head>", "<head>\n" + injected)
        return HTMLResponse(content, headers=_no_cache())
    return HTMLResponse("<h3>轻塑系统正在启动中...</h3>")
