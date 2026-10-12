# StationPlay's privacy notice

Copyright © 2026 egadgetboy. StationPlay is free and open source, under the GNU AGPL v3 (see [LICENSE](LICENSE)).

StationPlay runs on your own hardware, for your personal use, with your own Plex Media Server. Its developer runs no service for it and receives nothing from it: no accounts, analytics, ads or tracking.

## What StationPlay keeps

Everything stays in StationPlay's data folder, on your hardware:

- **Your stations and settings,** including the Plex token you give it.
- **The people who can sign in:** their names, their passwords and PINs (stored only as salted hashes), their sign-ins and linked devices, and their Viewing Levels.
- **What people watch** in StationPlay's apps (history, Resume and favorites), and viewing stats, for each person.
- **Logs:** the activity log, the access log (sign-ins and changes), and problems StationPlay's apps report.
- **Nightly backups** of all of this, in the same folder.

An Admin can see this on StationPlay's page. Removing a person removes their sign-ins, devices and history.

## What leaves your home

Only what you set up:

- **Your Plex Media Server.** StationPlay reads your libraries and, if you add it to Plex, serves Plex its guide and streams. Plex's own privacy policy covers Plex.
- **A web address for alerts,** if an Admin sets one (such as Discord or ntfy). It receives the alert's sentence.
- **Sonarr and Radarr,** if an Admin connects them, to replace broken files.
- **Your own away-from-home address,** which StationPlay checks it can reach, if watching away from home is on.

StationPlay sends nothing to its developer.

## StationPlay's apps

StationPlay's apps talk only to the StationPlay servers you sign in to, and send problem reports only to your own StationPlay. Casting to a TV goes through Google Cast or AirPlay, under their own terms, and buying an unlock goes through the app store, under its terms.

## Questions

Ask in the project's issues: https://github.com/egadgetboy/stationplay/issues. For a security problem, see [SECURITY.md](SECURITY.md).
