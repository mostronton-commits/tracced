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
| New analyses per wallet per day | {{ s.runs_per_day }} |
| Ranges, and analyses, per token | {{ s.ranges_per_token }} |
| Longest range | {{ s.max_window_hours }} hours |
| Requests one run may spend | {{ '{:,}'.format(s.run_cap_requests) }} |
| Wallets that get exact exits | {{ s.max_wallet_lookups }} |
| Smallest position that makes the table | ${{ s.min_invested_usd }} bought inside the range |
| Wallets whose age is checked | {{ s.age_lookups_max }} |
| Chart requests a day, per address / per wallet / for the site | {{ s.browse_per_day_guest }} / {{ s.browse_per_day }} / {{ s.browse_global_per_day }} |

Every number in this table is read from the same settings the site runs on, so it cannot drift from what actually
happens.

## Why the limits exist

Every new token costs real money. Reconstructing a token's history can take hundreds of requests to a paid API,
and the first analysis of a busy token is the expensive one — every further range on the same token is nearly
free, because its trades are already stored.

The wallets that get exact exits are the largest buyers of the range. The rest keep their entry and carry
`no-exits`. When the whole-history path turns out cheaper, every wallet gets exact exits and the cap does not
apply at all; the line above the table always says which happened.
