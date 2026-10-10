// StationPlay's page: The tab row's fit, Appearance, and the Add to Plex tab's panels.
// The Buy Me a Coffee link is never why a tab is out of sight: it's its cup
// and words if the tabs all fit beside them, else just its cup if they fit
// beside that, else left out if that makes them fit; when they don't fit
// even then (a phone), it's its cup, and the tabs go on to a second row, so
// every one is in sight. Looked at again when the window or a tab changes
// size (a tab shown or hidden, the Broken files count). (Only the row and
// the tabs are watched, which the link's own size doesn't change, so it
// settles at once.)
function fitCoffee() {
  const nav = $('nav.tabs'), link = $('.coffee');
  const fits = () => nav.scrollWidth <= nav.clientWidth + 1;
  nav.classList.remove('rows');
  link.hidden = false;
  link.classList.remove('compact');
  if (fits()) return;
  link.classList.add('compact');
  if (fits()) return;
  link.hidden = true;
  if (fits()) return;
  link.hidden = false;
  nav.classList.add('rows');
}
if ('ResizeObserver' in window) {
  const watch = new ResizeObserver(fitCoffee);
  watch.observe($('.tabrow'));
  document.querySelectorAll('nav.tabs .tab').forEach(t => watch.observe(t));
} else {
  $('.coffee').classList.add('compact');
}
$('#runSetup').addEventListener('click', runSetup);
$('#footSetup').addEventListener('click', runSetup);

// Appearance: Automatic follows the device; Light or Dark is kept for this
// browser in a cookie, which StationPlay reads so the page starts in it.
const appearance = $('#appearance');
appearance.value = document.documentElement.dataset.theme || '';
appearance.addEventListener('change', () => {
  const theme = appearance.value;
  document.cookie = theme
    ? `stationplay_theme=${theme}; path=/; max-age=31536000; SameSite=Lax`
    : 'stationplay_theme=; path=/; max-age=0; SameSite=Lax';
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  fitThemeColor();
});
// The window's own color (an installed app's title bar, a phone browser's
// bars): the page's background, light or dark as the device is, or as
// chosen under Appearance.
const themeColors = [...document.querySelectorAll('meta[name="theme-color"]')].map(m => [m, m.content]);
function fitThemeColor() {
  const chosen = document.documentElement.dataset.theme;
  const background = getComputedStyle(document.body).backgroundColor;
  for (const [meta, own] of themeColors) meta.content = chosen ? background : own;
}
fitThemeColor();

function renderMediaAccess(m) {
  const el = $('#mediaAccess');
  if (!m) return;
  const maps = m.mappings.map(x => `Plex’s ${x.plex} → ${x.local}`).join(', ');
  let text, cls;
  if (m.direct && !m.viaPlex) {
    text = `Read directly from disk${maps ? ` (${maps})` : ''}.`; cls = 'chip good';
  } else if (m.viaPlex) {
    text = `${m.viaPlex} of ${m.direct + m.viaPlex} files were streamed from Plex because StationPlay couldn’t find them in ${m.mediaDir}. That works, but mounting your media folder there is faster and puts less load on Plex.`;
    cls = 'chip bad';
  } else if (!m.mediaDirPresent) {
    text = `Nothing is mounted at ${m.mediaDir}, so files will be streamed from Plex. Mount your media folder there to read files directly.`;
    cls = 'chip accent';
  } else {
    text = `Media folder found at ${m.mediaDir}. Once a station plays, this shows whether StationPlay can read your files there.`;
    cls = '';
  }
  el.className = 'small';
  el.replaceChildren(cls ? h('span', { class: `${cls} note` }, text) : text);
}

function renderEncoding(e) {
  const el = $('#encoding');
  if (!e) return;
  const chip = (cls, text) => h('span', { class: `${cls} note` }, text);
  let content;
  if (e.state === 'starting') {
    content = 'Checking for a GPU…';
  } else if (e.state === 'gpu') {
    const extra = e.gpuFailures
      ? ` ${plural(e.gpuFailures, 'program')} had a GPU problem and finished on the CPU.` : '';
    const copies = e.copiesOnCpu
      ? ' Copies for StationPlay’s apps are converted on the CPU, since 3 in a row had a GPU problem (restart StationPlay to try the GPU again).' : '';
    content = chip('chip good', `${e.active}.${extra}${copies}`);
  } else if (e.state === 'disabled') {
    content = chip('chip bad', e.note);
  } else {
    content = chip('chip accent', `CPU. ${e.note}`);
  }
  el.replaceChildren(content);
}

function renderGuideState(g) {
  if (!g) return;
  const when = g.plexDownloadedGuide ? new Date(g.plexDownloadedGuide).toLocaleString() : null;
  const text = [
    when ? `Plex last downloaded the guide on ${when}.` : 'Plex hasn’t downloaded the guide yet.',
    g.canRefreshPlexGuide
      ? 'When a station changes, StationPlay asks Plex to refresh the guide.'
      : 'Once StationPlay is set up in Plex’s Live TV & DVR, it will ask Plex to refresh the guide whenever a station changes.',
  ].join(' ');
  $('#guideState').replaceChildren(h('span', { class: g.canRefreshPlexGuide ? 'chip good note' : 'chip accent note' }, text));
}

const betweenText = { commercials: 'Commercials', trailers: 'Trailers', 'station id': 'Station ID' };
function renderLive() {
  const list = $('#liveList');
  list.replaceChildren(...(status?.streams || []).filter(s => s.number != null && s.viewers > 0).map(s =>
    h('div', { class: 'panel live' },
      h('span', { class: 'dot live' }),
      h('strong', {}, `${s.number} ${s.name}`),
      h('span', { class: 'muted small' }, s.between ? `${betweenText[s.between.kind] || 'Between programs'} after ${epLabel(s.between.after)}`
        : s.playing ? epLabel(s.playing) : 'starting…'),
      s.replaced ? h('span', { class: 'chip accent', title: `Playing in place of ${epLabel(s.scheduled)}` }, 'replacement') : null,
      s.offAir ? h('span', { class: 'chip bad', title: s.offAirWhy === 'failing'
        ? 'This station’s stream keeps failing to start, so viewers see the off-air card. An Admin can see why on the Logs tab.'
        : 'Nothing on this station could play just now, so viewers see the off-air card. An Admin can see why on the Logs tab.' }, s.offAirWhy === 'failing' ? 'CAN’T START' : 'OFF THE AIR') : null,
      h('span', { class: 'spacer' }),
      h('span', { class: 'small muted' }, plural(s.viewers, 'connection')),
    )));
  list.style.marginBottom = list.children.length ? '12px' : '0';
}

document.querySelectorAll('[data-copy]').forEach(btn => btn.addEventListener('click', async () => {
  const text = $('#' + btn.dataset.copy).textContent;
  if (await copyText(text)) toast('Copied'); else toast(text);
}));
