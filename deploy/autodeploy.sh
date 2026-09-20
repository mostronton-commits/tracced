#!/usr/bin/env bash
# Self-updating site: every minute cron asks GitHub whether the branch moved; if it did, pull, rebuild,
# check /health, and roll back to the previous commit when the new container does not answer.
#
#   bash deploy/autodeploy.sh install /opt/tracced-dev compose.dev.yml   # once: adds the cron line, deploys now
#   bash deploy/autodeploy.sh run     /opt/tracced-dev compose.dev.yml   # what cron runs
#   bash deploy/autodeploy.sh remove  /opt/tracced-dev                   # stop auto-deploying this checkout
#
# Nothing here needs a GitHub secret on the server: the checkout is public and read-only for the server.
set -euo pipefail
MODE=${1:-run}; DIR=${2:-/opt/tracced-dev}; COMPOSE=${3:-compose.dev.yml}
LOG=${AUTODEPLOY_LOG:-/var/log/tracced-autodeploy.log}
LOCK="/tmp/tracced-autodeploy-$(echo "$DIR" | tr '/' '_').lock"
SELF="$DIR/deploy/autodeploy.sh"
say() { echo "$(date -u +%FT%TZ) [$DIR] $*"; }

healthy() {                       # ask the container itself; python is always there, curl is not
  docker compose -f "$COMPOSE" exec -T web python -c \
    "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','8095')+'/health', timeout=5).status==200 else 1)" >/dev/null 2>&1
}

run() {
  cd "$DIR"
  git fetch -q origin
  BR=$(git rev-parse --abbrev-ref HEAD)
  LOCAL=$(git rev-parse HEAD); REMOTE=$(git rev-parse "origin/$BR")
  [ "$LOCAL" = "$REMOTE" ] && [ "${FORCE:-0}" != "1" ] && exit 0
  say "new commits on $BR: ${LOCAL:0:7} -> ${REMOTE:0:7}"
  git pull -q --ff-only origin "$BR"
  docker compose -f "$COMPOSE" up -d --build 2>&1 | tail -3
  sleep 8
  for i in 1 2 3 4 5; do healthy && { say "deployed $BR $(git rev-parse --short HEAD), /health ok"; exit 0; }; sleep 5; done
  say "new container does not answer /health: rolling back to ${LOCAL:0:7}"
  git reset -q --hard "$LOCAL"
  docker compose -f "$COMPOSE" up -d --build 2>&1 | tail -3
  sleep 8
  healthy && say "rolled back to ${LOCAL:0:7}, /health ok" || say "ROLLBACK FAILED: the site may be down"
  exit 1
}

case "$MODE" in
  run) exec 9>"$LOCK"; flock -n 9 || exit 0; run ;;
  install)
    [ -f "$SELF" ] || { echo "no $SELF — pull the repo first"; exit 1; }
    LINE="* * * * * bash $SELF run $DIR $COMPOSE >> $LOG 2>&1"
    ( crontab -l 2>/dev/null | grep -v -F "$SELF" ; echo "$LINE" ) | crontab -
    touch "$LOG" 2>/dev/null || true
    echo "cron line installed:"; echo "  $LINE"
    echo "deploying now…"; FORCE=1 bash "$SELF" run "$DIR" "$COMPOSE" || true      # even if the pull already happened by hand
    echo "log: $LOG" ;;
  remove)
    ( crontab -l 2>/dev/null | grep -v -F "$SELF" ) | crontab -
    echo "removed the cron line for $DIR" ;;
  *) echo "usage: $0 install|run|remove <dir> <compose file>"; exit 2 ;;
esac
