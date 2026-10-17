import asyncio
import json
import re
import shutil
import tempfile
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .equalizer import BASE_TARGET_LUFS, EqualizerSettings
from .models import Station, clean, stream_url

METER_FILTER = "@stumble_meter:lavfi=[astats=metadata=1:reset=1]"
SWAP_TIMEOUT_SECONDS = 20.0
OBSERVED_PROPERTIES = ("media-title", "pause", "volume", "paused-for-cache", "metadata")


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
        self.filter_settings = EqualizerSettings(auto_level=False)
        self.audio_lock = asyncio.Lock()
        self.effects_supported = None
        self.auto_level_supported = None
        self.auto_level_state = "off"
        self.auto_level_correction_db = 0.0
        self.auto_level_target_lufs = BASE_TARGET_LUFS
        self.auto_level_started_at = 0.0
        self.auto_level_last_update = 0.0
        self.auto_level_last_position = None
        self.auto_level_disabled_for_session = False
        self.auto_level_error_sent = False

    async def check_equalizer_support(self, *, auto_level=False) -> None:
        if self.effects_supported is None or (auto_level and self.auto_level_supported is None):
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
                self.auto_level_supported = process.returncode == 0 and "ebur128" in names
            except TimeoutError as error:
                raise PlayerError("Timed out checking mpv equalizer support. Try again.") from error
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        if not self.effects_supported:
            raise PlayerError("This mpv build lacks equalizer filters. Use Bypass or upgrade mpv.")
        if auto_level and not self.auto_level_supported:
            raise PlayerError("This mpv build lacks the loudness meter needed for automatic leveling.")

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
                self.equalizer = self.filter_settings = EqualizerSettings(enabled=False, auto_level=False)
            raise PlayerError("Could not apply equalizer settings; the working sound was restored.") from error
        self.filter_settings = settings

    async def set_equalizer(self, settings: EqualizerSettings) -> None:
        async with self.audio_lock:
            live = self.writer and not self.writer.is_closing()
            if not live and settings == self.equalizer:
                return
            if settings.active:
                await self.check_equalizer_support(auto_level=settings.auto_level)
            if live:
                await self.apply_equalizer_filter(settings)
            self.equalizer = settings
            self.auto_level_disabled_for_session = False
            self.auto_level_error_sent = False
            self._reset_auto_level()

    def _reset_auto_level(self) -> None:
        self.auto_level_target_lufs = BASE_TARGET_LUFS + self.equalizer.gain_db
        self.auto_level_correction_db = 0.0
        self.auto_level_started_at = time.monotonic()
        self.auto_level_last_update = self.auto_level_started_at
        self.auto_level_last_position = None
        if self.auto_level_disabled_for_session:
            self.auto_level_state = "unavailable"
        else:
            self.auto_level_state = "measuring" if self.equalizer.enabled and self.equalizer.auto_level else "off"

    async def _restore_manual_equalizer(self) -> None:
        settings = EqualizerSettings(self.equalizer.bands, self.equalizer.gain_db, self.equalizer.enabled, auto_level=False)
        graph = settings.filter_graph()
        chain = METER_FILTER + (f",@stumble_eq:lavfi=[{graph}]" if graph else "")
        try:
            await self.command("af", "set", chain)
            self.filter_settings = settings
        except PlayerError:
            await self.command("af", "set", METER_FILTER)
            self.filter_settings = EqualizerSettings(auto_level=False)

    async def update_auto_level(self) -> None:
        """Nudge the named post-EQ gain toward the configured short-term LUFS target."""
        if not self.equalizer.enabled or not self.equalizer.auto_level or self.auto_level_disabled_for_session:
            self.auto_level_state = "unavailable" if self.auto_level_disabled_for_session else "off"
            return
        async with self.audio_lock:
            try:
                position = await self.command("get_property", "time-pos")
                metadata = await self.command("get_property", "af-metadata/stumble_eq")
                position = float(position)
                loudness = float((metadata or {}).get("lavfi.r128.S"))
            except (PlayerError, TypeError, ValueError):
                self.auto_level_state = "measuring"
                return
            if self.auto_level_last_position is not None and position <= self.auto_level_last_position:
                return
            self.auto_level_last_position = position
            if time.monotonic() - self.auto_level_started_at < 3:
                self.auto_level_state = "measuring"
                return
            if loudness <= -50:
                self.auto_level_state = "waiting"
                return
            now = time.monotonic()
            elapsed = min(1.0, max(0.0, now - self.auto_level_last_update))
            target = self.auto_level_target_lufs
            desired = max(-36.0, min(24.0, target - loudness))
            delta = desired - self.auto_level_correction_db
            correction = self.auto_level_correction_db + max(-6 * elapsed, min(2 * elapsed, delta))
            correction = round(correction, 1)
            self.auto_level_last_update = now
            if abs(correction - self.auto_level_correction_db) >= 0.1:
                try:
                    await self.command("af-command", "stumble_eq", "volume", f"{correction}dB", "volume@stumble_auto")
                except PlayerError as error:
                    self.auto_level_state = "unavailable"
                    self.auto_level_disabled_for_session = True
                    with suppress(PlayerError):
                        await self._restore_manual_equalizer()
                    if not self.auto_level_error_sent:
                        self.auto_level_error_sent = True
                        await self.events.put({"event": "equalizer-error", "error": clean(str(error))})
                    return
                self.auto_level_correction_db = correction
            self.auto_level_state = "limited" if correction in (-36, 24) else "active"

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
            self.process, self.reader, self.writer, self.tempdir = await self._open_instance()
            self.reader_task = asyncio.create_task(self._read_events())
            await self.observe()

    @property
    def _live(self) -> bool:
        return (
            bool(self.process)
            and self.process.returncode is None
            and bool(self.writer)
            and not self.writer.is_closing()
            and bool(self.reader_task)
            and not self.reader_task.done()
        )

    async def observe(self) -> None:
        for index, name in enumerate(OBSERVED_PROPERTIES):
            await self.command("observe_property", index, name)

    async def _open_instance(self, af_chain: str = METER_FILTER):
        """Spawn a fresh mpv process and return (process, reader, writer, tempdir)."""
        tempdir = tempfile.TemporaryDirectory(prefix="stumble-")
        socket_path = str(Path(tempdir.name) / "mpv.sock")
        process = await asyncio.create_subprocess_exec(
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
            f"--af={af_chain}",
            f"--input-ipc-server={socket_path}",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                return process, reader, writer, tempdir
            except (FileNotFoundError, ConnectionRefusedError):
                if process.returncode is not None:
                    tempdir.cleanup()
                    raise PlayerError("mpv exited during startup. Check your mpv installation.")
                await asyncio.sleep(0.05)
        await self._dispose(process, writer, tempdir)
        raise PlayerError("Timed out connecting to mpv.")

    async def _ipc(self, writer, state: dict, /, *args) -> None:
        request_id = state.get("next", 0) + 1
        state["next"] = request_id
        future = asyncio.get_running_loop().create_future()
        state[request_id] = future
        writer.write(
            (json.dumps({"command": args, "request_id": request_id}) + "\n").encode()
        )
        await writer.drain()
        try:
            result = await asyncio.wait_for(future, timeout=3)
            if result.get("error") != "success":
                raise PlayerError(f"mpv: {result.get('error', 'command failed')}")
        finally:
            state.pop(request_id, None)

    def _arm_watcher(self, process, reader, state: dict) -> tuple:
        """Track the secondary instance's socket until it reports a playable file."""
        loaded = asyncio.get_running_loop().create_future()
        failed = asyncio.get_running_loop().create_future()

        async def watch() -> None:
            try:
                while line := await reader.readline():
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    future = state.get(message.get("request_id"))
                    if future and not future.done():
                        future.set_result(message)
                    elif message.get("event") == "file-loaded":
                        if not loaded.done():
                            loaded.set_result(True)
                        return
                    elif (
                        message.get("event") in {"end-file", "shutdown"}
                        or process.returncode is not None
                    ):
                        if not failed.done():
                            failed.set_result(False)
                        return
            except OSError:
                if not failed.done():
                    failed.set_result(False)

        return loaded, failed, asyncio.create_task(watch())

    async def _settle_load(self, loaded, failed) -> bool:
        done, _ = await asyncio.wait_for(
            asyncio.wait({loaded, failed}, return_when=asyncio.FIRST_COMPLETED),
            timeout=SWAP_TIMEOUT_SECONDS,
        )
        return loaded in done

    async def _dispose(self, process, writer, tempdir) -> None:
        """Terminate an mpv instance that is no longer the active player."""
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        if writer:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
        if tempdir:
            tempdir.cleanup()

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
                    elif message["event"] == "file-loaded":
                        self._reset_auto_level()
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
            self.loading_station = station
            if self._live:
                return await self._play_swapping(station, url)
            return await self._play_started(station, url)

    async def configure_stream(self) -> None:
        """Prepare the running mpv for a full restart of its playlist."""
        self._reset_auto_level()
        try:
            if self.equalizer.active and not self.auto_level_disabled_for_session:
                await self.check_equalizer_support(auto_level=self.equalizer.auto_level)
            runtime_settings = self.equalizer
            if self.auto_level_disabled_for_session:
                runtime_settings = EqualizerSettings(self.equalizer.bands, self.equalizer.gain_db, self.equalizer.enabled, auto_level=False)
            if self.filter_settings.active:
                with suppress(PlayerError):
                    await self.command("af", "remove", "@stumble_eq")
                self.filter_settings = EqualizerSettings(auto_level=False)
            await self.apply_equalizer_filter(runtime_settings)
        except (PlayerError, OSError) as error:
            if self.equalizer.auto_level:
                self.auto_level_state = "unavailable"
                self.auto_level_disabled_for_session = True
                with suppress(PlayerError):
                    await self._restore_manual_equalizer()
            else:
                self.equalizer = EqualizerSettings(enabled=False, auto_level=False)
                await self.apply_equalizer_filter(self.equalizer)
            await self.events.put({"event": "equalizer-error", "error": clean(str(error))})
        await self.set_volume(self.output_volume)

    async def _play_started(self, station: Station, url: str) -> Path | None:
        await self.start()
        await self.configure_stream()
        saved = await self.stop_recording()
        await self.command("set_property", "pause", False)
        await self.command("loadfile", url, "replace")
        self.station = station
        return saved

    async def _play_swapping(self, station: Station, url: str) -> Path | None:
        """Load the next station in a second mpv process while this one keeps playing."""
        chain = METER_FILTER
        if self.filter_settings.active:
            chain += f",@stumble_eq:lavfi=[{self.filter_settings.filter_graph()}]"
        state: dict = {}
        process, reader, writer, tempdir = None, None, None, None
        try:
            process, reader, writer, tempdir = await self._open_instance(chain)
            loaded, failed, watcher = self._arm_watcher(process, reader, state)
            try:
                await self._ipc(writer, state, "loadfile", url, "replace")
                if await self._settle_load(loaded, failed):
                    with suppress(asyncio.CancelledError):
                        await watcher
                else:
                    raise PlayerError(f"Timeout while waiting for the stream to start: {station.name}")
            except BaseException:
                watcher.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher
                raise
        except (PlayerError, OSError) as error:
            await self._dispose(process, writer, tempdir)
            raise (error if isinstance(error, PlayerError) else PlayerError(str(error) or "mpv did not open the stream.")) from None
        saved = await self.stop_recording()
        paused = False
        with suppress(PlayerError):
            paused = bool(await self.command("get_property", "pause"))
        await self.swap(process, reader, writer, tempdir, station, paused)
        await self.events.put({"event": "start-file", "stationuuid": station.stationuuid})
        await self.events.put({"event": "file-loaded", "stationuuid": station.stationuuid})
        return saved

    async def swap(self, process, reader, writer, tempdir, station: Station, paused: bool) -> None:
        """Promote the secondary instance to the main player."""
        old_task, old_process, old_writer, old_tempdir = (
            self.reader_task,
            self.process,
            self.writer,
            self.tempdir,
        )
        self.process, self.reader, self.writer, self.tempdir = process, reader, writer, tempdir
        self.station = station
        for request_id in list(self.pending):
            future = self.pending.pop(request_id, None)
            if future and not future.done():
                future.set_exception(PlayerError("Connection replaced by the next station."))
        self.closing_mpv = True
        if old_task:
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task
        self.event_station = self.loading_station = station
        self.reader_task = asyncio.create_task(self._read_events())
        self.closing_mpv = False
        await self.observe()
        self._reset_auto_level()
        await self.command("set_property", "pause", paused)
        await self._dispose(old_process, old_writer, old_tempdir)

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
            self.filter_settings = EqualizerSettings(auto_level=False)
        finally:
            self.closing_mpv = False

    async def close(self) -> None:
        async with self.audio_lock:
            await self.stop_recording()
            await self._close_mpv()
