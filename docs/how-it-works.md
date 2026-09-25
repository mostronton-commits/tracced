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

The chart is Solana Tracker's candles. Some tokens trade for hours in a pool the source does not chart, often right
after they leave pump.fun, and that is usually the pump itself. Once a range is analyzed, the chart fills those
stretches with candles built from the trades the analysis already holds, so they cost nothing.

The range is always fetched in full. For each wallet's history the app then takes the cheaper of two **complete**
paths: the token's whole trade history, or each wallet's own trades. Completeness decides, not price. The line
above the table says which path ran and for how many wallets exits are known.

## How long it takes

A page of trades starts at a moment in time, so a long stretch of history can be cut into pieces and read eight
pieces at a time. A piece that turns out dense is split again while it is being read. Each wallet's own trades are
independent too, and eight wallets are fetched at once.

One run never spends more than its cap. A page or a wallet starts only when the most it could cost still fits, so
reading in parallel cannot push a run past its limit.

The result page stays light however many wallets it holds. The table arrives as numbers, the first hundred rows
are drawn and more on request, and sorting, filters, selection and export work on the numbers, so a result with
thousands of wallets opens and sorts at once, on a phone too.

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

Two events are marked on the price itself: **M** where trading left the launchpad, the DexScreener logo where
someone paid DexScreener to show the token's profile. Each badge sits above the candle where the event happened;
hover it for the time and the detail. **⇤ Launch** under the chart brings the first hours of trading into view.
Together the two events often explain the timing of a run.

The first comes from the token's own pools, which arrive in the response an analysis already pays for. The second
comes from DexScreener's public order list, which is free and costs no requests at all.

!!! warning "💸 Paid by someone, not necessarily the team"
    Anyone can pay for a token's profile. The badge says a payment happened and when, and nothing about who made
    it.

## Age and funding

Two facts are not trades, so they do not come from the trade feed: when a wallet made its first transaction ever,
and who sent it its first SOL. Those come from a Solana RPC node that keeps the whole history.

They are what `fresh` and `bundle` are built from. The first {{ s.age_lookups_max }} wallets by PnL, the ones
that made money on the token, are checked in the background after the table is already on screen. The check reads a
wallet's history back from its first buy in the range: for most wallets everything before that buy fits in one page,
and the last transaction on it is the wallet's first ever. A busy wallet is read to its very first transaction in one
more call. The SOL that arrived in that transaction names the funder; a wallet that apps pay fees for, like an account
in a trading app, often starts with tokens rather than SOL, so its first SOL is looked for among its first hundred
transactions. When it came later than that, the funder stays empty instead of guessed.

Any other wallet is checked the moment its card is opened, and the answer stays in the result for everyone.

A `bundle` is three or more wallets here whose first SOL came from the same wallet. An exchange or an app funds
thousands of wallets that have nothing to do with each other, at any time. So when a funder's latest 1,000
transactions fit into a single day, only the wallets it funded within half an hour of each other form a bundle:
that is how one operator creates wallets for a launch. When most of its wallets here were created that way, all of
them count, since here it is a bundler rather than an exchange. The rest stay in "Funded by", greyed out. In the PAID demo
most of what looked like bundles was one app's service wallet (154 of the buyers) and Coinbase (33). On another
token, one wallet created 200 wallets in 41 minutes, and all of them bought within minutes of the launch: that is
still a bundle, however busy its funder.

Until the check reaches a wallet, `fresh`, `bundle` and the filters that hide them do not know about it yet. Below
the first {{ s.age_lookups_max }} they stay unknown unless a card is opened: a bundle there counts only the wallets
that were checked.

These lookups have a monthly budget of their own. When it runs out, the check pauses, the page says so, and it
picks up again next month. A wallet checked before costs nothing.

## The wallet card

Click a wallet's name. The card shows, top to bottom:

1. who it is, when Solana Tracker knows (a star for a KOL, its X account, the app it trades through), and next to
   the address its age, like `94d`, and who sent it its first SOL; hover either for the detail. A wallet outside
   the first {{ s.age_lookups_max }} shows `…` for a moment while its card checks it; when that cannot happen (no
   wallet connected, the day's card checks used up) it shows `?` or `1k+ tx`: its age stays unknown rather than
   guessed;
2. its tags, ours and your own;
3. how it trades on every token over the last 7 or 30 days: realized PnL and its curve, win rate with wins and
   losses, volume, buys and sells, best and worst day, drawdown, how its closed positions ended, the hours it
   trades, and its latest tokens;
4. its position in this token, with its ROI;
5. the analyses you saved where it was early too, if any;
6. its trades on this token.

ROI, in the card and in its own column of the table, is the average exit cap over the average entry cap, buys
before the range included: `2×` is +100%, `61.5×` is +6,050%. Hover it for the percent.

The 30 days are counted by tracced from the wallet's own swaps, the same way as the table: average cost, and
profit only on tokens the wallet actually bought. A position is closed once 99% of it is sold. Win rate is the
closed positions that made money, out of all closed ones.

A token the wallet sold in those days without buying it there is left out and counted apart. It came by transfer
or was bought earlier, so its cost is unknown, and a transfer is not a profit.

!!! info "📊 Why not the numbers Solana Tracker already sells"
    Their PnL comes from a formula they do not publish, and their win rate over a period counts profitable days,
    not positions. The card shows numbers you can rebuild from the swaps yourself.

Nothing in the card is computed for wallets nobody opens. The swaps are read the moment a card opens, a few
requests with a connected wallet, and the answer is kept for a day, so opening the same wallet again is free for
everyone. The 7-day view is counted from the same swaps and costs nothing extra.
