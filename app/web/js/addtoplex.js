// The tab row's fit, Appearance, and the Setup tab's panels.
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
// browser in a cookie, which tapiOca reads so the page starts in it.
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

// (`plex`: whether tapiOca uses Plex; without it, nothing's said about
// Plex: 1.35.0. `folders`: your own Media folders, {count, missing}; left
// out, as status.js calls it, they're the status's once an Admin has
// chosen what tapiOca uses, and none before: 1.36.0's line, 1.37.0.)
function renderMediaAccess(m, plex = true, folders = undefined) {
  const el = $('#mediaAccess');
  if (!m) return;
  if (folders === undefined) folders = typeof status !== 'undefined' && status?.uses?.saved ? status.folders : null;
  const maps = m.mappings.map(x => `Plex’s ${x.plex} → ${x.local}`).join(', ');
  let text, cls;
  // (Nothing at MEDIA_DIR first: once a station has played, files have
  // streamed from Plex too, and the advice is the same. The fourth audit.)
  if (!m.mediaDirPresent && !m.mappings.length) {
    // (Not "Mount your media folder there": MEDIA_DIR is where tapiOca sees
    // the folder, inside its container, and that advice sent the owner to
    // his server's own path, October 13. Setup's first step finds where it
    // is instead.)
    text = `Nothing is at ${m.mediaDir} inside tapiOca. Run setup again: its first step says what to change.${plex ? ' Until then, Plex’s files are streamed from Plex.' : ''}`;
    cls = 'chip accent';
  } else if (m.direct && !m.viaPlex) {
    text = `Read directly from disk${maps ? ` (${maps})` : ''}.`; cls = 'chip good';
  } else if (m.viaPlex) {
    text = `${m.viaPlex} of ${m.direct + m.viaPlex} files were streamed from Plex because tapiOca couldn’t find them. That works, but reading them from disk is faster and puts less load on Plex. Run setup again: its Connecting your apps step says what to change.`;
    cls = 'chip bad';
  } else if (!m.mediaDirPresent) {
    text = `Nothing is at ${m.mediaDir} inside tapiOca, so files are read from the folders PATH_MAPPINGS names.`;
    cls = '';
  } else {
    text = `Media folder found at ${m.mediaDir}. Once a station plays, this shows whether tapiOca can read your files there.`;
    cls = '';
  }
  el.className = 'small';
  const own = folders?.count ? [` tapiOca reads your ${plural(folders.count, 'Media folder')} from ${m.mediaDir}.`] : [];
  if (own.length && folders.missing) own.push(' ', h('span', { class: 'chip bad note' }, `${folders.missing} can’t be read now: see Your own folders, below.`));
  el.replaceChildren(cls ? h('span', { class: `${cls} note` }, text) : text, ...own);
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
      ? ' Copies for tapiOca’s apps are converted on the CPU, since 3 in a row had a GPU problem (restart tapiOca to try the GPU again).' : '';
    content = chip('chip good', `${e.active}.${extra}${copies}`);
  } else if (e.state === 'disabled') {
    content = chip('chip bad', e.note);
  } else {
    content = chip('chip accent', `CPU. ${e.note}`);
  }
  el.replaceChildren(content);
}

// (Plex's alone: hidden where tapiOca doesn't use Plex.) Called with each
// status (status.js), so each place's section on the Setup tab is painted
// first, with Plex's line in it (1.37.0). `el`: a line of its own (the
// setup's), not the Setup tab's.
function renderGuideState(g, plex = true, el = null) {
  if (!el && typeof renderPlaces === 'function') renderPlaces();
  el ??= $('#guideState');
  if (!el) return;
  if (el.parentElement) el.parentElement.hidden = !plex;
  if (!g) return;
  const when = g.plexDownloadedGuide ? new Date(g.plexDownloadedGuide).toLocaleString() : null;
  const text = [
    when ? `Plex last downloaded the guide on ${when}.` : 'Plex hasn’t downloaded the guide yet.',
    g.canRefreshPlexGuide
      ? 'When a station changes, tapiOca asks Plex to refresh the guide.'
      : 'Once tapiOca is set up in Plex’s Live TV & DVR, it will ask Plex to refresh the guide whenever a station changes.',
  ].join(' ');
  el.replaceChildren(h('span', { class: g.canRefreshPlexGuide ? 'chip good note' : 'chip accent note' }, text));
}

// Each place you watch (1.37.0): how to add tapiOca to it, and how it's
// doing, as far as tapiOca can tell (when it last downloaded the guide, by
// the name it gives: see updates.py). On the Setup tab, under Tuner
// integration, and in the setup's Connecting your apps (`inSetup`: with
// the addresses it uses, as there's no panel of them above; `addresses`:
// with them on the Setup tab too, under More ways to watch, where the
// panel above leaves out what isn't chosen).
const WATCH_PLACES = ['tapioca', 'plex', 'jellyfin', 'emby', 'kodi', 'other'];
const PLACE_NAMES = { tapioca: 'tapiOca’s apps', plex: 'Plex', jellyfin: 'Jellyfin', emby: 'Emby', kodi: 'Kodi', other: 'Other apps' };
const GUIDE_FRESH_MS = 2 * 24 * 3600 * 1000;  // (a guide downloaded within 2 days: in use)
// The addresses shown for what's chosen (nothing chosen: all of them).
function copyRowsShown(watchIn) {
  const plex = !watchIn || watchIn.includes('plex');
  const others = !watchIn || ['jellyfin', 'emby', 'kodi', 'other'].some(p => watchIn.includes(p));
  return { tuner: plex, xmltv: plex, m3u: others, guide: others };
}
// "Downloaded the guide 3 hr ago", "Last downloaded the guide 5 days ago",
// or `never` (the words and the chip's color).
function downloadedChip(ms, never) {
  if (!ms) return h('span', { class: `chip ${never[0]}` }, never[1]);
  return Date.now() - ms < GUIDE_FRESH_MS
    ? h('span', { class: 'chip good' }, `Downloaded the guide ${ago(ms)}`)
    : h('span', { class: 'chip accent' }, `Last downloaded the guide ${ago(ms)}`);
}
function placeSection(place, st, opts = {}) {
  const guide = st?.guide || null;
  const tuner = opts.urls?.tuner || st?.tunerUrl || '';
  const urls = {
    tuner, xmltv: opts.urls?.xmltv || st?.xmltvUrl || (tuner && `${tuner}/xmltv.xml`),
    m3u: st?.m3uUrl || (tuner && `${tuner}/stations.m3u`), guide: st?.guideUrl || (tuner && `${tuner}/guide.xml`),
  };
  const copyRow = (what, value) => value ? h('div', { class: 'copyrow' }, h('span', { class: 'what' }, what), h('code', {}, value), copyButton(value)) : null;
  const hint = (...kids) => h('p', { class: 'hint', style: 'margin:0' }, ...kids);
  const em = text => h('em', {}, text);
  let chip = null, rows = [], lines = [], steps = [], notes = [];
  if (place === 'plex') {
    const configured = opts.plexConfigured ?? st?.plex?.configured;
    if (guide) {
      chip = configured
        ? h('span', { class: `chip ${guide.canRefreshPlexGuide ? 'good' : 'accent'}` }, guide.canRefreshPlexGuide ? 'In Plex' : 'Not added yet')
        : downloadedChip(guide.plexDownloadedGuide, ['accent', 'Not added yet']);
    }
    if (opts.inSetup || opts.addresses) rows = [copyRow('Tuner address', urls.tuner), copyRow('Guide (XMLTV) for Plex', urls.xmltv)];
    if (configured) {
      // (The Setup tab's own line, moved here; the setup's, a line of its own.)
      if (opts.guideRow) lines = [opts.guideRow];
      else if (guide) {
        const own = h('span', { class: 'small' });
        renderGuideState(guide, true, own);
        lines = [own];
      }
    } else if (guide) {
      const when = guide.plexDownloadedGuide ? new Date(guide.plexDownloadedGuide).toLocaleString() : null;
      lines = [hint(when ? `Plex last downloaded the guide on ${when}.` : 'Plex hasn’t downloaded the guide yet.',
        ' With PLEX_URL and PLEX_TOKEN set, tapiOca also asks Plex to refresh its guide when a station changes. Until then, refresh it in Plex after you change a station: ',
        em('Settings → Live TV & DVR → your tuner → Refresh Guide'), '.')];
    }
    const where = opts.inSetup || opts.addresses ? 'above' : 'shown above';
    steps = [
      h('li', {}, 'In Plex, open ', em('Settings → Live TV & DVR → Set Up Plex DVR'), '.'),
      h('li', {}, 'Choose ', em('Don’t see your HDHomeRun device? Enter its network address manually'), ' (Plex can’t find tapiOca on its own) and enter the tuner address above.'),
      h('li', {}, 'When Plex asks for guide data, choose ', em('Have an XMLTV guide on your server? Click here to use it'), ` and enter the guide address for Plex, ${where}.`),
      h('li', {}, 'Plex matches your stations automatically (it calls them channels). Continue, and they appear in the ', em('Live TV'), ' guide in Plex.'),
      opts.inSetup ? h('li', {}, 'Then choose Check again here.') : null,
    ];
    notes = [
      configured
        ? hint('tapiOca keeps the Plex guide up to date on its own: when a station changes, it asks Plex to refresh the guide. If it can’t, refresh the guide in Plex after you change a station: ', em('Settings → Live TV & DVR → your tuner → Refresh Guide'), '. For a new station, also choose ', em('Scan for channels'), ' there so Plex adds it.')
        : hint('After you make a new station, choose ', em('Scan for channels'), ' in Plex’s Live TV & DVR settings so Plex adds it.'),
      opts.inSetup ? hint('Plex needs at least one station to add tapiOca, so a new tapiOca starts with INFO on station 99: the date and time, what’s new in tapiOca and tips for watching. It plays even before Plex is connected.') : null,
      hint('Watching in Plex needs Plex Pass on the account that owns your Plex server.'),
    ];
  } else if (place === 'tapioca') {
    lines = [
      hint(`In the app, enter this server’s address: ${tuner}.`),
      st?.away ? hint(`Away from home: ${awaySummary(st.away)}.`) : null,
      hint('Signing in, Away from home and Media in the apps are on the Access tab.'),
    ];
  } else {
    const name = PLACE_NAMES[place];
    const seen = guide?.downloads?.[place] || 0;
    if (guide) chip = downloadedChip(seen, ['plain', 'Not seen yet']);
    if (opts.inSetup || opts.addresses) rows = [copyRow('Playlist (M3U) for other apps', urls.m3u), copyRow('Guide for other apps', urls.guide)];
    lines = [
      place === 'jellyfin'
        ? hint('Jellyfin downloads the guide on its own schedule, about once a day. After you change a station, refresh it in Jellyfin: ', em('Dashboard → Scheduled Tasks → Refresh Guide'), '.')
        : place === 'other'
          ? hint('Other apps download the guide on their own schedule, about once a day. After you change a station, refresh the guide in the app to see it right away.')
          : hint(`${name} downloads the guide on its own schedule, about once a day. After you change a station, refresh the guide in ${name} to see it right away.`),
      guide && !seen ? hint(`${place === 'other' ? 'No other app has' : `${name} hasn’t`} downloaded the guide yet, as far as tapiOca can tell: it knows each app by the name it gives.`) : null,
    ];
    steps = {
      jellyfin: [
        h('li', {}, 'In Jellyfin’s dashboard, open ', em('Live TV'), ' and choose ', em('+'), ' next to ', em('Tuner Devices'), '.'),
        h('li', {}, 'Choose ', em('M3U Tuner'), ' and enter the playlist address above. Save.'),
        h('li', {}, 'Choose ', em('+'), ' next to ', em('TV Guide Data Providers'), ', choose ', em('XMLTV'), ' and enter the guide address for other apps, above. Save.'),
      ],
      emby: [
        h('li', {}, 'In Emby’s settings, open ', em('Live TV'), ' and add a TV source. Choose ', em('M3U Tuner'), ' and enter the playlist address above.'),
        h('li', {}, 'Add a guide data provider. Choose ', em('XMLTV'), ' and enter the guide address for other apps, above.'),
      ],
      kodi: [
        h('li', {}, 'Install Kodi’s PVR Simple Client add-on (', em('Add-ons → Install from repository → PVR clients'), ').'),
        h('li', {}, 'In its settings, set the playlist location to remote and set ', em('M3U play list URL'), ' to the playlist address above. The playlist includes the guide’s address, so ', em('XMLTV URL'), ' can stay empty. You can also enter the guide address for other apps there.'),
        h('li', {}, 'Restart Kodi, or turn the add-on off and on. Your stations appear under ', em('TV'), '.'),
      ],
      other: [h('li', {}, 'Channels DVR and VLC accept the playlist address above. It tells them where to find the guide.')],
    }[place];
    notes = [
      place === 'jellyfin' ? hint('Leave Jellyfin’s limit on simultaneous streams at its default (no limit). tapiOca enforces its own.') : null,
      place === 'emby' ? hint('Emby’s Live TV needs Emby Premiere.') : null,
    ];
  }
  const heading = place === 'tapioca' || place === 'other' ? PLACE_NAMES[place] : `Adding tapiOca to ${PLACE_NAMES[place]}`;
  return h('div', { class: `${opts.inSetup ? '' : 'panel setup '}place`, 'data-place': place },
    h('div', { class: 'place-head' }, h('h3', { class: 'place-title' }, heading), chip),
    ...rows, ...lines,
    ...(steps.filter(Boolean).length ? [h(place === 'other' ? 'ul' : 'ol', { class: 'steps' }, ...steps)] : []),
    ...notes);
}

// The Setup tab's places, painted with each status (see renderGuideState):
// while where you watch isn't chosen, 1.36.0's panel as it is; once it is,
// What you use, the addresses each chosen place needs, a section for each,
// and the others under More ways to watch (never gone). Painted again only
// when something they show changes (at most once a minute for the "ago"s),
// so a section isn't redrawn under someone reading it.
let placesKey = null, guideRow = null;
function renderPlaces(st = status) {
  if (!st?.tunerUrl) return;
  renderUsesPanel(st);
  sayWhoNeverSignsIn(st);
  const chosen = st.uses?.saved && Array.isArray(st.uses.watchIn) ? st.uses.watchIn : null;
  const sources = st.uses?.sources || [];
  // Your own folders: where they're chosen, or any exist, or nothing is.
  $('#ownFolders').hidden = !!st.uses?.saved && !sources.includes('folders') && !st.folders?.count;
  const g = st.guide || {};
  const key = JSON.stringify([chosen, sources, st.plex?.configured, g.plexDownloadedGuide, g.canRefreshPlexGuide,
    g.downloads, st.tunerUrl, st.away?.on, st.away?.ready, chosen && Math.floor(Date.now() / 60000)]);
  if (key === placesKey) return;
  placesKey = key;
  guideRow ??= $('#guideState').parentElement;
  const shown = copyRowsShown(chosen);
  for (const [row, on] of Object.entries(shown)) $(`#${row}Row`).hidden = !on;
  $('#tunerIntro').textContent = chosen
    ? 'How to add tapiOca to each place you watch, and how each is doing.'
    : 'The addresses Plex, Jellyfin, Emby, Kodi and other apps use to watch your stations, and how to add them.';
  const legacy = $('#placesBefore');
  legacy.hidden = !!chosen;
  if (!chosen) {
    legacy.before(guideRow);
    $('#placesPanel').replaceChildren();
    $('#placesPanel').hidden = true;
    $('#morePlaces').hidden = true;
    return;
  }
  // (Plex's guide line, where tapiOca can ask Plex to refresh it.)
  const plexLine = st.plex?.configured ? guideRow : null;
  if (!plexLine) $('#guideRowParked').append(guideRow);
  const section = (p, addresses = false) => placeSection(p, st, { guideRow: p === 'plex' ? plexLine : null, addresses });
  const plexToo = chosen.includes('plex') || sources.includes('plex');
  $('#placesPanel').replaceChildren(...WATCH_PLACES.filter(p => chosen.includes(p)).map(p => section(p)),
    // (Plex's terms, wherever Plex is a source or a place: see setup.js.)
    ...(plexToo ? [h('div', { class: 'panel setup' }, PERSONAL_USE())] : []));
  $('#placesPanel').hidden = false;
  const others = WATCH_PLACES.filter(p => !chosen.includes(p));
  $('#morePlaces').hidden = !others.length;
  $('#morePlacesBody').replaceChildren(...others.map(p => section(p, true)));
}
// The Access tab's footer: who never signs in, by where you watch (its
// first words; 1.36.0's while nothing is chosen).
function whoNeverSignsIn(watchIn) {
  if (!watchIn) return 'Plex, Jellyfin and other apps never sign in,';
  const names = ['plex', 'jellyfin', 'emby', 'kodi'].filter(p => watchIn.includes(p))
    .map(p => ({ plex: 'Plex', jellyfin: 'Jellyfin', emby: 'Emby', kodi: 'Kodi' })[p]);
  if (watchIn.includes('other')) names.push('other apps');
  if (!names.length) return 'Apps other than tapiOca’s never sign in,';
  const text = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  const one = names.length === 1 && names[0] !== 'other apps';
  return `${text[0].toUpperCase()}${text.slice(1)} ${one ? 'never signs in' : 'never sign in'},`;
}
let neverSignInRest = null;  // (the footer's words after its first ones)
function sayWhoNeverSignsIn(st) {
  const first = $('#neverSignIn')?.firstChild;
  if (!first || first.nodeType !== Node.TEXT_NODE) return;
  if (neverSignInRest === null) {
    const at = first.nodeValue.indexOf(' never sign in,');
    if (at < 0) return;
    neverSignInRest = first.nodeValue.slice(at + ' never sign in,'.length);
  }
  const chosen = st.uses?.saved && Array.isArray(st.uses.watchIn) ? st.uses.watchIn : null;
  first.nodeValue = whoNeverSignsIn(chosen) + neverSignInRest;
}
// What you use, on the Setup tab: the setup's two questions, with Save.
// Made again when what's saved changes (unless it's being changed here).
let usesShown = null, usesForm = null;
async function renderUsesPanel(st) {
  const key = JSON.stringify([st.uses, st.plex?.configured, st.folders?.count]);
  if (key === usesShown || usesForm?.changed()) return;
  usesShown = key;
  let got;
  try { got = await api('/api/setup/uses'); } catch { usesShown = null; return; }
  const summary = $('#usesSum');
  const words = usesWords(got.sources, got.watchIn);
  summary.textContent = words.sources || words.watchIn
    ? [words.sources, words.watchIn && `watched in ${words.watchIn.startsWith('O') ? `o${words.watchIn.slice(1)}` : words.watchIn}`].filter(Boolean).join(' · ')
    : 'Not chosen yet';
  const said = h('span', { class: 'hint', role: 'status' });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    save.disabled = true;
    try {
      await api('/api/setup/uses', { method: 'PUT', body: usesForm.values() });
      said.textContent = '';
      usesForm = null;
      usesShown = null;
      toast('Saved');
      loadStatus();
    } catch (e) { said.textContent = e.message; }
    save.disabled = false;
  } }, 'Save');
  usesForm = usesFields(got, { onTab: true });
  const panel = $('#usesPanel');
  if (!got.sources && !got.watchIn) panel.open = true;
  $('#usesBody').replaceChildren(usesForm.sources, usesForm.watchIn, h('div', { class: 'row-btns' }, save, said));
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
