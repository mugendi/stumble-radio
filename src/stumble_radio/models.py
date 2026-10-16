import math
import re
from dataclasses import dataclass, fields
from urllib.parse import urlsplit


def clean(value: object) -> str:
    """Directory text must not inject terminal control sequences."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value or "")).strip()


def stream_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.port == 0:
        raise ValueError("Station needs a valid HTTP(S) stream URL.")
    return value


def number(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def coordinate(value: object, bound: int) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and abs(result) <= bound else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Station:
    stationuuid: str
    name: str = "Untitled station"
    url: str = ""
    country: str = ""
    countrycode: str = ""
    state: str = ""
    language: str = ""
    tags: str = ""
    codec: str = ""
    bitrate: int = 0
    votes: int = 0
    clickcount: int = 0
    lastcheckok: int = 0
    geo_lat: float | None = None
    geo_long: float | None = None

    @classmethod
    def from_api(cls, row: dict) -> "Station":
        data = {f.name: clean(row.get(f.name)) for f in fields(cls)}
        if not data["stationuuid"]:
            raise ValueError("Station has no UUID.")
        data["name"] = data["name"] or "Untitled station"
        data["url"] = clean(row.get("url_resolved") or row.get("url"))
        for key in ("bitrate", "votes", "clickcount", "lastcheckok"):
            data[key] = number(row.get(key))
        data["geo_lat"] = coordinate(row.get("geo_lat"), 90)
        data["geo_long"] = coordinate(row.get("geo_long"), 180)
        data["countrycode"] = data["countrycode"].upper()
        return cls(**data)


SORTS = {
    "clickcount": "Plays (24h)",
    "votes": "Votes",
    "name": "Name",
    "bitrate": "Bitrate",
    "country": "Country",
    "tags": "Genre / format",
    "favourite": "Favourites",
    "recent": "Recently played",
    "listen": "Listen time",
}


@dataclass(frozen=True)
class Search:
    terms: tuple[str, ...] = ()
    expression: tuple = ()
    name: str = ""
    country: str = ""
    state: str = ""
    language: str = ""
    tags: str = ""
    codec: str = ""
    bitrate_min: int = 0
    bitrate_max: int = 0
    https_only: bool = False
    hidebroken: bool = True
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None
    order: str = "clickcount"
    descending: bool = True

    def __post_init__(self) -> None:
        if len(self.terms) > 32:
            raise ValueError("Use at most 32 text terms or phrases.")
        if self.order not in SORTS:
            raise ValueError("Unknown sort order.")
        if self.bitrate_min < 0 or self.bitrate_max < 0:
            raise ValueError("Bitrates must be zero or positive.")
        if self.bitrate_max and self.bitrate_min > self.bitrate_max:
            raise ValueError("Minimum bitrate exceeds maximum bitrate.")
        geo = (self.latitude, self.longitude, self.radius_km)
        if any(x is not None for x in geo):
            if not all(x is not None and math.isfinite(x) for x in geo):
                raise ValueError("Set latitude, longitude and radius together (finite numbers).")
            if abs(self.latitude) > 90 or abs(self.longitude) > 180 or self.radius_km <= 0:
                raise ValueError("Coordinates out of range or radius must be positive.")

    def api_params(self) -> dict:
        params = {
            "name": self.name,
            "state": self.state,
            "language": self.language,
            "tagList": self.tags,
            "codec": self.codec,
            "bitrateMin": self.bitrate_min,
            "order": {"favourite": "clickcount", "recent": "clicktimestamp", "listen": "clickcount"}.get(
                self.order, self.order
            ),
            "reverse": str(self.descending).lower(),
            "hidebroken": str(self.hidebroken).lower(),
        }
        if len(self.country) == 2:
            params["countrycode"] = self.country.upper()
        elif self.country:
            params.update(country=self.country, countryExact="true")
        if self.bitrate_max:
            params["bitrateMax"] = self.bitrate_max
        if self.https_only:
            params["is_https"] = "true"
        if self.latitude is not None:
            params.update(
                geo_lat=self.latitude, geo_long=self.longitude, geo_distance=self.radius_km * 1000
            )
        return {key: value for key, value in params.items() if value != ""}


def distance_km(lat: float, lon: float, other_lat: float, other_lon: float) -> float:
    if other_lat is None or other_lon is None:
        return math.inf
    lat, lon, other_lat, other_lon = map(math.radians, (lat, lon, other_lat, other_lon))
    a = math.sin((other_lat - lat) / 2) ** 2
    a += math.cos(lat) * math.cos(other_lat) * math.sin((other_lon - lon) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))
