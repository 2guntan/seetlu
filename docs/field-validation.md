# Field validation protocol (pilot, manual — not CI)

Purpose: check on real shops what the automated tests cannot — door counts (AC-F1-5), service events
(F2), report delivery (AC-F4-1) and sales capture (F3/M9 parser rules) — before scaling past the 20
pilot shops (docs/12 H10). Owners must have signed the contract and the signage must be up (docs/12 H9).
Results go in the shared pilot log (one row per shop per check, template at the end).

## 1. At install — 2-hour manual tally (AC-F1-5)

1. After the 30-minute count check of the installer app passed (AC-F8-3: ≥ 20 entries, ≤ 10 % error),
   stay **2 hours** at a busy time (usually 17:00–19:00).
2. Count every person entering on a tally counter (staff included), note the start and end time to the minute.
3. Compare with the agent: support console → kit → events, `entry` count in the same window
   (staff included), or the shop's hourly chart for whole hours.
4. Pass = within **±5 %**. Fail → adjust the door line in the installer app (zones), repeat the 30-min
   check, then the 2-hour tally on another day. Two fails → camera position is wrong: move it.

## 2. Weekly audits — 30 minutes, 5 shops

Every week pick 5 active shops (rotate; always include any shop with an owner complaint).
For each: 30-minute tally at the door as above (pass = ±10 % on a short window), plus:

- the last 7 reports arrived (owner confirms, or the message log in the support console);
- missing hours in those reports match real outages (kit offline, power cuts) — never shown as zero (rule 3);
- verdicts used only the fixed wording of docs/06 (rule 4) and the owner understood them;
- the shop phone health screen: notification access on, last upload < 1 h, rules version current.

## 3. Service events — labelled clip sets (F2)

1. With the owner's written consent (docs/12 H2), request 20 clips per shop over 2 weeks from the
   moments the report selected (`wait`, `unattended`, `service`) and 10 random 20-s clips of the counter.
2. Two people label each clip independently: was there a customer waiting with nobody at the counter
   (`wait`)? was the counter unattended ≥ 5 min (`unattended`)? Disagreements → a third person decides.
3. Report precision (events confirmed / events flagged) and, from the random clips, missed events.
   Target for the pilot: precision ≥ 80 % for `wait` and `unattended`. Below → tune `wait_min_s` /
   `unattended_min_s` or the counter zones for that shop; log the change.
4. Clips used for labelling are not saved (they expire after 7 days); every view is in the audit log.

## 4. Sales capture (M9 rules)

For 3 days per shop, the owner keeps the Wave / Orange Money history screen. Compare the day's
transactions with the sales list in the app: every incoming payment must be there once (no duplicate),
with the right amount. Unparsed counts > 0 → copy the notification text (with consent, numbers masked)
into `android/shop-phone/src/test/resources/notifications/` as a new case, update `rules.json`, release.

## 5. Report delivery (AC-F4-1)

Weekly: from the message log, share of days where the report was delivered within 5 min of
`report_time`. Target ≥ 99 %. Misses → incident note (ops/runbooks/incident.md).

## Pilot log template

| Date | Shop | Check | Window | Manual | Agent | Error % | Pass | Notes / action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-12-02 | Boutique Awa | install tally | 17:00–19:00 | 143 | 139 | 2.8 | ✓ | |
