// Media folders, on the Setup tab (1.36.4, the owner: "Server just needs to
// know what folders it can see, and the option to toggle them on and off"):
// every Media folder tapiOca has (/api/app-libraries), each with its switch
// for tapiOca's apps, saved at once. Those tapiOca reads itself (folder
// libraries, see folders.py on the server: shows or movies from folders in
// the media folder, with or without Plex) also show their folders, how
// they're read, Read again, Edit and Remove.
let foldersShown = null;
let mediaShown = null;
let foldersTimer = null;
// (Each load's number: an answer to an older one, or one asked before a switch
// was saved, is dropped, so a slow answer never brings back what was switched.
// 1.36.4's third audit.)
let foldersAsked = 0;
// `again`: /api/app-libraries asked again too (not while one's being read:
// it can wait a few seconds for Plex).
async function loadFolderLibraries(again = true) {
  const asked = ++foldersAsked;
  let got, media;
  try {
    [got, media] = await Promise.all([
      api('/api/folder-libraries'),
      again || !mediaShown ? api('/api/app-libraries').catch(e => ({ failed: e.message })) : mediaShown,
    ]);
  } catch (e) {
    if (asked === foldersAsked) $('#foldersPanel').replaceChildren(h('p', { class: 'muted empty' }, e.message));
    return;
  }
  if (asked !== foldersAsked) return;
  mediaShown = media;
  foldersShown = got;
  renderFolderLibraries(got, mediaShown);
  // (While one's being read, it says how far it's got.)
  clearTimeout(foldersTimer);
  if (got.libraries.some(l => l.scanning || (!l.scannedMs && !l.problem)) && !$('#tab-setup').hidden) foldersTimer = setTimeout(() => loadFolderLibraries(false), 2000);
}
// A folder as the page shows it: from the media folder ("TV/Kids"), if it's in it.
const inMedia = f => {
  const root = foldersShown?.mediaReal;
  return root && f.startsWith(root + '/') ? f.slice(root.length + 1) : f;
};
function folderLibraryState(lib) {
  const bits = [];
  if (lib.scanning) {
    const s = lib.scanning;
    bits.push(h('span', { class: 'chip accent' }, s.toRead ? `Reading ${s.read} of ${plural(s.toRead, 'file')}` : 'Looking through its folders'));
  } else bits.push(h('span', { class: 'small muted' }, lib.scannedMs ? `Read ${ago(lib.scannedMs)}` : 'Not read yet'));
  if (lib.problem && !lib.scanning) bits.push(h('span', { class: 'chip bad note' }, lib.problem));
  if (lib.missingFolders.length) {
    const kept = lib.missing ? ` What was read from ${lib.missingFolders.length === 1 ? 'it' : 'them'} (${plural(lib.missing, 'program')}) is kept, missing, until ${lib.missingFolders.length === 1 ? 'it’s' : 'they’re'} back.` : '';
    bits.push(h('span', { class: 'chip bad note' }, `Can’t be read now: ${lib.missingFolders.map(inMedia).join(', ')}.${kept}`));
  }
  if (lib.alsoInPlex?.length) bits.push(h('span', { class: 'chip note' }, `Also in Plex’s ${lib.alsoInPlex.join(', ')}: its titles appear twice, once from each.`));
  return h('div', { class: 'state' }, ...bits);
}
function renderFolderLibraries(got, media) {
  const panel = $('#foldersPanel');
  const own = new Map(got.libraries.map(l => [l.key, l]));
  const listed = media.failed ? [] : media.libraries;
  // (Every Media folder, as the apps' list has them; one of tapiOca's own it
  // doesn't, after them.)
  const all = [
    ...listed.map(l => ({ key: l.key, title: l.title, kind: l.kind, own: own.get(l.key) })),
    ...got.libraries.filter(l => !listed.some(m => m.key === l.key)).map(l => ({ key: l.key, title: l.name, kind: l.kind, own: l })),
  ];
  const said = media.failed || media.problem;
  if (!all.length) {
    // (Nothing to list: none yet, or Plex isn't answering and there's nothing else.)
    panel.replaceChildren(said && (media.failed || got.plexProblem)
      ? h('p', { class: 'small empty', style: 'margin:0' }, warnIcon(), ' ', said)
      : h('p', { class: 'muted empty' }, 'No Media folders yet. Add one, or connect Plex in setup.'));
    return;
  }
  // A switch saves at once: the Media folders now on, and only them. (Nothing
  // asked before it is shown after it.)
  const boxes = new Map();
  const save = async () => {
    clearTimeout(foldersTimer);
    foldersAsked++;
    const on = [...boxes].filter(([, b]) => b.checked).map(([key]) => key);
    boxes.forEach(b => { b.disabled = true; });
    try { await api('/api/app-libraries', { method: 'PUT', body: { libraries: on } }); toast('Saved'); }
    catch (e) { toast(e.message, true); }
    await loadFolderLibraries();
  };
  const what = l => l.kind === 'show' ? `${plural(l.shows, 'show')}, ${plural(l.episodes, 'episode')}` : plural(l.movies, 'movie');
  const kind = l => l.kind === 'movie' ? 'Movies' : 'Shows';
  const switchFor = l => {
    if (media.failed || !listed.some(m => m.key === l.key)) return null;
    // (On only when it's shared: none are while sharing is still to be chosen, from before 1.34.1.)
    const box = mediaFolderBox({ ...media, waiting: false }, l.key, save, { 'aria-label': `${l.title} in tapiOca’s apps` });
    boxes.set(l.key, box);
    return h('label', { class: 'small in-apps' }, box, ' In tapiOca’s apps');
  };
  const acts = l => h('div', { class: 'acts' },
    h('button', { type: 'button', class: 'btn', title: 'Look for what’s new or changed in its folders now', onclick: async () => {
      try { await api(`/api/folder-libraries/${l.key}/scan`, { method: 'POST' }); toast(`Reading “${l.name}” again`); }
      catch (e) { toast(e.message, true); }
      setTimeout(() => loadFolderLibraries(false), 500);
    } }, 'Read again'),
    h('button', { type: 'button', class: 'btn', onclick: () => folderLibraryDialog(l) }, 'Edit'),
    h('button', { type: 'button', class: 'btn danger', onclick: async () => {
      if (!confirm(`Remove the Media folder “${l.name}”? Its files stay where they are. Stations lose its programs, and tapiOca’s apps no longer show it.`)) return;
      try { await api(`/api/folder-libraries/${l.key}`, { method: 'DELETE' }); toast(`“${l.name}” is removed`); }
      catch (e) { toast(e.message, true); }
      loadFolderLibraries();
    } }, 'Remove'));
  // What a switch does to Media folders added later (1.36.4's third audit): said before it's used.
  const later = media.failed || said ? null
    : media.everything ? 'Every Media folder is in tapiOca’s apps now, and new ones join by themselves. Once you switch one off, only those switched on are, and new ones start switched off.'
    : media.waiting ? 'None are in tapiOca’s apps yet. Switch on the ones to share, or choose them in setup’s Media step.'
    : null;
  panel.replaceChildren(
    ...(said ? [h('p', { class: 'small', style: 'margin:0 0 10px' }, warnIcon(), ' ', said)] : []),
    ...(later ? [h('p', { class: 'hint', style: 'margin:0 0 10px' }, later)] : []),
    h('table', { class: 'users folder-libs' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Media folder'), h('th', {}, 'Its folders'), h('th', {}, 'State'), h('th', {}, ''))),
      h('tbody', {}, ...all.map(m => {
        const l = m.own;
        return h('tr', { 'data-key': m.key },
          h('td', {}, h('strong', {}, l ? l.name : m.title),
            h('div', { class: 'small muted' }, l ? `${kind(l)} · ${what(l)}` : kind(m)),
            switchFor(m)),
          l ? h('td', { 'data-label': 'Its folders' }, ...l.folders.map(f => h('div', { class: 'where', title: f }, inMedia(f)))) : h('td', {}),
          l ? h('td', { 'data-label': 'State' }, folderLibraryState(l)) : h('td', {}),
          h('td', {}, l ? acts(l) : null));
      }))));
}
// Adding or changing one: its name, what it holds (for good), its folders.
let flKind = 'show';
let flFolders = [];
let flEditing = null;
async function folderLibraryDialog(lib = null) {
  flEditing = lib;
  flKind = lib?.kind || 'show';
  flFolders = lib ? [...lib.folders] : [];
  $('#folderLibTitle').textContent = lib ? `Change “${lib.name}”` : 'Add a Media folder';
  $('#flName').value = lib?.name || '';
  $('#flSave').textContent = lib ? 'Save' : 'Add';
  $('#flResult').textContent = '';
  $('#flKindField').hidden = !!lib;
  pressOne('flkind', flKind);
  renderChosenFolders();
  $('#folderLib').showModal();
  await browseFolders('');
}
function renderChosenFolders() {
  $('#flChosen').replaceChildren(...(flFolders.length ? flFolders.map(f => h('span', { class: 'sel', title: f }, inMedia(f),
    h('button', { type: 'button', 'aria-label': `Take away ${inMedia(f)}`, onclick: () => { flFolders = flFolders.filter(x => x !== f); renderChosenFolders(); } }, '×')))
    : [h('span', { class: 'hint' }, 'None yet. Open a folder below, then choose Add this folder.')]));
}
async function browseFolders(path) {
  let got;
  try { got = await api(`/api/folder-libraries/browse?path=${encodeURIComponent(path)}`); }
  catch (e) { $('#flFolders').replaceChildren(h('p', { class: 'hint', style: 'padding:10px;margin:0' }, e.message)); return; }
  const parts = got.path ? got.path.split('/') : [];
  // (The top: the media folder itself, by its path, so it's never taken for a Media folder.)
  const crumbs = [h('button', { type: 'button', class: 'crumb', onclick: () => browseFolders('') }, foldersShown?.mediaDir || '/media')];
  parts.forEach((p, i) => {
    crumbs.push(h('span', { class: 'muted' }, '/'));
    crumbs.push(i === parts.length - 1 ? h('span', { class: 'here' }, p)
      : h('button', { type: 'button', class: 'crumb', onclick: () => browseFolders(parts.slice(0, i + 1).join('/')) }, p));
  });
  const taken = flFolders.includes(got.full);
  $('#flPath').replaceChildren(...crumbs, h('span', { class: 'spacer' }),
    h('button', { type: 'button', class: 'btn', disabled: taken || !got.path, onclick: () => {
      flFolders.push(got.full);
      renderChosenFolders();
      browseFolders(got.path);
    } }, taken ? 'Added' : 'Add this folder'));
  const open = name => browseFolders(got.path ? `${got.path}/${name}` : name);
  $('#flFolders').replaceChildren(...(got.folders.length ? got.folders.map(name => h('div', { class: 'pick', role: 'button', tabindex: '0',
    onclick: () => open(name), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(name); } } },
    h('span', {}, name), h('span', { class: 'muted', 'aria-hidden': 'true' }, '›')))
    : [h('p', { class: 'hint', style: 'padding:10px;margin:0' }, 'No folders in here.')]));
  const note = $('#flNote');
  note.hidden = !got.inPlex?.length;
  note.textContent = got.inPlex?.length ? `This folder is in Plex’s ${got.inPlex.join(', ')} too. That’s fine, but its titles then appear twice: once from Plex, once from this Media folder.` : '';
}
document.querySelectorAll('[data-flkind]').forEach(b => b.addEventListener('click', () => { flKind = b.dataset.flkind; pressOne('flkind', flKind); }));
$('#addFolderLibrary').addEventListener('click', () => folderLibraryDialog());
$('#closeFolderLib').addEventListener('click', () => $('#folderLib').close());
$('#flCancel').addEventListener('click', () => $('#folderLib').close());
$('#flSave').addEventListener('click', async () => {
  const name = $('#flName').value.trim();
  const body = flEditing ? { name, folders: flFolders } : { name, kind: flKind, folders: flFolders };
  let lib;
  try { lib = await api(flEditing ? `/api/folder-libraries/${flEditing.key}` : '/api/folder-libraries', { method: flEditing ? 'PUT' : 'POST', body }); }
  catch (e) { $('#flResult').textContent = e.message; return; }
  $('#folderLib').close();
  toast(flEditing ? `“${lib.name}” is saved` : `“${lib.name}” is added. tapiOca is reading its folders now.`);
  loadFolderLibraries();
});
