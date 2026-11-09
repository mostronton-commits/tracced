# Your account

A Solana wallet signs a one-time message. That signature is the account: no password, no e-mail, no transaction,
no fee.

Works with Phantom, Backpack and Solflare. On a phone, open tracced inside the wallet's own app: the Connect button
takes you there.

You stay signed in for 30 days. **Sign out** ends the session on every device at once, not only in this browser.

## Your watchlist and saved analyses

The wallets you keep are your watchlist. In a result, click the star (☆) before a wallet's address, or **Watch** in its card. A
filled star (★) opens the menu of your lists: a click adds the wallet to a list, takes it out, or makes a new list. **Only my
watchlist**, in Filters, keeps only the wallets you saved. The star over the chart keeps the whole result under *My analyses*.
Both live at `/me`, in the menu behind your address.

Your watchlist starts with one list, *Main*, and can hold up to twenty. A wallet can sit in several. At `/me` every list has
its own tab, where you rename or delete it (the first one stays). A [ready list](/docs/how-it-works#ready-lists) comes in whole:
**Follow** makes a copy with its wallets in it and turns on their bells while your account has bells left.

**Export** there gives the list on screen, or all of them, as CSV or TXT: each wallet's name and X account when known, its first
funder and the exchange behind it, its first transaction, your tags, its lists and the token you found it on.

A row in a list is the wallet and your tags for it. Click it for the wallet's card: who it is, its age and first funder, the other
analyses you saved it in, and its last 7 or 30 days on every token.

A wallet with its bell on also shows the buys (↑) and sells (↓) the alerts saw in the last 7 days and how long ago it last traded.
Its card adds its biggest buy in those days and how many alerts it sent you today. Counts start when the bell goes on, go when it
goes off, and are kept for 8 days.

## Your own tags

Each saved wallet takes tags you write yourself, in its row in your watchlist or in its card: a short word, then Enter. A tag on a
result's card adds the wallet to your watchlist. A tag is the wallet's name for you: your lists and Telegram alerts show it
instead of the address. Up to six per wallet, lowercased. They never mix with the tags an analysis computes, and they come out in
the CSV.

## Repeats

When a wallet in a result was **also** an early buyer in another analysis you saved, its row carries a chain link.

Its card names those analyses as links, with what the wallet made there. **seen before** under the chart shows those wallets.

!!! tip "Where a repeat comes from"
    It is the intersection of analyses saved to **your** account. Other people's saved analyses are never part of
    it, nothing leaves the server, and it costs no requests.

## Ask in Telegram

Send `/early <token address>` to [@tracced_bot](https://t.me/tracced_bot), or add the bot to a group and send the
same command there (in a group with several bots, `/early@tracced_bot`). In a private chat a pasted address is enough.
The answer is one message that fills in as the work goes:

- the pump window: the range already analysed on tracced for this token. For a token nobody has analysed, the trading range right
  before a pump since its migration from the launchpad, at most an hour back; another range is marked on the site. A token still on
  pump.fun's curve, or with no pump since its migration, gets an answer that says so;
- up to five early wallets worth a look: the most realized profit among those that sold at {{ s.tg_top_min_multiple }}x their entry
  or more on average and took at least ${{ s.tg_top_min_profit_usd }}. Bots, the creator and the launch's own bundles never make
  it. Each has its entry and exit caps, its PnL (what it took plus its unsold tokens at today's price, less what it put in) and ROI;
- the launch check: what it found on chain, each fact with a link to its proof, or how many early sales it checked. It never calls a
  launch clean.

*Open on tracced* opens the whole analysis.

A token already analysed answers at once. A new one is a real analysis: up to
{{ s.tg_runs_per_chat }} a day per chat or group, and {{ s.tg_runs_per_day }} a day from the bot for everyone, within
the site's own budget.

## Telegram alerts

Click the bell by a wallet in your watchlist or in its card: its buys and sells come to Telegram a few seconds after they happen.
To hear a whole list, open it and switch on *Alerts for this list*. If the live stream misses a trade, a check every minute finds it;
an alert a minute or more late says how long ago the trade was.

A wallet that trades more than 30 times a minute is taken for a bot: the rest of that minute is skipped. A wallet that signs over
{{ s.alerts_spam_per_day }} transactions in 24 hours, or that many a day on average over 7 days, can't get a bell; if it starts later,
its bell switches off, Telegram tells you, and you can try again in {{ s.alerts_spam_days }} days.

Only trades count: the wallet signs and pays SOL or a stablecoin for a token, or gets them for one, even through an app that pays the
network fee. Transfers, airdrops and token-for-token swaps stay silent, and so does anything under your minimum.

- **Connect**: on your watchlist page, press *Connect Telegram*, then *Start* in the bot. The link works once, for ten
  minutes, and only from the wallet you are signed in with. A chat already connected to another wallet stays with it:
  send /stop there first.
- **Choose**: buys, sells, and the smallest trade in dollars, the same for every wallet. Up to {{ s.alerts_max_wallets }} wallets per
  account, {{ s.alerts_per_hour }} alerts an hour, {{ s.alerts_per_day }} a day (UTC) and {{ s.alerts_per_wallet_day }} a day from any one
  wallet. Past a cap, one message says so and the rest of that hour or day is skipped.
- **Stop**: *Disconnect* on the watchlist page, or /stop in the bot.

An alert reads like a trades channel, three lines:

- the dot is the trade's size: 🟢 under ${{ '{:,}'.format(s.alerts_size_usd[0]) }}, 🟡 up to ${{ '{:,}'.format(s.alerts_size_usd[1]) }}, 🔴 from
  ${{ '{:,}'.format(s.alerts_size_usd[1]) }}. Then the token, a link to its chart here; 🆕 when the wallet held none of it,
  *bought more* when it did; for a sale, how much of the position is sold since its first buy, and how much this sale
  took: *sold 60% (+20%)*, then *sold all*; the market cap and the transaction;
- the token's address, only in the first alert about that token;
- whose trade: your tags for the wallet (its short address when it has none), and the amount.

The token's name, cap and the share sold come from our data provider, with a daily share of {{ '{:,}'.format(s.alerts_st_per_day) }}
requests for everyone. On a day that uses it up, alerts keep coming with the token's short address, without the cap and the sold share.

We keep the Telegram chat the alerts go to and your Telegram username; nothing else from Telegram.


## What other people see

Finished analyses are public. The home page shows a live feed of the tokens everyone analyzes, and anyone who opens
a token sees its analyzed ranges and can open them.

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

Without a wallet, the log holds nothing about you: visits are counted by a privacy-friendly analytics tool, which sets no
cookies and never gets a wallet address.

The Telegram bot logs each `/early`: the token, the answer, what a new analysis cost, and the chat it came from. A
group is recorded by its name; a private chat by the person's Telegram username (or first name when there is none).
That is how the owner sees what each chat uses of its daily limit. It is kept like the rest of this log.
