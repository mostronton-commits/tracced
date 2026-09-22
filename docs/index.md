# What tracced does

Paste a Solana token, mark the range on the chart where the buying happened, and see every wallet that bought
inside it — with what it paid, what it took out, how long it held, and what it did next.

No scores. No "smart money" labels. The numbers come from raw on-chain swaps, and every row opens on Solscan so
you can check any of them yourself.

## The three steps

1. **Paste the token address.** The chart loads with its whole life on it.
2. **Mark the range.** Click the chart twice, or press **Find the pump** and let the detector propose one.
3. **Press Analyze.** A terminal shows the run, and the result is a table of every wallet that bought in that window.

The demo token is open to everyone with no account. Analyzing any other token needs a connected Solana wallet:
the wallet signs a short message, there is no transaction and no fee.

## What makes an answer different here

Most terminals rank the traders of a token by profit and show you the top hundred. That is a view backwards: who
happened to win. tracced answers a different question — **who was inside the window you chose**, whether they went
on to win or lose, and whether they moved together.

That second part is the interesting one. When eleven wallets were all funded by the same address and all bought
within the same four minutes, a list sorted by profit will never show it. A list of everyone who was there will.
