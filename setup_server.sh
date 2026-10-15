#!/bin/bash
set -e

echo "=== 1. Checking Python and Server File ==="
cd /opt/qingsu
python3 -c "import server; print('server.py imported successfully!')"

echo "=== 2. Creating systemd service for QingSu Backend ==="
cat << 'EOF' > /etc/systemd/system/qingsu.service
[Unit]
Description=QingSu Health & Shape Backend API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/qingsu
ExecStart=/usr/local/bin/uvicorn server:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable qingsu
systemctl restart qingsu
sleep 2
systemctl status qingsu --no-pager

echo "=== 3. Testing Local API endpoint ==="
curl -s http://127.0.0.1:8000/docs | head -n 10
echo "Backend service is live!"
