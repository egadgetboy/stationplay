// Checking files, on the Broken files tab.
// Checking files -------------------------------------------------------------------
const clock = t => { const [hh, mm] = t.split(':').map(Number); return new Date(2000, 0, 1, hh, mm).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); };
let scanShown = null;
async function loadScan() {
  let st;
  try { st = await api('/api/scan'); } catch { return; }
  const n = st.programs;
  $('#scanQuick').replaceChildren(h('strong', {}, 'Quick checks: '),
    `${st.quickChecked} of ${plural(n, 'program')} on the stations checked in the past week. New programs are checked within minutes of arriving, and everything is checked again each week.`,
    st.checking ? ` Checking ${plural(st.checking, 'file')} someone had trouble with first.` : '',
    st.state === 'checking' ? h('span', { class: 'chip accent', style: 'margin-left:6px' }, 'checking now')
      : st.state === 'paused' ? h('span', { class: 'chip plain', style: 'margin-left:6px', title: 'File checks pause while anyone is watching, a station or Media, so what they watch keeps playing smoothly' }, 'paused while someone is watching') : '');
  // Media: what's shared with StationPlay's apps (once its files are known).
  const m = st.media;
  $('#scanMedia').hidden = !m;
  if (m) $('#scanMedia').replaceChildren(h('strong', {}, 'Media: '),
    m.files != null ? `${m.quickChecked.toLocaleString()} of ${plural(m.files, 'file')} in the libraries shared with StationPlay’s apps checked, ${m.deepScanned.toLocaleString()} scanned in full. ` : '',
    'What’s newly added is checked within minutes. The rest is scanned overnight, after the stations’ programs: what people are watching first, then the most recently added.');
  // (The reports waiting on a check are shown afresh as it ends.)
  if (scanShown && scanShown.checking !== st.checking) loadBroken();
  const w = st.window;
  let now = '';
  if (st.state === 'scanning' && st.current) now = `Now scanning ${st.current} (${st.currentPct}%).`;
  else if (st.state === 'paused') now = 'Paused while someone is watching. It resumes when they stop.';
  else if (!w.on) now = 'Off.';
  else if (st.deepScanned >= n) now = 'Everything has been scanned. New and changed files get scanned overnight.';
  else if (!st.inWindow) now = `It runs next from ${clock(w.start)} to ${clock(w.end)}.`;
  const tonight = st.tonight && st.tonight.scanned ? ` Tonight: ${st.tonight.scanned} scanned, ${st.tonight.problems} with problems.` : '';
  $('#scanDeep').replaceChildren(h('strong', {}, 'Overnight deep scan: '),
    `${st.deepScanned} of ${n} scanned in full, starting with what airs soonest. ${now}${tonight}`);
  renderListCheck(st.list, w);
  const bad = status?.fillers?.unplayable || [];
  $('#scanClips').hidden = !bad.length;
  $('#scanClips').replaceChildren(h('strong', {}, 'Commercials and trailers that didn’t play: '),
    `${bad.map(p => p.split('/').pop()).join(', ')}. They’re left out until their files are replaced.`);
  // Don't overwrite the settings while they're being changed.
  if (!scanShown || $('#scanSave').hidden) {
    $('#scanOn').checked = w.on;
    $('#scanStart').value = w.start;
    $('#scanEnd').value = w.end;
  }
  scanShown = st;
}
// Going through the list again: every night as the overnight checks' hours
// begin, and with Check the list again. The list is shown afresh as it
// clears, and when it's done.
let listShown = null;
function renderListCheck(l, w) {
  if (!l) return;
  const btn = $('#brokenAgain');
  btn.disabled = l.running;
  btn.textContent = l.running ? 'Checking the list…' : 'Check the list again';
  const when = `every night at ${clock(w.start)} and whenever you choose Check the list again. Changes in Plex are checked every half hour.`;
  let text;
  if (l.running) {
    text = l.total ? `Checking it again now: ${l.done} of ${l.total}${l.cleared ? `, ${l.cleared} back on the air so far` : ''}…` : 'Checking it again now…';
  } else if (l.finishedAt) {
    text = `Checked again ${when} Last check (${new Date(l.finishedAt).toLocaleString()}): ${l.cleared} of ${l.total} back on the air.`
      + (l.plexAway ? ' It stopped partway because Plex couldn’t be reached. It will continue next time.' : '');
  } else {
    text = `Checked again ${when}`;
  }
  $('#scanList').replaceChildren(h('strong', {}, 'This list: '), text);
  // (Shown afresh as programs come off it, and when it's done.)
  if (listShown && (listShown.cleared !== l.cleared || (listShown.running && !l.running))) { loadBroken(); loadStatus(); }
  listShown = l;
}
$('#brokenAgain').addEventListener('click', async () => {
  $('#brokenAgain').disabled = true;
  try {
    const l = await api('/api/broken/check', { method: 'POST' });
    renderListCheck(l, scanShown?.window || { start: '01:00' });
  } catch (e) { toast(e.message, true); $('#brokenAgain').disabled = false; return; }
  loadScan();
});
for (const id of ['#scanOn', '#scanStart', '#scanEnd']) $(id).addEventListener('input', () => { $('#scanSave').hidden = false; });
$('#scanSave').addEventListener('click', async () => {
  try {
    await api('/api/scan', { method: 'PUT', body: { on: $('#scanOn').checked, start: $('#scanStart').value, end: $('#scanEnd').value } });
    $('#scanSave').hidden = true;
    toast('Saved');
    loadScan();
  } catch (e) { toast(e.message, true); }
});

async function retry(r) {
  try { await api(`/api/broken/${encodeURIComponent(r.key)}`, { method: 'DELETE' }); toast(`${programName(r)} is back on the air`); loadBroken(); loadStatus(); loadChannels(); }
  catch (e) { toast(e.message, true); }
}
