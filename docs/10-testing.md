# 10 — Testing without hardware

Everything must be buildable and testable on a laptop with no camera, no edge box, no WhatsApp account and no phone.

## fake-frigate (`edge/fake-frigate/`)

A small Python service that publishes Frigate-shaped MQTT messages to mosquitto, driven by **scenario files** (YAML), and serves the two Frigate HTTP endpoints the agent uses (returns a bundled sample MP4 / JPEG).

Scenario format:
```yaml
shop_timezone: Africa/Dakar
date: 2026-11-20
opening: ["08:00", "21:00"]
actors:
  - {kind: staff, id: s1, arrive: "07:55", leave: "21:05", breaks: [["13:00","13:40"]]}
  - {kind: customers, count: 140, window: ["08:00","21:00"], peak: ["18:00","20:00"],
     served_ratio: 0.8, service_s: [20, 120], wait_ratio: 0.05}
  - {kind: after_hours, at: "23:14"}
```
The generator turns actors into tracks with zone sequences (`door_out → door_in → counter_customer → … → door_out`) and per-zone person counts, then publishes them at accelerated time (`--speed 600` = 10 min per second).

Ship at least these scenarios with expected outputs (`expected.json`): `normal-day`, `busy-day`, `staff-absent-afternoon`, `power-cut-14-16` (no messages + no heartbeats), `after-hours-motion`, `crowded-door` (groups of 3 entering together), `re-entry-flicker` (track oscillating on the line).

## Test layers

| Layer | Tool | What |
| --- | --- | --- |
| Agent unit | pytest | geometry, door sequences, counter state machine, staff tagging, outbox backoff — table-driven with fixtures |
| Agent integration | pytest + docker compose (mosquitto, fake-frigate, mock API) | each scenario → events uploaded == expected.json (±0 for door counts in synthetic scenarios) |
| Domain unit | pytest + hypothesis | metrics, baseline, verdict boundaries (z = 2, 4), moments priority, alert caps, quiet hours, money never float |
| API | pytest + httpx + testcontainers (timescaledb, redis, minio) | every endpoint, auth matrix (`authorize` exhaustive test), idempotency, problem+json |
| WhatsApp | pytest with MockProvider | template params rendering, inbound grammar table, signature verification |
| Web | vitest + Testing Library; Playwright for 5 journeys | login, today, day detail + play moment, installer full flow, settings |
| Android | JUnit5 | parser rules against `notifications/` fixtures; queue/upload with MockWebServer |
| End-to-end | `make e2e` | seed account → run `normal-day` scenario through real agent → report computed → mock WhatsApp message matches golden file |

## Seed data (`make seed`)

1 owner, 1 manager, 1 staff, 1 installer, 1 support user; 2 shops (boutique Dakar, supérette Abidjan); 30 days of generated events and sales including 2 `worth_a_look` days and 1 `large_gap` day; 1 day with missing hours. Login codes in dev are always `000000`.

## Field validation (pilot, manual — not CI)

Protocol in `docs/field-validation.md` (create it in M10): 2-hour manual tally at install, weekly 30-min audits in 5 shops, labelled clip sets for service events, results logged per shop.
