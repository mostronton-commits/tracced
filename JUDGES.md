# tracced · a guide for the judges

**tracced finds the wallets that bought before a pump.** Paste a Solana token, mark the time range before it took off,
and get every wallet that bought inside that range, with what it paid, sold and earned on this token. Every number is
counted by tracced from the wallet's own swaps and links to the transaction on Solscan. No scores, no third-party
"smart money" labels.

- Live: **https://tracced.xyz** (free in beta)
- Started: **September 17, 2026**. 12 releases since then (0.1 → 0.7.4), 325 commits, 522 tests.
- Today: 33,100 wallets on the record, 132 tokens analyzed, 202,000 trades processed.

## Try it in two minutes

1. **No wallet needed:** open https://tracced.xyz and press **Demo** in the bar at the bottom. A real token opens with
   its recorded pumps as tabs. Press **Get wallets**: the recorded run replays and the result appears under the chart.
2. **A token of your own:** paste a Solana token address on the home page (or click one in the *Fresh pumps* tape), click
   the chart where buying starts and where the pump takes off, press **Get wallets**. A live run needs a connected
   wallet: sign in with Phantom, Solflare or Backpack. It is a message signature, never a transaction. A new or empty
   wallet gets one live analysis a day; the Demo has no limit.
3. **In the result:** sort by ROI, filter (Bought $50+, hide bot-like wallets), open a wallet's card (its trades on this
   token and its last 30 days on every token), star it to follow it, ask the AI agent about the analysis.

## How a result is built

```
token + range ──► Solana Tracker swaps (cached by time span) ──► wallets that bought inside the range
     ──► each wallet's whole history on this token ──► our ledger: average cost, realized PnL, ROI, hold
     ──► tags from the numbers (9 rules) ──► enrichment: wallet age and first funder from Solana RPC, identities
     ──► the result page under the chart (a tab per analyzed range)
```

| Step | Where in the code |
|---|---|
| Orchestration: range → buyers → their trades → table | `tracced/early/pipeline.py` |
| Swaps of a token, cached by covered time spans (a repeat costs 0 requests) | `tracced/early/store.py`, `tracced/early/st_client.py` |
| The ledger: every buy and sell → facts (average cost method) | `tracced/early/ledger.py` |
| Tags, each one checkable on chain (sniper, bundle, fresh, bot-like…) | `tracced/early/tags.py` |
| Wallet age and first funder, straight from Solana RPC | `tracced/early/wallet_age.py` |
| Queue of runs, results on disk | `tracced/web/jobs.py` |
| The token page: chart, ranges as tabs, the live run line | `tracced/web/static/tokenpage.js`, `chart.js` |
| The result: table, filters, saved views, wallet card | `tracced/web/static/result.js`, `card.js` |

## The numbers, defined

- **Bought:** everything the wallet bought of this token, before, inside and after the range. Under it: what it bought
  inside the range and the market cap there.
- **Sold:** what it received for its sells, and the share of its tokens sold.
- **PnL:** received minus what the sold tokens cost at the wallet's average price. Unsold tokens are shown apart.
- **ROI:** average exit market cap ÷ average entry market cap.
- **Held:** how long it held what it sold, on average, weighted by amount: $999 sold after 2 seconds and $1 after a
  day is about a minute and a half, not 2 seconds and not a day. Tokens still held are not in it.

We check our numbers against the chain. On 7 October, 28 wallets from 3 public analyses: all 584 of our trades are in
GMGN too; a trade's amount is within 1% of the chain (median); the realized profit of wallets that sold out is within
1.55% of the chain (median), against 4.8% for GMGN. One known gap: Solana Tracker misses most trades made through the
Terminal (Padre) app (19 of 20 in that check); reading those wallets' trades straight from the chain is on our list.

## Beyond one analysis

- **Wallet card:** the last 7 or 30 days of a wallet on every token, counted by the same ledger
  (`tracced/early/profile.py`).
- **Watchlists and Telegram alerts:** follow wallets and get their buys and sells in Telegram within seconds, from the
  official Solana node's stream (`tracced/web/alerts.py`).
- **AI agent:** answers questions about the analysis on screen only. The numbers come from the code, the model only
  picks and words them, and the code checks every answer against the analysis before it is shown
  (`tracced/early/agent.py`).
- **Ready lists:** last month's top traders, people only, profit counted by our ledger (`tracced/early/ready.py`).
- **Partner API (beta):** a token check by rules for other apps (`tracced/web/partner_api.py`); a team from this
  hackathon uses it.

## Engineering notes

- **Stack:** Python (aiohttp, Jinja2), vanilla JavaScript, Docker, Caddy, one VPS. `main` deploys to production, `dev`
  to a private staging server.
- **Data:** Solana Tracker (swaps, candles, wallet trades), Solana RPC (wallet age, funders), DexScreener (paid
  promotions on the chart). Wallet sign-in: Sign in with Solana (`tracced/web/accounts.py`).
- **Cost control:** every paid request goes through daily and monthly budgets; swaps and candles are cached on disk.
- **Privacy:** visits are counted with Umami, without cookies or addresses; nothing is sold or shared.
- **Tests:** `docker compose run --rm --no-deps -v "$PWD/tests:/app/tests" web python -m unittest discover -s tests -t .`
- **Docs** live in `docs/` and are served by the app at https://tracced.xyz/docs; `docs/updates.md` lists every release.
- **Built with AI:** the founder is not a programmer. The product is built with Claude Code (Anthropic) as the
  engineering team; every change goes through tests, a staging server and the founder's review before production.

## What is next

1. **Copy-trading:** copy the wallets you found in one click, executed through Relay; a fee per copied trade.
2. **EVM:** BSC first (four.meme), then Base and Robinhood Chain; data vendors are already compared.
3. **AI that runs your strategy:** the agent moves from explaining an analysis to acting on your own rules.

Questions: https://t.me/tracced_xyz · https://x.com/tracced_xyz
