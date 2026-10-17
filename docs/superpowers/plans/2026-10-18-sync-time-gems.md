# Sync Station Time + Hidden Gems — Implementation Plan

Spec: `docs/superpowers/specs/2026-10-18-sync-time-gems.md`

**Goal:** (1) sidebar "Sync Station Time" (My Time button + Sync By daypart dropdown) that biases stumbles to stations living in a chosen local time-of-day, with a station-clock on the destination line; (2) a "Hidden gems" shuffle pool for low-engagement stations.

**Tech stack:** stdlib only (`zoneinfo`, `tomllib`-style data tables), pytest, ruff (line 100).

## Task 1: `world_times.py` country clocks and daypart helpers

Files:
- Create `src/stumble_radio/world_times.py`
- Test: `tests/test_world_times.py` (new)

Interfaces:
- Produces: `CC_TZS: dict[str, str]` (countrycode → IANA zone); `DAYPARTS: dict[str, str]` labels for buckets ("Breakfast Shows", "Afternoon Shows", "Evening Shows", "Late Night Shows"); `DAYPART_WINDOWS: dict[str, set[int]]`; `local_hour(countrycode, when=None) -> int | None`; `daypart_for(hour) -> str`; `zone_for_daypart(daypart) -> str | None`.
- Bucket edges: Breakfast `6 ≤ h < 10`, Afternoon `10 ≤ h < 17`, Evening `17 ≤ h < 22`, Late Night `22 ≤ h < 24 or h < 6`.
- Data: generated from `/usr/share/zoneinfo/zone.tab` (public domain): centroid-of-country-zones heuristic, hand overrides for wide-spread countries.
- `local_hour` uses `zoneinfo.ZoneInfo` and returns None for unknown code/zone/bad data; goal is a plain hour int in station-local time.

Tests (TDD):
1. `test_daypart_edges_map_only_valid_hours` — daypart_for at boundary hours (6→Breakfast, 9→Breakfast, 10→Afternoon, 16→Afternoon, 17→Evening, 21→Evening, 22→Late, 2→Late) and rejects anything else.
2. `test_local_hour_resolves_zone_and_unknowns` — known code returns an int hour (use `when=` with a fixed datetime so value is deterministic, e.g. KE + time 09:41 UTC → 12:41); unknown code and unknown zone → None.
3. `test_every_country_zone_resolves` — for each value in CC_TZS, `ZoneInfo(zone)` succeeds (integrity of generated data).

## Task 2: `db.py` + `discovery.py` hidden gems pool

Files:
- Modify: `src/stumble_radio/discovery.py` (POOL_MODES; `GEM_VOTES = 10`, `GEM_CLICKS = 15`)
- Modify: `src/stumble_radio/db.py` `_discovery_where` (new pool branch)
- Test: `tests/test_db.py` (append)

Interfaces:
- `POOL_MODES` ends with `"Hidden gems"`; where clause `s.votes<=? AND s.clickcount<=?` bound with the constants.
- `m`-cycle picks it up automatically (app.py `action_pool`).

Tests (TDD):
1. `test_discover_hidden_gems_pool_filters_low_engagement` — insert one gem (votes 3, clickcount 5) and one popular (votes 500, clickcount 5000); `db.discover(search, "browse", "Hidden gems")` returns only the gem; `db.discover(search, "browse", "Anywhere")` may return both.
2. `test_pool_modes_summary` — discovery.POOL_MODES contains "Hidden gems" after "Nearby".

## Task 3: app.py sidebar section + persistence + destination clock

Files:
- Modify: `src/stumble_radio/app.py` (compose, handlers, CSS, `update_discovery_line`, destinations clock, restore on launch)
- Test: `tests/test_app.py` (append)

Interfaces:
- Compose (in `#sidebar`, after the `#library` Select, before `#detail`):
  `Static("SYNC STATION TIME", classes="sync-caption")` then `HorizontalGroup(id="sync-row")` with `Button("MY TIME", id="sync-my-time")` and `Select(id="sync-by")` options `("Off", "")`, `("Breakfast Shows", "breakfast")`, `("Afternoon Shows", "afternoon")`, `("Evening Shows", "evening")`, `("Late Night Shows", "late")`, `allow_blank=False`.
- State: `self.daypart = ""` in `__init__`.
- `on_select_changed`: `sync-by` sets `self.daypart`, persists db metadata key `sync_daypart` (json.dumps string), Off ("") clears. No auto-stumble.
- `on_button_pressed`: `sync-my-time` → `zone_for_daypart` resolution: compute `daypart_for(datetime.now().astimezone().hour)`, set the Select value (which sets self.daypart and persists), then call `self.action_stumble()`.
- Restore on launch (`on_mount`): read metadata `sync_daypart`; if a valid value, set Select value (handler re-arms + re-persists harmlessly).
- Discovery line: `Shuffle · {pool}` gains ` · <label> Shows` suffix when armed (tweak: active sync visible).
- Destination clock: when `self.current` and `local_hour(self.current.countrycode)` is not None, `update_destination_line` appends ` · HH:MM there` (station local now). A 60 s interval re-renders only if the minute changed.
- CSS: rules for `.sync-caption`, `#sync-row`, `#sync-by` in the existing stylesheet; compact on narrow widths (existing responsive pattern: `#sidebar {width: ...}` variants — follow).

Tests (TDD):
1. `test_sync_station_time_ui_arms_and_persists` — section renders below library select; selecting "Evening Shows" sets self.daypart and metadata; selecting Off clears both.
2. `test_my_time_stumbles_and_sets_dropdown` — monkeypatch stub so local hour lands in a bucket; button sets dropdown value and calls stumble (FakePlayer path; verify a tune happened or stumble worker ran offline-safe).
3. `test_sync_daypart_restored_on_launch` — pre-set metadata; new app run_test shows Select value + daypart armed.
4. `test_destination_line_shows_station_local_time` — monkeypatch `world_times.local_hour`; destination line contains "· 09:41 there".

## Task 4: daypart-weighted stumbles

Files:
- Modify: `src/stumble_radio/app.py` `action_stumble` (+ help of `world_times`)
- Test: `tests/test_app.py` (append)

Interfaces:
- When `self.daypart`: call `db.discover(search, mode, pool, exclude, limit=64)`; filter rows by `local_hour(row.countrycode)` in `zone_for_daypart(self.daypart)` window; keep weighting order.
- Fallback: empty → toast `No <label> broadcasts found · landing anywhere` and use the unfiltered (limit=8 normal call) results.

Tests (TDD):
1. `test_stumble_filters_candidates_to_daypart` — FakeDB-like monkeypatch of `db.discover` returning known stations across countries with a frozen `local_hour`; with daypart armed asserts the picked station is the in-bucket one and limit=64 was requested.
2. `test_stumble_falls_back_when_bucket_empty` — monkeypatched discover rows all out-of-bucket; asserts fallback toast text and station still tuned.

## Task 5: docs, help, full gate

Files:
- Modify: `docs/discovery.md` (Sync Station Time section + approximation note; Hidden gems in modes list)
- Modify: `README.md` (bullets in Discover section)
- Modify: `src/stumble_radio/screens.py` HelpScreen (`m` line + one line for My Time)
- Gate: `.venv/bin/python -m pytest -q` (~283) + `.venv/bin/ruff check src tests scripts`

Dependencies: strictly 1 → 2 → 3 → 4 → 5.
