#!/usr/bin/env bash
# Adds the tracced site block to the Caddy that owns ports 80/443 on this server and reloads it with no downtime.
# Usage: bash deploy/enable_domain.sh <domain> "<path to the Caddyfile on the host>" <caddy container name> [upstream container, default tracced-web]
# A backup of the Caddyfile is kept next to it; if Caddy rejects the new config, the old one is restored.
set -euo pipefail
DOMAIN="${1:?domain}"; FILE="${2:?path to the Caddyfile}"; CADDY="${3:?caddy container name}"; UP="${4:-tracced-web}"
if grep -q "^${DOMAIN}" "$FILE"; then echo "already enabled: ${DOMAIN}"; exit 0; fi
BAK="${FILE}.bak-$(date +%F-%H%M)"
cp "$FILE" "$BAK"; echo "backup: ${BAK}"
if [ "$UP" = "tracced-web" ]; then HOSTS="$DOMAIN, www.$DOMAIN"; else HOSTS="$DOMAIN"; fi
printf '\n# tracced (added %s; upstream = container %s)\n%s {\n    encode zstd gzip\n    header {\n        Strict-Transport-Security "max-age=31536000"\n        X-Content-Type-Options nosniff\n        Referrer-Policy strict-origin-when-cross-origin\n        Content-Security-Policy "frame-ancestors '"'"'none'"'"'; object-src '"'"'none'"'"'; base-uri '"'"'self'"'"'"\n    }\n    reverse_proxy %s:8095\n}\n' "$(date +%F)" "$UP" "$HOSTS" "$UP" >> "$FILE"
if docker exec "$CADDY" caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile
  echo "done: ${DOMAIN} is served; the HTTPS certificate arrives by itself once DNS points at this server"
else
  cp "$BAK" "$FILE"; echo "Caddy rejected the config — the previous Caddyfile is restored, nothing changed"; exit 1
fi
