#!/usr/bin/env bash
# One base backup: pg_basebackup (tar, gzip) → s3://$BUCKET/base/<UTC stamp>/, then retention.
# The WAL needed to make it consistent is archived by Postgres before pg_basebackup returns.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

ensure_bucket
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dir="$BACKUP_DIR/base/$stamp"
mkdir -p "$dir"
log "base backup $stamp"
pg_basebackup -D "$dir" -Ft -z -X none -c fast -l "seetlu-$stamp"
ship_wal
s3 cp --only-show-errors --recursive "$dir/" "s3://$BUCKET/base/$stamp/"
echo "$stamp" >"$BACKUP_DIR/base/LATEST"
metric seetlu_backup_last_base_timestamp_seconds "$(date +%s)"

# ---- retention: keep RETENTION_DAYS of base backups in S3 (always at least the newest), and the WAL
# from the oldest kept base onwards. Locally only the newest base and the WAL after it are kept.
cutoff=$(date -u -d "@$(($(date +%s) - RETENTION_DAYS * 86400))" +%Y%m%dT%H%M%SZ)
mapfile -t bases < <(s3 ls "s3://$BUCKET/base/" | awk '/PRE/ {sub("/", "", $2); print $2}' | sort)
keep=()
for b in "${bases[@]}"; do
  if [[ $b < $cutoff && $b != "$stamp" ]]; then
    log "retention: delete base $b"
    s3 rm --only-show-errors --recursive "s3://$BUCKET/base/$b/"
  else
    keep+=("$b")
  fi
done

# oldest WAL segment still needed = the start segment of the oldest kept base (its *.backup label file)
oldest=${keep[0]}
first_wal=$(s3 ls "s3://$BUCKET/wal/" | awk '{print $4}' | grep -E '^[0-9A-F]{24}\.[0-9A-F]{8}\.backup$' \
  | sort | while read -r label; do
      s3 cp --only-show-errors "s3://$BUCKET/wal/$label" - | grep -q "LABEL: seetlu-$oldest" && { echo "${label%%.*}"; break; }
    done || true)
if [[ -n $first_wal ]]; then
  s3 ls "s3://$BUCKET/wal/" | awk '{print $4}' | while read -r f; do
    seg=${f%%.*}
    if is_wal_segment "$seg" && [[ $seg < $first_wal ]]; then s3 rm --only-show-errors "s3://$BUCKET/wal/$f"; fi
  done
fi

# local: newest base only; WAL before it is in S3 already
find "$BACKUP_DIR/base" -mindepth 1 -maxdepth 1 -type d ! -name "$stamp" -exec rm -rf {} +
local_first=$(grep -l "LABEL: seetlu-$stamp" "$BACKUP_DIR"/wal/*.backup 2>/dev/null | head -1 || true)
[[ -n $local_first ]] && pg_archivecleanup "$BACKUP_DIR/wal" "$(basename "$local_first")"
offsite_sync
log "base backup $stamp done (kept ${#keep[@]} in s3)"
