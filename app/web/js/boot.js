// Starting the page: loaded last, once everything else is defined.
// Boot ---------------------------------------------------------------------------
// Who's signed in: someone may have changed your role, or signed you out.
const checkMe = () => {
  if (signedOut()) return;
  loadMe().then(() => { if (me.required && !me.user) showSignIn(me.idle); }).catch(() => {});
};
// Refreshed every 10 seconds while the page is showing (not in a hidden tab).
const refresh = () => {
  if (signedOut()) return;
  checkMe();
  loadStatus();
  if (!$('#editor').open) loadChannels();
  if (currentTab === 'stats') loadStats();
};
(async () => {
  if (!await firstMe()) return;
  if (me.required && !me.user) { showSignIn(me.idle); return; }
  const initial = location.hash.slice(1);
  if (TABS.includes(initial) && initial !== 'stations') showTab(initial);
  // The setup, for an Admin, at once: never waiting on tapiOca's status,
  // which asks Plex (1.34.1, the owner: it took 20 seconds with Plex down).
  if (isAdmin()) { setupChecked = true; maybeSetup(); }
  loadStatus();
  loadChannels();
  linkWanted();
  loadUpdates();
})();
// (A new version: looked for again every hour while the page is open.)
setInterval(() => { if (!document.hidden) loadUpdates(); }, 3600000);
setInterval(() => { if (!document.hidden) refresh(); }, 10000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(() => { if (currentTab === 'logs' && !document.hidden && !signedOut()) loadLogs(); }, 5000);
setInterval(() => { if (currentTab === 'stats' && !document.hidden && !signedOut()) loadNow(); }, 5000);
setInterval(() => { if (currentTab === 'broken' && !document.hidden && !signedOut()) loadScan(); }, 10000);
