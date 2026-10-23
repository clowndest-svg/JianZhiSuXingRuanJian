"""B06 估算可解释：配置在 / 真跑通过 / 最后一次成功时间，三件事必须分开答。

这条只测 app_modules/online_ai 这一层，不起服务、不碰数据库，所以不会和别的工作线抢文件。
它钉的是方案点名的那个错：把"配置存在"当成"能用"，模型挂了很久界面还显示已接入。
"""
import importlib.util
import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_module():
    """每次重新 import 一份：_runtime 是模块级状态，跨用例残留会让"从没成功过"永远为假。"""
    spec = importlib.util.spec_from_file_location(
        "online_ai_under_test", ROOT / "app_modules" / "online_ai.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["online_ai_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reply(text):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": text}}]}).encode())


class AiStatus(unittest.TestCase):
    def setUp(self):
        self.ai = load_module()
        # 没有配置文件时走本机模型：configured 为真，但一次都没跑过
        self.ai._CONFIG_CANDIDATES = []

    def test_configured_is_not_the_same_as_working(self):
        st = self.ai.online_status(force=True)
        self.assertTrue(st["configured"], "本机模型这条路应该是可配置的")
        self.assertIsNone(st["last_success_at"],
                          "一次都没跑过却给出了最后成功时间：那就是把配置当成了能用")
        self.assertIsNone(st["last_elapsed_ms"])
        self.assertEqual(st["last_failure_kind"], "")

    def test_a_real_success_records_time_model_and_latency(self):
        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("好的")):
            text, why = self.ai.online_chat("随便问一句")
        self.assertEqual((text, why), ("好的", ""))
        st = self.ai.online_status(force=True)
        began = time.time()
        self.assertIsNotNone(st["last_success_at"])
        self.assertLess(st["last_success_at"], began + 1)
        self.assertEqual(st["last_success_model"], st["model"],
                         "记下的模型名和当前模型对不上")
        self.assertIsNotNone(st["last_elapsed_ms"])
        self.assertGreaterEqual(st["last_elapsed_ms"], 0)

    def test_failures_are_typed_and_do_not_erase_the_last_success(self):
        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("成功过一次")):
            self.ai.online_chat("第一问")
        first_ok = self.ai.online_status(force=True)["last_success_at"]
        self.assertIsNotNone(first_ok)

        boom = urllib.error.HTTPError("u", 503, "busy", {}, None)
        with patch.object(self.ai.urllib.request, "urlopen", side_effect=boom):
            text, why = self.ai.online_chat("第二问")
        self.assertIsNone(text)
        self.assertIn("503", why)
        st = self.ai.online_status(force=True)
        self.assertEqual(st["last_failure_kind"], "http_503",
                         "失败类型没记下来，事后只能看到'就是不通'")
        self.assertIsNotNone(st["last_failure_at"])
        self.assertEqual(st["last_success_at"], first_ok,
                         "一次失败抹掉了上一次成功的时间：两个事实被混成一个")

        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("   ")):
            text2, why2 = self.ai.online_chat("第三问")
        self.assertIsNone(text2)
        self.assertIn("空内容", why2)
        self.assertEqual(self.ai.online_status(force=True)["last_failure_kind"], "empty_content",
                         '返回空内容被记成了别的原因')

    def test_connection_errors_keep_their_own_kind(self):
        with patch.object(self.ai.urllib.request, "urlopen",
                          side_effect=TimeoutError("timed out")):
            text, why = self.ai.online_chat("问")
        self.assertIsNone(text)
        self.assertIn("TimeoutError", why)
        self.assertEqual(self.ai.online_status(force=True)["last_failure_kind"], "TimeoutError")

    def test_status_never_leaks_the_prompt(self):
        secret = "我今天吃了三碗饭这个是私人内容"
        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("收到")):
            self.ai.online_chat(secret)
        blob = json.dumps(self.ai.online_status(force=True), ensure_ascii=False)
        self.assertNotIn(secret, blob, "状态接口把用户提示词带出来了")
        for word in ("吃了", "三碗饭"):
            self.assertNotIn(word, blob)

    def test_state_word_never_turns_configured_into_working(self):
        """界面那一格给的是 up / down / untested 三个词，不许把"配置在"折成 up。"""
        self.assertEqual(self.ai.online_state(), "untested",
                         "配置在但从没跑过，必须单独成一个状态，不能显示成 up")
        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("好")):
            self.ai.online_chat("问")
        self.assertEqual(self.ai.online_state(), "up", "真的成功过一次之后才该是 up")
        with patch.object(self.ai.urllib.request, "urlopen",
                          side_effect=urllib.error.HTTPError("u", 500, "x", {}, None)):
            self.ai.online_chat("再问")
        self.assertEqual(self.ai.online_state(), "down", "成功之后又失败了，应当是 down")
        with patch.object(self.ai.urllib.request, "urlopen", return_value=reply("又好了")):
            self.ai.online_chat("第三次")
        self.assertEqual(self.ai.online_state(), "up", "恢复之后要能自己回到 up")

    def test_state_word_is_down_when_unconfigured(self):
        self.assertEqual(
            self.ai.online_state({"ok": False, "last_success_at": 1, "last_failure_at": None}),
            "down", "没配置就是 down，哪怕历史上成功过（历史不能替现在的配置背书）")

    def test_unconfigured_still_says_why(self):
        self.ai._CONFIG_CANDIDATES = [str(ROOT / "_audit_sandbox" / "no-such-ai.json")]
        self.ai._state.update(cfg={"base_url": "http://insecure", "model": "x"}, why="")
        st = self.ai.online_status(force=True)
        # 本机模型的回落路径：即使外部配置不可用，仍要说清走的是哪一条
        self.assertIn(st["source"], ("本机模型", "外部接口", "无"))
        self.assertIn("configured", st)

    def test_equal_clock_ticks_preserve_completion_order(self):
        with patch.object(self.ai.time, 'time', return_value=1000):
            self.ai._note_ok('model', 1000)
            self.assertEqual(self.ai.online_state(), 'up')
            self.ai._note_fail('http_503', 1000)
            self.assertEqual(self.ai.online_state(), 'down')
            self.ai._note_ok('model', 1000)
            self.assertEqual(self.ai.online_state(), 'up')


if __name__ == "__main__":
    unittest.main(verbosity=2)
