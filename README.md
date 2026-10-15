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

- nginx: `server/nginx-portfolio.conf` -> `/etc/nginx/sites-available/portfolio`
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

`/home/` controls the TV, AC, washer and other devices at home from anywhere. Nothing on the router
is opened; there are two ways in:

- **Cloud, nothing to install at home.** On the page, a home links SmartThings (Samsung) or LG ThinQ.
  The relay on the VM (`home/relay.py`, nginx `/home/api/`) then calls those vendor clouds itself, with
  the drivers it loads from `site/home/bridge.py`. LG controls are built from each appliance's ThinQ
  profile, so every LG appliance type works without its own code.
- **Bridge, optional.** For devices that only listen on the WiFi (Samsung / LG / Roku TV remotes,
  Wake-on-LAN) or Home Assistant, `site/home/bridge.py` runs on an always-on machine at home and
  long-polls the relay.

- VM, once and after `home/relay.py` or nginx changes: `sudo sh ~/portfolio/server/home-relay-install.sh`
  (installs the `home-relay` systemd unit and nginx config; settings in `/etc/home-relay.env`)
- Accounts: anyone can tap "Create your home" and gets an access key (login) and a bridge token. Each
  account is a separate home that sees only its own bridge's devices. Hashes of the keys are kept in
  `/var/lib/home-relay/accounts.json`; `HOME_SIGNUP=0` closes sign-up. The owner home from
  `HOME_BRIDGE_TOKEN` also opens with `HOME_PANEL_PASSWORD`, or for anyone with `HOME_NO_PASSWORD=1` (testing only).
- Cloud links are stored per home in `/var/lib/home-relay/links.json` (mode 600). Tokens there must be
  usable, so they are not hashed. Cloud devices are only re-read while someone has the page open.
- LG ThinQ: the user pastes a personal access token from connect-pat.lgthinq.com (does not expire) and
  their country code (picks the kic / aic / eic API region).
- SmartThings: personal access tokens made after 30 Dec 2024 expire after 24 hours. For tokens that renew
  themselves, create an OAuth app once with the SmartThings CLI (`smartthings apps:create`, type OAuth-In App,
  scopes `r:devices:* x:devices:* r:locations:*`, redirect URI `http://68.221.25.41/home/api/st/callback`),
  put `HOME_ST_CLIENT_ID` and `HOME_ST_CLIENT_SECRET` in `/etc/home-relay.env` and rerun the install
  script. The page then shows "Connect SmartThings". If SmartThings refuses a plain-HTTP redirect URI,
  this needs HTTPS first (and `HOME_PUBLIC_URL` set to the https address).
- Home (optional bridge): `curl -O http://68.221.25.41/home/bridge.py && python3 bridge.py setup && python3 bridge.py`
- `bridge.json` and `.bridge-state.json` hold tokens and TV pairing keys: never commit them.
- The site is plain HTTP, so keys and pasted cloud tokens cross the network unencrypted; add HTTPS
  before relying on it.
- Test: `python3 home/test_home.py` (fake TVs, fake SmartThings and LG ThinQ clouds, no real devices).
