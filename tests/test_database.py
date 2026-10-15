from dataclasses import replace

import pytest

from stumble_radio.models import Search, Station, distance_km, stream_url


def test_combined_filters_and_sorts(db):
    rows, total = db.search(
        Search(
            country="KE",
            state="nai",
            language="swahili",
            tags="jazz,blues",
            codec="mp3",
            bitrate_min=128,
            bitrate_max=128,
            https_only=True,
        )
    )
    assert total == 1 and rows[0].name == "Nairobi Jazz"
    assert db.search(Search(order="votes"))[0][0].name == "London News"
    assert db.search(Search(country="Kenya"))[1] == 1
    assert db.search(Search(country="ken"))[1] == 0
    assert db.search(Search(tags="jazz,news"))[1] == 0
    assert db.search(Search(tags="jaz"))[1] == 0


def test_unicode_and_literal_input(db, station):
    db.upsert(
        [
            replace(
                station,
                stationuuid="unicode",
                url="https://example.test/unicode",
                name="Écho 100%_FM",
            )
        ]
    )
    assert db.search(Search(name="éCHO"))[1] == 1
    assert db.search(Search(name="%_"))[1] == 1
    assert db.search(Search(name="' OR 1=1 --"))[1] == 0
    assert db.count() == 3


def test_radius(db):
    rows, total = db.search(Search(latitude=-1.29, longitude=36.82, radius_km=50))
    assert total == 1 and rows[0].countrycode == "KE"
    assert distance_km(0, 179.99, 0, -179.99) < 3


def test_favourites_history_survive_sync_and_broken_checks(db, station):
    assert db.toggle_favourite(station)
    db.add_history(station)
    db.upsert([replace(station, lastcheckok=0)], sync_token="old")
    db.finish_sync("new")
    assert db.search(Search())[1] == 0
    assert db.search(Search(), "favourites")[1] == 1
    assert db.search(Search(), "history")[1] == 1
    assert db.search(Search(), "favourites")[0][0].lastcheckok == 0
    assert not db.toggle_favourite(station)
    assert not db.favourite_ids()


def test_unheard_and_unique_history(db, station):
    db.add_history(station)
    db.add_history(station)
    assert db.search(Search(), "history")[1] == 1
    rows, count = db.search(Search(), "unheard")
    assert count == 1 and rows[0].stationuuid == "two"


def test_upsert_preserves_sync_marker_and_checkpoint(db, station):
    db.upsert([station], sync_token="scan", next_offset=1000)
    db.upsert([replace(station, votes=100)])
    db.finish_sync("scan")
    assert db.search(Search())[1] == 1
    assert db.search(Search())[0][0].votes == 100
    assert db.metadata("sync_offset") == "0"


def test_pagination(db, station):
    db.upsert(
        [
            replace(station, stationuuid=str(i), url=f"https://example.test/{i}", votes=i)
            for i in range(210)
        ]
    )
    first, total = db.search(Search(order="votes"))
    second, _ = db.search(Search(order="votes"), offset=100)
    assert total == 212 and len(first) == len(second) == 100
    assert not {s.stationuuid for s in first} & {s.stationuuid for s in second}


@pytest.mark.parametrize(
    "order,descending,expected",
    [
        ("votes", True, ["one", "saved", "two"]),
        ("votes", False, ["saved", "one", "two"]),
        ("name", True, ["one", "saved", "two"]),
        ("name", False, ["saved", "one", "two"]),
    ],
)
def test_favourites_first_preserves_sort_within_groups(db, station, order, descending, expected):
    saved = replace(
        station, stationuuid="saved", url="https://example.test/saved", name="Alpha Jazz", votes=5
    )
    db.toggle_favourite(station)
    db.toggle_favourite(saved)
    rows, total = db.search(Search(order=order, descending=descending))
    assert total == 3
    assert [s.stationuuid for s in rows] == expected
    rows, total = db.search(Search(country="GB", order=order, descending=descending))
    assert total == 1 and rows[0].stationuuid == "two"


def test_favourites_priority_applies_before_pagination(db, station):
    db.upsert(
        [
            replace(station, stationuuid=str(i), url=f"https://example.test/{i}", votes=i + 100)
            for i in range(150)
        ]
    )
    db.toggle_favourite(station)
    first, total = db.search(Search(order="votes"))
    second, _ = db.search(Search(order="votes"), offset=100)
    assert total == 152 and first[0].stationuuid == station.stationuuid
    assert station.stationuuid not in {s.stationuuid for s in second}
    db.toggle_favourite(station)
    assert db.search(Search(order="votes"))[0][0].stationuuid == "149"


def test_history_also_puts_favourites_first(db, station):
    db.toggle_favourite(station)
    db.add_history(station)
    other = db.search(Search(country="GB"))[0][0]
    db.add_history(other)
    assert [s.stationuuid for s in db.search(Search(), mode="history")[0]] == ["one", "two"]


@pytest.mark.parametrize(
    "values",
    [
        {"order": "name; DROP TABLE stations"},
        {"bitrate_min": -1},
        {"bitrate_min": 320, "bitrate_max": 128},
        {"latitude": 0},
        {"latitude": 91, "longitude": 0, "radius_km": 5},
        {"latitude": 0, "longitude": 0, "radius_km": float("nan")},
        {"latitude": 0, "longitude": 0, "radius_km": 0},
    ],
)
def test_invalid_search(values):
    with pytest.raises(ValueError):
        Search(**values)


def test_api_null_fields_and_control_characters():
    station = Station.from_api(
        {
            "stationuuid": "id",
            "name": "\x1bHello\n",
            "votes": None,
            "bitrate": "bad",
            "geo_lat": "nan",
            "url_resolved": None,
            "url": "https://example.test/live",
        }
    )
    assert station.name == "Hello" and station.votes == station.bitrate == 0
    assert station.geo_lat is None and station.url.startswith("https://")
    with pytest.raises(ValueError):
        Station.from_api({})


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "--script=x",
        "https://",
        "javascript:x",
        "https://host:bad/live",
        "https://host:65536/live",
        "https://host:0/live",
    ],
)
def test_reject_non_network_streams(url):
    with pytest.raises(ValueError):
        stream_url(url)
