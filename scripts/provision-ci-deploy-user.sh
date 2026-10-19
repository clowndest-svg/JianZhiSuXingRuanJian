#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "run this provisioning script as root" >&2
  exit 1
fi
if [[ $# -ne 1 || ! -f $1 ]]; then
  echo "usage: provision-ci-deploy-user.sh <qingsu-ci-public-key-file>" >&2
  exit 2
fi

public_key=$(tr -d '\r\n' < "$1")
if [[ ! $public_key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ [A-Za-z0-9._@-]+$ ]]; then
  echo "expected one ED25519 public key with a simple comment" >&2
  exit 2
fi

repo_root=$(cd "$(dirname "$0")/.." && pwd)
gateway_source="$repo_root/scripts/ci-deploy-server.py"
if [[ ! -f $gateway_source || ! -d /opt/qingsu ]]; then
  echo "application repository or /opt/qingsu is missing" >&2
  exit 1
fi

if ! id qingsu-ci >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/qingsu-ci --shell /bin/bash qingsu-ci
fi
install -d -o qingsu-ci -g qingsu-ci -m 0700 /home/qingsu-ci/.ssh /opt/qingsu/ci-incoming
authorized=/home/qingsu-ci/.ssh/authorized_keys
touch "$authorized"
chmod 0600 "$authorized"
chown qingsu-ci:qingsu-ci "$authorized"
restricted="restrict $public_key"
if ! grep -Fxq "$restricted" "$authorized"; then
  printf '%s\n' "$restricted" >> "$authorized"
fi

install -o root -g root -m 0755 "$gateway_source" /usr/local/sbin/qingsu-ci-deploy
cat > /etc/sudoers.d/qingsu-ci-deploy <<'SUDOERS'
qingsu-ci ALL=(root) NOPASSWD: /usr/local/sbin/qingsu-ci-deploy main *, /usr/local/sbin/qingsu-ci-deploy admin *
SUDOERS
chmod 0440 /etc/sudoers.d/qingsu-ci-deploy
visudo -cf /etc/sudoers.d/qingsu-ci-deploy
echo "qingsu-ci deploy entry point provisioned"
