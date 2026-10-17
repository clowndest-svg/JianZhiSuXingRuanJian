"""可插拔的在线大模型客户端（OpenAI 兼容）。

设计约束，三条都不能破：
1. 没配置就是没有——返回 (None, 原因)，调用方必须如实说明，不许回落到"看着像答案"的文本；
2. 密钥只在服务器本地文件里，不进仓库、不进日志、不进任何接口响应；
3. 在线模型给的数字一律过硬校验，越界就当它没说。
"""
import json, os, re, time, urllib.error, urllib.request

_CONFIG_CANDIDATES = [
    os.environ.get("QINGSU_ONLINE_AI_FILE", ""),
    "/opt/qingsu/ai-online.json",
]
_REQUIRED = ("base_url", "model")
_state = {"checked_at": 0.0, "cfg": None, "why": ""}
_RECHECK = 30.0
_TIMEOUT = float(os.environ.get("QINGSU_ONLINE_AI_TIMEOUT", "25"))

# 热量合理区间：一份菜超过这个数或低于这个数，基本就是模型在胡说
_CAL_RANGE = (15, 3000)
_MACRO_RANGE = (0.0, 400.0)
_BANNED = ("作为一个", "我无法", "抱歉", "建议咨询", "一定能", "保证", "绝对", "治愈", "停药", "诊断")


def _load():
    for path in _CONFIG_CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                cfg = json.load(handle)
        except Exception as error:
            return None, "配置文件读不懂（%s）" % type(error).__name__
        missing = [k for k in _REQUIRED if not str(cfg.get(k) or "").strip()]
        if missing:
            return None, "配置缺少字段：" + "、".join(missing)
        if not str(cfg["base_url"]).startswith("https://"):
            return None, "base_url 必须是 https（密钥不能走明文）"
        if not str(cfg.get("api_key") or "").strip():
            return None, "配置里没有 api_key"
        return cfg, ""
    return None, "服务器上没有在线模型配置（放一个 /opt/qingsu/ai-online.json 就能开）"


def online_status(force=False):
    """给状态接口和判据用：能不能用、为什么不能用。绝不返回密钥。"""
    now = time.time()
    if not force and now - _state["checked_at"] < _RECHECK:
        return {"ok": _state["cfg"] is not None, "why": _state["why"],
                "model": (_state["cfg"] or {}).get("model", "")}
    cfg, why = _load()
    _state.update(checked_at=now, cfg=cfg, why=why)
    return {"ok": cfg is not None, "why": why, "model": (cfg or {}).get("model", "")}


def online_chat(prompt, max_tokens=400, temperature=0.3):
    """返回 (文本, 错误说明)。失败不冷却成"不可用"——每次调用都如实报当次原因。"""
    status = online_status()
    if not status["ok"]:
        return None, status["why"]
    cfg = _state["cfg"]
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {"model": cfg["model"],
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": int(max_tokens), "temperature": float(temperature)}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + str(cfg["api_key"])})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            got = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return None, "在线模型返回 HTTP %d" % error.code
    except Exception as error:
        return None, "连不上在线模型（%s）" % type(error).__name__
    try:
        text = ((got.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception:
        text = ""
    text = str(text).strip()
    return (text, "") if text else (None, "在线模型返回了空内容")


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def online_estimate_food(name, grams=None):
    """按菜名（可选克重）估热量与三大宏量。返回 dict 或 (None, 原因)。

    模型必须同时给出"它假设的份量"，否则一个没有前提的 kcal 数字比没有数字更坏。
    """
    hint = ("这是一份实际吃下去的量，请给出这一份的 kcal 与蛋白/碳水/脂肪克数；"
            if grams else "请先按常见外食份量假设一个克重，再给出这一份的 kcal 与三大宏量；")
    prompt = ("你是营养师。只输出一个 JSON 对象，不要解释、不要 Markdown。\n"
              "字段：grams（整数，这一份的可食部克重）、kcal（整数）、protein_g、carbs_g、fat_g（数字）、"
              "basis（不超过 24 字，说明你按什么算的）。\n"
              "规则：只按常见中式外食/包装食品估；不确定就给保守值并在 basis 里写"
              "「不确定」；不给医疗或减重建议。\n"
              "食物：" + str(name or "")[:120] + "\n" + (
                  ("已知这一份约 " + str(int(grams)) + " g。" + hint) if grams else hint))
    text, why = online_chat(prompt, max_tokens=220, temperature=0.2)
    if not text:
        return None, why or "在线模型没给内容"
    found = _JSON_BLOCK.search(text)
    if not found:
        return None, "在线模型没按 JSON 返回"
    try:
        data = json.loads(found.group(0))
    except Exception:
        return None, "在线模型的 JSON 读不懂"
    try:
        kcal = int(round(float(data.get("kcal"))))
        grams_out = int(round(float(data.get("grams") or 0)))
        pro = round(float(data.get("protein_g") or 0), 1)
        carb = round(float(data.get("carbs_g") or 0), 1)
        fat = round(float(data.get("fat_g") or 0), 1)
        basis = str(data.get("basis") or "")[:40]
    except (TypeError, ValueError):
        return None, "在线模型给的数字读不懂"
    problems = []
    if not _CAL_RANGE[0] <= kcal <= _CAL_RANGE[1]:
        problems.append("热量超出合理区间")
    if grams_out <= 0 or grams_out > 5000:
        problems.append("份量不合理")
    for value in (pro, carb, fat):
        if not 0 <= value <= _MACRO_RANGE[1]:
            problems.append("宏量超出合理区间")
    if any(word in basis for word in _BANNED):
        problems.append("依据里带了不该出现的话")
    if problems:
        return None, "在线估算被拦下：" + "、".join(problems)
    return {"cal": kcal, "grams": grams_out, "protein_g": pro, "carbs_g": carb,
            "fat_g": fat, "basis": basis or "按常见份量估"}, ""
