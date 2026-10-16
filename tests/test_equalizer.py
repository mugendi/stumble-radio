import asyncio
import json
import math
import shutil
import struct
from dataclasses import replace

import pytest

from stumble_radio.equalizer import BAND_FREQUENCIES, PRESETS, EqualizerSettings
from stumble_radio.player import METER_FILTER, Player, PlayerError


@pytest.mark.parametrize("values", [
    {"bands": (0,)}, {"bands": "00000"}, {"bands": (13, 0, 0, 0, 0)},
    {"bands": (0, -13, 0, 0, 0)}, {"bands": (float("nan"), 0, 0, 0, 0)},
    {"bands": (True, 0, 0, 0, 0)}, {"gain_db": -1}, {"gain_db": 13},
    {"gain_db": float("inf")}, {"gain_db": True}, {"enabled": "true"},
])
def test_equalizer_validates_settings(values):
    with pytest.raises(ValueError):
        EqualizerSettings(**values)


def test_presets_bypass_reset_and_snapshot():
    flat = EqualizerSettings()
    assert not flat.active and flat.filter_graph() == "" and flat.preset == "Flat"
    for name, bands in PRESETS.items():
        settings = EqualizerSettings(bands, 6)
        assert settings.preset == name
        assert EqualizerSettings.restore(json.loads(json.dumps(settings.snapshot()))) == settings
        assert not replace(settings, enabled=False).active
        assert replace(settings, enabled=False).filter_graph() == ""
    assert EqualizerSettings((1, 0, 0, 0, 0)).preset == "Custom"
    graph = EqualizerSettings(PRESETS["Bass boost"], 12).filter_graph()
    assert graph.startswith("aformat=sample_fmts=fltp,")
    assert [f"equalizer=f={hz}:" in graph for hz in BAND_FREQUENCIES] == [True] * 5
    assert graph.index("equalizer") < graph.index("volume=12dB") < graph.index("alimiter=")
    assert "level=false" in graph and "0.891250938" in graph
    for data in (None, [], {}, {"version": True}, {"version": 2}):
        with pytest.raises(ValueError):
            EqualizerSettings.restore(data)


class Writer:
    def is_closing(self):
        return False


async def test_effects_only_replace_their_label_and_preserve_volume_meter_and_recording(tmp_path):
    player = Player(tmp_path)
    player.effects_supported = True
    player.writer = Writer()
    player.output_volume = 0
    recording = player.record_process = object()
    commands = []

    async def command(*args):
        commands.append(args)

    player.command = command
    settings = EqualizerSettings(PRESETS["Bass boost"], 6)
    await player.set_equalizer(settings)
    await player.set_equalizer(replace(settings, gain_db=8))
    assert all(command[:2] == ("af", "add") for command in commands)
    assert all(command[2].startswith("@stumble_eq:") for command in commands)
    assert player.record_process is recording and player.output_volume == 0
    assert not any("stumble_meter" in str(command) for command in commands)
    await player.set_equalizer(replace(settings, enabled=False))
    assert commands[-1] == ("af", "remove", "@stumble_eq")
    assert player.equalizer.bands == settings.bands


async def test_unchanged_saved_effects_can_be_restored_without_starting_or_probing_mpv(tmp_path):
    player = Player(tmp_path)
    original = player.equalizer = EqualizerSettings(PRESETS["Speech"], 6)
    player.effects_supported = False
    await player.set_equalizer(original)
    assert player.equalizer == original and player.process is None


async def test_filter_rejection_restores_previous_sound_and_unsupported_build_is_rejected(tmp_path):
    player = Player(tmp_path)
    player.effects_supported = True
    player.writer = Writer()
    previous = EqualizerSettings(PRESETS["Speech"], 3)
    player.equalizer = player.filter_settings = previous
    commands = []

    async def command(*args):
        commands.append(args)
        if args[:2] == ("af", "add"):
            raise PlayerError("unsupported graph")

    player.command = command
    with pytest.raises(PlayerError, match="restored"):
        await player.set_equalizer(replace(previous, gain_db=8))
    assert player.equalizer == previous and player.filter_settings == previous
    assert commands[-1] == (
        "af", "set", METER_FILTER + f",@stumble_eq:lavfi=[{previous.filter_graph()}]"
    )
    player.effects_supported = False
    with pytest.raises(PlayerError, match="lacks"):
        await player.set_equalizer(replace(previous, gain_db=9))
    assert player.equalizer == previous


async def test_staged_effects_survive_restart_and_unsupported_saved_effects_do_not_block_playback(
    tmp_path, station, monkeypatch
):
    player = Player(tmp_path)
    player.effects_supported = True
    settings = EqualizerSettings(PRESETS["Speech"], 4)
    await player.set_equalizer(settings)
    commands = []

    async def start():
        player.writer = Writer()

    async def command(*args):
        commands.append(args)

    monkeypatch.setattr(player, "start", start)
    monkeypatch.setattr(player, "command", command)
    for _ in range(2):
        player.filter_settings = EqualizerSettings()
        await player.play(station)
        assert player.equalizer == settings
    assert sum(command[:2] == ("af", "add") for command in commands) == 2
    player.filter_settings = EqualizerSettings()
    player.effects_supported = False
    await player.play(station)
    assert player.station == station and not player.equalizer.active
    assert (await player.events.get())["event"] == "equalizer-error"
    assert commands[-1] == ("loadfile", station.url, "replace")


@pytest.mark.parametrize("cancel", [False, True])
async def test_filter_capability_probe_cleans_up_on_timeout_or_cancellation(tmp_path, monkeypatch, cancel):
    entered = asyncio.Event()

    class Probe:
        returncode = None

        async def communicate(self):
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise TimeoutError

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    probe = Probe()

    async def spawn(*args, **kwargs):
        return probe

    monkeypatch.setattr("stumble_radio.player.shutil.which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr("stumble_radio.player.asyncio.create_subprocess_exec", spawn)
    player = Player(tmp_path)
    if cancel:
        task = asyncio.create_task(player.check_equalizer_support())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(PlayerError, match="Timed out"):
            await player.check_equalizer_support()
    assert probe.returncode == -9 and player.effects_supported is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("mpv"), reason="audio tools missing")
async def test_real_filter_chain_frequency_response_gain_and_peak_limiting():
    async def samples(settings, frequency=1000, amplitude=0.1):
        graph = settings.filter_graph() or "anull"
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            f"aevalsrc={amplitude}*sin(2*PI*{frequency}*t):s=48000:d=0.25",
            "-af", graph, "-f", "f32le", "-ac", "1", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        output, errors = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, errors.decode()
        values = struct.unpack(f"{len(output) // 4}f", output)
        values = values[2400:-2400]
        return math.sqrt(sum(v * v for v in values) / len(values)), max(abs(v) for v in values)

    flat = EqualizerSettings()
    reference, _ = await samples(flat)
    boosted, _ = await samples(replace(flat, gain_db=6))
    assert boosted / reference == pytest.approx(10 ** (6 / 20), rel=0.02)
    bass = EqualizerSettings((6, 0, 0, 0, 0))
    bass_reference, _ = await samples(flat, 60)
    bass_rms, _ = await samples(bass, 60)
    treble_rms, _ = await samples(bass, 12000)
    treble_reference, _ = await samples(flat, 12000)
    assert bass_rms / bass_reference > 1.9
    assert treble_rms / treble_reference < 1.05
    _, peak = await samples(replace(flat, gain_db=12), amplitude=0.9)
    assert 0.88 < peak <= 0.89126
    process = await asyncio.create_subprocess_exec(
        "mpv", "--no-config", "--no-terminal", "--no-video", "--ao=null", "--length=0.2",
        f"--af={METER_FILTER},@stumble_eq:lavfi=[{bass.filter_graph()}]",
        "av://lavfi:sine=frequency=440",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, errors = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 0, errors.decode()
