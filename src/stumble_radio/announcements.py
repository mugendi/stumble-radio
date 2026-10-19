import asyncio
import random
import shutil
from contextlib import suppress
from pathlib import Path

from .models import clean
from .player import PlayerError
from .pomodoro import COMMANDS, category

MAX_ANNOUNCEMENT_SECONDS = 120


class AudioLibrary:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.last: dict[str, Path] = {}

    def ensure(self):
        for command in COMMANDS:
            (self.root / command).mkdir(parents=True, exist_ok=True)

    def folder(self, command: str) -> Path:
        folder = (self.root / category(command)).resolve()
        if not folder.is_relative_to(self.root):
            raise ValueError("A command folder must stay inside the voice library.")
        return folder

    def clips(self, command: str) -> list[Path]:
        folder = self.folder(command)
        if not folder.is_dir():
            return []
        return sorted(
            p
            for p in folder.iterdir()
            if p.is_file()
            and p.suffix.lower() in {".mp3", ".wav"}
            and p.resolve().is_relative_to(self.root)
        )

    def categories(self) -> list[str]:
        found = set(COMMANDS)
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.is_dir():
                    name = path.relative_to(self.root).as_posix()
                    try:
                        self.folder(name)
                    except ValueError:
                        continue
                    children = list(path.iterdir())
                    if not any(p.is_dir() for p in children) or any(
                        p.suffix.lower() == ".mp3" for p in children
                    ):
                        found.add(name)
        return sorted(found)

    def choose(self, command: str) -> Path | None:
        clips = self.clips(command)
        if not clips:
            return None
        choices = [p for p in clips if p != self.last.get(command)] or clips
        selected = random.choice(choices)
        self.last[command] = selected
        return selected

    @staticmethod
    def caption(clip: Path, default: str) -> str:
        try:
            with clip.with_suffix(".txt").open(encoding="utf-8") as handle:
                return clean(handle.read(4096).replace("\n", " ").replace("\r", " ")) or default
        except (OSError, UnicodeError):
            return default


class AnnouncementPlayer:
    """A separate local-file player; no station metadata, recording or radio controls."""

    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def play(self, clip: Path, volume: int):
        async with self.lock:
            if not shutil.which("mpv"):
                raise PlayerError("Install mpv to play Podmoro voice clips.")
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    "mpv",
                    "--no-config",
                    "--no-video",
                    "--no-terminal",
                    "--ytdl=no",
                    "--input-default-bindings=no",
                    "--input-vo-keyboard=no",
                    f"--volume={volume}",
                    "--",
                    str(clip.resolve()),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            )
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                with suppress(OSError):
                    process = await spawn
                    await self.stop(process)
                raise
            self.process = process
            try:
                code = await asyncio.wait_for(process.wait(), timeout=MAX_ANNOUNCEMENT_SECONDS)
                if code:
                    raise PlayerError(f"Could not play voice clip: {clip.name}")
            except TimeoutError as error:
                raise PlayerError(
                    "Voice clip stopped after the 120-second announcement limit."
                ) from error
            finally:
                await self.stop(process)

    async def stop(self, process=None):
        process = process or self.process
        if process and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if self.process is process:
            self.process = None
