#!/bin/sh
# rebuild the stats page from nginx logs; persisted db keeps history after log rotation
goaccess /var/log/nginx/access.log \
	--log-format=COMBINED \
	--persist --restore --db-path=/var/lib/goaccess \
	--ignore-crawlers \
	--html-report-title="Birru's Space · visitors" \
	-o /var/www/stats/index.html >/dev/null 2>&1
