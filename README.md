# tracced

Live demo, no sign-up: https://tracced.xyz/project

**Every wallet on the record.** Paste a Solana token, choose the pump range on the chart, and see every wallet that
bought there — and everything it did with the token next. Entry and exit market cap, invested, realized, held
time, bundle funding. Every number is a raw on-chain swap you can open on Solscan. No scores, no black-box
"smart money" labels: you decide who is worth following.

Built on Solana · AI-assisted · Colosseum Crypto World's Fair 2026

![Home](docs/img/home.png)

## How it works

1. **Paste contract** — the token's whole life loads as a market-cap chart.
2. **Choose range** — two clicks on the chart: where buying starts, where the pump takes off. Detected pumps are pre-filled as hints.
3. **Get wallets** — every wallet that bought inside the range, with its whole story on the token: first buy, exits, realized profit, tags. Export CSV / TXT / JSON.

![Range](docs/img/range.png)

![Result](docs/img/result.png)

### Facts, not scores
- **Range** only selects wallets; the numbers come from **all** of a wallet's trades on the token (before, inside and after the range). A scope switch recounts the same trades up to 24 h / 48 h after the range.
- **Tags are rules you can read**: `sniper`, `fresh`, `bot-like`, `pre-range`, `re-bought`, `bundle` (wallets funded from one source), `no-exits`. Hover a tag to see the rule.
- **Complete data by construction**: the range is always fetched in full (verified against the chain: 100% of the swaps in an audited range). For each wallet's history the app takes the cheaper of two complete paths — the whole token history or each wallet's own trades — and tells you the coverage above the table.
- **Repeats**: a wallet that was an early buyer in another analysis you saved carries a `⛓`; its card names those
  analyses with a link to each, and a chip filters the table to them. Computed from your own saved results, no
  labels from anywhere else.
- **Wallet story**: click a wallet to see every trade as a list and as markers on the chart — up to ten wallets at
  once, green bought and red sold, marker size is the amount, trades inside one candle merged into one, and a ring
  around the marker when the wallet was funded together with others in the list.

### Access: the demo for everyone, live mode for wallets
No passwords. The demo token replays without a request and is open to anyone. Any other token is **live mode**: anyone
can open its chart, mark ranges and press **Find the pump**; pressing **Analyze** asks to connect a Solana wallet
(Phantom, MetaMask, Rabby) — the wallet signs a short message, no transaction, no fees — and that signature is the
account; the range survives and runs right after. A wallet gets **one live analysis a day**, a token holds **three
analyses** (delete yours to make room), one run may spend at most **1,000 requests**; results are public and an
existing result opens for everyone, wallet or not. Charts of live tokens cost requests too (≈2 per new token, 1 per
chunk of candles), so browsing has a daily budget: 30 requests per address without a wallet, 150 per wallet, 300 for
the whole site; cached charts are free. The whole site runs at most 10 live analyses a day and one address may start
20 an hour. Wallets listed in `ADMIN_WALLETS` skip the daily run limit, the per-run request cap and the chart budget
(they still get three analyses per token and the AI agent's daily budget). Defaults live in `tracced/early/settings.py`;
override any of them under `early:` in `config.yaml` (`runs_per_day`, `runs_global_per_day`, `runs_per_hour`,
`ranges_per_token`, `run_cap_requests`, `finder_pumps`, `browse_per_day_guest`, `browse_per_day`, `browse_global_per_day`).
A run that fails gives the wallet its day back.

The cost of one new token is set in `config.yaml`: a range is at most **6 h**, exits are fetched for the **250**
largest buyers (the rest keep their entry and get the `no-exits` tag, unless the whole-history path was cheaper, in
which case everyone has exits), buyers under **$95** in the range are left out, and a run stops at **1,000 requests**.

Tick wallets in a result and **+ Watchlist**; **Save analysis** keeps the whole result under **My analyses**. Both live at
`/me`, with notes and CSV / TXT export. The owner sees who connected and what they ran at `/admin`. Accounts are JSON
files under `output/early/accounts/`, actions go to `_events.jsonl` next to them; nothing about accounts leaves the
server. Page-view analytics (Umami Cloud) run only when `UMAMI_WEBSITE_ID` is set.

## Run it

```bash
cp .env.example .env            # SOLANATRACKER_API_KEY, plus WEB_SECRET (openssl rand -hex 32) so sign-ins survive restarts
docker compose up -d --build    # http://127.0.0.1:8095
```

On a server: see [deploy/README.md](deploy/README.md) (one container behind an existing Caddy).

Tests:

```bash
docker compose run --rm --no-deps -v "$PWD/tests:/app/tests" web python -m unittest discover -s tests -t .
```

Settings live in `config.yaml` (`early.plan: free | advanced` sets the request caps for the Solana Tracker plan).

Version: `__version__` in `tracced/__init__.py`, shown in the footer as `v0.2`; bumped on every release to `main`.

## Demo token
Run a finished analysis through `scripts/capture_demo.py` (the docstring has the docker command; several analyses of
one token become several demo ranges): it writes the snapshot `output/early/demo/<mint>.json` and prints the
`early.demo_job` / `early.example_job` lines for `config.yaml`. Pasting that token then replays the whole flow — chart,
range, live terminal, result — without a single request to Solana Tracker. Good for showing the product around.

## Data
- Raw swaps and candles: [Solana Tracker Data API](https://www.solanatracker.io/data-api). Free plan: 10,000 requests/month; a cached analysis costs 0.
- The AI agent: any OpenAI-compatible chat endpoint; by default OpenRouter and a free model (`ASSISTANT_*` in `.env`), with per-wallet, per-guest and site-wide daily limits (`assistant_per_day`, `assistant_per_day_guest`, `assistant_global_per_day`; defaults in `tracced/early/settings.py`, override under `early:` in `config.yaml`).
- Wallet age and funder: public Solana RPC (`api.mainnet-beta.solana.com`; set `SOLANA_RPC_URL` for your own node with full signature history).
- Nothing else. No third-party PnL, labels or scores.

## Roadmap
- **Live** — analyze: range → wallets → whole story → export; bundle and fact tags; Find the pump; the AI agent picks wallets by your method; wallet accounts with a watchlist and saved analyses.
- **Next** — Telegram alerts when a saved wallet trades; the agent explains a whole pump in plain words.
- **Later** — non-custodial copy-trading on your list, strategy in plain words.

The longer story is on the [project page](https://tracced.xyz/project).

## License
MIT
