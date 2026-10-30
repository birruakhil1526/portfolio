# Ledger

Certificate Transparency monitor that flags lookalike domains of watched brands.
Live at `/ledger/`, console at `/ledger/console/` (same login as `/stats/`).

```
ledger/ct.py          CT log readers: RFC 6962 (Google Argon, Cloudflare Nimbus) and tiled (Let's Encrypt)
ledger/match.py       lookalike scoring: homoglyphs, digit swaps, brand inside a name, typos, scam words
ledger/ledger.py      the service: one reader thread per log, SQLite, Server-Sent Events, JSON API
site/ledger/          landing page and console (static, served by nginx like the rest of site/)
```

Standard library plus `cryptography`, no build step. The pages deploy with `site/` as usual;
the service and nginx routes are installed by hand on the VM:

```
cd ~/portfolio && git pull && sudo sh ledger/install.sh
```

Run locally: `LEDGER_DB=/tmp/ledger.db python3 ledger/ledger.py` (API on 127.0.0.1:8790).
Tests: `python3 -m unittest ledger/test_match.py`.

The CT logs rotate yearly or half-yearly (`argon2026h2`, `sycamore 2026h2`, ...): when Chrome's
log list (https://www.gstatic.com/ct/log_list/v3/log_list.json) retires a shard, update `LOGS` in
`ledger/ct.py` and rerun the installer.
