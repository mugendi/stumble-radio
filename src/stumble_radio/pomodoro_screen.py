import asyncio
from dataclasses import asdict
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .pomodoro import Profile, Reminder, Schedule, category, new_id

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class PomodoroScreen(ModalScreen):
    BINDINGS: ClassVar = [("escape", "close", "Close")]

    def __init__(self):
        super().__init__()
        self.profile_id = ""
        self.schedule_id = "new"
        self.reminders = []
        self.reminder_id = None

    @property
    def timer(self):
        return self.app.pomodoro

    def profile_options(self):
        return [(Text(p.name), p.id) for p in self.timer.profiles.values()]

    def compose(self) -> ComposeResult:
        with Vertical(id="pomodoro-dialog"):
            yield Label("PODMORO", classes="dialog-title")
            with TabbedContent(initial="pomo-session"):
                with TabPane("Session", id="pomo-session"), VerticalScroll():
                    yield Static("", id="pomo-live", markup=False)
                    yield Label("Start a profile")
                    yield Select(
                        self.profile_options(),
                        value=next(iter(self.timer.profiles)),
                        allow_blank=False,
                        id="pomo-run-profile",
                    )
                    with Grid(classes="pomo-actions", id="pomo-session-actions"):
                        for label, key in [
                            ("Start", "start"),
                            ("Pause", "pause"),
                            ("Stop", "stop"),
                            ("Skip phase", "skip"),
                            ("+5 minutes", "extend"),
                            ("Quiet: off", "quiet"),
                            ("Snooze 5m", "snooze"),
                            ("Dismiss", "dismiss"),
                            ("Rearm", "rearm"),
                        ]:
                            yield Button(
                                label,
                                id=f"pomo-{key}",
                                variant="primary" if key == "start" else "default",
                            )
                    yield Static(
                        "Music continues through breaks. Pausing radio silences scheduled voices; the timer keeps running.",
                        id="pomo-session-hint",
                        classes="muted",
                    )
                with TabPane("Profiles", id="pomo-profiles"), VerticalScroll():
                    yield Select(
                        self.profile_options(),
                        value=next(iter(self.timer.profiles)),
                        allow_blank=False,
                        id="pomo-profile",
                    )
                    with Grid(classes="pomo-actions"):
                        yield Button("New", id="pomo-profile-new")
                        yield Button("Duplicate", id="pomo-profile-copy")
                        yield Button("Delete", id="pomo-profile-delete")
                    with Grid(classes="pomo-fields"):
                        for key, label in [
                            ("name", "Profile name"),
                            ("focus", "Focus · minutes"),
                            ("short_break", "Short break · minutes"),
                            ("long_break", "Long break · minutes"),
                            ("long_every", "Long break every… blocks"),
                            ("limit", "Block limit · 0 repeats"),
                            ("focus_warning", "Focus warning · seconds"),
                            ("break_warning", "Break warning · seconds"),
                        ]:
                            yield Label(label)
                            yield Input(id=f"pomo-profile-{key}")
                    yield Label("Recurring reminders", classes="pomo-section")
                    yield DataTable(id="pomo-reminders", cursor_type="row", zebra_stripes=True)
                    with Grid(classes="pomo-fields"):
                        yield Label("Command folder")
                        yield Input("reminders/stretch", id="pomo-reminder-category")
                        yield Label("Every… eligible minutes")
                        yield Input("30", id="pomo-reminder-minutes")
                        yield Label("During")
                        yield Select(
                            [("Focus", "focus"), ("Breaks", "break"), ("Either", "any")],
                            value="focus",
                            allow_blank=False,
                            id="pomo-reminder-during",
                        )
                    yield Checkbox("Reminder enabled", True, id="pomo-reminder-enabled")
                    with Grid(classes="pomo-actions"):
                        yield Button("Add / update", id="pomo-reminder-save")
                        yield Button("New reminder", id="pomo-reminder-new")
                        yield Button("Remove", id="pomo-reminder-delete")
                    yield Button("Save profile", variant="primary", id="pomo-profile-save")
                    yield Static(
                        "Changes apply to the next session. The running session keeps its current settings.",
                        classes="muted",
                    )
                with TabPane("Schedules", id="pomo-schedules"), VerticalScroll():
                    yield Checkbox(
                        "Enable weekly scheduling while this app is open",
                        self.timer.calendar_enabled,
                        id="pomo-calendar",
                    )
                    yield Select(
                        self.schedule_options(), value="new", allow_blank=False, id="pomo-schedule"
                    )
                    with Grid(classes="pomo-fields"):
                        yield Label("Schedule name")
                        yield Input(id="pomo-schedule-name", placeholder="Weekday focus")
                        yield Label("Local time · 24-hour")
                        yield Input("09:00", id="pomo-schedule-time")
                        yield Label("Weekdays")
                        yield Input("Mon,Tue,Wed,Thu,Fri", id="pomo-schedule-days")
                        yield Label("Action")
                        yield Select(
                            [("Start profile", "start"), ("Speak reminder", "command")],
                            value="start",
                            allow_blank=False,
                            id="pomo-schedule-action",
                        )
                        yield Label("Profile", id="pomo-schedule-profile-label")
                        yield Select(
                            self.profile_options(),
                            value=next(iter(self.timer.profiles)),
                            allow_blank=False,
                            id="pomo-schedule-profile",
                        )
                        yield Label("Command folder", id="pomo-schedule-command-label")
                        yield Input("reminders/water", id="pomo-schedule-command")
                    yield Checkbox("Schedule enabled", True, id="pomo-schedule-enabled")
                    with Grid(classes="pomo-actions"):
                        yield Button("Save schedule", variant="primary", id="pomo-schedule-save")
                        yield Button("New schedule", id="pomo-schedule-new")
                        yield Button("Delete", id="pomo-schedule-delete")
                    yield Static(
                        "Local timezone · missed starts are skipped · an active or paused session is never replaced.",
                        classes="muted",
                    )
                with TabPane("Voice clips", id="pomo-clips"), VerticalScroll():
                    yield Label("Voice library folder")
                    yield Input(str(self.app.voice_library.root), id="pomo-audio-root")
                    yield Label("Voice volume · 0–100")
                    yield Input(str(self.timer.voice_volume), id="pomo-voice-volume")
                    yield Button("Save audio settings", variant="primary", id="pomo-audio-save")
                    yield Static(
                        "MP3 or WAV clips in command folders; a matching .txt file supplies"
                        " the caption. Empty folders are generated from the announcer voice"
                        " (Palette > Voices); deleting clips and restarting remakes them."
                        " All announcements cap at 120 seconds.",
                        classes="muted",
                    )
                    yield DataTable(id="pomo-clips-table", cursor_type="row", zebra_stripes=True)
                    with Grid(classes="pomo-actions"):
                        yield Button(
                            "Preview clip",
                            id="pomo-preview",
                            tooltip="An explicit preview plays even when Quiet or radio pause is on",
                        )
                        yield Button("Rescan folders", id="pomo-rescan")
                        yield Button("Stop preview", id="pomo-preview-stop")
                    yield Label("Create a custom command folder")
                    yield Input(placeholder="reminders/my-stretch", id="pomo-new-category")
                    yield Button("Create folder", id="pomo-category-create")
            yield Static("", id="pomo-feedback", markup=False)
            yield Button("Close", id="pomo-close")

    def schedule_options(self):
        return [
            ("New schedule…", "new"),
            *[(Text(f"{s.name} · {s.time}"), s.id) for s in self.timer.schedules],
        ]

    async def on_mount(self):
        self.set_class(self.app.size.width < 95, "narrow")
        self.query_one("#pomo-reminders", DataTable).add_columns(
            "Command", "Minutes", "During", "On"
        )
        self.query_one("#pomo-clips-table", DataTable).add_columns("Command folder", "Clips")
        self.load_profile(next(iter(self.timer.profiles)))
        self.schedule_fields()
        try:
            await self.rescan()
        except OSError as error:
            self.feedback(
                f"Cannot read the voice library: {error}. Choose a writable folder in Voice clips."
            )
        self.refresh_status()
        self.set_interval(1, self.refresh_status)

    def on_resize(self, event):
        self.set_class(event.size.width < 95, "narrow")

    def feedback(self, message):
        self.query_one("#pomo-feedback", Static).update(message)

    def refresh_status(self):
        session = self.timer.session
        self.query_one("#pomo-live", Static).update(self.app.pomodoro_summary())
        self.query_one("#pomo-start", Button).disabled = session is not None
        for key in ("pause", "stop", "skip", "extend"):
            self.query_one(f"#pomo-{key}", Button).disabled = session is None
        self.query_one("#pomo-pause", Button).label = (
            "Resume" if session and session["paused"] else "Pause"
        )
        self.query_one("#pomo-quiet", Button).label = (
            "Quiet: on" if self.timer.quiet else "Quiet: off"
        )
        self.query_one("#pomo-snooze", Button).disabled = not (
            self.app.last_announcement and self.app.last_announcement.kind == "reminder"
        )
        self.query_one("#pomo-rearm", Button).disabled = not self.timer.suspended
        self.query_one("#pomo-rearm", Button).display = self.timer.suspended

    def load_profile(self, profile_id):
        if profile_id not in self.timer.profiles:
            return
        self.profile_id = profile_id
        profile = self.timer.profiles[profile_id]
        for key in (
            "name",
            "focus",
            "short_break",
            "long_break",
            "long_every",
            "limit",
            "focus_warning",
            "break_warning",
        ):
            self.query_one(f"#pomo-profile-{key}", Input).value = str(getattr(profile, key))
        self.reminders = [Reminder(**asdict(r)) for r in profile.reminders]
        self.reminder_id = None
        self.render_reminders()

    def render_reminders(self):
        table = self.query_one("#pomo-reminders", DataTable)
        table.clear()
        for reminder in self.reminders:
            table.add_row(
                reminder.category,
                f"{reminder.minutes:g}",
                reminder.during,
                "yes" if reminder.enabled else "no",
                key=reminder.id,
            )

    def save_profile(self):
        values = {
            key: self.query_one(f"#pomo-profile-{key}", Input).value
            for key in (
                "name",
                "focus",
                "short_break",
                "long_break",
                "long_every",
                "limit",
                "focus_warning",
                "break_warning",
            )
        }
        for key in values.keys() - {"name"}:
            values[key] = int(values[key]) if key in {"long_every", "limit"} else float(values[key])
        profile = Profile(id=self.profile_id, reminders=self.reminders, **values)
        if any(
            p.id != profile.id and p.name.casefold() == profile.name.casefold()
            for p in self.timer.profiles.values()
        ):
            raise ValueError("Choose a different profile name.")
        self.timer.profiles[profile.id] = profile
        self.refresh_profiles(profile.id)
        self.feedback("Profile saved · changes apply to the next session")

    def refresh_profiles(self, selected):
        for key in ("pomo-profile", "pomo-run-profile", "pomo-schedule-profile"):
            select = self.query_one(f"#{key}", Select)
            old = select.value
            select.set_options(self.profile_options())
            select.value = (
                selected if key == "pomo-profile" or old not in self.timer.profiles else old
            )

    def schedule_fields(self):
        command = self.query_one("#pomo-schedule-action", Select).value == "command"
        for key in ("command", "command-label"):
            self.query_one(f"#pomo-schedule-{key}").display = command
        for key in ("profile", "profile-label"):
            self.query_one(f"#pomo-schedule-{key}").display = not command

    def load_schedule(self, schedule_id):
        self.schedule_id = schedule_id
        rule = next((s for s in self.timer.schedules if s.id == schedule_id), None)
        self.query_one("#pomo-schedule-name", Input).value = rule.name if rule else ""
        self.query_one("#pomo-schedule-time", Input).value = rule.time if rule else "09:00"
        self.query_one("#pomo-schedule-days", Input).value = (
            ",".join(DAY_NAMES[d] for d in rule.weekdays) if rule else "Mon,Tue,Wed,Thu,Fri"
        )
        self.query_one("#pomo-schedule-action", Select).value = rule.action if rule else "start"
        self.query_one("#pomo-schedule-enabled", Checkbox).value = rule.enabled if rule else True
        if rule and rule.action == "start" and rule.target in self.timer.profiles:
            self.query_one("#pomo-schedule-profile", Select).value = rule.target
        if rule and rule.action == "command":
            self.query_one("#pomo-schedule-command", Input).value = rule.target
        self.schedule_fields()

    async def rescan(self):
        library = self.app.voice_library

        def scan():
            library.ensure()
            return [(name, len(library.clips(name))) for name in library.categories()]

        rows = await asyncio.to_thread(scan)
        table = self.query_one("#pomo-clips-table", DataTable)
        table.clear()
        for name, count in rows:
            table.add_row(name, str(count), key=name)

    def on_select_changed(self, event: Select.Changed):
        event.stop()
        if not isinstance(event.value, str):
            return
        if event.select.id == "pomo-profile":
            self.load_profile(event.value)
        elif event.select.id == "pomo-schedule":
            self.load_schedule(event.value)
        elif event.select.id == "pomo-schedule-action":
            self.schedule_fields()

    def on_data_table_header_selected(self, event):
        event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        event.stop()
        if event.data_table.id == "pomo-reminders":
            reminder = next(r for r in self.reminders if r.id == event.row_key.value)
            self.reminder_id = reminder.id
            self.query_one("#pomo-reminder-category", Input).value = reminder.category
            self.query_one("#pomo-reminder-minutes", Input).value = str(reminder.minutes)
            self.query_one("#pomo-reminder-during", Select).value = reminder.during
            self.query_one("#pomo-reminder-enabled", Checkbox).value = reminder.enabled

    async def on_checkbox_changed(self, event: Checkbox.Changed):
        event.stop()
        if event.checkbox.id == "pomo-calendar":
            self.timer.calendar_enabled = event.value
            await self.app.persist_pomodoro()

    async def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        key = event.button.id
        try:
            if key == "pomo-close":
                self.action_close()
                return
            if key in {
                f"pomo-{name}"
                for name in (
                    "start",
                    "pause",
                    "stop",
                    "skip",
                    "extend",
                    "quiet",
                    "snooze",
                    "dismiss",
                    "rearm",
                )
            }:
                await self.app.pomodoro_control(
                    key[5:], self.query_one("#pomo-run-profile", Select).value
                )
            elif key in {"pomo-profile-new", "pomo-profile-copy"}:
                values = (
                    asdict(self.timer.profiles[self.profile_id])
                    if key.endswith("copy")
                    else asdict(Profile())
                )
                values["id"] = new_id()
                base = values["name"] + " copy" if key.endswith("copy") else "New profile"
                name, index = base, 2
                while any(p.name == name for p in self.timer.profiles.values()):
                    name, index = f"{base} {index}", index + 1
                values["name"] = name
                profile = Profile(**values)
                self.timer.profiles[profile.id] = profile
                self.refresh_profiles(profile.id)
                self.load_profile(profile.id)
                self.feedback("Profile created · edit its settings and Save profile")
            elif key == "pomo-profile-delete":
                if (
                    len(self.timer.profiles) == 1
                    or (
                        self.timer.session
                        and self.timer.session["profile"]["id"] == self.profile_id
                    )
                    or any(
                        s.action == "start" and s.target == self.profile_id
                        for s in self.timer.schedules
                    )
                ):
                    raise ValueError(
                        "Keep at least one profile. Stop its session and remove referencing schedules before deleting."
                    )
                del self.timer.profiles[self.profile_id]
                self.refresh_profiles(next(iter(self.timer.profiles)))
                self.load_profile(next(iter(self.timer.profiles)))
            elif key == "pomo-profile-save":
                self.save_profile()
            elif key == "pomo-reminder-new":
                self.reminder_id = None
                self.feedback("New reminder · enter a folder and interval, then Add / update")
            elif key == "pomo-reminder-save":
                reminder = Reminder(
                    id=self.reminder_id or new_id(),
                    category=self.query_one("#pomo-reminder-category", Input).value,
                    minutes=float(self.query_one("#pomo-reminder-minutes", Input).value),
                    during=self.query_one("#pomo-reminder-during", Select).value,
                    enabled=self.query_one("#pomo-reminder-enabled", Checkbox).value,
                )
                self.reminders = [r for r in self.reminders if r.id != reminder.id] + [reminder]
                self.save_profile()
                self.reminder_id = None
                self.render_reminders()
            elif key == "pomo-reminder-delete":
                if self.reminder_id is None:
                    raise ValueError("Select a reminder row with Enter before removing it.")
                self.reminders = [r for r in self.reminders if r.id != self.reminder_id]
                self.save_profile()
                self.reminder_id = None
                self.render_reminders()
            elif key == "pomo-schedule-save":
                names = {name.lower(): index for index, name in enumerate(DAY_NAMES)}
                parts = [
                    p.strip().lower()
                    for p in self.query_one("#pomo-schedule-days", Input).value.split(",")
                ]
                try:
                    days = [int(p) if p.isdigit() else names[p] for p in parts]
                except KeyError as error:
                    raise ValueError(
                        "Weekdays: use Mon,Tue,Wed,Thu,Fri,Sat,Sun or numbers 0–6."
                    ) from error
                action = self.query_one("#pomo-schedule-action", Select).value
                target = (
                    self.query_one("#pomo-schedule-profile", Select).value
                    if action == "start"
                    else self.query_one("#pomo-schedule-command", Input).value
                )
                rule = Schedule(
                    id=new_id() if self.schedule_id == "new" else self.schedule_id,
                    name=self.query_one("#pomo-schedule-name", Input).value,
                    time=self.query_one("#pomo-schedule-time", Input).value,
                    weekdays=days,
                    action=action,
                    target=target,
                    enabled=self.query_one("#pomo-schedule-enabled", Checkbox).value,
                )
                self.timer.schedules = [s for s in self.timer.schedules if s.id != rule.id] + [rule]
                self.query_one("#pomo-schedule", Select).set_options(self.schedule_options())
                self.query_one("#pomo-schedule", Select).value = rule.id
                self.schedule_id = rule.id
                self.feedback(
                    "Schedule saved"
                    + (
                        " · enable weekly scheduling to arm it"
                        if not self.timer.calendar_enabled
                        else ""
                    )
                )
            elif key in {"pomo-schedule-new", "pomo-schedule-delete"}:
                if key.endswith("delete"):
                    self.timer.schedules = [
                        s for s in self.timer.schedules if s.id != self.schedule_id
                    ]
                    self.query_one("#pomo-schedule", Select).set_options(self.schedule_options())
                self.query_one("#pomo-schedule", Select).value = "new"
                self.load_schedule("new")
            elif key == "pomo-audio-save":
                await self.app.configure_voice(
                    self.query_one("#pomo-audio-root", Input).value,
                    int(self.query_one("#pomo-voice-volume", Input).value),
                )
                await self.rescan()
                self.feedback("Voice library and volume saved")
            elif key == "pomo-rescan":
                await self.rescan()
                self.feedback("Voice folders rescanned")
            elif key == "pomo-category-create":
                folder = self.app.voice_library.folder(
                    category(self.query_one("#pomo-new-category", Input).value)
                )
                await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
                await self.rescan()
                self.feedback(f"Folder created: {folder}")
            elif key == "pomo-preview":
                table = self.query_one("#pomo-clips-table", DataTable)
                if table.row_count:
                    command = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                    self.app.preview_voice(command)
            elif key == "pomo-preview-stop":
                await self.app.dismiss_voice()
            await self.app.persist_pomodoro()
            self.refresh_status()
        except (ValueError, KeyError, OSError) as error:
            self.feedback(str(error) or "Check the entered values and try again.")

    def action_close(self):
        self.dismiss()

    async def on_unmount(self):
        if self.app.announcement_preview or self.app.preview_requested:
            await self.app.dismiss_voice()
