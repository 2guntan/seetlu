#!/usr/bin/env bash
# docs/11 M10 "restore drill passes": seed → base backup → more writes (WAL only) → restore from MinIO
# into a scratch server → the restored database has the seeded data AND the post-backup writes.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"

echo "== start db, minio; migrate; seed"
dc up -d --build --wait db minio
dc run --rm migrate
dc run --rm --no-deps -e SEETLU_ENV=dev api python -m seetlu.seed >/dev/null

echo "== base backup"
dc run --rm backup backup-now.sh

echo "== writes after the base backup (only in WAL)"
psql_live "CREATE TABLE drill_probe (n int); INSERT INTO drill_probe SELECT generate_series(1, 1234);"

echo "== restore drill"
dc run --rm -e DRILL_TABLES="accounts shops users kits events sales daily_reports audit_log drill_probe" \
  backup restore-drill.sh | tee "$tmp/drill.log"
grep -Eq '^drill_probe +1234 +1234$' "$tmp/drill.log" || { echo "FAIL: post-backup writes not restored"; exit 1; }
grep -Eq '^events +[1-9][0-9]* ' "$tmp/drill.log" || { echo "FAIL: seeded events missing"; exit 1; }

echo "== retention keeps the newest base and prunes older ones"
dc run --rm -e BACKUP_RETENTION_DAYS=0 backup backup-now.sh >/dev/null
# shellcheck disable=SC2016 # expanded inside the container
n=$(dc run --rm backup bash -c 'source /usr/local/bin/lib.sh; s3 ls "s3://$BUCKET/base/" | grep -c PRE' 2>/dev/null | tail -1)
[[ $n == 1 ]] || { echo "FAIL: expected 1 base backup after retention 0, got $n"; exit 1; }
echo "restore drill test PASSED"
