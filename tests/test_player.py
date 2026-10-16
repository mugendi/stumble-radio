import asyncio
import io
import json
import math
import shutil
import struct
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from stumble_radio.equalizer import EqualizerSettings
from stumble_radio.player import Player, PlayerError
from stumble_radio.tracks import Track, track_from_metadata


class Process:
    def __init__(self):
        self.returncode = None
        self.done = asyncio.Event()
        self.stderr = asyncio.StreamReader()
        self.stdout = io.BytesIO()
        self.stdin = self

    def write(self, value):
        if value == b"q\n":
            self.finish(0)

    async def drain(self):
        pass

    async def communicate(self):
        self.finish(0)
        return self.stdout.getvalue(), b""

    def finish(self, code):
        if self.returncode is None:
            self.returncode = code
            self.stderr.feed_eof()
            self.done.set()

    def terminate(self):
        self.finish(-15)

    def kill(self):
        self.finish(-9)

    async def wait(self):
        await self.done.wait()
        return self.returncode


async def test_ipc_playback_record_switch_and_cleanup(tmp_path, station, monkeypatch):
    commands = []
    processes = []
    servers = []
    writers = []

    async def serve(reader, writer):
        writers.append(writer)
        try:
            while line := await reader.readline():
                message = json.loads(line)
                commands.append(message["command"])
                writer.write(
                    (
                        json.dumps({"request_id": message["request_id"], "error": "success"}) + "\n"
                    ).encode()
                )
                if message["command"][0] == "loadfile":
                    writer.write(
                        b'{"event":"start-file"}\n'
                        b'{"event":"file-loaded"}\n'
                        b'{"event":"property-change","name":"metadata",'
                        b'"data":{"artist":"Boyz II Men","title":"End of the Road"}}\n'
                    )
                await writer.drain()
        finally:
            writer.close()

    async def spawn(*args, **kwargs):
        process = Process()
        processes.append(process)
        if args[0] == "mpv" and "--af=help" in args:
            # The equalizer-support probe spawns a plain mpv without IPC setup.
            process.stdout = io.BytesIO(
                b"  horizontal   Apply a simple stereo or multichannel level adjustment.\n"
                b"  volume        Apply volume.\n  equalizer     Pre-defined equalizer.\n"
                b"  aformat       Convert the input to a fixed format.\n"
                b"  alimiter      Lookahead limiter.\n  ebur128       EBUR128 loudness meter.\n"
            )
            return process
        if args[0] == "mpv":
            assert "--volume=0" in args
            path = next(a.split("=", 1)[1] for a in args if a.startswith("--input-ipc-server="))
            servers.append(await asyncio.start_unix_server(serve, path=path))
        else:
            assert "-c:a" in args and "copy" in args
            assert args[args.index("-i") + 1].startswith("https://")
            Path(args[-1]).write_bytes(b"test recording")
        return process

    monkeypatch.setattr("stumble_radio.player.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("stumble_radio.player.asyncio.create_subprocess_exec", spawn)
    player = Player(tmp_path / "recordings")
    with pytest.raises(PlayerError):
        await player.set_volume(0)
    try:
        await player.play(station)
        assert ["loadfile", station.url, "replace"] in commands
        assert commands.index(["set_property", "volume", 0]) < commands.index(
            ["loadfile", station.url, "replace"]
        )
        assert any(
            command[0] == "observe_property" and command[-1] == "metadata" for command in commands
        )
        while True:
            event = await asyncio.wait_for(player.events.get(), timeout=2)
            if event.get("name") == "metadata":
                assert event["stationuuid"] == station.stationuuid
                assert event["data"]["artist"] == "Boyz II Men"
                break
        await player.pause()
        assert ["cycle", "pause"] in commands
        await player.volume(-5)
        assert ["add", "volume", -5] in commands
        path = await player.record()
        assert path.exists() and path.suffix == ".mka"
        assert player.record_process.returncode is None
        saved = await player.play(replace(station, stationuuid="next", name="../../unsafe/name"))
        assert saved == path and player.record_process is None
        assert processes[1].returncode == 0
        path2 = await player.record()
        assert path2.parent == tmp_path / "recordings"
        # A live mpv process with a lost IPC connection must be restarted too.
        writers[-1].close()
        await writers[-1].wait_closed()
        await asyncio.wait_for(player.reader_task, timeout=2)
        await player.play(station)
        assert sum(command[0] == "loadfile" for command in commands) == 3
        assert processes[0].returncode is not None and processes[-1].returncode is None
        socket_dir = Path(player.tempdir.name)
        await player.close()
        assert not socket_dir.exists() and all(p.returncode is not None for p in processes)
    finally:
        await player.close()
        for writer in writers:
            writer.close()
        for server in servers:
            server.close()
            await server.wait_closed()


async def test_missing_player_and_invalid_stream(tmp_path, station, monkeypatch):
    player = Player(tmp_path)
    monkeypatch.setattr("stumble_radio.player.shutil.which", lambda name: None)
    with pytest.raises(PlayerError, match="Install mpv"):
        await player.play(station)
    with pytest.raises(ValueError, match="HTTP"):
        await player.play(replace(station, url="file:///etc/passwd"))
    with pytest.raises(PlayerError, match="before recording"):
        await player.record()
    await player.close()


@pytest.mark.skipif(not shutil.which("mpv"), reason="real mpv is not installed")
async def test_real_mpv_reports_decoded_silence_and_tone(tmp_path, station, monkeypatch):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(
            b"".join(
                struct.pack(
                    "<h", 0 if i < 16000 else int(6000 * math.sin(2 * math.pi * 440 * i / 8000))
                )
                for i in range(40000)
            )
        )
    payload = buffer.getvalue()
    info = b"INFO"
    for tag, value in ((b"IART", b"Boyz II Men\0"), (b"INAM", b"End of the Road\0")):
        info += tag + struct.pack("<I", len(value)) + value + b"\0" * (len(value) % 2)
    payload = payload[:12] + b"LIST" + struct.pack("<I", len(info)) + info + payload[12:]
    payload = payload[:4] + struct.pack("<I", len(payload) - 8) + payload[8:]

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                (
                    f"HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\n"
                    f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        if args[0] == "mpv":
            args = (*args, "--ao=null")
        return await original(*args, **kwargs)

    monkeypatch.setattr("stumble_radio.player.asyncio.create_subprocess_exec", spawn)
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    player = Player(tmp_path)
    try:
        await player.set_equalizer(EqualizerSettings(gain_db=12))
        await player.play(replace(station, url=f"http://127.0.0.1:{port}/sample.wav"))
        silent = audible = False
        for _ in range(50):
            await asyncio.sleep(0.1)
            try:
                _, rms = await player.health()
            except PlayerError:
                continue
            if rms is not None:
                silent |= rms <= -50
                audible |= rms > -50
            if silent and audible and rms is not None and rms > -20:
                break
        assert silent and audible
        assert -20 < rms < -15  # Source metering stays before the +12 dB playback gain.
        metadata = []
        while not player.events.empty():
            event = player.events.get_nowait()
            if event.get("name") == "metadata" and event.get("data"):
                metadata.append(event["data"])
        assert any(
            track_from_metadata(tags) == Track("Boyz II Men", "End of the Road")
            for tags in metadata
        ), metadata
    finally:
        await player.close()
        server.close()
        await server.wait_closed()
