// Viewing Levels.
// Viewing Levels ----------------------------------------------------------------------
// What a level or person hides by what a title is (1.33.0): genres, tags
// (Plex's labels), collections and studios, and (for a person) titles.
const TAG_KINDS = [['genres', 'Genres', 'genre'], ['labels', 'Tags', 'tag'], ['collections', 'Collections', 'collection'], ['studios', 'Studios', 'studio']];
const noBlocks = () => ({ genres: [], labels: [], collections: [], studios: [], titles: [] });
const blocksOf = b => ({ ...noBlocks(), ...structuredClone(b || {}) });
const hidesTags = b => TAG_KINDS.some(([kind]) => (b?.[kind] || []).length);
const hidesCount = b => [...TAG_KINDS.map(([kind]) => kind), 'titles'].reduce((n, kind) => n + (b?.[kind] || []).length, 0);
// "2 genres and 1 title" ('' for nothing).
function hidesSaid(b) {
  const parts = [...TAG_KINDS.map(([kind, , noun]) => [(b?.[kind] || []).length, noun]), [(b?.titles || []).length, 'title']]
    .filter(([n]) => n).map(([n, noun]) => plural(n, noun));
  return parts.length < 2 ? parts.join('') : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`;
}
const levelLimited = lv => lv.movieAge != null || lv.tvAge != null || !lv.unrated || lv.libraries != null || hidesTags(lv.blocks) || (lv.blocks?.titles || []).length > 0;
// The names Plex has for each, offered as they're typed (fetched once; if
// Plex can't be reached, names can still be typed).
let tagsOffered = null;
async function loadTagsOffered() {
  if (tagsOffered) return tagsOffered;
  try { tagsOffered = await api('/api/access/tags'); return tagsOffered; }
  catch { return { genres: [], labels: [], collections: [], studios: [] }; }
}
let pickerCount = 0;
// Names to hide: typed (Plex's own offered as they're typed), each shown
// with a way to take it out again. `values` is changed in place.
function namePicker(label, noun, values, offered) {
  const id = `namePick${++pickerCount}`;
  const input = h('input', { type: 'text', list: id, maxlength: 100, autocomplete: 'off', 'aria-label': label,
    placeholder: `Type ${/^[aeiou]/.test(noun) ? 'an' : 'a'} ${noun}` });
  const chips = h('div', { class: 'chips' });
  const paint = () => chips.replaceChildren(...values.map(name => h('span', { class: 'sel' }, h('span', {}, name),
    h('button', { type: 'button', 'aria-label': `Remove ${name}`, onclick: () => { values.splice(values.indexOf(name), 1); paint(); } }, '×'))));
  const add = () => {
    const typed = input.value.trim();
    // (As Plex writes it, when it's one Plex has.)
    const name = offered.find(n => n.toLowerCase() === typed.toLowerCase()) || typed;
    if (name && !values.some(v => v.toLowerCase() === name.toLowerCase())) values.push(name);
    input.value = '';
    paint();
  };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  paint();
  return h('div', { class: 'name-pick' },
    h('div', { class: 'inline-add' }, input, h('datalist', { id }, ...offered.map(n => h('option', { value: n }))),
      h('button', { type: 'button', class: 'btn', onclick: add }, 'Add')),
    chips);
}
// Every show and movie, for choosing titles (fetched once, when needed).
let everyTitle = null;
async function loadEveryTitle() {
  if (everyTitle) return everyTitle;
  const libs = (await api('/api/libraries')).filter(l => l.type === 'show' || l.type === 'movie');
  const found = [];
  for (const lib of libs) found.push(...await api(`/api/libraries/${lib.key}/items`));
  everyTitle = found;
  return found;
}
// Titles chosen by searching for them: `chosen` ({key, title}) is changed in place.
function titlePicker(label, chosen) {
  const input = h('input', { type: 'search', maxlength: 100, autocomplete: 'off', 'aria-label': label, placeholder: 'Type part of a title' });
  const finds = h('div', { class: 'chips title-finds', 'aria-live': 'polite' });
  const chips = h('div', { class: 'chips' });
  // (One Plex doesn't have now, as when it's added again with a new key,
  // is marked: choose it again.)
  const gone = t => everyTitle && !everyTitle.some(e => e.ratingKey === t.key);
  const paint = () => chips.replaceChildren(...chosen.map(t => h('span', { class: 'sel' }, h('span', {}, t.title || 'A title'),
    gone(t) ? h('span', { class: 'hint' }, ' — gone now: find it again') : null,
    h('button', { type: 'button', 'aria-label': `Remove ${t.title}`, onclick: () => { chosen.splice(chosen.indexOf(t), 1); paint(); } }, '×'))));
  if (chosen.length) loadEveryTitle().then(paint, () => {});
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 2) { finds.replaceChildren(); return; }
      let titles;
      try { titles = await loadEveryTitle(); }
      catch { finds.replaceChildren(h('span', { class: 'hint' }, 'Searching didn’t work just now. Try again in a moment.')); return; }
      if (input.value.trim().toLowerCase() !== q) return;
      const hits = titles.filter(t => t.title.toLowerCase().includes(q) && !chosen.some(c => c.key === t.ratingKey)).slice(0, 8);
      finds.replaceChildren(...(hits.length ? hits.map(t => h('button', { type: 'button', class: 'chipbtn', 'aria-label': `Add ${t.title}${t.year ? ` (${t.year})` : ''}`, onclick: () => {
        chosen.push({ key: t.ratingKey, title: `${t.title}${t.year ? ` (${t.year})` : ''}` });
        input.value = '';
        finds.replaceChildren();
        paint();
        input.focus();
      } }, `+ ${t.title}${t.year ? ` (${t.year})` : ''} · ${t.type === 'show' ? 'Show' : 'Movie'}`)) : [h('span', { class: 'hint' }, 'No show or movie has that in its title.')]));
    }, 200);
  });
  paint();
  return h('div', { class: 'name-pick' }, input, finds, chips);
}
const ratingName = (list, age) => age == null ? 'No limit' : (list.find(([a]) => a === age)?.[1] || `Ages ${age} and up`);
function levelSelect(value, attrs = {}) {
  const select = h('select', attrs, ...(viewing?.levels || []).map(lv => h('option', { value: String(lv.id) }, lv.name)));
  select.value = String(value);
  return select;
}
let plexLibraries = null;  // (for choosing a level's libraries)
// What other apps show, whatever a level hides: the fact for every choice,
// naming the apps chosen; Block stations for some Plex users where it can
// work (1.36.0's words while nothing is chosen). [label, sentence]
function othersNote() {
  const named = appsNamed();
  const block = ' To keep stations from some people in Plex, use Block stations for some Plex users, below.';
  if (!named) return ['Plex and other apps. ', `Plex, Jellyfin and other apps don’t say who’s watching, so they show every station.${block}`];
  const said = named.none ? 'Apps other than tapiOca’s don’t say who’s watching, so they show every station.'
    : named.one ? `${named.text} doesn’t say who’s watching, so it shows every station.`
      : `${upFirst(named.text)} don’t say who’s watching, so they show every station.`;
  return ['Other apps. ', said + (status?.plex?.configured && watches('plex') ? block : '')];
}
// What Plex calls tags, where tapiOca uses Plex ('' where it doesn't).
function labelsNote() {
  return plexUsed() ? 'Plex calls these labels' : '';
}
function renderViewing() {
  const panel = $('#viewingPanel');
  panel.hidden = !me.required || !viewing;
  if (panel.hidden) return;
  const body = $('#viewingBody');
  const limited = viewing.levels.filter(levelLimited).length;
  $('#viewingSum').textContent = `${plural(viewing.levels.length, 'level')}${limited ? `, ${limited} with limits` : ''}`;
  if (body.dataset.editing) return;  // (not while one is being changed)
  const libraryNames = new Map((plexLibraries || []).map(l => [l.key, l.title]));
  const librariesText = lv => lv.libraries == null ? 'All'
    : lv.libraries.length ? lv.libraries.map(k => libraryNames.get(k) || `Media folder ${k}`).join(', ') : 'None';
  const table = h('table', { class: 'users' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Level'), h('th', {}, 'Movies up to'), h('th', {}, 'TV up to'), h('th', {}, 'Unrated'), h('th', {}, 'Media folders'), h('th', {}, 'Also hides'), h('th', {}, 'People'), h('th', {}, ''))),
    h('tbody', {}, ...viewing.levels.map(lv => h('tr', {},
      h('td', {}, h('strong', {}, lv.name)),
      h('td', { 'data-label': 'Movies up to' }, ratingName(viewing.movieRatings, lv.movieAge)),
      h('td', { 'data-label': 'TV up to' }, ratingName(viewing.tvRatings, lv.tvAge)),
      h('td', { 'data-label': 'Unrated' }, lv.unrated ? 'Shown' : 'Hidden'),
      h('td', { class: 'small', 'data-label': 'Media folders' }, librariesText(lv)),
      h('td', { class: 'small', 'data-label': 'Also hides', title: TAG_KINDS.map(([kind, name]) => (lv.blocks?.[kind] || []).length ? `${name}: ${lv.blocks[kind].join(', ')}` : '').filter(Boolean).join('\n') || null }, hidesSaid(lv.blocks) || 'Nothing more'),
      h('td', { 'data-label': 'People' }, String(lv.users)),
      h('td', {},
        lv.builtin === 'unrestricted' ? h('span', { class: 'hint' }, 'Shows everything') : [
        h('button', { class: 'btn', type: 'button', onclick: () => editLevel(lv) }, 'Edit'),
        ' ', h('button', { class: 'btn danger', type: 'button', onclick: async () => {
          if (!confirm(`Remove the Viewing Level ${lv.name}?`)) return;
          try { await api(`/api/access/levels/${lv.id}`, { method: 'DELETE' }); toast(`${lv.name} removed`); }
          catch (err) { toast(err.message, true); }
          loadAccess();
        } }, 'Remove')])))));
  // The level new people start on (1.34.1, the owner).
  const startsOn = levelSelect(viewing.newLevel, { id: 'newLevel', onchange: async e => {
    const id = Number(e.target.value);
    try {
      viewing.newLevel = (await api('/api/access/new-level', { method: 'PUT', body: { level: id } })).newLevel;
      toast(`New people start on ${viewing.levels.find(lv => lv.id === id)?.name || 'that level'}`);
      fillNewUserLevel();
    } catch (err) { toast(err.message, true); e.target.value = String(viewing.newLevel); }
  } });
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'A Viewing Level says what its people can see in tapiOca’s apps and on this page: movies and shows up to a rating, whether unrated ones are shown, which Media folders, and any genres, tags, collections or studios it hides. Unrestricted shows everything and stays as it is. Teen, Kid and Young Child are there to start from: rename them, change them or remove them, and add as many levels of your own as you need, such as “Adults” with no R-rated movies or unrated titles. Admins always see everything.'),
    h('div', { class: 'scan-set' }, h('label', { for: 'newLevel', class: 'small' }, h('strong', {}, 'New people start on')), startsOn,
      h('span', { class: 'hint' }, 'Unrestricted until you choose another. You can choose a level for each person as you add them, too.')),
    h('div', { class: 'limit-note' }, h('strong', {}, 'How it works'),
      h('ul', {},
        h('li', {}, h('strong', {}, 'Stations are all or nothing. '), 'Everyone watching a station sees the same stream, so a station is shown only if everything it plays is within the level. Choose What they see beside someone’s name to allow or block one for them anyway.'),
        h('li', {}, h('strong', {}, 'Watching only. '), 'People on a level with limits, or with anything hidden for them, watch what they can see, but can’t make stations.'),
        h('li', {}, h('strong', {}, othersNote()[0]), othersNote()[1]))),
    table,
    h('div', {}, h('button', { class: 'btn', type: 'button', onclick: () => editLevel(null) }, 'Add a level')),
    ...[clipRatingsBox()].filter(Boolean));
}
// Commercials and trailers under limits (1.33.0): each folder's rating.
let clipRatings = null;  // (from /api/access/clips, with the Access tab)
async function loadClipRatings() {
  try { clipRatings = await api('/api/access/clips'); } catch { clipRatings = null; }
}
const KIND_NAMES = { commercials: 'Commercials', trailers: 'Trailers' };
function clipRatingsBox() {
  const folders = (clipRatings?.folders || []).filter(f => f.clips > 0);
  if (!folders.length) return null;
  const result = h('span', { class: 'hint', role: 'alert' });
  const picks = new Map();
  const rows = folders.map(f => {
    const list = f.kind === 'commercials' ? clipRatings.tvRatings : clipRatings.movieRatings;
    const kindName = KIND_NAMES[f.kind];
    const select = h('select', { 'aria-label': f.decade ? `${kindName} from the ${f.decade}s, rated` : `${kindName}, rated` },
      h('option', { value: '' }, f.decade ? `As ${kindName.toLowerCase()} are` : 'Not rated'),
      ...list.map(([a, n]) => h('option', { value: String(a) }, n)));
    select.value = f.age == null ? '' : String(f.age);
    if (f.age != null && !list.some(([a]) => a === f.age)) select.append(h('option', { value: String(f.age), selected: true }, `Ages ${f.age} and up`));
    picks.set(f.key, select);
    return h('tr', {},
      h('td', {}, h('strong', {}, f.decade ? `${kindName} from the ${f.decade}s` : `${kindName}`), h('div', { class: 'hint' }, plural(f.clips, f.kind === 'commercials' ? 'commercial' : 'trailer'))),
      h('td', { 'data-label': 'Rated' }, select));
  });
  const save = async () => {
    const chosen = {};
    for (const [key, select] of picks) chosen[key] = select.value === '' ? null : Number(select.value);
    try { clipRatings = await api('/api/access/clips', { method: 'PUT', body: { ratings: chosen } }); }
    catch (err) { result.textContent = err.message; return; }
    toast('Commercial and trailer ratings saved');
    renderViewing();
  };
  return h('div', { class: 'limit-note clip-ratings' },
    h('strong', {}, 'Commercials and trailers'),
    h('p', { style: 'margin:6px 0 0' }, 'On a station someone with limits can see, a commercial or trailer plays only if its folder is rated, and at or below the station’s highest-rated program. Until then, those stations skip it. Give each folder the rating of its strongest clip. A decade’s folder is rated as its kind is, unless you rate it.'),
    h('table', { class: 'users' }, h('tbody', {}, ...rows)),
    h('div', { class: 'scan-set' }, h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save ratings'), result));
}
async function editLevel(lv) {
  const body = $('#viewingBody');
  if (!plexLibraries) {
    try { plexLibraries = (await api('/api/libraries')).filter(l => l.type === 'show' || l.type === 'movie'); }
    catch { plexLibraries = []; }
  }
  const offered = await loadTagsOffered();
  body.dataset.editing = '1';
  const hidden = blocksOf(lv?.blocks);
  const name = h('input', { type: 'text', maxlength: 40, value: lv?.name || '', placeholder: 'Grandparents', autocomplete: 'off', 'aria-label': 'Name' });
  const ratingSelect = (list, age, label) => {
    const select = h('select', { 'aria-label': label }, h('option', { value: '' }, 'No limit'), ...list.map(([a, n]) => h('option', { value: String(a) }, n)));
    select.value = age == null ? '' : String(age);
    if (age != null && !list.some(([a]) => a === age)) select.append(h('option', { value: String(age), selected: true }, `Ages ${age} and up`));
    return select;
  };
  const movies = ratingSelect(viewing.movieRatings, lv ? lv.movieAge : 13, 'Movies up to');
  const tv = ratingSelect(viewing.tvRatings, lv ? lv.tvAge : 14, 'TV up to');
  const unrated = h('select', { 'aria-label': 'Unrated titles' }, h('option', { value: 'shown' }, 'Shown'), h('option', { value: 'hidden' }, 'Hidden'));
  unrated.value = lv && lv.unrated ? 'shown' : (lv ? 'hidden' : 'hidden');
  const every = h('input', { type: 'radio', name: 'levelLibraries', checked: !lv || lv.libraries == null });
  const some = h('input', { type: 'radio', name: 'levelLibraries', checked: !!lv && lv.libraries != null });
  const boxes = plexLibraries.map(l => [l.key, h('input', { type: 'checkbox', checked: !!lv?.libraries?.includes(l.key) })]);
  const pick = h('div', { class: 'checks-col' }, ...boxes.map(([key, box]) => h('label', {}, box, ` ${plexLibraries.find(l => l.key === key).title}`)));
  const showPick = () => { pick.hidden = !some.checked; };
  every.addEventListener('change', showPick);
  some.addEventListener('change', showPick);
  showPick();
  const result = h('span', { class: 'hint', role: 'alert' });
  const done = () => { delete body.dataset.editing; renderViewing(); };
  const save = async () => {
    const chosen = {
      name: name.value.trim(),
      movieAge: movies.value === '' ? null : Number(movies.value),
      tvAge: tv.value === '' ? null : Number(tv.value),
      unrated: unrated.value === 'shown',
      libraries: some.checked ? boxes.filter(([, b]) => b.checked).map(([k]) => k) : null,
      blocks: hidden,
    };
    try {
      await api(lv ? `/api/access/levels/${lv.id}` : '/api/access/levels', { method: lv ? 'PUT' : 'POST', body: chosen });
    } catch (err) { result.textContent = err.message; return; }
    toast(lv ? `${chosen.name} saved` : `${chosen.name} added`);
    delete body.dataset.editing;
    loadAccess();
  };
  const row = (label, control, hint) => h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, label), h('div', { class: 'opt-ctl' }, control, hint ? h('span', { class: 'hint' }, hint) : null));
  body.replaceChildren(h('div', { class: 'playback level-edit' },
    h('strong', {}, lv ? `Edit ${lv.name}` : 'Add a level'),
    row('Name', name),
    row('Movies up to', movies),
    row('TV up to', tv, 'An episode counts as its show’s rating, or its own if that’s stricter.'),
    row('Unrated titles', unrated, 'Titles with no rating.'),
    row('Media folders', h('div', {}, h('label', {}, every, ' Every Media folder'), ' ', h('label', {}, some, ' Only these:'), pick)),
    h('p', { class: 'hint', style: 'margin:0' }, 'Also hide any show or movie with one of these, whatever its rating. A station that plays one is hidden too. Capital letters don’t matter.'),
    ...TAG_KINDS.map(([kind, label, noun]) => row(label, namePicker(`${label} ${lv ? lv.name : 'this level'} hides`, noun, hidden[kind], offered[kind] || []),
      kind === 'labels' && labelsNote() ? `${labelsNote()}.` : null)),
    h('div', { class: 'scan-set' },
      h('button', { class: 'btn primary', type: 'button', onclick: save }, lv ? 'Save' : 'Add'),
      h('button', { class: 'btn', type: 'button', onclick: done }, 'Cancel'),
      result)));
  name.focus();
}
// What a person sees: their stations, as their level says or allowed or
// blocked for them; and (1.33.0) what's hidden for them, and titles allowed
// for them, whatever their level says.
let stationsFor = null;
async function openUserStations(u) {
  let got, offered;
  try { [got, offered] = await Promise.all([api(`/api/access/users/${u.id}/stations`), loadTagsOffered()]); }
  catch (err) { toast(err.message, true); return; }
  const own = viewing?.users[u.id]?.own || {};
  stationsFor = { user: u, picks: new Map(), hidden: blocksOf(own.blocks), allowed: structuredClone(own.allowTitles || []) };
  $('#userStationsTitle').textContent = `What ${u.name} sees`;
  $('#userStationsStatus').textContent = '';
  const said = s => s.chosen === 'allowed' ? `Allowed for ${u.name}.${s.why ? ` (${got.level} wouldn’t show it: ${s.why.toLowerCase()}.)` : ''}`
    : s.chosen === 'blocked' ? `Blocked for ${u.name}.`
    : s.levelSees ? `Shown: it’s within ${got.level}.` : `Hidden: ${s.why.charAt(0).toLowerCase()}${s.why.slice(1)}.`;
  const part = (title, ...children) => h('section', { class: 'sees-part' }, h('h4', {}, title), ...children);
  $('#userStationsBody').replaceChildren(
    h('p', { style: 'margin:0' }, `${u.name} is on ${got.level}. They see what ${got.level} shows, except for what you choose for them here.`),
    ...(viewing?.users[u.id]?.ownUnreadable ? [h('p', { class: 'hint', role: 'alert', style: 'margin:0' }, `What was chosen for ${u.name} here couldn’t be read, so they see nothing for now. Choose it again and save.`)] : []),
    part('Stations',
      h('p', { class: 'hint', style: 'margin:0' }, `A station is shown or hidden as ${got.level} says, unless you allow or block it for ${u.name}.`),
      got.stations.length ? h('table', { class: 'users' },
        h('tbody', {}, ...got.stations.map(st => {
          const hint = h('span', { class: 'hint' }, said(st));
          const select = h('select', { 'aria-label': `Station ${st.number}`, onchange: e => {
            stationsFor.picks.set(st.id, e.target.value);
            hint.textContent = said({ ...st, chosen: e.target.value });
          } }, h('option', { value: 'level' }, `As ${got.level} says`), h('option', { value: 'allowed' }, 'Allowed'), h('option', { value: 'blocked' }, 'Blocked'));
          select.value = st.chosen;
          stationsFor.picks.set(st.id, st.chosen);
          return h('tr', {},
            h('td', {}, h('strong', {}, st.number), ` ${st.name}`),
            h('td', {}, select, h('div', {}, hint)));
        }))) : h('p', { class: 'muted', style: 'margin:0' }, 'There are no stations yet.')),
    part(`Also hidden for ${u.name}`,
      h('p', { class: 'hint', style: 'margin:0' }, `Hidden for ${u.name} whatever ${got.level} shows: in Media, and any station that plays one (unless you allow that station above).`),
      ...TAG_KINDS.map(([kind, label, noun]) => h('div', { class: 'field' }, h('label', {}, label, kind === 'labels' && labelsNote() ? h('span', { class: 'hint' }, ` — ${labelsNote()}`) : null),
        namePicker(`${label} hidden for ${u.name}`, noun, stationsFor.hidden[kind], offered[kind] || []))),
      h('div', { class: 'field' }, h('label', {}, 'Shows and movies'), titlePicker(`Shows and movies hidden for ${u.name}`, stationsFor.hidden.titles))),
    part(`Allowed for ${u.name} in Media`,
      h('p', { class: 'hint', style: 'margin:0' }, `Shown to ${u.name} in Media even if ${got.level} would hide them, as long as they’re in a Media folder ${got.level} shows. A show or movie hidden above stays hidden. Stations are as chosen above.`),
      titlePicker(`Shows and movies allowed for ${u.name}`, stationsFor.allowed)));
  $('#userStations').showModal();
}
const closeUserStations = () => { $('#userStations').close(); stationsFor = null; };
$('#closeUserStations').addEventListener('click', closeUserStations);
$('#cancelUserStations').addEventListener('click', closeUserStations);
$('#saveUserStations').addEventListener('click', async () => {
  if (!stationsFor) return;
  const stations = {};
  for (const [id, pick] of stationsFor.picks) if (pick !== 'level') stations[id] = pick === 'allowed';
  const own = { blocks: stationsFor.hidden, allowTitles: stationsFor.allowed };
  try { await api(`/api/access/users/${stationsFor.user.id}/viewing`, { method: 'PUT', body: { stations, own } }); }
  catch (err) { $('#userStationsStatus').textContent = err.message; return; }
  toast(`What ${stationsFor.user.name} sees is saved`);
  closeUserStations();
  loadAccess();
});
// A new name for someone (an Admin's, themselves included): signing in takes
// it from then on, and everything of theirs stays theirs.
function renameUser(u, cell) {
  const input = h('input', { type: 'text', value: u.name, maxlength: 40, autocomplete: 'off', 'aria-label': `New name for ${u.name}` });
  const save = async () => {
    const name = input.value.trim();
    if (!name || name === u.name) { loadAccess(); return; }
    try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { name } }); }
    catch (err) { toast(err.message, true); return; }
    toast(`${u.name} is now ${name}. They sign in as ${name} from now on.`);
    if (u.id === me.user?.id) await loadMe();
    loadAccess();
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') loadAccess();
  });
  cell.replaceChildren(h('div', { class: 'inline-add' }, input,
    h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'),
    h('button', { class: 'btn', type: 'button', onclick: loadAccess }, 'Cancel')));
  input.focus();
  input.select();
}
function newPassword(u, cell) {
  const input = h('input', { type: 'password', minlength: ACCESS.passwordMin, maxlength: ACCESS.passwordMax, autocomplete: 'new-password', placeholder: 'New password', 'aria-label': `New password for ${u.name}` });
  const save = async () => {
    try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { password: input.value } }); toast(`${u.name}’s password was changed, and they’re signed out everywhere`); loadAccess(); }
    catch (err) { toast(err.message, true); }
  };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  cell.replaceChildren(h('div', { class: 'inline-add' }, input,
    h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'),
    h('button', { class: 'btn', type: 'button', onclick: loadAccess }, 'Cancel')));
  input.focus();
}
// (The last Admin is never removed: the server says so, 1.36.0.)
async function removeUser(u) {
  if (!confirm(`Remove ${u.name}? They won’t be able to sign in anymore. Stations they made stay, and only Admins can change them.`)) return;
  try { await api(`/api/access/users/${u.id}`, { method: 'DELETE' }); toast(`${u.name} removed`); }
  catch (err) { toast(err.message, true); return; }
  await loadMe();
  if (me.required && !me.user) { showSignIn(); return; }
  loadAccess();
  loadChannels();
}
$('#addUserForm').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('#newUserName').value.trim();
  let added;
  try {
    const pin = $('#newUserPin').value.trim();
    const level = $('#newUserLevelField').hidden ? {} : { level: Number($('#newUserLevel').value) };
    added = await api('/api/access/users', { method: 'POST', body: { name, password: $('#newUserPassword').value, role: $('#newUserRole').value, maxStations: limitOf($('#newUserStations')), ...(pin ? { pin } : {}), ...level } });
  } catch (err) { $('#addUserHint').textContent = err.message; return; }
  $('#addUserForm').reset();
  $('#newUserStations').value = String(ACCESS.newUserStations);
  fillNewUserLevel();
  $('#addUserHint').textContent = '';
  const first = !me.required;
  await loadMe();
  // Someone who can't sign in by name starts on no device (an Admin chooses
  // theirs); with only a PIN, their first sign-in on a device takes an
  // invite code.
  const nowhere = added.showOn === 'selected' && !added.hasPassword && !added.pin;
  const invited = added.showOn === 'signed-in' && !added.hasPassword;
  toast(first ? `Sign-in is on, and you’re signed in as ${name}`
    : nowhere ? `${name} is added. With no password or PIN, they show on no device until you choose one in Devices.`
    : invited ? `${name} is added. To sign in on a device, they need an invite code: see Devices.` : `${name} is added`);
  loadAccess();
  loadChannels();
});
// The add-a-user form's Viewing Level: the levels, with the one new people
// start on chosen (for a User, while signing in is on).
function fillNewUserLevel() {
  const select = $('#newUserLevel');
  select.replaceChildren(...(viewing?.levels || []).map(lv => h('option', { value: String(lv.id) }, lv.name)));
  if (viewing) select.value = String(viewing.newLevel);
  showNewUserStations();
}
