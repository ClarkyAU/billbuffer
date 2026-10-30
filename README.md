# Bill Buffer

Shows how much should be in your shared bills account right now, and how much each person puts in each payday.

Import 2 or 3 months of bank statements (CSV) and it finds your bills for you.

## Run it

With Docker Compose, using [`docker-compose.yml`](docker-compose.yml):

```sh
docker compose up -d
```

Or with plain Docker:

```sh
docker run -d --name bill-buffer --restart unless-stopped \
  -p 47219:8080 -v bill-buffer-data:/data \
  ghcr.io/clarkyau/billbuffer:latest
```

Then open `http://YOUR-SERVER-IP:47219`.

On a NAS or Portainer, paste `docker-compose.yml` in as a new stack or custom app.

**To update:** `docker compose pull && docker compose up -d`

## Passcode

Off by default, so anyone on your home network can open it. To lock it, go to **Settings > Passcode**.

## Back it up

Your bills live in the `bill-buffer-data` volume. Deleting the volume deletes them, so save a copy now and then from **Settings > Backup**.

## Install on your phone

Chrome only offers **Install app** on a secure (`https://`) address. Two ways to get it:

- **Tailscale:** run `tailscale serve`, which gives you an `https://` address. It also works away from home.
- **Chrome flag:** on the phone, open `chrome://flags` and turn on **Insecure origins treated as secure**. Add `http://YOUR-SERVER-IP:47219`, then restart Chrome.
