"""C08 监控可定位性：路由模板归并、子系统分类、告警去重与恢复、没读数不许写成 0。"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_monitor():
    spec = importlib.util.spec_from_file_location("qingsu_monitor", ROOT / "scripts" / "monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


monitor = load_monitor()

SAMPLE = "\n".join([
    "request id=a1 path=['api'] status=200 elapsed_ms=12.0",
    "request id=a2 path=/api/community/posts/12/comments status=200 elapsed_ms=40.0",
    "request id=a3 path=/api/community/posts/7 status=500 elapsed_ms=900.0",
    "request id=a4 path=/api/dashboard status=200 elapsed_ms=7.0",
    "request id=a5 path=/api/ai/status status=200 elapsed_ms=1500.0",
    "request id=a6 path=/uploads/2f3a4b5c6d7e8f90a1b2c3d4e5f6a7b8.jpg status=200 elapsed_ms=30.0",
    "request id=a7 path=/uploads/99887766554433221100ffaabbccddee.jpg status=403 elapsed_ms=25.0",
    "request id=a8 path=/ws/chat status=200 elapsed_ms=5.0",
    "application_failure id=a5 error=IntegrityError",
    "Application startup complete",
])


class RouteTemplate(unittest.TestCase):
    def test_numeric_and_hash_segments_collapse(self):
        self.assertEqual(monitor.route_template("/api/community/posts/12/comments"),
                         "/api/community/posts/{id}/comments")
        self.assertEqual(monitor.route_template("/api/community/users/77"), "/api/community/users/{id}")
        self.assertEqual(monitor.route_template("/uploads/" + "2f" * 16 + ".jpg"), "/uploads/{id}")

    def test_real_path_segments_are_kept(self):
        self.assertEqual(monitor.route_template("/api/ai/status"), "/api/ai/status")
        self.assertNotEqual(monitor.route_template("/api/dashboard"),
                            monitor.route_template("/api/community/posts/1"))

    def test_current_single_segment_log_form(self):
        # server.py 现在只打首段（列表字符串），归并必须照这个形状也能跑
        self.assertEqual(monitor.route_template("['api']"), "/api")
        self.assertEqual(monitor.route_template("['uploads']"), "/uploads")

    def test_rows_carry_template_status_and_latency(self):
        rows = monitor.request_rows(SAMPLE)
        self.assertEqual(len(rows), 8, "非请求日志行不该被算成一次调用")
        templates = {row[1] for row in rows}
        self.assertIn("/api/community/posts/{id}/comments", templates)
        self.assertEqual(sum(row[2] >= 500 for row in rows), 1)


class SlowEndpoints(unittest.TestCase):
    def test_ids_of_one_endpoint_share_one_bucket(self):
        logs = "\n".join(["request id=b%d path=/api/posts/%d status=200 elapsed_ms=%s" % (n, 10 + n, ms)
                          for n, ms in enumerate(["10.0", "20.0", "700.0"])])
        scored = monitor.slow_endpoints(monitor.request_rows(logs))
        self.assertEqual(len(scored), 1, "同一接口的不同 id 被拆成了多条")
        self.assertEqual(scored[0]["endpoint"], "/api/posts/{id}")
        self.assertEqual(scored[0]["requests"], 3)
        self.assertGreater(scored[0]["p95_ms"], 600, "P95 取到了最小样本，慢接口排名不可信")

    def test_ranking_is_slowest_first(self):
        rows = monitor.request_rows(SAMPLE)
        scored = {item["endpoint"]: item for item in monitor.slow_endpoints(rows, limit=99)}
        self.assertEqual(monitor.slow_endpoints(rows, limit=99)[0]["endpoint"], "/api/ai/status")
        self.assertEqual(scored["/api/dashboard"]["requests"], 1)
        self.assertGreater(scored["/api/ai/status"]["p95_ms"], scored["/api/dashboard"]["p95_ms"])

    def test_top_five_only(self):
        rows = [("api", "/api/e%d" % index, 200, float(index + 1)) for index in range(9)]
        self.assertEqual(len(monitor.slow_endpoints(rows)), 5)

    def test_no_readout_is_none_not_zero(self):
        self.assertIsNone(monitor.percentile([]))
        self.assertEqual(monitor.slow_endpoints([]), [])
        for name, entry in monitor.category_counts([]).items():
            self.assertIsNone(entry["requests"], "%s 没有读数却被写成 0" % name)
            self.assertIsNone(entry["p95_ms"], "%s 没有读数却被写成 0" % name)
            self.assertEqual(entry["readout"], "无读数")
            self.assertNotIn(0, (entry["requests"], entry["errors_5xx"]))
        self.assertIn("无读数", json.dumps(monitor.category_counts([]), ensure_ascii=False))


class Categories(unittest.TestCase):
    def test_each_subsystem_counts_separately(self):
        counts = monitor.category_counts(monitor.request_rows(SAMPLE))
        self.assertEqual(counts["api"]["requests"], 4)
        self.assertEqual(counts["api"]["errors_5xx"], 1)
        self.assertEqual(counts["ai"]["requests"], 1)
        self.assertEqual(counts["media"]["requests"], 2)
        self.assertEqual(counts["ws"]["requests"], 1)
        self.assertEqual(counts["admin"]["readout"], "无读数")

    def test_ops_logs_are_not_mixed_into_app_api(self):
        rows = monitor.request_rows(SAMPLE) + monitor.request_rows(SAMPLE, "admin")
        counts = monitor.category_counts(rows)
        self.assertEqual(counts["admin"]["requests"], 8)
        self.assertEqual(counts["api"]["requests"], 4)

    def test_error_types_are_kept_separate_from_status_codes(self):
        self.assertEqual(monitor.error_types(SAMPLE), {"IntegrityError": 1})


class AlertDedup(unittest.TestCase):
    def test_same_problem_is_reported_once_then_recovery_once(self):
        first, state1 = monitor.diff_alerts(None, ["stale_backup"], 1000)
        self.assertEqual(first["new"], ["stale_backup"])
        second, state2 = monitor.diff_alerts(state1, ["stale_backup"], 1300)
        self.assertEqual(second["new"], [], "持续中的故障被重复报了")
        self.assertEqual(second["ongoing"], ["stale_backup"])
        third, state3 = monitor.diff_alerts(state2, [], 1600)
        self.assertEqual(third["recovered"], ["stale_backup"], "问题消失时没有恢复通知")
        self.assertEqual(third["new"], [])
        fourth, _ = monitor.diff_alerts(state3, [], 1900)
        self.assertEqual(fourth["recovered"], [], "恢复通知重复报了")

    def test_state_file_roundtrip_and_env_override(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "alerts.json"
            os.environ["QINGSU_MONITOR_ALERT_STATE"] = str(path)
            try:
                self.assertEqual(monitor.alert_state_path(), path, "状态文件路径不能用环境变量覆盖")
                _alerts, state = monitor.diff_alerts(monitor.read_alert_state(path), ["turn"], 2000)
                path.write_text(json.dumps(state))
                self.assertEqual(monitor.read_alert_state(path)["problems"], ["turn"])
                self.assertEqual(monitor.read_alert_state(Path(temp) / "missing.json"), None)
            finally:
                del os.environ["QINGSU_MONITOR_ALERT_STATE"]

    def test_new_and_recovered_lines_only_for_changes(self):
        _alerts, state = monitor.diff_alerts(None, ["low_disk"], 1)
        alerts, _ = monitor.diff_alerts(state, [], 2)
        lines = ["ALERT problem=%s" % p for p in alerts["new"]] + ["RECOVERED problem=%s" % p for p in alerts["recovered"]]
        self.assertEqual(lines, ["RECOVERED problem=low_disk"])

    def test_corrupt_state_does_not_invent_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "alerts.json"
            path.write_text("{ 这不是 json")
            self.assertIsNone(monitor.read_alert_state(path))
            alerts, _ = monitor.diff_alerts(monitor.read_alert_state(path), [], 3)
            self.assertEqual(alerts["recovered"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
