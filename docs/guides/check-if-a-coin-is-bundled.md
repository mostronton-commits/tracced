# How to check if a meme coin is bundled

A bundled launch is one where a single operator bought a large part of the supply from many wallets at once, so the
holder list looks spread out when it is not. On pump.fun this usually happens in the first seconds, often inside one Jito
bundle with the transaction that created the token.

It matters because the same hand can sell all those wallets into your buy. In the 159 tokens analysed on tracced,
wallets that shared a funder with two or more others were in profit 77% of the time, against 57% for everyone else.
[The numbers](/guides/solana-launches-in-numbers).

## Three signs to look for

1. **Many wallets in the creator's launch bundle.** A Jito bundle runs up to five transactions in one block, in order, all or
   nothing. If the bundle that created the token also holds buys from other wallets, the creator bought those wallets'
   tokens.
2. **Wallets with one funder.** Fresh wallets whose first SOL came from the same address, minutes before they bought. An
   exchange's hot wallet does not count: thousands of strangers withdraw from it.
3. **Buys and sells inside one bundle.** Two wallets on both sides of a trade in the same bundle are one person moving
   tokens between pockets, often to paint volume.

## Check it on tracced

1. Paste the token's address on [tracced](/). The chart loads with the token's whole life.
2. Mark the launch and the first minutes on the chart, then press **Get wallets**.
3. Read the tags on the rows:
   - `launch-bundle`: bought inside the creator's own Jito bundle at the launch;
   - `bundle`: its first SOL came from the same wallet as two or more others in the table;
   - `own-bundle`: sold to, or bought from, another wallet of the table inside one Jito bundle;
   - `fresh`: under a day old at its first buy.
4. After the table, the launch check lists what it found about the launch, each fact with its proof. When it finds such
   facts, the token is marked as an organised launch.

Filter the table by a tag to see how much those wallets bought, and whether they have already sold. Every trade opens on
Solscan, so nothing has to be taken on trust.

## Check it by hand

On Solscan, open the token's first transactions. The creation transaction shows the creator's own buy; buys from other
wallets in the same slot, in a row, are the bundle. For each buyer, open its first incoming SOL transfer and note the
sender. Three or more buyers with one sender, which is not an exchange, are a cluster. It takes a few minutes per wallet,
which is why a tool helps.

## What it does not prove

A bundle shows who controls the supply, not what they will do with it. Some teams bundle to stop snipers, then hold.
Look at what the bundled wallets did next: the `Sold` column and the chart marks show it.

Related: [Bundles vs snipers](/guides/jito-bundles-snipers) · [Find insider wallets](/guides/find-insider-wallets) ·
[All tags](/docs/tags)
