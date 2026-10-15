from dataclasses import replace

from stumble_radio.models import Search
from stumble_radio.query import parse_query


def test_representative_prefers_working_saved_then_votes(db, station):
    popular = replace(station, stationuuid="popular", votes=900)
    broken = replace(station, stationuuid="broken", votes=999, lastcheckok=0)
    db.upsert([popular, broken])
    rows, total = db.search(Search(hidebroken=False))
    assert total == 2
    assert next(s for s in rows if s.url == station.url).stationuuid == "popular"
    db.toggle_favourite(station)
    assert db.search(Search())[0][0].stationuuid == station.stationuuid
    with db.connect() as connection:
        connection.execute("UPDATE stations SET lastcheckok=0 WHERE stationuuid='one'")
    assert db.search(Search(hidebroken=False))[0][0].stationuuid == "popular"


def test_filter_before_grouping_and_shared_favourite(db, station):
    alias = replace(station, stationuuid="alias", name="Smooth FM", tags="soul", votes=1)
    db.upsert([alias])
    db.toggle_favourite(station)
    assert db.favourite_ids() == {"one", "alias"}
    rows, total = db.search(parse_query("soul"), "favourites")
    assert total == 1 and rows[0].stationuuid == "alias"
    assert db.search(Search(), "favourites")[1] == 1
    assert not db.toggle_favourite(alias)
    assert not db.favourite_ids()
    assert db.search(Search(), "favourites")[1] == 0


def test_url_groups_keep_variants_query_strings_and_missing_urls_distinct(db, station):
    db.upsert(
        [
            replace(station, stationuuid="aac", url=station.url + ".aac", codec="AAC+"),
            replace(station, stationuuid="token", url=station.url + "?channel=2"),
            replace(station, stationuuid="empty1", url=""),
            replace(station, stationuuid="empty2", url=""),
            replace(station, stationuuid="alias"),
        ]
    )
    assert db.search(Search())[1] == 6
    assert len(db.discover(Search(), limit=20)) == 6


def test_duplicates_do_not_fill_pages_or_bias_shuffle(db, station, monkeypatch):
    db.upsert(
        [replace(station, stationuuid=f"copy-{i}", votes=i) for i in range(120)]
        + [
            replace(station, stationuuid=f"other-{i}", url=f"https://example.test/{i}")
            for i in range(105)
        ]
    )
    first, total = db.search(Search())
    second, second_total = db.search(Search(), offset=100)
    assert total == second_total == 107
    assert len(first) == 100 and len(second) == 7
    assert len({s.url for s in first + second}) == 107
    calls = []

    def weight(seconds):
        calls.append(seconds)
        return 1

    monkeypatch.setattr("stumble_radio.db.shuffle_key", weight)
    assert len(db.discover(Search(), limit=200)) == 107
    assert len(calls) == 107


def test_shared_history_unheard_cooldown_exclusion_and_weights(db, station, monkeypatch):
    alias = replace(station, stationuuid="alias", votes=100)
    db.upsert([alias])
    visit = db.add_history(station)
    db.save_listening(visit, 3, "skip")
    assert db.search(Search(), "history")[1] == 1
    assert db.search(Search(), "unheard")[1] == 1
    assert len(db.discover(Search())) == 1
    assert db.countries(Search()) == [("GB", "United Kingdom")]
    with db.connect() as connection:
        connection.execute("UPDATE affinity SET blocked_until=0")
    assert len(db.discover(Search(), exclude=(station.stationuuid,))) == 1
    second = db.add_history(alias)
    db.save_listening(second, 120, "quit")
    weights = []
    monkeypatch.setattr(
        "stumble_radio.db.shuffle_key", lambda seconds: weights.append(seconds) or 1
    )
    db.discover(Search())
    assert sorted(weights) == [0, 123]
    assert db.journal()["top"] == [
        {"name": station.name, "country": station.country, "listened_seconds": 123, "plays": 2}
    ]
    db.mark_dead(alias)
    assert len(db.discover(Search())) == 1


def test_recent_order_uses_latest_visit_on_any_alias(db, station, monkeypatch):
    alias = replace(station, stationuuid="alias", votes=100)
    db.upsert([alias])
    other = db.station("two")
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: 100)
    db.add_history(station)
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: 200)
    db.add_history(other)
    assert [s.stationuuid for s in db.search(Search(order="recent"), "history")[0]] == [
        "two",
        "alias",
    ]
    monkeypatch.setattr("stumble_radio.db.time.time", lambda: 300)
    db.add_history(station)
    assert [s.stationuuid for s in db.search(Search(order="recent"), "history")[0]] == [
        "alias",
        "two",
    ]


def test_long_manual_listen_rehabilitates_all_cold_aliases(db, station):
    alias = replace(station, stationuuid="alias")
    db.upsert([alias])
    visit = db.add_history(station)
    db.save_listening(visit, 3, "skip")
    assert len(db.discover(Search())) == 1
    revisit = db.add_history(alias)
    db.save_listening(revisit, 65, "quit")
    assert len(db.discover(Search())) == 2
