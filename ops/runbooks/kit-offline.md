# Runbook — kit offline or degraded (AC-F10-2)

Support console → Kits → filter `offline` (no heartbeat 30 min) or `degraded` (queue > 100 events or a
camera under 2 fps). The owner also got a `kit_offline` WhatsApp alert during opening hours.

1. Last heartbeat: power source and battery % (power cut → it comes back by itself; UPS empty?),
   network type (4G signal), storage %, CPU temperature.
2. Call the owner: is the box powered, router lit? Ask for a power cycle of the router first, then the box.
3. Box back but `degraded`: reboot it from the support console (audited `support.access`). The agent
   writes `/data/agent/host/reboot-requested`; the `seetlu-reboot.path` unit reboots the host.
4. A camera at 0 fps: cable / PoE port. Snapshot needs an owner support grant.
5. Still offline after 24 h: send the installer. On site: `journalctl -u seetlu-edge`,
   `docker compose -f /data/agent/docker-compose.edge.yml ps`, `df -h /data`.
6. Events are queued on the box (SQLite outbox) and upload when it is back: reports for the missing
   hours say which hours are missing (rule 3), never zero.

Re-provision a box: `sudo edge/os/provision.sh --serial … --claim-token … --api-url https://<domain>`
(idempotent; keeps the OTA-pinned version).
