# Birru's Space

Personal portfolio of Akhil Birru: a single static page with a developer theme
(terminal intro, `git log` career timeline, `package.json` skills), served by nginx
from a small Azure VM.

Live: http://68.221.25.41/

## Layout

```
site/        what gets published (index.html, resume PDF)
server/      nginx config, stats script, auto-deploy script for the VM
resume/      builds the public resume PDF (no phone number)
```

## Editing

Edit `site/index.html` and push to `main`. The VM checks GitHub every 5 minutes
and publishes `site/` when there is a new commit (`server/site-pull.sh`).

The page is one self-contained file: no build step, no external requests.

## Resume

```
python resume/build_public.py   # writes site/Akhil_Birru_Resume.pdf (needs python-docx + LibreOffice)
```

## Server

- nginx config: `server/nginx-portfolio.conf` -> `/etc/nginx/sites-available/portfolio`
- Visitor stats: GoAccess builds `/stats/` from nginx logs every 10 minutes
  (`server/goaccess-update.sh`), behind basic auth
- Changes in `server/` are not applied automatically; copy them to the VM by hand

Never commit the VM key (`*.pem`) or the stats password.
