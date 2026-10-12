// StationPlay's own new versions (see releases.py on the server): for
// Admins, a banner when a newer one is out, with how this kind of install
// updates its image, What's new and Back up now; and the update check's
// setting, on the Add to Plex tab. "Not now" hides the banner for that
// version, in this browser.
const UPDATE_NOT_NOW = 'stationplay.updateNotNow';
const notNowFor = () => { try { return localStorage.getItem(UPDATE_NOT_NOW) || ''; } catch { return ''; } };
let updates = null;
async function loadUpdates() {
  const banner = $('#updateBanner');
  if (!isAdmin() || signedOut()) { banner.hidden = true; return; }
  try { updates = await api('/api/updates'); } catch { return; }
  renderUpdatesPanel();
  const u = updates;
  if (!u.latest || notNowFor() === u.latest.version) { banner.hidden = true; return; }
  const copy = h('button', { class: 'btn', type: 'button', onclick: async () => toast(await copyText(u.command) ? 'Copied' : 'Couldn’t copy: select it and copy it yourself', !u.command) }, 'Copy');
  banner.replaceChildren(
    h('p', { class: 'update-title' }, h('strong', {}, `StationPlay ${u.latest.version} is available.`), ' ', h('span', { class: 'muted' }, `This is ${u.current}.`)),
    h('div', { class: 'update-steps' },
      u.install ? h('p', { class: 'small muted' }, `To update on ${u.install}:`) : null,
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
// The setting, on the Add to Plex tab (under Backups).
function renderUpdatesPanel() {
  const panel = $('#updatesPanel');
  if (!panel || !updates) return;
  const u = updates;
  const on = h('input', { type: 'checkbox', id: 'updateCheckOn', checked: u.on, onchange: async e => {
    try { updates = await api('/api/updates', { method: 'PUT', body: { on: e.target.checked } }); toast(e.target.checked ? 'StationPlay will tell you when a new version is out' : 'The update check is off'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message, true); }
    loadUpdates();
  } });
  const last = u.checked
    ? (u.checked.problem ? `Last checked ${new Date(u.checked.at).toLocaleString()}: ${u.checked.problem}.`
      : `Last checked ${new Date(u.checked.at).toLocaleString()}.`)
    : 'Not checked yet.';
  panel.replaceChildren(
    h('label', {}, on, ' Tell me when a new StationPlay is out'),
    h('p', { class: 'hint', style: 'margin:0' }, 'StationPlay asks GitHub once a day, sending only its version. It never updates by itself.'),
    h('div', { class: 'row-btns' },
      h('span', { class: 'small muted' }, u.on ? (u.latest ? `StationPlay ${u.latest.version} is available. ${last}` : `This is the newest StationPlay (${u.current}). ${last}`) : `This is StationPlay ${u.current}.`),
      h('span', { class: 'spacer' }),
      u.on ? h('button', { class: 'btn', type: 'button', onclick: async e => {
        e.target.disabled = true;
        try { updates = await api('/api/updates/check', { method: 'POST' }); } catch (err) { toast(err.message, true); }
        loadUpdates();
      } }, 'Check now') : null));
}
