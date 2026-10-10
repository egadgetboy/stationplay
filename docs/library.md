# The library: design (Phase 1)

StationPlay is moving from "built on Plex" to "built on a library." A
library is either a Plex library, as now, or a folder of your own (later).
This is the design for Phase 1: one library layer that everything reads
through, with Plex as its first source. Nothing about the stations changes.
The full product plan is in the document "StationPlay: the full plan."

## Goals

1. Every part of StationPlay that reads the media library reads it through
   one layer, `app/library.py`, never through the Plex client directly.
2. Plex is the first source behind that layer. Stations, their schedules,
   their stored data and every test behave exactly as before.
3. A second source (your folders, Phase 3) can be added without touching
   stations, the scheduler, the broadcaster, the file checks or the apps.
4. Anything about the Plex server itself, rather than a library, stays on
   the Plex client: the tuner and its guide refresh, who's watching,
   blocking, Plex accounts and Plex Pass.

## Program identity: keys

Every program, show, movie, collection and library has a key, which is a
short string.

- **Plex's keys don't change.** They're digits (`"12345"`). Nothing already
  stored changes, so there's no data migration.
- **Folder keys start with `f`.** A folder library's keys look like
  `"f812"`, so they can never collide with Plex's. Libraries are `"f1"`,
  `"f2"`; Plex's library keys stay digits.
- **The layer routes by shape.** It decides which source a key belongs to
  by its shape. Code outside the layer treats keys as opaque strings, as
  most of it already does.
- **Folder keys aren't found yet.** Until folder libraries exist, a folder
  key is simply "not found" (404). It's never sent to Plex, and never looks
  like Plex being unreachable.
- **Validation changes in Phase 3.** Checks that now mean "a Plex key"
  (`isdigit()`, `_plex_key`, the `_PLEX_PATH` rule) become "a library key"
  (digits, or `f` + digits) in Phase 3, with the folder source. Accepting
  folder keys before anything can answer for them would only let bad data
  in.

Keys are stored in these places, all unchanged: `channels.sources` and the
feature and block sources (JSON), `era_items` (rating, show and part keys),
`eras.first_pass`, `eras.tail`, `eras.special`, `markers`, `marathons`,
`special_runs`, `program_sets`, `scans`, the `meta` rows `plex_libraries`,
`scan_first` and `deep_again`, and `broken-files.json`.

## The layer

`Library` is the only object the rest of StationPlay holds (`ctx.library`).
It routes each call to the source that owns the key. For calls that span
libraries (listing libraries, collections, change detection), it asks every
source and combines the answers. Errors are `LibraryError` (Plex's
`PlexError` is one), with the HTTP-style `status` the source answered.

In Phase 1 there's one source, so `Library` calls the Plex client directly.
The folder source (Phase 3) answers the same calls, and `Library` gains the
routing between the two. This table shows what each source provides:

| Area | Methods | Plex source does it with |
|---|---|---|
| Libraries | `libraries()`, `library_items(key)`, `fingerprint()` | sections, section items, the library fingerprint |
| Building stations | `items_for_source(source)`, `find_again(item)` | `items_for_source`, `find_again` |
| Filters | `filter_fields`, `choices`, `filter_matches`, `filter_episodes` | the same Plex calls |
| Collections | `collections()`, `followed_collection(...)` | the same |
| Playing | `current_files(key)` → its files (`Media`, in order: one, or several for a movie on two discs), `stream_url(part)` | the same; folders have no stream URL (files are local) |
| Markers | `markers(key)`, `markers_and_added(key)` | the same; folders get detected markers (Phase 3) |
| Artwork | `art(key)`, `poster(key)`, `clear_logo(key)`, `logo_bytes(url)` | the same |
| IDs | `ids(key)` → tvdb, tmdb, imdb, library | the same |
| Rescans | `scan_folder(library, folder)` | asks Plex to scan the folder |
| Commercials | `locations()` → each library's folders and kind | sections' locations |
| Status | `configured`, `check()` | `configured`, `identity()` |

`Item`, `Media` and the source JSON shapes stay the shared language. `Media`
is a version of a program's file, with its `parts` when it's in several
files (see `catalog.py`). Each source turns its own data into these shapes,
as `plex.to_item` and `plex.to_media` do now.

These move off `ctx.plex` (the Plex map lists every call site): browsing,
station building, filters, smart stations, collections, playing, following
re-added items, change detection, artwork, markers, the scanner's credits
markers, commercials folders, Sonarr/Radarr's IDs and folder scans, and the
"is Plex set up" checks in the scanner, the list re-checks and
`/api/broken/check`, which become "is a library set up."

These stay on `ctx.plex`: `hdhr`, the guide refresh (`dvrs`,
`reload_guide`), `sessions`, `accounts`, `plex_pass`, `stop_session` and
`identity` for Plex's status line.

## StationPlay's API, and the apps' own addresses

There are two small, documented sets of addresses, built on what already
exists:

- **StationPlay's API**, under `/api/v1`, is for anyone's scripts and
  players as well as the apps. It covers the server, its stations and their
  guide, and a few Admin actions, with API tokens and an OpenAPI spec
  (`docs/api.md`).
- **The apps' own addresses**, under `/api/internal`
  (`docs/internal-api.md`), are what only StationPlay's apps use: signing
  in, connection tests and Media. They can change along with the apps.

In outline:

- `GET /api/v1/server` (open): name, version, API version, whether signing
  in is required, and the features this server has.
- `POST /api/internal/sign-in`: takes a name and password and returns a
  session token, for apps. StationPlay's page keeps using its cookie.
  `POST /api/internal/sign-out` ends the session. Apps send the token as
  `Authorization: Bearer <token>`. Sessions, the 30-day lifetime, signing
  out and the access log all work as before.
- `GET /api/v1/stations`: every station the person may watch, with its
  number, name, description, logo address, the Intro Bumper's colors for
  its logo, its HLS address, and what's on now and next.
- `GET /api/v1/guide?from=&to=` (at most 2 days): each station's programs,
  with start, end, kind, title, episode title, season, episode, year,
  summary, its picture's address, and the special it's part of, if any.
- Station logos and HLS work as before (`/channel-icon/…`, `/hls/…`).
- Every answer carries `StationPlay-API: 1`. Additions never break version
  1. A breaking change would be version 2, served alongside it.

Tests check each address against its document (`docs/api.md` or
`docs/internal-api.md`), so the documents and the server can't drift apart.

## Order of work

1. `app/library.py`: `Library` and `LibraryError`, with unit tests. Done.
2. Move each call site in the Plex map's list (a) onto `ctx.library`. Done.
3. The app connection (`app/appapi.py`), its documents (now `docs/api.md`
   and `docs/internal-api.md`) and its contract tests
   (`tests/test_app_api.py`). Done.
4. Phase 1's gate: every existing test passes, stations play exactly as
   before, and the app connection is documented.
5. Library keys (digits, or `f` + digits): with the folder source, in
   Phase 3.
