<p align="center"><img src="docs/logo.svg" alt="StationPlay" width="360"></p>

> [!WARNING]
> ## StationPlay is in ALPHA
> It works, but it is far from finished. Features are still being added and changed, some of what this README describes is still on its way, and things may break between versions. **TESTING ONLY - do not rely on it for anything yet!** Back up your data folder before you update.

# StationPlay

StationPlay turns your Plex library into always-on TV stations. Pick some shows or movies, give the station a number and a name, and it plays them around the clock like a broadcast channel. A program guide comes with it, and you can add commercials, station IDs, a corner logo, movie nights and Saturday-morning blocks if you like.

Plex sees StationPlay as an HDHomeRun network tuner, so your stations show up in Plex's **Live TV** guide on every Plex app. Jellyfin, Emby, Kodi and most IPTV apps can watch them too.

StationPlay is free, open source and self-hosted (see [License](#license)). It runs in Docker on your own hardware, gets everything from your Plex server, and needs no outside accounts or cloud services.

If you find it useful, you can [buy me a coffee](https://buymeacoffee.com/egadgetboy).

## Contents

- [What you need](#what-you-need)
- [Install](#install): [TrueNAS SCALE](#truenas-scale) · [Docker Compose (Linux, Proxmox, Raspberry Pi)](#docker-compose-linux-proxmox-raspberry-pi) · [Synology](#synology) · [Unraid](#unraid) · [Windows and macOS](#windows-and-macos) · [docker run](#docker-run)
- [GPU encoding](#gpu-encoding) · [Updating](#updating) · [Backups](#backups) · [How StationPlay reads your files](#how-stationplay-reads-your-files) · [Security and remote access](#security-and-remote-access)
- [Watch your stations](#watch-your-stations): Plex, Jellyfin, Emby, Kodi and other apps · [Coming soon: StationPlay's own apps](#coming-soon-stationplays-own-apps)
- [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home): a VPN, a reverse proxy, or a Cloudflare Tunnel
- [First-time setup](#first-time-setup)
- [Making stations](#making-stations)
- [How stations play](#how-stations-play)
- [Station features](#station-features): logos, corner logo, Up Next Banner, Station ID card, commercials, Intro Bumper, subtitles, specials
- [Keeping stations on the air](#keeping-stations-on-the-air): safeguards, the Broken files list, file checks, Sonarr and Radarr
- [Who can use StationPlay](#who-can-use-stationplay): [Viewing Levels](#viewing-levels) · [Linked devices and Who's tuning in?](#linked-devices-and-whos-tuning-in)
- [Stats](#stats) · [StationPlay's API](#stationplays-api) · [Settings](#settings) · [Troubleshooting](#troubleshooting) · [Development](#development)
- [Contributing](#contributing) · [Forks and credit](#forks-and-credit) · [License](#license)

## What you need

- **Plex Media Server** with your shows and movies. To watch in Plex, you also need **Plex Pass**, because Plex's Live TV & DVR feature requires it. Jellyfin, Emby, Kodi and IPTV apps don't need Plex Pass.
- **A computer that runs Docker** on the same home network as Plex: a NAS (TrueNAS SCALE, Synology, Unraid), a Linux server or virtual machine, a Raspberry Pi 4 or 5 with a 64-bit OS, or a Windows or Mac computer with Docker Desktop. Both x86-64 (Intel/AMD) and ARM64 work.
- **Your media folder visible to that computer.** StationPlay reads files directly from disk. If it can't see a file, it streams it from Plex instead, which works but adds load to Plex.
- **Enough processing power.** Each station being watched converts video in real time. A modern 4-core CPU can usually run several 720p stations at once. A GPU (Intel Quick Sync, AMD or NVIDIA) handles many more, and 1080p easily. A Raspberry Pi or a Mac has no GPU StationPlay can use, so plan on one or two stations at smaller picture sizes. **Test this server** on StationPlay's page measures what your hardware can do (see [Tuners](#tuners)).

## Install

### How installation works

Each StationPlay release is a set of files, and Docker builds the StationPlay image on your own machine:

| File | What it's for |
|---|---|
| `stationplay-<version>.zip` | The app. It unzips to a folder called `src`. |
| `stationplay.yaml` | The app definition for TrueNAS SCALE. |
| `docker-compose.yml` | The app definition for Docker Compose, for everything else. |

Both app definitions are also inside the zip, in `src`, and the steps below use those copies. The first build takes a few minutes, mostly to install ffmpeg.

**Before you start, gather four things:**

1. **Your Plex server's address**, such as `http://192.168.1.10:32400`. Use the server's network IP address, not `localhost`: inside a container, `localhost` means the container itself.
2. **Your Plex token** (see the next section).
3. **Where your media lives** on the Docker host, such as `/mnt/tank/media`.
4. **The user StationPlay runs as**, written as `UID:GID` (numbers). It must be able to read your media and write StationPlay's data folder. The examples use `1000:1000`. To see who owns your media, run `ls -ln /path/to/media`: the third and fourth columns are the UID and GID.

#### Finding your Plex token

In Plex Web, open any movie or episode and choose **⋯ → Get Info → View XML**. The address of the page that opens ends with `X-Plex-Token=…`. That value is your token. Keep it private: it gives full access to your Plex server. StationPlay never shows it on its page or in its logs.

### TrueNAS SCALE

Requires TrueNAS SCALE 24.10 (Electric Eel) or later, which has **Install via YAML**.

**1. Copy the zip file onto the NAS,** anywhere you can reach it, such as a folder on an SMB share you already use.

**2. Make StationPlay's folder and unzip the release into it.** Choose a place on a pool, such as `/mnt/tank/apps/stationplay` (use your pool's name instead of `tank`). Paths in TrueNAS are case-sensitive: `StationPlay` and `stationplay` are different folders. Open **System → Shell** and run:

```
sudo mkdir -p /mnt/tank/apps/stationplay/data
cd /mnt/tank/apps/stationplay
sudo unzip -o /path/to/stationplay-<version>.zip
sudo chown -R 1000:1000 data
```

The `data` folder holds your stations and settings, so it must be owned by the user StationPlay runs as (`1000:1000` here; see step 3). The `src` folder can stay owned by root: TrueNAS only reads it to build the image.

**3. Install the app.** Go to **Apps → Discover Apps → ⋮ (top right) → Install via YAML**. Name the app `stationplay` and paste the contents of `stationplay.yaml`. Then change every line marked `<- CHANGE`:

- the three folder paths: the `src` folder, the `data` folder and your media folder;
- `PLEX_URL`, `PLEX_TOKEN` and `TZ` (your time zone, such as `America/Chicago`);
- `user:`, if your media belongs to another user. TrueNAS's built-in apps user is `568:568`; if you use it, also run `sudo chown -R 568:568 data`.

Also check the GPU lines (see [GPU encoding](#gpu-encoding)). The Intel/AMD lines are turned on in this file: if the server has no Intel or AMD graphics, delete them, or the app won't start.

Save. The first build takes a few minutes.

**4. Open** `http://<your-nas-ip>:3310` in a browser. The [first-time setup](#first-time-setup) starts.

### Docker Compose (Linux, Proxmox, Raspberry Pi)

This works on any Linux machine with Docker and the Compose plugin: Ubuntu, Debian, a Proxmox VM or LXC container, a Raspberry Pi with a 64-bit OS, and most NAS systems with a terminal.

```
mkdir -p ~/stationplay && cd ~/stationplay
unzip -o /path/to/stationplay-<version>.zip        # creates src/
cp src/docker-compose.yml .
mkdir -p data && sudo chown -R 1000:1000 data      # use your UID:GID
```

If `unzip` isn't installed, install it first (`sudo apt install unzip` on Debian, Ubuntu and Raspberry Pi OS).

Open `docker-compose.yml` in a text editor and change every line marked `<- CHANGE`: the user, Plex's address, your Plex token, your time zone and your media folder. For a GPU, uncomment its lines (see [GPU encoding](#gpu-encoding)). Then build and start it:

```
docker compose up -d --build
```

Open `http://<server-ip>:3310`. Your copy of `docker-compose.yml` sits beside `src`, so updates never overwrite it.

- **Proxmox:** run Docker in a VM or an LXC container, then follow these steps. To use an Intel or AMD GPU from an LXC container, pass `/dev/dri` through to it in Proxmox first. Your media must be mounted inside the VM or container.
- **Raspberry Pi:** use a 64-bit OS. The Pi's GPU can't be used for encoding, so StationPlay encodes on the CPU. Start with the 480p picture size.

### Synology

Requires DSM 7.2 or later with **Container Manager** (from Package Center).

1. In **Control Panel → Terminal & SNMP**, turn on SSH.
2. In **File Station**, create a folder such as `/volume1/docker/stationplay`. Upload the zip file there, then right-click it and choose **Extract → Extract Here**. You now have a `src` folder. Copy `src/docker-compose.yml` into `/volume1/docker/stationplay` and create a `data` folder beside it.
3. Connect over SSH and find your user's IDs with `id`. You'll see something like `uid=1026(you) gid=100(users)`. Use those numbers so StationPlay can read your media:

   ```
   cd /volume1/docker/stationplay
   sudo chown -R 1026:100 data
   ```

4. Edit `docker-compose.yml` (in File Station or with a text editor): set `user: "1026:100"` (your numbers), and change the other lines marked `<- CHANGE`. Your media folder is usually under `/volume1/`, such as `/volume1/video`.
5. Build and start it:

   ```
   sudo docker compose up -d --build
   ```

   On older systems, the command is `sudo docker-compose up -d --build`.

Intel-based Synology models with built-in graphics can use the GPU: uncomment the Intel/AMD lines (see [GPU encoding](#gpu-encoding)).

### Unraid

1. From the **Apps** tab, install the **Compose Manager** plugin. It adds the `docker compose` command.
2. Copy the zip file into a share, for example `/mnt/user/appdata/stationplay`, then open the terminal (the `>_` icon) and run:

   ```
   cd /mnt/user/appdata/stationplay
   unzip -o stationplay-<version>.zip
   cp src/docker-compose.yml .
   mkdir -p data && chown -R 99:100 data
   ```

3. Edit `docker-compose.yml`: set `user: "99:100"` (Unraid's standard `nobody:users`, which owns your shares), set your media path (such as `/mnt/user/media`), and change the other lines marked `<- CHANGE`.
4. Run `docker compose up -d --build` in that folder.

For an Intel GPU, the `/dev/dri` folder must exist on the server (Unraid loads the Intel driver for most Intel graphics). See [GPU encoding](#gpu-encoding).

### Windows and macOS

StationPlay runs in **Docker Desktop**. The computer must stay on and awake for your stations to play.

1. Install Docker Desktop and start it.
2. Unzip the release into a folder, such as `C:\StationPlay` or `~/StationPlay`. Copy `src/docker-compose.yml` into that folder, beside `src`, and create a `data` folder.
3. Edit `docker-compose.yml`:
   - Delete the `user:` line. Docker Desktop manages file permissions itself.
   - Set your media folder with forward slashes, such as `D:/Media:/media:ro` on Windows or `/Users/you/Movies:/media:ro` on a Mac.
   - Change the other lines marked `<- CHANGE`.
4. In a terminal (PowerShell on Windows), go to that folder and run `docker compose up -d --build`.

Allow port 3310 through the computer's firewall if it asks. Docker Desktop can't use Intel or AMD graphics. On Windows, an NVIDIA GPU works through WSL 2 (see [GPU encoding](#gpu-encoding)). A Mac always encodes on the CPU.

If Plex runs on Windows, StationPlay can't translate Windows file paths (such as `D:\TV\…`), so it streams files from Plex instead. That works, but adds load to Plex.

### docker run

If you don't use Compose, build the image and start the container yourself. Run these from the folder you unzipped StationPlay into:

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

- Intel or AMD GPU: add `--device /dev/dri:/dev/dri --group-add <group number>` (see [GPU encoding](#gpu-encoding)).
- NVIDIA GPU: add `--gpus all` (needs the NVIDIA Container Toolkit).
- Page reachable from the internet: add `-p 3311:3311 -e PUBLIC_PORT=3311` (see [Security and remote access](#security-and-remote-access)).

Keep `--restart unless-stopped`: restoring a backup restarts StationPlay, and Docker must start it again.

### GPU encoding

A GPU makes StationPlay much lighter on your server and lets more stations play at once, at 1080p too. StationPlay supports Intel and AMD graphics through VA-API (including the Quick Sync graphics built into most Intel Core CPUs) and NVIDIA graphics through NVENC. When the GPU supports a file's format, it decodes the file too. Copies converted for StationPlay's apps (see [Coming soon: StationPlay's own apps](#coming-soon-stationplays-own-apps)) are made on the GPU as well.

At startup, StationPlay test-encodes a short clip with the exact command it uses for real programs. It uses the first GPU that passes (NVIDIA first, then each Intel/AMD device). If none passes, it encodes on the CPU. The **Video encoding** line on the **Add to Plex** tab shows which is in use, and why when it's the CPU.

**Intel or AMD.** The container needs the `/dev/dri` folder and permission to use it:

```
devices:
  - /dev/dri:/dev/dri
group_add:
  - "107"     # the group that owns /dev/dri/renderD128
```

To find the group number, run `ls -ln /dev/dri` on the host and look at the group of `renderD128` (or run `getent group render`). It's usually `107` on TrueNAS. If the number is wrong, the **Video encoding** line names the right one. The TrueNAS YAML has these lines turned on; in `docker-compose.yml` they're commented out. Remove them if the server has no `/dev/dri`, or the container won't start.

**NVIDIA.** On TrueNAS, turn on **Apps → Configure → Settings → Install NVIDIA Drivers**. Elsewhere, install the NVIDIA driver and the NVIDIA Container Toolkit (on Windows, Docker Desktop's WSL 2 backend provides GPU access). Then uncomment the `deploy:` block in the YAML or `docker-compose.yml`, or add `--gpus all` to `docker run`.

**Built-in safeguards:**

- If a program fails on the GPU, the same program carries on from the same point on the CPU. The file isn't marked as broken unless it also fails on the CPU.
- A copy for StationPlay's apps works the same way: if it fails on the GPU, it carries on from the same point on the CPU and stays there, and the viewer sees nothing more than the usual wait.
- If 3 programs in a row fail on the GPU but play on the CPU, StationPlay stops using the GPU until it restarts. Copies count separately: if 3 in a row fail on the GPU but are made fine on the CPU, only copies move to the CPU, and stations keep the GPU.
- A program that stalls on the GPU also moves to the CPU, but a stall never counts against the GPU (a slow disk causes stalls too).
- The "We'll be right back" card is always made on the CPU, so it works even if the GPU doesn't.

`HW_ACCEL` chooses the encoder: `auto` (default), `nvidia`, `intel` or `amd` (both mean VA-API), or `cpu`. With more than one GPU, `HW_DEVICE` picks one: a render node such as `/dev/dri/renderD129`, or an NVIDIA GPU number.

### Updating

Your stations, settings, logos, Intro Bumper videos and Broken files list live in the `data` folder, so updates keep them. Existing stations keep their settings; new defaults only apply to stations you make afterward. The version you're running is shown at the bottom of StationPlay's page.

**Always unzip the new version over `src` first,** then rebuild:

| Install | After unzipping the new version over `src` |
|---|---|
| TrueNAS SCALE | Edit the app, change the version in `image: stationplay:<version>` to the new one, and save. Change nothing else, so your Plex token and paths stay as they are. |
| Docker Compose, Synology, Unraid, Docker Desktop | Change the version in `image:` in your `docker-compose.yml`, then run `docker compose up -d --build`. |
| docker run | Run `docker build -t stationplay:<new version> ./src`, then `docker rm -f stationplay`, then the same `docker run` command as before with the new version. |

Unzip the new version the same way you did when you installed, into the same folder, replacing the files in `src` (on TrueNAS: `sudo unzip -o /path/to/stationplay-<version>.zip`). Your edited YAML or `docker-compose.yml` isn't in `src`, so it's never overwritten.

On TrueNAS, the order matters. A new version number is what makes TrueNAS rebuild, and it builds from whatever is in `src` at that moment. If you save before unzipping, it builds the old code under the new number (see [Troubleshooting](#troubleshooting)).

**Going back to an older version?** Older versions don't know newer settings and may play some programs wrongly. Before downgrading below 1.8, delete stations made from Plex collections, set **In the corner** to something other than **Clock**, and set each **Station ID card** to **Off** or **10 sec**. Below 1.6, also set **Commercials & trailers** to **None** and the **Station ID card** to **Off**. Below 1.4, also set **Intros & credits** to **Play them**. Wait for each change to take effect (at the next program break) before downgrading.

### Backups

StationPlay backs itself up automatically: about 15 minutes after it first starts, and then every night at about 3 AM (in your `TZ` time zone). It keeps the newest 7 backups in `data/backups`.

A backup includes your stations and their schedules, all settings, the Broken files list, the tuner's identity (so Plex still recognizes it), your logos (uploaded or from Plex), users and their passwords (stored as hashes only), and viewing stats. Intro Bumper videos aren't included, to keep backups small; they stay in `data/bumpers`, and a restore leaves them alone.

On the **Add to Plex** tab:

- **Download a backup** makes one now and downloads it. It's also saved in `data/backups` and counts toward the 7 kept.
- **Restore a backup…** replaces everything above with the backup's copy. StationPlay checks the file, restarts, and puts it in place as it starts. It saves what you had first, as a separate "before restore" backup, in case you change your mind.

After a restore, everyone signs in again as the users in the backup. A backup with no users turns sign-in off, so StationPlay asks before restoring one while sign-in is on.

### How StationPlay reads your files

StationPlay asks Plex where each file is, then reads it straight from disk. Plex reports paths as its own container sees them, such as `/data/tv/Show/episode.mkv`. You don't need to match those paths: mount your media at `/media` (as the YAML and Compose files do), and StationPlay finds each file by matching the end of Plex's path inside `/media`. It needs at least the file name and the folder it's in to match. Once a match works, it's reused for everything else. The **Media files** line on the **Add to Plex** tab shows whether files are read directly.

If StationPlay can't see a file, it streams it from Plex instead. That works, but it adds load to Plex. For unusual layouts, set the translation yourself with `PATH_MAPPINGS`, under `environment:`. For example, `PATH_MAPPINGS: "/data/media:/media"` means "where Plex says `/data/media/…`, read `/media/…`". (If Plex runs in Docker, its paths are the ones inside Plex's container.) Separate several pairs with `;`.

If your media share takes more than 8 seconds to answer, StationPlay treats it as temporarily unavailable: it skips those programs for now, without marking them broken.

### Security and remote access

**Keep port 3310 on your home network.** It serves Plex's tuner, guide and video streams, which never ask for a password (Plex can't sign in to a tuner). Never forward it on your router or point a tunnel or reverse proxy at it. Plex only needs it inside your network, and Plex users away from home still work, because Plex relays the stream.

**Using StationPlay's page from the internet.** StationPlay can open a second port only for its web page, set with `PUBLIC_PORT` (3311 in the YAML and Compose files; it must be different from `PORT`). On that port:

- The addresses Plex and other apps use (the tuner, guides, streams and playlist) don't exist.
- Signing in is always required. Before it, there's only the sign-in page, with its icons and what a browser needs to install the page as an app (see **As an app** under [First-time setup](#first-time-setup)). Until StationPlay has its first user, it shows only a message to add one from your home network, so no one can make themselves the first Admin from outside.
- Wrong passwords are limited per visitor address (5 in 15 minutes) and for the internet as a whole (100 in 15 minutes). A browser that has signed in before isn't held up by the internet-wide limit.

`PUBLIC_PORT` sits behind something that reaches it from the internet: a Cloudflare Tunnel, or a reverse proxy with HTTPS. [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home) explains each, and the other ways in. If you don't need it, remove the `3311` port line and `PUBLIC_PORT`.

**Built-in protections, however StationPlay is reached:**

- **Plex:** the page can't send its own requests to Plex. StationPlay makes only the requests it needs (library details, guide refreshes, folder scans and stopping blocked playback), so your Plex token can't be misused through it. The page never sees the token or Plex's address.
- **Uploads:** a logo is read only as a PNG, JPEG, WebP, GIF or BMP image, and an Intro Bumper only as a video file. Each is turned into a clean copy before use. Limits: 500 of your own logos, 50 Intro Bumper videos, and no upload that would leave less than 2 GB free on the data folder's disk.
- **The page:** it runs only its own scripts, can't be embedded in another site, and refuses changes sent from other sites.
- **Backups:** a backup is restored only if it's a genuine StationPlay backup; anything unexpected is refused before anything changes.

## Watch your stations

StationPlay offers your stations two ways at the same time, on your home network:

| For | Address |
|---|---|
| Plex (as an HDHomeRun tuner) | Tuner: `http://<server-ip>:3310`<br>Guide: `http://<server-ip>:3310/xmltv.xml` |
| Jellyfin, Emby, Kodi and IPTV apps | Playlist: `http://<server-ip>:3310/stations.m3u`<br>Guide: `http://<server-ip>:3310/guide.xml` |

The **Add to Plex** tab shows these addresses with **Copy** buttons. Station numbers and logos come with them. You can watch in as many apps as you like: everyone watching the same station shares one stream.

### In Plex

1. In Plex, open **Settings → Live TV & DVR → Set Up Plex DVR**.
2. Choose **Don't see your HDHomeRun device? Enter its network address manually** and enter the tuner address, `http://<server-ip>:3310`. (Plex doesn't find StationPlay on its own.)
3. When Plex asks for guide data, choose **Have an XMLTV guide on your server? Click here to use it** and enter `http://<server-ip>:3310/xmltv.xml`.
4. Continue. Plex matches your stations automatically (it calls them channels), and they appear under **Live TV**.

After that, StationPlay keeps Plex's guide up to date: whenever a station changes, it asks Plex to refresh the guide. The **Guide updates** line on the **Add to Plex** tab shows whether that's working. If it isn't, refresh the guide yourself in **Settings → Live TV & DVR → your tuner → Refresh Guide**.

**After you create a new station,** choose **Scan for channels** in Plex's Live TV & DVR settings so Plex adds it.

**Plex Home and managed users:** to see your stations, a user's Live TV & DVR access must be **Allow Live TV and DVR access**. With "Allow Live TV only", Plex doesn't show them channels from a tuner.

### In Jellyfin

1. In the dashboard, open **Live TV** and choose **+** next to **Tuner Devices**.
2. Choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`. Save.
3. Choose **+** next to **TV Guide Data Providers**, choose **XMLTV**, and enter `http://<server-ip>:3310/guide.xml`. Save.

Leave Jellyfin's limit on simultaneous streams at its default (no limit): StationPlay enforces its own.

### In Emby

Emby's Live TV requires Emby Premiere.

1. In Emby's settings, open **Live TV** and add a TV source: choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`.
2. Add a guide data provider: choose **XMLTV** and enter `http://<server-ip>:3310/guide.xml`.

### In Kodi

1. Install the **PVR IPTV Simple Client** add-on (**Add-ons → Install from repository → PVR clients**).
2. In its settings, set the playlist location to remote and **M3U play list URL** to `http://<server-ip>:3310/stations.m3u`. The playlist names the guide, so the **XMLTV URL** can stay empty (or enter `http://<server-ip>:3310/guide.xml`).
3. Restart Kodi (or turn the add-on off and on). Your stations appear under **TV**.

### In other apps

Channels DVR, TiviMate, VLC and most IPTV apps accept the playlist address, `http://<server-ip>:3310/stations.m3u`. The playlist tells apps where the guide is.

**HLS players.** Each station is also available as HLS, the format Safari, iPhones, iPads, Apple TV and many other players use: `http://<server-ip>:3310/hls/<station number>/index.m3u8`. It shares the station's one stream with everyone else watching it, so a station never takes a second tuner. It runs only while a player is asking for it, and stops 30 seconds after the last one does (at once, when StationPlay's own apps tune away).

**Keeping other apps' guides current.** These apps download the guide on their own schedule, usually once a day. When you change a station, refresh the guide in the app (in Jellyfin: **Dashboard → Scheduled Tasks → Refresh Guide**), or it shows that station's old schedule until its next refresh. Updates from Plex (such as new episodes) take effect when Plex downloads its guide, so an app that refreshes less often may briefly show an older schedule.

**Away from home.** These addresses only work on your home network. Plex users away from home watch through Plex as usual. Other apps must be on your network, or reach it over a VPN.

### Coming soon: StationPlay's own apps

StationPlay's own apps are in development. They connect directly to your StationPlay server, so you can watch your stations without Plex Pass or any other app.

- **Platforms.** iPhone, iPad and Apple TV; Android phones and tablets, Google TV, Android TV and Fire TV; and Roku.
- **A guide made for every screen.** On a TV, you browse it with your remote. On a phone, you see every station at a glance and swipe through the hours. On a tablet, the selected program and a live picture sit above the guide.
- **Changing stations.** While a station tunes in, you see its card in the same colors as its Intro Bumper. Flip up and down through your stations, enter a station number on your remote, or jump back to the last station you watched. If every tuner is in use, the app says so and lets you join a station that's already playing.
- **Favorites.** Mark the stations you watch most, and choose to show only those in the guide.
- **Night mode.** It softens loud scenes and makes quiet dialogue easier to hear, so you can watch late without disturbing anyone. Where a device can't change the sound itself (Apple's player, a Roku), StationPlay makes the station's night-mode sound on the server, only while someone's watching it that way: the picture is copied as it is, it uses the station's one tuner, and everyone else keeps the usual sound.
- **Sleep timer.** Choose 15 minutes to 2 hours, a time, or minutes of your own, from anything playing. In its last 30 seconds the picture fades to black; then playing stops and the screen stays dark, so the TV or device can go to sleep, until you press a button.
- **Phone and tablet extras.** Keep watching in picture-in-picture, choose whether the picture fits or fills the screen, and send it to your TV with AirPlay (Apple) or Cast (Android).
- **Secure sign-in.** On a TV, the app shows a short code that you enter on StationPlay's page from your phone or computer, so you never type a password with a remote. On a phone or tablet, you can use your name and password instead. Every signed-in app appears under **Signed-in apps** on the **Access** tab, where an Admin can sign it out.
- **Watching away from home.** When an Admin turns this on, the apps also work away from home, stations and your library alike, over HTTPS through the same reverse proxy that serves StationPlay's page (see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)).
- **Built for stability.** An Admin sets how many devices can watch at once, including how many away from home. StationPlay tests what your server and internet connection can handle and recommends limits. When a limit is reached, the app explains why and asks the viewer to try again later.
- **Your library on demand.** Browse your shows and movies by title, genre, what's new or what you haven't watched, jump to a letter, search them, and pick up where you left off from the Resume row. Each title's page has its cast and crew and others like it. Skip an episode's intro and credits at the press of a button, and choose subtitles and audio tracks. Each device gets the best picture and sound it supports, including Dolby Vision and Dolby Atmos, and a file is repackaged or converted only when a device can't play it as it is.

The server side is ready: StationPlay 1.19.0 and later include what the apps use. They read the stations and guide through [StationPlay's API](#stationplays-api), like any other client, and sign in, test connections and browse your library through addresses of their own, documented for the apps in [docs/internal-api.md](docs/internal-api.md).

**Sharing your library with the apps.** Your library stays out of the apps until an Admin chooses which libraries to share, on the **Access** tab under **Media in StationPlay's apps**. Stations, Plex, Jellyfin and other apps don't change either way. Each person who signs in has their own Resume row, resume points and watched list (while sign-in is off, everyone shares one). Programs played this way count toward the limit on devices watching at once. A title with several versions (4K and 1080p, say) is listed once, and each device plays the best version it can. If playing can't keep up for a while, even with the buffer, the app tests the connection to find out why, then offers a smaller version from where you are (or switches to it on its own, as you choose on the Access tab). A file plays as it is whenever the device can play it. If it can't, StationPlay makes a copy as it plays, which the app can seek anywhere in: repackaged, with the picture kept as it is and only the sound converted (this costs next to nothing), or converted, with the picture made again at up to 1080p in standard color (this takes a share of the server's processor, so at most 3 are converted at once, or 6 with a GPU, which converts them as it does stations and is light on the processor). A copy also draws in subtitles the device can't show itself, and makes a smaller picture when the connection can't keep up with any version. Your library plays on your home network or through a VPN, and while **StationPlay's apps away from home** is on, through the public port too (see **Media away from home**, below). The design is in [docs/on-demand.md](docs/on-demand.md).

**Media away from home.** With **StationPlay's apps away from home** turned on, your library plays away from home just as it does at home, for everyone signed in, within their Viewing Level and the limits on devices watching (a device away from home counts against the limit away from home too). Under **StationPlay's apps away from home** on the Access tab, **Media away from home** sets how fast it plays there: **Original** (the default) plays each title as it would at home; **Up to** a number of Mbps (1 to 200) plays a title within it as it would at home, and converts one whose file needs more down to fit, at most 1080p (it counts toward the copies converted at once, as at home). The panel shows your home's upload as StationPlay's apps measured it from outside, as a guide. When a connection can't keep up, the apps still step down on their own. The player needs no sign-in: each title an app plays through the public port has an address of its own, random and far too long to guess, which works there only for a title started there, only over HTTPS, and only while that app's sign-in lasts. A title started at home is never offered there.

**Even sound for a show's episodes.** Every episode played from your library in StationPlay's apps comes at the same loudness as the episodes on your stations (−24 LUFS), so a show's episodes match, played in order or shuffled, in any app, and none is much louder or quieter than the next. Movies are never changed. The picture plays as it is, and only the sound is made again (repackaged, which costs next to nothing), as night mode's sound is for an app that can't make it; with night mode too, the even sound comes first. Where the picture can't be kept as it is, the episode plays as it is, rather than have its picture made again. It's on to start: turn off **Even sound for a show's episodes** on the Access tab, under **Media in StationPlay's apps**, to play each episode's sound as it is, such as Dolby Atmos or DTS sent on to a receiver (with it on, that sound comes as ordinary 5.1 or stereo). Apps older than StationPlay 1.24.0's copies get each file as it is.

**Languages.** Each person chooses their own sound language and captions (on or off, and in which language) in an app's Options, and StationPlay keeps them, so they follow that person to every device. From the player, they can choose otherwise for a whole show, or for one episode or movie. When a title plays, StationPlay picks its sound and subtitles from that (the episode's or movie's choice, then the show's, then their own, then the file's default): the sound in their language (never a commentary when there's another), captions in theirs (a full track before a forced one), and with captions off, only forced subtitles, for the parts in another language. Subtitles the device can't show itself are drawn into a copy, as above; an episode whose chosen subtitles are inside its file, and shown by the device itself, plays as it is rather than with even sound, as a copy carries no subtitles. Someone who hasn't chosen anything gets each file as before. Stations don't use them.

## Reaching StationPlay from outside your home

**Often you don't need to.** Plex users away from home watch your stations through Plex as usual: Plex relays the stream. The same goes for Jellyfin and Emby, which reach StationPlay from your home network. What needs a way in from outside is StationPlay's own page, and StationPlay's apps.

**Never open port 3310 to the internet.** It serves Plex's tuner and streams, which never ask for a password. Every way below keeps it closed.

| Way in | Good for | Open to the internet | Setup | Cost |
|---|---|---|---|---|
| [A VPN: Tailscale](#tailscale) | The page and the apps, on your own phones, tablets and computers | Nothing | Easiest: an app on the server and on each device | Free for personal use |
| [A VPN: WireGuard on your router](#wireguard-on-your-router) | The same | One port, for the VPN | Moderate, if your router has it built in | Free |
| [A reverse proxy with HTTPS](#a-reverse-proxy-with-https) | The apps anywhere, for anyone you've added, with no VPN on their devices; and the page | Port 443, to the proxy, which reaches only StationPlay's public port | More: a domain name, a port forward and the proxy | A domain name, about $10 to $15 a year |
| [A Cloudflare Tunnel](#a-cloudflare-tunnel-the-page-only) | The page only, not the apps | Nothing | Moderate | Free |

A VPN is the most private: nothing at all is open to the internet, and to StationPlay a phone on the VPN is on your home network. A reverse proxy suits apps used by people who won't install a VPN, such as family elsewhere. A Roku can't run a VPN, so a Roku outside your home needs the reverse proxy.

**For StationPlay's apps**, turn on **StationPlay's apps away from home** on the **Access** tab (it's off until you do), with the address the apps use from outside: your VPN address with its port (such as `http://nas.your-tailnet.ts.net:3310`), or your reverse proxy's `https://` address alone, with no port. Apps set up at home remember it, and switch to it when home doesn't answer. Each station watched away from home is sent over your home connection's upload, at its picture size: about 1.7 Mbps at 480p, 3.7 Mbps at 720p and 6.2 Mbps at 1080p. So is your library, if you share it with the apps, at the quality you choose under **Media away from home** (Original, or up to a number of Mbps).

**StationPlay checks that the apps can reach it.** While that's on, StationPlay asks for itself at the address, as an app away from home would: a few seconds after it starts, at once when you save the address, every 5 minutes, and when you choose **Check now**. Only the check it's waiting for gets an answer, so StationPlay knows it reached itself, not just something, and how: through which port, and over HTTPS or not. It says **Ready** when an `https://` address reaches the public port over HTTPS (or a VPN address reaches StationPlay), which covers your library too while you share it (it plays through the same address, the same way), and otherwise what's wrong, in a sentence: a proxy that points at port 3310, an address without HTTPS, a name that isn't found, a certificate that has expired or isn't trusted, the proxy's own error, something else answering, or a redirect. The status sits under the address on the Access tab and in the setup, and for Admins, **Away from home** in the page's header says **Up**, **Down**, **Checking** or **Can't check** on every tab (choose it to open the Access tab's panel). One problem alone never makes it **Down**: StationPlay checks again a minute later. The log says when it goes down, and why, and when it's back.

**When your router answers from home.** Many routers don't let devices at home use the home's own internet address (this is called NAT loopback, or hairpinning). From inside your home, the address then reaches the router itself, which answers with its own sign-in page, certificate or redirect, or not at all, while apps away from home work fine. So StationPlay counts what could be the router (nothing answering, a certificate for another name or one that isn't trusted, something else answering, or a redirect) only once a check from home has worked since it started. A proxy error, a name that isn't found, an expired certificate, or StationPlay's own answer saying what's wrong always counts. When a signed-in app has come in through the public port in the last 15 minutes, it's **Up**, and the panel says when an app last came in from outside. Otherwise it says **Can't check**, and why: to be sure, open your address on a phone using mobile data, not Wi-Fi. **The fix:** a DNS host override in your router (such as OPNsense's or pfSense's Unbound host overrides) that points your address's name at the reverse proxy's address on your home network. Devices at home, StationPlay included, then reach the proxy directly.

### Tailscale

1. Install Tailscale on the server: on **TrueNAS SCALE**, **Apps → Discover Apps → Tailscale**; on **Unraid**, the Tailscale plugin; on **Synology**, **Package Center → Tailscale**; elsewhere, Tailscale's own installer or Docker image. Sign in, and turn on **MagicDNS** in Tailscale's admin console.
2. Install Tailscale on each phone, tablet, computer, Apple TV or Android TV that should reach StationPlay, signed in to the same account (or shared with it).
3. Use the server's Tailscale name with port 3310, such as `http://nas.your-tailnet.ts.net:3310`: for the page in a browser, and as the outside address on the Access tab for the apps.

Tailscale connects your devices directly and encrypts everything, so nothing on your router changes.

### WireGuard on your router

Many routers and firewalls have a WireGuard VPN server built in (Firewalla, UniFi, OPNsense, pfSense, GL.iNet and others). Turn it on, add each phone or tablet in the WireGuard app, and while it's connected, use StationPlay's home address (such as `http://192.168.1.20:3310`) as if you were home. The apps need no outside address for this: their home address works over the VPN.

### A reverse proxy with HTTPS

The proxy (Caddy or Nginx Proxy Manager, say) takes HTTPS connections from the internet and passes them to StationPlay's **public port** (3311), never 3310. You need:

1. **A domain name** pointing at your home's internet address (with dynamic DNS if that address changes), such as `tv.example.com`.
2. **Port 443 forwarded** on your router to the computer running the proxy.
3. **The proxy**, with a certificate (both proxies below get a free one from Let's Encrypt), passing requests to `http://<your-server-ip>:3311`, and passing on each visitor's address in `X-Real-IP` or `X-Forwarded-For`. Nginx Proxy Manager and NPMplus do both by default. StationPlay counts wrong passwords by that address and shows it in the access log, so the proxy must set it itself, replacing any value a visitor sends. (StationPlay takes `CF-Connecting-IP` only when a request came through Cloudflare, so a visitor can't send it to pose as someone else.)

**Caddy** (the whole `Caddyfile`):

```
tv.example.com {
    reverse_proxy 192.168.1.20:3311 {
        header_up X-Real-IP {remote_host}
    }
}
```

**Nginx Proxy Manager** (or NPMplus): add a proxy host for `tv.example.com` forwarding to `192.168.1.20` port `3311`. On its **SSL** tab, request a Let's Encrypt certificate and turn on **Force SSL**. It passes on each visitor's address by itself.

Then, on the **Access** tab at home, add the first user (an Admin) with a long password if you haven't, and turn on **StationPlay's apps away from home** with `https://tv.example.com`. Leave the port out: that's the proxy's address, and StationPlay itself never speaks HTTPS. Within a few seconds, the status under it should say **Ready**. If it says the proxy points at the wrong port, point it at 3311, never 3310.

What protects StationPlay there:

- **Signing in is required** for everything but the sign-in page; until there's a user, nothing else is shown at all.
- **Apps connect only over HTTPS.** Anything an app asks for that didn't come over HTTPS (as the proxy says) is refused, so no password, sign-in or stream address crosses the internet in the clear.
- **Wrong passwords are limited:** 5 in 15 minutes from one address, and 100 in 15 minutes from the internet as a whole. A browser or app that has signed in before isn't held up by the second limit.
- **Each signed-in app has a private address for its stations**, and one for each title it plays from your library, which stop working as soon as its sign-in ends: signing out, a new password, the person being removed, or an Admin signing that app out under **Signed-in apps** on the Access tab. A title's address works there only for a title the app started through the public port; one started at home is never offered there.
- **API tokens are refused there** unless an Admin turns on **Accept API tokens from the internet**, and even then work only with [StationPlay's API](#stationplays-api).
- **Plex's tuner, guides and streams don't exist there**, signed in or not.

### A Cloudflare Tunnel (the page only)

A Cloudflare Tunnel reaches StationPlay's page without opening any port. It's not for the apps: Cloudflare's free plan isn't meant for video, and an app can't enter Cloudflare Access's email codes.

1. On the **Access** tab, at home, add the first user (an Admin) with a long password.
2. Keep `PUBLIC_PORT: "3311"` and the `"3311:3311"` port line.
3. In Cloudflare **Zero Trust**, add a public hostname to your tunnel (such as `tv.example.com`) with the service `http://<your-server-ip>:3311`. Never use 3310. Cloudflare passes on each visitor's address in `CF-Connecting-IP` itself.
4. **Strongly recommended:** in Zero Trust **Access**, add that hostname as a self-hosted application with a policy that allows only your people's email addresses. Cloudflare then asks for a one-time email code before anyone reaches StationPlay, so its sign-in is a second lock rather than the only one. This is free for up to 50 people.

## First-time setup

The first time an Admin opens StationPlay's page, the setup asks a few questions and checks that everything is working. Use **Next** and **Back**, or the steps down the side. Each answer is saved when you go on to another step. **Skip setup** keeps everything else as it is.

1. **Checking your server:** whether StationPlay can reach Plex (and whether the account that owns your Plex server has Plex Pass, which watching in Plex needs), whether it can read your media files from disk, how it encodes video, whether its clock matches your browser's, and its backups. Anything marked **Needs a look** or **Not working** says what to do. After changing StationPlay's app settings, restart it, then choose **Check again**.
2. **How stations play:** the picture size for new stations and the number of tuners, with **Test this server** to help you choose.
3. **New station settings:** what each new station starts with: subtitles, commercials and trailers, the Station ID card, the Intro Bumper, the Up Next Banner, and what goes in the corner. Stations you already have aren't changed.
4. **Who can use StationPlay:** **Anyone on my network**, or **Only people who sign in** (you become the first Admin right away; see [Who can use StationPlay](#who-can-use-stationplay)).
5. **Who sees what:** each person's Viewing Level (see [Viewing Levels](#viewing-levels)).
6. **Watching away from home:** whether StationPlay's own apps can watch your stations away from home, and the address they use then (see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)).
7. **Media in StationPlay's apps:** which libraries the apps can browse and play on demand (see [Coming soon: StationPlay's own apps](#coming-soon-stationplays-own-apps)).
8. **Checking files:** when the overnight deep scan runs.
9. **Adding StationPlay to Plex:** the steps in Plex, the addresses to enter there, and whether Plex has StationPlay yet.
10. **All set:** what's set now, and anything that still needs a look.

**Run setup again** on the **Add to Plex** tab, or **Setup** at the foot of the page, opens it any time, with your current answers filled in. It's the only place to change the settings for new stations; everything else can be changed on its tab too.

**After an update.** When a new version brings a question that needs an Admin's answer, such as a new feature to turn on or a new choice, the setup opens once by itself with just those questions (and the checks, if something needs a look). Everything else stays as you set it.

**Light or dark.** StationPlay's page follows your device's light or dark setting. To keep it light or dark in one browser, choose **Light** or **Dark** under **Appearance** at the foot of the page; **Automatic** follows the device again. The choice is kept in that browser only, so each person and device can have their own.

**As an app.** StationPlay's page fits a phone, a tablet and a computer, in either orientation. You can also add it to a phone's or tablet's home screen, or install it on a computer, and it opens in a window of its own, like an app: in Safari on an iPhone or iPad, **Share → Add to Home Screen**; on Android, **Add to Home screen** in Chrome's menu; on a computer, **Install** in Chrome's or Edge's address bar, or **File → Add to Dock** in Safari on a Mac. Install it from the address you sign in at, such as your reverse proxy's `https://` address (Chrome and Edge install only from an `https://` address). Nothing is kept on the device: the app always shows StationPlay's page as it is now, so it needs StationPlay to be reachable.

## Making stations

Choose **New station** on the **Stations** tab.

**The basics.** Give the station a **Number** and a **Name** (a station with no name is called "Station 12", after its number), and choose a **Logo** (see [Logos](#logos)).

**What's on it.** Under **What's on this station**, choose one of:

- **Pick shows & movies:** select titles from your Plex libraries, with posters and genres. The **Filter** box searches titles, genres and years (every word must match one of them, so "western 1959" finds Westerns from 1959). The three buttons next to it change the poster size. A title already on another station says so ("Already on station 12"). Below the list, StationPlay adds up how many shows, movies and episodes you picked, and about how many hours that is. To add a whole library, choose **Everything in** that library. The list shows up to 3,000 titles per library; type in the filter to find the rest.
- **Use a filter:** describe what you want, and Plex keeps the station up to date as your library changes. See [Filters](#filters).

**Settings.** The rest of the editor is grouped into **How it plays**, **Specials**, **Between programs**, **On screen** and **When someone tunes in**. Each group shows a summary when it's closed. Closing the editor with unsaved changes asks first.

**What a new station starts with** (unless you chose otherwise in [First-time setup](#first-time-setup)): **Shuffle**, black bars on 4:3 shows, intros and credits played, no commercials or trailers, no Station ID card, a 10-second Intro Bumper with sound, the station's logo large in the bottom-left corner during programs, a large Up Next Banner for 10 seconds, no subtitles and no specials.

### Filters

Instead of picking titles, a station can ask Plex which titles match, and follow the answer as your library changes. Choose **Use a filter**, then combine any of these. Each condition narrows the results; several values in one condition mean "any of these".

- **Libraries:** one or more. A movie in two libraries plays once.
- **Anything Plex can filter that library on:** genre, content rating, network, studio, country, collection (including smart collections), label, director, writer, actor and more. People are searched as you type.
- **Decade** (TV shows count by the year they started) and **Title contains**.
- **Added in the last N days:** new arrivals. For TV, the episodes added in that time, so a "New This Week" station refreshes itself.
- **Minimum audience rating:** Plex's audience rating, out of 10. Titles without a rating are left out.

A count of matches, with examples, updates as you go. **Choose which…** lists every match, so you can uncheck any you don't want; they stay out, while new matches still join.

Examples: Action movies (Genre: Action). Spielberg movies (Director: Steven Spielberg). Classic TV (TV shows, Decade: 1950s and 1960s). Kids' TV (Content Rating: TV-Y, TV-G). Christmas movies: Plex has no Christmas genre, so select your Christmas movies in Plex, choose **Edit**, add the label "Christmas", and filter on **Label: Christmas**.

### Stations from Plex collections

On the **Stations** tab, **From Plex collections** lists the collections in your TV and movie libraries (including smart collections). Check the ones you want and choose **Make station** (or **Make N stations**). Each becomes its own station, named after its collection, with the next free number and the default settings. A collection of shows plays every episode of them. Up to 200 can be made at once; a collection that's already a station shows as checked.

Each station follows its collection: titles added to or removed from the collection in Plex join or leave the station within about an hour. If a tool recreates the collection, the station finds it again by name.

### Smart stations

**Smart stations** on the **Stations** tab makes stations from a filter (see [Filters](#filters)). Then choose:

- **One station** of everything that matches, or
- **One for each** decade, genre, studio, actor or anything else Plex offers. StationPlay asks Plex how much each would have ("1960s Comedy · 88 movies") and lists up to 40 of them. Check the ones you want and rename them if you like. For directors, actors, writers and producers, pick the names yourself when Plex can't list who's in what.

Examples: ten comedy stations, one per decade, is **Genre: Comedy** with **One for each → Decade**. Action and comedy shows together on one station is **TV shows**, **Genre: Action, Comedy**, **One station**.

Each new station takes the next free number, gets a logo and the default settings, and is an ordinary station afterward. Up to 50 are made at once. Everything comes from your Plex server.

### Big stations

A station can be as big as you like. A shuffled station with tens of thousands of episodes takes several seconds to build, and other stations keep playing meanwhile.

### The station card

Each station's card on the **Stations** tab shows what's on now, its description, who made it and when, and labels for anything that needs you (such as **2 broken**, **Update ready**, or an update that needs your review). **Details** opens a summary of every setting. While it's closed, a red triangle means the station itself has a problem: it can't start, it's off the air, or it has nothing to play.

Card buttons:

- **Guide:** what's on now and over the next 2 days.
- **Edit:** open the editor.
- **Duplicate:** a copy with the same shows and settings and the next free number, to change before saving.
- **Check files:** quick-check every program on the station now (see [File checks](#file-checks)).
- **Update now:** apply changes from Plex at the next program break at least a minute away.
- **Reshuffle** (shuffled stations only): start a new random order, the same way.
- **Delete:** removes the station, with **Undo** for 10 seconds.

## How stations play

### One picture format per station

Each station is one continuous stream, like a TV channel. Everything on it (programs, commercials, cards) is converted as it plays to the station's format: H.264 video at the station's picture size, 29.97 frames per second, in standard color (SDR), with stereo sound. That's why a 4K movie, a 1960s DVD rip and a commercial can follow one another without a glitch, in any app.

Choose each station's **Picture** under **How it plays**. New stations use the size set on the **Add to Plex** tab.

| Picture | Size | Video data per viewer | Work for the server |
|---|---|---|---|
| **480p** | 854×480 | 1.5 Mbps | About half of 720p. For slower servers or many stations. |
| **720p** (standard) | 1280×720 | 3.5 Mbps | Sharp on most TVs, and light enough for most servers. |
| **1080p** | 1920×1080 | 6 Mbps | About twice 720p. A GPU helps a lot. |

Sound adds 192 kbps. A new picture size takes effect the next time the station starts (after everyone has stopped watching it).

**4K and HDR.** Stations play at up to 1080p in standard color, on purpose. Streaming 4K HDR would need a GPU fast enough to convert everything in real time and about 20 Mbps per viewer, and Plex Live TV isn't known to pass HDR from a tuner through to the TV. So 4K programs are scaled down to the station's size, and HDR programs (HDR10, HDR10+, HLG, and most Dolby Vision) are converted to standard color the way a TV would, so they don't look washed out.

**Dolby Vision profile 5** files (common from streaming services) contain no standard picture that anything other than a Dolby Vision player can show correctly, so StationPlay doesn't play them. They're listed on the **Broken files** tab as **Unsupported**. Replace the file with another version and it goes back on the air.

### Tuners

StationPlay's **tuners** are how many different stations it can play at once. Set the number from 1 to 20 on the **Add to Plex** tab. Plex doesn't limit this to 4 or any other number: it uses as many tuners as StationPlay offers. The real limit is your server, because each station being watched is converted in real time. The default, 4, is a safe start for most servers, and a GPU can usually handle more. **Test this server** (below) suggests a number for yours.

Everyone watching the same station shares one stream, so a station uses one tuner no matter how many people watch it: 4 tuners means 4 different stations at once, for any number of viewers. The limit covers Plex and every other app together. While anyone is watching, a pill at the top of the page shows how many tuners are in use.

When every tuner is busy, someone tuning in to another station sees an **All tuners in use** card for 30 seconds, listing the stations that are on. (Up to 3 people at a time see the card; anyone beyond that gets Plex's own error.) StationPlay tells Plex it has more tuners than it really does, so Plex always lets it show that card. If you raise the number of tuners and Plex still won't play more stations at once, restart Plex.

A station keeps running for 20 seconds after its last viewer leaves, so flipping back is instant. A station in that state gives up its tuner if someone needs it.

**Test this server** on the **Add to Plex** tab makes a few seconds of video at each picture size (at low priority, so stations that are playing aren't affected) and estimates how many stations your server can play at once. Its suggestion leaves 30% headroom. **Use N tuners for 720p** applies it; choose **Save** to keep it. If you set more tuners than the test suggests, the page warns you.

### How many can watch at once

Every device watching through StationPlay's apps (or another player using the HLS addresses) receives its own copy of the station: at home over your network, and away from home over your internet connection's upload. A station still uses one tuner no matter how many people watch it, so this limit is about your network rather than your server's processor. Programs played from your library in the apps count too.

On the **Access** tab, under **How many can watch at once in StationPlay's apps**, an Admin can limit how many devices watch at once, and how many of those can be away from home. Leave a box empty for no limit. A device that's already watching can always change stations. Any device beyond the limit sees a message such as: "An Admin has limited StationPlay to 5 devices watching at once, so it runs smoothly for everyone. Please try again later." Plex, Jellyfin and IPTV apps aren't counted here: they have limits of their own, and the tuners cover them.

StationPlay recommends limits from **connection tests** run in its apps. A test times data sent by StationPlay, so it measures the connection the way viewers use it. Run one at home, and one on a phone away from home (on mobile data, for example) to measure your home's upload. StationPlay doesn't use an outside speed-test service. The recommendation uses the fastest recent test and leaves 30% headroom, and the page warns you if a limit is set higher.

### Schedules

Programs play back to back at their real lengths. Nothing is stretched or padded to fill 30- or 60-minute slots, so a 7-minute cartoon is followed straight away by the next one.

- **Episode order:** one episode of each show in turn, each show in episode order, like classic reruns. Shows go in alphabetical order, and a movie counts as a one-episode show. When a shorter show runs out, the others continue without it, so a long-running show can end up playing many episodes in a row at the end of the run. Then the run starts again.
- **Shuffle:** every program plays once per pass, and each pass is shuffled again, so a show doesn't air at the same time every day. No show plays more than twice in a row, and nothing from the end of one pass comes straight back at the start of the next. On a station where one show has more than twice as many episodes as everything else combined, the station card says "mostly one show", because that rule can't always hold.

The schedule is worked out the same way every time from when you saved the station. That keeps Plex's guide accurate, and restarting StationPlay never changes what's on.

### Updates from Plex

New episodes join stations automatically, and removed ones leave, without making Plex's guide wrong. Every hour, StationPlay asks Plex what changed and prepares an update. The update starts at the first program break after Plex next downloads the guide, so the guide Plex has already shows it. StationPlay asks Plex to refresh the guide when an update is ready, so this usually happens within the hour. The program on the air is never cut short. The station card shows **Update ready** while one is waiting.

In episode order, the station continues with the program that was due. In shuffle, new programs are spread through the current pass where they fit, and the rest join the next pass, so 23 new episodes of one show don't turn into a marathon.

**Updates that need your review.** On a station with 10 or more programs, an update that would remove more than half of them isn't applied automatically: it's more likely a library being rescanned or a drive offline than something you meant. The card says "Plex lost N programs — needs your review". The same happens if Plex suddenly reports nothing at all, or loses the intro and credits markers for more than half of the programs a station skips them on. Choose **Update now** if the change is right.

**Shows that Plex re-adds.** When Plex re-adds a show or movie (after it was removed and found again, rematched, or moved to another folder or drive), it gets a new ID in Plex. The station finds it again by title, and its episodes keep their places. When more than one show has that title (the same show in two libraries, say), the station follows the one in the library it came from; if that's unknown, the one with the station's own files. If it still can't tell, the station keeps playing what it had, and the **Logs** tab says which show to choose again in the editor.

StationPlay never reads anything from file names. The show, season, episode and title all come from Plex, however your files are named. Plex's specials (season 0) are left out.

### Skipping intros and credits

Set **Intros & credits** to **Skip them** for binge-watching: each program airs without its opening titles and end credits, and the next one starts right away. StationPlay uses the same markers as Plex's own **Skip Intro** and **Skip Credits** buttons:

- Anything before the intro (a cold open) still plays.
- A program ends where its final credits begin. Credits in the middle with a scene after them are skipped, and the scene still plays.
- Programs without markers play in full. The station card says how many programs have something skipped.
- The guide shows each program's length without the skipped parts, so times stay exact.

Markers are used only when they look right: an intro must start in the first half and be under 5 minutes, credits must start in the second half, and skipping can't remove more than half a program or leave less than a minute.

Plex has to find the markers first. In Plex, go to **Settings → Library** and set **Generate intro video markers** and **Generate credits video markers** to run as a scheduled task and when media is added (a Plex Pass feature). StationPlay asks Plex again about programs without markers, first after 6 hours and then less often, so markers Plex finds later arrive like any other update.

### Sound and picture shape

**Sound.** TV episodes are brought to the same loudness (−24 LUFS, the US broadcast standard), so the volume doesn't jump between episodes. Movies keep their original sound, with its full range. Episodes played from your library in StationPlay's apps get the same (see **Even sound for a show's episodes** under [Coming soon: StationPlay's own apps](#coming-soon-stationplays-own-apps)).

**4:3 shows.** Each station shows 4:3 programs with **Black bars** at the sides (the original shape), **Stretch** to fill the screen, or **Zoom** (fills the screen and trims the top and bottom). Widescreen programs are never changed. Many 4:3 shows are stored as widescreen video with black bars built into the picture; with Stretch or Zoom, StationPlay detects those bars and removes them first.

### The guide

The guide covers the next 2 days, both in Plex and in StationPlay's own **Guide** button. Plex only reloads the guide about once a day on its own, which is why it covers 2 days.

## Station features

### Logos

StationPlay includes nearly 1,000 original station logos, all drawn for it:

- **Networks:** made-up broadcast, cable, movie and classic over-the-air channels.
- **Classic TV, TV shows, Cartoons & anime and Teens:** made-up stations in the style of each.
- **Genres:** three designs for each of Plex's 37 genres.
- **Themes:** decades, holidays, seasons, times of day, moods, kids and family, and on-air signs.
- **Letters and numbers:** A–Z and 1–50, in a modern and a retro style.

None copies a real channel's or show's name, symbol or lettering.

A new station numbered 1 to 50 starts with its number's logo (which follows the number if you change it). Other new stations get a logo no other station is using. In the editor, **Choose…** opens the logo picker, with a search box and categories; when the station's name or filter suggests a genre, the picker opens on **Suggested** logos. **Surprise me** picks one at random. You can also show the **Station number** instead of a logo.

**Your own logos.** In the logo picker, choose **Upload your own…**: a PNG, JPEG, WebP, GIF or BMP image up to 10 MB. StationPlay makes it a 512×512 PNG on a clear background, so square images look best. Your logos are listed first, under **Your logos**, and stored in `data/logos`. Delete one with its × once no station uses it.

**Logos from Plex.** A new station with one show or movie is named after it, and if Plex has a logo for it (the title artwork Plex shows on its pages), that becomes the station's logo. A name you type or a logo you choose yourself stays put. On other stations, the first show's Plex logo is offered as **Use the logo from Plex**. StationPlay trims it, keeps its shape (most are wide), and sizes it to match the library's logos, then adds it to **Your logos** when you save the station.

Plex apps load logos from StationPlay's address, so they appear on your home network. Away from home, they appear only if StationPlay's address can be reached from there.

### In the corner

**In the corner** (under **On screen**) shows the station's **Logo**, its **Name**, or a **Clock** (12- or 24-hour, in your `TZ` time zone) in a corner during programs, like a TV network. Options:

- **Size:** Small, Medium or Large.
- **Transparency:** High, Medium or Low.
- **Corner:** click a corner of the preview to move it there.
- **Look:** **In color**, or **All white** like a real network's watermark.
- **When:** **Always**, or **At the start** (the first 30 seconds of each program, and of whatever is on when someone tunes in).

A station showing its number instead of a logo shows its name. Nothing is shown during commercials, trailers or cards. Changes apply from the next program.

**Burn-in protection.** So a screen that keeps a still picture too long (an OLED or plasma TV) never has the same pixels lit for hours, each program starts with the logo, name or clock moved a little: to the next of 9 places, 4 pixels apart, all within 6 pixels of the corner you chose. It stays put all through a program, the Up Next Banner's logo still lands exactly on it, and it works the same whether a station is converted on the GPU or the processor. There's no setting: every station does it.

### Up Next Banner

Three minutes before each show or movie ends, a banner in the bottom-left corner shows the station's logo, **Up next**, and the next program. Set how long it stays (**Off**, 3, 5 or 10 seconds) and its **Size**; **Preview** shows it. If the corner logo is also in the bottom left, the banner takes its place while it's up. The banner skips programs shorter than 3 minutes, programs where what's next isn't known, and programs tuned into after that point. If it can't be drawn in time, the program plays without it.

### Station ID card

**Station ID card** (under **Between programs**) adds a card after each program and its commercials: the station's logo, name and number, and **Up next** with the next program, for 3, 5 or 10 seconds. One of 15 short jingles plays underneath (made by StationPlay, not borrowed from any real station), always quieter than the programs. Set **Jingle** to **Off** for silence. The card's time is part of each program's time in the guide.

### Commercials and trailers

**Commercials & trailers** (under **Between programs**) plays **None**, 1, 2 or 3 clips after each program: commercials after TV episodes, trailers after movies. They're part of each program's time in the guide, so nothing is squeezed. Each clip plays about as often as the others, and is brought to the same loudness as TV episodes.

The clips come from two folders, named exactly as shown (Linux names are case-sensitive):

- `commercials` at the top of your TV library's folder, such as `/mnt/tank/media/tv/commercials`
- `trailers` at the top of your movie library's folder, such as `/mnt/tank/media/movies/trailers`

StationPlay finds them through the folders Plex lists for each library. If a library is your whole media folder, put the folder directly inside it. Subfolders are fine. Clips from 3 seconds to 10 minutes long are used. Put a file named `.plexignore` containing `*` in each folder so Plex doesn't add the clips to your libraries:

```
cd /mnt/tank/media
mkdir -p tv/commercials movies/trailers
echo '*' > tv/commercials/.plexignore
echo '*' > movies/trailers/.plexignore
```

**Commercials from the right decade.** Put clips in a subfolder named for a decade (`commercials/1960s` or `commercials/60s`; trailers work the same way), and they play only after programs from that decade, by the year Plex gives each program. Clips outside decade folders play after everything else.

StationPlay looks in the folders at startup and every hour; Admins can choose **Check again** in the editor to look right away. If a folder seems to vanish (a share that isn't mounted yet), the clips already found are kept for a few hours. A clip that fails to play is left out until its file changes, and listed on the **Broken files** tab under **Commercials and trailers that didn't play**. A plain card fills its time.

### Intro Bumper

When someone tunes in, an **Intro Bumper** (under **When someone tunes in**) can play before the program, like a station ident:

- **Built-in card:** the station's logo arriving (one of a dozen ways), "You're tuning in to", the station's name, a **Description** line, and what's on, for 3, 5, 10 or 15 seconds. Its **Sound** is an old TV dial turning through static. **Preview** shows it.
- **Your video:** upload a video up to 30 seconds long (MP4, MOV, MKV, WebM and similar, up to 500 MB). StationPlay makes a copy at the right size, with its volume matched to the programs. Your videos are stored in `data/bumpers` and available to every station.

The bumper plays when a station's stream starts. Someone tuning in while others are already watching joins the stream in progress, without a bumper. If a bumper can't be shown, the built-in card or a plain card plays instead.

### Where viewers join

**Viewers join** (under **When someone tunes in**) decides what happens when someone tunes in:

- **In progress** (the default): like real TV. Tune in at 10:20 to a show that started at 10:00 and you join 20 minutes in. The program keeps its place in the schedule, so viewers join it as far in as the bumper is long. In the bumper's last third, the show's sound fades in and carries straight into the show.
- **From the beginning:** the program on now starts from its beginning, right after the bumper. The station then runs that far behind the guide for as long as anyone is watching (Plex's guide still shows the schedule). When no one is watching anymore, the next viewer starts fresh. The bumper keeps its own sound to the end, so none of the program is missed. If someone tunes in during the commercials after a program, the next program starts from its beginning anyway. A program that began more than 2 hours earlier is joined in progress.

### Subtitles

**Subtitles** (under **On screen**) draws subtitles into the picture: **Off**, **Forced only** (just the lines meant to be read, such as foreign-language dialogue) or **Always**. They use the language set by `AUDIO_LANGUAGE` (English unless you change it), from the program's own file (text or DVD/Blu-ray picture subtitles) or a subtitle file beside it named the way Plex expects (`Movie (1999).en.srt`, `Movie (1999).en.forced.srt`). With **Always**, ordinary subtitles are preferred over SDH (with sound descriptions), and text over pictures.

Because they're part of the picture, viewers can't turn them off. Text subtitles inside a file are extracted in the background, one program ahead, so the first time a program airs it may play without them. If subtitles can't be drawn, the program plays without them.

### Specials: marathons, Feature Presentations and blocks

Under **Specials**, three kinds of event can take over a station's schedule now and then. Each starts at a program break near its time: the start or end of the program airing then, whichever is nearer (on a movie station, that can be an hour away). When it's over, the station picks up exactly where it left off. Specials are planned about a week ahead, before any guide shows them.

If two would overlap, a block wins over the Feature Presentation, and both win over a marathon; the other is skipped that time (the **Logs** tab says so). A special that would start more than 15 minutes late, because the one before it ran long, is skipped too.

- **Marathons:** three episodes of one show in a row. Choose **Random times** (1 to 4 a week) or **Set times** (days and a time). Shows take turns, and each marathon plays **Next in order** (picking up where that show's last marathon ended) or a **Random starting point**. A station needs at least 5 shows with 3 or more episodes each. Plex's guide adds "Show Name Marathon (1 of 3)." to each episode's description.
- **Feature Presentation:** a movie night on the days and at the time you choose. A 10-second **Feature Presentation** card plays first (**Preview the card** shows it), then the movie. **Movies from** the station's own movies, a movie library, or a movie collection, so a TV station can have movie nights too. Every movie is shown once before any repeats.
- **Blocks:** up to 4 time-of-day blocks, such as Saturday Morning Cartoons. Each has a name (up to 40 characters), days, start and end times (30 minutes to 12 hours, past midnight is fine), and shows of its own (**Choose shows…**). A block plays its shows in the station's order, ends at the program break nearest its end time, and continues where it left off the next time. A block is skipped if the nearest program break comes after its end time.

Saving is refused, with the reason, if a Feature Presentation has no movies, a block has nothing to play, two blocks overlap, or a Feature Presentation or marathon falls during a block. The station card shows when each special is next.

## Keeping stations on the air

A bad file should never take a station down. StationPlay is built around that.

### Safeguards

| When | What StationPlay does |
|---|---|
| A program won't open, or stops partway | Tries the same program again from where it stopped, twice (after 1 and 2 seconds). Many hiccups clear up by themselves. |
| It still won't play | Puts it on the [Broken files list](#the-broken-files-list), and a stand-in joins at the same point. If an episode fails 10 minutes in, the stand-in starts 10 minutes in and ends when the broken one would have, so the guide stays right. |
| Choosing a stand-in | Another episode of the same show first, then a program of the same kind, then anything long enough. In a block or Feature Presentation, its own programs come first. Up to 4 are tried. |
| Opening a file is slow (a sleeping drive, a busy NAS) | Keeps the stream alive with a few seconds of black. |
| A file stalls (no new video for 8 seconds) | Resumes or replaces it as above. A stall is blamed on storage, not the file: the file is skipped for the rest of that viewing, and listed only if it stalls in two separate viewings. A stuck ffmpeg process is abandoned after 2 seconds, and the next program reads ahead to rebuild the stream's 10-second cushion. |
| Something drawn over the picture fails (corner logo, banner or subtitles) | Tries the program again with nothing drawn over it before blaming the file. |
| Plex or the media share can't be reached | Skips the affected programs for now, without listing them. |
| A file is a few seconds shorter than Plex says | Fills the rest of its time with black. (More than 10 seconds or 2% short counts as cut short.) |
| Nothing on the station can fill the time | Shows a "We'll be right back" card for the time that's left, then continues. |
| Nothing could play for two programs in a row | Shows "This station is off the air. Please report it." and logs an error. It keeps trying each new program and comes back on the air by itself. |
| The station's stream fails | Restarts it immediately in the same stream, so viewers see at most a brief pause. It also restarts a stream that sends nothing for 45 seconds. After 3 failures within 5 minutes, the off-air card shows for 2 minutes before it tries again. A program that crashes the stream twice is skipped for that viewing. |
| Sonarr or Radarr upgraded or renamed a file | Nothing to do: StationPlay asks Plex for the current file every time a program plays. |

### The Broken files list

Programs that can't play properly go on the **Broken files** list, kept on the **Broken files** tab and in `data/broken-files.json`. Each entry says what's wrong, when it was found, how many times it failed, the file's path, and which stations have it (each opens that station's editor). Every entry is skipped on every station until it's cleared, and a stand-in plays in its place.

| Label | Meaning |
|---|---|
| **Missing** | The file is gone from disk, or the program is gone from Plex, while a station still has it. |
| **Broken** | The file won't play. |
| **Damaged** | It plays, but not properly (see [What counts as a problem](#what-counts-as-a-problem)). |
| **Unsupported** | It plays, but can't be shown correctly (Dolby Vision profile 5). |

When the list has both missing and other entries, buttons above it show just one kind. **Download list** saves it as a file.

**Clearing an entry yourself:**

- **Retry** means "the file is fine": the program goes back on the air, and the file checks leave that file alone from then on. (An Unsupported file then plays with the wrong colors.)
- **Removed a show on purpose?** Take it off the stations its entry lists, and its **Missing** entry clears itself within half an hour. Broken, damaged and unsupported entries stay even then, so a bad file can't return unnoticed.
- You can also delete an entry from `broken-files.json`; StationPlay notices within 15 seconds. Unlike **Retry**, that doesn't tell the checks to leave the file alone.

**Entries that clear themselves:**

- **Every half hour,** StationPlay checks the list against Plex. An entry clears when Plex has the program again under a new ID, or when its file is missing (or Plex removed it) and no station has it anymore. A program with a new file gets a quick check, and clears if the new file passes; otherwise the entry says what's wrong with the new file.
- **Every night,** when the overnight checks begin (1 AM unless you change it), and whenever you choose **Check the list again**, StationPlay also re-checks programs taken off the air by a quick check or because their file couldn't be opened (a share may have been down). They clear if they pass.
- Problems found by the deep scan or during playback stay until the file changes, because checking the same file again would find the same thing.

StationPlay recognizes a program Plex re-added under a new ID by its own show, season and episode first, then by the same file name, the same TVDB show, or the same episode title and year, never by a title alone.

### File checks

StationPlay checks your files at the lowest priority, so problems are found before anyone tunes in. While anyone is watching, the checks step aside: the automatic checks wait until no one is watching, and **Check files** and the list's re-checks read one file at a time with a rest between. (ZFS and most NAS disks ignore low disk priority; reading less at once is what helps.)

- **Quick check, when a program arrives:** a program new to a station is quick-checked within minutes, before it airs if possible. The file must open, and picture and sound must decode at five points (start, quarter, half, three quarters and end).
- **Weekly:** every program on a station is quick-checked again once a week, which also catches files that went missing or were replaced.
- **Overnight deep scan:** between 1 AM and 6 AM (change or turn off with **Deep scan every night from** on the **Broken files** tab), programs are decoded in full, soonest to air first. The scan stops the moment anyone starts watching and continues later. Each file is deep-scanned once, and again only if it changes. A 45-minute episode usually takes a few minutes.
- **Check files** on a station card quick-checks all of its programs right away. A new station gets this automatically.

The **Broken files** tab shows how far the checks have gotten and what the deep scan is doing.

#### What counts as a problem

| Result | What it means |
|---|---|
| **Broken** | The file won't open or has no picture; nothing decodes after some point; its picture stops early (more than 10 seconds or 2% short of its stated length, whichever is more); or it can't be read (a disk or share error, seen on two different nights). |
| **Damaged** | The picture breaks up, the sound drops out, or the file skips (see below). No sound, or no picture and sound, for 30 seconds or more partway through. No sound track, or silence all the way through (for programs from 1930 on). A completely black picture. Sound that stops before the picture does, unless it stops during the end credits, over a black picture, or after fading out in the last minute. A file that plays well past its stated length, so its ending would be cut off. |
| **Fine** | A decoder warning about something no one would see or hear, a patched picture shown for an instant, sound lost for less than 20 ms at one spot, anything in the first 2 seconds or last 5, a pause or silence under 30 seconds, a picture held still while sound plays (such as end credits over one drawing), a black opening, and a file slightly shorter than its stated length. |

**How the deep scan judges glitches.** Decoders report many errors that change nothing you'd see or hear. (Dolby TrueHD's "quant_step_size larger than huff_lsbs", common in Atmos tracks, is one: each costs at most 1/1200 of a second of sound.) So StationPlay goes by ffmpeg's report on each frame:

- **Picture:** a picture ffmpeg couldn't decode, or had to patch because part of it was missing or garbled, counts when later pictures are built on it, because the damage then stays on screen until the next full picture, often for seconds. One is enough. A patched picture shown for just one frame (a B-frame) doesn't count: tests comparing damaged files with clean ones found it gone within a frame or two.
- **Sound:** each lost or garbled frame of sound costs a fixed slice of time: about 21 ms for AAC, 32 ms for Dolby Digital, 11 ms for DTS, and under 1 ms for TrueHD. It counts when 20 ms or more is lost within one second, which you'd hear as a click or dropout.
- **Skipping:** part of the file's container is garbled, so playback jumps ahead.

None of these can freeze a player: StationPlay decodes every program and encodes it again, so players always receive a clean stream.

Each entry says what was found and where, such as "the picture breaks up around 12:31 and 48:02" or "no sound from 12:00 to 12:40". Glitch times are approximate: the real spot can be a few seconds before the time shown.

When an update changes how files are checked, files are checked again under the new rules (quick checks within hours, deep scans over the following nights). Programs taken off the air by the old quick check go back on the air right away and are re-checked first.

### Replacing files with Sonarr and Radarr

StationPlay only needs Plex. But if you use **Sonarr** (TV) or **Radarr** (movies), StationPlay can ask them to replace files on the Broken files list that a station plays. It works with Sonarr and Radarr version 3 and later.

**Turning it on.** On the **Broken files** tab, open **Replacing files with Sonarr and Radarr**. For each app, check **Use Sonarr for episodes** (or **Use Radarr for movies**), enter its address (such as `http://192.168.1.10:8989` for Sonarr or `:7878` for Radarr) and its API key (in the app, under **Settings → General**), choose **Test**, then **Save**. API keys are stored in StationPlay's database (and its backups) and never shown again.

**Choices:**

- **Files to replace:** **Broken or damaged**, **Missing**, or **Both** (the default). Choose **Broken or damaged** if missing files are usually ones you removed on purpose.
- **When to replace:** **Only when I ask** (the default) or **Automatically**.
  - With **Only when I ask**, nothing happens until you choose **Replace with Sonarr** (or **Radarr**) on an entry. After that, the app handles it on its own.
  - With **Automatically**, every entry is replaced without asking. Choose **I'll handle it** on an entry to stop that for it, and **Replace with Sonarr** to start again.
  - **Retry** still means "the file is fine".

StationPlay only asks about what the app is **monitoring** (in Sonarr, both the show and the episode). Unmonitoring something there is how you tell both apps to leave it alone; the entry says so, and **Try again** picks it up once it's monitored again. StationPlay finds the show by its TVDB ID (or its title) and the movie by its TMDB or IMDb ID (or its title and year), and only continues if exactly one matches.

**What happens:**

1. **A broken or damaged file:** StationPlay first has the app **blocklist** the release the file came from (as **Mark as Failed** in the app's History does), so the app won't download it again. Then the app deletes the file (into its recycle bin, if you set one) and searches for another. This only happens if the app's file is exactly the one StationPlay found broken (same name and size) and the app has a record of downloading it. A file you added by hand can't be blocklisted, so it's left to you.
2. **A missing file:** the app rescans the folder, then searches for it.

Each episode or movie gets up to **3 searches, 8 hours apart** (sooner if the last search brought a file that didn't work). When the app has a new file, StationPlay asks Plex to scan that folder, checks the new file, and puts the program back on the air once it passes. If Plex still hasn't found the file after a day, the entry says **Can't replace**.

**The same problem twice.** If the new file has the same problem at the same times (at least half of them within 30 seconds of the old file's), the problem may be part of the program itself, such as an old film's transition effects. StationPlay stops, blocklists nothing, and marks the entry **Needs your review**. Watch it at those times: if it looks fine, choose **Retry**; if not, **Try another file** blocklists that file too and searches again.

Each entry shows what the app is doing: **Replacing**, **Downloading**, **Downloaded**, **Gave up** (3 searches found nothing that works; **Try again** starts over), **Can't replace**, **Needs your review** or **You're handling it**. The **Logs** tab records every step. Unsupported files aren't replaced this way, since the right version is best chosen yourself.

## Who can use StationPlay

When StationPlay is first installed, its page is open to anyone on your network. (On the internet port, `PUBLIC_PORT`, signing in is always required.) To require sign-in, choose **Only people who sign in** during setup, or add a user on the **Access** tab with a name and a password of at least 8 characters. **The first user is always an Admin**, and you're signed in right away. After that, everyone else sees a sign-in page.

| Role | Can do |
|---|---|
| **Admin** | Everything. |
| **User** | Watch the stations and library their Viewing Level allows, and see the Stats tab. Make stations (3 by default; an Admin can choose none, 1, 3, 5, 10, 25 or no limit) and change or delete only their own; on a Viewing Level with limits, they only watch. Add logos and Intro Bumper videos (only Admins delete them). Can't open **Add to Plex**, **Broken files**, **Logs** or **Access**. |

- There's always at least one Admin. Removing the last user turns sign-in off again.
- Stations made before sign-in was turned on, or by a removed user, can be changed only by Admins.
- An Admin can rename people (themselves and other Admins too), change roles and set new passwords on the **Access** tab. A new name follows the rules a new user's does (no one else's, whatever its case), people sign in with it from then on, and everything of theirs stays theirs: their sign-ins and linked devices, the stations they made, their Viewing Level, where they are in what they watch, and their stats. StationPlay's apps show the new name the next time they ask. Your name at the top of the page lets you change your own password or sign out, and so do StationPlay's apps, in their Options. **Can change their own password**, beside each person's **New password**, says whether they may (yes, to start with; an Admin always may). A new password signs that person out everywhere else.
- A sign-in lasts 30 days after it was last used. After 5 wrong passwords from one address within 15 minutes, that address has to wait. Passwords are stored only as salted hashes.
- StationPlay's page signs you out after an hour without activity. StationPlay's apps stay signed in.
- Plex and IPTV apps never need a password, just like a real HDHomeRun: the tuner, guide, streams, logos and playlist stay open on your network.

### Viewing Levels

Each person has a **Viewing Level**: what they can see in StationPlay's apps and on its page. Admins always see everything. Choose a person's level beside their name on the **Access** tab. Under **Viewing Levels**, rename, change or remove the levels StationPlay starts you with, and add as many of your own as you need, such as "Adults" with no R-rated movies or unrated titles, or "Grandparents".

| Level | Movies up to | TV up to | Unrated titles |
|---|---|---|---|
| **Unrestricted** (everyone, to start; stays as it is) | No limit | No limit | Shown |
| **Teen** | PG-13 | TV-14 | Hidden |
| **Kid** | PG | TV-PG | Hidden |
| **Young Child** | G | TV-G | Hidden |

- **Ratings.** Plex's content ratings are read as ages, US and other countries' alike (such as `gb/15` or `de/12`). An episode counts as its show's rating, or its own if that's stricter. A title with no rating, or one StationPlay doesn't recognize, counts as unrated.
- **Libraries.** A level can also be limited to some libraries. That's how a show that's in both "TV Parents" and "TV Teens" is seen only through the library a person's level includes.
- **Stations are all or nothing.** Everyone watching a station sees the same stream, so a station is shown only if everything it plays is within the person's level. Choose **Stations** beside someone's name to allow or block a station for them anyway; it also says why each one is shown or hidden.
- **Nothing hidden shows.** What someone can't see isn't in any list, search, guide, Resume row or "on now" for them, and its address answers as though it doesn't exist.
- **Watching only.** People on a level with limits watch what they can see but can't make stations, since the station editor shows your libraries as a whole.
- **Plex and other apps.** Plex, Jellyfin and IPTV apps don't say who's watching, so they show every station. To keep stations from some people in Plex, see **Blocking stations for some Plex users**, below.

StationPlay learns the ratings of what's on each station as it checks Plex for updates. Until it knows a station's ratings, that station is hidden from anyone with limits.

### Linked devices and Who's tuning in?

StationPlay's apps can share one device among several people, such as the living room TV. The first time someone signs in on the device (with their password, or a code entered on StationPlay's page), it's **linked**. From then on, it opens on **Who's tuning in?**, and whoever is watching picks themselves.

- **Who's on the list.** Choose **Devices** beside a person's name: **Devices at home** (a household: on every device while it's at home, or through your VPN; away from home, only on a device they signed in on, or one you choose), **All devices** (away from home too), **Selected devices** (such as a family iPad that travels), or **Only where they sign in** (a larger server). New people start as **New people show on** says, under **Linked devices**.
- **Passcodes.** A person can have a 4-digit passcode, which the device asks for when they pick themselves. An Admin without a passcode gives their password. Five wrong passcodes for someone means a 15-minute wait for them, on every device. The first time someone signs in on a device with their password or an invite code, the app asks them to choose a passcode or none, and they can change it in the app's Options; an Admin who has a passcode keeps one. An Admin sets or removes anyone's under **Devices** beside their name on the **Access** tab.
- **No password needed.** A User can have no password, such as a "Kids" user who only picks themselves on the TV. Someone with neither a password nor a passcode can't sign in by name, so they're shown on devices at home or selected devices only.
- **Sign in on a new device.** Choose **Sign in** on Who's tuning in?, then enter your name and your password, or an **invite code** an Admin made for you under **Devices** (it works once, for 7 days). After that, you're on that device's list. Anyone can take themselves off a device's list.
- **Unlinking.** **Linked devices** on the **Access** tab lists each device and who's on its list. **Unlink** signs it out at once.

A sign-in from Who's tuning in? lasts a day from when it was last used, so a shared device goes back to the list rather than staying signed in as someone.

**Access log.** On the **Logs** tab, check **Access** to see sign-ins, failed sign-ins, sign-outs and changes to users. The newest 2,000 entries are kept across restarts.

**Locked out?** Create an empty file named `reset-access` in StationPlay's data folder (for example, `sudo touch data/reset-access`) and restart the app. Every user is removed, the page is open again, and the file is deleted.

### Blocking stations for some Plex users

*Optional; needs Plex Pass.* Plex can't hide a station from one person: every station appears in the guide for everyone with Live TV on your server, and Plex's parental controls don't cover Live TV. Instead, StationPlay can stop someone's playback.

On the **Access** tab, under **Block stations for some Plex users**, choose which stations each Plex user can't watch, check **Stop Plex users from watching stations blocked for them**, and choose **Save**. When a blocked user tunes in, Plex stops their playback within seconds and shows "This station isn't available on your Plex account." (in Plex apps that show messages). If they tune in again, it's stopped again. The tab lists recent stops, and the **Logs** tab records each one.

**Requirements:**

- **Plex Pass** on the account that owns your Plex server (the tab shows whether Plex reports it).
- **Watching in a Plex app.** This covers you, your Plex Home users (including managed users), and friends you've shared Live TV with. Apps using the M3U playlist aren't covered.
- **A Plex user for each person.** Everyone sharing one Plex account counts as one user.
- **Sign-in turned on in StationPlay.** Otherwise anyone on your network could turn blocking off.

StationPlay only stops a stream when it's sure which station it is: the one station with viewers airing exactly what Plex shows, or the one matching the channel number Plex reports. If two stations air the same program at once and Plex gives no channel number, it can't tell them apart and stops neither (the log says so, once). While a blocked user's station has viewers, StationPlay asks Plex what's playing every 5 seconds.

## Stats

The **Stats** tab shows how much each station is watched: viewings, hours watched, average viewing, when it was last watched, and its most-watched show or movie. Below are the most-watched shows and movies overall and the times of day people watch. Choose **Today** (since midnight), **7 days**, **30 days** or **All**.

A viewing counts once it lasts a minute, so flipping past a station doesn't count. Viewings are counted per stream, so several people watching one station together in Plex can count as one viewing; each of StationPlay's apps counts on its own. Stats are kept for 400 days, and a station's stats are deleted with it.

Admins see more (so does everyone while sign-in is off):

- **Server**, at the top, updated every 5 seconds while the tab is open: the processor and memory StationPlay uses and the whole machine's (or the container's memory limit, when it has one), what it's sending and receiving, which GPU is in use and how many stations and copies are on it, and the data folder's free space, each with a line of its last 10 minutes. StationPlay reads these from Linux itself (in Docker, the container's own figures); anything it can't read says "not available".
- **Watching now**: everyone watching right now, one row each: who, what (a station and what's on it, or something from Media), how it's sent (as it is, repackaged or converted; its picture size and bitrate; on the GPU or the processor), in which app on which device, at home or away, and since when.
- **Top people**: who watched most, stations and Media together, and the stations and shows or movies each watches most. In StationPlay's apps, viewing counts for whoever is signed in on the app (at home, for whoever's app last asked for the stations from that device). For Plex, while a station has viewers, StationPlay asks Plex every 30 seconds what it's playing and to whom, and matches each Live TV session to a station; Plex users are marked **Plex**. Viewing in other apps isn't counted per person, and neither is Plex time when two stations air the same program at once. If your Plex token isn't allowed to see what's playing, the tab says so.
- **Top Media**: the shows and movies played most on demand in StationPlay's apps, with hours and plays. Watching the same thing again on the same device soon after (with another sound track, or a smaller version) is the same play.

## StationPlay's API

*Optional.* Your own scripts, home automation (such as Home Assistant) and other players can use StationPlay's API, under `/api/v1`: the server, its stations with what's on now and next, the guide, each station's HLS stream, and how StationPlay is doing. With an Admin token, they can also update a station from Plex, check a station's files, ask Plex to refresh its guide, and make a backup. It's documented in [docs/api.md](docs/api.md), with an OpenAPI spec at `/api/v1/openapi.json` (also in [docs/openapi-v1.json](docs/openapi-v1.json)).

Version 1 is a stable contract: it only grows. New fields and addresses may be added, but nothing is renamed, removed or changed in meaning. A change that would break a client comes as version 2, served beside version 1, which then carries `Deprecation` and `Sunset` headers for at least six months before it goes.

**API tokens.** While sign-in is off, the API needs no token on your network. Once it's on, an Admin makes a token for each script on the **Access** tab, under **API tokens**: give it a name, choose **Viewer** (it can only read) or **Admin**, and choose when it expires. The token is shown once, so copy it then; StationPlay keeps only a hash of it. Scripts send it as `Authorization: Bearer <token>`.

- A token works only with the API, never with StationPlay's page, and never does more than the Admin who made it may do now.
- The Access tab shows when each token was last used. Revoke one there at any time; removing the Admin who made it revokes it too. The access log records each token made and revoked.

**From the internet.** API tokens are refused on the public port until an Admin checks **Accept API tokens from the internet** on the **Access** tab, and even then work only over HTTPS (through a reverse proxy or a Cloudflare Tunnel; see [Reaching StationPlay from outside your home](#reaching-stationplay-from-outside-your-home)). With Cloudflare Access in front, a script also needs a Cloudflare Access service token. A VPN is simpler still: to StationPlay, a script on the VPN is on your home network.

StationPlay's own apps also use addresses under `/api/internal`. Those are for the apps only, aren't part of the API, and may change with any release.

## Settings

StationPlay is set up mostly on its page. These environment variables (in the YAML or `docker-compose.yml`) cover the rest:

| Variable | Default | What it does |
|---|---|---|
| `PLEX_URL` | *(none)* | Your Plex server's address, such as `http://192.168.1.10:32400`. Required. |
| `PLEX_TOKEN` | *(none)* | Your Plex token (see [Finding your Plex token](#finding-your-plex-token)). Required. |
| `TZ` | `UTC` | Your time zone, such as `America/Chicago`. Used for the clock, specials, the overnight checks, backups, stats and log times. |
| `MEDIA_DIR` | `/media` | Where your media is mounted inside the container. |
| `PATH_MAPPINGS` | *(none)* | For unusual layouts only: `plex/path:local/path`, several separated by `;`. |
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

Picture sizes and the number of tuners are set on the page. Versions before 1.14 used `TUNER_COUNT` and `VIDEO_HEIGHT`: if they're still set, the page starts from them once and then ignores them (the **Logs** tab says so). `VIDEO_WIDTH` and `VIDEO_BITRATE_KBPS` are no longer used.

## Troubleshooting

Start with the **Logs** tab: it shows the newest 200 entries. Check **Warnings** or **Errors** to filter, and use **Copy** to paste them into a message. `docker logs stationplay` (or the app's logs in TrueNAS) has everything.

**What's playing.** The log names each station by its number and name ("station 2, Cartoon Classics"), and says what plays as it starts:

- **A station's program**: its file, its picture and sound ("1080p H.264, 5.1 E-AC-3"), and how the station makes it ("made 720p at 3.5 Mbps on the Intel/AMD GPU", "HDR made ordinary", "subtitles drawn in"). Tuning in from the beginning is said on the same line.
- **Media in StationPlay's apps**: who started what, in which app on which device, at home or away; its file, picture and sound; and how it plays: as it is, repackaged (and what changed, such as its sound made AAC stereo), or converted (to what, on the GPU or the processor, and why: what the device can't play, a picture made smaller to fit the connection, subtitles drawn in, or night mode's sound).
- **A step down in quality**: when an app switches to a smaller version or copy, one line says from what to what and why, with the app's own reason when it sends one.
- **Stopping**: who stopped what, where in it, and how long they watched; an app watching a station says when it stopped, and after how long.

**Problems in the apps.** At the top of the **Logs** tab, StationPlay's apps say when something goes wrong as they play: a station that doesn't start or stops, something from your library that doesn't play, playing that can't keep up, the app closing unexpectedly, or the app not reaching StationPlay for a minute or more (such as "Den couldn't reach StationPlay for 12 minutes · No network on this device"). An app that can't reach StationPlay keeps what went wrong meanwhile and sends it once it's back, saying when each happened. Each problem shows how often it happened, on how many devices and for whom, and on what kinds of device (the app, its version, the device's model and system), marked **One kind of device** when that's all it's been on. So a problem on every kind of device points to StationPlay or the file, and one on a single kind of device points to that device or its app. Under it, **What it means** says in plain words what the player's error was (for the errors StationPlay knows), **What the app said** gives the error as it was, and **What led up to it** shows the app's last lines before it. They're kept 30 days; **Clear** forgets them (the log keeps its own). For more about one device, its **Send a report to StationPlay** (in the app's Options) adds what the app did lately.

**Alerts.** StationPlay says when something needs an Admin's look: Plex can't be reached (or won't take StationPlay's token); the data folder has less than 2 GB free, or can't be written to; a station keeps failing to start (3 times in 10 minutes); backups fail twice in a row; StationPlay's clock is more than 2 minutes from Plex's (by the time Plex's answers carry: without it, the clock isn't checked); or StationPlay's apps can't reach it from outside. Each is said once it has lasted a while (for Plex, five checks a minute apart) and fixed once things have been right a while, so none comes and goes: a line in the **Logs** tab when it starts and when it's fixed, and for Admins, a pill in the page's header saying how many there are now, which opens a list of them. Admins see them in StationPlay's apps too. To be told elsewhere, open **Notify a web address** at the top of the **Logs** tab, turn it on, and enter a web address: an ntfy topic (**Plain text**), or a Gotify message or Home Assistant webhook address (**JSON**: `{"title": "StationPlay", "message": "...", "kind": "...", "state": "started"}`, or `"fixed"`). **Send a test** tries it at once. StationPlay waits 5 seconds for an answer, tries once more, follows no redirect, and keeps only the answer's status; the address is shown only to Admins, and the log names only its site.

**Installing and starting**

- **The app keeps restarting, and the log says it can't write to `/data`.** The data folder isn't owned by the user StationPlay runs as. The message shows the `chown` command to run: fill in your data folder's path, run it, then restart the app.
- **The app won't start, and mentions `/dev/dri`.** The GPU lines are in the YAML, but the server has no Intel/AMD graphics. Remove the `devices:` and `group_add:` lines.
- **Docker says port 3310 or 3311 "is already allocated" or "address already in use".** Another app on the server uses that port. Change only the first number of the port line (for example, `"3320:3310"`), and use the new port in every address: in your browser, and in Plex or your other apps.
- **After updating on TrueNAS, the page still shows the old version.** The app was saved before the new version was unzipped into `src`, so TrueNAS rebuilt the old code under the new number. Check that `src/app/__init__.py` has the new version, then edit the app, raise the version in `image:` once more, and save. Restarting the app never rebuilds it.
- **The page shows "Plex: PLEX_URL and PLEX_TOKEN aren't set"** or **"Plex didn't accept the token in PLEX_TOKEN".** Fix those two settings. Users who aren't Admins only see "Plex: not connected". If Plex runs in Docker on the same machine, use the machine's network IP in `PLEX_URL`, not `localhost`.

**Plex**

- **Plex can't find the tuner.** StationPlay doesn't answer Plex's automatic network search. Enter the address manually (see [In Plex](#in-plex)).
- **Plex says no tuners are available.** If you raised StationPlay's tuners, restart Plex so it reads the new number. When StationPlay's own tuners are all busy, viewers see its **All tuners in use** card instead.
- **The guide shows the wrong program.** In Plex, choose **Settings → Live TV & DVR → your tuner → Refresh Guide**, wait a minute, then reload the Plex app (apps keep the guide they loaded). The **Logs** tab says "Plex downloaded the guide" when Plex has the new one.
- **Plex says "Device not found".** Plex is looking for StationPlay's tuner under an old ID or address. The **Logs** tab shows which tuner Plex lists, such as `device://tv.plex.grabbers.hdhomerun/1A2B3C4D at <address>`. StationPlay's own ID is the `DeviceID` at `http://<server-ip>:3310/discover.json`. If the IDs differ (after starting with a fresh data folder, say), put Plex's ID in `data/device.json` as `{"deviceId": "1A2B3C4D"}` (exactly 8 hexadecimal characters), make sure the file belongs to StationPlay's user (such as `sudo chown 1000:1000 data/device.json`), and restart StationPlay. If the address is wrong, set up StationPlay in Plex again.
- **A managed user can't see the stations.** Their Live TV & DVR access must be **Allow Live TV and DVR access**.
- **Skipping intros and credits doesn't skip anything.** The card says "no intros or credits found yet" until Plex has marked some programs. Check Plex's marker settings (see [Skipping intros and credits](#skipping-intros-and-credits)). Plex finds intros by comparing episodes of a season, so a season with very few episodes may not get them.

**Playing**

- **A station shows "This station is off the air. Please report it."** Nothing on it could play for two programs in a row, or its stream failed 3 times within 5 minutes. The **Logs** tab says why: usually Plex or the media share can't be reached, or every program on the station is on the Broken files list.
- **A stream stops.** The **Logs** tab says what happened. "Viewer … left station … after …" means the player closed the connection itself. "Viewer … was disconnected from station …" gives StationPlay's reason. "is falling behind real time" means the server can't convert video as fast as it plays: use a smaller picture size, fewer tuners, or a GPU.
- **HDR movies look washed out.** The **Logs** tab says at startup if ffmpeg can't convert HDR (StationPlay's own image can).
- **Subtitles don't show.** The program needs subtitles in the `AUDIO_LANGUAGE` language, in its file or beside it; with **Forced only**, it needs forced ones. The first airing of a program may play without them while they're extracted.
- **No commercials or trailers play.** The editor shows how many were found. The folders must be named exactly `commercials` and `trailers`, at the top of a library's folder as Plex lists it, and visible inside `/media`.
- **A Feature Presentation or block doesn't happen.** The station card says when the next one is. A more important special may have overlapped it, or it would have started too late; the **Logs** tab says so.
- **Up Next Banners never appear, and the log mentions the data folder's path.** `DATA_DIR` is set to a path with characters ffmpeg can't handle. Remove the `DATA_DIR` setting: the default, `/data`, always works. (The folder's name on your server doesn't matter.)

**Files and the Broken files list**

- **Many files go on the list at once.** Check the reason. If StationPlay can neither see the files under `/media` nor reach Plex, programs are skipped, not listed. If Plex itself has lost the files, they're listed as "can't open the file" or "removed from Plex". Check the **Media files** line on the **Add to Plex** tab, fix the cause, then use **Retry**.
- **A file is listed as Damaged, but plays fine for you.** Choose **Retry**: it goes back on the air, and the checks leave that file alone.
- **A station stopped following Plex.** An update that would remove more than half its programs waits for you: choose **Update now** if it's right (see [Updates from Plex](#updates-from-plex)).

**GPU**

- **The GPU isn't used.** The **Video encoding** line on the **Add to Plex** tab says why. Usually it's the group number in `group_add` (the message names the right one) or `/dev/dri` not being passed to the container. `docker exec stationplay vainfo` shows whether the Intel/AMD driver sees the GPU.
- **"… was turned off after 3 programs in a row failed on it".** StationPlay stopped using the GPU to keep stations playing. Restart StationPlay to try the GPU again; if it keeps happening, check the GPU driver.

**Access and blocking**

- **Locked out of StationPlay's page.** See **Locked out?** under [Who can use StationPlay](#who-can-use-stationplay).
- **"Plex wouldn't stop … Stopping playback needs Plex Pass on the server owner's account."** Blocking needs Plex Pass on the account that owns the server.
- **"Plex won't say who's watching…"** Your Plex token isn't allowed to see what's playing. Use the server owner's token. Stats by Plex user and blocking both need it.

## Development

```
pip install -r requirements.txt pytest pytest-asyncio
python -m pytest                     # all tests, including end-to-end tests with real ffmpeg (about 30 minutes)
STATIONPLAY_SOAK=1 python -m pytest -k soak                # two long soak runs, 8 minutes each
STATIONPLAY_SOAK=1 STATIONPLAY_SOAK_MINUTES=30 python -m pytest -k soak
STATIONPLAY_REALWORLD=1 python -m pytest tests/test_e2e_realworld.py

pip install ruff mypy
ruff check app tests && ruff format --check app tests      # lint and formatting
mypy app                                                    # type checks
```

The tests need ffmpeg on the `PATH` (the HDR and real-world tests also need ffmpeg with libx265; they're skipped otherwise). `requirements.txt` is pinned for Python 3.13. The end-to-end tests run a fake Plex whose library includes a cut-short file, an unopenable file, a file with no sound and a source that stalls, and a stand-in ffmpeg (`tests/fake_gpu_ffmpeg.py`) that acts like a GPU and can be told to fail. They check that a viewer receives one continuous, clean stream that keeps pace with the clock.

`.github/workflows/image.yml` is optional: if you keep the code on GitHub, it runs the tests and publishes an x86-64 image to GitHub's container registry.

**The setup's questions.** When a release adds something an Admin needs to answer (a feature that's off until they turn it on, or a new choice), it goes in the setup: a new question in `QUESTIONS` in `app/setup.py`, with its step on the page (`SETUP_PAGES` in `app/web/index.html`); or, for a question that gains a choice, its version raised by one. After the update, the setup opens once by itself with just that question.

**The page at every screen size.** Before a release, `python tools/page_sizes.py /tmp/page-sizes` (it needs Playwright and Pillow) runs StationPlay with stand-in data and saves a screenshot of every tab and dialog at phone, tablet and computer sizes, light and dark, signed in as an Admin and as a User. It lists anything that scrolls sideways, is cut off, or is too small to tap.

**Releases.** Each release's notes are in `docs/releases/v<version>.md`, whose first lines name the commit of that version (`commit: <its full ID>`). When one is added to `main`, `.github/workflows/release.yml` publishes it on GitHub: the tag at that commit, the notes, and the release's files built from that commit (`stationplay-<version>.zip`, `stationplay.yaml` and `docker-compose.yml`). It checks that the commit is on `main` and is that version, leaves releases already published alone, and marks the newest as the latest.

### The logo library

The logos in `app/logos/` are drawn by code in `tools/logos/`, not by hand. `kit.py` is the drawing kit; `networks.py`, `classic_tv.py`, `tv_shows.py`, `movies.py`, `toons.py`, `kids.py`, `genres.py`, `themes.py`, `seasons.py` and `letters.py` design each group from the lettering, pictures (`symbols.py`) and layouts (`layouts.py`) there; and `build.py` draws them all with Chromium and writes the PNGs and `catalog.json`. Only the PNGs and `catalog.json` ship. The fonts are open-licensed (SIL Open Font License or Apache 2.0) and only needed to redraw the logos:

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
| `app/tsstitch.py` | Joins programs into one seamless MPEG-TS stream |
| `app/ffmpeg.py` | ffmpeg and ffprobe commands |
| `app/schedule.py` | Episode order, shuffle rules, and schedule and guide math |
| `app/playback.py` | Picture sizes, tuners, the "All tuners in use" card, and the speed test |
| `app/setup.py` | The setup: which questions an Admin is asked (all of them at first, then just the new ones after an update), and its checks |
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
| `app/ondemand.py`, `app/applibrary.py`, `app/catalog.py` | Your library on demand in StationPlay's apps |
| `app/languages.py` | Each person's languages in StationPlay's apps, and the sound and subtitles chosen from them |
| `app/converting.py`, `app/keyframes.py` | Copies of what a device can't play as it is: repackaged or converted, as HLS |
| `app/hdhr.py` | HDHomeRun and XMLTV formats |
| `app/breaks.py` | Commercials, trailers and Station ID cards |
| `app/intro.py` | Drawing the Intro Bumper and Station ID card, and their sound |
| `app/upnext.py` | The Up Next Banner |
| `app/bumpers.py` | Intro Bumper videos you upload |
| `app/backups.py` | Backups and restores |
| `app/access.py` | Sign-in, Admins and Users, and the access log |
| `app/viewing.py`, `app/ratings.py`, `app/titles.py` | Viewing Levels: what each person can see, ratings read as ages, and the ratings of what's on each station |
| `app/devices.py` | Linked devices, Who's tuning in?, passcodes and invite codes |
| `app/stats.py`, `app/watching.py` | Viewing stats, who's watching now, and matching Plex sessions to stations |
| `app/health.py` | The server's health for the Stats tab: processor, memory, network and storage, from Linux's own files |
| `app/alerts.py`, `app/notify.py` | Admin alerts, and notifying a web address of them |
| `app/playing.py` | What's playing, in words: how the log names stations, files and apps, and whose app is where |
| `app/limits.py` | Blocking stations for some Plex users |
| `app/logos.py`, `app/logos/` | The logo library and your own logos |
| `app/text.py`, `app/logbuffer.py` | Cleaning up names people type; recent log entries for the Logs tab |
| `app/assets/` | Sounds and other files the app draws with |
| `app/web/index.html`, `app/web/manifest.webmanifest` | The web page, and what installing it as an app takes (with its icons, made by `tools/app_icons.py`) |
| `tests/` | Unit and end-to-end tests |
| `Dockerfile`, `stationplay.yaml`, `docker-compose.yml` | The image, the TrueNAS app, and the Compose file |
| `docs/` | StationPlay's logo; StationPlay's API (`api.md`, `openapi-v1.json`); the apps' own addresses (`internal-api.md`); the designs of the library (`library.md`), of watching it on demand (`on-demand.md`), and of who sees what (`users.md`); each release's notes (`releases/`) |

## Contributing

Bug reports, ideas and fixes are all welcome. A good bug report says what you expected, what happened instead, and what the **Logs** tab showed at the time (its **Copy** button makes that easy).

Before sending a code change, run the tests and lint checks in [Development](#development), and add a test for anything new. StationPlay aims to be simple and reliable, to depend on nothing but Plex, and to use plain, friendly American English on its page and in its logs, where it says "station" rather than "channel". Changes that keep to those ideas are the easiest to accept.

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

This is only a summary; the [LICENSE](LICENSE) file is what applies. The packages StationPlay uses, and the fonts used to redraw its logos, keep their own licenses.
