# Bill Buffer

Works out how much should be in a shared bills account right now, and what each person puts in on their own pay cycle.

- Import 2 or 3 months of bank CSVs and it finds recurring bills, including several bills to the same payee
- Edit every bill: name, amount, how often, next due date, category, who pays
- Flags possible double-ups
- Calendar of bills and pay-ins
- Shared between your devices through your own server, and works offline

## Run it on TrueNAS

1. Open `truenas.yaml` and change `BB_PASSCODE` to your household passcode (8+ characters, no `$`).
2. Paste it into **Apps > Discover Apps > Custom App > Install via YAML**.
3. Open `http://YOUR-TRUENAS-IP:47219`, sign in with the passcode, and name the device.

The container downloads the latest app from this repo each time it starts. To update, restart the app.

## Where the data lives

One shared copy is kept in the `bill-buffer-data` Docker volume on the server (`/data/state.json`),
with the last 30 versions in `/data/history`. Each device also keeps a copy so the app opens offline,
and syncs when it can reach the server again.

Deleting the app in TrueNAS can delete the volume too. Keep a Drive backup from the Data tab.

## Security

- **Passcode and device tokens.** Devices sign in once with the household passcode and get their own
  token. The server stores only a SHA-256 hash of each token. You can sign out one device or every device
  from the Data tab.
- **Lockout.** Five wrong passcodes from one address lock sign-in for 15 minutes.
- **No silent overwrites.** Saves are versioned; if two devices change things at once, the second is asked which copy to keep.
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
