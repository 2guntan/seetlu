#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 VM (Senegal-hosted, docs/09) for the Seetlu production stack.
# Idempotent. Run as root from a checkout of the repo:
#
#   sudo ops/vm/setup.sh            # then: ops/vm/gen-secrets.sh --domain … && sudo systemctl start seetlu
#
# Does: Docker + compose plugin, firewall (22/80/443 only), unattended security upgrades, SSH key-only
# login (when a key is installed), journald 30-day log retention, systemd units for the stack and the
# monthly restore drill. Provider-agnostic: any VM with a public IPv4 and DNS for <domain> and files.<domain>.
set -euo pipefail

[[ $(id -u) == 0 ]] || { echo "run as root" >&2; exit 1; }
repo=$(cd "$(dirname "$0")/../.." && pwd)
export DEBIAN_FRONTEND=noninteractive

echo "== packages"
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 git openssl ufw unattended-upgrades ca-certificates curl
systemctl enable --now docker
id seetlu >/dev/null 2>&1 && usermod -aG docker seetlu

echo "== unattended security upgrades"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF

echo "== firewall"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "== ssh: key-only login"
if compgen -G "/root/.ssh/authorized_keys" >/dev/null || compgen -G "/home/*/.ssh/authorized_keys" >/dev/null; then
  cat >/etc/ssh/sshd_config.d/10-seetlu.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
  systemctl reload ssh || systemctl reload sshd || true
else
  echo "   no authorized_keys found: password login left on (install a key, then re-run)" >&2
fi

echo "== journald: 30-day log retention"
mkdir -p /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/10-seetlu.conf <<'CONF'
[Journal]
Storage=persistent
SystemMaxUse=4G
MaxRetentionSec=30day
CONF
systemctl restart systemd-journald

echo "== systemd units"
compose="/usr/bin/docker compose -f $repo/ops/docker-compose.prod.yml --env-file $repo/.env.prod"
cat >/etc/systemd/system/seetlu.service <<UNIT
[Unit]
Description=Seetlu production stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$repo
ExecStart=$compose up -d --build --wait --wait-timeout 600
ExecStop=$compose down
TimeoutStartSec=1200

[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/seetlu-restore-drill.service <<UNIT
[Unit]
Description=Seetlu monthly restore drill (docs/09)
Requires=seetlu.service
After=seetlu.service

[Service]
Type=oneshot
WorkingDirectory=$repo
ExecStart=$compose run --rm backup restore-drill.sh
UNIT
cat >/etc/systemd/system/seetlu-restore-drill.timer <<'UNIT'
[Unit]
Description=Run the Seetlu restore drill monthly

[Timer]
OnCalendar=monthly
RandomizedDelaySec=6h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable seetlu.service seetlu-restore-drill.timer
systemctl start seetlu-restore-drill.timer

if [[ -f $repo/.env.prod ]]; then
  echo "== starting the stack"
  systemctl restart seetlu.service
else
  echo "next: ops/vm/gen-secrets.sh --domain <domain> --email <email>; then: systemctl start seetlu"
fi
