#!/bin/sh
# install or update Ledger on the VM; run from the repo root: sudo sh ledger/install.sh
# the pages ship with site/ via site-pull; this installs the service and the nginx routes
set -e
cd "$(dirname "$0")"

python3 -c 'import cryptography' 2>/dev/null || apt-get install -y python3-cryptography

install -d -o root -g root -m 755 /opt/ledger
install -o root -g root -m 644 ct.py match.py ledger.py /opt/ledger/
install -o root -g root -m 644 ledger.service /etc/systemd/system/ledger.service

# rate limit for the public API (http context)
echo 'limit_req_zone $binary_remote_addr zone=ledger:1m rate=20r/s;' > /etc/nginx/conf.d/ledger-zone.conf
install -o root -g root -m 644 nginx-ledger.conf /etc/nginx/snippets/ledger.conf

# hook the snippet into the portfolio server block(s) once, next to the resume route
SITE=/etc/nginx/sites-available/portfolio
if ! grep -q 'snippets/ledger.conf' "$SITE"; then
	cp "$SITE" "$SITE.bak-ledger"
	sed -i '/# show the resume in the browser/i\	include /etc/nginx/snippets/ledger.conf;\n' "$SITE"
fi

systemctl daemon-reload
systemctl enable ledger >/dev/null 2>&1
systemctl restart ledger
nginx -t
systemctl reload nginx
echo "ledger: $(systemctl is-active ledger), http://$(hostname -I | cut -d' ' -f1)/ledger/"
