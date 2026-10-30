# Bill Buffer

Shows how much should be in your shared bills account right now, and how much each person puts in each payday.

Import 2 or 3 months of bank statements (CSV) and it finds your bills for you.

## Install on TrueNAS

1. Go to **Apps > Discover Apps > Custom App > Install via YAML**.
2. Paste in [`truenas.yaml`](truenas.yaml) and save.
3. Open `http://YOUR-TRUENAS-IP:47219`.

**To update:** restart the app in TrueNAS. It pulls the latest version from here each time it starts.

## Passcode

Off by default, so anyone on your home network can open it. To lock it, go to **Settings > Passcode**.

## Back it up

Your bills are kept on the server. Deleting the app in TrueNAS can delete them too, so save a copy now and then from **Settings > Backup**.

## Install on your phone

Chrome only offers **Install app** on a secure (`https://`) address. Two ways to get it:

- **Tailscale:** run `tailscale serve`, which gives you an `https://` address. It also works away from home.
- **Chrome flag:** on the phone, open `chrome://flags` and turn on **Insecure origins treated as secure**. Add `http://YOUR-TRUENAS-IP:47219`, then restart Chrome.
