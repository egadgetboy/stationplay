# Who sees what: people, Viewing Levels and devices (design)

This design covers what each person may **see**, and how a household shares
one TV or tablet. An Admin already adds people on the **Access** tab. Each
person signs in with a name and password, and the apps link with a code.
This design adds limits on what each person sees, and a **Who's tuning
in?** screen with optional PINs. The server decides everything. The
apps show only what the server sends.

## Goals

1. **Off until it's used.** A StationPlay with one person, or none, works
   exactly as it always has. Viewing Levels, PINs and Who's tuning in?
   appear only once there's a second person.
2. **Nothing leaks.** Anything a person can't see is missing from every
   list, search, guide, Resume row and "on now" for them. There's no title,
   no picture and no placeholder. A request for its key or address gets the
   same answer as one that doesn't exist.
3. **Stations are all or nothing.** Everyone watching a station shares one
   stream, so a station can't change for each person. A person sees a
   station only if everything on it is within their limits, or an Admin
   allowed that station for them.
4. **Plain rules, in order.** The first rule that applies decides, so an
   Admin can always tell why something is hidden.
5. **Lean.** Plex stays the catalog. StationPlay keeps a title's rating and
   library only where its stations need them.

## Phases

- **Phase 1.** Viewing Levels (rating and libraries), and stations allowed
  or blocked for each person, enforced everywhere. Linked devices, Who's
  tuning in?, PINs, invite codes and "Show on." Users can be
  watch-only.
- **Phase 2.** Genre, tag, title and collection rules; rating overrides;
  title exceptions for each person; Station Audience warnings; Preview as
  user; Why is this hidden.
- **Phase 3.** The Manager role, Lock to user, one person linked to
  accounts on several servers, and several tuner lineups for Plex.

## Roles

The Admin and User roles don't change. A User can make stations up to the
limit an Admin sets, and this design adds **None** to that limit: a User
with None only watches. (Manager comes in Phase 3.)

## Names

From 1.27.0, an Admin can rename anyone on the **Access** tab, including
themselves and other Admins. A new name follows the usual rules: up to 40
letters, numbers, spaces and `. _ - @`, and not someone else's name in any
case. From then on, the person signs in with the new name.

StationPlay keeps everything of a person's by their ID, never their name, so
it all stays theirs after a rename: their sign-ins (on StationPlay's page
and in the apps), linked devices, stations, Viewing Level, progress and
stats. Who linked a device is kept by ID too, so an Admin given a removed
person's name never gets that person's devices. The stats and the **Access**
tab show the new name, even for viewing counted after the rename from a play
that began before it.

The access log shows "<Admin> renamed <old> to <new>." The apps show the new
name the next time they ask. Who's tuning in? lists it, and
`GET /api/internal/me` reports who an app is signed in as, for its Options.

## Viewing Levels

A Viewing Level sets what its people can see. Everyone has one. Admins see
everything, whatever their level.

| Level | Movies up to | TV up to | Unrated |
|---|---|---|---|
| Unrestricted | No limit | No limit | Shown |
| Teen | PG-13 | TV-14 | Hidden |
| Kid | PG | TV-PG | Hidden |
| Young Child | G | TV-G | Hidden |

**Unrestricted** always exists and never changes. StationPlay creates Teen,
Kid and Young Child once, as a starting point. An Admin can rename, change
or remove them, like any level they add. A change applies at once to
everyone on that level. An Admin can add as many levels as they need, such
as "Adults" (no R-rated movies, no unrated titles) or "Grandparents."

A level also sets which **libraries** its people can see: all of them, or
the ones chosen. So a show that's in both "TV Parents" and "TV Teens" is
seen only through a library the person may see.

New people start on Unrestricted, so adding someone changes nothing until an
Admin chooses a level.

### Ratings as ages

StationPlay reads every rating as the youngest age it suits:

| Age | Ratings |
|---|---|
| 0 | G, TV-Y, TV-G |
| 7 | TV-Y7, TV-Y7-FV |
| 10 | PG, TV-PG |
| 13 | PG-13 |
| 14 | TV-14 |
| 17 | R, TV-MA |
| 18 | NC-17 |

Other countries' ratings are read the same way, by the age they name. Plex
writes them as `gb/15`, `de/12`, `au/MA15+` and so on. Anything else (`NR`,
`Not Rated`, blank or an unknown code) is **unrated**. A level stores its
limits as ages, and StationPlay's page shows each one as the US rating for
that age.

An episode uses its show's rating, or its own if that's stricter. Rating
overrides (Phase 2) belong to StationPlay and never change Plex.

## The rules, in order

For a person and a show, movie or episode, the first rule that applies
decides. Phase 1 has rules 1, 4, 5 and 7.

1. An Admin sees everything.
2. A title blocked for this person is hidden. *(Phase 2)*
3. A title allowed for this person is shown, whatever its rating, genre or
   tags, unless its library is hidden. *(Phase 2)*
4. A title in a library their level doesn't include is hidden.
5. A title rated above their level's age is hidden. An unrated title follows
   the level's setting.
6. A blocked genre, tag or collection hides a title. *(Phase 2)*
7. Anything else is shown.

For a station, a station **allowed** for the person is shown, and one
**blocked** for them is hidden. Otherwise, it's shown only if every program
it plays passes the rules above. "Every program" means everything in its
current lineup, including its specials' programs. Station numbers don't
change when some stations are hidden.

## What StationPlay keeps

- **`titles`.** A row for each show and movie on a station: its key, kind,
  rating as Plex has it, that rating's age (or none) and its library.
  StationPlay fills it in as it makes a station's lineup, since Plex sends
  these with the items. It also fills it once at startup for lineups made
  before this existed. An episode's own rating is kept in its lineup row
  when Plex gives one.
- **Each station's reach.** The oldest age and the libraries its programs
  need, and whether any program is unrated. StationPlay works this out when
  the lineup changes, so deciding whether someone sees a station takes only
  a few comparisons.
- **`levels`.** Name, movie age, TV age, whether unrated titles are shown,
  and libraries (all, or a list).
- **`users`.** Gains each person's level, PIN (`pin`: a hash, or
  none), whether they chose to have no PIN, Show on (see below) and
  whether they may change their own password. A User may have no password.
  They use only Who's tuning in?
- **`user_stations`.** A station allowed or blocked for a person.
- **`linked_devices`, `device_people` and `invites`.** The linked devices,
  each by a hash of its key, with who linked it (by ID and by name). Who's
  on each device's Who's tuning in? apart from their Show on setting
  (signed in there, chosen by an Admin, or taken off). Each person's invite
  code (a hash), while it lasts.

Media in the apps (browsing, search, details, pictures and playing) already
asks Plex about each title. Plex sends its rating and library, so
StationPlay judges the title from that and keeps no copy.

## Devices and Who's tuning in?

A **device** is one install of a StationPlay app, on a TV, phone or tablet.
It's linked to the server once, by signing in or with a code entered on
StationPlay's page. It gets a long-lived **device token**, which an Admin
can see and revoke on the **Access** tab. A revoked device is signed out on
its next request. Whoever is using the device gets a short-lived
**session** for one person, made by picking that person.

**Who's tuning in?** shows when the app starts, if more than one person can
use the device. Who appears on it depends on each person's **Show on**
setting and on where the device is. A device is **at home** when it asks
for the list on the home port, which a VPN reaches too. It's **away from
home** on the public port.

- **Only devices they sign in on.** The person appears on no device until
  they sign in on one. Then they appear on that device, at home and away.
  Unless Bo has signed in on Ada's TV, he isn't on its list, and she isn't
  on his phone's.
- **Every device at home.** The person appears on every linked device while
  it's at home. Away from home, they appear only on a device they signed in
  on themselves, or one an Admin chose for them. This suits a household.
- **Every device, at home and away.** The person appears on every linked
  device, wherever it is. A device away from home, such as a phone at a
  friend's house, shows their name too.
- **Only devices you choose.** The person appears only on the devices an
  Admin picks, at home and away, such as the Kids' Tablet or a family iPad
  that travels.

### New people show on

New people start with the **New people show on** setting, next to the linked
devices: Only devices they sign in on, or Every device at home. From 1.30.1,
it's Only devices they sign in on, unless an Admin chose otherwise before;
that choice stays. Someone who can't sign in by name (no password and no
PIN) starts on Every device at home instead, rather than on no device
at all.

Changing the setting doesn't move anyone already added. **Use for
everyone**, next to it, does:

- **A confirm first.** It shows how many people the change affects. Then
  everyone already added shows that way too, as does anyone added later.
- **Some people are kept.** For Only devices they sign in on, anyone who
  can't sign in by name keeps their setting. The page names them: "Kept as
  they were: Kids (no password or PIN)."
- **Picking isn't signing in.** Picking yourself on Who's tuning in? doesn't
  count as signing in on that device. So people appear again on a device
  they used that way once they sign in on it. The confirm says so.
- **Chosen devices stay.** The devices an Admin chose for someone stay
  chosen.
- **It's logged.** The access log shows "<Admin> set everyone to show on
  <choice>: <n> people changed," and who was kept.

### Earlier names

In 1.28.0, everyone on All devices moved once to Devices at home, and so did
the server's default. All devices had been the household's default until
then, and everyone added before Who's tuning in? existed was on it. The
access log shows how many people moved.

1.30.1 renamed the four choices. The values the API sends didn't change.

| Before 1.30.1 | From 1.30.1 | API value |
|---|---|---|
| Devices at home | Every device at home | `home` |
| All devices | Every device, at home and away | `all` |
| Selected devices | Only devices you choose | `selected` |
| Only where signed in | Only devices they sign in on | `signed-in` |

### Signing in and the safety rules

Who's tuning in? always has **Sign in**. The person enters their name and,
the first time on that device, their invite code or password. After that,
they switch with their PIN. Each person can choose **Remove me from
this device**.

- **A name alone never works.** Someone with neither a password nor a
  PIN, such as a "Kids" account, can only be on Every device at home or
  Only devices you choose. They never sign in by name, so no one can get in
  from anywhere by guessing a name like "Kids." No device away from home
  lists them unless an Admin chose it.
- **A password still works.** Someone with a password signs in with it, on
  StationPlay's page or in an app, as before.
- **The first sign-in needs more.** The first sign-in on a device takes an
  invite code or a password, never just a PIN. An Admin makes an
  **invite code** for one person. It works once and expires after 7 days.
- **Admins always unlock.** An Admin always needs their PIN (or
  password) on Who's tuning in?
- **PINs.** A PIN is 4 digits, stored as a hash. After 5 wrong
  PINs, that person waits 15 minutes, on every device.
- **Linked devices only.** Who's tuning in? exists only on a device that's
  already linked. A stranger who installs an app never sees a name.
- **Away from home.** Picking someone the device doesn't list there is
  refused, the same as picking someone who isn't on it at all.

### A PIN after the first sign-in

From 1.28.0, once someone has signed in with their password or an invite
code, later sign-ins are open, or locked with a 4-digit PIN if they
choose. The first time they sign in on a device that way (by name in an
app, or with a code entered on StationPlay's page), the app asks them to
choose a PIN or No PIN. It doesn't ask if they already have one,
or already chose none. Either answer applies on every device, and
they can change it in the app's Options. Everyone in a household, from
adults and teens to kids and little kids, can choose either way.

- **Proof it's them.** A sign-in made with their password, an invite code
  or their PIN proves it's them, so choosing a new PIN needs
  nothing more. Picking them without a PIN doesn't, since anyone at
  that device could have.
- **No lockouts by others.** From 1.28.1, a sign-in made by picking them
  without a PIN can't set one for them and lock them out. They sign in
  with their password or an invite code to set one.
- **Admins keep theirs.** An Admin who has a PIN keeps it, because an
  Admin needs a PIN, or their password on a device others use too. An
  Admin with none who chooses No PIN gives their password there, as
  before.
- **PIN-only people keep it.** Someone without a password keeps their
  PIN, because it's how they sign in.
- **Never asked.** Someone with neither, such as "Kids," is never asked.
  They never sign in by name, and only an Admin gives them a PIN.
- **Wrong tries still count.** Wrong PINs still count after a new one
  is chosen.
- **Admins can still change it.** An Admin can still set or remove anyone's
  PIN on the **Access** tab.
- **It's logged.** The access log shows "<name> set a PIN" or "<name>
  chose no PIN," and in which app.

### Changing your password in the apps

From 1.28.0, people can change their own password in the apps' Options, as
on StationPlay's page (under their name at the top). They need their
current password. The rules match the page: the same length, and the same
limit on wrong passwords (5 from one address in 15 minutes, then a wait).
Every other sign-in of theirs ends, as on the page, but the app they changed
it in stays signed in. The access log shows "<name> changed their password
in <the app, on the device>."

- **Can change their own password.** An Admin sets this for each person on
  the **Access** tab, next to their New password. It's on by default,
  including for everyone already added.
- **When it's off.** StationPlay's page and the apps both refuse the change
  with a plain sentence, and `GET /api/internal/me` reports it
  (`canChangePassword: false`). An Admin can always change their own.
- **No password yet.** Someone without a password, such as a PIN-only
  person or "Kids," can't set one this way. An Admin gives them a password
  or an invite code.

### Reporting problems from the apps

From 1.30.0, people can report a problem with what they're watching from
the apps. They pick it from a list (see "Reporting a problem" in
`docs/internal-api.md`). Each report goes to the **Broken files** tab for an
Admin, showing who sent it and from which device, as their sign-in records.

- **Can report problems.** An Admin sets this for each person on the
  **Access** tab, next to Can change their own password. It's also on the
  **Broken files** tab, next to the Sonarr and Radarr settings. It's on by
  default, including for everyone already added.
- **When it's off.** A report is refused with a plain sentence: "An Admin
  has turned off reporting problems for you." `GET /api/internal/me`
  reports it (`canReport: false`), so the app doesn't offer it. An Admin can
  always report.
- **Only what they can see.** An episode or movie their Viewing Level hides,
  or a station it hides or an Admin blocked for them, gets the answer for
  something that isn't there (404).
- **Limits.** Each person can send one report a day about each program, and
  10 a day in all. While signing in is off, the limits apply to each
  address.

## The addresses

The apps' own addresses (`docs/internal-api.md`):

- **Linking.** `"picker": true` on signing in, or on asking for a code,
  links the device and returns its `deviceKey`.
- **Who's tuning in?** `GET /api/internal/picker`,
  `POST /api/internal/picker/choose`, `POST /api/internal/picker/sign-in`
  and `POST /api/internal/picker/remove` are sent with that key, in the
  `StationPlay-Device` header.
- **PINs.** Signing in answers `askPin`, and `POST /api/internal/pin`
  sets a person's own PIN.
- **Passwords.** `POST /api/internal/password` changes a person's own
  password (1.28.0).
- **Reports.** `POST /api/internal/report-problem` sends a report (1.30.0).

The **Access** tab's addresses are `/api/access/viewing`,
`/api/access/levels`, `/api/access/users/{id}/viewing` and `/stations`,
`/api/access/devices` (with `PUT /api/access/devices/default` for New
people show on, and `POST /api/access/devices/everyone`),
`/api/access/users/{id}/picker` and `/invite`. Like everything on the
**Access** tab, they're for Admins only, and StationPlay refuses a change
sent from another site's page.

`POST /api/access/devices/everyone` (1.30.1) is Use for everyone. It takes
`{"showOn": "signed-in"}` (Only devices they sign in on) or
`{"showOn": "home"}` (Every device at home). Anything else is refused (400),
and nothing changes. It sets New people show on to that value, and sets
everyone already added to it too, except, for `signed-in`, people who can't
sign in by name. Then it answers with what it did, and records it in the
access log:

| Field | Type | What it is |
|---|---|---|
| `default` | string | New people show on, now |
| `changed` | number | How many people it changed |
| `kept` | list | The names of the people it left unchanged (no password or PIN) |

## Streams

The apps play stations from addresses that carry a key made for that
session. StationPlay checks the key on every request, and ends it when the
session ends. A key works only for the stations its person can see.
Programs from Media already play from addresses made for each play, checked
the same way.

The tuner, its guide and its streams, which Plex, Jellyfin and IPTV apps
use, carry no person, so limits can't apply there. The **Access** tab
explains this. (Phase 3 may offer several tuner lineups, each with its own
stations.)

## The apps

- **What they show.** Who's tuning in? on start, a PIN pad, Sign in,
  and Remove me from this device.
- **No filtering on the device.** The apps show exactly what the server
  sends.
- **The free app's station.** The free app's one station stays the
  **server's first station**, never the first one a person can see. If the
  person can't see it, the app says so and offers the unlock.

## Tests that must pass

- Someone on the Kid level never sees a TV-MA title in any list, search,
  guide, Resume row or "on now," and its key and stream address are
  refused.
- A station with one program above a person's level is hidden from them,
  unless an Admin allows that station for them.
- A User can't make an Admin, or change their own level.
- A first Admin can't be added from the internet (as before).
- A revoked device is signed out on its next request.
- Someone with neither a password nor a PIN can't sign in by name.
- Five wrong PINs lock that person out for 15 minutes, on every device.
- A StationPlay with one person, or none, answers exactly as before.
