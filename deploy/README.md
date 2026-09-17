# Deploy on a VPS

One container, no public port. HTTPS comes from the Caddy that already serves the server's other sites.

1. `git clone https://github.com/mostronton-commits/tracced /opt/tracced && cd /opt/tracced`
2. `cp .env.example .env` and fill in `SOLANATRACKER_API_KEY`, `WEB_PASSWORD` (the site is public: keep it set),
   `PROXY_NETWORK` (the Docker network of the Caddy container, `docker network ls`).
3. Optional demo: copy `output/early/demo/<mint>.json` and the example analysis `output/early/web/<id>.json`
   from the machine where they were made; the ids are in `config.yaml`.
4. `docker compose -f compose.vps.yml up -d --build`
5. Point the domain's A record at the server, then run `bash deploy/enable_domain.sh <domain> "<Caddyfile path>" <caddy container>`:
   it appends `deploy/Caddyfile.snippet` with a backup and reloads Caddy only if the config validates. Caddy fetches the certificate itself.

Update: `git pull && docker compose -f compose.vps.yml up -d --build`. Analyses and caches live in
`output/` and `cache/` on the host and survive rebuilds.
