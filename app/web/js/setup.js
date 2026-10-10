// The setup's dialog and its steps.
// The setup (see setup.py) -------------------------------------------------------------
// For an Admin (or anyone, while signing in is off). When StationPlay is
// new: every question, with checks that what's set up is working. After an
// update that brings new or changed questions: just those, once (and the
// checks, if something needs a look). And everything, whenever it's run
// again (Run setup again on the Add to Plex tab, or Setup at the foot of the
// page), with the current answers filled in. Each answer is saved as you go
// on from it; Skip setup (or Close) keeps everything else as it is.
const SETUP_TITLES = {
  checks: 'Checking your server',
  playback: 'How stations play',
  newStation: 'New station settings',
  signIn: 'Who can use StationPlay',
  viewing: 'Who sees what',
  away: 'Watching away from home',
  library: 'Media in StationPlay’s apps',
  fileChecks: 'Checking files',
  plex: 'Adding StationPlay to Plex',
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
async function setupChecks() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  try {
    return (await api(`/api/setup/checks?offset=${-new Date().getTimezoneOffset()}&zone=${encodeURIComponent(zone)}`)).checks;
  } catch { return null; }
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
const SETUP_AGAIN = 'You can run setup again any time from the Add to Plex tab, or Setup at the foot of the page.';
// `why`: "new" (a new StationPlay), "updated" (an update has new questions),
// or "again" (run again).
async function showSetup(st, why) {
  const dlg = $('#setupDlg');
  // Checks run first after an update: they decide whether that step is shown.
  let checks = why === 'updated' ? await setupChecks() : null;
  const steps = why === 'updated'
    ? [...(checks?.some(needsLook) ? ['checks'] : []), ...st.pending, 'done']
    : ['checks', ...st.questions, 'done'];
  const shownQuestions = steps.filter(s => st.questions.includes(s));
  const saved = new Set();  // (steps saved, or looked at, this time)
  let step = 0, page = null, leaving = false;
  const nav = h('ol', { class: 'setup-nav', 'aria-label': 'Steps' });
  const title = h('h4', { class: 'wstep' });
  const body = h('div', { class: 'setup-page' });
  const intro = h('p', { style: 'margin:0' }, {
    new: 'A few questions to set StationPlay up, and checks that everything is working. Each answer is saved when you go on to the next step, and you can change any of them later.',
    updated: `${status?.version ? `StationPlay ${status.version}` : 'This version of StationPlay'} has ${st.pending.length === 1 ? 'a new question' : 'new questions'} for you${steps[0] === 'checks' ? ', and something on your server needs a look' : ''}. Everything else stays as you set it.`,
    again: 'Here’s everything, with your current answers. Change anything you like: each answer is saved when you go on to the next step.',
  }[why]);
  const said = h('span', { class: 'hint', role: 'alert' });
  const back = h('button', { type: 'button', class: 'btn', onclick: () => go(step - 1) }, 'Back');
  const next = h('button', { type: 'button', class: 'btn primary', autofocus: true, onclick: () => step === steps.length - 1 ? finish() : go(step + 1) });
  const later = h('button', { type: 'button', class: 'btn ghost', onclick: closeSetup,
    title: `Your answers so far are kept. ${SETUP_AGAIN}` }, why === 'new' ? 'Skip setup' : 'Close');
  // Checks are loaded once, and again on Check again; while they load, the step says so.
  const loadChecks = async () => {
    checks = null;
    paintNav();
    checks = await setupChecks();
    paintNav();
    return checks;
  };
  if (!checks && steps.includes('checks')) loadChecks().then(() => { if (steps[step] === 'checks' || steps[step] === 'plex' || steps[step] === 'done') show(); });

  function paintNav() {
    nav.replaceChildren(...steps.map((s, n) => {
      const attention = (s === 'checks' && checks?.some(needsLook)) || (s === 'plex' && checks?.some(c => c.id === 'dvr' && needsLook(c)));
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
      page = await SETUP_PAGES[s]({ checks, loadChecks, why, st, shownQuestions, saved });
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
    if (st.questions.includes(s)) {
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
      try { await api('/api/setup', { method: 'PUT', body: { answered: shownQuestions } }); } catch {}
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
  $('#setupTitle').textContent = { new: 'Welcome to StationPlay', updated: 'What’s new in StationPlay', again: 'Setting up StationPlay' }[why];
  $('#setupBody').replaceChildren(intro, h('div', { class: 'setup-grid' }, nav, h('div', { class: 'setup-main' }, title, body)));
  $('#setupFoot').replaceChildren(later, h('div', { class: 'spacer' }), said, back, next);
  step = 0;
  await show();
  if (!dlg.open) dlg.showModal();

  // Skip setup, Close, ✕ or Escape: the questions shown count as answered
  // (they aren't asked again by themselves), and nothing else changes.
  async function closeSetup() {
    dlg.close();
    try { await api('/api/setup', { method: 'PUT', body: { answered: shownQuestions } }); } catch {}
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
      list.replaceChildren(...(got ? got.filter(c => c.id !== 'dvr').map(checkRow)
        : [h('p', { class: 'muted', style: 'margin:0' }, 'Checking… (this takes a few seconds)')]));
    }
    paint(checks);
    return { node: h('div', { class: 'playback' },
      h('p', { class: 'hint', style: 'margin:0' }, 'StationPlay checks that it can reach Plex and read your files, how it encodes video, its clock, and its backups. Anything marked Needs a look or Not working says what to do. After changing StationPlay’s app settings, restart it, then choose Check again.'),
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

  async signIn() {
    // Signing in turned on makes the first Admin, when this step is left.
    let signIn = me.required ? 'on' : 'off';
    const who = h('div', { class: 'playback' });
    const adminName = h('input', { type: 'text', autocomplete: 'username', maxlength: 40, 'aria-label': 'Your sign-in name' });
    const adminPassword = h('input', { type: 'password', autocomplete: 'new-password', minlength: ACCESS.passwordMin, maxlength: ACCESS.passwordMax, 'aria-label': 'Password' });
    function paint() {
      if (me.required) {
        who.replaceChildren(h('p', { style: 'margin:0' }, `Sign-in is on, so only people you add can use StationPlay${me.user ? ` (you’re signed in as ${me.user.name})` : ''}. Add or remove people on the Access tab.`));
        return;
      }
      const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Who can use StationPlay' },
        h('button', { type: 'button', 'aria-pressed': String(signIn === 'off'), onclick: () => { signIn = 'off'; paint(); } }, 'Anyone on my network'),
        h('button', { type: 'button', 'aria-pressed': String(signIn === 'on'), onclick: () => { signIn = 'on'; paint(); } }, 'Only people who sign in'));
      who.replaceChildren(...[
        h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Who'), h('div', { class: 'opt-ctl' }, seg,
          h('span', { class: 'hint' }, signIn === 'off'
            ? 'Anyone on your network who can open this page can use StationPlay. From the internet, StationPlay always asks people to sign in. Either way, Plex decides who can watch in Plex.'
            : 'Make yourself the first Admin now, and you’ll be signed in right away. On the Access tab, you can add other people as Admins, or as Users who can make and change only their own stations.'))),
        signIn === 'on' ? h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Your name'), h('div', { class: 'opt-ctl' }, adminName)) : null,
        signIn === 'on' ? h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Password'), h('div', { class: 'opt-ctl' }, adminPassword,
          h('span', { class: 'hint' }, `At least ${ACCESS.passwordMin} characters.`))) : null,
      ].filter(Boolean));
    }
    paint();
    return { node: who, save: async () => {
      if (me.required || signIn === 'off') return;
      const name = adminName.value.trim();
      if (!name || adminPassword.value.length < ACCESS.passwordMin) {
        return `Enter a name and a password of at least ${ACCESS.passwordMin} characters, or choose Anyone on my network.`;
      }
      try {
        await api('/api/access/users', { method: 'POST', body: { name, password: adminPassword.value, role: 'admin', maxStations: null } });
      } catch (e) { return e.message; }
      await loadMe();
      toast(`Sign-in is on, and you’re signed in as ${name}`);
    } };
  },

  async viewing() {
    const intro = h('p', { class: 'hint', style: 'margin:0' }, 'A Viewing Level says what each person can see in StationPlay’s apps and on this page: movies and shows up to a rating, whether unrated ones are shown, and which libraries. Everyone starts on Unrestricted, which shows everything. Teen, Kid and Young Child are there to start from: on the Access tab you can rename them, change them or remove them, and add levels of your own, such as “Adults” with no R-rated movies. Admins always see everything.');
    const [users, view] = me.required
      ? await Promise.all([api('/api/access/users').catch(() => []), api('/api/access/viewing').catch(() => null)])
      : [[], null];
    const people = users.filter(u => u.role !== 'admin');
    if (!view || !people.length) {
      return { node: h('div', { class: 'playback' }, intro,
        h('p', { style: 'margin:0' }, me.required
          ? 'Everyone who signs in now is an Admin. When you add people on the Access tab, choose a Viewing Level for each there, and the devices they’re on: on a shared TV, StationPlay’s apps ask Who’s tuning in?, and each person picks themselves.'
          : 'Viewing Levels come with signing in: choose Only people who sign in under Who can use StationPlay, then add people on the Access tab.')) };
    }
    viewing = view;
    const picks = new Map();
    const rows = people.map(u => {
      const select = levelSelect(view.users[u.id]?.level, { 'aria-label': `${u.name}’s Viewing Level` });
      picks.set(u.id, [select, select.value]);
      return h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, u.name), h('div', { class: 'opt-ctl' }, select));
    });
    return { node: h('div', { class: 'playback' }, intro, ...rows,
      h('p', { class: 'hint', style: 'margin:0' }, 'On the Access tab, Stations beside someone’s name allows or blocks a station for them, and Devices chooses which devices they’re on and gives them a passcode.')),
    save: async () => {
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

  async library() {
    const got = await api('/api/app-libraries');
    const fields = libraryFields(got, () => {});
    return { node: h('div', { class: 'playback' }, ...fields.nodes), save: async () => {
      if (!fields.changed()) return;
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
      h('p', { class: 'hint', style: 'margin:0' }, 'With Sonarr or Radarr, StationPlay can also ask them to replace a damaged file: set that up on the Broken files tab, under Replacing files with Sonarr and Radarr.')),
    save: async () => {
      try { await api('/api/scan', { method: 'PUT', body: { on: scanOn.checked, start: scanStart.value, end: scanEnd.value } }); } catch (e) { return e.message; }
    } };
  },

  async plex({ checks, loadChecks }) {
    const where = h('div', {});
    const again = h('button', { type: 'button', class: 'btn', onclick: async () => {
      again.disabled = true;
      again.textContent = 'Checking…';
      paint(await loadChecks());
      again.disabled = false;
      again.textContent = 'Check again';
    } }, 'Check again');
    function paint(got) {
      const dvr = got?.find(c => c.id === 'dvr');
      where.replaceChildren(dvr ? checkRow(dvr) : h('p', { class: 'muted small', style: 'margin:0' }, got ? '' : 'Checking whether Plex has StationPlay…'));
    }
    paint(checks);
    const copyRow = (what, value) => h('div', { class: 'copyrow' }, h('span', { class: 'what' }, what), h('code', {}, value),
      h('button', { type: 'button', class: 'btn', onclick: () => copyText(value) }, 'Copy'));
    return { node: h('div', { class: 'playback' },
      h('div', { class: 'row-btns', style: 'align-items:flex-start' }, h('div', { style: 'flex:1' }, where), again),
      h('ol', { class: 'steps' },
        h('li', {}, 'In Plex, open ', h('em', {}, 'Settings → Live TV & DVR → Set Up Plex DVR'), '.'),
        h('li', {}, 'Choose ', h('em', {}, 'Don’t see your HDHomeRun device? Enter its network address manually'), ' (Plex can’t find StationPlay on its own) and enter the tuner address below.'),
        h('li', {}, 'When Plex asks for guide data, choose ', h('em', {}, 'Have an XMLTV guide on your server? Click here to use it'), ' and enter the guide address below.'),
        h('li', {}, 'Plex matches your stations automatically (it calls them channels). Each time you make a new station, choose ', h('em', {}, 'Scan for channels'), ' in Plex’s Live TV & DVR settings so Plex adds it.'),
        h('li', {}, 'Then choose Check again here.')),
      status?.tunerUrl ? copyRow('Tuner address', status.tunerUrl) : null,
      status?.xmltvUrl ? copyRow('Guide (XMLTV) for Plex', status.xmltvUrl) : null,
      h('p', { class: 'hint', style: 'margin:0' }, 'Watching in Plex needs Plex Pass on the account that owns your Plex server. You’ll find these addresses, plus the ones for Jellyfin, Emby, Kodi and other apps, on the Add to Plex tab.')) };
  },

  async done({ checks, why }) {
    const look = (checks || []).filter(needsLook);
    // What's set now, in a few words each.
    const [pb, away, libs, scan, view] = await Promise.all([
      api('/api/playback'), api('/api/away'), api('/api/app-libraries').catch(() => null), api('/api/scan'),
      me.required ? api('/api/access/viewing').catch(() => null) : null,
    ]);
    setAway(away);
    const limited = view ? Object.values(view.users).filter(u => { const lv = view.levels.find(l => l.id === u.level); return lv && levelLimited(lv); }).length : 0;
    const shared = libs ? libs.libraries.filter(l => libs.shared.includes(l.key)).map(l => l.title) : [];
    const w = scan.window;
    const set = [
      ['playback', `${pb.picture} for new stations, ${plural(pb.tuners, 'tuner')}`],
      ['signIn', me.required ? 'Only people who sign in' : 'Anyone on your network'],
      ...(view ? [['viewing', limited ? `${limited === 1 ? '1 person' : `${limited} people`} on a level with limits` : 'Everyone sees everything']] : []),
      ['away', h('span', { 'data-away-sum': 'Ready for apps away from home' }, awaySummary(away, 'Ready for apps away from home'))],
      ['library', shared.length ? `Shared: ${shared.join(', ')}` : 'Not shared'],
      ['fileChecks', w.on ? `Deep scan every night from ${clock(w.start)} to ${clock(w.end)}` : 'Quick checks only (the deep scan is off)'],
    ];
    return { node: h('div', { class: 'playback' },
      h('dl', { class: 'details', style: 'margin:0;font-size:14px' }, ...set.flatMap(([what, value]) => [h('dt', {}, SETUP_TITLES[what]), h('dd', {}, value)])),
      look.length
        ? h('div', { class: 'playback' }, h('p', { style: 'margin:0' }, look.length === 1 ? 'One thing still needs a look:' : 'A few things still need a look:'), h('div', { class: 'setup-checks' }, ...look.map(checkRow)))
        : h('p', { style: 'margin:0' }, !checks ? 'That’s everything.'
          : checks.some(c => c.state === 'wait') ? 'Everything StationPlay could check is working.' : 'Everything StationPlay checks is working.'),
      h('p', { class: 'hint', style: 'margin:0' }, why === 'new' ? `Choose Finish, then New station to make your first one. ${SETUP_AGAIN}` : SETUP_AGAIN)) };
  },
};
$('#noticeOk').addEventListener('click', () => $('#notice').close());
