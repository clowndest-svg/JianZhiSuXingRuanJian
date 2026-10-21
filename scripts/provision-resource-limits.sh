#!/usr/bin/env bash
set -euo pipefail
# Protect the chat/call services from a Directus or local-LLM spike.
# Applies live cgroup limits and leaves persistent drop-ins for the next boot.
[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 1; }

install -d -m 755 /etc/systemd/system/qingsu-llama.service.d \
  /etc/systemd/system/qingsu.service.d /etc/systemd/system/coturn.service.d

cat > /etc/systemd/system/qingsu-llama.service.d/limits.conf <<'EOF'
[Service]
MemoryHigh=1000M
MemoryMax=1200M
CPUQuota=200%
EOF

cat > /etc/systemd/system/qingsu.service.d/resources.conf <<'EOF'
[Service]
CPUWeight=500
EOF

cat > /etc/systemd/system/coturn.service.d/resources.conf <<'EOF'
[Service]
CPUWeight=500
EOF

systemctl daemon-reload
systemctl set-property qingsu-llama.service MemoryHigh=1000M MemoryMax=1200M CPUQuota=200%
systemctl set-property qingsu.service CPUWeight=500
systemctl set-property coturn.service CPUWeight=500

# Directus is a container; keep the live cap and a server-side override so a
# `docker compose up -d` does not silently drop it.
if docker inspect qingsu-console >/dev/null 2>&1; then
  install -d -m 755 /opt/qingsu/admin-console
  cat > /opt/qingsu/admin-console/docker-compose.override.yml <<'EOF'
services:
  directus:
    mem_limit: 768m
    memswap_limit: 768m
    cpus: 1.0
EOF
  docker update --memory 768m --memory-swap 768m --cpus 1 qingsu-console >/dev/null
fi

echo "limits applied: directus 768M/1cpu, llama 1200M/2cpu, qingsu+coturn CPUWeight=500"
systemctl show qingsu-llama -p MemoryHigh -p MemoryMax -p CPUQuotaPerSecUSec
systemctl is-active qingsu qingsu-llama coturn
