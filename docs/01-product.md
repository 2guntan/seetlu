# 01 — Product spec (source of truth for behaviour)

## Promise

At the owner's chosen time (default 21:00 shop local time) the owner receives one WhatsApp message:
how many people came in, how many were served, how much money was recorded, whether the day looks
normal, and up to 3 short moments worth a look.

## Users and roles

| Role | Who | Scope |
| --- | --- | --- |
| owner | Pays for the account; 1–5 shops | Everything in their account |
| manager | Runs one or more shops | Assigned shops; clips only if owner allows |
| staff | Shop employee | Can log sales (quick log). No access to counts, reports or clips |
| installer | Seetlu partner technician | Kits assigned to them until activation |
| support | Seetlu ops staff | Health and config of all kits; clips only with an owner grant (24 h) |

Full permission matrix: `docs/09-security-privacy.md`.

## Glossary

- **Shop day**: from the shop's opening time to closing time in its local timezone.
- **Entry**: a non-staff track crossing the door line inward.
- **Service event**: customer and staff each present in their counter zones at the same time for at least `service_min_s` seconds.
- **Wait event**: customer in the customer zone more than `wait_min_s` with the staff zone empty.
- **Unattended**: staff zone empty more than `unattended_min_s` during opening hours.
- **Sale**: one record from mobile money, quick log, or POS webhook. **Cash declaration** is one record per day.
- **RPS (revenue per served customer)**: recorded money ÷ service events. Core health metric.

---

## F1 — Door count

Story: as an owner, I want customers in per hour, to compare days and staff busy hours.

- AC-F1-1: Inward crossings of the door line by a `person` track are counted as entries; outward as exits.
- AC-F1-2: A track crossing the line more than once within 10 s counts once (debounce).
- AC-F1-3: Staff exclusion: a track that accumulates ≥ 600 s in any `staff_side` zone during the day is tagged `staff`; its entries/exits are excluded from `visitors_in`. Because track IDs reset, the agent also subtracts `expected_staff` from the day's first entries if configured.
- AC-F1-4: Hourly buckets in shop local time are queryable via API.
- AC-F1-5 (field validation, not automated): daily in-count within ±5% of a manual count over a 2-hour window at install.

## F2 — Counter activity

Story: as an owner, I want to know how many customers were served, to compare with money recorded.

- AC-F2-1: A service event starts when both `customer_side` and `staff_side` zones of the counter camera contain a person for `service_min_s` (default 15, range 10–60) and ends when either is empty for 5 s.
- AC-F2-2: A wait event is created when `customer_side` is occupied ≥ `wait_min_s` (default 180) while `staff_side` is empty.
- AC-F2-3: An unattended event is created when `staff_side` is empty ≥ `unattended_min_s` (default 300) within opening hours.
- AC-F2-4: Every event stores start, end, duration, confidence, and the Frigate event id(s) needed to fetch a clip.

## F3 — Sales capture

Story: as an owner, I want sales collected without a POS.

- AC-F3-1: The shop phone app captures Wave and Orange Money incoming payment notifications (amount, time, reference) using configurable parsers and uploads them within 60 s when online.
- AC-F3-2: Offline captures are queued (Room DB) and uploaded on reconnect with original timestamps.
- AC-F3-3: `(source, external_ref)` is unique; duplicates are ignored (HTTP 200, `duplicate: true`).
- AC-F3-4: Quick log: a WhatsApp message from a registered staff/manager/owner phone matching `^\+\s?\d[\d\s.]*$` (e.g. `+2500`, `+ 2 500`) creates one `quick_log` sale; the bot replies with a ✓ and the day total.
- AC-F3-5: Cash declaration: at `cash_prompt_time` (default 20:30) the manager (or owner) receives a prompt; a numeric reply creates/replaces that day's `cash_declaration`.
- AC-F3-6: Unparseable notifications are stored raw (encrypted) for parser improvement and never block the queue.

## F4 — Daily report

Story: as an owner, I want one evening message that tells me if the day was normal.

- AC-F4-1: Sent at `report_time` (default 21:00) shop local time via the WhatsApp template `daily_report_fr`; delivered within 5 min on ≥ 99% of days (measured, not unit-tested).
- AC-F4-2: Content order: visitors in; served; money recorded (total XOF + split by source); verdict; unattended minutes; busiest hour; vs same weekday last week; up to 3 moments.
- AC-F4-3: Verdict is computed exactly as in `docs/06-report-engine.md` and is one of: `learning`, `normal`, `worth_a_look`, `large_gap`, `not_enough_activity`, `incomplete_data`.
- AC-F4-4: No verdict other than `learning` before 14 valid days exist.
- AC-F4-5: If any opening hour has no heartbeat, the report lists missing hours and the verdict is `incomplete_data` when more than 25% of opening hours are missing.
- AC-F4-6: Replies: `1`/`2`/`3` → link to that moment's clip; `photo` → live snapshot; `faux` → starts a correction flow (F9); `stop` → pause reports.

## F5 — Moments (clips)

- AC-F5-1: The report engine selects up to 3 moments in priority order: after-hours motion, longest unattended period during a busy hour, longest wait, the hour with the largest RPS drop.
- AC-F5-2: For each selected moment, the cloud queues a clip request; the edge agent fetches the clip from Frigate, transcodes to 480p H.264 ≤ 20 s, uploads it to object storage.
- AC-F5-3: Clip links are signed, require login, expire after 24 h; cloud clips expire after 7 days unless saved (max 30 saved per account).
- AC-F5-4: A clip request for a moment older than the edge buffer (7 days) returns `unavailable`.

## F6 — Alerts

- AC-F6-1: Only 4 alert types: `not_opened`, `unattended`, `after_hours_motion`, `kit_offline` (> 30 min).
- AC-F6-2: Max 3 alerts per shop per local day; quiet hours respected except `after_hours_motion`.
- AC-F6-3: Each alert type can be enabled/disabled and its threshold changed by the owner.

## F7 — Owner app (PWA)

- AC-F7-1: Screens: Today, History (calendar coloured by verdict), Day detail, Moments, Sales log, Shops, Users, Alerts, Settings, Audit log.
- AC-F7-2: Login by phone number + one-time code sent over WhatsApp (SMS fallback).
- AC-F7-3: Works on a 3G connection: initial load ≤ 300 KB gzipped JS; data cached offline (last 30 days).
- AC-F7-4: UI in French by default; Wolof and English selectable.

## F8 — Installer flow

- AC-F8-1: Installer registers a kit by scanning its QR code (kit serial + claim token).
- AC-F8-2: Installer draws the door line and the counter zones on a live snapshot per camera; the agent receives them as config.
- AC-F8-3: Count check: installer starts a 30-min check, taps +1 for each real entry; the app compares with the agent's count. Activation requires error ≤ 10% on ≥ 20 entries (or installer override with a reason, logged).
- AC-F8-4: Kit cannot be activated without a CDP declaration reference on the shop record.
- AC-F8-5: The box reads the shop's existing recorder (Hikvision, Dahua or Xiongmai DVR/NVR) or an RTSP/ONVIF camera: the installer picks the brand, enters the recorder login on the LAN setup page and picks a channel number; the box builds the sub-stream RTSP path from the brand preset. A raw RTSP path stays possible ("other").
- AC-F8-6: The LAN setup page lists the recorder's channels with a thumbnail each; the installer assigns exactly one `door` and one `counter` channel.
- AC-F8-7: Stream check per assigned channel: codec H.264/H.265 and sub-stream resolution of at least 640×360 are required (activation blocked otherwise); under 5 fps shows a warning. The box never changes recorder settings.
- AC-F8-8: Angle checklist on each snapshot (door fully in frame and a person at least 1/6 of the image height; counter with both sides visible); a failed item records "add-on camera needed" on the kit and blocks activation for that role until a camera passes.

## F9 — Corrections and confidence

- AC-F9-1: Owner/manager can mark a day's visitors or served as wrong with an approximate true value; stored in `day_corrections`, shown in history, and excluded from baselines.
- AC-F9-2: Each metric in a report has a confidence level `high|medium|low` from the rules in `docs/06-report-engine.md`.

## F10 — Kit health

- AC-F10-1: Edge agent sends a heartbeat every 5 min (power source, battery %, storage %, CPU temp, fps per camera, network type, agent version, frigate version).
- AC-F10-2: Support console lists kits by status `ok|degraded|offline` and shows the last 7 days of heartbeats.
- AC-F10-3: OTA: the cloud sets a target agent version per kit or per cohort; the agent updates itself (docker compose pull/up) and reports the result.
- AC-F10-4: Box front panel: one status LED (green steady ok, green blinking starting, amber no internet, red no camera stream) and one recessed button (hold 10 s: restart the agent and reopen the LAN setup page for 30 min).

## Out of scope (never build)

Face recognition or matching; age/gender/emotion/clothing analysis; heatmaps; staff scores or leaderboards;
continuous live streaming to the cloud; PTZ control; voice intercom; signage; music.
