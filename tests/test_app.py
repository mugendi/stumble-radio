import asyncio
import time
from dataclasses import replace

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static

from stumble_radio.app import StumbleRadio
from stumble_radio.discovery import POOL_MODES, DiscoverySettings
from stumble_radio.models import Search
from stumble_radio.player import PlayerError
from stumble_radio.query import format_query, parse_query
from stumble_radio.screens import (
    JournalScreen,
    LastPlayScreen,
    SearchScreen,
    SleepScreen,
    StationPicker,
)
from stumble_radio.tracks import Track


@pytest.fixture(autouse=True)
def network_is_reachable(monkeypatch):
    async def online(url):
        return True

    monkeypatch.setattr("stumble_radio.app.internet_available", online)
    monkeypatch.setattr("stumble_radio.app.retry_delay", lambda attempt: 0)


class FakePlayer:
    def __init__(self):
        self.events = asyncio.Queue()
        self.station = None
        self.record_process = None
        self.calls = []
        self.closed = False
        self.position = 1.0
        self.rms = -20
        self.volumes = []

    async def play(self, station):
        self.station = station
        self.calls.append(station)
        await self.events.put({"event": "file-loaded"})

    async def pause(self):
        await self.events.put({"event": "property-change", "name": "pause", "data": True})

    async def stop(self):
        self.calls.append("stop")

    async def health(self):
        self.position += 1
        return self.position, self.rms

    async def set_volume(self, value):
        self.volumes.append(value)

    async def close(self):
        self.closed = True


class OfflineAPI:
    async def close(self):
        pass

    async def stations(self, params):
        raise AssertionError("offline must not contact directory")

    async def search(self, *args, **kwargs):
        raise AssertionError("offline must not contact directory")

    async def register_play(self, *args):
        raise AssertionError("offline must not contact directory")


async def test_track_history_records_changes_without_duplicates_or_stale_stations(
    db, station, tmp_path
):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        app.manual_tune(station)
        await pilot.pause()

        async def metadata(value, stationuuid="one"):
            await player.events.put(
                {
                    "event": "property-change",
                    "name": "metadata",
                    "data": value,
                    "stationuuid": stationuuid,
                }
            )
            await pilot.pause(0.4)

        await player.events.put(
            {"event": "property-change", "name": "media-title", "data": station.name}
        )
        await metadata({"icy-name": station.name})
        assert db.search_tracks()[1] == 0
        await metadata({"icy-title": "Boyz II Men - End of the Road"})
        await metadata({"ARTIST": "Boyz II Men", "TITLE": "End of the Road"})
        assert db.search_tracks("Boyz")[1] == 1
        await player.events.put({"event": "property-change", "name": "pause", "data": True})
        await metadata({"artist": "Boyz II Men", "title": "On Bended Knee"})
        assert db.search_tracks()[1] == 1
        await player.events.put({"event": "property-change", "name": "pause", "data": False})
        await pilot.pause(0.4)
        assert db.search_tracks()[1] == 2
        other = db.station("two")
        app.manual_tune(other)
        await pilot.pause()
        await metadata({"icy-title": "Wrong band - Stale track"})
        assert db.search_tracks("Wrong")[1] == 0
        await metadata({"icy-title": "Boyz II Men - End of the Road"}, "two")
        rows, total = db.search_tracks("Boyz")
        assert total == 3 and rows[0]["stationuuid"] == "two"
        await metadata({"icy-title": "Another artist - Another song"}, "two")
        await metadata({"icy-title": "Boyz II Men - End of the Road"}, "two")
        assert db.search_tracks("Boyz")[1] == 4


async def test_last_play_search_pagination_keyboard_and_tune(db, station, tmp_path):
    other = db.station("two")
    for i in range(104):
        db.add_track(station, Track("Boyz II Men", f"Song {i}"))
    db.add_track(other, Track("Boyz II Men", "Newest Song"))
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(80, 28)) as pilot:
        await pilot.click("#last-play")
        await pilot.pause()
        assert isinstance(app.screen, LastPlayScreen)
        screen = app.screen
        assert screen.query_one(DataTable).row_count == 100
        await pilot.click("#last-play-next")
        await pilot.pause()
        assert screen.page_offset == 100 and screen.query_one(DataTable).row_count == 5
        screen.query_one(Input).value = "Boyz..."
        await pilot.pause()
        assert screen.page_offset == 0 and screen.total == 105
        screen.query_one(Input).value = "not heard"
        await pilot.pause()
        assert screen.total == 0
        screen.query_one(Input).value = "Boyz newest"
        await pilot.pause()
        assert screen.query_one(DataTable).row_count == 1
        screen.query_one(Input).focus()
        await pilot.press("enter", "enter")
        await pilot.pause()
        assert player.station.stationuuid == "two" and len(player.calls) == 1
        app.query_one("#quick-search", Input).focus()
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert isinstance(app.screen, LastPlayScreen)
        await pilot.press("escape")
        assert app.screen == app.default_screen


async def test_next_station_matches_playing_url_when_representative_changes(db, station, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        db.upsert([replace(station, stationuuid="alias", votes=100)])
        await app.refresh_library()
        assert {s.stationuuid for s in app.stations} == {"alias", "two"}
        app.action_next_station()
        await pilot.pause()
        assert player.station.stationuuid == "two"


async def test_keyboard_flow_and_dialogs(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 2
        assert str(app.query_one("#previous", Button).label) == "⏮"
        assert str(app.query_one("#next", Button).label) == "⏭"
        assert str(app.query_one("#pause", Button).label) == "▶"
        await pilot.press("enter")
        await pilot.pause()
        assert player.station and app.play_state == "PLAYING"
        assert str(app.query_one("#pause", Button).label) == "⏸"
        assert app.query_one("#pause", Button).tooltip == "Pause (Space)"
        assert db.search(Search(), "history")[1] == 1
        await pilot.press("space")
        await pilot.pause()
        assert app.play_state == "PAUSED"
        assert str(app.query_one("#pause", Button).label) == "▶"
        await player.events.put({"event": "property-change", "name": "pause", "data": False})
        await pilot.pause()
        assert str(app.query_one("#pause", Button).label) == "⏸"
        await pilot.press("f")
        await pilot.pause()
        assert player.station.stationuuid in db.favourite_ids()
        app.query_one("#library", Select).value = "favourites"
        await pilot.pause()
        assert app.mode == "favourites" and app.total == 1
        app.action_picker()
        await pilot.pause()
        assert isinstance(app.screen, StationPicker)
        await pilot.press("escape")
        app.action_search()
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        # Background status updates must work while a modal is open.
        await app.tick()
        app.screen.query_one("#country", Input).value = "KE"
        app.screen.apply()
        await pilot.pause()
        assert app.filters.country == "KE"
        app.action_sleep()
        await pilot.pause()
        assert isinstance(app.screen, SleepScreen)
        await pilot.press("escape")
        app.configure_sleep(15)
        await pilot.pause()
        assert app.sleep_minutes == 15
        app.sleep_until = time.monotonic() - 1
        await app.tick()
        assert player.calls[-1] == "stop" and app.play_state == "STOPPED"
        assert str(app.query_one("#pause", Button).label) == "▶"
    assert player.closed


async def test_narrow_screen_search_and_library(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(80, 28)) as pilot:
        await pilot.pause()
        query = app.query_one("#quick-search", Input)
        query.value = "Nairobi"
        await pilot.pause()
        assert app.total == 1
        query.value = "no such station"
        await pilot.pause()
        assert app.total == 0
        await pilot.click("#cycle-library")
        await pilot.pause()
        assert app.mode == "favourites" and not app.filters.name


async def test_search_validation_keeps_modal_open(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test() as pilot:
        app.action_search()
        await pilot.pause()
        app.screen.query_one("#latitude", Input).value = "NaN"
        app.screen.apply()
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)


async def test_stumble_respects_filters_and_offline(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.filters = Search(country="KE")
        app.action_stumble()
        await pilot.pause()
        assert player.station.countrycode == "KE"


async def test_results_paginate(db, station, tmp_path):
    db.upsert(
        [replace(station, stationuuid=str(i), url=f"https://example.test/{i}") for i in range(110)]
    )
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.stations) == 100
        app.action_next_page()
        await pilot.pause()
        assert app.offset == 100 and len(app.stations) == 12


async def test_teleport_changes_country_and_animates_header(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(120, 40)) as pilot:
        app.filters = Search(country="KE")
        await app.action_stumble().wait()
        await pilot.pause()
        assert app.current.countrycode == "KE"
        await app.action_teleport().wait()
        await pilot.pause()
        assert app.current.countrycode == "GB"
        assert app.destination == "United Kingdom" and app.automatic
        assert app.query_one("#quick-search").region.y > app.query_one("#transport").region.bottom


async def test_listening_measurement_excludes_pause_and_journal_shortcut(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        app.accounted_at -= 65
        await app.checkpoint_listening()
        assert db.journal()["seconds"] >= 65
        await pilot.press("space")
        await pilot.pause()
        await app.checkpoint_listening()
        baseline = db.journal()["seconds"]
        app.accounted_at -= 100
        await app.checkpoint_listening()
        assert db.journal()["seconds"] == baseline
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.screen, JournalScreen)


async def test_disconnected_stream_reconnects_same_station_after_it_has_loaded(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await app.action_stumble().wait()
        await pilot.pause()
        initial = app.current.stationuuid
        await player.events.put({"event": "end-file", "reason": "error"})
        await pilot.pause()
        assert app.current.stationuuid == initial and app.automatic
        assert len(player.calls) == 2 and app.play_state == "PLAYING"
        assert any(s.stationuuid == initial for s in db.discover(Search()))


async def test_manual_station_retries_beyond_shuffle_failure_budget(db, station, tmp_path):
    restored = asyncio.Event()

    class FlakyPlayer(FakePlayer):
        async def play(self, station):
            self.calls.append(station)
            self.station = station
            if 1 < len(self.calls) < 12:
                await self.events.put({"event": "end-file", "reason": "error"})
            else:
                await self.events.put({"event": "file-loaded"})
                if len(self.calls) == 12:
                    restored.set()

    player = FlakyPlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await player.events.put({"event": "end-file", "reason": "eof"})
        await asyncio.wait_for(restored.wait(), timeout=5)
        await pilot.pause()
        assert len(player.calls) == 12 and {s.stationuuid for s in player.calls} == {"one"}
        assert app.play_state == "PLAYING" and not app.recovering
        assert not app.failed_ids
        assert any(s.stationuuid == "one" for s in db.discover(Search()))


@pytest.mark.parametrize("loaded_first", [False, True])
async def test_internet_outage_preserves_station_and_resumes(
    db, station, tmp_path, monkeypatch, loaded_first
):
    online, detected, restored = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def reachable(url):
        detected.set()
        return online.is_set()

    monkeypatch.setattr("stumble_radio.app.internet_available", reachable)
    monkeypatch.setattr("stumble_radio.app.NETWORK_POLL_SECONDS", 0.01)

    class OutagePlayer(FakePlayer):
        async def play(self, station):
            self.station = station
            self.calls.append(station)
            if loaded_first or len(self.calls) > 1:
                await self.events.put({"event": "file-loaded"})
                if len(self.calls) > 1:
                    restored.set()

    player = OutagePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await app.tune(station, automatic=True).wait()
        await pilot.pause()
        app.volume_value = 37
        if loaded_first:
            await player.events.put({"event": "end-file", "reason": "error"})
        else:
            app.tune_started -= 50
            await app.tick()
        await asyncio.wait_for(detected.wait(), timeout=2)
        await pilot.pause(0.05)
        assert app.play_state == "WAITING FOR NETWORK" and len(player.calls) == 1
        assert "Network unavailable" in app.connection_state
        assert not app.failed_ids and app.recovery_attempts == 0
        assert any(s.stationuuid == "one" for s in db.discover(Search()))
        online.set()
        await asyncio.wait_for(restored.wait(), timeout=2)
        await pilot.pause()
        assert app.play_state == "PLAYING" and app.current.stationuuid == "one"
        assert not app.recovering and not app.needs_reconnect and not app.connection_state
        assert player.volumes[-1] == 37


async def test_pause_offline_suspends_retry_until_resume(db, station, tmp_path, monkeypatch):
    online, detected = asyncio.Event(), asyncio.Event()

    async def reachable(url):
        detected.set()
        return online.is_set()

    monkeypatch.setattr("stumble_radio.app.internet_available", reachable)
    monkeypatch.setattr("stumble_radio.app.NETWORK_POLL_SECONDS", 0.01)
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await player.events.put({"event": "disconnected"})
        await asyncio.wait_for(detected.wait(), timeout=2)
        await pilot.pause(0.02)
        await app.action_pause().wait()
        assert app.user_paused and not app.playback_wanted and app.play_state == "PAUSED"
        # A late unpause event from the old load must not undo the user's pause.
        await player.events.put({"event": "property-change", "name": "pause", "data": False})
        online.set()
        await pilot.pause(0.05)
        assert len(player.calls) == 2 and player.calls[-1] == "stop"
        assert str(app.query_one("#pause", Button).label) == "▶"
        app.query_one(DataTable).move_cursor(row=1)
        await app.action_pause().wait()
        await pilot.pause()
        assert player.calls[-1].stationuuid == "one" and app.play_state == "PLAYING"


async def test_changing_station_cancels_old_connectivity_check(db, station, tmp_path, monkeypatch):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def unreachable(url):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr("stumble_radio.app.internet_available", unreachable)
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await player.events.put({"event": "end-file", "reason": "error"})
        await asyncio.wait_for(started.wait(), timeout=2)
        app.manual_tune(db.station("two"))
        await asyncio.wait_for(cancelled.wait(), timeout=2)
        await pilot.pause()
        assert [s.stationuuid for s in player.calls] == ["one", "two"]
        assert app.play_state == "PLAYING" and not app.needs_reconnect


async def test_sleep_during_outage_cancels_future_resume(db, station, tmp_path, monkeypatch):
    online, detected = asyncio.Event(), asyncio.Event()

    async def reachable(url):
        detected.set()
        return online.is_set()

    monkeypatch.setattr("stumble_radio.app.internet_available", reachable)
    monkeypatch.setattr("stumble_radio.app.NETWORK_POLL_SECONDS", 0.01)
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await player.events.put({"event": "end-file", "reason": "error"})
        await asyncio.wait_for(detected.wait(), timeout=2)
        await app.configure_sleep(1).wait()
        app.sleep_until = time.monotonic() - 1
        await app.tick()
        online.set()
        await player.events.put({"event": "property-change", "name": "pause", "data": False})
        await player.events.put({"event": "end-file", "reason": "eof"})
        await pilot.pause(0.05)
        assert player.calls == [station, "stop"]
        assert app.play_state == "STOPPED" and not app.playback_wanted


async def test_pause_intent_survives_ipc_failure_and_stale_unpause(db, station, tmp_path):
    class LostIPC(FakePlayer):
        async def pause(self):
            await self.events.put({"event": "property-change", "name": "pause", "data": False})
            raise PlayerError("Lost connection to mpv")

    player = LostIPC()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        await app.action_pause().wait()
        await player.events.put({"event": "disconnected"})
        await pilot.pause()
        assert app.play_state == "PAUSED" and not app.playback_wanted
        assert player.calls == [station]
        await app.action_pause().wait()
        await pilot.pause()
        assert app.play_state == "PLAYING" and len(player.calls) == 2


async def test_manual_startup_errors_and_stalls_retry(db, station, tmp_path):
    class CannotConnect(FakePlayer):
        async def play(self, station):
            self.calls.append(station)
            if len(self.calls) == 1:
                raise PlayerError("mpv did not respond")
            self.station = station
            await self.events.put({"event": "file-loaded"})

    player = CannotConnect()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        assert len(player.calls) == 2 and app.play_state == "PLAYING"
        app.last_progress_at -= 50
        await app.tick()
        await pilot.pause()
        assert len(player.calls) == 3 and app.current.stationuuid == "one"


@pytest.mark.parametrize(
    "error", [ValueError("Invalid stream URL"), PlayerError("Install mpv for playback")]
)
async def test_invalid_stream_or_missing_mpv_does_not_retry_forever(db, station, tmp_path, error):
    class FatalPlayer(FakePlayer):
        async def play(self, station):
            self.calls.append(station)
            raise error

    player = FatalPlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        app.manual_tune(station)
        await pilot.pause()
        assert player.calls == [station] and app.play_state == "ERROR"
        assert not app.playback_wanted and not app.recovering


async def test_silence_recovers_and_pause_does_not(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await app.action_stumble().wait()
        await pilot.pause()
        initial = app.current.stationuuid
        await player.events.put({"event": "property-change", "name": "pause", "data": True})
        await pilot.pause()
        app.last_progress_at = app.last_audible_at = time.monotonic() - 50
        await app.tick()
        await pilot.pause()
        assert app.current.stationuuid == initial and app.play_state == "PAUSED"
        await player.events.put({"event": "property-change", "name": "pause", "data": False})
        await pilot.pause()
        player.rms = float("-inf")
        await app.check_health().wait()
        app.last_audible_at = time.monotonic() - 50
        await app.tick()
        await pilot.pause()
        assert app.current.stationuuid != initial


async def test_startup_timeout_recovers(db, tmp_path):
    class NeverLoads(FakePlayer):
        async def play(self, station):
            self.station = station
            self.calls.append(station)

    player = NeverLoads()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await app.action_stumble().wait()
        await pilot.pause()
        initial = app.current.stationuuid
        app.tune_started -= 50
        await app.tick()
        await pilot.pause()
        assert app.current.stationuuid != initial


async def test_sleep_fades_restores_volume_and_disables_recovery(db, tmp_path):
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test() as pilot:
        await app.action_stumble().wait()
        await pilot.pause()
        await app.configure_sleep(1, 10).wait()
        app.sleep_until = time.monotonic() + 5
        await app.tick()
        assert 0 < player.volumes[-1] < 65
        app.sleep_until = time.monotonic() - 1
        await app.tick()
        assert player.volumes[-1] == 65
        assert player.calls[-1] == "stop" and not app.automatic
        await player.events.put({"event": "end-file", "reason": "eof"})
        await pilot.pause()
        assert player.calls[-1] == "stop"


async def test_pool_modes_use_saved_language_and_location(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test() as pilot:
        app.settings = DiscoverySettings(language="swahili", latitude=-1.29, longitude=36.82)
        for expected in POOL_MODES[1:]:
            app.action_pool()
            assert app.pool == expected
        app.pool = "Your language"
        assert app.pool_search().language == "swahili"
        app.pool = "Nearby"
        search = app.pool_search()
        assert search.latitude == -1.29 and search.radius_km == 100
        rows = db.discover(search)
        assert len(rows) == 1 and rows[0].countrycode == "KE"
        await pilot.pause()


async def test_advanced_filters_stay_visible_and_clear_together(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(120, 40)) as pilot:
        app.filters = Search(
            name="Jazz",
            country="KE",
            state="Nairobi",
            language="swahili",
            tags="jazz,blues",
            codec="MP3",
            bitrate_min=128,
            bitrate_max=320,
            https_only=True,
            latitude=-1.29,
            longitude=36.82,
            radius_km=50,
            order="votes",
            descending=False,
        )
        app.query_one("#quick-search", Input).value = format_query(app.filters)
        await app.refresh_library()
        summary = app.query_one("#active-filters", Static)
        assert summary.display
        rendered = str(summary.content)
        for text in (
            "KE",
            "Nairobi",
            "swahili",
            "jazz,blues",
            "MP3",
            "128–320",
            "HTTPS",
            "50 km",
            "votes",
        ):
            assert text.casefold() in rendered.casefold()
        assert not app.query_one("#clear-filters", Button).disabled
        await pilot.resize_terminal(80, 28)
        await pilot.pause()
        assert app.query_one(DataTable).size.height >= 3
        await pilot.click("#clear-filters")
        await pilot.pause()
        assert app.filters == Search() and app.offset == 0
        assert not app.query_one("#quick-search", Input).value
        assert not summary.display and app.total == 2
        assert app.query_one("#clear-filters", Button).disabled


async def test_name_only_search_can_also_be_cleared(db, tmp_path):
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(80, 28)) as pilot:
        app.query_one("#quick-search", Input).value = "Nairobi"
        await pilot.pause()
        assert app.total == 1
        await pilot.click("#clear-filters")
        await pilot.pause()
        assert app.total == 2


async def test_boolean_search_bar_form_and_clear_stay_in_sync(db, station, tmp_path):
    db.upsert(
        [
            replace(
                station,
                stationuuid="rock",
                url="https://example.test/rock",
                name="Slow Tracks",
                tags="rock,country",
            )
        ]
    )
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(120, 40)) as pilot:
        query = app.query_one("#quick-search", Input)
        query.value = "country|rock|blues country:kenya"
        await pilot.pause()
        assert app.total == 2 and app.filters.country == "kenya"
        assert "rock" in str(app.query_one("#active-filters", Static).content)
        app.action_search()
        await pilot.pause()
        app.screen.query_one("#language", Input).value = "swahili"
        app.screen.apply()
        await pilot.pause()
        assert "language:swahili" in query.value and app.filters.expression
        assert parse_query(query.value) == app.filters
        query.value = "country+rock country:kenya"
        await pilot.pause()
        assert app.total == 1 and app.stations[0].stationuuid == "rock"
        query.value = "country+rock country:"
        await pilot.pause()
        assert app.query_error and app.query_one("#query-error").display
        assert app.total == 1
        await app.action_stumble().wait()
        assert app.current is None
        await pilot.click("#clear-filters")
        await pilot.pause()
        assert not app.query_error and app.total == 3


async def test_click_every_header_reverses_sort_and_preserves_query(db, station, tmp_path):
    db.toggle_favourite(station)
    player = FakePlayer()
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=player)
    async with app.run_test(size=(190, 45)) as pilot:
        app.query_one("#quick-search", Input).value = "country:KE|country:GB"
        await pilot.pause()
        table = app.query_one(DataTable)
        for key, _ in app.TABLE_COLUMNS:
            offset = 0
            for column in table.columns.values():
                if column.key.value == key:
                    break
                offset += column.get_render_width(table)
            await pilot.click("#stations", offset=(offset + 1, 0))
            await pilot.pause()
            assert app.filters.order == key
            first_direction = app.filters.descending
            assert parse_query(app.query_one("#quick-search", Input).value) == app.filters
            assert app.filters.expression and not player.calls
            if key != "favourite" or first_direction:
                assert app.stations[0].stationuuid == station.stationuuid
            await pilot.click("#stations", offset=(offset + 1, 0))
            await pilot.pause()
            assert app.filters.descending != first_direction
            assert str(column.label).endswith("↓" if app.filters.descending else "↑")


async def test_history_defaults_to_recent_but_plays_header_sorts_plays(db, station, tmp_path):
    db.add_history(station)
    app = StumbleRadio(db, tmp_path, offline=True, api=OfflineAPI(), player=FakePlayer())
    async with app.run_test(size=(190, 45)) as pilot:
        app.query_one("#library", Select).value = "history"
        await pilot.pause()
        assert app.filters.order == "recent"
        table = app.query_one(DataTable)
        offset = sum(c.get_render_width(table) for c in list(table.columns.values())[:-1]) + 1
        await pilot.click("#stations", offset=(offset, 0))
        await pilot.pause()
        assert app.filters.order == "clickcount" and app.filters.descending
