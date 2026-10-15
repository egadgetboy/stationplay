// The page's shared helpers ($, h, api, toast, notice...), and its tabs.
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
// Whether tapiOca uses Plex (status.js's status: an Admin's plexUsed, a
// User's plex.used). Without it, nothing's said about Plex (1.35.0).
const plexUsed = () => (status?.plexUsed ?? status?.plex?.used) !== false;

// opts.body is sent as JSON; opts.raw (a file) as it is. opts.blob: the answer is a file.
// Show and Hide beside every password box (1.36.2, the owner, October 14:
// "Admin should be able to unhide password when typing"), wherever one is
// drawn, now or later.
function revealable(input) {
  if (input.dataset.reveal) return;
  input.dataset.reveal = '1';
  const wrap = h('span', { class: 'reveal' });
  const button = h('button', { type: 'button', class: 'reveal-btn', 'aria-pressed': 'false', 'aria-label': 'Show password' }, 'Show');
  button.addEventListener('click', () => {
    const shown = input.type === 'password';
    input.type = shown ? 'text' : 'password';
    button.textContent = shown ? 'Hide' : 'Show';
    button.setAttribute('aria-pressed', String(shown));
    button.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
    input.focus();
  });
  input.replaceWith(wrap);
  wrap.append(input, button);
  // (Hidden again whenever its form is sent or reset.)
  input.form?.addEventListener('reset', () => { input.type = 'password'; button.textContent = 'Show'; button.setAttribute('aria-pressed', 'false'); });
}
new MutationObserver(() => document.querySelectorAll('input[type=password]:not([data-reveal])').forEach(revealable))
  .observe(document.documentElement, { childList: true, subtree: true });
document.querySelectorAll('input[type=password]').forEach(revealable);
async function api(path, opts = {}) {
  // (X-Tapioca-Page: what the server asks of every change made from its
  // page, which a page on another site can't send. See access.py.)
  const res = await fetch(path, {
    ...opts,
    headers: { 'X-Tapioca-Page': '1', ...(opts.body ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) },
    body: opts.raw ?? (opts.body ? JSON.stringify(opts.body) : undefined),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg);
    } catch {}
    // (A wrong password when signing in is a 401 too.)
    if (res.status === 401 && !['/api/access/sign-in', '/api/access/pin-sign-in', '/api/access/trusted-sign-in'].includes(path)) showSignIn(msg === ACCESS.idleSignedOut);
    throw Object.assign(new Error(msg), { status: res.status });
  }
  // (Nothing to say: 204, or a 202 with no body.)
  if (res.status === 204 || res.headers.get('content-length') === '0') return null;
  return opts.blob ? res.blob() : res.json();
}

let toastTimer;
// The dialog open on top, if one is (everything else is out of reach under
// it: a toast, or the copy's text, goes in it to be seen and selected).
const topDialog = () => [...document.querySelectorAll('dialog[open]')].filter(d => d.matches(':modal')).pop() || null;
// The toast, in sight: in the dialog on top, if there is one, or the page.
function toastBox() {
  const t = $('#toast');
  const host = topDialog() || document.body;
  if (t.parentElement !== host) host.append(t);
  return t;
}
function toast(msg, error = false) {
  // (Not over the sign-in page, which says what's needed: a problem then is
  // only something the page was doing as it was signed out.)
  if (error && signedOut()) return;
  const t = toastBox();
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
    h('p', { style: 'margin:0' }, `Watching in Plex? To add ${one ? 'it' : 'them'}, go to `, h('em', {}, 'Settings → Live TV & DVR → your tuner → Scan for channels'),
      ' in Plex (Plex calls stations “channels”). Other apps show new stations once they refresh their guide. Tuner integration, on the Setup tab, shows how to add tapiOca to each.'),
    problems.length ? h('div', { class: 'notice-bad' }, h('strong', {}, 'Couldn’t make these'),
      h('ul', { class: 'steps' }, ...problems.map(p => h('li', {}, p)))) : null);
}
// A message with an Undo button, shown until it's too late to undo.
function toastWithUndo(msg, undo) {
  const t = toastBox();
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
  if (name === 'setup') { loadBackups(); renderPlaybackPanel(); loadUpdates(); loadInfoStation(); loadFolderLibraries(); }
  if (name === 'stats') { loadStats(); loadNow(); }
  if (name === 'access') { loadAccess(); loadApps(); loadTuner(); loadLimits(); loadAway(); loadAppLimits(); loadAppLibraries(); loadApiTokens(); loadTrusted(); }
  history.replaceState(null, '', '#' + name);
}

// More above, more below ------------------------------------------------------
// Something that runs on past what shows (a dialog's body, the log, the
// page itself) has a down arrow while more of it is below what shows, and
// an up arrow while more is above, as tapiOca's apps have them. "More"
// is more than 1px (less is rounding, never a line of words), worked out
// from what's laid out, so a turned tablet or a short window gets them just
// when it needs them. Each is a chevron on a short fade into the background
// at that edge, so a line cut by the edge fades out under it. They're only
// drawn: clicks and taps go on to what's under them, they're never
// focused, and screen readers pass them by.
const MORE_SLACK = 1;
const moreArrowsOf = (scrolled, shown, whole) =>
  ({ above: scrolled > MORE_SLACK, below: whole - shown - scrolled > MORE_SLACK });
const MORE_CHEVRON = up => `<svg viewBox="0 0 32 32" width="32" height="32" focusable="false"><path d="${up ? 'M8 20 16 12 24 20' : 'M8 12 16 20 24 12'}"/></svg>`;
const moreLayer = cls => {
  const layer = h('div', { class: `more-arrows${cls ? ' ' + cls : ''}`, 'aria-hidden': 'true' },
    h('div', { class: 'more-up', hidden: true }), h('div', { class: 'more-down', hidden: true }));
  layer.firstChild.innerHTML = MORE_CHEVRON(true);
  layer.lastChild.innerHTML = MORE_CHEVRON(false);
  return layer;
};
const moreShow = (layer, arrows) => {
  if (layer.firstChild.hidden === arrows.above) layer.firstChild.hidden = !arrows.above;
  if (layer.lastChild.hidden === arrows.below) layer.lastChild.hidden = !arrows.below;
};
// Once a frame at most, however many things ask.
const moreLater = fn => {
  let asked = false;
  return () => { if (!asked) { asked = true; requestAnimationFrame(() => { asked = false; fn(); }); } };
};
const moreAdded = new WeakSet();
// The arrows for `el`, a box that scrolls (once each: again does nothing).
// They lie over it, beside it in its parent (made the place they're
// measured from, if it isn't one already).
function moreArrows(el) {
  if (moreAdded.has(el) || !el.parentElement) return;
  moreAdded.add(el);
  const parent = el.parentElement;
  if (getComputedStyle(parent).position === 'static') parent.classList.add('more-host');
  const layer = moreLayer();
  el.after(layer);
  const update = moreLater(() => {
    // (Over the part that shows: inside its border, beside its scroll bar.)
    const r = el.getBoundingClientRect(), p = parent.getBoundingClientRect(), s = layer.style;
    s.top = `${r.top - p.top - parent.clientTop + parent.scrollTop + el.clientTop}px`;
    s.left = `${r.left - p.left - parent.clientLeft + parent.scrollLeft + el.clientLeft}px`;
    s.width = `${el.clientWidth}px`;
    s.height = `${el.clientHeight}px`;
    const round = getComputedStyle(el);
    s.borderRadius = ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft']
      .map(c => `${Math.max(0, parseFloat(round[`border${c}Radius`]) - el.clientTop)}px`).join(' ');
    moreShow(layer, moreArrowsOf(el.scrollTop, el.clientHeight, el.scrollHeight));
  });
  el.addEventListener('scroll', update, { passive: true });
  el.addEventListener('load', update, true);  // (a picture in it, sized once it's loaded)
  // Its own size, and where it is in its parent (whatever is beside it changes size).
  const sizes = new ResizeObserver(update);
  const watch = () => { sizes.disconnect(); sizes.observe(el); sizes.observe(parent); for (const k of parent.children) if (k !== layer) sizes.observe(k); };
  watch();
  // What's in it (and what's beside it) changing.
  new MutationObserver(update).observe(el, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['open', 'hidden', 'class', 'style'] });
  new MutationObserver(() => { watch(); update(); }).observe(parent, { childList: true });
  update();
}
// The page's own down arrow: while the last footer that shows (the page's,
// or the sign-in screen's) ends below the window, by more than MORE_SLACK.
// The page's empty space under it is nothing more to see (the owner, in
// Safari, October 15). null when no footer shows.
const pageBelow = (feet, shown) => {
  const last = [...feet].filter(f => f.getClientRects().length).pop();
  return last ? last.getBoundingClientRect().bottom - shown > MORE_SLACK : null;
};
// The page's own, at the window's edges.
(() => {
  const layer = moreLayer('page');
  document.body.append(layer);
  const page = document.scrollingElement || document.documentElement;
  const update = moreLater(() => {
    const arrows = moreArrowsOf(page.scrollTop, window.innerHeight, page.scrollHeight);
    const below = pageBelow(document.querySelectorAll('.foot'), window.innerHeight);
    moreShow(layer, below === null ? arrows : { ...arrows, below });
  });
  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update);
  new ResizeObserver(update).observe(document.body);
  update();
})();
// Every dialog's body, the log, a problem's journal (see logs.js), and the
// station editor's lists.
document.querySelectorAll('.dlg-body, #logList, .picker-list, .fbox, #fMatches').forEach(moreArrows);

// Copying works on a plain http:// address too, where browsers don't offer
// the clipboard API.
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch {}
  }
  // (At a home address, over http, the browser has no clipboard to write
  // to: the text is selected and copied instead, in the dialog on top if
  // one's open, where it can be: 1.34.1, the owner.)
  const was = document.activeElement;
  const area = h('textarea', { style: 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0', readonly: true, 'aria-hidden': 'true', tabindex: '-1' });
  area.value = text;
  (topDialog() || document.body).append(area);
  area.focus({ preventScroll: true });
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch {}
  area.remove();
  was?.focus?.({ preventScroll: true });
  return ok;
}
// A Copy button: says Copied, or how to copy it otherwise.
const copyButton = value => h('button', { type: 'button', class: 'btn', onclick: async () => {
  toast(await copyText(value) ? 'Copied' : `Couldn’t copy. Select it and copy it yourself: ${value}`, false);
} }, 'Copy');
