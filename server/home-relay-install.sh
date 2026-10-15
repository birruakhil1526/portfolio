#!/bin/sh
# install or update the home control relay on the VM:  sudo sh ~/portfolio/server/home-relay-install.sh
# safe to re-run; secrets are created once in /etc/home-relay.env and never leave the VM
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

install -D -m 644 "$REPO/home/relay.py" /usr/local/lib/home-relay/relay.py
# the relay runs the SmartThings and LG ThinQ drivers from bridge.py itself
install -m 644 "$REPO/site/home/bridge.py" /usr/local/lib/home-relay/bridge.py
install -m 644 "$REPO/server/home-relay.service" /etc/systemd/system/home-relay.service

if [ ! -f /etc/home-relay.env ]; then
	umask 077
	{
		echo "HOME_PANEL_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
		echo "HOME_BRIDGE_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
	} > /etc/home-relay.env
	NEW=1
fi

systemctl daemon-reload
systemctl enable -q home-relay
systemctl restart home-relay

install -m 644 "$REPO/server/nginx-portfolio.conf" /etc/nginx/sites-available/portfolio
nginx -t
systemctl reload nginx

echo "home relay: $(systemctl is-active home-relay)"
if [ -n "$NEW" ]; then
	echo
	echo "Save these now (also in /etc/home-relay.env; change the password there, then rerun this script):"
	sed 's/^/  /' /etc/home-relay.env
fi
