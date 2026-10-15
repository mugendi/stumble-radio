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
  network.py   Recovery reachability checks and capped reconnect delays
  pomodoro.py  Focus/break clocks, reminders, weekly rules and checkpoints
  pomodoro_screen.py  Session, profile, schedule and voice-library editors
  announcements.py   Local MP3 discovery and independent bounded voice playback
  tracks.py    Broadcaster artist/title and ICY track metadata parsing
tests/         Database, API, player, and headless TUI checks
```

## API and implementation references

The project follows the supplied [API query reference](radio-browser-api-queries.md).
The directory is provided by the [Radio Browser community](https://www.radio-browser.info/).
Technical references: [Radio Browser API](https://api.radio-browser.info/),
[Textual workers](https://textual.textualize.io/guide/workers/),
[mpv JSON IPC](https://mpv.io/manual/stable/#json-ipc), and
[FFplay controls](https://ffmpeg.org/ffplay.html#While-playing).
