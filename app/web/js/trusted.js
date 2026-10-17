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
  'proxy-unknown': d => `A proxy at ${d.address} isn’t trusted, so tapiOca ignored what it said about its visitors.`,
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
      h('dd', {}, 'For tapiOca’s apps: the device is linked without signing in. Each person signs in on it once, with their password or an invite code, and then picks themselves there. Anyone with a PIN is asked for it. On this page, as anywhere at home, Who’s signing in? lists only the Admins who signed in on that browser.'),
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
  // (Not a proxy that's listed since: the owner, October 14, saw "it isn't
  // a trusted proxy" beside the proxy he'd just trusted.)
  const listedNow = d => d.about === 'proxy-unknown' && proxies.some(p => [d.address, `${d.address}/32`, `${d.address}/128`].includes(p.network));
  const seen = got.doors.filter(d => !listedNow(d)).sort((a, b) => b.lastMs - a.lastMs);
  $('#proxiesBody').replaceChildren(...[
    h('p', { style: 'margin:0' }, 'The reverse proxy that brings tapiOca’s apps in from the internet. tapiOca believes what a proxy says about its visitors only when it’s listed here. To add yours, choose Trust this proxy when tapiOca offers it, under tapiOca’s apps away from home, or enter its address below (127.0.0.1 for a tunnel in tapiOca’s own container).'),
    proxies.length ? h('table', { class: 'users trusted-list' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Proxy'), h('th', {}, ''))),
      h('tbody', {}, ...proxies.map(p => h('tr', {},
        h('td', {}, h('strong', {}, p.label || p.network), p.label ? h('span', { class: 'hint' }, p.network) : null,
          // (Docker's gateway or this machine's own address: see relays.py.)
          // (Said plainly, the owner, October 14: "Also over my head a bit.")
          p.relay ? h('span', { class: 'hint' }, 'Docker’s address on this server. Your proxy in another container uses it, and so do Plex and your other apps, which keep working. Nothing through it skips signing in.') : null),
        h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: () => {
          if (!confirm(`Remove ${p.label || p.network}? Apps coming in through it from outside are turned away until it’s trusted again.`)) return;
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
// One that signs in as someone: the page presses Continue itself when it's
// first opened. It never says who (1.38.0). (From 1.38.0 a network's Who's tuning in? is the apps' only:
// on the page, Who's signing in? is this browser's Admins, as at any home
// address. See showPeople in access.js.)
let trustedAuto = true;  // (pressed once, on opening: never after signing out or timing out)
// Whether `info` (what tapiOca says of this network) signs in as someone,
// shown if so.
function trustedSignIn(info, idle = false) {
  const on = !!info && info.gives === 'person';
  if (!on) return false;
  if (idle) trustedAuto = false;
  // (Signed out on purpose in this tab: never pressed for them.)
  try { if (sessionStorage.getItem('tapioca.signedOut')) trustedAuto = false; } catch {}
  showPeople([]);
  for (const id of ['#signinForm', '#pinForm', '#signinOther', '#signinForget', '#signinHome', '#signinWhere']) $(id).hidden = true;
  $('#signinTrusted').hidden = $('#signinSomeoneElse').hidden = false;
  // (Never who: no User is shown on this page. The owner, October 17.)
  $('#signinTrustedTitle').textContent = 'This device signs in for watching.';
  const go = $('#signinContinue');
  go.hidden = false;
  go.textContent = 'Continue on this device';
  go.onclick = () => trustedSend({});
  if (trustedAuto) { trustedAuto = false; trustedSend({}); }
  return true;
}
async function trustedSend(body) {
  try { await api('/api/access/trusted-sign-in', { method: 'POST', body }); }
  catch (err) { $('#signinStatus').textContent = err.message; return; }
  await signedInNow();
}
