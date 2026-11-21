# Runbook — deploy production on a fresh VM (target: under 1 hour)

Provider-agnostic: any Senegal-hosted VM (docs/09 hosting rule) with Ubuntu 24.04, 4 vCPU, 8 GB RAM,
100 GB SSD, a public IPv4. Choosing the provider is a human task (docs/12).

| Step | Time |
| --- | --- |
| 1. Create the VM with `ops/vm/cloud-init.yml` as user-data (put the ops SSH key in it) | 10 min |
| 2. DNS: `A` records for `<domain>` and `files.<domain>` → the VM IP | 5 min (+ propagation) |
| 3. Prepare + secrets + start | 25 min (mostly image builds) |
| 4. Checks | 10 min |

## 1–2. VM and DNS

Without cloud-init: `ssh` in, `sudo git clone https://github.com/2guntan/seetlu.git /opt/seetlu`, then
`sudo /opt/seetlu/ops/vm/setup.sh`. It installs Docker, the firewall (22/80/443), unattended upgrades,
key-only SSH, 30-day journald retention, and the `seetlu` + `seetlu-restore-drill.timer` units.

## 3. Secrets and start

```bash
cd /opt/seetlu
sudo make prod-secrets DOMAIN=app.example.sn EMAIL=ops@example.sn   # writes .env.prod + .env.worker (600)
sudo nano .env.prod   # WA_PHONE_NUMBER_ID, WA_ACCESS_TOKEN, WA_APP_SECRET (Meta, docs/07); ALERT_WEBHOOK_URL
sudo systemctl start seetlu   # = make prod-up: builds, migrates, starts, waits for health
```

The API refuses to start with dev values (`SEETLU_ENV=prod`: no dev JWT secret, no `DEV_FIXED_OTP`,
`MESSAGING_PROVIDER=whatsapp_cloud`). Use `SEETLU_ENV=staging` for the staging VM (mock inbox allowed).

## 4. Checks

```bash
curl -fsS https://app.example.sn/healthz                 # {"status":"ok",…}
sudo docker compose -f ops/docker-compose.prod.yml --env-file .env.prod ps   # all healthy / running
sudo make backup-now && sudo make restore-drill          # first base backup + a drill (must PASS)
ssh -L 3000:localhost:3000 -L 9090:localhost:9090 <vm>    # Grafana "Seetlu production", Prometheus targets up
```

Then in Meta: webhook URL `https://<domain>/v1/webhooks/whatsapp`, verify token = `WA_VERIFY_TOKEN`.
First people and kits (each writes an audit row):

```bash
P="docker compose -f ops/docker-compose.prod.yml --env-file .env.prod run --rm api python -m seetlu.admin"
sudo $P create-staff --role support --name "Support Seetlu" --phone +22177…
sudo $P create-staff --role installer --name "Installateur" --phone +22177…
sudo $P create-owner --account "Boutique Awa" --name "Awa Ndiaye" --phone +22177…
sudo $P register-kit --serial SN-0042   # prints the claim token + QR payload: print the QR, stick it on the box
```

Then provision the box (`edge/os/provision.sh`, kit-offline runbook), the owner adds the shop in the app,
and the installer claims the kit by scanning the QR.

## Updating

```bash
cd /opt/seetlu && sudo git pull && sudo make prod-up   # migrations run first (one-shot `migrate` service)
```

Roll back: `sudo git checkout <previous tag> && sudo make prod-up`. Migrations are forward-only; a release
that changes the schema says so in its PR, and the restore drill is the way back.
