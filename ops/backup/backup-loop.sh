#!/usr/bin/env bash
# Long-running backup service: ship WAL every minute, base backup once a day (docs/09).
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

until pg_isready -q; do sleep 2; done
ensure_bucket
log "started (bucket $BUCKET, retention $RETENTION_DAYS days)"
while true; do
  if ! ship_wal; then
    log "WAL shipping failed"
    metric seetlu_backup_last_error_timestamp_seconds "$(date +%s)"
  fi
  last=$(cat "$BACKUP_DIR/base/LATEST" 2>/dev/null || echo "")
  last_s=$([[ -n $last ]] && date -u -d "${last:0:4}-${last:4:2}-${last:6:2}T${last:9:2}:${last:11:2}:${last:13:2}Z" +%s || echo 0)
  if (($(date +%s) - last_s > 86400)); then
    backup-now.sh || { log "base backup failed"; metric seetlu_backup_last_error_timestamp_seconds "$(date +%s)"; }
  fi
  sleep "${BACKUP_LOOP_SLEEP:-60}"
done
