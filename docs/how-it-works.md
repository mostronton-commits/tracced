# How it works

Every figure on a result page comes from a swap that happened. Here is the path from the chain to the table.

## The range picks wallets, not numbers

The range decides **which wallets appear**. Their numbers come from all of that wallet's trades on the token:
before the range, inside it, after it.

So a wallet can show a bigger total than what it spent in your range: it was buying earlier too.

The scope switch above the table recounts the same stored trades up to 24 or 48 hours after the range. It costs
nothing: the trades are already here.

## Fresh pumps on the home page

Tokens created in the last {{ s.fresh_hours|int }} hours that reached a real market cap and are really traded.
Clones with huge caps and no trading, and charts bought by one bot, are filtered out. Biggest peak first; the list
is refreshed at most every {{ s.fresh_refresh_min|int }} minutes. A click opens the chart, where you mark the range.

## Where the numbers come from

Every row is a swap recorded on chain. Market cap is the swap price times the token supply, so an entry cap is the
cap at that exact trade.

The chart can have a gap, often right after a token leaves pump.fun, and that is usually the pump itself. Once a
range is analyzed, the chart fills the gap with candles built from that analysis's own trades.

The range is always read in full. The line above the table says for how many wallets exits are known.

## How long it takes

A busy token takes seconds, not minutes.

The result page stays light however many wallets it holds. The table arrives as numbers, the first hundred rows
are drawn and more on request, and sorting, filters, selection and export work on the numbers, so a result with
thousands of wallets opens and sorts at once, on a phone too.

!!! info "🔧 Checked on the way in"
    Every history is checked for completeness, and trades that arrive with a broken token amount are repaired;
    the count is shown with the results. The dollar amounts are never touched.

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

!!! warning "💸 Paid by someone, not necessarily the team"
    Anyone can pay for a token's profile. The badge says a payment happened and when, and nothing about who made
    it.

## Age and funding

Two facts are not trades: a wallet's age is its first transaction ever, and its funder is whoever sent it its first
SOL. They are what `fresh` and `bundle` are built from.

The first {{ s.age_lookups_max }} wallets by PnL, the ones that made money on the token, are checked in the
background after the table is already on screen. Any other wallet is checked the moment its card is opened, and the
answer stays in the result for everyone. When a funder cannot be found, it stays empty instead of guessed.

A `bundle` is three or more wallets here whose first SOL came from the same wallet. An exchange or an app funds
thousands of wallets that have nothing to do with each other, at any time. From such a busy funder, only the wallets
it funded close together in time form a bundle: that is how one operator creates wallets for a launch. The rest stay
in "Funded by", greyed out. In the PAID demo most of what looked like bundles was one app's service wallet (154 of
the buyers) and an exchange (33). On another token, one wallet created 200 wallets in 41 minutes, and all of them bought
within minutes of the launch: that is still a bundle, however busy its funder.

When the first SOL came straight from a known exchange, "Funded by" names the exchange instead of an address. An
exchange never makes a bundle.

When nearly all of the top {{ s.age_lookups_max }} by PnL are fresh or in bundles, one hand ran the launch and little
in the list is organic buying. A red mark above the chart says which kind:

| Word | The top is made of |
|---|---|
| Rigged | …and the token's creator bought in the range too |
| Bundled | mostly wallets of one funder, few of them fresh |
| Staged | mostly fresh wallets, made for the launch, without one funder |
| Cabal | both at once: fresh wallets from shared funders |

Above the table, tracced lists up to three things it found that a terminal does not show, each only when it is big
enough to matter, and each a click into exactly those wallets:

- operators: wallets that share a funder;
- the token's creator bought in the range;
- fresh wallets;
- wallets funded straight from exchanges;
- wallets early in your other pumps (with a wallet connected);
- the top 10 took most of the profit.

Until the check reaches a wallet, `fresh`, `bundle` and the filters that hide them do not know about it yet. Below
the first {{ s.age_lookups_max }} they stay unknown unless a card is opened: a bundle there counts only the wallets
that were checked. When the check is paused, the page says so.

## The wallet card

Click a wallet's name. The card shows, top to bottom:

1. who it is, when the wallet is publicly identified (a star for a KOL, its X account, the app it trades through),
   and next to the address its age, like `94d`, and who sent it its first SOL; hover either for the detail. A wallet outside
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

!!! info "📊 Why not a third-party PnL"
    Third-party PnL often comes from a formula nobody publishes, and a "win rate" over a period can count
    profitable days, not positions. The card shows numbers you can rebuild from the swaps yourself.

A card someone already opened today opens free for everyone. The 7-day view is counted from the same swaps.

## The AI agent

The agent on a result page reads that analysis and nothing else. Open it and pick a question (who sold the top,
whether it was a bundled launch, who is still holding) or ask your own, in any language. **Summary of this pump**
writes three cards: what happened in the range, what a buyer should weigh, and whose wallets stand out by the
method written under the card. A wallet it names opens its card.

It reads only what the site computed from the table and does not compute a number of its own. Before an answer
reaches the page, every number and wallet in it is checked against the analysis, and a line that fails is dropped.
It never tells you to buy or sell, never predicts a price and never calls a wallet good or a token safe.

It answers only about the analysis it is on. Anything else, including a request to change how it works, gets one
fixed reply. The agent needs a connected wallet; cards someone has already opened are kept, so opening them again is
free for everyone.{% if not assistant_on %}

!!! warning "🤖 The agent is off on this server"
    It needs a model key that this deployment does not have yet.
{% endif %}
