# Compare

Why not just look at Axiom or GMGN? Because they are built to trade, and this is built to read.

A terminal ranks the winners: top traders by profit, top holders by size. tracced lists **everyone who bought
inside the range you marked**, winners and losers together.

Their labels decide what you are allowed to see. GMGN plots wallet trades on the chart **by category**, smart
money, KOL, whales, snipers, so a wallet nobody has labelled never appears there, however much it made. You end
up watching the same known wallets as everyone else.

Most of the money in any range belongs to wallets nobody labelled. Those are the ones a full list gives you, and
they are the reason nine wallets funded from one address are obvious here and invisible in a ranking.

<table class="cmp">
<thead><tr><th>What you want</th><th class="us">tracced</th><th>Axiom</th><th>GMGN</th></tr></thead>
<tbody>
<tr><td>Buyers in your range</td><td class="us">every one</td><td>not documented</td><td>first 70 from launch</td></tr>
<tr><td>How many wallets</td><td class="us">all of them</td><td>not published</td><td>100 in the API</td></tr>
<tr><td>Trades on the chart</td><td class="us">10 at once</td><td>not documented</td><td>by category, not one</td></tr>
<tr><td>Age and first funder</td><td class="us">top {{ s.age_lookups_max }} by PnL, read to the first transaction; any other on its card</td><td>not documented</td><td>raw fields in the API</td></tr>
<tr><td>Shared-funder clusters</td><td class="us">3 or more</td><td>same block only</td><td>tags, no grouping</td></tr>
<tr><td>Label rules</td><td class="us">all published</td><td>bundle only</td><td>none published</td></tr>
<tr><td>Export</td><td class="us">CSV, TXT, JSON</td><td>not documented</td><td>follow list only</td></tr>
<tr><td>Trading</td><td class="us">no</td><td>yes</td><td>yes</td></tr>
</tbody>
</table>

!!! info "📅 Checked 22 September 2026"
    From their own docs: `docs.axiom.trade`, `docs.gmgn.ai`. **Not documented** means we could not find it in
    their manual, not that it is impossible. Wrong cell?
    [Tell us](https://github.com/mostronton-commits/tracced/issues).

## Fair to them

Axiom publishes the rule behind its bundle flag: four or more buys in one block. Most of this industry publishes
nothing.

GMGN hands you the raw inputs, wallet age and first funding transfer, through its API. It also says its own
labels "cannot guarantee real-time accuracy and is provided for auxiliary reference only". We agree, which is
why there are no scores here.

## What they have and we do not

Trading, copy-trading, automation, alerts, many chains, mobile. They charge about 1% a trade. tracced charges
nothing, and earns nothing from your trades, because it cannot place any.

## Which to use

A terminal to buy. tracced to find out who bought. Or both: find the wallets here, export, track them there.
