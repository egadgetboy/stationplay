// tapiOca's own new versions (see releases.py on the server): for
// Admins, a banner when a newer one is out, with how this kind of install
// updates its image, What's new and Back up now; the one-time question
// whether to look at all (asked here once setup is done, of a tapiOca
// updated from before 1.34.0: a new one asks in setup's last step); and the
// update check's setting, on the Setup tab. "Not now" hides the
// banner for that version, in this browser.
const UPDATE_NOT_NOW = 'tapioca.updateNotNow';
const UPDATE_PRIVACY = 'Every 4 hours, tapiOca asks GitHub whether a newer version is out. GitHub sees your server’s internet address when it asks, as any website does. tapiOca sends only its version, and never updates by itself.';
const notNowFor = () => { try { return localStorage.getItem(UPDATE_NOT_NOW) || ''; } catch { return ''; } };
let updates = null;
// An Admin's answer, from the question, the setting or setup: then the
// banner and the New versions panel show it. Whether it was saved.
async function answerUpdates(on) {
  try { updates = await api('/api/updates', { method: 'PUT', body: { on } }); }
  catch (err) { toast(err.message, true); return false; }
  toast(on ? 'tapiOca will tell you when a new version is out' : 'The update check is off');
  loadUpdates();
  return true;
}
async function loadUpdates() {
  const banner = $('#updateBanner');
  const pill = $('#updatePill');
  if (!isAdmin() || signedOut()) { banner.hidden = pill.hidden = true; return; }
  try { updates = await api('/api/updates'); } catch { return; }
  renderUpdatesPanel();
  const u = updates;
  // The header's pill, for as long as a newer tapiOca is out (even after
  // Not now): it brings the banner back (1.34.1, the owner).
  pill.hidden = !u.latest;
  if (u.latest) {
    pill.querySelector('.long').textContent = `tapiOca ${u.latest.version} is out`;
    pill.title = `tapiOca ${u.latest.version} is available. This is ${u.current}. Choose to see how to update.`;
  }
  if (u.ask) {
    const answer = on => async e => {
      for (const b of banner.querySelectorAll('button')) b.disabled = true;
      if (!(await answerUpdates(on))) for (const b of banner.querySelectorAll('button')) b.disabled = false;
    };
    banner.replaceChildren(
      h('p', { class: 'update-title' }, h('strong', {}, 'Should tapiOca tell you when a new version is out?')),
      h('p', { class: 'small' }, UPDATE_PRIVACY),
      h('p', { class: 'small muted' }, 'You can change this later under New versions on the Setup tab.'),
      h('div', { class: 'row-btns' },
        h('button', { class: 'btn primary', type: 'button', onclick: answer(true) }, 'Yes, tell me'),
        h('button', { class: 'btn', type: 'button', onclick: answer(false) }, 'No')));
    banner.hidden = false;
    return;
  }
  if (!u.latest || notNowFor() === u.latest.version) { banner.hidden = true; return; }
  const copy = h('button', { class: 'btn', type: 'button', onclick: async () => toast(await copyText(u.command) ? 'Copied' : 'Couldn’t copy: select it and copy it yourself', !u.command) }, 'Copy');
  banner.replaceChildren(
    h('p', { class: 'update-title' }, h('strong', {}, `tapiOca ${u.latest.version} is available.`), ' ', h('span', { class: 'muted' }, `This is ${u.current}.`)),
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
// The setting, on the Setup tab (under Backups). Never ticked until
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
    ? (u.latest ? `tapiOca ${u.latest.version} is available. ${last}` : `This is the newest tapiOca (${u.current}). ${last}`)
    : u.on === null ? `This is tapiOca ${u.current}. You haven’t chosen yet whether tapiOca looks for new versions.`
      : `This is tapiOca ${u.current}.`;
  panel.replaceChildren(
    h('label', {}, on, ' Tell me when a new tapiOca is out'),
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
$('#updatePill').addEventListener('click', () => {
  try { localStorage.removeItem(UPDATE_NOT_NOW); } catch {}
  loadUpdates().then(() => {
    window.scrollTo(0, 0);
    $('#updateBanner').querySelector('a.btn, button')?.focus();
  });
});
// The INFO station (see infostation.py on the server): station 99, its
// state, and Add the INFO station to bring it back, on the Setup tab.
async function loadInfoStation() {
  const panel = $('#infoPanel');
  if (!panel || !isAdmin()) return;
  let got;
  try { got = await api('/api/info-station'); } catch { return; }
  const about = h('p', { class: 'hint', style: 'margin:0' }, 'Station 99, INFO, shows the date and time, what’s new in this version of tapiOca and in its apps, how many stations you have and what’s in the Media folders shared with tapiOca’s apps (counts only, never titles), and tips for tapiOca’s apps, over a film of pearls flying through tapiOca’s ring. Everyone who can watch your stations in tapiOca’s apps sees it, so it never shows your server’s addresses or how it’s doing. It plays even without Plex. While it’s your only station, Plex and other apps get it too, so Plex has a station to find when you add tapiOca to it; once you have a station of your own, it’s for tapiOca’s apps only.');
  if (got.station !== null) {
    panel.replaceChildren(about, h('p', { style: 'margin:0' }, `INFO is station 99${got.name !== 'INFO' ? `, called ${got.name}` : ''}. To remove it, delete it on the Stations tab. You can add it back here any time.`));
    return;
  }
  const said = h('span', { class: 'hint', role: 'status' });
  const add = h('button', { type: 'button', class: 'btn', disabled: !!got.taken, onclick: async () => {
    add.disabled = true;
    try { await api('/api/info-station', { method: 'POST' }); }
    catch (e) { said.textContent = e.message; add.disabled = false; return; }
    toast('INFO is back on station 99');
    loadChannels();
    loadInfoStation();
  } }, 'Add the INFO station');
  panel.replaceChildren(about,
    got.taken ? h('p', { style: 'margin:0' }, `Station 99 is ${got.taken} now. To add INFO, give that station another number first: INFO is always station 99.`) : null,
    h('div', { class: 'scan-set' }, add, said));
}
