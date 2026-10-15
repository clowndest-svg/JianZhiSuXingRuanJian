# -*- coding: utf-8 -*-
"""轻塑后端回归台：不装 fastapi，用 stub 注入后 exec 真实 server.py，
直接调用其中的路由函数体与 sqlite 查询。沙箱落在项目内，不碰 C 盘。

用法:
    python _audit_harness.py            # 跑当前源码，全部判据应为绿
    python _audit_harness.py --mutant   # 跑 git HEAD 那版（改动前），同一批判据应变红
"""
import asyncio
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(ROOT, "_audit_sandbox")
SRC_REL = "server.py"


def install_stub_fastapi():
    fa = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code, self.detail = status_code, detail
            super().__init__(detail)

    def Depends(fn=None):
        return {"__dep__": fn}

    def Header(*a, **k):
        return None

    def File(*a, **k):
        return None

    def Form(*a, **k):
        return None

    class UploadFile:
        pass

    class FastAPI:
        def __init__(self, *a, **k):
            self.routes = []

        def add_middleware(self, *a, **k):
            pass

        def mount(self, *a, **k):
            pass

        def _reg(self, path, **kw):
            def deco(fn):
                self.routes.append((path, fn.__name__, fn))
                return fn
            return deco

        def get(self, path, **kw):
            return self._reg(path, **kw)

        post = get

    fa.FastAPI = FastAPI
    fa.HTTPException = HTTPException
    fa.Depends = Depends
    fa.Header = Header
    fa.File = File
    fa.Form = Form
    fa.UploadFile = UploadFile

    mw = types.ModuleType("fastapi.middleware")
    cors = types.ModuleType("fastapi.middleware.cors")

    class CORSMiddleware:
        pass

    cors.CORSMiddleware = CORSMiddleware
    st = types.ModuleType("fastapi.staticfiles")

    class StaticFiles:
        def __init__(self, *a, **k):
            pass

    st.StaticFiles = StaticFiles
    rs = types.ModuleType("fastapi.responses")

    class HTMLResponse:
        def __init__(self, content="", status_code=200, media_type=None, **kw):
            self.body, self.status_code = content, status_code
            self.headers = kw.get("headers") or {}

    class JSONResponse(HTMLResponse):
        pass

    class FileResponse(HTMLResponse):
        def __init__(self, path="", *a, **kw):
            # 必须真的把文件读进 body：留空会让"页面里不含某串"这类判据
            # 在旧版（走 FileResponse）上恒真，测不出任何东西。
            self.path, self.status_code = path, 200
            self.headers = kw.get("headers") or {}
            try:
                self.body = io.open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                self.body = ""

    rs.HTMLResponse = HTMLResponse
    rs.JSONResponse = JSONResponse
    rs.FileResponse = FileResponse

    py = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    py.BaseModel = BaseModel

    for name, mod in [("fastapi", fa), ("fastapi.middleware", mw),
                      ("fastapi.middleware.cors", cors), ("fastapi.staticfiles", st),
                      ("fastapi.responses", rs), ("pydantic", py)]:
        sys.modules[name] = mod
    mw.cors = cors


def load_server(source_text):
    patched = source_text.replace('"/opt/qingsu/data"', json.dumps(os.path.join(SANDBOX, "data")))
    patched = patched.replace('"/opt/qingsu/uploads"', json.dumps(os.path.join(SANDBOX, "uploads")))
    patched = patched.replace('"/opt/qingsu/web"', json.dumps(os.path.join(SANDBOX, "web")))
    install_stub_fastapi()
    mod = types.ModuleType("qingsu_under_test")
    mod.__file__ = os.path.join(ROOT, "server.py")
    exec(compile(patched, os.path.join(ROOT, "server.py"), "exec"), mod.__dict__)
    return mod


def get_source(mutant):
    if not mutant:
        return io.open(os.path.join(ROOT, SRC_REL), encoding="utf-8").read()
    out = subprocess.run(["git", "-C", ROOT, "show", "HEAD:" + SRC_REL], capture_output=True)
    if out.returncode != 0:
        sys.exit("取 HEAD 版本失败: " + out.stderr.decode("utf-8", "replace"))
    return out.stdout.decode("utf-8")


RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), str(detail)[:180]))


def body_of(r):
    return r if isinstance(r, str) else r.body


def main():
    mutant = "--mutant" in sys.argv
    shutil.rmtree(SANDBOX, ignore_errors=True)
    os.makedirs(SANDBOX, exist_ok=True)

    m = load_server(get_source(mutant))
    dbp = m.DB_PATH

    def q(sql, args=()):
        c = sqlite3.connect(dbp)
        c.row_factory = sqlite3.Row
        rows = [dict(x) for x in c.execute(sql, args).fetchall()]
        c.close()
        return rows

    def mkuser(name, **kw):
        d = dict(username=name, password="pw123", gender="female", age=28, height=165.0,
                 weight_jin=140.0, target_weight_jin=120.0, goal_type="female_hourglass",
                 dining_mode="takeout")
        d.update(kw)
        m.register(m.RegisterReq(**d))
        return dict(q("SELECT * FROM users WHERE username=?", (name,))[0])

    # --- 1. 注册不得写入伪造腰围 ---
    uname = "audit_ok_1"
    user = mkuser(uname)
    uid = user["id"]
    wl = q("SELECT waist_cm FROM weight_logs WHERE user_id=?", (uid,))
    bc = q("SELECT waist_cm, tone_score FROM body_cycles WHERE user_id=?", (uid,))
    check("注册 weight_logs 腰围留空", wl and abs(wl[0]["waist_cm"]) < 1e-9, wl)
    check("注册 body_cycles 腰围留空", bc and abs(bc[0]["waist_cm"]) < 1e-9, bc)

    # --- 2. 一笔未记时赤字柱必须是 0（含今天） ---
    ch = m.compute_charts_data(user)
    bars = {d["day"]: d["deficit"] for d in ch["deficit_history"]}
    check("今天无记录 -> 赤字 0", bars.get("今天") == 0, bars)
    check("新用户 7 根柱全 0", all(v == 0 for v in bars.values()), bars)

    # --- 3. 净缺口口径 ---
    p = dict(q("SELECT * FROM profiles WHERE user_id=?", (uid,))[0])
    met = m.compute_metrics(p)
    eat = int(met["target_cal"])
    m.log_food(m.FoodLogReq(slot="午餐", food_name="白水煮鸡胸肉", cal=eat), user=user)
    bar_today = [d for d in m.compute_charts_data(user)["deficit_history"] if d["day"] == "今天"][0]
    want = round(met["tdee"] - eat)
    check("吃满预算 -> 缺口=TDEE-摄入", bar_today["deficit"] == want,
          "got=%s want=%s 旧口径=%s" % (bar_today["deficit"], want, round(met["target_cal"] - eat)))
    check("吃满预算 -> 缺口=目标赤字", abs(bar_today["deficit"] - met["deficit"]) <= 1,
          "deficit=%s bar=%s" % (met["deficit"], bar_today["deficit"]))

    dash = m.compute_dashboard_data(user)
    check("看板剩余额度自洽", dash["remaining_cal"] == round(met["target_cal"] - eat),
          dash["remaining_cal"])
    check("看板今日摄入真实", dash["today_consumed"] == eat, dash["today_consumed"])

    # --- 4. 公网大屏注入 ---
    payload = "<img src=x onerror=alert(1)>"
    b404 = body_of(m.public_user_dashboard(username=payload))
    check("404 不回显原始标签", "<img src=x onerror" not in b404, b404[:100])
    check("404 已 HTML 转义", "&lt;img" in b404, b404[:100])

    os.makedirs(os.path.join(SANDBOX, "web"), exist_ok=True)
    # 用仓库里那份真首页当沙箱内容：占位 HTML 里没有 app.js 引用，
    # 会让"引用带版本号/不留裸引用"这类判据变成恒真。
    real_index = os.path.join(ROOT, "app", "src", "main", "assets", "index.html")
    io.open(os.path.join(SANDBOX, "web", "index.html"), "w", encoding="utf-8", newline="").write(
        io.open(real_index, encoding="utf-8", newline="").read())

    evil = "a';alert(1);//"
    mkuser(evil, gender="male", goal_type="male_steady")
    inj = [l for l in body_of(m.public_user_dashboard(username=evil)).split("\n")
           if "__PUBLIC_USER__" in l]
    check("注入行存在", len(inj) == 1, inj)
    def literal_of(txt):
        mm = re.search(r'__PUBLIC_USER__ = ("(?:[^"\\\n]|\\.)*");', txt)
        return mm.group(1) if mm else None

    line = inj[0] if inj else ""
    lit = literal_of(line)
    # 最强判据：把赋值字面量交给 json.loads，必须原样还原出用户名
    check("赋值字面量可解析且等于原用户名",
          lit is not None and json.loads(lit) == evil, line)

    evil2 = "</scr" + "ipt><svg onload=x>"
    mkuser(evil2, gender="male", goal_type="male_lean")
    line2 = [l for l in body_of(m.public_user_dashboard(username=evil2)).split("\n")
             if "__PUBLIC_USER__" in l]
    lit2 = literal_of(line2[0]) if line2 else None
    check("恶意标签未裸奔在字面量里",
          lit2 is not None and "<" not in lit2, str(lit2))
    check("恶意用户名仍可被 json.loads 原样还原",
          lit2 is not None and json.loads(lit2) == evil2, str(line2))

    normal = body_of(m.public_user_dashboard(username=uname))
    check("正常用户页带上 base", '<base href="/">' in normal, normal[:120])

    # --- 5. 周期报告：缺基准不得编造围度增减 ---
    asyncio.run(m.upgrade_cycle(weight_jin=138.0, waist_cm=85.0, photo=None, user=user))
    rows = q("SELECT * FROM body_cycles WHERE user_id=? ORDER BY cycle_num", (uid,))
    rep, score = rows[-1]["ai_report"], rows[-1]["tone_score"]
    check("无基准时不输出 cm 增减", not re.search(r"[+\-]\d+\.\d cm", rep), rep.replace("\n", " "))
    check("无基准时评级写明缺基准", "待补围度" in (score or ""), score)
    check("报告不声称做过视觉诊断", ("AI 视觉" not in rep) and ("明显变薄" not in rep),
          rep.replace("\n", " "))

    asyncio.run(m.upgrade_cycle(weight_jin=136.0, waist_cm=83.0, photo=None, user=user))
    rows2 = q("SELECT * FROM body_cycles WHERE user_id=? ORDER BY cycle_num", (uid,))
    rep2, score2 = rows2[-1]["ai_report"], rows2[-1]["tone_score"]
    check("有基准时给出 -2.0 cm", "-2.0 cm" in rep2, rep2.replace("\n", " "))
    check("有基准时评级回到档位", score2 in ("极佳 (94分)", "稳健 (88分)"), score2)
    check("体重差仍按真实两次记录", "+-2.0" not in rep2 and "-2.0 斤" in rep2, rep2.replace("\n", " "))

    # --- 6. 体重曲线只用真实记录 ---
    ch3 = m.compute_charts_data(user)
    n_days = len(q("SELECT DISTINCT log_date FROM weight_logs WHERE user_id=?", (uid,)))
    check("曲线点数=真实打卡天数", len(ch3["weight_history"]) == n_days,
          "%s vs %s" % (len(ch3["weight_history"]), n_days))

    # --- 7. 宏量估算口径（本轮没改，钉住现状防以后偷偷变） ---
    mm = ch3["macros_today"]
    check("宏量按比例倒推而非真实营养表",
          abs(mm["protein_g"] - round(eat * 0.25 / 4, 1)) < 0.11, mm)

    # --- 8. 首页出口的版本号与 Cache-Control（"网页与下载包是否实时"的判据）---
    import time as _t
    web = m.WEB_DIR

    def mk_static(name, text, shift=0):
        p = os.path.join(web, name)
        io.open(p, "w", encoding="utf-8").write(text)
        t = _t.time() + shift
        os.utime(p, (t, t))
        return p

    mk_static("app.js", "// v1")
    mk_static("style.css", "body{}")
    mk_static("qingsu.apk", "APKOLD")
    mk_static("qr.svg", "<svg/>")

    rp = m.root_dashboard()
    html = rp.body
    cc = (rp.headers or {}).get("Cache-Control", "")
    check("首页带 Cache-Control no-cache", "no-cache" in cc, cc)
    check("首页 app.js 引用带版本号", 'src="app.js?v=' in html, "")
    check("首页 style.css 引用带版本号", 'href="style.css?v=' in html, "")
    check("首页 APK 下载链接带版本号", 'href="/qingsu.apk?v=' in html, "")
    check("首页不留裸引用",
          ('src="app.js"' not in html) and ('href="/qingsu.apk"' not in html), "")

    def apk_ver(txt):
        mm = re.search(r'/qingsu\.apk\?v=(\d+)', txt)
        return mm.group(1) if mm else None

    v1 = apk_ver(html)
    check("APK 版本号取自真实 mtime", v1 not in (None, "0"), v1)

    # 关键一条：换了新包上线，首页给出的下载 URL 必须立刻不同，
    # 否则老浏览器会把它一直缓存住的旧包当最新的下发。
    mk_static("qingsu.apk", "APKNEW", shift=7)
    v2 = apk_ver(m.root_dashboard().body)
    check("换包后下载 URL 立即改变", v2 is not None and v2 != v1, "%s -> %s" % (v1, v2))

    rpub = m.public_user_dashboard(username=uname)
    check("大屏页同样带版本号", 'src="app.js?v=' in rpub.body, "")
    check("大屏页同样 no-cache", "no-cache" in (rpub.headers or {}).get("Cache-Control", ""), "")

    for fn in ("get_style", "get_app_js", "download_apk", "get_qr_svg"):
        h = (getattr(m, fn)().headers or {}).get("Cache-Control", "")
        check("静态件 %s 带 no-cache" % fn, "no-cache" in h, h)

    bad = [r for r in RESULTS if not r[1]]
    print("\n=== %s：%d 条，绿 %d，红 %d ===" % (
        "变异样本(HEAD 改动前)" if mutant else "当前源码",
        len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for name, ok, detail in RESULTS:
        print("  %s %s%s" % ("绿" if ok else "红", name, ("" if ok else "  -> " + detail)))
    # 正常模式：判据应全绿；变异模式：判据必须变红，否则说明它恒真
    if mutant:
        print("EXIT=%d" % (0 if len(bad) >= 8 else 1))
        print("变异样本红了 %d 条（判据有效性证据），少于 8 条则判据形同虚设" % len(bad))
        return 0 if len(bad) >= 8 else 1
    print("EXIT=%d" % (1 if bad else 0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
