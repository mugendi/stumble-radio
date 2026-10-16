import asyncio
import json
import time

import pytest
from test_app import FakePlayer, OfflineAPI
from textual.containers import VerticalScroll
from textual.pilot import Pilot
from textual.widgets import Button, DataTable, Input, TabbedContent

from stumble_radio.app import StumbleRadio
from stumble_radio.pomodoro import Announcement, Reminder
from stumble_radio.pomodoro_screen import PomodoroScreen


@pytest.fixture(autouse=True)
def reachable_network(monkeypatch):
    async def online(url):
        return True

    monkeypatch.setattr("stumble_radio.app.internet_available", online)
    monkeypatch.setattr("stumble_radio.app.retry_delay", lambda attempt: 0)


class Voice:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def play(self, clip, volume):
        self.calls.append((clip, volume))
        self.release = asyncio.Event()
        self.started.set()
        await self.release.wait()

    async def stop(self):
        self.release.set()


def app_with_voices(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    app.announcer = Voice()
    app.voice_library.ensure()
    for command in ("focus-start", "short-break-start", "reminders/stretch"):
        (app.voice_library.folder(command) / "voice.mp3").write_bytes(b"fake voice")
    return app, player


async def press_button(screen, key):
    screen.query_one(key, Button).press()
    await Pilot(screen.app).pause()


async def test_voice_mute_preserves_stream_recording_user_volume_and_metadata(
    db, station, tmp_path
):
    app, player = app_with_voices(db, tmp_path)
    async with app.run_test(size=(120, 42)) as pilot:
        app.manual_tune(station)
        await pilot.pause()
        recording = object()
        player.record_process = recording
        app.dispatch_announcement(Announcement("focus-start", "Time to focus"))
        await asyncio.wait_for(app.announcer.started.wait(), timeout=2)
        assert app.announcement_muted and player.volumes[-1] == 0
        assert player.calls == [station] and player.record_process is recording
        app.automatic = True
        player.rms = float("-inf")
        app.last_audible_at -= 50
        await app.tick()
        await pilot.pause()
        assert player.calls == [station]
        player.rms = -20
        app.accounted_at -= 100
        before = app.listen_seconds
        app.account_listening()
        assert app.listen_seconds == before
        await app.change_volume(5).wait()
        assert app.volume_value == 70 and player.volumes[-1] == 0
        await player.events.put({"event": "property-change", "name": "volume", "data": 0})
        await player.events.put(
            {
                "event": "property-change",
                "name": "metadata",
                "data": {"artist": "Band", "title": "Song"},
            }
        )
        await pilot.pause(0.35)
        assert db.search_tracks()[1] == 0 and app.volume_value == 70
        app.announcer.release.set()
        await pilot.pause(0.4)
        assert not app.announcement_muted and player.volumes[-1] == 70
        assert db.search_tracks("Band")[1] == 1
        assert player.record_process is recording


async def test_radio_pause_and_quiet_suppress_scheduled_voice_but_preview_is_explicit(
    db, station, tmp_path
):
    app, player = app_with_voices(db, tmp_path)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await app.action_pause().wait()
        app.dispatch_announcement(Announcement("focus-start", "Focus"))
        await pilot.pause()
        assert not app.announcer.calls and app.user_paused
        app.preview_voice("focus-start")
        await asyncio.wait_for(app.announcer.started.wait(), timeout=2)
        await app.dismiss_voice()
        assert app.user_paused and player.volumes[-1] == 0
        app.pomodoro.quiet = True
        app.user_paused = False
        app.dispatch_announcement(Announcement("focus-start", "Focus"))
        await pilot.pause()
        assert len(app.announcer.calls) == 1


async def test_switch_and_reconnect_during_voice_keep_radio_muted(db, station, tmp_path):
    app, player = app_with_voices(db, tmp_path)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        app.dispatch_announcement(Announcement("focus-start", "Focus"))
        await asyncio.wait_for(app.announcer.started.wait(), timeout=2)
        app.manual_tune(db.station("two"))
        await pilot.pause()
        assert app.announcement_muted and player.volumes[-1] == 0
        await player.events.put({"event": "end-file", "reason": "error"})
        await pilot.pause()
        assert player.calls[-1].stationuuid == "two" and player.volumes[-1] == 0
        await app.dismiss_voice()
        assert player.volumes[-1] == 65 and app.current.stationuuid == "two"


async def test_sleep_cancels_voice_suspends_scheduler_and_never_resumes_radio(
    db, station, tmp_path
):
    app, player = app_with_voices(db, tmp_path)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await app.pomodoro_control("start")
        await asyncio.wait_for(app.announcer.started.wait(), timeout=2)
        await app.configure_sleep(1, 10).wait()
        app.sleep_until = time.monotonic() - 1
        await app.tick()
        assert app.pomodoro.suspended and app.pomodoro.session["paused"]
        assert player.calls[-1] == "stop" and not app.announcement_muted
        assert player.volumes[-1] == 65 and not app.playback_wanted
        app.dispatch_announcement(Announcement("focus-start", "Should stay quiet"))
        await pilot.pause()
        assert len(app.announcer.calls) == 1


async def test_modal_session_profiles_schedule_and_custom_audio_library(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.click("#podmoro")
        await pilot.pause()
        assert isinstance(app.screen, PomodoroScreen)
        screen = app.screen
        await press_button(screen, "#pomo-start")
        assert app.pomodoro.session is not None
        await press_button(screen, "#pomo-pause")
        assert app.pomodoro.session["paused"]
        await press_button(screen, "#pomo-extend")
        assert app.pomodoro.session["remaining"] > 1700
        await press_button(screen, "#pomo-stop")
        screen.query_one(TabbedContent).active = "pomo-profiles"
        await pilot.pause()
        await press_button(screen, "#pomo-profile-copy")
        screen.query_one("#pomo-profile-name", Input).value = "Deep work"
        screen.query_one("#pomo-profile-focus", Input).value = "50"
        await press_button(screen, "#pomo-profile-save")
        assert any(p.name == "Deep work" and p.focus == 50 for p in app.pomodoro.profiles.values())
        screen.query_one("#pomo-reminder-category", Input).value = "reminders/stretch"
        screen.query_one("#pomo-reminder-minutes", Input).value = "20"
        await press_button(screen, "#pomo-reminder-save")
        assert len(app.pomodoro.profiles[screen.profile_id].reminders) == 1
        screen.query_one(TabbedContent).active = "pomo-schedules"
        await pilot.pause()
        screen.query_one("#pomo-schedule-name", Input).value = "Weekday focus"
        await press_button(screen, "#pomo-schedule-save")
        assert app.pomodoro.schedules[0].weekdays == [0, 1, 2, 3, 4]
        assert not app.pomodoro.calendar_enabled
        screen.query_one(TabbedContent).active = "pomo-clips"
        await pilot.pause()
        library = tmp_path / "custom-voices"
        screen.query_one("#pomo-audio-root", Input).value = str(library)
        await press_button(screen, "#pomo-audio-save")
        screen.query_one("#pomo-new-category", Input).value = "reminders/custom"
        await press_button(screen, "#pomo-category-create")
        assert (library / "reminders/custom").is_dir()
        assert screen.query_one("#pomo-clips-table", DataTable).row_count >= 10
        await pilot.press("escape")
        saved = json.loads(db.metadata("pomodoro_v1"))
        assert saved["library"] == str(library)


@pytest.mark.parametrize("width", [80, 95, 120])
async def test_modal_and_transport_fit_supported_widths(db, tmp_path, width):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(width, 28)) as pilot:
        for key in ("search", "podmoro", "last-play"):
            button = app.query_one(f"#{key}", Button)
            if button.display:
                assert button.region.right <= width and button.region.width >= len(
                    str(button.label)
                )
        await pilot.click("#podmoro")
        await pilot.pause()
        assert isinstance(app.screen, PomodoroScreen)
        screen = app.screen
        await press_button(screen, "#pomo-start")
        assert screen.query_one("#pomo-start", Button).region.right <= width
        viewport = screen.query_one("#pomo-session VerticalScroll", VerticalScroll)
        for key in ("start", "pause", "stop", "skip", "extend", "quiet", "snooze", "dismiss"):
            assert (
                screen.query_one(f"#pomo-{key}", Button).region.bottom
                <= viewport.content_region.bottom
            )
        await pilot.press("escape")


async def test_session_persists_and_restores_paused_without_announcements(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test() as pilot:
        await app.pomodoro_control("start")
        await pilot.pause()
        app.pomodoro.session["remaining"] = 123
    restored = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with restored.run_test() as pilot:
        await pilot.pause()
        assert restored.pomodoro.session["paused"]
        assert 122 <= restored.pomodoro.session["remaining"] <= 123
        assert not restored.announcement_muted
        assert db.count() == 2


async def test_quiet_reminders_keep_precise_captions_without_audio(db, tmp_path):
    app, _player = app_with_voices(db, tmp_path)
    (app.voice_library.folder("reminders/stretch") / "voice.txt").write_text(
        "Relax your shoulders", encoding="utf-8"
    )
    async with app.run_test() as pilot:
        app.pomodoro.quiet = True
        app.dispatch_announcement(Announcement("reminders/stretch", "Stretch", "reminder"))
        await pilot.pause()
        assert app.last_announcement.text == "Relax your shoulders"
        assert not app.announcer.calls and not app.announcement_muted


async def test_processing_gap_pauses_timer_and_stops_stale_voice(db, tmp_path):
    app, _player = app_with_voices(db, tmp_path)
    async with app.run_test():
        await app.pomodoro_control("start")
        await asyncio.wait_for(app.announcer.started.wait(), timeout=2)
        app.pomodoro.last_mono -= 70
        await app.tick()
        assert app.pomodoro.session["paused"] and not app.announcement_muted
        assert "Time passed" in app.pomodoro.notice


async def test_reopen_profiles_with_reminders_and_close_pending_preview(db, tmp_path, monkeypatch):
    app, _player = app_with_voices(db, tmp_path)
    app.pomodoro.profiles["classic"].reminders = [Reminder()]
    async with app.run_test() as pilot:
        app.action_podmoro()
        await pilot.pause()
        assert app.screen.query_one("#pomo-reminders", DataTable).row_count == 1
        original = app.voice_library.choose
        import threading

        entered, release = threading.Event(), threading.Event()

        def delayed(command):
            entered.set()
            release.wait(timeout=2)
            return original(command)

        monkeypatch.setattr(app.voice_library, "choose", delayed)
        app.preview_voice("focus-start")
        await asyncio.to_thread(entered.wait, 2)
        await pilot.press("escape")
        release.set()
        await pilot.pause()
        assert not app.announcer.calls and not app.announcement_muted
