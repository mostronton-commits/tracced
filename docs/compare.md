# Compare

The first question people ask is why not just look at Axiom or GMGN. Fair question. The short answer is that
they are built to trade and this is built to read, and the two answer different questions.

## Different question

A terminal shows you the winners: top traders by profit, top holders by size, the first N buyers after launch.
That answers "who made money on this token".

tracced answers "who was inside the window I marked". Everyone who bought there, winners and losers together,
with the facts from their own swaps.

That second question is the one a ranking cannot reach. Eleven wallets funded by the same address, all buying
within four minutes, are invisible in a list sorted by profit and obvious in a list of everyone who was present.

## Side by side

<table class="cmp">
<thead><tr><th>What you want</th><th class="us">tracced</th><th>Axiom</th><th>GMGN</th></tr></thead>
<tbody>
<tr><td>Mark any window and list everyone who bought inside it</td><td class="us">the window is yours</td><td>not documented</td><td>no window parameter</td></tr>
<tr><td>How the wallet list is bounded</td><td class="us">everyone above the dust floor</td><td>one row per trader, no published cap</td><td>API returns at most 100</td></tr>
<tr><td>A fixed "first N buyers" view</td><td class="us">any window instead</td><td>not documented</td><td>First 70 Buyers, from launch</td></tr>
<tr><td>One wallet's trades drawn on the price chart</td><td class="us">up to 10 wallets at once</td><td>not documented</td><td>by wallet category, not one address</td></tr>
<tr><td>Wallet age and who sent its first SOL</td><td class="us">on every row</td><td>not documented</td><td>both fields exist in the API</td></tr>
<tr><td>Grouping wallets by a shared funder</td><td class="us">3 or more in the list</td><td>same-block bundles, rule published</td><td>tags exist, grouping is a script</td></tr>
<tr><td>Are the rules behind the labels published</td><td class="us">all of them, one page</td><td>the bundle rule, not the rest</td><td>described, thresholds not given</td></tr>
<tr><td>Take the list away as a file</td><td class="us">CSV, TXT, JSON</td><td>no export documented</td><td>your followed list, as JSON</td></tr>
<tr><td>Place a trade</td><td class="us">no</td><td>yes, that is the point</td><td>yes, that is the point</td></tr>
</tbody>
</table>

!!! info "📅 Where these cells come from"
    The Axiom column is from `docs.axiom.trade`, the GMGN column from `docs.gmgn.ai` and GMGN's published API
    reference, read on 22 September 2026. **Not documented** means exactly that: we could not find it in their
    own documentation, not that it cannot be done. Both ship weekly. If a cell is wrong,
    [tell us](https://github.com/mostronton-commits/tracced/issues) and it gets fixed.

## Credit where it is due

Axiom publishes the rule behind its bundle flag: four or more transactions in the same block, with no time
limit. That is a real rule you can argue with, and most of this industry does not offer one.

GMGN exposes the raw inputs through its API. Wallet creation time and the first transfer that funded a wallet
are both fields you can read, which is more than a badge.

GMGN is also honest about the rest of it. Its own documentation says the numbers behind its labels "cannot
guarantee real-time accuracy and is provided for auxiliary reference only". We agree, and that is the whole
reason this product has no scores in it.

## What they do that we do not

Both are full terminals, and that is most of what they are.

- **Trading.** Hotkeys, limit orders, migration snipes, MEV settings. tracced places no orders at all.
- **Copy-trading and automation.** Auto-buy, take-profit, stop-loss, dev-sell triggers, Telegram bots.
- **Alerts.** Live tracking of a wallet you follow. Ours is on the [roadmap](/docs/roadmap), not in the product.
- **Reach.** Many chains, mobile, on-ramps, perpetuals, token launches.

They charge about 1% per trade. tracced is free while it is early, and it earns nothing from your trades because
it cannot place any.

## When to use which

**Use a terminal** when you want to buy something now, follow a wallet you already trust, or watch a launch as it
happens.

**Use tracced** when a pump already happened and you want the names. Mark the range, take the whole list, look at
who funded whom, keep the wallets that interest you, and check any row on Solscan.

**Use both.** Find the wallets here, export them, track them there. That is how the people who tested this
actually work, and nothing about it is exclusive.
