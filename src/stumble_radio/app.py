import asyncio
import json
import random
import sqlite3
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.cells import cell_len
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalGroup, Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Input, Select, Static

from .announcements import AnnouncementPlayer, AudioLibrary
from .api import DirectoryError, RadioBrowser, sync_catalogue
from .db import PAGE_SIZE, Database
from .discovery import MAX_RECOVERY_ATTEMPTS, POOL_MODES, DiscoverySettings
from .equalizer import EqualizerSettings
from .equalizer_screen import EqualizerScreen
from .models import SORTS, Search, Station, clean
from .network import NETWORK_POLL_SECONDS, internet_available, retry_delay
from .player import Player, PlayerError
from .pomodoro import PHASES, Announcement, Pomodoro, finite
from .pomodoro_screen import PomodoroScreen
from .query import format_expression, format_query, parse_query
from .screens import (
    ConfirmScreen,
    HelpScreen,
    JournalScreen,
    LastPlayScreen,
    SearchScreen,
    SettingsScreen,
    SleepScreen,
    StationNotesScreen,
    StationPicker,
)
from .tracks import track_from_metadata


def restore_volume(value: str) -> int:
    if not value:
        return 65
    saved = json.loads(value)
    if (not isinstance(saved, dict) or type(saved.get("version")) is not int
            or saved["version"] != 1 or type(saved.get("value")) is not int
            or not 0 <= saved["value"] <= 100):
        raise ValueError("Invalid saved volume")
    return saved["value"]


def listen_label(seconds: float) -> str:
    """Compact listen durations like "45 min", "35 hrs", "5 wks" or "6k hrs"."""
    total, minutes = max(0, int(seconds)), 0
    if total < 3600:
        minutes, _ = divmod(total, 60)
        return f"{minutes or 1} min"
    hours = total // 3600
    if hours < 100:
        return f"{hours} hrs"
    if hours < 1000:
        return f"{max(1, hours // 168)} wks"
    return f"{hours // 1000 or 1}k hrs"


class StationTable(DataTable):
    class Resized(Message):
        pass

    def on_resize(self) -> None:
        self.post_message(self.Resized())

    class NotesRequested(Message):
        def __init__(self, stationuuid: str):
            super().__init__()
            self.stationuuid = stationuuid

    def on_click(self, event: Click):
        if event.button != 3:
            return
        event.prevent_default()
        event.stop()
        row = event.style.meta.get("row", -1)
        if 0 <= row < self.row_count and "column" in event.style.meta:
            self.move_cursor(row=row)
            self.post_message(self.NotesRequested(self.ordered_rows[row].key.value))


class StumbleRadio(App):
    TITLE = "Stumble Radio"
    CSS_PATH = "app.tcss"
    TABLE_COLUMNS: ClassVar = (
        ("favourite", "Now / ★"),
        ("name", "Station"),
        ("listen", "Listen"),
        ("country", "Country"),
        ("tags", "Genre / format"),
        ("bitrate", "kbps"),
        ("votes", "Votes"),
        ("clickcount", "Plays/24h"),
    )
    BINDINGS: ClassVar = [
        Binding("s", "stumble", "Stumble"),
        Binding("t", "teleport", "Teleport"),
        Binding("m", "pool", "Shuffle"),
        Binding("slash", "journal", "Journal"),
        Binding("l", "last_play", "Last Play"),
        Binding("ctrl+l", "last_play", "Last Play", show=False, priority=True),
        Binding("ctrl+f", "search", "Search", show=False),
        Binding("ctrl+g", "settings", "Settings", show=False),
        Binding("ctrl+o", "podmoro", "Podmoro", show=False),
        Binding("space", "pause", "Pause"),
        Binding("n", "next_station", "Next", show=False),
        Binding("p", "previous_station", "Previous", show=False),
        Binding("f", "favourite", "Favourite"),
        Binding("i", "notes", "Notes"),
        Binding("e", "equalizer", "EQ"),
        Binding("r", "record", "Record"),
        Binding("ctrl+b", "picker", "Quick tune", show=False),
        Binding("plus,equals", "volume_up", "Volume +", show=False),
        Binding("minus", "volume_down", "Volume −", show=False),
        Binding("Z,z", "sleep", "Sleep", show=False),
        Binding("u", "online", "Online", show=False),
        Binding("left_square_bracket", "previous_page", "Page back", show=False),
        Binding("right_square_bracket", "next_page", "Page forward", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        db: Database,
        recordings: Path,
        *,
        offline: bool = False,
        api: RadioBrowser | None = None,
        player: Player | None = None,
    ):
        super().__init__()
        self.db = db
        self.offline = offline
        self.api = api or RadioBrowser()
        self.player = player or Player(recordings)
        self.filters = Search()
        self.mode = "browse"
        self.stations: list[Station] = []
        self.table_layout_width = 0
        self.total = 0
        self.offset = 0
        self.favourites: set[str] = set()
        self.listen_totals: dict[str, float] = {}
        self.current: Station | None = None
        self.notes_hint_count = 0
        self.play_state = "READY"
        self.media_title = ""
        self.status_line = ""
        self.page_summary = "0–0 of 0"
        self.volume_value = 65
        self.catalogue_count = 0
        self.sync_state = "Offline directory" if offline else "Directory starting…"
        self.sleep_until = None
        self.sleep_minutes = 0
        self.tune_lock = asyncio.Lock()
        self.online_offset = 0
        self.online_filters = None
        self.settings = DiscoverySettings()
        self.pool = "Anywhere"
        self.destination = "Earth"
        self.destination_landed = False
        self.automatic = False
        self.recovering = False
        self.recovery_attempts = 0
        self.failed_ids: set[str] = set()
        self.random_search, self.random_library, self.random_pool = (
            self.filters,
            self.mode,
            self.pool,
        )
        self.tune_started = self.last_progress_at = self.last_audible_at = time.monotonic()
        self.last_position = None
        self.listen_id = None
        self.listen_seconds = 0.0
        self.accounted_at = self.last_checkpoint = time.monotonic()
        self.fade_seconds = 10.0
        self.fade_volume = None
        self.listening_lock = asyncio.Lock()
        self.signal_silent = False
        self.audio_levels: list[float] = []
        self.user_paused = False
        self.query_error = ""
        self.track_metadata = None
        self.last_track_key = None
        self.playback_wanted = False
        self.needs_reconnect = False
        self.has_played = False
        self.connection_state = ""
        self.stream_result = asyncio.Event()
        self.stream_failed = False
        self.tune_generation = 0
        self.pause_target = None
        self.pomodoro = Pomodoro()
        self.voice_library = AudioLibrary(db.path.parent / "pomodoro" / "audio" / "commands")
        self.announcer = AnnouncementPlayer()
        self.announcement_lock = asyncio.Lock()
        self.pomodoro_save_lock = asyncio.Lock()
        self.announcement_muted = False
        self.announcement_preview = False
        self.preview_requested = False
        self.last_announcement = None
        self.sleep_gain = 1.0
        self.last_pomodoro_save = time.monotonic()

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            with Vertical(id="masthead-brand"):
                yield Static("STUMBLE ◎ RADIO", id="logo", markup=False)
                yield Static("terminal radio for curious minds", id="tagline", markup=False)
            yield Static("◎ Earth", id="destination-line", markup=False)
        with Horizontal(id="transport"):
            with HorizontalGroup(id="transport-primary"):
                yield Button("Stumble", id="stumble", variant="primary")
                yield Button(
                    "⏮", id="previous", classes="media-control", tooltip="Previous station (p)"
                )
                yield Button("▶", id="pause", classes="media-control", tooltip="Play (Space)")
                yield Button("⏭", id="next", classes="media-control", tooltip="Next station (n)")
                yield Button("Record", id="record")
                yield Button("Search", id="search")
                yield Button(
                    "Quick tune",
                    id="picker",
                    tooltip="Quick tune: pick from this page (Ctrl+B)",
                )
            with HorizontalGroup(id="transport-extra"):
                yield Static("", id="audio-meter", classes="transport-spacer", markup=False)
                yield Button(
                    "PODMORO", id="podmoro", tooltip="Focus scheduler and voice reminders (Ctrl+O)"
                )
        with Horizontal(id="info-line"):
            yield Static("", id="discovery-line", markup=False)
            yield Static("", id="podmoro-line", markup=False)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Select(
                    [
                        ("Explore", "browse"),
                        ("Favourites", "favourites"),
                        ("History", "history"),
                        ("Unheard", "unheard"),
                    ],
                    value="browse",
                    allow_blank=False,
                    id="library",
                )
                yield Static("Select a station to see its details.", id="detail", markup=False)
                yield Static("Sleep timer · off", id="timer")
            with Vertical(id="browser"):
                with Horizontal(id="search-toolbar"):
                    yield Input(
                        placeholder="Search… rock country:kenya · Ctrl+F for all filters",
                        id="quick-search",
                    )
                    yield Button("× Clear", id="clear-filters", disabled=True)
                yield Static("", id="active-filters", markup=False)
                yield Static("", id="query-error", markup=False)
                with Horizontal(id="table-toolbar"):
                    with Vertical(id="station-info"):
                        yield Static("", id="playing-station", markup=False)
                        yield Static("", id="status-line", markup=False)
                    with Horizontal(id="table-actions"):
                        yield Button("‹ Page", id="page-back", tooltip="Previous page ([)")
                        yield Button("Page ›", id="page-next", tooltip="Next page (])")
                        yield Button("Online ↻", id="online")
                        yield Button("Library", id="cycle-library")
                yield StationTable(
                    id="stations", cursor_type="row", zebra_stripes=True,
                )
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one(StationTable).tooltip = "Right-click a station for notes · Enter plays it"
        self.query_one(DataTable).focus()
        self.call_after_refresh(self.update_layout)
        saved_volume = await asyncio.to_thread(self.db.metadata, "volume_v1")
        try:
            self.volume_value = restore_volume(saved_volume)
            self.player.output_volume = self.volume_value
        except (ValueError, TypeError, KeyError):
            self.notify("Saved volume was invalid; using 65%.", severity="warning")
        saved_equalizer = await asyncio.to_thread(self.db.metadata, "equalizer_v1")
        try:
            self.player.equalizer = (
                EqualizerSettings.restore(json.loads(saved_equalizer))
                if saved_equalizer else EqualizerSettings()
            )
        except (ValueError, TypeError, KeyError):
            self.player.equalizer = EqualizerSettings()
            self.notify("Equalizer settings were invalid; using flat sound.", severity="warning")
        saved = await asyncio.to_thread(self.db.metadata, "discovery_settings")
        if saved:
            try:
                self.settings = DiscoverySettings(**json.loads(saved))
            except (ValueError, TypeError):
                self.notify("Discovery settings were invalid; using defaults.", severity="warning")
        self.update_discovery_line()
        await self.refresh_library()
        saved_pomodoro = await asyncio.to_thread(self.db.metadata, "pomodoro_v1")
        if saved_pomodoro:
            try:
                self.pomodoro = Pomodoro.restore(json.loads(saved_pomodoro))
                if self.pomodoro.library:
                    self.voice_library = AudioLibrary(Path(self.pomodoro.library))
            except (ValueError, TypeError, KeyError):
                await asyncio.to_thread(self.db.set_metadata, "pomodoro_recovery", saved_pomodoro)
                self.pomodoro = Pomodoro()
                self.notify(
                    "Podmoro settings were invalid; a recovery copy was kept. Using defaults.",
                    severity="warning",
                )
        self.pomodoro.tick(time.monotonic(), datetime.now().astimezone())
        self.update_pomodoro_line()
        self.set_interval(1, self.tick)
        self.set_interval(0.1, self.sample_audio_meter)
        self.set_interval(0.5, self.update_automatic_level)
        self.set_interval(3600, self.prune_track_history)
        self.consume_player_events()
        if not self.offline:
            self.catalogue_loop()

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 95, "narrow")
        self.set_class(event.size.width < 70, "compact")
        self.set_class(event.size.width < 50, "tiny")
        self.set_class(event.size.height < 28, "short")
        if self.is_mounted:
            self.call_after_refresh(self.update_layout)

    def update_layout(self) -> None:
        browser = self.query_one("#browser")
        self.default_screen.set_class(browser.size.width < 112, "stacked")
        self.query_one("#page-back", Button).label = "‹" if self.size.width < 70 else "‹ Page"
        self.query_one("#page-next", Button).label = "›" if self.size.width < 70 else "Page ›"
        self.update_pinned_station()
        self.update_status()
        self.update_discovery_line()
        self.update_pomodoro_line()
        if self.table_layout_width != self.query_one(DataTable).size.width:
            self.render_station_table(self.selected_station())
        self.call_after_refresh(self.update_status)

    def on_station_table_resized(self) -> None:
        self.call_after_refresh(self.update_layout)

    @work(group="catalogue")
    async def catalogue_loop(self) -> None:
        while True:
            try:
                self.sync_state = "Syncing directory…"
                self.update_status()
                await sync_catalogue(self.api, self.db, self.catalogue_progress)
                self.sync_state = "Directory up to date"
                await self.refresh_library()
                delay = 3600
            except (DirectoryError, sqlite3.Error, OSError) as error:
                self.sync_state = f"Sync paused · {clean(str(error))[:85]} · retry in 5 min"
                delay = 300
            self.update_status()
            await asyncio.sleep(delay)

    async def catalogue_progress(self) -> None:
        self.catalogue_count = await asyncio.to_thread(self.db.count)
        self.update_discovery_line()
        self.update_status()
        if not self.stations:
            await self.refresh_library()

    def update_status(self) -> None:
        if not self.is_running:
            return
        timer = ""
        if self.sleep_until:
            seconds = max(0, int(self.sleep_until - time.monotonic()))
            timer = f" · sleep {seconds // 60:02}:{seconds % 60:02}"
        suffix = f"vol {self.volume_value:.0f}%{timer}"
        level_text = "Auto off"
        settings = self.player.equalizer
        if settings.auto_level and not settings.enabled:
            level_text = "Auto bypassed"
        elif settings.auto_level:
            state = self.player.auto_level_state
            target = f"{settings.target_lufs} LUFS".replace("-", "−")
            correction = f"{self.player.auto_level_correction_db:+.1f} dB".replace("-", "−")
            if self.play_state != "PLAYING":
                text = f"Auto paused · {correction} · {target}"
            elif state == "active" or state == "limited":
                if state == "limited":
                    text = f"Auto limited · {correction} · {target}"
                else:
                    text = f"Auto {correction} · {target}"
            else:
                labels = {"measuring": "measuring", "waiting": "waiting for signal", "unavailable": "unavailable", "off": "measuring"}
                if state == "unavailable":
                    text = f"Auto unavailable · {target}"
                else:
                    text = f"Auto {labels.get(state, state)} · {correction} · {target}"
            level_text = text
        self.status_line = f"{suffix} · {level_text}  {self.page_summary}"
        status = self.query_one("#status-line", Static)
        status.tooltip = self.status_line
        text = self.status_line
        if cell_len(text) > status.size.width:
            short_level = level_text.rsplit(" · ", 1)[0] if level_text.endswith("LUFS") else level_text
            text = f"{suffix} · {short_level}  {self.page_summary}"
            if cell_len(text) > status.size.width:
                text = f"{suffix} · {short_level}  {self.page_summary.split(' of ')[0]}"
        status.update(text)

    async def update_automatic_level(self) -> None:
        if self.play_state == "PLAYING":
            await self.player.update_auto_level()
            self.update_status()

    def update_discovery_line(self):
        text = f"{self.catalogue_count:,} stations cached | Shuffle · {self.pool}"
        discovery = self.query_one("#discovery-line", Static)
        discovery.tooltip = text
        discovery.update(f"Shuffle · {self.pool}" if self.size.width < 70 else text)

    def update_destination_line(self, flight: str = ""):
        if flight:
            text = flight
        elif self.destination_landed:
            text = f"◎ LANDED · {self.destination}"
        else:
            text = f"◎ {self.destination}"
        destination = self.query_one("#destination-line", Static)
        destination.update(text)
        destination.tooltip = text

    def update_filter_bar(self):
        search = self.filters
        labels = []
        if search.expression:
            labels.append("Match: " + format_expression(search.expression))
        for key, label in (
            ("country", "Country"),
            ("state", "Region"),
            ("language", "Language"),
            ("tags", "Genres"),
            ("codec", "Codec"),
        ):
            if value := getattr(search, key):
                labels.append(f"{label}: {value}")
        if search.bitrate_min or search.bitrate_max:
            labels.append(f"Bitrate: {search.bitrate_min or 0}–{search.bitrate_max or 'any'} kbps")
        if search.latitude is not None:
            labels.append(
                f"Near: {search.latitude:g}, {search.longitude:g} · {search.radius_km:g} km"
            )
        if search.https_only:
            labels.append("HTTPS only")
        if not search.hidebroken:
            labels.append("Include failed checks")
        if search.order != self.default_filters().order or not search.descending:
            labels.append(f"Sort: {SORTS[search.order]} {'↓' if search.descending else '↑'}")
        summary = self.query_one("#active-filters", Static)
        summary.update("Filters · " + "  ·  ".join(labels))
        summary.tooltip = "Filters · " + "  ·  ".join(labels)
        summary.display = bool(labels)
        self.query_one("#clear-filters", Button).disabled = (
            search == self.default_filters() and not self.query_one("#quick-search", Input).value
        )
        error = self.query_one("#query-error", Static)
        error.update(self.query_error)
        error.display = bool(self.query_error)

    def default_filters(self):
        return Search(
            order=(
                "recent" if self.mode == "history"
                else "listen" if self.mode == "favourites"
                else "clickcount"
            )
        )

    def action_clear_filters(self):
        self.filters, self.offset = self.default_filters(), 0
        self.online_filters, self.online_offset = None, 0
        self.query_error = ""
        self.query_one("#quick-search", Input).value = ""
        self.update_filter_bar()
        self.load_library()

    def account_listening(self):
        now = time.monotonic()
        if (
            self.listen_id is not None
            and self.play_state == "PLAYING"
            and not self.signal_silent
            and not self.announcement_muted
        ):
            self.listen_seconds += max(0, now - self.accounted_at)
        self.accounted_at = now

    async def checkpoint_listening(self, reason: str = ""):
        async with self.listening_lock:
            self.account_listening()
            history_id, seconds = self.listen_id, self.listen_seconds
            if reason:
                self.listen_id = None
            if history_id is not None:
                await asyncio.to_thread(self.db.save_listening, history_id, seconds, reason)
            self.last_checkpoint = time.monotonic()

    def manual_tune(self, station: Station):
        self.playback_wanted = False
        self.automatic = self.recovering = False
        self.workers.cancel_group(self, "discovery")
        self.workers.cancel_group(self, "recovery")
        self.tune(station)

    @work(exclusive=True, group="library")
    async def load_library(self) -> None:
        await self.refresh_library()

    async def refresh_library(self) -> None:
        self.update_filter_bar()
        filters, mode, offset = self.filters, self.mode, self.offset
        stations, total = await asyncio.to_thread(self.db.search, filters, mode, offset)
        favourites = await asyncio.to_thread(self.db.favourite_ids)
        count = await asyncio.to_thread(self.db.count)
        if (filters, mode, offset) != (self.filters, self.mode, self.offset):
            return
        if not stations and total and offset:
            self.offset = max(0, ((total - 1) // PAGE_SIZE) * PAGE_SIZE)
            self.load_library()
            return
        old_station = self.selected_station()
        self.stations, self.total, self.favourites = stations, total, favourites
        self.catalogue_count = count
        if mode == "favourites":
            self.listen_totals = await asyncio.to_thread(self.db.listen_totals, stations)
        else:
            self.listen_totals = {}
        self.update_discovery_line()
        self.render_station_table(old_station)
        start, end = (offset + 1 if total else 0), min(offset + PAGE_SIZE, total)
        self.page_summary = f"{start:,}–{end:,} of {total:,}"
        if not total:
            self.page_summary += " · No matches"
        self.query_one("#page-back", Button).disabled = not offset
        self.query_one("#page-next", Button).disabled = offset + PAGE_SIZE >= total
        self.query_one("#online", Button).disabled = (
            self.offline or mode != "browse" or bool(self.query_error)
        )
        self.update_details()
        self.update_status()

    def render_station_table(self, selected: Station | None = None) -> None:
        table = self.query_one(DataTable)
        self.table_layout_width = table.size.width
        scroll = table.scroll_offset
        available = max(20, table.size.width - 1)
        widths = {"favourite": 3, "name": 0, "bitrate": 5}
        if self.mode == "favourites":
            widths["listen"] = 11
        for key, threshold, width in (
            ("country", 56, 18), ("tags", 86, 24),
            ("votes", 110, 7), ("clickcount", 128, 9),
        ):
            if available >= threshold:
                widths[key] = width
        widths["name"] = max(8, available - sum(widths.values()) - 2 * len(widths))
        rebuild_columns = [(c.key.value, c.width) for c in table.ordered_columns] != [
            (key, widths[key]) for key, _ in self.TABLE_COLUMNS if key in widths
        ]
        table.clear(columns=rebuild_columns)
        for key, label in self.TABLE_COLUMNS:
            if key not in widths:
                continue
            if key == "favourite":
                label = "▶/★"
            arrow = (
                ("↓" if self.filters.descending else "↑") if key == self.filters.order else ""
            )
            title = Text(f"{'★' if key == 'favourite' and arrow else label}{arrow}")
            if rebuild_columns:
                table.add_column(title, key=key, width=widths[key])
            else:
                table.columns[key].label = title
        for station in self.stations:
            playing = self.is_playing_station(station)
            favourite = station.stationuuid in self.favourites
            marker = Text("▶" if playing else "★" if favourite else "·")
            if playing:
                marker.stylize("bold #68ddc4")
            if playing and favourite:
                marker.append(" ★", style="bold #eebc78")
            seconds = self.listen_totals.get(station.url or station.stationuuid, 0)
            if (
                playing and self.listen_id is not None
                and self.play_state == "PLAYING" and not self.signal_silent
            ):
                seconds += max(0, time.monotonic() - self.accounted_at)
            badge = Text(
                f"[♪ {listen_label(seconds)}]" if favourite and seconds > 0 else "",
                style="bold #eebc78", no_wrap=True,
            )
            values = {
                "favourite": marker, "name": station.name, "listen": badge,
                "country": station.country,
                "tags": station.tags, "bitrate": str(station.bitrate or "—"),
                "votes": str(station.votes), "clickcount": str(station.clickcount),
            }
            table.add_row(*(
                value if isinstance(value := values[key], Text)
                else Text(value, no_wrap=True, overflow="ellipsis")
                for key, _ in self.TABLE_COLUMNS if key in widths
            ), key=station.stationuuid)
        scroll_y = 0
        if selected:
            for index, station in enumerate(self.stations):
                if station.stationuuid == selected.stationuuid or (
                    selected.url and station.url == selected.url
                ):
                    table.move_cursor(row=index, scroll=False)
                    scroll_y = scroll.y
                    break
        self.call_after_refresh(table.scroll_to, x=0, y=scroll_y, animate=False, force=True)

    def is_playing_station(self, station: Station) -> bool:
        return bool(
            self.current
            and (
                station.stationuuid == self.current.stationuuid
                or (self.current.url and station.url == self.current.url)
            )
        )

    def selected_station(self) -> Station | None:
        table = self.query_one(DataTable)
        if table.row_count and table.cursor_row < len(self.stations):
            return self.stations[table.cursor_row]
        return None

    def playing_channel(self) -> Station | None:
        """The channel the user has actually heard, or None if nothing is playing."""
        if self.current and (self.has_played or self.user_paused):
            return self.current
        return None

    def update_details(self) -> None:
        if station := self.selected_station():
            label = "▶ Now playing · " if self.is_playing_station(station) else ""
            self.query_one("#detail", Static).update(
                f"{station.name}\n\n{station.country or 'Unknown country'}\n"
                f"{station.state}\n\n{station.tags or 'Uncategorised'}\n\n"
                f"{station.language or 'Language unspecified'}\n"
                f"{station.codec} · {station.bitrate or '?'} kbps\n\n"
                f"{station.votes:,} votes\n{station.clickcount:,} plays (24h)\n\n"
                f"{label}{'★ Favourite' if station.stationuuid in self.favourites else 'f · Add to favourites'}"
            )
        else:
            self.query_one("#detail", Static).update(
                "Your next favourite is out there.\n\nPress s to stumble or / to explore."
            )

    def update_pinned_station(self) -> None:
        pinned = self.query_one("#playing-station", Static)
        if self.current:
            country = f" · {self.current.country}" if self.current.country else ""
            text = f"▶ NOW PLAYING · {self.current.name}{country}"
            pinned.tooltip = text
            if self.size.width < 70:
                text = f"▶ {self.current.name}"
            pinned.update(text)
            pinned.display = True
        else:
            pinned.update("")
            pinned.display = False

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.is_running and event.data_table.id == "stations":
            self.update_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "stations" and (station := self.selected_station()):
            self.manual_tune(station)

    def on_station_table_notes_requested(self, event: StationTable.NotesRequested):
        station = next((s for s in self.stations if s.stationuuid == event.stationuuid), None)
        if station:
            self.open_station_notes(station)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table.id != "stations":
            return
        if self.query_error:
            self.notify("Fix the search query or clear it first.", severity="warning")
            return
        key = event.column_key.value
        if key not in SORTS:
            return
        descending = (
            not self.filters.descending
            if self.filters.order == key
            else key not in {"name", "country", "tags"}
        )
        self.filters = replace(self.filters, order=key, descending=descending)
        self.offset = 0
        self.query_one("#quick-search", Input).value = format_query(self.filters)
        self.load_library()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "quick-search":
            try:
                search = parse_query(event.value) if event.value.strip() else self.default_filters()
            except ValueError as error:
                self.query_error = f"{error}  Showing previous valid results."
                self.query_one("#online", Button).disabled = True
                self.update_filter_bar()
                return
            self.query_error = ""
            self.filters = search
            self.offset = 0
            self.load_library()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "quick-search" and not self.query_error:
            self.query_one(DataTable).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "library" and isinstance(event.value, str):
            self.set_library(event.value)

    def set_library(self, mode: str) -> None:
        self.mode, self.offset = mode, 0
        # A saved library should always open with its complete station list.
        self.filters = self.default_filters()
        self.query_error = ""
        self.query_one("#quick-search", Input).value = ""
        self.load_library()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "stumble": self.action_stumble,
            "pause": self.action_pause,
            "previous": self.action_previous_station,
            "next": self.action_next_station,
            "record": self.action_record,
            "search": self.action_search,
            "podmoro": self.action_podmoro,
            "picker": self.action_picker,
            "page-back": self.action_previous_page,
            "page-next": self.action_next_page,
            "online": self.action_online,
            "clear-filters": self.action_clear_filters,
        }
        if event.button.id == "cycle-library":
            modes = ["browse", "favourites", "history", "unheard"]
            mode = modes[(modes.index(self.mode) + 1) % len(modes)]
            self.query_one("#library", Select).value = mode
        elif action := actions.get(event.button.id):
            action()

    def action_search(self) -> None:
        def apply(search: Search | None):
            if search is not None:
                self.filters, self.offset = search, 0
                self.query_error = ""
                self.query_one("#quick-search", Input).value = format_query(search)
                self.load_library()

        self.push_screen(SearchScreen(self.filters), apply)

    def action_picker(self) -> None:
        def pick(station):
            if station:
                self.manual_tune(station)

        self.push_screen(StationPicker(self.stations), pick)

    def action_notes(self):
        if station := self.selected_station():
            self.open_station_notes(station)

    def action_equalizer(self):
        if not isinstance(self.screen, EqualizerScreen):
            self.push_screen(EqualizerScreen(self.player.equalizer))

    async def save_equalizer(self, settings: EqualizerSettings):
        try:
            await asyncio.to_thread(
                self.db.set_metadata, "equalizer_v1", json.dumps(settings.snapshot(), allow_nan=False)
            )
        except (sqlite3.Error, OSError) as error:
            raise ValueError("Could not save sound settings. Check disk space and permissions, then retry.") from error
        self.notify("Equalizer settings saved.")

    @work(exclusive=True, group="station-notes")
    async def open_station_notes(self, station: Station):
        if isinstance(self.screen, StationNotesScreen):
            return
        try:
            details = await asyncio.to_thread(self.db.station_notes, station)
        except (sqlite3.Error, OSError):
            self.notify("Could not read station notes. Please try again.", severity="warning")
            return

        async def saved(play):
            if play is not None:
                self.notify("Station notes saved.")
                await self.refresh_library()
                if play:
                    self.manual_tune(station)

        self.push_screen(StationNotesScreen(self.db, station, **details), saved)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_podmoro(self):
        if not isinstance(self.screen, PomodoroScreen):
            self.push_screen(PomodoroScreen())

    def pomodoro_summary(self) -> str:
        timer, session = self.pomodoro, self.pomodoro.session
        today = timer.daily.get(
            datetime.now().astimezone().date().isoformat(), {"blocks": 0, "seconds": 0}
        )
        lines = []
        if session:
            seconds = max(0, int(session["remaining"]))
            lines.append(
                f"{session['profile']['name']} · {PHASES[session['phase']]} · {seconds // 60:02}:{seconds % 60:02} · {session['completed']} blocks completed"
                + (" · PAUSED" if session["paused"] else "")
            )
        else:
            lines.append("No active session · choose a profile and Start")
        lines.append(
            f"Today · {today['blocks']} completed blocks · {today['seconds'] / 60:.1f} focus minutes"
        )
        lines.append(
            f"Voice {'quiet' if timer.quiet else 'enabled'} · weekly schedules {'enabled' if timer.calendar_enabled else 'off'}"
        )
        if timer.notice:
            lines.append(timer.notice)
        if self.last_announcement:
            lines.append(self.last_announcement.text)
        return "\n".join(lines)

    def update_pomodoro_line(self):
        session = self.pomodoro.session
        if session:
            seconds = max(0, int(session["remaining"]))
            block = session["completed"] + (1 if session["phase"] == "focus" else 0)
            text = f"PODMORO · {PHASES[session['phase']]} {seconds // 60:02}:{seconds % 60:02} · #{block}"
            if session["paused"]:
                text += " · paused"
        else:
            text = "PODMORO · off"
        if self.pomodoro.quiet:
            text += " · quiet"
        podmoro = self.query_one("#podmoro-line", Static)
        podmoro.update(text)
        podmoro.tooltip = text
        podmoro.display = bool(session or self.pomodoro.quiet or self.size.width >= 95)

    async def persist_pomodoro(self):
        async with self.pomodoro_save_lock:
            snapshot = json.dumps(self.pomodoro.snapshot(), allow_nan=False)
            try:
                await asyncio.to_thread(self.db.set_metadata, "pomodoro_v1", snapshot)
            except (OSError, sqlite3.Error):
                if self.is_running:
                    self.notify(
                        "Could not save Podmoro settings. Check available disk space and database permissions.",
                        severity="warning",
                    )
            self.last_pomodoro_save = time.monotonic()

    async def pomodoro_control(self, action: str, profile_id: str = "classic"):
        now, wall = time.monotonic(), datetime.now().astimezone()
        self.pomodoro.tick(now, wall)
        timer = self.pomodoro
        if action == "start":
            self.dispatch_announcement(timer.start(profile_id, now, wall))
        elif action == "pause":
            if timer.session and timer.session["paused"]:
                timer.resume(now, wall)
            else:
                timer.pause()
                await self.dismiss_voice()
        elif action == "stop":
            timer.stop()
            await self.dismiss_voice()
            self.last_announcement = None
        elif action == "skip":
            if announcement := timer.transition(wall, skipped=True):
                self.dispatch_announcement(announcement)
        elif action == "extend":
            timer.extend()
        elif action == "quiet":
            timer.quiet = not timer.quiet
            if timer.quiet:
                await self.dismiss_voice()
        elif action == "snooze":
            if self.last_announcement:
                timer.snooze(self.last_announcement)
            await self.dismiss_voice()
            self.last_announcement = None
        elif action == "dismiss":
            await self.dismiss_voice()
            self.last_announcement = None
        elif action == "rearm":
            timer.resume(now, wall)
        self.update_pomodoro_line()
        await self.persist_pomodoro()

    async def configure_voice(self, root: str, volume: int):
        if not root.strip():
            raise ValueError("Choose a voice library folder.")
        finite(volume, 0, 100, "Voice volume")
        library = AudioLibrary(Path(root))
        await asyncio.to_thread(library.ensure)
        await self.dismiss_voice()
        self.voice_library = library
        self.pomodoro.library, self.pomodoro.voice_volume = str(library.root), volume

    def dispatch_announcement(self, announcement: Announcement):
        self.preview_requested = False
        self.last_announcement = announcement
        self.update_pomodoro_line()
        self.announce(announcement)

    def preview_voice(self, command: str):
        self.preview_requested = True
        self.announce(Announcement(command, Pomodoro.command_label(command)), preview=True)

    @work(exclusive=True, group="announcements")
    async def announce(self, announcement: Announcement, *, preview: bool = False):
        async with self.announcement_lock:
            if not preview and (
                announcement.generation is not None
                and announcement.generation != self.pomodoro.generation
            ):
                return
            try:
                clip = await asyncio.to_thread(self.voice_library.choose, announcement.category)
                if not clip:
                    if preview:
                        self.notify("No MP3s in this command folder. Add clips and preview again.")
                    return
                caption = await asyncio.to_thread(
                    self.voice_library.caption, clip, announcement.text
                )
                self.last_announcement = replace(announcement, text=caption)
                self.update_pomodoro_line()
                if not preview and (
                    self.pomodoro.quiet
                    or self.user_paused
                    or self.pomodoro.suspended
                    or (self.pomodoro.session and self.pomodoro.session["paused"])
                ):
                    return
                self.account_listening()
                self.announcement_preview = preview
                self.announcement_muted = True
                await self.apply_volume()
                await self.announcer.play(clip, self.pomodoro.voice_volume)
            except (OSError, ValueError, PlayerError) as error:
                self.notify(clean(str(error)), severity="warning", markup=False)
            finally:
                self.account_listening()
                self.announcement_muted = self.announcement_preview = False
                await self.apply_volume()
                if self.is_running:
                    self.save_current_track()

    async def dismiss_voice(self):
        self.preview_requested = False
        self.workers.cancel_group(self, "announcements")
        await self.announcer.stop()
        async with self.announcement_lock:
            self.account_listening()
            self.announcement_muted = self.announcement_preview = False
            await self.apply_volume()

    async def apply_volume(self):
        effective = self.volume_value * self.sleep_gain
        if self.announcement_muted or self.user_paused:
            effective = 0
        try:
            await self.player.set_volume(effective)
        except PlayerError:
            pass

    def action_next_page(self) -> None:
        if self.offset + PAGE_SIZE < self.total:
            self.offset += PAGE_SIZE
            self.load_library()

    def action_previous_page(self) -> None:
        self.offset = max(0, self.offset - PAGE_SIZE)
        self.load_library()

    @work(exclusive=True, group="online")
    async def action_online(self) -> None:
        if self.query_error:
            self.notify("Fix the search query or clear it first.", severity="warning")
            return
        if self.offline or self.mode != "browse":
            self.notify("Online refresh is available in Explore with networking enabled.")
            return
        filters = self.filters
        if self.online_filters != filters:
            self.online_offset, self.online_filters = 0, filters
        try:
            self.notify("Fetching directory matches…")
            rows = await self.api.search(filters, offset=self.online_offset)
            await asyncio.to_thread(self.db.upsert, rows)
            self.online_offset += 100
            if not rows:
                self.online_offset = 0
            await self.refresh_library()
            self.notify(f"Cached {len(rows)} matches. Refresh again for the next batch.")
        except (DirectoryError, sqlite3.Error) as error:
            self.notify(str(error), severity="warning")

    def pool_search(self) -> Search | None:
        if self.pool == "Your language":
            if not self.settings.language:
                self.action_settings()
                self.notify("Set your language, then press s to stumble.")
                return None
            return replace(self.filters, language=self.settings.language)
        if self.pool == "Nearby":
            if self.settings.latitude is None:
                self.action_settings()
                self.notify("Set your coordinates, then press s to stumble nearby.")
                return None
            return replace(
                self.filters,
                latitude=self.settings.latitude,
                longitude=self.settings.longitude,
                radius_km=self.settings.radius_km,
            )
        return self.filters

    def action_pool(self):
        self.pool = POOL_MODES[(POOL_MODES.index(self.pool) + 1) % len(POOL_MODES)]
        self.update_discovery_line()
        self.notify(f"Next stumble pool · {self.pool}")
        if self.pool in {"Your language", "Nearby"}:
            self.pool_search()

    def action_settings(self):
        def apply(settings):
            if settings is not None:
                self.settings = settings
                self.run_worker(
                    asyncio.to_thread(
                        self.db.set_metadata, "discovery_settings", json.dumps(asdict(settings))
                    ),
                    group="settings",
                )
                self.notify("Discovery compass saved.")

        self.push_screen(SettingsScreen(self.settings), apply)

    @work(exclusive=True, group="journal")
    async def action_journal(self):
        await self.checkpoint_listening()
        journal = await asyncio.to_thread(self.db.journal)
        self.push_screen(JournalScreen(journal))

    def action_last_play(self):
        if isinstance(self.screen, LastPlayScreen):
            return

        async def pick(stationuuid):
            if stationuuid and (station := await asyncio.to_thread(self.db.station, stationuuid)):
                self.manual_tune(station)

        self.push_screen(LastPlayScreen(self.db), pick)

    @work(exclusive=True, group="track-retention")
    async def prune_track_history(self):
        try:
            await asyncio.to_thread(self.db.prune_tracks)
        except sqlite3.Error:
            self.notify("Song history cleanup will retry next hour.", severity="warning")

    @work(exclusive=True, group="track-history")
    async def save_current_track(self):
        # Broadcasters often send artist/title in a burst; save the settled update once.
        await asyncio.sleep(0.25)
        station, listen_id = self.current, self.listen_id
        if (
            not station
            or listen_id is None
            or self.play_state != "PLAYING"
            or self.announcement_muted
        ):
            return
        track = track_from_metadata(self.track_metadata, station.name)
        if not track:
            self.last_track_key = None
            return
        key = (listen_id, track.artist.casefold(), track.title.casefold())
        if key == self.last_track_key:
            return
        try:
            await asyncio.to_thread(self.db.add_track, station, track)
        except sqlite3.Error:
            self.notify("Could not save this song to Last Play history.", severity="warning")
            return
        self.last_track_key = key

    @work(exclusive=True, group="discovery")
    async def action_stumble(self) -> None:
        if self.query_error:
            self.notify("Fix the search query or clear it first.", severity="warning")
            return
        search = self.pool_search()
        if search is None:
            return
        try:
            exclude = (self.current.stationuuid,) if self.current else ()
            rows = await asyncio.to_thread(self.db.discover, search, self.mode, self.pool, exclude)
            if not rows and not self.offline and self.mode in {"browse", "unheard"}:
                fetched = await self.api.search(search, limit=100, random_order=True)
                await asyncio.to_thread(self.db.upsert, fetched)
                rows = await asyncio.to_thread(
                    self.db.discover, search, self.mode, self.pool, exclude
                )
            if not rows:
                self.notify(
                    "No eligible station. Broaden filters or change shuffle mode; cold stations stay excluded."
                )
                return
            self.random_search, self.random_library, self.random_pool = search, self.mode, self.pool
            self.tune(rows[0], automatic=True)
        except (DirectoryError, sqlite3.Error) as error:
            self.notify(str(error), severity="warning")

    @work(exclusive=True, group="discovery")
    async def action_teleport(self):
        if self.query_error:
            self.notify("Fix the search query or clear it first.", severity="warning")
            return
        search = replace(
            self.filters,
            name="",
            country="",
            state="",
            latitude=None,
            longitude=None,
            radius_km=None,
        )
        try:
            countries = await asyncio.to_thread(self.db.countries, search)
            if not countries and not self.offline:
                result = await self.api.request("countries", {"limit": 300, "hidebroken": "true"})
                countries = [
                    (r["iso_3166_1"], r["name"])
                    for r in result
                    if isinstance(r, dict) and r.get("iso_3166_1") and r.get("name")
                ]
            if self.current and len(countries) > 1:
                countries = [c for c in countries if c[0] != self.current.countrycode]
            if not countries:
                self.notify("No countries available yet. Let the catalogue sync or try online.")
                return
            code, country = random.choice(countries)
            frames = ("◐", "◓", "◑", "◒")
            for index in range(12):
                flying = countries[index % len(countries)][1]
                self.update_destination_line(
                    f"{frames[index % 4]} Around the world · {flying}"
                )
                await asyncio.sleep(0.07)
            search = replace(search, country=code)
            rows = await asyncio.to_thread(self.db.discover, search)
            if not rows and not self.offline:
                fetched = await self.api.search(search, limit=100, random_order=True)
                await asyncio.to_thread(self.db.upsert, fetched)
                rows = await asyncio.to_thread(self.db.discover, search)
            if not rows:
                self.notify(f"No eligible streams in {country}. Teleport again.", markup=False)
                return
            self.destination = country
            self.destination_landed = True
            self.random_search, self.random_library, self.random_pool = search, "browse", "Anywhere"
            self.tune(rows[0], automatic=True)
        except (DirectoryError, sqlite3.Error) as error:
            self.notify(str(error), severity="warning", markup=False)
        finally:
            self.update_destination_line()
            self.update_discovery_line()

    @work(group="transport")
    async def tune(
        self, station: Station, *, automatic: bool = False, recovery: bool = False
    ) -> None:
        async with self.tune_lock:
            self.workers.cancel_group(self, "recovery")
            self.tune_generation += 1
            self.playback_wanted = False
            await self.checkpoint_listening("dead" if recovery else "skip")
            self.automatic = automatic
            self.recovering = False
            self.playback_wanted = True
            self.needs_reconnect = self.has_played = False
            self.connection_state = ""
            if not recovery:
                self.recovery_attempts = 0
                self.failed_ids.clear()
            if not self.is_playing_station(station):
                self.notes_hint_count += 1
                if self.notes_hint_count > 3:
                    self.query_one(StationTable).tooltip = None
            self.current = station
            self.update_pinned_station()
            self.load_library()
            self.user_paused = False
            try:
                await self.load_stream(station)
                self.update_now_playing()
            except (PlayerError, ValueError, OSError) as error:
                self.play_state = "ERROR"
                if isinstance(error, ValueError) or "Install mpv" in str(error):
                    self.playback_wanted = self.automatic = False
                    self.notify(str(error), severity="error", timeout=6)
                else:
                    self.queue_recovery("Station could not open")
                self.update_now_playing()

    async def load_stream(self, station: Station):
        self.pause_target = None
        self.track_metadata = self.last_track_key = None
        self.workers.cancel_group(self, "track-history")
        self.tune_started = self.last_progress_at = self.last_audible_at = time.monotonic()
        self.last_position = None
        self.signal_silent = False
        self.stream_result.clear()
        self.stream_failed = False
        self.play_state, self.media_title = "TUNING", ""
        self.update_now_playing(station)
        await self.apply_volume()
        await self.player.play(station)
        await self.apply_volume()

    def queue_recovery(self, reason: str):
        self.needs_reconnect = True
        if self.current and self.playback_wanted and not self.user_paused and not self.recovering:
            self.recovering = True
            self.account_listening()
            self.play_state = "RECOVERING"
            self.reconnect(reason, self.current, self.tune_generation)

    @work(exclusive=True, group="recovery")
    async def reconnect(self, reason: str, station: Station, generation: int):
        def active():
            return (
                self.playback_wanted and not self.user_paused and generation == self.tune_generation
            )

        attempt = 0
        saw_outage = False
        try:
            await self.checkpoint_listening("interrupted")
            while active():
                online = await internet_available(station.url)
                if not active():
                    return
                if not online:
                    saw_outage = True
                    self.play_state = "WAITING FOR NETWORK"
                    self.connection_state = "Network unavailable · checking every 5s"
                    self.update_now_playing()
                    self.update_status()
                    await asyncio.sleep(NETWORK_POLL_SECONDS)
                    continue
                if (
                    attempt == 0
                    and not saw_outage
                    and self.automatic
                    and (not self.has_played or reason == "Stream went silent")
                    and reason != "Player disconnected"
                ):
                    await self.recover(reason, station.stationuuid)
                    return
                attempt += 1
                delay = 0 if saw_outage else retry_delay(attempt)
                self.play_state = "RECONNECTING"
                self.connection_state = f"Reconnecting · attempt {attempt} · retry in {delay}s"
                self.update_now_playing()
                self.update_status()
                if delay:
                    await asyncio.sleep(delay)
                if not active():
                    return
                saw_outage = False
                try:
                    async with self.tune_lock:
                        if not active():
                            return
                        await self.checkpoint_listening("interrupted")
                        await self.load_stream(station)
                    await asyncio.wait_for(
                        self.stream_result.wait(), timeout=self.settings.recovery_seconds
                    )
                    if not self.stream_failed:
                        self.connection_state = ""
                        self.needs_reconnect = False
                        return
                except (PlayerError, OSError, TimeoutError):
                    pass
        finally:
            if generation == self.tune_generation:
                self.recovering = False
                self.update_status()

    async def recover(self, reason: str, station_id: str):
        if not self.automatic or not self.current or self.current.stationuuid != station_id:
            self.recovering = False
            return
        await self.checkpoint_listening("dead")
        self.failed_ids.add(station_id)
        await asyncio.to_thread(self.db.mark_dead, self.current)
        self.recovery_attempts += 1
        rows = []
        if self.recovery_attempts <= MAX_RECOVERY_ATTEMPTS:
            rows = await asyncio.to_thread(
                self.db.discover,
                self.random_search,
                self.random_library,
                self.random_pool,
                tuple(self.failed_ids),
            )
            if not rows and not self.offline and self.random_library in {"browse", "unheard"}:
                try:
                    fetched = await self.api.search(
                        self.random_search, limit=100, random_order=True
                    )
                    await asyncio.to_thread(self.db.upsert, fetched)
                    rows = await asyncio.to_thread(
                        self.db.discover,
                        self.random_search,
                        self.random_library,
                        self.random_pool,
                        tuple(self.failed_ids),
                    )
                except DirectoryError:
                    pass
        if rows:
            self.notify(f"{reason} · trying another frequency", markup=False)
            self.tune(rows[0], automatic=True, recovery=True)
        else:
            self.playback_wanted = self.automatic = self.recovering = False
            self.needs_reconnect = False
            try:
                await self.player.stop()
            except PlayerError:
                pass
            self.play_state = "STOPPED"
            self.notify(
                "No working candidates remain in this pool. Try Anywhere or Teleport.",
                severity="warning",
            )
            self.update_now_playing()

    def update_now_playing(self, station: Station | None = None) -> None:
        if not self.is_running:
            return
        pause_button = self.query_one("#pause", Button)
        can_pause = self.current is not None and self.playback_wanted and not self.user_paused
        pause_button.label = "⏸" if can_pause else "▶"
        pause_button.tooltip = "Pause (Space)" if can_pause else "Play (Space)"
        station = station or self.current
        self.query_one("#record", Button).label = (
            "Stop rec" if self.player.record_process else "Record"
        )

    @work(group="player-events")
    async def consume_player_events(self) -> None:
        while True:
            event = await self.player.events.get()
            kind = event.get("event")
            if (
                kind in {"start-file", "file-loaded", "end-file", "property-change"}
                and event.get("stationuuid")
                and self.current
                and event["stationuuid"] != self.current.stationuuid
            ):
                continue
            self.account_listening()
            if kind == "start-file":
                self.track_metadata = self.last_track_key = None
                self.workers.cancel_group(self, "track-history")
            elif kind == "file-loaded":
                if not self.playback_wanted and not self.user_paused:
                    continue
                self.has_played = True
                self.stream_failed = False
                self.stream_result.set()
                self.play_state = "PAUSED" if self.user_paused else "PLAYING"
                async with self.listening_lock:
                    if self.current and self.listen_id is None:
                        self.listen_id = await asyncio.to_thread(self.db.add_history, self.current)
                        self.listen_seconds = 0
                        self.accounted_at = time.monotonic()
                        if not self.offline:
                            self.run_worker(self.api.register_play(self.current), group="clicks")
            elif kind == "property-change":
                name, value = event.get("name"), event.get("data")
                if name == "media-title":
                    self.media_title = clean(value)
                elif name == "metadata":
                    self.track_metadata = value
                elif name == "pause" and self.current:
                    if not self.playback_wanted and (self.needs_reconnect or not self.user_paused):
                        continue
                    if self.pause_target is not None and bool(value) != self.pause_target:
                        continue
                    self.pause_target = None
                    self.user_paused = bool(value)
                    self.playback_wanted = not self.user_paused
                    if self.user_paused:
                        await self.dismiss_voice()
                    await self.apply_volume()
                    if self.play_state in {"PLAYING", "PAUSED", "BUFFERING"}:
                        self.play_state = "PAUSED" if value else "PLAYING"
                    self.last_progress_at = self.last_audible_at = time.monotonic()
                elif name == "paused-for-cache" and self.current and self.play_state != "PAUSED":
                    if value:
                        self.play_state = "BUFFERING"
                    elif self.play_state == "BUFFERING":
                        self.play_state = "PLAYING"
                # Mixer echoes contain temporary mute/fade gains, not the user's setting.
            elif kind == "end-file" and event.get("reason") in {"error", "eof"}:
                self.stream_failed = True
                self.stream_result.set()
                if self.playback_wanted or self.user_paused:
                    self.play_state = "PAUSED" if self.user_paused else "STREAM ENDED"
                    self.queue_recovery("Stream ended")
            elif kind == "disconnected":
                self.stream_failed = True
                self.stream_result.set()
                if self.playback_wanted or self.user_paused:
                    self.play_state = "PAUSED" if self.user_paused else "DISCONNECTED"
                    self.queue_recovery("Player disconnected")
            elif kind == "equalizer-error":
                self.notify("Equalizer bypassed: " + event["error"], severity="warning", markup=False)
            elif kind == "recording-ended":
                if event["code"]:
                    self.notify(
                        "Recording failed: " + (event.get("error") or "stream unavailable")[-250:],
                        severity="error",
                        timeout=8,
                    )
                else:
                    self.notify(f"Recording saved: {event['path']}", timeout=8)
                if self.player.record_process and self.player.record_process.returncode is not None:
                    self.player.record_process = None
                    self.player.record_path = None
                    self.player.record_task = None
            if kind == "file-loaded" or (
                kind == "property-change"
                and event.get("name") in {"metadata", "pause", "paused-for-cache"}
            ):
                self.save_current_track()
            self.update_now_playing()

    @work(group="controls")
    async def action_pause(self) -> None:
        try:
            if self.current and self.needs_reconnect:
                if self.playback_wanted:
                    self.playback_wanted = False
                    self.user_paused = True
                    await self.dismiss_voice()
                    self.workers.cancel_group(self, "recovery")
                    self.workers.cancel_group(self, "transport")
                    self.recovering = False
                    self.connection_state = "Reconnect paused · press Space to resume"
                    self.play_state = "PAUSED"
                    self.update_now_playing()
                    self.update_status()
                    async with self.tune_lock:
                        await self.player.stop()
                else:
                    self.user_paused = False
                    self.playback_wanted = True
                    self.queue_recovery("Resume connection")
                self.update_now_playing()
                self.update_status()
                return
            if self.current and self.play_state not in {
                "STREAM ENDED",
                "ERROR",
                "DISCONNECTED",
                "STOPPED",
            }:
                self.pause_target = not self.user_paused
                self.account_listening()
                self.user_paused = self.pause_target
                self.playback_wanted = not self.user_paused
                self.play_state = "PAUSED" if self.user_paused else "PLAYING"
                self.last_progress_at = self.last_audible_at = time.monotonic()
                if self.user_paused:
                    await self.dismiss_voice()
                await self.player.pause()
                await self.apply_volume()
            elif station := self.selected_station():
                self.manual_tune(station)
        except PlayerError as error:
            self.notify(str(error), severity="warning")
            if self.playback_wanted:
                self.queue_recovery("Player disconnected")
        self.update_now_playing()

    def step_station(self, direction: int) -> None:
        if not self.stations:
            return
        index = self.query_one(DataTable).cursor_row
        if self.current:
            index = next(
                (
                    i
                    for i, s in enumerate(self.stations)
                    if s.stationuuid == self.current.stationuuid
                    or (self.current.url and s.url == self.current.url)
                ),
                index - direction,
            )
        index = (index + direction) % len(self.stations)
        self.query_one(DataTable).move_cursor(row=index)
        self.manual_tune(self.stations[index])

    def action_next_station(self) -> None:
        self.step_station(1)

    def action_previous_station(self) -> None:
        self.step_station(-1)

    @work(group="favourites")
    async def action_favourite(self) -> None:
        # You can only like what you have heard: favourite the playing channel;
        # without playback, ask before acting on the highlighted row.
        station = self.playing_channel()
        if station is None:
            station = self.selected_station()
            if station is None:
                self.notify("No station highlighted.", severity="warning")
                return
            saving = station.stationuuid not in self.favourites
            ask = (
                f"{station.name} is not playing.\n"
                f"{'Save it to favourites anyway?' if saving else 'Remove it from favourites anyway?'}"
            )
            if not await self.push_screen_wait(
                ConfirmScreen(
                    "FAVOURITE", ask, confirm="Save" if saving else "Remove"
                )
            ):
                return
        added = await asyncio.to_thread(self.db.toggle_favourite, station)
        self.notify(f"{'Saved' if added else 'Removed'} · {station.name}")
        self.load_library()

    @work(group="controls")
    async def action_record(self) -> None:
        async with self.tune_lock:
            try:
                if self.player.record_process:
                    await self.player.stop_recording()
                else:
                    path = await self.player.record()
                    self.notify(f"Recording to {path}", timeout=6)
                self.update_now_playing()
            except (PlayerError, ValueError, OSError) as error:
                self.notify(str(error), severity="error")

    @work(group="controls")
    async def change_volume(self, delta: int) -> None:
        self.volume_value = max(0, min(100, self.volume_value + delta))
        await self.apply_volume()
        try:
            await asyncio.to_thread(
                self.db.set_metadata, "volume_v1",
                json.dumps({"version": 1, "value": self.volume_value}),
            )
        except (sqlite3.Error, OSError):
            self.notify("Could not save volume setting.", severity="warning")
        self.update_status()

    def action_volume_up(self) -> None:
        self.change_volume(5)

    def action_volume_down(self) -> None:
        self.change_volume(-5)

    def action_sleep(self) -> None:
        def apply(result):
            if result is not None:
                self.configure_sleep(*result)

        remaining = max(0, (self.sleep_until - time.monotonic()) / 60) if self.sleep_until else 30
        self.push_screen(SleepScreen(remaining, self.fade_seconds), apply)

    @work(group="sleep-settings", exclusive=True)
    async def configure_sleep(self, minutes: float, fade: float = 10):
        await self.restore_volume()
        self.sleep_minutes, self.fade_seconds = minutes, min(fade, minutes * 60)
        self.sleep_until = time.monotonic() + minutes * 60 if minutes else None
        label = f"{minutes:g} min · fade {self.fade_seconds:g}s" if minutes else "off"
        self.query_one("#timer", Static).update(f"Sleep timer · {label}")
        self.notify(f"Sleep timer · {label}")
        self.update_status()

    async def restore_volume(self):
        if self.fade_volume is not None:
            self.fade_volume = None
            self.sleep_gain = 1.0
            await self.apply_volume()

    @work(group="health", exclusive=True)
    async def check_health(self):
        station_id = self.current.stationuuid if self.current else None
        try:
            position, rms = await self.player.health()
        except PlayerError:
            return
        if (
            not self.current
            or self.current.stationuuid != station_id
            or self.play_state != "PLAYING"
        ):
            return
        self.account_listening()
        self.signal_silent = rms is not None and rms <= -50
        now = time.monotonic()
        if self.announcement_muted:
            self.last_audible_at = now
        if position is not None and position != self.last_position:
            self.last_progress_at = now
            if not self.signal_silent:
                self.last_audible_at = now
            self.last_position = position
        # A stable stream earns a fresh recovery budget.
        if now - self.tune_started >= self.settings.recovery_seconds * 2 and not self.signal_silent:
            self.recovery_attempts = 0

    async def tick(self) -> None:
        if not self.is_running:
            return
        self.update_audio_meter()
        self.account_listening()
        now = time.monotonic()
        if now - self.last_checkpoint >= 5:
            await self.checkpoint_listening()
        if not self.is_running:
            return
        if self.sleep_until and time.monotonic() >= self.sleep_until:
            self.sleep_until = None
            self.sleep_minutes = 0
            self.automatic = self.recovering = False
            self.playback_wanted = self.needs_reconnect = self.user_paused = False
            self.connection_state = ""
            self.pomodoro.sleep()
            await self.dismiss_voice()
            await self.persist_pomodoro()
            self.workers.cancel_group(self, "recovery")
            self.workers.cancel_group(self, "discovery")
            self.workers.cancel_group(self, "transport")
            await self.checkpoint_listening("sleep")
            try:
                await self.player.stop()
            except PlayerError as error:
                self.notify(str(error), severity="warning", markup=False)
            self.play_state = "STOPPED"
            await self.restore_volume()
            if not self.is_running:
                return
            self.query_one("#timer", Static).update("Sleep timer · off")
            self.notify("Sleep timer finished. Playback and recording stopped.")
            self.update_now_playing()
        elif self.sleep_until and self.fade_seconds and self.current:
            remaining = self.sleep_until - now
            if remaining <= self.fade_seconds:
                if self.fade_volume is None:
                    self.fade_volume = self.volume_value
                self.sleep_gain = max(0, remaining) / self.fade_seconds
                await self.apply_volume()
        if not self.is_running:
            return
        if self.current and self.playback_wanted and not self.recovering and not self.user_paused:
            timeout = self.settings.recovery_seconds
            if self.play_state == "TUNING" and now - self.tune_started >= timeout:
                self.queue_recovery("Station did not start")
            elif self.play_state in {"PLAYING", "BUFFERING"}:
                if now - self.last_progress_at >= timeout:
                    self.queue_recovery("Stream stalled")
                elif (
                    self.automatic
                    and not self.announcement_muted
                    and now - self.last_audible_at >= timeout
                ):
                    self.queue_recovery("Stream went silent")
                else:
                    self.check_health()
        if self.sleep_until:
            remaining = max(0, int(self.sleep_until - time.monotonic()))
            self.query_one("#timer", Static).update(
                f"Sleep · {remaining // 60:02}:{remaining % 60:02}"
                + (" · fading" if self.fade_volume is not None else "")
            )
        generation = self.pomodoro.generation
        fired = self.pomodoro.fired.copy()
        for announcement in self.pomodoro.tick(time.monotonic(), datetime.now().astimezone()):
            self.dispatch_announcement(announcement)
        if self.pomodoro.interrupted:
            await self.dismiss_voice()
        self.update_pomodoro_line()
        if (
            generation != self.pomodoro.generation
            or fired != self.pomodoro.fired
            or self.pomodoro.interrupted
            or time.monotonic() - self.last_pomodoro_save >= 15
        ):
            await self.persist_pomodoro()
        self.update_status()

    def update_audio_meter(self) -> None:
        if not self.is_running:
            return
        meter = self.query_one("#audio-meter", Static)
        if self.size.width < 95 or not self.current or self.play_state != "PLAYING":
            meter.update("")
            return
        bars = "▁▂▃▄▅▆▇█"
        sample_count = max(0, min(24, meter.size.width - 2))
        graph = (
            "".join(
                bars[min(7, int(level * 8))] for level in self.audio_levels[-sample_count:]
            )
            if sample_count
            else ""
        )
        meter.update("♪ " + graph)

    @work(group="audio-meter", exclusive=True)
    async def sample_audio_meter(self) -> None:
        if self.size.width < 95 or not self.current or self.play_state != "PLAYING":
            self.audio_levels.clear()
            self.update_audio_meter()
            return
        station_id = self.current.stationuuid
        try:
            rms = await self.player.audio_level()
        except PlayerError:
            return
        if (
            rms is None
            or not self.current
            or self.current.stationuuid != station_id
            or self.play_state != "PLAYING"
        ):
            return
        self.audio_levels.append(max(0.0, min(1.0, (rms + 60) / 60)))
        del self.audio_levels[:-24]
        self.update_audio_meter()

    async def on_unmount(self) -> None:
        self.playback_wanted = self.automatic = False
        await self.dismiss_voice()
        self.pomodoro.tick(time.monotonic(), datetime.now().astimezone())
        await self.persist_pomodoro()
        await self.checkpoint_listening("quit")
        await self.player.close()
        await self.api.close()
