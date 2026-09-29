# API (beta)

A token check for partners: send a Solana token address, get back which of nine rules it trips and whether it passes
the thresholds set for your key. It answers in well under a second. Keys are by invitation; ask through
[Contact](/feedback) or on [X](https://x.com/tracced_xyz).

There are no scores here, the same as on the rest of tracced: every rule is a plain fact with its limits written below.

## The check

```
GET https://tracced.xyz/api/v1/check?mint=<token address>
Authorization: Bearer <your key>
```

`X-API-Key: <your key>` works too. Never put the key in the address: addresses end up in logs.

```json
{
  "mint": "DKxXdaMC1so182urvrrnhs6V6fGTrttPS8br6JuEpump",
  "checked_at": "2026-09-29T10:00:00Z",
  "cached": false,
  "passes": false,
  "failed": ["bundle"],
  "high": ["bundle", "bundled_launch"],
  "flags": "2 of 9",
  "levels": {
    "dev": "low", "bundle": "high", "top10": "medium", "snipers": "medium", "insiders": "low",
    "bundled_launch": "high", "mint": "low", "freeze": "low", "liquidity": "low"
  },
  "age_minutes": 2
}
```

| Field | What it means |
|---|---|
| `passes` | The token passed your key's thresholds: the shares of the creator, of launch bundles and of the ten largest holders |
| `failed` | Which thresholds it failed. `no_data` when one of those shares is unknown: the check closes rather than guesses. `rugged` when the pool's liquidity is already gone |
| `high` | The rules at level high |
| `flags` | How many of the nine rules are high |
| `levels` | Every rule's level: `low`, `medium`, `high`, or `unknown` |
| `age_minutes` | Minutes since the token was created |
| `cached` | The same token was checked less than a minute ago, and this is that answer |

Your key's thresholds are set by tracced on request; the default is {{ API.DEFAULT_THRESHOLDS.dev|int }}% for each of
the three shares.

## The rules

| Rule | What it looks at | low | medium | high |
|---|---|---|---|---|
| `dev` | The creator's share of the supply | under {{ API.CUTS.dev[0] }}% | {{ API.CUTS.dev[0] }}–{{ API.CUTS.dev[1] }}% | over {{ API.CUTS.dev[1] }}% |
| `bundle` | Wallets from launch bundles: their share now | under {{ API.CUTS.bundle[0] }}% | {{ API.CUTS.bundle[0] }}–{{ API.CUTS.bundle[1] }}% | over {{ API.CUTS.bundle[1] }}% |
| `top10` | The ten largest holders, without pools and the launchpad curve | under {{ API.CUTS.top10[0] }}% | {{ API.CUTS.top10[0] }}–{{ API.CUTS.top10[1] }}% | over {{ API.CUTS.top10[1] }}% |
| `snipers` | Wallets that bought in the first seconds: their share now | under {{ API.CUTS.snipers[0] }}% | {{ API.CUTS.snipers[0] }}–{{ API.CUTS.snipers[1] }}% | over {{ API.CUTS.snipers[1] }}% |
| `insiders` | Wallets linked to the creator: their share now | under {{ API.CUTS.insiders[0] }}% | {{ API.CUTS.insiders[0] }}–{{ API.CUTS.insiders[1] }}% | over {{ API.CUTS.insiders[1] }}% |
| `bundled_launch` | What bundles took at launch, even if they sold since | under {{ API.CUTS.bundled_launch[0] }}% | {{ API.CUTS.bundled_launch[0] }}–{{ API.CUTS.bundled_launch[1] }}% | over {{ API.CUTS.bundled_launch[1] }}% |
| `mint` | The creator can still mint more tokens | revoked | | enabled |
| `freeze` | The creator can freeze holders' tokens | revoked | | enabled |
| `liquidity` | Whether the largest pool's liquidity can be pulled, and whether there is enough | on a launchpad curve, or over ${{ '{:,}'.format(API.LIQ_MEDIUM) }} | ${{ '{:,}'.format(API.LIQ_HIGH) }}–{{ '{:,}'.format(API.LIQ_MEDIUM) }} | under {{ API.LP_BURN_MIN }}% of the pool's LP burned, or under ${{ '{:,}'.format(API.LIQ_HIGH) }} |

Pools with concentrated liquidity (DLMM, CLMM, Whirlpool) have no LP tokens to burn, so only their size counts.
Shares are of the whole supply. Early numbers move fast: a creator can sell half of a position within a minute. If
you buy some time after the first check, check again right before.

## Limits and errors

A key has a daily limit, set with you, and takes up to 5 requests a second. The day resets at 00:00 UTC.

| Status | When |
|---|---|
| 400 | The address is not a Solana token address |
| 401 | The key is missing or unknown |
| 403 | The key is switched off |
| 404 | The data source does not know this token |
| 429 | Too many requests in a second, or the day's limit is used up |
| 502 | The data source did not answer; try again in a few seconds |
| 503 | This month's data budget is nearly used up; checks resume when it renews |

A key can also be tied to your servers' addresses. Then it does not work from anywhere else, even if it leaks.

## What it does not catch

A creator's wallets hidden behind an exchange or a chain of transfers, and bundles spread out over time. No check
catches everything; use it as a filter, not a guarantee.

## Terms of use (beta)

Using a key means accepting these terms:

- **Keep the key on your server.** Never put it in a web page, an app or a public repository. Tell us at once if it
  leaks, and we will issue a new one.
- **Use the answers to check tokens for your own product.** Showing a token's levels to your users is fine, with
  "rules by tracced" and a link to this page. Reselling the answers, or passing them on as a dataset, is not.
- **Do not call a token "safe", "audited" or "verified by tracced".** The check reports facts against written rules; it
  says nothing about where a price goes.
- **Provided as is, without warranty.** Not financial advice. tracced is not liable for losses from decisions made
  with it.
- **We can change the rules, the limits or this page, or switch a key off, at any time.** During the beta the check is
  free.
- **What we keep:** for each call, the key, the token, the time and the result, to run the service and to count its
  cost. Nothing about your users.
