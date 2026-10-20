import asyncio
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from .db import PAGE_SIZE, Database
from .discovery import DiscoverySettings, duration
from .models import SORTS, Search, Station
from .query import (
    format_expression,
    parse_expression,
    parse_query,
    quote_value,
    validate_expression,
)


class StationNotesScreen(ModalScreen[bool | None]):
    BINDINGS: ClassVar = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save notes"),
    ]

    def __init__(self, db: Database, station: Station, notes: str, tags: str):
        super().__init__()
        self.db, self.station = db, station
        self.notes, self.tags = notes, tags
        self.saving = False

    def compose(self) -> ComposeResult:
        with Vertical(id="station-notes-dialog"):
            yield Label("Station notes", classes="dialog-title")
            yield Static(self.station.name, id="notes-station", markup=False)
            yield Static(
                " · ".join(filter(None, (self.station.country, self.station.tags))),
                id="notes-station-details", markup=False,
            )
            yield Label("Notes · moods, shows, DJs, best time to tune in")
            yield TextArea(
                self.notes, id="station-notes-text", soft_wrap=True,
                placeholder="What will help you remember this station?",
            )
            yield Label("Personal tags · comma-separated")
            yield Input(
                self.tags, id="station-notes-tags", max_length=1000,
                placeholder="happy, work, no ads",
            )
            yield Static("", id="station-notes-error", markup=False)
            yield Static(
                "Notes and tags are searchable · Ctrl+S saves · Esc discards edits",
                classes="muted", markup=False,
            )
            with Horizontal(classes="dialog-actions"):
                yield Button("Save notes", variant="primary", id="station-notes-save")
                yield Button(
                    "Save & play", id="station-notes-play", tooltip="Save notes and play this station"
                )
                yield Button("Cancel", id="station-notes-cancel")

    def on_mount(self):
        self.query_one("#station-notes-error", Static).display = False
        self.query_one(TextArea).focus()

    def on_input_changed(self, event: Input.Changed):
        event.stop()

    def on_input_submitted(self, event: Input.Submitted):
        event.stop()

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == "station-notes-cancel":
            self.action_cancel()
        elif event.button.id in {"station-notes-save", "station-notes-play"}:
            await self.save(play=event.button.id == "station-notes-play")

    async def action_save(self):
        await self.save()

    async def save(self, *, play: bool = False):
        if self.saving:
            return
        self.saving = True
        for button in self.query(Button):
            button.disabled = True
        try:
            await asyncio.to_thread(
                self.db.save_station_notes, self.station,
                self.query_one(TextArea).text,
                self.query_one("#station-notes-tags", Input).value,
            )
        except (ValueError, sqlite3.Error, OSError) as error:
            feedback = self.query_one("#station-notes-error", Static)
            feedback.update(
                str(error) if isinstance(error, ValueError)
                else "Could not save notes. Check disk space and permissions, then try again."
            )
            feedback.display = True
        else:
            self.dismiss(play)
        finally:
            self.saving = False
            for button in self.query(Button):
                button.disabled = False

    def action_cancel(self):
        if not self.saving:
            self.dismiss(None)


class SearchScreen(ModalScreen[Search | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, search: Search):
        super().__init__()
        self.search = search

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("FIND YOUR FREQUENCY", classes="dialog-title")
            yield Static(
                "Filters combine • comma-separated genres require all tags", classes="muted"
            )
            with VerticalScroll(id="search-fields"):
                with Grid(id="filter-grid"):
                    yield Label("Text / boolean clause")
                    text = " ".join(
                        filter(
                            None,
                            [
                                format_expression(self.search.expression),
                                *(quote_value(term) for term in self.search.terms),
                            ],
                        )
                    )
                    yield Input(text, placeholder="slow (rock|blues)", id="search-terms")
                    for key, label, hint in [
                        ("name", "Station name", "Name contains…"),
                        ("country", "Country", "Kenya or KE (exact country)"),
                        ("state", "State / region / city", "Nairobi, California…"),
                        ("language", "Language", "Swahili, English…"),
                        ("tags", "Genres / format", "jazz,blues or news or talk"),
                        ("codec", "Codec", "MP3, AAC, OGG…"),
                        ("bitrate_min", "Min bitrate · kbps", "0 = any"),
                        ("bitrate_max", "Max bitrate · kbps", "0 = any"),
                        ("latitude", "Latitude", "Optional, e.g. -1.2921"),
                        ("longitude", "Longitude", "Optional, e.g. 36.8219"),
                        ("radius_km", "Radius · km", "Set all three location fields"),
                    ]:
                        yield Label(label)
                        value = getattr(self.search, key)
                        yield Input(
                            value="" if value is None else str(value), placeholder=hint, id=key
                        )
                    yield Label("Sort by")
                    yield Select(
                        [(v, k) for k, v in SORTS.items()],
                        value=self.search.order,
                        allow_blank=False,
                        id="search-order",
                    )
                yield Checkbox(
                    "Descending (highest / Z first)", self.search.descending, id="descending"
                )
                yield Checkbox(
                    "Hide stations that failed their last check",
                    self.search.hidebroken,
                    id="hidebroken",
                )
                yield Checkbox("HTTPS streams only", self.search.https_only, id="https_only")
            yield Static("", id="search-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("Apply filters", variant="primary", id="apply")
                yield Button("Reset", id="reset")
                yield Button("Cancel", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self) -> None:
        self.apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "reset":
            self.dismiss(Search())
        elif event.button.id == "apply":
            self.apply()

    def apply(self) -> None:
        values = asdict(self.search)
        try:
            text = self.query_one("#search-terms", Input).value
            parse_query(text)
            values["terms"] = ()
            values["expression"] = parse_expression(text)
            if values["expression"]:
                validate_expression(values["expression"])
            for key in ("name", "country", "state", "language", "tags", "codec"):
                values[key] = self.query_one(f"#{key}", Input).value.strip()
            values["tags"] = ",".join(t.strip() for t in values["tags"].split(",") if t.strip())
            for key in ("bitrate_min", "bitrate_max"):
                values[key] = int(self.query_one(f"#{key}", Input).value or "0")
            for key in ("latitude", "longitude", "radius_km"):
                value = self.query_one(f"#{key}", Input).value.strip()
                values[key] = float(value) if value else None
            for key in ("descending", "hidebroken", "https_only"):
                values[key] = self.query_one(f"#{key}", Checkbox).value
            values["order"] = self.query_one("#search-order", Select).value
            search = Search(**values)
        except ValueError as error:
            self.query_one("#search-error", Static).update(str(error))
            return
        self.dismiss(search)


class StationPicker(ModalScreen[Station | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close")]

    def __init__(self, stations: list[Station]):
        super().__init__()
        self.stations = stations
        self.filtered = stations

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Label("QUICK TUNE", classes="dialog-title")
            yield Input(placeholder="Filter this list…  ↓ to choose", id="picker-query")
            yield OptionList(id="picker-options")
            yield Static("Enter to play • Escape to close", classes="muted")

    def on_mount(self) -> None:
        self.update_options("")

    def update_options(self, query: str) -> None:
        self.filtered = [
            s
            for s in self.stations
            if query.casefold() in f"{s.name} {s.country} {s.tags}".casefold()
        ]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Option(Text(f"{s.name}  ·  {s.country}")) for s in self.filtered])

    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_options(event.value)

    def on_input_submitted(self) -> None:
        self.query_one(OptionList).focus()

    def on_key(self, event) -> None:
        if event.key == "down" and self.query_one(Input).has_focus:
            self.query_one(OptionList).focus()
            event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.filtered[event.option_index])

    def action_cancel(self) -> None:
        self.dismiss(None)


class LastPlayScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close")]

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.page_offset = self.total = 0
        self.rows = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="last-play-dialog"):
            yield Label("LAST PLAY SEARCH", classes="dialog-title")
            yield Input(placeholder="Song, artist or station… e.g. Boyz", id="last-play-query")
            yield Static(
                "Past 365 days · newest first · Enter / ↓ to choose a station",
                classes="muted",
            )
            yield DataTable(id="last-play-results", cursor_type="row", zebra_stripes=True)
            yield Static("", id="last-play-status", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("‹ Page", id="last-play-back", disabled=True)
                yield Button("Page ›", id="last-play-next", disabled=True)
                yield Button("Refresh", id="last-play-refresh")
                yield Button("Close", id="last-play-close")

    def on_mount(self):
        self.query_one(DataTable).add_columns(
            "Heard (local)", "Station", "Artist", "Song", "Country"
        )
        self.query_one(Input).focus()
        self.load_results()

    @work(exclusive=True, group="last-play-search")
    async def load_results(self):
        query = self.query_one(Input).value
        offset = self.page_offset
        try:
            rows, total = await asyncio.to_thread(self.db.search_tracks, query, offset)
        except sqlite3.Error:
            self.query_one("#last-play-status", Static).update(
                "Could not read song history. Try Refresh."
            )
            return
        if not self.is_mounted or (query, offset) != (
            self.query_one(Input).value,
            self.page_offset,
        ):
            return
        self.total = total
        self.rows = {str(row["id"]): row for row in rows}
        table = self.query_one(DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                datetime.fromtimestamp(row["played_at"]).astimezone().strftime("%Y-%m-%d %H:%M"),
                Text(row["station_name"][:40]),
                Text(row["artist"][:30] or "—"),
                Text(row["title"][:60]),
                Text(row["country"]),
                key=str(row["id"]),
            )
        status = (
            f"{offset + 1:,}–{offset + len(rows):,} of {total:,} plays · Enter tunes the station live"
            if rows
            else "No matching plays. Songs appear when a station broadcasts track metadata."
        )
        self.query_one("#last-play-status", Static).update(status)
        self.query_one("#last-play-back", Button).disabled = offset == 0
        self.query_one("#last-play-next", Button).disabled = offset + PAGE_SIZE >= total

    def on_input_changed(self, event: Input.Changed):
        event.stop()
        self.page_offset = 0
        self.load_results()

    def on_input_submitted(self, event: Input.Submitted):
        event.stop()
        self.query_one(DataTable).focus()

    def on_key(self, event):
        if event.key == "down" and self.query_one(Input).has_focus:
            self.query_one(DataTable).focus()
            event.stop()
            event.prevent_default()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        event.stop()
        if row := self.rows.get(event.row_key.value):
            self.dismiss(row["stationuuid"])

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected):
        event.stop()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == "last-play-close":
            self.dismiss(None)
        else:
            if event.button.id == "last-play-back":
                self.page_offset = max(0, self.page_offset - PAGE_SIZE)
            elif event.button.id == "last-play-next":
                self.page_offset += PAGE_SIZE
            self.load_results()

    def action_cancel(self):
        self.dismiss(None)


class HelpScreen(ModalScreen):
    AUTO_FOCUS = ""
    BINDINGS: ClassVar = [("escape", "close", "Close"), ("question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("A RADIO FOR CURIOUS EARS", classes="dialog-title")
            yield Static(
                "s         Stumble within your current filters / library\n"
                "t         Teleport to a random country\n"
                "m         Cycle shuffle pool\n"
                "/         Listening journal, stats and radio passport\n"
                "l / Ctrl+L Last Play Search: songs, artists and stations heard\n"
                "Ctrl+F    Advanced search (country, region, genres, geo…)\n"
                "Ctrl+G    Language, location and recovery settings\n"
                "Ctrl+O    Podmoro focus scheduler and voice clips\n"
                "Enter     Play highlighted station\n"
                "Right-click / i Station notes and personal tags\n"
                "e         Equalizer, gain and sound presets\n"
                "Space     Pause / resume\n"
                "n / p     Next / previous station in this result list\n"
                "f         Favourite the playing channel (asks if nothing is playing)\n"
                "Ctrl+B    Quick tune browser for this page\n"
                "+ / -     Volume up / down\n"
                "r         Start / finish a recording\n"
                "Z         Set / cancel sleep countdown and fade\n"
                "U         Upgrade Stumble Radio when a newer release is checked at launch\n"
                "u         Refresh these filters online (Explore only)\n"
                "[ / ]     Previous / next results page\n"
                "Ctrl+Q    Quit (works in text fields too)\n\n"
                "Explore searches your local catalogue immediately.\n"
                "Search: slow genre:rock country:KE\n"
                "OR: country|rock|blues country:kenya\n"
                "AND: country+rock country:kenya\n"
                "Use parentheses to group; quotes keep phrases together.\n"
                "Click a table header to sort; click again to reverse.\n"
                "Unheard excludes every station in your listening history.\n"
                "Stumble recovers from failed, stalled or silent streams.\n"
                "Station Sync stumbles land where the local radio day matches.\n"
                "Space on launch resumes the station you last heard.\n"
                "Fast skips cool a station for 24h; dwell time boosts it.\n"
                "City search matches the directory's state / region field.\n"
                "For precise locations, use coordinates and a radius.\n\n"
                "Plays (24h) are directory clicks, not live listeners.\n"
                "Recording continues during pause and ends on retuning.\n"
                "Recordings use the original audio in a Matroska (.mka) file.\n"
                "The sleep timer stops playback and recording together.",
                markup=False,
            )
            yield Button("Back to the dial", id="close", variant="primary")

    def action_close(self) -> None:
        self.dismiss()

    def on_button_pressed(self) -> None:
        self.dismiss()


class SettingsScreen(ModalScreen[DiscoverySettings | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, settings: DiscoverySettings):
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label("YOUR DISCOVERY COMPASS", classes="dialog-title")
            yield Static(
                "Used by Your language / Nearby. No automatic location lookup.", classes="muted"
            )
            with VerticalScroll():
                for key, label in (
                    ("language", "Your language (e.g. english or swahili)"),
                    ("latitude", "Latitude (optional)"),
                    ("longitude", "Longitude (optional)"),
                    ("radius_km", "Nearby radius · km"),
                    ("recovery_seconds", "Dead / silent stream timeout · seconds (3–120)"),
                ):
                    yield Label(label)
                    value = getattr(self.settings, key)
                    yield Input(value="" if value is None else str(value), id=f"setting-{key}")
            yield Static("", id="settings-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("Save", id="save-settings", variant="primary")
                yield Button("Cancel", id="cancel-settings")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-settings":
            self.dismiss(None)
            return
        try:
            values = {
                key: self.query_one(f"#setting-{key}", Input).value.strip()
                for key in ("language", "latitude", "longitude", "radius_km", "recovery_seconds")
            }
            settings = DiscoverySettings(
                language=values["language"],
                latitude=float(values["latitude"]) if values["latitude"] else None,
                longitude=float(values["longitude"]) if values["longitude"] else None,
                radius_km=float(values["radius_km"]),
                recovery_seconds=int(values["recovery_seconds"]),
            )
        except ValueError as error:
            self.query_one("#settings-error", Static).update(str(error))
            return
        self.dismiss(settings)


class ConfirmScreen(ModalScreen[bool | None]):
    """A yes/no question returned as True (confirmed) or None/False (cancelled)."""

    BINDINGS: ClassVar = [("escape", "no", "Cancel"), ("y", "yes", "Yes")]

    def __init__(self, title: str, body: str, confirm: str = "Yes"):
        super().__init__()
        self.title_text, self.body, self.confirm_label = title, body, confirm

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.title_text, classes="dialog-title")
            yield Static(self.body, markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button(self.confirm_label, variant="primary", id="confirm-yes")
                yield Button("Cancel", id="confirm-no")

    def action_no(self) -> None:
        self.dismiss(False)

    def action_yes(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "confirm-yes")


class SleepScreen(ModalScreen[tuple[float, float] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, minutes: float = 30, fade_seconds: float = 10):
        super().__init__()
        self.minutes, self.fade_seconds = minutes, fade_seconds

    def compose(self) -> ComposeResult:
        with Vertical(id="sleep-dialog"):
            yield Label("DRIFT OFF", classes="dialog-title")
            yield Label("Countdown · minutes (0 cancels)")
            yield Input(str(round(self.minutes, 2)), id="sleep-minutes")
            yield Label("Fade during the last… seconds (0 = stop immediately)")
            yield Input(str(self.fade_seconds), id="sleep-fade")
            yield Static("", id="sleep-error", markup=False)
            with Horizontal(classes="dialog-actions"):
                yield Button("Set timer", id="set-sleep", variant="primary")
                yield Button("Timer off", id="clear-sleep")
                yield Button("Cancel", id="cancel-sleep")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-sleep":
            self.dismiss(None)
        elif event.button.id == "clear-sleep":
            self.dismiss((0, 0))
        else:
            try:
                minutes = float(self.query_one("#sleep-minutes", Input).value)
                fade = float(self.query_one("#sleep-fade", Input).value)
                import math

                if (
                    not all(math.isfinite(v) for v in (minutes, fade))
                    or not 0 <= minutes <= 1440
                    or not 0 <= fade <= 300
                ):
                    raise ValueError("Use 0–1440 minutes and 0–300 fade seconds (finite numbers).")
            except ValueError as error:
                self.query_one("#sleep-error", Static).update(str(error))
                return
            self.dismiss((minutes, min(fade, minutes * 60)))


class JournalScreen(ModalScreen):
    BINDINGS: ClassVar = [("escape", "close", "Close"), ("slash", "close", "Close")]

    def __init__(self, journal: dict):
        super().__init__()
        self.journal = journal

    def compose(self) -> ComposeResult:
        data = self.journal
        with Vertical(id="journal-dialog"):
            yield Label("YOUR RADIO PASSPORT", classes="dialog-title")
            with VerticalScroll():
                yield Static(
                    f"{duration(data['seconds'])} listened · {data['plays']:,} plays · "
                    f"{len(data['passport'])} countries heard\n"
                    f"Country diversity {data['country_diversity']:.1f}/100 · "
                    f"Genre diversity {data['genre_diversity']:.1f}/100",
                    markup=False,
                )
                yield Label("PASSPORT STAMPS", classes="journal-heading")
                yield Static(
                    "\n".join(
                        f"{r['countrycode']}  {r['country']} · {duration(r['seconds'])}"
                        for r in data["passport"]
                    )
                    or "Your first country is waiting.",
                    markup=False,
                )
                yield Label("YOUR TOP STATIONS", classes="journal-heading")
                yield Static(
                    "\n".join(
                        f"{i}. {r['name']} · {duration(r['listened_seconds'])} · {r['plays']} plays"
                        for i, r in enumerate(data["top"], 1)
                    )
                    or "Tune in to start your journal.",
                    markup=False,
                )
                yield Label("RECENT LISTENING", classes="journal-heading")
                yield Static(
                    "\n".join(
                        f"{datetime.fromtimestamp(r['played_at']):%d %b %H:%M}  {r['name']}\n"
                        f"    {r['country']} · {duration(r['listened_seconds'])} · {r['end_reason'] or 'open session'}"
                        for r in data["recent"]
                    )
                    or "No sessions yet.",
                    markup=False,
                )
                yield Static(
                    "Diversity measures how evenly listening time spans categories.\n"
                    "Pauses and buffering do not count. Old history has no measured duration.",
                    classes="muted",
                )
            yield Button("Back to the dial", id="close-journal", variant="primary")

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self):
        self.dismiss()
