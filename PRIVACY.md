# StationPlay's privacy notice

Copyright © 2026 egadgetboy. StationPlay is free and open source, under the GNU AGPL v3: https://github.com/egadgetboy/stationplay/blob/main/LICENSE

StationPlay runs on your own hardware, with your own Plex Media Server. Its developer runs no service for it and receives nothing from it: no accounts, analytics, ads or tracking.

## What StationPlay keeps

On your hardware, in StationPlay's data folder:

- Your stations and settings. (The Plex token is in StationPlay's app settings, not in its data folder.)
- The people who can sign in: their names, Viewing Levels, sign-ins and linked devices, and their passwords and PINs, stored only as salted hashes.
- What each person watches in StationPlay's apps (history and Resume), and viewing stats for each person.
- The names of Plex users, and what each watched on StationPlay's stations in Plex, for the viewing stats.
- Logs: the activity log, and the access log of sign-ins (failed ones too, with the name typed), changes and the addresses they came from.
- Problems StationPlay's apps report, and problems people report, with who reported them.
- Nightly backups of all this (the newest 7), and a copy of the database made before each update that changes it.

The container's own output (its log, kept by Docker) has the activity log's lines too.

An Admin can see this on StationPlay's page. Removing a person removes their sign-ins, browsers, Resume and languages. What they watched stays in the viewing stats, under their name, for up to 400 days; their reports stay for up to 90 days; and backups keep everything until they're replaced.

## What StationPlay contacts

Only what you set up:

- Your Plex Media Server: StationPlay reads your libraries and, if you add it to Plex, serves Plex its guide and streams. Plex's own privacy policy covers Plex.
- A web address for alerts, if an Admin sets one (such as Discord or ntfy). It receives each alert's sentence, which can name a person and a title.
- Sonarr and Radarr, if an Admin connects them, to replace broken files.
- Your own away-from-home address, which StationPlay checks it can reach, if watching away from home is on. Your reverse proxy or tunnel provider carries what's watched away from home.

StationPlay sends nothing to its developer.

## StationPlay's apps

StationPlay's apps talk to the StationPlay servers you sign in to, and send problem reports to the server they're using. The app stores' own crash reports, and their check of a purchase, are under each store's terms. Casting to a TV goes through Google Cast or AirPlay, under their terms.

## Questions

Ask in the project's issues: https://github.com/egadgetboy/stationplay/issues
For a security problem: https://github.com/egadgetboy/stationplay/blob/main/SECURITY.md
