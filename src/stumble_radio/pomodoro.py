"""Clock-driven Pomodoro rules. Audio and persistence stay outside the timer engine."""

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4

COMMANDS = (
    "focus-start",
    "focus-ending",
    "short-break-start",
    "long-break-start",
    "break-ending",
    "session-complete",
    "reminders/water",
    "reminders/stretch",
    "reminders/eyes",
)
PHASES = {"focus": "Focus", "short-break": "Short break", "long-break": "Long break"}


def new_id() -> str:
    return uuid4().hex[:12]


def category(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", value):
        raise ValueError("Use command folders such as reminders/stretch (letters, digits, - or _).")
    return value


def finite(value: float, minimum: float, maximum: float, label: str):
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label}: use {minimum:g}–{maximum:g}.")


@dataclass
class Reminder:
    category: str = "reminders/stretch"
    minutes: float = 30
    during: str = "focus"
    enabled: bool = True
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        self.category = category(self.category)
        finite(self.minutes, 1, 1440, "Reminder interval in minutes")
        if self.during not in {"focus", "break", "any"}:
            raise ValueError("Reminder phase must be focus, break or any.")


@dataclass
class Profile:
    name: str = "Classic"
    focus: float = 25
    short_break: float = 5
    long_break: float = 15
    long_every: int = 4
    limit: int = 0
    focus_warning: float = 0
    break_warning: float = 0
    reminders: list[Reminder] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name or len(self.name) > 80:
            raise ValueError("Give the profile a name of 1–80 characters.")
        for value in (self.focus, self.short_break, self.long_break):
            finite(value, 1, 720, "Phase length in minutes")
        if (
            type(self.long_every) is not int
            or type(self.limit) is not int
            or not 1 <= self.long_every <= 100
            or not 0 <= self.limit <= 1000
        ):
            raise ValueError("Long break frequency: 1–100; focus block limit: 0–1000 (0 repeats).")
        finite(self.focus_warning, 0, self.focus * 60 - 1, "Focus warning in seconds")
        finite(
            self.break_warning,
            0,
            min(self.short_break, self.long_break) * 60 - 1,
            "Break warning in seconds",
        )
        self.reminders = [Reminder(**r) if isinstance(r, dict) else r for r in self.reminders]
        if len({r.id for r in self.reminders}) != len(self.reminders):
            raise ValueError("Reminder IDs must be unique.")


@dataclass
class Schedule:
    name: str
    time: str
    weekdays: list[int]
    action: str
    target: str
    enabled: bool = True
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name or len(self.name) > 80:
            raise ValueError("Give the schedule a name of 1–80 characters.")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError("Use a local time in 24-hour HH:MM format.")
        if not self.weekdays or any(
            type(day) is not int or not 0 <= day <= 6 for day in self.weekdays
        ):
            raise ValueError("Choose weekdays numbered 0 (Monday) through 6 (Sunday).")
        self.weekdays = sorted(set(self.weekdays))
        if self.action not in {"start", "command"}:
            raise ValueError("A schedule must start a profile or play a command.")
        if self.action == "command":
            self.target = category(self.target)


@dataclass(frozen=True)
class Announcement:
    category: str
    text: str
    kind: str = "phase"
    generation: int | None = None


class Pomodoro:
    def __init__(self):
        profile = Profile(id="classic")
        self.profiles = {profile.id: profile}
        self.schedules: list[Schedule] = []
        self.calendar_enabled = False
        self.quiet = False
        self.library = ""
        self.voice_volume = 75
        self.session: dict | None = None
        self.daily: dict[str, dict] = {}
        self.fired: dict[str, str] = {}
        self.snoozed: list[dict] = []
        self.suspended = False
        self.generation = 0
        self.last_mono: float | None = None
        self.last_wall: datetime | None = None
        self.notice = ""
        self.interrupted = False

    @property
    def active_profile(self) -> Profile | None:
        return Profile(**self.session["profile"]) if self.session else None

    def start(self, profile_id: str, now: float, wall: datetime) -> Announcement:
        if self.session:
            raise ValueError("Stop the current session before starting another profile.")
        profile = self.profiles[profile_id]
        self.generation += 1
        self.session = {
            "profile": asdict(profile),
            "phase": "focus",
            "remaining": profile.focus * 60,
            "completed": 0,
            "since_long": 0,
            "paused": False,
            "warning": False,
            "reminders": {},
        }
        self.suspended = False
        self.last_mono, self.last_wall = now, wall
        self.notice = ""
        return Announcement(
            "focus-start", f"Focus time · {profile.name}", generation=self.generation
        )

    def pause(self):
        if self.session:
            self.session["paused"] = True

    def resume(self, now: float, wall: datetime):
        if self.session:
            self.session["paused"] = False
        self.suspended = False
        self.last_mono, self.last_wall = now, wall
        self.notice = ""

    def stop(self):
        self.session = None
        self.generation += 1
        self.snoozed.clear()

    def sleep(self):
        self.pause()
        self.suspended = True
        self.snoozed.clear()
        self.notice = "Scheduler suspended by sleep · Resume to rearm weekly rules"

    def extend(self):
        if self.session:
            finite(self.session["remaining"] + 300, 0, 86400, "Extended phase in seconds")
            self.session["remaining"] += 300
            self.session["warning"] = False

    def snooze(self, announcement: Announcement):
        if announcement.kind == "reminder":
            self.snoozed.append({"announcement": asdict(announcement), "remaining": 300})

    def transition(self, wall: datetime, *, skipped: bool = False) -> Announcement | None:
        if not self.session:
            return None
        session, profile = self.session, self.active_profile
        if session["phase"] == "focus":
            if not skipped:
                session["completed"] += 1
                session["since_long"] += 1
                self.daily.setdefault(wall.date().isoformat(), {"seconds": 0, "blocks": 0})[
                    "blocks"
                ] += 1
            if profile.limit and session["completed"] >= profile.limit:
                self.stop()
                return Announcement("session-complete", f"Session complete · {profile.name}")
            phase = "long-break" if session["since_long"] >= profile.long_every else "short-break"
            if phase == "long-break":
                session["since_long"] = 0
            length = profile.long_break if phase == "long-break" else profile.short_break
            command = f"{phase}-start"
        else:
            phase, length, command = "focus", profile.focus, "focus-start"
        self.generation += 1
        session.update(phase=phase, remaining=length * 60, warning=False)
        self.snoozed = [item for item in self.snoozed if item["announcement"]["generation"] is None]
        return Announcement(
            command, f"{PHASES[phase]} · {length:g} minutes", generation=self.generation
        )

    def tick(self, now: float, wall: datetime) -> list[Announcement]:
        self.interrupted = False
        previous_mono, previous_wall = self.last_mono, self.last_wall
        self.last_mono, self.last_wall = now, wall
        if previous_mono is None or previous_wall is None:
            return []
        elapsed = max(0, now - previous_mono)
        wall_elapsed = wall.timestamp() - previous_wall.timestamp()
        if elapsed > 60 or abs(wall_elapsed) > 60:
            self.interrupted = True
            self.pause()
            if self.session:
                self.notice = "Time passed while away · session paused; Resume when ready"
            elif self.calendar_enabled:
                self.notice = "Scheduler resumed · missed starts skipped"
            return []
        if self.suspended:
            return []
        events = []
        phase_event = None
        if self.session and not self.session["paused"]:
            session, profile = self.session, self.active_profile
            phase = session["phase"]
            used = min(elapsed, session["remaining"])
            if phase == "focus":
                self.daily.setdefault(wall.date().isoformat(), {"seconds": 0, "blocks": 0})[
                    "seconds"
                ] += used
            session["remaining"] -= elapsed
            for reminder in profile.reminders:
                if not reminder.enabled or not (
                    reminder.during == "any" or (reminder.during == "focus") == (phase == "focus")
                ):
                    continue
                clock = session["reminders"].get(reminder.id, 0) + used
                if clock >= reminder.minutes * 60:
                    clock %= reminder.minutes * 60
                    events.append(
                        Announcement(
                            reminder.category,
                            self.command_label(reminder.category),
                            "reminder",
                            self.generation,
                        )
                    )
                session["reminders"][reminder.id] = clock
            if session["remaining"] <= 0:
                overrun = -session["remaining"]
                phase_event = self.transition(wall)
                if self.session:
                    self.session["remaining"] -= overrun
                    if self.session["phase"] == "focus":
                        self.daily.setdefault(wall.date().isoformat(), {"seconds": 0, "blocks": 0})[
                            "seconds"
                        ] += overrun
            else:
                warning = profile.focus_warning if phase == "focus" else profile.break_warning
                if warning and session["remaining"] <= warning and not session["warning"]:
                    session["warning"] = True
                    command = "focus-ending" if phase == "focus" else "break-ending"
                    phase_event = Announcement(
                        command, f"{PHASES[phase]} ending soon", generation=self.generation
                    )
        for item in list(self.snoozed):
            if self.session and self.session["paused"]:
                continue
            item["remaining"] -= elapsed
            if item["remaining"] <= 0:
                self.snoozed.remove(item)
                announcement = Announcement(**item["announcement"])
                if announcement.generation in {None, self.generation}:
                    events.append(announcement)
        if (
            wall.strftime("%Y-%m-%d %H:%M") != previous_wall.strftime("%Y-%m-%d %H:%M")
            and self.calendar_enabled
        ):
            today = wall.date().isoformat()
            for rule in self.schedules:
                if (
                    not rule.enabled
                    or wall.weekday() not in rule.weekdays
                    or wall.strftime("%H:%M") != rule.time
                    or self.fired.get(rule.id) == today
                ):
                    continue
                self.fired[rule.id] = today
                if rule.action == "start":
                    if self.session:
                        self.notice = f"Skipped {rule.name}: a session is already active or paused"
                    elif rule.target in self.profiles:
                        phase_event = self.start(rule.target, now, wall)
                    else:
                        self.notice = f"Schedule {rule.name} refers to a missing profile"
                else:
                    events.append(Announcement(rule.target, rule.name, "reminder"))
        return [phase_event] if phase_event else events[:1]

    @staticmethod
    def command_label(command: str) -> str:
        return command.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").capitalize()

    def snapshot(self) -> dict:
        return {
            "version": 1,
            "profiles": [asdict(p) for p in self.profiles.values()],
            "schedules": [asdict(s) for s in self.schedules],
            "calendar_enabled": self.calendar_enabled,
            "quiet": self.quiet,
            "library": self.library,
            "voice_volume": self.voice_volume,
            "session": self.session,
            "daily": self.daily,
            "fired": self.fired,
            "generation": self.generation,
            "snoozed": self.snoozed,
            "suspended": self.suspended,
        }

    @classmethod
    def restore(cls, data: dict) -> "Pomodoro":
        if data.get("version") != 1:
            raise ValueError("Unsupported Podmoro settings version.")
        timer = cls()
        profiles = [Profile(**item) for item in data["profiles"]]
        if not profiles or len({p.id for p in profiles}) != len(profiles):
            raise ValueError("At least one uniquely identified profile is required.")
        timer.profiles = {p.id: p for p in profiles}
        timer.schedules = [Schedule(**item) for item in data.get("schedules", [])]
        for key in (
            "calendar_enabled",
            "quiet",
            "library",
            "daily",
            "fired",
            "generation",
            "voice_volume",
            "suspended",
        ):
            if key in data:
                setattr(timer, key, data[key])
        finite(timer.voice_volume, 0, 100, "Voice volume")
        timer.session = data.get("session")
        if timer.session:
            Profile(**timer.session["profile"])
            if timer.session["phase"] not in PHASES:
                raise ValueError("Invalid restored timer phase.")
            finite(timer.session["remaining"], 0, 86400, "Remaining seconds")
            for key in ("completed", "since_long"):
                if type(timer.session[key]) is not int or timer.session[key] < 0:
                    raise ValueError("Invalid restored focus block count.")
            for value in timer.session["reminders"].values():
                finite(value, 0, 86400, "Reminder elapsed seconds")
            timer.pause()
            timer.notice = "Previous session restored paused · Resume when ready"
        if not isinstance(timer.daily, dict) or not isinstance(timer.fired, dict):
            raise TypeError("Invalid Podmoro totals or trigger history.")
        for day, totals in timer.daily.items():
            datetime.strptime(day, "%Y-%m-%d")
            finite(totals["seconds"], 0, 172800, "Daily focus seconds")
            if type(totals["blocks"]) is not int or totals["blocks"] < 0:
                raise ValueError("Invalid daily focus block count.")
        for key in ("calendar_enabled", "quiet", "suspended"):
            if type(getattr(timer, key)) is not bool:
                raise ValueError("Invalid Podmoro switch value.")
        if not isinstance(timer.library, str) or type(timer.generation) is not int:
            raise ValueError("Invalid Podmoro library or generation.")
        # Scheduled snoozes belong to the previous run; never replay them on launch.
        return timer
