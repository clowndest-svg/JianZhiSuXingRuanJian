"""按显式 id 清掉测试账号，连所有会因此变成孤儿的行一起删，删前删后都留证据。

为什么不用"所有含 user_id 的列"这一条规则扫：社区那批表里
follows(follower_id/followee_id)、messages(from_id/to_id)、user_blocks(blocker/blocked)、
content_reports(reporter) 都不叫 user_id，漏一张就会外键报错，或者更糟——留下孤儿行。

为什么要连"他的帖子 → 帖子下的评论 → 评论上的点赞/@ "这条链一起算：删一个人时，他帖子下
**别人**写的评论、别人给他评论点的赞，都不带他的 user_id，只按用户列扫根本扫不到；留着它们，
commit 时外键会把整笔删除顶回去（r154 在后台删号时就是这么 500 的）。所以先把"他的帖子"和
"他帖子下的评论"算成两个临时集合，再按 user / post / comment 三类引用列一起判。

id 一律先 int() 过再拼进 SQL（不用 ? 占位符）：一张表可能有两个用户列，
占位符个数就翻倍，execute 时少带一组直接 ProgrammingError——预演跑不起来等于这脚本从没验过。

用法：
    python3 scripts/purge-users.py --ids 184,185            # 先看
    python3 scripts/purge-users.py --ids 184,185 --apply     # 再删
"""
import argparse
import json
import sqlite3
import sys

# 只有这种命名的账号才是自动化夹具建的；不匹配就得 --force，防手滑删真人的号
FIXTURE_PATTERN = ("uqa", "usbqa", "releasecheck_", "layprobe", "aitest", "selftest")

# 有些表没写 FOREIGN KEY（notifications、follows 这类），只能按列名认
USERISH = ("user_id", "follower_id", "followee_id", "from_id", "to_id",
           "blocker", "blocked", "reporter", "actor_id", "a_id", "b_id",
           "last_from", "owner_id")


def all_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]


def ref_columns(conn):
    """{表: {"user": [...], "post": [...], "comment": [...]}}，外键现读 + 常见列名兜底。"""
    out = {}
    for table in all_tables(conn):
        cols = {c[1] for c in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        by_parent = {}
        for fk in conn.execute("PRAGMA foreign_key_list(%s)" % table).fetchall():
            by_parent.setdefault(fk[2], set()).add(fk[3])
        out[table] = {
            "user": sorted(by_parent.get("users", set()) | {c for c in cols if c in USERISH}),
            "post": sorted(by_parent.get("posts", set()) | {c for c in cols if c == "post_id"}),
            "comment": sorted(by_parent.get("comments", set()) | {c for c in cols if c == "comment_id"}),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/opt/qingsu/data/qingsu.db")
    ap.add_argument("--ids", required=True, help="逗号分隔的用户 id，必须显式给")
    ap.add_argument("--apply", action="store_true", help="不加这个参数只报告不删")
    ap.add_argument("--force", action="store_true", help="允许删非夹具命名的账号")
    args = ap.parse_args()

    ids = sorted({int(x) for x in args.ids.split(",") if x.strip()})
    if not ids:
        raise SystemExit("没给 id，拒绝执行")
    ph = ",".join(str(i) for i in ids)   # 已经是 int，拼进 SQL 没有注入面
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT id, username FROM users WHERE id IN (%s)" % ph).fetchall()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise SystemExit("这些 id 不在库里，说明清单和库不一致：%s" % missing)
    if not args.force:
        bad = [i for i, n in rows.items() if not n.startswith(FIXTURE_PATTERN)]
        if bad:
            raise SystemExit("这些账号不像测试夹具，要删请加 --force：%s" % bad)

    # 他的帖子、他帖子下的评论（含别人写的）。comments 不引用 comments，帖子集合不会因
    # 收了新评论再长大，所以两轮一定收敛——写成循环是为了以后加"评论引用评论"也不用改这里。
    conn.execute("CREATE TEMP TABLE _dp(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE _dc(id INTEGER PRIMARY KEY)")
    conn.execute("INSERT OR IGNORE INTO _dp SELECT id FROM posts WHERE user_id IN (%s)" % ph)
    for _ in range(2):
        conn.execute("INSERT OR IGNORE INTO _dc SELECT id FROM comments "
                     "WHERE user_id IN (%s) OR post_id IN (SELECT id FROM _dp)" % ph)

    specs = {t: s for t, s in ref_columns(conn).items()
             if t != "users" and (s["user"] or s["post"] or s["comment"])}

    def predicate(spec):
        # 一张表可能有好几个指向同一父表的列（messages 的 from_id/to_id、mentions 的
        # user_id/actor_id）。按列分别数会把同一行数好几遍，"任一列命中"才是真实行数。
        parts = []
        if spec["user"]:
            parts.append("(" + " OR ".join("%s IN (%s)" % (c, ph) for c in spec["user"]) + ")")
        if spec["post"]:
            parts.append("(" + " OR ".join("%s IN (SELECT id FROM _dp)" % c for c in spec["post"]) + ")")
        if spec["comment"]:
            parts.append("(" + " OR ".join("%s IN (SELECT id FROM _dc)" % c for c in spec["comment"]) + ")")
        return " OR ".join(parts)

    plans = {t: predicate(s) for t, s in specs.items()}
    before = {t: conn.execute("SELECT COUNT(*) FROM %s WHERE %s" % (t, w)).fetchone()[0]
              for t, w in plans.items()}
    keep_before = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in plans}
    print(json.dumps({"将删除的账号": rows,
                      "他的帖子数": conn.execute("SELECT COUNT(*) FROM _dp").fetchone()[0],
                      "要收回的评论数": conn.execute("SELECT COUNT(*) FROM _dc").fetchone()[0],
                      "各表行数": {k: v for k, v in before.items() if v},
                      "合计子表行": sum(before.values())}, ensure_ascii=False))
    if not args.apply:
        print("预演模式，什么都没删。确认无误再加 --apply")
        return 0

    # 删除顺序天然会撞外键：清 posts 的时候 comments 还指着它。把外键检查推到 commit——
    # 整个事务跑完仍然自洽才落盘，不自洽就整笔回滚，不会留下"删了一半"的库。
    conn.execute("PRAGMA defer_foreign_keys=ON")
    for table, where in plans.items():
        conn.execute("DELETE FROM %s WHERE %s" % (table, where))
    conn.execute("DELETE FROM users WHERE id IN (%s)" % ph)
    try:
        conn.commit()
    except sqlite3.IntegrityError as error:
        conn.rollback()
        raise SystemExit("删完不自洽，整笔已回滚（库里一行没动）：%s" % error)

    left = [r[0] for r in conn.execute("SELECT id FROM users ORDER BY id").fetchall()]
    orphans = {}
    for table, spec in specs.items():
        for kind, parent in (("user", "users"), ("post", "posts"), ("comment", "comments")):
            for col in spec[kind]:
                n = conn.execute("SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND %s NOT IN "
                                 "(SELECT id FROM %s)" % (table, col, col, parent)).fetchone()[0]
                if n:
                    orphans["%s.%s" % (table, col)] = n
    keep_after = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in keep_before}
    leaked = {t: (keep_before[t], keep_after[t], before[t]) for t in keep_before
              if keep_before[t] - keep_after[t] != before[t]}
    print(json.dumps({
        "剩余账号": left,
        "孤儿行": orphans,
        "foreign_key_check": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "删掉的行数与逐表对不上": leaked,
    }, ensure_ascii=False))
    conn.close()
    return 0 if not orphans else 1


if __name__ == "__main__":
    sys.exit(main())
