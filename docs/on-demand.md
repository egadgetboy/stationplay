# Media in StationPlay's apps: design (Phase 2)

Phase 2 lets StationPlay's own apps browse your shows and movies in Media
and play them whenever you like, alongside the stations. This document
covers the server's side. The full product plan is in the document
"StationPlay: the full plan," and the library layer this builds on is in
`docs/library.md`.

## Goals

1. **Off until an Admin chooses.** The apps get nothing from the library
   until an Admin picks which libraries to share, on the **Access** tab.
   Setups that use only Plex, Jellyfin or IPTV apps see no difference, and
   stations don't change at all.
2. **Only what's shared.** An app can see and play only what's in a shared
   library. Every key an app asks about is checked against that.
3. **The best picture and sound first.** A file plays directly whenever the
   device can play it (direct play). Repackaging and converting happen only
   when it can't, and repackaging (the picture unchanged) comes before
   converting (1.24.0).
4. **Each person's own place.** Where someone stopped, what they've watched
   and what's next are kept for each person.
5. **Lean.** Plex stays the catalog (Phase 3 adds folders). StationPlay
   keeps only who watched what, and copies nothing else from Plex.

## Releases

- **1.21.0.** Sharing libraries; browsing, details, search and pictures;
  direct play; progress, resume and watched; the Resume row (then called
  Continue Watching) and recently added. At home, and over a VPN (which
  looks like home).
- **1.22.0.** Versions: the best one the device and its connection keep up
  with, one chosen when playing, and a smaller one when playing can't keep
  up. Skip intro and Skip credits, for episodes only, where Plex's markers
  fit the file. The apps' own addresses move to `/api/internal`.
- **1.23.0.** Viewing Levels: each person sees only what their level
  allows, in Media as everywhere else (see `docs/users.md`).
- **1.24.0.** Copies of what a device can't play directly, repackaged or
  converted (HLS, with seeking: see Copies), with the chosen sound track,
  subtitles drawn in, a smaller picture to fit the connection, and night
  mode's sound. Browsing narrowed by genre or to what's unwatched, and by
  letter. Cast and crew, taglines, and titles like this one.
- **1.25.0.** Copies converted on the GPU, as stations use it (see Copies).
- **1.27.0.** Media through the public port while watching away from home
  is on, with the Admin's quality away from home (see Away from home). Even
  sound for a show's episodes (see Even sound).
- **1.30.0.** Media made solid. Answers come within 8 seconds whatever
  state Plex is in (see When Plex is slow or away). StationPlay sorts, pages
  and searches lists itself, ignoring case and accents (see Lists). Up next
  is decided in one place, and progress is kept in order (see Progress,
  resume and watched). Pictures are fetched once (ETags). A device plays
  one program at a time, and a movie in several files plays its first.
  Media's files get the same checks as the stations': the checks reach
  Media, trouble playing a file gets it checked, a broken file doesn't
  play, and people report problems from a list (see Files that don't play).
- **1.31.0.** A movie in several files plays as one. Its length covers all
  of them, and resume, progress, seeking, Up next and watched work across
  the whole (see A movie in several files).
- **Later.** Fragmented MP4 copies, so Apple's player can get an HEVC
  picture unchanged.

The `features` an app sees (`GET /api/v1/server`) show what this server
offers where the app is:

- **`library`**: once a library is shared, at home. From 1.27.0, also
  through the public port while watching away from home is on.
- **`convert`**: from 1.24.0, wherever `library` is.
- **`even-sound`**: from 1.27.0, wherever `library` is, while an Admin has
  it on.
- **`convert-asked`**: from 1.29.1, wherever `library` is. An app whose
  decoder failed at a file asks for a converted copy (`convert: true`), and
  gets one whatever the device says it plays.

## Sharing libraries

The **Access** tab has **Media in StationPlay's apps** (named for the apps'
Media section from 1.25.0): a checkbox for each Plex library of shows or
movies. None is checked at first. The choice is kept in `meta` as
`app_libraries` (a JSON list of library keys), and each change is written to
the log. A shared library that's gone from Plex is simply skipped.

Everyone who can use the apps sees the shared libraries, within their
Viewing Level (from 1.23.0: see `docs/users.md`). That includes Admins and
Users alike, and, while signing in is off, anyone on the home network.

## Is it shared?

Every program, show and movie an app asks about must be in a shared
library. Plex reports which library each is in (`librarySectionID`).
StationPlay remembers the answer for each key (the 5,000 most recent),
filling it in as browsing lists things, so checking rarely costs a request.
A key that isn't shared, or that Plex doesn't know, gets 404 with the same
sentence either way, so guessing keys reveals nothing.

## When Plex is slow or away

No address for the apps waits long on Plex. Whatever a request needs from
the library (details, a list, a picture, a show's episodes), it gets within
8 seconds of first asking (`ondemand.LIBRARY_WAIT_S`), or it answers 503:
"StationPlay can't reach Plex right now. Try again in a moment." That's well
before an app would give up waiting on its own.

The same goes for an answer from Plex that StationPlay can't read (one that
isn't JSON, or isn't what Plex should send). It's handled as Plex being
away, never as a 500. A single show or movie in a list that can't be read is
left out of the list. A field of the wrong type (a year that isn't a number,
say) is left out of the answer. What Plex says isn't there (404) answers
404, as anything not shared does.

What was being fetched isn't thrown away when a request stops waiting. It
carries on, once for everyone asking for it at the same time, and is kept as
usual, so an app asking again a little later often finds it ready. The log
reports that the library can't be reached at most once a minute, however
many apps are asking. The libraries themselves are kept for a minute, so
browsing rarely asks Plex for them.

## The addresses (all under `/api/internal`, documented in `docs/internal-api.md`)

| Address | What it answers |
|---|---|
| `GET /libraries` | The shared libraries: key, title, kind (`show` or `movie`) |
| `GET /libraries/{key}` | One library's shows or movies, a page at a time (`start`, `size` up to 200), sorted by `title`, `added` (newest first) or `released` (newest first), narrowed by `genre` or `unwatched`, with its genres and where each letter starts |
| `GET /home` | The Resume row for this person, and each shared library's recently added |
| `GET /search?q=` | Shows and movies whose titles contain the words, across shared libraries, ignoring case and accents; and stations airing one now |
| `GET /items/{key}` | A show's, movie's or episode's details |
| `GET /items/{key}/episodes?season=` | A show's episodes: one season's, or all of them, a page at a time (`start`, `size` up to 500) |
| `GET /items/{key}/related` | Titles like a show or movie: sharing its genres, then the nearest in years |
| `GET /art/{key}?kind=&w=` | A picture: `poster` (2:3), `backdrop` (16:9) or `thumb` (an episode's still) |
| `POST /play` | Starts playing a program, and answers how and where |
| `POST /progress` | Where someone is in a program, or marks it watched or not |

## Lists

StationPlay sorts and searches the lists itself, from each library's whole
list of shows or movies. It fetches that list from Plex 500 at a time (all
the rest at once after the first) and keeps it (`Whole` in `ondemand.py`).
The list is kept unchanged for 2 minutes, then for as long as the library's
fingerprint (Plex's times for each library's changes) shows nothing has
changed, up to 30 minutes. A genre's list is fetched as a list of its own.
At most 8 lists are kept, with 40,000 shows and movies among them. The
episodes of the 50 shows asked about most recently, 40,000 episodes among
them, are kept the same way.

- **Sorting.** By title, StationPlay uses the library's sort title. Plex's
  sort title leaves out a leading "The," "A" or "An." For a title without
  one, StationPlay leaves those words out itself. Titles sort from their
  first letter or digit ("¡Three Amigos!" with the Ts), ignoring case and
  accents, with numbers as numbers. "#" (digits, and anything but A to Z,
  such as another alphabet) comes first. Sorted by newest added or newest
  released, titles without a date come last, and ties go in title order.
  Titles that sort alike are in key
  order, so pages never repeat or skip one, and every letter stays together
  for jumping to it.
- **Paging.** A library's shows or movies come up to 200 a page. A show's
  episodes come up to 500 a page, and 500 unless an app asks for fewer, so
  an app before 1.30.0 still gets a whole season. Search answers up to 50.
  The Resume row and each library's recently added answer up to 20, and
  titles like a show or movie up to 12.
- **Search.** The words (1 to 100 characters) are found anywhere in a title
  or its sort title, ignoring case, accents ("Amélie" for "Amelie") and
  punctuation, and spaces too ("spiderman" for "Spider-Man"). A title that's
  just the words comes first, then titles starting with them, then titles
  with a word starting with them, then the rest, each group in title order.
  The answer is the first 50 that person may see.
- **Large libraries.** With 5,000 movies, 300 shows and 20,000 episodes,
  the first page of a library after it changes takes as long as Plex takes
  for its pages (10 of them, requested together, 6 at a time). After that,
  every page, sort, filter, letter and search comes from what's kept, in
  tens of milliseconds, without asking Plex (checked by the tests). A page
  of 200 is about 35 KB, and a show's 500 episodes about 140 KB. Lists are
  kept without each title's summary (cards don't show it; details do),
  which halves their size: 5,000 movies take about 4 MB.
- **The home screen** is opened often, so opening it again soon asks Plex
  for nothing. Each library's recently added is kept for a minute, and the
  Resume row's shows and movies for 10 minutes.

A **card** (in lists) is a show's or movie's key, kind, title and year, with
its poster's address. A show's card also has how many episodes it has and
how many this person hasn't watched. Text is made plain, as for stations.

Pictures come from Plex, at the size asked for. `w` is rounded up to one of
a few widths so pictures can be kept: 160, 320, 480, 720, 1280, 1920.
They're kept in memory, like the station editor's posters, up to 48 MB; one
over 6 MB isn't kept. They need a sign-in whenever signing in is on, as
everything under `/api/internal` does, so apps send their token with
pictures too.

- **Fetched once.** Each has an ETag (from its content) and
  `Cache-Control: private, max-age=86400`. An app keeps it a day, then asks
  with `If-None-Match`. While it's the same, the answer is 304, with nothing
  sent. Who may see it is checked first, every time.
- **Never a hang.** A picture the library says it doesn't have (no poster,
  no backdrop) is 404 without asking Plex. One Plex doesn't have, or answers
  with something that isn't a picture (an image type, not empty, at most
  20 MB), is 404 too. Plex not sending it in time is 503, as for the rest of
  the library (8 seconds). At most 8 are requested from Plex at once, since
  an app scrolling a grid of posters asks for many. The rest wait their turn
  within that time.

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

The server decides from Plex's description of the file (its container, each
stream's codec, size, bit depth, HDR type and Dolby Vision profile), never
from guesses:

- **Direct play** when the device lists the container, the video's codec at
  its size and bit depth, its HDR type (Dolby Vision profile 5 needs `dv`;
  profiles 7 and 8 play as HDR10) and the default audio track's codec. An
  HDR file on a device without HDR needs converting, since playing it
  directly would look washed out.
- **Otherwise, a copy** (see Copies), for an app that takes one
  (`device.hls`). For an app that doesn't, or when no copy would show it
  right, the answer is 422 with a sentence saying why, such as "This device
  can't play this file as it is (its Dolby Vision profile 5 picture), and
  StationPlay can't make a copy of it that the device can."

The answer is a play session:

| Field | What it is |
|---|---|
| `session` | The session's ID |
| `method` | `direct`, `repackage` or `convert` |
| `url` | Where the player gets it: `/play/<session>/file.<container>`, or a copy's playlist, `/play/<session>/index.m3u8` |
| `resumeMs` | Where this person stopped last time (0: the start) |
| `durationMs` | How long it is |
| `markers` | `intro` and `credits`, each `[startMs, endMs]` or null, and `creditsToEnd` (the Skip intro and Skip credits buttons; episodes only) |
| `subtitles` | The subtitle tracks; ones in separate files have a `url` to load alongside the video |

A device plays one program at a time. Starting one ends what it was
playing: its addresses answer 404 and a copy being made for it stops. The
log notes that it stopped, unless the new one is the same program again
(another sound track, or a smaller version). A device is an app's sign-in,
or, while signing in is off, its address. Every refusal is a status with
`detail`, a sentence the apps show unchanged.

`/play/<session>/…` addresses need no sign-in, since a player can't sign
in. The session ID, 32 random characters (192 bits, from `secrets`), is what
lets the player in, as the `/hls/k/` keys do. The file comes from where
StationPlay reads it for stations: straight from disk when it can see it,
otherwise from Plex. Range requests are answered either way, so players
seek freely. `POST /play/<session>/leave` ends a session (the app stopped
playing). A session also ends 4 hours after it was last used, when its
sign-in ends, when its library is no longer shared, and when StationPlay
restarts. Through the public port, only a session started there is offered
(see Away from home).

A session counts as a device watching, for the Admin's limits (see
`capacity.py`), from its start until 3 minutes after it was last heard from
(a file request or a progress report). One more device than the limits
allow gets 503 with `limit` and `most`, as for stations. A session also
counts as someone watching for StationPlay's file checks, which wait while
anyone watches a station or Media (see below).

## A movie in several files

Plex keeps some movies as several files, with one version stacked from them
("Movie-cd1.mkv", "Movie-cd2.mkv"; "part 1", "part 2"). From 1.31.0, such a
movie plays as one program, on the stations and in Media. Before, only its
first file played, and on a station, black filled the rest of its time.

- **Reading it.** Wherever StationPlay reads a version's file from Plex, it
  keeps every file, in order, each with its own length, and the whole
  (`catalog.Media.parts`). Each length is Plex's, or where Plex doesn't
  give one, the file's own, found by opening it. A version in one file is
  read as before.
- **The apps get one program.** Its `durationMs` is the whole. Resume,
  progress, seeking, Up next and watched (90% of the whole) work across it,
  in the movie's own time. Nothing an app receives names a file or says how
  many there are, except the copy's `why`.
- **How it plays: a copy that joins the files.** A player plays one
  address. So for an app that takes copies (`device.hls`), the server serves
  an HLS copy (see Copies) whose playlist lists the whole movie. Each file's
  pieces follow the previous file's (no piece spans two), with the movie's
  own times throughout, so the player sees one program and can seek
  anywhere in it.
- **Repackaged or converted.** The copy is **repackaged** when every file's
  picture is the same (format, size, bit depth, HDR) and the device plays
  it, so nothing is converted and it costs next to nothing. Otherwise (the
  files' pictures differ, or the device can't play them), it's
  **converted**, with one picture for all of them. The sound is copied when
  it's the same in every file and the device plays it, and remade
  otherwise.
- **No visible join.** Each file's pieces come from a separate ffmpeg run,
  and the next file's run starts as one reaches its file's end. The pieces
  carry straight on (their times, and the MPEG-TS stream's counters), so the
  player sees no join. Started from `startMs` inside a later file, the copy
  starts there, without reading the files before it. Its `why` starts with
  "its 2 files, played as one".
- **Why this way.** It's the only way that works for the apps at the time
  (StationPlay for Android 0.3.2, Apple 0.2.0, Roku 0.5.0), which play one
  address. Their players already take copies, so they need nothing new.
  Repackaging keeps the picture unchanged, so a movie whose files are alike
  (nearly all) plays at its full quality, at almost no cost.
- **The alternatives were worse.** The apps playing the files one after
  another would mean changing each app, a pause at the join, and resume and
  progress split between files. A file joined on the fly fails because MKV
  and MP4 files can't be joined end to end, and a joined container would
  have to be built as it plays. ffmpeg's concat demuxer as one input breaks
  where the files' formats differ, which then needs this anyway.
- **What it costs.** Every device gets a copy, where a movie in one file
  might play directly. So sound a copy can't carry unchanged (DTS, Dolby
  TrueHD) comes as Dolby Digital 5.1 or stereo, as for any copy. A converted
  copy counts against the copies converted at once.
- **Subtitles are drawn in.** Subtitles in the files, or in subtitle files
  of their own, are drawn into the picture, since a subtitle file next to
  the copy would match only one of the files. Each file uses its own track,
  at the same position among its tracks (none, for a file without one).
- **An app that doesn't take copies** (no `device.hls`) can't play it as
  one. It gets 422, with `why` ["it's in 2 files"] and the usual sentence.
  Another version in one file plays instead, if there's one it plays
  directly.
- **Its files are checked** like every file: each of them, in order, by the
  quick check and the deep scan, each with its own record. A damaged or
  broken one takes the version off the air, with one entry on the Broken
  files list that names the file ("Check: ..., in part 2 of 3"), its times
  that file's own. Trouble an app has at a point in the movie is checked in
  the file that point is in.

## Files that don't play

From 1.30.0, Media's files go through the same process as the stations'
(see `scanner.py`, `broken.py` and the README's Broken files list). What
StationPlay's checks find is kept for each file, whoever plays it, on the
one Broken files list. A file found broken for a station is broken in Media
too, and the other way around. A file checked for one isn't checked again
for the other unless it changes. A program's other versions are separate
files on the list (by its key and the version's ID).

- **The checks reach Media.** What's newly added to a shared library is
  quick-checked within minutes, after the stations' new programs. The
  overnight deep scan, after the stations' programs, decodes Media's files
  in full: what's in someone's Resume row first, then the next episode of a
  show someone is watching, then the rest, most recently added first.
- **No weekly checks.** Media's files aren't checked weekly. They're checked
  when they arrive, and when someone has trouble with one.
- **Trouble isn't a verdict.** A copy that can't be made or stops, or an app
  reporting that something didn't play or stopped
  (`POST /api/internal/problem`, with its playing and position, from
  1.30.0), puts that file at the front of the checks' queue. StationPlay
  checks the stretch around where it happened, then runs the quick check.
  Only what StationPlay finds puts a file on the list. Trouble caused by the
  network or the app changes nothing.
- **Listed files in Media.** A version found broken never plays. Another
  version plays, if there's one StationPlay didn't find broken, and the play
  answer's `why` says so. With none, the answer is 422: "This one can't play
  right now. An Admin has been told." A damaged version plays, as before.
  An item's details show what was found in each version
  (`versions[].problem`), so an app can offer another.
- **People's reports** (see `reports.py`, and "Reporting a problem" in
  `docs/internal-api.md`). People pick from a list on a movie's or an
  episode's page, in the player's menu, and in a station's player. What
  StationPlay can check is checked at once. What it can't judge waits for
  an Admin on the **Broken files** tab. A report never takes anything out of
  Media, or off the air, by itself.
- **Replacing.** Sonarr and Radarr replace Media's files as they do the
  stations', with the same settings, limits and rules.

## Away from home

From 1.27.0, while an Admin has watching away from home on (on the
**Access** tab, with the address the apps use from outside: see `away.py`),
the apps get Media through the public port too. A VPN looks like home, so
nothing changes there. A signed-in app can do there whatever it may at
home: browsing, details, search, pictures, progress and playing, directly
or as a copy, within the same Viewing Levels and limits. With watching away
from home off, the library's addresses answer 403 there, and `features`
doesn't list `library`.

- **Play addresses.** On the public port, `/play/<session>/…` is offered
  only for an active session that a signed-in app started through the
  public port, while watching away from home is on, and only over HTTPS (as
  everything for the apps is there).
- **Sign-ins checked each time.** A session's sign-in is checked on each
  request there (at home, every minute), so it stops the moment the sign-in
  ends. Turning watching away from home off ends every session started
  there.
- **Everything else is 404.** Anything else (a guessed address, a session
  started at home, or one that has ended) gets 404. Only an active session
  started there gets past the Gate (`access.Access.play_outside`). The Gate
  answers the rest itself, before anything else sees them.
- **Quality away from home** (an Admin's setting, kept with watching away
  from home). **Original** plays each title as it would at home. **Up to**
  1 to 200 Mbps plays a version within the cap as it would at home (the
  best the device plays directly, as at home). With none within the cap,
  StationPlay converts one down to fit: a converted copy whose picture and
  sound need no more than the cap (as `fit` makes one for a connection,
  without its headroom). Any copy converted away from home stays within the
  cap.
- **What a version needs.** An app that doesn't take copies is told why it
  can't play one over the cap (422). A version's need is Plex's bitrate, or
  else its size over its length. A version whose need isn't known isn't
  held against it. The apps' own "can't keep up" handling still works on
  top of the cap.
- **A guide for the cap.** Next to the setting, the **Access** tab shows the
  upload speed StationPlay's apps measured with their connection tests from
  outside.
- **Limits.** A device playing through the public port is counted by its
  app's own key, as its stations are, so apps behind one reverse proxy are
  told apart. It counts against the Admin's limit on devices away from home
  as well as the overall one. Copies converted away from home count toward
  the copies converted at once, along with those at home.
- **Logs and Stats** show "away from home" for these plays, as for
  stations, and the access log notes each one started there.
- **Checking the address** (`reach.py`). Media goes through the same proxy,
  to the same port, over HTTPS, as stations do. So a Ready check covers it,
  and says so while a library is shared.

## Copies

A device that can't play a file directly gets a copy that StationPlay makes
as it's played (`converting.py`). The copy is HLS. Its playlist lists the
whole program from its start, in pieces of about 6 seconds, so the player
shows the whole length and can seek anywhere.

One ffmpeg makes the pieces as they're asked for, from where the player is
(and again from wherever it jumps to). It stays a few pieces ahead of the
player and no further. Pieces are deleted behind the player and when the
session ends. ffmpeg stops when nothing has asked for 2 minutes, and the
pieces made are deleted when nothing has asked for 10 (an app gone without
leaving; they're made again if it comes back). StationPlay checks this
every minute. The session itself ends after 4 hours unused.

- **Repackaged** when the device plays the picture unchanged and the pieces
  can carry it (H.264; HEVC for a player that takes HEVC in MPEG-TS pieces).
  The picture is copied, costing next to nothing. The sound is converted if
  the device can't play it (AAC, or Dolby Digital 5.1 where the device plays
  it and the sound has more than two channels).
- **Keyframes from the index.** Each piece starts at one of the picture's
  keyframes, read up front from the file's own index (a Matroska file's
  Cues, an MP4's sample tables: `keyframes.py`), without reading through
  the file. A file without an index is converted.
- **Converted** otherwise, and for subtitles drawn in or a smaller picture:
  H.264 at most 1080p (or what fits the connection), an HDR picture
  tone-mapped to SDR as the stations do it, and a keyframe at the start of
  each piece. At most 3 at once, or 6 on a GPU.
- **On the GPU** (1.25.0). While the stations' GPU is in use (VA-API or
  NVENC, proven by its test at startup), a converted copy is made there. It
  is set up as the stations' programs are (the GPU decodes the file too,
  where it can) and encoded with their settings except for three: the
  copy's own bitrate, the level its size and frame rate need, and keyframes
  as often as libx264 makes them.
- **What stays on the processor.** Scaling, tone-mapping to SDR and drawing
  in subtitles stay on the processor, as for the stations; then the picture
  goes up to the GPU. A copy converted there is light on the processor.
  Each piece still starts with an IDR keyframe exactly where the playlist
  says, and there are no B-frames.
- **The processor as a fallback.** If a copy goes wrong on the GPU (ffmpeg
  stops with an error or writes nothing, a piece doesn't start with a
  keyframe where it should, or nothing comes for a minute), it carries on
  from where it was on the processor, and stays there. The viewer sees no
  more than the usual wait, and it isn't counted against the copy.
- **Strikes against the GPU.** Once the processor makes the piece the GPU
  failed at, that's a strike against the GPU for copies. A stall isn't,
  since a slow disk stalls too. A copy made on the GPU without trouble from
  start to end clears the strikes. After 3 strikes in a row, copies are
  converted on the processor until StationPlay restarts. The stations keep
  the GPU, since a copy's trouble there (a GPU out of encoding sessions,
  say) says nothing about theirs. While the GPU is being tested at startup,
  or once it's turned off, copies are converted on the processor.
- **Pieces that line up.** ffmpeg writes one MPEG-TS stream with the
  program's own times (offset by 10 seconds), and StationPlay cuts it into
  the pieces itself at their keyframes. So pieces made by different runs
  line up exactly.
- **Subtitles drawn in.** A picture track (PGS, VobSub) is laid over the
  picture. Text in the file is first extracted to a file of its own, once
  (as the stations do). A separate subtitle file is fetched first.

## Even sound

From 1.27.0, every episode played from Media comes at the loudness the
stations' episodes have (`ffmpeg.LOUDNESS_TARGET`, -24 LUFS, with ffmpeg's
loudnorm in one pass). So all of a show's episodes match, in order or
shuffled, in any app. Movies are never touched, as on the stations. It's on
by default. An Admin can turn **Even sound for a show's episodes** off on
the **Access** tab's Media panel (kept in `meta` as `app_even_sound`).

- **How.** The same way night mode's sound is made for an app that can't
  make it: a copy that keeps the picture unchanged and remakes only the
  sound (repackaged), for an app that takes copies (`device.hls`). Its sound
  is what the device would get anyway (`converting.sound_for`), remade
  rather than copied: Dolby Digital 5.1 where the device plays it and the
  sound has more than two channels, otherwise AAC stereo.
- **The order of filters.** Even sound comes first in its filters. With
  night mode too, night mode comes after it, so its compression starts from
  the same loudness in every episode and its limiter is last.
- **The picture is never remade for it.** Where the picture can't be kept
  unchanged (a picture the copy's pieces can't carry for that player, or a
  file without an index to cut it by), an episode the device plays directly
  plays directly. A copy made for another reason (converted, a smaller
  picture, subtitles drawn in, night mode) has even sound too.
- **The cost.** The episode's sound is remade, so sound sent unchanged to a
  receiver (Dolby Atmos, DTS) comes as ordinary 5.1 or stereo. That's why
  there's a switch.
- **The apps.** `features` lists `even-sound` while it's on, and a copy's
  `why` says "even sound for the show's episodes", for the player's info.
  An app that doesn't send `device.hls` (older apps) gets the file as
  before.

## Skip intro and Skip credits

For episodes only. Plex finds an episode's intro by matching it across a
season, and its closing credits as they start. Movies are made too many ways
(credits over the final scene, scenes between the credits) for a button to
be trusted, so they have none. A button in the wrong place is worse than
none, so an episode's markers are used only where they fit its file
(`plex._skips`), by the rules stations use (`markers.py`) and these:

- **Markers that don't fit.** A marker ending past the end of the file, or
  ending before it starts, means Plex's markers don't fit this file (they
  were found in another, since replaced). None are used.
- **Versions of different lengths.** Nor are markers used for an episode
  with versions of different lengths (over a second apart). Plex finds
  markers in one, and the others may not line up.
- **Where they must fall.** The intro starts in the first half and runs
  under 5 minutes. It must end before the credits start (otherwise neither
  is used) and at least a minute before the end. The credits start in the
  second half: the ones Plex marks as final, or else the last.
- **Scraps.** A scrap of under 5 seconds before the intro, or after the
  credits, goes with it. Skip intro shows from the very start, and Skip
  credits goes on to the next episode rather than a second of black
  (`creditsToEnd`).

The apps offer the buttons. Nothing is skipped unless the viewer presses one
(skipping without asking is planned as a setting, off by default). A button
shows while the player is inside its part, and again if the viewer goes back
into it. It lands exactly at the part's end. Skip credits with
`creditsToEnd` goes on to the next episode, or finishes the show.

## Keeping up

Steady playback comes before anything else. The apps buffer the way players
do for a file: well ahead (the Android app up to 90 seconds, within its
memory budget), and after a stall, a good 8 seconds before carrying on. So a
slow patch is one pause rather than many. Waits after a seek, or before the
first picture, aren't stalls.

Only trouble that lasts counts. The first 45 seconds belong to the buffer
and the decoder (only a single 20-second stall counts then), and waits under
a second are hiccups. After that, trouble is 4 stalls within 3 minutes, 20
seconds of them in all, or one of 20 seconds; or frames the device couldn't
draw in time, through most of a minute.

Then short tests find where the trouble is:

- **The device.** Frames not drawn in time are the device's.
- **The connection.** For a file not arriving in time, a 3-second connection
  test (`/api/internal/speed-test`) against what the file needs
  (`bitrateKbps` in the play answer) shows whether it's the connection.
- **StationPlay.** A fast connection with the file itself arriving slower
  than it needs (the player's own measure) means it's StationPlay reading
  the file (its disk, or Plex).
- **Anything else.** The tests don't show anything else, and nothing
  switches automatically for it.

Then comes a smaller version of the same title that the device can play,
from where the viewer is, as the Admin chose (`whenSlow`, kept in `meta` as
`app_when_slow`). At home, the app stops and its main button offers it
("Keep watching in 1080p from 42:10"). Away from home, it switches
automatically and says so. Either can be set the other way on the **Access**
tab. With no smaller version, the smaller one is a converted copy with a
picture made to fit the connection (`fit` with `maxKbps`, from 1.24.0: see
Copies), offered or switched to the same way. Only with no copy available
(an app that doesn't take copies, or a file that can't be converted) does
the app pause, explain which in a sentence, and offer Keep watching or Stop.

## Versions

A title Plex has in several versions (4K, 1080p, 480p) is listed once. Its
details list them best first (the biggest picture, HDR before non-HDR, then
the most detail), named plainly ("4K · HDR10", "1080p"), with their format
or Mbps where two would read the same. Playing takes the version asked for,
or else the best one the device can play directly. The play answer lists
them all, with whether this device can play each.

Planned: some Admins keep a separate 4K library. An Admin setting,
**Combine the same title across libraries** (off by default), will list each
title once with its versions from every shared library, matched by Plex's
own IDs. When it's off, each library stands apart, as in Plex. Either way, a
smaller version for keeping up can come from another shared library.

## Progress, resume and watched

`POST /progress` with `{"key", "positionMs", "session", "sequence"}` (every
10 seconds or so while playing, and when stopping), or `{"key", "watched":
true}` (or false) from a menu. Progress is kept in a new table, for each
person (user 0 while signing in is off), the newest 5,000 programs each:

```
progress (user_id, rating_key, show_key, position_ms, duration_ms,
          watched, updated_ms, PRIMARY KEY (user_id, rating_key))
```

- **Watched.** Into an episode's closing credits (Plex's marker), or 90% of
  the way through what plays, whichever comes first. What plays is the
  version playing, with its own length, since versions of a title can
  differ; for a movie in several files, it's all of them. That marks it
  watched and puts its position back to the start. Watched stays watched
  while someone watches it again.
- **Under a minute.** Less than a minute in starts from the beginning next
  time.
- **Up next** for a show is decided in one place (`ondemand.next_up`), the
  same for every app. It comes from the person's progress in the show,
  newest first, setting aside "not watched" marks from a menu:
  - The episode they're partway through (or barely started; a special too).
  - Else, after the last regular episode they finished, the first one after
    it, in order across seasons, that they haven't watched (specials aside,
    and past any in the same file as it).
  - With none, the show is finished and nothing is next, whatever they
    skipped before it.
  - A special they finished is passed over.
  - With nothing yet, the first episode (specials aside, unless there's
    nothing else).
- **The Resume row.** Movies partway through (a minute or more), and each
  show's Up next (not a show finished, or not started), newest first, one
  per show, up to 20, of what that person may see.
- **Episodes in one file** (S01E01-E02). Plex lists each, and each plays the
  file. Where someone is in one, and whether it's watched, is saved for all
  of them (those of its show's episodes StationPlay has at hand, so without
  asking Plex). Up next goes past them all.
- **Reports in order.** An app numbers its reports in each playing
  (`sequence`, from 1.30.0). A report numbered no higher than the newest for
  that playing (still going, or one of the last 200 ended) is late, and
  changes nothing. Without numbers, reports count as they arrive.
- **Bounds.** A position can be from 0 to 7 days. More than 10 minutes past
  the end of what plays (without `session`, its longest version) is
  refused. A little past it counts as the end.
- **Plex.** A report for something playing (`session`) never asks Plex
  anything, since the playing has the program. So reporting every second is
  fine, and a report is kept even while Plex is away.
- **Nothing goes to Plex.** Plex's own watched status is left alone, and
  what's watched in Plex's own players doesn't move anyone's place here
  (decided for 1.21.0, and again for 1.30.0). One Plex account can't stand
  for several people in StationPlay. Sending it to Plex for one chosen
  person is a later option.
- **Removing someone.** Removing a person removes their progress.

## Media and the stations

They're two ways of watching, often by different people. Stations are
lean-back and run on a clock. Media plays from the start, with each person
in their own place. So Media never mentions stations (no "playing now on
station 12" on a show's page), and stations never mention Media. Search is
the only place both appear: what's in the library, and which stations are
airing it right now.

## What stays out

- No preview pictures or chapter pictures (the plan's decision).
- No downloads.
- Nothing is copied from Plex into StationPlay's database but keys (as
  stations already keep).

## Order of work

1. This document.
2. Sharing, the "is it shared?" check, browsing, details, search and
   pictures, with the Plex calls behind `Library`.
3. Play sessions, direct play, progress and the Resume row.
4. The contract (`docs/internal-api.md`) and its tests, the **Access** tab,
   the README; then 1.21.0.
