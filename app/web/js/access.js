// Signing in, Admins and Users, and linked devices.
// Signing in (see access.py) ------------------------------------------------------
// Signing in may be off (anyone using the page can do everything) or on, as
// an Admin or a User.
let me = { required: false, user: null };
// (An Admin a trusted network signed in without their password is for
// watching: Admin tasks ask for it. See access.STEP_UP on the server.)
const isAdmin = () => !me.required || (me.user?.role === 'admin' && !me.user.byNetwork);
const roleName = role => role === 'admin' ? 'Admin' : 'User';
const aRole = role => role === 'admin' ? 'an Admin' : 'a User';
const signedOut = () => !$('#signinView').hidden;
async function loadMe() {
  me = await api('/api/access/me');
  signOutAt(me.idleLeftMs);
  document.querySelectorAll('.tab.admin').forEach(t => { t.hidden = !isAdmin(); });
  if (!FOR_EVERYONE.includes(currentTab) && !isAdmin()) showTab('stations');
  $('#footSetupWrap').hidden = !isAdmin();
  $('#userPill').hidden = !me.user;
  if (me.user) $('#userPill').firstElementChild.textContent = `${me.user.name} · ${roleName(me.user.role)}`;
  renderRoom();
}
// `idle`: signed out after an hour without activity.
function showSignIn(idle = false) {
  if (signedOut()) return;
  for (const d of document.querySelectorAll('dialog[open]')) d.close();
  $('.wrap').hidden = true;
  $('#signinView').hidden = false;
  $('#signinStatus').textContent = '';
  // From the internet, before anyone can sign in at all; or why you were signed out.
  const note = me.notSetUp || (idle ? ACCESS.idleSignedOut : '');
  $('#signinNote').hidden = !note;
  $('#signinNote').textContent = note;
  // Where the PIN works: from the internet (the public port, even through a
  // proxy at home), never; at home, after a password on this browser. (Hidden
  // when the PIN is what's asked: see signInBy.)
  $('#signinWhere').hidden = !me.outside || !!me.notSetUp;
  $('#signinHome').hidden = !!me.outside || !me.required;
  $('#signinName').closest('.field').hidden = false;
  signInBy('');
  trustedSignIn(null);
  // (From the internet before signing in is on, there's nothing to sign in
  // to: the owner's sentence alone. The fourth audit of 1.35.0.)
  if (me.notSetUp) for (const id of ['#signinByPassword', '#signinByPin', '#signinGo']) $(id).hidden = true;
  else { $('#signinGo').hidden = false; $('#signinName').focus(); }
  // On a trusted network: Who's tuning in?, or the person it signs in as
  // (see trusted.js).
  if (me.trusted && !me.notSetUp) trustedSignIn(me.trusted, idle);
  // At home, on a browser someone signed in on with their password: their PIN
  // will do (see pin_sign_in in access.py). And the notes again, from this
  // answer, in case the page's first one never came.
  api('/api/access/me').then(now => {
    if (!signedOut() || trustedFor) return;
    if (now.trusted && !now.notSetUp) { trustedSignIn(now.trusted, idle); return; }
    if (now.outside && !now.notSetUp) $('#signinWhere').hidden = false;
    if (now.outside) $('#signinHome').hidden = true;
    if (now.pinFor) signInBy(now.pinFor);
  }).catch(() => {});
}
// Signing in with `pinFor`'s PIN, or ('') with a name and password.
let pinFor = '';
function signInBy(name) {
  pinFor = name;
  if (name) $('#signinHome').hidden = true;
  $('#signinByPin').hidden = !name;
  $('#signinByPassword').hidden = !!name;
  $('#signinOther').hidden = !name;
  $('#signinSwitch').hidden = !name;
  $('#signinName').required = $('#signinPassword').required = !name;
  $('#signinPin').required = !!name;
  $('#signinPin').value = '';
  $('#signinStatus').textContent = '';
  if (name) {
    $('#signinPinLabel').textContent = `PIN for ${name}`;
    $('#signinSwitch').textContent = `Not ${name}? Switch user`;
    $('#signinPin').focus();
  }
}
// Their own password instead of the PIN: their name's already there.
$('#signinOther').addEventListener('click', () => {
  const name = pinFor;
  signInBy('');
  $('#signinName').value = name;
  $('#signinPassword').focus();
});
// Someone else at this browser (the owner, October 12): their name and
// password. Once they've signed in, the PIN asked here is theirs.
$('#signinSwitch').addEventListener('click', () => {
  signInBy('');
  $('#signinName').value = '';
  $('#signinPassword').value = '';
  $('#signinName').focus();
});
// Signed out after an hour without activity (see IDLE_SIGN_OUT_S in
// access.py). Using the page (clicking, typing, scrolling or touching) tells
// tapiOca, at most once a minute; its own polling doesn't count.
// tapiOca's clock decides, so using tapiOca in another tab counts
// here too: when the time it last gave comes, the page asks it again (even
// in a hidden tab, which doesn't poll).
let idleTimer = null;
function signOutAt(leftMs) {
  clearTimeout(idleTimer);
  if (leftMs != null) idleTimer = setTimeout(checkMe, leftMs + 1000);
}
let usedAt = 0;  // when tapiOca was last told
let usedLater = null;
function used() {
  if (!me.user || signedOut() || usedLater) return;
  const since = Date.now() - usedAt;
  if (since >= 60000) tellUsed();
  // (Used again since, not in the same click: it's told again when the minute's up.)
  else if (since > 1000) usedLater = setTimeout(() => { usedLater = null; tellUsed(); }, 60000 - since);
}
function tellUsed() {
  if (!me.user || signedOut()) return;
  usedAt = Date.now();
  api('/api/access/active', { method: 'POST' }).then(got => signOutAt(got.idleLeftMs)).catch(() => {});
}
// (Scrolling shows as the wheel, a touch or a key: not as scroll events, as
// the page scrolls itself too, such as the Logs tab when new lines come.)
for (const kind of ['pointerdown', 'keydown', 'wheel', 'touchstart']) {
  addEventListener(kind, used, { capture: true, passive: true });
}
$('#signinForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    if (trustedFor) await trustedSubmit();  // (on a trusted network: see trusted.js)
    else if (pinFor) await api('/api/access/pin-sign-in', { method: 'POST', body: { pin: $('#signinPin').value } });
    else await api('/api/access/sign-in', { method: 'POST', body: { name: $('#signinName').value, password: $('#signinPassword').value } });
  } catch (err) {
    $('#signinStatus').textContent = err.message;
    $('#signinPin').value = '';
    return;
  }
  await signedInNow();
});
// Signed in, however it was: the page, as that person sees it.
async function signedInNow() {
  try { sessionStorage.removeItem('tapioca.signedOut'); } catch {}
  trustedFor = null;
  $('#signinPassword').value = '';
  $('#signinPin').value = '';
  $('#signinView').hidden = true;
  $('.wrap').hidden = false;
  await loadMe();
  showTab(currentTab);
  loadStatus();
  loadChannels();
  linkWanted();
}
$('#userPill').addEventListener('click', () => {
  $('#accountTitle').textContent = `${me.user.name} (${roleName(me.user.role)})`;
  $('#accountForm').reset();
  // (An Admin can turn this off for a User; an Admin can always change their own.)
  const may = me.user.role === 'admin' || me.user.canChangePassword !== false;
  document.querySelectorAll('#pwCurrent, #pwNew, #accountForm [type=submit]').forEach(el => { el.disabled = !may; });
  $('#accountStatus').textContent = !may
    ? 'An Admin has turned off changing your own password. Ask an Admin if it needs changing.'
    : me.user.byNetwork
      ? `This network signed you in without your password, for watching.${me.user.role === 'admin' ? ' For Admin tasks, sign out, then choose Sign in with a password.' : ''}`
      : `At least ${ACCESS.passwordMin} characters. Changing your password signs you out of other browsers and apps.`;
  $('#account').showModal();
});
$('#closeAccount').addEventListener('click', () => $('#account').close());
$('#accountForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    await api('/api/access/me/password', { method: 'POST', body: { current: $('#pwCurrent').value, password: $('#pwNew').value } });
    $('#account').close();
    toast('Password changed');
  } catch (err) { $('#accountStatus').textContent = err.message; }
});
// Linking an app with the code it shows (see links.py on the server).
let linking = null;  // the code shown for confirming, once it's been found
function openLink(code = '') {
  linking = null;
  $('#linkForm').reset();
  $('#linkCode').value = linkCodeShown(code);
  $('#linkCode').disabled = false;
  $('#linkWho').hidden = true;
  $('#linkStatus').textContent = '';
  $('#linkGo').textContent = 'Next';
  $('#linkApp').showModal();
  $('#linkCode').focus();
}
// The code as the app shows it, "K7QM-4DPX": the dash goes in by itself after
// the first 4 characters (the owner asked), so typing it, pasting the code
// with or without it, and backspacing over it all work.
const LINK_HALF = 4;
const linkCodeShown = typed => {
  const plain = typed.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, LINK_HALF * 2);
  return plain.length > LINK_HALF ? `${plain.slice(0, LINK_HALF)}-${plain.slice(LINK_HALF)}` : plain;
};
$('#linkCode').addEventListener('input', e => {
  const input = e.target;
  // (Where the caret is, counted in letters and digits, so it stays put.)
  const before = input.value.slice(0, input.selectionStart ?? input.value.length).replace(/[^A-Za-z0-9]/g, '').length;
  let shown = linkCodeShown(input.value);
  // (Typing forward at the fourth: the dash shows then, ready for the fifth.)
  if ((e.inputType || '').startsWith('insert') && shown.length === LINK_HALF && before === LINK_HALF) shown += '-';
  if (shown === input.value) return;
  input.value = shown;
  const caret = Math.min(shown.length, before + (before > LINK_HALF || (before === LINK_HALF && shown.length > LINK_HALF) ? 1 : 0));
  input.setSelectionRange(caret, caret);
});
const closeLink = () => { $('#linkApp').close(); if (location.pathname === '/link') history.replaceState(null, '', '/' + location.hash); };
$('#openLink').addEventListener('click', () => { $('#account').close(); openLink(); });
$('#closeLink').addEventListener('click', closeLink);
$('#cancelLink').addEventListener('click', closeLink);
$('#linkForm').addEventListener('submit', async e => {
  e.preventDefault();
  const code = $('#linkCode').value.trim();
  if (!linking) {
    try {
      const got = await api(`/api/access/link/${encodeURIComponent(code)}`);
      linking = code;
      $('#linkCode').disabled = true;
      $('#linkWho').textContent = `${got.app} will be signed in as ${me.user.name}. Link it only if it’s yours and in front of you.`;
      $('#linkWho').hidden = false;
      $('#linkStatus').textContent = '';
      $('#linkGo').textContent = 'Link';
    } catch (err) { $('#linkStatus').textContent = err.message; }
    return;
  }
  try {
    const got = await api('/api/access/link', { method: 'POST', body: { code: linking } });
    closeLink();
    toast(`${got.app} is signed in as ${me.user.name}`);
    if (currentTab === 'access') loadApps();
  } catch (err) { $('#linkStatus').textContent = err.message; linking = null; $('#linkCode').disabled = false; $('#linkGo').textContent = 'Next'; }
});
// Opened at /link (where an app sends you): once signed in, the code box.
const linkWanted = () => {
  if (location.pathname !== '/link' || !me.user) return;
  openLink(new URLSearchParams(location.search).get('code') || '');
};
async function loadApps() {
  if (!me.required) { $('#appsPanel').hidden = true; return; }
  let apps = [];
  try { apps = await api('/api/access/apps'); } catch { return; }
  $('#appsPanel').hidden = !apps.length;
  const when = ms => new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  $('#appsTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'App'), h('th', {}, 'Signed in as'), h('th', {}, 'Signed in'), h('th', {}, 'Last used'), h('th', {}, ''))),
    h('tbody', {}, ...apps.map(a => h('tr', {},
      h('td', {}, h('strong', {}, a.app)),
      h('td', { 'data-label': 'Signed in as' }, a.user),
      h('td', { class: 'small', 'data-label': 'Signed in' }, when(a.signedInMs)),
      h('td', { class: 'small', 'data-label': 'Last used' }, when(a.seenMs)),
      h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: async () => {
        if (!confirm(`Sign out ${a.app}? It will need to sign in again to watch.`)) return;
        try { await api(`/api/access/apps/${a.id}`, { method: 'DELETE' }); toast(`${a.app} is signed out`); }
        catch (err) { toast(err.message, true); }
        loadApps();
      } }, 'Sign out'))))));
}
$('#signOut').addEventListener('click', async () => {
  // (Signed out on purpose: a trusted network's sign-in isn't pressed for
  // them again in this tab. See trusted.js.)
  try { sessionStorage.setItem('tapioca.signedOut', '1'); } catch {}
  try { await api('/api/access/sign-out', { method: 'POST' }); } catch {}
  location.reload();
});

// The Access tab: who can sign in.
function limitSelect(value, attrs = {}) {
  const select = h('select', attrs,
    ...ACCESS.stationLimits.map(n => h('option', { value: String(n) }, n === 0 ? 'None (watches only)' : String(n))),
    h('option', { value: '' }, 'Any number'));
  select.value = value == null ? '' : String(value);
  return select;
}
const limitOf = select => select.value === '' ? null : Number(select.value);
$('#newUserStations').replaceWith(limitSelect(ACCESS.newUserStations, { id: 'newUserStations' }));
const showNewUserStations = () => {
  const user = $('#newUserRole').value === 'user';
  $('#newUserStationsField').hidden = !user;
  // A User may have no password: they use only the apps' Who's tuning in?
  $('#newUserPassword').required = !user || !me.required;
  $('#newUserPassword').placeholder = user && me.required ? 'Optional for a User' : '';
  $('#newUserPinField').hidden = !me.required;
  $('#newUserLevelField').hidden = !user || !me.required || !viewing;
};
$('#newUserRole').addEventListener('change', showNewUserStations);
let viewing = null;  // Viewing Levels, and each user's (see viewing.py on the server)
let linked = null;  // linked devices (see devices.py on the server)
async function loadAccess() {
  let users = [];
  try {
    if (me.required) [users, viewing, linked] = await Promise.all([api('/api/access/users'), api('/api/access/viewing'), api('/api/access/devices'), loadClipRatings()]);
  } catch (e) { $('#accessState').textContent = e.message; return; }
  renderViewing();
  if (!$('#addUserForm').contains(document.activeElement)) fillNewUserLevel();
  renderDevices();
  $('#accessState').textContent = me.required
    ? `Sign-in is on: ${plural(users.length, 'user')} can sign in, and everyone else sees only the sign-in page.`
    : 'tapiOca is open: anyone at home, on your network or through a VPN into it (port 3310), can use it, and nobody can from the internet (port 3311). Add a user to require sign-in. The first user is always an Admin, and you’re signed in as that user right away.';
  $('#addUserTitle').textContent = me.required ? 'Add a user' : 'Add the first user (an Admin)';
  if (!me.required) $('#newUserRole').value = 'admin';
  $('#newUserRole').disabled = !me.required;
  showNewUserStations();
  $('#userPanel').hidden = !users.length;
  const admins = users.filter(u => u.role === 'admin').length;
  $('#userTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Name'), h('th', {}, 'Role'), h('th', {}, 'Viewing Level'), h('th', {}, 'Stations they make'), h('th', {}, 'Last signed in'), h('th', {}, ''))),
    h('tbody', {}, ...users.map(u => {
      const role = h('select', { 'aria-label': `${u.name}’s role`, disabled: u.role === 'admin' && admins === 1, onchange: async e => {
        try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { role: e.target.value } }); toast(`${u.name} is now ${aRole(e.target.value)}`); }
        catch (err) { toast(err.message, true); }
        await loadMe();
        loadAccess();
      } }, h('option', { value: 'admin' }, 'Admin'), h('option', { value: 'user' }, 'User'));
      role.value = u.role;
      // Users make as many stations as they may (none with limits, their
      // level's or their own: they only watch); Admins, any number.
      const made = h('div', { class: 'hint' }, `${u.stationsMade} made`);
      const mine = viewing?.users[u.id] || { level: null, stations: {} };
      const level = viewing?.levels.find(lv => lv.id === mine.level);
      const watchesOnly = u.role !== 'admin' && ((level && levelLimited(level)) || hidesCount(mine.own?.blocks) > 0 || mine.ownUnreadable);
      const stations = u.role === 'admin'
        ? h('td', { class: 'small', 'data-label': 'Stations they make' }, 'Any number', made)
        : watchesOnly
          ? h('td', { class: 'small', 'data-label': 'Stations they make' }, 'None (watches only)', u.stationsMade ? made : null)
          : h('td', { 'data-label': 'Stations they make' }, limitSelect(u.maxStations, { 'aria-label': `How many stations ${u.name} can make`, onchange: async e => {
            const limit = limitOf(e.target);
            try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { maxStations: limit } }); toast(`${u.name} can make ${limit == null ? 'any number of stations' : plural(limit, 'station')}`); }
            catch (err) { toast(err.message, true); }
            loadAccess();
          } }), made);
      const set = Object.keys(mine.stations).length + hidesCount(mine.own?.blocks) + (mine.own?.allowTitles || []).length;
      const levelCell = u.role === 'admin'
        ? h('td', { class: 'small', 'data-label': 'Viewing Level' }, 'Sees everything')
        : h('td', { 'data-label': 'Viewing Level' }, h('div', { class: 'inline-add' },
            levelSelect(mine.level, { 'aria-label': `${u.name}’s Viewing Level`, onchange: async e => {
              const id = Number(e.target.value);
              const name = viewing.levels.find(lv => lv.id === id)?.name;
              try { await api(`/api/access/users/${u.id}/viewing`, { method: 'PUT', body: { level: id } }); toast(`${u.name} is on ${name} now`); }
              catch (err) { toast(err.message, true); }
              loadAccess();
            } }),
            h('button', { class: 'btn', type: 'button', onclick: () => openUserStations(u) }, set ? `What they see (${set} set)` : 'What they see')));
      // Whether they may change their own password, on this page and in the
      // apps (an Admin always may).
      const admin = u.role === 'admin';
      const ownPassword = h('label', { class: 'own-password', title: admin ? 'An Admin can always change their own' : null },
        h('input', { type: 'checkbox', checked: admin || u.canChangePassword, disabled: admin, onchange: async e => {
          const on = e.target.checked;
          try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { canChangePassword: on } }); toast(on ? `${u.name} can change their own password` : `${u.name} can’t change their own password now`); }
          catch (err) { toast(err.message, true); }
          loadAccess();
        } }), 'Can change their own password');
      // (Problems with what they watch, from tapiOca's apps: see reports.py.)
      const canReport = h('label', { class: 'own-password', title: admin ? 'An Admin can always report problems' : 'From tapiOca’s apps, about what they watch. Reports go to the Broken files tab.' },
        h('input', { type: 'checkbox', checked: admin || u.canReport, disabled: admin, onchange: async e => {
          const on = e.target.checked;
          try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { canReport: on } }); toast(on ? `${u.name} can report problems` : `${u.name} can’t report problems now`); }
          catch (err) { toast(err.message, true); }
          loadAccess();
        } }), 'Can report problems');
      const named = h('td', {}, h('strong', {}, u.name), u.id === me.user?.id ? h('span', { class: 'hint' }, ' (you)') : null);
      const actions = h('td', {},
        h('button', { class: 'btn', type: 'button', onclick: () => renameUser(u, named) }, 'Rename'), ' ',
        h('button', { class: 'btn', type: 'button', onclick: () => openUserDevices(u) }, 'Devices'), ' ',
        h('button', { class: 'btn', type: 'button', onclick: () => newPassword(u, actions) }, u.hasPassword ? 'New password' : 'Add a password'), ' ',
        h('button', { class: 'btn', type: 'button', onclick: () => editPin(u, actions) }, u.pin ? 'Change PIN' : 'Set PIN'), ' ',
        h('button', { class: 'btn danger', type: 'button', onclick: () => removeUser(u) }, 'Remove'),
        ownPassword, canReport);
      return h('tr', {},
        named,
        h('td', { 'data-label': 'Role' }, role),
        levelCell,
        stations,
        h('td', { class: 'small', 'data-label': 'Last signed in' }, u.signedInMs ? new Date(u.signedInMs).toLocaleString() : 'Never',
          // (Where from, as the access log has it.)
          u.signedInMs && u.signedInFrom ? h('div', { class: 'muted', title: 'Where they last signed in from' }, u.signedInFrom) : null),
        actions);
    })));
}
// Linked devices, and Who's tuning in? on them -----------------------------------------
const when = ms => new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
function renderDevices() {
  const panel = $('#devicesPanel');
  panel.hidden = !me.required || !linked;
  if (panel.hidden) return;
  $('#showOnDefault').value = linked.default;
  $('#devicesTable').replaceChildren(...(linked.devices.length ? [
    h('thead', {}, h('tr', {}, h('th', {}, 'Device'), h('th', {}, 'On its list'), h('th', {}, 'Linked'), h('th', {}, 'Last used'), h('th', {}, ''))),
    h('tbody', {}, ...linked.devices.map(d => h('tr', {},
      h('td', {}, h('strong', {}, d.name)),
      h('td', { class: 'small', 'data-label': 'On its list' }, d.people.length ? d.people.join(', ') : 'No one',
        // (Away from home, only who's on every device, signed in on it or was chosen for it.)
        d.peopleAway.join() !== d.people.join() ? h('div', { class: 'hint' }, `Away from home: ${d.peopleAway.join(', ') || 'no one'}`) : null),
      h('td', { class: 'small', 'data-label': 'Linked' }, d.trustedNetwork != null
        ? `By the trusted network ${d.trustedNetwork}, ${when(d.linkedMs)}`
        : d.linkedBy ? `By ${d.linkedBy}, ${when(d.linkedMs)}` : when(d.linkedMs)),
      h('td', { class: 'small', 'data-label': 'Last used' }, when(d.seenMs)),
      h('td', {}, h('button', { class: 'btn danger', type: 'button', onclick: async () => {
        if (!confirm(`Unlink ${d.name}? It will be signed out.`)) return;
        try { await api(`/api/access/devices/${d.id}`, { method: 'DELETE' }); toast(`${d.name} is unlinked`); }
        catch (err) { toast(err.message, true); }
        loadAccess();
      } }, 'Unlink')))))]
    : [h('tbody', {}, h('tr', {}, h('td', { class: 'muted small' }, 'None yet. A device is linked when someone signs in on it.')))]));
}
$('#showOnDefault').addEventListener('change', async e => {
  $('#showOnEveryoneSaid').textContent = '';
  try { await api('/api/access/devices/default', { method: 'PUT', body: { showOn: e.target.value } }); toast('Saved. New people start this way.'); }
  catch (err) { toast(err.message, true); }
  loadAccess();
});
// Who can sign in on a device by name: with a password or a PIN (as the
// server says: see devices.py).
const signsInByName = u => u.hasPassword || u.pin;
const peopleCount = n => n === 1 ? '1 person' : `${n} people`;
const andList = names => names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names.join('');
const keptSaid = kept => kept.length ? ` Kept as they were: ${andList(kept)} (no password or PIN).` : '';
const keepsSaid = kept => kept.length ? ` ${andList(kept)} will stay as they are (no password or PIN).` : '';
// Use for everyone: everyone already added shows where new people do.
$('#showOnEveryone').addEventListener('click', async () => {
  const select = $('#showOnDefault');
  const showOn = select.value, label = select.selectedOptions[0].textContent;
  const said = $('#showOnEveryoneSaid');
  let users;
  try { users = await api('/api/access/users'); } catch (err) { said.textContent = err.message; return; }
  const moving = users.filter(u => u.showOn !== showOn);
  const kept = moving.filter(u => !signsInByName(u)).map(u => u.name);  // (either way: see devices.py)
  const changing = moving.length - kept.length;
  if (!changing) { said.textContent = kept.length ? `Nothing to change.${keptSaid(kept)}` : `Everyone already shows on ${label}.`; return; }
  // (Picking themselves from a device's list isn't signing in on it.)
  const then = showOn === 'signed-in' ? ' Each shows on a device once they sign in on it with their password or an invite code.' : '';
  if (!confirm(`Change ${peopleCount(changing)} to ${label}?${then}${keepsSaid(kept)}`)) return;
  try {
    const got = await api('/api/access/devices/everyone', { method: 'POST', body: { showOn } });
    said.textContent = `Changed ${peopleCount(got.changed)} to ${label}.${keptSaid(got.kept)}`;
  } catch (err) { said.textContent = err.message; }
  loadAccess();
});
// Someone's devices: where they show, their PIN, and an invite code.
let devicesFor = null;
function openUserDevices(u) {
  devicesFor = u;
  $('#userDevicesTitle').textContent = `${u.name} on devices`;
  $('#userDevicesStatus').textContent = '';
  paintUserDevices();
  $('#userDevices').showModal();
}
async function savePicker(body, said) {
  const u = devicesFor;
  try { await api(`/api/access/users/${u.id}/picker`, { method: 'PUT', body }); }
  catch (err) { $('#userDevicesStatus').textContent = err.message; return false; }
  const [users, devices] = await Promise.all([api('/api/access/users'), api('/api/access/devices')]);
  linked = devices;
  devicesFor = users.find(x => x.id === u.id) || u;
  $('#userDevicesStatus').textContent = said;
  paintUserDevices();
  return true;
}
function paintUserDevices() {
  const u = devicesFor;
  const byName = signsInByName(u);
  const chosen = new Set((linked.chosen || {})[u.id] || []);
  const radio = (value, label, hint, disabled = false) => {
    const input = h('input', { type: 'radio', name: 'showOn', value, checked: u.showOn === value, disabled, onchange: () => {
      if (value === 'selected') { devicesFor = { ...u, showOn: 'selected' }; paintUserDevices(); return; }
      savePicker({ showOn: value }, 'Saved');
    } });
    return h('label', { class: 'choice' }, input, h('span', {}, h('strong', {}, label), h('span', { class: 'hint' }, hint)));
  };
  // The devices chosen for them: their only ones (Only devices you choose),
  // or the ones they're on away from home too (Every device at home).
  const boxes = linked.devices.map(d => [d.id, h('input', { type: 'checkbox', checked: chosen.has(d.id) })]);
  const pick = ['home', 'selected'].includes(u.showOn) ? h('div', { class: 'checks-col', style: 'margin-left:26px' },
    u.showOn === 'home' ? h('span', { class: 'small' }, 'Away from home too, on:') : null,
    ...(boxes.length ? boxes.map(([id, box]) => h('label', {}, box, ` ${linked.devices.find(d => d.id === id).name}`)) : [h('span', { class: 'muted small' }, 'No devices are linked yet.')]),
    boxes.length ? h('div', {}, h('button', { class: 'btn', type: 'button', onclick: () => savePicker({ showOn: u.showOn, devices: boxes.filter(([, b]) => b.checked).map(([id]) => id) }, 'Saved') }, 'Save devices')) : null) : null;
  const invite = h('div', { class: 'small' });
  const needsOne = ' Needs a password or a PIN.';
  $('#userDevicesBody').replaceChildren(...[
    h('div', { class: 'playback' },
      h('strong', {}, 'Show on'),
      radio('signed-in', 'Only devices they sign in on', byName ? ' They show on a device once they sign in on it.' : needsOne, !byName),
      radio('home', 'Every device at home', ' Away from home, only devices they signed in on or that you choose.'),
      u.showOn === 'home' ? pick : null,
      radio('all', 'Every device, at home and away', byName ? ' Even on a phone at a friend’s house.' : needsOne, !byName),
      radio('selected', 'Only devices you choose', ' At home and away, such as a family iPad.'),
      u.showOn === 'selected' ? pick : null),
    h('div', { class: 'playback' },
      h('strong', {}, 'PIN'),
      h('p', { class: 'hint', style: 'margin:0' }, u.pin
        ? 'Asked for when they pick themselves.'
        : u.role === 'admin' ? 'None: they give their password instead.' : 'None: anyone at a device they’re on can pick them.'),
      pinControls(u, savePicker)),
    byName ? h('div', { class: 'playback' },
      h('strong', {}, 'Invite code'),
      h('p', { class: 'hint', style: 'margin:0' }, 'To sign in on a device without a password, they choose Sign in on Who’s tuning in? and enter their name and this code. It works once, for 7 days.'),
      h('div', {}, h('button', { class: 'btn', type: 'button', onclick: async () => {
        try {
          const got = await api(`/api/access/users/${u.id}/invite`, { method: 'POST' });
          invite.replaceChildren(h('code', { style: 'font-size:18px' }, got.code), ` · works until ${when(got.expiresMs)}`);
        } catch (err) { $('#userDevicesStatus').textContent = err.message; }
      } }, 'Make an invite code')),
      invite) : null].filter(Boolean));
}
// Someone's PIN: a box for a new one, Set PIN or Change PIN, and Remove PIN
// (in the Devices dialog, and in the Users table). `save(body, said)` sends
// it (see PUT /api/access/users/{id}/picker) and shows `said`, or why not.
function pinControls(u, save, extra = null) {
  const pin = h('input', { type: 'text', inputmode: 'numeric', pattern: '[0-9]{4}', maxlength: 4, placeholder: '4 digits', autocomplete: 'off', 'aria-label': `New PIN for ${u.name}`,
    onkeydown: e => { if (e.key === 'Enter') { e.preventDefault(); save({ pin: pin.value.trim() }, 'PIN saved'); } } });
  return h('div', { class: 'scan-set pin-set' }, pin,
    h('button', { class: 'btn', type: 'button', onclick: () => save({ pin: pin.value.trim() }, 'PIN saved') }, u.pin ? 'Change PIN' : 'Set PIN'),
    u.pin ? h('button', { class: 'btn', type: 'button', onclick: () => save({ pin: '' }, 'PIN removed') }, 'Remove PIN') : null,
    extra);
}
// In the Users table: someone's PIN, in place of their buttons until it's
// saved (or Cancel). What the server says against it shows below.
function editPin(u, cell) {
  const said = h('p', { class: 'hint pin-said', role: 'status' });
  const save = async (body, done) => {
    try { await api(`/api/access/users/${u.id}/picker`, { method: 'PUT', body }); }
    catch (err) { said.textContent = err.message; return false; }
    toast(`${done} for ${u.name}`);
    loadAccess();
    return true;
  };
  const controls = pinControls(u, save, h('button', { class: 'btn', type: 'button', onclick: loadAccess }, 'Cancel'));
  controls.addEventListener('keydown', e => { if (e.key === 'Escape') loadAccess(); });
  cell.replaceChildren(controls, said);
  controls.querySelector('input').focus();
}
const closeUserDevices = () => { $('#userDevices').close(); devicesFor = null; loadAccess(); };
$('#closeUserDevices').addEventListener('click', closeUserDevices);
$('#doneUserDevices').addEventListener('click', closeUserDevices);
