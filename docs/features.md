# Feature guide

[← Stumble Radio](../README.md)

Everything Stumble Radio does, grouped so you can find it. Each section links
to the manual that covers it in detail, and most screens appear in the manuals.

![Stumble Radio playing Kameme FM while the sidebar lists the catalogue](images/player.png)

## The dial: everyday listening

Everything you browse lives in the table on the left; what you hear sits above
it.

- Choose one of four libraries from the sidebar dropdown: Explore (the cached
  public directory with failed checks hidden), Favourites, History, or Unheard.
  Each page holds up to 100 rows and "[" / "]" turns pages.
- What you hear stays pinned above all rows with a play marker, starred if it
  is a favourite, so a long list never buries it. The pin is clickable: click
  to jump the table to that station, double-click to pause or resume, and
  right-click for its notes.
- Press "f" to favourite the playing channel. If nothing is playing, it acts
  on the highlighted row, but asks first. Favourites rank first in every result
  set until you sort another way.
- Right-click or press "i" on any station to keep private notes and personal
  tags, which are searchable (try "happy tunes").
- "Ctrl+B" opens a compact searchable picker for the current page. Type a few
  letters, press Enter, and you are listening.
- "n" and "p" step to the next or previous station within the visible page and
  wrap at the ends.
- "+" and "−" adjust the master volume, which is remembered between sessions.
- The now-playing panel shows the broadcaster's song title when the stream
  carries it.
- Each record is one row per identical stream URL, and broken entries stay
  hidden until you ask for them. A local SQLite copy of the directory is
  updated in the background, so browsing and listening never wait on the
  network.

Manual: [Favourites, browsing, catalogue sync and storage](library.md)

## Search

- The quick-search field speaks the full query language. Filter on country
  (country:KE), state or region, genre (genre:tarab), language, codec, bitrate,
  HTTPS-only, or coordinates with a radius.
- Combine conditions with OR (genre:jazz|genre:blues), AND (country+rock),
  parentheses, and phrase quoting.
- "Ctrl+F" opens the advanced form where every filter has its own field.
- An invalid query keeps the previous results on screen and explains the error.
- Click any column header to sort, and again to reverse. Votes, plays in the
  last 24 hours, name, country, bitrate and more are supported.
- Press "u" to refresh the current Explore filters from the directory online.

Manual: [Search syntax, all filters and worked examples](search.md)

## Stumble, teleport and shuffle

![Landed in Japan with Music-only shuffle and Breakfast Shows sync above the station browser](images/discovery.png)

- Stumble ("s") is random radio that learns. Quick skips cool a station for 24
  hours, dwell time boosts it, and dead or silent streams are replaced while
  you listen.
- Teleport ("t") spins a destination header through the countries that have
  eligible cached stations, avoids the country you are leaving, and lands.
- Shuffle pools ("m") set where the next Stumble draws from:

  | Pool | Selection |
  | --- | --- |
  | Anywhere | Current library and filters |
  | Music-only | Music tags, excluding talk/news/speech/sports |
  | Talk/News | Talk, news, speech or sports tags |
  | Your language | Your saved language from Ctrl+G |
  | Nearby | Your saved coordinates and radius |
  | Hidden gems | At most 10 votes and 15 clicks, so undiscovered channels surface |

- Station Sync is the sidebar dropdown next to the shuffle mode. Pick
  Breakfast, Afternoon, Evening or Late Night Shows and Stumbles land only on
  stations where that radio-day phase is happening now. If nothing fits, the
  toast says so and installs land anywhere instead. A live local-time clock
  shows the playing country's hour, and the choice persists.
- Discovery settings ("Ctrl+G") hold one language, latitude, longitude and
  radius for Nearby, and the dead-stream timeout. Nothing is inferred from your
  IP.

Manual: [Stumble, Teleport and shuffle modes](discovery.md)

## The journal and Last Play

![Radio passport with countries heard and listening totals](images/journal.png)

- The listening journal ("/") shows time per station, top stations, recent
  sessions and why each ended (skip, sleep, quit).
- The radio passport collects the countries you have heard and tracks region
  and genre diversity.
- Last Play Search ("l" or "Ctrl+L") searches every artist, song title and
  station heard in the past year, shows when and where, and retunes straight
  from the result.

Manual: [Listening journal and radio passport](journal.md), [Last Play Search](last-play.md)

## Sound

![Equalizer screen with five bands and gain](images/equalizer.png)

- Five-band equalizer with Flat, Bass boost, Speech, Rock, Pop, Jazz and
  Classical presets. Adjustments preview live and are saved.
- Gain adds up to +12 dB separately from volume.
- Auto loudness level is on by default. It lifts quiet stations and reins
  loud ones, so changing channels does not blast you.

Manual: [Playback: equalizer, levels and sleep](playback.md#equalizer-and-gain)

## Sleep and Podmoro

![Sleep countdown with fade in progress](images/sleep-fading.png)

- The sleep countdown ("Z") takes minutes or an absolute time, optionally with
  a fade. When it fires, playback and recording stop together.
- Podmoro ("Ctrl+O") is a Pomodoro scheduler built for radio:
  - Focus and break profiles: classic plus your own lengths, warnings and
    long-break rhythm.
  - Weekly schedules: auto-start a profile, for example weekday mornings
    09:00.
  - Voice reminders: your own short MP3s in command folders (water, stretch,
    eye-break, break endings, custom prompts) with captions and previews.
  - Pause, skip, extend, snooze or silence any prompt without losing your
    place. Daily focus totals are tracked.

![Podmoro session with focus countdown and a reminder playing](images/podmoro-session.png)

Manual: [Podmoro, scheduling and step-by-step sound setup](podmoro.md)

## Recording

- "r" starts and stops recording of the original stream audio into a Matroska
  (".mka") file on this machine.
- Recording continues while you browse or pause, and ends when you retune.

Manual: [Playback: recording](playback.md#recording)

## Streams that come back

![Recovery toast after a silent stream, with reconnect state shown](images/recovery.png)

- Dead, stalled or silent streams are detected after the timeout from Ctrl+G,
  and during random discovery the app replaces them with another station.
- Interrupted streams retry on their own. An outage suspends retries and
  "Space" queues the return: press it again to resume that station.
- The app starts and works from a cold cache with a working offline build; no
  operation waits for the network unless you ask for one.

Manual: [Reconnection, internet outages, and dead streams](playback.md#reconnection-internet-outages-and-dead-streams)

## The app itself

- A newer release is checked at launch and cached for a day. Press "U" to
  confirm: the app hands itself over without losing your radio timer or a
  running recording, upgrades with the same installer it came from, and opens
  the new version.
- The station you last heard shows as "▶ LAST · name · Space resumes" at
  launch, and "Space" picks it up again. The same clicks work on that line:
  click to find it in the table, double-click to resume, right-click for notes.
- The help screen ("?" or the button) maps every key and note worth knowing.
- Narrow terminals are handled: the layout folds, and the sidebar and
  destination line give way step by step.

![In-app help with every key binding](images/help.png)

## Keyboard quick reference

| Key | Action |
| --- | --- |
| s, t, m | Stumble, Teleport, cycle shuffle pool |
| Enter, Space | Play highlighted station; pause, resume or pick up |
| n, p | Next or previous station in page |
| /, l, Ctrl+L | Journal; Last Play Search |
| Ctrl+F, Ctrl+G, Ctrl+O | Advanced search, discovery settings, Podmoro |
| Ctrl+B | Quick tune picker |
| f, i | Favourite; station notes and tags |
| e, +, − | Equalizer; volume up; volume down |
| r, Z | Record; sleep timer |
| u, U, [, ] | Refresh filters online; upgrade app; page back; page forward |
| ?, q | Help; quit |

The full list lives in the help screen and in
[playback controls](playback.md#controls).
