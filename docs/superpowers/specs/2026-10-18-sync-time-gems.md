# Sync Station Time + Hidden Gems — Design

Date: 2026-10-18
Status: approved (brainstorm 2026-10-18)

## Goal

Two discovery upgrades that deepen the "roam the world by ear" core:

1. **Sync Station Time** — a sidebar section between the Explore dropdown and the
   station-info panel that biases stumbles toward stations where it is a chosen
   time of day, so you hear, say, Nairobi breakfast radio while Kenyans also
   hear it.
2. **Hidden gems** — a new shuffle-pool mode for low-engagement stations
   (votes ≤ 10, directory clickcount ≤ 15), making rarity a first-class pool
   axis alongside Music-only or Nearby.

## Non-goals

- No per-station timezone precision: country codes map to **one representative
  IANA zone** per country (documented approximation; per-station geo coords
  would need a new dependency). `geo_lat`/`geo_long` are too sparse to trust.
- Teleporting is untouched: it lands a country; stumbles pick the
  time-appropriate station inside whatever pool/library is active.
- No new Python dependencies (stdlib `zoneinfo`, generated country table).

## Sync Station Time

Sidebar layout (inside `#sidebar`, directly under the `#library` Select):

```
SYNC STATION TIME
[ MY TIME ] [ Sync By ▾ ]
```

- **My Time** button: resolves the user's local clock into a daypart bucket,
  selects it in the dropdown, persists it, and stumbles immediately (real
  stumble — toasts for offline or no result come from the normal path).
- **Sync By** dropdown: Off / Breakfast Shows / Afternoon Shows / Evening
  Shows / Late Night Shows. Selecting a bucket arms future stumbles (no
  auto-stumble); "Off" clears it. Choices persist in db metadata
  (`sync_daypart`) and are restored on launch without stumbling.
- Daypart windows (station local hour):
  Breakfast 06–10 · Afternoon 10–17 · Evening 17–22 · Late Night 22–24 ∪ 00–06.
- Armed stumbling: `db.discover` gets a larger candidate batch (limit 64
  instead of 8); candidates whose `local_hour(countrycode)` falls in the
  window stay, preserving the linger-weighted race order; stations with
  unknown country or unmapped zone are dropped in the filtered pass.
- Fallback: if the window yields nothing, toast
  `No <bucket> broadcasts found · landing anywhere` and land from the
  unfiltered candidates.
- State visibility: the discovery line shows the active sync
  (`Shuffle · Anywhere · Evening Shows`).
- Station local clock (kept from brainstorm): the destination line appends
  ` · 09:41 there` while a station with a known countrycode plays, refreshed
  once a minute.

## Hidden gems

- `POOL_MODES` gains `"Hidden gems"` (cycles with `m`).
- SQL: `s.votes <= GEM_VOTES AND s.clickcount <= GEM_CLICKS` with
  `GEM_VOTES = 10`, `GEM_CLICKS = 15` constants in `discovery.py`.
- Picking stays the linger-weighted shuffle race within the filtered set, so
  repeated stumbles do not repeat gems just because the pool is small.

## Country clocks

- `world_times.CC_TZS: dict[str, str]` — country-code → representative IANA
  zone, generated from public-domain `zone.tab`: centroid-of-country-zones
  heuristic with hand overrides for wide-spread countries (US, RU, CA, BR, AU,
  CN, MX, ID, KZ, …).
- `local_hour(countrycode, when=None) -> int | None` via `zoneinfo`
  (unknown code/zone → None); `daypart_for(hour)`,
  `zone_for_daypart` helpers; a data-integrity test asserts every zone name
  resolves through `ZoneInfo`.

## Affected surfaces

- New: `src/stumble_radio/world_times.py`, part of `tests/test_world_times.py`.
- Modify: `discovery.py` (POOL_MODES, gem constants), `db.py`
  (`_discovery_where`), `app.py` (compose, handlers, stumble integration,
  destination clock, persistence), `screens.py` (help text), docs.
- Tests: ~13 new (270 → ~283).

## Risks

- `zoneinfo` needs a system tz database (Linux/macOS always have one; the
  app already targets those platforms).
- Large countries get a single zone by design — documented in
  `docs/discovery.md`.
