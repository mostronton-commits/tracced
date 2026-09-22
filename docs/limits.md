# Limits and what they cost

tracced is early, so the limits are small while the load is watched. They will grow.

## What is open to everyone

The demo token, every finished result, every page, and the chart of any token. Opening a finished analysis is free
for anyone — that is what makes a shared link work.

## What needs a connected wallet

Running a **new** analysis. The wallet signs a message, there is no transaction and no fee. You are asked for it
at the moment you press Analyze, not before, and the range you marked survives the sign-in.

| Limit | Value |
|---|---|
| New analyses per wallet per day | 1 |
| Ranges, and analyses, per token | 3 |
| Longest range | 6 hours |
| Requests one run may spend | 1,000 |
| Wallets that get exact exits | 250 |
| Smallest position that makes the table | $95 bought inside the range |

## Why the limits exist

Every new token costs real money. Reconstructing a token's history can take hundreds of requests to a paid API,
and the first analysis of a busy token is the expensive one — every further range on the same token is nearly
free, because its trades are already stored.

The wallets that get exact exits are the largest buyers of the range. The rest keep their entry and carry
`no-exits`. When the whole-history path turns out cheaper, every wallet gets exact exits and the cap does not
apply at all; the line above the table always says which happened.
