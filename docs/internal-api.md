# StationPlay's apps: their own addresses

> **Internal: for StationPlay's own apps only.** This isn't a public API:
> it isn't in the OpenAPI spec, and it may change with any release. For
> your own scripts and players, use StationPlay's API (`docs/api.md`).

What StationPlay's own apps (iPhone, iPad, Apple TV, Android, Google TV,
Fire TV, Roku) ask the server besides StationPlay's API: signing in,
connection tests, and your library on demand, under `/api/internal`. The
apps also use the API itself (`docs/api.md`) for the server, its stations
and their guide, and play stations as it describes.

The rules are the API's (`docs/api.md`): every answer carries the header
`StationPlay-API: 1`, addresses in answers are relative to the server,
times are milliseconds since 1970 (UTC), and an error is an HTTP status
with `{"detail": "..."}`. The apps ignore fields they don't know. These
addresses change only along with the apps that use them, and the tables
below are checked against the server by its tests
(`tests/test_app_api.py`), so this document and the server can't drift
apart.

## Signing in

When StationPlay has users (signing in is on), an app signs in one of two
ways, and gets a token to send with every request:

- **With a code** (for TVs, and anything without a handy keyboard): the app
  shows a code, someone signed in on StationPlay's page enters it at `/link`,
  sees which app on which device it is, and links it to their account. No
  password is typed on a remote or sent by the TV. See
  `POST /api/internal/link`.
- **With a name and password**, as on the page. See
  `POST /api/internal/sign-in`.

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
under `/api/v1`, `/api/internal` or `/hls/k/` that didn't come over HTTPS
(as the reverse proxy in front says, with `X-Forwarded-Proto`) is refused
with 403. On the home network, and through a VPN, plain HTTP is fine.

Wrong passwords are limited as on the page: after 5 wrong ones from one
address within 15 minutes, signing in from there waits (HTTP 429).

When signing in is off, nothing needs a token on the home network.

On the public port, only `GET /api/v1/server` answers until signing in is
on. API tokens (`docs/api.md`) don't work here: these addresses are for
the apps' own sign-ins.

## POST /api/internal/link

Open to anyone: starts signing in with a code. Send which app this is, and
the device's own name, as the Access tab will list it:

```json
{"app": "StationPlay for Roku", "deviceName": "Living Room Roku"}
```

Show `code`, and where to enter it: StationPlay's page at `linkAt` (an app
that knows the page's address shows it whole, such as
`http://192.168.1.20:3310/link`). Then `POST /api/internal/link/check` with
`poll` every `interval` seconds until it answers with a token, or the code
runs out. Keep `poll` to the app: whoever has it gets the sign-in.

| Field | Type | What it is |
|---|---|---|
| `code` | string | The code to show, such as `K7QM-4DPX` |
| `poll` | string | The app's secret for checking back |
| `expiresIn` | number | Seconds until the code runs out (600) |
| `interval` | number | Seconds between checks (3) |
| `linkAt` | string | Where on StationPlay's page the code is entered |

Answers 400 when signing in is off, and 429 when one address has asked for
too many codes lately.

## POST /api/internal/link/check

Open to anyone. Send `{"poll": "..."}`. Answers 202 (`{"detail": ...}`)
while the code is waiting to be entered, 404 once it has run out (start
again), and once it's linked, the sign-in, just once:

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who linked it |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

## POST /api/internal/sign-in

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

## POST /api/internal/sign-out

Ends the token it's sent with. Answers `{"ok": true}`.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## GET /api/internal/speed-test

A connection test: data for the app to time, so the Admin can see how fast
StationPlay reaches devices (at home, and away from home, where it's the
home internet's upload) and how many can watch at once. `?mb=` is how many
megabytes (1 to 64; 20 if it isn't given). The data is random, so nothing
along the way can shrink it, and it has a `Content-Length`. An app times it
from a moment after the data starts (so the connection's start-up isn't
counted), and may stop reading after about 8 seconds on a slow connection.
One test from an address at a time: another within 10 seconds is answered
429.

## POST /api/internal/speed-test

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

## POST /api/internal/report

A problem report, for whoever is looking into a problem (from 1.22.1, when
`features` lists `reports`): what the app did lately, and on what device.
It goes in StationPlay's log, and so in the Logs tab, as a warning that
starts "Report from" and the app's name (with who's signed in). Send:

```json
{"text": "...", "app": "StationPlay for Android TV", "deviceName": "Den"}
```

`text` is lines of plain text: the app's and device's details, then what
it did lately, oldest first, with any crash. Never a token or a password.
StationPlay keeps at most 400 lines or 24,000 characters of it, and says
how many it left off. One report from an address every 30 seconds:
another is answered 429. An empty one is answered 400.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

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
`/api/internal/art`: add `&w=` with the width it will be shown at, in
pixels, and send the app's token with them.

Each person has their own place in what they watch (the Resume row,
where to resume, what they've watched), kept by StationPlay. While signing
in is off, everyone shares one.

## GET /api/internal/libraries

The shared libraries, in the library's own order.

| Field | Type | What it is |
|---|---|---|
| `libraries` | list | The shared libraries |
| `libraries[].key` | string | Its key |
| `libraries[].title` | string | Its name, such as "TV Shows" |
| `libraries[].kind` | string | `show` (a library of shows) or `movie` |

## GET /api/internal/libraries/{key}

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

## GET /api/internal/home

What the app's home screen shows.

| Field | Type | What it is |
|---|---|---|
| `continue` | list | The Resume row: what this person is partway through, and the next episode of shows they've been watching, newest first (up to 20) |
| `continue[]` | card | An episode or movie; `positionMs` is where to start it |
| `added` | list | Each shared library's recently added shows or movies (libraries with none are left out) |
| `added[].library` | string | The library's key |
| `added[].title` | string | Its name |
| `added[].items` | list | Its newest movies, or the shows with the newest episodes (up to 20) |
| `added[].items[]` | card | One show or movie |

## GET /api/internal/search

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

## GET /api/internal/items/{key}

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
| `markers` | object | (An episode) where its intro and closing credits are, for the Skip intro and Skip credits buttons. Movies have none, so they have no Skip buttons |
| `markers.intro` | list or null | The intro, as `[startMs, endMs]`: show Skip intro from its start until its end, and skip to its end. Null if it hasn't one, or Plex's markers don't fit its file |
| `markers.intro[]` | number | A time in it, in milliseconds from its start |
| `markers.credits` | list or null | The closing credits, as `[startMs, endMs]`; null if it hasn't them, or Plex's markers don't fit its file |
| `markers.credits[]` | number | A time in it |
| `markers.creditsToEnd` | boolean | Whether the credits run to its end: Skip credits then goes on to the next episode (or finishes), rather than to a scene after them |
| `picture` | object or null | (An episode or movie) its picture |
| `picture.size` | string or null | `4K`, `1080p`, `720p`, `576p`, `480p` or `SD` (of its best version) |
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
| `versions` | list | (An episode or movie) its versions, the best first: the biggest picture, HDR before not, then the most detail. One for most; more where the library has the same title as 4K and 1080p files, say |
| `versions[].id` | string | The version's ID, to play it (`version` in `POST /api/internal/play`) |
| `versions[].name` | string | How to list it, such as "4K · HDR10" or "1080p" (with its format, or its Mbps, where two would read the same) |
| `versions[].size` | string or null | As `picture.size` |
| `versions[].hdr` | string or null | As `picture.hdr` |
| `versions[].bitrateKbps` | number or null | What it needs, in kilobits a second |

Its `picture`, `audio` and `subtitles` are its best version's.

## GET /api/internal/items/{key}/episodes

A show's episodes, in order (specials last): all of them, or one season's
with `?season=`.

| Field | Type | What it is |
|---|---|---|
| `show` | string | The show's key |
| `season` | number or null | The season asked for (null: all of them) |
| `episodes` | list | Its episodes |
| `episodes[]` | card | One episode |

## GET /api/internal/art/{key}

A picture, as JPEG or PNG: `?kind=poster` (the default; 2:3, an episode's is
its show's), `backdrop` (16:9) or `thumb` (an episode's still, 16:9), made
`?w=` pixels wide (rounded up to 160, 320, 480, 720, 1280 or 1920). 404 if
there's no such picture.

## POST /api/internal/play

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
Vision); `[]` for a screen without HDR. Add `"version"` (a version's `id`
from its details) to play that version. Without it, the best version the
device can play as it is plays, unless the app sends `"maxKbps"`: how much
its connection to StationPlay carries, as it measured lately (with
`/api/internal/speed-test`). Then the best one that connection keeps up with
plays (it needs no more than two-thirds of it, on average), or with none,
the smallest the device can play. A file plays as it is when the
device can play its file type, its picture's format at its size and bit
depth, its HDR (Dolby Vision profile 5 needs `dv`; other profiles also play
as the HDR10, HLG or ordinary picture beneath), and the sound of its default
track. If it can't, the answer is 422, with
`detail` (a sentence to show) and `why` (a list of the reasons): StationPlay
doesn't convert files for the apps yet.

An Admin's limits on devices watching count programs played this way too
(see Playing a station in `docs/api.md`): one more device is answered 503
with `limit` and `most`.

Skip intro and Skip credits are for episodes only. Show Skip intro while
the player is inside `markers.intro`, and Skip credits inside
`markers.credits`, again whenever the viewer goes back into them; pressing
one moves to the end of that part, or with `creditsToEnd`, on to the next
episode. Offer them; skip without asking only where the viewer has turned
that on. Movies have no markers, since where a movie's credits start is too
often uncertain.

When playing keeps stopping to load, let the player's buffer deal with it
first. Only trouble that lasts counts (the Android app: nothing in the first
45 seconds but one 20-second stall; then 4 stalls of a second or more within
3 minutes, 20 seconds of them, or frames not drawn in time through most of a
minute). Then short tests say where it is: a connection test
(`/api/internal/speed-test`) against `bitrateKbps`, and how fast the file
itself has been arriving. If a smaller version is `playable`, do as
`whenSlow` says, from where the viewer is, but switch on its own only when
the tests showed where the trouble is (otherwise offer it); with none, say
so plainly.

| Field | Type | What it is |
|---|---|---|
| `session` | string | This playing's ID (for progress reports) |
| `method` | string | How it plays: `direct` (the file as it is) |
| `url` | string | What the player plays (it needs no token), such as `/play/<session>/file.mkv`. Ranges are answered, so the player can seek |
| `leave` | string | Where to `POST` when the player stops |
| `resumeMs` | number | Where this person stopped last time (0: the start). Offer to resume there, or start over |
| `durationMs` | number or null | How long it is |
| `bitrateKbps` | number or null | What the file needs, in kilobits a second: to tell, when playing keeps stopping to load, whether the connection is too slow for it (see `/api/internal/speed-test`) |
| `version` | string or null | The version playing |
| `versions` | list | Its versions, the best first, as in its details |
| `versions[].id` | string | As in its details |
| `versions[].name` | string | As in its details |
| `versions[].size` | string or null | As in its details |
| `versions[].hdr` | string or null | As in its details |
| `versions[].bitrateKbps` | number or null | As in its details |
| `versions[].playable` | boolean | Whether this device can play it as it is |
| `versions[].why` | list or null | Why not, as in a 422's `why` (null when it can) |
| `versions[].why[]` | string | One reason |
| `versions[].fits` | boolean or null | Whether the connection keeps up with it (`maxKbps`); null when that, or what it needs, isn't known |
| `whenSlow` | string | What the Admin chose for when playing can't keep up here: `offer` (stop, and offer a smaller playable version from where the viewer is) or `switch` (switch to it on its own, and say so) |
| `markers` | object | As in its details |
| `markers.intro` | list or null | As in its details |
| `markers.intro[]` | number | As in its details |
| `markers.credits` | list or null | As in its details |
| `markers.credits[]` | number | As in its details |
| `markers.creditsToEnd` | boolean | As in its details |
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

## POST /api/internal/progress

Where this person is in an episode or movie: send `{"key": "1234",
"positionMs": 1325000, "session": "..."}` every 10 seconds or so while it
plays (`session` keeps the device counted as watching), and when it stops.
Or mark it from a menu: `{"key": "1234", "watched": true}` (or `false`).

Reaching an episode's closing credits (or 90% of the way, for a movie or
an episode without them) marks it watched and starts it from the beginning
next time. Less than a minute in
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

