# StationPlay: standing rules

StationPlay is a self-hosted TV and media server, free and open source under
the GPL (version 3). Its paid apps live in a private repo
(egadgetboy/stationplay-apps). These are the owner's standing decisions:
follow them in every change.

## The product
- **"Station," never "channel,"** in anything people read (Plex's own
  feature names excepted).
- **Clear American English.** Friendly, short and plain on the page;
  concise in the logs. Short sentences, one idea each, no jargon. Say
  **PIN**, not "passcode" (the owner's choice; the rename ships in 1.31.0).
- **No outside services** beyond those the plan names, and no AI features.
  Nothing outside the home is required.
- **A look unlike Plex or Emby.** Original work only.
- **Opt-in features, a lean server:** no new dependencies; what an app can
  do itself lives in the app.
- **No real file names or paths** in anything the apps receive.
- StationPlay stays labeled **alpha**. No web client for watching, no DVR.
- The free app plays only the server's first station.

## Tests
- **Every bug gets a failing test first,** then a root-cause fix. The test
  stays.
- **Never weaken a test:** don't loosen a tolerance, change an expected
  result to make it pass, skip it or delete it. If a test looks wrong, stop
  and explain why.
- While working, run only the tests for the area being changed. The full
  suite (35 to 45 minutes, `python -m pytest -q -p no:cacheprovider`) runs
  once per release, in the main session.
- Don't edit `tests/fakeplex.py`.

## Releases
- One release per feature, or per small bundle of fixes; tiny wording or
  style fixes wait for the next feature release. Minor version for
  features, patch for fixes. The version is in `app/__init__.py`,
  `pyproject.toml`, `stationplay.yaml` and `docker-compose.yml`.
- Each release: a hostile audit before building; build; tests (the area's,
  then the full suite once; real FFmpeg streaming for playback; Playwright
  at 390, 768 and 1440 wide, light and dark, for page changes;
  `python tools/upgrade_check.py --from <previous release's commit>`;
  `python -m tools.attack_check`); a `cold-auditor` audit; clean up; notes;
  a report.
- Any database change on upgrade is preceded by an automatic backup
  (`data/backups/before-<version>-<date>.db`), and the notes give tested
  rollback steps.
- **Notes** (`docs/releases/v<version>.md`, line 2 `commit: <full ID>` of
  the tested commit on `main`): one screen. A summary sentence, short New
  and Fixed bullets, Updating, Rolling back. Published by
  `.github/workflows/release.yml`.
- **Report** to the owner, 5 lines: version and summary; tests; choices;
  known limits; one suggested improvement to the development process, for
  the owner's approval. Then: which work went to `routine-builder`, and what
  `cold-auditor` found and what was done about each item.
- **Every 3 releases, stop** and tell the owner, who runs an independent
  audit before work continues.
- **Stop and ask** when a decision isn't covered by the plan or these
  rules, or two parts of the plan conflict; when an error can't be fixed at
  its root; when a step would touch anything outside the repos (the owner's
  TrueNAS server, router or Plex: the owner installs releases); or when a
  step can't be undone.

## High-risk areas
Always built by the main session, never handed to `routine-builder`: the
streaming engine, sign-in and security, user access and content limits,
database changes and upgrades, multi-server, Watch Group sync, audio
passthrough, and anything that could expose data or stop playback.

## Delegation
- Hand `routine-builder` whole tasks, such as a full screen or a set of
  wording changes, not one-line fixes. Each helper starts fresh and has to
  re-read files, so tiny handoffs cost more than they save.
- Every handoff is complete: the task, the files involved, the relevant
  decisions, and what "done" means. Helpers don't see the conversation.
- Review everything `routine-builder` returns before it goes into a
  release.
- Send every finished release to `cold-auditor` before its report. Fix
  everything it finds, or explain in the report why an item isn't a
  problem. Each fix gets a test that would have caught it.
- Never set the `CLAUDE_CODE_EFFORT_LEVEL` environment variable: it
  overrides the helpers' effort levels.

## Git and the machine
- Explicit paths, never `git add -A`; never `git reset --hard` with
  uncommitted work. Only the main session pushes.
- Stop processes by their PID only (never `pkill -f` or `pgrep -f`).
- GitHub Actions minutes count: run what a change needs, nothing more.
