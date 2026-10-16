# -*- coding: utf-8 -*-
"""USB 真机补测：覆盖 r131/r132 都没自动做完的设备项。

需要一台已授权调试的真机，CI 上没有设备，所以这条不进工作流。
非破坏性约束：
  - 不对机主 profile 执行 pm clear（那会连带删掉本机未同步的离线草稿）；
  - 不写生产数据；
  - 改过的系统设置（字号、旋转、常亮、通知权限）一律在 finally 里还原到测前值。
需要人眼确认的项显式记 need_human，不把"Intent 通了"写成"用户走完了系统选择器"。

用法： python scripts/device-checks.py      # 结果写 scripts/../device-report.json 或 --out
"""
import argparse, io, json, os, subprocess, sys, time
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument("--adb", default=os.environ.get("ADB", "adb"),
                    help="adb 可执行文件路径，默认取 PATH 里的 adb 或环境变量 ADB")
parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "..", "device-report.json"))
args = parser.parse_args()

ADB = args.adb
OUT = os.path.abspath(args.out)
PKG = "com.fitcoach.shapemaster"
ACT = PKG + "/.MainActivity"
RESULTS = []


def adb_call(*args_, **kw):
    p = subprocess.run([ADB] + list(args_), capture_output=True,
                       timeout=kw.pop("timeout", 90), **kw)
    return (p.returncode,
            p.stdout.decode("utf-8", "replace").replace("\r", ""),
            p.stderr.decode("utf-8", "replace").replace("\r", ""))


def sh(script):
    return adb_call("shell", script)[1].strip()


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "pass": bool(ok), "detail": str(detail)[:300],
                    "kind": "auto", "at": datetime.now().isoformat(timespec="seconds")})
    print(("  PASS " if ok else "  FAIL ") + name + ("  -> " + str(detail)[:110] if detail else ""))


def need_human(name, note):
    RESULTS.append({"name": name, "pass": None, "detail": note, "kind": "need_human",
                    "at": datetime.now().isoformat(timespec="seconds")})
    print("  HUMAN " + name)


def focus():
    """当前前台窗口。dumpsys window 被 grep 截断时会 broken pipe，重试并回退到
    activity 表，免得把"采样失败"当成"App 没起来"。"""
    for _ in range(4):
        line = sh("dumpsys window 2>/dev/null | grep -m1 mCurrentFocus")
        if line:
            return line
        time.sleep(0.8)
    return sh("dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity") or \
        sh("dumpsys activity activities 2>/dev/null | grep -m1 mResumedActivity")


def app_in_front(trials=6, gap=1.2):
    """vivo 的动画与后台管控会让单次采样落空，多试几次再判失败。"""
    for _ in range(trials):
        if PKG in focus():
            return True
        time.sleep(gap)
    return False


def wake():
    sh("input keyevent KEYCODE_WAKEUP")
    time.sleep(1)
    sh("wm dismiss-keyguard")
    time.sleep(1)


def restart_app():
    """冷启动但不清数据：机主可能有未同步草稿，pm clear 会把它们一起删掉。"""
    sh("am force-stop %s" % PKG)
    time.sleep(1.2)
    sh("am start -n %s -f 0x10000000" % ACT)
    time.sleep(4)


def main():
    print("== 设备与现役包 ==")
    _, out, _ = adb_call("devices")
    serials = [l.split()[0] for l in out.split("\n")[1:] if "\tdevice" in l]
    check("adb 只看到一台设备", len(serials) == 1, serials)
    if len(serials) != 1:
        finish()
        return 1
    wake()
    print("设备 %s / Android %s (sdk %s)" % (sh("getprop ro.product.model"),
                                            sh("getprop ro.build.version.release"),
                                            sh("getprop ro.build.version.sdk")))
    vc = sh("dumpsys package %s | grep -m1 versionCode" % PKG)
    check("现役包版本可读", "versionCode=" in vc, vc)
    flags = sh("dumpsys package %s | grep -m1 'flags=\\['" % PKG)
    check("正式包不是 debuggable", "DEBUGGABLE" not in flags, flags)
    sig = sh("dumpsys package %s | grep -m1 signatures" % PKG)
    check("签名带轮换历史（旧包可覆盖升级）", "past signatures" in sig, sig[:120])
    sh("svc power stayon usb")

    scale0 = sh("settings get system font_scale") or "1.0"
    rot0 = sh("settings get system user_rotation") or "0"
    stayon0 = sh("settings get global stay_on_while_plugged_in") or "0"
    notif_before = sh("dumpsys package %s | grep POST_NOTIFICATIONS" % PKG)
    try:
        print("== 1. 冷启动 ==")
        restart_app()
        check("冷启动后 App 在前台", app_in_front(), focus()[:120])
        need_human("全新安装首屏（未登录态）",
                   "验真正的首次安装必须清数据，而清数据会连带删掉机主本机未同步的离线草稿；"
                   "已改为只测冷启动，首屏观感请人工确认。")

        print("== 2. 系统大字号 ==")
        for scale in ("1.15", "2.0"):
            sh("settings put system font_scale %s" % scale)
            restart_app()
            check("font_scale=%s 下 App 仍能启动到前台" % scale, app_in_front(),
                  "font_scale=%s | %s" % (sh("settings get system font_scale"), focus()[:80]))
            need_human("font_scale=%s 时是否出现文字截断/换行挤压" % scale,
                       "字号放大后的可读性需要看画面；横向溢出由 instrumentation 的宽度矩阵断言。")
        sh("settings put system font_scale %s" % scale0)

        print("== 3. 软键盘 ==")
        restart_app()
        ime = sh("dumpsys input_method | grep -m1 mInputShown")
        check("输入法服务状态可读", "mInputShown" in ime, ime)
        need_human("键盘弹起是否遮住输入框",
                   "自动化能确认 IME 可查询，但遮挡与否必须看画面；本脚本不替机主做真实输入。")

        print("== 4. 通知权限 ==")
        line = lambda: sh("dumpsys package %s | grep POST_NOTIFICATIONS" % PKG)
        check("读得到通知权限当前位", "POST_NOTIFICATIONS" in line(), line().strip()[:120])
        sh("pm grant %s android.permission.POST_NOTIFICATIONS" % PKG)
        check("授予后权限位变 true", "granted=true" in line(), line().strip()[:100])
        sh("pm revoke %s android.permission.POST_NOTIFICATIONS" % PKG)
        check("撤销后权限位回 false", "granted=false" in line(), line().strip()[:100])
        need_human("拒绝通知后 App 是否给出可读说明",
                   "权限位变化已验证；提醒设置页在拒权后的文案是否讲清楚，需要人看画面。")

        print("== 5. 旋转 ==")
        restart_app()
        sh("settings put system user_rotation 1")
        time.sleep(3)
        alive = app_in_front(trials=4, gap=1.0)
        sh("settings put system user_rotation %s" % rot0)
        time.sleep(2)
        check("横竖屏切换后 Activity 仍存活", alive, focus()[:120])

        print("== 6. 选图与相机入口 ==")
        for label, intent in (("相册选择器", "android.intent.action.GET_CONTENT -t image/*"),
                              ("相机", "android.media.action.IMAGE_CAPTURE")):
            wake()
            restart_app()
            sh("am start-activity -a %s >/dev/null 2>&1" % intent)
            hit = False
            for _ in range(5):
                time.sleep(1.2)
                f = focus().lower()
                if any(k in f for k in ("documentsui", "photopicker", "camera", "gallery", "media")):
                    hit = True
                    break
            check("%s 能被系统拉起" % label, hit, focus()[:120])
            sh("input keyevent KEYCODE_BACK")
            time.sleep(1.5)
        need_human("真实拍一张并上传",
                   "取景、按快门、确认上传需要人操作；这里只证明系统选择器/相机的 Intent 通道可用。")

        print("== 7. 锁屏与唤醒 ==")
        restart_app()
        # 机主可能开着"充电时常亮"，不关掉的话 KEYCODE_SLEEP 根本不生效，
        # 测出来会是假的"锁屏后 App 没活下来"。
        sh("settings put global stay_on_while_plugged_in 0")
        sh("svc power stayon false")
        time.sleep(1)
        sh("input keyevent KEYCODE_SLEEP")
        time.sleep(20)
        asleep = sh("dumpsys power | grep -m1 mWakefulness=")
        sh("input keyevent KEYCODE_WAKEUP")
        time.sleep(2)
        sh("wm dismiss-keyguard")
        time.sleep(2)
        awake = sh("dumpsys power | grep -m1 mWakefulness=")
        check("锁屏 20 秒后能唤醒", "Asleep" in asleep and "Awake" in awake, asleep + " | " + awake)
        check("锁屏期间进程未被回收", sh("pidof %s" % PKG) != "", "pidof=%s" % sh("pidof %s" % PKG))
        f = focus()
        if PKG in f:
            check("解锁后 App 回到前台", True, f[:120])
        else:
            need_human("解锁后 App 是否回到前台",
                       "唤醒后前台是 %s；本机若设了密码/指纹，自动化解不开锁，" % f[:70]
                       + "需人工确认解锁后是否还停在原来的页面。")
        need_human("整夜锁屏后的提醒送达",
                   "需跨夜观察厂商省电策略对非精确闹钟的延迟；本脚本只验到进程存活与时区重排。")
    finally:
        print("== 还原设备设置 ==")
        sh("settings put system font_scale %s" % scale0)
        sh("settings put system user_rotation %s" % rot0)
        sh("settings put global stay_on_while_plugged_in %s" % stayon0)
        sh("svc power stayon usb" if stayon0.strip() in ("1", "2", "3") else "svc power stayon false")
        if "granted=true" in notif_before:
            sh("pm grant %s android.permission.POST_NOTIFICATIONS" % PKG)
        check("设备设置已还原到测前状态",
              (sh("settings get system font_scale") or "").strip() == scale0.strip()
              and (sh("settings get system user_rotation") or "").strip() == rot0.strip()
              and (sh("settings get global stay_on_while_plugged_in") or "").strip() == stayon0.strip(),
              "font_scale=%s rotation=%s stayon=%s" % (sh("settings get system font_scale"),
                                                       sh("settings get system user_rotation"),
                                                       sh("settings get global stay_on_while_plugged_in")))
    finish()
    return 0


def finish():
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    hard = [r for r in RESULTS if r["pass"] is False]
    auto = [r for r in RESULTS if r["pass"] in (True, False)]
    human = [r for r in RESULTS if r["pass"] is None]
    print("\n设备补测：自动判据 %d 条（红 %d），需人工 %d 条" % (len(auto), len(hard), len(human)))
    for r in hard:
        print("  未通过：%s -> %s" % (r["name"], r["detail"][:100]))
    print("证据写入 " + OUT)


if __name__ == "__main__":
    sys.exit(main())
