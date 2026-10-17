"""Regenerate docs/images/*.png from a fictional demonstration catalogue.

No audio is played, no network request is made, and your real library is never
touched. Run from the project root:

    .venv/bin/python scripts/screenshots.py [names ...]

Requires inkscape (or another SVG rasteriser through --converter override).
"""

import asyncio
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from textual.widgets import Button, DataTable, Input, Select, Static, TabbedContent

from stumble_radio.announcements import AudioLibrary
from stumble_radio.app import StumbleRadio
from stumble_radio.db import Database
from stumble_radio.discovery import DiscoverySettings
from stumble_radio.equalizer_screen import EqualizerScreen
from stumble_radio.models import Station
from stumble_radio.pomodoro import COMMANDS, Announcement, Profile, Reminder, Schedule
from stumble_radio.pomodoro_screen import PomodoroScreen
from stumble_radio.query import parse_query
from stumble_radio.screens import (
    HelpScreen,
    JournalScreen,
    LastPlayScreen,
    SearchScreen,
    SettingsScreen,
    SleepScreen,
    StationNotesScreen,
    StationPicker,
)

DATA_DIR = ROOT / ".screenshots-demo"
IMAGES = ROOT / "docs" / "images"
TMP = Path("/tmp/opencode/stumble-shots")
VOICE_ROOT = Path("/tmp/stumble-radio-demo/.voice-library")
TITLE = "Stumble Radio · demonstration"
SIZE = (124, 36)
EXPORT_WIDTH = 1873

STATION_NAMES = [
    "Kameme FM",                                                # KE · swahili
    "NRG Radio",                                                # KE · pop
    "Radio Kaya",                                               # KE · jazz/tarab
    "REGGAE ROOTS",                                             # KE · reggae
    "Jazz Sakura (asia dream radio)",                           # JP · jazz
    "Listen.Moe JPop Vorbis",                                   # JP · jpop
    "Anime Para Ti",                                            # JP · anime
    "Classic Vinyl HD",                                         # US · standards
    "Adroit Jazz Underground",                                  # US · jazz
    "101 SMOOTH JAZZ",                                          # US · smooth jazz
    "Dance Wave!",                                              # HU · dance
    "Radio Paradise Main Mix (EU) 320k AAC",                    # US · eclectic
    "BBC World Service",                                        # GB · news
]
REAL_DB_PATH = Path.home() / ".local" / "share" / "stumble-radio" / "radio.sqlite3"

# Fallback specs for catalogue names the real database no longer carries.
SYNTH_SPECS = {
    "NRG Radio": {
        "station": {
            "country": "Kenya", "cc": "KE", "state": "Nairobi",
            "lang": "swahili,english", "tags": "pop,hip hop,afrobeat,afrobeats",
            "codec": "MP3", "bitrate": 128,
        },
        "votes": 410, "plays": 260, "lat": -1.2921, "lon": 36.8219,
    },
}


def load_real_specs() -> list[dict]:
    """Pull the curated demonstration stations straight out of a real catalogue."""
    import sqlite3

    query = ",".join("?" * len(STATION_NAMES))
    db = sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True)
    rows = db.execute(
        "select stationuuid, name, url, country, countrycode, state, language,"
        "tags, codec, bitrate, votes, clickcount, geo_lat, geo_long"
        " from stations where lastcheckok=1 and name in"
        f" ({query}) order by votes desc",
        STATION_NAMES,
    ).fetchall()
    db.close()
    specs: dict[str, dict] = {}
    for r in rows:
        if r[1] in specs:  # keep the highest-voted variant per name
            continue
        specs[r[1]] = {
            "uuid": r[0], "name": r[1], "url": r[2], "country": r[3], "cc": r[4],
            "state": r[5], "lang": r[6], "tags": r[7], "codec": r[8],
            "bitrate": r[9], "votes": r[10], "plays": r[11],
            "lat": r[12], "lon": r[13],
        }
    for name, spec in SYNTH_SPECS.items():
        if name not in specs:
            slug = name.lower().replace(" ", "-").replace("!", "").replace(".", "")
            specs[name] = {
                "uuid": uuid5(NAMESPACE_DNS, f"demo:{slug}").hex,
                "name": name,
                "url": f"https://streams.example.org/{slug}",
                "votes": spec["votes"], "plays": spec["plays"],
                "lat": spec["lat"], "lon": spec["lon"], **spec["station"],
            }
    missing = set(STATION_NAMES) - {s["name"] for s in specs.values()}
    if missing:
        raise SystemExit(f"Stations missing from {REAL_DB_PATH}: {sorted(missing)}")
    return [specs[name] for name in STATION_NAMES if name in specs]


STATIONS = load_real_specs()

# Real broadcast metadata for the "now playing" read-outs and Last Play dialog.
TRACKS = [
    ("Kameme FM", "Mercy Masika", "Mwema", 0),
    ("Jazz Sakura (asia dream radio)", "Tatsuro Yamashita", "Ride on Time", 1),
    ("Classic Vinyl HD", "Boyz II Men", "I'll Make Love to You", 3),
    ("Adroit Jazz Underground", "Shouse", "Love Tonight", 2),
    ("101 SMOOTH JAZZ", "Shouse", "Love Tonight", 5),
    ("Dance Wave!", "Jain", "Makeba", 4),
    ("Jazz Sakura (asia dream radio)", "Édith Piaf", "La Vie en Rose", 7),
    ("Kameme FM", "Sonstone", "Nikupende", 6),
    ("Radio Paradise Main Mix (EU) 320k AAC", "Shouse", "Love Tonight", 9),
    ("Listen.Moe JPop Vorbis", "Yorushika", "Kataomoi", 8),
]

LISTENING = {  # station name -> total measured seconds across sessions
    "Kameme FM": 7400, "Jazz Sakura (asia dream radio)": 5900,
    "Classic Vinyl HD": 4300, "Adroit Jazz Underground": 3700,
    "101 SMOOTH JAZZ": 3100, "Dance Wave!": 2600,
    "Listen.Moe JPop Vorbis": 2100, "Anime Para Ti": 1800,
    "Radio Kaya": 1500, "NRG Radio": 900, "REGGAE ROOTS": 600,
    "Radio Paradise Main Mix (EU) 320k AAC": 400, "BBC World Service": 150,
}
FAVOURITES = ("Kameme FM", "Jazz Sakura (asia dream radio)", "Adroit Jazz Underground")


def make_station(spec: dict, index: int) -> Station:
    return Station(
        stationuuid=spec["uuid"], name=spec["name"], url=spec["url"],
        country=spec["country"], countrycode=spec["cc"], state=spec["state"],
        language=spec["lang"], tags=spec["tags"], codec=spec["codec"],
        bitrate=spec["bitrate"], votes=spec["votes"], clickcount=spec["plays"],
        lastcheckok=1, geo_lat=spec.get("lat"), geo_long=spec.get("lon"),
    )


def clean_demo_data() -> None:
    for path in (DATA_DIR / "radio.sqlite3",):
        if path.exists():
            path.unlink()
    for path in DATA_DIR.rglob("*.sessions*"):
        path.unlink()


def seed_database(db: Database, stations: list[Station], by_name: dict) -> None:
    db.upsert(stations)
    for name in FAVOURITES:
        db.toggle_favourite(by_name[name])
    for name, seconds in LISTENING.items():
        station = by_name[name]
        sessions = max(1, round(seconds / 600))
        per_session = seconds / sessions
        for count in range(sessions):
            history_id = db.add_history(station)
            reason = ("sleep", "quit", "skip")[count % 3]
            seconds_for_session = per_session * (5 if reason != "skip" else 0.1)
            if count == sessions - 1:
                seconds_for_session = max(0, seconds - (sessions - 1) * per_session)
            db.save_listening(history_id, seconds_for_session, reason)
    now = time.time()
    for index, (station_name, artist, title, days_ago) in enumerate(TRACKS):
        station = by_name[station_name]
        played_at = now - timedelta(days=days_ago, hours=index * 2).total_seconds()
        icy = f"{artist} - {title}"
        from stumble_radio.tracks import Track

        db.add_track(station, Track(artist, title, icy), played_at=played_at)
    db.save_station_notes(
        by_name["Kameme FM"],
        "Prayer hour at dawn, then nonstop Kikuyu pop all day.\n\n"
        "The request show after 16:00 is worth staying for.",
        "kikuyu classics, request hour, morning shows",
    )


def lately(app: StumbleRadio, station: Station) -> None:
    """Present a station as live: transport, meter, track and totals."""
    app.playback_wanted = True
    app.user_paused = False
    app.automatic = True
    app.has_played = True
    app.play_state = "PLAYING"
    app.connection_state = ""
    app.current = station
    artist, title, _ = next(
        ((track[1], track[2], track[3]) for track in TRACKS
         if track[0] == station.name),
        ("Nina Simone", "Feeling Good", 0),
    )
    app.media_title = f"{artist} — {title}"
    app.track_metadata = {"icy-title": f"{artist} - {title}"}
    wave = [
        0.06, 0.09, 0.14, 0.2, 0.28, 0.37, 0.45, 0.52, 0.6, 0.66,
        0.71, 0.74, 0.72, 0.68, 0.63, 0.55, 0.47, 0.41, 0.37, 0.4,
        0.48, 0.58, 0.66, 0.71, 0.73, 0.7, 0.64, 0.58, 0.5, 0.43,
        0.39, 0.42, 0.5, 0.58, 0.62, 0.6, 0.54, 0.46, 0.36, 0.28,
        0.22, 0.19, 0.17, 0.18, 0.22, 0.28, 0.33, 0.36,
    ]
    wave += wave[:24]
    wave += [
        0.06, 0.09, 0.14, 0.2, 0.3, 0.42, 0.55, 0.68, 0.78, 0.85,
        0.8, 0.7, 0.56, 0.46, 0.36, 0.3, 0.26, 0.34, 0.46, 0.6,
        0.7, 0.62, 0.44, 0.24,
    ]
    app.audio_levels = wave[-64:]
    app.wave_lo, app.wave_hi = 0.03, 0.9
    app.update_pinned_station()
    app.update_now_playing()
    app.update_status()


def tune_cursor(app: StumbleRadio, station_name: str) -> None:
    for index, station in enumerate(app.stations):
        if station.name == station_name:
            app.query_one(DataTable).move_cursor(row=index)
            break
    app.update_details()


async def prep_context(app: StumbleRadio) -> None:
    """Apply state shared by most captures."""
    app.volume_value = 80
    app.sync_state = "Demonstration catalogue"
    app.catalogue_count = len(STATIONS)
    app.settings = DiscoverySettings(
        language="english", latitude=-1.2921, longitude=36.8219, radius_km=50,
        recovery_seconds=12,
    )
    app.destination, app.destination_landed = "Earth", False
    app.update_discovery_line()
    app.update_destination_line()


def deep_profile() -> Profile:
    return Profile(
        name="Deep Work", focus=50, short_break=10, long_break=20, long_every=3,
        focus_warning=120, break_warning=60,
        reminders=[Reminder(category="reminders/stretch", minutes=30, during="focus")],
    )


def build_pomodoro(app: StumbleRadio) -> None:
    timer = app.pomodoro
    timer.profiles[deep_profile().id] = deep_profile()
    rule = Schedule(
        name="Weekday mornings", time="09:00", weekdays=[0, 1, 2, 3, 4],
        action="start", target="classic",
    )
    timer.schedules.append(rule)


async def start_session(app: StumbleRadio, remaining: int = 24 * 60 + 57):
    now, wall = time.monotonic(), datetime.now().astimezone()
    app.pomodoro.start("classic", now, wall)
    app.pomodoro.session["remaining"] = remaining
    app.update_pomodoro_line()


def svg_to_png(svg_path: Path, png_path: Path, width: int) -> None:
    subprocess.run(
        ["inkscape", str(svg_path), "--export-type=png",
         f"--export-filename={png_path}", f"--export-width={width}"],
        check=True, stdout=subprocess.DEVNULL,
    )


async def clear_toasts(app, pilot) -> None:
    """Drop every notification so older toasts cannot leak into later shots."""
    app._notifications.clear()
    for rack in app.screen.query("ToastRack"):
        for toast in rack.query("Toast"):
            await toast.remove()
    await pilot.pause()


async def shot(app: StumbleRadio, name: str, width: int = EXPORT_WIDTH) -> None:
    svg = app.export_screenshot(title=TITLE)
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"{name}.svg"
    path.write_text(svg)
    svg_to_png(path, IMAGES / f"{name}.png", width)
    print(f"captured {name}.png")


async def main_captures(app, pilot) -> None:
    await prep_context(app)
    by_name = {s.name: s for s in app.stations}

    # --- player.png: main screen, Kameme FM playing, cursor on row 0.
    lately(app, app.stations[0])
    await app.refresh_library()
    tune_cursor(app, "Kameme FM")
    await pilot.pause()
    await shot(app, "player")

    # --- recovery.png: same view plus the dead-stream hand-off toast.
    app.play_state = "WAITING FOR NETWORK"
    app.connection_state = "Network unavailable · checking every 5s"
    app.notify("Stream went silent · trying another frequency", timeout=10)
    await pilot.pause()
    await shot(app, "recovery")
    app.play_state = "PLAYING"
    app.connection_state = ""
    await clear_toasts(app, pilot)

    # --- recording.png: record button engaged with its toast.
    app.play_state = "PLAYING"
    stamp = datetime.now()
    app.notify(f"Recording to /home/demo/Radio/recordings/"
               f"{stamp:%Y%m%d-%H%M%S}-kameme-fm-001df0ba.mka", timeout=10)
    app.query_one("#record", Button).label = "Stop rec"
    await pilot.pause()
    await shot(app, "recording")
    app.query_one("#record", Button).label = "Record"
    await clear_toasts(app, pilot)

    # --- sleep-fading.png: countdown running with fade under way.
    app.sleep_minutes = 30
    app.sleep_until = time.monotonic() + 8 * 60
    app.fade_seconds, app.fade_volume, app.sleep_gain = 30, app.volume_value, 0.8
    app.query_one("#timer", Static).update("Sleep · 08:00 · fading")
    app.update_status()
    await pilot.pause()
    await shot(app, "sleep-fading")
    app.sleep_until = app.sleep_minutes = None
    app.fade_seconds, app.fade_volume, app.sleep_gain = 10, None, 1.0
    app.query_one("#timer", Static).update("Sleep timer · off")

    # --- teleport-spin.png: mid-flight destination header.
    app.update_destination_line("◓ Around the world · Ghana")
    await pilot.pause()
    await shot(app, "teleport-spin")
    app.update_destination_line()

    # --- discovery.png: landed in Japan, Music-only, Jazz Sakura playing,
    #     with Breakfast Shows station sync armed in the sidebar.
    sakura = by_name["Jazz Sakura (asia dream radio)"]
    app.destination, app.destination_landed = "Japan", True
    app.pool = "Music-only"
    app.query_one("#sync-by", Select).value = "breakfast"
    lately(app, sakura)
    app.media_title = "Tatsuro Yamashita — Ride on Time"
    app.track_metadata = {"icy-title": "Tatsuro Yamashita - Ride on Time"}
    app.update_destination_line()
    app.update_discovery_line()
    await app.refresh_library()
    tune_cursor(app, "Jazz Sakura (asia dream radio)")
    await pilot.pause()
    await shot(app, "discovery")
    app.pool = "Anywhere"
    app.query_one("#sync-by", Select).value = ""
    app.set_daypart("")
    app.destination, app.destination_landed = "Earth", False
    app.update_destination_line()
    lately(app, app.stations[0])

    # --- favourites.png / history.png: library views.
    app.mode = "favourites"
    await app.refresh_library()
    tune_cursor(app, "Jazz Sakura (asia dream radio)")
    await pilot.pause()
    await shot(app, "favourites")
    app.mode = "history"
    await app.refresh_library()
    tune_cursor(app, "Kameme FM")
    await pilot.pause()
    await shot(app, "history")

    # --- search.png: worldwide jazz expression, votes sort.
    async def type_query(app, pilot, text: str):

        app.query_one(Input).focus()
        for char in text:
            await pilot.press("space" if char == " " else char)
        await pilot.pause()

    await type_query(app, pilot, "(genre:jazz|genre:tarab) sort:votes")
    await app.refresh_library()
    tune_cursor(app, "Kameme FM")
    await pilot.pause()
    await shot(app, "search")

    # --- search-form.png: the advanced form preloaded with the same query.
    await app.push_screen(SearchScreen(app.filters))
    await pilot.pause()
    await shot(app, "search-form")
    await app.pop_screen()
    await pilot.pause()

    # --- search-error.png: invalid query, previous valid results retained.
    bad = '"happy tunes genre:KE'
    try:
        parse_query(bad)
    except ValueError as error:
        app.query_error = f"{error}  Showing previous valid results."
    app.query_one(Input).value = bad
    app.update_filter_bar()
    await pilot.pause()
    await shot(app, "search-error")
    app.query_error = ""
    app.update_filter_bar()

    # --- quick-tune.png: compact picker over the current page.
    await app.push_screen(StationPicker(list(app.stations)))
    await pilot.pause()
    await shot(app, "quick-tune")
    await app.pop_screen()
    await pilot.pause()

    # --- station-notes.png: notes and personal tags for Kameme FM.
    station = by_name["Kameme FM"]
    details = await asyncio.to_thread(app.db.station_notes, station)
    await app.push_screen(StationNotesScreen(app.db, station, **details))
    await pilot.pause()
    await shot(app, "station-notes")
    await app.pop_screen()
    await pilot.pause()

    # --- equalizer.png: Auto level on, flat bands, gain zero.
    await app.push_screen(EqualizerScreen(app.player.equalizer))
    await pilot.pause()
    await shot(app, "equalizer")
    await app.pop_screen()
    await pilot.pause()

    # --- help.png: the in-app cheat sheet.
    await app.push_screen(HelpScreen())
    await pilot.pause()
    await shot(app, "help")
    await app.pop_screen()
    await pilot.pause()

    # --- sleep.png: the drift-off dialog.
    await app.push_screen(SleepScreen(30, 10))
    await pilot.pause()
    await shot(app, "sleep")
    await app.pop_screen()
    await pilot.pause()

    # --- discovery-settings.png: compass form.
    await app.push_screen(SettingsScreen(app.settings))
    await pilot.pause()
    await shot(app, "discovery-settings")
    await app.pop_screen()
    await pilot.pause()

    # --- journal.png: passport snapshot.
    await app.checkpoint_listening()
    journal = await asyncio.to_thread(app.db.journal)
    await app.push_screen(JournalScreen(journal))
    await pilot.pause()
    await shot(app, "journal")
    await app.pop_screen()
    await pilot.pause()

    # --- last-play.png: search Love.
    last_play = LastPlayScreen(app.db)
    await app.push_screen(last_play)
    words = "Love"
    last_play.query_one(Input).focus()
    for char in words:
        await pilot.press(char)
    for _ in range(20):
        await pilot.pause()
        if last_play.query_one(DataTable).row_count >= 3:
            break
    await pilot.press("down")
    await pilot.pause()
    await shot(app, "last-play")
    await app.pop_screen()
    await pilot.pause()

    # --- podmoro captures.
    app.voice_library = AudioLibrary(VOICE_ROOT)
    build_pomodoro(app)
    await start_session(app)
    pomo = PomodoroScreen()
    await app.push_screen(pomo)
    await pilot.pause()
    app.pomodoro.session["remaining"] = 24 * 60 + 57
    pomo.refresh_status()
    await pilot.pause()
    await shot(app, "podmoro-session")

    tabs = pomo.query_one(TabbedContent)
    tabs.active = "pomo-profiles"
    await pilot.pause()
    pomo.load_profile(next(iter(app.pomodoro.profiles)))
    await pilot.pause()
    await shot(app, "podmoro-profiles")

    tabs.active = "pomo-schedules"
    await pilot.pause()
    rule = app.pomodoro.schedules[0]
    pomo.load_schedule(rule.id)
    await pilot.pause()
    await shot(app, "podmoro-schedules")

    tabs.active = "pomo-clips"
    await pilot.pause()
    for _ in range(10):
        await pilot.pause()
        if pomo.query_one("#pomo-clips-table", object).row_count:
            break
    await pilot.pause()
    await shot(app, "podmoro-sounds")

    # --- podmoro-reminder.png: running session plus a visual reminder.
    tabs.active = "pomo-session"
    await pilot.pause()
    app.pomodoro.session["remaining"] = 24 * 60 + 57
    app.last_announcement = Announcement(
        "reminders/stretch", "Time for a shoulder break.", "reminder",
        app.pomodoro.generation,
    )
    pomo.refresh_status()
    app.update_pomodoro_line()
    await pilot.pause()
    await shot(app, "podmoro-reminder")
    await app.pop_screen()
    await pilot.pause()


async def compact_capture(db: Database) -> None:
    """A tiny terminal: no sidebar, no Quick tune / meter / destination line."""
    app = StumbleRadio(db, DATA_DIR / "recordings", offline=True)
    async with app.run_test(size=(44, 24), notifications=True) as pilot:
        app.volume_value = 80
        app.sync_state = "Demonstration catalogue"
        app.catalogue_count = len(STATIONS)
        lately(app, app.stations[0])
        await app.refresh_library()
        await pilot.pause()
        await shot(app, "compact", width=0)


def seed_voice_library() -> None:
    """A small fake voice-library folder so the clips tab shows real counts."""
    counts = {"focus-start": 2, "break-ending": 1, "reminders/stretch": 1,
              "reminders/water": 1}
    for command in COMMANDS:
        folder = VOICE_ROOT / command
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(counts.get(command, 0)):
            (folder / f"{folder.name}-{i + 1:02d}.mp3").write_bytes(b"ID3 demo")


async def run() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean_demo_data()
    seed_voice_library()
    db = Database(DATA_DIR / "radio.sqlite3")
    stations = [make_station(spec, i) for i, spec in enumerate(STATIONS, 1)]
    by_name = {station.name: station for station in stations}
    seed_database(db, stations, by_name)
    app = StumbleRadio(db, DATA_DIR / "recordings", offline=True)
    async with app.run_test(size=SIZE, notifications=True, tooltips=True) as pilot:
        await main_captures(app, pilot)
    await compact_capture(Database(DATA_DIR / "radio.sqlite3"))
    print("done")


if __name__ == "__main__":
    asyncio.run(run())
