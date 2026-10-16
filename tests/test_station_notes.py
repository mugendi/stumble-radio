from dataclasses import replace

import pytest

from stumble_radio.db import Database
from stumble_radio.models import Search
from stumble_radio.query import parse_query


def test_notes_and_personal_tags_are_searchable_with_existing_filters(db, station):
    db.save_station_notes(station, "Plays happy tunes\nAsk for DJ Élodie", "upbeat, work")
    for query in ("happy tunes", '"HAPPY TUNES"', "élodie", "upbeat", "work country:KE"):
        rows, total = db.search(parse_query(query))
        assert total == 1 and rows[0].stationuuid == station.stationuuid
    assert db.search(parse_query("happy country:GB"))[1] == 0
    assert db.search(parse_query("(happy|news) country:KE"))[1] == 1
    assert db.search(parse_query("happy+work"))[1] == 1
    assert db.search(Search(name="happy"))[1] == 0
    assert db.search(Search(tags="work"))[1] == 0
    assert db.station(station.stationuuid).tags == station.tags
    for mode in ("favourites", "history", "unheard"):
        if mode == "favourites":
            db.toggle_favourite(station)
        if mode == "history":
            db.add_history(station)
        expected = 0 if mode == "unheard" else 1
        assert db.search(parse_query("happy"), mode)[1] == expected


def test_notes_survive_reopen_catalogue_sync_and_url_change(db, station):
    db.save_station_notes(station, "happy tunes", "work")
    db = Database(db.path)
    updated = replace(station, name="Renamed", url="https://example.test/new-stream")
    db.upsert([updated], sync_token="fresh")
    db.finish_sync("fresh")
    assert db.station_notes(updated) == {"notes": "happy tunes", "tags": "work"}
    assert db.search(parse_query("happy tunes"))[0][0].name == "Renamed"
    db.finish_sync("removed")
    assert db.station_notes(updated)["notes"] == "happy tunes"
    db.save_station_notes(updated, "still here")
    assert db.count() == 0


def test_saving_an_open_editor_preserves_newer_catalogue_data(db, station):
    updated = replace(station, name="Renamed", url="https://example.test/new-stream", votes=99)
    db.upsert([updated], sync_token="fresh")
    db.save_station_notes(station, "happy tunes")
    assert db.station(station.stationuuid) == updated
    assert db.station_notes(updated)["notes"] == "happy tunes"


def test_notes_follow_url_aliases_and_can_be_edited_or_cleared_from_any_alias(db, station):
    db.save_station_notes(station, "happy tunes", "upbeat")
    alias = replace(station, stationuuid="alias", name="Alternative name", votes=999)
    db.upsert([alias])
    assert db.station_notes(alias) == {"notes": "happy tunes", "tags": "upbeat"}
    assert db.search(parse_query("happy"))[0][0].stationuuid == "alias"
    db.save_station_notes(alias, "relaxing tunes", "calm")
    assert db.station_notes(station) == {"notes": "relaxing tunes", "tags": "calm"}
    assert db.search(parse_query("happy"))[1] == 0
    assert db.search(parse_query("relaxing"))[1] == 1
    db.save_station_notes(station, "", "")
    assert db.station_notes(alias) == {"notes": "", "tags": ""}
    assert db.search(parse_query("relaxing|calm"))[1] == 0


def test_notes_preserve_both_records_when_directory_merges_streams(db, station):
    other = db.station("two")
    db.save_station_notes(station, "happy tunes", "upbeat")
    db.save_station_notes(other, "Evening show", "work")
    merged = replace(other, url=station.url)
    db.upsert([merged])
    assert db.station_notes(merged) == {
        "notes": "happy tunes\n\nEvening show", "tags": "upbeat, work",
    }
    details = db.station_notes(merged)
    db.save_station_notes(merged, **details)
    assert db.station_notes(station) == details


def test_empty_urls_and_different_stream_variants_keep_separate_notes(db, station):
    variants = [
        replace(station, stationuuid="aac", url=station.url + ".aac"),
        replace(station, stationuuid="empty-one", url=""),
        replace(station, stationuuid="empty-two", url=""),
    ]
    db.upsert(variants)
    db.save_station_notes(station, "happy")
    db.save_station_notes(variants[1], "quiet")
    assert db.station_notes(variants[0])["notes"] == ""
    assert db.station_notes(variants[2])["notes"] == ""
    assert db.search(parse_query("happy"))[1] == 1
    assert db.search(parse_query("quiet"))[1] == 1


def test_existing_databases_gain_notes_and_literal_input_is_safe(db, station):
    db.toggle_favourite(station)
    db.add_history(station)
    with db.connect() as connection:
        connection.execute("DROP TABLE station_notes")
    db = Database(db.path)
    assert db.station_notes(station) == {"notes": "", "tags": ""}
    db.save_station_notes(station, "100%_FM\n' OR 1=1 --\x1b", "work, work, , Happy")
    assert db.station_notes(station) == {
        "notes": "100%_FM\n' OR 1=1 --", "tags": "work, Happy",
    }
    assert db.search(Search(terms=("%_",)))[1] == 1
    assert db.search(Search(terms=("' OR 1=1 --",)))[1] == 1
    assert station.stationuuid in db.favourite_ids()
    assert db.search(Search(), "history")[1] == 1


@pytest.mark.parametrize("notes,tags", [("x" * 20_001, ""), ("", "x" * 1_001)])
def test_oversized_notes_preserve_saved_content(db, station, notes, tags):
    db.save_station_notes(station, "keep me")
    with pytest.raises(ValueError, match="20,000"):
        db.save_station_notes(station, notes, tags)
    assert db.station_notes(station)["notes"] == "keep me"
