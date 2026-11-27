# 05 — Edge box: Frigate + seetlu-agent

## Hardware and OS (reference kit)

- Orange Pi 5 Plus (RK3588, 8 GB, 2 × Ethernet: one to the shop's recorder, one to the internet; spec in `docs/13-ai-box.md`) with a Rockchip BSP kernel (5.10.x-rockchip or 6.1.x-rockchip) so that `/dev/dri/renderD129` (NPU) and the RKNN runtime are available. The plain Orange Pi 5 (RK3588S, one Ethernet port) runs the same image. Raspberry Pi 5 + AI HAT+ would need a Hailo mode that is not built.
- 128 GB NVMe mounted at `/data`. Docker + Docker Compose v2.
- `edge/os/provision.sh` must: set hostname to the kit serial, create `/data/{frigate,agent}`, install Docker, enable unattended security upgrades, configure the hardware watchdog, disable SSH password login, install the systemd unit that starts `docker-compose.edge.yml` on boot.

## Containers (`edge/docker-compose.edge.yml`)

| Service | Image | Notes |
| --- | --- | --- |
| mosquitto | eclipse-mosquitto:2 | Bound to 127.0.0.1 only |
| frigate | ghcr.io/blakeblackshear/frigate:stable-rk | Devices: /dev/dri, /dev/mpp_service, /dev/rga, /dev/dma_heap; config rendered by the agent |
| seetlu-agent | ghcr.io/<org>/seetlu-agent:<version> (arm64) | Mounts /data/agent, /data/frigate/config, docker socket (for restarts and self-update) |

Camera RTSP credentials are entered by the installer on the box (local setup page served by the agent on the LAN only, port 8080, PIN = last 6 of claim token) and stored in `/data/agent/secrets.json` (chmod 600). They never go to the cloud.

## Frigate configuration rendered by the agent

The agent renders `edge/frigate/config.template.yml` from the cloud `EdgeConfig`. Rules:

- One Frigate camera per Seetlu camera. `detect` uses the sub stream (640×360, 5 fps). `record` uses the sub stream, `retain: {days: 7, mode: motion}`.
- `objects.track: [person]` only. `snapshots.enabled: false`.
- **Disabled and never re-enabled:** `face_recognition`, `lpr`, `semantic_search`, `genai`, `birdseye`, `audio`.
- Detector: `rknn` with `num_cores: 3` and the default yolo-nas-s or yolov8n RKNN model shipped with the image.
- Zones are generated from Seetlu zones (coordinates converted from normalised 0..1 to detect pixels):
  - `door_line` → two band polygons `door_out` and `door_in`, each 40 px deep, on either side of the line; `inward_side` decides which band is `door_in`.
  - `customer_side` → zone `counter_customer`; `staff_side` → zone `counter_staff`; `shelf` → zone `shelf_main`.
  - All counter zones use `inertia: 3` and `loitering_time: 0`.
- After rendering, the agent compares the hash with the running config and restarts Frigate only if it changed.

## Agent inputs

| Source | Topic / endpoint | Used for |
| --- | --- | --- |
| Frigate MQTT | `frigate/events` (type new / update / end, with `before` / `after` objects incl. `id`, `camera`, `label`, `current_zones`, `entered_zones`, `start_time`, `end_time`, `score`) | Door crossings, staff tagging, after-hours motion |
| Frigate MQTT | `frigate/counter_customer/person`, `frigate/counter_staff/person` (live person count per zone) | Service, wait, unattended |
| Frigate MQTT | `frigate/stats`, `frigate/available` | Heartbeat fps, health |
| Frigate HTTP (127.0.0.1:5000) | `GET /api/<camera>/start/<ts>/end/<ts>/clip.mp4`, `GET /api/<camera>/latest.jpg` | Clips and snapshots |

Before coding, verify these topics and endpoints against the Frigate version pinned in the compose file and record any difference in `docs/decisions.md`.

## Algorithms (pure functions in the agent, 100% unit-tested with fixtures)

### Door crossing (F1)

For each Frigate track (`after.id`) keep the ordered list of door zones seen (`door_out`, `door_in`) from successive `current_zones` values, de-duplicated consecutively.

- Sequence contains `door_out` then later `door_in` → **entry** at the time `door_in` first appeared.
- Sequence contains `door_in` then later `door_out` → **exit**.
- A track can produce at most one entry and one exit; a second crossing in the same direction within 10 s of the first is ignored (AC-F1-2).
- Tracks with `label != person` or max `score < 0.6` are ignored.
- On Frigate `end`, flush the track; events are written to the outbox with `frigate_event_ids=[id]`.

### Staff tagging (F1-3)

- Accumulate per Frigate track the seconds spent with `counter_staff` in `current_zones`.
- When ≥ 600 s: mark the track staff; if that track produced an entry, send a corrective `entry` update with `is_staff=true` (same event id, upsert on the server).
- Day-level fallback: the server subtracts `expected_staff` from `visitors_in` (never below 0) when no staff tracks were tagged before 11:00 local.

### Counter state machine (F2)

Inputs: `c` = person count in `counter_customer`, `s` = person count in `counter_staff`, sampled on each MQTT message and re-evaluated every 1 s with last values.

- **Service**: when `c ≥ 1 and s ≥ 1` continuously for `service_min_s` → open service (start = when both first became ≥ 1). Close when `c == 0 or s == 0` for 5 s continuously. Emit on close.
- **Wait**: when `c ≥ 1 and s == 0` continuously for `wait_min_s` → open wait; close when `c == 0` or `s ≥ 1`. Emit on close with the full duration.
- **Unattended**: inside opening hours, when `s == 0` continuously for `unattended_min_s` → open; close when `s ≥ 1` or at closing time.
- Confidence = mean Frigate score of tracks in the zones during the event (fallback 0.8).

### After-hours motion

Outside opening hours, any new `person` track on any camera with score ≥ 0.7 → `after_hours_motion` event (one per 10 min max per camera).

## Outbox and upload

- SQLite at `/data/agent/outbox.db` (WAL mode). Table `outbox(id TEXT PK, kind TEXT, payload TEXT, created_at, attempts, next_try_at)`.
- Uploader loop: every 60 s or when ≥ 100 rows: POST batches of ≤ 500 to `/v1/edge/events`; delete on 200; exponential backoff (max 15 min) with jitter on failure. Never drop events; if the outbox exceeds 500 MB, drop oldest `after_hours_motion` first and log it.
- All timestamps are UTC from the box clock; NTP (chrony) must be running; heartbeat reports clock offset.

## Commands

Poll `GET /v1/edge/commands` every 30 s.

- `clip`: params `{camera, start, end}` → fetch Frigate clip → ffmpeg transcode to H.264 480p, CRF 28, `-preset veryfast`, max 20 s, no audio → PUT to `upload_url` → result `{object_key, duration_s, size_bytes}`. If footage is not available → status `unavailable`.
- `snapshot`: `latest.jpg` from the requested camera (default counter), resized to 960 px wide, JPEG q=70.
- `count_check_start` / `count_check_stop`: count entries on the door camera between start and stop; result `{agent_count}`.
- `update_agent`: `docker compose pull seetlu-agent && docker compose up -d seetlu-agent`; report the new version in the next heartbeat.
- `reboot`: `systemctl reboot` via a host helper.

## Heartbeat (every 5 min)

Fields per `Heartbeat` schema. `power_source` and `battery_pct` come from the mini-UPS if it exposes status over USB/GPIO; if not, report `mains` and null (record in decisions.md which UPS models expose status).

## Local LAN setup page (installer only)

Port 8080, LAN only, PIN-protected. Pages: network setup (Wi-Fi/4G status), camera discovery (ONVIF WS-Discovery), RTSP credential entry and test, live snapshot per camera. Zone drawing itself is done in the web app on the uploaded snapshot (F8).
