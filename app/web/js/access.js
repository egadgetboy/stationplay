// Signing in, Admins and Users, and linked devices.
// Signing in (see access.py) ------------------------------------------------------
// Who's signed in, as tapiOca says (`known`: it has said, since the page
// opened). Until it has, and if it can't be asked, nothing only an Admin may
// use is shown, not even for a moment (1.38.0, the owner, October 17: the
// Admin tabs "shouldn't flash for a second for a restricted [non Admin]
// user at all"). Signing in may be off (anyone using the page can do
// everything) or on, as an Admin or a User.
let me = { known: false, required: true, user: null };
// (An Admin signed in for watching only, as a trusted network or a PIN may
// sign them in, has no Admin tools: tapiOca says, adminTools. See
// access.STEP_UP on the server.)
const isAdmin = () => me.known && (!me.required || me.user?.adminTools === true);
const roleName = role => role === 'admin' ? 'Admin' : 'User';
const aRole = role => role === 'admin' ? 'an Admin' : 'a User';
const signedOut = () => !$('#signinView').hidden;
async function loadMe() {
  me = { ...await api('/api/access/me'), known: true };
  signOutAt(me.idleLeftMs);
  showForMe();
  $('#userPill').hidden = !me.user;
  if (me.user) $('#userPill').firstElementChild.textContent = `${me.user.name} · ${roleName(me.user.role)}${me.user.watching ? ', watching' : ''}`;
  showWatching();
  renderRoom();
}
// An Admin signed in for watching: said, with the way to their Admin tools
// (1.38.0: before, the Admin tabs went with no word of why).
function showWatching() {
  const on = me.known && !!me.user?.watching;
  $('#watchingNote').hidden = !on;
  if (!on) return;
  $('#watchingWhy').textContent = me.user.byNetwork
    ? 'This network signed you in for watching. Admin tasks need your password.'
    : me.outside
      ? 'Your PIN signs you in for watching away from home. Admin tasks need your password.'
      : 'This sign-in is for watching. Admin tasks need your password.';
}
$('#watchingSignIn').addEventListener('click', () => $('#signOut').click());
// The Admin tabs and the footer's Setup, as `me` allows (and off an Admin
// tab that's no longer allowed).
function showForMe() {
  document.querySelectorAll('.tab.admin').forEach(t => { t.hidden = !isAdmin(); });
  if (!FOR_EVERYONE.includes(currentTab) && !isAdmin()) showTab('stations');
  $('#footSetupWrap').hidden = !isAdmin();
}
// The page's first ask: true once tapiOca has said who's signed in, and the
// page shows (but for the sign-in screen's turn: someone signed out). If it
// couldn't be asked, the page says so, with Try again, and shows nothing
// else: never as if signing in were off.
async function firstMe() {
  try {
    await loadMe();
  } catch {
    if (signedOut()) return false;  // (a 401: the sign-in screen shows)
    $('.wrap').hidden = false;
    for (const sel of ['.tabrow', ...TABS.map(t => '#tab-' + t)]) $(sel).hidden = true;
    $('#meProblem').hidden = false;
    return false;
  }
  if (!(me.required && !me.user)) $('.wrap').hidden = false;
  return true;
}
// Back to a page the browser kept (Back, or a tab it put to sleep): as for
// someone signed out until tapiOca says again, since someone may have
// signed out or lost Admin tools meanwhile.
addEventListener('pageshow', async e => {
  if (!e.persisted || signedOut()) return;
  const was = currentTab;
  me = { ...me, known: false };
  showForMe();
  if (!await firstMe()) return;
  if (me.required && !me.user) { showSignIn(me.idle); return; }
  if (was !== currentTab && isAdmin()) showTab(was);
});
$('#meRetry').addEventListener('click', () => location.reload());
// Signed out (the sign-in screen's turn): nothing the sign-in before had
// stays, until tapiOca says who's signed in again (the cold audit of 1.38.0:
// a new role ends a sign-in, and its Admin tabs showed on).
function forgetMe() {
  me = { ...me, known: false, user: null };
  showForMe();
  $('#watchingNote').hidden = true;
}
// `idle`: signed out after an hour without activity.
function showSignIn(idle = false) {
  if (signedOut()) return;
  forgetMe();
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
  signInBy(null);
  showPeople([]);
  // (From the internet before signing in is on, there's nothing to sign in
  // to: the owner's sentence alone. The fourth audit of 1.35.0.)
  if (me.notSetUp) for (const id of ['#signinByPassword', '#signinByPin', '#signinGo']) $(id).hidden = true;
  else { $('#signinGo').hidden = false; $('#signinName').focus(); }
  // On a trusted network that signs in as someone: who (see trusted.js).
  // Otherwise, at home: Who's signing in? (see showPeople).
  if (me.notSetUp) return;
  if (!trustedSignIn(me.trusted, idle)) showPeople(me.people || []);
  // (Asked again, in case the page's first answer never came, or is old.)
  api('/api/access/me').then(now => {
    if (!signedOut() || now.user || now.notSetUp) return;
    if (now.outside) { $('#signinWhere').hidden = false; $('#signinHome').hidden = true; }
    if (!trustedSignIn(now.trusted, idle) && !pickedPerson) showPeople(now.people || []);
  }).catch(() => {});
}
// Who's signing in?: the Admins who signed in on this browser with their
// password, latest first: never a User, and never anyone who hasn't (1.38.0,
// the owner, October 17). Each one's PIN, in Light sign-in, or their password.
// With only one, their PIN (or password) is asked at once (as 1.37.0 asked it).
let people = [];
function showPeople(list) {
  people = list;
  const on = list.length > 0;
  $('#signinTrusted').hidden = !on;
  $('#signinContinue').hidden = true;
  $('#signinSomeoneElse').hidden = !on;
  if (!on) { $('#signinPeople').replaceChildren(); return; }
  $('#signinTrustedTitle').textContent = 'Who’s signing in?';
  $('#signinHome').hidden = true;
  $('#signinPeople').replaceChildren(...list.map(p => h('button', {
    class: 'who', type: 'button', role: 'listitem', 'aria-pressed': 'false', 'data-id': String(p.id),
    'aria-label': `${p.name}, ${p.pin ? 'PIN' : 'password'}`, onclick: () => signInBy(p),
  }, h('span', { class: 'face', 'aria-hidden': 'true' }, (p.name[0] || '?').toUpperCase()),
    h('span', { class: 'who-name' }, p.name),
    h('span', { class: 'who-note', 'aria-hidden': 'true' }, p.pin ? 'PIN' : 'Password'))));
  signInBy(list.length === 1 ? list[0] : null, !on);
}
// Signing in as `pickedPerson` (one of Who's signing in?, by their PIN or their
// password), or (null) with a name and password; `asking`: the name and
// password box shows even beside Who's signing in?.
let pickedPerson = null;
function signInBy(person, asking = true) {
  pickedPerson = person;
  for (const b of document.querySelectorAll('#signinPeople .who')) b.setAttribute('aria-pressed', String(!!person && b.dataset.id === String(person.id)));
  const byPin = !!person?.pin;
  $('#pinForm').hidden = !byPin;
  $('#signinForm').hidden = byPin || (!person && !asking && people.length > 0);
  $('#signinName').closest('.field').hidden = !!person;
  $('#signinOther').hidden = !byPin;
  $('#signinForget').hidden = !person;
  $('#signinPin').required = byPin;
  $('#signinPin').value = '';
  $('#signinPassword').value = '';
  $('#signinStatus').textContent = '';
  $('#signinName').value = person ? person.name : '';
  if (byPin) {
    $('#signinPinLabel').textContent = `PIN for ${person.name}`;
    $('#signinPin').focus();
  } else if (person) $('#signinPassword').focus();
}
// Their own password instead of the PIN: their name's already there.
$('#signinOther').addEventListener('click', () => {
  const person = pickedPerson;
  signInBy(person ? { ...person, pin: false } : null);
});
// Anyone else, by name and password (a User too: only Admins are listed).
$('#signinSomeoneElse').addEventListener('click', () => {
  signInBy(null);
  $('#signinName').focus();
});
// Remove from this browser: that Admin is no longer on its sign-in screen
// (their password brings them back). Sign out only ends the sign-in.
$('#signinForget').addEventListener('click', async () => {
  const person = pickedPerson;
  if (!person) return;
  try { await api('/api/access/browser/forget', { method: 'POST', body: { id: person.id } }); }
  catch (err) { $('#signinStatus').textContent = err.message; return; }
  showPeople(people.filter(p => p.id !== person.id));
  if (!people.length) signInBy(null);
  $('#signinStatus').textContent = `${person.name} is no longer on this browser’s sign-in screen.`;
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
    await api('/api/access/sign-in', { method: 'POST', body: { name: $('#signinName').value, password: $('#signinPassword').value } });
  } catch (err) {
    $('#signinStatus').textContent = err.message;
    $('#signinPassword').value = '';
    return;
  }
  await signedInNow();
});
$('#pinForm').addEventListener('submit', async e => {
  e.preventDefault();
  const person = pickedPerson;
  try {
    await api('/api/access/pin-sign-in', { method: 'POST', body: { id: person?.id, pin: $('#signinPin').value } });
  } catch (err) {
    $('#signinStatus').textContent = err.message;
    $('#signinPin').value = '';
    // (Too many wrong PINs on this browser: their password now.)
    if (/wrong PINs on this browser/.test(err.message) && person) signInBy({ ...person, pin: false });
    return;
  }
  await signedInNow();
});
// Signed in, however it was: the page, as that person sees it, once
// tapiOca has said who that is (never the sign-in before's for a moment).
async function signedInNow() {
  try { sessionStorage.removeItem('tapioca.signedOut'); } catch {}
  pickedPerson = null;
  $('#signinPassword').value = '';
  $('#signinPin').value = '';
  forgetMe();
  try { await loadMe(); } catch (err) {
    if (err.status !== 401) $('#signinStatus').textContent = 'tapiOca couldn’t check who’s signed in. Try again.';
    return;
  }
  $('#signinView').hidden = true;
  $('.wrap').hidden = false;
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
  document.querySelectorAll('#pwCurrent, #pwNew, #pwChange').forEach(el => { el.disabled = !may; });
  $('#accountStatus').textContent = !may
    ? 'An Admin has turned off changing your own password. Ask an Admin if it needs changing.'
    : me.user.byNetwork
      ? `This network signed you in without your password, for watching.${me.user.role === 'admin' ? ' For Admin tasks, sign out, then choose Sign in with a password.' : ''}`
      : `At least ${ACCESS.passwordMin} characters: a few words together work well. Changing your password signs you out of other browsers and apps.`;
  // An Admin's Full or Light sign-in, with their Admin tools (1.38.0).
  const mode = me.user.adminSignIn;
  $('#signinModeForm').hidden = !mode || !isAdmin();
  $('#signinModeForm').reset();
  for (const r of document.querySelectorAll('[name=adminSignIn]')) r.checked = r.value === mode;
  $('#modeStatus').textContent = '';
  $('#account').showModal();
});
$('#signinModeForm').addEventListener('submit', async e => {
  e.preventDefault();
  const how = document.querySelector('[name=adminSignIn]:checked')?.value;
  try {
    await api('/api/access/me/sign-in', { method: 'PUT', body: { how, password: $('#modePassword').value } });
  } catch (err) { $('#modeStatus').textContent = err.message; $('#modePassword').value = ''; return; }
  $('#modePassword').value = '';
  await loadMe();
  // (Light needs a PIN: without one, it's said how to get one. The cold audit of 1.38.0.)
  $('#modeStatus').textContent = how !== 'light'
    ? 'Saved. Your password signs you in every time.'
    : me.user?.pin
      ? 'Saved. Your PIN signs you in here from now on, at home.'
      : 'Saved. Light needs a PIN: set yours on the Access tab.';
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
  // (What a password asks, and what having none means: the owner, October
  // 14, made a User with neither and found they couldn't sign in.)
  $('#addUserHint').textContent = `A password needs at least ${ACCESS.passwordMin} characters. A few words together work well.`
    + (user && me.required ? ' A User with no password can only be picked at home, on Who’s tuning in? in the apps or Who’s signing in? on this page, or signed in on a new device with an invite code. Their PIN, if they have one, is asked when they pick themselves.' : '');
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
      // (And their own PIN, on its own: the owner, October 14, 1.36.2.)
      const ownPin = h('label', { class: 'own-password', title: admin ? 'An Admin can always change their own' : null },
        h('input', { type: 'checkbox', checked: admin || u.canChangePin !== false, disabled: admin, onchange: async e => {
          const on = e.target.checked;
          try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { canChangePin: on } }); toast(on ? `${u.name} can change their own PIN` : `${u.name} can’t change their own PIN now`); }
          catch (err) { toast(err.message, true); }
          loadAccess();
        } }), 'Can change their own PIN');
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
        ownPassword, ownPin, canReport);
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
  $('#devicesTable').replaceChildren(...(linked.devices.length ? [
    h('thead', {}, h('tr', {}, h('th', {}, 'Device'), h('th', {}, 'On its list'), h('th', {}, 'Linked'), h('th', {}, 'Last used'), h('th', {}, ''))),
    h('tbody', {}, ...linked.devices.map(d => h('tr', {},
      h('td', {}, h('strong', {}, d.name)),
      h('td', { class: 'small', 'data-label': 'On its list' }, d.people.length ? d.people.join(', ') : 'No one',
        // (Away from home, only those who signed in on it and have a password or PIN.)
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
// Who can sign in on a device by name: with a password or a PIN (as the
// server says: see devices.py).
const signsInByName = u => u.hasPassword || u.pin;
const andList = names => names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names.join('');
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
// From 1.38.0 (the owner, October 17) someone is on a device's Who's tuning
// in? only once they sign in on it themselves: Show on and the devices an
// Admin chose are kept, for going back to 1.37.1, but list no one.
function paintUserDevices() {
  const u = devicesFor;
  const byName = signsInByName(u);
  const on = (linked.devices || []).filter(d => d.people.includes(u.name)).map(d => d.name);
  const invite = h('div', { class: 'small' });
  $('#userDevicesBody').replaceChildren(...[
    h('div', { class: 'playback' },
      h('strong', {}, 'On devices'),
      h('p', { class: 'hint', style: 'margin:0' }, on.length ? `On ${andList(on)}.` : 'On no device yet.'),
      h('p', { class: 'hint', style: 'margin:0' }, byName
        ? 'They’re on a device once they sign in on it with their password or an invite code. They can take themselves off one there.'
        : 'With no password or PIN, they’re on a device once it’s signed in for them with an invite code, and then only at home, where anyone there can pick them.')),
    h('div', { class: 'playback' },
      h('strong', {}, 'PIN'),
      h('p', { class: 'hint', style: 'margin:0' }, u.pin
        ? 'Asked for when they pick themselves.'
        : u.role === 'admin' ? 'None: they give their password instead.' : 'None: anyone at a device they’re on can pick them.'),
      pinControls(u, savePicker)),
    h('div', { class: 'playback' },
      h('strong', {}, 'Invite code'),
      h('p', { class: 'hint', style: 'margin:0' }, 'To sign in on a device without a password, choose Sign in on its Who’s tuning in?, then enter their name and this code. It works once, for 7 days.'),
      h('div', {}, h('button', { class: 'btn', type: 'button', onclick: async () => {
        try {
          const got = await api(`/api/access/users/${u.id}/invite`, { method: 'POST' });
          invite.replaceChildren(h('code', { style: 'font-size:18px' }, got.code), ` · works until ${when(got.expiresMs)}`);
        } catch (err) { $('#userDevicesStatus').textContent = err.message; }
      } }, 'Make an invite code')),
      invite)]);
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
