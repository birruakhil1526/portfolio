#!/bin/sh
# pull the repo and publish site/ when main has new commits (runs as akhilbirru)
set -e
REPO=/home/akhilbirru/portfolio
WEB=/var/www/html

cd "$REPO"
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0

git reset -q --hard origin/main
sudo rsync -a --chown=root:root --chmod=D755,F644 --exclude '*.docx' "$REPO/site/" "$WEB/"
sudo find "$WEB" -name '*.html' -exec gzip -9 -k -f {} \;
echo "$(date -Is) deployed $(git rev-parse --short HEAD)" | sudo tee -a /var/log/site-pull.log >/dev/null
