#!/usr/bin/env bash
# Create .env.prod (from .env.prod.example, fresh random secrets) and .env.worker (raw-notification
# private key, given to the worker only — docs/09). Refuses to overwrite existing files.
#
#   ops/vm/gen-secrets.sh [--domain app.example.sn] [--email ops@example.sn]
set -euo pipefail
cd "$(dirname "$0")/../.."

domain="" email=""
while (($#)); do
  case $1 in
    --domain) domain=$2; shift 2 ;;
    --email) email=$2; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

for f in .env.prod .env.worker; do
  [[ -e $f ]] && { echo "$f exists; not overwriting (delete it first to regenerate)" >&2; exit 1; }
done

rand() { openssl rand -hex 32; }
keys=$(docker run --rm "$(docker build -q backend)" python -m seetlu.phone.crypto)
pub=$(sed -n 's/^RAW_PUBLIC_KEY_B64=//p' <<<"$keys")
priv=$(sed -n 's/^RAW_PRIVATE_KEY_B64=//p' <<<"$keys")
[[ -n $pub && -n $priv ]] || { echo "key generation failed" >&2; exit 1; }

umask 077
while IFS= read -r line; do
  while [[ $line == *__RANDOM__* ]]; do line=${line/__RANDOM__/$(rand)}; done
  line=${line/__RSA_PUBLIC__/$pub}
  [[ -n $domain && $line == SEETLU_DOMAIN=* ]] && line="SEETLU_DOMAIN=$domain"
  [[ -n $email && $line == ACME_EMAIL=* ]] && line="ACME_EMAIL=$email"
  printf '%s\n' "$line"
done <.env.prod.example >.env.prod
printf '# worker only (docs/09)\nRAW_PRIVATE_KEY_B64=%s\n' "$priv" >.env.worker
echo "wrote .env.prod and .env.worker (mode 600). Fill in the WA_* values from Meta before going live."
