"""IP → 属地：离线 xdb 解析，不联网、不新增运行时依赖。

格式取自 ip2region v3 xdb（Apache-2.0-style，作者 Leon / lionsoul2014），
这里只实现 IPv4 + 全量缓存这一条路径：库文件 11 MB，一次性读进内存换零 IO。

两条硬规矩：
1. 只输出到省一级，原始 IP 一律不入库、不出现在任何响应里；
2. 库没装 / 解析不出来时返回空串，由调用方如实显示"未知"，绝不猜。
"""
import io
import os
import re
import struct
import threading

HEADER_LEN = 256
VECTOR_INDEX_SIZE = 8
IPV4_INDEX_SIZE = 14          # sip(4) + eip(4) + data_len(2) + data_ptr(4)
DEFAULT_PATH = os.environ.get("QINGSU_IP2REGION", "/opt/qingsu/ip2region_v4.xdb")

_lock = threading.Lock()
_cache = {"key": None, "buf": b"", "error": ""}

_PROVINCE_SUFFIX = re.compile(r"(维吾尔自治区|壮族自治区|回族自治区|特别行政区|自治区|省|市)$")
_RESERVED = ("", "0", "Reserved", "IANA", "未知")


def _province(raw):
    """xdb 字段是 `国家|省份|城市|运营商|国家代码`，这里只留省一级；境外留国家。"""
    parts = (raw or "").split("|")
    country = (parts[0] if parts else "").strip()
    if country in _RESERVED:
        return ""
    if country != "中国":
        return country[:24]
    province = (parts[1] if len(parts) > 1 else "").strip()
    if not province or province == "0":
        # 库里有只到国家的记录，宁可显示"中国"也不编一个省出来
        return country
    return _PROVINCE_SUFFIX.sub("", province)[:12]



def _stat_key(path):
    try:
        st = os.stat(path)
        return "%s:%s:%s" % (path, st.st_size, st.st_mtime_ns)
    except OSError as error:
        return None if isinstance(error, FileNotFoundError) else "error"


def _ensure(path):
    """按 (大小, mtime) 缓存整库；换库文件即重读，不需要重启进程。"""
    key = _stat_key(path)
    if _cache["key"] == key and key is not None:
        return _cache["buf"]
    with _lock:
        if _cache["key"] == key and key is not None:
            return _cache["buf"]
        buf = b""
        error = ""
        if key is None:
            error = "库文件不存在"
        elif key == "error":
            error = "库文件读不到"
        else:
            try:
                with io.open(path, "rb") as f:
                    buf = f.read()
                if len(buf) < HEADER_LEN + VECTOR_INDEX_SIZE:
                    error = "库文件不完整"
                    buf = b""
            except Exception as exc:                      # 读库失败不能带崩请求
                error = type(exc).__name__
                buf = ""
        _cache["key"], _cache["buf"], _cache["error"] = key, buf, error
        return buf


def status(path=None):
    """只报通不通与原因，不报路径细节（响应里可能出现，别泄露部署结构）。"""
    path = path or DEFAULT_PATH
    buf = _ensure(path)
    if not buf:
        return {"ok": False, "why": _cache["error"] or "离线归属库未安装"}
    version, = struct.unpack_from("<H", buf, 0)
    return {"ok": True, "version": int(version), "bytes": len(buf)}


def _v4_sub_compare(ip, buff, offset):
    j = offset + 3
    for i in range(4):
        a, b = ip[i], buff[j]
        if a < b:
            return -1
        if a > b:
            return 1
        j -= 1
    return 0


def region_of(ip, path=None):
    """IPv4 → 省一级属地；解析不出、非 IPv4、库缺失一律空串。任何情况都不抛。"""
    try:
        buf = _ensure(path or DEFAULT_PATH)
        if not buf:
            return ""
        octets = (ip or "").strip().split(".")
        if len(octets) != 4:
            return ""
        nums = [int(x) for x in octets]
        if any(n < 0 or n > 255 for n in nums):
            return ""
        packed = struct.pack("4B", *nums)
        base = HEADER_LEN + (nums[0] * 256 + nums[1]) * VECTOR_INDEX_SIZE
        s_ptr, e_ptr = struct.unpack_from("<II", buf, base)
        if s_ptr == 0 or e_ptr == 0:
            return ""
        lo, hi = 0, int((e_ptr - s_ptr) / IPV4_INDEX_SIZE)
        while lo <= hi:
            mid = (lo + hi) >> 1
            p = s_ptr + mid * IPV4_INDEX_SIZE
            rec = buf[p:p + IPV4_INDEX_SIZE]
            if len(rec) < IPV4_INDEX_SIZE:
                return ""
            if _v4_sub_compare(packed, rec, 0) < 0:
                hi = mid - 1
            elif _v4_sub_compare(packed, rec, 4) > 0:
                lo = mid + 1
            else:
                d_len, = struct.unpack_from("<H", rec, 8)
                d_ptr, = struct.unpack_from("<I", rec, 10)
                return _province(buf[d_ptr:d_ptr + d_len].decode("utf-8", "replace"))
        return ""
    except Exception:
        return ""
