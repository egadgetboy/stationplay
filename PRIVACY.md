# tapiOca's privacy notice

tapiOca was called StationPlay until version 1.34.0.

Copyright © 2026 egadgetboy. tapiOca is free and open source, under the GNU AGPL v3: https://github.com/egadgetboy/tapioca-server/blob/main/LICENSE

tapiOca runs on your own hardware, with your own Plex Media Server. Its developer runs no service for it and receives nothing from it: no accounts, analytics, ads or tracking.

## What tapiOca keeps

On your hardware, in tapiOca's data folder:

- Your stations and settings. These include Sonarr's and Radarr's keys and the alert web addresses, if an Admin sets them. (The Plex token is in tapiOca's app settings, not in its data folder.)
- The people who can sign in: their names, Viewing Levels, sign-ins and linked devices, the browsers and apps each signed in on with their password, each Admin's choice of Full or Light sign-in, when and from what address each last signed in, and their passwords and PINs, stored only as salted hashes.
- What each person watches in tapiOca's apps (history and Resume), and viewing stats for each person.
- The names of Plex users, and what each watched on tapiOca's stations in Plex, for the viewing stats.
- The access log: sign-ins (failed ones too, with the name typed), changes, and the addresses they came from. It keeps the newest 2,000 lines.
- Trusted networks, if an Admin adds them: each network or address, its name, what it gives, the person it signs in as, and who added it and when. Also the trusted proxies and the names for tapiOca at home an Admin lists.
- Devices linked by a trusted network (the names the app and the device give), and sign-ins made on one. These work only on that network.
- The address Plex's Live TV & DVR uses for tapiOca's tuner, as your own Plex says it. tapiOca reads it from your Plex, and shows it only to Admins, on the **Setup** tab. It's never sent anywhere. It's cleared when Plex no longer lists a tapiOca tuner it can reach.
- Problems tapiOca's apps report (with the device's name), and problems people report, with who reported them and the address and device each came from.
- Nightly backups of all this (the newest 7), and a copy of the database made before each update that changes it.

Kept only in memory, for Admins: the latest address that reached tapiOca's home port from the internet, through a proxy, or by an internet name (with that name), the latest device to send forwarding headers that tapiOca ignored, and the latest address, such as Docker's, that carries other devices' connections. The access log notes each at most once an hour. Alerts about how tapiOca is reached never include an address or a name.

The activity log on the Logs tab is kept only in memory (the newest 500 lines) and is gone when tapiOca restarts. Its lines, and the access log's, also go to the container's own output, which Docker keeps until it rotates it or the container is replaced.

An Admin can see all this on tapiOca's page. Removing a person removes their sign-ins on browsers and apps, their Resume places and their language choices. Some things stay:

- What they watched stays in the viewing stats, under their name.
- The access log keeps the lines that name them.
- Apps they linked keep their name until those apps are removed.
- Their reports and their apps' problems stay until cleared.
- Backups keep everything until they're replaced.

tapiOca clears out old viewing stats (after 400 days), problems the apps reported (after 30 days) and people's reports (90 days after an Admin deals with them) as new ones come in.

## What tapiOca contacts

Only what you set up, and the update check:

- Your Plex Media Server: tapiOca reads the details of your movies and shows and, if you add it to Plex, serves Plex its guide and streams. Plex's own privacy policy covers Plex.
- Up to 3 web addresses for alerts, if an Admin sets them (such as Discord, Slack or ntfy). Each one receives every alert's sentence, which can name a person, a title and a station, and give your Plex server's home-network address and your away-from-home address.
- Sonarr and Radarr, if an Admin connects them, to replace broken files.
- Your own away-from-home address, which tapiOca checks it can reach, if watching away from home is on. Your reverse proxy or tunnel provider carries what's watched away from home.
- GitHub, every 4 hours, to see whether a new tapiOca is out, only if an Admin said yes to the update check (tapiOca asks first). It sends only tapiOca's version, and GitHub sees your server's internet address, as any website does.

tapiOca sends nothing to its developer.

## tapiOca's apps

tapiOca's apps talk to the tapiOca servers you sign in to, and send problem reports to the server they're using. The app stores check a purchase under their own terms. If your device shares crash reports, the store passes them to tapiOca's developer, under its terms. Casting to a TV goes through Google Cast or AirPlay, under their terms.

## Questions

Ask in the project's issues: https://github.com/egadgetboy/tapioca-server/issues
For a security problem: https://github.com/egadgetboy/tapioca-server/blob/main/SECURITY.md
