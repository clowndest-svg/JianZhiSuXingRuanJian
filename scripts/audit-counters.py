# -*- coding: utf-8 -*-
"""冗余计数列体检：点赞数、评论数这类"存了一份的数字"最容易和明细悄悄走散。

为什么要有这个：计数列是为了排序和列表页不重算全表才存的，改它和改明细是两处代码，
漏一处、或者并发时多扣一次，界面上就是"显示 3 条评论、点进去只有 2 条"。
这种错不会报错、不会 5xx，只能靠对账。

用法:
    python scripts/audit-counters.py                  # 只报告，有漂移就退出码 1
    python scripts/audit-counters.py --fix            # 按明细回写计数列
    python scripts/audit-counters.py --db /path.db    # 指定库（默认读 QINGSU_DB_DIR 或 /opt/qingsu/data）
"""
import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_db():
    env_dir = os.environ.get("QINGSU_DB_DIR")
    if env_dir:
        return os.path.join(env_dir, "qingsu.db")
    return "/opt/qingsu/data/qingsu.db"


# (名字, 明细真值 SQL, 计数列所在表, 键, 计数字段)
CHECKS = [
    ("帖子点赞数", "SELECT post_id AS k, COUNT(*) AS n FROM post_likes GROUP BY post_id",
     "posts", "id", "like_count"),
    ("帖子评论数", "SELECT post_id AS k, COUNT(*) AS n FROM comments "
                   "WHERE status='open' GROUP BY post_id",
     "posts", "id", "comment_count"),
    ("评论点赞数", "SELECT comment_id AS k, COUNT(*) AS n FROM comment_likes GROUP BY comment_id",
     "comments", "id", "like_count"),
]


def audit(conn):
    drift = []
    for name, detail_sql, table, key, col in CHECKS:
        truth = {int(r[0]): int(r[1]) for r in conn.execute(detail_sql).fetchall()}
        rows = conn.execute("SELECT %s, %s FROM %s" % (key, col, table)).fetchall()
        for k, stored in rows:
            real = truth.get(int(k), 0)
            if int(stored or 0) != real:
                drift.append({"what": name, "table": table, "key": int(k),
                              "stored": int(stored or 0), "actual": real})
    return drift


CHECKS_BY_NAME = {c[0]: (c[2], c[3], c[4]) for c in CHECKS}   # 名字 -> (表, 键, 计数列)


def fix(conn, drift):
    for item in drift:
        table, key, col = CHECKS_BY_NAME[item["what"]]
        conn.execute("UPDATE %s SET %s=? WHERE %s=?" % (table, col, key),
                     (item["actual"], item["key"]))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print(json.dumps({"ok": False, "why": "库不存在", "db": args.db}, ensure_ascii=False))
        return 2
    conn = sqlite3.connect(args.db)
    try:
        drift = audit(conn)
        if drift and args.fix:
            fix(conn, drift)
            after = audit(conn)
            print(json.dumps({"ok": not after, "fixed": len(drift), "remaining": len(after),
                              "drift": drift[:20]}, ensure_ascii=False))
            return 0 if not after else 1
        print(json.dumps({"ok": not drift, "drift": drift[:20], "count": len(drift),
                          "hint": "加 --fix 按明细回写" if drift else ""}, ensure_ascii=False))
        return 0 if not drift else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
