"""强制更新门的运维开关：在服务器上一条命令改最低可用构建号，不用重新发版。

用法（root 在 /opt/qingsu 下执行）：
    python3 set-min-build.py show          # 现在拦不拦、拦到几号、最近谁被挡
    python3 set-min-build.py 22            # 抬门：22 以下全部停用
    python3 set-min-build.py off           # 刹车：写 0，谁都不拦（新包没装上时用）
    python3 set-min-build.py auto          # 删掉运维文件，回落到 version.json 的策略
"""
import json, os, subprocess, sys, urllib.request, pathlib

DB_DIR = os.environ.get("QINGSU_DB_DIR", "/opt/qingsu/data")
WEB_DIR = os.environ.get("QINGSU_WEB_DIR", "/opt/qingsu/web")
TARGET = pathlib.Path(os.environ.get("QINGSU_MIN_BUILD_FILE", os.path.join(DB_DIR, "min_build")))
LOCAL = os.environ.get("QINGSU_LOCAL_API", "http://172.17.0.1:8000")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def manifest_min():
    try:
        with open(os.path.join(WEB_DIR, "version.json"), encoding="utf-8") as handle:
            return int(json.load(handle).get("min_version_code", 0) or 0)
    except Exception:
        return -1


def live():
    try:
        with opener.open(LOCAL + "/health/ready", timeout=10) as response:
            return json.load(response)
    except Exception as error:
        return {"error": type(error).__name__}


def show():
    override = TARGET.read_text(encoding="utf-8").strip() if TARGET.exists() else None
    ready = live()
    report = {
        "override_file": str(TARGET), "override": override,
        "manifest_min_version_code": manifest_min(),
        "effective_min_build_live": ready.get("min_build"),
        "build_override_present_live": ready.get("build_override"),
        "gate": ready.get("gate"), "release": ready.get("release"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def write(value):
    temp = TARGET.with_name(TARGET.name + ".new")
    temp.write_text(str(value), encoding="utf-8")
    os.chmod(temp, 0o644)
    os.replace(temp, TARGET)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "show"
    if action == "show":
        # show 必须把门的状态打印出来：只回一个退出码等于"我跑过了"，什么都没告诉运维
        return 0 if "error" not in show() else 1
    if action == "auto":
        if TARGET.exists():
            removed = str(TARGET)
            TARGET.unlink()
        else:
            removed = "本来就不存在"
        ready = live()
        want = manifest_min()
        assert ready.get("min_build") == want, \
            "已删运维文件 %s，但服务上报的 min_build=%s 和清单的 %s 不一致" % (removed, ready.get("min_build"), want)
        print("已回落清单策略 min_build=%s；%s 及更早版本现在会被挡" % (want, want - 1))
        return 0
    value = 0 if action == "off" else int(action)
    if action != "off":
        assert str(value) == action.strip(), "构建号必须是非负整数"
    write(value)
    ready = live()
    # 写完必须独立复核服务真的读到了新值：改了文件而进程还在用旧缓存，
    # 现场看起来就是"门抬了但没人被拦"，最坏会被当成"这功能没生效"。
    assert ready.get("min_build") == value, \
        "已写 %s=%s，但 /health/ready 报的是 %s（服务没读到新值）" % (TARGET, value, ready.get("min_build"))
    print("min_build=%s 已生效（运维文件 %s）" % (value, TARGET))
    show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
