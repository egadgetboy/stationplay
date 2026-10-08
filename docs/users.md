# Who sees what: users, Viewing Levels and devices (design)

StationPlay already has users: an Admin adds them on the Access tab, each
signs in with a name and password, and the apps link with a code. This adds
what each user may **see**, and a way for a household to share one TV or
tablet: a **Who's tuning in?** picker, with optional PINs. All of it is
decided on the server. The apps show only what the server sends.

## Goals

1. **Off until it's used.** A StationPlay with one user, or none, works
   exactly as it does today. Viewing Levels, PINs and the picker appear only
   once there's a second user.
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
  allow and block, enforced everywhere; linked devices, the picker, PINs,
  invite codes and "Show on"; Users can be watch-only.
- **Phase 2:** genre, tag, title and collection rules; rating overrides;
  per-user title exceptions; Station Audience warnings; Preview as user;
  Why is this hidden.
- **Phase 3:** the Manager role, Lock to user, one person linked to users
  on several servers, and several tuner lineups for Plex.

## Roles

Admin and User stay as they are. A User can make stations up to the limit
an Admin sets, and **None** is added to that limit: a User with None only
watches. (Manager comes in Phase 3.)

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
- **`users`** gains: level, PIN (a hash, or none), and Show on (see below).
  A User may have no password: they use only the pickers.
- **`user_stations`**: a station allowed or blocked for a user.
- **`linked_devices`**, **`device_people`** and **`invites`**: the linked
  devices (by a hash of each one's key), who's on each picker other than
  as Show on says (signed in there, chosen by an Admin, or taken off), and
  each person's invite code (a hash), while it lasts.

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
use it. Who's on it is each user's **Show on**:

- **All devices:** on every linked device's picker. Suits a household.
- **Selected devices:** only on the devices an Admin picks, such as the
  Living Room Roku and the Kids' Tablet.
- **Only where signed in:** on no picker until that person signs in on a
  device; then on that device's picker.

New users get the server's default as it is when they're added, which an
Admin sets: All devices (a household) or Only where signed in (a larger
server). Changing it doesn't move anyone already added; people added before
there were pickers are on every device.

The picker always has **Sign in**: the person enters their name and, the
first time on that device, their invite code or password; after that they
switch with their PIN. Each person can **Remove me from this device**.

Safety rules:

- A user with neither a password nor a PIN (a "Kids" user, say) can be
  **All devices** or **Selected devices** only, never signed in by name, so
  no one can get in from anywhere by guessing a name like "Kids". (A user
  with a password signs in with it, on the page or in an app, as today.)
- The first sign-in on a device takes an invite code or a password, never
  just a PIN. An **invite code** is made by an Admin for one user, works
  once, and expires after 7 days.
- An Admin always needs their PIN (or password) on a picker.
- PINs are 4 digits, kept as hashes. 5 wrong PINs for a user means a
  15-minute wait for that user, on every device.
- The picker exists only on a device already linked. A stranger who
  installs an app never sees a name.

## The addresses

The apps' own (`docs/internal-api.md`): `"picker": true` on signing in or
asking for a code links the device and returns its `deviceKey`;
`GET /api/internal/picker`, `POST /api/internal/picker/choose`,
`POST /api/internal/picker/sign-in` and `POST /api/internal/picker/remove`
are asked with the key, in the `StationPlay-Device` header. The Access
tab's: `/api/access/viewing`, `/api/access/levels`,
`/api/access/users/{id}/viewing` and `/stations`, `/api/access/devices`,
`/api/access/users/{id}/picker` and `/invite`.

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

- The picker on start, a PIN pad, Sign in, and Remove me from this device.
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
- A user with neither a password nor a PIN can't sign in by name.
- Five wrong PINs lock that user for 15 minutes, on every device.
- A StationPlay with one user, or none, answers exactly as before.
