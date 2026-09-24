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

## How long it takes

A page of trades starts at a moment in time, so a long stretch of history can be cut into pieces and read eight
pieces at a time. A piece that turns out dense is split again while it is being read. Each wallet's own trades are
independent too, and eight wallets are fetched at once.

One run never spends more than its cap. A page or a wallet starts only when the most it could cost still fits, so
reading in parallel cannot push a run past its limit.

!!! warning "🔧 Two defects in the source, fixed on the way in"
    The trade feed silently drops about 1% of swaps under naive pagination. We overlap the cursor and
    de-duplicate by transaction. About one trade in a thousand arrives with a broken token amount; it is repriced
    from the median price of its minute. The dollar amounts are never touched.

## Dollars or SOL

The `USD | SOL` switch above the table changes the unit of every amount that came from a swap: spent, sold, made.

Nothing is converted at today's rate. Both figures were recorded by the same swap, so the SOL amount is what
actually moved on chain and the dollar amount is what it was worth then. Profit is counted the same way in both
units, from the cost of the tokens actually sold, so the two never disagree.

What a wallet still holds stays in dollars. It is a valuation at a later price, not a swap that happened.

## What the token itself did

Two events are marked on the price itself and named in a line above the chart: **M** where trading left the
launchpad, **$** where someone paid DexScreener to show the token's profile. Together they often explain the timing
of a run.

The first comes from the token's own pools, which arrive in the response an analysis already pays for. The second
comes from DexScreener's public order list, which is free and costs no requests at all.

!!! warning "💸 Paid by someone, not necessarily the team"
    Anyone can pay for a token's profile. The line says a payment happened and when, and nothing about who made
    it.

## Age and funding

Two facts are not trades, so they do not come from the trade feed: when a wallet made its first transaction ever,
and who sent it its first SOL. Those come from a Solana RPC node with the full signature index.

They are what `fresh` and `bundle` are built from, and they fill in quietly after the table is already on screen.
These lookups have a monthly budget of their own. When it runs out, the check pauses, the page says so, and it
picks up again next month. A wallet checked before costs nothing.

## The wallet card

Click a wallet's name. The card shows, top to bottom:

1. its tags, ours and your own;
2. who it is, only when Solana Tracker names it: a KOL, an X handle, a trading platform, with the source written
   next to it;
3. what it did on this token;
4. its last 30 days on every token it traded;
5. its first transaction and who sent it its first SOL;
6. its trades on this token.

The 30 days are counted by tracced from the wallet's own swaps, the same way as the table: average cost, and
profit only on tokens the wallet actually bought. A position is closed once 99% of it is sold. Win rate is the
closed positions that made money, out of all closed ones.

A token the wallet sold in those days without buying it there is left out and counted apart. It came by transfer
or was bought earlier, so its cost is unknown, and a transfer is not a profit.

!!! info "📊 Why not the numbers Solana Tracker already sells"
    Their PnL comes from a formula they do not publish, and their win rate over a period counts profitable days,
    not positions. The card shows numbers you can rebuild from the swaps yourself.

Loading the 30 days takes a few requests and a connected wallet. The answer is kept for a day, so opening the same
wallet again is free for everyone.
