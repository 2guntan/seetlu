#!/bin/sh
# First start only: let the backup service (same compose network) run pg_basebackup.
set -e
echo "host replication seetlu samenet scram-sha-256" >>"$PGDATA/pg_hba.conf"
