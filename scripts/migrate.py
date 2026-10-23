# -*- coding: utf-8 -*-
"""显式跑一次结构迁移（方案 C05）。

部署时先跑这个，再启动服务：迁移失败要停在部署步骤里，而不是藏在服务日志中，
等第一条业务请求撞上"某个列不存在"才发现。

用法：
    python3 scripts/migrate.py            # 迁移到代码要求的版本并打印
    python3 scripts/migrate.py --check    # 只核对，不改结构（退出码非零＝落后）
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="轻塑结构迁移")
    parser.add_argument("--check", action="store_true", help="只核对版本，不改结构")
    args = parser.parse_args()

    if args.check:
        os.environ["QINGSU_SKIP_MIGRATE"] = "1"
    import server  # 迁移在 import 期完成，与生产启动走同一条代码路径

    from app_modules import migrations
    applied = server.schema_version_report()
    print("结构版本：库 %s / 代码要求 %d" % (applied, migrations.SCHEMA_VERSION))
    print("登记表：")
    for version, name, owner, detail in migrations.MIGRATIONS:
        print("  %2d  [%s] %s —— %s" % (version, owner, name, detail))
    print("后台自有表（主应用不建不改）：%s" % ", ".join(migrations.ADMIN_OWNED_TABLES))
    if applied != migrations.SCHEMA_VERSION:
        print("MIGRATE_FAILED 版本没对上" if not args.check else "CHECK_FAILED 库落后于代码")
        return 1
    print("MIGRATE_OK" if not args.check else "CHECK_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
