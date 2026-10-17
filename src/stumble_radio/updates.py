"""Launch-time update checks and the self-upgrade bridge for uv tool installs."""

import importlib.metadata
from pathlib import Path

from . import __version__

REPO_TAGS_URL = "https://api.github.com/repos/mugendi/stumble-radio/tags"
SOURCE_ARCHIVE = "https://github.com/mugendi/stumble-radio/archive/refs/heads/master.tar.gz"
UV_FALLBACK_DIRS = (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin")


def installed_version() -> str:
    try:
        return importlib.metadata.version("stumble-radio")
    except importlib.metadata.PackageNotFoundError:
        return __version__


def parse_version(value: str) -> tuple[int, ...] | None:
    parts = str(value).removeprefix("v").split(".")
    if not parts or not all(segment.isdigit() for segment in parts):
        return None
    return tuple(int(segment) for segment in parts)


def is_newer(latest: str, installed: str) -> bool:
    candidate = parse_version(latest)
    current = parse_version(installed)
    if not candidate or not current:
        return False
    width = max(len(candidate), len(current))
    return candidate + (0,) * (width - len(candidate)) > current + (0,) * (width - len(current))
