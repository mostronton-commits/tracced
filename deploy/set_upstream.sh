#!/usr/bin/env bash
# Points an existing site block in the shared Caddy at a different upstream container.
# Keeps a backup; reloads only if Caddy accepts the new config, otherwise restores the old file.
# Usage: bash deploy/set_upstream.sh <domain> "<Caddyfile path>" <caddy container> <upstream container>
set -euo pipefail
DOMAIN="${1:?domain}"; FILE="${2:?Caddyfile path}"; CADDY="${3:?caddy container}"; UP="${4:?upstream container}"
grep -qE "^${DOMAIN}(,| )" "$FILE" || { echo "no block for ${DOMAIN} in ${FILE}"; exit 1; }
BAK="${FILE}.bak-$(date +%F-%H%M%S)"; cp "$FILE" "$BAK"; echo "backup: ${BAK}"
awk -v d="$DOMAIN" -v up="$UP" '
  $0 ~ "^" d "(,| )" { inblk = 1; $0 = d " {" }
  inblk && /reverse_proxy/ { $0 = "    reverse_proxy " up ":8095" }
  { print }
  inblk && /^}/ { inblk = 0 }
' "$BAK" > "$FILE"
if docker exec "$CADDY" caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  docker exec "$CADDY" caddy reload --config /etc/caddy/Caddyfile
  echo "done: ${DOMAIN} now goes to ${UP}"
else
  cp "$BAK" "$FILE"; echo "Caddy rejected the config, restored the previous file, nothing changed"; exit 1
fi
