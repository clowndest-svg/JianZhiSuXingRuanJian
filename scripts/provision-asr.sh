#!/bin/bash
# Provision the on-host Chinese ASR daemon (Paraformer + CT-Punc, ONNX CPU).
# Idempotent: re-running upgrades deps/models and restarts the unit.
set -euo pipefail
MODELS=/opt/qingsu/asr-models
VENV=/opt/qingsu/asr-venv
PARA="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx"
PUNC="iic/punc_ct-transformer_zh-cn-common-vocab272727-onnx"
PIP="-i https://pypi.tuna.tsinghua.edu.cn/simple"

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q $PIP --upgrade pip
"$VENV/bin/pip" install -q $PIP funasr-onnx onnxruntime modelscope

"$VENV/bin/python" - "$PARA" "$PUNC" "$MODELS" <<'PY'
import sys
from modelscope import snapshot_download
for model in sys.argv[1:3]:
    print(snapshot_download(model, cache_dir=sys.argv[3]))
PY

PARA_DIR=$("$VENV/bin/python" -c "from modelscope import snapshot_download;print(snapshot_download('$PARA',cache_dir='$MODELS'))")
PUNC_DIR=$("$VENV/bin/python" -c "from modelscope import snapshot_download;print(snapshot_download('$PUNC',cache_dir='$MODELS'))")

cat > /etc/systemd/system/qingsu-asr.service <<UNIT
[Unit]
Description=QingSu speech-to-text (Paraformer ONNX, local only)
After=network.target

[Service]
Type=simple
Environment=ASR_MODEL_DIR=$PARA_DIR
Environment=ASR_PUNC_DIR=$PUNC_DIR
Environment=ASR_PORT=8071
Environment=ASR_THREADS=2
Environment=OMP_NUM_THREADS=2
ExecStart=$VENV/bin/python /opt/qingsu/asr-server.py
Restart=on-failure
RestartSec=3
MemoryMax=1200M
CPUQuota=200%
Nice=10

[Install]
WantedBy=multi-user.target
UNIT

printf '%s\n' '{"url": "http://127.0.0.1:8071"}' > /opt/qingsu/asr.json
systemctl daemon-reload
systemctl enable qingsu-asr
systemctl restart qingsu-asr
for _ in $(seq 1 30); do
    if curl -sf -m 3 http://127.0.0.1:8071/health >/dev/null; then
        echo "ASR ready on 127.0.0.1:8071"
        exit 0
    fi
    sleep 2
done
echo "ASR did not become ready; check journalctl -u qingsu-asr" >&2
exit 1
