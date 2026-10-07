#!/bin/sh
# publish site/ when GitHub main is ahead of what was last deployed
# installed as /usr/local/bin/site-pull and run by cron as akhilbirru, so a pull never rewrites the running script
set -e
REPO=/home/akhilbirru/portfolio
WEB=/var/www/html
STATE=/home/akhilbirru/.site-deployed

cd "$REPO"
git fetch -q origin main
TARGET=$(git rev-parse origin/main)
[ "$TARGET" = "$(cat "$STATE" 2>/dev/null)" ] && exit 0

git reset -q --hard "$TARGET"
sudo rsync -a --chown=root:root --chmod=D755,F644 --exclude '*.docx' "$REPO/site/" "$WEB/"
sudo find "$WEB" -name '*.html' -exec gzip -9 -k -f {} \;
echo "$TARGET" > "$STATE"
echo "$(date -Is) deployed $(git rev-parse --short HEAD)" | sudo tee -a /var/log/site-pull.log >/dev/null
