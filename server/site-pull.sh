#!/bin/sh
# pull the repo and publish site/ when main has new commits
set -e
REPO=/home/akhilbirru/portfolio
WEB=/var/www/html

cd "$REPO"
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0

git reset -q --hard origin/main
for f in "$REPO"/site/*; do
	case "$f" in *.docx) continue ;; esac
	install -m 644 "$f" "$WEB/"
done
gzip -9 -k -f "$WEB/index.html"
echo "$(date -Is) deployed $(git rev-parse --short HEAD)" >> /var/log/site-pull.log
