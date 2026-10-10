// StationPlay's page: Broken files, replacing files with Sonarr and Radarr, and people's reports.
// Broken files -------------------------------------------------------------------
// Everything about files: people's reports and what StationPlay found, in
// three parts (see replacing.tab_section and reports.py on the server):
// what needs you, what Sonarr or Radarr is replacing, and the rest.
// What's wrong with a file on the Broken files tab, in a word.
const PROBLEMS = { broken: 'Broken', damaged: 'Damaged', unsupported: 'Unsupported' };
// Which of the files that need you are shown: all, broken or damaged ones, or missing ones.
let brokenShow = 'all';
let brokenRows = [];
let reportRows = [];
async function loadBroken() {
  let rows, got;
  try { [rows, got] = await Promise.all([api('/api/broken'), api('/api/reports')]); }
  catch (e) { toast(e.message, true); return; }
  brokenRows = rows;
  reportRows = got.reports;
  renderBroken();
}
// Where a file is used: the stations that have it now, each opening its
// editor, and Media in StationPlay's apps.
function usedLine(r) {
  const on = r.on?.length ? h('span', {}, 'On ',
    ...r.on.flatMap((st, n) => [n ? ', ' : '', h('button', { type: 'button', class: 'linkish', title: `Open ${st.name}’s settings`, onclick: () => {
      const ch = channels.find(c => c.id === st.id);
      if (ch) openEditor(ch); else toast('That station no longer exists', true);
    } }, `${st.number} ${st.name}`)])) : null;
  if (!on && !r.media) return h('div', { class: 'small muted' }, r.missing ? 'Not on any station, or in Media, now. It will come off this list at its next check.' : 'Not on any station, or in Media, now.');
  return h('div', { class: 'small on-stations' }, on, on && r.media ? ' · ' : '', r.media ? 'In Media' : '',
    r.missing && on && !r.media ? h('span', { class: 'muted' }, ' · Don’t want it anymore? Remove it from these stations, and it comes off this list.') : '');
}
const programName = p => p.show ? `${p.show} ${sxe(p)}` : p.year ? `${p.title} (${p.year})` : p.title;
// A place in a program: "12:34", "1:02:03".
const placeIn = ms => { const t = Math.max(0, Math.floor(ms / 1000)); const hh = Math.floor(t / 3600), mm = Math.floor(t / 60) % 60, ss = t % 60;
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`; };
function filesTable(rows) {
  return h('table', { class: 'broken' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Program'), h('th', {}, 'What’s wrong'), h('th', {}, 'When'), h('th', {}))),
    h('tbody', {}, ...rows));
}
// An entry on the list (what StationPlay found).
function entryRow(r) {
  const by = [...new Set((r.reports || []).map(x => `${x.who} (${x.label})`))];
  return h('tr', {},
    h('td', {},
      h('strong', {}, programName(r)),
      r.show ? h('div', {}, r.title) : null,
      r.file ? h('div', { class: 'path' }, r.file) : null,
      r.version ? h('div', { class: 'small muted' }, 'One of its versions, in Media (stations play another)') : null),
    h('td', { class: 'reason' },
      h('span', { class: r.missing ? 'chip plain' : r.problem === 'broken' || !PROBLEMS[r.problem] ? 'chip bad' : 'chip accent', style: 'margin-right:6px' },
        r.missing ? 'Missing' : PROBLEMS[r.problem] || 'Broken'),
      r.reason,
      h('div', { class: 'small muted' }, plural(r.failures, 'failure')
        + (r.lastChecked ? ` · rechecked ${new Date(r.lastChecked).toLocaleString()}` : '')),
      by.length ? h('div', { class: 'small' }, `Reported by ${by.join(', ')}`) : null,
      usedLine(r),
      r.replace && r.replace.state ? arrLine(r.replace) : null),
    h('td', { class: 'small', 'data-label': 'Last failed' }, new Date(r.lastFailed).toLocaleString()),
    h('td', {}, h('div', { class: 'row-btns' },
      h('button', { class: 'btn', title: 'The file is fine. Put this program back on the air.', onclick: () => retry(r) }, 'Retry'),
      arrButton(r))));
}
// A program people reported (see reports.py on the server): one row, each
// report under it.
const REPORT_STATES = {
  checking: ['chip plain', 'Being checked'],
  waiting: ['chip accent', 'Waiting for you'],
  nothing: ['chip plain', 'Nothing found'],
  kept: ['chip plain', 'Back on the air'],
  "couldn't": ['chip plain', 'Couldn’t be checked'],
};
function reportRow(row) {
  const p = row.program;
  const [chip, said] = REPORT_STATES[row.state] || ['chip plain', row.state];
  const replaceable = row.actions.includes('replace');
  return h('tr', {},
    h('td', {},
      h('strong', {}, programName(p)),
      p.show && p.title ? h('div', {}, p.title) : null),
    h('td', { class: 'reason' },
      h('span', { class: 'chip plain', style: 'margin-right:6px' }, row.reports.length > 1 ? `${row.reports.length} reports` : 'Reported'),
      h('span', { class: chip }, said),
      row.facts.length ? h('ul', { class: 'facts small' }, ...row.facts.map(f => h('li', {}, f))) : null,
      ...row.notes.map(n => h('div', { class: 'small', style: 'margin-top:6px' }, n)),
      replaceable && !row.arr ? h('div', { class: 'small muted', style: 'margin-top:6px' }, `To replace it from here, turn on ${row.app} under Replacing files with Sonarr and Radarr, with Broken or damaged (or Both) chosen.`) : null,
      h('ul', { class: 'said small' }, ...row.reports.map(reportLine)),
      usedLine(row)),
    h('td', { class: 'small', 'data-label': 'Reported' }, new Date(row.at).toLocaleString()),
    h('td', {}, h('div', { class: 'row-btns' }, ...reportButtons(row))));
}
// One person's report: what, who and where from, when, where in the
// program, and how it was playing.
function reportLine(x) {
  const how = x.how || {};
  const ways = how.station ? [`On station ${how.station}`]
    : [how.method && `Played ${how.method}`, how.version && `the ${how.version} version`, how.audio && `sound: ${how.audio}`, how.subtitle && `subtitles: ${how.subtitle}`].filter(Boolean);
  return h('li', {},
    h('div', { class: 'who' }, x.label),
    h('div', {}, [x.who, x.device, fmtClock(x.at), x.positionMs != null ? `${placeIn(x.positionMs)} in` : ''].filter(Boolean).join(' · ')),
    ways.length ? h('div', { class: 'how' }, `${ways.join(', ')}`.replace(/^./, c => c.toUpperCase())) : null);
}
function reportButtons(row) {
  const act = async (what, done) => {
    let got;
    try { got = await api(`/api/reports/${encodeURIComponent(row.key)}/${what}`, { method: 'POST' }); }
    catch (e) { toast(e.message, true); return; }
    toast(got.said || done);
    loadBroken(); loadStatus();
  };
  const out = [];
  if (row.actions.includes('replace') && row.arr) {
    out.push(h('button', { class: 'btn', title: `${row.arr} adds its release to its blocklist, removes the file, and fetches another. It’s off the air until then.`, onclick: () => act('replace') }, `Replace with ${row.arr}`));
    out.push(h('button', { class: 'btn', title: `${row.arr} searches for a better copy, and keeps this file until it finds one`, onclick: () => act('better') }, 'Find a better copy'));
  }
  out.push(h('button', { class: 'btn', title: 'Nothing more is done about it', onclick: () => act('dismiss', `Dismissed the ${row.reports.length > 1 ? 'reports' : 'report'} on ${programName(row.program)}`) }, 'Dismiss'));
  return out;
}
function renderBroken() {
  const rows = brokenRows, reports = reportRows;
  const empty = !rows.length && !reports.length;
  $('#filesEmpty').hidden = !empty;
  $('#filesEmpty').replaceChildren(...(empty ? [h('div', { class: 'panel files' }, h('div', { class: 'empty' },
    h('h3', {}, 'Nothing broken'),
    h('p', { class: 'muted' }, 'Every file has played cleanly so far, and no one has reported a problem. Use “Check files” on a station to test everything ahead of time.')))] : []));
  $('#needsPanel').hidden = empty;
  const needs = rows.filter(r => r.section === 'needs you');
  const going = rows.filter(r => r.section === 'being replaced');
  const found = rows.filter(r => !['needs you', 'being replaced'].includes(r.section));
  const count = needs.length + reports.filter(x => x.needs).length;
  $('#needsCount').hidden = !count;
  $('#needsCount').textContent = count;
  // (Files that need you, all of them or the missing ones or the rest.)
  const missing = needs.filter(r => r.missing).length;
  if (brokenShow !== 'all' && !needs.some(r => (brokenShow === 'missing') === Boolean(r.missing))) brokenShow = 'all';
  const shown = needs.filter(r => brokenShow === 'all' || (brokenShow === 'missing') === Boolean(r.missing));
  const pick = (value, label) => h('button', { type: 'button', 'aria-pressed': String(brokenShow === value), onclick: () => { brokenShow = value; renderBroken(); } }, label);
  $('#needsList').replaceChildren(...(!needs.length && !reports.length
    ? [h('p', { class: 'muted small none' }, 'Nothing needs you now.')]
    : [
        missing && missing < needs.length ? h('div', { class: 'broken-show' },
          h('div', { class: 'seg', role: 'group', 'aria-label': 'Show files' },
            pick('all', `All files (${needs.length})`),
            pick('broken', `Broken or damaged (${needs.length - missing})`),
            pick('missing', `Missing (${missing})`))) : '',
        filesTable([...reports.map(reportRow), ...shown.map(entryRow)]),
      ]));
  $('#replacingPanel').hidden = !going.length;
  $('#replacingCount').textContent = going.length;
  $('#replacingList').replaceChildren(...(going.length ? [filesTable(going.map(entryRow))] : []));
  $('#foundPanel').hidden = !found.length;
  $('#foundCount').textContent = found.length;
  $('#brokenPanel').replaceChildren(...(found.length ? [filesTable(found.map(entryRow))] : []));
}
// (A station changed from this tab: its programs are shown afresh.)
$('#editor').addEventListener('close', () => { if (currentTab === 'broken') loadBroken(); });
// Sonarr and Radarr: replacing files (optional; see replacing.py) -------------------------
const ARR = { sonarr: { name: 'Sonarr', what: 'episodes', port: 8989 }, radarr: { name: 'Radarr', what: 'movies', port: 7878 } };
const ARR_DONE = ['gave up', "can't", 'same', 'left'];
const ARR_WHAT = { broken: 'Broken or damaged', missing: 'Missing', both: 'Broken, damaged, and missing' };
const ARR_STATES = { searching: 'Replacing', downloading: 'Downloading', downloaded: 'Downloaded', 'gave up': 'Gave up', "can't": 'Can’t replace', same: 'Needs your review', left: 'You’re handling it' };
let arrShown = null;
// What Sonarr or Radarr is doing about an entry.
function arrLine(s) {
  const name = ARR[s.app]?.name || 'Sonarr or Radarr';
  const chip = s.state === 'left' ? 'chip plain' : ['gave up', "can't"].includes(s.state) ? 'chip bad' : 'chip accent';
  return h('div', { class: 'small arr-line' },
    h('span', { class: chip, style: 'margin-right:6px' }, `${name}: ${ARR_STATES[s.state] || 'Replacing'}`),
    s.note || '');
}
// What you can have Sonarr or Radarr do about an entry (see replacing.py):
// replace it (when they replace when you say so; or it was left to you), try
// again or another (they stopped), or leave it to you (they're at it, or
// about to be).
function arrButton(r) {
  const app = r.show ? 'sonarr' : 'radarr';
  const got = arrShown;
  if (!got?.apps?.[app]?.on || !['broken', 'damaged'].includes(r.problem)) return null;
  if (got.what !== 'both' && (got.what === 'missing') !== Boolean(r.missing)) return null;
  const name = ARR[app].name;
  const what = programName(r);
  const s = r.replace || {};
  const ask = (label, title, done) => h('button', { class: 'btn', title, onclick: async () => {
    try { await api(`/api/broken/${encodeURIComponent(r.key)}/replace`, { method: 'POST' }); }
    catch (e) { toast(e.message, true); return; }
    toast(done);
    setTimeout(loadBroken, 3000);
  } }, label);
  // (Not begun: when they replace only when you ask, or nothing plays it,
  // which they'd leave be.)
  if (s.state === 'left' || (!s.state && !s.asked && (got.when === 'ask' || r.section !== 'being replaced')))
    return ask(`Replace with ${name}`, `Have ${name} replace this file`, `${name} is replacing ${what}`);
  if (s.state === 'same')
    return ask('Try another file', `${name} adds this file to its blocklist too and looks for another one`, `${name} is looking for another file for ${what}`);
  if (ARR_DONE.includes(s.state))
    return ask('Try again', `Have ${name} try replacing this file again`, `${name} is trying to replace ${what} again`);
  return h('button', { class: 'btn', title: `${name} stops working on this file, and you take care of it yourself`, onclick: async () => {
    try { await api(`/api/broken/${encodeURIComponent(r.key)}/leave`, { method: 'POST' }); }
    catch (e) { toast(e.message, true); return; }
    toast(`You’re handling ${what}`);
    loadBroken();
  } }, 'I’ll handle it');
}
async function loadArr() {
  let got;
  try { got = await api('/api/arr'); } catch { return; }
  arrShown = got;
  const on = Object.entries(got.apps).filter(([, a]) => a.on).map(([k]) => ARR[k].name);
  $('#arrSum').textContent = on.length ? `${on.join(' and ')} ${on.length > 1 ? 'are' : 'is'} on, replacing ${ARR_WHAT[got.what].toLowerCase()} files ${got.when === 'auto' ? 'automatically' : 'only when you ask'}` : 'Off';
  const body = $('#arrBody');
  if (body.dataset.editing) return;  // (not while settings are being changed)
  const pick = value => h('button', { type: 'button', 'aria-pressed': String(got.what === value), onclick: async () => {
    try { await api('/api/arr/what', { method: 'PUT', body: { what: value } }); }
    catch (e) { toast(e.message, true); return; }
    toast(`Sonarr and Radarr will replace ${ARR_WHAT[value].toLowerCase()} files`);
    loadArr().then(loadBroken);
  } }, { broken: 'Broken or damaged', missing: 'Missing', both: 'Both' }[value]);
  const pickWhen = value => h('button', { type: 'button', 'aria-pressed': String(got.when === value), onclick: async () => {
    try { await api('/api/arr/when', { method: 'PUT', body: { when: value } }); }
    catch (e) { toast(e.message, true); return; }
    toast(value === 'auto' ? 'Sonarr and Radarr will replace files automatically' : 'Sonarr and Radarr will replace files only when you ask');
    loadArr().then(loadBroken);
  } }, { ask: 'Only when I ask', auto: 'Automatically' }[value]);
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'Optional. StationPlay can ask Sonarr (for episodes) and Radarr (for movies) to replace files on this list that a station plays, or Media in StationPlay’s apps:'),
    h('ul', {},
      h('li', {}, h('strong', {}, 'A broken or damaged file: '), 'First, its release is added to the app’s blocklist so the same file isn’t downloaded again. Then the file is deleted (into Sonarr’s or Radarr’s recycle bin, if you’ve set one up), and the app searches for another. This happens only if the app’s file is the exact file found broken and the app downloaded it. A file you added by hand can’t be blocklisted, so it’s left for you to handle.'),
      h('li', {}, h('strong', {}, 'A missing file '), '(gone from disk or from Plex while a station or Media still has it): the app first checks what’s on disk, then searches for it.')),
    h('div', { class: 'scan-set' }, h('strong', {}, 'Files to replace'),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'Files to replace' }, pick('broken'), pick('missing'), pick('both'))),
    h('div', { class: 'scan-set' }, h('strong', {}, 'When to replace'),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'When to replace' }, pickWhen('ask'), pickWhen('auto'))),
    h('p', { style: 'margin:0' }, got.when === 'auto'
      ? 'Automatically: each entry is replaced without asking you. Want to deal with one yourself? Choose I’ll handle it on its entry.'
      : 'Only when I ask: nothing is replaced until you choose Replace with Sonarr (or Radarr) on its entry. After that, the app keeps working on it by itself.'),
    h('p', { style: 'margin:0' }, 'Only what Sonarr and Radarr are monitoring gets replaced (in Sonarr, both the show and the episode). Unmonitor something there, and StationPlay leaves it alone too. Removed a show or movie on purpose? Unmonitor or delete it there (or choose Broken or damaged here), and remove it from its stations. Each entry on this list shows which stations have it, and whether it’s in Media. They also replace what people report, when you choose Replace on a report.'),
    h('p', { style: 'margin:0' }, 'Each entry gets up to 3 searches over about a day. If none finds a file that plays, the entry stays on this list and says so. A new file is checked like any other, and the program goes back on the air once it passes. If the new file has the same problem in the same places as the old one, the problem may be part of the program itself (such as an old movie’s effects), not a bad file. The entry then says Needs your review: choose Retry to put it back on the air, or Try another file. StationPlay itself only needs Plex; this just uses apps you already have. You’ll find each app’s API key under Settings → General.'),
    ...['sonarr', 'radarr'].map(app => arrRow(app, got.apps[app], got.status[app])));
}
function arrRow(app, a, st) {
  const meta = ARR[app];
  const on = h('input', { type: 'checkbox', checked: a.on });
  const url = h('input', { type: 'text', value: a.url, placeholder: `http://your-nas:${meta.port}`, 'aria-label': `${meta.name} address`, autocomplete: 'off', spellcheck: 'false' });
  const key = h('input', { type: 'password', placeholder: a.hasKey ? 'API key saved (type a new one to change it)' : 'API key', 'aria-label': `${meta.name} API key`, autocomplete: 'off' });
  const result = h('span', { class: 'hint', role: 'status' }, st && !st.ok ? `Last request failed: ${st.problem}` : '');
  const body = () => ({ app, url: url.value.trim(), key: key.value.trim() || null, on: on.checked });
  const editing = () => { $('#arrBody').dataset.editing = '1'; };
  for (const el of [on, url, key]) el.addEventListener('input', editing);
  const test = h('button', { type: 'button', class: 'btn', onclick: async () => {
    result.textContent = 'Testing…';
    try {
      const r = await api('/api/arr/test', { method: 'POST', body: body() });
      result.textContent = `Connected to ${r.name} ${r.version}.`;
    } catch (e) { result.textContent = e.message; }
  } }, 'Test');
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    try { await api('/api/arr', { method: 'PUT', body: body() }); }
    catch (e) { result.textContent = e.message; return; }
    toast(`Saved. ${meta.name} is ${on.checked ? 'on' : 'off'}.`);
    delete $('#arrBody').dataset.editing;
    loadArr(); loadBroken();
  } }, 'Save');
  return h('div', { class: 'arr-app' },
    h('label', {}, on, ` Use ${meta.name} for ${meta.what}`),
    h('div', { class: 'scan-set' }, url, key),
    h('div', { class: 'scan-set' }, test, save, result));
}
// People's reports from StationPlay's apps (see reports.py) ---------------------------
// What they do, and who may send them: the same setting, for each person,
// as Can report problems on the Access tab.
async function loadReportSettings() {
  let users = [];
  if (me.required) { try { users = await api('/api/access/users'); } catch { users = []; } }
  const people = users.filter(u => u.role !== 'admin');
  const off = people.filter(u => !u.canReport);
  $('#reportsSum').textContent = !me.required ? 'Anyone at home can report problems'
    : off.length ? `${off.map(u => u.name).join(', ')} can’t report problems` : 'Everyone can report problems';
  const choice = u => h('label', { class: 'own-password' },
    h('input', { type: 'checkbox', checked: u.canReport, onchange: async e => {
      const on = e.target.checked;
      try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { canReport: on } }); toast(on ? `${u.name} can report problems` : `${u.name} can’t report problems now`); }
      catch (err) { toast(err.message, true); }
      loadReportSettings();
    } }), u.name);
  $('#reportsBody').replaceChildren(
    h('p', { style: 'margin:0' }, 'People can report a problem from StationPlay’s apps: from a movie’s or an episode’s page, from the player’s menu, and from a station’s player. They pick what’s wrong from a list. Each report comes here, under Needs you, saying who sent it, from which device, where in the program, and how it was playing.'),
    h('ul', {},
      h('li', {}, h('strong', {}, 'What StationPlay can check '), '(no picture, the picture breaking up, no sound, the sound cutting out, stopping early, not playing): its file is checked at once, where it happened first. If StationPlay finds the problem, the file goes on this list, and is replaced as you have that set. If not, the report says so, for you to dismiss.'),
      h('li', {}, h('strong', {}, 'What only a person can judge '), '(the sound out of sync, the wrong language, the wrong episode or movie, poor picture quality, subtitles): it waits for you, with what StationPlay can tell beside it. Choose Replace (Sonarr or Radarr adds its release to the blocklist and fetches another), Find a better copy (they search for an upgrade, keeping the file until they find one), or Dismiss.'),
      h('li', {}, h('strong', {}, 'Wrong title, details or artwork: '), 'fix it in Plex, then dismiss it.')),
    h('p', { style: 'margin:0' }, 'A report never takes anything off the air, or out of Media, by itself. Each person can send one report a day about each program, and ten a day in all. Admins are told through their alerts, at most once an hour.'),
    !me.required
      ? h('p', { class: 'muted', style: 'margin:0' }, 'While signing in is off, anyone at home can report problems. Turn signing in on to choose who can.')
      : h('div', { class: 'scan-set report-who' }, h('strong', {}, 'Can report problems'),
          ...(people.length ? people.map(choice) : [h('span', { class: 'muted' }, 'Admins always can. Add people on the Access tab.')])));
}
