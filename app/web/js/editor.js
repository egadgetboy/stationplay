// StationPlay's page: The station editor.
// Editor ------------------------------------------------------------------------
let editing = null;       // channel being edited, or null for new
let order = 'rotate';
let sources = [];         // [{type, ratingKey|key, title, sectionType}]
let libraries = [];
const libCache = new Map();

const orderHints = {
  rotate: 'One episode from each show in turn, each show in episode order — like classic reruns.',
  shuffle: 'A new random order each time through, so shows air at different times each day. It avoids playing more than 2 episodes of the same show in a row.',
};
const aspectHints = {
  fit: 'Keeps the original shape, with black bars at the sides.',
  stretch: 'Widens 4:3 shows to fill the screen. People and objects look wider.',
  zoom: 'Enlarges 4:3 shows to fill the screen, trimming some of the top and bottom.',
};
// The station's picture size: everything on it is converted to this as it plays.
const PICTURE_HINTS = {
  '480p': 'Lightest: about half the server work of 720p, with less detail. Good for a slower server or many stations at once.',
  '720p': 'The standard: sharp on most TVs, and light enough for most servers.',
  '1080p': 'Sharpest: about twice the work of 720p (a GPU helps a lot), and nearly twice the data to send.',
};
const PICTURE_NOTE = 'Everything on the station plays at this size as one stream. 4K programs are scaled down to it, and HDR programs are converted to standard color. (For stability, stations don’t play in 4K or HDR.)';
let picture = '720p';
function setPicture(p) {
  picture = PICTURE_HINTS[p] ? p : '720p';
  pressOne('picture', picture);
  const later = editing && editing.picture !== picture ? ' The new size takes effect the next time the station starts (after everyone stops watching it).' : '';
  $('#pictureHint').textContent = `${PICTURE_HINTS[picture]} ${PICTURE_NOTE}${later}`;
}
document.querySelectorAll('[data-picture]').forEach(b => b.addEventListener('click', () => setPicture(b.dataset.picture)));

// Subtitles drawn into the picture (see subtitles.py).
const SUBS_HINTS = {
  off: 'Programs play without subtitles.',
  forced: 'Only lines meant to be read, such as foreign-language dialogue in a movie, when the program has them.',
  always: 'Full subtitles in StationPlay’s language setting (English by default), when the program has them.',
};
const SUBS_NOTE = 'Subtitles come from the program’s file or a subtitle file next to it. They’re burned into the picture, so viewers can’t turn them off.';
let subs = 'off';
function setSubs(v) {
  subs = SUBS_HINTS[v] ? v : 'off';
  pressOne('subs', subs);
  $('#subsHint').textContent = subs === 'off' ? SUBS_HINTS.off : `${SUBS_HINTS[subs]} ${SUBS_NOTE}${status?.subtitles === false ? ' (This server can’t add subtitles to the picture. An Admin can see why on the Logs tab.)' : ''}`;
}
document.querySelectorAll('[data-subs]').forEach(b => b.addEventListener('click', () => setSubs(b.dataset.subs)));
const SUBS_TEXT = { forced: 'forced subtitles', always: 'subtitles' };

let aspect = 'fit';
function setAspect(a) {
  aspect = a;
  pressOne('aspect', a);
  $('#aspectHint').textContent = aspectHints[a] + ' Widescreen programs are never changed.';
}
document.querySelectorAll('[data-aspect]').forEach(b => b.addEventListener('click', () => setAspect(b.dataset.aspect)));

const skipHints = {
  off: 'Programs play in full.',
  on: 'Skips intros and end credits wherever Plex has found them, like Skip Intro and Skip Credits in Plex, so the next program starts right away. Anything before the intro still plays, and so does a scene after the credits. Programs Plex hasn’t marked play in full.',
};
let skipIntros = false;
function setSkip(on) {
  skipIntros = on;
  pressOne('skip', on ? 'on' : 'off');
  $('#skipHint').textContent = skipHints[on ? 'on' : 'off'];
}
document.querySelectorAll('[data-skip]').forEach(b => b.addEventListener('click', () => setSkip(b.dataset.skip === 'on')));

// Marathons: off, at random times (so many a week) or at set times (days
// and a time), with each show's next episodes or a random stretch.
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
let marathonMode = 'off', marathonsAWeek = 2, marathonDays = new Set([5]), marathonTime = '20:00', marathonEpisodes = 'next';
function setMarathons(st) {
  marathonMode = st.marathonMode || 'off';
  marathonsAWeek = st.marathonsAWeek || 2;
  marathonDays = new Set(String(st.marathonDays ?? '5').split(',').filter(d => /^[0-6]$/.test(d)).map(Number));
  if (!marathonDays.size) marathonDays.add(5);
  marathonTime = st.marathonTime || '20:00';
  marathonEpisodes = st.marathonEpisodes || 'next';
  $('#marathonTime').value = marathonTime;
  showMarathons();
}
function showMarathons() {
  pressOne('marathon', marathonMode);
  pressOne('mweek', String(marathonsAWeek));
  pressOne('mepisodes', marathonEpisodes);
  $('#marathonRandom').hidden = marathonMode !== 'random';
  $('#marathonSet').hidden = marathonMode !== 'set';
  $('#marathonPick').hidden = marathonMode === 'off';
  $('#marathonDays').replaceChildren(...DAY_NAMES.map((name, d) => h('button', {
    type: 'button', class: 'chipbtn', 'aria-pressed': String(marathonDays.has(d)),
    onclick: () => {
      if (marathonDays.has(d) && marathonDays.size > 1) marathonDays.delete(d); else marathonDays.add(d);
      showMarathons();
    },
  }, name)));
  $('#marathonHint').textContent = marathonMode === 'off' ? 'Three episodes of one of the station’s shows in a row, now and then.'
    : `Three episodes of one of the station’s shows in a row, ${marathonMode === 'random' ? 'at random times on different days' : 'at the program break nearest the time you set'}. Then the station picks up where it left off. Each show takes a turn${marathonEpisodes === 'next' ? ', playing its next three episodes (continuing from where its last marathon ended)' : ', playing three episodes in a row from a random point in the show'}. For marathons, a station needs at least 5 shows with 3 or more episodes each.`;
}
document.querySelectorAll('[data-marathon]').forEach(b => b.addEventListener('click', () => { marathonMode = b.dataset.marathon; showMarathons(); }));
document.querySelectorAll('[data-mweek]').forEach(b => b.addEventListener('click', () => { marathonsAWeek = Number(b.dataset.mweek); showMarathons(); }));
document.querySelectorAll('[data-mepisodes]').forEach(b => b.addEventListener('click', () => { marathonEpisodes = b.dataset.mepisodes; showMarathons(); }));
$('#marathonTime').addEventListener('change', () => { if (/^\d\d:\d\d$/.test($('#marathonTime').value)) marathonTime = $('#marathonTime').value; renderSummaries(); });
const marathonDaysText = () => [...marathonDays].sort().join(',');

// Days of the week chosen with chips (at least one stays chosen).
function daySet(text, fallback) {
  const days = new Set(String(text ?? '').split(',').filter(d => /^[0-6]$/.test(d)).map(Number));
  if (!days.size) days.add(fallback);
  return days;
}
const daysText = days => [...days].sort().join(',');
function dayChips(days, redraw) {
  return DAY_NAMES.map((name, d) => h('button', {
    type: 'button', class: 'chipbtn', 'aria-pressed': String(days.has(d)),
    onclick: () => { if (days.has(d) && days.size > 1) days.delete(d); else days.add(d); redraw(); },
  }, name));
}

// The Feature Presentation: off or on, on featureDays at featureTime, a
// movie from featureSource (a movie library or collection; {} for the
// station's own movies).
let featureMode = 'off', featureDays = new Set([4]), featureTime = '20:00', featureSource = {};
let movieSources = null;  // movie libraries and collections, once Plex has listed them
const featureKey = s => s?.type === 'section' ? `section:${s.key}` : s?.type === 'collection' ? `collection:${s.ratingKey}` : '';
function setFeature(st) {
  featureMode = st.featureMode || 'off';
  featureDays = daySet(st.featureDays, 4);
  featureTime = st.featureTime || '20:00';
  featureSource = structuredClone(st.featureSource || {});
  $('#featureTime').value = featureTime;
  $('#featureVideo').hidden = true;
  $('#featureVideo').removeAttribute('src');
  $('#featurePreviewStatus').textContent = '';
  showFeature();
}
function showFeature() {
  const on = featureMode === 'on';
  pressOne('feature', featureMode);
  $('#featureSet').hidden = $('#featureFrom').hidden = $('#featurePreviewRow').hidden = !on;
  if (!on) $('#featureVideo').hidden = true;
  $('#featureDays').replaceChildren(...dayChips(featureDays, showFeature));
  const current = featureKey(featureSource);
  const choices = [...(movieSources || [])];
  if (current && !choices.some(c => featureKey(c) === current)) choices.unshift(featureSource);
  $('#featureSource').replaceChildren(
    h('option', { value: '' }, 'This station’s movies'),
    ...choices.map(c => h('option', { value: featureKey(c) }, c.type === 'section' ? `All of ${c.title}` : `Collection: ${c.title}`)));
  $('#featureSource').value = current;
  $('#featureHint').textContent = on
    ? `At the program break nearest the time you set, a ${FEATURE_CARD_S}-second Feature Presentation card in the station’s colors plays, then a movie. Movies take turns: the one shown longest ago plays next. The card plays a jingle only if the Station ID card’s jingle is on.`
    : 'A movie on the days and at the time you set, introduced by a Feature Presentation card.';
  if (on && movieSources === null) loadMovieSources();
}
async function loadMovieSources() {
  movieSources = [];
  try {
    const libs = libraries.length ? libraries : await api('/api/libraries');
    const collections = await api('/api/collections');
    movieSources = [
      ...libs.filter(l => l.type === 'movie').map(l => ({ type: 'section', key: String(l.key), sectionType: 'movie', title: l.title })),
      ...collections.filter(c => c.kind === 'movie').map(c => ({ type: 'collection', ratingKey: c.ratingKey, title: c.title, library: c.library, kind: 'movie' })),
    ];
  } catch {
    movieSources = null;  // (asked again next time)
  }
  if (featureMode === 'on') showFeature();
}
document.querySelectorAll('[data-feature]').forEach(b => b.addEventListener('click', () => { featureMode = b.dataset.feature; showFeature(); }));
$('#featureTime').addEventListener('change', () => { if (/^\d\d:\d\d$/.test($('#featureTime').value)) featureTime = $('#featureTime').value; renderSummaries(); });
$('#featureSource').addEventListener('change', () => {
  const key = $('#featureSource').value;
  featureSource = key ? structuredClone([featureSource, ...(movieSources || [])].find(c => featureKey(c) === key) || {}) : {};
  renderSummaries();
});

// Time-of-day blocks: [{id, name, days (a Set while editing), start, end,
// sources}]. A block's shows are chosen with the station's own picker: while
// they are, `sources` is the block's, and the station's wait in
// stationSources.
const MAX_BLOCKS = 4;
let blocks = [], picking = null, stationSources = null;
function setBlocks(st) {
  picking = null;
  stationSources = null;
  $('#pickingBanner').hidden = true;
  $('#contentLabel').textContent = 'What’s on this station';
  blocks = (st.blocks || []).map(b => ({ ...structuredClone(b), days: daySet(b.days, 5) }));
  showBlocks();
}
// What a station or block plays, in a word or two (a title from Plex's
// lists, if it was picked without one).
function sourceName(s) {
  if (s.type === 'section') return `All of ${s.title || 'a library'}`;
  if (s.title) return s.title;
  if (s.type === 'filter') return 'a filter';
  if (s.type === 'collection') return 'a collection';
  for (const items of libCache.values()) {
    const found = items.find(it => String(it.ratingKey) === String(s.ratingKey));
    if (found) return found.title;
  }
  return s.type === 'movie' ? 'a movie' : 'a show';
}
function picksText(list) {
  const names = list.map(sourceName);
  return names.length > 3 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(', ');
}
function blockMinutes(b) {
  const minute = t => { const [hh, mm] = String(t).split(':').map(Number); return (hh || 0) * 60 + (mm || 0); };
  return ((minute(b.end) - minute(b.start)) % 1440 + 1440) % 1440;
}
function showBlocks() {
  $('#blockList').replaceChildren(...blocks.map((b, n) => {
    const minutes = blockMinutes(b);
    const note = minutes < 30 || minutes > 720 ? 'A block must be 30 minutes to 12 hours long.'
      : b.end <= b.start ? 'It ends the next day.' : '';
    const picks = b === picking ? sources : b.sources;
    return h('div', { class: 'block' },
      h('input', { type: 'text', value: b.name, maxlength: 40, placeholder: 'Name, like Saturday Morning Cartoons', 'aria-label': 'Block name',
        oninput: e => { b.name = e.target.value; renderSummaries(); } }),
      h('div', { class: 'marathon-row' },
        h('div', { class: 'chips', role: 'group', 'aria-label': 'Block days' }, ...dayChips(b.days, showBlocks)),
        h('input', { type: 'time', value: b.start, 'aria-label': 'Start time',
          onchange: e => { if (/^\d\d:\d\d$/.test(e.target.value)) b.start = e.target.value; showBlocks(); renderSummaries(); } }),
        h('span', { class: 'hint' }, 'to'),
        h('input', { type: 'time', value: b.end, 'aria-label': 'End time',
          onchange: e => { if (/^\d\d:\d\d$/.test(e.target.value)) b.end = e.target.value; showBlocks(); renderSummaries(); } })),
      note ? h('span', { class: 'hint' }, note) : null,
      h('div', { class: 'block-shows' },
        h('span', { class: 'hint' }, picks.length ? picksText(picks) : 'Nothing chosen yet'),
        h('button', { type: 'button', class: 'btn', onclick: () => pickFor(b) }, picks.length ? 'Change…' : 'Choose shows…'),
        h('button', { type: 'button', class: 'btn ghost', onclick: () => { if (b === picking) finishPicking(); blocks.splice(n, 1); showBlocks(); renderSummaries(); } }, 'Remove')));
  }));
  $('#addBlock').disabled = blocks.length >= MAX_BLOCKS;
  $('#blocksHint').textContent = blocks.length
    ? `Each block starts and ends at the program break nearest its times and plays its shows in this station’s order. Next time, it picks up where it left off. You can add up to ${MAX_BLOCKS}.`
    : 'Blocks play their own shows on the days and at the times you set, like Saturday morning cartoons.';
}
$('#addBlock').addEventListener('click', () => {
  if (blocks.length >= MAX_BLOCKS) return;
  blocks.push({ id: '', name: '', days: new Set([5]), start: '08:00', end: '11:00', sources: [] });
  showBlocks();
  renderSummaries();
  $('#blockList').lastElementChild?.querySelector('input')?.focus();
});
function pickFor(b) {
  finishPicking();
  stationSources = sources;
  sources = b.sources;
  picking = b;
  const name = b.name.trim() || 'this block';
  $('#contentLabel').textContent = `What’s on ${b.name.trim() ? `“${name}”` : name}`;
  $('#pickingText').textContent = `Choosing what ${b.name.trim() ? `“${name}”` : name} plays. Pick shows or use a filter, then choose Done.`;
  $('#pickingBanner').hidden = false;
  renderSelected();
  renderLibItems();
  $('#contentField').scrollIntoView({ block: 'start', behavior: 'smooth' });
}
function finishPicking() {
  if (!picking) return;
  picking.sources = sources;
  sources = stationSources;
  stationSources = null;
  picking = null;
  $('#pickingBanner').hidden = true;
  $('#contentLabel').textContent = 'What’s on this station';
  renderSelected();
  renderLibItems();
  showBlocks();
  renderSummaries();
}
$('#pickingDone').addEventListener('click', () => {
  finishPicking();
  $('#groupSpecials').open = true;
  $('#blockList').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
});
// The blocks as saved, and the station's own programs (wherever they are).
const blocksBody = () => blocks.map(b => ({
  id: b.id, name: b.name.trim(), days: daysText(b.days), start: b.start, end: b.end,
  sources: b === picking ? sources : b.sources,
}));
const stationPicks = () => picking ? stationSources : sources;

let breaks = 0;
function breaksHintText() {
  const f = status?.fillers;
  const parts = ['Commercials play after episodes and trailers after movies, within each program’s time slot in the guide.'];
  if (f) {
    const found = `Found ${plural(f.commercials, 'commercial')} and ${plural(f.trailers, 'trailer')}.`;
    parts.push(found);
    if (!f.commercials && !f.trailers) parts.push('To add some, make a folder named commercials at the top of your TV library’s folder and one named trailers at the top of your movie library’s folder (both lowercase). Put a .plexignore file containing * in each, so Plex doesn’t add them to your libraries.');
  }
  return parts.join(' ');
}
function setBreaks(n) {
  breaks = n;
  pressOne('breaks', String(n));
  $('#breaksHint').replaceChildren(n ? breaksHintText() : 'No commercials or trailers between programs.',
    n && isAdmin() ? h('button', { type: 'button', class: 'linkbtn', onclick: lookAgain }, 'Check again') : '');
}
async function lookAgain() {
  // After adding clips to the folders: StationPlay otherwise looks every hour.
  try {
    status = { ...status, fillers: await api('/api/fillers/refresh', { method: 'POST' }) };
    setBreaks(breaks);
  } catch (e) { toast(e.message, true); }
}
document.querySelectorAll('[data-breaks]').forEach(b => b.addEventListener('click', () => setBreaks(Number(b.dataset.breaks))));

let stationId = false, idSeconds = 5, idSound = true;
function setStationId(on, n = idSeconds) {
  stationId = on;
  idSeconds = n;
  pressOne('sid', on ? String(n) : '0');
  $('#sidHint').textContent = on
    ? `After each program and any commercials or trailers that follow it, a ${n}-second card shows the station’s logo, name, and what’s up next${idSound ? ', with a short jingle (one of 15, quieter than the programs)' : ''}.`
    : 'No card between programs.';
  $('#sidSet').hidden = !on;
}
function setIdSound(on) {
  idSound = on;
  pressOne('sidsound', on ? 'on' : 'off');
  setStationId(stationId);
}
document.querySelectorAll('[data-sid]').forEach(b => b.addEventListener('click', () => {
  const n = Number(b.dataset.sid);
  setStationId(n > 0, n || idSeconds);
}));
document.querySelectorAll('[data-sidsound]').forEach(b => b.addEventListener('click', () => setIdSound(b.dataset.sidsound === 'on')));

// The Intro Bumper: off, StationPlay's card (introLength seconds long), or a
// video you uploaded (introVideo). The card's length is kept for a video too:
// the card stands in if the video ever won't play.
let introKind = 'card', introLength = 5, introSound = true, introVideo = '';
// Where someone tuning in joins: now (where the station is, as on real TV)
// or start (the program on now, from its beginning).
let tuneIn = 'now';
const TUNE_IN_HINT = {
  now: 'Like real TV: if you tune in at 10:20 to a show that started at 10:00, you join it 20 minutes in. The guide is always accurate.',
  start: 'If you tune in at 10:20 to a show that started at 10:00, it plays from the beginning. The station then continues from there, 20 minutes behind the guide, until no one is watching it. Anyone else who tunes in meanwhile joins in progress. So does anyone who tunes in during a break, or to a program that started more than 2 hours ago.',
};
function setTuneIn(value) {
  tuneIn = value === 'start' ? 'start' : 'now';
  pressOne('tunein', tuneIn);
  $('#tuneInHint').textContent = TUNE_IN_HINT[tuneIn];
  showIntro();
}
document.querySelectorAll('[data-tunein]').forEach(b => b.addEventListener('click', () => setTuneIn(b.dataset.tunein)));
let bumpers = null;  // the videos you've uploaded, {id, name, seconds}, once loaded
const MAX_BUMPER_MB = 500;
function introHintText() {
  const n = introLength, start = tuneIn === 'start';
  if (introKind === 'video') return `When someone tunes in, your video plays first, then ${start ? 'the program from the very beginning' : 'the show. The show keeps its place in the schedule, so viewers join it as far in as the video is long'}. Upload any video up to 30 seconds long. StationPlay makes a copy at the stream’s size, with its volume matched to the programs.`;
  if (introKind === 'off') return start ? 'Tuning in goes straight to the program, from the beginning.' : 'Tuning in goes straight to the show.';
  const card = `When someone tunes in, a card shows the station’s logo, “You’re tuning in to” followed by its name, the description below, and what’s on, for ${n} seconds`;
  if (start) return `${card}${introSound ? ', with the sound of an old TV dial being turned' : ', silently'}. Then the program plays from its very first moment, so nothing is missed. (When viewers join in progress, the show’s own sound fades in during the last third of the bumper instead.)`;
  return `${card}${introSound ? ', with the sound of an old TV dial being turned' : ', silently until the show’s own sound comes in'}. The show keeps its place in the schedule, so viewers join it ${n} seconds in.`;
}
function showIntro() {
  pressOne('introkind', introKind);
  pressOne('intro', String(introLength));
  $('#introHint').textContent = introHintText();
  $('#introSet').hidden = introKind !== 'card';
  $('#bumperSet').hidden = introKind !== 'video';
  if (introKind === 'video') renderBumpers();
}
function setIntroSound(on) {
  introSound = on;
  pressOne('introsound', on ? 'on' : 'off');
  showIntro();
}
document.querySelectorAll('[data-introsound]').forEach(b => b.addEventListener('click', () => setIntroSound(b.dataset.introsound === 'on')));
document.querySelectorAll('[data-intro]').forEach(b => b.addEventListener('click', () => {
  introLength = Number(b.dataset.intro);
  showIntro();
}));
document.querySelectorAll('[data-introkind]').forEach(b => b.addEventListener('click', () => {
  introKind = b.dataset.introkind;
  if (introKind === 'video' && !introVideo && bumpers?.length) introVideo = bumpers[0].id;
  showIntro();
}));
async function loadBumpers() {
  try { bumpers = await api('/api/bumpers'); } catch { return; }
  if (introKind !== 'video') return;
  if (!introVideo && bumpers.length) introVideo = bumpers[0].id;
  renderBumpers();
}
function renderBumpers() {
  if (bumpers === null) {  // still loading
    $('#fBumper').replaceChildren(h('option', { value: '' }, 'Loading your videos…'));
    $('#fBumper').disabled = true;
    $('#bumperDelete').hidden = $('#bumperVideo').hidden = true;
    return;
  }
  const known = bumpers.some(b => b.id === introVideo);
  const options = bumpers.map(b => h('option', { value: b.id }, `${b.name} (${Math.round(b.seconds * 10) / 10} sec)`));
  if (introVideo && !known) options.unshift(h('option', { value: introVideo }, 'This station’s video (missing)'));
  if (!options.length) options.push(h('option', { value: '' }, 'No videos yet. Upload one.'));
  $('#fBumper').replaceChildren(...options);
  $('#fBumper').value = introVideo;
  $('#fBumper').disabled = !bumpers.length;
  $('#bumperDelete').hidden = !known || !isAdmin();
  const video = $('#bumperVideo');
  const src = known ? `/bumpers/${introVideo}.mp4#t=0.5` : '';  // (#t: its picture shows before it's played)
  if (video.getAttribute('src') !== src) {
    video.pause();
    if (src) video.src = src; else video.removeAttribute('src');
  }
  video.hidden = !src;
}
$('#fBumper').addEventListener('change', () => { introVideo = $('#fBumper').value; renderBumpers(); });
// Nothing keeps playing once the editor's closed.
$('#editor').addEventListener('close', () => document.querySelectorAll('#editor video').forEach(v => v.pause()));
$('#bumperUpload').addEventListener('change', async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  if (file.size > MAX_BUMPER_MB * 1048576) { toast(`That file is too big (the limit is ${MAX_BUMPER_MB} MB)`, true); return; }
  const status = $('#bumperStatus');
  status.textContent = 'Uploading and preparing the video… (a big file can take a minute or so)';
  try {
    const added = await api(`/api/bumpers?name=${encodeURIComponent(file.name)}`, { method: 'POST', raw: file });
    introVideo = added.id;
    await loadBumpers();
    renderBumpers();
    status.textContent = '';
    $('#editorStatus').textContent = '';
    toast(`Added your Intro Bumper “${added.name}”`);
  } catch (err) {
    status.textContent = err.message;
  }
});
$('#bumperDelete').addEventListener('click', async () => {
  const bumper = bumpers.find(b => b.id === introVideo);
  if (!bumper || !confirm(`Delete the Intro Bumper “${bumper.name}”? Stations won’t be able to play it anymore.`)) return;
  try {
    await api(`/api/bumpers/${encodeURIComponent(bumper.id)}`, { method: 'DELETE' });
    introVideo = '';
    await loadBumpers();
    introVideo = bumpers[0]?.id || '';
    renderBumpers();
  } catch (err) { toast(err.message, true); }
});
function countDescription() {
  const n = $('#fDescription').value.length;
  $('#descCount').textContent = n ? `${n} of 140` : 'Optional: one line about what the station plays';
}
$('#fDescription').addEventListener('input', countDescription);
// Previews: a short video made by the server from the editor's settings,
// played under its button.
const previewUrls = {};
async function showPreview(url, body, btn, status, video, playing = '') {
  btn.disabled = true;
  status.textContent = 'Making the preview…';
  try {
    const made = await api(url, { method: 'POST', body, blob: true });
    if (previewUrls[video.id]) URL.revokeObjectURL(previewUrls[video.id]);
    previewUrls[video.id] = URL.createObjectURL(made);
    video.src = previewUrls[video.id];
    video.hidden = false;
    status.textContent = playing;
    video.play().catch(() => {});
  } catch (e) {
    status.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}
async function previewCard(kind, btn, status, video) {
  let chosen;
  try { chosen = await settledLogo(); } catch (e) { status.textContent = e.message; return; }
  return showPreview('/api/intro/preview', {
    kind,
    channelId: editing ? editing.id : null,
    number: Number($('#fNumber').value) || 1,
    name: $('#fName').value.trim(),
    logo: chosen,
    description: $('#fDescription').value,
    seconds: kind === 'id' ? idSeconds : kind === 'feature' ? FEATURE_CARD_S : introLength,
    sound: kind === 'intro' ? introSound : idSound,
  }, btn, status, video);
}
$('#introPreview').addEventListener('click', () => previewCard('intro', $('#introPreview'), $('#introPreviewStatus'), $('#introVideo')));
$('#sidPreview').addEventListener('click', () => previewCard('id', $('#sidPreview'), $('#sidPreviewStatus'), $('#sidVideo')));
$('#featurePreview').addEventListener('click', () => previewCard('feature', $('#featurePreview'), $('#featurePreviewStatus'), $('#featureVideo')));

// The editor's groups of settings: each says in a line how it's set, and
// which are open is remembered (in this browser) for next time.
const ASPECT_TEXT = { fit: 'black bars on 4:3', stretch: '4:3 stretched', zoom: '4:3 zoomed' };
function renderSummaries() {
  $('#sumPlay').textContent = [
    picture,
    order === 'rotate' ? 'Episode order' : 'Shuffle',
    ASPECT_TEXT[aspect] || '',
    skipIntros ? 'skips intros & credits' : 'plays intros & credits',
  ].filter(Boolean).join(' · ');
  $('#sumSpecials').textContent = specialsText({
    marathonMode, marathonsAWeek, marathonDays: marathonDaysText(), marathonTime,
    featureMode, featureDays: daysText(featureDays), featureTime,
    blocks: blocks.map(b => ({ ...b, days: daysText(b.days) })),
  });
  $('#sumBreaks').textContent = [breaksText(breaks), idText(stationId, idSeconds, idSound)].join(' · ');
  $('#sumScreen').textContent = [
    cornerText(mark, clockFormat, markPos, markStyle, markTime),
    upNextText(upNextSeconds),
    SUBS_TEXT[subs],
  ].filter(Boolean).join(' · ');
  $('#sumTune').textContent = tuneText(introKind === 'video', introKind === 'off' ? 0 : introLength, introSound, tuneIn);
}
// (Every change in the editor is a click, after the setting has taken it.)
$('#editor').addEventListener('click', renderSummaries);
const GROUPS_KEY = 'stationplay.editorGroups';
function restoreGroups() {
  let open = [];
  try { open = JSON.parse(localStorage.getItem(GROUPS_KEY) || '[]'); } catch {}
  document.querySelectorAll('#editor details.group').forEach(d => { d.open = open.includes(d.id); });
}
document.querySelectorAll('#editor details.group').forEach(d => d.addEventListener('toggle', () => {
  const open = [...document.querySelectorAll('#editor details.group[open]')].map(g => g.id);
  try { localStorage.setItem(GROUPS_KEY, JSON.stringify(open)); } catch {}
}));
// The corner preview is sized from the picture, so it's drawn once it shows.
$('#groupScreen').addEventListener('toggle', renderMarkPreview);

// The Up Next Banner: off (0), or shown for upNextSeconds at upNextSize.
let upNextSeconds = 10, upNextSize = 'large';
function showUpNext() {
  pressOne('upnext', String(upNextSeconds));
  pressOne('upnextsize', upNextSize);
  $('#upNextHint').textContent = upNextSeconds
    ? `Three minutes before each show or movie ends, a banner shows the station’s logo, “Up next,” and the next show or movie in the bottom-left corner for ${upNextSeconds} seconds, then fades away. If the corner logo, name, or clock is also in the bottom left, the banner replaces it for those seconds, and a logo there becomes the banner’s logo in the same spot.`
    : 'No banner says what’s up next.';
  $('#upNextSet').hidden = !upNextSeconds;
}
document.querySelectorAll('[data-upnext]').forEach(b => b.addEventListener('click', () => {
  upNextSeconds = Number(b.dataset.upnext);
  showUpNext();
}));
document.querySelectorAll('[data-upnextsize]').forEach(b => b.addEventListener('click', () => {
  upNextSize = b.dataset.upnextsize;
  showUpNext();
}));
// (With what's in the corner, which makes way for the banner.)
$('#upNextVideo').addEventListener('click', e => {
  const video = e.currentTarget;
  if (video.paused) video.play().catch(() => {}); else video.pause();
});
$('#upNextPreview').addEventListener('click', async () => {
  let chosen;
  try { chosen = await settledLogo(); } catch (e) { $('#upNextPreviewStatus').textContent = e.message; return; }
  showPreview('/api/upnext/preview', {
  channelId: editing ? editing.id : null,
  number: Number($('#fNumber').value) || 1,
  name: $('#fName').value.trim(),
  logo: chosen,
  seconds: upNextSeconds,
  size: upNextSize,
  watermark: mark,
  watermarkSize: markSize,
  watermarkTransparency: markTrans,
  watermarkPosition: markPos,
  watermarkTiming: markTime,
  watermarkStyle: markStyle,
  clockFormat,
}, $('#upNextPreview'), $('#upNextPreviewStatus'), $('#upNextVideo'), 'Playing on a loop. Click the video to pause.');
});

let clockFormat = '12';
function setClockFormat(v) { clockFormat = v; pressOne('clock', v); renderMarkPreview(); }
document.querySelectorAll('[data-clock]').forEach(b => b.addEventListener('click', () => setClockFormat(b.dataset.clock)));
function clockText(d = new Date()) {
  return clockFormat === '24'
    ? `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    : `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
}

const markHints = {
  off: 'Nothing is shown over the picture.',
  logo: 'The station’s logo in a corner during programs (or its name, if it has no logo), as shown below. Hidden during commercials and trailers.',
  name: 'The station’s name in a corner during programs, as shown below. Hidden during commercials and trailers.',
  clock: 'The time in a corner during programs, as shown below. Hidden during commercials and trailers.',
};
let mark = 'off';
function setMark(m) {
  mark = m;
  pressOne('mark', m);
  $('#markHint').textContent = markHints[m];
  $('#markSet').hidden = m === 'off';
  $('#markStyleField').hidden = m !== 'logo';
  $('#clockFormatField').hidden = m !== 'clock';
  renderMarkPreview();
}
document.querySelectorAll('[data-mark]').forEach(b => b.addEventListener('click', () => setMark(b.dataset.mark)));

// Its size and transparency, as shares of the largest, most opaque (the
// same numbers the server draws with).
const MARK_SIZES = { small: 0.55, medium: 0.75, large: 1 };
const MARK_OPACITY = { high: 0.4, medium: 0.65, low: 1 };
let markSize = 'large';
let markTrans = 'low';
let markPos = 'bottom-left';
let markTime = 'always';
let markStyle = 'color';
const markTimeHints = {
  always: 'Throughout each show or movie.',
  start: 'For the first 30 seconds of each show or movie, and of whatever’s on when someone tunes in. Then it fades away.',
};
function setMarkTime(v) { markTime = v; pressOne('mtime', v); $('#markTimeHint').textContent = markTimeHints[v]; }
document.querySelectorAll('[data-mtime]').forEach(b => b.addEventListener('click', () => setMarkTime(b.dataset.mtime)));
function setMarkSize(v) { markSize = v; pressOne('msize', v); renderMarkPreview(); }
function setMarkTrans(v) { markTrans = v; pressOne('mtrans', v); renderMarkPreview(); }
function setMarkPos(v) { markPos = v; pressOne('mpos', v); renderMarkPreview(); }
function setMarkStyle(v) { markStyle = v; pressOne('mstyle', v); renderMarkPreview(); }
document.querySelectorAll('[data-mstyle]').forEach(b => b.addEventListener('click', () => setMarkStyle(b.dataset.mstyle)));
document.querySelectorAll('[data-mpos]').forEach(b => b.addEventListener('click', () => setMarkPos(b.dataset.mpos)));
document.querySelectorAll('[data-msize]').forEach(b => b.addEventListener('click', () => setMarkSize(b.dataset.msize)));
document.querySelectorAll('[data-mtrans]').forEach(b => b.addEventListener('click', () => setMarkTrans(b.dataset.mtrans)));
function renderMarkPreview() {
  const box = $('#markPreview');
  if (!box || mark === 'off') return;
  const scale = MARK_SIZES[markSize], opacity = MARK_OPACITY[markTrans];
  const name = $('#fName').value.trim() || `Station ${$('#fNumber').value}`;
  // On screen: a logo 13% of the picture's height, or the name at 1/26 of it,
  // in from the corner by 3.5% of the width and 5% of the height.
  const [vertical, horizontal] = markPos.split('-');
  const at = `${vertical}:5%;${horizontal}:3.5%`;
  // (A logo that isn't square is drawn in a box of its own shape: logoBox.)
  const markHeight = id => `${13 * scale * logoBox(...(logoSizes.get(id) || [1, 1]))[1]}%`;
  const shown = mark === 'logo' && logo
    ? h('img', {
        src: logoSrc(logo), alt: '', style: `${at};height:${markHeight(logo)};opacity:${0.65 * opacity}${markStyle === 'white' ? ';filter:url(#whiteMark)' : ''}`,
        onload: e => {
          logoSizes.set(logo, [e.target.naturalWidth, e.target.naturalHeight]);
          e.target.style.height = markHeight(logo);
        },
      })
    : mark === 'clock'
      ? h('span', { class: 'clock', style: `${at};font-size:${(box.clientHeight || 99) / 22 * scale}px;opacity:${0.8 * opacity}` }, clockText())
      : h('span', { style: `${at};font-size:${(box.clientHeight || 99) / 26 * scale}px;opacity:${0.7 * opacity}` }, name);
  // Each quarter of the picture moves it to that corner.
  const zones = ['top-left', 'top-right', 'bottom-left', 'bottom-right'].map(pos => {
    const [v, hz] = pos.split('-');
    return h('button', {
      type: 'button', class: 'zone', 'aria-label': `Move it to the ${v} ${hz}`,
      'aria-pressed': String(pos === markPos), style: `${v}:0;${hz}:0`, onclick: () => setMarkPos(pos),
    });
  });
  box.replaceChildren(shown, ...zones);
}

function setOrder(o) {
  order = o;
  pressOne('order', o);
  $('#orderHint').textContent = orderHints[o];
}
document.querySelectorAll('[data-order]').forEach(b => b.addEventListener('click', () => setOrder(b.dataset.order)));

// Filters saved before 1.6 kept these at the top level; now they're in tags.
const TAGS = ['genre', 'director', 'actor', 'collection', 'label'];
const sourceKey = s => s.type === 'section' ? `section:${s.key}`
  : s.type === 'filter' ? `filter:${JSON.stringify([s.kind, s.libraries, s.tags, ...TAGS.map(t => s[t]), s.decade, s.titleContains, s.addedWithinDays, s.minRating])}`
  : `${s.type}:${s.ratingKey}`;

function renderSelected() {
  const box = $('#selected');
  $('#pickedCount').textContent = sources.length
    ? `Picked: ${sources.length}${picksTotal()}` : 'Nothing picked yet — choose shows or movies above.';
  const remove = s => { sources = sources.filter(x => sourceKey(x) !== sourceKey(s)); renderSelected(); renderLibItems(); };
  box.replaceChildren(...sources.map(s => s.type === 'filter'
    ? h('span', { class: 'sel filter', title: 'A filter. StationPlay keeps checking Plex for matches, and new matches are added automatically. Click to change it.' },
        h('span', { onclick: async () => { setPickMode('filter', false); if (await initFilter(s)) remove(s); } }, `⚲ ${s.title}`),
        h('button', { type: 'button', 'aria-label': `Remove ${s.title}`, onclick: () => remove(s) }, '×'))
    : s.type === 'collection'
    ? h('span', { class: 'sel filter', title: 'A Plex collection. Anything added to it in Plex joins the station automatically.' },
        h('span', {}, `▦ ${s.title}`),
        h('button', { type: 'button', 'aria-label': `Remove ${s.title}`, onclick: () => remove(s) }, '×'))
    : h('span', { class: 'sel' },
        h('span', {}, s.type === 'section' ? `All of ${s.title}` : s.title),
        h('button', { type: 'button', 'aria-label': `Remove ${s.title}`, onclick: () => remove(s) }, '×'))));
  if (!picking) followFirstTitle();  // (a block's shows don't name the station)
  else showBlocks();
}

// How many times the editor has been opened (to tell a reply that comes
// after it was closed and opened again).
let editorOpened = 0;
// What's picked, added up from the libraries' lists: " — 2 shows, 1 movie ·
// 412 episodes · about 290 hours" (filters and collections are counted when
// the station is saved).
function picksTotal() {
  const known = new Map();
  for (const items of libCache.values()) for (const it of items) known.set(String(it.ratingKey), it);
  let shows = 0, movies = 0, episodes = 0, ms = 0, others = 0, missing = 0;
  const counted = new Set();  // (a show picked as itself and in a whole library counts once)
  const add = it => {
    if (counted.has(String(it.ratingKey))) return;
    counted.add(String(it.ratingKey));
    if (it.type === 'show') { shows++; episodes += it.episodes || 0; ms += (it.durationMs || 0) * (it.episodes || 0); }
    else { movies++; ms += it.durationMs || 0; }
  };
  for (const s of sources) {
    if (s.type === 'show' || s.type === 'movie') {
      const it = known.get(String(s.ratingKey));
      if (it) add(it); else missing++;
    } else if (s.type === 'section') {
      const items = libCache.get(String(s.key));
      if (items) items.forEach(add); else missing++;
    } else others++;
  }
  if (missing) fillLibCache();
  const parts = [];
  if (shows) parts.push(plural(shows, 'show'));
  if (movies) parts.push(plural(movies, 'movie'));
  const counts = [parts.join(', ')];
  if (episodes) counts.push(plural(episodes, 'episode'));
  if (ms && !missing) counts.push(ms < 7200000 ? `about ${Math.round(ms / 60000)} minutes` : `about ${Math.round(ms / 3600000).toLocaleString()} hours`);
  if (others) counts.push(`plus ${others === 1 ? 'a filter or collection' : `${others} filters or collections`}`);
  const text = counts.filter(Boolean).join(' · ');
  return text && (shows || movies) ? ` — ${text}` : '';
}
// The lists of every library, fetched once (one at a time) when what's
// picked includes titles from libraries not opened yet, to count them.
let fillingLibCache = false;
async function fillLibCache() {
  if (fillingLibCache || !libraries.length) return;
  fillingLibCache = true;
  try {
    let fetched = false;
    for (const lib of libraries) {
      if (libCache.has(lib.key)) continue;
      try { libCache.set(lib.key, await api(`/api/libraries/${lib.key}/items`)); } catch { return; }
      fetched = true;
    }
    // (Only when there's more to count: a pick no library lists any more
    // stays uncounted.)
    if (fetched && $('#editor').open) renderSelected();
  } finally {
    fillingLibCache = false;
  }
}

async function openEditor(ch = null, copy = false) {
  editorOpened++;
  editing = copy ? null : ch;
  $('#editorTitle').textContent = copy ? `New station (a copy of ${ch.number})` : ch ? `Edit station ${ch.number}` : 'New station';
  $('#fNumber').value = ch && !copy ? ch.number : nextNumber();
  $('#fName').value = copy ? `${ch.name} (copy)`.slice(0, 60) : ch ? ch.name : `Station ${$('#fNumber').value}`;
  $('#fName').placeholder = `Station ${$('#fNumber').value}`;
  const st = ch || NEW_STATION;  // a new station starts with what new stations start with
  setPicture(st.picture);
  setSubs(st.subtitles);
  setOrder(st.orderMode);
  setAspect(st.aspectMode);
  setSkip(Boolean(st.skipIntros));
  setMarathons(st);
  setFeature(st);
  setBlocks(st);
  setBreaks(st.breaks || 0);
  idSound = Boolean(st.idSound);
  pressOne('sidsound', idSound ? 'on' : 'off');
  setStationId(Boolean(st.stationId), st.idSeconds);
  setMarkSize(st.watermarkSize);
  setMarkTrans(st.watermarkTransparency);
  setMarkPos(st.watermarkPosition);
  setMarkTime(st.watermarkTiming);
  setMarkStyle(st.watermarkStyle);
  setClockFormat(st.clockFormat);
  setMark(st.watermark);
  introSound = Boolean(st.introSound);
  pressOne('introsound', introSound ? 'on' : 'off');
  introVideo = st.introVideo || '';
  introLength = st.introSeconds || NEW_STATION.introSeconds || 5;
  introKind = introVideo ? 'video' : st.introSeconds ? 'card' : 'off';
  $('#bumperStatus').textContent = '';
  setTuneIn(st.tuneIn);
  loadBumpers();
  $('#fDescription').value = ch ? ch.description || '' : '';
  countDescription();
  upNextSeconds = st.upNextSeconds ?? 0;
  upNextSize = st.upNextSize || 'large';
  showUpNext();
  for (const [video, status] of [['#introVideo', '#introPreviewStatus'], ['#sidVideo', '#sidPreviewStatus'], ['#upNextVideo', '#upNextPreviewStatus']]) {
    $(video).hidden = true;
    $(video).removeAttribute('src');
    $(status).textContent = '';
  }
  logo = ch ? ch.logo : '';
  logoChosen = Boolean(ch);  // (a station's logo is never changed for it)
  autoName = '';
  sources = ch ? structuredClone(ch.sources) : [];
  $('#editorStatus').textContent = '';
  renderSelected();
  flt = null;
  setPickMode('titles');
  renderLogoChoice();
  restoreGroups();
  renderSummaries();
  $('#editor').showModal();
  editorSnapshot = editorState();
  loadLogoCatalog().then(() => {
    if (!ch && editing === ch && !logoChosen && !logo.startsWith(FROM_PLEX)) defaultLogo(); else renderLogoChoice();
  }).catch(() => {});
  if (!libraries.length) {
    try {
      libraries = await api('/api/libraries');
    } catch (e) {
      $('#libSelect').replaceChildren(h('option', {}, 'Can’t reach Plex'));
      $('#libItems').replaceChildren(h('p', { class: 'hint', style: 'padding:12px' }, e.message));
      return;
    }
  }
  $('#libSelect').replaceChildren(...libraries.map(l => h('option', { value: l.key }, `${l.title} (${l.type === 'show' ? 'TV' : 'Movies'})`)));
  await loadLibItems();
}
// Keep a default "Station N" name in step with the number while it hasn't
// been given a name of its own.
let lastNumber = null;
$('#fNumber').addEventListener('focus', () => { lastNumber = $('#fNumber').value; });
$('#fNumber').addEventListener('input', () => {
  const n = $('#fNumber').value;
  const name = $('#fName').value.trim();
  if (!name || name === `Station ${lastNumber}`) $('#fName').value = n ? `Station ${n}` : '';
  $('#fName').placeholder = `Station ${n || ''}`.trim();
  // A logo that was just this station's number follows the number.
  if (logo && logo === numberLogo(Number(lastNumber))) {
    const own = numberLogo(Number(n));
    logo = own && logoCatalog?.some(l => l.id === own) ? own : logo;
  }
  lastNumber = n;
  renderLogoChoice();
});
