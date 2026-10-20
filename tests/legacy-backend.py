# -*- coding: utf-8 -*-
"""轻塑后端回归台：使用真实 FastAPI/Pydantic 执行旧版回归契约，
直接调用其中的路由函数体与 sqlite 查询。沙箱落在项目内，不碰 C 盘。

用法:
    python tests/legacy-backend.py            # 跑当前源码，全部判据应为绿
    python tests/legacy-backend.py --mutant   # 跑 git HEAD 那版（改动前），同一批判据应变红
"""
import asyncio
import html as html_lib
import gc
import hashlib
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT)
SANDBOX = os.path.join(ROOT, "_audit_sandbox", "legacy-backend")
SRC_REL = "server.py"


def _css_rules(css):
    """把样式表拆成 (选择器, 规则体) 列表。只看最内层花括号，@media 的外壳忽略掉。"""
    return [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def reset_ask_limiter(m):
    """重置问答限流窗口。新版计数在 Redis/内存里由 rate_reset_all_ask 清，
    旧版只有进程内 _ask_hits 字典——两边都要真的清掉，不能因为版本没这个函数就跳过。"""
    if hasattr(m, "rate_reset_all_ask"):
        m.rate_reset_all_ask()
    else:
        try:
            m._ask_hits.clear()
        except Exception:
            pass


def load_server(source_text):
    patched = source_text.replace('"/opt/qingsu/data"', json.dumps(os.path.join(SANDBOX, "data")))
    patched = patched.replace('"/opt/qingsu/uploads"', json.dumps(os.path.join(SANDBOX, "uploads")))
    patched = patched.replace('"/opt/qingsu/web"', json.dumps(os.path.join(SANDBOX, "web")))
    # Use the installed real framework; schema validation must not be mocked out.
    mod = types.ModuleType("qingsu_under_test")
    mod.__file__ = os.path.join(ROOT, "server.py")
    exec(compile(patched, os.path.join(ROOT, "server.py"), "exec"), mod.__dict__)
    return mod


def get_source(mutant):
    if not mutant:
        return io.open(os.path.join(ROOT, SRC_REL), encoding="utf-8").read()
    out = subprocess.run(["git", "-C", ROOT, "show", MUT_REF + ":" + SRC_REL], capture_output=True)
    if out.returncode != 0:
        sys.exit("取 HEAD 版本失败: " + out.stderr.decode("utf-8", "replace"))
    return out.stdout.decode("utf-8")


# 反样本基线：--mutant 默认拿 HEAD，但一旦这批改动提交，HEAD 就等于当前源码，
# 判据会在"正反两边都绿"里失去意义。所以允许 --mutant=<ref> 钉住改动前那一版。
MUT_REF = "HEAD"
for _a in sys.argv:
    if _a.startswith("--mutant="):
        MUT_REF = _a.split("=", 1)[1]

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), str(detail)[:180]))


def body_of(r):
    return r if isinstance(r,str) else r.body.decode("utf8")


def main():
    mutant = any(a == "--mutant" or a.startswith("--mutant=") for a in sys.argv)
    assert os.path.dirname(SANDBOX)==os.path.join(ROOT,"_audit_sandbox")
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
        # 默认隔离级别下 DML 不开 commit 就等于没做：判据里那些
        # "DELETE FROM kb_entries / cheers" 清场语句必须真落盘才有效
        c.commit()
        c.close()
        return rows

    def fake_request(host="203.0.113.9"):
        """register/login 现在都要读 request 拿 IP（登录就要落属地）。
        夹具给一个带 client.host 的假请求，走的是 _ip() 真实那条路。"""
        class _R:
            client = type("C", (), {"host": host})()
            method = "POST"
            headers = {}
        return _R()

    def mkuser(name, **kw):
        d = dict(username=name, password="pw123", gender="female", age=28, height=165.0,
                 weight_jin=140.0, target_weight_jin=120.0, goal_type="female_hourglass",
                 dining_mode="takeout")
        d.update(kw)
        m.register(m.RegisterReq(**d), fake_request())
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
    check("手填热量的宏量保持未知",
          mm["protein_g"]==0 and mm["carbs_g"]==0 and mm["fat_g"]==0 and mm["unknown_records"]==1, mm)

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
    html = body_of(rp)
    cc = (rp.headers or {}).get("Cache-Control", "")
    check("首页带 Cache-Control no-cache", "no-cache" in cc, cc)
    check("首页 app.js 引用带版本号", 'src="app.js?v=' in html, "")
    check("首页 style.css 引用带版本号", 'href="style.css?v=' in html, "")
    check("首页 APK 下载链接带版本号", 'href="/qingsu.apk?v=' in html, "")
    check("首页不留裸引用",
          ('src="app.js"' not in html) and ('href="/qingsu.apk"' not in html), "")

    def apk_ver(txt):
        mm = re.search(r'/qingsu\.apk\?v=([0-9a-f]+)', txt)
        return mm.group(1) if mm else None

    v1 = apk_ver(html)
    check("APK 版本号取自内容哈希", v1 not in (None, "0"), v1)

    # 关键一条：换了新包上线，首页给出的下载 URL 必须立刻不同，
    # 否则老浏览器会把它一直缓存住的旧包当最新的下发。
    # 换包＝字节变了，URL 必须立刻不同；只碰 mtime 而内容不变时 URL 必须保持不变，
    # 否则重新部署一次就逼所有老浏览器重下一遍 4.7MB。
    mk_static("qingsu.apk", "APKNEW", shift=7)
    v2 = apk_ver(body_of(m.root_dashboard()))
    check("换包后下载 URL 立即改变", v2 is not None and v2 != v1, "%s -> %s" % (v1, v2))

    mk_static("qingsu.apk", "APKNEW", shift=99)
    v3 = apk_ver(body_of(m.root_dashboard()))
    check("内容没换只是重新部署，URL 不换", v3 == v2, "%s vs %s" % (v2, v3))

    rpub = pub_page(uname, uname_k)
    check("大屏页同样带版本号", 'src="app.js?v=' in body_of(rpub), "")
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
    ok_none = a6["source"] == "none" and any(k in a6["answer"] for k in
        ("没查到", "没成功", "没有能确认的减脂相关词", "没有一条真正讲到"))
    check("联网问答不编造（有来源或明说失败）", ok_src and (ok_web or ok_none),
          "source=%s items=%d" % (a6["source"], len(a6.get("items") or [])))
    # 原来这条包在 if source == "web" 里：一旦出口换了 source 词，它就静默跳过，
    # 免责声明丢了也不会红。改成"凡是联网来的答案都必须带声明"。
    webish = a6["source"] in ("web", "web_model", "kb")
    sample = a6["answer"]
    check("联网结果标注非本系统建议", (not webish) or "不是本系统的减脂建议" in sample,
          "source=%s %s" % (a6["source"], sample[:120]))
    check("联网答案没有双重转义", (not webish) or "&amp;amp;" not in sample, sample[:160])
    check("联网标题里的标签已转义", "<script" not in sample.lower(), sample[:120])

    # 限频：别让这个接口变成免费代理
    ok_limit = True
    for _ in range(20):
        ok_limit = ok_limit and m._ask_allowed(424242)
    check("限频放行前 12 次后拒绝", ok_limit is False and len(m._ask_hits[424242]) <= m._ASK_LIMIT_PER_MIN,
          len(m._ask_hits[424242]))

    # --- 11. 静态审计：界面上不许存在没接数据的数字（本轮 bug 的根因）---
    # 静态件也必须跟着 --mutant 取 HEAD 那版。之前这里是磁盘直读，
    # 于是"界面预填假数""内联函数断链"这类判据在变异样本上永远绿——看着像
    # 判据无效，实际是它压根没在看旧版本。
    def read_asset(name):
        if not mutant:
            return io.open(os.path.join(ROOT, "app", "src", "main", "assets", name),
                           encoding="utf-8").read()
        import subprocess
        r = subprocess.run(["git", "show", MUT_REF + ":app/src/main/assets/" + name],
                           cwd=ROOT, capture_output=True)
        return r.stdout.decode("utf-8")

    html_txt = read_asset("index.html")
    js_txt = read_asset("app.js")
    css_txt = read_asset("style.css")
    all_ids = set(re.findall(r'id="([^"]+)"', html_txt))
    # --- 11b. 键盘可达性与读屏可见性（r131 整块漏做，本轮补）---
    clickable_divs = re.findall(r'<div[^>]*onclick=[^>]*>', html_txt)
    bare = [t[:60] for t in clickable_divs if 'role="button"' not in t]
    check("可点击 div 全部声明 role=button", clickable_divs and not bare,
          "%d 处缺: %s" % (len(bare), bare[:2]))
    no_tab = [t[:60] for t in clickable_divs if 'tabindex="0"' not in t]
    check("可点击 div 都能被 Tab 走到", not no_tab, no_tab[:2])

    dialogs = re.findall(r'<div class="modal-card[^"]*"[^>]*>', html_txt)
    check("五个弹窗都声明成 dialog",
          len(dialogs) == 5 and all('role="dialog"' in d and 'aria-modal="true"' in d for d in dialogs),
          "%d 个" % len(dialogs))
    check("弹窗都有可读名字", all('aria-label="' in d for d in dialogs), "")
    check("弹窗容器可被聚焦", all('tabindex="-1"' in d for d in dialogs), "")

    # 每个 <label> 要么 for 指向控件，要么真的把控件包在里面；
    # 只数"没 for 的有几个"测不出它是包着控件还是压根没关联。
    loose = []
    for tag, inner in re.findall(r'<label((?![^>]*for=)[^>]*)>(.*?)</label>', html_txt, re.S):
        if not re.search('<(input|select|textarea)[ >/]', inner):
            loose.append(inner[:40])
    check("label 要么 for 要么真的包住输入框", not loose, loose[:3])
    bound = re.findall(r'<label[^>]*for="([^"]+)"', html_txt)
    # 只查"绑出去的都对"证明不了"该绑的都绑了"，掉出清单也会绿，所以补正向条数
    check("至少 17 个 label 用 for 绑到控件", len(bound) >= 17, len(bound))
    dangling = sorted({i for i in re.findall(r'<label[^>]*for="([^"]+)"', html_txt) if i not in all_ids})
    check("label for 指向真实存在的 id", not dangling, dangling[:3])
    check("界面上不再有悬空 label", '<label class="form-label" style="margin-bottom: 0;">挑选目标身材形态' not in html_txt, "")

    check("图表都有无障碍名字", html_txt.count('role="img"') >= 3, html_txt.count('role="img"'))
    check("缺口图配了文字摘要节点", 'id="chart-deficit-summary"' in html_txt, "")
    check("摘要由 JS 生成而不是写死", 'function describeDeficit' in js_txt
          and 'chart-deficit-summary' in js_txt, "")
    # 动作详情控制栏：说明在 320 档被两颗按钮挤成四个字一列，一句话排了十几行。
    # flex:1 单独用等于"能压到 0"，必须给基准宽并允许换行，让整句落到按钮下面。
    _ctl_at = css_txt.find(".exd-ctl {")
    _ctl = css_txt[_ctl_at:css_txt.find("}", _ctl_at)]
    _note_at = css_txt.find(".exd-note {")
    _note = css_txt[_note_at:css_txt.find("}", _note_at)]
    check("控制栏允许换行且说明有基准宽",
          "flex-wrap: wrap" in _ctl and "flex: 1 1 200px" in _note and "min-width: 0" in _note,
          (_ctl[:60], _note[:80]))

    check("达标状态用文字而不只是颜色", all(w in js_txt for w in ("达标 ", "未达 ", "超支 ", "未记录 ")), "")
    check("注册了键盘监听", 'document.addEventListener("keydown"' in js_txt, "")
    check("弹窗打开时屏蔽背景内容", 'setAttribute("aria-hidden"' in js_txt and "node.inert = true" in js_txt, "")
    check("ESC 走的是各弹窗自己的关闭入口", "closeTopDialog" in js_txt
          and ".modal-close-btn, .exd-close" in js_txt, "")

    # aria-pressed 只该出现在可切换控件上；瞬时动作按钮挂 pressed 会念成"已按下"
    pressed = re.findall(r'<(?:div|button|span)[^>]*aria-pressed[^>]*>', html_txt)
    check("pressed 只用在餐别这类可切换项",
          len(pressed) == 4 and all("meal-slot-chip" in t for t in pressed),
          "%d 处: %s" % (len(pressed), [t[:44] for t in pressed if "meal-slot" not in t][:2]))
    check("切换餐别会同步 pressed",
          "setAttribute(\"aria-pressed\", \"true\")" in js_txt
          and "setAttribute(\"aria-pressed\", \"false\")" in js_txt, "")
    # 服务端还没升级时不能只把按钮灰着：那等于把故障洗成没测
    check("服务端不支持时说明原因", "服务端未支持" in js_txt, "")
    # 完整日确认：后端接口和界面入口必须同时存在，只有接口等于没做
    check("界面上有完整日确认按钮", 'id="day-complete-btn"' in html_txt
          and "toggleDayComplete()" in html_txt, "")
    check("按钮真的打 /api/day/complete", "/api/day/complete" in js_txt
          and "function toggleDayComplete" in js_txt, "")
    check("确认状态回读自服务端而不是本地猜测", "today_confirmed" in js_txt
          and '"today_confirmed"' in get_source(mutant), "")
    check("没取到日期时按钮禁用而不是能点了没反应",
          "btn.disabled = true;" in js_txt, "")
    nav_px = [float(x) for x in re.findall(r'\.nav-item[^{]*\{[^}]*?font-size:\s*([0-9.]+)px', css_txt, re.S)]
    check("底导字号不低于 11px", bool(nav_px) and min(nav_px) >= 11.0, nav_px)
    btn_h = re.search(r'\.btn-primary\s*\{[^}]*min-height:\s*(\d+)px', css_txt, re.S)
    check("主按钮有最小触控高度", bool(btn_h) and int(btn_h.group(1)) >= 44, btn_h and btn_h.group(1))
    check("样式表支持减少动画", "prefers-reduced-motion" in css_txt, "")
    check("焦点框可见", ":focus-visible" in css_txt, "")
    # 火柴人演示：画布上不许再叠浮层。上一版在视口上挂了视角提示、相位徽标、
    # 说明三处 absolute，手机上正好压在人形上，机主的原话是"各种遮挡动画，真难看"。
    stage_at = html_txt.find('class="exd-stage"')
    strip_at = html_txt.find('class="exd-strip"')
    ctl_at = html_txt.find('class="exd-ctl"')
    check("画布区块与信息条各自独立，信息条排在画布之后",
          -1 < stage_at < strip_at < ctl_at, (stage_at, strip_at, ctl_at))
    stage_html = html_txt[stage_at:html_txt.find("</div>", stage_at)]
    check("舞台里只有一张画布，没有第二个 canvas 也没有叠层 div",
          stage_html.count("<canvas") == 1 and "<div" not in stage_html, stage_html[:100])
    for gone in ("exd-viewport-overlay", "exd-view-indicator", "exd-phase-badge",
                 "exd-hud-foot", "exd-body-canvas", "exd-camera-bar", "exd-cam-btn"):
        check("叠层控件 " + gone + " 已从界面和样式里撤掉",
              gone not in html_txt and ("." + gone) not in css_txt, gone)
    for sel in (".exd-stage {", ".exd-strip {", ".exd-canvas {"):
        at = css_txt.find(sel)
        rule = css_txt[at:css_txt.find("}", at)] if at >= 0 else ""
        check("样式里 %s 不是浮层" % sel,
              "position: absolute" not in rule and "position: fixed" not in rule, rule[:90])
    canvas_at = css_txt.find(".exd-canvas {")
    canvas_css = css_txt[canvas_at:css_txt.find("}", canvas_at)]
    check("画布按宽度自适应并限高，窄屏不会被顶出屏幕",
          "width: 100%" in canvas_css and "aspect-ratio" in canvas_css
          and "max-height" in canvas_css, canvas_css[:120])
    # 相位与发力提示改回 CSS 类，不再用 inline style 涂深色面板上那两种荧光色
    phase_at = css_txt.find(".exd-phase {")
    check("相位条有正反两态样式",
          phase_at >= 0 and ".exd-phase.back {" in css_txt
          and "badge.classList.toggle(\"back\"" in js_txt, css_txt[phase_at:phase_at + 60])

    # --- 11c. 火柴人演示层：3D 全息人体整条链路已下线 ---
    adir = os.path.join(ROOT, "app", "src", "main", "assets")
    for gone in ("body3d.js", "vendor", "models"):
        check("3D 残留 %s 已从资产目录删除" % gone,
              not os.path.exists(os.path.join(adir, gone)), gone)
    check("页面不再用 ES 模块挂 3D 层", 'type="module"' not in html_txt, "")
    check("前端没有摄像机与模型残留",
          "Body3D" not in js_txt and "ex3DCamera" not in js_txt
          and "setEx3DAngle" not in js_txt and "MUSCLE_VOLUMES" not in js_txt, "")
    srv_src = get_source(mutant)
    check("服务端不再暴露 vendor/models 静态子目录",
          "_STATIC_SUBDIRS" not in srv_src and "/vendor/{name}" not in srv_src, "")
    check("已删除的 3D 模块没有留在公网静态件清单里",
          "body3d.js" not in srv_src and "body3d.js" not in io.open(
              os.path.join(ROOT, "tests", "test_integration.py"), encoding="utf-8").read(), "")
    # 画布位图要在弹窗 show 之后再量，而且只能量 clientWidth：未 show 时是 display:none，
    # 而卡片带 slideUp 动画（起手 scale(0.97)），getBoundingClientRect 把瞬时缩放算进去，
    # 位图就小 3%，显示时再拉回来又糊一层。MuMu 320 档实测到 W=357 而不是 368，就是它。
    js_open = js_txt[js_txt.find("function openExerciseDetail"):]
    show_at = js_open.find('modal.classList.add("show")')
    rect_at = js_open.find("cv.clientWidth")
    check("画布尺寸量在弹窗显示之后且取的是布局宽度", -1 < show_at < rect_at, (show_at, rect_at))
    # 发力高亮改用半透明垫线：canvas 阴影在 2 倍 dpr 上会糊成一团绿
    check("火柴人不使用 canvas 阴影", "shadowBlur" not in js_txt, "")
    check("火柴人画在浅色底上而不是深色全息面板",
          'bg.addColorStop(0, "#FFFFFF")' in js_txt and "#020617" not in js_txt, "")
    # 取景框按这组动作全部关键帧的并集算，不随单帧缩放，否则人形呼吸式忽大忽小。
    # "包住每帧每个关节"这种行为判据在前端套件里真跑 stickBox 量坐标，这里只钉
    # "取景是个独立函数且画之前一定调用它"——源码里出现 e.frames 证明不了它被用上。
    check("取景是独立函数且在 drawFrame 里被调用",
          js_txt.find("function stickBox") >= 0
          and js_txt.find("const box = stickBox(poseKey, arch)") > js_txt.find("function drawFrame"), "")
    # 头的大小必须由恒定骨长推，不能按肩宽：矢状面动作里左右肩几乎重合，
    # 按肩宽推就画出一个没有头的火柴人。
    torso_at = js_txt.find("const torso = Math.hypot(pv[0] - st[0]")
    head_at = js_txt.find("const headR")
    pad_at = js_txt.find("const padX")
    check("头半径按恒定骨长推且不取肩宽",
          -1 < torso_at < head_at < pad_at and "l_shoulder" not in js_txt[head_at:pad_at], "")
    # 正视动作左右等权；只有矢状面才把背向镜头那一侧画细画淡
    check("左右肢体远近只在矢状面区分", 'if (!sagittal) return seg.side ? "near"' in js_txt, "")
    check("演示说明写的是火柴人关节示意", "火柴人关节示意" in js_txt, "")
    check("动作详情界面不再宣称 3D 或拖拽",
          "3D" not in html_txt[html_txt.find('id="ex-detail-modal"'):html_txt.find('id="ex-detail-steps"')]
          and "拖拽" not in html_txt, "")

    # 真机 320 档实测：聊天输入框把布局视口顶到 410，窄屏判据全部假通过。
    # flex:1 不等于能缩到固有宽度以下，表单控件必须显式 min-width:0。
    chat_at = css_txt.find(".chat-input-bar input {")
    chat_css = css_txt[chat_at:css_txt.find("}", chat_at)]
    # ============ r146：账号中心、定位与推荐 ============
    feat_txt = read_asset("features.js")
    srv = get_source(mutant)

    # 忌口清单前后端必须逐条一致（豁免清单那条判据已经证明"两份清单会漂"）
    _av_s = srv[srv.find("AVOID_TAGS = ("):srv.find(")", srv.find("AVOID_TAGS = ("))]
    _av_c = feat_txt[feat_txt.find("const AVOID_TAGS="):feat_txt.find("];", feat_txt.find("const AVOID_TAGS="))]
    srv_avoid = re.findall(r'"([a-z_]+)"', _av_s)
    cli_avoid = re.findall(r"'([a-z_]+)'", _av_c)
    check("忌口清单前后端逐条一致", bool(srv_avoid) and srv_avoid == cli_avoid,
          {"服务端": srv_avoid, "前端": cli_avoid})
    check("前端每条忌口都有中文说明", all(k in feat_txt for k in srv_avoid),
          [k for k in srv_avoid if k not in feat_txt])

    # 城市词汇必须和菜名标签对得上：对不上的话"按城市排序"就是永远不生效的死代码
    if str(ROOT) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(ROOT))
    geo_mod = __import__("app_modules.geo", fromlist=["geo"])
    _cu = js_txt[js_txt.find("const TAKEOUT_CUISINE = {"):]
    _cu = _cu[:_cu.find("};")]
    dish_cuisines = {n: [x.strip().strip('"') for x in body.split(",") if x.strip()]
                     for n, body in re.findall(r'"([^"]+)":\s*\[([^\]]*)\]', _cu)}
    check("菜系标签表非空且覆盖每道外卖", len(dish_cuisines) >= 8, len(dish_cuisines))
    _extra = {"通用", "西式", "快餐", "轻食", "茶饮", "夜宵"}
    all_tags = set()
    for _n, _la, _lo, cs in geo_mod.CITIES:
        all_tags |= set(cs)
    unknown = {d: [x for x in cs if x not in all_tags and x not in _extra]
               for d, cs in dish_cuisines.items()}
    check("菜名上的菜系标签都在城市词汇表里", not [k for k, v in unknown.items() if v], unknown)
    dead = [n for n, _la, _lo, cs in geo_mod.CITIES
            if not any(set(cs) & set(v) for v in dish_cuisines.values())]
    # 十二道菜覆盖不了四十四座城市的每一种菜系，所以这条按覆盖率判：
    # 70% 是"城市这一维真的在起作用"，掉下去多半是两边词汇表漂了。
    hit_rate = 1.0 - len(dead) / float(len(geo_mod.CITIES))
    check("七成以上城市能匹配到至少一道外卖", hit_rate >= 0.70,
          {"覆盖": "%.0f%%" % (hit_rate * 100), "匹配不到": dead[:8]})
    dead_tags = sorted({x for cs in dish_cuisines.values() for x in cs
                        if x not in _extra and x not in all_tags})
    check("菜名上没有城市用不到的死标签", not dead_tags, dead_tags)

    # 就近匹配：阈值必须真起作用，不能"在太平洋上也认成某市"
    near = geo_mod.city_of(30.57, 104.07)
    check("成都坐标能就近认出来", bool(near) and near["city"] == "成都", near)
    check("海上的坐标认不出城市而不是硬给一个", geo_mod.city_of(-30.0, -160.0) is None, None)
    check("非法坐标不抛异常", geo_mod.city_of("x", None) is None, None)

    # 邮件通道：未配置必须拒绝；发送失败要把验证码收回；验证码只存哈希、绝不回给前端
    _sc = srv[srv.find("def _send_code"):srv.find("def _account_payload")]
    check("邮件未配置走 503 而不是假装已发送", "status_code=503" in _sc, _sc[:80])
    check("发送失败要回收验证码", "DELETE FROM email_codes" in _sc, "")
    check("验证码只存哈希", "code_hash" in srv and "hash_token(code)" in srv, "")
    check("验证码不回给前端", '"code": code' not in srv and "code=code" not in _sc, "")
    check("邮箱只回掩码", "def mask_email" in srv and "email_masked" in srv, "")

    # 改密与重置的撤销范围不同：前者留当前会话，后者一个不留
    cp = srv[srv.find("def change_password"):srv.find("def upload_avatar")]
    rs = srv[srv.find("def reset_password"):srv.find("def save_location")]
    check("改密只留当前会话", '_revoke_sessions(conn, user["id"], user.get("_session_hash"))' in cp, cp[-160:])
    check("重置撤销全部会话（不留 keep 参数）", "_revoke_sessions(conn, row[\"user_id\"])" in rs, rs[-160:])

    # 头像：固定文件名（覆盖而不是堆历史）+ 必须走签名链接
    check("头像按用户固定命名", "avatar-%d.jpg" in srv, "")
    check("头像返回签名链接", "signed_photo(" in srv[srv.find("def upload_avatar"):srv.find("def email_bind_send")], "")

    # WebView 定位：三件缺一不可，而且顺序必须是"先查系统权限再放行网页"
    act = io.open(os.path.join(ROOT, "app", "src", "main", "java", "com", "fitcoach",
                               "shapemaster", "MainActivity.java"), encoding="utf-8").read()
    check("WebView 开了定位", "setGeolocationEnabled(true)" in act, "")
    prompt = act[act.find("onGeolocationPermissionsShowPrompt"):act.find("setWebChromeClient", act.find("onGeolocationPermissionsShowPrompt"))]
    check("网页问定位时先查系统权限再放行",
          "hasLocationPermission()" in prompt
          and prompt.find("hasLocationPermission()") < prompt.find("callback.invoke(origin, true"),
          prompt[:100])
    check("弹不出系统授权时把网页回调结掉", "invoke(origin, false" in prompt, prompt[-120:])
    check("授权结果回来要结掉挂起的回调", "settleGeoCallback" in act, "")
    mf = io.open(os.path.join(ROOT, "app", "src", "main", "AndroidManifest.xml"), encoding="utf-8").read()
    for perm in ("ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION"):
        check("清单声明了 " + perm, perm in mf, perm)
    check("定位不是安装必需能力（没 GPS 也能装）",
          'android:name="android.hardware.location" android:required="false"' in mf, "")

    # 观感承诺：只标注、不偷改、不藏冲突项、不假装知道商家
    check("食谱冲突只标注不改写", "meal-clash" in js_txt and "与忌口冲突" in js_txt, "")
    check("外卖推荐不藏冲突项", "与忌口冲突（仍如实标热量）" in js_txt, "")
    check("说清没有商家数据", "没有商家与配送数据" in html_txt, "")

    check("聊天输入框允许压到视口宽度以内", "min-width: 0" in chat_css, chat_css[:90])

    # 就绪上报必须是"读出来的"，不能是写死的：写死时部署脚本拿同一个字自比，
    # 发错版本也照样判就绪。
    try:
        ident = m.release_identity()
        check("没有落盘清单时如实报 unknown 而不是编一个版本号",
              ident.get("release") == "unknown" and ident.get("source_revision") == "unknown", ident)
    except AttributeError:
        check("没有落盘清单时如实报 unknown 而不是编一个版本号",
              False, "缺实现：服务端根本不上报自己是谁")
    check("服务端源码里没有写死的发布标签",
          not re.search(r'"release"\s*:\s*"r[0-9]', get_source(mutant)), "")
    if not mutant:
        dep = io.open(os.path.join(ROOT, "scripts", "deploy.py"), encoding="utf-8").read()
    else:
        dep = subprocess.run(["git", "show", MUT_REF + ":scripts/deploy.py"],
                             cwd=ROOT, capture_output=True).stdout.decode("utf-8")
    hard = re.findall(r'["\']r[0-9]{2,}["\']', dep)
    check("部署脚本源码里没有写死的发布标签", not hard, hard[:2])
    # 部署脚本只在服务器上跑得起来，本地测不到执行顺序；写错顺序就是 NameError，
    # 所以这里静态拦一道：用到 stage 之前必须先定义 stage。
    check("部署脚本先定义 stage 再推导发布标签",
          dep.find("stage=Path(") >= 0 and dep.find("stage=Path(") < dep.find("RELEASE=args.release"),
          (dep.find("stage=Path("), dep.find("RELEASE=args.release")))
    check("部署脚本按提交号对账而不是按标签自比",
          "source_revision')==args.revision" in dep.replace(" ", ""),
          dep.count("args.revision"))
    # copy_files 原来只搬 is_file()：web/vendor、web/models 整目录会被跳过，
    # 线上 3D 静默退回 2D，而部署流程一路绿灯。子目录必须显式搬。
    cf = dep[dep.find("def copy_files"):dep.find("def protect_code")]
    check("部署脚本会搬 web 下的子目录", "is_dir()" in cf and "copytree" in cf, cf[:120])

    # 内容哈希强缓存：只有 URL 上带对哈希才敢给一年，带错必须回源校验。
    # 旧版本没有 v 参数，调用会抛——那必须记成红，不能让它把整台判据砸崩。
    def cache_of(**kw):
        return (m.get_app_js(**kw).headers or {}).get("Cache-Control", "")

    try:
        good = m._asset_ver(os.path.join(m.WEB_DIR, "app.js"))
        h_ok = cache_of(v=good)
        check("哈希对得上给一年强缓存",
              "immutable" in h_ok and "max-age=31536000" in h_ok, h_ok)
        h_bad = cache_of(v="000000000000")
        check("哈希对不上必须回源", "no-cache" in h_bad, h_bad)
        h_nov = cache_of()
        check("不带哈希必须回源", "no-cache" in h_nov, h_nov)
    except TypeError as exc:
        check("哈希对得上给一年强缓存", False, "缺实现: " + type(exc).__name__)
        check("哈希对不上必须回源", False, "缺实现")
        check("不带哈希必须回源", False, "缺实现")

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
    # 第六批补：这一类不是"数字没接数据"，而是没量过的承诺。
    # 上一轮只搜了"无需外网/纯本地"，同一句假话换个写法（内置超大…模型、毫秒级极速响应）
    # 就躲过去了——用户实拍才揪出来。黑名单要按"说过的话"钉，不是按"我想到的那几个词"。
    CLAIM_BLACKLIST = ["内置超大", "轻量化减脂营养模型", "毫秒级", "极速响应",
                       "完全不需要连接外网", "100%永久免费", "永久免费", "绝对",
                       "专业医师", "医学认证", "零误差"]
    claims = [b for b in CLAIM_BLACKLIST if b in html_txt]
    check("界面没有未量过的承诺用语", not claims, claims)
    check("顾问说明承认需要联网", "需要联网" in html_txt, "")
    check("引擎选项说明本地端点需自备", "需你自己手机上跑兼容服务" in html_txt, "")
    check("默认引擎选项是服务器",
          html_txt.index('value="server"') < html_txt.index('value="auto"'), "")
    check("疑似旧默认身体数据有核对横幅", "body-suspect-card" in html_txt, "")
    check("核对横幅只提醒不改数", "去核对并改成真实值" in html_txt, "")

    # 服务端识别函数：命中旧默认组、正常值不误报
    check("能认出旧默认身体数据",
          m.body_looks_invented({"age": 26, "height": 165.0, "weight_jin": 140.0,
                                 "target_weight_jin": 120.0}) is True, "")
    check("真实填写的身体数据不被误报",
          m.body_looks_invented({"age": 29, "height": 168.0, "weight_jin": 151.0,
                                 "target_weight_jin": 132.0}) is False, "")
    check("缺字段时不崩也不误报",
          m.body_looks_invented({}) is False and m.body_looks_invented(
              {"age": None, "height": "x"}) is False, "")

    back = [b for b in BLACKLIST if b in html_txt]
    check("已清除的假数据没回来", not back, back)

    # 排版实测修复的静态护栏：窄屏下这些文案必须短到放得下
    phs = dict(re.findall(r'id="([^"]+)"[^>]*placeholder="([^"]*)"', html_txt))
    TOO_LONG = {"input-meal-text": 10, "input-weight": 10, "cycle-input-weight": 8,
                "cycle-input-waist": 8, "chat-input": 10, "prof-age": 8,
                "prof-height": 8, "prof-weight-jin": 8, "prof-target-jin": 8}
    too = [(i, phs[i], len(phs[i])) for i, lim in TOO_LONG.items()
           if i in phs and len(phs[i]) > lim]
    check("输入框提示语短到窄屏放得下", not too, too)
    check("长说明改为字段小注而非塞进提示语", "field-hint" in html_txt and "卷尺水平绕肚脐" in html_txt, "")
    check("每日状态条允许折行不裁字",
          ".daily-strip .dc-val" in css_txt and "white-space: normal" in css_txt, "")
    check("引擎状态行允许折行",
          ".ai-engine-bar .eng-why" in css_txt and "white-space: normal" in css_txt, "")
    # 实测两头都翻车过：不许收缩时它反过来挤掉品牌行，默认收缩时被长标题压成 16px。
    # 现在的契约是"可收缩 + 92px 下限"，昵称自己有 max-width 省略。
    _chip = css_txt[css_txt.index(".account-chip {"):css_txt.index("}", css_txt.index(".account-chip {"))] \
        if ".account-chip {" in css_txt else ""
    check("顶栏账号入口可收缩但有下限",
          "flex: 0 1 auto" in _chip and "min-width: 92px" in _chip, _chip[:60])
    # 百分比上限的参照是工具组自身宽度，那是 shrink-to-fit 的循环量，各引擎算得不一样
    check("账号入口宽度上限用视口单位而不是自指百分比",
          "min(240px, 60vw)" in _chip and "max-width: 52%" not in _chip, _chip[:60])
    # 级联陷阱：文件末尾那组"右侧按钮组"覆盖规则里混进了 .account-chip，
    # 它的 min-width:0 会盖掉上面 92px 的下限——只看自己那条规则是查不出来的。
    _chip_zeroed = []
    for _sel, _body in _css_rules(css_txt):
        if ".account-chip" in [p.strip() for p in _sel.split(",")]:
            if "min-width: 0" in _body or "min-width:0" in _body:
                _chip_zeroed.append(_sel.strip()[:60])
    check("账号入口的收缩下限没被后面的覆盖组抹掉", not _chip_zeroed, _chip_zeroed[:2])

    # ---- 顶栏重排（机主实拍："一上一下不好看"、"用户名那样展示好丑"） ----
    check("顶栏不再有蓝色小人 emoji 当账号图标", "👤" not in html_txt[html_txt.index('<header'):html_txt.index("</header>")], "")
    check("账号入口是头像圆点 + 昵称两块，没有描边胶囊",
          ".account-chip {" in css_txt and "border: none" in css_txt[css_txt.index(".account-chip {"):css_txt.index("}", css_txt.index(".account-chip {"))],
          "")
    check("昵称超长走省略号而不是竖排",
          "max-width: 9em" in css_txt and ".account-name {" in css_txt, "")
    _hdr_html = html_txt[html_txt.index("<header"):html_txt.index("</header>")]
    check("顶栏只剩排版切换一颗图标按钮，重复的齿轮已删",
          _hdr_html.count('class="header-icon-btn"') == 1 and "openProfileModal" in _hdr_html,
          str(_hdr_html.count('class="header-icon-btn"')))
    _fcss = read_asset("features.css")
    check("窄屏不再把账号入口挤到品牌下面一行",
          ".header-row-1{flex-wrap:wrap}" not in _fcss
          and ".header-tools{flex:1 1 100%" not in _fcss, "")
    # 昵称改在 /api/account 里回读，顶栏只在登录那一刻画过一次的话，改了名字要重开 App 才生效
    _fjs = read_asset("features.js")
    check("个人中心回读到新昵称时顶栏跟着重画",
          "updateUserUI(displayName(state.user))" in _fjs
          and "updateUserUI(state.user.username)" not in _fjs, "")
    # 档案摘要挂进品牌第二行：顶栏从"品牌 / 档案 / 模式"三层压成两层
    brand_at = html_txt.index('class="app-brand"')
    prof_at = html_txt.index('class="brand-profile"')
    tools_at = html_txt.index('class="header-tools"')
    mode_at = html_txt.index('class="header-mode-bar"')
    check("档案摘要在品牌块内、且在工具组之前", brand_at < prof_at < tools_at, (brand_at, prof_at, tools_at))
    check("顶栏只剩两层：品牌行之后直接是模式条",
          html_txt.index("</header>", prof_at) > mode_at > tools_at
          and "header-profile-line" not in html_txt, "")
    check("旧档案行与描边胶囊的样式已删除",
          ".header-profile-line" not in css_txt and ".pill-edit" not in css_txt, "")

    check("遮挡覆盖规则已追加", "遮挡与溢出修复" in css_txt and "has-floating-dl" in css_txt, "")
    # 旧断言写的是"顶栏允许换行"——换行正是要修掉的那件事（账号入口掉到品牌下面一行）。
    # 现在的契约：品牌区长文本走省略号，不换行。
    check("顶栏品牌区长文本走省略号而不是换行",
          ".app-header .brand-text h1," in css_txt
          and "white-space: nowrap" in css_txt[css_txt.index(".app-header .brand-text h1,"):css_txt.index("}", css_txt.index(".app-header .brand-text h1,"))],
          "")
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
            return m.Request({"type":"http","client":(ip,12345),"headers":[]})

        # 12. 口令与令牌不再明文
        row = q("SELECT * FROM users WHERE username=?", (uname,))[0]
        check("注册即写随机盐", bool(row["pw_salt"]) and len(row["pw_salt"]) >= 16, row["pw_salt"])
        check("口令不是裸 sha256", row["password_hash"] !=
              __import__("hashlib").sha256("pw123".encode()).hexdigest(), "")
        check("scrypt 可校验通过", m.verify_pw("pw123", row) is True, "")
        check("错误口令校验失败", m.verify_pw("wrong", row) is False, "")
        check("令牌只存哈希", not row["token"] and bool(q("SELECT token_hash FROM sessions WHERE user_id=?",(uid,))),
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
                if (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)) == 429:
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


    # ============ 第五批：假数据入库通道（六处链条逐条钉住） ============
    srv_txt = get_source(mutant)

    # A. 界面输入框不许把身体数据写死在 value 里（用户不改就直接提交进库）
    BODY_FIELDS = ["cycle-input-weight", "cycle-input-waist", "prof-age", "prof-height",
                   "prof-weight-jin", "prof-target-jin", "reg-age"]
    numeric_prefill = []
    for tag in re.findall(r"<input[^>]*>", html_txt):
        vm = re.search(r'value="([^"]*)"', tag)
        if vm and re.search(r"\d", vm.group(1)):
            numeric_prefill.append((re.search(r'id="([^"]+)"', tag).group(1), vm.group(1)))
    check("输入框不得预填身体数字", not numeric_prefill, numeric_prefill)
    # 正向：七个框必须都还在、且都带 placeholder——防止"删掉输入框"也能通过上一条
    still_there = [i for i in BODY_FIELDS if ('id="%s"' % i) in html_txt]
    hinted = [i for i in still_there
              if re.search(r'id="%s"[^>]*placeholder=' % re.escape(i), html_txt)]
    check("身体数据输入框七个都在", len(still_there) == 7, still_there)
    check("空值输入框都带说明文案", len(hinted) == 7, hinted)

    # B. 内联 on* 引用的函数必须在页面脚本里定义（syncTargetWeightPlaceholder 曾只在 HTML 里）。
    #    页面加载 app.js 与 features.js 两份，所以两处定义都算数——
    #    只扫 app.js 会把 features.js 里的真函数误报成悬空，反过来也会漏掉真问题。
    KW = {"if", "for", "while", "switch", "catch", "return", "typeof", "new", "function"}
    page_js = js_txt + "\n" + read_asset("features.js")
    called, defs = set(), set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", page_js))
    for body in re.findall(r"\bon\w+\s*=\s*\"([^\"]*)\"", html_txt):
        for nm in re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", body):
            if nm not in KW:
                called.add(nm)
    dangling = sorted(called - defs)
    check("内联处理器引用的函数都已定义", not dangling, dangling)
    check("此前断链的函数已补上定义",
          "syncTargetWeightPlaceholder" in defs and "syncTargetWeightPlaceholder" in called,
          "defined=%s referenced=%s" % ("syncTargetWeightPlaceholder" in defs,
                                        "syncTargetWeightPlaceholder" in called))

    # C. 前端读身体数据不许再用编造值兜底
    invented = re.findall(r'(?:getElementById\("(?:reg|prof|cycle)-[^"]*"\)\.value\)\s*\|\|\s*[\d.]+)', js_txt)
    check("前端身体数据无编造兜底", not invented, invented)
    check("注册与保存都做了数值有效性把关",
          js_txt.count("every(Number.isFinite)") >= 2, js_txt.count("every(Number.isFinite)"))

    # D. 服务端：身体字段缺/离谱一律 400，合法值原样入库
    _seq = [0]

    def reg_try(**kw):
        # 每次换用户名：否则第一次成功之后，其余调用会被"用户名已存在"的 400
        # 顶上，那几条"超范围应报 400"就会因为错误的原因通过
        _seq[0] += 1
        d = dict(username="r5_body_%d" % _seq[0], password="pw123", gender="female",
                 goal_type="tone", dining_mode="takeout")
        d.update(kw)
        try:
            m.register(m.RegisterReq(**d), fake_request())
            return ("ok", None, "")
        except Exception as e:
            # 只认状态码不够：必须认文案说的是哪一项，"该用户名已存在"也是 400
            return ("err", (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)), str(getattr(e, "detail", e)))

    # 详情参数不能再调一次 reg_try：它有副作用，多跑一次就把后面的用户名序号整体推走
    no_body = reg_try(age=None, height=None, weight_jin=None, target_weight_jin=None)
    check("注册缺身体字段返回 400",
          no_body[0] == "err" and no_body[1] == 400 and "请填写" in no_body[2], no_body)
    e_age = reg_try(age=5, height=170.0, weight_jin=150.0, target_weight_jin=130.0)
    check("年龄超范围返回 422", e_age[0] == "err" and e_age[1] == 422 and "age" in e_age[2], e_age)
    e_ht = reg_try(age=30, height=3.5, weight_jin=150.0, target_weight_jin=130.0)
    check("身高超范围返回 422", e_ht[0] == "err" and e_ht[1] == 422 and "height" in e_ht[2], e_ht)
    e_wt = reg_try(age=30, height=170.0, weight_jin=99999.0, target_weight_jin=130.0)
    check("体重离谱返回 422", e_wt[0] == "err" and e_wt[1] == 422 and "weight_jin" in e_wt[2], e_wt)
    okres = reg_try(age=31, height=172.0, weight_jin=155.0, target_weight_jin=133.0)
    check("合法注册成功", okres[0] == "ok", okres)
    stored = q("SELECT age, height, weight_jin, target_weight_jin FROM profiles WHERE user_id="
               "(SELECT id FROM users WHERE username='r5_body_5')")
    check("入库的是本人填的那组数",
          bool(stored) and stored[0]["age"] == 31 and abs(stored[0]["height"] - 172.0) < 0.01
          and abs(stored[0]["weight_jin"] - 155.0) < 0.01
          and abs(stored[0]["target_weight_jin"] - 133.0) < 0.01, stored)
    # 关键反向断言：绝不允许悄悄落成 26/165/140/120
    fake_landed = bool(stored) and (stored[0]["age"] == 26 or stored[0]["height"] == 165.0
                                   or stored[0]["weight_jin"] == 140.0
                                   or stored[0]["target_weight_jin"] == 120.0)
    check("没有落成那组编造的默认身体", not fake_landed, stored)

    # E. 档案更新：库里缺值时报错，不拿默认值补齐
    # G. 失败不许把库锁住：register 报错前若没关连接，连接会带着未提交事务留在进程里，
    #    后续每一次写都 database is locked（旧版实测就是这样：NOT NULL 报错时连接漏在事务里）。
    gc.collect()
    def _in_txn(o):
        try:                    # 已关闭的连接读 in_transaction 会抛 ProgrammingError，
            return bool(o.in_transaction)   # getattr 的默认值挡不住属性本身抛异常
        except Exception:
            return False
    leaked = [o for o in gc.get_objects()
              if type(o).__name__ == "Connection" and _in_txn(o)]
    check("报错路径没把连接漏在事务里", not leaked, "%d 个连接仍在事务中" % len(leaked))
    for o in leaked:            # 收割掉，否则下面几条会被这把锁憋死（旧版跑不到终点）
        try:
            o.rollback(); o.close()
        except Exception:
            pass
    can_write = True
    try:
        wc = sqlite3.connect(dbp, timeout=5)
        wc.execute("INSERT INTO users (username, password_hash, nickname, created_at)"
                   " VALUES (?,?,?,?)", ("r5_writable", "x", "锁检查", "2026-10-01 00:00:00"))
        wc.commit(); wc.close()
    except Exception as e:
        can_write = False
        write_err = str(e)[:60]
    check("失败一次之后库仍可写", can_write, "" if can_write else write_err)

    # 用独立短连接建这行缺值档案
    nid = None
    wc = sqlite3.connect(dbp, timeout=20)
    try:
        cu = wc.cursor()
        cu.execute("INSERT OR IGNORE INTO users (username, password_hash, nickname, created_at)"
                   " VALUES (?,?,?,?)", ("r5_null", "x", u"缺档案", "2026-10-01 00:00:00"))
        cu.execute("SELECT id FROM users WHERE username='r5_null'")
        nid = cu.fetchone()[0]
        cu.execute("DELETE FROM profiles WHERE user_id=?", (nid,))
        cu.execute("INSERT INTO profiles (user_id, gender, age, height, weight_jin,"
                   " target_weight_jin, goal_type, dining_mode, scene) VALUES (?,?,?,?,?,?,?,?,?)",
                   (nid, "female", None, None, None, None, "tone", "takeout", "home"))
        wc.commit()
    finally:
        wc.close()
    null_user = {"id": nid, "username": "r5_null"}
    null_code = 0
    try:
        m.update_profile(m.ProfileUpdateReq(scene="home"), null_user)
    except Exception as e:
        null_code = (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0))
    check("档案缺值时保存报错而非编造", null_code in (400,422), null_code)

    # F. 源码层面：默认值与列默认值都不许回来
    check("RegisterReq 不再带身体数据默认值",
          not re.search(r"(age|height|weight_jin|target_weight_jin): Optional\[[a-z]+\] = (?!None)", srv_txt),
          re.findall(r"(?:age|height|weight_jin|target_weight_jin): Optional\[[a-z]+\] = \S+", srv_txt)[:4])
    check("profiles 建表去掉身体数据列默认值",
          "age INTEGER DEFAULT 26" not in srv_txt and "weight_jin REAL DEFAULT 140.0" not in srv_txt,
          "")
    check("校验器在写库之前就被调用",
          "body = _body_or_400" in srv_txt and srv_txt.index("body = _body_or_400")
          < srv_txt.index("INSERT INTO profiles"), "")


    # ============ 第五批 B：AI 顾问 v2（记忆隔离 / 知识库 / 模型不可用要承认） ============
    # 旧版根本没有这些函数。缺实现要逐条记红——直接抛 AttributeError 会让整个变异台崩掉，
    # 连"红了几个"这个有效性证据都拿不到（本轮就踩过一次）。
    R5AI_NAMES = [
        "吃多了走本人数据层", "吃多了的回答带真实额度数字",
        "联网问题确实发过一次搜索", "搜索词与原始口语问句不同", "搜索词带上了领域词",
        "模型不通时明确说未运行", "模型不通时仍给第三方免责", "摘录里的实体没有双重转义",
        "记住某事写入成功", "能列出记住的内容", "别的用户查不到这条记忆", "记忆确实是空的那一位",
        "第二次命中本机知识库", "命中知识库时不再联网", "知识库答案标注查证日期非实时",
        "知识库条目落了库", "ai_memory 表存在", "kb_entries 表存在",
    ]
    if not hasattr(m, "llm_chat") or not hasattr(m, "_rewrite_query"):
        for nm in R5AI_NAMES:
            check(nm, False, "该版本没有对应实现")
    else:
        # web_search 与 llm_chat 在这里被换成固定返回：判据要的是管线行为确定，
        # 不是碰运气看必应今天给什么。替换的形状与真函数一致（title/snippet/url/host 且已转义）。
        real_web = m.web_search
        real_llm = m.llm_chat
        seen_queries = []

        def fake_web(query, limit=4):
            # 桩必须像真搜索引擎：返回的页面讲的是你问的那个词，
            # 否则相关性闸门会把桩的产物全丢掉，测出来的是桩不忠实而不是产品有问题
            seen_queries.append(query)
            topic = (query or "减脂").split(" ")[0] or "减脂"
            return [{"title": html_lib.escape(topic + "与肌肉量"),
                     "snippet": html_lib.escape("减脂期每日热量缺口建议 300 到 500 kcal，%s 要注意总量。" % topic),
                     "url": "https://example.com/a", "host": "example.com"},
                    {"title": html_lib.escape("晚餐安排"),
                     "snippet": html_lib.escape("过度节食会让%s后的夜间饥饿感增强&nbsp;&ensp;这点要注意" % topic),
                     "url": "https://example.com/b", "host": "example.com"}]
        m.web_search = fake_web
        reset_ask_limiter(m)

        u2 = mkuser("r5_ai")
        d2 = m.compute_dashboard_data(u2)
        m.log_food(m.FoodLogReq(slot="午餐", food_name="鸡胸肉", cal=300), u2)

        # 1) 用户报的那个垃圾回答：必须落在自己的数据层，不许掉进联网层
        a_bad = m.ask(m.AskReq(question="中午吃多了晚上怎么自适应补救？"), u2)
        check("吃多了走本人数据层", a_bad["source"] == "data", a_bad["source"])
        check("吃多了的回答带真实额度数字", "kcal" in a_bad["answer"] and
              ("300" in a_bad["answer"] or "还剩" in a_bad["answer"] or "超出" in a_bad["answer"]),
              a_bad["answer"][:130])

        # 2) 搜索词必须被改写，不能把整句口语直接扔进去
        reset_ask_limiter(m)
        q("DELETE FROM kb_entries")
        a_web = m.ask(m.AskReq(question="吃香蕉真的能影响减脂吗？"), u2)
        check("联网问题确实发过一次搜索", len(seen_queries) >= 1, seen_queries)
        rewrote = seen_queries[-1] if seen_queries else ""
        check("搜索词与原始口语问句不同", rewrote != "请问不吃晚饭真的能瘦得更快吗？", rewrote)
        check("搜索词带上了领域词", "减脂" in rewrote or "减肥" in rewrote, rewrote)
        # 实测坑：必应咬住查询串第一个词，首位是单字动词就返回《喝（汉语文字）》这类字典页。
        # 所以领域词必须打头，不是"有就不加"。
        check("查询串以领域词开头",
              bool(rewrote.split(" ")[0]) and rewrote.split(" ")[0]
              in (list(getattr(m, "DOMAIN_TERMS", ["减脂", "减肥"])) + ["减脂", "减肥"]), rewrote)
        check("问句里的句末语气词不进查询串",
          not rewrote.rstrip().endswith(("吗", "呢", "吧")), rewrote)
        check("单字动词不做查询串开头",
          not re.match(r"^[喝吃练睡跑抽喝]\S", rewrote), rewrote)

        # 3) 模型没跑时：说人话承认是摘录，不假装有 AI
        m.llm_chat = lambda *a, **k: None
        reset_ask_limiter(m)
        del seen_queries[:]
        a_no = m.ask(m.AskReq(question="吃苹果会不会影响减脂吗？"), u2)
        check("模型不通时明确说未运行", "本机模型未运行" in a_no["answer"], a_no["answer"][:160])
        check("未运行文案带得出真实原因", "原因：" in a_no["answer"], a_no["answer"][:200])
        # 模型回了"不够"≠模型没跑：这两种兜底话术必须不同，否则把原因赖到没发生的事实上
        reset_ask_limiter(m)
        del seen_queries[:]
        m.llm_chat = lambda *a, **k: "不够"
        q_ins = "喝酸奶会不会影响减脂吗？"
        a_ins = m.ask(m.AskReq(question=q_ins), u2)
        check("资料不足与模型未运行文案分开",
          "资料不足以回答" in a_ins["answer"] and "本机模型未运行" not in a_ins["answer"],
          a_ins["answer"][:170])
        check("模型不通时仍给第三方免责", "不是本系统的减脂建议" in a_no["answer"], a_no["answer"][:160])
        check("摘录里的实体没有双重转义", "&amp;amp;" not in a_no["answer"], a_no["answer"][:200])

        # 4) 模型给的文本必须转义后才能出网（反射型 XSS 的新入口）
        m.llm_chat = lambda *a, **k: "好的<img src=x onerror=alert(1)>按资料是 300 到 500 kcal"
        reset_ask_limiter(m)
        del seen_queries[:]
        a_xss = m.ask(m.AskReq(question="咖啡会不会影响减脂？"), u2)
        # 实现走的是剥标签（比转义更强：标签整个不存在），所以不能断言 "&lt;img 出现"，
        # 那会把正确行为读成失败。两条互证：危险形态一律不见 + 正常内容确实穿过来。
        low = a_xss["answer"].lower()
        check("模型输出不含可执行标签形态",
              "<img" not in low and "<script" not in low and "onerror=" not in low, low[:200])
        check("模型给的正经内容确实进入答案", "300 到 500" in a_xss["answer"], a_xss["answer"][:200])
        m.llm_chat = real_llm

        # 5) 长期记忆：显式写入 / 列出 / 清空
        reset_ask_limiter(m)
        a_mem = m.ask(m.AskReq(question="记住我不吃香菜和动物内脏"), u2)
        check("记住某事写入成功", a_mem["source"] == "memory" and "不吃香菜" in a_mem["answer"],
              a_mem["answer"][:120])
        a_ls = m.ask(m.AskReq(question="你记得我什么"), u2)
        check("能列出记住的内容", "香菜" in a_ls["answer"], a_ls["answer"][:120])

        # 6) 记忆必须按用户隔离——"每个用户各自的长期记忆"这条需求的实质
        u3 = mkuser("r5_ai2")
        b_ls = m.ask(m.AskReq(question="你记得我什么"), u3)
        check("别的用户查不到这条记忆", "香菜" not in b_ls["answer"], b_ls["answer"][:120])
        check("记忆确实是空的那一位", "还没有" in b_ls["answer"], b_ls["answer"][:120])
        reset_ask_limiter(m)
        a_forget = m.ask(m.AskReq(question="把记住的删掉，忘记所有"), u2)
        check("可一键清空记忆",
              a_forget["source"] == "memory" and "清空" in a_forget["answer"], a_forget["answer"][:120])
        check("清空后确实查不到", "香菜" not in m.memory_list(u2["id"]), m.memory_list(u2["id"]))

        # 7) 知识库：同问题第二次不该再抓一次必应，且要说明这不是实时结果
        reset_ask_limiter(m)
        del seen_queries[:]
        q_kb = "喝牛奶会不会影响减脂？"
        a1 = m.ask(m.AskReq(question=q_kb), u2)
        n1 = len(seen_queries)
        reset_ask_limiter(m)
        a2 = m.ask(m.AskReq(question=q_kb), u2)
        # source 与答案来历必须一致：模型说"不够"时是摘录，不许标成 web_model
        check("摘录兜底不冒充模型合成", a_no["source"] == "web", a_no["source"])
        reset_ask_limiter(m)
        del seen_queries[:]
        m.llm_chat = lambda *a, **k: "黑咖啡对减脂没有直接作用，关键是总热量。"
        q_ok = "喝豆浆会不会影响减脂吗？"
        a_ok = m.ask(m.AskReq(question=q_ok), u2)
        check("模型真合成时标 web_model", a_ok["source"] == "web_model", a_ok["source"])
        m.llm_chat = lambda *a, **k: None
        check("生成答案不命中全局知识库", a2["source"] != "kb", a2["source"])
        check("停用全局答案缓存后重新检索", len(seen_queries) >= n1, seen_queries[n1:])
        check("检索回答不冒充个人事实", a2["source"] in ("web","web_model","none"), a2["source"])
        kb_rows = q("SELECT hits FROM kb_entries WHERE qkey=?", (m._qkey(q_kb),))
        check("不再写入全局生成答案", not kb_rows, kb_rows)

        # 8) 两张新表必须真被 migrate_db 建出来
        tables = [r["name"] for r in q("SELECT name FROM sqlite_master WHERE type='table'")]
        check("ai_memory 表存在", "ai_memory" in tables, tables)
        check("kb_entries 表存在", "kb_entries" in tables, tables)

        m.web_search = real_web


    # ============ 第五批后续：Redis 限流、AI 引擎端点、版本清单 ============
    R6_NAMES = [
        "rate_hit 返回三元组且标明计数存放处", "rate_hit 超上限后拒绝",
        "Redis 不通时限流退回内存而不是放行", "Redis 不通时不抛异常",
        "ai_status 报三态字段", "ai_context 给出本人真实摘要",
        "ai_context 未登录取不到", "ai_record 空答案被拒",
        "ai_record 写入后另一账号可命中同一知识库", "ai_record 拒绝非 http 来源",
        "version.json 路由存在", "version.json 字段齐且与实际包体一致",
        "版本清单走 no-cache", "RegisterReq 不再带身体默认值",
    ]
    if not hasattr(m, "rate_hit") or not hasattr(m, "ai_status"):
        for nm in R6_NAMES:
            check(nm, False, "该版本没有对应实现")
    else:
        u6 = mkuser("r6_ai")
        # 用 mkuser 返回的整行当 user：手搓字段会漏掉 nickname，
        # 而 compute_dashboard_data 要读它——漏了就变成测试自己把产品测崩
        user6 = u6

        # 本机 6379 上真有个 RESP 服务（另一个项目留的），键会跨次存活：
        # 不先清窗口，第一次就会读到上一轮遗留的计数，判据不幂等
        m.rate_reset("r6:test")
        ok_a, where_a, n_a = m.rate_hit("r6:test", 2, 60)
        ok_b, _w2, _n2 = m.rate_hit("r6:test", 2, 60)
        ok_c, _w3, _n3 = m.rate_hit("r6:test", 2, 60)
        check("rate_hit 返回三元组且标明计数存放处", where_a in ("redis", "memory"), where_a)
        check("rate_hit 超上限后拒绝", (ok_a and ok_b) and ok_c is False, (ok_a, ok_b, ok_c))
        check("rate_reset 能清掉窗口", (n_a == 1) and (ok_a is True), (n_a, ok_a))

        # Redis 不可用时必须退回内存计数，既不能放行也不能整个接口报错
        real_cmd = m._redis_cmd
        m._redis_cmd = lambda *a, **k: (False, None)
        m._mem_buckets.clear()
        try:
            res = [m.rate_hit("r6:fallback", 1, 60) for _ in range(2)]
            check("Redis 不通时限流退回内存而不是放行",
                  res[0][0] is True and res[1][0] is False and res[0][1] == "memory", res)
            check("Redis 不通时不抛异常", m.redis_up() is False, "")
        except Exception as e:
            check("Redis 不通时限流退回内存而不是放行", False, "抛了 " + repr(e))
            check("Redis 不通时不抛异常", False, repr(e))
        finally:
            m._redis_cmd = real_cmd

        st = m.ai_status(user=user6)
        check("ai_status 报三态字段",
              set(["server_model", "redis", "model_name"]).issubset(set(st.keys())), st)
        check("RegisterReq 不再带身体默认值",
              getattr(m.RegisterReq, "age", None) is None
              and getattr(m.RegisterReq, "weight_jin", None) is None,
              (getattr(m.RegisterReq, "age", "?"), getattr(m.RegisterReq, "weight_jin", "?")))

        ctx = m.ai_context(user=user6)
        dg = ctx.get("digest") or {}
        check("ai_context 给出本人真实摘要",
              "weight_jin" in dg and "budget_cal" in dg and "remaining_cal" in dg, dg)
        # 直接传 user=None 只会抛 TypeError，测不到鉴权；鉴权是 Depends 层的事，
        # 所以这里核对源码确实挂了 get_current_user，再由公网那条真请求兜底
        ctx_src = srv_txt[srv_txt.index("def ai_context"):srv_txt.index("def ai_context") + 400]
        check("ai_context 未登录取不到", "Depends(get_current_user)" in ctx_src, ctx_src[:120])

        try:
            m.ai_record(m.AiRecordReq(question="x", answer=""), user=user6)
            check("ai_record 空答案被拒", False, "没抛异常")
        except Exception as e:
            check("ai_record 空答案被拒", (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)) == 400,
                  (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)))
        r_bad = m.ai_record(m.AiRecordReq(question="javascript 注入", answer="内容",
                                          sources=[{"title": "t", "url": "javascript:alert(1)",
                                                    "host": "x"}]), user=user6)
        kb_rows = q("SELECT answer FROM private_ai_answers WHERE question = ?", ("javascript 注入",))
        check("ai_record 拒绝非 http 来源",
              bool(kb_rows) and "javascript:" not in kb_rows[0]["answer"],
              kb_rows[0]["answer"][:80] if kb_rows else "没落库")
        u7 = mkuser("r6_ai2")
        user7 = u7
        kb2 = m.kb_lookup("javascript 注入")
        check("ai_record 私有回答不进入共享知识库", kb2 is None, kb2)

        # 版本清单：路由存在、字段齐、且与实际躺在盘上的包体一致（防手抄）
        # 框架 stub 不注册路由，读 m.routes 永远是空——那等于没测。改核源码里的装饰器。
        check("version.json 路由存在", '@app.get("/version.json")' in srv_txt, "源码里找不到该路由")
        check("动作姿态表有公网路由",
              '@app.get("/exercise_poses.json")' in srv_txt, "网页版会 404 只能走回落")
        # 断言里要拼出的是 @app.get("/app.js") 这样的完整串，
        # 上一版把 + f 写进了字符串字面量，于是四项全"找不到"——判据自己假红
        STATIC_ROUTES = ["app.js", "style.css", "exercise_poses.json", "version.json"]
        missing_routes = [f for f in STATIC_ROUTES
                          if ('@app.get("/' + f + '")') not in srv_txt]
        check("静态件都有显式公网路由", not missing_routes, missing_routes)
        # 核的是仓库里那份将要发布的清单，对的是仓库里那个 apk——这条专门防手抄错 md5
        vpath = os.path.join(ROOT, "app", "src", "main", "web_version.json")
        apkpath = os.path.join(ROOT, "qingsu.apk")
        vj = {}
        if os.path.exists(vpath) and os.path.exists(apkpath):
            vj = json.loads(io.open(vpath, encoding="utf-8").read())
            blob = io.open(apkpath, "rb").read()
            gradle = io.open(os.path.join(ROOT, "app", "build.gradle"), encoding="utf-8").read()
            import re as _re
            gcode = _re.search(r"versionCode\s+(\d+)", gradle)
            check("version.json 字段齐且与实际包体一致",
                  all(k in vj for k in ("version_code", "version_name", "apk_url", "size", "md5"))
                  and vj["md5"] == hashlib.md5(blob).hexdigest()
                  and vj["size"] == len(blob)
                  and gcode is not None and int(gcode.group(1)) == vj["version_code"],
                  {"清单md5": str(vj.get("md5"))[:8], "实际md5": hashlib.md5(blob).hexdigest()[:8],
                   "清单size": vj.get("size"), "实际size": len(blob),
                   "gradle_code": gcode.group(1) if gcode else "?", "清单code": vj.get("version_code")})
        else:
            check("version.json 字段齐且与实际包体一致", False,
                  "缺文件：web_version.json=%s qingsu.apk=%s"
                  % (os.path.exists(vpath), os.path.exists(apkpath)))
        vsrc = srv_txt[srv_txt.index('@app.get("/version.json")'):][:900]
        check("版本清单走 no-cache", "headers=_no_cache()" in vsrc, vsrc[:160])
        check("版本清单不写死版本号", "version_code" not in vsrc.split("def version_json")[1][:400]
              or "WEB_DIR" in vsrc, "路由里疑似硬编版本")
        # 更新说明现读 CHANGELOG：既不能夹带下一节的正文，也要跟当前最新条目一致。
        chg = io.open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        chg_head = next((ln[3:].strip() for ln in chg.split(chr(10)) if ln.startswith("## ")), "")
        note = (vj.get("notes") or "") if os.path.exists(vpath) else ""
        check("更新说明只讲当前这一版，不夹带下一节正文",
              bool(chg_head) and note.startswith(chg_head) and "## r" not in note,
              {"清单开头": note[:24], "CHANGELOG首条": chg_head[:24],
               "夹带下一节": "## r" in note, "长度": len(note)})
        q("DELETE FROM kb_entries")

        # ── 强制更新门：三份构建号必须同源，且豁免清单前后端一致 ──
        import re as _rx
        gradle_code = None
        g_hit = _rx.search(r"versionCode\s+(\d+)",
                           io.open(os.path.join(ROOT, "app", "build.gradle"), encoding="utf-8").read())
        if g_hit:
            gradle_code = int(g_hit.group(1))
        js_txt_for_build = read_asset("app.js")
        b_hit = _rx.search(r"const APP_BUILD = (\d+);", js_txt_for_build)
        check("客户端会自报构建号（服务端门的前提）", b_hit is not None,
              "app.js 里找不到 APP_BUILD，旧包新包在服务端长得一样")
        check("客户端自报的构建号就是 gradle 那一版",
              b_hit is not None and gradle_code is not None and int(b_hit.group(1)) == gradle_code,
              {"app.js": b_hit.group(1) if b_hit else "?", "gradle": gradle_code})
        embedded_build = None
        if os.path.exists(apkpath):
            import zipfile
            with zipfile.ZipFile(apkpath) as zf:
                member = [n for n in zf.namelist() if n.endswith("assets/app.js")]
                if member:
                    hit = _rx.search(rb"const APP_BUILD = (\d+);", zf.read(member[0]))
                    embedded_build = int(hit.group(1)) if hit else -1
        check("打出来的包里那份 app.js 也是当前构建号",
              gradle_code is not None and embedded_build == gradle_code,
              {"包内": embedded_build, "gradle": gradle_code})
        check("清单声明最低可用构建，默认策略就是只许最新版",
              vj.get("min_version_code") == vj.get("version_code"),
              {"min": vj.get("min_version_code"), "version_code": vj.get("version_code")})
        mvj = io.open(os.path.join(ROOT, "make_version_json.py"), encoding="utf-8").read()
        check("构建号由脚本从 gradle 同步并回查包内资产，不靠手抄",
              "sync_asset_build" in mvj and "apk_embedded_build" in mvj, "")
        # 旧版本没有这两个名字，直接 .index 会把整轮判据带走——缺实现要记成红，不是崩
        def _listed_in(source, marker, closer):
            at = source.find(marker)
            if at < 0:
                return None
            window = source[at:]
            end = window.find(closer)
            return set(_rx.findall(r'"(/api/[^"]+)"', window[:end if end > 0 else 200]))
        srv_exempt = _listed_in(srv_txt, "GATE_EXEMPT_PATHS", ")")
        cli_exempt = _listed_in(js_txt_for_build, "VIEWER_API_PATHS", "]")
        check("访客接口豁免清单前后端逐条一致",
              bool(srv_exempt) and srv_exempt == cli_exempt,
              {"服务端": sorted(srv_exempt or []), "客户端": sorted(cli_exempt or [])})
        check("缺构建号按太旧处理而不是按未知放行",
              "if raw[:9].isdigit() else 0" in srv_txt,
              "request_build 不再把缺头当 0，就不会有旧包被挡")
        check("门只作用于 /api/，更新通道不参与",
              'path.startswith("/api/")' in srv_txt, "门扩大到静态件会让用户下不到新包")
        deploy_txt = io.open(os.path.join(ROOT, "scripts", "deploy.py"), encoding="utf-8").read()
        knob_txt = io.open(os.path.join(ROOT, "scripts", "set-min-build.py"), encoding="utf-8").read()
        check("部署会把强更刹车脚本发到服务器", "set-min-build.py" in deploy_txt, "")
        check("改完刹车会独立回读健康检查而不是写完就算",
              "/health/ready" in knob_txt and "min_build" in knob_txt, "")
        # show 只回退出码等于"我跑过了"，什么都没告诉运维——这条是被自己抓出来的：
        # 第一次在服务器上跑 show，文件在、退出码 0、一个字没打印。
        import subprocess as _sp
        _env = dict(os.environ,
                    QINGSU_MIN_BUILD_FILE=os.path.join(ROOT, "_audit_sandbox", "probe-min_build"),
                    QINGSU_LOCAL_API="http://127.0.0.1:1")
        _shown = _sp.run([sys.executable, os.path.join(ROOT, "scripts", "set-min-build.py"), "show"],
                         capture_output=True, text=True, env=_env, timeout=60)
        try:
            _parsed = json.loads(_shown.stdout)
        except Exception:
            _parsed = {}
        check("强更刹车的 show 会把门状态打印出来",
              {"override", "manifest_min_version_code", "effective_min_build_live"} <= set(_parsed),
              "stdout=" + _shown.stdout[:120] + " stderr=" + _shown.stderr[:80])
        check("健康检查看得见门的状态与还在调用的构建号",
              '"min_build"' in srv_txt and '"build_override"' in srv_txt and '"builds"' in srv_txt, "")

        # ── 图标：一次生成八份，漏一份就是"桌面新、设置里旧" ──
        res = os.path.join(ROOT, "app", "src", "main", "res")
        icon_files = ["mipmap-%s/ic_launcher.png" % d for d in
                      ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")]
        icon_files += ["drawable-nodpi/ic_launcher_foreground.png", "drawable-nodpi/ic_launcher_monochrome.png"]
        icon_missing = [f for f in icon_files if not os.path.exists(os.path.join(res, f))]
        check("五档密度与自适应两层图标都在", not icon_missing, icon_missing)
        stale_icons = [f for f in ("drawable/ic_launcher_foreground.xml", "drawable/ic_launcher_monochrome.xml")
                       if os.path.exists(os.path.join(res, f))]
        check("旧的矢量图标层已删除，不会与新位图抢同名资源", not stale_icons, stale_icons)
        web_manifest = json.loads(io.open(os.path.join(ROOT, "app", "src", "main", "assets",
                                                       "manifest.webmanifest"), encoding="utf-8").read())
        icon_src = [i["src"].lstrip("/") for i in web_manifest.get("icons", [])]
        bad_icons = [s for s in icon_src
                     if not os.path.exists(os.path.join(ROOT, "app", "src", "main", "assets", s))
                     or ('"%s"' % s) not in srv_txt]
        check("网页清单指向的图标文件存在且有显式公网路由", bool(icon_src) and not bad_icons,
              {"清单": icon_src, "有问题": bad_icons})
        make_icons = io.open(os.path.join(ROOT, "scripts", "make-icons.py"), encoding="utf-8").read()
        check("图标可由脚本一次重生成且会清掉同名旧层",
              "removed_stale" in make_icons and "ic_launcher_round.png" in make_icons, "")
        # ── 品牌位：顶栏/下载弹窗/监督页都必须是真图，不许再拿文字或 emoji 顶替 ──
        brand_html = read_asset("index.html")
        check("顶栏品牌位是图片而不是「塑」字占位",
              '<img class="brand-icon" src="app-icon.png"' in brand_html
              and 'class="brand-icon">塑<' not in brand_html, "顶栏还在用文字当 logo")
        check("下载弹窗头部用真 logo，不是手机 emoji",
              '<img class="brand-mark" src="app-icon.png"' in brand_html
              and "📱" not in brand_html[brand_html.index("download-apk-modal"):
                                     brand_html.index("download-apk-modal") + 1200], "")
        check("访客监督页标题也带品牌图", "public-brand" in read_asset("features.js"), "")
        check("品牌图有显式公网路由", '"app-icon.png"' in srv_txt, "")
        # 原生源码也要跟着 --mutant 取反样本：磁盘直读会让这条判据在旧版上恒绿，
        # 等于从来没被标定过（这个错在同一份台子里已经犯过一次）。
        _notif_rel = "app/src/main/java/com/fitcoach/shapemaster/WebAppInterface.java"
        if mutant:
            import subprocess as _s2
            notif = _s2.run(["git", "show", MUT_REF + ":" + _notif_rel], cwd=ROOT,
                            capture_output=True).stdout.decode("utf-8")
        else:
            notif = io.open(os.path.join(ROOT, _notif_rel), encoding="utf-8").read()
        check("通知栏小图标不再借用系统警告三角",
              "android.R.drawable." not in notif and "R.drawable.ic_stat_qingsu" in notif,
              "状态栏里挂的是 Android 自带的告警图标，和用户说明不了这是轻塑的提醒")
        missing_stat = [d for d in ("mdpi", "hdpi", "xhdpi", "xxhdpi")
                      if not os.path.exists(os.path.join(res, "drawable-" + d, "ic_stat_qingsu.png"))]
        check("通知小图标四档密度都在", not missing_stat, missing_stat)
        check("通知小图标由脚本从同一张 artwork 生成（白色剪影+透明底）",
              "ic_stat_qingsu" in make_icons and "silhouette" in make_icons, "")

        feat_js = read_asset("features.js")  # 下面几条弹窗判据要看它，这里先取一次
        check("闲聊来源在界面上有中文标签，不显示 undefined", "chat:" in js_txt_for_build, "")
        # 弹窗排版系统要能被"下一个新弹窗"自动守住：裸 p/label/button 就是没接上样式。
        # 取模板正文用"反引号之间"这种朴素切法，别拿正则去啃引号，容易把自己绕死。
        _bodies = []
        _cursor = 0
        while True:
            _at = feat_js.find("toolDialog(", _cursor)
            if _at < 0:
                break
            _head = feat_js[_at:_at + 200]
            # 只数调用点：toolDialog 自己的函数体里也有反引号模板，混进来会把实现当弹窗
            if ('",' not in _head and "'," not in _head):
                _cursor = _at + 10
                continue
            _tick = feat_js.find(chr(96), _at)
            _end = feat_js.find(chr(96), _tick + 1) if _tick > 0 else -1
            if _tick > 0 and _end > _tick:
                _bodies.append(feat_js[_tick + 1:_end])
            _cursor = _at + 10
        check("每个 toolDialog 模板都用到了排版系统的结构件",
              len(_bodies) >= 6 and all(('class="td-' in b) for b in _bodies),
              {"模板数": len(_bodies),
               "没接上的": [b[:44] for b in _bodies if 'class="td-' not in b][:2]})
        # "模板里出现过 td- 类"太松：只删掉开头那一处照样过。查正文开头才算接上了层级。
        check("每个弹窗正文一开头就是排版结构件（不是裸段落）",
              all(b.lstrip()[:60].find('class="td-') >= 0 for b in _bodies),
              [b[:44] for b in _bodies if b.lstrip()[:60].find('class="td-') < 0][:2])
        _btn_all = sum(b.count("<button") for b in _bodies)
        _btn_classed = sum(b.count('<button type="button" class="td-') for b in _bodies)
        check("弹窗模板里每个按钮都带样式类（裸按钮会退回浏览器默认外观）",
              _btn_all > 0 and _btn_all == _btn_classed,
              {"按钮数": _btn_all, "带类的": _btn_classed})
        check("弹窗里的输入框都挂在表单行或记录行上",
              all(("<input" not in b) or ("td-field-row" in b or "td-row" in b or "td-item" in b)
                  for b in _bodies),
              [b[:44] for b in _bodies if "<input" in b and "td-field-row" not in b
               and "td-row" not in b and "td-item" not in b][:2])
        check("餐食核对弹窗把原文当主角、按钮分主次",
              "td-meal-head" in feat_js and "先不记" in feat_js, "")

        # ── 在线模型：没配置就如实说，配了也要过硬校验 ──
        import app_modules.online_ai as _oai
        _git = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
        check("在线模型配置文件不进仓库", "ai-online.json" in _git, _git[:60])
        check("发信配置文件不进仓库", "mail.json" in _git, _git[-60:])
        _leaks = [n for n in ("sk-", "api_key\":\"") if n in srv_txt]
        check("服务端源码里不写死密钥", not _leaks, _leaks)
        _st = _oai.online_status(force=True)
        check("没配置时状态说清为什么不能用",
              (_st["ok"] and _st["model"]) or (not _st["ok"] and len(_st["why"]) > 4), str(_st))
        check("状态结构里绝不带密钥字段", "api_key" not in json.dumps(_st), json.dumps(_st)[:80])
        _orig_chat = _oai.online_chat
        try:
            _oai.online_chat = lambda *a, **k: (json.dumps({"grams": 300, "kcal": 520,
                                                            "protein_g": 22, "carbs_g": 62,
                                                            "fat_g": 16, "basis": "按一碗汤面估"}), "")
            good = _oai.online_estimate_food("番茄鸡蛋肉汤面")
            check("在线估算正常输出被采纳", good[0] and good[0]["cal"] == 520 and good[0]["grams"] == 300,
                  str(good)[:120])
            for label, payload in (("热量离谱", {"grams": 300, "kcal": 99999, "protein_g": 20,
                                                 "carbs_g": 60, "fat_g": 15, "basis": "x"}),
                                   ("没给份量", {"grams": 0, "kcal": 500, "protein_g": 20,
                                                "carbs_g": 60, "fat_g": 15, "basis": "x"}),
                                   ("宏量离谱", {"grams": 300, "kcal": 500, "protein_g": 900,
                                                "carbs_g": 60, "fat_g": 15, "basis": "x"}),
                                   ("带诊断话", {"grams": 300, "kcal": 500, "protein_g": 20,
                                                "carbs_g": 60, "fat_g": 15, "basis": "建议咨询医生"})):
                _oai.online_chat = (lambda body: (lambda *a, **k: (json.dumps(body), "")))(payload)
                bad = _oai.online_estimate_food("测试菜")
                check("在线估算硬校验拦下「%s」" % label, bad[0] is None and bool(bad[1]), str(bad)[:110])
            _oai.online_chat = lambda *a, **k: ("今天天气不错", "")
            check("不按 JSON 返回时不硬猜数字", _oai.online_estimate_food("测试菜")[0] is None, "")
            _oai.online_chat = lambda *a, **k: (None, "连不上在线模型（URLError）")
            _none = _oai.online_estimate_food("测试菜")
            check("在线模型不通时把原因带回去而不是给个空数",
                  _none[0] is None and "连不上" in _none[1], str(_none)[:110])
        finally:
            _oai.online_chat = _orig_chat
        # 上面全都打了桩，这条用真实现：没配置就不许当场给数，配了才必须有结果
        _real = _oai.online_estimate_food("番茄鸡蛋肉汤面")
        # 通道在≠模型一定答得出来。真实现下：给不出数字就必须带回看得懂的原因，
        # 给了数字就必须带份量与依据——两头都不许含糊。
        check("估算要么给出带份量依据的结果，要么带回看得懂的原因（真实现，不打桩）",
              (_real[0] is None and len(_real[1] or "") > 4)
              or (_real[0] and _real[0]["grams"] > 0 and _real[0]["basis"]), str(_real)[:110])
        check("弹窗给了「让在线模型估一下」的入口", "estimateMealByAi" in feat_js and "meal-ai-result" in feat_js, "")
        check("模型通道不可用时按钮改口，不装作能用", "模型通道不可用" in feat_js, "")
        check("估算结果要写明按多少克和依据", "'+r.grams+' g" in feat_js and "basis" in feat_js, "")
        _kb = __import__("app_modules.nutrition", fromlist=["x"]).parse_food_nutrition("番茄鸡蛋肉汤面")
        check("复合菜名不再只认出一个食材", _kb["cal"] >= 400 and _kb["source"] == "nutrition_kb",
              "%s %s" % (_kb["cal"], _kb["reason"][:60]))
        _fc = read_asset("features.css")
        # ── r144：弹窗关得掉、按钮只有一种样子、模型通道说清是哪台 ──
        _bare = _rx.findall(r"<button\s+(?![^>]*class=)[^>]*>", js_txt_for_build)
        check("界面模板里不许有裸按钮（会退回浏览器默认外观）", not _bare,
              [b[:46] for b in _bare][:3])
        check("行内小按钮与弹窗小按钮同一套形状",
              ".btn-row, .btn-row-danger {" in css_txt and ".btn-row-danger {" in css_txt
              and "border-radius: 10px" in css_txt and "min-height: 34px" in css_txt,
              css_txt[css_txt.index(".btn-row, .btn-row-danger {"):][:60])
        check("未打开的 dialog 必须隐藏（否则 close 后还留在页面上）",
              ".tool-dialog:not([open]){display:none}" in _fc.replace(" ", "").replace(".tool-dialog:not([open]){display:none}",
                  ".tool-dialog:not([open]){display:none}") or
              ":not([open])" in _fc, _fc[_fc.index(".tool-dialog"):][:60])
        check("弹窗 show 失败要退到非模态而不是留裸节点",
              "catch(e){try{d.show();}" in feat_js.replace(" ", ""), "")
        check("保存分享设置成功后会关掉弹窗", "dlg.close()" in feat_js.replace(" ", "")
              or "dlg.close()" in feat_js, "")
        check("模型来源在界面上说清是哪台", "status.source" in feat_js and "服务器模型" in feat_js, "")
        check("宏量与热量必须自洽，模型凑数要拦下", "对不上" in io.open(
              os.path.join(ROOT, "app_modules", "online_ai.py"), encoding="utf-8").read(), "")
        check("没外部密钥时走服务器本机模型，不再谎报未接入",
              "QINGSU_LOCAL_LLM_URL" in io.open(os.path.join(ROOT, "app_modules", "online_ai.py"),
                                                 encoding="utf-8").read(), "")
        check("机主不要的那块下载大按钮已移除，链接仍带包指纹",
              "方式二" not in html_txt and "btn-direct-download" not in html_txt
              and 'id="apk-direct-link"' in html_txt, "")

        # ── 排版层：三块界面重做后，形状要钉住，不能靠"我看着顺眼了" ──
        feat_css = read_asset("features.css")
        feat_js = read_asset("features.js")
        # ── r149 社区 / 私信 / 反馈：能真跑的判据绝不只是查字符串 ──
        import time as _gate_time   # main() 里 1800 行处有一句 import time，会让这个名字在整个函数里先变局部
        _cm_tables = ("posts", "post_likes", "comments", "follows", "notifications", "conversations",
                      "messages", "user_blocks", "content_reports", "feedback", "media_uploads",
                      "community_profile")
        _missing_tables = [t for t in _cm_tables
                           if ("CREATE TABLE IF NOT EXISTS %s" % t) not in srv_txt]
        check("社区与私信的表都在 migrate_db 里建好", not _missing_tables, _missing_tables)
        check("建表集中在 migrate_db（不是路由里现建，第一次并发请求会抢着建）",
              "_community_schema(c)" in srv_txt[srv_txt.index("def migrate_db"):srv_txt.index("\nmigrate_db()")], "")
        # 未读一律现算：多存一份计数，就要在发/读/撤/重连四条路上各维护一次，早晚对不上
        check("未读不落第二份存储",
              "unread_a" not in srv_txt and "unread_b" not in srv_txt
              and "unread INTEGER" not in srv_txt, "")
        _ip_in_insert = [ln.strip()[:70] for ln in srv_txt.splitlines()
                         if ln.strip().startswith("INSERT") and re.search(r"_ip\(|remote_addr|request\.client", ln)]
        check("原始 IP 不写进任何一行库", not _ip_in_insert, _ip_in_insert[:2])
        _gp = m.geoip.status()
        if not _gp.get("ok"):
            check("离线归属库没装时如实报原因，且不编属地",
                  bool(_gp.get("why")) and m.geoip.region_of("8.8.8.8") == ""
                  and m.geoip.region_of("127.0.0.1") == "" and m.geoip.region_of("垃圾") == "", _gp)
        else:
            check("离线归属库已装载时解析不抛异常", isinstance(m.geoip.region_of("8.8.8.8"), str), _gp)
        # 字段位置是 `国家|省份|城市|运营商|国家代码`——第一版按 `国家|区域|省|市|运营商`
        # 读，把城市当成了省，还和官方读取器对不上（202.38.64.1 错成澳大利亚）。
        # 下面这些样本是拿官方 py-ip2region 在同一份 xdb 上跑出来的原话。
        check("属地收敛到省一级，不带运营商、市和国家代码",
              m.geoip._province("中国|江苏省|南京市|0|CN") == "江苏"
              and m.geoip._province("中国|北京市|北京市|腾讯|CN") == "北京"
              and m.geoip._province("中国|内蒙古自治区|呼和浩特|x|CN") == "内蒙古"
              and m.geoip._province("United States|California|0|Google LLC|US") == "United States"
              and m.geoip._province("Reserved|Reserved|Reserved|0|0") == ""
              and m.geoip._province("中国|0|0|0|CN") == "中国"
              and m.geoip._province("") == "", m.geoip._province("中国|江苏省|南京市|0|CN"))
        _sec = b"x" * 32
        _tk = m.chat.mint_ticket(_sec, 7, 31, "n-1")
        check("WS 票据能验回身份", m.chat.read_ticket(_sec, _tk)["u"] == 7, _tk[:24])
        check("票据过期即废、改一个字节即废、乱码即废",
              m.chat.read_ticket(_sec, _tk, now=_gate_time.time() + m.chat.TICKET_TTL + 5) is None
              and m.chat.read_ticket(_sec, _tk[:-3] + "AAA") is None
              and m.chat.read_ticket(_sec, "garbage") is None
              and m.chat.read_ticket(_sec, "") is None, "")
        _ws_at = srv_txt.index("async def chat_socket")
        _ws_body = srv_txt[_ws_at:_ws_at + 1200]
        check("WS 握手自己校验一次性票据（HTTP 中间件盖不到 WS）",
              "chat.read_ticket" in _ws_body and "_ticket_redeem" in _ws_body, _ws_body[:60])
        _cm_routes = re.findall(r'@app\.(?:get|post|delete)\("(/api/(?:community|chat|notifications)[^"]*)"\)\n(.*?):\n',
                                srv_txt, re.S)
        _noauth = [p for p, sig in _cm_routes if "get_current_user" not in sig]
        check("社区与私信的每个接口都要登录", len(_cm_routes) >= 12 and not _noauth,
              {"接口数": len(_cm_routes), "漏鉴权": _noauth})
        _idem_paths = re.search(r"const RECORD_PATHS = \[([^\]]*)\]", js_txt, re.S)
        _idem_list = _idem_paths.group(1) if _idem_paths else ""
        check("发帖、评论、私信都进了幂等白名单",
              "/api/community/posts" in _idem_list and "/api/chat/send" in _idem_list
              and "/api/food/log" in _idem_list and "/api/workout/complete" in _idem_list, _idem_list[:90])
        _idem_models = [c for c in ("PostReq", "CommentReq", "DmSendReq")
                        if "request_id" not in srv_txt[srv_txt.index("class " + c):srv_txt.index("class " + c) + 260]]
        check("对应的服务端模型都收 request_id", not _idem_models, _idem_models)
        _bad_kind = [k for k in m.community.NOTICE_KINDS
                     if not m.community.notice_text(k, "小田", "今天吃了什么").startswith("小田")]
        check("每种通知都拼得出人话", not _bad_kind, _bad_kind)
        check("正文与评论的更严上限在模块里，不在界面字面量里",
              m.community.POST_MAX == 1000 and m.community.COMMENT_MAX == 500
              and m.community.BIO_MAX == 60 and m.community.IMAGES_MAX == 6, "")
        _over = ""
        try:
            m.community.clean_body("字" * 1001, m.community.POST_MAX, "正文")
        except ValueError as error:
            _over = str(error)
        check("超长正文要报出来说了多少字", "1001" in _over and "1000" in _over, _over)
        check("帖子图片只收本机随机文件名，外链一律丢掉",
              m.community.clean_images(["https://evil/x.jpg", "a" * 32 + ".jpg", ""]) == ["a" * 32 + ".jpg"], "")
        check("反馈状态名两边一致",
              set(m.FEEDBACK_STATUS) == set(["new", "doing", "done", "wontfix"])
              and all(k in srv_txt[srv_txt.index("def my_feedback"):] for k in m.FEEDBACK_STATUS), "")
        check("轻塑号是 8 位数字且不与已用号重复",
              re.fullmatch(r"\d{8}", m.community.new_public_id(set())) is not None
              and m.community.new_public_id({"11111111"}) != "11111111", "")
        check("取消点赞要顺手收掉那条赞的通知",
              "DELETE FROM notifications WHERE kind='like'" in srv_txt, "")
        check("取关要顺手收掉那条关注通知",
              "DELETE FROM notifications WHERE kind='follow'" in srv_txt, "")
        check("底部导航五槽且新页面都在里面",
              html_txt.count('class="nav-item') == 5
              and all(('id="nav-' + x) in html_txt for x in ("dashboard", "community", "messages", "me", "tools")),
              html_txt.count('class="nav-item'))
        check("工具之间切换有吸顶条，不靠退回更多页再点一次",
              'id="tool-strip"' in html_txt and html_txt.count('class="ts-chip') >= 6, "")
        check("新页面不许留没接数据的数字占位",
              'id="cm-post-count">0' not in html_txt and 'id="fb-count">0' not in html_txt, "")
        check("帖子卡片与私信气泡都走转义，不拼裸 HTML",
              "escapeHtml(p.body)" in feat_js and "escapeHtml(m.body)" in feat_js
              and "escapeHtml(cmName(" in feat_js, "")
        # uvicorn 光装自己不会说 WebSocket：没有实现库时它把升级请求当普通 HTTP 转给应用，
        # 现场表现是"路由 404"，而路由明明注册着——这条判据钉的是那个隐形依赖。
        _req = io.open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
        _lock = io.open(os.path.join(ROOT, "requirements.lock"), encoding="utf-8").read()
        check("WebSocket 实现库进了依赖清单", "websockets" in _req and "websockets" in _lock,
              {"txt": "websockets" in _req, "lock": "websockets" in _lock})
        # redis-py 对 PING 有响应回调，真实返回是 True 不是 "PONG"。状态接口当初比字符串，
        # 于是线上 Redis 一直在跑、health 却一直报"从未连上"——这条按真实返回值三种形状跑函数。
        _saved_rc = m._redis_cmd
        try:
            shapes = {}
            for label, ret in (("bool", (True, True)), ("pong", (True, "PONG")), ("down", (False, None))):
                m._redis_cmd = lambda args, timeout=0.35, _r=ret: _r
                shapes[label] = m.redis_up()
            check("Redis 在不在要按 redis-py 的真实返回判，不是比字符串",
                  shapes["bool"] is True and shapes["pong"] is True and shapes["down"] is False, shapes)
        finally:
            m._redis_cmd = _saved_rc
        _ops = io.open(os.path.join(ROOT, "docs/operations.md"), encoding="utf-8").read()
        check("运维手册写了 uvicorn 要显式选 ws 后端与 nginx 的 Upgrade 透传",
              "websockets-sansio" in _ops and "proxy_http_version" in _ops, _ops[:40])
        check("私信在没有 WebSocket 时退回 HTTP 发送",
              'postApi("/api/chat/send"' in feat_js and "function wsOpen" in feat_js, "")
        check("复制轻塑号不许不管结果就说已复制",
              "复制没成功" in feat_js and "document.execCommand" in feat_js, "")
        check("开关是真 checkbox 且选中态有独立样式",
              ".td-switch:checked" in feat_css and 'type="checkbox"' in feat_js, "")
        check("分段控件靠 aria-selected 区分当前项，不是再画一颗胶囊",
              'aria-selected="true"' in feat_css and "aria-selected" in feat_js, "")
        # 拉黑是个持久状态，不是瞬时动作：按钮必须跟着服务端的 partner.blocked 走，
        # 否则重开会话时写着"拉黑"，实际早就拉黑了
        _pt = (feat_js.split("function paintThread()")[1].split("function cmBubbleHTML")[0]
               if "function paintThread()" in feat_js else "")
        check("拉黑按钮的按下态由服务端回执决定",
              "cm.thread.partner" in _pt and ".blocked" in _pt
              and 'id="thread-block-btn" aria-pressed="' in _pt
              and 'partner["blocked"]' in srv_src, {"paintThread 长度": len(_pt)})
        # 作者行没有 flex 容器时，"关注"按钮会掉到下一行；名字与属地是 inline span 时
        # 会连成"小田属地 湖南"——这两条都是截图里量出来的，不是猜的
        check("帖子卡片作者行有 flex 容器包住关注按钮",
              '<div class="cm-card-head">' in feat_js and ".cm-card-head{display:flex" in feat_css, "")
        check("名字、属地、摘要各自成行，不连成一串",
              all((".%s{" % k) in feat_css and (".%s{display:block" % k) in feat_css
                  for k in ("cm-name", "cm-sub", "cm-row-title", "cm-row-meta",
                            "td-item-title", "td-item-meta")),
              [k for k in ("cm-name", "cm-sub", "cm-row-title", "cm-row-meta",
                           "td-item-title", "td-item-meta")
               if (".%s{display:block" % k) not in feat_css])
        check("关注按钮的初始态来自服务端而不是写死",
              "p.followed_by_me" in feat_js and '"followed_by_me": followed' in srv_src, "")
        # 评论的「删除」按钮看的是服务端给的 deletable。这个字段一旦漏返回，
        # 按钮就永远不出现，界面上看着像"本来就没有删除"——本轮真的这么漏过一次。
        check("评论回执带 deletable，且口径与删除端点一致（作者或楼主）",
              '"deletable": int(c["user_id"]) == int(user["id"])' in srv_src
              and 'int(row["user_id"]) == int(user["id"])' in srv_src
              and "c.deletable" in feat_js and "removeComment(" in feat_js, "")
        # 头像在这个版本里只有一种形状：圆形。方角 16px 的 me-avatar 曾和 34px 圆头像并存
        _av = [feat_css.split(".cm-avatar{")[1].split("}")[0] if ".cm-avatar{" in feat_css else "",
               feat_css.split(".me-avatar{")[1].split("}")[0] if ".me-avatar{" in feat_css else "",
               feat_css.split(".nav-avatar,.dnav-avatar{")[1].split("}")[0] if ".nav-avatar,.dnav-avatar{" in feat_css else ""]
        check("三种尺寸的头像是同一种形状（圆）",
              all("border-radius:50%" in a for a in _av) and len(_av[0]) > 10 and len(_av[2]) > 10,
              [a[:34] for a in _av])
        # cmAvatarInner 返回的是 HTML，再套一层 escapeHtml 会把 <img> 当字面量印到屏上
        _pd = (feat_js.split("function qsCommentHTML")[1].split("function qsCommentsHTML")[0]
               if "function qsCommentHTML" in feat_js else "")
        check("帖子详情里的人用圆形头像，不用功能图标方块",
              "cm-avatar sm" in _pd and "td-glyph" not in _pd, _pd[:60])
        check("头像片段不再被二次转义",
              "escapeHtml(cmAvatarInner" not in feat_js, "")
        _primary = feat_css.split(".td-btn{")[1].split("}")[0] if ".td-btn{" in feat_css else ""
        _quiet = feat_css.split(".td-btn-quiet{")[1].split("}")[0] if ".td-btn-quiet{" in feat_css else ""
        check("主按钮与次按钮必须不同权重（原来五颗绿描边胶囊长得一模一样）",
              "linear-gradient" in _primary and bool(_quiet) and "linear-gradient" not in _quiet,
              {"primary": _primary[:60], "quiet": _quiet[:60]})
        _body = feat_css.split(".td-body{")[1].split("}")[0] if ".td-body{" in feat_css else ""
        check("对话框正文可滚动、标题固定，长列表不会顶穿屏幕",
              "overflow:auto" in _body, _body[:80])
        check("触摸目标不低于 44px",
              "min-height:44px" in feat_css and "min-height:52px" in feat_css, "")
        # 屏上印 nutrition_kb_partial 这种词等于把调试面板交给用户；来源必须过一层映射
        # 旧版本没有这张映射表，直接 .index 会把整轮判据带走（缺实现要记成红，不是崩）
        _map_at = feat_js.find("TD_SOURCE_CN")
        if _map_at < 0:
            check("餐食来源枚举全部映射成人话，屏上不印原始代码", False, "features.js 里没有 TD_SOURCE_CN 映射表")
            _map_body = ""
            _outside = feat_js
        else:
            _map_body = feat_js[_map_at:].split("};")[0]
            _outside = feat_js[:_map_at] + feat_js[_map_at + len(_map_body):]
        _mapped = set(_rx.findall(r"([a-z_]+)\s*:", _map_body))
        _known = ("direct", "manual", "legacy_estimate", "nutrition_heuristic", "nutrition_kb_partial")
        _used = set(e for e in _rx.findall(r"'([a-z_]+)'", _outside) if e in _known)
        if _map_at >= 0:
            check("餐食来源枚举全部映射成人话，屏上不印原始代码",
                  bool(_used) and _used <= _mapped and '"+ x.source +"' not in feat_js,
                  {"文件里用到": sorted(_used), "映射表有": sorted(_mapped)})
        check("下载耗时改成真测，不再写死 0.3 MB/s",
              "330000" not in js_txt_for_build and "实测下行约 0.3" not in js_txt_for_build
              and "probeDownloadRate" in js_txt_for_build, "")
        check("测速失败要显示未测而不是回落到一个好看的数",
              "下载速度未测" in js_txt_for_build and "r.status !== 206" in js_txt_for_build, "")
        check("下载按钮旁要看得见手机现装版本与包指纹",
              "apk-fresh-line" in js_txt_for_build and 'id="apk-fresh-line"' in html_txt, "")
        # App 里页面源是 assets 域，根相对路径既取不到清单也下不了包
        check("取线上资源一律带 API_BASE，不用根相对路径",
              'fetch(API_BASE + "/version.json"' in js_txt_for_build
              and 'fetch(API_BASE + "/qingsu.apk"' in js_txt_for_build
              and 'link.href = API_BASE + "/qingsu.apk' in js_txt_for_build, "")
        check("App 里点下载要交给系统浏览器（WebView 自己不会下 apk）",
              "AndroidBridge.openBrowser" in js_txt_for_build
              and "return onDirectDownloadClick(event)" in html_txt, "")

    # 评测里抓到的两条真 bug，各钉一条
    reset_ask_limiter(m)
    q("DELETE FROM kb_entries")
    a_gum = m.ask(m.AskReq(question="嚼口香糖会不会影响减脂"), user)
    check("单字糖不会把口香糖抢进奶茶场景",
          "想喝甜的" not in a_gum.get("answer", "") and a_gum["source"] in ("none", "limited"),
          "%s %s" % (a_gum["source"], a_gum.get("answer", "")[:90]))
    a_last = m.ask(m.AskReq(question="我上次训练是什么时候"), user)
    check("上次训练走本人流水不掉联网",
          a_last["source"] == "data" and ("训练记录在" in a_last["answer"] or "还没有任何训练记录" in a_last["answer"]),
          "%s %s" % (a_last["source"], a_last["answer"][:100]))
    a_cake = m.ask(m.AskReq(question="明天能不能吃一整个蛋糕"), user)
    check("预测型提问明确不作体重承诺", a_cake["source"] == "scene" and "不能预测" in a_cake["answer"],
          "%s %s" % (a_cake["source"], a_cake["answer"][:100]))
    # ── 闲聊层：一句"你好"不许再被检索口径顶回来 ──
    CHAT_PROBES = ["你好", "您好", "在吗", "谢谢", "你是谁", "你能做什么", "减肥好累", "无聊", "讲个笑话"]
    for probe_q in CHAT_PROBES:
        got_chat = m.ask(m.AskReq(question=probe_q), user)
        check("闲聊「%s」被接住而不是被拒" % probe_q,
              got_chat["source"] == "chat" and "减脂相关词" not in got_chat["answer"],
              "%s %s" % (got_chat["source"], got_chat["answer"][:60]))
        check("闲聊「%s」回答里不许带数字" % probe_q,
              not any(c.isdigit() for c in got_chat["answer"]), got_chat["answer"][:60])
    check("「我今天吃了多少」仍走本人流水不被闲聊抢走",
          m.ask(m.AskReq(question="我今天吃了多少"), user)["source"] == "data", "")
    _mid = m.ask(m.AskReq(question="你好，中午吃多了怎么办"), user)
    check("打招呼+正事不被当成寒暄敷衍", _mid["source"] in ("data", "scene"),
          "%s %s" % (_mid["source"], _mid["answer"][:80]))
    check("「吃火锅怎么点」不被当成寒暄",
          m.ask(m.AskReq(question="吃火锅怎么点"), user)["source"] != "chat", "")
    check("实词提取能认出非减脂问题的主题",
          m._content_terms("量子计算是什么") == ["量子计算"]
          and "什么" not in m._content_terms("今天天气怎么样"),
          str(m._content_terms("量子计算是什么")))
    check("闲聊关键词不许用单字（长句会误命中）",
          all(len(w) >= 2 for _k, ws, _a in m.CHAT_INTENTS for w in ws),
          [w for _k, ws, _a in m.CHAT_INTENTS for w in ws if len(w) < 2])
    check("每条闲聊意图都有确定文案",
          all(len(txt) > 8 for _k, _w, txt in m.CHAT_INTENTS), "")
    check("闲聊不许带承诺或诊断词",
          not [w for _k, _w, txt in m.CHAT_INTENTS for w in ("一定能", "保证", "绝对", "治愈", "停药") if w in txt], "")
    reset_ask_limiter(m)
    for _i in range(10):
        m.ask(m.AskReq(question="量子计算是什么"), user)
    check("开放题的小配额用完后如实说限流而不是装成没查到",
          m.ask(m.AskReq(question="量子计算是什么"), user)["source"] == "limited", "")
    _after_broad = m.ask(m.AskReq(question="不吃晚饭真的能瘦得更快吗"), user)
    check("开放题限流不影响减脂题", _after_broad["source"] in ("scene", "data", "kb", "web", "web_model"),
          "%s %s" % (_after_broad["source"], _after_broad["answer"][:80]))
    reset_ask_limiter(m)
    a_period = m.ask(m.AskReq(question="生理期要不要停训练"), user)
    check("生理期不被训练流水抢走", a_period["source"] == "scene" and "生理期" in a_period["answer"],
          "%s %s" % (a_period["source"], a_period["answer"][:90]))
    # 场景层与无领域词的拒绝都不该吃联网配额
    reset_ask_limiter(m)
    for _i in range(14):
        m.ask(m.AskReq(question="量子计算是什么"), user)
    a_after2 = m.ask(m.AskReq(question="吃苹果会不会影响减脂"), user)
    check("开放闲聊不吃减脂题的联网配额（两条配额分开）",
          a_after2["source"] != "limited", a_after2["source"])

    reset_ask_limiter(m)
    q("DELETE FROM kb_entries")
    a_plateau = m.ask(m.AskReq(question="平台期体重不掉怎么办"), user)
    check("平台期不被体重分支抢走", a_plateau["source"] == "scene" and "平台期" in a_plateau["answer"],
          "%s %s" % (a_plateau["source"], a_plateau["answer"][:110]))
    a_weight = m.ask(m.AskReq(question="我现在多重"), user)
    check("单纯问体重仍走本人流水", a_weight["source"] == "data" and "斤" in a_weight["answer"],
          "%s %s" % (a_weight["source"], a_weight["answer"][:110]))

    # ============ r124 第八批：审另一个 Agent 交付的四个提交 ============
    # 这一批的每条都对应实测抓到的一个真缺陷；旧版没有对应实现时必须记红，
    # 不然 --mutant 会把它洗成"没测"。
    import time

    def soft(name, fn):
        try:
            v = fn()
            check(name, bool(v[0]) if isinstance(v, tuple) else bool(v),
                  v[1] if isinstance(v, tuple) else "")
        except AttributeError as e:
            check(name, False, "该版本没有对应实现: %s" % e)
        except Exception as e:
            check(name, False, "%s: %s" % (type(e).__name__, str(e)[:110]))

    import inspect
    psrc = inspect.getsource(m.parse_food_nutrition)
    check("打卡估算函数存在", bool(psrc), "该版本没有 parse_food_nutrition")
    check("打卡不拦本机模型", bool(psrc) and "llm_chat" not in psrc and "llm_ready" not in psrc,
          psrc[:100] if psrc else "")
    check("成分表不冒充国家权威表", bool(psrc) and "中国食物成分表" not in psrc and "精准核算" not in psrc,
          [w for w in ("中国食物成分表", "精准核算") if psrc and w in psrc])

    def f_partial():
        r = m.log_food(m.FoodLogReq(slot="午餐", food_name="香菜牛肉拌面加煎蛋"), user=user)
        return (r.get("source") == "nutrition_kb_partial"
                and "可能比这个数高" in r.get("reason", "")
                and "AI" not in r.get("msg", "")), r
    soft("只认出一部分食材时如实说偏低", f_partial)

    def f_heur():
        r = m.log_food(m.FoodLogReq(slot="早餐", food_name="杂粮南瓜粥配腐乳"), user=user)
        return (r.get("source") == "nutrition_heuristic"
                and "粗估" in r.get("reason", "")
                and r.get("source") != "ai_model"), r
    soft("成分表没有的菜名走关键词粗估", f_heur)

    def f_kbhit():
        r = m.log_food(m.FoodLogReq(slot="早餐", food_name="茶叶蛋、纯牛奶"), user=user)
        return (r.get("source") == "nutrition_kb" and r.get("cal") == 205
                and abs(r.get("protein_g", 0) - 13.0) < 0.01), r
    soft("两样都认得出时按成分表相加", f_kbhit)

    def f_speed():
        # 计时在这套判据里量不出来：模型不通时旧代码本来就跳过 AI 分支，
        # 两边都"很快"。所以把模型装成"随时可用"，再用探针数它被调用了几次。
        real_chat, real_ready = getattr(m, "llm_chat", None), getattr(m, "llm_ready", None)
        calls = []
        m.llm_chat = lambda *a, **k: (calls.append(1), "{}")[1]
        m.llm_ready = lambda: True
        try:
            r = m.log_food(m.FoodLogReq(slot="加餐", food_name="鸡胸肉沙拉"), user=user)
        finally:
            m.llm_chat, m.llm_ready = real_chat, real_ready
        return (len(calls) == 0 and r.get("source") != "ai_model"),                "模型被叫了 %d 次, source=%s" % (len(calls), r.get("source"))
    soft("打卡链路一次都不叫模型", f_speed)

    def f_habits():
        d = m.get_habits(user=user)
        rows = d.get("days") or []
        today = date.today().isoformat()
        return (len(rows) == 30 and d.get("window") == 30 and rows[-1]["date"] == today
                and all(set(("date", "consumed", "burned", "deficit")) <= set(r) for r in rows)), \
               "len=%s last=%s" % (len(rows), rows[-1]["date"] if rows else "-")
    soft("自律矩阵后端真给 30 天", f_habits)

    def f_same_rule():
        # 正向对照：7 天柱图与 30 天矩阵必须是同一份算法出来的，两边都从 _deficit_rows 取
        bar = m.compute_charts_data(user)["deficit_history"]
        mat = m.get_habits(user=user)["days"][-7:]
        return (len(bar) == 7 and bar == mat), "柱图=%s 矩阵尾=%s" % (bar[-1], mat[-1])
    soft("柱图与矩阵同口径", f_same_rule)

    def f_table():
        cols = [r["name"] for r in q("PRAGMA table_info(cheers)")]
        return ("sender_hash" in cols and "cheer_date" in cols and "kind" in cols), cols
    soft("打气落到服务端表里", f_table)

    def f_cheer_dedup():
        m.rate_reset("cheer:5.5.5.5"); m.rate_reset("pub:5.5.5.5")
        before = q("SELECT COUNT(*) AS n FROM cheers WHERE user_id=?", (user["id"],))[0]["n"]
        a = m.post_cheer(m.CheerReq(username=uname, k=okk, kind="稳步减脂"), request=R("5.5.5.5"))
        b = m.post_cheer(m.CheerReq(username=uname, k=okk, kind="稳步减脂"), request=R("5.5.5.5"))
        c2 = m.post_cheer(m.CheerReq(username=uname, k=okk, kind="喝水达人"), request=R("5.5.5.5"))
        after = q("SELECT COUNT(*) AS n FROM cheers WHERE user_id=?", (user["id"],))[0]["n"]
        return (a["total"] == before + 1 and b["total"] == before + 1
                and c2["total"] == before + 2 and after == before + 2), \
               "before=%s a=%s b=%s c=%s after=%s" % (before, a["total"], b["total"], c2["total"], after)
    soft("同一设备同款打气一天只算一枚", f_cheer_dedup)

    def f_cheer_counts():
        other = q("SELECT COUNT(*) AS n FROM cheers WHERE user_id<>?", (user["id"],))[0]["n"]
        return (other == 0,), "别的账号被写进了 %s 条" % other
    soft("打气只写进被分享的那个人", f_cheer_counts)

    def f_cheer_kind():
        m.rate_reset("cheer:6.6.6.6"); m.rate_reset("pub:6.6.6.6")
        try:
            m.post_cheer(m.CheerReq(username=uname, k=okk, kind="<img src=x>"), request=R("6.6.6.6"))
            return False, "非白名单徽章被接受了"
        except Exception as e:
            return (422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)) == 400, repr(e)[:120]
    soft("打气文案只认白名单", f_cheer_kind)

    def f_cheer_key():
        m.rate_reset("cheer:6.6.6.7"); m.rate_reset("pub:6.6.6.7")
        codes = []
        for kk in (None, "wrongwrongwr"):
            try:
                m.post_cheer(m.CheerReq(username=uname, k=kk, kind="稳步减脂"), request=R("6.6.6.7"))
                codes.append(200)
            except Exception as e:
                codes.append((422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)))
        return (codes == [404, 404]), codes
    soft("没密钥或密钥错送不出打气且不泄露用户名", f_cheer_key)

    def f_pub_total():
        m.rate_reset("cheer:6.6.6.8"); m.rate_reset("pub:6.6.6.8"); m.rate_reset("pub:6.6.6.9")
        m.post_cheer(m.CheerReq(username=uname, k=okk, kind="肌肉在生长"), request=R("6.6.6.8"))
        n = q("SELECT COUNT(*) AS n FROM cheers WHERE user_id=?", (user["id"],))[0]["n"]
        d = m.get_public_dashboard(username=uname, k=okk, request=R("6.6.6.9"))
        return (int(d.get("cheer_total", -1)) == n), "屏上=%s 库里=%s" % (d.get("cheer_total"), n)
    soft("公开大屏读到的打气数就是库里的数", f_pub_total)

    def f_cheer_limit():
        m.rate_reset("cheer:6.6.6.10"); m.rate_reset("pub:6.6.6.10")
        got = []
        for i in range(34):
            try:
                m.post_cheer(m.CheerReq(username=uname, k=okk, kind="饮食超干净"),
                             request=R("6.6.6.10"))
                got.append(200)
            except Exception as e:
                got.append((422 if type(e).__name__=="ValidationError" else getattr(e,"status_code",0)))
        return (got.count(200) >= 5 and 429 in got), "成功 %d 次 / %s" % (got.count(200), got[-3:])
    soft("同一设备狂点会被限流", f_cheer_limit)

    try:
        q("DELETE FROM cheers")
    except Exception:
        pass
    m.rate_reset_all_ask()

    # ============ r127：AI 乱回的根因与闸门 ============
    # 实测（服务器上直接打真必应）：整句中文它不切词，咬开头两个字返回《在外》《练》
    # 这类字典页；"减脂+整句"则永远返回同三篇泛泛减脂科普；"平台期体重不掉"返回
    # 微信公众平台，"黑咖啡"返回网易邮箱。所以联网只能当"有对题命中才允许出现"的
    # 参考，答案本体一律来自本人流水与内置场景库。
    check("场景库存在且覆盖十八个场景", len(getattr(m, "SCENE_RULES", [])) >= 18,
          len(getattr(m, "SCENE_RULES", [])))
    js_terms_sets = set(re.findall(r'q\.includes\("([^"]+)"\)', js_txt))
    srv_terms_sets = set(k for keys, _t in getattr(m, "SCENE_RULES", []) for k in keys)
    # 服务端是权威一份（场景更多），前端本地层只要求是它的子集，不许有服务端没有的词
    check("前端场景词都在服务端里", js_terms_sets <= srv_terms_sets,
          "只在前端: %s" % sorted(js_terms_sets - srv_terms_sets))
    check("场景关键词不许用单字", not [k for k in srv_terms_sets if len(k) < 2],
          sorted(k for k in srv_terms_sets if len(k) < 2))
    check("场景库扩到十八条", len(getattr(m, "SCENE_RULES", [])) >= 18,
          len(getattr(m, "SCENE_RULES", [])))

    probe = []
    m.web_search = lambda query, limit=4: (probe.append(query), [
        {"title": "网易163免费邮箱登录", "snippet": "网易免费邮，你的专业电子邮局",
         "url": "https://mail.163.com", "host": "mail.163.com"},
        {"title": "腾讯视频频道", "snippet": "最新热门电视剧电影综艺在线观看",
         "url": "https://v.qq.com", "host": "v.qq.com"},
        {"title": "喝（汉语文字）_百度百科", "snippet": "喝（拼音：hē）为汉语一级通用规范汉字",
         "url": "https://baike.baidu.com/h", "host": "baike.baidu.com"},
    ])[1]
    reset_ask_limiter(m)
    q("DELETE FROM kb_entries")
    del probe[:]
    a_cof = m.ask(m.AskReq(question="喝黑咖啡会影响减脂吗"), user)
    check("无关结果被闸门全部丢弃不凑答案", a_cof["source"] == "none"
          and "没有一条真正讲到" in a_cof["answer"], a_cof["answer"][:150])
    check("丢弃时点名要的是什么词", "咖啡" in a_cof["answer"], a_cof["answer"][:120])
    check("字典页与邮箱页没进答案", "邮箱" not in a_cof["answer"] and "汉语文字" not in a_cof["answer"],
          a_cof["answer"][:150])

    q("DELETE FROM kb_entries")
    del probe[:]
    reset_ask_limiter(m)   # 前面几条开放题判据把小配额用掉了，这里要真的清空再量
    a_ni = m.ask(m.AskReq(question="嚼口香糖会不会影响减脂"), user)
    # 旧契约是"认不出减脂领域词就压根不联网"；机主要"能像豆包一样随便聊、能联网"，
    # 契约改成：按问题实词试一次联网，但垃圾结果照样不许凑答案，且不许耗尽减脂题配额。
    check("没有领域词也会按实词试联网一次", len(probe) >= 1, probe)
    check("试联网仍不许拿不相干结果凑答案",
          a_ni["source"] in ("none", "web", "web_model", "chat")
          and ("没有一条真正讲到" in a_ni["answer"] or a_ni["source"] != "none"),
          "%s %s" % (a_ni["source"], a_ni["answer"][:120]))
    check("邮箱页与字典页没被塞进这类回答",
          "邮箱" not in a_ni["answer"] and "汉语文字" not in a_ni["answer"], a_ni["answer"][:150])

    del probe[:]
    a_hot = m.ask(m.AskReq(question="在外聚餐吃火锅该怎么点"), user)
    check("火锅聚餐走内置场景库", a_hot["source"] == "scene" and len(probe) == 0,
          "%s probe=%s" % (a_hot["source"], probe))
    check("场景答案给的是可执行要点", "份量" in a_hot["answer"] and "蘸料" in a_hot["answer"],
          a_hot["answer"][:130])
    check("场景层不再贴能量守恒", "能量守恒" not in a_hot["answer"], a_hot["answer"][:130])

    # 场景层不查网，就不该吃每分钟联网配额
    reset_ask_limiter(m)
    q("DELETE FROM kb_entries")
    for _i in range(25):
        m.ask(m.AskReq(question="在外聚餐吃火锅该怎么点"), user)
    del probe[:]
    a_after = m.ask(m.AskReq(question="吃苹果会不会影响减脂"), user)
    check("连问场景不耗尽联网配额", len(probe) == 1 and a_after["source"] != "limited",
          "probe=%d source=%s" % (len(probe), a_after["source"]))

    # 对题结果要留得下来，否则闸门就成了"永远不答"
    m.web_search = lambda query, limit=4: (probe.append(query), [
        {"title": "苹果（蔷薇科苹果属植物的果实）_百度百科",
         "snippet": "苹果是常见水果，含果胶与膳食纤维",
         "url": "https://baike.baidu.com/hg", "host": "baike.baidu.com"},
        {"title": "减脂期吃苹果合适吗", "snippet": "一个苹果约 95 kcal，放在加餐比奶茶合适",
         "url": "https://example.com/x", "host": "example.com"},
    ])[1]
    reset_ask_limiter(m)
    a_keep = m.ask(m.AskReq(question="吃苹果会不会影响减脂"), user)
    check("对题结果能通过闸门", a_keep["source"] in ("web", "web_model", "kb"), a_keep["source"])
    check("查询串是空格分词的词袋", " " in (probe[-1] if probe else ""), probe[-1] if probe else "")
    _dt = list(getattr(m, "DOMAIN_TERMS", []))
    check("词袋里每个词都是领域词",
          bool(_dt) and probe and all(w in _dt + ["减脂", "减肥"] for w in probe[-1].split(" ")),
          (probe[-1] if probe else "") + " 领域词表存在=%s" % bool(_dt))
    q("DELETE FROM kb_entries")

    # r129：104 题评测抓到的落点问题，各钉一条
    probe2 = []
    m.web_search = lambda query, limit=4: (probe2.append(query), [])[1]
    m.rate_reset_all_ask()
    q("DELETE FROM kb_entries")
    for qq, want_src, must in (
        ("我的维持代谢是多少", "data", "维持代谢"),
        ("离目标还要多久", "data", "天"),
        ("我今天喝够水了吗", "data", "杯"),
        ("今天训练消耗多少", "data", "kcal"),
        ("我一共省下多少热量", "data", "kcal"),
        ("早餐来不及吃怎么办", "scene", "实际"),
        ("不吃晚饭能瘦吗", "scene", "跳餐"),
        ("肌肉酸痛还要不要练", "scene", "专业评估"),
        ("每天走一万步有用吗", "scene", "估算"),
        ("啤酒和白酒哪个更容易胖", "scene", "饮酒"),
        ("肌酸值得买吗", "scene", "成分"),
    ):
        r2 = m.ask(m.AskReq(question=qq), user)
        check("评测题「%s」落点与内容都对" % qq[:12],
              r2.get("source") == want_src and must in (r2.get("answer") or ""),
              "%s / %s" % (r2.get("source"), (r2.get("answer") or "")[:70]))
    # 以前被泛词抢走的三条：必须不再被数据层顶掉
    for qq, bad_must in (("希腊酸奶和普通酸奶有什么区别", "运动日"),
                         ("豆腐算优质蛋白吗", "目标：蛋白"),
                         ("生理期能喝奶茶吗", "训练消耗记录")):
        r3 = m.ask(m.AskReq(question=qq), user)
        check("泛词不再抢走「%s」" % qq[:12], bad_must not in (r3.get("answer") or ""),
              "%s / %s" % (r3.get("source"), (r3.get("answer") or "")[:70]))
    check("场景库扩到 23 条以上", len(getattr(m, "SCENE_RULES", [])) >= 23,
          len(getattr(m, "SCENE_RULES", [])))
    check("维持/结束这类泛词不在场景键里",
          "维持" not in [k for ks, _t in m.SCENE_RULES for k in ks]
          and "结束" not in [k for ks, _t in m.SCENE_RULES for k in ks],
          [k for ks, _t in m.SCENE_RULES for k in ks if len(k) <= 2 and k in ("维持", "结束", "糖", "饿")])
    q("DELETE FROM kb_entries")

    # ============ r150：整页跳转、按钮统一、撤回/统计/同城 ============
    _html = read_asset("index.html")
    _fjs = read_asset("features.js")
    _fcss = read_asset("features.css")
    _ajs = read_asset("app.js")
    _all_js = _ajs + "\n" + _fjs

    # 机主清单里的 P0 第 1 条：一个绑了不存在函数的按钮，四套判据全绿地漏了过去。
    # 这道门是整套体系最便宜的补强——静态就能判，不需要跑起来。
    _defined = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)\s*\(', _all_js))
    _defined |= set(re.findall(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:function|\()', _all_js))
    _bound = set(re.findall(r'on(?:click|change|input|submit|keydown|contextmenu|touchstart)="([A-Za-z_$][\w$]*)\s*\(',
                            _html + _fjs + _ajs))
    _dangling = sorted(b for b in _bound if b not in _defined and b != "if")
    check("界面绑的处理函数都能解析到已定义函数（防死按钮）",
          not _dangling and len(_bound) >= 100, {"悬空": _dangling, "绑定数": len(_bound)})
    check("全部标为已读真的接了后端",
          "async function markNoticesRead" in _fjs and '"/api/notifications/read"' in _fjs, "")

    # 弹窗居中：`* { margin:0 }` 会打掉 <dialog> 的 UA 居中，必须显式写回来
    check("弹窗居中而不是贴左上角",
          ".tool-dialog{position:fixed;inset:0;margin:auto;" in _fcss, "")
    check("全局 reset 确实会动 margin（这条红了说明根因变了，要重看居中方案）",
          re.search(r'\*\s*\{\s*\n?\s*margin:\s*0', io.open(os.path.join(ROOT, "app", "src", "main",
                  "assets", "style.css"), encoding="utf-8").read()) is not None, "")

    # 页面层：看内容走整页，返回按钮要在
    check("整页跳转层已挂进页面",
          'id="page-layer"' in _html and 'class="pl-back" onclick="closePage()"' in _html
          and "QS_PAGE_DEF.member" in _fjs and "QS_PAGE_DEF.post" in _fjs
          and "QS_PAGE_DEF.dm" in _fjs and "QS_PAGE_DEF.stats" in _fjs, "")
    check("用户主页与帖子详情不再走弹窗",
          "toolDialog(" not in _fjs.split("async function qsRenderMember")[1][:1600]
          if "async function qsRenderMember" in _fjs else False, "")
    check("切 tab 会收起页面层，不会留一层盖在上面",
          "if (qsPageOpen()) qsCloseAllPages();" in _fjs, "")
    # 换页必须清顶栏槽位：真机截图上出现过"关注列表页头上挂着一颗上一页的私信按钮"
    _top = _fjs.split("function qsRenderTop()")[1].split("function openPage(")[0] \
        if "function qsRenderTop()" in _fjs else ""
    check("换页时清空顶栏右侧槽位与底栏",
          'cmEl("pl-slot")' in _top and "innerHTML = \"\"" in _top, _top[:100])
    # 私信改成整页之后，连接不能再靠"顺手路过消息 tab"拉起，否则从主页点进来就是哑的
    _dm = _fjs.split("async function openDM(uid)")[1].split("async function qsRenderDm")[0] \
        if "async function openDM(uid)" in _fjs else ""
    check("打开私信页会自己发起 WebSocket 连接",
          "connectChat()" in _dm and 'openPage("dm"' in _dm, _dm[:80])

    # 按钮统一：次按钮浅绿底、hover 深绿底、胶囊圆角覆盖到旧类
    _sec = _fcss.split(".td-btn-quiet,.td-mini,.btn-secondary,.btn-outline,.me-copy{")[1].split("}")[0] \
        if ".td-btn-quiet,.td-mini,.btn-secondary,.btn-outline,.me-copy{" in _fcss else ""
    check("次按钮统一浅绿底（原来一半是白板）", "#ECFDF5" in _sec and "#047857" in _sec, _sec[:60])
    def _css_rule(css, selector):
        """把样式表拆成 (选择器, 规则体)，找选择器里含 selector 的那一条。
        多选择器分组、跨行写法都能吃到——用 split("hover{...") 那种字符串截法会漏。"""
        for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            if selector in " ".join(sel.split()):
                return body.strip()
        return ""
    _hov = _css_rule(_fcss, ".btn-secondary:hover")
    check("悬停统一给深绿反馈", "background:#059669" in _hov, _hov[:70])
    check("动作按钮一律胶囊圆角",
          ".btn-secondary,.btn-outline" in _fcss and "border-radius:999px" in _fcss, "")
    check("主按钮仍是渐变（保住主次权重）",
          ".td-btn,.btn-primary" in _fcss and "linear-gradient" in
          _fcss.split(".td-btn,.btn-primary,.btn-log-meal")[1].split("}")[0], "")

    # 文本要能选中复制（机主："对话框不能鼠标复制文本"）
    check("气泡与正文允许选中复制，脱敏自全局 user-select:none",
          ".cm-bubble,.cm-body" in _fcss and "user-select:text" in _fcss, "")

    # 撤回：只有本人、限时、撤完正文不再外发
    check("撤回端点要登录且限时",
          '@app.post("/api/chat/recall")' in srv_txt
          and "只能撤回自己发出的消息" in srv_txt and "RECALL_WINDOW_SEC = 300" in srv_txt, "")
    check("撤回是打标记不是删行，且撤回后不回正文",
          "UPDATE messages SET recalled_at=?" in srv_txt and '"body": "" if recalled else row["body"]' in srv_txt, "")
    check("会话摘要跟着撤回改口",
          "（已撤回）" in srv_txt and "UPDATE conversations SET last_body=?" in srv_txt, "")

    # 统计可点：两个新列表端点 + 同城
    check("粉丝/关注与帖子列表端点在且带总数",
          '@app.get("/api/community/connections")' in srv_txt and '"total": total' in srv_txt
          and '@app.get("/api/community/posts-of")' in srv_txt, "")
    check("同城页签：没有属地时给空而不是给全部",
          '"latest", "follow", "mine", "city"' in srv_txt
          and "还没有你的属地" in srv_txt and 'return {"code": 0, "items": [], "next_cursor": 0, "more": False' in srv_txt, "")
    check("前端也认同城", "latest\", \"follow\", \"mine\", \"city\"" in _fjs.replace("'", '"')
          and 'data-feed="city"' in _html, "")

    # 属地：登录/注册就认，不等发帖
    check("登录与注册都会落一次属地",
          srv_txt.count("touch_region(") >= 3 and "region_touch_failed" in srv_txt, srv_txt.count("touch_region("))
    check("解析不出属地时保留原值，不掉回未知",
          "if not region:" in srv_txt.split("def touch_region")[1][:400], "")

    # 气泡装扮：白名单校验，脏值要拒
    check("气泡颜色走白名单",
          'BUBBLE_THEMES = ("green", "blue", "rose", "ink", "amber")' in
          io.open(os.path.join(ROOT, "app_modules", "community.py"), encoding="utf-8").read()
          and "没有这种气泡颜色" in srv_txt, "")
    check("气泡只改自己一侧，不写进消息本体",
          "recalled_at" in srv_txt and "bubble_theme" in srv_txt
          and 'data-t="' in _fjs and "cm.myTheme" in _fjs, "")

    # ---- 后台上线前置：封号要真的有人执行，密钥不能被后台读到 ----
    def _func_src(text, head):
        seg = text.split(head, 1)[1] if head in text else ""
        cut = re.search(r"\n(?:@app\.|def |class |# )", seg)
        return seg[:cut.start()] if cut else seg

    _gcu = _func_src(srv_txt, "def get_current_user(")
    _login_fn = _func_src(srv_txt, "def login(")
    _ws_fn = _func_src(srv_txt, "async def chat_socket(")
    check("users 用补列方式拿到封号两列（不重建表、不动现有数据）",
          '("banned_at", "TEXT")' in srv_txt and '"ban_reason", "TEXT NOT NULL DEFAULT' in srv_txt, "")
    check("登录态校验里真的判了封号", "banned_at" in _gcu and "AccountBanned" in _gcu, _gcu[:120])
    # 这条是 T-80 的静态那一半：get_current_user 每个 /api/ 请求都跑，多一次查询＝全站多一次锁竞争
    check("封号判定并进已有那条查询，没有多出一次数据库往返",
          _gcu.count("conn.execute(") == 1 and "SELECT u.*" in _gcu,
          "execute 次数=%d" % _gcu.count("conn.execute("))
    check("登录接口也拦封号，且排在口令校验之后（不给免口令可探的信号）",
          "banned_at" in _login_fn and "AccountBanned" in _login_fn
          and _login_fn.find("用户名或密码错误") < _login_fn.find("banned_at"), "")
    check("私信建连也认封号（手里已有票据也连不上，且复用原来那次存在性查询）",
          "SELECT banned_at FROM users WHERE id=?" in _ws_fn and "SELECT 1 FROM users" not in _ws_fn
          and "4403" in _ws_fn, "execute 次数=%d，封号在切片里=%s" % (_ws_fn.count("conn.execute("), "banned_at" in _ws_fn))
    check("封号响应带机器码，前端不拿 403 当凭据",
          '"code": "account_banned"' in srv_txt and "@app.exception_handler(AccountBanned)" in srv_txt, "")
    check("前端认这个机器码并清会话、说清原因",
          'policy.code === "account_banned"' in js_txt and "handleAccountBanned" in js_txt
          and "localStorage.removeItem(TOKEN_KEY)" in js_txt.split("function handleAccountBanned")[1][:300], "")
    check("签名密钥改从 KEY_DIR 取，业务库目录里不再留密钥",
          'os.environ.get("QINGSU_KEY_DIR"' in srv_txt and 'os.path.join(KEY_DIR, name)' in srv_txt
          and 'DB_DIR, "media-signing.key"' not in srv_txt and 'DB_DIR, "ws-secret.key"' not in srv_txt, "")
    check("密钥被新建过要说得出：日志、健康检查两处都留痕",
          "_KEYS_REGENERATED.add(name)" in srv_txt and "key_regenerated" in srv_txt
          and '"regenerated": sorted(_KEYS_REGENERATED)' in srv_txt, "")
    check("健康检查报密钥隔离状态与存在性，但不报内容",
          '"isolated": os.path.abspath(KEY_DIR) != os.path.abspath(DB_DIR)' in srv_txt
          and '"present"' in srv_txt, "")
    # 口径钉住：分享链接走自己的开关，封号不牵连访客页（写清楚是为了下次改动是有意的）
    _share_fn = _func_src(srv_txt, "def check_share(")
    check("分享页不受封号牵连（口径：分享有自己的开关与有效期）",
          "share_secret" in _share_fn and "banned_at" not in _share_fn,
          "切片长度=%d；share_secret 不在里面说明取到的不是 check_share 的函数体，判据在空转" % len(_share_fn))

    # ---- r152：返回手势、帖子编辑、私信左右、评论排版 ----
    check("页面栈接进 history（安卓返回键/侧滑不再直接退出 App）",
          "history.pushState" in _fjs and "popstate" in _fjs
          and "closePage(true)" in _fjs, "")
    check("帖子编辑接口存在且只有作者能改",
          '@app.patch("/api/community/posts/{post_id}")' in srv_txt
          and "只能改自己的帖子" in srv_txt and "SET body=?, edited_at=?" in srv_txt, "")
    check("帖子卡片带 edited_at（前端才能显示已编辑）",
          '"edited_at": row["edited_at"]' in srv_txt, "")
    check("自己/对方的 id 比较用 qsSameId（=== 会把字符串 id 判成别人）",
          "function qsSameId" in _fjs and _fjs.count("qsSameId(") >= 4
          and "m.from_id === me" not in _fjs and "p.author.id === (state.user" not in _fjs, "")
    check("私信气泡整行分侧并带头像",
          "dm-row" in _fjs and "dm-avatar" in _fjs and ".dm-row.me{justify-content:flex-end}" in _fcss, "")
    check("对方气泡不再和聊天背景同色（截图里像没有气泡）",
          ".cm-bubble.them{background:#fff" in _fcss and ".cm-bubbles.page{background:#EDEDED" in _fcss, "")
    check("评论改成小红书式的小号文字操作",
          "pd-cmt-meta" in _fjs and "pd-cmt-act" in _fjs and ".pd-cmt-meta{" in _fcss
          and "class=\"pd-reply\"" not in _fjs, "")
    # ---- r153：按钮语言与遮挡收口 ----
    check("弹窗按钮与页面按钮同一套胶囊（不再一套 12px 一套 999px）",
          ".tool-dialog button,.account-tools button,#public-view button{border-radius:999px}" in _fcss, "")
    check("次级动作按钮也统一胶囊",
          ".td-btn,.td-btn-quiet,.td-mini,.me-copy" in _fcss and "border-radius:999px" in _fcss, "")
    check("头像选择不再露原生 file 控件",
          "file-hidden" in _fjs and "qsPickAvatarName" in _fjs
          and '<input type="file" id="avatar-file" accept="image/*" class="file-hidden"' in _fjs, "")
    check("手机窄屏不再有悬浮下载压住卡片",
          "@media (max-width:760px){ #floating-dl-btn{display:none !important} }" in _fcss, "")
    check("『已开启』不再用危险红",
          'badge.dataset.tone = disc ? "on" : "off"' in _fjs
          and '.td-badge[data-tone="on"]{background:#ECFDF5;color:#047857}' in _fcss, "")
    check("切 tab 会把当前页写到 body（窄屏规则据此生效）",
          'document.body.setAttribute("data-tab", tabName || "")' in js_txt, "")
    check("详情页能就地编辑帖子（patchJson + 保存）",
          "async function patchJson" in _fjs and "function editPostFromDetail" in _fjs
          and "async function savePostEdit" in _fjs, "")
    # ---- r154：收藏、帖子搜索、举报 ----
    _fav_ddl = ""
    if "CREATE TABLE IF NOT EXISTS post_favorites" in srv_txt:
        _fav_ddl = srv_txt[srv_txt.index("CREATE TABLE IF NOT EXISTS post_favorites"):][:320]
    check("收藏用独立表，同一人同一帖只能一行",
          "CREATE TABLE IF NOT EXISTS post_favorites" in _fav_ddl
          and "PRIMARY KEY(post_id, user_id)" in _fav_ddl
          and "FOREIGN KEY(post_id) REFERENCES posts(id)" in _fav_ddl, _fav_ddl[:120])
    check("帖子卡片带收藏态与收藏数（前端据此点亮星标）",
          '"favorited_by_me": bool(' in srv_txt and '"favorite_count": int(' in srv_txt, "")
    check("收藏开关是接口不是本地状态",
          '@app.post("/api/community/posts/{post_id}/favorite")' in srv_txt
          and "INSERT OR IGNORE INTO post_favorites" in srv_txt
          and "DELETE FROM post_favorites WHERE post_id=? AND user_id=?" in srv_txt, "")
    check("我的收藏按帖子游标分页，已删除的帖子不出现",
          '@app.get("/api/community/favorites")' in srv_txt
          and "JOIN post_favorites f ON f.post_id=p.id" in srv_txt
          and "p.status='open'" in srv_txt, "")
    check("搜索同时返回人和帖子，前端两段都渲染",
          "posts = conn.execute(" in srv_txt and '"posts": [_post_card' in srv_txt
          and "r.posts" in _fjs, "")
    check("前端星标可点且状态跟着接口走",
          "async function toggleFavorite" in _fjs and "favorited_by_me" in _fjs
          and 'aria-pressed="' in _fjs, "")
    check("前端有『我的收藏』页并从接口读",
          "QS_PAGE_DEF.favorites" in _fjs and "async function qsRenderFavorites" in _fjs
          and "/api/community/favorites?limit=12" in _fjs, "")
    check("举报弹窗有理由选择与备注，提交走真实接口",
          'id="report-dialog"' in _html and "report-reasons" in _html
          and "async function submitReport" in _fjs and "/api/community/report" in _fjs, "")
    check("自己的帖子不显示举报按钮（举报自己没有意义）",
          '(mine ? "" : ' in _fjs and "openReport(&#39;post&#39;" in _fjs, "")
    # ---- r155：帖子操作行与弹窗按钮收口 ----
    check("帖子操作行允许换行，不再挤出卡片",
          ".pd-acts{display:flex;align-items:center;flex-wrap:wrap" in _fcss, "")
    check("编辑/删除等次级动作在 DOM 里收成一组",
          "pd-acts-extra" in _fjs, "")
    check("次级动作整组换行后靠右，不单独一颗掉在行首",
          ".pd-acts-extra{display:flex;align-items:center;gap:8px;margin-left:auto}" in _fcss, "")
    check("弹窗动作区允许换行并右对齐",
          ".td-actions{display:flex;flex-wrap:wrap;justify-content:flex-end" in _fcss, "")
    check("弹窗动作按钮按内容收窄（不再 flex:1 拉成整行巨块）",
          ".td-actions>.td-btn,.td-actions>.td-btn-quiet,.td-actions>.td-btn-danger{flex:0 1 auto;min-width:88px;min-height:40px" in _fcss, "")
    check("文件选择行里的按钮也是紧凑尺寸",
          ".td-file-line .td-btn{flex:0 0 auto;min-width:0;min-height:36px" in _fcss, "")
    check("上传头像并进文件选择行，不再单独占一整行",
          "td-file-upload" in _fjs and "td-file-line" in _fjs
          and '<div class="td-actions"><button type="button" class="td-btn" onclick="uploadAvatar()">上传头像</button></div>' not in _fjs, "")
    check("窄屏评论占位文案不再被截断",
          '"友善一点，好好说话"' in _fjs and len("友善一点，好好说话") <= 10, "")
    # ---- r157：私聊图片/视频/表情 ----
    def _repo_file(rel):
        """仓库里的文件也要跟着 --mutant 走：磁盘直读会让旧版反样本永远绿，
        等于判据从来没被标定过（r157 的 nginx 那条一开始就栽在这）。"""
        if not mutant:
            return io.open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
        r = subprocess.run(["git", "show", MUT_REF + ":" + rel], cwd=ROOT, capture_output=True)
        return r.stdout.decode("utf-8") if r.returncode == 0 else ""

    check("私信消息表能区分文字/表情/图片/视频",
          '("kind", "TEXT NOT NULL DEFAULT \'text\'")' in srv_txt
          and '("media_name", "TEXT NOT NULL DEFAULT \'\'")' in srv_txt, "")
    check("图片/视频上传接口只对互关开放",
          '@app.post("/api/chat/media")' in srv_txt
          and '互相关注后才能发图片和视频' in srv_txt
          and 'def mutual_follow(' in srv_txt
          and "mutual_follow(conn, user[\"id\"], int(to))" in srv_txt, "")
    check("发送媒体时服务端再查一次互关与文件归属",
          'if not owned or not os.path.isfile' in srv_txt
          and '这个媒体不是你刚上传的' in srv_txt, "")
    check("图片重编码、视频只收 MP4/WebM 且限 30MB",
          'DM_IMAGE_MAX = 8 * 1024 * 1024' in srv_txt and 'DM_VIDEO_MAX = 30 * 1024 * 1024' in srv_txt
          and 'head[4:8] == b"ftyp"' in srv_txt and 'head.startswith(b"\\x1aE\\xdf\\xa3")' in srv_txt, "")
    check("媒体消息读取时重新签短时 URL",
          '"media_url": signed_photo(' in srv_txt and '"media_mime":' in srv_txt, "")
    check("上传路由能放行视频并带正确 MIME",
          'jpg|jpeg|png|webp|mp4|webm' in srv_txt and 'mimetypes.guess_type(name)' in srv_txt, "")
    check("私信回执带 mutual_follow，前端才知道该不该亮图片按钮",
          'partner["mutual_follow"] = mutual_follow(' in srv_txt, "")
    check("前端有表情面板与更多面板（相册/拍照/视频/常用语）",
          "dm-emoji-panel" in _fjs and "dm-plus-panel" in _fjs and "DM_PHRASES" in _fjs
          and "dm-image-file" in _fjs and "dm-camera-file" in _fjs and "dm-video-file" in _fjs, "")
    check("未互关时图片/视频按钮禁用并给文案",
          '互相关注后才能发图片和视频' in _fjs and '!canMedia' in _fjs, "")
    check("图片/视频/表情各有自己的气泡样式",
          "dm-media-img" in _fjs and "dm-media-video" in _fjs and "dm-sticker" in _fjs
          and ".cm-bubble.media" in _fcss and ".cm-bubble .dm-sticker" in _fcss, "")
    check("nginx 上传上限容得下 30MB 视频",
          "client_max_body_size 40m;" in _repo_file("scripts/qingsu-tls.conf"), "")
    # ---- r158：更新弹窗排版与说明文字 ----
    _vj = _repo_file("make_version_json.py")
    check("更新说明去 Markdown 记号（弹窗里不许出现 ** 和反引号）",
          'def _plain(' in _vj and 'text.replace("**", "").replace("`", "")' in _vj, "")
    check("更新说明只取当前版，且不夹带验收/判据这些内部话",
          'internal = ("消息存法", "判据", "验收方式"' in _vj
          and "bullets = [b for b in bullets if not any(word in b for word in internal)]" in _vj, "")
    _up = _repo_file("app/src/main/java/com/fitcoach/shapemaster/UpdateManager.java")
    check("更新弹窗改用自定义正文（有行距与字号，不再是一坨默认小字）",
          "setView(body)" in _up and "COMPLEX_UNIT_SP, 15f" in _up
          and "setLineSpacing(" in _up, "")
    check("更新弹窗不硬编没量过的下载速度",
          "0.33 MB/s" not in _up and "UpdateCopy.body(" in _up, "")
    check("弹窗文案抽成纯 Java 类，能脱离 Android 运行时真跑",
          "class UpdateCopy" in _repo_file("app/src/main/java/com/fitcoach/shapemaster/UpdateCopy.java")
          and os.path.isfile(os.path.join(ROOT, "tests", "test_update_copy.py")), "")
    check("更新弹窗正文不重复标题里的版本号",
          'matches("^r\\\\d+\\\\s*/.*")' in _repo_file("app/src/main/java/com/fitcoach/shapemaster/UpdateCopy.java"),
          "")
    check("更新弹窗不再用默认 setMessage 塞整段说明", ".setMessage(" not in _up, _up[:120])
    check("更新说明按要点分行（一条一行，不是一整段）",
          'parts.extend("• " + b for b in bullets' in _vj, "")

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
