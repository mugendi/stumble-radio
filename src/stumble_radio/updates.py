"""Launch-time update checks and the self-upgrade bridge for uv tool installs."""

import asyncio
import importlib.metadata
from pathlib import Path

import httpx

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


async def _fetch_latest_version() -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(6, connect=3),
            headers={"Accept": "application/vnd.github+json"},
        ) as client:
            response = await client.get(REPO_TAGS_URL)
            response.raise_for_status()
            tags = response.json()
        for tag in tags if isinstance(tags, list) else []:
            name = str((tag or {}).get("name", "")).removeprefix("v")
            if parse_version(name) is not None:
                return name
    except (httpx.HTTPError, OSError, ValueError, TypeError, RuntimeError):
        return None
    return None


def fetch_latest_version() -> str | None:
    return asyncio.run(_fetch_latest_version())
