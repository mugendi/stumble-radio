import re
from dataclasses import dataclass

from .models import clean


@dataclass(frozen=True)
class Track:
    artist: str
    title: str
    raw: str = ""


def track_from_metadata(metadata: object, station_name: str = "") -> Track | None:
    """Use actual stream tags; mpv's media-title can fall back to a station or URL."""
    if not isinstance(metadata, dict):
        return None
    tags = {
        str(key).casefold(): clean(value)[:4096]
        for key, value in metadata.items()
        if isinstance(value, str)
    }
    raw = tags.get("icy-title", "") or tags.get("streamtitle", "")
    artist, title = tags.get("artist", ""), tags.get("title", "")
    if raw:
        # ICY updates are authoritative: static file tags may describe an earlier song.
        parts = re.split(r"\s+[-–—]\s+", raw, maxsplit=1)
        artist, title = parts if len(parts) == 2 else ("", raw)
    if not title or (not artist and title.casefold() == station_name.casefold()):
        return None
    if not artist:
        parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
        if len(parts) == 2:
            artist, title = parts
    artist, title = artist.strip(), title.strip()
    return Track(artist, title, raw) if title else None
