---
version: alpha
name: tracced
description: >
  Restrained engineering for on-chain facts. Light working surfaces, dark navy for the brand and the chart, one mint
  accent, thin borders instead of shadows, numbers in a monospaced face. Every colour beyond mint carries a meaning.
colors:
  primary: "#A7F3D0"          # mint: the one accent (primary button, active toggle, rising candles, the live dot)
  primary-border: "#86EFAC"
  primary-strong: "#34D399"   # mint on dark: focus on navy inputs, range borders
  primary-ink: "#047857"      # mint as text on white (links in toasts)
  on-primary: "#0F172A"
  ink: "#0F172A"              # text
  muted: "#64748B"            # secondary text, labels
  faint: "#94A3B8"            # icons at rest, axis text on dark
  line: "#E2E8F0"             # borders, dividers
  line-strong: "#CBD5E1"      # hover borders
  surface: "#FFFFFF"          # cards, tables, menus
  background: "#F8FAFC"       # the page under the cards
  hover: "#F1F5F9"            # hover and pressed fill of ghost controls
  sage: "#D1FAE5"             # selected row, PnL bar, focus ring on light inputs
  navy: "#090D16"             # header, hero, chart
  navy-line: "#1E293B"        # borders on navy
  gain: "#059669"             # profit, buys
  loss: "#DC2626"             # loss, sells, errors, destructive actions
  loss-fill: "#FEE2E2"        # negative PnL bar
  saved: "#D97706"            # a wallet in your lists (the star)
  saved-hover: "#B45309"
  saved-fill: "#FEF3C7"
  warn: "#92400E"             # sniper, bot-like, fresh; partial data
  warn-fill: "#FFFBEB"
  warn-line: "#FDE68A"
  repeat: "#5B21B6"           # seen before in your other analyses
  repeat-fill: "#F5F3FF"
  repeat-line: "#C4B5FD"
  identity: "#1E3A8A"         # publicly known wallet
  identity-fill: "#EFF6FF"
  identity-line: "#BFDBFE"
  danger-tag: "#7F1D1D"       # the token's creator
  danger-fill: "#FEF2F2"
  danger-line: "#FCA5A5"
  transfer: "#9A3412"         # bundle, transfer-in
  transfer-fill: "#FFF7ED"
  transfer-line: "#FDBA74"
typography:
  display-hero:
    fontFamily: Geist
    fontSize: 64px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
  body-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
  label-md:
    fontFamily: Geist
    fontSize: 12.5px
    fontWeight: 500
    lineHeight: 1.3
  label-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.3
  caption:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.3
  table-head:
    fontFamily: Geist
    fontSize: 11.5px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0.05em
  data-md:
    fontFamily: Geist Mono
    fontSize: 12.5px
    fontWeight: 400
    lineHeight: 1.3
    fontFeature: '"tnum" 1'
  data-strong:
    fontFamily: Geist Mono
    fontSize: 13.5px
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: '"tnum" 1'
  data-hero:
    fontFamily: Geist Mono
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: -0.02em
    fontFeature: '"tnum" 1'
  tag:
    fontFamily: Geist Mono
    fontSize: 10.5px
    fontWeight: 500
    lineHeight: 1.5
rounded:
  xs: 4px       # labels on the chart
  sm: 6px       # icon buttons, menu items, icon tags
  md: 8px       # buttons, inputs, menus, the table frame
  lg: 10px      # cards, popovers, toasts
  xl: 12px      # sheets
  full: 999px   # chips, pills, tags, list tabs
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  page-gutter: 24px
  page-gutter-phone: 16px
  card-padding: 20px
  page-max: 1280px
  page-max-result: 1600px
components:
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: 34px
    padding: 7px 14px
  button-hover:
    backgroundColor: "{colors.background}"
  button-pressed:
    backgroundColor: "{colors.hover}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    height: 34px
  button-primary-hover:
    backgroundColor: "#99EDC6"
  button-ghost:
    backgroundColor: transparent
    textColor: "{colors.muted}"
  button-ghost-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.ink}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: 34px
    padding: 7px 10px
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.full}"
    height: 24px
    padding: 0 9px
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: 20px 22px
  menu:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 4px
  toast:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: 10px 16px
  wallet-card:
    backgroundColor: "{colors.surface}"
    width: 440px
  star:
    textColor: "{colors.saved}"
    size: 22px
  chart:
    backgroundColor: "{colors.navy}"
    rounded: "{rounded.lg}"
    height: 400px
---

# tracced design system

This file is the source of truth for how tracced looks and moves. Every change to the interface follows it, whoever
makes the change. When a design skill or a general rule disagrees with this file, this file wins. When a change needs
something this file does not cover, settle it with the owner and then add it here in the same commit.

## Overview

tracced shows on-chain facts: who bought a token, when, and what the wallet did next. The look follows the job:
restrained, exact, quiet. It is closer to an engineering instrument than to a trading terminal. The brand and the
chart sit on dark navy. The working surfaces are light: a pale page, white cards and thin grey borders.

- **Minimum text, maximum substance.** One action per screen. Everything secondary waits behind a click, an `i` or a
  tooltip.
- **Facts, not verdicts.** Numbers and their sources. There are no scores, no "good wallet" badges and no hype words.
- **Colour means something.** Mint is the one accent. Every other hue belongs to one meaning and is used only for it.

## Colors

- **Mint (`primary`, #A7F3D0)** is the one accent: the primary button, an active toggle, rising candles, the live dot,
  the wallet's colour on the chart. Use it on one thing per view. Mint text on white is `primary-ink` (#047857); plain
  mint is too light to read.
- **Ink, muted, faint (#0F172A, #64748B, #94A3B8)** are the text levels. `faint` is for icons at rest and axis text,
  never for sentences.
- **Line (#E2E8F0) and line-strong (#CBD5E1)** separate things. The default border is 1px `line`, and `line-strong`
  marks a hover.
- **Background (#F8FAFC), surface (#FFFFFF), hover (#F1F5F9), sage (#D1FAE5)** are the light layers: the page, the
  cards, ghost hover and press, selected rows and the PnL bar.
- **Navy (#090D16) with navy-line (#1E293B)** carries the header, the home hero and the chart.
- **Meanings, each used for its meaning only:**
  - gain (#059669) and loss (#DC2626) for money;
  - saved, in amber (#D97706), for a wallet in your lists;
  - warn, amber on a pale fill, for sniper, bot-like, fresh and incomplete data;
  - repeat, violet, for a wallet seen in your other analyses;
  - identity, blue, for a publicly known wallet;
  - danger-tag, red, for the token's creator;
  - transfer, orange, for bundles and transfers in.
- **Chart:** candles are mint (up) and slate #CBD5E1 (down) on navy. Ranges are close shades of the same mint
  (rgb 52 211 153, 45 212 191, 134 239 172, 34 211 238, 110 231 183), never a rainbow. A range's row in the list
  carries the same shade.
- **Gradients exist in two places only:** the AI agent button and the hero background. Do not add more.

## Typography

There are two faces, both self-hosted: **Geist** for words and **Geist Mono** for anything that is data.

- **Numbers are mono with tabular figures** (`.mono`, `font-variant-numeric: tabular-nums`) and right-aligned in
  tables, so digits line up in columns.
- **Sizes stay on the scale:** 11, 11.5, 12, 12.5, 13, 14, 15 and 20 px, plus 24 px for the card's PnL and 64 px for
  the home wordmark (40 px on a phone). Body text is 14 px at 1.45.
- **Weights are 400, 500 and 600.** 700 is reserved for the wordmark and the card's PnL.
- **Table headers** are 11.5 px uppercase, `muted`, letter-spaced 0.05em. Uppercase appears only there and in
  section labels.
- **Copy** is English, in sentence case and the active voice. A control says what happens ("Save analysis", then
  "Analysis saved"). No Cyrillic on any page.

## Layout

- **Width:** the content is at most 1280 px wide, 1600 px on a result page, centred. The page side gutter is 24 px,
  16 px on a phone.
- **Spacing** follows a 4 px base: 2, 4, 8, 12, 16, 24 and 32 px. Odd steps of 6, 10, 14 and 18 px exist only inside
  dense controls. Space groups with `gap` in flex and grid, not with margins on each element.
- **Breakpoints:**
  - phone: up to 640 px;
  - tablet: 641 to 960 px;
  - laptop: 961 to 1399 px;
  - wide: 1400 px and up.
  
  Older rules at 380, 560, 720, 860 and 1000 px stay until someone touches them. On a phone and a tablet the
  result table turns into one card per wallet. Before a change counts as done, check it
  at 1920, 1440, 1280, 768 and 390 px. Nothing scrolls the page sideways, wide tables scroll inside their own frame,
  and the footer sits at the bottom.
- **The result page** runs top to bottom: the counts with their `i`, the findings, the chart, the toolbar, the
  filters, one sentence about who is in the table, the table. The wallet card slides in from the right.

## Elevation & Depth

The pages are flat. Depth comes from the light layers (page, card, hover) and from 1 px borders, not from shadows.

- **Shadows are only for things that float:** menus, popovers, the toast, sheets and markers on the chart. The
  popover shadow is `0 12px 32px -12px rgba(15, 23, 42, .35)`.
- **Focus rings:** light inputs get a 3 px `sage` ring with a `primary-border` edge. Inputs on navy get a 3 px
  `rgba(167, 243, 208, .18)` ring with a `primary-strong` edge.
- **Cards never carry a shadow.**

## Shapes

- **Radii:** 8 px (`md`) for controls, 10 px (`lg`) for cards and popovers, 6 px (`sm`) for icon buttons and menu items,
  and full pills for chips, tags and tabs.
- **One radius per kind of object.** A card is always 10 px and a button is always 8 px.
- **Icons are 1.5–1.7 px line drawings** on a 16 px grid in `currentColor`, with round caps. No emoji in controls or
  tables. A docs callout title may carry one, and so may the alerts in Telegram.

## Components

- **Buttons** are 34 px tall:
  - default: white;
  - primary: mint, one per view;
  - ghost: transparent with muted text, for secondary and icon actions.
  
  Pressing changes the fill; nothing scales. Only buttons may rise 1 px on hover.
- **Icon-only buttons** (export, close, copy, move) always carry an `aria-label` and a `title`, centre their glyph
  and are at least 30 px, 36 px on a phone.
- **Chips and tags** are pills set in mono at 10.5–11 px. A filter chip that is on gets a filled background. A hidden
  tag is struck through and pale.
- **Tables** are white, with 1 px row lines, a sticky uppercase header, numbers right-aligned in mono, and a sage bar
  behind PnL (a red-tinted bar for a loss). The first 100 rows are drawn and the rest wait behind "Show more".
- **The star** (save to lists) stays invisible until the pointer reaches its own place before the address, and then
  lights up. One click on an empty star saves the wallet to the Watchlist, and the star turns filled amber. A filled
  star always shows and opens the lists menu. Where there is no hover, as on a phone, the star always shows at 0.5
  opacity.
- **The wallet card** is a right-hand sheet, 420–440 px wide and full width on a phone, with a sticky head: identity,
  then the token facts, then the 7D/30D block (30D by default), then the trades.
- **Tooltips** come from `title` and stay short, about 90 characters at most. On a touch screen a tap on a `.tipt`
  element shows the same text as a toast. An `i` mark (`.dinfo`, `.kinfo`) holds the method; it turns into an amber
  `!` when the data is incomplete.
- **Insights** sit above the chart: a small uppercase "Insights" label, then up to four pills. Each pill is a share in
  percent and a few words ("Top 10 took 47% of the profit"). Amber means a warning, grey means information, violet
  means repeats. A pill with a filter behind it is a button, and one without is plain text with a tooltip. On the home
  page, each token shows its two strongest insights as one line in `ink` above the muted date.
- **Toasts** sit at the bottom centre, one at a time. They name the result and can carry one link ("Lists →") or one
  Undo.
- **Menus and popovers** are white with a 1 px border. Menus have an 8 px radius, popovers 10 px. Escape or a click
  outside closes them.
- **The chart** sits on navy with Geist Mono axes. Trades show as markers; a wallet put on the chart gets its own
  colour, and the same colour fills that row's chart icon.

## Motion

- **Hover and focus colour changes** take 120–150 ms with `ease`.
- **Panels, popovers and tooltips** come in within 200–300 ms with `ease-out`. Nothing that answers a click lasts
  longer than 300 ms, and nothing uses `ease-in`.
- **Content never jumps on hover.** No `translateY` on rows, chips or cards, because a chip in a clipped strip gets cut.
- **Name the properties being animated.** Never write `transition: all`.
- **Decorative loops** (the agent button's sheen, the fresh-pumps tape, the live dot) run briefly or only under the
  pointer. All of them stop under `prefers-reduced-motion: reduce`.

## Do's and Don'ts

- Do use mint on one thing per view. Don't introduce a new accent colour or a new meaning for an existing one.
- Do set every number in Geist Mono with tabular figures. Don't mix proportional digits into tables.
- Do give every hover-only control a touch fallback under `@media (hover: none)`. Don't hide the only way to do
  something behind hover.
- Do keep touch targets at least 36 px on a phone (40–44 px for the main action).
- Do keep keyboard focus visible and give icon-only buttons an `aria-label`. Don't leave a pop-up without Escape.
- Do keep tooltips under about 90 characters and put the method behind an `i`. Don't explain on the page what a
  tooltip can hold.
- Do check 1920, 1440, 1280, 768 and 390 px before calling a change done. Don't let anything scroll the page sideways.
- Don't add shadows to cards, gradients beyond the two that exist, or new fonts.
- Don't copy the look of another product or exchange. tracced must never pass for anyone else.
