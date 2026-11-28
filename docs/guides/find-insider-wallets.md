# How to find insider wallets on a Solana memecoin

An insider wallet is one that bought before the pump because it knew, not because it guessed: the team, their friends, a
group that was told the time. You cannot see intent on chain. You can see who bought in the quiet minutes before the move,
what they paid, and what they did when the price went up. That is usually enough.

## Why a profit ranking misses them

Every terminal can rank a token's traders by profit. That list shows who won, not who knew. An insider who bought early
and is still holding, or who spread the buys over ten wallets, sits far down a profit ranking. In a list of everyone who
bought inside the right window, they stand out: eleven wallets funded by one address, buying within four minutes.

## Step by step on tracced

1. **Paste the token's address** on [tracced](/). The chart shows its whole life, from creation.
2. **Mark the range.** Click where buying starts and where the price takes off. The best range is short: across 159
   analysed tokens, the median marked range was three minutes.
3. **Press Get wallets.** Every wallet that bought inside the range appears, with:
   - the market cap it entered at and its average exit;
   - what it spent, what it took out, and its realized profit (PnL) and ROI;
   - how long it held, and whether it is still holding.
4. **Sort and filter.** Sort by PnL, then turn on the tags: `fresh` (under a day old at its first buy), `bundle` (shares its
   first funder with two or more others), `pre-range` (was already buying before your range), `never-sold`.
5. **Open a wallet's card.** It shows the wallet's last 30 days on every token: win rate, PnL, what else it traded. A wallet
   that bought early on many tokens that later pumped is worth following.

Then save the wallets you want and switch on Telegram alerts: you get a message when they buy or sell again.

## What insiders tend to look like

From the same 159 tokens:

- Wallets first funded together with two or more others were in profit **77%** of the time, with a median realized profit of
  **$236**. An ordinary early buyer: 57% and about **$5**.
- Wallets under a day old did nearly as well: 74% in profit, **$141** median.
- The best tenth of a token's early wallets took **67%** of its profit.

None of these is proof on its own. A funding cluster can be one cautious trader. Look for two or three signals together,
and check the trades: every row opens on Solscan.

## Without a tool

On Solscan or a DEX screener, open the token's trades around the start of the pump, list the buyers, then open each
buyer's wallet: its age, its first funding transfer, and its other tokens. It works for ten wallets. For a hundred, it is
an afternoon.

Related: [Is it bundled?](/guides/check-if-a-coin-is-bundled) · [Copy trading early buyers](/guides/copy-trading-early-buyers) ·
[How a result is counted](/docs/how-it-works)
