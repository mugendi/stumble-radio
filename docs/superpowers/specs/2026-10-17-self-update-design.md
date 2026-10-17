# Stumble Radio self-update — design

Date: 2026-10-17
Status: approved for planning

## Goal

In-app update of the installed `stumble-radio` `uv` tool: a version check at
launch against GitHub tags, a `U` key that cleanly stops the app, upgrades via
`uv tool install --upgrade`, and relaunches the new version. No standalone
update script.

## Decisions made

- Publishing: GitHub tags on `mugendi/stumble-radio` (no PyPI release ritual).
  Tag format `vX.Y.Z`, tag version == `pyproject.toml` version.
- Check timing: once at launch, cached in local db metadata; GitHub is polled
  at most once per 24 h. Offline or failed fetch = silent skip, cache not
  refreshed.
- Upgrade degree: graceful exit → subprocess upgrade → process re-exec. No
  in-place environment swapping, no autopdate.
- Trigger: only the user, via capital `U` + confirmation. Lowercase `u` stays
  the Explore online-batch fetch. Launch check only informs.

## Components

### `src/stumble_radio/updates.py` (new, ~60 lines, no new deps)

- `installed_version() -> str` — `importlib.metadata.version("stumble-radio")`.
  Raises or returns `""` when the package metadata is unavailable (source
  checkout without install); callers treat that as "unknown".
- `latest_version(client) -> str | None` — GET
  `https://api.github.com/repos/mugendi/stumble-radio/tags` with a short
  timeout and `Accept: application/vnd.github+json`; parse `[0]["name"]`,
  strip `v` prefix. Any network/parse failure returns `None` (silent).
- `is_newer(latest, installed) -> bool` — numeric tuple compare; missing
  segments default to 0 so `0.2 > 0.1.9`.
- `uv_command(version_url) -> list[str] | None` — locate `uv` via
  `shutil.which("uv")` plus the `$HOME/.local/bin` and `$HOME/.cargo/bin`
  fallbacks used by `install.sh`; return
  `[uv, "tool", "install", "--upgrade", "--python", "3.11", version_url]`
  where `version_url` is the existing master-tarball URL from `install.sh`
  (`https://github.com/mugendi/stumble-radio/archive/refs/heads/master.tar.gz`).
  `None` when uv is missing.

### App integration (`app.py`)

- State: `self.update_available: str | None` = the newer version, else None.
- Startup worker (`group="updates"`): read cached `{last_check, latest}` from
  db metadata (`set_metadata` pattern); if `last_check` is fresh (< 24 h) and
  `latest` parses, use without fetching; otherwise fetch. If a fetch succeeded,
  write metadata `update_check` = JSON `{"last_check": <unix ts>,
  "latest": "<v>"}`. Persist even when no update (so the 24 h window holds),
  never persist on failure.
- On newer version: toast `A newer version is available: 0.1.4 — press U to
  update`; footer/help gains the `U Update` line.
- `action_update()` worker (`group="updates"`, exclusive): no-op with a brief
  hint unless `update_available` is set or a force-check finds one.
  1. ConfirmScreen: `Update Stumble Radio now? (0.1.3 → 0.1.4)`.
  2. Same teardown as quit: checkpoint listening, `stop_recording()`, stop
     playback, persist Podmoro, dismiss voice prompts.
  3. Footer line shows progress (`Updating · downloading…`, `Updating ·
     installing…`), stdout of the upgrade subprocess tail-captured.
  4. Success → toast `Updated 0.1.3 → 0.1.4 · relaunching`, then `os.execv`
     the original `sys.argv` so the new version boots cleanly.
  5. Failure (uv missing, non-zero exit, exec impossible) → notify the error,
     restart the TUI normally instead of killing the terminal.

### Installation-source guard

If the running copy is not a `uv` tool install (e.g. editable/source run),
the subprocess upgrade and relaunch are skipped: the launch check still
informs, and `U` reports `Update via your installation method` (detected by
requiring `importlib.metadata` metadata to exist and the uv tool binary dir
to contain the entry point; simplest robust pre-check: confirm the uv tool
bin path contains a `stumble-radio` executable owned by a uv tool venv).

## Error handling & constraints

- Never self-upgrades without user confirmation (ConfirmScreen each time).
- One GitHub request per launch max (24 h cache) — well inside the 60/h
  unauthenticated limit.
- No rollback guarantee: a re-exec that fails to boot ends the process; the
  user relaunches manually. Documented limitation.
- `privacy`: single GitHub metadata request; no tracking, no download auto-run.

## Tests

`tests/test_updates.py` (no network):

- `is_newer`: `0.2` vs `0.1.9`, equal, older, malformed segments,
  `v` prefixes.
- `latest_version`: fake client — newest tag picked, error/empty/malformed
  payload → None.
- Cache: fresh cache < 24 h skips fetch; stale triggers fetch + persists;
  failed fetch leaves cache untouched.

`tests/test_app.py` additions (fake subprocess runner + fake check):

- newer version → toast + `update_available` set; U without update = no-op.
- U flow: confirm → teardown calls seen → upgrade command received with the
  tarball URL and `--upgrade` → relaunch flag simulated.
- upgrade command fails → app restarts, error notified, no relaunch.

## Docs

- `docs/getting-started.md`: "Updating" section (launch check, U flow,
  24 h cache, install-method caveat).
- `docs/playback.md`: control table gains `| U | Update the app (when a newer
  version is available) |`.

Out of scope: standalone update script, releases with notes, auto-update
timers, rollback.
