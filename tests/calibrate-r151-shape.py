"""一次性标定：证明两条"形状判据"在真的改坏时会咬。
不修改工作区文件，只在内存里变异，跑完即弃。"""
import io, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
js = io.open(os.path.join(ROOT, "app", "src", "main", "assets", "app.js"), encoding="utf-8").read()


def func_src(text, head):
    seg = text.split(head, 1)[1]
    cut = re.search(r"\n(?:@app\.|def |class |# )", seg)
    return seg[:cut.start()] if cut else seg


gcu = func_src(src, "def get_current_user(")
share = func_src(src, "def check_share(")
hits = []

# 正样本：现在的源码必须是绿的
hits.append(("正样本：热路径判据在现役源码上为绿", gcu.count("conn.execute(") == 1 and "SELECT u.*" in gcu))
hits.append(("正样本：分享页判据在现役源码上为绿", "share_secret" in share and "banned_at" not in share))
# 下面两条也是"必须为绿"的对照（证明变异没把整个判据一起废掉）：
hits.append(("正样本：封号判定确实在 get_current_user 里", "banned_at" in gcu and "AccountBanned" in gcu))
hits.append(("正样本：机器码确实在响应里", '"code": "account_banned"' in src))

# µA：给封号判定另开一次查询（T-80 要抓的形状）
mut_a = src.replace('    if row["banned_at"]:\n        raise AccountBanned(row["ban_reason"])',
                    '    extra = conn.execute("SELECT banned_at FROM users WHERE id=?", (row["id"],)).fetchone()\n'
                    '    if extra["banned_at"]:\n        raise AccountBanned(extra["ban_reason"])')
assert mut_a != src, "µA 没变异成功，标定结论无效"
seg_a = func_src(mut_a, "def get_current_user(")
hits.append(("µA 加了第二次查询 → 热路径判据必须红", not (seg_a.count("conn.execute(") == 1 and "SELECT u.*" in seg_a)))

# µB：把封号判断塞进分享页（口径漂移）
mut_b = src.replace('    if not user or not key or key != (user["share_secret"] or ""):\n        return None',
                    '    if not user or not key or key != (user["share_secret"] or ""):\n        return None\n'
                    '    if user["banned_at"]:\n        return None')
assert mut_b != src, "µB 没变异成功，标定结论无效"
seg_b = func_src(mut_b, "def check_share(")
hits.append(("µB 分享页开始判封号 → 口径判据必须红", not ("share_secret" in seg_b and "banned_at" not in seg_b)))

# µC：封号响应漏掉机器码（前端只能拿 403 猜）
mut_c = src.replace('return JSONResponse({"detail": exc.detail, "code": "account_banned"}, status_code=403)',
                    'return JSONResponse({"detail": exc.detail}, status_code=403)')
assert mut_c != src, "µC 没变异成功，标定结论无效"
hits.append(("µC 响应去掉 code → 机器码判据必须红",
             not ('"code": "account_banned"' in mut_c and "@app.exception_handler(AccountBanned)" in mut_c)))

# µD：前端把普通 403 也当封号清会话
mut_d = js.replace('else if (policy && policy.code === "account_banned") handleAccountBanned(policy.detail);',
                   'else handleAccountBanned(policy.detail);')
assert mut_d != js, "µD 没变异成功，标定结论无效"
hits.append(("µD 前端不看 code → 对照判据的写法必须能区分（源码里仍要求带 code 的分支）",
             'policy.code === "account_banned"' not in mut_d))

# µE：把封号判定挪到口令校验之前 → "这个用户名被封过"就成了免口令可探的信号
ban_block = ('    # 封号判定放在口令校验之后：先判就会让"这个用户名被封过"变成免口令可探的信号，\n'
             '    # 和上面刻意不区分"不存在/密码错"的口径冲突。只有本人（持正确口令）才看得到原因。\n'
             '    if user["banned_at"]:\n        conn.close()\n        raise AccountBanned(user["ban_reason"])\n\n')
assert ban_block in src, "µE 锚文本没找到，标定结论无效"
mut_e = src.replace(ban_block, "")
cut = mut_e.find('        raise HTTPException(status_code=400, detail="用户名或密码错误")')
assert cut > 0, "µE 找不到口令失败那条"
mut_e = mut_e[:cut] + ban_block + mut_e[cut:]
seg_e = func_src(mut_e, "def login(")
hits.append(("µE 封号判定挪到口令之前 → 顺序判据必须红",
             not ("banned_at" in seg_e and "AccountBanned" in seg_e
                  and seg_e.find("用户名或密码错误") < seg_e.find("banned_at"))))

bad = 0
for name, ok in hits:
    # 这里的"有效"含义：正样本那条确实为绿；µ 那条确实因为变异而翻红（断言写的是 not(...)，所以 ok=True 才代表咬住了）
    print("%s %s" % ("有效" if ok else "失效", name))
    bad += 0 if ok else 1
# 结构：4 条正样本 + 5 条变异样本，全部都要"有效"；有一条失效就说明对应判据形同虚设
print("标定：%d/%d 条有效，失效 %d 条" % (len(hits) - bad, len(hits), bad))
sys.exit(0 if bad == 0 and len(hits) == 9 else 1)
