#!/bin/sh
# Which copy of the site answers @tracced_bot and sends the alerts (owner, 20.10). Telegram lets one server read a bot's
# messages, and production and dev share the bot's key, so the bot lives in one place at a time:
#   sh deploy/tg_bot_switch.sh dev    # a test: the bot and the alerts move to dev.tracced.xyz
#   sh deploy/tg_bot_switch.sh prod   # back to tracced.xyz
# Both .env files are copied first (.env.bak-<time>-tg); a running analysis on either copy stops the switch.
set -eu
PROD=/opt/tracced
DEV=/opt/tracced-dev
MODE=${1:-}
case "$MODE" in
  dev)  OFF=$PROD; OFF_C=compose.vps.yml; ON=$DEV; ON_C=compose.dev.yml ;;
  prod) OFF=$DEV; OFF_C=compose.dev.yml; ON=$PROD; ON_C=compose.vps.yml ;;
  *) echo "usage: sh $0 dev|prod"; exit 2 ;;
esac

health() {                        # /health of the copy in $1 (compose file $2): {running, queued} or nothing
  (cd "$1" && docker compose -f "$2" exec -T web python -c \
    "import urllib.request,os,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','8095')+'/health', timeout=5)); print(int(d.get('running') or 0)+int(d.get('queued') or 0))" 2>/dev/null)
}
set_alerts() {                    # ALERTS=$3 in $1/.env, after a copy of the file
  cp -p "$1/.env" "$1/.env.bak-$STAMP-tg"
  if grep -q '^ALERTS=' "$1/.env"; then sed -i "s/^ALERTS=.*/ALERTS=$3/" "$1/.env"; else echo "ALERTS=$3" >> "$1/.env"; fi
  echo "$1: $(grep '^ALERTS=' "$1/.env")"
}

for pair in "$OFF $OFF_C" "$ON $ON_C"; do
  set -- $pair
  n=$(health "$1" "$2" || echo "?")
  if [ "$n" != "0" ]; then echo "$1: an analysis is running (or the site does not answer: $n). Try again in a few minutes."; exit 1; fi
done

STAMP=$(date -u +%Y%m%d-%H%M)
set_alerts "$OFF" "$OFF_C" 0
set_alerts "$ON" "$ON_C" 1
(cd "$OFF" && docker compose -f "$OFF_C" up -d --force-recreate web >/dev/null 2>&1)   # first the old one lets go of the bot
sleep 5
(cd "$ON" && docker compose -f "$ON_C" up -d --force-recreate web >/dev/null 2>&1)
for i in $(seq 1 24); do
  if [ "$(health "$ON" "$ON_C" || true)" = "0" ] && [ "$(health "$OFF" "$OFF_C" || true)" = "0" ]; then
    echo "done: the bot now answers from $ON. Back: sh $0 $([ "$MODE" = dev ] && echo prod || echo dev)"
    exit 0
  fi
  sleep 5
done
echo "the sites did not answer within 2 minutes: check docker compose logs web in $ON and $OFF"
exit 1
