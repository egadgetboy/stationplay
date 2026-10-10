// StationPlay's page: Shared helpers ($, h, api, toast, notice...), and the tabs.
const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
};
// "station" or "stations"; "1 station" or "3 stations".
const noun = (n, word) => `${word}${n === 1 ? '' : 's'}`;
const plural = (n, word) => `${Number.isFinite(n) ? n.toLocaleString() : n} ${noun(n, word)}`;

// opts.body is sent as JSON; opts.raw (a file) as it is. opts.blob: the answer is a file.
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    ...opts,
    body: opts.raw ?? (opts.body ? JSON.stringify(opts.body) : undefined),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg);
    } catch {}
    // (A wrong password when signing in is a 401 too.)
    if (res.status === 401 && path !== '/api/access/sign-in') showSignIn(msg === ACCESS.idleSignedOut);
    throw Object.assign(new Error(msg), { status: res.status });
  }
  // (Nothing to say: 204, or a 202 with no body.)
  if (res.status === 204 || res.headers.get('content-length') === '0') return null;
  return opts.blob ? res.blob() : res.json();
}

let toastTimer;
function toast(msg, error = false) {
  // (Not over the sign-in page, which says what's needed: a problem then is
  // only something the page was doing as it was signed out.)
  if (error && signedOut()) return;
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (error ? ' error' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  // Long enough to read: 3 seconds (6 for a problem), more for a long one.
  toastTimer = setTimeout(() => (t.hidden = true), Math.min(10000, Math.max(error ? 6000 : 3000, msg.length * 70)));
}
// A message that stays until it's cleared with OK.
function notice(title, ...body) {
  $('#noticeTitle').textContent = title;
  $('#noticeBody').replaceChildren(...body.filter(Boolean));
  if (!$('#notice').open) $('#notice').showModal();
  $('#noticeOk').focus();
}
// After making stations: which, how to add them to Plex (where they're
// called channels), and what couldn't be made.
function madeNotice(made, problems = []) {
  const one = made.length === 1;
  notice(one ? `Station ${made[0].number} is on the air` : `${made.length} new stations are on the air`,
    h('ul', { class: 'steps' }, ...made.map(s => h('li', {}, h('strong', {}, String(s.number)), ` ${s.name}`))),
    h('p', { style: 'margin:0' }, `To add ${one ? 'it' : 'them'} to Plex, go to `, h('em', {}, 'Settings → Live TV & DVR → your tuner → Scan for channels'),
      ' in Plex (Plex calls stations “channels”). If you haven’t added StationPlay to Plex yet, the Add to Plex tab shows how.'),
    problems.length ? h('div', { class: 'notice-bad' }, h('strong', {}, 'Couldn’t make these'),
      h('ul', { class: 'steps' }, ...problems.map(p => h('li', {}, p)))) : null);
}
// A message with an Undo button, shown until it's too late to undo.
function toastWithUndo(msg, undo) {
  const t = $('#toast');
  t.replaceChildren(msg, h('button', { type: 'button', class: 'undo', onclick: () => { t.hidden = true; undo(); } }, 'Undo'));
  t.className = 'toast';
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), UNDO_S * 1000);
}

const fmtDur = ms => {
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min`;
  const hrs = Math.floor(m / 60), rem = m % 60;
  if (hrs < 48) return rem ? `${hrs} hr ${rem} min` : `${hrs} hr`;
  return `${Math.round(hrs / 24)} days`;
};
const sxe = it => `S${String(it.season ?? 0).padStart(2, '0')}E${String(it.episode ?? 0).padStart(2, '0')}`;
const epLabel = it => it.show ? `${it.show} · ${sxe(it)} “${it.title}”` : `${it.title}${it.year ? ` (${it.year})` : ''}`;
const guideLabel = it => epLabel(it) + (it.show && it.year ? ` · ${it.year}` : '');
// Marks the one button of a group (data-<attr>="...") that's chosen.
// Buttons that open a (hidden) file chooser: a real button, so it works
// from the keyboard too.
document.querySelectorAll('[data-choose-file]').forEach(b => b.addEventListener('click', () => $(`#${b.dataset.chooseFile}`).click()));
const pressOne = (attr, value) => document.querySelectorAll(`[data-${attr}]`)
  .forEach(b => b.setAttribute('aria-pressed', String(b.dataset[attr] === value)));

// Tabs ---------------------------------------------------------------------
document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
let currentTab = 'stations';
const TABS = ['stations', 'setup', 'access', 'stats', 'logs', 'broken'];
const FOR_EVERYONE = ['stations', 'stats'];
function showTab(name) {
  if (!TABS.includes(name) || (!FOR_EVERYONE.includes(name) && !isAdmin())) name = 'stations';
  currentTab = name;
  document.querySelectorAll('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === name)));
  for (const id of TABS) $('#tab-' + id).hidden = id !== name;
  if (name === 'broken') { loadArr().then(loadBroken); loadScan(); loadReportSettings(); }
  if (name === 'logs') { loadLogs(true); loadProblems(); loadNotify(); }
  if (name === 'setup') { loadBackups(); renderPlaybackPanel(); }
  if (name === 'stats') { loadStats(); loadNow(); }
  if (name === 'access') { loadAccess(); loadApps(); loadLimits(); loadAway(); loadAppLimits(); loadAppLibraries(); loadApiTokens(); }
  history.replaceState(null, '', '#' + name);
}

// Copying works on a plain http:// address too, where browsers don't offer
// the clipboard API.
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch {}
  }
  const area = h('textarea', { style: 'position:fixed;top:0;left:0;opacity:0', readonly: true });
  area.value = text;
  document.body.append(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch {}
  area.remove();
  return ok;
}
