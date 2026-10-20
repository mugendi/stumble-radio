"""Stumble Radio — a radio for curious ears."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stumble-radio")
except PackageNotFoundError:
    __version__ = "0.2.0"
