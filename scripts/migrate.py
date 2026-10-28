# -*- coding: utf-8 -*-
"""显式迁移；--check只用只读连接，不导入服务或创建运行目录。"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == 'scripts' else HERE
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def read_version():
    from app_modules import migrations
    path = Path(os.environ.get('QINGSU_DB_DIR', '/opt/qingsu/data')) / 'qingsu.db'
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        return migrations.read(conn)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='轻塑结构迁移')
    parser.add_argument('--check', action='store_true', help='只核对版本，不改结构')
    args = parser.parse_args()
    from app_modules import migrations

    if args.check:
        try:
            applied = read_version()
        except sqlite3.Error:
            print('CHECK_FAILED 数据库不存在或不可读，未创建或修改数据库')
            return 1
    else:
        # 显式迁移不能被服务进程继承的SKIP_MIGRATE开关变成只检查。
        os.environ['QINGSU_SKIP_MIGRATE'] = '0'
        import server
        applied = server.schema_version_report()

    print('结构版本：库 %s / 代码要求 %d' % (applied, migrations.SCHEMA_VERSION))
    if not args.check:
        print('登记表：')
        for version, name, owner, detail in migrations.MIGRATIONS:
            print('  %2d  [%s] %s —— %s' % (version, owner, name, detail))
        print('后台自有表（主应用不建不改）：%s' % ', '.join(migrations.ADMIN_OWNED_TABLES))
    if applied != migrations.SCHEMA_VERSION:
        print('CHECK_FAILED 结构版本不匹配' if args.check else 'MIGRATE_FAILED 结构版本不匹配')
        return 1
    print('CHECK_OK' if args.check else 'MIGRATE_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
