#!/usr/bin/env bash
# Provision an edge box (Orange Pi 5 / RK3588, Ubuntu Rockchip 24.04 or Armbian; docs/05).
# Idempotent: safe to re-run (re-running never changes an OTA-pinned agent version unless asked).
#
#   sudo edge/os/provision.sh --serial SN-0042 --claim-token XXXX --api-url https://app.example.sn \
#        [--image-owner 2guntan] [--agent-version 0.1.0] [--ssh-key "ssh-ed25519 AAAA… installer"] \
#        [--data-device /dev/nvme0n1 --wipe-data-device]
#
# Does (docs/05): hostname = kit serial; /data/{frigate,agent}; Docker + compose; unattended security
# upgrades; hardware watchdog; SSH key-only login; systemd unit that starts docker-compose.edge.yml on
# boot. Also: the reboot helper the agent's `reboot` command uses, journald 14-day retention, and
# optionally LUKS on the NVMe mounted at /data (docs/09 rule 3).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
edge=$(cd "$here/.." && pwd)
serial="" claim="" api="" owner="2guntan" version="" ssh_key="" data_dev="" wipe=0

usage() { sed -n '3,9p' "$0" >&2; exit 2; }
while (($#)); do
  case $1 in
    --serial) serial=$2; shift 2 ;;
    --claim-token) claim=$2; shift 2 ;;
    --api-url) api=$2; shift 2 ;;
    --image-owner) owner=$2; shift 2 ;;
    --agent-version) version=$2; shift 2 ;;
    --ssh-key) ssh_key=$2; shift 2 ;;
    --data-device) data_dev=$2; shift 2 ;;
    --wipe-data-device) wipe=1; shift ;;
    -h | --help) usage ;;
    *) echo "unknown option $1" >&2; usage ;;
  esac
done
[[ -n $serial && -n $claim && -n $api ]] || usage
[[ $serial =~ ^[A-Za-z0-9-]{1,63}$ ]] || { echo "serial must be letters, digits, '-' (it becomes the hostname)" >&2; exit 2; }
[[ $api == https://* || ${ALLOW_HTTP_API:-0} == 1 ]] || { echo "--api-url must be https:// (docs/09)" >&2; exit 2; }
if [[ -n $data_dev && $wipe != 1 ]] && ! mountpoint -q /data 2>/dev/null; then
  echo "refusing to format $data_dev without --wipe-data-device" >&2; exit 2
fi
[[ $(id -u) == 0 ]] || { echo "run as root" >&2; exit 1; }

has_systemd() { [[ -d /run/systemd/system ]]; }
sysctl_() { if has_systemd; then systemctl "$@"; else echo "   (no systemd running: skipped systemctl $*)"; fi; }
step() { echo "== $*"; }
export DEBIAN_FRONTEND=noninteractive

step "hostname = $serial"
echo "$serial" >"/etc/hostname"
if has_systemd; then hostnamectl set-hostname "$serial"; fi
grep -q "127.0.1.1 $serial" "/etc/hosts" 2>/dev/null || echo "127.0.1.1 $serial" >>"/etc/hosts"

step "packages: docker, compose, unattended-upgrades, cryptsetup"
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg systemd openssh-server unattended-upgrades cryptsetup docker.io python3
if ! apt-get install -y -q docker-compose-v2 2>/dev/null; then
  # Debian/Armbian: compose v2 from Docker's own repository
  # shellcheck source=/dev/null
  . /etc/os-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-compose-plugin
fi
sysctl_ enable --now docker

step "unattended security upgrades"
cat >"/etc/apt/apt.conf.d/20auto-upgrades" <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF

if [[ -n $data_dev ]]; then
  step "LUKS-encrypted /data on $data_dev"
  if mountpoint -q /data; then
    echo "   /data already mounted: left as is"
  else
    install -d -m 0700 /etc/seetlu
    [[ -f /etc/seetlu/data.key ]] || head -c 64 /dev/urandom >/etc/seetlu/data.key
    chmod 0400 /etc/seetlu/data.key
    cryptsetup luksFormat --batch-mode --type luks2 "$data_dev" /etc/seetlu/data.key
    cryptsetup open --key-file /etc/seetlu/data.key "$data_dev" seetlu-data
    mkfs.ext4 -q -L seetlu-data /dev/mapper/seetlu-data
    uuid=$(cryptsetup luksUUID "$data_dev")
    grep -q '^seetlu-data ' /etc/crypttab 2>/dev/null || echo "seetlu-data UUID=$uuid /etc/seetlu/data.key luks" >>/etc/crypttab
    grep -q '/dev/mapper/seetlu-data' /etc/fstab || echo "/dev/mapper/seetlu-data /data ext4 defaults,noatime 0 2" >>/etc/fstab
    mkdir -p /data && mount /data
  fi
fi

step "/data layout"
install -d -m 0755 "/data/frigate/config" "/data/frigate/media"
install -d -m 0700 "/data/agent" "/data/agent/host"
install -m 0644 "$edge/docker-compose.edge.yml" "/data/agent/docker-compose.edge.yml"
install -d -m 0755 "/data/agent/mosquitto"
install -m 0644 "$edge/mosquitto/mosquitto.edge.conf" "/data/agent/mosquitto/mosquitto.edge.conf"
umask 077
cat >"/data/agent/agent.env" <<ENV
SEETLU_API_URL=$api
KIT_SERIAL=$serial
KIT_CLAIM_TOKEN=$claim
ENV
# compose project .env: image owner + the pinned agent version (rewritten by OTA, docs/05 update_agent)
envf="/data/agent/.env"
current=$(sed -n 's/^SEETLU_AGENT_VERSION=//p' "$envf" 2>/dev/null || true)
default=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$edge/agent/seetlu_agent/__init__.py")
printf 'SEETLU_IMAGE_OWNER=%s\nSEETLU_AGENT_VERSION=%s\n' "$owner" "${version:-${current:-$default}}" >"$envf"
umask 022

step "hardware watchdog"
install -d "/etc/systemd/system.conf.d"
cat >"/etc/systemd/system.conf.d/10-seetlu-watchdog.conf" <<'CONF'
[Manager]
RuntimeWatchdogSec=30s
RebootWatchdogSec=2min
CONF

step "SSH: key-only login"
if [[ -n $ssh_key ]]; then
  install -d -m 0700 "/root/.ssh"
  grep -qxF "$ssh_key" "/root/.ssh/authorized_keys" 2>/dev/null || echo "$ssh_key" >>"/root/.ssh/authorized_keys"
  chmod 0600 "/root/.ssh/authorized_keys"
fi
if compgen -G "/root/.ssh/authorized_keys" >/dev/null || compgen -G "/home/*/.ssh/authorized_keys" >/dev/null; then
  install -d "/etc/ssh/sshd_config.d"
  cat >"/etc/ssh/sshd_config.d/10-seetlu.conf" <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
  sysctl_ reload ssh
else
  echo "   no SSH key installed (pass --ssh-key): password login left on so the box stays reachable" >&2
fi

step "journald: 14-day retention, 1 GB cap"
install -d "/etc/systemd/journald.conf.d"
cat >"/etc/systemd/journald.conf.d/10-seetlu.conf" <<'CONF'
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=14day
CONF

step "systemd units: stack on boot, reboot helper"
units=/etc/systemd/system
install -d "$units"
cat >"$units/seetlu-edge.service" <<'UNIT'
[Unit]
Description=Seetlu edge stack (Frigate + mosquitto + seetlu-agent)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
RequiresMountsFor=/data

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/data/agent
ExecStart=/usr/bin/docker compose -f /data/agent/docker-compose.edge.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose -f /data/agent/docker-compose.edge.yml down
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
UNIT
cat >"$units/seetlu-reboot.path" <<'UNIT'
[Unit]
Description=Reboot when the Seetlu agent asks (support console "reboot" command)

[Path]
PathExists=/data/agent/host/reboot-requested

[Install]
WantedBy=multi-user.target
UNIT
cat >"$units/seetlu-reboot.service" <<'UNIT'
[Unit]
Description=Reboot requested by the Seetlu agent

[Service]
Type=oneshot
ExecStart=/bin/rm -f /data/agent/host/reboot-requested
ExecStart=/bin/systemctl reboot
UNIT
step "front panel daemon (status LED + button, AC-F10-4)"
install -m 0755 "$here/seetlu-panel.py" /usr/local/bin/seetlu-panel
install -d /usr/local/share/seetlu
install -m 0644 "$here/seetlu-panel.dts" /usr/local/share/seetlu/seetlu-panel.dts  # GPIO lines set at hardware time
cat >"$units/seetlu-panel.service" <<'UNIT'
[Unit]
Description=Seetlu box front panel: status LED and setup button
After=docker.service
RequiresMountsFor=/data

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/seetlu-panel
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sysctl_ daemon-reload
sysctl_ enable seetlu-edge.service seetlu-reboot.path seetlu-panel.service
sysctl_ restart systemd-journald
sysctl_ start seetlu-reboot.path
sysctl_ restart seetlu-panel.service
sysctl_ start seetlu-edge.service

step "done: $serial → $api (agent $(sed -n 's/^SEETLU_AGENT_VERSION=//p' "$envf"))"
echo "next: plug the box into the shop recorder's network, open http://$serial.local:8080 (PIN = last 6 of the claim token), then claim the kit in the installer app"
