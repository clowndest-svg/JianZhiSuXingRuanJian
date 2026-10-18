"""按显式 id 清掉测试账号，连所有指向 users 的子表一起删，删前删后都留证据。

为什么不用"所有含 user_id 的列"这一条规则扫：社区那批表里
follows(follower_id/followee_id)、messages(from_id/to_id)、user_blocks(blocker/blocked)、
content_reports(reporter) 都不叫 user_id，漏一张就会外键报错，或者更糟——留下孤儿行。
这里改成从建表语句里的 FOREIGN KEY ... REFERENCES users 现读。

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


def user_refs(conn):
    """所有外键指向 users 的 (表, 列)；顺带把常见的用户列名也收进来。"""
    pairs = []
    for table in [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]:
        cols = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        fks = conn.execute("PRAGMA foreign_key_list(%s)" % table).fetchall()
        wanted = {fk[3] for fk in fks if fk[2] == "users"}
        wanted |= {c[1] for c in cols if c[1] in (
            "user_id", "follower_id", "followee_id", "from_id", "to_id",
            "blocker", "blocked", "reporter", "actor_id", "a_id", "b_id",
            "last_from", "owner_id")}
        for col in sorted(wanted):
            pairs.append((table, col))
    return pairs


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
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT id, username FROM users WHERE id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise SystemExit("这些 id 不在库里，说明清单和库不一致：%s" % missing)
    if not args.force:
        bad = [i for i, n in rows.items() if not n.startswith(FIXTURE_PATTERN)]
        if bad:
            raise SystemExit("这些账号不像测试夹具，要删请加 --force：%s" % bad)

    pairs = user_refs(conn)
    by_table = {}
    for table, col in pairs:
        by_table.setdefault(table, []).append(col)

    def predicate(cols):
        # 一张表可能有好几个指向 users 的列（messages 的 from_id/to_id、conversations 的
        # a_id/b_id/last_from）。按列分别数会把同一行数好几遍，"任一列命中"才是真实行数。
        return " OR ".join("%s IN (%s)" % (c, ",".join("?" * len(ids))) for c in cols)

    def bound(cols):
        return [v for _ in cols for v in ids]

    before = {}
    for table, cols in by_table.items():
        try:
            before[table] = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE %s" % (table, predicate(cols)), bound(cols)).fetchone()[0]
        except sqlite3.OperationalError:
            before[table] = 0
    keep_before = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in by_table}

    print(json.dumps({"将删除的账号": rows, "各表行数": {k: v for k, v in before.items() if v},
                      "合计子表行": sum(before.values())}, ensure_ascii=False))
    if not args.apply:
        print("预演模式，什么都没删。确认无误再加 --apply")
        return 0

    # 删除顺序天然会撞外键：清 posts 的时候 comments 还指着它。把外键检查推到 commit——
    # 整个事务跑完仍然自洽才落盘，不自洽就整笔回滚，不会留下"删了一半"的库。
    conn.execute("PRAGMA defer_foreign_keys=ON")
    for table, cols in by_table.items():
        try:
            conn.execute("DELETE FROM %s WHERE %s" % (table, predicate(cols)), bound(cols))
        except sqlite3.OperationalError:
            pass
    conn.execute("DELETE FROM users WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    try:
        conn.commit()
    except sqlite3.IntegrityError as error:
        conn.rollback()
        raise SystemExit("删完不自洽，整笔已回滚（库里一行没动）：%s" % error)

    left = [r[0] for r in conn.execute("SELECT id FROM users ORDER BY id").fetchall()]
    orphans = {}
    for table, col in pairs:
        try:
            n = conn.execute("SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND %s NOT IN "
                             "(SELECT id FROM users)" % (table, col, col)).fetchone()[0]
            if n:
                orphans["%s.%s" % (table, col)] = n
        except sqlite3.OperationalError:
            pass
    keep_after = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in by_table}
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
