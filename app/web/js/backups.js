// Backups, and the logo picker's buttons.
// Backups ----------------------------------------------------------------------
const fmtSize = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
async function loadBackups() {
  let res;
  try { res = await api('/api/backups'); } catch { return; }
  $('#backupList').replaceChildren(...(res.backups.length
    ? res.backups.map(b => h('div', { class: 'copyrow' },
        h('span', { class: 'what' }, new Date(b.made).toLocaleString()),
        h('span', { class: 'small muted' }, b.name.includes('before-restore') ? 'Saved before a restore' : 'Backup'),
        h('span', { class: 'spacer' }),
        h('span', { class: 'small muted' }, fmtSize(b.size)),
        h('a', { class: 'btn', href: `/api/backups/${encodeURIComponent(b.name)}`, download: b.name }, 'Download')))
    : [h('p', { class: 'hint', style: 'padding:4px 2px' }, 'No backups yet. StationPlay makes one within 15 minutes of starting, then one every night. To make one now, choose Download a backup.')]));
}
$('#backupNow').addEventListener('click', async () => {
  try {
    const made = await api('/api/backups', { method: 'POST' });
    const link = h('a', { href: `/api/backups/${encodeURIComponent(made.name)}`, download: made.name });
    document.body.append(link);
    link.click();
    link.remove();
    loadBackups();
  } catch (e) { toast(e.message, true); }
});
$('#restoreFile').addEventListener('change', async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  if (!confirm(`Restore ${file.name}? This replaces all your stations, settings, and users with the ones in the backup. StationPlay restarts, and anyone watching is disconnected. (Your current setup is backed up first.)`)) return;
  try {
    let res;
    try { res = await api('/api/restore', { method: 'POST', raw: file }); }
    catch (err) {
      if (err.status !== 409 || !confirm(`${err.message} Restore it anyway?`)) throw err;
      res = await api('/api/restore?opening=true', { method: 'POST', raw: file });
    }
    toast(`Restoring ${plural(res.stations, 'station')}. StationPlay is restarting…`);
    waitForRestart();
  } catch (err) { toast(err.message, true); }
});
async function waitForRestart() {
  // Wait for StationPlay to go away and come back, then reload the page.
  const started = Date.now();
  let wentAway = false;
  while (Date.now() - started < 120000) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      await api('/api/access/me');  // (open, signed in or not)
      if (wentAway || Date.now() - started > 15000) { location.reload(); return; }
    } catch { wentAway = true; }
  }
  toast('StationPlay hasn’t come back yet. If it isn’t running in Docker, start it again.', true);
}

async function deleteLogo(l) {
  if (!confirm(`Delete the logo “${l.name}”?`)) return;
  try {
    await api(`/api/logos/${l.id}`, { method: 'DELETE' });
    if (logo === l.id) { logo = ''; renderLogoChoice(); }
    await refreshLogoCatalog();
    if (!logoCatalog.some(x => x.category === YOURS) && logoCategory === YOURS) logoCategory = 'All';
    renderLogoPicker();
  } catch (err) { toast(err.message, true); }
}
function pickLogo(id) { logo = id; logoChosen = true; renderLogoChoice(); $('#logoPicker').close(); }
$('#chooseLogo').addEventListener('click', async () => {
  try { await loadLogoCatalog(); } catch (e) { toast(e.message, true); return; }
  $('#logoSearch').value = '';
  logoCategory = suggestedLogos().length ? SUGGESTED : 'All';
  renderLogoPicker();
  $('#logoPicker').showModal();
});
$('#randomLogo').addEventListener('click', async () => { await loadLogoCatalog(); logoChosen = true; randomLogo(); });
$('#fName').addEventListener('input', renderMarkPreview);
$('#closeLogos').addEventListener('click', () => $('#logoPicker').close());
