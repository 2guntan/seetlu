#!/usr/bin/env bash
# Shared helpers for the backup scripts (docs/09: daily full + WAL, 30-day retention, restore drill).
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
BUCKET=${BACKUP_S3_BUCKET:-seetlu-backups}
export RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}
METRICS_DIR=${METRICS_DIR:-/metrics}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}

log() { printf '%s backup: %s\n' "$(date -u +%FT%TZ)" "$*"; }

s3() { aws --endpoint-url "$BACKUP_S3_ENDPOINT" s3 "$@"; }

ensure_bucket() {
  s3 ls "s3://$BUCKET" >/dev/null 2>&1 || s3 mb "s3://$BUCKET" >/dev/null
}

# Write one Prometheus textfile metric (node-exporter textfile collector), keeping the others.
metric() {
  local name=$1 value=$2 file="$METRICS_DIR/seetlu-backup.prom"
  mkdir -p "$METRICS_DIR"
  touch "$file"
  { grep -v "^$name " "$file" || true; echo "$name $value"; } >"$file.tmp"
  mv "$file.tmp" "$file"
}

# WAL segment names are 24 hex digits and sort in replay order on one timeline.
is_wal_segment() { [[ $1 =~ ^[0-9A-F]{24}$ ]]; }

ship_wal() {
  s3 sync --only-show-errors "$BACKUP_DIR/wal/" "s3://$BUCKET/wal/"
  metric seetlu_backup_last_wal_ship_timestamp_seconds "$(date +%s)"
}

offsite_sync() {
  [[ -n ${BACKUP_OFFSITE_S3_ENDPOINT:-} && -n ${BACKUP_OFFSITE_S3_BUCKET:-} ]] || return 0
  local tmp="$BACKUP_DIR/offsite-staging"
  mkdir -p "$tmp"
  s3 sync --only-show-errors --delete "s3://$BUCKET/" "$tmp/"
  AWS_ACCESS_KEY_ID=$BACKUP_OFFSITE_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$BACKUP_OFFSITE_SECRET_ACCESS_KEY \
    aws --endpoint-url "$BACKUP_OFFSITE_S3_ENDPOINT" s3 sync --only-show-errors --delete \
    "$tmp/" "s3://$BACKUP_OFFSITE_S3_BUCKET/"
  metric seetlu_backup_last_offsite_sync_timestamp_seconds "$(date +%s)"
}
