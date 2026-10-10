// A station's logo, and your own logos.
// Logos ------------------------------------------------------------------------
let logo = '';              // the chosen logo's id; '' shows the station number
let logoCatalog = null;
const YOURS = 'Your logos';  // the category of logos you've uploaded
const SUGGESTED = 'Suggested';
// Letters and numbers say nothing on their own: never picked at random.
const LETTERING = new Set(['Letters', 'Numbers', 'Retro letters', 'Retro numbers']);
// (LOGO_V, COLLECTION_LOGO, NEW_STATION, FEATURE_CARD_S and ACCESS: filled in by
// the server, in index.html.)
let logoCategory = 'All';
// A show's or movie's logo from Plex that's the station's, but not yet one
// of your logos: FROM_PLEX and its rating key. (It's added when the station
// is saved, or previewed.)
const FROM_PLEX = 'plex:';
const logoSrc = id => id.startsWith(FROM_PLEX) ? plexLogoPicture
  : id.startsWith('upload-') ? `/logos/${id}.png` : `/logos/${id}.png?v=${LOGO_V}`;
const numberLogo = n => (Number.isInteger(n) && n >= 1 && n <= 50) ? `number-${n}-modern` : '';
// Each logo's picture's size, once it's been loaded: [width, height].
const logoSizes = new Map();
const isShaped = id => { const [w, ht] = logoSizes.get(id) || [1, 1]; return w !== ht; };
// A logo's picture. One that isn't square (a show's or movie's, from Plex)
// is shown on a dark tile: once it's loaded, and straight away after that
// (pictures are drawn again every few seconds).
function logoImg(id, attrs = {}) {
  return h('img', {
    src: logoSrc(id), alt: '', class: isShaped(id) ? 'shaped' : null, ...attrs,
    onload: e => {
      logoSizes.set(id, [e.target.naturalWidth, e.target.naturalHeight]);
      e.target.classList.toggle('shaped', isShaped(id));
    },
  });
}
// The box a logo is drawn in on screen, as a share of a square logo's (as
// ffmpeg.logo_box works it out): one that isn't square covers the same
// area in its own shape, at most 2.4 times as wide or 1.25 times as tall.
function logoBox(w, ht) {
  if (!w || !ht || w === ht) return [1, 1];
  const aspect = w / ht;
  let bw = Math.sqrt(aspect), bh = 1 / Math.sqrt(aspect);
  if (bw > 2.4) { bw = 2.4; bh = 2.4 / aspect; }
  if (bh > 1.25) { bw = 1.25 * aspect; bh = 1.25; }
  return [bw, bh];
}

// A new station with just one show or movie is named after it, and has
// the first show's or movie's logo from Plex (when Plex has one), until you
// choose otherwise: a name you type or a logo you choose stays. A station
// you're changing keeps its own: its first show's logo is offered instead.
let logoChosen = false;  // a logo chosen in the editor (not one it started with)
let autoName = '';       // the name given from its only show or movie
// The logo Plex has for the first show or movie picked: {key, title, id
// (the one it has, or would have, among your logos; set once its picture
// has come)}.
let plexLogo = null;
let plexLogoPicture = '';  // (its picture, as the page holds it)
function followFirstTitle() {
  nameAfterOnlyTitle();
  const first = sources.find(s => s.type === 'show' || s.type === 'movie');
  const key = first ? String(first.ratingKey) : '';
  if (key === (plexLogo?.key ?? '')) { showPlexLogo(); return; }
  // The last first title's logo goes with it: back to the station's own
  // (or, for a new station, what a new station starts with).
  if (logo.startsWith(FROM_PLEX)) {
    logo = editing ? editing.logo : '';
    logoChosen = Boolean(editing);
    if (!editing) defaultLogo();
    renderLogoChoice();
  }
  const offered = plexLogo = key ? { key, title: first.title, id: null } : null;
  if (offered) {
    fetch(`/plex-logo/${encodeURIComponent(key)}.png`).then(async res => {
      if (!res.ok) return;
      const picture = await res.blob();
      if (plexLogo !== offered) return;  // (another was picked first meanwhile)
      if (plexLogoPicture) URL.revokeObjectURL(plexLogoPicture);
      plexLogoPicture = URL.createObjectURL(picture);
      $('#plexLogoImg').src = plexLogoPicture;
      offered.id = res.headers.get('X-Logo-Id') || '';
      if (!editing && !logoChosen) logo = FROM_PLEX + key;
      renderLogoChoice();
    }).catch(() => {});
  }
  showPlexLogo();
}
// A new station's name: its only show's or movie's while it has just the
// one (and the name hasn't been changed), and back to "Station N" when
// something else joins it.
function nameAfterOnlyTitle() {
  if (editing) return;
  const only = sources.length === 1 && ['show', 'movie'].includes(sources[0].type) ? sources[0] : null;
  const wanted = only ? only.title.slice(0, 60) : '';
  if (wanted === autoName) return;
  const name = $('#fName').value.trim(), number = $('#fNumber').value;
  if (name && name !== `Station ${number}` && name !== autoName) return;  // (a name of its own)
  autoName = wanted;
  $('#fName').value = wanted || (number ? `Station ${number}` : '');
  renderMarkPreview();
}
function showPlexLogo() {
  const offered = plexLogo;
  $('#plexLogo').hidden = !offered?.id || offered.id === logo || FROM_PLEX + offered.key === logo;
  $('#plexLogo').title = offered ? `The logo Plex has for ${offered.title}` : '';
}
$('#plexLogo').addEventListener('click', () => {
  if (!plexLogo?.id) return;
  logo = FROM_PLEX + plexLogo.key;
  logoChosen = true;
  renderLogoChoice();
});
// The station's logo, once it's one of your logos: a logo from Plex is
// added now. (An error if Plex can't give it any more.)
async function settledLogo() {
  if (!logo.startsWith(FROM_PLEX)) return logo;
  const pending = logo, opened = editorOpened;
  const added = await api('/api/logos/plex', { method: 'POST', body: { ratingKey: pending.slice(FROM_PLEX.length) } });
  await refreshLogoCatalog();
  if (opened === editorOpened && logo === pending) {
    logo = added.id;
    if (plexLogo) plexLogo.id = added.id;
    renderLogoChoice();
  }
  return added.id;
}
async function loadLogoCatalog() {
  if (!logoCatalog) logoCatalog = await api('/api/logos');
  return logoCatalog;
}
function renderLogoChoice() {
  const entry = logoCatalog?.find(l => l.id === logo);
  $('#logoPreview').replaceChildren(logo
    ? logoImg(logo)
    : h('span', { class: 'logo-num' }, $('#fNumber').value || '#'));
  $('#logoName').textContent = !logo ? 'Station number'
    : logo.startsWith(FROM_PLEX) ? plexLogo?.title || '' : entry ? entry.name : '';
  showPlexLogo();
  renderMarkPreview();
}
function takenLogos() {
  return new Set(channels.filter(c => !editing || c.id !== editing.id).map(c => c.logo).filter(Boolean));
}
function randomLogo() {
  if (!logoCatalog?.length) return;
  const taken = takenLogos();
  const pool = logoCatalog.filter(l => !LETTERING.has(l.category) && l.category !== YOURS && l.id !== logo && l.id !== COLLECTION_LOGO);
  const free = pool.filter(l => !taken.has(l.id));
  const from = free.length ? free : pool;
  logo = from[Math.floor(Math.random() * from.length)].id;
  renderLogoChoice();
}
// A new station starts with its own number's logo (stations 1-50), or a
// picture chosen at random for the others.
function defaultLogo() {
  const own = numberLogo(Number($('#fNumber').value));
  if (own && logoCatalog?.some(l => l.id === own)) { logo = own; renderLogoChoice(); } else randomLogo();
}
// What a station is about, for suggesting logos: the genres it's filtered
// on, and the words of its name.
const SAME = { 'science fiction': ['sci-fi', 'space'], 'sci-fi': ['science fiction'], sport: ['sports'], sports: ['sport'],
  children: ['kids'], kids: ['children'], 'talk show': ['talk shows'], 'game show': ['game shows'], western: ['westerns'],
  westerns: ['western'], musical: ['musicals'], 'film-noir': ['film noir', 'noir'], animation: ['cartoons'], family: ['kids'] };
function stationTopics() {
  const topics = new Set();
  for (const src of sources) {
    if (src.type !== 'filter') continue;
    for (const g of [...(src.tags?.genre || []), ...(src.genre || [])]) topics.add(String(g).toLowerCase());
  }
  for (const w of ($('#fName').value || '').toLowerCase().split(/[^a-z0-9-]+/)) {
    if (w.length > 2 && !['the', 'and', 'station', 'channel', 'network'].includes(w)) topics.add(w.replace(/s$/, ''));
  }
  for (const t of [...topics]) for (const alt of SAME[t] || []) topics.add(alt);
  return topics;
}
function suggestedLogos() {
  if (!logoCatalog) return [];
  const topics = stationTopics();
  if (!topics.size) return [];
  const hits = logoCatalog.filter(l => !LETTERING.has(l.category) && l.category !== YOURS && [l.name.toLowerCase(), ...(l.tags || [])].some(tag => {
    const t = String(tag).toLowerCase();
    return topics.has(t) || topics.has(t.replace(/s$/, '')) || [...topics].some(w => w.length > 3 && t.split(/[\s·&-]+/).includes(w));
  }));
  // Genres first, then the rest in the library's order.
  return [...hits.filter(l => l.category === 'Genres'), ...hits.filter(l => l.category !== 'Genres')];
}
function logoMatches(l, words) {
  const hay = [l.name, l.category, ...(l.tags || [])].join(' ').toLowerCase();
  return words.every(w => hay.includes(w));
}
function renderLogoPicker() {
  const suggested = suggestedLogos();
  const cats = ['All', ...(suggested.length ? [SUGGESTED] : []), ...new Set(logoCatalog.map(l => l.category))];
  if (!cats.includes(logoCategory)) logoCategory = 'All';
  $('#logoCats').replaceChildren(...cats.map(c => h('button', {
    type: 'button', class: 'chipbtn', 'aria-pressed': String(c === logoCategory),
    onclick: () => { logoCategory = c; renderLogoPicker(); },
  }, c)));
  const taken = takenLogos();
  const words = $('#logoSearch').value.toLowerCase().split(/\s+/).filter(Boolean);
  const inCat = logoCategory === SUGGESTED ? suggested
    : logoCatalog.filter(l => logoCategory === 'All' || l.category === logoCategory);
  const shown = words.length ? inCat.filter(l => logoMatches(l, words)) : inCat;
  const numberChoice = h('button', { type: 'button', 'aria-pressed': String(logo === ''), onclick: () => pickLogo('') },
    h('span', { class: 'logo-num' }, $('#fNumber').value || '#'), h('span', {}, 'Station number'));
  const tile = l => h('button', {
    type: 'button', class: taken.has(l.id) ? 'taken' : null, title: l.name,
    'aria-pressed': String(l.id === logo), onclick: () => pickLogo(l.id),
  }, logoImg(l.id, { loading: 'lazy' }), h('span', {}, l.name));
  $('#logoGrid').replaceChildren(...(logoCategory === 'All' && !words.length ? [numberChoice] : []), ...shown.map(l => l.category === YOURS && isAdmin()
    ? h('div', { class: 'mine' }, tile(l),
        h('button', { type: 'button', class: 'del', title: `Delete “${l.name}”`, 'aria-label': `Delete ${l.name}`, onclick: () => deleteLogo(l) }, '×'))
    : tile(l)));
  $('#logoNone').hidden = shown.length > 0 || (logoCategory === 'All' && !words.length);
}
$('#logoSearch').addEventListener('input', () => renderLogoPicker());
async function refreshLogoCatalog() { logoCatalog = null; await loadLogoCatalog(); }
$('#logoUpload').addEventListener('change', async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { toast('That file is too big (the limit is 10 MB)', true); return; }
  try {
    const added = await api(`/api/logos?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
    await refreshLogoCatalog();
    logoCategory = YOURS;
    pickLogo(added.id);
    toast(`Added your logo “${added.name}”`);
  } catch (err) { toast(err.message, true); }
});
