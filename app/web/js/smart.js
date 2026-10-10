// Stations made from Plex collections, and Smart stations.
// Stations from Plex collections ---------------------------------------------
// One per collection: {ratingKey, name (numbered if others share it), kind,
// count, smart, libraryTitle, station}.
let collections = [];
let colPicked = new Set();  // rating keys
const KIND_WORDS = { movie: ['movie', 'movies'], show: ['show', 'shows'], season: ['season', 'seasons'], episode: ['episode', 'episodes'] };
function describeCollection(c) {
  const [one, many] = KIND_WORDS[c.kind] || [c.kind, c.kind];
  return `${c.count.toLocaleString()} ${c.count === 1 ? one : many} · ${c.libraryTitle}${c.smart ? ' · smart collection' : ''}`;
}
function updateColMake() {
  const n = colPicked.size;
  $('#colMake').disabled = !n;
  $('#colMake').textContent = n > 1 ? `Make ${n} stations` : 'Make station';
}
function renderCollections() {
  const q = $('#colSearch').value.trim().toLowerCase();
  const shown = collections.filter(c => !q || c.name.toLowerCase().includes(q));
  $('#colList').replaceChildren(...(shown.length
    ? shown.map(c => h('label', { class: c.station ? 'pick done' : 'pick' },
        h('input', { type: 'checkbox', disabled: Boolean(c.station), checked: Boolean(c.station) || colPicked.has(c.ratingKey),
          onchange: e => { if (e.target.checked) colPicked.add(c.ratingKey); else colPicked.delete(c.ratingKey); updateColMake(); } }),
        h('span', { class: 't' }, c.name),
        h('span', { class: 'hint' }, c.station ? `Station ${c.station}` : describeCollection(c))))
    : [h('p', { class: 'hint', style: 'padding:8px 12px' }, collections.length ? 'No collections match your search.' : 'Plex has no collections in your TV or movie libraries.')]));
}
$('#fromCollections').addEventListener('click', async () => {
  collections = [];
  colPicked = new Set();
  updateColMake();
  $('#colSearch').value = '';
  $('#colList').replaceChildren();
  $('#colStatus').textContent = 'Getting collections from Plex…';
  $('#collections').showModal();
  try {
    collections = await api('/api/collections');
    $('#colStatus').textContent = '';
    renderCollections();
  } catch (e) { $('#colStatus').textContent = e.message; }
});
$('#colSearch').addEventListener('input', renderCollections);
for (const id of ['#closeCollections', '#colCancel']) $(id).addEventListener('click', () => $('#collections').close());
$('#colMake').addEventListener('click', async () => {
  $('#colMake').disabled = true;
  $('#colStatus').textContent = 'Building the schedules from Plex…';
  try {
    const res = await api('/api/collections/stations', { method: 'POST', body: { ratingKeys: [...colPicked] } });
    $('#collections').close();
    madeNotice(res.made, res.problems);
    loadChannels();
  } catch (e) {
    $('#colStatus').textContent = e.message;
    updateColMake();
  }
});
// Smart stations -----------------------------------------------------------------
// Stations made from a filter (the station editor's filter builder, borrowed
// while this is open): one, or one for each decade, genre, studio… its
// matches fall into (see smart.py).
let smartMode = 'one', smartGroups = [], smartSeq = 0;
const smartField = () => $('#smartSplit').value || 'decade';
async function openSmart() {
  smartMode = 'one';
  smartGroups = [];
  $('#smartStatus').textContent = '';
  $('#smartFrom').value = nextNumber();
  $('#smartFilter').append($('#filterPicker'));
  $('#filterPicker').hidden = false;
  $('#addFilter').hidden = true;
  $('#fReview').hidden = true;
  $('#smartSplit').replaceChildren();
  $('#smart').showModal();
  flt = null;
  renderSmart();
  await initFilter();
}
// The editor gets its filter builder back.
$('#smart').addEventListener('close', () => {
  $('#titlePicker').after($('#filterPicker'));
  $('#filterPicker').hidden = true;
  $('#addFilter').hidden = false;
  $('#fReview').hidden = true;
  flt = null;
  smartSeq++;
});
// What it can be split by: decade, and what Plex has for these libraries.
function renderSmartSplit() {
  const was = $('#smartSplit').value;
  const fields = [{ field: 'decade', title: 'Decade' }, ...fFields];
  $('#smartSplit').replaceChildren(...fields.map(f => h('option', { value: f.field }, f.title)));
  $('#smartSplit').value = fields.some(f => f.field === was) ? was : 'decade';
}
// A station's name from what it plays: "1980s Comedy", "Studio Ghibli ·
// Adventure", "Action & Comedy" (each can be changed before it's made).
function smartName(value) {
  const field = smartMode === 'split' ? smartField() : null;
  const decades = field === 'decade' ? [value] : flt.decade;
  const decade = decades.length === 1 ? `${decades[0]}s` : '';
  const named = Object.entries(flt.tags).filter(([f, vs]) => vs.length && f !== field).flatMap(([, vs]) => vs);
  const rest = named.length > 2 ? `${named.slice(0, 2).join(' & ')} & more` : named.join(' & ');
  const kind = flt.kind === 'show' ? 'TV' : 'Movies';
  let name;
  if (field && field !== 'decade') name = rest || decade ? `${value} · ${[decade, rest].filter(Boolean).join(' ')}` : `${value}`;
  else name = [decade, rest || (flt.titleContains ? `“${flt.titleContains}”` : kind)].filter(Boolean).join(' ');
  return name.slice(0, 60);
}
function smartChanged() {
  if (smartMode === 'one') {
    const shown = fItems.filter(i => i.included);
    smartGroups = flt.libraries.length && shown.length
      ? [{ value: null, name: smartGroups[0]?.edited ? smartGroups[0].name : smartName(null), edited: smartGroups[0]?.edited, matches: shown.length, episodes: shown.reduce((n, i) => n + i.episodes, 0), on: true }]
      : [];
    renderSmart();
    return;
  }
  smartSplitNow();
}
let smartTimer, smartAsking = null, smartLimited = '';
const SMART_MOST = 50;  // stations made at once (smart.MAX_STATIONS)
function smartSplitNow() {
  clearTimeout(smartTimer);
  smartAsking?.abort();  // (an older question to Plex isn't wanted any more)
  smartAsking = null;
  const seq = ++smartSeq;
  smartGroups = [];
  smartLimited = '';
  renderSmart('Checking Plex…');
  if (!flt?.libraries.length) { renderSmart(); return; }
  smartTimer = setTimeout(async () => {
    const asking = smartAsking = new AbortController();
    try {
      const res = await api('/api/smart/split', { method: 'POST', body: { filter: tidyFilter(flt), split: smartField() }, signal: asking.signal });
      if (seq !== smartSeq) return;
      smartGroups = res.groups.map(g => ({ ...g, name: smartName(g.value), on: true }));
      smartLimited = res.limited ? `Only the ${res.most} with the most matches are listed.` : '';
      renderSmart();
    } catch (e) { if (seq === smartSeq && e.name !== 'AbortError') renderSmart(e.message); }
  }, 300);
}
function renderSmart(note = '') {
  pressOne('smart', smartMode);
  $('#smartSplit').hidden = smartMode !== 'split';
  const what = flt?.kind === 'show' ? 'show' : 'movie';
  const field = smartField();
  const people = fFields.find(f => f.field === field)?.search;
  $('#smartHint').textContent = smartMode === 'one'
    ? 'One station with everything the filter above matches.'
    : field === 'decade'
      ? `A station for each decade with matches${flt?.kind === 'show' ? ' (TV shows count by the year they started)' : ''}. Each also uses the rest of the filter.`
      : people
        ? 'A station for each one you chose above (or, if you chose none, the ones with the most matches). Each also uses the rest of the filter.'
        : 'A station for each one with matches (or each one you chose above), listed with the most matches first. Each also uses the rest of the filter.';
  const rows = smartGroups.map(g => h('label', { class: 'smart-group' },
    h('input', { type: 'checkbox', checked: g.on, 'aria-label': `Make ${g.name}`, onchange: e => { g.on = e.target.checked; renderSmart(); } }),
    h('input', { type: 'text', value: g.name, maxlength: 60, 'aria-label': 'Station name', oninput: e => { g.name = e.target.value; g.edited = true; } }),
    h('span', { class: 'hint' }, `${plural(g.matches, what)}${g.episodes ? ` · ${g.episodes.toLocaleString()} episodes` : ''}`)));
  const count = smartGroups.filter(g => g.on && g.matches).length;
  const notes = [smartMode === 'split' ? smartLimited : '', count > SMART_MOST ? `You can make up to ${SMART_MOST} at once. Uncheck some.` : '']
    .filter(Boolean).map(words => h('p', { class: 'hint', style: 'margin:0' }, words));
  $('#smartGroups').replaceChildren(...(rows.length ? [...rows, ...notes] : note ? [h('p', { class: 'hint', style: 'margin:0' }, note)] : []));
  $('#smartMake').disabled = !count || count > SMART_MOST;
  $('#smartMake').textContent = count > 1 ? `Make ${count} stations` : 'Make station';
}
document.querySelectorAll('[data-smart]').forEach(b => b.addEventListener('click', () => {
  if (smartMode === b.dataset.smart) return;
  smartMode = b.dataset.smart;
  smartGroups = [];
  if (flt) smartChanged(); else renderSmart();
}));
$('#smartSplit').addEventListener('change', () => { if (flt) smartSplitNow(); });
$('#smartStations').addEventListener('click', openSmart);
for (const id of ['#closeSmart', '#smartCancel']) $(id).addEventListener('click', () => $('#smart').close());
$('#smartMake').addEventListener('click', async () => {
  const chosen = smartGroups.filter(g => g.on && g.matches);
  const field = smartField();
  const base = tidyFilter(flt);
  const stations = chosen.map(g => {
    const source = smartMode === 'split' ? narrowed(base, field, g.value) : structuredClone(base);
    return { name: g.name.trim(), source: { ...source, title: describeFilter({ ...flt, ...source, tags: { ...source.tags } }) } };
  });
  $('#smartMake').disabled = true;
  $('#smartStatus').textContent = `Building ${stations.length === 1 ? 'the schedule' : `schedules for ${stations.length} stations`} from Plex…`;
  try {
    const res = await api('/api/smart/stations', { method: 'POST', body: { firstNumber: Number($('#smartFrom').value) || 1, stations } });
    $('#smart').close();
    madeNotice(res.made, res.problems);
    loadChannels();
  } catch (e) {
    $('#smartStatus').textContent = e.message;
    renderSmart();
  }
});
// A filter narrowed to one decade or one tag (as smart.with_value does).
function narrowed(source, field, value) {
  const out = structuredClone(source);
  if (field === 'decade') out.decade = [value];
  else out.tags = { ...(out.tags || {}), [field]: [String(value)] };
  return out;
}
