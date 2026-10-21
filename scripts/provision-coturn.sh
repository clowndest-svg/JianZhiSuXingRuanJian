#!/usr/bin/env bash
set -euo pipefail
# Provision the voice-call TURN server. Run as root on the production host.
# The shared secret is generated here and read by server.py; never commit it.
ROOT=/opt/qingsu
PUBLIC_IP="${TURN_PUBLIC_IP:-124.220.54.64}"
PRIVATE_IP="${TURN_PRIVATE_IP:-10.0.0.14}"
command -v turnserver >/dev/null 2>&1 || dnf install -y coturn
install -d -m 750 "$ROOT/keys"
if [ ! -s "$ROOT/keys/turn-secret" ]; then
  umask 077
  openssl rand -hex 32 > "$ROOT/keys/turn-secret"
fi
SECRET="$(cat "$ROOT/keys/turn-secret")"
chown root:qingsu "$ROOT/keys/turn-secret"
chmod 640 "$ROOT/keys/turn-secret"
cat > /etc/coturn/turnserver.conf <<EOF
listening-port=3478
listening-ip=0.0.0.0
external-ip=${PUBLIC_IP}/${PRIVATE_IP}
realm=qingsu
server-name=qingsu
use-auth-secret
static-auth-secret=${SECRET}
fingerprint
no-tcp
no-tls
no-dtls
no-multicast-peers
no-cli
stale-nonce
user-quota=12
total-quota=100
max-bps=128000
bps-capacity=3000000
min-port=49160
max-port=49180
denied-peer-ip=10.0.0.0-10.255.255.255
denied-peer-ip=172.16.0.0-172.31.255.255
denied-peer-ip=192.168.0.0-192.168.255.255
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
log-file=/var/log/coturn/turnserver.log
simple-log
EOF
chown root:coturn /etc/coturn/turnserver.conf
chmod 640 /etc/coturn/turnserver.conf
systemctl enable coturn
systemctl restart coturn
sleep 1
systemctl is-active coturn
echo "coturn ready: udp/${PUBLIC_IP}:3478 + 49160-49180"
