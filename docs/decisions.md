# Decision log

| Date | Question | Decision | Why |
| --- | --- | --- | --- |
| 2026-11-20 | Edge hardware | Rockchip RK3588 (Orange Pi 5) + Frigate rknn detector; fallback Raspberry Pi 5 + AI HAT+ | Cheapest from China, Frigate supports the NPU natively |
| 2026-11-20 | Door counting method | Two band zones (`door_out`, `door_in`) and zone-sequence logic, not pixel line crossing | Frigate publishes zone changes reliably; positions are not streamed every frame |
| 2026-11-20 | Core health metric | Revenue per served customer vs the shop's own 14–28 day baseline | Works without per-sale cash logging; robust to shop size |
| 2026-11-20 | Video in the cloud | Only requested clips (≤ 20 s, 480p) and snapshots | Privacy, data cost, CDP regime |
| 2026-11-20 | M0: Python package management | `uv` with one `pyproject.toml` + `uv.lock` per Python package (`backend`, `edge/agent`, `edge/fake-frigate`) | Each package ships as its own image; uv is fast and gives reproducible locks |
| 2026-11-20 | M0: health endpoint not in 04-api | Add `GET /healthz` (ops only, no auth) on api, mock WhatsApp and fake-frigate | Needed for compose healthchecks and `make up --wait`; not a product feature |
| 2026-11-20 | M0: mock WhatsApp service | Separate `mock-whatsapp` compose service running `seetlu.messaging.mock_inbox` from the backend image; in-memory inbox at `GET /messages` | Simplest dev inbox; the `MessagingProvider` interface and persistence come in M7 |
| 2026-11-20 | M0: Android scaffold timing | `android/shop-phone/` is created in M9, not M0 | M0 "empty test per package" covers the packages the dev stack runs; Gradle/Android SDK in CI only when the app exists |
| 2026-11-20 | M0: edge agent in dev stack | The dev compose also runs `agent` (connected to `fake-frigate` via mosquitto) | Lets `make sim-day` drive the real agent later without a separate stack |
| 2026-11-20 | M0: edge image publishing | `edge-image.yml` builds amd64 + arm64 on PRs and pushes `ghcr.io/<owner>/seetlu-agent:<sha>` on `main` | Multi-arch build proven early; push only from main |
| 2026-11-20 | M0: MinIO image | MinIO removed its Docker Hub/quay images (Oct 2025) and archived upstream (2026). Dev uses `cgr.dev/chainguard/minio` pinned by digest; bucket created by `python -m seetlu.storage.init_bucket` (boto3) because the image has no shell | Keeps the locked S3/MinIO choice working in dev. **Open for M10:** production object store (patched MinIO build vs another S3-compatible store) needs an owner decision |
| 2026-11-20 | M1: how the first migration applies 03-data-model.sql | Copy the file verbatim to `backend/alembic/sql/0001-initial.sql` and run it with `exec_driver_sql`; a test fails if the copy drifts from `docs/03-data-model.sql` | The SQL stays the single source of truth; the copy is needed because the api image only contains `backend/` |
| 2026-11-20 | M1: downgrade of 0001 | Drop all tables and enum types; keep the `timescaledb` and `citext` extensions | Extensions are database-level and harmless; dropping timescaledb mid-session is fragile |
| 2026-11-20 | M1: UUIDv7 generator | Own RFC 9562 implementation in `seetlu.core.ids` (48-bit ms + 12-bit monotonic counter + random) | Python 3.12 has no `uuid.uuid7`; avoids a dependency; monotonic within a process |
| 2026-11-20 | M1: models vs schema | `tests/test_models.py` runs Alembic `compare_metadata` against the migrated DB and must return no diff (types, indexes, FKs, uniques) | Catches model drift automatically |
| 2026-11-20 | M1: token hashing | argon2id (`argon2-cffi`) for claim tokens, device tokens and OTP codes | Required by docs/09 for device tokens; one helper for all |
| 2026-11-20 | M1: seed scope | Seed skeleton now (account, 5 role users, 2 shops Dakar/Abidjan, 2 kits with door+counter cameras and zones, alert rules); 30 days of events and sales are added in M6 with the report engine | Seed data must match real engine outputs (2 worth_a_look, 1 large_gap, 1 missing-hours day) |
| 2026-11-20 | M1: backend DB tests | testcontainers (`timescale/timescaledb:2.17.2-pg16`), one container per session; each up/down test uses its own database | docs/10 test layer "API: pytest + testcontainers" |
