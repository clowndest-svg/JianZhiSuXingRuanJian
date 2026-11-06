"""C11 CSP 的契约：默认只报告，转正要过两道实测门槛，且真的接在响应头上。

前一个类只测纯函数（不 import server，跑得快）；后一个类用真 app 验接线：
头真的发出去了吗、报告真的收下了吗、开关拨到转正但门槛没过时会不会把页面拦白。
只测纯函数的那一类判据，接口忘了挂上也照样全绿——C11 恰恰就是"模块写完了但没人调"。
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load():
    spec = importlib.util.spec_from_file_location(
        "content_security_under_test", ROOT / "app_modules" / "content_security.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["content_security_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class Csp(unittest.TestCase):
    def setUp(self):
        self.csp = load()
        self.csp.clear()
        os.environ.pop("QINGSU_CSP_ENFORCE", None)

    @staticmethod
    def frame(directive, disposition="report", blocked_uri="",
              document="https://example.test/"):
        """按 Chromium 实测到的真实形状造一条违规报告。

        外层是 {"csp-report": {...}}，里层没有 blocked 布尔，只有 disposition
        （report / enforce）和 blocked-uri。之前这里直接把顶层字段喂进去，
        产品只认那种假形状也能全绿，而真浏览器的报告会全被归成 unknown——
        聚合数字看着有，其实一条都没分类。
        """
        inner = {"effective-directive": directive, "violated-directive": directive,
                 "document-uri": document, "disposition": disposition,
                 "original-policy": "img-src 'self'"}
        if blocked_uri:
            inner["blocked-uri"] = blocked_uri
        return {"csp-report": inner}

    def test_default_is_report_only_not_enforce(self):
        name, value = self.csp.policy()
        self.assertEqual(name, "Content-Security-Policy-Report-Only",
                         "还有内联处理器时直接发正式策略，等于把页面自己拦白")
        self.assertIn("report-uri /csp-report", value)

    def test_enforce_switch_alone_does_not_flip_the_header(self):
        """开关说"转正"，内联处理器还在就只能继续报告。

        换掉这条判据的原因是原来那条在奖励错误行为：它要求环境一变就发正式策略，
        而那正好是把 186 处内联处理器赌没赌赢的决定交给一个没人复查的变量。
        """
        os.environ["QINGSU_CSP_ENFORCE"] = "1"
        name, _ = self.csp.policy(requested="report-only")
        self.assertEqual(name, "Content-Security-Policy-Report-Only")
        self.assertFalse(self.csp.enforce_allowed(186)[0])

    def test_enforce_header_only_after_the_measured_gate(self):
        """门槛真过了（实测 0 处内联、窗口内没有被拦的违规），头才该换名字。"""
        os.environ["QINGSU_CSP_ENFORCE"] = "1"
        with tempfile.TemporaryDirectory() as temp:
            with open(os.path.join(temp, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("<button onclick2=1>没有内联处理器</button>")
            self.csp.clear_inline_cache()
            self.assertEqual(self.csp.inline_handlers([temp]), 0)
            name, _ = self.csp.policy(directories=[temp])
            self.assertEqual(name, "Content-Security-Policy")
            self.assertEqual(self.csp.mode([temp]), "enforce")
            # "没数出来"不能当成"数出来是 0"：目录不存在和目录里没 HTML 是两条路，
            # 两条都必须返回 None，否则换一个空目录就能把转正门槛骗过去。
            missing = os.path.join(temp, "nope")
            self.assertIsNone(self.csp.inline_handlers([missing]))
            blank = os.path.join(temp, "blank")
            os.makedirs(blank)
            self.assertIsNone(self.csp.inline_handlers([blank]))
            self.assertFalse(self.csp.enforce_allowed(None)[0])
            self.assertIn("没能实测", "".join(self.csp.enforce_allowed(None)[1]))

    def test_the_lockdown_directives_are_present(self):
        _, value = self.csp.policy()
        for needed in ("object-src 'none'", "frame-ancestors 'none'",
                       "base-uri 'self'", "form-action 'self'"):
            self.assertIn(needed, value, "少了 " + needed)

    def test_media_images_and_bridges_are_not_blocked(self):
        """方案明确要求：正式 CSP 不许挡 WebView 桥、音视频、导出。"""
        _, value = self.csp.policy()
        media = [p for p in value.split(";") if p.strip().startswith("media-src")][0]
        self.assertIn("blob:", media, "语音气泡回放走 blob:，拦掉就是录音放不出来")
        img = [p for p in value.split(";") if p.strip().startswith("img-src")][0]
        self.assertIn("data:", img, "头像与缩略图有 data: 形式，拦掉就是白图")
        connect = [p for p in value.split(";") if p.strip().startswith("connect-src")][0]
        for scheme in ("ws:", "wss:"):
            self.assertIn(scheme, connect, "私信实时连接走 " + scheme)

    def test_enforce_refused_while_inline_handlers_remain(self):
        ok, reasons = self.csp.enforce_allowed(186)
        self.assertFalse(ok, "还有 186 处内联处理器却允许转正式策略")
        self.assertTrue(any("unsafe-inline" in r for r in reasons), reasons)
        self.assertTrue(any("186" in r for r in reasons), "没把还剩多少处说出来")

    def test_enforce_refused_while_reports_are_blocked(self):
        self.csp.record(self.frame("script-src", disposition="enforce",
                                   document="https://example.test/app.js?token=SECRETVALUE"))
        ok, reasons = self.csp.enforce_allowed(0)
        self.assertFalse(ok, "报告里还有会被拦的违规，却允许转正")
        self.assertTrue(any("转正" in r and "拦" in r for r in reasons), reasons)

    def test_report_only_violation_still_blocks_the_switch(self):
        """报告模式下 disposition 永远是 report、blocked 永远是 0。

        门槛要是只看 blocked，就变成"永远为 0、永远允许转正"，那条门槛等于不存在。
        真正该数的是 blocked-uri：转正以后这条就会拦下来。
        """
        self.csp.record(self.frame("img-src", disposition="report",
                                   blocked_uri="https://cdn.test/a.png"))
        out = self.csp.summary(window=60)
        self.assertEqual(out["blocked"], 0, "报告模式不该算成已经拦了")
        self.assertEqual(out["would_block"], 1, "转正后会被拦的那条数没算进来")
        ok, reasons = self.csp.enforce_allowed(0)
        self.assertFalse(ok, "有一条转正后会被拦的违规，却不拦转正")
        self.assertTrue(any("1" in r for r in reasons), reasons)

    def test_enforce_allowed_when_both_gates_pass(self):
        ok, reasons = self.csp.enforce_allowed(0)
        self.assertTrue(ok, reasons)

    def test_real_browser_shape_is_grouped_not_unknown(self):
        """这一条专门盯"解析有没有跟上真浏览器的形状"。

        去掉 record() 里那句 csp-report 解包，directive 会全变成 unknown：
        计数仍然非零、界面仍然有数，看着像在工作，实际一条都没分类。
        """
        self.assertTrue(self.csp.record(self.frame("connect-src")))
        out = self.csp.summary(window=60)
        self.assertIn("connect-src", out["by_directive"],
                      "真形状的报告没被归到 directive 名下：解析对不上浏览器发出来的东西")
        self.assertNotIn("unknown", out["by_directive"],
                         "报告全被归成 unknown，等于一条都没分类")

    def test_violated_directive_sentence_is_grouped_by_its_first_word(self):
        self.csp.record({"csp-report": {"violated-directive": "script-src 'self' 'unsafe-inline'",
                                        "disposition": "report",
                                        "document-uri": "https://example.test/"}})
        self.csp.record(self.frame("script-src"))
        out = self.csp.summary(window=60)
        self.assertEqual(sorted(out["by_directive"]), ["script-src"],
                         "同一类违规按整句话裂成两行，剩几类这个数就不可信")

    def test_report_aggregates_and_counts_blocked_separately(self):
        for _ in range(3):
            self.csp.record(self.frame("script-src", disposition="report"))
            time.sleep(0.01)
        self.csp.record(self.frame("img-src", disposition="enforce"))
        out = self.csp.summary(window=60)
        self.assertGreaterEqual(out["count"], 2, "重复的应该被合并，但两类 directive 都要在")
        self.assertIn("script-src", out["by_directive"])
        self.assertIn("img-src", out["by_directive"])
        self.assertEqual(out["by_directive"]["img-src"]["blocked"], 1)
        self.assertEqual(out["by_directive"]["script-src"]["blocked"], 0,
                         "未被拦截的被算成拦了，转正判断会偏保守到永远转不了")

    def test_report_does_not_keep_query_strings(self):
        self.csp.record(self.frame("connect-src", disposition="enforce",
                                   document="https://example.test/api/x?token=SECRETVALUE&u=9"))
        blob = str(self.csp.summary(window=60))
        self.assertNotIn("SECRETVALUE", blob, "违规报告把查询串带进来了，里面可能有令牌")
        self.assertNotIn("u=9", blob)

    def test_report_uri_must_be_absolute_for_the_apk_origin(self):
        """APK 里页面的源是 appassets.androidplatform.net。

        相对路径的 report-uri 会打到那个源上，我们一条都收不到——
        "有报告通道"就成了假话，而且界面和日志都不会报错。
        """
        _, value = self.csp.policy(base="https://124.220.54.64")
        self.assertIn("report-uri https://124.220.54.64/csp-report", value)
        _, plain = self.csp.policy()
        self.assertIn("report-uri /csp-report", plain)

    def test_apply_does_not_overwrite_an_existing_header(self):
        headers = {"Content-Security-Policy": "default-src 'none'"}
        self.csp.apply(headers)
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'",
                         "两处各写一份策略，最后谁生效要看字典顺序")
        self.assertNotIn("Content-Security-Policy-Report-Only", headers)


class CspWiring(unittest.TestCase):
    """CSP 接到真 app 上以后：头发得出去、报告收得下、开关骗不白界面。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        from fastapi.testclient import TestClient
        from app_modules import content_security
        cls.csp = content_security
        ROOT = Path(__file__).resolve().parents[1]
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "_audit_sandbox")
        cls.addClassCleanup(cls.temp.cleanup)
        for key in ("DB", "UPLOAD", "KEY"):
            os.environ["QINGSU_" + key + "_DIR"] = os.path.join(cls.temp.name, key)
        os.environ["QINGSU_WEB_DIR"] = str(ROOT / "app" / "src" / "main" / "assets")
        os.environ.pop("QINGSU_CSP_ENFORCE", None)
        spec = importlib.util.spec_from_file_location("csp_wiring_server", ROOT / "server.py")
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.c = TestClient(cls.m.app)
        cls.addClassCleanup(cls.c.close)
        cls.orig_dirs = list(cls.m.CSP_SCAN_DIRS)

    def setUp(self):
        self.csp.clear()
        self.csp.clear_inline_cache()
        self.m.CSP_SCAN_DIRS[:] = self.orig_dirs
        os.environ.pop("QINGSU_CSP_ENFORCE", None)

    def tearDown(self):
        self.m.CSP_SCAN_DIRS[:] = self.orig_dirs
        os.environ.pop("QINGSU_CSP_ENFORCE", None)
        self.csp.clear_inline_cache()

    def test_page_response_carries_report_only_header(self):
        r = self.c.get("/")
        name = "Content-Security-Policy-Report-Only"
        self.assertIn(name, r.headers, "默认必须是 Report-Only，否则内联处理器全被拦")
        lowered = {k.lower() for k in r.headers.keys()}
        self.assertNotIn("content-security-policy", lowered,
                         "同时发两种头时浏览器只看正式那个，报告模式就成了摆设")
        # 头里的 report-uri 必须是本站绝对地址：APK 页面的源不是本站，
        # 相对路径会把违规发到 appassets 域上，一条也收不回来。
        self.assertIn("report-uri " + self.m.SITE_BASE + "/csp-report", r.headers[name])

    def test_violation_report_is_collected_without_leaking_the_source(self):
        token = "qs-secret-token-should-not-appear"
        r = self.c.post("/csp-report", json={
            "csp-report": {"effective-directive": "script-src", "disposition": "enforce",
                           "document-uri": "https://x.example/index.html?a=%s" % token,
                           "blocked-uri": "https://x.example/inject.js?tok=%s" % token}})
        self.assertEqual(r.status_code, 204, r.text)
        health = self.c.get("/health/ready").json()
        csp = health["csp"]
        self.assertGreaterEqual(csp["count"], 1)
        self.assertGreaterEqual(csp["blocked"], 1)
        self.assertIn("script-src", csp["by_directive"],
                      "按真形状 POST 的报告没能归类：浏览器发的那份一定收不进统计")
        self.assertGreaterEqual(csp["blocked"], 1)
        blob = str(health) + str(self.csp._reports)
        self.assertNotIn(token, blob, "违规原文（可能带令牌）不许进日志或接口")

    def test_health_says_why_enforce_is_not_on_yet(self):
        health = self.c.get("/health/ready").json()["csp"]
        self.assertEqual(health["mode"], "report-only")
        self.assertFalse(health["requested_enforce"])
        # 门槛必须是实测出来的数字，不是文档里抄的
        counted = len(self.csp.INLINE_RE.findall(
            (Path(self.m.WEB_DIR) / "index.html").read_text(encoding="utf-8", errors="replace")))
        self.assertEqual(health["inline_handlers"], counted)
        self.assertGreater(health["inline_handlers"], 0,
                           "内联处理器真清零了就该删掉这条判据、把这条换成正向断言")
        self.assertFalse(health["can_enforce"])
        self.assertTrue(health["blockers"])

    def test_enforce_switch_cannot_white_screen_the_page(self):
        """最危险的一条：只拨开关，页面响应不许换成正式策略。"""
        os.environ["QINGSU_CSP_ENFORCE"] = "1"
        r = self.c.get("/")
        self.assertIn("Content-Security-Policy-Report-Only", r.headers)
        self.assertNotIn("Content-Security-Policy", r.headers)
        health = self.c.get("/health/ready").json()["csp"]
        self.assertTrue(health["requested_enforce"])
        self.assertEqual(health["mode"], "report-only")
        self.assertFalse(health["can_enforce"])

    def test_enforce_header_really_flips_once_gates_pass(self):
        """反向也要真：门槛过了就得发正式策略，否则上面那条绿灯可能只是永不点亮。"""
        with tempfile.TemporaryDirectory() as temp:
            with open(os.path.join(temp, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("<div>no inline handlers here</div>")
            self.m.CSP_SCAN_DIRS[:] = [temp]
            self.csp.clear_inline_cache()
            os.environ["QINGSU_CSP_ENFORCE"] = "1"
            r = self.c.get("/")
            self.assertIn("Content-Security-Policy", r.headers)
            self.assertNotIn("Content-Security-Policy-Report-Only", r.headers)
            self.assertEqual(self.c.get("/health/ready").json()["csp"]["mode"], "enforce")

    def test_health_exposes_would_block_and_absolute_endpoint(self):
        csp = self.c.get("/health/ready").json()["csp"]
        self.assertIn("would_block", csp, "只剩 blocked 的话，报告模式下它恒为 0")
        self.assertTrue(csp["report_endpoint"].startswith("http"),
                        "报告地址是相对路径时，APK 源会把违规发到 appassets 域上去")

    def test_routes_are_all_theirs_own(self):
        """接线插错位置会把一条已有路由 quietly 换掉，所以三条都要单独钉。

        本轮真实踩过：把 POST /csp-report 插进 @app.get("/health") 与
        @app.get("/health/ready") 之间，/health 就变成了恒返回 204 的那一个——
        接口没报错、健康检查"看起来"也通，只是浏览器再也拿不到文档，
        靠一条不相干的缓存判据才暴露。
        """
        live = self.c.get("/health")
        self.assertEqual(live.status_code, 200, "/health 被别的处理函数吞掉了")
        self.assertTrue(live.json(), "/health 不该回空")
        ready = self.c.get("/health/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertIn("csp", ready.json(), "/health/ready 被别的处理函数顶掉了")
        report = self.c.post("/csp-report", json={"csp-report": {
            "effective-directive": "img-src", "disposition": "report",
            "blocked-uri": "https://cdn.test/x.png", "document-uri": "https://x/a.html"}})
        self.assertEqual(report.status_code, 204)

    def test_wired_header_matches_the_module_policy(self):
        """接线要对得上模块的说法：中间件发出去的策略文本必须就是 policy() 的那一份。

        只在模块里测"策略长这样"，中间件写错一个字母（比如漏了 report-uri）也照样全绿。
        """
        # base 要和中间件用的一致：SITE_BASE 决定 report-uri 是不是绝对地址
        module_header = self.csp.policy(base=self.m.SITE_BASE)[1]
        for path in ("/", "/health/ready"):
            got = self.c.get(path).headers["Content-Security-Policy-Report-Only"]
            self.assertEqual(got, module_header, path + ' 上的 CSP 与模块给出的不是同一份')

    def test_reports_survive_a_renamed_directive(self):
        """旧浏览器只给 violated-directive（"img-src 'self' data:"整句话）。"""
        # 两份报告的来源页面要不同：同一 directive + 同一来源在 5 秒内会被合并，
        # 用同一个 document-uri 就只剩一条，测到的是去重而不是归类。
        self.c.post("/csp-report", json={"csp-report": {
            "violated-directive": "img-src 'self' data:", "disposition": "report",
            "blocked-uri": "https://cdn.test/a.png",
            "document-uri": "https://x.test/index.html"}})
        self.c.post("/csp-report", json={"csp-report": {
            "effective-directive": "img-src", "disposition": "report",
            "blocked-uri": "https://cdn.test/b.png",
            "document-uri": "https://x.test/offline.html"}})
        slot = self.c.get("/health/ready").json()["csp"]["by_directive"]
        self.assertEqual(sorted(slot), ["img-src"], slot)
        self.assertEqual(slot["img-src"]["would_block"], 2, slot)


if __name__ == "__main__":
    unittest.main(verbosity=2)


