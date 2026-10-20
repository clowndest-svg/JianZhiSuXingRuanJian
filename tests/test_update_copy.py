# -*- coding: utf-8 -*-
"""更新弹窗文案的真编译真跑测试。

UpdateCopy 是纯 Java，所以这里用 javac 现编现跑，不靠"读源码看着像对"。
notes 直接取 make_version_json 从 CHANGELOG 生成的那一份——两头一起验，
才能证明弹窗里不会出现 ** 和反引号。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import make_version_json  # noqa: E402

HARNESS = """
package com.fitcoach.shapemaster;
public class UpdateCopyHarness {
    public static void main(String[] args) {
        String notes = args.length > 0 ? args[0] : "";
        System.out.print(UpdateCopy.body(40, 41, "5.1 MB", notes));
    }
}
"""


class UpdateCopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qingsu-updatecopy-")
        src = Path(cls.tmp) / "src" / "com" / "fitcoach" / "shapemaster"
        src.mkdir(parents=True)
        shutil.copy2(ROOT / "app" / "src" / "main" / "java" / "com" / "fitcoach" / "shapemaster"
                     / "UpdateCopy.java", src / "UpdateCopy.java")
        with io.open(str(src / "UpdateCopyHarness.java"), "w", encoding="utf-8") as handle:
            handle.write(HARNESS)
        out = Path(cls.tmp) / "out"
        out.mkdir()
        done = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(out),
                               str(src / "UpdateCopy.java"), str(src / "UpdateCopyHarness.java")],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise AssertionError("javac 编译失败：" + (done.stderr or done.stdout))
        cls.cp = str(out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_body(self, notes):
        done = subprocess.run(["java", "-Dfile.encoding=UTF-8", "-cp", self.cp,
                               "com.fitcoach.shapemaster.UpdateCopyHarness", notes],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_real_changelog_notes_render_clean(self):
        notes = make_version_json.latest_release_note()
        body = self.run_body(notes)
        for mark in ("**", "`", "## "):
            self.assertNotIn(mark, body, "弹窗正文里还留着 Markdown 记号 " + mark)
        self.assertTrue(body.startswith("当前 40 版 → 最新 41 版"), body[:60])
        self.assertIn("更新内容：", body)
        self.assertIn("\n• ", body, "没有项目符号，用户看到的还是一整段")
        # 标题栏已经写了版本号，正文不该再来一行 rNNN / x.y.z
        self.assertNotIn("r15", body.split("更新内容：")[0], "正文开头重复了 CHANGELOG 版本标题")
        for internal in ("消息存法", "判据", "验收方式", "nginx", "外键"):
            self.assertNotIn(internal, body, "工程内部话漏进用户弹窗：" + internal)

    def test_missing_notes_says_so_instead_of_lying(self):
        body = self.run_body("")
        self.assertIn("这一版没有写更新说明", body)
        self.assertNotIn("None", body)

    def test_size_and_disclaimer_present(self):
        body = self.run_body("r158 / 2.1.0（42）\n\n更新内容：\n• 一条")
        self.assertIn("安装包约 5.1 MB", body)
        self.assertIn("系统浏览器", body)
        self.assertIn("系统设置里放行", body)
        self.assertIn("• 一条", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
