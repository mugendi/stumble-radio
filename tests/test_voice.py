from pathlib import Path
from typing import ClassVar

import pytest

import stumble_radio.voice as voice_module
from stumble_radio.voice import Announcer, VoiceError, VoiceSettings


class FakeEngine:
    loads: ClassVar[list] = []
    synth: ClassVar[int] = 0

    @classmethod
    def load(cls, model_path):
        if not Path(model_path).exists():
            raise VoiceError("model file missing")
        cls.loads.append(str(model_path))
        return cls()

    def synthesize_wav(self, text, handle):
        FakeEngine.synth += 1
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x02" * 32)


@pytest.fixture(autouse=True)
def engine_patched(monkeypatch):
    monkeypatch.setattr(voice_module, "engine", lambda: FakeEngine)
    monkeypatch.setattr(voice_module, "_loaded", {})
    FakeEngine.loads.clear()
    FakeEngine.synth = 0
    return monkeypatch


def record_download(monkeypatch, downloads: list):
    def record(url, dest):
        downloads.append(dest.name)
        dest.write_bytes(b"weights")

    monkeypatch.setattr(voice_module.Announcer, "_download", staticmethod(record))


def test_ensure_voice_downloads_then_reuses(tmp_path, engine_patched):
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    announcer.ensure_voice("jenny")
    assert sorted(downloads) == [
        "en_GB-jenny_dioco-medium.onnx",
        "en_GB-jenny_dioco-medium.onnx.json",
    ]
    assert voice_module._loaded["jenny"] is not None
    downloads.clear()
    voice_module._loaded.pop("jenny")
    announcer.ensure_voice("jenny")
    assert downloads == []
    assert voice_module._loaded["jenny"] is not None


def test_ensure_voice_rejects_unknown_person(tmp_path, engine_patched):
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    with pytest.raises(VoiceError):
        announcer.ensure_voice("morgan")
    assert downloads == []


def test_speak_writes_wav_and_caption(tmp_path, engine_patched):
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    folder = tmp_path / "commands" / "focus-start"
    folder.mkdir(parents=True)
    clip = announcer.speak("Focus time starting.", "alan", folder)
    assert clip.exists()
    assert clip.suffix == ".wav" and clip.name.startswith("tts-")
    caption = clip.with_suffix(".txt")
    assert caption.read_text(encoding="utf-8") == "Focus time starting."
    FakeEngine.synth = 0
    again = announcer.speak("Focus time starting.", "alan", folder)
    assert again == clip
    assert FakeEngine.synth == 0


def test_speak_per_voice_names_differ(tmp_path, engine_patched):
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    folder = tmp_path / "commands" / "focus-start"
    folder.mkdir(parents=True)
    alan = announcer.speak("Hello there.", "alan", folder)
    jenny = announcer.speak("Hello there.", "jenny", folder)
    assert alan != jenny
    assert alan.exists() and jenny.exists()


def test_speak_validates_text_and_person(tmp_path, engine_patched):
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    folder = tmp_path / "commands" / "focus-start"
    folder.mkdir(parents=True)
    with pytest.raises(VoiceError):
        announcer.speak("word " * 130, "alan", folder)
    with pytest.raises(VoiceError):
        announcer.speak("", "alan", folder)
    with pytest.raises(VoiceError):
        announcer.speak("Lovely day.", "brook", folder)
    assert downloads == []


def test_speak_without_engine_hints_install(tmp_path, engine_patched):
    engine_patched.setattr(voice_module, "engine", lambda: None)
    announcer = Announcer(tmp_path / "piper")
    downloads: list[str] = []
    record_download(engine_patched, downloads)
    with pytest.raises(VoiceError):
        announcer.speak("No engine around.", "alan", tmp_path)
    assert downloads == []


def test_voice_settings_restore():
    assert VoiceSettings.restore({"version": 1, "person": "jenny"}).person == "jenny"
    assert VoiceSettings.restore({}).person == "alan"
    assert VoiceSettings(person="alan").snapshot() == {"version": 1, "person": "alan"}
    for bad in ({"version": 2}, {"version": 1, "person": "moh"}, "jenny", None):
        with pytest.raises((ValueError, TypeError)):
            VoiceSettings.restore(bad)


def test_phrase_variants_cover_standards():
    for command in voice_module.PHRASES:
        parts = Announcer("~").phrase_variants(command)
        assert len(parts) == 2
        assert all(part.strip() for part in parts)


def test_phrase_variants_custom_falls_back_to_label():
    assert Announcer("~").phrase_variants("reminders/coffee") == ("Coffee",)
