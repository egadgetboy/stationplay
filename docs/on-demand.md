# Your library in StationPlay's apps: design (Phase 2)

Phase 2 lets StationPlay's own apps browse your shows and movies and play
them on demand, beside the stations. This document is the server's side of
it. The full product plan is in the doc "StationPlay: the full plan"; the
library layer it builds on is in `docs/library.md`.

## Goals

1. **Off until an Admin chooses.** Nothing about the library is offered to
   the apps until an Admin picks which libraries to share, on the Access
   tab. Setups that use only Plex, Jellyfin or IPTV apps never see a
   difference, and stations don't change at all.
2. **Only what's shared.** An app can see and play only what's in a shared
   library. Every key an app asks about is checked against that.
3. **The best picture and sound first.** A file plays as it is whenever the
   device can play it (direct play). Repackaging and converting come only
   when it can't (1.22.0).
4. **Each person's own place.** Where someone stopped, what they've
   watched, and what's next are kept per StationPlay user.
5. **Lean.** Plex stays the catalog (Phase 3 adds folders). StationPlay
   keeps only who watched what; it copies nothing else from Plex.

## Releases

- **1.21.0:** sharing libraries; browsing, details, search and pictures;
  direct play; progress, resume and watched; Continue Watching and
  recently added. At home, and over a VPN (which looks like home).
- **1.22.0:** repackaging and converting (HLS, with seeking), choosing
  audio and subtitle tracks when converting (picture subtitles drawn in),
  and the Admin's quality cap away from home. Watching on demand through
  the public port arrives here, since files can then be made to fit an
  upload.

The `features` an app sees (`GET /api/v1/server`) say what this server
offers where the app is: `library` once a library is shared (and, in 1.21.0,
only at home); `convert` from 1.22.0.

## Sharing libraries

The Access tab gets **Your library in StationPlay's apps**: a checkbox for
each Plex library of shows or movies. None is checked at first. The choice
is kept in `meta` as `app_libraries` (a JSON list of library keys), and
changing it is written to the log. A shared library that's gone from Plex
is simply skipped.

Everyone who can use the apps sees the shared libraries (Admins and Users
alike; while signing in is off, anyone on the home network). Kids' profiles,
which see less, come with profiles.

## Is it shared?

Every program, show and movie an app asks about must be in a shared
library. Plex says which library each is in (`librarySectionID`); the
answer is remembered per key (the 5,000 most recent), filled in as browsing
lists things, so checking rarely costs a request. A key that isn't shared,
or that Plex doesn't know, answers 404 with the same sentence either way,
so nothing can be learned by guessing keys.

## The addresses (all under `/api/v1`, documented in `docs/app-api.md`)

| Address | What it answers |
|---|---|
| `GET /libraries` | The shared libraries: key, title, kind (`show` or `movie`) |
| `GET /libraries/{key}` | One library's shows or movies, a page at a time (`start`, `size` up to 200), sorted by `title`, `added` (newest first) or `released` (newest first) |
| `GET /home` | Continue Watching for this person, and each shared library's recently added |
| `GET /search?q=` | Shows and movies whose titles contain the words, across shared libraries; and stations airing one now |
| `GET /items/{key}` | A show's or movie's or episode's details |
| `GET /items/{key}/episodes?season=` | A show's episodes: one season's, or all of them |
| `GET /art/{key}?kind=&w=` | A picture: `poster` (2:3), `backdrop` (16:9) or `thumb` (an episode's still) |
| `POST /play` | Starts playing a program: answers how and where |
| `POST /progress` | Where someone is in a program, or marks it watched or not |

A **card** (in lists) is a show's or movie's key, kind, title and year,
with its poster's address and, for a show, how many episodes it has and how
many this person hasn't watched. Text is made plain, as for stations.

Pictures come from Plex, made the size asked for (`w` is rounded up to one
of a few widths so they can be kept: 160, 320, 480, 720, 1280, 1920), and
kept in memory (up to 48 MB) like the station editor's posters. They need a
sign-in whenever signing in is on, as everything under `/api/v1` does, so
apps send their token with pictures too.

## Playing

`POST /play` with the program's key and what the device can play:

```json
{"key": "1234",
 "device": {"containers": ["mkv", "mp4", "mov", "ts"],
            "video": [{"codec": "h264", "width": 3840, "height": 2160},
                      {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10}],
            "hdr": ["hdr10", "hlg"],
            "audio": ["aac", "ac3", "eac3", "mp3", "opus", "flac"]}}
```

The server decides from Plex's description of the file (its container,
each stream's codec, size, bit depth, HDR kind and Dolby Vision profile),
never from guesses:

- **Direct play** when the device lists the container, the video's codec
  at its size and bit depth, its HDR kind (Dolby Vision profile 5 needs
  `dv`; profiles 7 and 8 play as HDR10), and the default audio track's
  codec. An HDR file on a device without HDR needs converting, since
  playing it as it is would look washed out.
- Otherwise it needs converting. In 1.21.0 that answers 422 with a
  sentence saying why, such as "This device can't play this file as it is:
  its Dolby Vision profile 5 picture. StationPlay can't convert video for
  its apps yet."

The answer is a play session:

| Field | What it is |
|---|---|
| `session` | The session's ID |
| `method` | `direct` (1.22.0 adds `repackage` and `convert`) |
| `url` | Where the player gets it: `/play/<session>/file.<container>` |
| `resumeMs` | Where this person stopped last time (0: the start) |
| `durationMs` | How long it is |
| `markers` | `intro` and `credits`, each `[startMs, endMs]` or null (the Skip intro and Skip credits buttons) |
| `subtitles` | The subtitle tracks; ones in separate files have a `url` to load beside the video |

`/play/<session>/…` addresses need no sign-in (a player can't sign in):
the session ID, 32 random characters, is what lets the player in, as the
`/hls/k/` keys do. The file comes from where StationPlay reads it for
stations: straight from disk when it can see it, otherwise from Plex. Range
requests are answered either way, so players seek freely. `POST
/play/<session>/leave` ends a session (the app stopped playing); a session
also ends 4 hours after it was last used, when its sign-in ends, when its
library is no longer shared, and when StationPlay restarts.

A session counts as a device watching, for the Admin's limits (see
`capacity.py`), from its start until 3 minutes after it was last heard from
(a file request or a progress report). One more device than the limits
allow is answered 503 with `limit` and `most`, as for stations.

## Progress, resume and watched

`POST /progress` with `{"key", "positionMs"}` (every 10 seconds or so while
playing, and when stopping), or `{"key", "watched": true}` (or false) from a
menu. Kept in a new table, per StationPlay user (user 0 while signing in is
off), the newest 5,000 programs each:

```
progress (user_id, rating_key, show_key, position_ms, duration_ms,
          watched, updated_ms, PRIMARY KEY (user_id, rating_key))
```

- Reaching a program's credits (Plex's marker) or, without one, 90% of the
  way through marks it **watched** and puts its position back to the start.
  Watched stays watched while someone watches it again.
- Less than a minute in starts from the beginning next time.
- **Up next** for a show: the episode someone is partway through (or barely
  started), or the one after the last they finished, or the first; specials
  aside, and skipping episodes already watched.
- **Continue Watching**: programs partway through, and up next for shows
  watched lately, newest first, one per show, up to 20.
- Removing a user removes their progress.
- Plex's own watched status is left alone in 1.21.0: one Plex account can't
  stand for several StationPlay users. Sending it to Plex for one chosen
  person is a later option.

## Your library and the stations

They're two ways of watching, often by different people: stations are
lean-back and run on a clock; the library plays from the start, each person
in their own place. So the library never mentions stations (no "playing now
on station 12" on a show's page), and stations never mention the library.
Search is the one place both appear: what's in the library, and which
stations are airing it right now.

## What stays out

- No preview pictures or chapter pictures (the plan's decision).
- No downloads.
- Nothing is copied from Plex into StationPlay's database but keys (as
  stations already keep).

## Order of work

1. This document.
2. Sharing, the "is it shared?" check, browsing, details, search and
   pictures, with the Plex calls behind `Library`.
3. Play sessions, direct play, progress and Continue Watching.
4. The contract (`docs/app-api.md`) and its tests, the Access tab, the
   README; then 1.21.0.
