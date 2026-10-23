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

# 三件事必须分开答（B06）：
#   configured   —— 配置在不在。静态事实，**不证明能跑**；
#   last_success —— 真的成功过一次吗、什么时候、哪个模型、花了多久；
#   last_failure —— 最后一次失败是什么类型、什么时候。
# 以前只有一个 ok，把"配置在"当成了"能用"，于是模型挂了很久还显示"已接入"。
# 只记类型与耗时，**不记提示词、不记模型回复**：那里面全是用户的私人内容。
_runtime = {"ok_at": 0.0, "ok_model": "", "ok_ms": 0,
            "fail_at": 0.0, "fail_kind": "", "fail_ms": 0}

# 热量合理区间：一份菜超过这个数或低于这个数，基本就是模型在胡说
_CAL_RANGE = (15, 3000)
_MACRO_RANGE = (0.0, 400.0)
_BANNED = ("作为一个", "我无法", "抱歉", "建议咨询", "一定能", "保证", "绝对", "治愈", "停药", "诊断")


# 没有外部 key 时走服务器本机那台 llama-server（qwen2.5-0.5b）。
# 上一版只认外部配置，界面上就写着"未接入"，而机器上明明有个能用的模型——
# 那是接线错了，不是没能力。
_LOCAL_LLM = os.environ.get("QINGSU_LOCAL_LLM_URL", "http://127.0.0.1:8081/v1/chat/completions")


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
    return {"base_url": "", "model": "qwen2.5-0.5b-instruct-q8_0", "local": True}, ""


def online_status(force=False):
    """给状态接口和判据用：用哪个模型、为什么不能用。绝不返回密钥。

    `ok` 只代表**配置可用**，不代表跑得通。要判断"能不能用"，看 `last_success_at`：
    配置在、但从没成功过，那就是"从没跑通过"，不能显示成可用。
    """
    now = time.time()
    if not force and now - _state["checked_at"] < _RECHECK:
        cfg = _state["cfg"]
        base = {"ok": cfg is not None, "why": _state["why"],
                "model": (cfg or {}).get("model", ""),
                "source": "本机模型" if (cfg or {}).get("local") else "外部接口"}
    else:
        cfg, why = _load()
        _state.update(checked_at=now, cfg=cfg, why=why)
        base = {"ok": cfg is not None, "why": why, "model": (cfg or {}).get("model", ""),
                "source": "本机模型" if (cfg or {}).get("local") else ("外部接口" if cfg else "无")}
    base.update({
        "configured": base["ok"],          # 配置在不在（静态）
        "last_success_at": _runtime["ok_at"] or None,
        "last_success_model": _runtime["ok_model"],
        # 有没有跑过用时间戳判断，不能用 "ms or None"：一次几毫秒的调用是 0，
        # 被 `or None` 吞掉就变成"从没跑过"，正好把这个字段要回答的问题答反。
        "last_elapsed_ms": _runtime["ok_ms"] if _runtime["ok_at"] else None,
        "last_failure_at": _runtime["fail_at"] or None,
        "last_failure_kind": _runtime["fail_kind"],
        "last_failure_ms": _runtime["fail_ms"] if _runtime["fail_at"] else None,
    })
    return base


def _note_ok(model, began):
    _runtime.update(ok_at=time.time(), ok_model=str(model or ""),
                    ok_ms=int((time.time() - began) * 1000))


def _note_fail(kind, began):
    _runtime.update(fail_at=time.time(), fail_kind=str(kind or "unknown"),
                    fail_ms=int((time.time() - began) * 1000))


def online_state(status=None):
    """把"配置在 / 真跑通过 / 最后一次成功"折成一个能给界面看的词。

    up       —— 最近一次调用成功，且此后没有更新的失败；
    down     —— 最近一次调用失败，或压根没配置；
    untested —— 配置在，但一次都没真跑过。**这一格以前被冒充成 up**，
                所以它必须是个独立的词，不能和 up 合并。
    """
    st = status if status is not None else online_status()
    if not st["ok"]:
        return "down"
    last_ok, last_fail = st.get("last_success_at"), st.get("last_failure_at")
    if last_ok and (not last_fail or last_ok >= last_fail):
        return "up"
    if last_fail:
        return "down"
    return "untested"


def online_chat(prompt, max_tokens=400, temperature=0.3):
    """返回 (文本, 错误说明)。失败不冷却成"不可用"——每次调用都如实报当次原因。"""
    status = online_status()
    if not status["ok"]:
        return None, status["why"]
    cfg = _state["cfg"]
    url = _LOCAL_LLM if cfg.get("local") else cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {"model": cfg["model"],
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": int(max_tokens), "temperature": float(temperature)}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        **({"Authorization": "Bearer " + str(cfg["api_key"])} if not cfg.get("local") else {})})
    began = time.time()
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            got = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        _note_fail("http_%d" % error.code, began)
        return None, "在线模型返回 HTTP %d" % error.code
    except Exception as error:
        _note_fail(type(error).__name__, began)
        return None, "连不上在线模型（%s）" % type(error).__name__
    try:
        text = ((got.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except Exception:
        text = ""
    text = str(text).strip()
    if text:
        _note_ok(cfg.get("model"), began)
        return text, ""
    _note_fail("empty_content", began)
    return None, "在线模型返回了空内容"


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
    # 三大宏量折算的热量必须和它自己报的 kcal 对得上，对不上就是模型在凑数
    from_macros = 4 * pro + 4 * carb + 9 * fat
    if kcal > 0 and abs(from_macros - kcal) / kcal > 0.45:
        problems.append("宏量和热量对不上（模型自相矛盾）")
    if problems:
        return None, "在线估算被拦下：" + "、".join(problems)
    return {"cal": kcal, "grams": grams_out, "protein_g": pro, "carbs_g": carb,
            "fat_g": fat, "basis": basis or "按常见份量估"}, ""
