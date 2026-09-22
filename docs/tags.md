# Tags and what each one means

A tag here is a rule, not an opinion. Each one is computed from numbers that are already in the table or from the
chain, each has a definition you can read by hovering it, and each can be argued with.

| Tag | The rule |
|---|---|
| `dev` | The wallet that created the token's pool |
| `sniper` | Bought within 60 seconds of the token being created |
| `fresh` | The wallet was younger than 24 hours at its first buy here |
| `bot-like` | 30 or more trades with a median hold under 2 minutes, or 5 or more buy→sell pairs within 5 seconds |
| `pre-range` | Also bought before the range you marked |
| `transfer-in` | Sold more than it was ever seen buying — the rest arrived another way, usually a transfer |
| `re-bought` | Bought again after the range |
| `bundle` | Its first SOL came from the same wallet as at least two others in this list — likely one operator |
| `no-exits` | Its exits were never fetched, because it fell outside the per-analysis cap |

`no-exits` is the honest one. It does not mean the wallet lost or still holds; it means we did not buy that data.
Those wallets are counted separately in the summary above the table and never folded into the winners or losers.

## Why there is no score

A score compresses a judgement into a number and hides the judgement. "Smart money" means whatever the vendor
decided it means, and you cannot check it. Every tag above can be checked: open the wallet on Solscan and the
first transaction, the funding transfer or the trade times are right there.

| `seen-before` | Also an early buyer in another analysis **you** saved |

`transfer-in` is worth reading twice. tracced sees swaps, not transfers, so a wallet that sold more than it ever
bought must have received those tokens some other way — almost always sent from another wallet. It used to be
folded into `pre-range`, which claimed the wallet had bought earlier; it had not necessarily bought at all.

`seen-before` is the only tag that depends on you rather than on the chain. It appears when the wallet was also an
early buyer in another analysis saved to your account, it carries how many, and clicking it opens the wallet's
card with each of those analyses as a link. Nobody else's saved analyses are ever part of it.
