# 13 — Seetlu AI box (product spec)

Status: approved by the owner on 2026-11-27 (decisions D1–D6 below). Behaviour changes are in
`docs/01-product.md` (AC-F8-5 to AC-F8-8, AC-F10-4).

## 1. Product in one sentence

A small box that plugs into the shop's **existing** camera recorder (DVR/NVR) over the network, reads two
camera channels, and turns them into the evening WhatsApp report. No new cameras when the existing ones
see the door and the counter.

## 2. Why the change from "kit with cameras"

- Most target shops in Dakar already have 2–8 cameras on a DVR (installed against theft).
- Selling only the box removes the cameras, the PoE switch and most of the cabling: lower price, a
  30-minute install instead of half a day, no ladder work in most shops.
- The software already supports it: each camera has its own RTSP path, detect size and fps
  (`cameras.rtsp_sub_path`, `detect_width/height/fps`); credentials stay on the box (LAN setup page).

## 3. What the box connects to

### 3.1 Supported sources

| Source | How the box reads it | MVP |
| --- | --- | --- |
| Hikvision / HiLook DVR or NVR | RTSP, sub stream per channel | Yes |
| Dahua / Imou DVR or NVR | RTSP, sub stream per channel | Yes |
| Xiongmai "XMeye" generic DVR (most cheap Chinese recorders) | RTSP, sub stream per channel | Yes, after sample test |
| Standalone IP camera with RTSP (ONVIF) | RTSP, direct | Yes |
| Wi-Fi cloud cameras without RTSP (some Ezviz, Imou, Tapo models with RTSP disabled) | Not readable | No: offer an add-on camera |
| Analog cameras with no recorder, or a recorder with no network port | Not readable | No: offer an add-on camera |

RTSP path patterns (to confirm on the H1 samples):

| Brand | Sub stream of channel N |
| --- | --- |
| Hikvision | `/Streaming/Channels/N02` |
| Dahua | `/cam/realmonitor?channel=N&subtype=1` |
| Xiongmai | `/user=<u>&password=<p>&channel=N&stream=1.sdp?real_stream` |
| ONVIF camera | discovered with ONVIF `GetStreamUri` |

### 3.2 Minimum stream requirements (per camera used)

- Codec H.264 or H.265 (both decoded in hardware on RK3588).
- Sub stream at least 640×360 (D1 704×576 and 640×480 accepted; CIF 352×288 refused: too small for
  door counting).
- 5 fps or more on the sub stream; the installer page sets it to 5–8 fps on the recorder if allowed.
- Two channels needed: one sees the **door** (whole doorway, people cross it), one sees the **counter**
  (both the customer side and the staff side).
- The recorder keeps its own recording; the box never changes the main stream or the recorder's storage.

### 3.3 Camera angle check (decides "box only" vs "box + camera")

The installer app takes a live snapshot of every channel and checks, with a checklist on screen:

- Door: the doorway is fully in frame, a person crossing is at least 1/6 of the image height, no
  strong backlight that turns people into silhouettes all day.
- Counter: the counter edge is visible, a customer and the seller standing on each side are both visible.

If a channel fails, the shop gets one **add-on PoE camera** (sold with a small PoE injector) for that role.
Target: at least 60 % of pilot shops need no add-on camera (to measure, see section 10).

## 4. Hardware

### 4.1 Compute board (recommended: Orange Pi 5 Plus, 8 GB)

| Item | Spec | Why |
| --- | --- | --- |
| SoC | Rockchip RK3588, NPU 6 TOPS | Frigate `rknn` detector, already wired in the code |
| RAM | 8 GB | Frigate + agent + 2–4 streams with margin |
| Network | **2 × Ethernet** | One port to the DVR side, one to the internet side; works even when the DVR is not on the shop router |
| Storage | M.2 NVMe 128 GB (PCIe) | 7 days of motion clips for 2–4 sub streams (~40–60 GB) |
| Wi-Fi | M.2 E-key Wi-Fi module (optional) | Uplink through the shop Wi-Fi when no cable is possible |
| Power in | 5 V / 4 A USB-C | Fed by the mini-UPS |

The plain Orange Pi 5 (RK3588S, one Ethernet port, no Wi-Fi) stays possible as a cheaper variant when the
DVR and the internet router are on the same switch. The code is identical for both boards.

### 4.2 Bill of materials (per box)

| Part | Spec | Notes |
| --- | --- | --- |
| Board | Orange Pi 5 Plus 8 GB | see 4.1 |
| SSD | NVMe 2280, 128 GB, TLC | |
| Cooling | Copper heatsink + 5 V fan, PWM | Shops reach 35–40 °C; RK3588 throttles without a fan |
| Enclosure | Aluminium, vented, wall-mount ears, dust filter on the fan intake | Sits next to the DVR |
| Mini-UPS | DC UPS, 5 V USB-C PD + 12 V out, ≥ 2 h at 10 W, status over USB | Keeps box + 4G router up during cuts; status gives `battery_pct` in heartbeats |
| Uplink | 4G router (LTE cat4, Ethernet out, external antenna), or shop Wi-Fi/router | 4G SIM data: ~1–2 GB/month (events, heartbeats, clips on request) |
| Cables | 2 × Cat6 1 m, 1 × Cat6 5 m, USB-C power cable | |
| Label | Serial number + QR claim code on the box and the box | Read by the installer app |

Cost estimates are to be filled after the H1 sample order; the retail price is set from them (D4).

### 4.3 Front panel

- 1 status LED (green steady = OK, green blinking = starting, amber = no internet, red = no camera).
- 1 recessed button: hold 10 s = restart the agent and open the LAN setup page again for 30 min.
- No screen, no speaker, no microphone.

## 5. Software on the box (already built, small changes needed)

| Part | State |
| --- | --- |
| Frigate `stable-rk`, person only, no biometrics | Done |
| seetlu-agent: events, heartbeats, outbox, clips, OTA | Done |
| LAN setup page with RTSP credentials (host, port, user, password) | Done |
| Per-camera RTSP path and detect size from the cloud config | Done |
| **Brand presets** (Hikvision/Dahua/Xiongmai paths, channel number instead of a raw path) | To build |
| **Channel scan**: list channels of the recorder with a thumbnail, installer picks door and counter | To build |
| **Stream check**: resolution, codec, fps of the sub stream; refuse CIF; warn under 5 fps | To build (probe exists) |
| **ONVIF discovery** of recorders and cameras on the LAN | To build |
| Mini-UPS status probe (`power_source`, `battery_pct`) | To build when the UPS model is chosen |
| Status LED + button | To build (GPIO) |

Rules that do not change: no faces, no biometrics; video stays in the shop; the recorder password never
leaves the box; every clip access is audited.

## 6. Installation flow (target: 30 minutes, one installer, no ladder)

1. Installer scans the box QR in the installer app → kit claimed for the shop.
2. Box plugged: Ethernet to the DVR side (DVR port or shop switch), second port or Wi-Fi to the internet,
   power through the mini-UPS.
3. Box finds the recorder (ONVIF or the brand list); installer types the recorder login on the LAN page.
4. Box shows every channel as a thumbnail; installer picks **door** and **counter**.
5. Angle checklist (3.3). Fail → add-on camera, same flow.
6. Installer draws the door line and counter zones on the snapshot (existing screen, AC-F8-2).
7. 10-minute count check (existing, AC-F8-3), then the owner pairs the shop phone.

## 7. Network and security

- The box never opens a port to the internet; it only calls the Seetlu API over HTTPS.
- The LAN setup page is reachable only from the local network, with the PIN.
- The box only reads RTSP sub streams; it never writes recorder settings (D3).
- NVMe encrypted (LUKS, already in `provision.sh`).

## 8. Environment and reliability

- Operating temperature 0–45 °C ambient, fan on above 55 °C SoC.
- Hardware watchdog on; auto-restart after power return; outbox keeps 7 days of events offline.
- Power cut: the mini-UPS holds ≥ 2 h; past that, missing hours are reported (never zeros, rule 3).

## 9. What the owner buys (offer)

| Pack | Content |
| --- | --- |
| Seetlu Box | Box + mini-UPS + cables + install |
| Seetlu Box + 4G | Same + 4G router with SIM |
| Add-on camera | 1 PoE camera + injector + install, when an angle fails |

## 10. Field acceptance (pilot)

- Box works with at least 3 recorder brands found in pilot shops.
- Door count error ≤ 10 % on the recorder's sub stream (same test as `docs/field-validation.md`).
- Install ≤ 45 min median; share of shops with no add-on camera measured.
- No stream drop longer than 5 min per day caused by the box.

## 11. Decisions (approved 2026-11-27)

| # | Question | Decision |
| --- | --- | --- |
| D1 | Board: Orange Pi 5 Plus (2 Ethernet) or plain Orange Pi 5 (cheaper, 1 port) | Orange Pi 5 Plus 8 GB for the pilot |
| D2 | Recorder brands to support at launch | Hikvision, Dahua, Xiongmai |
| D3 | May the box change the recorder's sub stream settings (fps, resolution)? | No: the box only reads; the installer sets the sub stream on the recorder by hand |
| D4 | Target price of the box and of the add-on camera | Set after the H1 sample costs (human task) |
| D5 | Up to 4 channels (e.g. 2 doors) or exactly 2 in MVP | Exactly 2 channels (door + counter) in MVP |
| D6 | Uplink: 4G router always, or shop Wi-Fi when present | Shop internet first; 4G router sold as an option |
