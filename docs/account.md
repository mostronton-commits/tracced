# Your account

A Solana wallet signs a one-time message. That signature is the account: no password, no e-mail, no transaction,
no fee.

Works with Phantom, Backpack and Solflare. On a phone, open tracced inside the wallet's own app: the Connect button
takes you there.

## Your watchlist and saved analyses

The wallets you keep are your watchlist. In a result, point at a wallet's row: a star (☆) comes out before its address.
One click puts the wallet in your watchlist and fills the star (★). A filled star, in the row or in the wallet's card,
opens the menu of your lists: it shows which lists hold the wallet, and a click adds or removes it, or makes a new
list. **★ Only my watchlist**, in the Filters panel, keeps only the wallets you have saved. **Save analysis** keeps the
whole result under *My analyses* at `/me`; the *Watchlist* link at the top of every page leads there.

Your watchlist starts with one list, *Main*, and can hold up to twenty: one per strategy, per token family, per person you
follow. A wallet can sit in several. At `/me` every list has its own tab with its count, where you rename it right in the tab
or delete it (the first one stays). A wallet's card there shows the lists that hold it: a click adds it to a list or
takes it out. It stays in at least one; × in its row drops the wallet.
**Export** there gives the list on screen, or all of them, as CSV or TXT. The CSV is about each wallet itself: its
name and X account when known, its first funder and the exchange behind it, its first transaction, your tags, the
lists that hold it, and the token you found it on.

A row in a list is the wallet and your tags for it: **+** adds one right there. Click the row for the wallet's card,
about the wallet itself: who it is if anyone knows, its age and first funder, the other analyses you saved it in, and its
last 7 or 30 days on every token. Nothing about the token you found it on: that stays on the result.

A wallet with its bell on also shows, in its row, the buys (↑) and sells (↓) the alerts saw in the last 7 days and how
long ago it last traded. Its card adds its biggest buy in those days and how many alerts it has sent you today. Every
trade counts, whatever your alert settings (except the skipped part of a bot's minute), from the moment the alerts
started watching the wallet. When its bell goes off, its counts are dropped, and they start again the next time.
Counts are kept for 8 days.

## Your own tags

Each saved wallet takes tags you write yourself: in your watchlist, right in its row, or in the wallet's card. Type a
short word, press Enter. A tag goes only by its own ×, and Undo in the message that follows brings it back. Tagging a wallet in its card on a result adds it to your *Watchlist*,
because a tag is a reason to watch it. A tag is the wallet's name for you: your lists and your Telegram alerts show
it instead of the address.

Up to six per wallet, lowercased, so `Insider` and `insider ` do not become two different things. They never mix
with the tags an analysis computes, and they come out in the CSV.

## Repeats

When a wallet in a result was **also** an early buyer in another analysis you saved, its row carries a chain link.

Click it and the wallet's card names those analyses — token, range, and what the wallet made there — as links.
The chip above the table filters the list down to those wallets.

!!! tip "🔗 Where a repeat comes from"
    It is the intersection of analyses saved to **your** account. Other people's saved analyses are never part of
    it, nothing leaves the server, and it costs no requests.

## Telegram alerts

Click the bell by a wallet, in its row or in its card: its buys and sells come to Telegram, a few seconds after they
happen. The bell is per wallet, so you choose exactly whose trades you hear about. To hear a whole list, open it and
switch on *Alerts for this list* in its bar: every wallet in it gets its bell, the newest first while there is room
under the cap, and switching it off silences them all. If the live stream misses a trade, a check that runs every minute finds the trades of the last 10 minutes; an
alert that comes a minute or more late says how long ago the trade was. A wallet that trades more than 30 times a
minute is taken for a bot: the rest of that minute is skipped.
Only trades count: a wallet has to sign the transaction itself and pay SOL or a stablecoin for a token, or get them for
one. Transfers, incoming SOL, airdrops and token-for-token swaps stay silent, and so does anything under your minimum.

- **Connect**: on your watchlist page, press *Connect Telegram*, then *Start* in the bot. The link works once, for ten
  minutes, and only from the wallet you are signed in with. A chat already connected to another wallet stays with it:
  send /stop there first.
- **Choose**: buys, sells, and the smallest trade in dollars, the same for every wallet with its bell on. Up to
  {{ s.alerts_max_wallets }} wallets per account: with all of them on, turn one off before you turn another on. Up to
  {{ s.alerts_per_hour }} alerts an hour and {{ s.alerts_per_day }} a day (UTC), and {{ s.alerts_per_wallet_day }} a day from
  any one wallet, so a bot trading every minute does not use up the rest; past any of them, one message says so and
  the rest of that hour or day is skipped (for that wallet alone, when it is the wallet's cap). The watchlist page counts both: how many wallets have their bell on, and how many
  alerts went out today.
- **Stop**: *Disconnect* on the watchlist page, or /stop in the bot.

An alert reads like a trades channel, three lines:

- the dot is the trade's size: 🟢 under ${{ '{:,}'.format(s.alerts_size_usd[0]) }}, 🟡 up to ${{ '{:,}'.format(s.alerts_size_usd[1]) }}, 🔴 from
  ${{ '{:,}'.format(s.alerts_size_usd[1]) }}. Then the token, a link to its chart here; 🆕 when the wallet held none of it,
  *bought more* when it did; for a sale, how much of the position is sold since its first buy, and how much this sale
  took: *sold 60% (+20%)*, then *sold all*; the market cap and the transaction;
- the token's address, only in the first alert about that token;
- whose trade: your tags for the wallet (its short address when it has none), and the amount.

A trade made through an app that pays the network fee for its users (FOMO and the like) counts the same: the wallet
still signs it.

The token's name, its market cap and the share sold come from our data provider, and alerts have a daily share of it:
{{ '{:,}'.format(s.alerts_st_per_day) }} requests for everyone together. On a day that uses it up, alerts keep coming
until 00:00 UTC, with the token's short address in place of its name (unless it came up in the last ten minutes), and
without the cap and the sold share.

We keep the Telegram chat the alerts go to and your Telegram username; nothing else from Telegram. Alerts are in a
closed test for now.

### After the alerts

Under your lists, *After the alerts* shows what happened after each first buy of a token by a wallet with its bell
on, in the last 7 days: the highest price in the next 24 hours and how long it took, the lowest before that, the
price now (or at 24 hours) and the wallet's own average exit, each as a multiple of its buy price. The strip above it
sums them up: how many buys, the median peak, how many doubled, the median now and the median exit. With no bell on
yet, it uses your 10 newest wallets.

It is counted from the wallets' own trades, so it also covers a buy that sent no alert (under your minimum, past a
daily limit). The trades come with each wallet's 30 days; the prices are 5-minute candles of each token. It is
counted again at most every 15 minutes.

## What other people see

Finished analyses are public. The home page lists what everyone analyzed, and any result opens for anyone.

**Who ran an analysis is never shown.** Your lists, your own tags and your saved analyses are never shown to other
people.

## What we record

With a connected wallet, the server keeps a log of what that wallet does here, so the owner can see how the product
is used and what it costs to run:

- the pages you open, and whether from a phone or a computer;
- the analyses you run, the wallets and analyses you save, your lists, how many own tags a wallet has (not the
  words), and your exports;
- the buttons you use, such as a sort, a filter, an export or a link to Solscan, with a short setting like the
  column you sorted by; never an address or anything you type;
- your use of the AI agent, and the questions you type to it;
- what you send through **Contact**, with the page you came from;
- what each step cost in data credits;
- once a day while the wallet is active: public facts about it from the chain — its age, its SOL balance, its last
  30 days of trading as counted by tracced's own ledger, and public identity labels (a KOL name or an X account, if
  it has one).

Only the owner sees it. It is never sold or shared, and it is kept for 13 months. Signing out stops it.

Without a wallet, the log holds nothing about you: visits are counted by Umami, which sets no cookies and never gets
a wallet address.
