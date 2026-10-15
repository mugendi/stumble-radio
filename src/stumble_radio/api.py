import asyncio
import random
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

from .db import Database
from .models import Search, Station
from .query import search_from_tokens

BOOTSTRAP = "https://all.api.radio-browser.info"
USER_AGENT = "StumbleRadio/0.1.0"
SYNC_INTERVAL = 24 * 60 * 60
SYNC_PAGE = 1000


def _term_queries(term: str, params: dict) -> list[dict]:
    return [{**params, "name": term}, {**params, "tag": term}]


def _expression_queries(node: tuple, params: dict) -> list[dict]:
    if node[0] == "leaf":
        leaf = search_from_tokens([node[1]])
        if leaf.terms:
            return _term_queries(leaf.terms[0], params)
        extra = {
            key: value
            for key, value in leaf.api_params().items()
            if key not in {"order", "reverse", "hidebroken"} and value != 0
        }
        return [{**params, **extra}]
    alternatives = [_expression_queries(child, params) for child in node[1:]]
    if node[0] == "and":
        return min(alternatives, key=len)
    return [query for group in alternatives for query in group]


class DirectoryError(Exception):
    pass


class RadioBrowser:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=True,
        )
        self.servers: list[str] = []
        self.discovery_time = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def discover(self) -> None:
        if self.servers and time.monotonic() - self.discovery_time < 3600:
            return
        try:
            response = await self.client.get(
                f"{BOOTSTRAP}/json/servers", headers={"User-Agent": USER_AGENT}
            )
            response.raise_for_status()
            servers = [
                f"https://{s['name']}"
                for s in response.json()
                if isinstance(s, dict)
                and isinstance(s.get("name"), str)
                and s["name"].endswith(".api.radio-browser.info")
                and all(c.isalnum() or c in ".-" for c in s["name"])
            ]
            if servers:
                random.shuffle(servers)
                self.servers = servers
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        self.servers = self.servers or [BOOTSTRAP]
        self.discovery_time = time.monotonic()

    async def request(self, endpoint: str, params: dict | None = None):
        await self.discover()
        last_error = None
        hosts = list(dict.fromkeys([*self.servers, BOOTSTRAP]))[:3]
        for host in hosts:
            try:
                response = await self.client.get(
                    f"{host}/json/{endpoint}", params=params, headers={"User-Agent": USER_AGENT}
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
        self.discovery_time = 0
        raise DirectoryError(
            "Radio Browser is unreachable. Cached stations are still available."
        ) from last_error

    async def search(
        self, search: Search, *, offset: int = 0, limit: int = 100, random_order: bool = False
    ) -> list[Station]:
        params = {**search.api_params(), "offset": offset, "limit": limit}
        if random_order:
            params["order"] = "random"
        queries = _expression_queries(search.expression, params) if search.expression else [params]
        if search.terms and not search.name:
            term_queries = _term_queries(search.terms[0], params)
            if not search.expression or len(term_queries) < len(queries):
                queries = term_queries
        if search.name or len(queries) > 8:
            queries = [params]
        queries = list({tuple(sorted(query.items())): query for query in queries}.values())
        if len(queries) > 1 or queries[0] != params:
            # Fetch bounded supersets; SQLite applies the complete boolean expression.
            await self.discover()
            pages = await asyncio.gather(*(self.stations(query) for query in queries))
            return list(
                {station.stationuuid: station for page in pages for station in page}.values()
            )
        return await self.stations(params)

    async def stations(self, params: dict) -> list[Station]:
        rows = await self.request("stations/search", params)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DirectoryError("Radio Browser returned an invalid station list.")
        result = []
        for row in rows:
            try:
                result.append(Station.from_api(row))
            except ValueError as error:
                raise DirectoryError("Radio Browser returned a station without an ID.") from error
        return result

    async def register_play(self, station: Station) -> None:
        try:
            await self.request(f"url/{quote(station.stationuuid, safe='')}")
        except DirectoryError:
            pass


async def sync_catalogue(api: RadioBrowser, db: Database, progress=None, *, force=False) -> bool:
    """Checkpoint each batch so a short listening session still builds the cache."""
    last_sync = float(await asyncio.to_thread(db.metadata, "last_sync", "0"))
    if not force and time.time() - last_sync < SYNC_INTERVAL:
        return False
    token = await asyncio.to_thread(db.metadata, "sync_token")
    offset = int(await asyncio.to_thread(db.metadata, "sync_offset", "0"))
    started = float(await asyncio.to_thread(db.metadata, "sync_started", "0"))
    if not token or time.time() - started > SYNC_INTERVAL:
        token, offset = uuid4().hex, 0
        await asyncio.to_thread(db.set_metadata, "sync_started", str(time.time()))
    while True:
        rows = await api.stations(
            {
                "limit": SYNC_PAGE,
                "offset": offset,
                "order": "name",
                "reverse": "false",
                "hidebroken": "false",
            }
        )
        offset += len(rows)
        await asyncio.to_thread(db.upsert, rows, sync_token=token, next_offset=offset)
        if progress:
            await progress()
        if len(rows) < SYNC_PAGE:
            await asyncio.to_thread(db.finish_sync, token)
            return True
        await asyncio.sleep(0.5)
