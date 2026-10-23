"""社区：内容校验、轻塑号、通知种类、计数口径。

放这里的都是"纯函数 + 常量"，SQL 与鉴权留在 server.py——
和 geo/mailer 一样的分工，判据可以直接 import 这些常量核对前后端一致。
"""
import json
import re
import secrets

POST_MAX = 1000
COMMENT_MAX = 500
BIO_MAX = 60
IMAGES_MAX = 9
# 标题照小红书：20 字（含标点与表情），只允许一行——两行的"标题"在信息流里就是正文
TITLE_MAX = 20
# 评论是短内容，配图 3 张够了；动图和静图走同一份文件名口径
COMMENT_IMAGES_MAX = 3
# 一条评论最多 @ 五个人：再多就变成群发骚扰，而不是"叫某人来看"
MENTION_MAX = 5
SEARCH_Q_MAX = 32
PAGE_MAX = 30
DEFAULT_PAGE = 12

# 通知种类：新增一种必须同时改前端图标映射，判据逐条核对集合相等。
# 私信不在这张表里——未读以 messages.read_at 为准，再存一份计数就会出现两边对不上。
NOTICE_KINDS = ("like", "comment", "reply", "follow", "mention")

# 气泡装扮的可选值。只影响自己这一侧的显示，所以不需要对方配合，也不需要新表。
BUBBLE_THEMES = ("green", "blue", "rose", "ink", "amber") + tuple("skin-" + name for name in (
    "ai", "luna", "sakura", "cyber", "cat", "bear", "aurora", "orbit", "holo", "pixel",
    "manga", "ghost", "rose", "heart", "moon", "cloud", "ocean", "forest", "tea", "whale"))

# 轻塑号：8 位数字，注册时随机生成，唯一且永不复用；搜索按它精确匹配
PUBLIC_ID_DIGITS = 8


def new_public_id(taken):
    """taken 是一个集合/可调用，用来避开已用号。"""
    floor = 10 ** (PUBLIC_ID_DIGITS - 1)
    span = 9 * floor
    for _ in range(64):
        cand = str(floor + secrets.randbelow(span))
        if cand not in taken:
            return cand
    return ""


def clean_body(text, limit, what):
    body = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not body:
        raise ValueError("%s不能为空" % what)
    if len(body) > limit:
        raise ValueError("%s最长 %d 字，你现在写了 %d 字" % (what, limit, len(body)))
    return body


def clean_title(text):
    """标题一律压成一行：换行在信息流卡片里会把两行摘要挤成三行。"""
    title = re.sub(r"\s*\n+\s*", " ", str(text or "")).strip()
    title = re.sub(r"\s{2,}", " ", title)
    if len(title) > TITLE_MAX:
        raise ValueError("标题最长 %d 字，你现在写了 %d 字" % (TITLE_MAX, len(title)))
    return title


def clean_images(raw, owned=None, limit=IMAGES_MAX):
    """帖子图片只允许引用已经落在上传目录里的文件名，不接受外部 URL。

    owned 传 None 时只校验形状；传集合时要求文件名在其中——防止有人把别人的
    私有媒体文件名拼进帖子，借公开接口把别人的身材照拉出来。
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:limit * 2]:
        name = str(item or "").strip()
        # 同一张图重复出现只算一次：不去重的话，客户端手滑传两份就会把配额吃掉，
        # 而且归属校验是按"去重后的集合"数的，两份同名会被误判成"有图不属于你"。
        if name in out:
            continue
        if re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|gif)", name) and (owned is None or name in owned):
            out.append(name)
        if len(out) >= limit:
            break
    return out


def images_json(names):
    return json.dumps(list(names or []), separators=(",", ":"))


def read_images(blob):
    return clean_images(blob)


def page_size(raw, default=DEFAULT_PAGE):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(PAGE_MAX, n))


def cursor_id(raw):
    """游标就是"上一页最后一条的自增 id"，0/非法一律回到最新。"""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def notice_text(kind, actor_name, snippet):
    snippet = (snippet or "").strip()
    if len(snippet) > 40:
        snippet = snippet[:40] + "…"
    if kind == "like":
        return "%s 赞了你的帖子" % actor_name
    if kind == "comment":
        return "%s 评论：%s" % (actor_name, snippet)
    if kind == "reply":
        return "%s 回复了你：%s" % (actor_name, snippet)
    if kind == "follow":
        return "%s 关注了你" % actor_name
    if kind == "mention":
        return "%s 在评论里提到了你：%s" % (actor_name, snippet)
    return actor_name
