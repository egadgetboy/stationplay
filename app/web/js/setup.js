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
  playback: 'How stations play',
  newStation: 'New station settings',
  signIn: 'Who can use tapiOca',
  viewing: 'Who sees what',
  away: 'Watching away from home',
  library: 'Media in tapiOca’s apps',
  fileChecks: 'Checking files',
  plex: 'Tuner',  // (where you watch, and how to add tapiOca there: 1.36.3)
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
// The Tuner step's Plex checks: whether Plex answers, whether tapiOca finds
// the files Plex lists, and whether Plex has tapiOca as a DVR; with the
// addresses to give Plex.
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
// Plex's terms, which tapiOca's own use of Plex goes by (see the README's
// What you need, and PRIVACY.md).
const PERSONAL_USE = () => h('div', { class: 'limit-note' }, h('strong', {}, 'Plex’s terms. '),
  'Plex’s terms license Plex Media Server for personal use, on hardware and storage you own. Use tapiOca with your Plex server as those terms allow. ',
  h('a', { href: 'https://www.plex.tv/about/privacy-legal/plex-terms-of-service/', target: '_blank', rel: 'noopener noreferrer' }, 'Plex’s terms'), ' · ',
  h('a', { href: '/privacy', target: '_blank', rel: 'noopener noreferrer' }, 'tapiOca’s privacy notice'));
// Where you watch (1.36.3, see setup.py): the Tuner step's question, which
// apps you'll watch your stations in, each with its own steps below it.
// Kept as saved (GET /api/setup/watch-in), so All set can say it. It only
// changes what the step shows: every app can still use the tuner.
// `watchDraft`: what's ticked and not yet saved, kept while the step is
// painted again (as when Plex's checks arrive).
let setupWatch = null, watchDraft = null;
const WATCH_CHOICES = [
  ['plex', 'Plex'],
  ['jellyfin', 'Jellyfin'],
  ['emby', 'Emby'],
  ['kodi', 'Kodi'],
  ['other', 'Another app', 'an M3U playlist and XMLTV guide'],
  ['tapioca', 'Only tapiOca’s own apps'],
];
const NO_WATCH_IN = 'Choose at least one app, or Only tapiOca’s own apps.';
// The choices after ticking or unticking `value`, in the order listed.
// Only tapiOca's own apps goes on its own: ticking it clears the others,
// and ticking another clears it.
function watchToggled(chosen, value, on) {
  if (!on) return chosen.filter(v => v !== value);
  const kept = value === 'tapioca' ? [] : chosen.filter(v => v !== 'tapioca');
  return WATCH_CHOICES.map(([v]) => v).filter(v => v === value || kept.includes(v));
}
// What's chosen, in a few words: "Plex and Jellyfin", "Only tapiOca’s own
// apps"; empty while nothing is.
function watchInWords(watchIn) {
  const names = { plex: 'Plex', jellyfin: 'Jellyfin', emby: 'Emby', kodi: 'Kodi', other: 'another app', tapioca: 'only tapiOca’s own apps' };
  const said = WATCH_CHOICES.map(([v]) => v).filter(v => (watchIn || []).includes(v)).map(v => names[v]);
  const text = said.length < 2 ? (said[0] || '') : `${said.slice(0, -1).join(', ')} and ${said[said.length - 1]}`;
  return text && text[0].toUpperCase() + text.slice(1);
}
// How to add tapiOca to an app other than Plex, with the addresses it
// uses (`urls`: m3u and guide), as the README's Watch your stations says.
function watchSection(place, urls) {
  const em = text => h('em', {}, text);
  const hint = (...kids) => h('p', { class: 'hint', style: 'margin:0' }, ...kids);
  const copyRow = (what, value) => value ? h('div', { class: 'copyrow' }, h('span', { class: 'what' }, what), h('code', {}, value), copyButton(value)) : null;
  if (place === 'tapioca') {
    return h('div', { class: 'playback watch-app', 'data-watch': place },
      hint('Nothing else is needed. tapiOca’s own apps get your stations straight from tapiOca.'));
  }
  const name = { jellyfin: 'Jellyfin', emby: 'Emby', kodi: 'Kodi' }[place];
  const steps = {
    jellyfin: [
      h('li', {}, 'In Jellyfin’s dashboard, open ', em('Live TV'), ' and choose ', em('+'), ' next to ', em('Tuner Devices'), '.'),
      h('li', {}, 'Choose ', em('M3U Tuner'), ' and enter the playlist address above. Save.'),
      h('li', {}, 'Choose ', em('+'), ' next to ', em('TV Guide Data Providers'), ', choose ', em('XMLTV'), ' and enter the guide address above. Save.'),
    ],
    emby: [
      h('li', {}, 'In Emby’s settings, open ', em('Live TV'), ' and add a TV source. Choose ', em('M3U Tuner'), ' and enter the playlist address above.'),
      h('li', {}, 'Add a guide data provider. Choose ', em('XMLTV'), ' and enter the guide address above.'),
    ],
    kodi: [
      h('li', {}, 'Install Kodi’s PVR Simple Client add-on (', em('Add-ons → Install from repository → PVR clients'), ').'),
      h('li', {}, 'In its settings, set the playlist location to remote and set ', em('M3U play list URL'), ' to the playlist address above. The playlist includes the guide’s address, so ', em('XMLTV URL'), ' can stay empty. You can also enter the guide address there.'),
      h('li', {}, 'Restart Kodi, or turn the add-on off and on. Your stations appear under ', em('TV'), '.'),
    ],
    other: [
      h('li', {}, 'Give the app the playlist address above. Channels DVR and VLC accept it, and it tells them where to find the guide.'),
      h('li', {}, 'If the app asks for a guide (XMLTV) too, enter the guide address above.'),
    ],
  }[place];
  const notes = {
    jellyfin: [
      hint('Leave Jellyfin’s limit on simultaneous streams at its default (no limit). tapiOca enforces its own.'),
      hint('Jellyfin downloads the guide on its own schedule, about once a day. After you change a station, refresh it in Jellyfin: ', em('Dashboard → Scheduled Tasks → Refresh Guide'), '.'),
    ],
    emby: [
      hint('Emby downloads the guide on its own schedule, about once a day. After you change a station, refresh the guide in Emby to see it right away.'),
      hint('Emby’s Live TV needs Emby Premiere.'),
    ],
    kodi: [hint('Kodi downloads the guide on its own schedule, about once a day. After you change a station, refresh the guide in Kodi to see it right away.')],
    other: [hint('Other apps download the guide on their own schedule, about once a day. After you change a station, refresh the guide in the app to see it right away.')],
  }[place];
  return h('div', { class: 'playback watch-app', 'data-watch': place },
    h('strong', { class: 'small' }, name ? `Adding tapiOca to ${name}` : 'Adding tapiOca to another app'),
    copyRow(name ? `Playlist (M3U) for ${name}` : 'Playlist (M3U)', urls.m3u),
    copyRow(name ? `Guide (XMLTV) for ${name}` : 'Guide (XMLTV)', urls.guide),
    h(place === 'other' ? 'ul' : 'ol', { class: 'steps' }, ...steps),
    ...notes);
}
const SETUP_AGAIN = 'You can run setup again any time from the Setup tab, or the Setup link at the foot of the page.';
// `why`: "new" (a new tapiOca), "updated" (an update has new questions),
// or "again" (run again).
async function showSetup(st, why) {
  const dlg = $('#setupDlg');
  setupWatch = watchDraft = null;  // (where you watch: read afresh each time)
  // Checks run first after an update: they decide whether that step is shown.
  let checks = why === 'updated' ? await setupChecks() : null;
  const steps = why === 'updated'
    ? [...(checks?.some(needsLook) ? ['checks'] : []), ...st.pending, 'done']
    : ['checks', ...st.questions, 'done'];
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
  if (steps.includes('plex')) loadPlex().then(() => { if (steps[step] === 'plex' || steps[step] === 'done') show(); });

  function paintNav() {
    nav.replaceChildren(...steps.map((s, n) => {
      const attention = (s === 'checks' && checks?.some(needsLook)) || (s === 'plex' && plexInfo?.checks.some(needsLook));
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
      // (`goTo`: a way to another step of this setup, if it has that step.)
      const goTo = to => steps.includes(to) ? () => go(steps.indexOf(to)) : null;
      page = await SETUP_PAGES[s]({ checks, loadChecks, plexInfo, loadPlex, why, st, shownQuestions, saved, notYet, goTo });
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
      h('p', { class: 'hint', style: 'margin:0' }, 'tapiOca checks the server itself: that it can read your media folder, how it encodes video, its clock, and its backups. Plex is checked in the Tuner step, near the end. Anything marked Needs a look or Not working says what to do. After changing tapiOca’s app settings, restart it, then choose Check again.'),
      list,
      h('div', { class: 'row-btns' }, again)) };
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
        h('span', { class: 'hint' }, `At least ${ACCESS.passwordMin} characters. A few words together work well, such as three or four that mean something to you. tapiOca turns away the most common passwords, and ones built from your name.`))),
    ];
    const neither = h('span', { class: 'hint' }, 'Signing in doesn’t change who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself.');
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
          h('span', { class: 'hint' }, 'Neither changes who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself.'))),
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
      // The network ticked: trusted (its devices are linked without signing
      // in; each person signs in once on each, from 1.38.0).
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

  async away({ goTo }) {
    let got = await api('/api/away');
    setAway(got);
    let warned = null;  // (the address it said to leave the port out of, once)
    // (Sign-in off: Turn on sign-in goes back to Who can use tapiOca.)
    const fields = awayFields(got, () => box.paint(), 'setupAway', { turnOn: goTo('signIn') || ' Add the first user on the Access tab to turn it on.' });
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
    // (Even sound, here too from 1.36.4: the owner couldn't find it on the Access tab.)
    const even = evenSoundField(got, () => {}, 'setupEvenSound');
    // (Waiting for a choice, from before 1.34.1: going on is the choice,
    // once the Media folders can be listed. Until then nothing's shared, and
    // setup asks again next time, however it's left: 1.34.1's audit.)
    const cant = got.waiting && !('libraries' in fields.values());
    if (cant) notYet.add('library'); else notYet.delete('library');
    return { node: h('div', { class: 'playback' }, ...fields.nodes, even.node), save: async () => {
      const evenChanged = even.input.checked !== got.evenSound;
      // (The folders can't be listed, or aren't changed: Even sound alone, if it changed, so
      // the folders' choice stays as it is, those added later included. 1.36.4's audit.)
      if (cant || (!fields.changed() && !got.waiting)) {
        if (!evenChanged) return;
        try { await api('/api/app-libraries', { method: 'PUT', body: { evenSound: even.input.checked } }); } catch (e) { return e.message; }
        return;
      }
      const body = { ...fields.values(), evenSound: even.input.checked };
      if (!got.waiting && !fields.librariesChanged()) delete body.libraries;  // (see libraryFields)
      try { await api('/api/app-libraries', { method: 'PUT', body }); } catch (e) { return e.message; }
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

  // The Tuner step (1.36.3, the owner: "I think maybe calling the step
  // Tuner is better"): where you'll watch, then for each app ticked, how to
  // add tapiOca to it. Plex's checks show with Plex ticked; and without it,
  // while tapiOca gets your shows and movies from Plex, or they need a look.
  async plex({ plexInfo, loadPlex }) {
    if (!setupWatch) {
      try { setupWatch = await api('/api/setup/watch-in'); } catch { setupWatch = null; }
    }
    // (Saved, or before it is, what the server suggests: Plex, if it's set up or has used the tuner.)
    let chosen = watchDraft || [...(setupWatch?.watchIn || setupWatch?.suggested || [])];
    let plexGot = plexInfo;
    const em = text => h('em', {}, text);
    const hint = (...kids) => h('p', { class: 'hint', style: 'margin:0' }, ...kids);
    const list = h('div', { class: 'setup-checks' });
    const again = h('button', { type: 'button', class: 'btn', onclick: async () => {
      again.disabled = true;
      again.textContent = 'Checking…';
      plexGot = await loadPlex();
      paintChecks();
      again.disabled = false;
      again.textContent = 'Check again';
    } }, 'Check again');
    const copyRow = (what, value) => h('div', { class: 'copyrow' }, h('span', { class: 'what' }, what), h('code', {}, value), copyButton(value));
    const plexAddresses = h('div', { class: 'playback' });
    const boxes = WATCH_CHOICES.map(([value, name, more]) => {
      const input = h('input', { type: 'checkbox', onchange: e => {
        chosen = watchToggled(chosen, value, e.target.checked);
        paint();
      } });
      return [value, input, h('label', { class: 'choice' }, input,
        h('span', {}, h('strong', {}, name), more ? h('span', { class: 'hint' }, ` (${more})`) : null))];
    });
    const none = h('p', { class: 'hint', role: 'status', style: 'margin:0' }, NO_WATCH_IN);
    const question = h('div', { class: 'playback watch-in', role: 'group', 'aria-labelledby': 'watchInAsk' },
      h('strong', { id: 'watchInAsk' }, 'Will you watch your stations in other apps?'),
      hint('Choose each app you’ll use, one or more. tapiOca shows the steps for each below. This only changes what this step shows: every app can still use tapiOca’s tuner.'),
      h('div', { class: 'checks-col' }, ...boxes.map(([, , label]) => label)),
      none);
    const plexChecks = h('div', { class: 'playback' },
      hint('tapiOca works with your own Plex Media Server. These checks say whether tapiOca can reach Plex and read the files Plex lists, and whether Plex has added tapiOca.'),
      list,
      h('div', { class: 'row-btns' }, again),
      // (Plex's terms go with Plex's checks, so they show whenever tapiOca uses Plex: with Plex
      // unticked too. 1.36.3's audit.)
      PERSONAL_USE());
    const plexSteps = h('div', { class: 'playback' },
      h('strong', { class: 'small' }, 'Adding tapiOca to Plex'),
      h('ol', { class: 'steps' },
        h('li', {}, 'In Plex, open ', em('Settings → Live TV & DVR → Set Up Plex DVR'), '.'),
        h('li', {}, 'Choose ', em('Don’t see your HDHomeRun device? Enter its network address manually'), ' (Plex can’t find tapiOca on its own) and enter the tuner address below.'),
        h('li', {}, 'When Plex asks for guide data, choose ', em('Have an XMLTV guide on your server? Click here to use it'), ' and enter the guide address below.'),
        h('li', {}, 'Plex matches your stations automatically (it calls them channels). Each time you make a new station, choose ', em('Scan for channels'), ' in Plex’s Live TV & DVR settings so Plex adds it.'),
        h('li', {}, 'Then choose Check again here.')),
      hint('If Plex says “There was a problem fetching channel mappings,” reload Plex’s page and start again. Plex renames the tuner partway through setup, so it may still know tapiOca’s tuner from before.'),
      hint('Plex needs at least one station to add tapiOca, so a new tapiOca starts with INFO on station 99: the date and time, what’s new in tapiOca and tips for watching. It plays even before Plex is connected.'),
      plexAddresses,
      hint('Watching in Plex needs Plex Pass on the account that owns your Plex server. You’ll find these addresses on the Setup tab too, under Tuner integration.'));
    // (Plex unticked: its checks, with a word on why they're here.)
    const plexOnly = hint('tapiOca gets your shows and movies from Plex, so Plex is checked here too.');
    const apps = h('div', { class: 'playback' });
    function paintChecks() {
      list.replaceChildren(...(plexGot ? plexGot.checks.map(checkRow)
        : [h('p', { class: 'muted', style: 'margin:0' }, 'Checking Plex… (this takes a few seconds)')]));
      const tuner = plexGot?.tunerUrl || status?.tunerUrl, guide = plexGot?.xmltvUrl || status?.xmltvUrl;
      plexAddresses.replaceChildren(...[tuner ? copyRow('Tuner address', tuner) : null, guide ? copyRow('Guide (XMLTV) for Plex', guide) : null].filter(Boolean));
      paintApps();
    }
    function paintApps() {
      const tuner = plexGot?.tunerUrl || status?.tunerUrl || '';
      const urls = { m3u: status?.m3uUrl || (tuner && `${tuner}/stations.m3u`), guide: status?.guideUrl || (tuner && `${tuner}/guide.xml`) };
      const plex = chosen.includes('plex');
      const checksAnyway = !plex && (status?.plex?.configured || plexGot?.checks.some(needsLook));
      apps.replaceChildren(...[
        plex ? h('div', { class: 'playback watch-app', 'data-watch': 'plex' }, plexChecks, plexSteps) : null,
        checksAnyway ? h('div', { class: 'playback watch-app', 'data-watch': 'plex-checks' }, h('strong', { class: 'small' }, 'Plex'), status?.plex?.configured ? plexOnly : null, plexChecks) : null,
        ...chosen.filter(p => p !== 'plex').map(p => watchSection(p, urls)),
      ].filter(Boolean));
    }
    function paint() {
      watchDraft = chosen;
      for (const [value, input] of boxes) input.checked = chosen.includes(value);
      none.hidden = chosen.length > 0;
      paintApps();
    }
    paint();
    paintChecks();
    return { node: h('div', { class: 'playback' }, question, apps), save: async () => {
      if (!chosen.length) return NO_WATCH_IN;
      try { setupWatch = await api('/api/setup/watch-in', { method: 'PUT', body: { watchIn: chosen } }); }
      catch (e) { return e.message; }
    } };
  },

  async done({ checks, plexInfo, why }) {
    const all = [...(checks || []), ...(plexInfo?.checks || [])];
    const look = all.filter(needsLook);
    // What's set now, in a few words each.
    const [pb, away, libs, scan, view, upd, watching] = await Promise.all([
      api('/api/playback'), api('/api/away'), api('/api/app-libraries').catch(() => null), api('/api/scan'),
      me.required ? api('/api/access/viewing').catch(() => null) : null,
      api('/api/updates').catch(() => null),
      setupWatch || api('/api/setup/watch-in').catch(() => null),
    ]);
    if (upd) updates = upd;
    setAway(away);
    const limited = view ? Object.values(view.users).filter(u => { const lv = view.levels.find(l => l.id === u.level); return (lv && levelLimited(lv)) || hidesCount(u.own?.blocks) > 0 || u.ownUnreadable; }).length : 0;
    const shared = libs ? libs.libraries.filter(l => libs.shared.includes(l.key)).map(l => l.title) : [];
    const sharing = libs?.everything ? 'Every Media folder' : shared.length ? `Shared: ${shared.join(', ')}` : libs?.shared.length ? 'On' : 'Not shared';
    const w = scan.window;
    const set = [
      ['playback', `${pb.picture} for new stations, ${plural(pb.tuners, 'tuner')}`],
      ['signIn', me.required ? 'Only people who sign in' : 'Anyone on your network'],
      ...(view ? [['viewing', limited ? `${limited === 1 ? '1 person' : `${limited} people`} with limits` : 'Everyone sees everything']] : []),
      ['away', h('span', { 'data-away-sum': 'Ready for apps away from home' }, awaySummary(away, 'Ready for apps away from home'))],
      ['library', sharing],
      ['fileChecks', w.on ? `Deep scan every night from ${clock(w.start)} to ${clock(w.end)}` : 'Quick checks only (the deep scan is off)'],
      // (Where you watch, once it's saved: "Plex and Jellyfin".)
      ...(watchInWords(watching?.watchIn) ? [['plex', watchInWords(watching.watchIn)]] : []),
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
