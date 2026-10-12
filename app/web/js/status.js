// StationPlay's status, and the picture and tuners.
// Status ---------------------------------------------------------------------
let status = null;
let pageVersion = null;  // (StationPlay's version when this page was loaded)
async function loadStatus() {
  try {
    status = await api('/api/status');
  } catch { return; }
  // After an update, StationPlay's page as it is now, as soon as nothing's
  // open (an app's window, from a home screen, has no reload button).
  pageVersion ??= status.version;
  if (status.version !== pageVersion && !document.querySelector('dialog[open]')) { location.reload(); return; }
  $('#appVersion').textContent = status.version ? `StationPlay ${status.version} · ` : '';
  const pill = $('#plexPill');
  pill.firstElementChild.className = 'dot ' + (status.plex.ok ? 'ok' : 'bad');
  const plexError = status.plex.error || 'not connected';
  pill.lastElementChild.textContent = status.plex.ok
    ? 'Plex connected'
    : /^Plex\b/.test(plexError) ? plexError : `Plex: ${plexError}`;
  // Stations someone is receiving right now (a station keeps running a few
  // seconds after its last viewer leaves, so flipping back is instant; those
  // don't count). Plex may carry several people on one connection.
  const watched = status.streams.filter(s => s.viewers > 0);
  const connections = watched.reduce((n, s) => n + s.viewers, 0);
  const full = watched.length >= status.tuners;
  $('#livePill').hidden = !watched.length;
  $('#livePill').title = `Stations being watched right now, and how many connections there are. Each station uses one tuner (StationPlay has ${plural(status.tuners, 'tuner')}), no matter how many people watch it in Plex or another app.${full ? ' Every tuner is in use, so anyone tuning in to another station sees a card saying so.' : ''}`;
  $('#livePill').firstElementChild.className = full ? 'dot warn' : 'dot live';
  $('#livePill').lastElementChild.textContent = `${watched.length} of ${plural(status.tuners, 'tuner')} in use · ${plural(connections, 'connection')}`;
  // (What's for Admins comes only to Admins: Away from home and alerts too.)
  setAway(status.away);
  setAlerts(status.alerts);
  if (status.tunerUrl) {
    $('#tunerUrl').textContent = status.tunerUrl;
    $('#xmltvUrl').textContent = status.xmltvUrl;
    $('#m3uUrl').textContent = status.m3uUrl;
    $('#guideUrl').textContent = status.guideUrl;
    renderMediaAccess(status.mediaAccess);
    renderEncoding(status.encoding);
    renderGuideState(status.guide);
    // (What needs an Admin on the Broken files tab: see reports.py.)
    const bc = $('#brokenCount');
    bc.hidden = !status.filesCount;
    bc.textContent = status.filesCount;
    if (!setupChecked) {
      setupChecked = true;
      maybeSetup();
    }
  }
  renderLive();
}

// Picture and tuners -------------------------------------------------------------
// How stations play (see playback.py): the picture size new stations start
// with, how many stations play at once, and what this server can manage. On
// the Add to Plex tab, and in the setup.
const SPEED_WAIT = 'Testing… (up to a minute)';
function playbackForm(pb, { saveLabel, onSaved, extraButtons = [], embedded = false }) {
  let picture = pb.picture, tuners = pb.tuners, tested = pb.speedTest;
  const hint = h('span', { class: 'hint' });
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Picture size for new stations' },
    ...pb.pictures.map(p => h('button', { type: 'button', 'aria-pressed': String(p === picture), onclick: () => { picture = p; paint(); } }, p)));
  const select = h('select', { 'aria-label': 'Number of tuners', onchange: () => { tuners = Number(select.value); paint(); } },
    ...Array.from({ length: pb.mostTuners }, (_, n) => h('option', { value: n + 1 }, String(n + 1))));
  const tunerHint = h('span', { class: 'hint' });
  const tunerWarn = h('span', { class: 'small', hidden: true });
  const result = h('span', { class: 'hint' });
  const testBtn = h('button', { type: 'button', class: 'btn', onclick: runTest }, 'Test this server');
  const useBtn = h('button', { type: 'button', class: 'btn', hidden: true, onclick: () => { tuners = recommended(); paint(); } });
  const save = h('button', { type: 'button', class: 'btn primary', onclick: doSave }, saveLabel);
  const recommended = () => tested ? Math.max(1, tested.pictures[picture]?.stations || 1) : null;
  function paint() {
    seg.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.textContent === picture)));
    hint.textContent = `${PICTURE_HINTS[picture]} You can give any station its own size under How it plays in its editor.`;
    select.value = String(tuners);
    tunerHint.textContent = `Up to ${plural(tuners, 'station')} can play at once, across Plex and all other apps. Everyone watching the same station shares one stream, so a station uses one tuner no matter how many people watch it. When every tuner is in use, anyone tuning in to another station sees a card saying so. (StationPlay tells Plex it has ${Math.max(tuners + 1, 2 * tuners)} tuners so that Plex lets it show that card. If you raise this number and Plex still won’t play more, restart Plex.)`;
    if (tested) {
      const p = tested.pictures;
      const when = new Date(tested.at).toLocaleDateString([], { month: 'short', day: 'numeric' });
      result.textContent = `This server can play about ${plural(p['480p'].stations, 'station')} at once at 480p, ${p['720p'].stations} at 720p, or ${p['1080p'].stations} at 1080p (on the ${tested.encoder}, tested ${when}${tested.playing ? ` with ${plural(tested.playing, 'station')} playing` : ''}). Programs in 4K or HDR take more work, so treat this as a rough guide.`;
      const r = recommended();
      useBtn.hidden = r === tuners;
      useBtn.textContent = `Use ${plural(r, 'tuner')} for ${picture}`;
      tunerWarn.hidden = tuners <= r;
      tunerWarn.replaceChildren(warnIcon(), ` ${plural(tuners, 'tuner')} is more than the test found this server can manage at ${picture} (about ${r}). Stations may stutter when more than ${r} play at once.`);
    } else {
      tunerWarn.hidden = true;
      result.textContent = 'Run a quick test to see roughly how many stations this server can play at once. It makes a few seconds of video at each size.';
      useBtn.hidden = true;
    }
  }
  async function runTest() {
    testBtn.disabled = true;
    testBtn.textContent = SPEED_WAIT;
    try {
      tested = (await api('/api/playback/speed-test', { method: 'POST' })).speedTest;
    } catch (e) {
      toast(e.message, true);
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = 'Test again';
      paint();
    }
  }
  async function doSave() {
    save.disabled = true;
    try {
      const saved = await api('/api/playback', { method: 'PUT', body: { picture, tuners } });
      // (The setup's question about this, answered.)
      api('/api/setup', { method: 'PUT', body: { answered: ['playback'] } }).catch(() => {});
      NEW_STATION.picture = saved.picture;
      Object.assign(NEW_STATION, saved.newStation);
      playbackSettings = saved;
      toast('Saved');
      onSaved?.(saved);
      loadStatus();
    } catch (e) {
      toast(e.message, true);
    } finally {
      save.disabled = false;
    }
  }
  if (tested) testBtn.textContent = 'Test again';
  paint();
  const form = h('div', { class: 'playback' },
    h('p', { class: 'hint', style: 'margin:0' }, 'As on broadcast TV, each station plays as one continuous stream in a single format. Every program, commercial, and card is converted to that format as it plays (H.264 at the station’s picture size), so one flows into the next without a glitch, in any app. Bigger pictures look sharper but take more work.'),
    h('p', { class: 'hint', style: 'margin:0' }, h('strong', {}, '4K and HDR programs are converted to fit. '), '4K plays at the station’s picture size (1080p at most), and HDR is converted to standard color so it doesn’t look washed out. A station must play everything in its one format to run without glitches. Streaming in 4K HDR would need a GPU fast enough to convert everything in real time and about 20 Mbps per viewer, and Plex Live TV isn’t known to pass HDR through to the TV. (Plex still struggles with ATSC 3.0, the broadcast standard that brings HEVC and HDR from real tuners.) So, for stability, stations play at up to 1080p in standard color. Dolby Vision profile 5 files can’t play correctly without a Dolby Vision player, so they’re left out and listed on the Broken files tab.'),
    h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Picture for new stations'), h('div', { class: 'opt-ctl' }, seg, hint)),
    h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'Tuners'), h('div', { class: 'opt-ctl' }, select, tunerWarn, tunerHint)),
    h('div', { class: 'opt' }, h('span', { class: 'opt-label' }, 'This server'), h('div', { class: 'opt-ctl' }, h('div', { class: 'row-btns' }, testBtn, useBtn), result)),
    embedded ? null : h('div', { class: 'row-btns' }, h('div', { class: 'spacer' }), ...extraButtons, save));
  // (In the setup, what's chosen is saved as the step is left.)
  form.values = () => ({ picture, tuners });
  return form;
}
let playbackSettings = null;
async function renderPlaybackPanel() {
  try { playbackSettings = await api('/api/playback'); } catch (e) { return; }
  $('#playbackPanel').replaceChildren(playbackForm(playbackSettings, { saveLabel: 'Save' }));
}
