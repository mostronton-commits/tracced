# Early Wallets — strategy (September 2026)

**Thesis.** Early Wallets shows who was there first — with receipts. Paste a Solana token, mark the pump on the
chart, and see every wallet that bought inside that range and everything it did with the token afterwards: entry
and exit market cap, invested, realized, held time, bundle funding. Every number is a raw on-chain swap you can open
on Solscan. No scores and no "smart money" labels from a black box: the user decides who is worth following; the app
gives the facts, then follows the wallets for the user, then trades for the user.

**Slogan.** every wallet on the record (home: `tracced` on one line, the slogan under it; same line in the footer).

## Stages

| Stage | For the user | To build | Money |
|---|---|---|---|
| 1 · Analyze (live) | pump → wallets → their whole story → export; bundle and fact tags; the assistant picks wallets to watch by your method | name, public repo, public demo | free (traction, feedback) |
| 1.5 · Accounts & quota | sign in, own analyses, daily quota | wallet sign-in (message signature) or email link; Postgres; shared trade cache; queue with priority | Free 2 new analyses/day · Pro · pay-as-you-go |
| 2 · Watchlist & alerts | save wallets, get alerts when they buy a new token or move on one you follow | watchlists; live trade feed (Solana Tracker WebSocket or RPC); Telegram bot; the assistant suggests the range | Free: 1 list of 10, delayed alerts · Pro: unlimited, instant |
| 3 · Copy-trading | follow the watchlist with rules, non-custodial | executor (Relay + Privy, already built in another product); strategy as an entity; the assistant turns plain words into rules; trade log | Copy tier + fee on copied trades |
| 4 · Platform | API, teams, other chains | public API, EVM sources (Alchemy), white-label | API tiers, partners |

The order is fixed: no money and no quotas without 1.5; no copy-trading without a watchlist. Stage 2 is the shortest
path to the first payment: alerts are a daily habit, an analysis is an event.

## The assistant across the stages
- Stage 1 (live): "Ask the assistant" — reads only the facts in the result table and the user's method, returns a
  short list of wallets with a one-sentence reason each. No prediction, no hidden data.
- Stage 2: proposes the range on the chart (from the pump detector and candles) and explains why.
- Stage 3: turns a strategy described in plain words into rules for the executor; explains every rule back.
- Stage 3+: reads the results of the watchlist over time, proposes to prune wallets that stopped working, flags what
  changed. Always with the facts it used, never as a verdict.

## Pricing (proposal)
- **Free** — 2 new analyses a day (cached analyses and pinned examples are free and uncounted), whole-history
  scope, CSV export, 1 watchlist of 10 wallets, alerts delayed by 5 minutes.
- **Pro — $29/month** ($24 yearly) — 30 analyses a day, all scopes, unlimited watchlists, instant Telegram alerts,
  history of analyses, priority queue.
- **Pay-as-you-go — $5 for 10 analyses**, valid 90 days.
- **Copy — $49/month + 10% of realized profit** on copied trades (or 0.5% of volume if performance fees are legally
  simpler). Non-custodial: the fee is taken as an app fee in the swap route, so the app never holds funds.
- **Team / API** — later, from $199/month.

Unit economics: Solana Tracker Advanced = €50 for 200,000 requests ≈ €0.00025 per request. A hot-token analysis
≈ 300–600 requests ≈ €0.08–0.15; an analysis from cache ≈ 0. A Pro user at 30 analyses a day costs at most ≈ €4 of
data a month. Break-even at VPS €20 + data €50 + free RPC = **3 Pro subscriptions**. Free is capped on *new* analyses
because every paid analysis fills the shared cache and makes the next ones free.

## Metrics to show
Analyses per day · 7-day return rate · watchlists created · alerts delivered · Free→Pro conversion · for Copy:
copied volume and fees collected. All countable from the stage-1.5 database.

## Scaling

**What the cost is made of** (measured on PAID, 17 Sep 2026). An analysis needs, for every wallet that bought
in the range, its whole story on the token. Two ways to get it:

| Path | Cost on PAID's three pump ranges | What it leaves behind |
|---|---|---|
| One request per wallet | ~6,250 requests | nothing — the next user pays again |
| The token's trade history, once | ~1,800 pages (450k trades) | a cache every later range and user reuses |

So the bill scales with **tokens touched**, not with users or analyses — as long as the run takes the second
path. Two things used to push it to the first: the free plan's page caps, and an estimate that carried the
pump's trade rate (500+/min) across the quiet hours that follow (~50/min), overstating the full path 3-4x.
The estimate is now measured with a few probe pages (`budget.pages_from_rates`).

**Rough budget at 200 active users a day:** 12,000 analyses a month over 400–800 unique tokens, ~200 pages
each on average ≈ 130,000 requests — inside the €50 / 200,000 Advanced tier. A thousand users needs the next
tier or an own index.

**What breaks first, in order.** (1) Disk: trades are JSONL per token and one hot token is ~170 MB, so
hundreds of tokens a month fill the VPS within months — needs a database and eviction of cold tokens.
(2) Latency: 1,800 pages is ~90 s at the Advanced pace, so the terminal has to stay honest about progress.
(3) The API tier itself. The endgame is an own indexer on a Geyser/gRPC stream, worth it only once paid
subscriptions exist.

- **Data.** One vendor today (Solana Tracker). Mitigations: shared cache; on-chain completeness audit built in;
  a second source (Helius parsed transactions or an own swap parser for pump.fun / PumpSwap / Raydium) at stage 4.
- **Compute.** Today one worker and JSON files. Stage 1.5: Postgres, a queue with several workers, paid users first.
- **Alerts.** One WebSocket for all watched wallets, fan-out to Telegram; the limit is unique wallets, not users.
- **Copy-trading.** The executor exists; a "strategy" entity and an API between analyzer and executor are missing.
- **Legal.** Non-custodial, "a tool, not advice"; a performance fee sold as software, not asset management;
  jurisdiction chosen before stage 3.

## Analytics & operations (after the domain)
Plausible or Umami self-hosted on the VPS (no cookie banners) for visits and the funnel; an internal `/admin`
behind a password: analyses per day, requests spent and Solana Tracker credits left, queue and errors, top tokens,
Free→Pro conversion; Telegram alerts to the founder on failures or an exhausted quota; logs in one place.

## Hackathon (Crypto World's Fair, submit by 12 Oct 2026)
Pitch (≤3 min, a startup pitch, not a demo): the problem (after every pump everyone asks who knew; the answer is
buried in thousands of swaps; trackers sell other people's scores), the product in 30 seconds (paste → mark →
wallets → story → bundle → export → assistant), the proof (100% of swaps in the audited range, reference checks,
first users), the model (Free → Pro → Copy with fees, cost per analysis), the road (Phase 1 live, Phase 2 next
with a sketch, Phase 3 with an executor that already exists), the team and why full-time. Tech demo (2–3 min):
raw swaps → ledger → scope; coverage cache; cheapest complete path; background enrichment from RPC; why no scores.
Checklist: name + domain · public repo (product only, README, screenshots, licence) · public demo with the Free
quota and pinned examples · pitch video · tech video · 8 slides · track: Consumer Apps · 5–10 users with quotes.

## Open decisions
- Pro price anchor $19 / $29 / $49 — recommended $29 with a yearly discount.
- Copy fee: 10% of profit (stronger pitch, harder accounting) vs 0.5% of volume (simple) — start with volume,
  promise the performance model.
- First user: retail memecoin trader (mass, Free→Pro) vs semi-pro with own bots (fewer, pays for API) — the first
  for the hackathon, the second in the roadmap.
- Solana Tracker Advanced (€50) before any public demo, or the Free quota is gone in a day.
- The product name.
