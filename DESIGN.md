---
# gstack: design-md-format=spec
name: Seetlu
description: A shop board painted for the sun. Dark ink on warm paper, one strong blue, sun yellow for money, calm verdicts that never accuse.
colors:
  paper: "#F4F2EC"
  surface: "#FFFFFF"
  surface-sunk: "#ECE9E1"
  text: "#14161A"
  text-muted: "#545966"
  line: "#D6D2C7"
  primary: "#1D45A6"
  primary-hover: "#163885"
  on-primary: "#FFFFFF"
  accent: "#FFC629"
  on-accent: "#14161A"
  ok-bg: "#DCEFE0"
  ok-text: "#135C2E"
  look-bg: "#FFEFBF"
  look-text: "#6E4300"
  gap-bg: "#FFD9BF"
  gap-text: "#863100"
  neutral-bg: "#E6E3DB"
  neutral-text: "#454A54"
  missing: "#8D8A82"
  error: "#B42318"
  chart-entries: "#7FA2E8"
  chart-served: "#1D45A6"
  chart-money: "#E0A100"
typography:
  display:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 750
    fontSize: clamp(2.25rem, 9vw, 3rem)
    letterSpacing: -0.01em
    fontFeature: tnum
  h1:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 750
    fontSize: 1.75rem
    lineHeight: 1.15
  h2:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 700
    fontSize: 1.25rem
    lineHeight: 1.2
  body:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 430
    fontSize: 1.0625rem
    lineHeight: 1.5
  label:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 600
    fontSize: 0.875rem
    letterSpacing: 0
  number:
    fontFamily: Atkinson Hyperlegible Next Variable
    fontWeight: 700
    fontSize: 1.5rem
    fontFeature: tnum
rounded:
  sm: 6px
  md: 10px
  lg: 14px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  3xl: 48px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    minHeight: 48px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-ghost:
    backgroundColor: transparent
    textColor: "{colors.primary}"
    borderColor: "{colors.line}"
    rounded: "{rounded.md}"
  input:
    borderColor: "{colors.line}"
    rounded: "{rounded.sm}"
    minHeight: 48px
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    rounded: "{rounded.lg}"
  badge-normal:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.ok-text}"
    rounded: "{rounded.sm}"
  badge-worth-a-look:
    backgroundColor: "{colors.look-bg}"
    textColor: "{colors.look-text}"
    rounded: "{rounded.sm}"
  badge-large-gap:
    backgroundColor: "{colors.gap-bg}"
    textColor: "{colors.gap-text}"
    rounded: "{rounded.sm}"
  nav-link:
    textColor: "{colors.text-muted}"
  nav-link-active:
    textColor: "{colors.primary}"
---

# Seetlu

## Overview

**Creative North Star:** a shop board painted for the sun. A Dakar shop owner looks at it for three seconds, at the counter, often outside. The money figure and the verdict have to be readable at arm's length in full light.

**Product context:**
- **Product:** a PWA for small-shop owners in Senegal, plus installer and support screens.
- **Users and conditions:** low-end Android phones, 3G, a glance in daylight.
- **Languages:** French by default, then Wolof and English.
- **Main question it answers:** did today's activity match today's money?

**Mode per surface:**
- **Operate:** today, day detail, history, sales, settings, installer and support.
- No Persuade surface: there is no marketing page in the app.

**Reference sites:** none. Research was skipped on purpose, because the use scene (sun, 3G, few words) decides more than what SaaS dashboards do.

**Key characteristics:**
- One big number per shop: today's money, in tabular figures with a sun-yellow underline.
- Verdicts are calm coloured labels, never red.
- A missing hour is hatched grey. It never looks like zero.
- Large touch targets (48px) and 17px body text.
- Few words. The interface leans on numbers and position.

## Colors

**Strategy:** Committed. One blue owns interaction (links, primary buttons, active tab). Sun yellow (`accent`) is kept for money only: the underline of the day's total and the money bars. Neutrals are warm, taken from paper and painted walls rather than cold grey.

**Light or dark:** light by default, because of the use scene: a counter in daylight, often in direct sun. A dark scheme is provided under `prefers-color-scheme: dark` for evening reading of the day. In dark mode, surfaces step up in lightness (paper → surface → sunk) so the hierarchy holds instead of being a plain inversion.

**Verdict palette (rule 4, never accuse):**
- `normal` uses green.
- `worth_a_look` uses amber.
- `large_gap` uses deep orange.
- Days without a verdict use neutral.

Red (`error`) is kept for system errors only, such as a failed request. A large gap is not a fault, so it never gets the error colour. Every verdict always carries its fixed text from `docs/06-report-engine.md`, so colour is never the only signal.

Contrast: `text` on `paper` is about 16:1, and `text-muted` on `surface` is about 7:1. Each verdict text colour on its background is at least 7:1, to survive sunlight glare.

## Typography

There is one family: **Atkinson Hyperlegible Next**, a variable font with weights 200 to 800.
- **Origin:** designed by the Braille Institute so that easily confused letters and figures stay distinct (1/l/I, 0/O, 5/S, 6/b). That matters for low vision, glare, and readers more at ease with numbers than with text.
- **Licence:** OFL-1.1, verified on npm as `@fontsource-variable/atkinson-hyperlegible-next@5.3.0`.
- **Loading:** self-hosted through the npm package. The latin subset is 34 KB as woff2 and loads with `font-display: swap`. Workbox precaches it, so it works offline.
- **Wolof:** ë, ñ, à and é are in the latin range.
- **Figures:** amounts and counts use `font-variant-numeric: tabular-nums`. The `tnum` feature is present in the font, so columns of numbers line up.

Scale: display 36–48px, h1 28px, h2 20px, number 24px, body 17px, label 14px. Two adjacent levels always differ by at least 1.25×. Labels are sentence case and never in tracked capitals, because tracked capitals read badly in Wolof and in glare.

## Layout

- Single column, maximum width 760px, side gutter 16px. The bottom navigation is fixed.
- Stats sit in a grid of `minmax(140px, 1fr)`, so there are 2 per row on a 360px phone.
- Spacing uses a 4px base. Inside a card the gap is 12–16px, between sections 24–32px.
- The day's money gets a full-width line of its own above the other stats: this is the one deliberate break in the grid.

## Elevation & Depth

- Flat. Depth comes from the step from paper to surface and from 1px `line` borders.
- Only the fixed bottom navigation carries a shadow, a small offset of `0 -1px 0`.
- No glow, no blur, no gradient.

## Shapes

Radii:
- `sm` 6px: badges and inputs.
- `md` 10px: buttons and stat tiles.
- `lg` 14px: cards.

A stat inside a card uses `md`, which is smaller than the card's `lg`, so a nested shape never matches its parent. No pill buttons, no bubbly radius.

## Components

| Component | Rules |
|---|---|
| **Button** (`button`, `.btn`) | Primary blue, at least 48px high, weight 650. Hover: `primary-hover`. Focus-visible: a 3px blue outline offset by 2px, which stays visible in sunlight. Disabled: 45% opacity, default cursor. |
| **Ghost button** (`.ghost`) | Transparent background, blue text, `line` border. |
| **Big button** (`.big`) | Shop-phone amount entry: full width, display-size text. |
| **Card** (`.card`) | `surface` background, `line` border, radius `lg`, 16px padding. Never a card inside a card. |
| **Stat** (`.stat`) | `surface-sunk` tile: label on top (label style, muted), value below (number style, tabular). A missing value shows `—` with its reason, never 0. |
| **Hero stat** (`.stat.hero`) | Today's money: display size, full grid row, 4px `accent` underline under the figure. |
| **Badge** (`.badge.v-*`) | Verdict label, radius `sm`, weight 650. The text always comes from i18n keys. |
| **Banner** (`.banner`) | Neutral information (missing hours, offline): `look-bg` with a 1px darker border. It is a notice, not an alarm. |
| **Tabs** (`nav.tabs`) | Fixed at the bottom, 56px high, active tab in blue with weight 700 and a 3px top bar. |
| **Input** (`input`, `select`, `textarea`) | At least 48px high, `line` border; focus shows a blue border plus the outline. |
| **List** (`ul.list.surface`) | One surface with rows split by `line` borders. Used for moments, people and the access log instead of a stack of cards. |
| **Scrolling table** (`.scroll-x`) | A table scrolls inside its own box; the page never scrolls sideways. |
| **Calendar** (`.calendar`) | Day cells tinted with the verdict colours. A day without a report has a dashed border and no tint. |
| **Hourly bars** | Three series using the `chart-*` tokens. A missing hour is hatched in `missing`, never drawn as a zero-height bar. |

Every component has its loading (`role=status`), error (`role=alert`, colour `error`) and empty state (muted sentence from i18n).

## Do's and Don'ts

- **Do:** use the tokens (`var(--…)`) for every colour in CSS and SVG. No hex values in components.
- **Do:** tabular figures for every amount and count.
- **Do:** at least 48px for anything a finger touches.
- **Do:** missing data shown as hatching or `—` plus the i18n reason.
- **Do:** check every screen at 360px wide.
- **Don't:** red for a verdict, or any colour that reads as a fault for a business gap.
- **Don't:** a new verdict text or any hard-coded user-facing string.
- **Don't:** shadows, gradients, glow or glass effects.
- **Don't:** tracked capitals, icons in coloured circles, or nested cards.
- **Don't:** a UI library. The initial JS budget is 300 KB gzipped (AC-F7-3).

## Motion

- **Approach:** minimal-functional.
- **Easing:** enter ease-out, exit ease-out, move ease-in-out.
- **Duration:**
  - micro (button press, focus): 100ms;
  - short (tab or colour change): 150ms.
- **Reduced motion:** everything is off under `prefers-reduced-motion: reduce`.
- **The one authored moment:** none. On a 3G phone in the sun, motion costs more than it gives.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-11-21 | Initial design system created | Created by /design-consultation from product context (Dakar shops, sun, 3G, fr/wo/en); research skipped, outside voices skipped (user authorized end to end without questions). |
| 2026-11-21 | Atkinson Hyperlegible Next as the only family | Built for legibility of confusable glyphs; covers Wolof; has `tnum`; 34 KB latin subset, self-hosted for offline use. |
| 2026-11-21 | No red in verdicts | Rule 4 (never accuse): large_gap uses deep orange; red kept for system errors. |
| 2026-11-21 | Light by default, dark via prefers-color-scheme | The use scene is daylight at the counter; dark only for evening reading. |
| 2026-11-21 | Lists instead of stacked cards; tabs capped at five | /design-review: stacked cards and six tabs failed at 375px |
