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
under `/api/v1`, `/api/internal`, `/hls/k/` or `/play/` that didn't come over
HTTPS (as the reverse proxy in front says, with `X-Forwarded-Proto`) is
refused with 403, but for StationPlay's check of itself (`GET
/api/internal/reach`).
On the home network, and through a VPN, plain HTTP is fine.

Wrong passwords are limited as on the page: after 5 wrong ones from one
address within 15 minutes, signing in from there waits (HTTP 429).

When signing in is off, nothing needs a token on the home network.

### Linked devices, and Who's tuning in?

An app that shows a picker of the people who use the device (a household's
TV, say: see `docs/users.md`) says so when it signs in or asks for a code,
with `"picker": true`. The device is then **linked**: the first time, the
answer carries a `deviceKey`, which the app keeps (where only it can read
it) and sends with every picker request, as a header:

```
StationPlay-Device: <deviceKey>
```

From then on, the app opens on the picker (`GET /api/internal/picker`), and
whoever is using it picks themselves (`POST /api/internal/picker/choose`,
with their PIN if they have one), or signs in by name
(`POST /api/internal/picker/sign-in`). Either gives a token for that
person, as signing in does, which lasts a day from when it was last used;
picking someone else ends it. A device key lasts until an Admin unlinks the
device on the Access tab, which also signs out whoever is signed in on it:
anything asked with its key then answers 401, and the app links again. An
app shows the picker when it lists more than one person, or one with a
PIN; otherwise it picks the one person itself. (An Admin without a PIN
gives their password only on a device others use too.)

Apps that don't send `"picker": true` sign in as they always have, and get
no `deviceKey`.

On the public port, only `GET /api/v1/server` (and StationPlay's check of
itself) answers until signing in is on. API tokens (`docs/api.md`) don't
work here: these addresses are for the apps' own sign-ins.

## POST /api/internal/link

Open to anyone: starts signing in with a code. Send which app this is, and
the device's own name, as the Access tab will list it:

```json
{"app": "StationPlay for Roku", "deviceName": "Living Room Roku", "picker": true,
 "deviceKey": "..."}
```

`picker` and `deviceKey` are optional: an app with a picker, and the
`deviceKey` it already has, if any (see Linked devices, above).

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
| `deviceKey` | string or null | For an app with a picker: the device's key, to keep; null when the one sent is still good, or for an app without one |
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
So are `picker` and `deviceKey`, for an app with a picker (see Linked
devices, above).

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `device` | string or null | Keep it, and send it when signing in again; null when the `device` sent is still good |
| `deviceKey` | string or null | For an app with a picker: the device's key, to keep; null when the one sent is still good, or for an app without one |
| `user` | object | Who signed in |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

Answers 401 for a wrong name or password, 429 while signing in waits, and
400 when signing in is off.

## GET /api/internal/picker

Asked with the device's key (`StationPlay-Device`; see Linked devices). Who
can be picked on this device, by name, where it is now (from 1.28.0): at
home (on the home network, or through a VPN), everyone shown on the
household's devices at home; away from home (through the public port), only
those an Admin shows on every device, those who signed in on this device,
and those an Admin chose it for. Ask again when the app comes back to the
front, as the device may have moved:

| Field | Type | What it is |
|---|---|---|
| `device` | string | This device, as the Access tab lists it |
| `people` | list | Who's on its picker |
| `people[].id` | number | Who they are, for `POST /api/internal/picker/choose` |
| `people[].name` | string | Their name |
| `people[].pin` | boolean | Whether picking them asks for their PIN |
| `people[].admin` | boolean | Whether they're an Admin (picking an Admin with no PIN asks for their password) |

Answers 401 when the key isn't good (the device was unlinked: link it
again), and 400 when signing in is off.

## POST /api/internal/picker/choose

Asked with the device's key. Picks someone on its picker:

```json
{"id": 3, "pin": "1234"}
```

`pin` when they have one; `password` instead, for an Admin with no PIN on
a device others use too (its picker lists more than one person).

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who was picked |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

Answers 403 for a wrong PIN or password (with the sentence to show), 429
after 5 wrong PINs for that person in 15 minutes (on any device), and 404
for someone not on this device's picker where it is now (away from home,
someone listed only at home, say). 401 always means the device isn't
linked any more, here and on every picker address: link it again.

## POST /api/internal/picker/sign-in

Asked with the device's key. Signs in by name, with an invite code (made
by an Admin on the Access tab: it works once) or a password:

```json
{"name": "Tia", "code": "K7QM-4DPX"}
```

Or `password`; or `secret`, for one box where either is typed: an invite
code if it is one, otherwise a password. Whoever signs in is on this
device's picker from then on.

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who signed in |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

Answers 403 for a wrong name, code or password, or for someone who can't
sign in by name (they have neither a password nor a PIN: pick them from
the list), with the sentence to show; and 429 after 10 wrong tries on this
device in 15 minutes.

## POST /api/internal/picker/remove

Asked with the device's key and the token of whoever is signed in on it:
takes them off this device's picker, and signs them out. Answers
`{"ok": true}`.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## GET /api/internal/me

Who this app is signed in as now (from 1.27.0), for its Options: an Admin
can rename people, so ask again when it's shown rather than keep the name
from signing in. (Who's tuning in? lists everyone as they're named now.)
Answers 401 when the sign-in has ended.

| Field | Type | What it is |
|---|---|---|
| `user` | object or null | Who it is; null while signing in is off |
| `user.name` | string | Their name, now |
| `user.role` | string | `admin` or `user` |

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

## GET /api/internal/reach

Not for the apps: StationPlay asks this of itself, at the address set for
watching away from home, to check that apps can reach it from outside (the
status on the Access tab, and in the page's header). It's open on both
ports, to anyone, over plain HTTP too, and before there's a user. `?n=` is
a random value a check is waiting for (for a minute at most). For any other
value, it's 404, and nothing more is said.

| Field | Type | What it is |
|---|---|---|
| `stationplay` | boolean | Always true |
| `port` | string | The port the request came in on: `home`, or `public` |
| `https` | boolean | Whether the request came over HTTPS, as the reverse proxy in front says (`X-Forwarded-Proto`) |

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

## POST /api/internal/problem

A problem the app ran into, sent by the app itself as it happens (from
1.23.0, when `features` lists `problems`): kept for the Logs tab, where an
Admin sees each problem with how often, on how many devices, and on what
kinds of device, so they can tell whether it's one device's, one kind of
device's, or everyone's. Send what's known:

```json
{"kind": "station-stopped", "station": 5, "detail": "The picture stopped...",
 "app": "StationPlay for Roku", "version": "0.5.0",
 "device": "Roku Ultra 4850X, Roku OS 14.0", "deviceName": "Den"}
```

`kind` says when the app sends it:

- `station-failed`: a station didn't start (with `station`). Not when every
  tuner is in use or a limit was reached: those are said to the person.
- `station-stopped`: a station stopped playing, and tuning in again didn't
  bring it back (`station`).
- `library-failed`: something from the library didn't play (`title`, as
  it's shown).
- `library-stopped`: playing from the library stopped and couldn't go on
  (`title`).
- `kept-up`: playing couldn't keep up, so a smaller version played
  (`title`, or `station`).
- `crashed`: the app closed unexpectedly last time (sent when it opens
  again; `detail` is the crash's first line).

`detail` is what the app saw, in a sentence (at most 300 characters kept);
`device` is the kind of device, its model and its system, as a problem
report's `Device:` line has it. Never a token, a password or a stream's
private address. The same problem from the same app and device within 10
minutes counts on its first, and is said in StationPlay's log once. At most
30 in 10 minutes from one app on one device: more are answered 429. A
`kind` StationPlay doesn't know is answered 400.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## Your library

When an Admin shares libraries with the apps (on the Access tab, under
**Media in StationPlay's apps**), the apps can browse them and play
their shows and movies on demand. Until then, `features` doesn't list
`library`, and these addresses answer 404 ("No libraries are shared with
StationPlay's apps"). That's on the home network (or through a VPN, which
looks like home), and from 1.27.0, through the public port too while
watching away from home is on (`features` lists `away`): there, a signed-in
app does what it may at home, and `features` lists `library` there too.
Through the public port with watching away from home off, these addresses
answer 403, and `features` doesn't list `library` there. Ask
`GET /api/v1/server` again where the app is (at home, or away) to know.

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
`?sort=`: `title` (the default; titles without a leading "The", "A" or
"An", as the library sorts them), `added` (newest first) or `released`
(newest first). Narrowed (from 1.24.0) by `?genre=` (one of its `genres`)
and `?unwatched=1` (only movies this person hasn't watched, and shows with
episodes they haven't watched); a genre the library hasn't any of leaves
nothing.

| Field | Type | What it is |
|---|---|---|
| `key` | string | The library's key |
| `title` | string | Its name |
| `kind` | string | `show` or `movie` |
| `total` | number | How many shows or movies it has in all, as narrowed |
| `start` | number | Where this page starts |
| `items` | list | This page |
| `items[]` | card | One show or movie |
| `genres` | list | The library's genres, A to Z (from 1.24.0), to narrow it by |
| `genres[]` | string | One genre |
| `letters` | list | Sorted by `title`: where each letter starts in the whole list, as narrowed, for jumping to it (`[]` for the other sorts; from 1.24.0) |
| `letters[].letter` | string | `A` to `Z`, or `#` for titles starting with a digit or anything else |
| `letters[].start` | number | Where its first show or movie is (a `start` to ask for) |

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
| `tagline` | string or null | Its tagline, a line said on its poster (from 1.24.0) |
| `genres` | list | Its genres (its first few) |
| `genres[]` | string | One genre |
| `contentRating` | string or null | Its rating, such as `TV-PG` |
| `studio` | string or null | Its studio, or a show's network |
| `released` | string or null | When it first came out, as `YYYY-MM-DD` |
| `backdrop` | string or null | A wide picture for behind the details (an episode's is its show's) |
| `cast` | list | Who's in it, as billed (up to 20; from 1.24.0) |
| `cast[].name` | string | Their name |
| `cast[].role` | string | The part they play ("" if the library doesn't say) |
| `directors` | list | Who directed it (up to 5; from 1.24.0) |
| `directors[]` | string | A name |
| `writers` | list | Who wrote it (up to 5; from 1.24.0) |
| `writers[]` | string | A name |
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

## GET /api/internal/items/{key}/related

Up to 12 other shows or movies like this one, from its own library (an
episode's are its show's), for More like this: those sharing the most of
its genres first, then the nearest in years. Empty when it has no genres.
From 1.24.0.

| Field | Type | What it is |
|---|---|---|
| `items` | list | Others like it |
| `items[]` | card | One show or movie |

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
track (or of `audio`, if it's sent).

When it can't, StationPlay 1.24.0 makes a copy it can (`features` lists
`convert`), for an app that says it takes one: `device.hls` lists what its
player takes in an HLS playlist, `ts` (MPEG-TS pieces with H.264), `ts-hevc`
(MPEG-TS pieces with HEVC) and `fmp4` (fragmented MP4 pieces; not made yet).
A copy is **repackaged** (`repackage`: the picture as it is, its sound
converted where the device needs it) when the device plays the picture and
its pieces carry it, or else **converted** (`convert`: the picture made
H.264, at most 1080p, ordinary rather than HDR). A copy is also made, with
`device.hls`, when the app sends:

- `subtitle`: the ID of a subtitle track to draw into the picture (for a
  track the player can't show itself: picture subtitles on a player without
  them, and any track inside the file while a copy plays). The copy is
  converted.
- `fit: true` with `maxKbps`: a smaller picture made to fit the connection,
  when no version keeps up. The copy is converted.
- `night: true`: night mode's sound (as the stations' `nightHls`), for an
  app that can't make it itself.

From 1.27.0, while `features` lists `even-sound` (an Admin's switch, on to
start), every episode (never a movie) comes at the stations' loudness, so a
show's episodes match: with `device.hls`, an episode the device plays as it
is comes as a `repackage` copy, its picture as it is and only its sound made
again (what the device would get anyway, but not copied: so sound sent as
it is to a receiver comes as 5.1 or stereo), and its `why` is `["even sound
for the show's episodes"]`; any other copy of an episode has it too, and
says so in its `why`. Where the picture can't be kept as it is, the episode
plays as it is (`direct`). Show the copy's `why` in the player's info.
Without `device.hls`, an episode plays as it did before.

Send `startMs` too: where the player will start (by default, where this
person stopped). A copy's playlist says to start there, and StationPlay
starts making it there. `audio` (a sound track's ID) plays that track; a copy
holds only that one, so another track is another copy: ask again with it and
`startMs` where the viewer is, and `POST` the old one's `leave`.

If the device can't play the file as it is and no copy can be made (the app
didn't send `device.hls`, or nothing it takes would show the file right),
the answer is 422, with `detail` (a sentence to show) and `why` (a list of
the reasons). StationPlay converts at most 3 copies at once, or 6 on a GPU
(repackaging costs next to nothing): one more is answered 503 with
`detail`.

An Admin's limits on devices watching count programs played this way too
(see Playing a station in `docs/api.md`), and through the public port, the
limit on devices away from home as well: one more device is answered 503
with `limit` and `most`.

Away from home (through the public port, from 1.27.0), a program plays at
the quality an Admin chose for Media away from home: as it would at home,
or up to a number of Mbps. With a cap, the best version within it plays (as
it is, or as a copy, as at home); with none within it, a copy is converted
down to fit (`why` says so: "a smaller copy, within the 10 Mbps allowed away
from home"), and any copy converted there stays within it. An app that
doesn't send `device.hls` is answered 422 for a program over the cap, with
`detail` and `why`. `maxKbps` and `fit` work on top of it, as at home.

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
| `method` | string | How it plays: `direct` (the file as it is), `repackage` or `convert` (a copy; from 1.24.0) |
| `url` | string | What the player plays (it needs no token): the file, such as `/play/<session>/file.mkv`, whose ranges are answered so the player can seek; or a copy's HLS playlist, `/play/<session>/index.m3u8`, listing the whole program from its start (a jump far ahead takes a few seconds more to start). Relative to where the app asked: a program started through the public port plays there (and at home), one started at home never plays through the public port |
| `why` | list or null | Why a copy is made (null for `direct`) |
| `why[]` | string | One reason, such as "its sound's format (DTS)", or "even sound for the show's episodes" (from 1.27.0) |
| `audioTrack` | string or null | The sound track in a copy (null for `direct`, where the player chooses among `audio`) |
| `drawnSubtitle` | string or null | The subtitle track drawn into a copy's picture, if any |
| `leave` | string | Where to `POST` when the player stops |
| `resumeMs` | number | Where this person stopped last time (0: the start). Offer to resume there, or start over |
| `durationMs` | number or null | How long it is |
| `bitrateKbps` | number or null | What the file (or a converted copy) needs, in kilobits a second: to tell, when playing keeps stopping to load, whether the connection is too slow for it (see `/api/internal/speed-test`) |
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
| `whenSlow` | string | What the Admin chose for when playing can't keep up here (at home, or away from home through the public port): `offer` (stop, and offer a smaller playable version from where the viewer is) or `switch` (switch to it on its own, and say so) |
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
is no longer shared, when watching away from home is turned off (for one
started through the public port), and when StationPlay restarts (404);
choose the program again to play it again. Through the public port, a
sign-in that ends stops its programs at once.

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

