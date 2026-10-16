"""Global listening effects; stream metering and recording remain upstream."""

from dataclasses import dataclass

BAND_FREQUENCIES = (60, 250, 1000, 4000, 12000)
PRESETS = {
    "Flat": (0, 0, 0, 0, 0),
    "Bass boost": (6, 3, 0, 0, 0),
    "Speech": (-3, 0, 3, 3, -3),
    "Rock": (5, 3, -2, 3, 5),
    "Pop": (-1, 2, 4, 2, -1),
    "Jazz": (3, 1, -1, 2, 3),
    "Classical": (3, 2, -2, 2, 3),
}


@dataclass(frozen=True)
class EqualizerSettings:
    bands: tuple[int, ...] = (0, 0, 0, 0, 0)
    gain_db: int = 0
    enabled: bool = True

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Equalizer enabled must be true or false.")
        if not isinstance(self.bands, (list, tuple)) or len(self.bands) != 5:
            raise ValueError("Set all five equalizer bands.")
        if any(type(value) is not int or not -12 <= value <= 12 for value in self.bands):
            raise ValueError("Equalizer bands must be whole numbers from −12 to +12 dB.")
        if type(self.gain_db) is not int or not 0 <= self.gain_db <= 12:
            raise ValueError("Gain must be a whole number from 0 to +12 dB.")
        object.__setattr__(self, "bands", tuple(self.bands))

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.gain_db or any(self.bands))

    @property
    def preset(self) -> str:
        return next((name for name, bands in PRESETS.items() if bands == self.bands), "Custom")

    def filter_graph(self) -> str:
        if not self.active:
            return ""
        filters = ["aformat=sample_fmts=fltp"]
        filters.extend(
            f"equalizer=f={hz}:t=o:w=2:g={gain}:precision=f32"
            for hz, gain in zip(BAND_FREQUENCIES, self.bands)
        )
        filters.extend((
            f"volume={self.gain_db}dB:precision=float",
            "alimiter=limit=0.891250938:level=false:latency=true",
        ))
        return ",".join(filters)

    def snapshot(self) -> dict:
        return {"version": 1, "bands": list(self.bands), "gain_db": self.gain_db,
                "enabled": self.enabled}

    @classmethod
    def restore(cls, data: dict) -> "EqualizerSettings":
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported equalizer settings version.")
        return cls(bands=data["bands"], gain_db=data["gain_db"], enabled=data["enabled"])
