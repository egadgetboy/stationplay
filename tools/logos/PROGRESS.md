# Logo library 1.8: progress

## RESUME HERE (2026-10-01)
- All 495 new logos are drawn and committed, plus the shared "Collection"
  logo (tv_shows.py, category "On the air", id "collection": what stations
  made from Plex collections start with; never handed out at random).
- Last logo stage: seasons.py batch 4, Halloween (10) and Valentine's (7):
  Belfry bats lightened, Hayride straw tidied, Cupid's Arrow redrawn with
  the arrow between the words, Be Mine bricks clipped to the panel.
- Next: the 1.8.0 finish: integrate modules in build.py (ORDER/categories:
  "Classic TV", "TV shows", "Decades", "Over-the-air classics",
  "Cartoons & anime", "Teens", "Kids & family", "Movie channels",
  "Holidays & seasons"); remove Hanukkah + 18 sister channels with REPLACED
  mappings; build the library; update tests (catalog size).
- Lessons: never fit() inside a clipped <g> (measurement fails — draw then
  clip, or use mix-blend); no backslashes inside f-string expressions
  (Python 3.11); check new looks against existing logos for lookalikes.

Work in stages: one batch (~20 logos) per stage, committed when done.
Review each batch with `python3 review.py OUT MODULE FILTER`; fix, then commit.

## Decisions (agreed 2026-09-30)
- ~500 new standalone stations (no sister channels), names generic enough to
  reuse; spoof channel styles, never real names/symbols. Quality = current set.
- Remove Hanukkah (stations using it move to a winter logo).
- Remove the 18 old sister-channel logos (Velvet Rope Comedy/Family/Signature,
  Night Reel Action/Thriller/Sci-Fi, Premiere Row Family/Extreme, Gold Seal
  Comedy/Edge/Kids & Family, Second Showing Westerns/Classic/Action/Suspense/
  Family, Widescreen Hits, Vertical Hold Plus); stations using one move to its
  parent (REPLACED in build.py) — at the integration stage. (agreed 19:44)
- New logos are ADDED (library 507 -> ~1,000); retiring weak existing ones is
  fine, always with a REPLACED mapping so stations keep working.
- Style rule (19:41): real-network polish first — confident wordmarks,
  emblems, badges, screens. Humour comes from the name, not novelty props.
  Avoid cartoon gags (gloves, beanies, cans, boxes, smoke clouds...).
- Halloween and Valentine's get new sets; keep New Year's, Easter, Summer,
  Winter, Thanksgiving, Christmas with variety.
- Ship as 1.8.0 together with the Intro Bumper and corner clock (already
  committed), after all logos + full test run.

## Stages
| Module / category | Batch | Status |
|---|---|---|
| classic_tv.py — Classic TV | 1 Comedy (20) | done |
| | 2 Favorites & mix (20) | done |
| | 3 Drama (15) | done |
| | 4 Action & adventure (15) | done |
| | 4b Redo the 14 cheesiest (Giggle Box, Madcap, Punchline, Canned Laughter, Knee Slapper, Laugh Riot, Hand-Me-Down TV, Pot Luck TV, The Clicker, Objection!, Soap Box, Big Hair TV, Burnout, Tailpipe) | done |
| | 5 Westerns (10) + Mystery (10) (Tumbleweed, Private Eye redrawn in review; no eye symbol) | done |
| | 6 Sci-fi (10) (Tin Robot, Star Hopper redrawn in review) | done |
| tv_shows.py — TV shows (30) | 1 (15 kept from draft, Cold Open de-iced; 15 new) | done |
| tv_shows.py — Decades (14) + Over-the-air classics (7) | 2 (60s TV redrawn as op-art; no target roundel) | done |
| toons.py — Cartoons & anime (50) | 1 Classic 12 (draft kept; Rubber Hose gloves/legs removed, Cel Block redrawn as stacked cels, Squash & Stretch simplified) + Cereal Bowl, Couch Fort, Toon Loop, Toon Soup, Anvil Drop | done |
| | 2 Banana Peel, Cream Pie, Seltzer Bottle, Screwball, Slapstick, Kaboom, Zany, Cartoon Jukebox, Doodle Den, Sketchbook, Toon Tower, Funhouse, Spring Loaded, Rad Toons, Tubular, Sugar Crash, Totally Toons (Banana Peel, Cream Pie, Sketchbook, Toon Tower, Funhouse tidied in review) | done |
| | 3 Neon Toons..Spirit Fox (16) (Neon Toons rebuilt two-line, Ramen/Paper Lantern/Katana tidied) | done |
| toons.py — Teens (40) | 1 Detention..Locker Talk (20) (Study Hall as crest, Class Clown stacked) | done |
| | 2 The Mall..Spring Break (20) (B-Side, Bestie, Cafeteria, Promposal tidied) | done |
| kids.py — Kids & family (55) | 1 Preschool 18 (draft kept; Pillow Fort redrawn as blanket tent; Toon Soup in toons.py redrawn as a pot so it no longer copies Alphabet Soup) | done |
| | 2 Monkey Bars..Marble Run (25) (Monkey Bars, Dino Dig, Lemonade Stand, Scooter tidied) | done |
| | 3 Kiddie Matinee..Family Album (12) | done |
| movies.py — Movie channels (126) | 1 Big screen + action (22) (draft kept; Roundhouse recoloured so it no longer reads as a basketball; Sold Out label straightened) | done |
| | 2 Comedy (8) + Horror (14) (Guffaw spacing, Spook Show two lines, Blooper Reel and Coffin simplified) | done |
| | 3 Sci-fi (8) + Thriller (8) + Romance (10) (7 tidied in review) | done |
| | 4 Classic (12) + Video store (8) (Golden Era laurel redrawn, Roxy recoloured; never fit() inside a clipped group — the measure breaks) | done |
| | 5 Drive-in (10) + Epics/war/western (10) (Battle Stations rebuilt, Sticky Floor puddle) | done |
| | 6 Arthouse (6) + Family (6) + Musicals (4) (Festival Circuit, Tap Shoes tidied) | done |
| seasons.py — Holidays & seasons (73) | 1 Christmas (22) (11 from draft; Christmas Eve sleigh moved off the moon; Nutcracker shako redrawn) | done |
| | 2 New Year (6) + Easter (6) + Thanksgiving (6) (Confetti via tspans, flutes, Kids' Table redrawn) | done |
| | 3 Summer (9) + Winter (7) (Fireside as stone hearth, Snowed In, Summer Vacation/Reruns tidied) | done |
| | 4 Halloween (10) + Valentine's (7) | done |
| Integrate: build.py ORDER/categories, remove Hanukkah + REPLACED, tests | | |
| Build library, full tests, package 1.8.0 | | |

Name lists for each category: drafts/BRIEF.md and the commit history of
this file's first version (see the conversation plan). Unreviewed drafts
from earlier parallel workers are in drafts/ (not imported): review, fix
and move into place when their category comes up.

## Name lists
- Classic TV: Comedy: Chuckle Channel, Laugh Riot, Knee Slapper, Canned Laughter, Studio Audience, Shenanigans, Hijinks, Wisecrack, Sitcom Street, TV Dinner, Shag Carpet TV, Belly Laugh, Giggle Box, Punchline, Madcap, Tomfoolery, Rib Tickler, Laugh Lines, Wood Panel TV, Meatloaf Monday. Favorites: Memory Lane, Time Capsule, Heirloom TV, Hand-Me-Down TV, Way Back When, Console TV, Tube Glow, The Clicker, Tin Foil Antenna, The Recliner, Evergreen TV, Golden Dial, Station Break, Channel Knob, Comfort TV, Old Faithful, Pot Luck TV, Sunday Best, The Den, Back in the Day. Drama: To Be Continued, Previously On, Stay Tuned, Cliffhanger, Big Hair TV, Shoulder Pads, Objection!, House Call, Bedside Manner, The Big Story, Second Act, Soap Box, Front Page, Grand Jury, Family Secrets. Action: Car Chase, Stunt Double, Freeze Frame, Code Three, Stakeout, Chopper TV, Muscle Car TV, High Octane, Road Block, Aviator Shades, Burnout, Rescue Squad, Undercover, Mission Control, Tailpipe. Westerns: Horse Opera, Ten-Gallon TV, Chuckwagon, Tumbleweed, Hitching Post, Saddle Up, Stampede, Lasso, Boot Hill, Dusty Trails. Mystery: Whodunit, Red Herring, The Butler Did It, Plot Twist, Trench Coat, Gumshoe, The Lineup, Private Eye, Night Beat, Deerstalker. Sci-fi: Ray Gun TV, Tin Robot, Tractor Beam, Moon Base, Launch Pad, Flying Saucer, Atomic TV, Space Station 9, Cosmic Channel, Star Hopper.
- Other categories: see the worker prompts summarised in drafts/BRIEF.md's companion list below.

### TV shows (30)
Case of the Week, Confessional, Bonus Round, Grand Prize, Box Set, Season Pass, Next Episode, Are You Still Watching?, The Narrator, True Story, One More Episode, Pilot Season, Spin-Off, Season Finale, Cold Open, Ensemble, Showrunner, Writers' Room, Tape Delay, Guest Star, Fan Favorite, Recap, Syndicated, Talk of the Town, Couch Potato, Two-Parter, Very Special Episode, Sweeps Week, Opening Credits, Theme Song
### Decades (14)
50s TV, 60s TV, 70s TV, 80s TV, 90s TV, 2000s TV, 50s Movies, 60s Movies, 70s Movies, 80s Movies, 90s Movies, 2000s Movies, Y2K, Mid-Century
### Over-the-air classics (7)
The 4:30 Movie, The Late Movie, Sunday Night Movie, Afternoon Movie, Movie of the Week, Weekend Movie, Morning Movie
### Cartoons & anime (50)
Rubber Hose, Pie-Eyed, Before the Feature, Ink & Paint, Squash & Stretch, Frame by Frame, Funny Pages, Short Subjects, Cel Block, Inkpot, Toon Parade, Cartoon Carnival; Cereal Bowl, Couch Fort, Toon Loop, Toon Soup, Anvil Drop, Banana Peel, Cream Pie, Seltzer Bottle, Screwball, Slapstick, Kaboom, Zany, Cartoon Jukebox, Doodle Den, Sketchbook, Toon Tower, Funhouse, Spring Loaded; Rad Toons, Tubular, Sugar Crash, Totally Toons, Neon Toons, Pajama Toons, Afterschool Toons, Mega Morning; Toons After Dark, Late Toons, Night Shift Toons, Midnight Ink; Kaiju Channel, Mecha, Origami, Ramen Night, Bullet Train, Paper Lantern, Katana Theater, Spirit Fox
### Teens (40)
Detention, Pop Quiz, Study Hall, Yearbook, Class Clown, Drama Club, Homecoming, Letterman, Food Court, Roller Rink, Skate Night, Sleepover, Boombox, Flip Phone, Dial-Up, Away Message, Whatever TV, Tween Screen, Hall Pass, Locker Talk, The Mall, Arcade, B-Side, Pep Rally, Promposal, Cafeteria, Bus Stop, Glow Stick, Cool Kids, Hangout, Group Chat, Crush, Diary, Bestie, Skate Park, Garage Band, Skip Day, Report Card, Teen Idol, Spring Break
### Kids & family (55)
Sippy Cup, Naptime, Peekaboo, Fingerpaint, Storytime, Puddle Jump, Bubble Wand, Pillow Fort, Hopscotch, Sidewalk Chalk, Crayon Box, Stacking Blocks, Lullaby Lane, Rain Boots, Teddy Bear, Seedlings, Alphabet Soup, Giggles; Monkey Bars, Tire Swing, Jungle Gym, Tree Fort, Treasure Chest, Dino Dig, Bug Jar, Lemonade Stand, Ice Cream Truck, Bouncy Castle, Kazoo, Field Trip, Show & Tell, Snow Cone, Gumdrop, Lollipop, Secret Clubhouse, Paper Airplane, Scooter, Science Fair, Magic Wand, Pirate Cove, Rocket Club, Kite String, Marble Run; Kiddie Matinee, Pajama Premiere, Family Flicks, Tiny Theater, Movie Fort, Saturday Flicks; Family Room, Minivan, Carpool, Cookout, Porch Swing, Family Album
### Movie channels (126)
Opening Weekend, Sold Out, Wide Release, Feature Presentation, Coming Attractions, Intermission, Front Row, Ticket Stub, Free Refill, Jumbo Tub, Big Screen, Red Carpet; One-Liner, Roundhouse, Mayhem Movies, Slow-Mo, Blast Radius, Adrenaline, Showdown, Last Stand, Full Throttle, Powder Burn; Crack-Up Cinema, Goofball, Blooper Reel, Outtakes, Laughing Gas, Silly Pictures, Gut Buster, Guffaw; Creature Feature, Shock Theater, Spook Show, Fog Machine, Cheap Scares, Jump Scare, Cobweb Cinema, Graveyard Shift, Things That Go Bump, Monster Matinee, Fright Lights, Night Terrors, Coffin Theater, Midnight Morgue; Deep Space Drive-In, Hyperdrive, Cyber Cinema, Future Shock, Robot Theater, Laserlight, Astro Cinema, Orbit Cinema; Edge of Your Seat, White Knuckle, Nail Biter, Double Cross, Dark Alley, Wiretap, Getaway Car, Paper Trail; Date Night, Back Row, Swoon, Love Seat, Happily Ever After, Candlelight Cinema, Three-Hanky Movies, Tissue Box, Sweet Nothings, Heart Throb; Old Hollywood, Studio Lot, Soundstage 9, Picture Palace, The Orpheum, The Rialto, The Roxy, The Bijou, Golden Era, Monochrome, Leading Man, Starlet; Late Fee, New Releases, Please Rewind, Tracking, Video Store Friday, Top Shelf, Rental Night, Staff Picks; Speaker Box, Dusk to Dawn, Car Hop, Sticky Floor, Direct to Video, Extra Cheese, So Bad It's Good, Starlite Drive-In, Cult Following, Bargain Matinee; Cast of Thousands, Three-Hour Epic, Front Line, Foxhole, Six-Gun Cinema, Saddle Theater, Battle Stations, Sword & Sandal, High Seas, Wide Open Range; Festival Circuit, Passport Cinema, Laurel Wreath, World Cinema, Short List, Film Society; Storybook Cinema, Cartoon Cinema, Family Feature, Toon Theater, Popcorn Pals, Magic Lantern; Show Tunes, Song & Dance, Tap Shoes, Jukebox Musical
### Holidays & seasons (73)
Yule Log, Ugly Sweater, Eggnog, Candy Cane Lane, North Pole Network, Sleigh Bells, Mistletoe Movies, Jingle, Stocking Stuffers, Christmas Eve, Fa La La, Santa's Workshop, Gingerbread, Holiday Specials, Twelve Days, Fruitcake, Tacky Lights, Deck the Halls, Nutcracker, Christmas Morning, Silent Night, Chestnuts; Countdown, Midnight Toast, Confetti, Resolution, Auld Lang Syne, Party Hats; Egg Hunt, Bunny Hop, Easter Basket, Chocolate Bunny, Easter Bonnet, Spring Chick; Turkey Day, Gobble Gobble, Kids' Table, Second Helpings, Food Coma, Pumpkin Pie; Summer Vacation, Pool Party, Heat Wave, Summer Reruns, Beach Blanket, School's Out, Dog Days, Surf's Up, Summer Camp; Snow Day, Cabin Fever, Snowed In, Ski Lodge, Fireside, Hot Cocoa, Icicle; Trick or Treat, Haunted House, Candy Corn, Jack-o'-Lantern, Witching Hour, Full Moon, Costume Party, Black Cat, Belfry, Hayride; Love Notes, Candy Hearts, Cupid's Arrow, Be Mine, Red Roses, Box of Chocolates, Puppy Love
