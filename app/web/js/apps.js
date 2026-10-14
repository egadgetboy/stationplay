// On the Access tab: Tuner access, stations kept from Plex users, the apps away from home, how many can watch at once, and Media in the apps.
// Stations kept from some Plex users (Access tab; see limits.py) ---------------------
let limitsShown = null;
async function loadLimits() {
  let got;
  try { got = await api('/api/plex-limits'); }
  catch (e) { $('#limitsSum').textContent = ''; $('#limitsBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  limitsShown = got;
  const kept = got.users.filter(u => u.kept.length);
  $('#limitsSum').textContent = !got.on ? 'Off'
    : kept.length ? `On: ${kept.map(u => u.name).join(', ')}` : 'On, but no stations are blocked for anyone yet';
  const body = $('#limitsBody');
  if (body.dataset.editing) return;  // (not while it's being changed)
  renderLimits(got);
}
function renderLimits(got) {
  const body = $('#limitsBody');
  const pass = got.plexPass === true ? 'Plex reports that your server has it.'
    : got.plexPass === false ? 'Plex reports that your server doesn’t have it, so tapiOca can’t stop anyone from watching.' : '';
  const on = h('input', { type: 'checkbox', checked: got.on });
  const editing = () => { body.dataset.editing = '1'; };
  on.addEventListener('input', editing);
  const picks = new Map();  // Plex user's id -> {name, boxes: Map(station id -> checkbox)}
  const users = got.users.map(u => {
    const boxes = new Map();
    const count = h('span', { class: 'muted' });
    const recount = () => {
      const n = [...boxes.values()].filter(b => b.checked).length;
      count.textContent = n ? `${plural(n, 'station')} blocked` : 'no stations blocked';
    };
    const grid = h('div', { class: 'limit-stations' }, ...got.stations.map(st => {
      const box = h('input', { type: 'checkbox', checked: u.kept.includes(st.id) });
      box.addEventListener('input', () => { editing(); recount(); });
      boxes.set(st.id, box);
      return h('label', { title: `${st.number} ${st.name}` }, box, h('span', {}, `${st.number} ${st.name}`));
    }));
    recount();
    picks.set(u.id, { name: u.name, boxes });
    return h('details', { class: 'limit-user' },
      h('summary', {}, h('strong', {}, u.name), u.owner ? h('span', { class: 'chip' }, 'server owner') : '', count), grid);
  });
  const result = h('span', { class: 'hint', role: 'status' });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    const kept = {}, names = {};
    for (const [id, p] of picks) {
      const chosen = [...p.boxes].filter(([, b]) => b.checked).map(([cid]) => cid);
      if (chosen.length) { kept[id] = chosen; names[id] = p.name; }
    }
    try { await api('/api/plex-limits', { method: 'PUT', body: { on: on.checked, kept, names } }); }
    catch (e) { result.textContent = e.message; return; }
    toast(on.checked ? 'Saved. Stations are now blocked for the Plex users you chose.' : 'Saved. Blocking is off.');
    delete body.dataset.editing;
    loadLimits();
  } }, 'Save');
  const stops = got.stops.map(x => h('li', {}, `${x.name}, station ${x.station}, ${new Date(x.atMs).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}`));
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'Plex can’t hide a station from one person: every station appears in the guide for everyone with Live TV on your Plex server. With this on, tapiOca watches what Plex is playing. When Plex users tune in to a station blocked for them, Plex stops it within seconds and shows the message “This station isn’t available on your Plex account.” (if their Plex app shows messages). If they tune in again, it’s stopped again.'),
    h('div', { class: 'limit-note' }, h('strong', {}, 'Requirements'),
      h('ul', {},
        h('li', {}, h('strong', {}, 'Plex Pass'), ' on the account that owns your Plex server. Stopping playback is a Plex Pass feature. ', pass),
        h('li', {}, h('strong', {}, 'Watching in Plex. '), 'Anyone watching in a Plex app is covered: you, your Plex Home members (including managed users), and friends you’ve shared Live TV with. Apps that use the playlist (M3U) aren’t covered.'),
        h('li', {}, h('strong', {}, 'A Plex user for each person. '), 'Everyone using the same Plex account counts as one user. To block a station for your kids, they need their own Plex Home user.'),
        h('li', {}, 'tapiOca stops a stream only when it’s sure which station it is. If two stations air the exact same program at the same time, tapiOca can’t tell them apart, so it doesn’t stop either one.'))),
    h('label', {}, on, ' Stop Plex users from watching stations blocked for them'),
    ...(got.plexProblem ? [h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', got.plexProblem)] : []),
    ...(got.problem ? [h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', got.problem)] : []),
    ...(users.length ? users : [h('p', { class: 'muted small', style: 'margin:0' }, got.plexProblem ? '' : 'Plex doesn’t list any users.')]),
    h('div', { class: 'scan-set' }, save, result),
    ...(stops.length ? [h('div', {}, h('strong', {}, 'Recently stopped'), h('ul', {}, ...stops))] : []));
}
// Tuner access (Access tab; see tuner.py) ----------------------------------------------
// Which devices may use the tuner (what Plex, Jellyfin and other apps use), and
// who did lately. Each change sends the whole of it, and what tapiOca
// answers is shown. Only these devices with none listed would shut everything
// out, so choosing it then saves nothing until a device is listed.
const TUNER_NONE = 'List at least one device, or choose Plex server only.';
let tunerOnlyChosen = false;  // (Only these devices chosen, with none listed: not saved yet)
let tunerTyped = { address: '', name: '' };  // (the add row's boxes, kept when it's shown again)
async function loadTuner() {
  let got;
  try { got = await api('/api/tuner'); }
  catch (e) { $('#tunerSum').textContent = ''; $('#tunerBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  renderTuner(got);
}
// `said`: what to show beside the controls (why a change wasn't made).
function renderTuner(got, said = '') {
  const nets = got.networks || [];  // (networks, such as 192.168.1.0/24: 1.36.0)
  const listedCount = got.devices.length + nets.length;
  if (got.only || listedCount) tunerOnlyChosen = false;
  const only = got.only || tunerOnlyChosen;
  if (only && !listedCount && !said) said = TUNER_NONE;
  $('#tunerSum').textContent = !got.only ? 'Any device on my home network'
    : nets.length ? `Only ${plural(got.devices.length, 'device')} and ${plural(nets.length, 'network')}` : `Only ${plural(got.devices.length, 'device')}`;
  const result = h('span', { class: 'hint', role: 'status' }, said);
  // Saves, then shows what's answered; or shows why not, with what was saved.
  const send = async (path, opts, done, clearTyped = false) => {
    let now;
    try { now = await api(path, opts); }
    catch (e) { renderTuner(got, e.message); return; }
    if (clearTyped) tunerTyped = { address: '', name: '' };
    tunerOnlyChosen = false;
    renderTuner(now);
    toast(done);
  };
  const put = (onlyThese, devices, done, clearTyped = false) =>
    send('/api/tuner', { method: 'PUT', body: { only: onlyThese, devices } }, done, clearTyped);
  // (Networks, such as 192.168.1.0/24: sent only when they change.)
  const putNets = (networks, done, clearTyped = false) =>
    send('/api/tuner', { method: 'PUT', body: { only: true, devices: got.devices, networks } }, done, clearTyped);
  const choice = (value, label, hint) => h('label', { class: 'choice' },
    h('input', { type: 'radio', name: 'tunerOnly', value, checked: only === (value === 'only'), onchange: () => {
      if (value === 'only') {
        if (got.devices.length) put(true, got.devices, 'Saved. Only the devices listed can use the tuner.');
        else if (nets.length) putNets(nets, 'Saved. Only the networks listed can use the tuner.');
        else { tunerOnlyChosen = true; renderTuner(got); }
      } else if (got.only) put(false, got.devices, 'Saved. Any device on your home network can use the tuner.');
      else { tunerOnlyChosen = false; renderTuner(got); }
    } }),
    h('span', { style: 'display:grid;gap:2px' }, h('strong', {}, label), hint ? h('span', { class: 'hint' }, hint) : null));
  const named = d => d.name || d.address;
  const listed = [];
  if (only) {
    const remove = d => {
      if (d.network) {
        if (listedCount === 1) { result.textContent = TUNER_NONE; return; }
        putNets(nets.filter(x => x.network !== d.network), `${d.name || d.network} is off the list`);
        return;
      }
      if (!nets.length) {
        if (got.devices.length === 1) { result.textContent = TUNER_NONE; return; }
      }
      put(true, got.devices.filter(x => x.address !== d.address), `${named(d)} is off the list`);
    };
    const address = h('input', { type: 'text', id: 'tunerAddress', value: tunerTyped.address, placeholder: '192.168.1.20', maxlength: 60, required: true,
      autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false', oninput: () => { tunerTyped.address = address.value; } });
    const name = h('input', { type: 'text', id: 'tunerName', value: tunerTyped.name, placeholder: 'Living room TV', maxlength: 60, autocomplete: 'off',
      oninput: () => { tunerTyped.name = name.value; } });
    const add = h('form', { class: 'adduser', onsubmit: e => {
      e.preventDefault();
      const typed = address.value.trim();
      // (With a slash, a whole network: 192.168.1.0/24.)
      if (typed.includes('/')) {
        const n = { network: typed, name: name.value.trim() };
        putNets([...nets, n], `${n.name || n.network} is on the list`, true);
        return;
      }
      const d = { address: typed, name: name.value.trim() };
      put(true, [...got.devices, d], `${named(d)} is on the list`, true);
    } },
      h('div', { class: 'field' }, h('label', { for: 'tunerAddress' }, 'Device’s IP address, or a network'), address),
      h('div', { class: 'field' }, h('label', { for: 'tunerName' }, 'Name (optional)'), name),
      h('button', { type: 'submit', class: 'btn primary' }, 'Add'));
    // (It asks first, naming the addresses it would list: anything can call
    // itself Plex, so the Admin sees which they are.)
    const plexOnly = h('button', { type: 'button', class: 'btn', onclick: () => {
      if (got.plex.length) {
        const others = got.devices.filter(d => !got.plex.includes(d.address));
        const where = got.plex.length === 1 ? `Plex’s address, ${got.plex[0]}` : `Plex’s addresses, ${got.plex.join(', ')}`;
        const gone = [others.length ? plural(others.length, 'other device') : '', nets.length ? plural(nets.length, 'network') : ''].filter(Boolean);
        const lose = gone.length ? ` ${gone.join(' and ')} can’t use the tuner then.` : '';
        if (!confirm(`Plex server only lists just ${where}.${lose} Go ahead?`)) return;
      }
      send('/api/tuner/plex-only', { method: 'POST' }, 'Saved. Only Plex can use the tuner.');
    } }, 'Plex server only');
    // (Where Plex is used, or has been seen using the tuner.)
    plexOnly.hidden = !got.plex.length && !plexUsed();
    listed.push(
      listedCount ? h('table', { class: 'users' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Device or network'), h('th', {}, 'Address'), h('th', {}, ''))),
        h('tbody', {}, ...[...got.devices, ...nets].map(d => h('tr', {},
          h('td', {}, h('strong', {}, d.network ? d.name || 'A network' : named(d))),
          h('td', { class: 'small', 'data-label': 'Address' }, d.network || d.address),
          h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: () => remove(d) }, 'Remove'))))))
        : h('p', { class: 'muted small', style: 'margin:0' }, 'No devices or networks are listed yet.'),
      add,
      h('p', { class: 'hint', style: 'margin:0' }, 'A whole network, entered as 192.168.1.0/24, lists every device on it. Home addresses only.'),
      h('div', { class: 'scan-set' }, plexOnly, result));
  }
  const allow = r => send('/api/tuner/allow', { method: 'POST', body: { address: r.address } }, `${r.name || r.address} is on the list`);
  const recent = got.recent.length ? h('table', { class: 'users' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Device'), h('th', {}, 'Address'), h('th', {}, 'Asked for'), h('th', {}, 'When'), h('th', {}, ''))),
    h('tbody', {}, ...got.recent.map(r => h('tr', {},
      h('td', {}, h('strong', {}, r.name || 'Unknown device'), r.refused ? [' ', h('span', { class: 'chip bad' }, 'Refused')] : null),
      h('td', { class: 'small', 'data-label': 'Address' }, r.address),
      h('td', { class: 'small', 'data-label': 'Asked for' }, r.asked),
      h('td', { class: 'small', 'data-label': 'When' }, ago(r.lastMs)),
      h('td', {}, r.listed ? h('span', { class: 'muted small' }, 'On the list')
        : h('button', { class: 'btn', type: 'button', onclick: () => allow(r) }, 'Allow'))))))
    : h('p', { class: 'muted small', style: 'margin:0' }, 'No device has used the tuner in the last 7 days.');
  $('#tunerBody').replaceChildren(
    h('p', { style: 'margin:0' }, 'The tuner is what Plex, Jellyfin and other apps use: the tuner itself, the guide, the list of stations and the stations’ streams. These apps can’t sign in.'),
    h('div', { class: 'checks-col', style: 'margin:0', role: 'radiogroup', 'aria-label': 'Who can use the tuner' },
      choice('any', 'Any device on my home network', ''),
      choice('only', 'Only these devices', 'tapiOca’s own apps, signed in, never need listing.')),
    // (With sign-in off, anyone at home can open this page and change it.)
    ...(only && !me.required ? [h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ',
      'Sign-in is off, so anyone on your home network can open this page and change who can use the tuner. Add a user, above, to turn sign-in on.')] : []),
    ...(got.warning ? [h('div', { class: 'reach down' },
      h('span', { class: 'icon down', 'aria-hidden': 'true' }, reachIcon('down')),
      h('p', { class: 'what' }, got.warning))] : []),
    ...(only ? listed : said ? [result] : []),
    h('div', { class: 'scan-set' }, h('strong', {}, 'Recent tuner connections'),
      h('button', { type: 'button', class: 'btn', onclick: loadTuner }, 'Refresh')),
    recent);
}
// tapiOca's apps away from home --------------------------------------------------
// Watching away from home: its settings, in its panel on the Access tab and
// in the setup (`id`: the address box's, for its label). `note` shows (or
// clears) what's wrong with the saved address: a port it can't have.
// `turnOn`: with sign-in off, how to turn it on: a sentence, or (in the
// setup) what its button does.
function awayFields(got, onEdit, id, { turnOn = ' Add the first user, above, to turn it on.' } = {}) {
  const on = h('input', { type: 'checkbox', checked: got.on, oninput: onEdit });
  const address = h('input', { type: 'url', id, value: got.address, placeholder: 'https://tv.example.com (no port)', maxlength: 200, autocomplete: 'off', 'aria-describedby': `${id}Hint`, oninput: onEdit, style: 'width:min(100%,360px)' });
  const portNote = h('p', { class: 'small', style: 'margin:0' });
  const note = problem => {
    portNote.hidden = !problem;
    portNote.replaceChildren(...(problem ? [warnIcon(), ' ', problem] : []));
  };
  note(got.on && got.portProblem);
  address.addEventListener('input', () => note(''));  // (it's about the address saved)
  const notes = [];
  if (!got.publicPort) notes.push(h('p', { class: 'small', style: 'margin:0' }, 'PUBLIC_PORT isn’t set, so apps can reach tapiOca from outside only through a VPN.'));
  // (Sign-in off: the step left to take, said as one, never as a warning.
  // The owner, October 14: "This seems to be process not error.")
  if (!me.required) {
    const button = typeof turnOn === 'function' ? h('button', { type: 'button', class: 'btn', onclick: turnOn }, 'Turn on sign-in') : null;
    notes.push(h('div', { class: 'step-note' },
      h('span', { class: 'icon', 'aria-hidden': 'true' }, reachIcon('next-step')),
      h('p', {}, h('strong', {}, 'Next step: turn on sign-in. '), 'Apps sign in when they’re away from home.', button ? '' : turnOn),
      button));
  }
  return {
    nodes: [
      h('p', { style: 'margin:0' }, 'With this on, tapiOca’s own apps can watch your stations away from home, and Media if you share it, as they do at home. Plex, Jellyfin and other apps don’t change: they use tapiOca on your home network only.'),
      h('div', { class: 'limit-note' }, h('strong', {}, 'What it takes'),
        h('ul', {},
          h('li', {}, h('strong', {}, 'A way in from outside. '), 'Either a VPN such as Tailscale or WireGuard on the phone or tablet (then the address below is your server’s VPN address, such as http://nas.your-tailnet.ts.net:3310), or the public port (PUBLIC_PORT) behind a reverse proxy with HTTPS. Not a Cloudflare Tunnel: Cloudflare’s free plan isn’t meant for video. The README’s “Reaching tapiOca from outside your home” explains each.'),
          h('li', {}, h('strong', {}, 'Signing in, through the public port. '), 'Each app that signs in gets a private address for its stations, and one for each title it plays from Media. They stop working as soon as that person signs out or is removed.'),
          h('li', {}, h('strong', {}, 'Upload speed. '), 'Each station watched away from home is sent over your home internet connection, at the picture size set under Picture and tuners on the Setup tab, and so is Media, at the quality you choose on the Access tab.'))),
      ...notes,
      h('label', {}, on, ' Let tapiOca’s apps watch away from home'),
      h('div', { class: 'field' }, h('label', { for: id }, 'The address apps reach tapiOca at from outside'), address,
        h('span', { class: 'hint', id: `${id}Hint` }, 'With a reverse proxy, its https:// address alone, with no port. With a VPN, the server’s VPN address with its port, such as http://nas.your-tailnet.ts.net:3310.'),
        portNote),
    ],
    values: () => ({ on: on.checked, address: address.value }),
    note,
  };
}
// Whether tapiOca's apps can reach it from outside (see reach.py on the
// server), for Admins while watching away from home is on: the pill in the
// header, the panel's summary, and the status on the Access tab and in the
// setup. Painted again whenever it's said anew: with the page's status
// (every 10 seconds), from the Access tab, and by Check now.
let awayNow = null;  // {on, address, reach} as last said ({on: false}: off)
const REACH_WORDS = { up: 'Up', down: 'Down', checking: 'Checking', 'cant-check': 'Can’t check', 'next-step': 'One step left' };
const lowerFirst = text => text.charAt(0).toLowerCase() + text.slice(1);
// `got`: /api/away's answer, or the status's `away` (null or missing: off,
// or not for this person).
function setAway(got) {
  awayNow = got?.on ? { on: true, address: got.address, reach: got.reach } : { on: false };
  paintAway();
}
// "On, at https://… · Ready" (or the problem, in a few words), or "Off".
const awaySummary = (away, ready = 'Ready') => !away?.on ? 'Off'
  : `On, at ${away.address} · ${away.reach.state === 'up' && away.reach.short === 'Ready' ? ready : away.reach.short}`;
function paintAway() {
  const pill = $('#awayPill');
  const reach = awayNow?.on && isAdmin() ? awayNow.reach : null;
  pill.hidden = !reach;
  if (reach) {
    const word = REACH_WORDS[reach.state] || REACH_WORDS.checking;
    pill.querySelector('.dot').className = `dot ${{ up: 'ok', down: 'bad', checking: 'accent', 'next-step': 'accent' }[reach.state] || ''}`;
    pill.querySelector('.word').className = `word ${reach.state}`;
    pill.querySelector('.word').textContent = word;
    pill.setAttribute('aria-label', `Away from home: ${word}`);
    pill.title = reach.detail;
  }
  document.querySelectorAll('[data-away-sum]').forEach(el => { el.textContent = awaySummary(awayNow, el.dataset.awaySum || 'Ready'); });
  document.querySelectorAll('.reach').forEach(box => box.paint?.());
}
$('#awayPill').addEventListener('click', () => {
  showTab('access');
  const panel = $('#awayPanel');
  panel.open = true;
  panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
});
// Admin alerts (see alerts.py on the server): what tapiOca finds wrong
// now, as the page's status says them (for Admins only), in a pill in the
// header that opens a list of them.
let alertsNow = [];
function setAlerts(list) {
  alertsNow = isAdmin() && Array.isArray(list) ? list : [];
  const pill = $('#alertsPill');
  pill.hidden = !alertsNow.length;
  pill.querySelector('.count').textContent = plural(alertsNow.length, 'alert');
  pill.title = alertsNow.map(a => a.sentence).join('\n');
  if ($('#alertsDlg').open) paintAlerts();
}
function paintAlerts() {
  $('#alertsBody').replaceChildren(...(alertsNow.length
    ? alertsNow.map(a => h('div', { class: 'alert-item' },
        h('span', { class: 'icon', 'aria-hidden': 'true' }, warnIcon()),
        h('div', {}, h('p', {}, a.sentence), h('p', { class: 'when' }, `Since ${fmtClock(a.since)}, ${ago(a.since)}`),
          // (What needs you on the Broken files tab: a way there.)
          a.kind === 'files' ? h('button', { class: 'linkish', type: 'button', onclick: () => { $('#alertsDlg').close(); showTab('broken'); } }, 'Open the Broken files tab')
          // (Commercials or trailers to rate: the Viewing Levels panel, open.)
          : a.kind === 'clips' ? h('button', { class: 'linkish', type: 'button', onclick: () => {
              $('#alertsDlg').close();
              showTab('access');
              $('#viewingPanel').open = true;
              $('#viewingPanel').scrollIntoView({ block: 'start' });
            } }, 'Open the Access tab') : null)))
    : [h('p', { class: 'muted', style: 'margin:0' }, 'Nothing needs a look now. Each alert that’s fixed is in the Logs tab.')]));
}
$('#alertsPill').addEventListener('click', () => { paintAlerts(); $('#alertsDlg').showModal(); });
$('#closeAlerts').addEventListener('click', () => $('#alertsDlg').close());
$('#alertsDone').addEventListener('click', () => $('#alertsDlg').close());
$('#alertsNotify').addEventListener('click', () => {
  $('#alertsDlg').close();
  showTab('logs');
  const panel = $('#notifyPanel');
  panel.open = true;
  panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
});
// Alert notifications to web addresses (see notify.py on the server), on the Logs tab.
const NOTIFY_FORMATS = { text: 'plain text', json: 'JSON', discord: 'Discord', slack: 'Slack' };
const NOTIFY_MOST = 3;
// (A Discord webhook's address always gets Discord's format, and one on
// hooks.slack.com Slack's, as on the server: see notify.py.)
const isDiscord = url => { try { const u = new URL(url.trim()); return /^(?:(?:ptb|canary)\.)?discord(?:app)?\.com$/i.test(u.hostname) && /^\/api\/(?:v\d+\/)?webhooks\//.test(u.pathname); } catch { return false; } };
const isSlack = url => { try { return new URL(url.trim()).hostname.toLowerCase() === 'hooks.slack.com'; } catch { return false; } };
const siteOf = url => { try { return new URL(url).host; } catch { return url; } };
const notifyLast = sent => sent
  ? `Last sent ${ago(sent.at)}${sent.test ? ' (a test)' : ''}: ${sent.ok ? sent.status : `it didn’t go through (${sent.status})`}.`
  : 'Nothing sent yet.';
async function loadNotify() {
  let got;
  try { got = await api('/api/notify'); }
  catch (e) { $('#notifySum').textContent = ''; $('#notifyBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  const saved = [...(got.url ? [{ url: got.url, format: got.format, last: got.last }] : []), ...(got.more || [])];
  $('#notifySum').textContent = !got.on ? 'Off'
    : saved.length > 1 ? `On, to ${saved.length} addresses: ${saved.map(a => siteOf(a.url)).join(', ')}`
    : `On, to ${siteOf(got.url)}, as ${NOTIFY_FORMATS[got.format]}`;
  const body = $('#notifyBody');
  if (body.dataset.editing) return;  // (not while it's being changed)
  const edit = () => { body.dataset.editing = '1'; };
  // Each address on the page: what's typed, its format, and how its last message went.
  const rows = saved.length ? saved.map(a => ({ ...a })) : [{ url: '', format: got.format, last: got.last }];
  const on = h('input', { type: 'checkbox', checked: got.on, oninput: edit });
  const list = h('div', { style: 'display:grid;gap:12px' });
  const add = h('button', { type: 'button', class: 'btn', style: 'justify-self:start', onclick: () => {
    if (rows.length >= NOTIFY_MOST) return;
    rows.push({ url: '', format: 'text', last: null });
    edit();
    paint();
    list.lastElementChild?.querySelector('input')?.focus();
  } }, 'Add an address');
  const row = (r, n) => {
    const many = rows.length > 1;
    const name = many ? `Web address ${n + 1}` : 'Web address';
    const id = n ? `notifyUrl${n + 1}` : 'notifyUrl';
    const format = h('select', { id: n ? `notifyFormat${n + 1}` : 'notifyFormat', 'aria-label': `Format for ${name.toLowerCase()}`, 'aria-describedby': 'notifyFormatHint',
      style: 'flex:1 0 auto;width:auto', onchange: () => { edit(); r.format = format.value; } },
      h('option', { value: 'text' }, 'ntfy or plain text'), h('option', { value: 'json' }, 'JSON (Gotify, Home Assistant and others)'),
      h('option', { value: 'discord' }, 'Discord'), h('option', { value: 'slack' }, 'Slack'));
    format.value = r.format;
    const url = h('input', { type: 'url', id, value: r.url, placeholder: 'https://ntfy.sh/your-topic', maxlength: 500, autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'notifyUrlHint',
      style: 'flex:1000 1 260px;min-width:0', oninput: () => {
        edit();
        r.url = url.value;
        if (isDiscord(url.value)) format.value = 'discord';
        else if (isSlack(url.value)) format.value = 'slack';
        r.format = format.value;
      } });
    const result = h('span', { class: 'hint', role: 'status' });
    const last = h('p', { class: 'muted small', style: 'margin:0' }, notifyLast(r.last));
    const test = h('button', { type: 'button', class: 'btn', onclick: async () => {
      test.disabled = true;
      test.textContent = 'Sending…';
      result.textContent = '';
      try {
        const tried = await api('/api/notify/test', { method: 'POST', body: { url: url.value, format: format.value, which: n } });
        r.last = tried.sent;
        last.textContent = notifyLast(tried.sent);
        result.textContent = tried.sent.ok ? 'Sent. Check that it arrived.' : `It didn’t go through: ${tried.sent.status}.`;
      } catch (e) {
        result.textContent = e.message;
      } finally {
        test.disabled = false;
        test.textContent = 'Send a test';
      }
    } }, 'Send a test');
    const remove = many ? h('button', { type: 'button', class: 'btn ghost', 'aria-label': `Remove ${name.toLowerCase()}`, onclick: () => {
      rows.splice(n, 1);
      edit();
      paint();
    } }, 'Remove') : null;
    return h('div', { class: 'arr-app' },
      h('div', { class: 'field' }, h('label', { for: id }, name), h('div', { class: 'scan-set' }, url, format)),
      h('div', { class: 'scan-set' }, test, remove, result),
      last);
  };
  const paint = () => {
    list.replaceChildren(...rows.map(row));
    add.hidden = rows.length >= NOTIFY_MOST;
  };
  paint();
  const result = h('span', { class: 'hint', role: 'status' });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    result.textContent = '';
    const [first, ...more] = rows;
    try { await api('/api/notify', { method: 'PUT', body: { on: on.checked, url: first.url, format: first.format, more: more.map(r => ({ url: r.url, format: r.format })) } }); }
    catch (e) { result.textContent = e.message; return; }
    const to = rows.filter(r => r.url.trim()).length > 1 ? 'those addresses' : 'that address';
    toast(on.checked ? `Saved. Alerts will be sent to ${to}.` : 'Saved. Alerts aren’t sent anywhere.');
    delete body.dataset.editing;
    loadNotify();
  } }, 'Save');
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'tapiOca says when something needs a look: Plex can’t be reached, the data folder is nearly full or can’t be written to, a station keeps failing to start, backups fail, the clock is badly off, or tapiOca’s apps can’t reach it from outside. Each alert shows in the header and in the log below, once when it starts and again when it’s fixed. With this on, tapiOca also sends each one to up to 3 web addresses of yours, such as an ntfy topic on your phone, Gotify, a Home Assistant webhook, or a Discord or Slack webhook.'),
    h('label', {}, on, ' Send each alert to the addresses below when it starts and when it’s fixed'),
    list,
    add,
    h('p', { class: 'hint', id: 'notifyUrlHint', style: 'margin:0' }, 'Each alert goes to every address. One that fails doesn’t hold up the others. Only Admins see the addresses, and the log shows only their sites, as an address can carry a token. tapiOca waits 5 seconds for an answer, tries once more, and follows no redirects.'),
    h('p', { class: 'hint', id: 'notifyFormatHint', style: 'margin:0' }, 'The ntfy or plain text format sends the alert as it is, titled tapiOca. JSON sends its title, message, kind, and state (started or fixed). Discord and Slack post it as a chat message. A Discord or Slack webhook’s address always uses its own format. Mattermost and Rocket.Chat take Slack’s format too.'),
    h('div', { class: 'scan-set' }, save, result));
}
function reachIcon(state) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.innerHTML = {
    up: '<circle cx="8" cy="8" r="7.5" fill="currentColor"/><path d="M4.7 8.2l2.2 2.2 4.4-4.6" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    down: '<path d="M8 1.2L15.3 14.6H.7z" fill="currentColor"/><path d="M8 6v4" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="12.3" r=".9" fill="#fff"/>',
    checking: '<circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="28 12.2" stroke-linecap="round"/>',
    'cant-check': '<circle cx="8" cy="8" r="6.9" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6.1 6.3a1.95 1.95 0 1 1 2.7 1.8c-.5.2-.8.6-.8 1.1v.3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="11.7" r=".9" fill="currentColor"/>',
    // (A step left to take: an arrow on, never a warning.)
    'next-step': '<circle cx="8" cy="8" r="7.5" fill="currentColor"/><path d="M4.6 8h6.2M8.4 5.2L11.2 8l-2.8 2.8" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
  }[state] || '';
  return svg;
}
// What Trust this proxy does, under its button (1.36.1).
function trustProxyWords(offer) {
  return offer.relay
    ? `${offer.address} is Docker’s address on this server. Your reverse proxy in another container reaches tapiOca through it, and so do Plex and your other apps, which keep working. Trust it only if your proxy runs in a container on this server.`
    : `This lists ${offer.address} under Trusted proxies, on the Access tab. tapiOca then believes what it says about each visitor: who they are, and that they came over HTTPS. Plex, or anything else on that computer, keeps working as before. Trust it only if it’s your reverse proxy.`;
}
// The status: an icon and what it is, when it was checked (and when an app
// last came in from outside, for an https:// address), and Check now.
// `save`: what Check now saves first (a sentence if that didn't work);
// `shown`: whether it's shown while what's saved is off (Check now saving it).
function reachStatus({ save = null, shown = () => false } = {}) {
  const icon = h('span', { class: 'icon', 'aria-hidden': 'true' });
  const what = h('p', { class: 'what', role: 'status' });
  const when = h('p', { class: 'when' });
  const check = h('button', { type: 'button', class: 'btn', onclick: async () => {
    check.disabled = true;
    check.textContent = 'Checking…';
    try {
      const problem = save ? await save() : null;
      if (problem) { toast(problem, true); return; }
      if (!awayNow?.on) return;
      const reach = await api('/api/away/check', { method: 'POST' });
      if (awayNow?.on) { awayNow.reach = reach; paintAway(); }
    } catch (e) {
      toast(e.message, true);
    } finally {
      check.disabled = false;
      check.textContent = 'Check now';
    }
  } }, 'Check now');
  // (1.36.1) A reverse proxy the check came through that isn't trusted
  // yet: trusted right here, in the setup too, not on another tab.
  const trustWhy = h('p', { class: 'hint', style: 'margin:4px 0 0' });
  const trust = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    trust.disabled = check.disabled = true;
    trust.textContent = 'Trusting…';
    try {
      // (The address shown: one found since isn't trusted unseen.)
      const reach = await api('/api/away/trust-proxy', { method: 'POST', body: { address: awayNow?.reach?.trustProxy?.address || '' } });
      if (awayNow?.on) { awayNow.reach = reach; paintAway(); }
      toast(reach.state === 'up' ? 'Trusted. Apps can reach tapiOca from outside now.' : 'Trusted. tapiOca checked again: see what it found.');
      if (typeof loadTrusted === 'function' && $('#trustedPanel')) loadTrusted();
    } catch (e) {
      toast(e.message, true);
    } finally {
      trust.disabled = check.disabled = false;
      trust.textContent = 'Trust this proxy';
    }
  } }, 'Trust this proxy');
  const trustBox = h('div', { class: 'reach-trust', hidden: true }, trust, trustWhy);
  const box = h('div', { class: 'reach' }, icon, h('div', {}, what, when, trustBox), check);
  box.paint = () => {
    const reach = awayNow?.on ? awayNow.reach : null;
    box.hidden = !reach && !shown();
    box.className = `reach ${reach ? reach.state : ''}`;
    icon.className = `icon ${reach ? reach.state : ''}`;
    icon.replaceChildren(reachIcon(reach ? reach.state : ''));
    // (Text is set only when it changes: `what` is read out when it does.)
    const say = (el, text) => { if (el.textContent !== text) el.textContent = text; };
    trustBox.hidden = !reach?.trustProxy;
    if (reach?.trustProxy) say(trustWhy, trustProxyWords(reach.trustProxy));
    if (!reach) {
      say(what, 'Check now saves this, and checks that apps can reach tapiOca at that address.');
      say(when, '');
      return;
    }
    say(what, reach.detail);
    say(when, [
      reach.checkedAt ? `Checked ${ago(reach.checkedAt)}` : 'Checking…',
      // (Only apps through the public port are seen; on a VPN, they're home.)
      awayNow.address.startsWith('https://')
        ? reach.lastApp ? `An app last reached tapiOca from outside ${ago(reach.lastApp)}` : 'No app has reached tapiOca from outside since it started'
        : '',
    ].filter(Boolean).join(' · '));
  };
  box.paint();
  return box;
}
async function loadAway() {
  let got;
  try { got = await api('/api/away'); }
  catch (e) { $('#awaySum').textContent = ''; $('#awayBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  setAway(got);  // (the summary beside the panel's title too)
  const body = $('#awayBody');
  if (body.dataset.editing) return;  // (not while it's being changed)
  const fields = awayFields(got, () => { body.dataset.editing = '1'; }, 'awayAddress');
  const media = mediaAwayFields(got, () => { body.dataset.editing = '1'; });
  const result = h('span', { class: 'hint', role: 'status' });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    const { on } = fields.values();
    const mediaMbps = media.value();
    if (mediaMbps === undefined) { result.textContent = `For Media away from home, enter a number of Mbps from 1 to ${got.mediaMbpsMost}.`; return; }
    let saved;
    try { saved = await api('/api/away', { method: 'PUT', body: { ...fields.values(), mediaMbps } }); }
    catch (e) { result.textContent = e.message; return; }
    // (Saved all the same, with a port it can't have: said plainly.)
    if (saved.on && saved.portProblem) toast(`Saved, but ${lowerFirst(saved.portProblem)}`, true);
    else toast(on ? 'Saved. tapiOca’s apps can watch away from home.' : 'Saved. Watching away from home is off.');
    delete body.dataset.editing;
    loadAway();
  } }, 'Save');
  body.replaceChildren(
    ...fields.nodes,
    ...media.nodes,
    h('div', { class: 'scan-set' }, save, result),
    reachStatus(),
    ...(got.on && got.apps ? [h('p', { class: 'muted small', style: 'margin:0' }, `${plural(got.apps, 'app')} signed in away from home since tapiOca started.`)] : []));
}
// Media away from home: Original, or up to a number of Mbps (see away.py on
// the server), with the upload tapiOca's apps measured from outside
// beside it, as a guide. `value()`: null for Original, the number, or
// undefined while the number won't do.
function mediaAwayFields(got, onEdit) {
  const most = got.mediaMbpsMost;
  const pick = h('select', { id: 'mediaAway', style: 'width:auto', onchange: () => { onEdit(); paint(); } },
    h('option', { value: 'original' }, 'Original'), h('option', { value: 'cap' }, 'Up to…'));
  pick.value = got.mediaMbps ? 'cap' : 'original';
  const mbps = h('input', { type: 'number', id: 'mediaAwayMbps', min: 1, max: most, step: 1, value: got.mediaMbps || '', placeholder: 'Mbps', 'aria-label': 'Up to how many Mbps', style: 'width:100px', oninput: onEdit });
  const unit = h('span', {}, 'Mbps');
  const paint = () => { mbps.hidden = unit.hidden = pick.value !== 'cap'; };
  paint();
  const up = got.upload;
  const measured = up
    ? `tapiOca’s apps measured your home’s upload from outside at ${up.mbps} Mbps (${shortDate(up.at)}, from ${up.device}). Everyone watching away from home shares it, stations too, so a cap well under it leaves room for others.`
    : 'No connection test from outside yet. To run one, open Options in a tapiOca app on a phone using mobile data and choose Test the connection; its result shows here, as a guide.';
  return {
    nodes: [
      h('div', { class: 'field' },
        h('label', { for: 'mediaAway' }, 'Media away from home'),
        h('div', { class: 'scan-set' }, pick, mbps, unit),
        h('span', { class: 'hint' }, 'Original plays each title as it would at home. With a cap, a title whose file needs more is converted down to fit, at most 1080p (this takes a share of the server’s processor, as other converted copies do); one within it plays as it would at home. When a connection can’t keep up, the apps still step down on their own.'),
        h('span', { class: 'hint' }, measured)),
    ],
    value: () => {
      if (pick.value !== 'cap') return null;
      const n = Number(mbps.value);
      return Number.isInteger(n) && n >= 1 && n <= most ? n : undefined;
    },
  };
}
// How many can watch at once in tapiOca's apps (see capacity.py) ---------------
const CONNECTION_TEST_MB = 20;  // (as the apps' test: capacity.TEST_MB)
const shortDate = ms => new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric' });
async function loadAppLimits() {
  let got;
  try { got = await api('/api/app-limits'); }
  catch (e) { $('#appLimitsSum').textContent = ''; $('#appLimitsBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  const limitText = (n, where) => n ? `${plural(n, 'device')}${where}` : `no limit${where}`;
  $('#appLimitsSum').textContent = got.devices || got.away
    ? `${limitText(got.devices, '')}, ${limitText(got.away, ' away from home')}` : 'No limit';
  const body = $('#appLimitsBody');
  if (body.dataset.editing) return;  // (not while it's being changed)
  const box = (id, value) => h('input', { type: 'number', id, min: 0, max: got.most, step: 1, placeholder: 'No limit', value: value || '', style: 'width:120px',
    oninput: () => { body.dataset.editing = '1'; paint(); } });
  const devices = box('appLimitDevices', got.devices);
  const away = box('appLimitAway', got.away);
  const count = el => Math.max(0, Math.floor(Number(el.value) || 0));
  const warnings = h('div', { class: 'arr-body', style: 'margin:0' });
  const result = h('span', { class: 'hint', role: 'status' });
  const room = got.room;
  const useBtn = h('button', { type: 'button', class: 'btn', hidden: !(room.home || room.away), onclick: () => {
    if (room.home) devices.value = room.home.devices;
    if (room.away) away.value = room.away.devices;
    body.dataset.editing = '1';
    paint();
  } }, 'Use the recommended numbers');
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    try { await api('/api/app-limits', { method: 'PUT', body: { devices: count(devices), away: count(away) } }); }
    catch (e) { result.textContent = e.message; return; }
    toast('Saved');
    delete body.dataset.editing;
    loadAppLimits();
  } }, 'Save');
  function paint() {
    const lines = [];
    const n = count(devices), m = count(away);
    if (room.home && n > room.home.devices) lines.push(`${plural(n, 'device')} at once is more than the connection test at home found room for (about ${room.home.devices}). Viewers may see the picture stutter or pause to catch up.`);
    if (room.away && m > room.away.devices) lines.push(`${plural(m, 'device')} away from home is more than your home internet upload can handle, based on the connection test away from home (about ${room.away.devices}). Viewers away from home may see the picture stutter or pause to catch up.`);
    if (n && m > n) lines.push('The limit away from home can’t be higher than the overall limit.');
    warnings.replaceChildren(...lines.map(w => h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', w)));
  }
  const tested = where => {
    const r = room[where];
    const place = where === 'away' ? 'away from home' : 'at home';
    if (!r) return h('li', {}, `No connection test ${place} yet.`);
    const t = r.test;
    return h('li', {}, `${where === 'away' ? 'Away from home' : 'At home'}: the fastest recent test (${t.mbps} Mbps, from ${t.device}${t.user ? ` as ${t.user}` : ''}, ${shortDate(t.at)}) leaves room for about ${plural(r.devices, 'device')} at once.`);
  };
  // The apps' connection test, run from this browser (1.34.1, the owner):
  // tapiOca's data timed as it arrives here, then what was found said to
  // tapiOca, which keeps it with the apps' tests.
  const testSaid = h('span', { class: 'hint', role: 'status' });
  const testBtn = h('button', { type: 'button', class: 'btn', onclick: async () => {
    testBtn.disabled = true;
    testSaid.textContent = 'Testing… (a few seconds)';
    try {
      const began = performance.now();
      const data = await api(`/api/internal/speed-test?mb=${CONNECTION_TEST_MB}`, { blob: true });
      const seconds = Math.max(0.001, (performance.now() - began) / 1000);
      const mbps = Math.round(data.size * 8 / seconds / 1e5) / 10;
      const found = await api('/api/internal/speed-test', { method: 'POST', body: { mbps, app: 'tapiOca’s page' } });
      const said = `${found.mbps} Mbps ${found.where === 'away' ? 'away from home' : 'at home'}: room for about ${plural(found.room, 'device')} at once.`;
      testSaid.textContent = said;
      toast(said);
      if (!body.dataset.editing) loadAppLimits();
    } catch (e) { testSaid.textContent = e.message; }
    finally { testBtn.disabled = false; }
  } }, 'Test the connection');
  const tests = got.tests.length ? h('table', { class: 'users' },
    h('tr', {}, h('th', {}, 'When'), h('th', {}, 'Where'), h('th', {}, 'App'), h('th', {}, 'Speed')),
    ...got.tests.map(t => h('tr', {}, h('td', {}, new Date(t.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })),
      h('td', {}, t.where === 'away' ? 'Away from home' : 'At home'), h('td', {}, t.device + (t.user ? ` (${t.user})` : '')), h('td', {}, `${t.mbps} Mbps`)))) : null;
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'Each device watching in tapiOca’s apps gets its own copy of the station: at home over your network, and away from home over your internet connection’s upload. A station still uses one tuner no matter how many people watch it, so these limits are about your network, not your server’s processor. Programs played from Media in the apps count too. Plex, Jellyfin and other apps aren’t counted here: they have limits of their own, and the tuners cover them.'),
    h('p', { class: 'muted small', style: 'margin:0' }, `Watching in tapiOca’s apps now: ${plural(got.watching.devices, 'device')}${got.watching.away ? ` (${got.watching.away} away from home)` : ''}.`),
    h('div', { class: 'scan-set' }, h('label', { for: 'appLimitDevices', style: 'min-width:220px' }, 'Devices watching at once'), devices),
    h('div', { class: 'scan-set' }, h('label', { for: 'appLimitAway', style: 'min-width:220px' }, 'Away from home, at most'), away),
    h('p', { class: 'hint', style: 'margin:0' }, 'Leave a box empty for no limit. Devices away from home count toward the first number too: the second keeps your home’s internet upload from running out. A device that’s already watching can always change stations. Any device beyond a limit sees a message such as: “An Admin has limited tapiOca to 5 devices watching at once, so it runs smoothly for everyone. Please try again later.”'),
    warnings,
    h('div', { class: 'limit-note' }, h('strong', {}, 'What tapiOca recommends'),
      h('ul', {},
        h('li', {}, `Each device uses about ${got.eachMbps} Mbps (at ${got.picture}, the largest picture size your stations use).`),
        tested('home'), tested('away'),
        h('li', {}, 'Test the connection runs the same test as tapiOca’s apps, from this browser. It counts as at home or away from home by where this page is opened. To test away from home, run it on a phone using mobile data (in a tapiOca app, under Options), or from this page opened outside your home: that measures your home’s upload the way viewers away from home get it. Test when your connection isn’t busy, and again from time to time. The fastest recent test is used.')),
      h('div', { class: 'scan-set' }, testBtn, testSaid)),
    h('div', { class: 'scan-set' }, save, useBtn, result),
    ...(tests ? [h('div', {}, h('strong', {}, 'Recent connection tests'), tests)] : []));
  paint();
}
// Media in tapiOca's apps (see ondemand.py) --------------------------------------
// Media in tapiOca's apps: its settings, in its panel on the
// Access tab and in the setup. `changed`: whether anything's been changed.
function libraryFields(got, onEdit) {
  const boxes = new Map();
  const choices = got.libraries.map(l => {
    // (None shared yet, from before 1.34.1: every one is offered, ticked.)
    // (While Plex's can't be listed, nothing here changes: see values.)
    const box = h('input', { type: 'checkbox', checked: got.waiting || got.shared.includes(l.key), disabled: !!got.problem, oninput: onEdit });
    boxes.set(l.key, box);
    return h('label', {}, box, ` ${l.title} `, h('span', { class: 'muted small' }, l.kind === 'movie' ? '(movies)' : '(shows)'));
  });
  // When playing can't keep up: offer a smaller version, or switch to it on its own.
  const slow = (where, label, hint) => {
    const pick = h('select', { onchange: onEdit },
      h('option', { value: 'offer' }, 'Stop, and offer a smaller version'),
      h('option', { value: 'switch' }, 'Switch to a smaller version on its own'));
    pick.value = (got.whenSlow || {})[where] || (where === 'home' ? 'offer' : 'switch');
    return [pick, h('label', { class: 'small' }, h('strong', {}, label), ' ', pick, hint ? h('span', { class: 'muted' }, ' ', hint) : '')];
  };
  const [slowHome, slowHomeRow] = slow('home', 'At home:', '');
  const [slowAway, slowAwayRow] = slow('away', 'Away from home:', '');
  // (While the Media folders can't all be listed, they're left as they are.)
  const values = () => ({
    ...(got.problem ? {} : { libraries: [...boxes].filter(([, b]) => b.checked).map(([key]) => key) }),
    whenSlow: { home: slowHome.value, away: slowAway.value },
  });
  const first = JSON.stringify(values());
  return {
    nodes: [
      h('p', { style: 'margin:0' }, got.everything
        ? 'People can browse and watch every Media folder on demand in tapiOca’s apps, beside your stations, and Media folders added later too. Untick any you’d rather keep out, then save. Stations don’t change, and neither do Plex, Jellyfin or other apps.'
        : got.waiting
          ? 'No Media folders are shared in tapiOca’s apps yet. Every one is ticked to start: untick any you’d rather keep out. People can browse and watch the ones you share on demand, beside your stations. Stations don’t change, and neither do Plex, Jellyfin or other apps.'
          : 'The Media folders people can browse and watch on demand in tapiOca’s apps, beside your stations. Stations don’t change, and neither do Plex, Jellyfin or other apps.'),
      h('div', { class: 'limit-note' }, h('strong', {}, 'How it works'),
        h('ul', {},
          h('li', {}, h('strong', {}, 'The best picture and sound. '), 'A file plays as it is whenever the device can play it, including 4K and HDR. If it can’t, tapiOca makes a copy as it plays: repackaged, with the picture kept as it is (this costs next to nothing), or converted, with the picture made again (this takes a share of the server’s processor, so at most 3 at once; on a GPU it’s light on the processor, so up to 6). Converted copies are 1080p at most, and HDR is made ordinary.'),
          h('li', {}, h('strong', {}, 'Each person’s own place. '), 'The Resume row, where each program picks up and what’s been watched are kept for each person who signs in (shared by everyone while sign-in is off).'),
          h('li', {}, h('strong', {}, 'At home and away. '), 'Media can be watched on your home network, or through a VPN such as Tailscale or WireGuard. With tapiOca’s apps away from home turned on (above), it can also be watched through the public port, by people signed in, at the quality you choose there.'),
          h('li', {}, h('strong', {}, 'Steady playing. '), 'The apps buffer ahead first. If playing still can’t keep up for a while, a short connection test says whether it’s the connection, tapiOca reading the file, or the device, and a smaller version of the title is used, as you choose below.'),
          h('li', {}, 'Programs played this way count toward the limit on devices watching at once, set on the Access tab.'))),
      ...(got.problem ? [h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', got.problem)] : []),
      ...(choices.length ? [h('div', { class: 'arr-body', style: 'margin:0;gap:6px' }, ...choices)]
        : [h('p', { class: 'muted small', style: 'margin:0' }, got.problem ? '' : 'There are no Media folders of shows or movies yet.')]),
      h('div', { class: 'arr-body', style: 'margin:0;gap:6px' },
        h('strong', { class: 'small' }, 'When playing can’t keep up'), slowHomeRow, slowAwayRow),
    ],
    values,
    changed: () => JSON.stringify(values()) !== first,
  };
}
async function loadAppLibraries() {
  let got;
  try { got = await api('/api/app-libraries'); }
  catch (e) { $('#appLibrariesSum').textContent = ''; $('#appLibrariesBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  const shared = got.libraries.filter(l => got.shared.includes(l.key));
  $('#appLibrariesSum').textContent = got.everything ? 'Every Media folder'
    : shared.length ? `Shared: ${shared.map(l => l.title).join(', ')}` : got.shared.length ? 'On' : 'Off';
  const body = $('#appLibrariesBody');
  if (body.dataset.editing) return;  // (not while it's being changed)
  const fields = libraryFields(got, () => { body.dataset.editing = '1'; });
  // Even sound for a show's episodes (see applibrary.py on the server): on to start.
  const even = h('input', { type: 'checkbox', id: 'evenSound', checked: got.evenSound, oninput: () => { body.dataset.editing = '1'; } });
  const evenField = h('div', { class: 'arr-body', style: 'margin:0;gap:6px' },
    h('label', { for: 'evenSound' }, even, ' ', h('strong', {}, 'Even sound for a show’s episodes')),
    h('span', { class: 'hint' }, 'Every episode plays at the same loudness as the episodes on your stations, so a show’s episodes match, in any order, and none is much louder or quieter than the next. Movies aren’t changed. The picture plays as it is and only the sound is made again, which costs next to nothing (where the picture can’t be kept as it is, the episode plays as it is). The cost: sound a device would send as it is to a receiver or soundbar, such as Dolby Atmos or DTS, comes as ordinary 5.1 or stereo instead. Turn this off to play each episode’s sound as it is.'));
  const result = h('span', { class: 'hint', role: 'status' });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    const chosen = { ...fields.values(), evenSound: even.checked };
    try { await api('/api/app-libraries', { method: 'PUT', body: chosen }); }
    catch (e) { result.textContent = e.message; return; }
    toast(!chosen.libraries ? 'Saved' : chosen.libraries.length ? 'Saved. tapiOca’s apps can show the Media folders you chose.' : 'Saved. tapiOca’s apps don’t show any Media folder.');
    delete body.dataset.editing;
    loadAppLibraries();
  } }, 'Save');
  body.replaceChildren(
    ...fields.nodes,
    evenField,
    h('div', { class: 'scan-set' }, save, result),
    ...(got.playing ? [h('p', { class: 'muted small', style: 'margin:0' }, `Playing from Media now: ${plural(got.playing, 'device')}.`)] : []));
}
// API tokens, for tapiOca's API (see api.py) ----------------------------------------
const API_TOKEN_DAYS = [[30, 'In 30 days'], [90, 'In 90 days'], [365, 'In a year'], [0, 'Never']];
async function loadApiTokens() {
  let got;
  try { got = await api('/api/api-tokens'); }
  catch (e) { $('#apiTokensSum').textContent = ''; $('#apiTokensBody').replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message)); return; }
  const n = got.tokens.length;
  $('#apiTokensSum').textContent = (n ? plural(n, 'token') : 'None') + (got.outside ? ', accepted from the internet' : '');
  const body = $('#apiTokensBody');
  if (body.dataset.editing) return;  // (not while one is being made, or shown)
  const editing = () => { body.dataset.editing = '1'; };
  const when = ms => new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  const intro = h('p', { style: 'margin:0' }, 'API tokens let your own scripts, home automation (such as Home Assistant) and other players use tapiOca’s API: its stations, guide and streams, and how it’s doing. An Admin token can also update a station from Plex, check a station’s files, refresh Plex’s guide, and make a backup. The README’s “tapiOca’s API” section explains how, and docs/api.md lists every address.');
  if (!got.signIn) {
    body.replaceChildren(intro, h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' Sign-in is off, so the API needs no token on your network. API tokens come with sign-in: add a user above first.'));
    return;
  }
  const table = n ? h('table', { class: 'users' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Name'), h('th', {}, 'Scope'), h('th', {}, 'Made by'), h('th', {}, 'Last used'), h('th', {}, 'Expires'), h('th', {}, ''))),
    h('tbody', {}, ...got.tokens.map(t => h('tr', {},
      h('td', {}, h('strong', {}, t.name)),
      h('td', { 'data-label': 'Scope' }, t.scope === 'admin' ? 'Admin' : 'Viewer'),
      h('td', { class: 'small', 'data-label': 'Made by' }, `${t.by}, ${when(t.createdMs)}`),
      h('td', { class: 'small', 'data-label': 'Last used' }, t.usedMs ? when(t.usedMs) : 'Never'),
      h('td', { class: 'small', 'data-label': 'Expires' }, t.expiresMs ? when(t.expiresMs) : 'Never'),
      h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: async () => {
        if (!confirm(`Revoke “${t.name}”? Anything using it stops working at once.`)) return;
        try { await api(`/api/api-tokens/${t.id}`, { method: 'DELETE' }); toast(`“${t.name}” is revoked`); }
        catch (err) { toast(err.message, true); }
        loadApiTokens();
      } }, 'Revoke')))))) : null;
  const name = h('input', { type: 'text', id: 'apiTokenName', maxlength: ACCESS.apiTokenNameMax, placeholder: 'Home Assistant', autocomplete: 'off', oninput: editing });
  const scope = h('select', { id: 'apiTokenScope', onchange: editing },
    h('option', { value: 'viewer' }, 'Viewer (reads only)'), h('option', { value: 'admin' }, 'Admin'));
  const days = h('select', { id: 'apiTokenDays', onchange: editing }, ...API_TOKEN_DAYS.map(([d, label]) => h('option', { value: String(d) }, label)));
  days.value = '90';
  const result = h('span', { class: 'hint', role: 'status' });
  const shown = h('div', { hidden: true });
  const make = h('button', { type: 'submit', class: 'btn primary' }, 'Make token');
  const form = h('form', { class: 'adduser', onsubmit: async e => {
    e.preventDefault();
    let made;
    try { made = await api('/api/api-tokens', { method: 'POST', body: { name: name.value, scope: scope.value, days: Number(days.value) || null } }); }
    catch (err) { result.textContent = err.message; return; }
    editing();
    result.textContent = '';
    const code = h('code', { style: 'word-break:break-all' }, made.token);
    const copy = h('button', { type: 'button', class: 'btn', onclick: async () => {
      toast(await copyText(made.token) ? 'Copied' : 'Couldn’t copy. Select the token and copy it.', false);
    } }, 'Copy');
    const done = h('button', { type: 'button', class: 'btn', onclick: () => { delete body.dataset.editing; loadApiTokens(); } }, 'Done');
    shown.replaceChildren(h('div', { class: 'limit-note' },
      h('strong', {}, `“${made.name}” is ready`),
      h('p', { class: 'small', style: 'margin:4px 0' }, 'Copy it now: tapiOca keeps only a fingerprint of it, so it can’t show it again. Scripts send it in a header: ', h('code', {}, 'Authorization: Bearer <token>'), '.'),
      h('div', { class: 'copyrow' }, code, copy, done)));
    shown.hidden = false;
    form.hidden = true;
  } },
    h('div', { class: 'field' }, h('label', { for: 'apiTokenName' }, 'What it’s for'), name),
    h('div', { class: 'field' }, h('label', { for: 'apiTokenScope' }, 'Scope'), scope),
    h('div', { class: 'field' }, h('label', { for: 'apiTokenDays' }, 'Expires'), days),
    make);
  const outside = h('input', { type: 'checkbox', checked: got.outside, onchange: async () => {
    if (outside.checked && !confirm('Accept API tokens from the internet? A script with a token could then use it from anywhere, over HTTPS through your public port.')) { outside.checked = false; return; }
    try { await api('/api/api-tokens/outside', { method: 'PUT', body: { on: outside.checked } }); toast(outside.checked ? 'API tokens are accepted from the internet' : 'API tokens work on your home network only'); }
    catch (err) { toast(err.message, true); }
    loadApiTokens();
  } });
  body.replaceChildren(intro,
    h('div', { class: 'limit-note' }, h('strong', {}, 'How they work'),
      h('ul', {},
        h('li', {}, h('strong', {}, 'Viewer or Admin. '), 'A Viewer token only reads. An Admin token never does more than the Admin who made it can do now.'),
        h('li', {}, h('strong', {}, 'Shown once. '), 'tapiOca keeps only a fingerprint of each token. If one is lost, revoke it and make another.'),
        h('li', {}, h('strong', {}, 'The API only. '), 'A token can’t open this page or sign in to tapiOca’s apps. It stops working when it expires, when it’s revoked, or when the Admin who made it is removed.'))),
    ...(table ? [table] : [h('p', { class: 'muted small', style: 'margin:0' }, 'No API tokens yet.')]),
    form, shown, result,
    h('label', {}, outside, ' Accept API tokens from the internet'),
    h('p', { class: 'hint', style: 'margin:0' }, 'Off by default. With it off, tokens work only on your home network, or through a VPN such as Tailscale or WireGuard (to tapiOca, a VPN is home). With it on, they also work through the public port, over HTTPS only.'));
}
