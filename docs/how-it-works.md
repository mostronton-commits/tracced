# How it works

Every figure on a result page comes from a swap that happened. Here is the path from the chain to the table.

## The range picks wallets, not numbers

The range decides **which wallets appear**. Their numbers come from all of that wallet's trades on the token: before the
range, inside it, after it. So a wallet can show a bigger total than what it spent in your range: it was buying earlier too.

## Fresh pumps on the home page

Tokens created in the last {{ s.fresh_hours|int }} hours with a market cap of ${{ (s.fresh_min_mcap / 1000)|int }}K or more,
${{ (s.fresh_min_liquidity / 1000)|int }}K of liquidity, ${{ (s.fresh_min_vol_24h / 1000)|int }}K traded in a day and {{ s.fresh_min_holders|int }}+ holders.
Clones with huge caps and no trading, and charts bought by one bot, are filtered out. A tile's size is its market cap now,
its colour how close it still is to its peak. The list is refreshed at most every {{ s.fresh_refresh_min|int }} minutes. A
click opens the chart.

## Ready lists

**Top traders**: up to ten wallets that made the most last month and trade like people, for when you have no token to start
from. On the 1st of the month (UTC) the next list is counted.

The candidates are known KOLs and the best of public PnL rankings. How much each one made, tracced counts itself, from
the wallet's own swaps over the month, the same way as its card. A sale with no purchase under it is left out: the rankings
count such tokens as profit. A swap of a memecoin into a tokenized stock (RACE, SKHY, SPCX) is a real exit and counts at the
stock's price.

A wallet is left out when, in the month, it:

- made more than {{ '{:,}'.format(s.ready_human.max_swaps) }} swaps or traded more than {{ s.ready_human.max_tokens }} tokens;
- closed fewer than {{ s.ready_human.min_closed }} positions, or won less than {{ s.ready_human.win_rate[0] }} % or more than {{ s.ready_human.win_rate[1] }} % of them;
- held less than {{ s.ready_human.min_hold_min }} minutes on average, or closed most positions within a minute;
- started trading less than {{ s.ready_human.min_age_days }} days before the month began;
- is marked a bot, an exchange or an arbitrageur.

Of the rest, the list keeps those that made more than ${{ '{:,}'.format(s.ready_min_pnl|int) }}, best first.

**Best ROI** ranks the same kind of people by profit on what they bought in the month (at least
${{ '{:,}'.format(s.ready_roi_min_invested|int) }} in and ${{ '{:,}'.format(s.ready_roi_min_pnl|int) }} made).

A list opens with a connected wallet. **Follow** puts a copy in your watchlist with the bells on while your account has bells
left. The copy is yours: next month's list does not change it.

## The numbers under the chart

Six cells. A click on one that can be clicked shows exactly those wallets, or sorts by it.

- **wallets bought**: the list below. Its **i** says how they were counted, and turns into **!** when exits are not known
  for every wallet.
- **spent**: what they spent inside the range.
- **realized profit**: what they took out above what it cost them, profits against losses on the scale.
- **in profit**: the share with a realized profit.
- **sold out**: the share that sold 99% or more of what they bought.
- **the token's main finding**, the first of these that holds:

| Finding | Shown when |
|---|---|
| organised launch | the launch check found facts (below) |
| creator bought | the token's creator bought in the range |
| bundled | wallets that share a funder made 10% or more of the buying |
| fresh | 10 or more wallets, and 10% of those checked, were under a day old when they bought |
| profit to the top 10 | the ten best took 40% or more of the profit, with 20+ wallets in profit |
| seen before | with a wallet connected, 3+ wallets were early in your other saved analyses too |
| from exchanges | 10 or more wallets, and 5% of those with a known funder, were funded straight from an exchange |

With nothing to say, the cell shows **still holding**: the share that sold less than half.

When nearly all of the top {{ s.age_lookups_max }} by PnL are fresh or in bundles, one hand ran the launch and little in the
list is organic buying. A red word takes the cell:

| Word | The top is made of |
|---|---|
| Rigged | …and the token's creator bought in the range too |
| Bundled | mostly wallets of one funder, few of them fresh |
| Staged | mostly fresh wallets, made for the launch, without one funder |
| Cabal | both at once: fresh wallets from shared funders |

## Where the numbers come from

Every row is a swap recorded on chain. Market cap is the swap price times the token supply, so an entry cap is the cap at that
exact trade. The range is always read in full.

The chart can have a gap, often right after a token leaves pump.fun, and that is usually the pump itself. Once a range is
analyzed, the chart fills the gap with candles built from that analysis's own trades.

**Held** is how long a wallet held what it sold, on average, weighted by amount. A wallet that sells $999 of its $1,000 two
seconds after buying and keeps the last $1 for a day held about a minute and a half. What it still holds is not counted.

**ROI** is the average exit cap over the average entry cap, buys before and after the range included: `2×` is +100%. Hover it
for the percent.

!!! info "Checked on the way in"
    Every history is checked for completeness, and trades that arrive with a broken token amount are repaired. The dollar
    amounts are never touched.

## Dollars or SOL

The `USD | SOL` switch over the chart changes the unit of every amount that came from a swap. Nothing is converted at today's
rate: both figures were recorded by the same swap, so the two never disagree. What a wallet still holds stays in dollars: it
is a valuation at a later price, not a swap.

## What the token itself did

Two events are marked on the chart: **Migrated** where trading left the launchpad, the DexScreener logo where someone paid
DexScreener to show the token's profile. Hover one for the time. **First hours** on the chart brings the start of trading into
view.

!!! warning "Paid by someone, not necessarily the team"
    Anyone can pay for a token's profile. The badge says a payment happened and when, nothing about who made it.

## Age and funding

A wallet's age is its first transaction ever, and its funder is whoever sent it its first SOL. They are what `fresh` and `bundle`
are built from. When the transaction right before a wallet's first buy here is a week old or older, it slept until this token and
gets `dormant`.

The first {{ s.age_lookups_max }} wallets by PnL are checked in the background after the table is on screen. Any other wallet
is checked when its card is opened, and the answer stays in the result for everyone. A funder that cannot be found stays empty
instead of guessed. Until the check reaches a wallet, `fresh`, `bundle` and the filters that hide them do not know about it.

A `bundle` is three or more wallets here whose first SOL came from the same wallet. An exchange or an app funds thousands of
unrelated wallets, so from such a busy funder only wallets funded close together in time form a bundle: that is how one operator
creates wallets for a launch. In the table a bundle's tag has one colour per funder; a click shows that bundle alone.

When the first SOL came straight from a known exchange, the card names it. Funders our own list does not know are looked up in
address labels: an exchange, an app or a casino makes no bundle, and its wallets count among
those funded from exchanges.

## Organised launches

After the table, tracced checks how the token was launched, from two free sources, and adds only facts with a proof. There is
no score.

- **Jito bundles of the first {{ (s.launch_window_s / 60)|int }} minutes.** Early sales are looked up at Jito: wallets that
  bought in one bundle get `own-bundle`, those in the bundle that created the token get `launch-bundle`.
- **The creator fee.** pump.fun lets a creator send the fee from every trade to another wallet. tracced reads where it went and
  how much SOL it has paid out.

Such wallets are never in the ready lists. Wallets tied to a launch only by later shared signatures are not caught yet.

## The wallet card

Click a wallet's address. The chart mark that comes out on its row puts its buys and sells on the chart instead. On a phone a
tap opens the card from below; a tap above it or pulling it down closes it. Top to bottom, the card shows:

1. who it is, when publicly identified, its age and who sent it its first SOL. A wallet outside the first
   {{ s.age_lookups_max }} shows `…` while its card checks it, and `?` or `1k+ tx` when that cannot happen;
2. its tags, ours and your own;
3. this token: its result, its trip from entry to exit, its buys and sells, every trade on request;
4. the last 7 or 30 days on every token: PnL and its curve, win rate, volume, average hold, best day, drawdown, how positions
   ended, the hours it trades, and its latest and best tokens. A click on a token opens its chart right there, with the
   wallet's trades marked;
5. the analyses you saved where it was early too.

**Bought** is everything the wallet bought of this token, before the range, inside it and after it. Sold, PnL and ROI count the
same buys, so the numbers add up: PnL is what it received minus what the sold tokens cost at its average price.

The 30 days are counted by tracced from the wallet's own swaps. Profit counts on the day of the sale, at what the wallet really
paid, even when the buy came earlier: the card reads earlier trades of up to {{ s.profile_history_tokens }} tokens with the
biggest sales. A position is closed once 99% of it is sold. A token sold with no buy found is left out and counted apart: a
transfer is not a profit.

A card someone already opened today opens free for everyone.

## Filters and views

**Filters** holds every number from and to, **Only my watchlist** and the tags to hide in one row, bots first. One `bundle`
chip hides `launch-bundle` and `own-bundle` too. A set you use often can
be kept: press *Save these filters* and name it. It stays in your browser and applies to any analysis in one click.

## The AI agent

The agent on a result page reads that analysis and nothing else. Pick a question or ask your own, in any language. **Summary of
this pump** writes what happened in the range, what a buyer should weigh, and whose wallets stand out. A wallet it names opens
its card.

It does not compute numbers of its own: before an answer reaches the page, every number and wallet in it is checked against the
analysis, and a line that fails is dropped. It never tells you to buy or sell, predicts a price or calls a token safe. With a
wallet connected it sees your own watchlist when you ask, so "which of my wallets are here?" has an answer.

Anything outside the analysis gets one fixed reply. Questions go to AI model hosts whose policy is not to collect them or train
on them, or to keep them only for a limited time. Do not type anything personal into it.{% if not assistant_on %}

!!! warning "The agent is off on this server"
    It needs a model key that this deployment does not have yet.
{% endif %}
