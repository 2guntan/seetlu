# 08 — Client apps

## Web app (React PWA) — `web/`

One app, three areas by role: **owner/manager**, **installer**, **support**.

### Owner / manager screens

| Route | Content |
| --- | --- |
| `/login` | Phone (+221 default, +225 allowed) → code from WhatsApp |
| `/` Today | Per shop card: visitors so far, served, money recorded, current counter status (occupied / empty since …), last heartbeat. Pull to refresh |
| `/history` | Month calendar, each day coloured by verdict (normal green, worth_a_look amber, large_gap red, others grey); tap → day |
| `/day/:shop/:date` | Report numbers with confidence marks, hourly bars (entries, served, money), moments list with play buttons, sales list, "corriger" button |
| `/moments` | Clips list (7-day + saved), save/unsave, audit-logged playback |
| `/sales` | Sales log by day, filter by source, add quick log, void own entry |
| `/shops/:id/settings` | Opening hours, report time, cash prompt time, thresholds (with plain-language help), alerts, users (invite by phone, role, clip access toggle), pair shop phone (6-digit code) |
| `/audit` | Who viewed which clip, support access |

Charts: lightweight SVG components (no heavy chart library). Bundle budget 300 KB gzipped (AC-F7-3).

### Installer screens

`/install` → claim kit (QR scan via camera; manual serial entry fallback) → pick or create shop (address, GPS from phone, category, hours, CDP declaration ref) → per camera: fetch snapshot (edge command) → draw door line (2 points + choose inside side) or polygons (customer side, staff side) on the snapshot → save → count check (big +1 button, timer, result) → activate.

### Support console

`/support/kits` table with health filters, last heartbeat, versions, queue depth; kit page with 7-day heartbeat sparklines, command buttons (snapshot only with an active owner grant, reboot, set target version), config viewer.

## Shop phone app (Android, Kotlin) — `android/shop-phone/`

Purpose: capture mobile-money payments received by the shop and offer a quick-log pad. No video, no reports.

- Pairing: enter the 6-digit code from the owner app → device token stored in EncryptedSharedPreferences.
- `NotificationListenerService` listening to the Wave and Orange Money app packages and to the SMS app (Orange Money confirmations often arrive by SMS). Package names and parsing rules are **not hard-coded**: they come from `GET /v1/phone/parsers` (JSON: `[{id, package, match_regex, amount_group, ref_group, direction: "in"}]`), cached locally, versioned.
- Only notifications that match an "incoming payment" rule become sales. Everything else from those packages is ignored, except notifications that look like payments but fail parsing → `unparsed` (raw text, encrypted with the server public key before upload).
- Room DB queue; WorkManager uploads every 15 min and immediately on capture when online.
- Quick-log screen: big amount pad, `Enregistrer`, last 10 entries, day total.
- Health screen: permission status (notification access, battery optimisation exemption), last upload, parser version. Show a persistent banner if notification access is revoked.
- Start parsers with placeholder rules plus unit tests on **sample notification texts that a human must collect** (see 12-human-tasks.md); keep the fixtures in `android/shop-phone/src/test/resources/notifications/`.
