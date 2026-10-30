# Bill Buffer

Works out how much should be in a shared bills account right now, and what each person puts in on their own pay cycle.

- Import 2 or 3 months of bank CSVs and it finds recurring bills, including several bills to the same payee
- Edit every bill: name, amount, how often, next due date, category, who pays
- Flags possible double-ups
- Calendar of bills and pay-ins
- One shared copy on your own server that every device works from

## Run it on TrueNAS

1. Paste `truenas.yaml` into **Apps > Discover Apps > Custom App > Install via YAML**.
2. Open `http://YOUR-TRUENAS-IP:47219`.
3. Optional: to require sign-in, set `BB_PASSCODE` in the YAML (8+ characters, no `$`).

The container downloads the latest app from this repo each time it starts. To update, restart the app.

## Where the data lives

There is one copy, kept in the `bill-buffer-data` Docker volume on the server (`/data/state.json`),
with the last 30 versions in `/data/history`. Devices don't keep their own copy: every device reads and
saves that one version, so everyone always sees the same thing. If two people save at the same moment,
the second save is refused and that person is shown the latest version to redo their change. The app needs
to reach the server to show or change bills.

Deleting the app in TrueNAS can delete the volume too. Keep a Drive backup from the Data tab.

## Security

- **Passcode is optional.** With `BB_PASSCODE` empty, anyone who can reach the server on your network can use it.
  With a passcode, devices sign in once and get their own token (only a SHA-256 hash is stored), five wrong
  tries lock sign-in for 15 minutes, and you can sign out one device or every device from the Data tab.
- **No silent overwrites.** Saves are versioned; a save based on an older version is refused.
- **Locked-down container.** The server drops root to an unprivileged user after preparing `/data`, all other
  Linux capabilities are dropped, and `no-new-privileges` is set. Data files are readable by that user only.
- **Browser protections.** Strict Content-Security-Policy, no framing, no referrer, and writes are refused from other sites.
- **Encryption in transit needs HTTPS.** Over plain `http://` on your home network, traffic isn't encrypted.
  For encryption, and for access away from home, put it behind Tailscale (`tailscale serve`) or a reverse
  proxy with a certificate. HTTPS also lets Chrome install it as an app without any flags.

## Install on a phone

Chrome only offers "Install app" from a secure address: use HTTPS (above), or in Chrome on the phone open
`chrome://flags`, enable "Insecure origins treated as secure", add `http://YOUR-TRUENAS-IP:47219`, and relaunch.

When you change files in `site/`, bump `VERSION` in `site/sw.js` so phones pick up the update.
