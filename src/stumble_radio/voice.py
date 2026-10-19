"""Local text-to-speech synthesis with Piper (https://github.com/OHF-Voice/piper1-gpl).

This module is the reusable announcements API. The app calls it in two places:

1. A background worker at startup downloads the preferred voice (once), warms
   the engine cache, and fills every command folder that has no clips yet.
2. ``app.announce`` generates a clip on demand when a command folder is empty.

The public surface is intentionally small:

    from stumble_radio.voice import Announcer, VoiceSettings

    announcer = Announcer(radio_dir / "piper")
    announcer.ensure_voice(settings.person)      # download + warm (idempotent)
    clip = announcer.speak("Focus time starting. See you.",
                           settings.person, library.folder("focus-start"))
    # clip is the WAV path; playback stays with AnnouncementPlayer.

Future announcements only need three things from here:

* ``Announcer.speak(text, person, dest_dir) -> Path`` renders speech to a WAV
  file (and a sibling ``.txt`` caption) without touching playback.
* ``Announcer.phrase_variants(command) -> tuple[str, ...]`` returns the spoken
  phrasings registered for a command folder; custom folders fall back to their
  command label.
* ``VoiceSettings`` persists which voice the user prefers, keyed by
  ``announcer_v1`` in the app metadata store.

Voices live under ``<radio data dir>/piper`` ( alan and jenny, both en_GB
medium ). Downloads come from the rhasspy/piper-voices Hugging Face repo and
are skipped when the files are already present.
"""

import hashlib
import shutil as _shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .models import clean
from .pomodoro import Pomodoro

VOICE_HOST = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
MAX_TTS_CHARS = 600
DOWNLOAD_TIMEOUT = 120

_UNSET = object()
_engine = _UNSET


def engine():
    """``piper.PiperVoice`` class, or ``None`` when the package is missing."""
    global _engine
    if _engine is _UNSET:
        try:
            from piper import PiperVoice as voice_class
        except ImportError:
            _engine = None
        else:
            _engine = voice_class
    return _engine

_loaded = {}


@dataclass
class VoiceSpec:
    person: str
    voice_id: str
    repo_dir: str


VOICES = {
    "alan": VoiceSpec("alan", "en_GB-alan-medium", "en/en_GB/alan/medium/"),
    "jenny": VoiceSpec("jenny", "en_GB-jenny_dioco-medium", "en/en_GB/jenny_dioco/medium/"),
}

PHRASES = {
    "focus-start": (
        "Focus time starting. See you when it is done.",
        "Ready to concentrate. I will tell you when focus ends.",
    ),
    "focus-ending": (
        "Focus wrapping up in a minute.",
        "Almost done. Tidy up your desk.",
    ),
    "short-break-start": (
        "Short break. Stretch your legs.",
        "Time for a short break.",
    ),
    "long-break-start": (
        "Long break. Step away for a while.",
        "Great work. Take a long break.",
    ),
    "break-ending": (
        "Break ending soon. Head back to the desk.",
        "Back to the desk in a minute.",
    ),
    "session-complete": (
        "Session complete. Well done.",
        "That is the session. Nice work.",
    ),
    "reminders/water": (
        "Time for a glass of water.",
        "Remember to hydrate.",
    ),
    "reminders/stretch": (
        "Stand up and stretch for a moment.",
        "Loosen up your shoulders.",
    ),
    "reminders/eyes": (
        "Rest your eyes for a moment.",
        "Look away from the screen briefly.",
    ),
}


class VoiceError(Exception):
    """Raised when synthesis or voice download cannot proceed."""


@dataclass
class VoiceSettings:
    """Which announcer voice the user prefers; stored as ``announcer_v1``."""

    person: str = "alan"

    def __post_init__(self):
        if self.person not in VOICES:
            raise ValueError("Announcer voice must be alan or jenny.")

    def snapshot(self) -> dict:
        return {"version": 1, "person": self.person}

    @classmethod
    def restore(cls, value):
        if not isinstance(value, dict):
            raise TypeError("Announcer settings must be saved as JSON objects.")
        if value and value.get("version") != 1:
            raise ValueError("Announcer settings need version 1.")
        return cls(person=value.get("person", "alan"))


class Announcer:
    """Downloads and caches Piper voices; renders text into WAV files."""

    def __init__(self, models_dir: Path):
        self.models_dir = Path(models_dir).expanduser().resolve()

    def ensure_voice(self, person: str):
        if person not in VOICES:
            raise VoiceError("Unknown announcer voice.")
        spec = VOICES[person]
        self.models_dir.mkdir(parents=True, exist_ok=True)
        for suffix in (".onnx", ".onnx.json"):
            dest = self.models_dir / f"{spec.voice_id}{suffix}"
            if not dest.exists():
                self._download(VOICE_HOST + spec.repo_dir + spec.voice_id + suffix, dest)
        return self._voice_model(person)

    def has_engine(self) -> bool:
        return engine() is not None

    def ready(self, person: str) -> bool:
        return person in VOICES and _loaded.get(person) is not None

    def phrase_variants(self, command: str) -> tuple:
        return PHRASES.get(command, (Pomodoro.command_label(command),))

    def speak(self, text: str, person: str, dest_dir: Path) -> Path:
        engine_class = engine()
        if engine_class is None:
            raise VoiceError("Voice announcements need the piper engine.")
        spoken = clean(text)
        if not spoken or len(spoken) > MAX_TTS_CHARS:
            raise VoiceError("Announcement texts are limited to 600 characters.")
        if person not in VOICES:
            raise VoiceError("Unknown announcer voice.")
        spec = VOICES[person]
        model = self._voice_model(person)
        if model is None:
            model = self.ensure_voice(person)
        dest = Path(dest_dir).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(f"{spec.voice_id}\x00{spoken}".encode()).hexdigest()[:8]
        wav = dest / f"tts-{digest}.wav"
        if wav.exists():
            return wav
        with wave.open(str(wav), "wb") as handle:
            model.synthesize_wav(spoken, handle)
        caption = wav.with_suffix(".txt")
        if not caption.exists():
            caption.write_text(spoken, encoding="utf-8")
        return wav

    def _voice_model(self, person: str):
        if person in _loaded:
            return _loaded[person]
        spec = VOICES[person]
        model = self.models_dir / f"{spec.voice_id}.onnx"
        if not model.exists():
            return None
        _loaded[person] = engine().load(model)
        return _loaded[person]

    @staticmethod
    def _download(url: str, dest: Path):
        try:
            with urlopen(Request(url), timeout=DOWNLOAD_TIMEOUT) as stream, dest.open("wb") as file:
                _shutil.copyfileobj(stream, file)
        except (URLError, OSError, TimeoutError, ValueError) as error:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise VoiceError(f"Could not download {dest.name}: {clean(str(error))}") from error
