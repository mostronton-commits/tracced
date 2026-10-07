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

## Ready lists

Two lists of ten wallets on the home page, for when you have no token to start from:

- **KOLs · 30 days**: known traders with a public X account, by the profit they realized in the last 30 days.
- **Top traders · 30 days**: the most profitable wallets of the last 30 days that trade at a human pace. The top of
  Solana Tracker's board is bots and market makers, so a wallet stays only with up to 1,500 trades a month, 10 or more
  active days, a win rate between 30 and 90 %, and a profit at most twenty times what it put in (beyond that, the
  profit comes from tokens it never bought).

The rankings and their sums are Solana Tracker's, from each wallet's own trades, refreshed every
{{ s.ready_lists_refresh_hours|int }} hours. A row opens the wallet's card, which counts its 30 days with tracced's own
ledger, so the two can differ a little. **Follow 10 wallets** puts the ten in your watchlist, in a list of the same
name, with their bells on while your account has bells left. Your copy keeps the wallets you took; the ranking moves
on without it. Past results, not advice.

## The numbers under the chart

One strip under the chart, a number and a word each. A click on a number shows exactly those wallets, or sorts by it.

Always there:

- **bought**: the wallets that bought in the range, the list below. Its **i** says how they were counted.
- **spent**: what they spent in the range.
- **sold out**: the share that sold 99% or more of what they bought.
- **holding**: the share that sold less than half.
- **best ROI**: the highest average exit cap ÷ average entry cap among them.

Then up to four findings, each only when it says something:

- **creator bought**: the token's creator bought in the range, and how much.
- **bundled**: wallets that share a funder made that share of the range's buying (shown from 10%).
- **fresh**: of the wallets checked for age, the share under a day old when they bought (shown from 10 wallets and
  10%).
- **to top 10**: the ten most profitable wallets' share of all the profit made (shown from 20 wallets in profit and
  40%).
- **seen before**: with a wallet connected, wallets that were early in your other saved analyses too (shown from 3).
- **from exchanges**: of the wallets whose first funder is known, the share funded straight from an exchange (shown
  from 10 wallets and 5%).
- **in profit**: wallets with a realized profit (shown from 20 wallets).

## Where the numbers come from

Every row is a swap recorded on chain. Market cap is the swap price times the token supply, so an entry cap is the
cap at that exact trade.

The chart can have a gap, often right after a token leaves pump.fun, and that is usually the pump itself. Once a
range is analyzed, the chart fills the gap with candles built from that analysis's own trades.

The range is always read in full. The **i** after the counts above the chart says for how many wallets exits are
known, and how many traded in the range but stay out of the table (too small, or only sold); it turns into **!** when
exits are not known for every wallet.

## How long it takes

A busy token takes seconds, not minutes.

The result page stays light however many wallets it holds. The table arrives as numbers, the first hundred rows
are drawn and more on request, and sorting, filters and export work on the numbers, so a result with
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
SOL. They are what `fresh` and `bundle` are built from. The same check reads the transaction right before the wallet's
first buy here: when it is a week old or older, the wallet slept until this token and gets `dormant`.

The first {{ s.age_lookups_max }} wallets by PnL, the ones that made money on the token, are checked in the
background after the table is already on screen. Any other wallet is checked the moment its card is opened, and the
answer stays in the result for everyone. When a funder cannot be found, it stays empty instead of guessed.

A `bundle` is three or more wallets here whose first SOL came from the same wallet. An exchange or an app funds
thousands of wallets that have nothing to do with each other, at any time. From such a busy funder, only the wallets
it funded close together in time form a bundle: that is how one operator creates wallets for a launch. The rest stay
out of any bundle. In the PAID demo most of what looked like bundles was one app's service wallet (154 of
the buyers) and an exchange (33). On another token, one wallet created 200 wallets in 41 minutes, and all of them bought
within minutes of the launch: that is still a bundle, however busy its funder.

When the first SOL came straight from a known exchange, the wallet's card says "funded by" and the exchange's name
instead of an address. From an exchange, as from any busy funder, only wallets created close together make a bundle.
Funders our own list of exchange wallets does not know are looked up in the labels of [InsightX](https://insightx.network):
the card then says the funder is an exchange, an app or a casino, such a funder makes no bundle, and its wallets count
among those funded from exchanges in the strip under the chart. The names stay with InsightX.

In the table a bundle's tag takes one colour per funder, so two bundles side by side are told apart; a click on the tag
shows that bundle alone.

When nearly all of the top {{ s.age_lookups_max }} by PnL are fresh or in bundles, one hand ran the launch and little
in the list is organic buying. A red word, first among the findings under the chart, says which kind:

| Word | The top is made of |
|---|---|
| Rigged | …and the token's creator bought in the range too |
| Bundled | mostly wallets of one funder, few of them fresh |
| Staged | mostly fresh wallets, made for the launch, without one funder |
| Cabal | both at once: fresh wallets from shared funders |

Until the check reaches a wallet, `fresh`, `bundle` and the filters that hide them do not know about it yet. Below
the first {{ s.age_lookups_max }} they stay unknown unless a card is opened: a bundle there counts only the wallets
that were checked. When the check is paused, the page says so.

## The wallet card

Click a wallet's address, or anywhere else in its row. The chart mark before it, which comes out with the star when the
pointer is over the row, puts its buys and sells on the chart instead, in the wallet's own colour. In the card, a click on
the address copies it. The card shows, top to bottom:

1. who it is, when the wallet is publicly identified (a star for a KOL, its X account, the app it trades through),
   and next to the address its age, like `94d old`, and who sent it its first SOL (`funded by …`); hover either for
   the detail. A wallet outside
   the first {{ s.age_lookups_max }} shows `…` for a moment while its card checks it; when that cannot happen (no
   wallet connected, the day's card checks used up) it shows `?` or `1k+ tx`: its age stays unknown rather than
   guessed;
2. its tags, ours and your own;
3. how it trades on every token over the last 7 or 30 days: realized PnL and its curve, win rate with wins and
   losses, volume, buys and sells, how many tokens and how many still open, average hold, best day, drawdown, how
   its closed positions ended and the hours it trades. Point at the PnL curve for any day's result and the running total
   after it;
4. the analyses you saved where it was early too, if any;
5. its trades, with a switch: on this token, its numbers here (bought, sold, PnL, ROI, held) and every trade; on all
   tokens, the latest tokens it traded. Click one of them: its chart opens right there, on the hours of the wallet's
   trades, with its buys and sells marked. The trades come with the 30 days; the candles cost what any chart costs.

ROI, in the card and in its own column of the table, is the average exit cap over the average entry cap, buys
before the range included: `2×` is +100%, `61.5×` is +6,050%. Hover it for the percent.

The 30 days are counted by tracced from the wallet's own swaps, the same way as the table: average cost, and
profit only on what the wallet actually bought. Profit counts on the day of the sale, as a broker counts it: a token
sold in those days counts in full, at what the wallet really paid for it, even when the buy came earlier. For such a
token the card reads the wallet's earlier trades of it too, up to {{ s.profile_history_tokens }} tokens with the biggest sales. A
position is closed once 99% of it is sold; win rate is the positions closed in those days that made money, out of all
of them.

A token sold in those days with no buy found is left out and counted apart: it came by transfer, or its buy is
older than what the card reads, so its cost is unknown, and a transfer is not a profit.

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

Ask who a wallet is, or who owns it, and the first line comes from tracced, not from the model: its X account or that
it has none, a KOL, a known bot or an exchange when the labels say so, a bot-like trader when its trades here look like
one, otherwise a trader, then the app it trades through and the exchange its first SOL came from.

It knows your watchlist too: when you ask, it sees which of your saved wallets bought in this range, the lists that hold
them and your own tags for them, so "which of my wallets are here?" or "what did my insiders do?" has an answer. When
some of them did buy here, the panel offers that question as a button. It sees only your own watchlist, and only when
you ask.

It answers only about the analysis it is on. Anything else, including a request to change how it works, gets one
fixed reply. The agent needs a connected wallet; cards someone has already opened are kept, so opening them again is
free for everyone. Questions go only to AI model hosts whose policy is not to collect them or train on them; do not
type anything personal into it.{% if not assistant_on %}

!!! warning "🤖 The agent is off on this server"
    It needs a model key that this deployment does not have yet.
{% endif %}
