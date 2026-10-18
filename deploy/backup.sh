#!/bin/sh
# Nightly copy of what users create on tracced and what it takes to bring the site back:
# output/ (accounts, saved analyses, the usage log, the agent's method, partner keys, daily counters, the demo),
# config.yaml and .env. Not cache/ (rebuilt from the data provider) and not old backup-* folders.
# The owner's Mac pulls these archives to an external SSD every day (deploy/README.md, "Backups").
#   0 3 * * * sh /opt/tracced/deploy/backup.sh >> /var/log/tracced-backup.log 2>&1
set -eu
SRC=${1:-/opt/tracced}
DEST=${2:-/root/backups/tracced}
KEEP_DAYS=${KEEP_DAYS:-7}

umask 077                                   # the archive holds .env: only root reads it
mkdir -p "$DEST"
stamp=$(date -u +%Y%m%d-%H%M)
part="$DEST/tracced-$stamp.tgz.part"
tar -czf "$part" -C "$SRC" --exclude='output/early/backup-*' output config.yaml .env
mv "$part" "$DEST/tracced-$stamp.tgz"       # a half-written archive never looks finished to the Mac
find "$DEST" -name 'tracced-*.tgz' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'tracced-*.tgz.part' -mmin +120 -delete
echo "$(date -u +%FT%TZ) backup $DEST/tracced-$stamp.tgz $(du -h "$DEST/tracced-$stamp.tgz" | cut -f1)"
