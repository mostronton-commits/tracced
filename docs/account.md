# Your account, watchlist and repeats

## Signing in

A Solana wallet signs a short message with a one-time code. There is no transaction, no fee, no password and no
e-mail. That signature is the account.

Supported wallets: Phantom, MetaMask and Rabby.

## Watchlist and saved analyses

Tick wallets in a result and press **+ Watchlist** to keep them. **Save analysis** keeps the whole result. Both
live at `/me`, both export to CSV and TXT, and both are two-way: clicking the star again removes the item.

Each saved wallet takes **your own tags**: type a short word and press Enter, click a tag to remove it. Up to six
per wallet, lowercased so `Insider` and `insider ` do not become two different things. They are yours, they never
mix with the tags the analysis computes, and they come out in the CSV.

## Repeats

This is the part worth understanding. When a wallet in a result was **also** an early buyer in another analysis
you saved, its row carries a **⛓**. Clicking it opens the wallet's card, which names those analyses — the token,
the range, and what the wallet made there — as links.

The chip above the table filters the list down to those wallets.

It is computed by intersecting the results of the analyses saved to your own account. Analyses saved by other
people are never part of it, nothing leaves the server, and no request is spent on it.

## What other people can see

Finished analyses are public: the home page lists what everyone analysed, and any result opens for anyone. **Who
ran an analysis is never shown.** Your watchlist, your notes and your saved list are yours alone.
