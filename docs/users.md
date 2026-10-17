# Who sees what: people, Viewing Levels and devices (design)

This design covers what each person may **see**, and how a household shares
one TV or tablet. An Admin already adds people on the **Access** tab. Each
person signs in with a name and password, and the apps link with a code.
This design adds limits on what each person sees, and a **Who's tuning
in?** screen with optional PINs. The server decides everything. The
apps show only what the server sends.

## Goals

1. **Off until it's used.** A tapiOca with one person, or none, works
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
5. **Lean.** Plex stays the catalog. tapiOca keeps a title's rating and
   Media folder only where its stations need them, and asks Plex for
   genres and tags only while some level or person hides by them.

## Phases

- **Phase 1.** Viewing Levels (rating and Media folders), and stations allowed
  or blocked for each person, enforced everywhere. Linked devices, Who's
  tuning in?, PINs, invite codes and "Show on" (which lists no one from
  1.38.0). Users can be
  watch-only.
- **Phase 2.** Built in 1.33.0: genre, tag, collection, studio and title
  rules for levels and people, and titles allowed for a person. After 1.0:
  rating overrides, Station Audience warnings, Preview as user and Why is
  this hidden.
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

tapiOca keeps everything of a person's by their ID, never their name, so
it all stays theirs after a rename: their sign-ins (on tapiOca's page
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

**Unrestricted** always exists and never changes. tapiOca creates Teen,
Kid and Young Child once, as a starting point. An Admin can rename, change
or remove them, like any level they add. A change applies at once to
everyone on that level. An Admin can add as many levels as they need, such
as "Adults" (no R-rated movies, no unrated titles) or "Grandparents."

A level also sets which **Media folders** (Plex's libraries) its people can see: all of them, or
the ones chosen. So a show that's in both "TV Parents" and "TV Teens" is
seen only through a Media folder the person may see.

From 1.33.0, a level can also hide titles by **genre**, **tag** (Plex calls
these labels), **collection** and **studio**, whatever their rating. Names
are matched whatever their capitals. An episode counts as its show: its
show's genres, tags, collections and studio. A title with no genre isn't
caught by a genre. A level's ratings stay the level's: to give one person
their own ratings, an Admin gives them a level of their own.

New people start on the level an Admin chose under **New people start on**,
in the **Viewing Levels** panel on the **Access** tab (from 1.34.1). It's
Unrestricted until an Admin chooses another, so until then adding someone
changes nothing. The **Add a user** form has a **Viewing Level** choice,
set to that level, to choose another for that person. Admins always see
everything, whatever their level. Removing the level new people start on
sets it back to Unrestricted, so a level added later never takes its place
by chance. The setup's **Who sees what** step asks about it too. The
choice is kept in `meta` as `viewing_new_level` (the level's id; none
means Unrestricted).

### Ratings as ages

tapiOca reads every rating as the youngest age it suits:

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
limits as ages, and tapiOca's page shows each one as the US rating for
that age.

An episode uses its show's rating, or its own if that's stricter. Rating
overrides (after 1.0) will belong to tapiOca and never change Plex.

## What's hidden or allowed for one person

From 1.33.0, an Admin can choose, for each person who isn't an Admin:

- **Also hidden.** Genres, tags, collections and studios, and shows and
  movies, hidden for that person whatever their level shows.
- **Allowed in Media.** Shows and movies shown to that person whatever
  their rating, genre or tags, as long as they're in a Media folder the
  person's level includes. A show or movie hidden for them wins over one
  allowed; a hidden genre, tag, collection or studio doesn't.

A hidden title is hidden everywhere tapiOca shows titles to that
person: Media, search, More like this, cast and crew pages and the Resume
row, and any station that plays it. Someone with
anything hidden for them watches only, as on a level with limits: the
station editor, which shows Media folders whole, isn't for them.

**What tapiOca knows.** tapiOca asks Plex for each title's genres
and tags in the background, only while some level or person hides by them:
each title again every day, and every title at once when a new name is
hidden. Until it knows a title's, the title is hidden from anyone whose
level or own rules hide by tags, as with a rating not known yet. Media asks
as it goes, 50 titles at a time, two batches at once, keeping each as it
comes and waiting only a few seconds (in all, for one answer) before
answering. A big folder's first 200 titles are asked about at once, and the
rest a batch at a time, behind what other answers ask, so the first look at
it shows some titles at first, and the rest as Plex answers (folders take
their turns, a batch at a time). Hiding a new name asks Plex about every title again, even across
a restart. A title Plex doesn't
have isn't asked about again for an hour. Titles are hidden or allowed by
Plex's key, so one Plex adds again under a new key needs choosing again
(the page marks it "not in Plex now").

**On the Access tab.** Viewing Levels → **Edit** (or **Add a level**) has
**Genres**, **Tags**, **Collections** and **Studios**: each a box to type a
name in, with Plex's own names offered, and **Add**. The levels' table
shows **Also hides** ("2 genres and 1 studio", or "Nothing more"). Beside
each person, **What they see** (formerly **Stations**; "(3 set)" when
anything is chosen) opens "What Kit sees", in three parts: **Stations**
(allowed, blocked, or as their level says, each with why it's shown or
hidden), **Also hidden for Kit**, and **Allowed for Kit in Media**. Shows
and movies are found by typing part of a title.

**It's logged.** The access log records each change: "Ada changed the
Viewing Level Kid (movies up to PG, …, hiding 2 genres and 1 studio)" and
"Ada set what's hidden and allowed for Kit (hiding 1 genre, 2 titles
allowed)".

## The rules, in order

For a person and a show, movie or episode, the first rule that applies
decides. An episode counts as its show for rules 2, 3, 6 and 7.

1. An Admin sees everything.
2. A title hidden for this person is hidden.
3. A title allowed for this person is shown, whatever its rating, genre or
   tags, as long as it's in a Media folder their level includes.
4. A title in a Media folder their level doesn't include is hidden.
5. A title rated above their level's age is hidden. An unrated title follows
   the level's setting.
6. A title with a genre, tag, collection or studio their level hides is
   hidden.
7. A title with a genre, tag, collection or studio hidden for this person
   is hidden.
8. Anything else is shown.

For a station, a station **allowed** for the person is shown, and one
**blocked** for them is hidden. Otherwise, it's shown only if every program
it plays passes rules 2 and 4 to 7. "Every program" means everything in its
current lineup, including its specials' programs. A title allowed for the
person doesn't make a station shown: an Admin allows the station instead.
Station numbers don't change when some stations are hidden.

Still to come *(after 1.0)*: rating overrides, Station Audience warnings,
Preview as user, and Why is this hidden for titles. (For stations, What
they see already says why each one is hidden.)

## Commercials and trailers

Commercials play after episodes, and trailers after movies, from the
`commercials` and `trailers` folders an Admin sets up. A folder named for
a decade, such as `commercials/1960s`, plays after programs from that
decade.

From 1.33.0, an Admin rates each clip folder under Access → Viewing Levels
→ **Commercials and trailers** (shown when there are any clips):
"Commercials", "Trailers", and each decade's folder ("Commercials from the
1960s"). Commercials use TV ratings (TV-G to TV-MA), and trailers use movie
ratings (G to NC-17). A decade's folder is rated as its kind is, unless it
has its own rating.

- **Stations people with limits can see.** A commercial or trailer plays
  only if its folder is rated, at or below the station's highest-rated
  program.
- **Until a folder is rated.** Those stations skip its clips. If a clip
  was already chosen, a plain card fills its time. An Admin alert says how
  many stations skip some: "2 stations people with limits can see skip
  commercials or trailers that aren't rated. Rate their folders under
  Viewing Levels on the Access tab." The alerts list offers **Open the
  Access tab**.
- **Stations only people without limits can see.** Every clip plays, as
  before.
- **Who sees a station.** A clip never changes it.
- **The whole station.** A station's lineup and its specials (Feature
  Presentation and blocks) are judged together: who can see it, and its
  highest-rated program.
- **Twice.** Clips are chosen as a lineup is made, and each is checked
  again as it's about to play. While what a station plays isn't known yet
  (a new show not asked about), every clip is chosen, and the check as each
  plays decides. As tapiOca starts, before the clip folders have been
  looked in, a clip is rated by the folder its file is in.
- **Nothing rated on the station.** A station whose programs are all
  unrated, seen by someone with limits, plays no commercials or trailers.
- **It's logged.** The access log shows "Ada rated the clip folders:
  commercials/1960s TV-14".

## Parental limits: what tapiOca enforces, and what it can't

Viewing Levels are limits in tapiOca's apps and on tapiOca's page,
and the docs say plainly what they don't cover.

**Enforced.** For someone signed in as themselves, on tapiOca's own
server, in tapiOca's apps and on its page: what they can find, see and
play, as Viewing Levels and the rules above say; stations, all or nothing;
and commercials and trailers, as above.

**Not covered:**

- **Plex, Jellyfin and anything else on the tuner.** They don't say who's
  watching, so they show every station (see the README's Tuner access and
  Blocking stations for some Plex users).
- **Devices without PINs.** On a shared device, anyone can pick anyone
  without a PIN on Who's tuning in? Everyone without limits should have a
  PIN on devices people with limits use.
- **Signing in as someone else,** on one's own device, with that person's
  password.
- **A rating or genre Plex has wrong, or doesn't have.** tapiOca goes
  by what Plex says. Unrated titles follow the level's Unrated setting.
- **What's inside a program,** beyond its rating, genres and tags.

Use the device's own controls too: Apple's Screen Time or Google's Family
Link.

## What tapiOca keeps

- **`titles`.** A row for each show and movie on a station: its key, kind,
  rating as Plex has it, that rating's age (or none) and its Media folder.
  tapiOca fills it in as it makes a station's lineup, since Plex sends
  these with the items. It also fills it once at startup for lineups made
  before this existed. From 1.33.0, it also keeps each title's genres,
  tags, collections and studio, asked of Plex in the background while some
  level or person hides by them. An episode's own rating is kept in its lineup row
  when Plex gives one.
- **Each station's reach.** The oldest age and the Media folders its programs
  need, and whether any program is unrated. tapiOca works this out when
  the lineup changes, so deciding whether someone sees a station takes only
  a few comparisons.
- **`levels`.** Name, movie age, TV age, whether unrated titles are shown,
  Media folders (all, or a list), and (1.33.0) the genres, tags,
  collections and studios it hides.
- **`users`.** Gains each person's level, PIN (`pin`: a hash, or
  none), whether they chose to have no PIN, Show on (kept, but from 1.38.0
  it lists no one: see below), whether they may change their own password,
  and (1.33.0) what's hidden or allowed for them. A User may have no
  password. They use only Who's tuning in? From 1.38.0, an Admin's Full or
  Light sign-in (`admin_sign_in`, `full` to start).
- **`user_stations`.** A station allowed or blocked for a person.
- **`linked_devices`, `device_people` and `invites`.** The linked devices,
  each by a hash of its key, with who linked it (by ID and by name). Each
  person's place on each device: signed in there (from 1.38.0, the only
  one that lists them, and `by_password`: whether with their password),
  chosen by an Admin (kept, but listing no one from 1.38.0), or taken off.
  Each person's invite code (a hash), while it lasts.
- **`browser_people`** (1.38.0). Each browser's people: everyone who signed
  in on it with their password, several to a browser, by a hash of the
  token kept in it. Whether each one's PIN may sign them in there, and when
  they last signed in there. Only the Admins among them are on its sign-in
  screen. On the first start of 1.38.0, it's filled from `devices`, which is
  kept as it was, for going back to 1.37.1.
- **`sessions`** gains, in 1.38.0, `admin_pin` (an Admin's sign-in made with
  their PIN in Light sign-in) and `watching` (a sign-in for watching only).
  Sign-ins made before give what they gave then. A backup is made before
  the update changes the database, as always.

Media in the apps (browsing, search, details, pictures and playing) already
asks Plex about each title. Plex sends its rating and Media folder, so
tapiOca judges the title from that and keeps no copy. Plex's lists
don't carry genres and tags, so from 1.33.0, while some level or person
hides by them, tapiOca asks for the genres and tags of the titles Media
shows, and keeps them in `titles`.

## Devices and Who's tuning in?

A **device** is one install of a tapiOca app, on a TV, phone or tablet.
It's linked to the server once, by signing in or with a code entered on
tapiOca's page. It gets a long-lived **device token**, which an Admin
can see and revoke on the **Access** tab. A revoked device is signed out on
its next request. Whoever is using the device gets a short-lived
**session** for one person, made by picking that person.

**Who's tuning in?** shows when the app starts, if more than one person can
use the device. A device is **at home** when it asks for the list on the
home port, which a VPN reaches too. It's **away from home** on the public
port.

From 1.38.0 (the owner, October 17), someone is on a device's list only
once they signed in on it themselves:

- **How.** With their password, an invite code, or a code entered on
  tapiOca's page (Link an app).
- **Never otherwise.** Not because they're at home, not because of their
  Show on, and not because an Admin chose the device for them.
- **At home and away.** Once there, they're listed wherever the device is.
  Unless Bo has signed in on Ada's TV, he isn't on its list, and she isn't
  on his phone's.
- **No password and no PIN.** Someone with neither, such as "Kids," is
  listed only at home, where anyone there can pick them.

### Show on, before 1.38.0

Before 1.38.0, each person's **Show on** said which devices listed them:

- **Only devices they sign in on.** On no device until they signed in on
  one, then on that device, at home and away.
- **Every device at home.** On every linked device while it was at home.
  Away from home, only on a device they signed in on, or one an Admin chose.
- **Every device, at home and away.** On every linked device, wherever it
  was.
- **Only devices you choose.** Only on the devices an Admin picked, at home
  and away.

From 1.38.0, Show on, **New people show on**, **Use for everyone** and the
devices an Admin chose are gone from the **Access** tab. Their values are
kept in the database, for going back to 1.37.1, and the API still takes
them, but they list no one. Someone who used to pick themselves on a device
signs in on it once to be on its list again. Each person's **Devices**
dialog shows the devices they're on, their PIN, and **Make an invite code**.

### New people show on, before 1.38.0

**New people show on** set where new people started: Only devices they
sign in on, or Every device at home. From 1.31.0, it was Only devices they
sign in on, unless an Admin chose otherwise before. Someone with no password
and no PIN started on Only devices you choose, with none chosen.

**Use for everyone**, next to it, set everyone already added that way too.
It asked first, showing how many people it changed, and kept anyone who
couldn't sign in by name as they were ("Kept as they were: Kids (no
password or PIN)"). Devices an Admin chose stayed chosen. The access log
shows "<Admin> set everyone to show on <choice>: <n> people changed," and
who was kept (still, when the API is used).

### Earlier names

In 1.28.0, everyone on All devices moved once to Devices at home, and so did
the server's default. All devices had been the household's default until
then, and everyone added before Who's tuning in? existed was on it. The
access log shows how many people moved.

1.31.0 renamed the four choices. The values the API sends didn't change.

| Before 1.31.0 | From 1.31.0 | API value |
|---|---|---|
| Devices at home | Every device at home | `home` |
| All devices | Every device, at home and away | `all` |
| Selected devices | Only devices you choose | `selected` |
| Only where signed in | Only devices they sign in on | `signed-in` |

### Signing in and the safety rules

Who's tuning in? always has **Sign in**. The person enters their name and,
the first time on that device, their invite code or password. After that,
they pick themselves, with their PIN if they have one. Each person can
choose **Remove me from this device**.

- **A name alone never works.** Someone with neither a password nor a
  PIN, such as a "Kids" account, never signs in by name. To get on a
  device, someone enters their name and an invite code there (from 1.38.0;
  before, they couldn't use one). They're then on that device's list only
  at home. No one can get in from anywhere by guessing a name like "Kids."
- **A password still works.** Someone with a password signs in with it, on
  tapiOca's page or in an app, as before.
- **The first sign-in needs more.** The first sign-in on a device takes an
  invite code or a password, never just a PIN. A PIN works only on a device
  someone already signed in on (unchanged since 1.36.2). An Admin makes an
  **invite code** for one person. It works once and expires after 7 days.
- **Admins always unlock.** An Admin gives their PIN, or their password, on
  Who's tuning in? An Admin with no PIN, alone on their own device, may be
  picked with nothing.
- **An Admin's sign-in in the apps.** Picked with their PIN, an Admin gets
  their Admin tasks only in Light sign-in, at home, on a device they signed
  in on with their password (not just an invite code). Otherwise the
  sign-in is for watching. So is an Admin picked with no PIN. Picked with
  their password, it's an Admin's sign-in.
- **PINs.** A PIN is 4 digits, stored as a hash. After 5 wrong
  PINs, that person waits 15 minutes, on every device.
- **A PIN removed.** Removing the PIN of someone without a password ends
  their sign-ins from Who's tuning in? on every device. They're then listed
  only at home, and pick themselves again.
- **Linked devices only.** Who's tuning in? exists only on a device that's
  already linked. A stranger who installs an app never sees a name.
- **Away from home.** Picking someone the device doesn't list there is
  refused, the same as picking someone who isn't on it at all.

### A PIN after the first sign-in

From 1.28.0, once someone has signed in with their password or an invite
code, later sign-ins are open, or locked with a 4-digit PIN if they
choose. The first time they sign in on a device that way (by name in an
app, or with a code entered on tapiOca's page), the app asks them to
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
- **Only from an Admin.** Someone with neither, such as "Kids," can't
  choose a PIN themselves. They never sign in by name, and only an Admin
  gives them a PIN.
- **Wrong tries still count.** Wrong PINs still count after a new one
  is chosen.
- **Admins can still change it.** An Admin can still set or remove anyone's
  PIN on the **Access** tab.
- **It's logged.** The access log shows "<name> set a PIN" or "<name>
  chose no PIN," and in which app.

### Changing your password in the apps

From 1.28.0, people can change their own password in the apps' Options, as
on tapiOca's page (under their name at the top). They need their
current password. The rules match the page: the same length, and the same
limit on wrong passwords (5 from one address in 15 minutes, then a wait).
Every other sign-in of theirs ends, as on the page, but the app they changed
it in stays signed in. The access log shows "<name> changed their password
in <the app, on the device>."

- **Can change their own password.** An Admin sets this for each person on
  the **Access** tab, next to their New password. It's on by default,
  including for everyone already added.
- **When it's off.** tapiOca's page and the apps both refuse the change
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

## Signing in on tapiOca's page

From 1.38.0 (the owner, October 17), `app/access.py`.

- **Full or Light.** Each Admin's own choice, in Your account (the name at
  the top of the page), under How you sign in. It takes their password
  (`PUT /api/access/me/sign-in`, `{"how": "full" or "light", "password":
  ...}`). **Full**, the default for every Admin after updating: their
  password every time, for Admin tasks. **Light**: their password once on
  each browser or device, then their PIN there, at home, gives their Admin
  tools. Light needs a PIN.
- **Away from home.** On the public port, the page never takes a PIN
  (`POST /api/access/pin-sign-in` answers 404 there), and a PIN's sign-in
  used there is for watching only.
- **What ends them.** Choosing Full ends the sign-ins the PIN made. A new
  PIN set by an Admin ends the sign-ins the old one made (one you set
  yourself keeps the sign-in you set it from). A new role (a User made an Admin,
  or an Admin made a User) ends all of that person's sign-ins, but the one
  making the change, so they sign in again as what they are now.
- **No credentials.** A PIN's sign-in can't make anything that works
  elsewhere: passwords, PINs, people, API tokens or invite codes
  (`access.STEP_UP`). It can't link an app either (`access.LINK_BOUND`).
- **Who's signing in?** The page's sign-in screen, at home, lists only the
  Admins who signed in on that browser with their password, latest first.
  Each shows PIN (Light, and their PIN works there) or Password. Never a
  User, even one who signed in there. With one listed, their PIN or
  password is asked at once. **Sign in with a password** is always there,
  for anyone, Users too.
- **Sign out, and Remove from this browser.** Sign out ends the sign-in but
  keeps the Admin listed, for their password first next time. Remove from
  this browser (`POST /api/access/browser/forget`, `{"id": ...}`) takes them
  off that browser's list. It answers `{"ok": true}` whoever is named.
- **A User's PIN.** It no longer signs in on the page. (1.37.0 and 1.37.1
  allowed it.)
- **Wrong PINs.** Each person's own limit (5, then 15 minutes, on every
  device and the page alike), and 10 on one browser, then the password
  there.
- **No Admin tabs before tapiOca says.** The page draws no Admin tabs until
  the server has said this sign-in may use them. If it can't be asked, the
  page says "tapiOca couldn't check who's signed in," with Try again.
- **Signed in for watching.** An Admin signed in for watching sees a note
  saying why, with Sign in with your password. Anything only an Admin may
  do answers 403 with `access.WATCHING_ONLY` ("You signed in without your
  password, so this sign-in is for watching. For Admin tasks, sign out, then
  sign in with your password."), or `access.ADMIN_PASSWORD_NEEDED` for a
  trusted network's sign-in.

`GET /api/access/me` (the page's) says, from 1.38.0:

| Field | What it is |
|---|---|
| `user.adminTools` | Whether this sign-in may do what only an Admin may. The page draws the Admin tabs by it |
| `user.watching` | An Admin signed in for watching only |
| `user.adminSignIn` | For an Admin only, their own: `full` or `light` |
| `user.byNetwork` | A trusted network signed them in |
| `people` | Signed out, at home: the Admins on this browser's sign-in screen, each with `id`, `name` and `pin` (whether their PIN signs them in here). Left out when there's no one. In place of 1.37.x's `pinFor` |
| `trusted` | Signed out, at home, only on a trusted network. One that signs in as someone: `{"gives": "person"}`, never who (1.38.0: no User is shown on the sign-in screen); `{"gives": "none"}` if that person is gone; on one that opens on Who's tuning in?, `{"gives": "picker"}`, never its people |

## Trusted networks

From 1.36.0, devices on a trusted network skip signing in. Nothing is
trusted until an Admin lists it (`app/trusted.py`).

- **Entries.** Kept in `meta["trusted_networks"]` with the trusted proxies
  and names for home. Each is a network or one address (home ranges only,
  never loopback or the internet), a name, what it gives, the person, who
  added it and when. At most 50; wider than a /24 (or /64) only with
  `confirmWide`. What can't be read trusts nothing.
- **The two choices.** `picker`: Who's tuning in?. `person`: Signed in as
  that person; an Admin only on a single address. The longest prefix wins.
- **When it applies.** Signing in on; at home (`app/networks.py`'s
  `judge`); a home name in the Host; the peer not a relay, even a relay
  listed as a trusted proxy (anyone it carries could name anyone); relays
  readable and addresses not hidden (`app/relays.py`); no forwarding
  headers, unless the peer is a trusted proxy. Headers only ever take
  trust away. Wrong passwords on the home port through a relay count as
  the relay.
- **Through a proxy.** A trusted proxy's visitor gets its own entry, but
  never one that signs in an Admin: the next wider entry applies, if any.
- **Bound sign-ins and devices.** Made on an entry, they carry its id
  (`sessions.trusted`, `linked_devices.trusted`) and work only on it. Their
  tokens and keys start `tt_` and are stored under `"t:" + sha256`, so
  1.35.0 never finds them. One made without a PIN or password is
  `unlocked`. A bound or unlocked sign-in is for watching
  (`access.by_network`): it can't change a password or PIN, add people,
  or make API tokens or invite codes (`access.STEP_UP`), or link an app
  (`access.LINK_BOUND`). An Admin's acts as a User's (the Gate puts a
  User-role copy in the request), and anything only an Admin may do is
  refused (`access.ADMIN_PASSWORD_NEEDED`); what they may watch is still an
  Admin's. A PIN sign-in from a network can't change that PIN. A password
  given on an app's picker makes an ordinary sign-in. (From 1.38.0, an
  Admin picked with nothing, alone on their own linked device, is for
  watching too: see Signing in on tapiOca's page.) Stream keys and play sessions made for a bound
  sign-in work only on its entry. A password or invite code used on a
  network-bound device clears its entry. An entry links at most 100
  devices, then one only in place of a device no one was ever picked on,
  or one unused for 30 days. One
  address asks at most 20 times in 15 minutes, and bound sign-ins are kept
  apart from a person's others (`SESSIONS_KEPT` each).
- **Reconcile.** When a person is removed or their role changes, and at
  each start (after reset-access, or a restore): an entry whose person is
  gone goes; an Admin's wider entry, or one listed before its person was
  made an Admin, becomes `picker`; and someone whose role changes loses
  all their sign-ins (from 1.38.0; before, someone made an Admin lost only
  their unlocked ones). Then, and on each
  save, an entry changed or removed ends what it gave. Each is logged.
- **The picker.** From 1.38.0, only in the apps. A network's device lists
  only those who signed in on it themselves, as any device does, so at
  first no one. Signing in on it by name makes it an ordinary linked
  device. On the page, a network that opens on Who's tuning in? changes
  nothing: its sign-in screen is as at any home address. (1.36.0 to 1.37.1
  listed everyone shown on Every device at home, on the page and in the
  apps, and signed them in with a PIN or nothing.) A network that signs in
  as someone still does, on the page and in the apps, for watching.
- **PIN limits.** Each person's own (5 wrong, then 15 minutes, everywhere).
  On the page, 10 wrong on one browser (`access.BROWSER_PIN_TRIES`), then
  a password there.
  An Admin's PIN locked is an `access` alert, fixed once it's unlocked.
- **Relays.** Every gateway in the routing table, tapiOca's own addresses
  and loopback are never trusted. When relays carry every request for an
  hour (20 page or API requests, with fewer than 5 from anything else;
  never the tuner, icons or logos, which Plex in Docker fetches through the
  gateway), trust is off for everyone. If the routing table can't be read,
  trust is off too, with an alert.
- **The apps.** `POST /api/internal/trusted` gives a `picker` app a
  network-bound device key, or a `person` app a bound sign-in. Off its
  network, a bound key gets 403.

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
`/api/access/levels`, `/api/access/new-level` (`PUT {"level": <id>}`:
New people start on, 1.34.1), `/api/access/users/{id}/viewing` and `/stations`,
`/api/access/clips` (the clip folders' ratings, 1.33.0),
`/api/access/devices` (with `PUT /api/access/devices/default` for New
people show on, and `POST /api/access/devices/everyone`),
`/api/access/users/{id}/picker` and `/invite`. Like everything on the
**Access** tab, they're for Admins only, and tapiOca refuses a change
sent from another site's page.

From 1.38.0, `PUT /api/access/devices/default`,
`POST /api/access/devices/everyone`, and `showOn` and `devices` in
`PUT /api/access/users/{id}/picker` are kept, for going back to 1.37.1.
They still take and save their values, but those values list no one on
any device. The page no longer offers them. `GET /api/access/devices`
lists, for each device, who's on it at home (`people`) and away from home
(`peopleAway`): only those who signed in on it.

`POST /api/access/devices/everyone` (1.31.0) is Use for everyone. It takes
`{"showOn": "signed-in"}` (Only devices they sign in on) or
`{"showOn": "home"}` (Every device at home). Anything else is refused (400),
and nothing changes. It sets New people show on to that value, and sets
everyone already added to it too, except people who can't sign in by name.
Then it answers with what it did, and records it in the access log. (From
1.38.0, none of this lists anyone.)

| Field | Type | What it is |
|---|---|---|
| `default` | string | New people show on, now |
| `changed` | number | How many people it changed |
| `kept` | list | The names of the people it left unchanged (no password or PIN) |

## Streams

The apps play stations from addresses that carry a key made for that
session. tapiOca checks the key on every request, and ends it when the
session ends. A key works only for the stations its person can see.
Programs from Media already play from addresses made for each play, checked
the same way.

The tuner, its guide and its streams, which Plex, Jellyfin and other apps
use, carry no person, so limits can't apply there. The **Access** tab
explains this. (Phase 3 may offer several tuner lineups, each with its own
stations.)

## The apps

- **What they show.** Who's tuning in? on start, a PIN pad, Sign in,
  and Remove me from this device.
- **No filtering on the device.** The apps show exactly what the server
  sends.
- **The Free tier's station.** In an app's Free tier, the one station is
  always the **server's first station**, never the first one a person can
  see. If the person can't see it, the app says so and offers **Unlock**.

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
- A tapiOca with one person, or none, answers exactly as before.
