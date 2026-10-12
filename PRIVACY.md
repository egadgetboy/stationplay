# StationPlay's privacy notice

Copyright © 2026 egadgetboy. StationPlay is free and open source, under the GNU AGPL v3: https://github.com/egadgetboy/stationplay/blob/main/LICENSE

StationPlay runs on your own hardware, with your own Plex Media Server. Its developer runs no service for it and receives nothing from it: no accounts, analytics, ads or tracking.

## What StationPlay keeps

On your hardware, in StationPlay's data folder:

- Your stations and settings. These include Sonarr's and Radarr's keys and the alert web addresses, if an Admin sets them. (The Plex token is in StationPlay's app settings, not in its data folder.)
- The people who can sign in: their names, Viewing Levels, sign-ins and linked devices, and their passwords and PINs, stored only as salted hashes.
- What each person watches in StationPlay's apps (history and Resume), and viewing stats for each person.
- The names of Plex users, and what each watched on StationPlay's stations in Plex, for the viewing stats.
- The access log: sign-ins (failed ones too, with the name typed), changes, and the addresses they came from. It keeps the newest 2,000 lines.
- Problems StationPlay's apps report (with the device's name), and problems people report, with who reported them and the address and device each came from.
- Nightly backups of all this (the newest 7), and a copy of the database made before each update that changes it.

The activity log on the Logs tab is kept only in memory (the newest 500 lines) and is gone when StationPlay restarts. Its lines, and the access log's, also go to the container's own output, which Docker keeps until it rotates it or the container is replaced.

An Admin can see all this on StationPlay's page. Removing a person removes their sign-ins on browsers and apps, their Resume places and their language choices. Some things stay:

- What they watched stays in the viewing stats, under their name.
- The access log keeps the lines that name them.
- Apps they linked keep their name until those apps are removed.
- Their reports and their apps' problems stay until cleared.
- Backups keep everything until they're replaced.

StationPlay clears out old viewing stats (after 400 days), problems the apps reported (after 30 days) and people's reports (90 days after an Admin deals with them) as new ones come in.

## What StationPlay contacts

Only what you set up, and the update check:

- Your Plex Media Server: StationPlay reads your libraries and, if you add it to Plex, serves Plex its guide and streams. Plex's own privacy policy covers Plex.
- Up to 3 web addresses for alerts, if an Admin sets them (such as Discord, Slack or ntfy). Each one receives every alert's sentence, which can name a person, a title and a station, and give your Plex server's home-network address and your away-from-home address.
- Sonarr and Radarr, if an Admin connects them, to replace broken files.
- Your own away-from-home address, which StationPlay checks it can reach, if watching away from home is on. Your reverse proxy or tunnel provider carries what's watched away from home.
- GitHub, once a day, to see whether a new StationPlay is out, if the update check is on (it is to start). It sends only StationPlay's version.

StationPlay sends nothing to its developer.

## StationPlay's apps

StationPlay's apps talk to the StationPlay servers you sign in to, and send problem reports to the server they're using. The app stores check a purchase under their own terms. If your device shares crash reports, the store passes them to StationPlay's developer, under its terms. Casting to a TV goes through Google Cast or AirPlay, under their terms.

## Questions

Ask in the project's issues: https://github.com/egadgetboy/stationplay/issues
For a security problem: https://github.com/egadgetboy/stationplay/blob/main/SECURITY.md
