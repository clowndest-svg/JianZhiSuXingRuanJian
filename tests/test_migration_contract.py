"""Migration regressions use isolated files; never import against production paths."""
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_modules import migrations


class MigrationContracts(unittest.TestCase):
    def setUp(self):
        (ROOT / '_audit_sandbox').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='migration-', dir=ROOT / '_audit_sandbox')
        self.root = Path(self.temp.name)
        self.env = {f'QINGSU_{name}_DIR': str(self.root / name)
                    for name in ('DB', 'KEY', 'UPLOAD', 'WEB')}
        self.env.update(QINGSU_SKIP_MIGRATE='0', PYTHONDONTWRITEBYTECODE='1')
        self.environment = patch.dict(os.environ, self.env)
        self.environment.start()
        self.server = self.load_server('migration_fixture')
        c = self.server.get_db()
        try:
            c.execute("INSERT INTO users(username,password_hash,public_id,created_at) VALUES ('synthetic','not-a-login-hash','12345678','2026-01-01 00:00:00')")
            c.commit()
        finally:
            c.close()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def load_server(self, name):
        spec = importlib.util.spec_from_file_location(name, ROOT / 'server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def read(self, sql):
        c = sqlite3.connect(self.root / 'DB' / 'qingsu.db')
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()

    def command(self, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/migrate.py'), *args],
                              cwd=ROOT, env=dict(os.environ, **(env or {})),
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_repeated_migrations_preserve_public_ids(self):
        for _ in range(2):
            self.server.migrate_db()
            self.assertEqual(self.read("SELECT public_id FROM users WHERE username='synthetic'"),
                             [('12345678',)])

    def test_only_missing_public_ids_are_backfilled(self):
        c = self.server.get_db()
        try:
            c.execute("INSERT INTO users(username,password_hash,public_id) VALUES ('empty','x','')")
            c.execute("INSERT INTO users(username,password_hash,public_id) VALUES ('null','x',NULL)")
            c.commit()
        finally:
            c.close()
        self.server.migrate_db()
        identities = dict(self.read('SELECT username,public_id FROM users'))
        self.assertEqual(identities['synthetic'], '12345678')
        for username in ('empty', 'null'):
            self.assertRegex(identities[username], r'^[1-9][0-9]{7}$')
        self.assertEqual(len(set(identities.values())), 3)

    def test_skip_migrate_import_does_not_write(self):
        statements = []
        original = sqlite3.connect

        def traced(*args, **kwargs):
            c = original(*args, **kwargs)
            c.set_trace_callback(statements.append)
            return c

        with patch.dict(os.environ, {'QINGSU_SKIP_MIGRATE': '1'}), \
                patch.object(sqlite3, 'connect', traced):
            self.load_server('migration_readonly')
        writes = [sql for sql in statements if sql.strip().split()[0].upper()
                  in ('CREATE', 'INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP', 'REPLACE')]
        self.assertEqual(writes, [], 'read-only startup performed schema or business writes')

    def test_failed_migration_rolls_back_backfill_and_version(self):
        c = self.server.get_db()
        try:
            c.execute("UPDATE users SET public_id='' WHERE username='synthetic'")
            c.execute('UPDATE schema_version SET version=14')
            c.commit()
        finally:
            c.close()
        with patch.object(migrations, 'record', side_effect=RuntimeError('synthetic migration failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic migration failure'):
                self.server.migrate_db()
        self.assertEqual(self.read("SELECT public_id FROM users WHERE username='synthetic'"), [('',)])
        self.assertEqual(self.read('SELECT version FROM schema_version'), [(14,)])
        # A failed attempt must release the write lock so the next attempt can finish.
        self.server.migrate_db()
        self.assertEqual(self.read('SELECT version FROM schema_version'), [(migrations.SCHEMA_VERSION,)])

    def test_check_reads_version_without_initializing_other_directories(self):
        extra = {f'QINGSU_{name}_DIR': str(self.root / ('check-' + name))
                 for name in ('KEY', 'UPLOAD', 'WEB')}
        result = self.command('--check', env=extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        for folder in extra.values():
            self.assertFalse(Path(folder).exists(), 'check created runtime directories')

    def test_check_missing_database_never_creates_it(self):
        missing = self.root / 'missing-database'
        result = self.command('--check', env={'QINGSU_DB_DIR': str(missing)})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists(), 'read-only check created a new database')

    def test_explicit_migration_overrides_skip_environment(self):
        c = self.server.get_db()
        try:
            c.execute('UPDATE schema_version SET version=1')
            c.commit()
        finally:
            c.close()
        result = self.command(env={'QINGSU_SKIP_MIGRATE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read('SELECT version FROM schema_version'), [(migrations.SCHEMA_VERSION,)])

    def test_all_extension_tables_exist_before_version_is_recorded(self):
        required = {'share_settings', 'daily_reviews', 'shared_goals', 'shared_goal_members',
                    'push_subscriptions', 'training_sessions', 'training_sets', 'training_templates'}
        original = migrations.record
        seen = []

        def record(conn, stamp):
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            seen.append(required <= existing)
            return original(conn, stamp)

        with patch.object(migrations, 'record', side_effect=record):
            # Start from a genuinely empty database, not tables installed by an earlier import.
            with patch.dict(os.environ, {'QINGSU_DB_DIR': str(self.root / 'fresh-db')}):
                self.load_server('migration_empty')
        self.assertEqual(seen, [True])

    def test_schema_script_keeps_transaction_and_quoted_semicolons(self):
        c = sqlite3.connect(':memory:')
        try:
            c.execute('BEGIN IMMEDIATE')
            migrations.execute_schema(c, "CREATE TABLE sample(value TEXT); INSERT INTO sample VALUES ('a;b');")
            self.assertEqual(c.execute('SELECT value FROM sample').fetchone(), ('a;b',))
            c.rollback()
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='sample'").fetchone())
        finally:
            c.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
