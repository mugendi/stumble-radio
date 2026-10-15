from dataclasses import replace

import pytest

from stumble_radio.db import Database
from stumble_radio.models import Station


@pytest.fixture
def station():
    return Station(
        "one",
        name="Nairobi Jazz",
        url="https://example.test/live",
        country="Kenya",
        countrycode="KE",
        state="Nairobi",
        language="swahili,english",
        tags="jazz,blues",
        codec="MP3",
        bitrate=128,
        votes=10,
        clickcount=20,
        lastcheckok=1,
        geo_lat=-1.2921,
        geo_long=36.8219,
    )


@pytest.fixture
def db(tmp_path, station):
    database = Database(tmp_path / "radio.sqlite3")
    database.upsert(
        [
            station,
            replace(
                station,
                stationuuid="two",
                url="https://example.test/news",
                name="London News",
                country="United Kingdom",
                countrycode="GB",
                state="London",
                tags="news,talk",
                language="english",
                votes=30,
                geo_lat=51.5074,
                geo_long=-0.1278,
            ),
        ]
    )
    return database
