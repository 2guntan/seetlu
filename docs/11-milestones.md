# 11 — Milestones (build in this order)

Each milestone ends with: tests green in CI, `make up && make seed` demo working, `docs/decisions.md` updated, a short summary of what was built and what is left. Commit per milestone on a branch `m<N>-<slug>` and open a PR to `main`.

| # | Milestone | Main docs | Done when |
| --- | --- | --- | --- |
| M0 | Repo scaffold: monorepo layout, Makefile, docker-compose (timescaledb, redis, minio, api, worker, beat, web, mosquitto, fake-frigate stub, mock WhatsApp), CI (lint, types, tests), `.env.example`, README | 02, CLAUDE.md | `make up` starts everything; CI green on an empty test per package |
| M1 | Database: Alembic migration from 03-data-model.sql, SQLAlchemy models, uuid7, seed skeleton | 03 | Migration up/down works on a clean DB; model tests |
| M2 | Auth + core API: OTP via MockProvider, JWT, `authorize()` matrix, accounts/shops/users/alert-rules CRUD, problem+json | 04, 09 | Exhaustive permission tests pass; OpenAPI served at `/docs` matches 04 |
| M3 | Edge ingest API: register, config (ETag), events (idempotent upsert incl. is_staff correction), heartbeat, commands queue + results, presigned uploads | 04, 05 | Contract tests for every edge endpoint |
| M4 | fake-frigate + scenarios + expected outputs | 10 | All 7 scenarios publish deterministic MQTT + HTTP |
| M5 | seetlu-agent: Frigate config renderer, door logic, staff tagging, counter state machine, after-hours, outbox/uploader, config poll, commands (clip via ffmpeg, snapshot, count check), heartbeat, LAN setup page; arm64 image | 05 | Agent integration tests: every scenario → expected events; rendered Frigate config passes the "no biometrics" assertion |
| M6 | Report engine: metrics, baselines, verdict, confidence, moments, vs-last-week, scheduling (beat), recompute on late data | 06 | Domain tests incl. boundaries; e2e `normal-day` produces the golden report |
| M7 | WhatsApp: provider interface, Cloud API client, MockProvider + dev inbox, templates, webhook + signature, inbound grammar, quick log, cash prompt, corrections, clip/photo replies, alerts | 07 | Grammar table fully tested; e2e: reply `1` returns a clip link |
| M8 | Web app: owner screens, installer flow (zone drawing, count check, activation rules), support console, i18n fr/en (wo keys present), PWA offline cache, bundle budget | 08 | Playwright journeys pass; bundle ≤ 300 KB gz |
| M9 | Android shop-phone app: pairing, parser engine from JSON rules, notification listener, Room queue, WorkManager upload, quick-log pad, health screen | 08 | Unit tests on fixtures; MockWebServer upload tests; debug APK built in CI |
| M10 | Ops: production compose / IaC for a Senegal VM, TLS, backups + restore script, monitoring (Prometheus + Grafana or Uptime checks), log retention, edge OS provisioning script, OTA flow, field-validation doc, runbooks | 05, 09 | Fresh VM deploy from README in < 1 h; restore drill passes; provision script tested on an arm64 VM |

## Out of MVP (do not start)

Shelf camera and empty-shelf alerts; Wolof voice notes; POS webhook; lender data share; multi-country billing automation.
