# Development and references

[← Stumble Radio](../README.md)

Run these commands from the project root.

## Development

```bash
uv venv
uv pip install -e '.[dev]'
.venv/bin/stumble-radio --data-dir /tmp/stumble-radio-dev
.venv/bin/pytest
.venv/bin/ruff check src tests
```

Tests use temporary SQLite databases, mocked HTTP responses, and Textual's
headless pilot. They do not play remote radio or alter your normal library.
When mpv is installed, a local integration test serves a generated silence/tone
sample over localhost and validates decoded metering using a null audio output.
That test needs local socket access and skips when mpv is missing. Real speaker
output and broadcaster-specific recording still require manual verification.

## Releases

The release script prepares an editable changelog first. Publishing is a separate,
explicit step. Git must have access to `origin`; publishing also needs the GitHub
CLI (`gh`) authenticated with permission to create releases.

1. Update the version in `pyproject.toml` and the fallback in
   `src/stumble_radio/__init__.py`, then commit the changes to release.
2. Generate and preview the notes:

   ```bash
   .venv/bin/python scripts/release.py
   ```

   The script adds a dated version entry to `CHANGELOG.md` using commits since
   the previous numeric remote version tag. It includes commit descriptions,
   commit links, and a full comparison link. The first release uses the complete
   history. Merge commit messages are omitted; their individual commits remain.

   `feat:` becomes **New features**, `fix:` becomes **Bug fixes**, and `docs:`
   becomes **Documentation**. Build, dependency, test, and other maintenance
   prefixes share **Dependencies and maintenance**. Unclassified messages appear
   under **Other changes**. A `!` after the type/scope or a `BREAKING CHANGE:`
   footer puts the commit under **Breaking changes**.
3. Edit `CHANGELOG.md` to explain user impact, add upgrade instructions, and
   remove details that do not help readers. Existing entries are preserved on
   reruns. To regenerate a draft, remove only that version's entry and rerun.
   Commit and push the reviewed notes and release changes.
4. Publish the tag and GitHub release:

   ```bash
   .venv/bin/python scripts/release.py --publish
   ```

   Optionally add `--title "Stumble Radio v0.2.0 — Voice announcements"`.
   Publishing requires a clean working tree and a nonempty changelog entry.
   The release body is the reviewed entry, excluding its version heading.

If a remote tag already exists, preparation uses that tag's commit, excluding
later work. Publishing can attach notes to that existing tag without moving it.
If the tag push succeeds but GitHub release creation fails, fix the reported
problem and rerun `--publish`. An already published release is left alone.
Existing GitHub drafts require review and publication on GitHub.

Preparation fetches remote tag objects but does not commit, tag, push, or create
a GitHub release. Run the release script's offline tests with
`.venv/bin/python -m pytest -q tests/test_release.py`.

```text
src/stumble_radio/
  cli.py       Entry point, storage paths, dependency diagnostics
  app.py       Main TUI, library navigation, background workers
  screens.py   Search, Last Play, quick tune, journal and settings dialogs
  app.tcss     Terminal styles and narrow-screen layout
  api.py       Mirror discovery, bounded queries, catalogue sync
  db.py        SQLite catalogue, URL grouping, favourites, history and song FTS
  discovery.py Learning thresholds, weighted shuffle, diversity and preferences
  models.py    Station parsing, search validation, geographic distance
  query.py     Field operators, boolean query parsing and query formatting
  player.py    mpv IPC, playback events, FFmpeg recording lifecycle
  equalizer.py  Validated five-band EQ, gain, presets and filter graph
  equalizer_screen.py  Live sound preview, save and cancellation
  network.py   Recovery reachability checks and capped reconnect delays
  pomodoro.py  Focus/break clocks, reminders, weekly rules and checkpoints
  pomodoro_screen.py  Session, profile, schedule and voice-library editors
  announcements.py   Local MP3 discovery and independent bounded voice playback
  voice.py   Piper TTS: voice download, cached engine, WAV phrase rendering
  tracks.py    Broadcaster artist/title and ICY track metadata parsing
  world_times.py   Representative country timezones, radio-daypart windows
  updates.py   Release check, version comparison and upgrade hand-off
tests/         Database, API, player, and headless TUI checks
```

## API and implementation references

The project follows the supplied [API query reference](radio-browser-api-queries.md).
The directory is provided by the [Radio Browser community](https://www.radio-browser.info/).
Technical references: [Radio Browser API](https://api.radio-browser.info/),
[Textual workers](https://textual.textualize.io/guide/workers/),
[mpv JSON IPC](https://mpv.io/manual/stable/#json-ipc), and
[FFplay controls](https://ffmpeg.org/ffplay.html#While-playing).
