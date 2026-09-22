# How it works

Every figure on a result page comes from a swap that happened. Here is the path from the chain to the table.

## The range picks wallets, not numbers

The range decides **which wallets appear**. Their numbers come from all of that wallet's trades on the token:
before the range, inside it, after it.

So a wallet can show a bigger total than what it spent in your range. It was buying earlier, and the `pre-range`
tag says so.

The scope switch above the table recounts the same stored trades up to 24 or 48 hours after the range. It costs
nothing: the trades are already here.

## Where the numbers come from

Raw swaps from the [Solana Tracker Data API](https://www.solanatracker.io/data-api). Market cap is the swap price
times the token supply, so an entry cap is the cap at that exact trade.

The range is always fetched in full. For each wallet's history the app then takes the cheaper of two **complete**
paths: the token's whole trade history, or each wallet's own trades. Completeness decides, not price. The line
above the table says which path ran and for how many wallets exits are known.

!!! warning "🔧 Two defects in the source, fixed on the way in"
    The trade feed silently drops about 1% of swaps under naive pagination. We overlap the cursor and
    de-duplicate by transaction. About one trade in a thousand arrives with a broken token amount; it is repriced
    from the median price of its minute. The dollar amounts are never touched.

## Dollars or SOL

The `USD | SOL` switch in the footer changes the unit of every amount that came from a swap: spent, sold, made.

Nothing is converted at today's rate. Both figures were recorded by the same swap, so the SOL amount is what
actually moved on chain and the dollar amount is what it was worth then. Profit is counted the same way in both
units, from the cost of the tokens actually sold, so the two never disagree.

What a wallet still holds stays in dollars. It is a valuation at a later price, not a swap that happened.

## Age and funding

Two facts are not trades, so they do not come from the trade feed: when a wallet made its first transaction ever,
and who sent it its first SOL. Those come from a Solana RPC node with the full signature index.

They are what `fresh` and `bundle` are built from, and they fill in quietly after the table is already on screen.
