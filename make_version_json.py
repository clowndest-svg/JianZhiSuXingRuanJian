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
        "notes": ("顾问接入本机模型与每用户长期记忆；身体数据不再由系统编造；"
                  "App 启动自检通知权限；外卖面板显示真实使用情况；顶栏切换按钮改纯图标。"),
    }
    io.open(OUT, "w", encoding="utf-8", newline="").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("version_code=%d version_name=%s size=%d md5=%s"
          % (code, name, out["size"], out["md5"][:8]))
    print("已写 %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
