import sqlite3

import pytest
from test_app import FakePlayer, OfflineAPI
from textual.widgets import Button, DataTable, Input, Static, TextArea

from stumble_radio.app import StumbleRadio
from stumble_radio.screens import StationNotesScreen


@pytest.mark.parametrize("width,height", [(80, 28), (120, 40)])
async def test_station_right_click_edits_notes_and_search_finds_them(db, tmp_path, width, height):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(width, height)) as pilot:
        await pilot.pause()
        station = app.stations[1]
        await pilot.click("#stations", offset=(15, 2), button=3)
        await pilot.pause()
        assert isinstance(app.screen, StationNotesScreen)
        assert app.screen.station == station
        assert player.calls == []
        assert app.focused.id == "station-notes-text"
        app.screen.query_one(TextArea).load_text("Plays happy tunes\nGreat for working")
        app.screen.query_one(Input).value = "upbeat, no ads"
        for key in ("station-notes-save", "station-notes-play", "station-notes-cancel"):
            button = app.screen.query_one(f"#{key}", Button)
            assert button.region.right <= width
            assert button.region.bottom <= height
            assert button.region.width >= len(str(button.label))
        tags = app.screen.query_one(Input)
        assert tags.region.bottom <= app.screen.query_one(".dialog-actions").region.y
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, StationNotesScreen)
        assert db.station_notes(station)["notes"].startswith("Plays happy tunes\n")
        query = app.query_one("#quick-search", Input)
        query.value = "happy tunes"
        await pilot.pause()
        assert app.total == 1 and app.stations[0] == station
        query.value = '"no ads"'
        await pilot.pause()
        assert app.total == 1
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert player.station == station


async def test_station_left_click_selects_and_plays_without_opening_notes(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        station = app.stations[1]
        await pilot.click("#stations", offset=(15, 2))
        await pilot.pause()
        assert app.screen is app.default_screen
        assert app.selected_station() == station
        await pilot.click("#stations", offset=(15, 2))
        await pilot.pause()
        assert app.screen is app.default_screen
        assert player.station == station
        filters = app.filters
        calls = list(player.calls)
        await pilot.click("#stations", offset=(15, 0), button=3)
        await pilot.pause()
        assert app.screen is app.default_screen
        assert app.filters == filters
        assert player.calls == calls


async def test_notes_tooltip_is_only_shown_for_first_three_stations_per_launch(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    one, two = db.station("one"), db.station("two")
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.query_one(DataTable)
        assert "Right-click" in table.tooltip
        for station in (one, two, one):
            await app.tune(station).wait()
            await pilot.pause()
            assert table.tooltip is not None
        await app.tune(one, recovery=True).wait()
        await pilot.pause()
        assert table.tooltip is not None
        await app.tune(two).wait()
        await pilot.pause()
        assert table.tooltip is None
        await app.refresh_library()
        assert table.tooltip is None
        await pilot.click("#stations", offset=(15, 1), button=3)
        await pilot.pause()
        assert isinstance(app.screen, StationNotesScreen)
        await pilot.press("escape")
        assert table.tooltip is None
    restarted = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with restarted.run_test():
        assert "Right-click" in restarted.query_one(DataTable).tooltip


async def test_notes_shortcut_cancel_save_and_play_do_not_disturb_current_stream(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        assert len(app.query("#notes, #equalizer")) == 0
        await pilot.press("enter")
        await pilot.pause()
        playing = player.station
        app.query_one(DataTable).move_cursor(row=1)
        station = app.selected_station()
        db.save_station_notes(station, "original", "work")
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, StationNotesScreen)
        app.screen.query_one(TextArea).load_text("discard this")
        await pilot.press("escape")
        await pilot.pause()
        assert db.station_notes(station)["notes"] == "original"
        assert player.station == playing
        await pilot.press("i")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "original"
        app.screen.query_one(TextArea).load_text("new notes")
        await pilot.click("#station-notes-play")
        await pilot.pause()
        assert db.station_notes(station)["notes"] == "new notes"
        assert player.station == station


async def test_notes_save_error_keeps_draft_open_for_retry(db, tmp_path, monkeypatch):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("i")
        await pilot.pause()
        screen = app.screen
        station = screen.station
        screen.query_one(TextArea).load_text("happy tunes")
        save = db.save_station_notes

        def unavailable(*args):
            raise sqlite3.OperationalError("disk full")

        monkeypatch.setattr(db, "save_station_notes", unavailable)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is screen
        assert screen.query_one(TextArea).text == "happy tunes"
        assert "Could not save" in str(screen.query_one("#station-notes-error", Static).render())
        assert not screen.query_one("#station-notes-save", Button).disabled
        monkeypatch.setattr(db, "save_station_notes", save)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert db.station_notes(station)["notes"] == "happy tunes"
