# -*- coding: utf-8 -*-
"""生成 app/src/main/assets/../web 用的 version.json。

版本号与安装包指纹一律现读现算，不手抄：
以前 README 里那个 apk md5 就是手抄的，换包后忘了改，直接把下一次验收带错。
"""
import hashlib
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GRADLE = os.path.join(ROOT, "app", "build.gradle")
APK = os.path.join(ROOT, "qingsu.apk")
OUT = os.path.join(ROOT, "app", "src", "main", "web_version.json")
ASSET_JS = os.path.join(ROOT, "app", "src", "main", "assets", "app.js")


def sync_asset_build(code):
    """把构建号烧进 app.js 的 APP_BUILD——服务端那道强更门只认这个数。

    不手抄：漏改一次的后果是"新包被自己的门挡在门外"，而现场看起来像服务器坏了。
    """
    text = io.open(ASSET_JS, encoding="utf-8", newline="").read()
    hit = re.search(r"const APP_BUILD = (\d+);", text)
    if not hit:
        raise SystemExit("app.js 里找不到 APP_BUILD 常量，客户端将无法自报构建号")
    if int(hit.group(1)) != code:
        io.open(ASSET_JS, "w", encoding="utf-8", newline="").write(
            text.replace(hit.group(0), "const APP_BUILD = %d;" % code))
    return code


def apk_embedded_build():
    """读包里真正那份 assets/app.js，确认装出去的就是当前构建号。

    清单指纹对得上但资产常量是上一版的，正是"先发版后改常量"会踩的顺序坑。
    """
    import zipfile
    with zipfile.ZipFile(APK) as zf:
        for name in zf.namelist():
            if name.endswith("assets/app.js"):
                return re.search(rb"const APP_BUILD = (\d+);", zf.read(name))
    return None



def read_gradle_version():
    g = io.open(GRADLE, encoding="utf-8", newline="").read()
    code = re.search(r"versionCode\s+(\d+)", g)
    name = re.search(r'versionName\s+"([^"]+)"', g)
    if not code or not name:
        raise SystemExit("build.gradle 里找不到 versionCode / versionName")
    return int(code.group(1)), name.group(1)


def _plain(text: str) -> str:
    """把 CHANGELOG 里的 Markdown 记号去掉：弹窗是纯文本，`**` 和反引号会被原样印给用户。"""
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def latest_release_note():
    """更新说明现读 CHANGELOG 最新一条，并且只留"给用户看的那部分"。

    以前这里把整段原文塞进清单，结果更新弹窗里满屏 `**`、反引号，
    还带着"验收方式""判据"这些工程内部话——用户不需要看这些。
    """
    text = io.open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    NL = chr(10)
    lines = text.split(NL)
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            start = i
            break
    if start is None:
        raise SystemExit("CHANGELOG.md 里找不到最新版本条目，拒绝生成没有说明的版本清单")
    title = _plain(lines[start][3:])
    section = []
    for later in lines[start + 1:]:
        if later.startswith("## "):
            break
        section.append(later)

    summary = ""
    bullets = []
    index = 0
    while index < len(section):
        line = section[index].strip()
        if line and not summary:
            summary = _plain(line)
        if line.startswith("- "):
            piece = [line[2:]]
            index += 1
            while index < len(section):
                nxt = section[index]
                if not nxt.strip() or nxt.strip().startswith("- ") or nxt.strip().startswith("**"):
                    break
                piece.append(nxt.strip())
                index += 1
            bullets.append(_plain(" ".join(piece)))
            continue
        index += 1

    # 工程内部话不进用户弹窗：表结构、网关配置、验收方式这些不是给机主看的
    internal = ("消息存法", "判据", "验收方式", "nginx", "外键", "签名链接")
    bullets = [b for b in bullets if not any(word in b for word in internal)]

    parts = [title]
    if summary:
        parts.append(summary)
    if bullets:
        parts.append("")
        parts.append("更新内容：")
        parts.extend("• " + b for b in bullets[:6])
    note = NL.join(parts).strip()
    if len(note) > 600:
        note = note[:600].rstrip() + "…"
    return note

def main():
    code, name = read_gradle_version()
    sync_asset_build(code)
    if sys.argv[1:] == ["--sync-asset-build-only"]:
        print("已将 app.js APP_BUILD 同步为 %d" % code)
        return 0
    if sys.argv[1:]:
        raise SystemExit("用法：python make_version_json.py [--sync-asset-build-only]")
    if not os.path.exists(APK):
        raise SystemExit("找不到 qingsu.apk，先打包再生成清单")
    embedded = apk_embedded_build()
    if not embedded or int(embedded.group(1)) != code:
        raise SystemExit("包内 assets/app.js 的 APP_BUILD 不是 %s，装出去的客户端会自报旧构建号" % code)
    blob = io.open(APK, "rb").read()
    out = {
        "version_code": code,
        "version_name": name,
        # 默认策略就是"只许最新版"；要放行旧版得在服务器上放一个 min_build 文件踩刹车，
        # 这样"忘了抬门"不会变成静默失效。
        "min_version_code": code,
        "apk_url": "https://scientificexploration.art/qingsu.apk",
        "size": len(blob),
        "md5": hashlib.md5(blob).hexdigest(),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "notes": latest_release_note(),
    }
    io.open(OUT, "w", encoding="utf-8", newline="").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("version_code=%d version_name=%s min_version_code=%d size=%d md5=%s"
          % (code, name, out["min_version_code"], out["size"], out["md5"][:8]))
    print("已写 %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
