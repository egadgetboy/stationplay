// StationPlay's own new versions (see releases.py on the server): for
// Admins, a banner when a newer one is out, with how this kind of install
// updates its image, What's new and Back up now; the one-time question
// whether to look at all (asked here once setup is done, of a StationPlay
// updated from before 1.34.0: a new one asks in setup's last step); and the
// update check's setting, on the Add to Plex tab. "Not now" hides the
// banner for that version, in this browser.
const UPDATE_NOT_NOW = 'stationplay.updateNotNow';
const UPDATE_PRIVACY = 'Once a day, StationPlay asks GitHub whether a newer version is out. GitHub sees your server’s internet address when it asks, as any website does. StationPlay sends only its version, and never updates by itself.';
const notNowFor = () => { try { return localStorage.getItem(UPDATE_NOT_NOW) || ''; } catch { return ''; } };
let updates = null;
// An Admin's answer, from the question, the setting or setup: then the
// banner and the New versions panel show it. Whether it was saved.
async function answerUpdates(on) {
  try { updates = await api('/api/updates', { method: 'PUT', body: { on } }); }
  catch (err) { toast(err.message, true); return false; }
  toast(on ? 'StationPlay will tell you when a new version is out' : 'The update check is off');
  loadUpdates();
  return true;
}
async function loadUpdates() {
  const banner = $('#updateBanner');
  if (!isAdmin() || signedOut()) { banner.hidden = true; return; }
  try { updates = await api('/api/updates'); } catch { return; }
  renderUpdatesPanel();
  const u = updates;
  if (u.ask) {
    const answer = on => async e => {
      for (const b of banner.querySelectorAll('button')) b.disabled = true;
      if (!(await answerUpdates(on))) for (const b of banner.querySelectorAll('button')) b.disabled = false;
    };
    banner.replaceChildren(
      h('p', { class: 'update-title' }, h('strong', {}, 'Should StationPlay tell you when a new version is out?')),
      h('p', { class: 'small' }, UPDATE_PRIVACY),
      h('p', { class: 'small muted' }, 'You can change this later under New versions on the Add to Plex tab.'),
      h('div', { class: 'row-btns' },
        h('button', { class: 'btn primary', type: 'button', onclick: answer(true) }, 'Yes, tell me'),
        h('button', { class: 'btn', type: 'button', onclick: answer(false) }, 'No')));
    banner.hidden = false;
    return;
  }
  if (!u.latest || notNowFor() === u.latest.version) { banner.hidden = true; return; }
  const copy = h('button', { class: 'btn', type: 'button', onclick: async () => toast(await copyText(u.command) ? 'Copied' : 'Couldn’t copy: select it and copy it yourself', !u.command) }, 'Copy');
  banner.replaceChildren(
    h('p', { class: 'update-title' }, h('strong', {}, `StationPlay ${u.latest.version} is available.`), ' ', h('span', { class: 'muted' }, `This is ${u.current}.`)),
    h('div', { class: 'update-steps' },
      u.install ? h('p', { class: 'small muted' }, u.heading) : null,
      ...u.steps.map(s => h('p', { class: 'small' }, s)),
      u.command ? h('div', { class: 'copyrow' }, h('code', {}, u.command), copy) : null),
    h('div', { class: 'row-btns' },
      h('a', { class: 'btn primary', href: u.latest.url, target: '_blank', rel: 'noopener noreferrer' }, 'What’s new'),
      h('button', { class: 'btn', type: 'button', onclick: () => $('#backupNow').click() }, 'Back up now'),
      h('a', { class: 'btn ghost', href: u.readme, target: '_blank', rel: 'noopener noreferrer' }, 'All the steps'),
      h('button', { class: 'btn ghost', type: 'button', onclick: () => {
        try { localStorage.setItem(UPDATE_NOT_NOW, u.latest.version); } catch {}
        banner.hidden = true;
      } }, 'Not now')));
  banner.hidden = false;
}
// The setting, on the Add to Plex tab (under Backups). Never ticked until
// an Admin says yes.
function renderUpdatesPanel() {
  const panel = $('#updatesPanel');
  if (!panel || !updates) return;
  const u = updates;
  const on = h('input', { type: 'checkbox', id: 'updateCheckOn', checked: u.on === true, onchange: async e => {
    const want = e.target.checked;
    e.target.disabled = true;
    if (!(await answerUpdates(want))) { e.target.checked = !want; e.target.disabled = false; }
  } });
  const last = u.checked
    ? (u.checked.problem ? `Last checked ${new Date(u.checked.at).toLocaleString()}: ${u.checked.problem}.`
      : `Last checked ${new Date(u.checked.at).toLocaleString()}.`)
    : 'Not checked yet.';
  const now = u.on === true
    ? (u.latest ? `StationPlay ${u.latest.version} is available. ${last}` : `This is the newest StationPlay (${u.current}). ${last}`)
    : u.on === null ? `This is StationPlay ${u.current}. You haven’t chosen yet whether StationPlay looks for new versions.`
      : `This is StationPlay ${u.current}.`;
  panel.replaceChildren(
    h('label', {}, on, ' Tell me when a new StationPlay is out'),
    h('p', { class: 'hint', style: 'margin:0' }, UPDATE_PRIVACY),
    h('div', { class: 'row-btns' },
      h('span', { class: 'small muted' }, now),
      h('span', { class: 'spacer' }),
      u.on === true ? h('button', { class: 'btn', type: 'button', onclick: async e => {
        e.target.disabled = true;
        try { updates = await api('/api/updates/check', { method: 'POST' }); } catch (err) { toast(err.message, true); }
        loadUpdates();
      } }, 'Check now') : null));
}
