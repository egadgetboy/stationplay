# Brief: new logos for StationPlay's logo library

StationPlay is a self-hosted app that makes broadcast-style TV stations; each
station shows its logo in TV guides (small, ~64 px) and on screen (large).
The library lives in `/home/claude/stationplay/tools/logos` and already has
~500 logos. You are adding a set of new ones in a NEW module of your own.
They must read as one cohesive, high-quality collection with the existing
logos: authentic-looking TV/cable channel logos — bold, dimensional,
polished, with depth (drop shadows, extrusion, gradients, panels, emblems,
badges, rims), professional lettering. NOT clip art, not flat childish
doodles: the owner rejected earlier logos as "childish, mismatched, boring"
and praised the current set ("these look fantastic"). Kids' channels can be
playful and bright, but polished like real kids' networks.

## Study first (don't skip)

- Contact sheets of the current library (view with Read):
  `/tmp/claude-0/-home-claude/2a18dafb-0b6c-5b09-b2a0-3df537bbe976/scratchpad/final/networks-1.png`,
  `networks-2.png`, `themes.png`, `genres.png`. This is the quality bar and
  the house style.
- `kit.py`: `svg(body, defs)`, `fit(group, x, y, w, h)` (places a group in a
  box, measured by pixels), `text(word, font, size, weight=, fill=, stroke=,
  sw=, style=, ls=)`, `arc_text`, `lin`/`rad` gradients, `shadow`, `glow`,
  `extrude`, `star`, `banner`, `tilt`, `skew`, `rough`, `worn`, `solid`...
- `layouts.py`: ~30 composition templates (emblem, sym_word, word_sym,
  roundel, seal, ribbon_badge, neon, marquee, poster, stamp, ticket,
  film_frame, deco, tv_screen, crest, block_word, pennant, postage, tag,
  chrome, bubble, script_card, varsity, tile_word, plate, burst_word,
  masthead, patch, letter_swap, stacked...). Read their signatures.
- `symbols.py`: 181 drawings on a 200x200 box (`S.SYMBOLS`), palettes via
  `P(a=, b=, c=, k=, l=)`, `centred(inner, cx, cy, size)`.
- Examples of finished logos: `networks.py`, `themes.py`, `genres.py`.
- Canvas: a 512x512 SVG, rendered to a transparent PNG.
- Fonts (only these are installed; use the family name, e.g. "Archivo Black"):
  Abril Fatface, Alfa Slab One, Anton, Archivo Black, Audiowide, Baloo 2,
  Bangers, Barlow Condensed, Bebas Neue, Bevan, Big Shoulders Display,
  Black Ops One, Bowlby One, Bungee, Bungee Inline, Carter One, Chango,
  Cinzel, DM Serif Display, Ewert, Federo, Fraunces, Fredoka, Graduate,
  Great Vibes, Holtwood One SC, IM Fell English, Inter, Kanit, Knewave,
  Libre Baskerville, Lilita One, Limelight, Lobster, Londrina Solid,
  Luckiest Guy, Michroma, Monoton, Montserrat, Orbitron, Oswald, Outfit,
  Pacifico, Permanent Marker, Pirata One, Playfair Display, Poiret One,
  Press Start 2P, Racing Sans One, Righteous, Russo One, Rye, Sancreek,
  Shrikhand, Sora, Space Grotesk, Special Elite, Syncopate, Teko, Tilt Neon,
  Titan One, Ultra, Unbounded, UnifrakturMaguntia, VT323, Yellowtail.
  (Check `kit.py`'s font loading if a family name doesn't render.)

## Your module

- Write `tools/logos/<your module>.py`. Copy the registration pattern from
  `networks.py`: a module list, a decorator `net(name, category, *tags)`,
  `slug()`, and `logos()` returning `[Logo(id, name, category, draw, tags)]`.
  IDs are `slug(name)`.
- Draw EVERY name on your list, exactly as given (fix capitalization only),
  in the category given, with 2–5 lowercase tags saying what such a station
  plays (e.g. "classic tv", "sitcoms", "comedy"; "movies", "horror";
  "cartoons"; "kids"; "christmas"). Tags feed the picker's suggestions, so
  include the obvious genre words.
- IDs must not collide with existing ones (`app/logos/catalog.json`) or other
  new modules. Other workers are writing, in parallel: classic_tv.py,
  tv_shows.py, toons.py, kids.py, movies.py, seasons.py. The name lists don't
  overlap.
- Do NOT edit kit.py, layouts.py, symbols.py, build.py or any other module:
  others are working at the same time. New drawings you need (and you'll
  need some) go in YOUR module, written like symbols.py (functions drawing
  on a 200x200 box, taking a `P` palette).

## Quality and variety

- Each logo is a complete, finished composition that reads at thumbnail
  size and at 512: the full station name, big and legible; a strong
  silhouette; good contrast. Nothing cramped, clipped, off-centre, or tiny.
- Vary the compositions: no single layout for more than ~15% of your set.
  Mix emblems, roundels, badges, crests, neon, marquees, screens, tickets,
  stamps, wordmarks with a symbol, stacked words, letter swaps, panels...
  and bespoke compositions. Vary fonts and palettes; match each name's vibe
  (vintage TV: period lettering and colours; westerns: slab/Rye; horror: dark
  and eerie; romance: script and roses; teens: 90s/2000s pop; kids: bright,
  rounded, still polished).
- Spoof the STYLE of channel types, never a specific real channel: no real
  channel's name, symbol, shape+colour combination or lettering. No famous
  characters or trademarks (no mouse ears, no Acme, no peacock, no eye, no
  MTV-style M, no HBO/Showtime/TCM-like marks, no real show titles).
- Sight gags and letter swaps are welcome when they stay legible.

## Workflow

1. Plan every logo briefly (composition + key visual + font + palette),
   checking the variety rule.
2. Write them in batches of ~15–25. Render and look:
   `cd /home/claude/stationplay/tools/logos && python3 review.py OUT <module>`
   with OUT = `/tmp/claude-0/-home-claude/2a18dafb-0b6c-5b09-b2a0-3df537bbe976/scratchpad/logos-<module>`
   (add `--light` for a light-background sheet too; a FILTER argument limits
   it to ids containing given words). View the sheets with Read. Fix
   anything weak, cramped, illegible, off-centre or clashing, and anything
   that looks like clip art. Iterate until every logo is one you'd ship.
   Rendering is cached, so re-runs only redraw what changed.
3. Check: `python3 -c "import <module>; l=<module>.logos(); print(len(l), len({x.id for x in l}))"`,
   and `ruff check <module>.py` from the repo root (E741, B007, PERF401,
   RUF005 and RUF059 are already ignored for tools/logos).
4. Finish with: your module path, the count, the final sheet paths, and
   anything you're unsure about (names you think may clash with a real
   channel, logos you're less happy with). Don't commit anything.

The machine has 2 CPU cores shared with other workers: render in batches,
not the whole set again and again.
