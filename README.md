# Seetlu

Camera kit + service for small shops in Senegal and Côte d'Ivoire: every evening, one WhatsApp message
tells the owner whether the day's activity matched the day's money.

Specifications live in `docs/` (start with `CLAUDE.md`, then `docs/11-milestones.md`); code is built
milestone by milestone (M0–M10).

## Status

| Milestone | State |
| --- | --- |
| M0 Repo scaffold | done: monorepo layout, Makefile, dev compose, CI |
| M1 Database | done: Alembic migration (03-data-model.sql), SQLAlchemy models, UUIDv7, seed skeleton |
| M2 Auth + core API | done: OTP login over (mock) WhatsApp, JWT access/refresh, `authorize()` matrix, shops/users/alert-rules, problem+json |
| M3 Edge ingest API | done: register, config (ETag), idempotent events, heartbeat, command queue + results, presigned uploads |
| M4 fake-frigate | done: 7 deterministic scenarios with `expected.json` ground truth, Frigate-shaped MQTT + HTTP |
| M5 seetlu-agent | done: door/staff/counter/after-hours logic, Frigate config renderer (no biometrics), SQLite WAL outbox + uploader, ETag config, commands (clip, snapshot, count check, update, reboot), heartbeats, LAN setup page, `make sim-day` |
| M6 | done: report engine (metrics, baseline, verdict, confidence, moments, vs last week), beat scheduling, late-data recompute, 30-day seed history, `make report`, `make e2e` golden |
| M7 | done: WhatsApp provider (mock + Cloud API), webhook, inbound grammar (1/2/3, photo, faux, +amount, cash reply, annuler, stop/start, aide), clip links, alerts, cash prompt, mock inbox page |
| M8 | done: web app (owner screens, installer flow with zone drawing + count check + activation rules, support console), i18n fr/en (wo keys), PWA offline cache, bundle budget, 5 Playwright journeys |
| M9 | done: shop phone app (pairing, parser rules from the server, notification listener, sealed raw text, Room queue, WorkManager upload, quick-log pad, health screen) + phone API (pairing codes, parsers, sales batch) |
| M10 | done: production compose (Caddy TLS, one-shot migrations, worker-only private key, dev values refused), Postgres base backup + WAL to MinIO with 30-day retention and a restore drill, Prometheus/Alertmanager/Grafana, journald log retention, VM setup + cloud-init, operator CLI, edge OS provisioning (tested on arm64), OTA release flow, runbooks, field-validation protocol |
| Design system | done: `DESIGN.md` (tokens, type, verdict colours, components); `web/src/styles.css` carries the tokens as CSS custom properties, light + dark; Atkinson Hyperlegible Next self-hosted and precached |

## Quick start (dev)

Requirements: Docker Desktop, `uv` (Python 3.12), Node 22, `make`.

```bash
make install   # local Python + npm deps (for lint/test outside Docker)
make up        # build + start the dev stack, waits for health
make seed      # migrate + demo account, 2 shops, 2 kits (idempotent)
make lint
make test
make down
```

| Service | URL |
| --- | --- |
| API (OpenAPI UI) | http://localhost:8000/docs (health: `/healthz`) |
| Web app (PWA) | http://localhost:5173 |
| Mock WhatsApp inbox | http://localhost:8025/messages (`?to=+221770000001`) |
| MinIO console | http://localhost:9001 (minio / minio123) |
| fake-frigate | http://localhost:5050/api/version |
| MQTT (mosquitto) | localhost:1883 |

Demo logins (OTP `000000` in dev): owner `+221770000001`, manager `…02`, staff `…03`,
installer `…04`, support `…05`. Backend tests start a TimescaleDB container (Docker required).

Secrets come from `.env` (copied from `.env.example` on first `make up`); never commit real values.

### Try the API

```bash
curl -X POST localhost:8000/v1/auth/otp/request -H 'content-type: application/json' -d '{"phone_e164":"+221770000001"}'
curl -X POST localhost:8000/v1/auth/otp/verify  -H 'content-type: application/json' -d '{"phone_e164":"+221770000001","code":"000000"}'
```

Edge endpoints (as the agent will call them):

```bash
curl -X POST localhost:8000/v1/edge/register -H 'content-type: application/json' -d '{"serial":"DEV-KIT-0001","claim_token":"dev-claim-token"}'
curl localhost:8000/v1/edge/config -H "Authorization: Bearer <device_token>"
```

### Simulator

```bash
curl localhost:5050/sim/scenarios                                   # list scenarios
curl -X POST "localhost:5050/sim/scenarios/normal-day/run?speed=600" # 1 simulated day in ~2.5 min
cd edge/fake-frigate && uv run fake-frigate expect normal-day       # ground truth for a scenario
```

### One simulated day through the real agent

```bash
make sim-day SHOP=DEV-KIT-0001 DATE=2026-11-20                          # shop id or kit serial
make sim-day SHOP=<shop id> DATE=2026-11-20 SCENARIO=power-cut-14-16    # any scenario name
```

`sim-day` stops the dev agent, runs `seetlu-agent replay` for the shop's kit on the simulator clock,
plays the scenario at full speed (~30 s), uploads events + heartbeats, then restarts the dev agent.
Event ids are deterministic UUIDv7, so re-running the same day changes nothing on the server.

The agent's LAN setup page is on http://localhost:8080 (user: any, PIN: last 6 characters of
`KIT_CLAIM_TOKEN`); it only answers private/loopback client addresses.

### Daily report

```bash
make seed                                   # also 30 days of history before 2026-11-20 (SEED_ANCHOR_DATE)
make report SHOP=DEV-KIT-0001 DATE=2026-11-19   # compute, send to the mock inbox, print the message
make e2e                                    # normal-day through the real agent → report == golden file
```

The message lands in the mock WhatsApp inbox: http://localhost:8025 (reply there as any seeded phone:
`1`, `photo`, `+2500`, `faux`, `aide`…). `make e2e` ends with the owner replying `1` and the agent's clip
link arriving in the inbox. The worker's beat sends each
shop's report at its local `report_time` (default 21:00).

### Web app

http://localhost:5173 → sign in with a demo phone and code `000000`. Owner: Today, History (calendar
coloured by verdict), Day detail (hourly bars, moments with video, sales, « Corriger »), Moments, Sales,
Settings, Journal. Installer (`…04`): claim kit → shop → snapshot + zones per camera → count check →
activate. Support (`…05`): kits by health, kit page.

```bash
cd web && npm test && npm run build && npm run check-bundle   # vitest + 300 KB gz budget
cd web && npx playwright test                                 # the 5 journeys (API mocked)
```

### Shop phone app (Android)

Requirements: JDK 17 and the Android SDK (`android/local.properties` with `sdk.dir=…`).

```bash
cd android && ./gradlew :shop-phone:testDebugUnitTest :shop-phone:assembleDebug
adb install -r shop-phone/build/outputs/apk/debug/shop-phone-debug.apk   # emulator: talks to http://10.0.2.2:8000
```

Owner web app → Réglages → Téléphone de la boutique → « Afficher un code », type it in the phone app,
then allow notification access from « État du téléphone ». For sealed raw notifications put a key pair in
`.env` (`docker compose run --rm api python -m seetlu.phone.crypto`). Parser rules live in
`backend/seetlu/phone/rules.json` and are **placeholders** until real Wave / Orange Money texts are
collected (docs/12); both test suites run the fixtures in
`android/shop-phone/src/test/resources/notifications/`.

## Production (M10)

Fresh Senegal-hosted Ubuntu 24.04 VM → running stack in under an hour: **`ops/runbooks/deploy.md`**.

```bash
sudo ops/vm/setup.sh                                      # docker, firewall, ssh, journald, systemd units
sudo make prod-secrets DOMAIN=app.example.sn EMAIL=ops@example.sn
sudo systemctl start seetlu                               # = make prod-up (builds, migrates, waits for health)
sudo make backup-now && sudo make restore-drill           # must print "restore drill PASSED"
```

- `ops/docker-compose.prod.yml`: Caddy (Let's Encrypt, TLS 1.2+, PWA + `/v1` + `files.<domain>` for
  presigned clip links), api, worker (the only service with `RAW_PRIVATE_KEY_B64`), beat, Postgres +
  TimescaleDB with WAL archiving, Redis (AOF), MinIO, backup, Prometheus, Alertmanager, blackbox and node
  exporters, Grafana. Only 80/443 are public; monitoring listens on 127.0.0.1 (SSH tunnel).
- Backups: daily `pg_basebackup` + continuous WAL to MinIO, 30 days, optional second copy in Senegal;
  monthly restore drill by a systemd timer (`ops/runbooks/backup-restore.md`).
- Logs: journald, 30 days on the VM, 14 days on kits.
- First accounts and kits: `python -m seetlu.admin create-owner | create-staff | register-kit`.
- Kits: `sudo edge/os/provision.sh --serial … --claim-token … --api-url https://…` (`docs/05`);
  OTA = tag `agent-v<version>`, then set the target version in the support console (`ops/runbooks/ota.md`).
- Runbooks: `ops/runbooks/` (deploy, backup-restore, ota, kit-offline, incident).
  Pilot checks: `docs/field-validation.md`.

```bash
make ops-test          # throwaway copy of the prod stack: restore drill (PITR) + TLS/monitoring smoke test
make provision-test    # edge/os/provision.sh twice in an arm64 Ubuntu 24.04 container
```

## Repo layout

```
backend/            FastAPI api, Celery worker/beat, report engine, messaging (incl. mock inbox)
edge/agent/         seetlu-agent (runs next to Frigate on the kit, arm64)
edge/fake-frigate/  Frigate simulator for dev and tests
edge/frigate/       Frigate config template (rendered by the agent)
edge/mosquitto/     MQTT broker configs (dev, and 127.0.0.1-only for the kit)
edge/docker-compose.edge.yml  production stack on the kit (mosquitto, frigate -rk, seetlu-agent)
edge/os/            provision.sh for the kit OS (+ arm64 test)
web/                React PWA (owner, installer, support)
ops/                production compose, Caddy, backups, monitoring, VM setup, runbooks, ops tests
docs/               specs + decisions.md
```

## Docs

| Doc | Content |
| --- | --- |
| `CLAUDE.md` | Instructions, locked stack, conventions, rules, definition of done |
| `DESIGN.md` | Design system: tokens, typography, colours, components, do's and don'ts |
| `docs/01-product.md` | Features F1–F10 with acceptance criteria |
| `docs/02-architecture.md` | Components, flows, repo layout |
| `docs/03-data-model.sql` | PostgreSQL + TimescaleDB schema (first migration) |
| `docs/04-api.openapi.yaml` | API contract |
| `docs/05-edge-agent.md` | Frigate + seetlu-agent on the edge box |
| `docs/06-report-engine.md` | Metrics, verdict, moments, alerts |
| `docs/07-whatsapp.md` | Templates and inbound commands |
| `docs/08-apps.md` | Web app (owner, installer, support) and Android shop-phone app |
| `docs/09-security-privacy.md` | Legal frame, permissions, security |
| `docs/10-testing.md` | Simulator, scenarios, test layers |
| `docs/11-milestones.md` | Build order M0–M10 |
| `docs/12-human-tasks.md` | What a human must do in parallel |
| `docs/13-ai-box.md` | AI box product spec: reads the shop's existing recorder |
| `docs/field-validation.md` | Pilot protocol: install tally, weekly audits, labelled clips |
| `docs/decisions.md` | Decision log (Claude Code appends to it) |

Product spec for humans: "Seetlu — Small-Shop Vision Kit: Product & Build Spec v1" (Claude doc).
