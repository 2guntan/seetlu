#!/usr/bin/env bash
# docs/11 M10 "provision script tested on an arm64 VM": runs edge/os/provision.sh twice (idempotence) in a
# fresh arm64 Ubuntu 24.04 and checks what it leaves behind. systemd is not PID 1 in a container, so unit
# start/enable is skipped there; unit files, compose file and configs are verified instead. LUKS needs a
# block device and is exercised on real hardware only (docs/12).
#
#   edge/os/tests/provision-test.sh            # needs Docker; uses --platform linux/arm64
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)

if [[ ${1:-} != --inside ]]; then
  exec docker run --rm --platform linux/arm64 -v "$repo/edge:/src/edge:ro" ubuntu:24.04 \
    bash /src/edge/os/tests/provision-test.sh --inside
fi

[[ $(uname -m) == aarch64 ]] || { echo "FAIL: not arm64 ($(uname -m))"; exit 1; }
key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLEtestkeyonly installer@test"
run() {
  bash /src/edge/os/provision.sh --serial SN-TEST-0042 --claim-token claim-123456 \
    --api-url https://app.example.test --ssh-key "$key" >/tmp/provision.log 2>&1 \
    || { tail -30 /tmp/provision.log; echo "FAIL: provision.sh exited non-zero"; exit 1; }
}
fail() { echo "FAIL: $*"; exit 1; }

run
# OTA has moved the kit to 0.2.0 since; a re-run must keep it
sed -i 's/^SEETLU_AGENT_VERSION=.*/SEETLU_AGENT_VERSION=0.2.0/' /data/agent/.env
run

[[ $(cat /etc/hostname) == SN-TEST-0042 ]] || fail "hostname"
for d in /data/frigate/config /data/frigate/media /data/agent /data/agent/host; do [[ -d $d ]] || fail "missing $d"; done
[[ $(stat -c %a /data/agent) == 700 ]] || fail "/data/agent must be 700"
[[ $(stat -c %a /data/agent/agent.env) == 600 ]] || fail "agent.env must be 600"
grep -qx "KIT_SERIAL=SN-TEST-0042" /data/agent/agent.env || fail "agent.env serial"
grep -qx "SEETLU_AGENT_VERSION=0.2.0" /data/agent/.env || fail "re-run changed the OTA-pinned version"
grep -qx "SEETLU_IMAGE_OWNER=2guntan" /data/agent/.env || fail "image owner"
command -v docker >/dev/null || fail "docker not installed"
docker compose version >/dev/null || fail "compose plugin not installed"
(cd /data/agent && docker compose -f docker-compose.edge.yml config --quiet) || fail "edge compose file invalid"
(cd /data/agent && docker compose -f docker-compose.edge.yml config) | grep -q "image: ghcr.io/2guntan/seetlu-agent:0.2.0" \
  || fail "compose does not resolve the pinned agent image"
grep -q '"1"' /etc/apt/apt.conf.d/20auto-upgrades || fail "unattended upgrades"
grep -qx "RuntimeWatchdogSec=30s" /etc/systemd/system.conf.d/10-seetlu-watchdog.conf || fail "watchdog"
grep -qx "PasswordAuthentication no" /etc/ssh/sshd_config.d/10-seetlu.conf || fail "ssh password login"
[[ $(grep -c "installer@test" /root/.ssh/authorized_keys) == 1 ]] || fail "ssh key duplicated or missing"
grep -q "docker-compose.edge.yml up -d" /etc/systemd/system/seetlu-edge.service || fail "boot unit"
grep -q "PathExists=/data/agent/host/reboot-requested" /etc/systemd/system/seetlu-reboot.path || fail "reboot helper"
grep -qx "MaxRetentionSec=14day" /etc/systemd/journald.conf.d/10-seetlu.conf || fail "journald retention"
if command -v systemd-analyze >/dev/null; then
  systemd-analyze verify /etc/systemd/system/seetlu-reboot.path /etc/systemd/system/seetlu-reboot.service \
    2>&1 | grep -v "docker.service\|Failed to\|Cannot add dependency" | grep . && fail "systemd-analyze"
fi

# refuses unsafe inputs
bash /src/edge/os/provision.sh --serial "bad serial" --claim-token x --api-url https://a 2>/dev/null && fail "bad serial accepted"
bash /src/edge/os/provision.sh --serial S --claim-token x --api-url http://a 2>/dev/null && fail "http api accepted"
bash /src/edge/os/provision.sh --serial S --claim-token x --api-url https://a --data-device /dev/null 2>/dev/null \
  && fail "formatted a device without --wipe-data-device"
echo "provision test PASSED (arm64, run twice)"
