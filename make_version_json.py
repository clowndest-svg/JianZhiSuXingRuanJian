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


def read_gradle_version():
    g = io.open(GRADLE, encoding="utf-8", newline="").read()
    code = re.search(r"versionCode\s+(\d+)", g)
    name = re.search(r'versionName\s+"([^"]+)"', g)
    if not code or not name:
        raise SystemExit("build.gradle 里找不到 versionCode / versionName")
    return int(code.group(1)), name.group(1)


def main():
    code, name = read_gradle_version()
    if not os.path.exists(APK):
        raise SystemExit("找不到 qingsu.apk，先打包再生成清单")
    blob = io.open(APK, "rb").read()
    out = {
        "version_code": code,
        "version_name": name,
        "apk_url": "/qingsu.apk",
        "size": len(blob),
        "md5": hashlib.md5(blob).hexdigest(),
        "notes": ("打卡改为纯本地计算，不再等模型（实测 0.1 秒内返回，不再出现自相矛盾的'AI 精准解析'）；"
                  "30 天自律矩阵读满 30 天真数据并把没记录的天画成灰格；电脑版顶栏两颗点了白屏的按钮修好；"
                  "动作弹窗画布按屏幕尺寸出图；访客打气改为服务端真实计数。"),
    }
    io.open(OUT, "w", encoding="utf-8", newline="").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("version_code=%d version_name=%s size=%d md5=%s"
          % (code, name, out["size"], out["md5"][:8]))
    print("已写 %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
