<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-on-dark.svg">
    <img src="docs/logo-on-light.svg" alt="tapiOca: Stations &amp; Media" width="360">
  </picture>
</p>

> [!WARNING]
> ## tapiOca is in BETA
> Features are still being added and changed. Some of what this README describes hasn't shipped yet, and things may break between versions. **For testing only.**

# tapiOca: Stations & Media

tapiOca was called StationPlay until version 1.34.0.

tapiOca turns your own movies and shows, in Plex or in folders of your own, into always-on TV stations. Pick some shows or movies, give the station a number and a name, and it plays them around the clock like a broadcast station. It comes with a program guide. You can also add commercials, station IDs, a corner logo, movie nights and Saturday-morning blocks.

Watch them in tapiOca's own apps, in Jellyfin, Emby or Kodi, in Plex's **Live TV** guide on every Plex app (Plex sees tapiOca as an HDHomeRun network tuner), or in other apps on your home network.

tapiOca is free, open source and self-hosted (see [License](#license)). It runs in Docker on your own hardware and gets everything from your Plex server, or straight from [folders of your own](#media-folders-of-your-own), with no Plex at all. It needs no outside accounts or cloud services. It can tell you when a new version is out, if an Admin says yes: every 4 hours it asks GitHub, which sees your server's internet address, as any website does (see [Updating](#updating)).

If you find it useful, you can [buy me a coffee](https://buymeacoffee.com/egadgetboy).

## Contents

- [What you need](#what-you-need)
- [Install](#install): [TrueNAS SCALE](#truenas-scale) · [Docker Compose (Linux, Proxmox, Raspberry Pi)](#docker-compose-linux-proxmox-raspberry-pi) · [Synology](#synology) · [Unraid](#unraid) · [Windows and macOS](#windows-and-macos) · [docker run](#docker-run)
- [GPU encoding](#gpu-encoding) · [Backups](#backups) · [How tapiOca reads your files](#how-tapioca-reads-your-files) · [Security and remote access](#security-and-remote-access)
- [Updating](#updating): [Switching to the published image](#switching-to-the-published-image) · [Rolling back](#rolling-back)
- [Watch your stations](#watch-your-stations): Plex, Jellyfin, Emby, Kodi and other apps · [tapiOca's own apps](#tapiocas-own-apps) · [Unlocking the apps](#unlocking-the-apps)
- [Reaching tapiOca from outside your home](#reaching-tapioca-from-outside-your-home): a VPN, a reverse proxy, or a Cloudflare Tunnel
- [First-time setup](#first-time-setup): [The INFO station](#the-info-station)
- [Media folders of your own](#media-folders-of-your-own): shows and movies straight from your folders, with or without Plex
- [Making stations](#making-stations)
- [How stations play](#how-stations-play)
- [Station features](#station-features): logos, corner logo, Up Next Banner, Station ID card, commercials, Intro Bumper, subtitles, specials
- [Keeping stations on the air](#keeping-stations-on-the-air): safeguards, the Broken files list, file checks, Sonarr and Radarr, people's reports
- [Who can use tapiOca](#who-can-use-tapioca): [Trusted networks](#trusted-networks) · [Trusted proxies](#trusted-proxies) · [Names for tapiOca at home](#names-for-tapioca-at-home) · [Doors left open](#doors-left-open) · [When tapiOca can't see where connections come from](#when-tapioca-cant-see-where-connections-come-from) · [Viewing Levels](#viewing-levels) · [Parental limits](#parental-limits-what-tapioca-enforces-and-what-it-cant) · [Linked devices and Who's tuning in?](#linked-devices-and-whos-tuning-in) · [Tuner access](#tuner-access)
- [Stats](#stats) · [tapiOca's API](#tapiocas-api) · [Settings](#settings) · [Troubleshooting](#troubleshooting) · [Development](#development)
- [Contributing](#contributing) · [Forks and credit](#forks-and-credit) · [License](#license)

## What you need

- **If you use Plex: your own Plex Media Server, under Plex's terms.** [Plex's terms](https://www.plex.tv/about/privacy-legal/plex-terms-of-service/) license Plex Media Server for personal use, on hardware and storage you own. Use tapiOca with your Plex server as those terms allow. tapiOca's [privacy notice](PRIVACY.md) says what it keeps, what it contacts, and that it sends nothing to its developer.
- **Your shows and movies, in Plex Media Server or in folders of your own** (see [Media folders of your own](#media-folders-of-your-own)), or both. To watch in Plex, you need Plex, and **Plex Pass**, because Plex's Live TV & DVR feature requires it. Jellyfin, Emby, Kodi, other apps and tapiOca's own apps need neither.
- **A computer that runs Docker** on your home network (the same one as Plex, if you use it). It can be a NAS (TrueNAS SCALE, Synology, Unraid), a Linux server or virtual machine, a Raspberry Pi 4 or 5 with a 64-bit OS, or a Windows or Mac computer with Docker Desktop. Both x86-64 (Intel/AMD) and ARM64 work.
- **Access to your media folder** from that computer. tapiOca reads files directly from disk. If it can't see a file Plex has, it streams it from Plex instead, which works but adds load to Plex.
- **Enough processing power.** Each station being watched is converted in real time. A modern 4-core CPU can usually run several 720p stations at once. A GPU (Intel Quick Sync, AMD or NVIDIA) handles many more, and 1080p easily. tapiOca can't use the GPU in a Raspberry Pi or a Mac, so plan on one or two stations at smaller picture sizes there. **Test this server** on tapiOca's page measures what your hardware can do (see [Tuners](#tuners)).

## Install

### How installation works

tapiOca comes as a ready-made Docker image, `ghcr.io/egadgetboy/tapioca-server`, for x86-64 (Intel/AMD) and ARM64 machines. Each version's image is the exact one that passed its tests. Docker downloads it for you, so there's nothing to unzip or build.

You need just one file, which tells Docker how to run tapiOca:

| File | What it's for |
|---|---|
| `tapioca-server.yaml` | The app definition for TrueNAS SCALE (`stationplay.yaml` before 1.35.0). |
| `docker-compose.yml` | The app definition for Docker Compose, for everything else. |
| `unraid/stationplay.xml` | A template for Unraid's Docker tab. It's in the repo's `unraid` folder. |

Download the first two from the [latest release](https://github.com/egadgetboy/tapioca-server/releases/latest), under **Assets**. Both ask for `:latest`, the newest release. Docker downloads it when you install, and again only when you update (see [Updating](#updating)), so tapiOca never needs the internet to start. Each also sets `TAPIOCA_INSTALL`, which tells tapiOca's page how your kind of install updates. The steps below say what to set it to.

To build the image yourself instead, see [Building from source](#building-from-source).

**Before you start, gather four things:**

1. **Your Plex server's address**, such as `http://192.168.1.10:32400`. Use the server's network IP address, not `localhost`. Inside a container, `localhost` means the container itself.
2. **Your Plex token** (see the next section).
3. **Where your media lives** on the Docker host, such as `/mnt/tank/media`.
4. **The user tapiOca runs as**, written as `UID:GID` (numbers). This user must be able to read your media and write to tapiOca's data folder. The examples use `1000:1000`. To see who owns your media, run `ls -ln /path/to/media`. The third and fourth columns are the UID and GID.

#### Finding your Plex token

In Plex Web, open any movie or episode and choose **⋯ → Get Info → View XML**. The address of the page that opens ends with `X-Plex-Token=…`. That value is your token. Keep it private, because it gives full access to your Plex server. tapiOca never shows it on its page or in its logs.

### TrueNAS SCALE

Requires TrueNAS SCALE 24.10 (Electric Eel) or later, which has **Install via YAML**.

**1. Make tapiOca's data folder.** Choose a place on a pool, such as `/mnt/tank/apps/stationplay/data` (use your pool's name instead of `tank`). Paths in TrueNAS are case-sensitive, so `Data` and `data` are different folders. Open **System → Shell** and run:

```
sudo mkdir -p /mnt/tank/apps/stationplay/data
sudo chown -R 1000:1000 /mnt/tank/apps/stationplay/data
```

The `data` folder holds your stations and settings, so the user tapiOca runs as must own it (`1000:1000` here; see step 2).

**2. Install the app.** Go to **Apps → Discover Apps → ⋮ (top right) → Install via YAML**. Name the app `stationplay` and paste the contents of `tapioca-server.yaml`. Then change every line marked `<- CHANGE`:

- **The two folder paths:** the `data` folder and your media folder. On each `volumes` line, change only the folder on your server, the part before `:/data` or `:/media`, such as `/mnt/tank/media:/media:ro`. Leave `MEDIA_DIR` as `/media`: that's where tapiOca sees the folder.
- **Plex and time zone:** `PLEX_URL`, `PLEX_TOKEN` and `TZ` (your time zone, such as `America/Chicago`).
- **The user:** change `user:` if your media belongs to another user. TrueNAS's built-in apps user is `568:568`. If you use it, also run `sudo chown -R 568:568 /mnt/tank/apps/stationplay/data`.

Leave `TAPIOCA_INSTALL` set to `truenas`. Also check the GPU lines (see [GPU encoding](#gpu-encoding)). The Intel/AMD lines are turned on in this file. If the server has no Intel or AMD graphics, delete them, or the app won't start.

Save. TrueNAS downloads the image and starts tapiOca.

**3. Open** `http://<your-nas-ip>:3310` in a browser. The [first-time setup](#first-time-setup) starts.

### Docker Compose (Linux, Proxmox, Raspberry Pi)

This works on any Linux machine with Docker and the Compose plugin. That includes Ubuntu, Debian, a Proxmox VM or LXC container, a Raspberry Pi with a 64-bit OS, and most NAS systems with a terminal.

```
mkdir -p ~/stationplay && cd ~/stationplay
curl -fLO https://github.com/egadgetboy/tapioca-server/releases/latest/download/docker-compose.yml
mkdir -p data && sudo chown -R 1000:1000 data      # use your UID:GID
```

(Or download `docker-compose.yml` from the [latest release](https://github.com/egadgetboy/tapioca-server/releases/latest) in a browser, and put it in that folder.)

Open `docker-compose.yml` in a text editor and change every line marked `<- CHANGE`: the user, Plex's address, your Plex token, your time zone and your media folder. Leave `TAPIOCA_INSTALL` set to `compose`. For a GPU, uncomment its lines (see [GPU encoding](#gpu-encoding)). Then start tapiOca:

```
docker compose up -d
```

Docker downloads the image and starts it. Open `http://<server-ip>:3310`. Updates never change your `docker-compose.yml`: they only fetch a newer image.

- **On Proxmox.** Run Docker in a VM or an LXC container, then follow these steps. To use an Intel or AMD GPU from an LXC container, first pass `/dev/dri` through to it in Proxmox. Your media must be mounted inside the VM or container.
- **On a Raspberry Pi.** Use a 64-bit OS. The Pi's GPU can't be used for encoding, so tapiOca encodes on the CPU. Start with the 480p picture size.

### Synology

Requires DSM 7.2 or later with **Container Manager** (from Package Center).

1. In **Control Panel → Terminal & SNMP**, turn on SSH.
2. In **File Station**, create a folder such as `/volume1/docker/stationplay`, with a `data` folder inside it. Download `docker-compose.yml` from the [latest release](https://github.com/egadgetboy/tapioca-server/releases/latest) and upload it to `/volume1/docker/stationplay`.
3. Connect over SSH and find your user's IDs with `id`. You'll see something like `uid=1026(you) gid=100(users)`. Use those numbers so tapiOca can read your media:

   ```
   cd /volume1/docker/stationplay
   sudo chown -R 1026:100 data
   ```

4. Edit `docker-compose.yml` in File Station or a text editor. Set `user: "1026:100"` (your numbers), set `TAPIOCA_INSTALL` to `"synology"`, and change the other lines marked `<- CHANGE`. Your media folder is usually under `/volume1/`, such as `/volume1/video`.
5. In **Container Manager**, open **Project** and choose **Create**. Name it `stationplay`, choose `/volume1/docker/stationplay` as its path, and use the `docker-compose.yml` that's there. Finish, and Container Manager downloads the image and starts tapiOca.

   If you'd rather use SSH, run `sudo docker compose up -d` in that folder instead. Either way, tapiOca updates over SSH (see [Updating](#updating)).

   On older systems where `docker compose` isn't found, use `docker-compose`, with a hyphen, in its place, here and in the steps for updating and rolling back. To update, run `sudo docker-compose pull`, then `sudo docker-compose up -d`.

Intel-based Synology models with built-in graphics can use the GPU. Uncomment the Intel/AMD lines (see [GPU encoding](#gpu-encoding)).

### Unraid

The simplest way is tapiOca's template, from the repo's `unraid` folder. You can also set it up from the compose file (below).

1. Open the terminal (the `>_` icon). Make tapiOca's data folder, owned by Unraid's standard `nobody:users` (`99:100`, which owns your shares), and add the template:

   ```
   mkdir -p /mnt/user/appdata/stationplay/data
   chown -R 99:100 /mnt/user/appdata/stationplay/data
   curl -fL -o /boot/config/plugins/dockerMan/templates-user/my-stationplay.xml \
     https://raw.githubusercontent.com/egadgetboy/tapioca-server/main/unraid/stationplay.xml
   ```

2. On the **Docker** tab, choose **Add Container**, and pick **stationplay** under **Template**. That's the container's name, as on every other kind of install.
3. Fill in Plex's address, your Plex token, your time zone and your media folder (such as `/mnt/user/media`). The data folder is already `/mnt/user/appdata/stationplay/data`, the same folder a compose install there uses. Leave `TAPIOCA_INSTALL` set to `unraid`. The template runs tapiOca as `99:100`: to change that, turn on **Advanced View** and edit `--user` under **Extra Parameters**.
4. Choose **Apply**. Unraid downloads the image and starts tapiOca.

**With the compose file instead.** From the **Apps** tab, install the **Compose Manager** plugin, which adds the `docker compose` command. Then follow the [Docker Compose](#docker-compose-linux-proxmox-raspberry-pi) steps in `/mnt/user/appdata/stationplay`, with `user: "99:100"` and `chown -R 99:100 data`. Set `TAPIOCA_INSTALL` to `"compose"`, since you'll update it with `docker compose`, not from the Docker tab.

For an Intel GPU, the `/dev/dri` folder must exist on the server. Unraid loads the Intel driver for most Intel graphics. In the template, turn on **Advanced View** and set **GPU** to `/dev/dri`. If the **Video encoding** line names a group tapiOca needs, add `--group-add <that number>` to **Extra Parameters**. See [GPU encoding](#gpu-encoding).

### Windows and macOS

tapiOca runs in **Docker Desktop**. The computer must stay on and awake for your stations to play.

1. Install Docker Desktop and start it.
2. Make a folder, such as `C:\tapioca` or `~/tapioca`, with a `data` folder inside it. Download `docker-compose.yml` from the [latest release](https://github.com/egadgetboy/tapioca-server/releases/latest) into that folder.
3. Edit `docker-compose.yml`:
   - Delete the `user:` line. Docker Desktop manages file permissions itself.
   - Set `TAPIOCA_INSTALL` to `"docker-desktop"`.
   - Set your media folder with forward slashes, such as `D:/Media:/media:ro` on Windows or `/Users/you/Movies:/media:ro` on a Mac.
   - Change the other lines marked `<- CHANGE`.
4. In a terminal (PowerShell on Windows), go to that folder and run `docker compose up -d`.

Allow port 3310 through the computer's firewall if it asks. Docker Desktop can't use Intel or AMD graphics. On Windows, an NVIDIA GPU works through WSL 2 (see [GPU encoding](#gpu-encoding)). A Mac always encodes on the CPU.

If Plex runs on Windows, tapiOca can't translate its Windows file paths (such as `D:\TV\…`). It streams those files from Plex instead, which works but adds load to Plex.

### docker run

If you don't use Compose, start the container yourself. Make a folder for tapiOca with a `data` folder inside, and run this from that folder, with your own settings:

```
mkdir -p data && sudo chown -R 1000:1000 data      # use your UID:GID
docker run -d --name stationplay --restart unless-stopped --init \
  --user 1000:1000 \
  -p 3310:3310 \
  -p 3311:3311 \
  -e TAPIOCA_INSTALL=docker-run \
  -e PLEX_URL=http://192.168.1.10:32400 \
  -e PLEX_TOKEN=paste-your-plex-token-here \
  -e TZ=America/Chicago \
  -e PORT=3310 \
  -e PUBLIC_PORT=3311 \
  -e MEDIA_DIR=/media \
  -e HW_ACCEL=auto \
  -v "$PWD/data:/data" \
  -v /path/to/your/media:/media:ro \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --log-opt max-size=10m --log-opt max-file=3 \
  ghcr.io/egadgetboy/tapioca-server:latest
```

Save your command in a file (such as `stationplay.sh`). You'll run the same one each time you update.

- **The page and apps from the internet.** The `3311` port and `PUBLIC_PORT` are for that (see [Security and remote access](#security-and-remote-access)). If you don't need it, remove `-p 3311:3311` and `-e PUBLIC_PORT=3311`.
- **Intel or AMD GPU.** Add `--device /dev/dri:/dev/dri --group-add <group number>` (see [GPU encoding](#gpu-encoding)).
- **NVIDIA GPU.** Add `--gpus all` (needs the NVIDIA Container Toolkit).

Keep `--restart unless-stopped`. Restoring a backup restarts tapiOca, and Docker must start it again.

### GPU encoding

A GPU makes tapiOca much lighter on your server and lets more stations play at once, including at 1080p. tapiOca supports Intel and AMD graphics through VA-API (including the Quick Sync graphics built into most Intel Core CPUs) and NVIDIA graphics through NVENC. When the GPU supports a file's format, it decodes the file too. It also makes the converted copies for tapiOca's apps (see [tapiOca's own apps](#tapiocas-own-apps)).

At startup, tapiOca test-encodes a short clip with the exact command it uses for real programs. It uses the first GPU that passes, trying NVIDIA first and then each Intel/AMD device. If none passes, it encodes on the CPU. The **Video encoding** line on the **Setup** tab shows which is in use, and why when it's the CPU.

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
- **Copies fall back too.** A copy for tapiOca's apps that fails on the GPU carries on from the same point on the CPU and stays there. The viewer sees only the usual wait.
- **A failing GPU is set aside.** If 3 programs in a row fail on the GPU but play on the CPU, tapiOca stops using the GPU until it restarts. Copies count separately. If 3 in a row fail this way, only copies move to the CPU.
- **Stalls don't count.** A program that stalls on the GPU also moves to the CPU, but a slow disk causes stalls too, so they never count against the GPU.
- **The "We'll be right back" card** is always made on the CPU, so it works even if the GPU doesn't.

`HW_ACCEL` chooses the encoder: `auto` (default), `nvidia`, `intel` or `amd` (both mean VA-API), or `cpu`. With more than one GPU, `HW_DEVICE` picks one: a render node such as `/dev/dri/renderD129`, or an NVIDIA GPU number.

### Backups

tapiOca backs itself up automatically: about 15 minutes after it first starts, then every night at about 3 AM (in your `TZ` time zone). It keeps the newest 7 backups in `data/backups`. The database copies made before updates are kept there too, separately from these (see [Rolling back](#rolling-back)).

A backup includes your stations and their schedules, all settings, the Broken files list, the tuner's identity (so Plex still recognizes it), your logos (uploaded or from Plex), users and their passwords (stored only as hashes) and viewing stats. Intro Bumper videos aren't included, to keep backups small. They stay in `data/bumpers`, and a restore leaves them alone.

On the **Setup** tab:

- **Download a backup** makes a backup now and downloads it. It's also saved in `data/backups` and counts toward the 7 kept.
- **Restore a backup…** replaces everything above with the backup's copy. tapiOca checks the file, restarts and puts the backup in place as it starts. First it saves what you had as a separate "before restore" backup, in case you change your mind.

After a restore, everyone signs in again as the users in the backup. A backup with no users turns sign-in off, so tapiOca asks before restoring one while sign-in is on.

### How tapiOca reads your files

tapiOca asks Plex where each file is, then reads it straight from disk. Plex reports paths as its own container sees them, such as `/data/tv/Show/episode.mkv`. You don't need to match those paths. Mount your media at `/media` (as the YAML and Compose files do), and tapiOca finds each file by matching the end of Plex's path inside `/media`. At least the file name and its folder must match. Once a match works, tapiOca reuses it for every other file. The **Media files** line on the **Setup** tab shows whether files are read directly.

If tapiOca can't see a file, it streams it from Plex instead, which works but adds load to Plex. For unusual layouts, set the translation yourself with `PATH_MAPPINGS` under `environment:`. For example, `PATH_MAPPINGS: "/data/media:/media"` means "where Plex says `/data/media/…`, read `/media/…`". If Plex runs in Docker, use the paths inside Plex's container. Separate several pairs with `;`.

If your media share takes more than 8 seconds to answer, tapiOca treats it as temporarily unavailable. It skips those programs for now, without marking them broken.

### Security and remote access

**Keep port 3310 on your home network.** It serves Plex's tuner, guide and video streams, which never ask for a password, because Plex can't sign in to a tuner. Never forward it on your router or point a tunnel or reverse proxy at it. If that happens anyway, tapiOca treats those connections as from the internet and alerts Admins (see [Doors left open](#doors-left-open)). Plex only needs it inside your network. Plex users away from home can still watch, because Plex relays the stream. To choose which devices at home can use it, see [Tuner access](#tuner-access) on the **Access** tab.

**Using tapiOca's page and apps from the internet.** tapiOca can open a second port for its page and for tapiOca's apps away from home, set with `PUBLIC_PORT`. It's 3311 in the YAML and Compose files, and it must differ from `PORT`. On that port:

- **No Plex addresses.** The addresses Plex and other apps use (the tuner, guides, streams and playlist) don't exist there.
- **Sign-in always required.** Before signing in, visitors see only the sign-in page, its icons, what a browser needs to install the page as an app (see **As an app** under [First-time setup](#first-time-setup)), tapiOca's name and version, its open-source notices and its privacy notice. tapiOca's apps also ask it the server's name, its away-from-home address and which features are on, to connect. Until signing in is on, the page there says only "This tapiOca client can't reach the server. Please check back later.", as tapiOca's apps do, and no one can sign in or make themselves the first Admin from outside.
- **Wrong passwords limited.** The limits are 5 in 15 minutes per address, and 100 in 15 minutes for the internet as a whole. tapiOca knows a visitor's own address only through a [trusted proxy](#trusted-proxies) or Cloudflare's own network. Otherwise it counts the address that connected, so through a proxy you haven't listed, every visitor shares the proxy's address. A browser or app that has signed in before isn't held up by the internet-wide limit.

Put `PUBLIC_PORT` behind a Cloudflare Tunnel or a reverse proxy with HTTPS. [Reaching tapiOca from outside your home](#reaching-tapioca-from-outside-your-home) explains each, and the other ways in. If you don't need it, remove the `3311` port line and `PUBLIC_PORT`.

**Built-in protections, however tapiOca is reached:**

- **Plex.** The page can't send its own requests to Plex. tapiOca makes only the requests it needs (details of your movies and shows, guide refreshes, folder scans and stopping blocked playback), so no one can misuse your Plex token through it. The page never sees the token or Plex's address.
- **Uploads.** A logo is accepted only as a PNG, JPEG, WebP, GIF or BMP image, and an Intro Bumper only as a video file. Each is turned into a clean copy before use. The limits are 500 of your own logos, 50 Intro Bumper videos, and no upload that would leave less than 2 GB free on the data folder's disk.
- **The page.** It runs only its own scripts, can't be embedded in another site, and refuses changes sent from other sites. Every change it makes carries a header only tapiOca's own page sends (`X-Tapioca-Page`), so another site's page can't make one, even at home over plain http, with sign-in off or an Admin signed in. The same goes for anything a browser sends to the API's or the apps' addresses. Scripts and apps send no browser headers and aren't affected.
- **Backups.** tapiOca restores a backup only if it's a genuine tapiOca backup. Anything unexpected is refused before anything changes.

## Updating

**tapiOca's page can tell you when a new version is out,** if an Admin says yes (see **The update check** below). Admins then see a banner at the top: "tapiOca 1.35.0 is available." It shows the steps for your kind of install (from `TAPIOCA_INSTALL`), with **What's new** (the release's notes), **Back up now**, **All the steps** (this section) and **Not now**, which hides the banner for that version in this browser. While a newer version is out, Admins also see a small **tapiOca 1.35.0 is out** pill in the page's header (just **Update** on a phone), even after **Not now**. Choose it to see the banner again, with how to update. tapiOca never downloads or updates anything by itself.

Your stations, settings, logos, Intro Bumper videos and Broken files list live in the `data` folder, so updates keep them. Existing stations keep their settings. New defaults apply only to stations you make afterward. The version you're running is shown at the bottom of tapiOca's page.

**How each kind of install updates.** Back up first (**Back up now** on the banner, or **Download a backup** on the **Setup** tab). Then:

| Install | To update |
|---|---|
| TrueNAS SCALE | In TrueNAS, open **Apps**, then **stationplay**. If it offers **Update**, choose it. If it doesn't, open **System**, then **Shell**, and run `sudo docker pull ghcr.io/egadgetboy/tapioca-server:latest`. Then open **Apps**, choose **stationplay**, and choose **Edit**, then **Save**. These TrueNAS steps haven't been confirmed yet. If tapiOca still shows the old version afterward, see [Troubleshooting](#troubleshooting). |
| Docker Compose | In the folder with tapiOca's `docker-compose.yml`, run `docker compose up -d --pull always`. |
| Docker Desktop | In a terminal (PowerShell on Windows), in the folder with tapiOca's `docker-compose.yml`, run `docker compose up -d --pull always`. |
| Unraid | On Unraid's **Docker** tab, choose **Check for Updates**. When **stationplay** shows an update, choose **apply update**. |
| Synology | Connect over SSH, go to tapiOca's folder (such as `/volume1/docker/stationplay`), and run `sudo docker compose up -d --pull always` (on older systems, `sudo docker-compose pull`, then `sudo docker-compose up -d`). Container Manager's own way (open **Project**, choose the stationplay project, then **Stop** and **Build**) hasn't been confirmed yet to fetch the newest image, so these steps haven't been confirmed yet either way. |
| docker run | Fetch the newest image, then remove the container and start it again with the same `docker run` command as before (see [docker run](#docker-run)). |

For `docker run`, that's these two commands:

```
docker pull ghcr.io/egadgetboy/tapioca-server:latest
docker rm -f stationplay
```

then your `docker run` command. Removing the container keeps your data, because it's in the `data` folder.

**Staying on one version.** `:latest` is always the newest release. To stay on one, change the end of `image:` (on Unraid, **Repository**; with `docker run`, the last line):

- `ghcr.io/egadgetboy/tapioca-server:1.34` gets fixes for 1.34 (1.34.1, 1.34.2 and so on), but not 1.35.
- `ghcr.io/egadgetboy/tapioca-server:1.34.0` stays on exactly 1.34.0.

The update steps above then fetch only what that tag allows. Change it back to `:latest` to follow every release again. Images are published from 1.34.0 on.

**The update check.** If an Admin says yes, tapiOca asks GitHub every 4 hours whether a newer version is out. GitHub sees your server's internet address when it asks, as any website does. tapiOca sends only its version. It asks nothing until an Admin answers: first-time setup asks in its last step, and the page asks once after an update from before 1.34.0. Until then, and while it's off, tapiOca doesn't contact GitHub. An Admin can change the answer under **New versions** on the **Setup** tab (**Tell me when a new tapiOca is out**), where **Check now** looks right away.

**A database copy before each change.** Starting with 1.29.1, before an update changes tapiOca's database, tapiOca copies it, sign-ins included, to `data/backups` as `before-<version>-<date>.db` (such as `before-1.29.1-20261009-153000.db`). It notes this on the **Logs** tab, then makes the change. The newest 3 copies are kept. If it can't make the copy (because the disk is full, for example), it changes nothing and stops. Its log (`docker logs stationplay`, or the app's logs on TrueNAS) shows why. Make room, then start it again.

### Switching to the published image

Before 1.34.0, tapiOca was built on your own machine from the release's zip. From 1.34.0 on, it comes as a ready-made image. If you built it before, switch once:

1. **Make a backup.** On the **Setup** tab, choose **Download a backup**.
2. **Edit your YAML or compose file.** On TrueNAS, open **Apps**, then **stationplay**, and choose **Edit**. Then:
   - Delete the `build:` block: the `build:` line and the lines indented under it (`context:` and `dockerfile:`).
   - Change `image:` to `ghcr.io/egadgetboy/tapioca-server:latest`.
   - Add `TAPIOCA_INSTALL` under `environment:`, set to how you update (see [Updating](#updating)). On TrueNAS, set it to `"truenas"`. With Docker Compose on Linux, set it to `"compose"`, and with Docker Desktop, `"docker-desktop"`. On Synology, set it to `"synology"`: you installed it over SSH, and it updates that way. On Unraid, set it to `"compose"`: you installed it with the Compose Manager plugin, and it updates with `docker compose`.
3. **Leave everything else as it is:** your Plex token, folders, user, ports and GPU lines.
4. **Save it in TrueNAS,** or run `docker compose up -d` in the compose file's folder. On Synology, connect over SSH and run `sudo docker compose up -d` there.

The top of the file then looks like this:

```
services:
  stationplay:
    image: ghcr.io/egadgetboy/tapioca-server:latest
    container_name: stationplay
    ...
    environment:
      TAPIOCA_INSTALL: "truenas"
```

The data folder doesn't change, so your stations, settings and people carry over. Afterward, you can delete the `src` folder.

With `docker run`, run `docker rm -f stationplay`, then the [docker run](#docker-run) command with your own settings. Leave out `-p 3311:3311` and `-e PUBLIC_PORT=3311` unless you used them before, to reach tapiOca's page or apps from away from home.

### Rolling back

To go back to the version you had before an update:

1. **Stop tapiOca.** On TrueNAS, open **Apps** and choose **Stop** on stationplay. With Docker Compose, run `docker compose stop` in its folder. With docker run, run `docker stop stationplay`. On Unraid, stop it on the **Docker** tab, and on Synology, stop its project in Container Manager.
2. **Restore the database from before the update.** In the data folder, replace `stationplay.db` with the copy made before the update (the newest `before-<new version>-<date>.db` in `backups`). Delete `stationplay.db-wal` and `stationplay.db-shm` if they're there:
   ```
   cd /mnt/tank/apps/stationplay/data
   sudo cp backups/before-1.29.1-20261009-153000.db stationplay.db
   sudo rm -f stationplay.db-wal stationplay.db-shm
   ```
   In PowerShell (Docker Desktop on Windows), in the data folder:
   ```
   Copy-Item backups\before-1.29.1-20261009-153000.db stationplay.db
   Remove-Item stationplay.db-wal, stationplay.db-shm -ErrorAction SilentlyContinue
   ```
   Use your own folder and the copy's name. Copying over the old file keeps its owner, so tapiOca can still write to it.
3. **Ask for the previous version's image.** Change the end of `image:` from `:latest` to that version, such as `ghcr.io/egadgetboy/tapioca-server:1.34.0`, and start it. On TrueNAS, edit the app and save it, then start it if it doesn't start by itself. With Docker Compose, run `docker compose up -d`. On Unraid, edit the container's **Repository** and apply. On Synology, edit `docker-compose.yml`, then connect over SSH and run `sudo docker compose up -d` in its folder. With docker run, run `docker rm stationplay`, then your `docker run` command with that version at the end.

It stays on that version until you change `image:` back to `:latest`. Images are published from 1.34.0 on. To go back to an earlier version, build it from its zip (see [Building from source](#building-from-source)).

Everyone stays signed in. Stations, settings and people return to how they were just before the update, and anything changed since then is lost. If the update didn't change the database, it made no copy, so skip step 2.

**Going back further?** Older versions don't know newer settings and may play some programs incorrectly. Before downgrading below 1.8, delete stations made from Plex collections, set **In the corner** to something other than **Clock**, and set each **Station ID card** to **Off** or **10 sec**. Below 1.6, also set **Commercials & trailers** to **None** and the **Station ID card** to **Off**. Below 1.4, also set **Intros & credits** to **Play them**. Wait for each change to take effect at the next program break before downgrading.

## Watch your stations

tapiOca offers your stations in two ways at once, on your home network:

| For | Address |
|---|---|
| Plex (as an HDHomeRun tuner) | Tuner: `http://<server-ip>:3310`<br>Guide: `http://<server-ip>:3310/xmltv.xml` |
| Jellyfin, Emby, Kodi and other apps | Playlist: `http://<server-ip>:3310/stations.m3u`<br>Guide: `http://<server-ip>:3310/guide.xml` |

**Tuner integration**, on the **Setup** tab, shows these addresses with **Copy** buttons. Station numbers and logos come with them. You can watch in as many apps as you like. Everyone watching the same station shares one stream.

### In Plex

Plex won't add a tuner whose guide has no stations. A new tapiOca starts with the INFO station on 99, so you can add it to Plex before you've made a station of your own (see [The INFO station](#the-info-station)).

1. In Plex, open **Settings → Live TV & DVR → Set Up Plex DVR**.
2. Choose **Don't see your HDHomeRun device? Enter its network address manually** and enter the tuner address, `http://<server-ip>:3310`. Plex doesn't find tapiOca on its own.
3. When Plex asks for guide data, choose **Have an XMLTV guide on your server? Click here to use it** and enter `http://<server-ip>:3310/xmltv.xml`.
4. Continue. Plex matches your stations automatically (Plex calls them channels), and they appear under **Live TV**.

After that, tapiOca keeps Plex's guide up to date. Whenever a station changes, it asks Plex to refresh the guide. The **Guide updates** line on the **Setup** tab shows whether that's working. If it isn't, refresh the guide yourself in **Settings → Live TV & DVR → your tuner → Refresh Guide**.

**After you create a new station,** choose **Scan for channels** in Plex's Live TV & DVR settings so Plex adds it.

**Plex Home and managed users.** To see your stations, a user's Live TV & DVR access must be **Allow Live TV and DVR access**. With "Allow Live TV only", Plex doesn't show them stations from a tuner.

### In Jellyfin

1. In the dashboard, open **Live TV** and choose **+** next to **Tuner Devices**.
2. Choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`. Save.
3. Choose **+** next to **TV Guide Data Providers**, choose **XMLTV**, and enter `http://<server-ip>:3310/guide.xml`. Save.

Leave Jellyfin's limit on simultaneous streams at its default (no limit). tapiOca enforces its own.

### In Emby

Emby's Live TV requires Emby Premiere.

1. In Emby's settings, open **Live TV** and add a TV source. Choose **M3U Tuner** and enter `http://<server-ip>:3310/stations.m3u`.
2. Add a guide data provider. Choose **XMLTV** and enter `http://<server-ip>:3310/guide.xml`.

### In Kodi

1. Install Kodi's PVR Simple Client add-on (**Add-ons → Install from repository → PVR clients**).
2. In its settings, set the playlist location to remote and set **M3U play list URL** to `http://<server-ip>:3310/stations.m3u`. The playlist includes the guide's address, so **XMLTV URL** can stay empty. You can also enter `http://<server-ip>:3310/guide.xml` there.
3. Restart Kodi, or turn the add-on off and on. Your stations appear under **TV**.

### In other apps

Channels DVR and VLC accept the playlist address, `http://<server-ip>:3310/stations.m3u`. The playlist includes the guide's address.

**HLS players.** Each station is also available as HLS, the format used by Safari, iPhones, iPads, Apple TV and many other players: `http://<server-ip>:3310/hls/<station number>/index.m3u8`. It shares the station's one stream with everyone else watching, so a station never takes a second tuner. The HLS stream runs only while a player is asking for it. It stops 30 seconds after the last player stops asking, or right away when tapiOca's own apps tune away.

**Keeping other apps' guides current.** These apps download the guide on their own schedule, usually once a day. When you change a station, refresh the guide in the app (in Jellyfin, **Dashboard → Scheduled Tasks → Refresh Guide**). Otherwise the app shows that station's old schedule until its next refresh. Changes such as new episodes wait until the guide these apps downloaded runs out, so it stays right (see [Updates to stations](#updates-to-stations)). With Plex, they take effect when Plex downloads its guide, and an app that refreshes less often may briefly show an older schedule.

**Away from home.** These addresses only work on your home network. Plex users away from home watch through Plex as usual. Other apps must be on your network or reach it over a VPN.

### tapiOca's own apps

**tapiOca for Android** is a beta test build, in private testing. It isn't in any app store yet. The Apple app and the Roku app are coming. The apps connect directly to your tapiOca server, so you can watch your stations without Plex Pass or any other app.

- **Platforms.** In private testing: Android phones, foldables and tablets, Google TV and Android TV, in tapiOca for Android. Coming: iPhone, iPad and Apple TV, and Roku.
- **A guide for every screen.** On a TV, you browse it with your remote. On a phone, you see every station at a glance and swipe through the hours. On a tablet, the selected program and a live picture sit above the guide.
- **Changing stations.** While a station tunes in, you see its card in the same colors as its Intro Bumper. Flip up and down through your stations, enter a station number on your remote, or jump back to the last station you watched. If every tuner is in use, the app says so and lets you join a station that's already playing.
- **Favorites.** Mark the stations you watch most, and choose to show only those in the guide.
- **Night mode.** It brings loud scenes down close to the voices, so you can watch late without disturbing anyone. It only ever turns sound down: loud scenes the most, voices only a little, and nothing gets louder, so there's no need to change the volume. From 1.36.4, it also cuts deep rumble, under 50 Hz. Some devices can't change the sound themselves (Apple's player, a Roku). For those, tapiOca makes the station's night-mode sound on the server, only while someone is watching that way. The picture is copied unchanged, it uses the station's one tuner, and everyone else keeps the usual sound.
- **Sleep timer.** Choose 15 minutes to 2 hours, a clock time, or your own number of minutes, from anything playing. In the last 30 seconds, the picture fades to black. Then playback stops and the screen stays dark until you press a button, so the TV or device can go to sleep.
- **Phone and tablet extras.** Keep watching in picture-in-picture, choose whether the picture fits or fills the screen, and send it to your TV with AirPlay (Apple) or Cast (Android).
- **Secure sign-in.** On a TV, the app shows a short code. You enter it on tapiOca's page from your phone or computer, so you never type a password with a remote. The dash in the code fills in by itself as you type. On a phone or tablet, you can use your name and password instead. Every signed-in app appears under **Signed-in apps** on the **Access** tab, where an Admin can sign it out.
- **Watching away from home.** When an Admin turns this on, the apps also work away from home, for stations and Media alike. They connect over HTTPS through the same reverse proxy that serves tapiOca's page (see [Reaching tapiOca from outside your home](#reaching-tapioca-from-outside-your-home)).
- **Built for stability.** An Admin sets how many devices can watch at once, including how many away from home. tapiOca tests what your server and internet connection can handle and recommends limits. When a limit is reached, the app explains why and asks the viewer to try again later.
- **Media.** Browse your shows and movies by title, genre, what's new or what you haven't watched. Jump to a letter, search, and pick up where you left off from the Resume row. Each title's page shows its cast and crew and titles like it. Skip an episode's intro and credits with one button, and choose subtitles and audio tracks.
- **The best picture and sound.** Each device gets the best picture and sound it supports, including Dolby Vision and Dolby Atmos. A file is repackaged or converted only when a device can't play it directly.

**Which tapiOca the apps need.** The apps need tapiOca 1.22.0 or newer. With an older version, the app says so: "The tapiOca at … is version …, but this app needs 1.22.0 or newer." For every feature, use the newest version:

| tapiOca | What the apps gain |
|---|---|
| 1.22.0 | The minimum |
| 1.28.0 | PINs |
| 1.29.0 | Languages and Admin alerts |
| 1.29.1 | A converted copy of a file the device can't play, and more detail on problems |
| 1.30.0 | Report a problem |
| 1.34.0 | Automatic subtitles |

The apps read the stations and guide through [tapiOca's API](#tapiocas-api), like any other program. They sign in, test connections and browse Media through their own addresses, documented for the apps in [docs/internal-api.md](docs/internal-api.md).

**Sharing Media with the apps.** Every Media folder of shows and movies is shared with the apps to start, and so are Media folders added later. That lasts until an Admin saves a choice, on the **Access** tab under **Media in tapiOca's apps**, or in the setup. Untick any you'd rather keep out. A choice is kept, even none, and then the apps show no Media. Viewing Levels still decide what each person sees. Stations, Plex, Jellyfin and other apps aren't affected.

A tapiOca updated from before 1.34.1 that never saved a choice shared no Media folders, and it still shares none until an Admin chooses. The setup asks about Media once, with every Media folder ticked: going on from that step shares them.

- **Your own Resume row.** Each person who signs in has their own Resume row, resume points and watched list. While sign-in is off, everyone shares one.
- **Limits apply.** Programs played from Media count toward the limit on devices watching at once.
- **One listing per title.** A title with several versions (4K and 1080p, say) is listed once. Each device plays the best version it can.
- **When playback can't keep up.** If playback keeps stalling, even with the buffer, the app tests the connection to find out why. It then offers a smaller version from where you are, or switches by itself, as you choose on the Access tab.
- **Copies only when needed.** A file plays unchanged whenever the device can play it. Otherwise tapiOca makes a copy as it plays, and the app can seek anywhere in it. A repackaged copy keeps the picture and converts only the sound, which costs almost nothing.
- **Converted copies.** A converted copy remakes the picture at up to 1080p in standard color. This uses the server's processor, so at most 3 are converted at once, or 6 with a GPU, which is light on the processor.
- **What else copies do.** A copy draws in subtitles the device can't show itself. It also makes a smaller picture when the connection can't keep up with any version.
- **Movies in several files.** A movie Plex keeps in several files ("cd1" and "cd2") plays as one program with their combined length. Resume, progress, seeking and watched status cover the whole movie. It plays as a copy that joins the files, repackaged when their pictures are alike (nearly always) and converted when they're not. Apps that predate the copies in tapiOca 1.24.0 can't play such a movie, and say so.
- **Where it plays.** Media plays on your home network or through a VPN. While **tapiOca's apps away from home** is on, it also plays through the public port.

The design is in [docs/on-demand.md](docs/on-demand.md).

**Media away from home.** With **tapiOca's apps away from home** on, Media plays away from home just as it does at home, for everyone signed in. Viewing Levels and the limits on devices watching still apply, and a device away from home also counts against the away-from-home limit. Under **tapiOca's apps away from home** on the Access tab, **Media away from home** sets the quality:

- **Original** (the default) plays each title as it would at home.
- **Up to** a number of Mbps (1 to 200) plays titles within that rate as at home. A file that needs more is converted down to fit, at most 1080p, and counts toward the copies converted at once.

The panel shows your home's upload speed, as tapiOca's apps measured it from outside. When a connection can't keep up, the apps still step down by themselves.

The video stream itself needs no sign-in. Each title an app plays through the public port gets its own random address, far too long to guess. It works only for a title started there, only over HTTPS, and only while that app's sign-in lasts. A title started at home is never offered there.

**Even sound for a show's episodes.** Episodes played from Media in tapiOca's apps play at the same loudness as the episodes on your stations (−24 LUFS). A show's episodes match in any order and in any app. Movies are never changed. Only the sound is remade (a repackaged copy, which costs almost nothing). With night mode on too, even sound is applied first. If the picture can't be kept unchanged, the episode plays unchanged instead.

Even sound is on by default. To keep each episode's original sound, such as Dolby Atmos or DTS sent on to a receiver, turn off **Even sound for a show's episodes** on the Access tab, under **Media in tapiOca's apps**. With it on, that sound plays as ordinary 5.1 or stereo. Apps that predate the copies in tapiOca 1.24.0 get each file unchanged.

**Languages.** Each person chooses their sound language and subtitles in an app's Options. tapiOca saves the choices, so they follow that person to every device. Subtitles are **Automatic** to start: they show in your language when the sound is in another (your Subtitles language if you choose one, else your device's language). Choose **On** to always have them, or **Off** for only the parts meant to be read. From the player, a person can choose differently for one episode or movie, or for a whole show with **Sticky Audio & Subtitles**: what you pick holds for every episode of that show.

tapiOca uses the most specific choice: the episode's or movie's, then the show's, then the person's own, then the file's default. It picks sound in their language, never a commentary track when there's another. With subtitles on, it picks their language, preferring a full track over a forced one. With subtitles off, it shows only forced subtitles, for parts in another language.

Subtitles the device can't show are drawn into a copy. If an episode's chosen subtitles are inside its file and the device can show them, the episode plays unchanged instead of with even sound, because a copy carries no subtitles. Someone who hasn't chosen anything gets each file as before. Stations don't use these choices.

### Unlocking the apps

tapiOca and its page are free and unlimited. tapiOca's apps will be free to download, with a free tier, and unlocked with one purchase in each platform's store:

- **Free.** Each server's first station, for up to 2 hours a day on each device, and the first 10 minutes of each title in Media.
- **The unlock.** One-time purchase, no subscription. Bought in the App Store, Google Play or Roku's store, it unlocks everything, on every server, for every user, on that store account's devices. Each platform is bought separately. Refunds go through each store.
- **Nothing on the server.** tapiOca itself needs no purchase and never locks anything. Plex, Jellyfin and other apps are never limited.

Unlocking comes with the apps' store releases. Until then, the apps play as they do now.

## Reaching tapiOca from outside your home

**Often you don't need to.** Plex users away from home watch your stations through Plex as usual, because Plex relays the stream. The same goes for Jellyfin and Emby, which reach tapiOca from your home network. Only tapiOca's own page and tapiOca's apps need a way in from outside.

**Never open port 3310 to the internet.** Its tuner and streams never ask for a password. Every way in below keeps it closed.

| Way in | Good for | Open to the internet | Setup | Cost |
|---|---|---|---|---|
| [A VPN: Tailscale](#tailscale) | The page and the apps, on your own phones, tablets and computers | Nothing | Easiest: an app on the server and on each device | Free for personal use |
| [A VPN: WireGuard on your router](#wireguard-on-your-router) | The same | One port, for the VPN | Moderate, if your router has it built in | Free |
| [A reverse proxy with HTTPS](#a-reverse-proxy-with-https) | The apps anywhere, for anyone you've added, with no VPN on their devices; also the page | Port 443, to the proxy, which reaches only tapiOca's public port | More: a domain name, a port forward and the proxy | A domain name, about $10 to $15 a year |
| [A Cloudflare Tunnel](#a-cloudflare-tunnel-the-page-only) | The page only, not the apps | Nothing | Moderate | Free |

A VPN is the most private. Nothing at all is open to the internet, and tapiOca treats a phone on the VPN as on your home network. A reverse proxy suits people who won't install a VPN, such as family elsewhere. A Roku can't run a VPN, so a Roku outside your home needs the reverse proxy.

**For tapiOca's apps**, turn on **tapiOca's apps away from home** on the **Access** tab (it's off by default). Enter the address the apps use from outside: your VPN address with its port (such as `http://nas.your-tailnet.ts.net:3310`), or your reverse proxy's `https://` address alone, with no port. Apps set up at home remember it and switch to it when home doesn't answer.

Each station watched away from home uses your home connection's upload: about 1.7 Mbps at 480p, 3.7 Mbps at 720p and 6.2 Mbps at 1080p. Shared Media uses upload too, at the quality set under **Media away from home** (Original, or up to a number of Mbps).

**tapiOca checks that the apps can reach it.** While this is on, tapiOca calls its own address the way an app away from home would. It checks a few seconds after it starts, when you save the address, every 5 minutes, and when you choose **Check now**.

- **Ready** means an `https://` address reaches the public port over HTTPS, or a VPN address reaches tapiOca. Shared Media plays through the same address, so it's covered too.
- **Anything else** comes with the problem in one sentence. Examples are a proxy that points at port 3310, an address without HTTPS, a name that isn't found, an expired or untrusted certificate, the proxy's own error, something else answering, or a redirect.

The status appears under the address on the Access tab and in the setup. For Admins, **Away from home** in the page's header shows **Up**, **Down**, **Checking** or **Can't check** on every tab, and opens the Access tab's panel. A single failure never makes it **Down**, because tapiOca checks again a minute later. The log records when it goes down, why, and when it's back.

**When your router answers from home.** Many routers don't let devices at home use the home's own internet address (this is called NAT loopback, or hairpinning). From home, the address then reaches the router, which answers with its own sign-in page, certificate or redirect, or not at all. Apps away from home still work fine.

So tapiOca ignores results that could come from the router (nothing answering, a certificate for another name or one that isn't trusted, something else answering, or a redirect) until a check from home has worked since it started. A proxy error, a name that isn't found, an expired certificate, or tapiOca's own answer describing a problem always counts. If a signed-in app came in through the public port in the last 15 minutes, the status is **Up**, and the panel shows when an app last came in from outside. Otherwise it's **Can't check**, with the reason. To be sure, open your address on a phone using mobile data, not Wi-Fi.

**The fix.** Add a DNS host override in your router (such as OPNsense's or pfSense's Unbound host overrides) that points your address's name at the reverse proxy's address on your home network. Devices at home, tapiOca included, then reach the proxy directly.

### Tailscale

1. Install Tailscale on the server. On **TrueNAS SCALE**, use **Apps → Discover Apps → Tailscale**. On **Unraid**, use the Tailscale plugin. On **Synology**, use **Package Center → Tailscale**. Elsewhere, use Tailscale's own installer or Docker image. Sign in, and turn on **MagicDNS** in Tailscale's admin console.
2. Install Tailscale on each phone, tablet, computer, Apple TV or Android TV that should reach tapiOca. Sign in to the same account, or share the server with that account.
3. Use the server's Tailscale name with port 3310, such as `http://nas.your-tailnet.ts.net:3310`. Use it for the page in a browser, and as the outside address on the Access tab for the apps.

Tailscale connects your devices directly and encrypts everything, so nothing on your router changes.

### WireGuard on your router

Many routers and firewalls have a WireGuard VPN server built in (Firewalla, UniFi, OPNsense, pfSense, GL.iNet and others). Turn it on and add each phone or tablet in the WireGuard app. While the VPN is connected, use tapiOca's home address (such as `http://192.168.1.20:3310`) as if you were home. The apps need no outside address for this, because their home address works over the VPN.

### A reverse proxy with HTTPS

The proxy (such as Caddy or Nginx Proxy Manager) takes HTTPS connections from the internet and passes them to tapiOca's **public port** (3311), never 3310. You need:

1. **A domain name** pointing at your home's internet address, such as `tv.example.com`. Use dynamic DNS if that address changes.
2. **Port 443 forwarded** on your router to the computer running the proxy.
3. **The proxy**, with a certificate (both proxies below get a free one from Let's Encrypt). It passes requests to `http://<your-server-ip>:3311` and passes on each visitor's address in `X-Real-IP` or `X-Forwarded-For`. Nginx Proxy Manager and NPMplus do both by default. tapiOca counts wrong passwords by that address and shows it in the access log, so the proxy must set it itself, replacing any value a visitor sends. tapiOca accepts `CF-Connecting-IP` only when a request came through Cloudflare, so a visitor can't send it to pose as someone else.
4. **The proxy listed under Trusted proxies.** At home, on the **Access** tab, add the proxy's address on your home network under **Trusted proxies** (see [Trusted proxies](#trusted-proxies)). tapiOca believes forwarding headers only from a proxy listed there. Until it's listed, every visitor counts as the proxy's own address for wrong passwords, and tapiOca can't tell that the proxy received HTTPS, so it turns the apps away. From a listed proxy, the last address in each of `X-Real-IP`, `X-Forwarded-For` and `Forwarded` must name the same visitor. If they don't, tapiOca can't tell who it is.

**Caddy** (the whole `Caddyfile`). Caddy passes a visitor's own `X-Real-IP` through untouched, so this sets it itself, which keeps it in agreement with `X-Forwarded-For`:

```
tv.example.com {
    reverse_proxy 192.168.1.20:3311 {
        header_up X-Real-IP {remote_host}
    }
}
```

**Nginx Proxy Manager** (or NPMplus): add a proxy host for `tv.example.com` that forwards to `192.168.1.20` port `3311`. On its **SSL** tab, request a Let's Encrypt certificate and turn on **Force SSL**. It passes on each visitor's address by itself.

Then, at home, open the **Access** tab. If you haven't yet, add the first user (an Admin) with a long password. List the proxy's address under **Trusted proxies** (step 4). Turn on **tapiOca's apps away from home** with `https://tv.example.com`. Leave out the port, because that's the proxy's address, and tapiOca itself never speaks HTTPS. Within a few seconds, the status under it should show **Ready**. If it says the proxy points at the wrong port, point it at 3311, never 3310.

Besides the public port's sign-in and password limits (see [Security and remote access](#security-and-remote-access)), tapiOca is protected there by these rules:

- **Apps connect only over HTTPS.** tapiOca refuses any app request the proxy didn't receive over HTTPS, so no password, sign-in or stream address crosses the internet unencrypted.
- **Private addresses for each app.** Each signed-in app has a private address for its stations, and one for each title it plays from Media. These stop working as soon as its sign-in ends: on sign-out, a new password, the person's removal, or an Admin signing that app out under **Signed-in apps** on the Access tab.
- **API tokens are refused there** unless an Admin turns on **Accept API tokens from the internet**. Even then, they work only with [tapiOca's API](#tapiocas-api).

### A Cloudflare Tunnel (the page only)

A Cloudflare Tunnel reaches tapiOca's page without opening any port. It's not for the apps. Cloudflare's free plan isn't meant for video, and an app can't enter Cloudflare Access's email codes.

1. At home, on the **Access** tab, add the first user (an Admin) with a long password.
2. Keep `PUBLIC_PORT: "3311"` and the `"3311:3311"` port line.
3. In Cloudflare **Zero Trust**, add a public hostname to your tunnel (such as `tv.example.com`) with the service `http://<your-server-ip>:3311`. Never use 3310. Cloudflare passes on each visitor's address in `CF-Connecting-IP` by itself.
4. On the **Access** tab, list the address `cloudflared` reaches tapiOca from under **Trusted proxies** (see [Trusted proxies](#trusted-proxies)). That's its device's address on your home network, or `127.0.0.1` if it runs in tapiOca's own container (or Docker's own address, if it's another container on the same server: see [Trusted proxies](#trusted-proxies)). Otherwise every visitor through the tunnel counts as one address for wrong passwords. (Cloudflare's own addresses are believed for `CF-Connecting-IP` only when they connect to the public port directly.)
5. **Strongly recommended:** in Zero Trust **Access**, add that hostname as a self-hosted application, with a policy that allows only your people's email addresses. Cloudflare then asks for a one-time email code before anyone reaches tapiOca. tapiOca's sign-in becomes a second lock rather than the only one. This is free for up to 50 people.

## First-time setup

The first time an Admin opens tapiOca's page, the setup opens right away. It doesn't wait for Plex. It asks a few questions and checks that everything works. Use **Next** and **Back**, or the steps down the side. Each answer is saved when you move to another step. **Skip setup** leaves everything else unchanged.

1. **Checking your server:** the server itself. It never waits on Plex, which is checked in the Tuner step (step 9). It reads your media folder directly: `MEDIA_DIR`, and any folder `PATH_MAPPINGS` names. It checks whether the folder is there, whether tapiOca can read it, whether it holds anything, and whether tapiOca can read a video in it. If nothing is at `MEDIA_DIR`, it looks at the folders mounted into tapiOca and says where your media seems to be, and what to set `MEDIA_DIR` to: the folder's place inside tapiOca, not on your server. It also checks how tapiOca encodes video, whether its clock matches your browser's, and its backups. Anything marked **Needs a look** or **Not working** says what to do. After changing tapiOca's app settings, restart it, then choose **Check again**.
2. **How stations play:** the picture size for new stations and the number of tuners, with **Test this server** to help you choose.
3. **New station settings:** the defaults for new stations. These cover subtitles, commercials and trailers, the Station ID card, the Intro Bumper, the Up Next Banner, and what goes in the corner. Stations you already have don't change.
4. **Who can use tapiOca:** everyone signs in, at home and away. Enter your name and a password (see [Passwords](#passwords)) to become the first Admin, and you're signed in right away. To let your home's devices skip signing in, tick **Devices on my home network skip signing in**. It offers the network tapiOca sees you on (such as `192.168.1.0/24`), with a name you can change. Its devices then open on **Who's tuning in?**, and **New people show on** becomes **Every device at home**. Never use a guest network (see [Trusted networks](#trusted-networks)). A tapiOca updated with signing in off offers both choices here: **Anyone on my network**, or **Only people who sign in** (see [Who can use tapiOca](#who-can-use-tapioca)).
5. **Who sees what:** the Viewing Level **New people start on** (Unrestricted until you choose another), and each person's Viewing Level (see [Viewing Levels](#viewing-levels)).
6. **Watching away from home:** whether tapiOca's own apps can watch your stations away from home, and the address they use there (see [Reaching tapiOca from outside your home](#reaching-tapioca-from-outside-your-home)).
7. **Media in tapiOca's apps:** which Media folders the apps can browse and play in Media. Every Media folder is shared to start. Untick any you'd rather keep out (see [tapiOca's own apps](#tapiocas-own-apps)). If Plex isn't answering, the step says so within a few seconds, and Media folders already shared stay shared.
8. **Checking files:** when the overnight deep scan runs.
9. **Tuner:** where you'll watch your stations, then how to add tapiOca to each app. It asks **Will you watch your stations in other apps?** Tick each one you'll use, one or more: **Plex**, **Jellyfin**, **Emby**, **Kodi**, **Another app** (an M3U playlist and XMLTV guide), or **Only tapiOca's own apps**. Until you answer, Plex is ticked if tapiOca is set up with Plex or Plex has used its tuner. Your answer only changes what the step shows: every app can still use the tuner (see [Watch your stations](#watch-your-stations)). Below the question, each app ticked has its own steps and addresses, each address with a **Copy** button:
   - **Plex:** the checks for Plex, the steps in Plex, and the tuner and guide addresses to enter there. **Check again** runs the checks again. If Plex says "There was a problem fetching channel mappings," reload Plex's page and start again: Plex renames the tuner partway through setup, so it may still know tapiOca's tuner from before. Plex is optional: with a [Media folder of your own](#media-folders-of-your-own) and no `PLEX_URL`, the Plex check says tapiOca isn't using Plex, and that's fine. While tapiOca gets your shows and movies from Plex, or a Plex check needs attention, the checks show even with Plex unticked.
     - **Plex:** whether tapiOca can reach Plex, and whether the account that owns your Plex server has Plex Pass, which watching in Plex needs. When tapiOca can't reach Plex, it says what happened: nothing answered, the connection was refused, the address couldn't be found, Plex answered with a problem, or Plex didn't accept the token. It also says so when `PLEX_URL` is still the example address from tapiOca's YAML, `http://192.168.1.10:32400`.
     - **Plex's files:** whether tapiOca finds the files Plex lists, so it can read them straight from disk.
     - **tapiOca in Plex:** whether Plex has tapiOca as a DVR yet.
   - **Jellyfin**, **Emby** and **Kodi:** the playlist and guide addresses, and the steps in that app, as in [Watch your stations](#watch-your-stations).
   - **Another app:** the playlist and guide addresses.
   - **Only tapiOca's own apps:** nothing else is needed.
10. **All set:** your current settings, and anything that still needs attention. It also asks whether tapiOca should tell you when a new version is out (see [Updating](#updating)). The box is never ticked for you, and leaving it unticked is No.

To open the setup at any time, choose **Run setup again** on the **Setup** tab, or **Setup** at the bottom of the page. Your current answers are filled in. The setup is the only place to change the settings for new stations. Everything else can also be changed on its own tab.

**After an update.** When a new version brings a question for an Admin, such as a new feature to turn on or a new choice, the setup opens once by itself with just those questions. It also shows the checks if something needs attention. Everything else stays as you set it.

**Light or dark.** tapiOca's page follows your device's light or dark setting. To keep it light or dark in one browser, choose **Light** or **Dark** under **Appearance** at the bottom of the page. **Automatic** follows the device again. The choice is saved in that browser only, so each person and device can have their own.

**As an app.** tapiOca's page fits phones, tablets and computers, in either orientation. You can add it to a phone's or tablet's home screen, or install it on a computer. It then opens in its own window, like an app:

- **iPhone or iPad.** In Safari, choose **Share → Add to Home Screen**.
- **Android.** In Chrome's menu, choose **Add to Home screen**.
- **A computer.** Choose **Install** in Chrome's or Edge's address bar, or **File → Add to Dock** in Safari on a Mac.

Install it from the address you sign in at, such as your reverse proxy's `https://` address. Chrome and Edge install only from an `https://` address. Nothing is stored on the device. The app always shows tapiOca's page live, so tapiOca must be reachable.

### The INFO station

A new tapiOca starts with station 99, **INFO**, with tapiOca's logo. Plex's Live TV & DVR won't add a tuner whose guide has no stations, so INFO lets you add tapiOca to Plex before you've made a station of your own. It stays useful after that:

- **What it shows.** A film of teal pearls flying through tapiOca's ring, to a light tune, with the time and date in the top right corner, tapiOca's web address in the bottom right, and a panel in the bottom left that changes every 15 seconds: **What's new in tapiOca** (this version's highlights), **tapiOca's apps, in beta** (their newest versions and what's new in them), **By the numbers** (your stations, and the movies, shows and episodes in the Media folders shared with tapiOca's apps, with how many were added this week) and **A tip for tapiOca's apps**, a new one each hour.
- **For everyone.** Everyone who can watch your stations sees INFO, whatever their Viewing Level, in Plex too. So it shows counts, never titles, and never your server's addresses or how it's doing.
- **No burn-in.** Nothing on it holds still: the logo floats, and the text drifts a few pixels now and then. The pearls always fly in front of the text.
- **It plays without Plex.** The film comes with tapiOca itself, and nothing on INFO asks anything of the internet. Plex is asked for its counts once an hour.
- **In the guide.** INFO shows as back-to-back 4-hour listings from midnight (by your server's clock), each saying what it shows, in Plex's guide and every other. It plays its film over and over all the same.
- **Never a broken file.** Its film is never checked, and never put on the **Broken files** list (from 1.36.2).
- **Always 99, and only its film.** You can rename INFO and change its settings, but not its number, and no other station can be 99. A station that was 99 before 1.34.1 keeps its number until you move it. INFO plays only its own film (no blocks, Feature Presentation or marathons), and no other station can play it.
- **Removing it.** Delete it on the **Stations** tab. To bring it back, choose **Add the INFO station** under **The INFO station** on the **Setup** tab.
- **Only new tapiOcas get it by themselves.** A tapiOca updated from an earlier version can add it on the **Setup** tab.

## Media folders of your own

A Media folder of your own is one tapiOca reads itself, straight from folders in its media folder (`MEDIA_DIR`, `/media` in the container): your own shows or movies, with or without Plex. It works as one of Plex's Media folders does, for stations, filters, smart stations, collections and Media in tapiOca's apps. Use one instead of Plex, beside it, or for what isn't in Plex. To use tapiOca without Plex, leave out `PLEX_URL` and `PLEX_TOKEN` (delete their two lines in the YAML or Compose file).

**Adding one.** On the **Setup** tab, under **Your own folders**, choose **Add a Media folder**. Give it a name, choose **Shows** or **Movies**, and choose its folders inside the media folder (it can have several, but not one inside another). tapiOca reads it right away. A folder that's also in one of Plex's Media folders is allowed, with a note: its programs then appear twice, once from each. New Media folders are shared with tapiOca's apps until an Admin chooses which are (see [tapiOca's own apps](#tapiocas-own-apps)).

**How to lay it out.** As Sonarr, Radarr, Plex, Jellyfin and Emby lay out folders:

- **Shows:** `TV/Show (2010)/Season 01/Show (2010) - S01E02 - Title.mkv`. Also `1x02`; `S01E02E03` or `S01E02-E03` (one file, two episodes); `Specials` or `Season 00`; and dates for daily shows (`Show - 2024-03-15 - Title.mkv`).
- **Movies:** `Movies/Movie (1999)/Movie (1999).mkv`. Other files in a movie's folder are its versions (`Movie (1999) - 4K.mkv`), and `cd1` and `cd2`, `part1` and `part2`, or `disc1` and `disc2` are its parts, played one after the other as one movie.
- **IDs in names**, such as `{tmdb-12345}`, `[imdbid-tt0012345]` or `{tvdb-67890}`, are kept with the show or movie.
- **Left out:** hidden files and folders, extras folders (Extras, Featurettes, Behind The Scenes, Deleted Scenes, Interviews, Trailers, Shorts, Other), trailers and samples, a NAS's own folders (`@eaDir`, `#recycle`), discs copied as they are (`BDMV`, `VIDEO_TS`), and any link that leads outside the media folder.

**Where its details come from.** For each detail, the first of these that has it:

1. **NFO files** beside the videos, as Sonarr, Radarr, Jellyfin, Emby and tinyMediaManager write them (`tvshow.nfo`, `season.nfo`, an episode's or movie's own). They give titles, years, plots, genres, content ratings, studios, cast and crew, and collections.
2. **Tags inside the files:** a title, date, description, show, season and episode, and genre.
3. **Folder and file names.**

tapiOca doesn't look anything up online for these, and never guesses: what it can't be sure of is listed by what its names say. Matching titles, and fixing what's wrong, come in a later version.

**Ratings** come from the NFO files (`<mpaa>`, such as `PG-13` or `TV-14`) and count as Plex's do. A title with no rating is unrated, so the Viewing Levels that hide unrated titles hide it (see [Viewing Levels](#viewing-levels)): every level but Unrestricted, to start.

**Pictures** come from beside the videos (`poster.jpg`, `folder.jpg`, `fanart.jpg`, `clearlogo.png`, `season01-poster.jpg`, an episode's `-thumb.jpg`, and the like), then from covers inside the files (an MKV's attached cover, an MP4's cover). A title with neither shows without a picture.

**Reading it again.** tapiOca reads new and changed files soon after it starts, every 6 hours, when you choose **Read again**, and when Sonarr or Radarr brings a replacement tapiOca asked for (see [Replacing files with Sonarr and Radarr](#replacing-files-with-sonarr-and-radarr)). It reads at the lowest priority, and never while anyone's watching a station or Media. A file renamed or moved keeps its place on stations, and what people watched of it, and so does one replaced with a better copy (as Sonarr and Radarr upgrade). If a folder can't be reached (a share that isn't mounted, or one folder on it that can't be read for a moment), its programs are kept and listed as missing until it's back. They're never taken off your stations for it. A file or folder whose name isn't UTF-8 (as on some older NAS shares) is skipped, and the **Logs** tab says so: rename it, and tapiOca reads it.

**Titles from names.** When nothing but a file's name says what it is, its title is made from the name, as words, without its release details (`Coastline.2010.Special.1080p.WEB-DL.x264-GRP.mkv` is "Coastline 2010 Special"). tapiOca's apps never get a file's name or a folder's path.

**While Plex isn't answering** (if you use it too), your own Media folders are still listed in Media and in the station editor, and their programs play. Sharing Media with the apps can't be changed until Plex answers, and stations pick up what's new in your folders once it does.

**What they don't have yet.** Skipping intros and credits, on stations and in tapiOca's apps, and pictures for titles that have none beside them or inside them.

## Making stations

Choose **New station** on the **Stations** tab.

**The basics.** Give the station a **Number** and a **Name**, and choose a **Logo** (see [Logos](#logos)). A station with no name is called "Station 12", after its number.

**What's on it.** Under **What's on this station**, choose one of:

- **Pick shows & movies:** select titles from your Media folders in Plex, shown with posters and genres.
- **Use a filter:** describe what you want, and Plex keeps the station up to date as your movies and shows change. See [Filters](#filters).

**Picking titles.** The **Filter** box searches titles, genres and years. Every word must match one of them, so "western 1959" finds Westerns from 1959. The three buttons next to it change the poster size. A title already on another station is marked ("Already on station 12"). Below the list, tapiOca totals the shows, movies and episodes you picked, and about how many hours that is. To add a whole Media folder, choose **Everything in** that Media folder. The list shows up to 3,000 titles per Media folder. Type in the filter to find the rest.

**Settings.** The rest of the editor is grouped into **How it plays**, **Specials**, **Between programs**, **On screen** and **When someone tunes in**. Each group shows a summary when it's closed. If you close the editor with unsaved changes, it asks first.

**New station defaults.** Unless you chose otherwise in [First-time setup](#first-time-setup), a new station starts with **Shuffle**, black bars on 4:3 shows, intros and credits played, no commercials or trailers, no Station ID card, a 10-second Intro Bumper with sound, the station's logo large in the bottom-left corner during programs, a large Up Next Banner for 10 seconds, no subtitles and no specials.

### Filters

Instead of picking titles, a station can ask Plex which titles match and follow the answer as your movies and shows change. Choose **Use a filter**, then combine any of these conditions. Each condition narrows the results. Several values in one condition mean "any of these".

- **Media folders:** one or more. A movie in two Media folders plays once.
- **Any Plex filter for those Media folders:** genre, content rating, network, studio, country, collection (including smart collections), label, director, writer, actor and more. People are searched as you type.
- **Decade** (TV shows count by the year they started) and **Title contains**.
- **Added in the last N days:** new arrivals. For TV, this means the episodes added in that time, so a "New This Week" station refreshes itself.
- **Minimum audience rating:** Plex's audience rating, out of 10. Titles without a rating are left out.

A count of matches, with examples, updates as you go. **Choose which…** lists every match, so you can uncheck any you don't want. Those stay out, while new matches still join.

Examples:

- **Action movies:** Genre: Action.
- **A favorite director's movies:** Director: the one you choose.
- **Classic TV:** TV shows, Decade: 1950s and 1960s.
- **Kids' TV:** Content Rating: TV-Y, TV-G.
- **Christmas movies:** Plex has no Christmas genre. Select your Christmas movies in Plex, choose **Edit**, add the label "Christmas", and filter on **Label: Christmas**.

### Stations from Plex collections

On the **Stations** tab, **From Plex collections** lists the collections in your TV and movie Media folders, including smart collections. Check the ones you want and choose **Make station** (or **Make N stations**). Each becomes its own station, named after its collection, with the next free number and the default settings. A collection of shows plays every episode of those shows. You can make up to 200 at once. A collection that's already a station shows as checked.

Each station follows its collection. Titles added to or removed from the collection in Plex join or leave the station within about an hour. If a tool recreates the collection, the station finds it again by name.

### Smart stations

**Smart stations** on the **Stations** tab makes stations from a filter (see [Filters](#filters)). Then choose:

- **One station** of everything that matches, or
- **One for each** decade, genre, studio, actor or anything else Plex offers. tapiOca asks Plex how much each would have ("1960s Comedy · 88 movies") and lists up to 40. Check the ones you want and rename them if you like. For directors, actors, writers and producers, pick the names yourself when Plex can't list who's in what.

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

Choose each station's **Picture** under **How it plays**. New stations use the size set on the **Setup** tab.

| Picture | Size | Video data per viewer | Work for the server |
|---|---|---|---|
| **480p** | 854×480 | 1.5 Mbps | About half of 720p. For slower servers or many stations. |
| **720p** (standard) | 1280×720 | 3.5 Mbps | Sharp on most TVs, and light enough for most servers. |
| **1080p** | 1920×1080 | 6 Mbps | About twice 720p. A GPU helps a lot. |

Sound adds 192 kbps. A new picture size takes effect the next time the station starts, after everyone has stopped watching it.

**4K and HDR.** Stations play at up to 1080p in standard color, on purpose. Streaming 4K HDR would need a GPU fast enough to convert everything in real time, and about 20 Mbps per viewer. Plex Live TV also isn't known to pass HDR from a tuner through to the TV. So 4K programs are scaled down to the station's size. HDR programs (HDR10, HDR10+, HLG and most Dolby Vision) are converted to standard color the way a TV would, so they don't look washed out.

**Dolby Vision profile 5** files (common from streaming services) have no standard picture that anything but a Dolby Vision player can show correctly, so tapiOca doesn't play them. They're listed on the **Broken files** tab as **Unsupported**. Replace the file with another version, and it goes back on the air.

**Movies in several files.** Plex stacks a movie kept as several files (`Movie-cd1.mkv` and `Movie-cd2.mkv`, or "part 1" and "part 2") into one. tapiOca plays the files back to back as one program. The corner logo, the Up Next Banner and burn-in protection carry on across the join, and someone tuning in during the second file joins at the right place. The guide shows the files' combined time, as Plex reports it. If one file is missing or won't play, the movie is handled like any broken file. It goes on the **Broken files** list, which names the file ("part 2 of 3"), and a stand-in plays the rest of its time.

### Tuners

tapiOca's **tuners** set how many different stations it can play at once. Set the number from 1 to 20 on the **Setup** tab. Plex doesn't cap this at 4 or any other number. It uses as many tuners as tapiOca offers. The real limit is your server, because each station being watched is converted in real time. The default, 4, is a safe start for most servers, and a GPU can usually handle more. **Test this server** (below) suggests a number for yours.

Everyone watching the same station shares one stream, so a station uses one tuner no matter how many people watch it. With 4 tuners, 4 different stations can play at once, for any number of viewers. The limit covers Plex and every other app together. While anyone is watching, a pill at the top of the page shows how many tuners are in use.

When every tuner is busy, someone tuning in to another station sees an **All tuners in use** card for 30 seconds, listing the stations that are on. Up to 3 people at a time see the card. Anyone beyond that gets Plex's own error. tapiOca reports more tuners to Plex than it really has, so Plex always lets it show that card. If you raise the number of tuners and Plex still won't play more stations at once, restart Plex.

A station keeps running for 20 seconds after its last viewer leaves, so flipping back is instant. During that time, the station gives up its tuner if someone else needs it.

**Test this server** on the **Setup** tab makes a few seconds of video at each picture size and estimates how many stations your server can play at once. It runs at low priority, so stations that are playing aren't affected. Its suggestion leaves 30% headroom. **Use N tuners for 720p** applies it; choose **Save** to keep it. If you set more tuners than the test suggests, the page warns you.

### How many can watch at once

Every device watching through tapiOca's apps (or another player using the HLS addresses) receives its own copy of the station, over your network at home and over your internet upload away from home. A station still uses one tuner however many people watch it, so this limit is about your network, not your server's processor. Programs played from Media count too.

On the **Access** tab, under **How many can watch at once in tapiOca's apps**, an Admin can set two limits:

- **Devices watching at once:** every device, at home and away. Devices away from home count toward this number too.
- **Away from home, at most:** how many of those can be away from home. This keeps your home's internet upload from running out.

Leave a box empty for no limit. A device that's already watching can always change stations. A device beyond a limit sees a message such as: "An Admin has limited tapiOca to 5 devices watching at once, so it runs smoothly for everyone. Please try again later." Plex, Jellyfin and other apps aren't counted here. They have their own limits, and the tuners cover them.

tapiOca recommends limits based on **connection tests**. A test times data sent by tapiOca, so it measures the connection the way viewers use it. tapiOca doesn't use an outside speed-test service. The recommendation uses the fastest recent test and leaves 30% headroom. The page warns you if a limit is set higher.

- **Test the connection,** in the panel, runs the same test as tapiOca's apps, from the browser you're using. At home, it's a test at home. From outside your home, it's a test away from home. Its result is kept with the apps' tests and used for the recommendations.
- **To test away from home,** run the test on a phone using mobile data, in a tapiOca app (under Options) or on this page opened from outside your home. That measures your home's upload.

### Schedules

Programs play back to back at their real lengths. Nothing is stretched or padded to fill 30- or 60-minute slots, so a 7-minute cartoon is followed right away by the next one.

- **Episode order:** one episode of each show in turn, each show in episode order, like classic reruns. Shows go in alphabetical order, and a movie counts as a one-episode show. When a shorter show runs out, the others continue without it. So a long-running show can play many episodes in a row near the end of the run. Then the run starts again.
- **Shuffle:** every program plays once per pass, and each pass is shuffled again, so a show doesn't air at the same time every day. No show plays more than twice in a row, and nothing from the end of one pass comes right back at the start of the next. If one show has more than twice as many episodes as everything else combined, that rule can't always hold, and the station card says "mostly one show".

tapiOca works out the schedule the same way every time, starting from when you saved the station. That keeps Plex's guide accurate, and restarting tapiOca never changes what's on.

### Updates to stations

New episodes join stations automatically, and removed ones leave, without making any app's guide wrong. Every hour, tapiOca looks at what changed in Plex, and in what it last read of your own Media folders (read every 6 hours, or when you choose **Read again**), and prepares an update. The program on the air is never cut short: an update starts at a program break. The station card shows **Update ready** while an update is waiting. When the update starts depends on where you watch:

- **With Plex:** at the first program break after Plex next downloads the guide, so the guide Plex already has shows it. tapiOca asks Plex to refresh the guide when an update is ready, so this usually happens within the hour.
- **Without Plex** (or when Plex hasn't downloaded the guide for a day): once the guide other apps last downloaded runs out, so their guides stay right. That guide covers 48 hours, so an update can take up to 2 days. If no app downloads the guide (tapiOca's own apps don't need it), an update starts at the first program break after it's prepared.

In episode order, the station continues with the program that was due. In shuffle, new programs are spread through the current pass where they fit, and the rest join the next pass. That way, 23 new episodes of one show don't turn into a marathon.

**Updates that need your review.** On a station with 10 or more programs, an update that would remove more than half of them isn't applied automatically. That's more likely a Media folder being rescanned or a drive offline than something you meant. The card says "N programs gone — needs your review". The same happens if Plex or a Media folder suddenly reports nothing at all, or loses the intro and credits markers for more than half of the programs a station skips them on. Choose **Update now** if the change is right.

**Shows that Plex re-adds.** (Your own Media folders keep a show's or movie's place when it's renamed, moved or replaced: see [Media folders of your own](#media-folders-of-your-own).) When Plex re-adds a show or movie, it gets a new ID in Plex. This happens when it was removed and found again, rematched, or moved to another folder or drive. The station finds it again by title, and its episodes keep their places. When more than one show has that title (the same show in two Media folders, say), the station follows the one in the Media folder it came from. If that's unknown, it follows the one with the station's own files. If it still can't tell, the station keeps playing what it had, and the **Logs** tab names the show to choose again in the editor.

For Plex's titles, tapiOca never reads anything from file names: the show, season, episode and title all come from Plex, however your files are named. Your own Media folders' titles come from their NFO files, then the files' tags, then their names (see [Media folders of your own](#media-folders-of-your-own)). Specials (season 0) are left out.

### Skipping intros and credits

Set **Intros & credits** to **Skip them** for binge-watching. Each program airs without its opening titles and end credits, and the next one starts right away. tapiOca starts from the same markers as Plex's own **Skip Intro** and **Skip Credits** buttons:

- **Cold opens still play.** Anything before the intro plays to its end.
- **Final credits end the program.** A program ends where its final credits begin. Credits in the middle with a scene after them are skipped, and the scene still plays.
- **No markers, no skipping.** Programs without markers play in full, and so do programs from your own Media folders, which have none yet. The station card shows how many programs have something skipped.
- **Exact guide times.** The guide shows each program's length without the skipped parts.

tapiOca uses markers only when they look right. An intro must start in the first half and be under 5 minutes. Credits must start in the second half. Skipping can't remove more than half a program or leave less than a minute.

**Skips end where the picture cuts.** Plex finds an intro by its theme music, which often starts under the last line of the cold open and runs on over the program's first shot. So tapiOca looks at a few seconds of each file around each marker (at low priority, one program at a time). It moves each skip to a change of shot or a moment of black inside it, so the cold open plays to its end and the program plays from its start. If the picture changes shot more than once under the music, tapiOca keeps the extra shots, so a few seconds of the titles may show (usually 3 at most, and never more than 6 at each end). Where there's no clean cut (a slow fade), the skip stays 2 seconds inside Plex's marker at that end. A skip only ever gets shorter, never longer. One left too short to keep (a few seconds) isn't made, and the program plays in full.

When you save a station with only a few programs still to look at, tapiOca waits up to 10 seconds for them. (Stations made several at a time, as [smart stations](#smart-stations) or [from Plex collections](#stations-from-plex-collections), don't wait: their programs are looked at first.) The rest are looked at in the background and keep the 2-second margins until then. What's found in the background reaches your stations together, twice a day at most (and when tapiOca starts), with the next update from Plex. It's kept in `cuts.json` in the data folder, so each file is usually looked at just once. The **Logs** tab says when looking starts, how far along it is now and then, and when it's done.

Plex has to find the markers first. In Plex, go to **Settings → Library** and set **Generate intro video markers** and **Generate credits video markers** to run as a scheduled task and when media is added (a Plex Pass feature). tapiOca asks Plex again about programs without markers, first after 6 hours and then less often. Markers Plex finds later arrive like any other update.

### Sound and picture shape

**Sound.** TV episodes are brought to the same loudness (−24 LUFS, the US broadcast standard), so the volume doesn't jump between episodes. Movies keep their original sound, with its full range. Episodes played from Media in tapiOca's apps get the same treatment (see **Even sound for a show's episodes** under [tapiOca's own apps](#tapiocas-own-apps)).

**4:3 shows.** Each station shows 4:3 programs with **Black bars** at the sides (the original shape), **Stretch** to fill the screen, or **Zoom**, which fills the screen and trims the top and bottom. Widescreen programs are never changed. Many 4:3 shows are stored as widescreen video with black bars built into the picture. With Stretch or Zoom, tapiOca detects those bars and removes them first.

### The guide

The guide covers the next 2 days, both in Plex and in tapiOca's own **Guide** button. Plex reloads the guide only about once a day on its own, which is why it covers 2 days.

## Station features

### Logos

tapiOca includes nearly 1,000 original station logos, all drawn for it:

- **Networks and stations:** made-up broadcast and cable networks, Movie stations and Classic stations.
- **Classic TV, TV shows, Cartoons & anime and Teens:** made-up stations in the style of each.
- **Genres:** three designs for each of Plex's 37 genres.
- **Themes:** decades, holidays, seasons, times of day, moods, kids and family, and on-air signs.
- **Letters and numbers:** A–Z and 1–50, in a modern and a retro style.

None copies a real TV network's or show's name, symbol or lettering.

A new station numbered 1 to 50 starts with its number's logo, which follows the number if you change it. Other new stations get a logo no other station is using. In the editor, **Choose…** opens the logo picker, with a search box and categories. When the station's name or filter suggests a genre, the picker opens on **Suggested** logos. **Surprise me** picks one at random. You can also show the **Station number** instead of a logo.

**Your own logos.** In the logo picker, choose **Upload your own…** and pick a PNG, JPEG, WebP, GIF or BMP image up to 10 MB. tapiOca makes it a 512×512 PNG on a clear background, so square images look best. Your logos are listed first, under **Your logos**, and stored in `data/logos`. Once no station uses one, you can delete it with its ×.

**Logos from Plex.** A new station with one show or movie is named after it. If Plex has a logo for it (the title artwork Plex shows on its pages), that becomes the station's logo. A name you type or a logo you choose yourself isn't replaced. On other stations, the first show's Plex logo is offered as **Use the logo from Plex**. tapiOca trims it, keeps its shape (most are wide) and sizes it to match the built-in logos. It adds the logo to **Your logos** when you save the station.

Plex apps load logos from tapiOca's address, so they appear on your home network. Away from home, they appear only if tapiOca's address can be reached from there.

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

**Station ID card** (under **Between programs**) adds a card after each program and its commercials. The card shows the station's logo, name and number, and **Up next** with the next program, for 3, 5 or 10 seconds. One of 15 short jingles plays underneath, always quieter than the programs. tapiOca made the jingles; none is borrowed from a real station. Set **Jingle** to **Off** for silence. The card's time is part of each program's time in the guide.

### Commercials and trailers

**Commercials & trailers** (under **Between programs**) plays **None**, 1, 2 or 3 clips after each program: commercials after TV episodes, trailers after movies. They're part of each program's time in the guide, so nothing is squeezed. Each clip plays about as often as the others and is brought to the same loudness as TV episodes.

The clips come from two folders, named exactly as shown (Linux names are case-sensitive):

- `commercials` at the top of your TV shows' Media folder, such as `/mnt/tank/media/tv/commercials`
- `trailers` at the top of your movies' Media folder, such as `/mnt/tank/media/movies/trailers`

tapiOca finds them through the folders Plex lists for each Media folder. If a Media folder is your whole media drive, put the folder directly inside it. Subfolders are fine. Clips from 3 seconds to 10 minutes long are used. Put a file named `.plexignore` containing `*` in each folder, so Plex doesn't add the clips to your Media folders:

```
cd /mnt/tank/media
mkdir -p tv/commercials movies/trailers
echo '*' > tv/commercials/.plexignore
echo '*' > movies/trailers/.plexignore
```

**Commercials from the right decade.** Put clips in a subfolder named for a decade (`commercials/1960s` or `commercials/60s`), and they play only after programs from that decade, by the year Plex gives each program. Trailers work the same way. Clips outside decade folders play after everything else.

**Under Viewing Levels.** On a station someone with limits can see, a clip plays only if you've rated its folder, at or below the station's highest-rated program. Rate the folders on the **Access** tab (see [Viewing Levels](#viewing-levels)). On other stations, every clip plays.

tapiOca looks in the folders at startup and every hour. Admins can choose **Check again** in the editor to look right away. If a folder seems to vanish (a share that isn't mounted yet), the clips already found are kept for a few hours. A clip that fails to play is left out until its file changes. It's listed on the **Broken files** tab under **Commercials and trailers that didn't play**, and a plain card fills its time.

### Intro Bumper

When someone tunes in, an **Intro Bumper** (under **When someone tunes in**) can play before the program, like a station ident:

- **Built-in card:** the station's logo arriving (in one of a dozen ways), "You're tuning in to", the station's name, a **Description** line and what's on, for 3, 5, 10 or 15 seconds. Its **Sound** is an old TV dial turning through static. **Preview** shows it.
- **Your video:** upload a video up to 30 seconds long (MP4, MOV, MKV, WebM and similar, up to 500 MB). tapiOca makes a copy at the right size, with its volume matched to the programs. Your videos are stored in `data/bumpers` and available to every station.

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
- **Feature Presentation:** a movie night on the days and at the time you choose. A 10-second **Feature Presentation** card plays first (**Preview the card** shows it), then the movie. **Movies from** sets the source: the station's own movies, a movie Media folder or a movie collection. So a TV station can have movie nights too. Every movie is shown once before any repeats.
- **Blocks:** up to 4 time-of-day blocks, such as Saturday Morning Cartoons. Each has a name (up to 40 characters), days, start and end times, and its own shows (**Choose shows…**). A block can run 30 minutes to 12 hours, and past midnight is fine. It plays its shows in the station's order, ends at the program break nearest its end time, and picks up where it left off next time. A block is skipped if the nearest program break comes after its end time.

Saving is refused, with the reason, if a Feature Presentation has no movies, a block has nothing to play, two blocks overlap, or a Feature Presentation or marathon falls during a block. The station card shows when each special is next.

## Keeping stations on the air

A bad file should never take a station down. tapiOca is built around that.

### Safeguards

| When | What tapiOca does |
|---|---|
| A program won't open, or stops partway | Tries the same program again from where it stopped, twice (after 1 and 2 seconds). Many hiccups clear up by themselves. |
| It still won't play | Puts it on the [Broken files list](#the-broken-files-list), and a stand-in joins at the same point. If an episode fails 10 minutes in, the stand-in starts 10 minutes in and ends when the broken one would have, so the guide stays right. |
| Choosing a stand-in | Tries another episode of the same show first, then a program of the same kind, then anything long enough. In a block or Feature Presentation, its own programs come first. Up to 4 are tried. |
| Opening a file is slow (a sleeping drive, a busy NAS) | Keeps the stream alive with a few seconds of black. |
| A file stalls (no new video for 8 seconds) | Resumes or replaces it as above. A stall is blamed on storage, not the file. The file is skipped for the rest of that viewing, and listed only if it stalls in two separate viewings. A stuck ffmpeg process is abandoned after 2 seconds, and the next program reads ahead to rebuild the stream's 10-second cushion. |
| Something drawn over the picture fails (corner logo, banner or subtitles) | Tries the program again with nothing drawn over it before blaming the file. |
| Plex or the media share can't be reached | Skips the affected programs for now, without listing them. |
| A file is a few seconds shorter than Plex says | Fills the rest of its time with black. A file more than 10 seconds or 2% short counts as cut short. |
| A movie in several files | Plays each file in turn, opening the next while one plays. A file that's missing or won't play is handled as above, and a stand-in plays from there. While Plex can't be reached, tapiOca can't ask which files the movie has. Then a file that ends a minute or more before its time gets a stand-in for the rest, instead of black. |
| Nothing on the station can fill the time | Shows a "We'll be right back" card for the time that's left, then continues. |
| Nothing could play for two programs in a row | Shows "This station is off the air. Please report it." and logs an error. It keeps trying each new program and comes back on the air by itself. |
| The station's stream fails | Restarts it right away in the same stream, so viewers see at most a brief pause. It also restarts a stream that sends nothing for 45 seconds. After 3 failures within 5 minutes, the off-air card shows for 2 minutes before it tries again. A program that crashes the stream twice is skipped for that viewing. |
| Sonarr or Radarr upgraded or renamed a file | Nothing. tapiOca asks Plex for the current file every time a program plays. |

### The Broken files list

Files that can't play properly go on the **Broken files** list, shown on the **Broken files** tab and stored in `data/broken-files.json`.

- **One list for every file.** The list covers stations and Media in tapiOca's apps (the Media folders an Admin shares with them). A file found broken for one is broken for the other too.
- **What each entry shows.** What's wrong, when it was found, how many times it failed, and the file's path. It also shows which stations have the file (each opens that station's editor), and whether it's in Media.
- **On stations.** Every entry is skipped on every station until it's cleared, and a stand-in plays in its place.
- **In Media.** A broken file doesn't play. Another version plays instead, if one isn't broken, and the apps say so. A damaged file still plays.
- **Versions.** A program's other versions (a 4K and a 1080p file, say) are separate files, and an entry for one is about that version alone. `broken-files.json` lists them under `versions`. Stations play a program's first version, listed under `files`.
- **Movies in several files.** Such a movie has one entry, for the file with the problem. Its reason ends with the part ("…, in part 2 of 3"), and its times and path are that file's. `part` and `parts` say which file it is. The whole movie is off the air until the entry is cleared, and **Retry** puts that file back on the air.

The tab has three parts:

- **Needs you:** people's reports (see [People's reports](#peoples-reports)), and files tapiOca found that are waiting for you. These are broken or damaged files a station or Media plays that Sonarr or Radarr aren't replacing by themselves, and files they couldn't replace. The tab's count is the number of items here. Admins are notified through their alerts (see [Troubleshooting](#troubleshooting)).
- **Being replaced:** what Sonarr or Radarr is fetching now.
- **Found by tapiOca:** everything else. That means files you're handling yourself, files no station or Media plays now (a missing one leaves the list by itself), and unsupported files.

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
- **Editing the list file.** You can also delete an entry from `broken-files.json`. tapiOca notices within 15 seconds. Unlike **Retry**, this doesn't tell the checks to leave the file alone.

**Entries that clear themselves:**

- **Every half hour,** tapiOca checks the list against Plex. An entry clears when Plex has the program again under a new ID, or when its file is missing (or Plex removed it) and neither a station nor Media has it anymore. An entry for one of a program's versions clears when Plex no longer has that version.
- **A new file** for a program gets a quick check, and the entry clears if the new file passes. Otherwise the entry says what's wrong with the new file.
- **Every night,** when the overnight checks begin (1 AM unless you change it), tapiOca re-checks programs taken off the air by a quick check or because their file couldn't be opened. A share may have been down. It does the same when you choose **Check the list again**. These entries clear if the files pass.
- **Deep-scan and playback problems** stay until the file changes, because checking the same file again would find the same thing.

tapiOca recognizes a program Plex re-added under a new ID by its own show, season and episode first. Next it tries the same file name, the same TVDB show, or the same episode title and year. It never matches by a title alone.

### File checks

tapiOca checks your files at the lowest priority, to find problems before anyone tunes in. It checks the stations' programs and what's shared for Media. Results are kept per file, so a file checked for a station isn't checked again for Media, or the other way around, unless it changes.

While anyone is watching, the checks step aside. The automatic checks wait until no one is watching. **Check files** and the list's re-checks read one file at a time, with a rest between files. ZFS and most NAS disks ignore low disk priority, so reading less at once is what helps.

The checks wait in one line, in this order:

1. **A station's program airing soon** (in the next 3 hours, or in an update about to start) that's due a check.
2. **A file someone just had trouble with.** That can be a copy for an app that couldn't be made or stopped, an app reporting that something didn't play or stopped, or a person's report. tapiOca decodes the minute starting 20 seconds before where it happened, as the deep scan would, then gives the file the quick check. For a report that says where, it also runs the deep scan if those find nothing. Only what tapiOca finds puts the file on the list, so trouble caused by the network or the app changes nothing.
3. **Quick check, when something arrives.** A program new to a station, then anything newly added to a Media folder shared for Media, is quick-checked within minutes, before it airs if possible. The file must open, and picture and sound must decode at five points (start, quarter, half, three quarters and end).
4. **Weekly.** Every program on a station is quick-checked again once a week. This also catches files that went missing or were replaced. Media's files are checked when they arrive, and when someone has trouble with one.
5. **Overnight deep scan.** Between 1 AM and 6 AM, files are decoded in full. To change the time or turn it off, use **Deep scan every night from** on the **Broken files** tab. The stations' programs go first, soonest to air first. Then come Media's files: what's in someone's Resume row, the next episode of a show someone is watching, then the rest, most recently added first. A file that hasn't had its quick check gets one first. The scan stops the moment anyone starts watching and continues later. Each file is deep-scanned once, and again only if it changes. A 45-minute episode usually takes a few minutes.

**Check files** on a station card quick-checks all of its programs right away. A new station gets this automatically.

**A movie in several files** has each of its files checked in order, by both the quick check and the deep scan. A problem in any of them takes the movie off the air, and its entry names the file.

The **Broken files** tab shows how far the checks have gotten, for the stations and for Media, and what the deep scan is doing.

#### What counts as a problem

| Result | What it means |
|---|---|
| **Broken** | The file won't open or has no picture. Or nothing decodes after some point. Or its picture stops early (more than 10 seconds or 2% short of its stated length, whichever is more). Or it can't be read (a disk or share error, seen on two different nights). |
| **Damaged** | The picture breaks up, the sound drops out, or the file skips (see below). No sound, or no picture and sound, for 30 seconds or more partway through. No sound track, or silence all the way through (for programs from 1930 on). A completely black picture. Sound that stops before the picture does, unless it stops during the end credits, over a black picture, or after fading out in the last minute. A file that plays well past its stated length, so its ending would be cut off. |
| **Fine** | A decoder warning about something no one would see or hear, a patched picture shown for an instant, sound lost for less than 20 ms at one spot, anything in the first 2 seconds or last 5, a pause or silence under 30 seconds, a picture held still while sound plays (such as end credits over one drawing), a black opening, and a file slightly shorter than its stated length. |

**How the deep scan judges glitches.** Decoders report many errors that change nothing you'd see or hear. One example is Dolby TrueHD's "quant_step_size larger than huff_lsbs", common in Atmos tracks. Each one costs at most 1/1200 of a second of sound. So tapiOca judges by ffmpeg's report on each frame:

- **Picture.** A picture ffmpeg couldn't decode, or had to patch because part of it was missing or garbled, counts when later pictures are built on it. The damage then stays on screen until the next full picture, often for seconds. One is enough. A patched picture shown for just one frame (a B-frame) doesn't count. Tests comparing damaged files with clean ones found that damage gone within a frame or two.
- **Sound.** Each lost or garbled frame of sound costs a fixed slice of time: about 21 ms for AAC, 32 ms for Dolby Digital, 11 ms for DTS, and under 1 ms for TrueHD. It counts when 20 ms or more is lost within one second, which you'd hear as a click or dropout.
- **Skipping.** Part of the file's container is garbled, so playback jumps ahead.

None of these can freeze a player. tapiOca decodes every program and encodes it again, so players always receive a clean stream.

Each entry says what was found and where, such as "the picture breaks up around 12:31 and 48:02" or "no sound from 12:00 to 12:40". Glitch times are approximate. The real spot can be a few seconds before the time shown.

When an update changes how files are checked, files are checked again under the new rules: quick checks within hours, and deep scans over the following nights. Programs taken off the air by the old quick check go back on the air right away and are re-checked first.

### Replacing files with Sonarr and Radarr

tapiOca doesn't need them. But if you use **Sonarr** (TV) or **Radarr** (movies), tapiOca can ask them to replace files on the Broken files list that a station or Media plays. Both apps get the same choices and limits. Sonarr and Radarr version 3 and later work. For one of a program's versions, this works only when the app's file is that version. Problems people report are replaced only when you choose **Replace** on the report (see [People's reports](#peoples-reports)).

**Turning it on.** On the **Broken files** tab, open **Replacing files with Sonarr and Radarr**. For each app:

1. Check **Use Sonarr for episodes** (or **Use Radarr for movies**).
2. Enter its address, such as `http://192.168.1.10:8989` for Sonarr or `:7878` for Radarr.
3. Enter its API key, found in the app under **Settings → General**.
4. Choose **Test**, then **Save**.

API keys are stored in tapiOca's database (and its backups) and never shown again.

**Choices:**

- **Files to replace:** **Broken or damaged**, **Missing**, or **Both** (the default). Choose **Broken or damaged** if missing files are usually ones you removed on purpose.
- **When to replace:** **Only when I ask** (the default) or **Automatically**.
  - With **Only when I ask**, nothing happens until you choose **Replace with Sonarr** (or **Radarr**) on an entry. After that, the app handles it on its own.
  - With **Automatically**, every entry is replaced without asking. Choose **I'll handle it** on an entry to stop that for it, and **Replace with Sonarr** to start again.
  - **Retry** still means "the file is fine".

tapiOca only asks about what the app is **monitoring** (in Sonarr, both the show and the episode). To tell both apps to leave something alone, unmonitor it there. The entry notes this, and **Try again** picks it up once it's monitored again. tapiOca finds a show by its TVDB ID (or its title) and a movie by its TMDB or IMDb ID (or its title and year). It continues only if exactly one matches.

**What happens:**

1. **A broken or damaged file:** tapiOca first has the app **blocklist** the release the file came from, as **Mark as Failed** in the app's History does, so the app won't download it again. Then the app deletes the file (into its recycle bin, if you set one) and searches for another. This only happens if the app's file is exactly the one tapiOca found broken (same name and size) and the app has a record of downloading it. A file you added by hand can't be blocklisted, so it's left to you.
2. **A missing file:** the app rescans the folder, then searches for it.

Each episode or movie gets up to **3 searches, 8 hours apart**, or sooner if the last search brought a file that didn't work. When the app has a new file, tapiOca asks Plex to scan that folder (or reads its own Media folder again), checks the new file, and puts the program back on the air once it passes. If Plex still hasn't found the file after a day, the entry shows **Can't replace**.

**The same problem twice.** Sometimes the new file has the same problem at the same times (at least half of them within 30 seconds of the old file's). Then the problem may be part of the program itself, such as an old film's transition effects. tapiOca stops, blocklists nothing, and marks the entry **Needs your review**. Watch the program at those times. If it looks fine, choose **Retry**. If not, **Try another file** blocklists that file too and searches again.

Each entry shows what the app is doing: **Replacing**, **Downloading**, **Downloaded**, **Gave up** (3 searches found nothing that works; **Try again** starts over), **Can't replace**, **Needs your review** or **You're handling it**. The **Logs** tab records every step. Unsupported files aren't replaced this way, because you're the best judge of the right version.

### People's reports

People can report a problem from tapiOca's apps: from a movie's or episode's page, from the player's menu, or from a station's player (about what's on it now). They pick the problem from a list rather than typing it:

| Group | Problems |
|---|---|
| **Picture** | No picture; The picture breaks up or freezes; Poor picture quality |
| **Sound** | No sound; The sound cuts out; The sound is out of sync; Wrong language |
| **Subtitles** | Subtitles are missing or wrong |
| **The program** | It won't play; It stops before the end; Wrong episode or movie |
| **Details** | Wrong title, details or artwork |

Each report includes who sent it, from what device, where in the program it happened, and how it was playing (unchanged or as a copy, which version, and which sound track and subtitles). Reports go to the **Broken files** tab, under **Needs you**. Several reports on one program share one row.

| A report of | What tapiOca does |
|---|---|
| No picture, the picture breaking up, no sound, the sound cutting out, stopping early, or not playing | Checks the file right away, ahead of everything but a station's program about to air. It checks around where the problem happened, then runs the quick check. If the report says where and those find nothing, it runs the deep scan. If it finds the problem, the file goes on the list and is replaced according to your settings. If not, the report says tapiOca found nothing wrong, for you to **Dismiss**. |
| The sound out of sync, the wrong language, the wrong episode or movie, poor picture quality, or subtitles | Waits for you, with what tapiOca can tell next to it: the file's sound languages, its length compared with the show's other episodes, its picture size and its subtitles. Choose **Replace with Sonarr** (or **Radarr**), **Find a better copy** or **Dismiss**. Replacing blocklists the release and fetches another, as for a broken file, and the program is off the air until then. **Find a better copy** has the app search for an upgrade, keeping the file until it finds one. |
| Wrong title, details or artwork | Waits for you to fix it in Plex (**Fix Match** or **Edit** on its page there), then **Dismiss** it. |

A report never takes anything off the air, or out of Media, by itself. Only tapiOca's own checks or your choice can do that. Each person can send one report a day about each program, and 10 a day in all. An Admin can turn reporting off for someone with **Can report problems**, on the **Access** tab or under **Reports from tapiOca's apps** on the **Broken files** tab. Admins can always report. Reports are kept while they wait, and for 90 days after they're handled.

## Who can use tapiOca

**At home and from the internet.** Anything reaching `PUBLIC_PORT` (3311), where your reverse proxy or Cloudflare Tunnel points, is from the internet, even from inside your home. A connection to `PORT` (3310 unless you change it) is at home only when all of these hold:

- **A home address.** It comes from an address on your home network or your own VPN, such as 192.168.x.x, 10.x.x.x, 172.16.x.x to 172.31.x.x, or Tailscale's 100.64.x.x.
- **Not by an internet address.** It doesn't ask for tapiOca by an internet address, such as your home's own internet address.
- **Nothing says otherwise.** No forwarding header from a proxy says it's from the internet.

Anything else is treated as from the internet: it gets exactly what the public port gives. So a port forward or a proxy pointed at 3310 by mistake doesn't open tapiOca to the internet (see [Doors left open](#doors-left-open)). Still, never forward 3310, or point a reverse proxy at it.

**Home names.** [Trusted networks](#trusted-networks) also need tapiOca asked for by a home name: an address on your network, a single-word name (such as `nas`), a name ending in `.local`, `.lan`, `.home`, `.home.arpa`, `.internal`, `.localdomain` or `.ts.net`, `BASE_URL`'s name, or a name listed under [Names for tapiOca at home](#names-for-tapioca-at-home). Asked for by any other name, such as `tv.example.com`, a connection at home is never trusted, and Admins get an alert. With signing in off, it gets only tapiOca's page, saying to add the name, and the tuner: a web page elsewhere can't point a name of its own at tapiOca and use your browser to change it (this is called DNS rebinding).

**Signing in.** A new tapiOca has everyone sign in, at home and away. The setup's step 4 makes you the first Admin, and can let your home network's devices skip signing in (see [Trusted networks](#trusted-networks)). You can also add the first user on the **Access** tab, with a name and a password (see [Passwords](#passwords)). **The first user is always an Admin**, and you're signed in right away. After that, everyone else sees a sign-in page, or **Who's tuning in?** on a trusted network. Until there's an Admin, tapiOca's page and apps are open to anyone at home, and they can change anything, as an Admin can. Nobody can use them from the internet then, even with **Away from home** on: tapiOca's apps there say "This tapiOca client can't reach the server. Please check back later." tapiOca's apps work from the internet once **Away from home** is on, on the **Access** tab. Signing in doesn't change who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself.

**Updated with signing in off.** A tapiOca that had signing in off (**Anyone on my network**) before 1.36.0 keeps working the same way at home. Admins get an alert suggesting signing in, with your home network trusted so its devices skip it (see [Doors left open](#doors-left-open)).

| Role | Can do |
|---|---|
| **Admin** | Everything. |
| **User** | Watch the stations and Media their Viewing Level allows, and see the Stats tab. Make stations (3 by default; an Admin can choose none, 1, 3, 5, 10, 25 or no limit) and change or delete only their own. On a Viewing Level with limits, they can only watch. Add logos and Intro Bumper videos (only Admins can delete them). Can't open **Setup**, **Broken files**, **Logs** or **Access**. |

- **Always an Admin.** There's always at least one Admin: the last one can't be removed or made a User. Removing people never turns signing in off. Locked out? See **Locked out?** below.
- **Older stations.** Stations made before sign-in was turned on, or by a removed user, can be changed only by Admins.
- **Managing people.** On the **Access** tab, an Admin can rename people (including themselves and other Admins), change roles and set new passwords.
- **Renaming.** A new name must differ from everyone else's, ignoring capitalization, as for a new user. The person signs in with it from then on and keeps everything: their sign-ins and linked devices, the stations they made, their Viewing Level, where they are in what they watch, and their stats. tapiOca's apps show the new name the next time they check.
- **Your own account.** Choose your name at the top of the page, or Options in tapiOca's apps, to change your password or sign out.
- **Permissions.** **Can change their own password**, **Can change their own PIN** (from 1.36.2) and **Can report problems** (see [People's reports](#peoples-reports)), under each person's buttons, are on by default. Admins can always do all three. A new password signs that person out everywhere else.
- <a id="passwords"></a>**Passwords.** From 1.36.2: at least 12 characters, with no rules about symbols or capitals. That's less than NIST's guidelines (SP 800-63B) ask for: at least 15 characters where a password is the only way to sign in, as it is in tapiOca. A few words together work well. tapiOca turns away the most common passwords (a list kept in tapiOca, from the UK National Cyber Security Centre's 100,000 most used; nothing is sent anywhere to check one), passwords that repeat a character or run in order, and ones built from the person's name or tapiOca's. Passwords set before 1.36.2 keep working. Every password box has **Show**, to see what you typed.
- **No password.** A User may have none. They can then only be picked on **Who's tuning in?** at home, or signed in on a new device with an invite code. A PIN works only on a device that's already signed in, never to sign in a new one.
- **Last signed in.** Each person's last sign-in shows its date and time, and below it the address it came from, as the access log has it. (Through a [trusted proxy](#trusted-proxies), it's the visitor's, as the proxy saw it. Through a proxy you haven't listed, it's the proxy's own address.)
- **Sign-in limits.** A sign-in lasts 30 days after it was last used. After 5 wrong passwords from one address within 15 minutes, that address has to wait. That's the visitor's own address only through a trusted proxy, or Cloudflare's own network. Passwords are stored only as salted hashes.
- **Page timeout.** tapiOca's page signs you out after an hour without activity. tapiOca's apps stay signed in. At home, you can sign in again with just your PIN (if you have one), on a browser where you've signed in with your password before. "At home" means tapiOca's address on your home network, as above. Through its internet address (your reverse proxy or tunnel), or anything tapiOca treats as from the internet, it's always your password, even from home. The sign-in page says which. After updating from a version before 1.32.0, each browser needs your password once before the PIN works there. After 5 wrong PINs, wait 15 minutes. If you sign out on purpose, or your password changes, that browser needs your password next time.
- **No password for Plex.** Plex, Jellyfin and other apps never need a password, just like a real HDHomeRun. The tuner, guide, streams, logos and playlist stay open on your network. To limit all but the logos to devices and networks you list, choose **Only these devices** under [Tuner access](#tuner-access).

### Trusted networks

Devices on a trusted network skip signing in. Nothing is trusted until an Admin adds it, under **Trusted networks** on the **Access** tab (or in the setup's step 4). Add your own home network, one device, or your own VPN. **Never add a guest network.**

- **What to add.** A whole home network, such as `192.168.1.0/24`. One device's address, such as `192.168.1.44`. Your own VPN's network, such as `10.8.0.0/24`. Give it a name if you like, such as "Home Wi-Fi". **Add the network you're on** adds yours in one step. The tab says where you are: "You're at 192.168.1.44, on Home Wi-Fi."
- **What each one gives.** **Who's tuning in?** (the default): each person picks themselves, and kids get their own limits. It lists people shown on **Every device at home** or **Every device, at home and away**. Anyone with a PIN is asked for it, and an Admin always is (their PIN, or their password if they have none). Or **Signed in as** a person: the device is signed in as them. An Admin can be signed in only on one device's address. Whoever has that address is that person, so reserve it for the device in your router's DHCP settings.
- **Anyone can still sign in as someone else.** **Sign in with a password** is always there.
- **Home addresses only.** Internet addresses are refused. A network wider than 256 addresses, such as `192.168.0.0/16`, asks first, because it often takes in guest networks too. List up to 50. When two overlap, the narrower one wins: `192.168.1.44` signed in as Ada works inside a `192.168.1.0/24` on Who's tuning in?
- **Where it works.** In tapiOca's apps (1.36.0 and later) and on tapiOca's page. Plex, Jellyfin and other apps use [Tuner access](#tuner-access) instead.
- **Only there.** Sign-ins and devices a trusted network makes work only on that network: never on another, away from home, or on the public port. Changing or removing the network ends them. So does removing the person it signs in as. Making that person an Admin ends what was signed in for them with no PIN or password, and turns a network that signs them in into **Who's tuning in?**, until you choose **Signed in as** them again.
- **Only when tapiOca can be sure.** Trust needs an Admin (signing in on), a connection at home asking for a home name (see [Who can use tapiOca](#who-can-use-tapioca)), and tapiOca able to see where connections come from (see [When tapiOca can't see where connections come from](#when-tapioca-cant-see-where-connections-come-from)). A device that sends forwarding headers, and isn't a [trusted proxy](#trusted-proxies), is never trusted. Through a trusted proxy, the visitor's address counts, but a network that signs in an Admin never applies there. The network around it does, if there is one. Nothing is ever trusted through Docker's own address, even listed as a trusted proxy.
- **Wrong PINs.** Each person's own limit applies: after 5 wrong PINs, they wait 15 minutes, on every device. After 10 wrong PINs from one device's address in an hour, that device needs a password, or a wait. Anyone with a password may give it instead of a PIN. When an Admin's PIN is locked, Admins get an alert: "An Admin's PIN was entered wrong 5 times, so it's locked for 15 minutes. If that wasn't them, change it on the Access tab."
- **For watching.** A sign-in a trusted network makes (with a PIN, or nothing) is for watching. It can't change passwords or PINs, add people, make API tokens or invite codes, or link an app. An Admin signed in this way is a User there, and gives their password for anything only an Admin does, such as the **Access**, **Setup** and **Logs** tabs: sign out, then choose **Sign in with a password**. Admin alerts don't show there either; they show after a password sign-in, and go to the alert web addresses as always. Picking yourself on Who's tuning in? with your password is an ordinary sign-in.
- **Limits.** One device's address can ask a trusted network for 20 sign-ins in 15 minutes. A network's sign-ins never sign anyone out elsewhere, and a network with 100 devices linked links another only in place of one never used, or unused for 30 days.

### Trusted proxies

List your reverse proxy or tunnel under **Trusted proxies** on the **Access** tab, by its address on your home network. List up to 10. Home addresses only, or `127.0.0.1` for a tunnel in tapiOca's own container.

- **Never by headers alone.** tapiOca never decides a device is a proxy because it sends forwarding headers. Only a listed proxy is believed.
- **Who the visitor is.** From a listed proxy, tapiOca reads the last address in each of `X-Real-IP`, `X-Forwarded-For` and `Forwarded` it sends. They must all name the same visitor. If they don't, tapiOca can't tell who it is, and treats the request as from the internet. The access log calls it "an unnamed visitor via" the proxy, and its wrong passwords count on their own, never as the proxy's address, which everyone through it shares.
- **Headers from anything else.** They're ignored: they never say who a visitor is, and never give trust. They can only take trust away. If they name an internet address, or can't be read, the request is treated as from the internet. Admins get an alert: "tapiOca is ignoring forwarding headers from a device that isn't a trusted proxy. If it's your reverse proxy, add it under Trusted proxies on the Access tab." The alert never gives the address. The **Access** tab shows it to Admins, until the proxy is listed: "A proxy at 192.168.50.2 isn't trusted, so tapiOca ignored what it said about its visitors."
- **HTTPS.** tapiOca believes a proxy saying a request came over HTTPS only from a listed proxy. So tapiOca's apps from the internet need their proxy listed.
- **The proxy's own computer.** A listed proxy sending no forwarding headers at all, asked for by an address or a home name, may be its own computer: Plex there, say. From 1.36.2, Plex's tuner, guide and logos are its computer's, at home, so Plex keeps them (before, Plex lost the tuner). Anything else from it, the page or the API, is still a proxy's, for the internet, and nothing from it skips signing in. **Known limit:** a proxy that sends no headers at all (HAProxy without `option forwardfor`, a plain TCP forward), listed and pointed at the home port by mistake, can't be told from its computer, so the tuner is reachable through it, as through any proxy not listed. Point a proxy at the public port, 3311, and the outside check says so if it isn't.
- **Trust this proxy.** When tapiOca checks its address from outside (under **tapiOca's apps away from home**, and in the setup's **Watching away from home**) and finds it came through a proxy that isn't listed yet, it names the proxy's address and offers **Trust this proxy**, which lists just that address and checks again. It's not offered for an internet address, or when 10 are listed already. Clicking it checks again first, and lists the address only if that check sees it too.
- **A proxy in another container on the same server.** It reaches tapiOca from Docker's own address (its gateway, such as `172.17.0.1`), which carries other connections too: other containers, and devices over IPv6. List that address for your public port, so wrong passwords count by each visitor there (the internet's own limit holds too). But nothing is ever trusted through it, and wrong passwords on the home port through it count as it. What arrives from it with no forwarding headers, such as Plex or another container, is taken as from that address, at home, as if it weren't listed (from 1.36.1). The **Access** tab marks such an entry. For trusted networks through your proxy, put it on a Docker network shared with tapiOca, with an address of its own, and list that.
- **One address.** A proxy has one address: listing more (a network) asks first, as every device there could say who a visitor is.

### Names for tapiOca at home

If you open tapiOca at home by a name such as `tapioca.example.com` (split DNS, where your home's own DNS answers with tapiOca's home address), add it under **Names for tapiOca at home** on the **Access** tab. Your away-from-home address's name can't be one: that's how the internet reaches tapiOca (made the away address later, it comes off this list). tapiOca then knows that's you at home and not a tunnel, so trusted networks work by that name. List up to 10. Names that are always home's, such as `nas.local`, need no listing (see [Who can use tapiOca](#who-can-use-tapioca)).

### Doors left open

tapiOca is built to stay safe when a door is left open by mistake. When it can't be sure a connection is from home, it treats it as from the internet: it gets exactly what the public port gives. The alerts never include an address or a name. For the first four below, the **Access** tab shows Admins the last address and time, and the access log notes each, with its address, at most once an hour.

| Left open | What tapiOca does | Admins' alert |
|---|---|---|
| **The home port forwarded on the router**, or opened by your internet address | Treats it as from the internet | "tapiOca is being reached from the internet on its home port. Close that port forward. Until then, tapiOca treats those connections as from the internet." |
| **A reverse proxy or tunnel pointed at 3310** | Treats what it sends from the internet, or can't name, as from the internet | "A reverse proxy or tunnel is sending internet visitors to tapiOca's home port, 3310. Point it at the public port, 3311, instead. Until then, tapiOca treats them as from the internet." (With your own ports. With no public port, it says to set `PUBLIC_PORT`.) |
| **An internet name on 3310**, with no forwarding headers | Never trusts it. With signing in on, it isn't refused, as it may be a name your home's DNS gives. With signing in off, it gets only the page and the tuner | "Something reached tapiOca's home port by an internet name. If a tunnel or proxy points at port 3310, point it at the public port instead. If it's a name you use at home, add it under Names for tapiOca at home on the Access tab." |
| **Forwarding headers from a device that isn't a trusted proxy** | Ignores them, and never trusts that device | "tapiOca is ignoring forwarding headers from a device that isn't a trusted proxy. If it's your reverse proxy, add it under Trusted proxies on the Access tab." |
| **Docker hiding every device's address** | Turns trusted networks off | "tapiOca can't see where connections come from: they all arrive from Docker's own address. Trusted networks are off, and tapiOca can't tell the internet from home. The Access tab says how to fix it." |
| **Signing in left off** | Open at home only. Anything treated as from the internet gets "This tapiOca client can't reach the server. Please check back later.", and no one can make the first Admin from there | "Signing in is off, so anyone on your home network can change anything in tapiOca. Add a user on the Access tab to turn it on, and trust your home network so its devices skip signing in." |
| **The tuner and an internet address** | Never gives it the tuner, even if it's listed under **Only these devices** | None |

The first four alerts are marked fixed after a day without. The Docker alert is fixed once tapiOca can see where connections come from again, and the signing-in alert once signing in is on.

### When tapiOca can't see where connections come from

Some Docker setups pass every connection through Docker's own address (its gateway, such as `172.17.0.1`). That hides each device's own address. Docker's userland proxy does this, often for IPv6, and Docker Desktop for Mac and Windows always does.

- **Hidden.** In an hour, if 20 page or app requests on the home port (not the tuner, icons or logos, which Plex or Jellyfin in Docker fetch that way) come from Docker's address and fewer than 5 from anywhere else, tapiOca calls addresses hidden. Trusted networks are then off for everyone, the setup offers no network, the **Access** tab says why, and Admins get an alert. It ends once 5 requests come from devices seen as themselves, or when tapiOca restarts.
- **Partly hidden.** When some requests come through Docker's address and some don't, the **Access** tab says so. Open tapiOca by its IPv4 address, such as `http://192.168.1.20:3310`.
- **Never trusted.** Docker's gateway and tapiOca's own addresses carry other devices' connections, so they're never trusted, even inside a trusted network. tapiOca can't tell your router's address apart this way: a router that forwards a port to tapiOca and rewrites where it came from, or a VPN that does (masquerading), shows as the router itself. Don't trust a network with such an address in it, and never forward the home port.
- **The fix.** Run tapiOca with host networking (`network_mode: host` in the YAML or Compose file, in place of its `ports:` lines). Or turn off Docker's userland proxy (`"userland-proxy": false` in Docker's `daemon.json`), then restart Docker and tapiOca.
- **No fix.** On Docker Desktop for Mac or Windows, there's none: every device signs in.
- **Run from source.** When tapiOca can't read the machine's routing table (run from source on a computer that isn't Linux, say), trusted networks are off too, and Admins with networks listed get an alert.

### Viewing Levels

Each person has a **Viewing Level** that sets what they can see in tapiOca's apps and on its page. Admins always see everything. Choose a person's level next to their name on the **Access** tab. Under **Viewing Levels**, you can rename, change or remove the other built-in levels, and add as many of your own as you need, such as "Adults" with no R-rated movies or unrated titles, or "Grandparents".

**The level new people start on.** In the **Viewing Levels** panel, **New people start on** is the level everyone you add as a User starts on. It's Unrestricted until you choose another. The **Add a user** form has a **Viewing Level** choice too, set to that level, to choose another for that person. Admins always see everything. If you remove the level new people start on, they start on Unrestricted again. The setup asks about it too, in its **Who sees what** step.

| Level | Movies up to | TV up to | Unrated titles |
|---|---|---|---|
| **Unrestricted** (where new people start, until you choose another; can't be changed) | No limit | No limit | Shown |
| **Teen** | PG-13 | TV-14 | Hidden |
| **Kid** | PG | TV-PG | Hidden |
| **Young Child** | G | TV-G | Hidden |

- **Ratings.** Plex's content ratings are read as ages, for the US and other countries alike (such as `gb/15` or `de/12`). An episode counts as its show's rating, or its own if that's stricter. A title with no rating, or one tapiOca doesn't recognize, counts as unrated.
- **Media folders.** A level can also be limited to some Media folders. That way, a show in both "TV Parents" and "TV Teens" is seen only through the Media folder a person's level includes.
- **Genres, tags, collections and studios.** A level can also hide any show or movie with a genre, tag, collection or studio you name, whatever its rating. Choose **Edit** beside a level (or **Add a level**), type a name under **Genres**, **Tags**, **Collections** or **Studios**, and choose **Add**. Plex's own names are offered as you type. Tags are what Plex calls labels. Capital letters don't matter. An episode counts as its show, with its show's genres, tags, collections and studio. A title with no genre isn't caught by a genre. The levels' table shows what each one hides in **Also hides**, such as "2 genres and 1 studio".
- **What they see.** Choose **What they see** next to someone's name (not an Admin's: Admins see everything). It shows "(3 set)" when you've chosen anything there. For someone named Kit, **What Kit sees** has three parts:
  - **Stations:** allow or block a station for them, or leave it as their level says. It also shows why each station is shown or hidden.
  - **Also hidden for Kit:** genres, tags, collections and studios, and shows and movies you find by typing part of a title. These are hidden for Kit, whatever their level shows.
  - **Allowed for Kit in Media:** shows and movies their level would hide, shown to Kit anyway, whatever the rating, genre or tags. They still need to be in a Media folder the level includes. A show or movie under **Also hidden** stays hidden; a genre, tag, collection or studio there doesn't hide one allowed here.
- **Their own ratings.** Ratings belong to a level. To give one person ratings of their own, give them a level of their own.
- **Stations are all or nothing.** Everyone watching a station sees the same stream. So a station is shown only if everything it plays is within the person's level and isn't hidden for them. To show or hide a station for someone anyway, allow or block it under **What they see**. A show or movie allowed for someone doesn't show a station that plays it: allow the station instead.
- **Nothing hidden shows.** What someone can't see isn't in Media, search, **More like this**, cast and crew pages, the Resume row, the guide or "on now" for them. Its address answers as though it doesn't exist.
- **Commercials and trailers.** On a station someone with limits can see, a commercial or trailer plays only if its folder is rated, and at or below the station's highest-rated program. Rate the folders under **Commercials and trailers**, below the levels (it's there once tapiOca has found clips): **Commercials**, **Trailers**, and each decade's folder, such as "Commercials from the 1960s". Commercials take TV ratings (TV-G to TV-MA), and trailers take movie ratings (G to NC-17). A decade's folder is rated as its kind is, unless you rate it. Until then, those stations skip clips that aren't rated, and a plain card fills the time if one was already chosen. An alert says how many stations skip some. On a station only people without limits can see, every clip plays. A clip never changes who can see a station.
- **Watching only.** People on a level with limits, or with anything under **Also hidden**, can watch what they can see, but can't make stations, because the station editor shows your Media folders as a whole.
- **Plex and other apps.** Plex, Jellyfin and other apps don't report who's watching, so they show every station. To keep stations from some people in Plex, see **Blocking stations for some Plex users**, below.
- **It's logged.** The access log (**Logs**, then **Access**) records each change, such as "Ada changed the Viewing Level Kid (movies up to PG, …, hiding 2 genres and 1 studio)", "Ada set what's hidden and allowed for Kit (hiding 1 genre, 2 titles allowed)" and "Ada rated the clip folders: commercials/1960s TV-14".

tapiOca learns the ratings of what's on each station as it checks Plex for updates. Until it knows a station's ratings, that station is hidden from anyone with limits. While a level or a person hides by genre or tag, tapiOca also asks Plex for each title's genres and tags in the background: again every day, and at once when you hide a new name. Until it knows a title's, the title is hidden from anyone whose level or own choices hide by them. So the first time someone limited this way opens a big Media folder, it shows some titles at first, and the rest as Plex answers.

### Parental limits: what tapiOca enforces, and what it can't

Viewing Levels are limits in tapiOca's apps and on tapiOca's page. They don't reach anything else on your TV.

**What tapiOca enforces.** For someone signed in as themselves, on your tapiOca server, in tapiOca's apps and on its page:

- **What they find, see and play,** as their Viewing Level and **What they see** say. Nothing hidden shows anywhere, and its address answers as though it doesn't exist.
- **Stations, all or nothing.** A station that plays anything hidden for them is hidden, unless you allow that station for them.
- **Commercials and trailers,** rated as above, on stations people with limits can see.

**What limits don't cover:**

- **Plex, Jellyfin and anything else on the tuner.** They don't say who's watching, so they show every station. See [Tuner access](#tuner-access) and [Blocking stations for some Plex users](#blocking-stations-for-some-plex-users).
- **Devices without PINs.** On a shared device, anyone can pick anyone without a PIN on **Who's tuning in?** Give everyone without limits a PIN on devices people with limits use.
- **Signing in as someone else.** Someone who knows another person's password can sign in as them on their own device.
- **A rating or genre Plex has wrong, or doesn't have.** tapiOca goes by what Plex says. Unrated titles follow the level's **Unrated titles** setting.
- **What's inside a program,** beyond its rating, genres and tags.

Use your devices' own controls too, such as Apple's Screen Time or Google's Family Link.

### Linked devices and Who's tuning in?

tapiOca's apps can share one device among several people, such as the living room TV. The first time someone signs in on the device, with their password or a code entered on tapiOca's page, the device is **linked**. From then on, it opens on **Who's tuning in?**, and whoever is watching picks themselves.

- **Who's on the list.** Choose **Devices** next to a person's name, then one of these:
  - **Only devices they sign in on:** at home and away. Unless Bo has signed in on your TV, he isn't on its list, and you aren't on his phone's.
  - **Every device at home:** for a household. They're on every device while it's at home or on your VPN. Away from home, they're only on devices they signed in on or that you choose.
  - **Every device, at home and away:** even a phone at a friend's house.
  - **Only devices you choose:** such as a family iPad that travels.
- **Where new people start.** **New people show on**, under **Linked devices**, sets this. The default is **Only devices they sign in on**. If you chose **Devices at home** there before 1.31.0, that choice stays (as **Every device at home**). Someone with no password and no PIN can't sign in, so on that default they start on no device's list: choose theirs under **Devices** beside their name (with **Every device at home** as the default, they start there).
- **Changing everyone.** Changing **New people show on** doesn't move anyone already added. **Use for everyone**, next to it, does. It first asks, showing how many people it changes. Devices you chose for someone stay chosen. People with no password and no PIN can't be on **Only devices they sign in on**, so that choice leaves them unchanged, and the page names them ("Kept as they were: Kids (no password or PIN)").
- **Signing in again.** With **Only devices they sign in on**, someone who used to pick themselves on a device must sign in on it once (**Sign in**, with their password or an invite code) to be on its list again. Picking yourself isn't signing in.
- **PINs.** A person can have a 4-digit PIN, which the device asks for when they pick themselves. An Admin without a PIN enters their password instead. After 5 wrong PINs, that person must wait 15 minutes, on every device.
- **Choosing a PIN.** The first time someone signs in on a device with their password or an invite code, the app asks them to choose a PIN or none. They can change it in the app's Options. An Admin who has a PIN keeps one. An Admin can set, change or remove anyone's PIN on the **Access** tab, with **Set PIN** (or **Change PIN**, for someone who has one, however they set it) beside **New password**, or under **Devices**.
- **No password needed.** A User can have no password, such as a "Kids" user who only picks themselves on the TV. Without a password or a PIN, they can't sign in by name, so they can only be on **Every device at home** or **Only devices you choose**.
- **Sign in on a new device.** Choose **Sign in** on Who's tuning in?, then enter your name and password, or an **invite code** an Admin made for you under **Devices**. An invite code works once, for 7 days. You're then on that device's list. Anyone can take themselves off a device's list.
- **Linked by a trusted network.** On a [trusted network](#trusted-networks) that gives **Who's tuning in?**, tapiOca's apps (1.36.0 and later) link the device by themselves. The **Access** tab lists it as "Linked by the trusted network Home Wi-Fi". It works only on that network. Elsewhere it says "This device skips signing in only on its trusted network. Sign in to use tapiOca here." A password or invite code used on it makes it an ordinary linked device. A network links up to 100 devices, and then another only in place of one never used, or unused for 30 days.
- **Unlinking.** **Linked devices** on the **Access** tab lists each device and who's on its list. **Unlink** signs the device out at once.

A sign-in from Who's tuning in? lasts a day from when it was last used, so a shared device returns to the list instead of staying signed in as someone.

**Access log.** On the **Logs** tab, check **Access** to see sign-ins, failed sign-ins, sign-outs and changes to users. The newest 2,000 entries are kept across restarts.

**Locked out?** Create an empty file named `reset-access` in tapiOca's data folder (for example, `sudo touch data/reset-access`) and restart the app. Every user is removed, and so is every trusted network that signed in a person, and every trusted proxy. The page is open again at home, and the file is deleted.

### Blocking stations for some Plex users

*Optional; needs Plex Pass.* Plex can't hide a station from one person. Every station appears in the guide for everyone with Live TV on your server, and Plex's parental controls don't cover Live TV. Instead, tapiOca can stop someone's playback.

On the **Access** tab, under **Block stations for some Plex users**, choose which stations each Plex user can't watch. Check **Stop Plex users from watching stations blocked for them**, and choose **Save**. When a blocked user tunes in, Plex stops their playback within seconds and shows "This station isn't available on your Plex account." in Plex apps that show messages. If they tune in again, it's stopped again. The tab lists recent stops, and the **Logs** tab records each one.

**Requirements:**

- **Plex Pass** on the account that owns your Plex server. The tab shows whether Plex reports it.
- **Watching in a Plex app.** This covers you, your Plex Home users (including managed users), and friends you've shared Live TV with. Apps using the M3U playlist aren't covered.
- **A Plex user for each person.** Everyone sharing one Plex account counts as one user.
- **Sign-in turned on in tapiOca.** Otherwise anyone on your network could turn blocking off.

tapiOca only stops a stream when it's sure which station it is: only one station with viewers is airing exactly what Plex shows, or only one matches the station number Plex reports. If two stations air the same program at once and Plex gives no station number, tapiOca can't tell them apart and stops neither. The log notes this once. While a blocked user's station has viewers, tapiOca asks Plex what's playing every 5 seconds.

### Tuner access

The **tuner** is what Plex, Jellyfin and other apps use, and none of them can sign in. It's the HDHomeRun tuner itself, the guide, the list of stations, the stations' streams and the guide's pictures. All of it is on tapiOca's home port (3310, unless you set `PORT`), never the public port, and never for anything tapiOca treats as from the internet. Station logos aren't part of it. On the **Access** tab, under **Tuner access**, choose who can use it:

- **Any device on my home network.** This is the default.
- **Only these devices.** Only the devices and networks you list, with a name if you like: a device by its IP address, such as `192.168.1.44`, or a whole network, such as `192.168.1.0/24`. Networks must be home addresses. List up to 50 devices and networks in all. **Plex server only** lists just Plex's own address, in one step, after showing you which address that is.

**Recent tuner connections** shows each device that used the tuner in the last 7 days: its name (what it calls itself), its address, what it asked for, when, and whether it was refused. **Allow**, beside one, lists it. Each refused request is logged in plain words, once an hour for each address, and ten addresses an hour at most.

- **Plex's address.** While only listed devices can use the tuner, the tab warns you when Plex can't use it, because Plex can't show your stations then. Plex in Docker often reaches tapiOca from the Docker network's address, not the server's. So choose **Plex server only**, or **Allow** beside Plex's recent connection, rather than typing in the server's address.
- **What a device calls itself.** Any device can call itself Plex. So tapiOca takes Plex's address from `PLEX_URL` when Plex uses the tuner from there, and never from a device it turned away. When something calling itself Plex is turned away, the tab says just that. Check the address before you choose **Allow**.
- **The Docker network's address.** Every container on the same server reaches tapiOca from that one address, not just Plex: listing it lets them all use the tuner, including a reverse proxy.
- **An IP address isn't a password.** On your home network, a device can take another's address. Tuner access keeps out devices that shouldn't use the tuner by mistake, such as a smart TV app finding it on its own. It can't stop someone at home who means to get in.
- **Never an internet address.** A device at an internet address never gets the tuner, even if it's listed (see [Doors left open](#doors-left-open)).
- **Sign-in.** With sign-in off, anyone on your home network can open tapiOca's page and change Tuner access, so turn sign-in on first. The tab reminds you.
- **tapiOca's own apps.** Signed in, they never need listing: at home too, each gets stream addresses of its own, so changing Tuner access never stops one. With signing in off, an app is a device like any other.
- **Scripts.** For scripts using [tapiOca's API](#tapiocas-api), a program's `art` address is part of the tuner.

Plex, Jellyfin and other apps are never limited in any other way.

## Stats

The **Stats** tab shows how much each station is watched: viewings, hours watched, average viewing, when it was last watched, and its most-watched show or movie. Below that are the most-watched shows and movies overall, and the times of day people watch. Choose **Today** (since midnight), **7 days**, **30 days** or **All**.

A viewing counts once it lasts a minute, so flipping past a station doesn't count. Viewings are counted per stream, so several people watching one station together in Plex can count as one viewing. Each of tapiOca's apps counts on its own. Stats are kept for 400 days, and a station's stats are deleted with it.

Admins see more, and so does everyone while sign-in is off:

- **Server**, at the top, updated every 5 seconds while the tab is open. It shows the processor and memory tapiOca uses and the whole machine's (or the container's memory limit, if it has one), what it's sending and receiving, which GPU is in use with how many stations and copies, and the data folder's free space. Each has a chart of its last 10 minutes. Figures come from Linux itself (in Docker, the container's own). Anything tapiOca can't read shows "not available".
- **Watching now**: one row for each person watching. It shows who, what (a station and what's on it, or something from Media), which app on which device, at home or away, and since when. It also shows how the video is sent: unchanged, repackaged or converted, its picture size and bitrate, and on the GPU or the processor.
- **Top people**: who watched most, stations and Media together, and what each person watches most. In tapiOca's apps, viewing counts for whoever is signed in. At home, it counts for whoever's app last asked for the stations from that device.
- **Plex viewing per person.** While a station has viewers, tapiOca asks Plex every 30 seconds what it's playing and to whom, and matches each Live TV session to a station. Plex users are marked **Plex**. Viewing in other apps isn't counted per person, and neither is Plex time when two stations air the same program at once. If your Plex token isn't allowed to see what's playing, the tab says so.
- **Top Media**: the shows and movies played most in Media, with hours and plays. Watching the same thing again on the same device soon after (with another sound track, or a smaller version) counts as one play.

## tapiOca's API

*Optional.* Your own scripts, home automation (such as Home Assistant) and other players can use tapiOca's API, under `/api/v1`. It covers the server, its stations with what's on now and next, the guide, each station's HLS stream, and how tapiOca is doing. With an Admin token, scripts can also update a station from Plex, check a station's files, ask Plex to refresh its guide, and make a backup. It's documented in [docs/api.md](docs/api.md), with an OpenAPI spec at `/api/v1/openapi.json` (also in [docs/openapi-v1.json](docs/openapi-v1.json)).

Version 1 is a stable contract: it only grows. New fields and addresses may be added, but nothing is renamed, removed or changed in meaning. A change that would break a client comes as version 2, served next to version 1. Version 1 then carries `Deprecation` and `Sunset` headers for at least 6 months before it's removed.

**API tokens.** While sign-in is off, the API needs no token on your network. Once sign-in is on, an Admin makes a token for each script on the **Access** tab, under **API tokens**. Give it a name, choose **Viewer** (read only) or **Admin**, and choose when it expires. The token is shown once, so copy it then. tapiOca keeps only a hash of it. Scripts send it as `Authorization: Bearer <token>`.

- **API only.** A token works only with the API, never with tapiOca's page. It never does more than the Admin who made it may do now.
- **Revoking tokens.** The Access tab shows when each token was last used. Revoke one there at any time. Removing the Admin who made a token revokes it too. The access log records each token made and revoked.

**From the internet.** API tokens are refused on the public port until an Admin checks **Accept API tokens from the internet** on the **Access** tab. Even then, they work only over HTTPS, through a reverse proxy or a Cloudflare Tunnel (see [Reaching tapiOca from outside your home](#reaching-tapioca-from-outside-your-home)). With Cloudflare Access in front, a script also needs a Cloudflare Access service token. A VPN is simpler still: tapiOca treats a script on the VPN as on your home network.

tapiOca's own apps also use addresses under `/api/internal`. Those are for the apps only, aren't part of the API, and may change with any release.

## Settings

tapiOca is set up mostly on its page. These environment variables, in the YAML or `docker-compose.yml`, cover the rest:

| Variable | Default | What it does |
|---|---|---|
| `PLEX_URL` | *(none)* | Your Plex server's address, such as `http://192.168.1.10:32400`. Required for Plex; leave it out to use only [Media folders of your own](#media-folders-of-your-own). |
| `PLEX_TOKEN` | *(none)* | Your Plex token (see [Finding your Plex token](#finding-your-plex-token)). Required for Plex. |
| `TAPIOCA_INSTALL` | *(none)* | How you installed tapiOca: `truenas`, `compose`, `unraid`, `synology`, `docker-desktop` or `docker-run`. The page uses it to show how your install updates (see [Updating](#updating)). |
| `TZ` | `UTC` | Your time zone, such as `America/Chicago`. Used for the clock, specials, the overnight checks, backups, stats and log times. |
| `MEDIA_DIR` | `/media` | Where your media is mounted inside the container. Media folders of your own are chosen from inside it. |
| `PATH_MAPPINGS` | *(none)* | For unusual layouts only: `plex/path:local/path`, with several separated by `;`. |
| `HW_ACCEL` | `auto` | `auto`, `nvidia`, `intel`, `amd` or `cpu`. See [GPU encoding](#gpu-encoding). |
| `HW_DEVICE` | *(automatic)* | With more than one GPU: a render node (`/dev/dri/renderD129`) or an NVIDIA GPU number. |
| `PORT` | `3310` | The port for Plex, other apps and your home network. |
| `PUBLIC_PORT` | *(off)* | A separate port for the page, and tapiOca's apps, from the internet. Must differ from `PORT`. See [Security and remote access](#security-and-remote-access). |
| `AUDIO_LANGUAGE` | `eng` | Preferred language for sound tracks and subtitles. |
| `FRIENDLY_NAME` | `tapiOca` | The tuner's name in Plex. |
| `BASE_URL` | *(automatic)* | Only if Plex reaches tapiOca at a different address than your browser does. |
| `IDLE_GRACE_SECONDS` | `20` | How long a station keeps running after its last viewer leaves. |
| `AUDIO_BITRATE_KBPS` | `192` | The stations' sound bitrate. |
| `DATA_DIR` | `/data` | Where tapiOca keeps its data inside the container. |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe` | For a custom ffmpeg build. The image's own is recommended. |

Picture sizes and the number of tuners are set on the page. Versions before 1.14 used `TUNER_COUNT` and `VIDEO_HEIGHT`. If they're still set, the page starts from them once and then ignores them, and the **Logs** tab says so. `VIDEO_WIDTH` and `VIDEO_BITRATE_KBPS` are no longer used.

## Troubleshooting

Start with the **Logs** tab, which shows the newest 200 entries. Check **Warnings** or **Errors** to filter, and use **Copy** to paste them into a message. `docker logs stationplay` (or the app's logs in TrueNAS) has everything.

**What's playing.** The log names each station by its number and name ("station 2, Cartoon Classics") and describes what plays as it starts:

- **A station's program:** its file, its picture and sound ("1080p H.264, 5.1 E-AC-3"), and how the station makes it ("made 720p at 3.5 Mbps on the Intel/AMD GPU", "HDR made ordinary", "subtitles drawn in"). The same line notes a viewer tuning in from the beginning.
- **Media in tapiOca's apps:** who started what, in which app on which device, at home or away; its file, picture and sound; and how it plays: unchanged, repackaged (and what changed, such as its sound made AAC stereo), or converted.
- **A converted copy:** what it was converted to, on the GPU or the processor, and why. The reason can be something the device can't play, a picture made smaller to fit the connection, subtitles drawn in, or night mode's sound.
- **A step down in quality:** when an app switches to a smaller version or copy, one line shows from what to what and why, with the app's own reason when it sends one.
- **Stopping:** who stopped what, where in it, and how long they watched. An app watching a station reports when it stopped, and after how long.

**Problems in the apps.** At the top of the **Logs** tab, tapiOca's apps report problems as they play: a station that doesn't start or stops, something from Media that doesn't play, playback that can't keep up, the app closing unexpectedly, or the app not reaching tapiOca for a minute or more (such as "Den couldn't reach tapiOca for 12 minutes · No network on this device"). An app that can't reach tapiOca sends what went wrong once it's back, with the time of each problem.

Each problem shows how often it happened, on how many devices, for whom, and on what kinds of device (the app, its version, the device's model and system). **One kind of device** marks a problem seen on only one kind, which points to that device or its app. A problem on every kind of device points to tapiOca or the file. Under each problem:

- **What it means** explains the player's error in plain words, for the errors tapiOca knows.
- **What the app said** gives the error exactly as the app sent it.
- **What led up to it** shows the app's last lines before the error.

Problems are kept for 30 days. **Clear** removes them, and the log keeps its own record. For more about one device, use its **Send app details to tapiOca** (in the app's Options), which adds what the app did recently.

**Alerts.** tapiOca alerts Admins when something needs attention:

- **Plex.** Plex can't be reached, or won't accept tapiOca's token. The alert says what happened and what to check (see **Plex isn't connected** under **Plex**, below).
- **The data folder.** It has less than 2 GB free, or can't be written to.
- **A failing station.** A station keeps failing to start (3 times in 10 minutes).
- **Backups.** Backups fail twice in a row.
- **The clock.** tapiOca's clock is more than 2 minutes off from Plex's. This uses the time in Plex's answers; without it, the clock isn't checked.
- **Away from home.** tapiOca's apps can't reach it from outside.
- **Broken files.** Something on the **Broken files** tab needs an Admin: a person's report, a broken or damaged file that isn't being replaced automatically, or one Sonarr or Radarr couldn't replace. An example: "There are 3 files to look at on the Broken files tab: Tia reported No sound on Northbound S2 E4". This alert appears at most once an hour. It starts again when there's something new, an hour or more after the last one.

An alert starts only once a problem persists (for Plex, five checks a minute apart), and clears only once things stay right, so alerts don't flicker on and off. Each start and fix adds a line in the **Logs** tab. Admins also see a pill in the page's header with the number of current alerts, which opens a list of them, and they see alerts in tapiOca's apps too.

Alerts are kept in tapiOca's database, so a restart doesn't repeat them. An open alert stays open (the **Logs** tab notes it's still going) until its check finds it fixed. Then it's reported fixed, once. That's so even if it was fixed while tapiOca was stopped. The apps' list of alerts fixed in the last day survives restarts too. A restored backup starts with no alerts, so anything still wrong is reported again.

**Notifications.** To get alerts elsewhere, open **Alert notifications** at the top of the **Logs** tab, turn it on, and enter a web address. Choose **Add an address** for more, up to 3 (say, Discord and your phone). Each alert goes to every address, and one that fails or is slow doesn't hold up the others. Each address has its own format: an ntfy topic (**ntfy or plain text**); a Gotify message or Home Assistant webhook address (**JSON**: `{"title": "tapiOca", "message": "...", "kind": "...", "state": "started"}`, or `"fixed"`); a Discord webhook's address (in Discord: **Server Settings**, **Integrations**, **Webhooks**), in Discord's own format (**Discord**); or a Slack incoming webhook's address, in Slack's format (**Slack**: `{"text": "..."}`, which Mattermost and Rocket.Chat take too). A Discord or Slack webhook's address always gets its own format, whichever is chosen, and never pings anyone. **Send a test** tries an address right away. For each address, tapiOca waits 5 seconds for an answer, tries once more, follows no redirects, and keeps only the answer's status. Only Admins see the addresses, and the log names only their sites.

**Installing and starting**

- **The app keeps restarting, and the log says it can't write to `/data`.** The data folder isn't owned by the user tapiOca runs as. The message shows the `chown` command to run. Fill in your data folder's path, run it, then restart the app.
- **The app won't start, and mentions `/dev/dri`.** The GPU lines are in the YAML, but the server has no Intel/AMD graphics. Remove the `devices:` and `group_add:` lines.
- **Docker says port 3310 or 3311 "is already allocated" or "address already in use".** Another app on the server uses that port. Change only the first number of the port line (for example, `"3320:3310"`). Then use the new port in every address: in your browser, and in Plex or your other apps.
- **After updating, the page still shows the old version.** Docker didn't fetch the newest image, or didn't start tapiOca from it. Check that `image:` ends in `:latest` (`:1.34` or `:1.34.0` stays on that version). Then fetch it yourself: on TrueNAS, in **System**, then **Shell**, run `sudo docker pull ghcr.io/egadgetboy/tapioca-server:latest`, then edit the app and save it; with Compose, run `docker compose up -d --pull always` (with `sudo` first on Synology).
- **Docker says there's "no matching manifest" for your system.** The image is for 64-bit machines only: x86-64 (Intel/AMD) and ARM64. On a Raspberry Pi, use a 64-bit OS.
- **The page shows "Nothing to play yet"** or **"Plex didn't accept the token in PLEX_TOKEN".** Add a Media folder of your own on the **Setup** tab, or fix those two settings to use Plex (with the YAML's sample token left in place, tapiOca doesn't use Plex: paste your token, or delete the PLEX_URL and PLEX_TOKEN lines). Users (not Admins) see only "Plex: not connected". If Plex runs in Docker on the same machine, use the machine's network IP in `PLEX_URL`, not `localhost`.

**Plex**

- **Plex isn't connected.** The page says so plainly, such as "Plex isn't answering" or "Plex is taking too long to answer". The details (what tapiOca asked Plex, and the error) go to the log, at most once a minute. Check three things:
  - `PLEX_URL` is your Plex server's address, not the YAML's example, `http://192.168.1.10:32400`.
  - Plex is running.
  - `PLEX_TOKEN` is right (see [Finding your Plex token](#finding-your-plex-token)).

  The **Tuner** step of the setup and the Plex alert say which of these it is. After changing tapiOca's app settings, restart it.
- **Plex can't find the tuner.** tapiOca doesn't answer Plex's automatic network search. Enter the address manually (see [In Plex](#in-plex)).
- **Plex says no tuners are available.** If you raised tapiOca's tuners, restart Plex so it reads the new number. When tapiOca's own tuners are all busy, viewers see its **All tuners in use** card instead.
- **The guide shows the wrong program.** In Plex, choose **Settings → Live TV & DVR → your tuner → Refresh Guide**, wait a minute, then reload the Plex app. Apps keep the guide they loaded. The **Logs** tab says "Plex downloaded the guide" when Plex has the new one.
- **Plex says "Device not found".** Plex is looking for tapiOca's tuner under an old ID or address. The **Logs** tab shows which tuner Plex lists, such as `device://tv.plex.grabbers.hdhomerun/1A2B3C4D at <address>`. tapiOca's own ID is the `DeviceID` at `http://<server-ip>:3310/discover.json`.
- **Fixing a different ID.** If the IDs differ (after starting with a fresh data folder, say), put Plex's ID in `data/device.json` as `{"deviceId": "1A2B3C4D"}` (exactly 8 hexadecimal characters). Make sure the file belongs to tapiOca's user (such as `sudo chown 1000:1000 data/device.json`), and restart tapiOca. If the address is wrong, set up tapiOca in Plex again.
- **A managed user can't see the stations.** Their Live TV & DVR access must be **Allow Live TV and DVR access**.
- **Skipping intros and credits doesn't skip anything.** The card says "no intros or credits found yet" until Plex has marked some programs. Check Plex's marker settings (see [Skipping intros and credits](#skipping-intros-and-credits)). Plex finds intros by comparing a season's episodes, so a season with very few episodes may not get them.

**Playing**

- **A station shows "This station is off the air. Please report it."** Nothing on it could play for two programs in a row, or its stream failed 3 times within 5 minutes. The **Logs** tab says why. Usually Plex or the media share can't be reached, or every program on the station is on the Broken files list.
- **A stream stops.** The **Logs** tab says what happened. "Viewer … left station … after …" means the player closed the connection itself. "Viewer … was disconnected from station …" gives tapiOca's reason. "is falling behind real time" means the server can't convert video as fast as it plays. Use a smaller picture size, fewer tuners, or a GPU.
- **HDR movies look washed out.** At startup, the **Logs** tab notes if ffmpeg can't convert HDR. tapiOca's own image can.
- **Subtitles don't show.** The program needs subtitles in the `AUDIO_LANGUAGE` language, in its file or next to it. With **Forced only**, it needs forced ones. A program's first airing may play without them while they're extracted.
- **No commercials or trailers play.** The editor shows how many were found. The folders must be named exactly `commercials` and `trailers`, at the top of a Media folder as Plex lists it, and visible inside `/media`.
- **A Feature Presentation or block doesn't happen.** The station card shows when the next one is. A more important special may have overlapped it, or it would have started too late. The **Logs** tab says which.
- **Up Next Banners never appear, and the log mentions the data folder's path.** `DATA_DIR` is set to a path with characters ffmpeg can't handle. Remove the `DATA_DIR` setting, because the default, `/data`, always works. The folder's name on your server doesn't matter.

**Files and the Broken files list**

- **Many files go on the list at once.** Check the reason. If tapiOca can neither see the files under `/media` nor reach Plex, programs are skipped, not listed. If Plex itself has lost the files, they're listed as "can't open the file" or "removed from Plex". Check the **Media files** line on the **Setup** tab, fix the cause, then use **Retry**.
- **A file is listed as Damaged, but plays fine for you.** Choose **Retry**. It goes back on the air, and the checks leave that file alone.
- **A station stopped following Plex.** An update that would remove more than half its programs waits for you. Choose **Update now** if it's right (see [Updates to stations](#updates-to-stations)).

**GPU**

- **The GPU isn't used.** The **Video encoding** line on the **Setup** tab shows why. Usually it's the group number in `group_add` (the message names the right one) or `/dev/dri` not being passed to the container. `docker exec stationplay vainfo` shows whether the Intel/AMD driver sees the GPU.
- **"… was turned off after 3 programs in a row failed on it".** tapiOca stopped using the GPU to keep stations playing. Restart tapiOca to try the GPU again. If it keeps happening, check the GPU driver.

**Access and blocking**

- **Locked out of tapiOca's page.** See **Locked out?** under [Who can use tapiOca](#who-can-use-tapioca).
- **"Plex wouldn't stop … Stopping playback needs Plex Pass on the server owner's account."** Blocking needs Plex Pass on the account that owns the server.
- **"Plex won't say who's watching…"** Your Plex token isn't allowed to see what's playing. Use the server owner's token. Stats by Plex user and blocking both need it.

## Development

```
pip install -r requirements.txt pytest pytest-asyncio
python -m pytest                     # all tests, including end-to-end tests with real ffmpeg (35 to 45 minutes)
STATIONPLAY_SOAK=1 python -m pytest -k soak -o faulthandler_timeout=0              # two long soak runs, 8 minutes each
STATIONPLAY_SOAK=1 STATIONPLAY_SOAK_MINUTES=30 python -m pytest -k soak -o faulthandler_timeout=0
STATIONPLAY_REALWORLD=1 python -m pytest tests/test_e2e_realworld.py

docker build --target test -t stationplay-test .           # all tests in the image as people get it, as GitHub runs them
docker run --rm --init stationplay-test

pip install ruff mypy
ruff check app tests && ruff format --check app tests      # lint and formatting
mypy app                                                    # type checks
```

The tests need ffmpeg on the `PATH`. The HDR and real-world tests also need ffmpeg with libx265, and they're skipped without it. `requirements.txt` is pinned for Python 3.13. A test still running after 5 minutes prints where every thread is (`faulthandler_timeout` in `pytest.ini`), and with `-v` its name comes first, so a test that hangs names itself. The end-to-end tests run a fake Plex that has a cut-short file, an unopenable file, a file with no sound and a source that stalls. They also use a stand-in ffmpeg (`tests/fake_gpu_ffmpeg.py`) that acts like a GPU and can be told to fail. They check that a viewer receives one continuous, clean stream that keeps pace with the clock.

`.github/workflows/image.yml` builds the image whenever `main` changes, on an amd64 machine and an arm64 machine, and runs the tests inside each: the Dockerfile's test stage is the image people get, with its own FFmpeg and Python, plus the tests and git (for one test). The tests stop after an hour. Each image that passes is pushed to GitHub's container registry under its commit only (`sha-<commit>-amd64`, `sha-<commit>-arm64`, then both joined as `sha-<commit>`), never under a version: that's for the release workflow. In a fork, it pushes to the fork's own registry. The Dockerfile pins its base image by digest, so every build starts from the same Debian and Python; a comment there says how to update it. `.github/workflows/quality.yml` runs the plan's longer quality checks in the image every Monday, or from its **Run workflow** button: two soak tests of 4½ hours each, and the real-world and HDR tests. It publishes nothing.

**The setup's questions.** When a release adds something an Admin needs to answer (a feature that's off until they turn it on, or a new choice), it goes in the setup. Add a new question to `QUESTIONS` in `app/setup.py`, with its step on the page (`SETUP_PAGES` in `app/web/js/setup.js`). For a question that gains a choice, raise its version by one. After the update, the setup opens once by itself with just that question.

**The page at every screen size.** Before a release, run `python tools/page_sizes.py /tmp/page-sizes` (it needs Playwright and Pillow). It runs tapiOca with stand-in data and saves a screenshot of every tab and dialog at phone, tablet and computer sizes, light and dark, signed in as an Admin and as a User. It lists anything that scrolls sideways, is cut off, or is too small to tap.

**Updating, rolling back and installing fresh.** For every release, `python tools/upgrade_check.py` tests the upgrade path:

1. Starts the previous release (by its git tag, unpacked into a temporary folder) on a new data folder. Through its API, adds an Admin, a User with a PIN and a Viewing Level, a linked device, settings and a station.
2. Starts this checkout on the same folder, and checks that everything is there, everyone is still signed in, and the database was backed up first (a release that doesn't change the database makes no copy).
3. Makes two alerts live, sent to a web address it stands in for, and restarts with them. Checks that neither is sent again, and that one fixed while tapiOca was stopped is reported fixed once.
4. Starts the previous release on the current database, live alert and all.
5. Rolls back as [Rolling back](#rolling-back) describes, and checks that the previous release works with its data.
6. Installs this checkout fresh.

It uses its own ports, stops only what it started, and cleans up afterward. `--from v1.28.1` starts from another release, and `-v` shows every check.

**Releases.** Each release's notes are in `docs/releases/v<version>.md`. Their first lines name the commit of that version (`commit: <its full ID>`), which must be a commit `main` was tested at (for a merge, the merge commit). `.github/workflows/release.yml` runs each time the image workflow finishes on `main`. For each version not yet published, it checks that the commit is on `main`, is that version, and passed the image workflow's tests on both machines (on that commit, or on a later one that changed only release notes). Then it makes the release on GitHub, first as a draft:

- **The tag** at that commit, and the notes.
- **The files built from that commit:** `tapioca-<version>.zip`, `tapioca-server.yaml` (`stationplay.yaml` before 1.35.0) and `docker-compose.yml`.
- **Two lists of packages:** `tapioca-<version>-packages.txt` (amd64) and `tapioca-<version>-packages-arm64.txt`. Each lists every package in the image that was tested (the tests' own additions aside), at its exact version, with a link to its source. The image workflow run that tested the commit makes them after its tests and keeps them with the run for 90 days. Without them, nothing is published, and the release run says to re-run that image run.
- **`tapioca-<version>-source.tar`:** the source of every GPL and LGPL package in the images, as Debian publishes it, fetched from inside the tested image. If any of it can't be fetched, nothing is published, and the run says which.
- **`SHA256SUMS`:** the SHA-256 of each of the release's files, and the image's digest for each of its tags.
- **`tapioca-<version>.zip.sig` and `SHA256SUMS.sig`:** their signatures (see [Checking a release's signature](#checking-a-releases-signature)). From 1.35.0, a release isn't published without them. Before then, files that can't be signed are published unsigned, with a warning on the run.
- **The image's tags,** once the draft is made. The image the run tested (both machines' images, joined, by digest) gets `:<version>`, `:<major.minor>` if it's the newest of that minor version, and `:latest` if it's the newest release. Each tag is copied onto that very image, never built again, and checked to be it.

Then the draft is published, once anyone can pull the image without signing in: the `tapioca-server` package on GitHub must be public, or the run says so and publishes nothing. A draft left by a run that stopped partway is deleted, and the release made again. The workflow runs only in this repository, not in forks.

A version whose tests are still running waits for them, and one whose tests failed isn't published; the run says why in one line. Push and test each version's commit before the next one's. Versions before 1.34.0 were source only: no image was published for them, and each person's build got Debian's packages from Debian. Public releases here start with 1.32.0.

**Before each push to `main`,** run `python tools/image_check.py` (about 3 minutes). It lays the project out as the image's test stage has it and runs the tests that read the project's own files there, so a file the image hasn't got shows up at once rather than 40 minutes into the image workflow. The image workflow runs the same tests first, in the image itself.

### Building from source

This is the advanced choice: most people should use the published image (see [Install](#install)). To build the image yourself, to try a change, say:

1. **Get the source:** a release's `tapioca-<version>.zip` (releases before 1.34.0 named it `stationplay-<version>.zip`), which unzips to a folder called `src` (check its signature first; see the next section), or a clone:

   ```
   git clone https://github.com/egadgetboy/tapioca-server.git
   ```

2. **Build the image,** from the folder that holds `src` (or your clone's folder). The first build takes a few minutes, mostly to install FFmpeg. On TrueNAS (in **System → Shell**) and over SSH on Synology, use `sudo docker build` instead.

   ```
   docker build -t tapioca:1.34.1 ./src              # or ./tapioca-server for a clone
   ```

3. **Point `image:` at your build.** In your YAML or compose file, set `image: tapioca:1.34.1` (your build's name) and `pull_policy: never`, so Docker uses your build and never looks for it online. With `docker run`, put `tapioca:1.34.1` at the end instead. Remove `TAPIOCA_INSTALL`, so the page doesn't suggest fetching the published image.

To update, get the new source, build it under the new version, and change `image:` to match. Then save the app in TrueNAS, or run `docker compose up -d`.

**Going back to a version before 1.34.0.** Those versions built themselves from `src`. First restore the database (step 2 of [Rolling back](#rolling-back)). Then unzip that version's `stationplay-<version>.zip` in the folder that holds `src` (it unzips to `src`). In your YAML or compose file, put that version's `build:` block and `image:` line (from its `stationplay.yaml` or `docker-compose.yml`, such as `image: stationplay:1.33.1`) in place of `image:` and `pull_policy:`. Then save the app in TrueNAS, or run `docker compose up -d --build` (with `sudo` over SSH on Synology). With `docker run`, build it as in step 2 under that version's name, run `docker rm -f stationplay`, then your `docker run` command with `stationplay:1.33.1` (that version) at the end.

### Checking a release's signature

Each release's zip comes with an SSH signature, `tapioca-<version>.zip.sig`, made by the key in the repo's `release-signing.pub`. To check one, put this line in a file named `allowed_signers`:

```
tapioca-release namespaces="tapioca-release" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMGwA9MpUzSlWeish/aRH6oYEo3PjkIBC9LXZSXxcdsC StationPlay release signing
```

Then, in the folder with the zip and its signature, run:

```
ssh-keygen -Y verify -f allowed_signers -I tapioca-release -n tapioca-release -s tapioca-<version>.zip.sig < tapioca-<version>.zip
```

It says `Good "tapioca-release" signature` when the zip is exactly what was published. From 1.34.0 on, every release's zip and its `SHA256SUMS` are signed.

`SHA256SUMS` comes with each release from 1.34.0 on, signed the same way (`SHA256SUMS.sig`). Check it as you checked the zip, with `SHA256SUMS` and `SHA256SUMS.sig` in place of the zip and its signature. Then `sha256sum -c --ignore-missing SHA256SUMS` checks the release's files you have. Its last line gives the image's digest, as `ghcr.io/egadgetboy/tapioca-server:1.34.0` (`:latest` and `:1.34` move with later releases, so they aren't listed): `docker pull ghcr.io/egadgetboy/tapioca-server@sha256:<that digest>` fetches exactly that image.

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

Three logos also use system fonts: DejaVu Sans (Sing-Along) and Noto Sans CJK JP (two anime logos). The Station ID jingles are made by `tools/bumper/` (needs numpy). The [INFO station](#the-info-station)'s film and logo are drawn by `tools/info/render.py`, and its music is made by `tools/info/music.py`. They need Pillow, numpy and ffmpeg, which aren't in the image. Only the film and logo they make ship, in `app/assets/info/`, with each release's `news.json` (what's new, for INFO) and `apps.json` (the newest apps).

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
| `app/infostation.py` | The INFO station, 99: made once, on a new tapiOca's first start, and brought back by an Admin; its film, logo, settings and panels (drawn over the film by `ffmpeg.py`) |
| `app/specials.py`, `app/marathons.py` | Marathons, Feature Presentations and blocks |
| `app/smart.py` | Smart stations |
| `app/subtitles.py` | Subtitles drawn into the picture |
| `app/replacement.py` | Choosing stand-ins for programs that can't play |
| `app/markers.py` | Plex's intro and credits markers |
| `app/updates.py` | Following Plex: hourly checks, and when updates take over |
| `app/db.py` | Stations and settings (SQLite) |
| `app/library.py` | Your shows and movies, wherever they come from: Plex, or Media folders of your own |
| `app/folders.py`, `app/folderscan.py` | Media folders of your own: their tables, reading them, their details put together, and the page's addresses |
| `app/naming.py`, `app/nfo.py` | What folder and file names, and NFO files, say about a show, episode or movie |
| `app/folderart.py` | Media folders of your own: pictures beside the videos and inside them |
| `app/plex.py` | Talking to Plex |
| `app/sources.py` | Finding the file to play, and matching Plex's paths to `/media` |
| `app/broken.py` | The Broken files list |
| `app/jobs.py` | Check files, and re-checking the Broken files list |
| `app/scanner.py` | Quick checks, weekly checks and the overnight deep scan |
| `app/replacing.py`, `app/arr.py` | Replacing files with Sonarr and Radarr |
| `app/gpu.py` | GPU detection, the startup test, and turning off a failing GPU |
| `app/hls.py` | Stations as HLS, for tapiOca's apps and other HLS players |
| `app/appapi.py`, `app/api.py` | tapiOca's API (`/api/v1`): the server, stations and guide; API tokens, Admin actions and the OpenAPI spec. Also the apps' own sign-in and connection tests (`/api/internal`) |
| `app/links.py` | Signing in an app with a code |
| `app/away.py`, `app/reach.py`, `app/capacity.py` | tapiOca's apps away from home, and the check that they can reach it; limits on devices watching, and connection tests |
| `app/ondemand.py`, `app/applibrary.py`, `app/catalog.py` | Media in tapiOca's apps |
| `app/languages.py` | Each person's languages in tapiOca's apps, and the sound and subtitles chosen from them |
| `app/converting.py`, `app/keyframes.py` | Copies of what a device can't play directly: repackaged or converted, as HLS |
| `app/hdhr.py` | HDHomeRun and XMLTV formats |
| `app/breaks.py` | Commercials, trailers and Station ID cards |
| `app/intro.py` | Drawing the Intro Bumper and Station ID card, and their sound |
| `app/upnext.py` | The Up Next Banner |
| `app/bumpers.py` | Intro Bumper videos you upload |
| `app/backups.py` | Backups and restores, and the database copy made before an update changes it |
| `app/access.py` | Sign-in, Admins and Users, and the access log |
| `app/viewing.py`, `app/ratings.py`, `app/titles.py` | Viewing Levels: what each person can see, ratings read as ages, and the ratings, genres and tags of what's on each station |
| `app/cliprules.py` | Commercials and trailers under Viewing Levels: each clip folder's rating |
| `app/devices.py` | Linked devices, Who's tuning in?, PINs and invite codes |
| `app/stats.py`, `app/watching.py` | Viewing stats, who's watching now, and matching Plex sessions to stations |
| `app/health.py` | The server's health for the Stats tab: processor, memory, network and storage, from Linux's own files |
| `app/alerts.py`, `app/notify.py` | Admin alerts, and notifying up to 3 web addresses of them |
| `app/playing.py` | What's playing, in words: how the log names stations, files and apps, and whose app is where |
| `app/limits.py` | Blocking stations for some Plex users |
| `app/logos.py`, `app/logos/` | The logo library and your own logos |
| `app/text.py`, `app/logbuffer.py` | Cleaning up names people type; recent log entries for the Logs tab |
| `app/assets/` | Sounds and other files the app draws with |
| `app/web/index.html`, `app/web/manifest.webmanifest` | tapiOca's page, and what installing it as an app takes (with its icons, from tapiOca's brand kit) |
| `app/web/page.css`, `app/web/js/` | The page's styles, and its scripts, one file for each part of the page (loaded in the order `PAGE_FILES` in `app/access.py` lists them) |
| `tests/` | Unit and end-to-end tests |
| `Dockerfile`, `tapioca-server.yaml`, `docker-compose.yml` | The image, the TrueNAS app, and the Compose file |
| `docs/` | tapiOca's logo; tapiOca's API (`api.md`, `openapi-v1.json`); the apps' own addresses (`internal-api.md`); the designs of the layer that reads your movies and shows (`library.md`), of Media in the apps (`on-demand.md`), and of who sees what (`users.md`); each release's notes (`releases/`); and the old names other programs still match (`notes/names-kept.md`) |

## Contributing

Bug reports and ideas are welcome, as GitHub issues. A good bug report says what you expected, what happened instead, and what the **Logs** tab showed at the time. Its **Copy** button makes that easy. If you know what's wrong, say so in the issue.

tapiOca doesn't accept code contributions for now, so please don't open pull requests. That may change later, with a contributor agreement.

To report a security problem, see [SECURITY.md](SECURITY.md). Please don't describe one in a public issue.

## Forks and credit

tapiOca is free and open-source software. You're welcome to fork it, change it and build on it, as its license allows. If you do, please respect the original project:

- **Give credit.** Say clearly that your project is based on tapiOca by egadgetboy, with a link back to it, in your README and on your app's About page or footer.
- **Keep the notices.** Leave the copyright and license notices in place, including the credit line at the bottom of tapiOca's page, and note what you changed.
- **Use your own name and logo,** so people can tell your version from tapiOca and know where to ask for help with it.
- **Tell us about improvements.** If you fix a bug or add something useful, consider opening an issue that describes it, so everyone's stations get better.

## License

tapiOca is Copyright © 2026 egadgetboy and is licensed under the [GNU Affero General Public License, version 3](LICENSE) (AGPL-3.0). In short:

- You may use, study, change and share tapiOca, including for profit.
- If you share tapiOca, changed or not, you must include its source code or offer it, under the same license.
- If you run a changed tapiOca that other people use over a network, you must offer them its source code too. The **Source** link at the bottom of tapiOca's page points to this project's code: point it to your changed code instead (it's in `app/web/index.html`).
- Keep the copyright and license notices, and mark what you changed.
- tapiOca comes with no warranty.

This is only a summary. The [LICENSE](LICENSE) file is what applies. The packages tapiOca uses, and the fonts used to redraw its logos, keep their own licenses.

The open-source parts in tapiOca's image, such as FFmpeg, and their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). tapiOca's page links to them too, under **Open-source notices** at the bottom.
