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
| M3–M10 | to do |

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

## Repo layout

```
backend/            FastAPI api, Celery worker/beat, report engine, messaging (incl. mock inbox)
edge/agent/         seetlu-agent (runs next to Frigate on the kit, arm64)
edge/fake-frigate/  Frigate simulator for dev and tests
edge/mosquitto/     dev MQTT broker config
web/                React PWA (owner, installer, support)
ops/                dev and production scripts
docs/               specs + decisions.md
```

## Docs

| Doc | Content |
| --- | --- |
| `CLAUDE.md` | Instructions, locked stack, conventions, rules, definition of done |
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
| `docs/decisions.md` | Decision log (Claude Code appends to it) |

Product spec for humans: "Seetlu — Small-Shop Vision Kit: Product & Build Spec v1" (Claude doc).
