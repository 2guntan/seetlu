# 06 — Report engine (verdict, baselines, moments, alerts)

All logic in `backend/seetlu/domain/` as pure functions taking plain data and returning plain data.
Workers only load data, call these functions, and persist results.

## Daily metrics (shop local day D)

| Metric | Definition |
| --- | --- |
| visitors_in | count(entry where not is_staff) − staff fallback (see 05), floor 0 |
| served | count(service events started on D within opening hours) |
| waits | count(wait events) |
| unattended_min | sum(duration of unattended events) / 60, rounded |
| busiest_hour | local hour with most entries (ties → earliest) |
| sales_count | count(sales on D, source ≠ cash_declaration, not voided) |
| sales_xof | sum(amount of mobile money + quick_log + pos) **+ cash_declared_xof if present and no quick_log rows exist that day**; if quick_log rows exist, the cash declaration is shown but not added (avoids double counting) |
| sales_by_source | sum per source |
| rps_xof | sales_xof / served, null if served = 0 |
| missing_hours | opening hours (local) with no heartbeat at all |

## Valid days and baseline

A day is **valid** if: shop active; missing_hours ≤ 25% of opening hours; served ≥ 10; sales_xof > 0; no `day_corrections` row for `served`.

Baseline for day D = valid days in the 56 days before D (max 28 most recent):
`rps_median` = median of rps_xof; `rps_mad` = median absolute deviation, floored at 10% of `rps_median`.
`n_days` = number of valid days used.

## Verdict (evaluate in this order; first match wins)

1. `incomplete_data` — missing_hours > 25% of opening hours.
2. `not_enough_activity` — served < 10.
3. `learning` — baseline n_days < 14.
4. Compute `z = (rps_median − rps_xof) / rps_mad` (positive = less money per served customer than usual).
   - `normal` if z ≤ 2
   - `worth_a_look` if 2 < z ≤ 4
   - `large_gap` if z > 4
   - If `sales_xof == 0` and served ≥ 10 → `large_gap`.

A day with *more* money than usual (z < 0) is always `normal`.

## Confidence per metric

| Metric | high | medium | low |
| --- | --- | --- | --- |
| visitors_in | last count check passed ≤ 30 days ago and door fps ≥ 4 all day | fps ≥ 2 all day | otherwise |
| served | counter fps ≥ 4 all day and mean event confidence ≥ 0.75 | mean confidence ≥ 0.6 | otherwise |
| sales | phone app seen in last 2 h before report and parser_version current | phone seen today | phone not seen today |

## Comparison with last week

Same weekday 7 days before: deltas for visitors_in, served, sales_xof (absolute and %). Omitted if that day was not valid.

## Moments (max 3, in this priority)

1. Each `after_hours_motion` event (latest first).
2. Longest `unattended` event that overlaps the busiest hour or any hour with ≥ 3 entries.
3. Longest `wait` event.
4. Hour with the largest drop in hourly RPS vs the shop's median hourly RPS (needs ≥ 3 services in that hour); moment = 20 s around the longest service event of that hour.

Clip window for a moment = event start − 5 s to start + 15 s (≤ 20 s). Clip commands are queued at report time but links are only generated when the owner asks (`1`, `2`, `3`).

## Fixed wording (French, MVP)

| Verdict | Text |
| --- | --- |
| learning | « Seetlu apprend encore votre boutique (jour {n}/14). » |
| normal | « Journée normale. » |
| worth_a_look | « À regarder : moins d'argent que d'habitude pour le nombre de clients servis. » |
| large_gap | « Écart important : beaucoup de clients servis, peu d'argent enregistré. » |
| not_enough_activity | « Peu d'activité aujourd'hui, pas de verdict. » |
| incomplete_data | « Données incomplètes (heures manquantes : {hours}). Pas de verdict. » |

Never use the words « vol », « voleur », « fraude » or any staff name in automatic messages.

## Alerts (evaluated every minute by beat)

| Type | Trigger | Default |
| --- | --- | --- |
| not_opened | no entry and no staff presence by opening time + grace | grace 30 min |
| unattended | open unattended event longer than threshold during opening hours | 10 min |
| after_hours_motion | event received | on |
| kit_offline | no heartbeat for 30 min during opening hours | on |

Cap 3 per shop per local day (`alerts_sent`); quiet hours suppress all except `after_hours_motion`. One alert per event id.

## Scheduling

- Beat runs `schedule_due_reports` every minute: for each active shop whose local time just passed `report_time` and with no `sent_at` for today → enqueue `compute_and_send_daily_report(shop_id, date)`.
- `cash_prompt` same pattern at `cash_prompt_time`.
- Late events (arriving after the report) trigger `recompute_report` but do not resend; the app shows the recomputed values with a "mis à jour" badge.
