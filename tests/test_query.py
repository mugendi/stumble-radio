from dataclasses import replace

import pytest

from stumble_radio.models import Search
from stumble_radio.query import format_query, parse_query


@pytest.fixture
def radio_catalogue(db, station):
    db.upsert(
        [
            replace(
                station,
                stationuuid="slow",
                url="https://example.test/slow",
                name="Slow Tracks",
                tags="rock,blues",
                bitrate=192,
            ),
            replace(
                station,
                stationuuid="country-rock",
                url="https://example.test/country-rock",
                name="Highway Radio",
                tags="country,rock",
                bitrate=320,
            ),
            replace(
                station,
                stationuuid="pop",
                url="https://example.test/pop",
                name="Slow Pop",
                tags="pop",
                bitrate=64,
            ),
            replace(
                station,
                stationuuid="ug",
                url="https://example.test/ug",
                name="Uganda Rock",
                country="Uganda",
                countrycode="UG",
                tags="rock",
                bitrate=192,
            ),
        ]
    )
    return db


@pytest.mark.parametrize(
    "text,expected",
    [
        ("country|rock|blues country:kenya", {"one", "slow", "country-rock"}),
        ("country+rock country:kenya", {"country-rock"}),
        ("slow genre:rock", {"slow"}),
        ("rock county:kenya", {"slow", "country-rock"}),
        ("(slow|country)+rock country:KE", {"slow", "country-rock"}),
        ("country:KE|country:UG genre:rock", {"slow", "country-rock", "ug"}),
        ("genre:rock|genre:blues country:KE", {"one", "slow", "country-rock"}),
        ("slow+rock|news", {"slow", "two"}),
        ('name:"Slow Tracks" codec:MP3 bitrate:128..256 https:true', {"slow"}),
        ('country:"United Kingdom" genre:news language:english', {"two"}),
        ("lat:-1.29 lon:36.82 radius:50 country:KE", {"one", "slow", "country-rock", "pop"}),
        ("near:-1.29,36.82,50 country:KE genre:rock", {"slow", "country-rock"}),
    ],
)
def test_combinations_filter_the_whole_catalogue(radio_catalogue, text, expected):
    search = parse_query(text)
    rows, count = radio_catalogue.search(search)
    assert {s.stationuuid for s in rows} == expected and count == len(expected)
    assert parse_query(format_query(search)) == search


@pytest.mark.parametrize(
    "search",
    [
        Search(),
        Search(name="America's Country"),
        Search(terms=("classic rock",), country="United Kingdom", language="english"),
        Search(
            name='A "quoted" + (live) station',
            country="KE",
            tags="rock,blues",
            codec="AAC",
            bitrate_min=128,
            bitrate_max=320,
            https_only=True,
            hidebroken=False,
            latitude=-1.2921,
            longitude=36.8219,
            radius_km=50,
            order="votes",
            descending=False,
        ),
        Search(order="name", descending=True),
        Search(order="name", descending=False),
        Search(order="country", descending=False),
        Search(order="favourite", descending=False),
        Search(order="recent"),
        Search(terms=("Radio:Jazz",)),
    ],
)
def test_query_format_round_trip(search):
    assert parse_query(format_query(search)) == search


@pytest.mark.parametrize(
    "text",
    [
        "country:",
        'name:"unfinished',
        "county:KE country:UG",
        "typo:rock",
        "rock|",
        "+rock",
        "rock++blues",
        "(rock|blues",
        "rock)",
        "rock|()",
        "bitrate:wrong",
        "bitrate:320..128",
        "https:perhaps",
        "sort:injection",
        "direction:backwards",
        "lat:0",
        "near:nan,0,5",
        "sort:votes|rock",
        "broken:true|rock",
        "lat:0|rock",
        "x" * 4097,
    ],
)
def test_invalid_or_incomplete_queries_are_rejected(text):
    with pytest.raises(ValueError):
        parse_query(text)


def test_query_limits_and_sql_literals(radio_catalogue):
    with pytest.raises(ValueError):
        parse_query("(" * 17 + "rock" + ")" * 17)
    query = parse_query('text:"\' OR 1=1 --"|text:"%_" country:KE')
    assert radio_catalogue.search(query)[1] == 0
    assert radio_catalogue.count() == 6


def test_aliases_cover_advanced_form_fields():
    search = parse_query(
        "county:KE region:Nairobi lang:swahili tagList:jazz,blues "
        "bitrateMin:64 bitrateMax:320 https_only:yes hidebroken:no "
        "latitude:-1 longitude:36 radius_km:100 order:genre descending:no"
    )
    assert search == Search(
        country="KE",
        state="Nairobi",
        language="swahili",
        tags="jazz,blues",
        bitrate_min=64,
        bitrate_max=320,
        https_only=True,
        hidebroken=False,
        latitude=-1,
        longitude=36,
        radius_km=100,
        order="tags",
        descending=False,
    )


def test_favourites_stay_first_with_boolean_search(radio_catalogue):
    favourite = radio_catalogue.search(Search(name="Highway"))[0][0]
    radio_catalogue.toggle_favourite(favourite)
    rows, _ = radio_catalogue.search(parse_query("country|rock|blues country:KE sort:name"))
    assert rows[0].stationuuid == favourite.stationuuid


@pytest.mark.parametrize(
    "text", ["bitrate:128..320 minbitrate:256", "minbitrate:256 bitrate:128..320"]
)
def test_overlapping_bitrate_constraints_intersect_in_either_order(text):
    query = parse_query(text)
    assert (query.bitrate_min, query.bitrate_max) == (256, 320)


def test_conflicting_bitrate_constraints_are_rejected():
    with pytest.raises(ValueError):
        parse_query("bitrate:128 minbitrate:256")
