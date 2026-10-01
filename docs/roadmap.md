# Roadmap

## Shipped

Paste a token, mark a range, get every wallet that bought there with facts you can check. Tags that are rules.
Export. Repeats across your own saved analyses. Amounts in dollars or in SOL.

A wallet card with the wallet's last 7 or 30 days on every token, counted from its swaps, and a mark when it is a
known one: a KOL, its X account, the app it trades through. Several named lists for the wallets you keep. A busy
token analyzed in seconds. A result that reads on a phone and stays light with thousands of wallets. New analyses
counted per person a day, not per wallet.

Fresh pumps on the home page: tokens of the last two days that reached a real peak and are really traded, without the
clones and the wash volume. Telegram alerts for the wallets in a list, in a closed test: a buy or a sell about two
seconds after the block, and each row counting the wallet's trades of the last 7 days.

An AI agent that reads only the analysis in front of it: answers to your questions and a summary in three cards
(what happened, what to weigh, whose wallets stand out), each line carrying a number from the table. It needs a connected
wallet.{% if not assistant_on %}

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

**Alerts for everyone.** A wallet on one of your lists buys or sells and Telegram tells you within seconds. In a
closed test now; open to all next.

**90 days in the wallet card.** Today it counts 30.

## Later

**Copy-trading, non-custodial.** Follow the wallets you picked, keys staying yours.

**More chains.** A second chain after Solana.

## Not on this list, on purpose

Wallet scores. "Smart money" ratings. Any number whose meaning only the vendor knows.

If a claim cannot be checked against the chain, it does not belong in a product whose whole argument is that you
can check it.
