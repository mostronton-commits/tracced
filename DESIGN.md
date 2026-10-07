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
    fontFamily: IBM Plex Sans
    fontSize: 64px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.01em
  headline-md:
    fontFamily: IBM Plex Sans
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
  label-md:
    fontFamily: IBM Plex Sans
    fontSize: 12.5px
    fontWeight: 500
    lineHeight: 1.3
  label-sm:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.3
  caption:
    fontFamily: IBM Plex Sans
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.3
  table-head:
    fontFamily: IBM Plex Sans
    fontSize: 11.5px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0.05em
  data-md:
    fontFamily: IBM Plex Mono
    fontSize: 12.5px
    fontWeight: 400
    lineHeight: 1.3
    fontFeature: '"tnum" 1'
  data-strong:
    fontFamily: IBM Plex Mono
    fontSize: 13.5px
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: '"tnum" 1'
  data-hero:
    fontFamily: IBM Plex Mono
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: -0.02em
    fontFeature: '"tnum" 1'
  tag:
    fontFamily: IBM Plex Mono
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
- **Navy (#090D16) with navy-line (#1E293B)** carries the header, the home hero and the chart, and the rank marks of
  a ready list's first three.
- **Meanings, each used for its meaning only:**
  - gain (#059669) and loss (#DC2626) for money;
  - saved, in amber (#D97706), for a wallet in your lists;
  - warn, amber on a pale fill, for sniper, bot-like, fresh and incomplete data;
  - repeat, violet, for a wallet seen in your other analyses;
  - identity, blue, for a publicly known wallet;
  - danger-tag, red, for the token's creator;
  - transfer, orange, for bundles and transfers in.
- **Kinds of wallet** (owner, 04.10, second look: one grey made the pictures alike). Each tag's picture has its own
  quiet colour, by meaning, on one recipe: a pale fill, a light border, the glyph a deeper shade of the same hue. The
  creator is red, sniper amber, bundle orange, bot-like slate, fresh lime, dormant fuchsia, transfer-in cyan, pre-range
  stone, re-bought green (a buy), never-sold sky. A KOL and an exchange are identity blue, a known exploit red. The
  filter legend keeps white chips and colours only the glyphs. Your own tags are words, in the watchlist's indigo.
- **A funder from InsightX's labels** reads "funded by an exchange" (or an app, a casino) on the public site: their terms
  allow what we derive, not their names. The draft shows the names, for the owner to judge them.
- **Chart:** candles are mint (up) and slate #CBD5E1 (down) on navy. Ranges are close shades of the same mint
  (rgb 52 211 153, 45 212 191, 134 239 172, 34 211 238, 110 231 183), never a rainbow. A range's row in the list
  carries the same shade.
- **Gradients exist in two places only:** the AI agent button and the hero background. Do not add more.

## Typography

There are two faces, both self-hosted: **IBM Plex Sans** for words and **IBM Plex Mono** for anything that is data (on trial
from 04.10, owner; they pair with the Carbon icons. Geist stays in `static/fonts/` as the way back).

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
  
  Older rules at 380, 560, 720, 860 and 1000 px stay until someone touches them. On a tablet the result table turns
  into one card per wallet, on a phone into a list, one line per wallet (see Phones). Before a change counts as done, check it
  at 1920, 1440, 1280, 768 and 390 px. Nothing scrolls the page sideways, wide tables scroll inside their own frame,
  and the footer sits at the bottom.
- **The result page** runs top to bottom: the chart, the tally (the counts and the insights in one strip), the
  toolbar, the table with its filters in its head. The wallet card slides in from the right.

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
- **Icons are IBM Carbon** (Apache-2.0; owner, 02.10: the Lucide manner of the old ones read as AI-made). They come
  from one sprite, `static/icons.svg`: `icon('name')` in a template, `EarlyIcon('name')` in a script. Filled shapes
  on a 32-unit artboard in `currentColor`, drawn at 16 px (20 px for the card's star), where they stay sharp. A new
  one is taken from the same commit of the Carbon repo and added to the sprite, never drawn by hand. The brand marks
  (X, Telegram, the trading apps) stay their own. No emoji in controls or tables. A docs callout title may carry one,
  and so may the alerts in Telegram.

## Components

- **Buttons** are 34 px tall:
  - default: white;
  - primary: mint, one per view;
  - ghost: transparent with muted text, for secondary and icon actions.
  
  Pressing changes the fill; nothing scales and nothing rises on hover. No arrows inside buttons: the label says it.
  The hero's Analyze is the plain primary key in Plex Sans 600 (owner, 02.10: the mono capitals went back).
- **Icon-only buttons** (export, close, copy, bell) always carry an `aria-label` and a `title`, centre their glyph
  and are at least 30 px, 36 px on a phone.
- **Chips and tags** are pills set in mono at 10.5–11 px. A bundle's tag is orange like every bundle and carries its
  group's colour as a dot in its corner (one colour per funder; no violet, which means repeats), and a click on it
  shows that bundle alone. A filter chip that is on gets a filled background. A hidden
  tag is struck through and pale. Your own tag carries its own × and goes only by it, with an Undo in the toast; a
  click on the word does nothing (owner, 02.10: tags went by accident).
- **Tables** are white, with 1 px row lines, a sticky uppercase header, numbers right-aligned in mono, and a sage bar
  behind PnL (a red-tinted bar for a loss). The first 100 rows are drawn and the rest wait behind "Show more".
- **Filters live in the table's head** (owner, 02.10). A head reads, on one line: the money key where there is one,
  the sort mark, the name, the funnel. Only the numbers sort; the address does not, and there is no Funded by column:
  the card says who funded a wallet. Funnels stand only by numbers and open one small window: "from … to …", Reset, Apply; Enter applies and
  Escape closes. A funnel holding a filter turns sage. The money unit is a small `$`/◎ key by "Bought". **Filters**
  opens a panel over the table, its full width (owner, 04.10: as it was, not a pop-up): finding a wallet and ★ Only my
  watchlist, then every number from and to, then the tags to hide, struck through when hidden. It applies as you type,
  and it and the funnels edit the same numbers. On a phone or a tablet, where the table has no head, it is the way in.
  **Reset** stands beside Filters whenever a filter is on or the order is not "PnL, highest first", and clears both.
- **The star and the chart mark** before an address come out with the row under the pointer and are gone without it
  (owner, 04.10). One click on an empty star saves the wallet to the watchlist, and the star turns filled amber. A
  filled star always shows and opens the lists menu; the chart mark of a wallet on the chart stays in its colour.
  Where there is no hover, as on a phone, both show at 0.5 opacity.
- **The card hint**: on the first visits, once the table's first row is on screen, a pointer comes to its address and
  clicks, the address rings once and a mint label says "Click an address: its card opens", like the chart's two clicks.
  It shows on at most three visits, stops for good once a card is opened, and is gone at the first click.
- **Watchlist** is the name of everything a person keeps (owner, 04.10): the one link at the top, the page, the star's
  words. A list is one part of it; the first one is *Main*.
- **Alerts** (owner, 04.10): the bell sits on each wallet, in its row and in its card, green when on. A list's own bar
  holds a switch, "Alerts for this list", with "k of N on" beside it: on rings every wallet in the list, the newest
  first while the cap leaves room; off silences them all. On the draft site no bot runs, so the alerts are a preview:
  the bells and the switch save, and the Telegram card says that nothing is sent.
- **The wallet card** is a right-hand sheet, 420–440 px wide (on a phone a sheet from the bottom, see Phones), with a sticky head: identity,
  then the Performance block (7D/30D, 30D by default), always there, then the trades with a switch, "<symbol> token"
  (its numbers here as a small tally, then its trades) and "All tokens" (its recent tokens); the last choice stays for
  the next card (owner, 04.10). A wallet's address in the table opens the card, never copies: it is underlined like a
  link, and a click anywhere else in the row opens the card too. In the card, the address copies itself on a click,
  with no copy mark beside it. Its chips say what they are without a hover: "funded by Binance", "94d old". In the
  watchlist the card shows the lists holding the wallet as switches under "Saved in", amber when on; the last one
  stays, × in the row drops the wallet. In "All tokens" a recent token's row opens, under it, a small chart of that
  token on the hours of the wallet's trades, its buys and sells marked as on the result's chart, with a link to the
  token's page (owner, 04.10). The token's address under a result's or a token's title copies itself on a click too,
  with no copy mark beside it.
- **After the alerts** (on the draft only until the owner shapes it, 04.10) is a block of the watchlist under the lists: a tally strip (buys, median peak,
  doubled, median now, its exit), then a table of first buys by the wallets with a bell, newest first: when, who, the
  token, the size, the peak with how long it took, the dip before it, now (or at 24 h) and the wallet's own exit, all
  as multiples of its buy price. A peak is green from ×2, red below ×1; now and the exit are green from ×1.
- **What's new** (owner, 04.10): a quiet bell right of the wallet (or of Connect), in the top bar and on the home hero.
  While this browser has not seen the newest update, it carries a mint dot with a soft ring that pulses a few times,
  and a hover shows a small note, "Update 0.7.0 is out · Read what's new". It opens /docs/updates, which marks it seen;
  a first visit starts as seen. The Updates page sets each version as a mono line with its date and a few bullets of a
  few words each (owner, 04.10: «лаконічно, чіткіше і коротше»), all on one rail; the newest carries a mint dot and
  "Latest".
- **Tooltips** come from `title` and stay short, about 90 characters at most. On a touch screen a tap on a `.tipt`
  element shows the same text as a toast. An `i` mark (`.dinfo`, `.kinfo`) holds the method; it turns into an amber
  `!` when the data is incomplete.
- **The tally** sits under the chart (owner, 02.10: no pills, no sentence of counts): one strip of cells, each a
  number in mono at 18 px over one uppercase word, the way the table's head reads. First the counts (bought, spent,
  sold out, holding, best ROI, with the `i` of the method), then up to four findings and the launch word when they say
  something. Colour only for meaning: amber a warning, red the creator or a staged launch, violet repeats. A cell with
  a filter or an order behind it is a button. The strip is a grid: a short last row keeps its cells' width. The home
  page shows none.
- **Live on tracced** on the home page is a feed, not a list of links (owner, 05.10: people opened others' finished
  analyses and took them for our verdicts, not seeing they could run their own). It shows the latest twenty analyses by
  anyone, one row each: a letter mark, the symbol, the wallets found and the best ×, or "analyzing now", and how long
  ago. Never who ran them. Rows lead nowhere; the one action is "paste it above" in the caption, which focuses the
  token field. Seven rows show at once (owner, 07.10): the newest arrive one at a time at the top, 3–10 s apart, as
  they happened, and real new ones come every 20 s from `/live.json`. Nothing loops. A row: the token's picture (its
  letter while it loads or when it has none), symbol, one fact, how long ago. The fact is "saved N wallets" with the
  star when people really saved wallets from that analysis, otherwise "found N wallets". Never a made-up number. The
  demo is no row: a guest gets a demo card under the token field (the token, its wallets and 2×+, Open the demo).
- **Ready lists** (owner, 07.10: «цікаво, зрозуміло і привабливо»; 08.10) sit on the home page under the live feed:
  two cards side by side, one column on a phone. Each is last month's and says so ("KOLs · September"), and changes
  once a month: the card reads "N wallets · next list Nov 1". A card is a small leaderboard: the sum they made in the
  month in mono at 24 px 700, green as profit is, the first three as rows (navy rank mark, face, name with @X or win
  rate, the profit), then two keys: *Follow N wallets* with the bell (mint) and *See all N* (white). The two cards are
  one choice, so each carries its own mint key. No stack of faces, no "and 7 more", no line of selling points and no
  note under the cards (owner, 08.10: they looked cheap). Profits show three significant figures ($6.77M, $583K):
  with fewer, neighbours look alike. Every number is tracced's own count of the month, the same as the wallet's card
  on that month; the board that names the candidates is never quoted.
- **A ready list's page**: the title and its rule in one paragraph, the key on top (on a phone a bar fixed at the
  bottom of the screen), a tally strip (Profit, Best, Wallets, Next list), then the wallets as a leaderboard with @X,
  win rate, wins and losses. A row opens the wallet card on the list's month (its tab first, then 7D and 30D), the
  same numbers as the row. Once the person follows the list, the key becomes "In your watchlist".
- **Free while we build it** (owner, 07.10: out of the hero): its own quiet block at the end of the home page, above
  the footer: the line, and *Follow @tracced_xyz* with the X mark, instead of payment.
- **Phones get less text, not fewer facts** (owner, 07.10, «like FOMO»): a short lead in the hero, no 01/02/03 steps,
  no captions under section titles; numbers and actions stay.
- **Phones read like a trading app's lists** (owner, 07.10: «Сторінку результату й картку гаманця як у FOMO»), in
  tracced's own colours:
  - a result's wallet is one line: the star, the wallet's picture (drawn from its address, round), the address with up
    to three marks, under it what it put in, at which cap and how much it sold ("$1.2K at 263K cap · sold out"); PnL
    and ROI on the right. Seven to nine wallets fit a screen. The chart mark leaves the line: the card puts the
    wallet on the chart when it opens;
  - the toolbar is two lines: Filters, Sort and the money unit; then the count, Export and the agent;
  - the result's head keeps the star and "Chart" beside the title, the range under it across the width; the token
    page's facts stand three to a line, never one under another;
  - where the desktop shows a mouse pointer clicking (the chart's two-click demo, the result's card hint), a touch
    screen shows a fingertip pressing, or nothing;
  - a range row is two lines: its number, name and ×; then its times, the pencil and the key;
  - the wallet card rises from the bottom as a sheet (12 px corners, a handle, the page dimmed behind it) and closes
    by ×, a tap above it or pulling its head down. In it, this token's PnL is large like a position, ROI beside it,
    then bought, sold and held.
- **The token's picture** stands before its symbol in a result's head, as in the home feed: its letter on its hue while
  it loads or when it has none.
- **Toasts** sit at the bottom centre, one at a time. They name the result and can carry one link ("Lists →") or one
  Undo.
- **Menus and popovers** are white with a 1 px border. Menus have an 8 px radius, popovers 10 px. Escape or a click
  outside closes them.
- **The chart** sits on navy with Plex Mono axes. Trades show as markers; a wallet put on the chart gets its own
  colour, and the same colour fills that row's chart icon.

## Motion

- **Hover and focus colour changes** take 120–150 ms with `ease`.
- **Panels, popovers and tooltips** come in within 200–300 ms with `ease-out`. Nothing that answers a click lasts
  longer than 300 ms, and nothing uses `ease-in`.
- **Nothing jumps on hover.** No `translateY` on buttons, rows, chips or cards; a chip in a clipped strip gets cut.
- **Name the properties being animated.** Never write `transition: all`.
- **Decorative loops** (the agent button's sheen, the live dot) run briefly or only under the pointer.
- **The fresh-pumps tape** moves slowly all the time and stops under the pointer.
- **The live feed does not roll**: a new row slides in at the top (300 ms, `ease-out`) and the seventh fades out
  at the bottom.
- **The phone's wallet card** rises in 260 ms (`ease-out`) and follows the finger when its head is pulled down; past
  90 px it closes, short of it it goes back.
- All of these stop under `prefers-reduced-motion: reduce`: the tape then scrolls by hand, new feed rows appear
  without sliding, and the card's sheet appears without rising.

## Do's and Don'ts

- Do use mint on one thing per view. Don't introduce a new accent colour or a new meaning for an existing one.
- Do set every number in Plex Mono with tabular figures. Don't mix proportional digits into tables.
- Do give every hover-only control a touch fallback under `@media (hover: none)`. Don't hide the only way to do
  something behind hover.
- Do keep touch targets at least 36 px on a phone (40–44 px for the main action).
- Do keep keyboard focus visible and give icon-only buttons an `aria-label`. Don't leave a pop-up without Escape.
- Do keep tooltips under about 90 characters and put the method behind an `i`. Don't explain on the page what a
  tooltip can hold.
- Do check 1920, 1440, 1280, 768 and 390 px before calling a change done. Don't let anything scroll the page sideways.
- Don't add shadows to cards, gradients beyond the two that exist, or new fonts.
- Don't copy the look of another product or exchange. tracced must never pass for anyone else.
- Don't reach for the template look that AI tools produce by default (owner, 02.10): an arrow in every button, hover
  lifts, semibold everything, pill-shaped stat chips, stock chart libraries, stock component kits. Each detail is chosen for tracced: the
  ledger's mono, the record's cursor, facts in tables.
