// Viewing Levels.
// Viewing Levels ----------------------------------------------------------------------
const levelLimited = lv => lv.movieAge != null || lv.tvAge != null || !lv.unrated || lv.libraries != null;
const ratingName = (list, age) => age == null ? 'No limit' : (list.find(([a]) => a === age)?.[1] || `Ages ${age} and up`);
function levelSelect(value, attrs = {}) {
  const select = h('select', attrs, ...(viewing?.levels || []).map(lv => h('option', { value: String(lv.id) }, lv.name)));
  select.value = String(value);
  return select;
}
let plexLibraries = null;  // (for choosing a level's libraries)
function renderViewing() {
  const panel = $('#viewingPanel');
  panel.hidden = !me.required || !viewing;
  if (panel.hidden) return;
  const body = $('#viewingBody');
  const limited = viewing.levels.filter(levelLimited).length;
  $('#viewingSum').textContent = `${plural(viewing.levels.length, 'level')}${limited ? `, ${limited} with limits` : ''}`;
  if (body.dataset.editing) return;  // (not while one is being changed)
  const libraryNames = new Map((plexLibraries || []).map(l => [l.key, l.title]));
  const librariesText = lv => lv.libraries == null ? 'All'
    : lv.libraries.length ? lv.libraries.map(k => libraryNames.get(k) || `Library ${k}`).join(', ') : 'None';
  const table = h('table', { class: 'users' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Level'), h('th', {}, 'Movies up to'), h('th', {}, 'TV up to'), h('th', {}, 'Unrated'), h('th', {}, 'Libraries'), h('th', {}, 'People'), h('th', {}, ''))),
    h('tbody', {}, ...viewing.levels.map(lv => h('tr', {},
      h('td', {}, h('strong', {}, lv.name)),
      h('td', { 'data-label': 'Movies up to' }, ratingName(viewing.movieRatings, lv.movieAge)),
      h('td', { 'data-label': 'TV up to' }, ratingName(viewing.tvRatings, lv.tvAge)),
      h('td', { 'data-label': 'Unrated' }, lv.unrated ? 'Shown' : 'Hidden'),
      h('td', { class: 'small', 'data-label': 'Libraries' }, librariesText(lv)),
      h('td', { 'data-label': 'People' }, String(lv.users)),
      h('td', {},
        lv.builtin === 'unrestricted' ? h('span', { class: 'hint' }, 'Shows everything') : [
        h('button', { class: 'btn', type: 'button', onclick: () => editLevel(lv) }, 'Edit'),
        ' ', h('button', { class: 'btn danger', type: 'button', onclick: async () => {
          if (!confirm(`Remove the Viewing Level ${lv.name}?`)) return;
          try { await api(`/api/access/levels/${lv.id}`, { method: 'DELETE' }); toast(`${lv.name} removed`); }
          catch (err) { toast(err.message, true); }
          loadAccess();
        } }, 'Remove')])))));
  body.replaceChildren(
    h('p', { style: 'margin:0' }, 'A Viewing Level says what its people can see in StationPlay’s apps and on this page: movies and shows up to a rating, whether unrated ones are shown, and which libraries. Everyone starts on Unrestricted, which shows everything and stays as it is. Teen, Kid and Young Child are there to start from: rename them, change them or remove them, and add as many levels of your own as you need, such as “Adults” with no R-rated movies or unrated titles. Admins always see everything.'),
    h('div', { class: 'limit-note' }, h('strong', {}, 'How it works'),
      h('ul', {},
        h('li', {}, h('strong', {}, 'Stations are all or nothing. '), 'Everyone watching a station sees the same stream, so a station is shown only if everything it plays is within the level. Choose Stations beside someone’s name to allow or block one for them anyway.'),
        h('li', {}, h('strong', {}, 'Watching only. '), 'People on a level with limits watch what they can see, but can’t make stations.'),
        h('li', {}, h('strong', {}, 'Plex and other apps. '), 'Plex, Jellyfin and IPTV apps don’t say who’s watching, so they show every station. To keep stations from some people in Plex, use Block stations for some Plex users, below.'))),
    table,
    h('div', {}, h('button', { class: 'btn', type: 'button', onclick: () => editLevel(null) }, 'Add a level')));
}
async function editLevel(lv) {
  const body = $('#viewingBody');
  if (!plexLibraries) {
    try { plexLibraries = (await api('/api/libraries')).filter(l => l.type === 'show' || l.type === 'movie'); }
    catch { plexLibraries = []; }
  }
  body.dataset.editing = '1';
  const name = h('input', { type: 'text', maxlength: 40, value: lv?.name || '', placeholder: 'Grandparents', autocomplete: 'off', 'aria-label': 'Name' });
  const ratingSelect = (list, age, label) => {
    const select = h('select', { 'aria-label': label }, h('option', { value: '' }, 'No limit'), ...list.map(([a, n]) => h('option', { value: String(a) }, n)));
    select.value = age == null ? '' : String(age);
    if (age != null && !list.some(([a]) => a === age)) select.append(h('option', { value: String(age), selected: true }, `Ages ${age} and up`));
    return select;
  };
  const movies = ratingSelect(viewing.movieRatings, lv ? lv.movieAge : 13, 'Movies up to');
  const tv = ratingSelect(viewing.tvRatings, lv ? lv.tvAge : 14, 'TV up to');
  const unrated = h('select', { 'aria-label': 'Unrated titles' }, h('option', { value: 'shown' }, 'Shown'), h('option', { value: 'hidden' }, 'Hidden'));
  unrated.value = lv && lv.unrated ? 'shown' : (lv ? 'hidden' : 'hidden');
  const every = h('input', { type: 'radio', name: 'levelLibraries', checked: !lv || lv.libraries == null });
  const some = h('input', { type: 'radio', name: 'levelLibraries', checked: !!lv && lv.libraries != null });
  const boxes = plexLibraries.map(l => [l.key, h('input', { type: 'checkbox', checked: !!lv?.libraries?.includes(l.key) })]);
  const pick = h('div', { class: 'checks-col' }, ...boxes.map(([key, box]) => h('label', {}, box, ` ${plexLibraries.find(l => l.key === key).title}`)));
  const showPick = () => { pick.hidden = !some.checked; };
  every.addEventListener('change', showPick);
  some.addEventListener('change', showPick);
  showPick();
  const result = h('span', { class: 'hint', role: 'alert' });
  const done = () => { delete body.dataset.editing; renderViewing(); };
  const save = async () => {
    const chosen = {
      name: name.value.trim(),
      movieAge: movies.value === '' ? null : Number(movies.value),
      tvAge: tv.value === '' ? null : Number(tv.value),
      unrated: unrated.value === 'shown',
      libraries: some.checked ? boxes.filter(([, b]) => b.checked).map(([k]) => k) : null,
    };
    try {
      await api(lv ? `/api/access/levels/${lv.id}` : '/api/access/levels', { method: lv ? 'PUT' : 'POST', body: chosen });
    } catch (err) { result.textContent = err.message; return; }
    toast(lv ? `${chosen.name} saved` : `${chosen.name} added`);
    delete body.dataset.editing;
    loadAccess();
  };
  const row = (label, control, hint) => h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, label), h('div', { class: 'opt-ctl' }, control, hint ? h('span', { class: 'hint' }, hint) : null));
  body.replaceChildren(h('div', { class: 'playback level-edit' },
    h('strong', {}, lv ? `Edit ${lv.name}` : 'Add a level'),
    row('Name', name),
    row('Movies up to', movies),
    row('TV up to', tv, 'An episode counts as its show’s rating, or its own if that’s stricter.'),
    row('Unrated titles', unrated, 'Titles with no rating in Plex.'),
    row('Libraries', h('div', {}, h('label', {}, every, ' Every library'), ' ', h('label', {}, some, ' Only these:'), pick)),
    h('div', { class: 'scan-set' },
      h('button', { class: 'btn primary', type: 'button', onclick: save }, lv ? 'Save' : 'Add'),
      h('button', { class: 'btn', type: 'button', onclick: done }, 'Cancel'),
      result)));
  name.focus();
}
// A person's stations: as their level says, or allowed or blocked for them.
let stationsFor = null;
async function openUserStations(u) {
  let got;
  try { got = await api(`/api/access/users/${u.id}/stations`); }
  catch (err) { toast(err.message, true); return; }
  stationsFor = { user: u, picks: new Map() };
  $('#userStationsTitle').textContent = `${u.name}’s stations`;
  $('#userStationsStatus').textContent = '';
  const said = s => s.chosen === 'allowed' ? `Allowed for ${u.name}.${s.why ? ` (${got.level} wouldn’t show it: ${s.why.toLowerCase()}.)` : ''}`
    : s.chosen === 'blocked' ? `Blocked for ${u.name}.`
    : s.levelSees ? `Shown: it’s within ${got.level}.` : `Hidden: ${s.why.charAt(0).toLowerCase()}${s.why.slice(1)}.`;
  $('#userStationsBody').replaceChildren(
    h('p', { style: 'margin:0' }, `${u.name} is on ${got.level}. A station is shown or hidden as ${got.level} says, unless you allow or block it for ${u.name} here.`),
    got.stations.length ? h('table', { class: 'users' },
      h('tbody', {}, ...got.stations.map(st => {
        const hint = h('span', { class: 'hint' }, said(st));
        const select = h('select', { 'aria-label': `Station ${st.number}`, onchange: e => {
          stationsFor.picks.set(st.id, e.target.value);
          hint.textContent = said({ ...st, chosen: e.target.value });
        } }, h('option', { value: 'level' }, `As ${got.level} says`), h('option', { value: 'allowed' }, 'Allowed'), h('option', { value: 'blocked' }, 'Blocked'));
        select.value = st.chosen;
        stationsFor.picks.set(st.id, st.chosen);
        return h('tr', {},
          h('td', {}, h('strong', {}, st.number), ` ${st.name}`),
          h('td', {}, select, h('div', {}, hint)));
      }))) : h('p', { class: 'muted', style: 'margin:0' }, 'There are no stations yet.'));
  $('#userStations').showModal();
}
const closeUserStations = () => { $('#userStations').close(); stationsFor = null; };
$('#closeUserStations').addEventListener('click', closeUserStations);
$('#cancelUserStations').addEventListener('click', closeUserStations);
$('#saveUserStations').addEventListener('click', async () => {
  if (!stationsFor) return;
  const stations = {};
  for (const [id, pick] of stationsFor.picks) if (pick !== 'level') stations[id] = pick === 'allowed';
  try { await api(`/api/access/users/${stationsFor.user.id}/viewing`, { method: 'PUT', body: { stations } }); }
  catch (err) { $('#userStationsStatus').textContent = err.message; return; }
  toast(`${stationsFor.user.name}’s stations saved`);
  closeUserStations();
  loadAccess();
});
// A new name for someone (an Admin's, themselves included): signing in takes
// it from then on, and everything of theirs stays theirs.
function renameUser(u, cell) {
  const input = h('input', { type: 'text', value: u.name, maxlength: 40, autocomplete: 'off', 'aria-label': `New name for ${u.name}` });
  const save = async () => {
    const name = input.value.trim();
    if (!name || name === u.name) { loadAccess(); return; }
    try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { name } }); }
    catch (err) { toast(err.message, true); return; }
    toast(`${u.name} is now ${name}. They sign in as ${name} from now on.`);
    if (u.id === me.user?.id) await loadMe();
    loadAccess();
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') loadAccess();
  });
  cell.replaceChildren(h('div', { class: 'inline-add' }, input,
    h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'),
    h('button', { class: 'btn', type: 'button', onclick: loadAccess }, 'Cancel')));
  input.focus();
  input.select();
}
function newPassword(u, cell) {
  const input = h('input', { type: 'password', minlength: ACCESS.passwordMin, maxlength: ACCESS.passwordMax, autocomplete: 'new-password', placeholder: 'New password', 'aria-label': `New password for ${u.name}` });
  const save = async () => {
    try { await api(`/api/access/users/${u.id}`, { method: 'PUT', body: { password: input.value } }); toast(`${u.name}’s password was changed, and they’re signed out everywhere`); loadAccess(); }
    catch (err) { toast(err.message, true); }
  };
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  cell.replaceChildren(h('div', { class: 'inline-add' }, input,
    h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'),
    h('button', { class: 'btn', type: 'button', onclick: loadAccess }, 'Cancel')));
  input.focus();
}
async function removeUser(u, count) {
  const last = count === 1;
  if (!confirm(last
    ? `Remove ${u.name}? They’re the last user, so sign-in turns off and anyone on your network who can reach StationPlay can use it.`
    : `Remove ${u.name}? They won’t be able to sign in anymore. Stations they made stay, and only Admins can change them.`)) return;
  try { await api(`/api/access/users/${u.id}`, { method: 'DELETE' }); toast(`${u.name} removed`); }
  catch (err) { toast(err.message, true); return; }
  await loadMe();
  if (me.required && !me.user) { showSignIn(); return; }
  loadAccess();
  loadChannels();
}
$('#addUserForm').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('#newUserName').value.trim();
  let added;
  try {
    const pin = $('#newUserPin').value.trim();
    added = await api('/api/access/users', { method: 'POST', body: { name, password: $('#newUserPassword').value, role: $('#newUserRole').value, maxStations: limitOf($('#newUserStations')), ...(pin ? { pin } : {}) } });
  } catch (err) { $('#addUserHint').textContent = err.message; return; }
  $('#addUserForm').reset();
  $('#newUserStations').value = String(ACCESS.newUserStations);
  $('#addUserHint').textContent = '';
  const first = !me.required;
  await loadMe();
  // Someone who can't sign in by name starts on no device (an Admin chooses
  // theirs); with only a passcode, their first sign-in on a device takes an
  // invite code.
  const nowhere = added.showOn === 'selected' && !added.hasPassword && !added.pin;
  const invited = added.showOn === 'signed-in' && !added.hasPassword;
  toast(first ? `Sign-in is on, and you’re signed in as ${name}`
    : nowhere ? `${name} is added. With no password or passcode, they show on no device until you choose one in Devices.`
    : invited ? `${name} is added. To sign in on a device, they need an invite code: see Devices.` : `${name} is added`);
  loadAccess();
  loadChannels();
});
