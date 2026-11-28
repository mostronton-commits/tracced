# Jito bundles, bundlers and snipers, told apart

Three words get mixed up in memecoin chats. They describe different people doing different things, and the difference
decides whether a launch is a fair race or a staged one.

## Jito bundle

A Jito bundle is a group of up to five Solana transactions that run one after another in the same block, all or none,
for a tip to the validator. It is a tool, not a scam: wallets, bots and market makers use it every day to avoid being
front-run.

## Bundler

A bundler is a creator who puts the token's creation and buys from several of their own wallets into one bundle. The buys
land before anyone else can see the token, at the lowest price, and the supply looks spread over many holders. On tracced,
those wallets carry the `launch-bundle` tag.

Across 159 analysed tokens, a wallet from the creator's own launch bundle was among the early buyers in **3.8%** of
tokens. Treat that as a floor: the check reads only the first minutes after creation, and many marked ranges start later. Funding clusters were far more common: **43%** of tokens had three or more early buyers
first funded by one address (`bundle`).

## Sniper

A sniper is a bot that buys in the first seconds after a token appears, before most people have seen it, and usually sells
into the first wave of buyers. It is a stranger to the creator, at least on chain. tracced tags a wallet `sniper` when it
bought within 60 seconds of the token's creation.

Snipers were among the early buyers of **85%** of the analysed tokens. They did only slightly better than everyone else:
63% in profit against 56%, with a median realized profit of $13.

## Side by side

| | Who | When | Tag on tracced |
|---|---|---|---|
| Bundler | the creator, from several wallets | in the creation's own bundle | `launch-bundle` |
| Funding cluster | one operator, from fresh wallets | any time | `bundle`, often with `fresh` |
| Wash inside a bundle | one hand on both sides | any time | `own-bundle` |
| Sniper | a bot, not the creator | first 60 s | `sniper` |

## Why it matters for you

Snipers take a slice of the first move. A bundler holds the supply and decides when the price ends. If a token you like has
a heavy `launch-bundle` or `bundle` share that has not sold yet, you are buying from the person who can sell to you.

Check any token: [Is it bundled?](/guides/check-if-a-coin-is-bundled) · [All tags](/docs/tags)
