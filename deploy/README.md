# Deploy on a VPS

One container, no public port. HTTPS comes from the Caddy that already serves the server's other sites.

1. `git clone https://github.com/mostronton-commits/tracced /opt/tracced && cd /opt/tracced`
2. `cp .env.example .env` and fill in `SOLANATRACKER_API_KEY`, `WEB_SECRET` (random string; signs the wallet cookies, without it a restart signs everyone out), `ADMIN_WALLETS` (your wallet address: opens `/admin`, skips the daily run limit, the per-run request cap and the chart budget),
   `PROXY_NETWORK` (the Docker network of the Caddy container, `docker network ls`), and the `ASSISTANT_*` lines if the AI agent should be on.
3. Optional demo: copy `output/early/demo/<mint>.json` and the example analysis `output/early/web/<id>.json`
   from the machine where they were made (`scripts/capture_demo.py` builds them); the ids are in `config.yaml`.
4. `docker compose -f compose.vps.yml up -d --build`
5. Point the domain's A record at the server, then run `bash deploy/enable_domain.sh <domain> "<Caddyfile path>" <caddy container>`:
   it appends a site block for `<domain>` and `www.<domain>` (the same block as `deploy/Caddyfile.snippet`: compression,
   security headers, reverse proxy) with a backup and reloads Caddy only if the config validates. Caddy fetches the certificate itself.
   To point a domain at another container later (the dev site, a rollback container):
   `bash deploy/set_upstream.sh <domain> "<Caddyfile path>" <caddy container> tracced-dev-web`.

Update by hand: `git pull && docker compose -f compose.vps.yml up -d --build`. Analyses, accounts, daily counters and caches
live in `output/` and `cache/` on the host and survive rebuilds. Do not edit `config.yaml` on the server: it is tracked by
git, a local edit blocks the self-updating checkout (see below) and a rollback would discard it — change it in the
repository instead.

## Self-updating checkout

`bash deploy/autodeploy.sh install /opt/tracced-dev compose.dev.yml` (dev) or
`bash deploy/autodeploy.sh install /opt/tracced compose.vps.yml` (production) adds a cron line: every minute the server
asks GitHub whether the checked-out branch moved; when it did, it waits for a running analysis to finish (up to 10 min),
pulls, builds, starts the new container and checks `/health`. If the build fails or the new container does not answer,
it goes back to the previous commit, rebuilds it, and marks the rejected commit so it is not retried until a new push.
Log: `/var/log/tracced-autodeploy.log` (`AUTODEPLOY_LOG` to change). `remove` takes the cron line out again. The server
needs no GitHub secret: it only reads a public repository, so the only way to deploy is to push to that branch.

## Promote dev → main (production)

1. Back up production data on the VPS: `tar czf ~/tracced-prod-$(date +%F).tgz -C /opt/tracced output cache .env`.
2. In `/opt/tracced/.env` make sure these exist: `WEB_SECRET` (`openssl rand -hex 32`), `ADMIN_WALLETS`, the `ASSISTANT_*`
   lines (OpenRouter API key with free endpoints allowed), `PROXY_NETWORK`; delete any `WEB_PASSWORD` line (no passwords
   any more).
3. Copy the demo snapshot and the example analysis from the dev checkout if production lacks them:
   `cp -n /opt/tracced-dev/output/early/demo/*.json /opt/tracced/output/early/demo/` and the `output/early/web/<example id>.json` named in `config.yaml`.
4. `cd /opt/tracced && git status` must be clean.
5. Merge `dev` into `main` on GitHub.
6. First time: `cd /opt/tracced && git pull && bash deploy/autodeploy.sh install /opt/tracced compose.vps.yml`.
   From then on every push to `main` deploys itself.
7. Check `docker compose -f compose.vps.yml logs --tail 50 web`, open the site, run the demo, connect the admin wallet.

## Backups and logs

Everything users create is under `output/early` (accounts, saved analyses, events, daily counters, the demo snapshot).
A daily copy, kept two weeks:
`0 4 * * * tar czf /var/backups/tracced/early-$(date +\%F).tgz -C /opt/tracced output/early && find /var/backups/tracced -name 'early-*.tgz' -mtime +14 -delete`
(create `/var/backups/tracced` once). Copy the archives off the box now and then. Container logs are capped by the
compose files (5 × 20 MB per container).
