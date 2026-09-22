# How an analysis works

## The range selects wallets, not numbers

The range you mark decides **which wallets appear** in the table. The numbers for each of them come from all of
that wallet's trades on the token — before the range, inside it, and after it. That is why a wallet can show a
bigger total than what it spent inside your window: it was buying earlier too, and the `pre-range` tag says so.

The scope switch above the table recounts the same stored trades up to 24 or 48 hours after the range instead of
up to the moment of the analysis. It costs no requests: the trades are already there.

## Where the numbers come from

Raw swaps from the [Solana Tracker Data API](https://www.solanatracker.io/data-api). Market cap is the swap price
multiplied by the token supply, so an entry or exit cap is the cap at that exact trade.

The range is always fetched in full. For each wallet's history the app then takes the cheaper of two **complete**
paths: the whole trade history of the token, or each wallet's own trades. Completeness decides, not price — and
the line above the table says which path was taken and for how many wallets exits are known.

Two defects in the source were found and are corrected on the way in. The trade feed silently drops about 1% of
swaps under naive pagination, which is fixed by overlapping the cursor and de-duplicating by transaction. About
one trade in a thousand arrives with a broken token amount, which is repriced from the median price of its minute;
the USD amounts are never touched.

## Dollars or SOL

The `USD | SOL` switch in the footer changes the unit of every amount that came from a swap: what a wallet spent,
what it sold for, what it made. Nothing is converted at today's rate — both figures were recorded by the same swap,
so the SOL amount is what actually moved on chain at that moment and the dollar amount is what it was worth then.
Profit is counted the same way in both units, from the cost of the tokens actually sold, so the two never disagree.

What a wallet still holds is the one figure that stays in dollars. It is a valuation at a later price, not a swap
that happened, and there is no SOL amount on chain to show for it.

A result saved before tracced started recording SOL amounts has no SOL figures to show. Those cells stay in
dollars and are dimmed, so the page never dresses a dollar number up as a SOL one.

## Wallet age and funding

Two facts do not come from the trade feed at all, because they are not trades: when a wallet made its very first
transaction, and who sent it its first SOL. Those come from a Solana RPC node that keeps the full signature index.
They are what the `fresh` and `bundle` tags are built from, and they are filled in the background after the table
is already on screen.
