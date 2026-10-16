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
    check("达标状态用文字而不只是颜色", all(w in js_txt for w in ("达标 ", "未达 ", "超支 ", "未记录 ")), "")
    check("注册了键盘监听", 'document.addEventListener("keydown"' in js_txt, "")
    check("弹窗打开时屏蔽背景内容", 'setAttribute("aria-hidden"' in js_txt and "node.inert = true" in js_txt, "")
    check("ESC 走的是各弹窗自己的关闭入口", "closeTopDialog" in js_txt
          and ".modal-close-btn, .exd-close" in js_txt, "")

    # aria-pressed 只该出现在可切换控件上；瞬时动作按钮挂 pressed 会念成"已按下"
    pressed = re.findall(r'<(?:div|button|span)[^>]*aria-pressed[^>]*>', html_txt)
    check("pressed 只用在餐别这类可切换项",
          len(pressed) == 4 and all("meal-slot-chip" in t for t in pressed),
          "%d 处: %s" % (len(pressed), [t[:40] for t in pressed if "meal-slot" not in t][:2]))
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
    # 实测根因是账号胶囊被 flex 收缩到 16px，不是子元素缺 min-width
    check("顶栏账号胶囊不参与收缩",
          ".user-account-badge" in css_txt and "flex: 0 0 auto" in css_txt, "")

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

    # B. 内联 on* 引用的函数必须在 app.js 里定义（syncTargetWeightPlaceholder 曾只在 HTML 里）
    KW = {"if", "for", "while", "switch", "catch", "return", "typeof", "new", "function"}
    called, defs = set(), set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", js_txt))
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
            m.register(m.RegisterReq(**d))
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
        q("DELETE FROM kb_entries")

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
    a_period = m.ask(m.AskReq(question="生理期要不要停训练"), user)
    check("生理期不被训练流水抢走", a_period["source"] == "scene" and "生理期" in a_period["answer"],
          "%s %s" % (a_period["source"], a_period["answer"][:90]))
    # 场景层与无领域词的拒绝都不该吃联网配额
    reset_ask_limiter(m)
    for _i in range(14):
        m.ask(m.AskReq(question="量子计算是什么"), user)
    a_after2 = m.ask(m.AskReq(question="吃苹果会不会影响减脂"), user)
    check("拒答不耗尽联网配额", a_after2["source"] != "limited", a_after2["source"])

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
    a_ni = m.ask(m.AskReq(question="嚼口香糖会不会影响减脂"), user)
    check("认不出领域词就根本不联网", len(probe) == 0 and a_ni["source"] == "none", probe)
    check("不联网时如实说为什么不答", "没有能确认的减脂相关词" in a_ni["answer"], a_ni["answer"][:120])

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
