"""Validate and normalize private voice recordings with bounded local decoding."""
import json
import math
import os
import shutil
import subprocess


class InvalidAudio(ValueError):
    pass


class AudioUnavailable(RuntimeError):
    pass


def _tool(name):
    path = os.environ.get("QINGSU_" + name.upper()) or shutil.which(name)
    if not path:
        raise AudioUnavailable("语音处理暂不可用，请稍后重试")
    return path


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InvalidAudio("语音无法读取，或处理时间过长") from error
    if result.returncode:
        raise InvalidAudio("请选择可播放的语音文件")
    return result.stdout


def _probe(path, container):
    raw = _run([_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
                "-f", container, "-show_streams", "-show_format", "-of", "json", str(path)])
    try:
        info = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise InvalidAudio("语音格式不对") from error
    streams = info.get("streams", [])
    if not streams or any(s.get("codec_type") != "audio" for s in streams):
        raise InvalidAudio("语音文件只能包含音轨，不能包含视频")
    return info


def normalize(source, output, mime, max_seconds=600):
    containers = {"audio/webm": "matroska", "audio/mp4": "mov",
                  "audio/ogg": "ogg", "audio/aac": "aac"}
    container = containers.get(mime)
    if not container:
        raise InvalidAudio("不支持这个语音格式")
    _probe(source, container)
    try:
        # Force the detected container; uploaded playlists cannot select network inputs.
        _run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-threads", "1",
              "-protocol_whitelist", "file,pipe", "-f", container, "-i", str(source),
              "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-t", str(max_seconds + 1),
              "-ac", "1", "-ar", "24000", "-c:a", "libopus", "-b:a", "20k",
              "-application", "voip", "-f", "ogg", str(output)])
        info = _probe(output, "ogg")
        duration = float(info.get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or duration <= 0 or duration > max_seconds:
            raise InvalidAudio("语音最长 10 分钟，请缩短后再发送")
        return max(1, math.ceil(duration)), "audio/ogg"
    except Exception:
        try:
            os.unlink(output)
        except OSError:
            pass
        raise
