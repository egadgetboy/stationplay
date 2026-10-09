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
   when it can't, repackaging (the picture kept as it is) before
   converting (1.24.0).
4. **Each person's own place.** Where someone stopped, what they've
   watched, and what's next are kept per StationPlay user.
5. **Lean.** Plex stays the catalog (Phase 3 adds folders). StationPlay
   keeps only who watched what; it copies nothing else from Plex.

## Releases

- **1.21.0:** sharing libraries; browsing, details, search and pictures;
  direct play; progress, resume and watched; the Resume row (then called
  Continue Watching) and recently added. At home, and over a VPN (which
  looks like home).
- **1.22.0:** versions (the best one the device and its connection keep
  up with, one chosen when playing, and a smaller one when playing can't
  keep up); Skip intro and Skip credits for episodes only, where Plex's
  markers fit the file. The apps' own addresses move to `/api/internal`.
- **1.23.0:** Viewing Levels: each person sees only what their level
  allows, in the library as everywhere else (see `docs/users.md`).
- **1.24.0:** copies of what a device can't play as it is, repackaged or
  converted (HLS, with seeking: see Copies), with the sound track chosen,
  subtitles drawn in, a smaller picture made to fit the connection, and
  night mode's sound; browsing narrowed by genre or to what's unwatched, and
  by letter; cast and crew, taglines, and others like a title.
- **1.25.0:** copies converted on the GPU, as stations use it (see Copies).
- **1.27.0:** watching on demand through the public port, while watching
  away from home is on, with the Admin's quality away from home (see Away
  from home); and even sound for a show's episodes (see Even sound).
- **1.30.0:** Media made solid: answers within 8 seconds however Plex is
  (see When Plex is slow or away); lists sorted, paged and searched by
  StationPlay, case and accents aside (see Lists); Up next decided in one
  place, and progress kept in order (see Progress, resume and watched);
  pictures fetched once (ETags); a device playing one program at a time;
  a movie in several files playing its first.
- **Later:** fragmented MP4 copies, so Apple's player can have an HEVC
  picture as it is; a movie in several files played as one.

The `features` an app sees (`GET /api/v1/server`) say what this server
offers where the app is: `library` once a library is shared, at home (and
from 1.27.0, through the public port too while watching away from home is
on); `convert` from 1.24.0, where `library` is; `even-sound` from 1.27.0,
where `library` is, while an Admin has it on.

## Sharing libraries

The Access tab gets **Media in StationPlay's apps** (named for the apps'
Media section from 1.25.0): a checkbox for each Plex library of shows or
movies. None is checked at first. The choice is kept in `meta` as
`app_libraries` (a JSON list of library keys), and changing it is written
to the log. A shared library that's gone from Plex is simply skipped.

Everyone who can use the apps sees the shared libraries (Admins and Users
alike; while signing in is off, anyone on the home network), within their
Viewing Level (from 1.23.0: see `docs/users.md`).

## Is it shared?

Every program, show and movie an app asks about must be in a shared
library. Plex says which library each is in (`librarySectionID`); the
answer is remembered per key (the 5,000 most recent), filled in as browsing
lists things, so checking rarely costs a request. A key that isn't shared,
or that Plex doesn't know, answers 404 with the same sentence either way,
so nothing can be learned by guessing keys.

## When Plex is slow or away

No address for the apps waits long on Plex. Whatever a request asks of the
library (its details, a list, a picture, the episodes of a show) it gets
within 8 seconds of its first ask (`ondemand.LIBRARY_WAIT_S`), or it answers
503, "StationPlay can't reach Plex right now. Try again in a moment.", well
before an app would give up waiting itself. The same goes for Plex saying
something StationPlay can't read (an answer that isn't JSON, or isn't what
Plex says): it's handled as Plex away, never as a 500. A single show or
movie in a list that can't be read is left out of the list, and a field of
the wrong kind (a year that isn't a number, say) is left out of what's
told. What Plex says isn't there (404) answers 404, as anything not shared
does.

What was being fetched isn't thrown away when a request stops waiting: it
carries on, once for everyone who asks for it at the same time, and is kept
as usual, so an app asking again a little later often finds it ready. The
log says the library can't be reached once a minute at most, however many
apps are asking. The libraries themselves are kept a minute, so browsing
asks Plex for them rarely.

## The addresses (all under `/api/internal`, documented in `docs/internal-api.md`)

| Address | What it answers |
|---|---|
| `GET /libraries` | The shared libraries: key, title, kind (`show` or `movie`) |
| `GET /libraries/{key}` | One library's shows or movies, a page at a time (`start`, `size` up to 200), sorted by `title`, `added` (newest first) or `released` (newest first), narrowed by `genre` or `unwatched`, with its genres and where each letter starts |
| `GET /home` | The Resume row for this person, and each shared library's recently added |
| `GET /search?q=` | Shows and movies whose titles have the words in them, across shared libraries, case and accents aside; and stations airing one now |
| `GET /items/{key}` | A show's or movie's or episode's details |
| `GET /items/{key}/episodes?season=` | A show's episodes: one season's, or all of them, a page at a time (`start`, `size` up to 500) |
| `GET /items/{key}/related` | Others like a show or movie: sharing its genres, then the nearest in years |
| `GET /art/{key}?kind=&w=` | A picture: `poster` (2:3), `backdrop` (16:9) or `thumb` (an episode's still) |
| `POST /play` | Starts playing a program: answers how and where |
| `POST /progress` | Where someone is in a program, or marks it watched or not |

## Lists

StationPlay sorts and searches the lists itself, from each library's whole
list of shows or movies, fetched from Plex 500 at a time, all at once after
the first, and kept (`Whole` in `ondemand.py`): as it is for 2 minutes,
then for as long as the library's fingerprint (Plex's times for each
library's changes) says nothing has changed, up to 30 minutes. A genre's
list is fetched as one of its own. At most 8 lists are kept, and 40,000
shows and movies among them; a show's episodes, for its 50 latest shows,
and 40,000 episodes among them.

- **Sorting.** By title: the library's sort title (Plex's leaves out a
  leading "The", "A" or "An"; without one, StationPlay leaves those out),
  case and accents aside, numbers as numbers, "#" (digits, and anything
  but A to Z) first. Newest added, or newest released (those without a
  date last), ties in the order of their titles. Titles alike are in the
  order of their keys, so pages never repeat or skip one, and every letter
  is together, for jumping to it.
- **Paging.** A library's shows or movies, up to 200 a page; a show's
  episodes, up to 500 a page (500 unless asked for fewer, so an app before
  1.30.0 gets a whole season, as before). Search answers up to 50; the
  Resume row and each library's recently added, up to 20; others like a
  title, up to 12.
- **Search.** The words (1 to 100 characters) are found anywhere in a
  title or its sort title, with case, accents ("Amélie" for "Amelie") and
  punctuation set aside, and with spaces left out too ("spiderman" for
  "Spider-Man"). A title that's just the words comes first, then those
  starting with them, then those with a word starting with them, then the
  rest, each in title order; the first 50 that person may see.
- **Large libraries.** With 5,000 movies, 300 shows and 20,000 episodes,
  the first page of a library after it changes takes as long as Plex takes
  for its pages (10 of them, asked at once, 6 at a time); after that, every
  page, sort, filter, letter and search comes from what's kept, in tens of
  milliseconds, without asking Plex (checked by the tests). A page of 200
  is about 35 KB; a show's 500 episodes about 140 KB. Each library's
  recently added is kept a minute, as the home screen is opened often.

A **card** (in lists) is a show's or movie's key, kind, title and year,
with its poster's address and, for a show, how many episodes it has and how
many this person hasn't watched. Text is made plain, as for stations.

Pictures come from Plex, made the size asked for (`w` is rounded up to one
of a few widths so they can be kept: 160, 320, 480, 720, 1280, 1920), and
kept in memory (up to 48 MB; one over 6 MB isn't kept) like the station
editor's posters. They need a sign-in whenever signing in is on, as
everything under `/api/internal` does, so apps send their token with
pictures too.

- **Fetched once.** Each has an ETag (from what's in it) and
  `Cache-Control: private, max-age=86400`: an app keeps it a day, then asks
  with `If-None-Match`, and while it's the same it's told so (304), with
  nothing sent. Who may see it is checked first, every time.
- **Never a hang.** A picture the library says it hasn't got (no poster,
  no backdrop) is 404 without asking Plex; one Plex hasn't got, or answers
  with something that isn't a picture (an image's type, not empty, at most
  20 MB), is 404 too; Plex not sending it in time is 503, as for the rest
  of the library (8 seconds). At most 8 are asked of Plex at once (an app
  scrolling a grid of posters asks for many), the rest waiting their turn
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

The server decides from Plex's description of the file (its container,
each stream's codec, size, bit depth, HDR kind and Dolby Vision profile),
never from guesses:

- **Direct play** when the device lists the container, the video's codec
  at its size and bit depth, its HDR kind (Dolby Vision profile 5 needs
  `dv`; profiles 7 and 8 play as HDR10), and the default audio track's
  codec. An HDR file on a device without HDR needs converting, since
  playing it as it is would look washed out.
- Otherwise it needs a copy (see Copies), for an app that takes one
  (`device.hls`). For an app that doesn't, or when no copy would show it
  right, it answers 422 with a sentence saying why, such as "This device
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
| `subtitles` | The subtitle tracks; ones in separate files have a `url` to load beside the video |

A device plays one program at a time: starting one ends what it was
playing (its addresses answer 404, a copy being made for it stops, and the
log says it stopped, unless it's the same program again: another sound
track, or a smaller version). A device is an app's sign-in, or while
signing in is off, its address. Every refusal is a status with `detail`, a
sentence the apps show as it is.

A movie in several files (Plex's stacked parts) plays its first file, as it
is or as a copy, and the log says so; its length, for watched, is that
file's. Playing the parts one after another as one is left for later: it
would take a copy for every device, and a new way of making copies, where
playing the first file as it is is sure.

`/play/<session>/…` addresses need no sign-in (a player can't sign in):
the session ID, 32 random characters (192 bits, from `secrets`), is what
lets the player in, as the `/hls/k/` keys do. The file comes from where
StationPlay reads it for stations: straight from disk when it can see it,
otherwise from Plex. Range requests are answered either way, so players
seek freely. `POST /play/<session>/leave` ends a session (the app stopped
playing); a session also ends 4 hours after it was last used, when its
sign-in ends, when its library is no longer shared, and when StationPlay
restarts. Through the public port, only a session started there is offered
(see Away from home).

A session counts as a device watching, for the Admin's limits (see
`capacity.py`), from its start until 3 minutes after it was last heard from
(a file request or a progress report). One more device than the limits
allow is answered 503 with `limit` and `most`, as for stations.

## Away from home

From 1.27.0, while an Admin has watching away from home on (on the Access
tab, with the address the apps use from outside: see `away.py`), the apps
get Media through the public port too (a VPN looks like home, so nothing
changes there). A signed-in app does there whatever it may at home:
browsing, details, search, pictures, progress and playing, as it is or as a
copy, within the same Viewing Levels and limits. With watching away from
home off, the library's addresses answer 403 there, and `features` doesn't
list `library`.

- **Play addresses.** On the public port, `/play/<session>/…` is offered
  only for a session that's going, which a signed-in app started through
  the public port, while watching away from home is on, and only over HTTPS
  (as everything for the apps is there). Its sign-in is checked each time
  it's asked for there (at home, every minute), so it stops the moment the
  sign-in ends; turning watching away from home off ends every session
  started there. Anything else (a guessed address, one started at home, or
  one that has ended) is answered 404. Only a session started there that's
  still going gets past the Gate (`access.Access.play_outside`); the Gate
  answers the rest itself, before anything else sees them.
- **Quality away from home** (an Admin's setting, kept with watching away
  from home): **Original** plays each title as it would at home; **Up to**
  1 to 200 Mbps plays a version within it as it would at home (the best the
  device plays as it is, as at home), and with none within it, converts one
  down to fit: a converted copy whose picture and sound need no more than
  the cap (as `fit` makes one for a connection, without its headroom). Any
  copy converted away from home stays within it. An app that doesn't take
  copies is told why it can't play one over it (422). What a version needs
  is Plex's bitrate, or else its size over its length; one whose need isn't
  known isn't held against it. The apps' own "can't keep up" still works on
  top of it. The Access tab shows, beside it, the upload StationPlay's apps
  measured with their connection tests from outside, as a guide.
- **Limits.** A device playing through the public port is counted by its
  app's own key (as its stations are: apps behind one reverse proxy are
  told apart), against the Admin's limit on devices away from home as well
  as the overall one. Copies converted away from home count toward the
  copies converted at once, with those at home.
- **Logs and Stats** say "away from home" for these plays, as for stations,
  and the access log notes each one started there.
- **Checking the address** (`reach.py`): Media goes through the same proxy,
  to the same port, over HTTPS, as stations do, so a Ready check covers it,
  and says so while a library is shared.

## Copies

A device that can't play a file as it is gets a copy StationPlay makes as
it's played (`converting.py`): HLS, its playlist listing the whole program
from its start in pieces of about 6 seconds, so the player shows the whole
length and seeks anywhere. The pieces are made as they're asked for, by one
ffmpeg from where the player is (again from wherever it jumps to), a few
pieces ahead of the player and no further, and deleted behind it and when
the session ends; ffmpeg stops when nothing has asked for two minutes, and
the pieces made are deleted when nothing has asked for ten (an app gone
without leaving: they're made again if it comes back), checked every
minute. The session itself ends after 4 hours unused.

- **Repackaged** when the device plays the picture as it is and the pieces
  can carry it (H.264; HEVC for a player that takes HEVC in MPEG-TS
  pieces): the picture is copied, costing next to nothing, and the sound
  converted if the device can't play it (AAC, or Dolby Digital 5.1 where
  the device plays it and the sound has more than two channels). Each
  piece starts at one of the picture's keyframes, read up front from the
  file's own index (a Matroska file's Cues, an MP4's sample tables:
  `keyframes.py`), without reading the file; a file without one is
  converted.
- **Converted** otherwise, and for subtitles drawn in or a smaller picture:
  H.264 at most 1080p (or what fits the connection), an HDR picture made
  ordinary as the stations do it, a keyframe at the start of each piece.
  At most 3 at once, or 6 on a GPU.
- **On the GPU** (1.25.0): while the stations' GPU is in use (VA-API or
  NVENC, proven by its test at startup), a converted copy is made there,
  set up as the stations' programs are (the GPU decodes the file too, where
  it can) and encoded with their settings but for three: the copy's own
  bitrate, the level its size and frame rate need, and keyframes as often
  as libx264 makes them. Scaling, making the picture ordinary and drawing
  in subtitles stay on the processor, as for the stations; then the
  picture goes up to the GPU. A copy converted there is light on the
  processor. Each piece still starts with an IDR keyframe exactly where the
  playlist says, and there are no B-frames.
- **The processor behind it.** If a copy goes wrong on the GPU (ffmpeg stops
  with an error or writes nothing, a piece doesn't start with a keyframe
  where it should, or nothing comes for a minute), it carries on from where
  it was on the processor, and stays there. The viewer sees no more than
  the usual wait, and it isn't counted against the copy. Once the
  processor makes the piece the GPU failed at, that's a strike against the
  GPU for copies (a stall isn't: a slow disk stalls too), and a copy made
  fine on the GPU throughout clears them. After 3 strikes in a row, copies
  are converted on the processor until StationPlay restarts; the stations
  keep the GPU, since a copy's trouble there (a GPU out of encoding
  sessions, say) says nothing about theirs. While the GPU is being tested
  at startup, or once it's turned off, copies are converted on the
  processor.
- ffmpeg writes one MPEG-TS stream with the program's own times (moved on
  10 seconds), and StationPlay cuts it into the pieces itself at their
  keyframes, so pieces made by different runs line up exactly.
- Subtitles drawn in: a picture track (PGS, VobSub) laid over the picture;
  text in the file read out into a file of its own first, once (as the
  stations do); a subtitle file of its own fetched first.

## Even sound

From 1.27.0, every episode played on demand comes at the loudness the
stations' episodes have (`ffmpeg.LOUDNESS_TARGET`, -24 LUFS, with ffmpeg's
loudnorm in one pass), so all of a show's episodes match, in order or
shuffled, in any app. Movies are never touched, as on the stations. On to
start: an Admin can turn **Even sound for a show's episodes** off on the
Access tab's Media panel (kept in `meta` as `app_even_sound`).

- **How.** As night mode's sound is made for an app that can't make it: a
  copy that keeps the picture as it is and makes only the sound
  (repackaged), for an app that takes copies (`device.hls`). Its sound is
  what the device would get anyway (`converting.sound_for`), made again
  rather than copied: Dolby Digital 5.1 where the device plays it and the
  sound has more than two channels, otherwise AAC stereo. Even sound comes
  first in its filters; with night mode too, night mode's after it, so its
  compressing starts from the same loudness in every episode and its
  limiter is last.
- **Never a picture made again for it.** Where the picture can't be kept as
  it is (a picture the copy's pieces can't carry for that player, or a file
  without an index to cut it by), an episode the device plays as it is
  plays as it is. A copy made for another reason (converted, a smaller
  picture, subtitles drawn in, night mode) has even sound too.
- **The cost.** The episode's sound is made again, so sound sent as it is to
  a receiver (Dolby Atmos, DTS) comes as ordinary 5.1 or stereo. Hence the
  switch.
- **The apps.** `features` lists `even-sound` while it's on, and a copy's
  `why` says "even sound for the show's episodes", for the player's info.
  An app that doesn't send `device.hls` (older apps) gets the file as
  before.

## Skip intro and Skip credits

For episodes only. Plex finds an episode's intro by matching it across a
season, and its closing credits as they start; movies are made too many
ways (credits over the final scene, scenes between the credits) for a
button to be trusted, so they have none. A button in the wrong place is
worse than none, so an episode's markers are used only where they fit its
file (`plex._skips`), by the rules stations use (`markers.py`) and these:

- A marker ending past the end of the file, or ending before it starts,
  means Plex's markers don't fit this file (they were found in another, since
  replaced): none are used.
- Nor are they for an episode with versions of different lengths (over a
  second apart): Plex finds markers in one, and the others may not line up.
- The intro starts in the first half and runs under five minutes; it must
  end before the credits start (otherwise neither is used) and at least a
  minute before the end. The credits start in the second half: the ones
  Plex says are final, or else the last.
- A scrap of under five seconds before the intro, or after the credits,
  goes with it. Skip intro shows from the very start, and Skip credits goes
  on to the next episode rather than a second of black (`creditsToEnd`).

The apps offer the buttons: nothing is skipped unless the viewer presses
one (skipping without asking is planned as a setting, off at first). A
button shows while the player is inside its part (again if the viewer goes
back into it), and lands exactly at its end; Skip credits with
`creditsToEnd` goes on to the next episode, or finishes the show.

## Keeping up

Playing a file should be steady before it's anything else. The apps buffer
the way players do for a file first: well ahead (the Android app up to 90
seconds, within its memory budget), and after a stall, a good 8 seconds
before carrying on, so a slow patch is one pause rather than many. Waits
after a seek, or before the first picture, aren't stalls.

Only trouble that lasts counts. The first 45 seconds are the buffer's and
the decoder's (only a single 20-second stall counts then), and waits under
a second are hiccups. After that: 4 stalls within 3 minutes, 20 seconds of
them in all, or one of 20 seconds; or frames the device couldn't draw in
time, through most of a minute. Then short tests say where the trouble is:
frames not drawn in time are the device's; for a file not arriving in time,
a 3-second connection test (`/api/internal/speed-test`) against what the file
needs (`bitrateKbps` in the play answer) says whether it's the connection;
a fast connection with the file itself arriving slower than it needs (the
player's own measure) says it's StationPlay reading the file (its disk, or
Plex). Anything else the tests don't show, and nothing is switched on its
own for it.

Then a smaller version of the same title that the device can play, from
where the viewer is, as the Admin chose (`whenSlow`, kept in `meta` as
`app_when_slow`): at home, the app stops and its main button offers it
("Keep watching in 1080p from 42:10"); away from home, it switches on its
own and says so. Each can be turned the other way on the Access tab. With
no smaller version, the app pauses, says which it is in a sentence, and
offers Keep watching or Stop (later, a converted copy).

## Versions

A title Plex has in several versions (4K, 1080p, 480p) is listed once. Its
details list them the best first (the biggest picture, HDR before not, then
the most detail), named plainly ("4K · HDR10", "1080p"; their format or
Mbps where two would read the same). Playing takes the version asked for,
or else the best the device can play as it is; the play answer lists them
all with whether this device can play each.

Planned: some Admins keep a separate 4K library. An Admin setting, **Combine
the same title across libraries** (off at first), will list each title once
with its versions from every shared library, matched by Plex's own IDs;
off, each library stands apart, as in Plex. Either way, a smaller version
for keeping up can come from another shared library.

## Progress, resume and watched

`POST /progress` with `{"key", "positionMs", "session", "sequence"}` (every
10 seconds or so while playing, and when stopping), or `{"key", "watched":
true}` (or false) from a menu. Kept in a new table, per StationPlay user
(user 0 while signing in is off), the newest 5,000 programs each:

```
progress (user_id, rating_key, show_key, position_ms, duration_ms,
          watched, updated_ms, PRIMARY KEY (user_id, rating_key))
```

- **Watched**: into an episode's closing credits (Plex's marker), or 90%
  of the way through what plays (the version playing: its own length, as
  versions of a title can differ; a movie in several files plays its first,
  so it's that file's), whichever comes first. That marks it watched and
  puts its position back to the start. Watched stays watched while someone
  watches it again.
- Less than a minute in starts from the beginning next time.
- **Up next** for a show is decided in one place (`ondemand.next_up`), the
  same for every app, from someone's progress in the show, newest first,
  menu marks of "not watched" aside: the episode they're partway through
  (or barely started; a special too); else after the last regular episode
  they finished, the first one after it, in order across seasons, that they
  haven't watched (specials aside, and past any in the same file as it);
  none, and the show is finished, nothing next, whatever they skipped
  before it; a special they finished is passed over; with nothing yet, the
  first episode (specials aside, unless there's nothing else).
- **The Resume row**: movies partway through (a minute or more), and each
  show's Up next (not a show finished, or not started), newest first, one
  per show, up to 20, of what that person may see.
- **Episodes in one file** (S01E01-E02): Plex lists each, and each plays
  the file. Where someone is in one, and whether it's watched, is saved for
  all of them (those of its show's episodes StationPlay has at hand, so
  without asking Plex), and Up next goes past them all.
- **Reports in order.** An app numbers its reports in each playing
  (`sequence`, from 1.30.0); one numbered no higher than the newest for
  that playing (still going, or one of the last 200 ended) is late, and
  changes nothing. Without numbers, they count as they arrive.
- **Bounds.** A position from 0 to 7 days; more than 10 minutes past the
  end of what plays is refused, a little past it is the end.
- **Plex.** A report for something playing (`session`) never asks Plex
  anything (the playing has the program), so reporting every second is
  fine, and is kept even while Plex is away. Nothing is sent to Plex:
  Plex's own watched status is left alone, and what's watched in Plex's own
  players doesn't move anyone's place here (decided for 1.21.0, and again
  for 1.30.0): one Plex account can't stand for several StationPlay users.
  Sending it to Plex for one chosen person is a later option.
- Removing a user removes their progress.

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
3. Play sessions, direct play, progress and the Resume row.
4. The contract (`docs/internal-api.md`) and its tests, the Access tab, the
   README; then 1.21.0.
