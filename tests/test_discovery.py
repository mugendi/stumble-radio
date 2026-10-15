import random
import sqlite3
import time

import pytest

from stumble_radio.db import Database
from stumble_radio.discovery import DiscoverySettings, diversity_score, shuffle_key
from stumble_radio.models import Search


def test_fast_skip_cools_random_pool_but_preserves_manual_search(db, station):
    visit = db.add_history(station)
    db.save_listening(visit, 3, "skip")
    assert all(s.stationuuid != station.stationuuid for s in db.discover(Search()))
    assert db.search(Search(country="KE"))[1] == 1
    assert db.journal()["seconds"] == 3
    # A long manual revisit earns the station its place back.
    second = db.add_history(station)
    db.save_listening(second, 65, "quit")
    assert any(s.stationuuid == station.stationuuid for s in db.discover(Search()))


def test_checkpoint_is_incremental_and_finalisation_is_idempotent(db, station):
    visit = db.add_history(station)
    db.save_listening(visit, 4)
    db.save_listening(visit, 12)
    db.save_listening(visit, 11)
    db.save_listening(visit, 20, "quit")
    db.save_listening(visit, 100, "skip")
    assert db.journal()["seconds"] == 20
    assert len(db.discover(Search())) == 2


def test_hot_station_has_higher_sampling_weight(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.5)
    assert shuffle_key(120) < shuffle_key(0)
    assert shuffle_key(6000) == shuffle_key(600)


def test_shuffle_modes_and_country_pool(db):
    assert [s.countrycode for s in db.discover(Search(), pool="Music-only")] == ["KE"]
    assert [s.countrycode for s in db.discover(Search(), pool="Talk/News")] == ["GB"]
    assert db.countries(Search()) == [("GB", "United Kingdom"), ("KE", "Kenya")]
    assert db.countries(Search(language="swahili")) == [("KE", "Kenya")]


def test_dead_station_cooldown_and_expiry(db, station, monkeypatch):
    now = time.time()
    db.mark_dead(station)
    assert len(db.discover(Search())) == 1
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: now + 901)
    assert len(db.discover(Search())) == 2


def test_journal_diversity_passport_and_top_stations(db, station):
    first = db.add_history(station)
    db.save_listening(first, 120, "quit")
    other = db.search(Search(country="GB"))[0][0]
    second = db.add_history(other)
    db.save_listening(second, 60, "sleep")
    journal = db.journal()
    assert journal["seconds"] == 180 and journal["plays"] == 2
    assert journal["top"][0]["name"] == station.name
    assert {r["countrycode"] for r in journal["passport"]} == {"KE", "GB"}
    assert 0 < journal["country_diversity"] < 100
    assert diversity_score([1, 1]) == 50
    assert diversity_score([]) == diversity_score([5]) == 0
    assert journal["recent"][0]["end_reason"] == "sleep"


def test_history_migration_preserves_favourites_and_legacy_history(db, station):
    db.toggle_favourite(station)
    visit = db.add_history(station)
    with sqlite3.connect(db.path) as connection:
        connection.execute("ALTER TABLE history DROP COLUMN listened_seconds")
        connection.execute("ALTER TABLE history DROP COLUMN end_reason")
    reopened = Database(db.path)
    assert reopened.favourite_ids() == {station.stationuuid}
    reopened.save_listening(visit, 40, "quit")
    assert reopened.journal()["seconds"] == 40


@pytest.mark.parametrize(
    "settings",
    [
        {"recovery_seconds": 0},
        {"latitude": 5},
        {"latitude": 91, "longitude": 0},
        {"radius_km": float("nan")},
        {"latitude": 0, "longitude": 0, "radius_km": -5},
    ],
)
def test_settings_validation(settings):
    with pytest.raises(ValueError):
        DiscoverySettings(**settings)
