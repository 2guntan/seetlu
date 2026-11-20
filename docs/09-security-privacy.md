# 09 — Security and privacy

## Legal frame (Senegal)

Law No. 2008-12 on personal data; the CDP's 2015 deliberation on video surveillance puts it under the normal declaration regime, with a stricter regime for data hosted abroad. The owner is the data controller; Seetlu is the processor. Product rules below are mandatory.

## Product rules

1. No biometrics (see CLAUDE.md rule 1). Frigate face recognition, LPR, semantic search and GenAI are disabled in every rendered config and a test asserts it.
2. Tracks are anonymous Frigate ids; never stored beyond the event's `frigate_event_ids`.
3. Edge recordings: 7 days, motion only, encrypted at rest (LUKS on `/data` with a key derived from the device token sealed on the box).
4. Cloud clips: 7 days unless saved (max 30 per account). Nightly job deletes expired objects and rows.
5. Activation blocked without `shops.cdp_declaration_ref`.
6. Hosting: production in Senegal (provider TBD); no clip storage outside the production region.

## Permission matrix (enforce in one `authorize(user, action, resource)` function with exhaustive tests)

| Action | owner | manager | staff | installer | support |
| --- | --- | --- | --- | --- | --- |
| report.view / receive | ✓ | assigned shops (if receives_report) | ✗ | ✗ | aggregated only |
| counts.view | ✓ | assigned | ✗ | during install | ✓ |
| clip.view / snapshot | ✓ | if account.clip_access_for_managers | ✗ | calibration snapshot until activation | only with active support_grant |
| sale.quick_log | ✓ | ✓ | ✓ | ✗ | ✗ |
| sale.cash_declaration | ✓ | ✓ | ✗ | ✗ | ✗ |
| zones.edit | ✓ | ✗ | ✗ | until activation | ✓ (audited) |
| users.manage, alerts.manage | ✓ | ✗ | ✗ | ✗ | ✗ |
| correction.create | ✓ | ✓ | ✗ | ✗ | ✓ (audited) |
| kit.command (reboot, update) | ✗ | ✗ | ✗ | own kits until activation | ✓ |

## Technical security

- JWT access 15 min, refresh 30 days (rotating, revocable). OTP: 6 digits, 5 min, 5 attempts, rate-limit 3 requests / 15 min per phone and per IP.
- Device tokens: 32-byte random, stored hashed (argon2id); rotate on re-registration.
- All traffic TLS 1.2+. Presigned URLs: PUT 10 min, GET 15 min.
- Raw notifications encrypted client-side with a server RSA/X25519 public key; private key only in the worker.
- Audit log for: clip.view, clip.save, snapshot.request, zone.update, correction.create, support.access, user.invite, kit.activate, count_check.override.
- Backups: Postgres daily full + WAL, 30-day retention; restore drill script in `ops/`.
- Dependency scanning and container image scanning in CI.
