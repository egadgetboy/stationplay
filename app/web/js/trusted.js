// Trusted networks, trusted proxies and names for tapiOca at home (the Access
// tab; see trusted.py and trustedapi.py on the server), and Who's tuning in?
// on the sign-in page, on a trusted network.

// The Access tab ---------------------------------------------------------------
let trustedLists = null;  // what's listed, where you are, and what came through a door
let trustedPeople = [];  // everyone, for Signed in as
// What each door left open says, with its last address (see doors.py).
const DOOR_SEEN = {
  'home-port': d => `${d.address} reached the home port from the internet.`,
  proxy: d => `${d.address} sent internet visitors to the home port.`,
  name: d => `${d.address} asked for the home port by the name ${d.host || 'an internet name'}.`,
  'proxy-unknown': d => `tapiOca ignored forwarding headers from ${d.address}: it isn’t a trusted proxy.`,
};
async function loadTrusted() {
  try {
    [trustedLists, trustedPeople] = await Promise.all([
      api('/api/access/trusted'), me.required ? api('/api/access/users') : Promise.resolve([])]);
  } catch (e) {
    for (const id of ['trusted', 'proxies', 'homeNames']) {
      $(`#${id}Sum`).textContent = '';
      $(`#${id}Body`).replaceChildren(h('p', { class: 'muted', style: 'margin:0' }, e.message));
    }
    return;
  }
  renderTrustedLists();
}
function renderTrustedLists() {
  renderTrusted();
  renderProxies();
  renderHomeNames();
}
// Saves one list (each save replaces only what it sends). A network wider
// than one home network asks first. `said`: where to show why not.
async function saveTrustedLists(body, done, said) {
  let got;
  try { got = await api('/api/access/trusted', { method: 'PUT', body }); }
  catch (e) {
    if (e.status === 409 && !body.confirmWide) {
      return confirm(e.message) ? saveTrustedLists({ ...body, confirmWide: true }, done, said) : false;
    }
    said.textContent = e.message;
    return false;
  }
  trustedLists = got;
  toast(done);
  renderTrustedLists();
  return true;
}
const entryOut = e => ({ network: e.network, label: e.label, gives: e.gives, person: e.person });
const entryName = e => e.label || e.network;
const addressCount = n => n === 1 ? 'One device' : `${n.toLocaleString()} addresses`;
// What an entry gives: Who's tuning in?, or Signed in as someone. An Admin
// only on one device's address (the server says so too).
function givesSelect(value, single, attrs = {}) {
  const select = h('select', attrs,
    h('option', { value: 'picker' }, 'Who’s tuning in?'),
    ...trustedPeople.map(u => h('option', { value: String(u.id), disabled: u.role === 'admin' && !single },
      `Signed in as ${u.name}${u.role === 'admin' && !single ? ' (one device only)' : ''}`)));
  select.value = value;
  return select;
}
const givesOf = select => select.value === 'picker'
  ? { gives: 'picker', person: null } : { gives: 'person', person: Number(select.value) };
// The Docker notice: where connections seem to come from (see relays.py).
function seeingNotice(got) {
  const relay = got.relayAddress || 'Docker’s own address';
  const said = {
    hidden: `tapiOca can’t see where connections come from. They all arrive from ${relay}, Docker’s own address. So trusted networks are off, and tapiOca can’t tell the internet from home. To fix it, run tapiOca with host networking, or turn off Docker’s userland proxy, then restart tapiOca. The README shows how. On Docker Desktop for Mac or Windows, there’s no fix: every device signs in.`,
    partial: `Some devices reach tapiOca through Docker’s own address, ${relay}, often over IPv6. tapiOca can’t trust them. Open tapiOca by its IPv4 address, such as http://192.168.1.20:3310.`,
    unreadable: 'tapiOca can’t read this computer’s network settings, so it can’t tell which connections come through Docker or a router. Trusted networks are off.',
  }[got.seeing];
  return said ? h('div', { class: 'reach down' },
    h('span', { class: 'icon down', 'aria-hidden': 'true' }, reachIcon('down')),
    h('p', { class: 'what' }, said)) : null;
}
function renderTrusted() {
  const got = trustedLists;
  const entries = got.entries;
  $('#trustedSum').textContent = entries.length ? plural(entries.length, 'network') : 'None';
  const said = h('span', { class: 'hint', role: 'status' });
  const save = (list, done) => saveTrustedLists({ entries: list.map(entryOut) }, done, said);
  const mine = got.you.entry ? entries.find(e => e.id === got.you.entry) : null;
  const you = h('p', { class: 'trusted-you' }, mine
    ? `You’re at ${got.you.address}, on ${entryName(mine)}.`
    : `You’re at ${got.you.address}, not on a trusted network.`);
  const rows = entries.map(e => {
    const single = e.addresses === 1;
    const value = e.gives === 'person' && e.person ? String(e.person) : 'picker';
    const gives = givesSelect(value, single, { 'aria-label': `What ${entryName(e)} gives`, onchange: async ev => {
      const now = givesOf(ev.target);
      const ok = await save(entries.map(x => x.id === e.id ? { ...x, ...now } : x), `Saved. ${entryName(e)}’s sign-ins and devices start over.`);
      if (!ok) ev.target.value = value;
    } });
    return h('tr', {},
      h('td', {}, h('strong', {}, entryName(e)), e.label ? h('span', { class: 'hint' }, e.network) : null),
      h('td', { class: 'small', 'data-label': 'Addresses' }, addressCount(e.addresses)),
      h('td', { 'data-label': 'Gives' }, gives),
      h('td', { class: 'small', 'data-label': 'Devices' }, e.devices ? plural(e.devices, 'device') : 'No devices'),
      h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: () => {
        if (!confirm(`Remove ${entryName(e)}? Devices it signed in or linked are signed out.`)) return;
        save(entries.filter(x => x.id !== e.id), `${entryName(e)} is off the list`);
      } }, 'Remove')));
  });
  const network = h('input', { type: 'text', id: 'trustedNetwork', placeholder: '192.168.1.0/24 or 192.168.1.44', maxlength: 50, required: true,
    autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false' });
  const label = h('input', { type: 'text', id: 'trustedLabel', placeholder: 'Home Wi-Fi', maxlength: 40, autocomplete: 'off' });
  const gives = givesSelect('picker', true, { id: 'trustedGives' });
  // (Who an Admin may be signed in as depends on the address: one device.)
  network.addEventListener('input', () => {
    const single = !network.value.includes('/') || /\/(32|128)$/.test(network.value.trim());
    for (const o of gives.options) {
      const u = trustedPeople.find(x => String(x.id) === o.value);
      if (u?.role === 'admin') o.disabled = !single;
    }
    if (gives.selectedOptions[0]?.disabled) gives.value = 'picker';
  });
  const add = h('form', { class: 'adduser', onsubmit: async ev => {
    ev.preventDefault();
    const entry = { network: network.value.trim(), label: label.value.trim(), ...givesOf(gives) };
    if (await save([...entries, entry], `${entry.label || entry.network} is trusted`)) { network.value = ''; label.value = ''; }
  } },
    h('div', { class: 'field' }, h('label', { for: 'trustedNetwork' }, 'Network, or one device’s IP address'), network),
    h('div', { class: 'field' }, h('label', { for: 'trustedLabel' }, 'Name (optional)'), label),
    h('div', { class: 'field' }, h('label', { for: 'trustedGives' }, 'Its devices'), gives),
    h('button', { type: 'submit', class: 'btn primary' }, 'Add'));
  const offer = got.you.offer && !entries.some(e => e.network === got.you.offer)
    ? h('button', { type: 'button', class: 'btn', onclick: () => save([...entries, { network: got.you.offer, label: 'Home network', gives: 'picker', person: null }], `${got.you.offer} is trusted`) },
      `Add the network you’re on (${got.you.offer})`)
    : null;
  $('#trustedBody').replaceChildren(...[
    h('p', { style: 'margin:0' }, 'Devices on a trusted network skip signing in. Add your own home network, one device, or your own VPN. Never add a guest network. Nothing is trusted until you add it.'),
    h('dl', { class: 'roles' },
      h('dt', {}, 'Who’s tuning in?'),
      h('dd', {}, 'Each person picks themselves, and kids get their own limits. Anyone with a PIN is asked for it, and an Admin always is. It lists people shown on Every device at home.'),
      h('dt', {}, 'Signed in as a person'),
      h('dd', {}, 'The device is signed in as that person. For an Admin, only one device’s address.')),
    h('p', { class: 'hint', style: 'margin:0' }, 'Anyone can still sign in as someone else. Works in tapiOca’s apps (1.36.0 and later) and on this page. Plex, Jellyfin and other apps use Tuner access.'),
    !me.required ? h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', 'Trusted networks work once signing in is on. Add a user above to turn it on.') : null,
    seeingNotice(got),
    you,
    entries.length ? h('table', { class: 'users trusted-list' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Network'), h('th', {}, 'Addresses'), h('th', {}, 'Gives'), h('th', {}, 'Devices'), h('th', {}, ''))),
      h('tbody', {}, ...rows)) : h('p', { class: 'muted small', style: 'margin:0' }, 'No networks are trusted.'),
    add,
    h('div', { class: 'scan-set' }, offer, said)].filter(Boolean));
}
function renderProxies() {
  const got = trustedLists;
  const proxies = got.proxies;
  $('#proxiesSum').textContent = !proxies.length ? 'None' : proxies.length === 1 ? '1 proxy' : `${proxies.length} proxies`;
  const said = h('span', { class: 'hint', role: 'status' });
  const save = (list, done) => saveTrustedLists({ proxies: list.map(p => ({ network: p.network, label: p.label })) }, done, said);
  const address = h('input', { type: 'text', id: 'proxyAddress', placeholder: '192.168.1.2', maxlength: 50, required: true,
    autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false' });
  const label = h('input', { type: 'text', id: 'proxyLabel', placeholder: 'Nginx Proxy Manager', maxlength: 40, autocomplete: 'off' });
  const add = h('form', { class: 'adduser', onsubmit: async ev => {
    ev.preventDefault();
    const p = { network: address.value.trim(), label: label.value.trim() };
    if (await save([...proxies, p], `${p.label || p.network} is a trusted proxy`)) { address.value = ''; label.value = ''; }
  } },
    h('div', { class: 'field' }, h('label', { for: 'proxyAddress' }, 'Proxy’s IP address'), address),
    h('div', { class: 'field' }, h('label', { for: 'proxyLabel' }, 'Name (optional)'), label),
    h('button', { type: 'submit', class: 'btn primary' }, 'Add'));
  const seen = got.doors.slice().sort((a, b) => b.lastMs - a.lastMs);
  $('#proxiesBody').replaceChildren(...[
    h('p', { style: 'margin:0' }, 'Your reverse proxy or tunnel, by its address on your home network (127.0.0.1 for a tunnel in tapiOca’s own container). tapiOca believes the visitor’s address a proxy sends only from one listed here, never just because it sends one.'),
    proxies.length ? h('table', { class: 'users trusted-list' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Proxy'), h('th', {}, ''))),
      h('tbody', {}, ...proxies.map(p => h('tr', {},
        h('td', {}, h('strong', {}, p.label || p.network), p.label ? h('span', { class: 'hint' }, p.network) : null,
          // (Docker's gateway or this machine's own address: see relays.py.)
          p.relay ? h('span', { class: 'hint' }, warnIcon(), ' This is Docker’s own address, or this computer’s, which carries other connections too. Nothing is trusted through it, wrong passwords at home through it count as it, and anything else from it that names no visitor is treated as from the internet. List it only for a proxy in another container on this server.') : null),
        h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: () => {
          if (!confirm(`Remove ${p.label || p.network}? Visitors through it then count as its own address.`)) return;
          save(proxies.filter(x => x.network !== p.network), `${p.label || p.network} is off the list`);
        } }, 'Remove'))))))
      : h('p', { class: 'muted small', style: 'margin:0' }, 'No proxies are listed.'),
    add,
    said,
    h('strong', {}, 'Seen lately'),
    seen.length ? h('ul', { class: 'small', style: 'margin:0;padding-left:18px' },
      ...seen.map(d => h('li', {}, `${(DOOR_SEEN[d.about] || (x => `${x.address}.`))(d)} `, h('span', { class: 'muted' }, ago(d.lastMs)))))
      : h('p', { class: 'muted small', style: 'margin:0' }, 'Nothing has reached the home port from the internet, or through a proxy that isn’t listed, since tapiOca started.')]);
}
function renderHomeNames() {
  const names = trustedLists.homeNames;
  $('#homeNamesSum').textContent = names.length ? plural(names.length, 'name') : 'None';
  const said = h('span', { class: 'hint', role: 'status' });
  const save = (list, done) => saveTrustedLists({ homeNames: list }, done, said);
  const name = h('input', { type: 'text', id: 'homeName', placeholder: 'tv.example.com', maxlength: 253, required: true,
    autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false' });
  $('#homeNamesBody').replaceChildren(
    h('p', { style: 'margin:0' }, 'If you open tapiOca at home by a name such as tv.example.com, add it here, so tapiOca knows that’s you at home and not a tunnel.'),
    names.length ? h('table', { class: 'users' }, h('tbody', {}, ...names.map(n => h('tr', {},
      h('td', {}, h('strong', {}, n)),
      h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: () => save(names.filter(x => x !== n), `${n} is off the list`) }, 'Remove'))))))
      : h('p', { class: 'muted small', style: 'margin:0' }, 'No names are listed.'),
    h('form', { class: 'adduser', onsubmit: async ev => {
      ev.preventDefault();
      if (await save([...names, name.value.trim()], `${name.value.trim()} is a name for tapiOca at home`)) name.value = '';
    } },
      h('div', { class: 'field' }, h('label', { for: 'homeName' }, 'Name'), name),
      h('button', { type: 'submit', class: 'btn primary' }, 'Add')),
    said);
}

// The sign-in page, on a trusted network ---------------------------------------------
// Who's tuning in?: each person listed picks themselves (a PIN if they have
// one; an Admin always gives a PIN or password). Or the device signs in as
// one person: the page presses Continue itself when it's first opened.
let trustedFor = null;  // the person picked, while their PIN or password is asked
let trustedAuto = true;  // (pressed once, on opening: never after signing out or timing out)
const PASSWORD_NOW = /wrong PINs on this device/;
function trustedSignIn(info, idle = false) {
  trustedFor = null;
  const on = !!info && info.gives !== 'none';
  $('#signinTrusted').hidden = $('#signinSomeoneElse').hidden = !on;
  if (!on) return;
  if (idle) trustedAuto = false;
  // (Signed out on purpose in this tab: never pressed for them.)
  try { if (sessionStorage.getItem('tapioca.signedOut')) trustedAuto = false; } catch {}
  for (const id of ['#signinByPassword', '#signinByPin', '#signinGo', '#signinOther', '#signinSwitch', '#signinHome', '#signinWhere']) $(id).hidden = true;
  $('#signinName').required = $('#signinPassword').required = $('#signinPin').required = false;
  if (info.gives === 'person') {
    $('#signinTrustedTitle').textContent = `This device signs in as ${info.name}.`;
    $('#signinPeople').replaceChildren();
    const go = $('#signinContinue');
    go.hidden = false;
    go.textContent = `Continue as ${info.name}`;
    go.onclick = () => trustedSend({});
    if (trustedAuto) { trustedAuto = false; trustedSend({}); }
    return;
  }
  $('#signinTrustedTitle').textContent = 'Who’s tuning in?';
  $('#signinContinue').hidden = true;
  const people = info.people || [];
  $('#signinPeople').replaceChildren(...(people.length ? people.map(p => h('button', {
    class: 'who', type: 'button', role: 'listitem', 'aria-pressed': 'false', onclick: e => trustedPick(p, e.currentTarget),
  }, h('span', { class: 'face', 'aria-hidden': 'true' }, (p.name[0] || '?').toUpperCase()),
    h('span', { class: 'who-name' }, p.name),
    p.pin || p.admin ? h('span', { class: 'who-note' }, p.pin ? 'PIN' : 'Password') : null))
    : [h('p', { class: 'muted small', style: 'margin:0' }, 'No one is listed here yet. Sign in below.')]));
}
// Someone picked: signed in, or asked for their PIN (or password).
function trustedPick(p, button, password = false) {
  for (const b of document.querySelectorAll('#signinPeople .who')) b.setAttribute('aria-pressed', String(b === button));
  $('#signinStatus').textContent = '';
  if (!p.pin && !p.admin) { trustedSend({ id: p.id }); return; }
  trustedFor = { ...p, button, byPassword: password || !p.pin };
  const byPassword = trustedFor.byPassword;
  $('#signinByPin').hidden = byPassword;
  $('#signinByPassword').hidden = !byPassword;
  $('#signinName').closest('.field').hidden = true;
  $('#signinPin').required = !byPassword;
  $('#signinPassword').required = byPassword;
  $('#signinPinLabel').textContent = `PIN for ${p.name}`;
  $('#signinGo').hidden = false;
  $('#signinPin').value = $('#signinPassword').value = '';
  (byPassword ? $('#signinPassword') : $('#signinPin')).focus();
}
// The sign-in form, for the person picked (see access.js).
async function trustedSubmit() {
  const p = trustedFor;
  const body = p.byPassword ? { id: p.id, password: $('#signinPassword').value } : { id: p.id, pin: $('#signinPin').value };
  try { await api('/api/access/trusted-sign-in', { method: 'POST', body }); }
  catch (err) {
    // (Too many wrong PINs on this device: a password now, for those who have one.)
    if (PASSWORD_NOW.test(err.message) && !p.byPassword && p.password) trustedPick(p, p.button, true);
    throw err;
  }
}
async function trustedSend(body) {
  try { await api('/api/access/trusted-sign-in', { method: 'POST', body }); }
  catch (err) { $('#signinStatus').textContent = err.message; return; }
  await signedInNow();
}
// Someone else, by name and password.
$('#signinSomeoneElse').addEventListener('click', () => {
  trustedFor = null;
  $('#signinTrusted').hidden = $('#signinSomeoneElse').hidden = true;
  $('#signinName').closest('.field').hidden = false;
  signInBy('');
  $('#signinGo').hidden = false;
  $('#signinName').focus();
});
