# Your account

A Solana wallet signs a one-time message. That signature is the account: no password, no e-mail, no transaction,
no fee.

Works with Phantom. On a phone, open tracced inside the Phantom app: the Connect button takes you there.

## Lists and saved analyses

Tick wallets in a result and press **+ Add to list**, then pick a list or name a new one. The star in a wallet's
card opens the same menu for that one wallet: it shows which lists hold it, and a click adds or removes it.
**Save analysis** keeps the whole result under *My analyses* at `/me`.

You start with one list, *Watchlist*, and can keep up to twenty: one per strategy, per token family, per person you
follow. A wallet can sit in several. At `/me` every list has its own tab with its count, where you rename or delete
it (the first one stays). **Export** there gives the list on screen, or all of them, as CSV or TXT, and the CSV
says which lists hold each wallet.

A row in a list is the wallet and your tags for it: **+** adds one right there. Click the row for the wallet's card,
about the wallet itself: who it is if anyone knows, its age and first funder, the other analyses you saved it in, and its
last 7 or 30 days on every token. Nothing about the token you found it on: that stays on the result.

In a list with alerts on, a row also shows the wallet's buys (↑) and sells (↓) that the alerts saw in the last 7 days
and how long ago it last traded; its card says the same. Every trade counts, whatever your alert settings, from the
moment the list's alerts are on. The counts are kept with your account for 30 days.

## Your own tags

Each saved wallet takes tags you write yourself: in your lists, right in its row, or in the wallet's card. Type a
short word, press Enter. Click a tag to remove it. Tagging a wallet in its card on a result adds it to your *Watchlist*,
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

Open a list and switch its alerts on: the buys and sells of its wallets come to Telegram, a few seconds after they
happen.
Only trades count: a wallet has to sign the transaction itself and pay SOL or a stablecoin for a token, or get them for
one. Transfers, incoming SOL, airdrops and token-for-token swaps stay silent, and so does anything under your minimum.

- **Connect**: on your lists page, press *Connect Telegram*, then *Start* in the bot. The link works once, for ten
  minutes, and only from the wallet you are signed in with. A chat already connected to another wallet stays with it:
  send /stop there first.
- **Choose**: buys, sells, and the smallest trade in dollars, the same for every list with the bell on. Up to
  {{ s.alerts_max_wallets }} wallets per account, and up to {{ s.alerts_per_hour }} alerts an hour.
- **Stop**: *Disconnect* on the lists page, or /stop in the bot.

An alert reads like a trades channel, three lines:

- the dot is the trade's size: 🟢 under ${{ '{:,}'.format(s.alerts_size_usd[0]) }}, 🟡 up to ${{ '{:,}'.format(s.alerts_size_usd[1]) }}, 🔴 from
  ${{ '{:,}'.format(s.alerts_size_usd[1]) }}. Then the token, a link to its chart here; 🆕 when the wallet held none of it,
  *bought more* when it did; for a sale, how much of the position is sold since its first buy, and how much this sale
  took: *sold 60% (+20%)*, then *sold all*; the market cap and the transaction;
- the token's address, only in the first alert about that token;
- whose trade: your tags for the wallet (its short address when it has none), and the amount.

A trade made through an app that pays the network fee for its users (FOMO and the like) counts the same: the wallet
still signs it.

We keep the Telegram chat the alerts go to and your Telegram username; nothing else from Telegram. Alerts are in a
closed test for now.

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
