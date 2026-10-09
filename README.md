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
  *.pdf          public resume (generated)
jobs/            jobs.json (updated by the daily 7 AM job-match run) and its page builder
study/           sources for site/study/: markdown guides, diagrams, page template, builder
resume/          builds the public resume PDF
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
