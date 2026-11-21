#!/usr/bin/env bash
# Whole production stack on this machine (Caddy local CA instead of Let's Encrypt): TLS entry point,
# PWA, API, presigned-file host, private key only on the worker, monitoring targets up.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"
port=$(sed -n 's/^HTTPS_PORT=//p' "$tmp/env")

echo "== up (build + wait)"
dc up -d --build --wait --wait-timeout 600

fail() { echo "FAIL: $*"; dc ps; exit 1; }
curl_k() { curl -ksS --resolve "localhost:$port:127.0.0.1" --resolve "files.localhost:$port:127.0.0.1" "$@"; }

echo "== TLS entry point"
curl_k "https://localhost:$port/healthz" | grep -q '"status":"ok"' || fail "healthz through Caddy"
curl_k "https://localhost:$port/" | grep -q '<div id="root">' || fail "PWA index"
curl_k "https://localhost:$port/some/deep/link" | grep -q '<div id="root">' || fail "SPA fallback"
curl_k -o /dev/null -w '%{http_code}' "https://files.localhost:$port/minio/health/live" | grep -q 200 || fail "files host"
code=$(curl_k -o /dev/null -w '%{http_code}' -X POST "https://localhost:$port/v1/auth/otp/request" \
  -H 'content-type: application/json' -d '{"phone_e164":"+221770000099"}')
[[ $code =~ ^2 ]] || fail "OTP request through Caddy returned $code"
curl -sS -o /dev/null --tls-max 1.1 -k "https://127.0.0.1:$port/" 2>/dev/null && fail "TLS 1.1 accepted"
curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$(sed -n 's/^HTTP_PORT=//p' "$tmp/env")/" -H 'Host: localhost' \
  | grep -q 308 || fail "http does not redirect to https"

echo "== secrets: raw-notification private key only on the worker (docs/09)"
[[ -z $(dc exec -T api printenv RAW_PRIVATE_KEY_B64 || true) ]] || fail "API has the private key"
[[ $(dc exec -T worker printenv RAW_PRIVATE_KEY_B64) == test-private-key ]] || fail "worker lacks the private key"
dc exec -T api printenv DEV_FIXED_OTP | grep -q . && fail "DEV_FIXED_OTP set"

echo "== monitoring"
for _ in $(seq 1 30); do
  up=$(dc exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=up' | grep -o '"value":\[[^]]*,"1"\]' | wc -l)
  ((up >= 4)) && break
  sleep 3
done
((up >= 4)) || fail "prometheus targets not up ($up)"
dc exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/rules' | grep -q BaseBackupMissing || fail "alert rules"
dc exec -T grafana wget -qO- http://localhost:3000/api/health | grep -q '"database": *"ok"' || fail "grafana"
for _ in $(seq 1 60); do
  dc exec -T node-exporter wget -qO- http://localhost:9100/metrics | grep -q '^seetlu_backup_last_base_timestamp_seconds' && break
  sleep 5
done
dc exec -T node-exporter wget -qO- http://localhost:9100/metrics | grep -q '^seetlu_backup_last_base_timestamp_seconds' \
  || fail "backup service did not record a base backup"
echo "prod smoke PASSED"
