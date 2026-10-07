# The app connection, version 1

What StationPlay's own apps (iPhone, iPad, Apple TV, Android, Google TV, Fire
TV, Roku) ask the server. It's a small, fixed set of addresses under
`/api/v1`. Anyone can write a player against it too: it's part of the
server, under the same license.

The tables below are checked against the server by its tests
(`tests/test_app_api.py`), so this document and the server can't drift
apart.

## The rules

- Every answer under `/api/v1` carries the header `StationPlay-API: 1`, and
  every answer is JSON (pictures and streams aside).
- Version 1 only grows. New fields and new addresses may be added; nothing
  is renamed, removed or changed in meaning. Apps ignore fields they don't
  know. A change that would break an app becomes version 2, served beside
  version 1.
- Addresses in answers (`logo`, `hls`, `art`, `url`) are relative to the
  server: add them to the address the app reached the server at.
- Times are milliseconds since 1970 (UTC).
- An error is an HTTP status with `{"detail": "..."}`, a sentence an app can
  show as it is.

## Signing in

When StationPlay has users (signing in is on), an app signs in one of two
ways, and gets a token to send with every request:

- **With a code** (for TVs, and anything without a handy keyboard): the app
  shows a code, someone signed in on StationPlay's page enters it at `/link`,
  sees which app on which device it is, and links it to their account. No
  password is typed on a remote or sent by the TV. See `POST /api/v1/link`.
- **With a name and password**, as on the page. See `POST /api/v1/sign-in`.

Either way, the app then sends its token with every request:

```
Authorization: Bearer <token>
```

A token lasts 30 days from when it was last used, like a browser's sign-in.
Signing out ends it, and so do a new password for its person, their removal,
and an Admin signing that app out from the Access tab's **Signed-in apps**,
which lists each app by the name and device it gave. Sign-ins, links and
sign-outs show in the access log. Apps keep their token where only they can
read it (the Keychain on Apple devices, Android's Keystore, a Roku's own
storage for the app), and never show it.

From the internet (the public port), apps connect only over HTTPS: anything
under `/api/v1` or `/hls/k/` that didn't come over HTTPS (as the reverse
proxy in front says, with `X-Forwarded-Proto`) is refused with 403. On the
home network, and through a VPN, plain HTTP is fine.

Wrong passwords are limited as on the page: after 5 wrong ones from one
address within 15 minutes, signing in from there waits (HTTP 429).

When signing in is off, nothing needs a token on the home network.

On the public port, only `GET /api/v1/server` answers until signing in is
on.

## Away from home

An app reaches StationPlay away from home either through a VPN (then it's on
the home network, as far as StationPlay can tell) or through the public port
(behind a reverse proxy), signed in. Watching stations through the public
port works only once an Admin turns on **StationPlay's apps away from home**
on the Access tab; it's off until then, and `awayAddress` is null.

When it's on, `awayAddress` is the address to use from outside. An app set
up at home keeps it, and when the home address doesn't answer, uses that
instead. From outside, each station's `hls` and `logo` are addresses of the
app's own, `/hls/k/<key>/<number>/index.m3u8` and
`/hls/k/<key>/<number>/logo.png` (so a player, or a picture, needs no
sign-in): the key belongs to the app's sign-in, and stops working when that
sign-in ends, when watching away from home is turned off, or when
StationPlay restarts. When it stops working (404), the app asks for
`GET /api/v1/stations` again for new ones.

## GET /api/v1/server

Open to anyone: what this server is, so an app can tell whether it's a
StationPlay it can talk to.

| Field | Type | What it is |
|---|---|---|
| `name` | string | The server's name (`FRIENDLY_NAME`) |
| `id` | string | The server's ID, the same for as long as its data folder lasts |
| `version` | string | StationPlay's version, such as `1.18.0` |
| `api` | number | The app connection's version: `1` |
| `signIn` | boolean | Whether apps must sign in |
| `notSetUp` | string or null | Why nothing can be done from here yet (the public port, before signing in is on); null otherwise |
| `outside` | boolean | Whether the app reached StationPlay through its public port |
| `awayAddress` | string or null | The address to use away from home (such as `https://tv.example.com`), when an Admin has turned that on; null otherwise |
| `features` | list | What this server offers apps |
| `features[]` | string | One of them: `hls` (stations as HLS), `speed-test` (connection tests, from 1.20.0), `away` (watching away from home is on), `library` (libraries are shared with the apps, and can be watched from here; from 1.21.0) |

## POST /api/v1/link

Open to anyone: starts signing in with a code. Send which app this is, and
the device's own name, as the Access tab will list it:

```json
{"app": "StationPlay for Roku", "deviceName": "Living Room Roku"}
```

Show `code`, and where to enter it: StationPlay's page at `linkAt` (an app
that knows the page's address shows it whole, such as
`http://192.168.1.20:3310/link`). Then `POST /api/v1/link/check` with `poll`
every `interval` seconds until it answers with a token, or the code runs out.
Keep `poll` to the app: whoever has it gets the sign-in.

| Field | Type | What it is |
|---|---|---|
| `code` | string | The code to show, such as `K7QM-4DPX` |
| `poll` | string | The app's secret for checking back |
| `expiresIn` | number | Seconds until the code runs out (600) |
| `interval` | number | Seconds between checks (3) |
| `linkAt` | string | Where on StationPlay's page the code is entered |

Answers 400 when signing in is off, and 429 when one address has asked for
too many codes lately.

## POST /api/v1/link/check

Open to anyone. Send `{"poll": "..."}`. Answers 202 (`{"detail": ...}`)
while the code is waiting to be entered, 404 once it has run out (start
again), and once it's linked, the sign-in, just once:

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who linked it |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

## POST /api/v1/sign-in

Open to anyone. Send:

```json
{"name": "Sam", "password": "...", "device": "...",
 "app": "StationPlay for iPhone", "deviceName": "Sam's iPhone"}
```

`device` is optional: the `device` from an earlier sign-in on this device,
which keeps it signing in while too many wrong passwords from the internet
hold everyone else back (as a browser that has signed in before does). `app`
and `deviceName` are optional too: how the Access tab lists this sign-in.

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `device` | string or null | Keep it, and send it when signing in again; null when the `device` sent is still good |
| `user` | object | Who signed in |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

Answers 401 for a wrong name or password, 429 while signing in waits, and
400 when signing in is off.

## POST /api/v1/sign-out

Ends the token it's sent with. Answers `{"ok": true}`.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## GET /api/v1/stations

Every station, in number order, with what's on now and next.

| Field | Type | What it is |
|---|---|---|
| `stations` | list | The stations |
| `stations[].number` | number | Its number |
| `stations[].name` | string | Its name |
| `stations[].description` | string | Its description (may be empty) |
| `stations[].logo` | string | Its logo, a PNG (a badge with its number if it has none). The address changes when the logo does, and from outside is one of this app's own (see Away from home) |
| `stations[].colors` | object | Colors from its logo, as its Intro Bumper uses them |
| `stations[].colors.dark` | string | The darkest background, as `#RRGGBB` |
| `stations[].colors.light` | string | A lighter background |
| `stations[].colors.accent` | string | The accent |
| `stations[].hls` | string | The station as HLS, to play: at home `/hls/<number>/index.m3u8`, and from outside an address of this app's own (see Away from home) |
| `stations[].now` | program or null | What's on now (null before the station's first program) |
| `stations[].next` | program or null | What's on next |

## GET /api/v1/guide

Each station's programs between two times: `?from=` and `?to=`, in
milliseconds. `from` is now if it isn't given, and `to` is six hours after
`from`. `from` must be within 7 days of now, and `to` at most 2 days after
`from` (400 otherwise).

| Field | Type | What it is |
|---|---|---|
| `from` | number | The start of what's listed |
| `to` | number | The end of what's listed |
| `stations` | list | Each station, in number order |
| `stations[].number` | number | The station's number |
| `stations[].programs` | list | Its programs that overlap `from` to `to`, in order |
| `stations[].programs[]` | program | One program |

## Playing a station

Each station's `hls` address is an HLS playlist (see Away from home for
where it is from outside). The first ask starts the station's stream for apps and
waits (up to 25 seconds) until there's enough to start playing. While it
can't play, it answers 503 with `{"detail": "..."}`, and when every tuner is
in use, also `"onNow"`: the numbers of the stations playing, which the app
can offer to join instead. All the apps watching a station share its one
stream, on one tuner.

An Admin can limit how many devices watch through the apps at once, and of
those, how many away from home (on the Access tab). A device already
watching can always change station; one more device is answered 503 with
`"limit"` (`devices`, or `away`) and `"most"` (the limit), and a `detail`
the app shows as it is, such as "An Admin has limited StationPlay to 5
devices watching at once, so it runs smoothly for everyone. Please try
again later." It should offer to try again rather than retrying by itself.

`POST` to the `hls` address with `index.m3u8` changed to `leave` (such as
`/hls/<number>/leave`) says this device stopped watching a station
(tuned away, or went back to the guide). If no other app is watching it,
its stream stops and its tuner is free at once; otherwise it stops once
nothing has asked for it for 30 seconds. Answers 204, whatever the station.

## GET /api/v1/speed-test

A connection test: data for the app to time, so the Admin can see how fast
StationPlay reaches devices (at home, and away from home, where it's the
home internet's upload) and how many can watch at once. `?mb=` is how many
megabytes (1 to 64; 20 if it isn't given). The data is random, so nothing
along the way can shrink it, and it has a `Content-Length`. An app times it
from a moment after the data starts (so the connection's start-up isn't
counted), and may stop reading after about 8 seconds on a slow connection.
One test from an address at a time: another within 10 seconds is answered
429.

## POST /api/v1/speed-test

What the app found: `{"mbps": 48.2, "app": "...", "deviceName": "..."}`
(`app` and `deviceName` as for signing in). StationPlay keeps it for the
Access tab, with where it ran as StationPlay sees it, and recommends limits
from the fastest recent tests.

| Field | Type | What it is |
|---|---|---|
| `mbps` | number | The speed kept, in megabits a second |
| `where` | string | `home`, or `away` (through the public port) |
| `eachMbps` | number | What one device watching takes, at the biggest picture the stations use |
| `room` | number | How many devices a connection this fast has room for at once |

## Your library

When an Admin shares libraries with the apps (on the Access tab, under
**Your library in StationPlay's apps**), the apps can browse them and play
their shows and movies on demand. Until then, `features` doesn't list
`library`, and these addresses answer 404 ("No libraries are shared with
StationPlay's apps"). For now, this is on the home network (or through a
VPN, which looks like home): through the public port they answer 403, and
`features` doesn't list `library` there.

Anything that isn't in a shared library answers 404, the same as something
that doesn't exist. When the library can't be reached (Plex is down, say),
these answer 503.

Keys are strings, and the same key always means the same show, movie or
episode. Pictures (`poster`, `backdrop`, `thumb`) are addresses under
`/api/v1/art`: add `&w=` with the width it will be shown at, in pixels, and
send the app's token with them.

Each person has their own place in what they watch (Continue Watching,
where to resume, what they've watched), kept by StationPlay. While signing
in is off, everyone shares one.

## GET /api/v1/libraries

The shared libraries, in the library's own order.

| Field | Type | What it is |
|---|---|---|
| `libraries` | list | The shared libraries |
| `libraries[].key` | string | Its key |
| `libraries[].title` | string | Its name, such as "TV Shows" |
| `libraries[].kind` | string | `show` (a library of shows) or `movie` |

## GET /api/v1/libraries/{key}

One shared library's shows or movies, a page at a time: `?start=` (0 if it
isn't given) and `?size=` (1 to 200; 50 if it isn't given), sorted by
`?sort=`: `title` (the default), `added` (newest first) or `released`
(newest first).

| Field | Type | What it is |
|---|---|---|
| `key` | string | The library's key |
| `title` | string | Its name |
| `kind` | string | `show` or `movie` |
| `total` | number | How many shows or movies it has in all |
| `start` | number | Where this page starts |
| `items` | list | This page |
| `items[]` | card | One show or movie |

## GET /api/v1/home

What the app's home screen shows.

| Field | Type | What it is |
|---|---|---|
| `continue` | list | Continue Watching: what this person is partway through, and the next episode of shows they've been watching, newest first (up to 20) |
| `continue[]` | card | An episode or movie; `positionMs` is where to start it |
| `added` | list | Each shared library's recently added shows or movies (libraries with none are left out) |
| `added[].library` | string | The library's key |
| `added[].title` | string | Its name |
| `added[].items` | list | Its newest movies, or the shows with the newest episodes (up to 20) |
| `added[].items[]` | card | One show or movie |

## GET /api/v1/search

Search: the one place the library and the stations meet. Shows and movies
whose titles contain `?q=` (up to 100 characters), across the shared
libraries, titles starting with it first (up to 50); and the stations
airing a show or movie with it in its title right now. It answers wherever
the stations do, with `items` empty where the library isn't offered.

| Field | Type | What it is |
|---|---|---|
| `items` | list | What was found in the library |
| `items[]` | card | One show or movie |
| `onNow` | list | The stations airing a match now, in number order |
| `onNow[].number` | number | The station's number |
| `onNow[].name` | string | Its name |
| `onNow[].now` | program | What's on it now |

## GET /api/v1/items/{key}

A show's, movie's or episode's details: its card's fields, and more.

| Field | Type | What it is |
|---|---|---|
| `key` | string | As in a card |
| `kind` | string | As in a card |
| `title` | string | As in a card |
| `year` | number or null | As in a card |
| `poster` | string or null | As in a card |
| `episodes` | number or null | (A show) as in a card |
| `unwatched` | number or null | (A show) as in a card |
| `durationMs` | number or null | (An episode or movie) as in a card |
| `positionMs` | number | (An episode or movie) as in a card |
| `watched` | boolean | (An episode or movie) as in a card |
| `episodeTitle` | string or null | (An episode) as in a card |
| `season` | number or null | (An episode) as in a card |
| `episode` | number or null | (An episode) as in a card |
| `showKey` | string or null | (An episode) as in a card |
| `thumb` | string or null | (An episode) as in a card |
| `summary` | string | What it's about (may be empty) |
| `genres` | list | Its genres (its first few) |
| `genres[]` | string | One genre |
| `contentRating` | string or null | Its rating, such as `TV-PG` |
| `studio` | string or null | Its studio, or a show's network |
| `released` | string or null | When it first came out, as `YYYY-MM-DD` |
| `backdrop` | string or null | A wide picture for behind the details (an episode's is its show's) |
| `seasons` | list | (A show) its seasons, in order, specials last |
| `seasons[].season` | number or null | The season's number (0: specials; null for episodes without one, which are listed with all of a show's episodes) |
| `seasons[].title` | string | "Season 1", "Specials" |
| `seasons[].episodes` | number | How many episodes it has |
| `seasons[].unwatched` | number | How many of them this person hasn't watched |
| `next` | card or null | (A show) the episode to play next: the one this person is partway through, or the one after the last they finished, or the first; null once they've watched it all |
| `markers` | object | (An episode or movie) where its intro and closing credits are, for Skip intro and Skip credits buttons |
| `markers.intro` | list or null | The intro, as `[startMs, endMs]`; null if it hasn't one |
| `markers.intro[]` | number | A time in it, in milliseconds from its start |
| `markers.credits` | list or null | The closing credits, as `[startMs, endMs]`; null if it hasn't them |
| `markers.credits[]` | number | A time in it |
| `picture` | object or null | (An episode or movie) its picture |
| `picture.size` | string or null | `4K`, `1080p`, `720p` or `SD` |
| `picture.hdr` | string or null | `Dolby Vision`, `HDR10` or `HLG`; null if it isn't HDR |
| `audio` | list | (An episode or movie) its sound tracks |
| `audio[].id` | string | The track's ID |
| `audio[].name` | string | How to list it, such as "English · Dolby Digital · 5.1" |
| `audio[].language` | string or null | Its language |
| `audio[].codec` | string | Its format, such as `aac`, `ac3`, `eac3`, `dts`, `truehd` |
| `audio[].default` | boolean | Whether the file says to play it unless asked otherwise |
| `audio[].index` | number or null | Its place among all the file's tracks (0 is the first) |
| `subtitles` | list | (An episode or movie) its subtitle tracks |
| `subtitles[].id` | string | The track's ID |
| `subtitles[].name` | string | How to list it, such as "Spanish · Forced" |
| `subtitles[].language` | string or null | Its language |
| `subtitles[].codec` | string | Its format: `srt`, `ass`, `vtt` and `mov_text` are text; `pgs` and `vobsub` are pictures |
| `subtitles[].default` | boolean | Whether the file says to show it unless asked otherwise |
| `subtitles[].forced` | boolean | Whether it's only the parts in another language |
| `subtitles[].external` | boolean | Whether it's a file of its own beside the video, rather than inside it |
| `subtitles[].index` | number or null | Its place among all the file's tracks (null for a file of its own) |

## GET /api/v1/items/{key}/episodes

A show's episodes, in order (specials last): all of them, or one season's
with `?season=`.

| Field | Type | What it is |
|---|---|---|
| `show` | string | The show's key |
| `season` | number or null | The season asked for (null: all of them) |
| `episodes` | list | Its episodes |
| `episodes[]` | card | One episode |

## GET /api/v1/art/{key}

A picture, as JPEG or PNG: `?kind=poster` (the default; 2:3, an episode's is
its show's), `backdrop` (16:9) or `thumb` (an episode's still, 16:9), made
`?w=` pixels wide (rounded up to 160, 320, 480, 720, 1280 or 1920). 404 if
there's no such picture.

## POST /api/v1/play

Starts playing an episode or movie. Send its key and what the device can
play, as the device itself reports it (never a guess), and optionally `app`
and `deviceName` (as for signing in, for the log):

```json
{"key": "1234",
 "device": {"containers": ["mkv", "mp4", "mov", "ts", "webm"],
            "video": [{"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8},
                      {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10}],
            "hdr": ["hdr10", "hlg"],
            "audio": ["aac", "ac3", "eac3", "mp3", "opus", "flac"]},
 "app": "StationPlay for Android TV", "deviceName": "Den"}
```

`hdr` lists only what the screen shows (`hdr10`, `hlg`, `dv` for Dolby
Vision); `[]` for a screen without HDR. A file plays as it is when the
device can play its file type, its picture's format at its size and bit
depth, its HDR (Dolby Vision profile 5 needs `dv`; other profiles also play
as the HDR10, HLG or ordinary picture beneath), and the sound of its default
track. If it can't, the answer is 422, with
`detail` (a sentence to show) and `why` (a list of the reasons): StationPlay
doesn't convert files for the apps yet.

An Admin's limits on devices watching count programs played this way too
(see Playing a station): one more device is answered 503 with `limit` and
`most`.

| Field | Type | What it is |
|---|---|---|
| `session` | string | This playing's ID (for progress reports) |
| `method` | string | How it plays: `direct` (the file as it is) |
| `url` | string | What the player plays (it needs no token), such as `/play/<session>/file.mkv`. Ranges are answered, so the player can seek |
| `leave` | string | Where to `POST` when the player stops |
| `resumeMs` | number | Where this person stopped last time (0: the start). Offer to resume there, or start over |
| `durationMs` | number or null | How long it is |
| `markers` | object | As in its details |
| `markers.intro` | list or null | As in its details |
| `markers.intro[]` | number | As in its details |
| `markers.credits` | list or null | As in its details |
| `markers.credits[]` | number | As in its details |
| `audio` | list | Its sound tracks, as in its details |
| `audio[].id` | string | As in its details |
| `audio[].name` | string | As in its details |
| `audio[].language` | string or null | As in its details |
| `audio[].codec` | string | As in its details |
| `audio[].default` | boolean | As in its details |
| `audio[].index` | number or null | As in its details |
| `subtitles` | list | Its subtitle tracks, as in its details |
| `subtitles[].id` | string | As in its details |
| `subtitles[].name` | string | As in its details |
| `subtitles[].language` | string or null | As in its details |
| `subtitles[].codec` | string | As in its details |
| `subtitles[].default` | boolean | As in its details |
| `subtitles[].forced` | boolean | As in its details |
| `subtitles[].external` | boolean | As in its details |
| `subtitles[].index` | number or null | As in its details |
| `subtitles[].url` | string or null | For a file of its own: where to get it, to add beside the video (it needs no token). Tracks inside the file are the player's to show |

The `url` (and subtitles' `url`) stop working when the app `POST`s to
`leave`, after 4 hours unused, when the app's sign-in ends, when its library
is no longer shared, and when StationPlay restarts (404); choose the program
again to play it again.

## POST /api/v1/progress

Where this person is in an episode or movie: send `{"key": "1234",
"positionMs": 1325000, "session": "..."}` every 10 seconds or so while it
plays (`session` keeps the device counted as watching), and when it stops.
Or mark it from a menu: `{"key": "1234", "watched": true}` (or `false`).

Reaching its closing credits (or, without them, 90% of the way) marks it
watched and starts it from the beginning next time. Less than a minute in
starts it from the beginning too.

| Field | Type | What it is |
|---|---|---|
| `positionMs` | number | Where it will start next time |
| `watched` | boolean | Whether this person has watched it |

## A card

How the library's lists describe a show, movie or episode. Shows have
`episodes` and `unwatched`; episodes and movies have `durationMs`,
`positionMs` and `watched`; episodes also have `episodeTitle`, `season`,
`episode`, `showKey` and `thumb`.

| Field | Type | What it is |
|---|---|---|
| `key` | string | Its key |
| `kind` | string | `show`, `movie` or `episode` |
| `title` | string | The show's title, or the movie's |
| `year` | number or null | The year |
| `poster` | string or null | Its poster (an episode's is its show's) |
| `episodes` | number or null | How many episodes a show has |
| `unwatched` | number or null | How many of a show's episodes this person hasn't watched |
| `durationMs` | number or null | How long it is |
| `positionMs` | number | Where it would start for this person (0: the start) |
| `watched` | boolean | Whether this person has watched it |
| `episodeTitle` | string or null | The episode's own title |
| `season` | number or null | The season (0: specials) |
| `episode` | number or null | The episode |
| `showKey` | string or null | The show's key |
| `thumb` | string or null | The episode's still |

## A program

How the stations and the guide describe a program.

| Field | Type | What it is |
|---|---|---|
| `start` | number | When it starts |
| `end` | number | When it ends (the commercials after it included) |
| `kind` | string | `episode` or `movie` |
| `title` | string | The show's title, or the movie's |
| `episodeTitle` | string or null | The episode's title (null for a movie) |
| `season` | number or null | The season |
| `episode` | number or null | The episode |
| `year` | number or null | The year |
| `summary` | string | What it's about (may be empty) |
| `art` | string | Its picture: the show's, or the movie's |
| `special` | string or null | What special it's part of: "Feature Presentation", a block's name, or "Leave It to Beaver Marathon (1 of 3)" |
