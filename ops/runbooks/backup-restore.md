# Runbook — backups and restore (docs/09)

## What runs

- Postgres archives every WAL segment (at least every 5 min, `archive_timeout=300`) to the `backups` volume.
- The `backup` service ships WAL to MinIO bucket `seetlu-backups/wal/` every minute and takes a base
  backup (`pg_basebackup`, tar + gzip) once every 24 h to `seetlu-backups/base/<UTC stamp>/`.
- Retention: 30 days of base backups in MinIO (the newest is always kept) and the WAL from the oldest
  kept base onwards. Locally only the newest base and the WAL after it stay on disk.
- Optional second copy (`BACKUP_OFFSITE_*`): the bucket is mirrored after each base backup to another
  S3 endpoint. It must also be in Senegal (no personal data outside the production region).
- Metrics for Prometheus: `seetlu_backup_last_base_timestamp_seconds`, `…_last_wal_ship_…`,
  `seetlu_restore_drill_last_success_timestamp_seconds`. Alerts: `BaseBackupMissing` (26 h),
  `WalShippingStalled` (15 min), `RestoreDrillOverdue` (35 days).

## Monthly drill (automatic: `seetlu-restore-drill.timer`)

```bash
sudo make restore-drill
```

Creates a restore point on the live DB, rebuilds a scratch server from MinIO only (latest base + WAL),
replays to the restore point, prints live vs restored row counts, exits 0 on PASS. The live DB is not
touched except for the restore point and one WAL switch. Logs: `journalctl -u seetlu-restore-drill`.

## Real restore (database lost or corrupted)

1. Stop writers: `docker compose … stop api worker beat`.
2. Restore into a scratch dir and keep the server: 
   `docker compose … run --rm -e RESTORE_ONLY=1 -e RESTORE_TARGET_DIR=/backups/restore backup restore-drill.sh`
   (to stop at a precise time instead of now, edit `recovery_target_name` to `recovery_target_time` in
   `/backups/restore/data/postgresql.auto.conf` and restart that server).
3. Check the data on port 5433 inside that container, then: stop `db`, move the `pgdata` volume aside
   (`docker volume create pgdata-broken` + copy, never delete first), copy `/backups/restore/data` into the
   `pgdata` volume, remove `recovery.signal` and the `restore_command` lines, start `db`, then the rest.
4. Take a new base backup (`make backup-now`) and write the incident down (incident runbook).

If MinIO itself is lost: restore its bucket from the off-site copy first (`aws s3 sync` back), then step 2.
