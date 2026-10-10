# Who sees what: users, Viewing Levels and devices (design)

StationPlay already has users: an Admin adds them on the Access tab, each
signs in with a name and password, and the apps link with a code. This adds
what each user may **see**, and a way for a household to share one TV or
tablet: a **Who's tuning in?** picker, with optional passcodes. All of it is
decided on the server. The apps show only what the server sends.

## Goals

1. **Off until it's used.** A StationPlay with one user, or none, works
   exactly as it does today. Viewing Levels, passcodes and the picker
   appear only once there's a second user.
2. **Nothing leaks.** What a user can't see isn't in any list, search, guide,
   Resume row or "on now" for them: no title, no picture, no placeholder. A
   key or address for it is refused with the same answer as one that
   doesn't exist.
3. **Stations are all or nothing.** A station is one stream that everyone
   watching it shares, so it can't change for each person. A user sees a
   station only if everything on it is within their limits, or an Admin
   allowed that station for them.
4. **Plain rules, in order.** The first rule that applies decides, so an
   Admin can always tell why something is hidden.
5. **Lean.** Plex stays the catalog. StationPlay keeps a title's rating and
   library only where its stations need them.

## Phases

- **Phase 1:** Viewing Levels (rating and libraries), per-user station
  allow and block, enforced everywhere; linked devices, the picker,
  passcodes, invite codes and "Show on"; Users can be watch-only.
- **Phase 2:** genre, tag, title and collection rules; rating overrides;
  per-user title exceptions; Station Audience warnings; Preview as user;
  Why is this hidden.
- **Phase 3:** the Manager role, Lock to user, one person linked to users
  on several servers, and several tuner lineups for Plex.

## Roles

Admin and User stay as they are. A User can make stations up to the limit
an Admin sets, and **None** is added to that limit: a User with None only
watches. (Manager comes in Phase 3.)

## Names

From 1.27.0, an Admin can rename anyone on the Access tab, themselves and
other Admins too, with the rules a new name has (up to 40 letters, numbers,
spaces and `. _ - @`, and no one else's, whatever its case). Signing in
takes the new name from then on. Everything of a person's is kept by their
id, never their name, so it stays theirs: their sign-ins (the page's and
the apps'), linked devices (who linked one is kept by id too, so an Admin
given a removed person's name never has their device for their own),
stations, Viewing Level, progress and stats (the stats and the Access tab
show the new name, even for viewing counted after, from a play that began
before). The access log says "<Admin> renamed <old> to <new>". The apps
show the new name the next time they ask: Who's tuning in? lists it, and
`GET /api/internal/me` says who an app is signed in as, for its Options.

## Viewing Levels

A Viewing Level says what its users can see. Every user has one; Admins
see everything whatever their level says.

| Level | Movies up to | TV up to | Unrated |
|---|---|---|---|
| Unrestricted | No limit | No limit | Shown |
| Teen | PG-13 | TV-14 | Hidden |
| Kid | PG | TV-PG | Hidden |
| Young Child | G | TV-G | Hidden |

**Unrestricted** is always there and stays as it is. Teen, Kid and Young
Child are made once, the first time, to start from: an Admin can rename
them, change them (a change applies to everyone on that level at once) or
remove them, as they can the levels they add, as many as they need, such
as "Adults" (no R-rated movies, no unrated titles) or "Grandparents". A level also says which **libraries** its users can see:
all of them, or the ones chosen. That's how a show that's in both "TV
Parents" and "TV Teens" is seen only through the library a user may see.

New users start on Unrestricted, so adding a user changes nothing until an
Admin chooses a level.

### Ratings as ages

Every rating is read as the youngest age it suits:

| Age | Ratings |
|---|---|
| 0 | G, TV-Y, TV-G |
| 7 | TV-Y7, TV-Y7-FV |
| 10 | PG, TV-PG |
| 13 | PG-13 |
| 14 | TV-14 |
| 17 | R, TV-MA |
| 18 | NC-17 |

Other countries' ratings (Plex writes them as `gb/15`, `de/12`, `au/MA15+`
and so on) are read the same way, by the age they name. Anything else
(`NR`, `Not Rated`, blank, an unknown code) is **unrated**. A level's limits
are kept as ages; the page shows them as the US rating with that age.

An episode is judged by its show's rating, or its own if that's stricter.
Rating overrides (Phase 2) are StationPlay's own and never change Plex.

## The rules, in order

For a user and a show, movie or episode (Phase 1 has 1, 4, 5 and 7):

1. An Admin sees everything.
2. A title blocked for this user is hidden. *(Phase 2)*
3. A title allowed for this user is shown, whatever its rating, genre or
   tags, but not if its library is hidden. *(Phase 2)*
4. A title in a library their level doesn't include is hidden.
5. A title rated above their level's age is hidden; an unrated one follows
   the level.
6. A blocked genre, tag or collection hides a title. *(Phase 2)*
7. Anything else is shown.

For a station: a station **allowed** for the user is shown; one **blocked**
for them is hidden; otherwise it's shown only if every program it plays
passes the rules above. "Every program" is what its current lineup holds,
its specials' programs included. Station numbers don't change when some are
hidden.

## What StationPlay keeps

- **`titles`**: for each show and movie on a station: its key, kind,
  rating as Plex has it, that rating's age (or none), and its library.
  Filled in as a station's lineup is made (Plex sends these with the
  items), and once at start-up for lineups made before this existed. An
  episode's own rating is kept in its lineup row when Plex gives one.
- **Each station's reach**: the oldest age and the libraries its programs
  need, and whether any is unrated. Worked out when its lineup changes,
  so deciding whether a user sees a station is a few comparisons.
- **`levels`**: name, movie age, TV age, unrated shown or not, libraries
  (all, or a list).
- **`users`** gains: level, passcode (`pin`: a hash, or none), whether they
  chose to have no passcode, Show on (see below), and whether they may
  change their own password. A User may have no password: they use only the
  pickers.
- **`user_stations`**: a station allowed or blocked for a user.
- **`linked_devices`**, **`device_people`** and **`invites`**: the linked
  devices (by a hash of each one's key, with who linked each, by id and by
  name), who's on each picker other than as Show on says (signed in there,
  chosen by an Admin, or taken off), and each person's invite code (a
  hash), while it lasts.

The library in the apps (browsing, search, details, pictures, playing)
already asks Plex about each title, which sends its rating and library, so
it's judged from what Plex sent, with no copy kept.

## Devices and the picker

A **device** is one install of a StationPlay app (a TV, a phone, a tablet),
linked to the server once, with a code entered on StationPlay's page or by
signing in. It gets a long-lived **device token**, which an Admin can see
and revoke on the Access tab (revoked: it's signed out on its next request).
The person using it at the moment gets a short-lived **session** for one
user, made by picking that user.

**Who's tuning in?** shows on a device's start when more than one user can
use it. Who's on it is each user's **Show on**, and where the device is:
**at home** (its picker is asked on the home port, which a VPN reaches too)
or **away from home** (the public port):

- **Only devices they sign in on:** on no picker until that person signs
  in on a device; then on that device's picker, at home and away. Unless
  Bo has signed in on Ada's TV, he isn't on its picker, and she isn't on
  his phone's.
- **Every device at home:** on every linked device's picker while it's at
  home. Away from home, only on a device they signed in on themselves, or
  one an Admin chose for them. Suits a household.
- **Every device, at home and away:** on every linked device's picker, at
  home and away: a device away from home (a phone at a friend's) shows
  their name too.
- **Only devices you choose:** only on the devices an Admin picks, at home
  and away, such as the Kids' Tablet, or a family iPad that travels.

New users start where **New people show on**, beside the linked devices,
says when they're added: Only devices they sign in on, or Every device at
home. From 1.30.1, it's Only devices they sign in on, unless an Admin
chose otherwise before, which stays as they chose it. Someone who can't
sign in by name (no password and no passcode) starts on Every device at
home instead, rather than on no device at all. Changing it doesn't move
anyone already added. **Use for everyone**, beside it, does: after a
confirm that says how many it changes, everyone already added shows that
way too (and anyone added later). For Only devices they sign in on,
someone who can't sign in by name is kept as they were, and the page names
them ("Kept as they were: Kids (no password or passcode)"); and as picking
yourself from a picker isn't signing in on its device, the others are on a
device they used that way again once they sign in on it (the confirm says
so). The devices an Admin chose for someone stay chosen. The access log
says "<Admin> set everyone to show on <choice>: <n> people changed", and
who was kept.

In 1.28.0, everyone on All devices (the household's default until then,
which everyone added before there were pickers was on too) moved to Devices
at home, once, and so did the server's default; the access log says how
many people moved. 1.30.1 renamed the four, in fewer words: Devices at home
is Every device at home, All devices is Every device, at home and away,
Selected devices is Only devices you choose, and Only where signed in is
Only devices they sign in on. (What the API sends, `home`, `all`,
`selected` and `signed-in`, is as it was.)

The picker always has **Sign in**: the person enters their name and, the
first time on that device, their invite code or password; after that they
switch with their passcode. Each person can **Remove me from this device**.

Safety rules:

- A user with neither a password nor a passcode (a "Kids" user, say) can be
  **Every device at home** or **Only devices you choose** only, never
  signed in by name, so no one can get in from anywhere by guessing a name
  like "Kids", and no device away from home lists them unless an Admin
  chose it. (A user with a password signs in with it, on the page or in an
  app, as today.)
- The first sign-in on a device takes an invite code or a password, never
  just a passcode. An **invite code** is made by an Admin for one user,
  works once, and expires after 7 days.
- An Admin always needs their passcode (or password) on a picker.
- Passcodes are 4 digits, kept as hashes. 5 wrong passcodes for a user
  means a 15-minute wait for that user, on every device.
- The picker exists only on a device already linked. A stranger who
  installs an app never sees a name.
- Away from home, picking someone a device doesn't list there is refused,
  as for someone not on it at all.

### A passcode after the first sign-in

From 1.28.0, once someone has signed in with their password or an invite
code, later sign-ins are open, or locked with a 4-digit passcode if they
choose. The first time they sign in on a device that
way (in an app, by name, or with a code entered on StationPlay's page),
the app asks them to choose a passcode, or No passcode, unless they have one
or already said they want none. Either answer holds on every device, and
they can change it in the app's Options. A household's adults, teens, kids
and little kids can each have one or not.

- A sign-in made with their password, an invite code or their passcode
  says it's them, so choosing a new passcode needs nothing more. One made
  by picking them without a passcode doesn't, as anyone at that device
  could have: it can't set one for them, and lock them out (1.28.1). They
  sign in with their password or an invite code to set one.
- An Admin who has one keeps it: an Admin needs a passcode, or their
  password on a device others use too. (An Admin with none who chooses No
  passcode gives their password there, as before.)
- Someone without a password keeps theirs: it's how they sign in.
- Someone with neither (a "Kids" user) is never asked: they never sign in
  by name, and only an Admin gives them a passcode.
- Wrong passcodes still count after a new one is chosen. An Admin still
  sets or removes anyone's passcode on the Access tab.
- The access log says "<name> set a passcode" or "<name> chose no
  passcode", and in which app.

### Changing your password in the apps

From 1.28.0, people change their own password in the apps' Options, as on
StationPlay's page (their name at the top), with their current one: the
same length, the same limits on wrong ones (5 from one address in 15
minutes, then a wait), and every other sign-in of theirs ends, as on the
page, while the app they changed it in stays signed in. The access log says
"<name> changed their password in <the app, on the device>".

- **Can change their own password** is an Admin's choice for each person
  on the Access tab, beside their New password: on to start with, for
  everyone already added too. When it's off, both the page's change and
  the apps' are refused with a plain sentence, and `GET /api/internal/me`
  says so (`canChangePassword: false`). An Admin can always change their
  own.
- Someone without a password (a passcode-only person, or "Kids") can't set
  one this way: an Admin gives them one, or an invite code.

### Reporting problems from the apps

From 1.30.0, people report a problem with what they watch from the apps,
picked from a list (see "Reporting a problem" in `docs/internal-api.md`):
each report goes to the Broken files tab, for an Admin, saying who sent it
and from which device, as their sign-in says.

- **Can report problems** is an Admin's choice for each person, on the
  Access tab beside Can change their own password (and on the Broken files
  tab, beside Sonarr's and Radarr's settings): on to start with, for
  everyone already added too. When it's off, a report is refused with a
  plain sentence ("An Admin has turned off reporting problems for you."),
  and `GET /api/internal/me` says so (`canReport: false`), so the app
  doesn't offer it. An Admin can always report.
- Only what someone may see can be reported: an episode or a movie their
  Viewing Level hides, or a station it hides (or an Admin blocked for
  them), is answered as though it weren't there (404).
- One report a day about each program, and ten a day in all, for each
  person; while signing in is off, for each address.

## The addresses

The apps' own (`docs/internal-api.md`): `"picker": true` on signing in or
asking for a code links the device and returns its `deviceKey`;
`GET /api/internal/picker`, `POST /api/internal/picker/choose`,
`POST /api/internal/picker/sign-in` and `POST /api/internal/picker/remove`
are asked with the key, in the `StationPlay-Device` header. Signing in
answers `askPin`, `POST /api/internal/pin` sets someone's own passcode,
`POST /api/internal/password` changes their own password (1.28.0), and
`POST /api/internal/report-problem` sends a report (1.30.0). The
Access tab's: `/api/access/viewing`, `/api/access/levels`,
`/api/access/users/{id}/viewing` and `/stations`, `/api/access/devices`
(with `PUT /api/access/devices/default` for New people show on, and
`POST /api/access/devices/everyone`), `/api/access/users/{id}/picker` and
`/invite`. Like everything on the Access tab, they're for Admins only, and
a change sent from another site's page is refused.

`POST /api/access/devices/everyone` (1.30.1) is Use for everyone. It takes
`{"showOn": "signed-in"}` (Only devices they sign in on) or
`{"showOn": "home"}` (Every device at home), and anything else is refused
(400) with nothing changed. It sets New people show on to that, and
everyone already added, but for who can't sign in by name, for
`signed-in`; then answers what it did, and says so in the access log:

| Field | Type | What it is |
|---|---|---|
| `default` | string | New people show on, now |
| `changed` | number | How many people it changed |
| `kept` | list | The names of who it kept as they were (no password or passcode) |

## Streams

The apps play stations from addresses that carry a key made for that
session, checked on every request, and ended when the session ends. A key
works only for the stations its user can see. Programs from the library
already play from addresses made per play, checked the same way.

What Plex, Jellyfin and IPTV apps use (the tuner, its guide, its streams)
carries no user, so limits can't apply there. The Access tab says so
plainly. (Phase 3 may offer several tuner lineups, each with its own
stations.)

## The apps

- The picker on start, a passcode pad, Sign in, and Remove me from this
  device.
- Whatever the server sends is what's shown; nothing is filtered on the
  device.
- The free app's one station stays the **server's first station**, never
  the first one a user can see; if the user can't see it, the app says so
  and offers the unlock.

## Tests that must pass

- A Kid never sees a TV-MA title in any list, search, guide, Resume row or
  "on now", and its key and stream address are refused.
- A station with one program above a user's level is hidden from them,
  unless an Admin allows that station for them.
- A User can't make an Admin, or change their own level.
- A first Admin can't be added from the internet (as today).
- A revoked device is signed out on its next request.
- A user with neither a password nor a passcode can't sign in by name.
- Five wrong passcodes lock that user for 15 minutes, on every device.
- A StationPlay with one user, or none, answers exactly as before.
