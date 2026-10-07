#!/bin/sh
# publish site/ when GitHub main is ahead of what was last deployed
# installed as /usr/local/bin/site-pull and run by cron as akhilbirru, so a pull never rewrites the running script
set -e
REPO=/home/akhilbirru/portfolio
WEB=/var/www/html
STATE=/home/akhilbirru/.site-deployed

# skip if the previous run is still going
exec 9>/tmp/site-pull.lock
flock -n 9 || exit 0

cd "$REPO"
timeout 60 git fetch -q origin main
TARGET=$(git rev-parse origin/main)
[ "$TARGET" = "$(cat "$STATE" 2>/dev/null)" ] && exit 0

git reset -q --hard "$TARGET"
# --delete drops files removed from the repo; the *.gz copies are made here, so leave them alone
sudo rsync -a --delete --exclude '*.gz' --exclude '*.docx' --chown=root:root --chmod=D755,F644 "$REPO/site/" "$WEB/"
sudo find "$WEB" -name '*.html' -exec gzip -9 -k -f {} \;
# drop .gz copies of removed pages and the folders they leave behind
sudo find "$WEB" -name '*.html.gz' -exec sh -c '[ -e "${1%.gz}" ] || rm "$1"' _ {} \;
sudo find "$WEB" -mindepth 1 -type d -empty -delete
echo "$TARGET" > "$STATE"
echo "$(date -Is) deployed $(git rev-parse --short HEAD)" | sudo tee -a /var/log/site-pull.log >/dev/null
