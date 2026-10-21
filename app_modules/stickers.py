"""Licensed Commons stickers, with no API key, disk writes or image decoding.

search(q, uid, secret, *, opener=None) -> {"items": [..]}
import_media(id, uid, secret, *, opener=None) -> (bytes, attribution_dict)

``uid`` is a positive integer; ``secret`` accepts bytes or UTF-8 text. The
optional opener is a urllib-style callable (Request, timeout=8), for offline
tests. It is used for both API requests and downloads. The caller MUST decode /
re-encode the returned image, or validate its GIF frames, before storing it:
API and HTTP MIME declarations are only hints, not image-content validation.
"""
import base64
from collections import OrderedDict
import hashlib
import hmac
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


API_URL = "https://commons.wikimedia.org/w/api.php"
TIMEOUT = 8
API_LIMIT = 2 * 1024 * 1024
MEDIA_LIMIT = 8 * 1024 * 1024
RESULT_LIMIT = 12
THUMB_SIZE = 720
TOKEN_TTL = 15 * 60
CACHE_TTL = 5 * 60
CACHE_LIMIT = 128
OPENMOJI_BASE = "https://raw.githubusercontent.com/hfg-gmuend/openmoji/17.0.0/"
OPENMOJI_CATALOG = OPENMOJI_BASE + "data/openmoji.json"
_openmoji = (0, ())
MEME_API = 'https://api.memegen.link/templates'
_memes = (0, ())

# 中文梗图：公开图片检索结果。只取检索站自己的 HTTPS 缩略图，不直连结果页外链。
SO360_API = "https://image.so.com/j"
BAIDU_API = "https://image.baidu.com/search/acjson"
CN_LICENSE = "版权归原作者，来源未声明许可"
CN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CN_SEARCH_TTL = 10 * 60
CN_RESULT_TTL = 15 * 60
_cn_search = OrderedDict()
_cn_results = OrderedDict()

_MEDIA_HOSTS = frozenset(("upload.wikimedia.org", "thumb.wikimedia.org"))
_CN_360_HOST = re.compile(r"p[0-9]{1,3}\.ssl\.qhimgs1\.com")
_CN_BAIDU_HOST = re.compile(r"img[0-9]{1,3}\.baidu\.com")
_RASTER_MIMES = frozenset((
    "image", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "image/x-ms-bmp", "image/tiff", "image/x-icon", "image/vnd.microsoft.icon",
    "image/avif",
))
_QUERY_WORDS = {
    "开心": "happy", "高兴": "happy", "快乐": "happy", "加油": "cheer",
    "鼓励": "encourage", "点赞": "thumbs up", "赞": "thumbs up",
    "谢谢": "thanks", "感谢": "thanks", "哈哈": "laugh", "大笑": "laugh",
    "微笑": "smile", "笑脸": "smile", "难过": "sad", "伤心": "sad",
    "哭": "cry", "生气": "angry", "惊讶": "surprised", "爱心": "love",
    "喜欢": "love", "拥抱": "hug", "晚安": "sleep", "困": "sleep",
    "可爱": "cute", "你好": "hello", "再见": "bye",
}
_cache = OrderedDict()
_cache_lock = threading.Lock()


class InvalidSticker(ValueError):
    def __init__(self, message="表情无效或已过期，请重新搜索"):
        super().__init__(message)


class ProviderUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("表情来源暂时不可用，请稍后重试")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never follow even same-host redirects (including 307/308).
        raise HTTPError(req.full_url, code, "Redirect refused", headers, fp)


# Ordinary CA-verified HTTPS, no custom trust roots, cookies or credentials.
_http = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))


def _https_parts(url, hosts):
    if (not isinstance(url, str) or not url or len(url) > 4096
            or re.search(r"[\x00-\x20\x7f\\]", url)):
        raise InvalidSticker()
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (parts.scheme != "https" or host not in hosts
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443)
                or parts.netloc.lower() not in (host, host + ":443")
                or parts.fragment):
            raise InvalidSticker()
        return parts
    except ValueError:
        raise InvalidSticker() from None


def _media_url(url):
    """Exact hosts/path, HTTPS:443, no userinfo; remove all tracking queries."""
    if isinstance(url, str) and url.startswith('https://api.memegen.link/'):
        parts = _https_parts(url, frozenset(('api.memegen.link',)))
        if not re.fullmatch(r'/images/[a-z0-9-]{1,64}\.jpg', parts.path):
            raise InvalidSticker()
        return urlunsplit(('https', parts.hostname, parts.path, '', ''))
    if isinstance(url, str) and url.startswith(OPENMOJI_BASE):
        parts = _https_parts(url, frozenset(('raw.githubusercontent.com',)))
        if not re.fullmatch(r'/hfg-gmuend/openmoji/17\.0\.0/color/72x72/[A-F0-9]+(?:-[A-F0-9]+)*\.png', parts.path):
            raise InvalidSticker()
        return urlunsplit(('https', parts.hostname, parts.path, '', ''))
    if isinstance(url, str):
        try:
            candidate = urlsplit(url)
            host = candidate.hostname
        except ValueError:
            raise InvalidSticker() from None
        if host and _CN_360_HOST.fullmatch(host):
            parts = _https_parts(url, frozenset((host,)))
            path = unquote(parts.path, errors="strict")
            if not re.fullmatch(r"/t[0-9a-f]{6,64}\.(?:jpe?g|png|gif|webp)", path):
                raise InvalidSticker()
            return urlunsplit(("https", host, parts.path, "", ""))
        if host and _CN_BAIDU_HOST.fullmatch(host):
            parts = _https_parts(url, frozenset((host,)))
            path = unquote(parts.path, errors="strict")
            base, *params = path.split("&")
            if not re.fullmatch(r"/it/u=[0-9]+,[0-9]+", base):
                raise InvalidSticker()
            for param in params:
                key, _, value = param.partition("=")
                if (key not in {"fm", "fmt", "app", "f"}
                        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value)):
                    raise InvalidSticker()
            allowed = {}
            for key, value in parse_qsl(parts.query, keep_blank_values=False):
                if (key in {"fm", "fmt", "app", "f", "w", "h"}
                        and re.fullmatch(r"[A-Za-z0-9_.-]{1,20}", key)
                        and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value)):
                    allowed[key] = value
            return urlunsplit(("https", host, parts.path, urlencode(sorted(allowed.items())), ""))
    parts = _https_parts(url, _MEDIA_HOSTS)
    try:
        path = unquote(parts.path, errors="strict")
    except (UnicodeError, ValueError):
        raise InvalidSticker() from None
    if (not parts.path.startswith("/wikipedia/commons/")
            or not path.startswith("/wikipedia/commons/")
            or re.search(r"[\x00-\x1f\x7f\\]", path)
            or any(segment in (".", "..", "") for segment in path.split("/")[1:])):
        raise InvalidSticker()
    return urlunsplit(("https", parts.hostname, parts.path, "", ""))


def _read_url(url, limit, *, image=False, opener=None, headers=None):
    # All connections, including through an injected opener, pass these guards.
    if image:
        url = _media_url(url)
    else:
        parts = _https_parts(url, frozenset(("commons.wikimedia.org", "raw.githubusercontent.com",
                                             "api.memegen.link", "image.so.com", "image.baidu.com")))
        if not ((parts.hostname == 'commons.wikimedia.org' and parts.path == '/w/api.php')
                or url in (OPENMOJI_CATALOG, MEME_API)
                or (parts.hostname == 'image.so.com' and parts.path == '/j')
                or (parts.hostname == 'image.baidu.com' and parts.path == '/search/acjson')):
            raise InvalidSticker()
    response = None
    deadline = time.monotonic() + TIMEOUT
    try:
        request = Request(url, headers={
            "User-Agent": "QingsuStickers/1.0 (licensed Wikimedia Commons emoticons)",
            "Accept": "image/*" if image else "application/json",
            "Accept-Encoding": "identity",
            **(headers or {}),
        })
        response = (opener or _http.open)(request, timeout=TIMEOUT)
        # A custom opener must not silently follow redirects either.
        if response.getcode() != 200 or response.geturl() != url:
            raise ProviderUnavailable()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if image and content_type not in _RASTER_MIMES:
            raise InvalidSticker()
        if (not image and content_type != "application/json"
                and not (parts.hostname == "image.so.com"
                         and content_type in ("application/javascript", "text/javascript"))
                and not (url == OPENMOJI_CATALOG and content_type == 'text/plain')):
            raise ProviderUnavailable()
        if response.headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
            raise ProviderUnavailable()
        length = response.headers.get("Content-Length")
        if length is not None:
            if not re.fullmatch(r"[0-9]{1,20}", length.strip()):
                raise ProviderUnavailable()
            if int(length) > limit:
                raise InvalidSticker() if image else ProviderUnavailable()
        chunks, size = [], 0
        # read1 avoids waiting to fill an entire chunk on a trickling response.
        read = getattr(response, "read1", response.read)
        while True:
            if time.monotonic() >= deadline:
                raise ProviderUnavailable()
            chunk = read(min(64 * 1024, limit + 1 - size))
            if time.monotonic() >= deadline:
                raise ProviderUnavailable()
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise InvalidSticker() if image else ProviderUnavailable()
            chunks.append(chunk)
        if not size:
            raise InvalidSticker() if image else ProviderUnavailable()
        if length is not None and size != int(length):
            raise ProviderUnavailable()
        return b"".join(chunks)
    except (InvalidSticker, ProviderUnavailable):
        raise
    except HTTPError as error:
        error.close()
        raise ProviderUnavailable() from None
    except Exception:
        # No provider response body, IP, TLS detail or internal exception leaks.
        raise ProviderUnavailable() from None
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif not self.hidden and tag in ("br", "p", "div", "li", "tr"):
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ("p", "div", "li", "tr"):
            self.text.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def _plain(value, limit=400):
    if not isinstance(value, str):
        return ""
    parser = _Text()
    parser.feed(unescape(value[:16384]))
    parser.close()
    text = "".join(parser.text)
    # Also remove residual / entity-encoded tag delimiters and control chars.
    text = re.sub(r"<[^>]*>", " ", unescape(text)).replace("<", "").replace(">", "")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())[:limit]


def _metadata_value(metadata, key):
    entry = metadata.get(key)
    return _plain(entry.get("value")) if isinstance(entry, dict) else ""


def _license(metadata):
    name = _metadata_value(metadata, "LicenseShortName")
    normalized = re.sub(r"[-\s]+", " ", name.upper()).strip()
    match = re.fullmatch(r"CC BY( SA)?(?: (1\.0|2\.0|2\.5|3\.0|4\.0))?", normalized)
    url = _metadata_value(metadata, "LicenseUrl")
    if match:
        family = "by-sa" if match.group(1) else "by"
        version = match.group(2)
        if url:
            # Avoid accepting an NC/ND licence mislabelled with a BY short name.
            parts = urlsplit(url)
            license_match = re.fullmatch(r"/licenses/(by|by-sa)/(1\.0|2\.0|2\.5|3\.0|4\.0)/?", parts.path)
            if (parts.scheme not in ("http", "https")
                    or parts.netloc not in ("creativecommons.org", "www.creativecommons.org")
                    or not license_match or license_match.group(1) != family
                    or (version and license_match.group(2) != version)):
                raise InvalidSticker()
            version = license_match.group(2)
        return ("CC BY-SA" if family == "by-sa" else "CC BY") + (" " + version if version else "")
    if normalized in ("CC0", "CC0 1.0"):
        if url and not re.fullmatch(r"https?://(?:www\.)?creativecommons\.org/publicdomain/zero/1\.0/?", url):
            raise InvalidSticker()
        return "CC0" if normalized == "CC0" else "CC0 1.0"
    if normalized in ("PUBLIC DOMAIN", "PD"):
        return "Public domain"
    raise InvalidSticker()


def _positive_int(value):
    return type(value) is int and 0 < value <= 2 ** 63 - 1


def _record(page):
    if (not isinstance(page, dict) or not _positive_int(page.get("pageid"))
            or page.get("ns") != 6 or page.get("missing") is not None):
        raise InvalidSticker()
    title = page.get("title")
    if (not isinstance(title, str) or not title.startswith("File:")
            or len(title) > 1024 or re.search(r"[\x00-\x1f\x7f]", title)):
        raise InvalidSticker()
    infos = page.get("imageinfo")
    if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
        raise InvalidSticker()
    info = infos[0]
    mime = info.get("mime")
    if (mime not in _RASTER_MIMES or not _positive_int(info.get("size"))
            or info["size"] > MEDIA_LIMIT
            or not _positive_int(info.get("width")) or not _positive_int(info.get("height"))):
        raise InvalidSticker()
    metadata = info.get("extmetadata")
    if not isinstance(metadata, dict):
        raise InvalidSticker()
    license_name = _license(metadata)
    original = _media_url(info.get("url"))
    small = max(info["width"], info["height"]) <= THUMB_SIZE
    if mime == "image/gif" and small:
        preview = original
    elif info.get("thumburl"):
        if (not _positive_int(info.get("thumbwidth")) or not _positive_int(info.get("thumbheight"))
                or max(info["thumbwidth"], info["thumbheight"]) > THUMB_SIZE
                or info.get("thumbmime", mime) not in _RASTER_MIMES):
            raise InvalidSticker()
        preview = _media_url(info["thumburl"])
    elif small:
        preview = original
    else:
        raise InvalidSticker()
    # Build the Commons file page ourselves; never trust an external description URL.
    source = "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe=":")
    return {
        "pageid": page["pageid"], "title": _plain(title[5:], 300),
        "preview_url": preview, "source_url": source, "license": license_name,
        "author": _metadata_value(metadata, "Artist") or "未知作者",
        # Preserve GIF animation; all other formats download the bounded thumbnail.
        "download_url": original if mime == "image/gif" else preview,
    }


def _api(params, opener):
    query = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": str(THUMB_SIZE), "iiurlheight": str(THUMB_SIZE),
        "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist",
    }
    query.update(params)
    body = _read_url(API_URL + "?" + urlencode(query), API_LIMIT, opener=opener)
    try:
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict) or "error" in data or "errors" in data:
            raise ValueError()
        if "query" not in data:
            if data.get("batchcomplete") is True:
                return []
            raise ValueError()
        pages = data["query"]["pages"]
        if not isinstance(pages, list):
            raise ValueError()
        return pages
    except (ValueError, UnicodeError, TypeError, KeyError):
        raise ProviderUnavailable() from None


def _identity(uid, secret):
    if not _positive_int(uid):
        raise InvalidSticker()
    try:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
    except UnicodeError:
        raise InvalidSticker() from None
    if not isinstance(key, bytes) or not key:
        raise InvalidSticker()
    return key


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError()
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(decoded) != value:
        raise ValueError()
    return decoded


def _sign(pageid, uid, key):
    payload = json.dumps({"pageid": pageid, "uid": uid, "exp": int(time.time()) + TOKEN_TTL},
                         separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(key, b"commons-sticker-v1\0" + payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(signature)


def _verify(sticker_id, uid, key):
    try:
        if not isinstance(sticker_id, str) or len(sticker_id) > 512:
            raise ValueError()
        encoded, signed = sticker_id.split(".")
        payload, signature = _unb64(encoded), _unb64(signed)
        expected = hmac.new(key, b"commons-sticker-v1\0" + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(payload.decode("utf-8"))
        now = int(time.time())
        if (not isinstance(data, dict) or set(data) != {"pageid", "uid", "exp"}
                or not _positive_int(data["pageid"]) or not _positive_int(data["uid"])
                or data["uid"] != uid or type(data["exp"]) is not int
                or not now < data["exp"] <= now + TOKEN_TTL):
            raise ValueError()
        return data["pageid"]
    except (ValueError, UnicodeError, TypeError, KeyError):
        raise InvalidSticker() from None


def _search_terms(q):
    if (not isinstance(q, str) or not 1 <= len(q) <= 60
            or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", q)):
        raise InvalidSticker("搜索词须为1到60个字符")
    q = " ".join(q.split())
    if not q:
        raise InvalidSticker("搜索词须为1到60个字符")
    # Replace just the recognized words; unrelated words / modifiers survive.
    for word in sorted(_QUERY_WORDS, key=len, reverse=True):
        q = q.replace(word, " " + _QUERY_WORDS[word] + " ")
    return " ".join(q.split()) + " emoticon filetype:bitmap"


def search_commons(q, uid, secret, *, opener=None):
    """Search at most 12 licensed raster files; every call signs its own IDs."""
    key = _identity(uid, secret)
    terms = _search_terms(q)
    now = time.monotonic()
    with _cache_lock:
        for expired in [k for k, (until, _) in _cache.items() if until <= now]:
            del _cache[expired]
        cached = _cache.get(terms)
        records = cached[1] if cached else None
        if cached:
            _cache.move_to_end(terms)
    if records is None:
        pages = _api({"generator": "search", "gsrsearch": terms,
                      "gsrnamespace": "6", "gsrlimit": str(RESULT_LIMIT)}, opener)
        pages = sorted(pages, key=lambda p: p.get("index", RESULT_LIMIT + 1)
                       if isinstance(p, dict) and type(p.get("index")) is int else RESULT_LIMIT + 1)
        records = []
        for page in pages[:RESULT_LIMIT]:
            try:
                records.append(_record(page))
            except InvalidSticker:
                continue
        records = tuple(records)
        with _cache_lock:
            _cache[terms] = (time.monotonic() + CACHE_TTL, records)
            _cache.move_to_end(terms)
            while len(_cache) > CACHE_LIMIT:
                _cache.popitem(last=False)
    return {"items": [dict(
        id=_sign(record["pageid"], uid, key),
        **{field: record[field] for field in ("title", "preview_url", "source_url", "license", "author")}
    ) for record in records]}


def import_media(id, uid, secret, *, opener=None):
    """Verify a user-bound ID, re-fetch its current licence/URL, then download."""
    if isinstance(id, str) and id.startswith('cn.'):
        key = _identity(uid, secret)
        try:
            parts = id.split('.', 3)
            if (len(parts) != 4 or not re.fullmatch(r'[a-f0-9]{16}', parts[1])
                    or not re.fullmatch(r'[0-9]{1,3}', parts[2])):
                raise ValueError()
            index = int(parts[2])
            if _verify(parts[3], uid, key) != index + 1:
                raise ValueError()
        except ValueError:
            raise InvalidSticker() from None
        records = _cn_lookup(parts[1])
        if records is None or index >= len(records):
            raise InvalidSticker()
        record = records[index]
        blob = _read_url(record['download_url'], MEDIA_LIMIT, image=True, opener=opener)
        return blob, {field: record[field] for field in ('title', 'source_url', 'license', 'author')}
    if isinstance(id, str) and id.startswith('mg.'):
        key = hmac.digest(_identity(uid, secret), b'memegen-v1', 'sha256')
        wanted = _verify(id[3:], uid, key)
        record = next((r for r in _meme_records(opener) if _meme_id(r['slug']) == wanted), None)
        if record is None:
            raise InvalidSticker()
        blob = _read_url(record.get('download_url') or record['preview_url'], MEDIA_LIMIT, image=True, opener=opener)
        return blob, {f: record[f] for f in ('title', 'source_url', 'license', 'author')}
    if isinstance(id, str) and id.startswith('om.'):
        key = hmac.digest(_identity(uid, secret), b'openmoji-v1', 'sha256')
        index = _verify(id[3:], uid, key) - 1
        records = _openmoji_records(opener)
        if not 0 <= index < len(records):
            raise InvalidSticker()
        record = records[index]
        blob = _read_url(record['preview_url'], MEDIA_LIMIT, image=True, opener=opener)
        return blob, {field: record[field] for field in ('source_url', 'license', 'author', 'title')}
    key = _identity(uid, secret)
    pageid = _verify(id, uid, key)
    # Deliberately bypass the search cache: revoked licences and moved files matter.
    pages = _api({"pageids": str(pageid)}, opener)
    page = next((page for page in pages if isinstance(page, dict) and page.get("pageid") == pageid), None)
    record = _record(page)
    blob = _read_url(record["download_url"], MEDIA_LIMIT, image=True, opener=opener)
    metadata = {field: record[field] for field in ("source_url", "license", "author", "title")}
    return blob, metadata


def _openmoji_records(opener=None):
    global _openmoji
    with _cache_lock:
        until, records = _openmoji
    if until > time.monotonic():
        return records
    # Ship the fixed-version search index; downloading its 2MB catalog per cold
    # worker is slow on the production route. Actual PNGs still come upstream.
    raw = ((Path(__file__).with_name('openmoji-17.json')).read_bytes() if opener is None
           else _read_url(OPENMOJI_CATALOG, 4 * 1024 * 1024, opener=opener))
    try:
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) > 10000:
            raise ValueError()
        records = []
        for item in data:
            code = item.get('hexcode', '')
            if not isinstance(code, str) or not re.fullmatch(r'[A-F0-9]+(?:-[A-F0-9]+)*', code) or len(code) > 160:
                raise ValueError()
            records.append(dict(title=_plain(item.get('annotation'), 200),
                author=_plain(item.get('openmoji_author'), 200) or 'OpenMoji contributors',
                license='CC BY-SA 4.0', source_url='https://openmoji.org/library/emoji-' + code + '/',
                preview_url=OPENMOJI_BASE + 'color/72x72/' + code + '.png',
                terms=' '.join(str(item.get(k, '')) for k in ('annotation', 'tags', 'openmoji_tags')).lower()))
        records = tuple(records)
    except (ValueError, TypeError, AttributeError):
        raise ProviderUnavailable() from None
    with _cache_lock:
        _openmoji = (time.monotonic() + 3600, records)
    return records


def _cn_query(q):
    if (not isinstance(q, str) or not 1 <= len(q) <= 60
            or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", q)):
        raise InvalidSticker("搜索词须为1到60个字符")
    q = " ".join(q.split())
    if not q:
        raise InvalidSticker("搜索词须为1到60个字符")
    return q


def _cn_360_url(term):
    return SO360_API + "?" + urlencode({"q": term, "src": "srp", "correct": term, "pn": 0, "rn": 48})


def _cn_baidu_url(term):
    return BAIDU_API + "?" + urlencode({"tn": "resultjson_com", "ipn": "rj", "word": term, "pn": 0, "rn": 30})


def _cn_page_url(value, fallback):
    try:
        if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
            return fallback
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443) or parts.fragment):
            return fallback
        return urlunsplit(("https", parts.hostname, parts.path, parts.query, ""))
    except ValueError:
        return fallback


def _cn_title(value):
    text = _plain(value, 120) or "中文梗图"
    return text if len(text) <= 18 else text[:17] + "…"


def _cn_size(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if 0 < number <= 10000 else 0


def _cn_cached(source, term, loader):
    key = (source, term)
    now = time.monotonic()
    with _cache_lock:
        for expired in [k for k, (until, _) in _cn_search.items() if until <= now]:
            del _cn_search[expired]
        hit = _cn_search.get(key)
        if hit:
            _cn_search.move_to_end(key)
            return hit[1]
    records = tuple(loader())
    with _cache_lock:
        _cn_search[key] = (time.monotonic() + CN_SEARCH_TTL, records)
        _cn_search.move_to_end(key)
        while len(_cn_search) > 64:
            _cn_search.popitem(last=False)
    return records


def _cn_records_360(term, opener=None):
    raw = _read_url(_cn_360_url(term), API_LIMIT, opener=opener,
                    headers={"Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
                             "Referer": "https://image.so.com/"})
    try:
        data = json.loads(raw)
        items = data.get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError()
    except (ValueError, TypeError):
        raise ProviderUnavailable() from None
    records = []
    for item in items[:48]:
        if not isinstance(item, dict):
            continue
        try:
            image = _media_url(item.get("thumb"))
        except InvalidSticker:
            continue
        width, height = _cn_size(item.get("width")), _cn_size(item.get("height"))
        if width and height and (width < 80 or height < 80):
            continue
        title = _cn_title(item.get("title"))
        author = _plain(item.get("site"), 80) or "原图作者"
        records.append(dict(title=title, preview_url=image, download_url=image,
            source_url=_cn_page_url(item.get("link"), "https://image.so.com/"),
            license=CN_LICENSE, author=author, source_label="360 图片",
            width=width, height=height))
    return records


def _cn_records_baidu(term, opener=None):
    raw = _read_url(_cn_baidu_url(term), API_LIMIT, opener=opener,
                    headers={"Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
                             "Referer": "https://image.baidu.com/"})
    try:
        data = json.loads(raw)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError()
    except (ValueError, TypeError):
        raise ProviderUnavailable() from None
    records = []
    for item in items[:40]:
        if not isinstance(item, dict):
            continue
        try:
            image = _media_url(item.get("middleURL") or item.get("thumbURL") or item.get("hoverURL"))
        except InvalidSticker:
            continue
        query = dict(parse_qsl(urlsplit(image).query))
        width, height = _cn_size(query.get("w")), _cn_size(query.get("h"))
        if width and height and (width < 80 or height < 80):
            continue
        title = _cn_title(item.get("fromPageTitleEnc"))
        author = _plain(item.get("fromURLHost"), 80) or "原图作者"
        source = "https://image.baidu.com/search/index?" + urlencode({"tn": "baiduimage", "word": term})
        records.append(dict(title=title, preview_url=image, download_url=image,
            source_url=source, license=CN_LICENSE, author=author,
            source_label="百度图片", width=width, height=height))
    return records


_CN_MEME_WORDS = ("表情", "梗图", "搞笑", "沙雕", "动态图", "配图", "meme")
_CN_GOOD_SITES = ("fabiaoqing.com", "soogif.com", "doutula.com", "kanqq.com", "qqtn.com")


def _cn_score(record, q):
    title, author = record["title"].lower(), record["author"].lower()
    meme_in_title = any(word in title for word in _CN_MEME_WORDS)
    score = 3 if meme_in_title else (1 if any(word in author for word in _CN_MEME_WORDS) else 0)
    if q.lower() in title:
        score += 2
    width, height = record.get("width") or 0, record.get("height") or 0
    if width and height and 0.6 <= width / height <= 1.7:
        score += 1
    if any(site in author for site in _CN_GOOD_SITES):
        score += 1
    if not meme_in_title and any(word in title for word in ("图片", "图赏", "简笔画", "怎么画", "壁纸", "摄影")):
        score -= 2
    return score


def _cn_store(records):
    token = secrets.token_hex(8)
    now = time.monotonic()
    with _cache_lock:
        for expired in [k for k, (until, _) in _cn_results.items() if until <= now]:
            del _cn_results[expired]
        _cn_results[token] = (now + CN_RESULT_TTL, tuple(records))
        while len(_cn_results) > 128:
            _cn_results.popitem(last=False)
    return token


def _cn_lookup(token):
    now = time.monotonic()
    with _cache_lock:
        item = _cn_results.get(token)
        if not item:
            return None
        if item[0] <= now:
            _cn_results.pop(token, None)
            return None
        return item[1]


def search_cn(q, uid, secret, *, opener=None):
    key = _identity(uid, secret)
    q = _cn_query(q)
    plain = q
    meme = q if ("表情" in q or "梗图" in q) else q + " 表情包"
    records, sources, unavailable = [], [], []
    for term in dict.fromkeys((plain, meme)):
        try:
            found = _cn_cached("360", term, lambda term=term: _cn_records_360(term, opener))
            if found:
                sources.append("360 图片")
                records.extend(found)
        except (ProviderUnavailable, InvalidSticker):
            unavailable.append("360 图片")
    seen, merged = set(), []
    for record in records:
        if record["download_url"] in seen:
            continue
        seen.add(record["download_url"])
        merged.append(record)
    if len(merged) < 8:
        try:
            found = _cn_cached("baidu", meme, lambda: _cn_records_baidu(meme, opener))
            if found:
                sources.append("百度图片")
                for record in found:
                    if record["download_url"] not in seen:
                        seen.add(record["download_url"])
                        merged.append(record)
        except (ProviderUnavailable, InvalidSticker):
            unavailable.append("百度图片")
    merged.sort(key=lambda record: -_cn_score(record, q))
    merged = merged[:RESULT_LIMIT]
    sources = list(dict.fromkeys(sources))
    unavailable = list(dict.fromkeys(unavailable))
    if not merged:
        return {"items": [], "provider": "中文梗图", "sources": sources,
                "unavailable": unavailable, "available": False,
                "detail": "没有搜到中文梗图，换个关键词，或用这句话生成一张"}
    token = _cn_store(merged)
    items = [dict(id="cn." + token + "." + str(index) + "." + _sign(index + 1, uid, key),
                  **{field: record[field] for field in
                     ("title", "preview_url", "source_url", "license", "author", "source_label")})
             for index, record in enumerate(merged)]
    return {"items": items, "provider": "中文梗图", "sources": sources,
            "unavailable": unavailable, "available": True}


def search(q, uid, secret, *, opener=None, provider='openmoji'):
    if provider == 'cn':
        return search_cn(q, uid, secret, opener=opener)
    if provider == 'memegen':
        key = hmac.digest(_identity(uid, secret), b'memegen-v1', 'sha256')
        _search_terms(q)  # shared input limits/control-character validation
        aliases = {'梗图':'', '热门':'', '全部':'', '猫咪':'cat', '狗狗':'dog', '猫':'cat', '狗':'dog',
            '疑惑':'confused', '困惑':'confused', '黑人问号':'confused', '德雷克':'drake',
            '拒绝':'drake', '分心':'distracted', '女友':'distracted', '外星人':'aliens',
            '吃瓜':'popcorn', '成功':'success', '生气':'angry', '无语':'really', '失败':'fail'}
        terms = q.lower().strip()
        for word in sorted(aliases, key=len, reverse=True):
            terms = terms.replace(word, ' ' + aliases[word] + ' ')
        words = terms.split()
        items = [dict(id='mg.' + _sign(_meme_id(r['slug']), uid, key),
            **{f:r[f] for f in ('title', 'source_url', 'license', 'author', 'preview_url')})
            for r in _meme_records(opener) if all(w in r['terms'] for w in words)][:RESULT_LIMIT]
        return {'items':items, 'provider':'Memegen 网络梗图模板'}
    if provider == 'commons':
        return dict(search_commons(q, uid, secret, opener=opener), provider='Wikimedia Commons')
    if provider != 'openmoji':
        raise InvalidSticker('不支持这个表情来源')
    key = hmac.digest(_identity(uid, secret), b'openmoji-v1', 'sha256')
    terms = _search_terms(q).removesuffix(' emoticon filetype:bitmap').lower().split()
    out = []
    for index, record in enumerate(_openmoji_records(opener)):
        if all(term in record['terms'] for term in terms):
            out.append(dict(id='om.' + _sign(index + 1, uid, key),
                **{field: record[field] for field in ('title', 'author', 'license', 'source_url', 'preview_url')}))
            if len(out) >= RESULT_LIMIT:
                break
    return {'items': out, 'provider': 'OpenMoji'}


def _meme_id(slug):
    return (int.from_bytes(hashlib.sha256(slug.encode()).digest()[:8], 'big') & (2 ** 63 - 1)) or 1


def _meme_records(opener=None):
    global _memes
    with _cache_lock:
        until, records = _memes
    if until > time.monotonic():
        return records
    raw = _read_url(MEME_API, API_LIMIT, opener=opener)
    try:
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) > 1000:
            raise ValueError()
        records = []
        for item in data:
            if not isinstance(item, dict):
                continue
            slug = item.get('id', '')
            if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9-]{1,64}', slug):
                continue
            try:
                image = _media_url(item.get('blank'))
            except InvalidSticker:
                continue
            if image != 'https://api.memegen.link/images/' + slug + '.jpg':
                continue
            source = str(item.get('source') or '').replace('http://knowyourmeme.com/', 'https://knowyourmeme.com/')
            if not source.startswith('https://knowyourmeme.com/memes/') or re.search(r'[\x00-\x20<>"\\]', source):
                source = 'https://github.com/jacebrowning/memegen/tree/main/templates/' + slug
            records.append(dict(slug=slug, title=_plain(item.get('name'), 200),
                preview_url=image + '?width=240', download_url=image, source_url=source,
                author='原图作者见来源',
                license='原图许可未声明，请查看来源',
                terms=' '.join((slug, str(item.get('name', '')), str(item.get('keywords', [])))).lower()))
        if not records:
            raise ValueError()
        records = tuple(records)
    except (ValueError, TypeError, AttributeError, InvalidSticker):
        raise ProviderUnavailable() from None
    with _cache_lock:
        _memes = (time.monotonic() + 3600, records)
    return records
