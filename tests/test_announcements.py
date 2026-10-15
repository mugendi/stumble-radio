import asyncio
import shutil

import pytest

from stumble_radio.announcements import AnnouncementPlayer, AudioLibrary
from stumble_radio.player import PlayerError


def test_library_discovers_empty_custom_folders_mp3_variants_and_captions(tmp_path):
    library = AudioLibrary(tmp_path / "voices")
    library.ensure()
    folder = library.folder("reminders/my-stretch")
    folder.mkdir()
    assert "reminders/my-stretch" in library.categories()
    assert library.choose("focus-start") is None
    for name in ("one.mp3", "two.MP3", "ignore.txt"):
        (folder / name).write_text("fixture")
    (folder / "one.txt").write_text("Move your shoulders\x07\n", encoding="utf-8")
    assert len(library.clips("reminders/my-stretch")) == 2
    first = library.choose("reminders/my-stretch")
    assert library.choose("reminders/my-stretch") != first
    assert library.caption(folder / "one.mp3", "Default") == "Move your shoulders"
    assert library.caption(folder / "two.MP3", "Default") == "Default"
    (folder / "three.mp3").write_text("new")
    assert len(library.clips("reminders/my-stretch")) == 3


def test_library_rejects_traversal_and_outside_symlinks(tmp_path):
    library = AudioLibrary(tmp_path / "library")
    library.ensure()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp3").write_bytes(b"data")
    (library.root / "outside").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        library.folder("outside")
    with pytest.raises(ValueError):
        library.folder("../outside")
    (library.folder("focus-start") / "linked.mp3").symlink_to(outside / "secret.mp3")
    assert not library.clips("focus-start")


class Process:
    def __init__(self):
        self.returncode = None
        self.done = asyncio.Event()

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def terminate(self):
        self.finish(-15)

    def kill(self):
        self.finish(-9)

    def finish(self, code):
        self.returncode = code
        self.done.set()


async def test_voice_process_is_local_and_cancelled_cleanly(tmp_path, monkeypatch):
    process = Process()
    started = asyncio.Event()
    commands = []

    async def spawn(*args, **kwargs):
        commands.append(args)
        started.set()
        return process

    monkeypatch.setattr("stumble_radio.announcements.shutil.which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr("stumble_radio.announcements.asyncio.create_subprocess_exec", spawn)
    voice = AnnouncementPlayer()
    clip = tmp_path / "--voice.mp3"
    task = asyncio.create_task(voice.play(clip, 70))
    await started.wait()
    assert commands[0][-2:] == ("--", str(clip.resolve()))
    assert "--volume=70" in commands[0]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -15 and voice.process is None


async def test_clip_errors_and_timeout_release_the_player(tmp_path, monkeypatch):
    monkeypatch.setattr("stumble_radio.announcements.shutil.which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr("stumble_radio.announcements.MAX_ANNOUNCEMENT_SECONDS", 0.01)
    processes = []

    async def spawn(*args, **kwargs):
        process = Process()
        if not processes:
            process.finish(2)
        processes.append(process)
        return process

    monkeypatch.setattr("stumble_radio.announcements.asyncio.create_subprocess_exec", spawn)
    voice = AnnouncementPlayer()
    with pytest.raises(PlayerError, match="Could not play"):
        await voice.play(tmp_path / "bad.mp3", 75)
    with pytest.raises(PlayerError, match="120-second"):
        await voice.play(tmp_path / "long.mp3", 75)
    assert processes[-1].returncode == -15 and voice.process is None


async def test_cancel_during_process_creation_does_not_orphan_voice(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    process = Process()

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr("stumble_radio.announcements.shutil.which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr("stumble_radio.announcements.asyncio.create_subprocess_exec", spawn)
    voice = AnnouncementPlayer()
    task = asyncio.create_task(voice.play(tmp_path / "voice.mp3", 75))
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -15 and voice.process is None


@pytest.mark.skipif(
    not shutil.which("mpv") or not shutil.which("ffmpeg"), reason="local audio tools unavailable"
)
async def test_real_local_mp3_voice_playback(tmp_path, monkeypatch):
    clip = tmp_path / "voice.mp3"
    encoder = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=8000:cl=mono",
        "-t",
        "0.1",
        "-c:a",
        "libmp3lame",
        str(clip),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, error = await encoder.communicate()
    assert encoder.returncode == 0, error.decode()
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await original(args[0], "--ao=null", *args[1:], **kwargs)

    monkeypatch.setattr("stumble_radio.announcements.asyncio.create_subprocess_exec", spawn)
    voice = AnnouncementPlayer()
    await voice.play(clip, 75)
    assert voice.process is None
