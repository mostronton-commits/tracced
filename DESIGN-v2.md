---
version: 1.0
name: tracced
description: >
  One dark theme, «Графіт» (owner, 26.10): graphite surfaces, mint for the controls and the brand only, profit green
  and loss red for figures only. Switzer for words and numbers with tabular figures, Tabular for addresses. The values
  live in tracced/web/static/v2/tokens.css; this file says how to use them.
colors:
  background: "#101112"        # the page
  background-deep: "#0B0C0D"   # stages, the hero, inputs inside cards
  surface: "#17181A"           # cards, the chart, menus, the header's search and buttons
  surface-2: "#202225"         # rows, tiles, quiet buttons, the chosen half of a switch
  surface-3: "#2A2C30"         # hover on surface-2
  line: "rgba(255, 255, 255, 0.07)"          # dividers, card edges
  line-strong: "rgba(237, 238, 239, 0.14)"   # outlines of inputs and round buttons
  ink: "#EDEEEF"               # text, numbers; the fill of an ink button
  ink-2: "#C9CCD0"             # long reading text
  muted: "#8B8F94"             # labels, secondary lines, placeholders
  faint: "#4C5055"             # empty dots, the version, disabled
  primary: "#95EBD5"           # mint: the primary key, a switch that is on, the logo, the live dot; never a number
  primary-hover: "#ABF1DE"
  on-primary: "#04261C"
  primary-wash: "rgba(149, 235, 213, 0.09)"  # a selected chip or row
  primary-line: "rgba(149, 235, 213, 0.35)"
  profit: "#5AD46A"            # figures, bars and chart marks that gained
  profit-wash: "rgba(90, 212, 106, 0.13)"
  loss: "#FF6470"              # figures that lost, errors
  loss-wash: "rgba(255, 100, 112, 0.13)"
  risk: "#E7B45A"              # sniper, bundle, fresh, transfer in, bot-like; the saved star
  danger: "#FF6470"            # the creator, launch and own bundles, an organised launch
  known: "#6AB2F2"             # a publicly known wallet: KOL, exchange
  repeat: "#A99AF5"            # seen before in your other analyses
  sleeper: "#E58AD6"           # dormant
  telegram: "#6AB2F2"          # inside pictures of Telegram only
typography:
  hero:
    fontFamily: Switzer
    fontSize: 84px
    fontWeight: 600
    lineHeight: 1.04
    letterSpacing: -0.04em
  display:
    fontFamily: Switzer
    fontSize: 60px
    fontWeight: 600
    letterSpacing: -0.04em
  h1:
    fontFamily: Switzer
    fontSize: 40px
    fontWeight: 600
    letterSpacing: -0.02em
  h2:
    fontFamily: Switzer
    fontSize: 28px
    fontWeight: 600
    letterSpacing: -0.02em
  num:
    fontFamily: Switzer
    fontSize: 24px
    fontWeight: 600
    fontFeature: '"tnum" 1'
  title:
    fontFamily: Switzer
    fontSize: 19px
    fontWeight: 600
    letterSpacing: -0.02em
  lead:
    fontFamily: Switzer
    fontSize: 18px
    fontWeight: 400
  read:
    fontFamily: Switzer
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.65
  body:
    fontFamily: Switzer
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: '"tnum" 1'
  small:
    fontFamily: Switzer
    fontSize: 13px
    fontWeight: 400
  caption:
    fontFamily: Switzer
    fontSize: 12px
    fontWeight: 400
  micro:
    fontFamily: Switzer
    fontSize: 11px
    fontWeight: 500
    letterSpacing: 0.05em
  address:
    fontFamily: Tabular
    fontSize: 13px
    fontWeight: 400
rounded:
  xs: 4px       # bars, size dots
  sm: 6px       # tags, small chips inside text
  md: 10px      # inputs, toolbar buttons, tiles inside a row
  lg: 14px      # rows, tiles, menus, the chart
  card: 22px    # cards
  modal: 26px   # modals, the hero input
  full: 999px   # primary and ink keys, switches, pills, the account pill
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  page-gutter: 24px
  page-gutter-phone: 12px
  page-max: 1280px
  page-max-result: 1600px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.full}"
  button-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.background}"
    rounded: "{rounded.full}"
    height: 40px
  button:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: 34px
  icon-round:
    backgroundColor: "{colors.surface}"
    size: 40px
  search:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.full}"
    height: 40px
    width: 420px
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: 20px 22px
  menu:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: 6px
  chart:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
---

# tracced design system

This file is the source of truth for how tracced looks and moves. Every change to the interface follows it, whoever
makes the change. When a design skill or a general rule disagrees with this file, this file wins. When a change needs
something this file does not cover, settle it with the owner and then add it here in the same commit.

The target screens are on the owner's design canvas («tracced — напрями», page «Усі екрани»), approved on 26.10.

**v2 lives beside the old look** (owner, 26.10): `static/v2/tokens.css` and `static/v2/style.css`, the header, footer
and account pill in `templates/v2/`; `base.html` picks them when the browser has the cookie `design=v2`, and the old
`static/style.css` with DESIGN.md stays the default, untouched. `/design?to=v2` and `/design?to=old` switch a browser
(the closed copy and the owner's wallets only). Scripts ask `document.documentElement.dataset.design === 'v2'`.
v2 moves onto the canvas in phases (see the last section); until a page's phase lands, it keeps its old layout in the
new colours and type.

## Overview

tracced shows on-chain facts: who bought a token, when, and what the wallet did next. The look follows the job:
restrained, exact, quiet, on one dark theme. It is closer to an engineering instrument than to a trading terminal.

Rules the owner set (do not undo them):

- **One dark theme** (26.10). No light theme and no switch; light may come later as its own project.
- **Each fact once per page.** If the header says it, the footer does not. The footer carries no logo or name.
- **Little text.** One short line under a title at most; explanations go into a tooltip (`i`) or Docs.
- **Minimal is not fewer features** (owner, 26.10: «мінімалізм не значить що ми врізаємо функціонал»). Rarely used
  controls hide behind a `⋯` or a menu; they are never deleted.
- **Facts, not verdicts.** Numbers and their sources; no scores, no "good wallet" badges, no hype words.
- **Not «AI-made».** No default AI fonts, no stock icon kits, no Tailwind colours, no glowing blobs, no arrows inside
  buttons, no hover lifts, no mascots (the eyed candle was rejected).
- **Real brands where trust matters.** Wallet apps show their original logos; tokens their real pictures.
- **No fake activity.** Feeds and counters show real events only.

## Colors

- **Graphite surfaces:** `background` the page, `background-deep` stages and the hero, `surface` cards, the chart and
  menus, `surface-2` rows, tiles and quiet buttons, `surface-3` their hover. Edges are hairlines: `line` between
  things, `line-strong` around inputs and round buttons.
- **Text:** `ink` for text and numbers, `ink-2` for long reading, `muted` for labels and secondary lines, `faint` for
  empty dots and the version, never for a sentence.
- **Mint (`primary`) is for controls and the brand only:** the primary key (one per view), a switch that is on, the
  logo, the live dot, a selected chip (`primary-wash` with a `primary-line` edge). Text on mint is `on-primary`.
  **Mint never colours a number.**
- **Profit and loss** colour figures, bars and chart marks only: PnL, ROI, candles, buys and sells on the chart.
- **Meanings, each used for its meaning only:** `risk` amber (sniper, bundle, fresh, transfer in, bot-like, partial
  data, the saved star), `danger` red (the creator, launch and own bundles, an organised launch), `known` blue (a KOL
  or an exchange), `repeat` violet, `sleeper` pink. A tag carries its hue at 16 % fill, about 40 % edge, the glyph in
  the full hue. Telegram's blue appears only inside pictures of Telegram.
- **Gradients exist in one place:** the quiet light at the top of the page (and, from phase 2, the planet on the home
  page). Do not add more.

## Typography

Two faces, self-hosted: **Switzer** for words and numbers, **Tabular** for wallet and token addresses. Both are
Fontshare's (ITF Free Font License: they may be self-hosted, not redistributed), so their files live in
`static/fonts/fs/`, outside git, and are copied to each server once; IBM Plex follows each face in the stacks, for the
Cyrillic of the agent's Ukrainian, the arrows, and a checkout without the files.

- **Numbers use tabular figures** (`font-variant-numeric: tabular-nums` on the whole page) and sit right-aligned in
  tables, so digits line up. `var(--data)` in the stylesheet is the numbers' face (Switzer); `var(--mono)` is Tabular.
- **Sizes are the twelve steps:** 11, 12, 13, 14, 16, 18, 19, 24, 28, 40, 60 and 84 px. Body text is 14 px at 1.45.
  Titles of 19 px and up are tightened (`-0.02em`), 60 px and up more (`-0.04em`).
- **Weights are 400, 500 and 600.** There is no 700.
- **Table headers** are 11 px uppercase, `muted`, letter-spaced. Uppercase appears only there and in section labels.
- **Copy** is English, in sentence case and the active voice. A control says what happens ("Save analysis", then
  "Analysis saved"). No Cyrillic on any page. Numbers: `$1.2K`, `$2.7M`, a real minus `−`, multiples `3.1×`.

## Layout

- **Width:** the content is at most 1280 px wide, 1600 px on a token's page (its results are on it), centred. The page side gutter is 24 px,
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
- **A token's page is one page from the token to its wallets** (owner, 09.10: «юзер вводить токен і на тій самій
  сторінці виділяє діапазон і отримує результат»). Top to bottom: the token's head with its chips, the chart, the
  token's analyses as tabs (each in its band's shade: «Pump 1 · 765 wallets», a dashed «+ New range»), the run's line
  while it goes, and the chosen
  result: the tally (the counts and the insights in one strip), the toolbar, the table with its filters in its head.
  The wallet card slides in from the right.
  - The chart is the control: two clicks mark a range and a small bar appears on the chart itself, top centre,
    where the hint was: the range's times, ✎ for exact minutes, Cancel, *Get wallets* (owner, 14.10, variant B: under
    the chart nobody saw it). Nothing under the chart repeats it. Nothing runs until it is pressed (owner, 09.10:
    variant A). A result on screen stays while a new range is marked.
  - A first-visit tour (owner, 14.10): four steps, each shown when its part of the page appears — the chart (mark the
    zone), the bar on the chart (Get wallets), the result's table, a wallet's card. A spotlight dims the rest without
    blocking it; a light card says what the part does in one short sentence. Once per browser, Skip ends it; on a
    phone the card is a sheet at the bottom. The chart's animated cursor plays only while the first step is open; once
    that step is read it is gone, and after a skipped tour it plays one cycle, once per browser (owner, 14.10).
  - The run (owner, 09.10: «бігуча строка»): a line under the chart fills with the run's own steps — Token,
    Trades, Exits, Checks, Wallets — its phase and count in words («Checking where they sold · 329 / 765 wallets»), a
    light passing along the filled part, and the range's band on the chart glows with a light moving left to right.
    Full, it says how many wallets were found, then the result rises in below. No page reload anywhere.
  - Tabs (owner, 09.10: variant A of two): one result on the page at a time; the others wait as fetched markup (three
    at most), so a tab opens at once; the band's label on the chart opens its tab too. Up to `ranges_per_token`
    analyses per token; the demo's tabs are its recorded pumps, each replayed once per browser. Tabs go in the order
    their ranges start and are named Pump 1, 2, 3 by it, the same on the page as after a reload; a run you started
    gets its × when it ends. A closed tab's late answers (a card's age, trades, profile) are dropped, never drawn
    into the open tab's card (release check, 10.10).
  - The address follows the tab: /job/<id> for a result (shareable, opens this page with that tab chosen), /token?mint=
    for the bare token; Back and Forward move between tabs.
  - Weak computers (owner, 09.10): one result mounted, its listeners, timers and pop-ups gone when another tab opens
    (static/result.js); motion in CSS only, none with reduced motion; the table draws a hundred rows at a time. On a 4×
    slower processor a tab switch stays under 200 ms of blocking.

## Page frame

- **The header** (every page but home), 68 px, aligned with the page's content: the logo (the mark in mint and
  *tracced* at 18 px), one search pill (420 px, "Paste a token address", a `/` key that puts the cursor in it), a
  spacer, a round X button that follows @tracced_xyz, and who is signed in. No links in the header (owner, 26.10).
  The search takes a token; it will take a wallet too once a wallet has a page of its own.
- **Who is signed in:** a pill with the wallet's fingerprint, its short address in Tabular and a chevron; it opens a
  menu: Watchlist, My analyses, Top traders (when a list is out), Docs, Sign out. A guest sees Connect, an ink key.
  How many analyses are left today is said where an analysis starts (the bar on the chart), not in the pill.
- **The wallet fingerprint:** sha256 of the address; five rows of five dots, the left three columns mirrored to the
  right. Byte *i* of the hash (row by row, three per row) sets cell *i*: `% 4 == 0` an empty `faint` dot, `1` mint,
  else `ink`. The same address draws the same picture everywhere (`fingerprint()` on the server).
- **The home header:** the small logo on the left, the X button and the account on the right, over the planet (canvas Home6).
- **The footer** is one line on every page: Demo (when there is one), Docs, How it works, The project, What's new,
  Contact; then the Telegram and GitHub marks and the version. No logo, no status bar, no bell (owner, 26.10).
- **Quiet light:** the top of every page carries a faint mint light (`radial-gradient` at 10 %) and a few stars
  (`static/v2/stars.svg`), painted on the page itself so nothing sits above the content.
- **Small marks** (search, X, Telegram, GitHub, chevron) are our own 16-unit strokes in `currentColor`
  (`glyph()` on the server). The IBM Carbon sprite stays for the controls that use it until their phase.

## One theme

v2's stylesheet began as a copy of the old one with the dark theme of 08.10 made the only one, in the graphite
palette instead of navy. Its `[data-theme="dark"]` rules start with `:root`, which keeps their weight; the
plain-element ones (`input`, `button`, `a`) use `:where(:root)` so a control's own rule still wins. A new rule needs
no second, dark line.

## Elevation & Depth

- **Cards** are `surface` with a `line` hairline and no shadow.
- **Things that float** (menus, popovers, toasts, sheets) carry `shadow-pop`; modals `shadow-modal` over a dimmed
  page.
- **Focus:** inputs get a mint edge and a soft mint ring; the header's search glows the same way.

## Shapes

- **Radii:** 4 px bars, 6 px tags, 10 px inputs and toolbar buttons, 14 px rows, menus and the chart, 22 px cards,
  26 px modals and the hero input, full pills for the primary and ink keys, switches and the account pill. Inner
  radius = outer radius − padding.

## Components

- **Buttons** are 34 px tall in toolbars, 40–50 px where they are the page's action:
  - default: `surface-2` with a hairline, `r-m` corners;
  - primary: mint, a pill, one per view;
  - ink: the light `ink` fill with dark text, a pill — Connect and the AI agent (26.10: the iridescent agent button went);
  - ghost: transparent with muted text, for secondary and icon actions.
  
  Pressing changes the fill; nothing scales and nothing rises on hover. No arrows inside buttons: the label says it.
  The hero's Analyze is the plain primary key in Switzer 600.
- **Icon-only buttons** (export, close, copy, bell) always carry an `aria-label` and a `title`, centre their glyph
  and are at least 30 px, 36 px on a phone.
- **Chips and tags** are pills at 11–12 px. A bundle's tag is orange like every bundle and carries its
  group's colour as a dot in its corner (one colour per funder; no violet, which means repeats), and a click on it
  shows that bundle alone. A filter chip that is on gets a filled background. A hidden
  tag is struck through and pale. Your own tag carries its own × and goes only by it, with an Undo in the toast; a
  click on the word does nothing (owner, 02.10: tags went by accident).
- **Tables** sit on their card, with 1 px `line` rows, a sticky uppercase header, numbers right-aligned in tabular
  figures, addresses in Tabular, and a `profit-wash` bar behind PnL (`loss-wash` for a loss). The first 100 rows are drawn and the rest wait behind "Show more".
- **Bought is everything the wallet bought of the token** (owner, 11.10: «bought $32, sold $13K» read as a mistake):
  before, inside and after the range, the same base as Sold, PnL and ROI. Under it, small: what it bought inside the
  range and the cap there ("$32 in range · 169K"), or the cap alone when it bought only inside. Its funnel and its sort
  use the number on screen. The card's "bought" says the same.
- **A bot mark is ours only** (owner, 11.10): the bot picture means the bot-like tag, from the wallet's own trades on
  this token. Solana Tracker's «known bot», «likely bot or arbitrage» labels are not drawn anywhere, so Hide bot-like
  hides every row that shows one. The exchange and exploit marks from public labels stay.
- **One card's trades on the chart at a time** (owner, 11.10: three cards in a row left a mess of arrows): a card puts
  its wallet on the chart, and the next card takes its place. A wallet put there with the row's chart mark stays until
  its × or the mark again.
- **Filters live in the table's head** (owner, 02.10). A head reads, on one line: the money key where there is one,
  the sort mark, the name, the funnel. Only the numbers sort; the address does not, and there is no Funded by column:
  the card says who funded a wallet. Funnels stand only by numbers and open one small window: "from … to …", Reset, Apply; Enter applies and
  Escape closes. A funnel holding a filter turns mint. The money unit is a small `$`/◎ key by "Bought". **Filters**
  opens a panel over the table, its full width (owner, 04.10: as it was, not a pop-up): finding a wallet and ★ Only my
  watchlist, then every number from and to, then the tags to hide, struck through when hidden. It applies as you type,
  and it and the funnels edit the same numbers. On a phone or a tablet, where the table has no head, it is the way in.
  **Reset** stands beside Filters whenever a filter is on or the order is not "PnL, highest first", and clears both.
  **Views** (owner, 12.10, after Phanes): the last row of the panel. "Save these filters" asks for a name and keeps the
  numbers, the hidden tags, the toggles and the order in this browser for any analysis; a chip applies one (mint-washed when
  it is in force), its × deletes it, eight at most. The button shows only when something is set.
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
  then the Performance block (7D/30D, 30D by default) with its tokens under the numbers, Recent or Best. It is the same
  card everywhere (owner, 08.10: «картка трейдера має бути однакова скрізь»): a result's card adds one block on top,
  "<symbol> trades" (its numbers here as a small tally, then its trades), and nothing switches between them. A wallet's address in the table opens the card, never copies: it is underlined like a
  link, and a click anywhere else in the row opens the card too. In the card, the address copies itself on a click,
  with no copy mark beside it. Its chips say what they are without a hover: "funded by Binance", "94d old". In the
  watchlist the card shows the lists holding the wallet as switches under "Saved in", amber when on; the last one
  stays, × in the row drops the wallet. In the tokens under the numbers a row opens, under it, a small chart of that
  token on the hours of the wallet's trades, its buys and sells marked as on the result's chart, with a link to the
  token's page (owner, 04.10). The token's address under a result's or a token's title copies itself on a click too,
  with no copy mark beside it.
- **After the alerts** (on the draft only until the owner shapes it, 04.10) is a block of the watchlist under the lists: a tally strip (buys, median peak,
  doubled, median now, its exit), then a table of first buys by the wallets with a bell, newest first: when, who, the
  token, the size, the peak with how long it took, the dip before it, now (or at 24 h) and the wallet's own exit, all
  as multiples of its buy price. A peak is green from ×2, red below ×1; now and the exit are green from ×1.
- **What's new** is a link in the footer (26.10: the bell beside the wallet went with the status bar). The Updates page
  sets each version as a line with its date and a few bullets of a few words each (owner, 04.10: «лаконічно, чіткіше і
  коротше»), all on one rail; the newest carries a mint dot and "Latest".
- **Tooltips** come from `title` and stay short, about 90 characters at most. On a touch screen a tap on a `.tipt`
  element shows the same text as a toast. An `i` mark (`.dinfo`, `.kinfo`) holds the method; it turns into an amber
  `!` when the data is incomplete.
- **The tally** sits under the chart (owner, 02.10: no pills, no sentence of counts): one strip of cells, each a
  number in tabular figures at 18 px over one uppercase word, the way the table's head reads. First the counts (bought, spent,
  sold out, holding, best ROI, with the `i` of the method), then up to four findings and the launch word when they say
  something. Colour only for meaning: amber a warning, red the creator or a staged launch, violet repeats. A cell with
  a filter or an order behind it is a button. The strip is a grid: a short last row keeps its cells' width. The home
  page shows none.
- **Live on tracced** on the home page is a feed, not a list of links (owner, 05.10: people opened others' finished
  analyses and took them for our verdicts, not seeing they could run their own). It shows the latest twenty analyses by
  anyone, one row each: a letter mark, the symbol, the wallets found and the best ×, or "analyzing now", and how long
  ago. Never who ran them. Rows lead nowhere. No caption and no day count above it (owner, 08.10). Seven rows show at once (owner, 07.10): the newest arrive one at a time at the top, 3–10 s apart, as
  they happened, and real new ones come every 20 s from `/live.json`. Nothing loops. A row: the token's picture (its
  letter while it loads or when it has none), symbol, one fact, how long ago. The fact is "saved N wallets" with the
  star when people really saved wallets from that analysis, otherwise nothing (owner, 08.10: "found 180 wallets" said
  nothing, the market cap neither, and "made 2×+" left unclear who made it). Never a made-up number: the owner asked
  for random saved counts three times and they stay out, as they would show activity that never happened. The demo is
  neither a row nor a card on the home page (owner, 08.10): it is a link, Demo, first in the footer's line.
- **Ready lists** (owner, 07.10: «цікаво, зрозуміло і привабливо»; 08.10: one list, simpler) sit on the home page under
  the live feed, under "Follow the best traders" (owner, 08.10: no subtitle, no word twice): two cards side by side, one
  column on a phone. The first is the list, last month's, and says so ("September's top 10", "next list Nov 1"): the
  sum they made in the month in tabular figures at 24 px 700, green as profit is, "combined profit" under it, five leaders as rows (three on a
  phone) and the next one blurred, as the old list of analyses did, then one full-width key: *Open the list*, which
  asks for a wallet first and then opens the list's page (owner, 08.10). The first three ranks are medals, quietly
  (owner, 08.10): a pale gold, silver and bronze disc with a deeper digit, never a bright fill. Beside the list, three
  tiles (owner, 08.10, «text», the take he chose of three after tier-1 sites): a big one, "Their trades, in your
  Telegram", whose deep area (the hero's, with a faint mint and indigo glow) holds two real alerts of a trader on the
  list as notifications, the newest on top and the older one smaller and dimmer behind, the text the first line of what
  the alert code writes, with no links (the home page is open to guests, the list is not); under it two quiet tiles, a
  mint icon on a deep square and two lines: "Real traders only" and "A new list every month". No illustrations, no
  numbers in them. The column takes the list's height and the deep area fills what is left; on a phone the three stack.
  With no alert to show, the big tile becomes a quiet one with the bell. No stack of faces, no notes under the cards.
  Profits show three significant figures ($6.77M, $583K). Every number is tracced's own count of the month, the same
  as the wallet's card on that month.
- **A ready list's page** is for a connected wallet only (owner, 08.10: nobody takes the list without connecting; a
  guest sees the title, one line and Connect): the title, one short line ("September's most profitable traders. Real
  people, no bots."), the key on top (on a phone a bar fixed at the bottom), a tally strip (Profit, Best, Wallets,
  Next update), the wallets as a leaderboard with @X, win rate, wins and losses, and a link to the other list (Best ROI,
  for comparison: ROI is the main number there). A row opens the wallet card, the same as a result's: 7D and 30D, no
  tab for the month (owner, 08.10: the month is the list itself). Under the card's numbers its tokens switch between
  Recent and Best (owner, 08.10, «як на FOMO»): Best is where the PnL was made, the most profitable first.
- **Free during beta** (owner, 07.10: out of the hero; 08.10: the words): its own quiet block at the end of the home
  page, above the footer: "Pay with a follow on X, and be the first to see what's new." and *Follow @tracced_xyz* with
  the X mark, instead of payment.
- **Chips under a token's title** (owner, 08.10, like OpenSea): on the token page and a result, under the symbol and the
  token's picture: SOLANA, its age ("3 weeks old"), NEW in green for its first day, the launchpad; capitals in a
  thin outline, then the short address that copies itself, Solscan and the project's X.
- **No status bar** (owner, 26.10). Its links are the footer's line; UTC/Local is a key on the chart's toolbar (the
  chart is where time is read) and USD/SOL the `$`/◎ key in the table's head, a switch in the toolbar where the head is
  hidden. A switch is a segmented pill: `bg` track, the chosen half on `surface-2`.
- **The hero line stays "every wallet on the record_"** (owner, 08.10: "Find who bought before the pump — and catch
  their next move" was tried and is too long): under the big *tracced*, in tabular figures at 26 px (18 on a phone), "on the
  record" in mint, the cursor after it; under it the lead, "Paste a token, mark the pump — see who bought before it and
  what they did next." (owner, 08.10: not "every wallet" twice). A shared link shows "See who bought before the pump,
  and what they did next." (description and og tags).
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
- **Menus and popovers** are `surface` with `shadow-pop` and a 14 px radius, items 36 px with 10 px corners. Escape or a click
  outside closes them.
- **The chart** sits on `surface` with Switzer axes, candles in profit and loss, hairline grid. Trades show as markers; a wallet put on the chart gets its own
  colour, and the same colour fills that row's chart icon.

## Motion

- **Hover and focus colour changes** take 120–150 ms (`--t-fast`) with `ease`.
- **Panels, popovers and tooltips** come in within 200–300 ms with `ease-out`. Nothing that answers a click lasts
  longer than 300 ms, and nothing uses `ease-in`.
- **Nothing jumps on hover.** No `translateY` on buttons, rows, chips or cards; a chip in a clipped strip gets cut.
- **Name the properties being animated.** Never write `transition: all`.
- **Decorative loops** (the agent button's sheen, the live dot) run briefly or only under the pointer.
- **The fresh-pumps tape** moves slowly all the time and stops under the pointer. Each chip leads with the market
  cap now, the number the token page opens with, and the peak follows it, smaller (owner, 10.10).
- **The live feed does not roll**: a new row slides in at the top (300 ms, `ease-out`) and the seventh fades out
  at the bottom.
- **The phone's wallet card** rises in 260 ms (`ease-out`) and follows the finger when its head is pulled down; past
  90 px it closes, short of it it goes back.
- All of these stop under `prefers-reduced-motion: reduce`: the tape then scrolls by hand, new feed rows appear
  without sliding, and the card's sheet appears without rising.

## Do's and Don'ts

- Do use mint on controls, one primary key per view. Don't colour a number mint, or add an accent.
- Do set numbers with tabular figures and addresses in Tabular.
- Do give every hover-only control a touch fallback under `@media (hover: none)`. Don't hide the only way to do
  something behind hover.
- Do keep touch targets at least 36 px on a phone (40–44 px for the main action).
- Do keep keyboard focus visible and give icon-only buttons an `aria-label` and a `title`. Don't leave a pop-up without
  Escape.
- Do keep tooltips under about 90 characters and put the method behind an `i`.
- Do check 1920, 1440, 1280, 768 and 390 px before calling a change done. Don't let anything scroll the page sideways.
- Don't add shadows to cards, gradients beyond the quiet light, new fonts or a light theme.
- Don't copy the look of another product or exchange. tracced must never pass for anyone else.

## The rebrand, phase by phase

1. **Frame (26.10):** tokens, fonts, one dark theme, the header with the account pill, the one-line footer, the quiet
   light; the chart in the new colours; UTC/Local on the chart; the AI agent an ink key.
2. **Every page after the canvas (26.10, first pass; the owner reviews each one next):**
   - home (`v2/index.html`, `home.css`): the planet with real wallet-stars of the latest analysis (height = what it
     made, mint at 3×+), the centred hero, Fresh pumps as a market map (6 tiles, «+N more», 2×2 on a phone; hidden
     when the list is off or stale, «Quiet: no new pumps in 24 h» when it is fresh and empty), Live on tracced, Top 10
     beside Alerts in Telegram, the closing call with the first buyers of that analysis on orbits;
   - analysis (`v2/token.html`, `v2/_result.html`, `analysis.css`, v2 branches in result.js, tokenpage.js, chart.js,
     card.js): toolbar above the chart (timeframes, Market cap | Price, back to range, first hours, wallets on the
     chart, UTC | Local, USD | SOL), the range bar on the chart, tabs and the progress card, the tally of counts and
     findings, the table with fingerprints and the trip line, a Columns menu that shows, hides and reorders columns
     (Held, Buys/sells, First buy, Funded by live there), `⋯` with Export, the card as a right column from 1200 px with
     Share (`/job/<id>?w=<wallet>` opens that card) and Watch;
   - lists and watchlist (`v2/lists.html`, `v2/me.html`, `lists.css`): the leaderboard on one card, Telegram alerts as
     a head and three tiles (Send me, Smallest trade, Today);
   - docs, contact, the connect sheet (the wallet apps' original logos in `static/v2/wallets/`), one «Page not found»
     with a line that drops to zero; the private page looks the same and keeps Connect in the header for the owner.
