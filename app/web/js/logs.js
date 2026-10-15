// The Logs tab, and problems sent from the apps.
// Logs ---------------------------------------------------------------------------
let logText = '';
// (Each ask is numbered: only the newest's answer shows, so a slow one never
// covers a newer search's. The cold audit, 1.37.0.)
let logAsked = 0;
async function loadLogs(scrollToEnd = false) {
  const mine = ++logAsked;
  const levels = [$('#logWarn').checked && 'WARNING', $('#logErr').checked && 'ERROR'].filter(Boolean);
  const accessLog = $('#logAccess').checked;
  // (The search, 1.37.0: every word, in any case, through all that's kept.)
  const q = $('#logFind').value.trim();
  let data;
  try { data = await api(`/api/logs?limit=200&levels=${levels.join(',')}&access_log=${accessLog}&q=${encodeURIComponent(q)}`); }
  catch (e) { if (mine === logAsked) $('#logList').replaceChildren(h('p', { class: 'muted', style: 'padding:14px;margin:0' }, e.message)); return; }
  if (mine !== logAsked) return;
  logText = data.text;
  const list = $('#logList');
  const atEnd = scrollToEnd || list.scrollTop + list.clientHeight >= list.scrollHeight - 40;
  list.replaceChildren(...(data.entries.length
    ? data.entries.map(e => h('div', { class: `logline ${e.level}` },
        h('span', { class: 'when' }, new Date(e.time * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' })),
        h('span', { class: 'lvl' }, e.level),
        h('span', { class: 'msg' }, e.message)))
    : [h('p', { class: 'muted', style: 'padding:14px;margin:0' }, q ? (levels.length || accessLog ? `No lines with these choices have “${q}”.` : `Nothing in the log has “${q}”.`) : levels.length || accessLog ? 'No matching entries.' : 'Nothing logged yet.')]));
  if (atEnd) list.scrollTop = list.scrollHeight;
}
$('#logWarn').addEventListener('change', () => loadLogs(true));
$('#logErr').addEventListener('change', () => loadLogs(true));
$('#logAccess').addEventListener('change', () => loadLogs(true));
// (Searched as it's typed, once typing pauses.)
let logFindTimer = null;
$('#logFind').addEventListener('input', () => { clearTimeout(logFindTimer); logFindTimer = setTimeout(() => loadLogs(true), 300); });
// What the apps ran into (see problems.py on the server).
let problemDays = 7;
async function loadProblems() {
  const list = $('#problemList');
  let data;
  try { data = await api(`/api/problems?days=${problemDays}`); }
  catch (e) { list.replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
  const at = ms => new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  const period = problemDays === 1 ? 'today' : `in the last ${problemDays} days`;
  $('#clearProblems').disabled = !data.problems.length;
  list.replaceChildren(...(data.problems.length ? data.problems.map(p => {
    const times = p.times === 1 ? 'once' : `${p.times} times`;
    const devices = p.devices === 1 ? 'on 1 device' : `on ${p.devices} devices`;
    const who = p.people.length ? ` · ${p.people.join(', ')}` : '';
    const where = p.only
      ? h('p', { class: 'problem-on' }, h('span', { class: 'pill' }, 'One kind of device'), ` Only on ${p.on[0].device}`)
      : h('p', { class: 'problem-on' }, h('span', { class: 'pill' }, `${p.on.length} kinds of device`), ' ',
          p.on.slice(0, 4).map(o => `${o.device} (${o.times})`).join(' · ') + (p.on.length > 4 ? ` · and ${p.on.length - 4} more` : ''));
    return h('div', { class: 'problem' },
      h('p', { class: 'problem-what' }, h('strong', {}, p.label), h('span', { class: 'muted small' },
        ` ${times} ${devices}${who}${p.away ? ' · some away from home' : ''} · last ${at(p.lastMs)}`)),
      where,
      p.means.length ? h('div', { class: 'problem-means' }, h('span', { class: 'label' }, 'What it means'),
        ...p.means.map(m => h('p', {}, m))) : null,
      p.details.length ? h('p', { class: 'muted small' }, `What the app said: ${p.details.join('; ')}`) : null,
      p.journal != null ? journalOf(p.journal) : null);
  }) : [h('p', { class: 'muted' }, `No problems from the apps ${period}.`)]));
}
// What an app did before a problem: its journal's lines, fetched when opened.
function journalOf(id) {
  const lines = h('pre', { class: 'journal' }, 'Loading…');
  let asked = false;
  const more = h('details', { class: 'more', ontoggle: async e => {
    if (!e.target.open || asked) return;
    asked = true;
    try { lines.textContent = (await api(`/api/problems/${id}/journal`)).lines.join('\n'); }
    catch (err) { lines.textContent = err.message; asked = false; }
  } }, h('summary', {}, 'What led up to it'), lines);
  moreArrows(lines);  // (its arrows while more of it is above or below: see core.js)
  return more;
}
$('#problemDays').addEventListener('click', e => {
  const b = e.target.closest('button[data-days]');
  if (!b) return;
  problemDays = Number(b.dataset.days);
  [...$('#problemDays').children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  loadProblems();
});
$('#clearProblems').addEventListener('click', async () => {
  if (!confirm('Clear every problem the apps sent? They’re also in the log, which keeps them.')) return;
  try { await api('/api/problems', { method: 'DELETE' }); }
  catch (e) { toast(e.message, true); return; }
  loadProblems();
});
$('#copyLogs').addEventListener('click', async () => {
  if (!logText) { toast('Nothing to copy'); return; }
  toast(await copyText(logText) ? 'Logs copied' : 'Couldn’t copy. Select the text and copy it instead.', false);
});
