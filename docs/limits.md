# Limits

tracced is early, so the caps are small while the load is watched. They will grow.

## Free for everyone

The demo token, every finished result, every page, and the chart of any token. Opening a finished analysis costs
nothing and needs no account — that is what makes a shared link work.

## Needs a wallet

Running a **new** analysis. The wallet signs a message: no transaction, no fee. You are asked at the moment you
press Analyze, not before, and the range you marked survives the sign-in.

The daily count of new analyses is per person, not per wallet: connecting another wallet in the same browser adds
nothing. To know the browser again, the first analysis leaves a cookie holding a random number and nothing else; it
is not used for analytics. One network has its own, higher count, because an office or a phone carrier puts many
people behind one address. Every count resets at midnight UTC, and the page shows how many are left. A run that
fails gives its analysis back.

Loading what a result does not hold yet in a wallet card: the wallet's last 30 days on every token, its age and
first funder when it is not among the first {{ s.age_lookups_max }} by PnL that the analysis checks itself, and the
trades of a wallet without exact exits. What someone has already loaded is free for everyone: the 30 days are kept
for a day, and the age and funder stay in the result.

| Limit | Value |
|---|---|
| New analyses a day, per person: wallet and browser count together | {{ s.runs_per_day }} |
| New analyses a day from one network | {{ s.runs_per_ip_per_day }} |
| Ranges per token | {{ s.ranges_per_token }} |
| Longest range | {{ s.max_window_hours }} hours |
| Requests one run may spend | {{ '{:,}'.format(s.run_cap_requests) }} |
| Wallets that get exact exits | {{ '{:,}'.format(s.max_wallet_lookups) }} |
| Smallest position in the table | ${{ s.min_invested_usd }} bought inside the range |
| Wallets whose age is checked with the analysis, first by PnL | {{ s.age_lookups_max }} |
| Other wallets checked from their cards, per person a day | {{ s.get('age_card_per_day', 50) }} |
| Requests a day: charts (guest) / charts and wallet cards (wallet) / the whole site | {{ '{:,}'.format(s.browse_per_day_guest) }} / {{ '{:,}'.format(s.browse_per_day) }} / {{ '{:,}'.format(s.browse_global_per_day) }} |
| New analyses on the whole site, per day | {{ s.runs_global_per_day }} |

!!! info "📐 These numbers are the live settings"
    The table is rendered from the same configuration the site runs on, so it cannot drift from what actually
    happens.

## Why they exist

A new token costs real money. Reconstructing its history can take hundreds of requests to a paid API.

The first analysis of a busy token is the expensive one. Every further range on the same token is nearly free,
because its trades are already stored.

{% if s.credits_reserve_pct %}## The month

The data plan is a monthly budget. A new analysis starts only while the worst it could cost still leaves
{{ s.credits_reserve_pct }}% of the plan untouched. Near the end of a heavy month new analyses wait for the plan to
renew; the demo, every finished result and every chart stay open.

{% endif %}## Which wallets get exact exits

The largest buyers of the range. The rest keep their entry and carry `no-exits`.

When the whole-history path turns out cheaper, everyone gets exact exits and this cap does not apply at all. The
line above the table always says which happened.
