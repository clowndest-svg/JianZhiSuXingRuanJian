# -*- coding: utf-8 -*-
"""生成轻塑官方表情包：统一 IP 形象「轻小团」的 18 个表情。

为什么要脚本生成而不是手摆 18 个文件：表情包最怕的是"画着画着换了张脸"。
共用的身体、叶子、腮红、底色都写成函数，逐张只换眉眼嘴和配件，
改一下底色全局生效。产物：app/src/main/assets/stickers/*.svg + stickers.json。

用法:
    python scripts/make-stickers.py
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "src", "main", "assets", "stickers")

GREEN = "#10B981"
DARK = "#047857"
SOFT = "#ECFDF5"
LINE = "#E2E8F0"
INK = "#0F172A"
PINK = "#FDA4AF"
BG = "#F8FAFC"


def svg(inner, size=160):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %(s)d %(s)d" '
            'width="%(s)d" height="%(s)d">%(i)s</svg>' % {"s": size, "i": inner})


def backdrop():
    return ('<rect width="160" height="160" rx="36" fill="%s"/>' % BG)


def body():
    # 团子身体 + 头顶一片叶子，所有表情共用
    return ('<ellipse cx="80" cy="96" rx="44" ry="39" fill="#FFFFFF" stroke="%s" '
            'stroke-width="2.5"/><path d="M80 52c6-12 20-16 27-8 3 4 1 10-4 11-7 2-14 5-17 11z" '
            'fill="%s"/><path d="M80 52c-6-12-20-16-27-8-3 4-1 10 4 11 7 2 14 5 17 11z" fill="%s"/>'
            % (LINE, GREEN, DARK))


def cheeks(on=True):
    if not on:
        return ""
    return ('<circle cx="55" cy="104" r="7" fill="%s" opacity=".75"/>'
            '<circle cx="105" cy="104" r="7" fill="%s" opacity=".75"/>' % (PINK, PINK))


def eyes(kind, cx=80):
    lx, rx, y = cx - 19, cx + 19, 88
    if kind == "dot":
        return ('<circle cx="%d" cy="%d" r="5.5" fill="%s"/><circle cx="%d" cy="%d" r="5.5" '
                'fill="%s"/>' % (lx, y, INK, rx, y, INK))
    if kind == "happy":          # 弯弯笑眼
        return ('<path d="M%d %d q6 -8 12 0" fill="none" stroke="%s" stroke-width="4" '
                'stroke-linecap="round"/><path d="M%d %d q6 -8 12 0" fill="none" stroke="%s" '
                'stroke-width="4" stroke-linecap="round"/>'
                % (lx - 6, y, INK, rx - 6, y, INK))
    if kind == "sleep":          # 闭眼
        return ('<path d="M%d %d q6 7 12 0" fill="none" stroke="%s" stroke-width="4" '
                'stroke-linecap="round"/><path d="M%d %d q6 7 12 0" fill="none" stroke="%s" '
                'stroke-width="4" stroke-linecap="round"/>'
                % (lx - 6, y, INK, rx - 6, y, INK))
    if kind == "wide":           # 睁大眼
        return ('<circle cx="%d" cy="%d" r="8" fill="#FFFFFF" stroke="%s" stroke-width="2.5"/>'
                '<circle cx="%d" cy="%d" r="3.5" fill="%s"/>'
                '<circle cx="%d" cy="%d" r="8" fill="#FFFFFF" stroke="%s" stroke-width="2.5"/>'
                '<circle cx="%d" cy="%d" r="3.5" fill="%s"/>'
                % (lx, y, INK, lx, y, INK, rx, y, INK, rx, y, INK))
    if kind == "heart":
        return ('<path d="M%d %d c-8 -9 -16 -2 -8 6 l8 8 8 -8 c8 -8 0 -15 -8 -6z" fill="%s"/>'
                '<path d="M%d %d c-8 -9 -16 -2 -8 6 l8 8 8 -8 c8 -8 0 -15 -8 -6z" fill="%s"/>'
                % (lx - 8, y + 2, "#F87171", rx - 8, y + 2, "#F87171"))
    if kind == "angry":          # 倒眉 + 细眼
        return ('<path d="M%d %d l14 -6" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
                '<path d="M%d %d l-14 -6" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
                '<circle cx="%d" cy="%d" r="4.5" fill="%s"/><circle cx="%d" cy="%d" r="4.5" '
                'fill="%s"/>' % (lx + 7, y - 4, INK, rx - 7, y - 4, INK, lx, y + 2, INK, rx, y + 2, INK))
    if kind == "cool":           # 墨镜
        return ('<path d="M%d %d h38" stroke="%s" stroke-width="4"/><rect x="%d" y="%d" width="15" '
                'height="12" rx="5" fill="%s"/><rect x="%d" y="%d" width="15" height="12" rx="5" '
                'fill="%s"/>' % (lx - 12, y - 4, INK, lx - 12, y - 5, INK, rx - 3, y - 5, INK))
    return ""


def mouth(kind, cx=80):
    y = 110
    if kind == "smile":
        return ('<path d="M%d %d q10 10 20 0" fill="none" stroke="%s" stroke-width="3.5" '
                'stroke-linecap="round"/>' % (cx - 10, y - 4, INK))
    if kind == "grin":
        return ('<path d="M%d %d q%d 18 20 0z" fill="%s"/>'
                '<path d="M%d %d q10 12 20 0" fill="%s" stroke="%s" stroke-width="2.5"/>'
                % (cx - 16, y - 6, 10, "#F87171", cx - 16, y - 6, INK, INK))
    if kind == "open":           # 大哭/大笑嘴
        return ('<ellipse cx="%d" cy="%d" rx="9" ry="11" fill="%s"/>' % (cx, y + 2, "#F87171"))
    if kind == "flat":
        return ('<path d="M%d %d h18" stroke="%s" stroke-width="3.5" stroke-linecap="round"/>'
                % (cx - 9, y, INK))
    if kind == "wave":           # 无语/馋
        return ('<path d="M%d %d q5 -6 9 0 q5 6 9 0" fill="none" stroke="%s" stroke-width="3.5" '
                'stroke-linecap="round"/>' % (cx - 9, y, INK))
    if kind == "ouch":           # 小 O 嘴
        return '<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (cx, y, "#F87171")
    return ""


def tear(x=68):
    return ('<path d="M%d 98 c-5 8 5 10 0 16 -5 -6 5 -8 0 -16z" fill="%s"/>' % (x, "#60A5FA"))


def extra(kind):
    if kind == "sweatdrop":
        return ('<path d="M126 74 c-7 12 7 14 0 22 -7 -8 7 -10 0 -22z" fill="%s"/>'
                '<circle cx="34" cy="70" r="4" fill="%s" opacity=".6"/>' % ("#60A5FA", "#94A3B8"))
    if kind == "sleep":
        return ('<path d="M116 40 q6 -8 14 -4 -8 4 -4 12 z" fill="%s"/>'
                '<text x="132" y="34" font-size="16" fill="%s">z</text>'
                '<text x="144" y="22" font-size="12" fill="%s">z</text>' % ("#FCD34D", "#94A3B8", "#94A3B8"))
    if kind == "dumbbell":
        return ('<rect x="34" y="96" width="86" height="8" rx="4" fill="%s"/>'
                '<rect x="24" y="84" width="14" height="32" rx="5" fill="%s"/>'
                '<rect x="116" y="84" width="14" height="32" rx="5" fill="%s"/>' % (INK, "#64748B", "#64748B"))
    if kind == "cup":
        return ('<path d="M104 100 h34 v26 a10 10 0 0 1 -10 10 h-14 a10 10 0 0 1 -10 -10z" '
                'fill="#FFFFFF" stroke="%s" stroke-width="2.5"/>'
                '<path d="M104 106 h34" stroke="%s" stroke-width="3"/><path d="M126 92 c8 -6 8 -14 0 -20" '
                'fill="none" stroke="%s" stroke-width="3" stroke-linecap="round"/>' % (LINE, GREEN, GREEN))
    if kind == "leafinmouth":
        return ('<path d="M96 112 q22 -6 30 6 -22 8 -30 -6z" fill="%s"/>' % GREEN)
    if kind == "run":
        return ('<path d="M20 78 h22" stroke="%s" stroke-width="3" stroke-linecap="round" '
                'opacity=".5"/><path d="M14 92 h18" stroke="%s" stroke-width="3" '
                'stroke-linecap="round" opacity=".5"/>' % (GREEN, GREEN))
    if kind == "confetti":
        return ('<rect x="30" y="44" width="8" height="8" rx="2" fill="%s"/>'
                '<rect x="120" y="52" width="8" height="8" rx="2" fill="%s"/>'
                '<rect x="46" y="34" width="7" height="7" rx="2" fill="%s"/>'
                '<rect x="106" y="36" width="7" height="7" rx="2" fill="%s"/>' % (GREEN, PINK, "#FCD34D", "#60A5FA"))
    if kind == "heart":
        return ('<path d="M80 62 c-14 -16 -32 -6 -18 12 l18 18 18 -18 c14 -18 -4 -28 -18 -12z" '
                'fill="%s" opacity=".9"/>' % "#F87171")
    if kind == "anger":
        return ('<path d="M124 66 l14 -10 -6 16z" fill="%s"/>' % "#EF4444")
    if kind == "beg":
        return ('<ellipse cx="58" cy="128" rx="12" ry="8" fill="#FFFFFF" stroke="%s" '
                'stroke-width="2.5"/><ellipse cx="102" cy="128" rx="12" ry="8" fill="#FFFFFF" '
                'stroke="%s" stroke-width="2.5"/>' % (LINE, LINE))
    if kind == "win":
        return ('<path d="M56 118 l8 18 14 -22" fill="none" stroke="%s" stroke-width="4" '
                'stroke-linecap="round"/><text x="110" y="52" font-size="18" fill="%s">✦</text>'
                % (GREEN, "#FCD34D"))
    if kind == "band":
        return ('<path d="M38 76 q42 -26 84 0" fill="none" stroke="%s" stroke-width="5" '
                'stroke-linecap="round"/><path d="M78 66 l8 8 8 -8 -8 -8z" fill="%s"/>'
                % ("#EF4444", "#EF4444"))
    return ""


# 每张 = (id, 名字, 分组, 拼音, 标签, 眼神, 嘴型, 配件, 腮红)
FACES = [
    ("smile",   "微笑",    "日常", "weixiao",  ["笑", "开心", "hi"],        "dot",   "smile", None,        True),
    ("laugh",   "大笑",    "日常", "daxiao",   ["哈哈", "好笑"],            "happy", "grin",  None,        True),
    ("cry",     "委屈",    "日常", "weiqu",    ["哭", "想哭"],              "dot",   "open",  "tear",      True),
    ("cheer",   "加油",    "减脂", "jiayou",   ["打气", "坚持"],            "dot",   "grin",  "band",      True),
    ("water",   "喝水",    "减脂", "heshui",   ["水杯", "排钠"],            "happy", "smile", "cup",       True),
    ("veg",     "吃菜",    "减脂", "chicai",   ["蔬菜", "沙拉"],            "happy", "leafinmouth", None,   True),
    ("run",     "跑步",    "减脂", "paobu",    ["运动", "有氧"],            "dot",   "open",  "run",       True),
    ("fit",     "举铁",    "减脂", "jutie",    ["力量", "撸铁"],            "angry", "flat",  "dumbbell",  False),
    ("shy",     "害羞",    "日常", "haixiu",   ["脸红", "羞"],               "sleep", "wave",  None,        True),
    ("sleep",   "睡了",    "日常", "shuile",   ["晚安", "困"],              "sleep", "smile", "sleep",     False),
    ("love",    "喜欢",    "日常", "xihuan",   ["爱心", "爱了"],            "heart", "smile", "heart",     True),
    ("cool",    "酷",      "日常", "ku",       ["墨镜", "帅"],              "cool",  "flat",  None,        False),
    ("angry",   "生气",    "日常", "shengqi",  ["气", "怒"],                "angry", "wave",  "anger",     False),
    ("sweat",   "无语",    "日常", "wuyu",     ["汗", "尴尬"],              "dot",   "wave",  "sweatdrop", False),
    ("drool",   "馋了",    "日常", "chanle",   ["想吃", "馋"],              "wide",  "ouch",  None,        True),
    ("party",   "庆祝",    "日常", "qingzhu",  ["恭喜", "牛"],              "happy", "grin",  "confetti",  True),
    ("win",     "胜利",    "日常", "shengli",  ["耶", "V"],                 "happy", "grin",  "win",       True),
    ("beg",     "拜托",    "日常", "baituo",   ["求了", "拜托"],            "wide",  "wave",  "beg",       True),
]


def build():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    items = []
    for sid, name, group, pinyin, tags, eye, mouth_kind, extra_kind, cheek in FACES:
        parts = [backdrop(), body(), cheeks(cheek),
                 '<g transform="translate(0,%d)">%s</g>' % (-14, eyes(eye)),
                 '<g transform="translate(0,-2)">%s</g>' % mouth(mouth_kind),
                 extra(extra_kind) if extra_kind else ""]
        inner = "".join(p for p in parts if p)
        with io.open(os.path.join(OUT, sid + ".svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(svg(inner))
        items.append({"id": sid, "name": name, "group": group, "pinyin": pinyin,
                      "tags": tags, "file": "stickers/" + sid + ".svg"})
    with io.open(os.path.join(os.path.dirname(OUT), "stickers.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"version": 1, "items": items}, f, ensure_ascii=False, indent=1)
    print("已生成 %d 个表情 -> %s" % (len(items), OUT))


if __name__ == "__main__":
    build()
