// The setup's dialog and its steps.
// The setup (see setup.py) -------------------------------------------------------------
// For an Admin (or anyone, while signing in is off). When tapiOca is
// new: every question, with checks that what's set up is working. After an
// update that brings new or changed questions: just those, once (and the
// checks, if something needs a look). And everything, whenever it's run
// again (Run setup again on the Setup tab, or Setup at the foot of the
// page), with the current answers filled in. Each answer is saved as you go
// on from it; Skip setup (or Close) keeps everything else as it is.
const SETUP_TITLES = {
  checks: 'Checking your server',
  sources: 'Your shows and movies',
  watchIn: 'Where you watch',
  playback: 'How stations play',
  newStation: 'New station settings',
  signIn: 'Who can use tapiOca',
  viewing: 'Who sees what',
  away: 'Watching away from home',
  library: 'Media in tapiOca’s apps',
  fileChecks: 'Checking files',
  plex: 'Connecting your apps',
  done: 'All set',
};
// What each check's state is called beside it (the dot's color says it too).
const CHECK_STATES = {
  good: ['good', 'Working'],
  warn: ['warn', 'Needs a look'],
  bad: ['bad', 'Not working'],
  info: ['plain', 'Good to know'],
  wait: ['plain', 'Not checked yet'],
};
let setupChecked = false;
async function maybeSetup() {
  let st;
  try { st = await api('/api/setup'); } catch { return; }
  if (!st.fresh && !st.pending.length) return;
  // (Not over linking an app, or a station being made: there's time later.)
  if ($('#editor').open || $('#linkApp').open || $('#setupDlg').open || location.pathname === '/link') return;
  showSetup(st, st.fresh ? 'new' : 'updated');
}
async function runSetup() {
  let st;
  try { st = await api('/api/setup'); } catch (e) { toast(e.message, true); return; }
  showSetup(st, 'again');
}
// The first step's checks: the server itself (its media folder, video
// encoding, its clock and backups), never waiting on Plex.
async function setupChecks() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  try {
    return (await api(`/api/setup/checks?offset=${-new Date().getTimezoneOffset()}&zone=${encodeURIComponent(zone)}`)).checks;
  } catch { return null; }
}
// The Plex step's: whether Plex answers, whether tapiOca finds the files
// Plex lists, and whether Plex has tapiOca as a DVR; with the addresses to
// give Plex.
async function setupPlex() {
  try { return await api('/api/setup/plex'); } catch { return null; }
}
function checkRow(c) {
  const [chip, words] = CHECK_STATES[c.state] || CHECK_STATES.info;
  return h('div', { class: 'setup-check' },
    h('span', { class: `dot ${{ good: 'ok', warn: 'warn', bad: 'bad' }[c.state] || ''}`, 'aria-hidden': 'true' }),
    h('div', {},
      h('div', { class: 'head' }, h('strong', {}, c.title), h('span', { class: `chip ${chip}` }, words)),
      ...c.lines.map(line => h('p', { class: 'small', style: 'margin:3px 0 0' }, line))));
}
const needsLook = c => c.state === 'bad' || c.state === 'warn';
// The steps: after an update, the checks (if something needs a look) and
// the new questions; otherwise the checks and every question.
function setupSteps(st, why, checks) {
  return why === 'updated'
    ? [...(checks?.some(needsLook) ? ['checks'] : []), ...st.pending, 'done']
    : ['checks', ...st.questions, 'done'];
}

// What tapiOca uses (1.37.0, see uses.py): the setup's Your shows and
// movies and Where you watch, and What you use on the Setup tab. Kept here
// as the setup saves it (GET /api/setup/uses), so later steps follow it at
// once. Nothing saved: the setup says what 1.36.0 said.
let setupUses = null;
const setupWatchIn = () => (Array.isArray(setupUses?.watchIn) ? setupUses.watchIn : null);
// Whether Plex is a source or a place (nothing saved: as 1.36.0, always).
function setupPlexWanted() {
  const u = setupUses;
  if (!u || (!u.sources && !u.watchIn)) return true;
  const source = u.locked?.plex || (u.sources ? u.sources.includes('plex') : plexUsed());
  const place = u.watchIn ? u.watchIn.includes('plex') : plexUsed();
  return source || place;
}
// What signing in doesn't change, in the apps chosen ("Neither changes...":
// the two choices' hint, for a tapiOca set up before). Nothing chosen:
// 1.36.0's sentence. Only tapiOca's apps (and other apps): nothing to say.
function whoWatchesLine(watchIn, neither = false) {
  if (!watchIn) {
    return neither
      ? 'Neither changes who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself.'
      : 'Signing in doesn’t change who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself.';
  }
  const names = [['plex', 'Plex'], ['jellyfin', 'Jellyfin'], ['emby', 'Emby'], ['kodi', 'Kodi']]
    .filter(([place]) => watchIn.includes(place)).map(([, name]) => name);
  if (!names.length) return '';
  const apps = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`;
  return `${neither ? 'Neither changes' : 'Signing in doesn’t change'} who can watch in ${apps}: ${names.length === 1 ? names[0] : 'each app'} decides that itself.`;
}
// What's chosen, in a few words each ("Plex and Media folders of your own";
// "tapiOca’s apps, Plex and Jellyfin"); empty while nothing is.
function usesWords(sources, watchIn) {
  const SOURCE_WORDS = { plex: 'Plex', folders: 'Media folders of your own' };
  const PLACE_WORDS = { tapioca: 'tapiOca’s apps', plex: 'Plex', jellyfin: 'Jellyfin', emby: 'Emby', kodi: 'Kodi', other: 'other apps' };
  const say = (values, words) => {
    const names = Object.keys(words).filter(v => (values || []).includes(v)).map(v => words[v]);
    const text = names.length < 2 ? (names[0] || '') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
    return text.startsWith('other') ? `O${text.slice(1)}` : text;
  };
  return { sources: say(sources, SOURCE_WORDS), watchIn: say(watchIn, PLACE_WORDS) };
}
// The choices, as checkboxes: `sources` (Your shows and movies) and
// `watchIn` (Where you watch), each a group with its hint. What's set up
// is ticked and can't be unticked (it says how to stop using it). Ticked
// from what's saved, or (nothing saved) from what tapiOca has seen.
// `onTab`: on the Setup tab, not in the setup.
const PLACE_CHOICES = [
  ['tapioca', 'tapiOca’s apps', 'tapiOca’s own apps, for your stations and Media.'],
  ['plex', 'Plex', 'Plex’s Live TV guide, in every Plex app. Needs Plex Pass.'],
  ['jellyfin', 'Jellyfin', 'Jellyfin’s Live TV.'],
  ['emby', 'Emby', 'Emby’s Live TV. Needs Emby Premiere.'],
  ['kodi', 'Kodi', 'Kodi’s TV, with its PVR Simple Client add-on.'],
  ['other', 'Other apps', 'Apps that take a playlist and guide, such as Channels DVR or VLC.'],
];
function usesFields(got, { onChange = () => {}, onTab = false } = {}) {
  const locked = { plex: !!got.locked?.plex, folders: !!got.locked?.folders };
  const sources = new Set(got.sources ?? got.suggested?.sources ?? []);
  const places = new Set(got.watchIn ?? got.suggested?.watchIn ?? []);
  for (const s of ['plex', 'folders']) if (locked[s]) sources.add(s);
  const first = () => JSON.stringify(values());
  let libs = null, loading = false;  // (your own Media folders, once they're shown)
  const sourcesNode = h('div', { class: 'uses-group uses-sources' });
  const placesNode = h('div', { class: 'uses-group uses-places' });
  const box = (set, value, disabled) => h('input', { type: 'checkbox', checked: set.has(value), disabled, onchange: e => {
    if (e.target.checked) set.add(value); else set.delete(value);
    paint();
    onChange();
  } });
  const choice = (input, name, ...hints) => h('label', { class: `choice${input.disabled ? ' locked' : ''}` }, input,
    h('span', {}, h('strong', {}, name), ...hints.filter(Boolean).map(t => h('span', { class: 'hint' }, t))));
  async function loadLibs() {
    if (loading) return;
    loading = true;
    try { libs = (await api('/api/folder-libraries')).libraries; } catch { libs = []; }
    loading = false;
    if (libs.length) { locked.folders = true; sources.add('folders'); }
    paint();
  }
  function foldersList() {
    if (!sources.has('folders')) return null;
    if (!libs) { loadLibs(); return h('p', { class: 'hint', style: 'margin:0' }, 'Loading…'); }
    const what = l => l.kind === 'show' ? `Shows · ${plural(l.shows, 'show')}` : `Movies · ${plural(l.movies, 'movie')}`;
    const add = h('button', { type: 'button', class: 'btn', onclick: async () => {
      $('#folderLib').addEventListener('close', () => { libs = null; paint(); }, { once: true });
      await folderLibraryDialog();
    } }, 'Add a Media folder');
    return h('div', { class: 'uses-folders' },
      ...(libs.length ? libs.map(l => h('div', { class: 'small' }, h('strong', {}, l.name), h('span', { class: 'muted' }, ` · ${what(l)}`)))
        : [h('p', { class: 'hint', style: 'margin:0' }, 'None yet.')]),
      h('div', { class: 'row-btns' }, add));
  }
  function paint() {
    // (replaceChildren would show a null as the word "null".)
    sourcesNode.replaceChildren(...[
      // (In the setup, the step's title says it.)
      onTab ? h('strong', {}, 'Your shows and movies') : null,
      h('p', { class: 'hint', style: 'margin:0' }, 'Where tapiOca gets your shows and movies. Choose one or both.'),
      choice(box(sources, 'plex', locked.plex), 'Plex', locked.plex
        ? 'tapiOca is set up with Plex. To stop using it, delete PLEX_URL and PLEX_TOKEN from tapiOca’s app settings, then restart tapiOca.'
        : `Your own Plex Media Server. To connect it, set PLEX_URL and PLEX_TOKEN in tapiOca’s app settings, then restart tapiOca. ${onTab ? 'Run setup again to check it, in Connecting your apps.' : 'Connecting your apps, near the end, checks it.'}`),
      choice(box(sources, 'folders', locked.folders), 'Media folders of my own',
        'Shows and movies tapiOca reads straight from folders in its media folder.',
        locked.folders ? 'To stop using one, remove it on the Setup tab, under Your own folders.' : null),
      foldersList(),
      sources.size ? null : h('p', { class: 'hint', role: 'status', style: 'margin:0' }, 'Choose Plex, Media folders of your own, or both.'),
    ].filter(Boolean));
    placesNode.replaceChildren(...[
      onTab ? h('strong', {}, 'Where you watch') : null,
      h('p', { class: 'hint', style: 'margin:0' }, 'Where you’ll watch your stations. tapiOca then shows the steps for each. This only changes what tapiOca shows you: every app can still use tapiOca’s tuner, playlist and guide.'),
      ...PLACE_CHOICES.map(([value, name, hint]) => choice(box(places, value, false), name, hint)),
      places.size ? null : h('p', { class: 'hint', role: 'status', style: 'margin:0' }, 'Choose at least one place you’ll watch.'),
    ].filter(Boolean));
  }
  function values() {
    return { sources: ['plex', 'folders'].filter(s => sources.has(s)), watchIn: PLACE_CHOICES.map(([v]) => v).filter(v => places.has(v)) };
  }
  paint();
  const was = first();
  return { sources: sourcesNode, watchIn: placesNode, values, changed: () => first() !== was };
}
// Plex's terms, which tapiOca's own use of Plex goes by (see the README's
// What you need, and PRIVACY.md).
const PERSONAL_USE = () => h('div', { class: 'limit-note' }, h('strong', {}, 'Plex’s terms. '),
  'Plex’s terms license Plex Media Server for personal use, on hardware and storage you own. Use tapiOca with your Plex server as those terms allow. ',
  h('a', { href: 'https://www.plex.tv/about/privacy-legal/plex-terms-of-service/', target: '_blank', rel: 'noopener noreferrer' }, 'Plex’s terms'), ' · ',
  h('a', { href: '/privacy', target: '_blank', rel: 'noopener noreferrer' }, 'tapiOca’s privacy notice'));
const SETUP_AGAIN = 'You can run setup again any time from the Setup tab, or the Setup link at the foot of the page.';
// `why`: "new" (a new tapiOca), "updated" (an update has new questions),
// or "again" (run again).
async function showSetup(st, why) {
  const dlg = $('#setupDlg');
  // Checks run first after an update: they decide whether that step is shown.
  let checks = why === 'updated' ? await setupChecks() : null;
  const steps = setupSteps(st, why, checks);
  // (What tapiOca uses: the steps follow it. It never asks Plex.)
  setupUses = await api('/api/setup/uses').catch(() => null);
  const shownQuestions = steps.filter(s => st.questions.includes(s));
  const saved = new Set();  // (steps saved, or looked at, this time)
  const notYet = new Set();  // (questions a step says can't be answered yet)
  let step = 0, page = null, leaving = false;
  const nav = h('ol', { class: 'setup-nav', 'aria-label': 'Steps' });
  const title = h('h4', { class: 'wstep' });
  const body = h('div', { class: 'setup-page' });
  const intro = h('p', { style: 'margin:0' }, {
    new: 'A few questions to set tapiOca up, and checks that everything is working. Each answer is saved when you go on to the next step, and you can change any of them later.',
    updated: `${status?.version ? `tapiOca ${status.version}` : 'This version of tapiOca'} has ${st.pending.length === 1 ? 'a new question' : 'new questions'} for you${steps[0] === 'checks' ? ', and something on your server needs a look' : ''}. Everything else stays as you set it.`,
    again: 'Here’s everything, with your current answers. Change anything you like: each answer is saved when you go on to the next step.',
  }[why]);
  const said = h('span', { class: 'hint', role: 'alert' });
  const back = h('button', { type: 'button', class: 'btn', onclick: () => go(step - 1) }, 'Back');
  const next = h('button', { type: 'button', class: 'btn primary', autofocus: true, onclick: () => step === steps.length - 1 ? finish() : go(step + 1) });
  const later = h('button', { type: 'button', class: 'btn ghost', onclick: closeSetup,
    title: `Your answers so far are kept. ${SETUP_AGAIN}` }, why === 'new' ? 'Skip setup' : 'Close');
  // Checks are loaded once, and again on Check again; while they load, the
  // step says so. The Plex step's load on their own, in the background: a
  // Plex that doesn't answer never holds up the rest.
  let plexInfo = null;
  const loadChecks = async () => {
    checks = null;
    paintNav();
    checks = await setupChecks();
    paintNav();
    return checks;
  };
  const loadPlex = async () => {
    plexInfo = null;
    paintNav();
    plexInfo = await setupPlex();
    paintNav();
    return plexInfo;
  };
  if (!checks && steps.includes('checks')) loadChecks().then(() => { if (steps[step] === 'checks' || steps[step] === 'done') show(); });
  // (Again once what you use is saved: Plex's checks follow it.)
  const reloadPlex = () => {
    if (steps.includes('plex')) loadPlex().then(() => { if (steps[step] === 'plex' || steps[step] === 'done') show(); });
  };
  reloadPlex();

  function paintNav() {
    nav.replaceChildren(...steps.map((s, n) => {
      const attention = (s === 'checks' && checks?.some(needsLook)) || (s === 'plex' && setupPlexWanted() && plexInfo?.checks.some(needsLook));
      const mark = attention ? h('span', { class: 'dot warn', 'aria-label': 'Needs a look' })
        : saved.has(s) ? h('span', { class: 'done', 'aria-label': 'Done' }, '✓') : h('span', { class: 'num' }, String(n + 1));
      return h('li', {}, h('button', { type: 'button', 'aria-current': n === step ? 'step' : 'false', onclick: () => go(n) }, mark, h('span', {}, SETUP_TITLES[s])));
    }));
  }
  async function show() {
    const s = steps[step];
    title.textContent = `Step ${step + 1} of ${steps.length} · ${SETUP_TITLES[s]}`;
    back.hidden = step === 0;
    intro.hidden = step !== 0;  // (the welcome, on the first step only)
    later.hidden = step === steps.length - 1;
    next.textContent = step === steps.length - 1 ? 'Finish' : 'Next';
    said.textContent = '';
    paintNav();
    body.replaceChildren(h('p', { class: 'muted' }, 'Loading…'));
    try {
      page = await SETUP_PAGES[s]({ checks, loadChecks, plexInfo, loadPlex, reloadPlex, why, st, shownQuestions, saved, notYet });
    } catch (e) {
      page = { node: h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', e.message) };
    }
    // (Unless the step was left meanwhile.)
    if (steps[step] === s) body.replaceChildren(page.node);
  }
  // Leaving a step saves it (a question), and says it's been answered.
  async function leave() {
    const s = steps[step];
    if (page?.save) {
      const problem = await page.save();
      if (problem) { said.textContent = problem; return false; }
    }
    if (st.questions.includes(s) && !notYet.has(s)) {
      try { await api('/api/setup', { method: 'PUT', body: { answered: [s] } }); } catch {}
    }
    saved.add(s);
    return true;
  }
  async function go(n) {
    if (leaving || n === step || n < 0 || n >= steps.length) return;
    leaving = true;
    back.disabled = next.disabled = true;
    try {
      if (!(await leave())) return;
      step = n;
      await show();
    } finally {
      leaving = false;
      back.disabled = next.disabled = false;
    }
  }
  async function finish() {
    if (leaving) return;
    leaving = true;
    next.disabled = true;
    try {
      if (!(await leave())) return;
      // (What wasn't stepped through counts as answered too: it was shown.)
      try { await api('/api/setup', { method: 'PUT', body: { answered: shownQuestions.filter(q => !notYet.has(q)) } }); } catch {}
      dlg.close();
      toast(why === 'new' ? 'All set. Choose New station to make your first one.' : 'All set');
      loadStatus();
      if (!$('#tab-setup').hidden) renderPlaybackPanel();
      if (!$('#tab-access').hidden) { loadAway(); loadAppLibraries(); }
    } finally {
      leaving = false;
      next.disabled = false;
    }
  }
  $('#setupTitle').textContent = { new: 'Welcome to tapiOca', updated: 'What’s new in tapiOca', again: 'Setting up tapiOca' }[why];
  $('#setupBody').replaceChildren(intro, h('div', { class: 'setup-grid' }, nav, h('div', { class: 'setup-main' }, title, body)));
  $('#setupFoot').replaceChildren(later, h('div', { class: 'spacer' }), said, back, next);
  step = 0;
  await show();
  if (!dlg.open) dlg.showModal();

  // Skip setup, Close, ✕ or Escape: the questions shown count as answered
  // (they aren't asked again by themselves, unless a step said it couldn't
  // be answered yet), and nothing else changes.
  async function closeSetup() {
    dlg.close();
    try { await api('/api/setup', { method: 'PUT', body: { answered: shownQuestions.filter(q => !notYet.has(q)) } }); } catch {}
    if (why === 'new') toast(SETUP_AGAIN);
    loadStatus();
  }
  setupCloser = closeSetup;
}
let setupCloser = null;
$('#closeSetup').addEventListener('click', () => setupCloser?.());
$('#setupDlg').addEventListener('cancel', e => { e.preventDefault(); setupCloser?.(); });

// What new stations start with, as the setup asks (each setting's page
// name, its label, its choices as [value, words], what it does, and
// optionally when it's asked and whether its choices are a 2×2 grid).
const CORNERS = [['top-left', 'Top left'], ['top-right', 'Top right'], ['bottom-left', 'Bottom left'], ['bottom-right', 'Bottom right']];
const NEW_STATION_CHOICES = [
  ['subtitles', 'Subtitles', [['off', 'Off'], ['forced', 'Forced only'], ['always', 'Always']], v => `${SUBS_HINTS[v]}${v === 'off' ? '' : ` ${SUBS_NOTE}`}`],
  ['breaks', 'Commercials & trailers', [[0, 'None'], [1, '1'], [2, '2'], [3, '3']], () => breaksHintText()],
  ['idSeconds', 'Station ID card', [[0, 'Off'], [3, '3 sec'], [5, '5 sec'], [10, '10 sec']], v => v ? 'After each program, a card shows the station’s logo, name, and what’s up next, with a short jingle.' : 'No card between programs.'],
  ['introSeconds', 'Intro Bumper', [[0, 'Off'], [3, '3 sec'], [5, '5 sec'], [10, '10 sec'], [15, '15 sec']], v => v ? 'When someone tunes in, a card shows the station’s logo, name, and what’s on, with the sound of an old TV dial being turned.' : 'Tuning in goes straight to the show.'],
  ['upNextSeconds', 'Up Next Banner', [[0, 'Off'], [3, '3 sec'], [5, '5 sec'], [10, '10 sec']], v => v ? 'Three minutes before each show or movie ends, a banner in the corner says what’s next.' : 'No banner says what’s up next.'],
  ['watermark', 'In the corner', [['off', 'Nothing'], ['logo', 'Logo'], ['name', 'Name'], ['clock', 'Clock']], v => ({
    off: 'Nothing is shown over the picture.',
    logo: 'The station’s logo in a corner during programs (or its name, if it has no logo).',
    name: 'The station’s name in a corner during programs.',
    clock: 'The time in a corner during programs.',
  })[v]],
  ['watermarkPosition', 'Corner', CORNERS, () => '', { when: c => c.watermark !== 'off', grid: true }],
];
// The setup's steps: each makes its page (from what's saved now) and, for a
// question, says how to save it (a sentence if that didn't work).
const SETUP_PAGES = {
  async checks({ checks, loadChecks }) {
    const list = h('div', { class: 'setup-checks' });
    const again = h('button', { type: 'button', class: 'btn', onclick: async () => {
      again.disabled = true;
      again.textContent = 'Checking…';
      paint(await loadChecks());
      again.disabled = false;
      again.textContent = 'Check again';
    } }, 'Check again');
    function paint(got) {
      list.replaceChildren(...(got ? got.map(checkRow)
        : [h('p', { class: 'muted', style: 'margin:0' }, 'Checking… (this takes a few seconds)')]));
    }
    paint(checks);
    return { node: h('div', { class: 'playback' },
      h('p', { class: 'hint', style: 'margin:0' }, `tapiOca checks the server itself: that it can read your media folder, how it encodes video, its clock, and its backups. ${
        // (1.36.0's words until what you use is saved; then Plex only where it's used.)
        !setupUses?.sources && !setupUses?.watchIn ? 'Plex has a step of its own, near the end. '
          : setupPlexWanted() ? 'Plex is checked in Connecting your apps, near the end. ' : ''
      }Anything marked Needs a look or Not working says what to do. After changing tapiOca’s app settings, restart it, then choose Check again.`),
      list,
      h('div', { class: 'row-btns' }, again)) };
  },

  async sources({ reloadPlex }) {
    const got = setupUses || await api('/api/setup/uses');
    const fields = usesFields(got);
    return { node: h('div', { class: 'playback' }, fields.sources), save: async () => {
      try { setupUses = await api('/api/setup/uses', { method: 'PUT', body: { sources: fields.values().sources } }); }
      catch (e) { return e.message; }
      reloadPlex();
    } };
  },

  async watchIn({ reloadPlex }) {
    const got = setupUses || await api('/api/setup/uses');
    const fields = usesFields(got);
    return { node: h('div', { class: 'playback' }, fields.watchIn), save: async () => {
      try { setupUses = await api('/api/setup/uses', { method: 'PUT', body: { watchIn: fields.values().watchIn } }); }
      catch (e) { return e.message; }
      reloadPlex();
    } };
  },

  async playback() {
    const pb = await api('/api/playback');
    const form = playbackForm(pb, { embedded: true });
    return { node: form, save: async () => {
      try {
        const saved = await api('/api/playback', { method: 'PUT', body: form.values() });
        NEW_STATION.picture = saved.picture;
        playbackSettings = saved;
      } catch (e) { return e.message; }
    } };
  },

  async newStation() {
    const pb = await api('/api/playback');
    // What new stations start with ("idSeconds" 0: no Station ID card), as saved now.
    const chosen = {};
    const starts = { ...NEW_STATION, ...pb.newStation };
    for (const [name] of NEW_STATION_CHOICES) chosen[name] = starts[name];
    if (!starts.stationId) chosen.idSeconds = 0;
    // (Every row is painted again on any choice: one can depend on another.)
    const painters = [];
    const paintChoices = () => painters.forEach(paint => paint());
    const node = h('div', { class: 'playback' },
      h('p', { class: 'hint', style: 'margin:0' }, 'The settings each new station starts with. You can change any of them for a station in its editor, which has even more options. Your existing stations stay as they are.'),
      ...NEW_STATION_CHOICES.map(([name, label, choices, hintOf, { when, grid } = {}]) => {
        const hint = h('span', { class: 'hint' });
        const seg = h('div', { class: grid ? 'seg corners' : 'seg', role: 'group', 'aria-label': label },
          ...choices.map(([value, words]) => h('button', { type: 'button', 'aria-pressed': 'false', onclick: () => { chosen[name] = value; paintChoices(); } }, words)));
        const row = h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, label), h('div', { class: 'opt-ctl' }, seg, hint));
        painters.push(() => {
          [...seg.children].forEach((b, n) => b.setAttribute('aria-pressed', String(choices[n][0] === chosen[name])));
          hint.textContent = hintOf(chosen[name]);
          hint.hidden = !hint.textContent;
          row.hidden = when ? !when(chosen) : false;
        });
        return row;
      }));
    paintChoices();
    return { node, save: async () => {
      const newStation = { ...chosen, stationId: chosen.idSeconds > 0 };
      if (!newStation.stationId) delete newStation.idSeconds;  // (its length stays as it was)
      try {
        const saved = await api('/api/playback', { method: 'PUT', body: { newStation } });
        Object.assign(NEW_STATION, saved.newStation, { picture: saved.picture });
      } catch (e) { return e.message; }
    } };
  },

  async signIn({ why } = {}) {
    // Signing in turned on makes the first Admin, when this step is left. A
    // new tapiOca has everyone sign in (1.36.0, the owner's D4); one updated
    // with signing in off keeps both choices. Either way, the network you're
    // on can be trusted, so its devices skip signing in (see trusted.js).
    const fresh = why === 'new' && !me.required;
    let signIn = me.required || fresh ? 'on' : 'off';
    let lists = null;
    try { lists = await api('/api/access/trusted'); } catch {}
    const offer = lists?.you?.offer || '';
    const listed = lists?.entries || [];
    const who = h('div', { class: 'playback' });
    const adminName = h('input', { type: 'text', autocomplete: 'username', maxlength: 40, 'aria-label': 'Your sign-in name' });
    const adminPassword = h('input', { type: 'password', autocomplete: 'new-password', minlength: ACCESS.passwordMin, maxlength: ACCESS.passwordMax, 'aria-label': 'Password' });
    const trust = h('input', { type: 'checkbox', onchange: () => paint() });
    const trustNetwork = h('input', { type: 'text', value: offer, maxlength: 50, 'aria-label': 'Your home network', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false' });
    const trustName = h('input', { type: 'text', value: 'Home network', maxlength: 40, 'aria-label': 'Its name' });
    const addresses = net => {
      const [, bits] = net.split('/');
      return net.includes(':') ? 'a whole IPv6 network' : `${(2 ** (32 - Number(bits || 32))).toLocaleString()} addresses`;
    };
    // The network to trust: offered when tapiOca can see where you are.
    const trustRows = () => {
      if (listed.length) {
        return [h('p', { class: 'hint', style: 'margin:0' }, `Trusted networks: ${listed.map(e => e.label || e.network).join(', ')}. Change them on the Access tab.`)];
      }
      if (!offer) {
        return [h('p', { class: 'hint', style: 'margin:0' }, 'tapiOca can’t see your device’s own address here, so it can’t offer your network. The Access tab says why.')];
      }
      return [
        h('label', { class: 'choice' }, trust, h('span', {}, h('strong', {}, 'Devices on my home network skip signing in'))),
        trust.checked ? h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Network'), h('div', { class: 'opt-ctl' }, trustNetwork)) : null,
        trust.checked ? h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Name'), h('div', { class: 'opt-ctl' }, trustName)) : null,
        h('p', { class: 'hint', style: 'margin:0' }, `That’s the network tapiOca sees you on: ${addresses(offer)}. Its devices open on Who’s tuning in?, where each person picks themselves, and kids get their own limits. Anyone with a PIN is asked for it, and an Admin always is. Never use a guest network.`),
      ];
    };
    const admin = () => [
      h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Your name'), h('div', { class: 'opt-ctl' }, adminName)),
      h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Password'), h('div', { class: 'opt-ctl' }, adminPassword,
        h('span', { class: 'hint' }, `At least ${ACCESS.passwordMin} characters.`))),
    ];
    // (What signing in doesn't change, in the apps you watch in: 1.37.0.)
    const watchLine = whoWatchesLine(setupWatchIn());
    const neither = watchLine ? h('span', { class: 'hint' }, watchLine) : null;
    const neitherLine = whoWatchesLine(setupWatchIn(), true);
    function paint() {
      if (me.required) {
        who.replaceChildren(
          h('p', { style: 'margin:0' }, `Sign-in is on, so only people you add can use tapiOca${me.user ? ` (you’re signed in as ${me.user.name})` : ''}. Add or remove people on the Access tab.`),
          ...trustRows().filter(Boolean));
        return;
      }
      if (fresh) {
        who.replaceChildren(...[
          h('p', { style: 'margin:0' }, 'Everyone signs in to tapiOca, at home and away. Make yourself the first Admin now, and you’ll be signed in right away.'),
          ...admin(), ...trustRows(), neither].filter(Boolean));
        return;
      }
      const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Who can use tapiOca' },
        h('button', { type: 'button', 'aria-pressed': String(signIn === 'off'), onclick: () => { signIn = 'off'; paint(); } }, 'Anyone on my network'),
        h('button', { type: 'button', 'aria-pressed': String(signIn === 'on'), onclick: () => { signIn = 'on'; paint(); } }, 'Only people who sign in'));
      who.replaceChildren(...[
        h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Who'), h('div', { class: 'opt-ctl' }, seg,
          // (Said plainly, the owner, October 13: "Does the first one allow
          // remote users too?" No: nobody, from the internet.)
          h('span', { class: 'hint' }, signIn === 'off'
            ? 'No signing in. Anyone at home, on your network or through a VPN into it (port 3310), can use tapiOca’s page and apps and change anything, as an Admin can. Nobody can from the internet (port 3311), even with Away from home on. tapiOca suggests Only people who sign in, with your home network trusted so its devices skip it.'
            : 'Everyone signs in, at home and away, as an Admin or a User. Make yourself the first Admin now, and you’ll be signed in right away. On the Access tab, you can add other people as Admins, or as Users who can make and change only their own stations. To use tapiOca’s apps from the internet (port 3311), also turn on Away from home on the Access tab.'),
          neitherLine ? h('span', { class: 'hint' }, neitherLine) : null)),
        ...(signIn === 'on' ? [...admin(), ...trustRows()] : []),
      ].filter(Boolean));
    }
    paint();
    return { node: who, save: async () => {
      if (!me.required && signIn === 'on') {
        const name = adminName.value.trim();
        if (!name || adminPassword.value.length < ACCESS.passwordMin) {
          return fresh
            ? `Enter a name and a password of at least ${ACCESS.passwordMin} characters.`
            : `Enter a name and a password of at least ${ACCESS.passwordMin} characters, or choose Anyone on my network.`;
        }
        try {
          await api('/api/access/users', { method: 'POST', body: { name, password: adminPassword.value, role: 'admin', maxStations: null } });
        } catch (e) { return e.message; }
        await loadMe();
        toast(`Sign-in is on, and you’re signed in as ${name}`);
      }
      // The network ticked: trusted, and new people show on every device
      // at home (else its Who's tuning in? lists no one new).
      if (me.required && trust.checked && !listed.length) {
        const entry = { network: trustNetwork.value.trim(), label: trustName.value.trim(), gives: 'picker', person: null };
        let body = { entries: [entry] };
        for (;;) {
          try { await api('/api/access/trusted', { method: 'PUT', body }); break; }
          catch (e) {
            if (e.status === 409 && !body.confirmWide && confirm(e.message)) { body = { ...body, confirmWide: true }; continue; }
            return e.message;
          }
        }
        listed.push(entry);
        try { await api('/api/access/devices/default', { method: 'PUT', body: { showOn: 'home' } }); } catch {}
        toast(`${entry.label || entry.network} is trusted: its devices skip signing in`);
      }
    } };
  },

  async viewing() {
    const intro = h('p', { class: 'hint', style: 'margin:0' }, 'A Viewing Level says what each person can see in tapiOca’s apps and on this page: movies and shows up to a rating, whether unrated ones are shown, and which Media folders. Unrestricted shows everything. Teen, Kid and Young Child are there to start from: on the Access tab you can rename them, change them or remove them, and add levels of your own, such as “Adults” with no R-rated movies. Admins always see everything.');
    const [users, view] = me.required
      ? await Promise.all([api('/api/access/users').catch(() => []), api('/api/access/viewing').catch(() => null)])
      : [[], null];
    if (!view) {
      return { node: h('div', { class: 'playback' }, intro,
        h('p', { style: 'margin:0' }, me.required
          ? 'The Viewing Levels can’t be read right now. You’ll find them on the Access tab.'
          : 'Viewing Levels come with signing in: choose Only people who sign in under Who can use tapiOca, then add people on the Access tab.')) };
    }
    viewing = view;
    // The level new people start on (1.34.1, the owner): Unrestricted until it's chosen.
    const startsOn = levelSelect(view.newLevel, { id: 'setupNewLevel' });
    const startsWas = startsOn.value;
    const newRow = h('div', { class: 'opt' }, h('label', { class: 'opt-label', for: 'setupNewLevel' }, 'New people start on'),
      h('div', { class: 'opt-ctl' }, startsOn, h('span', { class: 'hint' }, 'Everyone you add as a User starts on this level. You can choose another for each person as you add them, or later.')));
    const people = users.filter(u => u.role !== 'admin');
    const picks = new Map();
    const rows = people.map(u => {
      const select = levelSelect(view.users[u.id]?.level, { 'aria-label': `${u.name}’s Viewing Level` });
      picks.set(u.id, [select, select.value]);
      return h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, u.name), h('div', { class: 'opt-ctl' }, select));
    });
    return { node: h('div', { class: 'playback' }, intro, newRow, ...rows,
      h('p', { class: 'hint', style: 'margin:0' }, people.length
        ? 'On the Access tab, Stations beside someone’s name allows or blocks a station for them, and Devices chooses which devices they’re on and gives them a PIN.'
        : 'Everyone who signs in now is an Admin. When you add people on the Access tab, choose the devices they’re on there. On a shared TV, tapiOca’s apps ask Who’s tuning in? The first time, each person signs in on it with their password or an invite code. After that, they pick themselves, with their PIN if they have one.')),
    save: async () => {
      if (startsOn.value !== startsWas) {
        try { viewing.newLevel = (await api('/api/access/new-level', { method: 'PUT', body: { level: Number(startsOn.value) } })).newLevel; }
        catch (e) { return e.message; }
      }
      for (const [id, [select, was]] of picks) {
        if (select.value === was) continue;
        try { await api(`/api/access/users/${id}/viewing`, { method: 'PUT', body: { level: Number(select.value) } }); }
        catch (e) { return e.message; }
      }
    } };
  },

  async away() {
    let got = await api('/api/away');
    setAway(got);
    let warned = null;  // (the address it said to leave the port out of, once)
    const fields = awayFields(got, () => box.paint(), 'setupAway');
    // Saves what's changed: on leaving the step, and for Check now (a
    // sentence if that didn't work).
    const put = async () => {
      const { on, address } = fields.values();
      if (on === got.on && address.trim() === got.address) return;
      try { got = await api('/api/away', { method: 'PUT', body: { on, address } }); } catch (e) { return e.message; }
      setAway(got);
      fields.note(got.on && got.portProblem);
    };
    const box = reachStatus({ save: put, shown: () => fields.values().on });
    return { node: h('div', { class: 'playback' }, ...fields.nodes, box), save: async () => {
      const problem = await put();
      if (problem) return problem;
      // Saved with a port it can't have: said here once, before going on.
      if (got.on && got.portProblem && warned !== got.address) {
        warned = got.address;
        return `Saved, but ${lowerFirst(got.portProblem)}`;
      }
    } };
  },

  async library({ notYet }) {
    const got = await api('/api/app-libraries');
    const fields = libraryFields(got, () => {});
    // (Waiting for a choice, from before 1.34.1: going on is the choice,
    // once the Media folders can be listed. Until then nothing's shared, and
    // setup asks again next time, however it's left: 1.34.1's audit.)
    const cant = got.waiting && !('libraries' in fields.values());
    if (cant) notYet.add('library'); else notYet.delete('library');
    return { node: h('div', { class: 'playback' }, ...fields.nodes), save: async () => {
      if (cant || (!fields.changed() && !got.waiting)) return;
      try { await api('/api/app-libraries', { method: 'PUT', body: fields.values() }); } catch (e) { return e.message; }
    } };
  },

  async fileChecks() {
    const w = (await api('/api/scan')).window;
    const scanOn = h('input', { type: 'checkbox', checked: w.on });
    const scanStart = h('input', { type: 'time', value: w.start, 'aria-label': 'Start time' });
    const scanEnd = h('input', { type: 'time', value: w.end, 'aria-label': 'End time' });
    return { node: h('div', { class: 'playback' },
      h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'File checks'), h('div', { class: 'opt-ctl' },
        h('div', { class: 'scan-set' }, h('label', {}, scanOn, ' Deep scan every night from'), scanStart, h('span', {}, 'to'), scanEnd),
        h('span', { class: 'hint' }, 'New programs get a quick check within minutes of arriving. The deep scan plays every file all the way through, starting with what airs soonest, to find damage before it airs. It pauses while anyone is watching. Problems are listed on the Broken files tab, and other programs play in their place.'))),
      h('p', { class: 'hint', style: 'margin:0' }, 'With Sonarr or Radarr, tapiOca can also ask them to replace a damaged file: set that up on the Broken files tab, under Replacing files with Sonarr and Radarr.')),
    save: async () => {
      try { await api('/api/scan', { method: 'PUT', body: { on: scanOn.checked, start: scanStart.value, end: scanEnd.value } }); } catch (e) { return e.message; }
    } };
  },

  // Connecting your apps: Plex's checks, where Plex is a source or a place
  // to watch; then how to add tapiOca to each place you watch (each one,
  // while nothing's chosen), with its addresses (see addtoplex.js).
  async plex({ plexInfo, loadPlex }) {
    const wanted = setupPlexWanted();
    const chosen = setupWatchIn();
    const list = h('div', { class: 'setup-checks' });
    const again = h('button', { type: 'button', class: 'btn', onclick: async () => {
      again.disabled = true;
      again.textContent = 'Checking…';
      paint(await loadPlex());
      again.disabled = false;
      again.textContent = 'Check again';
    } }, 'Check again');
    const places = h('div', { class: 'places' });
    function paint(got) {
      list.replaceChildren(...(got ? got.checks.map(checkRow)
        : [h('p', { class: 'muted', style: 'margin:0' }, 'Checking Plex… (this takes a few seconds)')]));
      const tuner = got?.tunerUrl || status?.tunerUrl;
      const urls = { tuner, xmltv: got?.xmltvUrl || status?.xmltvUrl };
      places.replaceChildren(...WATCH_PLACES.filter(p => !chosen || chosen.includes(p))
        .map(p => placeSection(p, status, { inSetup: true, urls, plexConfigured: setupUses?.locked?.plex })));
    }
    paint(plexInfo);
    return { node: h('div', { class: 'playback' },
      h('p', { class: 'hint', style: 'margin:0' }, 'How to add tapiOca to each place you watch, with the addresses to enter there.'),
      ...(wanted ? [
        h('p', { class: 'hint', style: 'margin:0' }, 'tapiOca works with your own Plex Media Server. These checks say whether tapiOca can reach Plex and read its files, and whether Plex has added tapiOca.'),
        list,
        h('div', { class: 'row-btns' }, again),
      ] : []),
      places,
      h('p', { class: 'hint', style: 'margin:0' }, 'You’ll find these addresses on the Setup tab too, under Tuner integration.'),
      wanted ? PERSONAL_USE() : null) };
  },

  async done({ checks, plexInfo, why }) {
    // (Plex's checks count only where Plex is a source or a place: 1.37.0.)
    const all = [...(checks || []), ...(setupPlexWanted() ? plexInfo?.checks || [] : [])];
    const look = all.filter(needsLook);
    // What's set now, in a few words each.
    const [pb, away, libs, scan, view, upd] = await Promise.all([
      api('/api/playback'), api('/api/away'), api('/api/app-libraries').catch(() => null), api('/api/scan'),
      me.required ? api('/api/access/viewing').catch(() => null) : null,
      api('/api/updates').catch(() => null),
    ]);
    if (upd) updates = upd;
    setAway(away);
    const limited = view ? Object.values(view.users).filter(u => { const lv = view.levels.find(l => l.id === u.level); return (lv && levelLimited(lv)) || hidesCount(u.own?.blocks) > 0 || u.ownUnreadable; }).length : 0;
    const shared = libs ? libs.libraries.filter(l => libs.shared.includes(l.key)).map(l => l.title) : [];
    const sharing = libs?.everything ? 'Every Media folder' : shared.length ? `Shared: ${shared.join(', ')}` : libs?.shared.length ? 'On' : 'Not shared';
    const w = scan.window;
    const using = usesWords(setupUses?.sources, setupUses?.watchIn);
    const set = [
      ...(using.sources ? [['sources', using.sources]] : []),
      ...(using.watchIn ? [['watchIn', using.watchIn]] : []),
      ['playback', `${pb.picture} for new stations, ${plural(pb.tuners, 'tuner')}`],
      ['signIn', me.required ? 'Only people who sign in' : 'Anyone on your network'],
      ...(view ? [['viewing', limited ? `${limited === 1 ? '1 person' : `${limited} people`} with limits` : 'Everyone sees everything']] : []),
      ['away', h('span', { 'data-away-sum': 'Ready for apps away from home' }, awaySummary(away, 'Ready for apps away from home'))],
      ['library', sharing],
      ['fileChecks', w.on ? `Deep scan every night from ${clock(w.start)} to ${clock(w.end)}` : 'Quick checks only (the deep scan is off)'],
    ];
    // The update check (see updates.js), asked here: never ticked until an
    // Admin ticks it. Left unticked when setup's finished, that's No.
    const lookOut = h('input', { type: 'checkbox', checked: updates?.on === true, onchange: async e => {
      try { updates = await api('/api/updates', { method: 'PUT', body: { on: e.target.checked } }); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message, true); }
    } });
    return { save: async () => {
      if (updates && updates.on === null) {
        try { updates = await api('/api/updates', { method: 'PUT', body: { on: lookOut.checked } }); } catch {}
      }
      loadUpdates();
    }, node: h('div', { class: 'playback' },
      h('dl', { class: 'details', style: 'margin:0;font-size:14px' }, ...set.flatMap(([what, value]) => [h('dt', {}, SETUP_TITLES[what]), h('dd', {}, value)])),
      look.length
        ? h('div', { class: 'playback' }, h('p', { style: 'margin:0' }, look.length === 1 ? 'One thing still needs a look:' : 'A few things still need a look:'), h('div', { class: 'setup-checks' }, ...look.map(checkRow)))
        : h('p', { style: 'margin:0' }, !all.length ? 'That’s everything.'
          : all.some(c => c.state === 'wait') ? 'Everything tapiOca could check is working.' : 'Everything tapiOca checks is working.'),
      h('label', {}, lookOut, ' Tell me when a new tapiOca is out'),
      h('p', { class: 'hint', style: 'margin:0' }, `${UPDATE_PRIVACY} You can change this under New versions on the Setup tab.`),
      h('p', { class: 'hint', style: 'margin:0' }, why === 'new' ? `Choose Finish, then New station to make your first one. ${SETUP_AGAIN}` : SETUP_AGAIN)) };
  },
};
$('#noticeOk').addEventListener('click', () => $('#notice').close());
