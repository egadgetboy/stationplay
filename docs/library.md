# The library: design (Phases 1 and 3)

tapiOca is built on a library, not on Plex. A library is either one of
Plex's or one of tapiOca's own, read straight from folders. This is the
design for Phase 1, one library layer that everything reads through, with
Plex as its first source; and for Phase 3 (1.35.0, below), the folder
source: tapiOca with or without Plex. The full product plan is in the
document "tapiOca: the full plan."

"Library" here is the code's name for this layer and for its libraries.
What people read says **Media** for the titles shared with tapiOca's apps,
**Media folders** for Plex's libraries, and **Media folders tapiOca reads itself**
for the folders it reads without Plex.

## Goals

1. Every part of tapiOca that reads the media library reads it through
   one layer, `app/library.py`, never through the Plex client directly.
2. Plex is the first source behind that layer. Stations, their schedules,
   their stored data and every test behave exactly as before.
3. A second source (your folders, Phase 3) is added without touching
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
- **A folder key no folder library has is "not found" (404).** It's never
  sent to Plex, and never looks like Plex being unreachable.
- **Validation is "a library key."** Everywhere a key comes in (station
  sources, filters' libraries and left-out programs, the editor's lists and
  posters, logos, and Media's keys and shared Media folders), a key is
  digits, or `f` and digits (`library.is_key`), at most 20 digits.
  `isdigit()` checks left in the code are about other things (track
  numbers, Sonarr's and Radarr's IDs, times). Plex's own `_PLEX_PATH` rule
  stays as it is: only Plex's keys ever reach Plex.
- **One program belongs to no source (from 1.34.1).** The INFO station's
  one program (`app/infostation.py`) has the key `f0`: a folder library's
  shape, with a number no folder library is given (their ids start at 1).
  Its station's one source
  is `{"type": "info"}`. The layer answers for it itself, from the film in
  the image (`app/assets/info/`), without asking Plex: its program, its
  file, no markers, and its logo as its art and poster.

Keys are stored in these places, all unchanged: `channels.sources` and the
feature and block sources (JSON), `era_items` (rating, show and part keys),
`eras.first_pass`, `eras.tail`, `eras.special`, `markers`, `marathons`,
`special_runs`, `program_sets`, `scans`, the `meta` rows `plex_libraries`,
`scan_first` and `deep_again`, and `broken-files.json`.

## The layer

`Library` is the only object the rest of tapiOca holds (`ctx.library`).
It routes each call to the source that owns the key. For calls that span
libraries (listing libraries, collections, change detection), it asks every
source and combines the answers. Errors are `LibraryError` (Plex's
`PlexError` is one), with the HTTP-style `status` the source answered.

`Library` routes each call by its key's shape: digits to Plex, `f` and
digits to the folder source (`app/folders.py`). For calls about every
library it asks both and puts Plex's answers first. Either source may be
missing: Plex when `PLEX_URL` and `PLEX_TOKEN` aren't set, the folder
source until an Admin adds a Media folder of tapiOca's own. This table
shows what each source provides:

| Area | Methods | Plex | Folders |
|---|---|---|---|
| Libraries | `libraries()`, `library_items(key)`, `fingerprint()`, `counts()` | sections, section items, the library fingerprint | its libraries, their shows or movies, a fingerprint of what was read |
| Building stations | `items_for_source(source)`, `find_again(item)` | `items_for_source`, `find_again` | the same, from its tables |
| Filters | `filter_fields`, `choices`, `filter_matches`, `filter_episodes` | the same Plex calls | genre, collection, studio (a show's network), content rating, director, actor and decade, from NFO files, tags and names |
| Collections | `collections()`, `followed_collection(...)` | the same | collections named in NFO files (`<set>`) |
| Media | `browse`, `genres`, `recently_added`, `entry`, `entries`, `show_episodes`, `picture` | the same | the same, from its tables |
| Playing | `current_files(key)` → its files (`Media`, in order: one, or several for a movie on two discs), `stream_url(part)` | the same | its files, read from disk; no stream URL |
| Markers | `markers(key)`, `markers_and_added(key)` | the same | none yet (detected markers come after 1.0) |
| Artwork | `art(key)`, `poster(key)`, `clear_logo(key)`, `logo_bytes(url)` | the same | pictures beside the videos, then covers inside them |
| IDs | `ids(key)` → tvdb, tmdb, imdb, library | the same | from NFO files and names (`{tmdb-12345}`) |
| Rescans | `scan_folder(library, folder)` | asks Plex to scan the folder | reads its library again soon (only what's new or changed) |
| Commercials | `libraries()` → each library's folders (`locations`) and kind | sections' locations | its folders |
| Status | `configured`, `check()` | `configured`, `identity()` | configured once it has a library |

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

## Phase 3: Media folders of tapiOca's own (1.35.0)

An Admin adds one on the Setup tab, under **Media folders**: a
name, Shows or Movies, and one or more folders inside the media folder
(`MEDIA_DIR`, `/media` in the container). Each is a library like Plex's:
for stations, filters, smart stations, collections, and Media in tapiOca's
apps (on to start, as every Media folder is, until an Admin chooses).

**The modules.** `app/folders.py` (the source: its tables, scanning, the
details put together, and the page's addresses), `app/folderscan.py`
(walking a folder and reading each file), `app/naming.py` (what names
say), `app/nfo.py` (what NFO files say) and `app/folderart.py` (pictures).

**Keys and tables.** Libraries are `f1`, `f2`...; shows, episodes, movies
and collections are `f` and their id, from 1. Ids are never used twice
(SQLite's `AUTOINCREMENT`). A file moved or renamed keeps its key when it's
recognizably the same: the same size and the same show, season and
episode, or the same movie. The tables (new in 1.35.0, so the update makes
`before-1.35.0-<date>.db` first) are `folder_libraries`, `folder_items`
(each show, episode, movie and collection), `folder_files` (what each video
holds, as last read) and `folder_nfos` (each NFO file, as last read).

**Scanning.** At the lowest priority, never while anyone is watching a
station or Media (it waits and looks again): 30 seconds after tapiOca
starts, every 6 hours, when an Admin chooses **Read again**, when a Media
folder is added or its folders change, and when Sonarr or Radarr brings a
replacement tapiOca asked for (`scan_folder`). Only what's new or changed, by size and
time, is read again (ffprobe, two files at once). A folder that can't be
reached (an unmounted share) never empties a library: its programs are
kept and said to be missing until it's back, and they're never taken off
stations for it.

**Walking.** Only videos, by extension. Left out: hidden files and
folders; a NAS's own folders (`@eaDir`, `#recycle`); discs copied as they
are (`BDMV`, `VIDEO_TS`); extras folders (Extras, Featurettes, Behind The
Scenes, Deleted Scenes, Interviews, Trailers, Shorts, Other, Scenes) and
extras named as Plex names them (`-trailer`); samples; and anything whose
real path is outside the media folder (a symbolic link out of it).

**Details, in layers.** Each detail comes from the first layer that has
it:

1. NFO files beside the videos, in Kodi's format, as Sonarr, Radarr,
   Jellyfin, Emby and tinyMediaManager write them (`tvshow.nfo`,
   `season.nfo`, an episode's own, `movie.nfo`). Read safely: at most 1 MB,
   never one with a DOCTYPE or entities, each detail cut to a sensible
   length.
2. Tags inside the files (title, date, description, show, season and
   episode, genre), from ffprobe.
3. Folder and file names, as Sonarr, Radarr, Plex, Jellyfin and Emby name
   them: `Show (2010)/Season 01/Show - S01E02 - Title.mkv`, `1x02`,
   `S01E02E03` and `S01E02-E03` (one file, two episodes), `Specials` or
   `Season 00`, dates for daily shows, `Movie (1999)/Movie (1999).mkv`,
   versions (`Movie (1999) - 4K.mkv`) and parts (`cd1`, `part1`, `disc1`),
   and IDs in names (`{tmdb-12345}`, `[imdbid-tt0012345]`, `{tvdb-67890}`).

Nothing is looked up online, matched or guessed in Phase 3: a title
tapiOca can't be sure of is listed by what its names say. Matching, Needs a
match, locks and the online sources come with the rest of folder libraries
(the plan's #4, and after 1.0).

**Pictures.** Only from inside the media folder: first pictures beside the
videos (`poster.jpg`, `folder.jpg`, `fanart.jpg`, `clearlogo.png`,
`season01-poster.jpg`, an episode's `-thumb.jpg`...), then a cover inside
the file (an MKV's attachment, an MP4's cover), taken out once and kept in
the data folder's `folder-art`. Every path is resolved first (links
followed), and one that ends up outside the media folder is refused. A
title with no picture shows as the apps show any title without one;
tapiOca's own made pictures come later.

**What the apps get.** The same as from Plex, with keys of `f` and digits.
Never a file's name or a path: a version is described by what it holds
(picture, sound, subtitles, length), as Plex's are.

**Without Plex.** With a Media folder of its own and no `PLEX_URL`,
tapiOca's setup says Plex is optional and passes its Tuner step's Plex checks; stations
play from the files, and the tuner works for Jellyfin and other apps as
before. Plex's Live TV still needs Plex, and Plex Pass.

## tapiOca's API, and the apps' own addresses

There are two small, documented sets of addresses, built on what already
exists:

- **tapiOca's API**, under `/api/v1`, is for anyone's scripts and
  players as well as the apps. It covers the server, its stations and their
  guide, and a few Admin actions, with API tokens and an OpenAPI spec
  (`docs/api.md`).
- **The apps' own addresses**, under `/api/internal`
  (`docs/internal-api.md`), are what only tapiOca's apps use: signing
  in, connection tests and Media. They can change along with the apps.

In outline:

- `GET /api/v1/server` (open): name, version, API version, whether signing
  in is required, and the features this server has.
- `POST /api/internal/sign-in`: takes a name and password and returns a
  session token, for apps. tapiOca's page keeps using its cookie.
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
   Phase 3. Done.
6. Phase 3: the folder source (1.35.0). Its gate: stations run and Media
   plays from folders alone, with no Plex, with real ffmpeg
   (`tests/test_e2e_folders.py`).
