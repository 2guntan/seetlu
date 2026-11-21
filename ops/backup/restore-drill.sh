#!/usr/bin/env bash
# Restore drill (docs/09): rebuild the database from S3 only (latest base backup + archived WAL) in a
# scratch data directory, replay up to a restore point created now, and compare it with the live DB.
# Exit 0 = drill passed. Nothing on the live database is changed except the restore point and a WAL switch.
#
#   docker compose -f ops/docker-compose.prod.yml --env-file .env.prod run --rm backup restore-drill.sh
#
# RESTORE_ONLY=1 RESTORE_TARGET_DIR=/path stops after recovery and leaves the server running on port 5433
# (real disaster recovery: see ops/runbooks/backup-restore.md).
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

TABLES=${DRILL_TABLES:-"accounts shops users kits events sales daily_reports audit_log"}
work=${RESTORE_TARGET_DIR:-$(mktemp -d /tmp/restore-XXXX)}
data="$work/data"
port=5433

live_count() { psql -d seetlu -Atc "SELECT count(*) FROM $1" 2>/dev/null || echo "-"; }

point="drill-$(date -u +%Y%m%dT%H%M%SZ)"
declare -A before
for t in $TABLES; do before[$t]=$(live_count "$t"); done
psql -d seetlu -Atc "SELECT pg_create_restore_point('$point')" >/dev/null
psql -d seetlu -Atc "SELECT pg_switch_wal()" >/dev/null
# wait until the switched segment is archived, then ship it
for _ in $(seq 1 30); do
  ready=$(psql -d seetlu -Atc "SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready'")
  [[ $ready == 0 ]] && break
  sleep 1
done
ship_wal

latest=$(s3 ls "s3://$BUCKET/base/" | awk '/PRE/ {sub("/", "", $2); print $2}' | sort | tail -1)
[[ -n $latest ]] || { log "restore: no base backup in s3://$BUCKET/base/"; exit 1; }
log "restore: base $latest + WAL to restore point $point into $data"
mkdir -p "$data" "$work/wal"
s3 cp --only-show-errors "s3://$BUCKET/base/$latest/base.tar.gz" "$work/base.tar.gz"
tar -xzf "$work/base.tar.gz" -C "$data"
s3 sync --only-show-errors "s3://$BUCKET/wal/" "$work/wal/"
rm -f "$data/postmaster.pid"
cat >>"$data/postgresql.auto.conf" <<CONF
restore_command = 'cp $work/wal/%f %p'
recovery_target_name = '$point'
recovery_target_action = 'promote'
archive_mode = off
CONF
touch "$data/recovery.signal"
chown -R postgres:postgres "$work"
chmod 700 "$data"
su-exec postgres pg_ctl -D "$data" -l "$work/restore.log" -o "-p $port -c listen_addresses=localhost" -w -t 600 start

for _ in $(seq 1 300); do
  [[ $(psql -h localhost -p $port -d seetlu -Atc "SELECT pg_is_in_recovery()" 2>/dev/null) == f ]] && break
  sleep 1
done
if ! grep -q "recovery stopping at restore point \"$point\"" "$work/restore.log"; then
  log "restore: the restore point was not reached"; tail -20 "$work/restore.log"; exit 1
fi

status=0
printf '%-14s %10s %10s\n' table live restored
for t in $TABLES; do
  restored=$(psql -h localhost -p $port -d seetlu -Atc "SELECT count(*) FROM $t" 2>/dev/null || echo "-")
  printf '%-14s %10s %10s\n' "$t" "${before[$t]}" "$restored"
  # writes may land between the count and the restore point, never before the count
  if [[ ${before[$t]} == "-" || $restored == "-" ]] || ((restored < before[$t])); then status=1; fi
done

if [[ ${RESTORE_ONLY:-0} == 1 ]]; then
  log "restore: server left running on port $port with data in $data"
  exit $status
fi
su-exec postgres pg_ctl -D "$data" -m fast -w stop >/dev/null
rm -rf "$work"
if ((status == 0)); then
  metric seetlu_restore_drill_last_success_timestamp_seconds "$(date +%s)"
  log "restore drill PASSED (base $latest, restore point $point)"
else
  log "restore drill FAILED"
fi
exit $status
