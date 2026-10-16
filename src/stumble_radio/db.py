import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .discovery import (
    DEAD_COOLDOWN,
    HOT_SECONDS,
    QUICK_SKIP_SECONDS,
    SKIP_COOLDOWN,
    diversity_score,
    shuffle_key,
)
from .models import Search, Station, clean, distance_km
from .query import search_from_tokens
from .tracks import Track

PAGE_SIZE = 100
TRACK_RETENTION_SECONDS = 365 * 24 * 60 * 60
STATION_COLUMNS = tuple(Station.__dataclass_fields__)
FOLD_COLUMNS = ("name", "country", "state", "language", "tags", "codec")
STREAM_KEY = "coalesce(nullif(s.url,''),s.stationuuid)"
AFFINITY_JOIN = f"""LEFT JOIN (
    SELECT {STREAM_KEY} stream_key, sum(a.listened_seconds) listened_seconds,
        sum(a.plays) plays, max(a.blocked_until) blocked_until
    FROM affinity a JOIN stations s USING(stationuuid) GROUP BY {STREAM_KEY}
) a ON a.stream_key={STREAM_KEY}"""


class Database:
    """Short-lived connections keep worker threads isolated; WAL lets searches overlap sync."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            columns = ", ".join(
                f"{key} {'REAL' if key.startswith('geo_') else 'INTEGER' if key in {'bitrate', 'votes', 'clickcount', 'lastcheckok'} else 'TEXT'}"
                for key in STATION_COLUMNS
                if key != "stationuuid"
            )
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS stations (
                    stationuuid TEXT PRIMARY KEY, {columns},
                    in_catalog INTEGER NOT NULL DEFAULT 1,
                    sync_token TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS stations_country ON stations(countrycode);
                CREATE INDEX IF NOT EXISTS stations_plays ON stations(clickcount DESC);
                CREATE INDEX IF NOT EXISTS stations_votes ON stations(votes DESC);
                CREATE INDEX IF NOT EXISTS stations_url ON stations(url);
                CREATE TABLE IF NOT EXISTS favourites (
                    stationuuid TEXT PRIMARY KEY REFERENCES stations(stationuuid),
                    added_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, stationuuid TEXT REFERENCES stations(stationuuid),
                    played_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_station ON history(stationuuid);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS station_notes (
                    stationuuid TEXT PRIMARY KEY REFERENCES stations(stationuuid),
                    notes TEXT NOT NULL, tags TEXT NOT NULL,
                    search_fold TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS affinity (
                    stationuuid TEXT PRIMARY KEY REFERENCES stations(stationuuid),
                    listened_seconds REAL NOT NULL DEFAULT 0,
                    plays INTEGER NOT NULL DEFAULT 0,
                    quick_skips INTEGER NOT NULL DEFAULT 0,
                    blocked_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS track_plays (
                    id INTEGER PRIMARY KEY,
                    stationuuid TEXT NOT NULL REFERENCES stations(stationuuid),
                    station_name TEXT NOT NULL, country TEXT NOT NULL,
                    artist TEXT NOT NULL, title TEXT NOT NULL, raw TEXT NOT NULL,
                    played_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS track_plays_time ON track_plays(played_at DESC,id DESC);
                CREATE VIRTUAL TABLE IF NOT EXISTS track_plays_fts USING fts5(
                    artist, title, raw, station_name,
                    content='track_plays', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2', prefix='2 3 4'
                );
                CREATE TRIGGER IF NOT EXISTS track_plays_insert AFTER INSERT ON track_plays BEGIN
                    INSERT INTO track_plays_fts(rowid,artist,title,raw,station_name)
                    VALUES (new.id,new.artist,new.title,new.raw,new.station_name);
                END;
                CREATE TRIGGER IF NOT EXISTS track_plays_delete AFTER DELETE ON track_plays BEGIN
                    INSERT INTO track_plays_fts(track_plays_fts,rowid,artist,title,raw,station_name)
                    VALUES ('delete',old.id,old.artist,old.title,old.raw,old.station_name);
                END;
            """)
            db.execute(
                "DELETE FROM track_plays WHERE played_at < ?",
                (time.time() - TRACK_RETENTION_SECONDS,),
            )
            history_columns = {row[1] for row in db.execute("PRAGMA table_info(history)")}
            for column, declaration in (
                ("listened_seconds", "REAL NOT NULL DEFAULT 0"),
                ("end_reason", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in history_columns:
                    db.execute(f"ALTER TABLE history ADD COLUMN {column} {declaration}")
            db.execute(
                "INSERT OR IGNORE INTO affinity(stationuuid,listened_seconds,plays) "
                "SELECT stationuuid,sum(listened_seconds),count(*) FROM history GROUP BY stationuuid"
            )
            existing = {row[1] for row in db.execute("PRAGMA table_info(stations)")}
            # Fold once on import rather than invoking Python for every row on every search.
            for column in FOLD_COLUMNS:
                if f"{column}_fold" not in existing:
                    db.execute(
                        f"ALTER TABLE stations ADD COLUMN {column}_fold TEXT NOT NULL DEFAULT ''"
                    )
                    db.execute(f"UPDATE stations SET {column}_fold=casefold({column})")
            db.executescript("""
                CREATE INDEX IF NOT EXISTS stations_catalogue ON stations(in_catalog);
                CREATE INDEX IF NOT EXISTS stations_popular_working
                    ON stations(clickcount DESC,stationuuid) WHERE in_catalog=1 AND lastcheckok=1;
                CREATE INDEX IF NOT EXISTS stations_name ON stations(name_fold,stationuuid);
                CREATE INDEX IF NOT EXISTS stations_country_name ON stations(country_fold);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.create_function("casefold", 1, lambda x: (x or "").casefold(), deterministic=True)
        db.create_function("distance_km", 4, distance_km, deterministic=True)
        db.create_function("shuffle_key", 1, shuffle_key)
        try:
            with db:
                yield db
        finally:
            db.close()

    def metadata(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def set_metadata(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, value))

    def upsert(
        self,
        stations: list[Station],
        *,
        sync_token: str | None = None,
        next_offset: int | None = None,
        reactivate: bool = True,
    ) -> None:
        all_columns = (*STATION_COLUMNS, *(f"{c}_fold" for c in FOLD_COLUMNS))
        columns = ",".join(all_columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in all_columns if c != "stationuuid")
        if sync_token is not None:
            updates += ",sync_token=excluded.sync_token"
        if reactivate:
            updates += ",in_catalog=1"
        with self.connect() as db:
            db.executemany(
                f"INSERT INTO stations ({columns},sync_token) VALUES ({','.join('?' for _ in range(len(all_columns) + 1))}) "
                f"ON CONFLICT(stationuuid) DO UPDATE SET {updates}",
                [
                    (
                        *asdict(s).values(),
                        *(getattr(s, c).casefold() for c in FOLD_COLUMNS),
                        sync_token or "",
                    )
                    for s in stations
                ],
            )
            if next_offset is not None:
                db.executemany(
                    "INSERT OR REPLACE INTO metadata VALUES (?,?)",
                    [("sync_offset", str(next_offset)), ("sync_token", sync_token)],
                )

    def finish_sync(self, token: str) -> None:
        with self.connect() as db:
            # Keep personal library records even if the directory removes the station.
            db.execute("UPDATE stations SET in_catalog=0 WHERE sync_token != ?", (token,))
            db.executemany(
                "INSERT OR REPLACE INTO metadata VALUES (?,?)",
                [("last_sync", str(time.time())), ("sync_offset", "0"), ("sync_token", "")],
            )

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM stations WHERE in_catalog=1").fetchone()[0]

    def station(self, stationuuid: str) -> Station | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM stations WHERE stationuuid=?", (stationuuid,)
            ).fetchone()
            return Station(**{key: row[key] for key in STATION_COLUMNS}) if row else None

    def station_notes(self, station: Station) -> dict[str, str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT n.notes,n.tags FROM station_notes n JOIN stations s USING(stationuuid) "
                "WHERE s.stationuuid=? OR (s.url!='' AND s.url="
                "(SELECT url FROM stations WHERE stationuuid=?)) "
                "ORDER BY n.updated_at,n.stationuuid",
                (station.stationuuid, station.stationuuid),
            ).fetchall()
        return {
            "notes": "\n\n".join(dict.fromkeys(row["notes"] for row in rows if row["notes"])),
            "tags": ", ".join(dict.fromkeys(
                tag.strip() for row in rows for tag in row["tags"].split(",") if tag.strip()
            )),
        }

    def save_station_notes(self, station: Station, notes: str, tags: str = "") -> None:
        if len(notes) > 20_000 or len(tags) > 1_000:
            raise ValueError("Use at most 20,000 characters for notes and 1,000 for personal tags.")
        notes = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", notes).strip()
        tags = ", ".join(dict.fromkeys(tag.strip() for tag in clean(tags).split(",") if tag.strip()))
        if self.station(station.stationuuid) is None:
            self.upsert([station], reactivate=False)
        with self.connect() as db:
            # Notes follow the same exact-URL groups as favourites, including a new representative.
            db.execute(
                "DELETE FROM station_notes WHERE stationuuid IN "
                "(SELECT stationuuid FROM stations WHERE stationuuid=? OR (url!='' AND "
                "url=(SELECT url FROM stations WHERE stationuuid=?)))",
                (station.stationuuid, station.stationuuid),
            )
            if notes or tags:
                db.execute(
                    "INSERT INTO station_notes VALUES (?,?,?,?,?)",
                    (station.stationuuid, notes, tags, (notes + "\n" + tags).casefold(), time.time()),
                )

    def add_track(self, station: Station, track: Track, *, played_at: float | None = None) -> int:
        with self.connect() as db:
            result = db.execute(
                "INSERT INTO track_plays(stationuuid,station_name,country,artist,title,raw,played_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    station.stationuuid,
                    station.name,
                    station.country,
                    track.artist,
                    track.title,
                    track.raw,
                    time.time() if played_at is None else played_at,
                ),
            )
            return result.lastrowid

    def search_tracks(self, query: str = "", offset: int = 0) -> tuple[list[dict], int]:
        # Quote each word: user punctuation and FTS operators are never executable syntax.
        words = re.findall(r"[^\W_]+", query, re.UNICODE)[:32]
        match = " AND ".join(f'"{word}"*' for word in words)
        if query.strip() and not words:
            return [], 0
        join = " JOIN track_plays_fts ON track_plays_fts.rowid=t.id" if match else ""
        where = " WHERE t.played_at >= ?"
        params = [time.time() - TRACK_RETENTION_SECONDS]
        if match:
            where += " AND track_plays_fts MATCH ?"
            params.append(match)
        with self.connect() as db:
            total = db.execute(
                "SELECT count(*) FROM track_plays t" + join + where, params
            ).fetchone()[0]
            rows = db.execute(
                "SELECT t.* FROM track_plays t"
                + join
                + where
                + " ORDER BY t.played_at DESC,t.id DESC LIMIT ? OFFSET ?",
                [*params, PAGE_SIZE, max(0, offset)],
            ).fetchall()
            return [dict(row) for row in rows], total

    def prune_tracks(self, *, now: float | None = None) -> int:
        with self.connect() as db:
            return db.execute(
                "DELETE FROM track_plays WHERE played_at < ?",
                ((time.time() if now is None else now) - TRACK_RETENTION_SECONDS,),
            ).rowcount

    @staticmethod
    def _url_members(table: str, condition: str = "1") -> str:
        # Only internal table names/conditions reach this helper.
        return (
            f"(s.stationuuid IN (SELECT stationuuid FROM {table} WHERE {condition}) OR "
            f"(s.url!='' AND s.url IN (SELECT member.url FROM {table} "
            f"JOIN stations member USING(stationuuid) WHERE {condition})))"
        )

    @staticmethod
    def _unique_stations(where: str, *, discovery: bool = False, sort_value: str = "0") -> str:
        affinity = ",a.listened_seconds url_seconds,a.plays url_plays" if discovery else ""
        join = AFFINITY_JOIN if discovery else ""
        # Keep sorting narrow; load full station details only after selecting a page.
        return f"""WITH matching AS (
            SELECT s.stationuuid, {STREAM_KEY} stream_key, s.lastcheckok,s.votes,
                EXISTS(SELECT 1 FROM favourites f WHERE f.stationuuid=s.stationuuid) saved_record,
                {Database._url_members("favourites")} saved, {sort_value} sort_value {affinity}
            FROM stations s {join} WHERE {where}
        ), ranked AS (
            SELECT s.*,row_number() OVER (PARTITION BY s.stream_key
                ORDER BY s.lastcheckok DESC,s.saved_record DESC,s.votes DESC,s.stationuuid) url_rank
            FROM matching s
        ), unique_stations AS (SELECT * FROM ranked WHERE url_rank=1) """

    @staticmethod
    def _where(search: Search, mode: str) -> tuple[str, list]:
        clauses, params = [], []
        if mode == "predicate":
            pass
        elif mode == "favourites":
            clauses.append(Database._url_members("favourites"))
        elif mode == "history":
            clauses.append(Database._url_members("history"))
        else:
            clauses.append("s.in_catalog=1")
            if search.hidebroken:
                clauses.append("s.lastcheckok=1")
            if mode == "unheard":
                clauses.append("NOT " + Database._url_members("affinity", "plays>0"))
        for key in ("name", "state", "language", "codec"):
            if value := getattr(search, key).strip():
                clauses.append(f"instr(s.{key}_fold,?) > 0")
                params.append(value.casefold())
        for term in search.terms:
            personal = Database._url_members("station_notes", "instr(search_fold,?)>0")
            clauses.append(f"(instr(s.name_fold,?)>0 OR instr(s.tags_fold,?)>0 OR {personal})")
            params.extend((term.casefold(),) * 4)
        if search.expression:
            sql, arguments = Database._expression_where(search.expression)
            clauses.append(sql)
            params.extend(arguments)
        if search.country:
            if len(search.country) == 2:
                clauses.append("s.countrycode=?")
                params.append(search.country.upper())
            else:
                clauses.append("s.country_fold=?")
                params.append(search.country.casefold())
        for tag in search.tags.split(","):
            if tag.strip():
                clauses.append("instr(',' || s.tags_fold || ',', ?) > 0")
                params.append("," + tag.strip().casefold() + ",")
        if search.bitrate_min:
            clauses.append("s.bitrate>=?")
            params.append(search.bitrate_min)
        if search.bitrate_max:
            clauses.append("s.bitrate<=?")
            params.append(search.bitrate_max)
        if search.https_only:
            clauses.append("s.url LIKE 'https://%'")
        if search.latitude is not None:
            clauses.append(
                "s.geo_lat IS NOT NULL AND s.geo_long IS NOT NULL "
                "AND distance_km(?,?,s.geo_lat,s.geo_long)<=?"
            )
            params.extend((search.latitude, search.longitude, search.radius_km))
        return " AND ".join(clauses) or "1", params

    @staticmethod
    def _expression_where(node: tuple) -> tuple[str, list]:
        if node[0] == "leaf":
            return Database._where(search_from_tokens([node[1]]), "predicate")
        clauses, params = [], []
        for child in node[1:]:
            sql, arguments = Database._expression_where(child)
            clauses.append(f"({sql})")
            params.extend(arguments)
        return "(" + (" OR " if node[0] == "or" else " AND ").join(clauses) + ")", params

    def search(
        self,
        search: Search,
        mode: str = "browse",
        offset: int = 0,
        limit: int = PAGE_SIZE,
        random: bool = False,
    ) -> tuple[list[Station], int]:
        where, params = self._where(search, mode)
        sort_value = f"s.{search.order}"
        order = f"s.sort_value {'DESC' if search.descending else 'ASC'},s.stationuuid"
        if search.order == "listen":
            # Listen time is grouped by URL like favourites themselves; it is only
            # meaningful in the favourites library, other modes keep the default.
            sort_value = (
                "(SELECT coalesce(sum(a2.listened_seconds),0) FROM affinity a2 "
                "JOIN stations m2 ON a2.stationuuid=m2.stationuuid "
                "WHERE m2.stationuuid=s.stationuuid OR (s.url!='' AND m2.url=s.url))"
                if mode == "favourites"
                else "s.clickcount"
            )
        if search.order in {"name", "country", "tags"}:
            sort_value += "_fold"
        if search.order == "favourite":
            sort_value = "s.name_fold"
            order = f"s.saved {'DESC' if search.descending else 'ASC'},s.sort_value,s.stationuuid"
        if search.order == "recent":
            sort_value = (
                "(SELECT max(h.played_at) FROM history h JOIN stations played USING(stationuuid) "
                "WHERE played.stationuuid=s.stationuuid OR (s.url!='' AND played.url=s.url))"
            )
        if random:
            sort_value, order = "random()", "s.sort_value,s.stationuuid"
        elif search.order != "favourite":
            order = "s.saved DESC," + order
        with self.connect() as db:
            count = db.execute(
                f"SELECT count(DISTINCT {STREAM_KEY}) FROM stations s WHERE {where}", params
            ).fetchone()[0]
            rows = db.execute(
                self._unique_stations(where, sort_value=sort_value)
                + f", page AS (SELECT * FROM unique_stations s ORDER BY {order} LIMIT ? OFFSET ?) "
                + "SELECT station.* FROM page s JOIN stations station USING(stationuuid) "
                + f"ORDER BY {order}",
                [*params, limit, offset],
            ).fetchall()
            return [Station(**{c: row[c] for c in STATION_COLUMNS}) for row in rows], count

    def favourite_ids(self) -> set[str]:
        with self.connect() as db:
            return {
                row[0]
                for row in db.execute(
                    "SELECT s.stationuuid FROM stations s WHERE " + self._url_members("favourites")
                )
            }

    def listen_totals(self, stations: list[Station]) -> dict[str, float]:
        """Accumulated listen seconds per URL-group for the given (favourite) rows."""
        uuids = list(dict.fromkeys(s.stationuuid for s in stations))
        urls = list(dict.fromkeys(s.url for s in stations if s.url))
        if not uuids:
            return {}
        id_ph = ",".join("?" for _ in uuids)
        url_sql = ""
        params: list = [*uuids]
        if urls:
            url_sql = f" OR (s.url!='' AND s.url IN ({','.join('?' for _ in urls)}))"
            params += urls
        with self.connect() as db:
            return {
                row["stream_key"]: row["seconds"]
                for row in db.execute(
                    "SELECT coalesce(nullif(s.url,''),s.stationuuid) stream_key, "
                    "coalesce(sum(b.listened_seconds),0) seconds FROM stations s "
                    "LEFT JOIN affinity b USING(stationuuid) "
                    f"WHERE s.stationuuid IN ({id_ph}){url_sql} GROUP BY stream_key",
                    params,
                ).fetchall()
            }

    def listen_seconds_for(self, station: Station) -> float:
        with self.connect() as db:
            row = db.execute(
                "SELECT sum(b.listened_seconds) FROM stations s "
                "LEFT JOIN affinity b USING(stationuuid) "
                "WHERE s.stationuuid=? OR (s.url!='' AND s.url=?)",
                (station.stationuuid, station.url),
            ).fetchone()
        return row[0] or 0.0

    def toggle_favourite(self, station: Station) -> bool:
        self.upsert([station], reactivate=False)
        with self.connect() as db:
            deleted = db.execute(
                "DELETE FROM favourites WHERE stationuuid IN "
                "(SELECT stationuuid FROM stations WHERE stationuuid=? OR (url!='' AND url=?))",
                (station.stationuuid, station.url),
            )
            if deleted.rowcount:
                return False
            db.execute("INSERT INTO favourites VALUES (?,?)", (station.stationuuid, time.time()))
            return True

    def add_history(self, station: Station) -> int:
        self.upsert([station], reactivate=False)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO history(stationuuid,played_at) VALUES (?,?)",
                (station.stationuuid, time.time()),
            )
            db.execute(
                "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 5000)"
            )
            db.execute(
                "INSERT INTO affinity(stationuuid,plays) VALUES (?,1) "
                "ON CONFLICT(stationuuid) DO UPDATE SET plays=plays+1",
                (station.stationuuid,),
            )
            return cursor.lastrowid

    def save_listening(self, history_id: int, seconds: float, reason: str = "") -> None:
        with self.connect() as db:
            row = db.execute(
                "SELECT stationuuid,listened_seconds,end_reason FROM history WHERE id=?",
                (history_id,),
            ).fetchone()
            if not row or row["end_reason"]:
                return
            seconds = max(row["listened_seconds"], seconds)
            delta = seconds - row["listened_seconds"]
            quick_skip = reason == "skip" and seconds < QUICK_SKIP_SECONDS
            db.execute(
                "UPDATE history SET listened_seconds=?,end_reason=? WHERE id=?",
                (seconds, reason, history_id),
            )
            db.execute(
                "UPDATE affinity SET listened_seconds=listened_seconds+?, "
                "quick_skips=quick_skips+?, blocked_until=CASE WHEN ? THEN ? "
                "WHEN ?>=? THEN 0 ELSE blocked_until END WHERE stationuuid=?",
                (
                    delta,
                    int(quick_skip),
                    int(quick_skip),
                    time.time() + SKIP_COOLDOWN,
                    seconds,
                    HOT_SECONDS,
                    row["stationuuid"],
                ),
            )
            if seconds >= HOT_SECONDS:
                db.execute(
                    "UPDATE affinity SET blocked_until=0 WHERE stationuuid IN "
                    "(SELECT alias.stationuuid FROM stations alias JOIN stations played "
                    "ON alias.url=played.url WHERE played.stationuuid=? AND played.url!='')",
                    (row["stationuuid"],),
                )

    def mark_dead(self, station: Station) -> None:
        self.upsert([station], reactivate=False)
        with self.connect() as db:
            db.execute(
                "INSERT INTO affinity(stationuuid,blocked_until) VALUES (?,?) "
                "ON CONFLICT(stationuuid) DO UPDATE SET blocked_until=excluded.blocked_until",
                (station.stationuuid, time.time() + DEAD_COOLDOWN),
            )

    @staticmethod
    def _discovery_where(search: Search, mode: str, pool: str, exclude: tuple[str, ...]):
        where, params = Database._where(search, mode)
        where += " AND coalesce(a.blocked_until,0)<=?"
        params.append(time.time())
        if exclude:
            placeholders = ",".join("?" for _ in exclude)
            where += (
                f" AND s.stationuuid NOT IN ({placeholders}) AND (s.url='' OR s.url NOT IN "
                f"(SELECT url FROM stations WHERE stationuuid IN ({placeholders})))"
            )
            params.extend(exclude)
            params.extend(exclude)
        talk = (
            "("
            + " OR ".join(
                f"instr(s.tags_fold,'{tag}')>0" for tag in ("talk", "news", "speech", "sports")
            )
            + ")"
        )
        if pool == "Talk/News":
            where += " AND " + talk
        elif pool == "Music-only":
            music = (
                "music",
                "jazz",
                "blues",
                "rock",
                "pop",
                "classical",
                "electronic",
                "dance",
                "hip hop",
                "hip-hop",
                "country",
                "soul",
                "funk",
                "reggae",
                "metal",
                "ambient",
                "folk",
                "house",
                "techno",
                "trance",
                "rnb",
                "r&b",
                "oldies",
                "hits",
                "disco",
            )
            where += (
                " AND NOT "
                + talk
                + " AND ("
                + " OR ".join(f"instr(s.tags_fold,'{tag}')>0" for tag in music)
                + ")"
            )
        return where, params

    def discover(
        self,
        search: Search,
        mode: str = "browse",
        pool: str = "Anywhere",
        exclude: tuple[str, ...] = (),
        limit: int = 8,
    ) -> list[Station]:
        where, params = self._discovery_where(search, mode, pool, exclude)
        with self.connect() as db:
            rows = db.execute(
                self._unique_stations(where, discovery=True)
                + ", page AS (SELECT *,shuffle_key(coalesce(url_seconds,0)) weight "
                "FROM unique_stations ORDER BY weight,stationuuid LIMIT ?) "
                "SELECT s.* FROM page p JOIN stations s USING(stationuuid) ORDER BY p.weight,p.stationuuid",
                [*params, limit],
            ).fetchall()
            return [Station(**{c: row[c] for c in STATION_COLUMNS}) for row in rows]

    def countries(
        self, search: Search, mode: str = "browse", pool: str = "Anywhere"
    ) -> list[tuple[str, str]]:
        where, params = self._discovery_where(search, mode, pool, ())
        with self.connect() as db:
            return [
                tuple(row)
                for row in db.execute(
                    f"SELECT s.countrycode,min(s.country) FROM stations s {AFFINITY_JOIN} "
                    f"WHERE {where} AND s.countrycode!='' GROUP BY s.countrycode ORDER BY s.countrycode",
                    params,
                )
            ]

    def journal(self) -> dict:
        with self.connect() as db:
            totals = db.execute(
                "SELECT coalesce(sum(listened_seconds),0),coalesce(sum(plays),0) FROM affinity"
            ).fetchone()
            top = [
                dict(r)
                for r in db.execute(
                    self._unique_stations("1", discovery=True)
                    + ", top AS (SELECT * FROM unique_stations WHERE url_seconds>0 "
                    "ORDER BY url_seconds DESC,stationuuid LIMIT 10) "
                    "SELECT s.name,s.country,t.url_seconds listened_seconds,t.url_plays plays "
                    "FROM top t JOIN stations s USING(stationuuid) "
                    "ORDER BY t.url_seconds DESC,s.name"
                )
            ]
            passport = [
                dict(r)
                for r in db.execute(
                    "SELECT s.country,s.countrycode,sum(a.listened_seconds) seconds FROM affinity a "
                    "JOIN stations s USING(stationuuid) WHERE a.listened_seconds>0 AND s.countrycode!='' "
                    "GROUP BY s.countrycode ORDER BY seconds DESC"
                )
            ]
            genres = {}
            for row in db.execute(
                "SELECT s.tags,a.listened_seconds FROM affinity a JOIN stations s USING(stationuuid) WHERE a.listened_seconds>0"
            ):
                tags = {tag.strip().casefold() for tag in row["tags"].split(",") if tag.strip()}
                for tag in tags:
                    genres[tag] = genres.get(tag, 0) + row["listened_seconds"] / len(tags)
            recent = [
                dict(r)
                for r in db.execute(
                    "SELECT s.name,s.country,h.played_at,h.listened_seconds,h.end_reason FROM history h "
                    "JOIN stations s USING(stationuuid) ORDER BY h.id DESC LIMIT 100"
                )
            ]
            return {
                "seconds": totals[0],
                "plays": totals[1],
                "top": top,
                "passport": passport,
                "country_diversity": diversity_score([r["seconds"] for r in passport]),
                "genre_diversity": diversity_score(list(genres.values())),
                "recent": recent,
            }
