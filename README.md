# Stumble Radio

![Stumble Radio terminal player with station browser, favourites and playback controls](docs/images/player.png)

*The actual TUI, shown with demonstration stations and listening data.*

## What it is

Stumble Radio is a terminal radio player for curious ears. Search the world’s
radio stations, stumble into something new, and keep your favourites close.
Built with Python and SQLite, with a local station catalogue for fast search.
Use the keyboard or mouse; the layout adapts to smaller terminals.

## Why

I enjoy music as I work. I actually find it hard to work in absolute silence.
I have always wanted a good terminal music/radio player, and I have tested several
without ever being very happy with them. I once even tried building my own player,
[Geek Play](https://github.com/mugendi/geek-play), but abandoned the project when
a close collaborator, [Joseph Ndung’u](https://github.com/joseph-n),
[passed on](https://github.com/mugendi/geek-play/blob/master/eulogy.md).

Many times I just listen to [Radio Garden](https://radio.garden/). But that means
adding one more browser tab, which sometimes disconnects. I also think the search
and station sorting features can be greatly enhanced.

Finally, I got researching. With the aid of AI, it is now much easier to build a
real terminal radio with a tonne of features. Here is what Stumble Radio can do.

## Features

### Listen, record and drift off

- Play/pause, previous/next station, volume controls, and broadcaster song metadata.
- Record the original audio while continuing to browse or pausing your listening.
- Retry interrupted streams and resume when the internet comes back.
- Automatically skip dead or silent stations during random discovery.
- Set a sleep countdown with a fade, then stop playback and recording.

[Playback, recording, sleep and keyboard controls →](docs/playback.md)

### Discover somewhere new

- **Stumble:** random radio that learns from quick skips and longer listens.
- **Teleport:** spin through country names, land somewhere, and listen there.
- **Shuffle modes:** Anywhere, Music-only, Talk/News, Your language, and Nearby.

[Stumble, Teleport and shuffle modes →](docs/discovery.md)

### Find exactly what you want

- Filter by name, country, region, genre/format, language, codec, bitrate, HTTPS,
  stream health, or geographic radius.
- Combine search operators, phrases, AND (`+`), OR (`|`) and parentheses.
- See every active filter, clear them in one click, and click any header to sort.
- Sort by votes, recent directory plays, name, country and more, with matching
  favourites first.

[Search syntax, all filters and worked examples →](docs/search.md)

### Keep your own dial

- Save favourites and browse Explore, Favourites, History, or Unheard.
- Open a compact, searchable Quick tune picker.
- Browse a local SQLite catalogue, quietly updated in the background.
- See one row per identical stream URL, keeping your favourites and history intact.

[Favourites, browsing, catalogue sync and storage →](docs/library.md)

### See where you have been

- Open your listening journal for time per station, top stations and recent sessions.
- Collect a radio passport of countries heard and track country/genre diversity.

[Listening journal and radio passport →](docs/journal.md)

### Find that song again

- **Last Play Search:** search remembered artists, songs or stations you heard.
- See where and when you heard each track, newest first, and tune that station.
- Search a local full-text index; plays older than one year are removed automatically.

[Last Play Search →](docs/last-play.md)

### Work with a rhythm

- **PODMORO:** custom focus/break profiles, weekly schedules and daily focus totals.
- Interrupt the music with your own MP3 voice prompts for breaks or reminders.
- Add water, stretch, eye-break or custom command folders; preview clips and captions.
- Pause, skip, extend, snooze or silence reminders without losing your place.

[Podmoro, scheduling and step-by-step sound setup →](docs/podmoro.md)

## Get started

You need **Python 3.11+**, **mpv**, and **FFmpeg** if you want to record.
Linux and macOS are supported; Windows users need WSL with working audio.

From this project’s checkout, install a globally available command with uv:

```bash
uv tool install .
uv tool update-shell
stumble-radio
```

Open a new terminal if needed. Press **s** to Stumble, **t** to Teleport,
**Ctrl+F** to search, **Ctrl+O** for Podmoro, and **?** for help.

[Installation, audio dependencies and first launch](docs/getting-started.md) ·
[Troubleshooting](docs/troubleshooting.md) ·
[Development](docs/development.md)

Station directory provided by the [Radio Browser community](https://www.radio-browser.info/).
