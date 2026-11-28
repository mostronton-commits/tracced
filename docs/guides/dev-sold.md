# Dev sold: what it means and how to check it

"Dev sold" means the wallet that created the token has sold its own tokens. Screeners show it as a badge because a
creator selling early is the most common way a memecoin ends. It is a fact about one wallet, though, and the creator rarely
has only one.

## What the badge does not see

- **Other wallets of the creator.** A creator who bought from five wallets in the launch bundle can keep the main one
  untouched, so the badge stays quiet while the others sell. See [Is it bundled?](/guides/check-if-a-coin-is-bundled).
- **The creator fee.** pump.fun lets a creator take a fee from every trade and send it to another wallet. A creator can
  earn without selling a single token.
- **Transfers.** Tokens moved to a fresh wallet and sold from there do not count as the dev's sale.

So "dev not sold" is weak comfort, and "dev sold" can be old news from the first minute.

## How often the creator trades the pump

Across 159 tokens analysed on tracced, the wallet that created the token's pool was itself a buyer inside the marked range
in **65 tokens (41%)**. 19 of those sold on the token, and 14 sold everything.
[More numbers](/guides/solana-launches-in-numbers).

## Check it on tracced

1. Paste the token on [tracced](/) and mark the launch and the minutes before the pump.
2. Press **Get wallets**. The creator's wallet carries the `dev` tag when it bought in the range; its row shows what it
   spent, what it sold, and at what market cap.
3. Turn on `launch-bundle` and `bundle` to see the wallets that most likely belong to the same hand, and compare their
   `Sold` column with the creator's.
4. After the table, the launch check shows where the creator fee goes and how much SOL it has paid out.

## Check it by hand

Open the token on Solscan and find the creation transaction; its signer is the creator. Open that wallet's token
transfers for this token: every outgoing transfer to a pool is a sale, every transfer to another wallet is worth following.
Then look at who received the creator fee.

Related: [Bundles vs snipers](/guides/jito-bundles-snipers) · [All tags](/docs/tags)
