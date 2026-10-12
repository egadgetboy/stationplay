# Names kept from StationPlay

tapiOca was called StationPlay until version 1.34.0. The rename (the owner's,
October 12) changed what people read. These names stayed exactly as they
were, because other programs, stored data or existing installs match them.
Don't rename them.

## Settings and the API
- The `StationPlay-API: 1` header: the apps and scripts check it on every API answer.
- The `StationPlay-Device` header: the apps send it with a linked device's key, and the server reads it.
- Every URL path (`/api/v1`, `/stream/`, `/hls/`, `/play/`, `/manifest.webmanifest` and the rest): Plex, the apps, scripts and bookmarks use them.
- The `spk_` API token prefix: tokens already made start with it, and the server tells them apart by it.

## Stored names
- Cookies `stationplay_session`, `stationplay_device` and `stationplay_theme`: browsers already hold them, and a new name would sign everyone out.
- The page's localStorage and sessionStorage keys from before 1.34.0 (`stationplay.*`): each browser's saved choices are under them.
- The database file `stationplay.db`, its tables and its META keys: every install's data is in them.
- The data folder's other file and folder names (`stationplay-backup.json`, `stationplay-copy-*` and the like), and backup file names: backups and restores made before 1.34.0 must still be found.
- A backup's manifest says `"app": "StationPlay"`: restoring checks it, and backups from before 1.34.0 carry it.

## Installs
- The compose service and container name `stationplay`: renaming it would start a second container beside the old one on upgrade.
- The Unraid template's container name, `stationplay`, as every other install's, so the README's `docker logs stationplay` and `docker exec stationplay` work there too.
- The Unraid template's data folder, `/mnt/user/appdata/stationplay/data`: an Unraid Compose install from before 1.34.0 already uses it, so switching to the template keeps the same stations and the same tuner.
- The TrueNAS app's name and the Synology project's name the README gives, `stationplay`: TrueNAS app names are lowercase only, and the update steps say "open **Apps**, then **stationplay**" and "choose the stationplay project".
- The volume paths (`/data`, `/media`) and the image's folder `/opt/stationplay`: existing installs mount and use them.
- The file names `stationplay.yaml` and `unraid/stationplay.xml`: existing TrueNAS installs and Unraid templates point to them (an Unraid template's TemplateURL fetches the XML by its name).
- The Dockerfile's stage name and the local build tag `stationplay:latest` in image.yml: CI's own names, never published (the published image is `ghcr.io/egadgetboy/tapioca-server`).

## What Plex and the apps match
- The tuner's DeviceID: Plex knows the tuner by it, and a new one would make Plex see a new tuner.
- The tuner's Manufacturer, `StationPlay`, in discover.json and device.xml: discovery answers carry it, and Plex and other apps may match it. (The name Plex shows, FriendlyName, is `tapiOca` by default.)
- `X-Plex-Client-Identifier: stationplay-live-channels`: Plex knows the server's requests by it.
- Lineup and guide (XMLTV) channel IDs, and Station keys: Plex maps its guide to them.
- The User-Agent token `stationplay` that tuner.py looks for, and the `StationPlay/<version>` User-Agent the server sends to alert addresses and its own reach check.
- Older apps' problem-report sentences, which problems.py still reads (as_now): "StationPlay's address couldn't be found", "StationPlay didn't answer", "StationPlay answered with an error". Apps from 1.34.0's release say "tapiOca" there; both are shown by the new name.

## Code and history
- The Python package and module names (`app`, `stationplay` in pyproject.toml).
- Published release notes, docs/releases/v1.33.1.md and earlier: never rewritten.
- release-signing.pub, the owner's key, with its comment "StationPlay release signing".
- tests/fakeplex.py: never edited.
- The long test runs' switches (`STATIONPLAY_SOAK`, `STATIONPLAY_SOAK_MINUTES`, `STATIONPLAY_REALWORLD`): only developers set them.

## Not kept: new in 1.34.0

These came with 1.34.0 and were never released under the old name, so they carry the new one:

- `TAPIOCA_INSTALL`, the setting that tells the page how an install updates.
- `tapioca.updateNotNow`, the page's localStorage key for the update banner's **Not now**.
- `tapiOca/<version>`, the User-Agent the update check sends to GitHub.
