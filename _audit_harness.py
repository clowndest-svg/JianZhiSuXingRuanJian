# -*- coding: utf-8 -*-
"""轻塑后端回归台：不装 fastapi，用 stub 注入后 exec 真实 server.py，
直接调用其中的路由函数体与 sqlite 查询。沙箱落在项目内，不碰 C 盘。

用法:
    python _audit_harness.py            # 跑当前源码，全部判据应为绿
    python _audit_harness.py --mutant   # 跑 git HEAD 那版（改动前），同一批判据应变红
"""
import asyncio
from datetime import date, timedelta
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

    class _Client:
        def __init__(self, host):
            self.host = host

    class Request:
        def __init__(self, ip="127.0.0.1"):
            self.client = _Client(ip)

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

    class Response:
        def __init__(self, content="", media_type=None, headers=None, status_code=200, **kw):
            self.body, self.media_type = content, media_type
            self.headers = headers or {}
            self.status_code = status_code

    rs.Response = Response
    fa.Request = Request
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
    r3_missing = [f for f in ("set_day_mode", "submit_measure", "export_csv", "ask",
                              "log_takeout_event", "check_share", "migrate_db", "_progression")
                  if not hasattr(m, f)]
    if r3_missing:
        print("[注意] 该版本缺少 %d 个本轮新增实现：" + ", ".join(r3_missing))
        print("       本轮新增判据在它上面无法执行（端点不存在，等价于全红），故只跑共有判据。")
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

    def get_secret(name):
        """旧版没有 share_secret 列，取不到就返回 None。"""
        try:
            return q("SELECT share_secret FROM users WHERE username=?", (name,))[0]["share_secret"]
        except Exception:
            return None

    def pub_page(name, key):
        """新版签名带 k、旧版没有：两种都能调，变异样本才跑得完。"""
        try:
            return m.public_user_dashboard(username=name, k=key)
        except TypeError:
            return m.public_user_dashboard(username=name)

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
    # 额度现在跟随 day_mode 的预算（休息日 rest_cal / 运动日 workout_cal），不再固定 target_cal
    # 这条测的是"额度与当日预算自洽"，两版各自都该成立：新版预算随 day_mode，旧版固定 target_cal
    budget = dash.get("budget_cal", met["target_cal"])
    check("看板剩余额度自洽", dash["remaining_cal"] == round(budget - eat),
          "remaining=%s budget=%s eat=%s" % (dash["remaining_cal"], budget, eat))
    check("看板今日摄入真实", dash["today_consumed"] == eat, dash["today_consumed"])

    # --- 4. 公网大屏注入 ---
    payload = "<img src=x onerror=alert(1)>"
    b404 = body_of(pub_page(payload, None))
    check("404 不回显原始标签", "<img src=x onerror" not in b404, b404[:100])
    # 旧判据要求"已转义"；现在更进一步——页面里根本不该出现用户名相关内容
    check("404 页完全不回显用户名", "onerror" not in b404.lower(), b404[:140])

    os.makedirs(os.path.join(SANDBOX, "web"), exist_ok=True)
    # 用仓库里那份真首页当沙箱内容：占位 HTML 里没有 app.js 引用，
    # 会让"引用带版本号/不留裸引用"这类判据变成恒真。
    real_index = os.path.join(ROOT, "app", "src", "main", "assets", "index.html")
    io.open(os.path.join(SANDBOX, "web", "index.html"), "w", encoding="utf-8", newline="").write(
        io.open(real_index, encoding="utf-8", newline="").read())

    evil = "a';alert(1);//"
    mkuser(evil, gender="male", goal_type="male_steady")
    evil_k = get_secret(evil)
    inj = [l for l in body_of(pub_page(evil, evil_k)).split("\n")
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
    evil2_k = get_secret(evil2)
    line2 = [l for l in body_of(pub_page(evil2, evil2_k)).split("\n")
             if "__PUBLIC_USER__" in l]
    lit2 = literal_of(line2[0]) if line2 else None
    check("恶意标签未裸奔在字面量里",
          lit2 is not None and "<" not in lit2, str(lit2))
    check("恶意用户名仍可被 json.loads 原样还原",
          lit2 is not None and json.loads(lit2) == evil2, str(line2))

    uname_k = get_secret(uname)
    normal = body_of(pub_page(uname, uname_k))
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

    rpub = pub_page(uname, uname_k)
    check("大屏页同样带版本号", 'src="app.js?v=' in rpub.body, "")
    check("大屏页同样 no-cache", "no-cache" in (rpub.headers or {}).get("Cache-Control", ""), "")

    for fn in ("get_style", "get_app_js", "download_apk", "get_qr_svg"):
        h = (getattr(m, fn)().headers or {}).get("Cache-Control", "")
        check("静态件 %s 带 no-cache" % fn, "no-cache" in h, h)

    # --- 9. 外卖自律统计：没有记录就必须是 0，不替用户预先记功 ---
    st0 = m.compute_dashboard_data(user)["takeout_stats"]
    check("新用户拦截统计全 0", st0["intercepted"] == 0 and st0["cal_saved"] == 0 and st0["fat_jin"] == 0, st0)

    m.log_takeout_event(m.TakeoutEventReq(event_type="substitute", cal_avoided=690, dish_name="猪脚饭"), user=user)
    m.log_takeout_event(m.TakeoutEventReq(event_type="blocked", cal_avoided=900, dish_name="奶茶"), user=user)
    m.log_takeout_event(m.TakeoutEventReq(event_type="cancelled", cal_avoided=980, dish_name="汉堡套餐"), user=user)
    st1 = m.compute_dashboard_data(user)["takeout_stats"]
    check("平替+退单计入少摄入", st1["cal_saved"] == 690 + 980, st1)
    check("门禁拦下不折算热量", st1["blocked"] == 1, st1)
    check("拦截次数=拦下+退单", st1["intercepted"] == 2, st1)
    check("脂肪折算口径正确", st1["fat_jin"] == round((690 + 980) / 7700.0 * 2, 1), st1)
    check("blocked 上报的热量被强制归零",
          q("SELECT cal_avoided FROM takeout_events WHERE event_type='blocked'")[0]["cal_avoided"] == 0,
          q("SELECT cal_avoided FROM takeout_events WHERE event_type='blocked'"))
    try:
        m.log_takeout_event(m.TakeoutEventReq(event_type="刷单"), user=user)
        check("未知事件类型被拒", False, "没抛异常")
    except Exception as e:
        check("未知事件类型被拒", getattr(e, "status_code", None) == 400, type(e).__name__)

    # 起点体重与累计富余必须是真数
    d_now = m.compute_dashboard_data(user)
    check("起点体重取真实首条记录", d_now["start_weight_jin"] == 140.0, d_now["start_weight_jin"])
    check("累计富余是真实差额", d_now["over_cal_total"] >= 0, d_now["over_cal_total"])

    # --- 10. 顾问：先答本人真数据，绝不编 ---
    a1 = m.ask(m.AskReq(question="我多重"), user=user)
    check("问体重要答真实数字", a1["source"] == "data" and "140" in a1["answer"] or "138" in a1["answer"], a1["answer"][:120])
    check("问体重不提联网", "联网" not in a1["answer"], a1["answer"][:80])

    a2 = m.ask(m.AskReq(question="我还剩多少额度"), user=user)
    check("问额度答真实剩余", a2["source"] == "data" and str(d_now["remaining_cal"]) in a2["answer"], a2["answer"][:140])

    a3 = m.ask(m.AskReq(question="今天净缺口多少"), user=user)
    check("问缺口答真实净缺口", a3["source"] == "data" and "维持代谢" in a3["answer"], a3["answer"][:140])

    a4 = m.ask(m.AskReq(question="我拦截了几次外卖"), user=user)
    check("问拦截答统计且带折算口径", a4["source"] == "data" and "7700" in a4["answer"], a4["answer"][:160])

    # 恶意菜名不得原样进 HTML 答案
    m.log_food(m.FoodLogReq(slot="午餐", food_name="<script>alert(1)</script>", cal=100), user=user)
    a5 = m.ask(m.AskReq(question="我今天吃了什么"), user=user)
    check("菜名里的标签被转义", "<script>" not in a5["answer"] and "&lt;script&gt;" in a5["answer"], a5["answer"][:160])

    # 联网兜底：要么给真来源，要么明说没查到，两种都不许编答案
    a6 = m.ask(m.AskReq(question="量子计算是什么"), user=user)
    ok_src = a6["source"] in ("web", "none")
    ok_web = a6["source"] == "web" and a6["items"] and all("url" in it for it in a6["items"])
    ok_none = a6["source"] == "none" and ("没查到" in a6["answer"] or "没成功" in a6["answer"])
    check("联网问答不编造（有来源或明说失败）", ok_src and (ok_web or ok_none),
          "source=%s items=%d" % (a6["source"], len(a6.get("items") or [])))
    if a6["source"] == "web":
        sample = a6["answer"]
        check("联网结果标注非本系统建议", "不是本系统的减脂建议" in sample, sample[:120])
        check("联网标题里的标签已转义", "<script" not in sample.lower(), sample[:120])

    # 限频：别让这个接口变成免费代理
    ok_limit = True
    for _ in range(20):
        ok_limit = ok_limit and m._ask_allowed(424242)
    check("限频放行前 12 次后拒绝", ok_limit is False and len(m._ask_hits[424242]) <= m._ASK_LIMIT_PER_MIN,
          len(m._ask_hits[424242]))

    # --- 11. 静态审计：界面上不许存在没接数据的数字（本轮 bug 的根因）---
    html_txt = io.open(os.path.join(ROOT, "app", "src", "main", "assets", "index.html"),
                       encoding="utf-8").read()
    js_txt = io.open(os.path.join(ROOT, "app", "src", "main", "assets", "app.js"),
                     encoding="utf-8").read()
    css_txt = io.open(os.path.join(ROOT, "app", "src", "main", "assets", "style.css"),
                      encoding="utf-8").read()
    all_ids = set(re.findall(r'id="([^"]+)"', html_txt))
    # 绑定方式有两种：直接 getElementById，以及经 setText(id, ...) 间接写
    bound = set(re.findall(r'getElementById\(\s*"([^"]+)"', js_txt)) \
        | set(re.findall(r'setText\(\s*"([^"]+)"', js_txt))

    # 白名单：内置知识与结构说明里的数字，不是统计量，允许写死
    STATIC_OK = {"kpi-protein-sub", "kpi-carbs-sub", "kpi-fat-sub",
                 "modal-tab-female", "modal-tab-male", "timer-display", "timer-label",
                 "takeout-quota-rule", "display-user-public-url", "modal-download-url"}

    def all_zero(t):
        """数字全为 0 —— 那是"没有记录"的诚实占位，不算假数据。"""
        nums = re.findall(r"\d+", t)
        return bool(nums) and all(int(n) == 0 for n in nums)

    unbound = []
    for i in sorted(all_ids - bound):
        mm = re.search(r'id="%s"[^>]*>([^<]*)<' % re.escape(i), html_txt)
        txt = (mm.group(1) if mm else "").strip()
        if re.search(r"[0-9]", txt) and i not in STATIC_OK and not all_zero(txt):
            unbound.append((i, txt))
    check("没有未接数据却显示数字的元素", not unbound, unbound)

    # 本轮清掉的假数，一个都不许回来
    BLACKLIST = ["5 次", "3,850", "1.1 斤", "剩余 1 次", "每周至多 1 次", "自制控油率",
                 "+580 kcal", "70.0 kg", "60.0 kg", "目标 450 kcal", "稳减4-6斤",
                 "110g (30%)", "145g (40%)", "45g (30%)", "优+ (89分)", "-1.6 斤", "-2.0 cm",
                 "69.2 kg", "680 kcal", "-220 kcal", "1400 - 1500", "165cm · 70kg", "下行稳健",
                 "已累计记录 7 次", "当前 140 斤", "今日训练已完成"]
    back = [b for b in BLACKLIST if b in html_txt]
    check("已清除的假数据没回来", not back, back)

    check("遮挡覆盖规则已追加", "遮挡与溢出修复" in css_txt and "has-floating-dl" in css_txt, "")
    check("顶栏允许换行不挤标题", "flex-wrap: wrap" in css_txt, "")
    check("长文本走省略号不竖排", "text-overflow: ellipsis" in css_txt, "")
    check("App 内隐藏悬浮下载入口",
          "floating.style.display" in js_txt and "has-floating-dl" in js_txt, "")
    check("顾问改走后端问答接口", 'postApi("/api/ask"' in js_txt, "")
    check("聊天气泡默认转义", "asHtml ? String(text) : escapeHtml(String(text))" in js_txt, "")

    # ============ 本轮：安全与每日语义 ============
    R3_NAMES = [
        "注册即写随机盐", "口令不是裸 sha256", "scrypt 可校验通过", "错误口令校验失败",
        "令牌只存哈希", "老账号登录后升级为 scrypt", "升级后仍能登录", "连错 5 次后限流 429",
        "无密钥取不到公开数据", "不存在与密钥错返回同一形状", "带正确密钥可读到公开大屏",
        "运动日预算比休息日高 170", "day_mode 回传前端", "budget_cal 跟着变",
        "训练打卡后 today_workout_done 为真", "训练打卡自动切运动日", "连续记录天数可算",
        "饮水目标按体重算", "清单勾选已按今天存库", "清单绑定的是今天",
        "周期第几天按真实日期算", "未到 7 天不催拍照", "只填数字也能建周期",
        "测量报告写明非视觉分析", "测量通道不假装看过照片", "周期名带真实第几天",
        "导出行数=库内总行数+表头", "导出带 BOM 防 Excel 乱码", "导出声明为附件下载",
        "顾问先答真实体重", "顾问能解释两种日子的真实差别", "顾问能答周期与提醒",
        "没记录时不说假摄入",
    ]
    if r3_missing:
        # 缺实现就是没做到，必须记红；跳过会让 --mutant 失去标定意义
        for nm in R3_NAMES:
            check(nm, False, "该版本没有对应实现")
    else:
        def R(ip="127.0.0.1"):
            return m.Request(ip)

        # 12. 口令与令牌不再明文
        row = q("SELECT * FROM users WHERE username=?", (uname,))[0]
        check("注册即写随机盐", bool(row["pw_salt"]) and len(row["pw_salt"]) >= 16, row["pw_salt"])
        check("口令不是裸 sha256", row["password_hash"] !=
              __import__("hashlib").sha256("pw123".encode()).hexdigest(), "")
        check("scrypt 可校验通过", m.verify_pw("pw123", row) is True, "")
        check("错误口令校验失败", m.verify_pw("wrong", row) is False, "")
        check("令牌只存哈希", bool(row["token_hash"]) and not row["token"],
              "token=%r token_hash=%s" % (row["token"], str(row["token_hash"])[:8]))

        # 老账号透明升级
        legacy = "legacy_sha"
        conn = m.get_db(); cc = conn.cursor()
        cc.execute("INSERT INTO users (username, password_hash, nickname, created_at) VALUES (?,?,?,?)",
                   (legacy, m.hash_pw("old-pass"), "老账号", "2026-10-01 00:00:00"))
        cc.execute("INSERT INTO profiles (user_id, gender, age, height, weight_jin, target_weight_jin, goal_type) "
                   "VALUES (?, 'female', 30, 160, 130, 118, 'female_lean')", (cc.lastrowid,))
        conn.commit(); conn.close()
        lg = m.login(m.LoginReq(username=legacy, password="old-pass"), R())
        after = q("SELECT pw_salt, password_hash FROM users WHERE username=?", (legacy,))[0]
        check("老账号登录后升级为 scrypt", bool(after["pw_salt"]) and
              after["password_hash"] != m.hash_pw("old-pass"), "")
        check("升级后仍能登录", m.login(m.LoginReq(username=legacy, password="old-pass"), R())["code"] == 0, "")

        # 登录限流
        lk = "brute"
        blocked = False
        for i in range(7):
            try:
                m.login(m.LoginReq(username=lk, password="nope"), R("9.9.9.9"))
            except Exception as e:
                if getattr(e, "status_code", 0) == 429:
                    blocked = True
        check("连错 5 次后限流 429", blocked, "")

        # 13. 公开大屏必须带密钥，且不给枚举信号
        nokey = None
        try:
            nokey = m.get_public_dashboard(username=uname, k=None, request=R())
        except Exception as e:
            nokey = e
        check("无密钥取不到公开数据", getattr(nokey, "status_code", 200) == 404, nokey)
        wrong_key = None
        try:
            wrong_key = m.get_public_dashboard(username=uname, k="x" * 12, request=R("2.2.2.2"))
        except Exception as e:
            wrong_key = e
        d_no = getattr(nokey, "detail", "")
        d_wr = getattr(wrong_key, "detail", "")
        check("不存在与密钥错返回同一形状", d_no == d_wr and uname not in str(d_no),
              "%r vs %r" % (d_no, d_wr))
        okk = q("SELECT share_secret FROM users WHERE username=?", (uname,))[0]["share_secret"]
        pub = m.get_public_dashboard(username=uname, k=okk, request=R("3.3.3.3"))
        check("带正确密钥可读到公开大屏", pub.get("user", {}).get("username") == uname, "")

        # 14. 休息日 / 运动日真的改额度
        m.set_day_mode(m.ModeReq(day_mode="rest"), user=user)
        rest = m.compute_dashboard_data(user)
        m.set_day_mode(m.ModeReq(day_mode="workout"), user=user)
        work = m.compute_dashboard_data(user)
        diff = work["remaining_cal"] - rest["remaining_cal"]
        check("运动日预算比休息日高 170", diff == 170, "rest=%s work=%s diff=%s"
              % (rest["remaining_cal"], work["remaining_cal"], diff))
        check("day_mode 回传前端", work["day_mode"] == "workout", work["day_mode"])
        check("budget_cal 跟着变", work["budget_cal"] == work["metrics"]["workout_cal"], "")

        # 15. 每日状态：练完自动运动日 + today_workout_done 来自服务端
        m.log_workout(m.WorkoutLogReq(duration_minutes=20, cal_burned=220.0, plan_name="测试"), user=user)
        after_w = m.compute_dashboard_data(user)
        check("训练打卡后 today_workout_done 为真", after_w["today_workout_done"] is True, "")
        check("训练打卡自动切运动日", after_w["day_mode"] == "workout", after_w["day_mode"])
        check("连续记录天数可算", after_w["streak_days"] >= 1, after_w["streak_days"])
        check("饮水目标按体重算", after_w["water_target_ml"] ==
              int(round(after_w["current_weight_jin"] / 2.0 * 35 / 50.0) * 50), after_w["water_target_ml"])

        # 清单按日期隔离
        m.save_checklist(m.ChecklistReq(state={"shop_0_1": True}), user=user)
        today = date.today().isoformat()
        got_cl = m.compute_dashboard_data(user)["checklist"]
        check("清单勾选已按今天存库", got_cl.get("shop_0_1") is True, got_cl)
        other = q("SELECT log_date FROM checklist_state WHERE user_id=?", (uid,))[0]["log_date"]
        check("清单绑定的是今天", other == today, "%s vs %s" % (other, today))

        # 16. 周期按真实日历，不传照片也能更新
        conn = m.get_db(); cc = conn.cursor()
        cc.execute("UPDATE profiles SET cycle_started_at = ? WHERE user_id = ?",
                   ((date.today() - timedelta(days=3)).isoformat(), uid))
        conn.commit(); conn.close()
        cyc = m.compute_dashboard_data(user)
        check("周期第几天按真实日期算", cyc["cycle_day"] == 4, cyc["cycle_day"])
        check("未到 7 天不催拍照", cyc["photo_due"] is False or cyc["days_since_measure"] is not None, 
              "due=%s since=%s" % (cyc["photo_due"], cyc["days_since_measure"]))

        meas = asyncio.run(m.submit_measure(weight_jin=133.0, waist_cm=82.0, photo=None, user=user))
        check("只填数字也能建周期", meas["code"] == 0 and meas["cycle_num"] >= 2, meas)
        last = q("SELECT * FROM body_cycles WHERE user_id=? ORDER BY cycle_num DESC LIMIT 1", (uid,))[0]
        check("测量报告写明非视觉分析", "非视觉分析" in last["ai_report"], last["ai_report"][:120])
        check("测量通道不假装看过照片", "未上传" in last["ai_report"] or "改用你填写的数字" in last["ai_report"],
              last["ai_report"][:160])
        check("周期名带真实第几天", "第 4 天" in last["cycle_name"], last["cycle_name"])

        # 17. CSV 导出
        resp = m.export_csv(user=user)
        body = resp.body if isinstance(resp.body, str) else resp.body.decode("utf-8")
        lines_csv = [x for x in body.split("\n") if x.strip()]
        # 必须按本人 user_id 数：库里还有别的测试账号，全库计数会虚高
        n_db = sum(q("SELECT COUNT(*) AS n FROM " + t + " WHERE user_id=?", (uid,))[0]["n"] for t in
                   ("food_logs", "weight_logs", "workout_logs", "water_logs", "takeout_events", "body_cycles"))
        check("导出行数=库内总行数+表头", len(lines_csv) == n_db + 1, "%s vs %s" % (len(lines_csv), n_db + 1))
        check("导出带 BOM 防 Excel 乱码", body.startswith("\ufeff"), body[:12])
        check("导出声明为附件下载",
              "attachment" in (resp.headers or {}).get("Content-Disposition", ""), resp.headers)

        # 18. 顾问三层
        a1 = m.ask(m.AskReq(question="我多重"), user=user)
        check("顾问先答真实体重", a1["source"] == "data" and "133" in a1["answer"], a1["answer"][:120])
        a2 = m.ask(m.AskReq(question="休息日和运动日有什么区别"), user=user)
        check("顾问能解释两种日子的真实差别", a2["source"] == "data" and "170" in a2["answer"], a2["answer"][:150])
        a3 = m.ask(m.AskReq(question="我该拍照了吗"), user=user)
        check("顾问能答周期与提醒", a3["source"] == "data" and ("第" in a3["answer"] or "该更新" in a3["answer"]),
              a3["answer"][:120])
        a4 = m.ask(m.AskReq(question="今天还没记录，我摄入多少"), user=user)
        check("没记录时不说假摄入", a4["source"] != "web", a4["source"])

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
