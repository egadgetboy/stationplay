// Choosing a station's programs by filter, and the library's lists.
// Choosing by filter -----------------------------------------------------------
function setPickMode(mode, start = true) {
  pressOne('pick', mode);
  $('#titlePicker').hidden = mode !== 'titles';
  $('#filterPicker').hidden = mode !== 'filter';
  if (mode === 'filter' && start && !flt) initFilter();
}
document.querySelectorAll('[data-pick]').forEach(b => b.addEventListener('click', () => setPickMode(b.dataset.pick)));

let flt = null;             // the filter being built
let fItems = [];            // everything it matches (see /api/filter/preview), to choose from
let fFields = [];           // what the chosen libraries can be filtered on (from Plex)
let fDecades = [];
let previewSeq = 0;
let choicesSeq = 0;
// Lists longer than this are typed into rather than shown as buttons.
const MAX_CHIPS = 40;
function newFilter(kind) {
  return {
    type: 'filter', kind, libraries: libraries.filter(l => l.type === kind).map(l => l.key),
    tags: {}, decade: [], titleContains: '', addedWithinDays: 0, minRating: 0, exclude: [],
  };
}
// Returns whether the filter builder is ready.
async function initFilter(existing = null) {
  if (!libraries.length) {
    try { libraries = await api('/api/libraries'); }
    catch (e) { $('#fCount').textContent = e.message; return false; }
  }
  if (existing) {
    // Fill in anything a filter saved some other way leaves out, and move
    // tags saved the pre-1.6 way into "tags".
    const kind = existing.kind === 'show' ? 'show' : 'movie';
    const old = structuredClone(existing);
    flt = { ...newFilter(kind), ...old, kind, tags: { ...(old.tags || {}) } };
    for (const t of TAGS) { if (Array.isArray(old[t]) && old[t].length) flt.tags[t] = old[t]; delete flt[t]; }
    if (!Array.isArray(flt.decade)) flt.decade = [];
    if (!Array.isArray(flt.libraries)) flt.libraries = newFilter(kind).libraries;
    flt.titleContains = String(flt.titleContains || '');
    flt.addedWithinDays = Number(flt.addedWithinDays) || 0;
    flt.minRating = Number(flt.minRating) || 0;
    if (!Array.isArray(flt.exclude)) flt.exclude = [];
  } else {
    flt = newFilter(flt?.kind || 'movie');
  }
  delete flt.title;
  fFields = []; fDecades = [];
  renderFilter();
  await loadChoices();
  return true;
}
async function loadChoices() {
  const seq = ++choicesSeq;
  if (!flt.libraries.length) { fFields = []; fDecades = []; renderFilter(); updateCount(); return; }
  let res;
  try { res = await api(`/api/filter/fields?kind=${flt.kind}&libraries=${flt.libraries.join(',')}`); }
  catch (e) {
    if (seq === choicesSeq) $('#fCount').textContent = e.message;
    return;
  }
  if (seq !== choicesSeq) return;  // the libraries or kind changed meanwhile
  fFields = res.fields; fDecades = res.decade;
  renderFilter();
  updateCount();
}
// (Once the libraries have been chosen: not for each click on the way.)
let choicesTimer;
function loadChoicesSoon() { clearTimeout(choicesTimer); choicesTimer = setTimeout(loadChoices, 300); }
function toggleIn(list, value) {
  const i = list.indexOf(value);
  if (i >= 0) list.splice(i, 1); else list.push(value);
}
const changed = () => { renderFilter(); updateCount(); };
function chipFor(list, value, label = value) {
  return h('button', {
    type: 'button', class: 'chipbtn', 'aria-pressed': String(list.includes(value)),
    onclick: () => { toggleIn(list, value); changed(); },
  }, label);
}
const picked = f => (flt.tags[f] ||= []);
// One filter (genre, network...): buttons for a short list; otherwise type a
// name (the choices, or for people a search of Plex) and add it.
function fieldBox(f) {
  const values = picked(f.field);
  const label = h('label', {}, f.title, h('span', { class: 'hint' }, ' — any of these'));
  if (!f.search && f.choices.length <= MAX_CHIPS) {
    const offered = [...new Set([...f.choices, ...values])];
    return h('div', { class: 'field' }, label, h('div', { class: 'chips' }, ...offered.map(v => chipFor(values, v))));
  }
  const listId = `fl-${f.field}`;
  const input = h('input', { type: 'text', list: listId, placeholder: f.search ? 'Type a name' : `Type to find ${/^[aeiou]/i.test(f.title) ? 'an' : 'a'} ${f.title.toLowerCase()}`, autocomplete: 'off' });
  const list = h('datalist', { id: listId }, ...(f.search ? [] : f.choices.map(c => h('option', { value: c }))));
  const add = () => {
    const name = input.value.trim();
    if (name && !values.includes(name)) { values.push(name); changed(); }
    input.value = '';
  };
  let timer = null;
  if (f.search) input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (q.length < 2 || !flt.libraries.length) return;
      try {
        const names = await api(`/api/filter/search?kind=${flt.kind}&libraries=${flt.libraries.join(',')}&field=${f.field}&q=${encodeURIComponent(q)}`);
        list.replaceChildren(...names.map(n => h('option', { value: n })));
      } catch {}
    }, 250);
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  return h('div', { class: 'field' }, label,
    h('div', { class: 'inline-add' }, input, list, h('button', { type: 'button', class: 'btn', onclick: add }, 'Add')),
    h('div', { class: 'chips' }, ...values.map(name => h('span', { class: 'sel' }, h('span', {}, name),
      h('button', { type: 'button', 'aria-label': `Remove ${name}`, onclick: () => { toggleIn(values, name); changed(); } }, '×')))));
}
function renderFilter() {
  pressOne('fkind', flt.kind);
  const libs = libraries.filter(l => l.type === flt.kind);
  $('#fLibs').replaceChildren(...(libs.length ? libs.map(l => h('button', {
    type: 'button', class: 'chipbtn', 'aria-pressed': String(flt.libraries.includes(l.key)),
    onclick: () => { toggleIn(flt.libraries, l.key); renderFilter(); loadChoicesSoon(); },
  }, l.title)) : [h('span', { class: 'hint' }, `Plex has no ${flt.kind === 'show' ? 'TV' : 'movie'} libraries.`)]));
  // Anything already chosen stays visible even if these libraries don't offer it.
  const shown = [...fFields];
  for (const [field, values] of Object.entries(flt.tags)) {
    if (values.length && !shown.some(f => f.field === field)) shown.push({ field, title: field, choices: [] });
  }
  $('#fFields').replaceChildren(...shown.map(fieldBox));
  const decades = [...new Set([...fDecades, ...flt.decade])].sort();
  $('#fDecade').replaceChildren(...(decades.length ? decades.map(d => chipFor(flt.decade, d, `${d}s`)) : [h('span', { class: 'hint' }, '—')]));
  if ($('#fTitle').value !== flt.titleContains) $('#fTitle').value = flt.titleContains;
  $('#fAdded').value = flt.addedWithinDays || '';
  $('#fAddedHint').textContent = flt.kind === 'show'
    ? 'Episodes added to Plex in that time, from any matching show (e.g., 30 for a New Arrivals station).'
    : 'Movies added to Plex in that time (e.g., 30 for a New Arrivals station).';
  $('#fRating').value = String(flt.minRating || 0);
  if ($('#smart').open) renderSmartSplit();
}
document.querySelectorAll('[data-fkind]').forEach(b => b.addEventListener('click', () => {
  if (flt.kind === b.dataset.fkind) return;
  flt = newFilter(b.dataset.fkind);
  fFields = []; fDecades = [];
  renderFilter();
  loadChoices();
}));
$('#fAdded').addEventListener('change', () => {
  flt.addedWithinDays = Math.max(0, Math.min(3650, Math.round(Number($('#fAdded').value) || 0)));
  changed();
});
$('#fRating').addEventListener('change', () => { flt.minRating = Number($('#fRating').value) || 0; changed(); });
let titleTimer = null;
$('#fTitle').addEventListener('input', () => {
  clearTimeout(titleTimer);
  titleTimer = setTimeout(() => { flt.titleContains = $('#fTitle').value.trim(); updateCount(); }, 300);
});
let countTimer = null;
function updateCount() {
  // Anything already on its way back is out of date now.
  clearTimeout(countTimer);
  const seq = ++previewSeq;
  $('#fCount').textContent = flt.libraries.length ? 'Checking Plex…' : 'Choose at least one library.';
  if (!flt.libraries.length) return;
  countTimer = setTimeout(async () => {
    try {
      const res = await api('/api/filter/preview', { method: 'POST', body: flt });
      if (seq !== previewSeq) return;
      fItems = res.items;
      showCount();
      renderReview();
      if ($('#smart').open) smartChanged();
    } catch (e) { if (seq === previewSeq) $('#fCount').textContent = e.message; }
  }, 250);
}
// How many match, as ticked in the list below.
function showCount() {
  const shown = fItems.filter(i => i.included);
  const what = flt.kind === 'show' ? 'show' : 'movie';
  const eps = flt.kind === 'show' ? ` (${shown.reduce((n, i) => n + i.episodes, 0).toLocaleString()} episodes)` : '';
  const out = fItems.length - shown.length;
  // (Their names, unless they're all listed below.)
  const names = $('#fReview').hidden ? shown.slice(0, 12).map(i => i.title + (i.year ? ` (${i.year})` : '')) : [];
  $('#fCount').textContent = shown.length
    ? `${plural(shown.length, what)}${eps} match${shown.length === 1 ? 'es' : ''}${out ? `, ${out} left out` : ''}${names.length ? `: ${names.join(', ')}${shown.length > names.length ? '…' : ''}` : '.'}`
    : fItems.length ? `All matches are left out (${plural(fItems.length, what)}).` : `No ${what}s match yet.`;
  $('#fReviewOpen').hidden = !fItems.length;
  $('#fReviewOpen').textContent = $('#fReview').hidden ? 'Choose which…' : 'Done choosing';
}
// Every match, ticked unless it's left out.
function renderReview() {
  if ($('#fReview').hidden) return;
  $('#fMatches').replaceChildren(...fItems.map(it => h('label', { class: 'pick' },
    h('input', { type: 'checkbox', checked: it.included, onchange: e => include([it], e.target.checked) }),
    ...titleCells(it),
    h('span', { class: 'hint' }, flt.kind === 'show' ? plural(it.episodes, 'episode') : ''))));
}
function include(items, on) {
  const keys = new Set(items.flatMap(i => i.ratingKeys));
  flt.exclude = flt.exclude.filter(k => !keys.has(k));
  if (!on) flt.exclude.push(...keys);
  for (const it of items) it.included = on;
  showCount();
}
$('#fReviewOpen').addEventListener('click', () => {
  $('#fReview').hidden = !$('#fReview').hidden;
  showCount();
  renderReview();
});
$('#fReviewAll').addEventListener('click', () => { include(fItems, true); renderReview(); });
$('#fReviewNone').addEventListener('click', () => { include(fItems, false); renderReview(); });
// A filter as it's saved: no empty lists or unused settings.
function tidyFilter(f) {
  const source = structuredClone(f);
  delete source.title;
  for (const [field, values] of Object.entries(source.tags)) if (!values.length) delete source.tags[field];
  if (!source.addedWithinDays) delete source.addedWithinDays;
  if (!source.minRating) delete source.minRating;
  if (!source.exclude?.length) delete source.exclude;
  return source;
}
function describeFilter(f) {
  const or = xs => xs.join(' or ');
  const titleOf = field => fFields.find(x => x.field === field)?.title || field;
  const bits = [];
  for (const [field, values] of Object.entries(f.tags || {})) {
    if (!values.length) continue;
    if (field === 'genre') bits.push(or(values));
    else if (field === 'director') bits.push(`directed by ${or(values)}`);
    else if (field === 'actor') bits.push(`with ${or(values)}`);
    else if (field === 'collection') bits.push(`in ${or(values)}`);
    else if (field === 'label') bits.push(`labeled ${or(values)}`);
    else bits.push(`${titleOf(field)} ${or(values)}`);
  }
  if (f.decade?.length) bits.push(or(f.decade.map(d => `${d}s`)));
  if (f.titleContains) bits.push(`“${f.titleContains}” in the title`);
  if (f.minRating) bits.push(`rated ${f.minRating}+`);
  if (f.addedWithinDays) bits.push(`${f.kind === 'show' ? 'episodes ' : ''}added in the last ${f.addedWithinDays} days`);
  const what = f.kind === 'show' ? 'TV shows' : 'Movies';
  const from = libraries.filter(l => f.libraries.includes(l.key)).map(l => l.title).join(', ');
  const left = f.exclude?.length ? ` (${fItems.filter(i => !i.included).length || f.exclude.length} left out)` : '';
  return (bits.length ? `${what}: ${bits.join(', ')}` : `All ${what.toLowerCase()} in ${from}`) + left;
}
$('#addFilter').addEventListener('click', () => {
  if (!flt.libraries.length) { $('#fCount').textContent = 'Choose at least one library.'; return; }
  flt.titleContains = $('#fTitle').value.trim();
  const source = { ...tidyFilter(flt), title: describeFilter(flt) };
  sources = sources.filter(s => sourceKey(s) !== sourceKey(source));
  sources.push(source);
  renderSelected();
  toast('Filter added. New matches in Plex join the station automatically.');
  flt = newFilter(flt.kind);
  $('#fReview').hidden = true;
  renderFilter();
  updateCount();
});

function nextNumber() {
  const used = new Set(channels.map(c => c.number));
  let n = 1; while (used.has(n)) n++; return n;
}

async function loadLibItems() {
  const key = $('#libSelect').value;
  if (!key) return;
  if (!libCache.has(key)) {
    $('#libItems').replaceChildren(h('p', { class: 'hint', style: 'padding:12px' }, 'Loading…'));
    try { libCache.set(key, await api(`/api/libraries/${key}/items`)); }
    catch (e) { $('#libItems').replaceChildren(h('p', { class: 'hint', style: 'padding:12px' }, e.message)); return; }
  }
  renderLibItems();
}
$('#libSelect').addEventListener('change', loadLibItems);
// Wait for a pause in typing before filtering a long list.
let filterTimer = null;
$('#libSearch').addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(renderLibItems, 120);
});

// The most shows or movies listed at once; type in the filter to find others.
const MAX_LISTED = 3000;
// What the filter looks through for each show or movie: its title, genres
// and year (every word typed has to be in one of them).
const searchTexts = new WeakMap();
function searchText(it) {
  let text = searchTexts.get(it);
  if (text === undefined) {
    text = [it.title, ...(it.genres || []), it.year || ''].join('\n').toLowerCase();
    searchTexts.set(it, text);
  }
  return text;
}

function renderLibItems() {
  const key = $('#libSelect').value;
  const lib = libraries.find(l => l.key === key);
  const items = libCache.get(key);
  if (!lib || !items) return;
  const q = $('#libSearch').value.trim().toLowerCase();
  const chosen = new Set(sources.map(sourceKey));
  const allKey = `section:${lib.key}`;
  const rows = [];
  let listed = 0;
  if (!q) {
    rows.push(h('label', { class: 'pick all' },
      h('input', { type: 'checkbox', checked: chosen.has(allKey), onchange: e => toggleSource({ type: 'section', key: lib.key, sectionType: lib.type, title: lib.title }, e.target.checked) }),
      h('span', { class: 'poster' }),
      h('span', { class: 't' }, `Everything in ${lib.title}`),
      h('span', { class: 'hint' }, plural(items.length, lib.type === 'show' ? 'show' : 'movie'))));
  }
  const words = q.split(/\s+/).filter(Boolean);
  const onStations = stationsWithTitles();
  for (const it of items) {
    if (words.length && !words.every(w => searchText(it).includes(w))) continue;
    if (listed === MAX_LISTED) {
      rows.push(h('p', { class: 'hint', style: 'padding:8px 12px' }, `Showing the first ${MAX_LISTED.toLocaleString()}. Type to filter.`));
      break;
    }
    listed++;
    const src = { type: it.type, ratingKey: it.ratingKey, title: it.title };
    const on = onStations.get(String(it.ratingKey));
    rows.push(h('label', { class: 'pick' },
      h('input', { type: 'checkbox', checked: chosen.has(sourceKey(src)), onchange: e => toggleSource(src, e.target.checked) }),
      ...titleCells(it, posterZoom === 3, on ? h('span', { class: 'onair', title: `Already on ${on.map(c => `station ${c.number} (${c.name})`).join(', ')}` },
        `Already on ${noun(on.length, 'station')} ${on.map(c => c.number).join(', ')}`) : null),
      h('span', { class: 'hint' }, it.type === 'show' ? `${it.episodes ?? '?'} episodes` : (it.durationMs ? fmtDur(it.durationMs) : ''))));
  }
  $('#libItems').className = `picker-list zoom-${posterZoom}`;
  $('#libItems').replaceChildren(...(rows.length ? rows : [h('p', { class: 'hint', style: 'padding:12px' }, 'No matches.')]));
}
// The other stations each show or movie is on (picked as itself, not by a
// filter or a whole library): {rating key: [stations]}.
function stationsWithTitles() {
  const on = new Map();
  for (const c of channels) {
    if (editing && c.id === editing.id) continue;
    for (const s of c.sources || []) {
      if (s.type !== 'show' && s.type !== 'movie') continue;
      const key = String(s.ratingKey);
      if (!on.has(key)) on.set(key, []);
      if (!on.get(key).includes(c)) on.get(key).push(c);
    }
  }
  for (const list of on.values()) list.sort((a, b) => a.number - b.number);
  return on;
}
// How large the list's posters are (1 to 3), remembered in this browser.
const ZOOM_KEY = 'stationplay.posterZoom';
let posterZoom = 1;
try { posterZoom = [1, 2, 3].includes(Number(localStorage.getItem(ZOOM_KEY))) ? Number(localStorage.getItem(ZOOM_KEY)) : 1; } catch {}
function setPosterZoom(z) {
  posterZoom = z;
  pressOne('zoom', String(z));
  try { localStorage.setItem(ZOOM_KEY, String(z)); } catch {}
  renderLibItems();
}
document.querySelectorAll('[data-zoom]').forEach(b => b.addEventListener('click', () => setPosterZoom(Number(b.dataset.zoom))));
pressOne('zoom', String(posterZoom));

// A show or movie in a list: its poster (fetched as it scrolls into view),
// and its title, year and genres.
function posterOf(it, big = false) {
  if (!it.poster && !it.ratingKeys) return h('span', { class: 'poster' });
  const key = it.ratingKey ?? it.ratingKeys[0];
  return h('img', {
    class: 'poster', src: `/poster/${key}${big ? '?big=1' : ''}`, alt: '', loading: 'lazy', decoding: 'async',
    onerror: e => e.target.replaceWith(h('span', { class: 'poster' })),
  });
}
function titleCells(it, big = false, note = null) {
  return [
    posterOf(it, big),
    h('span', { class: 't' },
      h('span', {}, it.title, it.year ? h('span', { class: 'hint' }, ` (${it.year})`) : null),
      it.genres?.length ? h('span', { class: 'genres' }, it.genres.join(' · ')) : null,
      note),
  ];
}

function toggleSource(src, on) {
  const k = sourceKey(src);
  sources = sources.filter(s => sourceKey(s) !== k);
  if (on) sources.push(src);
  renderSelected();
}

// The editor as you left it, to tell whether closing it would lose
// anything: what StationPlay fills in by itself for a new station (its name
// from its only show, a logo you didn't choose) doesn't count.
let editorSnapshot = '';
function editorState() {
  const name = $('#fName').value.trim(), number = $('#fNumber').value;
  return JSON.stringify({
    number,
    name: editing || (name !== autoName && name !== `Station ${number}`) ? name : '',
    logo: logoChosen ? logo : '',
    sources: stationPicks(), picture, subs, order, aspect, skipIntros, breaks, stationId, idSeconds, idSound,
    mark, markSize, markTrans, markPos, markTime, markStyle, clockFormat,
    introKind, introLength, introSound, introVideo, tuneIn, upNextSeconds, upNextSize,
    marathonMode, marathonsAWeek, marathonDays: marathonDaysText(), marathonTime, marathonEpisodes,
    featureMode, featureDays: daysText(featureDays), featureTime, featureSource, blocks: blocksBody(),
    description: $('#fDescription').value.trim(),
  });
}
const keepEditing = () => editorState() !== editorSnapshot
  && !confirm(editing ? `Close without saving your changes to ${editing.name}?` : 'Close without saving this new station?');
$('#editor').addEventListener('cancel', e => { if (keepEditing()) e.preventDefault(); });

$('#editorForm').addEventListener('submit', async e => {
  if (e.submitter?.value === 'cancel') {
    if (keepEditing()) e.preventDefault();
    return;
  }
  e.preventDefault();
  finishPicking();
  if (!sources.length) { $('#editorStatus').textContent = 'Pick at least one show or movie, or add a filter.'; return; }
  const unnamed = blocks.find(b => !b.name.trim());
  const empty = blocks.find(b => !b.sources.length);
  if (unnamed || empty) {
    $('#groupSpecials').open = true;
    $('#editorStatus').textContent = unnamed ? 'Give each block a name.' : `Choose what “${empty.name.trim()}” plays.`;
    return;
  }
  if (introKind === 'video' && !introVideo) { $('#editorStatus').textContent = 'Upload a video for the Intro Bumper, or choose Built-in card or Off.'; return; }
  const btn = $('#saveChannel');
  btn.disabled = true;
  let chosen;
  try {
    chosen = await settledLogo();
  } catch (err) {
    $('#editorStatus').textContent = `Couldn’t add the logo from Plex (${err.message}). Choose another logo.`;
    btn.disabled = false;
    return;
  }
  const body = {
    number: Number($('#fNumber').value),
    name: $('#fName').value.trim(),
    picture,
    subtitles: subs,
    orderMode: order,
    aspectMode: aspect,
    skipIntros,
    breaks,
    stationId,
    idSeconds,
    idSound,
    watermark: mark,
    watermarkSize: markSize,
    watermarkTransparency: markTrans,
    watermarkPosition: markPos,
    watermarkTiming: markTime,
    watermarkStyle: markStyle,
    clockFormat,
    introSeconds: introKind === 'off' ? 0 : introLength,
    introSound,
    introVideo: introKind === 'video' ? introVideo : '',
    tuneIn,
    description: $('#fDescription').value.trim(),
    upNextSeconds,
    upNextSize,
    marathonMode,
    marathonsAWeek,
    marathonDays: marathonDaysText(),
    marathonTime,
    marathonEpisodes,
    featureMode,
    featureDays: daysText(featureDays),
    featureTime,
    featureSource,
    blocks: blocksBody(),
    logo: chosen,
    sources,
  };
  $('#editorStatus').textContent = 'Building the schedule from Plex…';
  try {
    const res = editing
      ? await api(`/api/channels/${editing.id}`, { method: 'PUT', body })
      : await api('/api/channels', { method: 'POST', body });
    $('#editor').close();
    if (editing) toast(res.changed ? changedMessage(res) : 'Station saved');
    else madeNotice([res]);
    loadChannels();
  } catch (err) {
    $('#editorStatus').textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});
$('#newChannel').addEventListener('click', () => openEditor());
