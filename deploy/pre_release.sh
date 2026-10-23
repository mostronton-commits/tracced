#!/bin/sh
# Before a release to production (the owner runs it: ssh vps 'sh /opt/tracced-dev/deploy/pre_release.sh'):
# the running production image gets a rollback tag, config.yaml and .env are copied beside themselves, and it says
# whether an analysis is running (the self-updating checkout waits for it anyway).
#   back to it: docker tag tracced-web:rollback-<sha> tracced-web:latest, then
#   cd /opt/tracced && docker compose -f compose.vps.yml up -d --force-recreate web (and revert main on GitHub)
set -eu
cd /opt/tracced
sha=$(git rev-parse --short HEAD)
stamp=$(date -u +%Y%m%d-%H%M)
docker tag tracced-web:latest "tracced-web:rollback-$sha"
cp -p config.yaml "config.yaml.bak-$stamp-release"
cp -p .env ".env.bak-$stamp-release"
busy=$(docker compose -f compose.vps.yml exec -T web python -c \
  "import urllib.request,os,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','8095')+'/health', timeout=5)); print(int(d.get('running') or 0)+int(d.get('queued') or 0))" 2>/dev/null || echo "?")
echo "ready: production $sha tagged tracced-web:rollback-$sha; config.yaml and .env copied (*.bak-$stamp-release)"
[ "$busy" = "0" ] || echo "note: analyses running or queued: $busy (the deploy waits for them)"
