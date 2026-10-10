# StationPlay's apps: their own addresses

> **Internal: for StationPlay's own apps only.** This isn't a public API. It
> isn't in the OpenAPI spec, and it may change with any release. For your
> own scripts and players, use StationPlay's API (`docs/api.md`).

StationPlay's own apps (iPhone, iPad, Apple TV, Android, Google TV, Fire TV,
Roku) use these addresses, under `/api/internal`, for signing in,
connection tests and Media. For the server, its stations and their guide,
the apps use StationPlay's API (`docs/api.md`), and they play stations as it
describes.

The API's rules (`docs/api.md`) apply here too. Every answer carries the
header `StationPlay-API: 1`. Addresses in answers are relative to the
server. Times are milliseconds since 1970 (UTC). An error is an HTTP status
with `{"detail": "..."}`. The apps ignore fields they don't know.

These addresses change only along with the apps that use them. The
server's tests (`tests/test_app_api.py`) check the tables below against the
server, so this document and the server can't drift apart.

## Signing in

When StationPlay has users (signing in is on), an app signs in one of two
ways, and gets a token to send with every request:

- **With a code.** This suits TVs, and anything without a handy keyboard.
  The app shows a code. Someone signed in on StationPlay's page enters it
  at `/link`, sees which app on which device it is, and links it to their
  account. No password is typed on a remote or sent by the TV. See
  `POST /api/internal/link`.
- **With a name and password.** This works as on StationPlay's page. See
  `POST /api/internal/sign-in`.

Either way, the app then sends its token with every request:

```
Authorization: Bearer <token>
```

A token lasts 30 days from when it was last used, like a browser's sign-in.
It ends when the app signs out, when its person gets a new password or is
removed, and when an Admin signs that app out under **Signed-in apps** on
the **Access** tab. That list shows each app by the name and device it
gave. Sign-ins, links and sign-outs show in the access log. Apps keep their
token where only they can read it (the Keychain on Apple devices, Android's
Keystore, a Roku's own storage for the app), and never show it.

From the internet (the public port), apps connect only over HTTPS. Anything
under `/api/v1`, `/api/internal`, `/hls/k/` or `/play/` that didn't come
over HTTPS is refused with 403. (The reverse proxy in front reports this
with `X-Forwarded-Proto`.) The only exception is StationPlay's check of
itself (`GET /api/internal/reach`). On the home network, and through a VPN,
plain HTTP is fine.

Wrong passwords are limited as on StationPlay's page. After 5 wrong ones
from one address within 15 minutes, signing in from there must wait (HTTP
429).

When signing in is off, nothing needs a token on the home network.

### Linked devices, and Who's tuning in?

An app may show a picker of the people who use the device, such as a
household's TV (see `docs/users.md`). It says so with `"picker": true` when
it signs in or asks for a code. The device is then **linked**. The first
time, the answer carries a `deviceKey`. The app keeps it where only it can
read it, and sends it as a header with every picker request:

```
StationPlay-Device: <deviceKey>
```

From then on, the app opens on the picker (`GET /api/internal/picker`).
Whoever is using it picks themselves (`POST /api/internal/picker/choose`,
with their PIN if they have one) or signs in by name
(`POST /api/internal/picker/sign-in`). Either gives a token for that
person, as signing in does. This token lasts a day from when it was last
used, and picking someone else ends it.

A device key lasts until an Admin unlinks the device on the **Access** tab.
That also signs out whoever is signed in on it. Anything asked with its key
then answers 401, and the app links again.

An app shows the picker when it lists more than one person, or one person
with a PIN. Otherwise it picks that person itself. (An Admin without a
PIN gives their password only on a device others use too.)

Apps that don't send `"picker": true` sign in as they always have, and get
no `deviceKey`.

### A PIN, after the first sign-in

From 1.28.0, three sign-in answers carry `askPin`: signing in with a
password or an invite code (`POST /api/internal/sign-in`,
`POST /api/internal/picker/sign-in`), or with a code entered on
StationPlay's page (`POST /api/internal/link/check`). `askPin` says whether
to ask this person, right then, to choose a 4-digit PIN for picking
themselves on Who's tuning in? (The fields call it `pin`.) It's true while
they have none and haven't chosen to have none. Offer both:

- **A PIN.** 4 digits, typed twice to be sure, sent with
  `POST /api/internal/pin` as `{"pin": "1234"}`. From then on, picking them
  on any device asks for it.
- **No PIN.** Send `{"pin": null}`. They aren't asked again, on any
  device. For an Admin, explain what that means: on a device others use
  too, they give their password instead.

If they leave without choosing, they're asked again the next time they sign
in with their password or a code. Someone with a PIN isn't asked. The
app's Options shows whether they have one (`user.pin` in
`GET /api/internal/me`), so they can choose a new one there, or none. An
Admin who has a PIN can't remove it in an app. That's refused, with
the sentence to show, so offer an Admin only a new one.

### What 1.28.0 asks of the apps

1. **Who's tuning in?** Ask `GET /api/internal/picker` each time the picker
   shows, and again when the app comes back to the front. A device lists
   fewer people away from home than at home. When picking someone answers
   404, they aren't on this device's list where it is now, so ask for the
   list again.
2. **After signing in** with a password, an invite code or a code entered on
   StationPlay's page: when `askPin` is true, ask for a PIN (typed
   twice) or No PIN, and send it with `POST /api/internal/pin`.
3. **Options.** Ask `GET /api/internal/me` when Options opens. Show whether
   the person has a PIN (`user.pin`), with Change PIN and No
   PIN (not for an Admin who has one). Show Change password only while
   `user.canChangePassword` is true (`POST /api/internal/password`), and
   keep the `token` it answers with in place of the app's.
4. **Every refusal** carries a sentence to show unchanged (`detail`).

A server before 1.28.0 doesn't send `askPin`, `user.pin` or
`user.canChangePassword`, and doesn't have the two new addresses. Without
those fields, leave out what they'd offer.

On the public port, only `GET /api/v1/server` (and StationPlay's check of
itself) answers until signing in is on. API tokens (`docs/api.md`) don't
work on these addresses, which are for the apps' own sign-ins.

## What 1.29.0 asks of the apps

1. **Options: Audio language and Subtitles.** Ask `GET /api/internal/me`
   when Options opens. Offer **Audio language** (each file's own, or one of
   `languages.choices`, listed by `name`) and **Subtitles**: on or off, and
   their language (the audio's, or one of `choices`). Save each change with
   `PUT /api/internal/languages`. It applies on every device the person
   uses (see Languages).
2. **Playing.** Send `device.subtitles` with `POST /api/internal/play`: the
   subtitle formats the player shows itself. Don't send `audio` or
   `subtitle` when a program starts, since StationPlay chooses from the
   person's languages. When `chosen` isn't null, select `chosen.audio` and
   `chosen.subtitle` in the player. (A separate subtitle file comes from
   `subtitles[].url`. One that's `drawnSubtitle` is already in the
   picture.) Show `chosen.audioWhy` and `chosen.subtitleWhy` in the
   player's info. When `chosen` is null, the player chooses, as before.
3. **The player's Audio & subtitles.** Offer **Remember for the whole
   show**, on by default for an episode. (A movie's choice belongs to the
   movie.) When the viewer chooses a sound track, or subtitles (or none),
   save it with `PUT /api/internal/items/{key}/languages`:
   - With it on, save it for the show (`showKey`), and clear the episode's
     own choice (`DELETE` its key) so the show's applies.
   - With it off, save it for the episode alone (or the movie).
   - Send the track's `languageCode` as `audio`. For subtitles, send
     `captions: true` and their `languageCode` as `captionLanguage`. For a
     forced track, or none, send `captions: false`.
   - A track whose `languageCode` is null can't be saved, so leave that one
     out.

   Then switch tracks as before. The player switches among a file's own
   tracks. For a copy, ask `POST /api/internal/play` again, with `audio` and
   `subtitle` as the viewer has them (null for none) and `startMs` where
   they are, and `POST` the old one's `leave`.
4. **Alerts, for Admins.** For an Admin (`user.role` is `admin`, or signing
   in is off), ask `GET /api/internal/alerts` when the app opens and comes
   back to the front, and every few minutes while it's open. Show the
   current alerts, each `sentence` unchanged with how long it's lasted (see
   Admin alerts), and show when one is fixed.
   - Android also asks every 15 minutes in the background (WorkManager). It
     notifies once for each new `id`, and once when it's fixed.
   - Apple's apps also ask when iOS lets them refresh in the background, as
     well as when they open.
   - The Roku app shows how many there are in the guide's header, which
     opens the list.
5. **PIN.** From 1.31.0, StationPlay's page and its sentences say "PIN"
   (1.28.0 to 1.30.0 said "passcode"); the apps say the same. The fields
   were always `pin`.

A server before 1.29.0 doesn't send `languages` (in `GET /api/internal/me`
and an item's details), `chosen` or `languageCode`, and answers 404 for the
new addresses. Without them, leave out what they'd offer (and show no
alerts).

## What 1.30.0 asks of the apps

1. **Progress in order.** Number each playing's progress reports
   (`sequence`: 1, 2, 3..., from 1 again for each `POST /api/internal/play`).
   Then one that arrives late never moves the viewer back (see
   `POST /api/internal/progress`). Send the last one as the player stops,
   before its `leave`.
2. **One program at a time.** Starting a program ends the one the device
   was playing (its addresses answer 404). Ask for the next episode when
   it's time to play it, not while another plays. Switching sound tracks
   or versions works as before.
3. **Up next from StationPlay.** Show a show's `next`, and the Resume row,
   as they come (see Up next and the Resume row). Don't work out what's
   next in the app. When an episode ends and the next should play, report
   where it ended, then ask for its show's details for `next`.
4. **A show's episodes a page at a time.**
   `GET /api/internal/items/{key}/episodes` answers up to 500 at once (a
   whole season, for all but the longest), with `total` and `start`. While
   `start` plus the episodes you have is less than `total`, ask for more
   with `?start=`.
5. **Pictures.** Keep each one a day, by its address. Then ask with
   `If-None-Match` and its `ETag`. A 304 means the one you have is still
   current.
6. **503 means try again.** When Plex is slow or unreachable, the library's
   addresses answer within 8 seconds with 503 and a sentence to show. Offer
   to try again. What was being fetched carries on, so it's often ready a
   moment later.
7. **Report a problem.** Offer it on a movie's or an episode's page, in the
   player's menu, and in a station's player, when `user.canReport` is true
   in `GET /api/internal/me` (and always while signing in is off). When
   it's chosen, ask `GET /api/internal/report-choices` for the choices. Show
   them under their groups, in order, and never a list of your own. Send
   the one picked with `POST /api/internal/report-problem`:
   - Send the key, or for a station's player, the station's number.
   - From a player, also send where it is (`positionMs`) and how it's
     playing (`method`, `version`, `audio`, `subtitle`).
   - Show the answer's `detail` unchanged ("Thanks. An Admin will take a
     look."). Show a refusal's `detail` unchanged too, such as a limit
     ("You've reported this one today. Thanks.") or reporting turned off.

   See Reporting a problem.
8. **What's broken doesn't play.** A version StationPlay found broken never
   plays. When another version plays in its place, `why` says so (for
   `direct` too, so show it in the player's info). When every version is
   broken, the answer is 422 with the `detail` "This one can't play right
   now. An Admin has been told." Show it unchanged. An item's
   `versions[].problem` shows what was found in each version (`broken` or
   `damaged`). Mark a broken one, so the viewer chooses another.
9. **Problems say what and where.** With `library-failed` and
   `library-stopped`, send the playing's `session` and `positionMs` (see
   `POST /api/internal/problem`). StationPlay checks that file at that point
   first.
10. **Alerts about files.** For an Admin, alerts may now be `files` (see
    Admin alerts). Notify once for each `id`, as for any other alert. If
    the app links to StationPlay's page, offer a way to its **Broken files**
    tab.

A server before 1.30.0 ignores `sequence`. It answers a show's episodes all
at once without `total` and `start` (take them as the whole list), and
sends pictures without an `ETag`. It doesn't send `user.canReport`,
`versions[].problem` or `files` alerts, and answers 404 for the report
addresses. Without them, don't offer Report a problem.

## POST /api/internal/link

Open to anyone. Starts signing in with a code. Send which app this is, and
the device's own name, as the **Access** tab will list it:

```json
{"app": "StationPlay for Roku", "deviceName": "Living Room Roku", "picker": true,
 "deviceKey": "..."}
```

`picker` and `deviceKey` are optional. Send `picker` from an app with a
picker, and `deviceKey` if the app already has one (see Linked devices,
above).

Show `code`, and where to enter it: StationPlay's page at `linkAt`. An app
that knows the page's address shows it in full, such as
`http://192.168.1.20:3310/link`. Then send `poll` to
`POST /api/internal/link/check` every `interval` seconds, until it answers
with a token or the code expires. Keep `poll` inside the app: whoever has it
gets the sign-in.

| Field | Type | What it is |
|---|---|---|
| `code` | string | The code to show, such as `K7QM-4DPX` |
| `poll` | string | The app's secret for checking back |
| `expiresIn` | number | Seconds until the code runs out (600) |
| `interval` | number | Seconds between checks (3) |
| `linkAt` | string | Where on StationPlay's page the code is entered |

Answers 400 when signing in is off, and 429 when one address has asked for
too many codes recently.

## POST /api/internal/link/check

Open to anyone. Send `{"poll": "..."}`. It answers 202 (`{"detail": ...}`)
while the code is waiting to be entered, and 404 once the code has expired
(start again). Once it's linked, it answers with the sign-in, just once:

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `deviceKey` | string or null | For an app with a picker: the device's key, to keep; null when the one sent is still good, or for an app without one |
| `user` | object | Who linked it |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |
| `askPin` | boolean | Whether to ask them now to choose a PIN, or none (from 1.28.0: see A PIN, after the first sign-in) |

## POST /api/internal/sign-in

Open to anyone. Send:

```json
{"name": "Sam", "password": "...", "device": "...",
 "app": "StationPlay for iPhone", "deviceName": "Sam's iPhone"}
```

`device` is optional. It's the `device` from an earlier sign-in on this
device. With it, this device can still sign in while too many wrong
passwords from the internet hold everyone else back, as a browser that has
signed in before can. `app` and `deviceName` are optional too: they're how
the **Access** tab lists this sign-in. So are `picker` and `deviceKey`, for
an app with a picker (see Linked devices, above).

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `device` | string or null | Keep it, and send it when signing in again; null when the `device` sent is still good |
| `deviceKey` | string or null | For an app with a picker: the device's key, to keep; null when the one sent is still good, or for an app without one |
| `user` | object | Who signed in |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |
| `askPin` | boolean | Whether to ask them now to choose a PIN, or none (from 1.28.0: see A PIN, after the first sign-in) |

Answers 401 for a wrong name or password, 429 while signing in must wait,
and 400 when signing in is off.

## GET /api/internal/picker

Sent with the device's key (`StationPlay-Device`; see Linked devices). From
1.28.0, it lists who can be picked on this device, by name, where the
device is now:

- Those who signed in on this device.
- Those an Admin chose it for.
- Those an Admin shows on every device, at home and away.
- At home (on the home network, or through a VPN), also those shown on
  every device at home.

From 1.31.0, new people show only on devices they sign in on, unless an
Admin chose otherwise. So a device just linked may list only whoever linked
it. Ask again when the app comes back to the front, since the device may
have moved.

| Field | Type | What it is |
|---|---|---|
| `device` | string | This device, as the **Access** tab lists it |
| `people` | list | Who's on its picker |
| `people[].id` | number | Who they are, for `POST /api/internal/picker/choose` |
| `people[].name` | string | Their name |
| `people[].pin` | boolean | Whether picking them asks for their PIN |
| `people[].admin` | boolean | Whether they're an Admin (picking an Admin with no PIN asks for their password) |

Answers 401 when the key isn't valid (the device was unlinked, so link it
again), and 400 when signing in is off.

## POST /api/internal/picker/choose

Sent with the device's key. Picks someone on its picker:

```json
{"id": 3, "pin": "1234"}
```

Send `pin` (their PIN) when they have one. Send `password` instead for
an Admin with no PIN on a device others use too (its picker lists more
than one person).

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who was picked |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |

Answers 403 for a wrong PIN or password (with the sentence to show).
Answers 429 after 5 wrong PINs for that person in 15 minutes, on any
device. Answers 404 for someone not on this device's picker where it is
now, such as someone listed only at home while the device is away from
home. 401 always means the device isn't linked anymore, here and on every
picker address, so link it again.

## POST /api/internal/picker/sign-in

Sent with the device's key. Signs in by name, with an invite code or a
password. (An Admin makes invite codes on the **Access** tab, and each one
works once.)

```json
{"name": "Tia", "code": "K7QM-4DPX"}
```

Send `password` instead of `code`, or send `secret` for a single box where
either is typed. StationPlay treats `secret` as an invite code if it is
one, and otherwise as a password. Whoever signs in is on this device's
picker from then on.

| Field | Type | What it is |
|---|---|---|
| `token` | string | Send it as `Authorization: Bearer <token>` |
| `user` | object | Who signed in |
| `user.name` | string | Their name |
| `user.role` | string | `admin` or `user` |
| `askPin` | boolean | Whether to ask them now to choose a PIN, or none (from 1.28.0: see A PIN, after the first sign-in) |

Answers 403, with the sentence to show, for a wrong name, code or password.
It also answers 403 for someone who can't sign in by name, because they have
neither a password nor a PIN (pick them from the list instead).
Answers 429 after 10 wrong tries on this device in 15 minutes.

## POST /api/internal/picker/remove

Sent with the device's key and the token of whoever is signed in on it.
Takes them off this device's picker, and signs them out. Answers
`{"ok": true}`.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## GET /api/internal/me

From 1.27.0, shows who this app is signed in as now, for its Options. An
Admin can rename people, so ask again when Options shows, rather than keep
the name from signing in. (Who's tuning in? lists everyone by their current
name.) From 1.29.0, it includes their languages too. Answers 401 when the
sign-in has ended.

| Field | Type | What it is |
|---|---|---|
| `user` | object or null | Who it is; null while signing in is off |
| `user.name` | string | Their name, now |
| `user.role` | string | `admin` or `user` |
| `user.pin` | boolean | Whether they have a PIN (from 1.28.0) |
| `user.canChangePassword` | boolean | Whether they may change their password in the app (from 1.28.0): false for someone without a password, and for someone an Admin turned that off for. Offer Change password only when it's true |
| `user.canReport` | boolean | Whether they may report a problem (from 1.30.0: see Reporting a problem): false for someone an Admin turned that off for. Offer Report a problem only when it's true (and while signing in is off, always) |
| `languages` | object | Their own languages, for Options (from 1.29.0: see Languages); while signing in is off, everyone's |
| `languages.audio` | object or null | The sound's language; null: each file's default track |
| `languages.audio.code` | string | Its code, such as `jpn` |
| `languages.audio.name` | string | Its name, such as "Japanese" |
| `languages.captions` | boolean | Whether subtitles are on |
| `languages.captionLanguage` | object or null | The subtitles' language; null: the language of the sound that plays |
| `languages.captionLanguage.code` | string | Its code |
| `languages.captionLanguage.name` | string | Its name |
| `languages.choices` | list | Every language StationPlay knows, A to Z by name, to choose from |
| `languages.choices[].code` | string | Its code |
| `languages.choices[].name` | string | Its name |

## PUT /api/internal/languages

From 1.29.0, sets the person's own languages for every device, as chosen
in the app's Options (see Languages). Send it with the app's token, or
without one while signing in is off. Send only what changes. What isn't
sent stays unchanged:

```json
{"audio": "jpn", "captions": true, "captionLanguage": "eng"}
```

`audio` and `captionLanguage` are a language's code, or null. For `audio`,
null means each file's default track. For `captionLanguage`, null means the
sound's language. `captions` (subtitles on or off) is true or false. It
only ever sets the languages of the person signed in, and anything else
sent is ignored. Answers 400, with the sentence to show, for a language
StationPlay doesn't know, and for `captions` that isn't true or false.

| Field | Type | What it is |
|---|---|---|
| `audio` | object or null | The sound's language, as in `GET /api/internal/me` |
| `audio.code` | string | Its code |
| `audio.name` | string | Its name |
| `captions` | boolean | Whether subtitles are on |
| `captionLanguage` | object or null | The subtitles' language |
| `captionLanguage.code` | string | Its code |
| `captionLanguage.name` | string | Its name |

## POST /api/internal/pin

From 1.28.0, the person signed in chooses their own PIN, with the
app's token. Send `{"pin": "1234"}` (exactly 4 digits, each 0 to 9), or
`{"pin": null}` for none. None removes any PIN they have, and they
aren't asked again, on any device.

A sign-in made with their password, an invite code or their PIN
proves it's them. So a new PIN needs nothing more, even to replace one
they have. A sign-in made by picking them on Who's tuning in? without a
PIN doesn't prove it, since anyone at that device could have done it.
From 1.28.1, such a sign-in can't set or remove a PIN, so sign in with
a password or an invite code first.

The access log shows "Tia set a PIN in StationPlay for Android on
Tia's phone" or "Tia chose no PIN in ...".

| Field | Type | What it is |
|---|---|---|
| `pin` | boolean | Whether they have a PIN now |

Answers 400 for a PIN that isn't 4 digits, and 400 while signing in is
off. Answers 403, with the sentence to show:

- **An Admin removing theirs.** An Admin needs a PIN, or their
  password on a device others use too.
- **Someone without a password removing theirs.** It's how they sign in.
- **Someone with neither** a password nor a PIN, such as "Kids." Only
  an Admin gives them one.
- **A sign-in made by picking someone** without a PIN (from 1.28.1).
- **A browser's sign-in,** since this is for the apps.

Wrong PINs tried recently still count after a new one is chosen: 5
within 15 minutes still means a wait.

## POST /api/internal/password

From 1.28.0, the person signed in changes their own password, as on
StationPlay's page, with the app's token. Send their current password and
the new one:

```json
{"current": "...", "new": "..."}
```

A new password has at least 8 characters (and at most 200). As on
StationPlay's page, every other sign-in of theirs ends (other apps,
browsers and pickers). The app's own token ends too. The app carries on
with `token`, which it keeps in place of the old one. The access log shows
"Sam changed their password in StationPlay for Android on Sam's phone."

| Field | Type | What it is |
|---|---|---|
| `token` | string | The app's new token: send it from now on |

Answers 400, with the sentence to show, when the current password is wrong
or the new one isn't allowed. Answers 429 after 5 wrong ones from one
address within 15 minutes, as signing in does. Answers 403, with the
sentence to show:

- **Changing it is turned off.** An Admin has turned off changing their own
  password for them. `canChangePassword` in `GET /api/internal/me` shows
  this beforehand. An Admin can always change their own.
- **No password.** For someone without a password (a PIN-only person,
  or "Kids"), an Admin gives them one.
- **A browser's sign-in.**

Answers 400 while signing in is off.

## POST /api/internal/sign-out

Ends the token it's sent with. Answers `{"ok": true}`.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## GET /api/internal/speed-test

A connection test: data for the app to time. It shows the Admin how fast
StationPlay reaches devices (at home, and away from home, where it's the
home internet's upload) and how many can watch at once. `?mb=` is how many
megabytes to send (1 to 64; 20 if it isn't given). The data is random, so
nothing along the way can compress it, and it has a `Content-Length`.

An app times it from a moment after the data starts, so the connection's
startup isn't counted. It may stop reading after about 8 seconds on a slow
connection. Each address can run one test at a time: another within 10
seconds gets 429.

## POST /api/internal/speed-test

What the app found: `{"mbps": 48.2, "app": "...", "deviceName": "..."}`
(`app` and `deviceName` as for signing in). StationPlay keeps it for the
**Access** tab, with where it ran as StationPlay sees it. It recommends
limits from the fastest recent tests.

| Field | Type | What it is |
|---|---|---|
| `mbps` | number | The speed kept, in megabits a second |
| `where` | string | `home`, or `away` (through the public port) |
| `eachMbps` | number | What one device watching takes, at the biggest picture the stations use |
| `room` | number | How many devices a connection this fast has room for at once |

## GET /api/internal/reach

Not for the apps. StationPlay asks this of itself, at the address set for
watching away from home, to check that apps can reach it from outside. The
result shows on the **Access** tab and in the page's header. It's open on
both ports, to anyone, over plain HTTP too, and before there's a user.
`?n=` is a random value a check is waiting for (for a minute at most). For
any other value, it answers 404 and nothing more.

| Field | Type | What it is |
|---|---|---|
| `stationplay` | boolean | Always true |
| `port` | string | The port the request came in on: `home`, or `public` |
| `https` | boolean | Whether the request came over HTTPS, as the reverse proxy in front reports (`X-Forwarded-Proto`) |

## POST /api/internal/report

From 1.22.1, when `features` lists `reports`: a problem report, for
whoever is looking into a problem. It shows what the app did recently, and
on what device. It goes in StationPlay's log, and so on the **Logs** tab, as
a warning that starts "Report from" and the app's name (with who's signed
in). Send:

```json
{"text": "...", "app": "StationPlay for Android TV", "deviceName": "Den"}
```

`text` is lines of plain text: the app's and device's details, then what it
did recently, oldest first, with any crash. Never include a token or a
password. StationPlay keeps at most 400 lines or 24,000 characters of it,
and notes how many it left out. Each address can send one report every 30
seconds, and another gets 429. An empty one gets 400.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## POST /api/internal/problem

From 1.23.0, when `features` lists `problems`: a problem the app ran into,
sent by the app itself as it happens. It's kept for the **Logs** tab. There,
an Admin sees each problem with how often it happened, on how many devices
and on what kinds of device. So they can tell whether it affects one
device, one kind of device or everyone. Send what's known:

```json
{"kind": "station-stopped", "station": 5, "detail": "The picture stopped...",
 "app": "StationPlay for Roku", "version": "0.5.0",
 "device": "Roku Ultra 4850X, Roku OS 14.0", "deviceName": "Den",
 "at": 1791580000000, "journal": "Tuned to station 5\nThe picture stopped at 0:42"}
```

`kind` says when the app sends it:

- `station-failed`: a station didn't start (with `station`). Not when every
  tuner is in use or a limit was reached, since the person is told about
  those.
- `station-stopped`: a station stopped playing, and tuning in again didn't
  bring it back (`station`).
- `library-failed`: something from the library didn't play (`title`, as
  it's shown).
- `library-stopped`: playing from the library stopped and couldn't continue
  (`title`). With either of these two, from 1.30.0, send `session` (the
  playing's ID, from `POST /api/internal/play`) and `positionMs` (where in
  the program it happened). StationPlay checks that file at that point
  first, ahead of everything else it checks except a station's program
  about to air. It puts the file on the **Broken files** list only if it
  finds what's wrong. Without `session`, it checks what that device played
  last, where the app last reported it was, if the problem happened in the
  last 10 minutes (by `at`).
- `kept-up`: playing couldn't keep up, so a smaller version played
  (`title`, or `station`).
- `crashed`: the app closed unexpectedly last time (sent when it opens
  again; `detail` is the crash's first line).
- `unreachable` (from 1.29.1): the app couldn't reach StationPlay for a
  minute or more, sent once it's back. `detail` says what kind of trouble.
  It starts with one of "No network on this device", "StationPlay's address
  couldn't be found", "StationPlay didn't answer", "A secure connection
  couldn't be made" or "StationPlay answered with an error (503)". Then come
  the device's kind of network (Wi-Fi, mobile data, Ethernet; never its
  name or address) and how long it lasted. `lastedMs` says how long, in
  milliseconds. (Without it, StationPlay reads "for 3 min 20 s" or "for 1
  hr 5 min" from `detail`.) `at` is when it began. The **Logs** tab shows it
  as "Den couldn't reach StationPlay for 12 minutes · No network on this
  device."

`detail` is what the app saw, in a sentence (StationPlay keeps at most 300
characters). For a player's error, put its code first, as the player names
it: `ERROR_CODE_DECODING_FAILED` from Media3; `AVFoundationErrorDomain -11821`
or `NSURLErrorDomain -1009` from Apple's players, as "<domain> <code>";
`Roku error -5` from Roku's. Then add the rest of its message. The **Logs** tab
explains the codes it knows in plain words. `device` is the kind of device,
its model and its system, as a problem report's `Device:` line has it.
Never include a token, a password or a stream's private address.

From 1.29.1, also send:

- `at`: when it happened (milliseconds since 1970). An app keeps the
  problems it couldn't send (while StationPlay is out of reach, say) and
  sends them once it's back, oldest first. One from up to 7 days ago, or up
  to 5 minutes ahead (a device's clock a little off), is kept as happening
  then. Otherwise, it's kept as happening when it arrived. The **Logs** tab
  orders problems by when each happened.
- `journal`: the app's last lines before it, as a problem report has them,
  joined with `\n` (never a token, a password or a stream's private
  address). StationPlay keeps its newest lines, within 8 KB (8,192 bytes in
  UTF-8), for the **Logs** tab's **What led up to it**. A longer one is cut,
  leaving out its oldest lines.

The same problem from the same app and device within 10 minutes of the
first counts toward the first, and is written to StationPlay's log once.
Each app on each device can send at most 30 in 10 minutes, and more get 429
(keep them, and send them later). The 5,000 that happened most recently are
kept, so a backlog of old ones never pushes out newer ones. A `kind`
StationPlay doesn't know gets 400.

| Field | Type | What it is |
|---|---|---|
| `ok` | boolean | Always true |

## Reporting a problem

From 1.30.0, a person can report a problem with what they're watching. They
can report from a movie's or an episode's page, from the player's menu, and
from a station's player (about what's on it now). They pick the problem
from a list and never type it. The list comes from
`GET /api/internal/report-choices`, so it can change without an app update.
Show the choices under their `group` headings, in order, and send the one
picked with `POST /api/internal/report-problem`. Show the answer's `detail`
unchanged, and a refusal's `detail` unchanged too (the limits, or reporting
turned off).

StationPlay knows who sent a report, and on what device, from the app's
sign-in. What it does depends on the problem:

- **What StationPlay can check.** No picture, the picture breaking up, no
  sound, the sound cutting out, stopping early or not playing. StationPlay
  checks the file at once, around where the problem happened first.
- **What a machine can't judge.** This waits for an Admin on the **Broken
  files** tab.

A report alone never takes anything off the air, or out of Media. Offer
Report a problem only when `user.canReport` is true in
`GET /api/internal/me`. (An Admin can turn it off for someone, on the
**Access** tab.)

## GET /api/internal/report-choices

From 1.30.0: what a person can report, in order. Anyone signed in may ask
(or, while signing in is off, anyone at home).

| Field | Type | What it is |
|---|---|---|
| `choices` | list | The choices, in the order to show them |
| `choices[].id` | string | What to send as `choice` |
| `choices[].group` | string | The heading it's under: "Picture", "Sound", "Subtitles", "The program" or "Details" |
| `choices[].label` | string | What to show, such as "No sound" |

## POST /api/internal/report-problem

From 1.30.0: a person's report. For an episode or a movie (from its page,
or the player's menu), send its key:

```json
{"choice": "no-sound", "key": "1234", "positionMs": 754000,
 "method": "direct", "version": "5678", "audio": "1235", "subtitle": null}
```

For what's on a station now (from the station's player), send its number
instead. StationPlay knows the program, and where in it the station is.

```json
{"choice": "picture-breaks", "station": 5}
```

`choice` is a choice's `id`. Also send what the app knows: `positionMs`
(where in the program, if it's playing or was), and how it was playing.
That's `method` (as the play answer had it: `direct`, `repackage` or
`convert`), `version` (the version playing), and `audio` and `subtitle`
(the tracks' IDs; null for none). Leave out what you don't know. Without a
`version`, StationPlay uses what that device played of it recently, or else
its best version.

The answer is `{"detail": "Thanks. An Admin will take a look."}`: show it.
Each refusal has a `detail` to show unchanged:

- **400:** a `choice` that isn't one, both a key and a station or neither,
  or a show rather than an episode or a movie.
- **403:** "An Admin has turned off reporting problems for you."
- **404:** it isn't shared, this person can't see it, or there's no such
  station, or nothing on it.
- **429:** one report a day per person for each program ("You've reported
  this one today. Thanks."), and 10 a day per person ("That's all the
  reports for today. Thanks for your help.").

| Field | Type | What it is |
|---|---|---|
| `detail` | string | What to show: "Thanks. An Admin will take a look." |

## Admin alerts

From 1.29.0, StationPlay raises an alert for each problem an Admin can act
on, once when it starts and again when it's fixed:

- Plex can't be reached (or won't accept StationPlay's token).
- The data folder is nearly full or can't be written to.
- A station keeps failing to start.
- Backups are failing.
- The clock is badly off (by Plex's).
- The apps can't reach StationPlay from outside (the outside check).

An alert is raised only once the problem has lasted for some time, such as
3 checks in a row a minute apart, or a station failing to start 3 times in
10 minutes. It's marked fixed only once things have been right for some
time too, so no alert comes and goes. The **Logs** tab and the page's header
show alerts too, and an Admin can have them sent to a web address (ntfy,
Gotify, Home Assistant).

From 1.30.0, there's one more kind, `files`: something on the **Broken
files** tab needs an Admin. That's a person's report, a file a station or
Media plays that StationPlay found broken or damaged and that isn't being
replaced automatically, or one Sonarr or Radarr couldn't replace. For
example: "There are 3 files to look at on the Broken files tab: Tia
reported No sound on Northbound S2 E4." The alert shows how many, and the
newest, as more come. It's fixed when nothing there needs an Admin.

An Admin is told about files at most once an hour. Once an hour has passed
since the alert was last raised, anything new since then restarts it with a
new `id`, and the old one is no longer listed. (It isn't fixed, so don't
say it was.) The apps need nothing new for it: notify once for each `id`,
as for any alert. The web address gets the same alerts.

For an Admin, an app shows the current alerts, with each `sentence`
unchanged and how long it's lasted, and can show when one is fixed. Ask
`GET /api/internal/alerts` when the app opens and comes back to the front,
and every few minutes while it's open. On Android, also ask every 15
minutes in the background (WorkManager), notifying once for each new `id`,
and once when it's fixed.

From 1.31.0, StationPlay keeps its alerts across a restart:

- **One still going** keeps its `id`. It isn't new, so don't notify again.
- **One fixed while StationPlay was stopped** is listed as fixed, with its
  `id`, once its check finds it.
- **Those fixed in the last 24 hours** stay listed.

The apps need nothing new for it. Before 1.31.0 (and from 1.31.0, once a
backup is restored), the list starts fresh after a restart, and anything
still wrong starts again with a new `id`.

## GET /api/internal/alerts

For Admins only (from 1.29.0; while signing in is off, anyone at home).
Anyone else gets 403. Lists the current alerts, and those fixed in the last
24 hours. It's small and quick, to ask every few minutes.

| Field | Type | What it is |
|---|---|---|
| `alerts` | list | The alerts now, the newest first; then those fixed in the last 24 hours, the most recently fixed first |
| `alerts[].id` | string | Its ID: the same for as long as it lasts (one that starts again later has a new one) |
| `alerts[].kind` | string | What it's about: `plex`, `data-full`, `data-write`, `station`, `backups`, `clock`, `outside` or `files` (from 1.30.0; kinds may be added: show the sentence) |
| `alerts[].sentence` | string | What's wrong, in a sentence an Admin can act on, to show unchanged |
| `alerts[].since` | number | When it started |
| `alerts[].fixed` | number or null | When it was fixed; null while it lasts |

## Your library

When an Admin shares libraries with the apps (on the **Access** tab, under
**Media in StationPlay's apps**), the apps can browse them and play their
shows and movies whenever the viewer likes. Until then, `features` doesn't
list `library`, and these addresses answer 404 ("No libraries are shared
with StationPlay's apps").

- **At home.** These addresses answer on the home network, or through a
  VPN, which looks like home.
- **Away from home, when it's on.** From 1.27.0, they answer through the
  public port too, while watching away from home is on (`features` lists
  `away`). There, a signed-in app can do whatever it may at home, and
  `features` lists `library` there too.
- **Away from home, when it's off.** Through the public port, these
  addresses answer 403, and `features` doesn't list `library` there.

To know which applies, ask `GET /api/v1/server` again where the app is (at
home, or away).

Anything that isn't in a shared library answers 404, the same as something
that doesn't exist (and so does anything Plex says isn't there). Every one
of these answers within 8 seconds, however slow Plex is. When Plex is slow,
unreachable, or sends something StationPlay can't read, they answer 503
with "StationPlay can't reach Plex right now. Try again in a moment." (never
a 500). What StationPlay was fetching carries on meanwhile, so asking again
a little later often finds it ready.

From 1.29.1, nothing the apps receive names a file or a folder: not a play
answer, details, versions, tracks, alerts or refusals. A track whose title
in the file is a file's name ("Northbound.S02E04.1080p.mkv") is listed
without it. A program's own address ends in a plain name (`file.mkv`,
`index.m3u8`).

Keys are strings, and the same key always means the same show, movie or
episode. Pictures (`poster`, `backdrop`, `thumb`) are addresses under
`/api/internal/art`. Add `&w=` with the width it will be shown at, in
pixels, and send the app's token with them.

StationPlay keeps each person's own place in what they watch: the Resume
row, where to resume and what they've watched. While signing in is off,
everyone shares one.

## Languages

From 1.29.0, each person has their own languages. StationPlay keeps them,
so they follow the person to every device. (While signing in is off,
everyone shares one set.)

- **Their own** (`languages` in `GET /api/internal/me`; set with
  `PUT /api/internal/languages`). The sound's language (null: each file's
  default track), subtitles on or off, and the subtitles' language (null:
  the language of the sound that plays).
- **For a show, or for an episode or a movie alone** (`languages` in
  `GET /api/internal/items/{key}`; set from the player with
  `PUT /api/internal/items/{key}/languages`, cleared with `DELETE`). Any of
  the three, each null where nothing is chosen there. A show's choice
  applies to all its episodes. An episode's applies to it alone.

Languages are ISO 639-2 codes, as files carry them (`eng`, `jpn`). For the
few with two codes, it's the one files use (`fre`, `ger`). Each comes with
a name to show ("English," "Japanese"). StationPlay knows the languages in
`choices` (in `GET /api/internal/me`). It also accepts two-letter codes
(`en`, `pt-BR`) and the other three-letter ones (`fra`, `deu`) for them.
Any other code is refused with 400 and a sentence to show.

When an app plays an episode or a movie (`POST /api/internal/play`) without
sending `audio` or `subtitle`, StationPlay chooses for whoever is signed
in. It takes each of the three from the most specific place it's chosen:
the episode's (or movie's), else its show's, else the person's own, else
the file's default.

- **Sound.** The first track in that language (the file's default among
  them first), never a commentary when there's another. With none in that
  language, the file's default.
- **Subtitles on.** A subtitle track in the subtitles' language, a full one
  before a forced one. (One for the deaf and hard of hearing counts as a
  full one.)
- **Subtitles off.** Only a forced track in the language of the sound that
  plays. (Forced subtitles cover the parts in another language, meant to
  be read.)

The answer's `chosen` shows what StationPlay chose, and why, in a few words
to show ("Japanese, as chosen for this show"), and that's what plays. The
app selects `chosen.audio` and `chosen.subtitle` in its player. A subtitle
the player can't show itself is drawn into a copy's picture, as an app's
`subtitle` is, by the same rules. That's one whose format isn't in
`device.subtitles`, or, in a copy, one inside the file, since a copy holds
none.

An app that sends `audio` or `subtitle` (either, even null) gets exactly
that, as before, and `chosen` is null. So does someone who has chosen
nothing anywhere: their programs play as they did before 1.29.0. Stations
don't use these languages yet.

## Up next and the Resume row

StationPlay decides what's next in a show, the same for every app (a show's
`next`, and the Resume row). It works from this person's progress in the
show's episodes, newest first. Marking an episode not watched from a menu
says nothing about where they are, so those marks are passed over.

1. **An episode they're partway through**, or barely started (a special
   too): that one, where they stopped (from the start, if it was under a
   minute).
2. **After an episode they finished** (or marked watched): the first one
   after it that they haven't watched, in order across seasons (specials
   aside, and past any in the same file as it). With none, they've finished
   the show. Nothing is next (`next` is null, and it isn't on the Resume
   row), even if they skipped one before it.
3. **A special they finished** is passed over: they're where they were
   before it.
4. **Nothing yet:** the first episode (specials aside, unless the show has
   only specials). A show they haven't started isn't on the Resume row.

The Resume row has the movies they're partway through (a minute or more
in), and each show's Up next by rule 1 or 2. It's newest first, one per
show, up to 20. Only StationPlay keeps track of where they are (see
`POST /api/internal/progress`). What they watch in Plex's own players
doesn't count.

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
isn't given) and `?size=` (1 to 200; 50 if it isn't given). Sorted by
`?sort=`:

- `title` (the default): by the library's sort title (or the title without
  a leading "The," "A" or "An"), from its first letter or digit. Case and
  accents are ignored ("Élan" with the Es), and numbers sort as numbers
  ("Saw 2" before "Saw 10"). Titles starting with a digit, or anything but
  A to Z (another alphabet, say), come first.
- `added`: newest first.
- `released`: newest first, with those without a date last.

Titles that sort alike (two movies called "Hamlet," or added at the same
moment) are always in the same order, so a page never repeats or skips one.
From 1.24.0, a list can be narrowed by `?genre=` (one of its `genres`) and
`?unwatched=1` (only movies this person hasn't watched, and shows with
episodes they haven't watched). A genre the library has none of leaves
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
| `letters` | list | Sorted by `title`: where each letter starts in the whole list, as narrowed, for jumping to it: each letter once, in order, `#` first (`[]` for the other sorts; from 1.24.0). How many a letter has is where the next starts (or `total`), less its own `start` |
| `letters[].letter` | string | `A` to `Z`, or `#` for titles starting with a digit or anything else |
| `letters[].start` | number | Where its first show or movie is (a `start` to ask for) |

## GET /api/internal/home

What the app's home screen shows.

| Field | Type | What it is |
|---|---|---|
| `continue` | list | The Resume row: the movies this person is partway through, and each show's Up next (see Up next and the Resume row), newest first, one per show (up to 20) |
| `continue[]` | card | An episode or movie; `positionMs` is where to start it |
| `added` | list | Each shared library's recently added shows or movies (libraries with none are left out) |
| `added[].library` | string | The library's key |
| `added[].title` | string | Its name |
| `added[].items` | list | Its newest movies, or the shows with the newest episodes (up to 20) |
| `added[].items[]` | card | One show or movie |

## GET /api/internal/search

Search is the only place the library and the stations meet. It finds shows
and movies whose titles contain `?q=`, across the shared libraries, and the
stations airing a show or movie with it in its title right now. It answers
wherever the stations do, with `items` empty where the library isn't
offered.

- **Length.** `q` is 1 to 100 characters. A single letter is fine, for
  searching as the viewer types. An empty or longer `q` is refused (400,
  with the sentence to show).
- **Matching.** Case, accents and punctuation are ignored: "amelie" finds
  "Amélie," and "spider man" and "spiderman" find "Spider-Man." A title is
  found by its sort title too ("matrix" finds "The Matrix" as a title
  that's just that).
- **Order.** It answers up to 50, the best first: a title that's just what
  was typed, then titles starting with it, then titles with a word starting
  with it, then the rest. Each group is in title order (as `sort=title`
  lists them).

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
| `tagline` | string or null | Its tagline, the line on its poster (from 1.24.0) |
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
| `next` | card or null | (A show) the episode to play next (see Up next and the Resume row): the one this person is partway through, or the first after the last they finished that they haven't watched, or the first; null once they've finished the show |
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
| `audio[].languageCode` | string or null | Its language's code, such as `jpn` (from 1.29.0): what to save when the viewer chooses it (see Languages); null if it isn't known |
| `audio[].codec` | string | Its format, such as `aac`, `ac3`, `eac3`, `dts`, `truehd` |
| `audio[].default` | boolean | Whether the file says to play it unless asked otherwise |
| `audio[].index` | number or null | Its place among all the file's tracks (0 is the first) |
| `subtitles` | list | (An episode or movie) its subtitle tracks |
| `subtitles[].id` | string | The track's ID |
| `subtitles[].name` | string | How to list it, such as "Spanish · Forced" |
| `subtitles[].language` | string or null | Its language |
| `subtitles[].languageCode` | string or null | Its language's code (from 1.29.0), as `audio[].languageCode` |
| `subtitles[].codec` | string | Its format: `srt`, `ass`, `vtt` and `mov_text` are text; `pgs` and `vobsub` are pictures |
| `subtitles[].default` | boolean | Whether the file says to show it unless asked otherwise |
| `subtitles[].forced` | boolean | Whether it's only the parts in another language |
| `subtitles[].external` | boolean | Whether it's a file of its own next to the video, rather than inside it |
| `subtitles[].index` | number or null | Its place among all the file's tracks (null for a file of its own) |
| `versions` | list | (An episode or movie) its versions, the best first: the biggest picture, HDR before non-HDR, then the most detail. One for most; more where the library has the same title as 4K and 1080p files, say |
| `versions[].id` | string | The version's ID, to play it (`version` in `POST /api/internal/play`) |
| `versions[].name` | string | How to list it, such as "4K · HDR10" or "1080p" (with its format, or its Mbps, where two would read the same) |
| `versions[].size` | string or null | As `picture.size` |
| `versions[].hdr` | string or null | As `picture.hdr` |
| `versions[].bitrateKbps` | number or null | What it needs, in kilobits a second |
| `versions[].problem` | string or null | What StationPlay found wrong with this version's file (from 1.30.0), so the app can offer another: `broken` (it can't play; another version plays in its place, if there's one StationPlay didn't find broken) or `damaged` (it plays, but its picture or sound breaks up in places); null when it found nothing |
| `languages` | object | What this person chose for it (from 1.29.0: see Languages), for the player's Audio & subtitles |
| `languages.item` | object or null | For this show (the whole show), or this episode or movie alone; null: nothing |
| `languages.item.audio` | object or null | The sound's language; null: not chosen here |
| `languages.item.audio.code` | string | Its code, such as `jpn` |
| `languages.item.audio.name` | string | Its name, such as "Japanese" |
| `languages.item.captions` | boolean or null | Subtitles on or off; null: not chosen here |
| `languages.item.captionLanguage` | object or null | The subtitles' language; null: not chosen here |
| `languages.item.captionLanguage.code` | string | Its code |
| `languages.item.captionLanguage.name` | string | Its name |
| `languages.show` | object or null | (An episode) for its whole show; null: nothing (or not an episode) |
| `languages.show.audio` | object or null | As `languages.item.audio` |
| `languages.show.audio.code` | string | Its code |
| `languages.show.audio.name` | string | Its name |
| `languages.show.captions` | boolean or null | As `languages.item.captions` |
| `languages.show.captionLanguage` | object or null | As `languages.item.captionLanguage` |
| `languages.show.captionLanguage.code` | string | Its code |
| `languages.show.captionLanguage.name` | string | Its name |

Its `picture`, `audio` and `subtitles` are its best version's.

## GET /api/internal/items/{key}/related

From 1.24.0: up to 12 other shows or movies like this one, from its own
library (an episode's are its show's), for More like this. Those sharing
the most of its genres come first, then the nearest in years. Empty when it
has no genres.

| Field | Type | What it is |
|---|---|---|
| `items` | list | Others like it |
| `items[]` | card | One show or movie |

## GET /api/internal/items/{key}/episodes

A show's episodes, in order: seasons in order, specials last, and episodes
without a season or a number after those with one (those alike always in
the same order). It lists all of them, or one season's with `?season=`.
From 1.30.0, it answers a page at a time, with `?start=` (0 if it isn't
given) and `?size=` (1 to 500; 500 if it isn't given). Ask for the next
page while `start` plus the episodes you have is less than `total`.

| Field | Type | What it is |
|---|---|---|
| `show` | string | The show's key |
| `season` | number or null | The season asked for (null: all of them) |
| `total` | number | How many episodes there are in all, of the season asked for (from 1.30.0) |
| `start` | number | Where this page starts (from 1.30.0) |
| `episodes` | list | Its episodes: this page |
| `episodes[]` | card | One episode |

## PUT /api/internal/items/{key}/languages

From 1.29.0, from the player's Audio & subtitles: sets languages for
whoever is signed in (see Languages). Send a show's key for the whole show,
or an episode's or a movie's key for it alone. Send what changes, each
optional:

```json
{"audio": "jpn", "captions": false, "captionLanguage": null}
```

Each language is a code, or null to clear that one (then the show's choice,
or the person's own, applies). `captions` is true, false or null. What
isn't sent stays unchanged. Answers 400, with the sentence to show, for a
language StationPlay doesn't know, or a key that isn't a show, an episode
or a movie (a season, say). Answers 404 for what isn't shared or can't be
seen, as its details do.

| Field | Type | What it is |
|---|---|---|
| `item` | object or null | What's chosen for it now, as `languages.item` in its details |
| `item.audio` | object or null | The sound's language; null: not chosen here |
| `item.audio.code` | string | Its code |
| `item.audio.name` | string | Its name |
| `item.captions` | boolean or null | Subtitles on or off; null: not chosen here |
| `item.captionLanguage` | object or null | The subtitles' language; null: not chosen here |
| `item.captionLanguage.code` | string | Its code |
| `item.captionLanguage.name` | string | Its name |
| `show` | object or null | (An episode) what's chosen for its whole show, as `languages.show` |
| `show.audio` | object or null | As `item.audio` |
| `show.audio.code` | string | Its code |
| `show.audio.name` | string | Its name |
| `show.captions` | boolean or null | As `item.captions` |
| `show.captionLanguage` | object or null | As `item.captionLanguage` |
| `show.captionLanguage.code` | string | Its code |
| `show.captionLanguage.name` | string | Its name |

## DELETE /api/internal/items/{key}/languages

From 1.29.0, clears all three for a show, an episode or a movie, for
whoever is signed in. Their show's choice, or their own, then applies
again. Answers as `PUT` does, with `item` null.

| Field | Type | What it is |
|---|---|---|
| `item` | object or null | Null: nothing is chosen for it now |
| `show` | object or null | (An episode) what's chosen for its whole show, as in `PUT` |
| `show.audio` | object or null | As in `PUT` |
| `show.audio.code` | string | Its code |
| `show.audio.name` | string | Its name |
| `show.captions` | boolean or null | As in `PUT` |
| `show.captionLanguage` | object or null | As in `PUT` |
| `show.captionLanguage.code` | string | Its code |
| `show.captionLanguage.name` | string | Its name |

## GET /api/internal/art/{key}

A picture, as JPEG or PNG (or WebP or GIF, as Plex has it):

- **Kind.** `?kind=poster` (the default; 2:3, and an episode's is its
  show's), `backdrop` (16:9) or `thumb` (an episode's still, 16:9).
- **Width.** `?w=` is the width in pixels (1 to 10000; 320 if it isn't given). It's
  rounded up to 160, 320, 480, 720, 1280 or 1920, with the largest for
  anything wider.

It answers 404 if there's no such picture, or what Plex has isn't one, and
answers at once when the library says there's none. It answers 503 when
Plex doesn't send it in time, as for the rest of the library.

Each comes with `Cache-Control: private, max-age=86400` and an `ETag`. Keep
it a day. After that, ask again with `If-None-Match` and its ETag. While
it's the same, the answer is 304, with nothing in it. A picture's address
stays the same for as long as it's the same show, movie or episode, so apps
cache by it.

## POST /api/internal/play

Starts playing an episode or movie. Send its key and what the device can
play, as the device itself reports it (never a guess). Optionally send
`app` and `deviceName` (as for signing in, for the log):

```json
{"key": "1234",
 "device": {"containers": ["mkv", "mp4", "mov", "ts", "webm"],
            "video": [{"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8},
                      {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10}],
            "hdr": ["hdr10", "hlg"],
            "audio": ["aac", "ac3", "eac3", "mp3", "opus", "flac"],
            "subtitles": ["srt", "ass", "vtt", "pgs"]},
 "app": "StationPlay for Android TV", "deviceName": "Den"}
```

`hdr` lists only what the screen shows (`hdr10`, `hlg`, `dv` for Dolby
Vision), or `[]` for a screen without HDR. From 1.29.0, `subtitles` lists
the subtitle formats its player shows itself (`srt`, `ass`, `vtt`,
`mov_text`, `pgs`, `vobsub`), in a file it plays directly or alongside a
copy. A subtitle chosen for the person in another format is drawn in (see
Languages). Without the list, every subtitle chosen for them is drawn in.

Add `"version"` (a version's `id` from its details) to play that version.
Without it, the best version the device can play directly plays, unless the
app sends `"maxKbps"`. That's how much its connection to StationPlay
carries, as it measured recently (with `/api/internal/speed-test`). Then the
best version that connection keeps up with plays (one that needs no more
than two-thirds of it, on average). With none, the smallest the device can
play plays.

A file plays directly when the device can play its file type, its
picture's format at its size and bit depth, and its HDR. (Dolby Vision
profile 5 needs `dv`. Other profiles also play as the HDR10, HLG or
ordinary picture beneath.) The device must also play the sound of its
default track, or of `audio` if it's sent, or else of the one chosen for
the person (see Languages).

When it can't, StationPlay 1.24.0 and later makes a copy it can play
(`features` lists `convert`), for an app that says it takes one.
`device.hls` lists what its player takes in an HLS playlist: `ts` (MPEG-TS
pieces with H.264), `ts-hevc` (MPEG-TS pieces with HEVC) and `fmp4`
(fragmented MP4 pieces; not made yet).

- **Repackaged** (`repackage`): the picture unchanged, and its sound
  converted where the device needs it. This happens when the device plays
  the picture and the copy's pieces can carry it.
- **Converted** (`convert`): otherwise. The picture is made H.264, at most
  1080p, and ordinary rather than HDR.

With `device.hls`, a copy is also made when the app sends:

- `subtitle`: the ID of a subtitle track to draw into the picture. This is
  for a track the player can't show itself: picture subtitles on a player
  without them, and any track inside the file while a copy plays. The copy
  is converted.
- `fit: true` with `maxKbps`: a smaller picture made to fit the connection,
  when no version keeps up. The copy is converted.
- `night: true`: night mode's sound (as the stations' `nightHls`), for an
  app that can't make it itself.
- `convert: true` (from 1.29.1, when `features` lists `convert-asked`): a
  converted copy, whatever `device` says it plays. This is for when the
  device's decoder failed at the file (Media3's
  `ERROR_CODE_DECODING_FAILED`, say), so asking for the same again would
  only fail again.
  - The picture is made H.264 at 8 bits, at most 1080p (within 1920×1080,
    or the device's own H.264 size if that's smaller), and ordinary rather
    than HDR.
  - The sound is AAC: 5.1 where the file's has more than two channels and
    `device.audio` lists a surround format (`ac3`, `eac3`, `dts` or
    `truehd`), otherwise stereo.
  - Everything else asked for still applies: `startMs`, `version`, `audio`,
    `subtitle`, `night`, `fit` with `maxKbps`, and the cap away from home.
  - Its `why` starts with "a converted copy, as the app asked". It counts
    against the copies converted at once, as any converted copy does.
  - Send the problem the app ran into first (`POST /api/internal/problem`,
    kind `library-failed` or `library-stopped`, with the player's error in
    `detail`). StationPlay's log then shows that the app asked for the copy
    after that.
  - Without `device.hls` (`ts`), the answer is 422 with `detail`. A file
    that can't be converted (a Dolby Vision profile 5 picture, say) gets
    422 with `detail` and `why`, as below.

From 1.27.0, while `features` lists `even-sound` (an Admin's switch, on by
default), every episode (never a movie) plays at the stations' loudness, so
a show's episodes match. With `device.hls`:

- An episode the device plays directly comes as a `repackage` copy. Its
  picture is unchanged, and only its sound is remade. The sound is what the
  device would get anyway, but not copied, so sound sent unchanged to a
  receiver comes as 5.1 or stereo. Its `why` is
  `["even sound for the show's episodes"]`.
- Any other copy of an episode has even sound too, and says so in its
  `why`.
- Where the picture can't be kept unchanged, the episode plays directly
  (`direct`).

Show the copy's `why` in the player's info. Without `device.hls`, an
episode plays as it did before.

Send `startMs` too: where the player will start (by default, where this
person stopped). A copy's playlist says to start there, and StationPlay
starts making it there. `audio` (a sound track's ID) plays that track. A
copy holds only that one, so another track means another copy. Ask again
with it and `startMs` where the viewer is, and `POST` the old one's
`leave`.

If the device can't play the file directly and no copy can be made, the
answer is 422, with `detail` (a sentence to show) and `why` (a list of the
reasons). That happens when the app didn't send `device.hls`, or nothing it
takes would show the file correctly. StationPlay converts at most 3 copies
at once, or 6 on a GPU (repackaging costs next to nothing). One more gets
503 with `detail`. (A device's own copy, which a new one takes over from,
isn't counted.)

From 1.30.0, a version StationPlay found broken never plays
(`versions[].problem` is `broken`: its checks found it can't play). Another
version plays instead, if there's one StationPlay didn't find broken
(whichever would play otherwise, as above). `why` says so ("another
version, as 4K can't play right now"), whether it plays directly or as a
copy. With none, the answer is 422, with the `detail` "This one can't play
right now. An Admin has been told." (and `why`). A damaged version plays,
as before. Trouble playing a version isn't a verdict on its own. That's a
copy that can't be made, or a problem the app sends (see
`POST /api/internal/problem`). StationPlay checks the file at that point,
and only what it finds puts the file on the list.

Every refusal has `detail`, a sentence to show unchanged:

- **400:** an episode or a movie wasn't chosen, or the request wasn't
  understood.
- **404:** it isn't shared, can't be seen, or has no file.
- **422:** as above, or every version of it was found broken.
- **503:** Plex can't be reached, the file can't be read right now, a copy
  can't be started, too many are being converted, or one more device than
  the limits allow (with `limit` and `most`).

From 1.30.0, a device plays one program at a time. Asking for another, or
for the same one again (another sound track, a smaller version), ends the
one it was playing, and the copy being made for it, if any. Its addresses
answer 404 from then on. So ask for the next episode when it's time to play
it, not while another plays. A device is an app's sign-in (each app signs
in on its own), or, while signing in is off, its address.

From 1.31.0, a movie Plex has in several files (stacked: "Part 1" and "Part
2") plays as one program. (Before, its first file played.) Its `durationMs`
is the whole, it counts as watched at 90% of the whole, and resume,
progress, seeking and Up next use the whole, as for any program.

- **With `device.hls`,** it plays as a copy that joins its files, from
  `startMs` as usual. The copy is `repackage` (its picture unchanged) when
  every file's picture is the same and the device plays it, and `convert`
  otherwise. Its `why` starts with "its 2 files, played as one". The app
  needs nothing new: play it as any copy. Subtitles are drawn into the
  picture rather than listed with a `url`, since a separate subtitle file
  matches only one of the files.
- **Without `device.hls`,** it gets 422, with `why` ["it's in 2 files"] and
  `detail`, unless another version (in one file) plays directly.

Nothing names its files.

An Admin's limits on devices watching count programs played this way too
(see Playing a station in `docs/api.md`). Through the public port, the
limit on devices away from home applies as well. One more device gets 503
with `limit` and `most`.

From 1.27.0, away from home (through the public port), a program plays at
the quality an Admin chose for Media away from home: as it would at home,
or up to a number of Mbps. With a cap, the best version within it plays
(directly, or as a copy, as at home). With none within it, a copy is
converted down to fit, and `why` says so: "a smaller copy, within the 10
Mbps allowed away from home". Any copy converted there stays within the
cap. An app that doesn't send `device.hls` gets 422 for a program over the
cap, with `detail` and `why`. `maxKbps` and `fit` work on top of the cap,
as at home.

Skip intro and Skip credits are for episodes only. Show Skip intro while
the player is inside `markers.intro`, and Skip credits inside
`markers.credits`, again whenever the viewer goes back into them. Pressing
one moves to the end of that part, or with `creditsToEnd`, on to the next
episode. Offer the buttons, and skip without asking only where the viewer
has turned that on. Movies have no markers, since where a movie's credits
start is too often uncertain.

When playing keeps stopping to load, let the player's buffer deal with it
first. Only trouble that lasts counts. In the Android app, nothing in the
first 45 seconds counts but one 20-second stall. After that, it counts 4
stalls of a second or more within 3 minutes, 20 seconds of them in all, or
frames not drawn in time through most of a minute. Then short tests find
where the trouble is: a connection test (`/api/internal/speed-test`)
against `bitrateKbps`, and how fast the file itself has been arriving. If a
smaller version is `playable`, do as `whenSlow` says, from where the viewer
is. But switch automatically only when the tests showed where the trouble
is, and otherwise offer it. With none, say so plainly.

| Field | Type | What it is |
|---|---|---|
| `session` | string | This playing's ID (for progress reports) |
| `method` | string | How it plays: `direct` (the file unchanged), `repackage` or `convert` (a copy; from 1.24.0) |
| `url` | string | What the player plays (it needs no token): the file, such as `/play/<session>/file.mkv`, whose ranges are answered so the player can seek; or a copy's HLS playlist, `/play/<session>/index.m3u8`, listing the whole program from its start (a jump far ahead takes a few seconds more to start). Relative to where the app asked: a program started through the public port plays there (and at home), one started at home never plays through the public port |
| `why` | list or null | Why a copy is made (null for `direct`); and from 1.30.0, that another version plays, in place of one StationPlay found broken (for `direct` too) |
| `why[]` | string | One reason, such as "its sound's format (DTS)", "even sound for the show's episodes" (from 1.27.0), "another version, as 4K can't play right now" (from 1.30.0), or "its 2 files, played as one" (from 1.31.0) |
| `audioTrack` | string or null | The sound track in a copy (null for `direct`, where the player chooses among `audio`) |
| `drawnSubtitle` | string or null | The subtitle track drawn into a copy's picture, if any |
| `chosen` | object or null | What StationPlay chose for this person from their languages, and plays (from 1.29.0: see Languages); null when the app sent `audio` or `subtitle`, or nothing is chosen anywhere for them |
| `chosen.audio` | string or null | The sound track that plays: select it in the player (a copy holds only it); null for a file without sound |
| `chosen.audioWhy` | string | Why, in a few words to show: "Japanese, as chosen for this show", "The file's default: it has no Japanese sound" |
| `chosen.subtitle` | string or null | The subtitle track to show: select it in the player (for a file of its own, add it from `subtitles[].url`), unless it's `drawnSubtitle`; null for none |
| `chosen.subtitleWhy` | string | Why: "English subtitles, as you chose", "Forced English subtitles, for the parts in another language", "Subtitles are off" (from 1.29.1; "captions" before) |
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
| `versions[].problem` | string or null | As in its details |
| `versions[].playable` | boolean | Whether this device can play it directly |
| `versions[].why` | list or null | Why not, as in a 422's `why` (null when it can) |
| `versions[].why[]` | string | One reason |
| `versions[].fits` | boolean or null | Whether the connection keeps up with it (`maxKbps`); null when that, or what it needs, isn't known |
| `whenSlow` | string | What the Admin chose for when playing can't keep up here (at home, or away from home through the public port): `offer` (stop, and offer a smaller playable version from where the viewer is) or `switch` (switch to it automatically, and say so) |
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
| `audio[].languageCode` | string or null | As in its details |
| `audio[].codec` | string | As in its details |
| `audio[].default` | boolean | As in its details |
| `audio[].index` | number or null | As in its details |
| `subtitles` | list | Its subtitle tracks, as in its details |
| `subtitles[].id` | string | As in its details |
| `subtitles[].name` | string | As in its details |
| `subtitles[].language` | string or null | As in its details |
| `subtitles[].languageCode` | string or null | As in its details |
| `subtitles[].codec` | string | As in its details |
| `subtitles[].default` | boolean | As in its details |
| `subtitles[].forced` | boolean | As in its details |
| `subtitles[].external` | boolean | As in its details |
| `subtitles[].index` | number or null | As in its details |
| `subtitles[].url` | string or null | For a file of its own: where to get it, to add alongside the video (it needs no token). Tracks inside the file are the player's to show |

The `url` (and subtitles' `url`) stop working (404) when the app `POST`s to
`leave`, when the same device plays something else (from 1.30.0), after 4
hours unused, when the app's sign-in ends, when its library is no longer
shared, when watching away from home is turned off (for one started through
the public port), and when StationPlay restarts. Choose the program again
to play it again. Through the public port, a sign-in that ends stops its
programs at once.

An app gone without its `leave` (closed, or out of reach) doesn't leave
anything being made for long. A copy stops being made 2 minutes after its
player last asked for a piece. The pieces made are deleted after 10
minutes, and made again, from where the player is, if it comes back.

## POST /api/internal/progress

Where this person is in an episode or movie. Send this every 10 seconds or
so while it plays (`session` keeps the device counted as watching), and
when it stops, before its `leave`:

```json
{"key": "1234", "positionMs": 1325000, "session": "...", "sequence": 12}
```

Or mark it from a menu: `{"key": "1234", "watched": true}` (or `false`).

- **`sequence`** (from 1.30.0): each report's number in its playing (1, 2,
  3...). A report numbered no higher than one StationPlay already has for
  that playing (sent before it, but arriving after) changes nothing. It's
  answered with what's kept, so a late report never moves someone back.
  (Rewinding is a newer report, so it does.) Without `sequence`, reports
  count as they arrive.
- **Bounds.** `positionMs` is a whole number of milliseconds, 0 to 7 days.
  Anything else is refused (400, with the sentence to show). A little past
  the end counts as the end. More than 10 minutes past the end of what
  plays is refused: "That's past the end of this program." (What plays is
  the version playing, with `session`. Without it, it's the longest
  version.)
- **Watched.** Into an episode's closing credits, or 90% of the way through
  what plays, whichever comes first. For a movie in several files, that's
  all of them (see `POST /api/internal/play`). It then starts from the
  beginning next time, and Up next moves on. Watched stays watched while
  it's watched again. Less than a minute in also starts from the beginning
  next time (see Up next and the Resume row).
- **Episodes in one file.** For an episode in one file with others
  ("S01E01-E02"), where it is, and whether it's watched, applies to the
  others too.
- **How often.** Every second is fine. With `session`, Plex isn't asked
  anything for a report (one is kept even while Plex is unreachable).
  Nothing is ever sent on to Plex. StationPlay keeps each person's place
  itself, and leaves Plex's own watched marks unchanged.

| Field | Type | What it is |
|---|---|---|
| `positionMs` | number | Where it will start next time |
| `watched` | boolean | Whether this person has watched it |

## A card

How the library's lists describe a show, movie or episode. Shows have
`episodes` and `unwatched`. Episodes and movies have `durationMs`,
`positionMs` and `watched`. Episodes also have `episodeTitle`, `season`,
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
