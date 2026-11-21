# CLAUDE.md — Seetlu

You are building **Seetlu**, a camera kit + service that sends a small-shop owner in Senegal one WhatsApp
message every evening answering: *did today's activity match today's money?*

Read these files before writing code, in this order:

1. `docs/01-product.md` — what we build and the acceptance criteria (source of truth for behaviour)
2. `docs/02-architecture.md` — components, repo layout, tech stack (source of truth for structure)
3. `docs/11-milestones.md` — the build order. Work milestone by milestone. Do not skip ahead.
4. The doc each milestone points to (schema, API, edge agent, report engine, WhatsApp, apps, security, testing)

`docs/12-human-tasks.md` lists what you cannot do (hardware, accounts, legal). Never block on them:
build against the mocks and simulators described in `docs/10-testing.md`.

## Tech stack (locked — do not change without asking)

| Area | Choice |
| --- | --- |
| Backend API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 + TimescaleDB 2.x |
| Jobs and schedules | Celery 5 + Redis 7 (Celery beat for schedules) |
| Object storage | S3-compatible (MinIO locally and in production) |
| Edge agent | Python 3.12, paho-mqtt, httpx, SQLite (WAL), runs in Docker next to Frigate on arm64 |
| Edge video AI | Frigate (open source NVR) with the `rknn` detector on Rockchip RK3588; never fork it |
| Owner + installer web app | React 18, TypeScript, Vite, PWA, TanStack Query, i18next (fr default, wo, en) |
| Shop phone app | Android, Kotlin, minSdk 26, NotificationListenerService, WorkManager, Room |
| Messaging | WhatsApp Business Platform (Cloud API) behind a `MessagingProvider` interface with a mock |
| Dev environment | Docker Compose; Makefile targets |
| CI | GitHub Actions: lint, type-check, tests, build images (amd64 + arm64 for edge) |

## Conventions

- Monorepo layout exactly as in `docs/02-architecture.md`.
- File and folder names: lowercase with hyphens. **Never use underscores in file or folder names**
  (Python module files are the only exception, because Python imports require it).
- Money: integer XOF (FCFA), column suffix `_xof`. Never floats for money.
- Time: store UTC `timestamptz`; every shop has an IANA `timezone`; "a day" is the shop's local day.
- IDs: UUIDv7 everywhere (sortable). Events from the edge carry their own UUIDv7 = idempotency key.
- All user-facing strings go through i18n keys. French is the default language; never hard-code text.
- API errors: RFC 9457 problem+json.
- Python: ruff + mypy --strict; tests with pytest. TypeScript: eslint + tsc --noEmit; tests with vitest.
- Kotlin: ktlint; unit tests with JUnit5.
- Every feature ships with tests that map to the acceptance criteria IDs in `docs/01-product.md`
  (e.g. test names contain `AC-F4-2`).

## Commands (create them in M0 and keep them working)

```
make up          # start postgres, redis, minio, api, worker, beat, web, mock-whatsapp, fake-frigate
make down
make migrate     # alembic upgrade head
make seed        # demo account, 2 shops, 2 kits, 30 days of simulated events and sales
make test        # all test suites
make lint
make sim-day SHOP=<id> DATE=YYYY-MM-DD   # generate a simulated shop day through the real edge agent
make report SHOP=<id> DATE=YYYY-MM-DD    # compute + send (to mock) a daily report
```

## Rules you must follow

1. **No biometrics, ever.** No face detection/recognition, no age, gender, emotion or clothing attributes.
   Frigate face recognition, LPR and semantic search stay disabled in every config you write.
2. **Video stays in the shop by default.** Only events, heartbeats and explicitly requested clips leave the edge box.
3. **Never show zeros for missing data.** If hours are missing, reports say which hours are missing.
4. **Never accuse.** Verdict wording is fixed in `docs/06-report-engine.md`; do not invent new wording.
5. **Every clip access and every support action writes an audit log row.**
6. **Secrets** only via environment variables; `.env.example` lists them; never commit real values.
7. When a spec is ambiguous, pick the simplest option that satisfies the acceptance criteria,
   write the decision in `docs/decisions.md` (date, question, decision, why), and continue.
8. Do not add features that are not in `docs/01-product.md`. Ask instead.

## Definition of done (per milestone)

- All acceptance criteria for the milestone have passing automated tests.
- `make lint` and `make test` pass in CI.
- `make up && make seed` gives a working demo for the milestone.
- `docs/decisions.md` and `README.md` updated.

## Design System

Read `DESIGN.md` before visual or UI work: it defines the fonts, colors, spacing, and
aesthetic direction. Ask the user before departing from it. When reviewing or QA-ing
UI, flag code that doesn't match `DESIGN.md`.
