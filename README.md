# Bill Buffer

Works out how much should be in a shared bills account right now, and what each person puts in on their own pay cycle.

- Import 2 or 3 months of bank CSVs and it finds recurring bills
- Edit every bill: name, amount, how often, next due date, category, who pays
- Flags possible double-ups
- Calendar of bills and pay-ins
- Works offline once installed; all data stays on the phone, with backups to Google Drive

## Run it on TrueNAS

Paste `truenas.yaml` into **Apps > Discover Apps > Custom App > Install via YAML**.
It serves the app on port 47219 and downloads the latest version from this repo each time it starts.
To update, push changes here and restart the app.

## Install on a phone

Chrome only offers "Install app" from a secure address. Either:

- In Chrome on the phone open `chrome://flags`, enable "Insecure origins treated as secure", add `http://YOUR-TRUENAS-IP:47219`, and relaunch, or
- serve it over HTTPS (Tailscale or a reverse proxy).

When you change files in `site/`, bump `VERSION` in `site/sw.js` so phones pick up the update.
