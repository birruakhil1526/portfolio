# Birru's Space

Personal portfolio of Akhil Birru: static pages served by nginx from a small Azure VM.
No framework, no external requests, everything inline.

Live: http://68.221.25.41/

## Layout

```
site/            published as-is to the web root
  index.html     the portfolio (hand-written, self-contained)
  study/         hidden study page (generated, do not edit by hand)
  jobs/          daily job matches, unlisted (generated from jobs/jobs.json)
  home/          home control page + bridge.py (downloaded and run on a machine at home)
  *.pdf          public resume (generated)
jobs/            fetch_jobs.py (Apify -> jobs.json, run daily by .github/workflows/jobs.yml) and the page builder
study/           sources for site/study/: markdown guides, diagrams, page template, builder
resume/          builds the public resume PDF
home/            relay.py (runs on the VM behind /home/api/) and its end-to-end test
server/          VM setup: nginx config, stats script, auto-deploy script
build.sh         builds generated pages; --check is what CI runs
```

## Quick start

```
./build.sh                          # rebuild site/study/ after editing study/
./build.sh --check                  # also verify site/ is committed up to date
python3 -m http.server -d site      # preview at http://localhost:8000
```

Commit `site/` together with the source change. CI (`.github/workflows/check.yml`)
fails a push when the generated page is stale or a phone number other than Akhil's appears in `site/`.

## Deploy

Push to `main`. The VM checks GitHub every 5 minutes and publishes `site/`
(`server/site-pull.sh`, installed as `/usr/local/bin/site-pull`, cron `/etc/cron.d/site-pull`,
log `/var/log/site-pull.log`). Files deleted from `site/` are removed from the server too.

`server/` changes are not applied automatically; install them on the VM by hand.

## Study page

`/study/` is unlinked: triple-click or tap the name on the portfolio, or type `study` in its
terminal. Add a guide by dropping a markdown file in `study/src/` and listing it in `GUIDES` in
`study/build_study.py`; diagrams live in `study/diagrams.py` and are attached per heading there.
Unlinked is not private: anyone with the URL can open it.

## Resume

```
python3 resume/build_public.py      # writes site/Akhil_Birru_Resume.pdf (needs python-docx + LibreOffice)
```

## Server

- nginx: `server/nginx-portfolio.conf` -> `/etc/nginx/sites-available/portfolio`, plus `server/nginx-portfolio-common.conf` -> `/etc/nginx/snippets/portfolio-common.conf`
- Visitor stats: GoAccess rebuilds `/stats/` from nginx logs every 10 minutes
  (`server/goaccess-update.sh`), behind basic auth

## Never commit

The VM key (`*.pem`), the stats password, salary or notice-period details.
This repo is public.

## Jobs page

`.github/workflows/jobs.yml` runs every day at 06:59 IST (and on demand from the Actions tab):
`jobs/fetch_jobs.py` pulls senior Angular roles from LinkedIn through Apify, ranks them,
rebuilds `site/jobs/` and pushes to `main`, which the VM then deploys. It needs the repo secret
`APIFY_TOKEN` (Settings → Secrets and variables → Actions).

## Home control

`/home/` controls the TV, AC, washer and other devices at home from anywhere. A browser cannot reach
devices on the home WiFi, so `site/home/bridge.py` runs on an always-on machine at home, finds devices
(SSDP, Samsung / LG / Roku TVs, Wake-on-LAN, plus SmartThings and Home Assistant for cloud appliances)
and long-polls the relay on the VM (`home/relay.py`, nginx `/home/api/`). Nothing is opened on the router.

- VM, once and after `home/relay.py` or nginx changes: `sudo sh ~/portfolio/server/home-relay-install.sh`
  (installs the `home-relay` systemd unit and nginx config, prints the page password and bridge token
  kept in `/etc/home-relay.env`)
- Home: `curl -O http://68.221.25.41/home/bridge.py && python3 bridge.py setup && python3 bridge.py`
- `bridge.json` and `.bridge-state.json` hold tokens and TV pairing keys: never commit them.
- Sign-in: Google (only the accounts in `HOME_ALLOWED_EMAILS`), a password, or `HOME_NO_PASSWORD=1` for
  testing, all set in `/etc/home-relay.env`. Google needs HTTPS: `sudo sh ~/portfolio/server/https-setup.sh <name>.duckdns.org`
  gets a Let's Encrypt certificate (port 443 must be open in the Azure network security group) and writes
  `/etc/nginx/snippets/portfolio-https-site.conf`; the bare IP keeps serving plain HTTP.
- nginx: `server/nginx-portfolio.conf` holds the server blocks, `server/nginx-portfolio-common.conf` the shared
  headers and locations (`/etc/nginx/snippets/portfolio-common.conf`).
