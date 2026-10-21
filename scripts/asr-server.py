# -*- coding: utf-8 -*-
"""Local-only speech-to-text daemon: FunASR Paraformer + CT-Punc, ONNX CPU.

Runs under /opt/qingsu/asr-venv and is pinned by qingsu-asr.service
(MemoryMax/CPUQuota) so transcription cannot squeeze qingsu/coturn.
"""
import json
import os
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from funasr_onnx import CT_Transformer, Paraformer

MODEL_DIR = os.environ["ASR_MODEL_DIR"]
PUNC_DIR = os.environ.get("ASR_PUNC_DIR", "")
PORT = int(os.environ.get("ASR_PORT", "8071"))
THREADS = int(os.environ.get("ASR_THREADS", "2"))

print("loading paraformer…", flush=True)
ASR = Paraformer(MODEL_DIR, batch_size=1, quantize=True, intra_op_num_threads=THREADS)
PUNC = None
if PUNC_DIR:
    print("loading punctuation…", flush=True)
    PUNC = CT_Transformer(PUNC_DIR, batch_size=1, quantize=True, intra_op_num_threads=THREADS)


def _warmup():
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(path, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b"\x00\x00" * 4000)
        ASR(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


_warmup()
print("ready on 127.0.0.1:%d" % PORT, flush=True)


class Handler(BaseHTTPRequestHandler):
    lock = threading.Lock()

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/asr":
            self._json(404, {"error": "not found"})
            return
        path = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 44 or length > 40 * 1024 * 1024:
                raise ValueError("bad length")
            payload = self.rfile.read(length)
            fd, path = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(fd, "wb") as out:
                out.write(payload)
            with self.lock:
                result = ASR(path)
                text = result[0]["preds"][0] if result else ""
                if PUNC and text:
                    text = PUNC(text)[0]
            self._json(200, {"text": text or ""})
        except Exception as error:
            self._json(500, {"error": type(error).__name__})
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
