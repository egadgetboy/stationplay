// StationPlay's page: The Stations tab: the list of stations, and the guide.
// Channels -------------------------------------------------------------------
let channels = [];
async function loadChannels() {
  try { channels = await api('/api/channels'); }
  catch (e) { toast(e.message, true); return; }
  renderChannels();
}

const icon = d => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 16 16'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.6'); s.innerHTML = d; return s; };

// How many more stations you may make: any number, unless you're a User with
// a limit (see access.py). The server decides; this just says so.
function stationsLeft() {
  const u = me.user;
  if (!u || u.role === 'admin' || u.maxStations == null) return Infinity;
  return u.maxStations - channels.filter(c => c.mine).length;
}
function renderRoom() {
  const left = stationsLeft();
  const full = left <= 0;
  for (const b of [$('#newChannel'), $('#fromCollections'), $('#smartStations')]) {
    b.disabled = full;
    b.dataset.tip ??= b.title;  // (its own tooltip, for when there's room again)
    b.title = full ? 'Delete one of your stations, or ask an Admin to raise your limit' : b.dataset.tip;
  }
  $('#roomHint').hidden = left === Infinity;
  if (left !== Infinity) {
    const made = channels.filter(c => c.mine).length;
    $('#roomHint').textContent = full
      ? `You can make ${plural(me.user.maxStations, 'station')}, and you’ve made ${made}`
      : `You can make ${plural(left, 'more station')}`;
  }
}

function renderChannels() {
  renderRoom();
  const box = $('#channels');
  const shown = channels.filter(c => !deleting.has(c.id));  // (not those being deleted)
  if (!shown.length) {
    box.replaceChildren(h('div', { class: 'panel empty' },
      h('h3', {}, 'No stations yet'),
      h('p', { class: 'muted' }, 'Pick some shows or movies from Plex, and StationPlay turns them into a station that plays around the clock.'),
      h('button', { class: 'btn primary', onclick: () => openEditor() }, 'Create your first station')));
    return;
  }
  const now = Date.now();
  box.replaceChildren(...shown.map(ch => {
    const n = ch.now;
    const pct = n ? Math.min(100, Math.max(0, (now - n.start) / (n.end - n.start) * 100)) : 0;
    const check = ch.check;
    const art = ch.logo
      ? h('div', { class: 'chart' }, logoImg(ch.logo), h('span', { class: 'no' }, ch.number))
      : h('div', { class: 'chnum' }, ch.number);
    const p = ch.pending;
    const change = ch.lastChange;
    return h('article', { class: 'panel channel' },
      art,
      h('div', {},
        h('div', { class: 'chname' }, ch.name,
          ch.offAir ? h('span', { class: 'chip bad', title: ch.offAirWhy === 'failing'
            ? 'This station’s stream keeps failing to start, so viewers see the off-air card. An Admin can see why on the Logs tab.'
            : 'Nothing on this station could play just now, so viewers see the off-air card. An Admin can see why on the Logs tab.' }, ch.offAirWhy === 'failing' ? 'Can’t start' : 'Off the air') : null,
          ch.brokenCount ? h('span', { class: 'chip bad', title: 'Programs on this station that are skipped because their files have problems' }, `${ch.brokenCount} broken`) : null,
          check?.running ? h('span', { class: 'chip accent' }, `Checking ${check.done} of ${check.total}`) : null,
          p && !p.held ? h('span', { class: 'chip accent', title: 'Changes from Plex are ready. They start at the next program break after Plex downloads the guide, so the Plex guide always matches.' }, `Update ready: ${changeText(p)}`) : null,
          p && p.held ? h('span', { class: 'chip bad', title: p.removed
              ? 'Plex no longer lists many of this station’s programs. This usually means a library is being rescanned or a drive is offline, so nothing changes until you choose Update now.'
              : p.lostSkips ? 'Plex no longer reports intros and credits for many of this station’s programs. This usually means Plex is detecting them again, so nothing changes until you choose Update now.'
              : 'Plex no longer lists the programs for one of this station’s blocks, or the movies for its Feature Presentation. This usually means a library is being rescanned or a drive is offline, so nothing changes until you choose Update now.' },
            p.removed ? `Plex lost ${plural(p.removed, 'program')} — needs your review` : p.lostSkips ? `Plex lost intros & credits for ${plural(p.lostSkips, 'program')} — needs your review` : 'Plex lost a special’s programs — needs your review') : null,
          madeText(ch)),
        ch.description ? h('div', { class: 'desc' }, ch.description) : null,
        n ? h('div', { class: 'now' },
          h('div', { class: 'label' }, n.special ? `On now · ${n.special}` : 'On now'),
          h('div', {}, epLabel(n)),
          h('div', { class: 'bar' }, h('span', { class: pct > 0 ? 'at' : '', style: `width:${pct.toFixed(1)}%` }))) : null,
        stationDetails(ch, check, now),
        h('div', { class: 'actions' },
          h('button', { class: 'btn', onclick: () => openGuide(ch) }, icon('<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M2 7h12M6 3v10"/>'), h('span', {}, 'Guide')),
          ...stationActions(ch, check))));
  }));
}
const SIZES = ['4K', '1080p', '720p', 'SD'];  // picture sizes, largest first
// A time of day ("20:00") as this browser says it ("8:00 PM").
function timeOfDay(time) {
  const [hh, mm] = String(time).split(':').map(Number);
  return new Date(2000, 0, 1, hh || 0, mm || 0).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
// Days as stored ("4,5") in a few words: "Fri, Sat", or "daily".
function daysWords(days) {
  const named = String(days).split(',').filter(d => /^[0-6]$/.test(d)).map(d => DAY_NAMES[d]);
  return named.length === 7 ? 'daily' : named.join(', ');
}
// How a station's specials are set, in a few words.
function marathonText(mode, aWeek, days, time) {
  if (mode === 'random') return `${plural(aWeek, 'marathon')} a week`;
  if (mode !== 'set') return '';
  return `marathons ${daysWords(days)} at ${timeOfDay(time)}`;
}
const featureText = (mode, days, time) => mode === 'on' ? `Feature Presentation ${daysWords(days)} at ${timeOfDay(time)}` : '';
const blockText = b => `${b.name || 'a block'} ${daysWords(b.days)} ${timeOfDay(b.start)}–${timeOfDay(b.end)}`;
function specialsText(st) {
  const parts = [
    marathonText(st.marathonMode, st.marathonsAWeek, st.marathonDays, st.marathonTime),
    featureText(st.featureMode, st.featureDays, st.featureTime),
    st.blocks?.length ? (st.blocks.length === 1 ? blockText(st.blocks[0]) : plural(st.blocks.length, 'block')) : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'None';
}
// How a station's other settings read in a few words: the same on its card
// as in the editor's groups.
const breaksText = n => n ? `${n} ${n === 1 ? 'commercial or trailer' : 'commercials or trailers'}` : 'No commercials';
const idText = (on, seconds, sound) => on ? `${seconds}-sec Station ID card${sound ? '' : ' (silent)'}` : 'no Station ID card';
const upNextText = seconds => seconds ? `${seconds}-sec Up Next Banner` : 'no Up Next Banner';
const tuneText = (video, seconds, sound, tuneIn) => (video ? 'Your own Intro Bumper video'
  : seconds ? `${seconds}-sec Intro Bumper${sound ? '' : ' (silent)'}` : 'Straight to the show')
  + (tuneIn === 'start' ? ', from the beginning' : '');
function cornerText(mark, clockFormat, position, style, timing) {
  const corner = { logo: 'Logo', name: 'Name', clock: `${clockFormat === '24' ? '24' : '12'}-hour clock` }[mark];
  if (!corner) return 'Nothing in the corner';
  return `${corner} ${(position || 'bottom-left').replace('-', ' ')}${mark === 'logo' && style === 'white' ? ', in white' : ''}${timing === 'start' ? ', at the start' : ''}`;
}
// A small red warning triangle.
function warnIcon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.innerHTML = '<path d="M8 1.8L15 14H1z" fill="currentColor"/><path d="M8 6v4" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="12" r=".9" fill="#fff"/>';
  return svg;
}
// What a station is and how it's set, in rows like the editor's groups:
// tidy to read at a glance, each with its details on hover.
function stationDetails(ch, check, now) {
  const row = (label, ...parts) => {
    const shown = parts.filter(Boolean);
    return shown.length ? [h('dt', {}, label), h('dd', {}, ...shown.flatMap((part, n) => n ? [h('span', { class: 'sep' }, ' · '), part] : [part]))] : [];
  };
  const text = (words, title) => h('span', title ? { title } : {}, words);
  const pic = ch.programPictures;
  const sizes = pic ? Object.entries(pic.counts).map(([size, n]) => `${n.toLocaleString()} in ${size}`).join(', ') : '';
  const change = ch.lastChange;
  const gist = [
    plural(ch.itemCount, 'program'),
    ch.orderMode === 'rotate' ? 'Episode order' : 'Shuffle',
    `plays at ${ch.picture}`,
  ].join(' · ');
  // Something wrong with the station itself, flagged on the summary while
  // the details are rolled up (broken files and updates have chips of
  // their own).
  const problems = [
    ch.offAir && ch.offAirWhy === 'failing' ? 'its stream keeps failing to start, so viewers see the off-air card (an Admin can see why on the Logs tab)' : '',
    ch.offAir && ch.offAirWhy !== 'failing' ? 'nothing on it could play just now, usually because Plex or your media can’t be reached, so viewers see the off-air card (an Admin can see why on the Logs tab)' : '',
    !ch.itemCount ? 'it has nothing to play' : ch.brokenCount >= ch.itemCount ? 'it has nothing to play because every program on it is broken' : '',
  ].filter(Boolean);
  return h('details', {
    class: 'more', open: openDetails.has(ch.id),
    ontoggle: e => { e.target.open ? openDetails.add(ch.id) : openDetails.delete(ch.id); saveOpenDetails(); },
  }, h('summary', {}, h('span', {}, `Details: ${gist}`),
      problems.length ? h('span', { class: 'warn', role: 'img', 'aria-label': `Needs attention: ${problems.join('; ')}`, title: `Needs attention: ${problems.join('; ')}` },
        warnIcon()) : null),
    h('dl', { class: 'details' },
    ...row('Programs',
      text(plural(ch.itemCount, 'program')),
      text(`each airs once every ${fmtDur(ch.loopMs)}`),
      pic ? text(pic.size === 'Mixed' ? `files: mixed sizes (${SIZES.filter(size => pic.counts[size]).join(', ')})` : `files: ${pic.size}`, `Picture sizes of the program files, according to Plex: ${sizes}. The station plays them all at its own size (${ch.picture}).`) : null),
    ...row('How it plays',
      text(ch.picture, 'The picture size the station plays everything at (set in its editor)'),
      text(ch.orderMode === 'rotate' ? 'Episode order' : 'Shuffle'),
      text(ASPECT_TEXT[ch.aspectMode] || ''),
      ch.skipIntros ? text(ch.trimmedCount ? `skips intros & credits (${ch.trimmedCount.toLocaleString()} of ${ch.itemCount.toLocaleString()})` : 'no intros or credits found yet',
        ch.trimmedCount
          ? `Plex has found intros or credits in ${ch.trimmedCount} of this station’s ${ch.itemCount} programs, and StationPlay skips them. The rest play in full.`
          : 'Plex hasn’t found intros or credits in any of this station’s programs yet. Turn on intro and credits detection in your Plex library settings. StationPlay picks them up within a few hours.')
        : text('plays intros & credits'),
      ch.mostlyOneShow ? text('mostly one show', 'One show makes up most of this station, so shuffle will sometimes play it three or more times in a row. Add more shows to avoid that.') : null),
    ...row('Specials',
      ch.marathonMode !== 'off' ? text(marathonText(ch.marathonMode, ch.marathonsAWeek, ch.marathonDays, ch.marathonTime)) : null,
      ch.marathonMode !== 'off' ? text(ch.nextMarathon ? `next: ${ch.nextMarathon.title} Marathon, ${fmtClock(ch.nextMarathon.at)}` : 'no marathon scheduled',
        ch.nextMarathon ? '' : 'For marathons, a station needs at least 5 shows with 3 or more episodes each.') : null,
      ch.featureMode === 'on' ? text(featureText(ch.featureMode, ch.featureDays, ch.featureTime)) : null,
      ch.featureMode === 'on' ? text(ch.nextFeature ? `next: ${ch.nextFeature.title}, ${fmtClock(ch.nextFeature.at)}` : 'no Feature Presentation scheduled',
        ch.nextFeature ? '' : 'It needs movies. This station has none of its own, or the library or collection it uses is empty.') : null,
      ...(ch.blocks || []).map(b => text(blockText(b))),
      ch.blocks?.length ? text(ch.nextBlock ? `next: ${ch.nextBlock.title}, ${fmtClock(ch.nextBlock.at)}` : 'no block scheduled',
        ch.nextBlock ? '' : 'A block needs shows that can play.') : null),
    ...row('Between programs',
      text(breaksText(ch.breaks), 'Commercials after each episode, trailers after each movie'),
      text(idText(ch.stationId, ch.idSeconds, ch.idSound))),
    ...row('On screen',
      text(cornerText(ch.watermark, ch.clockFormat, ch.watermarkPosition, ch.watermarkStyle, ch.watermarkTiming),
        ch.watermark !== 'off' ? `Size: ${ch.watermarkSize}, transparency: ${ch.watermarkTransparency}` : ''),
      text(upNextText(ch.upNextSeconds), ch.upNextSeconds ? `Size: ${ch.upNextSize}` : ''),
      SUBS_TEXT[ch.subtitles] ? text(SUBS_TEXT[ch.subtitles], 'Shown in the picture when a program has subtitles') : null),
    ...row('Tuning in',
      text(tuneText(ch.introVideo, ch.introSeconds, ch.introSound, ch.tuneIn),
        ch.tuneIn === 'start' ? 'The current program starts from the beginning, and the station runs that far behind the guide while anyone is watching' : '')),
    ...row('Status',
      change && change.reason !== 'created' && change.startsAt > now ? text(`changes at ${fmtClock(change.startsAt)}`) : null,
      change && change.reason !== 'created' && change.startsAt <= now && (change.added || change.removed)
        ? text(`updated ${ago(change.at)} (${changeText(change)})`, new Date(change.at).toLocaleString()) : null,
      ch.brokenCount ? text(`${plural(ch.brokenCount, 'broken file')}, skipped`, 'Listed on the Broken files tab') : null,
      check && !check.running && check.finishedAt ? text(`last check: ${check.newlyBroken ? `${check.newlyBroken} newly broken` : 'no new problems'}`) : null,
      ...problems.map(words => text(words)))));
}
// Who made a station and when, at the top right of its card: "Made by Pat",
// "Oct 3, 2026" (or "Made Oct 3, 2026" when who isn't known; "before" for a
// station made before StationPlay kept the date).
function madeText(ch) {
  if (!ch.createdAt && !ch.madeBy) return null;
  const made = new Date(ch.createdAt);
  const day = ch.createdAt ? `${ch.createdExact ? '' : 'on or before '}${made.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' })}` : '';
  const title = ch.createdAt ? (ch.createdExact ? `Made ${made.toLocaleString()}` : 'Made before StationPlay recorded creation dates. It was on the air by this date.') : '';
  return h('span', { class: 'made', title },
    ch.madeBy ? h('span', {}, `Made by ${ch.madeBy}`) : null,
    day ? h('span', {}, ch.madeBy ? day : `Made ${day}`) : null);
}
// Which stations' details are rolled down (rolled up unless you open them),
// remembered in this browser.
const DETAILS_KEY = 'stationplay.openDetails';
const openDetails = new Set();
try { for (const id of JSON.parse(localStorage.getItem(DETAILS_KEY) || '[]')) if (Number.isInteger(id)) openDetails.add(id); } catch {}
function saveOpenDetails() {
  try { localStorage.setItem(DETAILS_KEY, JSON.stringify([...openDetails])); } catch {}
}
function stationActions(ch, check) {
  const duplicate = stationsLeft() > 0
    ? h('button', { class: 'btn', title: 'Make a new station with the same shows and settings, then change it as you like', onclick: () => openEditor(ch, true) },
        icon('<rect x="5" y="5" width="8.5" height="8.5" rx="1.5"/><path d="M3 10.5V3.5A1 1 0 0 1 4 2.5h6.5"/>'), h('span', {}, 'Duplicate'))
    : null;
  // (Changing it is for an Admin, or whoever made it.)
  if (!ch.mayChange) return [duplicate];
  return [
          h('button', { class: 'btn', onclick: () => openEditor(ch) }, icon('<path d="M11 2.5l2.5 2.5L6 12.5H3.5V10z"/>'), h('span', {}, 'Edit')),
          duplicate,
          h('button', { class: 'btn', disabled: check?.running, title: 'Check every file on this station now, so problems are found before anyone tunes in', onclick: () => checkChannel(ch) }, icon('<path d="M3 8.5l3 3 7-7"/>'), h('span', {}, 'Check files')),
          h('button', { class: 'btn', title: 'Check Plex for new and removed programs now. Changes start at the next program break.', onclick: () => updateNow(ch) }, icon('<path d="M13 3v4H9"/><path d="M13 7A5 5 0 1 0 12 12"/>'), h('span', {}, 'Update now')),
          ch.orderMode === 'shuffle' ? h('button', { class: 'btn', title: 'Start a new random order at the next program break', onclick: () => reshuffle(ch) }, icon('<path d="M2 4h3l6 8h3M2 12h3l6-8h3"/>'), h('span', {}, 'Reshuffle')) : null,
          h('button', { class: 'btn danger', onclick: () => removeChannel(ch) }, icon('<path d="M3 4h10M6 4V2.5h4V4M5 4l.5 9h5L11 4"/>'), h('span', {}, 'Delete')),
  ];
}

async function checkChannel(ch) {
  try { await api(`/api/channels/${ch.id}/check`, { method: 'POST' }); toast(`Checking every file on ${ch.name}…`); loadChannels(); }
  catch (e) { toast(e.message, true); }
}
const changeText = c => [c.added ? `${c.added} new` : '', c.removed ? `${c.removed} removed` : ''].filter(Boolean).join(', ')
  || (c.specials ? 'new programs for its specials' : 'updated run times');
// A time, with the day too if it isn't today.
function fmtClock(ms) {
  const d = new Date(ms);
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return d.toDateString() === new Date().toDateString()
    ? time
    : `${d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} ${time}`;
}
function ago(ms) {
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const hrs = Math.round(m / 60);
  return hrs < 48 ? `${hrs} hr ago` : `${Math.round(hrs / 24)} days ago`;
}
function changedMessage(res) {
  const when = res.lastChange?.startsAt ? `at ${fmtClock(res.lastChange.startsAt)}` : 'shortly';
  const guide = res.plexGuideRefreshed ? 'The Plex guide is being refreshed.' : 'Refresh the guide in Plex so it matches.';
  return `${res.name} changes ${when}. ${guide}`;
}
async function updateNow(ch) {
  try {
    const res = await api(`/api/channels/${ch.id}/update`, { method: 'POST' });
    toast(res.changed ? changedMessage(res) : `${ch.name} is already up to date`);
    loadChannels();
  } catch (e) { toast(e.message, true); }
}
async function reshuffle(ch) {
  if (!confirm(`Reshuffle ${ch.name}? A new random order starts at the next program break.`)) return;
  try { toast(changedMessage(await api(`/api/channels/${ch.id}/reshuffle`, { method: 'POST' }))); loadChannels(); }
  catch (e) { toast(e.message, true); }
}
// A station deleted here goes from the list straight away, but is only
// deleted UNDO_S seconds later, so Undo can bring it back as it was. (If
// the page is closed first, it's deleted then.)
const UNDO_S = 10;
const deleting = new Map();  // station id: its timer
async function removeChannel(ch) {
  if (deleting.has(ch.id)) return;
  deleting.set(ch.id, setTimeout(() => reallyDelete(ch), UNDO_S * 1000));
  renderChannels();
  toastWithUndo(`Station ${ch.number}${ch.name === `Station ${ch.number}` ? '' : ` (${ch.name})`} deleted`, () => {
    clearTimeout(deleting.get(ch.id));
    deleting.delete(ch.id);
    renderChannels();
    toast(`Station ${ch.number} is back`);
  });
}
async function reallyDelete(ch) {
  try { await api(`/api/channels/${ch.id}`, { method: 'DELETE' }); }
  catch (e) { if (e.status !== 404) toast(`Couldn’t delete station ${ch.number}: ${e.message}`, true); }
  deleting.delete(ch.id);
  loadChannels();
}
window.addEventListener('pagehide', () => {
  for (const [id, timer] of deleting) {
    clearTimeout(timer);
    fetch(`/api/channels/${id}`, { method: 'DELETE', keepalive: true }).catch(() => {});
  }
  deleting.clear();
});

// Guide ------------------------------------------------------------------------
async function openGuide(ch) {
  $('#guideTitle').textContent = `${ch.number} · ${ch.name} — up next`;
  $('#guideList').replaceChildren(h('p', { class: 'muted' }, 'Loading…'));
  $('#guide').showModal();
  try {
    const slots = await api(`/api/channels/${ch.id}/guide?hours=48`);
    const now = Date.now();
    $('#guideList').replaceChildren(...slots.map(s => h('div', { class: 'gitem' },
      h('div', {},
        s.start <= now && now < s.end ? h('div', { class: 'label' }, 'On now') : null,
        s.special ? h('div', { class: 'label' }, s.special) : null,
        h('div', { class: 'what' }, guideLabel(s))),
      s.broken ? h('span', { class: 'chip bad', title: 'This file is broken, so another program will play instead' }, 'replaced') : h('span'))),
      h('p', { class: 'hint', style: 'margin-top:10px' }, 'The next 2 days, the same period the Plex guide covers.'));
  } catch (e) { $('#guideList').replaceChildren(h('p', { class: 'muted' }, e.message)); }
}
$('#closeGuide').addEventListener('click', () => $('#guide').close());
