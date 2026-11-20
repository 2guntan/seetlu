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
