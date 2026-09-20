# tracced

Live demo, no sign-up: https://tracced.xyz/project

**Every wallet on the record.** Paste a Solana token, choose the pump range on the chart, and see every wallet that
bought there — and everything it did with the token next. Entry and exit market cap, invested, realized, held
time, bundle funding. Every number is a raw on-chain swap you can open on Solscan. No scores, no black-box
"smart money" labels: you decide who is worth following.

Built on Solana · AI-assisted (coming next) · Colosseum Crypto World's Fair 2026

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
- **Wallet story**: click a wallet to see every trade as a list and as markers on the chart.

### Your account: a wallet, not a password
Sign in with a Solana wallet (Phantom, Solflare, Backpack or any Wallet Standard wallet): the wallet signs a short
message — no transaction, no fees — and that signature is the account. Tick wallets in a result and **Save to my list**;
**Save analysis** keeps the whole result under **My analyses**. Both live at `/me`, with notes and CSV / TXT export.
Signing in does not unlock live analyses of new tokens: that stays behind the beta password while the free API quota lasts.
Saving from the demo result needs no password, so anyone can try the account.

The owner sees who connected and what they did at `/admin`: set `ADMIN_WALLETS` to your own wallet address and connect it.
Accounts are JSON files under `output/early/accounts/`, actions go to `_events.jsonl` next to them; nothing leaves the server.

## Run it

```bash
cp .env.example .env            # SOLANATRACKER_API_KEY, plus WEB_SECRET (openssl rand -hex 32) so sign-ins survive restarts
docker compose up -d --build    # http://127.0.0.1:8095
```

On a server: see [deploy/README.md](deploy/README.md) (one container behind an existing Caddy, password on).

Tests:

```bash
docker compose run --rm --no-deps -v "$PWD/tests:/app/tests" web python -m unittest discover -s tests -t .
```

Settings live in `config.yaml` (`early.plan: free | advanced` sets the request caps for the Solana Tracker plan).

Version: `__version__` in `tracced/__init__.py`, shown in the footer as `v0.2`; bumped on every release to `main`.

## Demo token
Set `early.demo_job` in `config.yaml` to a finished analysis and put its snapshot in `output/early/demo/<mint>.json`
(info, candles, range). Pasting that token then replays the whole flow — chart, range, live terminal, result — without a
single request to Solana Tracker. Good for showing the product around.

## Data
- Raw swaps and candles: [Solana Tracker Data API](https://www.solanatracker.io/data-api). Free plan: 2,500 requests/month; a cached analysis costs 0.
- Wallet age and funder: public Solana RPC (`api.mainnet-beta.solana.com`; set `SOLANA_RPC_URL` for your own node with full signature history).
- Nothing else. No third-party PnL, labels or scores.

## Roadmap
- **Live** — analyze: range → wallets → whole story → export; bundle and fact tags; sign in with a wallet, save wallets and analyses to your account.
- **Next** — Telegram alerts when a saved wallet trades; the AI agent picks wallets by your method and suggests the range.
- **Later** — non-custodial copy-trading on your list, strategy in plain words.

See [docs/strategy.md](docs/strategy.md).

## License
MIT
