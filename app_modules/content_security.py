"""CSP 的报告模式与违规回收（方案 C11）。

为什么先报告模式：index.html 里还有 186 处内联事件处理器，直接上正式策略会把
它们全部拦掉——那是"把没验证过的东西当成已验证"。所以这一步只做两件事：
  1. 发 Content-Security-Policy-Report-Only，浏览器照常执行页面，只把违规报回来；
  2. 收违规、按 directive 聚合，让"能不能转正"变成一个有数可看的问题。

正式策略要同时满足两个条件才允许打开（见 enforce_allowed）：
  · 内联事件处理器已经清零（或 script-src 不再需要 'unsafe-inline'）；
  · 报告窗口内没有任何 blocked 的违规。
两个条件都不满足时说"已启用 CSP"就是假话，所以这里默认只发 Report-Only。
"""
import json
import os
import re
import time

REPORT_WINDOW = int(os.environ.get("QINGSU_CSP_REPORT_WINDOW", "300"))
REPORT_CAP = 200

# WebView 桥、录音回放、导出下载都在这几格里，写错一位就是"界面白屏但日志干净"。
DIRECTIVES = {
    "default-src": "'self'",
    "script-src": "'self' 'unsafe-inline'",     # 内联处理器还在，转正前要摘干净
    "style-src": "'self' 'unsafe-inline'",      # 大量内联样式与主题变量
    "img-src": "'self' data: blob:",
    "media-src": "'self' blob: data:",          # 语音气泡回放走 blob
    "connect-src": "'self' ws: wss: http: https: data: blob:",
    "font-src": "'self' data:",
    "manifest-src": "'self'",
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
}

_reports = []           # [(epoch, directive, blocked, would_block, short_source)]
_seen = {}


INLINE_RE = re.compile(r"\son[a-z]+\s*=", re.I)
INLINE_TTL = 60.0
_inline_cache = {}        # 目录 -> (取数时间, {文件名: mtime_ns}, 计数或 None)


def html_dirs(directories=None):
    """要找内联处理器，就得去真要下发的那份 HTML 里找。

    生产是 WEB_DIR；开发机上那个目录往往不存在，才退回仓库里的 assets。
    两边都存在时只用前者——数两遍会把同一个数字翻倍，而翻倍的数字正好让
    转正门槛看起来比实际更严，那是自欺不是自证。
    """
    if directories:
        # 显式给了目录就以它为准：再悄悄补一个仓库里的 assets，
        # "没数出来"就会被伪装成"数出来 186 处"，门槛永远过不去也永远说不清为什么。
        candidates = list(directories)
    else:
        candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "app", "src", "main", "assets")]
    return [d for d in candidates if d and os.path.isdir(d)]


def _fingerprint(directory):
    return {n: os.stat(os.path.join(directory, n)).st_mtime_ns
            for n in sorted(os.listdir(directory)) if n.endswith(".html")}


def inline_handlers(directories=None):
    """实测还剩多少内联事件处理器；一个 HTML 都找不到时返回 None，不许当成 0。"""
    dirs = html_dirs(directories)
    if not dirs:
        return None
    directory = dirs[0]
    try:
        stamp = _fingerprint(directory)
    except OSError:
        return None
    if not stamp:
        return None
    cached = _inline_cache.get(directory)
    if cached and cached[1] == stamp and time.time() - cached[0] < INLINE_TTL:
        return cached[2]
    total = 0
    for name in stamp:
        try:
            with open(os.path.join(directory, name), encoding="utf-8",
                      errors="replace") as handle:
                total += len(INLINE_RE.findall(handle.read()))
        except OSError:
            return None
    _inline_cache[directory] = (time.time(), stamp, total)
    return total


def clear_inline_cache():
    _inline_cache.clear()


def policy(requested=None, directories=None, base=None):
    """requested 为空时按环境决定发哪一种头；写死 report-only 会让开关形同不存在。

    base 不是可有可无的：APK 里页面源是 appassets.androidplatform.net，相对路径的
    report-uri 会打到那个源上，我们这边一条都收不到——"有报告通道"就成了假话。
    """
    chosen = requested or mode(directories)
    parts = ["%s %s" % (name, value) for name, value in DIRECTIVES.items()]
    parts.append("report-uri %s/csp-report" % (base.rstrip("/") if base else ""))
    header = "; ".join(parts)
    return ("Content-Security-Policy" if chosen == "enforce"
            else "Content-Security-Policy-Report-Only"), header


def mode(directories=None):
    """开关只表示"想转正"；过不过得了由两道实测门槛说了算。

    把 QINGSU_CSP_ENFORCE 一拨就发正式策略，是拿用户的界面去赌"内联处理器大概
    已经清干净了"。过不了门槛就继续 Report-Only，并且把这个决定如实交出去（见 state），
    运维看到的不是"设置没生效"，而是"为什么还没生效"。
    """
    if os.environ.get("QINGSU_CSP_ENFORCE") != "1":
        return "report-only"
    ok, _ = enforce_allowed(inline_handlers(directories))
    return "enforce" if ok else "report-only"


def apply(headers, requested=None, directories=None, base=None):
    """给响应加 CSP 头。调用方已经设过就不覆盖，避免两处各写一份策略。"""
    if "content-security-policy" in {k.lower() for k in headers.keys()}:
        return headers
    name, value = policy(requested, directories, base)
    headers[name] = value
    return headers


def record(raw):
    """收一条浏览器回报的违规。只留 directive、是否拦截和来源文件名——
    完整 violated 字段可能是用户输入的 URL 带查询串，不进日志也不进接口。"""
    try:
        item = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except Exception:
        return False
    # 新浏览器给 effective-directive（只有指令名），旧的只给 violated-directive
    # （"script-src 'self'"这种整句话）。不取首词的话同一类违规会按策略文本裂成好几行，
    # "还剩几类没解决"这个数就不可信。
    raw_directive = item.get("effective-directive") or item.get("violated-directive") or "unknown"
    inner = item.get("csp-report")
    if isinstance(inner, dict):
        # 真浏览器（本轮用 Chromium 实测过）出门的形状是 {"csp-report":{...}}，
        # 字段全在里层，而且没有 blocked 布尔——只有 disposition。
        # 只按顶层字段解析的话，每一条真实违规都会被归成 unknown，
        # 聚合数字看着有、其实一条都没分类，转正门槛就被一个假形状骗过去了。
        item = inner
    raw_directive = item.get("effective-directive") or item.get("violated-directive") or "unknown"
    directive = str(raw_directive).split()[0][:40] if str(raw_directive).split() else "unknown"
    disposition = str(item.get("disposition") or "").lower()
    blocked = bool(item.get("blocked")) or disposition == "enforce"
    # 报告模式下 disposition 是 "report"：这条没真被拦，但转正后会被拦。
    # 转正门槛要看的正是这个数，否则"报告模式没拦任何东西"会让门槛永远为 0。
    would_block = blocked or bool(item.get("blocked-uri"))
    source = str(item.get("document-uri") or item.get("blocked-uri") or "")
    # 只留文件名：查询串里可能有令牌或用户输入，报告不进日志也不进接口。
    source = source.split("?")[0].split("#")[0].split("/")[-1][:60]
    key = "%s|%s|%s" % (directive, "e" if blocked else "r", source)
    now = time.time()
    # 匿名报告可以构造无限多个不同来源文件名；_seen 不设上限就是一条内存增长通道。
    if len(_seen) > 4096:
        cutoff = now - REPORT_WINDOW
        for stale_key, seen_at in list(_seen.items()):
            if seen_at < cutoff:
                _seen.pop(stale_key, None)
        if len(_seen) > 4096:
            _seen.clear()
    hit = _seen.get(key)
    if hit and now - hit < 5:
        return False
    _seen[key] = now
    _reports.append((now, directive, blocked, would_block, source))
    del _reports[:-REPORT_CAP]
    return True


def summary(window=None):
    """窗口内的违规聚合。给运维和判据看的是"能不能转正"，不是一条条原文。"""
    cutoff = time.time() - (window or REPORT_WINDOW)
    fresh = [r for r in _reports if r[0] >= cutoff]
    by_directive = {}
    for _, directive, blocked, would_block, source in fresh:
        slot = by_directive.setdefault(directive, {"total": 0, "blocked": 0,
                                                   "would_block": 0, "sources": []})
        slot["total"] += 1
        slot["blocked"] += 1 if blocked else 0
        slot["would_block"] += 1 if would_block else 0
        if source and source not in slot["sources"] and len(slot["sources"]) < 5:
            slot["sources"].append(source)
    return {"window_seconds": window or REPORT_WINDOW, "count": len(fresh),
            "blocked": sum(1 for r in fresh if r[2]),
            "would_block": sum(1 for r in fresh if r[3]),
            "by_directive": by_directive}


def clear():
    _reports.clear()
    _seen.clear()


def enforce_allowed(handlers):
    """转正的两个门槛，缺一不可，并把缺什么说清楚。

    handlers=None 是"没数出来"，和"数出来是 0"不是一回事：前者必须挡住转正，
    否则换一个没有 HTML 的目录就能把门槛骗过去。
    """
    # 报告模式下 disposition 全是 report，blocked 恒为 0——拿它当门槛等于没有门槛。
    # 会真被拦下来的那条数才是"转正以后会不会挡用户"的证据。
    counts = summary()
    blocked = counts["would_block"]
    reasons = []
    if handlers is None:
        reasons.append("没能实测内联事件处理器（找不到可数的 HTML），不能按 0 处理")
    elif handlers > 0:
        reasons.append("还有 %d 处内联事件处理器，script-src 离不开 'unsafe-inline'"
                       % handlers)
    if blocked > 0:
        reasons.append("报告窗口内仍有 %d 条违规在转正后会被拦下来" % blocked)
    return (not reasons), reasons


def state(directories=None, base=None):
    """给 /health/ready：实际发的是哪一种头、想不想转正、能不能转正、卡在哪。"""
    requested = os.environ.get("QINGSU_CSP_ENFORCE") == "1"
    handlers = inline_handlers(directories)
    ok, reasons = enforce_allowed(handlers)
    out = summary()
    out.update({"mode": "enforce" if (requested and ok) else "report-only",
                "requested_enforce": requested, "inline_handlers": handlers,
                "can_enforce": ok, "blockers": reasons,
                "report_endpoint": "%s/csp-report" % (base.rstrip("/") if base else "")})
    return out
