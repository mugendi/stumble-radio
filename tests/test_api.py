import time
from dataclasses import asdict

import httpx
import pytest

from stumble_radio import api as api_module
from stumble_radio.api import DirectoryError, RadioBrowser, sync_catalogue
from stumble_radio.models import Search
from stumble_radio.query import parse_query


async def test_discovery_and_failover(station):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["User-Agent"].startswith("StumbleRadio/")
        if request.url.path == "/json/servers":
            return httpx.Response(
                200,
                json=[
                    {"name": "bad.api.radio-browser.info"},
                    {"name": "good.api.radio-browser.info"},
                    {"name": "evil.example/path.api.radio-browser.info"},
                ],
            )
        if request.url.host.startswith("bad"):
            return httpx.Response(503)
        return httpx.Response(200, json=[asdict(station)])

    api = RadioBrowser(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.discover()
    api.servers = ["https://bad.api.radio-browser.info", "https://good.api.radio-browser.info"]
    rows = await api.search(
        Search(country="KE", tags="jazz", latitude=0, longitude=0, radius_km=50)
    )
    assert rows == [station]
    assert calls[-1].url.params["geo_distance"] == "50000"
    assert calls[-1].url.params["limit"] == "100"
    assert calls[-1].url.params["countrycode"] == "KE"
    assert calls[-1].url.params["hidebroken"] == "true"
    await api.close()


async def test_offline_mirrors_fail_cleanly():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    api = RadioBrowser(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DirectoryError, match="Cached stations"):
        await api.search(Search())
    await api.close()


async def test_malformed_response_not_cached():
    api = RadioBrowser(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"error": "oops"})
            )
        )
    )
    with pytest.raises(DirectoryError, match="invalid station list"):
        await api.search(Search())
    await api.close()


async def test_sync_checkpoint_resume_and_freshness(db, station, monkeypatch):
    monkeypatch.setattr(api_module, "SYNC_PAGE", 2)

    class FakeAPI:
        def __init__(self):
            self.offsets = []
            self.fail = True

        async def stations(self, params):
            assert params["hidebroken"] == "false"
            self.offsets.append(params["offset"])
            if params["offset"] == 0:
                return db.search(Search())[0]
            if self.fail:
                raise DirectoryError("interrupted")
            return []

    api = FakeAPI()
    with pytest.raises(DirectoryError):
        await sync_catalogue(api, db)
    assert db.metadata("sync_offset") == "2"
    assert db.count() == 2
    api.fail = False
    assert await sync_catalogue(api, db)
    assert api.offsets == [0, 2, 2]
    assert float(db.metadata("last_sync")) <= time.time()
    assert not await sync_catalogue(api, db)
    assert db.metadata("sync_offset") == "0"


async def test_invalid_rows_do_not_complete_sync(db):
    api = RadioBrowser(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=[{"name": "no ID"}])
            )
        )
    )
    with pytest.raises(DirectoryError):
        await sync_catalogue(api, db)
    assert db.count() == 2
    assert not db.metadata("last_sync")
    await api.close()


async def test_boolean_api_queries_are_bounded_deduplicated_candidate_pages(station):
    calls = []

    def handler(request):
        if request.url.path.endswith("servers"):
            return httpx.Response(200, json=[])
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[asdict(station)])

    api = RadioBrowser(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        rows = await api.search(
            parse_query("country|rock|blues country:kenya"), offset=100, limit=100
        )
        assert rows == [station]
        assert len(calls) == 6
        assert {r.get("name") or r.get("tag") for r in calls} == {"country", "rock", "blues"}
        assert all(
            r["country"] == "kenya" and r["limit"] == "100" and r["offset"] == "100" for r in calls
        )
        calls.clear()
        await api.search(parse_query("country:KE|country:UG genre:rock"))
        assert {r["countrycode"] for r in calls} == {"KE", "UG"}
        assert all(r["tagList"] == "rock" for r in calls)
        calls.clear()
        await api.search(parse_query("a|b|c|d|e"))
        assert len(calls) == 1
    finally:
        await api.close()
