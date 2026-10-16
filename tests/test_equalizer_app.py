import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest
from test_app import FakePlayer, OfflineAPI
from textual.widgets import Button, Checkbox, Input, Select, Static

from stumble_radio.app import StumbleRadio
from stumble_radio.equalizer import PRESETS, EqualizerSettings
from stumble_radio.equalizer_screen import EqualizerScreen
from stumble_radio.player import PlayerError


async def eventually(pilot, predicate):
    for _ in range(40):
        await pilot.pause(0.05)
        if predicate():
            return
    assert predicate()


@pytest.mark.parametrize("width,height", [(80, 28), (120, 40)])
async def test_equalizer_preview_presets_bypass_reset_and_cancel(db, tmp_path, width, height):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EqualizerScreen)
        assert app.focused.id == "eq-band-0"
        for name in ("reset", "save", "cancel"):
            button = screen.query_one(f"#eq-{name}", Button)
            assert button.region.right <= width and button.region.bottom <= height
        for label in screen.query(".eq-row Label"):
            assert label.region.width >= len(str(label.content))
        screen.query_one("#eq-gain", Input).value = "6"
        for name in ("Rock", "Pop", "Jazz", "Classical", "Bass boost"):
            screen.query_one("#eq-preset", Select).value = name
            await eventually(
                pilot, lambda name=name: player.equalizer == EqualizerSettings(PRESETS[name], 6)
            )
        assert db.metadata("equalizer_v1") == ""
        await pilot.click("#eq-plus-0")
        await eventually(pilot, lambda: player.equalizer.bands[0] == 7)
        assert screen.query_one("#eq-preset", Select).value == "Custom"
        screen.query_one("#eq-bypass", Checkbox).value = True
        await eventually(pilot, lambda: not player.equalizer.active and player.equalizer.gain_db == 6)
        await pilot.click("#eq-reset")
        await eventually(pilot, lambda: player.equalizer == EqualizerSettings())
        screen.query_one("#eq-gain", Input).value = "3"
        await eventually(pilot, lambda: player.equalizer.gain_db == 3)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.default_screen
        assert player.equalizer == EqualizerSettings()
        assert db.metadata("equalizer_v1") == ""


async def test_save_restore_and_invalid_settings_fallback(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    expected = EqualizerSettings(PRESETS["Speech"], 4)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#eq-preset", Select).value = "Speech"
        app.screen.query_one("#eq-gain", Input).value = "4"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is app.default_screen
        assert EqualizerSettings.restore(json.loads(db.metadata("equalizer_v1"))) == expected
    restored = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with restored.run_test():
        assert restored.player.equalizer == expected
    db.set_metadata("equalizer_v1", '{"version":1,"bands":[null]}')
    fallback = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with fallback.run_test():
        assert fallback.player.equalizer == EqualizerSettings()


@pytest.mark.parametrize("width,height", [(80, 28), (120, 40)])
async def test_automatic_leveling_setting_persists_and_reports_on_status(db, tmp_path, width, height):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#eq-gain", Input).value = "6"
        app.screen.query_one("#eq-auto-level", Checkbox).value = True
        await eventually(pilot, lambda: player.equalizer.auto_level and player.equalizer.gain_db == 6)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert EqualizerSettings.restore(json.loads(db.metadata("equalizer_v1"))).auto_level
        player.auto_level_state = "active"
        player.auto_level_correction_db = 4.2
        app.play_state = "PLAYING"
        app.update_status()
        status = str(app.query_one("#status-line", Static).content)
        assert "Auto +4.2 dB" in status
        assert "−17 LUFS" in status
        assert len(status) <= width


@pytest.mark.parametrize("width,height", [(80, 28), (120, 40)])
async def test_invalid_fields_filter_failure_and_save_failure_keep_draft(db, tmp_path, monkeypatch, width, height):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        screen = app.screen
        gain = screen.query_one("#eq-gain", Input)
        gain.value = "99"
        gain.focus()
        await eventually(pilot, lambda: screen.query_one("#eq-error", Static).display)
        await pilot.pause()
        assert player.equalizer == EqualizerSettings()
        assert screen.query_one("#eq-error", Static).display
        assert screen.query_one("#eq-fields").region.contains_region(gain.region)
        apply = player.set_equalizer

        async def reject(settings):
            raise PlayerError("unsupported filter")

        monkeypatch.setattr(player, "set_equalizer", reject)
        gain.value = "6"
        await eventually(pilot, lambda: "unsupported" in str(screen.query_one("#eq-error", Static).content))
        assert player.equalizer == EqualizerSettings()
        assert "unsupported" in str(screen.query_one("#eq-error", Static).content)
        await pilot.press("ctrl+s")
        assert app.screen is screen and db.metadata("equalizer_v1") == ""
        monkeypatch.setattr(player, "set_equalizer", apply)

        def full_disk(*args):
            raise sqlite3.OperationalError("disk full")

        monkeypatch.setattr(db, "set_metadata", full_disk)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is screen
        assert gain.value == "6" and player.equalizer.gain_db == 6
        assert db.metadata("equalizer_v1") == ""
        assert "Could not save" in str(screen.query_one("#eq-error", Static).content)
        await pilot.press("escape")
        assert player.equalizer == EqualizerSettings()


async def test_cancel_waits_for_running_preview_and_discards_queued_changes(db, tmp_path):
    player = FakePlayer()
    apply = player.set_equalizer
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(settings):
        if settings.gain_db == 1:
            entered.set()
            await release.wait()
        await apply(settings)

    player.set_equalizer = slow
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        gain = app.screen.query_one("#eq-gain", Input)
        gain.value = "1"
        await asyncio.wait_for(entered.wait(), 2)
        gain.value = "2"
        await pilot.pause(0.25)
        cancel = asyncio.create_task(app.screen.action_cancel())
        await asyncio.sleep(0)
        release.set()
        await cancel
        await pilot.pause(0.3)
        assert app.screen is app.default_screen
        assert player.equalizer == EqualizerSettings()


async def test_processing_preserves_station_recording_mute_and_sleep_controls(db, station, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.tune(station).wait()
        await pilot.pause()
        recording = player.record_process = object()
        settings = EqualizerSettings(PRESETS["Bass boost"], 12)
        await player.set_equalizer(settings)
        assert player.calls == [station] and player.record_process is recording
        app.announcement_muted = True
        await app.apply_volume()
        assert player.volumes[-1] == 0 and player.equalizer == settings
        app.announcement_muted = False
        app.user_paused = True
        await app.apply_volume()
        assert player.volumes[-1] == 0
        app.user_paused = False
        app.sleep_gain = 0.5
        await app.apply_volume()
        assert player.volumes[-1] == app.volume_value * 0.5
        assert player.equalizer == settings
        await player.set_equalizer(replace(settings, enabled=False))
        assert player.record_process is recording
        player.record_process = None
