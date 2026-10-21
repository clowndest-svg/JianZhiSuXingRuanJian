# -*- coding: utf-8 -*-
"""Ask the on-host ASR daemon to transcribe a voice message.

The daemon is optional: without /opt/qingsu/asr.json (or with enabled=false)
this module raises AsrUnavailable and callers must surface that honestly.
"""
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

from app_modules import audio

CONFIG = os.environ.get("QINGSU_ASR_CONFIG") or "/opt/qingsu/asr.json"


class AsrUnavailable(RuntimeError):
    pass


def _config():
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("enabled") is False:
        return {}
    return data


def enabled():
    return bool(str(_config().get("url") or "").strip())


def transcribe(path, timeout=120):
    cfg = _config()
    url = str(cfg.get("url") or "").strip()
    if not url:
        raise AsrUnavailable("语音转文字暂不可用")
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        convert = subprocess.run(
            [audio._tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(path),
             "-ac", "1", "-ar", "16000", "-f", "wav", wav],
            capture_output=True, timeout=30, check=False)
        if convert.returncode:
            raise AsrUnavailable("这条语音读不出来，转不了文字")
        req = urllib.request.Request(
            url.rstrip("/") + "/asr",
            data=open(wav, "rb").read(),
            headers={"Content-Type": "audio/wav"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as response:
                data = json.loads(response.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            raise AsrUnavailable("语音转文字暂不可用") from error
        return str(data.get("text") or "").strip()[:500]
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass
