#!/usr/bin/env bash
# Shared setup for the ops tests: a throwaway copy of the production stack under its own project name.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
tmp=$(mktemp -d)
project=${OPS_TEST_PROJECT:-seetlu-opstest}

cat >"$tmp/env" <<ENV
SEETLU_ENV=staging
SEETLU_DOMAIN=localhost
ACME_EMAIL=ops@example.test
CADDY_TLS=internal
POSTGRES_PASSWORD=$(openssl rand -hex 16)
MINIO_ROOT_USER=seetlu
MINIO_ROOT_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)
RAW_PUBLIC_KEY_B64=test-public-key
MESSAGING_PROVIDER=mock
MOCK_WHATSAPP_URL=http://localhost:9
DEV_FIXED_OTP=
BACKUP_S3_BUCKET=seetlu-backups
ALERT_WEBHOOK_URL=http://localhost:9/disabled
LOG_DRIVER=json-file
HTTP_PORT=${HTTP_PORT:-18080}
HTTPS_PORT=${HTTPS_PORT:-18443}
SEETLU_ENV_FILE=$tmp/env
SEETLU_WORKER_ENV_FILE=$tmp/worker
ENV
echo "RAW_PRIVATE_KEY_B64=test-private-key" >"$tmp/worker"

dc() { docker compose -p "$project" -f "$root/ops/docker-compose.prod.yml" --env-file "$tmp/env" "$@"; }
cleanup() { dc down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
psql_live() { dc exec -T db psql -U seetlu -d seetlu -Atc "$1"; }
