# tapiOca's API, version 1

tapiOca's API is for your own scripts, home automation and players. It
covers the server, its stations, their guide and streams, and a few actions
an Admin can have tapiOca take. It's a small, fixed set of addresses
under `/api/v1`, part of the server and under the same license.

Its OpenAPI spec is served at `/api/v1/openapi.json`, and kept next to this
document as `docs/openapi-v1.json`. The server's tests
(`tests/test_app_api.py`) check the tables below and the spec against the
server, so the three can't drift apart.

tapiOca's own apps also use addresses of their own, under
`/api/internal`, for signing in, connection tests and Media. Those aren't
part of this API, and they may change with any release.

## The rules

- **Headers and JSON.** Every answer under `/api/v1` carries the header
  `StationPlay-API: 1`. Every answer except a stream is JSON.
- **Version 1 only grows.** New fields and new addresses may be added.
  Nothing is renamed, removed or changed in meaning. Ignore fields you don't
  know. A change that would break a client becomes version 2, served
  alongside version 1.
- **Deprecation.** An address on its way out answers with the headers
  `Deprecation: true`, `Sunset` (the date it goes, at least 6 months
  later) and `Link` (where to read about it, with `rel="deprecation"`).
  Nothing in version 1 is on its way out.
- **Relative addresses.** Addresses in answers (`logo`, `hls`, `art`) are
  relative to the server. Add them to the address you reached the server
  at.
- **Times.** Times are milliseconds since 1970 (UTC).
- **Errors.** An error is an HTTP status with `{"detail": "..."}`, a
  sentence you can show unchanged.
- **From a web page.** A change (`POST`) sent by a browser, which says so
  with an `Origin` header, needs a token, or the header
  `X-Tapioca-Page: 1` that tapiOca's own page sends (403 otherwise, from
  1.36.2). That keeps another site's page from making changes through a
  browser at home while sign-in is off. Scripts send no `Origin`, so
  nothing changes for them.

## Tokens

While signing in to tapiOca is off, nothing needs a token on the home
network. Once tapiOca has users, every request except
`GET /api/v1/server` needs one, sent as:

```
Authorization: Bearer <token>
```

An Admin makes API tokens on the **Access** tab, under **API tokens**. Each
has a name (what it's for, such as "Home Assistant"), a scope, and an
expiration: 30 days, 90 days, a year, or never. A token is shown once, when
it's made. tapiOca keeps only a fingerprint of it (a SHA-256 hash), so
it can't show it again. Tokens start with `spk_`, which makes one easy to
spot if it's pasted where it shouldn't be.

| Scope | What it may do |
|---|---|
| **Viewer** | Read: the server, its stations, their guide, and its status |
| **Admin** | Also what's marked Admin below, such as updating a station from Plex |

A token never does more than the Admin who made it may do now. If they
become a User, their Admin tokens can only read. A token works only under
`/api/v1`, not on tapiOca's page or the apps' own addresses. It stops
working when it expires, when an Admin revokes it on the **Access** tab, and
when the Admin who made it is removed. The **Access** tab shows when each
token was last used, and the access log shows each one made and revoked.

A token that isn't valid (revoked, expired or mistyped) gets 401. A Viewer
token asked to do something gets 403, as does any token used outside
`/api/v1`.

A tapiOca app's sign-in works here too, with whatever its person may do.

From the internet (tapiOca's public port), API tokens are refused until
an Admin turns on **Accept API tokens from the internet** on the **Access**
tab. Then they work only over HTTPS. Anything under `/api/v1` that didn't
come over HTTPS (as the reverse proxy in front reports, with
`X-Forwarded-Proto`) is refused with 403. On the home network, and through a
VPN, plain HTTP is fine. Until signing in is on, only `GET /api/v1/server`
answers on the public port.

## Away from home

Through tapiOca's public port, a station's `hls` and `logo` are the home
addresses, which aren't served there. That changes when an Admin turns on
**tapiOca's apps away from home** on the **Access** tab. Then they're
addresses of the token's own, `/hls/k/<key>/<number>/index.m3u8` and
`/hls/k/<key>/<number>/logo.png`, so a player or a picture needs no token.
The key stops working when the token does, when watching away from home is
turned off, and when tapiOca restarts. When it stops working (404), ask
for `GET /api/v1/stations` again to get new ones.

At home, too, while only listed devices may use the tuner (**Tuner access**
on the **Access** tab, from 1.32.0), a signed-in token's `hls`, `nightHls`
and `logo` are addresses of its own, so the device needn't be listed. They
stop working in the same way (404): ask for `GET /api/v1/stations` again. A
program's `art` (`/art/...`) is part of the tuner, so then only listed
devices get it.

## GET /api/v1/server

What this server is, so a client can tell whether it's a tapiOca it can
talk to. It needs no token.

| Field | Type | What it is |
|---|---|---|
| `name` | string | The server's name (`FRIENDLY_NAME`) |
| `id` | string | The server's ID, the same for as long as its data folder lasts |
| `version` | string | tapiOca's version, such as `1.22.0` |
| `api` | number | The newest version of this API it answers: `1` |
| `signIn` | boolean | Whether requests need a token |
| `notSetUp` | string or null | Why nothing can be done from here yet (the public port, before signing in is on); null otherwise |
| `outside` | boolean | Whether the request came through tapiOca's public port |
| `awayAddress` | string or null | The address tapiOca's apps use away from home (such as `https://tv.example.com`), when an Admin has turned that on; null otherwise |
| `features` | list | What this server offers |
| `features[]` | string | One of them: `hls` (stations as HLS), `speed-test` (connection tests for tapiOca's apps, from 1.20.0), `away` (tapiOca's apps away from home is on), `library` (Media folders are shared with tapiOca's apps, as Media, and can be watched from here; from 1.21.0), `reports` (tapiOca's apps can send problem reports, from 1.22.1), `night` (each station also has night mode's sound, `nightHls`, from 1.23.0), `problems` (tapiOca's apps send the problems they run into, from 1.23.0), `convert` (tapiOca makes copies of what a device can't play directly, from 1.24.0; wherever `library` is offered), `convert-asked` (tapiOca makes a converted copy when an app asks for one, whatever the device plays, from 1.29.1; wherever `library` is offered), `even-sound` (a show's episodes from Media play at the stations' loudness, from 1.27.0; wherever `library` is offered, while it's on) |

## GET /api/v1/stations

Every station, in number order, with what's on now and next.

| Field | Type | What it is |
|---|---|---|
| `stations` | list | The stations |
| `stations[].number` | number | Its number |
| `stations[].name` | string | Its name |
| `stations[].description` | string | Its description (may be empty) |
| `stations[].logo` | string | Its logo, a PNG (a badge with its number if it has none). The address changes when the logo does. Where `hls` is one of the token's own, so is this (see Away from home) |
| `stations[].colors` | object | Colors from its logo, as its Intro Bumper uses them |
| `stations[].colors.dark` | string | The darkest background, as `#RRGGBB` |
| `stations[].colors.light` | string | A lighter background |
| `stations[].colors.accent` | string | The accent |
| `stations[].hls` | string | The station as HLS, to play: `/hls/<number>/index.m3u8` at home, and an address of the token's own from outside. At home, it's one of the token's own too while only listed devices may use the tuner, and for tapiOca's own apps always (from 1.32.0; see Away from home) |
| `stations[].nightHls` | string | The same with night mode's sound (from 1.23.0): `/hls/<number>/night/index.m3u8` at home, or the token's own address, as for `hls`. Loud scenes are much quieter, voices a little quieter, and nothing is louder (from 1.32.0; before, everything was then turned up 8 dB); rumble under 50 Hz is cut (from 1.36.4); the picture is the same. It's made only while something plays it, from the same tuner. An app that leaves reports it at `.../night/leave` |
| `stations[].now` | program or null | What's on now (null before the station's first program) |
| `stations[].next` | program or null | What's on next |

## GET /api/v1/guide

Each station's programs between two times, `?from=` and `?to=`, in
milliseconds. If `from` isn't given, it's now. If `to` isn't given, it's 6
hours after `from`. `from` must be within 7 days of now, and `to` at most 2
days after `from` (400 otherwise).

| Field | Type | What it is |
|---|---|---|
| `from` | number | The start of what's listed |
| `to` | number | The end of what's listed |
| `stations` | list | Each station, in number order |
| `stations[].number` | number | The station's number |
| `stations[].programs` | list | Its programs that overlap `from` to `to`, in order |
| `stations[].programs[]` | program | One program |

The INFO station (99) is listed in 4-hour blocks from midnight, by the
server's clock, each saying what it shows (from 1.36.2). It plays its
2-minute film over and over all the same.

## Playing a station

Each station's `hls` address is an HLS playlist (see Away from home for its
address from outside). The first request starts the station's stream and
waits, up to 25 seconds, until there's enough to start playing. While it
can't play, it answers 503 with `{"detail": "..."}`. When every tuner is in
use, the answer also has `"onNow"`: the numbers of the stations playing,
which a player can offer to join instead. Every player watching a station
shares its one stream, on one tuner.

An Admin can limit how many devices watch at once, and how many of those
watch away from home (on the **Access** tab). A device already watching can
always change stations. One more device gets 503 with `"limit"` (`devices`
or `away`), `"most"` (the limit) and a `detail` to show unchanged, such as
"An Admin has limited tapiOca to 5 devices watching at once, so it runs
smoothly for everyone. Please try again later." Offer to try again rather
than retrying on your own.

When a device stops watching a station, `POST` to the `hls` address with
`index.m3u8` changed to `leave` (such as `/hls/<number>/leave`). If nothing
else is watching, the station's stream stops and its tuner is free at once.
Otherwise it stops once nothing has asked for it for 30 seconds. The answer
is 204, whatever the station.

## GET /api/v1/status

How tapiOca is doing.

| Field | Type | What it is |
|---|---|---|
| `version` | string | tapiOca's version |
| `plexConnected` | boolean | Whether Plex answers |
| `tuners` | number | How many stations can play at once |
| `playing` | list | The stations playing now, to Plex, tapiOca's apps or other players |
| `playing[].number` | number | The station's number |
| `playing[].viewers` | number | How many devices are watching it |

## POST /api/v1/stations/{number}/update

Admin. Updates a station from Plex now, as **Update now** does on the
station's card: new and removed programs, with any held update applied.
Answers 404 for a station that doesn't exist, 502 when Plex can't be read,
and 429 while too many requests to Plex are already waiting (try again in a
moment).

| Field | Type | What it is |
|---|---|---|
| `number` | number | The station's number |
| `changed` | boolean | Whether Plex had anything new for it |

## POST /api/v1/stations/{number}/check

Admin. Starts the quick check of the files of each of a station's programs,
as **Check files** does on the station's card. While a check of that station
is running, it doesn't start another. It reports that check's progress
instead.

| Field | Type | What it is |
|---|---|---|
| `number` | number | The station's number |
| `running` | boolean | Whether the check is still going |
| `total` | number | How many programs it checks (0: no check yet) |
| `done` | number | How many it has checked |
| `newlyBroken` | number | How many it found problems in (they're off the air now, on the Broken files list) |
| `skipped` | number | How many couldn't be checked (their share was down, say) |

## GET /api/v1/stations/{number}/check

Admin. A station's last check of its files, running or done, without
starting one. It has the same fields.

| Field | Type | What it is |
|---|---|---|
| `number` | number | The station's number |
| `running` | boolean | Whether the check is still going |
| `total` | number | How many programs it checks (0: no check yet) |
| `done` | number | How many it has checked |
| `newlyBroken` | number | How many it found problems in (they're off the air now, on the Broken files list) |
| `skipped` | number | How many couldn't be checked (their share was down, say) |

## POST /api/v1/guide/refresh

Admin. Asks Plex to refresh its guide from tapiOca, as tapiOca does
on its own after a change.

| Field | Type | What it is |
|---|---|---|
| `refreshed` | boolean | Whether Plex agreed to (false: Plex didn't answer in time, or has no tapiOca tuner) |

## POST /api/v1/backups

Admin. Backs up tapiOca now, as it does every night, into the `backups`
folder inside its data folder, which keeps the last 7. Answers 201. The
Backups section of the **Setup** tab lists the backup, to download or
restore.

| Field | Type | What it is |
|---|---|---|
| `name` | string | The backup's file name |

## GET /api/v1/openapi.json

This API's OpenAPI 3.1 spec: each address, what it answers and the token it
takes. Read it as you would any other address (with a token, once signing in
is on).

## A program

How the stations and the guide describe a program.

| Field | Type | What it is |
|---|---|---|
| `start` | number | When it starts |
| `end` | number | When it ends (including the commercials after it) |
| `kind` | string | `episode` or `movie` |
| `title` | string | The show's title, or the movie's |
| `episodeTitle` | string or null | The episode's title (null for a movie) |
| `season` | number or null | The season |
| `episode` | number or null | The episode |
| `year` | number or null | The year |
| `summary` | string | What it's about (may be empty) |
| `art` | string | Its picture, on the home network: the show's, or the movie's. It's part of the tuner: while only listed devices may use it (from 1.32.0), only they get it |
| `special` | string or null | The special it's part of: "Feature Presentation", a block's name, or "Maple Street Marathon (1 of 3)" |
