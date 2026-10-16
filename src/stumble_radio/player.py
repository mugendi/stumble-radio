import asyncio
import json
import re
import shutil
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .equalizer import EqualizerSettings
from .models import Station, clean, stream_url

METER_FILTER = "@stumble_meter:lavfi=[astats=metadata=1:reset=1]"


class PlayerError(Exception):
    pass


class Player:
    """mpv JSON IPC and an independent FFmpeg recording process (Linux/macOS)."""

    def __init__(self, recordings: Path):
        self.recordings = recordings
        self.process = None
        self.reader = None
        self.writer = None
        self.reader_task = None
        self.tempdir = None
        self.pending = {}
        self.request_id = 0
        self.events = asyncio.Queue()
        self.station: Station | None = None
        self.loading_station: Station | None = None
        self.event_station: Station | None = None
        self.record_process = None
        self.record_path: Path | None = None
        self.record_task = None
        self.record_error = ""
        self.start_lock = asyncio.Lock()
        self.closing_mpv = False
        self.output_volume = 65
        self.equalizer = EqualizerSettings()
        self.filter_settings = EqualizerSettings()
        self.audio_lock = asyncio.Lock()
        self.effects_supported = None

    async def check_equalizer_support(self) -> None:
        if self.effects_supported is None:
            if not shutil.which("mpv"):
                raise PlayerError("Install mpv to use the equalizer.")
            process = await asyncio.create_subprocess_exec(
                "mpv", "--no-config", "--af=help", stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
                names = set(re.findall(r"^\s*(\S+)\s", output.decode(errors="replace"), re.MULTILINE))
                self.effects_supported = process.returncode == 0 and {
                    "aformat", "equalizer", "volume", "alimiter"
                } <= names
            except TimeoutError as error:
                raise PlayerError("Timed out checking mpv equalizer support. Try again.") from error
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        if not self.effects_supported:
            raise PlayerError("This mpv build lacks equalizer filters. Use Bypass or upgrade mpv.")

    async def apply_equalizer_filter(self, settings: EqualizerSettings) -> None:
        if settings == self.filter_settings:
            return
        previous = self.filter_settings
        try:
            graph = settings.filter_graph()
            if graph:
                await self.command("af", "add", f"@stumble_eq:lavfi=[{graph}]")
            elif previous.active:
                await self.command("af", "remove", "@stumble_eq")
        except PlayerError as error:
            chain = METER_FILTER
            if previous.active:
                chain += f",@stumble_eq:lavfi=[{previous.filter_graph()}]"
            try:
                await self.command("af", "set", chain)
            except PlayerError:
                await self.command("af", "set", METER_FILTER)
                self.equalizer = self.filter_settings = EqualizerSettings(enabled=False)
            raise PlayerError("Could not apply equalizer settings; the working sound was restored.") from error
        self.filter_settings = settings

    async def set_equalizer(self, settings: EqualizerSettings) -> None:
        async with self.audio_lock:
            live = self.writer and not self.writer.is_closing()
            if not live and settings == self.equalizer:
                return
            if settings.active:
                await self.check_equalizer_support()
            if live:
                await self.apply_equalizer_filter(settings)
            self.equalizer = settings

    async def start(self) -> None:
        async with self.start_lock:
            if (
                self.process
                and self.process.returncode is None
                and self.writer
                and not self.writer.is_closing()
                and self.reader_task
                and not self.reader_task.done()
            ):
                return
            if not shutil.which("mpv"):
                raise PlayerError("Install mpv for playback (see stumble-radio --doctor).")
            await self._close_mpv()
            self.tempdir = tempfile.TemporaryDirectory(prefix="stumble-")
            socket_path = str(Path(self.tempdir.name) / "mpv.sock")
            self.process = await asyncio.create_subprocess_exec(
                "mpv",
                "--no-config",
                "--idle=yes",
                "--no-video",
                "--no-terminal",
                "--input-default-bindings=no",
                "--input-vo-keyboard=no",
                "--ytdl=no",
                f"--volume={self.output_volume}",
                "--network-timeout=15",
                "--cache=yes",
                f"--af={METER_FILTER}",
                f"--input-ipc-server={socket_path}",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            for _ in range(60):
                try:
                    self.reader, self.writer = await asyncio.open_unix_connection(socket_path)
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if self.process.returncode is not None:
                        raise PlayerError("mpv exited during startup. Check your mpv installation.")
                    await asyncio.sleep(0.05)
            else:
                await self._close_mpv()
                raise PlayerError("Timed out connecting to mpv.")
            self.reader_task = asyncio.create_task(self._read_events())
            for index, name in enumerate(
                ("media-title", "pause", "volume", "paused-for-cache", "metadata")
            ):
                await self.command("observe_property", index, name)

    async def _read_events(self) -> None:
        try:
            while line := await self.reader.readline():
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                future = self.pending.get(message.get("request_id"))
                if future and not future.done():
                    future.set_result(message)
                elif "event" in message:
                    if message["event"] == "start-file":
                        self.event_station = self.loading_station
                    if self.event_station:
                        message["stationuuid"] = self.event_station.stationuuid
                    await self.events.put(message)
        except (OSError, ValueError):
            pass
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(PlayerError("Lost connection to mpv."))
            if not self.closing_mpv:
                await self.events.put({"event": "disconnected"})

    async def command(self, *args):
        if not self.writer or self.writer.is_closing():
            raise PlayerError("Player is not running.")
        self.request_id += 1
        request_id = self.request_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            self.writer.write(
                (json.dumps({"command": args, "request_id": request_id}) + "\n").encode()
            )
            await self.writer.drain()
            result = await asyncio.wait_for(future, timeout=3)
            if result.get("error") != "success":
                raise PlayerError(f"mpv: {result.get('error', 'command failed')}")
            return result.get("data")
        except (TimeoutError, OSError) as error:
            raise PlayerError("mpv did not respond. Try playing the station again.") from error
        finally:
            self.pending.pop(request_id, None)

    async def play(self, station: Station) -> Path | None:
        url = stream_url(station.url)
        async with self.audio_lock:
            await self.start()
            try:
                if self.equalizer.active:
                    await self.check_equalizer_support()
                await self.apply_equalizer_filter(self.equalizer)
            except (PlayerError, OSError) as error:
                self.equalizer = EqualizerSettings(enabled=False)
                await self.apply_equalizer_filter(self.equalizer)
                await self.events.put({"event": "equalizer-error", "error": clean(str(error))})
            await self.set_volume(self.output_volume)
            saved = await self.stop_recording()
            await self.command("set_property", "pause", False)
            self.loading_station = station
            await self.command("loadfile", url, "replace")
            self.station = station
            return saved

    async def pause(self) -> None:
        if not self.station:
            raise PlayerError("Choose a station first.")
        await self.command("cycle", "pause")

    async def volume(self, delta: int) -> None:
        await self.command("add", "volume", delta)

    async def set_volume(self, value: float) -> None:
        self.output_volume = max(0, min(100, value))
        await self.command("set_property", "volume", self.output_volume)

    async def health(self) -> tuple[float | None, float | None]:
        position = await self.command("get_property", "time-pos")
        return position, await self.audio_level()

    async def audio_level(self) -> float | None:
        try:
            metadata = await self.command("get_property", "af-metadata/stumble_meter")
            level = (metadata or {}).get("lavfi.astats.Overall.RMS_level")
            rms = float(level) if level is not None else None
        except (PlayerError, ValueError, TypeError):
            rms = None
        return rms

    async def stop(self) -> Path | None:
        saved = await self.stop_recording()
        if self.writer and not self.writer.is_closing():
            await self.command("stop")
        self.station = None
        return saved

    async def record(self) -> Path:
        if not self.station:
            raise PlayerError("Play a station before recording.")
        if self.record_process:
            raise PlayerError("A recording is already running.")
        if not shutil.which("ffmpeg"):
            raise PlayerError("Install FFmpeg to record (see stumble-radio --doctor).")
        self.recordings.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w-]+", "-", self.station.name).strip("-_")[:64] or "station"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.record_path = self.recordings / f"{stamp}-{slug}-{uuid4().hex[:6]}.mka"
        self.record_error = ""
        self.record_process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-rw_timeout",
            "15000000",
            "-protocol_whitelist",
            "http,https,tcp,tls,crypto",
            "-i",
            stream_url(self.station.url),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "copy",
            str(self.record_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self.record_task = asyncio.create_task(
            self._watch_recording(self.record_process, self.record_path)
        )
        return self.record_path

    async def _watch_recording(self, process, path: Path) -> None:
        # Drain continuously so a failing stream cannot fill the stderr pipe.
        while chunk := await process.stderr.read(1024):
            self.record_error = (self.record_error + clean(chunk.decode(errors="replace")))[-2000:]
        code = await process.wait()
        await self.events.put(
            {
                "event": "recording-ended",
                "code": code,
                "path": str(path),
                "error": self.record_error,
            }
        )

    async def stop_recording(self) -> Path | None:
        process, path = self.record_process, self.record_path
        if process is None:
            return None
        try:
            if process.returncode is None:
                try:
                    process.stdin.write(b"q\n")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
            if self.record_task:
                await self.record_task
        finally:
            self.record_process = None
            self.record_task = None
            self.record_path = None
        return path

    async def _close_mpv(self) -> None:
        self.closing_mpv = True
        try:
            if self.process and self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            if self.reader_task:
                self.reader_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.reader_task
            if self.writer:
                self.writer.close()
                with suppress(OSError):
                    await self.writer.wait_closed()
            if self.tempdir:
                self.tempdir.cleanup()
            self.process = self.writer = self.reader = self.reader_task = self.tempdir = None
            self.filter_settings = EqualizerSettings()
        finally:
            self.closing_mpv = False

    async def close(self) -> None:
        async with self.audio_lock:
            await self.stop_recording()
            await self._close_mpv()
