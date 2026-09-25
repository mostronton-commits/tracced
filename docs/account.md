# Your account

A Solana wallet signs a one-time message. That signature is the account: no password, no e-mail, no transaction,
no fee.

Works with Phantom, MetaMask and Rabby.

## Lists and saved analyses

Tick wallets in a result and press **+ Add to list**, then pick a list or name a new one. The star in a wallet's
card opens the same menu for that one wallet: it shows which lists hold it, and a click adds or removes it.
**Save analysis** keeps the whole result under *My analyses* at `/me`.

You start with one list, *Watchlist*, and can keep up to twenty: one per strategy, per token family, per person you
follow. A wallet can sit in several. At `/me` every list has its own tab with its count, where you rename or delete
it (the first one stays). **Export** there gives the list on screen, or all of them, as CSV or TXT, and the CSV
says which lists hold each wallet.

## Your own tags

Each saved wallet takes tags you write yourself, at `/me` or in the wallet's card. Type a short word, press Enter.
Click a tag to remove it. Tagging a wallet in its card adds it to your *Watchlist*, because a tag is a reason to
watch it.

Up to six per wallet, lowercased, so `Insider` and `insider ` do not become two different things. They never mix
with the tags an analysis computes, and they come out in the CSV.

## Repeats

When a wallet in a result was **also** an early buyer in another analysis you saved, its row carries a chain link.

Click it and the wallet's card names those analyses — token, range, and what the wallet made there — as links.
The chip above the table filters the list down to those wallets.

!!! tip "🔗 Where a repeat comes from"
    It is the intersection of analyses saved to **your** account. Other people's saved analyses are never part of
    it, nothing leaves the server, and it costs no requests.

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
- what you send through **Write to us**, with the page you came from;
- what each step cost in data credits;
- once a day while the wallet is active: public facts about it from the chain — its age, its SOL balance, its last
  30 days of trading as counted by tracced's own ledger, and what Solana Tracker knows about it (a KOL name or an X
  account, if it has one).

Only the owner sees it. It is never sold or shared, and it is kept for about a year. Signing out stops it.

Without a wallet, the log holds nothing about you: visits are counted by Umami, which sets no cookies and never gets
a wallet address.
