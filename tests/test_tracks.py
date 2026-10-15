import time
from dataclasses import replace

import pytest

from stumble_radio.db import TRACK_RETENTION_SECONDS, Database
from stumble_radio.tracks import Track, track_from_metadata


@pytest.mark.parametrize(
    "metadata,expected",
    [
        (
            {"ARTIST": "Boyz II Men", "TITLE": "End of the Road"},
            Track("Boyz II Men", "End of the Road"),
        ),
        (
            {"icy-title": "Boyz II Men - I'll Make Love to You"},
            Track("Boyz II Men", "I'll Make Love to You", "Boyz II Men - I'll Make Love to You"),
        ),
        (
            {"Artist": "Old band", "title": "Old song", "icy-title": "New band — New song"},
            Track("New band", "New song", "New band — New song"),
        ),
        (
            {"StreamTitle": "A programme without an artist"},
            Track("", "A programme without an artist", "A programme without an artist"),
        ),
        ({"title": "Boyz II Men – On Bended Knee"}, Track("Boyz II Men", "On Bended Knee")),
        ({"title": "\x00Song\n", "artist": "Band\x07"}, Track("Band", "Song")),
        ({"icy-name": "Station", "icy-genre": "jazz"}, None),
        ({"title": "Station"}, None),
        ({"artist": "Band"}, None),
        ({"title": 123}, None),
        (None, None),
    ],
)
def test_metadata_parsing(metadata, expected):
    assert track_from_metadata(metadata, "Station") == expected


def test_fts_prefix_accent_punctuation_and_recent_order(db, station):
    now = time.time()
    other = db.station("two")
    db.add_track(station, Track("Boyz II Men", "End of the Road"), played_at=now - 100)
    db.add_track(other, Track("Boyz II Men", "On Bended Knee"), played_at=now)
    db.add_track(station, Track("Beyoncé", "Halo"), played_at=now - 50)
    rows, total = db.search_tracks("Boyz...")
    assert total == 2 and [row["stationuuid"] for row in rows] == ["two", "one"]
    assert db.search_tracks('boyz "II" men bended')[1] == 1
    assert db.search_tracks("beyonce")[1] == 1
    assert db.search_tracks("London")[1] == 1
    assert db.search_tracks("*")[1] == 0
    assert db.search_tracks("NOT OR artist:")[1] == 0
    assert db.search_tracks("' OR 1=1 --")[1] == 0
    assert db.search_tracks("")[1] == 3


def test_song_history_pagination_and_station_snapshot_survive_sync(db, station):
    for i in range(105):
        db.add_track(station, Track("Boyz II Men", f"Song {i}"))
    db.upsert([replace(station, name="Renamed")])
    db.finish_sync("empty")
    first, count = db.search_tracks("Boyz")
    last, _ = db.search_tracks("Boyz", 100)
    assert count == 105 and len(first) == 100 and len(last) == 5
    assert first[0]["station_name"] == "Nairobi Jazz"
    assert first[0]["title"] == "Song 104" and last[-1]["title"] == "Song 0"
    assert db.station(first[0]["stationuuid"]).name == "Renamed"


def test_retention_removes_fts_matches_and_runs_on_database_open(db, station, monkeypatch):
    now = time.time()
    cutoff = now - TRACK_RETENTION_SECONDS
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: now)
    db.add_track(station, Track("ExpiredArtist", "Old"), played_at=cutoff - 1)
    db.add_track(station, Track("BoundaryArtist", "Keep"), played_at=cutoff)
    db.add_track(station, Track("FreshArtist", "New"), played_at=now)
    assert db.search_tracks()[1] == 2
    assert db.prune_tracks(now=now) == 1
    with db.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM track_plays_fts WHERE track_plays_fts MATCH 'ExpiredArtist'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT count(*) FROM track_plays").fetchone()[0] == 2
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: now + 1)
    reopened = Database(db.path)
    with reopened.connect() as connection:
        assert connection.execute("SELECT count(*) FROM track_plays").fetchone()[0] == 1
    assert reopened.search_tracks("Fresh")[1] == 1
