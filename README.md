<p align="center"><img src="docs/logo.svg" alt="StationPlay" width="360"></p>

> [!WARNING]
> ## StationPlay is in ALPHA
> It works, but it's far from finished. Features are still being added and changed, some of what this README describes hasn't shipped yet, and things may break between versions. **For testing only. Don't rely on it for anything yet.** Back up your data folder before you update.

# StationPlay

StationPlay turns your Plex library into always-on TV stations. Pick some shows or movies, give the station a number and a name, and it plays them around the clock like a broadcast station. It comes with a program guide. You can also add commercials, station IDs, a corner logo, movie nights and Saturday-morning blocks.

Plex sees StationPlay as an HDHomeRun network tuner, so your stations show up in Plex's **Live TV** guide on every Plex app. Jellyfin, Emby, Kodi and most IPTV apps can watch them too.

StationPlay is free, open source and self-hosted (see [License](#license)). It runs in Docker on your own hardware and gets everything from your Plex server. It needs no outside accounts or cloud services.

If you find it useful, you can [buy me a coffee](https://buymeacoffee.com/egadgetboy).

## Contents

- [What you need](#what-you-need)
- [Install](#install): [TrueNAS SCALE](#truenas-scale) · [Docker Compose (Linux, Proxmox, Raspberry Pi)](#docker-compose-linux-proxmox-raspberry-pi) · [Synology](#synology) · [Unraid](#unraid) · [Windows and macOS](#windows-and-macos) · [docker run](#docker-run)
- [GPU encoding](#gpu-encoding) · [Updating](#updating) · [Backups](#backups) · [How StationPlay reads your files](#how-stationplay-reads-your-files) · [Security and remote access](#security-and-remote-access)
- [Watch your stations](#watch-your-stations): Plex, Jellyfin, Emby, Kodi and other apps · [StationPlay's own apps](#stationplays-own-apps)
- [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home): a VPN, a reverse proxy, or a Cloudflare Tunnel
- [First-time setup](#first-time-setup)
- [Making stations](#making-stations)
- [How stations play](#how-stations-play)
- [Station features](#station-features): logos, corner logo, Up Next Banner, Station ID card, commercials, Intro Bumper, subtitles, specials
- [Keeping stations on the air](#keeping-stations-on-the-air): safeguards, the Broken files list, file checks, Sonarr and Radarr, people's reports
- [Who can use StationPlay](#who-can-use-stationplay): [Viewing Levels](#viewing-levels) · [Linked devices and Who's tuning in?](#linked-devices-and-whos-tuning-in)
- [Stats](#stats) · [StationPlay's API](#stationplays-api) · [Settings](#settings) · [Troubleshooting](#troubleshooting) · [Development](#development)
- [Contributing](#contributing) · [Forks and credit](#forks-and-credit) · [License](#license)

## What you need

- **Plex Media Server** with your shows and movies. To watch in Plex, you also need **Plex Pass**, because Plex's Live TV & DVR feature requires it. Jellyfin, Emby, Kodi and IPTV apps don't need Plex Pass.
- **A computer that runs Docker** on the same home network as Plex. It can be a NAS (TrueNAS SCALE, Synology, Unraid), a Linux server or virtual machine, a Raspberry Pi 4 or 5 with a 64-bit OS, or a Windows or Mac computer with Docker Desktop. Both x86-64 (Intel/AMD) and ARM64 work.
- **Access to your media folder** from that computer. StationPlay reads files directly from disk. If it can't see a file, it streams it from Plex instead, which works but adds load to Plex.
- **Enough processing power.** Each station being watched is converted in real time. A modern 4-core CPU can usually run several 720p stations at once. A GPU (Intel Quick Sync, AMD or NVIDIA) handles many more, and 1080p easily. StationPlay can't use the GPU in a Raspberry Pi or a Mac, so plan on one or two stations at smaller picture sizes there. **Test this server** on StationPlay's page measures what your hardware can do (see [Tuners](#tuners)).

## Install

### How installation works

Each StationPlay release is a set of files. Docker builds the StationPlay image on your own machine.

| File | What it's for |
|---|---|
| `stationplay-<version>.zip` | The app. It unzips to a folder called `src`. |
| `stationplay.yaml` | The app definition for TrueNAS SCALE. |
| `docker-compose.yml` | The app definition for Docker Compose, for everything else. |

Both app definitions are also inside the zip, in `src`, and the steps below use those copies. The first build takes a few minutes, mostly to install ffmpeg.

**Before you start, gather four things:**

1. **Your Plex server's address**, such as `http://192.168.1.10:32400`. Use the server's network IP address, not `localhost`. Inside a container, `localhost` means the container itself.
2. **Your Plex token** (see the next section).
3. **Where your media lives** on the Docker host, such as `/mnt/tank/media`.
4. **The user StationPlay runs as**, written as `UID:GID` (numbers). This user must be able to read your media and write to StationPlay's data folder. The examples use `1000:1000`. To see who owns your media, run `ls -ln /path/to/media`. The third and fourth columns are the UID and GID.

#### Finding your Plex token

In Plex Web, open any movie or episode and choose **⋯ → Get Info → View XML**. The address of the page that opens ends with `X-Plex-Token=…`. That value is your token. Keep it private, because it gives full access to your Plex server. StationPlay never shows it on its page or in its logs.

### TrueNAS SCALE

Requires TrueNAS SCALE 24.10 (Electric Eel) or later, which has **Install via YAML**.

**1. Copy the zip file onto the NAS.** Put it anywhere you can reach, such as a folder on an SMB share you already use.

**2. Make StationPlay's folder and unzip the release into it.** Choose a place on a pool, such as `/mnt/tank/apps/stationplay` (use your pool's name instead of `tank`). Paths in TrueNAS are case-sensitive, so `StationPlay` and `stationplay` are different folders. Open **System → Shell** and run:

```
sudo mkdir -p /mnt/tank/apps/stationplay/data
cd /mnt/tank/apps/stationplay
sudo unzip -o /path/to/stationplay-<version>.zip
sudo chown -R 1000:1000 data
```

The `data` folder holds your stations and settings, so the user StationPlay runs as must own it (`1000:1000` here; see step 3). The `src` folder can stay owned by root, because TrueNAS only reads it to build the image.

**3. Install the app.** Go to **Apps → Discover Apps → ⋮ (top right) → Install via YAML**. Name the app `stationplay` and paste the contents of `stationplay.yaml`. Then change every line marked `<- CHANGE`:

- **The three folder paths:** the `src` folder, the `data` folder and your media folder.
- **Plex and time zone:** `PLEX_URL`, `PLEX_TOKEN` and `TZ` (your time zone, such as `America/Chicago`).
- **The user:** change `user:` if your media belongs to another user. TrueNAS's built-in apps user is `568:568`. If you use it, also run `sudo chown -R 568:568 data`.

Also check the GPU lines (see [GPU encoding](#gpu-encoding)). The Intel/AMD lines are turned on in this file. If the server has no Intel or AMD graphics, delete them, or the app won't start.

Save. The first build takes a few minutes.

**4. Open** `http://<your-nas-ip>:3310` in a browser. The [first-time setup](#first-time-setup) starts.

### Docker Compose (Linux, Proxmox, Raspberry Pi)

This works on any Linux machine with Docker and the Compose plugin. That includes Ubuntu, Debian, a Proxmox VM or LXC container, a Raspberry Pi with a 64-bit OS, and most NAS systems with a terminal.

```
mkdir -p ~/stationplay && cd ~/stationplay
unzip -o /path/to/stationplay-<version>.zip        # creates src/
cp src/docker-compose.yml .
mkdir -p data && sudo chown -R 1000:1000 data      # use your UID:GID
```

If `unzip` isn't installed, install it first (`sudo apt install unzip` on Debian, Ubuntu and Raspberry Pi OS).

Open `docker-compose.yml` in a text editor and change every line marked `<- CHANGE`: the user, Plex's address, your Plex token, your time zone and your media folder. For a GPU, uncomment its lines (see [GPU encoding](#gpu-encoding)). Then build and start StationPlay:

```
docker compose up -d --build
```

Open `http://<server-ip>:3310`. Your copy of `docker-compose.yml` sits next to `src`, so updates never overwrite it.

- **On Proxmox.** Run Docker in a VM or an LXC container, then follow these steps. To use an Intel or AMD GPU from an LXC container, first pass `/dev/dri` through to it in Proxmox. Your media must be mounted inside the VM or container.
- **On a Raspberry Pi.** Use a 64-bit OS. The Pi's GPU can't be used for encoding, so StationPlay encodes on the CPU. Start with the 480p picture size.

### Synology

Requires DSM 7.2 or later with **Container Manager** (from Package Center).

1. In **Control Panel → Terminal & SNMP**, turn on SSH.
2. In **File Station**, create a folder such as `/volume1/docker/stationplay`. Upload the zip file there, right-click it and choose **Extract → Extract Here**. You now have a `src` folder. Copy `src/docker-compose.yml` into `/volume1/docker/stationplay` and create a `data` folder next to it.
3. Connect over SSH and find your user's IDs with `id`. You'll see something like `uid=1026(you) gid=100(users)`. Use those numbers so StationPlay can read your media:

   ```
   cd /volume1/docker/stationplay
   sudo chown -R 1026:100 data
   ```

4. Edit `docker-compose.yml` in File Station or a text editor. Set `user: "1026:100"` (your numbers) and change the other lines marked `<- CHANGE`. Your media folder is usually under `/volume1/`, such as `/volume1/video`.
5. Build and start it:

   ```
   sudo docker compose up -d --build
   ```

   On older systems, the command is `sudo docker-compose up -d --build`.

Intel-based Synology models with built-in graphics can use the GPU. Uncomment the Intel/AMD lines (see [GPU encoding](#gpu-encoding)).

### Unraid

1. From the **Apps** tab, install the **Compose Manager** plugin. It adds the `docker compose` command.
2. Copy the zip file into a share, such as `/mnt/user/appdata/stationplay`. Then open the terminal (the `>_` icon) and run:

   ```
   cd /mnt/user/appdata/stationplay
   unzip -o stationplay-<version>.zip
   cp src/docker-compose.yml .
   mkdir -p data && chown -R 99:100 data
   ```

3. Edit `docker-compose.yml`. Set `user: "99:100"` (Unraid's standard `nobody:users`, which owns your shares) and your media path (such as `/mnt/user/media`). Change the other lines marked `<- CHANGE`.
4. Run `docker compose up -d --build` in that folder.

For an Intel GPU, the `/dev/dri` folder must exist on the server. Unraid loads the Intel driver for most Intel graphics. See [GPU encoding](#gpu-encoding).

### Windows and macOS

StationPlay runs in **Docker Desktop**. The computer must stay on and awake for your stations to play.

1. Install Docker Desktop and start it.
2. Unzip the release into a folder, such as `C:\StationPlay` or `~/StationPlay`. Copy `src/docker-compose.yml` into that folder, next to `src`, and create a `data` folder.
3. Edit `docker-compose.yml`:
   - Delete the `user:` line. Docker Desktop manages file permissions itself.
   - Set your media folder with forward slashes, such as `D:/Media:/media:ro` on Windows or `/Users/you/Movies:/media:ro` on a Mac.
   - Change the other lines marked `<- CHANGE`.
4. In a terminal (PowerShell on Windows), go to that folder and run `docker compose up -d --build`.

Allow port 3310 through the computer's firewall if it asks. Docker Desktop can't use Intel or AMD graphics. On Windows, an NVIDIA GPU works through WSL 2 (see [GPU encoding](#gpu-encoding)). A Mac always encodes on the CPU.

If Plex runs on Windows, StationPlay can't translate its Windows file paths (such as `D:\TV\…`). It streams those files from Plex instead, which works but adds load to Plex.

### docker run

If you don't use Compose, build the image and start the container yourself. Run these commands from the folder you unzipped StationPlay into:

```
mkdir -p data && sudo chown -R 1000:1000 data      # use your UID:GID
docker build -t stationplay:<version> ./src
docker run -d --name stationplay --restart unless-stopped --init \
  --user 1000:1000 \
  -p 3310:3310 \
  -e PLEX_URL=http://192.168.1.10:32400 \
  -e PLEX_TOKEN=paste-your-plex-token-here \
  -e TZ=America/Chicago \
  -v "$PWD/data:/data" \
  -v /path/to/your/media:/media:ro \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --log-opt max-size=10m --log-opt max-file=3 \
  stationplay:<version>
```

- **Intel or AMD GPU.** Add `--device /dev/dri:/dev/dri --group-add <group number>` (see [GPU encoding](#gpu-encoding)).
- **NVIDIA GPU.** Add `--gpus all` (needs the NVIDIA Container Toolkit).
- **Page reachable from the internet.** Add `-p 3311:3311 -e PUBLIC_PORT=3311` (see [Security and remote access](#security-and-remote-access)).

Keep `--restart unless-stopped`. Restoring a backup restarts StationPlay, and Docker must start it again.

### GPU encoding

A GPU makes StationPlay much lighter on your server and lets more stations play at once, including at 1080p. StationPlay supports Intel and AMD graphics through VA-API (including the Quick Sync graphics built into most Intel Core CPUs) and NVIDIA graphics through NVENC. When the GPU supports a file's format, it decodes the file too. It also makes the converted copies for StationPlay's apps (see [StationPlay's own apps](#stationplays-own-apps)).

At startup, StationPlay test-encodes a short clip with the exact command it uses for real programs. It uses the first GPU that passes, trying NVIDIA first and then each Intel/AMD device. If none passes, it encodes on the CPU. The **Video encoding** line on the **Add to Plex** tab shows which is in use, and why when it's the CPU.

**Intel or AMD.** The container needs the `/dev/dri` folder and permission to use it:

```
devices:
  - /dev/dri:/dev/dri
group_add:
  - "107"     # the group that owns /dev/dri/renderD128
```

To find the group number, run `ls -ln /dev/dri` on the host and look at the group of `renderD128` (or run `getent group render`). It's usually `107` on TrueNAS. If the number is wrong, the **Video encoding** line names the right one. These lines are turned on in the TrueNAS YAML and commented out in `docker-compose.yml`. Remove them if the server has no `/dev/dri`, or the container won't start.

**NVIDIA.** On TrueNAS, turn on **Apps → Configure → Settings → Install NVIDIA Drivers**. Elsewhere, install the NVIDIA driver and the NVIDIA Container Toolkit. On Windows, Docker Desktop's WSL 2 backend provides GPU access. Then uncomment the `deploy:` block in the YAML or `docker-compose.yml`, or add `--gpus all` to `docker run`.

**Built-in safeguards:**

- **Programs fall back to the CPU.** A program that fails on the GPU carries on from the same point on the CPU. The file is marked broken only if it also fails there.
- **Copies fall back too.** A copy for StationPlay's apps that fails on the GPU carries on from the same point on the CPU and stays there. The viewer sees only the usual wait.
- **A failing GPU is set aside.** If 3 programs in a row fail on the GPU but play on the CPU, StationPlay stops using the GPU until it restarts. Copies count separately. If 3 in a row fail this way, only copies move to the CPU.
- **Stalls don't count.** A program that stalls on the GPU also moves to the CPU, but a slow disk causes stalls too, so they never count against the GPU.
- **The "We'll be right back" card** is always made on the CPU, so it works even if the GPU doesn't.

`HW_ACCEL` chooses the encoder: `auto` (default), `nvidia`, `intel` or `amd` (both mean VA-API), or `cpu`. With more than one GPU, `HW_DEVICE` picks one: a render node such as `/dev/dri/renderD129`, or an NVIDIA GPU number.

### Updating

Your stations, settings, logos, Intro Bumper videos and Broken files list live in the `data` folder, so updates keep them. Existing stations keep their settings. New defaults apply only to stations you make afterward. The version you're running is shown at the bottom of StationPlay's page.

**Always unzip the new version over `src` first,** then rebuild:

| Install | After unzipping the new version over `src` |
|---|---|
| TrueNAS SCALE | Edit the app, change the version in `image: stationplay:<version>` to the new one, and save. Change nothing else, so your Plex token and paths stay the same. |
| Docker Compose, Synology, Unraid, Docker Desktop | Change the version in `image:` in your `docker-compose.yml`, then run `docker compose up -d --build`. |
| docker run | Run `docker build -t stationplay:<new version> ./src`, then `docker rm -f stationplay`, then the same `docker run` command as before with the new version. |

Unzip the new version the same way you did when you installed: into the same folder, replacing the files in `src` (on TrueNAS, `sudo unzip -o /path/to/stationplay-<version>.zip`). Your edited YAML or `docker-compose.yml` isn't in `src`, so it's never overwritten.

On TrueNAS, the order matters. A new version number is what makes TrueNAS rebuild, and it builds from whatever is in `src` at that moment. If you save before unzipping, it builds the old code under the new number (see [Troubleshooting](#troubleshooting)).

**A database copy before each change.** Starting with 1.29.1, before an update changes StationPlay's database, StationPlay copies it, sign-ins included, to `data/backups` as `before-<version>-<date>.db` (such as `before-1.29.1-20261009-153000.db`). It notes this on the **Logs** tab, then makes the change. The newest 3 copies are kept. If it can't make the copy (because the disk is full, for example), it changes nothing and stops. Its log (`docker logs stationplay`, or the app's logs on TrueNAS) shows why. Make room, then start it again.

#### Rolling back

To go back to the version you had before an update:

1. **Stop StationPlay.** On TrueNAS, open **Apps** and choose **Stop** on stationplay. With Docker Compose, run `docker compose stop` in its folder. With docker run, run `docker stop stationplay`.
2. **Restore the database from before the update.** In the data folder, replace `stationplay.db` with the copy made before the update (the newest `before-<new version>-<date>.db` in `backups`). Delete `stationplay.db-wal` and `stationplay.db-shm` if they're there:
   ```
   cd /mnt/tank/apps/stationplay/data
   sudo cp backups/before-1.29.1-20261009-153000.db stationplay.db
   sudo rm -f stationplay.db-wal stationplay.db-shm
   ```
   Use your own folder and the copy's name. Using `cp` over the old file keeps its owner, so StationPlay can still write to it.
3. **Restore the previous version's `src`** by unzipping its zip over `src`, as when updating.
4. **Set `image:` back to that version** (such as `stationplay:1.29.0`) and start it, as when updating. On TrueNAS, edit the app and save it, then start it if it doesn't start by itself. With Docker Compose, run `docker compose up -d --build`. With docker run, build that version's image and run it as when updating.

Everyone stays signed in. Stations, settings and people return to how they were just before the update, and anything changed since then is lost. If the update didn't change the database, it made no copy, so skip step 2.

**Going back further?** Older versions don't know newer settings and may play some programs incorrectly. Before downgrading below 1.8, delete stations made from Plex collections, set **In the corner** to something other than **Clock**, and set each **Station ID card** to **Off** or **10 sec**. Below 1.6, also set **Commercials & trailers** to **None** and the **Station ID card** to **Off**. Below 1.4, also set **Intros & credits** to **Play them**. Wait for each change to take effect at the next program break before downgrading.

### Backups

StationPlay backs itself up automatically: about 15 minutes after it first starts, then every night at about 3 AM (in your `TZ` time zone). It keeps the newest 7 backups in `data/backups`. The database copies made before updates are kept there too, separately from these (see [Rolling back](#rolling-back)).

A backup includes your stations and their schedules, all settings, the Broken files list, the tuner's identity (so Plex still recognizes it), your logos (uploaded or from Plex), users and their passwords (stored only as hashes) and viewing stats. Intro Bumper videos aren't included, to keep backups small. They stay in `data/bumpers`, and a restore leaves them alone.

On the **Add to Plex** tab:

- **Download a backup** makes a backup now and downloads it. It's also saved in `data/backups` and counts toward the 7 kept.
- **Restore a backup…** replaces everything above with the backup's copy. StationPlay checks the file, restarts and puts the backup in place as it starts. First it saves what you had as a separate "before restore" backup, in case you change your mind.

After a restore, everyone signs in again as the users in the backup. A backup with no users turns sign-in off, so StationPlay asks before restoring one while sign-in is on.

### How StationPlay reads your files

StationPlay asks Plex where each file is, then reads it straight from disk. Plex reports paths as its own container sees them, such as `/data/tv/Show/episode.mkv`. You don't need to match those paths. Mount your media at `/media` (as the YAML and Compose files do), and StationPlay finds each file by matching the end of Plex's path inside `/media`. At least the file name and its folder must match. Once a match works, StationPlay reuses it for every other file. The **Media files** line on the **Add to Plex** tab shows whether files are read directly.

If StationPlay can't see a file, it streams it from Plex instead, which works but adds load to Plex. For unusual layouts, set the translation yourself with `PATH_MAPPINGS` under `environment:`. For example, `PATH_MAPPINGS: "/data/media:/media"` means "where Plex says `/data/media/…`, read `/media/…`". If Plex runs in Docker, use the paths inside Plex's container. Separate several pairs with `;`.

If your media share takes more than 8 seconds to answer, StationPlay treats it as temporarily unavailable. It skips those programs for now, without marking them broken.

### Security and remote access

**Keep port 3310 on your home network.** It serves Plex's tuner, guide and video streams, which never ask for a password, because Plex can't sign in to a tuner. Never forward it on your router or point a tunnel or reverse proxy at it. Plex only needs it inside your network. Plex users away from home can still watch, because Plex relays the stream.

**Using StationPlay's page from the internet.** StationPlay can open a second port just for its page, set with `PUBLIC_PORT`. It's 3311 in the YAML and Compose files, and it must differ from `PORT`. On that port:

- **No Plex addresses.** The addresses Plex and other apps use (the tuner, guides, streams and playlist) don't exist there.
- **Sign-in always required.** Before signing in, visitors see only the sign-in page, its icons and what a browser needs to install the page as an app (see **As an app** under [First-time setup](#first-time-setup)). Until StationPlay has its first user, the port shows only a message to add one from your home network, so no one can make themselves the first Admin from outside.
- **Wrong passwords limited.** The limits are 5 in 15 minutes per visitor address, and 100 in 15 minutes for the internet as a whole. A browser or app that has signed in before isn't held up by the internet-wide limit.

Put `PUBLIC_PORT` behind a Cloudflare Tunnel or a reverse proxy with HTTPS. [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home) explains each, and the other ways in. If you don't need it, remove the `3311` port line and `PUBLIC_PORT`.

**Built-in protections, however StationPlay is reached:**

- **Plex.** The page can't send its own requests to Plex. StationPlay makes only the requests it needs (library details, guide refreshes, folder scans and stopping blocked playback), so no one can misuse your Plex token through it. The page never sees the token or Plex's address.
- **Uploads.** A logo is accepted only as a PNG, JPEG, WebP, GIF or BMP image, and an Intro Bumper only as a video file. Each is turned into a clean copy before use. The limits are 500 of your own logos, 50 Intro Bumper videos, and no upload that would leave less than 2 GB free on the data folder's disk.
- **The page.** It runs only its own scripts, can't be embedded in another site, and refuses changes sent from other sites.
- **Backups.** StationPlay restores a backup only if it's a genuine StationPlay backup. Anything unexpected is refused before anything changes.

## Watch your stations

StationPlay offers your stations in two ways at once, on your home network:

| For | Address |
|---|---|
| Plex (as an HDHomeRun tuner) | Tuner: `http://<server-ip>:3310`<br>Guide: `http://<server-ip>:3310/xmltv.xml` |
| Jellyfin, Emby, Kodi and IPTV apps | Playlist: `http://<server-ip>:3310/stations.m3u`<br>Guide: `http://<server-ip>:3310/guide.xml` |

The **Add to Plex** tab shows these addresses with **Copy** buttons. Station numbers and logos come with them. You can watch in as many apps as you like. Everyone watching the same station shares one stream.

### In Plex

1. In Plex, open **Settings → Live TV & DVR → Set Up Plex DVR**.
2. Choose **Don't see your HDHomeRun device? Enter its network address manually** and enter the tuner address, `http://<server-ip>:3310`. Plex doesn't find StationPlay on its own.
3. When Plex asks for guide data, choose **Have an XMLTV guide on your server? Click here to use it** and enter `http://<server-ip>:3310/xmltv.xml`.
4. Continue. Plex matches your stations automatically (Plex calls them channels), and they appear under **Live TV**.

After that, StationPlay keeps Plex's guide up to date. Whenever a station changes, it asks Plex to refresh the guide. The **Guide updates** line on the **Add to Plex** tab shows whether that's working. If it isn't, refresh the guide yourself in **Settings → Live TV & DVR → your tuner → Refresh Guide**.

**After you create a new station,** choose **Scan for channels** in Plex's Live TV & DVR settings so Plex adds it.

**Plex Home and managed users.** To see your stations, a user's Live TV & DVR access must be **Allow Live TV and DVR access**. With "Allow Live TV only", Plex doesn't show them stations from a tuner.

### In Jellyfin

1. In the dashboard, open **Live TV** and choose **+** next to **Tuner Devices**.
2. Choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`. Save.
3. Choose **+** next to **TV Guide Data Providers**, choose **XMLTV**, and enter `http://<server-ip>:3310/guide.xml`. Save.

Leave Jellyfin's limit on simultaneous streams at its default (no limit). StationPlay enforces its own.

### In Emby

Emby's Live TV requires Emby Premiere.

1. In Emby's settings, open **Live TV** and add a TV source. Choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`.
2. Add a guide data provider. Choose **XMLTV** and enter `http://<server-ip>:3310/guide.xml`.

### In Kodi

1. Install the **PVR IPTV Simple Client** add-on (**Add-ons → Install from repository → PVR clients**).
2. In its settings, set the playlist location to remote and set **M3U play list URL** to `http://<server-ip>:3310/stations.m3u`. The playlist includes the guide's address, so **XMLTV URL** can stay empty. You can also enter `http://<server-ip>:3310/guide.xml` there.
3. Restart Kodi, or turn the add-on off and on. Your stations appear under **TV**.

### In other apps

Channels DVR, TiviMate, VLC and most IPTV apps accept the playlist address, `http://<server-ip>:3310/stations.m3u`. The playlist includes the guide's address.

**HLS players.** Each station is also available as HLS, the format used by Safari, iPhones, iPads, Apple TV and many other players: `http://<server-ip>:3310/hls/<station number>/index.m3u8`. It shares the station's one stream with everyone else watching, so a station never takes a second tuner. The HLS stream runs only while a player is asking for it. It stops 30 seconds after the last player stops asking, or right away when StationPlay's own apps tune away.

**Keeping other apps' guides current.** These apps download the guide on their own schedule, usually once a day. When you change a station, refresh the guide in the app (in Jellyfin, **Dashboard → Scheduled Tasks → Refresh Guide**). Otherwise the app shows that station's old schedule until its next refresh. Changes from Plex, such as new episodes, take effect when Plex downloads its guide. An app that refreshes less often may briefly show an older schedule.

**Away from home.** These addresses only work on your home network. Plex users away from home watch through Plex as usual. Other apps must be on your network or reach it over a VPN.

### StationPlay's own apps

**StationPlay for Android** is in private testing, in alpha like StationPlay itself. It isn't in any app store yet. The Apple app and the Roku app are coming. The apps connect directly to your StationPlay server, so you can watch your stations without Plex Pass or any other app.

- **Platforms.** In private testing: Android phones and tablets, Google TV, Android TV and Fire TV, in StationPlay for Android. Coming: iPhone, iPad and Apple TV, and Roku.
- **A guide for every screen.** On a TV, you browse it with your remote. On a phone, you see every station at a glance and swipe through the hours. On a tablet, the selected program and a live picture sit above the guide.
- **Changing stations.** While a station tunes in, you see its card in the same colors as its Intro Bumper. Flip up and down through your stations, enter a station number on your remote, or jump back to the last station you watched. If every tuner is in use, the app says so and lets you join a station that's already playing.
- **Favorites.** Mark the stations you watch most, and choose to show only those in the guide.
- **Night mode.** It softens loud scenes and makes quiet dialogue easier to hear, so you can watch late without disturbing anyone. Some devices can't change the sound themselves (Apple's player, a Roku). For those, StationPlay makes the station's night-mode sound on the server, only while someone is watching that way. The picture is copied unchanged, it uses the station's one tuner, and everyone else keeps the usual sound.
- **Sleep timer.** Choose 15 minutes to 2 hours, a clock time, or your own number of minutes, from anything playing. In the last 30 seconds, the picture fades to black. Then playback stops and the screen stays dark until you press a button, so the TV or device can go to sleep.
- **Phone and tablet extras.** Keep watching in picture-in-picture, choose whether the picture fits or fills the screen, and send it to your TV with AirPlay (Apple) or Cast (Android).
- **Secure sign-in.** On a TV, the app shows a short code. You enter it on StationPlay's page from your phone or computer, so you never type a password with a remote. On a phone or tablet, you can use your name and password instead. Every signed-in app appears under **Signed-in apps** on the **Access** tab, where an Admin can sign it out.
- **Watching away from home.** When an Admin turns this on, the apps also work away from home, for stations and Media alike. They connect over HTTPS through the same reverse proxy that serves StationPlay's page (see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)).
- **Built for stability.** An Admin sets how many devices can watch at once, including how many away from home. StationPlay tests what your server and internet connection can handle and recommends limits. When a limit is reached, the app explains why and asks the viewer to try again later.
- **Media.** Browse your shows and movies by title, genre, what's new or what you haven't watched. Jump to a letter, search, and pick up where you left off from the Resume row. Each title's page shows its cast and crew and titles like it. Skip an episode's intro and credits with one button, and choose subtitles and audio tracks.
- **The best picture and sound.** Each device gets the best picture and sound it supports, including Dolby Vision and Dolby Atmos. A file is repackaged or converted only when a device can't play it directly.

**Which StationPlay the apps need.** The apps need StationPlay 1.22.0 or newer. With an older version, the app says so: "The StationPlay at … is version …, but this app needs 1.22.0 or newer." For every feature, use the newest version:

| StationPlay | What the apps gain |
|---|---|
| 1.22.0 | The minimum |
| 1.28.0 | PINs |
| 1.29.0 | Languages and Admin alerts |
| 1.29.1 | Converted copies on request, and more detail on problems |
| 1.30.0 | Reporting a problem |

The apps read the stations and guide through [StationPlay's API](#stationplays-api), like any other program. They sign in, test connections and browse your library through their own addresses, documented for the apps in [docs/internal-api.md](docs/internal-api.md).

**Sharing your library with the apps.** The apps can't see your library until an Admin chooses which libraries to share, on the **Access** tab under **Media in StationPlay's apps**. Stations, Plex, Jellyfin and other apps aren't affected.

- **Your own Resume row.** Each person who signs in has their own Resume row, resume points and watched list. While sign-in is off, everyone shares one.
- **Limits apply.** Programs played from Media count toward the limit on devices watching at once.
- **One listing per title.** A title with several versions (4K and 1080p, say) is listed once. Each device plays the best version it can.
- **When playback can't keep up.** If playback keeps stalling, even with the buffer, the app tests the connection to find out why. It then offers a smaller version from where you are, or switches by itself, as you choose on the Access tab.
- **Copies only when needed.** A file plays unchanged whenever the device can play it. Otherwise StationPlay makes a copy as it plays, and the app can seek anywhere in it. A repackaged copy keeps the picture and converts only the sound, which costs almost nothing.
- **Converted copies.** A converted copy remakes the picture at up to 1080p in standard color. This uses the server's processor, so at most 3 are converted at once, or 6 with a GPU, which is light on the processor.
- **What else copies do.** A copy draws in subtitles the device can't show itself. It also makes a smaller picture when the connection can't keep up with any version.
- **Movies in several files.** A movie Plex keeps in several files ("cd1" and "cd2") plays as one program with their combined length. Resume, progress, seeking and watched status cover the whole movie. It plays as a copy that joins the files, repackaged when their pictures are alike (nearly always) and converted when they're not. Apps that predate the copies in StationPlay 1.24.0 can't play such a movie, and say so.
- **Where it plays.** Media plays on your home network or through a VPN. While **StationPlay's apps away from home** is on, it also plays through the public port.

The design is in [docs/on-demand.md](docs/on-demand.md).

**Media away from home.** With **StationPlay's apps away from home** on, Media plays away from home just as it does at home, for everyone signed in. Viewing Levels and the limits on devices watching still apply, and a device away from home also counts against the away-from-home limit. Under **StationPlay's apps away from home** on the Access tab, **Media away from home** sets the quality:

- **Original** (the default) plays each title as it would at home.
- **Up to** a number of Mbps (1 to 200) plays titles within that rate as at home. A file that needs more is converted down to fit, at most 1080p, and counts toward the copies converted at once.

The panel shows your home's upload speed, as StationPlay's apps measured it from outside. When a connection can't keep up, the apps still step down by themselves.

The video stream itself needs no sign-in. Each title an app plays through the public port gets its own random address, far too long to guess. It works only for a title started there, only over HTTPS, and only while that app's sign-in lasts. A title started at home is never offered there.

**Even sound for a show's episodes.** Episodes played from Media in StationPlay's apps play at the same loudness as the episodes on your stations (−24 LUFS). A show's episodes match in any order and in any app. Movies are never changed. Only the sound is remade (a repackaged copy, which costs almost nothing). With night mode on too, even sound is applied first. If the picture can't be kept unchanged, the episode plays unchanged instead.

Even sound is on by default. To keep each episode's original sound, such as Dolby Atmos or DTS sent on to a receiver, turn off **Even sound for a show's episodes** on the Access tab, under **Media in StationPlay's apps**. With it on, that sound plays as ordinary 5.1 or stereo. Apps that predate the copies in StationPlay 1.24.0 get each file unchanged.

**Languages.** Each person chooses their sound language and subtitles (on or off, and which language) in an app's Options. StationPlay saves the choices, so they follow that person to every device. From the player, a person can choose differently for a whole show, or for one episode or movie.

StationPlay uses the most specific choice: the episode's or movie's, then the show's, then the person's own, then the file's default. It picks sound in their language, never a commentary track when there's another. With subtitles on, it picks their language, preferring a full track over a forced one. With subtitles off, it shows only forced subtitles, for parts in another language.

Subtitles the device can't show are drawn into a copy. If an episode's chosen subtitles are inside its file and the device can show them, the episode plays unchanged instead of with even sound, because a copy carries no subtitles. Someone who hasn't chosen anything gets each file as before. Stations don't use these choices.

## Reaching StationPlay from outside your home

**Often you don't need to.** Plex users away from home watch your stations through Plex as usual, because Plex relays the stream. The same goes for Jellyfin and Emby, which reach StationPlay from your home network. Only StationPlay's own page and StationPlay's apps need a way in from outside.

**Never open port 3310 to the internet.** Its tuner and streams never ask for a password. Every way in below keeps it closed.

| Way in | Good for | Open to the internet | Setup | Cost |
|---|---|---|---|---|
| [A VPN: Tailscale](#tailscale) | The page and the apps, on your own phones, tablets and computers | Nothing | Easiest: an app on the server and on each device | Free for personal use |
| [A VPN: WireGuard on your router](#wireguard-on-your-router) | The same | One port, for the VPN | Moderate, if your router has it built in | Free |
| [A reverse proxy with HTTPS](#a-reverse-proxy-with-https) | The apps anywhere, for anyone you've added, with no VPN on their devices; also the page | Port 443, to the proxy, which reaches only StationPlay's public port | More: a domain name, a port forward and the proxy | A domain name, about $10 to $15 a year |
| [A Cloudflare Tunnel](#a-cloudflare-tunnel-the-page-only) | The page only, not the apps | Nothing | Moderate | Free |

A VPN is the most private. Nothing at all is open to the internet, and StationPlay treats a phone on the VPN as on your home network. A reverse proxy suits people who won't install a VPN, such as family elsewhere. A Roku can't run a VPN, so a Roku outside your home needs the reverse proxy.

**For StationPlay's apps**, turn on **StationPlay's apps away from home** on the **Access** tab (it's off by default). Enter the address the apps use from outside: your VPN address with its port (such as `http://nas.your-tailnet.ts.net:3310`), or your reverse proxy's `https://` address alone, with no port. Apps set up at home remember it and switch to it when home doesn't answer.

Each station watched away from home uses your home connection's upload: about 1.7 Mbps at 480p, 3.7 Mbps at 720p and 6.2 Mbps at 1080p. Shared Media uses upload too, at the quality set under **Media away from home** (Original, or up to a number of Mbps).

**StationPlay checks that the apps can reach it.** While this is on, StationPlay calls its own address the way an app away from home would. It checks a few seconds after it starts, when you save the address, every 5 minutes, and when you choose **Check now**.

- **Ready** means an `https://` address reaches the public port over HTTPS, or a VPN address reaches StationPlay. Shared Media plays through the same address, so it's covered too.
- **Anything else** comes with the problem in one sentence. Examples are a proxy that points at port 3310, an address without HTTPS, a name that isn't found, an expired or untrusted certificate, the proxy's own error, something else answering, or a redirect.

The status appears under the address on the Access tab and in the setup. For Admins, **Away from home** in the page's header shows **Up**, **Down**, **Checking** or **Can't check** on every tab, and opens the Access tab's panel. A single failure never makes it **Down**, because StationPlay checks again a minute later. The log records when it goes down, why, and when it's back.

**When your router answers from home.** Many routers don't let devices at home use the home's own internet address (this is called NAT loopback, or hairpinning). From home, the address then reaches the router, which answers with its own sign-in page, certificate or redirect, or not at all. Apps away from home still work fine.

So StationPlay ignores results that could come from the router (nothing answering, a certificate for another name or one that isn't trusted, something else answering, or a redirect) until a check from home has worked since it started. A proxy error, a name that isn't found, an expired certificate, or StationPlay's own answer describing a problem always counts. If a signed-in app came in through the public port in the last 15 minutes, the status is **Up**, and the panel shows when an app last came in from outside. Otherwise it's **Can't check**, with the reason. To be sure, open your address on a phone using mobile data, not Wi-Fi.

**The fix.** Add a DNS host override in your router (such as OPNsense's or pfSense's Unbound host overrides) that points your address's name at the reverse proxy's address on your home network. Devices at home, StationPlay included, then reach the proxy directly.

### Tailscale

1. Install Tailscale on the server. On **TrueNAS SCALE**, use **Apps → Discover Apps → Tailscale**. On **Unraid**, use the Tailscale plugin. On **Synology**, use **Package Center → Tailscale**. Elsewhere, use Tailscale's own installer or Docker image. Sign in, and turn on **MagicDNS** in Tailscale's admin console.
2. Install Tailscale on each phone, tablet, computer, Apple TV or Android TV that should reach StationPlay. Sign in to the same account, or share the server with that account.
3. Use the server's Tailscale name with port 3310, such as `http://nas.your-tailnet.ts.net:3310`. Use it for the page in a browser, and as the outside address on the Access tab for the apps.

Tailscale connects your devices directly and encrypts everything, so nothing on your router changes.

### WireGuard on your router

Many routers and firewalls have a WireGuard VPN server built in (Firewalla, UniFi, OPNsense, pfSense, GL.iNet and others). Turn it on and add each phone or tablet in the WireGuard app. While the VPN is connected, use StationPlay's home address (such as `http://192.168.1.20:3310`) as if you were home. The apps need no outside address for this, because their home address works over the VPN.

### A reverse proxy with HTTPS

The proxy (such as Caddy or Nginx Proxy Manager) takes HTTPS connections from the internet and passes them to StationPlay's **public port** (3311), never 3310. You need:

1. **A domain name** pointing at your home's internet address, such as `tv.example.com`. Use dynamic DNS if that address changes.
2. **Port 443 forwarded** on your router to the computer running the proxy.
3. **The proxy**, with a certificate (both proxies below get a free one from Let's Encrypt). It passes requests to `http://<your-server-ip>:3311` and passes on each visitor's address in `X-Real-IP` or `X-Forwarded-For`. Nginx Proxy Manager and NPMplus do both by default. StationPlay counts wrong passwords by that address and shows it in the access log, so the proxy must set it itself, replacing any value a visitor sends. StationPlay accepts `CF-Connecting-IP` only when a request came through Cloudflare, so a visitor can't send it to pose as someone else.

**Caddy** (the whole `Caddyfile`):

```
tv.example.com {
    reverse_proxy 192.168.1.20:3311 {
        header_up X-Real-IP {remote_host}
    }
}
```

**Nginx Proxy Manager** (or NPMplus): add a proxy host for `tv.example.com` that forwards to `192.168.1.20` port `3311`. On its **SSL** tab, request a Let's Encrypt certificate and turn on **Force SSL**. It passes on each visitor's address by itself.

Then, at home, open the **Access** tab. If you haven't yet, add the first user (an Admin) with a long password. Turn on **StationPlay's apps away from home** with `https://tv.example.com`. Leave out the port, because that's the proxy's address, and StationPlay itself never speaks HTTPS. Within a few seconds, the status under it should show **Ready**. If it says the proxy points at the wrong port, point it at 3311, never 3310.

Besides the public port's sign-in and password limits (see [Security and remote access](#security-and-remote-access)), StationPlay is protected there by these rules:

- **Apps connect only over HTTPS.** StationPlay refuses any app request the proxy didn't receive over HTTPS, so no password, sign-in or stream address crosses the internet unencrypted.
- **Private addresses for each app.** Each signed-in app has a private address for its stations, and one for each title it plays from Media. These stop working as soon as its sign-in ends: on sign-out, a new password, the person's removal, or an Admin signing that app out under **Signed-in apps** on the Access tab.
- **API tokens are refused there** unless an Admin turns on **Accept API tokens from the internet**. Even then, they work only with [StationPlay's API](#stationplays-api).

### A Cloudflare Tunnel (the page only)

A Cloudflare Tunnel reaches StationPlay's page without opening any port. It's not for the apps. Cloudflare's free plan isn't meant for video, and an app can't enter Cloudflare Access's email codes.

1. At home, on the **Access** tab, add the first user (an Admin) with a long password.
2. Keep `PUBLIC_PORT: "3311"` and the `"3311:3311"` port line.
3. In Cloudflare **Zero Trust**, add a public hostname to your tunnel (such as `tv.example.com`) with the service `http://<your-server-ip>:3311`. Never use 3310. Cloudflare passes on each visitor's address in `CF-Connecting-IP` by itself.
4. **Strongly recommended:** in Zero Trust **Access**, add that hostname as a self-hosted application, with a policy that allows only your people's email addresses. Cloudflare then asks for a one-time email code before anyone reaches StationPlay. StationPlay's sign-in becomes a second lock rather than the only one. This is free for up to 50 people.

## First-time setup

The first time an Admin opens StationPlay's page, the setup asks a few questions and checks that everything works. Use **Next** and **Back**, or the steps down the side. Each answer is saved when you move to another step. **Skip setup** leaves everything else unchanged.

1. **Checking your server:** whether StationPlay can reach Plex, and whether the account that owns your Plex server has Plex Pass, which watching in Plex needs. It also checks whether StationPlay can read your media files from disk, how it encodes video, whether its clock matches your browser's, and its backups. Anything marked **Needs a look** or **Not working** says what to do. After changing StationPlay's app settings, restart it, then choose **Check again**.
2. **How stations play:** the picture size for new stations and the number of tuners, with **Test this server** to help you choose.
3. **New station settings:** the defaults for new stations. These cover subtitles, commercials and trailers, the Station ID card, the Intro Bumper, the Up Next Banner, and what goes in the corner. Stations you already have don't change.
4. **Who can use StationPlay:** **Anyone on my network**, or **Only people who sign in**. With the second, you become the first Admin right away (see [Who can use StationPlay](#who-can-use-stationplay)).
5. **Who sees what:** each person's Viewing Level (see [Viewing Levels](#viewing-levels)).
6. **Watching away from home:** whether StationPlay's own apps can watch your stations away from home, and the address they use there (see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)).
7. **Media in StationPlay's apps:** which libraries the apps can browse and play in Media (see [StationPlay's own apps](#stationplays-own-apps)).
8. **Checking files:** when the overnight deep scan runs.
9. **Adding StationPlay to Plex:** the steps in Plex, the addresses to enter there, and whether Plex has StationPlay yet.
10. **All set:** your current settings, and anything that still needs attention.

To open the setup at any time, choose **Run setup again** on the **Add to Plex** tab, or **Setup** at the bottom of the page. Your current answers are filled in. The setup is the only place to change the settings for new stations. Everything else can also be changed on its own tab.

**After an update.** When a new version brings a question for an Admin, such as a new feature to turn on or a new choice, the setup opens once by itself with just those questions. It also shows the checks if something needs attention. Everything else stays as you set it.

**Light or dark.** StationPlay's page follows your device's light or dark setting. To keep it light or dark in one browser, choose **Light** or **Dark** under **Appearance** at the bottom of the page. **Automatic** follows the device again. The choice is saved in that browser only, so each person and device can have their own.

**As an app.** StationPlay's page fits phones, tablets and computers, in either orientation. You can add it to a phone's or tablet's home screen, or install it on a computer. It then opens in its own window, like an app:

- **iPhone or iPad.** In Safari, choose **Share → Add to Home Screen**.
- **Android.** In Chrome's menu, choose **Add to Home screen**.
- **A computer.** Choose **Install** in Chrome's or Edge's address bar, or **File → Add to Dock** in Safari on a Mac.

Install it from the address you sign in at, such as your reverse proxy's `https://` address. Chrome and Edge install only from an `https://` address. Nothing is stored on the device. The app always shows StationPlay's page live, so StationPlay must be reachable.

## Making stations

Choose **New station** on the **Stations** tab.

**The basics.** Give the station a **Number** and a **Name**, and choose a **Logo** (see [Logos](#logos)). A station with no name is called "Station 12", after its number.

**What's on it.** Under **What's on this station**, choose one of:

- **Pick shows & movies:** select titles from your Plex libraries, shown with posters and genres.
- **Use a filter:** describe what you want, and Plex keeps the station up to date as your library changes. See [Filters](#filters).

**Picking titles.** The **Filter** box searches titles, genres and years. Every word must match one of them, so "western 1959" finds Westerns from 1959. The three buttons next to it change the poster size. A title already on another station is marked ("Already on station 12"). Below the list, StationPlay totals the shows, movies and episodes you picked, and about how many hours that is. To add a whole library, choose **Everything in** that library. The list shows up to 3,000 titles per library. Type in the filter to find the rest.

**Settings.** The rest of the editor is grouped into **How it plays**, **Specials**, **Between programs**, **On screen** and **When someone tunes in**. Each group shows a summary when it's closed. If you close the editor with unsaved changes, it asks first.

**New station defaults.** Unless you chose otherwise in [First-time setup](#first-time-setup), a new station starts with **Shuffle**, black bars on 4:3 shows, intros and credits played, no commercials or trailers, no Station ID card, a 10-second Intro Bumper with sound, the station's logo large in the bottom-left corner during programs, a large Up Next Banner for 10 seconds, no subtitles and no specials.

### Filters

Instead of picking titles, a station can ask Plex which titles match and follow the answer as your library changes. Choose **Use a filter**, then combine any of these conditions. Each condition narrows the results. Several values in one condition mean "any of these".

- **Libraries:** one or more. A movie in two libraries plays once.
- **Any Plex filter for that library:** genre, content rating, network, studio, country, collection (including smart collections), label, director, writer, actor and more. People are searched as you type.
- **Decade** (TV shows count by the year they started) and **Title contains**.
- **Added in the last N days:** new arrivals. For TV, this means the episodes added in that time, so a "New This Week" station refreshes itself.
- **Minimum audience rating:** Plex's audience rating, out of 10. Titles without a rating are left out.

A count of matches, with examples, updates as you go. **Choose which…** lists every match, so you can uncheck any you don't want. Those stay out, while new matches still join.

Examples:

- **Action movies:** Genre: Action.
- **Spielberg movies:** Director: Steven Spielberg.
- **Classic TV:** TV shows, Decade: 1950s and 1960s.
- **Kids' TV:** Content Rating: TV-Y, TV-G.
- **Christmas movies:** Plex has no Christmas genre. Select your Christmas movies in Plex, choose **Edit**, add the label "Christmas", and filter on **Label: Christmas**.

### Stations from Plex collections

On the **Stations** tab, **From Plex collections** lists the collections in your TV and movie libraries, including smart collections. Check the ones you want and choose **Make station** (or **Make N stations**). Each becomes its own station, named after its collection, with the next free number and the default settings. A collection of shows plays every episode of those shows. You can make up to 200 at once. A collection that's already a station shows as checked.

Each station follows its collection. Titles added to or removed from the collection in Plex join or leave the station within about an hour. If a tool recreates the collection, the station finds it again by name.

### Smart stations

**Smart stations** on the **Stations** tab makes stations from a filter (see [Filters](#filters)). Then choose:

- **One station** of everything that matches, or
- **One for each** decade, genre, studio, actor or anything else Plex offers. StationPlay asks Plex how much each would have ("1960s Comedy · 88 movies") and lists up to 40. Check the ones you want and rename them if you like. For directors, actors, writers and producers, pick the names yourself when Plex can't list who's in what.

Examples: for 10 comedy stations, one per decade, use **Genre: Comedy** with **One for each → Decade**. For action and comedy shows together on one station, use **TV shows**, **Genre: Action, Comedy**, **One station**.

Each new station takes the next free number and gets a logo and the default settings. After that, it's an ordinary station. You can make up to 50 at once. Everything comes from your Plex server.

### Big stations

A station can be as big as you like. A shuffled station with tens of thousands of episodes takes several seconds to build, while other stations keep playing.

### The station card

Each station's card on the **Stations** tab shows what's on now, its description, who made it and when, and labels for anything that needs you (such as **2 broken**, **Update ready**, or an update that needs your review). **Details** opens a summary of every setting. While Details is closed, a red triangle means the station itself has a problem: it can't start, it's off the air, or it has nothing to play.

Card buttons:

- **Guide:** what's on now and over the next 2 days.
- **Edit:** opens the editor.
- **Duplicate:** makes a copy with the same shows and settings and the next free number, to change before saving.
- **Check files:** quick-checks every program on the station now (see [File checks](#file-checks)).
- **Update now:** applies changes from Plex at the next program break at least a minute away.
- **Reshuffle** (shuffled stations only): starts a new random order, also at the next program break at least a minute away.
- **Delete:** removes the station, with **Undo** for 10 seconds.

## How stations play

### One picture format per station

Each station is one continuous stream, as on broadcast TV. Everything on it (programs, commercials, cards) is converted as it plays to the station's format: H.264 video at the station's picture size, 29.97 frames per second, in standard color (SDR), with stereo sound. That's why a 4K movie, a 1960s DVD rip and a commercial can follow one another without a glitch, in any app.

Choose each station's **Picture** under **How it plays**. New stations use the size set on the **Add to Plex** tab.

| Picture | Size | Video data per viewer | Work for the server |
|---|---|---|---|
| **480p** | 854×480 | 1.5 Mbps | About half of 720p. For slower servers or many stations. |
| **720p** (standard) | 1280×720 | 3.5 Mbps | Sharp on most TVs, and light enough for most servers. |
| **1080p** | 1920×1080 | 6 Mbps | About twice 720p. A GPU helps a lot. |

Sound adds 192 kbps. A new picture size takes effect the next time the station starts, after everyone has stopped watching it.

**4K and HDR.** Stations play at up to 1080p in standard color, on purpose. Streaming 4K HDR would need a GPU fast enough to convert everything in real time, and about 20 Mbps per viewer. Plex Live TV also isn't known to pass HDR from a tuner through to the TV. So 4K programs are scaled down to the station's size. HDR programs (HDR10, HDR10+, HLG and most Dolby Vision) are converted to standard color the way a TV would, so they don't look washed out.

**Dolby Vision profile 5** files (common from streaming services) have no standard picture that anything but a Dolby Vision player can show correctly, so StationPlay doesn't play them. They're listed on the **Broken files** tab as **Unsupported**. Replace the file with another version, and it goes back on the air.

**Movies in several files.** Plex stacks a movie kept as several files (`Movie-cd1.mkv` and `Movie-cd2.mkv`, or "part 1" and "part 2") into one. StationPlay plays the files back to back as one program. The corner logo, the Up Next Banner and burn-in protection carry on across the join, and someone tuning in during the second file joins at the right place. The guide shows the files' combined time, as Plex reports it. If one file is missing or won't play, the movie is handled like any broken file. It goes on the **Broken files** list, which names the file ("part 2 of 3"), and a stand-in plays the rest of its time.

### Tuners

StationPlay's **tuners** set how many different stations it can play at once. Set the number from 1 to 20 on the **Add to Plex** tab. Plex doesn't cap this at 4 or any other number. It uses as many tuners as StationPlay offers. The real limit is your server, because each station being watched is converted in real time. The default, 4, is a safe start for most servers, and a GPU can usually handle more. **Test this server** (below) suggests a number for yours.

Everyone watching the same station shares one stream, so a station uses one tuner no matter how many people watch it. With 4 tuners, 4 different stations can play at once, for any number of viewers. The limit covers Plex and every other app together. While anyone is watching, a pill at the top of the page shows how many tuners are in use.

When every tuner is busy, someone tuning in to another station sees an **All tuners in use** card for 30 seconds, listing the stations that are on. Up to 3 people at a time see the card. Anyone beyond that gets Plex's own error. StationPlay reports more tuners to Plex than it really has, so Plex always lets it show that card. If you raise the number of tuners and Plex still won't play more stations at once, restart Plex.

A station keeps running for 20 seconds after its last viewer leaves, so flipping back is instant. During that time, the station gives up its tuner if someone else needs it.

**Test this server** on the **Add to Plex** tab makes a few seconds of video at each picture size and estimates how many stations your server can play at once. It runs at low priority, so stations that are playing aren't affected. Its suggestion leaves 30% headroom. **Use N tuners for 720p** applies it; choose **Save** to keep it. If you set more tuners than the test suggests, the page warns you.

### How many can watch at once

Every device watching through StationPlay's apps (or another player using the HLS addresses) receives its own copy of the station, over your network at home and over your internet upload away from home. A station still uses one tuner however many people watch it, so this limit is about your network, not your server's processor. Programs played from Media count too.

On the **Access** tab, under **How many can watch at once in StationPlay's apps**, an Admin can limit how many devices watch at once, and how many of those can be away from home. Leave a box empty for no limit. A device that's already watching can always change stations. A device beyond the limit sees a message such as: "An Admin has limited StationPlay to 5 devices watching at once, so it runs smoothly for everyone. Please try again later." Plex, Jellyfin and IPTV apps aren't counted here. They have their own limits, and the tuners cover them.

StationPlay recommends limits based on **connection tests** run in its apps. A test times data sent by StationPlay, so it measures the connection the way viewers use it. Run one at home, and one on a phone away from home (on mobile data, for example) to measure your home's upload. StationPlay doesn't use an outside speed-test service. The recommendation uses the fastest recent test and leaves 30% headroom. The page warns you if a limit is set higher.

### Schedules

Programs play back to back at their real lengths. Nothing is stretched or padded to fill 30- or 60-minute slots, so a 7-minute cartoon is followed right away by the next one.

- **Episode order:** one episode of each show in turn, each show in episode order, like classic reruns. Shows go in alphabetical order, and a movie counts as a one-episode show. When a shorter show runs out, the others continue without it. So a long-running show can play many episodes in a row near the end of the run. Then the run starts again.
- **Shuffle:** every program plays once per pass, and each pass is shuffled again, so a show doesn't air at the same time every day. No show plays more than twice in a row, and nothing from the end of one pass comes right back at the start of the next. If one show has more than twice as many episodes as everything else combined, that rule can't always hold, and the station card says "mostly one show".

StationPlay works out the schedule the same way every time, starting from when you saved the station. That keeps Plex's guide accurate, and restarting StationPlay never changes what's on.

### Updates from Plex

New episodes join stations automatically, and removed ones leave, without making Plex's guide wrong. Every hour, StationPlay asks Plex what changed and prepares an update. The update starts at the first program break after Plex next downloads the guide, so the guide Plex already has shows it. StationPlay asks Plex to refresh the guide when an update is ready, so this usually happens within the hour. The program on the air is never cut short. The station card shows **Update ready** while an update is waiting.

In episode order, the station continues with the program that was due. In shuffle, new programs are spread through the current pass where they fit, and the rest join the next pass. That way, 23 new episodes of one show don't turn into a marathon.

**Updates that need your review.** On a station with 10 or more programs, an update that would remove more than half of them isn't applied automatically. That's more likely a library being rescanned or a drive offline than something you meant. The card says "Plex lost N programs — needs your review". The same happens if Plex suddenly reports nothing at all, or loses the intro and credits markers for more than half of the programs a station skips them on. Choose **Update now** if the change is right.

**Shows that Plex re-adds.** When Plex re-adds a show or movie, it gets a new ID in Plex. This happens when it was removed and found again, rematched, or moved to another folder or drive. The station finds it again by title, and its episodes keep their places. When more than one show has that title (the same show in two libraries, say), the station follows the one in the library it came from. If that's unknown, it follows the one with the station's own files. If it still can't tell, the station keeps playing what it had, and the **Logs** tab names the show to choose again in the editor.

StationPlay never reads anything from file names. The show, season, episode and title all come from Plex, however your files are named. Plex's specials (season 0) are left out.

### Skipping intros and credits

Set **Intros & credits** to **Skip them** for binge-watching. Each program airs without its opening titles and end credits, and the next one starts right away. StationPlay uses the same markers as Plex's own **Skip Intro** and **Skip Credits** buttons:

- **Cold opens still play.** Anything before the intro plays as usual.
- **Final credits end the program.** A program ends where its final credits begin. Credits in the middle with a scene after them are skipped, and the scene still plays.
- **No markers, no skipping.** Programs without markers play in full. The station card shows how many programs have something skipped.
- **Exact guide times.** The guide shows each program's length without the skipped parts.

StationPlay uses markers only when they look right. An intro must start in the first half and be under 5 minutes. Credits must start in the second half. Skipping can't remove more than half a program or leave less than a minute.

Plex has to find the markers first. In Plex, go to **Settings → Library** and set **Generate intro video markers** and **Generate credits video markers** to run as a scheduled task and when media is added (a Plex Pass feature). StationPlay asks Plex again about programs without markers, first after 6 hours and then less often. Markers Plex finds later arrive like any other update.

### Sound and picture shape

**Sound.** TV episodes are brought to the same loudness (−24 LUFS, the US broadcast standard), so the volume doesn't jump between episodes. Movies keep their original sound, with its full range. Episodes played from Media in StationPlay's apps get the same treatment (see **Even sound for a show's episodes** under [StationPlay's own apps](#stationplays-own-apps)).

**4:3 shows.** Each station shows 4:3 programs with **Black bars** at the sides (the original shape), **Stretch** to fill the screen, or **Zoom**, which fills the screen and trims the top and bottom. Widescreen programs are never changed. Many 4:3 shows are stored as widescreen video with black bars built into the picture. With Stretch or Zoom, StationPlay detects those bars and removes them first.

### The guide

The guide covers the next 2 days, both in Plex and in StationPlay's own **Guide** button. Plex reloads the guide only about once a day on its own, which is why it covers 2 days.

## Station features

### Logos

StationPlay includes nearly 1,000 original station logos, all drawn for it:

- **Networks:** made-up broadcast, cable, movie and classic over-the-air TV networks.
- **Classic TV, TV shows, Cartoons & anime and Teens:** made-up stations in the style of each.
- **Genres:** three designs for each of Plex's 37 genres.
- **Themes:** decades, holidays, seasons, times of day, moods, kids and family, and on-air signs.
- **Letters and numbers:** A–Z and 1–50, in a modern and a retro style.

None copies a real TV network's or show's name, symbol or lettering.

A new station numbered 1 to 50 starts with its number's logo, which follows the number if you change it. Other new stations get a logo no other station is using. In the editor, **Choose…** opens the logo picker, with a search box and categories. When the station's name or filter suggests a genre, the picker opens on **Suggested** logos. **Surprise me** picks one at random. You can also show the **Station number** instead of a logo.

**Your own logos.** In the logo picker, choose **Upload your own…** and pick a PNG, JPEG, WebP, GIF or BMP image up to 10 MB. StationPlay makes it a 512×512 PNG on a clear background, so square images look best. Your logos are listed first, under **Your logos**, and stored in `data/logos`. Once no station uses one, you can delete it with its ×.

**Logos from Plex.** A new station with one show or movie is named after it. If Plex has a logo for it (the title artwork Plex shows on its pages), that becomes the station's logo. A name you type or a logo you choose yourself isn't replaced. On other stations, the first show's Plex logo is offered as **Use the logo from Plex**. StationPlay trims it, keeps its shape (most are wide) and sizes it to match the library's logos. It adds the logo to **Your logos** when you save the station.

Plex apps load logos from StationPlay's address, so they appear on your home network. Away from home, they appear only if StationPlay's address can be reached from there.

### In the corner

**In the corner** (under **On screen**) shows the station's **Logo**, its **Name**, or a **Clock** in a corner during programs, like a TV network. The clock is 12- or 24-hour, in your `TZ` time zone. Options:

- **Size:** Small, Medium or Large.
- **Transparency:** High, Medium or Low.
- **Corner:** click a corner of the preview to move it there.
- **Look:** **In color**, or **All white** like a real network's watermark.
- **When:** **Always**, or **At the start**. At the start means the first 30 seconds of each program, and of whatever is on when someone tunes in.

A station that shows its number instead of a logo shows its name in the corner. Nothing is shown during commercials, trailers or cards. Changes apply from the next program.

**Burn-in protection.** OLED and plasma TVs can be marked by a still picture left on for hours. To prevent that, the logo, name or clock moves a little, all through every program. Every 4 minutes, it steps to the next of 9 places. The places are 4 pixels apart, all within 6 pixels of where the station puts it. Its place depends only on the time of day. So tuning in, or a program resuming after a hiccup, never holds it in one place. The Up Next Banner moves with it, so the banner's logo still lands exactly on it. It works the same on the GPU or the processor. There's no setting. Every station does it.

### Up Next Banner

Three minutes before each show or movie ends, a banner in the bottom-left corner shows the station's logo, **Up next**, and the next program. Set how long it stays up (**Off**, 3, 5 or 10 seconds) and its **Size**. **Preview** shows it. If the corner logo is also in the bottom left, the banner takes its place while it's up. The banner skips programs shorter than 3 minutes and programs where what's next isn't known. Viewers who tune in after that point don't see it. If it can't be drawn in time, the program plays without it.

### Station ID card

**Station ID card** (under **Between programs**) adds a card after each program and its commercials. The card shows the station's logo, name and number, and **Up next** with the next program, for 3, 5 or 10 seconds. One of 15 short jingles plays underneath, always quieter than the programs. StationPlay made the jingles; none is borrowed from a real station. Set **Jingle** to **Off** for silence. The card's time is part of each program's time in the guide.

### Commercials and trailers

**Commercials & trailers** (under **Between programs**) plays **None**, 1, 2 or 3 clips after each program: commercials after TV episodes, trailers after movies. They're part of each program's time in the guide, so nothing is squeezed. Each clip plays about as often as the others and is brought to the same loudness as TV episodes.

The clips come from two folders, named exactly as shown (Linux names are case-sensitive):

- `commercials` at the top of your TV library's folder, such as `/mnt/tank/media/tv/commercials`
- `trailers` at the top of your movie library's folder, such as `/mnt/tank/media/movies/trailers`

StationPlay finds them through the folders Plex lists for each library. If a library is your whole media folder, put the folder directly inside it. Subfolders are fine. Clips from 3 seconds to 10 minutes long are used. Put a file named `.plexignore` containing `*` in each folder, so Plex doesn't add the clips to your libraries:

```
cd /mnt/tank/media
mkdir -p tv/commercials movies/trailers
echo '*' > tv/commercials/.plexignore
echo '*' > movies/trailers/.plexignore
```

**Commercials from the right decade.** Put clips in a subfolder named for a decade (`commercials/1960s` or `commercials/60s`), and they play only after programs from that decade, by the year Plex gives each program. Trailers work the same way. Clips outside decade folders play after everything else.

StationPlay looks in the folders at startup and every hour. Admins can choose **Check again** in the editor to look right away. If a folder seems to vanish (a share that isn't mounted yet), the clips already found are kept for a few hours. A clip that fails to play is left out until its file changes. It's listed on the **Broken files** tab under **Commercials and trailers that didn't play**, and a plain card fills its time.

### Intro Bumper

When someone tunes in, an **Intro Bumper** (under **When someone tunes in**) can play before the program, like a station ident:

- **Built-in card:** the station's logo arriving (in one of a dozen ways), "You're tuning in to", the station's name, a **Description** line and what's on, for 3, 5, 10 or 15 seconds. Its **Sound** is an old TV dial turning through static. **Preview** shows it.
- **Your video:** upload a video up to 30 seconds long (MP4, MOV, MKV, WebM and similar, up to 500 MB). StationPlay makes a copy at the right size, with its volume matched to the programs. Your videos are stored in `data/bumpers` and available to every station.

The bumper plays when a station's stream starts. Someone tuning in while others are already watching joins the stream in progress, without a bumper. If a bumper can't be shown, the built-in card or a plain card plays instead.

### Where viewers join

**Viewers join** (under **When someone tunes in**) sets what happens when someone tunes in:

- **In progress** (the default): like real TV. Tune in at 10:20 PM to a show that started at 10:00 PM, and you join 20 minutes in. The program keeps its place in the schedule, so viewers join it as far in as the bumper is long. In the bumper's last third, the show's sound fades in and carries straight into the show.
- **From the beginning:** the program on now starts from the beginning, right after the bumper. The station then runs that far behind the guide for as long as anyone is watching. Plex's guide still shows the schedule. When no one is watching anymore, the next viewer starts fresh. The bumper keeps its own sound to the end, so none of the program is missed. If someone tunes in during the commercials after a program, the next program starts from its beginning anyway. A program that began more than 2 hours earlier is joined in progress.

### Subtitles

**Subtitles** (under **On screen**) draws subtitles into the picture: **Off**, **Forced only** (just the lines meant to be read, such as foreign-language dialogue) or **Always**. They use the language set by `AUDIO_LANGUAGE` (English unless you change it). They come from the program's own file (text or DVD/Blu-ray picture subtitles) or from a subtitle file next to it, named the way Plex expects (`Movie (1999).en.srt`, `Movie (1999).en.forced.srt`). With **Always**, ordinary subtitles are preferred over SDH (with sound descriptions), and text over pictures.

Because subtitles are part of the picture, viewers can't turn them off. Text subtitles inside a file are extracted in the background, one program ahead, so a program's first airing may play without them. If subtitles can't be drawn, the program plays without them.

### Specials: marathons, Feature Presentations and blocks

Under **Specials**, three kinds of event can take over a station's schedule now and then. Each starts at a program break near its time: the start or end of the program airing then, whichever is nearer. On a movie station, that can be an hour away. When the special is over, the station picks up exactly where it left off. Specials are planned about a week ahead, before any guide shows them.

If two would overlap, a block wins over a Feature Presentation, and both win over a marathon. The other is skipped that time, and the **Logs** tab says so. A special that would start more than 15 minutes late, because the one before it ran long, is skipped too.

- **Marathons:** three episodes of one show in a row. Choose **Random times** (1 to 4 a week) or **Set times** (days and a time). Shows take turns. Each marathon plays **Next in order** (picking up where that show's last marathon ended) or from a **Random starting point**. A station needs at least 5 shows with 3 or more episodes each. Plex's guide adds "Show Name Marathon (1 of 3)." to each episode's description.
- **Feature Presentation:** a movie night on the days and at the time you choose. A 10-second **Feature Presentation** card plays first (**Preview the card** shows it), then the movie. **Movies from** sets the source: the station's own movies, a movie library or a movie collection. So a TV station can have movie nights too. Every movie is shown once before any repeats.
- **Blocks:** up to 4 time-of-day blocks, such as Saturday Morning Cartoons. Each has a name (up to 40 characters), days, start and end times, and its own shows (**Choose shows…**). A block can run 30 minutes to 12 hours, and past midnight is fine. It plays its shows in the station's order, ends at the program break nearest its end time, and picks up where it left off next time. A block is skipped if the nearest program break comes after its end time.

Saving is refused, with the reason, if a Feature Presentation has no movies, a block has nothing to play, two blocks overlap, or a Feature Presentation or marathon falls during a block. The station card shows when each special is next.

## Keeping stations on the air

A bad file should never take a station down. StationPlay is built around that.

### Safeguards

| When | What StationPlay does |
|---|---|
| A program won't open, or stops partway | Tries the same program again from where it stopped, twice (after 1 and 2 seconds). Many hiccups clear up by themselves. |
| It still won't play | Puts it on the [Broken files list](#the-broken-files-list), and a stand-in joins at the same point. If an episode fails 10 minutes in, the stand-in starts 10 minutes in and ends when the broken one would have, so the guide stays right. |
| Choosing a stand-in | Tries another episode of the same show first, then a program of the same kind, then anything long enough. In a block or Feature Presentation, its own programs come first. Up to 4 are tried. |
| Opening a file is slow (a sleeping drive, a busy NAS) | Keeps the stream alive with a few seconds of black. |
| A file stalls (no new video for 8 seconds) | Resumes or replaces it as above. A stall is blamed on storage, not the file. The file is skipped for the rest of that viewing, and listed only if it stalls in two separate viewings. A stuck ffmpeg process is abandoned after 2 seconds, and the next program reads ahead to rebuild the stream's 10-second cushion. |
| Something drawn over the picture fails (corner logo, banner or subtitles) | Tries the program again with nothing drawn over it before blaming the file. |
| Plex or the media share can't be reached | Skips the affected programs for now, without listing them. |
| A file is a few seconds shorter than Plex says | Fills the rest of its time with black. A file more than 10 seconds or 2% short counts as cut short. |
| A movie in several files | Plays each file in turn, opening the next while one plays. A file that's missing or won't play is handled as above, and a stand-in plays from there. While Plex can't be reached, StationPlay can't ask which files the movie has. Then a file that ends a minute or more before its time gets a stand-in for the rest, instead of black. |
| Nothing on the station can fill the time | Shows a "We'll be right back" card for the time that's left, then continues. |
| Nothing could play for two programs in a row | Shows "This station is off the air. Please report it." and logs an error. It keeps trying each new program and comes back on the air by itself. |
| The station's stream fails | Restarts it right away in the same stream, so viewers see at most a brief pause. It also restarts a stream that sends nothing for 45 seconds. After 3 failures within 5 minutes, the off-air card shows for 2 minutes before it tries again. A program that crashes the stream twice is skipped for that viewing. |
| Sonarr or Radarr upgraded or renamed a file | Nothing. StationPlay asks Plex for the current file every time a program plays. |

### The Broken files list

Files that can't play properly go on the **Broken files** list, shown on the **Broken files** tab and stored in `data/broken-files.json`.

- **One list for every file.** The list covers stations and Media in StationPlay's apps (the libraries an Admin shares with them). A file found broken for one is broken for the other too.
- **What each entry shows.** What's wrong, when it was found, how many times it failed, and the file's path. It also shows which stations have the file (each opens that station's editor), and whether it's in Media.
- **On stations.** Every entry is skipped on every station until it's cleared, and a stand-in plays in its place.
- **In Media.** A broken file doesn't play. Another version plays instead, if one isn't broken, and the apps say so. A damaged file still plays.
- **Versions.** A program's other versions (a 4K and a 1080p file, say) are separate files, and an entry for one is about that version alone. `broken-files.json` lists them under `versions`. Stations play a program's first version, listed under `files`.
- **Movies in several files.** Such a movie has one entry, for the file with the problem. Its reason ends with the part ("…, in part 2 of 3"), and its times and path are that file's. `part` and `parts` say which file it is. The whole movie is off the air until the entry is cleared, and **Retry** puts that file back on the air.

The tab has three parts:

- **Needs you:** people's reports (see [People's reports](#peoples-reports)), and files StationPlay found that are waiting for you. These are broken or damaged files a station or Media plays that Sonarr or Radarr aren't replacing by themselves, and files they couldn't replace. The tab's count is the number of items here. Admins are notified through their alerts (see [Troubleshooting](#troubleshooting)).
- **Being replaced:** what Sonarr or Radarr is fetching now.
- **Found by StationPlay:** everything else. That means files you're handling yourself, files no station or Media plays now (a missing one leaves the list by itself), and unsupported files.

| Label | Meaning |
|---|---|
| **Missing** | The file is gone from disk, or the program is gone from Plex, while a station or Media still has it. |
| **Broken** | The file won't play. |
| **Damaged** | It plays, but not properly (see [What counts as a problem](#what-counts-as-a-problem)). |
| **Unsupported** | It plays, but can't be shown correctly (Dolby Vision profile 5). |

When the files that need you include both missing files and other kinds, buttons above them show one kind at a time. **Download list** saves the whole list as a file.

**Clearing an entry yourself:**

- **Retry** means "the file is fine". The program goes back on the air, and the file checks leave that file alone from then on. An Unsupported file then plays with the wrong colors.
- **Removed a show on purpose?** Take it off the stations its entry lists, and its **Missing** entry clears itself within half an hour. Broken, damaged and unsupported entries stay even then, so a bad file can't return unnoticed.
- **Editing the list file.** You can also delete an entry from `broken-files.json`. StationPlay notices within 15 seconds. Unlike **Retry**, this doesn't tell the checks to leave the file alone.

**Entries that clear themselves:**

- **Every half hour,** StationPlay checks the list against Plex. An entry clears when Plex has the program again under a new ID, or when its file is missing (or Plex removed it) and neither a station nor Media has it anymore. An entry for one of a program's versions clears when Plex no longer has that version.
- **A new file** for a program gets a quick check, and the entry clears if the new file passes. Otherwise the entry says what's wrong with the new file.
- **Every night,** when the overnight checks begin (1 AM unless you change it), StationPlay re-checks programs taken off the air by a quick check or because their file couldn't be opened. A share may have been down. It does the same when you choose **Check the list again**. These entries clear if the files pass.
- **Deep-scan and playback problems** stay until the file changes, because checking the same file again would find the same thing.

StationPlay recognizes a program Plex re-added under a new ID by its own show, season and episode first. Next it tries the same file name, the same TVDB show, or the same episode title and year. It never matches by a title alone.

### File checks

StationPlay checks your files at the lowest priority, to find problems before anyone tunes in. It checks the stations' programs and what's shared for Media. Results are kept per file, so a file checked for a station isn't checked again for Media, or the other way around, unless it changes.

While anyone is watching, the checks step aside. The automatic checks wait until no one is watching. **Check files** and the list's re-checks read one file at a time, with a rest between files. ZFS and most NAS disks ignore low disk priority, so reading less at once is what helps.

The checks wait in one line, in this order:

1. **A station's program airing soon** (in the next 3 hours, or in an update about to start) that's due a check.
2. **A file someone just had trouble with.** That can be a copy for an app that couldn't be made or stopped, an app reporting that something didn't play or stopped, or a person's report. StationPlay decodes the minute starting 20 seconds before where it happened, as the deep scan would, then gives the file the quick check. For a report that says where, it also runs the deep scan if those find nothing. Only what StationPlay finds puts the file on the list, so trouble caused by the network or the app changes nothing.
3. **Quick check, when something arrives.** A program new to a station, then anything newly added to a library shared for Media, is quick-checked within minutes, before it airs if possible. The file must open, and picture and sound must decode at five points (start, quarter, half, three quarters and end).
4. **Weekly.** Every program on a station is quick-checked again once a week. This also catches files that went missing or were replaced. Media's files are checked when they arrive, and when someone has trouble with one.
5. **Overnight deep scan.** Between 1 AM and 6 AM, files are decoded in full. To change the time or turn it off, use **Deep scan every night from** on the **Broken files** tab. The stations' programs go first, soonest to air first. Then come Media's files: what's in someone's Continue Watching, the next episode of a show someone is watching, then the rest, most recently added first. A file that hasn't had its quick check gets one first. The scan stops the moment anyone starts watching and continues later. Each file is deep-scanned once, and again only if it changes. A 45-minute episode usually takes a few minutes.

**Check files** on a station card quick-checks all of its programs right away. A new station gets this automatically.

**A movie in several files** has each of its files checked in order, by both the quick check and the deep scan. A problem in any of them takes the movie off the air, and its entry names the file.

The **Broken files** tab shows how far the checks have gotten, for the stations and for Media, and what the deep scan is doing.

#### What counts as a problem

| Result | What it means |
|---|---|
| **Broken** | The file won't open or has no picture. Or nothing decodes after some point. Or its picture stops early (more than 10 seconds or 2% short of its stated length, whichever is more). Or it can't be read (a disk or share error, seen on two different nights). |
| **Damaged** | The picture breaks up, the sound drops out, or the file skips (see below). No sound, or no picture and sound, for 30 seconds or more partway through. No sound track, or silence all the way through (for programs from 1930 on). A completely black picture. Sound that stops before the picture does, unless it stops during the end credits, over a black picture, or after fading out in the last minute. A file that plays well past its stated length, so its ending would be cut off. |
| **Fine** | A decoder warning about something no one would see or hear, a patched picture shown for an instant, sound lost for less than 20 ms at one spot, anything in the first 2 seconds or last 5, a pause or silence under 30 seconds, a picture held still while sound plays (such as end credits over one drawing), a black opening, and a file slightly shorter than its stated length. |

**How the deep scan judges glitches.** Decoders report many errors that change nothing you'd see or hear. One example is Dolby TrueHD's "quant_step_size larger than huff_lsbs", common in Atmos tracks. Each one costs at most 1/1200 of a second of sound. So StationPlay judges by ffmpeg's report on each frame:

- **Picture.** A picture ffmpeg couldn't decode, or had to patch because part of it was missing or garbled, counts when later pictures are built on it. The damage then stays on screen until the next full picture, often for seconds. One is enough. A patched picture shown for just one frame (a B-frame) doesn't count. Tests comparing damaged files with clean ones found that damage gone within a frame or two.
- **Sound.** Each lost or garbled frame of sound costs a fixed slice of time: about 21 ms for AAC, 32 ms for Dolby Digital, 11 ms for DTS, and under 1 ms for TrueHD. It counts when 20 ms or more is lost within one second, which you'd hear as a click or dropout.
- **Skipping.** Part of the file's container is garbled, so playback jumps ahead.

None of these can freeze a player. StationPlay decodes every program and encodes it again, so players always receive a clean stream.

Each entry says what was found and where, such as "the picture breaks up around 12:31 and 48:02" or "no sound from 12:00 to 12:40". Glitch times are approximate. The real spot can be a few seconds before the time shown.

When an update changes how files are checked, files are checked again under the new rules: quick checks within hours, and deep scans over the following nights. Programs taken off the air by the old quick check go back on the air right away and are re-checked first.

### Replacing files with Sonarr and Radarr

StationPlay only needs Plex. But if you use **Sonarr** (TV) or **Radarr** (movies), StationPlay can ask them to replace files on the Broken files list that a station or Media plays. Both apps get the same choices and limits. Sonarr and Radarr version 3 and later work. For one of a program's versions, this works only when the app's file is that version. Problems people report are replaced only when you choose **Replace** on the report (see [People's reports](#peoples-reports)).

**Turning it on.** On the **Broken files** tab, open **Replacing files with Sonarr and Radarr**. For each app:

1. Check **Use Sonarr for episodes** (or **Use Radarr for movies**).
2. Enter its address, such as `http://192.168.1.10:8989` for Sonarr or `:7878` for Radarr.
3. Enter its API key, found in the app under **Settings → General**.
4. Choose **Test**, then **Save**.

API keys are stored in StationPlay's database (and its backups) and never shown again.

**Choices:**

- **Files to replace:** **Broken or damaged**, **Missing**, or **Both** (the default). Choose **Broken or damaged** if missing files are usually ones you removed on purpose.
- **When to replace:** **Only when I ask** (the default) or **Automatically**.
  - With **Only when I ask**, nothing happens until you choose **Replace with Sonarr** (or **Radarr**) on an entry. After that, the app handles it on its own.
  - With **Automatically**, every entry is replaced without asking. Choose **I'll handle it** on an entry to stop that for it, and **Replace with Sonarr** to start again.
  - **Retry** still means "the file is fine".

StationPlay only asks about what the app is **monitoring** (in Sonarr, both the show and the episode). To tell both apps to leave something alone, unmonitor it there. The entry notes this, and **Try again** picks it up once it's monitored again. StationPlay finds a show by its TVDB ID (or its title) and a movie by its TMDB or IMDb ID (or its title and year). It continues only if exactly one matches.

**What happens:**

1. **A broken or damaged file:** StationPlay first has the app **blocklist** the release the file came from, as **Mark as Failed** in the app's History does, so the app won't download it again. Then the app deletes the file (into its recycle bin, if you set one) and searches for another. This only happens if the app's file is exactly the one StationPlay found broken (same name and size) and the app has a record of downloading it. A file you added by hand can't be blocklisted, so it's left to you.
2. **A missing file:** the app rescans the folder, then searches for it.

Each episode or movie gets up to **3 searches, 8 hours apart**, or sooner if the last search brought a file that didn't work. When the app has a new file, StationPlay asks Plex to scan that folder, checks the new file, and puts the program back on the air once it passes. If Plex still hasn't found the file after a day, the entry shows **Can't replace**.

**The same problem twice.** Sometimes the new file has the same problem at the same times (at least half of them within 30 seconds of the old file's). Then the problem may be part of the program itself, such as an old film's transition effects. StationPlay stops, blocklists nothing, and marks the entry **Needs your review**. Watch the program at those times. If it looks fine, choose **Retry**. If not, **Try another file** blocklists that file too and searches again.

Each entry shows what the app is doing: **Replacing**, **Downloading**, **Downloaded**, **Gave up** (3 searches found nothing that works; **Try again** starts over), **Can't replace**, **Needs your review** or **You're handling it**. The **Logs** tab records every step. Unsupported files aren't replaced this way, because you're the best judge of the right version.

### People's reports

People can report a problem from StationPlay's apps: from a movie's or episode's page, from the player's menu, or from a station's player (about what's on it now). They pick the problem from a list rather than typing it:

| Group | Problems |
|---|---|
| **Picture** | No picture; The picture breaks up or freezes; Poor picture quality |
| **Sound** | No sound; The sound cuts out; The sound is out of sync; Wrong language |
| **Subtitles** | Subtitles are missing or wrong |
| **The program** | It won't play; It stops before the end; Wrong episode or movie |
| **Details** | Wrong title, details or artwork |

Each report includes who sent it, from what device, where in the program it happened, and how it was playing (unchanged or as a copy, which version, and which sound track and subtitles). Reports go to the **Broken files** tab, under **Needs you**. Several reports on one program share one row.

| A report of | What StationPlay does |
|---|---|
| No picture, the picture breaking up, no sound, the sound cutting out, stopping early, or not playing | Checks the file right away, ahead of everything but a station's program about to air. It checks around where the problem happened, then runs the quick check. If the report says where and those find nothing, it runs the deep scan. If it finds the problem, the file goes on the list and is replaced according to your settings. If not, the report says StationPlay found nothing wrong, for you to **Dismiss**. |
| The sound out of sync, the wrong language, the wrong episode or movie, poor picture quality, or subtitles | Waits for you, with what StationPlay can tell next to it: the file's sound languages, its length compared with the show's other episodes, its picture size and its subtitles. Choose **Replace with Sonarr** (or **Radarr**), **Find a better copy** or **Dismiss**. Replacing blocklists the release and fetches another, as for a broken file, and the program is off the air until then. **Find a better copy** has the app search for an upgrade, keeping the file until it finds one. |
| Wrong title, details or artwork | Waits for you to fix it in Plex (**Fix Match** or **Edit** on its page there), then **Dismiss** it. |

A report never takes anything off the air, or out of Media, by itself. Only StationPlay's own checks or your choice can do that. Each person can send one report a day about each program, and 10 a day in all. An Admin can turn reporting off for someone with **Can report problems**, on the **Access** tab or under **Reports from StationPlay's apps** on the **Broken files** tab. Admins can always report. Reports are kept while they wait, and for 90 days after they're handled.

## Who can use StationPlay

When StationPlay is first installed, its page is open to anyone on your network. On the internet port, `PUBLIC_PORT`, sign-in is always required. To require sign-in at home too, choose **Only people who sign in** during setup, or add a user on the **Access** tab with a name and a password of at least 8 characters. **The first user is always an Admin**, and you're signed in right away. After that, everyone else sees a sign-in page.

| Role | Can do |
|---|---|
| **Admin** | Everything. |
| **User** | Watch the stations and library their Viewing Level allows, and see the Stats tab. Make stations (3 by default; an Admin can choose none, 1, 3, 5, 10, 25 or no limit) and change or delete only their own. On a Viewing Level with limits, they can only watch. Add logos and Intro Bumper videos (only Admins can delete them). Can't open **Add to Plex**, **Broken files**, **Logs** or **Access**. |

- **Always an Admin.** There's always at least one Admin. Removing the last user turns sign-in off again.
- **Older stations.** Stations made before sign-in was turned on, or by a removed user, can be changed only by Admins.
- **Managing people.** On the **Access** tab, an Admin can rename people (including themselves and other Admins), change roles and set new passwords.
- **Renaming.** A new name must differ from everyone else's, ignoring capitalization, as for a new user. The person signs in with it from then on and keeps everything: their sign-ins and linked devices, the stations they made, their Viewing Level, where they are in what they watch, and their stats. StationPlay's apps show the new name the next time they check.
- **Your own account.** Choose your name at the top of the page, or Options in StationPlay's apps, to change your password or sign out.
- **Permissions.** **Can change their own password**, next to each person's **New password**, and **Can report problems**, below it (see [People's reports](#peoples-reports)), are on by default. Admins can always do both. A new password signs that person out everywhere else.
- **Sign-in limits.** A sign-in lasts 30 days after it was last used. After 5 wrong passwords from one address within 15 minutes, that address has to wait. Passwords are stored only as salted hashes.
- **Page timeout.** StationPlay's page signs you out after an hour without activity. StationPlay's apps stay signed in.
- **No password for Plex.** Plex and IPTV apps never need a password, just like a real HDHomeRun. The tuner, guide, streams, logos and playlist stay open on your network.

### Viewing Levels

Each person has a **Viewing Level** that sets what they can see in StationPlay's apps and on its page. Admins always see everything. Choose a person's level next to their name on the **Access** tab. Under **Viewing Levels**, you can rename, change or remove the other built-in levels, and add as many of your own as you need, such as "Adults" with no R-rated movies or unrated titles, or "Grandparents".

| Level | Movies up to | TV up to | Unrated titles |
|---|---|---|---|
| **Unrestricted** (everyone's level by default; can't be changed) | No limit | No limit | Shown |
| **Teen** | PG-13 | TV-14 | Hidden |
| **Kid** | PG | TV-PG | Hidden |
| **Young Child** | G | TV-G | Hidden |

- **Ratings.** Plex's content ratings are read as ages, for the US and other countries alike (such as `gb/15` or `de/12`). An episode counts as its show's rating, or its own if that's stricter. A title with no rating, or one StationPlay doesn't recognize, counts as unrated.
- **Libraries.** A level can also be limited to some libraries. That way, a show in both "TV Parents" and "TV Teens" is seen only through the library a person's level includes.
- **Stations are all or nothing.** Everyone watching a station sees the same stream. So a station is shown only if everything it plays is within the person's level. To allow or block a station for someone anyway, choose **Stations** next to their name. It also shows why each station is shown or hidden.
- **Nothing hidden shows.** What someone can't see isn't in any list, search, guide, Resume row or "on now" for them. Its address answers as though it doesn't exist.
- **Watching only.** People on a level with limits can watch what they can see, but can't make stations, because the station editor shows your libraries as a whole.
- **Plex and other apps.** Plex, Jellyfin and IPTV apps don't report who's watching, so they show every station. To keep stations from some people in Plex, see **Blocking stations for some Plex users**, below.

StationPlay learns the ratings of what's on each station as it checks Plex for updates. Until it knows a station's ratings, that station is hidden from anyone with limits.

### Linked devices and Who's tuning in?

StationPlay's apps can share one device among several people, such as the living room TV. The first time someone signs in on the device, with their password or a code entered on StationPlay's page, the device is **linked**. From then on, it opens on **Who's tuning in?**, and whoever is watching picks themselves.

- **Who's on the list.** Choose **Devices** next to a person's name, then one of these:
  - **Only devices they sign in on:** at home and away. Unless Bo has signed in on your TV, he isn't on its list, and you aren't on his phone's.
  - **Every device at home:** for a household. They're on every device while it's at home or on your VPN. Away from home, they're only on devices they signed in on or that you choose.
  - **Every device, at home and away:** even a phone at a friend's house.
  - **Only devices you choose:** such as a family iPad that travels.
- **Where new people start.** **New people show on**, under **Linked devices**, sets this. The default is **Only devices they sign in on**. If you chose **Devices at home** there before 1.30.1, that choice stays (as **Every device at home**). Someone with no password and no PIN can't sign in, so they start on **Every device at home**.
- **Changing everyone.** Changing **New people show on** doesn't move anyone already added. **Use for everyone**, next to it, does. It first asks, showing how many people it changes. Devices you chose for someone stay chosen. People with no password and no PIN can't be on **Only devices they sign in on**, so that choice leaves them unchanged, and the page names them ("Kept as they were: Kids (no password or PIN)").
- **Signing in again.** With **Only devices they sign in on**, someone who used to pick themselves on a device must sign in on it once (**Sign in**, with their password or an invite code) to be on its list again. Picking yourself isn't signing in.
- **PINs.** A person can have a 4-digit PIN, which the device asks for when they pick themselves. An Admin without a PIN enters their password instead. After 5 wrong PINs, that person must wait 15 minutes, on every device.
- **Choosing a PIN.** The first time someone signs in on a device with their password or an invite code, the app asks them to choose a PIN or none. They can change it in the app's Options. An Admin who has a PIN keeps one. An Admin can set or remove anyone's PIN under **Devices** on the **Access** tab.
- **No password needed.** A User can have no password, such as a "Kids" user who only picks themselves on the TV. Without a password or a PIN, they can't sign in by name, so they can only be on **Every device at home** or **Only devices you choose**.
- **Sign in on a new device.** Choose **Sign in** on Who's tuning in?, then enter your name and password, or an **invite code** an Admin made for you under **Devices**. An invite code works once, for 7 days. You're then on that device's list. Anyone can take themselves off a device's list.
- **Unlinking.** **Linked devices** on the **Access** tab lists each device and who's on its list. **Unlink** signs the device out at once.

A sign-in from Who's tuning in? lasts a day from when it was last used, so a shared device returns to the list instead of staying signed in as someone.

**Access log.** On the **Logs** tab, check **Access** to see sign-ins, failed sign-ins, sign-outs and changes to users. The newest 2,000 entries are kept across restarts.

**Locked out?** Create an empty file named `reset-access` in StationPlay's data folder (for example, `sudo touch data/reset-access`) and restart the app. Every user is removed, the page is open again, and the file is deleted.

### Blocking stations for some Plex users

*Optional; needs Plex Pass.* Plex can't hide a station from one person. Every station appears in the guide for everyone with Live TV on your server, and Plex's parental controls don't cover Live TV. Instead, StationPlay can stop someone's playback.

On the **Access** tab, under **Block stations for some Plex users**, choose which stations each Plex user can't watch. Check **Stop Plex users from watching stations blocked for them**, and choose **Save**. When a blocked user tunes in, Plex stops their playback within seconds and shows "This station isn't available on your Plex account." in Plex apps that show messages. If they tune in again, it's stopped again. The tab lists recent stops, and the **Logs** tab records each one.

**Requirements:**

- **Plex Pass** on the account that owns your Plex server. The tab shows whether Plex reports it.
- **Watching in a Plex app.** This covers you, your Plex Home users (including managed users), and friends you've shared Live TV with. Apps using the M3U playlist aren't covered.
- **A Plex user for each person.** Everyone sharing one Plex account counts as one user.
- **Sign-in turned on in StationPlay.** Otherwise anyone on your network could turn blocking off.

StationPlay only stops a stream when it's sure which station it is: only one station with viewers is airing exactly what Plex shows, or only one matches the station number Plex reports. If two stations air the same program at once and Plex gives no station number, StationPlay can't tell them apart and stops neither. The log notes this once. While a blocked user's station has viewers, StationPlay asks Plex what's playing every 5 seconds.

## Stats

The **Stats** tab shows how much each station is watched: viewings, hours watched, average viewing, when it was last watched, and its most-watched show or movie. Below that are the most-watched shows and movies overall, and the times of day people watch. Choose **Today** (since midnight), **7 days**, **30 days** or **All**.

A viewing counts once it lasts a minute, so flipping past a station doesn't count. Viewings are counted per stream, so several people watching one station together in Plex can count as one viewing. Each of StationPlay's apps counts on its own. Stats are kept for 400 days, and a station's stats are deleted with it.

Admins see more, and so does everyone while sign-in is off:

- **Server**, at the top, updated every 5 seconds while the tab is open. It shows the processor and memory StationPlay uses and the whole machine's (or the container's memory limit, if it has one), what it's sending and receiving, which GPU is in use with how many stations and copies, and the data folder's free space. Each has a chart of its last 10 minutes. Figures come from Linux itself (in Docker, the container's own). Anything StationPlay can't read shows "not available".
- **Watching now**: one row for each person watching. It shows who, what (a station and what's on it, or something from Media), which app on which device, at home or away, and since when. It also shows how the video is sent: unchanged, repackaged or converted, its picture size and bitrate, and on the GPU or the processor.
- **Top people**: who watched most, stations and Media together, and what each person watches most. In StationPlay's apps, viewing counts for whoever is signed in. At home, it counts for whoever's app last asked for the stations from that device.
- **Plex viewing per person.** While a station has viewers, StationPlay asks Plex every 30 seconds what it's playing and to whom, and matches each Live TV session to a station. Plex users are marked **Plex**. Viewing in other apps isn't counted per person, and neither is Plex time when two stations air the same program at once. If your Plex token isn't allowed to see what's playing, the tab says so.
- **Top Media**: the shows and movies played most in Media, with hours and plays. Watching the same thing again on the same device soon after (with another sound track, or a smaller version) counts as one play.

## StationPlay's API

*Optional.* Your own scripts, home automation (such as Home Assistant) and other players can use StationPlay's API, under `/api/v1`. It covers the server, its stations with what's on now and next, the guide, each station's HLS stream, and how StationPlay is doing. With an Admin token, scripts can also update a station from Plex, check a station's files, ask Plex to refresh its guide, and make a backup. It's documented in [docs/api.md](docs/api.md), with an OpenAPI spec at `/api/v1/openapi.json` (also in [docs/openapi-v1.json](docs/openapi-v1.json)).

Version 1 is a stable contract: it only grows. New fields and addresses may be added, but nothing is renamed, removed or changed in meaning. A change that would break a client comes as version 2, served next to version 1. Version 1 then carries `Deprecation` and `Sunset` headers for at least 6 months before it's removed.

**API tokens.** While sign-in is off, the API needs no token on your network. Once sign-in is on, an Admin makes a token for each script on the **Access** tab, under **API tokens**. Give it a name, choose **Viewer** (read only) or **Admin**, and choose when it expires. The token is shown once, so copy it then. StationPlay keeps only a hash of it. Scripts send it as `Authorization: Bearer <token>`.

- **API only.** A token works only with the API, never with StationPlay's page. It never does more than the Admin who made it may do now.
- **Revoking tokens.** The Access tab shows when each token was last used. Revoke one there at any time. Removing the Admin who made a token revokes it too. The access log records each token made and revoked.

**From the internet.** API tokens are refused on the public port until an Admin checks **Accept API tokens from the internet** on the **Access** tab. Even then, they work only over HTTPS, through a reverse proxy or a Cloudflare Tunnel (see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)). With Cloudflare Access in front, a script also needs a Cloudflare Access service token. A VPN is simpler still: StationPlay treats a script on the VPN as on your home network.

StationPlay's own apps also use addresses under `/api/internal`. Those are for the apps only, aren't part of the API, and may change with any release.

## Settings

StationPlay is set up mostly on its page. These environment variables, in the YAML or `docker-compose.yml`, cover the rest:

| Variable | Default | What it does |
|---|---|---|
| `PLEX_URL` | *(none)* | Your Plex server's address, such as `http://192.168.1.10:32400`. Required. |
| `PLEX_TOKEN` | *(none)* | Your Plex token (see [Finding your Plex token](#finding-your-plex-token)). Required. |
| `TZ` | `UTC` | Your time zone, such as `America/Chicago`. Used for the clock, specials, the overnight checks, backups, stats and log times. |
| `MEDIA_DIR` | `/media` | Where your media is mounted inside the container. |
| `PATH_MAPPINGS` | *(none)* | For unusual layouts only: `plex/path:local/path`, with several separated by `;`. |
| `HW_ACCEL` | `auto` | `auto`, `nvidia`, `intel`, `amd` or `cpu`. See [GPU encoding](#gpu-encoding). |
| `HW_DEVICE` | *(automatic)* | With more than one GPU: a render node (`/dev/dri/renderD129`) or an NVIDIA GPU number. |
| `PORT` | `3310` | The port for Plex, other apps and your home network. |
| `PUBLIC_PORT` | *(off)* | A separate port for the page from the internet. Must differ from `PORT`. See [Security and remote access](#security-and-remote-access). |
| `AUDIO_LANGUAGE` | `eng` | Preferred language for sound tracks and subtitles. |
| `FRIENDLY_NAME` | `StationPlay` | The tuner's name in Plex. |
| `BASE_URL` | *(automatic)* | Only if Plex reaches StationPlay at a different address than your browser does. |
| `IDLE_GRACE_SECONDS` | `20` | How long a station keeps running after its last viewer leaves. |
| `AUDIO_BITRATE_KBPS` | `192` | The stations' sound bitrate. |
| `DATA_DIR` | `/data` | Where StationPlay keeps its data inside the container. |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe` | For a custom ffmpeg build. The image's own is recommended. |

Picture sizes and the number of tuners are set on the page. Versions before 1.14 used `TUNER_COUNT` and `VIDEO_HEIGHT`. If they're still set, the page starts from them once and then ignores them, and the **Logs** tab says so. `VIDEO_WIDTH` and `VIDEO_BITRATE_KBPS` are no longer used.

## Troubleshooting

Start with the **Logs** tab, which shows the newest 200 entries. Check **Warnings** or **Errors** to filter, and use **Copy** to paste them into a message. `docker logs stationplay` (or the app's logs in TrueNAS) has everything.

**What's playing.** The log names each station by its number and name ("station 2, Cartoon Classics") and describes what plays as it starts:

- **A station's program:** its file, its picture and sound ("1080p H.264, 5.1 E-AC-3"), and how the station makes it ("made 720p at 3.5 Mbps on the Intel/AMD GPU", "HDR made ordinary", "subtitles drawn in"). The same line notes a viewer tuning in from the beginning.
- **Media in StationPlay's apps:** who started what, in which app on which device, at home or away; its file, picture and sound; and how it plays: unchanged, repackaged (and what changed, such as its sound made AAC stereo), or converted.
- **A converted copy:** what it was converted to, on the GPU or the processor, and why. The reason can be something the device can't play, a picture made smaller to fit the connection, subtitles drawn in, or night mode's sound.
- **A step down in quality:** when an app switches to a smaller version or copy, one line shows from what to what and why, with the app's own reason when it sends one.
- **Stopping:** who stopped what, where in it, and how long they watched. An app watching a station reports when it stopped, and after how long.

**Problems in the apps.** At the top of the **Logs** tab, StationPlay's apps report problems as they play: a station that doesn't start or stops, something from Media that doesn't play, playback that can't keep up, the app closing unexpectedly, or the app not reaching StationPlay for a minute or more (such as "Den couldn't reach StationPlay for 12 minutes · No network on this device"). An app that can't reach StationPlay sends what went wrong once it's back, with the time of each problem.

Each problem shows how often it happened, on how many devices, for whom, and on what kinds of device (the app, its version, the device's model and system). **One kind of device** marks a problem seen on only one kind, which points to that device or its app. A problem on every kind of device points to StationPlay or the file. Under each problem:

- **What it means** explains the player's error in plain words, for the errors StationPlay knows.
- **What the app said** gives the error exactly as the app sent it.
- **What led up to it** shows the app's last lines before the error.

Problems are kept for 30 days. **Clear** removes them, and the log keeps its own record. For more about one device, use its **Send a report to StationPlay** (in the app's Options), which adds what the app did recently.

**Alerts.** StationPlay alerts Admins when something needs attention:

- **Plex.** Plex can't be reached, or won't accept StationPlay's token.
- **The data folder.** It has less than 2 GB free, or can't be written to.
- **A failing station.** A station keeps failing to start (3 times in 10 minutes).
- **Backups.** Backups fail twice in a row.
- **The clock.** StationPlay's clock is more than 2 minutes off from Plex's. This uses the time in Plex's answers; without it, the clock isn't checked.
- **Away from home.** StationPlay's apps can't reach it from outside.
- **Broken files.** Something on the **Broken files** tab needs an Admin: a person's report, a broken or damaged file that isn't being replaced automatically, or one Sonarr or Radarr couldn't replace. An example: "There are 3 files to look at on the Broken files tab: Tia reported No sound on Northbound S2 E4". This alert appears at most once an hour. It starts again when there's something new, an hour or more after the last one.

An alert starts only once a problem persists (for Plex, five checks a minute apart), and clears only once things stay right, so alerts don't flicker on and off. Each start and fix adds a line in the **Logs** tab. Admins also see a pill in the page's header with the number of current alerts, which opens a list of them, and they see alerts in StationPlay's apps too.

Alerts are kept in StationPlay's database, so a restart doesn't repeat them. An open alert stays open (the **Logs** tab notes it's still going) until its check finds it fixed. Then it's reported fixed, once. That's so even if it was fixed while StationPlay was stopped. The apps' list of alerts fixed in the last day survives restarts too. A restored backup starts with no alerts, so anything still wrong is reported again.

**Notifications.** To get alerts elsewhere, open **Notify a web address** at the top of the **Logs** tab, turn it on, and enter a web address. Use an ntfy topic (**Plain text**), or a Gotify message or Home Assistant webhook address (**JSON**: `{"title": "StationPlay", "message": "...", "kind": "...", "state": "started"}`, or `"fixed"`). **Send a test** tries it right away. StationPlay waits 5 seconds for an answer, tries once more, follows no redirects, and keeps only the answer's status. Only Admins see the address, and the log names only its site.

**Installing and starting**

- **The app keeps restarting, and the log says it can't write to `/data`.** The data folder isn't owned by the user StationPlay runs as. The message shows the `chown` command to run. Fill in your data folder's path, run it, then restart the app.
- **The app won't start, and mentions `/dev/dri`.** The GPU lines are in the YAML, but the server has no Intel/AMD graphics. Remove the `devices:` and `group_add:` lines.
- **Docker says port 3310 or 3311 "is already allocated" or "address already in use".** Another app on the server uses that port. Change only the first number of the port line (for example, `"3320:3310"`). Then use the new port in every address: in your browser, and in Plex or your other apps.
- **After updating on TrueNAS, the page still shows the old version.** The app was saved before the new version was unzipped into `src`, so TrueNAS rebuilt the old code under the new number. Check that `src/app/__init__.py` has the new version. Then edit the app, raise the version in `image:` once more, and save. Restarting the app never rebuilds it.
- **The page shows "Plex: PLEX_URL and PLEX_TOKEN aren't set"** or **"Plex didn't accept the token in PLEX_TOKEN".** Fix those two settings. Users (not Admins) see only "Plex: not connected". If Plex runs in Docker on the same machine, use the machine's network IP in `PLEX_URL`, not `localhost`.

**Plex**

- **Plex can't find the tuner.** StationPlay doesn't answer Plex's automatic network search. Enter the address manually (see [In Plex](#in-plex)).
- **Plex says no tuners are available.** If you raised StationPlay's tuners, restart Plex so it reads the new number. When StationPlay's own tuners are all busy, viewers see its **All tuners in use** card instead.
- **The guide shows the wrong program.** In Plex, choose **Settings → Live TV & DVR → your tuner → Refresh Guide**, wait a minute, then reload the Plex app. Apps keep the guide they loaded. The **Logs** tab says "Plex downloaded the guide" when Plex has the new one.
- **Plex says "Device not found".** Plex is looking for StationPlay's tuner under an old ID or address. The **Logs** tab shows which tuner Plex lists, such as `device://tv.plex.grabbers.hdhomerun/1A2B3C4D at <address>`. StationPlay's own ID is the `DeviceID` at `http://<server-ip>:3310/discover.json`.
- **Fixing a different ID.** If the IDs differ (after starting with a fresh data folder, say), put Plex's ID in `data/device.json` as `{"deviceId": "1A2B3C4D"}` (exactly 8 hexadecimal characters). Make sure the file belongs to StationPlay's user (such as `sudo chown 1000:1000 data/device.json`), and restart StationPlay. If the address is wrong, set up StationPlay in Plex again.
- **A managed user can't see the stations.** Their Live TV & DVR access must be **Allow Live TV and DVR access**.
- **Skipping intros and credits doesn't skip anything.** The card says "no intros or credits found yet" until Plex has marked some programs. Check Plex's marker settings (see [Skipping intros and credits](#skipping-intros-and-credits)). Plex finds intros by comparing a season's episodes, so a season with very few episodes may not get them.

**Playing**

- **A station shows "This station is off the air. Please report it."** Nothing on it could play for two programs in a row, or its stream failed 3 times within 5 minutes. The **Logs** tab says why. Usually Plex or the media share can't be reached, or every program on the station is on the Broken files list.
- **A stream stops.** The **Logs** tab says what happened. "Viewer … left station … after …" means the player closed the connection itself. "Viewer … was disconnected from station …" gives StationPlay's reason. "is falling behind real time" means the server can't convert video as fast as it plays. Use a smaller picture size, fewer tuners, or a GPU.
- **HDR movies look washed out.** At startup, the **Logs** tab notes if ffmpeg can't convert HDR. StationPlay's own image can.
- **Subtitles don't show.** The program needs subtitles in the `AUDIO_LANGUAGE` language, in its file or next to it. With **Forced only**, it needs forced ones. A program's first airing may play without them while they're extracted.
- **No commercials or trailers play.** The editor shows how many were found. The folders must be named exactly `commercials` and `trailers`, at the top of a library's folder as Plex lists it, and visible inside `/media`.
- **A Feature Presentation or block doesn't happen.** The station card shows when the next one is. A more important special may have overlapped it, or it would have started too late. The **Logs** tab says which.
- **Up Next Banners never appear, and the log mentions the data folder's path.** `DATA_DIR` is set to a path with characters ffmpeg can't handle. Remove the `DATA_DIR` setting, because the default, `/data`, always works. The folder's name on your server doesn't matter.

**Files and the Broken files list**

- **Many files go on the list at once.** Check the reason. If StationPlay can neither see the files under `/media` nor reach Plex, programs are skipped, not listed. If Plex itself has lost the files, they're listed as "can't open the file" or "removed from Plex". Check the **Media files** line on the **Add to Plex** tab, fix the cause, then use **Retry**.
- **A file is listed as Damaged, but plays fine for you.** Choose **Retry**. It goes back on the air, and the checks leave that file alone.
- **A station stopped following Plex.** An update that would remove more than half its programs waits for you. Choose **Update now** if it's right (see [Updates from Plex](#updates-from-plex)).

**GPU**

- **The GPU isn't used.** The **Video encoding** line on the **Add to Plex** tab shows why. Usually it's the group number in `group_add` (the message names the right one) or `/dev/dri` not being passed to the container. `docker exec stationplay vainfo` shows whether the Intel/AMD driver sees the GPU.
- **"… was turned off after 3 programs in a row failed on it".** StationPlay stopped using the GPU to keep stations playing. Restart StationPlay to try the GPU again. If it keeps happening, check the GPU driver.

**Access and blocking**

- **Locked out of StationPlay's page.** See **Locked out?** under [Who can use StationPlay](#who-can-use-stationplay).
- **"Plex wouldn't stop … Stopping playback needs Plex Pass on the server owner's account."** Blocking needs Plex Pass on the account that owns the server.
- **"Plex won't say who's watching…"** Your Plex token isn't allowed to see what's playing. Use the server owner's token. Stats by Plex user and blocking both need it.

## Development

```
pip install -r requirements.txt pytest pytest-asyncio
python -m pytest                     # all tests, including end-to-end tests with real ffmpeg (35 to 45 minutes)
STATIONPLAY_SOAK=1 python -m pytest -k soak -o faulthandler_timeout=0              # two long soak runs, 8 minutes each
STATIONPLAY_SOAK=1 STATIONPLAY_SOAK_MINUTES=30 python -m pytest -k soak -o faulthandler_timeout=0
STATIONPLAY_REALWORLD=1 python -m pytest tests/test_e2e_realworld.py

docker build --target test -t stationplay-test .           # all tests in the image as it ships, as GitHub runs them
docker run --rm --init stationplay-test

pip install ruff mypy
ruff check app tests && ruff format --check app tests      # lint and formatting
mypy app                                                    # type checks
```

The tests need ffmpeg on the `PATH`. The HDR and real-world tests also need ffmpeg with libx265, and they're skipped without it. `requirements.txt` is pinned for Python 3.13. A test still running after 5 minutes prints where every thread is (`faulthandler_timeout` in `pytest.ini`), and with `-v` its name comes first, so a test that hangs names itself. The end-to-end tests run a fake Plex whose library includes a cut-short file, an unopenable file, a file with no sound and a source that stalls. They also use a stand-in ffmpeg (`tests/fake_gpu_ffmpeg.py`) that acts like a GPU and can be told to fail. They check that a viewer receives one continuous, clean stream that keeps pace with the clock.

`.github/workflows/image.yml` is optional. If you keep the code on GitHub, it builds the image and runs the tests inside it whenever `main` changes, without publishing anything: the Dockerfile's test stage is the image that ships, with its own FFmpeg and Python, plus the tests. The tests stop after an hour. The Dockerfile pins its base image by digest, so every build starts from the same Debian and Python; a comment there says how to update it. `.github/workflows/quality.yml` runs the plan's longer quality checks in the image every Monday, or from its **Run workflow** button: two soak tests of 4½ hours each, and the real-world and HDR tests. It publishes nothing.

**The setup's questions.** When a release adds something an Admin needs to answer (a feature that's off until they turn it on, or a new choice), it goes in the setup. Add a new question to `QUESTIONS` in `app/setup.py`, with its step on the page (`SETUP_PAGES` in `app/web/js/setup.js`). For a question that gains a choice, raise its version by one. After the update, the setup opens once by itself with just that question.

**The page at every screen size.** Before a release, run `python tools/page_sizes.py /tmp/page-sizes` (it needs Playwright and Pillow). It runs StationPlay with stand-in data and saves a screenshot of every tab and dialog at phone, tablet and computer sizes, light and dark, signed in as an Admin and as a User. It lists anything that scrolls sideways, is cut off, or is too small to tap.

**Updating, rolling back and installing fresh.** For every release, `python tools/upgrade_check.py` tests the upgrade path:

1. Starts the previous release (by its git tag, unpacked into a temporary folder) on a new data folder. Through its API, adds an Admin, a User with a PIN and a Viewing Level, a linked device, settings and a station.
2. Starts this checkout on the same folder, and checks that everything is there, everyone is still signed in, and the database was backed up first (a release that doesn't change the database makes no copy).
3. Makes two alerts live, sent to a web address it stands in for, and restarts with them. Checks that neither is sent again, and that one fixed while StationPlay was stopped is reported fixed once.
4. Starts the previous release on the current database, live alert and all.
5. Rolls back as [Rolling back](#rolling-back) describes, and checks that the previous release works with its data.
6. Installs this checkout fresh.

It uses its own ports, stops only what it started, and cleans up afterward. `--from v1.28.1` starts from another release, and `-v` shows every check.

**Releases.** Each release's notes are in `docs/releases/v<version>.md`. Their first lines name the commit of that version (`commit: <its full ID>`), which must be a commit `main` was tested at (for a merge, the merge commit). `.github/workflows/release.yml` runs each time the image workflow finishes on `main`. For each version not yet published, it checks that the commit is on `main`, is that version, and passed the image workflow's tests (on that commit, or on a later one that changed only release notes). Then it publishes the release on GitHub: the tag at that commit, the notes, the files built from that commit (`stationplay-<version>.zip`, `stationplay.yaml` and `docker-compose.yml`), and its image (`ghcr.io/<you>/stationplay:<version>`, and `:latest` for the newest). A version whose tests are still running waits for them, and one whose tests failed isn't published; the run says why in one line. Push and test each version's commit before the next one's. Public releases start with 1.31.0, the first under the AGPL: notes for earlier versions stay in `docs/releases` as history and are never published.

### The logo library

The logos in `app/logos/` are drawn by code in `tools/logos/`, not by hand. `kit.py` is the drawing kit. `networks.py`, `classic_tv.py`, `tv_shows.py`, `movies.py`, `toons.py`, `kids.py`, `genres.py`, `themes.py`, `seasons.py` and `letters.py` design each group from the kit's lettering, pictures (`symbols.py`) and layouts (`layouts.py`). `build.py` draws them all with Chromium and writes the PNGs and `catalog.json`. Only the PNGs and `catalog.json` ship. The fonts are open-licensed (SIL Open Font License or Apache 2.0) and needed only to redraw the logos:

```
cd tools/logos
npm install                                  # the fonts, listed in package.json
pip install playwright pillow imagequant
python -m playwright install chromium
python build.py                              # every logo (unchanged ones come from .cache/)
python review.py /tmp/sheets networks        # contact sheets for checking a group
```

Three logos also use system fonts: DejaVu Sans (Sing-Along) and Noto Sans CJK JP (two anime logos). The Station ID jingles are made by `tools/bumper/` (needs numpy).

### Code map

| Path | Job |
|---|---|
| `app/main.py` | Web server: Plex tuner endpoints, streams and the API |
| `app/config.py` | Settings from environment variables |
| `app/broadcaster.py` | Each station's engine and its safeguards |
| `app/tsstitch.py` | Joins programs into one continuous MPEG-TS stream |
| `app/ffmpeg.py` | ffmpeg and ffprobe commands |
| `app/schedule.py` | Episode order, shuffle rules, and schedule and guide math |
| `app/playback.py` | Picture sizes, tuners, the "All tuners in use" card, and the speed test |
| `app/setup.py` | The setup: which questions an Admin is asked (all of them at first, then only new ones after an update), and its checks |
| `app/specials.py`, `app/marathons.py` | Marathons, Feature Presentations and blocks |
| `app/smart.py` | Smart stations |
| `app/subtitles.py` | Subtitles drawn into the picture |
| `app/replacement.py` | Choosing stand-ins for programs that can't play |
| `app/markers.py` | Plex's intro and credits markers |
| `app/updates.py` | Following Plex: hourly checks, and when updates take over |
| `app/db.py` | Stations and settings (SQLite) |
| `app/library.py` | Your shows and movies, whichever library they're in (Plex, for now) |
| `app/plex.py` | Talking to Plex |
| `app/sources.py` | Finding the file to play, and matching Plex's paths to `/media` |
| `app/broken.py` | The Broken files list |
| `app/jobs.py` | Check files, and re-checking the Broken files list |
| `app/scanner.py` | Quick checks, weekly checks and the overnight deep scan |
| `app/replacing.py`, `app/arr.py` | Replacing files with Sonarr and Radarr |
| `app/gpu.py` | GPU detection, the startup test, and turning off a failing GPU |
| `app/hls.py` | Stations as HLS, for StationPlay's apps and other HLS players |
| `app/appapi.py`, `app/api.py` | StationPlay's API (`/api/v1`): the server, stations and guide; API tokens, Admin actions and the OpenAPI spec. Also the apps' own sign-in and connection tests (`/api/internal`) |
| `app/links.py` | Signing in an app with a code |
| `app/away.py`, `app/reach.py`, `app/capacity.py` | StationPlay's apps away from home, and the check that they can reach it; limits on devices watching, and connection tests |
| `app/ondemand.py`, `app/applibrary.py`, `app/catalog.py` | Media in StationPlay's apps |
| `app/languages.py` | Each person's languages in StationPlay's apps, and the sound and subtitles chosen from them |
| `app/converting.py`, `app/keyframes.py` | Copies of what a device can't play directly: repackaged or converted, as HLS |
| `app/hdhr.py` | HDHomeRun and XMLTV formats |
| `app/breaks.py` | Commercials, trailers and Station ID cards |
| `app/intro.py` | Drawing the Intro Bumper and Station ID card, and their sound |
| `app/upnext.py` | The Up Next Banner |
| `app/bumpers.py` | Intro Bumper videos you upload |
| `app/backups.py` | Backups and restores, and the database copy made before an update changes it |
| `app/access.py` | Sign-in, Admins and Users, and the access log |
| `app/viewing.py`, `app/ratings.py`, `app/titles.py` | Viewing Levels: what each person can see, ratings read as ages, and the ratings of what's on each station |
| `app/devices.py` | Linked devices, Who's tuning in?, PINs and invite codes |
| `app/stats.py`, `app/watching.py` | Viewing stats, who's watching now, and matching Plex sessions to stations |
| `app/health.py` | The server's health for the Stats tab: processor, memory, network and storage, from Linux's own files |
| `app/alerts.py`, `app/notify.py` | Admin alerts, and notifying a web address of them |
| `app/playing.py` | What's playing, in words: how the log names stations, files and apps, and whose app is where |
| `app/limits.py` | Blocking stations for some Plex users |
| `app/logos.py`, `app/logos/` | The logo library and your own logos |
| `app/text.py`, `app/logbuffer.py` | Cleaning up names people type; recent log entries for the Logs tab |
| `app/assets/` | Sounds and other files the app draws with |
| `app/web/index.html`, `app/web/manifest.webmanifest` | StationPlay's page, and what installing it as an app takes (with its icons, made by `tools/app_icons.py`) |
| `app/web/page.css`, `app/web/js/` | The page's styles, and its scripts, one file for each part of the page (loaded in the order `PAGE_FILES` in `app/access.py` lists them) |
| `tests/` | Unit and end-to-end tests |
| `Dockerfile`, `stationplay.yaml`, `docker-compose.yml` | The image, the TrueNAS app, and the Compose file |
| `docs/` | StationPlay's logo; StationPlay's API (`api.md`, `openapi-v1.json`); the apps' own addresses (`internal-api.md`); the designs of the library (`library.md`), of Media in the apps (`on-demand.md`), and of who sees what (`users.md`); each release's notes (`releases/`) |

## Contributing

Bug reports, ideas and fixes are all welcome. A good bug report says what you expected, what happened instead, and what the **Logs** tab showed at the time. Its **Copy** button makes that easy.

Before sending a code change, run the tests and lint checks in [Development](#development), and add a test for anything new. StationPlay aims to be simple and reliable, and to depend on nothing but Plex. It uses plain, friendly American English on its page and in its logs, and says "station" rather than "channel". Changes that keep to those ideas are the easiest to accept.

By sending a change, you agree that it's shared under StationPlay's license (see [License](#license)) and that you have the right to share it.

## Forks and credit

StationPlay is free and open-source software. You're welcome to fork it, change it and build on it, as its license allows. If you do, please respect the original project:

- **Give credit.** Say clearly that your project is based on StationPlay by egadgetboy, with a link back to it, in your README and on your app's About page or footer.
- **Keep the notices.** Leave the copyright and license notices in place, including the credit line at the bottom of StationPlay's page, and note what you changed.
- **Use your own name and logo,** so people can tell your version from StationPlay and know where to ask for help with it.
- **Send improvements back.** If you fix a bug or add something useful, consider offering it to StationPlay too, so everyone's stations get better.

## License

StationPlay is Copyright © 2026 egadgetboy and is licensed under the [GNU General Public License, version 3](LICENSE) (GPL-3.0). In short:

- You may use, study, change and share StationPlay, including for profit.
- If you share StationPlay, changed or not, you must include its source code or offer it, under the same license.
- Keep the copyright and license notices, and mark what you changed.
- StationPlay comes with no warranty.

This is only a summary. The [LICENSE](LICENSE) file is what applies. The packages StationPlay uses, and the fonts used to redraw its logos, keep their own licenses.
