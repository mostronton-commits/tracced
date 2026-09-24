# Roadmap

## Shipped

Paste a token, mark a range, get every wallet that bought there with facts you can check. Tags that are rules.
Export. Repeats across your own saved analyses. Amounts in dollars or in SOL.

A wallet card with the wallet's last 30 days on every token, counted from its swaps, and its name when it is a known
one. Wallet histories fetched in parallel, so a busy token takes seconds. A result that reads on a phone.

An AI agent that reads only the table in front of it and the method you describe, then returns a short list with
a reason for each pick.{% if not assistant_on %}

!!! warning "🤖 The agent is off on this server"
    It needs a model key that this deployment does not have yet, so its button explains itself instead of
    answering.
{% endif %}

## Next

!!! agent "✦ An analyst you can talk to"
    Describe how you pick wallets, in your own words. The agent reads the table, opens the wallet cards it needs
    (30-day PnL, win rate, when it trades, what it bought lately), checks funders and your earlier analyses, and
    returns a short list. Every reason points at a number you can open: a row, a card, a swap on Solscan. It judges
    only by those facts and your method, and it never predicts a price.

!!! agent "✦ tracced for agents"
    The same tools, open to any AI agent through the Model Context Protocol (MCP): analyze a token's range, read the
    wallets, open a card, keep lists. An agent you already use, in Claude, Cursor or your own trading bot, asks
    tracced who bought before a pump the way it would search the web. Alerts reach it next, then copy-trading, and
    no trade leaves without your confirmation.

**Alerts.** A wallet on one of your lists buys something and you hear about it within a minute or two. The wallets
you watch are checked on a schedule, so no new data source is needed.

**90 days in the wallet card.** Today it counts 30.

## Later

**Copy-trading, non-custodial.** Follow the wallets you picked, keys staying yours.

**More chains.** One provider sits behind a thin adapter, so a second chain is a new adapter, not a new product.

## Not on this list, on purpose

Wallet scores. "Smart money" ratings. Any number whose meaning only the vendor knows.

If a claim cannot be checked against the chain, it does not belong in a product whose whole argument is that you
can check it.
