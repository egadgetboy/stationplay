// The Stats tab.
// The Stats tab ----------------------------------------------------------------------
let statDays = 7;
const hoursText = h_ => h_ >= 10 ? `${Math.round(h_)} hr` : h_ >= 1 ? `${h_.toFixed(1)} hr` : `${Math.round(h_ * 60)} min`;
function stationBadge(s) {
  return h('span', { class: 'station' },
    s.logo ? logoImg(s.logo) : h('span', { class: 'logo-num' }, s.number),
    h('span', {}, h('strong', {}, s.number), ` ${s.name}`));
}
const hourName = n => `${n % 12 || 12} ${n < 12 ? 'AM' : 'PM'}`;
async function loadStats() {
  pressOne('days', String(statDays));
  let s;
  try { s = await api(`/api/stats?days=${statDays}`); }
  catch (e) { $('#statTiles').replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
  const tile = (value, label) => h('div', { class: 'panel tile' }, h('div', { class: 'v' }, value), h('div', { class: 'k' }, label));
  $('#statTiles').replaceChildren(
    tile(hoursText(s.totals.hours), 'watched'),
    tile(s.totals.views.toLocaleString(), noun(s.totals.views, 'viewing')),
    tile(`${s.totals.watched} of ${s.stations.length}`, 'stations watched'),
    tile(String(s.watchingNow), 'watching now'));
  const most = Math.max(...s.stations.map(x => x.hours), 0) || 1;
  $('#statTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Station'), h('th', { class: 'num' }, 'Viewings'), h('th', {}, 'Watched'),
      h('th', { class: 'num' }, 'Average'), h('th', {}, 'Last watched'), h('th', {}, 'Most watched'))),
    h('tbody', {}, ...(s.stations.length ? s.stations.map(x => h('tr', {},
      h('td', { class: 'first' }, stationBadge(x)),
      h('td', { class: 'num', 'data-label': 'Viewings' }, x.views.toLocaleString()),
      h('td', { class: 'wide', 'data-label': 'Watched' }, h('div', { class: 'hcell', title: `${x.hours.toFixed(2)} hours` },
        h('div', {}, h('div', { class: 'hbar', style: `width:${(x.hours / most * 100).toFixed(1)}%` })),
        h('span', { class: 'small' }, x.hours ? hoursText(x.hours) : '—'))),
      h('td', { class: 'num', 'data-label': 'Average' }, x.views ? `${Math.round(x.averageMinutes)} min` : '—'),
      h('td', { class: 'small', 'data-label': 'Last watched' }, x.lastMs ? ago(x.lastMs) : '—'),
      h('td', { class: 'small', 'data-label': 'Most watched' }, x.top || '—')))
      : [h('tr', {}, h('td', { colspan: 6, class: 'muted' }, 'No stations yet.'))])));
  renderTop(s.people, s.media, s.usersProblem);
  const topMost = Math.max(...s.programs.map(p => p.hours), 0) || 1;
  $('#statPrograms').replaceChildren(...(s.programs.length ? s.programs.map(p => h('div', { class: 'toprow', title: `${p.hours.toFixed(2)} hours, on ${noun(p.stations.length, 'station')} ${p.stations.join(', ')}` },
    h('span', { class: 'name' }, p.title, h('span', { class: 'hint' }, p.kind === 'movie' ? ' · movie' : '')),
    h('div', {}, h('div', { class: 'hbar', style: `width:${(p.hours / topMost * 100).toFixed(1)}%` })),
    h('span', { class: 'small' }, hoursText(p.hours))))
    : [h('p', { class: 'muted small', style: 'margin:0' }, 'Nothing watched in this period.')]));
  const top = Math.max(...s.byHour, 0) || 1;

  $('#statHours').replaceChildren(
    h('div', { class: 'hours', role: 'img', 'aria-label': 'Hours watched by time of day' },
      ...s.byHour.map((v, n) => h('span', { style: `height:${(v / top * 100).toFixed(1)}%`, title: `${hourName(n)}: ${hoursText(v)}` }))),
    h('div', { class: 'hours-axis' }, ...[0, 6, 12, 18].map(n => h('span', {}, hourName(n)))));
}
document.querySelectorAll('[data-days]').forEach(b => b.addEventListener('click', () => { statDays = Number(b.dataset.days); loadStats(); }));
// Top people and Top Media (Admins only: the page gets `people` and `media` only then).
function renderTop(people, media, problem) {
  $('#statTop').hidden = !people;
  if (!people) return;
  const most = Math.max(...people.map(u => u.hours), 0) || 1;
  const list = (items, name) => items.map(x => `${name(x)} (${hoursText(x.hours)})`).join(', ');
  $('#statPeople').replaceChildren(
    ...(problem ? [h('p', { class: 'small', style: 'margin:0' }, warnIcon(), ' ', problem)] : []),
    ...(people.length ? people.map(u => h('div', { class: 'who' },
      h('div', { class: 'toprow', title: `${u.hours.toFixed(2)} hours` },
        h('span', { class: 'name' }, u.name, u.plex ? h('span', { class: 'hint' }, ' · Plex') : null),
        h('div', {}, h('div', { class: 'hbar', style: `width:${(u.hours / most * 100).toFixed(1)}%` })),
        h('span', { class: 'small' }, hoursText(u.hours))),
      h('div', { class: 'who-detail' },
        ...[u.stations.length ? `Stations: ${list(u.stations, x => `${x.number} ${x.name}`)}` : '',
          u.mediaHours ? `Media: ${hoursText(u.mediaHours)}` : '',
          u.programs.length ? `Shows & movies: ${list(u.programs, x => x.title)}` : '']
          .filter(Boolean).flatMap((line, n) => n ? [h('br'), line] : [line]))))
    : [h('p', { class: 'muted small', style: 'margin:0' }, 'No one watched in this period.')]));
  const top = Math.max(...media.map(m => m.hours), 0) || 1;
  $('#statMedia').replaceChildren(...(media.length ? media.map(m => h('div', { class: 'toprow', title: `${m.hours.toFixed(2)} hours, ${plural(m.plays, 'play')}` },
    h('span', { class: 'name' }, m.title, h('span', { class: 'hint' }, m.kind === 'movie' ? ' · movie' : '')),
    h('div', {}, h('div', { class: 'hbar', style: `width:${(m.hours / top * 100).toFixed(1)}%` })),
    h('span', { class: 'small' }, `${hoursText(m.hours)} · ${plural(m.plays, 'play')}`)))
    : [h('p', { class: 'muted small', style: 'margin:0' }, 'Nothing from Media was played in this period.')]));
}

// The server, now, and who's watching (Admins only): asked every 5 seconds
// while the Stats tab is showing.
let nowData = null;
async function loadNow() {
  if (!isAdmin()) { $('#statLive').hidden = true; return; }
  let d;
  try { d = await api('/api/stats/now'); } catch { return; }
  nowData = d;
  $('#statLive').hidden = false;
  renderHealth(d.server);
  renderNow(d.watching);
}
const pct = v => `${v < 10 ? v.toFixed(1) : Math.round(v)}%`;
const bytesText = b => b >= 1e12 ? `${(b / 1e12).toFixed(1)} TB` : b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`;
const mbpsText = m => `${m >= 10 ? Math.round(m) : m.toFixed(1)} Mbps`;
const agoS = s => s < 60 ? `${Math.round(s)} sec ago` : `${Math.round(s / 60)} min ago`;
function renderHealth(sv) {
  const hist = sv.history;
  const na = () => h('div', { class: 'v na' }, 'Not available');
  const last = vs => [...vs].reverse().find(v => v != null);
  const gauge = (key, label, value, sub, series, fmt, top) => {
    const el = h('div', { class: 'panel gauge', 'data-k': key },
      h('div', { class: 'k' }, label),
      value == null ? na() : h('div', { class: 'v' }, value),
      sub ? h('div', { class: 'sub' }, sub) : null);
    if (series && series.some(v => v != null)) el.append(sparkline(series, hist.atMs, fmt, top, label));
    return el;
  };
  const p = sv.processor, m = sv.memory, n = sv.network, g = sv.gpu, st = sv.storage;
  const things = (a, b) => `${plural(a, 'station')} and ${b} ${b === 1 ? 'copy' : 'copies'} on it now`;
  $('#healthTiles').replaceChildren(
    gauge('processor', 'Processor', p.own == null ? null : pct(p.own),
      p.machine == null ? 'Whole machine: not available' : `Whole machine: ${pct(p.machine)}${p.processors ? ` of ${plural(p.processors, 'processor')}` : ''}`,
      hist.processor, pct, () => 100),
    gauge('memory', 'Memory', m.own == null ? null : bytesText(m.own),
      m.used != null && m.total ? `${m.limit ? 'Container’s limit' : 'Whole machine'}: ${bytesText(m.used)} of ${bytesText(m.total)}` : 'Whole machine: not available',
      hist.memory, bytesText, vs => Math.max(...vs) * 1.15),
    gauge('sending', 'Sending', n.sending == null ? null : mbpsText(n.sending),
      last(hist.sending) == null ? null : `Peak ${mbpsText(Math.max(...hist.sending.filter(v => v != null)))}`,
      hist.sending, mbpsText, vs => Math.max(...vs, 1) * 1.15),
    gauge('receiving', 'Receiving', n.receiving == null ? null : mbpsText(n.receiving),
      last(hist.receiving) == null ? null : `Peak ${mbpsText(Math.max(...hist.receiving.filter(v => v != null)))}`,
      hist.receiving, mbpsText, vs => Math.max(...vs, 1) * 1.15),
    gauge('gpu', 'GPU', g.name ? g.name.split(' (')[0] : 'None',
      g.name ? things(g.stations, g.copies) : g.state === 'starting' ? 'Testing the GPU' : 'Video is encoded on the processor',
      g.name ? hist.gpu : null, v => `${v} on it`, vs => Math.max(...vs, 2) * 1.15),
    gauge('storage', 'Storage', st.free == null ? null : bytesText(st.free),
      st.total ? `free of ${bytesText(st.total)}, in the data folder` : null,
      hist.storage, v => `${bytesText(v)} free`, () => st.total || 1));
}
// One value's last 10 minutes as a line (a single series, on its own scale
// from zero), with its newest point marked. Pointing at it shows the value
// then, in the tile's own value and label.
function sparkline(values, times, fmt, top, label) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'spark');
  const known = values.filter(v => v != null);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${label}, the last 10 minutes: now ${fmt(known[known.length - 1])}, lowest ${fmt(Math.min(...known))}, highest ${fmt(Math.max(...known))}`);
  const draw = () => {
    const w = svg.clientWidth || 140, ht = 40, pad = 5;
    svg.setAttribute('viewBox', `0 0 ${w} ${ht}`);
    const most = Math.max(top(known) || 0, 1e-9);
    const span = Math.max(values.length - 1, 1);
    const x = i => pad + (w - 2 * pad) * (values.length === 1 ? 1 : i / span);
    const y = v => ht - pad - (ht - 2 * pad) * Math.min(1, v / most);
    const pts = values.map((v, i) => v == null ? null : [x(i), y(v)]);
    let d = '', area = '', run = [];
    const flush = () => {
      if (run.length) {
        d += 'M' + run.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join('L');
        area += `M${run[0][0].toFixed(1)},${ht - pad}L` + run.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join('L') + `L${run[run.length - 1][0].toFixed(1)},${ht - pad}Z`;
      }
      run = [];
    };
    for (const pt of pts) { if (pt) run.push(pt); else flush(); }
    flush();
    const end = [...pts].reverse().find(Boolean);
    svg.innerHTML = `<line class="base" x1="${pad}" x2="${w - pad}" y1="${ht - pad + .5}" y2="${ht - pad + .5}"/>`
      + `<path class="area" d="${area}"/><path class="line" d="${d}"/>`
      + `<line class="hair" y1="2" y2="${ht - pad}" visibility="hidden"/><circle class="dot" r="4" cx="${end[0]}" cy="${end[1]}"/>`;
    const hair = svg.querySelector('.hair'), dot = svg.querySelector('.dot');
    const tile = svg.closest('.gauge'), k = tile?.querySelector('.k'), v = tile?.querySelector('.v');
    const shown = [k?.textContent, v?.textContent];
    svg.onpointermove = e => {
      const r = svg.getBoundingClientRect();
      let i = Math.round((e.clientX - r.left - pad) / Math.max(w - 2 * pad, 1) * span);
      i = Math.max(0, Math.min(values.length - 1, i));
      while (i > 0 && pts[i] == null) i--;
      if (!pts[i]) return;
      hair.setAttribute('x1', pts[i][0]); hair.setAttribute('x2', pts[i][0]); hair.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', pts[i][0]); dot.setAttribute('cy', pts[i][1]);
      const back = (times[times.length - 1] - times[i]) / 1000;
      if (k && v) { k.textContent = `${shown[0]} · ${back < 3 ? 'now' : agoS(back)}`; v.textContent = fmt(values[i]); }
    };
    svg.onpointerleave = () => {
      hair.setAttribute('visibility', 'hidden');
      dot.setAttribute('cx', end[0]); dot.setAttribute('cy', end[1]);
      if (k && v) [k.textContent, v.textContent] = shown;
    };
  };
  requestAnimationFrame(draw);
  return svg;
}
const HOW = { direct: 'As it is', repackage: 'Repackaged', convert: 'Converted' };
// "Station 2, Cartoon Classics" (or just "Station 2", when its name says no more).
const stationLine = st => st.name && st.name.toLowerCase() !== `station ${st.number}` ? `Station ${st.number}, ${st.name}` : `Station ${st.number}`;
function renderNow(rows) {
  $('#nowCount').textContent = rows.length ? `${rows.length} watching` : '';
  if (!rows.length) {
    $('#statNow').replaceChildren(h('p', { class: 'muted small' }, 'No one is watching right now.'));
    return;
  }
  const sub = text => text ? h('div', { class: 'sub' }, text) : null;
  $('#statNow').replaceChildren(h('table', { class: 'now' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Who'), h('th', {}, 'Watching'), h('th', {}, 'How'), h('th', {}, 'App and device'), h('th', {}, 'Since'))),
    h('tbody', {}, ...rows.map(r => {
      const who = r.plex ? (r.who || 'Plex') : (r.who || (r.where ? 'Someone' : 'Another player'));
      const how = r.how;
      const size = [how.picture, how.mbps != null ? `${how.mbps} Mbps` : null].filter(Boolean).join(' at ');
      return h('tr', {},
        h('td', { class: 'now-who' }, h('strong', {}, who),
          r.plex ? h('span', { class: 'chip plain' }, 'Plex') : null,
          r.where ? h('span', { class: 'chip ' + (r.where === 'away' ? 'accent' : 'plain') }, r.where === 'away' ? 'Away' : 'Home') : null),
        h('td', { class: 'now-what' },
          r.station ? [h('div', {}, stationLine(r.station)), sub(r.station.program)]
            : [h('div', {}, r.media.title), sub('Media, on demand')]),
        h('td', { class: 'now-how', 'data-label': 'How' }, h('div', {}, HOW[how.method] || how.method),
          sub([size, how.on ? `on the ${how.on}` : null].filter(Boolean).join(' ')),
          ...(how.notes || []).map(n => sub(`With ${n}`))),
        h('td', { class: 'now-app', 'data-label': 'App and device' }, h('div', {}, r.app || (r.plex ? 'Plex' : 'An app')), sub(r.address)),
        h('td', { class: 'now-since', title: new Date(r.sinceMs).toLocaleString() }, ago(r.sinceMs)));
    }))));
}
window.addEventListener('resize', () => { if (currentTab === 'stats' && nowData) renderHealth(nowData.server); });
