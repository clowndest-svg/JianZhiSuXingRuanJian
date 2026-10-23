"""C10 长任务骨架：幂等触发、原子领取、心跳回收、并发上限。测锁必须换线程。"""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_modules.long_tasks import LongTaskBusy, LongTasks


def utc(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "long_tasks.db"
        self.tasks = LongTasks(self.db)

    def set_heartbeat(self, task_id, seconds_ago):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE ops_long_tasks SET heartbeat_at=? WHERE id=?", (utc(seconds_ago), task_id))
        conn.commit()
        conn.close()


class IdempotentEnqueue(Base):
    def test_same_dedup_key_yields_exactly_one_task(self):
        first = self.tasks.enqueue("backup", {"scope": "full"}, "web-1", dedup_key="daily")
        second = self.tasks.enqueue("backup", {"scope": "full"}, "web-2", dedup_key="daily")
        self.assertEqual(first["id"], second["id"], "同一 dedup_key 起了两份任务")
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ops_long_tasks").fetchone()[0], 1)
        conn.close()

    def test_concurrent_triggers_still_create_one_row(self):
        results = []
        barrier = threading.Barrier(4)

        def worker(index):
            barrier.wait()
            results.append(self.tasks.enqueue("backup", {}, "node%d" % index, dedup_key="race")["id"])

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 1, "并发触发起了多份：%s" % set(results))
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ops_long_tasks WHERE kind='backup'").fetchone()[0], 1)
        conn.close()

    def test_different_dedup_keys_do_not_collide(self):
        self.tasks.enqueue("backup", {}, "web", dedup_key="daily-a")
        self.tasks.enqueue("backup", {}, "web", dedup_key="daily-b")
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ops_long_tasks").fetchone()[0], 2)
        conn.close()

    def test_finished_task_frees_the_dedup_key(self):
        first = self.tasks.enqueue("backup", {}, "web", dedup_key="daily")
        self.tasks.claim(first["id"], "web")
        self.tasks.finish(first["id"], {"snapshot": "20261022"})
        second = self.tasks.enqueue("backup", {}, "web", dedup_key="daily")
        self.assertNotEqual(first["id"], second["id"], "上一份已经终态，新触发应该起新任务")

    def test_max_active_rejects_extra_launch_without_writing(self):
        self.tasks.enqueue("backup", {}, "web")
        with self.assertRaises(LongTaskBusy):
            self.tasks.enqueue("backup", {}, "web2", max_active=1)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ops_long_tasks").fetchone()[0], 1)
        conn.close()


class ClaimLock(Base):
    def test_only_one_thread_claims_one_task(self):
        task = self.tasks.enqueue("export", {}, "web")
        outcome = []
        start = threading.Barrier(3)

        def worker(name):
            start.wait()
            outcome.append((name, self.tasks.claim(task["id"], name)))

        threads = [threading.Thread(target=worker, args=("owner-%d" % index,)) for index in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(1 for _name, won in outcome if won), 1, "两个以上进程抢到了同一份任务：%s" % outcome)
        current = self.tasks.status(task["id"])
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["attempts"], 1, "失败的抢占也把 attempts 计上去了")
        self.assertEqual(current["owner"], next(name for name, won in outcome if won))

    def test_status_of_unknown_task_is_none_not_fake(self):
        self.assertIsNone(self.tasks.status("does-not-exist"))

    def test_second_claim_of_running_task_fails(self):
        task = self.tasks.enqueue("export", {}, "web")
        self.assertTrue(self.tasks.claim(task["id"], "worker-a"))
        self.assertFalse(self.tasks.claim(task["id"], "worker-b"))

    def test_owner_guard_blocks_foreign_finish(self):
        task = self.tasks.enqueue("export", {}, "web")
        self.tasks.claim(task["id"], "worker-a")
        self.assertIsNone(self.tasks.finish(task["id"], {"x": 1}, owner="worker-b"))
        self.assertEqual(self.tasks.status(task["id"])["status"], "running")


class ResultsAndRetry(Base):
    def test_finish_and_fail_record_payloads(self):
        done = self.tasks.enqueue("backup", {"scope": "full"}, "web")
        self.tasks.claim(done["id"], "web")
        closed = self.tasks.finish(done["id"], {"snapshot": "20261022", "integrity": "ok"})
        self.assertEqual(closed["status"], "done")
        self.assertEqual(closed["result_json"]["result"]["snapshot"], "20261022")
        self.assertEqual(closed["args_json"], {"scope": "full"})

        failed = self.tasks.enqueue("backup", {}, "web")
        self.tasks.claim(failed["id"], "web")
        closed = self.tasks.fail(failed["id"], "disk full")
        self.assertEqual(closed["status"], "failed")
        self.assertEqual(closed["result_json"]["error"], "disk full")

    def test_retryable_failure_becomes_reclaimable(self):
        task = self.tasks.enqueue("backup", {}, "web", dedup_key="daily")
        self.tasks.claim(task["id"], "web")
        self.tasks.fail(task["id"], "临时网络故障", retryable=True)
        again = self.tasks.enqueue("backup", {}, "web", dedup_key="daily")
        self.assertEqual(again["id"], task["id"], "可重试的失败应该复用同一份任务")
        self.assertEqual(again["status"], "interrupted")
        self.assertTrue(self.tasks.claim(task["id"], "web2"))
        self.assertEqual(self.tasks.status(task["id"])["attempts"], 2)

    def test_stale_heartbeat_is_reaped_and_retryable(self):
        running = self.tasks.enqueue("backup", {}, "web")
        self.tasks.claim(running["id"], "web")
        self.set_heartbeat(running["id"], 600)
        fresh = self.tasks.enqueue("cleanup", {}, "web")
        self.tasks.claim(fresh["id"], "web")
        self.assertEqual(self.tasks.reap_stale(60), [running["id"]])
        self.assertEqual(self.tasks.status(running["id"])["status"], "interrupted")
        self.assertEqual(self.tasks.status(fresh["id"])["status"], "running", "没超时的任务被误回收了")
        self.assertTrue(self.tasks.claim(running["id"], "web2"))

    def test_reap_is_scoped_by_kind(self):
        task = self.tasks.enqueue("backup", {}, "web")
        self.tasks.claim(task["id"], "web")
        self.set_heartbeat(task["id"], 600)
        self.assertEqual(self.tasks.reap_stale(60, kind="cleanup"), [])
        self.assertEqual(self.tasks.status(task["id"])["status"], "running")


class Heartbeat(Base):
    def test_heartbeat_only_for_owner_of_running_task(self):
        task = self.tasks.enqueue("backup", {}, "web")
        self.assertFalse(self.tasks.heartbeat(task["id"]), "还没领取就不该有心跳")
        self.tasks.claim(task["id"], "web")
        self.assertTrue(self.tasks.heartbeat(task["id"], owner="web"))
        self.assertFalse(self.tasks.heartbeat(task["id"], owner="别的进程"))

    def test_environment_default_path_is_used(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["QINGSU_LONG_TASKS_DB"] = str(Path(temp) / "from-env.db")
            try:
                tasks = LongTasks()
                task = tasks.enqueue("backup", {}, "web")
                self.assertTrue((Path(temp) / "from-env.db").is_file())
                self.assertEqual(tasks.status(task["id"])["kind"], "backup")
            finally:
                del os.environ["QINGSU_LONG_TASKS_DB"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
