# The project

Built in Ukraine for the Solana Crypto World's Fair, 2026. This is the argument behind the product, for anyone
deciding whether it is worth their time.

## The question

Every Solana run ends the same way: who was already in? The evidence is public but unreadable. One pump hides tens
of thousands of swaps, so traders either scroll a block explorer by hand or buy someone else's "smart money"
ranking and trust a score they cannot check.

tracced answers it in two clicks. Paste a token, mark the pump on the chart, and read every wallet that bought
inside that range: entry market cap, dollars in, exits, realized profit, hold time, who funded it.

Nothing is scored. Every row opens as a transaction on Solscan.

## Three steps

1. **Paste a token.** Any Solana mint. The chart is drawn in market cap, not price.
2. **Mark the pump.** Two clicks set the range, from where buying starts to where it takes off. Detected pumps are
   offered as hints; the call is yours.
3. **Read the wallets.** Everyone who bought inside it, with what they paid, sold, still hold, and who funded them.
   Export as CSV, TXT or JSON.

## Proof it is complete

Cursor-paged trade feeds drop trades silently. The cursor is exclusive and trade times are whole seconds, so
everything after the first trade of a boundary second disappears. On one token that was about 1% of all swaps,
including buys of several hundred thousand dollars.

We found it by comparing our set against the pool's own signatures on chain, fixed the paging, and now re-read the
boundary second every time.

The same audit found a defect in the source data: roughly one trade in a thousand arrives with a token amount
shifted by orders of magnitude. The dollar figure is right, the derived price is not. Those trades are repriced at
the market rate of their minute, and the count is shown with the results.

!!! info "📏 What that costs to prove"
    On the demo token the whole trade history had to be reconstructed, 489,000 swaps, before a single exit could be
    called complete. It is, for all 4,634 wallets across the three ranges, and 370 of them share a funding source.
    Those are not user numbers. They are the size of the claim being checked.

## What it refuses to do

No wallet scores and no "smart money" badge. The card's win rate is a count, not a score: the wallet's closed
positions that made money, out of all its closed ones, counted from its own swaps by the rule in
[How it works](/docs/how-it-works#the-wallet-card).

Tags are facts with fixed definitions you can read: bought within 60 seconds of creation, wallet younger than 24
hours, funded by the same wallet as others in the list. Each is derived from trades you can open yourself. The
judgement stays with the person.

No tracking by third parties. Visits are counted with Umami, which sets no cookies and never gets a wallet address.
When you connect a wallet, tracced's own server also keeps what that wallet does here and what each step cost, so
the owner can see how the product is used. None of it goes to anyone else:
[what is recorded](/docs/account#what-we-record).

## Where to go next

| | |
|---|---|
| The demo | [open it, no sign-up]({{ '/token?mint=' ~ demo_token if demo_token else '/' }}) |
| The code | [github.com/mostronton-commits/tracced](https://github.com/mostronton-commits/tracced) |
| Updates | [@tracced_xyz](https://x.com/tracced_xyz) |
| A bug, an idea, a question | [Write to us](/feedback) |
| Next to the terminals | [where this sits beside Axiom and GMGN](/docs/compare) |
