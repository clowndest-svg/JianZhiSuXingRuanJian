#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 问答全量测试：打真实后端、真实模型、真实必应，不用任何桩。

跑在服务器上（走 127.0.0.1:8000），因为它要能停/起 qingsu-llama 来验证兜底，
也要能直接读库核对"答案里的数字是不是本人真数据"。
"""
import json
import re
import statistics
import subprocess
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
DB = "/opt/qingsu/data/qingsu.db"

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print("  %s %s%s" % ("绿" if cond else "红", name, "" if cond else "  -> " + str(detail)[:150]))


def api(path, body=None, token=None, method=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"err": "%s: %s" % (type(e).__name__, e)}


def ask(q, token):
    code, d = api("/api/ask", {"question": q}, token)
    return code, d


def plain(h):
    return re.sub(r"<[^>]+>", " ", h or "")


# ============ 建两个真实账号（测隔离要用两个） ============
BODY = {"password": "T3stPass!", "gender": "female", "age": 29, "height": 168,
        "weight_jin": 151, "target_weight_jin": 132, "goal_type": "female_hourglass",
        "dining_mode": "takeout"}
code, a = api("/api/register", dict(BODY, username="aitest_main"))
tok = a.get("token", "")
code2, b = api("/api/register", dict(BODY, username="aitest_other"))
tok2 = b.get("token", "")
print("=== 建号 ===")
ok("两个测试账号注册成功", bool(tok) and bool(tok2), (a.get("detail") or b.get("detail") or ""))

# 记一条真实摄入，让"吃多了"这类问题有真数字可答
api("/api/food/log", {"slot": "午餐", "food_name": "牛肉面加蛋", "cal": 620}, tok)

print("=== 1. 数据类问题必须走本人流水，且数字来自真实记录 ===")
DIGEST = {"151": 0, "132": 0, "168": 0, "29": 0, "620": 0}
code, d = ask("我多重", tok)
ok("体重问题 source=data", d.get("source") == "data", d.get("source"))
ok("体重答案含真实 151 斤", "151" in plain(d.get("answer", "")), plain(d.get("answer", ""))[:80])
code, d = ask("今天还剩多少额度", tok)
ok("额度问题 source=data", d.get("source") == "data", d.get("source"))
code, d = ask("中午吃多了晚上怎么自适应补救？", tok)
txt = plain(d.get("answer", ""))
ok("吃多了走本人数据层", d.get("source") == "data", d.get("source"))
ok("吃多了答案提到真实摄入 620", "620" in txt, txt[:120])
# 原判据是"答案里不许出现三位以上数字"，误伤了正确行为：934 是按真实身高体重
# 算出来的合法热量。改成钉真正会伤人的那类——带斤字的体重数必须等于档案真值。
_c, dctx = api("/api/ai/context", None, tok)
dg = dctx.get('digest', {})
real_jin = set()
for key in ('weight_jin', 'target_jin'):
    v = dg.get(key)
    if v is not None:
        real_jin.add(str(v))
        try:
            real_jin.add(str(int(round(float(v)))))
        except Exception:
            pass
jin = re.findall(r'(\d+(?:\.\d+)?)\s*斤', txt)
fake_jin = sorted(set(x for x in jin if x not in real_jin))
ok('答案里带斤字的数都等于本人真值', not fake_jin,
   {'答案': jin, '真值': sorted(real_jin), '可疑': fake_jin})
ok('目标体重仍是本人填的那个数', str(dg.get('target_jin')) in ('132.0', '132'), dg.get('target_jin'))

print("=== 2. 联网类：不许再吐字典页 ===")
DICT_HINTS = ["汉语词语", "汉语文字", "的意思,", "拼音", "部首", "笔顺", "解释,"]
QS = ["喝黑咖啡会影响减脂吗", "晚上几点以后吃东西会胖", "不吃晚饭能瘦吗",
      "平台期怎么突破", "喝水真的能提高代谢吗", "无糖可乐能喝吗"]
bad, lat, srcs = [], [], []
for q in QS:
    c0, d0 = ask(q, tok)
    t = plain(d0.get("answer", ""))
    srcs.append(d0.get("source"))
    lat.append(d0.get("_ms", 0))
    hit = [k for k in DICT_HINTS if k in t]
    if hit or d0.get("source") in ("none",):
        bad.append((q, d0.get("source"), hit, t[:60]))
ok("六个联网问题都没落到字典页/没查到", not bad, bad)
print("     source 分布:", json.dumps({s: srcs.count(s) for s in set(srcs)}, ensure_ascii=False))

print("=== 3. 长期记忆：写入/回读/隔离/清空 ===")
c0, d0 = ask("记住我不吃香菜和动物内脏", tok)
ok("写入记忆", "不吃香菜" in plain(d0.get("answer", "")), d0.get("source"))
c0, d0 = ask("你记得我什么", tok)
ok("本人能回读", "香菜" in plain(d0.get("answer", "")), plain(d0.get("answer", ""))[:60])
c0, d0 = ask("你记得我什么", tok2)
ok("另一个用户查不到（隔离）", "香菜" not in plain(d0.get("answer", "")), plain(d0.get("answer", ""))[:60])
c0, d0 = api("/api/ai/memory", {"forget_all": True}, tok)
ok("可一键清空", d0.get("cleared", 0) >= 1 and not d0.get("memory"), d0)

print("=== 4. 知识库共用与回写 ===")
c0, d0 = api("/api/ai/context", None, tok)
ok("context 给出真实摘要", str(d0.get("digest", {}).get("weight_jin")) == "151.0"
   or d0.get("digest", {}).get("weight_jin") == 151, d0.get("digest"))
c0, d0 = api("/api/ai/record", {"question": "嚼口香糖会影响减脂吗",
                                "answer": "没有直接证据表明嚼口香糖影响减脂。",
                                "sources": [{"title": "示例", "url": "https://example.com/x",
                                             "host": "example.com"}]}, tok)
ok("本机引擎可回写共享知识库", d0.get("stored") is True, d0)
c0, d0 = ask("嚼口香糖会影响减脂吗", tok2)
ok("另一账号也能命中同一知识库", d0.get("source") == "kb", d0.get("source"))
c0, d0 = api("/api/ai/record", {"question": "x", "answer": ""}, tok)
ok("空答案拒绝回写", c0 == 400, c0)

print("=== 5. 引擎状态与兜底（真停模型再测） ===")
c0, d0 = api("/api/ai/status", None, tok)
ok("状态接口报服务器模型在线", d0.get("server_model") == "up", d0)
ok("状态接口报 Redis 在线", d0.get("redis") == "up", d0)
subprocess.call(["systemctl", "stop", "qingsu-llama"])
import time
time.sleep(2)
c0, d0 = ask("睡前吃东西会胖吗", tok)
t = plain(d0.get("answer", ""))
ok("模型停了仍能答", c0 == 200 and bool(t), c0)
ok("模型停了要承认是摘录并给原因", ("本机模型未运行" in t) or ("资料不足" in t)
   or d0.get("source") == "data", t[:130])
c0, d0 = api("/api/ai/status", None, tok)
ok("状态接口如实报模型离线", d0.get("server_model") == "down", d0)
subprocess.call(["systemctl", "start", "qingsu-llama"])
for _ in range(30):
    time.sleep(2)
    c0, d0 = api("/api/ai/status", None, tok)
    if d0.get("server_model") == "up":
        break
ok("模型恢复后状态回到在线", d0.get("server_model") == "up", d0)

print("=== 6. 边界与注入 ===")
c0, d0 = ask("", tok)
ok("空问题返回 400", c0 == 400, c0)
c0, d0 = ask("<img src=x onerror=alert(1)>", tok)
t = plain(d0.get("answer", ""))
ok("注入载荷不被原样回显", "<img src=x" not in (d0.get("answer") or ""), t[:80])
c0, d0 = ask("啊" * 400, tok)
ok("超长问题被截断而非报错", c0 == 200, c0)
c0, d0 = api("/api/ai/context", None, None)
ok("未登录取不到上下文", c0 in (401, 403), c0)

print("=== 7. 限流真的生效（且计数在 Redis） ===")
blocked = False
for i in range(16):
    c0, d0 = ask("问题%d 减脂" % i, tok2)
    if d0.get("source") == "limited":
        blocked = True
        break
ok("连问 16 次触发限流", blocked, d0.get("source"))

print("=== 清理 ===")
subprocess.call(["sqlite3", DB,
                 "DELETE FROM ai_memory WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM kb_entries;"
                 "DELETE FROM food_logs WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM weight_logs WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM workout_logs WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM water_logs WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM body_cycles WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM checklist_state WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM takeout_events WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM profiles WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'aitest%');"
                 "DELETE FROM users WHERE username LIKE 'aitest%';"])
out = subprocess.check_output(["sqlite3", DB, "SELECT count(*) FROM users;"], text=True).strip()
ok("测试账号已清干净，真实用户数不变", out == "2", "users=" + out)

print("\n=== 汇总：绿 %d，红 %d ===" % (len(PASS), len(FAIL)))
for n, d in FAIL:
    print("   红 %s -> %s" % (n, str(d)[:140]))
raise SystemExit(1 if FAIL else 0)
