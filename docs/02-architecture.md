# 02 — Architecture and repo layout

## Components

```
 SHOP (per kit)                                   CLOUD (hosted in Senegal)                 OWNER
 ┌───────────────────────────────┐                ┌──────────────────────────────┐          ┌────────────┐
 │ 2 PoE IP cameras (RTSP)       │                │ api (FastAPI)                │◄────────►│ web (PWA)  │
 │   │                           │   HTTPS only,  │ worker + beat (Celery)       │          └────────────┘
 │   ▼                           │   outbound     │ postgres + timescaledb       │          ┌────────────┐
 │ Frigate (rknn detector)       │   from shop    │ redis                        │─────────►│ WhatsApp   │
 │   │ MQTT (mosquitto, local)   │ ─────────────► │ minio (clips, snapshots)     │◄─────────│ (Cloud API)│
 │   ▼                           │                │ messaging provider (WA/mock) │          └────────────┘
 │ seetlu-agent (Python)         │                └──────────────────────────────┘
 │   SQLite queue, uploader      │                           ▲
 └───────────────────────────────┘                           │ HTTPS
 ┌───────────────────────────────┐                           │
 │ Shop phone app (Android)      │───────────────────────────┘
 │ reads Wave / Orange Money     │
 └───────────────────────────────┘
```

- The edge box never accepts inbound connections. It polls the cloud for config and commands (every 30 s).
- Frigate does detection and tracking only. All Seetlu logic (line crossing, zones, staff tagging, events) lives in `seetlu-agent`.
- The cloud is the source of truth for configuration; the agent caches the last config on disk.

## Repo layout (monorepo)

```
seetlu/
├── CLAUDE.md
├── README.md
├── Makefile
├── docker-compose.yml              # dev stack
├── .env.example
├── .github/workflows/              # ci.yml, edge-image.yml
├── docs/                           # this pack + decisions.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                    # migrations (first migration = docs/03-data-model.sql)
│   ├── seetlu/
│   │   ├── api/                    # routers per resource
│   │   ├── core/                   # config, security, ids (uuid7), i18n, problem+json
│   │   ├── db/                     # models, session
│   │   ├── domain/                 # pure logic: report engine, verdict, baselines, moments, alerts
│   │   ├── messaging/              # MessagingProvider, whatsapp_cloud.py, mock.py, templates/
│   │   ├── storage/                # S3 client, signed URLs
│   │   ├── workers/                # celery app, tasks, schedules
│   │   └── seed/                   # demo data generator
│   └── tests/
├── edge/
│   ├── agent/                      # seetlu-agent python package
│   │   ├── seetlu_agent/
│   │   │   ├── frigate_client.py   # MQTT subscribe + HTTP API (clips, snapshots)
│   │   │   ├── geometry.py         # line crossing, point-in-polygon
│   │   │   ├── door.py             # F1 logic
│   │   │   ├── counter.py          # F2 logic
│   │   │   ├── staff.py            # staff tagging
│   │   │   ├── queue.py            # SQLite outbox
│   │   │   ├── uploader.py
│   │   │   ├── commands.py         # clip/snapshot/count-check commands
│   │   │   ├── health.py           # heartbeat
│   │   │   ├── config.py
│   │   │   └── main.py
│   │   └── tests/
│   ├── frigate/
│   │   └── config.template.yml     # rendered by the agent from cloud config
│   ├── fake-frigate/               # simulator publishing Frigate-shaped MQTT events (dev + tests)
│   ├── docker-compose.edge.yml     # frigate + mosquitto + seetlu-agent (arm64)
│   └── os/                         # provisioning script for Orange Pi 5 (Armbian/Ubuntu Rockchip BSP)
├── web/                            # React PWA (owner + installer + support console)
│   └── src/{routes,components,api,i18n,lib}
└── android/
    └── shop-phone/                 # Kotlin app: notification listener + quick log pad
```

## Request flows

1. **Events**: Frigate → MQTT `frigate/events` → agent logic → SQLite outbox → `POST /v1/edge/events` (batches ≤ 500, every 60 s or when 100 queued).
2. **Heartbeat**: agent → `POST /v1/edge/heartbeat` every 5 min.
3. **Config**: agent → `GET /v1/edge/config` every 30 s with `If-None-Match`; on change re-render Frigate config and restart Frigate only if camera/zone geometry changed.
4. **Commands**: agent → `GET /v1/edge/commands` every 30 s → executes clip/snapshot/count-check → `POST /v1/edge/commands/{id}/result` (+ upload to presigned URL).
5. **Sales**: phone app → `POST /v1/sales/batch` (device token).
6. **Report**: beat schedules per-shop `compute_and_send_daily_report` at local `report_time`; worker computes → selects moments → requests clips → sends template (clip links are generated lazily when the owner replies `1/2/3`).
7. **WhatsApp inbound**: Meta webhook → `POST /v1/webhooks/whatsapp` → command parser → action → reply.

## Environments

| Env | Where | Notes |
| --- | --- | --- |
| dev | docker compose on laptop | fake-frigate + mock WhatsApp |
| staging | 1 VPS | real WhatsApp test number |
| prod | Senegal-hosted VMs (to be chosen) | Postgres with daily backups + WAL archiving to MinIO |
