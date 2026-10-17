import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from . import __version__


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "stumble-radio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "stumble-radio"


def relaunch_process(argv: list[str]) -> None:
    try:
        os.execv(argv[0], argv)
    except OSError as error:
        print(f"Stumble Radio was updated but could not relaunch itself: {error}", file=sys.stderr)
        raise SystemExit(1) from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Stumble Radio — a radio for curious ears.")
    parser.add_argument("--version", action="version", version=f"Stumble Radio {__version__}")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="Database directory (default: platform user data directory)",
    )
    parser.add_argument(
        "--recordings-dir", type=Path, help="Recording destination (default: DATA_DIR/recordings)"
    )
    parser.add_argument(
        "--offline", action="store_true", help="Use the cached directory without API requests"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Check dependencies and show storage paths"
    )
    args = parser.parse_args()
    recordings = (args.recordings_dir or args.data_dir / "recordings").expanduser().resolve()
    data_dir = args.data_dir.expanduser().resolve()
    if args.doctor:
        print(f"Stumble Radio {__version__}\nPython: {sys.version.split()[0]}")
        for binary in ("mpv", "ffmpeg"):
            print(f"{binary}: {shutil.which(binary) or 'MISSING'}")
        print(f"Database: {data_dir / 'radio.sqlite3'}\nRecordings: {recordings}")
        print(f"Default Podmoro voice library: {data_dir / 'pomodoro' / 'audio' / 'commands'}")
        print("Podmoro uses local MP3s and mpv; no speech service or background daemon.")
        print("Install audio tools: apt install mpv ffmpeg  |  brew install mpv ffmpeg")
        return
    if os.name != "posix":
        parser.error("Playback currently supports Linux and macOS; use WSL on Windows.")
    from .app import StumbleRadio
    from .db import Database

    try:
        db = Database(data_dir / "radio.sqlite3")
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Cannot open station database: {error}\n")
    app = StumbleRadio(db, recordings, offline=args.offline)
    app.run()
    if app.relaunch_requested and os.name == "posix" and sys.argv and sys.argv[0]:
        print("Relaunching Stumble Radio…")
        relaunch_process(list(sys.argv))
