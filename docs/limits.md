# Limits

tracced is early, so the caps are small while the load is watched. They will grow.

## Free for everyone

The demo token, every finished result, every page, and the chart of any token. Opening a finished analysis costs
nothing and needs no account — that is what makes a shared link work.

## Needs a wallet

Running a **new** analysis. The wallet signs a message: no transaction, no fee. You are asked at the moment you
press Analyze, not before, and the range you marked survives the sign-in.

| Limit | Value |
|---|---|
| New analyses, per wallet, per day | {{ s.runs_per_day }} |
| Ranges per token | {{ s.ranges_per_token }} |
| Longest range | {{ s.max_window_hours }} hours |
| Requests one run may spend | {{ '{:,}'.format(s.run_cap_requests) }} |
| Wallets that get exact exits | {{ s.max_wallet_lookups }} |
| Smallest position in the table | ${{ s.min_invested_usd }} bought inside the range |
| Wallets whose age is checked | {{ s.age_lookups_max }} |
| Chart requests a day: guest / wallet / site | {{ s.browse_per_day_guest }} / {{ s.browse_per_day }} / {{ s.browse_global_per_day }} |

!!! note "📐 These numbers are the live settings"
    The table is rendered from the same configuration the site runs on, so it cannot drift from what actually
    happens.

## Why they exist

A new token costs real money. Reconstructing its history can take hundreds of requests to a paid API.

The first analysis of a busy token is the expensive one. Every further range on the same token is nearly free,
because its trades are already stored.

## Which wallets get exact exits

The largest buyers of the range. The rest keep their entry and carry `no-exits`.

When the whole-history path turns out cheaper, everyone gets exact exits and this cap does not apply at all. The
line above the table always says which happened.
