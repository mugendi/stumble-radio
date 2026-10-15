# Stumble Radio

```text
              [    ST    ]
           stumble radio

       A radio for curious ears.
     Stumble into something good.
```

Stumble Radio is a Python terminal radio player for Linux and macOS. Explore the
community-maintained Radio Browser directory, discover a random station, build a
favourites library, and record what you hear. Its SQLite catalogue makes browsing
and searching independent of API response times once stations are cached.

## What you can do

- **Stumble:** tune a station from your current library and filters, weighted by
  your listening habits. Quick skips cool stations; longer listens boost them.
- **Teleport (`t`):** spin through country names, land in a random country, then
  tune a random station there. Countries get an equal chance regardless of size.
- **Session shuffle (`m`):** Anywhere → Music-only → Talk/News → Your language → Nearby.
- **Stream recovery:** skip stations that never start or stay silent while
  stumbling or teleporting; reconnect a playing station after an interruption.
- **Stay connected:** retry interrupted streams indefinitely and resume your
  station when internet access returns, with pause and sleep respected.
- **Search:** combine station name, exact country name or two-letter country code,
  state/region, language, genres/formats, codec, bitrate range, HTTPS, and geographic
  coordinates with a radius. Genres include music, talk, news, and anything else
  tagged in the directory.
- **Sort:** click any station-table header, then click again to reverse direction.
  Matching favourites stay first when sorting other columns; the star header can
  explicitly switch favourites first/last.
- **Listen:** play, pause/resume, change volume, or move to the next/previous station.
- **Save:** keep favourites across sessions and browse recent listening history.
- **Quick tune:** open a compact, searchable station picker for the current page.
- **Unheard:** browse or stumble through stations you have not played before.
- **Record:** save original audio without re-encoding, independently of playback pause.
- **Listening journal (`/`):** measured time per station, top stations, country and
  genre diversity, recent sessions, and your radio passport of countries heard.
- **Last Play Search (`l` / `Ctrl+L`):** find songs and artists you heard, with their
  stations and listening dates, newest first. Song history is kept for 365 days.
- **Sleep (`Z`):** choose a countdown and fade duration, then stop playback and recording.
- **PODMORO (`Ctrl+O`):** focus/break profiles, weekly starts, recurring reminders,
  local MP3 voice commands, and daily focus totals. Radio stays live during speech.
- **See what's on:** show the stream's title when the broadcaster provides metadata.
- **Keep browsing:** background sync is checkpointed, quiet, and automatically retried.

The interface supports keyboard and mouse, adapts to narrower terminals, and
keeps the current station playing while you search or open a dialog. A terminal
of at least **80 columns × 28 rows** is recommended; **110 × 35** gives more room
for station details. Use `Tab` / `Shift+Tab` to move between controls.

## Requirements

- Python **3.11 or later**.
- **mpv** on your `PATH` for playback.
- **FFmpeg** on your `PATH` for recording; browsing and playback work without it.
- An internet connection for radio streams and initial station discovery.
- Linux or macOS. On Windows, use **WSL** with working audio forwarding; native
  Windows playback is not implemented because the player uses Unix-domain IPC.

Install the audio tools with your system's package manager:

```bash
# Debian / Ubuntu
sudo apt install mpv ffmpeg

# Fedora
sudo dnf install mpv ffmpeg

# Arch
sudo pacman -S mpv ffmpeg

# macOS
brew install mpv ffmpeg
```

Package availability can depend on your distribution's enabled repositories.
mpv is controlled through its JSON IPC interface, which supports reliable external
pause, volume, metadata, and playback events. FFplay's interactive controls are
less convenient for this purpose. FFmpeg runs separately so a recording can
continue while you pause listening.

## Install globally

Run either installation command **from this project directory**. These install an
isolated Python application and expose `stumble-radio` globally for your user;
you do not need to activate a virtual environment or stay in the project folder.
The project does not need to be published on PyPI.

### Using uv

```bash
uv tool install .
uv tool update-shell
stumble-radio
```

Open a new terminal if the command is not yet on `PATH`. For an editable install
that follows changes in this checkout:

```bash
uv tool install --editable .
```

### Using pipx

```bash
pipx install .
pipx ensurepath
stumble-radio
```

### Without uv or pipx

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/stumble-radio
```

This last approach is local to the virtual environment. Use uv or pipx for a
globally available command without modifying system Python.

### Check the installation

```bash
stumble-radio --version
stumble-radio --doctor
```

`--doctor` lists the detected mpv and FFmpeg executables and the actual database
and recordings paths. It does not start audio or contact the directory.

## First launch

1. Run `stumble-radio`. No account, API key, or configuration file is needed.
2. The app starts downloading the catalogue in batches in the background. The
   status line shows how many stations are cached. You can use the app immediately.
3. Press **s** to stumble into a station, **t** to teleport, or **Ctrl+F** for advanced search.
4. Select a row with the arrow keys and press **Enter** to play it.
5. Press **f** to save the highlighted station to favourites.
6. Choose **Favourites**, **History**, or **Unheard** from the library dropdown.

On a fresh empty cache, Stumble can ask the API for random candidates without
waiting for the full catalogue. Search starts locally: use **Online ↻** / **u**
in Explore to fetch matching stations before the background download reaches them.
The app never autoplays on launch.

## Controls

Single-letter shortcuts apply outside text fields. When typing into an input,
letters and spaces enter text normally. Press `Tab` or `Enter` to return to the
station list. `Ctrl+Q` quits even while an input has focus.

| Key | Action |
| --- | --- |
| `s` | Stumble within current filters and library |
| `t` | Teleport to a random country and station |
| `m` | Cycle the session shuffle pool |
| `/` | Open listening journal, stats, and radio passport |
| `l` / `Ctrl+L` | Open Last Play Search (also the Last Play button); Ctrl+L works inside inputs |
| `Ctrl+F` | Open advanced search (also the Search button) |
| `Ctrl+G` | Set preferred language, location, and recovery timeout |
| `Ctrl+O` | Open the PODMORO scheduler (also the PODMORO button after Search) |
| `↑` / `↓` | Highlight a station |
| `Enter` | Play the highlighted station |
| `Space` | Pause/resume; play the selected station if stopped |
| `n` / `p` | Next/previous station within the visible results page, wrapping at the ends |
| `f` | Toggle favourite for the **highlighted** station |
| `Ctrl+B` | Open the quick tune picker for this results page |
| `+` / `-` | Raise/lower volume by 5 |
| `r` | Start or finish recording the **playing** station |
| `Z` / `z` | Set or cancel a sleep countdown and fade |
| `u` | Fetch another online results batch for Explore's current filters |
| `[` / `]` | Previous/next page (100 stations per page) |
| `?` | Show help |
| `Escape` | Close a dialog |
| `q` / `Ctrl+Q` | Quit and finalise any recording |

The transport buttons use **⏮** (previous), **▶** (play/resume), **⏸** (pause), and
**⏭** (next). The centre button shows the available action and switches as playback
changes; hover over an icon for its label and shortcut. **Library** cycles through
Explore, Favourites, History, and Unheard; it remains available on narrow terminals
where the sidebar is hidden. A library change clears filters so saved stations
are easy to find. The quick picker's text box filters the current page; use the
main search or advanced filters to search the entire catalogue.

## Teleport and smarter Stumble

**Teleport** chooses uniformly among countries with eligible cached stations,
animates a spinning destination header, and tunes there. When more than one
country is available, it avoids the currently playing country. Teleport clears
the name/country/region/radius restrictions for the trip; language, genre, codec,
bitrate, and health filters still apply. It explores the public catalogue,
independently of the selected personal library or session shuffle mode. If the
cache is empty, it can discover countries online and cache candidates on arrival.
The destination remains in the header after landing.

**Hot/Cold learning** stays entirely in SQLite:

- Switching away after **less than 10 seconds of measured listening** excludes
  that station from random selection for **24 hours**. Pausing, quitting, a sleep
  timer, and stream errors do not count as a voluntary quick skip.
- Each minute listened adds sampling weight, capped at **10×** the initial weight.
  Sampling stays random; a boosted station is never guaranteed to be chosen.
- Manually listening to a cooled station for **60 seconds** clears its cooldown.
  Explicit search, favourites, and manual tuning always remain available.
- A dead stream has a separate **15-minute** cooldown, without a taste penalty.
- Cooldowns and listening weights survive restarts. Directory sync preserves them.

### Session shuffle modes

Press **m** to cycle the pool used by your *next* Stumble:

| Mode | Eligible stations |
| --- | --- |
| Anywhere | Current library and advanced filters |
| Music-only | Recognised music tags, excluding talk/news/speech/sports tags |
| Talk/News | Tags containing talk, news, speech, or sports |
| Your language | Your saved language, overriding the language search field |
| Nearby | Your saved coordinates and radius, overriding the geographic search fields |

The active mode appears above the station browser. These modes change random
selection; they do not rewrite the station table's search. Other advanced filters
and the chosen library still apply. Music/talk classification is a heuristic
based on community tags, so untagged or unusual formats can be missed.

Use **Ctrl+G** to set one language name (for example, `english` or `swahili`),
latitude, longitude, and radius. Choosing a mode that needs missing information
opens this form; save it, then press `s`. No IP geolocation or device location is
collected. Settings persist, while the selected shuffle mode resets to Anywhere
on launch. Nearby can match only stations that supply coordinates.

### Reconnection, internet outages, and dead streams

Every station has automatic reconnection, including manually selected stations
and favourites. If a playing stream ends, disconnects, or stalls, the app retries
**that same station indefinitely**. A lost mpv connection also restarts the player.
Retries wait **1, 2, 4, 8, 16, then 30 seconds**, capped at 30 seconds between
subsequent attempts. Each attempt also needs time to connect/load. A successful
reconnection resets the delay for the next interruption and restores your volume.

When playback fails, lightweight TCP checks test the station host and Radio
Browser's bootstrap host in parallel, with a three-second timeout. These checks
download no audio or directory data and run only during recovery. If both hosts
are unreachable, the player shows **WAITING FOR NETWORK** and checks again every
**five seconds** after the probes finish. As soon as either becomes reachable, it
tries the current station immediately. Reachability checks are a network estimate;
a reachable host can still refuse a particular stream, which then keeps retrying.
`--offline` disables directory sync/API queries; streaming and these connection
checks still use the network.

During an outage, Stumble stays on the current station and does **not** blacklist
it, spend replacement attempts, or cycle through other stations. It also retries
the same station if an outage prevented the initial stream from loading.

Stumble and Teleport still skip an online station that **never starts**, or whose
decoded audio stays below **−50 dB RMS**. Detection uses mpv's FFmpeg `astats`
filter, rather than missing song titles or speaker volume. If metering is
unavailable, errors and position/stall checks still operate. Manually chosen
stations keep retrying connection/startup failures and are not skipped for silence.

The default timeout is **12 seconds**, configurable from **3–120 seconds** with
`Ctrl+G`. Checks run about once per second, so recovery may take slightly longer
than the configured threshold. Pressing **Space / Pause** during reconnection or
an outage suspends retries; press it again to resume that station. Changing
stations cancels the previous retry. Sleep expiry and quitting cancel retries too,
so playback cannot restart afterwards. A sleep countdown keeps running offline.
Changing the shuffle mode affects your next Stumble; dead-stream replacement
retains the original pool or Teleport country.

Recovery avoids failed candidates, can fetch more candidates online, and allows
up to **eight consecutive replacements** for dead/silent Stumble candidates. A
stream that stays healthy for twice the timeout resets that budget. If that pool
is exhausted, playback stops with a message. This budget does not limit same-station
reconnection. A missing mpv installation or invalid stream URL reports an error
instead of repeatedly attempting an unusable local setup.

Reconnecting finalises any existing recording, just as a manual retune does;
recording does not restart automatically. Press Record after playback returns to
start a new file. Interrupted time does not count toward listening totals. Quiet
programmes can trigger Stumble's silence threshold; raise the timeout or manually
tune that station if needed.

## Listening journal and radio passport

Press **/** for your journal. It shows total measured listening time, play count,
the ten stations you have spent the most time with, the latest 100 sessions, and
country passport stamps with listening time. Playback continues while it is open.
Close and reopen it to refresh the snapshot.

Time accumulates while playback is active; pause and buffering are excluded.
Detected silence is excluded when decoded audio metering is available. Listening is
checkpointed every five seconds and on station changes, journal opening, sleep,
and normal exit. A crash can lose the last few uncheckpointed seconds. Stations
enter history when their stream loads; failed startup attempts do not earn a
passport stamp. A country is stamped once measured listening time is positive.

Country and genre scores use **Simpson diversity**, expressed as
`100 × (1 − Σ share²)`. Zero means one category; the score approaches 100 as time
spreads evenly over more categories. Genre time is split equally between each
station's distinct tags. Unknown countries and empty tags are omitted from the
corresponding diversity calculation.

Per-station totals, learning weights, and passport stamps persist beyond the
5,000-event history window. Existing databases upgrade automatically, preserving
favourites and history. Older play events remain visible, but their duration is
unknown and is not invented retroactively.

## Last Play Search: find that song again

Press **l**, **Ctrl+L**, or the **Last Play** button. Stumble Radio saves song
metadata as you listen, so you can find which station played a track days or
months later. Playback continues while the search window is open.

For example, enter `Boyz` or `Boyz...` to find Boyz II Men tracks. Results show the
listening date and time in your local timezone, station, artist, song, and country,
ordered by **most recent play first**. Each listening occurrence is a separate
result, including the same song heard again later or on another station.

- Search words match **word prefixes** across artist, title, original ICY track
  text, and station name. `boyz bended` requires both prefixes somewhere in the
  entry; `beyonce` also matches `Beyoncé`. This is word-prefix search, rather than
  arbitrary substrings inside a word.
- Punctuation such as the dots in `Boyz...` is ignored. Quotes and words such as
  `OR` are treated as ordinary search text; the station search bar's field and
  boolean syntax does not apply here.
- Clear the input to browse recent songs. Results have **100 entries per page**;
  use the page buttons for older matches. **Refresh** reloads plays captured while
  the window is open.
- Press `Enter` or `↓` from the input to focus results, then `Enter` on a result
  to **tune its station live**. This does not replay the historical song or create
  an audio recording. Escape closes the window.

Artist/title tags and common ICY `Artist - Title` announcements are supported.
Unsplit announcements remain searchable as song text, with an unknown artist.
Repeated notifications for the same current track are suppressed. Tracks announced
while paused or buffering are saved when playback resumes. Station names and
stream URLs used by mpv as display fallbacks do not create song-history entries.

This depends on **metadata supplied by the broadcaster**: a stream without song
tags cannot supply song history, and inaccurate tags are preserved as provided.
There is no audio fingerprinting, microphone access, or external song-identification
service. History starts after installing this feature; older listening sessions
cannot be reconstructed into songs.

The local SQLite database stores entries in `track_plays`, with an **FTS5 index**
for search and a timestamp index for expiry. Entries older than a rolling **365
days** are deleted on startup and hourly while the app is open. Expired entries
are excluded from search immediately, including between cleanup runs. Deletion
also updates the full-text index. This retention applies to song history, leaving
favourites and listening totals intact. SQLite reuses freed space; deleting rows
does not necessarily shrink the database file on disk.

## PODMORO: focus scheduler and voice reminders

Open **PODMORO** after Search, or press **Ctrl+O**. The modal has four tabs:
**Session**, **Profiles**, **Schedules**, and **Voice clips**. Its countdown stays
visible above the station browser when you close the modal. On narrow terminals,
the top controls use two rows so PODMORO and Last Play remain reachable.

The scheduler is **off initially**. The included Classic profile uses 25 minutes
of focus, a 5-minute short break, and a 15-minute long break after four completed
focus blocks. It repeats until stopped. There are no bundled recordings: without
your MP3s, reminders appear visually and the timer still works.

### Sessions and profiles

Choose a profile in Session and press **Start**. Focus and break phases advance
automatically; radio music normally continues through both.

| Control | Behaviour |
| --- | --- |
| Pause / Resume | Freeze/resume the session clock and its interval reminders; pause dismisses speech |
| Stop | End the session silently; completed blocks and elapsed focus time remain in today's totals |
| Skip phase | Move to the next phase; skipping focus does not award a completed block |
| +5 minutes | Extend the current phase, up to 24 hours remaining |
| Quiet | Silence scheduled voices without stopping the timer or visual reminders |
| Snooze 5m | Repeat the latest reminder in five active minutes; unavailable for phase announcements |
| Dismiss voice | Stop the current announcement and clear its displayed message |
| Rearm schedules | Resume a scheduler suspended by the sleep timer |

In Profiles, create, duplicate, rename, save, or delete profiles. Durations can be
1–720 minutes, long breaks occur after 1–100 completed focus blocks, and the block
limit can be 0–1000. Zero repeats indefinitely; a nonzero limit finishes the
session immediately after its final focus block, without adding another break.

Optional **focus-ending** and **break-ending** warnings use seconds before the
phase deadline. Zero disables them, and a warning must be shorter than its phase
(a shared break warning must fit the shorter break). Editing a profile affects
the **next** session; the running session keeps a snapshot of its settings.
Profiles referenced by a schedule or the current session cannot be deleted until
those references are removed; at least one profile must remain.

To add an interval reminder, enter its command folder, interval, and eligible
phase, then **Add / update**. Select a reminder row with Enter to edit or remove
it; **New reminder** clears that selection. Intervals range from 1–1440 minutes.
For example, `reminders/stretch`, every `30`, during `Focus` counts only focus
minutes and carries that count across breaks. `Breaks` counts break time, and
`Either` counts both. Pausing the session stops those clocks.

Today's totals show completed focus blocks and elapsed focus minutes. These are
timer measurements, not a claim that attention or exercise was detected. Radio
pause and Quiet leave the focus clock running; use the scheduler's Pause when
you want its clock stopped too.

### Weekly schedules

In Schedules, choose **New schedule**, enter a name and a local 24-hour time such
as `09:00`, and enter weekdays such as `Mon,Tue,Wed,Thu,Fri`. Numbers `0` through
`6` also work, with Monday as zero. Choose either:

- **Start profile:** select the profile to begin at that time.
- **Speak reminder:** enter a command folder such as `reminders/water`; no active
  focus session is required.

Save the rule and check **Enable weekly scheduling while this app is open**.
Each rule also has its own enabled switch. For example, a weekday 09:00 Classic
start and a weekday 13:00 water reminder can be independent rules.

Schedules use your system's local timezone and run **only while the TUI is open**.
They do not install a daemon, wake a closed application, or replay missed starts.
A scheduled start never replaces an active or paused session. Repeated local
times during a daylight-saving fallback fire once; nonexistent spring-forward
times are skipped. A processing/clock gap greater than 60 seconds pauses a running
session rather than racing through overdue phases and announcements.

### Set up your voice library

Voice clips shows the current library path, category counts, Preview, Rescan, and
settings for an alternate library folder and independent voice volume (0–100).
`stumble-radio --doctor` also prints the default location. With the default Linux
data directory, it is:

```text
~/.local/share/stumble-radio/pomodoro/audio/commands/
  focus-start/
  focus-ending/
  short-break-start/
  long-break-start/
  break-ending/
  session-complete/
  reminders/
    water/
    stretch/
    eyes/
```

The default folders are created when you open the modal. Put short MP3 recordings
in their command folders; `.mp3` and `.MP3` extensions are accepted. Multiple
clips provide variety: selection is random, with no immediate repeat when an
alternative exists. New files are discovered before announcements, and **Rescan
folders** refreshes the visible counts.

For example, `focus-start/ready.mp3` might say “Time to focus,” and
`reminders/stretch/shoulders.mp3` might contain your own short stretch instruction.
Use generic wording if the clip is shared by profiles with different durations;
there is no text-to-speech substitution or generated speech.

An optional same-name UTF-8 text file supplies the caption:

```text
reminders/stretch/shoulders.mp3
reminders/stretch/shoulders.txt
```

Captions remain useful in Quiet mode or while radio is paused. If no clip exists,
the category/event label is displayed instead. Bad or unreadable clips report a
brief error and release the radio mute. Each announcement is capped at **120
seconds**; this version is for short commands, not long guided recordings.

Use **Create a custom command folder** for categories such as
`reminders/my-stretch`. Folder names accept letters, digits, hyphens, underscores,
and `/` between nested folders. Reminder rules reference that relative category,
so filenames within it can change freely. Keep referenced category names stable.
Clips and category symlinks must resolve inside the selected library directory.

**Preview clip** is an explicit audio action: it plays even in Quiet mode or while
radio is paused. Stop preview, close the modal, or press radio Pause to dismiss
it. No voice clips are downloaded or generated, and no speech service is contacted.
Future guided routines can reuse these categories as ordered steps with timed
gaps; this version does not yet include a routine editor or exercise programme.

### Audio, sleep, and recovery behaviour

Announcements use a separate mpv process. Radio is **muted, not retuned**, while
speech plays and returns to the live broadcast afterwards. Its user volume,
temporary voice mute, and sleep fade are combined, so volume changes, station
changes, and reconnects during speech do not undo the mute or restore an old level.

Manually pausing radio also silences scheduled voices; the timer and visual
reminders continue. Pausing the scheduler suppresses its speech too. Quiet is a
separate persistent preference. Network outages do not stop the local focus clock
or local voice files, provided you have not intentionally paused or silenced them.

Only one announcement plays at once. Phase announcements take precedence over
coincident reminders. Moving to a new phase discards stale in-session snoozes;
missed voices are not queued into a backlog when you unpause.

Voice audio never enters radio recordings or Last Play Search. Radio keeps
recording independently while muted, but voice-muted time is excluded from radio
listening totals. Songs announced by the station during speech are saved to Last
Play Search only if they are still current when audible radio resumes.

Sleep expiry stops speech, pauses the session, and suspends weekly triggers until
you manually Resume/Rearm them. Closing the app terminates voice playback and
saves a checkpoint. An interrupted session returns **paused**, without replaying
old speech. Profiles, rules, Quiet, library settings, daily totals, and checkpoints
are stored as a versioned `pomodoro_v1` record in the existing SQLite metadata
table; station/favourite/history tables are preserved. Checkpoints are saved on
controls, phase/calendar transitions, exit, and every 15 seconds while open. A
crash can lose up to roughly 15 seconds of timer progress.

## Sleep countdown and fade

Press **Z** (or `z`) to enter minutes and the final fade duration. For example,
`30` minutes with a `10` second fade gradually lowers volume during the last ten
seconds, then stops both playback and recording. Countdown limits are 0–1,440
minutes; fade limits are 0–300 seconds, capped at the countdown duration. A fade
of zero stops immediately when the timer expires.

The remaining time appears in the status line and sidebar. Use **Timer off** to
cancel. Cancelling during a fade or completing the timer restores the original
volume for the next playback. Expiry also cancels pending Teleport/recovery work,
so automatic discovery does not start another station after bedtime. Timers are
session-only and are not restored after restarting the app.

## Search bar: field filters and AND/OR queries

Type a query directly into the main search bar. Results update as you type.
Plain words match **station names or genre/format tags**, case-insensitively.
Use `name:` when you want to search station names specifically. All the filters
from the advanced-search form have a corresponding query operator below.

```text
rock county:kenya
slow genre:rock
country|rock|blues country:kenya
country+rock country:kenya
```

`county:` is accepted as an alias for `country:`. In the third example, the plain
word `country` means the music/format keyword; `country:kenya` is the geographic
filter. Any of the three keywords may match, but the station must be in Kenya.
The fourth example requires **both** the `country` and `rock` keywords in Kenya.

### Connectors, phrases, and grouping

| Syntax | Meaning | Example |
| --- | --- | --- |
| A space | AND between clauses | `slow genre:rock country:KE` |
| `+` | Explicit AND | `country+rock country:KE` |
| `\|` | OR | `country\|rock\|blues country:KE` |
| `(…)` | Group conditions | `(rock\|blues)+slow country:KE` |
| `"…"` | Keep words together as a substring phrase | `"classic rock" country:US` |
| `field:"…"` | A field value containing spaces or literal operators | `name:"Rock + Blues"` |

**A space separates clauses that must all match. Within a clause, `+` binds more
tightly than `|`; parentheses override the grouping.** In particular:

```text
country|rock|blues country:kenya
# (country OR rock OR blues) AND country:kenya

slow+rock|news country:KE
# ((slow AND rock) OR news) AND country:KE

(slow|smooth)+(rock|blues) country:KE
# (slow OR smooth) AND (rock OR blues) AND country:KE
```

The `#` lines above are explanations, not text to paste into the search bar.
Spaces around an explicit connector are allowed: `rock | blues country:KE`
has the same meaning as `rock|blues country:KE`.

OR works with field filters as well as words. Repeat the field name on each
alternative:

```text
country:KE|country:UG genre:rock
language:english|language:swahili country:KE
genre:rock|genre:blues country:KE
(country:KE|country:UG) (genre:rock|genre:blues) codec:MP3
```

Use `genre:rock+genre:blues` or `genre:rock,blues` when both exact tags must be
present. A comma is the tag-list separator, not a general OR connector.

Double quotes preserve spaces and literal `+`, `|`, or parentheses. Apostrophes
inside names are ordinary characters: `name:"America's Country"` works. To search
literal text containing a colon, use `text:"Radio:Jazz"` or `name:"Radio:Jazz"`.
For an embedded double quote, escape it with a backslash, for example
`name:"The \"Jazz\" Station"`.

The supported boolean connectors are **`+` and `|`**, with spaces as implicit
AND. The words `AND` and `OR`, minus/NOT, wildcards, and regular expressions are
not special operators. Name and word searches are literal substring matches.

### Complete operator reference

Operator names are case-insensitive. Do not put a space after the colon unless
the value is enclosed in double quotes.

| Operator | Aliases | Meaning and examples |
| --- | --- | --- |
| Plain word / `text:` | — | Name-or-tag substring: `slow`, `"classic rock"`, `text:"Radio:Jazz"` |
| `name:` | — | Station-name substring: `name:"Capital FM"` |
| `country:` | `county:`, `countrycode:` | Exact country name or two-letter ISO code: `country:kenya`, `country:KE`, `country:"United Kingdom"` |
| `state:` | `region:`, `city:` | Region/state substring: `region:Nairobi`, `state:California`. City data depends on the directory; this does not geocode a place name. |
| `language:` | `lang:` | Language-name substring: `language:swahili`, `lang:english` |
| `tags:` | `tag:`, `genre:`, `genres:`, `tagList:` | Exact community tags; comma lists or repeated clauses require all: `genre:rock`, `tags:jazz,blues` |
| `codec:` | — | Codec substring: `codec:MP3`, `codec:AAC`, `codec:"AAC+"` |
| `bitrate:` | — | Exact kbps or inclusive range: `bitrate:128`, `bitrate:128..320`, `bitrate:128..`, `bitrate:..192`. Zero disables that bound. |
| `bitrate_min:` | `minbitrate:`, `bitrateMin:` | Minimum kbps: `minbitrate:128` |
| `bitrate_max:` | `maxbitrate:`, `bitrateMax:` | Maximum kbps: `maxbitrate:320` |
| `https:` | `https_only:` | `https:true` restricts to HTTPS streams; `https:false` removes that restriction. |
| `broken:` | — | `broken:true` includes failed/unchecked stations; `broken:false` hides them (the default). It does not select only broken stations. |
| `hidebroken:` | — | Inverse spelling of `broken:`: `hidebroken:false` includes failed checks. |
| `near:` | — | Centre latitude, longitude, radius **in kilometres**: `near:-1.2921,36.8219,50` |
| `lat:` | `latitude:` | Latitude; use together with longitude and radius: `lat:-1.2921` |
| `lon:` | `longitude:` | Longitude: `lon:36.8219` |
| `radius:` | `radius_km:` | Positive radius in kilometres: `radius:50` |
| `sort:` | `order:` | Sort field; see values below: `sort:votes`, `sort:name` |
| `direction:` | `dir:` | `direction:asc` or `direction:desc` |
| `reverse:` | `descending:` | Boolean spelling of direction: `reverse:true` means descending. |

Boolean values accept `true`/`false`, `yes`/`no`, or `1`/`0`.

`sort:` values are `plays` (also `clicks` / `clickcount`), `votes`, `name`,
`country`, `genre` (also `tags`), `bitrate`, `favourites` (also `favorites`,
`favourite`, `star`), and `recent` (your most recently played stations).
Text columns default to ascending; numeric sorts, favourites, and recent default
to descending. `direction:` overrides the default.

Sorting and health visibility are query-wide options. Keep `sort:`, `direction:`,
`reverse:`, `broken:`, and `hidebroken:` outside OR groups. Separate `lat:`,
`lon:`, and `radius:` must appear together as query-wide clauses; use a complete
`near:` condition inside a boolean group instead. For example:

```text
(near:-1.2921,36.8219,50|country:UG) genre:news sort:votes
```

Single-valued filters cannot be repeated in the same AND clause; use OR for
alternatives. For example, write `country:KE|country:UG`, rather than two separate
country clauses. Tags may repeat because they accumulate as an AND list.

### More combinations

```text
# Slow rock stations in Kenya, most voted first
slow genre:rock country:KE sort:votes

# Country, rock, or blues in Kenya, popular first
country|rock|blues country:kenya sort:plays

# Both country and rock keywords, in Kenya
country+rock country:kenya

# Rock OR blues in Kenya OR Uganda, English-language, 128–320 kbps
(genre:rock|genre:blues) (country:KE|country:UG) lang:english bitrate:128..320

# Swahili news or talk in Nairobi
(genre:news|genre:talk) country:KE region:Nairobi language:swahili

# High-bitrate HTTPS jazz, alphabetical by station
genre:jazz codec:MP3 minbitrate:192 https:true sort:name

# A station-name phrase, including stations with failed checks
name:"Radio Citizen" country:KE broken:true

# Nearby stations, using either geographic spelling
near:-1.2921,36.8219,50 genre:news
lat:-1.2921 lon:36.8219 radius:50 genre:news

# Votes ascending, with favourites still grouped first
country:KE sort:votes direction:asc
```

Paste the query lines, without the explanatory `#` lines.

### Search form, errors, online results, and sorting

**Ctrl+F** opens the same filters as a form. Its Text / boolean clause field can
hold phrases and boolean groups; the other fields add AND restrictions. Applying
the form writes an equivalent query back into the search bar. Aliases and
connectors may be normalised, but their meaning stays the same. Editing/removing
an operator in the bar edits/removes that filter; there are no hidden form filters.

Incomplete quotes, missing values, unmatched parentheses, unsupported operators,
invalid bitrate ranges, and incomplete coordinates show an inline error. The
previous valid results remain visible. Online search, Stumble, and Teleport wait
until you fix or clear the invalid query. **× Clear** removes the entire query,
all constraints, and pagination; it keeps the selected library and shuffle mode.

The query applies to the **whole cached catalogue before sorting and pagination**,
not just the page on screen. It also constrains Stumble. Radio Browser does not
offer this complete boolean syntax, so online refresh fetches bounded candidate
pages and SQLite applies the full expression. A refresh can issue up to eight
requests of 100 candidates each, with duplicates merged. Larger expressions fall
back to a broader candidate page. Refresh again for the next page of candidates,
or let catalogue sync finish for complete local results. A small candidate batch
may not contain every match yet.

Click **★, Station, Country, Genre / format, kbps, Votes, or Plays/24h** to sort
the whole result list by that column. Click again to reverse it; the arrow shows
the active direction. Text columns begin A–Z and numeric columns highest first.
Matching favourites remain ahead of other results for these sorts. Clicking
**★** explicitly toggles favourites first/last, with names alphabetised within
each group. Genre sorting uses the station's complete tag string. The selected
sort appears in the query/filter summary, and sorting returns to page one.
History starts with recently played stations but can be re-sorted with any header.

### Advanced-form examples

Form fields combine with **AND**. Empty fields are unrestricted. Most text filters
match a case-insensitive substring; country is an exact name or exact ISO code.

| Find | Filters |
| --- | --- |
| Kenyan stations | Country: `KE` or `Kenya` |
| Swahili news in Kenya | Country: `KE`, Language: `swahili`, Genres: `news` |
| Regional stations | Country: `US`, State/region: `California` |
| Jazz with blues | Genres: `jazz,blues` (requires **both** exact tags) |
| Talk radio | Genres: `talk` |
| Higher bitrate MP3 | Codec: `MP3`, Min bitrate: `128` |
| Popular stations | Sort: Plays (24h), Descending checked |
| Alphabetical stations | Sort: Name, Descending unchecked |
| Stations within 50 km of Nairobi | Latitude: `-1.2921`, Longitude: `36.8219`, Radius: `50` |

Use **Apply filters** to search locally. **Reset** clears the search. Edit the main
query to narrow results without reopening the dialog. The form validates
bitrate ranges and requires all three geographic fields together.

Active advanced filters stay visible beneath the search bar, including country,
region, language, genres, codec, bitrate, radius, HTTPS, health, and non-default
sorting and boolean groups. This explains why a result list is restricted. The compact **× Clear**
button resets all search fields and sort choices, clears the query input, and
returns to the first page. It keeps your selected library and shuffle mode.

### Directory data limitations

- **Plays (24h)** is Radio Browser's recent click count; it is **not concurrent
  listeners**. The directory does not expose a reliable live listener count.
- Tags, languages, and regions are community supplied. For instance, `hip hop`,
  `hip-hop`, and `hiphop` may describe different sets of stations.
- The region field sometimes includes a city, but it is not a general address
  search. There is no built-in geocoder. Use explicit coordinates for radius search.
- Radius matches include only stations with coordinates; many do not have them.
  Results follow the selected sort, rather than distance from the search centre.
- A station that passed its last health check can still fail now. Favourites and
  history include saved stations even if they are now marked broken or removed.
- History is written when mpv reports that a stream loaded. It stores up to 5,000
  play events; the History view shows each station once, favourites first and then
  most recently played within each group by default. Clicking a header changes that sort.
  Unheard uses the persistent per-station play totals, including imported older history.

## Local database and background sync

SQLite is intentional: it provides a durable personal library, quick local
filtering, and directory browsing when API mirrors are unavailable. Playback
still needs access to each station's stream.

### Duplicate station records

Radio Browser can contain several UUIDs for exactly the same playback URL.
Station lists display **one row per exact cached playback URL** (`url_resolved`
when the API provides it, otherwise `url`). The database retains every API UUID
for syncing and personal history; a URL index supports grouping without deleting
or replacing your existing records.

Filters apply first, then matching records sharing a URL are grouped **before
sorting and pagination**. Result counts and page sizes therefore count distinct
streams. Within a matching group, the representative is chosen by a successful
last stream check, then a directly favourited record, then highest votes, then
UUID for a stable tie-break. Sort values come from that representative; duplicate
records' votes and directory play counts are not summed.

Favourites apply to every alias of the same URL. Removing a favourite removes its
saved aliases too. History and Unheard recognize plays through any alias, and
the journal's top stations combine their listening time. Stumble samples each URL
once, combines its listening time for weighting, and respects cooldowns and current
station exclusions across aliases.

Different URLs remain separate, including MP3/AAC variants, HTTP/HTTPS endpoints,
and URLs with different query parameters. The app does not follow every stream's
redirects or compare audio to guess which URLs carry the same programme. Entries
with no URL remain separate because an empty URL does not identify a stream.
The status line's cached-record count includes API aliases; station-list totals
count the matching distinct streams.

### Sync behaviour

- On startup, a stale or missing catalogue starts syncing without blocking the UI.
- The app discovers Radio Browser mirrors, picks a random mirror order, and retries
  other discovered mirrors on request failures. It sends `StumbleRadio/0.1.0` as
  its descriptive User-Agent and always bounds station requests with a limit.
- Full downloads use **1,000 records per batch**, with a brief pause between batches.
  Broken station entries are cached too; Explore and Unheard hide them by default.
- Each batch and its next offset commit in one SQLite transaction. Closing the
  app preserves progress; a download started less than 24 hours ago resumes next time.
- After a successful full scan, the catalogue is considered fresh for **24 hours**.
  While the app remains open, it checks hourly whether another scan is due.
- If sync fails, existing records remain usable and sync retries after five minutes.
  There are no repeated sync failure popups. The status line reflects the failure.
- Online search candidates are immediately merged by station UUID into the cache.
  Each request fetches a page of 100 candidates. Boolean queries may combine
  several bounded pages; the complete local expression decides which stations appear.
- Successful scans mark unseen records as absent from the public catalogue. They
  retain those records, favourites, and history so personal data is preserved.
- Downloads are paginated by name against a changing, mirrored directory. They
  provide an eventually consistent cache, not an atomic snapshot; directory changes
  during pagination may cause omissions until a later refresh.
- Background sync runs **only while the TUI is open**. There is no daemon, cron
  job, or separate service to install.

SQLite uses WAL mode and short-lived worker-thread connections, so database work
does not block input or audio controls. The app's async API requests also run
outside the UI message handlers. Search terms are bound SQL parameters, and sort
columns are restricted to known fields.

## Recording

Press **r** while listening to begin recording. Press **r** again to finish.
Files use a timestamp, a sanitised station name, and a unique suffix:

```text
20261015-213500-Example-Jazz-a1b2c3.mka
```

Recordings contain the original audio stream in a **Matroska audio (.mka)**
container. Stream copying avoids quality loss and works with common radio codecs
without guessing the correct filename extension. You can play the result in mpv
or VLC, or remux/convert it with FFmpeg when needed.

- Recording opens a **separate connection** to the same stream. It uses additional
  network bandwidth; stations with connection limits may reject that connection.
- Pausing playback **does not pause recording**.
- Switching stations stops and finalises the current recording; press `r` to
  record the new station.
- Quitting normally or finishing the sleep timer finalises the recording too.
- A stream or disk failure is reported. A forced process kill or power loss may
  leave an incomplete file. There is no built-in duration or disk-space limit.

To extract MP3 audio from a recording whose source codec is MP3:

```bash
ffmpeg -i recording.mka -c:a copy recording.mp3
```

For a different source codec, choose a compatible container or re-encode explicitly.

## Files and command-line options

Default data location:

| Platform | Directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/stumble-radio` or `~/.local/share/stumble-radio` |
| macOS | `~/Library/Application Support/stumble-radio` |

The directory contains `radio.sqlite3`, SQLite's transient WAL files, and a
`recordings/` subdirectory. Favourites and history are stored in the database;
they do not require a separate account or cloud service. No telemetry is added.
When online, a successful play sends the directory's standard click notification.

```bash
stumble-radio --help
stumble-radio --version
stumble-radio --doctor
stumble-radio --offline
stumble-radio --data-dir /path/to/library
stumble-radio --recordings-dir /path/to/recordings
```

`--offline` disables **all directory API requests**, including catalogue sync,
online search, and play notifications. It does not disable network audio streams;
stations saved in the cache remain playable when their streams are reachable.
An empty offline cache has no stations to display.

### Back up or reset

Close the app before copying the entire data directory. Restoring that directory
restores favourites, listening history, and the catalogue. Copy recordings too if
you use a separate recordings directory. Removing the database resets **all**
station data, including favourites and history; prefer backing it up first.

### Uninstall

```bash
uv tool uninstall stumble-radio
# or
pipx uninstall stumble-radio
```

Uninstalling the application leaves your database and recordings in place.

## Troubleshooting

**`stumble-radio: command not found`**

Run `uv tool update-shell` or `pipx ensurepath`, then open a new terminal. Confirm
that the tool installation succeeded. The command is `stumble-radio`.

**No stations appear on first launch**

Allow the initial batch to arrive, press `s`, or enter filters and use `Online ↻`.
Check the status line for a directory connection failure. The cache starts empty;
there are no bundled pretend stations.

**Missing mpv or FFmpeg**

Run `stumble-radio --doctor`. Install the missing executable and ensure the terminal
running Stumble Radio can find it on `PATH`. FFmpeg alone is enough for recording,
but mpv is required for playback.

**A station fails or there is no sound**

Try a different station. Some listed streams are offline, restricted by location,
or temporarily unavailable. Check system volume and the TUI volume. To separate
audio-device problems from a stream problem, try `mpv 'STREAM_URL'` in a terminal.
The app uses mpv with `--no-config`, so user mpv scripts and settings do not affect it.

**Search finds fewer stations than expected**

Wait for catalogue sync or use `Online ↻` in Explore. Clear extra filters, try the
country's two-letter code, vary tag spelling, and check whether you enabled HTTPS,
bitrate, health, or geographic restrictions. Radius filtering cannot include
stations without coordinates.

**Recording fails**

Confirm FFmpeg is available, the destination is writable, and the disk has space.
Some stations reject a second connection or use an incompatible stream. The error
notification includes the end of FFmpeg's error output. Use a different station
to determine whether the problem is broadcaster-specific.

**A dialog is too tall or columns are cut off**

Enlarge the terminal, reduce its font size, or scroll. The advanced-search form
scrolls independently. The station table scrolls horizontally; narrow terminals
hide the sidebar, and the Library button still switches views.

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
