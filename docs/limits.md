# Limits

tracced is early, so the caps are small while the load is watched. They will grow.

## Free for everyone

The demo token, every finished result, every page, and the chart of any token. Opening a finished analysis costs
nothing and needs no account — that is what makes a shared link work. A finished analysis stays as it was run,
whoever ran it: its range does not move, and a different range is a new row beside it.

## Needs a wallet

Running a **new** analysis. The wallet signs a message: no transaction, no fee. You are asked at the moment you
press Analyze, not before, and the range you marked survives the sign-in.

The daily count of new analyses is per person, not per wallet: connecting another wallet in the same browser adds
nothing. To know the browser again, the first analysis leaves a cookie holding a random number and nothing else; it
is not used for analytics. One network has its own, higher count, because an office or a phone carrier puts many
people behind one address. Every count resets at midnight UTC, and the page shows how many are left. A run that
fails early, or is cut short by a server restart, gives its analysis back; one that fails once it has done real
work counts toward the day.

Beta testers the owner invites have no daily count. The limits on a single run apply to them as to everyone.

Loading what a result does not hold yet in a wallet card: the wallet's last 30 days on every token, and its age and
first funder when the analysis has not checked them. What someone has already loaded is free for everyone: the 30
days are kept for a day, and the age and funder stay in the result.

| Limit | Value |
|---|---|
| New analyses a day, per person: wallet and browser count together | {{ s.runs_per_day }} |
| New analyses a day from one network | {{ s.runs_per_ip_per_day }} |
| New analyses a day on the whole site, while the month's requests last | {{ s.runs_global_per_day }} |
| Ranges per token | {{ s.ranges_per_token }} |
| Longest range | {{ s.max_window_hours }} hours |
| Wallets that get exact exits | {{ '{:,}'.format(s.max_wallet_lookups) }} |
| Smallest position in the table | ${{ s.min_invested_usd }} bought inside the range |
| Wallets whose age is checked with the analysis, first by PnL | {{ s.age_lookups_max }} |
| Other wallets checked from their cards, per person a day, and per network | {{ s.age_card_per_day }} |
| Changes to your watchlist, tags and notes, and exports, per wallet a day | {{ '{:,}'.format(s.acct_writes_per_day) }} |
| Questions to the AI agent, per person a day | {{ s.agent_questions_per_day }} |
| Results the agent writes its cards for, per person a day (cards someone already opened are free) | {{ s.agent_cards_per_day }} |

!!! info "📐 These numbers are the live settings"
    The table is rendered from the same configuration the site runs on, so it cannot drift from what actually
    happens.

## Why they exist

Reading a new token's history costs real money. The first analysis of a busy token is the expensive one. Every
further range on the same token is nearly free, because its trades are already stored.{% if s.credits_reserve_pct %}

Near the end of a heavy month new analyses may wait; the demo, every finished result and every chart stay open.{% endif %}

## Which wallets get exact exits

The largest buyers of the range. The rest keep their entry; their Sold and PnL show `—`, because we did not read
their sells.

On some tokens everyone gets exact exits and this cap does not apply at all. The line above the table always says
which happened.
