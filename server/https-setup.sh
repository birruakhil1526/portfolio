#!/bin/sh
# HTTPS for the site on a DuckDNS name, then Google sign-in for /home/:
#   sudo sh ~/portfolio/server/https-setup.sh birru.duckdns.org
# needs: the DuckDNS name pointing at this VM, and port 443 open in the Azure network security group.
# safe to re-run; the certificate renews itself (certbot's systemd timer) and reloads nginx.
set -e
DOMAIN=$1
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
echo "$DOMAIN" | grep -Eq '^[a-z0-9-]+\.duckdns\.org$|^[a-z0-9.-]+\.[a-z]{2,}$' || { echo "usage: sudo sh $0 <name>.duckdns.org" >&2; exit 1; }

command -v certbot >/dev/null || { apt-get update -q && apt-get install -y -q certbot; }

# the http server answers the Let's Encrypt challenge from /var/www/acme
sh "$REPO/server/home-relay-install.sh" >/dev/null
certbot certonly --webroot -w /var/www/acme -d "$DOMAIN" --cert-name portfolio \
	--non-interactive --agree-tos --register-unsafely-without-email \
	--deploy-hook "systemctl reload nginx"

cat > /etc/nginx/snippets/portfolio-https-site.conf <<CONF
# written by server/https-setup.sh
server {
	listen 443 ssl;
	listen [::]:443 ssl;
	server_name $DOMAIN;
	ssl_certificate /etc/letsencrypt/live/portfolio/fullchain.pem;
	ssl_certificate_key /etc/letsencrypt/live/portfolio/privkey.pem;
	ssl_protocols TLSv1.2 TLSv1.3;
	ssl_session_cache shared:portfolio:1m;
	include /etc/nginx/snippets/portfolio-common.conf;
}

# http://$DOMAIN goes to https; the bare IP keeps working over http
server {
	listen 80;
	listen [::]:80;
	server_name $DOMAIN;
	location ^~ /.well-known/acme-challenge/ { root /var/www/acme; }
	location / { return 301 https://$DOMAIN\$request_uri; }
}
CONF
nginx -t
systemctl reload nginx

# tell the relay its public address, which Google sign-in redirects back to
touch /etc/home-relay.env
sed -i '/^HOME_PUBLIC_URL=/d' /etc/home-relay.env
echo "HOME_PUBLIC_URL=https://$DOMAIN" >> /etc/home-relay.env
chmod 600 /etc/home-relay.env
systemctl restart home-relay

echo
echo "https://$DOMAIN is live."
echo "Google sign-in redirect URI:  https://$DOMAIN/home/api/auth/callback"
grep -q '^GOOGLE_CLIENT_ID=' /etc/home-relay.env || echo "Next: add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and HOME_ALLOWED_EMAILS to /etc/home-relay.env, then: sudo systemctl restart home-relay"
