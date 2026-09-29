# API (beta)

Check a Solana token in one request: the level of each of nine rules, and whether it passes the thresholds set for
your key. Answers in under a second. No scores: every rule is a fact with its limits written below. Keys are by
invitation: ask through [Contact](/feedback) or on [X](https://x.com/tracced_xyz).

## Request

```
GET https://tracced.xyz/api/v1/check?mint=<token address>
Authorization: Bearer <your key>
```

Send the key only in this header, never in the address.

## Response

```json
{
  "mint": "<token address>",
  "passes": false,
  "failed": ["bundle"],
  "high": ["bundle", "bundled_launch"],
  "flags": "2 of 9",
  "levels": {
    "dev": "low", "bundle": "high", "top10": "medium",
    "snipers": "medium", "insiders": "low", "bundled_launch": "high",
    "mint": "low", "freeze": "low", "liquidity": "low"
  },
  "age_minutes": 2,
  "cached": false,
  "checked_at": "2026-09-29T10:00:00Z"
}
```

| Field | Meaning |
|---|---|
| `passes` | `true` when the creator, launch bundles and the ten largest holders all stay within your key's thresholds, agreed with you |
| `failed` | The thresholds it missed. `no_data`: one of those shares is unknown, so the check fails rather than guesses. `rugged`: the pool's liquidity is gone |
| `high`, `flags` | The rules at level high, and their count out of nine |
| `levels` | Each rule: `low`, `medium`, `high` or `unknown` |
| `age_minutes` | Minutes since the token was created |
| `cached` | The same token was checked less than a minute ago, and this is that answer |

## Rules

Shares are of the whole supply. Anything below medium is low.

| Rule | Medium | High |
|---|---|---|
| `dev`<br>The creator's share | {{ API.CUTS.dev[0] }}–{{ API.CUTS.dev[1] }}% | over {{ API.CUTS.dev[1] }}% |
| `bundle`<br>Wallets from launch bundles, their share now | {{ API.CUTS.bundle[0] }}–{{ API.CUTS.bundle[1] }}% | over {{ API.CUTS.bundle[1] }}% |
| `top10`<br>The ten largest holders, without pools | {{ API.CUTS.top10[0] }}–{{ API.CUTS.top10[1] }}% | over {{ API.CUTS.top10[1] }}% |
| `snipers`<br>Wallets that bought in the first seconds, their share now | {{ API.CUTS.snipers[0] }}–{{ API.CUTS.snipers[1] }}% | over {{ API.CUTS.snipers[1] }}% |
| `insiders`<br>Wallets linked to the creator, their share now | {{ API.CUTS.insiders[0] }}–{{ API.CUTS.insiders[1] }}% | over {{ API.CUTS.insiders[1] }}% |
| `bundled_launch`<br>What bundles took at launch, even if sold since | {{ API.CUTS.bundled_launch[0] }}–{{ API.CUTS.bundled_launch[1] }}% | over {{ API.CUTS.bundled_launch[1] }}% |
| `mint`<br>The creator can still mint more tokens | — | enabled |
| `freeze`<br>The creator can freeze holders' tokens | — | enabled |
| `liquidity`<br>The largest pool | ${{ '{:,}'.format(API.LIQ_HIGH) }}–{{ '{:,}'.format(API.LIQ_MEDIUM) }} | under ${{ '{:,}'.format(API.LIQ_HIGH) }}, or under {{ API.LP_BURN_MIN }}% of its LP burned |

A token still on its launchpad curve counts as low on liquidity. DLMM, CLMM and Whirlpool pools have no LP to burn, so
only their size counts.

Early numbers change within minutes: check again right before a buy. No check catches everything, so treat this one
as a filter, not a guarantee.

## Limits and errors

A key takes up to 5 requests a second and has a daily limit agreed with you. The day resets at 00:00 UTC. A key can
also be tied to your servers' addresses, and then it works from nowhere else.

| Status | When |
|---|---|
| 400 | Not a Solana token address |
| 401 | The key is missing or unknown |
| 403 | The key is switched off, or used from an address it is not tied to |
| 404 | The data source does not know this token |
| 429 | Over 5 requests a second, today's limit used up, or too many wrong keys |
| 502 | The data source did not answer; retry in a few seconds |
| 503 | Checks are paused on our side; retry later |

## Terms of use (beta)

Using a key means accepting these terms.

- **Keep the key on your server:** never in a web page, an app or a public repository. If it leaks, tell us and we
  will issue a new one.
- **Use the answers in your own product.** Showing a token's levels to your users is fine, with "rules by tracced" and
  a link to this page. Reselling them, or passing them on as a dataset, is not.
- **Never call a token "safe", "audited" or "verified by tracced".** The check reports facts against written rules;
  it says nothing about where a price goes.
- **Provided as is, without warranty, and not financial advice.** tracced is not liable for losses from decisions made
  with it.
- **The rules, the limits and this page can change, and a key can be switched off, at any time.** The check is free
  during the beta.
- **For each call we keep the key, the token, the time and the result,** to run the service. Nothing about your users.
