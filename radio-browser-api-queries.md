# Radio Browser API: Query Reference for Agents

Purpose: build correct HTTP queries against the Radio Browser API (community radio station directory) to find stations by name, country, state, language, genre/tag, or geographic location.

> Status: written from knowledge of the public API docs (https://api.radio-browser.info). Not executed against the live API. If a response shape differs from this document, trust the live response and print one raw record to inspect it.

---

## 1. Connection basics

### 1.1 Base URL

Use a server hostname, then `/json/...` for JSON output.

```
https://all.api.radio-browser.info/json/...
```

`all.api.radio-browser.info` resolves to all mirrors. For production use, pick one mirror at random and retry another if it fails. List mirrors:

```bash
curl -s https://all.api.radio-browser.info/json/servers
```

Typical mirror hostnames look like `de1.api.radio-browser.info`, `de2...`, `fi1...`, `nl1...`. Do not hardcode one; discover via `/json/servers`.

### 1.2 Required etiquette

- Always send a descriptive `User-Agent` header, e.g. `User-Agent: my-agent/1.0 (contact@example.com)`.
- Always set `limit`. Never fetch the whole catalog repeatedly; cache results.
- Prefer `hidebroken=true` to exclude stations whose last health check failed.
- No API key is required.

### 1.3 Methods

- `GET` with query string parameters works for every endpoint below.
- `POST` to `/json/stations/search` with `application/x-www-form-urlencoded` or JSON body is also supported (useful for long `tagList`).

---

## 2. The main endpoint: advanced search

```
GET /json/stations/search
```

Combine any of these parameters (all optional; combined with AND):

| Parameter | Type | Match behaviour | Example |
|---|---|---|---|
| `name` | string | Substring, case-insensitive | `name=capital` |
| `nameExact` | bool | If `true`, `name` must match fully | `nameExact=true` |
| `country` | string | Substring on country name | `country=kenya` |
| `countryExact` | bool | If `true`, full country name match | `countryExact=true` |
| `countrycode` | string | ISO 3166-1 alpha-2, exact (preferred for country) | `countrycode=KE` |
| `state` | string | Substring on state/region | `state=nairobi` |
| `stateExact` | bool | Full state match | `stateExact=true` |
| `language` | string | Substring on language name (lowercase names) | `language=swahili` |
| `languageExact` | bool | Full language match | `languageExact=true` |
| `tag` | string | Substring on a single tag | `tag=jazz` |
| `tagExact` | bool | Full tag match | `tagExact=true` |
| `tagList` | string | Comma-separated; station must have ALL tags | `tagList=jazz,blues` |
| `codec` | string | Audio codec | `codec=AAC` |
| `bitrateMin` | int | Minimum bitrate in kbps | `bitrateMin=128` |
| `bitrateMax` | int | Maximum bitrate in kbps | `bitrateMax=320` |
| `has_geo_info` | bool | Only stations with coordinates | `has_geo_info=true` |
| `has_extended_info` | bool | Only stations with extended info | `has_extended_info=true` |
| `is_https` | bool | Only HTTPS streams | `is_https=true` |
| `geo_lat` | float | Latitude of search centre | `geo_lat=-1.2921` |
| `geo_long` | float | Longitude of search centre | `geo_long=36.8219` |
| `geo_distance` | float | Radius in **meters** around the centre | `geo_distance=50000` |
| `order` | string | Sort field (see 2.1) | `order=votes` |
| `reverse` | bool | Reverse sort order | `reverse=true` |
| `offset` | int | Pagination offset | `offset=100` |
| `limit` | int | Max results | `limit=50` |
| `hidebroken` | bool | Hide stations that failed last check | `hidebroken=true` |

### 2.1 `order` values

`name`, `url`, `homepage`, `favicon`, `tags`, `country`, `state`, `language`, `votes`, `codec`, `bitrate`, `lastcheckok`, `lastchecktime`, `clicktimestamp`, `clickcount`, `clicktrend`, `changetimestamp`, `random`

For popularity ranking use `order=clickcount&reverse=true` or `order=votes&reverse=true`.

### 2.2 Geo search notes

- `geo_lat`, `geo_long` and `geo_distance` must be given together.
- `geo_distance` is in meters (50 km = `50000`).
- Only stations that have coordinates can match. Many stations have none.
- Result ordering by distance is not guaranteed; if nearest-first matters, compute the distance client-side from `geo_lat`/`geo_long` in each record.

---

## 3. Query recipes (copy and adapt)

All examples use `curl` and `jq`. Replace the host with a discovered mirror if desired.

```bash
BASE="https://all.api.radio-browser.info/json"
UA="my-agent/1.0"
```

### 3.1 By name

```bash
# Substring match
curl -s -H "User-Agent: $UA" "$BASE/stations/search?name=capital&hidebroken=true&limit=20"

# Exact name
curl -s -H "User-Agent: $UA" "$BASE/stations/search?name=Capital%20FM&nameExact=true&limit=20"

# Shortcut endpoint (substring, name in path)
curl -s -H "User-Agent: $UA" "$BASE/stations/byname/capital?limit=20"
```

### 3.2 By country

```bash
# By ISO code (most reliable)
curl -s -H "User-Agent: $UA" "$BASE/stations/search?countrycode=KE&hidebroken=true&limit=50&order=votes&reverse=true"

# By name
curl -s -H "User-Agent: $UA" "$BASE/stations/search?country=kenya&countryExact=true&hidebroken=true&limit=50"

# Shortcut endpoints
curl -s -H "User-Agent: $UA" "$BASE/stations/bycountrycodeexact/KE?limit=50"
curl -s -H "User-Agent: $UA" "$BASE/stations/bycountryexact/Kenya?limit=50"
```

### 3.3 By state / region

```bash
# State within a country
curl -s -H "User-Agent: $UA" "$BASE/stations/search?countrycode=US&state=california&hidebroken=true&limit=50"

# Exact state
curl -s -H "User-Agent: $UA" "$BASE/stations/search?countrycode=US&state=Texas&stateExact=true&limit=50"

# Shortcut
curl -s -H "User-Agent: $UA" "$BASE/stations/bystateexact/Texas?limit=50"
```

Tip: valid state values per country come from section 4.

### 3.4 By genre / tag

```bash
# Single tag (substring)
curl -s -H "User-Agent: $UA" "$BASE/stations/search?tag=jazz&hidebroken=true&limit=50&order=votes&reverse=true"

# Exact tag
curl -s -H "User-Agent: $UA" "$BASE/stations/search?tag=jazz&tagExact=true&hidebroken=true&limit=50"

# Multiple tags, station must have ALL of them
curl -s -H "User-Agent: $UA" "$BASE/stations/search?tagList=jazz,blues&hidebroken=true&limit=50"

# Shortcut
curl -s -H "User-Agent: $UA" "$BASE/stations/bytagexact/jazz?limit=50"
```

Tags are free-text, community-entered, and inconsistent (`hip hop`, `hip-hop`, `hiphop`). To find the real spellings, list tags (section 4) and filter.

### 3.5 By language

```bash
# Language names are lowercase English names
curl -s -H "User-Agent: $UA" "$BASE/stations/search?language=swahili&languageExact=true&hidebroken=true&limit=50"

# Shortcut
curl -s -H "User-Agent: $UA" "$BASE/stations/bylanguageexact/swahili?limit=50"
```

Each station record also has `languagecodes` (ISO 639 codes, comma-separated).

### 3.6 By geographic location (lat/long + radius)

```bash
# Stations within 50 km of Nairobi
curl -s -H "User-Agent: $UA" "$BASE/stations/search?geo_lat=-1.2921&geo_long=36.8219&geo_distance=50000&hidebroken=true&limit=50"

# Within 200 km of London, popular first
curl -s -H "User-Agent: $UA" "$BASE/stations/search?geo_lat=51.5074&geo_long=-0.1278&geo_distance=200000&order=votes&reverse=true&limit=50"

# Only stations that have coordinates at all
curl -s -H "User-Agent: $UA" "$BASE/stations/search?has_geo_info=true&countrycode=KE&limit=100"
```

### 3.7 Combined filters (typical real query)

```bash
# Swahili-language, news-tagged, working, HTTPS stations in Kenya, best first
curl -s -H "User-Agent: $UA" "$BASE/stations/search?countrycode=KE&language=swahili&tag=news&is_https=true&hidebroken=true&order=votes&reverse=true&limit=25"

# High-quality AAC jazz stations anywhere
curl -s -H "User-Agent: $UA" "$BASE/stations/search?tag=jazz&codec=AAC&bitrateMin=128&hidebroken=true&limit=25"

# Name plus country
curl -s -H "User-Agent: $UA" "$BASE/stations/search?name=radio%20citizen&countrycode=KE&limit=10"
```

### 3.8 Popularity and recency shortcuts

```bash
curl -s -H "User-Agent: $UA" "$BASE/stations/topclick/20"      # most clicked
curl -s -H "User-Agent: $UA" "$BASE/stations/topvote/20"       # most voted
curl -s -H "User-Agent: $UA" "$BASE/stations/lastclick/20"     # recently played
curl -s -H "User-Agent: $UA" "$BASE/stations/lastchange/20"    # recently changed
```

### 3.9 Lookup a specific station

```bash
curl -s -H "User-Agent: $UA" "$BASE/stations/byuuid/STATION_UUID"
curl -s -H "User-Agent: $UA" "$BASE/stations/byurl?url=https://example.com/stream.mp3"
```

---

## 4. Discovery lists (use these to get valid filter values)

```bash
curl -s -H "User-Agent: $UA" "$BASE/countries"                 # name, iso_3166_1, stationcount
curl -s -H "User-Agent: $UA" "$BASE/countrycodes"              # codes with counts
curl -s -H "User-Agent: $UA" "$BASE/states"                    # all states
curl -s -H "User-Agent: $UA" "$BASE/states/Kenya"              # states for one country
curl -s -H "User-Agent: $UA" "$BASE/languages"                 # language names with counts
curl -s -H "User-Agent: $UA" "$BASE/tags"                      # all tags with counts
curl -s -H "User-Agent: $UA" "$BASE/codecs"                    # codecs with counts
```

Useful filters:

```bash
# Tags with at least 100 stations, sorted by count
curl -s -H "User-Agent: $UA" "$BASE/tags?order=stationcount&reverse=true&hidebroken=true&limit=100"

# Find tag spellings containing "hop"
curl -s -H "User-Agent: $UA" "$BASE/tags/hop"
```

---

## 5. Station record fields (response)

Each station is a JSON object. Fields an agent will most often need:

| Field | Meaning |
|---|---|
| `stationuuid` | Stable unique ID |
| `name` | Station name |
| `url` | Stream URL as submitted |
| `url_resolved` | Resolved direct stream URL (prefer this for playback) |
| `homepage` | Station website |
| `favicon` | Logo URL |
| `tags` | Comma-separated genre/tags |
| `country` | Country name |
| `countrycode` | ISO 3166-1 alpha-2 |
| `iso_3166_2` | Region code (may be empty) |
| `state` | State/region |
| `language` | Comma-separated language names |
| `languagecodes` | Comma-separated language codes |
| `codec` | e.g. `MP3`, `AAC`, `OGG` |
| `bitrate` | kbps (0 = unknown) |
| `hls` | `1` if HLS stream |
| `votes` | Community votes |
| `clickcount` | Plays in the last 24h |
| `clicktrend` | Change in clicks |
| `lastcheckok` | `1` if last health check passed |
| `lastchecktime` | Time of last health check |
| `geo_lat`, `geo_long` | Coordinates (may be `null`) |
| `has_extended_info` | Whether extended info is present |
| `ssl_error` | `1` if TLS problem detected |

Other fields exist (`changeuuid`, `serveruuid`, `lastchangetime`, `lastcheckoktime`, `lastlocalchecktime`, `clicktimestamp`); ignore them unless needed.

Fields can be empty strings or `null`. Handle missing values defensively.

---

## 6. Playing a result with ffmpeg

Use `url_resolved`, falling back to `url`:

```bash
ffplay -nodisp "STREAM_URL"
ffmpeg -i "STREAM_URL" -t 600 -c copy out.mp3
```

To be polite to the directory and to improve click stats, you may register a play by calling:

```bash
curl -s -H "User-Agent: $UA" "$BASE/url/STATION_UUID"
```

This returns the resolved URL and counts one click.

---

## 7. Python helper (ready to reuse)

```python
import random
import requests

UA = {"User-Agent": "my-agent/1.0"}


def pick_server():
    r = requests.get("https://all.api.radio-browser.info/json/servers", headers=UA, timeout=15)
    r.raise_for_status()
    names = [s["name"] for s in r.json()]
    return f"https://{random.choice(names)}/json"


def search(base, **params):
    """params use the names from section 2, e.g. countrycode='KE', tag='news'."""
    params.setdefault("hidebroken", "true")
    params.setdefault("limit", 50)
    r = requests.get(f"{base}/stations/search", params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    base = pick_server()

    # name
    print(search(base, name="capital", limit=5))
    # country + language + tag
    print(search(base, countrycode="KE", language="swahili", tag="news", order="votes", reverse="true"))
    # geo: within 50 km of Nairobi
    print(search(base, geo_lat=-1.2921, geo_long=36.8219, geo_distance=50000))
```

---

## 8. Agent decision guide

| User intent | Use |
|---|---|
| "Find station called X" | `name=X` (add `nameExact=true` if full name known) |
| "Stations in country C" | `countrycode=<ISO>` (resolve code via `/countrycodes` if only a name is known) |
| "Stations in region R" | `countrycode` + `state=R` |
| "Genre G" | `tag=G`; verify spelling via `/tags/G` |
| "Genres A and B together" | `tagList=A,B` |
| "Language L" | `language=L&languageExact=true` (lowercase) |
| "Near a place" | Geocode the place to lat/long, then `geo_lat`, `geo_long`, `geo_distance` (meters) |
| "Best / popular" | `order=votes&reverse=true` or `order=clickcount&reverse=true` |
| "Only working" | `hidebroken=true` |
| "Browser-playable" | `is_https=true` |

Rules of thumb:

1. Narrow with `countrycode` first; it is the most reliable filter.
2. Always set `limit` and `hidebroken=true`.
3. Tags and languages are messy; query the discovery lists (section 4) to find the exact values before using `*Exact` flags.
4. Treat `geo_lat`/`geo_long` as optional; many stations lack them.
5. Cache discovery lists; they change slowly.
6. Prefer `url_resolved` for playback.

---

## 9. Common pitfalls

- Spaces in values must be URL-encoded (`Capital%20FM`), or pass params through a library like `requests`.
- Boolean params are the strings `true` / `false`.
- `country=` is a substring match, so `country=niger` also matches Nigeria. Use `countrycode` or `countryExact=true`.
- `tag=rock` also matches `punk rock`, `rock and roll`, etc. Use `tagExact=true` for strictness.
- Omitting `limit` can return a very large payload.
- A station with `lastcheckok=1` can still fail later; build retry logic.
- Mirrors can be temporarily down; retry on another mirror.
