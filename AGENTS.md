# Announcements pipeline (agent-facing notes)

How interruption sound works end to end, what contracts hold, and how to extend
or test it. User-facing docs live in `docs/podmoro.md` and `docs/voice.md`.

## 1. Pipeline

1. `Pomodoro` (src/stumble_radio/pomodoro.py) decides *that* an announcement
   should fire (phase change, focus-ending warning, recurring reminder,
   schedule rule, snooze, preview request) and returns an
   `Announcement(category, text, weight, generation)` on its clock thread.
2. The app drains announcements from the timer on a heartbeat and calls
   `app.announce(...)` in the Textual worker group `"announcements"`
   (`exclusive=True`, so one announcement runs at a time).
3. `announce` (src/stumble_radio/app.py) holds `self.announcement_lock` while:
   - picking a clip: `AsyncioLibrary.choose(category)` — random, avoids an
     immediate repeat; caps duration at `MAX_ANNOUNCEMENT_SECONDS` (120 s).
   - fallback: if the folder is empty, `generate_on_demand` asks
     `voice.py` for a synthesized WAV (only when the engine is warm; never
     downloads mid-announcement).
   - showing the caption: `caption(clip, fallback_text)` reads the sibling
     `.txt`; `last_announcement` is replaced and `update_pomodoro_line()`
     repaints the header.
   - gating: Quiet, radio pause, scheduler suspension or a paused session
     return early *after* setting `last_announcement` (visual reminder only).
   - ducking: `fade_announcement(down=True)` ramps `announcement_gain`
     1.0 → 0.66 → 0.33 → 0.0 (`apply_volume()` after each step), then sets
     `announcement_muted`; the stream keeps playing, zeroed.
   - playback: `await self.announcer.play(clip, self.pomodoro.voice_volume)`
     — an `AnnouncementPlayer` (see §3) in worker group `"announcements"`,
     with `started`/`finished` events consumed by the timer heartbeat.
4. `finally` (also on OSError/ValueError/PlayerError notification paths):
   unmute, `fade_announcement(down=False)` back to gain 1.0, `apply_volume()`,
   and `save_current_track()` so a song announced by the broadcaster during
   speech is kept only if still current when the radio becomes audible again.

Volume composition lives in `apply_volume()`:
`effective = volume_value * sleep_gain * announcement_gain`, zeroed when
`announcement_muted or user_paused`. Recording and listening-accounting
(`account_listening`) are untouched by dips: voice-muted time is excluded from
listening totals, recording continues, and voice audio never enters
recordings or Last Play Search.

Previews (`preview_voice(command)`) run through the same `announce` worker with
`preview=True`: no gating, no `last_announcement` update, notification when the
folder is empty. `dismiss_voice()` stops the player, resets preview flags and
gain. Listeners: `pomodoro_screen.py` preview buttons, `Beacon` and
`AnnouncementStub` in tests.

## 2. Clip library contract (announcements.py)

`AudioLibrary` owns the command tree under `<radio dir>/pomodoro/audio/commands/`:

- `categories()` → sorted relative folders (nested with `/`), symlinks must
  resolve inside the root.
- `clips(category)` → `.mp3` / `.MP3` / `.wav` files in that folder.
- `choose(category)` → `(clip, identifier)` after `random.seed`-free choice
  that avoids repeating `previously`; raises `ValueError` when empty.
- `caption(clip, fallback)` → sibling `.txt` text or the fallback label.
- `folder(category)` → created on demand; custom folder names accept letters,
  digits, hyphens, underscores and `/`.
- Changing the destination folder through the Voice clips tab rebuilds the
  library; `Library` envelope in `announcements.py` contains `root`.
- Files are discovered at each announcement; no rescan step is needed in the
  worker, the Voice clips Rescan button only refreshes the table counts.

## 3. AnnouncementPlayer contract (announcements.py)

`AnnouncementsPlayer` keeps voice audio fully independent of the mpv radio
stream:

- `play(uri, volume)` → event to that for recording; caps the duration at
  `MAX_ANNOUNCEMENT_SECONDS` (120 s) so no clip can hang the pipeline.
- `announcer.started.wait()` in tests after `dispatch_announcement` and to wait
  out race with the duck fade before asserting on `FakePlayer.volumes`;
- `announcer.finished` consumed after `release.set()` to assert the unmute
  volume restored and `announcement_gain` back to 1.0.
- Process exit kills the voice process; sleep expiry stops speech; no replay
  of missed announcements after pause (checkpoints in `pomodoro_v1`).

## 4. TTS API (voice.py)

`voice.py` is the reusable announcements API; it renders text to WAV and
persists the user's voice choice. It never touches playback.

- `VOICES` — `{"alan": VoiceSpec("alan", "en_GB-alan-medium", "en/en_GB/alan/
  medium/"), "jenny": VoiceSpec("jenny", "en_GB-jenny_dioco-medium", ...)}`;
  downloads come from `VOICE_HOST` (rhasspy/piper-voices on Hugging Face) with
  `DOWNLOAD_TIMEOUT = 120`, models land in `<radio data dir>/piper`
  (`app.tts = Announcer(db.path.parent / "piper")`).
- `MAX_TTS_CHARS = 600`; `speak(text, person, dest_dir) -> Path` sanitises via
  `models.clean`, refuses oversized/unknown text or voice with `VoiceError`,
  writes `tts-<sha1(voice_id + \\0 + text)[:8]>.wav` (deterministic, so
  repeated phrasings reuse the file) plus a sibling `.txt` caption.
- `ensure_voice(person)` — idempotent download of `.onnx` + `.onnx.json`, then
  `engine().load(model)` cached in the module-level `_loaded` dict;
  `ready(person)` reports a warm cache without touching the network;
  `has_engine()` reports `piper` importability (it ships as a dependency of
  this app — `piper-tts>=1.3,<2` in `pyproject.toml`).
- `phrase_variants(command)` — catalogued `PHRASES[command]` (two phrasings per
  default folder), custom folders fall back to
  `pomodoro.Pomodoro.command_label(command)`.
- `VoiceSettings(person="alan")` — listener preferences persisted as metadata
  key `announcer_v1`: `{"version": 1, "person": "alan"}`
  (`snapshot()` / `VoiceSettings.restore(raw)`; restores validate and throw
  `TypeError`/`ValueError` for malformed payloads, so the app falls back to
  Alan with a warning).
- The engine seam is the module-level `engine()` function (lazy
  `from piper import PiperVoice`, cached after the first call). Tests and
  offline runs patch it instead of installing models; `_loaded` is patched or
  cleared per test.

## 5. Recipes

- **New default phrase for an existing folder**: extend the tuple in `PHRASES`
  (voice.py). On the next app start, empty folders get both variants; folders
  that already hold clips are untouched. If users need the new phrasing in
  existing libraries, they delete the generated `tts-*.wav` files and restart.
- **New announcer voice**: add a `VoiceSpec` to `VOICES`, drop the matching
  files under `piper/piper-voices` remote directory (see `spec.repo_dir`),
  extend the `VoicesCommand` provider test, and update docs/voice.md + the
  table in AGENTS voice section. `VoiceSettings.__post_init__` keeps
  `person` validated against `VOICES`, so nothing else changes.
- **One-off announcement from any feature**: build an
  `Announcement(category, text, generation=self.pomodoro.generation)` and
  `dispatch_announcement(...)`; the caption comes from the clip's `.txt` or
  from `text` when the folder is empty and generation continues.
- **New announcement-consuming feature** (e.g., hourly station ID in your own
  voice): reuse `announce` with a folder seeded from `speak`; do not call
  `AnnouncementPlayer` directly — ducking, gating and accounting live in
  `announce`/`apply_volume`.
- **A folder users should never auto-generate**: keep it out of `COMMANDS`
  and ship no `PHRASES` entry; the startup filler only walks
  `set(voice_library.categories()) | set(COMMANDS)`.

## 6. Testing

- Engine seam: monkeypatch `voice_module.engine` (lambda returning a stub with
  `load(...)` classmethod and `synthesize_wav(text, wav_handle)`), clear
  `voice_module._loaded = {}`, and stub downloads with
  `monkeypatch.setattr(voice_module.Announcer._download, staticmethod(...)`
  — see `patch_tts` in tests/test_pomodoro_app.py and the toolbox in
  tests/test_voice.py.
- Timers: `player.announcer.started.wait(timeout=2)` (timeout loop already
  covered by `dispatch_announcement` tests) and `player.volumes[-3:]`
  approximations (`65 * 0.66`, `65 * 0.33`, `0`) — the fade writes four
  effective volumes per duck and the muted write lands exactly at volume 0.
- Offline by default: `app_with_voices` builds the app with `offline=True`,
  so warmup never runs in background unless a test calls `app.work_voice()`.
  Do not set `app.offline` in pomodoro tests: `catalogue_loop` would hit the
  OfflineAPI and panic the run.
- Accepting generated files: `voice_library.clips(...) == 2` per folder (the
  two `PHRASES` variants) with `all(c.suffix == ".wav")`; captions are written
  alongside as `.txt` but are excluded from `clips`; models asserted by
  `(tmp_path / "piper").glob("en_GB*")`.
- Full suite gating: `tests/test_voice.py` (no Textual), then
  `tests/test_pomodoro_app.py` (17 tests incl. ducking, palette switching,
  generation, fallback), then the rest. Keep `ruff check src tests` clean.
