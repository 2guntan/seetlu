# Runbook — production incident

Alerts arrive on the Alertmanager webhook (`ALERT_WEBHOOK_URL`). Grafana and Prometheus are on
127.0.0.1 only: `ssh -L 3000:localhost:3000 -L 9090:localhost:9090 <vm>`.

| Alert | First look |
| --- | --- |
| EndpointDown | `docker compose … ps`; `journalctl CONTAINER_TAG=seetlu/<service> -n 200`; `make prod-up` restarts what is down |
| TlsCertificateExpiresSoon | Caddy logs (`seetlu/…caddy…`); DNS still points here? port 80 open for the ACME challenge? |
| DiskAlmostFull | `docker system df`; clips expire nightly (7 days); journald is capped at 4 GB; grow the disk |
| BaseBackupMissing / WalShippingStalled | `journalctl CONTAINER_TAG=…backup…`; MinIO up? `make backup-now` |
| RestoreDrillOverdue | `systemctl status seetlu-restore-drill.timer`; run `make restore-drill` |

Daily reports: if the 21:00 reports did not go out, check `beat` and `worker` logs, then send one by hand:
`docker compose … run --rm api python -m seetlu.reports <shop id> <YYYY-MM-DD>` (never resends a sent report).

Logs: journald, 30 days (`/etc/systemd/journald.conf.d/10-seetlu.conf`). Every support action and clip
access is in `audit_log` (rule 5) — use it to answer "who looked at what".

After: write a short note (what, impact, cause, fix, follow-up) in the ops log; rotate any secret that
may have leaked (`.env.prod`, then `make prod-up`; kit/phone tokens are re-issued by re-pairing).
