import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stumble_radio.pomodoro import Announcement, Pomodoro, Profile, Reminder, Schedule


class Clock:
    def __init__(self, timer, wall=None):
        self.timer = timer
        self.now = 0.0
        self.wall = wall or datetime(2026, 10, 19, 8, 59, 0, tzinfo=UTC)
        timer.tick(self.now, self.wall)

    def step(self, seconds):
        self.now += seconds
        self.wall = datetime.fromtimestamp(self.wall.timestamp() + seconds, self.wall.tzinfo)
        return self.timer.tick(self.now, self.wall)

    def advance(self, seconds):
        events = []
        while seconds > 0:
            step = min(seconds, 30)
            events.extend(self.step(step))
            seconds -= step
        return events

    def start(self):
        return self.timer.start("classic", self.now, self.wall)


def test_classic_cycle_long_break_limit_and_totals():
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(
        id="classic", focus=1, short_break=1, long_break=2, long_every=2, limit=3
    )
    clock = Clock(timer)
    assert clock.start().category == "focus-start"
    assert clock.advance(60)[0].category == "short-break-start"
    assert timer.session["completed"] == 1
    assert clock.advance(60)[0].category == "focus-start"
    assert clock.advance(60)[0].category == "long-break-start"
    assert clock.advance(120)[0].category == "focus-start"
    assert clock.advance(60)[0].category == "session-complete"
    assert timer.session is None
    assert timer.daily["2026-10-19"] == {"seconds": 180, "blocks": 3}


def test_pause_extend_skip_and_running_profile_snapshot():
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(id="classic", focus=1)
    clock = Clock(timer)
    clock.start()
    clock.advance(15)
    timer.pause()
    clock.advance(30)
    assert timer.session["remaining"] == 45
    timer.extend()
    timer.resume(clock.now, clock.wall)
    timer.profiles["classic"].focus = 50
    clock.advance(5)
    assert timer.active_profile.focus == 1 and timer.session["remaining"] == 340
    assert timer.transition(clock.wall, skipped=True).category == "short-break-start"
    assert timer.session["completed"] == 0
    assert timer.daily["2026-10-19"] == {"seconds": 20, "blocks": 0}


def test_skipped_focus_after_long_break_does_not_repeat_long_break():
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(id="classic", focus=1, long_every=1)
    clock = Clock(timer)
    clock.start()
    assert clock.advance(60)[0].category == "long-break-start"
    timer.transition(clock.wall, skipped=True)
    assert timer.transition(clock.wall, skipped=True).category == "short-break-start"
    assert timer.session["completed"] == 1


def test_phase_warnings_reminders_accumulate_only_eligible_time_and_priority():
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(
        id="classic",
        focus=2,
        short_break=1,
        focus_warning=20,
        break_warning=10,
        reminders=[Reminder(minutes=1, during="focus")],
    )
    clock = Clock(timer)
    clock.start()
    assert clock.advance(60)[0].kind == "reminder"
    assert clock.advance(40)[0].category == "focus-ending"
    assert clock.advance(20)[0].category == "short-break-start"
    assert clock.advance(50)[0].category == "break-ending"
    assert clock.advance(10)[0].category == "focus-start"
    assert clock.advance(60)[0].kind == "reminder"


@pytest.mark.parametrize("during,expected", [("focus", 1), ("break", 1), ("any", 2)])
def test_reminder_phase_filters(during, expected):
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(
        id="classic", focus=2, short_break=2, reminders=[Reminder(minutes=1, during=during)]
    )
    clock = Clock(timer)
    clock.start()
    # Transition events supersede a reminder coinciding with a phase boundary.
    events = clock.advance(240)
    assert sum(event.kind == "reminder" for event in events) == expected


def test_snooze_and_phase_change_drop_stale_reminders():
    timer = Pomodoro()
    clock = Clock(timer)
    clock.start()
    reminder = Announcement("reminders/water", "Water", "reminder", timer.generation)
    timer.snooze(reminder)
    assert not clock.advance(299)
    assert clock.step(1) == [reminder]
    timer.snooze(reminder)
    timer.transition(clock.wall, skipped=True)
    assert not timer.snoozed
    timer.snooze(Announcement("focus-start", "Focus"))
    assert not timer.snoozed


def test_weekly_triggers_skip_active_session_and_do_not_run_on_launch():
    timer = Pomodoro()
    timer.calendar_enabled = True
    timer.schedules = [Schedule("Morning", "09:00", [0], "start", "classic")]
    clock = Clock(timer)
    assert clock.step(60)[0].category == "focus-start"
    assert not clock.step(1)
    timer.schedules.append(Schedule("Second", "09:01", [0], "start", "classic"))
    clock.step(59)
    assert "already active" in timer.notice
    restored = Pomodoro.restore(json.loads(json.dumps(timer.snapshot())))
    restored.stop()
    assert restored.tick(0, datetime(2026, 10, 19, 9, 0, 30, tzinfo=UTC)) == []
    assert restored.tick(1, datetime(2026, 10, 19, 9, 0, 31, tzinfo=UTC)) == []


def test_weekly_command_and_disabled_rules():
    timer = Pomodoro()
    timer.calendar_enabled = True
    timer.schedules = [
        Schedule("Water", "09:00", [0], "command", "reminders/water"),
        Schedule("Off", "09:00", [0], "command", "reminders/stretch", enabled=False),
    ]
    clock = Clock(timer)
    event = clock.step(60)[0]
    assert event.kind == "reminder" and event.generation is None
    assert timer.session is None and len(timer.fired) == 1


def test_dst_fall_back_does_not_repeat_command_and_spring_gap_is_skipped():
    zone = ZoneInfo("America/New_York")
    timer = Pomodoro()
    timer.calendar_enabled = True
    timer.schedules = [Schedule("Once", "01:00", [6], "command", "reminders/water")]
    clock = Clock(timer, datetime(2026, 11, 1, 0, 59, 30, tzinfo=zone))
    assert len(clock.advance(3660)) == 1
    spring = Pomodoro()
    spring.calendar_enabled = True
    spring.schedules = [Schedule("Missing", "02:30", [6], "command", "reminders/water")]
    clock = Clock(spring, datetime(2026, 3, 8, 1, 59, 30, tzinfo=zone))
    assert not clock.advance(120)


def test_suspend_gap_sleep_and_restore_never_catch_up_audio():
    timer = Pomodoro()
    clock = Clock(timer)
    clock.start()
    clock.step(10)
    before = timer.session["remaining"]
    assert clock.step(5000) == []
    assert timer.session["paused"] and timer.session["remaining"] == before
    assert timer.daily["2026-10-19"]["seconds"] == 10
    restored = Pomodoro.restore(json.loads(json.dumps(timer.snapshot())))
    assert restored.session["paused"]
    restored.resume(clock.now, clock.wall)
    assert not restored.session["paused"]
    restored.sleep()
    assert restored.suspended and restored.session["paused"]
    assert restored.tick(clock.now + 1, clock.wall + timedelta(seconds=1)) == []


def test_short_tick_overrun_is_carried_without_clock_drift():
    timer = Pomodoro()
    timer.profiles["classic"] = Profile(id="classic", focus=1, short_break=1)
    clock = Clock(timer)
    clock.start()
    clock.step(59.5)
    clock.step(1)
    assert timer.session["phase"] == "short-break" and timer.session["remaining"] == 59.5


@pytest.mark.parametrize(
    "values",
    [
        {"focus": float("nan")},
        {"focus": 0},
        {"long_every": 1.5},
        {"limit": -1},
        {"focus_warning": 1500},
        {"break_warning": 300},
    ],
)
def test_profile_validation(values):
    with pytest.raises(ValueError):
        Profile(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"category": "../outside"},
        {"category": "/tmp/file"},
        {"category": "a//b"},
        {"minutes": float("inf")},
        {"during": "unknown"},
    ],
)
def test_reminder_validation(values):
    with pytest.raises(ValueError):
        Reminder(**values)


@pytest.mark.parametrize(
    "time,days", [("25:00", [0]), ("9:00", [0]), ("09:00", []), ("09:00", [7])]
)
def test_weekly_validation(time, days):
    with pytest.raises(ValueError):
        Schedule("Morning", time, days, "start", "classic")


def test_snapshot_roundtrip_preserves_profiles_rules_and_daily_counts(db):
    timer = Pomodoro()
    timer.profiles["classic"].reminders = [Reminder()]
    timer.schedules = [Schedule("Morning", "09:00", [0, 2, 4], "start", "classic")]
    clock = Clock(timer)
    clock.start()
    clock.advance(60)
    db.set_metadata("pomodoro_v1", json.dumps(timer.snapshot()))
    restored = Pomodoro.restore(json.loads(db.metadata("pomodoro_v1")))
    assert restored.snapshot()["profiles"] == [asdict(p) for p in timer.profiles.values()]
    assert restored.daily == timer.daily and restored.session["paused"]
    assert db.count() == 2
